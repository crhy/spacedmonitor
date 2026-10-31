# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for spaced_monitor.theme."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from spaced_monitor.theme import (
    DARK, LIGHT, Palette, palette, gradient, rgba, css,
    load_settings, save_settings, resolve_theme,
)


class TestPalette(unittest.TestCase):
    """Palette dataclass is complete and DARK/LIGHT are distinct."""

    def test_dark_has_all_fields(self):
        fields = Palette.__dataclass_fields__
        for name in fields:
            val = getattr(DARK, name)
            self.assertIsInstance(val, tuple)
            self.assertEqual(len(val), 3)
            for c in val:
                self.assertGreaterEqual(c, 0.0)
                self.assertLessEqual(c, 1.0)

    def test_light_has_all_fields(self):
        fields = Palette.__dataclass_fields__
        for name in fields:
            val = getattr(LIGHT, name)
            self.assertIsInstance(val, tuple)
            self.assertEqual(len(val), 3)
            for c in val:
                self.assertGreaterEqual(c, 0.0)
                self.assertLessEqual(c, 1.0)

    def test_dark_and_light_differ(self):
        self.assertNotEqual(DARK.window, LIGHT.window)
        self.assertNotEqual(DARK.card, LIGHT.card)
        self.assertNotEqual(DARK.text, LIGHT.text)
        self.assertNotEqual(DARK.gauge_track, LIGHT.gauge_track)

    def test_palette_lookup(self):
        self.assertIs(palette("dark"), DARK)
        self.assertIs(palette("light"), LIGHT)

    def test_palette_invalid(self):
        with self.assertRaises(ValueError):
            palette("neon")

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            DARK.window = (0, 0, 0)  # type: ignore


class TestGradient(unittest.TestCase):
    """gradient() returns correct colour pairs."""

    def test_cpu(self):
        start, end = gradient(DARK, "cpu")
        self.assertEqual(start, DARK.cpu_start)
        self.assertEqual(end, DARK.cpu_end)

    def test_gpu(self):
        start, end = gradient(LIGHT, "gpu")
        self.assertEqual(start, LIGHT.gpu_start)
        self.assertEqual(end, LIGHT.gpu_end)

    def test_memory(self):
        start, end = gradient(DARK, "memory")
        self.assertEqual(start, DARK.memory_start)
        self.assertEqual(end, DARK.memory_end)

    def test_gpu_memory(self):
        start, end = gradient(DARK, "gpu_memory")
        self.assertEqual(start, DARK.gpu_memory_start)
        self.assertEqual(end, DARK.gpu_memory_end)

    def test_invalid_kind(self):
        with self.assertRaises(KeyError):
            gradient(DARK, "nonexistent")


class TestRgba(unittest.TestCase):
    """rgba() formats correctly."""

    def test_basic(self):
        result = rgba((1.0, 0.0, 0.0), 0.5)
        self.assertEqual(result, "rgba(255, 0, 0, 0.5)")

    def test_alpha_one(self):
        result = rgba((0.0, 1.0, 0.0), 1.0)
        self.assertEqual(result, "rgba(0, 255, 0, 1.0)")


class TestCss(unittest.TestCase):
    """css() contains required classes and colours."""

    def test_dark_classes(self):
        text = css(DARK)
        for cls in (".card", ".card-title", ".big-value", ".muted",
                    ".value", ".topbar", ".tab-selected", ".end-button"):
            self.assertIn(cls, text)

    def test_dark_window_colour(self):
        text = css(DARK)
        self.assertIn("#0b1220", text)

    def test_light_window_colour(self):
        text = css(LIGHT)
        self.assertIn("#eef2f8", text)

    def test_dark_card_colour(self):
        text = css(DARK)
        self.assertIn("#111a2e", text)

    def test_light_card_colour(self):
        text = css(LIGHT)
        self.assertIn("#ffffff", text)

    def test_border_radius(self):
        text = css(DARK)
        self.assertIn("border-radius: 12px", text)

    def test_end_button_red(self):
        text = css(DARK)
        self.assertIn("#ef4444", text)

    def test_tab_selected_uses_gpu_tint(self):
        text = css(DARK)
        self.assertIn("rgba(14, 165, 233, 0.25)", text)

    def test_muted_colour_dark(self):
        text = css(DARK)
        self.assertIn("#8a96ab", text)

    def test_muted_colour_light(self):
        text = css(LIGHT)
        self.assertIn("#6b7280", text)


