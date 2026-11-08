#!/usr/bin/env python3
"""Run rich multi-axis influence-weighted shape keys on roc idle1 transit.

Uses profile camera initialization and collision scoring (same lane as
alternate_deform_compare). Outputs to alternate_deform_compare/shape_keys_rich/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/alternate_deform_compare"
GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

sys.path.insert(0, str(TOOL))

from gpu_alternate_deform import run_alternate_deform_method
from run_roc_idle1_alternate_deform_compare import build_experiment, COMPARE_OVERRIDES
from run_roc_idle1_start_move_end_root_weave import KEEP_FRAME_INDICES, release_gpu


def main() -> int:
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )

    dest = OUT / "shape_keys_rich"
    dest.mkdir(parents=True, exist_ok=True)
    plan = {
        "method": "shape_keys_rich",
        "shape_keys_mode": "rich",
        "max_rounds": 6,
        "probe_deg": 18.0,
        "collision_enabled": True,
        "collision_weight": 0.35,
        "profile_init_enabled": True,
        "overrides": COMPARE_OVERRIDES,
    }
    (dest / "run_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        experiment, hybrid, _sprite = build_experiment()
        try:
            print(f"shape_keys_rich -> {dest}", flush=True)
            report = run_alternate_deform_method(
                experiment,
                method="shape_keys_rich",
                output_dir=dest,
                groups_catalog_path=GROUPS,
                max_rounds=6,
                probe_deg=18.0,
                lattice_grid=2,
            )
        finally:
            experiment.release_cuda()
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)

    collision = report.get("collisionError") or []
    collision_mean = sum(collision) / max(1, len(KEEP_FRAME_INDICES))
    summary = {
        "method": "shape_keys_rich",
        "score": float(report["score"]),
        "collision_mean": collision_mean,
        "shapeKeyBasisCount": report.get("shapeKeyBasisCount"),
        "elapsedSec": round(time.perf_counter() - started, 1),
        "outputDir": str(dest),
        "frameScores": report.get("frameScores"),
        "perFrameGreedyScores": report.get("perFrameGreedyScores"),
        "hybridConfig": {
            "animation_name": getattr(hybrid, "animation_name", None),
            "frame_indices": list(KEEP_FRAME_INDICES),
        },
    }
    (dest / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
