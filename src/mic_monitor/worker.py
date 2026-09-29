"""The monitoring worker: streams an input device to an output device.

Run in the background by `mic-monitor start` (as `python -m mic_monitor.worker`)
or in the foreground by `mic-monitor run`.

Recovery: a wireless headset that sleeps and wakes gets its audio endpoint
re-created, and an open stream keeps running into the dead one (the process
looks fine, you hear nothing). The worker reopens its stream when the stream
goes inactive on its own (any platform) or, on Windows, when either
endpoint's PnP arrival timestamp changes. Reopening is in-process, so the
PID, the CLI and the tray are unaffected.

Following the default: a device left unset (no --in / --out) means the
system default, and on Windows the worker also reopens when that default is
changed in Sound settings, so monitoring moves to the new device. A device
given by name stays put.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from . import config
from .devices import PREFERRED_HOSTAPI, DeviceNotFound, resolve_device

STOP_POLL_SECONDS = 0.5  # keeps Ctrl+C responsive on Windows
ENDPOINT_CHECK_EVERY = 4  # PnP check every 4th poll = every 2 s
REOPEN_RETRY_SECONDS = 2.0


def log(msg: str) -> None:
    print(msg, flush=True)


def endpoints_changed(baseline: dict, current: dict) -> bool:
    """Did any watched endpoint re-arrive?

    Both maps go name -> arrival stamp (any comparable value) or None when
    not present. An endpoint with a baseline that is now present with a
    different stamp is a change. No baseline (None) = not watched. Still
    absent = not a change (a reopen would fail anyway)."""
    for name, before in baseline.items():
        now = current.get(name)
        if before is not None and now is not None and now != before:
            return True
    return False


def default_changed(baseline, current, follow) -> str | None:
    """Which followed default moved: "input", "output" or None.

    `baseline` and `current` are (input_id, output_id) with None for "no
    default" or "unknown"; `follow` is (follow_input, follow_output). A
    default that vanished is not a change: the stream going inactive covers
    that, and there is nothing to reopen onto."""
    for i, kind in enumerate(("input", "output")):
        if follow[i] and baseline[i] is not None and current[i] is not None:
            if current[i] != baseline[i]:
                return kind
    return None


def stream_channels(in_dev, out_dev) -> tuple[int, int]:
    """(input, output) channel counts: each device's own, capped at stereo.
    A mono mic into stereo headphones broadcasts to both ears; the input is
    never wider than the output, which numpy could not broadcast."""
    out_ch = min(int(out_dev["max_output_channels"]), 2)
    in_ch = min(int(in_dev["max_input_channels"]), out_ch)
    return in_ch, out_ch


def _is_wasapi(sd, dev) -> bool:
    return sd.query_hostapis(dev["hostapi"])["name"] == PREFERRED_HOSTAPI


def _default_ids():
    if sys.platform == "win32":
        from . import winaudio

        try:
            return winaudio.default_endpoint_ids()
        except OSError as e:  # a COM failure must not kill monitoring
            log(f"default device watch error: {e}")
    return (None, None)


def _default_snapshot(names):
    if sys.platform == "win32":
        from . import winpnp

        try:
            return winpnp.snapshot_endpoints(names)
        except OSError as e:  # a cfgmgr32 failure must not kill monitoring
            log(f"endpoint watch error: {e}")
    return {n: None for n in names}


class Monitor:
    """Owns the stream and the reopen logic.

    `settings` is a config-shaped dict (in, out, gain, blocksize, samplerate).
    `snapshot` and `defaults` are injectable so the reopen mechanics can be
    integration-tested without a real headset sleep or a settings change.
    `status_file` gets a small JSON written on every (re)open so the CLI and
    tray can show the device names."""

    def __init__(
        self,
        settings: dict,
        snapshot=_default_snapshot,
        status_file: Path | None = None,
        token: str = "",
        defaults=_default_ids,
    ):
        self.settings = settings
        self.snapshot = snapshot
        self.defaults = defaults
        # Unset device = system default, which is followed when it changes.
        self.follow = (not settings.get("in"), not settings.get("out"))
        self.status_file = status_file
        self.token = token  # echoed in the status file so the CLI knows it is ours
        self.stop = threading.Event()
        self.reopens = 0
        self.gain = float(settings.get("gain") or 1.0)
        self.names = ("", "")

    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr, flush=True)
        if self.gain != 1.0:
            outdata[:] = indata * self.gain
        else:
            outdata[:] = indata

    def open(self):
        """Resolve devices and open the stream. Raises DeviceNotFound if a
        device is missing and sounddevice.PortAudioError if it cannot open."""
        import sounddevice as sd

        in_idx = resolve_device(self.settings.get("in"), "input")
        out_idx = resolve_device(self.settings.get("out"), "output")
        in_dev, out_dev = sd.query_devices(in_idx), sd.query_devices(out_idx)
        # Follow the input device's rate unless the caller overrides.
        samplerate = int(self.settings.get("samplerate") or in_dev["default_samplerate"])
        blocksize = int(self.settings.get("blocksize") or 64)
        channels = stream_channels(in_dev, out_dev)
        extra = None
        # WASAPI shared mode rejects a rate that differs from an endpoint's
        # own; let the Windows audio engine convert when they differ (a
        # 44.1 kHz interface into a 48 kHz headset, say).
        rates = {samplerate, int(in_dev["default_samplerate"]), int(out_dev["default_samplerate"])}
        if len(rates) > 1 and _is_wasapi(sd, in_dev) and _is_wasapi(sd, out_dev):
            conv = sd.WasapiSettings(auto_convert=True)
            extra = (conv, conv)
        stream = sd.Stream(
            device=(in_idx, out_idx),
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="float32",
            channels=channels,
            latency="low",
            callback=self._callback,
            extra_settings=extra,
        )
        stream.start()
        names = (in_dev["name"], out_dev["name"])
        log(f"Monitoring: {names[0]}  ->  {names[1]}")
        log(
            f"gain={self.gain}  blocksize={blocksize}  samplerate={samplerate}  "
            f"channels={channels[0]}->{channels[1]}"
            + ("  (rate converted)" if extra else "")
        )
        self.names = names
        self._write_status(names, samplerate)
        return stream, names

    def _write_status(self, names, samplerate, waiting: str | None = None) -> None:
        """`waiting` = why a reopen is failing; the CLI and tray show it so
        they never report the last good devices as still monitoring."""
        if not self.status_file:
            return
        data = {
            "pid": os.getpid(),
            "token": self.token,
            "in": names[0],
            "out": names[1],
            "samplerate": samplerate,
            "reopens": self.reopens,
            "since": time.time(),
        }
        if waiting:
            data["waiting"] = waiting
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            self.status_file.write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            log(f"could not write status file: {e}")

    def _watch_until_change(self, stream, names):
        """Block until stop is requested or the stream needs reopening.
        Returns the reason string, or None when stopping."""
        baseline = self.snapshot(names)
        if all(v is None for v in baseline.values()):
            if sys.platform == "win32":
                log(
                    "endpoint watch: no PnP match for these device names; "
                    "auto-recovery on headset wake is disabled"
                )
            baseline = {}
        default_ids = self.defaults() if any(self.follow) else (None, None)
        tick = 0
        while not self.stop.wait(STOP_POLL_SECONDS):
            tick += 1
            if not stream.active:
                return "stream went inactive"
            if baseline and tick % ENDPOINT_CHECK_EVERY == 0:
                if endpoints_changed(baseline, self.snapshot(names)):
                    return "audio endpoint re-arrived (device slept/woke or was replugged)"
            if default_ids != (None, None) and tick % ENDPOINT_CHECK_EVERY == 0:
                kind = default_changed(default_ids, self.defaults(), self.follow)
                if kind:
                    return f"system default {kind} device changed"
        return None

    def run(self) -> None:
        stream, names = self.open()  # first open: a missing device is fatal
        try:
            while True:
                reason = self._watch_until_change(stream, names)
                stream.close()
                if reason is None:
                    return
                log(f"Reopening: {reason}")
                stream, names = self._reopen()
                if stream is None:
                    return
                self.reopens += 1
                log("Reopened.")
        finally:
            if stream is not None and not stream.closed:
                stream.close()

    def _reopen(self):
        """Refresh PortAudio's device table and retry the open until it works
        or stop is requested. Returns (stream, names) or (None, None)."""
        import sounddevice as sd

        waiting_logged = False
        while not self.stop.is_set():
            sd._terminate()
            sd._initialize()
            try:
                return self.open()
            except (DeviceNotFound, sd.PortAudioError) as e:
                if not waiting_logged:
                    log(f"waiting for device: {e}")
                    self._write_status(self.names, None, waiting=str(e))
                    waiting_logged = True
                self.stop.wait(REOPEN_RETRY_SECONDS)
        return None, None


def add_settings_args(ap: argparse.ArgumentParser) -> None:
    """Shared by the worker and the CLI's start/run/config commands."""
    ap.add_argument("--in", dest="in_", metavar="NAME", help="input device name substring")
    ap.add_argument("--out", metavar="NAME", help="output device name substring")
    ap.add_argument("--gain", type=float, help="output gain multiplier (default 1.0)")
    ap.add_argument("--blocksize", type=int, help="frames per block; lower = less latency (64)")
    ap.add_argument("--samplerate", type=int, help="sample rate (default: input device's own)")


