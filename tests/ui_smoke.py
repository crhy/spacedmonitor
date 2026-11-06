# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless UI smoke test: render overview, processes and hardware pages."""

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
    Temperature, Filesystem, Interface, GpuExtra,
)
from spaced_monitor.cards import (CpuCard, GpuCard, MemoryCard, GpuMemoryCard,
                                  TemperatureCard, DiskCard, NetworkCard)
from spaced_monitor.apptable import AppTable
from spaced_monitor.app import FooterItem
from spaced_monitor.pages import HardwarePage, ProcessesPage
from spaced_monitor.processes import AppUsage, ProcUsage

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "build" / "screenshots"


def _mock_snapshot() -> Snapshot:
    """Return a Snapshot matching the mockup numbers."""
    cpu = CpuInfo(
        model="Ryzen 7 7800X3D", percent=42.0,
        per_core=[float((i * 37) % 100) for i in range(16)], freq_mhz=4600.0,
        temp_c=62.0,
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
                    used=int(48 * 1024**3), total=int(240 * 1024**3))
    net = NetInfo(rx_bps=50 * 1024**2, tx_bps=10 * 1024**2)
    fans = [Fan(label="fan1", rpm=1240)]
    temps = [Temperature("cpu", "core", 58.0), Temperature("cpu", "vr", 74.0),
             Temperature("gpu", "hotspot", 86.0), Temperature("nvme", "drive",
                                                             49.0)]
    files = [Filesystem("/", "ext4", int(48 * 1024**3), int(240 * 1024**3)),
             Filesystem("/home", "ext4", int(120 * 1024**3),
                        int(480 * 1024**3)),
             Filesystem("/var", "xfs", int(9 * 1024**3), int(64 * 1024**3))]
    ifaces = [Interface("eth0", "192.168.4.1", 50 * 1024**2, 10 * 1024**2),
              Interface("wlan0", "10.0.0.7", 4 * 1024**2, 1 * 1024**2)]
    extra = GpuExtra(driver="5611.5", link_gen="4", link_width="16")
    return Snapshot(
        cpu=cpu, memory=mem, gpu=gpu, disk=disk, net=net,
        fans=fans, cpu_power_w=48.0, uptime_s=3 * 3600 + 42 * 60,
        time=datetime.now(), temperatures=temps, filesystems=files,
        interfaces=ifaces, gpu_extra=extra,
    )


def _mock_apps(count: int = 40) -> list:
    """Return `count` mock apps, each with three child processes."""
    names = ["brave", "strata", "python3", "firefox", "steam", "code",
             "gimp", "inkscape", "obs", "postgres", "nginx", "mpv"]
    apps = []
    for i in range(count):
        name = names[i % len(names)]
        kids = [ProcUsage(1000 + i * 3 + j, name, float((i + j) % 30),
                          int((i + 1) * 0.2 * 1024**3)) for j in range(3)]
        apps.append(AppUsage(name, [1000 + i * 3], float(i % 40),
                             int((i % 12) * 0.4 * 1024**3), float(i % 70),
                             int((i % 5) * 0.6 * 1024**3), float(i * 4096),
                             "root" if i % 5 == 0 else "rhy", name, kids))
    return apps


