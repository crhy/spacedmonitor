# SPDX-License-Identifier: GPL-3.0-or-later
"""Processes and Hardware pages: pure helpers first, then the GTK pages."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from spaced_monitor import format as fmt
from spaced_monitor import theme as theme_mod
from spaced_monitor.apptable import (end_outcome, end_question, meter_fraction)
from spaced_monitor.collect import Filesystem, GpuExtra, Interface, Temperature
from spaced_monitor.processes import AppUsage, ProcUsage, end_app, filter_apps
from spaced_monitor.widgets import Gauge, Meter, StackedBar

# Columns the Processes page can sort by, in header order.
SORT_COLUMNS = ("app", "cpu", "ram", "gpu", "disk")

_SORT_KEYS = {
    "app": lambda a: a.name.lower(),
    "cpu": lambda a: a.cpu_percent,
    "ram": lambda a: a.rss,
    "gpu": lambda a: a.gpu_percent,
    "disk": lambda a: a.disk_bps,
}


def sort_apps(apps: list, column: str = "cpu", reverse: bool = True) -> list:
    """Sort apps by the chosen column; the app column is always alphabetical."""
    key = _SORT_KEYS.get(column, _SORT_KEYS["cpu"])
    if column == "app":
        return sorted(apps, key=key)
    return sorted(apps, key=key, reverse=reverse)


def sort_indicator(column: str, active: str, reverse: bool) -> str:
    """The sorted column's header carries the arrow: ▲ descending, ▼ ascending."""
    if column != active:
        return ""
    return "\u25b2" if reverse else "\u25bc"


def count_summary(apps: list) -> str:
    """The left header cell: '128 apps · 412 processes'."""
    processes = sum(len(a.pids) for a in apps)
    return f"{len(apps)} apps \u00b7 {processes} processes"


def child_rows(app: AppUsage) -> list:
    """Rows shown under an expanded app: pid, name, cpu, ram."""
    return [(str(c.pid), c.name, fmt.percent(c.cpu_percent), fmt.bytes_gb(c.rss))
            for c in app.children]


def temp_colour_class(c: float | None) -> str:
    """Colour a temperature: green below 60, orange below 80, red at or above."""
    if c is None:
        return "value"
    if c < 60.0:
        return "temp-cool"
    if c < 80.0:
        return "temp-warm"
    return "temp-hot"


def sensor_rows(temperatures: list) -> list:
    """One row per reading: chip, label, value text, colour class."""
    return [(t.chip, t.label, fmt.temp(t.celsius), temp_colour_class(t.celsius))
            for t in temperatures]


def _fraction(percent: float) -> float:
    """Clamp a percent into a 0..1 bar fraction."""
    return min(1.0, max(0.0, (percent or 0.0) / 100.0))


def core_meters(per_core: list, columns: int = 8) -> list:
    """One meter per core, laid out into rows of `columns` cells."""
    cells = [(f"C{i}", _fraction(v)) for i, v in enumerate(per_core)]
    columns = max(1, columns)
    return [cells[i:i + columns] for i in range(0, len(cells), columns)]


def fan_rows(fans: list) -> list:
    """One row per fan: label and rpm text."""
    return [(f.label, fmt.rpm(f.rpm)) for f in fans]


def core_summary(per_core: list) -> str:
    """'16 cores' from the per-core sample list."""
    if not per_core:
        return ""
    return f"{len(per_core)} cores"


def freq_line(current: float | None, lo: float | None, hi: float | None) -> str:
    """'freq 4.6 / 4.2 / 4.8 GHz': current, slowest and fastest seen."""
    if current is None and lo is None and hi is None:
        return ""
    return (f"freq {fmt.ghz(current)} / {fmt.ghz(lo)} / {fmt.ghz(hi)}")


def filesystem_rows(filesystems: list) -> list:
    """One row per filesystem: mount, type, 'used / total' and the bar fraction."""
    rows = []
    for f in filesystems:
        fraction = 0.0
        if f.used is not None and f.total:
            fraction = min(1.0, f.used / f.total)
        rows.append((f.mount, f.fstype, fmt.pair_gb(f.used, f.total), fraction))
    return rows


def interface_rows(interfaces: list) -> list:
    """One row per interface: name, address, rx rate, tx rate."""
    return [(i.name, i.address or fmt.EMDASH, fmt.rate(i.rx_bps), fmt.rate(i.tx_bps))
            for i in interfaces]


