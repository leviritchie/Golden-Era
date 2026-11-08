#!/usr/bin/env python3
"""Stacked small-step silhouette_miss IK on Roc walk.

Same experiment lane as stacked_small_pass_v1 but articulation is incremental
blob IK (distal chain local-axis steps) instead of one-joint grid probes.
Starts from rest. Profile camera aims the bind once; root search and root Adam
are off so frame-to-frame fit must come from IK, not per-frame root spin. IK uses ±2.5° steps,
four inner rounds per blob chain, six outer re-derive passes. Keep during IK is
silhouette+depth+collision on every free frame. Lab chroma is skipped.

Writes only under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_small_ik_v1/``.
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
SOLVER_ID = "stacked_small_ik_v1"
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
from run_roc_stacked_small_pass import (  # noqa: E402
    refuse_imported_pose_seed,
    refuse_result_matching_fused_seed,
    rest_poses_for_frames,
)

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
    clip=CLIP,
)

STACKED_IK_OVERRIDES = {
    "articulated_iterations": 0,
    "articulated_funnel_enabled": False,
    "articulated_funnel_force_gradient_order": False,
    "articulated_multi_bone_enabled": False,
    "joint_adaptive_step_enabled": False,
    "fine_iterations": 0,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": False,
    "score_escape_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": False,
    "include_unlisted_search_bones": True,
    "bone_limit_scale_overrides": (),
    "joint_search_axes": ("x", "y", "z"),
    "joint_diagonal_axes": 6,
    "ik_enabled": True,
    "ik_keypoints_source": "silhouette_miss",
    "ik_keypoints_path": None,
    "ik_bone_roles_path": None,
    "ik_silhouette_score_mode": "frame_hybrid",
    "ik_max_step_deg": 2.5,
    "ik_proximal_max_step_deg": 2.5,
    "ik_proximal_min_depth": 0,
    "ik_step_scale_mode": "fixed",
    "ik_iterations": 6,
    "ik_blob_search_rounds": 4,
    "ik_max_chain_depth": 6,
    "ik_blob_iou_target": 0.95,
    "ik_require_improvement": False,
    "ik_dynamic_stop_enabled": False,
    "cheap_joint_probe_occupancy_only": True,
    "cheap_joint_probe_frame_count": 0,
    "early_symmetry_enabled": False,
    "bone_order_mode": "error_leverage",
    "idle_fused_macro_enabled": False,
    "idle_fused_shared_transit_yaw_enabled": False,
    "root_search_enabled": False,
    "root_iterations": 0,
    "root_refit_after_base_enabled": False,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_defer_camera_up": False,
    "freeze_root_after_root_stage": True,
    "articulated_skip_when_seeded": False,
    "skip_tiny_bones": False,
    "live_preview": False,
    "seed_previous_frame": True,
}

EXPERIMENT_NOTE = """# stacked_small_ik_v1 (experiment lane only)

Not pose-pipeline compliant. Not `CURRENT_CASCADE_KEEP`. Do not copy these
poses into `fused_push_v24_pipeline/` or `meshy_downloads/`.

- From-rest articulation via silhouette_miss incremental blob IK, not fused
  pose seed and not one-joint articulated probes (`articulated_iterations=0`).
- Profile camera aims the bind once. `root_search_enabled=false`,
  `root_iterations=0`, `freeze_root_after_root_stage=true` — no per-frame root
  hypothesis spin before IK.
  pairs, attributes distal chains, and searches local axes at ±2.5° with four
  inner rounds per chain prefix (≈10° cap per bone per blob, six passes).
- Joint clamps opened for stacked IK: all bones searchable
  (`include_unlisted_search_bones`), no anatomy rotation-scale caps
  (`bone_limit_scale_overrides=()`), x/y/z + 6 diagonal local axes.
- Keep during IK visits is silhouette+depth+collision on **every** free frame
  (`cheap_joint_probe_frame_count=0`, `cheap_joint_probe_occupancy_only`).
  Lab chroma skipped on those probes; collision still scores.
