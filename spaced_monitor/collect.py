# SPDX-License-Identifier: GPL-3.0-or-later
"""Collectors for CPU, memory, temperatures, fans and uptime."""

from __future__ import annotations

import glob
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Tuple
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


@dataclass
class GpuInfo:
    """GPU model, utilisation, temperature, power and memory (bytes)."""
    name: Optional[str]
    percent: Optional[float]
    temp_c: Optional[float]
    power_w: Optional[float]
    mem_used: Optional[int]
    mem_total: Optional[int]


@dataclass
class DiskInfo:
    """Disk read/write rates in bytes per second, plus root filesystem use."""
    read_bps: float
    write_bps: float
    used: Optional[int]
    total: Optional[int]


@dataclass
class NetInfo:
    """Network receive/send rates in bytes per second."""
    rx_bps: float
    tx_bps: float


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


def _default_run(cmd: list, timeout: float = 2.0) -> str:
    """Run a command and return its stdout (default for GPU probes)."""
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return res.stdout


def _num(raw: str) -> Optional[float]:
    """Parse a sysfs or nvidia-smi number; "[N/A]" and junk become None."""
    s = raw.strip()
    if not s or s == "[N/A]":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _read_num(path: str) -> Optional[float]:
    """Read one number from a sysfs file; missing or unreadable files give None."""
    try:
        with open(path) as f:
            return _num(f.read())
    except OSError:
        return None


def _mib_to_bytes(value: Optional[float]) -> Optional[int]:
    """Convert an nvidia-smi MiB figure to bytes."""
    if value is None:
        return None
    return int(value * 1024 * 1024)


def _gpu_name(raw: str) -> str:
    """Drop the NVIDIA vendor prefixes from a GPU name."""
    for prefix in ("NVIDIA GeForce ", "NVIDIA "):
        if raw.startswith(prefix):
            return raw[len(prefix):].strip()
    return raw.strip()


