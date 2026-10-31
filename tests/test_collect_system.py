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
