# SPDX-License-Identifier: GPL-3.0-or-later
"""Collectors for CPU, memory, temperatures, fans and uptime."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Tuple


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
class Temperature:
    """One temperature reading: chip, label and degrees."""
    chip: str
    label: str
    celsius: float


@dataclass
class Filesystem:
    """One mounted filesystem: mount point, type and use."""
    mount: str
    fstype: str
    used: Optional[int]
    total: Optional[int]


@dataclass
class Interface:
    """One network interface: name, address and rx/tx rates."""
    name: str
    address: Optional[str]
    rx_bps: float
    tx_bps: float


@dataclass
class GpuExtra:
    """Static GPU details: driver version and PCIe link."""
    driver: Optional[str]
    link_gen: Optional[str]
    link_width: Optional[str]


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


def temperatures(ps) -> list:
    """Return every reading from psutil.sensors_temperatures(), chip by chip."""
    try:
        raw = ps.sensors_temperatures()
    except (AttributeError, OSError):
        return []
    result: list[Temperature] = []
    for chip, readings in raw.items():
        for r in readings:
            result.append(Temperature(chip=chip,
                                      label=(r.label or chip).strip(),
                                      celsius=float(r.current)))
    return result


# Filesystems that are not real storage or are runtime plumbing.
_SKIP_FSTYPES = frozenset({
    "squashfs", "tmpfs", "overlay", "proc", "sysfs", "devtmpfs", "cgroup",
    "cgroupfs", "autofs", "autofs-fs", "fuse", "nsfs", "virtual",
})
_SKIP_MOUNTS = ("/snap", "/var/lib/snap", "/var/lib/flatpak", "/run", "/tmp")


def real_filesystem(fstype: str, mount: str) -> bool:
    """True for a real filesystem worth showing (not squashfs/tmpfs/overlay/snap)."""
    if fstype in _SKIP_FSTYPES:
        return False
    for skip in _SKIP_MOUNTS:
        if mount == skip or mount.startswith(skip + "/"):
            return False
    return True


def filesystems(ps) -> list:
    """Return Filesystem for every real mounted filesystem, biggest first."""
    try:
        parts = ps.disk_partitions(all=False)
    except (AttributeError, OSError):
        return []
    result: list[Filesystem] = []
    for part in parts:
        if not real_filesystem(part.fstype, part.mountpoint):
            continue
        try:
            usage = ps.disk_usage(part.mountpoint)
        except OSError:
            continue
        result.append(Filesystem(mount=part.mountpoint, fstype=part.fstype,
                                 used=usage.used, total=usage.total))
    result.sort(key=lambda f: f.total or 0, reverse=True)
    return result


def parse_ip_addr(out: str) -> dict:
    """Map interface name -> primary address from `ip -j addr show` JSON."""
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, list):
        return {}
    result: dict[str, str] = {}
    for entry in data:
        name = entry.get("ifname") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            continue
        blocks = entry.get("addr_info")
        if not isinstance(blocks, list):
            continue
        ipv6 = None
        for block in blocks:
            if not isinstance(block, dict):
                continue
            address = block.get("local")
            if not isinstance(address, str) or not address:
                continue
            if block.get("family") == "inet":
                result[name] = address
                break
            if block.get("family") == "inet6":
                # Prefer a global IPv6 address over a link-local fallback,
                # but keep looking for IPv4 regardless of JSON ordering.
                if ipv6 is None or block.get("scope") == "global":
                    ipv6 = address
        if name not in result and ipv6 is not None:
            result[name] = ipv6
    return result


def interface_addresses(run: Callable = None) -> dict:
    """Interface addresses from `ip -j addr show`; empty when ip is unavailable."""
    if run is None:
        run = _default_run
    try:
        out = run(["ip", "-j", "addr", "show"], timeout=2.0)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return {}
    return parse_ip_addr(out)


def memory(ps) -> MemInfo:
    """Return MemInfo from psutil.virtual_memory() and psutil.swap_memory()."""
    vm = ps.virtual_memory()
    sw = ps.swap_memory()
    return MemInfo(
        total=vm.total,
        apps=vm.total - vm.available,
        # Only the cache the kernel can hand back: buffers+cached also counts
        # shared memory (tmpfs, GPU/IPC buffers) that is already in "apps", so
        # apps + cache + free must add up to total.
        cache=max(0, vm.available - vm.free),
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


def _nvml_gpu() -> Optional[GpuInfo]:
    """Collect the GPU via NVML ctypes; None when NVML is unavailable."""
    from spaced_monitor import nvml
    if not nvml.available():
        return None
    name = nvml.device_name(0)
    if name is None:
        return None
    pct = nvml.utilization(0)
    temp = nvml.temperature(0)
    power = nvml.power_usage(0)
    mem_used, mem_total = nvml.memory_info(0)
    return GpuInfo(
        name=_gpu_name(name),
        percent=pct,
        temp_c=temp,
        power_w=power,
        mem_used=mem_used,
        mem_total=mem_total,
    )


def nvidia_gpu(run: Callable = None) -> Optional[GpuInfo]:
    """Collect the GPU: NVML first, nvidia-smi as fallback."""
    info = _nvml_gpu()
    if info:
        return info
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


def _nvml_extra() -> Optional[GpuExtra]:
    """Driver version and PCIe link via NVML; None when NVML is unavailable."""
    from spaced_monitor import nvml
    if not nvml.available():
        return None
    driver = nvml.driver_version()
    gen, width = nvml.pci_link(0)
    if driver is None and gen is None:
        return None
    return GpuExtra(driver=driver, link_gen=gen, link_width=width)


def nvidia_extra(run: Callable = None) -> Optional[GpuExtra]:
    """Driver version and PCIe link: NVML first, nvidia-smi as fallback."""
    extra = _nvml_extra()
    if extra:
        return extra
    if run is None:
        run = _default_run
    cmd = [
        "nvidia-smi",
        "--query-gpu=driver_version,pcie.link.gen.current,pcie.link.width.current",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = run(cmd, timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_nvidia_extra(out)


def _text(raw: str) -> Optional[str]:
    """Keep a probe field as text; "[N/A]" and blanks become None."""
    s = (raw or "").strip()
    return None if not s or s == "[N/A]" else s


def _parse_nvidia_extra(out: str) -> Optional[GpuExtra]:
    """Parse the first nvidia-smi csv line into GpuExtra."""
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    while len(parts) < 3:
        parts.append("")
    return GpuExtra(driver=_text(parts[0]), link_gen=_text(parts[1]), link_width=_text(parts[2]))


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


def _virtual_interface(name: str) -> bool:
    """True for loopback and container/VM plumbing, which we never show."""
    if name == "lo" or name == "lo:" or name.startswith("lo:"):
        return True
    return name.startswith(("veth", "docker", "virbr", "tap", "br-", "vnet"))


class RateSampler:
    """Turn psutil's cumulative disk and network counters into rates."""

    def __init__(self, ps, clock: Callable[[], float] = time.monotonic) -> None:
        self._ps = ps
        self._clock = clock
        self._prev: Optional[Tuple[float, float, float, float, float]] = None
        self._prev_iface: dict = {}
        self.per_interface: dict = {}

    def sample(self) -> Tuple[DiskInfo, NetInfo]:
        """Return DiskInfo and NetInfo for the interval since the previous sample."""
        io = self._ps.disk_io_counters()
        by_iface = self._net_by_iface()
        rx = sum(v[0] for v in by_iface.values())
        tx = sum(v[1] for v in by_iface.values())
        now = self._clock()
        if self._prev is None:
            rates = (0.0, 0.0, 0.0, 0.0)
            self.per_interface = {name: (0.0, 0.0) for name in by_iface}
        else:
            pt, pr, pw, prx, ptx = self._prev
            dt = now - pt
            rates = (self._rate(pr, io.read_bytes, dt), self._rate(pw, io.write_bytes, dt),
                     self._rate(prx, rx, dt), self._rate(ptx, tx, dt))
            current = {}
            for name, (cur_rx, cur_tx) in by_iface.items():
                prev_rx, prev_tx = self._prev_iface.get(name, (0, 0))
                current[name] = (self._rate(prev_rx, cur_rx, dt),
                                 self._rate(prev_tx, cur_tx, dt))
            self.per_interface = current
        self._prev = (now, io.read_bytes, io.write_bytes, rx, tx)
        self._prev_iface = by_iface
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

    def _net_by_iface(self) -> dict:
        """Cumulative rx/tx per real interface, as {name: (bytes_recv, bytes_sent)}."""
        result: dict = {}
        for name, entry in self._ps.net_io_counters(pernic=True).items():
            if _virtual_interface(name):
                continue
            result[name] = (entry.bytes_recv, entry.bytes_sent)
        return result

    def _net_totals(self) -> Tuple[int, int]:
        """Sum net_io_counters over real interfaces only."""
        by_iface = self._net_by_iface()
        return (sum(v[0] for v in by_iface.values()),
                sum(v[1] for v in by_iface.values()))

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
    temperatures: list = field(default_factory=list)
    filesystems: list = field(default_factory=list)
    interfaces: list = field(default_factory=list)
    gpu_extra: Optional[GpuExtra] = None


