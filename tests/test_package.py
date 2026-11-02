import contextlib
import io
import os
import unittest
from unittest import mock

import spaced_monitor
from spaced_monitor import app as app_mod


class Package(unittest.TestCase):
    def test_version(self):
        self.assertRegex(spaced_monitor.__version__, r"^\d+\.\d+\.\d+$")


class NoDisplay(unittest.TestCase):
    """A shell with no screen must get a sentence, not a GTK assertion dump."""

    def _run_without_display(self) -> tuple[int, str]:
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = app_mod.main([])
        return code, err.getvalue()

    def test_returns_one(self):
        code, _text = self._run_without_display()
        self.assertEqual(code, 1)

    def test_explains_itself(self):
        _code, text = self._run_without_display()
        self.assertIn("no display connection", text)
        self.assertIn("DISPLAY=:0", text)
        self.assertIn("xvfb-run", text)

    def test_version_still_works_without_a_display(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app_mod.main(["--version"]), 0)
        self.assertIn(f"spaced-monitor {spaced_monitor.__version__}", out.getvalue())


if __name__ == "__main__":
    unittest.main()
