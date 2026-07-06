"""Import settings XML repair workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from .models import ImportSourceRepair
from .xml_utils import local_name, save_xml


def repair_import_settings_sources(
    xml_root: str | Path,
    *,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Repair Toolkit import settings XML source paths rewritten to absolute Data/ASSETS paths."""

    log = progress or (lambda message: None)
    root_path = Path(xml_root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Import settings root does not exist: {root_path}")
    if root_path.is_file() and root_path.suffix.lower() != ".xml":
        raise ValueError(f"Expected an .xml file or folder: {root_path}")

    files = [root_path] if root_path.is_file() else sorted(root_path.rglob("*.xml"), key=lambda item: str(item).lower())
    if not files:
        log(f"No XML files found under: {root_path}\n")
        return 0

    log(f"Scanning import settings XML under: {root_path}\n")
    repaired = 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for file in files:
        try:
            tree = ET.parse(file)
        except ET.ParseError as exc:
            log(f"Warning: Skipped invalid XML '{file}': {exc}\n")
            continue
        except OSError as exc:
            log(f"Warning: Could not read '{file}': {exc}\n")
            continue

        changes = get_import_source_repairs(tree.getroot())
        if not changes:
            continue

        log(f"Repairing: {file}\n")
        for change in changes:
            log(f"  {change.old_source}\n")
            log(f"  -> {change.new_source}\n")

        if backup_original:
            backup_path = file.with_name(f"{file.name}.bak-{stamp}")
            shutil.copy2(file, backup_path)
            log(f"  Backed up original: {backup_path}\n")

        save_xml(tree, file)
        repaired += 1

    log(f"Done. Repaired {repaired} file(s).\n")
    return repaired

def get_import_source_repairs(root: ET.Element) -> list[ImportSourceRepair]:
    repairs: list[ImportSourceRepair] = []
    for settings_node in iter_settings_nodes(root):
        source = settings_node.attrib.get("source")
        if not source:
            continue

        repaired = repair_import_source_path(source)
        if repaired is None or repaired == source:
            continue

        settings_node.set("source", repaired)
        repairs.append(ImportSourceRepair(old_source=source, new_source=repaired))

    return repairs

def iter_settings_nodes(root: ET.Element):
    for element in root.iter():
        if local_name(element.tag) == "Settings":
            yield element

def repair_import_source_path(source: str) -> str | None:
    stripped = source.strip()
    if not stripped or stripped.upper().startswith("($SOURCE)"):
        return None

    normalized = stripped.replace("\\", "/")
    match = re.search(r"(?i)(?:^|/)Data/ASSETS/(.+)$", normalized)
    if not match:
        return None

    relative = match.group(1).strip("/\\")
    if not relative:
        return None

    return "($SOURCE)\\" + relative.replace("/", "\\")
