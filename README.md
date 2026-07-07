# mic-monitor

Live microphone monitoring for macOS: route an input device to an output device
with low latency so you hear yourself in your headphones. Defaults to
**Blue Yeti -> Corsair headset**.

## Components

| File | Role |
|------|------|
| `mic-monitor` | zsh CLI wrapper: `start` / `stop` / `status` / `toggle` (default `toggle`). Backgrounds the worker and tracks a PID file. |
| `yeti-monitor.py` | The worker. Uses [`sounddevice`](https://python-sounddevice.readthedocs.io/) to stream input -> output. |
| `mic-monitor-app.py` | Menu-bar toggle (🎙️/🔇) via [`rumps`](https://github.com/jaredks/rumps). Drives the CLI so both stay in sync. |

## Install

The scripts run in place from this repo. Put the two entry points on your `PATH`
by symlinking them into `~/.local/bin` (each resolves its own real path, so the
worker script is always found alongside it):

```sh
ln -sf "$PWD/mic-monitor"        ~/.local/bin/mic-monitor
ln -sf "$PWD/mic-monitor-app.py" ~/.local/bin/mic-monitor-app.py
```

## Usage

```sh
mic-monitor            # toggle on/off
mic-monitor start      # start monitoring
mic-monitor stop       # stop
mic-monitor status     # is it running?

# pass-through worker options (forwarded after `start`):
mic-monitor start --in Yeti --out CORSAIR --gain 1.0 --blocksize 256
yeti-monitor.py --list # list available audio devices
```

Menu-bar app:

```sh
mic-monitor-app.py     # 🎙️ = on, 🔇 = off; quitting stops monitoring
```

## Requirements

- macOS, Homebrew Python (`/opt/homebrew/bin/python3`)
- `pip install sounddevice rumps`
