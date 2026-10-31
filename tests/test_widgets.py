# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Cairo-drawn widgets (rendered headless on cairo surfaces)."""

import math
import os
import unittest

import cairo

from spaced_monitor import widgets
from spaced_monitor.theme import DARK


def _surface():
    """Return a fresh 400x200 surface and its draw context."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 200)
    return surf, cairo.Context(surf)


def _pixel(surf, x, y):
    """Return (r, g, b) 0-255 of a pixel."""
    data = surf.get_data()
    stride = surf.get_stride()
    i = y * stride + x * 4
    return (data[i + 2], data[i + 1], data[i])


def _has_colour(surf, target, tol=30):
    """True if any pixel is within tol of the target rgb."""
    tr, tg, tb = target
    data = surf.get_data()
    for i in range(0, len(data), 4):
        r, g, b = data[i + 2], data[i + 1], data[i]
        if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
            return True
    return False


def _save(surf, name):
    """Write a render to build/screenshots/widgets-<name>.png."""
    os.makedirs("build/screenshots", exist_ok=True)
    surf.write_to_png(f"build/screenshots/widgets-{name}.png")


def _rgb255(colour):
    """Convert a palette float tuple to 0-255 ints."""
    return tuple(int(c * 255) for c in colour)


class TestGauge(unittest.TestCase):
    """draw_gauge renders every percent value without error."""

    def _render(self, percent):
        surf, cr = _surface()
        widgets.draw_gauge(cr, 400, 200, DARK, "cpu", percent)
        return surf

    def test_percent_values(self):
        for v in (0, 38, 100, -5, 150, None):
            surf = self._render(v)
            _save(surf, f"gauge-{v}")

    def test_38_left_arc_green_right_track(self):
        surf = self._render(38)
        cx, cy, r, _lw = widgets._gauge_geometry(400, 200)
        left = _pixel(surf, int(cx - r), int(cy))
        right = _pixel(surf, int(cx + r), int(cy))
        self.assertGreater(left[1], left[0])
        self.assertGreater(left[1], left[2])
        track = _rgb255(DARK.gauge_track)
        for a, b in zip(right, track):
            self.assertLess(abs(a - b), 12)


class TestBars(unittest.TestCase):
    """draw_stacked_bar and draw_meter handle data and empty input."""

    def test_stacked_bar(self):
        surf, cr = _surface()
        segs = [(0.3, DARK.cpu_start), (0.5, DARK.memory_start)]
        widgets.draw_stacked_bar(cr, 400, 200, segs)
        _save(surf, "stacked-bar")
        self.assertTrue(_has_colour(surf, _rgb255(DARK.cpu_start)))

    def test_stacked_bar_empty(self):
        surf, cr = _surface()
        widgets.draw_stacked_bar(cr, 400, 200, None)
        _save(surf, "stacked-bar-empty")

    def test_meter(self):
        surf, cr = _surface()
        widgets.draw_meter(cr, 400, 200, DARK, 0.42, DARK.gpu_start)
        _save(surf, "meter")
        self.assertTrue(_has_colour(surf, _rgb255(DARK.gpu_start)))

    def test_meter_none(self):
        surf, cr = _surface()
        widgets.draw_meter(cr, 400, 200, DARK, None, DARK.gpu_start)
        _save(surf, "meter-none")


class TestLineGraph(unittest.TestCase):
    """draw_line_graph draws each series colour and the threshold line."""

    def _vals(self):
        return [50 + 20 * math.sin(i / 20) for i in range(300)]

    def test_full_graph(self):
        surf, cr = _surface()
        series = [(DARK.cpu_temp, self._vals()),
                  (DARK.gpu_temp, [v + 10 for v in self._vals()])]
        widgets.draw_line_graph(cr, 400, 200, DARK, series, 0, 100,
                                threshold=80, unit="°C", seconds=300)
        _save(surf, "line-graph")
        self.assertTrue(_has_colour(surf, _rgb255(DARK.cpu_temp)))
        self.assertTrue(_has_colour(surf, _rgb255(DARK.gpu_temp)))
        self.assertTrue(_has_colour(surf, _rgb255(DARK.threshold)))

    def test_empty_graph(self):
        surf, cr = _surface()
        widgets.draw_line_graph(cr, 400, 200, DARK, [(DARK.cpu_temp, [])],
                                0, 100)
        _save(surf, "line-graph-empty")

    def test_no_threshold_absent(self):
        surf, cr = _surface()
        widgets.draw_line_graph(cr, 400, 200, DARK,
                                [(DARK.cpu_temp, self._vals())], 0, 100)
        _save(surf, "line-graph-no-threshold")
        self.assertFalse(_has_colour(surf, _rgb255(DARK.threshold), tol=10))


class TestSparkline(unittest.TestCase):
    """draw_sparkline auto-scales and handles empty input."""

    def test_sparkline(self):
        surf, cr = _surface()
        vals = [40 + 30 * math.sin(i / 8) for i in range(60)]
        series = [(DARK.cpu_temp, vals), (DARK.memory_start, [v * 0.5 for v in vals])]
        widgets.draw_sparkline(cr, 400, 200, DARK, series)
        _save(surf, "sparkline")
        self.assertTrue(_has_colour(surf, _rgb255(DARK.cpu_temp)))

    def test_sparkline_empty(self):
        surf, cr = _surface()
        widgets.draw_sparkline(cr, 400, 200, DARK, [])
        _save(surf, "sparkline-empty")


class TestSeriesPoints(unittest.TestCase):
    """_series_points maps values and skips None gaps (used by LineGraph)."""

    def test_skips_none(self):
        pts = widgets._series_points([10, None, 30], 0, 100, 0, 100,
                                     0, 100, seconds=3)
        assert len(pts) == 2
        assert all(p[0] >= 0 for p in pts)

    def test_empty(self):
        assert widgets._series_points([], 0, 100, 0, 100, 0, 100, 3) == []


if __name__ == "__main__":
    unittest.main()
