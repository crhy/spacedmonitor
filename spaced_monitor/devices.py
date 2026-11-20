# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared, GTK-independent device summaries and full detail rows."""
from collections import deque
from pathlib import Path

from spaced_monitor import format as fmt
from spaced_monitor.collect import ram_temperatures


def gpu_devices(snap):
    return snap.gpus or ([snap.gpu] if snap.gpu else [])


def sensor_name(t):
    # A hwmon path identifies a sensor, not necessarily a physical DIMM slot.
    source = t.source.split("/hwmon/")[0].rsplit("/", 1)[-1] if t.source else ""
    return f"{t.chip} · {t.label}" + (f" · {source}" if source else "")


def device_rows(snap):
    """key -> (heading, compact summary, detail (label, value) pairs)."""
    cpu, mem = snap.cpu, snap.memory
    ram = ram_temperatures(snap.temperatures)
    rows = {
        "cpu": ("CPU", f"{cpu.model} · {cpu.percent:.0f}% · {fmt.temp(cpu.temp_c)}", [
            ("Model", cpu.model), ("Usage", f"{cpu.percent:.1f}%"),
            ("Logical threads", str(len(cpu.per_core))),
            ("Physical cores", str(cpu.physical_cores) if cpu.physical_cores else "Unavailable"),
            ("Current frequency", fmt.ghz(cpu.freq_mhz) if cpu.freq_mhz else "Unavailable"),
            ("Reported frequency range", f"{fmt.ghz(cpu.min_mhz)} – {fmt.ghz(cpu.max_mhz)}"
             if cpu.min_mhz and cpu.max_mhz else "Unavailable"),
            ("Package temperature", fmt.temp(cpu.temp_c)),
            ("Package power", fmt.watts(snap.cpu_power_w)),
        ] + [(sensor_name(t), fmt.temp(t.celsius)) for t in snap.temperatures
             if t.chip in {"k10temp", "coretemp", "zenpower", "cpu_thermal", "soc_thermal"}]
          + [(f"Logical thread {i}", f"{v:.1f}%") for i, v in enumerate(cpu.per_core)]),
        "memory": ("Memory", f"{fmt.pair_gb(mem.total - mem.available, mem.total)} used · " +
                   (f"Hottest RAM sensor {fmt.temp(max(t.celsius for t in ram))}" if ram else "RAM temperature unavailable"), [
            ("Total", fmt.bytes_gb(mem.total)), ("Used", fmt.bytes_gb(mem.total - mem.available)),
            ("Applications", fmt.bytes_gb(mem.apps)),
            ("Available", fmt.bytes_gb(mem.available)), ("Reclaimable cache", fmt.bytes_gb(mem.cache)),
            ("Free", fmt.bytes_gb(max(0, mem.available - mem.cache))),
            ("Swap", fmt.pair_gb(mem.swap_used, mem.swap_total)),
            ("RAM temperatures", "Sensors below; slot names only when reported" if ram else
             "Unavailable — no memory temperature sensor exposed by the kernel"),
        ] + [(sensor_name(t), fmt.temp(t.celsius)) for t in ram]),
        "storage": ("Storage", f"Read {fmt.rate(snap.disk.read_bps)} · Write {fmt.rate(snap.disk.write_bps)}", [
            ("Aggregate read", fmt.rate(snap.disk.read_bps)), ("Aggregate write", fmt.rate(snap.disk.write_bps)),
            ("Root usage", fmt.pair_gb(snap.disk.used, snap.disk.total)),
        ] + [(f"{f.mount} ({f.fstype})", fmt.pair_gb(f.used, f.total)) for f in snap.filesystems]),
        "network": ("Network", f"Down {fmt.rate(snap.net.rx_bps)} · Up {fmt.rate(snap.net.tx_bps)}", [
            ("Aggregate receive", fmt.rate(snap.net.rx_bps)), ("Aggregate send", fmt.rate(snap.net.tx_bps)),
        ] + [(i.name, f"{i.address or 'Address unavailable'} · ↓ {fmt.rate(i.rx_bps)} · ↑ {fmt.rate(i.tx_bps)}")
             for i in snap.interfaces]),
        "sensors": ("Temperatures and fans", f"{len(snap.temperatures)} hwmon readings · {len(snap.fans)} fans", [
            ("CPU package", fmt.temp(cpu.temp_c)),
        ] + [(g.name or "GPU", fmt.temp(g.temp_c)) for g in gpu_devices(snap)] + [
            (sensor_name(t), fmt.temp(t.celsius)) for t in snap.temperatures
        ] + [(f.label, fmt.rpm(f.rpm)) for f in snap.fans]),
    }
    gpu_rows = {}
    for g in gpu_devices(snap):
        process_rows = []
        for pid, used in sorted((g.memory_processes or {}).items(), key=lambda p: p[1], reverse=True):
            try:
                name = Path(f"/proc/{pid}/comm").read_text().strip()
            except OSError:
                name = "Exited or inaccessible process"
            process_rows.append((f"{name} · PID {pid}", f"{used / 1024**2:,.1f} MiB"))
        gpu_rows["vram:" + g.device_id] = ("GPU memory · " + (g.name or "GPU"),
            fmt.pair_gb(g.mem_used, g.mem_total), [
                ("Device identity", g.device_id), ("Used / total", fmt.pair_gb(g.mem_used, g.mem_total)),
                ("Process allocations", "Unavailable from this driver" if g.memory_processes is None else
                 "Reported compute and graphics allocations; totals can exclude driver allocations and shared memory")
            ] + (process_rows or ([("Processes", "No process allocations reported")] if g.memory_processes is not None else [])))
        gpu_rows["gpu:" + g.device_id] = (g.name or "GPU", f"{fmt.percent(g.percent)} · {fmt.temp(g.temp_c)} · {fmt.pair_gb(g.mem_used, g.mem_total)}", [
            ("Model", g.name or "Unavailable"), ("Device identity", g.device_id),
            ("Driver", g.driver or "Unavailable"), ("PCIe link", g.pci_link or "Unavailable"),
            ("Usage", fmt.percent(g.percent)), ("Temperature", fmt.temp(g.temp_c)),
            ("Board power", fmt.watts(g.power_w)),
            ("VRAM used / total", fmt.pair_gb(g.mem_used, g.mem_total)),
            ("VRAM available", fmt.bytes_gb(g.mem_total - g.mem_used)
             if g.mem_total is not None and g.mem_used is not None else "Unavailable"),
        ])
    return {"cpu": rows.pop("cpu"), "memory": rows.pop("memory"), **gpu_rows, **rows}


