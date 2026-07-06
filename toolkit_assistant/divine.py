"""Integration with Norbyte's Divine.exe."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from .constants import APP_DIR


def resolve_divine(explicit_path: str | Path | None = None) -> Path:
    candidates: list[str | Path] = []
    if explicit_path:
        candidates.append(explicit_path)

    for env_name in ("LSLIB_DIVINE", "BG3_DIVINE", "DIVINE_EXE"):
        env_value = os.environ.get(env_name)
        if env_value:
            candidates.append(env_value)

    for local_name in (
        "Divine.exe",
        "Tools/Divine.exe",
        "ExportTool/Tools/Divine.exe",
        "lslib/Tools/Divine.exe",
    ):
        candidates.append(APP_DIR / local_name)

    path_command = shutil.which("Divine.exe")
    if path_command:
        candidates.append(path_command)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()

    raise FileNotFoundError("Could not find Divine.exe. Choose it, or set LSLIB_DIVINE.")

def find_default_divine() -> str:
    try:
        return str(resolve_divine())
    except FileNotFoundError:
        return ""

def convert_resource(divine: Path, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    args = [
        str(divine),
        "-g",
        "bg3",
        "-a",
        "convert-resource",
        "-s",
        str(source),
        "-d",
        str(destination),
    ]

    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        args,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"Divine conversion failed for {source} -> {destination}.\n{output}")
    if not destination.is_file():
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"Divine did not create {destination}.\n{output}")

def convert_model(divine: Path, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    args = [
        str(divine),
        "-g",
        "bg3",
        "-a",
        "convert-model",
        "-s",
        str(source),
        "-d",
        str(destination),
    ]

    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        args,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"Divine model conversion failed for {source} -> {destination}.\n{output}")
    if not destination.is_file():
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"Divine did not create {destination}.\n{output}")
