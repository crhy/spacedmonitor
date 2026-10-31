# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for pane fraction clamping, save and restore."""

import unittest

from spaced_monitor.panes import (
    clamp_fraction,
    default_fractions,
    load_pane_fractions,
    save_pane_fractions,
    fractions_to_pixels,
    pixels_to_fractions,
)


class TestClampFraction(unittest.TestCase):
    """Tests for clamp_fraction."""

    def test_valid_mid(self):
        self.assertAlmostEqual(clamp_fraction(0.5), 0.5)

    def test_valid_min(self):
        self.assertAlmostEqual(clamp_fraction(0.1), 0.1)

    def test_valid_max(self):
        self.assertAlmostEqual(clamp_fraction(0.9), 0.9)

    def test_below_min(self):
        self.assertIsNone(clamp_fraction(0.05))

    def test_above_max(self):
        self.assertIsNone(clamp_fraction(0.95))

    def test_zero(self):
        self.assertIsNone(clamp_fraction(0.0))

    def test_one(self):
        self.assertIsNone(clamp_fraction(1.0))

    def test_negative(self):
        self.assertIsNone(clamp_fraction(-0.5))

    def test_none(self):
        self.assertIsNone(clamp_fraction(None))

    def test_string(self):
        self.assertIsNone(clamp_fraction("0.5"))

    def test_int(self):
        self.assertIsNone(clamp_fraction(1))

    def test_int_zero(self):
        self.assertIsNone(clamp_fraction(0))


class TestDefaultFractions(unittest.TestCase):
    """Tests for default_fractions."""

    def test_returns_three_keys(self):
        d = default_fractions()
        self.assertEqual(set(d.keys()), {"pane_gauges", "pane_graphs",
                                         "pane_mid_h"})

    def test_values_in_range(self):
        for v in default_fractions().values():
            self.assertGreaterEqual(v, 0.1)
            self.assertLessEqual(v, 0.9)

    def test_gauges_default(self):
        self.assertAlmostEqual(default_fractions()["pane_gauges"], 0.20)

    def test_graphs_default(self):
        self.assertAlmostEqual(default_fractions()["pane_graphs"], 0.28)

    def test_mid_h_default(self):
        self.assertAlmostEqual(default_fractions()["pane_mid_h"], 0.50)


class TestLoadPaneFractions(unittest.TestCase):
    """Tests for load_pane_fractions."""

    def test_empty_settings(self):
        fr = load_pane_fractions({})
        self.assertEqual(fr, default_fractions())

    def test_valid_settings(self):
        s = {"pane_gauges": 0.3, "pane_graphs": 0.4, "pane_mid_h": 0.6}
        fr = load_pane_fractions(s)
        self.assertAlmostEqual(fr["pane_gauges"], 0.3)
        self.assertAlmostEqual(fr["pane_graphs"], 0.4)
        self.assertAlmostEqual(fr["pane_mid_h"], 0.6)

    def test_out_of_range_ignored(self):
        s = {"pane_gauges": 0.05, "pane_graphs": 0.95, "pane_mid_h": 0.5}
        fr = load_pane_fractions(s)
        self.assertAlmostEqual(fr["pane_gauges"], 0.20)
        self.assertAlmostEqual(fr["pane_graphs"], 0.28)
        self.assertAlmostEqual(fr["pane_mid_h"], 0.5)

    def test_non_numeric_ignored(self):
        s = {"pane_gauges": "abc", "pane_graphs": None}
        fr = load_pane_fractions(s)
        self.assertAlmostEqual(fr["pane_gauges"], 0.20)
        self.assertAlmostEqual(fr["pane_graphs"], 0.28)

    def test_extra_keys_ignored(self):
        s = {"pane_gauges": 0.3, "unknown": 0.5}
        fr = load_pane_fractions(s)
        self.assertNotIn("unknown", fr)


class TestSavePaneFractions(unittest.TestCase):
    """Tests for save_pane_fractions."""

    def test_saves_valid(self):
        s = {"theme": "dark"}
        fr = {"pane_gauges": 0.35, "pane_graphs": 0.45, "pane_mid_h": 0.55}
        out = save_pane_fractions(s, fr)
        self.assertAlmostEqual(out["pane_gauges"], 0.35)
        self.assertAlmostEqual(out["pane_graphs"], 0.45)
        self.assertAlmostEqual(out["pane_mid_h"], 0.55)
        self.assertEqual(out["theme"], "dark")

    def test_skips_invalid(self):
        s = {"theme": "light"}
        fr = {"pane_gauges": 0.01, "pane_graphs": 0.99, "pane_mid_h": 0.5}
        out = save_pane_fractions(s, fr)
        self.assertNotIn("pane_gauges", out)
        self.assertNotIn("pane_graphs", out)
        self.assertAlmostEqual(out["pane_mid_h"], 0.5)

    def test_rounds_to_four(self):
        s = {}
        fr = {"pane_gauges": 0.333333}
        out = save_pane_fractions(s, fr)
        self.assertEqual(out["pane_gauges"], 0.3333)


class TestFractionPixelConversion(unittest.TestCase):
    """Tests for fractions_to_pixels and pixels_to_fractions."""

    def test_fractions_to_pixels(self):
        fr = {"pane_gauges": 0.2, "pane_graphs": 0.3}
        px = fractions_to_pixels(fr, 1000)
        self.assertEqual(px["pane_gauges"], 200)
        self.assertEqual(px["pane_graphs"], 300)

    def test_pixels_to_fractions(self):
        px = {"pane_gauges": 200, "pane_graphs": 300}
        fr = pixels_to_fractions(px, 1000)
        self.assertAlmostEqual(fr["pane_gauges"], 0.2)
        self.assertAlmostEqual(fr["pane_graphs"], 0.3)

    def test_zero_total(self):
        fr = pixels_to_fractions({"pane_gauges": 100}, 0)
        self.assertEqual(fr, default_fractions())

    def test_roundtrip(self):
        fr = {"pane_gauges": 0.25, "pane_graphs": 0.45, "pane_mid_h": 0.6}
        px = fractions_to_pixels(fr, 900)
        back = pixels_to_fractions(px, 900)
        for k in fr:
            self.assertAlmostEqual(back[k], fr[k], places=3)


if __name__ == "__main__":
    unittest.main()
