# SPDX-License-Identifier: GPL-3.0-or-later
"""The four gauge cards: CPU, GPU, MEMORY, GPU MEMORY."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from spaced_monitor import format as fmt
from spaced_monitor.theme import palette, gradient
from spaced_monitor.widgets import Gauge, StackedBar


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
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Create a muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Create a big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Create a card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    return lbl


class _CardBase(Gtk.Frame):
    """Shared card frame with a gauge and info column."""

    def __init__(self, kind: str, title_text: str, pal) -> None:
        super().__init__()
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
        self.add(row)

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


class MemoryCard(Gtk.Frame):
    """MEMORY card: gauge, pair, stacked bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__()
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
        self.add(vbox)

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


class GpuMemoryCard(Gtk.Frame):
    """GPU MEMORY card: gauge, pair, bar, legend."""

    def __init__(self, pal) -> None:
        super().__init__()
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
        self.add(vbox)

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
