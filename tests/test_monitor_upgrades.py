"""Temperature preferences, measured suggestions and per-device VRAM."""
import ctypes
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from spaced_monitor import format as fmt, preferences, nvml
from spaced_monitor.devices import device_rows, device_metrics, History
from spaced_monitor.suggestions import DiskActivity, Suggestions
from tests.ui_smoke import _mock_snapshot


class Temperatures(unittest.TestCase):
    def test_units_and_missing(self):
        with patch.object(fmt, "CELSIUS", False):
            self.assertEqual(fmt.temperature_value(0), 32)
            self.assertIn("°F", fmt.temp(40))
            self.assertIsNone(fmt.temperature_value(None))
        with patch.object(fmt, "CELSIUS", True):
            self.assertEqual(fmt.temperature_value(40), 40)
            self.assertIn("°C", fmt.temp(40))

    def test_preference_default_persist_corrupt(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"XDG_CONFIG_HOME": root}):
            self.assertFalse(preferences.load_celsius())
            self.assertTrue(preferences.save_celsius(True))
            self.assertTrue(preferences.load_celsius())
            self.assertTrue(preferences.save_celsius(False))
            self.assertFalse(preferences.load_celsius())
            for bad in ("bad json", "[]", "null", '{"celsius": "true"}'):
                preferences.path().write_text(bad)
                self.assertFalse(preferences.load_celsius())


class Advice(unittest.TestCase):
    def snapshot(self, **kwargs):
        snap = _mock_snapshot()
        return replace(snap, cpu=replace(snap.cpu, percent=10),
                       memory=replace(snap.memory, available=snap.memory.total * .7),
                       gpu=None, gpus=[], **kwargs)

    def test_warmup_idle_and_busy_drives(self):
        model = Suggestions()
        snap = self.snapshot()
        model.update(snap)
        self.assertIn("Measuring", dict(model.rows()))
        for _ in range(20):
            model.update(snap)
        self.assertIn("No sustained", dict(model.rows())["Biggest bottleneck"])
        for kind in ("HDD", "SSD / non-NVMe", "NVMe"):
            model = Suggestions()
            for _ in range(5):
                model.update(replace(snap, disk_devices=[("disk", kind, 95)]))
            rows = dict(model.rows())
            self.assertIn("Drive", rows["Highest observed pressure"])
            self.assertIn("NVMe SSD may help" if kind != "NVMe" else "competing disk users", rows["Suggestion"])

    def test_removed_drive_and_missing_samples(self):
        model = Suggestions()
        for _ in range(25):
            model.update(self.snapshot(disk_devices=[("sda", "HDD", 100)]))
        self.assertEqual(len(model.samples), 20)
        model.update(self.snapshot(disk_devices=[("sdb", "HDD", None)]))
        self.assertNotIn("Highest observed pressure", dict(model.rows()))

    def test_vram_pressure(self):
        snap = self.snapshot()
        gpu = replace(_mock_snapshot().gpu, mem_used=99, mem_total=100, percent=None)
        model = Suggestions()
        for _ in range(5):
            model.update(replace(snap, gpu=gpu, gpus=[gpu]))
        self.assertIn("VRAM", dict(model.rows())["Highest observed pressure"])

    def test_disk_delta_reset_and_missing(self):
        with tempfile.TemporaryDirectory() as root:
            dev = Path(root) / "sda"
            (dev / "queue").mkdir(parents=True)
            (dev / "queue/rotational").write_text("1")
            def ticks(n):
                (dev / "stat").write_text("0 " * 9 + str(n) + " 0")
            clock = Mock(side_effect=[0, 2, 3, 4])
            probe = DiskActivity(root, clock)
            ticks(100)
            self.assertEqual(probe.sample(), [("sda", "HDD", None)])
            ticks(1100)
            self.assertEqual(probe.sample(), [("sda", "HDD", 50)])
            ticks(0)
            self.assertIsNone(probe.sample()[0][2])
            (dev / "stat").write_text("broken")
            self.assertEqual(probe.sample(), [])


class Vram(unittest.TestCase):
    def test_separate_device_details_and_history(self):
        snap = _mock_snapshot()
        a = replace(snap.gpu, device_id="a", mem_used=20, mem_total=100, memory_processes={123: 20})
        b = replace(a, device_id="b", mem_used=80, memory_processes=None)
        snap = replace(snap, gpu=a, gpus=[a, b])
        rows = device_rows(snap)
        self.assertNotEqual(rows["gpu:a"], rows["vram:a"])
        self.assertIn("123", str(rows["vram:a"]))
        self.assertIn("Unavailable", str(rows["vram:b"]))
        self.assertNotEqual(device_metrics(snap, "vram:a"), device_metrics(snap, "vram:b"))
        history = History()
        history.update(snap)
        self.assertEqual(list(history.values["vram:a"]), [20])
        self.assertEqual(list(history.values["vram:b"]), [80])

    def test_deduplicate_compute_and_graphics(self):
        with patch.object(nvml, "_running_processes", side_effect=[{1: 100}, {1: 100, 2: 50}]):
            self.assertEqual(nvml.memory_processes(), {1: 100, 2: 50})
        with patch.object(nvml, "_running_processes", return_value=None):
            self.assertIsNone(nvml.memory_processes())

    def test_process_abi_and_multiple_entries(self):
        self.assertEqual(ctypes.sizeof(nvml._ProcessInfo), 24)
        lib = Mock()
        def query(dev, count, entries):
            count._obj.value = 3
            for i, (pid, used) in enumerate(((10, 111), (20, 222), (30, 2**64 - 1))):
                entries[i].pid, entries[i].usedMemory = pid, used
            return 0
        lib.nvmlDeviceGetComputeRunningProcesses_v3.side_effect = query
        with patch.object(nvml, "_load", return_value=lib), patch.object(nvml, "_init", return_value=True), patch.object(nvml, "_device_handle", return_value=1):
            self.assertEqual(nvml.compute_processes(), {10: 111, 20: 222})

    def test_process_buffer_growth_and_unavailable_driver(self):
        lib = Mock()
        calls = []
        def query(dev, count, entries):
            calls.append(count._obj.value)
            if len(calls) == 1:
                count._obj.value = 100
                return 7
            count._obj.value = 1
            entries[0].pid, entries[0].usedMemory = 42, 1000
            return 0
        lib.nvmlDeviceGetGraphicsRunningProcesses_v3.side_effect = query
        with patch.object(nvml, "_load", return_value=lib), patch.object(nvml, "_init", return_value=True), patch.object(nvml, "_device_handle", return_value=1):
            self.assertEqual(nvml._running_processes(0, "Graphics"), {42: 1000})
            self.assertEqual(calls, [64, 128])
        with patch.object(nvml, "_load", return_value=None):
            self.assertIsNone(nvml.memory_processes())


if __name__ == "__main__":
    unittest.main()
