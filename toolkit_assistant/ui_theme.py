from __future__ import annotations

import re

from .constants import ACCENT_COLOR


UI_THEME_SETTING_KEY = "ui_theme"
UI_THEME_LIGHT = "light"
UI_THEME_DARK = "dark"
ACCENT_COLOR_SETTING_KEY = "accent_color"

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def normalize_ui_theme_name(value: object) -> str:
    return UI_THEME_DARK if str(value).lower() == UI_THEME_DARK else UI_THEME_LIGHT


def normalize_accent_color(value: object) -> str:
    color = str(value).strip()
    if not color.startswith("#"):
        color = f"#{color}"
    if not _HEX_COLOR_RE.fullmatch(color):
        return ACCENT_COLOR
    return color.lower()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    color = normalize_accent_color(hex_color)
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


def blend_hex_color(hex_color: str, target_hex_color: str, amount: float) -> str:
    source = hex_to_rgb(hex_color)
    target = hex_to_rgb(target_hex_color)
    blended = tuple(
        round(source[index] + (target[index] - source[index]) * amount)
        for index in range(3)
    )
    return rgb_to_hex(*blended)


def readable_foreground_for(hex_color: str) -> str:
    red, green, blue = (component / 255 for component in hex_to_rgb(hex_color))

    def linearize(channel: float) -> float:
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * linearize(red)
        + 0.7152 * linearize(green)
        + 0.0722 * linearize(blue)
    )
    return "#1c1c1c" if luminance > 0.5 else "#ffffff"


def derive_accent_palette(accent_color: str) -> dict[str, str]:
    accent = normalize_accent_color(accent_color)
    return {
        "accent": accent,
        "dark": blend_hex_color(accent, "#000000", 0.22),
        "light": blend_hex_color(accent, "#ffffff", 0.88),
        "foreground": readable_foreground_for(accent),
    }


__all__ = [
    "ACCENT_COLOR_SETTING_KEY",
    "UI_THEME_DARK",
    "UI_THEME_LIGHT",
    "UI_THEME_SETTING_KEY",
    "blend_hex_color",
    "derive_accent_palette",
    "hex_to_rgb",
    "normalize_accent_color",
    "normalize_ui_theme_name",
    "readable_foreground_for",
    "rgb_to_hex",
]
