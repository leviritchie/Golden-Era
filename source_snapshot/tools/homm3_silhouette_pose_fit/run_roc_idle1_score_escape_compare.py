#!/usr/bin/env python3
"""Compare score-gated escape passes on roc idle1+start+move+end.

Foundation: joint_adaptive_step + gradient_magnitude + woven root (same as
idle1 weave runner). Each trial enables ``score_escape_mode`` when mean hybrid
score stays below ``score_escape_threshold`` (default 0.80).

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/score_escape_compare"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
SPRITE_STAGED = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end"
    / "sprite_idle1_start_move_end"
)

sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_roc_idle1_start_move_end_root_weave import (
    idle1_start_move_end_config,
    release_gpu,
    shared_kwargs,
    stage_sequential_pngs,
    KEEP_FRAME_INDICES,
)

TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "adaptive_baseline",
        "label": "adaptive",
        "reason": "Adaptive articulated walk only; no score escape.",
        "overrides": {"score_escape_enabled": False},
    },
    {
        "id": "escape_articulated_retry",
        "label": "retry",
        "reason": "Second full adaptive walk when mean < 0.80.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "articulated_retry",
        },
    },
    {
        "id": "escape_branch_rescue",
        "label": "rescue",
        "reason": "Parent-child joint combos even with adaptive step.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "branch_rescue",
        },
    },
    {
        "id": "escape_coarse_push",
        "label": "coarse",
        "reason": "Retry adaptive walk with coarse threshold 0.85 (more 15° rungs).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "coarse_push",
            "score_escape_coarse_push_coarse": 0.85,
        },
    },
    {
        "id": "escape_no_consensus",
        "label": "no_cons",
        "reason": "Retry adaptive walk without temporal consensus smoothing.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "no_consensus_retry",
        },
    },
    {
        "id": "escape_root_burst",
        "label": "root",
        "reason": "Wide keep-gated root refit (12° window) on weak mean score.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "root_burst",
        },
    },
    {
        "id": "escape_sa_nudge",
        "label": "sa_nudge",
        "reason": "Small SA perturbation from current pose (2 restarts, 25°).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "sa_nudge",
        },
    },
    {
        "id": "escape_chain_space",
        "label": "chain",
        "reason": "Chain-space gradient burst when mean stays under threshold.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "chain_space",
        },
    },
    {
        "id": "escape_combo",
        "label": "combo",
        "reason": "Adaptive retry then branch rescue when still < 0.80.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "combo",
        },
    },
)


def trial_dir(out_root: Path, trial_id: str) -> Path:
    return out_root / trial_id


def trial_complete(dest: Path) -> bool:
    clip = dest / "gpu_clip_result.json"
    rgb = dest / "solved_rgb" / f"{int(KEEP_FRAME_INDICES[0]):02d}.png"
    return clip.is_file() and rgb.is_file()


def load_score(dest: Path) -> float | None:
    clip = dest / "gpu_clip_result.json"
    if not clip.is_file():
        return None
    return float(json.loads(clip.read_text(encoding="utf-8")).get("score") or 0)


def compose_grid(
    out_root: Path,
    sprite_dir: Path,
    frame_count: int,
    panels: list[tuple[str, Path]],
    *,
    gif_name: str = "idle1_score_escape_compare.gif",
) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = out_root / gif_name
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
        str(frame_count),
        "--panel",
        "sprite",
        str(sprite_dir),
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
        raise RuntimeError("compare GIF compose failed")
    return gif


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--gif-name",
        default="idle1_score_escape_compare.gif",
        help="Compare GIF filename under --out",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--trial", type=str, default="", help="Run one trial id only")
    args = parser.parse_args()

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    frame_count = len(KEEP_FRAME_INDICES)

    if not SPRITE_STAGED.is_dir():
        raise FileNotFoundError(f"staged sprites missing: {SPRITE_STAGED}")

    selected = TRIALS
    if args.trial:
        selected = tuple(t for t in TRIALS if t["id"] == args.trial)
        if not selected:
            raise RuntimeError(f"unknown trial: {args.trial}")

    plan = {
        "proof": "generated experiment candidate; not delivery validated",
        "clip": "idle1_start_move_end",
        "scoreEscapeThreshold": 0.80,
        "foundation": "joint_adaptive_step + gradient_magnitude + root weave",
        "trials": [
            {"id": t["id"], "label": t["label"], "reason": t["reason"]} for t in selected
        ],
    }
    (out_root / "compare_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )

    if not args.compose_only:
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        config = idle1_start_move_end_config(MESH, NOTEBOOK)
        base_kwargs = shared_kwargs()
        lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        try:
            for trial in selected:
                dest = trial_dir(out_root, str(trial["id"]))
                if args.skip_existing and trial_complete(dest):
                    score = load_score(dest)
                    print(f"skip existing {trial['id']} score={score}", flush=True)
                    results.append(
                        {
                            "id": trial["id"],
                            "label": trial["label"],
                            "score": score,
                            "skipped": True,
                        }
                    )
                    continue
                overrides = dict(trial.get("overrides") or {})
                kwargs = {**base_kwargs, **overrides}
                print(f"fit {trial['id']} -> {dest}", flush=True)
                dest.mkdir(parents=True, exist_ok=True)
                solved = run_gpu_depth_fit_from_hybrid_config(
                    config,
                    output_dir=dest,
                    **kwargs,
                )
                payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
                score = float(payload.get("score") or 0)
                escape = payload.get("scoreEscape") or []
                results.append(
                    {
                        "id": trial["id"],
                        "label": trial["label"],
                        "score": score,
                        "scoreEscape": escape,
                        "skipped": False,
                    }
                )
                print(f"done {trial['id']} score={score:.4f}", flush=True)
        finally:
            release_gpu()
            release_cascade_batch_lock(lock)

        report = {
            "elapsedSec": round(time.perf_counter() - started, 1),
            "results": results,
        }
        (out_root / "score_escape_compare_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    panels: list[tuple[str, Path]] = []
    for trial in TRIALS:
        dest = trial_dir(out_root, str(trial["id"]))
        if not trial_complete(dest):
            continue
        score = load_score(dest)
        label = str(trial["label"])
        if score is not None:
            label = f"{label} {score:.3f}"
        seq = dest / "solved_rgb_sequential"
        stage_sequential_pngs(dest / "solved_rgb", seq, KEEP_FRAME_INDICES)
        panels.append((label, seq))

    if not panels:
        raise RuntimeError("no completed trials to compose")

    gif = compose_grid(
        out_root, SPRITE_STAGED, frame_count, panels, gif_name=str(args.gif_name)
    )
    print(f"composed {gif} panels={len(panels)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
