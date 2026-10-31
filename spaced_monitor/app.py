# SPDX-License-Identifier: GPL-3.0-or-later
"""Main application: window, top bar, pages, cards, footer, worker thread."""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from spaced_monitor import theme as theme_mod
from spaced_monitor import format as fmt
from spaced_monitor.cards import (CpuCard, GpuCard, MemoryCard, GpuMemoryCard,
                                  TemperatureCard, DiskCard, NetworkCard)
from spaced_monitor.apptable import AppTable
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


def _lbl(text: str, css: str = "value") -> Gtk.Label:
    """Label with a CSS class."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class(css)
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    lbl.set_ellipsize(1)
    return lbl


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
        self._user_dragged = False
        self._pane_fracs = default_fractions()
        self._build_ui()
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
        self.add(root)

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
        is_dark = self._pal is theme_mod.DARK
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

    def _build_overview(self) -> Gtk.Paned:
        """Overview page: three resizable sections via nested vertical Paned."""
        self._cpu_card = CpuCard(self._pal)
        self._gpu_card = GpuCard(self._pal)
        self._mem_card = MemoryCard(self._pal)
        self._gmem_card = GpuMemoryCard(self._pal)
        self._temp_card = TemperatureCard(self._pal)
        self._disk_card = DiskCard(self._pal)
        self._net_card = NetworkCard(self._pal)
        self._app_table = AppTable(self._pal)

        gauges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for card in (self._cpu_card, self._gpu_card,
                     self._mem_card, self._gmem_card):
            gauges.pack_start(card, True, True, 0)

        graphs = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        graphs.pack1(self._temp_card, True, True)
        disk_net = _hbox(spacing=10)
        disk_net.pack_start(self._disk_card, expand=True, fill=True, padding=0)
        disk_net.pack_start(self._net_card, expand=True, fill=True, padding=0)
        graphs.pack2(disk_net, True, True)
        self._paned_mid_h = graphs

        inner = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        inner.pack1(graphs, True, True)
        inner.pack2(self._app_table, True, True)
        self._paned_inner = inner

        outer = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        outer.pack1(gauges, False, False)
        outer.pack2(inner, True, True)
        self._paned_outer = outer

        outer.connect("drag-end", self._on_pane_drag)
        inner.connect("drag-end", self._on_pane_drag)
        graphs.connect("drag-end", self._on_pane_drag)
        outer.connect("size-allocate", self._on_overview_resize)
        return outer

    def _restore_panes(self) -> None:
        """Set Paned positions from saved fractions in settings."""
        settings = theme_mod.load_settings()
        fr = load_pane_fractions(settings)
        self._pane_fracs = fr
        ov_h = self._overview.get_allocated_height() or 900
        pos = max(int(fr["pane_gauges"] * ov_h), self._GAUGE_MIN_H)
        self._paned_outer.set_position(pos)
        inner_h = ov_h - pos
        self._paned_inner.set_position(int(fr["pane_graphs"] * inner_h))
        ov_w = self._overview.get_allocated_width() or 1400
        self._paned_mid_h.set_position(int(fr["pane_mid_h"] * ov_w))

    def _on_pane_drag(self, paned, _handle, _is_reposition) -> None:
        """Save pane fractions after the user stops dragging."""
        self._user_dragged = True
        GLib.timeout_add(300, self._do_save_panes)

    def _on_overview_resize(self, _widget, _allocation) -> None:
        """Re-apply saved fractions on every resize unless user dragged this session."""
        if self._user_dragged:
            return
        GLib.timeout_add(0, self._apply_fractions)

    def _apply_fractions(self) -> bool:
        """Set Paned positions from fractions (deferred to after layout pass)."""
        ov_h = self._overview.get_allocated_height()
        ov_w = self._overview.get_allocated_width()
        if ov_h < 1 or ov_w < 1:
            return False
        fr = self._pane_fracs
        pos = max(int(fr["pane_gauges"] * ov_h), self._GAUGE_MIN_H)
        self._paned_outer.set_position(pos)
        inner_h = ov_h - pos
        self._paned_inner.set_position(int(fr["pane_graphs"] * inner_h))
        self._paned_mid_h.set_position(int(fr["pane_mid_h"] * ov_w))
        return False

    def _do_save_panes(self) -> bool:
        """Persist current pane positions as fractions."""
        ov_h = self._overview.get_allocated_height()
        ov_w = self._overview.get_allocated_width()
        if ov_h < 1 or ov_w < 1:
            return False
        pos_g = self._paned_outer.get_position()
        pos_i = self._paned_inner.get_position()
        pos_m = self._paned_mid_h.get_position()
        inner_h = ov_h - pos_g
        fracs = {
            "pane_gauges": pos_g / ov_h,
            "pane_graphs": pos_i / inner_h if inner_h > 0 else 0.28,
            "pane_mid_h": pos_m / ov_w,
        }
        settings = theme_mod.load_settings()
        settings = save_pane_fractions(settings, fracs)
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
        self._hardware_page.update(snap)
        self._status_lbl.set_text("Updated just now")
        return False

    def _apply_apps(self, apps: list) -> bool:
        """Hand the process sampler's app list to both app lists."""
        self._app_table.set_apps(apps)
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
        """Toggle dark/light theme."""
        current = "dark" if self._pal is theme_mod.DARK else "light"
        new = "light" if current == "dark" else "dark"
        self._apply_theme(new)

    def _apply_theme(self, name: str) -> None:
        """Switch palette, re-apply CSS, redraw widgets."""
        pal = theme_mod.palette(name)
        self._pal = pal
        theme_mod.apply_css(pal)
        for card in (self._cpu_card, self._gpu_card,
                     self._mem_card, self._gmem_card,
                     self._temp_card, self._disk_card, self._net_card):
            card.set_palette(pal)
        self._processes_page.set_palette(pal)
        self._hardware_page.set_palette(pal)
        self._show_tab()
        self._update_theme_btn_icon()
        settings = theme_mod.load_settings()
        settings["theme"] = name
        theme_mod.save_settings(settings)

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
        self._window.show_all()
        self._window.show_tab_only()
        self._window._restore_panes()
        self._window.start_worker()
        GLib.timeout_add(3000, self._tick_status)

    def _tick_status(self) -> bool:
        """Update the status dot every 3 seconds."""
        if self._window:
            self._window.update_status_dot()
        return True

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

    def do_quit(self) -> None:  # type: ignore[override]
        """Clean shutdown."""
        if self._window:
            self._window._stop_event.set()
        Gtk.Application.do_quit(self)


def main(argv: list[str] | None = None) -> int:
    """Entry point: run the real application."""
    args = argv if argv is not None else sys.argv[1:]
    if "--version" in args or "-V" in args:
        from spaced_monitor import __version__
        print(f"spaced-monitor {__version__}")
        return 0
    sampler_obj = Sampler()
    app = MonitorApp(sampler=sampler_obj.sample)
    app.run(args)
    if app.window is None:
        return 1
    # This GTK build never calls do_main, so drive the loop here; it returns
    # when the window closes.
    Gtk.main()
    app.quit()
    return 0
