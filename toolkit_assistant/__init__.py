"""Public API for Toolkit Assistant."""

from __future__ import annotations

from .app import ToolkitAssistantApp, main
from .bounds_patcher import (
    find_matching_lsf_by_uuid,
    normalize_uuid_values,
    parse_uuid_values,
    patch_all_visualbank_lsf_files,
    patch_lsf_file,
    patch_lsf_files_by_uuid,
    patch_lsf_from_related_mesh,
    patch_visualbank_lsf_files_from_related_mesh,
)
from .constants import *
from .divine import convert_model, convert_resource, find_default_divine, resolve_divine
from .import_repair import (
    get_import_source_repairs,
    iter_settings_nodes,
    repair_import_settings_sources,
    repair_import_source_path,
)
from .lsx import (
    apply_bounds_payload,
    copy_attribute_element,
    ensure_children_element,
    get_attribute_type_default,
    get_bounds_payload,
    get_game_object_candidates,
    get_single_target_node,
    get_target_nodes_by_uuid,
    node_matches_uuid,
)
from .mesh_bounds import (
    calculate_collada_bounds,
    calculate_mesh_bounds,
    collect_collada_node_positions,
    collect_position_sources_from_vertices,
    convert_position_to_visualbank_space,
    format_float,
    format_mesh_bounds_xml,
    format_vec3,
    get_collada_node_transform,
    identity_matrix,
    multiply_matrices,
    parse_float_values,
    parse_matrix_values,
    parse_rotate_values,
    parse_scale_values,
    parse_translate_values,
    read_collada_controller_positions,
    read_collada_float_source_positions,
    read_collada_geometry_positions,
    read_collada_instanced_positions,
    read_collada_mesh_positions,
    read_collada_positions,
    read_collada_uninstanced_positions,
    transform_point,
    VISUALBANK_X_OFFSET,
)
from .models import BoundsPayload, ImportSourceRepair, LsfBatchTarget, MeshBounds, MeshReference, ProjectBackupCopy
from .paths import get_game_folder_error, is_path_within
from .project_tools import (
    backup_toolkit_projects,
    find_toolkit_project_names,
    get_module_info_node,
    get_project_backup_copies,
    has_invalid_windows_filename_chars,
    rename_toolkit_mod_project,
    resolve_existing_mod_folder_name,
    split_mod_folder_uuid_suffix,
    update_project_meta_file,
)
from .resources import (
    dedupe_mesh_references,
    describe_node_for_log,
    extract_gr2_path,
    find_gr2_mesh_references,
    format_mesh_reference_summary,
    get_single_gr2_mesh_reference,
    get_visualbank_gr2_mesh_references,
    get_visualbank_resource_nodes,
    node_has_direct_attribute_value,
    resolve_gr2_resource_path,
    split_resource_path,
)
from .settings import load_settings, save_settings
from .temp_files import delete_temp_folder_contents
from .xml_utils import (
    find_nodes_by_id,
    get_direct_attribute_by_id,
    get_direct_attribute_elements,
    get_direct_child_by_name,
    get_direct_child_node_by_id,
    get_direct_children_by_name,
    get_direct_children_element,
    iter_elements,
    local_name,
    parse_xml_fragment,
    replace_child,
    safe_file_stem,
    save_xml,
)
