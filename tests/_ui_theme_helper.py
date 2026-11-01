# SPDX-License-Identifier: GPL-3.0-or-later
"""Helper for ui_themes: create a MonitorWindow with fake data, capture screenshot.

Usage: python3 tests/_ui_theme_helper.py <output_png_path>
Run under: env GTK_THEME=Spaced-X xvfb-run -a python3 tests/_ui_theme_helper.py out.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GLib, Gdk

from PIL import Image

from spaced_monitor import theme as theme_mod
from spaced_monitor.app import MonitorWindow


def _fake_snapshot():
    """Return a minimal fake Snapshot for rendering."""
    from datetime import datetime
    from spaced_monitor.collect import (
        Snapshot, CpuInfo, MemInfo, DiskInfo, NetInfo, GpuInfo)
    return Snapshot(
        cpu=CpuInfo(model="Test CPU", percent=45.0, per_core=[45.0, 50.0],
                    freq_mhz=3600.0, temp_c=65.0),
        memory=MemInfo(total=16*1024**3, apps=4*1024**3, cache=2*1024**3,
                       available=8*1024**3, swap_used=0, swap_total=2*1024**3),
        gpu=GpuInfo(name="Test GPU", percent=30.0, temp_c=55.0,
                    power_w=8.0, mem_used=2*1024**3, mem_total=8*1024**3),
        disk=DiskInfo(read_bps=120*1024**2, write_bps=80*1024**2,
                      used=50*1024**3, total=200*1024**3),
        net=NetInfo(rx_bps=50*1024**2, tx_bps=20*1024**2),
        fans=[],
        cpu_power_w=12.5,
        uptime_s=3600.0,
        time=datetime.now(),
        temperatures=[],
        filesystems=[],
        interfaces=[],
        gpu_extra=None,
    )


def _sample_line(win, png_path: str) -> None:
    """Print palette-derived pixel samples as JSON for ui_themes to assert on.

    The samples are taken from real widget geometry (a meter track, a table
    row band, the table background) so the test checks what is actually drawn
    rather than guessing at coordinates.
    """
    ctx = win.get_style_context()

    def _named(name: str) -> list[int] | None:
        found, value = ctx.lookup_color(name)
        if not found:
            return None
        return [round(c * 255) for c in (value.red, value.green, value.blue)]

    out: dict[str, object] = {"theme_bg": _named("theme_bg_color"),
                              "theme_base": _named("theme_base_color")}
    img = Image.open(png_path).convert("RGB")
    img_w, img_h = img.size
    view = win._app_table._scrolled.get_allocation()

    def _px(widget, dx: int, dy: int) -> list[int] | None:
        """Pixel of the screenshot at a point inside widget's allocation.

        The app list scrolls, so widgets below the visible rows still report
        an allocation outside the captured window; those are skipped rather
        than read out of range.
        """
        a = widget.get_allocation()
        x, y = a.x + dx, a.y + dy
        if a.width < 1 or a.height < 1:
            return None
        if not (a.y >= view.y and a.y + a.height <= view.y + view.height):
            return None
        if not (0 <= x < img_w and 0 <= y < img_h):
            return None
        return list(img.getpixel((x, y)))

    def _first(widgets, dx: int, dy: int) -> list[int] | None:
        for w in widgets:
            a = w.get_allocation()
            px = _px(w, a.width + dx, a.height // 2 + dy)
            if px is not None:
                return px
        return None

    table = win._app_table
    if table._meters:
        out["meter_track"] = _first([m[0] for m in table._meters], -3, 0)
    names = [c for c in table._grid.get_children()
             if isinstance(c, Gtk.Label) and c.get_hexpand()]
    if names:
        out["row_band"] = _first(names, -3, 0)
    box = table.get_allocation()
    if 0 <= box.x + 3 < img_w and 0 <= box.y + 3 < img_h:
        out["table_bg"] = list(img.getpixel((box.x + 3, box.y + 3)))
    print("SAMPLE " + json.dumps(out))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: _ui_theme_helper.py <output_png>", file=sys.stderr)
        return 1
    out_path = sys.argv[1]

    snap = _fake_snapshot()
    pal = theme_mod.palette("dark")
    theme_mod.apply_css(pal)

    win = MonitorWindow(
        sampler=lambda: snap,
        refresh_ms=500,
        pal=pal,
    )
    win.show_all()
    win.show_tab_only()
    win.start_worker()

    # Rebuild palette from the real GTK theme (follow desktop).
    win._follow_desktop = True
    win._rebuild_from_gtk()

    # Pump 2 seconds for rendering.
    def _quit():
        Gtk.main_quit()
        return False
    GLib.timeout_add_seconds(2, _quit)
    Gtk.main()

    # Capture.
    gdk_win = win.get_window()
    if gdk_win is None:
        print("FAIL: no gdk window", file=sys.stderr)
        return 1
    w = win.get_allocated_width()
    h = win.get_allocated_height()
    if w < 1 or h < 1:
        print("FAIL: window not allocated", file=sys.stderr)
        return 1
    pixbuf = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h)
    if pixbuf is None:
        print("FAIL: no pixbuf", file=sys.stderr)
        return 1
    result = pixbuf.save_to_bufferv("png", [])
    if not result[0]:
        print("FAIL: save failed", file=sys.stderr)
        return 1
    Path(out_path).write_bytes(result[1])
    try:
        _sample_line(win, out_path)
    except Exception as exc:  # sampling must not fail the capture
        print(f"SAMPLE_ERROR {exc}", file=sys.stderr)
    win._stop_event.set()
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
