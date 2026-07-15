"""Application theme helpers."""

from __future__ import annotations

import colorsys
import struct
import re
import zlib

from .constants import ACCENT_COLOR, LUMI_SUN_VALLEY_THEME_PATH


UI_THEME_SETTING_KEY = "ui_theme"
UI_THEME_LIGHT = "light"
UI_THEME_DARK = "dark"
ACCENT_COLOR_SETTING_KEY = "accent_color"

LUMI_THEME_LIGHT = "lumi-sun-valley-light"
LUMI_THEME_DARK = "lumi-sun-valley-dark"
LUMI_THEME_DIR = LUMI_SUN_VALLEY_THEME_PATH.parent / "theme"

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
_BASE_SPRITE_ACCENTS = {
    "light": "#005fb8",
    "dark": "#57c8ff",
}
_NEUTRAL_SPRITE_NAMES = {
    "tab-hover",
    "tab-rest",
    "tab-selected",
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
    blended = tuple(round(source[index] + (target[index] - source[index]) * amount) for index in range(3))
    return rgb_to_hex(*blended)


def readable_foreground_for(hex_color: str) -> str:
    red, green, blue = (component / 255 for component in hex_to_rgb(hex_color))

    def linearize(channel: float) -> float:
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * linearize(red) + 0.7152 * linearize(green) + 0.0722 * linearize(blue)
    return "#1c1c1c" if luminance > 0.5 else "#ffffff"


def derive_accent_palette(accent_color: str) -> dict[str, str]:
    accent = normalize_accent_color(accent_color)
    return {
        "accent": accent,
        "dark": blend_hex_color(accent, "#000000", 0.22),
        "light": blend_hex_color(accent, "#ffffff", 0.88),
        "foreground": readable_foreground_for(accent),
    }


def tint_accent_png(png_data: bytes, accent_color: str, *, base_accent: str = ACCENT_COLOR) -> bytes:
    try:
        png = _decode_rgba_png(png_data)
    except ValueError:
        return png_data
    if png is None:
        return png_data

    width, height, pixels = png
    base_hsv = _hex_to_hsv(base_accent)
    accent_hsv = _hex_to_hsv(accent_color)

    for index in range(0, len(pixels), 4):
        alpha = pixels[index + 3]
        if alpha == 0:
            continue

        rgb = (pixels[index], pixels[index + 1], pixels[index + 2])
        if not _is_base_accent_pixel(rgb, base_hsv):
            continue

        recolored = _recolor_accent_pixel(rgb, base_hsv, accent_hsv)
        pixels[index : index + 3] = recolored

    return _encode_rgba_png(width, height, bytes(pixels))


def load_lumi_theme(root, ttk_module) -> bool:
    if getattr(root, "_lumi_theme_loaded", False):
        return True

    if not LUMI_SUN_VALLEY_THEME_PATH.is_file():
        return False

    style = ttk_module.Style(root)
    style.tk.call("source", str(LUMI_SUN_VALLEY_THEME_PATH))
    root._lumi_theme_loaded = True  # type: ignore[attr-defined]
    return True


def set_lumi_theme(root, ttk_module, theme_name: str) -> bool:
    if not load_lumi_theme(root, ttk_module):
        return False

    theme = normalize_ui_theme_name(theme_name)
    style = ttk_module.Style(root)
    style.theme_use(LUMI_THEME_DARK if theme == UI_THEME_DARK else LUMI_THEME_LIGHT)
    return True


def apply_lumi_accent(root, tk_module, ttk_module, accent_color: str) -> bool:
    if not load_lumi_theme(root, ttk_module):
        return False

    accent = normalize_accent_color(accent_color)
    current_accent = getattr(root, "_lumi_theme_accent", normalize_accent_color(ACCENT_COLOR))
    if current_accent == accent:
        _set_theme_color_variables(root, accent)
        return True

    sprite_info = _get_sprite_info(root)
    for mode, base_accent in _BASE_SPRITE_ACCENTS.items():
        base_path = LUMI_THEME_DIR / f"spritesheet_{mode}_base.png"
        if not base_path.is_file():
            return False

        base_image = tk_module.PhotoImage(master=root, file=str(base_path))
        try:
            _recolor_theme_images(root, base_image, sprite_info, mode, base_accent, accent)
        finally:
            try:
                root.tk.call("image", "delete", str(base_image))
            except Exception:
                pass

    _set_theme_color_variables(root, accent)
    root._lumi_theme_accent = accent  # type: ignore[attr-defined]
    return True


def _set_theme_color_variables(root, accent_color: str) -> None:
    foreground = readable_foreground_for(accent_color)
    for namespace in ("lumi_sv_light", "lumi_sv_dark"):
        for key, value in (("-selbg", accent_color), ("-accent", accent_color), ("-selfg", foreground)):
            try:
                root.tk.call("set", f"::ttk::theme::{namespace}::colors({key})", value)
            except Exception:
                pass


def _get_sprite_info(root) -> list[tuple[str, int, int, int, int]]:
    raw_values = root.tk.splitlist(root.tk.call("set", "::spriteinfo"))
    if len(raw_values) % 5 != 0:
        return []

    sprites: list[tuple[str, int, int, int, int]] = []
    for index in range(0, len(raw_values), 5):
        name, x, y, width, height = raw_values[index : index + 5]
        sprites.append((str(name), int(x), int(y), int(width), int(height)))
    return sprites


def _recolor_theme_images(
    root,
    base_image,
    sprite_info: list[tuple[str, int, int, int, int]],
    mode: str,
    base_accent: str,
    accent_color: str,
) -> None:
    namespace = f"lumi_sv_{mode}"
    base_hsv = _hex_to_hsv(base_accent)
    accent_hsv = _hex_to_hsv(accent_color)

    for sprite_name, x, y, width, height in sprite_info:
        if sprite_name in _NEUTRAL_SPRITE_NAMES:
            continue

        try:
            image_name = root.tk.call("set", f"::ttk::theme::{namespace}::I({sprite_name})")
        except Exception:
            continue

        root.tk.call(image_name, "copy", str(base_image), "-from", x, y, x + width, y + height)
        for row in range(height):
            for column in range(width):
                rgb = _photo_pixel_to_rgb(base_image.get(x + column, y + row))
                if rgb is None or not _is_accent_blue(rgb):
                    continue
                root.tk.call(
                    image_name,
                    "put",
                    _recolor_blue_pixel(rgb, base_hsv, accent_hsv),
                    "-to",
                    column,
                    row,
                )


def _photo_pixel_to_rgb(pixel: object) -> tuple[int, int, int] | None:
    if isinstance(pixel, tuple) and len(pixel) >= 3:
        return int(pixel[0]), int(pixel[1]), int(pixel[2])
    if isinstance(pixel, str):
        if pixel.startswith("#") and len(pixel) >= 7:
            return int(pixel[1:3], 16), int(pixel[3:5], 16), int(pixel[5:7], 16)
        parts = pixel.split()
        if len(parts) >= 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
    return None


def _hex_to_hsv(hex_color: str) -> tuple[float, float, float]:
    red, green, blue = (component / 255 for component in hex_to_rgb(hex_color))
    return colorsys.rgb_to_hsv(red, green, blue)


def _is_accent_blue(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = rgb
    hue, saturation, _value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    return 0.52 <= hue <= 0.62 and saturation >= 0.25 and blue > red + 15 and blue >= green


def _recolor_blue_pixel(
    rgb: tuple[int, int, int],
    base_hsv: tuple[float, float, float],
    accent_hsv: tuple[float, float, float],
) -> str:
    red, green, blue = rgb
    _hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    _base_hue, base_saturation, base_value = base_hsv
    accent_hue, accent_saturation, accent_value = accent_hsv

    saturation_scale = saturation / base_saturation if base_saturation else 1
    value_scale = value / base_value if base_value else 1
    new_saturation = max(0.0, min(0.95, accent_saturation * min(1.2, saturation_scale)))
    new_value = max(0.0, min(0.98, accent_value * value_scale))
    new_rgb = colorsys.hsv_to_rgb(accent_hue, new_saturation, new_value)
    return rgb_to_hex(*(round(channel * 255) for channel in new_rgb))


def _is_base_accent_pixel(rgb: tuple[int, int, int], base_hsv: tuple[float, float, float]) -> bool:
    red, green, blue = rgb
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    base_hue, _base_saturation, _base_value = base_hsv
    hue_distance = abs(hue - base_hue)
    hue_distance = min(hue_distance, 1 - hue_distance)
    return hue_distance <= 0.08 and saturation >= 0.15 and value >= 0.08


def _recolor_accent_pixel(
    rgb: tuple[int, int, int],
    base_hsv: tuple[float, float, float],
    accent_hsv: tuple[float, float, float],
) -> bytes:
    red, green, blue = rgb
    _hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    _base_hue, base_saturation, base_value = base_hsv
    accent_hue, accent_saturation, accent_value = accent_hsv

    saturation_scale = saturation / base_saturation if base_saturation else 1
    value_scale = value / base_value if base_value else 1
    new_saturation = max(0.0, min(0.95, accent_saturation * min(1.2, saturation_scale)))
    new_value = max(0.0, min(0.98, accent_value * value_scale))
    new_rgb = colorsys.hsv_to_rgb(accent_hue, new_saturation, new_value)
    return bytes(round(channel * 255) for channel in new_rgb)


def _decode_rgba_png(png_data: bytes) -> tuple[int, int, bytearray] | None:
    if not png_data.startswith(_PNG_SIGNATURE):
        return None

    cursor = len(_PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    idat_chunks: list[bytes] = []
    while cursor + 8 <= len(png_data):
        chunk_length = struct.unpack(">I", png_data[cursor : cursor + 4])[0]
        chunk_type = png_data[cursor + 4 : cursor + 8]
        chunk_data_start = cursor + 8
        chunk_data_end = chunk_data_start + chunk_length
        if chunk_data_end + 4 > len(png_data):
            return None

        chunk_data = png_data[chunk_data_start:chunk_data_end]
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break
        cursor = chunk_data_end + 4

    if (
        width is None
        or height is None
        or bit_depth != 8
        or color_type != 6
        or interlace != 0
        or not idat_chunks
    ):
        return None

    try:
        filtered = zlib.decompress(b"".join(idat_chunks))
    except zlib.error:
        return None

    return width, height, _unfilter_rgba_png(width, height, filtered)


def _unfilter_rgba_png(width: int, height: int, filtered: bytes) -> bytearray:
    bytes_per_pixel = 4
    row_length = width * bytes_per_pixel
    expected_length = height * (row_length + 1)
    if len(filtered) != expected_length:
        raise ValueError("Unexpected PNG scanline length.")

    pixels = bytearray(width * height * bytes_per_pixel)
    previous_row = bytearray(row_length)
    cursor = 0
    output_cursor = 0
    for _row in range(height):
        filter_type = filtered[cursor]
        cursor += 1
        raw_row = filtered[cursor : cursor + row_length]
        cursor += row_length
        row = bytearray(row_length)

        for index, value in enumerate(raw_row):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous_row[index]
            up_left = previous_row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = _paeth_predictor(left, up, up_left)
            else:
                raise ValueError(f"Unsupported PNG filter type: {filter_type}.")
            row[index] = (value + predictor) & 0xFF

        pixels[output_cursor : output_cursor + row_length] = row
        output_cursor += row_length
        previous_row = row

    return pixels


def _encode_rgba_png(width: int, height: int, pixels: bytes) -> bytes:
    row_length = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        start = row * row_length
        raw.extend(pixels[start : start + row_length])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            _PNG_SIGNATURE,
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw))),
            _png_chunk(b"IEND", b""),
        )
    )


def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(chunk_data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(chunk_data)) + chunk_type + chunk_data + struct.pack(">I", crc)


def _paeth_predictor(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    up_left_distance = abs(estimate - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left
