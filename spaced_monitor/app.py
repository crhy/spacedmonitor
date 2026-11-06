# SPDX-License-Identifier: GPL-3.0-or-later
"""Main application: window, top bar, pages, cards, footer, worker thread."""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from spaced_monitor import theme as theme_mod
from spaced_monitor import format as fmt
from spaced_monitor.cards import (CpuCard, GpuCard, MemoryCard, GpuMemoryCard,
                                  TemperatureCard, DiskCard, NetworkCard)
from spaced_monitor.apptable import AppTable
from spaced_monitor.widgets import ELLIPSIZE_END
from spaced_monitor.pages import HardwarePage, ProcessesPage
from spaced_monitor.collect import Sampler, Snapshot
from spaced_monitor.panes import (load_pane_fractions, save_pane_fractions,
                                   default_fractions)
from spaced_monitor.processes import ProcessSampler


def _hbox(spacing: int = 6) -> Gtk.Box:
    """Horizontal box."""
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def _vbox(spacing: int = 4) -> Gtk.Box:
    """Vertical box."""
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def _flow_row(max_items: int, spacing: int) -> Gtk.FlowBox:
    """Row of cards that reflows into extra rows when squeezed.

    A plain Gtk.Box reports the *sum* of its children's minimum widths, so
    four gauge cards pinned the window at ~990px and the window manager
    simply cut the right-hand card off.  A FlowBox reports the widest child
    instead, so the window can shrink and the cards stack into two rows.
    FlowBox's spacing API changed across GTK versions, hence the probes.
    """
    row = Gtk.FlowBox()
    row.set_min_children_per_line(1)
    row.set_max_children_per_line(max_items)
    row.set_selection_mode(Gtk.SelectionMode.NONE)
    for name in ("set_expand_children",):
        if hasattr(row, name):
            getattr(row, name)(True)
    for name in ("set_child_spacing", "set_column_spacing"):
        if hasattr(row, name):
            getattr(row, name)(spacing)
            break
    for name in ("set_line_spacing", "set_row_spacing"):
        if hasattr(row, name):
            getattr(row, name)(spacing)
            break
    return row