class TestSettings(unittest.TestCase):
    """Settings load/save round trip, corrupt handling, clamping, atomicity."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(dir=str(Path(__file__).resolve().parent.parent / "build")))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_defaults_on_missing(self):
        s = load_settings(path=str(self.tmpdir / "nonexistent.json"))
        self.assertEqual(s["theme"], "system")
        self.assertEqual(s["refresh_ms"], 1000)

    def test_defaults_on_corrupt(self):
        p = self.tmpdir / "bad.json"
        p.write_text("not json at all {{{")
        s = load_settings(path=str(p))
        self.assertEqual(s["theme"], "system")
        self.assertEqual(s["refresh_ms"], 1000)

    def test_defaults_on_non_dict(self):
        p = self.tmpdir / "arr.json"
        p.write_text("[1, 2, 3]")
        s = load_settings(path=str(p))
        self.assertEqual(s["theme"], "system")

    def test_round_trip(self):
        p = str(self.tmpdir / "settings.json")
        save_settings({"theme": "dark", "refresh_ms": 2000}, path=p)
        s = load_settings(path=p)
        self.assertEqual(s["theme"], "dark")
        self.assertEqual(s["refresh_ms"], 2000)

    def test_clamp_low(self):
        p = str(self.tmpdir / "s.json")
        save_settings({"theme": "light", "refresh_ms": 100}, path=p)
        s = load_settings(path=p)
        self.assertEqual(s["refresh_ms"], 500)

    def test_clamp_high(self):
        p = str(self.tmpdir / "s.json")
        save_settings({"theme": "dark", "refresh_ms": 9999}, path=p)
        s = load_settings(path=p)
        self.assertEqual(s["refresh_ms"], 5000)

    def test_invalid_theme_ignored(self):
        p = self.tmpdir / "s.json"
        p.write_text(json.dumps({"theme": "neon", "refresh_ms": 1000}))
        s = load_settings(path=str(p))
        self.assertEqual(s["theme"], "system")

    def test_atomic_creates_parent(self):
        p = str(self.tmpdir / "sub" / "dir" / "settings.json")
        save_settings({"theme": "dark", "refresh_ms": 800}, path=p)
        s = load_settings(path=p)
        self.assertEqual(s["theme"], "dark")
        self.assertEqual(s["refresh_ms"], 800)

    def test_no_temp_files_left(self):
        p = str(self.tmpdir / "settings.json")
        save_settings({"theme": "dark", "refresh_ms": 1000}, path=p)
        files = list(self.tmpdir.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "settings.json")


class TestResolveTheme(unittest.TestCase):
    """resolve_theme handles all cases."""

    def test_explicit_dark(self):
        self.assertEqual(resolve_theme("dark", MagicMock()), "dark")

    def test_explicit_light(self):
        self.assertEqual(resolve_theme("light", MagicMock()), "light")

    def test_system_prefer_dark(self):
        gs = MagicMock()
        gs.get_gtk_application_prefer_dark_theme.return_value = True
        gs.get_gtk_theme_name.return_value = "Adwaita"
        self.assertEqual(resolve_theme("system", gs), "dark")

    def test_system_dark_in_name(self):
        gs = MagicMock()
        gs.get_gtk_application_prefer_dark_theme.return_value = False
        gs.get_gtk_theme_name.return_value = "HighContrastDark"
        self.assertEqual(resolve_theme("system", gs), "dark")

    def test_system_light(self):
        gs = MagicMock()
        gs.get_gtk_application_prefer_dark_theme.return_value = False
        gs.get_gtk_theme_name.return_value = "Adwaita"
        self.assertEqual(resolve_theme("system", gs), "light")

    def test_system_none_name(self):
        gs = MagicMock()
        gs.get_gtk_application_prefer_dark_theme.return_value = False
        gs.get_gtk_theme_name.return_value = None
        self.assertEqual(resolve_theme("system", gs), "light")


if __name__ == "__main__":
    unittest.main()
