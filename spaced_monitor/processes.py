# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-app process usage and safe ending of an app."""

from __future__ import annotations

import contextlib
import os
import pwd
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence


@dataclass
class ProcUsage:
    """One process, as shown under an expanded app row."""
    pid: int
    name: str
    cpu_percent: float
    rss: int
    exe: str = ""
    cmdline: list = None  # type: ignore[assignment]


@dataclass
class AppUsage:
    """One app: grouped processes and their combined usage."""
    name: str
    pids: list[int]
    cpu_percent: float
    rss: int
    gpu_percent: float
    gpu_mem: int
    disk_bps: float
    user: str
    icon: str
    children: list = field(default_factory=list)
    exe: str = ""
    cmdline: list = None  # type: ignore[assignment]


# Known process names that need a special label (not capitalised or renamed).
_NAME_MAP = {
    "llama-server": "llama-server",
    "Xorg": "System display (Xorg)",
    "python3": "Python",
    "claude": "Claude Code",
    "pi": "pi (coding agent)",
    "strata": "Strata",
}

_GENERIC_INTERPRETERS = frozenset(("python3", "python", "node", "java", "bash",
                                   "sh", "perl", "ruby"))
# Ending one of these ends the desktop session (or the display), not an app.
_SESSION_CRITICAL = frozenset((
    "Xorg", "Xwayland", "X", "mate-session", "marco", "compiz", "mate-panel",
    "lightdm", "slim", "elogind", "elogind-daemon", "dbus-daemon", "login"))
_SKIP_DIRS = frozenset(("versions", "bin", "lib", ".local", "share", ""))


def _is_version(name: str) -> bool:
    """True when name is only digits and dots (e.g. '2.1.287')."""
    return bool(name) and all(c.isdigit() or c == "." for c in name)


def _is_interpreter(name: str) -> bool:
    """True for python3, python3.14, node, bash ...: the script is the app."""
    low = name.lower()
    if low.startswith("python") and _is_version(low[6:]):
        return True
    return low in _GENERIC_INTERPRETERS


def _script_of(cmdline: list) -> str:
    """The script or module an interpreter runs ('' when none): its identity."""
    args = list(cmdline or [])[1:]
    for i, arg in enumerate(args):
        if arg == "-m" and i + 1 < len(args):
            return "-m " + args[i + 1]
        if arg == "-c":
            return "-c " + (args[i + 1] if i + 1 < len(args) else "")
        if not arg.startswith("-"):
            return arg
    return ""


def _group_key(name: str, user: str, cmdline: list) -> tuple[str, str]:
    """Processes are grouped by name and user; interpreters also by script."""
    if _is_interpreter(name):
        return (name + "\0" + _script_of(cmdline), user)
    return (name, user)


def _name_from_exe(exe: str) -> str:
    """Derive app name from exe path's parent dirs, skipping generic names."""
    if not exe:
        return ""
    parts = exe.replace("\\", "/").split("/")
    # Walk from the basename's parent upward.
    for part in reversed(parts[:-1]):
        if part and part not in _SKIP_DIRS:
            return part[0].upper() + part[1:]
    return ""


def _name_from_cmdline(cmdline: list) -> str:
    """Derive app name from a script path in cmdline (e.g. /x/y/app.py -> App)."""
    script = _script_of(cmdline)
    if script.startswith("-m "):
        script = script[3:].split(".")[0]
    for arg in ([script] if script and not script.startswith("-c") else []):
        base = os.path.basename(arg)
        stem = os.path.splitext(base)[0]
        if stem and not stem.startswith("-") and not _is_version(stem):
            return stem[0].upper() + stem[1:]
    return ""


