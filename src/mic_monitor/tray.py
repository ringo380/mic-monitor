"""`mic-monitor-tray`: a system tray / menu bar icon that toggles monitoring.

Green disc with a white mic = on, grey disc with a red slash = off. Left
click toggles; the menu shows the devices and has Start/Stop and Quit.
Quitting stops monitoring. The icon polls every 3 s so it stays correct when
monitoring is toggled from the command line.

Installed as a GUI script: on Windows it runs under pythonw, which has no
console and where sys.stdout is None, so this module never prints. Errors go
to tray.log in the state directory.
"""

from __future__ import annotations

import threading
import traceback

from . import cli, config

POLL_SECONDS = 3
SIZE = 64


def make_icon(on: bool):
    """Bold, high-contrast disc. Tray icons are tiny, so no fine detail."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (30, 160, 60, 255) if on else (70, 70, 70, 255)
    d.ellipse((0, 0, SIZE - 1, SIZE - 1), fill=bg)
    white = (255, 255, 255, 255)
    d.rounded_rectangle((24, 12, 40, 36), radius=8, fill=white)  # capsule
    d.arc((18, 22, 46, 44), start=0, end=180, fill=white, width=4)  # cradle
    d.line((32, 44, 32, 52), fill=white, width=4)  # stem
    d.line((22, 52, 42, 52), fill=white, width=4)  # base
    if not on:
        d.line((12, 52, 52, 12), fill=(220, 40, 40, 255), width=7)
    return img


class TrayApp:
    def __init__(self):
        import pystray

        self.on = False
        self.devices = ""
        self._stop_poll = threading.Event()
        self.icon = pystray.Icon(
            "mic-monitor",
            icon=make_icon(False),
            title="Mic monitor: OFF",
            menu=pystray.Menu(
                pystray.MenuItem(lambda item: self.status_text(), None, enabled=False),
                pystray.MenuItem(lambda item: self.toggle_text(), self.toggle, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self.quit),
            ),
        )

    def status_text(self) -> str:
        if self.on:
            return f"Monitoring: ON  ({self.devices})" if self.devices else "Monitoring: ON"
        return "Monitoring: OFF"

    def toggle_text(self) -> str:
        return "Stop monitoring" if self.on else "Start monitoring"

    def refresh(self) -> None:
        on = cli.is_running()
        devices = ""
        if on:
            st = cli.read_status()
            if st and st.get("waiting"):
                devices = "waiting for device"
            elif st:
                devices = f"{st['in']} -> {st['out']}"
        if on != self.on or devices != self.devices:
            self.on, self.devices = on, devices
            self.icon.icon = make_icon(on)
            self.icon.title = "Mic monitor: ON" if on else "Mic monitor: OFF"
            self.icon.update_menu()

    def toggle(self, icon=None, item=None) -> None:
        cli.toggle()
        self.refresh()

    def quit(self, icon=None, item=None) -> None:
        self._stop_poll.set()
        cli.stop()
        self.icon.stop()

    def _poll(self) -> None:
        while not self._stop_poll.wait(POLL_SECONDS):
            try:
                self.refresh()
            except Exception:  # keep polling; a dead poll thread = stale icon forever
                _log_exception()

    def _setup(self, icon) -> None:
        icon.visible = True
        self.refresh()
        threading.Thread(target=self._poll, daemon=True).start()

    def run(self) -> None:
        self.icon.run(setup=self._setup)


def _log_exception() -> None:
    try:
        p = config.tray_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        TrayApp().run()
    except Exception:
        _log_exception()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
