"""Live compact overview and visual detail regression checks (private Xvfb)."""
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.ui_live import _pump, _capture_window
from gi.repository import Gtk
from spaced_monitor.app import MonitorWindow
from spaced_monitor.collect import Sampler
from spaced_monitor import theme
from spaced_monitor import format as fmt, preferences


def main():
    theme.apply_css(theme.palette("dark"))
    win = MonitorWindow(Sampler().sample)
    win.show_all()
    win.show_tab_only()
    win.start_worker()
    _pump(3)
    win.resize(850, 620)
    _pump(2)
    _capture_window(win, "build/screenshots/compact-850x620.png")
    adj = win._overview.get_vadjustment()
    assert tuple(win.get_size()) == (850, 620)
    if len(win._snapshot.gpus) <= 3:
        assert adj.get_upper() <= adj.get_page_size() + 1, (adj.get_upper(), adj.get_page_size())
    cards = [child.get_child() for child in win._gauges.get_children()]
    assert cards[:4] == [win._cpu_card, win._mem_card, win._gpu_card, win._gmem_card]
    assert win._temp_card._graph._compact
    cards += [win._temp_card, win._disk_card, win._net_card, win._app_table]
    for card in cards:
        more = [child for child in card.get_children()
                if isinstance(child, Gtk.Button) and child.get_label() == "More"]
        assert len(more) == 1, type(card).__name__
        assert more[0].get_halign() == Gtk.Align.END
        x, y = more[0].translate_coordinates(card, 0, 0)
        assert abs(card.get_allocated_height() - y - more[0].get_allocated_height()) <= 10
        assert abs(card.get_allocated_width() - x - more[0].get_allocated_width()) <= 10
    print("GPU order:", [g.name for g in win._snapshot.gpus], flush=True)
    vram_keys = ["vram:" + gpu.device_id for gpu in win._snapshot.gpus]
    for key in ("cpu", "memory", "gpu:first", "storage", "network", "sensors", *vram_keys):
        win._open_details(key)
        _pump(.3)
        assert win._details._metrics, key
        assert win._details.vram_card.get_visible() == key.startswith("vram:"), key
        _capture_window(win, f"build/screenshots/compact-{key.replace(':', '-').replace('/', '_')}.png")
        win._close_details()
    win._on_tab(None, "suggest")
    _pump(.2)
    assert win._suggest_rows.labels
    _capture_window(win, "build/screenshots/compact-suggest.png")
    with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
        before = list(win._temp_card._graph._series[0][1])
        win._temperature_btn.set_active(True)
        assert fmt.CELSIUS and preferences.load_celsius()
        assert win._temp_card._graph._unit == "°C"
        assert "°C" in win._cpu_card._line1.get_text()
        assert len(win._temp_card._graph._series[0][1]) == len(before)
        win._open_details("sensors")
        assert "°C" in win._details.maximum.get_text()
        win._temperature_btn.set_active(False)
        assert not fmt.CELSIUS and not preferences.load_celsius()
        assert "°F" in win._details.maximum.get_text()
        for old, restored in zip(before, win._temp_card._graph._series[0][1]):
            if old is not None:
                assert abs(old - restored) < .00001
        win._close_details()
    win.destroy()
    _pump(.1)
    print("OK: compact overview, bottom-right More buttons and visual details")


if __name__ == "__main__":
    main()
