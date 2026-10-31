# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for spaced_monitor.format."""

import unittest

from spaced_monitor.format import (
    EMDASH, bytes_gb, pair_gb, rate, temp, ghz, watts, rpm, duration, percent,
)


class TestBytesGb(unittest.TestCase):
    def test_none(self):
        self.assertEqual(bytes_gb(None), EMDASH)

    def test_zero(self):
        self.assertEqual(bytes_gb(0), "0.0 GB")

    def test_one_gb(self):
        self.assertEqual(bytes_gb(1024**3), "1.0 GB")

    def test_fractional(self):
        self.assertEqual(bytes_gb(int(24.6 * 1024**3)), "24.6 GB")

    def test_large(self):
        self.assertEqual(bytes_gb(32 * 1024**3), "32.0 GB")


class TestPairGb(unittest.TestCase):
    def test_none_used(self):
        self.assertEqual(pair_gb(None, 100), EMDASH)

    def test_none_total(self):
        self.assertEqual(pair_gb(100, None), EMDASH)

    def test_whole_total(self):
        self.assertEqual(pair_gb(int(24.6 * 1024**3), 32 * 1024**3), "24.6 / 32 GB")

    def test_fractional_total(self):
        self.assertEqual(pair_gb(int(13.2 * 1024**2 * 1024), int(15.5 * 1024**3)),
                         "13.2 / 15.5 GB")

    def test_zero(self):
        self.assertEqual(pair_gb(0, 16 * 1024**3), "0.0 / 16 GB")


class TestRate(unittest.TestCase):
    def test_none(self):
        self.assertEqual(rate(None), EMDASH)

    def test_zero(self):
        self.assertEqual(rate(0), "0 B/s")

    def test_negative(self):
        self.assertEqual(rate(-5), "0 B/s")

    def test_bytes(self):
        self.assertEqual(rate(512), "512 B/s")

    def test_kb(self):
        self.assertEqual(rate(940 * 1024), "940 KB/s")

    def test_mb(self):
        self.assertEqual(rate(128 * 1024**2), "128 MB/s")

    def test_gb(self):
        self.assertEqual(rate(2 * 1024**3), "2 GB/s")


class TestTemp(unittest.TestCase):
    def test_none(self):
        self.assertEqual(temp(None), EMDASH)

    def test_rounds(self):
        self.assertEqual(temp(62.4), "62 °C")

    def test_rounds_up(self):
        self.assertEqual(temp(62.6), "63 °C")

    def test_zero(self):
        self.assertEqual(temp(0), "0 °C")


class TestGhz(unittest.TestCase):
    def test_none(self):
        self.assertEqual(ghz(None), EMDASH)

    def test_basic(self):
        self.assertEqual(ghz(4600), "4.6 GHz")

    def test_zero(self):
        self.assertEqual(ghz(0), "0.0 GHz")


class TestWatts(unittest.TestCase):
    def test_none(self):
        self.assertEqual(watts(None), EMDASH)

    def test_basic(self):
        self.assertEqual(watts(235), "235 W")

    def test_rounds(self):
        self.assertEqual(watts(47.6), "48 W")


class TestRpm(unittest.TestCase):
    def test_none(self):
        self.assertEqual(rpm(None), EMDASH)

    def test_small(self):
        self.assertEqual(rpm(120), "120 RPM")

    def test_thousands(self):
        self.assertEqual(rpm(1240), "1,240 RPM")

    def test_millions(self):
        self.assertEqual(rpm(1234567), "1,234,567 RPM")


class TestDuration(unittest.TestCase):
    def test_none(self):
        self.assertEqual(duration(None), EMDASH)

    def test_minutes_only(self):
        self.assertEqual(duration(12 * 60), "12m")

    def test_hours_minutes(self):
        self.assertEqual(duration(3 * 3600 + 42 * 60), "3h 42m")

    def test_days_hours(self):
        self.assertEqual(duration(2 * 86400 + 5 * 3600), "2d 5h")

    def test_zero(self):
        self.assertEqual(duration(0), "0m")

    def test_under_minute(self):
        self.assertEqual(duration(59), "0m")


class TestPercent(unittest.TestCase):
    def test_none(self):
        self.assertEqual(percent(None), EMDASH)

    def test_zero(self):
        self.assertEqual(percent(0), "0%")

    def test_rounds(self):
        self.assertEqual(percent(77.3), "77%")

    def test_rounds_up(self):
        self.assertEqual(percent(82.6), "83%")

    def test_hundred(self):
        self.assertEqual(percent(100), "100%")


if __name__ == "__main__":
    unittest.main()
