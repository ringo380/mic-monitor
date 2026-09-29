"""Per-user config (saved defaults) and state (PID file, log, status) paths.

Config:  Windows %APPDATA%\\mic-monitor\\config.json
         POSIX   $XDG_CONFIG_HOME/mic-monitor/config.json (default ~/.config)
State:   Windows %LOCALAPPDATA%\\mic-monitor\\
         POSIX   $XDG_STATE_HOME/mic-monitor/ (default ~/.local/state)

Precedence for a setting: command-line flag > saved config > built-in default.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = "mic-monitor"

# None for a device means "the system default device of that kind".
DEFAULTS: dict[str, object] = {
    "in": None,
    "out": None,
    "gain": 1.0,
    "blocksize": 64,
    "samplerate": None,  # None = the input device's own rate
}
KEYS = tuple(DEFAULTS)


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP


def state_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP


def config_path() -> Path:
    return config_dir() / "config.json"


def pid_path() -> Path:
    return state_dir() / "worker.pid"


def log_path() -> Path:
    return state_dir() / "worker.log"


def status_path() -> Path:
    return state_dir() / "status.json"


def tray_log_path() -> Path:
    return state_dir() / "tray.log"


def load(path: Path | None = None) -> dict[str, object]:
    """Saved settings merged over DEFAULTS. Unknown keys are ignored; a
    missing or unreadable file yields the defaults."""
    path = path or config_path()
    values = dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if isinstance(data, dict):
        for k in KEYS:
            if k in data:
                values[k] = data[k]
    return values


def save(values: dict[str, object], path: Path | None = None) -> Path:
    """Write the known keys of `values` (merged over what is already saved)."""
    path = path or config_path()
    merged = load(path)
    for k in KEYS:
        if k in values:
            merged[k] = values[k]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return path


def resolve(cli_values: dict[str, object], saved: dict[str, object]) -> dict[str, object]:
    """Effective settings: a CLI value that is not None wins over the saved one."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in saved.items() if k in KEYS})
    out.update({k: v for k, v in cli_values.items() if k in KEYS and v is not None})
    return out
