# SPDX-License-Identifier: GPL-3.0-or-later
"""Live UI test: drive the real MonitorWindow with real samplers under Xvfb.

Tests layout correctness at four window sizes: 620x420, 1000x700, 1400x900,
1920x1040.  Asserts gauge cards are never clipped, process-list columns are
always visible, no horizontal scrollbar, and GPU memory shows real data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GLib, Gdk

from spaced_monitor import theme as theme_mod
from spaced_monitor.app import MonitorWindow
from spaced_monitor import collect

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "build" / "screenshots"

SIZES = [(620, 420), (1000, 700), (1400, 900), (1920, 1040)]


def _pump(seconds: float) -> None:
    """Run the GTK event loop for the given number of seconds."""
    def _quit():
        Gtk.main_quit()
        return False
    GLib.timeout_add_seconds(int(seconds), _quit)
    Gtk.main()


def _capture_window(win: Gtk.Window, path: str) -> bool:
    """Capture the window surface to a PNG file."""
    gdk_win = win.get_window()
    if gdk_win is None:
        return False
    w = win.get_allocated_width()
    h = win.get_allocated_height()
    if w < 1 or h < 1:
        return False
    pixbuf = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h)
    if pixbuf is None:
        return False
    result = pixbuf.save_to_bufferv("png", [])
    if not result[0]:
        return False
    with open(path, "wb") as f:
        f.write(result[1])
    return os.path.exists(path) and os.path.getsize(path) > 1024


def _inside(alloc, container_alloc) -> bool:
    """True if alloc is fully inside container_alloc."""
    return (alloc.x >= container_alloc.x and
            alloc.y >= container_alloc.y and
            alloc.x + alloc.width <= container_alloc.x + container_alloc.width and
            alloc.y + alloc.height <= container_alloc.y + container_alloc.height)


def _find_scrolled_window(widget: Gtk.Widget) -> Gtk.ScrolledWindow | None:
    """Find the first ScrolledWindow in a widget tree."""
    if isinstance(widget, Gtk.ScrolledWindow):
        return widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            found = _find_scrolled_window(child)
            if found:
                return found
    return None


def _has_horizontal_scrollbar(sw: Gtk.ScrolledWindow) -> bool:
    """Check if the ScrolledWindow shows a horizontal scrollbar."""
    sb = sw.get_child()  # In GTK3 the child is a Gtk.Grid or viewport
    # The scrollbar is a sibling of the content in the internal structure.
    # Check the policy: if horizontal is NEVER, no h-scrollbar can appear.
    hpol = sw.get_policy()[0]
    if hpol == Gtk.PolicyType.NEVER:
        return False
    # If policy allows it, check if a scrollbar child is visible.
    for child in sw.get_children():
        if isinstance(child, Gtk.Scrollbar) and child.is_visible():
            orient = child.get_orientation()
            if orient == Gtk.Orientation.HORIZONTAL:
                return True
    return False


def _find_col_headers(app_table: Gtk.Box) -> dict:
    """Find column header buttons in the app table grid."""
    headers = {}
    sw = _find_scrolled_window(app_table)
    if sw is None:
        return headers
    grid = sw.get_child()
    # GTK3 may wrap in a viewport
    if not isinstance(grid, Gtk.Grid):
        children = grid.get_children() if hasattr(grid, "get_children") else []
        if children:
            grid = children[0]
    if not isinstance(grid, Gtk.Grid):
        return headers
    for child in grid.get_children():
        if isinstance(child, Gtk.Button):
            ctx = child.get_style_context()
            if "col-header" in ctx.list_classes():
                headers[child.get_label().split()[0]] = child
    return headers


def main() -> int:
    """Build the real window, test layout at four sizes."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    sampler_obj = collect.Sampler()
    pal = theme_mod.palette("dark")
    theme_mod.apply_css(pal)

    win = MonitorWindow(sampler=sampler_obj.sample, refresh_ms=1000, pal=pal)
    win.show_all()
    win.show_tab_only()
    win.start_worker()

    # Pump 3 seconds so at least 3 snapshots arrive.
    _pump(3.0)

    errors = []

    for w, h in SIZES:
        win._on_tab(None, "overview")
        win.resize(w, h)
        _pump(1.0)

        path = str(SCREENSHOT_DIR / f"live-overview-{w}x{h}.png")
        if not _capture_window(win, path):
            errors.append(f"FAIL: live-overview-{w}x{h}.png not captured")
        else:
            print(f"OK: {path} ({os.path.getsize(path)} bytes)")

        win_alloc = win.get_allocation()

        # (a) Each of the 4 gauge cards has allocation fully inside window
        #     with width > 60 and height > 60.
        cards = (win._cpu_card, win._gpu_card, win._mem_card, win._gmem_card)
        for card in cards:
            ca = card.get_allocation()
            if ca.width <= 60:
                errors.append(
                    f"FAIL: {w}x{h} card width {ca.width} <= 60")
            if ca.height <= 60:
                errors.append(
                    f"FAIL: {w}x{h} card height {ca.height} <= 60")
            if not _inside(ca, win_alloc):
                errors.append(
                    f"FAIL: {w}x{h} card not inside window "
                    f"({ca.x},{ca.y} {ca.width}x{ca.height} "
                    f"vs {win_alloc.width}x{win_alloc.height})")

        # (b) Each card's title label is allocated (height > 0) and fully
        #     inside its card.
        title_labels = [
            win._cpu_card._title_lbl,
            win._gpu_card._title_lbl,
            win._mem_card._title_lbl,
            win._gmem_card._title_lbl,
        ]
        for card, lbl in zip(cards, title_labels):
            la = lbl.get_allocation()
            if la.height < 1:
                errors.append(
                    f"FAIL: {w}x{h} title label height {la.height} < 1")
            if not _inside(la, card.get_allocation()):
                errors.append(
                    f"FAIL: {w}x{h} title label not inside card")

        # (c) CPU, RAM, GPU, Disk header labels of the process list are
        #     all allocated and fully inside the window.
        headers = _find_col_headers(win._app_table)
        for col_name in ("CPU", "RAM", "GPU", "Disk"):
            btn = headers.get(col_name)
            if btn is None:
                errors.append(
                    f"FAIL: {w}x{h} col header '{col_name}' not found")
                continue
            ba = btn.get_allocation()
            if ba.height < 1:
                errors.append(
                    f"FAIL: {w}x{h} col header '{col_name}' height {ba.height} < 1")
            if not _inside(ba, win_alloc):
                errors.append(
                    f"FAIL: {w}x{h} col header '{col_name}' not inside window")

        # (d) The list's horizontal scrollbar is not visible.
        sw = _find_scrolled_window(win._app_table)
        if sw is not None:
            if _has_horizontal_scrollbar(sw):
                errors.append(
                    f"FAIL: {w}x{h} horizontal scrollbar visible in process list")

        # (e) GPU memory card shows used/total text, not em-dash.
        gpu = sampler_obj.sample().gpu if hasattr(sampler_obj, 'sample') else None
        # Check the card's big_lbl text (shows pair_gb or em-dash)
        gmem_text = win._gmem_card._big_lbl.get_text()
        has_nv = False
        try:
            from spaced_monitor import nvml
            has_nv = nvml.available()
        except Exception:
            pass
        if not has_nv:
            import shutil
            has_nv = shutil.which("nvidia-smi") is not None
        if has_nv and gmem_text in ("\u2013", "", "\u2014"):
            errors.append(
                f"FAIL: {w}x{h} GPU memory card shows '{gmem_text}' "
                f"but NVIDIA GPU is present")
        elif has_nv:
            print(f"OK: {w}x{h} GPU memory text: '{gmem_text}'")

    # Stop the worker.
    win._stop_event.set()
    win.close()

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
