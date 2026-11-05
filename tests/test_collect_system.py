# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for spaced_monitor.collect."""

import types
import unittest

from spaced_monitor.collect import (
    CpuInfo, MemInfo, Fan, cpu_model, cpu_temp, fans, memory,
    uptime_seconds, CpuSampler,
)


class TestCpuModel(unittest.TestCase):
    def test_amd(self):
        text = "model name\t: AMD Ryzen 7 7800X3D 8-Core Processor\n"
        assert cpu_model(read=lambda p: text) == "Ryzen 7 7800X3D"

    def test_intel(self):
        text = "model name\t: Intel(R) Core(TM) i7-12700H CPU @ 2.70GHz\n"
        assert cpu_model(read=lambda p: text) == "i7-12700H"

    def test_missing(self):
        assert cpu_model(read=lambda p: "vendor\n") == "Unknown"


class TestCpuTemp(unittest.TestCase):
    def _reading(self, label, current):
        return types.SimpleNamespace(label=label, current=current)

    def test_k10temp_tctl(self):
        ps = types.SimpleNamespace(
            sensors_temperatures=lambda: {
                "k10temp": [self._reading("Tctl", 55.0), self._reading("Tdie", 50.0)]
            }
        )
        assert cpu_temp(ps) == 55.0

    def test_k10temp_tdie_only(self):
        ps = types.SimpleNamespace(
            sensors_temperatures=lambda: {
                "k10temp": [self._reading("Tdie", 48.0)]
            }
        )
        assert cpu_temp(ps) == 48.0

    def test_coretemp_package(self):
        ps = types.SimpleNamespace(
            sensors_temperatures=lambda: {
                "coretemp": [self._reading("Package id 0", 72.0),
                             self._reading("Core 0", 80.0)]
            }
        )
        assert cpu_temp(ps) == 72.0

    def test_zenpower(self):
        ps = types.SimpleNamespace(
            sensors_temperatures=lambda: {
                "zenpower": [self._reading("Tctl", 61.0)]
            }
        )
        assert cpu_temp(ps) == 61.0

    def test_fallback_first(self):
        ps = types.SimpleNamespace(
            sensors_temperatures=lambda: {
                "mystery": [self._reading("x", 33.0)]
            }
        )
        assert cpu_temp(ps) == 33.0

    def test_none_when_empty(self):
        ps = types.SimpleNamespace(sensors_temperatures=lambda: {})
        assert cpu_temp(ps) is None

    def test_none_when_missing(self):
        ps = types.SimpleNamespace()
        assert cpu_temp(ps) is None


class TestFans(unittest.TestCase):
    def _reading(self, label, current):
        return types.SimpleNamespace(label=label, current=current)

    def test_basic(self):
        ps = types.SimpleNamespace(
            sensors_fans=lambda: {
                "cpu": [self._reading("fan1", 1200), self._reading("fan2", 0)]
            }
        )
        result = fans(ps)
        assert len(result) == 1
        assert result[0] == Fan(label="cpu fan1", rpm=1200)

    def test_missing_sensors_fans(self):
        ps = types.SimpleNamespace()
        assert fans(ps) == []

    def test_empty(self):
        ps = types.SimpleNamespace(sensors_fans=lambda: {})
        assert fans(ps) == []


