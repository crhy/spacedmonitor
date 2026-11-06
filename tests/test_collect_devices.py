# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the GPU, disk, network and power collectors."""

import json
import os
import subprocess
import tempfile
import time
import types
import unittest

from spaced_monitor.collect import (
    Fan, Filesystem, GpuExtra, GpuInfo, DiskInfo, Interface, NetInfo,
    Snapshot, Temperature,
    nvidia_gpu, amd_gpu, gpu, RateSampler, CpuPower, Sampler,
    parse_ip_addr, interface_addresses,
)


def write(path, text):
    """Write a fixture file, creating parent directories."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def io(bytes_sent=0, bytes_recv=0):
    """A psutil-like snetio entry."""
    return types.SimpleNamespace(bytes_sent=bytes_sent, bytes_recv=bytes_recv)


class TestNvidia(unittest.TestCase):
    """nvidia_gpu() parsing and failure handling."""

    CSV = "NVIDIA GeForce RTX 4070 Ti SUPER, 97, 56, 160.53, 15684, 16376\n"

    def setUp(self):
        import unittest.mock
        self._p = unittest.mock.patch("spaced_monitor.collect._nvml_gpu", return_value=None)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_normal(self):
        info = nvidia_gpu(run=lambda cmd, timeout=None: self.CSV)
        assert info == GpuInfo(
            name="RTX 4070 Ti SUPER", percent=97.0, temp_c=56.0, power_w=160.53,
            mem_used=15684 * 1024 * 1024, mem_total=16376 * 1024 * 1024,
        )

    def test_na_fields(self):
        line = "NVIDIA Foo, [N/A], [N/A], [N/A], [N/A], [N/A]\n"
        info = nvidia_gpu(run=lambda cmd, timeout=None: line)
        assert info == GpuInfo(name="Foo", percent=None, temp_c=None,
                               power_w=None, mem_used=None, mem_total=None)

    def test_missing_binary(self):
        def run(cmd, timeout=None):
            raise FileNotFoundError(2, "nvidia-smi")
        assert nvidia_gpu(run=run) is None

    def test_timeout(self):
        def run(cmd, timeout=None):
            raise subprocess.TimeoutExpired(cmd, 2)
        assert nvidia_gpu(run=run) is None

    def test_empty_output(self):
        assert nvidia_gpu(run=lambda cmd, timeout=None: "") is None

    def test_second_line_ignored(self):
        info = nvidia_gpu(run=lambda cmd, timeout=None: self.CSV + "other, 1, 2, 3, 4, 5\n")
        assert info.name == "RTX 4070 Ti SUPER"

    def test_nvidia_prefix_without_geforce(self):
        info = nvidia_gpu(run=lambda cmd, timeout=None: "NVIDIA Llama, 1, 2, 3, 4, 5\n")
        assert info.name == "Llama"

    def test_gpu_prefers_nvidia(self):
        assert gpu(run=lambda cmd, timeout=None: self.CSV, drm_root="no-such-dir").name \
            == "RTX 4070 Ti SUPER"


class TestAmd(unittest.TestCase):
    """amd_gpu() reads the sysfs tree from a fixture directory."""

    def setUp(self):
        import unittest.mock
        self._p = unittest.mock.patch("spaced_monitor.collect._nvml_gpu", return_value=None)
        self._p.start()
        self.addCleanup(self._p.stop)

    def _fixture(self, power_file="power1_average"):
        """Build build/-local drm tree: card0 has a GPU, card1 does not."""
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        root = tmp.name
        dev = os.path.join(root, "card0", "device")
        write(os.path.join(dev, "gpu_busy_percent"), "42\n")
        write(os.path.join(dev, "mem_info_vram_used"), "26112000\n")
        write(os.path.join(dev, "mem_info_vram_total"), "536870912\n")
        hwmon = os.path.join(dev, "hwmon", "hwmon1")
        write(os.path.join(hwmon, "temp1_input"), "47000\n")
        write(os.path.join(hwmon, power_file), "1500000\n")
        write(os.path.join(root, "card1", "device", "driver"), "iGPU stub\n")
        write(os.path.join(root, "card0-DP-1", "device", "driver"), "link stub\n")
        return root

    def test_reads_card0(self):
        root = self._fixture()
        info = amd_gpu(root=root)
        assert info == GpuInfo(name="card0", percent=42.0, temp_c=47.0,
                               power_w=1.5, mem_used=26112000, mem_total=536870912)

    def test_power1_input_fallback(self):
        root = self._fixture(power_file="power1_input")
        assert amd_gpu(root=root).power_w == 1.5

    def test_no_card_with_busy_percent(self):
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        write(os.path.join(tmp.name, "card9", "device", "driver"), "x\n")
        assert amd_gpu(root=tmp.name) is None

    def test_missing_root(self):
        assert amd_gpu(root="build/definitely-not-here") is None

    def test_gpu_falls_back_to_amd(self):
        root = self._fixture()
        def run(cmd, timeout=None):
            raise FileNotFoundError(2, "nvidia-smi")
        assert gpu(run=run, drm_root=root).name == "card0"


class TestRates(unittest.TestCase):
    """RateSampler turns cumulative counters into bytes per second."""

    def _ps(self, disk=(0, 0), net=None, usage=(1000, 4000)):
        """Fake ps object with settable counters."""
        read_b, write_b = disk
        net = net or {}
        return types.SimpleNamespace(
            disk_io_counters=lambda: types.SimpleNamespace(
                read_bytes=read_b, write_bytes=write_b),
            net_io_counters=lambda pernic=True: net,
            disk_usage=lambda path: types.SimpleNamespace(used=usage[0], total=usage[1]),
        )

    def test_first_sample_is_zero(self):
        sampler = RateSampler(self._ps(), clock=lambda: 0.0)
        disk, net = sampler.sample()
        assert disk == DiskInfo(read_bps=0.0, write_bps=0.0, used=1000, total=4000)
        assert net == NetInfo(rx_bps=0.0, tx_bps=0.0)

    def test_rates_over_two_samples(self):
        ps = self._ps(disk=(2000, 1000), net={"eth0": io(bytes_sent=400, bytes_recv=800)})
        clock = FakeClock(0.0)
        sampler = RateSampler(ps, clock=clock)
        sampler.sample()
        ps.disk_io_counters = lambda: types.SimpleNamespace(read_bytes=4000, write_bytes=2000)
        ps.net_io_counters = lambda pernic=True: {"eth0": io(bytes_sent=800, bytes_recv=1600)}
        clock.t = 2.0
        disk, net = sampler.sample()
        assert disk.read_bps == 1000.0 and disk.write_bps == 500.0
        assert net.rx_bps == 400.0 and net.tx_bps == 200.0

    def test_excluded_interfaces(self):
        net = {"lo": io(bytes_sent=99, bytes_recv=99),
               "veth1a2b": io(bytes_sent=7, bytes_recv=7),
               "docker0": io(bytes_sent=7, bytes_recv=7),
               "virbr0": io(bytes_sent=7, bytes_recv=7),
               "tap0": io(bytes_sent=7, bytes_recv=7),
               "wlan0": io(bytes_sent=50, bytes_recv=60)}
        sampler = RateSampler(self._ps(net=net), clock=lambda: 0.0)
        sampler.sample()
        disk, net_info = sampler.sample()
        assert net_info == NetInfo(rx_bps=0.0, tx_bps=0.0)

    def test_counter_reset_gives_zero(self):
        ps = self._ps(disk=(5000, 5000))
        clock = FakeClock(0.0)
        sampler = RateSampler(ps, clock=clock)
        sampler.sample()
        ps.disk_io_counters = lambda: types.SimpleNamespace(read_bytes=10, write_bytes=0)
        clock.t = 5.0
        disk, _ = sampler.sample()
        assert disk.read_bps == 0.0 and disk.write_bps == 0.0

    def test_unreadable_root_fs(self):
        ps = self._ps()
        def boom(path):
            raise OSError("not mounted")
        ps.disk_usage = boom
        disk, _ = RateSampler(ps, clock=lambda: 0.0).sample()
        assert disk.used is None and disk.total is None


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


class TestInterfaceAddresses(unittest.TestCase):
    """Use iproute2's actual JSON keys, not a collector-shaped fake."""

    def test_iproute2_json(self):
        output = json.dumps([
            {"ifindex": 1, "ifname": "lo", "addr_info": [
                {"family": "inet", "local": "127.0.0.1", "prefixlen": 8,
                 "scope": "host"}]},
            {"ifindex": 2, "ifname": "eth0", "addr_info": [
                {"family": "inet6", "local": "fe80::1234", "scope": "link"},
                {"family": "inet", "local": "192.0.2.42", "prefixlen": 24,
                 "scope": "global"},
                {"family": "inet", "local": "192.0.2.43", "prefixlen": 24,
                 "scope": "global", "secondary": True}]},
            {"ifindex": 3, "ifname": "wlan0", "addr_info": []},
        ])
        calls = []

        def run(cmd, timeout=None):
            calls.append((cmd, timeout))
            return output

        self.assertEqual(interface_addresses(run),
                         {"lo": "127.0.0.1", "eth0": "192.0.2.42"})
        self.assertEqual(calls, [(["ip", "-j", "addr", "show"], 2.0)])

    def test_ipv6_only_prefers_global_address(self):
        output = json.dumps([{"ifname": "eth0", "addr_info": [
            {"family": "inet6", "local": "fe80::1", "scope": "link"},
            {"family": "inet6", "local": "2001:db8::42", "scope": "global"},
        ]}])
        self.assertEqual(parse_ip_addr(output), {"eth0": "2001:db8::42"})

    def test_malformed_output_is_ignored(self):
        for output in ("", "not json", "null", "{}", "42", '"text"'):
            with self.subTest(output=output):
                self.assertEqual(parse_ip_addr(output), {})
        output = json.dumps([
            None, 42, {}, {"ifname": "eth0", "addr_info": 4},
            {"ifname": "eth1", "addr_info": [None, 3, {},
                {"family": "inet", "local": []},
                {"family": "inet", "local": ""},
                {"family": "other", "local": "not an address"}]},
        ])
        self.assertEqual(parse_ip_addr(output), {})

    def test_unavailable_ip_is_nonfatal(self):
        for error in (FileNotFoundError("ip"), OSError("unavailable"),
                      subprocess.TimeoutExpired("ip", 2.0)):
            with self.subTest(error=error):
                def run(cmd, timeout=None):
                    raise error
                self.assertEqual(interface_addresses(run), {})


