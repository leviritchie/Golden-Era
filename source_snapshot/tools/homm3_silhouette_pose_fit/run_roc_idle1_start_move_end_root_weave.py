#!/usr/bin/env python3
"""Roc transit: 1 idle + move_start + move + move_end, prior-frame seed.

Move-only starts already rotated off rest. This clip keeps one leading idle
frame (last idle before move_start), then start/move/end, drops trailing idle.

Fit uses base+articulated+mid+branch rescue and woven root micro-turns.
sprite_aligned_motion_keep is off: on idle->move transitions its hold pass
zeros travel that does not beat occupancy motion by 0.01, which traps the dive.
Generated-artifact only; not OE runtime.
"""

from __future__ import annotations

import gc
import inspect
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end"
DEST = OUT / "gradient_magnitude_root_weave"
MOVE_ONLY_WEAVE = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/bone_importance_compare"
    / "gradient_magnitude_root_interleave"
)

sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)

IDLE_COUNT = 8
START_COUNT = 4
MOVE_COUNT = 6
END_COUNT = 4
KEEP_FRAME_INDICES = (IDLE_COUNT - 1,) + tuple(
    range(IDLE_COUNT, IDLE_COUNT + START_COUNT + MOVE_COUNT + END_COUNT)
)
SLICED_GROUPS = (2, 20, 0, 21)
SLICED_COUNTS = (1, START_COUNT, MOVE_COUNT, END_COUNT)


def release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def filter_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.discard("config")
    allowed.discard("output_dir")
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError("bad kwargs: " + ", ".join(unknown))
    return {k: kwargs[k] for k in kwargs if k in allowed}


def shared_kwargs() -> dict[str, Any]:
    from run_crusader_gpu_cascade_animation_set import notebook_gpu_fit_kwargs

    kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
    kwargs.update(
        {
            "score_mode": "geometry",
            "motion_weight": 1.0,
            "depth_weight": 0.25,
            "silhouette_weight": 0.2,
            "chroma_weight": 0.2,
            "collision_enabled": True,
            "collision_weight": 0.35,
            "sa_enabled": False,
            "gradient_ladder_enabled": False,
            "ik_enabled": False,
            "physics_smooth_enabled": False,
            "joint_temporal_consensus_enabled": True,
            "sprite_aligned_motion_keep_enabled": False,
            "sprite_aligned_motion_keep_min_improvement": 0.01,
            "live_preview": False,
            "chain_space_enabled": False,
            "articulated_iterations": 1,
            "fine_iterations": 0,
            "base_pose_enabled": True,
            "mid_pose_enabled": True,
            "branch_rescue_enabled": True,
            "skip_tiny_bones": False,
            "bone_order_mode": "gradient_magnitude",
            "root_search_enabled": False,
            "root_refit_after_base_enabled": False,
            "root_rotation_defer_camera_up": False,
            "articulated_root_interleave_enabled": True,
            "articulated_root_interleave_rotation_deg": 8.0,
            "articulated_root_interleave_rotation_step_deg": 4.0,
            "articulated_root_interleave_include_translation": False,
            "seed_previous_frame": True,
            "idle_prefix_frames": 1,
            "idle_suffix_frames": 0,
            "joint_temporal_consensus_idle_end": False,
        }
    )
    return filter_kwargs(kwargs)


