# SPDX-License-Identifier: GPL-3.0-or-later
"""Colour palettes, GTK CSS, and user settings for Spaced Monitor."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _hex(h: str) -> tuple[float, float, float]:
    """Convert a hex colour string to (r, g, b) floats in 0-1."""
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))  # type: ignore


@dataclass(frozen=True)
class Palette:
    """All named colours used by the UI as (r, g, b) floats."""
    window: tuple[float, float, float]
    card: tuple[float, float, float]
    border: tuple[float, float, float]
    text: tuple[float, float, float]
    muted: tuple[float, float, float]
    cpu_start: tuple[float, float, float]
    cpu_end: tuple[float, float, float]
    gpu_start: tuple[float, float, float]
    gpu_end: tuple[float, float, float]
    memory_start: tuple[float, float, float]
    memory_end: tuple[float, float, float]
    gpu_memory_start: tuple[float, float, float]
    gpu_memory_end: tuple[float, float, float]
    cpu_temp: tuple[float, float, float]
    gpu_temp: tuple[float, float, float]
    threshold: tuple[float, float, float]
    disk_read: tuple[float, float, float]
    disk_write: tuple[float, float, float]
    net_download: tuple[float, float, float]
    net_upload: tuple[float, float, float]
    gauge_track: tuple[float, float, float]
    end_button: tuple[float, float, float]


DARK = Palette(
    window=_hex("#0b1220"),
    card=_hex("#111a2e"),
    border=_hex("#1e2a44"),
    text=_hex("#e6ecf5"),
    muted=_hex("#8a96ab"),
    cpu_start=_hex("#22c55e"),
    cpu_end=_hex("#34d399"),
    gpu_start=_hex("#0ea5e9"),
    gpu_end=_hex("#38bdf8"),
    memory_start=_hex("#f59e0b"),
    memory_end=_hex("#fbbf24"),
    gpu_memory_start=_hex("#8b5cf6"),
    gpu_memory_end=_hex("#c084fc"),
    cpu_temp=_hex("#f97316"),
    gpu_temp=_hex("#38bdf8"),
    threshold=_hex("#ef4444"),
    disk_read=_hex("#22c55e"),
    disk_write=_hex("#f59e0b"),
    net_download=_hex("#38bdf8"),
    net_upload=_hex("#a855f7"),
    gauge_track=_hex("#1e2a44"),
    end_button=_hex("#ef4444"),
)

LIGHT = Palette(
    window=_hex("#eef2f8"),
    card=_hex("#ffffff"),
    border=_hex("#dfe5ef"),
    text=_hex("#1f2937"),
    muted=_hex("#6b7280"),
    cpu_start=_hex("#22c55e"),
    cpu_end=_hex("#34d399"),
    gpu_start=_hex("#0ea5e9"),
    gpu_end=_hex("#38bdf8"),
    memory_start=_hex("#f59e0b"),
    memory_end=_hex("#fbbf24"),
    gpu_memory_start=_hex("#8b5cf6"),
    gpu_memory_end=_hex("#c084fc"),
    cpu_temp=_hex("#f97316"),
    gpu_temp=_hex("#38bdf8"),
    threshold=_hex("#ef4444"),
    disk_read=_hex("#22c55e"),
    disk_write=_hex("#f59e0b"),
    net_download=_hex("#38bdf8"),
    net_upload=_hex("#a855f7"),
    gauge_track=_hex("#e5e7eb"),
    end_button=_hex("#ef4444"),
)


def palette(name: str) -> Palette:
    """Return the palette for the given theme name."""
    if name == "dark":
        return DARK
    if name == "light":
        return LIGHT
    raise ValueError(f"unknown theme: {name!r}")


def gradient(pal: Palette, kind: str) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return (start, end) colour stops for a named gradient."""
    mapping = {
        "cpu": (pal.cpu_start, pal.cpu_end),
        "gpu": (pal.gpu_start, pal.gpu_end),
        "memory": (pal.memory_start, pal.memory_end),
        "gpu_memory": (pal.gpu_memory_start, pal.gpu_memory_end),
    }
    return mapping[kind]