def device_metrics(snap, key):
    """Numeric gauges: (name, value, unit, fixed full scale or None).

    None scales use a clearly labelled session peak, never a health limit.
    Missing readings remain missing rather than becoming zero.
    """
    cpu, mem = snap.cpu, snap.memory
    thermal = lambda t: (sensor_name(t), t.celsius, "°C", 120)
    if key == "cpu":
        return [("Usage", cpu.percent, "%", 100),
                ("Frequency", cpu.freq_mhz or None, "MHz", cpu.max_mhz or None),
                ("Package temperature", cpu.temp_c, "°C", 120),
                ("Package power", snap.cpu_power_w, "W", None)] + [
                    thermal(t) for t in snap.temperatures
                    if t.chip in {"k10temp", "coretemp", "zenpower", "cpu_thermal", "soc_thermal"}
                ] + [(f"Thread {i}", v, "%", 100) for i, v in enumerate(cpu.per_core)]
    if key == "memory":
        gib = 1024**3
        return [(name, value / gib, "GiB", mem.total / gib) for name, value in (
            ("Used", mem.total - mem.available), ("Applications", mem.apps),
            ("Available", mem.available), ("Cache", mem.cache),
            ("Free", max(0, mem.available - mem.cache)))] + [
                ("Swap", mem.swap_used / gib, "GiB", mem.swap_total / gib)
            ] + [thermal(t) for t in ram_temperatures(snap.temperatures)]
    for g in gpu_devices(snap):
        if key == "vram:" + g.device_id:
            total = g.mem_total / 1024**3 if g.mem_total else None
            return [("Used", g.mem_used / 1024**3 if g.mem_used is not None else None, "GiB", total),
                    ("Available", max(0, g.mem_total - g.mem_used) / 1024**3
                     if g.mem_total is not None and g.mem_used is not None else None, "GiB", total)]
        if key == "gpu:" + g.device_id:
            return [("Usage", g.percent, "%", 100), ("Temperature", g.temp_c, "°C", 120),
                    ("Board power", g.power_w, "W", None),
                    ("VRAM used", g.mem_used / 1024**3 if g.mem_used is not None else None,
                     "GiB", g.mem_total / 1024**3 if g.mem_total else None)]
    if key == "storage":
        return [("Read", snap.disk.read_bps / 1024**2, "MiB/s", None),
                ("Write", snap.disk.write_bps / 1024**2, "MiB/s", None),
                ("Root used", snap.disk.used / 1024**3, "GiB", snap.disk.total / 1024**3)] + [
                    (f.mount, f.used / 1024**3, "GiB", f.total / 1024**3) for f in snap.filesystems]
    if key == "network":
        return [("Receive", snap.net.rx_bps / 1024**2, "MiB/s", None),
                ("Send", snap.net.tx_bps / 1024**2, "MiB/s", None)] + [
                    (f"{i.name} {direction}", value / 1024**2, "MiB/s", None)
                    for i in snap.interfaces for direction, value in (("↓", i.rx_bps), ("↑", i.tx_bps))]
    if key == "sensors":
        return [("CPU package", cpu.temp_c, "°C", 120)] + [
            (g.name, g.temp_c, "°C", 120) for g in gpu_devices(snap)] + [
            thermal(t) for t in snap.temperatures] + [(f.label, f.rpm, "RPM", None) for f in snap.fans]
    return []


class History:
    """Bounded session history keyed by device identity, not visible widgets."""
    def __init__(self):
        self.values = {}
        self.maximum = {}

    def update(self, snap):
        values = {"cpu": snap.cpu.percent, "memory": (snap.memory.total - snap.memory.available) / max(1, snap.memory.total) * 100,
                  "storage": snap.disk.read_bps + snap.disk.write_bps,
                  "network": snap.net.rx_bps + snap.net.tx_bps,
                  "sensors": max((t.celsius for t in snap.temperatures), default=None)}
        values.update({"gpu:" + g.device_id: g.percent for g in gpu_devices(snap)})
        values.update({"vram:" + g.device_id: g.mem_used / g.mem_total * 100
                       if g.mem_used is not None and g.mem_total else None for g in gpu_devices(snap)})
        # Disconnected devices have gaps, never another device's measurements.
        for key in self.values.keys() | values.keys():
            value = values.get(key)
            self.values.setdefault(key, deque(maxlen=120)).append(value)
            if value is not None:
                self.maximum[key] = max(value, self.maximum.get(key, value))

    def reset_maximum(self):
        self.maximum.clear()
