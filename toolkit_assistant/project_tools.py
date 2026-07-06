"""Toolkit project rename and backup workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from .constants import (
    MOD_FOLDER_UUID_SUFFIX_RE,
    PROJECT_BACKUP_SOURCES,
    PROJECT_RENAME_TARGETS,
    TEMPORARY_RENAME_BACKUP_RETENTION_DAYS,
    WINDOWS_INVALID_FILENAME_CHARS,
)
from .models import ProjectBackupCopy
from .paths import get_game_folder_error, is_path_within
from .xml_utils import get_direct_attribute_by_id, iter_elements, save_xml


def backup_toolkit_projects(
    game_folder: str | Path,
    backup_root: str | Path,
    *,
    project_names: list[str] | tuple[str, ...] | set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Back up Toolkit project folders from a BG3 game folder."""

    log = progress or (lambda message: None)
    game_path = Path(game_folder).resolve()
    game_folder_error = get_game_folder_error(game_path)
    if game_folder_error:
        raise FileNotFoundError(game_folder_error)

    data_dir = game_path / "Data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Could not find Data folder under game folder: {data_dir}")

    projects_dir = data_dir / "Projects"
    if not projects_dir.is_dir():
        raise FileNotFoundError(f"Could not find Projects folder: {projects_dir}")

    destination_root = Path(backup_root).resolve()
    if is_path_within(destination_root, data_dir):
        raise ValueError("Choose a backup destination outside the game Data folder.")

    available_project_names = find_toolkit_project_names(projects_dir)
    if project_names is None:
        selected_project_names = available_project_names
    else:
        available_by_key = {name.lower(): name for name in available_project_names}
        selected_project_names = []
        seen_names: set[str] = set()
        for project_name in project_names:
            project_name = project_name.strip()
            if not project_name:
                continue

            matched_name = available_by_key.get(project_name.lower())
            if matched_name is None:
                log(f"Warning: selected project no longer exists and will be skipped: {project_name}\n")
                continue

            matched_key = matched_name.lower()
            if matched_key in seen_names:
                continue

            seen_names.add(matched_key)
            selected_project_names.append(matched_name)

    log(f"Using game folder: {game_path}\n")
    log(f"Using Data folder: {data_dir}\n")
    log(f"Backup destination: {destination_root}\n")
    log(f"Project count: {len(selected_project_names)}\n")

    if not selected_project_names:
        log("No Toolkit projects found to back up.\n")
        return 0

    if project_names is not None:
        heading = "Selected project:" if len(selected_project_names) == 1 else "Selected projects:"
        log(f"{heading}\n")
        for project_name in selected_project_names:
            log(f"- {project_name}\n")

    destination_root.mkdir(parents=True, exist_ok=True)
    today_backup_folder = get_unique_project_backup_run_root(destination_root)
    today_backup_folder.mkdir(parents=True)
    log(f"Backup folder: {today_backup_folder}\n")

    backed_up = 0
    for project_name in selected_project_names:
        log(f"Backing up {project_name}\n")
        bits_to_copy = get_project_backup_copies(data_dir, today_backup_folder, project_name)
        bits_that_exist = [copy_item for copy_item in bits_to_copy if copy_item.source.is_dir()]

        for copy_item in bits_to_copy:
            if not copy_item.source.is_dir():
                log(f"  Skipped missing source: {copy_item.source}\n")
                continue

            log(f"  Copying: {copy_item.source} -> {copy_item.destination}\n")
            shutil.copytree(copy_item.source, copy_item.destination)

        if bits_that_exist:
            backed_up += 1

    log(f"Done. Backed up {backed_up} project(s).\n")
    return backed_up

def get_unique_project_backup_run_root(destination_root: Path) -> Path:
    backup_name = datetime.now().strftime("%Y%m%d")
    candidate = destination_root / backup_name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        try_this_one = destination_root / f"{backup_name}-{counter}"
        if not try_this_one.exists():
            return try_this_one
        counter += 1

