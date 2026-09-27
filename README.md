# mic-monitor

Hear your own microphone in your headphones with low latency.

Useful when you record or stream with a USB microphone and closed headphones
and want to hear yourself (sidetone) without the delay that Windows' "Listen
to this device" adds. It streams an input device straight to an output device
through PortAudio with a small buffer, and it survives a wireless headset
going to sleep and waking up.

- **CLI**: `mic-monitor` toggles monitoring on and off in the background.
- **Tray icon**: `mic-monitor-tray` gives you a click-to-toggle icon.
- **Any devices**: defaults to the system default input and output. Pick
  others by a part of their name.
- **Recovery**: reopens the stream by itself when a headset sleeps and wakes.

Works on Windows. macOS and Linux are supported by the code but not yet tested
by the author, see [Platform notes](#platform-notes).

## Install

Requires Python 3.10 or newer. [pipx](https://pipx.pypa.io/) keeps the tool
in its own environment and puts the commands on your PATH:

```sh
pipx install git+https://github.com/ringo380/mic-monitor
```

Without pipx, `pip install git+https://github.com/ringo380/mic-monitor` works
too; make sure your Python scripts directory is on PATH.

Linux also needs the PortAudio library, for example `sudo apt install libportaudio2`.

## Use

```sh
mic-monitor              # toggle: start if stopped, stop if running
mic-monitor start        # start in the background
mic-monitor stop
mic-monitor status       # Running (pid 1234): <input>  ->  <output>
mic-monitor run          # foreground, Ctrl+C to stop (handy for trying settings)
mic-monitor list         # show audio devices
```

Tray icon:

```sh
mic-monitor-tray
```

Green disc with a white mic = on, grey disc with a red slash = off. Left-click
toggles, right-click shows the devices, Start/Stop and Quit. Quitting stops
monitoring. The icon polls every 3 seconds, so it stays correct when you toggle
from a terminal. To have it at login, add `mic-monitor-tray` to your startup
items (Windows: `shell:startup` folder, macOS: Login Items).

## Choose devices and settings

With no settings, monitoring goes from the system default input to the system
default output. To pick devices, use a distinctive part of their names as
shown by `mic-monitor list`:

```sh
mic-monitor start --in Yeti --out CORSAIR
```

Save settings so every start and the tray icon use them:

```sh
mic-monitor config --in Yeti --out CORSAIR     # save
mic-monitor config                              # show
mic-monitor config --reset                      # back to defaults
```

| Setting | Default | Meaning |
|---|---|---|
| `--in` | system default | input device name substring (case-insensitive) |
| `--out` | system default | output device name substring |
| `--gain` | 1.0 | output volume multiplier |
| `--blocksize` | 256 | frames per buffer; lower = less latency, more risk of dropouts |
| `--samplerate` | input device's rate | only change it if you know the device accepts it |

Precedence: a command-line flag beats the saved config, which beats the default.

On Windows a device appears once per host API (MME, DirectSound, WASAPI,
WDM-KS). mic-monitor always prefers the WASAPI entry, which is the low-latency
one (about 3 ms of buffer against 90 ms for MME), so you never need to pick it
by index.

## How recovery works

A wireless headset that sleeps and wakes gets its audio endpoint re-created by
the operating system. A stream that was open on the old endpoint keeps
running into nothing: the process looks fine, you hear silence. mic-monitor
reopens its stream when:

- the stream goes inactive on its own (any platform), or
- on Windows, the Plug and Play arrival timestamp of the input or output
  endpoint changes (checked every 2 seconds through cfgmgr32, no extra
  packages).

While the device is away the log shows `waiting for device: ...` with a retry
every 2 seconds, then `Reopened.` The reopen happens inside the same process,
so the PID, the CLI and the tray icon are unaffected.

## Files

| What | Windows | macOS / Linux |
|---|---|---|
| Saved config | `%APPDATA%\mic-monitor\config.json` | `~/.config/mic-monitor/config.json` |
| Worker log | `%LOCALAPPDATA%\mic-monitor\worker.log` | `~/.local/state/mic-monitor/worker.log` |
| PID and status | same directory as the log | same directory as the log |
| Tray errors | `%LOCALAPPDATA%\mic-monitor\tray.log` | `~/.local/state/mic-monitor/tray.log` |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are honoured.

## Platform notes

- **Windows**: tested. The background worker runs with no console window and
  stopping it is a hard kill, which is fine for a pass-through stream.
- **macOS**: the tray icon uses pystray, which pulls in pyobjc. Not yet tested
  by the author; the worker code path is the same as on Windows minus the PnP
  watch. Reports welcome.
- **Linux**: needs `libportaudio2` and an X11 or AppIndicator-capable tray for
  the icon. Not yet tested by the author.

## Development

```sh
git clone https://github.com/ringo380/mic-monitor
cd mic-monitor
pip install -e .[dev]
python check.py          # ruff + tests, no hardware needed, a few seconds
python check.py --hw     # also the hardware tests (opens your real devices)
```

The hardware tests use your saved config or the system defaults. One of them
simulates a headset re-arrival and asserts the stream reopens.

## License

MIT, see [LICENSE](LICENSE).
