"""Shared from-rest unlock base for Roc stacked solving experiments."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
UNIT = "h3_roc"
CLIP = "idle_start_move_end"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit  # noqa: E402

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
    clip=CLIP,
)

ANATOMY_VETO_KWARGS_ROC: dict[str, Any] = {
    "anatomy_veto_prop_enabled": False,
}

ANATOMY_VETO_KWARGS_CRUSADER: dict[str, Any] = {
    "anatomy_veto_prop_enabled": True,
    "anatomy_veto_bone_roles_path": str(
        TOOL / "bone_roles_crusader_smartrigged_rigidized.json"
    ),
    "anatomy_veto_prop_coords_path": str(
        ROOT
        / "artifacts/pose_picker_runs/h3_crusader/move_g0_props_authored/props_coords.json"
    ),
}

# Scoring + feasibility held constant across solve-compare trials.
STACKED_UNLOCK_BASE: dict[str, Any] = {
    "articulated_funnel_enabled": False,
    "articulated_funnel_force_gradient_order": False,
    "articulated_multi_bone_enabled": False,
    "joint_adaptive_step_enabled": False,
    "fine_iterations": 0,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": False,
    "score_escape_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": False,
    "include_unlisted_search_bones": True,
    "bone_limit_scale_overrides": (),
    "joint_search_axes": ("x", "y", "z"),
    "joint_diagonal_axes": 6,
    "cheap_joint_probe_occupancy_only": True,
    "cheap_joint_probe_frame_count": 0,
    "early_symmetry_enabled": False,
    "bone_order_mode": "error_leverage",
    "idle_fused_macro_enabled": False,
    "idle_fused_shared_transit_yaw_enabled": False,
    "root_search_enabled": False,
    "root_iterations": 0,
    "root_refit_after_base_enabled": False,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_defer_camera_up": False,
    "freeze_root_after_root_stage": True,
    "articulated_skip_when_seeded": False,
    "skip_tiny_bones": False,
    "live_preview": False,
    "seed_previous_frame": True,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
}

IK_MISS_BASE: dict[str, Any] = {
    "ik_enabled": True,
    "ik_keypoints_source": "silhouette_miss",
    "ik_keypoints_path": None,
    "ik_bone_roles_path": None,
    "ik_silhouette_score_mode": "frame_hybrid",
    "ik_max_step_deg": 2.5,
    "ik_proximal_max_step_deg": 2.5,
    "ik_proximal_min_depth": 0,
    "ik_step_scale_mode": "fixed",
    "ik_iterations": 6,
    "ik_blob_search_rounds": 4,
    "ik_max_chain_depth": 6,
    "ik_blob_iou_target": 0.95,
    "ik_require_improvement": False,
    "ik_dynamic_stop_enabled": False,
    "ik_frame_order_mode": "clip",
    "articulated_iterations": 0,
}

JOINT_PROBE_BASE: dict[str, Any] = {
    "ik_enabled": False,
    "joint_step_deg": 2.5,
    "fine_joint_step_deg": 2.5,
    "joint_pass_limit_deg": 10.0,
    "joint_probe_rungs": 4,
    "articulated_iterations": 6,
    "joint_round_followup_neighbors": False,
}

# Fast DINO joint iteration (~1–5 min): sparse worst-8 walk probes, coarse steps.
# Keep score is dinov3_geometry_consensus (sqrt(iou * softened logit-minmax DINO)),
# not raw dinov3_dense — raw DINO clusters near 0.9 so silhouette/IoU alone would
# drive accepts without per-pack normalization.
JOINT_DINO_QUICK_OVERRIDES: dict[str, Any] = {
    **JOINT_PROBE_BASE,
    "score_mode": "dinov3_geometry_consensus",
    "articulated_iterations": 2,
    "joint_step_deg": 7.5,
    "fine_joint_step_deg": 5.0,
    "joint_pass_limit_deg": 25.0,
    "joint_probe_rungs": 2,
    "cheap_joint_probe_frame_count": 8,
    "joint_adaptive_step_enabled": False,
    "joint_step_score_norm": "logit_minmax",
    "bone_order_mode": "dependency",
}

# Looser quick iteration: bigger steps, wider pass window, one extra round.
JOINT_DINO_QUICK_LOOSE_PATCH: dict[str, Any] = {
    "articulated_iterations": 3,
    "joint_step_deg": 12.0,
    "fine_joint_step_deg": 8.0,
    "joint_pass_limit_deg": 45.0,
    "joint_probe_rungs": 3,
    "idle_suffix_mirror_prefix_enabled": True,
}


def stacked_unit_resolve(unit: str, clip: str) -> dict[str, Any]:
    """Resolve mesh, notebook, anatomy, and optional geometry-IK seed lane per unit."""
    sid = str(unit)
    animation = str(clip)
    base = ROOT / "artifacts" / "pose_picker_runs" / sid / animation
    if sid == "h3_roc":
        return {
            "unit": sid,
            "clip": animation,
            "mesh": ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb",
            "notebook": NOTEBOOK,
            "anatomy_kwargs": dict(ANATOMY_KWARGS),
            "anatomy_veto_kwargs": dict(ANATOMY_VETO_KWARGS_ROC),
            "geometry_ik_root": base / "stacked_small_ik_v1",
        }
    if sid == "h3_crusader":
        return {
            "unit": sid,
            "clip": animation,
            "mesh": ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
            "notebook": NOTEBOOK,
            "anatomy_kwargs": {},
            "anatomy_veto_kwargs": dict(ANATOMY_VETO_KWARGS_CRUSADER),
            "geometry_ik_root": base / "stacked_small_ik_v1",
        }
    if sid == "h3_hobgoblin":
        return {
            "unit": sid,
            "clip": animation,
            "mesh": ROOT / "artifacts/meshy_downloads/h3_hobgoblin_smartrigged_rigidized.glb",
            "notebook": NOTEBOOK,
            "anatomy_kwargs": {},
            "anatomy_veto_kwargs": dict(ANATOMY_VETO_KWARGS_ROC),
            "geometry_ik_root": base / "gpu_cascade_delivery",
        }
    raise ValueError(f"unsupported stacked quick unit: {sid!r}")