def _lbl(text: str, css: str = "value") -> Gtk.Label:
    """Label with a CSS class."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class(css)
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(ELLIPSIZE_END)
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(ELLIPSIZE_END)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(ELLIPSIZE_END)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(ELLIPSIZE_END)
    return lbl


def _set_pos(paned: Gtk.Paned, pos: int) -> None:
    """Move a Paned divider only when it really moves (each move relayouts)."""
    if paned.get_position() != pos:
        paned.set_position(pos)


class FooterItem(Gtk.Box):
    """One footer cell: an icon beside a muted label above a value."""

    def __init__(self, label_text: str, icon: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.get_style_context().add_class("footer-item")
        if icon:
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
            img.set_valign(Gtk.Align.CENTER)
            self.pack_start(img, False, False, 0)
        col = _vbox(spacing=2)
        self._m = _muted(label_text)
        self._v = _lbl(fmt.EMDASH, "value")
        col.pack_start(self._m, expand=False, fill=False, padding=0)
        col.pack_start(self._v, expand=False, fill=False, padding=0)
        self.pack_start(col, expand=False, fill=False, padding=0)

    def set_value(self, text: str) -> None:
        """Update the value text."""
        self._v.set_text(text)


class MonitorWindow(Gtk.Window):
    """The main Spaced Monitor window."""

    _GAUGE_MIN_H = 100  # minimum height for the gauge card row

    def __init__(self, sampler: Callable[[], Snapshot], refresh_ms: int = 1000,
                 pal=None, proc_sampler: Callable[[], list] | None = None) -> None:
        super().__init__(title="Spaced Monitor")
        self.set_default_size(1400, 900)
        self._pal = pal or theme_mod.palette("dark")
        self._sampler = sampler
        self._refresh_ms = refresh_ms
        self._proc_sampler = proc_sampler or ProcessSampler().sample
        self._last_proc = 0.0
        self._snapshot: Optional[Snapshot] = None
        self._last_sample_time: float = 0.0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pane_fracs = default_fractions()
        self._follow_desktop = True
        self._focused_card = None
        self._focus_hidden: list = []
        self._focus_expand: tuple[bool, bool] | None = None
        self._build_ui()
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self._on_card_click)
        self.connect("destroy", self._on_close)

    def _build_ui(self) -> None:
        """Build the full window layout: bar, one visible page, footer."""
        root = _vbox(spacing=0)
        root.pack_start(self._build_topbar(), expand=False, fill=True, padding=0)
        self._overview = self._build_overview()
        self._processes_page = ProcessesPage(self._pal)
        self._hardware_page = HardwarePage(self._pal)
        self._pages = {"overview": self._overview,
                       "processes": self._processes_page,
                       "hardware": self._hardware_page}
        for page in self._pages.values():
            root.pack_start(page, expand=True, fill=True, padding=0)
        root.pack_start(self._build_footer(), expand=False, fill=True, padding=0)
        self._tab = "overview"
        self._show_tab()
        self._root = root
        self.add(root)

    @staticmethod
    def _nearest_card(widget):
        """Return the closest ancestor carrying the shared card CSS class."""
        while widget is not None:
            if widget.get_style_context().has_class("card"):
                return widget
            widget = widget.get_parent()
        return None

    def _on_card_click(self, _window, event) -> bool:
        """Double-click a card to focus it; the next click restores the page."""
        if event.button != Gdk.BUTTON_PRIMARY:
            return False
        if self._focused_card is not None:
            self._restore_focused_card()
            return False
        if event.type != Gdk.EventType._2BUTTON_PRESS:
            return False
        card = self._nearest_card(Gtk.get_event_widget(event))
        if card is not None:
            self._focus_card(card)
        return False

    def _focus_card(self, card) -> None:
        """Hide siblings along a card's container path so it fills the page."""
        hidden = []
        current = card
        parent = current.get_parent()
        while parent is not None and parent is not self:
            if isinstance(parent, Gtk.Container):
                for child in parent.get_children():
                    if child is not current and child.get_visible():
                        child.hide()
                        hidden.append(child)
            current = parent
            parent = current.get_parent()
        self._focus_hidden = hidden
        self._focus_expand = (card.get_hexpand(), card.get_vexpand())
        self._focused_card = card
        card.set_hexpand(True)
        card.set_vexpand(True)

    def _restore_focused_card(self) -> None:
        """Restore widgets hidden by card focus without exposing other tabs."""
        card = self._focused_card
        if card is not None and self._focus_expand is not None:
            card.set_hexpand(self._focus_expand[0])
            card.set_vexpand(self._focus_expand[1])
        for widget in reversed(self._focus_hidden):
            widget.show()
        self._focused_card = None
        self._focus_hidden = []
        self._focus_expand = None

    def _build_topbar(self) -> Gtk.Box:
        """Top bar: title, tabs, status, theme button."""
        bar = _hbox(spacing=12)
        bar.get_style_context().add_class("topbar")
        name = Gtk.Label(label="Spaced Monitor")
        name.get_style_context().add_class("card-title")
        bar.pack_start(name, expand=False, fill=False, padding=0)
        tabs = _hbox(spacing=4)
        self._tab_btns: dict = {}
        for tab_name in ("Overview", "Processes", "Hardware"):
            btn = Gtk.Button(label=tab_name)
            btn.set_size_request(80, 28)
            btn.connect("clicked", self._on_tab, tab_name.lower())
            self._tab_btns[tab_name.lower()] = btn
            tabs.pack_start(btn, expand=False, fill=False, padding=0)
        bar.pack_start(tabs, expand=True, fill=False, padding=0)
        self._status_lbl = _muted("Updated just now")
        bar.pack_start(self._status_lbl, expand=False, fill=False, padding=0)
        self._theme_btn = Gtk.Button()
        self._theme_btn.set_size_request(28, 28)
        self._theme_btn.connect("clicked", self._on_theme_toggle)
        self._update_theme_btn_icon()
        bar.pack_start(self._theme_btn, expand=False, fill=False, padding=0)
        return bar

    def _update_theme_btn_icon(self) -> None:
        """Set the theme button to a sun or moon icon for the current theme."""
        is_dark = theme_mod._relative_luminance(self._pal.window) < 0.5
        if is_dark:
            self._theme_btn.set_tooltip_text("Switch to light theme")
            icon_name = "weather-clear-night-symbolic"
        else:
            self._theme_btn.set_tooltip_text("Switch to dark theme")
            icon_name = "weather-clear-symbolic"
        child = self._theme_btn.get_child()
        if child:
            self._theme_btn.remove(child)
        img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
        self._theme_btn.add(img)
        img.show()   # added after show_all(): without this the button goes blank

    def _build_overview(self) -> Gtk.ScrolledWindow:
        """Resizable sections that scroll instead of clipping in small windows."""
        self._cpu_card = CpuCard(self._pal)
        self._gpu_card = GpuCard(self._pal)
        self._mem_card = MemoryCard(self._pal)
        self._gmem_card = GpuMemoryCard(self._pal)
        self._temp_card = TemperatureCard(self._pal)
        self._disk_card = DiskCard(self._pal)
        self._net_card = NetworkCard(self._pal)
        self._app_table = AppTable(self._pal)
        # Keep the search controls, column headers and several process rows
        # usable even when the whole overview needs vertical scrolling.
        self._app_table.set_size_request(-1, 180)

        gauges = _flow_row(4, 8)
        for card in (self._cpu_card, self._gpu_card,
                     self._mem_card, self._gmem_card):
            card.set_hexpand(True)
            card.set_size_request(width=80, height=-1)
            gauges.add(card)

        graphs = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # Horizontal shrink must stay enabled so the window can cross the
        # stacking breakpoint. Vertical shrink is disabled when stacked.
        graphs.pack1(self._temp_card, True, True)
        disk_net = _hbox(spacing=10)
        disk_net.pack_start(self._disk_card, expand=True, fill=True, padding=0)
        disk_net.pack_start(self._net_card, expand=True, fill=True, padding=0)
        graphs.pack2(disk_net, True, True)
        self._paned_mid_h = graphs

        inner = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        inner.pack1(graphs, True, False)
        inner.pack2(self._app_table, True, False)
        self._paned_inner = inner

        outer = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        outer.pack1(gauges, False, False)
        outer.pack2(inner, True, False)
        self._paned_outer = outer

        for paned in (outer, inner, graphs):
            # GtkWidget::drag-end is drag-and-drop, not a divider drag.
            paned.connect("button-release-event", self._on_pane_drag)
            paned.connect_after("accept-position", self._on_pane_accept)
        outer.connect("size-allocate", self._on_overview_resize)
        graphs.connect("size-allocate", self._on_graphs_resize)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(outer)
        return scroll

    def _mid_extent(self, ov_w: int, graphs_h: int) -> tuple[bool, int]:
        """Extent (px) the graphs splitter runs along, given its orientation."""
        horizontal = self._paned_mid_h.get_orientation() == Gtk.Orientation.HORIZONTAL
        return horizontal, (ov_w if horizontal else graphs_h)

    def _mid_side_by_side_min(self) -> int:
        """Width below which Temperature / Disk / Network cannot sit side by side."""
        return (self._temp_card.get_preferred_width()[0]
                + self._disk_card.get_preferred_width()[0]
                + self._net_card.get_preferred_width()[0] + 24)

    def _set_mid_orientation(self, ov_w: int) -> None:
        """Stack the graphs row once side-by-side no longer fits.

        GTK3 Paned clips its children instead of refusing to shrink, so below
        this width the disk/network labels were being cut in half; stacking
        keeps every card at its own minimum width.
        """
        want = (Gtk.Orientation.HORIZONTAL
                if ov_w >= self._mid_side_by_side_min()
                else Gtk.Orientation.VERTICAL)
        if self._paned_mid_h.get_orientation() != want:
            self._paned_mid_h.set_orientation(want)
            for child in self._paned_mid_h.get_children():
                self._paned_mid_h.child_set_property(
                    child, "shrink", want == Gtk.Orientation.HORIZONTAL)

    def _restore_panes(self) -> None:
        """Set Paned positions from saved fractions in settings."""
        settings = theme_mod.load_settings()
        self._pane_fracs = load_pane_fractions(settings)
        self._apply_fractions()

    def _on_pane_drag(self, _paned, event) -> bool:
        """Save the completed drag before a subsequent resize can relayout."""
        if event.button == Gdk.BUTTON_PRIMARY:
            self._do_save_panes()
        return False

    def _on_pane_accept(self, _paned) -> bool:
        """Persist a divider position accepted through keyboard navigation."""
        self._do_save_panes()
        return False

    def _on_overview_resize(self, _widget, allocation) -> None:
        """Re-apply saved fractions when the overview's size changes.

        size-allocate also fires for every relayout at the same size (and
        set_position below causes one), so only a real size change counts:
        reacting to all of them re-laid the window out at frame rate.
        """
        size = (allocation.width, allocation.height)
        if size == getattr(self, "_ov_size", None):
            return
        self._ov_size = size
        GLib.timeout_add(0, self._apply_fractions)

    def _apply_fractions(self) -> bool:
        """Set Paned positions from fractions (deferred to after layout pass)."""
        # The content can be taller than the visible viewport. Fractions
        # belong to that content, not to the clipped on-screen rectangle.
        ov_h = self._paned_outer.get_allocated_height()
        ov_w = self._paned_outer.get_allocated_width()
        if ov_h < 1 or ov_w < 1:
            return False
        fr = self._pane_fracs
        pos = max(int(fr["pane_gauges"] * ov_h), self._GAUGE_MIN_H)
        _set_pos(self._paned_outer, pos)
        inner_h = ov_h - pos
        _set_pos(self._paned_inner, int(fr["pane_graphs"] * inner_h))
        self._set_mid_orientation(ov_w)
        self._apply_mid_fraction()
        return False

    def _on_graphs_resize(self, _widget, allocation) -> None:
        """Restore the split after its actual extent/orientation changes."""
        size = (allocation.width, allocation.height,
                self._paned_mid_h.get_orientation())
        if size != getattr(self, "_graphs_size", None):
            self._graphs_size = size
            GLib.idle_add(self._apply_mid_fraction)

    def _apply_mid_fraction(self) -> bool:
        """Use the graph row's height, not the whole lower pane, when stacked."""
        _horizontal, extent = self._mid_extent(
            self._paned_mid_h.get_allocated_width(),
            self._paned_mid_h.get_allocated_height())
        _set_pos(self._paned_mid_h, int(self._pane_fracs["pane_mid_h"] * extent))
        return False

    def _do_save_panes(self) -> bool:
        """Persist current pane positions as fractions."""
        ov_h = self._paned_outer.get_allocated_height()
        ov_w = self._paned_outer.get_allocated_width()
        if ov_h < 1 or ov_w < 1:
            return False
        pos_m = self._paned_mid_h.get_position()
        pos_i = self._paned_inner.get_position()
        pos_g = self._paned_outer.get_position()
        inner_h = self._paned_inner.get_allocated_height()
        _horizontal, extent = self._mid_extent(
            self._paned_mid_h.get_allocated_width(),
            self._paned_mid_h.get_allocated_height())
        fracs = {
            "pane_gauges": pos_g / ov_h,
            "pane_graphs": pos_i / inner_h if inner_h > 0 else 0.28,
            "pane_mid_h": pos_m / extent if extent > 0 else 0.5,
        }
        settings = theme_mod.load_settings()
        settings = save_pane_fractions(settings, fracs)
        self._pane_fracs = load_pane_fractions(settings)
        theme_mod.save_settings(settings)
        return False

    def _build_footer(self) -> Gtk.Box:
        """Footer strip: four icon+text items split by thin border lines."""
        row = _hbox(spacing=0)
        row.get_style_context().add_class("footer")
        self._f_fans = FooterItem("Fans", "weather-windy-symbolic")
        self._f_cpu_pow = FooterItem("CPU power", "system-run-symbolic")
        self._f_gpu_pow = FooterItem("GPU power",
                                     "battery-full-charged-symbolic")
        self._f_uptime = FooterItem("Uptime", "alarm-symbolic")
        items = (self._f_fans, self._f_cpu_pow, self._f_gpu_pow,
                 self._f_uptime)
        for index, item in enumerate(items):
            if index:
                item.get_style_context().add_class("footer-sep")
            row.pack_start(item, expand=True, fill=True, padding=0)
        return row

    def _on_tab(self, _btn, name: str) -> None:
        """Switch to the clicked page."""
        if name == self._tab or name not in self._pages:
            return
        self._tab = name
        self._show_tab()
        self._refresh_visible_page()

    def _refresh_visible_page(self) -> None:
        """Give a page that just became visible the latest data at once."""
        snap = getattr(self, "_snapshot", None)
        apps = getattr(self, "_apps_latest", None)
        if self._tab == "hardware" and snap is not None:
            self._hardware_page.update(snap)
        elif self._tab == "overview" and apps is not None:
            self._app_table.set_apps(apps)
        elif self._tab == "processes" and apps is not None:
            self._processes_page.set_apps(apps)

    def show_tab_only(self) -> None:
        """After show_all(): hide every page but the selected one again."""
        self._show_tab()

    def _show_tab(self) -> None:
        """Show one page at a time and mark its tab button as selected."""
        for key, page in self._pages.items():
            page.set_visible(key == self._tab)
        for key, btn in self._tab_btns.items():
            ctx = btn.get_style_context()
            if key == self._tab:
                ctx.add_class("tab-selected")
            else:
                ctx.remove_class("tab-selected")

    def start_worker(self) -> None:
        """Start the sampler thread."""
        self._thread = threading.Thread(target=self._worker_loop,
                                        daemon=True)
        self._thread.start()

    def _worker_loop(self) -> None:
        """Sample snapshots every refresh; the app list every 2 seconds."""
        while not self._stop_event.is_set():
            try:
                snap = self._sampler()
            except Exception as exc:
                snap = None
                self._report_error("sampling", exc)
            if snap is not None:
                GLib.idle_add(self._apply_snapshot, snap)
            if time.monotonic() - self._last_proc >= 2.0:
                self._last_proc = time.monotonic()
                try:
                    apps = self._proc_sampler()
                except Exception as exc:
                    apps = None
                    self._report_error("process sampling", exc)
                if apps is not None:
                    GLib.idle_add(self._apply_apps, apps)
            self._stop_event.wait(self._refresh_ms / 1000.0)

    def _report_error(self, what: str, exc: Exception) -> None:
        """Print each distinct worker error once to stderr instead of swallowing it."""
        key = f"{what}: {type(exc).__name__}: {exc}"
        seen = self.__dict__.setdefault("_reported", set())
        if key not in seen:
            seen.add(key)
            print(f"spaced-monitor: {key}", file=sys.stderr)

    def _apply_snapshot(self, snap: Snapshot) -> bool:
        """Apply a snapshot on the GTK thread; returns False to stop."""
        self._snapshot = snap
        self._last_sample_time = time.monotonic()
        self._cpu_card.update(snap)
        self._gpu_card.update(snap)
        self._mem_card.update(snap)
        self._gmem_card.update(snap)
        self._temp_card.update(snap)
        self._disk_card.update(snap)
        self._net_card.update(snap)
        self._update_footer(snap)
        # Hidden pages are not rebuilt every second; _refresh_visible_page
        # catches them up when they are shown.
        if self._tab == "hardware":
            self._hardware_page.update(snap)
        self._status_lbl.set_text("Updated just now")
        return False

    def _apply_apps(self, apps: list) -> bool:
        """Hand the process sampler's app list to the app list on screen.

        Both lists rebuild every row's widgets, so only the visible one does.
        """
        self._apps_latest = apps
        if self._tab == "overview":
            self._app_table.set_apps(apps)
        elif self._tab == "processes":
            self._processes_page.set_apps(apps)
        return False

    def _update_footer(self, snap: Snapshot) -> None:
        """Refresh footer values."""
        fans = snap.fans
        total_rpm = sum(f.rpm for f in fans) if fans else None
        self._f_fans.set_value(fmt.rpm(total_rpm))
        self._f_cpu_pow.set_value(fmt.watts(snap.cpu_power_w))
        gpu = snap.gpu
        self._f_gpu_pow.set_value(fmt.watts(gpu.power_w if gpu else None))
        self._f_uptime.set_value(fmt.duration(snap.uptime_s))

    def _on_close(self, *_args) -> bool:
        """Stop the worker thread on window close."""
        self._stop_event.set()
        return False

    def _on_theme_toggle(self, _btn) -> None:
        """Toggle between 'follow desktop' and the opposite of the desktop palette."""
        if self._follow_desktop:
            # Override: pick the opposite of what the desktop would give us.
            desktop_pal = self._desktop_palette()
            is_dark = theme_mod._relative_luminance(desktop_pal.window) < 0.5
            new = "light" if is_dark else "dark"
            self._follow_desktop = False
            self._apply_theme(new)
        else:
            # Return to following the desktop.
            self._follow_desktop = True
            self._rebuild_from_gtk()
        settings = theme_mod.load_settings()
        settings["theme"] = "system" if self._follow_desktop else (
            "dark" if self._pal is theme_mod.DARK else "light")
        theme_mod.save_settings(settings)

    def _desktop_palette(self) -> theme_mod.Palette:
        """Return the palette the desktop theme would produce."""
        try:
            win = self._overview
            ctx = win.get_style_context()
            return theme_mod.palette_from_gtk(ctx)
        except Exception:
            return theme_mod.palette("dark")

    def _rebuild_from_gtk(self) -> None:
        """Rebuild palette from the active GTK theme and redraw."""
        try:
            ctx = self.get_style_context()
            pal = theme_mod.palette_from_gtk(ctx)
        except Exception:
            pal = theme_mod.palette("dark")
        self._apply_palette(pal)

    def _on_gtk_settings_change(self, _settings, _event) -> None:
        """A desktop theme change always returns to 'follow desktop'."""
        if not self._follow_desktop:
            self._follow_desktop = True
            settings = theme_mod.load_settings()
            settings["theme"] = "system"
            theme_mod.save_settings(settings)
        self._rebuild_from_gtk()

    def _apply_theme(self, name: str) -> None:
        """Switch to a fixed palette (dark or light)."""
        pal = theme_mod.palette(name)
        self._apply_palette(pal)

    def _apply_palette(self, pal: theme_mod.Palette) -> None:
        """Apply a palette: re-apply CSS, redraw widgets."""
        self._pal = pal
        theme_mod.apply_css(pal)
        for card in (self._cpu_card, self._gpu_card,
                     self._mem_card, self._gmem_card,
                     self._temp_card, self._disk_card, self._net_card):
            card.set_palette(pal)
        self._app_table.set_palette(pal)
        self._processes_page.set_palette(pal)
        self._hardware_page.set_palette(pal)
        self._show_tab()
        self._update_theme_btn_icon()

    def update_status_dot(self) -> None:
        """Called periodically to update the 'Updated Xs ago' label."""
        if self._snapshot is None:
            return
        elapsed = time.monotonic() - self._last_sample_time
        if elapsed >= 3.0:
            self._status_lbl.set_text(f"Updated {int(elapsed)} s ago")