- Final `gpu_clip_result.json` still reports full chroma+collision once.
- Compare GIF: sprite | rest | stacked ik. Proof: generated-artifact. Not OE battle.
"""


def assert_solver_write_path(path: Path) -> Path:
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


def compose_compare_gif(
    *,
    sprite_dir: Path,
    rest_rgb_dir: Path,
    solved_rgb_dir: Path,
    dest: Path,
    frames: list[int],
    solved_label: str,
) -> Path:
    from PIL import Image, ImageDraw

    dest = assert_solver_write_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for frame in frames:
        sprite_path = sprite_dir / f"{int(frame):02d}.png"
        rest = Image.open(rest_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        solved = Image.open(solved_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
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
        draw.text((panel_w * 2 + 8, 4), solved_label, fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(rest, (panel_w, header))
        canvas.paste(solved, (panel_w * 2, header))
        images.append(canvas)
        rest.close()
        solved.close()
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
    out = assert_solver_write_path(OUT)
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
    gpu_kwargs.update(STACKED_IK_OVERRIDES)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs["live_status_path"] = str(out / "live_status.json")
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    if gpu_kwargs.get("initial_poses"):
        raise RuntimeError(f"{SOLVER_ID} must start from rest")
    if not gpu_kwargs.get("ik_enabled"):
        raise RuntimeError(f"{SOLVER_ID} requires ik_enabled=True")
    if bool(gpu_kwargs.get("articulated_funnel_enabled")):
        raise RuntimeError(f"{SOLVER_ID} must not run articulated funnel")
    if int(gpu_kwargs.get("articulated_iterations") or 0) != 0:
        raise RuntimeError(f"{SOLVER_ID} must disable articulated joint probes")
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
                "articulation": "silhouette_miss_ik",
                "out": str(out).replace("\\", "/"),
                "ik_iterations": gpu_kwargs.get("ik_iterations"),
                "ik_max_step_deg": gpu_kwargs.get("ik_max_step_deg"),
                "ik_blob_search_rounds": gpu_kwargs.get("ik_blob_search_rounds"),
                "articulated_iterations": gpu_kwargs.get("articulated_iterations"),
                "cheap_joint_probe_occupancy_only": gpu_kwargs.get(
                    "cheap_joint_probe_occupancy_only"
                ),
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
            raise RuntimeError(f"{SOLVER_ID} wrote live fused-push: {result_path}")
        frames = [int(frame) for frame in payload["frameIndices"]]
        refuse_result_matching_fused_seed(payload)
        rest_payload = dict(payload)
        rest_payload["poses"] = {str(frame): {} for frame in rest_poses_for_frames(frames)}
        rest_preview = raster_tweak_preview(
            payload=rest_payload,
            mesh_glb=MESH,
            output_dir=assert_solver_write_path(out / "rest_preview"),
        )
        sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{CLIP}_shadow_culled"
        targets = payload.get("targetPaths") or []
        if targets:
            sprite_dir = Path(str(targets[0])).parent
        gif = compose_compare_gif(
            sprite_dir=sprite_dir,
            rest_rgb_dir=Path(rest_preview["rgbDir"]),
            solved_rgb_dir=out / "solved_rgb",
            dest=out / "sprite_rest_stacked_ik.gif",
            frames=frames,
            solved_label="stacked ik",
        )
        report = {
            "ok": True,
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "poseUnits": payload.get("poseUnits"),
            "seed": "rest",
            "articulation": "silhouette_miss_ik",
            "ikIterations": (payload.get("config") or {}).get("ik_iterations"),
            "ikMaxStepDeg": (payload.get("config") or {}).get("ik_max_step_deg"),
            "compareGif": str(gif).replace("\\", "/"),
            "elapsedSec": time.perf_counter() - started,
            "proof": "generated-artifact",
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
