#!/usr/bin/env python3
"""Regression: fused_push hybrid stack on three ground clips.

Default is **memory-safe** (tight raster batch + 2x chroma, reduced escape).
Full v24-class budget spills into shared GPU memory on this machine — only use
``--full`` or ``FUSED_REGRESSION_FULL=1`` when the GPU lane is empty and you
accept long runs + dedicated VRAM pressure.

Clips:
- Behemoth Move (DEF 0)
- Crusader AttackFront (DEF 12)
- Basilisk Hit (DEF 3)

Generated-artifact only; not OE runtime. Does not overwrite roc fused_push_080.
"""
from __future__ import annotations

import argparse
import gc
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
OUT_ROOT = ROOT / "artifacts/pose_picker_runs/fused_push_regression"
METHOD_ID = "fused_push_v24_pipeline"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_chain_space_surface_compare import (  # noqa: E402
    _prepare_choice_config,
    _sprite_dir,
    compose_clip_gif,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
)
from run_hybrid_method_quad import _build_isolated_def_choice  # noqa: E402
from run_roc_idle1_fused_push_080 import PUSH_OVERRIDES  # noqa: E402
from run_roc_idle1_start_move_end_root_weave import release_gpu  # noqa: E402

CLIPS: dict[str, dict[str, Any]] = {
    "behemoth_move": {
        "unit_sid": "h3_behemoth",
        "def_groups": (0,),
        "mesh": ROOT / "artifacts/meshy_downloads/h3_behemoth_smartrigged.glb",
        "title": "Behemoth Move (DEF 0)",
    },
    "crusader_attack_front": {
        "unit_sid": "h3_crusader",
        "def_groups": (12,),
        "mesh": ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
        "title": "Crusader AttackFront (DEF 12)",
    },
    "basilisk_hitted": {
        "unit_sid": "h3_basilisk",
        "def_groups": (3,),
        "mesh": ROOT / "artifacts/meshy_downloads/h3_basilisk_smartrigged_rigidized.glb",
        "title": "Basilisk Hit (DEF 3)",
    },
}

# Roc idle1 anatomy catalog — omit for other units; keep error_leverage search.
ROC_ANATOMY_KEYS = frozenset(
    {
        "search_bones",
        "include_unlisted_search_bones",
        "bone_limit_scale_overrides",
        "anatomy_groups_catalog_path",
        "anatomy_group_visit_order",
    }
)

GROUND_CLIP_TWEAKS = {
    "idle_prefix_frames": 0,
    "idle_suffix_frames": 0,
    "motion_exempt_idle_prefix": False,
    "joint_temporal_consensus_idle_end": True,
    # Roc anatomy catalog omitted — symmetry visit needs that path.
    "early_symmetry_enabled": False,
    "articulated_multi_bone_enabled": False,
}

# Explicit spill-avoidance lane (--memory-safe). Tighter than the batch default.
MEMORY_SAFE_OVERRIDES = {
    "joint_score_raster_batch": 512,
    "chroma_scale": 2,
    "profile_init_resolution": (192, 172),
    "articulated_iterations": 3,
    "articulated_funnel_broad_rounds": 1,
    "articulated_funnel_broad_probe_rungs": 2,
    "score_escape_mode": "worst_stack",
    "score_escape_max_rounds": 2,
    "score_escape_articulated_iterations": 4,
    "root_hypotheses": 32,
    "score_escape_worst_frame_count": 6,
}

# Raster/chroma placeholders. Batch default replaces these from mesh
# properties in kwargs_for_choice (fused_push_mesh_raster_budget).
# Explicit --memory-safe / --gpu-fed keep the constant tiers below.
BATCH_RASTER_DEFAULT = {
    "joint_score_raster_batch": 512,
    "chroma_scale": 2,
    "profile_init_resolution": (192, 172),
}
BATCH_RASTER_MEMORY_SAFE = {
    "joint_score_raster_batch": 512,
    "chroma_scale": 2,
    "profile_init_resolution": (192, 172),
}
BATCH_RASTER_GPU_FED = {
    "joint_score_raster_batch": 1024,
    "chroma_scale": 4,
    "profile_init_resolution": (192, 172),
}