def display_name(name: str, exe: str = "", cmdline: list = None) -> str:
    """Turn a raw process name into a nicer label."""
    if _is_interpreter(name):
        derived = _name_from_cmdline(cmdline or [])
        if derived:
            return derived
    if name in _NAME_MAP:
        return _NAME_MAP[name]
    base = name
    for suffix in (".bin", "-bin", "-wrapped"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if _is_version(base) or _is_interpreter(base):
        derived = (_name_from_cmdline(cmdline or []) if _is_interpreter(base)
                   else _name_from_exe(exe) or _name_from_cmdline(cmdline or []))
        if derived:
            return derived
        if base.lower() in _NAME_MAP:
            return _NAME_MAP[base.lower()]
        return base[0].upper() + base[1:]
    if base:
        base = base[0].upper() + base[1:]
    return base


def _current_user() -> str:
    """Current user's login name, for the 'mine' scope."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return ""


_ICON_FALLBACK = "application-x-executable"
_ICON_DIRS = (
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
)
_icon_cache: dict[str, str] = {}


def _read_desktop(path: str) -> dict:
    """Parse the Exec, StartupWMClass and Icon keys from a .desktop file."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                for key in ("Exec", "StartupWMClass", "Icon"):
                    if line.startswith(f"{key}="):
                        out[key] = line[len(key) + 1:].strip()
    except OSError:
        return out
    return out


def _flatpak_app_id(pid: int) -> str:
    """Read the Flatpak app id from /proc/<pid>/root/.flatpak-info or cgroup."""
    try:
        with open(f"/proc/{pid}/root/.flatpak-info", encoding="utf-8",
                  errors="replace") as f:
            for line in f:
                if line.startswith("FlatpakAppID="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8",
                  errors="replace") as f:
            for line in f:
                if "flatpak/" in line:
                    parts = line.split("/")
                    for p in parts:
                        if "." in p and "-" in p and len(p) > 4:
                            return p
    except OSError:
        pass
    return ""


def icon_for(name: str, dirs: Sequence[str] = _ICON_DIRS,
             exe: str = "", pid: int = 0) -> str:
    """Find a matching .desktop Icon for a process; cached."""
    if name in _icon_cache:
        return _icon_cache[name]
    target = name.lower()
    exe_base = os.path.basename(exe).lower() if exe else ""
    # Flatpak: try the app id as an additional target.
    fpk_id = _flatpak_app_id(pid) if pid else ""
    targets = {t for t in (target, exe_base, fpk_id.lower()) if t}
    for d in dirs:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for fn in entries:
            if not fn.endswith(".desktop"):
                continue
            stem = fn[: -len(".desktop")].lower()
            stem_clean = stem.removesuffix("-bin")
            keys = _read_desktop(os.path.join(d, fn))
            exec_base = ""
            if "Exec" in keys:
                exec_base = os.path.basename(
                    keys["Exec"].split()[0]).lower()
            wm = keys.get("StartupWMClass", "").lower()
            hits = {stem, stem_clean, exec_base, wm} & targets
            if hits:
                icon = keys.get("Icon") or _ICON_FALLBACK
                _icon_cache[name] = icon
                return icon
    _icon_cache[name] = _ICON_FALLBACK
    return _ICON_FALLBACK


def _default_run(cmd: list, timeout: float = 2.0) -> str:
    """Run a command and return stdout (default GPU probe runner)."""
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return res.stdout


def _nvml_gpu_mem() -> Optional[dict[int, int]]:
    """Per-pid GPU memory via NVML; None when NVML is unavailable."""
    from spaced_monitor import nvml
    if not nvml.available():
        return None
    return nvml.compute_processes(0)


def _nvml_gpu_sm() -> Optional[dict[int, float]]:
    """Per-pid GPU SM utilisation via NVML; None when NVML is unavailable."""
    from spaced_monitor import nvml
    if not nvml.available():
        return None
    return nvml.process_utilization(0)


def _gpu_mem_by_pid(run: Callable = None) -> dict[int, int]:
    """Per-pid GPU memory in bytes: NVML first, nvidia-smi compute-apps as fallback."""
    # An empty NVML answer means "no GPU process right now", not "ask again":
    # nvidia-smi is only for machines where NVML cannot be loaded.
    result = _nvml_gpu_mem()
    if result is not None:
        return result
    if run is None:
        run = _default_run
    cmd = ["nvidia-smi", "--query-compute-apps=pid,used_memory",
           "--format=csv,noheader,nounits"]
    try:
        out = run(cmd, timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    result: dict[int, int] = {}
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            mib = float(parts[1])
        except ValueError:
            continue
        result[pid] = int(mib * 1024 * 1024)
    return result


def _gpu_sm_by_pid(run: Callable = None) -> dict[int, float]:
    """Per-pid GPU SM utilisation percent: NVML first, nvidia-smi pmon as fallback."""
    result = _nvml_gpu_sm()
    if result is not None:
        return result
    if run is None:
        run = _default_run
    cmd = ["nvidia-smi", "pmon", "-c", "1", "-s", "u"]
    try:
        out = run(cmd, timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    result: dict[int, float] = {}
    for line in (out or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        try:
            pid = int(cols[1])
        except ValueError:
            continue
        sm = 0.0 if cols[3] == "-" else float(cols[3])
        result[pid] = sm
    return result


def _safe_exe(proc) -> str:
    """Return proc.exe() or empty string on access-denied/missing."""
    try:
        return proc.exe() or ""
    except Exception:
        return ""


def _safe_cmdline(proc) -> list:
    """Return proc.cmdline() or empty list on access-denied/missing."""
    try:
        return proc.cmdline() or []
    except Exception:
        return []


_KERNEL_THREAD = object()   # marks a pid that is a kernel thread (skipped)


def _oneshot(proc):
    """psutil's oneshot() batching when available (fakes in tests lack it)."""
    one = getattr(proc, "oneshot", None)
    return one() if one is not None else contextlib.nullcontext()


class ProcessSampler:
    """Group processes into apps and sample their usage over time."""

    def __init__(self, ps=None, clock: Callable[[], float] = time.monotonic,
                 gpu_run: Callable = None) -> None:
        """Keep Process objects and io counters between samples for deltas."""
        if ps is None:
            import psutil
            ps = psutil
        self._ps = ps
        self._clock = clock
        self._gpu_run = gpu_run
        self._procs: dict[int, object] = {}
        self._io: dict[int, tuple[int, int]] = {}
        self._static: dict[int, object] = {}
        self._prev_t: Optional[float] = None

    def _has_exe(self, proc) -> bool:
        """True when a process exposes an executable path."""
        try:
            return bool(proc.exe())
        except self._ps.NoSuchProcess:
            return False
        except self._ps.AccessDenied:
            return True

    def _is_kernel_thread(self, proc) -> bool:
        """Kernel threads (children of kthreadd, pid 2) are left out."""
        if proc.pid in (1, 2):
            return True
        return proc.ppid() == 2

    def _io_delta(self, proc, pid: int) -> int:
        """Read+write bytes since the last sample; denied or missing -> 0."""
        try:
            cur = proc.io_counters()
        except (AttributeError, self._ps.AccessDenied, self._ps.NoSuchProcess):
            return 0
        read_b, write_b = cur.read_bytes, cur.write_bytes
        prev = self._io.get(pid)
        self._io[pid] = (read_b, write_b)
        if prev is None:
            return 0
        return max(0, (read_b - prev[0]) + (write_b - prev[1]))

    def sample(self) -> list[AppUsage]:
        """Return AppUsage rows sorted by cpu_percent descending."""
        now = self._clock()
        dt = (now - self._prev_t) if self._prev_t is not None else 0.0
        self._prev_t = now
        gpu_mem = _gpu_mem_by_pid(self._gpu_run)
        gpu_sm = _gpu_sm_by_pid(self._gpu_run)
        cpu_n = self._ps.cpu_count() or 1
        groups: dict[tuple[str, str], dict] = {}
        pids = self._ps.pids()
        for pid in pids:
            proc = self._procs.get(pid)
            if proc is None:
                try:
                    proc = self._ps.Process(pid)
                except self._ps.NoSuchProcess:
                    continue
                self._procs[pid] = proc
            try:
                # oneshot() reads /proc/<pid>/stat and status once for all the
                # calls below; name, user, exe and cmdline never change for a
                # running process, so they are read once per pid.
                with _oneshot(proc):
                    static = self._static.get(pid)
                    if static is None:
                        if self._is_kernel_thread(proc):
                            self._static[pid] = _KERNEL_THREAD
                            continue
                        static = (proc.name(), proc.username(),
                                  _safe_exe(proc), _safe_cmdline(proc))
                        self._static[pid] = static
                    elif static is _KERNEL_THREAD:
                        continue
                    cpu = proc.cpu_percent(interval=None)
                    rss = proc.memory_info().rss
                    disk = self._io_delta(proc, pid)
            except self._ps.NoSuchProcess:
                self._procs.pop(pid, None)
                self._static.pop(pid, None)
                continue
            except (self._ps.AccessDenied, self._ps.ZombieProcess):
                continue
            name, user, exe, cmdl = static
            g = groups.setdefault(_group_key(name, user, cmdl), {
                "pids": [], "cpu": 0.0, "rss": 0, "gpu_percent": 0.0,
                "gpu_mem": 0, "disk": 0, "children": [],
                "exe": "", "cmdline": [],
            })
            if not g["exe"] and exe:
                g["exe"] = exe
            if not g["cmdline"] and cmdl:
                g["cmdline"] = cmdl
            g["pids"].append(pid)
            g["children"].append(ProcUsage(pid, name, cpu, rss, exe, cmdl))
            g["cpu"] += cpu
            g["rss"] += rss
            g["gpu_percent"] += gpu_sm.get(pid, 0.0)
            g["gpu_mem"] += gpu_mem.get(pid, 0)
            g["disk"] += disk
        present = set(pids)
        for pid in list(self._procs):
            if pid not in present:
                self._procs.pop(pid, None)
                self._io.pop(pid, None)
                self._static.pop(pid, None)
        rows = []
        for (key, user), g in groups.items():
            name = key.split("\0", 1)[0]
            rows.append(AppUsage(
                name=name, pids=g["pids"],
                cpu_percent=g["cpu"] / cpu_n,
                rss=g["rss"], gpu_percent=g["gpu_percent"], gpu_mem=g["gpu_mem"],
                disk_bps=(g["disk"] / dt) if dt > 0 else 0.0,
                user=user, icon=icon_for(name, exe=g["exe"], pid=g["pids"][0] if g["pids"] else 0),
                children=sorted(g["children"],
                                key=lambda p: p.cpu_percent, reverse=True),
                exe=g["exe"], cmdline=g["cmdline"],
            ))
        rows.sort(key=lambda a: a.cpu_percent, reverse=True)
        return rows


def filter_apps(apps: Sequence[AppUsage], text: str = "", scope: str = "all",
                me: Optional[str] = None) -> list[AppUsage]:
    """Keep apps whose display name matches text; scope 'mine' limits to me."""
    if me is None:
        me = _current_user()
    low = text.lower()
    out = []
    for a in apps:
        if scope == "mine" and a.user != me:
            continue
        if low and low not in display_name(a.name, exe=a.exe, cmdline=a.cmdline).lower():
            continue
        out.append(a)
    return out


def _start_time(pid: int) -> Optional[str]:
    """The kernel start time of pid (/proc/<pid>/stat field 22); None if gone.

    A pid can be reused by an unrelated process: the start time tells them apart.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as fh:
            stat = fh.read()
    except OSError:
        return None
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else None


def _refusal(app: AppUsage, me: int, uid: int) -> Optional[str]:
    """Why this app must not be ended, or None when it may be."""
    name = display_name(app.name, exe=app.exe, cmdline=app.cmdline)
    for pid in app.pids:
        if pid in (1, 2) or pid == me:
            return f"refusing to end {name}: protected process {pid}"
    if app.name in _SESSION_CRITICAL:
        return f"{name} runs your desktop session: ending it would log you out."
    try:
        owner = pwd.getpwuid(uid).pw_name
    except KeyError:
        owner = None
    if uid != 0 and app.user and owner is not None and app.user != owner:
        return f"{name} belongs to {app.user}: ending it needs an administrator."
    return None


def end_app(app: AppUsage, force: bool = False, kill: Callable = os.kill,
            me: Optional[int] = None, uid: Optional[int] = None) -> tuple[bool, str]:
    """End an app's processes; refuse protected pids and other users' apps."""
    me = os.getpid() if me is None else me
    uid = os.getuid() if uid is None else uid
    reason = _refusal(app, me, uid)
    if reason:
        return (False, reason)
    return _signal_all(app, signal.SIGKILL if force else signal.SIGTERM, kill)


def _signal_all(app: AppUsage, sig: int, kill: Callable) -> tuple[bool, str]:
    """Send sig to every pid of app; the result message for the user."""
    name = display_name(app.name, exe=app.exe, cmdline=app.cmdline)
    killed = 0
    for pid in app.pids:
        try:
            kill(pid, sig)
            killed += 1
        except ProcessLookupError:
            continue
        except PermissionError:
            return (False, f"{name} belongs to {app.user}: ending it needs an administrator.")
    if killed == 0:
        return (True, f"{name} was already gone")
    return (True, f"ended {name} ({killed} process(es))")


def end_immediate(app: AppUsage, kill: Callable = os.kill,
                  timeout_add: Callable | None = None,
                  me: Optional[int] = None, uid: Optional[int] = None,
                  start_of: Callable = _start_time) -> tuple[bool, str]:
    """End an app now: SIGTERM every pid, SIGKILL the same processes after 2 s.

    timeout_add is the GLib.timeout_add callable (or a fake in tests).
    Returns (False, reason) when the app is protected or belongs to another user.
    """
    me = os.getpid() if me is None else me
    uid = os.getuid() if uid is None else uid
    reason = _refusal(app, me, uid)
    if reason:
        return (False, reason)
    starts = {pid: start_of(pid) for pid in app.pids}
    ok, msg = _signal_all(app, signal.SIGTERM, kill)
    if ok and timeout_add is not None and not msg.endswith("already gone"):
        timeout_add(2000, _sigkill_survivors, list(app.pids), kill, starts, start_of)
    return (ok, msg)


def _sigkill_survivors(pids: list, kill: Callable, starts: dict,
                       start_of: Callable = _start_time) -> bool:
    """SIGKILL each pid that is still the SAME process SIGTERM was sent to.

    A pid whose start time changed was reused by another process: never touch it.
    Returns False so the GLib timeout does not repeat.
    """
    for pid in pids:
        now = start_of(pid)
        if now is None or starts.get(pid) is None or now != starts[pid]:
            continue
        try:
            kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return False


def main() -> None:
    """Print the top apps using this machine."""
    sampler = ProcessSampler()
    sampler.sample()
    time.sleep(1.0)
    apps = sampler.sample()
    print(f"{'APP':<22} {'CPU%':>6} {'MEM':>8} {'GPU%':>5} {'GPUmem':>8} {'DISK':>8} USER")
    for a in apps[:8]:
        print(f"{display_name(a.name):<22} {a.cpu_percent:>6.1f} "
              f"{_fmt_bytes(a.rss):>8} {a.gpu_percent:>5.0f} {_fmt_bytes(a.gpu_mem):>8} "
              f"{_fmt_bps(a.disk_bps):>8} {a.user}")


def _fmt_bytes(value: int) -> str:
    """Human-readable byte size."""
    size = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


def _fmt_bps(value: float) -> str:
    """Human-readable bytes-per-second rate."""
    if value <= 0:
        return "-"
    return _fmt_bytes(int(value)) + "/s"


if __name__ == "__main__":
    main()