def nvidia_gpu(run: Callable = None) -> Optional[GpuInfo]:
    """Collect the GPU from nvidia-smi; None when it is missing, fails or times out."""
    if run is None:
        run = _default_run
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = run(cmd, timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_nvidia(out)


def _parse_nvidia(out: str) -> Optional[GpuInfo]:
    """Parse the first nvidia-smi csv line into GpuInfo."""
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return None
    return GpuInfo(
        name=_gpu_name(parts[0]),
        percent=_num(parts[1]),
        temp_c=_num(parts[2]),
        power_w=_num(parts[3]),
        mem_used=_mib_to_bytes(_num(parts[4])),
        mem_total=_mib_to_bytes(_num(parts[5])),
    )


def amd_gpu(root: str = "/sys/class/drm") -> Optional[GpuInfo]:
    """Collect the first AMD card that exposes gpu_busy_percent."""
    for card in sorted(glob.glob(os.path.join(root, "card*"))):
        dev = os.path.join(card, "device")
        busy = _read_num(os.path.join(dev, "gpu_busy_percent"))
        if busy is None:
            continue
        temp_c = power_w = None
        for hwmon in sorted(glob.glob(os.path.join(dev, "hwmon", "hwmon*"))):
            temp = _read_num(os.path.join(hwmon, "temp1_input"))
            if temp is not None:
                temp_c = temp / 1000.0
            power = _read_num(os.path.join(hwmon, "power1_average"))
            if power is None:
                power = _read_num(os.path.join(hwmon, "power1_input"))
            if power is not None:
                power_w = power / 1e6
        used = _read_num(os.path.join(dev, "mem_info_vram_used"))
        total = _read_num(os.path.join(dev, "mem_info_vram_total"))
        return GpuInfo(
            name=os.path.basename(card),
            percent=busy,
            temp_c=temp_c,
            power_w=power_w,
            mem_used=_as_int(used),
            mem_total=_as_int(total),
        )
    return None


def _as_int(value: Optional[float]) -> Optional[int]:
    """Round a parsed number to an int, keeping None."""
    return None if value is None else int(value)


def gpu(run: Callable = None, drm_root: str = "/sys/class/drm") -> Optional[GpuInfo]:
    """Return the GPU sample: nvidia-smi first, then the AMD sysfs path."""
    info = nvidia_gpu(run=run)
    if info:
        return info
    return amd_gpu(root=drm_root)


class RateSampler:
    """Turn psutil's cumulative disk and network counters into rates."""

    def __init__(self, ps, clock: Callable[[], float] = time.monotonic) -> None:
        self._ps = ps
        self._clock = clock
        self._prev: Optional[Tuple[float, float, float, float, float]] = None

    def sample(self) -> Tuple[DiskInfo, NetInfo]:
        """Return DiskInfo and NetInfo for the interval since the previous sample."""
        io = self._ps.disk_io_counters()
        rx, tx = self._net_totals()
        now = self._clock()
        if self._prev is None:
            self._prev = (now, io.read_bytes, io.write_bytes, rx, tx)
            rates = (0.0, 0.0, 0.0, 0.0)
        else:
            pt, pr, pw, prx, ptx = self._prev
            self._prev = (now, io.read_bytes, io.write_bytes, rx, tx)
            dt = now - pt
            rates = self._rate(pr, io.read_bytes, dt), self._rate(pw, io.write_bytes, dt)
            rates += self._rate(prx, rx, dt), self._rate(ptx, tx, dt)
        used, total = self._root_usage()
        return (
            DiskInfo(read_bps=rates[0], write_bps=rates[1], used=used, total=total),
            NetInfo(rx_bps=rates[2], tx_bps=rates[3]),
        )

    @staticmethod
    def _rate(prev: float, cur: float, dt: float) -> float:
        """Rate in bytes per second; a reset counter gives 0, never a negative."""
        if dt <= 0 or cur < prev:
            return 0.0
        return (cur - prev) / dt

    def _net_totals(self) -> Tuple[int, int]:
        """Sum net_io_counters over real interfaces only."""
        rx = tx = 0
        for name, entry in self._ps.net_io_counters(pernic=True).items():
            if name == "lo" or name.startswith(("veth", "docker", "virbr", "tap")):
                continue
            rx += entry.bytes_recv
            tx += entry.bytes_sent
        return rx, tx

    def _root_usage(self) -> Tuple[Optional[int], Optional[int]]:
        """Used and total bytes of the root filesystem."""
        try:
            usage = self._ps.disk_usage("/")
        except OSError:
            return None, None
        return usage.used, usage.total


class CpuPower:
    """CPU package power in watts from the sysfs energy counters (Intel and AMD)."""

    def __init__(self, root: str = "/sys/class/powercap", clock: Callable[[], float] = time.monotonic) -> None:
        self._pkg = os.path.join(root, "intel-rapl:0")
        self._clock = clock
        self._prev: Optional[Tuple[float, float]] = None

    def sample(self) -> Optional[float]:
        """Return watts from the energy delta, or None when the counter is unreadable."""
        energy = _read_num(os.path.join(self._pkg, "energy_uj"))
        if energy is None:
            return None
        now = self._clock()
        if self._prev is None:
            self._prev = (now, energy)
            return None
        pt, pe = self._prev
        self._prev = (now, energy)
        dt = now - pt
        if dt <= 0:
            return None
        delta = energy - pe
        if delta < 0:
            rng = _read_num(os.path.join(self._pkg, "max_energy_range_uj"))
            if rng is None:
                return None
            delta += rng
        return delta / dt / 1e6


@dataclass
class Snapshot:
    """One sample of everything the monitor shows."""
    cpu: CpuInfo
    memory: MemInfo
    gpu: Optional[GpuInfo]
    disk: DiskInfo
    net: NetInfo
    fans: list
    cpu_power_w: Optional[float]
    uptime_s: float
    time: datetime = field(default_factory=datetime.now)


class Sampler:
    """Own the sub-samplers and return one Snapshot per sample()."""

    def __init__(self, ps=None, run: Callable = None, clock: Callable[[], float] = time.monotonic,
                 power_root: str = "/sys/class/powercap", drm_root: str = "/sys/class/drm",
                 gpu_fn: Callable = None, read: Callable[[str], str] = None) -> None:
        """Wire the collectors; every probe is injectable for tests."""
        if ps is None:
            import psutil
            ps = psutil
        self._ps = ps
        self._cpu = CpuSampler(ps, read=read)
        self._rates = RateSampler(ps, clock=clock)
        self._power = CpuPower(root=power_root, clock=clock)
        self._gpu_fn = gpu_fn if gpu_fn is not None else lambda: gpu(run=run, drm_root=drm_root)

    def sample(self) -> Snapshot:
        """Take one full snapshot."""
        disk, net = self._rates.sample()
        return Snapshot(
            cpu=self._cpu.sample(),
            memory=memory(self._ps),
            gpu=self._gpu_fn(),
            disk=disk,
            net=net,
            fans=fans(self._ps),
            cpu_power_w=self._power.sample(),
            uptime_s=uptime_seconds(self._ps),
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


def _fmt_bytes(value: Optional[int]) -> str:
    """Human-readable size, or "-" when unknown."""
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


def _fmt(value: Optional[float], unit: str = "") -> str:
    """Human-readable number, or "-" when unknown."""
    return "-" if value is None else f"{value:.0f}{unit}"


def main() -> None:
    """Print one human-readable line per collected item."""
    sampler = Sampler()
    sampler.sample()
    time.sleep(1.0)
    snap = sampler.sample()
    ci = snap.cpu
    print(f"Time: {snap.time:%Y-%m-%d %H:%M}")
    print(f"CPU: {ci.model}  {ci.percent}%  freq {ci.freq_mhz:.0f} MHz  temp {ci.temp_c}  "
          f"power {_fmt(snap.cpu_power_w, 'W')}")
    print(f"Cores: {ci.per_core}")
    mi = snap.memory
    print(f"Mem: total {_fmt_bytes(mi.total)}  apps {_fmt_bytes(mi.apps)}  "
          f"cache {_fmt_bytes(mi.cache)}  avail {_fmt_bytes(mi.available)}  "
          f"swap {_fmt_bytes(mi.swap_used)}/{_fmt_bytes(mi.swap_total)}")
    g = snap.gpu
    if g:
        print(f"GPU: {g.name}  util {_fmt(g.percent, '%')}  temp {_fmt(g.temp_c, 'C')}  "
              f"power {_fmt(g.power_w, 'W')}  vram {_fmt_bytes(g.mem_used)}/{_fmt_bytes(g.mem_total)}")
    else:
        print("GPU: none detected")
    d = snap.disk
    print(f"Disk: read {_fmt(d.read_bps, 'B/s')}  write {_fmt(d.write_bps, 'B/s')}  "
          f"/ {_fmt_bytes(d.used)}/{_fmt_bytes(d.total)}")
    n = snap.net
    print(f"Net: down {_fmt(n.rx_bps, 'B/s')}  up {_fmt(n.tx_bps, 'B/s')}")
    fl = snap.fans
    if fl:
        print(f"Fans: {', '.join(f'{f.label} {f.rpm}RPM' for f in fl)}")
    else:
        print("Fans: none detected")
    days, rem = divmod(int(snap.uptime_s), 86400)
    hours, rem2 = divmod(rem, 3600)
    mins, _ = divmod(rem2, 60)
    print(f"Uptime: {days}d {hours}h {mins}m")


if __name__ == "__main__":
    main()
