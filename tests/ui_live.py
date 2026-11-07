# SPDX-License-Identifier: GPL-3.0-or-later
"""Live UI test: drive the real MonitorWindow with real samplers under Xvfb.

Tests layout correctness at four window sizes: 620x420, 1000x700, 1400x900,
1920x1040.  Asserts gauge cards are never clipped, no detail label in a card
is ever ellipsized (a card that cannot fit a label hides or wraps it instead),
no label on any tab is cut off, process-list columns are always visible, no
horizontal scrollbar, and GPU memory shows real data.
"""

from __future__ import annotations

import os
import sys
import ctypes
from ctypes.util import find_library
from pathlib import Path
from unittest.mock import patch

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
    GLib.timeout_add(max(1, int(seconds * 1000)), _quit)
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


def _inside_widget(widget: Gtk.Widget, ancestor: Gtk.Widget) -> bool:
    """Compare real coordinates, not allocations relative to different parents."""
    xy = widget.translate_coordinates(ancestor, 0, 0)
    if xy is None:
        return False
    x, y = xy
    return (x >= 0 and y >= 0 and
            x + widget.get_allocated_width() <= ancestor.get_allocated_width() and
            y + widget.get_allocated_height() <= ancestor.get_allocated_height())


def _drag_horizontal_handle(paned: Gtk.Paned, fraction: float) -> None:
    """Exercise a real X11 pointer drag, not the save callback in isolation."""
    x11 = ctypes.CDLL(find_library("X11"))
    xtst = ctypes.CDLL(find_library("Xtst"))
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("The live UI drag regression requires an X11 display")
    handle = paned.get_handle_window()
    _, x, y = handle.get_origin()
    x += max(1, handle.get_width() // 2)
    y += max(1, handle.get_height() // 2)
    delta = int(paned.get_allocated_width() * fraction) - paned.get_position()
    try:
        xtst.XTestFakeMotionEvent(display, -1, x, y, 0)
        xtst.XTestFakeButtonEvent(display, 1, True, 0)
        x11.XFlush(display)
        _pump(.05)
        xtst.XTestFakeMotionEvent(display, -1, x + delta, y, 0)
        x11.XFlush(display)
        _pump(.05)
        xtst.XTestFakeButtonEvent(display, 1, False, 0)
        x11.XFlush(display)
        _pump(.05)
    finally:
        xtst.XTestFakeButtonEvent(display, 1, False, 0)
        x11.XCloseDisplay(display)


def _check_overview_reachable(win: MonitorWindow, size: str, errors: list) -> None:
    """Every card stays intact and its controls can be scrolled into view."""
    scroll = win._overview
    viewport = scroll.get_child()
    content = win._paned_outer
    adjustment = scroll.get_vadjustment()
    cards = (win._cpu_card, win._gpu_card, win._mem_card, win._gmem_card,
             win._temp_card, win._disk_card, win._net_card)
    targets = []
    for card in cards:
        minimum = card.get_preferred_height_for_width(card.get_allocated_width())[0]
        if card.get_allocated_height() < minimum:
            errors.append(f"FAIL: {size} {type(card).__name__} height "
                          f"{card.get_allocated_height()} < minimum {minimum}")
        for lbl in _walk_labels(card):
            if not _inside_widget(lbl, card):
                errors.append(f"FAIL: {size} {type(card).__name__} clips "
                              f"label {lbl.get_text()!r}")
            if lbl.get_allocated_height() < lbl.get_preferred_height_for_width(
                    lbl.get_allocated_width())[0]:
                errors.append(f"FAIL: {size} label height clips {lbl.get_text()!r}")
            targets.append(lbl)
    targets.extend((win._temp_card._graph, win._disk_card._spark,
                    win._net_card._spark, win._app_table._search,
                    *win._app_table._header_btns.values()))
    win._app_table._scrolled.get_vadjustment().set_value(0)
    if win._app_table._rows:
        targets.extend(win._app_table._rows[0]["widgets"])
    for target in targets:
        if not target.get_visible():
            continue
        xy = target.translate_coordinates(content, 0, 0)
        if xy is None:
            errors.append(f"FAIL: {size} unreachable {type(target).__name__}")
            continue
        adjustment.set_value(max(0, min(xy[1], adjustment.get_upper()
                                       - adjustment.get_page_size())))
        _pump(0.02)
        # Check every clipping ancestor, including the table's inner scroll
        # area: a nonzero allocation alone never proved anything was visible.
        ancestor = target.get_parent()
        while ancestor is not None:
            if not _inside_widget(target, ancestor):
                errors.append(f"FAIL: {size} {type(target).__name__} remains "
                              f"clipped by {type(ancestor).__name__} after scroll")
                break
            if ancestor is viewport:
                break
            ancestor = ancestor.get_parent()
    if size == "620x420":
        if adjustment.get_upper() <= adjustment.get_page_size():
            errors.append("FAIL: 620x420 overview has no vertical scroll range")
        _capture_window(win, str(SCREENSHOT_DIR / "live-overview-620x420-bottom.png"))
    if _has_horizontal_scrollbar(scroll):
        errors.append(f"FAIL: {size} overview scrolls horizontally")
    adjustment.set_value(0)
    _pump(0.05)


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


def _walk_labels(widget: Gtk.Widget):
    """Yield every visible, allocated Gtk.Label in the widget tree.

    Subtrees whose root is hidden are pruned: only the currently shown tab
    has an allocated widget tree, and an unallocated label (x < 0 or width
    < 1) is off screen rather than cut off.
    """
    if not widget.get_visible():
        return
    alloc = widget.get_allocation()
    if isinstance(widget, Gtk.Label) and alloc.width > 0 and alloc.x >= 0:
        yield widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            yield from _walk_labels(child)


def _cut_labels(win: Gtk.Window):
    """Labels on the shown page whose allocation is narrower than they need.

    A non-wrapping label needs its full text width; a wrapping one only its
    minimum (longest word), because it takes extra lines instead.
    """
    cut = []
    for lbl in _walk_labels(win):
        if not lbl.get_text():
            continue
        alloc = lbl.get_allocation().width
        need = lbl.get_preferred_width()[0 if lbl.get_line_wrap() else 1]
        if need > 0 and alloc + 1 < need:
            cut.append((alloc, need, lbl.get_text()))
    return cut


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
        _pump(2.0)

        if tuple(win.get_size()) != (w, h):
            errors.append(f"FAIL: requested {w}x{h}, actual {tuple(win.get_size())}")
        _check_overview_reachable(win, f"{w}x{h}", errors)

        path = str(SCREENSHOT_DIR / f"live-overview-{w}x{h}.png")
        if not _capture_window(win, path):
            errors.append(f"FAIL: live-overview-{w}x{h}.png not captured")
        else:
            print(f"OK: {path} ({os.path.getsize(path)} bytes)")

        win_alloc = win.get_allocation()

        # (a) Each of the 4 gauge cards has allocation fully inside content
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
            if not _inside_widget(card, win._paned_outer):
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
            if not _inside_widget(lbl, card):
                errors.append(
                    f"FAIL: {w}x{h} title label not inside card")

        # (b2) At 1000x700 and 1400x900 every top card shows all detail labels.
        if w in (1000, 1400):
            detail_labels_by_card = [
                (win._cpu_card, [win._cpu_card._model_lbl,
                                 win._cpu_card._line1, win._cpu_card._line2]),
                (win._gpu_card, [win._gpu_card._model_lbl,
                                 win._gpu_card._line1, win._gpu_card._line2]),
                (win._mem_card, [win._mem_card._big_lbl,
                                 win._mem_card._pct_lbl,
                                 win._mem_card._bar, win._mem_card._legend]),
                (win._gmem_card, [win._gmem_card._big_lbl,
                                  win._gmem_card._pct_lbl,
                                  win._gmem_card._bar,
                                  win._gmem_card._legend]),
            ]
            for card, labels in detail_labels_by_card:
                for lbl in labels:
                    if not lbl.get_visible():
                        errors.append(
                            f"FAIL: {w}x{h} {type(card).__name__} "
                            f"label not visible")
                    la = lbl.get_allocation()
                    if la.width < 1:
                        errors.append(
                            f"FAIL: {w}x{h} {type(card).__name__} "
                            f"label width {la.width} < 1")

        # (b3) At every size no visible label in a top card is wider than its card.
        all_top_labels = [
            (win._cpu_card, [win._cpu_card._title_lbl,
                             win._cpu_card._model_lbl,
                             win._cpu_card._line1, win._cpu_card._line2]),
            (win._gpu_card, [win._gpu_card._title_lbl,
                             win._gpu_card._model_lbl,
                             win._gpu_card._line1, win._gpu_card._line2]),
            (win._mem_card, [win._mem_card._title_lbl,
                             win._mem_card._big_lbl,
                             win._mem_card._pct_lbl,
                             win._mem_card._bar, win._mem_card._legend]),
            (win._gmem_card, [win._gmem_card._title_lbl,
                              win._gmem_card._big_lbl,
                              win._gmem_card._pct_lbl,
                              win._gmem_card._bar,
                              win._gmem_card._legend]),
        ]
        for card, labels in all_top_labels:
            cw = card.get_allocation().width
            for lbl in labels:
                if lbl.get_visible():
                    lw = lbl.get_allocation().width
                    if lw > cw:
                        errors.append(
                            f"FAIL: {w}x{h} {type(card).__name__} "
                            f"label width {lw} > card width {cw}")

        # (b4) At 1920x1040 nothing is hidden in top cards.
        if w == 1920:
            for card, labels in all_top_labels:
                for lbl in labels:
                    if not lbl.get_visible():
                        errors.append(
                            f"FAIL: {w}x{h} {type(card).__name__} "
                            f"label hidden at full size")

        # (b5) No visible label in a top card is cut off.  A card that
        # cannot fit a detail label is supposed to hide it, so a clipped label
        # means the responsive rules measured the label against the wrong box
        # (a label inside a card's padding is never offered the card's own
        # width).  For a non-wrapping label the natural width is the full
        # text; for a wrapping one the minimum is its longest word - below
        # those numbers GTK truncates instead of laying the text out.
        for card, labels in all_top_labels:
            for lbl in labels:
                if not isinstance(lbl, Gtk.Label) or not lbl.get_visible():
                    continue
                alloc = lbl.get_allocation().width
                idx = 0 if lbl.get_line_wrap() else 1
                need = lbl.get_preferred_width()[idx]
                if need > 0 and alloc + 1 < need:
                    errors.append(
                        f"FAIL: {w}x{h} {type(card).__name__} label cut off "
                        f"to {alloc}px, needs {need}px: "
                        f"{lbl.get_text()!r}")

        # (c) CPU, RAM, GPU, Disk header labels of the process list are
        #     all allocated (reachability through scrolling is checked above).
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

        # (f) No label on any tab is cut off.  The processes page grid
        # spans more columns than a narrow window offers: when its value
        # labels were ellipsised GTK squeezed those columns to 13px instead
        # of scrolling the table sideways, so every number read "5.…".
        for tab in ("overview", "processes", "hardware"):
            win._on_tab(None, tab)
            _pump(1.5)
            found = _cut_labels(win)
            for alloc, need, txt in found[:4]:
                errors.append(
                    f"FAIL: {w}x{h} {tab} label cut to {alloc}px, "
                    f"needs {need}px: {txt!r}")

        # (g) Table value labels must not be ellipsised.  An ellipsised
        # label reports a tiny minimum width, so Gtk.Grid squeezes its
        # column below the text instead of scrolling the table sideways;
        # at a narrow window every number then read "5.…".  The window
        # clamps its own width, so the crushing is not always observable
        # on screen - this asserts the invariant that prevents it.
        for page_name, page in (("processes", win._processes_page),
                                ("hardware", win._hardware_page)):
            for lbl in _walk_labels(page):
                classes = lbl.get_style_context().list_classes()
                if "value" not in classes and "big-value" not in classes:
                    continue
                if lbl.get_ellipsize() != 0:  # Gtk.LabelEllipsize.NONE
                    errors.append(
                        f"FAIL: {page_name} value label {lbl.get_text()!r} "
                        f"is ellipsised, so its column can be crushed")

        # (h) Card titles must wrap, never ellipsize.  An ellipsised title
        # reports a tiny minimum width, so the card can be squeezed until
        # the heading itself read "Memory …"; wrapping keeps the card's
        # minimum honest and the title readable at any window width.
        for lbl in _walk_labels(win._overview):
            if "card-title" not in lbl.get_style_context().list_classes():
                continue
            if lbl.get_ellipsize() != 0:
                errors.append(
                    f"FAIL: overview card title {lbl.get_text()!r} "
                    f"is ellipsised instead of wrapping")
            if not lbl.get_line_wrap():
                errors.append(
                    f"FAIL: overview card title {lbl.get_text()!r} "
                    f"cannot wrap, so it truncates when the card is narrow")

    # A user-adjusted divider must not disable later responsive stacking.
    win._on_tab(None, "overview")
    _pump(.1)
    with patch.object(theme_mod, "load_settings", return_value={}), \
            patch.object(theme_mod, "save_settings") as save:
        _drag_horizontal_handle(win._paned_mid_h, .6)
        # Resize immediately, before the old delayed-save deadline.
        win.resize(620, 420)
        _pump(.1)
        if not save.called or abs(win._pane_fracs["pane_mid_h"] - .6) > .01:
            errors.append("FAIL: dragging divider does not retain its fraction")
    for w, h in ((620, 420), (1400, 900)):
        win.resize(w, h)
        _pump(1)
        want = Gtk.Orientation.VERTICAL if w == 620 else Gtk.Orientation.HORIZONTAL
        if win._paned_mid_h.get_orientation() != want:
            errors.append(f"FAIL: {w}x{h} divider drag disabled responsive stacking")
        _check_overview_reachable(win, f"{w}x{h} after drag", errors)

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
