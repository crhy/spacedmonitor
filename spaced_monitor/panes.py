# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure helpers for saving, loading and clamping Paned handle positions."""

from __future__ import annotations

PANE_KEYS = ("pane_gauges", "pane_graphs", "pane_mid_h")
PANE_MIN = 0.1
PANE_MAX = 0.9


def clamp_fraction(value: object) -> float | None:
    """Return value clamped to [PANE_MIN, PANE_MAX], or None if invalid."""
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v < PANE_MIN or v > PANE_MAX:
        return None
    return v


def default_fractions() -> dict[str, float]:
    """Return default pane fractions for a 900 px tall window."""
    return {"pane_gauges": 0.20, "pane_graphs": 0.28, "pane_mid_h": 0.50}


def load_pane_fractions(settings: dict) -> dict[str, float]:
    """Extract valid pane fractions from a settings dict, filling defaults."""
    defaults = default_fractions()
    result = {}
    for key in PANE_KEYS:
        raw = settings.get(key)
        clamped = clamp_fraction(raw)
        if clamped is not None:
            result[key] = clamped
        else:
            result[key] = defaults[key]
    return result


def save_pane_fractions(settings: dict, fractions: dict[str, float]) -> dict:
    """Merge valid pane fractions into a settings dict for saving."""
    out = dict(settings)
    for key in PANE_KEYS:
        val = fractions.get(key)
        clamped = clamp_fraction(val)
        if clamped is not None:
            out[key] = round(clamped, 4)
    return out


def fractions_to_pixels(fractions: dict[str, float], total: int) -> dict[str, int]:
    """Convert fraction dict to pixel positions for a given total height."""
    result = {}
    for key, frac in fractions.items():
        result[key] = int(frac * total)
    return result


def pixels_to_fractions(positions: dict[str, int], total: int) -> dict[str, float]:
    """Convert pixel positions back to fractions for a given total height."""
    if total <= 0:
        return default_fractions()
    result = {}
    for key, px in positions.items():
        result[key] = round(px / total, 4)
    return result
