#!/opt/homebrew/bin/python3
"""Live mic monitor: route an input device to an output device with low latency.

Default: Yeti mic -> Corsair headset, so you hear yourself in the headphones.
Runs on macOS (Core Audio) and Windows (prefers the WASAPI host API).

Recovery: a wireless headset that sleeps and wakes gets its Windows audio
endpoint re-created, and the open stream keeps running into the dead one
(status says running, you hear nothing). On Windows the worker watches the
PnP arrival timestamp of both endpoints and reopens the stream when either
changes. On every platform a stream that goes inactive on its own is reopened.
Reopening happens in-process, so the PID, PID file, CLI and tray app are
unaffected.
"""
import argparse
import signal
import sys
import threading
import time

import sounddevice as sd

# PortAudio on Windows lists every endpoint once per host API. Only WASAPI is
# low latency (3 ms here vs 90 ms for MME), so prefer it when it is present.
PREFERRED_HOSTAPI = "Windows WASAPI"

STOP_POLL_SECONDS = 0.5      # keeps Ctrl+C responsive on Windows
ENDPOINT_CHECK_EVERY = 4     # PnP check every 4th poll = every 2 s
REOPEN_RETRY_SECONDS = 2.0


def log(msg):
    print(msg, flush=True)


def find_device(name, kind, devices=None, hostapis=None):
    """kind: 'input' or 'output'. Returns the index of the best device whose
    name contains `name` (case-insensitive) and has channels of that kind.

    Preference order: a device on PREFERRED_HOSTAPI, else the first match.
    `devices` / `hostapis` default to the live PortAudio lists; they are
    parameters so the selection logic can be tested without hardware.
    """
    if devices is None:
        devices = sd.query_devices()
    if hostapis is None:
        hostapis = sd.query_hostapis()
    want = name.lower()
    chan_key = "max_input_channels" if kind == "input" else "max_output_channels"
    matches = [
        i for i, d in enumerate(devices)
        if want in d["name"].lower() and d[chan_key] > 0
    ]
    if not matches:
        raise SystemExit(f"No {kind} device matching '{name}'. Run with --list to see devices.")
    for i in matches:
        if hostapis[devices[i]["hostapi"]]["name"] == PREFERRED_HOSTAPI:
            return i
    return matches[0]


# --- Windows endpoint arrival watch (cfgmgr32 via ctypes, no dependencies) ---

