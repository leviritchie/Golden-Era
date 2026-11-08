#!/usr/bin/env python3
"""Roc Move: notebook DINOv3 artic path with axis/envelope clamps opened.

Does not use flyer autolock. Same cascade entry as the chromatic notebook
(`run_gpu_depth_fit_from_hybrid_config`, score_mode=dinov3_dense) with:
  - joint_search_axes x/y/z + diagonal 6
  - all bones searchable
  - no bone_limit_scale_overrides
  - freeze_root_after_root_stage=False
  - wide root rotation limits
  - ik_enabled=False (avoids proximal 15° clamp)
  - physics_smooth_enabled=False
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE_CAM = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/initialization"
    / "flyer_side_profile_camera_fit.json"
)
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad/roc_move_dinov3_unrestricted_artic"
METHOD = "dinov3_unrestricted_artic"
BUDGET_SEC = 300.0

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))


def main() -> int:
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from run_chain_space_surface_compare import _prepare_choice_config, _sprite_dir, compose_clip_gif
    from run_crusader_gpu_cascade_animation_set import (
        _release_gpu_workspace,
        notebook_gpu_fit_kwargs,
    )
    import roc_semantic_hybrid_widgets as widgets

    if not MESH.is_file():
        raise FileNotFoundError(MESH)
    if not SIDE_CAM.is_file():
        raise FileNotFoundError(SIDE_CAM)

    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        from run_hybrid_method_quad import _build_isolated_def_choice

        choice = _build_isolated_def_choice(
            widgets, unit_sid="h3_roc", def_groups=(0,)
        )
        config = _prepare_choice_config(choice, MESH, NOTEBOOK)
        config.camera_fit_path = str(SIDE_CAM)
        if hasattr(config, "joint_free_deg"):
            config.joint_free_deg = 150.0

        arm = OUT / METHOD
        arm.mkdir(parents=True, exist_ok=True)

        kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
        # Notebook DINOv3 artic, clamps opened.
        kwargs.update(
            {
                "score_mode": "dinov3_dense",
                "dense_semantic_model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
                "dense_semantic_feature_layers": ("last",),
                "dense_semantic_local_radius": 1,
                "dense_semantic_position_weight": 1.0,
                "dense_semantic_raster_scale": 4,
                "dense_semantic_batch_size": 8,
                "depth_weight": 0.0,
                "silhouette_weight": 0.0,
                "chroma_weight": 0.0,
                "motion_weight": 0.0,
                "collision_enabled": False,
                "collision_weight": 0.0,
                "gradient_ladder_enabled": False,
                "chain_space_enabled": False,
                "ik_enabled": False,
                "physics_smooth_enabled": False,
                "profile_init_enabled": True,
                "profile_init_camera_basis_mode": "upright_turntable",
                "root_search_enabled": True,
                "root_rotation_axes": ("camera_forward", "camera_right", "camera_up"),
                "root_rotation_camera_up_limit_deg": 180.0,
                "root_rotation_first_frame_limit_deg": 180.0,
                "root_rotation_per_frame_limit_deg": 180.0,
                "root_rotation_defer_camera_up": False,
                "freeze_root_after_root_stage": False,
                "search_bones": (),
                "include_unlisted_search_bones": True,
                "bone_limit_scale_overrides": (),
                "joint_search_axes": ("x", "y", "z"),
                "joint_diagonal_axes": 6,
                "joint_step_deg": 15.0,
                "mid_joint_step_deg": 5.0,
                "fine_joint_step_deg": 2.5,
                "articulated_iterations": 1,
                "fine_iterations": 0,
                "base_pose_enabled": False,
                "mid_pose_enabled": False,
                "branch_rescue_enabled": False,
                "root_refit_after_base_enabled": False,
                "fine_root_enabled": False,
                "skip_tiny_bones": False,
                "bone_order_mode": "dependency",
            }
        )
        # Drop unknown keys from notebook dump that are not in the fit signature.
        import inspect

        allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
        kwargs = {k: v for k, v in kwargs.items() if k in allowed}

        print(
            f"roc_move DINOv3 unrestricted artic -> {arm} "
            f"score={kwargs.get('score_mode')} artic={kwargs.get('articulated_iterations')} "
            f"axes={kwargs.get('joint_search_axes')} freeze_root={kwargs.get('freeze_root_after_root_stage')}",
            flush=True,
        )
        solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm, **kwargs)
        _release_gpu_workspace()

        pose_result = getattr(solved, "pose_result", None) or getattr(solved, "clip_result", None) or {}
        if not isinstance(pose_result, dict):
            pose_result = {}
        result_path = Path(
            pose_result.get("clipResultPath")
            or pose_result.get("clip_result_path")
            or (arm / "gpu_clip_result.json")
        )
        if not result_path.is_file():
            for cand in sorted(arm.glob("*clip*.json")) + sorted(arm.glob("*result*.json")):
                if cand.is_file():
                    result_path = cand
                    break
        payload = (
            json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        )
        sprite_dir = Path(_sprite_dir(choice))
        frame_count = len(tuple(getattr(config, "frame_indices", ()) or ())) or 6
        gif = compose_clip_gif(
            clip_root=OUT,
            sprite_dir=sprite_dir,
            frame_count=frame_count,
            arms=({"id": METHOD},),
        )
        elapsed = time.perf_counter() - started
        report = {
            "method": METHOD,
            "proof": "generated-artifact; notebook DINOv3 artic with clamps opened; not OE runtime",
            "elapsedSec": round(elapsed, 1),
            "budgetSec": BUDGET_SEC,
            "withinBudget": elapsed <= BUDGET_SEC,
            "gif": str(gif).replace("\\", "/"),
            "clipResult": str(result_path).replace("\\", "/"),
            "score_mode": (payload.get("config") or {}).get("score_mode"),
            "frameIoU": payload.get("frameIoU") or payload.get("frameScores"),
            "score": payload.get("score"),
            "knobs": {
                "joint_search_axes": list(kwargs.get("joint_search_axes") or ()),
                "joint_diagonal_axes": kwargs.get("joint_diagonal_axes"),
                "freeze_root_after_root_stage": kwargs.get("freeze_root_after_root_stage"),
                "articulated_iterations": kwargs.get("articulated_iterations"),
                "include_unlisted_search_bones": kwargs.get("include_unlisted_search_bones"),
                "bone_limit_scale_overrides": list(kwargs.get("bone_limit_scale_overrides") or ()),
                "ik_enabled": kwargs.get("ik_enabled"),
                "root_rotation_camera_up_limit_deg": kwargs.get("root_rotation_camera_up_limit_deg"),
            },
        }
        (OUT / "run_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        if elapsed > BUDGET_SEC:
            print(f"WARNING: exceeded {BUDGET_SEC:.0f}s budget ({elapsed:.1f}s)", flush=True)
        return 0
    finally:
        release_cascade_batch_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
