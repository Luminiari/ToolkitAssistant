"""Mesh bounds calculation for GR2 and Collada files."""

from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from .divine import convert_model, resolve_divine
from .models import MeshBounds
from .xml_utils import (
    get_direct_child_by_name,
    get_direct_children_by_name,
    iter_elements,
    local_name,
    safe_file_stem,
)


def calculate_mesh_bounds(
    mesh_file: str | Path,
    divine_path: str | Path | None = None,
    *,
    progress: Callable[[str], None] | None = None,
) -> MeshBounds:
    log = progress or (lambda message: None)
    source_mesh = Path(mesh_file).resolve()
    if not source_mesh.is_file():
        raise FileNotFoundError(f"Mesh file does not exist: {source_mesh}")

    suffix = source_mesh.suffix.lower()
    if suffix not in {".gr2", ".dae"}:
        raise ValueError("Expected a .gr2 or .dae mesh file.")

    if suffix == ".dae":
        return calculate_collada_bounds(source_mesh)

    divine = resolve_divine(divine_path)
    log(f"Using Divine: {divine}\n")
    with tempfile.TemporaryDirectory(prefix="ToolkitAssistant-mesh-") as work_dir_text:
        work_dir = Path(work_dir_text)
        dae_path = work_dir / f"{safe_file_stem(source_mesh)}.dae"
        log(f"Converting GR2 to temporary DAE: {source_mesh}\n")
        convert_model(divine, source_mesh, dae_path)
        return calculate_collada_bounds(dae_path)

def calculate_collada_bounds(dae_path: Path) -> MeshBounds:
    positions = read_collada_positions(dae_path)
    if not positions:
        raise ValueError(f"No mesh position vertices were found in: {dae_path}")

    min_x = min(position[0] for position in positions)
    min_y = min(position[1] for position in positions)
    min_z = min(position[2] for position in positions)
    max_x = max(position[0] for position in positions)
    max_y = max(position[1] for position in positions)
    max_z = max(position[2] for position in positions)

    minimum = (min_x, min_y, min_z)
    maximum = (max_x, max_y, max_z)
    center = ((min_x + max_x) / 2, (min_y + max_y) / 2, (min_z + max_z) / 2)
    half_x = (max_x - min_x) / 2
    half_y = (max_y - min_y) / 2
    half_z = (max_z - min_z) / 2
    radius = (half_x * half_x + half_y * half_y + half_z * half_z) ** 0.5
    return MeshBounds(minimum=minimum, maximum=maximum, center=center, radius=radius, vertex_count=len(positions))

def read_collada_positions(dae_path: Path) -> list[tuple[float, float, float]]:
    tree = ET.parse(dae_path)
    root = tree.getroot()
    sources_by_id = {
        source.attrib.get("id", ""): source
        for source in iter_elements(root, "source")
        if source.attrib.get("id")
    }
    geometry_positions = read_collada_geometry_positions(root, sources_by_id)
    controller_positions = read_collada_controller_positions(root, geometry_positions)
    instanced_positions = read_collada_instanced_positions(root, geometry_positions, controller_positions)
    if instanced_positions:
        return instanced_positions

    return read_collada_uninstanced_positions(root, sources_by_id)

def read_collada_geometry_positions(
    root: ET.Element,
    sources_by_id: dict[str, ET.Element],
) -> dict[str, list[tuple[float, float, float]]]:
    geometries: dict[str, list[tuple[float, float, float]]] = {}
    for geometry in iter_elements(root, "geometry"):
        geometry_id = geometry.attrib.get("id")
        if not geometry_id:
            continue

        mesh = get_direct_child_by_name(geometry, "mesh")
        if mesh is None:
            continue

        positions = read_collada_mesh_positions(mesh, sources_by_id)
        if positions:
            geometries[geometry_id] = positions

    return geometries

def read_collada_mesh_positions(
    mesh: ET.Element,
    sources_by_id: dict[str, ET.Element],
) -> list[tuple[float, float, float]]:
    vertices_by_id = {
        vertices.attrib.get("id", ""): vertices
        for vertices in get_direct_children_by_name(mesh, "vertices")
        if vertices.attrib.get("id")
    }
    position_source_ids: set[str] = set()

    for vertices in vertices_by_id.values():
        collect_position_sources_from_vertices(vertices, position_source_ids)

    for primitive_name in ("triangles", "polylist", "polygons", "lines", "linestrips"):
        for primitive in get_direct_children_by_name(mesh, primitive_name):
            for child in list(primitive):
                if local_name(child.tag) != "input":
                    continue

                semantic = child.attrib.get("semantic")
                source_id = child.attrib.get("source", "").lstrip("#")
                if semantic == "POSITION" and source_id:
                    position_source_ids.add(source_id)
                elif semantic == "VERTEX":
                    vertices = vertices_by_id.get(source_id)
                    if vertices is not None:
                        collect_position_sources_from_vertices(vertices, position_source_ids)

    if not position_source_ids:
        for source_id in sources_by_id:
            if "position" in source_id.lower():
                position_source_ids.add(source_id)

    positions: list[tuple[float, float, float]] = []
    for source_id in sorted(position_source_ids):
        source = sources_by_id.get(source_id)
        if source is not None:
            positions.extend(read_collada_float_source_positions(source))

    return positions