def settings_from_args(args) -> dict:
    return {
        "in": args.in_,
        "out": args.out,
        "gain": args.gain,
        "blocksize": args.blocksize,
        "samplerate": args.samplerate,
    }


def settings_to_args(settings: dict) -> list[str]:
    """Inverse of settings_from_args, for building the worker command line."""
    out: list[str] = []
    for key, flag in (("in", "--in"), ("out", "--out"), ("gain", "--gain"),
                      ("blocksize", "--blocksize"), ("samplerate", "--samplerate")):
        v = settings.get(key)
        if v is not None:
            out += [flag, str(v)]
    return out


def run_monitor(settings: dict, status_file: Path | None = None, token: str = "") -> int:
    """Run until SIGINT/SIGTERM. Returns a process exit code."""
    mon = Monitor(settings, status_file=status_file, token=token)

    def request_stop(signum, frame):
        mon.stop.set()

    # Portable stop: signal.sigwait does not exist on Windows. Handlers set an
    # Event and the timed wait loop keeps Ctrl+C responsive there.
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        mon.run()
    except DeviceNotFound as e:
        log(f"error: {e}. Run `mic-monitor list` to see devices.")
        return 2
    log("Stopped.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mic_monitor.worker")
    add_settings_args(ap)
    ap.add_argument("--log", metavar="FILE", help="write stdout+stderr to FILE")
    ap.add_argument("--status-file", metavar="FILE", help="write device names as JSON here")
    ap.add_argument("--token", default="", help="launch token echoed into the status file")
    args = ap.parse_args(argv)

    if args.log:
        # Started detached with no inherited handles; the worker owns its log.
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        logf = open(args.log, "w", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = logf

    settings = config.resolve(settings_from_args(args), {})
    status_file = Path(args.status_file) if args.status_file else None
    return run_monitor(settings, status_file, args.token)


if __name__ == "__main__":
    raise SystemExit(main())