def gpu_extra_line(extra: GpuExtra | None) -> str:
    """'driver 5611.5 · PCIe gen 4 · width 16' from the once-read nvidia values."""
    if extra is None:
        return ""
    parts = []
    if extra.driver:
        parts.append(f"driver {extra.driver}")
    if extra.link_gen:
        link = f"PCIe gen {extra.link_gen}"
        if extra.link_width:
            link += f" \u00b7 width {extra.link_width}"
        parts.append(link)
    return " \u00b7 ".join(parts)


# --- Processes page ---------------------------------------------------------

_COLUMN_MAX = {"cpu": 100.0, "ram": 16.0 * 1024 ** 3, "gpu": 100.0, "disk": 100e6}
_COLUMN_TITLES = {"app": "App", "cpu": "CPU", "ram": "RAM", "gpu": "GPU",
                  "disk": "Disk"}
_END_ID = 1
_FORCE_ID = 2


def system_only(apps: list) -> list:
    """The 'System' scope: apps owned by root, i.e. the services."""
    return [a for a in apps if a.user == "root"]


def visible_apps(apps: list, text: str, scope: str, me: str | None,
                 column: str, reverse: bool) -> list:
    """Filter by search and scope, then sort by the chosen column."""
    kept = filter_apps(apps, text=text,
                       scope=("mine" if scope == "mine" else "all"), me=me)
    if scope == "system":
        kept = system_only(kept)
    return sort_apps(kept, column=column, reverse=reverse)


def _value_text(column: str, value: float) -> str:
    """Format one sortable cell for display."""
    if column == "cpu" or column == "gpu":
        return fmt.percent(value)
    if column == "ram":
        return fmt.bytes_gb(int(value))
    if column == "disk":
        return fmt.rate(value)
    return ""


def _muted(text: str) -> Gtk.Label:
    """Muted label, left aligned."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    return lbl


def _title_label(text: str) -> Gtk.Label:
    """Card-title label, left aligned."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    return lbl


def _value(text: str) -> Gtk.Label:
    """Value label, left aligned."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("value")
    lbl.set_xalign(0.0)
    return lbl


def _big_value(text: str) -> Gtk.Label:
    """Big-value label, left aligned."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    return lbl


def _flat_button(label: str, css: str = "") -> Gtk.Button:
    """Borderless button used as an in-row control."""
    btn = Gtk.Button(label=label)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    if css:
        btn.get_style_context().add_class(css)
    return btn


