"""Automated owned bind for Meshy smart-rig failures (rider+mount first)."""

from .animation_bind import (
    audit_reference_bind,
    bind_from_reference_frames,
    build_part_tree,
    mesh_boundary_edges,
)
from .audit import audit_owned_bind, lbs_delta_after_bone_rotate
from .bind import bind_species_mesh, skin_vertices
from .diagnose import diagnose_smartrig_quality
from .exact_bind import (
    ExactBindParams,
    audit_exact_bind,
    bind_from_exact_reference,
    fit_reference_scale,
    rescale_to_extent,
)
from .part_map import apply_part_map, load_part_map
from .pipeline import run_owned_rerig_pipeline
from .pose_source import (
    CaptureToWorld,
    PoseSource,
    ReferenceInconsistentError,
    SpriteCameraFit,
    load_registered_pose_source,
)
from .prop_fit import PropFitParams, measure_prop_region_fit
from .reference_frames import load_reference_frames
from .species import load_species_template, required_bone_names
from .strip import strip_armature
from .tpose import (
    CANONICAL_T_POSE,
    TPOSE_SCHEMA,
    character_frame,
    edge_stretch,
    rigid_weights,
    stretch_regions,
    tpose_joint_track,
)
from .weld_topology import weld_topology

# Stable public aliases used by CLIs/tests.
diagnose_smartrig_quality = diagnose_smartrig_quality
bind_species_mesh = bind_species_mesh
skin_vertices = skin_vertices
load_species_template = load_species_template
required_bone_names = required_bone_names
rotate_bone_lbs_delta = lbs_delta_after_bone_rotate

__all__ = [
    "CaptureToWorld",
    "ExactBindParams",
    "PoseSource",
    "PropFitParams",
    "ReferenceInconsistentError",
    "SpriteCameraFit",
    "apply_part_map",
    "audit_exact_bind",
    "audit_owned_bind",
    "audit_reference_bind",
    "bind_from_exact_reference",
    "bind_from_reference_frames",
    "bind_species_mesh",
    "build_part_tree",
    "diagnose_smartrig_quality",
    "fit_reference_scale",
    "lbs_delta_after_bone_rotate",
    "load_part_map",
    "load_reference_frames",
    "load_registered_pose_source",
    "load_species_template",
    "measure_prop_region_fit",
    "mesh_boundary_edges",
    "required_bone_names",
    "rescale_to_extent",
    "rotate_bone_lbs_delta",
    "run_owned_rerig_pipeline",
    "skin_vertices",
    "strip_armature",
    "weld_topology",
]
