# SPDX-License-Identifier: GPL-3.0-or-later
"""The 'what is using your computer' app table and its end button."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from spaced_monitor import format as fmt
from spaced_monitor.processes import AppUsage, display_name, filter_apps, end_app
from spaced_monitor.widgets import Meter

_END_ID = 1
_FORCE_ID = 2


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


def meter_fraction(value: float, maximum: float,
                   cap: float | None = None) -> float:
    """Fraction for a mini bar: value/max, clamped to [0, 1] and to cap."""
    if not maximum:
        return 0.0
    frac = value / maximum
    if cap is not None:
        frac = min(frac, cap)
    return max(0.0, min(1.0, frac))


def end_question(app: AppUsage) -> tuple[str, str]:
    """Return (question, detail) shown in the end confirmation dialog."""
    name = display_name(app.name)
    n = len(app.pids)
    detail = "1 process" if n == 1 else f"{n} processes"
    return f"End {name}?", detail


def end_outcome(ok: bool, msg: str, forced: bool) -> tuple[str, bool]:
    """Return (message, offer_force) after an end attempt.

    Force is offered only when a normal (non-forced) end failed.
    """
    if ok:
        return msg, False
    return msg, not forced


class AppTable(Gtk.Frame):
    """A card with a search/scope header and a table of the top apps."""

    def __init__(self, pal, rows: int = 5) -> None:
        super().__init__()
        self.get_style_context().add_class("card")
        self._pal = pal
        self._row_count = max(1, rows)
        self._all_apps: list[AppUsage] = []
        self._apps: list[AppUsage] = []
        self._search_text = ""
        self._scope = "all"
        self._build_header()
        self._build_grid()

    def _build_header(self) -> None:
        """Title, search entry and scope combo across the top of the card."""
        head = _hbox(spacing=10)
        head.pack_start(_title("What is using your computer?"),
                        expand=False, fill=False, padding=0)
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search processes…")
        self._search.connect("changed", self._on_search)
        head.pack_start(self._search, expand=True, fill=True, padding=0)
        self._scope_combo = Gtk.ComboBoxText()
        self._scope_combo.append_text("All processes")
        self._scope_combo.append_text("My processes")
        self._scope_combo.set_active(0)
        self._scope_combo.connect("changed", self._on_scope)
        head.pack_start(self._scope_combo, expand=False, fill=False, padding=0)
        self._head = head

    def _build_grid(self) -> None:
        """Build the column headers and the fixed set of value rows."""
        self._grid = Gtk.Grid()
        self._grid.set_row_spacing(4)
        self._grid.set_column_spacing(6)
        for c, label in enumerate(self._COLUMNS()):
            self._grid.attach(_value(label), 3 + c * 2, 0, 2, 1)
        self._rows: list[dict] = [self._make_row(r)
                                  for r in range(self._row_count)]
        vbox = _vbox(spacing=6)
        vbox.pack_start(self._head, expand=False, fill=False, padding=0)
        vbox.pack_start(self._grid, expand=True, fill=True, padding=0)
        self.add(vbox)

    def _COLUMNS(self) -> tuple[str, ...]:
        """Column titles for the value columns."""
        return ("CPU", "RAM", "GPU", "Disk")

    def _make_row(self, r: int) -> dict:
        """Create one row of cells and attach them to the grid."""
        cells: dict[str, Gtk.Widget] = {"r": r}
        btn = Gtk.Button(label="✕")
        btn.get_style_context().add_class("end-button")
        btn.set_tooltip_text("End this app")
        btn.connect("clicked", self._on_end, r)
        cells["end"] = btn
        self._grid.attach(btn, 0, r + 1, 1, 1)
        icon = Gtk.Image.new_from_icon_name("application-x-executable",
                                            Gtk.IconSize.MENU)
        cells["icon"] = icon
        self._grid.attach(icon, 1, r + 1, 1, 1)
        name = _value("")
        name.set_hexpand(True)
        cells["name"] = name
        self._grid.attach(name, 2, r + 1, 1, 1)
        colours = (self._pal.cpu_start, self._pal.gpu_start,
                   self._pal.gpu_memory_start, self._pal.disk_read)
        for c, colour in enumerate(colours):
            col = 3 + c * 2
            lbl = _value("")
            lbl.set_xalign(1.0)
            cells[f"v{c}"] = lbl
            self._grid.attach(lbl, col, r + 1, 1, 1)
            meter = Meter(self._pal)
            meter.set_size_request(56, 12)
            meter.set_value(0.0, colour)
            cells[f"m{c}"] = meter
            self._grid.attach(meter, col + 1, r + 1, 1, 1)
        return cells

    def set_apps(self, apps: list[AppUsage]) -> None:
        """Store the full list, filter it, and repaint the rows in place."""
        self._all_apps = list(apps)
        self._apps = filter_apps(self._all_apps, self._search_text, self._scope)
        self._repaint()

    def _repaint(self) -> None:
        """Fill every row from the current filtered apps and scale the meters."""
        for cells in self._rows:
            r = cells["r"]
            app = self._apps[r] if r < len(self._apps) else None
            self._paint_row(cells, app)
        self._update_meters()

    def _paint_row(self, cells: dict, app: AppUsage | None) -> None:
        """Fill one row's cells from an app, or blank it when there is none."""
        if app is None:
            cells["name"].set_text("")
            cells["icon"].set_from_icon_name("", Gtk.IconSize.MENU)
            for c in range(4):
                cells[f"v{c}"].set_text("")
            return
        cells["name"].set_text(display_name(app.name))
        cells["icon"].set_from_icon_name(app.icon or "application-x-executable",
                                        Gtk.IconSize.MENU)
        cells["v0"].set_text(fmt.percent(app.cpu_percent))
        cells["v1"].set_text(fmt.bytes_gb(app.rss))
        cells["v2"].set_text(fmt.percent(app.gpu_percent))
        cells["v3"].set_text(fmt.rate(app.disk_bps))

    def _update_meters(self) -> None:
        """Scale each column's meters to that column's maximum."""
        maxima = (100.0,
                  max((a.rss for a in self._apps), default=0),
                  100.0,
                  max((a.disk_bps for a in self._apps), default=0.0))
        for cells in self._rows:
            r = cells["r"]
            app = self._apps[r] if r < len(self._apps) else None
            values = ((app.cpu_percent, app.rss, app.gpu_percent,
                       app.disk_bps) if app else (0.0, 0, 0.0, 0.0))
            for c, maximum in enumerate(maxima):
                cells[f"m{c}"].set_value(meter_fraction(values[c], maximum))

    def _on_search(self, entry) -> None:
        """Remember the search text and re-filter."""
        self._search_text = entry.get_text()
        self._repaint()

    def _on_scope(self, combo) -> None:
        """Remember the scope selection and re-filter."""
        text = combo.get_active_text() or "All processes"
        self._scope = "mine" if text.lower().startswith("my") else "all"
        self._repaint()

    def _on_end(self, _btn, r: int) -> None:
        """Open the end confirmation dialog for the app in row r."""
        if r < len(self._apps):
            self._confirm_end(self._apps[r])

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
        """End the app; on failure offer a force end (never after a force)."""
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
