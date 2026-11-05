# SPDX-License-Identifier: GPL-3.0-or-later
"""The four gauge cards: CPU, GPU, MEMORY, GPU MEMORY."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from spaced_monitor import format as fmt
from spaced_monitor.theme import palette, gradient, _css_colour
from spaced_monitor.widgets import (ELLIPSIZE_END, ELLIPSIZE_NONE, Gauge,
                                    StackedBar, LineGraph, Meter, Sparkline)


def _hbox(spacing: int = 6) -> Gtk.Box:
    """Create a horizontal box."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    return box


def _vbox(spacing: int = 4) -> Gtk.Box:
    """Create a vertical box."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    return box


def _wrap(lbl: Gtk.Label) -> None:
    """Let a label wrap instead of being cut off.

    A wrapping label's minimum width is its longest word, so the card can
    shrink to that.  Pinning a label's width with set_size_request instead
    would raise the card's minimum width and stop the window shrinking.
    """
    lbl.set_line_wrap(True)
    lbl.set_line_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    lbl.set_justify(Gtk.Justification.FILL)
    lbl.set_ellipsize(ELLIPSIZE_NONE)


def _label(text: str, css_class: str = "value") -> Gtk.Label:
    """Create a label with a CSS class."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class(css_class)
    lbl.set_xalign(0.0)
    _wrap(lbl)
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Create a muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    _wrap(lbl)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Create a big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    _wrap(lbl)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Create a card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    _wrap(lbl)
    return lbl


_MAX_LINES = 2
_TITLE_LINES = 3
_BAR_MIN_W = 40


def _nat_width(lbl: Gtk.Label) -> int:
    """Single-line natural width, measured even when the label is hidden.

    A hidden label reports zero width, so it is shown for the measurement and
    restored afterwards.
    """
    was = lbl.get_visible()
    lbl.set_visible(True)
    lbl.set_size_request(-1, -1)
    nat = lbl.get_preferred_width()[1]
    lbl.set_visible(was)
    return nat


