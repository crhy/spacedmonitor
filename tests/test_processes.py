# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for spaced_monitor.processes (grouping, GPU, icons, ending)."""

import os
import signal
import types
import unittest

from spaced_monitor import processes
from spaced_monitor.processes import (
    AppUsage, ProcessSampler, display_name, icon_for, filter_apps, end_app,
    _gpu_mem_by_pid, _gpu_sm_by_pid,
)


class NoSuchProcess(Exception):
    pass


class AccessDenied(Exception):
    pass


class ZombieProcess(Exception):
    pass


class FakeProcess:
    """A psutil.Process stand-in with settable readings."""

    def __init__(self, pid, name="x", user="rhy", cpu=0.0, rss=0, ppid=1,
                 exe="/bin/x", read=0, write=0, io_raises=None, name_raises=None,
                 cmdline=None):
        self.pid = pid
        self._cmdline = cmdline or []
        self._name = name
        self._user = user
        self._cpu = cpu
        self._rss = rss
        self._ppid = ppid
        self._exe = exe
        self.read = read
        self.write = write
        self._io_raises = io_raises
        self._name_raises = name_raises

    def name(self):
        if self._name_raises:
            raise self._name_raises
        return self._name

    def username(self):
        return self._user

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_info(self):
        return types.SimpleNamespace(rss=self._rss)

    def ppid(self):
        return self._ppid

    def exe(self):
        return self._exe or ""

    def cmdline(self):
        return self._cmdline

    def io_counters(self):
        if self._io_raises:
            raise self._io_raises
        return types.SimpleNamespace(read_bytes=self.read, write_bytes=self.write)


class FakePs:
    """A psutil stand-in: pids(), Process(), cpu_count() and the error types."""

    NoSuchProcess = NoSuchProcess
    AccessDenied = AccessDenied
    ZombieProcess = ZombieProcess

    def __init__(self, procs, cpu_n=4):
        self._by_pid = {p.pid: p for p in procs}
        self._cpu_n = cpu_n

    def pids(self):
        return list(self._by_pid)

    def Process(self, pid):
        p = self._by_pid.get(pid)
        if p is None:
            raise self.NoSuchProcess(pid)
        return p

    def cpu_count(self):
        return self._cpu_n


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


PMON = (
    "#    gpu    pid    type    sm    mem\n"
    "    0      14679    C     83     26\n"
    "    0      7050     G      -      -\n"
)
COMPUTE = "14679, 15444\n"


def gpu_runner(pmon=PMON, compute=COMPUTE):
    """Fake nvidia-smi runner: pmon text for pmon, compute text otherwise."""
    def run(cmd, timeout=None):
        if "pmon" in cmd:
            return pmon
        return compute
    return run


