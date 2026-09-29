"""Windows only: read the system default audio endpoints from Core Audio.

PortAudio snapshots the device list, defaults included, when it initializes,
so a default changed in Sound settings stays invisible to an open stream. The
worker polls these endpoint IDs instead and reopens when one changes; the
reopen re-initializes PortAudio, which then reports the new default.

Calls IMMDeviceEnumerator::GetDefaultAudioEndpoint through raw ctypes COM, so
there is nothing to install. The multimedia role is the one PortAudio's
WASAPI host API reports as its default.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("mic_monitor.winaudio is Windows only")

_ole = ctypes.OleDLL("ole32")  # HRESULT functions raise OSError on failure
_ole.CoUninitialize.restype = None
_ole.CoTaskMemFree.restype = None
_ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]

_CLSID_MMDEVICE_ENUMERATOR = "bcde0395-e52f-467c-8e3d-c4579291692e"
_IID_IMMDEVICE_ENUMERATOR = "a95664d2-9614-4f35-a746-de8db63617e6"
_CLSCTX_ALL = 0x17
_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: COM already set up another way
_E_NOTFOUND = -2147023728  # 0x80070490: no endpoint of that kind
_E_RENDER, _E_CAPTURE = 0, 1
_E_MULTIMEDIA = 1


def _guid(s: str) -> ctypes.Array:
    return (ctypes.c_ubyte * 16)(*uuid.UUID(s).bytes_le)


# vtable slots: IUnknown is 0-2 on both interfaces.
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
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


def default_endpoint_ids() -> tuple[str | None, str | None]:
    """(input, output) endpoint IDs of the current system defaults, None for
    a kind with no device. Raises OSError on a COM failure."""
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
            return _default_id(enum, _E_CAPTURE), _default_id(enum, _E_RENDER)
        finally:
            _release(enum)
    finally:
        if initialized:
            _ole.CoUninitialize()
