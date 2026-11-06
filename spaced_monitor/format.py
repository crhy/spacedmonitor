# SPDX-License-Identifier: GPL-3.0-or-later
"""Human-readable formatters for the Spaced Monitor UI."""

from __future__ import annotations

from typing import Optional

EMDASH = "\u2014"


def bytes_gb(n: Optional[int]) -> str:
    """Format a byte count as gigabytes with one decimal, e.g. '24.6 GB'."""
    if n is None:
        return EMDASH
    return f"{n / (1024**3):.1f} GB"


def pair_gb(used: Optional[int], total: Optional[int]) -> str:
    """Format 'used / total' in GB; total drops decimals when whole."""
    if used is None or total is None:
        return EMDASH
    u = used / (1024**3)
    t = total / (1024**3)
    ts = f"{t:.0f}" if t == int(t) else f"{t:.1f}"
    return f"{u:.1f} / {ts} GB"


def rate(bps: Optional[float]) -> str:
    """Format a bytes-per-second rate with an appropriate unit."""
    if bps is None:
        return EMDASH
    if bps <= 0:
        return "0 B/s"
    units = ("B", "KB", "MB", "GB", "TB")
    v = float(bps)
    i = 0
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return f"{int(v)} {units[i]}/s"
    return f"{v:.0f} {units[i]}/s"


def fahrenheit(c: Optional[float]) -> Optional[float]:
    """Convert a Celsius reading to Fahrenheit, preserving missing values."""
    if c is None:
        return None
    return (c * 9.0 / 5.0) + 32.0


def temp(c: Optional[float]) -> str:
    """Format a Celsius reading for display in Fahrenheit, e.g. '144 °F'."""
    if c is None:
        return EMDASH
    return f"{int(round(fahrenheit(c)))} °F"


def ghz(mhz: Optional[float]) -> str:
    """Format a frequency from MHz to GHz, e.g. '4.6 GHz'."""
    if mhz is None:
        return EMDASH
    return f"{mhz / 1000.0:.1f} GHz"


def watts(w: Optional[float]) -> str:
    """Format a power reading in watts, e.g. '235 W'."""
    if w is None:
        return EMDASH
    return f"{int(round(w))} W"


def rpm(n: Optional[int]) -> str:
    """Format fan RPM with thousands separator, e.g. '1,240 RPM'."""
    if n is None:
        return EMDASH
    return f"{n:,} RPM"


def duration(s: Optional[float]) -> str:
    """Format a duration as '3h 42m', '2d 5h', or '12m'."""
    if s is None:
        return EMDASH
    total = int(s)
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def percent(p: Optional[float]) -> str:
    """Format a percentage value, e.g. '77%'."""
    if p is None:
        return EMDASH
    return f"{int(round(p))}%"
