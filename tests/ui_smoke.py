# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless UI smoke test: render overview in dark and light themes."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from spaced_monitor import theme as theme_mod
from spaced_monitor.collect import (
    Snapshot, CpuInfo, MemInfo, GpuInfo, DiskInfo, NetInfo, Fan,
)
from spaced_monitor.cards import (CpuCard, GpuCard, MemoryCard, GpuMemoryCard,
                                  TemperatureCard, DiskCard, NetworkCard)
from spaced_monitor.apptable import AppTable
from spaced_monitor.processes import AppUsage

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "build" / "screenshots"


def _mock_snapshot() -> Snapshot:
    """Return a Snapshot matching the mockup numbers."""
    cpu = CpuInfo(
        model="Ryzen 7 7800X3D", percent=42.0,
        per_core=[42.0] * 16, freq_mhz=4600.0, temp_c=62.0,
    )
    mem = MemInfo(
        total=32 * 1024**3, apps=int(14.1 * 1024**3),
        cache=int(6.0 * 1024**3), available=int(7.4 * 1024**3),
        swap_used=int(4.2 * 1024**3), swap_total=8 * 1024**3,
    )
    gpu = GpuInfo(
        name="RTX 4070 Ti SUPER", percent=67.0, temp_c=72.0,
        power_w=235.0, mem_used=int(13.2 * 1024**3),
        mem_total=16 * 1024**3,
    )
    disk = DiskInfo(read_bps=128 * 1024**2, write_bps=940 * 1024,
                    used=None, total=None)
    net = NetInfo(rx_bps=50 * 1024**2, tx_bps=10 * 1024**2)
    fans = [Fan(label="fan1", rpm=1240)]
    return Snapshot(
        cpu=cpu, memory=mem, gpu=gpu, disk=disk, net=net,
        fans=fans, cpu_power_w=48.0, uptime_s=3 * 3600 + 42 * 60,
        time=datetime.now(),
    )


def _build_overview(pal, snap: Snapshot) -> Gtk.Box:
    """Build the overview layout: top bar, cards row, footer."""
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    # Top bar
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    bar.get_style_context().add_class("topbar")
    bar.pack_start(Gtk.Label(label="S"), False, False, 0)
    bar.pack_start(Gtk.Label(label="Spaced Monitor"), False, False, 0)
    bar.pack_start(Gtk.Label(label="Updated just now"), True, False, 0)
    root.pack_start(bar, False, True, 0)
    # Cards row
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    cards = []
    for cls, kind in ((CpuCard, "cpu"), (GpuCard, "gpu"),
                      (MemoryCard, "memory"), (GpuMemoryCard, "gpu_memory")):
        card = cls(pal)
        card.update(snap)
        cards.append(card)
        row.pack_start(card, True, True, 0)
    root.pack_start(row, False, True, 0)
    # Graph row: temperature (wide), disk, network
    graphs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    temp_card = TemperatureCard(pal)
    temp_card.update(snap)
    graphs.pack_start(temp_card, True, True, 0)
    disk_card = DiskCard(pal)
    disk_card.update(snap)
    graphs.pack_start(disk_card, False, True, 0)
    net_card = NetworkCard(pal)
    net_card.update(snap)
    graphs.pack_start(net_card, False, True, 0)
    root.pack_start(graphs, True, True, 0)
    # App table
    apps = [
        AppUsage("brave", [10, 11], 12.0, int(1.4 * 1024**3), 0.0, 0,
                 940 * 1024, "rhy", "brave"),
        AppUsage("strata", [20], 33.0, int(2.1 * 1024**3), 67.0,
                 int(13.2 * 1024**3), 128 * 1024**2, "rhy", ""),
        AppUsage("python3", [30], 5.0, int(0.3 * 1024**3), 0.0, 0,
                 0.0, "rhy", ""),
    ]
    table = AppTable(pal, rows=5)
    table.set_apps(apps)
    root.pack_start(table, True, True, 0)
    # Footer
    footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    footer.get_style_context().add_class("footer")
    for label in ("Fans", "CPU power", "GPU power", "Uptime"):
        item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        item.pack_start(Gtk.Label(label=label), False, False, 0)
        item.pack_start(Gtk.Label(label="—"), False, False, 0)
        footer.pack_start(item, True, True, 0)
    root.pack_start(footer, False, True, 0)
    return root


def _show_and_map(w: Gtk.Widget) -> None:
    """Recursively show and map a widget tree (GTK 3.24 needs explicit show/map)."""
    w.show()
    if hasattr(w, "get_children"):
        for c in w.get_children():
            _show_and_map(c)
    if w.get_realized():
        w.map()


def _capture(box: Gtk.Box, path: str, pal) -> bool:
    """Render a box to PNG via an OffscreenWindow."""
    off = Gtk.OffscreenWindow()
    off.set_size_request(1400, 900)
    screen = off.get_style_context().get_screen()
    theme_mod.apply_css(pal, screen=screen)
    off.add(box)
    _show_and_map(off)
    off.queue_resize()

    captured = [False]

    def _grab():
        surface = off.get_surface()
        if surface is not None:
            surface.write_to_png(path)
        captured[0] = True
        off.close()
        Gtk.main_quit()
        return False

    GLib.timeout_add(100, _grab)
    Gtk.main()
    return captured[0] and os.path.exists(path) and os.path.getsize(path) > 20 * 1024


def run_screenshots() -> list[str]:
    """Build the overview with mock data and capture dark + light screenshots."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = _mock_snapshot()
    paths = []
    for theme_name in ("dark", "light"):
        pal = theme_mod.palette(theme_name)
        box = _build_overview(pal, snap)
        path = str(SCREENSHOT_DIR / f"overview-{theme_name}.png")
        ok = _capture(box, path, pal)
        if not ok:
            print(f"FAIL: {path} missing or too small", file=sys.stderr)
            return []
        paths.append(path)
    return paths


def main() -> int:
    """Run the smoke test."""
    paths = run_screenshots()
    if not paths:
        return 1
    for p in paths:
        print(f"OK: {p} ({os.path.getsize(p)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
