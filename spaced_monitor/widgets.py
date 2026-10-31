# SPDX-License-Identifier: GPL-3.0-or-later
"""Cairo-drawn gauges, bars and graphs for Spaced Monitor."""

from __future__ import annotations

import math
import time

import cairo

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from spaced_monitor.theme import DARK, gradient


def _clamp(v: float | None, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value into [lo, hi]; None becomes lo."""
    if v is None:
        return lo
    return max(lo, min(hi, v))


def _arc_point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    """Point on a circle at `deg` degrees (cairo y-down, clockwise)."""
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _arc_path(cr, cx: float, cy: float, r: float, a0: float, a1: float) -> None:
    """Append a polyline arc sweeping from a0 to a1 degrees."""
    steps = max(2, int(abs(a1 - a0) / 2))
    for i in range(steps + 1):
        x, y = _arc_point(cx, cy, r, a0 + (a1 - a0) * i / steps)
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)


def _rounded_rect(cr, x: float, y: float, w: float, h: float, rad: float) -> None:
    """Append a rounded-rectangle path."""
    r = min(rad, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


GAUGE_START_DEG = 150.0
GAUGE_SWEEP_DEG = 240.0


def _gauge_geometry(w: float, h: float) -> tuple[float, float, float, float]:
    """Return (cx, cy, r, line_width) for a gauge in a w x h box."""
    size = min(w, h)
    lw = size * 0.11
    margin = lw * 0.5 + 2.0
    r = min((w - lw) / 2.0, (h - lw) / 1.5) - margin
    r = max(r, 1.0)
    cx = w / 2.0
    cy = margin + lw / 2.0 + r
    return cx, cy, r, lw


def _draw_gauge_text(cr, cx: float, cy: float, size: float, percent: float,
                     pal) -> None:
    """Draw the percent value big with a smaller % sign, centred."""
    value = int(round(_clamp(percent, 0.0, 100.0)))
    num = str(value)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    big = size * 0.30
    small = big * 0.55
    cr.set_font_size(big)
    wn = cr.text_extents(num).x_advance
    cr.set_font_size(small)
    wp = cr.text_extents("%").x_advance
    cr.set_source_rgb(*pal.text)
    baseline = cy + big * 0.35
    x = cx - (wn + wp) / 2.0
    cr.set_font_size(big)
    cr.move_to(x, baseline)
    cr.show_text(num)
    cr.set_font_size(small)
    cr.move_to(x + wn, baseline)
    cr.show_text("%")


def draw_gauge(cr, w: float, h: float, pal, kind: str, percent: float) -> None:
    """Draw a 240-degree gauge: track arc, gradient value arc, centred percent."""
    cx, cy, r, lw = _gauge_geometry(w, h)
    cr.set_line_width(lw)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    _arc_path(cr, cx, cy, r, GAUGE_START_DEG, GAUGE_START_DEG + GAUGE_SWEEP_DEG)
    cr.set_source_rgb(*pal.gauge_track)
    cr.stroke()
    p = _clamp(percent, 0.0, 100.0)
    if p > 0.0:
        end = GAUGE_START_DEG + GAUGE_SWEEP_DEG * (p / 100.0)
        _arc_path(cr, cx, cy, r, GAUGE_START_DEG, end)
        start, stop = gradient(pal, kind)
        grad = cairo.LinearGradient(cx - r, cy, cx + r, cy)
        grad.add_color_stop_rgb(0.0, *start)
        grad.add_color_stop_rgb(1.0, *stop)
        cr.set_source(grad)
        cr.stroke()
    _draw_gauge_text(cr, cx, cy, min(w, h), p, pal)


class Gauge(Gtk.DrawingArea):
    """A 240-degree percentage gauge widget."""

    def __init__(self, kind: str, pal=None):
        super().__init__()
        self._kind = kind
        self._pal = pal or DARK
        self._percent = 0.0
        self.set_size_request(60, 50)
        self.connect("draw", self._on_draw)

    def set_percent(self, v: float) -> None:
        """Set the gauge value in percent (0-100, clamped) and redraw."""
        self._percent = _clamp(v, 0.0, 100.0)
        self.queue_draw()

    def _on_draw(self, da, cr) -> None:
        """Paint the gauge from the stored value."""
        width, height = da.get_allocated_width(), da.get_allocated_height()
        draw_gauge(cr, width, height, self._pal,
                   self._kind, self._percent)


def draw_stacked_bar(cr, w: float, h: float, segments) -> None:
    """Draw stacked (fraction, colour) segments left to right on a rounded track."""
    rad = min(h, w) * 0.25
    cr.save()
    _rounded_rect(cr, 0.5, 0.5, w - 1.0, h - 1.0, rad)
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.18)
    cr.fill()
    _rounded_rect(cr, 0.5, 0.5, w - 1.0, h - 1.0, rad)
    cr.clip()
    x = 0.0
    for frac, colour in (segments or []):
        seg_w = _clamp(frac) * w
        if seg_w <= 0.0:
            continue
        cr.set_source_rgb(*colour)
        cr.rectangle(x, 0.0, seg_w, h)
        cr.fill()
        x += seg_w
    cr.restore()


class StackedBar(Gtk.DrawingArea):
    """A horizontal bar split into coloured segments."""

    def __init__(self, pal=None):
        super().__init__()
        self._pal = pal or DARK
        self._segments: list[tuple[float, tuple[float, float, float]]] = []
        self.set_size_request(120, 16)
        self.connect("draw", self._on_draw)

    def set_segments(self, segments) -> None:
        """Replace the segments and redraw."""
        self._segments = list(segments) if segments else []
        self.queue_draw()

    def _on_draw(self, da, cr) -> None:
        """Paint the current segments."""
        width, height = da.get_allocated_width(), da.get_allocated_height()
        draw_stacked_bar(cr, width, height, self._segments)


def draw_meter(cr, w: float, h: float, pal, fraction: float,
               colour: tuple[float, float, float]) -> None:
    """Draw one rounded mini bar filled to `fraction` in `colour`."""
    rad = min(h, w) * 0.5
    _rounded_rect(cr, 0.5, 0.5, w - 1.0, h - 1.0, rad)
    cr.set_source_rgb(*pal.gauge_track)
    cr.fill()
    fill_w = _clamp(fraction) * (w - 1.0)
    if fill_w > 0.0:
        cr.save()
        _rounded_rect(cr, 0.5, 0.5, w - 1.0, h - 1.0, rad)
        cr.clip()
        cr.set_source_rgb(*colour)
        cr.rectangle(0.5, 0.5, fill_w, h - 1.0)
        cr.fill()
        cr.restore()


class Meter(Gtk.DrawingArea):
    """A single rounded mini bar used inside table cells."""

    def __init__(self, pal=None):
        super().__init__()
        self._pal = pal or DARK
        self._fraction = 0.0
        self._colour = self._pal.cpu_start
        self.set_size_request(60, 12)
        self.connect("draw", self._on_draw)

    def set_value(self, fraction: float, colour=None) -> None:
        """Set the fill fraction and optional colour, then redraw."""
        self._fraction = _clamp(fraction)
        if colour is not None:
            self._colour = colour
        self.queue_draw()

    def _on_draw(self, da, cr) -> None:
        """Paint the meter from the stored value."""
        width, height = da.get_allocated_width(), da.get_allocated_height()
        draw_meter(cr, width, height, self._pal,
                   self._fraction, self._colour)


def _graph_area(w: float, h: float) -> tuple[float, float, float, float]:
    """Return the plot rectangle (x0, y0, x1, y1) inside the axis margins."""
    return 34.0, 6.0, w - 8.0, h - 16.0


def _value_y(v: float, y0: float, y1: float, y_min: float, y_max: float) -> float:
    """Map a data value to a y coordinate inside [y0, y1]."""
    if y_max <= y_min:
        return y1
    t = _clamp((v - y_min) / (y_max - y_min))
    return y1 - t * (y1 - y0)


def _series_points(values, x0, x1, y0, y1, y_min, y_max, seconds):
    """Map one-value-per-second values (newest last) to plot points."""
    pts = []
    n = len(values)
    if n == 0:
        return pts
    span = float(seconds) if seconds > 0 else float(n)
    for j, v in enumerate(values):
        if v is None:
            continue
        age = n - 1 - j
        x = x1 - age * ((x1 - x0) / span)
        pts.append((max(x, x0), _value_y(v, y0, y1, y_min, y_max)))
    return pts


def _polyline(cr, pts) -> None:
    """Append a polyline through the given points."""
    for i, (x, y) in enumerate(pts):
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)


def _interp_y(pts, x: float) -> float:
    """Return the y of a polyline at x (flat beyond the ends)."""
    if not pts:
        return 0.0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for i in range(1, len(pts)):
        xa, ya = pts[i - 1]
        xb, yb = pts[i]
        if xa <= x <= xb:
            span = xb - xa
            if span <= 0.0:
                return yb
            return ya + (yb - ya) * (x - xa) / span
    return pts[-1][1]


def _envelope(a, b):
    """Merge two polylines into their upper (smallest y) envelope."""
    if not a:
        return list(b)
    if not b:
        return list(a)
    xs = sorted({px for px, _ in a} | {px for px, _ in b})
    return [(x, min(_interp_y(a, x), _interp_y(b, x))) for x in xs]


def _fill_under(cr, pts, y_bottom, colour, envelope=None) -> None:
    """Fill the area under a line in its own colour, fading to transparent.

    `envelope` is the upper edge of the areas already painted by lower
    lines; the fill is clipped to the area above it so two translucent
    areas never stack into a muddy grey.
    """
    if len(pts) < 1:
        return
    top = min(y for _, y in pts)
    cr.save()
    if envelope:
        cr.move_to(envelope[0][0], 0.0)
        for ex, ey in envelope:
            cr.line_to(ex, ey)
        cr.line_to(envelope[-1][0], 0.0)
        cr.close_path()
        cr.clip()
        cr.new_sub_path()
    cr.move_to(pts[0][0], y_bottom)
    for px, py in pts:
        cr.line_to(px, py)
    cr.line_to(pts[-1][0], y_bottom)
    cr.close_path()
    grad = cairo.LinearGradient(0, top, 0, max(y_bottom, top + 1.0))
    grad.add_color_stop_rgba(0.0, *colour, 0.35)
    grad.add_color_stop_rgba(1.0, *colour, 0.0)
    cr.set_source(grad)
    cr.fill()
    cr.restore()


def _paint_areas(cr, plotted, y_bottom) -> None:
    """Fill every series area, lowest line first, each clipped to its own band.

    Painting the lowest line first and clipping the higher lines to the
    area above the envelope already painted keeps each area in its own
    colour instead of stacking translucent tints into grey.
    """
    order = sorted((i for i in range(len(plotted)) if plotted[i][1]),
                   key=lambda i: -max(y for _, y in plotted[i][1]))
    envelope = None
    for i in order:
        colour, pts = plotted[i]
        _fill_under(cr, pts, y_bottom, colour, envelope)
        envelope = _envelope(envelope, pts)


def _text_centered(cr, cx, cy, text) -> None:
    """Draw text centred on (cx, cy) using the current font and colour."""
    m = cr.text_extents(text)
    cr.move_to(cx - (m.x_bearing + m.width / 2), cy - (m.y_bearing + m.height / 2))
    cr.show_text(text)


def _text_right(cr, x_right, cy, text) -> None:
    """Draw text right-aligned to x_right, vertically centred on cy."""
    m = cr.text_extents(text)
    cr.move_to(x_right - (m.x_bearing + m.width), cy - (m.y_bearing + m.height / 2))
    cr.show_text(text)


def draw_line_graph(cr, w, h, pal, series, y_min, y_max, threshold=None,
                    unit="°C", seconds=300) -> None:
    """Draw a scrolling multi-series graph with grid, time and threshold."""
    x0, y0, x1, y1 = _graph_area(w, h)
    plot_w = x1 - x0
    cr.set_line_width(1.0)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(9)
    g = math.ceil(y_min / 10.0) * 10.0
    while g <= y_max + 1e-9:
        y = _value_y(g, y0, y1, y_min, y_max)
        cr.set_source_rgba(*pal.border, 0.6)
        cr.move_to(x0, y)
        cr.line_to(x1, y)
        cr.stroke()
        cr.set_source_rgb(*pal.muted)
        _text_right(cr, x0 - 3, y, str(int(g)))
        g += 10.0
    now = time.time()
    for age in range(0, int(seconds) + 1, 60):
        x = x1 - age * (plot_w / float(seconds))
        cr.set_source_rgb(*pal.muted)
        _text_centered(cr, x, y1 + 9, time.strftime("%H:%M", time.localtime(now - age)))
    plotted = [(c, _series_points(v, x0, x1, y0, y1, y_min, y_max, seconds))
               for c, v in (series or [])]
    _paint_areas(cr, plotted, y1)
    for colour, pts in plotted:
        cr.set_line_width(2.0)
        cr.set_source_rgb(*colour)
        _polyline(cr, pts)
        cr.stroke()
    if threshold is not None:
        y = _value_y(threshold, y0, y1, y_min, y_max)
        cr.set_line_width(1.5)
        cr.set_dash([4.0, 3.0], 0.0)
        cr.set_source_rgb(*pal.threshold)
        cr.move_to(x0, y)
        cr.line_to(x1, y)
        cr.stroke()
        cr.set_dash([], 0.0)
        _text_right(cr, x1 - 2, y - 6, f"{int(threshold)} {unit}")


class LineGraph(Gtk.DrawingArea):
    """A scrolling multi-series temperature graph with a ring buffer."""

    def __init__(self, colors, y_min, y_max, pal=None, threshold=None,
                 unit="°C", seconds=300):
        super().__init__()
        self._pal = pal or DARK
        self._y_min = float(y_min)
        self._y_max = float(y_max)
        self._threshold = threshold
        self._unit = unit
        self._seconds = max(1, int(seconds))
        self._series = [[c, []] for c in colors]
        self.set_size_request(120, 60)
        self.connect("draw", self._on_draw)

    def push(self, values_per_series) -> None:
        """Append one sample per series, keeping the last `seconds` points."""
        for entry, v in zip(self._series, values_per_series):
            buf = entry[1]
            buf.append(v)
            if len(buf) > self._seconds:
                del buf[0]
        self.queue_draw()

    def expand_range(self, lo: float, hi: float) -> None:
        """Widen the y range to include lo/hi (base range never shrinks)."""
        changed = False
        if lo is not None and lo < self._y_min:
            self._y_min = lo
            changed = True
        if hi is not None and hi > self._y_max:
            self._y_max = hi
            changed = True
        if changed:
            self.queue_draw()

    def _on_draw(self, da, cr) -> None:
        """Paint the graph from the ring buffers."""
        width, height = da.get_allocated_width(), da.get_allocated_height()
        draw_line_graph(cr, width, height, self._pal,
                        [(e[0], e[1]) for e in self._series], self._y_min,
                        self._y_max, self._threshold, self._unit, self._seconds)


def _spark_points(values, x0, x1, y0, y1, maxv):
    """Map values across the full width, scaled to maxv (at least 1)."""
    pts = []
    n = len(values)
    if n == 0:
        return pts
    if n == 1:
        return [(x1, y1 - (values[0] / maxv) * (y1 - y0))]
    for j, v in enumerate(values):
        x = x0 + (x1 - x0) * j / (n - 1)
        pts.append((x, y1 - _clamp(v / maxv) * (y1 - y0)))
    return pts


def draw_sparkline(cr, w, h, pal, series) -> None:
    """Draw auto-scaled filled series with no axes."""
    if not series:
        return
    maxv = 1.0
    for _, values in series:
        for v in values:
            if v > maxv:
                maxv = v
    x0, x1, y0, y1 = 1.0, w - 1.0, 1.0, h - 1.0
    plotted = [(c, _spark_points(v, x0, x1, y0, y1, maxv)) for c, v in series]
    _paint_areas(cr, plotted, y1)
    for colour, pts in plotted:
        cr.set_line_width(1.5)
        cr.set_source_rgb(*colour)
        _polyline(cr, pts)
        cr.stroke()


class Sparkline(Gtk.DrawingArea):
    """A compact auto-scaled multi-series sparkline (60 points)."""

    def __init__(self, colors, pal=None, points=60):
        super().__init__()
        self._pal = pal or DARK
        self._points = max(1, int(points))
        self._series = [[c, []] for c in colors]
        self.set_size_request(120, 30)
        self.connect("draw", self._on_draw)

    def push(self, *values) -> None:
        """Append one sample per series, keeping the last `points` values."""
        for entry, v in zip(self._series, values):
            buf = entry[1]
            buf.append(v)
            if len(buf) > self._points:
                del buf[0]
        self.queue_draw()

    def _on_draw(self, da, cr) -> None:
        """Paint the sparkline from the ring buffers."""
        width, height = da.get_allocated_width(), da.get_allocated_height()
        draw_sparkline(cr, width, height, self._pal,
                       [(e[0], e[1]) for e in self._series])
