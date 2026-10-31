# SPDX-License-Identifier: GPL-3.0-or-later
"""Main application: window, top bar, pages, cards, footer, worker thread."""

from __future__ import annotations

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
from spaced_monitor.collect import Sampler, Snapshot
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
    return lbl


def _muted(text: str) -> Gtk.Label:
    """Muted label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("muted")
    lbl.set_xalign(0.0)
    return lbl


def _big(text: str) -> Gtk.Label:
    """Big-value label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("big-value")
    lbl.set_xalign(0.0)
    return lbl


def _title(text: str) -> Gtk.Label:
    """Card-title label."""
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class("card-title")
    lbl.set_xalign(0.0)
    return lbl


class FooterItem(Gtk.Box):
    """One footer cell: muted label above a value."""

    def __init__(self, label_text: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.get_style_context().add_class("footer-item")
        self._m = _muted(label_text)
        self._v = _lbl(fmt.EMDASH, "value")
        self.pack_start(self._m, expand=False, fill=False, padding=0)
        self.pack_start(self._v, expand=False, fill=False, padding=0)

    def set_value(self, text: str) -> None:
        """Update the value text."""
        self._v.set_text(text)


class MonitorWindow(Gtk.Window):
    """The main Spaced Monitor window."""

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
        self._build_ui()
        self.connect("destroy", self._on_close)

    def _build_ui(self) -> None:
        """Build the full window layout."""
        root = _vbox(spacing=0)
        root.pack_start(self._build_topbar(), expand=False, fill=True, padding=0)
        root.pack_start(self._build_cards(), expand=True, fill=True, padding=0)
        root.pack_start(self._build_footer(), expand=False, fill=True, padding=0)
        self.add(root)

    def _build_topbar(self) -> Gtk.Box:
        """Top bar: logo, tabs, status, theme button."""
        bar = _hbox(spacing=12)
        bar.get_style_context().add_class("topbar")
        logo = Gtk.Label(label="S")
        logo.get_style_context().add_class("card-title")
        bar.pack_start(logo, expand=False, fill=False, padding=0)
        name = Gtk.Label(label="Spaced Monitor")
        name.get_style_context().add_class("card-title")
        bar.pack_start(name, expand=False, fill=False, padding=0)
        tabs = _hbox(spacing=4)
        for tab_name in ("Overview", "Processes", "Hardware"):
            btn = Gtk.Button(label=tab_name)
            btn.set_size_request(80, 28)
            tabs.pack_start(btn, expand=False, fill=False, padding=0)
        bar.pack_start(tabs, expand=True, fill=False, padding=0)
        self._status_lbl = _muted("Updated just now")
        bar.pack_start(self._status_lbl, expand=False, fill=False, padding=0)
        self._theme_btn = Gtk.Button(label="●")
        self._theme_btn.set_size_request(28, 28)
        self._theme_btn.connect("clicked", self._on_theme_toggle)
        bar.pack_start(self._theme_btn, expand=False, fill=False, padding=0)
        return bar

    def _build_cards(self) -> Gtk.Box:
        """Middle of the page: gauge row, graph row, then the app table."""
        col = _vbox(spacing=10)
        gauges = _hbox(spacing=10)
        self._cpu_card = CpuCard(self._pal)
        self._gpu_card = GpuCard(self._pal)
        self._mem_card = MemoryCard(self._pal)
        self._gmem_card = GpuMemoryCard(self._pal)
        for card in (self._cpu_card, self._gpu_card,
                     self._mem_card, self._gmem_card):
            gauges.pack_start(card, expand=True, fill=True, padding=0)
        col.pack_start(gauges, expand=False, fill=True, padding=0)
        graphs = _hbox(spacing=10)
        self._temp_card = TemperatureCard(self._pal)
        self._disk_card = DiskCard(self._pal)
        self._net_card = NetworkCard(self._pal)
        graphs.pack_start(self._temp_card, expand=True, fill=True, padding=0)
        graphs.pack_start(self._disk_card, expand=False, fill=True, padding=0)
        graphs.pack_start(self._net_card, expand=False, fill=True, padding=0)
        col.pack_start(graphs, expand=True, fill=True, padding=0)
        self._app_table = AppTable(self._pal, rows=5)
        col.pack_start(self._app_table, expand=True, fill=True, padding=0)
        return col

    def _build_footer(self) -> Gtk.Box:
        """Footer row with four items."""
        row = _hbox(spacing=0)
        row.get_style_context().add_class("footer")
        self._f_fans = FooterItem("Fans")
        self._f_cpu_pow = FooterItem("CPU power")
        self._f_gpu_pow = FooterItem("GPU power")
        self._f_uptime = FooterItem("Uptime")
        for item in (self._f_fans, self._f_cpu_pow,
                     self._f_gpu_pow, self._f_uptime):
            row.pack_start(item, expand=True, fill=True, padding=0)
        return row

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
            except Exception:
                snap = None
            if snap is not None:
                GLib.idle_add(self._apply_snapshot, snap)
            if time.monotonic() - self._last_proc >= 2.0:
                self._last_proc = time.monotonic()
                try:
                    apps = self._proc_sampler()
                except Exception:
                    apps = None
                if apps is not None:
                    GLib.idle_add(self._apply_apps, apps)
            self._stop_event.wait(self._refresh_ms / 1000.0)

    def _apply_snapshot(self, snap: Snapshot) -> bool:
        """Apply a snapshot on the GTK thread; returns False to stop."""
        self._snapshot = snap
        self._last_sample_time = time.monotonic()
        self._cpu_card.update(snap)
        self._gpu_card.update(snap)
        self._mem_card.update(snap)
        self._gmem_card.update(snap)
        self._temp_card.push(snap.cpu.temp)
        self._disk_card.update(snap.disk)
        self._net_card.update(snap.net)
        self._update_footer(snap)
        self._status_lbl.set_text("Updated just now")
        return False

    def _apply_apps(self, apps: list) -> bool:
        """Hand the process sampler's app list to the app table."""
        self._app_table.set_apps(apps)
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
        super().__init__(app_name="Monitor",
                        app_id="org.spacedlinux.Monitor")
        self._sampler = sampler
        self._refresh_ms = refresh_ms
        self._window: Optional[MonitorWindow] = None

    def do_startup(self) -> None:  # type: ignore[override]
        """Create the window on startup."""
        Gtk.Application.do_startup(self)
        settings = theme_mod.load_settings()
        gtk_settings = self.get_default_style_settings()
        theme_name = theme_mod.resolve_theme(
            str(settings.get("theme", "system")), gtk_settings)
        pal = theme_mod.palette(theme_name)
        theme_mod.apply_css(pal)
        self._window = MonitorWindow(
            sampler=self._sampler,
            refresh_ms=int(settings.get("refresh_ms", self._refresh_ms)),
            pal=pal,
        )
        self._window.show()
        self._window.start_worker()
        GLib.set_timeout(3000, self._tick_status)

    def _tick_status(self) -> bool:
        """Update the status dot every 3 seconds."""
        if self._window:
            self._window.update_status_dot()
        return True

    def do_quit(self) -> None:  # type: ignore[override]
        """Clean shutdown."""
        if self._window:
            self._window._stop_event.set()
        Gtk.Application.do_quit(self)


def main(argv: list[str] | None = None) -> int:
    """Entry point: run the real application."""
    sampler_obj = Sampler()
    app = MonitorApp(sampler=sampler_obj.sample)
    return app.run(argv or [])
