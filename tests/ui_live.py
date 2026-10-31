# SPDX-License-Identifier: GPL-3.0-or-later
"""Live UI test: drive the real MonitorWindow with real samplers under Xvfb."""

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


def _pump(seconds: float) -> None:
    """Run the GTK event loop for the given number of seconds."""
    def _quit():
        Gtk.main_quit()
        return False  # don't repeat
    GLib.timeout_add_seconds(int(seconds), _quit)
    Gtk.main()


def _visible_labels(widget: Gtk.Widget) -> list:
    """Collect all visible Gtk.Label texts in a widget tree."""
    texts = []
    if isinstance(widget, Gtk.Label):
        if widget.get_visible() and widget.get_text().strip():
            texts.append(widget.get_text())
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            texts.extend(_visible_labels(child))
    return texts


def _count_visible_rows(page: Gtk.Widget) -> int:
    """Count visible rows in the ProcessesPage grid by counting end-buttons."""
    # Navigate: page -> vbox -> ScrolledWindow -> (Viewport) -> Gtk.Grid
    for child in page.get_children():
        if isinstance(child, Gtk.Box):
            for sub in child.get_children():
                if isinstance(sub, Gtk.ScrolledWindow):
                    grid = sub.get_child()
                    # GTK3 wraps in a Viewport
                    if not isinstance(grid, Gtk.Grid):
                        children = grid.get_children() if hasattr(grid, 'get_children') else []
                        if children:
                            grid = children[0]
                    if not isinstance(grid, Gtk.Grid):
                        return 0
                    # Count visible Gtk.Button widgets (one end-button per row)
                    count = 0
                    for widget in grid.get_children():
                        if isinstance(widget, Gtk.Button) and widget.get_visible():
                            count += 1
                    return count
    return 0


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


def main() -> int:
    """Build the real window, pump the loop, assert per-tab content."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    sampler_obj = collect.Sampler()
    pal = theme_mod.palette("dark")
    theme_mod.apply_css(pal)

    win = MonitorWindow(sampler=sampler_obj.sample, refresh_ms=1000, pal=pal)
    win.set_default_size(1400, 900)
    win.show_all()
    win.show_tab_only()
    win.start_worker()

    # Pump 8 seconds so at least 8 snapshots arrive.
    _pump(8.0)

    errors = []

    # --- Overview assertions ---
    win._on_tab(None, "overview")
    _pump(1.0)
    path = str(SCREENSHOT_DIR / "live-overview.png")
    if not _capture_window(win, path):
        errors.append(f"FAIL: live-overview.png not captured")
    else:
        print(f"OK: {path} ({os.path.getsize(path)} bytes)")

    # Check CPU model is visible in the CPU gauge card.
    labels = _visible_labels(win._cpu_card)
    cpu_model_found = any(
        lbl for lbl in labels
        if lbl and lbl != "\u2013" and len(lbl) > 3
    )
    if not cpu_model_found:
        errors.append("FAIL: CPU gauge card shows no CPU model text")
    else:
        print(f"OK: CPU card model: {labels[1] if len(labels) > 1 else '?'}")

    # --- Processes tab assertions ---
    win._on_tab(None, "processes")
    _pump(1.0)
    path = str(SCREENSHOT_DIR / "live-processes.png")
    if not _capture_window(win, path):
        errors.append("FAIL: live-processes.png not captured")
    else:
        print(f"OK: {path} ({os.path.getsize(path)} bytes)")

    row_count = _count_visible_rows(win._processes_page)
    if row_count < 5:
        errors.append(f"FAIL: Processes has only {row_count} visible row labels (need >= 5)")
    else:
        print(f"OK: Processes has {row_count} visible row name labels")

    # No kernel-thread names visible.
    proc_labels = _visible_labels(win._processes_page)
    kernel_names = ["Kworker", "Ksoftirqd", "kthreadd"]
    found_kernel = [n for n in kernel_names if any(n in lbl for lbl in proc_labels)]
    if found_kernel:
        errors.append(f"FAIL: kernel-thread names visible: {found_kernel}")
    else:
        print("OK: no kernel-thread names in Processes tab")

    # --- Hardware tab assertions ---
    win._on_tab(None, "hardware")
    _pump(1.0)
    path = str(SCREENSHOT_DIR / "live-hardware.png")
    if not _capture_window(win, path):
        errors.append("FAIL: live-hardware.png not captured")
    else:
        print(f"OK: {path} ({os.path.getsize(path)} bytes)")

    hw_labels = _visible_labels(win._hardware_page)

    # Sensor rows: at least one line containing "°C" with a name.
    sensor_lines = [lbl for lbl in hw_labels if "\u00b0C" in lbl]
    if len(sensor_lines) < 1:
        errors.append("FAIL: no sensor readings with \u00b0C visible")
    else:
        print(f"OK: {len(sensor_lines)} sensor \u00b0C readings visible")

    # Storage card: filesystem mount points visible.
    mount_lines = [lbl for lbl in hw_labels if lbl.startswith("/")]
    if len(mount_lines) < 1:
        errors.append("FAIL: no filesystem mount points visible in Storage card")
    else:
        print(f"OK: {len(mount_lines)} filesystem rows visible")

    # Network card: interface names visible.
    iface_names = ["eth0", "wlan0", "lo", "docker", "veth"]
    iface_found = [lbl for lbl in hw_labels if any(n in lbl for n in iface_names)]
    if len(iface_found) < 1:
        errors.append("FAIL: no network interfaces visible in Network card")
    else:
        print(f"OK: {len(iface_found)} network interface rows visible")

    # CPU card: per-core meters visible.
    core_meter_count = 0
    # Find the FlowBox (may be nested inside ScrolledWindow/Viewport).
    flow = None
    def _find_flowbox(w):
        for c in w.get_children():
            if isinstance(c, Gtk.FlowBox):
                return c
            found = _find_flowbox(c)
            if found:
                return found
        return None
    flow = _find_flowbox(win._hardware_page)
    if flow:
        for fbc in flow.get_children():
            card = fbc.get_children()[0] if hasattr(fbc, "get_children") and fbc.get_children() else None
            if card is None:
                continue
            body = card.get_children()[0]
            title = body.get_children()[0] if body.get_children() else None
            if isinstance(title, Gtk.Label) and title.get_text() == "CPU":
                for child in body.get_children():
                    if isinstance(child, Gtk.Grid):
                        core_meter_count = sum(1 for m in child.get_children() if m.get_visible())
    if core_meter_count < 2:
        errors.append(f"FAIL: CPU card shows {core_meter_count} core meters (need >= 2)")
    else:
        print(f"OK: CPU card shows {core_meter_count} per-core meters")

    # Window width must not exceed the default size.
    width = win.get_allocated_width()
    if width > 1400:
        errors.append(f"FAIL: window width {width} > 1400")
    else:
        print(f"OK: window width {width} <= 1400")

    # --- Window height assertion ---
    height = win.get_allocated_height()
    if height > 900:
        errors.append(f"FAIL: window height {height} > 900")
    else:
        print(f"OK: window height {height} <= 900")

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
