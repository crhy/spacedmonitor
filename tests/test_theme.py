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
    load_settings, save_settings, resolve_theme, palette_from_gtk,
    _relative_luminance, _mix_towards, _lightness,
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

    def test_ordinary_end_button_is_orange(self):
        text = css(DARK)
        self.assertIn(".end-button {\n    background-color: #f97316", text)

    def test_essential_end_button_is_red(self):
        text = css(DARK)
        self.assertIn(".end-button.essential-end-button", text)
        self.assertIn("background-color: #ef4444", text)

    def test_tab_selected_uses_gpu_tint(self):
        text = css(DARK)
        self.assertIn("rgba(14, 165, 233, 0.4)", text)

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


class TestPaletteFromGtk(unittest.TestCase):
    """palette_from_gtk with a fake style context."""

    def _fake_ctx(self, colours: dict):
        """Return a fake style_context whose lookup_color returns Gdk.RGBA-like."""
        class FakeRGBA:
            def __init__(self, r, g, b):
                self.red = r
                self.green = g
                self.blue = b

        class FakeCtx:
            def lookup_color(self, name):
                if name in colours:
                    r, g, b = colours[name]
                    return (True, FakeRGBA(r, g, b))
                return (False, FakeRGBA(0, 0, 0))

        return FakeCtx()

    def test_grey_dark_theme(self):
        """Spaced Mint: grey bg, grey base -> dark grey palette."""
        # Spaced-Mint: theme_bg_color #2b2b2b, theme_base_color #1d1d1d
        ctx = self._fake_ctx({
            "theme_bg_color": (0x2b/255, 0x2b/255, 0x2b/255),
            "theme_base_color": (0x1d/255, 0x1d/255, 0x1d/255),
            "theme_fg_color": (0.9, 0.9, 0.9),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        # Should be dark (luminance of #2b2b2b < 0.5)
        self.assertLess(_relative_luminance(pal.window), 0.5)
        # Window should be grey
        self.assertAlmostEqual(pal.window[0], pal.window[1], places=3)
        self.assertAlmostEqual(pal.window[1], pal.window[2], places=3)
        # Card should be close to base
        self.assertAlmostEqual(pal.card[0], 0x1d/255, places=2)

    def test_navy_dark_theme(self):
        """Spaced Win11-Dark: navy bg -> dark navy palette."""
        # Spaced-Win11-Dark: theme_bg_color #17243b, theme_base_color #111827
        ctx = self._fake_ctx({
            "theme_bg_color": (0x17/255, 0x24/255, 0x3b/255),
            "theme_base_color": (0x11/255, 0x18/255, 0x27/255),
            "theme_fg_color": (0.85, 0.88, 0.92),
            "theme_selected_bg_color": (0.3, 0.5, 0.9),
        })
        pal = palette_from_gtk(ctx)
        self.assertLess(_relative_luminance(pal.window), 0.5)
        # Navy: blue channel > red channel
        self.assertGreater(pal.window[2], pal.window[0])

    def test_light_theme(self):
        """Spaced Win11-Light: light bg -> light palette."""
        # Spaced-Win11-Light: theme_bg_color #f3f3f3, theme_base_color #ffffff
        ctx = self._fake_ctx({
            "theme_bg_color": (0xf3/255, 0xf3/255, 0xf3/255),
            "theme_base_color": (1.0, 1.0, 1.0),
            "theme_fg_color": (0.1, 0.1, 0.1),
            "theme_selected_bg_color": (0.2, 0.4, 0.8),
        })
        pal = palette_from_gtk(ctx)
        self.assertGreater(_relative_luminance(pal.window), 0.5)
        # Card is white, window is #f3f3f3: lightness diff ~4.7% > 4%, no shading
        self.assertAlmostEqual(pal.card[0], 1.0, places=2)

    def test_missing_colours_fallback(self):
        """When no colours are found, falls back to DARK."""
        ctx = self._fake_ctx({})
        pal = palette_from_gtk(ctx)
        # With no bg, is_dark depends on fg which is also missing -> fallback DARK
        self.assertEqual(pal.window, DARK.window)
        self.assertEqual(pal.card, DARK.card)
        self.assertEqual(pal.text, DARK.text)

    def test_low_contrast_card_shading(self):
        """Card within 4% lightness of window gets shaded 6% towards fg."""
        # Both bg and base are the same grey
        grey = 0x2b / 255
        ctx = self._fake_ctx({
            "theme_bg_color": (grey, grey, grey),
            "theme_base_color": (grey, grey, grey),
            "theme_fg_color": (0.9, 0.9, 0.9),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        # Card should be lighter than window (shaded towards light fg)
        self.assertGreater(_lightness(pal.card), _lightness(pal.window))

    def test_accent_colours_preserved(self):
        """Accent colours (cpu green, gpu blue, etc.) are always from fallback."""
        ctx = self._fake_ctx({
            "theme_bg_color": (0.5, 0.5, 0.5),
            "theme_base_color": (0.4, 0.4, 0.4),
            "theme_fg_color": (0.9, 0.9, 0.9),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        # cpu_start should be the accent green, not derived from theme
        self.assertEqual(pal.cpu_start, DARK.cpu_start)
        self.assertEqual(pal.end_button, DARK.end_button)

    def test_selected_bg_from_theme(self):
        """selected_bg comes from theme_selected_bg_color."""
        ctx = self._fake_ctx({
            "theme_bg_color": (0.2, 0.2, 0.2),
            "theme_base_color": (0.15, 0.15, 0.15),
            "theme_fg_color": (0.9, 0.9, 0.9),
            "theme_selected_bg_color": (0.1, 0.6, 0.3),
        })
        pal = palette_from_gtk(ctx)
        self.assertAlmostEqual(pal.selected_bg[1], 0.6, places=2)

    def test_muted_is_fg_at_65_percent(self):
        """muted = mix(window, fg, 0.65)."""
        ctx = self._fake_ctx({
            "theme_bg_color": (0.0, 0.0, 0.0),
            "theme_base_color": (0.1, 0.1, 0.1),
            "theme_fg_color": (1.0, 1.0, 1.0),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        # mix(black, white, 0.65) = 0.65
        self.assertAlmostEqual(pal.muted[0], 0.65, places=2)

    def test_border_is_fg_at_12_percent(self):
        """border = mix(window, fg, 0.12)."""
        ctx = self._fake_ctx({
            "theme_bg_color": (0.0, 0.0, 0.0),
            "theme_base_color": (0.1, 0.1, 0.1),
            "theme_fg_color": (1.0, 1.0, 1.0),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        self.assertAlmostEqual(pal.border[0], 0.12, places=2)

    def test_gauge_track_is_fg_at_14_percent(self):
        """gauge_track = mix(window, fg, 0.14)."""
        ctx = self._fake_ctx({
            "theme_bg_color": (0.0, 0.0, 0.0),
            "theme_base_color": (0.1, 0.1, 0.1),
            "theme_fg_color": (1.0, 1.0, 1.0),
            "theme_selected_bg_color": (0.2, 0.5, 0.8),
        })
        pal = palette_from_gtk(ctx)
        self.assertAlmostEqual(pal.gauge_track[0], 0.14, places=2)


class TestRelativeLuminance(unittest.TestCase):
    """_relative_luminance returns correct values."""

    def test_black(self):
        self.assertAlmostEqual(_relative_luminance((0, 0, 0)), 0.0, places=3)

    def test_white(self):
        self.assertAlmostEqual(_relative_luminance((1, 1, 1)), 1.0, places=2)

    def test_grey_mid(self):
        lum = _relative_luminance((0.5, 0.5, 0.5))
        self.assertGreater(lum, 0.15)
        self.assertLess(lum, 0.25)


if __name__ == "__main__":
    unittest.main()