class MonitorApp(Gtk.Application):
    """GTK Application wrapper."""

    def __init__(self, sampler: Callable[[], Snapshot],
                 refresh_ms: int = 1000) -> None:
        super().__init__()
        self._sampler = sampler
        self._refresh_ms = refresh_ms
        self._window: Optional[MonitorWindow] = None
        self._status_source = 0
        self._settings_handlers: list = []

    def do_startup(self) -> None:  # type: ignore[override]
        """Create the window on startup."""
        Gtk.Application.do_startup(self)
        settings = theme_mod.load_settings()
        gtk_settings = (self.get_default_style_settings()
                        if hasattr(self, "get_default_style_settings") else None)
        theme_name = theme_mod.resolve_theme(
            str(settings.get("theme", "system")), gtk_settings)
        pal = theme_mod.palette(theme_name)
        theme_mod.apply_css(pal)
        self._window = MonitorWindow(
            sampler=self._sampler,
            refresh_ms=int(settings.get("refresh_ms", self._refresh_ms)),
            pal=pal,
        )
        # Gtk.Application owns the loop while its registered window exists.
        # Without this, run() returns immediately and a second Gtk.main()
        # keeps an invisible process alive after the window is destroyed.
        self.add_window(self._window)
        self._window.show_all()
        self._window.show_tab_only()
        self._window._restore_panes()
        self._window.start_worker()
        self._status_source = GLib.timeout_add(3000, self._tick_status)
        # If following the desktop, rebuild palette from the real GTK theme.
        if str(settings.get("theme", "system")) == "system":
            self._window._follow_desktop = True
            self._window._rebuild_from_gtk()
        # Connect to GTK settings changes for live theme following.
        self._connect_gtk_settings()

    def _tick_status(self) -> bool:
        """Update the status dot every 3 seconds."""
        if self._window:
            self._window.update_status_dot()
        return True

    def _connect_gtk_settings(self) -> None:
        """Connect to Gtk.Settings notifications for live theme following."""
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk as _Gtk
            gtk_settings = _Gtk.Settings.get_default()
            if self._window:
                for signal in ("notify::gtk-theme-name",
                               "notify::gtk-application-prefer-dark-theme"):
                    handler = gtk_settings.connect(
                        signal, self._window._on_gtk_settings_change)
                    self._settings_handlers.append((gtk_settings, handler))
        except Exception:
            pass

    @property
    def window(self) -> Optional[MonitorWindow]:
        """The window created during startup, if any."""
        return self._window

    def do_activate(self) -> None:  # type: ignore[override]
        """Bring the window forward; required or GTK quits after startup."""
        if self._window:
            self._window.show_all()
            self._window.show_tab_only()
            self._window.grab_focus()

    def do_shutdown(self) -> None:  # type: ignore[override]
        """Clean shutdown."""
        if self._window:
            self._window._stop_event.set()
        if self._status_source:
            GLib.source_remove(self._status_source)
            self._status_source = 0
        for settings, handler in self._settings_handlers:
            settings.disconnect(handler)
        self._settings_handlers.clear()
        Gtk.Application.do_shutdown(self)


