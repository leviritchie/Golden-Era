#!/usr/bin/env python3
"""Stacked small-step cheap occupancy joint passes on Roc walk.

This is its own articulation method. It starts from rest (bind joints, no
fused-push / idle / upgrade-line pose seed). Profile camera aims the bind once;
root search and root Adam stay off so motion must come from joints, not per-frame
root spin. Joint search is one bone at a time, ±2.5° up to 10°, six rounds,
silhouette+depth+collision on free frames. Lab chroma is skipped on probes.

Writes only under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_small_pass_v1/``.
Experiment lane. Not pose-pipeline delivery. Not ``CURRENT_CASCADE_KEEP``.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
UNIT = "h3_roc"
CLIP = "idle_start_move_end"
SOLVER_ID = "stacked_small_pass_v1"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
OUT = ROOT / "artifacts/pose_picker_runs" / UNIT / CLIP / SOLVER_ID
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit  # noqa: E402
from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
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

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
    clip=CLIP,
)

STACKED_OVERRIDES = {
    "joint_step_deg": 2.5,
    "fine_joint_step_deg": 2.5,
    "joint_pass_limit_deg": 10.0,
    "joint_probe_rungs": 4,
    "joint_search_axes": ("x", "y", "z"),
    "joint_diagonal_axes": 6,
    "include_unlisted_search_bones": True,
    "bone_limit_scale_overrides": (),
    "joint_adaptive_step_enabled": False,
    "articulated_iterations": 6,
    "articulated_funnel_enabled": False,
    "articulated_funnel_force_gradient_order": False,
    "articulated_multi_bone_enabled": False,
    "joint_round_followup_neighbors": False,
    "score_escape_enabled": False,
    "branch_rescue_enabled": False,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "fine_iterations": 0,
    "cheap_joint_probe_occupancy_only": True,
    "cheap_joint_probe_frame_count": 0,
    "early_symmetry_enabled": False,
    "bone_order_mode": "error_leverage",
    "idle_fused_importance_mode": "error_leverage",
    "idle_fused_macro_enabled": False,
    "idle_fused_shared_transit_yaw_enabled": False,
    "idle_fused_skip_macro_when_seeded": True,
    "idle_fused_skip_reroot_when_seeded": True,
    "root_search_enabled": False,
    "root_iterations": 0,
    "root_refit_after_base_enabled": False,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_defer_camera_up": False,
    "freeze_root_after_root_stage": True,
    "idle_fused_reroot_transit_after_articulated": False,
    "articulated_skip_when_seeded": False,
    "skip_tiny_bones": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": False,
    "live_preview": False,
    "seed_previous_frame": True,
}

EXPERIMENT_NOTE = """# stacked_small_pass_v1 (experiment lane only)

Not pose-pipeline compliant. Not `CURRENT_CASCADE_KEEP`. Do not copy these
poses into `fused_push_v24_pipeline/` or `meshy_downloads/`. Do not call
`gpu_cascade_delivery` or skinned-clip/deliberate-motion ship validators.

- This is a separate articulation method. It starts from rest (bind joints).
  It must not load fused-push, idle-clip, or upgrade-line sibling poses.
- Root search may still aim the whole body at the sprite. Idle-fused macro,
  45° funnel, adaptive 15/30/45, score-escape, and multi-bone combo stay off.
- Each articulated visit is one joint, ±2.5° rungs up to 10°, six skeleton
  rounds. A non-centered joint copies the same local rotvec onto its catalog
  twin (`wing_a`/`wing_b`, `leg_a`/`leg_b`) on every visit. Central groups
  still probe profile-plane x/y.
- Keep during those visits is silhouette + depth + collision. Lab chroma is
  skipped on purpose (the expensive RGB raster). Mesh collision still scores.
  Probes raster free frames only (locked idle prefix/suffix never), and at
  most the worst 8 of those by the occupancy keep score.
- The written `gpu_clip_result.json` still reports the fused chroma+collision
  mix once at the end. Cheap keep skips chroma only; it does not skip collision.
- Proof: generated-artifact JSON + GIFs. Not OE battle.
"""


def assert_stacked_write_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed = (ROOT / "artifacts" / "pose_picker_runs").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(
            f"{SOLVER_ID} may only write under {allowed}; got {resolved}"
        ) from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"{SOLVER_ID} must not write live payload paths: {resolved}")
    if SOLVER_ID not in resolved.parts:
        raise RuntimeError(
            f"{SOLVER_ID} writes must include {SOLVER_ID} in the path; got {resolved}"
        )
    return resolved


def refuse_imported_pose_seed(gpu_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Stacked cheap articulation starts from rest. Pose dicts are not a seed."""
    if "initial_poses" not in gpu_kwargs:
        return gpu_kwargs
    stolen = gpu_kwargs.pop("initial_poses")
    if stolen:
        print(
            "stacked_small_pass_v1: refusing imported pose seed "
            f"({len(stolen)} frames); articulation starts from rest",
            flush=True,
        )
    if gpu_kwargs.get("initial_poses"):
        raise RuntimeError("stacked_small_pass_v1 must not keep initial_poses")
    return gpu_kwargs


FUSED_POSE_SEED = (
    ROOT
    / "artifacts/pose_picker_runs"
    / UNIT
    / CLIP
    / "fused_push_v24_pipeline"
    / "gpu_clip_result.presmooth.json"
)


def refuse_result_matching_fused_seed(payload: dict[str, Any]) -> None:
    """Fail closed if this run still emitted the fused-push pose dict."""
    if not FUSED_POSE_SEED.is_file():
        return
    fused = json.loads(FUSED_POSE_SEED.read_text(encoding="utf-8"))
    fused_poses = fused.get("poses") or {}
    stacked_poses = payload.get("poses") or {}
    if fused_poses and stacked_poses == fused_poses:
        raise RuntimeError(
            "stacked_small_pass_v1 poses match fused-push presmooth; "
            "this method must start from rest, not a fused seed"
        )


