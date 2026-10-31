# SPDX-License-Identifier: GPL-3.0-or-later
"""Colour palettes, GTK CSS, and user settings for Spaced Monitor."""

from __future__ import annotations

import configparser
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
    selected_bg: tuple[float, float, float]
    cpu_start: tuple[float, float, float]
    cpu_end: tuple[float, float, float]
    ram_start: tuple[float, float, float]
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
    selected_bg=_hex("#0ea5e9"),
    cpu_start=_hex("#22c55e"),
    cpu_end=_hex("#34d399"),
    ram_start=_hex("#0ea5e9"),
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
    selected_bg=_hex("#0ea5e9"),
    cpu_start=_hex("#22c55e"),
    cpu_end=_hex("#34d399"),
    ram_start=_hex("#0ea5e9"),
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


def _relative_luminance(colour: tuple[float, float, float]) -> float:
    """WCAG relative luminance from sRGB floats."""
    def lin(c: float) -> float:
        if c <= 0.0392:
            return c / 12.92
        if c <= 0.787:
            return ((c + 0.055) / 1.055) ** 2.4
        return c
    r, g, b = colour
    return 0.2127 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _mix_towards(base: tuple[float, float, float],
                 target: tuple[float, float, float],
                 amount: float) -> tuple[float, float, float]:
    """Mix base towards target by amount (0-1)."""
    return tuple(b + (t - b) * amount for b, t in zip(base, target))  # type: ignore


def _lightness(colour: tuple[float, float, float]) -> float:
    """Perceptual lightness (0-1) for comparing two colours."""
    r, g, b = colour
    return 0.299 * r + 0.587 * g + 0.114 * b


