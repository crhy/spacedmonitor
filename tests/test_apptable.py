# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the app table's pure helpers and end flow (no GTK display)."""

import os
import signal
import unittest
from unittest.mock import patch

from spaced_monitor.apptable import meter_fraction
from spaced_monitor.processes import AppUsage, end_immediate, _sigkill_survivors


def _app(name="brave", pids=(10, 11), user="rhy"):
    """Build an AppUsage for helper tests."""
    return AppUsage(name, list(pids), 1.0, 0, 0.0, 0, 0.0, user, "")


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


class TestEndImmediate(unittest.TestCase):
    """end_immediate sends SIGTERM, schedules SIGKILL, refuses protected pids."""

    def test_sigterm_sent(self):
        """All pids receive SIGTERM."""
        calls = []
        fake_kill = lambda pid, sig: calls.append((pid, sig))
        ok, msg = end_immediate(_app(pids=(10, 11)), kill=fake_kill,
                                uid=0)
        self.assertTrue(ok)
        self.assertEqual(calls, [(10, signal.SIGTERM), (11, signal.SIGTERM)])

    def test_sigkill_scheduled(self):
        """timeout_add is called with 2000ms after SIGTERM."""
        timeouts = []
        fake_timeout = lambda ms, fn, *a: timeouts.append((ms, fn, a))
        fake_kill = lambda pid, sig: None
        end_immediate(_app(pids=(42,)), kill=fake_kill, uid=0,
                      timeout_add=fake_timeout)
        self.assertEqual(len(timeouts), 1)
        self.assertEqual(timeouts[0][0], 2000)

    def test_refuses_pid_1(self):
        """Protected pid 1 is never touched."""
        calls = []
        fake_kill = lambda pid, sig: calls.append((pid, sig))
        ok, msg = end_immediate(_app(pids=(1, 10)), kill=fake_kill, uid=0)
        self.assertFalse(ok)
        self.assertIn("protected", msg)
        self.assertEqual(calls, [])

    def test_refuses_pid_2(self):
        """Protected pid 2 is never touched."""
        ok, msg = end_immediate(_app(pids=(2,)), kill=lambda p, s: None, uid=0)
        self.assertFalse(ok)
        self.assertIn("protected", msg)

    def test_refuses_own_pid(self):
        """The caller's own pid is protected."""
        import os
        ok, msg = end_immediate(_app(pids=(os.getpid(),)),
                                kill=lambda p, s: None, uid=0)
        self.assertFalse(ok)
        self.assertIn("protected", msg)

    def test_refuses_other_user(self):
        """Another user's app needs an administrator."""
        ok, msg = end_immediate(_app(pids=(99,), user="root"),
                                kill=lambda p, s: None, uid=os.getuid())
        self.assertFalse(ok)
        self.assertIn("administrator", msg)

    def test_permission_error_refuses(self):
        """PermissionError during kill gives the refusal message."""
        def deny(pid, sig):
            raise PermissionError
        ok, msg = end_immediate(_app(pids=(55,)), kill=deny, uid=0)
        self.assertFalse(ok)
        self.assertIn("administrator", msg)

    def test_already_gone(self):
        """ProcessLookupError on all pids means already ended."""
        def gone(pid, sig):
            raise ProcessLookupError
        ok, msg = end_immediate(_app(pids=(77,)), kill=gone, uid=0)
        self.assertTrue(ok)
        self.assertIn("already gone", msg)

    def test_sigkill_survivors_kills_alive(self):
        """_sigkill_survivors SIGKILLs pids that are still alive."""
        calls = []
        fake_kill = lambda pid, sig: calls.append((pid, sig))
        with patch("os.kill", side_effect=lambda p, s: None):
            result = _sigkill_survivors([100], fake_kill)
        self.assertFalse(result)
        self.assertEqual(calls, [(100, signal.SIGKILL)])

    def test_sigkill_survivors_skips_dead(self):
        """_sigkill_survivors skips pids that are already gone."""
        calls = []
        fake_kill = lambda pid, sig: calls.append((pid, sig))
        def lookup_fail(p, s):
            raise ProcessLookupError
        with patch("os.kill", side_effect=lookup_fail):
            result = _sigkill_survivors([100], fake_kill)
        self.assertFalse(result)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
