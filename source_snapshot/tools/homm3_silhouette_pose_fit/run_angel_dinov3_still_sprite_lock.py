#!/usr/bin/env python3
"""Angel idle_start_move_end: still-sprite lock on the dinov3_dense cascade.

Hypothesis: idle wiggle is per-frame DINOv3 argmax on sprites that barely
changed. This run copies the previous frame's full pose onto still frames
(MAD < 0.015) after each gather, consensus, root, and SA commit.

Notebook GPU knobs are reused except:
- joint_keep_still_sprite_lock=True
- live_preview=False
- physics_smooth_enabled=False

Output is a new folder so the unlocked dinov3 GIF is not overwritten.
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
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
ANGEL_MESH = ROOT / "artifacts/meshy_downloads/h3_angel_smartrigged_rigidized.glb"
DEFAULT_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end"
    / "gpu_depth_fit_still_sprite_lock"
)
STILL_MAD = 0.015

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
    "joint_keep_still_sprite_lock": True,
    "joint_keep_still_sprite_rgb_mad": STILL_MAD,
    "live_preview": False,
    "physics_smooth_enabled": False,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=ANGEL_MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    mesh = Path(args.mesh).resolve()
    if mesh != ANGEL_MESH.resolve():
        raise RuntimeError(f"still-sprite lock run is locked to {ANGEL_MESH}")
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    _ensure_hf_token()
    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import RocHybridConfig

    choice = _select_angel_move(widgets)
    out_dir = Path(args.out).resolve()
    if out_dir.resolve() == (
        Path(choice.pilot_dir) / "gpu_depth_silhouette_simple_def12_nn_idle_start_move_end"
    ).resolve():
        raise RuntimeError("refusing to overwrite the unlocked dinov3 output folder")
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
            "still sprites (consecutive RGB MAD < 0.015) cannot keep a different "
            "pose than the previous frame"
        ),
    }
    (out_dir / "still_sprite_lock_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(plan, indent=2), flush=True)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    try:
        print(
            f"fit still-sprite-lock frames={len(config.frame_indices)} out={out_dir}",
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
        summary = {
            "elapsedSeconds": round(elapsed, 1),
            "score": payload.get("score"),
            "rgbGif": str(gif).replace("\\", "/"),
            "clipResult": str(clip_path).replace("\\", "/"),
        }
        (out_dir / "still_sprite_lock_result.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2), flush=True)
        print(f"elapsed={elapsed:.1f}s gif={gif}", flush=True)
        return 0
    finally:
        _release_gpu()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
