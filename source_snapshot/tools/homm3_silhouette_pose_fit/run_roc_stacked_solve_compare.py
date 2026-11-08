#!/usr/bin/env python3
"""Compare stacked solving strategies on Roc idle_start_move_end.

Holds scoring + joint feasibility constant (unlocked from-rest base). Varies
only the solve strategy: small IK blobs, bold IK, deficit ordering, joint
probes, IK then joint refinement, and chain-space surface search.

Writes under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_solve_compare/``.
Composes a 2×3 MP4 grid (sprite + five methods). Experiment lane only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs" / "h3_roc" / "idle_start_move_end" / "stacked_solve_compare"
BASELINE_IK = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_small_ik_v1"
)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees  # noqa: E402
from roc_stacked_solve_common import (  # noqa: E402
    ANATOMY_KWARGS,
    CLIP,
    FORBIDDEN_WRITE_PARTS,
    IK_MISS_BASE,
    JOINT_PROBE_BASE,
    MESH,
    NOTEBOOK,
    STACKED_UNLOCK_BASE,
    UNIT,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)
from run_fused_push_batch_all_units import (  # noqa: E402
    _apply_choice_camera,
    _build_config,
    kwargs_for_choice,
)
from run_fused_push_regression_triplet import filter_kwargs  # noqa: E402
from run_roc_stacked_small_pass import refuse_imported_pose_seed  # noqa: E402

COMPARE_ID = "stacked_solve_compare"


def assert_compare_write_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed = (ROOT / "artifacts" / "pose_picker_runs").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(
            f"{COMPARE_ID} may only write under {allowed}; got {resolved}"
        ) from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"{COMPARE_ID} must not write live payload paths: {resolved}")
    if COMPARE_ID not in resolved.parts:
        raise RuntimeError(
            f"{COMPARE_ID} writes must include {COMPARE_ID} in the path; got {resolved}"
        )
    return resolved

TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "ik_small",
        "label": "ik ±2.5°",
        "reason": "Greedy silhouette_miss blob IK, small fixed steps (baseline).",
        "overrides": {
            **IK_MISS_BASE,
        },
        "reuse_from": BASELINE_IK,
    },
    {
        "id": "ik_bold",
        "label": "ik ±8°",
        "reason": "Same IK attribution, larger steps and more outer passes.",
        "overrides": {
            **IK_MISS_BASE,
            "ik_max_step_deg": 8.0,
            "ik_proximal_max_step_deg": 8.0,
            "ik_iterations": 8,
            "ik_blob_search_rounds": 6,
            "ik_step_scale_mode": "displacement",
        },
    },
    {
        "id": "ik_deficit",
        "label": "ik deficit",
        "reason": "Worst-frame-first order + deficit-scaled step size.",
        "overrides": {
            **IK_MISS_BASE,
            "ik_frame_order_mode": "deficit",
            "ik_step_scale_mode": "deficit",
            "ik_iterations": 8,
        },
    },
    {
        "id": "joint_probe",
        "label": "joint ±2.5°",
        "reason": "One-joint articulated probes only (no IK init).",
        "overrides": {
            **JOINT_PROBE_BASE,
        },
    },
    {
        "id": "ik_then_joint",
        "label": "ik+joint",
        "reason": "Silhouette_miss IK then four articulated refinement rounds.",
        "overrides": {
            **IK_MISS_BASE,
            "articulated_iterations": 4,
            "joint_step_deg": 2.5,
            "fine_joint_step_deg": 2.5,
            "joint_pass_limit_deg": 10.0,
            "joint_probe_rungs": 4,
        },
    },
    {
        "id": "chain_space",
        "label": "chain space",
        "reason": "Chain-space gradient surface search (no IK).",
        "overrides": {
            **JOINT_PROBE_BASE,
            "articulated_iterations": 0,
            "chain_space_enabled": True,
            "chain_space_iterations": 4,
            "chain_space_step_degs": (4.0, 8.0, 12.0),
        },
    },
)


def trial_dir(out_root: Path, trial_id: str) -> Path:
    return assert_compare_write_path(out_root / trial_id)


def trial_complete(dest: Path) -> bool:
    clip = dest / "gpu_clip_result.json"
    rgb = dest / "solved_rgb" / "00.png"
    return clip.is_file() and rgb.is_file()


def load_score(dest: Path) -> float | None:
    clip = dest / "gpu_clip_result.json"
    if not clip.is_file():
        return None
    return float(json.loads(clip.read_text(encoding="utf-8")).get("score") or 0)


def sprite_dir_for_choice(choice) -> Path:
    pilot = Path(choice.pilot_dir)
    return pilot / f"frames_def12_nn_{CLIP}_shadow_culled"


def build_fit_context():
    import roc_semantic_hybrid_widgets as widgets
    from gpu_cascade_delivery import select_unit_delivery_choices
    from run_crusader_full_animation_set import _literal_config_kwargs

    choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), UNIT)
    choice = next((item for item in choices if str(item.animation_name) == CLIP), None)
    if choice is None:
        raise RuntimeError(f"no delivery choice for {UNIT} {CLIP}")
    notebook_kwargs = _literal_config_kwargs(NOTEBOOK, require_dino=False)
    notebook_gpu_fit_kwargs(NOTEBOOK)
    config = _build_config(choice, MESH, notebook_kwargs, NOTEBOOK, use_cache=False)
    gpu_kwargs = kwargs_for_choice(choice, full_pipeline=False, batch=True, mesh=MESH)
    gpu_kwargs.update(ANATOMY_KWARGS)
    gpu_kwargs.update(STACKED_UNLOCK_BASE)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, MESH)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config = prepare_gpu_targets(config)
    return choice, config, gpu_kwargs


def reuse_baseline(dest: Path, source: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("gpu_clip_result.json", "fit_report.json"):
        src = source / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    solved_src = source / "solved_rgb"
    solved_dest = dest / "solved_rgb"
    if solved_src.is_dir():
        if solved_dest.exists():
            shutil.rmtree(solved_dest)
        shutil.copytree(solved_src, solved_dest)


def compose_compare_mp4(
    out_root: Path,
    sprite_dir: Path,
    panels: list[tuple[str, Path]],
    *,
    frame_count: int,
) -> Path:
    from compose_method_compare_mp4 import main as compose_main

    mp4 = out_root / "stacked_solve_compare_grid.mp4"
    argv = [
        "--out",
        str(mp4),
        "--cols",
        "3",
        "--cell-w",
        "220",
        "--cell-h",
        "260",
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
        sys.argv = ["compose_method_compare_mp4.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compare MP4 compose failed")
    return mp4


def main() -> int:
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--trial", type=str, default="", help="Run one trial id only")
    args = parser.parse_args()

    out_root = assert_compare_write_path(Path(args.out).resolve())
    out_root.mkdir(parents=True, exist_ok=True)

    selected = TRIALS
    if args.trial:
        selected = tuple(t for t in TRIALS if t["id"] == args.trial)
        if not selected:
            raise RuntimeError(f"unknown trial: {args.trial}")

    plan = {
        "proof": "generated-artifact; solving compare — not OE battle",
        "clip": CLIP,
        "heldConstant": "unlocked from-rest scoring + feasibility",
        "trials": [
            {"id": t["id"], "label": t["label"], "reason": t["reason"]} for t in selected
        ],
    }
    (out_root / "compare_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )

    choice = None
    frame_count = 30

    if not args.compose_only:
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        choice, config, base_kwargs = build_fit_context()
        lock_path = global_cascade_batch_lock_path(ROOT)
        acquire_cascade_batch_lock(lock_path)
        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        try:
            for trial in selected:
                dest = trial_dir(out_root, str(trial["id"]))
                reuse = trial.get("reuse_from")
                if reuse and Path(reuse).is_dir() and trial_complete(Path(reuse)):
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
                    if not trial_complete(dest):
                        print(f"reuse baseline {trial['id']} <- {reuse}", flush=True)
                        reuse_baseline(dest, Path(reuse))
                    score = load_score(dest)
                    results.append(
                        {
                            "id": trial["id"],
                            "label": trial["label"],
                            "score": score,
                            "reused": True,
                            "skipped": False,
                        }
                    )
                    continue
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
                kwargs = dict(base_kwargs)
                kwargs.update(dict(trial.get("overrides") or {}))
                kwargs["live_status_path"] = str(dest / "live_status.json")
                kwargs = refuse_imported_pose_seed(kwargs)
                kwargs = filter_kwargs(kwargs)
                if kwargs.get("initial_poses"):
                    raise RuntimeError(f"{trial['id']} must start from rest")
                dest.mkdir(parents=True, exist_ok=True)
                print(
                    json.dumps(
                        {
                            "trial": trial["id"],
                            "label": trial["label"],
                            "ik_enabled": kwargs.get("ik_enabled"),
                            "articulated_iterations": kwargs.get("articulated_iterations"),
                            "chain_space_enabled": kwargs.get("chain_space_enabled"),
                        },
                        indent=2,
                    ),
                    flush=True,
                )
                run_gpu_depth_fit_from_hybrid_config(
                    config,
                    output_dir=dest,
                    **dict(kwargs),
                )
                result_path = dest / "gpu_clip_result.json"
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                require_pose_units_degrees(payload, source=str(result_path))
                if any(part in FORBIDDEN_WRITE_PARTS for part in result_path.parts):
                    raise RuntimeError(f"trial wrote live fused-push: {result_path}")
                frame_count = len(payload.get("frameIndices") or [])
                score = float(payload.get("score") or 0)
                results.append(
                    {
                        "id": trial["id"],
                        "label": trial["label"],
                        "score": score,
                        "skipped": False,
                    }
                )
                print(f"done {trial['id']} score={score:.4f}", flush=True)
        finally:
            _release_gpu_workspace()
            release_cascade_batch_lock(lock_path)

        report = {
            "elapsedSec": round(time.perf_counter() - started, 1),
            "results": results,
        }
        (out_root / "compare_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    if choice is None:
        choice, _, _ = build_fit_context()
    sprite_dir = sprite_dir_for_choice(choice)

    panels: list[tuple[str, Path]] = []
    for trial in TRIALS:
        dest = trial_dir(out_root, str(trial["id"]))
        if not trial_complete(dest):
            continue
        score = load_score(dest)
        label = str(trial["label"])
        if score is not None:
            label = f"{label} {score:.3f}"
        panels.append((label, dest / "solved_rgb"))

    if not panels:
        raise RuntimeError("no completed trials to compose")

    mp4 = compose_compare_mp4(out_root, sprite_dir, panels, frame_count=frame_count)
    print(f"composed {mp4} panels={len(panels)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