class Sampler:
    """Own the sub-samplers and return one Snapshot per sample()."""

    _SLOW_EVERY_S = 5.0

    def __init__(self, ps=None, run: Callable = None, clock: Callable[[], float] = time.monotonic,
                 power_root: str = "/sys/class/powercap", drm_root: str = "/sys/class/drm",
                 gpu_fn: Callable = None, read: Callable[[str], str] = None,
                 iface_fn: Callable = None, gpu_extra_fn: Callable = None) -> None:
        """Wire the collectors; every probe is injectable for tests."""
        # The lean hwmon reader stands in for psutil's sensors only when the
        # real psutil is used; an injected ps (tests) is read as given.
        self._hwmon = None
        if ps is None:
            import psutil
            ps = psutil
            self._hwmon = HwmonTemps()
        self._ps = ps
        self._cpu = CpuSampler(ps, read=read)
        self._rates = RateSampler(ps, clock=clock)
        self._power = CpuPower(root=power_root, clock=clock)
        self._gpu_fn = gpu_fn if gpu_fn is not None else lambda: gpu(run=run, drm_root=drm_root)
        self._iface_fn = iface_fn if iface_fn is not None else lambda: interface_addresses(run)
        self._gpu_extra_fn = gpu_extra_fn if gpu_extra_fn is not None else lambda: nvidia_extra(run)
        self._clock = clock
        self._slow_at: Optional[float] = None
        self._temps_last: list = []
        self._fans_last: list = []
        self._addresses: Optional[dict] = None
        self._extra: Optional[GpuExtra] = None
        self._extra_read = False

    def _interfaces(self, refresh: bool = False) -> list:
        """Refresh DHCP/VPN addresses on the slow cadence, not every sample."""
        if refresh or self._addresses is None:
            self._addresses = self._iface_fn()
        rates = self._rates.per_interface
        return [Interface(name, self._addresses.get(name), rates[name][0], rates[name][1])
                for name in sorted(rates)]

    def _gpu_extra(self) -> Optional[GpuExtra]:
        """Driver version and PCIe link: read once, never again."""
        if not self._extra_read:
            self._extra_read = True
            self._extra = self._gpu_extra_fn()
        return self._extra

    def sample(self) -> Snapshot:
        """Take one full snapshot."""
        disk, net = self._rates.sample()
        info = self._gpu_fn()
        # Every sensor chip and fan sits on a slow bus whose driver re-reads
        # the hardware once its ~1 s cache expires: the full list and the fans
        # are read every _SLOW_EVERY_S, the CPU temperature every sample.
        now = self._clock()
        slow = self._slow_at is None or now - self._slow_at >= self._SLOW_EVERY_S
        if slow:
            self._slow_at = now
        once = _SensorsOnce(self._ps, self._hwmon, cpu_only=not slow)
        if slow:
            self._temps_last = temperatures(once)
            self._fans_last = fans(self._ps)
        return Snapshot(
            cpu=self._cpu.sample(once),
            memory=memory(self._ps),
            gpu=info,
            disk=disk,
            net=net,
            fans=self._fans_last,
            cpu_power_w=self._power.sample(),
            uptime_s=uptime_seconds(self._ps),
            temperatures=self._temps_last,
            filesystems=filesystems(self._ps),
            interfaces=self._interfaces(refresh=slow),
            gpu_extra=self._gpu_extra() if info else None,
        )


