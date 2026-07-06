"""LSF bounds patching workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .divine import convert_resource, resolve_divine
from .lsx import apply_bounds_payload, get_bounds_payload, get_single_target_node, get_target_nodes_by_uuid
from .mesh_bounds import calculate_mesh_bounds, format_mesh_bounds_xml
from .models import LsfBatchTarget
from .paths import get_game_folder_error
from .resources import (
    describe_node_for_log,
    get_single_gr2_mesh_reference,
    get_visualbank_gr2_mesh_references,
    get_visualbank_resource_nodes,
)
from .xml_utils import parse_xml_fragment, safe_file_stem, save_xml


def patch_lsf_file(
    lsf_file: str | Path,
    bounds_text: str,
    divine_path: str | Path | None = None,
    *,
    keep_lsx: bool = True,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Patch a single .lsf file with pasted bounds XML.

    Divine is still required because it performs BG3 LSF <-> LSX resource
    conversion.
    """

    log = progress or (lambda message: None)
    source_lsf = Path(lsf_file).resolve()
    if not source_lsf.is_file():
        raise FileNotFoundError(f"LSF file does not exist: {source_lsf}")
    if source_lsf.suffix.lower() != ".lsf":
        raise ValueError(f"Expected a .lsf file: {source_lsf}")

    bounds_text = bounds_text.strip()
    if not bounds_text:
        raise ValueError("Bounds XML is empty.")

    divine = resolve_divine(divine_path)
    payload = get_bounds_payload(parse_xml_fragment(bounds_text, "bounds XML"))
    log(f"Bounds payload type: {payload.kind}\n")
    log(f"Using Divine: {divine}\n")

    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-") as work_dir_text:
        work_dir = Path(work_dir_text)
        safe_name = safe_file_stem(source_lsf)
        working_lsx = work_dir / f"{safe_name}.lsx"
        working_lsf = work_dir / f"{safe_name}.lsf"

        log(f"Converting to LSX: {source_lsf}\n")
        convert_resource(divine, source_lsf, working_lsx)

        tree = ET.parse(working_lsx)
        root = tree.getroot()
        target = get_single_target_node(root)
        apply_bounds_payload(target, payload)

        if backup_original:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = source_lsf.with_name(f"{source_lsf.name}.bak-{stamp}")
            shutil.copy2(source_lsf, backup_path)
            log(f"Backed up original: {backup_path}\n")

        if keep_lsx:
            kept_lsx = source_lsf.with_suffix(".lsx")
            save_xml(tree, working_lsx)
            shutil.copy2(working_lsx, kept_lsx)
            log(f"Wrote edited LSX: {kept_lsx}\n")
        else:
            save_xml(tree, working_lsx)

        log(f"Converting back to LSF: {source_lsf}\n")
        convert_resource(divine, working_lsx, working_lsf)

        shutil.copy2(working_lsf, source_lsf)
        log("Done. Updated 1 file.\n")
        return 1

