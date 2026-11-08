#!/usr/bin/env python3
"""Run the full fused-push pose pipeline for Roc idle_start_move_end.

Starts from the existing abbreviated fused-push poses (read-only) and lets the
pre-BATCH_PERF search budget refine them. Writes only under
artifacts/sprite_feasibility/. Never writes live fused_push_v24_pipeline/ or
artifacts/meshy_downloads/.

Proof: generated-artifact gpu_clip_result.json. Not OE battle. Not masterGlb.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
UNIT = "h3_roc"
CLIP = "idle_start_move_end"
OUT = ROOT / "artifacts/sprite_feasibility" / UNIT / f"{CLIP}_full_pipeline"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from run_crusader_full_animation_set import _literal_config_kwargs  # noqa: E402
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
from sprite_pose_feasibility import assert_write_path  # noqa: E402


def _load_seed_poses(path: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    require_pose_units_degrees(payload, source=str(path))
    poses = payload.get("poses")
    if not isinstance(poses, dict) or not poses:
        raise RuntimeError(f"{path} has no poses to seed from")
    return {int(frame): dict(pose) for frame, pose in poses.items()}


def main() -> int:
    raise RuntimeError(
        "refusing full fused-push for roc idle_start_move_end: this budget "
        "spilled into shared GPU memory and does not complete. Seed surgery "
        "from the completed abbreviated fused-push poses instead."
    )
    out = assert_write_path(OUT, repo_root=ROOT)
    if "fused_push_v24_pipeline" in out.parts or "meshy_downloads" in out.parts:
        raise RuntimeError(f"refusing live pipeline write path: {out}")
    out.mkdir(parents=True, exist_ok=True)

    seed_clip = (
        ROOT
        / "artifacts"
        / "pose_picker_runs"
        / UNIT
        / CLIP
        / "fused_push_v24_pipeline"
        / "gpu_clip_result.json"
    )
    if not seed_clip.is_file():
        raise FileNotFoundError(f"missing abbreviated fused-push seed (read-only): {seed_clip}")
    seed_poses = _load_seed_poses(seed_clip)

    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from inventory_smartrig_skinned_rollout import STATUS_PATH, build_status
    from fused_push_mesh_raster_budget import apply_mesh_raster_budget

    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.is_file() else build_status()
    rows = [
        row
        for row in status["units"]
        if row.get("labSid") == UNIT and row.get("meshRole") == "own_glb"
    ]
    if not rows:
        raise RuntimeError(f"{UNIT} is not an own-GLB SmartRig row")
    mesh = Path(rows[0]["glb"]).resolve()
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), UNIT)
    choice = next((item for item in choices if str(item.animation_name) == CLIP), None)
    if choice is None:
        raise RuntimeError(f"no delivery choice for {UNIT} {CLIP}")

    notebook_kwargs = _literal_config_kwargs(NOTEBOOK, require_dino=False)
    notebook_gpu_fit_kwargs(NOTEBOOK)
    config = _build_config(choice, mesh, notebook_kwargs, NOTEBOOK, use_cache=False)
    gpu_kwargs = kwargs_for_choice(choice, full_pipeline=True, mesh=mesh)
    gpu_kwargs["initial_poses"] = seed_poses
    gpu_kwargs["articulated_skip_when_seeded"] = False
    gpu_kwargs["root_skip_when_seeded"] = False
    gpu_kwargs["idle_fused_skip_macro_when_seeded"] = False
    gpu_kwargs["idle_fused_skip_reroot_when_seeded"] = False
    frames = len(seed_poses)
    gpu_kwargs, budget = apply_mesh_raster_budget(gpu_kwargs, mesh, frame_count=frames)
    gpu_kwargs["live_status_path"] = str(out / "live_status.json")
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, mesh)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config = prepare_gpu_targets(config)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    print(
        json.dumps(
            {
                "unit": UNIT,
                "clip": CLIP,
                "seed": str(seed_clip).replace("\\", "/"),
                "out": str(out).replace("\\", "/"),
                "articulated_iterations": gpu_kwargs.get("articulated_iterations"),
                "score_escape_mode": gpu_kwargs.get("score_escape_mode"),
                "raster": budget,
                "neverLiveFusedPush": True,
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        solved = run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=out,
            **dict(gpu_kwargs),
        )
        result_path = Path(solved.pose_result["clipResultPath"])
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(payload, source=str(result_path))
        if "fused_push_v24_pipeline" in result_path.parts:
            raise RuntimeError(f"full pipeline wrote live fused-push: {result_path}")
        report = {
            "ok": True,
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "poseUnits": payload.get("poseUnits"),
            "articulated_iterations": (payload.get("config") or {}).get("articulated_iterations"),
            "elapsedSec": time.perf_counter() - started,
            "proof": "generated-artifact",
            "neverMasterGlb": True,
        }
        (out / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