class TestSampler(unittest.TestCase):
    def setUp(self):
        import unittest.mock
        self._pm = unittest.mock.patch("spaced_monitor.processes._nvml_gpu_mem", return_value=None)
        self._ps = unittest.mock.patch("spaced_monitor.processes._nvml_gpu_sm", return_value=None)
        self._pm.start()
        self._ps.start()
        self.addCleanup(self._pm.stop)
        self.addCleanup(self._ps.stop)

    def _sampler(self, procs, cpu_n=4, gpu_run=None, clock=None):
        return ProcessSampler(ps=FakePs(procs, cpu_n),
                              clock=clock or FakeClock(0.0),
                              gpu_run=gpu_run or (lambda cmd, timeout=None: ""))

    def test_groups_same_name(self):
        procs = [FakeProcess(10, name="brave"), FakeProcess(11, name="brave"),
                 FakeProcess(12, name="brave")]
        rows = self._sampler(procs).sample()
        assert len(rows) == 1
        assert sorted(rows[0].pids) == [10, 11, 12]
        assert rows[0].name == "brave" and rows[0].user == "rhy"

    def test_interpreter_scripts_are_separate_apps(self):
        """Two python3 programs are two apps: one red X must not end both."""
        procs = [FakeProcess(30, name="python3", cmdline=["/usr/bin/python3", "/opt/voxa/voxa.py"]),
                 FakeProcess(31, name="python3", cmdline=["/usr/bin/python3", "-m", "spaced_monitor"]),
                 FakeProcess(32, name="python3", cmdline=["/usr/bin/python3", "/opt/voxa/voxa.py", "--x"])]
        rows = self._sampler(procs).sample()
        by_pids = sorted(sorted(r.pids) for r in rows)
        assert by_pids == [[30, 32], [31]], by_pids
        names = sorted(display_name(r.name, exe=r.exe, cmdline=r.cmdline) for r in rows)
        assert names == ["Spaced_monitor", "Voxa"], names

    def test_interpreter_display_names(self):
        """The script, not the interpreter, names the app."""
        assert display_name("python3", cmdline=["/usr/bin/python3", "/x/app.py"]) == "App"
        assert display_name("python3.14", cmdline=["python3.14", "-m", "pkg.main"]) == "Pkg"
        assert display_name("bash", cmdline=["bash", "/home/u/run-all.sh"]) == "Run-all"
        assert display_name("python3", cmdline=["/usr/bin/python3"]) == "Python"

    def test_inline_commands_are_separate_apps(self):
        """Each `bash -c <command>` is its own program."""
        procs = [FakeProcess(40, name="bash", cmdline=["bash", "-c", "sleep 9"]),
                 FakeProcess(41, name="bash", cmdline=["bash", "-c", "make all"])]
        assert len(self._sampler(procs).sample()) == 2

    def test_static_fields_read_once_per_pid(self):
        """name/user/exe/cmdline do not change: one read per pid, not per sample."""
        calls = []

        class Counting(FakeProcess):
            def name(self):
                calls.append(self.pid)
                return super().name()

        a, b = Counting(50, name="brave"), Counting(51, name="mpv")
        ps = FakePs([a, b])
        sampler = ProcessSampler(ps=ps, clock=FakeClock(0.0),
                                 gpu_run=lambda cmd, timeout=None: "")
        for _ in range(3):
            sampler.sample()
        assert sorted(calls) == [50, 51], calls
        del ps._by_pid[51]                     # mpv exits
        sampler.sample()
        assert 51 not in sampler._static and 51 not in sampler._procs

    def test_per_user_split(self):
        procs = [FakeProcess(20, name="worker", user="rhy"),
                 FakeProcess(21, name="worker", user="root")]
        rows = self._sampler(procs).sample()
        assert len(rows) == 2
        assert {r.user for r in rows} == {"rhy", "root"}

    def test_cpu_is_machine_share(self):
        procs = [FakeProcess(10, cpu=10.0), FakeProcess(11, cpu=10.0)]
        rows = self._sampler(procs, cpu_n=4).sample()
        assert rows[0].cpu_percent == 5.0

    def test_rss_summed(self):
        procs = [FakeProcess(10, rss=1000), FakeProcess(11, rss=2000)]
        rows = self._sampler(procs).sample()
        assert rows[0].rss == 3000

    def test_sorted_by_cpu_desc(self):
        procs = [FakeProcess(10, name="a", cpu=1.0), FakeProcess(11, name="b", cpu=9.0)]
        rows = self._sampler(procs).sample()
        assert [r.name for r in rows] == ["b", "a"]

    def test_disk_rate_over_two_samples(self):
        clock = FakeClock(0.0)
        p = FakeProcess(10, name="dd", read=100, write=0)
        sampler = self._sampler([p], clock=clock)
        first = sampler.sample()
        assert first[0].disk_bps == 0.0
        p.read = 1100
        clock.t = 2.0
        second = sampler.sample()
        assert second[0].disk_bps == 500.0

    def test_io_denied_is_zero(self):
        p = FakeProcess(10, name="dd", io_raises=AccessDenied())
        rows = self._sampler([p]).sample()
        assert rows[0].disk_bps == 0.0

    def test_kernel_thread_pid2(self):
        procs = [FakeProcess(2, name="init"), FakeProcess(10, name="keep")]
        rows = self._sampler(procs).sample()
        assert [r.name for r in rows] == ["keep"]

    def test_kernel_thread_no_exe_ppid2(self):
        procs = [FakeProcess(30, name="thread", exe="", ppid=2),
                 FakeProcess(31, name="real", exe="/bin/x", ppid=2)]
        rows = self._sampler(procs).sample()
        assert [r.name for r in rows] == []

    def test_vanished_process(self):
        procs = [FakeProcess(10, name="gone", name_raises=NoSuchProcess(10)),
                 FakeProcess(11, name="ok")]
        rows = self._sampler(procs).sample()
        assert [r.name for r in rows] == ["ok"]

    def test_pid_listed_but_process_gone(self):
        ps = FakePs([FakeProcess(11, name="ok")])
        ps.pids = lambda: [11, 99]
        rows = ProcessSampler(ps=ps, gpu_run=lambda cmd, timeout=None: "").sample()
        assert [r.name for r in rows] == ["ok"]

    def test_gpu_percent_and_mem(self):
        procs = [FakeProcess(14679, name="strata")]
        rows = self._sampler(procs, gpu_run=gpu_runner()).sample()
        assert rows[0].gpu_percent == 83.0
        assert rows[0].gpu_mem == 15444 * 1024 * 1024

    def test_gpu_dash_is_zero(self):
        procs = [FakeProcess(7050, name="compiz")]
        rows = self._sampler(procs, gpu_run=gpu_runner()).sample()
        assert rows[0].gpu_percent == 0.0 and rows[0].gpu_mem == 0

    def test_gpu_failure_is_zero(self):
        def run(cmd, timeout=None):
            raise FileNotFoundError(2, "nvidia-smi")
        rows = self._sampler([FakeProcess(10, name="x")], gpu_run=run).sample()
        assert rows[0].gpu_percent == 0.0 and rows[0].gpu_mem == 0


