"""`mic-monitor` command: start / stop / status / toggle / run / list / config.

The background worker is launched fully detached with no inherited handles,
so a caller that captures this command's output (the tray app, a script)
returns immediately instead of blocking until the worker exits.

sounddevice is imported lazily: status/stop/toggle-off never load PortAudio.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid

from . import __version__, config
from .worker import add_settings_args, settings_from_args, settings_to_args

START_TIMEOUT = 5.0  # seconds to wait for the worker to report its devices


# --- process liveness ------------------------------------------------------

def pid_alive(pid: int) -> bool:
    """Is `pid` a live Python process? On Windows never use os.kill(pid, 0):
    it TERMINATES the target. The image-name check guards against PID reuse
    by an unrelated process; a reused PID that is also Python is accepted,
    which is good enough for a per-user utility."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
                return False
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return False
            return os.path.basename(buf.value).lower().startswith("python")
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_record() -> tuple[int, str] | None:
    """The PID file holds `<pid> <token>`: the PID we launched (on Windows in
    a venv that is a launcher whose child is the real worker, so PIDs cannot
    be matched) and a random token the worker echoes into its status file."""
    try:
        parts = config.pid_path().read_text(encoding="utf-8").split()
        pid = int(parts[0])
        token = parts[1] if len(parts) > 1 else ""
    except (OSError, ValueError, IndexError):
        return None
    return (pid, token) if pid_alive(pid) else None


def read_pid() -> int | None:
    rec = read_record()
    return rec[0] if rec else None


def read_status() -> dict | None:
    """The worker's status (device names etc.), only if it belongs to the
    launch recorded in the PID file."""
    rec = read_record()
    if not rec:
        return None
    try:
        st = json.loads(config.status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return st if isinstance(st, dict) and st.get("token") == rec[1] else None


def _clear_state() -> None:
    for p in (config.pid_path(), config.status_path()):
        try:
            p.unlink()
        except OSError:
            pass


# --- commands --------------------------------------------------------------

def worker_python() -> str:
    """The interpreter for the background worker. On Windows prefer the
    pythonw.exe next to python.exe: it is GUI-subsystem, so neither it nor
    the real interpreter a venv launcher spawns ever gets a console window.
    (A console python.exe started without a console allocates a new,
    visible one.)"""
    exe = sys.executable
    if sys.platform == "win32":
        base = os.path.basename(exe).lower()
        if base == "python.exe":
            w = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(w):
                return w
    return exe


def worker_command(settings: dict, python: str | None = None, token: str = "") -> list[str]:
    return [
        python or worker_python(), "-m", "mic_monitor.worker",
        "--log", str(config.log_path()),
        "--status-file", str(config.status_path()),
        "--token", token,
        *settings_to_args(settings),
    ]


def start(cli_settings: dict | None = None, remember: bool = True) -> str:
    """Start the background worker. Returns a one-line message. `remember`
    records "on" as the state to restore at the next login."""
    if remember:
        config.remember_state(True)
    pid = read_pid()
    if pid:
        return f"Already running (pid {pid})."
    settings = config.resolve(cli_settings or {}, config.load())
    config.state_dir().mkdir(parents=True, exist_ok=True)
    _clear_state()
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    if sys.platform == "win32":
        # CREATE_NO_WINDOW, not DETACHED_PROCESS: should the worker end up on
        # a console python.exe after all, it gets a hidden console instead
        # of allocating a visible one.
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    token = uuid.uuid4().hex
    proc = subprocess.Popen(worker_command(settings, token=token), **kwargs)
    config.pid_path().write_text(f"{proc.pid} {token}\n", encoding="utf-8")

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        st = read_status()
        if st:
            return f"Started (pid {proc.pid}): {st['in']}  ->  {st['out']}"
        if proc.poll() is not None:
            _clear_state()
            return "Failed to start:\n" + _log_tail() + f"\n(log: {config.log_path()})"
        time.sleep(0.1)
    return f"Started (pid {proc.pid}); still opening devices. Log: {config.log_path()}"


def stop(remember: bool = True) -> str:
    """Stop the worker. `remember` records "off" for the next login; the
    tray's Exit passes False so monitoring that was on comes back."""
    if remember:
        config.remember_state(False)
    pid = read_pid()
    if not pid:
        _clear_state()
        return "Not running."
    st = read_status()
    targets = [pid]
    if st and isinstance(st.get("pid"), int) and st["pid"] != pid:
        targets.append(st["pid"])  # the real worker behind a venv launcher
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)  # POSIX: handled signal. Windows: hard kill.
        except OSError:
            pass
    if sys.platform != "win32":
        deadline = time.monotonic() + 3.0
        while any(pid_alive(t) for t in targets) and time.monotonic() < deadline:
            time.sleep(0.05)
    _clear_state()
    return "Stopped."


