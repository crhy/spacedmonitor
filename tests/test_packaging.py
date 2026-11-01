# SPDX-License-Identifier: GPL-3.0-or-later
"""Packaging: build the .deb and check its contents, metadata and launcher."""
import subprocess
import unittest
from pathlib import Path

import spaced_monitor

ROOT = Path(__file__).resolve().parent.parent


class Packaging(unittest.TestCase):
    """Build scripts/build-deb.sh and inspect the result."""

    @classmethod
    def setUpClass(cls):
        cls.version = spaced_monitor.__version__
        cls.deb = ROOT / "build" / f"spaced-monitor_{cls.version}_all.deb"
        cls.stage = ROOT / "build" / "deb" / f"spaced-monitor_{cls.version}_all"
        subprocess.run(["bash", "scripts/build-deb.sh"], cwd=str(ROOT),
                       timeout=120, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def _dpkg(self, *args):
        return subprocess.run(["dpkg-deb", *args], cwd=str(ROOT), timeout=60,
                              check=True, text=True,
                              stdout=subprocess.PIPE).stdout

    def test_deb_built(self):
        self.assertTrue(self.deb.is_file())

    def test_contents(self):
        listing = self._dpkg("-c", str(self.deb))
        for need in ("usr/bin/spaced-monitor",
                     "usr/lib/spaced-monitor/spaced_monitor/app.py",
                     "usr/share/applications/org.spacedlinux.Monitor.desktop",
                     "usr/share/icons/hicolor/scalable/apps/org.spacedlinux.Monitor.svg",
                     "usr/share/doc/spaced-monitor/copyright",
                     "usr/share/doc/spaced-monitor/LICENSE"):
            self.assertIn(need, listing)
        self.assertNotIn("__pycache__", listing)
        self.assertNotIn("tests/", listing)

    def test_launcher_mode(self):
        listing = self._dpkg("-c", str(self.deb))
        self.assertRegex(listing, r"[-]rwxr-xr-x[ ]+root/root[ ]+\d+[ ]+\S+[ ]+\S+[ ]+./usr/bin/spaced-monitor")

    def test_depends(self):
        deps = self._dpkg("-f", str(self.deb), "Depends")
        for dep in ("python3", "python3-gi", "gir1.2-gtk-3.0", "python3-cairo",
                    "python3-psutil"):
            self.assertIn(dep, deps)
        self.assertNotIn("systemd", deps)

    def test_no_writable_modes(self):
        listing = self._dpkg("-c", str(self.deb))
        for line in listing.splitlines():
            mode = line.split()[0]
            if mode.startswith("d"):
                self.assertEqual(mode, "drwxr-xr-x", line)
            else:
                self.assertFalse(mode[5] == "w", f"group-writable: {line}")

    def test_launcher_version(self):
        launcher = self.stage / "usr" / "bin" / "spaced-monitor"
        out = subprocess.run([str(launcher), "--version"], cwd=str(ROOT),
                             timeout=60, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(out.stdout.strip(), f"spaced-monitor {self.version}")

    def test_launcher_leaves_no_bytecode_behind(self):
        launcher = self.stage / "usr" / "bin" / "spaced-monitor"
        subprocess.run([str(launcher), "--version"], cwd=str(ROOT),
                       timeout=60, check=True, stdout=subprocess.PIPE)
        left = list((self.stage / "usr" / "lib" / "spaced-monitor").rglob("__pycache__"))
        self.assertEqual(left, [], f"launcher wrote bytecode into the prefix: {left}")


if __name__ == "__main__":
    unittest.main()
