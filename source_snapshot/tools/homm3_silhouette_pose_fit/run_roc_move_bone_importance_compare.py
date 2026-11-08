#!/usr/bin/env python3
"""Roc move: compare animation-derived bone-importance rankings in one grid.

Shared motion-led geometry authority. Compared variable is bone_order_mode
on a one-pass articulated walk (chain-space off):

- dependency — topology baseline
- error_driven — silhouette error x skin influence
- gradient_magnitude — d(score)/d(bone)
- expected_gain — trial-step keep delta
- temporal_disagreement — frame-to-frame disagreement
- screen_space_leverage — screen motion a joint can cause
- error_leverage — occupancy leftover × screen joint reach

Generated-artifact only; not OE runtime.
"""

from __future__ import annotations

import argparse
import gc
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
DEFAULT_OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/move/bone_importance_compare"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_bone_order import CASCADE_BONE_ORDER_MODES  # noqa: E402
from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)

COMPARE_MODES = tuple(mode for mode in CASCADE_BONE_ORDER_MODES if mode != "asset")

PANEL_LABELS = {
    "dependency": "dependency",
    "error_driven": "error",
    "gradient_magnitude": "grad",
    "expected_gain": "exp_gain",
    "temporal_disagreement": "temporal",
    "screen_space_leverage": "leverage",
    "error_leverage": "err+lev",
}

GEOMETRY_AUTHORITY = {
    "score_mode": "geometry",
    "motion_weight": 1.00,
    "depth_weight": 0.25,
    "silhouette_weight": 0.20,
    "chroma_weight": 0.20,
    "collision_enabled": True,
    "collision_weight": 0.35,
}


def _mode_dir(out_root: Path, mode: str) -> Path:
    return Path(out_root) / str(mode)


def _result_complete(out_dir: Path, mode: str) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb"
    if not clip.is_file() or not rgb.is_dir() or not any(rgb.glob("*.png")):
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    recorded = str(config.get("bone_order_mode") or config.get("boneOrderMode") or "")
    return recorded == str(mode)


def _release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _filter_fit_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.discard("config")
    allowed.discard("output_dir")
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError("GPU fit kwargs are not adapter parameters: " + ", ".join(unknown))
    return {name: kwargs[name] for name in kwargs if name in allowed}