class TestCpuPower(unittest.TestCase):
    """CpuPower reads the sysfs energy counter, or gives up quietly."""

    def _fixture(self, energy="0", rng="1000000", unreadable=False):
        """Build a powercap tree under build/ with the given counter values."""
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        root = tmp.name
        pkg = os.path.join(root, "intel-rapl:0")
        write(os.path.join(pkg, "energy_uj"), energy + "\n")
        if rng:
            write(os.path.join(pkg, "max_energy_range_uj"), rng + "\n")
        if unreadable:
            os.chmod(os.path.join(pkg, "energy_uj"), 0o000)
        return root

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_unreadable_file(self):
        power = CpuPower(root=self._fixture(energy="1000", unreadable=True))
        assert power.sample() is None

    def test_missing_file(self):
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        assert CpuPower(root=tmp.name).sample() is None

    def test_first_sample_primes(self):
        power = CpuPower(root=self._fixture(energy="1000"), clock=FakeClock(0.0))
        assert power.sample() is None

    def test_delta_in_watts(self):
        root = self._fixture(energy="1000000")
        clock = FakeClock(0.0)
        power = CpuPower(root=root, clock=clock)
        power.sample()
        energy_path = os.path.join(root, "intel-rapl:0", "energy_uj")
        write(energy_path, "3000000")
        clock.t = 2.0
        self.assertAlmostEqual(power.sample(), 1.0)

    def test_wrap_uses_max_energy_range(self):
        root = self._fixture(energy="900", rng="1000")
        clock = FakeClock(0.0)
        power = CpuPower(root=root, clock=clock)
        power.sample()
        write(os.path.join(root, "intel-rapl:0", "energy_uj"), "100")
        clock.t = 2.0
        self.assertAlmostEqual(power.sample(), 200 / 2 / 1e6)

    def test_wrap_without_range(self):
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        pkg = os.path.join(tmp.name, "intel-rapl:0")
        write(os.path.join(pkg, "energy_uj"), "900")
        clock = FakeClock(0.0)
        power = CpuPower(root=tmp.name, clock=clock)
        power.sample()
        write(os.path.join(pkg, "energy_uj"), "100")
        clock.t = 2.0
        assert power.sample() is None


