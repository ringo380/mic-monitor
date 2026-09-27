"""System tray toggle for Yeti -> Corsair mic monitoring (Windows counterpart
of mic-monitor-app.py).

Drives the `mic-monitor.ps1` wrapper so the CLI and this app stay in sync.
Launch with pythonw.exe so no console window is attached.
"""
import os
import subprocess
import threading

import pystray
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.realpath(__file__))
WRAPPER = os.path.join(HERE, "mic-monitor.ps1")
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", WRAPPER]
# Without CREATE_NO_WINDOW every wrapper call (including the 3 s poll) flashes
# a console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

POLL_SECONDS = 3
SIZE = 64


def run_wrapper(command):
    return subprocess.run(POWERSHELL + [command], capture_output=True, text=True,
                          creationflags=NO_WINDOW).stdout


def is_running():
    return "Running" in run_wrapper("status")


def make_icon(on):
    """Bold, high-contrast disc: green with a white mic when ON, dark grey with
    a red slash when OFF. Tray icons are tiny, so no fine detail."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (30, 160, 60, 255) if on else (70, 70, 70, 255)
    d.ellipse((0, 0, SIZE - 1, SIZE - 1), fill=bg)
    white = (255, 255, 255, 255)
    # mic capsule + stem + base
    d.rounded_rectangle((24, 12, 40, 36), radius=8, fill=white)
    d.arc((18, 22, 46, 44), start=0, end=180, fill=white, width=4)
    d.line((32, 44, 32, 52), fill=white, width=4)
    d.line((22, 52, 42, 52), fill=white, width=4)
    if not on:
        d.line((12, 52, 52, 12), fill=(220, 40, 40, 255), width=7)
    return img


class TrayApp:
    def __init__(self):
        self.on = False
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

    def status_text(self):
        return "Monitoring: ON  (Yeti -> Corsair)" if self.on else "Monitoring: OFF"

    def toggle_text(self):
        return "Stop monitoring" if self.on else "Start monitoring"

    def refresh(self):
        on = is_running()
        if on != self.on:
            self.on = on
            self.icon.icon = make_icon(on)
            self.icon.title = "Mic monitor: ON (Yeti -> Corsair)" if on else "Mic monitor: OFF"
            self.icon.update_menu()

    def toggle(self, icon=None, item=None):
        run_wrapper("toggle")
        self.refresh()

    def quit(self, icon=None, item=None):
        # Same as the Mac app: quitting stops monitoring.
        self._stop_poll.set()
        run_wrapper("stop")
        self.icon.stop()

    def _poll(self):
        # keeps the icon correct even if toggled from the terminal
        while not self._stop_poll.wait(POLL_SECONDS):
            self.refresh()

    def _setup(self, icon):
        icon.visible = True
        self.refresh()
        threading.Thread(target=self._poll, daemon=True).start()

    def run(self):
        self.icon.run(setup=self._setup)


if __name__ == "__main__":
    TrayApp().run()
