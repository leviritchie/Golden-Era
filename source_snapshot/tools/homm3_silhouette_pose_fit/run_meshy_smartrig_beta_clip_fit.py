#!/usr/bin/env python3
"""Fit one fused-push clip on a new Meshy Smart Rig Beta GLB.

Does not seed from older fused_push_v24 poses (joint counts often change).

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
POSE_RUNS = ROOT / "artifacts/pose_picker_runs"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
OLD_RUN = "fused_push_v24_pipeline"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
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
    ap.add_argument("--lab-sid", required=True)
    ap.add_argument("--animation", required=True)
    ap.add_argument("--mesh", type=Path, required=True)
    ap.add_argument("--gpu-run", default="fused_push_smartrig_beta_20260824")
    ap.add_argument("--out-gif", type=Path, default=None)
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-compare", action="store_true")
    ap.add_argument("--memory-safe", action="store_true", default=True)
    ap.add_argument("--overwrite-fit", action="store_true")
    return ap.parse_args()


def _find_choice(lab_sid: str, animation: str):
    import roc_semantic_hybrid_widgets as widgets
    from gpu_cascade_delivery import select_unit_delivery_choices

    choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), lab_sid)
    for choice in choices:
        if str(choice.animation_name) == animation:
            return choice
    known = sorted({str(c.animation_name) for c in choices})
    raise RuntimeError(f"no delivery choice for {lab_sid} {animation!r}; known={known}")


def _out_dir(choice, run_name: str) -> Path:
    return Path(choice.pilot_dir) / run_name


def _clip_path(choice, run_name: str) -> Path:
    return _out_dir(choice, run_name) / "gpu_clip_result.json"


def _fit(*, choice, mesh: Path, gpu_run: str, memory_safe: bool, overwrite: bool) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    clip_path = _clip_path(choice, gpu_run)
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

    out_dir = _out_dir(choice, gpu_run)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print(
        f"beta smartrig fit {choice.unit_sid} {choice.animation_name} mesh={mesh} "
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


def _compare(
    *,
    lab_sid: str,
    animation: str,
    gpu_run: str,
    mesh: Path,
    beta_payload: dict[str, Any],
    out_gif: Path,
) -> dict[str, Any]:
    sprite_dir = POSE_RUNS / lab_sid / animation / f"frames_def12_nn_{animation}_shadow_culled"
    if not sprite_dir.is_dir():
        raise FileNotFoundError(f"sprite dir missing: {sprite_dir}")
    old_rgb = POSE_RUNS / lab_sid / animation / OLD_RUN / "solved_rgb"
    beta_rgb = POSE_RUNS / lab_sid / animation / gpu_run / "solved_rgb"
    if not old_rgb.is_dir():
        raise FileNotFoundError(f"old fused_push RGB missing: {old_rgb}")
    if not beta_rgb.is_dir():
        raise FileNotFoundError(f"beta fused_push RGB missing: {beta_rgb}")

    frame_count = len(beta_payload.get("frameIndices") or [])
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    panels: list[tuple[str, Path]] = [
        ("sprite", sprite_dir),
        ("old_meshy_smartrig", old_rgb),
        ("new_meshy_smartrig_beta", beta_rgb),
    ]
    _compose(out_path=out_gif, panels=panels, frame_count=frame_count)
    return {
        "compareGif": str(out_gif).replace("\\", "/"),
        "panels": [label for label, _ in panels],
        "frameCount": frame_count,
        "betaScore": beta_payload.get("score"),
        "betaMesh": str(mesh.resolve()).replace("\\", "/"),
    }


def main() -> int:
    args = _parse()
    mesh = Path(args.mesh).resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"mesh missing: {mesh}")
    lab_sid = str(args.lab_sid)
    animation = str(args.animation)
    gpu_run = str(args.gpu_run)
    choice = _find_choice(lab_sid, animation)
    out_gif = args.out_gif or (
        POSE_RUNS / lab_sid / animation / "meshy_smartrig_beta_vs_old.gif"
    )
    summary: dict[str, Any] = {
        "ok": True,
        "labSid": lab_sid,
        "animation": animation,
        "mesh": str(mesh).replace("\\", "/"),
        "gpuRun": gpu_run,
        "note": "fresh fit; not seeded from fused_push_v24 poses",
    }
    payload: dict[str, Any] | None = None
    if not args.skip_fit:
        lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
        try:
            payload = _fit(
                choice=choice,
                mesh=mesh,
                gpu_run=gpu_run,
                memory_safe=bool(args.memory_safe),
                overwrite=bool(args.overwrite_fit),
            )
            summary["score"] = payload.get("score")
            summary["clipResult"] = str(_clip_path(choice, gpu_run)).replace("\\", "/")
        finally:
            release_cascade_batch_lock(lock, pid=os.getpid())
    else:
        payload = json.loads(_clip_path(choice, gpu_run).read_text(encoding="utf-8"))
        summary["score"] = payload.get("score")

    if not args.skip_compare:
        assert payload is not None
        summary["compare"] = _compare(
            lab_sid=lab_sid,
            animation=animation,
            gpu_run=gpu_run,
            mesh=mesh,
            beta_payload=payload,
            out_gif=Path(out_gif),
        )

    summary["proof"] = (
        "generated artifact validated — Meshy Smart Rig Beta GPU fit; not OE runtime proven"
    )
    out_json = Path(out_gif).with_suffix(".json")
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