class ProcessesPage(Gtk.Box):
    """The Processes page: searchable, sortable, scrollable, expandable list.

    Each row carries an End button; clicking a column header sorts by it and
    clicking a row's twist toggle reveals that app's individual processes.
    """

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._pal = pal
        self._all: list = []
        self._shown: list = []
        self._expanded: set = set()
        self._text = ""
        self._scope = "all"
        self._col = "cpu"
        self._desc = True
        self._build()

    def set_palette(self, pal) -> None:
        """Swap palette colours and redraw every row."""
        self._pal = pal
        self._rebuild()

    def set_apps(self, apps: list) -> None:
        """Replace the app list and repaint the visible rows."""
        self._all = list(apps)
        self._refresh()

    def _build(self) -> None:
        """Head row (count, search, scope), column headers, then scroll area."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._count = _muted(count_summary([]))
        head.pack_start(self._count, False, False, 0)
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search processes\u2026")
        self._search.set_hexpand(True)
        self._search.connect("changed", self._on_search)
        head.pack_start(self._search, True, True, 0)
        self._scope_combo = Gtk.ComboBoxText()
        for item in ("All", "System", "Mine"):
            self._scope_combo.append_text(item)
        self._scope_combo.set_active(0)
        self._scope_combo.connect("changed", self._on_scope)
        head.pack_start(self._scope_combo, False, False, 0)
        vbox.pack_start(head, False, False, 0)
        self._header_btns: dict = {}
        headers = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for col in SORT_COLUMNS:
            btn = _flat_button(_COLUMN_TITLES[col], css="col-header")
            btn.connect("clicked", self._on_sort, col)
            self._header_btns[col] = btn
            headers.pack_start(btn, True, True, 0)
        self._repaint_headers()
        vbox.pack_start(headers, False, False, 0)
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.AUTOMATIC,
                                  Gtk.PolicyType.AUTOMATIC)
        self._grid = Gtk.Grid()
        self._grid.set_row_spacing(2)
        self._grid.set_column_spacing(8)
        self._scrolled.add(self._grid)
        vbox.pack_start(self._scrolled, True, True, 0)
        self.pack_start(vbox, True, True, 0)

    def _repaint_headers(self) -> None:
        """Mark the active sort column with its direction arrow."""
        for col, btn in self._header_btns.items():
            arrow = sort_indicator(col, self._col, self._desc)
            btn.set_label(f"{_COLUMN_TITLES[col]} {arrow}".strip())

    def _refresh(self) -> None:
        """Recompute the visible rows, update the count, rebuild the grid."""
        self._shown = visible_apps(self._all, self._text, self._scope,
                                   None, self._col, self._desc)
        self._count.set_label(count_summary(self._shown))
        self._rebuild()

    def _rebuild(self) -> None:
        """Recreate every row from the current filter, sort and expansion."""
        for child in self._grid.get_children():
            self._grid.remove(child)
        row = 0
        for app in self._shown:
            self._add_row(app, row)
            row += 1
            if (app.name, app.user) in self._expanded:
                for cells in child_rows(app):
                    self._add_child_row(cells, row)
                    row += 1

    def _add_row(self, app: AppUsage, row: int) -> None:
        """Attach one app row: end, twist toggle, icon, name, value pairs."""
        end = _flat_button("\u2715", css="end-button")
        end.connect("clicked", self._on_end, app)
        self._grid.attach(end, 0, row, 1, 1)
        key = (app.name, app.user)
        toggle = _flat_button("\u25b1" if key in self._expanded else "\u25b0")
        toggle.connect("clicked", self._on_expand, app)
        self._grid.attach(toggle, 1, row, 1, 1)
        icon = Gtk.Label(label=app.icon or "\u25a4")
        icon.set_name("icon")
        self._grid.attach(icon, 2, row, 1, 1)
        name = Gtk.Label(label=app.name)
        name.set_hexpand(True)
        name.set_xalign(0.0)
        self._grid.attach(name, 3, row, 1, 1)
        for i, col in enumerate(("cpu", "ram", "gpu", "disk")):
            value = _SORT_KEYS[col](app)
            self._grid.attach(_value(_value_text(col, value)),
                              4 + 2 * i, row, 1, 1)
            meter = Meter(self._pal)
            meter.set_value(meter_fraction(value, _COLUMN_MAX[col]))
            self._grid.attach(meter, 5 + 2 * i, row, 1, 1)

    def _add_child_row(self, cells: tuple, row: int) -> None:
        """Attach one process under an expanded app: pid, name, cpu, ram."""
        pid, pname, cpu, ram = cells
        self._grid.attach(_muted("\u2514"), 1, row, 1, 1)
        self._grid.attach(_muted(pid), 2, row, 1, 1)
        self._grid.attach(_muted(pname), 3, row, 1, 1)
        self._grid.attach(_value(cpu), 4, row, 1, 1)
        self._grid.attach(_value(ram), 6, row, 1, 1)

    def _on_search(self, entry) -> None:
        """Remember the search text and re-filter."""
        self._text = entry.get_text()
        self._refresh()

    def _on_scope(self, combo) -> None:
        """Remember the scope selection and re-filter."""
        self._scope = (combo.get_active_text() or "All").lower()
        self._refresh()

    def _on_sort(self, _btn, col: str) -> None:
        """Sort by the clicked column; clicking it again reverses the order."""
        if col == self._col:
            self._desc = not self._desc
        else:
            self._col = col
            self._desc = True
        self._repaint_headers()
        self._refresh()

    def _on_expand(self, _btn, app: AppUsage) -> None:
        """Toggle whether this app row shows its individual processes."""
        self.toggle_expand(app)

    def toggle_expand(self, app: AppUsage) -> None:
        """Show or hide one app's individual processes."""
        key = (app.name, app.user)
        if key in self._expanded:
            self._expanded.discard(key)
        else:
            self._expanded.add(key)
        self._refresh()

    def _on_end(self, _btn, app: AppUsage) -> None:
        """Open the end confirmation dialog for this row's app."""
        self._confirm_end(app)

    def _confirm_end(self, app: AppUsage) -> None:
        """Show a modal confirmation and end the app on the End button."""
        question, detail = end_question(app)
        dialog = Gtk.MessageDialog(
            parent=self.get_root(), modal=True,
            message_class=Gtk.MessageQuestion, buttons=Gtk.ButtonsType.NONE,
            text=f"{question}\n{detail}")
        dialog.add_button("Cancel", Gtk.ButtonsType.CANCEL)
        dialog.add_button("End", _END_ID)
        dialog.set_default_response(Gtk.ButtonsType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == _END_ID:
            self._run_end(app, force=False)

    def _run_end(self, app: AppUsage, force: bool) -> None:
        """End the app; on refusal offer a force end (never after a force)."""
        ok, msg = end_app(app, force=force)
        if ok:
            return
        _msg, offer_force = end_outcome(ok, msg, force)
        if offer_force:
            self._offer_force(app, msg)

    def _offer_force(self, app: AppUsage, msg: str) -> None:
        """Show the refusal and offer a force end as a secondary action."""
        dialog = Gtk.MessageDialog(
            parent=self.get_root(), modal=True,
            message_class=Gtk.MessageWarning, buttons=Gtk.ButtonsType.NONE,
            text=msg)
        dialog.add_button("Cancel", Gtk.ButtonsType.CANCEL)
        dialog.add_button("Force end", _FORCE_ID)
        dialog.set_default_response(Gtk.ButtonsType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == _FORCE_ID:
            end_app(app, force=True)


# --- Hardware page ----------------------------------------------------------


class _HCard(Gtk.Box):
    """A Hardware page card: title, optional model line, then its own body."""

    def __init__(self, title: str, model: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._body.pack_start(_title_label(title), False, False, 0)
        self._model = _muted(model)
        self._body.pack_start(self._model, False, False, 0)
        self.pack_start(self._body, True, True, 0)

    def set_model(self, model: str) -> None:
        """Set the small model line under the card title."""
        self._model.set_label(model)

    def add_widget(self, widget, expand: bool = False) -> None:
        """Append a drawing widget to the card body."""
        self._body.pack_start(widget, expand, True, 0)


class _CpuCard(_HCard):
    """CPU: load gauge, model, frequency, temperature, one meter per core."""

    def __init__(self, pal) -> None:
        super().__init__("CPU")
        self._pal = pal
        self._gauge = Gauge("cpu", pal)
        self._gauge.set_size_request(120, 100)
        self._load = _value(fmt.EMDASH)
        self._cores_lbl = _muted("")
        self._freq = _muted("")
        self._temp = _muted("")
        self._freq_lo: float | None = None
        self._freq_hi: float | None = None
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top.pack_start(self._gauge, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.pack_start(self._load, False, False, 0)
        info.pack_start(self._cores_lbl, False, False, 0)
        info.pack_start(self._freq, False, False, 0)
        info.pack_start(self._temp, False, False, 0)
        top.pack_start(info, True, True, 0)
        self.add_widget(top)
        self._cores = Gtk.Grid()
        self._cores.set_row_spacing(3)
        self._cores.set_column_spacing(3)
        self.add_widget(self._cores, expand=True)

    def update(self, snap) -> None:
        """Refresh load, cores, frequency range, temperature and core meters."""
        self.set_model(snap.cpu.model or "")
        self._gauge.set_percent(snap.cpu.percent)
        self._load.set_label(fmt.percent(snap.cpu.percent))
        self._cores_lbl.set_label(core_summary(snap.cpu.per_core))
        freq = snap.cpu.freq_mhz
        if freq is not None:
            if self._freq_lo is None or freq < self._freq_lo:
                self._freq_lo = freq
            if self._freq_hi is None or freq > self._freq_hi:
                self._freq_hi = freq
        self._freq.set_label(freq_line(freq, self._freq_lo, self._freq_hi))
        self._temp.set_label(f"temp {fmt.temp(snap.cpu.temp_c)}")
        self._draw_cores(snap.cpu.per_core)

    def _draw_cores(self, per_core: list) -> None:
        """Rebuild the core meter grid: one cell per core, eight per row."""
        for child in self._cores.get_children():
            self._cores.remove(child)
        for row, cells in enumerate(core_meters(per_core)):
            for col, (name, fraction) in enumerate(cells):
                meter = Meter(self._pal)
                meter.set_value(fraction)
                meter.set_tooltip_text(f"{name} {fmt.percent(per_core[col])}")
                self._cores.attach(meter, col, row, 1, 1)


class _SensorCard(_HCard):
    """Sensors: every temperature reading, coloured, then every fan."""

    def __init__(self, pal) -> None:
        super().__init__("Sensors")
        self._pal = pal
        self._rows: list = []

    def update(self, snap) -> None:
        """Refresh every temperature reading and fan, recolouring each value."""
        rows = [(f"{chip} {label}".strip(), text, css)
                for chip, label, text, css in sensor_rows(snap.temperatures)]
        rows += [(label, text, "value") for label, text in fan_rows(snap.fans)]
        while len(self._rows) < len(rows):
            self._rows.append(self._new_row())
        for index, (name, text, css) in enumerate(rows):
            name_lbl, value = self._rows[index]
            name_lbl.set_label(name)
            value.set_label(text)
            value.get_style_context().remove_class("temp-cool")
            value.get_style_context().remove_class("temp-warm")
            value.get_style_context().remove_class("temp-hot")
            value.get_style_context().add_class(css)
        for extra in self._rows[len(rows):]:
            extra[0].get_parent().hide()
        self._rows = self._rows[:len(rows)]

    def _new_row(self) -> tuple:
        """One sensor row: name on the left, coloured value on the right."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = _muted("")
        value = _value("")
        box.pack_start(name, True, True, 0)
        box.pack_start(value, False, False, 0)
        self.add_widget(box)
        return (name, value)


class _GpuCard(_HCard):
    """GPU: load gauge, model, temperature, power, video memory, link info."""

    def __init__(self, pal) -> None:
        super().__init__("GPU")
        self._pal = pal
        self._gauge = Gauge("gpu", pal)
        self._gauge.set_size_request(120, 100)
        self._load = _value(fmt.EMDASH)
        self._lines = [_muted("") for _ in range(3)]
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top.pack_start(self._gauge, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.pack_start(self._load, False, False, 0)
        for line in self._lines:
            info.pack_start(line, False, False, 0)
        top.pack_start(info, True, True, 0)
        self.add_widget(top)

    def update(self, snap) -> None:
        """Refresh GPU load, temperature, power, memory and the link line."""
        gpu = snap.gpu
        self.set_model(gpu.name or "")
        self._gauge.set_percent(gpu.percent)
        self._load.set_label(fmt.percent(gpu.percent))
        self._lines[0].set_label(
            f"temp {fmt.temp(gpu.temp_c)}  power {fmt.watts(gpu.power_w)}")
        self._lines[1].set_label(
            f"vram {fmt.pair_gb(gpu.mem_used, gpu.mem_total)}")
        self._lines[2].set_label(gpu_extra_line(snap.gpu_extra))


class _MemoryCard(_HCard):
    """Memory: used / total, stacked bar, apps, cache, swap."""

    def __init__(self, pal) -> None:
        super().__init__("Memory")
        self._pal = pal
        self._big = _big_value(fmt.EMDASH)
        self._bar = StackedBar(pal)
        self._lines = [_muted("") for _ in range(2)]
        self.add_widget(self._big)
        self.add_widget(self._bar, expand=True)
        for line in self._lines:
            self.add_widget(line)

    def update(self, snap) -> None:
        """Refresh the used / total pair, the bar and the legend lines."""
        mem = snap.memory
        used = (mem.total - mem.available) if mem.total else 0
        self._big.set_label(fmt.pair_gb(used, mem.total))
        total = mem.total or 1
        self._bar.set_segments([
            (mem.apps / total, self._pal.cpu_start),
            (mem.cache / total, self._pal.gpu_memory_start),
            (max(0, mem.available) / total, self._pal.cpu_end),
        ])
        self._lines[0].set_label(
            f"apps {fmt.bytes_gb(mem.apps)}  cache {fmt.bytes_gb(mem.cache)}")
        self._lines[1].set_label(
            f"swap {fmt.pair_gb(mem.swap_used, mem.swap_total)}")


class _StorageCard(_HCard):
    """Storage: read and write rates, then one row per real filesystem."""

    def __init__(self, pal) -> None:
        super().__init__("Storage")
        self._pal = pal
        self._read = _value(fmt.EMDASH)
        self._write = _value(fmt.EMDASH)
        rates = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        rates.pack_start(self._read, True, True, 0)
        rates.pack_start(self._write, True, True, 0)
        self.add_widget(rates)
        self._rows: list = []

    def update(self, snap) -> None:
        """Refresh the io rates and every filesystem row."""
        self._read.set_label(f"read {fmt.rate(snap.disk.read_bps)}")
        self._write.set_label(f"write {fmt.rate(snap.disk.write_bps)}")
        self.set_model(fmt.pair_gb(snap.disk.used, snap.disk.total))
        rows = filesystem_rows(snap.filesystems)
        while len(self._rows) < len(rows):
            self._rows.append(self._new_row())
        for index, (mount, fstype, pair, fraction) in enumerate(rows):
            name, bar, value = self._rows[index]
            name.set_label(mount)
            name.set_tooltip_text(f"{mount} ({fstype})")
            bar.set_value(fraction)
            value.set_label(pair)
        for extra in self._rows[len(rows):]:
            extra[0].get_parent().hide()
        self._rows = self._rows[:len(rows)]

    def _new_row(self) -> tuple:
        """One filesystem row: mount, used bar, used / total text."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = _muted("")
        bar = Meter(self._pal)
        value = _value("")
        box.pack_start(name, True, True, 0)
        box.pack_start(bar, True, True, 0)
        box.pack_start(value, False, False, 0)
        self.add_widget(box)
        return (name, bar, value)


class _NetworkCard(_HCard):
    """Network: total download / upload, then one row per interface."""

    def __init__(self, pal) -> None:
        super().__init__("Network")
        self._pal = pal
        self._rates = [_muted(""), _muted("")]
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        for cell in self._rates:
            row.pack_start(cell, True, True, 0)
        self.add_widget(row)
        self._rows: list = []

    def update(self, snap) -> None:
        """Refresh the total rates and every interface row."""
        self._rates[0].set_label(f"down {fmt.rate(snap.net.rx_bps)}")
        self._rates[1].set_label(f"up {fmt.rate(snap.net.tx_bps)}")
        rows = interface_rows(snap.interfaces)
        while len(self._rows) < len(rows):
            self._rows.append(self._new_row())
        for index, (name, address, rx, tx) in enumerate(rows):
            iface, addr, rates = self._rows[index]
            iface.set_label(name)
            addr.set_label(address)
            rates.set_label(f"{rx} / {tx}")
        for extra in self._rows[len(rows):]:
            extra[0].get_parent().hide()
        self._rows = self._rows[:len(rows)]

    def _new_row(self) -> tuple:
        """One interface row: name, address, download / upload rates."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        iface = _value("")
        addr = _muted("")
        rates = _muted("")
        box.pack_start(iface, False, False, 0)
        box.pack_start(addr, False, False, 0)
        box.pack_start(rates, False, False, 0)
        self.add_widget(box)
        return (iface, addr, rates)


class HardwarePage(Gtk.Box):
    """The Hardware page: responsive cards for CPU, sensors, GPU, memory,
    storage and network."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("page")
        self._pal = pal
        self._build()

    def set_palette(self, pal) -> None:
        """Rebuild every card with the new palette colours."""
        self._pal = pal
        self._build_cards()

    def update(self, snap) -> None:
        """Push the latest snapshot into every card."""
        for card in self._cards:
            card.update(snap)

    def _build(self) -> None:
        """Wrap the FlowBox of cards in the page frame."""
        self._flow = Gtk.FlowBox()
        self._flow.set_orientation(Gtk.Orientation.VERTICAL)
        self._flow.set_selection_mode(False)
        self._flow.set_max_children_per_line(3)
        self.pack_start(self._flow, True, True, 0)
        self._build_cards()

    def _build_cards(self) -> None:
        """Recreate the six cards and append them to the FlowBox."""
        for child in self._flow.get_children():
            self._flow.remove(child)
        self._cards = [
            _CpuCard(self._pal), _SensorCard(self._pal), _GpuCard(self._pal),
            _MemoryCard(self._pal), _StorageCard(self._pal),
            _NetworkCard(self._pal),
        ]
        for card in self._cards:
            card.set_margin_end(12)
            card.set_margin_bottom(12)
            self._flow.add(card)