# Batch rollout: same hybrid score mix, fewer redundant macro/escape passes.
# Transit clips (idle prefix) re-enable macro in kwargs_for_choice().
BATCH_PERF_OVERRIDES = {
    "articulated_iterations": 1,
    "articulated_funnel_broad_rounds": 1,
    "articulated_funnel_broad_probe_rungs": 2,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": True,
    "idle_fused_macro_enabled": False,
    "idle_fused_shared_transit_yaw_enabled": False,
    "idle_fused_reroot_transit_after_articulated": False,
    "idle_fused_reroot_all_transit": False,
    # Escape: worst_stack + lower threshold + fail-fast (see roc_gpu_cascade_experiment).
    # full_stack often burned minutes on rescue/root with keep_best reverts and +0 score.
    "score_escape_mode": "worst_stack",
    "score_escape_max_rounds": 1,
    "score_escape_threshold": 0.70,
    "score_escape_articulated_iterations": 3,
    "score_escape_fail_fast": True,
    "score_escape_root_held_abort": 3,
    # Idle-seeded non-idle clips already have a plausible pose; skip escape
    # coarse/broad that mostly re-searches the same basin.
    "score_escape_skip_coarse_broad_when_seeded": True,
    # Unseeded first clips that land far below threshold (mesh/sprite soft-miss)
    # waste minutes on coarse/broad for ~0 gain; skip when mean < 0.50.
    "score_escape_skip_coarse_broad_below_mean": 0.50,
    "root_hypotheses": 32,
    "live_preview": False,
    "exact_raster_enabled": True,
}

# High-throughput lane: opt-in (--gpu-fed). May spill to shared pool on 16 GB cards.
BATCH_GPU_FED_EXTRA = {
    "articulated_funnel_broad_probe_rungs": 2,
    "score_escape_articulated_iterations": 2,
    "joint_temporal_consensus_independent_passes": False,
    "articulated_funnel_worst_frame_keep_count": 4,
}


def filter_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.discard("config")
    allowed.discard("output_dir")
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError("bad kwargs: " + ", ".join(unknown))
    return {k: kwargs[k] for k in kwargs if k in allowed}


def regression_kwargs(
    *,
    full_pipeline: bool = False,
    batch: bool = False,
    memory_safe_batch: bool = False,
    gpu_fed_batch: bool = False,
) -> dict[str, Any]:
    base = {k: v for k, v in PUSH_OVERRIDES.items() if k not in ROC_ANATOMY_KEYS}
    base.update(GROUND_CLIP_TWEAKS)
    if full_pipeline:
        # Full v24-class — can exhaust dedicated VRAM and spill to shared pool.
        base["score_escape_skip_coarse_broad_when_seeded"] = False
        base["score_escape_skip_articulated_retry_when_seeded"] = False
        base["idle_fused_skip_macro_when_seeded"] = False
        base["idle_fused_skip_reroot_when_seeded"] = False
        base["root_skip_when_seeded"] = False
        base["articulated_skip_when_seeded"] = False
        print("WARNING: full fused_push pipeline — high VRAM; GPU lane must be empty", flush=True)
    elif batch:
        base.update(BATCH_PERF_OVERRIDES)
        if gpu_fed_batch:
            base.update(BATCH_RASTER_GPU_FED)
            base.update(BATCH_GPU_FED_EXTRA)
            lane = (
                "gpu-fed: joint_score_raster_batch=1024 chroma_scale=4 "
                "(opt-in; may spill on 16GB)"
            )
        elif memory_safe_batch:
            base.update(BATCH_RASTER_MEMORY_SAFE)
            lane = "memory-safe: joint_score_raster_batch=512 chroma_scale=2"
        else:
            base.update(BATCH_RASTER_DEFAULT)
            lane = "batch default: mesh-sized raster (see kwargs_for_choice)"
        print(
            f"batch {lane} artic=1 escape=1x worst_stack thresh=0.70 fail_fast no-post-reroot",
            flush=True,
        )
    else:
        base.update(MEMORY_SAFE_OVERRIDES)
        print(
            "memory-safe regression: joint_score_raster_batch=512 chroma_scale=2 "
            "escape_rounds=2 (use --full for v24-class budget)",
            flush=True,
        )
    if os.environ.get("FUSED_REGRESSION_FAST", "").strip().lower() in {"1", "true", "yes"}:
        from run_roc_idle1_fused_push_080 import FAST_PUSH_OVERRIDES

        base.update(FAST_PUSH_OVERRIDES)
        print("FUSED_REGRESSION_FAST=1: further reduced escape budget", flush=True)
    return filter_kwargs(base)