def collect_position_sources_from_vertices(vertices: ET.Element, position_source_ids: set[str]) -> None:
    for child in list(vertices):
        if local_name(child.tag) == "input" and child.attrib.get("semantic") == "POSITION":
            source_id = child.attrib.get("source", "").lstrip("#")
            if source_id:
                position_source_ids.add(source_id)

def read_collada_controller_positions(
    root: ET.Element,
    geometry_positions: dict[str, list[tuple[float, float, float]]],
) -> dict[str, list[tuple[float, float, float]]]:
    controllers: dict[str, list[tuple[float, float, float]]] = {}
    for controller in iter_elements(root, "controller"):
        controller_id = controller.attrib.get("id")
        if not controller_id:
            continue

        skin = get_direct_child_by_name(controller, "skin")
        if skin is None:
            continue

        geometry_id = skin.attrib.get("source", "").lstrip("#")
        positions = geometry_positions.get(geometry_id)
        if not positions:
            continue

        bind_shape_matrix = identity_matrix()
        bind_shape = get_direct_child_by_name(skin, "bind_shape_matrix")
        if bind_shape is not None and bind_shape.text:
            bind_shape_matrix = parse_matrix_values(bind_shape.text)

        controllers[controller_id] = [transform_point(bind_shape_matrix, position) for position in positions]

    return controllers

def read_collada_instanced_positions(
    root: ET.Element,
    geometry_positions: dict[str, list[tuple[float, float, float]]],
    controller_positions: dict[str, list[tuple[float, float, float]]],
) -> list[tuple[float, float, float]]:
    positions: list[tuple[float, float, float]] = []
    for visual_scene in iter_elements(root, "visual_scene"):
        for node in get_direct_children_by_name(visual_scene, "node"):
            collect_collada_node_positions(node, identity_matrix(), geometry_positions, controller_positions, positions)

    return positions

def collect_collada_node_positions(
    node: ET.Element,
    parent_matrix: tuple[float, ...],
    geometry_positions: dict[str, list[tuple[float, float, float]]],
    controller_positions: dict[str, list[tuple[float, float, float]]],
    output: list[tuple[float, float, float]],
) -> None:
    node_matrix = multiply_matrices(parent_matrix, get_collada_node_transform(node))
    for child in list(node):
        tag = local_name(child.tag)
        if tag == "instance_geometry":
            geometry_id = child.attrib.get("url", "").lstrip("#")
            output.extend(transform_point(node_matrix, position) for position in geometry_positions.get(geometry_id, ()))
        elif tag == "instance_controller":
            controller_id = child.attrib.get("url", "").lstrip("#")
            output.extend(transform_point(node_matrix, position) for position in controller_positions.get(controller_id, ()))
        elif tag == "node":
            collect_collada_node_positions(child, node_matrix, geometry_positions, controller_positions, output)

def get_collada_node_transform(node: ET.Element) -> tuple[float, ...]:
    transform = identity_matrix()
    for child in list(node):
        tag = local_name(child.tag)
        if tag == "matrix" and child.text:
            transform = multiply_matrices(transform, parse_matrix_values(child.text))
        elif tag == "translate" and child.text:
            transform = multiply_matrices(transform, parse_translate_values(child.text))
        elif tag == "scale" and child.text:
            transform = multiply_matrices(transform, parse_scale_values(child.text))
        elif tag == "rotate" and child.text:
            transform = multiply_matrices(transform, parse_rotate_values(child.text))

    return transform