def idle1_start_move_end_config(mesh: Path, notebook: Path):
    from run_chain_space_surface_compare import _prepare_choice_config, _select_choice
    import roc_semantic_hybrid_widgets as widgets

    choice = _select_choice(widgets, unit_sid="h3_roc", animation="idle_start_move_end")
    if tuple(choice.def_lab_groups) != (2, 20, 0, 21, 2):
        raise RuntimeError(f"unexpected roc groups: {choice.def_lab_groups}")
    if tuple(choice.def_expected_counts) != (8, 4, 6, 4, 8):
        raise RuntimeError(f"unexpected roc counts: {choice.def_expected_counts}")
    config = _prepare_choice_config(choice, mesh, notebook)
    if tuple(config.frame_indices) != tuple(range(30)):
        raise RuntimeError(f"expected 30 materialized frames, got {config.frame_indices}")
    expected_keep = (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
    if KEEP_FRAME_INDICES != expected_keep:
        raise RuntimeError(f"frame recipe drifted: {KEEP_FRAME_INDICES}")
    # Keep authentic DEF group counts so rematerialize still sees 8 idle frames.
    # The loaded clip is the KEEP_FRAME_INDICES subset; idle_prefix_frames=1 is
    # passed to the adapter so cascade treat only the first loaded frame as idle.
    return replace(
        config,
        frame_indices=KEEP_FRAME_INDICES,
        seed_from_previous=True,
        animation_name="idle1_start_move_end",
    )


def load_payload(dest: Path, solved=None) -> dict[str, Any]:
    path = dest / "gpu_clip_result.json"
    if solved is not None:
        pose = getattr(solved, "pose_result", None) or getattr(solved, "clip_result", None) or {}
        if isinstance(pose, dict):
            cand = Path(pose.get("clipResultPath") or pose.get("clip_result_path") or path)
            if cand.is_file():
                path = cand
    if not path.is_file():
        for cand in sorted(dest.glob("*clip*.json")):
            path = cand
            break
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = dest / "gpu_clip_result.json"
    if path.resolve() != canonical.resolve():
        canonical.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def assert_contract(payload: Mapping[str, Any], *, frame_count: int) -> None:
    cfg = payload.get("config")
    if not isinstance(cfg, Mapping):
        raise RuntimeError("missing config")
    if str(cfg.get("bone_order_mode") or "") != "gradient_magnitude":
        raise RuntimeError(f"bone_order_mode={cfg.get('bone_order_mode')!r}")
    if bool(cfg.get("root_search_enabled")):
        raise RuntimeError("root_search_enabled should be False")
    if not bool(cfg.get("articulated_root_interleave_enabled")):
        raise RuntimeError("articulated_root_interleave_enabled should be True")
    if not bool(cfg.get("optimize_root_rotation")):
        raise RuntimeError("optimize_root_rotation should be True")
    if not bool(cfg.get("seed_previous_frame")):
        raise RuntimeError("seed_previous_frame should be True")
    if int(cfg.get("idle_prefix_frames") or 0) != 1:
        raise RuntimeError(f"idle_prefix_frames={cfg.get('idle_prefix_frames')!r}, want 1")
    rgb = DEST / "solved_rgb"
    n_png = len(list(rgb.glob("*.png"))) if rgb.is_dir() else 0
    if n_png < frame_count:
        raise RuntimeError(f"solved_rgb has {n_png} pngs, want >= {frame_count}")


def stage_sequential_pngs(src_dir: Path, dest_dir: Path, keep: tuple[int, ...]) -> Path:
    """Renumber a subset lane to 00..n-1 for compose_method_compare_gif.

    Always read by source index (``keep``), never by output index in ``src_dir``.
    The full idle_start_move_end shadow-culled lane is 00..29; preferring 00.png
    in the source would stage early idle instead of the last idle + move clip.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for out_i, src_i in enumerate(keep):
        src_path = src_dir / f"{int(src_i):02d}.png"
        if not src_path.is_file():
            raise FileNotFoundError(
                f"missing source frame {int(src_i):02d} under {src_dir} "
                f"(clip output index {out_i})"
            )
        (dest_dir / f"{out_i:02d}.png").write_bytes(src_path.read_bytes())
    return dest_dir


def main() -> int:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from run_chain_space_surface_compare import _select_choice, _sprite_dir
    import roc_semantic_hybrid_widgets as widgets
    from compose_method_compare_gif import main as compose_main

    if not MESH.is_file():
        raise FileNotFoundError(MESH)
    if not NOTEBOOK.is_file():
        raise FileNotFoundError(NOTEBOOK)

    OUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "proof": "generated experiment candidate; not delivery validated",
        "clip": "idle1_start_move_end",
        "recipe": {
            "keepFrameIndices": list(KEEP_FRAME_INDICES),
            "defGroups": list(SLICED_GROUPS),
            "defCounts": list(SLICED_COUNTS),
            "idle": "1 frame (last leading idle)",
            "move_start": START_COUNT,
            "move": MOVE_COUNT,
            "move_end": END_COUNT,
            "trailing_idle": 0,
            "seed_previous_frame": True,
        },
        "bone_order_mode": "gradient_magnitude",
        "articulated_root_interleave_enabled": True,
        "out": str(DEST).replace("\\", "/"),
        "moveOnlyWeavePrior": str(MOVE_ONLY_WEAVE).replace("\\", "/"),
    }
    (OUT / "compare_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2), flush=True)

    choice = _select_choice(widgets, unit_sid="h3_roc", animation="idle_start_move_end")
    full_sprite = Path(_sprite_dir(choice))
    sprite_dir = stage_sequential_pngs(
        full_sprite, OUT / "sprite_idle1_start_move_end", KEEP_FRAME_INDICES
    )

    config = idle1_start_move_end_config(MESH, NOTEBOOK)
    frame_count = len(tuple(config.frame_indices))
    if frame_count != len(KEEP_FRAME_INDICES):
        raise RuntimeError("frame_count mismatch")

    DEST.mkdir(parents=True, exist_ok=True)
    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        print(f"fit idle1_start_move_end weave frames={frame_count} -> {DEST}", flush=True)
        solved = run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=DEST,
            **shared_kwargs(),
        )
        payload = load_payload(DEST, solved)
        assert_contract(payload, frame_count=frame_count)
        print(
            f"fitted score={payload.get('score')} elapsed={time.perf_counter() - started:.1f}s",
            flush=True,
        )
    finally:
        release_gpu()
        release_cascade_batch_lock(lock)

    compose_rgb = stage_sequential_pngs(
        DEST / "solved_rgb", DEST / "solved_rgb_sequential", KEEP_FRAME_INDICES
    )
    gif = OUT / "idle1_start_move_end_root_weave_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        "2",
        "--cell-w",
        "240",
        "--cell-h",
        "280",
        "--hold",
        "2",
        "--frame-count",
        str(frame_count),
        "--panel",
        "sprite",
        str(sprite_dir),
        "--panel",
        "idle1+S+M+E weave",
        str(compose_rgb),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compose failed")

    prior_score = None
    prior_path = MOVE_ONLY_WEAVE / "gpu_clip_result.json"
    if prior_path.is_file():
        prior_score = json.loads(prior_path.read_text(encoding="utf-8")).get("score")

    report = {
        "proof": (
            "generated-artifact; roc idle1+start+move+end with prior-frame seed "
            "and woven root; not OE runtime"
        ),
        "elapsedSec": round(time.perf_counter() - started, 1),
        "gif": str(gif).replace("\\", "/"),
        "score": payload.get("score"),
        "moveOnlyWeavePriorScore": prior_score,
        "frameCount": frame_count,
        "frameIoU": payload.get("frameIoU"),
        "frameScores": payload.get("frameScores"),
        "recipe": plan["recipe"],
        "config": {
            "bone_order_mode": (payload.get("config") or {}).get("bone_order_mode"),
            "root_search_enabled": (payload.get("config") or {}).get("root_search_enabled"),
            "articulated_root_interleave_enabled": (payload.get("config") or {}).get(
                "articulated_root_interleave_enabled"
            ),
            "optimize_root_rotation": (payload.get("config") or {}).get("optimize_root_rotation"),
            "seed_previous_frame": (payload.get("config") or {}).get("seed_previous_frame"),
            "idle_prefix_frames": (payload.get("config") or {}).get("idle_prefix_frames"),
            "def_lab_group": (payload.get("config") or {}).get("def_lab_group"),
            "def_expected_count": (payload.get("config") or {}).get("def_expected_count"),
        },
    }
    (OUT / "idle1_start_move_end_root_weave_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2), flush=True)
    print(f"composed {gif}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
