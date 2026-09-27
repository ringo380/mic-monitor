# mic-monitor

Live microphone monitoring: route an input device to an output device with low
latency so you hear yourself in your headphones. Defaults to
**Blue Yeti -> Corsair headset**. Runs on macOS and Windows.

## Components

| File | Role |
|------|------|
| `yeti-monitor.py` | The worker, shared by both platforms. Uses [`sounddevice`](https://python-sounddevice.readthedocs.io/) to stream input -> output. On Windows it prefers the WASAPI host API (3 ms) over MME (90 ms). |
| `mic-monitor` | macOS zsh CLI wrapper: `start` / `stop` / `status` / `toggle` (default `toggle`). Backgrounds the worker and tracks a PID file. |
| `mic-monitor-app.py` | macOS menu-bar toggle via [`rumps`](https://github.com/jaredks/rumps). Drives the CLI so both stay in sync. |
| `mic-monitor.ps1` | Windows PowerShell CLI wrapper, same commands as `mic-monitor`. Runs the worker under `pythonw.exe` so no console window appears. |
| `mic-monitor-tray.py` | Windows system-tray toggle via [`pystray`](https://github.com/moses-palmer/pystray). Drives `mic-monitor.ps1`. |
| `install-windows.ps1` | Writes `.cmd` shims for the two Windows entry points into `~\.local\bin`. |
| `test_find_device.py` | Unit test for device selection (WASAPI preference, macOS fallback). |

## Install

### macOS

The scripts run in place from this repo. Put the two entry points on your `PATH`
by symlinking them into `~/.local/bin` (each resolves its own real path, so the
worker script is always found alongside it):

```sh
ln -sf "$PWD/mic-monitor"        ~/.local/bin/mic-monitor
ln -sf "$PWD/mic-monitor-app.py" ~/.local/bin/mic-monitor-app.py
```

### Windows

```powershell
pip install sounddevice pystray pillow
.\install-windows.ps1     # writes ~\.local\bin\mic-monitor.cmd and mic-monitor-tray.cmd
```

The shims point at the repo by absolute path; re-run the installer if the repo
moves. `~\.local\bin` must be on `PATH`.

## Usage

Same commands on both platforms (`mic-monitor` resolves to the zsh wrapper on
macOS and to the `.cmd` shim on Windows):

```sh
mic-monitor            # toggle on/off
mic-monitor start      # start monitoring
mic-monitor stop       # stop
mic-monitor status     # is it running?

# pass-through worker options (forwarded after `start`):
mic-monitor start --in Yeti --out CORSAIR --gain 1.0 --blocksize 256
python yeti-monitor.py --list   # list host APIs and audio devices
```

`--samplerate` defaults to the input device's own rate. WASAPI shared mode
rejects any other rate, so only override it if you know the endpoint accepts it.

Menu-bar / tray app:

```sh
mic-monitor-app.py     # macOS: emoji icon in the menu bar
mic-monitor-tray       # Windows: green disc = on, grey with red slash = off
```

Left-click the tray icon (or use its menu) to toggle. Quitting stops monitoring.
The icon polls every 3 s so it stays correct when toggled from a terminal.

Windows log: `%TEMP%\mic-monitor.log` (the worker writes it itself via `--log`).
Stopping is a hard kill of the worker, which is fine for a pass-through stream.

## Auto-recovery after headset sleep

A wireless headset that sleeps and wakes gets its Windows audio endpoint
re-created. An open stream keeps running into the old endpoint: status says
running, but you hear nothing. On Windows the worker polls the PnP arrival
timestamp of both endpoints every 2 s (cfgmgr32 via ctypes, no extra packages)
and reopens the stream when either changes. On every platform a stream that
goes inactive on its own is reopened too. The reopen happens in-process, so the
PID, the CLI and the tray app are unaffected. The log shows `Reopening: ...`
and `Reopened.` when it fires, or `waiting for device: ...` while the headset
is still off.

## Requirements

- macOS: Homebrew Python (`/opt/homebrew/bin/python3`), `pip install sounddevice rumps`
- Windows: Python 3 at `C:\Program Files\Python314\` (edit the path at the top of
  `mic-monitor.ps1` and in `install-windows.ps1` for a different install),
  `pip install sounddevice pystray pillow`

## Test

```sh
python -m pytest test_find_device.py
```
