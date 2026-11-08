#!/usr/bin/env python3
"""Fit angel idle_start_move_end under DINOv3 keep-score normalizations.

Adaptive joint step still lerps 2.5°..15° from a 0.45/0.80 keep band.
DINOv3 qualities sit near 1.0, so ``raw`` treats every frame as fine.
The other modes expand that band. Shared fit knobs match the notebook
dinov3 articulated ablation: one articulated walk, no root-search, no
base/mid/fine/rescue/physics. Not a CURRENT_CASCADE_KEEP delivery.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
DEFAULT_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end/dinov3_score_norm_compare"
)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from roc_gpu_cascade_experiment import JOINT_STEP_SCORE_NORMS  # noqa: E402
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

LABELS = {
    "raw": "raw",
    "clip_minmax": "minmax",
    "logit_minmax": "logit",
    "rank": "rank",
    "robust_z": "robust_z",
}

SHARED_OVERRIDES: dict[str, Any] = {
    "score_mode": "dinov3_dense",
    "joint_adaptive_step_enabled": True,
    "root_search_enabled": False,
    "sa_enabled": False,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": False,
    "fine_iterations": 0,
    "articulated_iterations": 1,
    "physics_smooth_enabled": False,
    "live_preview": False,
    "gradient_ladder_enabled": False,
    "ik_enabled": False,
}


def _trial_dir(out_root: Path, mode: str) -> Path:
    return Path(out_root) / str(mode)


def _result_complete(out_dir: Path, mode: str) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb" / "00.png"
    stamp = out_dir / "norm_trial.json"
    if not clip.is_file() or not rgb.is_file() or not stamp.is_file():
        return False
    stamp_payload = json.loads(stamp.read_text(encoding="utf-8"))
    if str(stamp_payload.get("mode") or "") != str(mode):
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    return str(config.get("joint_step_score_norm") or "") == str(mode)


def _head_magnitude_deg(poses: Mapping[Any, Mapping[str, Any]], bone: str) -> list[float]:
    out: list[float] = []
    for index in range(len(poses)):
        pose = poses.get(str(index)) or poses.get(index) or {}
        angles = pose.get(bone) or {"x": 0.0, "y": 0.0, "z": 0.0}
        mag = math.sqrt(
            float(angles.get("x") or 0.0) ** 2
            + float(angles.get("y") or 0.0) ** 2
            + float(angles.get("z") or 0.0) ** 2
        )
        out.append(math.degrees(mag))
    return out


def compose_compare_gif(*, out_root: Path, sprite_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = Path(out_root) / "angel_move_dinov3_score_norm_compare.gif"
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
    for mode in JOINT_STEP_SCORE_NORMS:
        argv.extend(["--panel", LABELS[mode], str(_trial_dir(out_root, mode) / "solved_rgb")])
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
    gpu_kwargs = _filter_fit_kwargs(_notebook_gpu_kwargs(args.notebook))
    gpu_kwargs.update(SHARED_OVERRIDES)

    plan = {
        "unit": choice.unit_sid,
        "animation": choice.animation_name,
        "frames": len(choice.frame_indices),
        "modes": list(JOINT_STEP_SCORE_NORMS),
        "overrides": SHARED_OVERRIDES,
        "mesh": str(mesh).replace("\\", "/"),
        "out": str(out_root).replace("\\", "/"),
    }
    (out_root / "compare_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
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

    summary: list[dict[str, Any]] = []
    for mode in JOINT_STEP_SCORE_NORMS:
        dest = _trial_dir(out_root, mode)
        if args.skip_existing and _result_complete(dest, mode):
            print(f"reuse {mode}: {dest}", flush=True)
        else:
            started = time.perf_counter()
            print(f"fit {mode} frames={len(config.frame_indices)} out={dest}", flush=True)
            try:
                solved = run_gpu_depth_fit_from_hybrid_config(
                    config,
                    output_dir=dest,
                    **{**gpu_kwargs, "joint_step_score_norm": mode},
                )
                clip_path = Path(solved.pose_result["clipResultPath"])
                payload = json.loads(clip_path.read_text(encoding="utf-8"))
                recorded = str((payload.get("config") or {}).get("joint_step_score_norm") or "")
                if recorded != mode:
                    raise RuntimeError(
                        f"{dest} recorded joint_step_score_norm={recorded!r}, not {mode!r}"
                    )
                elapsed = time.perf_counter() - started
                (dest / "norm_trial.json").write_text(
                    json.dumps({"mode": mode, "elapsed": elapsed}, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"fitted {mode} score={payload.get('score')} elapsed={elapsed:.1f}s",
                    flush=True,
                )
            finally:
                _release_gpu()
        payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
        poses = payload.get("poses") or {}
        head = _head_magnitude_deg(poses, "Bone_018")
        summary.append(
            {
                "mode": mode,
                "score": payload.get("score"),
                "evalCount": payload.get("evaluationCount"),
                "head018MaxDeg": max(head) if head else None,
                "head018MeanDeg": (sum(head) / len(head)) if head else None,
            }
        )

    (out_root / "compare_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    gif = compose_compare_gif(
        out_root=out_root,
        sprite_dir=sprite_dir,
        frame_count=len(config.frame_indices),
    )
    print(f"composed {gif}", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
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
