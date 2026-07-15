from __future__ import annotations

import ast
import ctypes
from pathlib import Path
import pkgutil
import re
import shutil
import struct
from ctypes import wintypes


ROOT = Path(__file__).resolve().parent
DIST_ROOT = ROOT / "dist"
BUNDLE_NAME = "ToolkitAssistant"
BUNDLE_DIR = DIST_ROOT / BUNDLE_NAME
RUNTIME_DIR = BUNDLE_DIR / "runtime"
ASSET_DIR = ROOT / "assets"
ICON_PATH = ASSET_DIR / "ToolkitAssistant.ico"
VERSION_INFO_PATH = ROOT / "version_info.txt"
RT_VERSION = 16
VERSION_RESOURCE_ID = 1
LANG_EN_AU = 0x0C09
UNICODE_CODEPAGE = 1200


VERSION_STRING_TO_PY2EXE_KEY = {
    "Comments": "comments",
    "CompanyName": "company_name",
    "FileDescription": "description",
    "FileVersion": "version",
    "InternalName": "internal_name",
    "LegalCopyright": "copyright",
    "LegalTrademarks": "trademarks",
    "PrivateBuild": "private_build",
    "ProductName": "product_name",
    "ProductVersion": "product_version",
    "SpecialBuild": "special_build",
}


def read_version_info() -> dict[str, str]:
    metadata = parse_version_info_metadata()
    strings = metadata["strings"]
    return {
        "version": strings.get("FileVersion", "0.0.0.0"),
        "description": strings.get("FileDescription", "Lumi's Toolkit Assistant"),
        "company_name": strings.get("CompanyName", "Luminiari"),
        "product_name": strings.get("ProductName", "Lumi's Toolkit Assistant"),
        "product_version": strings.get("ProductVersion", "0.0.0.0"),
        "copyright": strings.get("LegalCopyright", "Copyright (c) 2026 Luminiari. All rights reserved."),
        "internal_name": strings.get("InternalName", "ToolkitAssistant"),
    }


def parse_version_info_metadata() -> dict[str, object]:
    try:
        text = VERSION_INFO_PATH.read_text(encoding="utf-8")
    except OSError:
        text = ""

    strings: dict[str, str] = {}
    quoted_string = r'"(?:\\.|[^"])*"'
    string_pattern = re.compile(rf"StringStruct\(\s*({quoted_string})\s*,\s*({quoted_string})\s*\)")
    for name_literal, value_literal in string_pattern.findall(text):
        strings[ast.literal_eval(name_literal)] = ast.literal_eval(value_literal)

    fixed = {
        "filevers": _parse_tuple_field(text, "filevers", (0, 0, 0, 0)),
        "prodvers": _parse_tuple_field(text, "prodvers", (0, 0, 0, 0)),
        "mask": _parse_int_field(text, "mask", 0x3F),
        "flags": _parse_int_field(text, "flags", 0x0),
        "OS": _parse_int_field(text, "OS", 0x40004),
        "fileType": _parse_int_field(text, "fileType", 0x1),
        "subtype": _parse_int_field(text, "subtype", 0x0),
        "date": _parse_tuple_field(text, "date", (0, 0)),
    }

    table_match = re.search(r'StringTable\(\s*"([0-9A-Fa-f]{8})"', text)
    translation_match = re.search(r'VarStruct\(\s*"Translation"\s*,\s*\[([^\]]+)\]\s*\)', text)
    if translation_match:
        translation_values = [
            int(value.strip(), 0)
            for value in translation_match.group(1).split(",")
            if value.strip()
        ]
    else:
        translation_values = [LANG_EN_AU, UNICODE_CODEPAGE]

    language = translation_values[0] if len(translation_values) >= 1 else LANG_EN_AU
    codepage = translation_values[1] if len(translation_values) >= 2 else UNICODE_CODEPAGE
    table_key = table_match.group(1).upper() if table_match else f"{language:04X}{codepage:04X}"

    return {
        "strings": strings,
        "fixed": fixed,
        "language": language,
        "codepage": codepage,
        "table_key": table_key,
    }


def _parse_int_field(text: str, name: str, fallback: int) -> int:
    match = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)", text)
    return int(match.group(1), 0) if match else fallback


def _parse_tuple_field(text: str, name: str, fallback: tuple[int, ...]) -> tuple[int, ...]:
    match = re.search(rf"\b{name}\s*=\s*\(([^)]*)\)", text)
    if not match:
        return fallback
    values = tuple(int(value.strip(), 0) for value in match.group(1).split(",") if value.strip())
    return values or fallback


def toolkit_modules() -> list[str]:
    package_root = ROOT / "toolkit_assistant"
    modules = ["toolkit_assistant"]
    modules.extend(
        module.name
        for module in pkgutil.walk_packages([str(package_root)], "toolkit_assistant.")
    )
    return modules


