# SPDX-License-Identifier: GPL-3.0-or-later
"""Collectors for CPU, memory, temperatures, fans and uptime."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class CpuInfo:
    """CPU model, usage percent, per-core, frequency and temperature."""
    model: str
    percent: float
    per_core: list[float]
    freq_mhz: float
    temp_c: Optional[float]


@dataclass
class MemInfo:
    """Memory stats in bytes."""
    total: int
    apps: int
    cache: int
    available: int
    swap_used: int
    swap_total: int


@dataclass
class Fan:
    """A single fan with label and rpm."""
    label: str
    rpm: int


def cpu_model(read: Callable[[str], str] = None) -> str:
    """Extract cleaned CPU model from /proc/cpuinfo."""
    if read is None:
        read = _default_read
    text = read("/proc/cpuinfo")
    for line in text.splitlines():
        if line.startswith("model name"):
            raw = line.split(":", 1)[1].strip()
            return _clean_model(raw)
    return "Unknown"


def _clean_model(raw: str) -> str:
    """Strip vendor prefixes, trademarks and suffixes from a CPU model string."""
    s = raw
    s = re.sub(r"^AMD\s+", "", s)
    s = re.sub(r"^Intel\(R\)\s+", "", s)
    s = re.sub(r"^Intel\s+", "", s)
    s = re.sub(r"\s*\(R\)", "", s)
    s = re.sub(r"\s*\(TM\)", "", s)
    s = re.sub(r"\s*\d+-Core Processor", "", s)
    s = re.sub(r"\s*Processor", "", s)
    s = re.sub(r"\s*Core\(TM\)\s*", " ", s)
    s = re.sub(r"\s*Core\s*", " ", s)
    s = re.sub(r"\s*@\s*[\d.]+\s*GHz", "", s)
    s = re.sub(r"\s*CPU\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _default_read(path: str) -> str:
    with open(path) as f:
        return f.read()


def cpu_temp(ps) -> Optional[float]:
    """Return CPU temperature from psutil.sensors_temperatures()."""
    try:
        sensors = ps.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    if not sensors:
        return None
    # k10temp: prefer Tctl, then Tdie
    k10 = sensors.get("k10temp")
    if k10:
        for r in k10:
            if r.label == "Tctl":
                return r.current
        for r in k10:
            if r.label == "Tdie":
                return r.current
    # coretemp: "Package id 0"
    core = sensors.get("coretemp")
    if core:
        for r in core:
            if r.label == "Package id 0":
                return r.current
    # zenpower
    zen = sensors.get("zenpower")
    if zen:
        return zen[0].current
    # fallback: first sensor's first reading
    first = next(iter(sensors.values()), None)
    if first:
        return first[0].current
    return None


def fans(ps) -> list[Fan]:
    """Return list of Fan with rpm > 0 from psutil.sensors_fans()."""
    try:
        raw = ps.sensors_fans()
    except (AttributeError, OSError):
        return []
    result: list[Fan] = []
    for name, readings in raw.items():
        for r in readings:
            if r.current > 0:
                result.append(Fan(label=f"{name} {r.label}".strip(), rpm=int(r.current)))
    return result


def memory(ps) -> MemInfo:
    """Return MemInfo from psutil.virtual_memory() and psutil.swap_memory()."""
    vm = ps.virtual_memory()
    sw = ps.swap_memory()
    return MemInfo(
        total=vm.total,
        apps=vm.total - vm.available,
        cache=vm.buffers + vm.cached,
        available=vm.available,
        swap_used=sw.used,
        swap_total=sw.total,
    )


def uptime_seconds(ps, now: Callable[[], float] = time.time) -> float:
    """Return system uptime in seconds."""
    return now() - ps.boot_time()


class CpuSampler:
    """Stateful CPU sampler that uses psutil's internal delta tracking."""

    def __init__(self, ps, read: Callable[[str], str] = None) -> None:
        self._ps = ps
        self._model = cpu_model(read)

    def sample(self) -> CpuInfo:
        """Take one CPU sample (non-blocking, uses psutil deltas)."""
        percent = self._ps.cpu_percent(interval=None)
        per_core = self._ps.cpu_percent(interval=None, percpu=True)
        freq_obj = self._ps.cpu_freq()
        freq_mhz = freq_obj.current if freq_obj else 0.0
        temp = cpu_temp(self._ps)
        return CpuInfo(
            model=self._model,
            percent=percent,
            per_core=per_core,
            freq_mhz=freq_mhz,
            temp_c=temp,
        )


def main() -> None:
    """Print one human-readable line per collected item."""
    import psutil

    sampler = CpuSampler(psutil)
    # Prime the delta counters.
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(0.5)
    ci = sampler.sample()
    print(f"CPU: {ci.model}  {ci.percent}%  freq {ci.freq_mhz:.0f} MHz  temp {ci.temp_c}")
    print(f"Cores: {ci.per_core}")
    mi = memory(psutil)
    gib = 1024 ** 3
    print(f"Mem: total {mi.total // gib}G  apps {mi.apps // gib}G  "
          f"cache {mi.cache // gib}G  avail {mi.available // gib}G  "
          f"swap {mi.swap_used // gib}G/{mi.swap_total // gib}G")
    fl = fans(psutil)
    if fl:
        print(f"Fans: {', '.join(f'{f.label} {f.rpm}RPM' for f in fl)}")
    else:
        print("Fans: none detected")
    up = uptime_seconds(psutil)
    days, rem = divmod(int(up), 86400)
    hours, rem2 = divmod(rem, 3600)
    mins, _ = divmod(rem2, 60)
    print(f"Uptime: {days}d {hours}h {mins}m")


if __name__ == "__main__":
    main()