def status() -> str:
    pid = read_pid()
    if not pid:
        return "Not running."
    st = read_status()
    if st and st.get("waiting"):
        return f"Running (pid {pid}), waiting for device: {st['waiting']}"
    if st:
        extra = f" (reopened {st['reopens']}x)" if st.get("reopens") else ""
        return f"Running (pid {pid}): {st['in']}  ->  {st['out']}{extra}"
    return f"Running (pid {pid}), still opening devices."


def is_running() -> bool:
    return read_pid() is not None


def toggle(cli_settings: dict | None = None) -> str:
    return stop() if is_running() else start(cli_settings)


def _log_tail(n: int = 8) -> str:
    try:
        lines = config.log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-n:]) if lines else "(empty log)"


def _config_cmd(args) -> str:
    values = settings_from_args(args)
    given = {k: v for k, v in values.items() if v is not None}
    for k in ("in", "out"):
        if given.get(k) == "":  # --in "" = back to the system default
            given[k] = None
    if args.reset:
        path = config.config_path()
        try:
            path.unlink()
        except OSError:
            pass
        return f"Config reset (removed {path})."
    if given:
        path = config.save(given)
        note = ""
        if is_running():
            note = "\nMonitoring is running with the old settings; restart it to apply."
        return f"Saved to {path}:\n" + _fmt(config.load()) + note
    return f"{config.config_path()}\n" + _fmt(config.load())


def _fmt(settings: dict) -> str:
    rows = []
    for k in config.KEYS:
        v = settings.get(k)
        if k in ("in", "out"):
            v = v if v else "(system default)"
        elif k == "samplerate":
            v = v if v else "(input device's rate)"
        rows.append(f"  {k:<10} {v}")
    return "\n".join(rows)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mic-monitor",
        description="Hear your microphone in your headphones with low latency. "
        "With no command, toggles monitoring on/off.",
    )
    ap.add_argument("--version", action="version", version=f"mic-monitor {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    for name, help_ in (
        ("start", "start monitoring in the background"),
        ("toggle", "start if stopped, stop if running (the default)"),
        ("run", "monitor in the foreground until Ctrl+C"),
    ):
        p = sub.add_parser(name, help=help_)
        add_settings_args(p)
    p = sub.add_parser("stop", help="stop monitoring")
    # For the installers: stop for an upgrade without changing whether the
    # tray turns monitoring back on at the next login.
    p.add_argument("--keep-state", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("status", help="show whether monitoring is running")
    sub.add_parser("list", help="list audio devices")
    p = sub.add_parser("config", help="show or save default settings")
    add_settings_args(p)
    p.add_argument("--reset", action="store_true", help="delete the saved config")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "toggle"
    if cmd == "start":
        print(start(settings_from_args(args)))
    elif cmd == "toggle":
        print(toggle(settings_from_args(args)))
    elif cmd == "stop":
        print(stop(remember=not args.keep_state))
    elif cmd == "status":
        print(status())
    elif cmd == "list":
        from .devices import describe_devices

        print(describe_devices())
    elif cmd == "config":
        print(_config_cmd(args))
    elif cmd == "run":
        from .worker import run_monitor

        if is_running():
            print("Background monitoring is already running; stop it first.")
            return 1
        settings = config.resolve(settings_from_args(args), config.load())
        print("Ctrl+C to stop.")
        return run_monitor(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
