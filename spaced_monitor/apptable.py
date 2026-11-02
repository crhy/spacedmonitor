# SPDX-License-Identifier: GPL-3.0-or-later
"""The 'what is using your computer' app table and its end button."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from spaced_monitor import format as fmt
from spaced_monitor.pages import sort_apps, sort_indicator, meter_fraction
from spaced_monitor.processes import (AppUsage, display_name, filter_apps,
                                      end_immediate)
from spaced_monitor.widgets import ELLIPSIZE_END, Meter

_COLUMNS = ("cpu", "ram", "gpu", "disk")
_COLUMN_TITLES = {"cpu": "CPU", "ram": "RAM", "gpu": "GPU", "disk": "Disk"}


def _hbox(spacing: int = 6) -> Gtk.Box:
    """Create a horizontal box."""
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def _vbox(spacing: int = 4) -> Gtk.Box:
    """Create a vertical box."""
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def _title(text: str) -> Gtk.Label:
    """Create a card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    return lbl


def _value(text: str) -> Gtk.Label:
    """Create a value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("value")
    return lbl


class AppTable(Gtk.Box):
    """A card with a search/scope header and a scrollable, sortable table."""

    def __init__(self, pal) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("card")
        self.get_style_context().add_class("app-table")
        self._pal = pal
        self._all_apps: list[AppUsage] = []
        self._apps: list[AppUsage] = []
        self._search_text = ""
        self._scope = "all"
        self._col = "cpu"
        self._desc = True
        self._header_btns: dict[str, Gtk.Button] = {}
        self._meters: list[list[Meter]] = []
        self._msg_bar: Gtk.Label | None = None
        self._msg_timeout_id: int = 0
        self._build_header()
        self._build_scroll_area()
        self.connect("size-allocate", self._on_size_allocate)

    def _build_header(self) -> None:
        """Title, search entry and scope combo across the top of the card."""
        head = _hbox(spacing=10)
        head.pack_start(_title("What is using your computer?"),
                        expand=False, fill=False, padding=0)
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search processes\u2026")
        self._search.connect("changed", self._on_search)
        head.pack_start(self._search, expand=True, fill=True, padding=0)
        self._scope_combo = Gtk.ComboBoxText()
        self._scope_combo.append_text("All processes")
        self._scope_combo.append_text("My processes")
        self._scope_combo.set_active(0)
        self._scope_combo.connect("changed", self._on_scope)
        head.pack_start(self._scope_combo, expand=False, fill=False, padding=0)
        self._head = head

    def _build_scroll_area(self) -> None:
        """Build the column-header buttons and a scrollable grid for rows."""
        self._vbox = _vbox(spacing=6)
        self._vbox.pack_start(self._head, expand=False, fill=False, padding=0)
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER,
                                  Gtk.PolicyType.AUTOMATIC)
        self._grid = Gtk.Grid()
        self._grid.set_row_spacing(4)
        self._grid.set_column_spacing(6)
        self._build_col_headers()
        self._scrolled.add(self._grid)
        self._vbox.pack_start(self._scrolled, expand=True, fill=True, padding=0)
        self.pack_start(self._vbox, True, True, 0)

    def _build_col_headers(self) -> None:
        """Attach clickable column-header buttons into the grid row 0."""
        for c, col in enumerate(_COLUMNS):
            btn = Gtk.Button(label=_COLUMN_TITLES[col])
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("col-header")
            btn.connect("clicked", self._on_sort, col)
            self._header_btns[col] = btn
            self._grid.attach(btn, 3 + c * 2, 0, 2, 1)
        self._repaint_headers()

    def _repaint_headers(self) -> None:
        """Mark the active sort column with its direction arrow."""
        for col, btn in self._header_btns.items():
            arrow = sort_indicator(col, self._col, self._desc)
            btn.set_label(f"{_COLUMN_TITLES[col]} {arrow}".strip())

    def set_apps(self, apps: list[AppUsage]) -> None:
        """Store the full list, filter and sort it, rebuild the grid."""
        self._all_apps = list(apps)
        self._apps = self._visible()
        self._rebuild()

    def _visible(self) -> list[AppUsage]:
        """Filter by search/scope then sort by the chosen column."""
        kept = filter_apps(self._all_apps, self._search_text, self._scope)
        return sort_apps(kept, column=self._col, reverse=self._desc)

    def _rebuild(self) -> None:
        """Recreate the data rows, keeping the column-header buttons pinned.

        The header buttons are built once and never removed, so they stay
        allocated (visible) across every refresh instead of briefly becoming
        unallocated while the grid is rebuilt.
        """
        header_btns = set(self._header_btns.values())
        for child in self._grid.get_children():
            if child not in header_btns:
                self._grid.remove(child)
        self._meters = []
        self._repaint_headers()
        for r, app in enumerate(self._apps, start=1):
            self._add_row(app, r)
        self._update_meters()
        self._grid.show_all()
        self._apply_meter_visibility()

    def _add_row(self, app: AppUsage, row: int) -> None:
        """Attach one app row: end button, icon, name, value+meter pairs."""
        btn = Gtk.Button(label="\u2715")
        btn.get_style_context().add_class("end-button")
        btn.set_tooltip_text("End this app")
        btn.connect("clicked", self._on_end, app)
        self._grid.attach(btn, 0, row, 1, 1)
        icon_name = app.icon or "application-x-executable"
        theme = Gtk.IconTheme.get_default()
        if icon_name != "application-x-executable" and not theme.has_icon(icon_name):
            icon_name = "application-x-executable"
        icon = Gtk.Image.new_from_icon_name(
            icon_name, Gtk.IconSize.MENU)
        self._grid.attach(icon, 1, row, 1, 1)
        name = _value(display_name(app.name, exe=app.exe, cmdline=app.cmdline))
        name.set_hexpand(True)
        name.set_xalign(0.0)
        name.set_ellipsize(ELLIPSIZE_END)
        self._grid.attach(name, 2, row, 1, 1)
        colours = (self._pal.cpu_start, self._pal.ram_start,
                   self._pal.gpu_memory_start, self._pal.disk_read)
        texts = (fmt.percent(app.cpu_percent), fmt.bytes_gb(app.rss),
                 fmt.percent(app.gpu_percent), fmt.rate(app.disk_bps))
        row_meters: list[Meter] = []
        for c, (colour, text) in enumerate(zip(colours, texts)):
            col = 3 + c * 2
            lbl = _value(text)
            lbl.set_xalign(1.0)
            self._grid.attach(lbl, col, row, 1, 1)
            meter = Meter(self._pal)
            meter.set_size_request(56, 12)
            meter.set_value(0.0, colour)
            self._grid.attach(meter, col + 1, row, 1, 1)
            row_meters.append(meter)
        self._meters.append(row_meters)

    def _update_meters(self) -> None:
        """Scale each column's meters to that column's maximum."""
        maxima = (100.0,
                  max((a.rss for a in self._apps), default=0),
                  100.0,
                  max((a.disk_bps for a in self._apps), default=0.0))
        for r, row_m in enumerate(self._meters):
            app = self._apps[r] if r < len(self._apps) else None
            values = ((app.cpu_percent, app.rss, app.gpu_percent,
                       app.disk_bps) if app else (0.0, 0, 0.0, 0.0))
            for c, maximum in enumerate(maxima):
                row_m[c].set_value(meter_fraction(values[c], maximum))

    def _on_size_allocate(self, _widget, _allocation) -> None:
        """Hide meters below 900px width to keep all columns visible."""
        self._apply_meter_visibility()

    def _apply_meter_visibility(self) -> None:
        """Show or hide meters based on current allocated width."""
        w = self.get_allocated_width()
        show_meters = w >= 900
        for row_m in self._meters:
            for meter in row_m:
                meter.set_visible(show_meters)

    def _on_search(self, entry) -> None:
        """Remember the search text and re-filter."""
        self._search_text = entry.get_text()
        self._apps = self._visible()
        self._rebuild()

    def _on_scope(self, combo) -> None:
        """Remember the scope selection and re-filter."""
        text = combo.get_active_text() or "All processes"
        self._scope = "mine" if text.lower().startswith("my") else "all"
        self._apps = self._visible()
        self._rebuild()

    def _on_sort(self, _btn, col: str) -> None:
        """Sort by the clicked column; clicking it again reverses the order."""
        if col == self._col:
            self._desc = not self._desc
        else:
            self._col = col
            self._desc = True
        self._repaint_headers()
        self._apps = self._visible()
        self._rebuild()

    def _on_end(self, _btn, app: AppUsage) -> None:
        """End the app immediately: SIGTERM then SIGKILL after 2 s."""
        ok, msg = end_immediate(app, timeout_add=GLib.timeout_add)
        if not ok:
            self._show_msg(msg)

    def _show_msg(self, text: str) -> None:
        """Show a refusal message inline for 4 seconds."""
        if self._msg_bar is None:
            bar = Gtk.Label(label=text)
            bar.get_style_context().add_class("muted")
            bar.set_xalign(0.0)
            self._msg_bar = bar
            self._vbox.pack_start(bar, False, False, 0)
        else:
            self._msg_bar.set_text(text)
        if self._msg_timeout_id:
            GLib.timeout_cancel(self._msg_timeout_id)
        self._msg_timeout_id = GLib.timeout_add(
            4000, self._clear_msg)

    def _clear_msg(self) -> bool:
        """Clear the inline message; returns False so it does not repeat."""
        if self._msg_bar:
            self._msg_bar.set_text("")
        self._msg_timeout_id = 0
        return False
