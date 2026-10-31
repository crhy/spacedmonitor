# SPDX-License-Identifier: GPL-3.0-or-later
"""UI theme test: verify the monitor follows desktop themes.

For each Spaced theme, spawn a subprocess with GTK_THEME set, capture a
screenshot, then assert:
  (a) the window background pixel matches the theme's theme_bg_color within 8/channel
  (b) a card's text is readable (contrast ratio >= 4.5)

Run from scripts/check.sh after ui_live.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "build" / "screenshots"
HELPER = str(ROOT / "tests" / "_ui_theme_helper.py")

# (theme_name, expected_bg_rgb)
THEMES = [
    ("Spaced-Mint", (0x2b, 0x2b, 0x2b)),
    ("Spaced-Dark", (0x38, 0x38, 0x38)),
    ("Spaced-Win11-Dark", (0x17, 0x24, 0x3b)),
    ("Spaced-Win7Aero-Dark", (0x18, 0x25, 0x33)),
    ("Spaced-Win11-Light", (0xf3, 0xf3, 0xf3)),
    ("Spaced-Linux-Light", (0xf3, 0xf3, 0xf3)),
]


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG relative luminance from 0-255 ints."""
    def lin(c: float) -> float:
        c = c / 255.0
        if c <= 0.0392:
            return c / 12.92
        if c <= 0.787:
            return ((c + 0.055) / 1.055) ** 2.4
        return c
    return 0.2127 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(lum1: float, lum2: float) -> float:
    """WCAG contrast ratio between two luminances."""
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def _capture(theme: str, out_path: Path) -> bool:
    """Spawn a subprocess with GTK_THEME and xvfb, capture screenshot."""
    env = os.environ.copy()
    env["GTK_THEME"] = theme
    cmd = [
        "env", f"GTK_THEME={theme}",
        "xvfb-run", "-a", "-s", "-screen 0 1400x900x24",
        sys.executable, HELPER, str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  subprocess stderr: {result.stderr[:200]}", file=sys.stderr)
        return False
    return out_path.exists() and out_path.stat().st_size > 1024


def _check_background(img: Image.Image, expected_rgb: tuple) -> bool:
    """Check that the window background matches expected within 8 per channel.

    The window bg shows in the page area (between cards and page padding).
    The topbar is ~40-50px tall; the page has 14px padding. Sample at
    y=55-70, x=5-15 (page padding area, left edge).
    """
    w, h = img.size
    # Page padding area: below topbar (~50px), in the left padding (x < 16)
    for y in range(55, min(75, h)):
        for x in range(2, min(16, w)):
            r, g, b = img.getpixel((x, y))[:3]
            if (abs(r - expected_rgb[0]) <= 8 and
                abs(g - expected_rgb[1]) <= 8 and
                abs(b - expected_rgb[2]) <= 8):
                return True
    # Fallback: scan a wider area in the page region
    for y in range(50, min(200, h)):
        for x in range(2, min(30, w)):
            r, g, b = img.getpixel((x, y))[:3]
            if (abs(r - expected_rgb[0]) <= 8 and
                abs(g - expected_rgb[1]) <= 8 and
                abs(b - expected_rgb[2]) <= 8):
                return True
    return False


def _check_text_contrast(img: Image.Image, theme: str) -> bool:
    """Check that card text is readable against card background.

    Sample a region where card text should be (card title area).
    We look for a cluster of pixels that differ significantly from the card bg.
    """
    w, h = img.size
    # The topbar is at the top. Cards start below it.
    # Card titles are bold text on card background.
    # Sample a horizontal strip in the card area (y ~ 80-120) and look for
    # text pixels (significantly different from the surrounding card bg).
    card_y_start = 60
    card_y_end = min(150, h)

    # Collect all unique colours in this strip
    colours: dict[tuple, int] = {}
    for y in range(card_y_start, card_y_end):
        for x in range(20, min(400, w)):
            px = img.getpixel((x, y))[:3]
            colours[px] = colours.get(px, 0) + 1

    if not colours:
        return False

    # The most common colour is the card background.
    # The second most common (or any colour with high contrast to the first)
    # is the text.
    sorted_colours = sorted(colours.items(), key=lambda x: x[1], reverse=True)
    bg_colour = sorted_colours[0][0]
    bg_lum = _relative_luminance(*bg_colour)

    # Find any colour with contrast ratio >= 4.5
    for colour, count in sorted_colours[1:]:
        lum = _relative_luminance(*colour)
        ratio = _contrast_ratio(bg_lum, lum)
        if ratio >= 4.5 and count > 5:
            return True
    return False


def main() -> int:
    """Run the theme tests."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    for theme_name, expected_bg in THEMES:
        out_path = SCREENSHOT_DIR / f"theme-{theme_name}.png"
        print(f"Testing {theme_name}...", end=" ", flush=True)

        if not _capture(theme_name, out_path):
            errors.append(f"FAIL: {theme_name} screenshot not captured")
            print("FAIL (capture)")
            continue

        img = Image.open(out_path)
        img = img.convert("RGB")

        # (a) Background check
        if not _check_background(img, expected_bg):
            errors.append(f"FAIL: {theme_name} background mismatch")
            print("FAIL (bg)", end=" ")
        else:
            print("bg OK", end=" ")

        # (b) Text contrast check
        if not _check_text_contrast(img, theme_name):
            errors.append(f"FAIL: {theme_name} text contrast too low")
            print("FAIL (contrast)")
        else:
            print("contrast OK")

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