def compose_compare_gif(*, out_root: Path, sprite_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = Path(out_root) / "roc_move_bone_importance_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        "4",
        "--cell-w",
        "220",
        "--cell-h",
        "260",
        "--hold",
        "2",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
    ]
    for mode in COMPARE_MODES:
        argv.extend(
            ["--panel", PANEL_LABELS[mode], str(_mode_dir(out_root, mode) / "solved_rgb")]
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


def _shared_kwargs(notebook: Path) -> dict[str, Any]:
    from run_crusader_gpu_cascade_animation_set import notebook_gpu_fit_kwargs

    kwargs = notebook_gpu_fit_kwargs(notebook)
    kwargs.update(
        {
            **GEOMETRY_AUTHORITY,
            "sa_enabled": False,
            "gradient_ladder_enabled": False,
            "ik_enabled": False,
            "physics_smooth_enabled": False,
            "joint_temporal_consensus_enabled": True,
            "sprite_aligned_motion_keep_enabled": True,
            "sprite_aligned_motion_keep_min_improvement": 0.01,
            "live_preview": False,
            "chain_space_enabled": False,
            "articulated_iterations": 1,
            "fine_iterations": 0,
            "base_pose_enabled": False,
            "mid_pose_enabled": False,
            "branch_rescue_enabled": False,
            "skip_tiny_bones": False,
            "root_search_enabled": False,
            "root_rotation_defer_camera_up": False,
        }
    )
    return _filter_fit_kwargs(kwargs)


def _load_clip_payload(dest: Path, solved) -> dict[str, Any]:
    pose_result = (
        getattr(solved, "pose_result", None)
        or getattr(solved, "clip_result", None)
        or {}
    )
    if not isinstance(pose_result, dict):
        pose_result = {}
    result_path = Path(
        pose_result.get("clipResultPath")
        or pose_result.get("clip_result_path")
        or (dest / "gpu_clip_result.json")
    )
    if not result_path.is_file():
        for cand in sorted(dest.glob("*clip*.json")) + sorted(dest.glob("*result*.json")):
            if cand.is_file():
                result_path = cand
                break
    if not result_path.is_file():
        raise FileNotFoundError(f"no clip result under {dest}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    canonical = dest / "gpu_clip_result.json"
    if result_path.resolve() != canonical.resolve():
        canonical.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not Path(args.mesh).is_file():
        raise FileNotFoundError(args.mesh)
    if not Path(args.notebook).is_file():
        raise FileNotFoundError(args.notebook)

    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from run_chain_space_surface_compare import (
        _prepare_choice_config,
        _select_choice,
        _sprite_dir,
    )
    import roc_semantic_hybrid_widgets as widgets

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    plan = {
        "proof": "generated experiment candidate; not delivery validated",
        "clip": "roc_move",
        "mesh": str(Path(args.mesh).resolve()).replace("\\", "/"),
        "geometryAuthority": GEOMETRY_AUTHORITY,
        "modes": list(COMPARE_MODES),
        "comparedVariable": "bone_order_mode",
        "articulated_iterations": 1,
        "chain_space_enabled": False,
        "out": str(out_root).replace("\\", "/"),
    }
    (out_root / "compare_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0

    choice = _select_choice(widgets, unit_sid="h3_roc", animation="move")
    sprite_dir = Path(_sprite_dir(choice))
    config = _prepare_choice_config(choice, Path(args.mesh), Path(args.notebook))
    frame_count = len(tuple(getattr(config, "frame_indices", ()) or ()))
    if frame_count < 1:
        raise RuntimeError("roc move materialized zero frames")

    if args.compose_only:
        gif = compose_compare_gif(
            out_root=out_root, sprite_dir=sprite_dir, frame_count=frame_count
        )
        print(f"composed {gif}", flush=True)
        return 0

    gpu_kwargs = _shared_kwargs(Path(args.notebook))
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    arm_rows: list[dict[str, Any]] = []
    try:
        for mode in COMPARE_MODES:
            dest = _mode_dir(out_root, mode)
            if args.skip_existing and _result_complete(dest, mode):
                print(f"reuse {mode}: {dest}", flush=True)
                payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
            else:
                dest.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                print(f"fit {mode} frames={frame_count} out={dest}", flush=True)
                try:
                    solved = run_gpu_depth_fit_from_hybrid_config(
                        config,
                        output_dir=dest,
                        **{**gpu_kwargs, "bone_order_mode": mode},
                    )
                    payload = _load_clip_payload(dest, solved)
                    recorded = str((payload.get("config") or {}).get("bone_order_mode") or "")
                    if recorded != mode:
                        raise RuntimeError(
                            f"{dest} recorded bone_order_mode={recorded!r}, not {mode!r}"
                        )
                    print(
                        f"fitted {mode} score={payload.get('score')} "
                        f"elapsed={time.perf_counter() - started:.1f}s",
                        flush=True,
                    )
                finally:
                    _release_gpu()

            arm_rows.append(
                {
                    "mode": mode,
                    "panel": PANEL_LABELS[mode],
                    "score": payload.get("score"),
                    "frameIoU": payload.get("frameIoU"),
                    "frameScores": payload.get("frameScores"),
                    "dir": str(dest).replace("\\", "/"),
                }
            )

        gif = compose_compare_gif(
            out_root=out_root, sprite_dir=sprite_dir, frame_count=frame_count
        )
        report = {
            "proof": (
                "generated-artifact; roc move bone_order_mode compare under "
                "motion-led geometry; not OE runtime"
            ),
            "gif": str(gif).replace("\\", "/"),
            "frameCount": frame_count,
            "arms": arm_rows,
            "plan": plan,
        }
        (out_root / "compare_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2), flush=True)
        print(f"composed {gif}", flush=True)
        return 0
    finally:
        release_cascade_batch_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
