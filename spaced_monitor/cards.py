# SPDX-License-Identifier: GPL-3.0-or-later
"""The four gauge cards: CPU, GPU, MEMORY, GPU MEMORY."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from spaced_monitor import format as fmt
from spaced_monitor.theme import palette, gradient, _css_colour
from spaced_monitor.widgets import Gauge, StackedBar, LineGraph, Meter, Sparkline


def _hbox(spacing: int = 6) -> Gtk.Box:
    """Create a horizontal box."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    return box


def _vbox(spacing: int = 4) -> Gtk.Box:
    """Create a vertical box."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    return box


def _label(text: str, css_class: str = "value") -> Gtk.Label:
    """Create a label with a CSS class."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class(css_class)
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Create a muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Create a big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Create a card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


class _CardBase(Gtk.Box):
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
        self.connect("size-allocate", self._on_size_allocate)

    def _on_size_allocate(self, _widget, _allocation) -> None:
        """Hide detail lines below 260px, model below 150px."""
        w = self.get_allocated_width()
        if w < 150:
            self._title_lbl.set_visible(True)
            self._model_lbl.set_visible(False)
            self._line1.set_visible(False)
            self._line2.set_visible(False)
        elif w < 260:
            self._title_lbl.set_visible(True)
            self._model_lbl.set_visible(False)
            self._line1.set_visible(False)
            self._line2.set_visible(False)
        else:
            self._title_lbl.set_visible(True)
            self._model_lbl.set_visible(True)
            self._line1.set_visible(True)
            self._line2.set_visible(True)

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
            return
        self._gauge.set_percent(gpu.percent or 0)
        self._title_lbl.set_text("GPU")
        self._model_lbl.set_text(gpu.name or fmt.EMDASH)
        self._line1.set_text(fmt.temp(gpu.temp_c))
        self._line2.set_text(fmt.watts(gpu.power_w))


class MemoryCard(Gtk.Box):
    """MEMORY card: gauge, pair, stacked bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._gauge = Gauge("memory", pal)
        self._bar = StackedBar(pal)
        self._title_lbl = _title("MEMORY")
        self._big_lbl = _big("")
        self._pct_lbl = _muted("")
        self._legend = _muted("")
        vbox = _vbox(spacing=4)
        top = _hbox(spacing=10)
        top.pack_start(self._gauge, expand=False, fill=False, padding=0)
        info = _vbox(spacing=2)
        info.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        info.pack_start(self._big_lbl, expand=False, fill=False, padding=0)
        info.pack_start(self._pct_lbl, expand=False, fill=False, padding=0)
        top.pack_start(info, expand=True, fill=True, padding=0)
        vbox.pack_start(top, expand=False, fill=False, padding=0)
        vbox.pack_start(self._bar, expand=False, fill=True, padding=0)
        vbox.pack_start(self._legend, expand=False, fill=False, padding=0)
        self.pack_start(vbox, True, True, 0)
        self.connect("size-allocate", self._on_size_allocate)

    def _on_size_allocate(self, _widget, _allocation) -> None:
        """Hide detail lines below 260px, bar/legend below 150px."""
        w = self.get_allocated_width()
        if w < 150:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(False)
            self._pct_lbl.set_visible(False)
            self._bar.set_visible(False)
            self._legend.set_visible(False)
        elif w < 260:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(False)
            self._pct_lbl.set_visible(False)
            self._bar.set_visible(False)
            self._legend.set_visible(False)
        else:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(True)
            self._pct_lbl.set_visible(True)
            self._bar.set_visible(True)
            self._legend.set_visible(True)

    def set_palette(self, pal) -> None:
        """Swap the palette on theme change."""
        self._pal = pal
        self._gauge._pal = pal
        self._bar._pal = pal
        self._gauge.queue_draw()
        self._bar.queue_draw()

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


class GpuMemoryCard(Gtk.Box):
    """GPU MEMORY card: gauge, pair, bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._gauge = Gauge("gpu_memory", pal)
        self._bar = StackedBar(pal)
        self._title_lbl = _title("GPU MEMORY")
        self._big_lbl = _big("")
        self._pct_lbl = _muted("")
        self._legend = _muted("")
        vbox = _vbox(spacing=4)
        top = _hbox(spacing=10)
        top.pack_start(self._gauge, expand=False, fill=False, padding=0)
        info = _vbox(spacing=2)
        info.pack_start(self._title_lbl, expand=False, fill=False, padding=0)
        info.pack_start(self._big_lbl, expand=False, fill=False, padding=0)
        info.pack_start(self._pct_lbl, expand=False, fill=False, padding=0)
        top.pack_start(info, expand=True, fill=True, padding=0)
        vbox.pack_start(top, expand=False, fill=False, padding=0)
        vbox.pack_start(self._bar, expand=False, fill=True, padding=0)
        vbox.pack_start(self._legend, expand=False, fill=False, padding=0)
        self.pack_start(vbox, True, True, 0)
        self.connect("size-allocate", self._on_size_allocate)

    def _on_size_allocate(self, _widget, _allocation) -> None:
        """Hide detail lines below 260px, bar/legend below 150px."""
        w = self.get_allocated_width()
        if w < 150:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(False)
            self._pct_lbl.set_visible(False)
            self._bar.set_visible(False)
            self._legend.set_visible(False)
        elif w < 260:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(False)
            self._pct_lbl.set_visible(False)
            self._bar.set_visible(False)
            self._legend.set_visible(False)
        else:
            self._title_lbl.set_visible(True)
            self._big_lbl.set_visible(True)
            self._pct_lbl.set_visible(True)
            self._bar.set_visible(True)
            self._legend.set_visible(True)

    def set_palette(self, pal) -> None:
        """Swap the palette on theme change."""
        self._pal = pal
        self._gauge._pal = pal
        self._bar._pal = pal
        self._gauge.queue_draw()
        self._bar.queue_draw()

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