def patch_lsf_from_related_mesh(
    lsf_file: str | Path,
    game_folder: str | Path,
    divine_path: str | Path | None = None,
    *,
    keep_lsx: bool = True,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Calculate bounds from the GR2 referenced by an LSF and patch that LSF."""

    log = progress or (lambda message: None)
    source_lsf = Path(lsf_file).resolve()
    if not source_lsf.is_file():
        raise FileNotFoundError(f"LSF file does not exist: {source_lsf}")
    if source_lsf.suffix.lower() != ".lsf":
        raise ValueError(f"Expected a .lsf file: {source_lsf}")

    game_root = Path(game_folder).resolve()
    game_folder_error = get_game_folder_error(game_root)
    if game_folder_error:
        raise ValueError(game_folder_error)
    if not (game_root / "Data").is_dir():
        raise FileNotFoundError(f"Could not find a Data folder inside: {game_root}")

    divine = resolve_divine(divine_path)
    log(f"Using Divine: {divine}\n")

    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-auto-bounds-") as work_dir_text:
        work_dir = Path(work_dir_text)
        safe_name = safe_file_stem(source_lsf)
        working_lsx = work_dir / f"{safe_name}.lsx"
        working_lsf = work_dir / f"{safe_name}.lsf"

        log(f"Converting to LSX: {source_lsf}\n")
        convert_resource(divine, source_lsf, working_lsx)

        tree = ET.parse(working_lsx)
        root = tree.getroot()
        reference = get_single_gr2_mesh_reference(root, game_root, identifier_hint=source_lsf.stem)
        log(f"Found GR2 reference: {reference.source_file}\n")
        log(f"Resolved GR2: {reference.resolved_path}\n")
        log(f"Patching node: {describe_node_for_log(reference.target_node)}\n")

        bounds = calculate_mesh_bounds(
            reference.resolved_path,
            divine,
            progress=log,
        )
        log(f"Vertex count: {bounds.vertex_count}\n")

        bounds_xml = format_mesh_bounds_xml(bounds)
        payload = get_bounds_payload(parse_xml_fragment(bounds_xml, "generated bounds XML"))
        apply_bounds_payload(reference.target_node, payload)

        if backup_original:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = source_lsf.with_name(f"{source_lsf.name}.bak-{stamp}")
            shutil.copy2(source_lsf, backup_path)
            log(f"Backed up original: {backup_path}\n")

        if keep_lsx:
            kept_lsx = source_lsf.with_suffix(".lsx")
            save_xml(tree, working_lsx)
            shutil.copy2(working_lsx, kept_lsx)
            log(f"Wrote edited LSX: {kept_lsx}\n")
        else:
            save_xml(tree, working_lsx)

        log(f"Converting back to LSF: {source_lsf}\n")
        convert_resource(divine, working_lsx, working_lsf)

        shutil.copy2(working_lsf, source_lsf)
        log("Done. Updated 1 file.\n")
        return 1

def patch_visualbank_lsf_files_from_related_mesh(
    content_folder: str | Path,
    game_folder: str | Path,
    divine_path: str | Path | None = None,
    *,
    keep_lsx: bool = True,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Calculate bounds from GR2 SourceFile values and patch VisualBank LSF files under a folder."""

    log = progress or (lambda message: None)
    root_path = Path(content_folder).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Content folder does not exist: {root_path}")

    game_root = Path(game_folder).resolve()
    game_folder_error = get_game_folder_error(game_root)
    if game_folder_error:
        raise ValueError(game_folder_error)
    if not (game_root / "Data").is_dir():
        raise FileNotFoundError(f"Could not find a Data folder inside: {game_root}")

    lsf_files = sorted(root_path.rglob("*.lsf"), key=lambda item: str(item).lower())
    if not lsf_files:
        raise ValueError(f"No .lsf files were found under: {root_path}")

    divine = resolve_divine(divine_path)
    log(f"Using Divine: {divine}\n")
    log(f"Scanning Content folder: {root_path}\n")

    changed = 0
    skipped = 0
    backup_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bounds_cache: dict[Path, str] = {}

    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-one-click-batch-") as work_dir_text:
        work_dir = Path(work_dir_text)
        for source_lsf in lsf_files:
            safe_name = safe_file_stem(source_lsf)
            working_lsx = work_dir / f"{safe_name}.lsx"
            working_lsf = work_dir / f"{safe_name}.lsf"

            log(f"Converting to LSX: {source_lsf}\n")
            try:
                convert_resource(divine, source_lsf, working_lsx)
                tree = ET.parse(working_lsx)
            except (RuntimeError, ET.ParseError, OSError) as exc:
                skipped += 1
                log(f"Warning: Skipped '{source_lsf}': {exc}\n")
                continue

            root = tree.getroot()
            resource_nodes = get_visualbank_resource_nodes(root)
            if not resource_nodes:
                skipped += 1
                log(f"Skipped non-VisualBank LSF: {source_lsf}\n")
                continue

            references = get_visualbank_gr2_mesh_references(root, game_root)
            if not references:
                skipped += 1
                log(f"Warning: Skipped '{source_lsf}': no VisualBank SourceFile GR2 references were found.\n")
                continue

            patched_nodes = 0
            missing_references = 0
            for reference in references:
                if not reference.resolved_path.is_file():
                    missing_references += 1
                    log(f"Warning: Missing GR2 for {reference.source_file}: {reference.resolved_path}\n")
                    continue

                bounds_xml = bounds_cache.get(reference.resolved_path)
                if bounds_xml is None:
                    log(f"Calculating bounds from GR2: {reference.resolved_path}\n")
                    bounds = calculate_mesh_bounds(reference.resolved_path, divine, progress=log)
                    log(f"Vertex count: {bounds.vertex_count}\n")
                    bounds_xml = format_mesh_bounds_xml(bounds)
                    bounds_cache[reference.resolved_path] = bounds_xml
                else:
                    log(f"Reusing bounds for GR2: {reference.resolved_path}\n")

                payload = get_bounds_payload(parse_xml_fragment(bounds_xml, "generated bounds XML"))
                apply_bounds_payload(reference.target_node, payload)
                patched_nodes += 1

            if not patched_nodes:
                skipped += 1
                if missing_references:
                    log(f"Warning: Skipped '{source_lsf}': all VisualBank GR2 references were missing.\n")
                else:
                    log(f"Warning: Skipped '{source_lsf}': no patchable VisualBank resources were found.\n")
                continue

            if backup_original:
                backup_path = source_lsf.with_name(f"{source_lsf.name}.bak-{backup_stamp}")
                shutil.copy2(source_lsf, backup_path)
                log(f"Backed up original: {backup_path}\n")

            save_xml(tree, working_lsx)

            if keep_lsx:
                kept_lsx = source_lsf.with_suffix(".lsx")
                shutil.copy2(working_lsx, kept_lsx)
                log(f"Wrote edited LSX: {kept_lsx}\n")

            log(f"Converting back to LSF: {source_lsf}\n")
            convert_resource(divine, working_lsx, working_lsf)

            shutil.copy2(working_lsf, source_lsf)
            log(f"Patched {patched_nodes} VisualBank resource node(s): {source_lsf}\n")
            changed += 1

    log(f"Done. Updated {changed} file(s). Skipped {skipped} file(s).\n")
    return changed

def patch_lsf_files_by_uuid(
    lsf_root: str | Path,
    uuid_values: list[str] | tuple[str, ...] | set[str],
    bounds_text: str,
    divine_path: str | Path | None = None,
    *,
    keep_lsx: bool = True,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Patch every matching .lsf under a root using UUID filename matching."""

    log = progress or (lambda message: None)
    root_path = Path(lsf_root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Content folder does not exist: {root_path}")

    uuids = normalize_uuid_values(uuid_values)
    if not uuids:
        raise ValueError("Paste or load at least one UUID.")

    bounds_text = bounds_text.strip()
    if not bounds_text:
        raise ValueError("Bounds XML is empty.")

    divine = resolve_divine(divine_path)
    payload = get_bounds_payload(parse_xml_fragment(bounds_text, "bounds XML"))
    log(f"Bounds payload type: {payload.kind}\n")
    log(f"Finding .lsf files matching requested UUIDs under: {root_path}\n")

    targets = find_matching_lsf_by_uuid(root_path, uuids)
    if not targets:
        raise ValueError(f"No .lsf filenames under '{root_path}' matched the requested UUIDs.")

    log(f"Using Divine: {divine}\n")
    log(f"Target file count: {len(targets)}\n")

    uuid_set = {uuid.lower() for uuid in uuids}
    changed = 0
    backup_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-batch-") as work_dir_text:
        work_dir = Path(work_dir_text)
        for target in targets:
            source_lsf = target.file
            safe_name = safe_file_stem(source_lsf)
            working_lsx = work_dir / f"{safe_name}.lsx"
            working_lsf = work_dir / f"{safe_name}.lsf"

            log(f"Converting to LSX: {source_lsf}\n")
            convert_resource(divine, source_lsf, working_lsx)

            tree = ET.parse(working_lsx)
            root = tree.getroot()
            target_nodes = get_target_nodes_by_uuid(root, uuid_set, target.matched_uuid)
            if not target_nodes:
                log(f"Warning: Skipped '{source_lsf}': could not identify a target node in the converted LSX.\n")
                continue

            for node in target_nodes:
                apply_bounds_payload(node, payload)

            if backup_original:
                backup_path = source_lsf.with_name(f"{source_lsf.name}.bak-{backup_stamp}")
                shutil.copy2(source_lsf, backup_path)
                log(f"Backed up original: {backup_path}\n")

            save_xml(tree, working_lsx)

            if keep_lsx:
                kept_lsx = source_lsf.with_suffix(".lsx")
                shutil.copy2(working_lsx, kept_lsx)
                log(f"Wrote edited LSX: {kept_lsx}\n")

            log(f"Converting back to LSF: {source_lsf}\n")
            convert_resource(divine, working_lsx, working_lsf)

            shutil.copy2(working_lsf, source_lsf)
            changed += 1

    log(f"Done. Updated {changed} file(s).\n")
    return changed

def patch_all_visualbank_lsf_files(
    lsf_root: str | Path,
    bounds_text: str,
    divine_path: str | Path | None = None,
    *,
    keep_lsx: bool = True,
    backup_original: bool = True,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Patch every valid VisualBank .lsf under a root with pasted bounds XML."""

    log = progress or (lambda message: None)
    root_path = Path(lsf_root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Content folder does not exist: {root_path}")

    bounds_text = bounds_text.strip()
    if not bounds_text:
        raise ValueError("Bounds XML is empty.")

    lsf_files = sorted(root_path.rglob("*.lsf"), key=lambda item: str(item).lower())
    if not lsf_files:
        raise ValueError(f"No .lsf files were found under: {root_path}")

    divine = resolve_divine(divine_path)
    payload = get_bounds_payload(parse_xml_fragment(bounds_text, "bounds XML"))
    log(f"Bounds payload type: {payload.kind}\n")
    log(f"Using Divine: {divine}\n")
    log(f"Scanning all .lsf files under: {root_path}\n")

    changed = 0
    skipped = 0
    backup_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-visualbank-batch-") as work_dir_text:
        work_dir = Path(work_dir_text)
        for source_lsf in lsf_files:
            safe_name = safe_file_stem(source_lsf)
            working_lsx = work_dir / f"{safe_name}.lsx"
            working_lsf = work_dir / f"{safe_name}.lsf"

            log(f"Converting to LSX: {source_lsf}\n")
            try:
                convert_resource(divine, source_lsf, working_lsx)
                tree = ET.parse(working_lsx)
            except (RuntimeError, ET.ParseError, OSError) as exc:
                skipped += 1
                log(f"Warning: Skipped '{source_lsf}': {exc}\n")
                continue

            target_nodes = get_visualbank_resource_nodes(tree.getroot())
            if not target_nodes:
                skipped += 1
                log(f"Skipped non-VisualBank LSF: {source_lsf}\n")
                continue

            log(f"VisualBank entry count: {len(target_nodes)}\n")

            for node in target_nodes:
                apply_bounds_payload(node, payload)

            if backup_original:
                backup_path = source_lsf.with_name(f"{source_lsf.name}.bak-{backup_stamp}")
                shutil.copy2(source_lsf, backup_path)
                log(f"Backed up original: {backup_path}\n")

            save_xml(tree, working_lsx)

            if keep_lsx:
                kept_lsx = source_lsf.with_suffix(".lsx")
                shutil.copy2(working_lsx, kept_lsx)
                log(f"Wrote edited LSX: {kept_lsx}\n")

            log(f"Converting back to LSF: {source_lsf}\n")
            convert_resource(divine, working_lsx, working_lsf)

            shutil.copy2(working_lsf, source_lsf)
            changed += 1

    log(f"Done. Updated {changed} file(s). Skipped {skipped} file(s).\n")
    return changed

def parse_uuid_values(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in re.split(r"[\r\n,;]+", text):
        value = raw_value.strip()
        if not value or value.startswith("#"):
            continue

        key = value.lower()
        if key not in seen:
            seen.add(key)
            values.append(value)

    return values

def normalize_uuid_values(uuid_values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    return parse_uuid_values("\n".join(str(value) for value in uuid_values))

def find_matching_lsf_by_uuid(root_path: Path, uuid_values: list[str]) -> list[LsfBatchTarget]:
    targets: list[LsfBatchTarget] = []
    lowered = [(uuid, uuid.lower()) for uuid in uuid_values]
    for file in sorted(root_path.rglob("*.lsf"), key=lambda item: str(item).lower()):
        file_name = file.name.lower()
        file_stem = file.stem.lower()
        for uuid, uuid_key in lowered:
            if file_stem == uuid_key or uuid_key in file_name:
                targets.append(LsfBatchTarget(file=file.resolve(), matched_uuid=uuid))
                break

    return targets
