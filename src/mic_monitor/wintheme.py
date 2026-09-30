"""Windows only: make the tray's native popup menus follow the system theme.

Win32 menus are drawn light unless the process opts in to dark mode, which
Windows only exposes through uxtheme.dll ordinals (the same ones Explorer,
Notepad++ and Windows Terminal use; stable since Windows 10 1903):

    135  SetPreferredAppMode(mode)   0 default, 1 allow dark, 2 force dark, 3 force light
    104  RefreshImmersiveColorPolicyState()
    136  FlushMenuThemes()

The mode is forced to match the "app mode" setting (Settings > Personalization
> Colors), and `apply()` is called again when that setting changes so an open
tray follows along. Any failure leaves the default light menus.
"""

from __future__ import annotations

import ctypes
import sys
import winreg

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("mic_monitor.wintheme is Windows only")

_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_FORCE_DARK, _FORCE_LIGHT = 2, 3


def apps_use_dark() -> bool:
    """True when Windows is set to dark mode for apps."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False  # no value = light, the Windows default


def apply(dark: bool | None = None) -> bool | None:
    """Set this process's menus to dark or light (default: the system
    setting). Returns the mode applied, or None when uxtheme refused."""
    if dark is None:
        dark = apps_use_dark()
    try:
        ux = ctypes.WinDLL("uxtheme")
        set_mode = ux[135]
        set_mode.argtypes = [ctypes.c_int]
        set_mode.restype = ctypes.c_int
        set_mode(_FORCE_DARK if dark else _FORCE_LIGHT)
        ux[104]()
        ux[136]()
    except (OSError, AttributeError):
        return None
    return dark
