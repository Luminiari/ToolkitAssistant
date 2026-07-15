"""Regenerate Lumi Sun Valley accent sprites from the preserved base sheets."""

from __future__ import annotations

import argparse
import colorsys
import re
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
THEME_DIR = ROOT / "assets" / "lumi-sun-valley-theme" / "theme"
DEFAULT_ACCENT = "#955ab0"
BASE_ACCENTS = {
    "light": "#005fb8",
    "dark": "#57c8ff",
}
TAB_SPRITES = {
    "tab-hover": (130, 0, 32, 32),
    "tab-rest": (130, 32, 32, 32),
    "tab-selected": (120, 64, 32, 32),
}
TAB_PALETTES = {
    "light": {
        "rest_fill": (250, 250, 250, 0),
        "rest_outline": (218, 218, 218, 255),
        "hover_fill": (250, 250, 250, 160),
        "hover_outline": (202, 202, 202, 255),
        "selected_fill": (250, 250, 250, 255),
        "selected_outline": (202, 202, 202, 255),
    },
    "dark": {
        "rest_fill": (28, 28, 28, 0),
        "rest_outline": (70, 70, 70, 255),
        "hover_fill": (34, 34, 34, 180),
        "hover_outline": (82, 82, 82, 255),
        "selected_fill": (28, 28, 28, 255),
        "selected_outline": (90, 90, 90, 255),
    },
}


def hex_to_hsv(hex_color: str) -> tuple[float, float, float]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
        raise ValueError(f"Expected a #RRGGBB color, got {hex_color!r}.")

    red = int(hex_color[1:3], 16) / 255
    green = int(hex_color[3:5], 16) / 255
    blue = int(hex_color[5:7], 16) / 255
    return colorsys.rgb_to_hsv(red, green, blue)


def recolor_spritesheet(source: Path, target: Path, *, base_hex: str, accent_hex: str) -> None:
    _base_h, base_s, base_v = hex_to_hsv(base_hex)
    target_h, target_s, target_v = hex_to_hsv(accent_hex)
    image = Image.open(source).convert("RGBA")
    pixels = image.load()

    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue

            hue, sat, val = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            is_accent_blue = (
                0.52 <= hue <= 0.62
                and sat >= 0.25
                and blue > red + 15
                and blue >= green
            )
            if not is_accent_blue:
                continue

            sat_scale = sat / base_s if base_s else 1
            val_scale = val / base_v if base_v else 1
            new_sat = max(0.0, min(0.95, target_s * min(1.2, sat_scale)))
            new_val = max(0.0, min(0.98, target_v * val_scale))
            new_rgb = colorsys.hsv_to_rgb(target_h, new_sat, new_val)
            pixels[x, y] = tuple(round(channel * 255) for channel in new_rgb) + (alpha,)

    image.save(target)


def update_theme_colors(path: Path, accent: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'(-selbg\s+)"#[0-9a-fA-F]{6}"', rf'\1"{accent}"', text)
    text = re.sub(r'(-accent\s+)"#[0-9a-fA-F]{6}"', rf'\1"{accent}"', text)
    path.write_text(text, encoding="utf-8")


def draw_tab_sprite(fill: tuple[int, int, int, int], outline: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 2, 31, 29), radius=4, fill=fill, outline=outline, width=1)
    draw.rectangle((0, 25, 31, 29), fill=fill)
    draw.line((0, 25, 0, 29), fill=outline)
    draw.line((31, 25, 31, 29), fill=outline)
    draw.line((0, 29, 31, 29), fill=outline)
    return image


def write_clean_tab_sprites(path: Path, mode: str) -> None:
    image = Image.open(path).convert("RGBA")
    palette = TAB_PALETTES[mode]
    replacements = {
        "tab-rest": draw_tab_sprite(palette["rest_fill"], palette["rest_outline"]),
        "tab-hover": draw_tab_sprite(palette["hover_fill"], palette["hover_outline"]),
        "tab-selected": draw_tab_sprite(palette["selected_fill"], palette["selected_outline"]),
    }

    for name, replacement in replacements.items():
        x, y, _width, _height = TAB_SPRITES[name]
        image.paste(replacement, (x, y))

    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accent", default=DEFAULT_ACCENT, help="Accent color as #RRGGBB.")
    args = parser.parse_args()

    accent = args.accent.lower()
    hex_to_hsv(accent)

    for mode, base in BASE_ACCENTS.items():
        recolor_spritesheet(
            THEME_DIR / f"spritesheet_{mode}_base.png",
            THEME_DIR / f"spritesheet_{mode}.png",
            base_hex=base,
            accent_hex=accent,
        )
        write_clean_tab_sprites(THEME_DIR / f"spritesheet_{mode}.png", mode)
        update_theme_colors(THEME_DIR / f"{mode}.tcl", accent)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
