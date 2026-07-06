"""Filesystem path validation helpers."""

from __future__ import annotations

from pathlib import Path


def get_game_folder_error(game_folder: str | Path) -> str | None:
    path = Path(game_folder)
    if not path.is_dir():
        return f"Game folder does not exist: {path}"
    if path.name.lower() != "baldurs gate 3":
        return "Choose the folder named Baldurs Gate 3, not Data or another parent folder."

    return None

def is_path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False

    return True
