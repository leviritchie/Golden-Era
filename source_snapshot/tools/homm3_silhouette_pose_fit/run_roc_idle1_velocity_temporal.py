#!/usr/bin/env python3
"""Roc idle1 transit fused push with velocity/acceleration-only temporal scoring.

Uses geometry hybrid (silhouette + depth + chroma + collision) with motion_weight=0.
Temporal smoothness is velocity + acceleration on bones and root only — not
occupancy-motion blend. Clip objective (geometry − temporal penalty) is used in
score escape, root hypothesis search, and idle-fused macro selection.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/fused_push_080"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
SPRITE_STAGED = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end"
    / "sprite_idle1_start_move_end"
)
RUN_DEST = "fused_push_v14_velocity_temporal"

# Tighter escape budget for iteration (full push can raise these again).
FAST_ESCAPE_OVERRIDES = {
    "score_escape_max_rounds": 4,
    "score_escape_worst_frame_count": 6,
    "score_escape_articulated_iterations": 4,
    "root_hypotheses": 32,
}

sys.path.insert(0, str(TOOL))

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit
from run_roc_idle1_fused_push_080 import compose_grid, sprite_src_dir
from run_roc_idle1_start_move_end_root_weave import (
    KEEP_FRAME_INDICES,
    idle1_start_move_end_config,
    release_gpu,
    shared_kwargs,
)

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
    clip="idle1_start_move_end",
)

VELOCITY_TEMPORAL_OVERRIDES = {
    "score_mode": "geometry",
    "motion_weight": 0.0,
    "temporal_scoring_mode": "velocity_acceleration_only",
    "velocity_weight": 0.04,
    "acceleration_weight": 0.025,
    "root_velocity_weight": 0.02,
    "root_acceleration_weight": 0.01,
    "root_rotation_velocity_weight": 0.02,
    "root_rotation_acceleration_weight": 0.01,
    "bone_pose_prior_weight": 0.0,
    "root_translation_prior_weight": 0.0,
    "root_rotation_prior_weight": 0.0,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "joint_collision_positive_abs_slack": 0.12,
    "profile_init_enabled": True,
    "physics_smooth_enabled": False,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
    "live_preview": False,
    "articulated_iterations": 5,
    "articulated_funnel_enabled": True,
    "articulated_funnel_broad_step_deg": 45.0,
    "articulated_funnel_broad_probe_rungs": 4,
    "articulated_funnel_broad_rounds": 1,
    "articulated_funnel_broad_min_improvement": 0.0,
    "articulated_funnel_force_gradient_order": True,
    "articulated_funnel_broad_multi_bone_block_size": 3,
    "articulated_funnel_worst_frame_keep_enabled": True,
    "articulated_funnel_worst_frame_keep_count": 6,
    "articulated_funnel_worst_frame_keep_weight": 2.0,
    "fine_iterations": 0,
    "freeze_root_after_root_stage": True,
    "articulated_root_interleave_enabled": False,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": True,
    "skip_tiny_bones": False,
    "bone_order_mode": "gradient_magnitude",
    "root_search_enabled": False,
    "root_refit_after_base_enabled": False,
    "root_rotation_defer_camera_up": True,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_camera_up_limit_deg": 45.0,
    "root_rotation_per_frame_limit_deg": 30.0,
    "root_rotation_first_frame_limit_deg": 30.0,
    "articulated_multi_bone_enabled": True,
    "articulated_multi_bone_block_size": 2,
    "seed_previous_frame": True,
    "idle_prefix_frames": 1,
    "idle_suffix_frames": 0,
    "ik_enabled": False,
    "idle_fused_macro_enabled": True,
    "idle_fused_importance_mode": "gradient_magnitude",
    "idle_fused_root_window_deg": 90.0,
    "idle_fused_root_step_deg": 15.0,
    "idle_fused_macro_step_deg": 25.0,
    "idle_fused_top_bone_count": 6,
    "idle_fused_macro_chain_count": 3,
    "idle_fused_macro_root_rotation_axes": ("camera_forward", "camera_right"),
    "idle_fused_per_frame_root_enabled": False,
    "idle_fused_per_frame_root_count": 14,
    "anatomy_head_pin_enabled": False,
    "early_symmetry_enabled": True,
    "early_symmetry_visit_limit": 16,
    "idle_fused_shared_transit_yaw_enabled": False,
    "live_status_path": str(OUT / "live_status.json"),
    "idle_fused_reroot_transit_after_articulated": True,
    "idle_fused_reroot_all_transit": False,
    "score_escape_collision_burst_enabled": True,
    "score_escape_collision_burst_threshold": 0.15,
    "score_escape_enabled": True,
    "score_escape_mode": "until_plateau",
    "score_escape_threshold": 0.80,
    "score_escape_max_rounds": 4,
    "score_escape_min_improvement": 0.003,
    "score_escape_root_window_deg": 90.0,
    "score_escape_root_step_deg": 10.0,
    "score_escape_worst_frame_count": 6,
    "score_escape_coarse_push_coarse": 0.88,
    "score_escape_articulated_iterations": 4,
    "root_hypotheses": 32,
    **ANATOMY_KWARGS,
}


def main() -> int:
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import prepare_gpu_fit_config

    out_root = OUT
    dest = out_root / RUN_DEST
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "velocity_temporal_plan.json").write_text(
        json.dumps(
            {
                "dest": RUN_DEST,
                "temporalScoringMode": "velocity_acceleration_only",
                "motionWeight": 0.0,
                "overrides": VELOCITY_TEMPORAL_OVERRIDES,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    config = idle1_start_move_end_config(MESH, NOTEBOOK)
    hybrid = prepare_gpu_fit_config(config)
    kwargs = {**shared_kwargs(), **VELOCITY_TEMPORAL_OVERRIDES}
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        print(f"velocity temporal fused push -> {dest}", flush=True)
        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=dest,
            **kwargs,
        )
        payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
        score = float(payload.get("score") or 0)
        fs = payload.get("frameScores") or []
        report = {
            "temporalScoringMode": "velocity_acceleration_only",
            "motionWeight": 0.0,
            "targetScore": 0.8,
            "score": score,
            "achieved": score >= 0.8,
            "frameScores": fs,
            "elapsedSec": round(time.perf_counter() - started, 1),
            "solver": payload.get("solver"),
            "config": {
                "velocity_weight": payload.get("config", {}).get("velocity_weight"),
                "acceleration_weight": payload.get("config", {}).get("acceleration_weight"),
                "temporal_scoring_mode": payload.get("config", {}).get(
                    "temporal_scoring_mode"
                ),
                "motion_weight": payload.get("config", {}).get("motion_weight"),
            },
        }
        (dest / "velocity_temporal_report.json").write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        gif = compose_grid(out_root, dest, score, sprite_src_dir(hybrid))
        print(json.dumps(report, indent=2), flush=True)
        print(f"composed {gif}", flush=True)
        return 0 if score >= 0.8 else 1
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
