#!/usr/bin/env python3
"""Fit idle_attack_front on the Aug-24 Meshy Smart Rig Beta GLB.

The new download has 52 joints (old handoff had 63). Do not seed from the
old fused_push_v24 poses. Output is a separate run folder so v24 stays intact.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
MESHY = ROOT / "artifacts/meshy_downloads"
POSE_RUNS = ROOT / "artifacts/pose_picker_runs"
PIPELINE = ROOT / "artifacts/cavalier_pose_pipeline"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
NEW_MESH = MESHY / "h3_cavalier_smartrigged_beta_20260824.glb"
DOWNLOAD_SRC = Path.home() / "Downloads" / "Meshy_AI_Character_output (5).glb"
GPU_RUN = "fused_push_smartrig_beta_20260824"
OLD_RUN = "fused_push_v24_pipeline"
OWNED_RUN = "owned_fused_push_v1_pipeline"
OWNED_MASTER = PIPELINE / "owned_bind/h3_cavalier_master_yup.glb"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_cavalier_owned_rig_test import _find_choice  # noqa: E402
from run_crusader_full_animation_set import _literal_config_kwargs  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)
from run_fused_push_batch_all_units import (  # noqa: E402
    _apply_choice_camera,
    _build_config,
    kwargs_for_choice,
)
from run_fused_push_regression_triplet import filter_kwargs  # noqa: E402


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--animation", default="idle_attack_front")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-compare", action="store_true")
    ap.add_argument("--memory-safe", action="store_true", default=True)
    ap.add_argument("--overwrite-fit", action="store_true")
    return ap.parse_args()


def _ensure_mesh() -> Path:
    if NEW_MESH.is_file():
        return NEW_MESH.resolve()
    if DOWNLOAD_SRC.is_file():
        NEW_MESH.parent.mkdir(parents=True, exist_ok=True)
        NEW_MESH.write_bytes(DOWNLOAD_SRC.read_bytes())
        return NEW_MESH.resolve()
    raise FileNotFoundError(
        f"new Meshy Smart Rig GLB missing: {NEW_MESH} and {DOWNLOAD_SRC}"
    )


def _out_dir(choice, run_name: str) -> Path:
    return Path(choice.pilot_dir) / run_name


def _clip_path(choice, run_name: str) -> Path:
    return _out_dir(choice, run_name) / "gpu_clip_result.json"


def _fit(*, choice, mesh: Path, memory_safe: bool, overwrite: bool) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    clip_path = _clip_path(choice, GPU_RUN)
    if clip_path.is_file() and not overwrite:
        payload = json.loads(clip_path.read_text(encoding="utf-8"))
        print(f"reuse existing beta fit: {clip_path}", flush=True)
        return payload

    notebook_kwargs = _literal_config_kwargs(NOTEBOOK, require_dino=False)
    gpu_kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
    kw = kwargs_for_choice(
        choice,
        full_pipeline=False,
        batch=True,
        memory_safe_batch=memory_safe,
        mesh=mesh,
    )
    # Old idle/v24 poses are 63-bone; this GLB is 52-bone. Start from rest.
    kw.pop("initial_poses", None)
    kw["root_search_enabled"] = True
    kw = filter_kwargs(kw)
    config = _build_config(choice, mesh, notebook_kwargs, NOTEBOOK, use_cache=False)
    config = replace(
        config,
        src_glb=mesh,
        require_meshy_rigidization=False,
        meshy_rigidization_report=None,
    )
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, mesh)
    config = prepare_gpu_targets(config)

    out_dir = _out_dir(choice, GPU_RUN)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print(
        f"beta smartrig fit {choice.animation_name} mesh={mesh} "
        f"frames={len(config.frame_indices)} out={out_dir}",
        flush=True,
    )
    solved = run_gpu_depth_fit_from_hybrid_config(
        config,
        output_dir=out_dir,
        **kw,
    )
    clip_path = Path(solved.pose_result["clipResultPath"])
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    print(
        f"beta fitted score={payload.get('score')} elapsed={time.perf_counter() - started:.1f}s",
        flush=True,
    )
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    return payload


def _compose(*, out_path: Path, panels: list[tuple[str, Path]], frame_count: int) -> None:
    from compose_method_compare_gif import main as compose_gif_main
    from preview_timing import PREVIEW_GIF_FRAME_MS

    argv = [
        "--out",
        str(out_path),
        "--cols",
        str(len(panels)),
        "--cell-w",
        "280",
        "--cell-h",
        "320",
        "--hold",
        "2",
        "--duration-ms",
        str(int(PREVIEW_GIF_FRAME_MS)),
        "--frame-count",
        str(int(frame_count)),
    ]
    for label, folder in panels:
        argv.extend(["--panel", label, str(folder)])
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_gif_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError(f"GIF compose failed: {out_path}")


def _compare(*, animation: str, beta_payload: dict[str, Any]) -> dict[str, Any]:
    sprite_dir = POSE_RUNS / "h3_cavalier" / animation / f"frames_def12_nn_{animation}_shadow_culled"
    if not sprite_dir.is_dir():
        raise FileNotFoundError(f"sprite dir missing: {sprite_dir}")
    old_rgb = POSE_RUNS / "h3_cavalier" / animation / OLD_RUN / "solved_rgb"
    beta_rgb = POSE_RUNS / "h3_cavalier" / animation / GPU_RUN / "solved_rgb"
    owned_rgb = POSE_RUNS / "h3_cavalier" / animation / OWNED_RUN / "solved_rgb"
    if not old_rgb.is_dir():
        raise FileNotFoundError(f"old fused_push RGB missing: {old_rgb}")
    if not beta_rgb.is_dir():
        raise FileNotFoundError(f"beta fused_push RGB missing: {beta_rgb}")

    frame_count = len(beta_payload.get("frameIndices") or [])
    clip_out = PIPELINE / "owned_rig_test" / animation
    clip_out.mkdir(parents=True, exist_ok=True)
    panels: list[tuple[str, Path]] = [
        ("sprite", sprite_dir),
        ("old_meshy_smartrig", old_rgb),
        ("new_meshy_smartrig_beta", beta_rgb),
    ]
    if owned_rgb.is_dir():
        panels.append(("owned_bind", owned_rgb))
    gif_path = clip_out / "meshy_smartrig_beta_vs_old_attack.gif"
    _compose(out_path=gif_path, panels=panels, frame_count=frame_count)
    return {
        "compareGif": str(gif_path).replace("\\", "/"),
        "panels": [label for label, _ in panels],
        "frameCount": frame_count,
        "betaScore": beta_payload.get("score"),
        "betaClip": str(_clip_path(_find_choice(animation), GPU_RUN)).replace("\\", "/"),
        "betaMesh": str(NEW_MESH.resolve()).replace("\\", "/"),
    }


def main() -> int:
    args = _parse()
    mesh = _ensure_mesh()
    choice = _find_choice(str(args.animation))
    summary: dict[str, Any] = {
        "ok": True,
        "labSid": "h3_cavalier",
        "animation": args.animation,
        "mesh": str(mesh).replace("\\", "/"),
        "gpuRun": GPU_RUN,
        "note": "52-joint Meshy Smart Rig Beta; not seeded from 63-joint v24 poses",
    }
    payload: dict[str, Any] | None = None
    if not args.skip_fit:
        lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
        try:
            payload = _fit(
                choice=choice,
                mesh=mesh,
                memory_safe=bool(args.memory_safe),
                overwrite=bool(args.overwrite_fit),
            )
            summary["score"] = payload.get("score")
            summary["clipResult"] = str(_clip_path(choice, GPU_RUN)).replace("\\", "/")
        finally:
            release_cascade_batch_lock(lock, pid=os.getpid())
    else:
        payload = json.loads(_clip_path(choice, GPU_RUN).read_text(encoding="utf-8"))
        summary["score"] = payload.get("score")

    if not args.skip_compare:
        assert payload is not None
        summary["compare"] = _compare(animation=str(args.animation), beta_payload=payload)

    summary["proof"] = (
        "generated artifact validated — new Meshy Smart Rig Beta GPU fit; not OE runtime proven"
    )
    out_json = PIPELINE / "owned_rig_test" / str(args.animation) / "meshy_smartrig_beta_attack.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