def read_collada_uninstanced_positions(
    root: ET.Element,
    sources_by_id: dict[str, ET.Element],
) -> list[tuple[float, float, float]]:
    position_source_ids: set[str] = set()
    for vertices in iter_elements(root, "vertices"):
        collect_position_sources_from_vertices(vertices, position_source_ids)

    for mesh in iter_elements(root, "mesh"):
        for primitive_name in ("triangles", "polylist", "polygons", "lines", "linestrips"):
            for primitive in get_direct_children_by_name(mesh, primitive_name):
                for child in list(primitive):
                    if local_name(child.tag) == "input" and child.attrib.get("semantic") == "POSITION":
                        source_id = child.attrib.get("source", "").lstrip("#")
                        if source_id:
                            position_source_ids.add(source_id)

    if not position_source_ids:
        for source_id in sources_by_id:
            if "position" in source_id.lower():
                position_source_ids.add(source_id)

    positions: list[tuple[float, float, float]] = []
    for source_id in sorted(position_source_ids):
        source = sources_by_id.get(source_id)
        if source is not None:
            positions.extend(read_collada_float_source_positions(source))

    return positions

def identity_matrix() -> tuple[float, ...]:
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )

def parse_matrix_values(text: str) -> tuple[float, ...]:
    return tuple(parse_float_values(text, expected=16, label="matrix"))

def parse_translate_values(text: str) -> tuple[float, ...]:
    values = parse_float_values(text, expected=3, label="translate")
    return (
        1.0,
        0.0,
        0.0,
        values[0],
        0.0,
        1.0,
        0.0,
        values[1],
        0.0,
        0.0,
        1.0,
        values[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )

def parse_scale_values(text: str) -> tuple[float, ...]:
    values = parse_float_values(text, expected=3, label="scale")
    return (
        values[0],
        0.0,
        0.0,
        0.0,
        0.0,
        values[1],
        0.0,
        0.0,
        0.0,
        0.0,
        values[2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )

def parse_rotate_values(text: str) -> tuple[float, ...]:
    values = parse_float_values(text, expected=4, label="rotate")
    x, y, z, angle_degrees = values
    length = (x * x + y * y + z * z) ** 0.5
    if length == 0:
        return identity_matrix()

    x /= length
    y /= length
    z /= length
    angle = math.radians(angle_degrees)
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    one_minus_cos = 1.0 - cos_angle

    return (
        cos_angle + x * x * one_minus_cos,
        x * y * one_minus_cos - z * sin_angle,
        x * z * one_minus_cos + y * sin_angle,
        0.0,
        y * x * one_minus_cos + z * sin_angle,
        cos_angle + y * y * one_minus_cos,
        y * z * one_minus_cos - x * sin_angle,
        0.0,
        z * x * one_minus_cos - y * sin_angle,
        z * y * one_minus_cos + x * sin_angle,
        cos_angle + z * z * one_minus_cos,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )

def parse_float_values(text: str, *, expected: int, label: str) -> list[float]:
    try:
        values = [float(value) for value in text.split()]
    except ValueError as exc:
        raise ValueError(f"Could not parse Collada {label} values.") from exc

    if len(values) < expected:
        raise ValueError(f"Collada {label} expected {expected} values, found {len(values)}.")

    return values[:expected]

def multiply_matrices(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        sum(left[row * 4 + offset] * right[offset * 4 + column] for offset in range(4))
        for row in range(4)
        for column in range(4)
    )

def transform_point(matrix: tuple[float, ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )

def read_collada_float_source_positions(source: ET.Element) -> list[tuple[float, float, float]]:
    float_array = get_direct_child_by_name(source, "float_array")
    if float_array is None or not float_array.text:
        return []

    try:
        values = [float(value) for value in float_array.text.split()]
    except ValueError as exc:
        raise ValueError(f"Could not parse float array in Collada source '{source.attrib.get('id', '')}'.") from exc

    stride = 3
    accessor = None
    technique = get_direct_child_by_name(source, "technique_common")
    if technique is not None:
        accessor = get_direct_child_by_name(technique, "accessor")
    if accessor is not None:
        try:
            stride = int(accessor.attrib.get("stride", "3"))
        except ValueError:
            stride = 3

    if stride < 3:
        return []

    positions: list[tuple[float, float, float]] = []
    for index in range(0, len(values) - stride + 1, stride):
        positions.append((values[index], values[index + 1], values[index + 2]))

    return positions

def format_mesh_bounds_xml(bounds: MeshBounds) -> str:
    lines = [
        f'<attribute id="BoundsMax" type="fvec3" value="{format_vec3(bounds.maximum)}" />',
        f'<attribute id="BoundsMin" type="fvec3" value="{format_vec3(bounds.minimum)}" />',
        f'<attribute id="Center" type="fvec3" value="{format_vec3(bounds.center)}" />',
        f'<attribute id="Radius" type="float" value="{format_float(bounds.radius)}" />',
    ]
    return "\n".join(lines)

def format_vec3(values: tuple[float, float, float]) -> str:
    return " ".join(format_float(value) for value in values)

def format_float(value: float) -> str:
    text = f"{value:.2f}"
    return "0" if text in {"0.00", "-0.00"} else text
