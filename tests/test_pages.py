# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the Processes and Hardware page helpers."""

import unittest

from spaced_monitor.collect import (Fan, Filesystem, GpuExtra, Interface,
                                    Temperature, real_filesystem)
from spaced_monitor.pages import (
    child_rows, count_summary, sort_apps, sort_indicator,
    core_meters, core_summary, filesystem_rows, freq_line, gpu_extra_line,
    fan_rows, interface_rows, sensor_rows, temp_colour_class, visible_apps,
)
from spaced_monitor.processes import AppUsage, ProcUsage


def app(name, cpu=0.0, rss=0, gpu=0.0, disk=0.0, user="rhy",
        pids=(), icon="", children=()):
    """Build one AppUsage for helper tests."""
    return AppUsage(name, list(pids) or [1], cpu, rss, gpu, 0, disk,
                    user, icon, list(children))


class SortTests(unittest.TestCase):
    """Column sorting and the header arrow."""

    def test_sort_apps_defaults_to_cpu_descending(self):
        """No column given: biggest CPU user first."""
        apps = [app("a", cpu=10.0), app("b", cpu=40.0), app("c", cpu=25.0)]
        self.assertEqual([a.name for a in sort_apps(apps)], ["b", "c", "a"])

    def test_sort_apps_ascending(self):
        """reverse=False puts the smallest value first."""
        apps = [app("a", cpu=10.0), app("b", cpu=40.0)]
        self.assertEqual([a.name for a in sort_apps(apps, "cpu", False)],
                         ["a", "b"])

    def test_sort_apps_by_ram_then_disk(self):
        """Byte columns sort numerically, not as strings."""
        apps = [app("a", rss=500), app("b", rss=9000), app("c", rss=100)]
        self.assertEqual([a.name for a in sort_apps(apps, "ram")],
                         ["b", "a", "c"])
        apps = [app("a", disk=5.0), app("b", disk=90.0)]
        self.assertEqual([a.name for a in sort_apps(apps, "disk")], ["b", "a"])

    def test_app_column_is_always_alphabetical(self):
        """The App column ignores direction: it is always A-Z."""
        apps = [app("brave"), app("alpha"), app("strata")]
        self.assertEqual([a.name for a in sort_apps(apps, "app", False)],
                         ["alpha", "brave", "strata"])
        self.assertEqual([a.name for a in sort_apps(apps, "app", True)],
                         ["alpha", "brave", "strata"])

    def test_unknown_column_falls_back_to_cpu(self):
        """A column we never offer must not crash the table."""
        apps = [app("a", cpu=1.0), app("b", cpu=9.0)]
        self.assertEqual([a.name for a in sort_apps(apps, "nope")], ["b", "a"])

    def test_sort_indicator_arrows(self):
        """Descending is ▲, ascending is ▼, other headers stay plain."""
        self.assertEqual(sort_indicator("cpu", "cpu", True), "\u25b2")
        self.assertEqual(sort_indicator("cpu", "cpu", False), "\u25bc")
        self.assertEqual(sort_indicator("ram", "cpu", True), "")

    def test_count_summary(self):
        """'N apps · M processes' counts apps and their pids."""
        apps = [app("a", pids=[1, 2, 3]), app("b", pids=[4])]
        self.assertEqual(count_summary(apps), "2 apps \u00b7 4 processes")
        self.assertEqual(count_summary([]), "0 apps \u00b7 0 processes")


class ChildRowTests(unittest.TestCase):
    """Expanded rows under an app."""

    def test_child_rows_formats_each_process(self):
        """Each child becomes pid, name, cpu, ram strings."""
        kids = [ProcUsage(4242, "strata", 12.5, int(1.5 * 1024**3)),
                ProcUsage(99, "worker", 0.0, 0)]
        rows = child_rows(app("strata", children=kids))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "4242")
        self.assertEqual(rows[0][1], "strata")
        self.assertIn("12", rows[0][2])
        self.assertEqual(rows[1][0], "99")

    def test_child_rows_empty_when_no_children(self):
        """An app with no children expands to nothing."""
        self.assertEqual(child_rows(app("solo")), [])


