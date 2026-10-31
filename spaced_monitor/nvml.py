# SPDX-License-Identifier: GPL-3.0-or-later
"""ctypes wrapper around libnvidia-ml.so.1 — no subprocess, no nvidia-smi."""
from __future__ import annotations

import ctypes
import ctypes.util
import atexit
from typing import Optional

_lib = None
_initialized = False


def _load() -> Optional[ctypes.CDLL]:
    """Load libnvidia-ml.so.1 lazily; return None when the library is absent."""
    global _lib
    if _lib is not None:
        return _lib
    path = ctypes.util.find_library("nvidia-ml")
    if path is None:
        return None
    try:
        _lib = ctypes.CDLL(path)
    except OSError:
        return None
    return _lib


def _init() -> bool:
    """Call nvmlInit_v2 once; return True on success."""
    global _initialized
    if _initialized:
        return True
    lib = _load()
    if lib is None:
        return False
    lib.nvmlInit_v2.restype = ctypes.c_int
    if lib.nvmlInit_v2() != 0:
        return False
    _initialized = True
    atexit.register(_shutdown)
    return True


def _shutdown() -> None:
    """Call nvmlShutdown at process exit."""
    global _initialized
    if not _initialized:
        return
    lib = _load()
    if lib is not None:
        lib.nvmlShutdown.restype = ctypes.c_int
        lib.nvmlShutdown()
    _initialized = False


def _device_handle(lib: ctypes.CDLL, index: int = 0):
    """Return nvmlDevice_t for device at *index*, or None."""
    lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
        ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
    ]
    lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
    handle = ctypes.c_void_p()
    if lib.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(index),
                                         ctypes.byref(handle)) != 0:
        return None
    return handle


# --- Struct layouts (documented C ABI) ---


class _Utilization(ctypes.Structure):
    """nvmlUtilization_t: gpu and memory as unsigned int percentages."""
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memory(ctypes.Structure):
    """nvmlMemory_v2_t: total, free, reserved, used in bytes."""
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("reserved", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _MemoryV1(ctypes.Structure):
    """nvmlMemory_t (v1): total, free, used in bytes (no reserved field)."""
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _ProcessInfo(ctypes.Structure):
    """nvmlProcessInfo_v3_t: pid, usedMemory, processName, then extras."""
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedMemory", ctypes.c_ulonglong),
        ("processName", ctypes.c_char * 1024),
        ("residentSize", ctypes.c_ulonglong),
        ("managedSize", ctypes.c_ulonglong),
        ("offsetsSize", ctypes.c_ulonglong),
        ("offsetsCount", ctypes.c_ulonglong),
        ("offsets", ctypes.POINTER(ctypes.c_ulonglong)),
    ]


class _ProcUtil(ctypes.Structure):
    """nvmlProcessUtilizationSample_t: pid, timeStamp, utilization, extras."""
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("timeStamp", ctypes.c_ulonglong),
        ("utilization", _Utilization),
        ("dataBufferSize", ctypes.c_uint),
        ("dataBuffer", ctypes.POINTER(ctypes.c_uint)),
    ]


# --- Public API ---


def available() -> bool:
    """True when NVML can be loaded and initialised."""
    return _init()


def device_name(index: int = 0) -> Optional[str]:
    """Return GPU name for device *index*."""
    lib = _load()
    if lib is None or not _init():
        return None
    dev = _device_handle(lib, index)
    if dev is None:
        return None
    buf = ctypes.create_string_buffer(96)
    lib.nvmlDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                      ctypes.c_uint, ctypes.c_uint]
    lib.nvmlDeviceGetName.restype = ctypes.c_int
    # NVML >= 12: (device, name, type, length) — type 0 = backend
    rc = lib.nvmlDeviceGetName(dev, buf, ctypes.c_uint(0), ctypes.c_uint(96))
    if rc != 0:
        # Fallback: older 3-arg signature (device, name, length)
        lib.nvmlDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                          ctypes.c_uint]
        rc = lib.nvmlDeviceGetName(dev, buf, ctypes.c_uint(96))
    if rc != 0:
        return None
    return buf.value.decode("utf-8", errors="replace") or None


def utilization(index: int = 0) -> Optional[float]:
    """GPU utilisation percent for device *index*."""
    lib = _load()
    if lib is None or not _init():
        return None
    dev = _device_handle(lib, index)
    if dev is None:
        return None
    util = _Utilization()
    lib.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(_Utilization)]
    lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
    if lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util)) != 0:
        return None
    return float(util.gpu)


def temperature(index: int = 0) -> Optional[float]:
    """GPU temperature (sensor 0) in Celsius for device *index*."""
    lib = _load()
    if lib is None or not _init():
        return None
    dev = _device_handle(lib, index)
    if dev is None:
        return None
    temp = ctypes.c_uint(0)
    lib.nvmlDeviceGetTemperature.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                             ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
    if lib.nvmlDeviceGetTemperature(dev, ctypes.c_uint(0),
                                    ctypes.byref(temp)) != 0:
        return None
    return float(temp.value)


