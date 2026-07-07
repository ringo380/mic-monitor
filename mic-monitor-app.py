#!/opt/homebrew/bin/python3
"""Menu bar toggle for Yeti -> Corsair mic monitoring.

Drives the `mic-monitor` shell wrapper so the CLI and this app stay in sync.
"""
import os
import subprocess

import rumps

# Resolve the CLI wrapper next to this script's real location (follows the
# ~/.local/bin symlink), so the app and CLI stay in sync from the repo.
HERE = os.path.dirname(os.path.realpath(__file__))
WRAPPER = os.path.join(HERE, "mic-monitor")

ICON_ON = "🎙️"
ICON_OFF = "🔇"


def is_running():
    out = subprocess.run([WRAPPER, "status"], capture_output=True, text=True).stdout
    return "Running" in out


class MicMonitorApp(rumps.App):
    def __init__(self):
        super().__init__(ICON_OFF, quit_button=None)
        self.status_item = rumps.MenuItem("", callback=None)
        self.toggle_item = rumps.MenuItem("Start monitoring", callback=self.toggle)
        self.menu = [self.status_item, self.toggle_item, None, rumps.MenuItem("Quit", callback=self.quit)]
        self.refresh()
        # poll so the icon stays correct even if toggled from the terminal
        rumps.Timer(lambda _: self.refresh(), 3).start()

    def refresh(self):
        on = is_running()
        self.title = ICON_ON if on else ICON_OFF
        self.status_item.title = "Monitoring: ON  (Yeti -> Corsair)" if on else "Monitoring: OFF"
        self.toggle_item.title = "Stop monitoring" if on else "Start monitoring"

    def toggle(self, _):
        subprocess.run([WRAPPER, "toggle"], capture_output=True, text=True)
        self.refresh()

    def quit(self, _):
        # leave monitoring as-is on quit; comment the next line out to keep it running
        subprocess.run([WRAPPER, "stop"], capture_output=True, text=True)
        rumps.quit_application()


if __name__ == "__main__":
    MicMonitorApp().run()
