#!/usr/bin/env python3
"""Refresh Cavalier owned bind, fit attack on owned rig, compare vs Meshy Smart Rig.

1. Re-run owned_rerig from the Meshy Smart Rig source (strip + part map + bind).
2. GPU-fit idle_attack_front on the owned master (not smartrig).
3. Raster compare: sprite | Meshy smartrig+smartrig poses | owned+owned poses.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
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
OWNED_MASTER = PIPELINE / "owned_bind/h3_cavalier_master_yup.glb"
SMARTRIG_MESH = MESHY / "h3_cavalier_smartrigged_rigidized.glb"
SMARTRIG_SRC = MESHY / "h3_cavalier_smartrigged.glb"
PART_MAP = PIPELINE / "part_map_authored.json"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
OWNED_GPU_RUN = "owned_fused_push_v1_pipeline"
COMPARE_OUT = PIPELINE / "owned_rig_test"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(ROOT / "tools/homm3_meshy_frame_pose"))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from owned_rerig.pipeline import run_owned_rerig_pipeline  # noqa: E402
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


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--animation", default="idle_attack_front")
    ap.add_argument("--skip-rerig", action="store_true")
    ap.add_argument("--skip-fit", action="store_true")
    ap.add_argument("--skip-compare", action="store_true")
    ap.add_argument("--memory-safe", action="store_true", default=True)
    ap.add_argument("--overwrite-fit", action="store_true")
    return ap.parse_args()


def _refresh_owned_bind() -> dict[str, Any]:
    if not SMARTRIG_SRC.is_file():
        raise FileNotFoundError(f"smartrig source missing: {SMARTRIG_SRC}")
    if not PART_MAP.is_file():
        raise FileNotFoundError(f"part map missing: {PART_MAP}")
    report = run_owned_rerig_pipeline(
        dest_dir=PIPELINE,
        src_glb=SMARTRIG_SRC,
        part_map_path=PART_MAP,
        species="rider_mount",
        unit_sid="h3_cavalier",
    )
    if not report.get("audit", {}).get("ok"):
        raise RuntimeError(f"owned bind audit failed: {report.get('audit')}")
    return report


def _find_choice(animation: str):
    import roc_semantic_hybrid_widgets as widgets
    from gpu_cascade_delivery import select_unit_delivery_choices

    choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), "h3_cavalier")
    for choice in choices:
        if str(choice.animation_name) == animation:
            return choice
    known = sorted({str(c.animation_name) for c in choices})
    raise RuntimeError(f"no delivery choice for h3_cavalier {animation!r}; known={known}")


def _owned_clip_result(choice) -> Path:
    return Path(choice.pilot_dir) / OWNED_GPU_RUN / "gpu_clip_result.json"


def _owned_gpu_output(choice) -> Path:
    return Path(choice.pilot_dir) / OWNED_GPU_RUN


def _fit_owned_attack(choice, *, memory_safe: bool, overwrite: bool) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    mesh = OWNED_MASTER.resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"owned master missing: {mesh}")

    clip_path = _owned_clip_result(choice)
    if clip_path.is_file() and not overwrite:
        payload = json.loads(clip_path.read_text(encoding="utf-8"))
        print(f"reuse owned fit: {clip_path}", flush=True)
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

    out_dir = _owned_gpu_output(choice)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print(
        f"owned fit {choice.animation_name} mesh={mesh} "
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
        f"owned fitted score={payload.get('score')} elapsed={time.perf_counter() - started:.1f}s",
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


def _compare_rig_test(*, animation: str, owned_payload: dict[str, Any]) -> dict[str, Any]:
    from cascade_clip_pose_tweak import load_clip_result, raster_tweak_preview
    from compose_method_compare_gif import main as compose_gif_main
    from preview_timing import PREVIEW_GIF_FRAME_MS
    from tweak_gpu_clip_poses import _with_cascade_lock

    smartrig_clip = POSE_RUNS / "h3_cavalier" / animation / "fused_push_v24_pipeline/gpu_clip_result.json"
    if not smartrig_clip.is_file():
        raise FileNotFoundError(f"smartrig clip missing: {smartrig_clip}")
    if not SMARTRIG_MESH.is_file():
        raise FileNotFoundError(f"smartrig mesh missing: {SMARTRIG_MESH}")

    sprite_dir = POSE_RUNS / "h3_cavalier" / animation / f"frames_def12_nn_{animation}_shadow_culled"
    if not sprite_dir.is_dir():
        raise FileNotFoundError(f"sprite dir missing: {sprite_dir}")

    owned_clip_path = _owned_clip_result(_find_choice(animation))
    owned_payload = json.loads(owned_clip_path.read_text(encoding="utf-8"))
    smartrig_payload = load_clip_result(smartrig_clip)
    frame_count = len(smartrig_payload.get("frameIndices") or [])
    if frame_count < 1:
        raise ValueError("smartrig clip has no frames")

    clip_out = COMPARE_OUT / animation
    smartrig_raster = clip_out / "smartrig_raster"
    owned_raster = clip_out / "owned_raster"
    smartrig_raster.mkdir(parents=True, exist_ok=True)
    owned_raster.mkdir(parents=True, exist_ok=True)

    smartrig_rgb = Path(
        _with_cascade_lock(
            lambda: raster_tweak_preview(
                payload=smartrig_payload,
                mesh_glb=SMARTRIG_MESH,
                output_dir=smartrig_raster,
            )
        )["rgbDir"]
    )
    owned_rgb = Path(
        _with_cascade_lock(
            lambda: raster_tweak_preview(
                payload=owned_payload,
                mesh_glb=OWNED_MASTER,
                output_dir=owned_raster,
            )
        )["rgbDir"]
    )

    gif_path = clip_out / "smartrig_vs_owned.gif"
    argv = [
        "--out",
        str(gif_path),
        "--cols",
        "3",
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
        "--panel",
        "sprite",
        str(sprite_dir),
        "--panel",
        "smartrig",
        str(smartrig_rgb),
        "--panel",
        "owned_bind",
        str(owned_rgb),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_gif_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError(f"GIF compose failed: {gif_path}")

    return {
        "animation": animation,
        "compareGif": str(gif_path).replace("\\", "/"),
        "smartrigMesh": str(SMARTRIG_MESH).replace("\\", "/"),
        "ownedMesh": str(OWNED_MASTER).replace("\\", "/"),
        "smartrigClip": str(smartrig_clip).replace("\\", "/"),
        "ownedClip": str(owned_clip_path).replace("\\", "/"),
        "smartrigScore": smartrig_payload.get("score"),
        "ownedScore": owned_payload.get("score"),
        "frameCount": frame_count,
        "panels": ["sprite", "smartrig", "owned_bind"],
    }


def main() -> int:
    args = _parse()
    summary: dict[str, Any] = {"ok": True, "updatedAt": _utc_now(), "labSid": "h3_cavalier"}

    if not args.skip_rerig:
        print("[cavalier-owned-test] refresh owned bind...", flush=True)
        summary["ownedRerig"] = _refresh_owned_bind()
    else:
        summary["ownedRerig"] = {"status": "skipped"}

    bind_proof = subprocess.run(
        [sys.executable, str(TOOL / "run_cavalier_gpu_cascade_animation_set.py")],
        cwd=str(ROOT),
        check=False,
    )
    if bind_proof.returncode != 0:
        raise RuntimeError(f"bind proof failed (exit {bind_proof.returncode})")
    summary["bindProof"] = str((PIPELINE / "gpu_cascade_skinned/clip_report.json")).replace("\\", "/")

    choice = _find_choice(str(args.animation))
    owned_payload: dict[str, Any] | None = None
    if not args.skip_fit:
        lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
        try:
            print(f"[cavalier-owned-test] fit owned {args.animation}...", flush=True)
            owned_payload = _fit_owned_attack(
                choice,
                memory_safe=bool(args.memory_safe),
                overwrite=bool(args.overwrite_fit),
            )
            summary["ownedFit"] = {
                "animation": args.animation,
                "score": owned_payload.get("score"),
                "clipResult": str(_owned_clip_result(choice)).replace("\\", "/"),
            }
        finally:
            release_cascade_batch_lock(lock, pid=__import__("os").getpid())
    else:
        summary["ownedFit"] = {"status": "skipped"}

    if not args.skip_compare:
        print("[cavalier-owned-test] compare smartrig vs owned...", flush=True)
        if owned_payload is None:
            owned_payload = json.loads(_owned_clip_result(choice).read_text(encoding="utf-8"))
        summary["compare"] = _compare_rig_test(
            animation=str(args.animation),
            owned_payload=owned_payload,
        )

    summary["proof"] = (
        "generated artifact validated — owned rider_mount bind vs UniRig smartrig; not OE runtime proven"
    )
    summary_path = COMPARE_OUT / "owned_rig_test_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