class TestGpuParsing(unittest.TestCase):
    def setUp(self):
        import unittest.mock
        self._pm = unittest.mock.patch("spaced_monitor.processes._nvml_gpu_mem", return_value=None)
        self._ps = unittest.mock.patch("spaced_monitor.processes._nvml_gpu_sm", return_value=None)
        self._pm.start()
        self._ps.start()
        self.addCleanup(self._pm.stop)
        self.addCleanup(self._ps.stop)

    def test_mem_csv(self):
        out = _gpu_mem_by_pid(run=lambda cmd, timeout=None: "111, 2048\n222, 512\n")
        assert out == {111: 2048 * 1024 * 1024, 222: 512 * 1024 * 1024}

    def test_mem_junk_skipped(self):
        assert _gpu_mem_by_pid(run=lambda cmd, timeout=None: "abc, xyz\n") == {}

    def test_mem_failure(self):
        def run(cmd, timeout=None):
            raise FileNotFoundError(2, "nvidia-smi")
        assert _gpu_mem_by_pid(run=run) == {}

    def test_sm_table(self):
        out = _gpu_sm_by_pid(run=lambda cmd, timeout=None: PMON)
        assert out == {14679: 83.0, 7050: 0.0}

    def test_sm_failure(self):
        import subprocess
        def run(cmd, timeout=None):
            raise subprocess.TimeoutExpired(cmd, 2)
        assert _gpu_sm_by_pid(run=run) == {}


class TestDisplayName(unittest.TestCase):
    def test_capitalise(self):
        assert display_name("brave") == "Brave"

    def test_strip_suffixes(self):
        assert display_name("foo.bin") == "Foo"
        assert display_name("foo-bin") == "Foo"
        assert display_name("foo-wrapped") == "Foo"

    def test_known_map(self):
        assert display_name("llama-server") == "llama-server"
        assert display_name("Xorg") == "System display (Xorg)"
        assert display_name("python3") == "Python"


