"""Stable device identity, missing telemetry and bounded histories."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from spaced_monitor.collect import all_gpus, ram_temperatures, Temperature
from spaced_monitor.devices import History, device_rows, device_metrics
from tests.ui_smoke import _mock_snapshot


class Devices(unittest.TestCase):
    def test_memory_sensor_recognition(self):
        known = [Temperature("jc42", "temp1", 42),
                 Temperature("spd5118", "temp1", 43),
                 Temperature("board", "DIMM_A1", 44)]
        unrelated = [Temperature("acpitz", "temp1", 50),
                     Temperature("nvme", "Composite", 51)]
        self.assertEqual(ram_temperatures(known + unrelated), known)

    @patch("spaced_monitor.nvml.device_count", return_value=0)
    def test_batched_nvidia_and_drm(self, _count):
        calls = []
        def run(command, timeout):
            calls.append((command, timeout))
            return ("GPU-b, NVIDIA Same, 20, 40, 50, 100, 200, 580\n"
                    "GPU-a, NVIDIA Same, N/A, nan, N/A, N/A, 200, 580")
        with tempfile.TemporaryDirectory() as root:
            device = Path(root) / "card0" / "device"
            device.mkdir(parents=True)
            (device / "vendor").write_text("0x1002")
            (device / "gpu_busy_percent").write_text("25")
            result = all_gpus(run, root)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 2.0)
        self.assertEqual(len(result), 3)
        self.assertEqual([g.device_id for g in result[:2]], ["GPU-b", "GPU-a"])
        gpu = next(g for g in result if g.device_id == "GPU-a")
        self.assertIsNone(gpu.percent)
        self.assertIsNone(gpu.temp_c)
        self.assertIsNone(gpu.mem_used)
        self.assertEqual(next(g for g in result if g.device_id == "GPU-b").mem_used, 100 * 1024**2)

    @patch("spaced_monitor.nvml.device_count", return_value=0)
    def test_drm_nvidia_not_hidden_by_amd(self, _count):
        with tempfile.TemporaryDirectory() as root:
            for index, vendor in enumerate(("0x1002", "0x10de")):
                device = Path(root) / f"card{index}" / "device"
                device.mkdir(parents=True)
                (device / "vendor").write_text(vendor)
            result = all_gpus(lambda *a, **kw: "", root)
        self.assertEqual(len(result), 2)

    def test_history_identity_disconnect_and_bounds(self):
        snap = _mock_snapshot()
        a = replace(snap.gpu, device_id="a", percent=10)
        b = replace(snap.gpu, device_id="b", percent=90)
        history = History()
        history.update(replace(snap, gpu=a, gpus=[a, b]))
        history.update(replace(snap, gpu=b, gpus=[b, a]))
        self.assertEqual(list(history.values["gpu:a"]), [10, 10])
        history.update(replace(snap, gpu=b, gpus=[b]))
        self.assertIsNone(history.values["gpu:a"][-1])
        for _ in range(150):
            history.update(snap)
        self.assertEqual(len(history.values["cpu"]), 120)
        self.assertEqual(history.maximum["gpu:b"], 90)
        history.reset_maximum()
        self.assertEqual(history.maximum, {})

    def test_full_details_and_ram_reason(self):
        snap = _mock_snapshot()
        rows = device_rows(snap)
        self.assertIn(("Logical threads", "16"), rows["cpu"][2])
        self.assertIn("no memory temperature sensor", dict(rows["memory"][2])["RAM temperatures"])
        self.assertEqual(len(rows["network"][2]), 2 + len(snap.interfaces))
        self.assertIn(("Device identity", "legacy"), rows["gpu:legacy"][2])

    def test_visual_metrics_and_missing_readings(self):
        snap = _mock_snapshot()
        for key in device_rows(snap):
            self.assertTrue(device_metrics(snap, key), key)
        self.assertEqual(len([m for m in device_metrics(snap, "cpu")
                              if m[0].startswith("Thread ")]), 16)
        gpu = replace(snap.gpu, percent=None, temp_c=None, mem_used=None)
        metrics = device_metrics(replace(snap, gpu=gpu, gpus=[gpu]), "gpu:legacy")
        self.assertIsNone(metrics[0][1])
        self.assertIsNone(metrics[1][1])
        self.assertIsNone(metrics[3][1])
        self.assertEqual(device_metrics(snap, "gpu:disconnected"), [])
