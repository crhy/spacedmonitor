# SPDX-License-Identifier: GPL-3.0-or-later
"""The four gauge cards: CPU, GPU, MEMORY, GPU MEMORY."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

from spaced_monitor import format as fmt
from spaced_monitor.collect import ram_temperatures
from spaced_monitor.theme import _css_colour
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
    lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_justify(Gtk.Justification.LEFT)
    lbl.set_ellipsize(ELLIPSIZE_NONE)
    lbl.set_max_width_chars(16)


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
        self._gauge.set_size_request(92, 76)
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
        row.pack_start(self._gauge, expand=False, fill=True, padding=0)
        row.pack_start(self._info, expand=True, fill=True, padding=0)
        self.pack_start(row, True, True, 0)
        self._connect_sizing()

    def _fit(self) -> bool:
        self._sa_pending = False
        for cell in (self._title_lbl, self._model_lbl, self._line1, self._line2):
            cell.set_visible(True)
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
            self._gauge.set_percent(None)
            self._title_lbl.set_text("GPU")
            self._model_lbl.set_text(fmt.EMDASH)
            self._line1.set_text(fmt.EMDASH)
            self._line2.set_text(fmt.EMDASH)
            self.queue_fit()
            return
        self._gauge.set_percent(gpu.percent)
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
        self._gauge.set_size_request(76, 56)
        self._bar = StackedBar(pal)
        self._bar.set_size_request(40, 6)
        self._title_lbl = _title(title_text)
        self._big_lbl = _big("")
        self._legend = _muted("")
        self._legend.set_size_request(-1, -1)
        self._vbox = _vbox(spacing=2)
        top = _hbox(spacing=10)
        top.pack_start(self._gauge, expand=False, fill=True, padding=0)
        self._info = _vbox(spacing=2)
        self._info.pack_start(self._title_lbl, False, False, 0)
        self._info.pack_start(self._big_lbl, expand=False, fill=False,
                        padding=0)
        top.pack_start(self._info, expand=True, fill=True, padding=0)
        self._vbox.pack_start(top, expand=True, fill=True, padding=0)
        self._vbox.pack_start(self._bar, expand=False, fill=True, padding=0)
        self._vbox.pack_start(self._legend, expand=False, fill=False, padding=0)
        self.pack_start(self._vbox, True, True, 0)
        self._connect_sizing()

    def _fit(self) -> bool:
        self._sa_pending = False
        for cell in (self._title_lbl, self._big_lbl, self._legend):
            cell.set_visible(True)
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
        total = mem.total or 1
        free = max(0, mem.available - mem.cache)   # apps + cache + free = total
        segs = [
            (mem.apps / total, self._pal.cpu_start),
            (mem.cache / total, self._pal.gpu_memory_start),
            (free / total, self._pal.cpu_end),
        ]
        self._bar.set_segments(segs)
        self._legend.set_text(
            f"Apps {fmt.bytes_gb(mem.apps)}  "
            f"Cache {fmt.bytes_gb(mem.cache)}\n"
            f"Free {fmt.bytes_gb(free)}"
        )
        ram = ram_temperatures(snapshot.temperatures)
        self._legend.set_text(self._legend.get_text() + " · RAM " +
                              (fmt.temp(max(t.celsius for t in ram)) if ram else fmt.EMDASH))
        self._legend.set_tooltip_text("RAM temperature: hottest available RAM sensor; — means unavailable.")
        self.queue_fit()


class GpuMemoryCard(_MemoryLikeCard):
    """GPU MEMORY card: gauge, pair, bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__("gpu_memory", "GPU MEMORY", pal)

    def update(self, snapshot) -> None:
        """Refresh from a Snapshot."""
        gpu = snapshot.gpu
        self._title_lbl.set_text("VRAM" + (f" · {gpu.name}" if gpu else ""))
        if gpu and gpu.mem_total and gpu.mem_used is not None:
            used = gpu.mem_used
            total = gpu.mem_total
            pct = (used / total * 100) if total else 0
            self._gauge.set_percent(pct)
            self._big_lbl.set_text(fmt.pair_gb(used, total))
            segs = [
                (used / total, self._pal.gpu_memory_start),
                ((total - used) / total, self._pal.cpu_end),
            ]
            self._bar.set_segments(segs)
            avail = fmt.bytes_gb(total - used)
            self._legend.set_text(f"Available {avail}")
        else:
            self._gauge.set_percent(None)
            self._big_lbl.set_text(fmt.EMDASH)
            self._bar.set_segments([])
            self._legend.set_text("")
        self.queue_fit()

