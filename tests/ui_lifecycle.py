# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the real entry point in a process and close its real GTK window."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile

CHILD = '''
from gi.repository import GLib
from spaced_monitor import app as app_mod

instances = []
class ClosingApp(app_mod.MonitorApp):
    def do_activate(self):
        super().do_activate()
        instances.append(self)
        def close():
            assert self.window.get_mapped(), "Window never mapped"
            self.window.close()
            return False
        GLib.timeout_add(250, close)
app_mod.MonitorApp = ClosingApp
assert app_mod.main([]) == 0
assert len(instances) == 1
app = instances[0]
assert app.window._stop_event.is_set()
assert app._status_source == 0
assert not app._settings_handlers
assert not app.get_windows()
'''


def main():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="monitor-lifecycle-") as config:
        env = dict(os.environ, XDG_CONFIG_HOME=config, NO_AT_BRIDGE="1")
        # An independent process exposes the original second-loop bug:
        # destroying the window must return from main() and exit, not hang.
        for _ in range(3):
            result = subprocess.run(
                [sys.executable, "-c", CHILD], cwd=root, env=env,
                capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stderr
            assert "Traceback" not in result.stderr, result.stderr
    print("OK: three real launches exit cleanly when their window closes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
