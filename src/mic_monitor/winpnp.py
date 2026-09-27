"""Windows only: read audio endpoint arrival timestamps from the PnP tree.

A wireless headset that sleeps and wakes gets its audio endpoint re-created.
DEVPKEY_Device_LastArrivalDate changes when that happens, which is the signal
the worker uses to reopen its stream. Uses cfgmgr32 through ctypes, the same
API PowerShell's Get-PnpDeviceProperty calls, so there is nothing to install.

Endpoint instance IDs (SWD\\MMDEVAPI\\...) can themselves be re-created, so
every call enumerates afresh and matches by name; nothing is cached.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("mic_monitor.winpnp is Windows only")

_cm = ctypes.WinDLL("cfgmgr32")


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


def _guid(s: str) -> _GUID:
    u = uuid.UUID(s)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


_DEVPKEY_NAME = _DEVPROPKEY(_guid("b725f130-47ef-101a-a5f1-02608c9eebac"), 10)
_DEVPKEY_LAST_ARRIVAL = _DEVPROPKEY(_guid("83da6326-97a6-4088-9453-a1923f573b29"), 102)
_CM_GETIDLIST_FILTER_ENUMERATOR = 0x1
_CR_SUCCESS = 0

_cm.CM_Get_Device_ID_List_SizeW.argtypes = [
    ctypes.POINTER(wintypes.ULONG),
    wintypes.LPCWSTR,
    wintypes.ULONG,
]
_cm.CM_Get_Device_ID_ListW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.ULONG,
    wintypes.ULONG,
]
_cm.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR, wintypes.ULONG]
_cm.CM_Get_DevNode_PropertyW.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(_DEVPROPKEY),
    ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.ULONG),
    wintypes.ULONG,
]


def _devnode_prop(dn: int, key: _DEVPROPKEY) -> bytes | None:
    ptype = wintypes.ULONG()
    size = wintypes.ULONG(0)
    _cm.CM_Get_DevNode_PropertyW(
        dn, ctypes.byref(key), ctypes.byref(ptype), None, ctypes.byref(size), 0
    )
    if size.value == 0:
        return None
    buf = ctypes.create_string_buffer(size.value)
    cr = _cm.CM_Get_DevNode_PropertyW(
        dn, ctypes.byref(key), ctypes.byref(ptype), buf, ctypes.byref(size), 0
    )
    return buf.raw[: size.value] if cr == _CR_SUCCESS else None


def _endpoint_ids() -> list[str]:
    size = wintypes.ULONG()
    if _cm.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "SWD", _CM_GETIDLIST_FILTER_ENUMERATOR):
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    if _cm.CM_Get_Device_ID_ListW("SWD", buf, size.value, _CM_GETIDLIST_FILTER_ENUMERATOR):
        return []
    return [s for s in buf[: size.value].split("\0") if "MMDEVAPI" in s.upper()]


def snapshot_endpoints(names) -> dict[str, int | None]:
    """Map each name -> arrival FILETIME (int) of the audio endpoint with
    exactly that PnP name, or None when it is not present right now."""
    result: dict[str, int | None] = {n: None for n in names}
    for iid in _endpoint_ids():
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
    return result