def palette_from_gtk(style_context) -> Palette:
    """Build a Palette from the active GTK theme's named colours.

    Uses style_context.lookup_color(name) which returns (found, Gdk.RGBA).
    Falls back to DARK or LIGHT when a colour is not found.
    """
    def _lookup(name: str) -> tuple[float, float, float] | None:
        found, rgba_val = style_context.lookup_color(name)
        if not found:
            return None
        return (rgba_val.red, rgba_val.green, rgba_val.blue)

    bg = _lookup("theme_bg_color")
    base = _lookup("theme_base_color")
    fg = _lookup("theme_fg_color")
    sel = _lookup("theme_selected_bg_color")

    # Determine dark vs light from bg luminance.
    if bg is not None:
        is_dark = _relative_luminance(bg) < 0.5
    elif fg is not None:
        # Fall back: use fg luminance (fg is opposite of bg).
        is_dark = _relative_luminance(fg) > 0.5
    else:
        is_dark = True  # no information, default to dark

    fallback = DARK if is_dark else LIGHT

    window = bg if bg is not None else fallback.window
    text = fg if fg is not None else fallback.text

    # Card: use theme_base_color; if within ~4% lightness of window, shade
    # 6% towards the foreground so cards stay visible.
    if base is not None:
        card = base
        if abs(_lightness(card) - _lightness(window)) < 0.04:
            card = _mix_towards(card, text, 0.06)
    else:
        card = fallback.card

    # Derived colours from fg.
    if fg is not None:
        muted = _mix_towards(window, fg, 0.65)
        border = _mix_towards(window, fg, 0.12)
        gauge_track = _mix_towards(window, fg, 0.14)
    else:
        muted = fallback.muted
        border = fallback.border
        gauge_track = fallback.gauge_track

    selected_bg = sel if sel is not None else fallback.selected_bg

    return Palette(
        window=window,
        card=card,
        border=border,
        text=text,
        muted=muted,
        selected_bg=selected_bg,
        cpu_start=fallback.cpu_start,
        cpu_end=fallback.cpu_end,
        ram_start=fallback.ram_start,
        gpu_start=fallback.gpu_start,
        gpu_end=fallback.gpu_end,
        memory_start=fallback.memory_start,
        memory_end=fallback.memory_end,
        gpu_memory_start=fallback.gpu_memory_start,
        gpu_memory_end=fallback.gpu_memory_end,
        cpu_temp=fallback.cpu_temp,
        gpu_temp=fallback.gpu_temp,
        threshold=fallback.threshold,
        disk_read=fallback.disk_read,
        disk_write=fallback.disk_write,
        net_download=fallback.net_download,
        net_upload=fallback.net_upload,
        gauge_track=gauge_track,
        end_button=fallback.end_button,
    )


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
    gpu_blue = _css_colour(pal.gpu_end)
    red = _css_colour(pal.end_button)
    cool = _css_colour(pal.cpu_start)
    warm = _css_colour(pal.cpu_temp)
    hot = _css_colour(pal.threshold)
    sel = _css_colour(pal.selected_bg)
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
button {{
    background-image: none;
    background-color: {c};
    color: {t};
    border: 1px solid {b};
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 0;
}}
button:hover, button:active, button:focus {{
    background-color: {rgba(pal.gpu_start, 0.10)};
    color: {t};
}}
button.tab-selected, button.tab-selected:hover,
button.tab-selected:active, button.tab-selected:focus {{
    background-color: {rgba(pal.selected_bg, 0.40)};
    color: {sel};
    border: 1px solid {sel};
}}
entry, combobox entry {{
    background-color: {c};
    color: {t};
    border: 1px solid {b};
    border-radius: 6px;
    padding: 4px 8px;
}}
entry.placeholder, entry label.placeholder, entry placeholder {{
    color: {m};
}}
combobox {{
    background-color: {c};
    border: 1px solid {b};
    border-radius: 6px;
    padding: 0;
}}
combobox button {{
    background-image: none;
    background-color: {c};
    color: {t};
    border: none;
}}
.card {{
    background-color: {c};
    border: 1px solid {b};
    border-radius: 12px;
    padding: 14px;
    color: {t};
}}
/* The app list needs vertical room for rows, so it uses a tighter frame. */
.app-table {{
    padding: 8px 10px;
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
    background-color: {rgba(pal.selected_bg, 0.40)};
    color: {sel};
    border-radius: 6px;
    padding: 4px 10px;
}}
.end-button {{
    background-color: {red};
    background-image: none;
    color: #ffffff;
    border-radius: 10px;
    min-width: 20px;
    min-height: 20px;
    padding: 2px;
    border: none;
}}
.end-button:hover, .end-button:active, .end-button:focus,
.end-button:backdrop, .end-button:hover:active {{
    background-color: #dc2626;
    background-image: none;
    color: #ffffff;
    border: none;
}}
button.end-button, button.end-button:hover, button.end-button:active,
button.end-button:focus, button.end-button:backdrop {{
    background-color: {red};
    background-image: none;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    min-width: 20px;
    min-height: 20px;
    padding: 2px;
}}
button.end-button:hover, button.end-button:active, button.end-button:focus {{
    background-color: #dc2626;
    background-image: none;
    color: #ffffff;
}}
.page {{
    padding: 10px;
}}
.footer {{
    background-color: {c};
    border: 1px solid {b};
    border-radius: 12px;
    padding: 8px 6px;
    color: {t};
}}
.footer-item {{
    padding: 2px 12px;
}}
.footer-sep {{
    border-left: 1px solid {b};
}}
.col-header {{
    font-weight: bold;
    font-size: 11px;
    color: {m};
    background-color: transparent;
    border: none;
    padding: 2px 6px;
}}
.temp-cool {{
    color: {cool};
}}
.temp-warm {{
    color: {warm};
}}
.temp-hot {{
    color: {hot};
    font-weight: bold;
}}
paned > paned-handle {{
    background-color: {b};
    min-width: 4px;
    min-height: 4px;
    border: none;
}}
paned > paned-handle:hover {{
    background-color: {gpu_blue};
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
    for key in ("pane_gauges", "pane_graphs", "pane_mid_h"):
        val = data.get(key)
        if isinstance(val, (int, float)) and 0.1 <= val <= 0.9:
            result[key] = val
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


def _gtk_preference(gtk_settings: object) -> tuple:
    """Ask GTK for (prefer_dark, theme_name); (None, '') when unsupported."""
    try:
        return (bool(gtk_settings.get_gtk_application_prefer_dark_theme()),
                str(gtk_settings.get_gtk_theme_name() or ""))
    except AttributeError:
        return (None, "")


def _theme_from_environment() -> str:
    """Guess dark or light from GTK_THEME and the user's gtk-3.0 config."""
    if "dark" in os.environ.get("GTK_THEME", "").lower():
        return "dark"
    home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    ini = home / "gtk-3.0" / "gtk.ini"
    if ini.is_file():
        try:
            parser = configparser.ConfigParser()
            parser.read(ini)
            if parser.getboolean("GTK", "gtk-application-prefer-dark-theme",
                                 fallback=False):
                return "dark"
        except (configparser.Error, ValueError):
            pass
    return "light"


def resolve_theme(setting: str, gtk_settings: object) -> str:
    """Resolve 'system' to 'dark' or 'light' using GTK preferences."""
    if setting in ("dark", "light"):
        return setting
    prefer_dark, theme_name = _gtk_preference(gtk_settings)
    if prefer_dark is None:
        return _theme_from_environment()
    if prefer_dark:
        return "dark"
    if "dark" in theme_name.lower():
        return "dark"
    return "light"
