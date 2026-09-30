"""Start the tray icon at login.

Windows  HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run, value "mic-monitor".
         Task Manager's Startup tab can disable it; that shows here as off.
macOS    ~/Library/LaunchAgents/com.robworks.mic-monitor.tray.plist (RunAtLoad)
Linux    $XDG_CONFIG_HOME/autostart/mic-monitor-tray.desktop

The tray is started with --login, which turns monitoring back on only if it
was on when the user last logged off or exited (config.last_state_on).
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

NAME = "mic-monitor"
LOGIN_FLAG = "--login"
_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_LABEL = "com.robworks.mic-monitor.tray"


def tray_command() -> list[str]:
    """The command that starts this tray. Prefer the installed launcher
    (mic-monitor-tray[.exe]) the tray was started from, else run the module
    with this interpreter (pythonw on Windows, so no console)."""
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if os.path.basename(argv0).lower().startswith("mic-monitor-tray") and os.path.isfile(argv0):
        return [argv0, LOGIN_FLAG]
    exe = sys.executable
    if sys.platform == "win32" and os.path.basename(exe).lower() == "python.exe":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w
    return [exe, "-m", "mic_monitor.tray", LOGIN_FLAG]


# --- Windows ---------------------------------------------------------------

def _win_is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN) as k:
            winreg.QueryValueEx(k, NAME)
    except OSError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED) as k:
            data = winreg.QueryValueEx(k, NAME)[0]
        # First byte: 2 = enabled, 3 = disabled in Task Manager.
        return not (isinstance(data, bytes) and data[:1] == b"\x03")
    except OSError:
        return True


def _win_set(enabled: bool) -> None:
    import subprocess
    import winreg

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN) as k:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(tray_command()))
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, NAME)
        except OSError:
            pass
    # Clear a Task Manager "disabled" mark so the checkbox means what it says.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
    except OSError:
        pass


# --- macOS / Linux ---------------------------------------------------------

def _file_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "mic-monitor-tray.desktop"


def _file_content(cmd: list[str]) -> str:
    if sys.platform == "darwin":
        from xml.sax.saxutils import escape

        args = "".join(f"\n    <string>{escape(a)}</string>" for a in cmd)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            f"  <key>Label</key>\n  <string>{_LABEL}</string>\n"
            f"  <key>ProgramArguments</key>\n  <array>{args}\n  </array>\n"
            "  <key>RunAtLoad</key>\n  <true/>\n"
            "</dict>\n</plist>\n"
        )
    return (
        "[Desktop Entry]\nType=Application\nName=mic-monitor tray\n"
        f"Exec={shlex.join(cmd)}\nX-GNOME-Autostart-enabled=true\n"
    )


# --- public ----------------------------------------------------------------

def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_is_enabled()
    return _file_path().exists()


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        _win_set(enabled)
        return
    path = _file_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_file_content(tray_command()), encoding="utf-8")
    else:
        try:
            path.unlink()
        except OSError:
            pass
