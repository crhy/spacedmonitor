# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the NVML ctypes wrapper and its integration into collectors."""

import ctypes
import ctypes.util
import unittest
from unittest.mock import patch

from spaced_monitor.collect import GpuInfo, GpuInfo, GpuExtra, nvidia_gpu, nvidia_extra
from spaced_monitor.processes import _gpu_mem_by_pid, _gpu_sm_by_pid


class TestNvmlGpuParsing(unittest.TestCase):
    """nvidia_gpu() uses NVML when available, falls back to nvidia-smi."""

    CSV = "NVIDIA GeForce RTX 4070 Ti SUPER, 42, 65, 120, 4096, 8192"

    def test_nvml_first(self):
        """When NVML returns data, nvidia-smi is never called."""
        fake_info = GpuInfo(name="RTX 4070 Ti SUPER", percent=42.0,
                            temp_c=65.0, power_w=120.0, mem_used=4096,
                            mem_total=8192)
        with patch("spaced_monitor.collect._nvml_gpu", return_value=fake_info):
            def should_not_run(cmd, timeout=None):
                raise AssertionError("nvidia-smi should not be called")
            info = nvidia_gpu(run=should_not_run)
        assert info is fake_info

    def test_falls_back_when_nvml_none(self):
        """When NVML returns None, nvidia-smi is used."""
        with patch("spaced_monitor.collect._nvml_gpu", return_value=None):
            info = nvidia_gpu(run=lambda cmd, timeout=None: self.CSV)
        assert info is not None
        assert info.name == "RTX 4070 Ti SUPER"

    def test_both_fail(self):
        """When both NVML and nvidia-smi fail, result is None."""
        with patch("spaced_monitor.collect._nvml_gpu", return_value=None):
            def fail(cmd, timeout=None):
                raise FileNotFoundError(2, "nvidia-smi")
            assert nvidia_gpu(run=fail) is None


class TestNvmlExtraParsing(unittest.TestCase):
    """nvidia_extra() uses NVML when available, falls back to nvidia-smi."""

    CSV = "5611.5, 4, 16"

    def test_nvml_first(self):
        """When NVML returns data, nvidia-smi is never called."""
        fake = GpuExtra(driver="5611.5", link_gen="4", link_width="16")
        with patch("spaced_monitor.collect._nvml_extra", return_value=fake):
            def should_not_run(cmd, timeout=None):
                raise AssertionError("nvidia-smi should not be called")
            extra = nvidia_extra(run=should_not_run)
        assert extra is fake

    def test_falls_back_when_nvml_none(self):
        """When NVML returns None, nvidia-smi is used."""
        with patch("spaced_monitor.collect._nvml_extra", return_value=None):
            extra = nvidia_extra(run=lambda cmd, timeout=None: self.CSV)
        assert extra is not None
        assert extra.driver == "5611.5"


class TestNvmlProcessParsing(unittest.TestCase):
    """_gpu_mem_by_pid and _gpu_sm_by_pid use NVML first."""

    def test_gpu_mem_nvml_first(self):
        """NVML compute_processes is tried before nvidia-smi."""
        with patch("spaced_monitor.processes._nvml_gpu_mem",
                   return_value={100: 2048, 200: 4096}):
            result = _gpu_mem_by_pid(run=lambda cmd, timeout=None: "999, 9999")
        assert result == {100: 2048, 200: 4096}

    def test_gpu_mem_falls_back(self):
        """When NVML is unavailable, nvidia-smi compute-apps is used."""
        with patch("spaced_monitor.processes._nvml_gpu_mem", return_value=None):
            result = _gpu_mem_by_pid(run=lambda cmd, timeout=None: "111, 2048\n222, 512")
        assert result == {111: 2048 * 1024 * 1024, 222: 512 * 1024 * 1024}

    def test_gpu_sm_nvml_first(self):
        """NVML process_utilization is tried before nvidia-smi pmon."""
        with patch("spaced_monitor.processes._nvml_gpu_sm",
                   return_value={42: 55.0}):
            result = _gpu_sm_by_pid(run=lambda cmd, timeout=None: "unused")
        assert result == {42: 55.0}

    def test_empty_nvml_answer_spawns_no_nvidia_smi(self):
        """No GPU process right now is an answer: nvidia-smi must not run every 2 s."""
        def run(cmd, timeout=None):
            raise AssertionError("nvidia-smi was spawned: %s" % cmd)
        with patch("spaced_monitor.processes._nvml_gpu_mem", return_value={}), \
                patch("spaced_monitor.processes._nvml_gpu_sm", return_value={}):
            assert _gpu_mem_by_pid(run=run) == {}
            assert _gpu_sm_by_pid(run=run) == {}

    def test_gpu_sm_falls_back(self):
        """When NVML is unavailable, nvidia-smi pmon is used."""
        pmon = ("#    gpu    pid    type    sm    mem\n"
                "    0      1234    C     75     50\n")
        with patch("spaced_monitor.processes._nvml_gpu_sm", return_value=None):
            result = _gpu_sm_by_pid(run=lambda cmd, timeout=None: pmon)
        assert result == {1234: 75.0}


class TestNvmlRealDevice(unittest.TestCase):
    """When libnvidia-ml.so.1 is loadable, read a real device name."""

    def test_real_device_name(self):
        """Skip when the NVML library is not present."""
        path = ctypes.util.find_library("nvidia-ml")
        if path is None:
            self.skipTest("libnvidia-ml.so.1 not available")
        from spaced_monitor import nvml
        if not nvml.available():
            self.skipTest("NVML init failed")
        name = nvml.device_name(0)
        assert name is not None
        assert len(name) > 0


if __name__ == "__main__":
    unittest.main()
