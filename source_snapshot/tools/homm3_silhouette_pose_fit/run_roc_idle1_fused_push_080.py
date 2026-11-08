#!/usr/bin/env python3
"""Push roc idle1 transit fused stack toward mean hybrid score 0.80.

error_leverage (occupancy leftover × screen joint reach) schedules macro root
(90 deg cap, per-worst-frame hypothesis) + top-bone combos, then adaptive
articulated walk, score_escape until plateau.

No unit-specific hacks; no LLM authoring. Generated-artifact only.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
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
RUN_DEST = "fused_push_v25_collision_worst_escape"
SEED_CLIP_RESULT: Path | None = (
    OUT / "fused_push_v23_shared_yaw_escape" / "gpu_clip_result.json"
)

MEMORY_SAFE_OVERRIDES = {
    "joint_score_raster_batch": 512,
    "root_hypotheses": 32,
}

V25_ESCAPE_OVERRIDES = {
    "score_escape_mode": "worst_stack",
    "score_escape_max_rounds": 12,
    "score_escape_min_improvement": 0.0015,
    "score_escape_worst_frame_count": 12,
    "score_escape_worst_frame_collision_weight": 0.45,
    "score_escape_collision_burst_threshold": 0.08,
    "branch_rescue_values_per_bone": 4,
    "score_escape_articulated_iterations": 6,
}

FAST_PUSH_OVERRIDES = {
    "articulated_root_interleave_enabled": False,
    "score_escape_max_rounds": 4,
    "score_escape_worst_frame_count": 6,
    "score_escape_articulated_iterations": 4,
    "root_hypotheses": 32,
    "joint_temporal_consensus_enabled": False,
}

sys.path.insert(0, str(TOOL))

from cascade_anatomy_bone_order import (
    cascade_kwargs_from_catalog_transit,
)
from run_roc_idle1_start_move_end_root_weave import (
    KEEP_FRAME_INDICES,
    idle1_start_move_end_config,
    release_gpu,
    shared_kwargs,
    stage_sequential_pngs,
)

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
    clip="idle1_start_move_end",
)

PUSH_OVERRIDES = {
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
    "motion_exempt_idle_prefix": False,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "joint_collision_positive_abs_slack": 0.12,
    "profile_init_enabled": True,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": True,
    "joint_temporal_consensus_idle_end": False,
    "sprite_aligned_motion_keep_enabled": False,
    "live_preview": False,
    "articulated_iterations": 5,
    "articulated_root_interleave_enabled": False,
    "articulated_funnel_enabled": True,
    "articulated_funnel_broad_step_deg": 45.0,
    "articulated_funnel_broad_probe_rungs": 4,
    "articulated_funnel_broad_rounds": 1,
    "articulated_funnel_broad_min_improvement": 0.0,
    "articulated_funnel_broad_multi_bone_block_size": 3,
    "articulated_funnel_worst_frame_keep_enabled": True,
    "articulated_funnel_worst_frame_keep_count": 6,
    "articulated_funnel_worst_frame_keep_weight": 2.0,
    "fine_iterations": 0,
    "freeze_root_after_root_stage": True,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": True,
    "skip_tiny_bones": False,
    "root_search_enabled": False,
    "root_refit_after_base_enabled": False,
    "root_rotation_defer_camera_up": True,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_camera_up_limit_deg": 45.0,
    "root_rotation_per_frame_limit_deg": 30.0,
    "root_rotation_first_frame_limit_deg": 30.0,
    "root_hypotheses": 64,
    "articulated_multi_bone_enabled": True,
    "articulated_multi_bone_block_size": 2,
    "seed_previous_frame": True,
    "idle_prefix_frames": 1,
    "idle_suffix_frames": 0,
    "ik_enabled": False,
    "idle_fused_macro_enabled": True,
    "idle_fused_skip_macro_when_seeded": True,
    "idle_fused_skip_reroot_when_seeded": True,
    "root_skip_when_seeded": True,
    "articulated_skip_when_seeded": True,
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
    "idle_fused_shared_transit_yaw_enabled": True,
    "idle_fused_shared_transit_yaw_bone_adapt_rounds": 2,
    "idle_fused_shared_transit_yaw_bone_adapt_top_bones": 6,
    "idle_fused_shared_transit_yaw_step_deg": 15.0,
    "score_escape_mode": "until_plateau",
    "score_escape_max_rounds": 10,
    "live_status_path": str(OUT / "live_status.json"),
    "idle_fused_reroot_transit_after_articulated": True,
    "idle_fused_reroot_all_transit": False,
    "score_escape_collision_burst_enabled": True,
    "score_escape_collision_burst_threshold": 0.15,
    "score_escape_enabled": True,
    "score_escape_threshold": 0.80,
    "score_escape_min_improvement": 0.003,
    "score_escape_root_window_deg": 90.0,
    "score_escape_root_step_deg": 10.0,
    "score_escape_worst_frame_count": 10,
    "score_escape_coarse_push_coarse": 0.88,
    "score_escape_articulated_iterations": 8,
    "score_escape_threshold_uses_hybrid_mean": True,
    "score_escape_skip_coarse_broad_when_seeded": True,
    "score_escape_shared_transit_yaw_enabled": True,
    "score_escape_skip_articulated_retry_when_seeded": True,
    "score_escape_translation_burst_enabled": False,
    **ANATOMY_KWARGS,
    # Anatomy catalog defaults bone_order_mode to dependency. Ranking must
    # win: leftover pixels × screen joint reach, not hips-then-leaves.
    "bone_order_mode": "error_leverage",
    "idle_fused_importance_mode": "error_leverage",
    "articulated_funnel_force_gradient_order": False,
}


def seed_camera_fit_path(clip_result: Path) -> Path | None:
    payload = json.loads(clip_result.read_text(encoding="utf-8"))
    raw_path = payload.get("cameraFitPath")
    if raw_path:
        resolved = Path(str(raw_path))
        if resolved.is_file():
            return resolved
    sibling = clip_result.parent / "initialization" / "profile_camera_fit.json"
    return sibling if sibling.is_file() else None


def load_initial_poses(path: Path) -> dict[int, dict] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    poses = payload.get("poses")
    if not isinstance(poses, dict) or not poses:
        return None
    return {int(frame): pose for frame, pose in poses.items()}


def sprite_src_dir(hybrid) -> Path:
    root = Path(hybrid.root).resolve()
    pilot = (
        Path(hybrid.pilot_dir).resolve()
        if hybrid.pilot_dir
        else root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    )
    return (pilot / hybrid.shadow_culled_frame_dir).resolve()


def compose_grid(out_root: Path, dest: Path, score: float, sprite_src: Path) -> Path:
    from compose_method_compare_gif import main as compose_main

    seq = dest / "solved_rgb_sequential"
    stage_sequential_pngs(dest / "solved_rgb", seq, KEEP_FRAME_INDICES)
    gif = out_root / "idle1_fused_push_080.gif"
    sprite_seq = out_root / "sprite_sequential"
    try:
        stage_sequential_pngs(sprite_src, sprite_seq, KEEP_FRAME_INDICES)
        sprite_panel = str(sprite_seq)
    except FileNotFoundError as exc:
        print(f"skip sprite panel: {exc}", flush=True)
        sprite_panel = str(SPRITE_STAGED)
    argv = [
        "--out",
        str(gif),
        "--cols",
        "3",
        "--cell-w",
        "220",
        "--cell-h",
        "260",
        "--hold",
        "2",
        "--frame-count",
        str(len(KEEP_FRAME_INDICES)),
        "--panel",
        "sprite",
        sprite_panel,
        "--panel",
        f"push {score:.3f}",
        str(seq),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("GIF compose failed")
    return gif


def main() -> int:
    import os

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
    (out_root / "push_plan.json").write_text(
        json.dumps(
            {
                "targetScore": 0.8,
                "overrides": PUSH_OVERRIDES,
                "seedClipResult": str(SEED_CLIP_RESULT) if SEED_CLIP_RESULT else None,
                "dest": RUN_DEST,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    config = idle1_start_move_end_config(MESH, NOTEBOOK)
    if SEED_CLIP_RESULT is not None and SEED_CLIP_RESULT.is_file():
        seed_camera = seed_camera_fit_path(SEED_CLIP_RESULT)
        if seed_camera is not None:
            config = replace(config, camera_fit_path=str(seed_camera))
            print(f"seed camera from {seed_camera}", flush=True)
    hybrid = prepare_gpu_fit_config(config)
    kwargs = {**shared_kwargs(), **PUSH_OVERRIDES}
    kwargs.update(MEMORY_SAFE_OVERRIDES)
    kwargs.update(V25_ESCAPE_OVERRIDES)
    if os.environ.get("ROC_FUSED_PUSH_FAST", "").strip().lower() in {"1", "true", "yes"}:
        kwargs.update(FAST_PUSH_OVERRIDES)
        print("ROC_FUSED_PUSH_FAST=1: using reduced escape/consensus budget", flush=True)
    initial_poses = load_initial_poses(SEED_CLIP_RESULT) if SEED_CLIP_RESULT is not None else None
    if initial_poses is not None:
        kwargs["profile_init_enabled"] = False
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        print(f"fit fused_push_080 -> {dest}", flush=True)
        print(
            f"memory_safe joint_score_raster_batch={kwargs.get('joint_score_raster_batch')} "
            f"root_hypotheses={kwargs.get('root_hypotheses')} "
            f"escape_collision_weight={kwargs.get('score_escape_worst_frame_collision_weight')}",
            flush=True,
        )
        if initial_poses is not None:
            print(f"seed poses from {SEED_CLIP_RESULT}", flush=True)
        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=dest,
            initial_poses=initial_poses,
            **kwargs,
        )
        payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
        score = float(payload.get("score") or 0)
        fs = payload.get("frameScores") or []
        report = {
            "targetScore": 0.8,
            "score": score,
            "achieved": score >= 0.8,
            "frameScores": fs,
            "elapsedSec": round(time.perf_counter() - started, 1),
            "solver": payload.get("solver"),
        }
        (out_root / "push_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
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