class VisibleAppsTests(unittest.TestCase):
    """Search, scope and sort combined."""

    def setUp(self):
        """One app per scope bucket."""
        self.apps = [app("brave", cpu=10.0, user="rhy"),
                     app("nginx", cpu=30.0, user="root"),
                     app("firefox", cpu=20.0, user="rhy")]

    def test_scope_all_keeps_everything(self):
        """All shows every app, sorted by the chosen column."""
        names = [a.name for a in visible_apps(self.apps, "", "all", "rhy",
                                              "cpu", True)]
        self.assertEqual(names, ["nginx", "firefox", "brave"])

    def test_scope_system_keeps_only_root_services(self):
        """System is the root-owned services."""
        names = [a.name for a in visible_apps(self.apps, "", "system", "rhy",
                                              "cpu", True)]
        self.assertEqual(names, ["nginx"])

    def test_scope_mine_keeps_only_my_apps(self):
        """Mine filters on the given user."""
        names = [a.name for a in visible_apps(self.apps, "", "mine", "rhy",
                                              "app", True)]
        self.assertEqual(names, ["brave", "firefox"])

    def test_search_narrows_then_sorts(self):
        """Search text and sort work together."""
        names = [a.name for a in visible_apps(self.apps, "fire", "all", "rhy",
                                              "cpu", True)]
        self.assertEqual(names, ["firefox"])

    def test_search_and_system_do_not_conflict(self):
        """A search that matches nothing in scope gives an empty list."""
        self.assertEqual(visible_apps(self.apps, "nginx", "mine", "rhy",
                                      "cpu", True), [])

    def test_empty_search_keeps_order(self):
        """Empty text is not a filter."""
        self.assertEqual(len(visible_apps(self.apps, "", "all", "rhy",
                                          "cpu", True)), 3)


class TemperatureTests(unittest.TestCase):
    """Sensor colour coding."""

    def test_colour_bands(self):
        """Green below 60, orange below 80, red at or above 80."""
        self.assertEqual(temp_colour_class(21.0), "temp-cool")
        self.assertEqual(temp_colour_class(59.9), "temp-cool")
        self.assertEqual(temp_colour_class(60.0), "temp-warm")
        self.assertEqual(temp_colour_class(79.9), "temp-warm")
        self.assertEqual(temp_colour_class(80.0), "temp-hot")
        self.assertEqual(temp_colour_class(105.0), "temp-hot")

    def test_missing_temperature_is_neutral(self):
        """A sensor that has not reported yet gets no colour."""
        self.assertEqual(temp_colour_class(None), "value")

    def test_sensor_rows_pair_value_and_colour(self):
        """One row per reading: chip, label, text, class."""
        temps = [Temperature("cpu", "core", 58.0),
                 Temperature("gpu", "hotspot", 86.0)]
        rows = sensor_rows(temps)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "cpu")
        self.assertEqual(rows[0][1], "core")
        self.assertEqual(rows[0][3], "temp-cool")
        self.assertEqual(rows[1][3], "temp-hot")
        self.assertEqual(rows[1][2], "187 °F")

    def test_sensor_rows_empty(self):
        """No sensors (no sensors.yaml) is not an error."""
        self.assertEqual(sensor_rows([]), [])


class CoreMeterTests(unittest.TestCase):
    """Per-core meters laid out into rows."""

    def test_core_meters_row_of_eight(self):
        """16 cores become two rows of eight, labelled C0..C15."""
        rows = core_meters([10.0] * 16)
        self.assertEqual([len(r) for r in rows], [8, 8])
        self.assertEqual(rows[0][0][0], "C0")
        self.assertEqual(rows[1][-1][0], "C15")

    def test_core_meters_clamp_fractions(self):
        """Fractions stay inside 0..1 whatever the percent is."""
        rows = core_meters([0.0, 50.0, 100.0, 150.0, -20.0], columns=8)
        values = [cell[1] for row in rows for cell in row]
        self.assertEqual(values, [0.0, 0.5, 1.0, 1.0, 0.0])

    def test_core_meters_odd_counts_and_empty(self):
        """Ragged core counts and no cores at all."""
        self.assertEqual([len(r) for r in core_meters([5.0] * 5, 8)], [5])
        self.assertEqual([len(r) for r in core_meters([5.0] * 5, 2)],
                         [2, 2, 1])
        self.assertEqual(core_meters([]), [])

    def test_core_meters_columns_never_zero(self):
        """columns=0 must not produce an infinite loop or empty rows."""
        rows = core_meters([1.0, 2.0], columns=0)
        self.assertEqual([len(r) for r in rows], [1, 1])


