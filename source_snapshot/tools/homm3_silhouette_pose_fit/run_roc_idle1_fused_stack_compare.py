#!/usr/bin/env python3
"""Roc idle1 transit: gradient_magnitude + idle-fused macro stack.

Motion-importance (gradient_magnitude) drives macro root yaw + top-bone combo
probes before the articulated walk. Idle prefix is snapshotted/restored.

5-minute viability budget: articulated_iterations=1, no IK.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/fused_stack_compare"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
SPRITE_STAGED = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end"
    / "sprite_idle1_start_move_end"
)

sys.path.insert(0, str(TOOL))

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit
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

BUDGET_FIT = {
    "score_mode": "geometry",
    "motion_weight": 1.0,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": True,
    "joint_temporal_consensus_idle_end": False,
    "sprite_aligned_motion_keep_enabled": False,
    "live_preview": False,
    "articulated_iterations": 1,
    "fine_iterations": 0,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": False,
    "skip_tiny_bones": False,
    "bone_order_mode": "gradient_magnitude",
    "root_search_enabled": False,
    "root_refit_after_base_enabled": False,
    "articulated_root_interleave_enabled": True,
    "articulated_root_interleave_rotation_deg": 8.0,
    "articulated_root_interleave_rotation_step_deg": 4.0,
    "articulated_root_interleave_include_translation": False,
    "articulated_root_interleave_policy": "primary_group_end",
    "articulated_multi_bone_enabled": True,
    "articulated_multi_bone_block_size": 2,
    "seed_previous_frame": True,
    "idle_prefix_frames": 1,
    "idle_suffix_frames": 0,
    "ik_enabled": False,
    **ANATOMY_KWARGS,
}

TRIALS = (
    {
        "id": "grad_mag_baseline",
        "label": "grad only",
        "overrides": {**BUDGET_FIT, "idle_fused_macro_enabled": False},
    },
    {
        "id": "grad_mag_fused_macro",
        "label": "grad+fused",
        "overrides": {
            **BUDGET_FIT,
            "idle_fused_macro_enabled": True,
            "idle_fused_importance_mode": "gradient_magnitude",
            "idle_fused_root_window_deg": 45.0,
            "idle_fused_root_step_deg": 15.0,
            "idle_fused_macro_step_deg": 22.0,
            "idle_fused_top_bone_count": 6,
            "idle_fused_macro_chain_count": 2,
        },
    },
)


def compose_grid(out_root: Path, panels: list[tuple[str, Path]]) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = out_root / "idle1_fused_stack_compare.gif"
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
        str(SPRITE_STAGED),
    ]
    for label, folder in panels:
        argv.extend(["--panel", label, str(folder)])
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
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    out_root = OUT
    out_root.mkdir(parents=True, exist_ok=True)
    config = idle1_start_move_end_config(MESH, NOTEBOOK)
    base_kwargs = shared_kwargs()
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    results: list[dict] = []
    started = time.perf_counter()
    try:
        for trial in TRIALS:
            dest = out_root / str(trial["id"])
            dest.mkdir(parents=True, exist_ok=True)
            kwargs = {**base_kwargs, **trial["overrides"]}
            print(f"fit {trial['id']} -> {dest}", flush=True)
            run_gpu_depth_fit_from_hybrid_config(config, output_dir=dest, **kwargs)
            payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
            score = float(payload.get("score") or 0)
            results.append({"id": trial["id"], "label": trial["label"], "score": score})
            print(f"done {trial['id']} score={score:.4f}", flush=True)
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)

    report = {"elapsedSec": round(time.perf_counter() - started, 1), "results": results}
    (out_root / "fused_stack_compare_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    panels: list[tuple[str, Path]] = []
    for trial in TRIALS:
        dest = out_root / str(trial["id"])
        score = next(r["score"] for r in results if r["id"] == trial["id"])
        seq = dest / "solved_rgb_sequential"
        stage_sequential_pngs(dest / "solved_rgb", seq, KEEP_FRAME_INDICES)
        panels.append((f"{trial['label']} {score:.3f}", seq))

    gif = compose_grid(out_root, panels)
    print(f"composed {gif}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