def _budget_lines(lbl: Gtk.Label, avail: int, max_lines: int) -> bool:
    """Ask a wrapping label for the height its wrapped text needs.

    GTK budgets a wrapping label's height for a single line, so the extra
    lines are requested explicitly.  Only the height is requested: a width
    request would raise the card's minimum width and stop the window
    shrinking.  The previous pass's request is cleared first, because a
    label's preferred height is its own size request, so measuring before
    clearing would multiply the request on every resize.
    """
    lbl.set_size_request(-1, -1)
    nat = lbl.get_preferred_width()[1]
    if nat <= avail:
        return True
    line_h = max(1, lbl.get_preferred_height()[1])
    lines = -(-nat // max(1, avail))
    if lines > max_lines:
        return False
    lbl.set_size_request(-1, line_h * lines)
    return True


class _Sizing:
    """Mixin: re-measure a card once per layout pass.

    A size-allocate handler must not change visibility synchronously, or the
    same pass re-enters it; the work is deferred to GLib.idle_add and guarded
    so at most one measurement is queued per card.
    """

    def _connect_sizing(self) -> None:
        self.connect("size-allocate", self._on_size_allocate)

    def _on_size_allocate(self, _widget, allocation) -> None:
        # Only a new size needs a re-measure: _fit's own visibility changes
        # trigger relayouts at the same size, which must not queue it again.
        size = (allocation.width, allocation.height)
        if getattr(self, "_sa_pending", False) or size == getattr(self, "_sa_size", None):
            return
        self._sa_size = size
        self._sa_pending = True
        GLib.idle_add(self._fit)

    def _fit(self) -> bool:
        """Hide detail labels that no longer fit; False dequeues the callback."""
        return False

    def queue_fit(self) -> None:
        """Queue a re-measure after the card's text changed.

        Text changes alter a wrapping label's line count without changing the
        card's allocated width, so no size-allocate fires to trigger _fit.
        """
        GLib.idle_add(self._fit)


class _CardBase(Gtk.Box, _Sizing):
    """Shared card box with a gauge and info column."""

    def __init__(self, kind: str, title_text: str, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._gauge = Gauge(kind, pal)
        self._info = _vbox(spacing=2)
        self._title_lbl = _title(title_text)
        self._model_lbl = _muted("")
        self._line1 = _label("", "value")
        self._line2 = _label("", "value")
        self._info.pack_start(self._title_lbl, expand=False, fill=False,
                        padding=0)
        self._info.pack_start(self._model_lbl, expand=False, fill=False,
                        padding=0)
        self._info.pack_start(self._line1, expand=False, fill=False,
                        padding=0)
        self._info.pack_start(self._line2, expand=False, fill=False,
                        padding=0)
        row = _hbox(spacing=10)
        row.pack_start(self._gauge, expand=False, fill=False, padding=0)
        row.pack_start(self._info, expand=True, fill=True, padding=0)
        self.pack_start(row, True, True, 0)
        self._connect_sizing()

    def _fit(self) -> bool:
        self._sa_pending = False
        w = self.get_allocated_width()
        if w < 1:
            return False
        gauge_w = self._gauge.get_allocated_width()
        avail = max(1, w - gauge_w - 10)
        labels = [self._title_lbl, self._model_lbl, self._line1, self._line2]
        nat = [_nat_width(l) for l in labels]
        # Drop order: model (idx 1), line2 (idx 3), line1 (idx 2).  The title
        # is never dropped: it is the shortest label and identifies the card.
        show = [True, True, True, True]
        for idx in (1, 3, 2):
            needed = max(nat[i] for i in range(4) if show[i])
            if needed <= avail:
                break
            show[idx] = False
        for l, s in zip(labels, show):
            if l.get_visible() != s:
                l.set_visible(s)
        return False

    def set_palette(self, pal) -> None:
        """Swap the palette on theme change."""
        self._pal = pal
        self._gauge._pal = pal
        self._gauge.queue_draw()


class CpuCard(_CardBase):
    """CPU card: gauge, model, temp, frequency."""

    def __init__(self, pal) -> None:
        super().__init__("cpu", "CPU", pal)

    def update(self, snapshot) -> None:
        """Refresh from a Snapshot."""
        cpu = snapshot.cpu
        self._gauge.set_percent(cpu.percent)
        self._title_lbl.set_text("CPU")
        self._model_lbl.set_text(cpu.model or fmt.EMDASH)
        self._line1.set_text(fmt.temp(cpu.temp_c))
        self._line2.set_text(fmt.ghz(cpu.freq_mhz))
        self.queue_fit()


class GpuCard(_CardBase):
    """GPU card: gauge, name, temp, power."""

    def __init__(self, pal) -> None:
        super().__init__("gpu", "GPU", pal)

    def update(self, snapshot) -> None:
        """Refresh from a Snapshot."""
        gpu = snapshot.gpu
        if gpu is None:
            self._gauge.set_percent(0)
            self._title_lbl.set_text("GPU")
            self._model_lbl.set_text(fmt.EMDASH)
            self._line1.set_text(fmt.EMDASH)
            self._line2.set_text(fmt.EMDASH)
            self.queue_fit()
            return
        self._gauge.set_percent(gpu.percent or 0)
        self._title_lbl.set_text("GPU")
        self._model_lbl.set_text(gpu.name or fmt.EMDASH)
        self._line1.set_text(fmt.temp(gpu.temp_c))
        self._line2.set_text(fmt.watts(gpu.power_w))
        self.queue_fit()


class _MemoryLikeCard(Gtk.Box, _Sizing):
    """MEMORY and GPU MEMORY cards: gauge, pair, stacked bar, legend.

    The two cards differ only in which numbers feed the gauge and the legend;
    the layout, the palette swap and the responsive rules are shared.
    """

    def __init__(self, kind: str, title_text: str, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._gauge = Gauge(kind, pal)
        self._bar = StackedBar(pal)
        self._title_lbl = _title(title_text)
        self._big_lbl = _big("")
        self._pct_lbl = _muted("")
        self._legend = _muted("")
        self._legend.set_size_request(-1, -1)
        self._vbox = _vbox(spacing=4)
        top = _hbox(spacing=10)
        top.pack_start(self._gauge, expand=False, fill=False, padding=0)
        self._info = _vbox(spacing=2)
        self._info.pack_start(self._title_lbl, expand=False, fill=False,
                        padding=0)
        self._info.pack_start(self._big_lbl, expand=False, fill=False,
                        padding=0)
        self._info.pack_start(self._pct_lbl, expand=False, fill=False,
                        padding=0)
        top.pack_start(self._info, expand=True, fill=True, padding=0)
        self._vbox.pack_start(top, expand=False, fill=False, padding=0)
        self._vbox.pack_start(self._bar, expand=False, fill=True, padding=0)
        self._vbox.pack_start(self._legend, expand=False, fill=False, padding=0)
        self.pack_start(self._vbox, True, True, 0)
        self._connect_sizing()

    def _fit(self) -> bool:
        self._sa_pending = False
        w = self.get_allocated_width()
        if w < 1:
            return False
        gauge_w = self._gauge.get_allocated_width()
        avail = max(1, w - gauge_w - 10)
        info_labels = [self._title_lbl, self._big_lbl, self._pct_lbl]
        nat_info = [_nat_width(l) for l in info_labels]
        legend_nat = _nat_width(self._legend)
        # The legend is a child of _vbox, so it is offered the card's *content*
        # width, not its border-to-border width: the card's CSS padding is
        # not available to it.  Comparing against the box the legend actually
        # lives in beats recomputing that padding.
        legend_avail = self._vbox.get_allocated_width()
        if legend_avail < 1:
            legend_avail = w
        show_big = True
        show_pct = True
        show_bar = True
        # A legend wider than the box it sits in would pin the card's minimum
        # width, so it is dropped rather than allowed to hold the card open.
        show_legend = bool(self._legend.get_text()) and legend_nat <= legend_avail
        needed = max(nat_info)
        if needed > avail:
            show_pct = False
            needed = max(nat_info[0], nat_info[1])
        if needed > avail:
            show_big = False
            needed = nat_info[0]
        if needed > avail:
            show_bar = False
        if self._legend.get_visible() != show_legend:
            self._legend.set_visible(show_legend)
        if self._pct_lbl.get_visible() != show_pct:
            self._pct_lbl.set_visible(show_pct)
        if self._bar.get_visible() != show_bar:
            self._bar.set_visible(show_bar)
        if self._big_lbl.get_visible() != show_big:
            self._big_lbl.set_visible(show_big)
        if not self._title_lbl.get_visible():
            self._title_lbl.set_visible(True)
        # A visible label that is wider than the space offered to it wraps
        # (see _wrap); GTK still budgets its height for one line, so the
        # extra lines are requested explicitly.
        if show_legend:
            _budget_lines(self._legend, legend_avail, _MAX_LINES)
        else:
            self._legend.set_size_request(-1, -1)
        return False

    def set_palette(self, pal) -> None:
        """Swap the palette on theme change."""
        self._pal = pal
        self._gauge._pal = pal
        self._bar._pal = pal
        self._gauge.queue_draw()
        self._bar.queue_draw()


class MemoryCard(_MemoryLikeCard):
    """MEMORY card: gauge, pair, stacked bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__("memory", "MEMORY", pal)

    def update(self, snapshot) -> None:
        """Refresh from a Snapshot."""
        mem = snapshot.memory
        used = mem.total - mem.available
        pct = (used / mem.total * 100) if mem.total else 0
        self._gauge.set_percent(pct)
        self._title_lbl.set_text("MEMORY")
        self._big_lbl.set_text(fmt.pair_gb(used, mem.total))
        self._pct_lbl.set_text(f"{int(round(pct))}% used")
        total = mem.total or 1
        segs = [
            (mem.apps / total, self._pal.cpu_start),
            (mem.cache / total, self._pal.gpu_memory_start),
            (mem.available / total, self._pal.cpu_end),
        ]
        self._bar.set_segments(segs)
        self._legend.set_text(
            f"Apps {fmt.bytes_gb(mem.apps)}  "
            f"Cache {fmt.bytes_gb(mem.cache)}  "
            f"Available {fmt.bytes_gb(mem.available)}"
        )
        self.queue_fit()


class GpuMemoryCard(_MemoryLikeCard):
    """GPU MEMORY card: gauge, pair, bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__("gpu_memory", "GPU MEMORY", pal)

    def update(self, snapshot) -> None:
        """Refresh from a Snapshot."""
        gpu = snapshot.gpu
        mem = snapshot.memory
        if gpu and gpu.mem_total:
            used = gpu.mem_used or 0
            total = gpu.mem_total
            pct = (used / total * 100) if total else 0
            self._gauge.set_percent(pct)
            self._big_lbl.set_text(fmt.pair_gb(used, total))
            self._pct_lbl.set_text(f"{int(round(pct))}% used")
            segs = [
                (used / total, self._pal.gpu_memory_start),
                ((total - used) / total, self._pal.cpu_end),
            ]
            self._bar.set_segments(segs)
            swap = fmt.pair_gb(mem.swap_used, mem.swap_total)
            avail = fmt.bytes_gb(total - used)
            self._legend.set_text(f"Swap {swap}  Available {avail}")
        else:
            self._gauge.set_percent(0)
            self._big_lbl.set_text(fmt.EMDASH)
            self._pct_lbl.set_text("")
            self._bar.set_segments([])
            self._legend.set_text("")
        self.queue_fit()

def _dot(pal, colour: tuple[float, float, float], text: str) -> str:
    """Return label markup: a coloured dot plus text in the palette colour."""
    hexc = _css_colour(colour)
    return f"<span foreground='{hexc}'>{text}</span>"


class TemperatureCard(Gtk.Box):
    """Temperature card: CPU/GPU line graph with an 80 °C threshold."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._graph = LineGraph([pal.cpu_temp, pal.gpu_temp], 30, 90,
                                pal=pal, threshold=80, unit="°C", seconds=300)
        self._title_lbl = _title("Temperature · last 5 minutes")
        self._cpu_lbl = _muted("")
        self._gpu_lbl = _muted("")
        self._cpu_val: float | None = None
        self._gpu_val: float | None = None
        vbox = _vbox(spacing=6)
        head = _hbox(spacing=10)
        head.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        legend = _vbox(spacing=2)
        legend.pack_start(self._cpu_lbl, expand=False, fill=False, padding=0)
        legend.pack_start(self._gpu_lbl, expand=False, fill=False, padding=0)
        head.pack_start(legend, expand=True, fill=False, padding=0)
        vbox.pack_start(head, expand=False, fill=False, padding=0)
        vbox.pack_start(self._graph, expand=True, fill=True, padding=0)
        self.pack_start(vbox, True, True, 0)

    def set_palette(self, pal) -> None:
        """Swap palette and re-colour the legend."""
        self._pal = pal
        self._graph._pal = pal
        self._graph._series = [[pal.cpu_temp, e[1]] for e in self._graph._series]
        self._graph.queue_draw()
        self._render_legend()

    def update(self, snapshot) -> None:
        """Push CPU/GPU temps and widen the y range when outside 30-90."""
        cpu = snapshot.cpu.temp_c
        gpu = snapshot.gpu.temp_c if snapshot.gpu else None
        self._graph.push((cpu, gpu))
        vals = [v for v in (cpu, gpu) if v is not None]
        if vals:
            self._graph.expand_range(min(vals), max(vals))
        self._cpu_val, self._gpu_val = cpu, gpu
        self._render_legend()

    def _render_legend(self) -> None:
        """Colour the legend dots and show the latest CPU/GPU temperature."""
        self._cpu_lbl.set_markup(
            _dot(self._pal, self._pal.cpu_temp,
                 f"● CPU {fmt.temp(self._cpu_val)}"))
        self._gpu_lbl.set_markup(
            _dot(self._pal, self._pal.gpu_temp,
                 f"● GPU {fmt.temp(self._gpu_val)}"))


class DiskCard(Gtk.Box):
    """Disk activity card: read/write rates, storage bar, sparkline."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._title_lbl = _title("Disk activity")
        self._read_lbl = _muted("")
        self._write_lbl = _muted("")
        for lbl in (self._read_lbl, self._write_lbl):
            lbl.set_ellipsize(ELLIPSIZE_END)
        self._storage_lbl = _muted("")
        self._pct_lbl = _muted("")
        self._bar = Meter(pal)
        self._spark = Sparkline([pal.disk_read, pal.disk_write], pal)
        self._last = None
        vbox = _vbox(spacing=6)
        vbox.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        rates = _hbox(spacing=16)
        rates.pack_start(self._read_lbl, expand=True, fill=False, padding=0)
        rates.pack_start(self._write_lbl, expand=True, fill=False, padding=0)
        vbox.pack_start(rates, expand=False, fill=False, padding=0)
        store = _vbox(spacing=2)
        store.pack_start(self._storage_lbl, expand=False, fill=False, padding=0)
        store.pack_start(self._bar, expand=False, fill=True, padding=0)
        store.pack_start(self._pct_lbl, expand=False, fill=False, padding=0)
        vbox.pack_start(store, expand=False, fill=False, padding=0)
        vbox.pack_start(self._spark, expand=False, fill=True, padding=0)
        self.pack_start(vbox, True, True, 0)

    def set_palette(self, pal) -> None:
        """Swap palette and re-colour the rate labels."""
        self._pal = pal
        self._bar._pal = pal
        self._spark._pal = pal
        self._spark._series = [[pal.disk_read, e[1]] for e in self._spark._series]
        self._bar.queue_draw()
        self._spark.queue_draw()
        if self._last is not None:
            self._render(self._last)

    def update(self, snapshot) -> None:
        """Push read/write rates to the sparkline and refresh the labels."""
        disk = snapshot.disk
        self._spark.push(disk.read_bps, disk.write_bps)
        self._last = disk
        self._render(disk)

    def _render(self, disk) -> None:
        """Colour read/write values and set the storage bar and percent."""
        self._read_lbl.set_markup(
            _dot(self._pal, self._pal.disk_read, f"Read {fmt.rate(disk.read_bps)}"))
        self._write_lbl.set_markup(
            _dot(self._pal, self._pal.disk_write, f"Write {fmt.rate(disk.write_bps)}"))
        if disk.total:
            frac = (disk.used or 0) / disk.total
            self._bar.set_value(frac, self._pal.memory_start)
            self._storage_lbl.set_text(f"Storage {fmt.pair_gb(disk.used, disk.total)}")
            self._pct_lbl.set_text(fmt.percent(frac * 100))
        else:
            self._bar.set_value(0.0)
            self._storage_lbl.set_text(f"Storage {fmt.pair_gb(disk.used, disk.total)}")
            self._pct_lbl.set_text("")


class NetworkCard(Gtk.Box):
    """Network card: download/upload rates and a sparkline."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._title_lbl = _title("Network")
        self._dl_lbl = _muted("")
        self._ul_lbl = _muted("")
        self._spark = Sparkline([pal.net_download, pal.net_upload], pal)
        self._last = None
        vbox = _vbox(spacing=6)
        vbox.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        rates = _hbox(spacing=16)
        rates.pack_start(self._dl_lbl, expand=True, fill=False, padding=0)
        rates.pack_start(self._ul_lbl, expand=True, fill=False, padding=0)
        vbox.pack_start(rates, expand=False, fill=False, padding=0)
        vbox.pack_start(self._spark, expand=False, fill=True, padding=0)
        self.pack_start(vbox, True, True, 0)

    def set_palette(self, pal) -> None:
        """Swap palette and re-colour the rate labels."""
        self._pal = pal
        self._spark._pal = pal
        self._spark._series = [[pal.net_download, e[1]] for e in self._spark._series]
        self._spark.queue_draw()
        if self._last is not None:
            self._render(self._last)

    def update(self, snapshot) -> None:
        """Push download/upload rates to the sparkline and refresh the labels."""
        net = snapshot.net
        self._spark.push(net.rx_bps, net.tx_bps)
        self._last = net
        self._render(net)

    def _render(self, net) -> None:
        """Colour the download and upload values."""
        self._dl_lbl.set_markup(
            _dot(self._pal, self._pal.net_download,
                 f"Download {fmt.rate(net.rx_bps)}"))
        self._ul_lbl.set_markup(
            _dot(self._pal, self._pal.net_upload,
                 f"Upload {fmt.rate(net.tx_bps)}"))
