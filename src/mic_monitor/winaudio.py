"""Windows only: read audio endpoints and the system defaults from Core Audio.

PortAudio snapshots the device list, defaults included, when it initializes,
so a default changed in Sound settings stays invisible to an open stream. The
worker polls these endpoint IDs instead and reopens when one changes; the
reopen re-initializes PortAudio, which then reports the new default.

Calls IMMDeviceEnumerator::GetDefaultAudioEndpoint through raw ctypes COM, so
there is nothing to install. The multimedia role is the one PortAudio's
WASAPI host API reports as its default.

`active_endpoint_names` lists the endpoints the way PortAudio's WASAPI host
API names them (the endpoint friendly name). The tray uses it for its device
menus: it is cheap enough to poll and always current, where PortAudio's list
is frozen at initialization.
"""
from __future__ import annotations

import ctypes
import sys
import uuid
from contextlib import contextmanager
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("mic_monitor.winaudio is Windows only")

_ole = ctypes.OleDLL("ole32")  # HRESULT functions raise OSError on failure
_ole.CoUninitialize.restype = None
_ole.CoTaskMemFree.restype = None
_ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole.PropVariantClear.argtypes = [ctypes.c_void_p]

_CLSID_MMDEVICE_ENUMERATOR = "bcde0395-e52f-467c-8e3d-c4579291692e"
_IID_IMMDEVICE_ENUMERATOR = "a95664d2-9614-4f35-a746-de8db63617e6"
_CLSCTX_ALL = 0x17
_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: COM already set up another way
_E_NOTFOUND = -2147023728  # 0x80070490: no endpoint of that kind
_E_RENDER, _E_CAPTURE = 0, 1
_E_MULTIMEDIA = 1
_DEVICE_STATE_ACTIVE = 0x1
_STGM_READ = 0
_VT_LPWSTR = 31
_PKEY_FRIENDLY_NAME = ("a45c254e-df1c-4efd-8020-67d146a850e0", 14)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", ctypes.c_ubyte * 16), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    # vt, 3 reserved words, then a union; only the pointer member is read.
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("r1", ctypes.c_ushort),
        ("r2", ctypes.c_ushort),
        ("r3", ctypes.c_ushort),
        ("ptr", ctypes.c_void_p),
        ("pad", ctypes.c_void_p),
    ]


def _guid(s: str) -> ctypes.Array:
    return (ctypes.c_ubyte * 16)(*uuid.UUID(s).bytes_le)


# vtable slots: IUnknown is 0-2 on every interface.
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_EnumAudioEndpoints = ctypes.WINFUNCTYPE(  # IMMDeviceEnumerator slot 3
    ctypes.HRESULT, ctypes.c_void_p, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
)
_GetCount = ctypes.WINFUNCTYPE(  # IMMDeviceCollection slot 3
    ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT)
)
_Item = ctypes.WINFUNCTYPE(  # IMMDeviceCollection slot 4
    ctypes.HRESULT, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)
)
_OpenPropertyStore = ctypes.WINFUNCTYPE(  # IMMDevice slot 4
    ctypes.HRESULT, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
)
_GetValue = ctypes.WINFUNCTYPE(  # IPropertyStore slot 5
    ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
)
_GetDefaultAudioEndpoint = ctypes.WINFUNCTYPE(  # IMMDeviceEnumerator slot 4
    ctypes.HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
)
_GetId = ctypes.WINFUNCTYPE(  # IMMDevice slot 5
    ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
)


def _method(obj: ctypes.c_void_p, slot: int, proto):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return proto(vtbl[slot])


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        _method(obj, 2, _Release)(obj)


def _default_id(enum: ctypes.c_void_p, flow: int) -> str | None:
    dev = ctypes.c_void_p()
    try:
        _method(enum, 4, _GetDefaultAudioEndpoint)(enum, flow, _E_MULTIMEDIA, ctypes.byref(dev))
    except OSError as e:
        if e.winerror == _E_NOTFOUND:
            return None
        raise
    try:
        raw = ctypes.c_void_p()
        _method(dev, 5, _GetId)(dev, ctypes.byref(raw))
        try:
            return ctypes.wstring_at(raw.value)
        finally:
            _ole.CoTaskMemFree(raw)
    finally:
        _release(dev)


@contextmanager
def _enumerator():
    """COM set up on this thread plus an IMMDeviceEnumerator, released after."""
    try:
        _ole.CoInitializeEx(None, _COINIT_MULTITHREADED)
        initialized = True
    except OSError as e:
        if e.winerror != _RPC_E_CHANGED_MODE:
            raise
        initialized = False  # already initialized as STA; usable as is
    try:
        enum = ctypes.c_void_p()
        _ole.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_MMDEVICE_ENUMERATOR)), None, _CLSCTX_ALL,
            ctypes.byref(_guid(_IID_IMMDEVICE_ENUMERATOR)), ctypes.byref(enum),
        )
        try:
            yield enum
        finally:
            _release(enum)
    finally:
        if initialized:
            _ole.CoUninitialize()


def default_endpoint_ids() -> tuple[str | None, str | None]:
    """(input, output) endpoint IDs of the current system defaults, None for
    a kind with no device. Raises OSError on a COM failure."""
    with _enumerator() as enum:
        return _default_id(enum, _E_CAPTURE), _default_id(enum, _E_RENDER)


def _friendly_name(dev: ctypes.c_void_p) -> str | None:
    store = ctypes.c_void_p()
    _method(dev, 4, _OpenPropertyStore)(dev, _STGM_READ, ctypes.byref(store))
    try:
        key = _PROPERTYKEY(_guid(_PKEY_FRIENDLY_NAME[0]), _PKEY_FRIENDLY_NAME[1])
        var = _PROPVARIANT()
        _method(store, 5, _GetValue)(store, ctypes.byref(key), ctypes.byref(var))
        try:
            return ctypes.wstring_at(var.ptr) if var.vt == _VT_LPWSTR and var.ptr else None
        finally:
            _ole.PropVariantClear(ctypes.byref(var))
    finally:
        _release(store)


def active_endpoint_names(kind: str) -> list[str]:
    """Friendly names of the active "input" or "output" endpoints, sorted.
    Raises OSError on a COM failure."""
    flow = _E_CAPTURE if kind == "input" else _E_RENDER
    names = []
    with _enumerator() as enum:
        coll = ctypes.c_void_p()
        _method(enum, 3, _EnumAudioEndpoints)(enum, flow, _DEVICE_STATE_ACTIVE, ctypes.byref(coll))
        try:
            count = wintypes.UINT()
            _method(coll, 3, _GetCount)(coll, ctypes.byref(count))
            for i in range(count.value):
                dev = ctypes.c_void_p()
                _method(coll, 4, _Item)(coll, i, ctypes.byref(dev))
                try:
                    name = _friendly_name(dev)
                finally:
                    _release(dev)
                if name:
                    names.append(name)
        finally:
            _release(coll)
    return sorted(names, key=str.lower)
