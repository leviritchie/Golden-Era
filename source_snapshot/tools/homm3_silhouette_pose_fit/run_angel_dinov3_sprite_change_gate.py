#!/usr/bin/env python3
"""Angel idle_start_move_end: still-plate sprite-change veto.

Subtracting change-map excess from DINOv3 made keep optimize the wrong
thing (score 0.822). A veto on every plate then froze frames 01–27 to one
identical picture (score 0.913, walk MAD 0): the first step off bind
changes more RGB than consecutive sprites do.

This run keeps DINOv3 as the score. Excess versus the last accepted
picture of the *same* plate is a veto only on still sprites (MAD < 0.015).
Walk plates are unconstrained. After base/articulated, still plates are
seeded from the previous pose once so they are not left in bind.

Notebook GPU knobs are reused except:
    - joint_keep_sprite_change_gate=True
    - joint_keep_still_sprite_lock=False
    - live_preview=False
    - physics_smooth_enabled=False

Output is a new folder so unlocked, still-lock, penalty-gate, and
whole-clip-veto GIFs are not overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
ANGEL_MESH = ROOT / "artifacts/meshy_downloads/h3_angel_smartrigged_rigidized.glb"
DEFAULT_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_fit_sprite_change_still_veto"
)
PENALTY_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_fit_sprite_change_gate"
)
STEP_VETO_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_fit_sprite_change_step_veto"
)
UNLOCKED_RGB = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_silhouette_simple_def12_nn_idle_start_move_end"
    / "solved_rgb"
)
LOCK_RGB = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_fit_still_sprite_lock"
    / "solved_rgb"
)
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_angel_bone_order_compare import (  # noqa: E402
    _filter_fit_kwargs,
    _notebook_gpu_kwargs,
    _release_gpu,
    _select_angel_move,
)
from run_crusader_full_animation_set import (  # noqa: E402
    _ensure_hf_token,
    _literal_config_kwargs,
    _notebook_config,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    prepare_gpu_targets,
)


OVERRIDES: dict[str, Any] = {
    "joint_keep_sprite_change_gate": True,
    "joint_keep_sprite_change_weight": 1.0,
    "joint_keep_sprite_change_slack": 0.0,
    "joint_keep_still_sprite_lock": False,
    "live_preview": False,
    "physics_smooth_enabled": False,
}

SPANS: tuple[tuple[str, int, int], ...] = (
    ("idle01_07", 1, 7),
    ("motion08_20", 8, 20),
    ("idle21_27", 21, 27),
)


def _windows_path(path: Path) -> str:
    return str(path.resolve()).replace("/", "\\")


def _load_rgb_stack(folder: Path, frame_count: int) -> np.ndarray:
    frames = []
    for index in range(frame_count):
        path = folder / f"{index:02d}.png"
        if not path.is_file():
            raise FileNotFoundError(path)
        with Image.open(path) as image:
            frames.append(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
    return np.stack(frames, axis=0)


def _span_consecutive_mad(rgb: np.ndarray, start: int, end: int) -> float:
    if start < 1 or end >= int(rgb.shape[0]) or start > end:
        raise ValueError(f"span {start:02d}-{end:02d} is outside the clip")
    deltas = np.abs(rgb[start : end + 1] - rgb[start - 1 : end]).mean(axis=(1, 2, 3))
    return float(deltas.mean())


def _compare_spans(solved_rgb: Path, frame_count: int) -> dict[str, Any]:
    ours = _load_rgb_stack(solved_rgb, frame_count)
    payload: dict[str, Any] = {}
    for name, start, end in SPANS:
        row: dict[str, float] = {
            "gate": _span_consecutive_mad(ours, start, end),
        }
        if UNLOCKED_RGB.is_dir():
            unlocked = _load_rgb_stack(UNLOCKED_RGB, frame_count)
            row["unlocked"] = _span_consecutive_mad(unlocked, start, end)
        if LOCK_RGB.is_dir():
            locked = _load_rgb_stack(LOCK_RGB, frame_count)
            row["wholePoseLock"] = _span_consecutive_mad(locked, start, end)
        payload[name] = row
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=ANGEL_MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    mesh = Path(args.mesh).resolve()
    if mesh != ANGEL_MESH.resolve():
        raise RuntimeError(f"sprite-change gate run is locked to {ANGEL_MESH}")
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    _ensure_hf_token()
    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import RocHybridConfig

    choice = _select_angel_move(widgets)
    out_dir = Path(args.out).resolve()
    unlocked_out = (
        Path(choice.pilot_dir) / "gpu_depth_silhouette_simple_def12_nn_idle_start_move_end"
    ).resolve()
    lock_out = (
        Path(choice.pilot_dir) / "gpu_depth_fit_still_sprite_lock"
    ).resolve()
    penalty_out = (
        Path(choice.pilot_dir) / "gpu_depth_fit_sprite_change_gate"
    ).resolve()
    step_veto_out = (
        Path(choice.pilot_dir) / "gpu_depth_fit_sprite_change_step_veto"
    ).resolve()
    if out_dir in {unlocked_out, lock_out, penalty_out, step_veto_out}:
        raise RuntimeError(
            "refusing to overwrite the unlocked, still-lock, penalty-gate, "
            "or whole-clip-veto output folder"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
    gpu_kwargs = _filter_fit_kwargs(_notebook_gpu_kwargs(args.notebook))
    gpu_kwargs.update(OVERRIDES)
    if str(gpu_kwargs.get("score_mode") or "") != "dinov3_dense":
        raise RuntimeError(
            "notebook CASCADE_SCORE_MODE must be dinov3_dense for this hypothesis; "
            f"got {gpu_kwargs.get('score_mode')!r}"
        )

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

    plan = {
        "unit": choice.unit_sid,
        "animation": choice.animation_name,
        "groups": list(choice.def_lab_groups),
        "counts": list(choice.def_expected_counts),
        "frames": len(config.frame_indices),
        "overrides": OVERRIDES,
        "scoreMode": gpu_kwargs.get("score_mode"),
        "mesh": str(mesh).replace("\\", "/"),
        "out": str(out_dir).replace("\\", "/"),
        "hypothesis": (
            "DINOv3 keep is unchanged. Excess vs last committed same-frame "
            "plate vetoes still sprites only. Walk plates are unconstrained. "
            "Whole-clip veto froze 01–27 and is not used."
        ),
    }
    (out_dir / "sprite_change_gate_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(plan, indent=2), flush=True)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    try:
        print(
            f"fit sprite-change-still-veto frames={len(config.frame_indices)} out={out_dir}",
            flush=True,
        )
        solved = run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=out_dir,
            **gpu_kwargs,
        )
        elapsed = time.perf_counter() - started
        clip_path = Path(solved.pose_result["clipResultPath"])
        payload = json.loads(clip_path.read_text(encoding="utf-8"))
        recorded = payload.get("config")
        if not isinstance(recorded, Mapping):
            raise RuntimeError(f"{out_dir} clip result is missing config")
        for key, value in OVERRIDES.items():
            if key == "live_preview":
                continue
            if recorded.get(key) != value:
                raise RuntimeError(
                    f"{out_dir} recorded {key}={recorded.get(key)!r}, expected {value!r}"
                )
        gif = Path(str(solved.pose_result.get("rgbGif") or out_dir / "solved_rgb" / "gpu_solved_rgb.gif"))
        spans = _compare_spans(out_dir / "solved_rgb", len(config.frame_indices))
        summary = {
            "elapsedSeconds": round(elapsed, 1),
            "score": payload.get("score"),
            "rgbGif": str(gif).replace("\\", "/"),
            "rgbGifWindows": _windows_path(gif),
            "clipResult": str(clip_path).replace("\\", "/"),
            "consecutiveRgbMad": spans,
        }
        (out_dir / "sprite_change_gate_result.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2), flush=True)
        print(f"elapsed={elapsed:.1f}s gif={_windows_path(gif)}", flush=True)
        return 0
    finally:
        _release_gpu()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
