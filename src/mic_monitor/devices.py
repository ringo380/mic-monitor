"""Audio device selection on top of sounddevice / PortAudio.

PortAudio on Windows lists every endpoint once per host API (MME, DirectSound,
WASAPI, WDM-KS). Only WASAPI is low latency (about 3 ms here versus 90 ms for
MME), so both name matching and the "system default" fall back prefer it.
On macOS and Linux there is one host API and the preference is a no-op.

Every function takes optional `devices` / `hostapis` lists so the selection
logic is testable without hardware; they default to the live PortAudio lists.
"""

from __future__ import annotations

PREFERRED_HOSTAPI = "Windows WASAPI"


class DeviceNotFound(LookupError):
    pass


def _live():
    import sounddevice as sd

    return list(sd.query_devices()), list(sd.query_hostapis())


def _chan_key(kind: str) -> str:
    if kind not in ("input", "output"):
        raise ValueError(kind)
    return "max_input_channels" if kind == "input" else "max_output_channels"


def find_device(name: str, kind: str, devices=None, hostapis=None) -> int:
    """Index of the best device whose name contains `name` (case-insensitive)
    and has channels of `kind`. A PREFERRED_HOSTAPI match wins, else the
    first match. Raises DeviceNotFound."""
    if devices is None or hostapis is None:
        devices, hostapis = _live()
    want = name.lower()
    key = _chan_key(kind)
    matches = [i for i, d in enumerate(devices) if want in d["name"].lower() and d[key] > 0]
    if not matches:
        raise DeviceNotFound(f"no {kind} device matching '{name}'")
    for i in matches:
        if hostapis[devices[i]["hostapi"]]["name"] == PREFERRED_HOSTAPI:
            return i
    return matches[0]


def default_device(kind: str, devices=None, hostapis=None, pa_default=None) -> int:
    """Index of the system default device of `kind`.

    On Windows, PortAudio's own default is the MME one, so use the WASAPI
    host API's default instead. Elsewhere use PortAudio's default
    (`pa_default` = (input_index, output_index), read from sounddevice when
    not given). Raises DeviceNotFound when there is no default."""
    if devices is None or hostapis is None:
        devices, hostapis = _live()
    slot = "default_input_device" if kind == "input" else "default_output_device"
    _chan_key(kind)
    for api in hostapis:
        if api["name"] == PREFERRED_HOSTAPI and api[slot] is not None and api[slot] >= 0:
            return api[slot]
    if pa_default is None:
        import sounddevice as sd

        pa_default = tuple(sd.default.device)
    idx = pa_default[0] if kind == "input" else pa_default[1]
    if idx is None or idx < 0 or idx >= len(devices):
        raise DeviceNotFound(f"no default {kind} device")
    return idx


def resolve_device(name, kind: str, devices=None, hostapis=None) -> int:
    """`name` None or empty = system default, otherwise a name substring."""
    if devices is None or hostapis is None:
        devices, hostapis = _live()
    if not name:
        return default_device(kind, devices, hostapis)
    return find_device(name, kind, devices, hostapis)


def describe_devices() -> str:
    """Human-readable device table for `mic-monitor list`."""
    import sounddevice as sd

    apis = sd.query_hostapis()
    lines = ["Host APIs:"]
    for i, a in enumerate(apis):
        lines.append(
            f"  {i}: {a['name']}  (default in={a['default_input_device']}, "
            f"out={a['default_output_device']})"
        )
    lines.append("")
    lines.append("Devices  (idx  in/out channels  host API  name):")
    for i, d in enumerate(sd.query_devices()):
        lines.append(
            f"  {i:3d}  {d['max_input_channels']:2d}/{d['max_output_channels']:<2d}  "
            f"{apis[d['hostapi']]['name']:<20} {d['name']}"
        )
    lines.append("")
    lines.append("Use a distinctive part of a name with --in / --out, e.g. --in Yeti.")
    return "\n".join(lines)