def copy_runtime_files() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if VERSION_INFO_PATH.is_file():
        shutil.copy2(VERSION_INFO_PATH, RUNTIME_DIR / "version_info.txt")

    if ASSET_DIR.is_dir():
        shutil.copytree(ASSET_DIR, RUNTIME_DIR / "assets", dirs_exist_ok=True)


def remove_stale_build_outputs() -> None:
    for path in (
        DIST_ROOT / "ToolkitAssistant.exe",
    ):
        if path.is_file():
            path.unlink()


def patch_py2exe_error_log_path(py2exe_runtime) -> None:
    original_get_data = py2exe_runtime.pkgutil.get_data

    def get_data(package: str, resource: str) -> bytes:
        data = original_get_data(package, resource)
        if package == "py2exe" and resource == "boot_common.py":
            text = data.decode("utf-8")
            old = (
                '        _fname = os.path.join(os.environ["APPDATA"],\n'
                "                                os.path.splitext(os.path.basename(sys.executable))[0] + '.log')"
            )
            line_break = "\n"
            if old not in text:
                old = old.replace("\n", "\r\n")
                line_break = "\r\n"
            if old not in text:
                raise RuntimeError("Could not patch py2exe error log path.")

            new = (
                '        _log_dir = os.path.join(os.environ["APPDATA"], "ToolkitAssistant")\n'
                "        try:\n"
                "            os.makedirs(_log_dir, exist_ok=True)\n"
                "        except Exception:\n"
                '            _log_dir = os.environ["APPDATA"]\n'
                "        _fname = os.path.join(_log_dir,\n"
                "                                os.path.splitext(os.path.basename(sys.executable))[0] + '.log')"
            ).replace("\n", line_break)
            text = text.replace(old, new)
            return text.encode("utf-8")
        return data

    py2exe_runtime.pkgutil.get_data = get_data


def build_version_resource(metadata: dict[str, object]) -> bytes:
    fixed = metadata["fixed"]
    strings = metadata["strings"]
    table_key = metadata["table_key"]
    language = int(metadata["language"])
    codepage = int(metadata["codepage"])

    fixed_info = build_fixed_file_info(fixed)
    string_structs = [
        build_string_struct(name, value)
        for name, value in sorted(strings.items())
    ]
    string_table = build_version_block(str(table_key), children=string_structs, value_type=1)
    string_file_info = build_version_block("StringFileInfo", children=[string_table], value_type=1)

    translation = struct.pack("<HH", language, codepage)
    translation_block = build_version_block(
        "Translation",
        value=translation,
        value_length=len(translation),
        value_type=0,
    )
    var_file_info = build_version_block("VarFileInfo", children=[translation_block], value_type=1)

    return build_version_block(
        "VS_VERSION_INFO",
        value=fixed_info,
        value_length=len(fixed_info),
        value_type=0,
        children=[string_file_info, var_file_info],
    )


def build_fixed_file_info(fixed: object) -> bytes:
    fixed_info = fixed if isinstance(fixed, dict) else {}
    file_version = _four_part_version(fixed_info.get("filevers", (0, 0, 0, 0)))
    product_version = _four_part_version(fixed_info.get("prodvers", (0, 0, 0, 0)))
    date = _two_part_value(fixed_info.get("date", (0, 0)))
    return struct.pack(
        "<13I",
        0xFEEF04BD,
        0x00010000,
        file_version[0],
        file_version[1],
        product_version[0],
        product_version[1],
        int(fixed_info.get("mask", 0x3F)),
        int(fixed_info.get("flags", 0x0)),
        int(fixed_info.get("OS", 0x40004)),
        int(fixed_info.get("fileType", 0x1)),
        int(fixed_info.get("subtype", 0x0)),
        date[0],
        date[1],
    )


def _four_part_version(value: object) -> tuple[int, int]:
    parts = tuple(int(part) for part in value) if isinstance(value, tuple) else (0, 0, 0, 0)
    parts = (parts + (0, 0, 0, 0))[:4]
    return ((parts[0] << 16) | parts[1], (parts[2] << 16) | parts[3])


def _two_part_value(value: object) -> tuple[int, int]:
    parts = tuple(int(part) for part in value) if isinstance(value, tuple) else (0, 0)
    parts = (parts + (0, 0))[:2]
    return parts[0], parts[1]


def build_string_struct(name: str, value: str) -> bytes:
    encoded_value = _utf16le_z(value)
    return build_version_block(
        name,
        value=encoded_value,
        value_length=len(value) + 1,
        value_type=1,
    )


