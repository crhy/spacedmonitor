# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the app table's pure helpers (no GTK display needed)."""

import unittest

from spaced_monitor.apptable import end_outcome, end_question, meter_fraction
from spaced_monitor.processes import AppUsage


def _app(name="brave", pids=(10, 11)):
    """Build an AppUsage for helper tests."""
    return AppUsage(name, list(pids), 1.0, 0, 0.0, 0, 0.0, "rhy", "")


class TestMeterFraction(unittest.TestCase):
    """meter_fraction clamps value/max into [0, 1] and honours cap."""

    def test_basic(self):
        assert meter_fraction(50, 100) == 0.5

    def test_clamp_high(self):
        assert meter_fraction(150, 100) == 1.0

    def test_clamp_low(self):
        assert meter_fraction(-5, 100) == 0.0

    def test_zero_max(self):
        assert meter_fraction(10, 0) == 0.0

    def test_cap(self):
        assert meter_fraction(30, 100, cap=0.2) == 0.2

    def test_cap_not_raised(self):
        assert meter_fraction(10, 100, cap=0.2) == 0.1


class TestEndQuestion(unittest.TestCase):
    """end_question returns the dialog title and a process-count detail."""

    def test_plural(self):
        q, d = end_question(_app(pids=(10, 11, 12)))
        assert q == "End Brave?" and d == "3 processes"

    def test_singular(self):
        q, d = end_question(_app(pids=(10,)))
        assert d == "1 process"


class TestEndOutcome(unittest.TestCase):
    """end_outcome offers force only after a normal (non-forced) failure."""

    def test_success(self):
        assert end_outcome(True, "done", False) == ("done", False)

    def test_fail_normal_offers_force(self):
        assert end_outcome(False, "no", False) == ("no", True)

    def test_fail_forced_no_second_force(self):
        assert end_outcome(False, "no", True) == ("no", False)


if __name__ == "__main__":
    unittest.main()
