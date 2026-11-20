# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact persistent hardware rows and a single-device detail page."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from spaced_monitor.devices import device_rows, device_metrics
from spaced_monitor.widgets import LineGraph, Gauge
from spaced_monitor import format as fmt
from spaced_monitor.cards import GpuMemoryCard
from spaced_monitor.devices import gpu_devices
from dataclasses import replace


def label(text="", selectable=False):
    result = Gtk.Label(label=text, xalign=0)
    result.set_line_wrap(True)
    result.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    result.set_max_width_chars(60)
    result.set_selectable(selectable)
    return result


class Rows(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.labels = []

    def update(self, rows):
        while len(self.labels) < len(rows):
            cell = label(selectable=True)
            self.pack_start(cell, False, False, 0)
            self.labels.append(cell)
        for cell, (key, value) in zip(self.labels, rows):
            cell.set_text(f"{key}:  {'Unavailable' if value == '—' else value}")
            cell.show()
        for cell in self.labels[len(rows):]:
            cell.hide()


class HardwarePage(Gtk.Box):
    def __init__(self, pal, open_details=lambda key: None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.get_style_context().add_class("page")
        self._open = open_details
        self._rows = {}
        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self._body)
        self.pack_start(scroll, True, True, 0)

    def set_palette(self, pal):
        # CSS updates in place: no lost focus, expanded rows or scroll offset.
        pass

    def update(self, snap):
        devices = device_rows(snap)
        for position, (key, (title, summary, details)) in enumerate(devices.items()):
            if key not in self._rows:
                event = Gtk.EventBox()
                event._detail_key = key
                event.get_style_context().add_class("card")
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                box.set_border_width(8)
                header = Gtk.Box(spacing=8)
                heading = label()
                header.pack_start(heading, True, True, 0)
                button = Gtk.Button(label="More")
                button.set_halign(Gtk.Align.END)
                button.set_tooltip_text("Open full-window device details (or double-click the card)")
                button.connect("clicked", lambda _b, k=key: self._open(k))
                box.pack_start(header, False, False, 0)
                expander = Gtk.Expander(label="Quick details")
                content = Rows()
                expander.add(content)
                box.pack_start(expander, False, False, 0)
                box.pack_end(button, False, False, 0)
                event.add(box)
                self._body.pack_start(event, False, False, 0)
                event.show_all()
                self._rows[key] = (event, heading, content)
            event, heading, content = self._rows[key]
            self._body.reorder_child(event, position)
            heading.set_text(f"{title}\n{summary}")
            content.update(details)
            event.show()
        for key, (event, _, _) in list(self._rows.items()):
            if key not in devices:
                event.destroy()
                del self._rows[key]


class DetailPage(Gtk.Box):
    def __init__(self, pal, close, history):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.get_style_context().add_class("page")
        self._history = history
        self._pal = pal
        self._metrics = {}
        self._metric_key = None
        self.key = None
        header = Gtk.Box(spacing=12)
        self.back = Gtk.Button(label="← Back")
        self.back.connect("clicked", lambda _b: close())
        header.pack_start(self.back, False, False, 0)
        self.title = label()
        header.pack_start(self.title, True, True, 0)
        reset = Gtk.Button(label="Reset session maximum")
        reset.connect("clicked", self._reset_maximum)
        header.pack_start(reset, False, False, 0)
        self.pack_start(header, False, False, 0)
        self.maximum = label()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._body = body
        self.vram_card = GpuMemoryCard(pal)
        self.vram_card._gauge.set_size_request(230, 180)
        self.vram_card._bar.set_size_request(-1, 18)
        body.pack_start(self.vram_card, False, False, 0)
        self.gauges = Gtk.FlowBox()
        self.gauges.set_selection_mode(Gtk.SelectionMode.NONE)
        self.gauges.set_min_children_per_line(1)
        self.gauges.set_max_children_per_line(6)
        self.gauges.set_homogeneous(True)
        body.pack_start(self.gauges, False, False, 0)
        body.pack_start(self.maximum, False, False, 0)
        self.graph = LineGraph([pal.cpu_start], 0, 100, pal, seconds=120, unit="%")
        self.graph.set_size_request(-1, 160)
        body.pack_start(self.graph, False, True, 0)
        self.content = Rows()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body.pack_start(self.content, False, False, 0)
        scroll.add(body)
        self.pack_start(scroll, True, True, 0)

    def set_palette(self, pal):
        self._pal = pal
        self.vram_card.set_palette(pal)
        for gauge, _, _, _ in self._metrics.values():
            gauge._pal = pal
            gauge.queue_draw()
        self.graph._pal = pal
        self.graph.queue_draw()

    def _reset_maximum(self, _button):
        self._history.reset_maximum()
        for index, (gauge, value, scale, _) in self._metrics.items():
            self._metrics[index] = (gauge, value, scale, 0)

    def update(self, snap):
        vram = next((g for g in gpu_devices(snap) if self.key == "vram:" + g.device_id), None)
        self.vram_card.set_visible(vram is not None)
        if vram:
            self.vram_card.update(replace(snap, gpu=vram))
        metrics = device_metrics(snap, self.key)
        signature = (self.key, tuple(m[0] for m in metrics))
        if signature != self._metric_key:
            for child in self.gauges.get_children():
                child.destroy()
            self._metrics.clear()
            self._metric_key = signature
            for index, (name, _, _, _) in enumerate(metrics):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                box.get_style_context().add_class("card")
                heading = label(name)
                heading.set_max_width_chars(16)
                gauge = Gauge("cpu", self._pal)
                gauge.set_size_request(90, 70)
                value, scale = label(), label()
                for child in (heading, gauge, value, scale):
                    box.pack_start(child, False, False, 0)
                self.gauges.add(box)
                self._metrics[index] = (gauge, value, scale, 0)
            self.gauges.show_all()
        for index, (_, reading, unit, limit) in enumerate(metrics):
            gauge, value, scale, peak = self._metrics[index]
            peak = max(peak, reading or 0)
            full = limit if limit is not None else max(1, peak)
            gauge.set_percent(reading / full * 100 if reading is not None and full > 0 else None)
            if unit == "°C":
                reading, full = fmt.temperature_value(reading), fmt.temperature_value(full)
                unit = fmt.temperature_unit()
            gauge.display = (f"{reading:.1f}", unit) if reading is not None else ("—", "")
            value.set_text(f"{reading:.1f} {unit}" if reading is not None else "Unavailable")
            scale.set_text(f"{'Scale' if limit is not None else 'View peak scale'}: {full:.1f} {unit}")
            scale.set_max_width_chars(16)
            self._metrics[index] = (gauge, value, scale, peak)
        # The expanded VRAM card already visualizes these values. Bring the
        # per-process allocations up directly beneath it instead of repeating
        # the same readings in a second row of gauges.
        self.gauges.set_visible(not self.key.startswith("vram:"))
        self._body.reorder_child(self.content, 1 if self.key.startswith("vram:") else -1)
        device = device_rows(snap).get(self.key)
        if device is None:
            self.title.set_text("Device disconnected / unavailable")
            self.content.update([("Device identity", self.key or "Unavailable")])
        else:
            title, _, rows = device
            self.title.set_text(title)
            self.content.update(rows)
        values = list(self._history.values.get(self.key, []))
        unit = "MiB/s" if self.key in ("network", "storage") else "°C" if self.key == "sensors" else "%"
        maximum = self._history.maximum.get(self.key)
        if unit == "MiB/s":
            values = [v / 1024**2 if v is not None else None for v in values]
            maximum = maximum / 1024**2 if maximum is not None else None
        elif unit == "°C":
            values = [fmt.temperature_value(v) for v in values]
            maximum = fmt.temperature_value(maximum)
            unit = fmt.temperature_unit()
        self.maximum.set_text(f"Recent history ({unit}) · Session maximum: " +
                              (f"{maximum:.1f} {unit}" if maximum is not None else "Unavailable"))
        self.graph._unit = unit
        self.graph._y_min = 0
        self.graph._y_max = max(1, max((v for v in values if v is not None), default=100)) if unit != "%" else 100
        self.graph._series = [[self.graph._pal.cpu_start, values]]
        self.graph.queue_draw()
