from __future__ import annotations

from pathlib import Path
import pkgutil
import re
import shutil

from py2exe import freeze
import py2exe.runtime as py2exe_runtime


ROOT = Path(__file__).resolve().parent
DIST_ROOT = ROOT / "dist"
BUNDLE_NAME = "ToolkitAssistant"
BUNDLE_DIR = DIST_ROOT / BUNDLE_NAME
RUNTIME_DIR = BUNDLE_DIR / "runtime"
ASSET_DIR = ROOT / "assets"
ICON_PATH = ASSET_DIR / "ToolkitAssistant.ico"
VERSION_INFO_PATH = ROOT / "version_info.txt"


def read_version_info() -> dict[str, str]:
    try:
        text = VERSION_INFO_PATH.read_text(encoding="utf-8")
    except OSError:
        text = ""

    def field(name: str, fallback: str) -> str:
        match = re.search(rf'StringStruct\("{name}",\s*"([^"]+)"\)', text)
        return match.group(1) if match is not None else fallback

    return {
        "version": field("FileVersion", "0.0.0.0"),
        "description": field("FileDescription", "Lumi's Toolkit Assistant"),
        "company_name": field("CompanyName", "Luminiari"),
        "product_name": field("ProductName", "Lumi's Toolkit Assistant"),
        "product_version": field("ProductVersion", "0.0.0.0"),
        "copyright": field("LegalCopyright", "Copyright (c) 2026 Luminiari. All rights reserved."),
        "internal_name": field("InternalName", "ToolkitAssistant"),
    }


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


def patch_py2exe_error_log_path() -> None:
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

patch_py2exe_error_log_path()

freeze(
    windows=[target],
    zipfile=str(Path("runtime") / "library.zip"),
    options={
        "dist_dir": str(BUNDLE_DIR),
        "bundle_files": 3,
        "compressed": 1,
        "includes": [
            "tkinter",
            "tkinter.ttk",
            "tkinter.filedialog",
            "tkinter.messagebox",
            "_tkinter",
            *toolkit_modules(),
        ],
    },
    version_info=version_info,
)

copy_runtime_files()
