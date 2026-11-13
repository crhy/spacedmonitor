# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the app table's pure helpers and end flow (no GTK display)."""

import os
import signal
import unittest
from unittest.mock import patch

from spaced_monitor.apptable import meter_fraction
from spaced_monitor.processes import (AppUsage, end_immediate, is_essential,
                                      _sigkill_survivors)


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

    def test_essential_marker_matches_protected_system_processes(self):
        """The red X covers kernel, desktop-session and core-service guards."""
        self.assertTrue(is_essential(_app(pids=(1,))))
        self.assertTrue(is_essential(_app(name="Xorg", pids=(500,))))
        self.assertTrue(is_essential(_app(name="mate-panel", pids=(501,))))
        for name in ("NetworkManager", "wpa_supplicant", "eudevd", "polkitd"):
            self.assertTrue(is_essential(_app(name=name, pids=(503,))), name)
        self.assertFalse(is_essential(_app(name="brave", pids=(502,))))

    def test_monitor_self_guard_is_not_labelled_essential(self):
        """Self-protection is a runtime safety rule, not a system classification."""
        self.assertFalse(is_essential(_app(name="spaced_monitor",
                                           pids=(os.getpid(),))))

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

    def test_sigkill_survivors_kills_same_process(self):
        """A pid still running with the start time recorded at SIGTERM is SIGKILLed."""
        calls = []
        result = _sigkill_survivors([100], lambda p, s: calls.append((p, s)),
                                    {100: "555"}, start_of=lambda pid: "555")
        self.assertFalse(result)
        self.assertEqual(calls, [(100, signal.SIGKILL)])

    def test_sigkill_survivors_skips_dead(self):
        """A pid that is gone is not signalled."""
        calls = []
        result = _sigkill_survivors([100], lambda p, s: calls.append((p, s)),
                                    {100: "555"}, start_of=lambda pid: None)
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_sigkill_survivors_never_kills_a_reused_pid(self):
        """The app exited and the kernel gave its pid to another process."""
        calls = []
        _sigkill_survivors([100], lambda p, s: calls.append((p, s)),
                           {100: "555"}, start_of=lambda pid: "999")
        self.assertEqual(calls, [])

    def test_end_immediate_records_start_times_for_sigkill(self):
        """The scheduled SIGKILL gets the start times taken at SIGTERM."""
        timeouts = []
        end_immediate(_app(pids=(42, 43)), kill=lambda p, s: None, uid=0,
                      timeout_add=lambda ms, fn, *a: timeouts.append(a),
                      start_of=lambda pid: "t%d" % pid)
        self.assertEqual(timeouts[0][2], {42: "t42", 43: "t43"})

    def test_no_sigkill_scheduled_when_already_gone(self):
        """Nothing to follow up when every pid was already gone."""
        timeouts = []
        def gone(pid, sig):
            raise ProcessLookupError
        end_immediate(_app(pids=(7,)), kill=gone, uid=0,
                      timeout_add=lambda *a: timeouts.append(a),
                      start_of=lambda pid: None)
        self.assertEqual(timeouts, [])

    def test_refuses_desktop_session_processes(self):
        """Ending the window manager or the X server would log the user out."""
        for name in ("Xorg", "mate-session", "marco", "compiz", "mate-panel"):
            calls = []
            ok, msg = end_immediate(_app(name=name, pids=(500,)),
                                    kill=lambda p, s: calls.append(p), uid=0)
            self.assertFalse(ok, name)
            self.assertIn("session unusable", msg)
            self.assertEqual(calls, [], name)

    def test_start_time_of_a_real_process(self):
        """The start time parser reads this test's own /proc entry."""
        from spaced_monitor.processes import _start_time
        self.assertTrue(_start_time(os.getpid()).isdigit())
        self.assertIsNone(_start_time(2 ** 22 + 1))


if __name__ == "__main__":
    unittest.main()
