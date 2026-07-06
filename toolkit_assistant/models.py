"""Small data containers shared by Toolkit Assistant workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class BoundsPayload:
    kind: str
    bounds_node: ET.Element | None = None
    bound_nodes: tuple[ET.Element, ...] = ()
    attributes: tuple[ET.Element, ...] = ()

@dataclass(frozen=True)
class LsfBatchTarget:
    file: Path
    matched_uuid: str

@dataclass(frozen=True)
class ImportSourceRepair:
    old_source: str
    new_source: str

@dataclass(frozen=True)
class ProjectBackupCopy:
    source: Path
    destination: Path

@dataclass(frozen=True)
class MeshBounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    center: tuple[float, float, float]
    radius: float
    vertex_count: int

@dataclass(frozen=True)
class MeshReference:
    source_file: str
    resolved_path: Path
    target_node: ET.Element
    attribute_id: str