def fit_clip(label: str, *, out_root: Path, full_pipeline: bool = False) -> dict[str, Any]:
    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    spec = CLIPS[label]
    mesh = Path(spec["mesh"])
    if not mesh.is_file():
        raise FileNotFoundError(mesh)
    out = out_root / label
    arm_dir = out / METHOD_ID
    arm_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    choice = _build_isolated_def_choice(
        widgets,
        unit_sid=str(spec["unit_sid"]),
        def_groups=tuple(int(g) for g in spec["def_groups"]),
    )
    config = _prepare_choice_config(choice, mesh, NOTEBOOK)
    kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
    kwargs.update(regression_kwargs(full_pipeline=full_pipeline))
    kwargs["live_status_path"] = str(out / "live_status.json")
    print(
        f"fit {label} frames={len(config.frame_indices)} "
        f"joint_score_raster_batch={kwargs.get('joint_score_raster_batch')} "
        f"chroma_scale={kwargs.get('chroma_scale')} -> {arm_dir}",
        flush=True,
    )
    solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm_dir, **kwargs)
    gc.collect()
    elapsed = time.perf_counter() - started
    result_path = Path(solved.pose_result["clipResultPath"])
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    config_out = payload.get("config") or {}
    if str(config_out.get("score_mode")) != "geometry":
        raise RuntimeError(f"{label}: expected geometry score_mode, got {config_out.get('score_mode')}")
    gif = compose_clip_gif(
        clip_root=out,
        sprite_dir=_sprite_dir(choice),
        frame_count=len(config.frame_indices),
        arms=({"id": METHOD_ID},),
    )
    report = {
        "label": label,
        "title": spec["title"],
        "methodId": METHOD_ID,
        "gif": str(gif).replace("\\", "/"),
        "clipResult": str(result_path).replace("\\", "/"),
        "score": payload.get("score"),
        "frameScores": payload.get("frameScores"),
        "elapsedSec": round(elapsed, 1),
        "frameCount": len(config.frame_indices),
        "proof": "generated-artifact; fused_push regression; not OE runtime",
    }
    (out / "run_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clips",
        default=",".join(CLIPS),
        help=f"comma-separated labels from {sorted(CLIPS)}",
    )
    parser.add_argument(
        "--dest",
        default="memory_safe",
        help="subdir under fused_push_regression for this batch",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="v24-class full pipeline (high VRAM; do not run alongside other GPU jobs)",
    )
    args = parser.parse_args()
    full_pipeline = bool(args.full) or os.environ.get(
        "FUSED_REGRESSION_FULL", ""
    ).strip().lower() in {"1", "true", "yes"}
    wanted = [part.strip() for part in str(args.clips).split(",") if part.strip()]
    unknown = sorted(set(wanted) - set(CLIPS))
    if unknown:
        raise SystemExit(f"unknown clips: {unknown}; known={sorted(CLIPS)}")
    out_root = OUT_ROOT / str(args.dest)
    out_root.mkdir(parents=True, exist_ok=True)
    plan = {
        "methodId": METHOD_ID,
        "clips": wanted,
        "overrides": regression_kwargs(full_pipeline=full_pipeline),
        "fullPipeline": full_pipeline,
        "dest": str(out_root).replace("\\", "/"),
    }
    (out_root / "regression_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    reports: list[dict[str, Any]] = []
    batch_started = time.perf_counter()
    try:
        for label in wanted:
            reports.append(
                fit_clip(label, out_root=out_root, full_pipeline=full_pipeline)
            )
            _release_gpu_workspace()
            release_gpu()
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)
    summary = {
        "methodId": METHOD_ID,
        "dest": str(out_root).replace("\\", "/"),
        "elapsedSec": round(time.perf_counter() - batch_started, 1),
        "clips": reports,
    }
    (out_root / "regression_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