# hwmon chips that report the CPU package temperature (what cpu_temp reads).
_CPU_CHIPS = frozenset(("k10temp", "coretemp", "zenpower", "cpu_thermal", "soc_thermal"))


class HwmonTemps:
    """Read hwmon temperatures cheaply: labels once, only temp*_input each time.

    psutil.sensors_temperatures() re-reads every label, max and crit file on
    every call (about a thousand sysfs reads on a desktop board, 40-100 ms).
    Labels never change, so they are discovered once and refreshed every 30 s
    (or after a failed read: a sensor came or went). The result has psutil's
    shape: {chip: [reading with .label and .current]}.
    """

    _REDISCOVER_S = 30.0

    def __init__(self, root: str = "/sys/class/hwmon",
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._root = root
        self._clock = clock
        self._inputs: list = []
        self._found_at: Optional[float] = None

    def _discover(self) -> None:
        inputs = []
        for hw in sorted(glob.glob(os.path.join(self._root, "hwmon*"))):
            chip = _read_first(os.path.join(hw, "name"))
            if not chip:
                continue
            for path in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
                label = _read_first(path[: -len("_input")] + "_label") or ""
                inputs.append((chip, label, path))
        self._inputs = inputs
        self._found_at = self._clock()

    def sensors_temperatures(self, cpu_only: bool = False) -> dict:
        """Current readings, psutil-shaped; {} when the machine has no hwmon.

        cpu_only reads just the CPU's own chip (cheap, every second); other
        chips sit on slow buses (DDR5 SPD, Super-IO) and are read less often.
        A machine with no known CPU chip is read in full.
        """
        if self._found_at is None or self._clock() - self._found_at > self._REDISCOVER_S:
            self._discover()
        inputs = self._inputs
        if cpu_only:
            cpu = [i for i in inputs if i[0] in _CPU_CHIPS]
            inputs = cpu or inputs
        out: dict = {}
        for chip, label, path in inputs:
            raw = _read_first(path)
            if raw is None:
                self._found_at = None
                continue
            try:
                value = int(raw) / 1000.0
            except ValueError:
                continue
            out.setdefault(chip, []).append(_HwReading(label, value))
        return out


@dataclass
class _HwReading:
    """One hwmon temperature, shaped like psutil's shwtemp for our readers."""
    label: str
    current: float


def _read_first(path: str) -> Optional[str]:
    """First line of a small sysfs file, stripped; None when unreadable."""
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            return fh.readline().strip()
    except OSError:
        return None


class _SensorsOnce:
    """psutil, but every hwmon temperature is read once per snapshot.

    sensors_temperatures() walks every hwmon file (~40 ms here) and both the
    CPU temperature and the temperature list need it.
    """

    def __init__(self, ps, fast: Optional[HwmonTemps] = None,
                 cpu_only: bool = False) -> None:
        self._ps = ps
        self._fast = fast
        self._cpu_only = cpu_only
        self._temps = None

    def sensors_temperatures(self):
        if self._temps is None:
            temps = (self._fast.sensors_temperatures(cpu_only=self._cpu_only)
                     if self._fast else {})
            self._temps = temps or self._ps.sensors_temperatures()
        return self._temps

    def __getattr__(self, name):
        return getattr(self._ps, name)


def uptime_seconds(ps, now: Callable[[], float] = time.time) -> float:
    """Return system uptime in seconds."""
    return now() - ps.boot_time()


class CpuSampler:
    """Stateful CPU sampler that uses psutil's internal delta tracking."""

    def __init__(self, ps, read: Callable[[str], str] = None) -> None:
        self._ps = ps
        self._model = cpu_model(read)

    def sample(self, sensors=None) -> CpuInfo:
        """Take one CPU sample (non-blocking, uses psutil deltas).

        sensors is what to read the temperature from (default: psutil).
        """
        percent = self._ps.cpu_percent(interval=None)
        per_core = self._ps.cpu_percent(interval=None, percpu=True)
        freq_obj = self._ps.cpu_freq()
        freq_mhz = freq_obj.current if freq_obj else 0.0
        temp = cpu_temp(sensors if sensors is not None else self._ps)
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