def _build_overview(pal, snap: Snapshot) -> Gtk.Box:
    """Build the overview layout: top bar, cards row, footer."""
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    # Top bar
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    bar.get_style_context().add_class("topbar")
    # Logo: 28px circle in GPU blue with white bold S
    import cairo
    logo = Gtk.DrawingArea()
    logo.set_size_request(28, 28)
    def _draw_logo(da, cr):
        cr.set_source_rgb(*pal.gpu_start)
        cr.arc(14, 14, 13, 0, 2 * 3.14159)
        cr.fill()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(16)
        cr.set_source_rgb(1, 1, 1)
        m = cr.text_extents("S")
        cr.move_to(14 - m.x_bearing - m.width / 2, 14 - m.y_bearing - m.height / 2)
        cr.show_text("S")
    logo.connect("draw", _draw_logo)
    bar.pack_start(logo, False, False, 0)
    bar.pack_start(Gtk.Label(label="Spaced Monitor"), False, False, 0)
    # Tabs: the same plain buttons the app uses, one marked selected
    tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    for tab_name in ("Overview", "Processes", "Hardware"):
        btn = Gtk.Button(label=tab_name)
        btn.set_size_request(80, 28)
        if tab_name == "Overview":
            btn.get_style_context().add_class("tab-selected")
        tabs.pack_start(btn, False, False, 0)
    bar.pack_start(tabs, True, False, 0)
    # Green dot + status
    status = Gtk.Label(label='<span foreground="#22c55e">●</span> Updated just now')
    status.set_use_markup(True)
    bar.pack_start(status, False, False, 0)
    # Theme button
    theme_btn = Gtk.Button()
    theme_btn.set_image(Gtk.Image.new_from_icon_name(
        "weather-clear-night-symbolic", Gtk.IconSize.BUTTON))
    theme_btn.set_size_request(28, 28)
    bar.pack_start(theme_btn, False, False, 0)
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
    for i in range(300):
        temp_card.update(snap)
    graphs.pack_start(temp_card, True, True, 0)
    disk_card = DiskCard(pal)
    for i in range(300):
        disk_card.update(snap)
    graphs.pack_start(disk_card, False, True, 0)
    net_card = NetworkCard(pal)
    for i in range(300):
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
        AppUsage("firefox", [40, 41, 42], 8.0, int(0.9 * 1024**3), 12.0,
                 int(2.1 * 1024**3), 64 * 1024**2, "rhy", "firefox"),
        AppUsage("steam", [50], 2.0, int(0.5 * 1024**3), 5.0,
                 int(1.0 * 1024**3), 32 * 1024**2, "rhy", "steam"),
    ]
    table = AppTable(pal)
    table.set_apps(apps)
    root.pack_start(table, False, True, 0)
    # Footer
    footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    footer.get_style_context().add_class("footer")
    fans_rpm = sum(f.rpm for f in snap.fans) if snap.fans else None
    gpu_pw = snap.gpu.power_w if snap.gpu else None
    uptime_h = int(snap.uptime_s) // 3600
    uptime_m = (int(snap.uptime_s) % 3600) // 60
    footer_vals = [
        ("Fans", f"{fans_rpm:,} RPM" if fans_rpm else "\u2027",
         "weather-windy-symbolic"),
        ("CPU power", f"{int(round(snap.cpu_power_w))} W"
         if snap.cpu_power_w else "\u2027", "system-run-symbolic"),
        ("GPU power", f"{int(round(gpu_pw))} W" if gpu_pw else "\u2027",
         "battery-full-charged-symbolic"),
        ("Uptime", f"{uptime_h}h {uptime_m}m", "alarm-symbolic"),
    ]
    for index, (label, val, icon) in enumerate(footer_vals):
        item = FooterItem(label, icon)
        if index:
            item.get_style_context().add_class("footer-sep")
        item.set_value(val)
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


def _capture(box: Gtk.Widget, path: str, pal) -> bool:
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
    """Build every page with mock data and capture its screenshots."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = _mock_snapshot()
    apps = _mock_apps()
    wanted = [("overview", "dark"), ("overview", "light"),
              ("processes", "dark"), ("hardware", "dark"),
              ("hardware", "light")]
    paths = []
    for page_name, theme_name in wanted:
        pal = theme_mod.palette(theme_name)
        if page_name == "processes":
            box = ProcessesPage(pal)
            box.set_apps(apps)
            box.toggle_expand(apps[0])
            box.toggle_expand(apps[1])
        elif page_name == "hardware":
            box = HardwarePage(pal)
            box.update(snap)
        else:
            box = _build_overview(pal, snap)
        path = str(SCREENSHOT_DIR / f"{page_name}-{theme_name}.png")
        ok = _capture(box, path, pal)
        if not ok:
            print(f"FAIL: {path} missing or too small", file=sys.stderr)
            return []
        paths.append(path)
    return paths


def _tab_switch_check() -> None:
    """Drive the real MonitorWindow through every tab."""
    from spaced_monitor.app import MonitorWindow
    snap = _mock_snapshot()
    apps = _mock_apps()
    win = MonitorWindow(sampler=lambda: snap, refresh_ms=1000,
                        proc_sampler=lambda: apps)
    win.show_all()
    win.show_tab_only()
    for tab in ("overview", "processes", "hardware", "overview"):
        win._on_tab(None, tab)
        assert win._tab == tab, win._tab
        shown = [name for name, page in win._pages.items() if page.get_visible()]
        assert shown == [tab], shown
        selected = [name for name, btn in win._tab_btns.items()
                    if btn.get_style_context().has_class("tab-selected")]
        assert selected == [tab], selected
    win._apply_snapshot(snap)
    win._apply_apps(apps)
    win._on_tab(None, "overview")
    win._focus_card(win._temp_card)
    assert win._focused_card is win._temp_card
    assert win._temp_card.get_visible()
    assert not win._paned_outer.get_child1().get_visible()
    assert not win._paned_mid_h.get_child2().get_visible()
    win._restore_focused_card()
    assert win._focused_card is None
    assert win._paned_outer.get_child1().get_visible()
    assert win._paned_mid_h.get_child2().get_visible()
    win._on_tab(None, "hardware")
    win._apply_snapshot(snap)
    win.close()
    print("OK: MonitorWindow switches tabs, focuses cards and updates all pages")


def main() -> int:
    """Run the smoke test."""
    paths = run_screenshots()
    if not paths:
        return 1
    for p in paths:
        print(f"OK: {p} ({os.path.getsize(p)} bytes)")
    _tab_switch_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
