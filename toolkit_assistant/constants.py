"""Application constants for Toolkit Assistant."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


APP_TITLE = "Lumi's Toolkit Assistant"
APP_HEADING = "larian y u make this so hard"
ACCENT_COLOR = "#955ab0"
ACCENT_DARK_COLOR = "#75448c"
ACCENT_LIGHT_COLOR = "#f4edf7"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
PACKAGED_RESOURCE_DIR = APP_DIR / "runtime"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PACKAGED_RESOURCE_DIR if PACKAGED_RESOURCE_DIR.exists() else APP_DIR))
VERSION_INFO_PATH = RESOURCE_DIR / "version_info.txt"
APP_ICON_PATH = RESOURCE_DIR / "assets" / "ToolkitAssistant.ico"
SETTINGS_PATH = (
    Path(os.environ["APPDATA"]) / "ToolkitAssistant" / "settings.json"
    if os.environ.get("APPDATA")
    else APP_DIR / "settings.json"
)
def read_app_version() -> str:
    try:
        version_info_text = VERSION_INFO_PATH.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0.0"

    for field_name in ("ProductVersion", "FileVersion"):
        match = re.search(rf'StringStruct\("{field_name}",\s*"([^"]+)"\)', version_info_text)
        if match is not None:
            return match.group(1)

    return "0.0.0.0"

APP_VERSION = read_app_version()
INTRO_DISMISSED_KEY = "intro_dismissed"
LSLIB_RELEASES_URL = "https://github.com/Norbyte/lslib/releases"
TOOLKIT_ASSISTANT_WIKI_URL = "https://github.com/Luminiari/ToolkitAssistant/wiki"
TEMPORARY_FILES_ROOT = SETTINGS_PATH.parent / "temporary_backups"
TEMPORARY_RENAME_BACKUP_ROOT = TEMPORARY_FILES_ROOT / "rename"
TEMPORARY_RENAME_BACKUP_RETENTION_DAYS = 30
ABOUT_LINKS = (
    ("Patreon", "https://www.patreon.com/c/Luminiari", "about-patreon.png"),
    ("GitHub", "https://github.com/Luminiari/ToolkitAssistant", "about-github.png"),
    ("Bluesky", "https://bsky.app/profile/luminiari.moe", "about-bluesky.png"),
    ("Carrd", "https://luminiarimods.carrd.co", "about-carrd.png"),
)
BOUNDS_ATTRIBUTE_IDS = {
    "BoundsMin",
    "BoundsMax",
    "Center",
    "Radius",
    "Min",
    "Max",
    "Height",
    "Shape",
    "Type",
    "IsIgnoringScale",
}
PROJECT_BACKUP_SOURCES = (
    ((), ()),
    (("Projects",), ("Projects",)),
    (("Editor", "Mods"), ("Editor", "Mods")),
    (("Mods",), ("Mods",)),
    (("Public",), ("Public",)),
    (("Generated", "Public"), ("Generated", "Public")),
)
PROJECT_RENAME_TARGETS = (
    (),
    ("Editor", "Mods"),
    ("Generated", "Public"),
    ("Mods",),
    ("Projects",),
    ("Public",),
)
MOD_FOLDER_UUID_SUFFIX_RE = re.compile(
    r"_(?P<uuid>[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})$"
)
WINDOWS_INVALID_FILENAME_CHARS = set('<>:"/\\|?*') | {chr(value) for value in range(32)}