class TestSnapshot(unittest.TestCase):
    """Sampler assembles a Snapshot from injected fakes."""

    def setUp(self):
        import unittest.mock
        self._p = unittest.mock.patch("spaced_monitor.collect._nvml_gpu", return_value=None)
        self._p.start()
        self.addCleanup(self._p.stop)

    def _ps(self):
        """Fake psutil covering every collector used by Sampler."""
        return types.SimpleNamespace(
            cpu_percent=lambda interval=None, percpu=False: [10.0, 15.0] if percpu else 12.5,
            cpu_freq=lambda: types.SimpleNamespace(current=3600.0, min=0.0, max=0.0),
            sensors_temperatures=lambda: {"k10temp": [types.SimpleNamespace(label="Tctl", current=61.0)]},
            sensors_fans=lambda: {"fanx": [types.SimpleNamespace(label="Chassis", current=1200.0)]},
            virtual_memory=lambda: types.SimpleNamespace(
                total=8000, available=2000, free=1000, buffers=300, cached=700),
            swap_memory=lambda: types.SimpleNamespace(total=1000, used=100, percent=10),
            boot_time=lambda: time.time() - 100.0,
            disk_io_counters=lambda: types.SimpleNamespace(read_bytes=1000, write_bytes=500),
            net_io_counters=lambda pernic=True: {"lo": io(9, 9), "eth0": io(10, 20)},
            disk_usage=lambda path: types.SimpleNamespace(used=400, total=900),
        )

    def test_snapshot_fields(self):
        gpu_info = GpuInfo(name="RTX 5", percent=1.0, temp_c=50.0, power_w=90.0,
                           mem_used=1, mem_total=2)
        clock = FakeClock(100.0)
        sampler = Sampler(ps=self._ps(), read=lambda p: "model name\t: AMD TestModel 8-Core Processor\n",
                          gpu_fn=lambda: gpu_info, clock=clock,
                          iface_fn=lambda: {"eth0": "10.0.0.2"},
                          gpu_extra_fn=lambda: GpuExtra(driver="5611.5", link_gen="4", link_width="16"))
        snap = sampler.sample()
        assert isinstance(snap, Snapshot)
        assert snap.cpu.model == "TestModel" and snap.cpu.percent == 12.5
        assert snap.cpu.temp_c == 61.0 and snap.cpu.per_core == [10.0, 15.0]
        assert snap.memory.total == 8000 and snap.memory.apps == 6000
        assert snap.gpu is gpu_info
        assert snap.disk == DiskInfo(read_bps=0.0, write_bps=0.0, used=400, total=900)
        assert snap.net == NetInfo(rx_bps=0.0, tx_bps=0.0)
        assert snap.fans == [Fan(label="fanx Chassis", rpm=1200)]
        assert snap.cpu_power_w is None
        assert snap.gpu_extra == GpuExtra(driver="5611.5", link_gen="4", link_width="16")
        assert snap.interfaces == [Interface(name="eth0", address="10.0.0.2",
                                             rx_bps=0.0, tx_bps=0.0)]
        self.assertAlmostEqual(snap.uptime_s, 100.0, delta=1.0)
        assert snap.time is not None

    def test_gpu_absent(self):
        def run(cmd, timeout=None):
            raise FileNotFoundError(2, "nvidia-smi")
        sampler = Sampler(ps=self._ps(), read=lambda p: "", run=run,
                          drm_root="build/nope")
        assert sampler.sample().gpu is None

    def test_interface_addresses_refresh_on_slow_cadence(self):
        clock = FakeClock(0.0)
        ps = self._ps()
        calls = []
        addresses = {"eth0": "192.0.2.42"}

        def iface_fn():
            calls.append(clock())
            return addresses.copy()

        sampler = Sampler(ps=ps, read=lambda p: "", clock=clock,
                          gpu_fn=lambda: None, gpu_extra_fn=lambda: None,
                          iface_fn=iface_fn)
        self.assertEqual(sampler.sample().interfaces[0].address, "192.0.2.42")
        addresses["eth0"] = "192.0.2.43"
        for second in range(1, 5):
            clock.t = float(second)
            self.assertEqual(sampler.sample().interfaces[0].address, "192.0.2.42")
        clock.t = 5.0
        self.assertEqual(sampler.sample().interfaces[0].address, "192.0.2.43")
        self.assertEqual(calls, [0.0, 5.0])

        # Replacing an interface must discard its cached address too.
        addresses.clear()
        addresses["wlan0"] = "198.51.100.7"
        ps.net_io_counters = lambda pernic=True: {"wlan0": io(20, 30)}
        clock.t = 10.0
        interfaces = sampler.sample().interfaces
        self.assertEqual([(i.name, i.address) for i in interfaces],
                         [("wlan0", "198.51.100.7")])
        self.assertEqual(calls, [0.0, 5.0, 10.0])

    def test_address_lookup_recovers_after_empty_result(self):
        clock = FakeClock(0.0)
        addresses = {}
        sampler = Sampler(ps=self._ps(), read=lambda p: "", clock=clock,
                          gpu_fn=lambda: None, gpu_extra_fn=lambda: None,
                          iface_fn=lambda: addresses.copy())
        self.assertIsNone(sampler.sample().interfaces[0].address)
        addresses["eth0"] = "192.0.2.42"
        clock.t = 5.0
        self.assertEqual(sampler.sample().interfaces[0].address, "192.0.2.42")


if __name__ == "__main__":
    unittest.main()
