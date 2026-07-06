"""LSX payload and node helpers."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from .constants import BOUNDS_ATTRIBUTE_IDS
from .models import BoundsPayload
from .xml_utils import (
    find_nodes_by_id,
    get_direct_attribute_by_id,
    get_direct_attribute_elements,
    get_direct_child_node_by_id,
    get_direct_children_element,
    iter_elements,
    local_name,
    replace_child,
)


def get_bounds_payload(source_root: ET.Element) -> BoundsPayload:
    bounds_nodes = [
        element
        for element in source_root.iter()
        if local_name(element.tag) == "node" and element.attrib.get("id", "").lower() == "bounds"
    ]
    if bounds_nodes:
        return BoundsPayload(kind="BoundsNode", bounds_node=bounds_nodes[0])

    bound_nodes = [
        element
        for element in source_root.iter()
        if local_name(element.tag) == "node" and element.attrib.get("id", "").lower() == "bound"
    ]
    if bound_nodes:
        return BoundsPayload(kind="BoundNodes", bound_nodes=tuple(bound_nodes))

    attributes = [
        element
        for element in source_root.iter()
        if local_name(element.tag) == "attribute" and element.attrib.get("id") in BOUNDS_ATTRIBUTE_IDS
    ]
    if attributes:
        return BoundsPayload(kind="Attributes", attributes=tuple(attributes))

    raise ValueError(
        'No bounds payload found. Expected <node id="Bounds">, <node id="Bound">, '
        "or BoundsMin/BoundsMax/Center/Radius attributes."
    )

def get_single_target_node(root: ET.Element) -> ET.Element:
    candidates = get_game_object_candidates(root)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Could not find a target node with GameObjects, VisualResource, or existing bounds data.")

    raise ValueError(
        f"Found {len(candidates)} possible target nodes. This simple single-file tool expects exactly one."
    )

def get_game_object_candidates(root: ET.Element) -> list[ET.Element]:
    game_objects = find_nodes_by_id(root, "GameObjects")
    if game_objects:
        return game_objects

    visual_resources = find_nodes_by_id(root, "VisualResource")
    if visual_resources:
        return visual_resources

    candidates: list[ET.Element] = []
    for node in iter_elements(root, "node"):
        if get_direct_child_node_by_id(node, "Bounds") is not None:
            candidates.append(node)
        elif get_direct_attribute_by_id(node, "BoundsMin") is not None:
            candidates.append(node)
    return candidates

def get_target_nodes_by_uuid(root: ET.Element, uuid_set: set[str], matched_uuid: str | None) -> list[ET.Element]:
    nodes: list[ET.Element] = []
    if uuid_set:
        for node in iter_elements(root, "node"):
            if node_matches_uuid(node, uuid_set):
                nodes.append(node)

    if nodes:
        return nodes

    candidates = get_game_object_candidates(root)
    if matched_uuid and len(candidates) == 1:
        return [candidates[0]]

    return []

def node_matches_uuid(node: ET.Element, uuid_set: set[str]) -> bool:
    for attribute in get_direct_attribute_elements(node):
        value = attribute.attrib.get("value", "")
        if value.lower() in uuid_set:
            return True

    return False

def apply_bounds_payload(target: ET.Element, payload: BoundsPayload) -> None:
    if payload.kind == "BoundsNode":
        if payload.bounds_node is None:
            raise ValueError("Bounds payload is missing its Bounds node.")
        children = ensure_children_element(target)
        existing = get_direct_child_node_by_id(target, "Bounds")
        imported = copy.deepcopy(payload.bounds_node)
        if existing is None:
            children.append(imported)
        else:
            replace_child(children, existing, imported)
        return

    if payload.kind == "BoundNodes":
        children = ensure_children_element(target)
        existing = get_direct_child_node_by_id(target, "Bounds")
        if existing is not None:
            children.remove(existing)

        bounds = ET.Element("node", {"id": "Bounds"})
        bounds_children = ET.SubElement(bounds, "children")
        for bound in payload.bound_nodes:
            bounds_children.append(copy.deepcopy(bound))
        children.append(bounds)
        return

    if payload.kind == "Attributes":
        for attribute in payload.attributes:
            copy_attribute_element(attribute, target)
        return

    raise ValueError(f"Unknown bounds payload type: {payload.kind}")

def copy_attribute_element(source: ET.Element, target_node: ET.Element) -> None:
    attribute_id = source.attrib.get("id")
    if not attribute_id:
        return

    target = get_direct_attribute_by_id(target_node, attribute_id)
    if target is None:
        target = ET.Element("attribute")
        target_node.append(target)

    target.attrib.clear()
    target.attrib.update(source.attrib)
    if "type" not in target.attrib:
        target.set("type", get_attribute_type_default(attribute_id))

def get_attribute_type_default(attribute_id: str) -> str:
    if attribute_id in {"BoundsMin", "BoundsMax", "Center", "Min", "Max"}:
        return "fvec3"
    if attribute_id in {"Radius", "Height", "Size", "CapsuleRadius", "CapsuleHeight"}:
        return "float"
    if attribute_id in {"IsIgnoringScale", "IgnoreScale"}:
        return "bool"
    if attribute_id in {"Shape", "Type"}:
        return "uint8"
    return "FixedString"

def ensure_children_element(node: ET.Element) -> ET.Element:
    children = get_direct_children_element(node)
    if children is not None:
        return children

    children = ET.Element("children")
    node.append(children)
    return children