def endpoints_changed(baseline, current):
    """Pure decision: did any watched endpoint re-arrive?

    Both args map endpoint name -> arrival timestamp (any comparable value)
    or None when the endpoint is not present. Changed means an endpoint that
    had a baseline is now present with a different arrival value. An endpoint
    with no baseline (None) is not watched; a still-absent endpoint is not a
    change (the reopen would fail anyway).
    """
    for name, before in baseline.items():
        now = current.get(name)
        if before is not None and now is not None and now != before:
            return True
    return False


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import uuid

    _cm = ctypes.WinDLL("cfgmgr32")

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class _DEVPROPKEY(ctypes.Structure):
        _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]

    def _guid(s):
        u = uuid.UUID(s)
        return _GUID(u.time_low, u.time_mid, u.time_hi_version,
                     (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    _DEVPKEY_NAME = _DEVPROPKEY(_guid("b725f130-47ef-101a-a5f1-02608c9eebac"), 10)
    _DEVPKEY_LAST_ARRIVAL = _DEVPROPKEY(_guid("83da6326-97a6-4088-9453-a1923f573b29"), 102)
    _CM_GETIDLIST_FILTER_ENUMERATOR = 0x1
    _CR_SUCCESS = 0

    def _devnode_prop(dn, key):
        ptype = wintypes.ULONG()
        size = wintypes.ULONG(0)
        _cm.CM_Get_DevNode_PropertyW(dn, ctypes.byref(key), ctypes.byref(ptype),
                                     None, ctypes.byref(size), 0)
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        cr = _cm.CM_Get_DevNode_PropertyW(dn, ctypes.byref(key), ctypes.byref(ptype),
                                          buf, ctypes.byref(size), 0)
        return buf.raw[:size.value] if cr == _CR_SUCCESS else None

    def snapshot_endpoints(names):
        """Map each name in `names` -> raw arrival FILETIME (as int) of the
        audio endpoint with exactly that PnP name, or None if not present.
        Enumerates SWD\\MMDEVAPI fresh every call: endpoint GUIDs can be
        re-created, so an instance ID must never be cached."""
        result = {n: None for n in names}
        try:
            size = wintypes.ULONG()
            if _cm.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "SWD",
                                               _CM_GETIDLIST_FILTER_ENUMERATOR) != _CR_SUCCESS:
                return result
            buf = ctypes.create_unicode_buffer(size.value)
            if _cm.CM_Get_Device_ID_ListW("SWD", buf, size.value,
                                          _CM_GETIDLIST_FILTER_ENUMERATOR) != _CR_SUCCESS:
                return result
            for iid in buf[:size.value].split("\0"):
                if "MMDEVAPI" not in iid.upper():
                    continue
                dn = wintypes.DWORD()
                if _cm.CM_Locate_DevNodeW(ctypes.byref(dn), iid, 0) != _CR_SUCCESS:
                    continue
                raw = _devnode_prop(dn.value, _DEVPKEY_NAME)
                if not raw:
                    continue
                name = raw.decode("utf-16-le").rstrip("\0")
                if name in result:
                    arrival = _devnode_prop(dn.value, _DEVPKEY_LAST_ARRIVAL)
                    result[name] = int.from_bytes(arrival[:8], "little") if arrival else None
        except OSError as e:  # a cfgmgr32 call failing must not kill monitoring
            log(f"endpoint watch error: {e}")
        return result
else:
    def snapshot_endpoints(names):
        return {n: None for n in names}


class Monitor:
    """Owns the stream and the reopen logic. `snapshot` is injectable so the
    reopen mechanics can be integration-tested without a real headset sleep."""

    def __init__(self, inp, out, gain, blocksize, samplerate, snapshot=snapshot_endpoints):
        self.inp, self.out, self.gain = inp, out, gain
        self.blocksize, self.samplerate_arg = blocksize, samplerate
        self.snapshot = snapshot
        self.stop = threading.Event()
        self.reopens = 0

    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr, flush=True)
        if self.gain != 1.0:
            outdata[:] = indata * self.gain
        else:
            outdata[:] = indata

    def open(self):
        """Resolve devices and open the stream. Raises SystemExit if a device
        is missing and sd.PortAudioError if it cannot be opened."""
        in_idx = find_device(self.inp, "input")
        out_idx = find_device(self.out, "output")
        in_dev, out_dev = sd.query_devices(in_idx), sd.query_devices(out_idx)
        # WASAPI shared mode rejects a rate that differs from the endpoint's
        # own, so follow the input device unless the caller overrides.
        samplerate = self.samplerate_arg or int(in_dev["default_samplerate"])
        stream = sd.Stream(
            device=(in_idx, out_idx), samplerate=samplerate, blocksize=self.blocksize,
            dtype="float32", channels=2, latency="low", callback=self._callback,
        )
        stream.start()
        names = (in_dev["name"], out_dev["name"])
        log(f"Monitoring: {names[0]}  ->  {names[1]}")
        log(f"gain={self.gain}  blocksize={self.blocksize}  sr={samplerate}")
        return stream, names

    def _watch_until_change(self, stream, names):
        """Block until stop is requested or the stream needs reopening.
        Returns the reason string, or None when stopping."""
        baseline = self.snapshot(names)
        if all(v is None for v in baseline.values()):
            if sys.platform == "win32":
                log("endpoint watch: no PnP match for these device names; "
                    "auto-recovery on headset wake is disabled")
            baseline = {}
        tick = 0
        while not self.stop.wait(STOP_POLL_SECONDS):
            tick += 1
            if not stream.active:
                return "stream went inactive"
            if baseline and tick % ENDPOINT_CHECK_EVERY == 0:
                if endpoints_changed(baseline, self.snapshot(names)):
                    return "audio endpoint re-arrived (device slept/woke or was replugged)"
        return None

    def run(self):
        stream, names = self.open()          # first open: a missing device is fatal, as before
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
        waiting_logged = False
        while not self.stop.is_set():
            sd._terminate()
            sd._initialize()
            try:
                return self.open()
            except (SystemExit, sd.PortAudioError) as e:
                if not waiting_logged:
                    log(f"waiting for device: {e}")
                    waiting_logged = True
                self.stop.wait(REOPEN_RETRY_SECONDS)
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="Yeti", help="input device name substring")
    ap.add_argument("--out", dest="out", default="CORSAIR", help="output device name substring")
    ap.add_argument("--gain", type=float, default=1.0, help="output gain multiplier")
    ap.add_argument("--blocksize", type=int, default=256, help="frames/block (lower=less latency)")
    ap.add_argument("--samplerate", type=int, default=None,
                    help="sample rate (default: the input device's own rate)")
    ap.add_argument("--list", action="store_true", help="list devices and exit")
    ap.add_argument("--log", default=None, metavar="FILE",
                    help="write stdout+stderr to FILE (used by the Windows wrapper)")
    args = ap.parse_args()

    if args.log:
        # The Windows wrapper launches us under pythonw with NO redirected
        # handles: if it redirected, the worker would inherit the caller's
        # capture pipe and every `subprocess.run(..., capture_output=True)`
        # that started monitoring would block until the worker exited.
        logf = open(args.log, "w", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = logf

    if args.list:
        print(sd.query_hostapis())
        print(sd.query_devices())
        return

    mon = Monitor(args.inp, args.out, args.gain, args.blocksize, args.samplerate)

    # Portable stop signal: signal.sigwait does not exist on Windows. Handlers
    # set an Event; the timed wait loop keeps Ctrl+C responsive on Windows.
    def request_stop(signum, frame):
        mon.stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    log("Ctrl+C to stop.")
    mon.run()
    log("\nStopped.")


if __name__ == "__main__":
    main()
