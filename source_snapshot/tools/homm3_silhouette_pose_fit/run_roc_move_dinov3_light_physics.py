#!/usr/bin/env python3
"""One-off: roc Move (DEF group 0) with notebook dinov3_dense cascade + light physics.

Does not overwrite idle keep files. Does not apply CURRENT_CASCADE_KEEP
(that keep refuses dinov3). Writes a new folder only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/move_dinov3_light_physics"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_chain_space_surface_compare import (  # noqa: E402
    _build_isolated_move_choice,
    compose_clip_gif,
)
from run_chain_space_surface_compare import _prepare_choice_config  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
)


def main() -> int:
    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        choice = _build_isolated_move_choice(widgets, unit_sid="h3_roc")
        config = _prepare_choice_config(choice, MESH, NOTEBOOK)
        gpu_kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
        gpu_kwargs.update(
            {
                "score_mode": "dinov3_dense",
                "chain_space_enabled": False,
                "gradient_ladder_enabled": False,
                "ik_enabled": False,
                "collision_enabled": False,
                "collision_weight": 0.0,
                "depth_weight": 0.0,
                "silhouette_weight": 0.0,
                "chroma_weight": 0.0,
                "motion_weight": 0.0,
                "joint_unique_gain_weight": 0.0,
                "fine_unique_gain_weight": 0.0,
                "physics_smooth_enabled": True,
                # Light vs keep defaults (stiffness 180, gravity 9.81, weight 0.6):
                # keep notebook 0.81 gravity, half stiffness, half gravity weight.
                "physics_smooth_stiffness": 90.0,
                "physics_smooth_gravity": 0.81,
                "physics_smooth_gravity_weight": 0.3,
                "articulated_iterations": 1,
            }
        )
        notes = {
            "schema": "roc_move_dinov3_light_physics.v1",
            "score_mode": "dinov3_dense",
            "physics": {
                "enabled": True,
                "stiffness": 90.0,
                "gravity": 0.81,
                "gravity_weight": 0.3,
            },
            "articulated_iterations": 1,
            "not": "CURRENT_CASCADE_KEEP geometry; not layer_surface",
            "idleKeepUntouched": True,
        }
        arm_dir = OUT / "dinov3_light_physics"
        arm_dir.mkdir(parents=True, exist_ok=True)
        (OUT / "notes.json").write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
        print(
            f"fit roc move dinov3_dense+light_physics frames={len(config.frame_indices)}",
            flush=True,
        )
        solved = run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=arm_dir,
            **gpu_kwargs,
        )
        result_path = Path(solved.pose_result["clipResultPath"])
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        config_out = payload.get("config") or {}
        if str(config_out.get("score_mode")) != "dinov3_dense":
            raise RuntimeError(f"expected dinov3_dense, got {config_out.get('score_mode')}")
        if not bool(config_out.get("physics_smooth_enabled")):
            raise RuntimeError("physics_smooth_enabled did not stay on")
        if bool(config_out.get("chain_space_enabled")):
            raise RuntimeError("chain_space must stay off for dinov3_dense")
        sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{choice.animation_name}_shadow_culled"
        gif = compose_clip_gif(
            clip_root=OUT,
            sprite_dir=sprite_dir,
            frame_count=len(config.frame_indices),
            arms=({"id": "dinov3_light_physics"},),
        )
        # compose_clip_gif looks for OUT/<arm_id>/solved_rgb; copy layout it expects
        report = {
            "gif": str(gif).replace("\\", "/"),
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "elapsedSec": round(time.perf_counter() - started, 1),
            "score_mode": config_out.get("score_mode"),
            "physics_smooth_enabled": config_out.get("physics_smooth_enabled"),
            "physics_smooth_stiffness": config_out.get("physics_smooth_stiffness"),
            "physics_smooth_gravity": config_out.get("physics_smooth_gravity"),
            "physics_smooth_gravity_weight": config_out.get("physics_smooth_gravity_weight"),
            "profile": payload.get("profileInit") or payload.get("profile"),
            "proof": "generated-artifact; not CURRENT_CASCADE_KEEP; not OE runtime",
        }
        (OUT / "run_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock, pid=os.getpid())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