def rgba(colour: tuple[float, float, float], alpha: float) -> str:
    """Format a colour + alpha as a CSS rgba() string."""
    r, g, b = colour
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {alpha})"


def _css_colour(colour: tuple[float, float, float]) -> str:
    """Format a colour tuple as a CSS hex string."""
    return "#{:02x}{:02x}{:02x}".format(*(int(c * 255) for c in colour))


def css(pal: Palette) -> str:
    """Return GTK 3 CSS for the given palette."""
    w = _css_colour(pal.window)
    c = _css_colour(pal.card)
    b = _css_colour(pal.border)
    t = _css_colour(pal.text)
    m = _css_colour(pal.muted)
    gpu_tint = rgba(pal.gpu_start, 0.25)
    red = _css_colour(pal.end_button)
    return f"""\
window, .background {{
    background-color: {w};
    color: {t};
}}
.topbar {{
    background-color: {c};
    border-bottom: 1px solid {b};
    padding: 6px 10px;
}}
.card {{
    background-color: {c};
    border: 1px solid {b};
    border-radius: 12px;
    padding: 14px;
    color: {t};
}}
.card-title {{
    font-weight: bold;
    font-size: 13px;
    color: {t};
}}
.big-value {{
    font-weight: bold;
    font-size: 22px;
    color: {t};
}}
.muted {{
    font-size: 11px;
    color: {m};
}}
.value {{
    font-size: 13px;
    color: {t};
}}
.tab-selected {{
    background-color: {gpu_tint};
    border-radius: 6px;
    padding: 4px 10px;
}}
.end-button {{
    background-color: {red};
    color: #ffffff;
    border-radius: 10px;
    min-width: 20px;
    min-height: 20px;
    padding: 2px;
}}
"""


_css_provider: object | None = None
_screen: object | None = None


def apply_css(pal: Palette, screen=None) -> None:
    """Install CSS on the given GTK screen, replacing any previous provider."""
    global _css_provider, _screen
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk
    provider = Gtk.CssProvider()
    provider.load_from_data(css(pal).encode("utf-8"))
    if screen is None:
        if _screen is None:
            w = Gtk.OffscreenWindow()
            w.show()
            _screen = w.get_style_context().get_screen()
            w.close()
        screen = _screen
    if _css_provider is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _css_provider)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    _css_provider = provider


_DEFAULT_SETTINGS: dict[str, object] = {"theme": "system", "refresh_ms": 1000}


def _settings_path(path: str | None = None) -> Path:
    """Return the path to the settings file."""
    if path is not None:
        return Path(path)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "spaced-monitor" / "settings.json"


def load_settings(path: str | None = None) -> dict[str, object]:
    """Load user settings, returning defaults on missing or corrupt file."""
    p = _settings_path(path)
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return dict(_DEFAULT_SETTINGS)
    result = dict(_DEFAULT_SETTINGS)
    if data.get("theme") in ("dark", "light", "system"):
        result["theme"] = data["theme"]
    ms = data.get("refresh_ms")
    if isinstance(ms, (int, float)):
        result["refresh_ms"] = max(500, min(5000, int(ms)))
    return result


def save_settings(data: dict[str, object], path: str | None = None) -> None:
    """Atomically save settings to disk."""
    p = _settings_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, str(p))
    except BaseException:
        os.unlink(tmp)
        raise


def resolve_theme(setting: str, gtk_settings: object) -> str:
    """Resolve 'system' to 'dark' or 'light' using GTK preferences."""
    if setting in ("dark", "light"):
        return setting
    prefer_dark = gtk_settings.get_gtk_application_prefer_dark_theme()
    if prefer_dark:
        return "dark"
    theme_name = gtk_settings.get_gtk_theme_name() or ""
    if "dark" in theme_name.lower():
        return "dark"
    return "light"