def _dot(pal, colour: tuple[float, float, float], text: str) -> str:
    """Return label markup: a coloured dot plus text in the palette colour."""
    hexc = _css_colour(colour)
    return f"<span foreground='{hexc}'>{text}</span>"


class TemperatureCard(Gtk.Box):
    """Temperature card: CPU/primary GPU history, without invented limits."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._graph = LineGraph([pal.cpu_temp, pal.gpu_temp], 86, 194,
                                pal=pal, unit="°F", seconds=300, compact=True)
        self._title_lbl = _title("Temperature · last 5 minutes")
        self._graph.set_size_request(120, 60)
        self._cpu_lbl = _muted("")
        self._gpu_lbl = _muted("")
        self._cpu_val: float | None = None
        self._gpu_val: float | None = None
        self._gpu_name = "GPU"
        vbox = _vbox(spacing=2)
        vbox.pack_start(self._title_lbl, False, False, 0)
        legend = _hbox(spacing=12)
        legend.pack_start(self._cpu_lbl, expand=False, fill=False, padding=0)
        legend.pack_start(self._gpu_lbl, expand=False, fill=False, padding=0)
        vbox.pack_start(legend, expand=False, fill=False, padding=0)
        vbox.pack_start(self._graph, expand=True, fill=True, padding=0)
        self.pack_start(vbox, True, True, 0)

    def set_palette(self, pal) -> None:
        """Swap palette and re-colour the legend."""
        self._pal = pal
        self._graph._pal = pal
        self._graph._series = [[c, e[1]] for c, e in zip((pal.cpu_temp, pal.gpu_temp), self._graph._series)]
        self._graph.queue_draw()
        self._render_legend()

    def update(self, snapshot, record=True) -> None:
        """Refresh CPU/GPU temperatures in the selected display unit."""
        cpu = snapshot.cpu.temp_c
        gpu = snapshot.gpu.temp_c if snapshot.gpu else None
        unit = fmt.temperature_unit()
        if self._graph._unit != unit:
            convert = (lambda v: (v - 32) * 5 / 9) if fmt.CELSIUS else fmt.fahrenheit
            for series in self._graph._series:
                series[1][:] = [convert(v) if v is not None else None for v in series[1]]
            self._graph._y_min = convert(self._graph._y_min)
            self._graph._y_max = convert(self._graph._y_max)
            self._graph._unit = unit
        cpu_f = fmt.temperature_value(cpu)
        gpu_f = fmt.temperature_value(gpu)
        if record:
            self._graph.push((cpu_f, gpu_f))
        else:
            self._graph.queue_draw()
        vals = [v for v in (cpu_f, gpu_f) if v is not None]
        if vals:
            self._graph.expand_range(min(vals), max(vals))
        self._cpu_val, self._gpu_val = cpu, gpu
        self._gpu_name = snapshot.gpu.name if snapshot.gpu and snapshot.gpu.name else "GPU"
        self._gpu_lbl.set_tooltip_text(self._gpu_name)
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
        vbox = _vbox(spacing=2)
        vbox.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        rates = _hbox(spacing=16)
        rates.pack_start(self._read_lbl, expand=True, fill=False, padding=0)
        rates.pack_start(self._write_lbl, expand=True, fill=False, padding=0)
        vbox.pack_start(rates, expand=False, fill=False, padding=0)
        store = _vbox(spacing=2)
        store.pack_start(self._storage_lbl, expand=False, fill=False, padding=0)
        usage = _hbox(spacing=4)
        usage.pack_start(self._bar, True, True, 0)
        usage.pack_end(self._pct_lbl, False, False, 0)
        store.pack_start(usage, False, False, 0)
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
        vbox = _vbox(spacing=2)
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