def rest_poses_for_frames(frames: list[int]) -> dict[int, dict[str, Any]]:
    return {int(frame): {} for frame in frames}


def compose_compare_gif(
    *,
    sprite_dir: Path,
    rest_rgb_dir: Path,
    stacked_rgb_dir: Path,
    dest: Path,
    frames: list[int],
) -> Path:
    from PIL import Image, ImageDraw

    dest = assert_stacked_write_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for frame in frames:
        sprite_path = sprite_dir / f"{int(frame):02d}.png"
        rest = Image.open(rest_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        stacked = Image.open(stacked_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        panel_w, panel_h = rest.size
        sprite = Image.new("RGB", (panel_w, panel_h), (12, 12, 16))
        if sprite_path.is_file():
            with Image.open(sprite_path) as raw:
                sprite = raw.convert("RGB").resize((panel_w, panel_h))
        header = 22
        canvas = Image.new("RGB", (panel_w * 3, header + panel_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "sprite", fill=(230, 230, 235))
        draw.text((panel_w + 8, 4), "rest", fill=(230, 230, 235))
        draw.text((panel_w * 2 + 8, 4), "stacked cheap", fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(rest, (panel_w, header))
        canvas.paste(stacked, (panel_w * 2, header))
        images.append(canvas)
        rest.close()
        stacked.close()
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return dest


def main() -> int:
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    out = assert_stacked_write_path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    (out / "EXPERIMENT.md").write_text(EXPERIMENT_NOTE, encoding="utf-8")
    if not MESH.is_file():
        raise FileNotFoundError(MESH)

    import roc_semantic_hybrid_widgets as widgets
    from cascade_clip_pose_tweak import raster_tweak_preview
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), UNIT)
    choice = next((item for item in choices if str(item.animation_name) == CLIP), None)
    if choice is None:
        raise RuntimeError(f"no delivery choice for {UNIT} {CLIP}")

    notebook_kwargs = _literal_config_kwargs(NOTEBOOK, require_dino=False)
    notebook_gpu_fit_kwargs(NOTEBOOK)
    config = _build_config(choice, MESH, notebook_kwargs, NOTEBOOK, use_cache=False)
    gpu_kwargs = kwargs_for_choice(choice, full_pipeline=False, batch=True, mesh=MESH)
    gpu_kwargs.update(ANATOMY_KWARGS)
    gpu_kwargs.update(STACKED_OVERRIDES)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs["live_status_path"] = str(out / "live_status.json")
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    if gpu_kwargs.get("initial_poses"):
        raise RuntimeError("stacked_small_pass_v1 must start from rest")
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, MESH)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
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
                "seed": "rest",
                "out": str(out).replace("\\", "/"),
                "articulated_iterations": gpu_kwargs.get("articulated_iterations"),
                "joint_step_deg": gpu_kwargs.get("joint_step_deg"),
                "joint_pass_limit_deg": gpu_kwargs.get("joint_pass_limit_deg"),
                "root_search_enabled": gpu_kwargs.get("root_search_enabled"),
                "cheap_joint_probe_occupancy_only": gpu_kwargs.get(
                    "cheap_joint_probe_occupancy_only"
                ),
                "cheap_joint_probe_frame_count": gpu_kwargs.get(
                    "cheap_joint_probe_frame_count"
                ),
                "early_symmetry_visit_limit": gpu_kwargs.get("early_symmetry_visit_limit"),
                "bone_order_mode": gpu_kwargs.get("bone_order_mode"),
                "neverLiveFusedPush": True,
                "proof": "generated-artifact",
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
        if any(part in FORBIDDEN_WRITE_PARTS for part in result_path.parts):
            raise RuntimeError(f"stacked pass wrote live fused-push: {result_path}")
        frames = [int(frame) for frame in payload["frameIndices"]]
        refuse_result_matching_fused_seed(payload)
        rest_payload = dict(payload)
        rest_payload["poses"] = {
            str(frame): {} for frame in rest_poses_for_frames(frames)
        }
        rest_preview = raster_tweak_preview(
            payload=rest_payload,
            mesh_glb=MESH,
            output_dir=assert_stacked_write_path(out / "rest_preview"),
        )
        sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{CLIP}_shadow_culled"
        targets = payload.get("targetPaths") or []
        if targets:
            sprite_dir = Path(str(targets[0])).parent
        stale_fused_gif = out / "sprite_fused_stacked.gif"
        if stale_fused_gif.is_file():
            stale_fused_gif.unlink()
        stale_fused_preview = out / "fused_seed_preview"
        if stale_fused_preview.is_dir():
            shutil.rmtree(stale_fused_preview)
        gif = compose_compare_gif(
            sprite_dir=sprite_dir,
            rest_rgb_dir=Path(rest_preview["rgbDir"]),
            stacked_rgb_dir=out / "solved_rgb",
            dest=out / "sprite_rest_stacked.gif",
            frames=frames,
        )
        report = {
            "ok": True,
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "poseUnits": payload.get("poseUnits"),
            "seed": "rest",
            "articulated_iterations": (payload.get("config") or {}).get(
                "articulated_iterations"
            ),
            "cheapJointProbeOccupancyOnly": (payload.get("config") or {}).get(
                "cheap_joint_probe_occupancy_only"
            ),
            "compareGif": str(gif).replace("\\", "/"),
            "elapsedSec": time.perf_counter() - started,
            "proof": "generated-artifact",
            "neverMasterGlb": True,
            "currentCascadeKeep": False,
        }
        (out / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
