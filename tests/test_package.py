import unittest

import spaced_monitor


class Package(unittest.TestCase):
    def test_version(self):
        self.assertRegex(spaced_monitor.__version__, r"^\d+\.\d+\.\d+$")