def power_usage(index: int = 0) -> Optional[float]:
    """Power draw in watts for device *index* (NVML returns mW)."""
    lib = _load()
    if lib is None or not _init():
        return None
    dev = _device_handle(lib, index)
    if dev is None:
        return None
    mw = ctypes.c_uint(0)
    lib.nvmlDeviceGetPowerUsage.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetPowerUsage.restype = ctypes.c_int
    if lib.nvmlDeviceGetPowerUsage(dev, ctypes.byref(mw)) != 0:
        return None
    return mw.value / 1000.0


def memory_info(index: int = 0) -> tuple[Optional[int], Optional[int]]:
    """(used_bytes, total_bytes) for device *index*."""
    lib = _load()
    if lib is None or not _init():
        return None, None
    dev = _device_handle(lib, index)
    if dev is None:
        return None, None
    # Try v2 first (has reserved field).
    mem = _Memory()
    lib.nvmlDeviceGetMemoryInfo_v2.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(_Memory)]
    lib.nvmlDeviceGetMemoryInfo_v2.restype = ctypes.c_int
    if lib.nvmlDeviceGetMemoryInfo_v2(dev, ctypes.byref(mem)) == 0:
        return int(mem.used), int(mem.total)
    # Fallback to v1 (total, free, used — no reserved).
    mem1 = _MemoryV1()
    lib.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(_MemoryV1)]
    lib.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
    if lib.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem1)) != 0:
        return None, None
    return int(mem1.used), int(mem1.total)


def driver_version() -> Optional[str]:
    """System driver version string."""
    lib = _load()
    if lib is None or not _init():
        return None
    buf = ctypes.create_string_buffer(80)
    lib.nvmlSystemGetDriverVersion.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    lib.nvmlSystemGetDriverVersion.restype = ctypes.c_int
    if lib.nvmlSystemGetDriverVersion(buf, ctypes.c_uint(80)) != 0:
        return None
    return buf.value.decode("utf-8", errors="replace") or None


def pci_link(index: int = 0) -> tuple[Optional[str], Optional[str]]:
    """(gen, width) for device *index*."""
    lib = _load()
    if lib is None or not _init():
        return None, None
    dev = _device_handle(lib, index)
    if dev is None:
        return None, None
    gen = ctypes.c_uint(0)
    lib.nvmlDeviceGetCurrPcieLinkGeneration.argtypes = [ctypes.c_void_p,
                                                       ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetCurrPcieLinkGeneration.restype = ctypes.c_int
    if lib.nvmlDeviceGetCurrPcieLinkGeneration(dev, ctypes.byref(gen)) != 0:
        return None, None
    width = ctypes.c_uint(0)
    lib.nvmlDeviceGetCurrPcieLinkWidth.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetCurrPcieLinkWidth.restype = ctypes.c_int
    if lib.nvmlDeviceGetCurrPcieLinkWidth(dev, ctypes.byref(width)) != 0:
        return None, None
    return str(gen.value), str(width.value)


def compute_processes(index: int = 0) -> dict[int, int]:
    """Per-pid GPU memory in bytes from nvmlDeviceGetComputeRunningProcesses_v3."""
    lib = _load()
    if lib is None or not _init():
        return {}
    dev = _device_handle(lib, index)
    if dev is None:
        return {}
    count = ctypes.c_uint(64)
    buf = (_ProcessInfo * 64)()
    lib.nvmlDeviceGetComputeRunningProcesses_v3.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(_ProcessInfo)
    ]
    lib.nvmlDeviceGetComputeRunningProcesses_v3.restype = ctypes.c_int
    rc = lib.nvmlDeviceGetComputeRunningProcesses_v3(
        dev, ctypes.byref(count), ctypes.cast(buf, ctypes.POINTER(_ProcessInfo)))
    if rc != 0:
        # Fallback to v2
        lib.nvmlDeviceGetComputeRunningProcesses_v2.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(_ProcessInfo)
        ]
        lib.nvmlDeviceGetComputeRunningProcesses_v2.restype = ctypes.c_int
        rc = lib.nvmlDeviceGetComputeRunningProcesses_v2(
            dev, ctypes.byref(count), ctypes.cast(buf, ctypes.POINTER(_ProcessInfo)))
        if rc != 0:
            return {}
    result: dict[int, int] = {}
    for i in range(count.value):
        result[buf[i].pid] = int(buf[i].usedMemory)
    return result


_last_seen_ts = ctypes.c_ulonglong(0)


def process_utilization(index: int = 0) -> dict[int, float]:
    """Per-pid GPU SM utilisation from nvmlDeviceGetProcessUtilization."""
    global _last_seen_ts
    lib = _load()
    if lib is None or not _init():
        return {}
    dev = _device_handle(lib, index)
    if dev is None:
        return {}
    count = ctypes.c_uint(64)
    buf = (_ProcUtil * 64)()
    ts = _last_seen_ts
    lib.nvmlDeviceGetProcessUtilization.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_ProcUtil),
        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_ulonglong)
    ]
    lib.nvmlDeviceGetProcessUtilization.restype = ctypes.c_int
    rc = lib.nvmlDeviceGetProcessUtilization(
        dev, ctypes.cast(buf, ctypes.POINTER(_ProcUtil)),
        ctypes.byref(count), ctypes.byref(ts))
    if rc != 0:
        return {}
    _last_seen_ts = ts
    result: dict[int, float] = {}
    for i in range(count.value):
        result[buf[i].pid] = float(buf[i].utilization.gpu)
    return result