def _display_problem() -> str:
    """Explain why GTK cannot show a window, in terms the user can act on."""
    disp = os.environ.get("DISPLAY")
    way = os.environ.get("WAYLAND_DISPLAY")
    if not disp and not way:
        return ("no display connection: DISPLAY and WAYLAND_DISPLAY are both unset. "
                "Run it from your desktop session (for example "
                "DISPLAY=:0 spaced-monitor), or render it headless with xvfb-run.")
    return (f"GTK cannot connect to the display (DISPLAY={disp or 'unset'}, "
            f"WAYLAND_DISPLAY={way or 'unset'}). Check XAUTHORITY, or start the app "
            "from the session that owns the screen.")


def main(argv: list[str] | None = None) -> int:
    """Entry point: run the real application."""
    args = argv if argv is not None else sys.argv[1:]
    if "--version" in args or "-V" in args:
        from spaced_monitor import __version__
        print(f"spaced-monitor {__version__}")
        return 0
    # Fail with a sentence, not a GTK assertion dump: init_check() answers whether
    # a display can be reached at all, and does not crash when it cannot.
    # With neither variable set there is no display to reach, even if GTK was
    # already initialised earlier in this process.
    no_env = not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    if no_env or not Gtk.init_check()[0]:
        print(f"spaced-monitor: {_display_problem()}", file=sys.stderr)
        return 1
    sampler_obj = Sampler()
    app = MonitorApp(sampler=sampler_obj.sample)
    return app.run(["spaced-monitor", *args])
