"""XML helpers for LSX, import settings, and Collada files."""

from __future__ import annotations

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_xml_fragment(text: str, label: str) -> ET.Element:
    stripped = text.strip()
    if not stripped:
        raise ValueError(f"{label} is empty.")

    for candidate in (stripped, f"<toolkit_assistant_root>{stripped}</toolkit_assistant_root>"):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError as error:
            last_error = error

    raise ValueError(f"Could not parse {label} as XML. {last_error}") from last_error

def save_xml(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)

def get_direct_children_element(node: ET.Element) -> ET.Element | None:
    for child in list(node):
        if local_name(child.tag) == "children":
            return child
    return None

def get_direct_child_node_by_id(node: ET.Element, node_id: str) -> ET.Element | None:
    children = get_direct_children_element(node)
    if children is None:
        return None

    for child in list(children):
        if local_name(child.tag) == "node" and child.attrib.get("id", "").lower() == node_id.lower():
            return child
    return None

def get_direct_attribute_by_id(node: ET.Element, attribute_id: str) -> ET.Element | None:
    for child in list(node):
        if local_name(child.tag) == "attribute" and child.attrib.get("id", "").lower() == attribute_id.lower():
            return child
    return None

def get_direct_attribute_elements(node: ET.Element) -> list[ET.Element]:
    return [child for child in list(node) if local_name(child.tag) == "attribute"]

def get_direct_child_by_name(node: ET.Element, tag_name: str) -> ET.Element | None:
    for child in list(node):
        if local_name(child.tag) == tag_name:
            return child
    return None

def get_direct_children_by_name(node: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in list(node) if local_name(child.tag) == tag_name]

def replace_child(parent: ET.Element, old_child: ET.Element, new_child: ET.Element) -> None:
    children = list(parent)
    index = children.index(old_child)
    parent.remove(old_child)
    parent.insert(index, new_child)

def find_nodes_by_id(root: ET.Element, node_id: str) -> list[ET.Element]:
    return [
        element
        for element in iter_elements(root, "node")
        if element.attrib.get("id", "").lower() == node_id.lower()
    ]

def iter_elements(root: ET.Element, tag_name: str):
    for element in root.iter():
        if local_name(element.tag) == tag_name:
            yield element

def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def safe_file_stem(path: Path) -> str:
    digest = hashlib.sha1(str(path).lower().encode("utf-8")).hexdigest()[:16]
    return digest