def rename_toolkit_mod_project(
    game_folder: str | Path,
    old_folder: str,
    new_folder: str,
    *,
    temporary_backup_root: str | Path | None = None,
    temporary_backup_retention_days: int = TEMPORARY_RENAME_BACKUP_RETENTION_DAYS,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Rename Toolkit mod folders under Data and preserve the mod UUID suffix."""

    log = progress or (lambda message: None)
    game_path = Path(game_folder).resolve()
    old_folder = old_folder.strip()
    new_folder = new_folder.strip()

    game_folder_error = get_game_folder_error(game_path)
    if game_folder_error:
        raise FileNotFoundError(game_folder_error)

    data_dir = game_path / "Data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Could not find Data folder under game folder: {data_dir}")
    if not old_folder:
        raise ValueError("Old mod folder is required.")
    if not new_folder:
        raise ValueError("New mod folder is required.")
    if has_invalid_windows_filename_chars(old_folder):
        raise ValueError("Old mod folder contains characters that Windows cannot use in a folder name.")
    if has_invalid_windows_filename_chars(new_folder):
        raise ValueError("New mod folder contains characters that Windows cannot use in a folder name.")

    old_full_folder = resolve_existing_mod_folder_name(data_dir, old_folder)
    _old_base, uuid_suffix = split_mod_folder_uuid_suffix(old_full_folder)
    new_base, supplied_new_suffix = split_mod_folder_uuid_suffix(new_folder)
    if not new_base:
        raise ValueError("New mod folder must include a name before the UUID suffix.")
    new_full_folder = f"{new_base}{uuid_suffix}"
    if old_full_folder == new_full_folder:
        raise ValueError("Old mod folder and new mod folder are the same after preserving the UUID suffix.")

    log(f"Using Data folder: {data_dir}\n")
    log(f"Resolved old folder: {old_folder} -> {old_full_folder}\n")
    if uuid_suffix:
        if supplied_new_suffix and supplied_new_suffix.lower() != uuid_suffix.lower():
            log(f"Ignoring new-folder UUID suffix and preserving existing suffix: {uuid_suffix}\n")
        log(f"Resolved new folder: {new_folder} -> {new_full_folder}\n")
    else:
        log(f"Resolved new folder: {new_folder}\n")

    # Work out every folder move before touching anything. The Toolkit has
    # enough nonsense already; let's not make things worse, hm?
    folders_to_rename = get_project_rename_plan(data_dir, old_full_folder, new_full_folder)
    if not folders_to_rename:
        raise FileNotFoundError(f"Could not find folders to rename for '{old_full_folder}'.")

    meta_before_rename = data_dir / "Mods" / old_full_folder / "meta.lsx"
    if meta_before_rename.is_file():
        validate_project_meta_file(meta_before_rename)
    else:
        meta_before_rename = None

    if temporary_backup_root is not None:
        backup_root = Path(temporary_backup_root)
        prune_temporary_project_backups(
            backup_root,
            retention_days=temporary_backup_retention_days,
            progress=log,
        )
        create_temporary_project_rename_backup(
            data_dir,
            backup_root,
            old_full_folder,
            new_full_folder,
            progress=log,
        )

    changed = rename_data_mod_folders(folders_to_rename, progress=log)

    meta_after_rename = data_dir / "Mods" / new_full_folder / "meta.lsx" if meta_before_rename is not None else None

    changed += update_project_meta_file(
        meta_after_rename,
        new_full_folder,
        progress=log,
    )

    log(f"Done. Applied {changed} change(s).\n")
    return changed

def has_invalid_windows_filename_chars(value: str) -> bool:
    return any(character in WINDOWS_INVALID_FILENAME_CHARS for character in value)

def split_mod_folder_uuid_suffix(folder_name: str) -> tuple[str, str]:
    match = MOD_FOLDER_UUID_SUFFIX_RE.search(folder_name)
    if match is None:
        return folder_name, ""

    return folder_name[: match.start()], folder_name[match.start() :]

def resolve_existing_mod_folder_name(data_dir: Path, old_folder: str) -> str:
    old_base, old_suffix = split_mod_folder_uuid_suffix(old_folder)
    exact_matches: set[str] = set()
    base_matches: set[str] = set()

    for target_parts in PROJECT_RENAME_TARGETS:
        parent = data_dir.joinpath(*target_parts)
        if not parent.is_dir():
            continue

        for entry in parent.iterdir():
            if not entry.is_dir():
                continue

            if entry.name.lower() == old_folder.lower():
                exact_matches.add(entry.name)
                continue

            entry_base, entry_suffix = split_mod_folder_uuid_suffix(entry.name)
            if not old_suffix and entry_suffix and entry_base.lower() == old_base.lower():
                base_matches.add(entry.name)

    if len(exact_matches) == 1:
        return next(iter(exact_matches))
    if len(exact_matches) > 1:
        raise ValueError(f"Found multiple case variants matching '{old_folder}'. Use the exact folder name.")

    if len(base_matches) == 1:
        return next(iter(base_matches))
    if len(base_matches) > 1:
        matches = ", ".join(sorted(base_matches))
        raise ValueError(f"Found multiple folders matching '{old_folder}': {matches}")

    raise FileNotFoundError(f"Could not find a mod folder matching '{old_folder}' under Data.")

def get_project_rename_plan(data_dir: Path, old_name: str, new_name: str) -> list[tuple[Path, Path]]:
    plan: list[tuple[Path, Path]] = []

    for target_parts in PROJECT_RENAME_TARGETS:
        parent = data_dir.joinpath(*target_parts)
        if not parent.is_dir():
            continue

        old_path = parent / old_name
        new_path = parent / new_name
        if not old_path.is_dir():
            continue
        if new_path.exists():
            raise FileExistsError(f"Cannot rename '{old_path}' because '{new_path}' already exists.")

        plan.append((old_path, new_path))

    return plan

def rename_data_mod_folders(
    rename_plan: list[tuple[Path, Path]],
    *,
    progress: Callable[[str], None],
) -> int:
    changed = 0
    for old_path, new_path in rename_plan:
        old_path.rename(new_path)
        progress(f"Renamed folder: {old_path} -> {new_path}\n")
        changed += 1

    return changed

def validate_project_meta_file(meta_path: Path) -> None:
    tree = ET.parse(meta_path)
    module_info = get_module_info_node(tree.getroot())
    if module_info is None:
        raise ValueError(f"Could not find ModuleInfo in '{meta_path}'.")
    if get_direct_attribute_by_id(module_info, "Folder") is None:
        raise ValueError(f"Could not find ModuleInfo Folder attribute in '{meta_path}'.")

def create_temporary_project_rename_backup(
    data_dir: Path,
    backup_root: Path,
    old_folder: str,
    new_folder: str,
    *,
    progress: Callable[[str], None],
) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    this_backup = get_unique_backup_run_root(backup_root, old_folder, new_folder)
    backup_bits = get_project_backup_copies(data_dir, this_backup, old_folder)
    bits_that_exist = [copy_item for copy_item in backup_bits if copy_item.source.is_dir()]
    if not bits_that_exist:
        raise FileNotFoundError(f"Could not find folders to back up before renaming '{old_folder}'.")

    progress(f"Temporary backup: {this_backup}\n")
    for copy_item in bits_that_exist:
        progress(f"  Copying: {copy_item.source} -> {copy_item.destination}\n")
        shutil.copytree(copy_item.source, copy_item.destination)

    return this_backup

def get_unique_backup_run_root(backup_root: Path, old_folder: str, new_folder: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    old_label = sanitise_backup_folder_label(split_mod_folder_uuid_suffix(old_folder)[0] or old_folder)
    new_label = sanitise_backup_folder_label(split_mod_folder_uuid_suffix(new_folder)[0] or new_folder)
    backup_name = f"{timestamp}_{old_label}_to_{new_label}"
    candidate = backup_root / backup_name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        try_this_one = backup_root / f"{backup_name}-{counter}"
        if not try_this_one.exists():
            return try_this_one
        counter += 1

def sanitise_backup_folder_label(value: str) -> str:
    cleaned = "".join("_" if character in WINDOWS_INVALID_FILENAME_CHARS else character for character in value.strip())
    cleaned = cleaned.strip(" ._")
    return cleaned[:80] or "Unnamed"

def prune_temporary_project_backups(
    backup_root: Path,
    *,
    retention_days: int,
    progress: Callable[[str], None],
) -> int:
    if retention_days < 1 or not backup_root.is_dir():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for entry in backup_root.iterdir():
        if not entry.is_dir():
            continue

        created_at = get_temporary_backup_created_at(entry)
        if created_at >= cutoff:
            continue

        try:
            shutil.rmtree(entry)
        except OSError as exc:
            progress(f"Warning: could not remove expired temporary backup '{entry}': {exc}\n")
            continue

        progress(f"Removed expired temporary backup: {entry}\n")
        removed += 1

    return removed

def get_temporary_backup_created_at(path: Path) -> datetime:
    timestamp_text = path.name[:15]
    try:
        return datetime.strptime(timestamp_text, "%Y%m%d-%H%M%S")
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_ctime)

def rename_data_mod_folder(
    parent: Path,
    old_name: str,
    new_name: str,
    *,
    progress: Callable[[str], None],
) -> int:
    if not parent.is_dir():
        return 0

    old_path = parent / old_name
    new_path = parent / new_name
    if not old_path.is_dir():
        return 0
    if new_path.exists():
        raise FileExistsError(f"Cannot rename '{old_path}' because '{new_path}' already exists.")

    old_path.rename(new_path)
    progress(f"Renamed folder: {old_path} -> {new_path}\n")

    return 1

def update_project_meta_file(
    meta_path: Path | None,
    new_folder: str,
    *,
    progress: Callable[[str], None],
) -> int:
    if meta_path is None:
        progress("Warning: No meta.lsx found for this mod folder. Folder rename completed without metadata changes.\n")
        return 0
    if not meta_path.is_file():
        raise FileNotFoundError(f"meta.lsx does not exist after rename: {meta_path}")

    tree = ET.parse(meta_path)
    module_info = get_module_info_node(tree.getroot())
    if module_info is None:
        raise ValueError(f"Could not find ModuleInfo in '{meta_path}'.")

    changed = 0
    folder_attribute = get_direct_attribute_by_id(module_info, "Folder")
    if folder_attribute is None:
        raise ValueError(f"Could not find ModuleInfo Folder attribute in '{meta_path}'.")

    old_folder_value = folder_attribute.attrib.get("value", "")
    if old_folder_value != new_folder:
        folder_attribute.set("value", new_folder)
        changed += 1
    progress(f"meta.lsx Folder: {old_folder_value} -> {new_folder}\n")

    save_xml(tree, meta_path)
    progress(f"Updated meta.lsx: {meta_path}\n")
    return changed

def get_module_info_node(root: ET.Element) -> ET.Element | None:
    for node in iter_elements(root, "node"):
        if node.attrib.get("id") == "ModuleInfo":
            return node

    return None

def find_toolkit_project_names(projects_dir: Path) -> list[str]:
    names: list[str] = []
    for entry in sorted(projects_dir.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        if entry.name.lower() == "gustavdev":
            continue
        names.append(entry.name)

    return names

def get_project_backup_copies(data_dir: Path, backup_root: Path, project_name: str) -> list[ProjectBackupCopy]:
    copies: list[ProjectBackupCopy] = []
    for source_parts, destination_parts in PROJECT_BACKUP_SOURCES:
        source = data_dir.joinpath(*source_parts, project_name)
        destination = backup_root.joinpath(project_name, *destination_parts, project_name)
        copies.append(ProjectBackupCopy(source=source, destination=destination))

    return copies
