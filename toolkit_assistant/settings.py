"""Persistent user settings."""

from __future__ import annotations

import json

from .constants import SETTINGS_PATH


def load_settings() -> dict[str, str]:
    if not SETTINGS_PATH.is_file():
        return {}

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(key): str(value) for key, value in data.items() if value is not None}

def save_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
