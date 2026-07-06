"""Temporary file cleanup helpers."""

from __future__ import annotations

from pathlib import Path
import shutil


def delete_temp_folder_contents(temp_root: str | Path) -> int:
    """Delete everything inside the app temp folder and return the top-level item count."""

    temp_path = Path(temp_root)
    if not temp_path.exists():
        return 0
    if not temp_path.is_dir():
        raise NotADirectoryError(f"Temporary path is not a folder: {temp_path}")

    deleted = 0
    for thing in temp_path.iterdir():
        if thing.is_dir():
            shutil.rmtree(thing)
        else:
            thing.unlink()
        deleted += 1

    return deleted
