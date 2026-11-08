#!/usr/bin/env python3
"""Compare autonomous alternate-deformation lanes on roc idle1 transit.

Runs hierarchical parenting, auto shape keys, lattice, and vertex-array fits
with bone joints fixed at bind, profile camera initialization, and collision
scoring enabled.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/alternate_deform_compare"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

sys.path.insert(0, str(TOOL))

from gpu_alternate_deform import (
    DEFORM_METHODS,
    attach_profile_locked_root,
    prepare_profile_camera_fit,
    run_alternate_deform_method,
)
from run_roc_idle1_start_move_end_root_weave import (
    KEEP_FRAME_INDICES,
    idle1_start_move_end_config,
    release_gpu,
    shared_kwargs,
    stage_sequential_pngs,
)

COMPARE_OVERRIDES = {
    "score_mode": "geometry",
    "motion_weight": 1.0,
    "motion_exempt_idle_prefix": False,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "score_escape_collision_burst_enabled": False,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
    "physics_smooth_enabled": False,
    "root_search_enabled": False,
    "articulated_root_interleave_enabled": False,
    "idle_fused_macro_enabled": False,
    "score_escape_enabled": False,
    "live_preview": False,
    "profile_init_enabled": True,
    "idle_fused_shared_transit_yaw_enabled": False,
}


def build_experiment():
    from gpu_geometry_score import gpu_score_raster_resolution
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_gpu_cascade_experiment import GpuCascadeExperiment
    from roc_semantic_hybrid_experiment import prepare_gpu_fit_config

    hybrid = prepare_gpu_fit_config(idle1_start_move_end_config(MESH, NOTEBOOK))
    kwargs = {**shared_kwargs(), **COMPARE_OVERRIDES}
    gpu_config = run_gpu_depth_fit_from_hybrid_config(hybrid, config_only=True, **kwargs)
    gpu_config = replace(
        gpu_config,
        optimize_bones=False,
        root_iterations=0,
        articulated_iterations=0,
        fine_iterations=0,
        root_search_enabled=False,
        optimize_root_translation=False,
        optimize_root_rotation=False,
    )
    root = Path(hybrid.root).resolve()
    pilot = (
        Path(hybrid.pilot_dir).resolve()
        if hybrid.pilot_dir
        else root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    )
    target = (pilot / hybrid.shadow_culled_frame_dir).resolve()
    frame_indices = tuple(int(frame) for frame in hybrid.frame_indices)
    score_resolution = gpu_score_raster_resolution(
        tuple(int(value) for value in gpu_config.resolution),
        chroma_weight=float(gpu_config.chroma_weight),
        chroma_resolution=gpu_config.chroma_resolution,
        chroma_scale=int(gpu_config.chroma_scale),
        rgb_upsample=gpu_config.uses_rgb_raster(),
    )
    profile_fit, profile_report = prepare_profile_camera_fit(
        hybrid,
        pilot=pilot,
        target=target,
        frame_indices=frame_indices,
        output_dir=OUT,
        profile_init_enabled=bool(COMPARE_OVERRIDES.get("profile_init_enabled", True)),
        proxy_resolution=tuple(int(value) for value in score_resolution),
    )
    experiment = GpuCascadeExperiment(
        src_glb=Path(hybrid.src_glb).resolve(),
        camera_fit=profile_fit,
        target_frame_dir=target,
        frame_indices=frame_indices,
        config=gpu_config,
    )
    attach_profile_locked_root(experiment, profile_report)
    return experiment, hybrid, target


def compose_compare_gif(
    out_root: Path,
    panels: list[tuple[str, Path]],
    score_line: str,
    *,
    sprite_src: Path | None = None,
) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = out_root / "idle1_alternate_deform_compare.gif"
    argv = ["--out", str(gif), "--frame-count", str(len(KEEP_FRAME_INDICES)), "--cols", "3"]
    if sprite_src is not None and sprite_src.is_dir():
        seq = out_root / "sprite_sequential"
        try:
            stage_sequential_pngs(sprite_src, seq, KEEP_FRAME_INDICES)
            argv.extend(["--panel", "sprite", str(seq)])
        except FileNotFoundError as exc:
            print(f"skip sprite panel: {exc}", flush=True)
    for label, solved_dir in panels:
        seq = solved_dir.parent / f"{solved_dir.name}_sequential"
        stage_sequential_pngs(solved_dir, seq, KEEP_FRAME_INDICES)
        argv.extend(["--panel", label, str(seq)])
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

    out_root = OUT
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "compare_plan.json").write_text(
        json.dumps(
            {
                "methods": list(DEFORM_METHODS),
                "collision_enabled": True,
                "collision_weight": 0.35,
                "profile_init_enabled": True,
                "overrides": COMPARE_OVERRIDES,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    reports: list[dict] = []
    panels: list[tuple[str, Path]] = []
    hybrid = None
    sprite_src = None
    try:
        experiment, hybrid, sprite_src = build_experiment()
        try:
            for method in DEFORM_METHODS:
                dest = out_root / method
                print(f"alternate deform {method} -> {dest}", flush=True)
                report = run_alternate_deform_method(
                    experiment,
                    method=method,
                    output_dir=dest,
                    groups_catalog_path=GROUPS,
                    max_rounds=4,
                    probe_deg=18.0,
                    lattice_grid=2,
                )
                reports.append(report)
                panels.append((method.replace("_", " "), dest / "solved_rgb"))
                print(
                    f"{method}: score={report['score']:.4f} "
                    f"collision_mean={sum(report.get('collisionError') or [0]) / max(1, len(KEEP_FRAME_INDICES)):.4f}",
                    flush=True,
                )
        finally:
            experiment.release_cuda()
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)

    score_line = " | ".join(f"{row['method']} {float(row['score']):.3f}" for row in reports)
    summary = {
        "elapsedSec": round(time.perf_counter() - started, 1),
        "collision_enabled": True,
        "collision_weight": 0.35,
        "profile_init_enabled": True,
        "methods": reports,
        "hybridConfig": {
            "animation_name": getattr(hybrid, "animation_name", None),
            "frame_indices": list(KEEP_FRAME_INDICES),
        },
    }
    (out_root / "compare_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    gif = compose_compare_gif(out_root, panels, score_line, sprite_src=sprite_src)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"composed {gif}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
