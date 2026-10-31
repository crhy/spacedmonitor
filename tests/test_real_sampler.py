# SPDX-License-Identifier: GPL-3.0-or-later
"""The real collectors must run on any Linux machine without raising (no fakes)."""
import time
import unittest

from spaced_monitor import collect, processes


class RealSampler(unittest.TestCase):
    def test_two_real_samples(self):
        sampler = collect.Sampler()
        sampler.sample()
        time.sleep(0.2)
        snap = sampler.sample()
        self.assertGreater(snap.memory.total, 0)
        self.assertGreaterEqual(snap.cpu.percent, 0)

    def test_real_process_sample(self):
        apps = processes.ProcessSampler().sample()
        self.assertTrue(apps)
