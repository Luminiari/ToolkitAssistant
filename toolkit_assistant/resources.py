"""BG3 resource and VisualBank reference helpers."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .models import MeshReference
from .xml_utils import get_direct_attribute_by_id, get_direct_attribute_elements, iter_elements, local_name


def get_single_gr2_mesh_reference(
    root: ET.Element,
    game_folder: str | Path,
    *,
    identifier_hint: str | None = None,
) -> MeshReference:
    references = find_gr2_mesh_references(root, game_folder)
    if not references:
        raise ValueError("No .gr2 SourceFile references were found in the converted LSX.")

    existing = [reference for reference in references if reference.resolved_path.is_file()]
    if not existing:
        raise FileNotFoundError(
            "Found .gr2 reference(s), but none resolved to files on disk:\n"
            + format_mesh_reference_summary(references)
        )

    source_file_references = [
        reference
        for reference in existing
        if reference.attribute_id.lower() == "sourcefile"
    ]
    candidates = dedupe_mesh_references(source_file_references or existing)

    if identifier_hint and len(candidates) > 1:
        hinted = [
            reference
            for reference in candidates
            if node_has_direct_attribute_value(reference.target_node, identifier_hint)
        ]
        if len(hinted) == 1:
            return hinted[0]

    if len(candidates) == 1:
        return candidates[0]

    raise ValueError(
        "Found multiple usable .gr2 references. Choose the mesh manually in Bounds Calculator, "
        "or use a converted LSX with one clear model reference:\n"
        + format_mesh_reference_summary(candidates)
    )

def find_gr2_mesh_references(root: ET.Element, game_folder: str | Path) -> list[MeshReference]:
    references: list[MeshReference] = []
    for node in iter_elements(root, "node"):
        for attribute in get_direct_attribute_elements(node):
            value = attribute.attrib.get("value", "")
            source_file = extract_gr2_path(value)
            if source_file is None:
                continue

            references.append(
                MeshReference(
                    source_file=source_file,
                    resolved_path=resolve_gr2_resource_path(source_file, game_folder),
                    target_node=node,
                    attribute_id=attribute.attrib.get("id", ""),
                )
            )

    return references

def extract_gr2_path(value: str) -> str | None:
    stripped = value.strip().strip('"').strip("'")
    if stripped.lower().endswith(".gr2"):
        return stripped

    return None

def resolve_gr2_resource_path(source_file: str, game_folder: str | Path) -> Path:
    game_root = Path(game_folder).resolve()
    data_root = game_root / "Data"
    normalized = source_file.strip().strip('"').strip("'").replace("\\", "/")

    if normalized.upper().startswith("($SOURCE)"):
        relative = normalized[len("($SOURCE)") :].lstrip("/\\")
        return data_root.joinpath("ASSETS", *split_resource_path(relative))

    source_path = Path(source_file)
    if source_path.is_absolute():
        return source_path.resolve()

    parts = split_resource_path(normalized)
    if parts and parts[0].lower() == "data":
        parts = parts[1:]

    return data_root.joinpath(*parts)

def split_resource_path(path_text: str) -> list[str]:
    normalized = path_text.replace("\\", "/").strip("/")
    return [part for part in normalized.split("/") if part and part != "."]

def dedupe_mesh_references(references: list[MeshReference]) -> list[MeshReference]:
    deduped: list[MeshReference] = []
    seen: set[tuple[str, int]] = set()
    for reference in references:
        key = (str(reference.resolved_path).lower(), id(reference.target_node))
        if key in seen:
            continue

        seen.add(key)
        deduped.append(reference)

    return deduped

def node_has_direct_attribute_value(node: ET.Element, value: str) -> bool:
    value_key = value.lower()
    for attribute in get_direct_attribute_elements(node):
        if attribute.attrib.get("value", "").lower() == value_key:
            return True

    return False

def describe_node_for_log(node: ET.Element) -> str:
    parts = [f'node id="{node.attrib.get("id", "")}"']
    for attribute_id in ("ID", "MapKey", "Name"):
        attribute = get_direct_attribute_by_id(node, attribute_id)
        if attribute is not None:
            parts.append(f'{attribute_id}="{attribute.attrib.get("value", "")}"')

    return ", ".join(parts)

def format_mesh_reference_summary(references: list[MeshReference]) -> str:
    lines = [
        f"- {reference.source_file} -> {reference.resolved_path} ({describe_node_for_log(reference.target_node)})"
        for reference in references[:10]
    ]
    if len(references) > 10:
        lines.append(f"- ...and {len(references) - 10} more")

    return "\n".join(lines)

def get_visualbank_resource_nodes(root: ET.Element) -> list[ET.Element]:
    nodes: list[ET.Element] = []
    seen: set[int] = set()
    for container in root.iter():
        if local_name(container.tag) not in {"region", "node"}:
            continue
        if container.attrib.get("id", "").lower() != "visualbank":
            continue

        for node in iter_elements(container, "node"):
            if node.attrib.get("id", "").lower() != "resource":
                continue
            if get_direct_attribute_by_id(node, "ID") is None:
                continue

            marker = id(node)
            if marker in seen:
                continue

            seen.add(marker)
            nodes.append(node)

    return nodes

def get_visualbank_gr2_mesh_references(root: ET.Element, game_folder: str | Path) -> list[MeshReference]:
    references: list[MeshReference] = []
    for node in get_visualbank_resource_nodes(root):
        source_file_attribute = get_direct_attribute_by_id(node, "SourceFile")
        if source_file_attribute is None:
            continue

        source_file = extract_gr2_path(source_file_attribute.attrib.get("value", ""))
        if source_file is None:
            continue

        references.append(
            MeshReference(
                source_file=source_file,
                resolved_path=resolve_gr2_resource_path(source_file, game_folder),
                target_node=node,
                attribute_id=source_file_attribute.attrib.get("id", ""),
            )
        )

    return references