class TestIcon(unittest.TestCase):
    def setUp(self):
        processes._icon_cache.clear()

    def _dir(self, *files):
        import tempfile
        tmp = tempfile.TemporaryDirectory(dir="build")
        self.addCleanup(tmp.cleanup)
        for fn, text in files:
            with open(os.path.join(tmp.name, fn), "w") as f:
                f.write(text)
        return tmp.name

    def test_exec_match(self):
        d = self._dir(("brave.desktop", "[Desktop Entry]\nExec=/usr/bin/brave %U\nIcon=brave-icon\n"))
        assert icon_for("brave", dirs=[d]) == "brave-icon"

    def test_wmclass_match(self):
        d = self._dir(("x.desktop", "StartupWMClass=Brave\nIcon=wm-icon\n"))
        assert icon_for("brave", dirs=[d]) == "wm-icon"

    def test_filename_match(self):
        d = self._dir(("org.foo.bar.desktop", "Icon=fn-icon\n"))
        assert icon_for("org.foo.bar", dirs=[d]) == "fn-icon"

    def test_fallback(self):
        d = self._dir(("brave.desktop", "Exec=/usr/bin/brave\nIcon=brave-icon\n"))
        assert icon_for("nope", dirs=[d]) == "application-x-executable"

    def test_cached(self):
        d = self._dir(("brave.desktop", "Exec=/usr/bin/brave\nIcon=brave-icon\n"))
        icon_for("brave", dirs=[d])
        assert processes._icon_cache.get("brave") == "brave-icon"


class TestFilter(unittest.TestCase):
    def _apps(self):
        return [
            AppUsage("brave", [1], 1.0, 0, 0.0, 0, 0.0, "rhy", ""),
            AppUsage("Xorg", [2], 1.0, 0, 0.0, 0, 0.0, "root", ""),
        ]

    def test_text_match_display(self):
        rows = filter_apps(self._apps(), text="org")
        assert [a.name for a in rows] == ["Xorg"]

    def test_scope_mine(self):
        rows = filter_apps(self._apps(), scope="mine", me="rhy")
        assert [a.name for a in rows] == ["brave"]

    def test_no_filter(self):
        assert len(filter_apps(self._apps())) == 2


class TestEndApp(unittest.TestCase):
    def _app(self, name="brave", pids=(10, 11), user="rhy"):
        return AppUsage(name, list(pids), 1.0, 0, 0.0, 0, 0.0, user, "")

    def test_success_sigterm(self):
        calls = []
        ok, msg = end_app(self._app(), kill=lambda p, s: calls.append((p, s)),
                          me=999, uid=os.getuid())
        assert ok and calls == [(10, signal.SIGTERM), (11, signal.SIGTERM)]

    def test_force_sigkill(self):
        calls = []
        end_app(self._app(), force=True, kill=lambda p, s: calls.append(s),
                me=999, uid=os.getuid())
        assert all(s == signal.SIGKILL for s in calls)

    def test_refuse_pid1(self):
        ok, msg = end_app(self._app(pids=(1,)), kill=lambda p, s: None,
                          me=999, uid=os.getuid())
        assert not ok and "protected" in msg

    def test_refuse_pid2(self):
        ok, _ = end_app(self._app(pids=(2,)), kill=lambda p, s: None,
                        me=999, uid=os.getuid())
        assert not ok

    def test_refuse_own_pid(self):
        ok, _ = end_app(self._app(pids=(999,)), kill=lambda p, s: None,
                        me=999, uid=os.getuid())
        assert not ok

    def test_refuse_other_user(self):
        ok, msg = end_app(self._app(user="root"), kill=lambda p, s: None,
                          me=999, uid=os.getuid())
        assert not ok and "belongs to root" in msg and "administrator" in msg

    def test_root_can_end(self):
        calls = []
        ok, _ = end_app(self._app(user="root"), kill=lambda p, s: calls.append(p),
                        me=999, uid=0)
        assert ok and calls == [10, 11]

    def test_permission_error(self):
        def kill(p, s):
            raise PermissionError(1, "no")
        ok, msg = end_app(self._app(user="rhy"), kill=kill, me=999, uid=0)
        assert not ok and "belongs to rhy" in msg

    def test_process_lookup_ok(self):
        def kill(p, s):
            raise ProcessLookupError()
        ok, msg = end_app(self._app(), kill=kill, me=999, uid=os.getuid())
        assert ok and "already gone" in msg


if __name__ == "__main__":
    unittest.main()