class StorageNetworkTests(unittest.TestCase):
    """Filesystem and interface rows."""

    def test_filesystem_rows_compute_fraction(self):
        """Mount, type, 'used / total' and a 0..1 bar."""
        files = [Filesystem("/", "ext4", int(48 * 1024**3),
                           int(240 * 1024**3)),
                 Filesystem("/home", "xfs", int(9 * 1024**3), int(10 * 1024**3))]
        rows = filesystem_rows(files)
        self.assertEqual(rows[0][0], "/")
        self.assertEqual(rows[0][1], "ext4")
        self.assertAlmostEqual(rows[0][3], 0.2, places=6)
        self.assertLess(rows[1][3], 1.0)
        self.assertGreater(rows[1][3], 0.89)

    def test_filesystem_rows_handle_unknown_sizes(self):
        """A filesystem with no size data draws an empty bar."""
        rows = filesystem_rows([Filesystem("/x", "tmpfs", None, None)])
        self.assertEqual(rows[0][3], 0.0)
        self.assertEqual(rows[0][2], "\u2014")

    def test_filesystem_rows_empty(self):
        """Filtered-away pseudo filesystems leave the card empty."""
        self.assertEqual(filesystem_rows([]), [])

    def test_interface_rows_show_rates(self):
        """One row per interface with download and upload rates."""
        ifaces = [Interface("eth0", "192.168.4.1", 50 * 1024**2, 1024**2),
                  Interface("wlan0", None, 0.0, 0.0)]
        rows = interface_rows(ifaces)
        self.assertEqual(rows[0][0], "eth0")
        self.assertEqual(rows[0][1], "192.168.4.1")
        self.assertEqual(rows[1][1], "\u2014")

    def test_interface_rows_empty(self):
        """A host with no managed interfaces is fine."""
        self.assertEqual(interface_rows([]), [])


class GpuExtraTests(unittest.TestCase):
    """The nvidia-smi driver and PCIe line."""

    def test_gpu_extra_line_full(self):
        """Driver, generation and width on one muted line."""
        extra = GpuExtra(driver="5611.5", link_gen="4", link_width="16")
        self.assertEqual(gpu_extra_line(extra),
                         "driver 5611.5 \u00b7 PCIe gen 4 \u00b7 width 16")

    def test_gpu_extra_line_partial(self):
        """Missing PCIe width still shows what we have."""
        self.assertEqual(gpu_extra_line(GpuExtra("5611.5", "4", None)),
                         "driver 5611.5 \u00b7 PCIe gen 4")
        self.assertEqual(gpu_extra_line(GpuExtra(None, None, None)), "")

    def test_gpu_extra_line_none(self):
        """No NVIDIA card: no line at all."""
        self.assertEqual(gpu_extra_line(None), "")


class FanRowTests(unittest.TestCase):
    """Fans and the CPU frequency line."""

    def test_fan_rows_label_and_rpm(self):
        """Each fan becomes a label plus a formatted rpm."""
        fans = [Fan(label="fan1", rpm=1240), Fan(label="cpu", rpm=0)]
        self.assertEqual(fan_rows(fans), [("fan1", "1,240 RPM"),
                                          ("cpu", "0 RPM")])

    def test_fan_rows_empty(self):
        """A host with no readable fans shows nothing."""
        self.assertEqual(fan_rows([]), [])

    def test_core_summary_counts_cores(self):
        """The core count comes from the per-core sample."""
        self.assertEqual(core_summary([1.0] * 16), "16 cores")
        self.assertEqual(core_summary([]), "")

    def test_freq_line_current_min_max(self):
        """Current, slowest and fastest frequency on one line."""
        line = freq_line(4600.0, 4200.0, 4800.0)
        self.assertEqual(line, "freq 4.6 GHz / 4.2 GHz / 4.8 GHz")

    def test_freq_line_unknown(self):
        """No frequency data gives an empty line, not 'None'."""
        self.assertEqual(freq_line(None, None, None), "")
        self.assertEqual(freq_line(4600.0, None, None),
                         "freq 4.6 GHz / \u2014 / \u2014")


class FilesystemFilterTests(unittest.TestCase):
    """Which mounts the Storage card is allowed to show."""

    def test_real_filesystem_accepts_real_mounts(self):
        """Ordinary ext4/xfs/btrfs mounts are shown."""
        for mount in ("/", "/home", "/var/lib/postgres", "/data"):
            self.assertTrue(real_filesystem("ext4", mount), msg=mount)

    def test_real_filesystem_skips_pseudo_types(self):
        """squashfs, tmpfs and overlay never appear."""
        for fstype in ("squashfs", "tmpfs", "overlay", "proc", "nsfs"):
            self.assertFalse(real_filesystem(fstype, "/anything"), msg=fstype)

    def test_real_filesystem_skips_runtime_mounts(self):
        """snap and flatpak runtime mounts are filtered by path prefix."""
        for mount in ("/snap/foo/123", "/var/lib/snap/aux", "/var/lib/flatpak",
                      "/run/user/1000", "/tmp/x"):
            self.assertFalse(real_filesystem("ext4", mount), msg=mount)

    def test_real_filesystem_does_not_over_filter(self):
        """'/snapshot-thing' is not '/snap' and must survive."""
        self.assertTrue(real_filesystem("ext4", "/snapshot-data"))
        self.assertTrue(real_filesystem("ext4", "/tmpdata"))
        self.assertTrue(real_filesystem("ext4", "/var/lib/snapd/snaps"))


if __name__ == "__main__":
    unittest.main()
