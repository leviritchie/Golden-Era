#!/usr/bin/env python3
"""Fit angel move under several cascade knob/weight hypotheses and compose one grid GIF.

Notebook GPU knobs are reused except:
- discrete mid / rescue / fine stages are ON for every trial (the previous
  bone-order GIF left them off, so 15° SA+base was the whole pose)
- ``sa_seed=0`` so SA is not a second hidden variable
- one named override set per trial (the compared variable)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
DEFAULT_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end/cascade_knob_compare"
)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_angel_bone_order_compare import (  # noqa: E402
    ANGEL_MESH,
    NOTEBOOK,
    _filter_fit_kwargs,
    _notebook_gpu_kwargs,
    _release_gpu,
    _select_angel_move,
)
from run_crusader_full_animation_set import _literal_config_kwargs, _notebook_config  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    prepare_gpu_targets,
)

# Shared so every panel actually runs the discrete walk + polish. The notebook
# currently has these off for an SA-only preview.
SHARED_OVERRIDES: dict[str, Any] = {
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": True,
    "fine_iterations": 2,
    "sa_seed": 0,
    "live_preview": False,
    "physics_smooth_enabled": True,
}

# Eight trials → sprite + 8 panels, same 3×3 wrap as the bone-order GIF.
TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "full_disc",
        "label": "full_disc",
        "reason": (
            "Control: notebook weights, but mid/rescue/fine on. "
            "The last GIF never ran those polish stages."
        ),
        "overrides": {},
    },
    {
        "id": "no_sa",
        "label": "no_sa",
        "reason": (
            "SA proposes 45° multi-bone jumps with collision weight 0, then "
            "base inherits splits/tunic melt. Discrete walk only."
        ),
        "overrides": {"sa_enabled": False},
    },
    {
        "id": "sa_safe",
        "label": "sa_safe",
        "reason": (
            "Keep SA for basin search, but score it with the normal collision "
            "weight and a smaller perturbation so exploratory poses cannot "
            "be legal pretzels."
        ),
        "overrides": {
            "sa_collision_weight": 0.35,
            "sa_perturbation_scale_deg": 25.0,
        },
    },
    {
        "id": "strict_col",
        "label": "strict_col",
        "reason": (
            "Walk frames tore the skirt and put limbs through the torso. "
            "Raise collision cost and shrink the slack that lets extra "
            "contact through."
        ),
        "overrides": {
            "collision_weight": 0.70,
            "joint_collision_positive_abs_slack": 0.03,
        },
    },
    {
        "id": "unique",
        "label": "unique",
        "reason": (
            "Wings and the trailing leg disappear into the tunic blob. "
            "Raise unique-remainder credit so leftover pixels can pick "
            "the distal bone."
        ),
        "overrides": {"joint_unique_gain_weight": 0.80},
    },
    {
        "id": "sil_first",
        "label": "sil_first",
        "reason": (
            "Notebook mix is ~66% depth / 33% chroma / 0.7% occupancy. "
            "A Lab-better head tilt can beat a silhouette-correct walk. "
            "Raise occupancy, cut chroma."
        ),
        "overrides": {
            "depth_weight": 0.70,
            "silhouette_weight": 0.25,
            "chroma_weight": 0.10,
        },
    },
    {
        "id": "smooth",
        "label": "smooth",
        "reason": (
            "Neighbor consensus still pops when the sprite cost of a copy "
            "exceeds 0.01. Larger copy budget plus a stiffer physics "
            "post-pass on one-frame spikes."
        ),
        "overrides": {
            "joint_temporal_consensus_tie_bonus": 0.02,
            "physics_smooth_stiffness": 360.0,
            "physics_smooth_outlier_min_deg": 6.0,
        },
    },
    {
        "id": "all_bones",
        "label": "all_bones",
        "reason": (
            "skip_tiny drops short wing/feather bones from the discrete walk. "
            "Search every skinned bone so fold/spread can move those tips."
        ),
        "overrides": {"skip_tiny_bones": False},
    },
)


def _trial_dir(out_root: Path, trial_id: str) -> Path:
    return Path(out_root) / str(trial_id)


def _merged_overrides(trial: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(SHARED_OVERRIDES)
    merged.update(dict(trial["overrides"]))
    return merged


def _result_complete(out_dir: Path, trial: Mapping[str, Any]) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb" / "00.png"
    stamp = out_dir / "knob_trial.json"
    if not clip.is_file() or not rgb.is_file() or not stamp.is_file():
        return False
    stamp_payload = json.loads(stamp.read_text(encoding="utf-8"))
    if str(stamp_payload.get("id") or "") != str(trial["id"]):
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    expected = _merged_overrides(trial)
    expected.pop("live_preview", None)
    for key, value in expected.items():
        recorded = config.get(key)
        if recorded != value:
            return False
    return True


def compose_compare_gif(*, out_root: Path, sprite_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = Path(out_root) / "angel_move_cascade_knob_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        "3",
        "--cell-w",
        "260",
        "--cell-h",
        "300",
        "--hold",
        "2",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
    ]
    for trial in TRIALS:
        argv.extend(
            ["--panel", str(trial["label"]), str(_trial_dir(out_root, trial["id"]) / "solved_rgb")]
        )
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compare GIF compose failed")
    return gif


def _main_locked() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=ANGEL_MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mesh = Path(args.mesh).resolve()
    if mesh != ANGEL_MESH.resolve():
        raise RuntimeError(f"angel compare is locked to {ANGEL_MESH}")
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import RocHybridConfig

    choice = _select_angel_move(widgets)
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
    gpu_base = _filter_fit_kwargs(_notebook_gpu_kwargs(args.notebook))

    plan = {
        "unit": choice.unit_sid,
        "animation": choice.animation_name,
        "groups": list(choice.def_lab_groups),
        "counts": list(choice.def_expected_counts),
        "frames": len(choice.frame_indices),
        "sharedOverrides": SHARED_OVERRIDES,
        "trials": [
            {
                "id": trial["id"],
                "label": trial["label"],
                "reason": trial["reason"],
                "overrides": _merged_overrides(trial),
            }
            for trial in TRIALS
        ],
        "mesh": str(mesh).replace("\\", "/"),
        "out": str(out_root).replace("\\", "/"),
        "proof": (
            "generated artifact validated — knob-compare preview GIF; "
            "not OE runtime proven"
        ),
    }
    (out_root / "compare_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0

    sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{choice.animation_name}_shadow_culled"
    if args.compose_only:
        gif = compose_compare_gif(
            out_root=out_root,
            sprite_dir=sprite_dir,
            frame_count=sum(int(count) for count in choice.def_expected_counts),
        )
        print(f"composed {gif}", flush=True)
        return 0

    config = _notebook_config(RocHybridConfig, notebook_kwargs, notebook=args.notebook)
    overrides = _choice_overrides(choice, mesh)
    report_path = overrides.get("meshy_rigidization_report")
    if report_path is not None:
        report_payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        report_output = Path(str(report_payload.get("output") or "")).resolve()
        if report_output != mesh:
            overrides["meshy_rigidization_report"] = None
            overrides["require_meshy_rigidization"] = False
    config = replace(config, **overrides)
    config = prepare_gpu_targets(config)
    expected_frames = sum(int(count) for count in choice.def_expected_counts)
    if len(config.frame_indices) != expected_frames:
        raise RuntimeError(
            f"angel move materialized {len(config.frame_indices)} frames, "
            f"expected {expected_frames}"
        )

    for trial in TRIALS:
        dest = _trial_dir(out_root, trial["id"])
        merged = _merged_overrides(trial)
        if args.skip_existing and _result_complete(dest, trial):
            print(f"reuse {trial['id']}: {dest}", flush=True)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "knob_trial.json").write_text(
            json.dumps(
                {
                    "id": trial["id"],
                    "label": trial["label"],
                    "reason": trial["reason"],
                    "overrides": merged,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        started = time.perf_counter()
        print(f"fit {trial['id']} frames={len(config.frame_indices)} out={dest}", flush=True)
        try:
            solved = run_gpu_depth_fit_from_hybrid_config(
                config,
                output_dir=dest,
                **{**gpu_base, **merged},
            )
            payload = json.loads(Path(solved.pose_result["clipResultPath"]).read_text(encoding="utf-8"))
            recorded = payload.get("config")
            if not isinstance(recorded, Mapping):
                raise RuntimeError(f"{dest} clip result is missing config")
            check = dict(merged)
            check.pop("live_preview", None)
            mismatches = {
                key: {"expected": value, "recorded": recorded.get(key)}
                for key, value in check.items()
                if recorded.get(key) != value
            }
            if mismatches:
                raise RuntimeError(
                    f"{dest} recorded config mismatches {trial['id']}: {mismatches}"
                )
            print(
                f"fitted {trial['id']} score={payload.get('score')} "
                f"elapsed={time.perf_counter() - started:.1f}s",
                flush=True,
            )
        finally:
            _release_gpu()

    gif = compose_compare_gif(
        out_root=out_root,
        sprite_dir=sprite_dir,
        frame_count=len(config.frame_indices),
    )
    print(f"composed {gif}", flush=True)
    return 0


def main() -> int:
    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    try:
        return _main_locked()
    finally:
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