def build_version_block(
    key: str,
    *,
    value: bytes = b"",
    value_length: int = 0,
    value_type: int = 1,
    children: list[bytes] | None = None,
) -> bytes:
    children = children or []
    header = struct.pack("<HHH", 0, value_length, value_type) + _utf16le_z(key)
    data = header + _dword_padding(len(header)) + value
    data += _dword_padding(len(data))
    for child in children:
        data += child
    return struct.pack("<H", len(data)) + data[2:]


def _utf16le_z(value: str) -> bytes:
    return value.encode("utf-16le") + b"\x00\x00"


def _dword_padding(length: int) -> bytes:
    return b"\x00" * ((4 - (length % 4)) % 4)


def patch_executable_version_resource(exe_path: Path, metadata: dict[str, object]) -> None:
    language = int(metadata["language"])
    version_resource = build_version_resource(metadata)
    existing_languages = set(enum_version_resource_languages(exe_path))

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.UpdateResourceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.UpdateResourceW.restype = wintypes.BOOL
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    kernel32.EndUpdateResourceW.restype = wintypes.BOOL

    update_handle = kernel32.BeginUpdateResourceW(str(exe_path), False)
    if not update_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    discard_changes = True
    try:
        for existing_language in existing_languages - {language}:
            if not kernel32.UpdateResourceW(
                update_handle,
                ctypes.c_void_p(RT_VERSION),
                ctypes.c_void_p(VERSION_RESOURCE_ID),
                existing_language,
                None,
                0,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

        resource_buffer = ctypes.create_string_buffer(version_resource)
        if not kernel32.UpdateResourceW(
            update_handle,
            ctypes.c_void_p(RT_VERSION),
            ctypes.c_void_p(VERSION_RESOURCE_ID),
            language,
            resource_buffer,
            len(version_resource),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        discard_changes = False
    finally:
        if not kernel32.EndUpdateResourceW(update_handle, discard_changes):
            raise ctypes.WinError(ctypes.get_last_error())


def enum_version_resource_languages(exe_path: Path) -> list[int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel32.FreeLibrary.restype = wintypes.BOOL

    enum_callback = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMODULE,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.WORD,
        wintypes.LPARAM,
    )
    kernel32.EnumResourceLanguagesW.argtypes = [
        wintypes.HMODULE,
        wintypes.LPVOID,
        wintypes.LPVOID,
        enum_callback,
        wintypes.LPARAM,
    ]
    kernel32.EnumResourceLanguagesW.restype = wintypes.BOOL

    languages: list[int] = []

    @enum_callback
    def collect_language(_module, _resource_type, _resource_name, language, _param):
        languages.append(int(language))
        return True

    module = kernel32.LoadLibraryExW(str(exe_path), None, 0x00000002)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        ctypes.set_last_error(0)
        success = kernel32.EnumResourceLanguagesW(
            module,
            ctypes.c_void_p(RT_VERSION),
            ctypes.c_void_p(VERSION_RESOURCE_ID),
            collect_language,
            0,
        )
        if not success and ctypes.get_last_error() != 0:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.FreeLibrary(module)

    return languages


def verify_executable_version_language(exe_path: Path, expected_language: int) -> None:
    languages = enum_version_resource_languages(exe_path)
    if languages != [expected_language]:
        formatted = ", ".join(f"0x{language:04X}" for language in languages) or "none"
        raise RuntimeError(
            f"Expected ToolkitAssistant.exe version resource language 0x{expected_language:04X}, found {formatted}."
        )


def main() -> None:
    from py2exe import freeze
    import py2exe.runtime as py2exe_runtime

    version_metadata = parse_version_info_metadata()
    version_info = read_version_info()
    target = {
        "script": str(ROOT / "ToolkitAssistant.pyw"),
        "dest_base": "ToolkitAssistant",
        "version_info": version_info,
    }

    if ICON_PATH.is_file():
        target["icon_resources"] = [(1, str(ICON_PATH))]

    remove_stale_build_outputs()
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    patch_py2exe_error_log_path(py2exe_runtime)

    freeze(
        windows=[target],
        zipfile=str(Path("runtime") / "library.zip"),
        options={
            "dist_dir": str(BUNDLE_DIR),
            "bundle_files": 3,
            "compressed": 1,
            "includes": [
                "tkinter",
                "tkinter.colorchooser",
                "tkinter.ttk",
                "tkinter.filedialog",
                "tkinter.messagebox",
                "_tkinter",
                *toolkit_modules(),
            ],
        },
        version_info=version_info,
    )

    exe_path = BUNDLE_DIR / "ToolkitAssistant.exe"
    patch_executable_version_resource(exe_path, version_metadata)
    verify_executable_version_language(exe_path, int(version_metadata["language"]))
    copy_runtime_files()


if __name__ == "__main__":
    main()