class TestMemory(unittest.TestCase):
    def test_arithmetic(self):
        vm = types.SimpleNamespace(total=32 * 1024**3, available=20 * 1024**3,
                                   free=14 * 1024**3,
                                   buffers=2 * 1024**3, cached=4 * 1024**3)
        sw = types.SimpleNamespace(used=1 * 1024**3, total=2 * 1024**3)
        ps = types.SimpleNamespace(virtual_memory=lambda: vm, swap_memory=lambda: sw)
        mi = memory(ps)
        gib = 1024**3
        assert mi.total == 32 * gib
        assert mi.apps == 12 * gib
        assert mi.cache == 6 * gib
        assert mi.available == 20 * gib
        assert mi.swap_used == 1 * gib
        assert mi.swap_total == 2 * gib

    def test_segments_never_exceed_total_with_shared_memory(self):
        """20 GB of shmem counts in buffers+cached and in apps: no double count."""
        gib = 1024**3
        vm = types.SimpleNamespace(total=30 * gib, available=4 * gib, free=gib // 2,
                                   buffers=gib // 16, cached=23 * gib)
        sw = types.SimpleNamespace(used=0, total=0)
        mi = memory(types.SimpleNamespace(virtual_memory=lambda: vm, swap_memory=lambda: sw))
        free = mi.available - mi.cache
        self.assertEqual(mi.apps + mi.cache + free, mi.total)


class TestUptime(unittest.TestCase):
    def test_basic(self):
        ps = types.SimpleNamespace(boot_time=lambda: 1000000.0)
        assert uptime_seconds(ps, now=lambda: 1086430.0) == 86430.0


class TestCpuSampler(unittest.TestCase):
    def test_sample(self):
        ps = types.SimpleNamespace(
            cpu_percent=lambda interval=None, percpu=False: (
                [10.0, 20.0, 30.0] if percpu else 20.0
            ),
            cpu_freq=lambda: types.SimpleNamespace(current=4200.0, min=0.0, max=0.0),
            sensors_temperatures=lambda: {
                "k10temp": [types.SimpleNamespace(label="Tctl", current=55.0)]
            },
        )
        sampler = CpuSampler(ps, read=lambda p: "model name\t: AMD Ryzen 7 7800X3D 8-Core Processor\n")
        ci = sampler.sample()
        assert ci.model == "Ryzen 7 7800X3D"
        assert ci.percent == 20.0
        assert ci.per_core == [10.0, 20.0, 30.0]
        assert ci.freq_mhz == 4200.0
        assert ci.temp_c == 55.0

    def test_freq_none(self):
        ps = types.SimpleNamespace(
            cpu_percent=lambda interval=None, percpu=False: (
                [5.0] if percpu else 5.0
            ),
            cpu_freq=lambda: None,
            sensors_temperatures=lambda: {},
        )
        sampler = CpuSampler(ps, read=lambda p: "model name\t: x\n")
        ci = sampler.sample()
        assert ci.freq_mhz == 0.0


if __name__ == "__main__":
    unittest.main()


class SensorsReadOncePerSnapshot(unittest.TestCase):
    """The hwmon walk is the costliest read: one per snapshot, not one per user."""

    def test_one_sensors_temperatures_call_per_sample(self):
        import psutil
        from spaced_monitor.collect import Sampler

        class Counting:
            calls = 0

            def sensors_temperatures(self):
                Counting.calls += 1
                return {"k10temp": [types.SimpleNamespace(label="Tctl", current=50.0,
                                                          high=None, critical=None)]}

            def __getattr__(self, name):
                return getattr(psutil, name)

        snap = Sampler(ps=Counting(), gpu_fn=lambda: None, iface_fn=lambda: {},
                       gpu_extra_fn=lambda: None, power_root="/nonexistent").sample()
        self.assertEqual(Counting.calls, 1)
        self.assertEqual(snap.cpu.temp_c, 50.0)


class HwmonTempsReader(unittest.TestCase):
    """The lean hwmon reader returns psutil's shape and survives hotplug."""

    def _chip(self, root, n, name, sensors):
        import os
        d = os.path.join(root, f"hwmon{n}")
        os.makedirs(d)
        with open(os.path.join(d, "name"), "w") as fh:
            fh.write(name + "\n")
        for i, (label, milli) in enumerate(sensors, 1):
            with open(os.path.join(d, f"temp{i}_input"), "w") as fh:
                fh.write(f"{milli}\n")
            if label is not None:
                with open(os.path.join(d, f"temp{i}_label"), "w") as fh:
                    fh.write(label + "\n")

    def test_reads_and_rediscovers(self):
        import os, shutil, tempfile
        from spaced_monitor.collect import HwmonTemps, cpu_temp
        root = tempfile.mkdtemp(dir=os.path.join(os.path.dirname(__file__), "..", "build"))
        self.addCleanup(shutil.rmtree, root)
        self._chip(root, 0, "k10temp", [("Tctl", 61250), ("Tccd1", 55000)])
        self._chip(root, 1, "nvme", [(None, 40000)])
        h = HwmonTemps(root=root, clock=lambda: 0.0)
        got = h.sensors_temperatures()
        self.assertEqual([(r.label, r.current) for r in got["k10temp"]],
                         [("Tctl", 61.25), ("Tccd1", 55.0)])
        self.assertEqual([(r.label, r.current) for r in got["nvme"]], [("", 40.0)])
        self.assertEqual(cpu_temp(h), 61.25)
        shutil.rmtree(os.path.join(root, "hwmon1"))   # a device went away
        self.assertNotIn("nvme", h.sensors_temperatures())
        self.assertEqual(sorted(h.sensors_temperatures()), ["k10temp"])  # rediscovered


class SlowSensorsEveryFiveSeconds(unittest.TestCase):
    """Fans and the full temperature list sit on slow buses: not every second."""

    def test_fans_and_full_list_every_five_seconds(self):
        import psutil
        from spaced_monitor.collect import Sampler

        class Counting:
            fans = 0

            def sensors_fans(self):
                Counting.fans += 1
                return {}

            def sensors_temperatures(self):
                return {"k10temp": [types.SimpleNamespace(label="Tctl", current=50.0)]}

            def __getattr__(self, name):
                return getattr(psutil, name)

        t = [100.0]
        s = Sampler(ps=Counting(), clock=lambda: t[0], gpu_fn=lambda: None,
                    iface_fn=lambda: {}, gpu_extra_fn=lambda: None, power_root="/nonexistent")
        snaps = []
        for _ in range(6):
            snaps.append(s.sample())
            t[0] += 1.0
        self.assertEqual(Counting.fans, 2)                     # t=100 and t=105
        self.assertTrue(all(sn.temperatures for sn in snaps))  # reused in between
        self.assertTrue(all(sn.cpu.temp_c == 50.0 for sn in snaps))

    def test_cpu_only_reads_just_the_cpu_chip(self):
        import os, shutil, tempfile
        from spaced_monitor.collect import HwmonTemps
        root = tempfile.mkdtemp(dir=os.path.join(os.path.dirname(__file__), "..", "build"))
        self.addCleanup(shutil.rmtree, root)
        HwmonTempsReader._chip(self, root, 0, "k10temp", [("Tctl", 60000)])
        HwmonTempsReader._chip(self, root, 1, "spd5118", [(None, 35000)])
        h = HwmonTemps(root=root, clock=lambda: 0.0)
        self.assertEqual(sorted(h.sensors_temperatures(cpu_only=True)), ["k10temp"])
        self.assertEqual(sorted(h.sensors_temperatures()), ["k10temp", "spd5118"])
        shutil.rmtree(os.path.join(root, "hwmon0"))
        h2 = HwmonTemps(root=root, clock=lambda: 0.0)
        self.assertEqual(sorted(h2.sensors_temperatures(cpu_only=True)), ["spd5118"])  # no CPU chip: all
