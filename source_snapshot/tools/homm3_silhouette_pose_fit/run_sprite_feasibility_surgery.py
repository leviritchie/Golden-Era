#!/usr/bin/env python3
"""Classify sprite leftover, then write previewable camera or body-surgery artifacts.

Writes only under artifacts/sprite_feasibility/. Never live fused-push or Meshy.
Proof: generated-artifact GIFs/GLBs. Not battle, not masterGlb, not installed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from gpu_cascade_batch_lock import (
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees
from leftover_gravity import bone_distance_map, extra_predicted_mask
from sprite_anatomy import (
    anatomy_attitude_bones,
    anatomy_bilateral_pairs,
    anatomy_bilateral_wing_pair,
    anatomy_central_search_groups,
    anatomy_group_bones,
    anatomy_landmark_bone,
    anatomy_ventral_bind_axis,
    anatomy_visual_body_chain,
    anatomy_wing_chain,
    load_unit_anatomy_catalog,
    tpose_pole_for_pair,
)
from occupancy_lane import occupancy_lane_maps
from preview_timing import PREVIEW_GIF_FRAME_MS
from roc_gpu_cascade_experiment import compute_search_bone_influence_maps
from sprite_body_surgery import (
    ROOT_ROTATION_AXES,
    ROOT_TRANSLATION_AXES,
    bind_like_poses,
    body_extent,
    clone_pose_map,
    identity_joint_keep_root_poses,
    copy_joints_keep_dest_root,
    seed_frame_from_inertial,
    seed_frame_pipeline_relative,
    insert_child_bone,
    load_glb,
    node_index_by_name,
    primitive_rest_positions,
    node_world_translation,
    first_skinned_primitive,
    joint_slot_for_node,
    normalize_skin_weights,
    rebind_vertices_to_joint,
    replace_positions,
    replace_triangle_indices,
    rest_sculpt_positions,
    rotate_bone_deg,
    rotate_bone_deg_within_limit,
    rotate_bone_deg_shared_within_limit,
    rotate_bone_model_axis_deg_shared,
    rotate_bilateral_pair_deg_shared,
    add_axis_angle_deg_shared_within_limit,
    rotate_root_deg,
    save_glb,
    scale_bone_rest_translation,
    set_root_rotation_deg,
    skinned_triangle_faces,
    translate_root,
    validate_skinned_glb,
    write_after_poses,
    write_camera_fit_from_candidate,
)
from sprite_bilateral_axes import (
    ANATOMICAL_AXES,
    SAGITTAL_MODEL_AXES,
    bone_anatomical_axes,
    bone_distal_directions,
    experiment_rest_worlds,
    local_delta_from_anatomical,
    model_bind_frame,
)
from sprite_pose_feasibility import (
    ARTICULATION_ACCEPTANCE_CLASSES,
    CLASS_BODY_INFEASIBLE_LENGTH,
    CLASS_BODY_INFEASIBLE_REST,
    CLASS_CAMERA_MISMATCH,
    CLASS_CAMERA_MISMATCH_UNRESOLVED,
    CLASS_CAMERA_RESOLVED_POSE_STALE,
    CLASS_FEASIBLE,
    CLASS_LBS_ILL_CONDITIONED,
    CLASS_MISSING_GEOMETRY,
    CLASS_MISSING_JOINT,
    CLASS_NEEDS_BLENDSHAPE_OR_REJECT,
    CLASS_NEEDS_GEOMETRY_AUTHORING,
    CLASS_PARTIAL_SURGERY_EXHAUSTED,
    CLASS_POSE_SEARCH_DEBT,
    CLASS_SURGERY_REJECTED,
    CLASS_TOPOLOGY_FUSED,
    CLASS_WRONG_OWNER,
    CLASS_WRONG_RIG_LANE,
    DEBT_PROBE_DEG,
    EPSILON_EXTRA,
    EPSILON_LEFTOVER,
    FEASIBLE_EXTRA,
    FEASIBLE_LEFTOVER,
    OCCUPANCY_REST_FILL_MAX_ASSIGN_PX,
    OCCUPANCY_REST_EXTRA_FACING_PX,
    MAX_ASSIGN_PX,
    MAX_BODY_ROUNDS,
    OCCUPANCY_AMBIGUOUS_RATIO,
    OCCUPANCY_UNIQUE_MIN_WEIGHT,
    OPERATOR_BY_CLASS,
    REST_LENGTH_SCALE_MAX,
    REST_LENGTH_SCALE_MIN,
    REST_LENGTH_EXTRA_SCALE,
    STRAIN_EXCLUSIVE_WEIGHT,
    STRAIN_TOLERANCE,
    STRAIN_ACCEPT_SLACK,
    accept_occupancy_rest,
    accept_surgery,
    agreed_rebind_vertices,
    argmax_round,
    assert_write_path,
    assign_leftover_pixels,
    classify_camera_from_init,
    classify_occupancy_body,
    clip_wide_mean,
    COMPARE_GIF_MAX_PANEL_PX,
    compare_gif_panel_size,
    fractions_from_masks,
    is_feasible,
    leftover_flip_is_blendshape,
    next_body_class,
    next_pending_class,
    occupancy_assigned_unique_bones,
    occupancy_fractions,
    OccupancyFractions,
    occupancy_rest_frame_index,
    occupancy_rest_modes,
    occupancy_vertex_deltas_px,
    unique_region_bones_from_pixels,
    unique_region_centroid_shrink_deltas,
    extra_on_vertex_mask,
    apply_rest_space_deltas,
    UNIQUE_REGION_VOLUME_SHRINK_FRAC,
    REST_SCULPT_MAX_BODY_LENGTHS,
    FLIGHT_YAW_CAP_DEG,
    FLIGHT_PRIOR,
    idle_band_from_payload,
    move_frame_positions,
    mask_bbox_aspect,
    flight_attitude_needed,
    leftover_primary_better,
    leftover_extend_scale,
    leftover_extend_target_name,
    flyer_camera_trap_search_bones,
    flyer_attitude_occupancy_allows,
    flyer_attitude_bones,
    flyer_spine_chain_bones,
    flyer_visual_body_chain,
    flyer_broad_stroke_search_bones,
    flyer_broad_stroke_ok,
    flyer_broad_stroke_frame_ok,
    flyer_phase_needs_right_seed,
    FLIGHT_BROAD_STROKE_MIN_SCORE,
    camera_axis_spans,
    side_view_ratio,
    horizontal_ratio,
    spine_camera_align,
    spine_is_side_view_flight,
    spine_level_score,
    flight_phase_sprite_axis,
    flight_phase_groups,
    flight_phase_representative_frames,
    frame_rest_source,
    bake_lbs_pose_to_rest,
    rotation_aligning_bases,
    rotate_points_about_pivot,
    spread_labeled_wing_vertices,
    symmetric_limb_destinations,
    symmetric_raised_wing_destinations,
    tpose_stretched_bridge_faces,
    ANATOMY_FIT_STAGES,
    ARCHITECTURE_ACCEPT_NAMES,
    SYMMETRIC_BONE_STEPS_DEG,
    TEMPORAL_FINE_STEPS_DEG,
    ASYMMETRIC_REST_LENGTH_SCALES,
    unique_joint_pose_count,
    insert_child_bone_name,
    leftover_symmetric_insert_parents,
    distal_owner_vertex_indices,
    anatomy_joints_xy,
    next_anatomy_fit_stage,
    symmetric_bone_fit_pairs,
    asymmetric_distal_bones,
    symmetric_bone_trial_better,
    substantial_occupancy_better,
    occupancy_collision_unacceptable,
    leftover_trial_illegal,
    temporal_coarse_combos,
    combo_pruned_by_collision_bounds,
    bind_chest_toward_camera,
    clip_wraps_temporally,
    pose_bidirectional_velocity_rms,
    clip_pose_velocity_rms,
    POSE_VELOCITY_EPS_DEG,
    POSE_VELOCITY_TRAP_EPS_DEG,
    flyer_frame_is_perch_trap,
    flyer_frame_is_flat_trap,
    flyer_frame_is_pitch_trap,
    flyer_frame_is_camera_trap,
    mask_principal_axis_xy,
    mask_body_core_axis_xy,
    spine_sprite_axis_score,
    spine_is_image_plane,
    belly_camera_align,
    belly_is_down,
    remove_axis_component,
    side_view_flight_better,
    FLIGHT_SPINE_STEPS_DEG,
    FLIGHT_BELLY_ROLL_STEPS_DEG,
    FLIGHT_PER_FRAME_SPINE_STEPS_DEG,
    PIPELINE_REFINE_SPINE_STEPS_DEG,
    FLIGHT_SPINE_RIGHT_MIN,
    FLIGHT_REST_RIGHT_MIN,
    FLIGHT_BELLY_DOWN_MIN,
    IDENTITY_SIDE_VIEW_ROUND_IDS,
    orbit_projection,
    vision_check_frame_positions,
    VISION_CHECK_FIXED_CAMERAS,
    VISION_CHECK_ORBIT_YAW_DEG,
    VISION_CHECK_QUESTIONS,
    pick_highest_facing_profile,
    sha256_file,
    work_tree_root,
)

ROOT = Path(__file__).resolve().parents[2]
ARTICULATION_CLIP = "idle_start_move_end"
BODY_ORDER = (
    CLASS_WRONG_OWNER,
    CLASS_BODY_INFEASIBLE_REST,
    CLASS_BODY_INFEASIBLE_LENGTH,
    CLASS_MISSING_JOINT,
)
OPERATOR_ALIASES = {
    "pose_search": CLASS_POSE_SEARCH_DEBT,
    "rest_sculpt": CLASS_BODY_INFEASIBLE_REST,
    "rest_length": CLASS_BODY_INFEASIBLE_LENGTH,
    "rebind": CLASS_WRONG_OWNER,
    "insert_bone": CLASS_MISSING_JOINT,
}


def _json_load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _json_dump(path: Path, payload: Mapping[str, Any]) -> Path:
    dest = assert_write_path(path, repo_root=ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def fused_push_clip_path(repo: Path, unit: str, clip: str) -> Path:
    return (
        repo
        / "artifacts"
        / "pose_picker_runs"
        / unit
        / clip
        / "fused_push_v24_pipeline"
        / "gpu_clip_result.json"
    )


def clip_resolution(payload: Mapping[str, Any]) -> tuple[int, int]:
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("clip payload has no config")
    resolution = config.get("resolution")
    if not isinstance(resolution, Sequence) or len(resolution) != 2:
        raise ValueError("clip payload has no raster resolution")
    width, height = (int(resolution[0]), int(resolution[1]))
    if width < 1 or height < 1:
        raise ValueError("clip raster resolution must be positive")
    return width, height


def source_mesh_from_init(init: Mapping[str, Any]) -> Path:
    mesh = init.get("sourceMesh")
    if not mesh:
        raise ValueError("profile init has no sourceMesh")
    path = Path(str(mesh))
    if not path.is_file():
        raise FileNotFoundError(f"source mesh is missing: {path}")
    return path


def rewrite_work_clip(
    payload: dict[str, Any],
    *,
    camera_fit: Path,
    init_path: Path | None,
    poses: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rewritten = dict(payload)
    camera = str(camera_fit.resolve())
    rewritten["cameraFitPath"] = camera
    config = rewritten.get("config")
    if isinstance(config, dict) and "cameraFitPath" in config:
        config = dict(config)
        config["cameraFitPath"] = camera
        rewritten["config"] = config
    if init_path is not None:
        report = str(init_path.resolve())
        rewritten["reportPath"] = report
        if isinstance(rewritten.get("config"), dict) and "reportPath" in rewritten["config"]:
            nested = dict(rewritten["config"])
            nested["reportPath"] = report
            rewritten["config"] = nested
    if poses is not None:
        rewritten["poses"] = {
            str(int(frame)): clone_pose_map({int(frame): pose})[int(frame)]
            for frame, pose in poses.items()
        }
        rewritten["poseUnits"] = "degrees"
    return rewritten


def sprite_paths(payload: Mapping[str, Any], frames: Sequence[int]) -> list[Path]:
    from cascade_clip_pose_tweak import target_frame_dir_from_clip

    directory = target_frame_dir_from_clip(payload)
    paths = [directory / f"{int(frame):02d}.png" for frame in frames]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"sprite frames missing: {missing}")
    return paths


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _fit_compare_panel(
    image: Image.Image,
    *,
    raster_size: tuple[int, int],
    panel_size: tuple[int, int],
) -> Image.Image:
    """Occupancy rasters integer-upscale. High-res DEF sprites letterbox into the panel.

    Crushing a ~1000px DEF plate down to the occupancy raster and then nearest-
    upscaling it is what made the sprite panel grainy.
    """
    rgba = image.convert("RGBA")
    raster_w, raster_h = int(raster_size[0]), int(raster_size[1])
    panel_w, panel_h = int(panel_size[0]), int(panel_size[1])
    if rgba.size == (raster_w, raster_h):
        return rgba.resize((panel_w, panel_h), Image.Resampling.NEAREST)
    fitted = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 255))
    scale = min(panel_w / max(rgba.width, 1), panel_h / max(rgba.height, 1))
    size = (max(1, int(round(rgba.width * scale))), max(1, int(round(rgba.height * scale))))
    resampling = Image.Resampling.NEAREST if scale >= 2.0 - 1e-9 else Image.Resampling.LANCZOS
    reduced = rgba.resize(size, resampling)
    fitted.paste(reduced, ((panel_w - size[0]) // 2, (panel_h - size[1]) // 2), reduced)
    return fitted


def write_compare_gif(
    *,
    sprite_paths: Sequence[Path],
    panel_a: Path,
    panel_b: Path,
    frames: Sequence[int],
    dest: Path,
    labels: tuple[str, str, str],
    caption: str,
    loops: int = 1,
    cell: tuple[int, int] | None = None,
) -> Path:
    dest = assert_write_path(dest, repo_root=ROOT)
    n = len(frames)
    if n < 1 or n != len(sprite_paths):
        raise ValueError("sprite_paths must match frames")
    with Image.open(panel_a / f"{int(frames[0]):02d}.png") as mesh_probe:
        raster_size = (int(mesh_probe.width), int(mesh_probe.height))
    if cell is None:
        width, height, scale = compare_gif_panel_size(raster_size[0], raster_size[1])
    else:
        width, height = int(cell[0]), int(cell[1])
        scale = max(1, width // max(raster_size[0], 1))
    font = _font(max(16, 12 + 3 * scale))
    header = 22 + 6 * scale
    footer = 32 + 8 * scale
    canvas_w = width * 3
    canvas_h = header + height + footer
    images: list[Image.Image] = []
    for _ in range(int(loops)):
        for index, frame in enumerate(frames):
            canvas = Image.new("RGB", (canvas_w, canvas_h), (12, 12, 16))
            draw = ImageDraw.Draw(canvas)
            before = panel_a / f"{int(frame):02d}.png"
            after = panel_b / f"{int(frame):02d}.png"
            missing = [path for path in (sprite_paths[index], before, after) if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"compare GIF missing stills: {missing}")
            cells = [Image.open(sprite_paths[index]), Image.open(before), Image.open(after)]
            for col, (label, image) in enumerate(zip(labels, cells)):
                x0 = col * width
                draw.rectangle([x0, 0, x0 + width - 1, header - 1], fill=(28, 28, 36))
                draw.text((x0 + 8, 6), label, fill=(230, 230, 235), font=font)
                fitted = _fit_compare_panel(
                    image,
                    raster_size=raster_size,
                    panel_size=(width, height),
                )
                canvas.paste(fitted.convert("RGB"), (x0, header))
            draw.rectangle([0, header + height, canvas_w, canvas_h], fill=(20, 20, 26))
            draw.text(
                (10, header + height + 8),
                f"unlit GPU  f{int(frame):02d}  {caption}",
                fill=(210, 210, 220),
                font=font,
            )
            images.append(canvas)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return dest


def _projection_from_experiment(experiment) -> dict[str, Any]:
    return {
        "right": experiment.camera_right.detach().cpu().numpy().astype(np.float64),
        "down": experiment.camera_down.detach().cpu().numpy().astype(np.float64),
        "up": experiment.camera_up.detach().cpu().numpy().astype(np.float64),
        "forward": experiment.camera_forward.detach().cpu().numpy().astype(np.float64),
        "offset": experiment.camera_offset.detach().cpu().numpy().astype(np.float64),
        "pxPerWorld": experiment.px_per_world.detach().cpu().numpy().astype(np.float64),
    }


def _apply_projection(experiment, camera: Mapping[str, Any]) -> None:
    import torch

    device = experiment.device
    experiment.camera_right = torch.as_tensor(np.asarray(camera["right"], dtype=np.float64), dtype=torch.float32, device=device)
    experiment.camera_down = torch.as_tensor(np.asarray(camera["down"], dtype=np.float64), dtype=torch.float32, device=device)
    experiment.camera_up = torch.as_tensor(np.asarray(camera["up"], dtype=np.float64), dtype=torch.float32, device=device)
    experiment.camera_forward = torch.as_tensor(
        np.asarray(camera["forward"], dtype=np.float64), dtype=torch.float32, device=device
    )
    experiment.camera_offset = torch.as_tensor(
        np.asarray(camera["offset"], dtype=np.float64), dtype=torch.float32, device=device
    )


def _raster_rgb_uint8(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> np.ndarray:
    import torch
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone, root_t, root_r = frozen_pose_tensors(experiment, poses)
    pos = int(frame_pos)
    with torch.no_grad():
        rgb, _alpha, _depth = experiment.exact_triangle_rgb(
            bone[pos : pos + 1],
            root_t[pos : pos + 1],
            root_r[pos : pos + 1],
            bone_mask=experiment.active_node_mask,
        )
    return np.rint(rgb[0].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0).astype(np.uint8)


def write_vision_check(
    *,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    dest: Path,
    sprites: Sequence[Path],
    world_up: Sequence[float] = (0.0, 1.0, 0.0),
) -> dict[str, Any]:
    """Raster the same posed mesh from extra cameras. Does not change occupancy leftover.

    Projection only. Root-rotation axes stay on the profile camera so stored poses
    keep their meaning. Proof is generated-artifact stills for a vision read.
    """
    dest = assert_write_path(dest, repo_root=ROOT)
    dest.mkdir(parents=True, exist_ok=True)
    prefix, suffix = idle_band_from_payload(payload)
    frames = [int(frame) for frame in experiment.frame_indices]
    positions = vision_check_frame_positions(len(frames), prefix, suffix)
    pivot = experiment.root_pivot.detach().cpu().numpy().astype(np.float64).reshape(3)
    seed = _projection_from_experiment(experiment)
    cameras: list[dict[str, Any]] = []
    stills: dict[str, dict[str, str]] = {}
    sheets: list[str] = []
    orbit_frames: list[Image.Image] = []
    orbit_gif = dest / "orbit.gif"
    orbit_frame = frames[positions[len(positions) // 2]] if positions else 0
    try:
        for spec in VISION_CHECK_FIXED_CAMERAS:
            camera = orbit_projection(
                right=seed["right"],
                down=seed["down"],
                offset=seed["offset"],
                px_per_world=seed["pxPerWorld"],
                pivot=pivot,
                yaw_deg=float(spec["yawDeg"]),
                pitch_deg=float(spec["pitchDeg"]),
                world_up=world_up,
            )
            cameras.append(
                {
                    "id": spec["id"],
                    "role": spec["role"],
                    "yawDeg": float(spec["yawDeg"]),
                    "pitchDeg": float(spec["pitchDeg"]),
                }
            )
            _apply_projection(experiment, camera)
            stills[str(spec["id"])] = {}
            for position in positions:
                frame = frames[int(position)]
                image = _raster_rgb_uint8(experiment, poses, int(position))
                path = dest / f"f{int(frame):02d}_{spec['id']}.png"
                Image.fromarray(image, "RGB").save(path, format="PNG", compress_level=0)
                stills[str(spec["id"])][f"{int(frame):02d}"] = str(path).replace("\\", "/")
        panel_w = int(experiment.config.resolution[0])
        panel_h = int(experiment.config.resolution[1])
        header = 22
        for position in positions:
            frame = frames[int(position)]
            canvas = Image.new(
                "RGB",
                (panel_w * (1 + len(VISION_CHECK_FIXED_CAMERAS)), header + panel_h),
                (12, 12, 16),
            )
            draw = ImageDraw.Draw(canvas)
            sprite_path = sprites[int(position)] if int(position) < len(sprites) else None
            if sprite_path is not None and Path(sprite_path).is_file():
                with Image.open(sprite_path) as sprite:
                    fitted = _fit_compare_panel(
                        sprite,
                        raster_size=(panel_w, panel_h),
                        panel_size=(panel_w, panel_h),
                    )
                canvas.paste(fitted.convert("RGB"), (0, header))
            draw.text((8, 4), f"sprite f{int(frame):02d}", fill=(230, 230, 235))
            for col, spec in enumerate(VISION_CHECK_FIXED_CAMERAS, start=1):
                x0 = col * panel_w
                draw.text((x0 + 8, 4), str(spec["id"]), fill=(230, 230, 235))
                with Image.open(dest / f"f{int(frame):02d}_{spec['id']}.png") as panel:
                    canvas.paste(panel.convert("RGB"), (x0, header))
            sheet = dest / f"sheet_f{int(frame):02d}.png"
            canvas.save(sheet, format="PNG", compress_level=0)
            sheets.append(str(sheet).replace("\\", "/"))
        orbit_pos = positions[len(positions) // 2]
        orbit_frame = frames[int(orbit_pos)]
        for yaw in VISION_CHECK_ORBIT_YAW_DEG:
            camera = orbit_projection(
                right=seed["right"],
                down=seed["down"],
                offset=seed["offset"],
                px_per_world=seed["pxPerWorld"],
                pivot=pivot,
                yaw_deg=float(yaw),
                pitch_deg=0.0,
                world_up=world_up,
            )
            _apply_projection(experiment, camera)
            rgb = _raster_rgb_uint8(experiment, poses, int(orbit_pos))
            labeled = Image.new("RGB", (panel_w, panel_h + header), (12, 12, 16))
            draw = ImageDraw.Draw(labeled)
            draw.text((8, 4), f"orbit yaw={int(yaw)} f{int(orbit_frame):02d}", fill=(230, 230, 235))
            labeled.paste(Image.fromarray(rgb, "RGB"), (0, header))
            orbit_frames.append(labeled)
            Image.fromarray(rgb, "RGB").save(
                dest / f"orbit_f{int(orbit_frame):02d}_yaw{int(yaw):03d}.png",
                format="PNG",
                compress_level=0,
            )
        orbit_frames[0].save(
            orbit_gif,
            save_all=True,
            append_images=orbit_frames[1:],
            duration=int(PREVIEW_GIF_FRAME_MS),
            loop=0,
            optimize=False,
        )
    finally:
        _apply_projection(experiment, seed)
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "notOccupancyGate": True,
        "rootBasisUnchanged": True,
        "framePositions": [int(index) for index in positions],
        "frameIndices": [int(frames[index]) for index in positions],
        "orbitFrame": int(orbit_frame),
        "cameras": cameras,
        "stills": stills,
        "sheets": sheets,
        "orbitGif": str(orbit_gif).replace("\\", "/"),
        "questions": list(VISION_CHECK_QUESTIONS),
        "answers": None,
        "worldUp": [float(value) for value in world_up],
        "note": (
            "Occupancy leftover is the profile camera only. Read the sheets and orbit GIF. "
            "A pose that matches the sprite from profile but is a card, a standing perch on "
            "fly frames, or belly-up from the top camera is overfit."
        ),
    }
    _json_dump(dest / "vision_check.json", report)
    return report


def world_up_from_camera_fit(camera_path: Path) -> tuple[float, float, float]:
    if not camera_path.is_file():
        return (0.0, 1.0, 0.0)
    data = _json_load(camera_path)
    metrics = data.get("profileMetrics") if isinstance(data.get("profileMetrics"), Mapping) else {}
    axis = metrics.get("worldUpAxis") if isinstance(metrics, Mapping) else None
    if isinstance(axis, Sequence) and len(axis) == 3:
        return (float(axis[0]), float(axis[1]), float(axis[2]))
    return (0.0, 1.0, 0.0)


def last_accepted_round_id(index: Mapping[str, Any]) -> str | None:
    last: str | None = None
    for row in index.get("trajectory") or []:
        if row.get("accepted"):
            last = str(row["roundId"])
    return last


def poses_from_after_file(path: Path) -> dict[int, dict[str, Any]]:
    loaded = _json_load(path)
    return clone_pose_map({int(frame): value for frame, value in loaded["poses"].items()})


def run_vision_check_work(*, unit: str, clip: str, round_id: str | None = None) -> dict[str, Any]:
    """Raster extra cameras for an existing accepted round. Occupancy leftover is unchanged."""
    work = assert_write_path(work_tree_root(ROOT) / unit / clip, repo_root=ROOT)
    index = _json_load(work / "index.json")
    chosen = str(round_id) if round_id else last_accepted_round_id(index)
    if not chosen:
        raise RuntimeError(f"no accepted round to vision-check under {work}")
    round_dir = work / chosen
    after_glb = round_dir / "after.glb"
    after_poses = round_dir / "after_poses.json"
    paths = resume_paths(work, index)
    mesh_path = after_glb if after_glb.is_file() else Path(paths["mesh_path"])
    clip_path = Path(paths["clip_path"])
    camera_path = Path(paths["camera_path"])
    experiment, payload, poses = load_preview_experiment(clip_path, mesh_path)
    if after_poses.is_file():
        poses = poses_from_after_file(after_poses)
    elif paths["poses_path"] is not None:
        poses = poses_from_after_file(Path(paths["poses_path"]))
    last_clip = round_dir / "gpu_clip_result.json"
    if last_clip.is_file():
        last_payload = _json_load(last_clip)
        cap = float((last_payload.get("config") or {}).get("root_rotation_camera_up_limit_deg") or 0.0)
        if cap + 1e-9 >= 90.0:
            raise_flyer_yaw_cap(experiment, payload)
    sprites = sprite_paths(payload, experiment.frame_indices)
    try:
        vision = write_vision_check(
            experiment=experiment,
            payload=payload,
            poses=poses,
            dest=round_dir / "vision_check",
            sprites=sprites,
            world_up=world_up_from_camera_fit(camera_path),
        )
    finally:
        close_experiment(experiment)
    report_path = round_dir / "round_report.json"
    if report_path.is_file():
        report = _json_load(report_path)
        report["visionCheck"] = {
            "orbitGif": vision["orbitGif"],
            "sheets": vision["sheets"],
            "report": str((round_dir / "vision_check" / "vision_check.json").resolve()).replace("\\", "/"),
        }
        _json_dump(report_path, report)
    return vision


def load_preview_experiment(clip_path: Path, mesh_path: Path):
    from gpu_post_pose_warp_repair import _experiment_from_clip

    experiment, payload, poses = _experiment_from_clip(
        clip_path=clip_path,
        mesh_glb=mesh_path,
        rescore=False,
    )
    require_pose_units_degrees(payload, source=str(clip_path))
    return experiment, payload, poses


def close_experiment(experiment: Any) -> None:
    if experiment is None:
        return
    del experiment
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def raster_bundle(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    png_dir: Path,
) -> dict[str, Any]:
    import torch
    from gpu_mesh_strain import build_backend_strain_table, strain_error_from_table
    from gpu_post_pose_warp_repair import frozen_pose_tensors
    from leftover_gravity import leftover_mask as leftover_pixels

    png_dir = assert_write_path(png_dir, repo_root=ROOT)
    png_dir.mkdir(parents=True, exist_ok=True)
    clip_poses = {int(frame): dict(poses[int(frame)]) for frame in experiment.frame_indices}
    bone_vectors, root_translation, root_rotation = frozen_pose_tensors(experiment, clip_poses)
    with torch.no_grad():
        rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )
    rows = []
    leftover_maps = []
    extra_maps = []
    for position, frame in enumerate(experiment.frame_indices):
        target = experiment.target_masks[position].detach().cpu().numpy()
        predicted = alpha[position].detach().cpu().numpy()
        frac = fractions_from_masks(target, predicted)
        rows.append(frac)
        leftover_maps.append(leftover_pixels(target, predicted, None, predicted_threshold=0.5))
        extra_maps.append(extra_predicted_mask(target, predicted, None, predicted_threshold=0.5))
        array = np.rint(rgb[position].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0).astype(np.uint8)
        Image.fromarray(array, "RGB").save(png_dir / f"{int(frame):02d}.png", format="PNG", compress_level=0)
    table = build_backend_strain_table(experiment, exclusive_weight=STRAIN_EXCLUSIVE_WEIGHT)
    with torch.no_grad():
        strain = strain_error_from_table(
            experiment,
            table,
            experiment._bounded_bone_vectors(bone_vectors),
            tolerance=STRAIN_TOLERANCE,
        )
    strain_mean = float(strain.mean().item())
    wide = clip_wide_mean(rows)
    return {
        "fractions": wide,
        "perFrame": rows,
        "leftoverMasks": leftover_maps,
        "extraMasks": extra_maps,
        "strain": strain_mean,
        "pngDir": png_dir,
        "resolution": [int(experiment.config.resolution[0]), int(experiment.config.resolution[1])],
        "boneVectors": bone_vectors,
        "rootTranslation": root_translation,
        "rootRotation": root_rotation,
    }


def copy_round_00(
    *,
    dest_dir: Path,
    live_clip: Path,
    live_camera: Path,
    live_init: Path,
    live_mesh: Path,
) -> dict[str, Any]:
    dest_dir = assert_write_path(dest_dir, repo_root=ROOT)
    dest_dir.mkdir(parents=True, exist_ok=True)
    camera_dest = dest_dir / "profile_camera_fit.json"
    init_dest = dest_dir / "profile_camera_initialization.json"
    mesh_dest = dest_dir / "source_mesh.glb"
    clip_dest = dest_dir / "gpu_clip_result.json"
    sources = {
        "clipJson": {"path": str(live_clip.resolve()).replace("\\", "/"), "sha256": sha256_file(live_clip)},
        "cameraFit": {"path": str(live_camera.resolve()).replace("\\", "/"), "sha256": sha256_file(live_camera)},
        "sourceMesh": {"path": str(live_mesh.resolve()).replace("\\", "/"), "sha256": sha256_file(live_mesh)},
        "profileInit": {"path": str(live_init.resolve()).replace("\\", "/"), "sha256": sha256_file(live_init)},
    }
    report_path = dest_dir / "round_report.json"
    if report_path.is_file():
        previous = _json_load(report_path)
        stored = previous.get("sourceHashes")
        if not isinstance(stored, dict):
            raise RuntimeError(f"{report_path} is missing sourceHashes")
        for key, row in sources.items():
            expected = (stored.get(key) or {}).get("sha256")
            if expected != row["sha256"]:
                raise RuntimeError(
                    f"round_00 hash mismatch for {key}: live {row['sha256']} stored {expected}"
                )
        return previous
    shutil.copy2(live_camera, camera_dest)
    shutil.copy2(live_init, init_dest)
    shutil.copy2(live_mesh, mesh_dest)
    payload = rewrite_work_clip(_json_load(live_clip), camera_fit=camera_dest, init_path=init_dest)
    require_pose_units_degrees(payload, source=str(live_clip))
    _json_dump(clip_dest, payload)
    copies = {
        "clipJson": {"path": str(clip_dest.resolve()).replace("\\", "/"), "sha256": sha256_file(clip_dest)},
        "cameraFit": {"path": str(camera_dest.resolve()).replace("\\", "/"), "sha256": sha256_file(camera_dest)},
        "sourceMesh": {"path": str(mesh_dest.resolve()).replace("\\", "/"), "sha256": sha256_file(mesh_dest)},
        "profileInit": {"path": str(init_dest.resolve()).replace("\\", "/"), "sha256": sha256_file(init_dest)},
    }
    report = {
        "roundId": "round_00",
        "accepted": True,
        "class": "original",
        "operator": "snapshot",
        "sourceHashes": sources,
        "copyHashes": copies,
        "singleClipOnly": True,
        "neverMasterGlb": True,
    }
    _json_dump(report_path, report)
    return report


def rig_provenance(mesh_path: Path) -> dict[str, Any]:
    return {
        "kind": "meshy_smartrig_copy",
        "sourceMesh": str(mesh_path.resolve()).replace("\\", "/"),
        "neverShip": True,
        "neverMasterGlb": True,
        "wrongRigLane": False,
        "note": "smartrig copies may be edited here; they still never become masterGlb",
    }


def joint_limit_deg(payload: Mapping[str, Any]) -> float:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    limit = float(config.get("joint_limit_deg", 150.0))
    if not math_finite_positive(limit):
        raise ValueError("joint_limit_deg must be positive")
    return limit


def math_finite_positive(value: float) -> bool:
    return bool(np.isfinite(value) and float(value) > 0.0)


def unique_and_assignment(
    experiment,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    width, height = (int(experiment.config.resolution[0]), int(experiment.config.resolution[1]))
    nodes = tuple(int(index) for index in experiment.active_node_indices)
    names = [str(experiment.node_names[index]) for index in nodes]
    frame_reports = []
    owners: list[dict[int, str]] = []
    leftover_near = False
    leftover_far = False
    unassigned_far = False
    geometry_near = False
    assigned_counts: dict[str, int] = {name: 0 for name in names}
    for position, frame in enumerate(experiment.frame_indices):
        weights = compute_search_bone_influence_maps(
            experiment,
            bundle["boneVectors"],
            bundle["rootTranslation"],
            bundle["rootRotation"],
            frame_position=int(position),
            node_indices=nodes,
            height=height,
            width=width,
        )
        lane = occupancy_lane_maps(
            weights,
            min_weight=OCCUPANCY_UNIQUE_MIN_WEIGHT,
            ambiguous_ratio=OCCUPANCY_AMBIGUOUS_RATIO,
        )
        joint_xy = project_all_joints(experiment, bundle, position)
        unique_distance = {
            name: bone_distance_map(
                lane.unique.get(name, np.zeros((height, width), dtype=bool)),
                joint_xy.get(name, (0.0, 0.0)),
                shape=(height, width),
            )
            for name in names
        }
        leftover = bundle["leftoverMasks"][position]
        assigned = assign_leftover_pixels(leftover, unique_distance, max_assign_px=MAX_ASSIGN_PX)
        leftover_near = leftover_near or any(count > 0 for count in assigned["counts"].values())
        leftover_far = leftover_far or assigned["unassigned"] > 0
        unassigned_far = leftover_far
        if assigned["leftoverPixels"] > 0:
            from scipy.ndimage import distance_transform_edt

            dist = distance_transform_edt(~np.asarray(leftover, dtype=bool))
            verts = posed_first_primitive(experiment, bundle, position)
            xs, ys = project_points(experiment, verts)
            for x, y in zip(xs, ys):
                px = int(round(float(x)))
                py = int(round(float(y)))
                if 0 <= px < width and 0 <= py < height and float(dist[py, px]) <= MAX_ASSIGN_PX:
                    geometry_near = True
                    break
        owners.append(vertex_owners_for_leftover(experiment, bundle, position, leftover, lane.unique, names))
        for name, count in assigned["counts"].items():
            assigned_counts[name] += int(count)
        frame_reports.append(
            {
                "frame": int(frame),
                "assigned": assigned["counts"],
                "unassigned": assigned["unassigned"],
            }
        )
    dominant = max(assigned_counts.items(), key=lambda item: (item[1], item[0]))[0] if assigned_counts else None
    unique_owner = dominant if dominant is not None and assigned_counts.get(dominant, 0) > 0 else None
    from sprite_pose_feasibility import aggregate_vertex_owners

    vote = aggregate_vertex_owners(owners) if any(owners) else {"agreed": {}, "disagreed": (), "vertexCount": 0}
    owner_agrees = len(vote["disagreed"]) == 0 and bool(vote["agreed"] or unique_owner)
    return {
        "leftoverNear": leftover_near,
        "leftoverFar": leftover_far,
        "unassignedFar": unassigned_far,
        "geometryProjectsNear": geometry_near,
        "uniqueOwner": unique_owner,
        "assignedCounts": assigned_counts,
        "ownerAgrees": owner_agrees,
        "ownerVote": {
            "agreedCount": int(len(vote["agreed"])),
            "disagreed": list(vote["disagreed"]),
            "vertexCount": int(vote["vertexCount"]),
        },
        "ownersPerFrame": owners,
        "frames": frame_reports,
    }


def project_all_joints(experiment, bundle: Mapping[str, Any], frame_position: int) -> dict[str, tuple[float, float]]:
    import torch

    bounded = experiment._bounded_bone_vectors(bundle["boneVectors"])
    worlds = experiment._forward_kinematics(
        bounded[frame_position : frame_position + 1],
        bone_mask=experiment.active_node_mask,
    )
    origins = worlds[0, :, :3, 3].unsqueeze(0)
    posed = experiment._root_transform(
        origins,
        bundle["rootTranslation"][frame_position : frame_position + 1],
        bundle["rootRotation"][frame_position : frame_position + 1],
    )[0]
    out: dict[str, tuple[float, float]] = {}
    for index, name in enumerate(experiment.node_names):
        sx, sy = project_points(experiment, posed[index : index + 1].detach().cpu().numpy())
        out[str(name)] = (float(sx[0]), float(sy[0]))
    _ = torch
    return out


def anatomy_catalog(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    catalog = payload.get("_anatomyCatalog")
    if not isinstance(catalog, Mapping) or not catalog.get("groups"):
        raise ValueError("sprite feasibility requires _anatomyCatalog on the work payload")
    return catalog


def attach_anatomy_catalog(payload: dict[str, Any], unit: str) -> dict[str, Any]:
    payload["_anatomyCatalog"] = load_unit_anatomy_catalog(unit)
    payload["_unit"] = str(unit)
    return payload


def posed_lbs_only(experiment, bundle: Mapping[str, Any], frame_position: int) -> np.ndarray:
    bounded = experiment._bounded_bone_vectors(bundle["boneVectors"])
    worlds = experiment._forward_kinematics(
        bounded[frame_position : frame_position + 1],
        bone_mask=experiment.active_node_mask,
    )
    primitive = experiment.primitives[0]
    verts = experiment._skinned_vertices(worlds, primitive)
    if isinstance(verts, tuple):
        verts = verts[0]
    return verts[0].detach().cpu().numpy()


def posed_first_primitive(experiment, bundle: Mapping[str, Any], frame_position: int) -> np.ndarray:
    import torch

    bounded = experiment._bounded_bone_vectors(bundle["boneVectors"])
    worlds = experiment._forward_kinematics(
        bounded[frame_position : frame_position + 1],
        bone_mask=experiment.active_node_mask,
    )
    primitive = experiment.primitives[0]
    verts = experiment._skinned_vertices(worlds, primitive)
    posed = experiment._root_transform(
        verts,
        bundle["rootTranslation"][frame_position : frame_position + 1],
        bundle["rootRotation"][frame_position : frame_position + 1],
    )[0]
    _ = torch
    return posed.detach().cpu().numpy()


def project_points(experiment, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    right = experiment.camera_right.detach().cpu().numpy()
    down = experiment.camera_down.detach().cpu().numpy()
    offset = experiment.camera_offset.detach().cpu().numpy()
    px = experiment.px_per_world.detach().cpu().numpy()
    sx = pts @ right * float(px[0]) + float(offset[0])
    sy = pts @ down * float(px[1]) + float(offset[1])
    return sx, sy


def vertex_owners_for_leftover(
    experiment,
    bundle: Mapping[str, Any],
    frame_position: int,
    leftover: np.ndarray,
    unique: Mapping[str, np.ndarray],
    names: Sequence[str],
) -> dict[int, str]:
    height, width = leftover.shape
    verts = posed_first_primitive(experiment, bundle, frame_position)
    xs, ys = project_points(experiment, verts)
    primitive = experiment.primitives[0]
    joints = primitive.joints.detach().cpu().numpy().astype(np.int64)
    weights = primitive.normalized_weights.detach().cpu().numpy()
    skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
    owners: dict[int, str] = {}
    for vertex, (x, y) in enumerate(zip(xs, ys)):
        px = int(round(float(x)))
        py = int(round(float(y)))
        if not (0 <= px < width and 0 <= py < height):
            continue
        if not leftover[py, px]:
            continue
        named = None
        for name in names:
            mask = unique.get(name)
            if mask is not None and mask[py, px]:
                named = str(name)
                break
        if named is None:
            slot = int(np.argmax(weights[vertex]))
            node = int(skin_to_node[int(joints[vertex, slot])])
            named = str(experiment.node_names[node])
        owners[int(vertex)] = named
    return owners


def vertex_dominant_owner_names(experiment) -> list[str]:
    primitive = experiment.primitives[0]
    joints = primitive.joints.detach().cpu().numpy().astype(np.int64)
    weights = primitive.normalized_weights.detach().cpu().numpy()
    skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
    names: list[str] = []
    for vertex in range(int(weights.shape[0])):
        slot = int(np.argmax(weights[vertex]))
        node = int(skin_to_node[int(joints[vertex, slot])])
        names.append(str(experiment.node_names[node]))
    return names


def occupancy_unique_owner_allow(
    owner_names: Sequence[str],
    allowed_bones: Sequence[str],
) -> np.ndarray:
    allowed = {str(name) for name in allowed_bones}
    if not allowed:
        raise ValueError("unique-region occupancy rest needs at least one bone")
    return np.asarray([str(name) in allowed for name in owner_names], dtype=bool)


def debt_helps(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    bundle: Mapping[str, Any],
    occupancy: Mapping[str, Any],
) -> bool:
    leftover_sizes = [int(np.count_nonzero(mask)) for mask in bundle["leftoverMasks"]]
    if max(leftover_sizes) < 1:
        return False
    frame_pos = int(np.argmax(leftover_sizes))
    frame = int(experiment.frame_indices[frame_pos])
    ranked = sorted(occupancy["assignedCounts"].items(), key=lambda item: item[1], reverse=True)
    bones = [name for name, count in ranked[:2] if count > 0]
    if not bones:
        bones = [str(experiment.node_names[int(index)]) for index in experiment.active_node_indices[:2]]
    before = occupancy_fractions(
        bundle["leftoverMasks"][frame_pos],
        bundle["extraMasks"][frame_pos],
        experiment.target_masks[frame_pos].detach().cpu().numpy() > 0.5,
    )
    limit = joint_limit_deg(payload)
    import torch
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    for bone in bones:
        for axis in ("x", "y", "z"):
            for sign in (-1.0, 1.0):
                trial = clone_pose_map(poses)
                try:
                    rotate_bone_deg(
                        trial,
                        joint=bone,
                        frames=(frame,),
                        axis=axis,
                        delta_deg=sign * DEBT_PROBE_DEG,
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, trial)
                with torch.no_grad():
                    _rgb, alpha, _depth = experiment.exact_triangle_rgb(
                        bone_vectors[frame_pos : frame_pos + 1],
                        root_t[frame_pos : frame_pos + 1],
                        root_r[frame_pos : frame_pos + 1],
                        bone_mask=experiment.active_node_mask,
                    )
                target = experiment.target_masks[frame_pos].detach().cpu().numpy()
                after = fractions_from_masks(target, alpha[0].detach().cpu().numpy())
                if (before.leftover - after.leftover) >= EPSILON_LEFTOVER:
                    return True
    return False


def recover_root_and_lbs(experiment, bundle: Mapping[str, Any], frame_position: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import torch

    primitive = experiment.primitives[0]
    bounded = experiment._bounded_bone_vectors(bundle["boneVectors"])
    worlds = experiment._forward_kinematics(
        bounded[frame_position : frame_position + 1],
        bone_mask=experiment.active_node_mask,
    )
    joint_matrices = torch.matmul(worlds[:, primitive.skin_joints], primitive.inverse_bind.unsqueeze(0))[0]
    node_world = worlds[0, int(primitive.node)].detach().cpu().numpy()
    jm = joint_matrices.detach().cpu().numpy()
    joints = primitive.joints.detach().cpu().numpy().astype(np.int64)
    weights = primitive.normalized_weights.detach().cpu().numpy()
    rest = primitive.positions.detach().cpu().numpy()
    blends = np.zeros((rest.shape[0], 4, 4), dtype=np.float64)
    for vertex in range(rest.shape[0]):
        mixed = np.zeros((4, 4), dtype=np.float64)
        for slot in range(joints.shape[1]):
            mixed += float(weights[vertex, slot]) * jm[int(joints[vertex, slot])]
        blends[vertex] = node_world @ mixed
    pivot = experiment.root_pivot.detach().cpu().numpy().reshape(3)
    basis = np.stack(
        [
            pivot,
            pivot + np.asarray((1.0, 0.0, 0.0)),
            pivot + np.asarray((0.0, 1.0, 0.0)),
            pivot + np.asarray((0.0, 0.0, 1.0)),
        ]
    )
    tensor = torch.as_tensor(basis, dtype=torch.float32, device=experiment.device).unsqueeze(0)
    posed = experiment._root_transform(
        tensor,
        bundle["rootTranslation"][frame_position : frame_position + 1],
        bundle["rootRotation"][frame_position : frame_position + 1],
    )[0].detach().cpu().numpy()
    origin = posed[0]
    rotation = np.stack((posed[1] - origin, posed[2] - origin, posed[3] - origin), axis=1)
    return rest, blends, rotation


def coil_detect_overlay(mesh_path: Path, dest_dir: Path) -> dict[str, Any]:
    dest_dir = assert_write_path(dest_dir, repo_root=ROOT)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        from coil_weld_repair import detect_coil_weld_clusters
        from gpu_cascade_delivery import _read_glb
        from sprite_body_surgery import _accessor_array, first_skinned_primitive
    except Exception as exc:
        report = {"ok": False, "error": str(exc), "class": None}
        _json_dump(dest_dir / "coil_weld_detect.json", report)
        return report
    doc, blob = _read_glb(mesh_path)
    try:
        _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
        if "indices" not in prim:
            raise ValueError("coil-weld detect needs triangle indices")
        positions = _accessor_array(doc, blob, int(prim["attributes"]["POSITION"]))
        faces = _accessor_array(doc, blob, int(prim["indices"])).astype(np.int64).reshape(-1, 3)
        result = detect_coil_weld_clusters(positions.astype(np.float64), faces)
    except Exception as exc:
        report = {"ok": False, "error": str(exc), "class": None, "applied": False}
        _json_dump(dest_dir / "coil_weld_detect.json", report)
        return report
    count = int(len(result.clusters))
    payload = result.to_dict()
    payload.update(
        {
            "ok": True,
            "class": CLASS_TOPOLOGY_FUSED if count else None,
            "applied": False,
            "note": "detect overlay only; coil-weld apply is not an auto operator",
        }
    )
    _json_dump(dest_dir / "coil_weld_detect.json", payload)
    return payload


def pose_search_schedule(frame_count: int, *, fine: bool = False) -> dict[str, Any]:
    if fine:
        return {
            "bones": 12 if int(frame_count) <= 8 else 6,
            "sharedBoneSteps": (-12.0, -6.0, 6.0, 12.0),
            "perFrameSteps": (-8.0, -4.0, 4.0, 8.0),
            "rootSteps": (-20.0, -10.0, -5.0, 5.0, 10.0, 20.0),
            "transSteps": (-0.04, -0.02, 0.02, 0.04),
            "tryBind": False,
            "perFrameAll": int(frame_count) <= 8,
        }
    if int(frame_count) <= 8:
        return {
            "bones": 8,
            "sharedBoneSteps": (-30.0, -15.0, 15.0, 30.0),
            "perFrameSteps": (-25.0, -12.5, 12.5, 25.0),
            "rootSteps": (-60.0, -45.0, -30.0, -15.0, -7.5, 7.5, 15.0, 30.0, 45.0, 60.0),
            "transSteps": (-0.08, -0.04, -0.02, 0.02, 0.04, 0.08),
            "tryBind": True,
            "perFrameAll": True,
        }
    return {
        "bones": 4,
        "sharedBoneSteps": (-30.0, -15.0, 15.0, 30.0),
        "perFrameSteps": (-30.0, -15.0, 15.0, 30.0),
        "rootSteps": (-45.0, -30.0, -15.0, 15.0, 30.0, 45.0),
        "transSteps": (-0.06, -0.03, 0.03, 0.06),
        "tryBind": False,
        "perFrameAll": False,
    }


def root_rotation_limit_deg(payload: Mapping[str, Any], axis: str) -> float:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    if str(axis) == "camera_up":
        return float(config.get("root_rotation_camera_up_limit_deg", 90.0))
    return 45.0


def clip_leftover_extra(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    positions: Sequence[int] | None = None,
):
    import torch
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    if positions is None:
        index_list = list(range(len(experiment.frame_indices)))
    else:
        index_list = [int(index) for index in positions]
        if not index_list:
            raise ValueError("clip leftover extra needs at least one frame position")
        bone_vectors = bone_vectors[index_list]
        root_t = root_t[index_list]
        root_r = root_r[index_list]
    with torch.no_grad():
        _rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_t,
            root_r,
            bone_mask=experiment.active_node_mask,
        )
    rows = []
    for row_i, position in enumerate(index_list):
        target = experiment.target_masks[position].detach().cpu().numpy()
        rows.append(fractions_from_masks(target, alpha[row_i].detach().cpu().numpy()))
    return clip_wide_mean(rows)


def frame_occupancy_view(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> tuple[Any, float]:
    import torch
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    with torch.no_grad():
        _rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors[frame_pos : frame_pos + 1],
            root_t[frame_pos : frame_pos + 1],
            root_r[frame_pos : frame_pos + 1],
            bone_mask=experiment.active_node_mask,
        )
    predicted = alpha[0].detach().cpu().numpy()
    target = experiment.target_masks[frame_pos].detach().cpu().numpy()
    return fractions_from_masks(target, predicted), mask_bbox_aspect(predicted > 0.5)


def frame_leftover_extra(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int):
    fractions, _aspect = frame_occupancy_view(experiment, poses, frame_pos)
    return fractions


def frame_occupancy_strain(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    frame_pos: int,
    strain_table: Mapping[str, Any],
) -> tuple[Any, float]:
    """One-frame leftover/extra plus mixed-edge LBS strain. Occupancy cannot see melt."""
    import torch
    from gpu_mesh_strain import strain_error_from_table
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    with torch.no_grad():
        _rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors[frame_pos : frame_pos + 1],
            root_t[frame_pos : frame_pos + 1],
            root_r[frame_pos : frame_pos + 1],
            bone_mask=experiment.active_node_mask,
        )
        strain = strain_error_from_table(
            experiment,
            strain_table,
            experiment._bounded_bone_vectors(bone_vectors)[frame_pos : frame_pos + 1],
            tolerance=STRAIN_TOLERANCE,
        )
    predicted = alpha[0].detach().cpu().numpy()
    target = experiment.target_masks[frame_pos].detach().cpu().numpy()
    return fractions_from_masks(target, predicted), float(strain[0].item())


def frame_occupancy_aspect(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> float:
    _fractions, aspect = frame_occupancy_view(experiment, poses, frame_pos)
    return aspect


def frame_camera_spans(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> dict[str, float]:
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    bundle = {
        "boneVectors": bone_vectors,
        "rootTranslation": root_t,
        "rootRotation": root_r,
    }
    verts = posed_first_primitive(experiment, bundle, int(frame_pos))
    return camera_axis_spans(
        verts,
        experiment.camera_right.detach().cpu().numpy(),
        experiment.camera_down.detach().cpu().numpy(),
        experiment.camera_forward.detach().cpu().numpy(),
    )


def posed_joint_worlds(experiment, poses: Mapping[int, Mapping[str, Any]], frame_pos: int) -> dict[str, np.ndarray]:
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    bounded = experiment._bounded_bone_vectors(bone_vectors)
    worlds = experiment._forward_kinematics(
        bounded[int(frame_pos) : int(frame_pos) + 1],
        bone_mask=experiment.active_node_mask,
    )
    origins = worlds[0, :, :3, 3].unsqueeze(0)
    posed = experiment._root_transform(
        origins,
        root_t[int(frame_pos) : int(frame_pos) + 1],
        root_r[int(frame_pos) : int(frame_pos) + 1],
    )[0]
    out: dict[str, np.ndarray] = {}
    for index, name in enumerate(experiment.node_names):
        out[str(name)] = posed[index].detach().cpu().numpy().astype(np.float64)
    return out


def frame_spine_align(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    frame_pos: int,
    chain: Sequence[str],
) -> dict[str, float]:
    worlds = posed_joint_worlds(experiment, poses, int(frame_pos))
    points = []
    for name in chain:
        if name not in worlds:
            raise ValueError(f"spine chain missing joint {name}")
        points.append(worlds[str(name)])
    return spine_camera_align(
        np.asarray(points, dtype=np.float64),
        experiment.camera_right.detach().cpu().numpy(),
        experiment.camera_down.detach().cpu().numpy(),
        experiment.camera_forward.detach().cpu().numpy(),
    )


def bind_joint_origins(experiment) -> dict[str, np.ndarray]:
    import torch

    zero = torch.zeros(
        (1, len(experiment.node_names), 3),
        dtype=torch.float32,
        device=experiment.device,
    )
    worlds = experiment._forward_kinematics(zero, bone_mask=experiment.active_node_mask)
    origins = worlds[0, :, :3, 3].detach().cpu().numpy()
    return {str(name): origins[index].astype(np.float64) for index, name in enumerate(experiment.node_names)}


def rest_ventral_mask(experiment, chain: Sequence[str]) -> np.ndarray:
    import torch

    zero = torch.zeros(
        (1, len(experiment.node_names), 3),
        dtype=torch.float32,
        device=experiment.device,
    )
    worlds = experiment._forward_kinematics(zero, bone_mask=experiment.active_node_mask)
    primitive = experiment.primitives[0]
    skinned = experiment._skinned_vertices(worlds, primitive)
    if isinstance(skinned, tuple):
        skinned = skinned[0]
    bind_np = skinned.detach().cpu().numpy().astype(np.float64)
    bind_verts = bind_np[0] if bind_np.ndim == 3 else bind_np
    origins = bind_joint_origins(experiment)
    missing = [name for name in chain if name not in origins]
    if missing:
        raise ValueError(f"ventral mask missing joints {missing}")
    spine_mid = np.mean([origins[str(name)] for name in chain], axis=0)
    return bind_verts[:, 1] < float(spine_mid[1])


def frame_belly_align(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    frame_pos: int,
    chain: Sequence[str],
    ventral_mask: np.ndarray,
) -> dict[str, float]:
    from gpu_post_pose_warp_repair import frozen_pose_tensors

    bone_vectors, root_t, root_r = frozen_pose_tensors(experiment, poses)
    bundle = {
        "boneVectors": bone_vectors,
        "rootTranslation": root_t,
        "rootRotation": root_r,
    }
    posed = posed_first_primitive(experiment, bundle, int(frame_pos))
    mask = np.asarray(ventral_mask, dtype=bool)
    if mask.shape[0] != posed.shape[0]:
        raise ValueError("ventral mask does not match posed vertex count")
    if int(np.count_nonzero(mask)) < 8:
        raise ValueError("ventral mask selected too few vertices")
    worlds = posed_joint_worlds(experiment, poses, int(frame_pos))
    points = [worlds[str(name)] for name in chain]
    spine_mid = np.mean(np.asarray(points, dtype=np.float64), axis=0)
    spine_axis = np.asarray(points[-1], dtype=np.float64) - np.asarray(points[0], dtype=np.float64)
    ventral = np.mean(posed[mask], axis=0) - spine_mid
    offset = remove_axis_component(ventral, spine_axis)
    return belly_camera_align(
        offset,
        experiment.camera_down.detach().cpu().numpy(),
        experiment.camera_forward.detach().cpu().numpy(),
    )


def flight_ventral_mask(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    chain: Sequence[str],
) -> np.ndarray:
    mask = rest_ventral_mask(experiment, chain)
    bind_poses = bind_like_poses(poses, [int(frame) for frame in experiment.frame_indices])
    bind_belly = frame_belly_align(experiment, bind_poses, 0, chain, mask)
    if float(bind_belly["down"]) < 0.0:
        return np.logical_not(mask)
    return mask


def identity_side_view_seed_path(work_clip: Path) -> Path | None:
    clip_dir = Path(work_clip).resolve().parent.parent
    for round_id in IDENTITY_SIDE_VIEW_ROUND_IDS:
        candidate = clip_dir / str(round_id) / "after_poses.json"
        if candidate.is_file():
            return candidate
    return None


def _keep_fractions(before, trial) -> bool:
    leftover_drop = float(before.leftover) - float(trial.leftover)
    extra_growth = float(trial.extra) - float(before.extra)
    return leftover_drop > 1e-9 and extra_growth <= EPSILON_EXTRA + 1e-12


def _keep_occupancy_net(before, trial) -> bool:
    leftover_drop = float(before.leftover) - float(trial.leftover)
    extra_drop = float(before.extra) - float(trial.extra)
    leftover_growth = float(trial.leftover) - float(before.leftover)
    return leftover_drop + extra_drop > 1e-9 and leftover_growth <= EPSILON_LEFTOVER + 1e-12


def raise_flyer_yaw_cap(experiment, payload: dict[str, Any]) -> None:
    """Allow 90° camera_up. Cascade's 45° yaw cap cannot represent side-profile flight."""
    experiment.config = replace(
        experiment.config,
        root_rotation_camera_up_limit_deg=float(FLIGHT_YAW_CAP_DEG),
    )
    config = payload.get("config")
    if isinstance(config, dict):
        nested = dict(config)
        nested["root_rotation_camera_up_limit_deg"] = float(FLIGHT_YAW_CAP_DEG)
        payload["config"] = nested


def flyer_flight_attitude_search(
    experiment,
    payload: dict[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Pitch move frames into landscape flight. Idle perch frames stay upright.

    Occupancy leftover of a perched bone pose at 90° is worse than a standing
    overlap of the fly plate. Apply the attitude as a prior, then re-aim bones.
    """
    frames = [int(frame) for frame in experiment.frame_indices]
    prefix, suffix = idle_band_from_payload(payload)
    move_pos = move_frame_positions(len(frames), prefix, suffix)
    masks = [
        experiment.target_masks[index].detach().cpu().numpy() > 0.5 for index in range(len(frames))
    ]
    idle_pos = list(range(0, prefix)) + list(range(len(frames) - suffix, len(frames)))
    idle_aspect = (
        float(np.mean([mask_bbox_aspect(masks[index]) for index in idle_pos])) if idle_pos else 0.0
    )
    move_aspect = (
        float(np.mean([mask_bbox_aspect(masks[index]) for index in move_pos])) if move_pos else 0.0
    )
    details: dict[str, Any] = {
        "prefix": int(prefix),
        "suffix": int(suffix),
        "movePositions": [int(index) for index in move_pos],
        "idleAspect": idle_aspect,
        "moveAspect": move_aspect,
        "needed": False,
        "applied": False,
        "prior": FLIGHT_PRIOR,
    }
    if not move_pos or not flight_attitude_needed(masks, prefix, suffix):
        details["skipped"] = "sprite_aspect_not_flight" if move_pos else "no_move_frames"
        return clone_pose_map(poses), details
    details["needed"] = True
    raise_flyer_yaw_cap(experiment, payload)
    details["yawCapDeg"] = float(FLIGHT_YAW_CAP_DEG)
    move_frames = [frames[index] for index in move_pos]
    seed = clone_pose_map(poses)
    seed_frac = clip_leftover_extra(experiment, seed, positions=move_pos)
    details["leftoverBefore"] = float(seed_frac.leftover)
    details["extraBefore"] = float(seed_frac.extra)
    probe_pos = int(move_pos[len(move_pos) // 2])
    sprite_probe_aspect = mask_bbox_aspect(masks[probe_pos])
    pitched = False
    for frame in move_frames:
        rot = (seed.get(int(frame)) or {}).get("__motion_root_rotation__") or {}
        if abs(float(rot.get("camera_right") or 0.0)) > 45.0 or abs(float(rot.get("camera_up") or 0.0)) > 45.0:
            pitched = True
    best = clone_pose_map(seed)
    best_frac = clip_leftover_extra(experiment, best, positions=move_pos)
    details.update(
        {
            "applied": True,
            "prior": FLIGHT_PRIOR,
            "preservePipelinePoses": True,
            "pitchDeg": 0.0,
            "rollDeg": 0.0,
            "yawDeg": 0.0,
            "pitchedRootCleared": False,
            "reseatedFromIdle": False,
            "zeroMoveRoot": False,
            "pipelineRootLeftPitched": bool(pitched),
            "spriteProbeAspect": float(sprite_probe_aspect),
            "probePosition": probe_pos,
            "leftoverAfter": float(best_frac.leftover),
            "extraAfter": float(best_frac.extra),
        }
    )
    return best, details


def flyer_spine_attitude_search(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    probe_pos: int,
    sprite_aspect: float,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """90° image-plane spine pitch on move frames. Idle perch stays.

    Occupancy leftover cannot tell a belly-on dive from side-view flight.
    Keep by sprite-aspect match with a side-view span veto.
    """
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_spine_chain_bones(names, parents)
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    limit = joint_limit_deg(payload)
    best = clone_pose_map(poses)
    best_frac, best_aspect = frame_occupancy_view(experiment, best, int(probe_pos))
    best_spans = frame_camera_spans(experiment, best, int(probe_pos))
    best_align = frame_spine_align(experiment, best, int(probe_pos), measure)
    kept = 0
    for bone in spine:
        for axis in ("x", "y", "z"):
            for step in FLIGHT_SPINE_STEPS_DEG:
                trial = clone_pose_map(best)
                try:
                    rotate_bone_deg(
                        trial,
                        joint=bone,
                        frames=[int(frame) for frame in move_frames],
                        axis=axis,
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                trial_frac, trial_aspect = frame_occupancy_view(experiment, trial, int(probe_pos))
                trial_spans = frame_camera_spans(experiment, trial, int(probe_pos))
                trial_align = frame_spine_align(experiment, trial, int(probe_pos), measure)
                if float(trial_align["forward"]) > float(best_align["forward"]) + 0.05:
                    continue
                if float(trial_align["right"]) <= float(best_align["right"]) + 1e-9:
                    continue
                best = trial
                best_frac = trial_frac
                best_aspect = trial_aspect
                best_spans = trial_spans
                best_align = trial_align
                kept += 1
    return best, {
        "spineBones": spine,
        "kept": kept,
        "probeAspect": float(best_aspect),
        "spriteAspect": float(sprite_aspect),
        "sideViewRatio": side_view_ratio(best_spans),
        "horizontalRatio": horizontal_ratio(best_spans),
        "spineAlign": best_align,
        "moveFramesOnly": True,
    }


def flyer_belly_roll_search(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    probe_pos: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Roll the torso around a horizontal spine so the belly faces the ground.

    Spine-along-screen-right still leaves a belly-on card if the mesh is rolled
    around that axis. Occupancy leftover cannot see that roll.
    """
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_spine_chain_bones(names, parents)
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    limit = joint_limit_deg(payload)
    best = clone_pose_map(poses)
    best_align = frame_spine_align(experiment, best, int(probe_pos), measure)
    best_belly = frame_belly_align(experiment, best, int(probe_pos), measure, ventral_mask)
    kept = 0
    for bone in spine:
        for axis in ("x", "y", "z"):
            for step in FLIGHT_BELLY_ROLL_STEPS_DEG:
                trial = clone_pose_map(best)
                try:
                    rotate_bone_deg(
                        trial,
                        joint=bone,
                        frames=[int(frame) for frame in move_frames],
                        axis=axis,
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                trial_align = frame_spine_align(experiment, trial, int(probe_pos), measure)
                if not spine_is_side_view_flight(trial_align):
                    continue
                if float(trial_align["right"]) + 0.05 < float(best_align["right"]):
                    continue
                trial_belly = frame_belly_align(experiment, trial, int(probe_pos), measure, ventral_mask)
                if float(trial_belly["down"]) <= float(best_belly["down"]) + 1e-9:
                    continue
                if abs(float(trial_belly["forward"])) > abs(float(best_belly["forward"])) + 0.05:
                    continue
                best = trial
                best_align = trial_align
                best_belly = trial_belly
                kept += 1
    return best, {
        "spineBones": spine,
        "kept": kept,
        "spineAlign": best_align,
        "bellyAlign": best_belly,
        "bellyDown": belly_is_down(best_belly),
        "moveFramesOnly": True,
    }


def copy_spine_pose(
    poses: dict[int, dict[str, Any]],
    dest_frame: int,
    src_frame: int,
    bones: Sequence[str],
) -> None:
    src = poses[int(src_frame)]
    dest = poses[int(dest_frame)]
    for bone in bones:
        if bone not in src:
            continue
        dest[str(bone)] = {key: float(src[str(bone)][key]) for key in ("x", "y", "z")}


def flyer_attitude_donor_frame(
    previous_rows: Sequence[Mapping[str, Any]],
    *,
    perch_trap: bool,
    flat_trap: bool,
) -> int | None:
    """Copy a nearby honest fly pose onto a trapped frame.

    Perch copies the last previous side-view fly pose. Flat landing copies the
    previous climb/flare pose, never the flattest cruise.
    """
    donor = None
    donor_score = None
    for row in previous_rows:
        align = row.get("spineAlign") or {}
        if not spine_is_image_plane(align):
            continue
        right = float(align["right"])
        down = abs(float(align["down"]))
        if right < 0.5:
            continue
        frame = int(row["frame"])
        if perch_trap and down <= 0.85:
            donor = frame
        elif flat_trap and 0.35 <= down <= 0.85:
            if donor_score is None or down > donor_score:
                donor = frame
                donor_score = down
    return donor


def skeleton_velocity_allows(
    best_poses: Mapping[int, Mapping[str, Any]],
    trial_poses: Mapping[int, Mapping[str, Any]],
    *,
    frame: int,
    frames: Sequence[int],
    bones: Sequence[str],
    wrap: bool,
    trap: bool,
) -> bool:
    best_vel = pose_bidirectional_velocity_rms(
        best_poses, frame=int(frame), frames=frames, bones=bones, wrap=wrap
    )
    trial_vel = pose_bidirectional_velocity_rms(
        trial_poses, frame=int(frame), frames=frames, bones=bones, wrap=wrap
    )
    cap = float(POSE_VELOCITY_TRAP_EPS_DEG if trap else POSE_VELOCITY_EPS_DEG)
    return trial_vel <= best_vel + cap + 1e-9


def previous_rows_same_phase(
    previous_rows: Sequence[Mapping[str, Any]],
    *,
    frame: int,
    frame_phase: Mapping[int, str],
) -> list[dict[str, Any]]:
    """Trap seeds stay inside one flight phase. Takeoff must not overwrite landing."""
    phase = frame_phase.get(int(frame))
    if phase is None:
        return []
    return [
        dict(row)
        for row in previous_rows
        if frame_phase.get(int(row["frame"])) == phase
    ]


def seed_trapped_flyer_frames(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    move_pos: Sequence[int],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_spine_chain_bones(names, parents)
    seed_bones = ["Bone_000", *spine] if "Bone_000" in names else list(spine)
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    prefix, suffix = idle_band_from_payload(payload)
    frame_count = len(list(experiment.frame_indices))
    groups = flight_phase_groups(
        move_frames, prefix=prefix, suffix=suffix, frame_count=frame_count
    )
    frame_phase = {
        int(frame): str(phase)
        for phase, group_frames in groups.items()
        for frame in group_frames
    }
    best = clone_pose_map(poses)
    seeded: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] = []
    for frame_pos, frame in zip(move_pos, move_frames):
        frame_i = int(frame)
        pos_i = int(frame_pos)
        sprite_axis = flight_phase_sprite_axis(
            frame_i, prefix=prefix, suffix=suffix, frame_count=frame_count
        )
        align = frame_spine_align(experiment, best, pos_i, measure)
        perch_trap = flyer_frame_is_perch_trap(align, sprite_axis)
        flat_trap = flyer_frame_is_flat_trap(align, sprite_axis)
        donor = None
        if perch_trap or flat_trap:
            donor = flyer_attitude_donor_frame(
                previous_rows_same_phase(previous, frame=frame_i, frame_phase=frame_phase),
                perch_trap=perch_trap,
                flat_trap=flat_trap,
            )
            if donor is not None:
                copy_spine_pose(best, frame_i, donor, seed_bones)
                align = frame_spine_align(experiment, best, pos_i, measure)
                seeded.append(
                    {
                        "frame": frame_i,
                        "seededFrom": donor,
                        "bones": list(seed_bones),
                        "phase": frame_phase.get(frame_i),
                    }
                )
        previous.append({"frame": frame_i, "spineAlign": align})
    return best, {
        "spineBones": spine,
        "seedBones": list(seed_bones),
        "seeded": seeded,
        "sharedSkeleton": True,
        "samePhaseOnly": True,
    }


def copy_phase_skeleton(
    poses: dict[int, dict[str, Any]],
    groups: Mapping[str, Sequence[int]],
    bones: Sequence[str],
) -> list[dict[str, Any]]:
    """One skeleton pose per flight phase. Neighbor frames are copies, not new meshes."""
    copied: list[dict[str, Any]] = []
    bone_list = [str(bone) for bone in bones]
    if not bone_list:
        return copied
    for phase, group_frames in groups.items():
        frames = [int(frame) for frame in group_frames]
        if len(frames) < 2:
            continue
        if phase == "takeoff":
            src = frames[0]
        elif phase == "landing":
            src = frames[-1]
        else:
            src = frames[len(frames) // 2]
        for dest in frames:
            if int(dest) == int(src):
                continue
            copy_spine_pose(poses, int(dest), int(src), bone_list)
            copied.append({"phase": phase, "from": int(src), "to": int(dest), "bones": bone_list})
    return copied


def flyer_shared_phase_attitude_search(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    move_pos: Sequence[int],
    wrap: bool,
    steps: Sequence[float] | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """One Euler delta per flight phase on the shared skeleton.

    Takeoff, cruise, and landing are different poses, but frames inside a phase
    must move together. Independent per-frame Euler is a flipbook.
    Starts from the incoming pipeline poses and applies small shared deltas.
    """
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_broad_stroke_search_bones(names, parents, catalog=anatomy_catalog(payload))
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    limit = joint_limit_deg(payload)
    prefix, suffix = idle_band_from_payload(payload)
    frame_count = len(list(experiment.frame_indices))
    clip_frames = [int(frame) for frame in experiment.frame_indices]
    frame_to_pos = {int(frame): int(pos) for pos, frame in zip(move_pos, move_frames)}
    groups = flight_phase_groups(
        move_frames, prefix=prefix, suffix=suffix, frame_count=frame_count
    )
    step_values = tuple(
        float(step) for step in (steps if steps is not None else PIPELINE_REFINE_SPINE_STEPS_DEG)
    )
    best = clone_pose_map(poses)
    kept = 0
    phase_rows: list[dict[str, Any]] = []
    for phase, group_frames in groups.items():
        if not group_frames:
            continue
        if phase == "takeoff":
            representative = int(group_frames[0])
        elif phase == "landing":
            representative = int(group_frames[-1])
        else:
            representative = int(group_frames[len(group_frames) // 2])
        pos_i = int(frame_to_pos[representative])
        sprite_axis = flight_phase_sprite_axis(
            representative, prefix=prefix, suffix=suffix, frame_count=frame_count
        )
        best_align = frame_spine_align(experiment, best, pos_i, measure)
        best_score = spine_sprite_axis_score(best_align, sprite_axis)
        best_belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
        best_frac = frame_leftover_extra(experiment, best, pos_i)
        if phase != "takeoff" and flyer_phase_needs_right_seed(best_align, sprite_axis):
            donor = groups.get("takeoff") or []
            if donor:
                seed_bones = list(dict.fromkeys(["Bone_000", *spine]))
                for dest in group_frames:
                    copy_spine_pose(best, int(dest), int(donor[0]), seed_bones)
                best_align = frame_spine_align(experiment, best, pos_i, measure)
                best_score = spine_sprite_axis_score(best_align, sprite_axis)
                best_belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
                best_frac = frame_leftover_extra(experiment, best, pos_i)
        perch_trap = flyer_frame_is_perch_trap(best_align, sprite_axis)
        flat_trap = flyer_frame_is_flat_trap(best_align, sprite_axis)
        pitch_trap = flyer_frame_is_pitch_trap(best_align, sprite_axis)
        camera_trap = flyer_frame_is_camera_trap(best_align)
        trap = perch_trap or flat_trap or pitch_trap or camera_trap
        search_bones = list(spine)
        if camera_trap:
            search_bones = flyer_camera_trap_search_bones(spine, names)
        phase_kept = 0
        for bone in search_bones:
            for axis in ("x", "y", "z"):
                for step in step_values:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg_shared_within_limit(
                            trial,
                            joint=bone,
                            frames=group_frames,
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_align = frame_spine_align(experiment, trial, pos_i, measure)
                    trial_score = spine_sprite_axis_score(trial_align, sprite_axis)
                    if float(sprite_axis[0]) > 0.0 and float(trial_align["rightSigned"]) <= 0.0:
                        continue
                    best_plane = spine_is_image_plane(best_align)
                    trial_plane = spine_is_image_plane(trial_align)
                    if not best_plane:
                        if abs(float(trial_align["forward"])) >= abs(float(best_align["forward"])) - 1e-9:
                            continue
                    else:
                        if not trial_plane:
                            continue
                        if pitch_trap or camera_trap:
                            if trial_score + 0.05 < best_score:
                                continue
                        elif trial_score <= best_score + 1e-9:
                            continue
                    if perch_trap or pitch_trap:
                        if abs(float(trial_align["down"])) >= abs(float(best_align["down"])) - 1e-9:
                            continue
                    elif flat_trap:
                        if abs(float(trial_align["down"])) <= abs(float(best_align["down"])) + 1e-9:
                            continue
                    elif camera_trap:
                        if abs(float(trial_align["forward"])) >= abs(float(best_align["forward"])) - 1e-9:
                            continue
                        if abs(float(trial_align["down"])) > abs(float(best_align["down"])) + 1e-9:
                            continue
                    trial_belly = frame_belly_align(experiment, trial, pos_i, measure, ventral_mask)
                    if float(trial_belly["down"]) + 0.08 < float(best_belly["down"]):
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not flyer_attitude_occupancy_allows(
                        best_frac,
                        trial_frac,
                        camera_trap=camera_trap,
                        trap=trap,
                    ):
                        continue
                    if abs(float(trial_align["forward"])) > abs(float(best_align["forward"])) + 0.05:
                        continue
                    if not skeleton_velocity_allows(
                        best,
                        trial,
                        frame=representative,
                        frames=clip_frames,
                        bones=spine,
                        wrap=wrap,
                        trap=trap,
                    ):
                        continue
                    best = trial
                    best_align = trial_align
                    best_score = trial_score
                    best_belly = trial_belly
                    best_frac = trial_frac
                    phase_kept += 1
                    kept += 1
        phase_rows.append(
            {
                "phase": phase,
                "frames": list(group_frames),
                "representative": representative,
                "kept": phase_kept,
                "spriteAxis": [float(sprite_axis[0]), float(sprite_axis[1])],
                "spriteAxisScore": best_score,
                "spineAlign": best_align,
                "bellyAlign": best_belly,
                "cameraTrap": camera_trap,
            }
        )
    return best, {
        "spineBones": spine,
        "kept": kept,
        "phases": phase_rows,
        "sharedSkeleton": True,
        "temporalWrap": bool(wrap),
        "refineSteps": list(step_values),
        "preservePipelinePoses": True,
    }


def flyer_shared_phase_belly_roll(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    move_pos: Sequence[int],
    wrap: bool,
    steps: Sequence[float] | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Roll belly toward the ground per flight phase, from pipeline poses.

    A level tail→head axis can still show the pale belly to the camera.
    Search small shared Euler on trunk/neck/tail. Do not apply 60–150°
    from-scratch rolls to every move frame at once.
    """
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_broad_stroke_search_bones(names, parents, catalog=anatomy_catalog(payload))
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    limit = joint_limit_deg(payload)
    prefix, suffix = idle_band_from_payload(payload)
    frame_count = len(list(experiment.frame_indices))
    clip_frames = [int(frame) for frame in experiment.frame_indices]
    frame_to_pos = {int(frame): int(pos) for pos, frame in zip(move_pos, move_frames)}
    groups = flight_phase_groups(
        move_frames, prefix=prefix, suffix=suffix, frame_count=frame_count
    )
    step_values = tuple(
        float(step) for step in (steps if steps is not None else PIPELINE_REFINE_SPINE_STEPS_DEG)
    )
    best = clone_pose_map(poses)
    kept = 0
    phase_rows: list[dict[str, Any]] = []
    for phase, group_frames in groups.items():
        if not group_frames:
            continue
        if phase == "takeoff":
            representative = int(group_frames[0])
        elif phase == "landing":
            representative = int(group_frames[-1])
        else:
            representative = int(group_frames[len(group_frames) // 2])
        pos_i = int(frame_to_pos[representative])
        sprite_axis = flight_phase_sprite_axis(
            representative, prefix=prefix, suffix=suffix, frame_count=frame_count
        )
        best_align = frame_spine_align(experiment, best, pos_i, measure)
        best_score = spine_sprite_axis_score(best_align, sprite_axis)
        best_belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
        best_frac = frame_leftover_extra(experiment, best, pos_i)
        phase_kept = 0
        for bone in spine:
            for axis in ("x", "y", "z"):
                for step in step_values:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg_shared_within_limit(
                            trial,
                            joint=bone,
                            frames=group_frames,
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_align = frame_spine_align(experiment, trial, pos_i, measure)
                    if not spine_is_image_plane(trial_align):
                        continue
                    if float(sprite_axis[0]) > 0.0 and float(trial_align["rightSigned"]) <= 0.0:
                        continue
                    trial_score = spine_sprite_axis_score(trial_align, sprite_axis)
                    if trial_score + 0.05 < best_score:
                        continue
                    if abs(float(trial_align["forward"])) > abs(float(best_align["forward"])) + 0.05:
                        continue
                    trial_belly = frame_belly_align(experiment, trial, pos_i, measure, ventral_mask)
                    if float(trial_belly["down"]) <= float(best_belly["down"]) + 1e-9:
                        continue
                    if abs(float(trial_belly["forward"])) > abs(float(best_belly["forward"])) + 0.08:
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not flyer_attitude_occupancy_allows(
                        best_frac,
                        trial_frac,
                        camera_trap=flyer_frame_is_camera_trap(best_align),
                        trap=True,
                    ):
                        continue
                    if not skeleton_velocity_allows(
                        best,
                        trial,
                        frame=representative,
                        frames=clip_frames,
                        bones=spine,
                        wrap=wrap,
                        trap=True,
                    ):
                        continue
                    best = trial
                    best_align = trial_align
                    best_score = trial_score
                    best_belly = trial_belly
                    best_frac = trial_frac
                    phase_kept += 1
                    kept += 1
        phase_rows.append(
            {
                "phase": phase,
                "frames": list(group_frames),
                "representative": representative,
                "kept": phase_kept,
                "spineAlign": best_align,
                "bellyAlign": best_belly,
                "bellyDown": belly_is_down(best_belly),
                "spriteAxisScore": best_score,
            }
        )
    return best, {
        "spineBones": spine,
        "kept": kept,
        "phases": phase_rows,
        "sharedSkeleton": True,
        "temporalWrap": bool(wrap),
        "refineSteps": list(step_values),
        "preservePipelinePoses": True,
    }


def flyer_per_frame_attitude_search(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    move_pos: Sequence[int],
    wrap: bool,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Pitch each fly frame to that sprite's 2D long axis.

    Takeoff (frame 8) climbs. Cruise (frame 15) is level. Landing (frame 21)
    flares more upright. A shared 'level spine' pose cannot be all three.
    Neighbor Euler velocity (forward and backward) keeps this a skeleton
    trajectory, not a per-frame mesh swap.
    """
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_spine_chain_bones(names, parents)
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    limit = joint_limit_deg(payload)
    prefix, suffix = idle_band_from_payload(payload)
    frame_count = len(list(experiment.frame_indices))
    clip_frames = [int(frame) for frame in experiment.frame_indices]
    best = clone_pose_map(poses)
    kept = 0
    per_frame: list[dict[str, Any]] = []
    for frame_pos, frame in zip(move_pos, move_frames):
        frame_i = int(frame)
        pos_i = int(frame_pos)
        sprite_axis = flight_phase_sprite_axis(
            frame_i,
            prefix=prefix,
            suffix=suffix,
            frame_count=frame_count,
        )
        best_align = frame_spine_align(experiment, best, pos_i, measure)
        best_score = spine_sprite_axis_score(best_align, sprite_axis)
        best_belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
        best_frac = frame_leftover_extra(experiment, best, pos_i)
        seeded_from = None
        perch_trap = flyer_frame_is_perch_trap(best_align, sprite_axis)
        flat_trap = flyer_frame_is_flat_trap(best_align, sprite_axis)
        pitch_trap = flyer_frame_is_pitch_trap(best_align, sprite_axis)
        if perch_trap or flat_trap:
            donor = flyer_attitude_donor_frame(
                per_frame, perch_trap=perch_trap, flat_trap=flat_trap
            )
            if donor is not None:
                copy_spine_pose(best, frame_i, donor, spine)
                best_align = frame_spine_align(experiment, best, pos_i, measure)
                best_score = spine_sprite_axis_score(best_align, sprite_axis)
                best_belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
                best_frac = frame_leftover_extra(experiment, best, pos_i)
                seeded_from = donor
                perch_trap = flyer_frame_is_perch_trap(best_align, sprite_axis)
                flat_trap = flyer_frame_is_flat_trap(best_align, sprite_axis)
                pitch_trap = flyer_frame_is_pitch_trap(best_align, sprite_axis)
        frame_kept = 0
        for bone in spine:
            for axis in ("x", "y", "z"):
                for step in FLIGHT_PER_FRAME_SPINE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg_within_limit(
                            trial,
                            joint=bone,
                            frames=(frame_i,),
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_align = frame_spine_align(experiment, trial, pos_i, measure)
                    trial_score = spine_sprite_axis_score(trial_align, sprite_axis)
                    best_plane = spine_is_image_plane(best_align)
                    trial_plane = spine_is_image_plane(trial_align)
                    if not best_plane:
                        if abs(float(trial_align["forward"])) >= abs(float(best_align["forward"])) - 1e-9:
                            continue
                        if trial_score + 0.2 < best_score:
                            continue
                    else:
                        if not trial_plane:
                            continue
                        if trial_score <= best_score + 1e-9:
                            continue
                        if abs(float(trial_align["forward"])) > abs(float(best_align["forward"])) + 0.05:
                            continue
                    if perch_trap:
                        if abs(float(trial_align["down"])) >= abs(float(best_align["down"])) - 1e-9:
                            continue
                    elif flat_trap:
                        if abs(float(trial_align["down"])) <= abs(float(best_align["down"])) + 1e-9:
                            continue
                    elif pitch_trap:
                        if abs(float(trial_align["down"])) >= abs(float(best_align["down"])) - 1e-9:
                            continue
                    else:
                        if abs(float(sprite_axis[0])) >= 0.5 and abs(float(trial_align["down"])) > 0.85:
                            continue
                        if abs(float(sprite_axis[1])) >= 0.5 and abs(float(trial_align["right"])) > 0.95 and abs(float(trial_align["down"])) < 0.25:
                            continue
                    trial_belly = frame_belly_align(experiment, trial, pos_i, measure, ventral_mask)
                    if float(trial_belly["down"]) + 0.08 < float(best_belly["down"]):
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, pos_i)
                    camera_trap = flyer_frame_is_camera_trap(best_align)
                    if not flyer_attitude_occupancy_allows(
                        best_frac,
                        trial_frac,
                        camera_trap=camera_trap,
                        trap=not best_plane or perch_trap or flat_trap or pitch_trap or camera_trap,
                    ):
                        continue
                    if not skeleton_velocity_allows(
                        best,
                        trial,
                        frame=frame_i,
                        frames=clip_frames,
                        bones=spine,
                        wrap=wrap,
                        trap=perch_trap or flat_trap or pitch_trap,
                    ):
                        continue
                    best = trial
                    best_align = trial_align
                    best_score = trial_score
                    best_belly = trial_belly
                    best_frac = trial_frac
                    frame_kept += 1
                    kept += 1
        for bone in spine:
            for axis in ("x", "y", "z"):
                for step in FLIGHT_PER_FRAME_SPINE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg_within_limit(
                            trial,
                            joint=bone,
                            frames=(frame_i,),
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_align = frame_spine_align(experiment, trial, pos_i, measure)
                    trial_score = spine_sprite_axis_score(trial_align, sprite_axis)
                    if trial_score + 0.05 < best_score:
                        continue
                    if not spine_is_image_plane(trial_align):
                        continue
                    if abs(float(trial_align["forward"])) > abs(float(best_align["forward"])) + 0.05:
                        continue
                    trial_belly = frame_belly_align(experiment, trial, pos_i, measure, ventral_mask)
                    if float(trial_belly["down"]) <= float(best_belly["down"]) + 1e-9:
                        continue
                    if abs(float(trial_belly["forward"])) > abs(float(best_belly["forward"])) + 0.05:
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, pos_i)
                    leftover_growth = float(trial_frac.leftover) - float(best_frac.leftover)
                    if leftover_growth > float(EPSILON_LEFTOVER) + 1e-12:
                        continue
                    if not skeleton_velocity_allows(
                        best,
                        trial,
                        frame=frame_i,
                        frames=clip_frames,
                        bones=spine,
                        wrap=wrap,
                        trap=False,
                    ):
                        continue
                    best = trial
                    best_align = trial_align
                    best_score = trial_score
                    best_belly = trial_belly
                    best_frac = trial_frac
                    frame_kept += 1
                    kept += 1
        perch_trap = flyer_frame_is_perch_trap(best_align, sprite_axis)
        flat_trap = flyer_frame_is_flat_trap(best_align, sprite_axis)
        pitch_trap = flyer_frame_is_pitch_trap(best_align, sprite_axis)
        per_frame.append(
            {
                "frame": frame_i,
                "position": pos_i,
                "kept": frame_kept,
                "spriteAxis": [float(sprite_axis[0]), float(sprite_axis[1])],
                "spriteAxisScore": best_score,
                "spineAlign": best_align,
                "spineLevel": spine_level_score(best_align),
                "bellyAlign": best_belly,
                "seededFrom": seeded_from,
                "perchTrap": perch_trap,
                "flatTrap": flat_trap,
                "pitchTrap": pitch_trap,
            }
        )
    return best, {
        "spineBones": spine,
        "kept": kept,
        "frames": per_frame,
        "moveFramesOnly": True,
        "match": "flight_phase_sprite_axis",
        "sharedSkeleton": True,
        "temporalWrap": bool(wrap),
    }


def flyer_measure_move_attitude(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    move_frames: Sequence[int],
    move_pos: Sequence[int],
    wrap: bool,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Record per-frame spine after shared-skeleton search. Does not pose independently."""
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    spine = flyer_spine_chain_bones(names, parents)
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    prefix, suffix = idle_band_from_payload(payload)
    frame_count = len(list(experiment.frame_indices))
    clip_frames = [int(frame) for frame in experiment.frame_indices]
    best = clone_pose_map(poses)
    per_frame: list[dict[str, Any]] = []
    for frame_pos, frame in zip(move_pos, move_frames):
        frame_i = int(frame)
        pos_i = int(frame_pos)
        sprite_axis = flight_phase_sprite_axis(
            frame_i, prefix=prefix, suffix=suffix, frame_count=frame_count
        )
        align = frame_spine_align(experiment, best, pos_i, measure)
        belly = frame_belly_align(experiment, best, pos_i, measure, ventral_mask)
        per_frame.append(
            {
                "frame": frame_i,
                "position": pos_i,
                "kept": 0,
                "spriteAxis": [float(sprite_axis[0]), float(sprite_axis[1])],
                "spriteAxisScore": spine_sprite_axis_score(align, sprite_axis),
                "spineAlign": align,
                "spineLevel": spine_level_score(align),
                "bellyAlign": belly,
                "perchTrap": flyer_frame_is_perch_trap(align, sprite_axis),
                "flatTrap": flyer_frame_is_flat_trap(align, sprite_axis),
                "pitchTrap": flyer_frame_is_pitch_trap(align, sprite_axis),
                "cameraTrap": flyer_frame_is_camera_trap(align),
                "velocityRms": pose_bidirectional_velocity_rms(
                    best, frame=frame_i, frames=clip_frames, bones=spine, wrap=wrap
                ),
            }
        )
    return best, {
        "spineBones": spine,
        "kept": 0,
        "frames": per_frame,
        "moveFramesOnly": True,
        "match": "shared_skeleton_measure",
        "sharedSkeleton": True,
        "temporalWrap": bool(wrap),
        "independentPerFrameSearch": False,
    }


def leftover_pose_search(
    experiment,
    payload: dict[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    bones: Sequence[str],
    *,
    fine: bool = False,
    clip_name: str = "",
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Clip-wide leftover search: shared root, shared bones, then per-frame leftover bones."""
    frames = [int(frame) for frame in experiment.frame_indices]
    schedule = pose_search_schedule(len(frames), fine=fine)
    limit = joint_limit_deg(payload)
    trans_limit = 0.25
    wrap = clip_wraps_temporally(clip_name, payload)
    details: dict[str, Any] = {
        "schedule": {key: schedule[key] for key in ("bones", "tryBind", "perFrameAll")},
        "fine": bool(fine),
        "temporalWrap": wrap,
        "sharedSkeleton": True,
    }

    stored = clone_pose_map(poses)
    seed = stored
    seed_frac = clip_leftover_extra(experiment, stored)
    if schedule["tryBind"]:
        bind = bind_like_poses(stored, frames)
        bind_frac = clip_leftover_extra(experiment, bind)
        details["storedLeftover"] = float(seed_frac.leftover)
        details["bindLeftover"] = float(bind_frac.leftover)
        if float(bind_frac.leftover) + 1e-9 < float(seed_frac.leftover):
            seed = bind
            seed_frac = bind_frac
            details["seed"] = "bind"
        else:
            details["seed"] = "stored"
    else:
        details["seed"] = "stored"

    seed, flight_details = flyer_flight_attitude_search(experiment, payload, seed)
    details["flightAttitude"] = flight_details
    seed_frac = clip_leftover_extra(experiment, seed)
    flight_applied = bool(flight_details.get("applied"))
    move_pos = [int(index) for index in flight_details.get("movePositions") or []]
    move_frames = [frames[index] for index in move_pos]
    probe_pos = int(flight_details.get("probePosition") or (move_pos[len(move_pos) // 2] if move_pos else 0))
    sprite_aspect = float(flight_details.get("spriteProbeAspect") or 0.0)
    shared_frames = frames
    score_positions = None
    if flight_applied:
        names = [str(name) for name in experiment.node_names]
        parents = [
            None if parent is None or int(parent) < 0 else int(parent)
            for parent in experiment.parents
        ]
        measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
        current_align = frame_spine_align(experiment, seed, probe_pos, measure)
        current_belly = frame_belly_align(
            experiment,
            seed,
            probe_pos,
            measure,
            flight_ventral_mask(experiment, seed, measure),
        )
        details["preservePipelinePoses"] = True
        details["spineAlign"] = current_align
        details["spineAttitude"] = {
            "kept": 0,
            "spineAlign": current_align,
            "skipped": "preserve_pipeline_poses",
            "moveFramesOnly": True,
        }
        details["bellyRoll"] = {
            "kept": 0,
            "spineAlign": current_align,
            "bellyAlign": current_belly,
            "bellyDown": belly_is_down(current_belly),
            "skipped": "preserve_pipeline_poses",
            "moveFramesOnly": True,
        }
        seed, seed_details = seed_trapped_flyer_frames(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
        )
        details["trapSeed"] = seed_details
        seed, shared_details = flyer_shared_phase_attitude_search(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
            wrap=wrap,
            steps=PIPELINE_REFINE_SPINE_STEPS_DEG,
        )
        details["sharedPhaseAttitude"] = shared_details
        seed, belly_details = flyer_shared_phase_belly_roll(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
            wrap=wrap,
            steps=PIPELINE_REFINE_SPINE_STEPS_DEG,
        )
        seed, belly_details_2 = flyer_shared_phase_belly_roll(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
            wrap=wrap,
            steps=PIPELINE_REFINE_SPINE_STEPS_DEG,
        )
        details["bellyRoll"] = {
            **belly_details_2,
            "kept": int(belly_details.get("kept") or 0) + int(belly_details_2.get("kept") or 0),
            "passes": 2,
            "skipped": None,
        }
        prefix, suffix = idle_band_from_payload(payload)
        details["phaseSkeletonCopy"] = copy_phase_skeleton(
            seed,
            flight_phase_groups(
                move_frames,
                prefix=prefix,
                suffix=suffix,
                frame_count=len(frames),
            ),
            list(dict.fromkeys(["Bone_000", *flyer_broad_stroke_search_bones(names, parents, catalog=anatomy_catalog(payload))])),
        )
        seed, seed_details_after = seed_trapped_flyer_frames(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
        )
        details["trapSeedAfterBelly"] = seed_details_after
        seed, per_frame_details = flyer_measure_move_attitude(
            experiment,
            payload,
            seed,
            move_frames=move_frames,
            move_pos=move_pos,
            wrap=wrap,
        )
        details["perFrameAttitude"] = per_frame_details
        seed_frac = clip_leftover_extra(experiment, seed, positions=move_pos)
        keep = leftover_primary_better
        details["keep"] = "side_view_leftover_flight"
        shared_frames = move_frames
        score_positions = move_pos
    else:
        if float(seed_frac.leftover) >= float(seed_frac.extra) and float(seed_frac.leftover) > FEASIBLE_LEFTOVER:
            keep = lambda before, trial: leftover_primary_better(
                before, trial, allow_leftover_growth=False
            )
            details["keep"] = "leftover_primary"
        elif float(seed_frac.extra) > FEASIBLE_EXTRA:
            keep = _keep_occupancy_net
            details["keep"] = "occupancy_net"
        else:
            keep = _keep_fractions
            details["keep"] = "leftover_extra_cap"
    leftover_bones = [str(name) for name in bones if name]
    attitude_frames = (details.get("perFrameAttitude") or {}).get("frames") or []
    broad_ok = (not flight_applied) or flyer_broad_stroke_ok(attitude_frames)
    details["broadStroke"] = {
        "ok": bool(broad_ok),
        "minScore": float(FLIGHT_BROAD_STROKE_MIN_SCORE),
        "needed": bool(flight_applied),
    }
    if flight_applied:
        names = [str(name) for name in experiment.node_names]
        parents = [
            None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
        ]
        spine = flyer_attitude_bones(names, parents)
        held_spine = set(flyer_broad_stroke_search_bones(names, parents, catalog=anatomy_catalog(payload)))
        leftover_bones = [name for name in leftover_bones if name not in held_spine]
        details["spineHeldAfterAttitude"] = sorted(held_spine)
        cap = max(int(schedule["bones"]), 8)
        shared_steps = (-30.0, -20.0, -12.0, -6.0, 6.0, 12.0, 20.0, 30.0)
        per_frame_steps = (-20.0, -12.0, -8.0, -4.0, 4.0, 8.0, 12.0, 20.0)
        details["spineBones"] = spine
    else:
        cap = int(schedule["bones"])
        shared_steps = tuple(schedule["sharedBoneSteps"])
        per_frame_steps = tuple(schedule["perFrameSteps"])
    insert = "Bone_FeasibilityInsert"
    if insert in {str(name) for name in experiment.node_names}:
        leftover_bones = [insert, *[name for name in leftover_bones if name != insert]]
    ranked = leftover_bones[:cap]
    defer_fill = bool(flight_applied and not broad_ok)
    if defer_fill:
        ranked = []
        details["leftoverFillDeferred"] = True
        details["leftoverFillDeferredReason"] = "broad_stroke_first"
    details["schedule"]["bones"] = len(ranked)

    def score_clip(candidate):
        return clip_leftover_extra(experiment, candidate, positions=score_positions)

    def flight_fill_keep(before_poses, trial_poses, before_frac, trial_frac, view_pos: int) -> bool:
        _before_view, before_aspect = frame_occupancy_view(experiment, before_poses, int(view_pos))
        _trial_view, trial_aspect = frame_occupancy_view(experiment, trial_poses, int(view_pos))
        return side_view_flight_better(
            before_frac,
            trial_frac,
            before_spans=frame_camera_spans(experiment, before_poses, int(view_pos)),
            trial_spans=frame_camera_spans(experiment, trial_poses, int(view_pos)),
            sprite_aspect=sprite_aspect,
            before_aspect=float(before_aspect),
            trial_aspect=float(trial_aspect),
            leftover_growth_cap=0.0,
        ) and leftover_primary_better(before_frac, trial_frac, allow_leftover_growth=False)

    best = clone_pose_map(seed)
    best_frac = seed_frac
    kept_root = 0
    if not flight_applied:
        for axis in ROOT_ROTATION_AXES:
            for step in schedule["rootSteps"]:
                trial = clone_pose_map(best)
                try:
                    rotate_root_deg(
                        trial,
                        frames=frames,
                        axis=axis,
                        delta_deg=float(step),
                        limit_deg=root_rotation_limit_deg(payload, axis),
                    )
                except ValueError:
                    continue
                trial_frac = clip_leftover_extra(experiment, trial)
                if keep(best_frac, trial_frac):
                    best = trial
                    best_frac = trial_frac
                    kept_root += 1
    kept_trans = 0
    if not defer_fill:
        for axis in ROOT_TRANSLATION_AXES:
            for step in schedule["transSteps"]:
                trial = clone_pose_map(best)
                try:
                    translate_root(
                        trial,
                        frames=shared_frames,
                        axis=axis,
                        delta=float(step),
                        limit=trans_limit,
                    )
                except ValueError:
                    continue
                trial_frac = score_clip(trial)
                if flight_applied:
                    accepted_step = flight_fill_keep(best, trial, best_frac, trial_frac, probe_pos)
                else:
                    accepted_step = keep(best_frac, trial_frac)
                if accepted_step:
                    best = trial
                    best_frac = trial_frac
                    kept_trans += 1
    kept_shared = 0
    for bone in ranked:
        for axis in ("x", "y", "z"):
            for step in shared_steps:
                trial = clone_pose_map(best)
                try:
                    rotate_bone_deg(
                        trial,
                        joint=bone,
                        frames=shared_frames,
                        axis=axis,
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                trial_frac = score_clip(trial)
                if flight_applied:
                    accepted_step = flight_fill_keep(best, trial, best_frac, trial_frac, probe_pos)
                else:
                    accepted_step = keep(best_frac, trial_frac)
                if accepted_step:
                    best = trial
                    best_frac = trial_frac
                    kept_shared += 1

    leftover_sizes = [
        float(frame_leftover_extra(experiment, best, position).leftover) for position in range(len(frames))
    ]
    if flight_applied:
        frame_positions = list(move_pos)
    elif schedule["perFrameAll"]:
        frame_positions = list(range(len(frames)))
    else:
        order = list(np.argsort(leftover_sizes)[::-1])
        frame_positions = order[: max(4, len(frames) // 2)]
    kept_frame = 0
    for frame_pos in frame_positions:
        frame = frames[int(frame_pos)]
        frame_best = frame_leftover_extra(experiment, best, int(frame_pos))
        for bone in ranked:
            for axis in ("x", "y", "z"):
                for step in per_frame_steps:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg(
                            trial,
                            joint=bone,
                            frames=(frame,),
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, int(frame_pos))
                    if flight_applied:
                        accepted_step = flight_fill_keep(best, trial, frame_best, trial_frac, int(frame_pos))
                    else:
                        accepted_step = keep(frame_best, trial_frac)
                    if accepted_step and not skeleton_velocity_allows(
                        best,
                        trial,
                        frame=int(frame),
                        frames=frames,
                        bones=ranked,
                        wrap=wrap,
                        trap=False,
                    ):
                        accepted_step = False
                    if accepted_step:
                        best = trial
                        frame_best = trial_frac
                        kept_frame += 1
    clip_before = clip_leftover_extra(experiment, seed)
    final_frac = clip_leftover_extra(experiment, best)
    details.update(
        {
            "keptRoot": kept_root,
            "keptTranslation": kept_trans,
            "keptSharedBones": kept_shared,
            "keptPerFrame": kept_frame,
            "bones": ranked,
            "leftoverBefore": float(clip_before.leftover),
            "leftoverAfter": float(final_frac.leftover),
            "extraBefore": float(clip_before.extra),
            "extraAfter": float(final_frac.extra),
            "moveFramesOnly": bool(flight_applied),
            "velocityRmsAfter": clip_pose_velocity_rms(
                best,
                frames,
                ranked or bones,
                wrap=wrap,
            ),
        }
    )
    if flight_applied:
        names = [str(name) for name in experiment.node_names]
        parents = [
            None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
        ]
        measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
        details["spineAlignAfter"] = frame_spine_align(experiment, best, probe_pos, measure)
        details["bellyAlignAfter"] = frame_belly_align(
            experiment,
            best,
            probe_pos,
            measure,
            flight_ventral_mask(experiment, best, measure),
        )
        details["spineLevelAfter"] = spine_level_score(details["spineAlignAfter"])
        sample_pos = []
        if move_pos:
            sample_pos.append(int(move_pos[0]))
        sample_pos.append(int(probe_pos))
        if move_pos:
            sample_pos.append(int(move_pos[-1]))
        seen: set[int] = set()
        samples: list[dict[str, Any]] = []
        ventral = flight_ventral_mask(experiment, best, measure)
        for pos in sample_pos:
            if pos in seen:
                continue
            seen.add(pos)
            align = frame_spine_align(experiment, best, pos, measure)
            belly = frame_belly_align(experiment, best, pos, measure, ventral)
            prefix, suffix = idle_band_from_payload(payload)
            sprite_axis = flight_phase_sprite_axis(
                int(frames[pos]),
                prefix=prefix,
                suffix=suffix,
                frame_count=len(frames),
            )
            samples.append(
                {
                    "frame": frames[pos],
                    "position": pos,
                    "spineAlign": align,
                    "spineLevel": spine_level_score(align),
                    "spriteAxis": [float(sprite_axis[0]), float(sprite_axis[1])],
                    "spriteAxisScore": spine_sprite_axis_score(align, sprite_axis),
                    "bellyAlign": belly,
                }
            )
        details["perFrameSpineAfter"] = samples
    return best, details


def best_rotate_search(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    bones: Sequence[str],
    *,
    steps: Sequence[float],
    keep=None,
) -> dict[int, dict[str, Any]]:
    """Re-aim named bones only. Does not re-seed bind or re-search root heading.

    When extra is still above the feasible cap, keep occupancy net so leftover
    fill is not rejected just because extra grew a little.
    """
    frames = [int(frame) for frame in experiment.frame_indices]
    limit = joint_limit_deg(payload)
    best = clone_pose_map(poses)
    best_frac = clip_leftover_extra(experiment, best)
    if keep is None:
        keep = _keep_occupancy_net if float(best_frac.extra) > FEASIBLE_EXTRA else _keep_fractions
    for bone in bones:
        for axis in ("x", "y", "z"):
            for step in steps:
                trial = clone_pose_map(best)
                try:
                    rotate_bone_deg(
                        trial,
                        joint=bone,
                        frames=frames,
                        axis=axis,
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                trial_frac = clip_leftover_extra(experiment, trial)
                if keep(best_frac, trial_frac):
                    best = trial
                    best_frac = trial_frac
    for frame_pos, frame in enumerate(frames):
        frame_best = frame_leftover_extra(experiment, best, int(frame_pos))
        for bone in bones:
            for axis in ("x", "y", "z"):
                for step in steps:
                    trial = clone_pose_map(best)
                    try:
                        rotate_bone_deg(
                            trial,
                            joint=bone,
                            frames=(frame,),
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    trial_frac = frame_leftover_extra(experiment, trial, int(frame_pos))
                    if keep(frame_best, trial_frac):
                        best = trial
                        frame_best = trial_frac
    return best


def flight_rest_frame_candidates(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
) -> list[int] | None:
    """Flyer leftover fill must not pick a standing leftover blob on a fly plate."""
    prefix, suffix = idle_band_from_payload(payload)
    count = len(list(experiment.frame_indices))
    masks = [
        experiment.target_masks[index].detach().cpu().numpy() > 0.5 for index in range(count)
    ]
    if not flight_attitude_needed(masks, prefix, suffix):
        return None
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    usable: list[int] = []
    for pos in move_frame_positions(count, prefix, suffix):
        align = frame_spine_align(experiment, poses, int(pos), measure)
        axis = flight_phase_sprite_axis(
            int(experiment.frame_indices[int(pos)]),
            prefix=prefix,
            suffix=suffix,
            frame_count=count,
        )
        if (
            spine_is_image_plane(align)
            and float(align["right"]) >= float(FLIGHT_REST_RIGHT_MIN)
            and not flyer_frame_is_perch_trap(align, axis)
            and not flyer_frame_is_flat_trap(align, axis)
        ):
            usable.append(int(pos))
    return usable


def flight_attitude_trap_frames(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Standing or flat leftovers on fly plates. Rest-sculpt must not run yet."""
    prefix, suffix = idle_band_from_payload(payload)
    count = len(list(experiment.frame_indices))
    frames = [int(frame) for frame in experiment.frame_indices]
    masks = [
        experiment.target_masks[index].detach().cpu().numpy() > 0.5 for index in range(count)
    ]
    if not flight_attitude_needed(masks, prefix, suffix):
        return []
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    traps: list[dict[str, Any]] = []
    for pos in move_frame_positions(count, prefix, suffix):
        align = frame_spine_align(experiment, poses, int(pos), measure)
        axis = flight_phase_sprite_axis(
            int(frames[int(pos)]), prefix=prefix, suffix=suffix, frame_count=count
        )
        if flyer_frame_is_perch_trap(align, axis) or flyer_frame_is_flat_trap(align, axis):
            traps.append(
                {
                    "frame": int(frames[int(pos)]),
                    "position": int(pos),
                    "perchTrap": flyer_frame_is_perch_trap(align, axis),
                    "flatTrap": flyer_frame_is_flat_trap(align, axis),
                    "spineAlign": align,
                }
            )
    return traps


def flight_broad_stroke_status(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """True only when every fly plate's visual body matches that plate."""
    prefix, suffix = idle_band_from_payload(payload)
    count = len(list(experiment.frame_indices))
    masks = [
        experiment.target_masks[index].detach().cpu().numpy() > 0.5 for index in range(count)
    ]
    if not flight_attitude_needed(masks, prefix, suffix):
        return {"needed": False, "ok": True, "frames": []}
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    measure = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    ventral_mask = flight_ventral_mask(experiment, poses, measure)
    frames = [int(frame) for frame in experiment.frame_indices]
    rows: list[dict[str, Any]] = []
    for pos in move_frame_positions(count, prefix, suffix):
        align = frame_spine_align(experiment, poses, int(pos), measure)
        axis = flight_phase_sprite_axis(
            int(frames[int(pos)]), prefix=prefix, suffix=suffix, frame_count=count
        )
        belly = frame_belly_align(experiment, poses, int(pos), measure, ventral_mask)
        row = {
            "frame": int(frames[int(pos)]),
            "position": int(pos),
            "spriteAxis": [float(axis[0]), float(axis[1])],
            "spriteAxisScore": spine_sprite_axis_score(align, axis),
            "spineAlign": align,
            "bellyAlign": belly,
            "perchTrap": flyer_frame_is_perch_trap(align, axis),
            "flatTrap": flyer_frame_is_flat_trap(align, axis),
            "pitchTrap": flyer_frame_is_pitch_trap(align, axis),
            "cameraTrap": flyer_frame_is_camera_trap(align),
        }
        row["ok"] = flyer_broad_stroke_frame_ok(align, axis, belly)
        rows.append(row)
    return {
        "needed": True,
        "ok": flyer_broad_stroke_ok(rows),
        "frames": rows,
        "measureBones": measure,
    }


def composite_phase_rest_bundle(
    *,
    perch: Mapping[str, Any],
    phase_bundles: Mapping[str, Mapping[str, Any]],
    sources: Sequence[str],
    png_dir: Path,
    frames: Sequence[int],
) -> dict[str, Any]:
    png_dir = assert_write_path(png_dir, repo_root=ROOT)
    png_dir.mkdir(parents=True, exist_ok=True)
    leftover_maps = []
    extra_maps = []
    rows = []
    strain_parts: list[float] = []
    if len(list(sources)) != len(list(frames)):
        raise ValueError("phase rest composite sources must match the clip frames")
    for index, frame in enumerate(frames):
        source = str(sources[index])
        if source == "perch":
            bundle = perch
        else:
            if source not in phase_bundles:
                raise ValueError(f"phase rest composite missing bundle for {source!r}")
            bundle = phase_bundles[source]
        leftover_maps.append(np.asarray(bundle["leftoverMasks"][index], dtype=bool))
        extra_maps.append(np.asarray(bundle["extraMasks"][index], dtype=bool))
        rows.append(bundle["perFrame"][index])
        strain_parts.append(float(bundle["strain"]))
        src_png = Path(bundle["pngDir"]) / f"{int(frame):02d}.png"
        Image.open(src_png).convert("RGB").save(png_dir / f"{int(frame):02d}.png", format="PNG", compress_level=0)
    wide = clip_wide_mean(rows)
    return {
        "fractions": wide,
        "perFrame": rows,
        "leftoverMasks": leftover_maps,
        "extraMasks": extra_maps,
        "strain": float(np.mean(strain_parts)) if strain_parts else float(perch["strain"]),
        "pngDir": png_dir,
        "resolution": perch["resolution"],
        "boneVectors": perch["boneVectors"],
        "rootTranslation": perch["rootTranslation"],
        "rootRotation": perch["rootRotation"],
    }


def last_architecture_round_dir(work: Path) -> Path | None:
    index_path = work / "index.json"
    if not index_path.is_file():
        return None
    index = _json_load(index_path)
    rid = index.get("architectureRound")
    if not rid:
        return None
    path = work / str(rid)
    if not path.is_dir():
        return None
    return path


def architecture_source_round(work: Path, source_id: str) -> Path:
    """Named prior round whose fly rests this pass copies. Fail-closed."""
    rid = str(source_id).strip()
    if not rid:
        raise ValueError("architecture source round id is required")
    path = Path(work) / rid
    if not path.is_dir():
        raise ValueError(f"architecture source {rid} is not a round directory")
    return path


def fly_rest_tpose_source(source_round: Path, *, allow_symmetric_standin: bool) -> Path:
    """Shared fly rest for pair search. Abbreviated pass may use the uncut symmetric rest."""
    tpose = Path(source_round) / "fly_rest_tpose.glb"
    if tpose.is_file():
        return tpose
    if allow_symmetric_standin:
        alt = Path(source_round) / "fly_rest_symmetric.glb"
        if alt.is_file():
            return alt
    raise ValueError(f"{Path(source_round).name} has no fly_rest_tpose.glb")


def last_round_with_file(work: Path, filename: str) -> Path | None:
    """Latest accepted round that already wrote ``filename``."""
    index_path = work / "index.json"
    if not index_path.is_file():
        return None
    index = _json_load(index_path)
    for row in reversed(list(index.get("trajectory") or [])):
        if not row.get("accepted"):
            continue
        rid = str(row.get("roundId") or "")
        if not rid:
            continue
        path = work / rid
        if (path / filename).is_file():
            return path
    return None


def last_round_with_architecture(work: Path, architecture: str) -> Path | None:
    """Latest accepted round whose details.architecture matches."""
    index_path = work / "index.json"
    if not index_path.is_file():
        return None
    index = _json_load(index_path)
    wanted = str(architecture)
    for row in reversed(list(index.get("trajectory") or [])):
        if not row.get("accepted"):
            continue
        details = row.get("details") or {}
        if str(details.get("architecture") or "") != wanted:
            continue
        rid = str(row.get("roundId") or "")
        if not rid:
            continue
        path = work / rid
        if path.is_dir():
            return path
    return None


def last_anatomy_fit_completed(work: Path) -> list[str]:
    round_dir = last_architecture_round_dir(work)
    if round_dir is None:
        return []
    report_path = round_dir / "round_report.json"
    if not report_path.is_file():
        return []
    report = _json_load(report_path)
    completed = ((report.get("details") or {}).get("anatomyFitCompleted") or [])
    return [str(item) for item in completed]


def write_phase_chat_stills(
    round_dir: Path,
    png_dir: Path,
    representatives: Mapping[str, int],
) -> dict[str, str]:
    dest = assert_write_path(round_dir / "chat_stills", repo_root=ROOT)
    dest.mkdir(parents=True, exist_ok=True)
    named = {"idle": 0, **{str(name): int(frame) for name, frame in representatives.items()}}
    paths: dict[str, str] = {}
    for name, frame in named.items():
        src = Path(png_dir) / f"{int(frame):02d}.png"
        if not src.is_file():
            raise ValueError(f"chat still missing raster {src}")
        dest_png = dest / f"f{int(frame):02d}_{name}.png"
        shutil.copy2(src, dest_png)
        paths[str(name)] = str(dest_png.resolve()).replace("\\", "/")
    return paths


def search_symmetric_bones_on_experiment(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    phase_frames: Sequence[int],
    representative: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Drive catalog pairs together. Coarse model-frame axes. One phase, one skeleton."""
    names = [str(name) for name in experiment.node_names]
    catalog = anatomy_catalog(payload)
    pairs = symmetric_bone_fit_pairs(catalog, names)
    central_groups = anatomy_central_search_groups(catalog)
    rest_rotations, origins = experiment_rest_worlds(experiment)
    model_frame = model_bind_frame(catalog, origins)
    bone_dirs = bone_distal_directions(catalog, origins)
    limit = joint_limit_deg(payload)
    frames = [int(frame) for frame in experiment.frame_indices]
    frame_to_pos = {int(frame): int(pos) for pos, frame in enumerate(frames)}
    if int(representative) not in frame_to_pos:
        raise ValueError(f"representative frame {representative} is not on the clip")
    pos_i = int(frame_to_pos[int(representative)])
    ordered_frames = [int(frame) for frame in phase_frames]
    if not ordered_frames:
        raise ValueError("symmetric bone fit needs at least one phase frame")
    best = clone_pose_map(poses)
    best_frac = frame_leftover_extra(experiment, best, pos_i)
    kept: list[dict[str, Any]] = []
    for pair in pairs:
        bones_a = [str(bone) for bone in pair["bonesA"]]
        bones_b = [str(bone) for bone in pair["bonesB"]]
        for bone_a, bone_b in zip(bones_a, bones_b):
            pair_best = best
            pair_frac = best_frac
            pair_row: dict[str, Any] | None = None
            for axis in ANATOMICAL_AXES:
                for step in SYMMETRIC_BONE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        applied = rotate_bilateral_pair_deg_shared(
                            trial,
                            bone_a=bone_a,
                            bone_b=bone_b,
                            frames=ordered_frames,
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                            rest_rotations=rest_rotations,
                            model_frame=model_frame,
                            bone_dirs=bone_dirs,
                        )
                    except ValueError:
                        continue
                    frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not symmetric_bone_trial_better(pair_frac, frac):
                        continue
                    pair_best = trial
                    pair_frac = frac
                    pair_row = {
                        "groupA": pair["groupA"],
                        "groupB": pair["groupB"],
                        "boneA": bone_a,
                        "boneB": bone_b,
                        "axis": axis,
                        "stepDeg": float(step),
                        "appliedDeg": float(applied),
                        "leftover": float(frac.leftover),
                        "extra": float(frac.extra),
                    }
            best = pair_best
            best_frac = pair_frac
            if pair_row is not None:
                kept.append(pair_row)
    for group in central_groups:
        for bone in anatomy_group_bones(catalog, group):
            if bone not in names:
                raise ValueError(f"central group {group} bone {bone} is not on the skeleton")
            bone_best = best
            bone_frac = best_frac
            bone_row: dict[str, Any] | None = None
            for axis in SAGITTAL_MODEL_AXES:
                for step in SYMMETRIC_BONE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        applied = rotate_bone_model_axis_deg_shared(
                            trial,
                            joint=str(bone),
                            frames=ordered_frames,
                            rest_rotation=rest_rotations[str(bone)],
                            axis_world=model_frame[str(axis)],
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not symmetric_bone_trial_better(bone_frac, frac):
                        continue
                    bone_best = trial
                    bone_frac = frac
                    bone_row = {
                        "group": str(group),
                        "bone": str(bone),
                        "axis": axis,
                        "stepDeg": float(step),
                        "appliedDeg": float(applied),
                        "leftover": float(frac.leftover),
                        "extra": float(frac.extra),
                    }
            best = bone_best
            best_frac = bone_frac
            if bone_row is not None:
                kept.append(bone_row)
    seed_frac = frame_leftover_extra(experiment, poses, pos_i)
    return best, {
        "representativeFrame": int(representative),
        "phaseFrames": ordered_frames,
        "seedLeftover": float(seed_frac.leftover),
        "seedExtra": float(seed_frac.extra),
        "leftover": float(best_frac.leftover),
        "extra": float(best_frac.extra),
        "kept": kept,
        "stepsDeg": [float(step) for step in SYMMETRIC_BONE_STEPS_DEG],
        "earlySymmetry": True,
        "wingDivergence": False,
    }


def load_pose_map_from_after_poses(path: Path) -> dict[int, dict[str, Any]]:
    payload = _json_load(path)
    require_pose_units_degrees(payload, source=str(path))
    poses = payload.get("poses")
    if not isinstance(poses, Mapping) or not poses:
        raise ValueError(f"{path} has no poses")
    return {int(frame): dict(entry) for frame, entry in poses.items()}


def search_asymmetric_bones_on_experiment(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    phase_frames: Sequence[int],
    representative: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Drive each side of a catalog pair on its own. Coarse model-frame axes. One phase."""
    names = [str(name) for name in experiment.node_names]
    catalog = anatomy_catalog(payload)
    pairs = symmetric_bone_fit_pairs(catalog, names)
    central_groups = anatomy_central_search_groups(catalog)
    rest_rotations, origins = experiment_rest_worlds(experiment)
    model_frame = model_bind_frame(catalog, origins)
    bone_dirs = bone_distal_directions(catalog, origins)
    limit = joint_limit_deg(payload)
    frames = [int(frame) for frame in experiment.frame_indices]
    frame_to_pos = {int(frame): int(pos) for pos, frame in enumerate(frames)}
    if int(representative) not in frame_to_pos:
        raise ValueError(f"representative frame {representative} is not on the clip")
    pos_i = int(frame_to_pos[int(representative)])
    ordered_frames = [int(frame) for frame in phase_frames]
    if not ordered_frames:
        raise ValueError("asymmetric bone fit needs at least one phase frame")
    best = clone_pose_map(poses)
    best_frac = frame_leftover_extra(experiment, best, pos_i)
    kept: list[dict[str, Any]] = []

    def search_one(bone: str, group: str) -> None:
        nonlocal best, best_frac, kept
        if str(bone) not in bone_dirs:
            raise ValueError(f"asymmetric search missing distal direction for {bone}")
        bone_best = best
        bone_frac = best_frac
        bone_row: dict[str, Any] | None = None
        for axis in ANATOMICAL_AXES:
            for step in SYMMETRIC_BONE_STEPS_DEG:
                trial = clone_pose_map(best)
                try:
                    applied = rotate_bone_model_axis_deg_shared(
                        trial,
                        joint=str(bone),
                        frames=ordered_frames,
                        rest_rotation=rest_rotations[str(bone)],
                        axis_world=bone_anatomical_axes(bone_dirs[str(bone)], model_frame)[
                            str(axis)
                        ],
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                frac = frame_leftover_extra(experiment, trial, pos_i)
                if not symmetric_bone_trial_better(bone_frac, frac):
                    continue
                bone_best = trial
                bone_frac = frac
                bone_row = {
                    "group": str(group),
                    "bone": str(bone),
                    "axis": axis,
                    "stepDeg": float(step),
                    "appliedDeg": float(applied),
                    "leftover": float(frac.leftover),
                    "extra": float(frac.extra),
                }
        best = bone_best
        best_frac = bone_frac
        if bone_row is not None:
            kept.append(bone_row)

    for pair in pairs:
        bones_a = [str(bone) for bone in pair["bonesA"]]
        bones_b = [str(bone) for bone in pair["bonesB"]]
        for bone_a, bone_b in zip(bones_a, bones_b):
            search_one(bone_a, pair["groupA"])
            search_one(bone_b, pair["groupB"])
    for group in central_groups:
        for bone in anatomy_group_bones(catalog, group):
            if bone not in names:
                raise ValueError(f"central group {group} bone {bone} is not on the skeleton")
            search_one(str(bone), str(group))
    seed_frac = frame_leftover_extra(experiment, poses, pos_i)
    return best, {
        "representativeFrame": int(representative),
        "phaseFrames": ordered_frames,
        "seedLeftover": float(seed_frac.leftover),
        "seedExtra": float(seed_frac.extra),
        "leftover": float(best_frac.leftover),
        "extra": float(best_frac.extra),
        "kept": kept,
        "stepsDeg": [float(step) for step in SYMMETRIC_BONE_STEPS_DEG],
        "earlySymmetry": False,
        "wingDivergence": True,
    }


def apply_bone_combo_deg(
    poses: dict[int, dict[str, Any]],
    *,
    bone: str,
    frames: Sequence[int],
    combo: tuple[float, float, float],
    joint_limit_deg: float,
    rest_rotation: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
    bone_dir: np.ndarray,
) -> None:
    """Apply a combined anatomical (raise, sweep, twist) delta for this bone."""
    if len(combo) != 3:
        raise ValueError("combo must be (raise, sweep, twist) degrees")
    add = local_delta_from_anatomical(combo, rest_rotation, bone_dir, model_frame)
    if float(np.linalg.norm(add)) <= 1e-12:
        return
    add_axis_angle_deg_shared_within_limit(
        poses,
        joint=str(bone),
        frames=frames,
        add_xyz=add,
        joint_limit_deg=float(joint_limit_deg),
    )


def search_one_frame_leftover(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Leftover search on one frame only. Neighbors are not stamped.

    Coarse: combined anatomical (raise, sweep, twist) steps from the seed.
    A combo that grows extra too far, or stretches mixed-weight edges past
    strain slack, prunes larger steps in those same signed axes. Fine: one
    anatomical axis at a time. Keep only a substantial leftover drop that
    does not melt the mesh.
    """
    names = [str(name) for name in experiment.node_names]
    catalog = anatomy_catalog(payload)
    pairs = symmetric_bone_fit_pairs(catalog, names)
    central_groups = anatomy_central_search_groups(catalog)
    rest_rotations, origins = experiment_rest_worlds(experiment)
    model_frame = model_bind_frame(catalog, origins)
    bone_dirs = bone_distal_directions(catalog, origins)
    limit = joint_limit_deg(payload)
    frames = [int(item) for item in experiment.frame_indices]
    frame_to_pos = {int(item): int(pos) for pos, item in enumerate(frames)}
    if int(frame) not in frame_to_pos:
        raise ValueError(f"frame {frame} is not on the clip")
    pos_i = int(frame_to_pos[int(frame)])
    only = [int(frame)]
    from gpu_mesh_strain import build_backend_strain_table

    strain_table = build_backend_strain_table(experiment, exclusive_weight=STRAIN_EXCLUSIVE_WEIGHT)
    best = clone_pose_map(poses)
    seed_frac, seed_strain = frame_occupancy_strain(experiment, best, pos_i, strain_table)
    opening_strain = seed_strain
    best_frac, best_strain = seed_frac, seed_strain
    kept: list[dict[str, Any]] = []
    coarse_combos = temporal_coarse_combos()

    def occupancy_pick_better(
        current: OccupancyFractions | None,
        candidate: OccupancyFractions,
        *,
        current_strain: float | None = None,
        candidate_strain: float | None = None,
    ) -> bool:
        if current is None:
            return True
        if float(candidate.leftover) < float(current.leftover) - 1e-12:
            return True
        if abs(float(candidate.leftover) - float(current.leftover)) > 1e-12:
            return False
        if float(candidate.extra) < float(current.extra) - 1e-12:
            return True
        if abs(float(candidate.extra) - float(current.extra)) > 1e-12:
            return False
        if current_strain is None or candidate_strain is None:
            return False
        return float(candidate_strain) < float(current_strain) - 1e-12

    def search_one(bone: str, group: str) -> None:
        nonlocal best, best_frac, best_strain, kept
        if str(bone) not in bone_dirs:
            raise ValueError(f"leftover search missing distal direction for {bone}")
        seed = clone_pose_map(best)
        seed_frac = best_frac
        seed_strain = best_strain
        collision_bounds: list[tuple[float, float, float]] = []
        bone_best = seed
        bone_frac = seed_frac
        bone_strain = seed_strain
        bone_row: dict[str, Any] | None = None
        evaluated = 0
        pruned = 0
        for combo in coarse_combos:
            if combo_pruned_by_collision_bounds(combo, collision_bounds):
                pruned += 1
                continue
            trial = clone_pose_map(seed)
            try:
                apply_bone_combo_deg(
                    trial,
                    bone=str(bone),
                    frames=only,
                    combo=combo,
                    joint_limit_deg=limit,
                    rest_rotation=rest_rotations[str(bone)],
                    model_frame=model_frame,
                    bone_dir=bone_dirs[str(bone)],
                )
            except ValueError:
                collision_bounds.append(combo)
                pruned += 1
                continue
            frac, strain = frame_occupancy_strain(experiment, trial, pos_i, strain_table)
            evaluated += 1
            if occupancy_collision_unacceptable(seed_frac, frac):
                collision_bounds.append(combo)
                continue
            if leftover_trial_illegal(
                seed_frac, frac, seed_strain=opening_strain, trial_strain=strain
            ):
                collision_bounds.append(combo)
                continue
            if not substantial_occupancy_better(
                seed_frac, frac, before_strain=opening_strain, after_strain=strain
            ):
                continue
            if occupancy_pick_better(
                None if bone_row is None else bone_frac,
                frac,
                current_strain=None if bone_row is None else bone_strain,
                candidate_strain=strain,
            ):
                bone_best = trial
                bone_frac = frac
                bone_strain = strain
                bone_row = {
                    "stage": "coarse",
                    "kind": "combined_axes",
                    "group": str(group),
                    "bone": str(bone),
                    "comboDeg": [float(combo[0]), float(combo[1]), float(combo[2])],
                    "leftover": float(frac.leftover),
                    "extra": float(frac.extra),
                    "strain": float(strain),
                }
        best = bone_best
        best_frac = bone_frac
        best_strain = bone_strain
        if bone_row is not None:
            bone_row["evaluatedCombos"] = int(evaluated)
            bone_row["collisionPruned"] = int(pruned)
            kept.append(bone_row)
        for axis in ANATOMICAL_AXES:
            axis_seed = clone_pose_map(best)
            axis_seed_frac = best_frac
            axis_seed_strain = best_strain
            axis_pick = None
            axis_frac = axis_seed_frac
            axis_strain = axis_seed_strain
            axis_row: dict[str, Any] | None = None
            for step in TEMPORAL_FINE_STEPS_DEG:
                trial = clone_pose_map(axis_seed)
                try:
                    applied = rotate_bone_model_axis_deg_shared(
                        trial,
                        joint=str(bone),
                        frames=only,
                        rest_rotation=rest_rotations[str(bone)],
                        axis_world=bone_anatomical_axes(bone_dirs[str(bone)], model_frame)[
                            str(axis)
                        ],
                        delta_deg=float(step),
                        joint_limit_deg=limit,
                    )
                except ValueError:
                    continue
                frac, strain = frame_occupancy_strain(experiment, trial, pos_i, strain_table)
                if occupancy_collision_unacceptable(axis_seed_frac, frac):
                    continue
                if leftover_trial_illegal(
                    axis_seed_frac,
                    frac,
                    seed_strain=opening_strain,
                    trial_strain=strain,
                ):
                    continue
                if not substantial_occupancy_better(
                    axis_seed_frac,
                    frac,
                    before_strain=opening_strain,
                    after_strain=strain,
                ):
                    continue
                if occupancy_pick_better(
                    None if axis_row is None else axis_frac,
                    frac,
                    current_strain=None if axis_row is None else axis_strain,
                    candidate_strain=strain,
                ):
                    axis_pick = trial
                    axis_frac = frac
                    axis_strain = strain
                    axis_row = {
                        "stage": "fine",
                        "kind": "per_axis",
                        "group": str(group),
                        "bone": str(bone),
                        "axis": axis,
                        "stepDeg": float(step),
                        "appliedDeg": float(applied),
                        "leftover": float(frac.leftover),
                        "extra": float(frac.extra),
                        "strain": float(strain),
                    }
            if axis_pick is not None and axis_row is not None:
                best = axis_pick
                best_frac = axis_frac
                best_strain = axis_strain
                kept.append(axis_row)

    for pair in pairs:
        for bone in pair["bonesA"]:
            search_one(str(bone), pair["groupA"])
        for bone in pair["bonesB"]:
            search_one(str(bone), pair["groupB"])
    for group in central_groups:
        for bone in anatomy_group_bones(catalog, group):
            if bone not in names:
                raise ValueError(f"central group {group} bone {bone} is not on the skeleton")
            search_one(str(bone), str(group))
    return best, {
        "frame": int(frame),
        "seedLeftover": float(seed_frac.leftover),
        "seedExtra": float(seed_frac.extra),
        "seedStrain": float(seed_strain),
        "leftover": float(best_frac.leftover),
        "extra": float(best_frac.extra),
        "strain": float(best_strain),
        "kept": kept,
        "copiedFromPrevious": False,
        "seededFromInertial": False,
        "pipelineRelativeSeed": True,
        "independentPerFrameSearch": False,
        "temporalWrap": False,
        "coarseCombinedAxes": True,
        "modelFrameAxes": True,
        "anatomicalAxes": True,
        "copy_anatomical_delta": True,
        "collisionBoundPrune": True,
        "strainVeto": True,
        "substantialKeep": True,
    }


def search_one_frame_insert_bones(
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame: int,
    insert_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Leftover search on new insert bones only. Neighbors are not stamped."""
    names = {str(name) for name in experiment.node_names}
    catalog = anatomy_catalog(payload)
    rest_rotations, origins = experiment_rest_worlds(experiment)
    model_frame = model_bind_frame(catalog, origins)
    limit = joint_limit_deg(payload)
    frames = [int(item) for item in experiment.frame_indices]
    frame_to_pos = {int(item): int(pos) for pos, item in enumerate(frames)}
    if int(frame) not in frame_to_pos:
        raise ValueError(f"frame {frame} is not on the clip")
    pos_i = int(frame_to_pos[int(frame)])
    only = [int(frame)]
    best = clone_pose_map(poses)
    best_frac = frame_leftover_extra(experiment, best, pos_i)
    kept: list[dict[str, Any]] = []
    for row in insert_rows:
        kind = str(row.get("kind") or "")
        if kind == "bilateral":
            child_a = str(row["childA"])
            child_b = str(row["childB"])
            missing = [name for name in (child_a, child_b) if name not in names]
            if missing:
                raise ValueError(f"insert children {missing} are not on the skeleton")
            pair_best = best
            pair_frac = best_frac
            pair_row: dict[str, Any] | None = None
            for axis in ANATOMICAL_AXES:
                for step in SYMMETRIC_BONE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        applied = rotate_bilateral_pair_deg_shared(
                            trial,
                            bone_a=child_a,
                            bone_b=child_b,
                            frames=only,
                            axis=axis,
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                            rest_rotations=rest_rotations,
                            model_frame=model_frame,
                            bone_dirs={
                                child_a: origins[child_a] - origins[str(row["parentA"])],
                                child_b: origins[child_b] - origins[str(row["parentB"])],
                            },
                        )
                    except ValueError:
                        continue
                    frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not symmetric_bone_trial_better(pair_frac, frac):
                        continue
                    pair_best = trial
                    pair_frac = frac
                    pair_row = {
                        "kind": "bilateral",
                        "groupA": str(row["groupA"]),
                        "groupB": str(row["groupB"]),
                        "boneA": child_a,
                        "boneB": child_b,
                        "axis": axis,
                        "stepDeg": float(step),
                        "appliedDeg": float(applied),
                        "leftover": float(frac.leftover),
                        "extra": float(frac.extra),
                    }
            best = pair_best
            best_frac = pair_frac
            if pair_row is not None:
                kept.append(pair_row)
            continue
        if kind == "central":
            child = str(row["child"])
            if child not in names:
                raise ValueError(f"insert child {child} is not on the skeleton")
            bone_best = best
            bone_frac = best_frac
            bone_row: dict[str, Any] | None = None
            for axis in ANATOMICAL_AXES:
                for step in SYMMETRIC_BONE_STEPS_DEG:
                    trial = clone_pose_map(best)
                    try:
                        applied = rotate_bone_model_axis_deg_shared(
                            trial,
                            joint=child,
                            frames=only,
                            rest_rotation=rest_rotations[str(child)],
                            axis_world=bone_anatomical_axes(
                                origins[child] - origins[str(row["parent"])],
                                model_frame,
                            )[str(axis)],
                            delta_deg=float(step),
                            joint_limit_deg=limit,
                        )
                    except ValueError:
                        continue
                    frac = frame_leftover_extra(experiment, trial, pos_i)
                    if not symmetric_bone_trial_better(bone_frac, frac):
                        continue
                    bone_best = trial
                    bone_frac = frac
                    bone_row = {
                        "kind": "central",
                        "group": str(row["group"]),
                        "bone": child,
                        "axis": axis,
                        "stepDeg": float(step),
                        "appliedDeg": float(applied),
                        "leftover": float(frac.leftover),
                        "extra": float(frac.extra),
                    }
            best = bone_best
            best_frac = bone_frac
            if bone_row is not None:
                kept.append(bone_row)
            continue
        raise ValueError(f"insert row kind {kind!r} is not bilateral or central")
    seed_frac = frame_leftover_extra(experiment, poses, pos_i)
    return best, {
        "frame": int(frame),
        "seedLeftover": float(seed_frac.leftover),
        "seedExtra": float(seed_frac.extra),
        "leftover": float(best_frac.leftover),
        "extra": float(best_frac.extra),
        "kept": kept,
        "copiedFromPrevious": True,
        "independentPerFrameSearch": False,
        "temporalWrap": False,
        "sameRoundReaim": True,
    }


def search_asymmetric_rest_length(
    clip_path: Path,
    mesh_path: Path,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    representative: int,
    round_dir: Path,
    phase: str,
) -> dict[str, Any]:
    """Lengthen each distal pair bone independently if leftover drops."""
    experiment = None
    try:
        experiment, _payload, _ignore = load_preview_experiment(clip_path, mesh_path)
        names = [str(name) for name in experiment.node_names]
        catalog = anatomy_catalog(payload)
        distal = asymmetric_distal_bones(catalog, names)
        frames = [int(frame) for frame in experiment.frame_indices]
        frame_to_pos = {int(frame): int(pos) for pos, frame in enumerate(frames)}
        if int(representative) not in frame_to_pos:
            raise ValueError(f"representative frame {representative} is not on the clip")
        pos_i = int(frame_to_pos[int(representative)])
        best_frac = frame_leftover_extra(experiment, poses, pos_i)
        seed_frac = best_frac
    finally:
        close_experiment(experiment)
        experiment = None
    kept: list[dict[str, Any]] = []
    snapshot = assert_write_path(round_dir / f"rest_length_snap_{phase}.glb", repo_root=ROOT)
    trial_path = assert_write_path(round_dir / f"rest_length_trial_{phase}.glb", repo_root=ROOT)
    for row in distal:
        bone = str(row["bone"])
        shutil.copy2(mesh_path, snapshot)
        bone_frac = best_frac
        bone_scale = 1.0
        for scale in ASYMMETRIC_REST_LENGTH_SCALES:
            shutil.copy2(snapshot, trial_path)
            doc, blob = load_glb(trial_path)
            node = node_index_by_name(doc, bone)
            scale_bone_rest_translation(doc, blob, joint_node=node, scale=float(scale))
            failed = save_normalized_mesh(trial_path, doc, blob, {})
            if failed:
                raise ValueError(failed)
            trial_exp = None
            try:
                trial_exp, _p, _i = load_preview_experiment(clip_path, trial_path)
                frac = frame_leftover_extra(trial_exp, poses, pos_i)
            finally:
                close_experiment(trial_exp)
            if not symmetric_bone_trial_better(bone_frac, frac):
                continue
            shutil.copy2(trial_path, mesh_path)
            bone_frac = frac
            bone_scale = float(scale)
            best_frac = frac
        if bone_scale != 1.0:
            kept.append(
                {
                    "group": str(row["group"]),
                    "bone": bone,
                    "scale": bone_scale,
                    "leftover": float(bone_frac.leftover),
                    "extra": float(bone_frac.extra),
                }
            )
    return {
        "representativeFrame": int(representative),
        "seedLeftover": float(seed_frac.leftover),
        "seedExtra": float(seed_frac.extra),
        "leftover": float(best_frac.leftover),
        "extra": float(best_frac.extra),
        "kept": kept,
        "scales": [float(scale) for scale in ASYMMETRIC_REST_LENGTH_SCALES],
    }


def operate_symmetric_bone_fit(
    *,
    round_dir: Path,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    mesh_path: Path,
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    after_mesh: Path,
    after_poses_path: Path,
    after_png: Path,
    details: dict[str, Any],
    class_name: str,
    operator: str,
) -> dict[str, Any]:
    """Anatomy stage 4: mirrored coarse Euler on the T-pose phase rests.

    Does not redo T-pose, snip, or anatomy rotation. Move frames start at
    identity joints with the kept motion root. Idle stays on the perch rest.
    """
    prefix, suffix = idle_band_from_payload(payload)
    frame_indices = [int(frame) for frame in experiment.frame_indices]
    clip_path = payload.get("_workClip")
    if not clip_path:
        details["rejectedReason"] = "symmetric bone fit needs the work clip path"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    abbreviated = bool(payload.get("_abbreviatedSymmetricOnly"))
    source_id = str(payload.get("_architectureSource") or "")
    try:
        if abbreviated and not source_id:
            raise ValueError("symmetric_only requires --architecture-source")
        if source_id:
            source_round = architecture_source_round(round_dir.parent, source_id)
        else:
            source_round = last_architecture_round_dir(round_dir.parent)
            if source_round is None:
                raise ValueError("symmetric bone fit needs a prior architecture round")
        tpose_src = fly_rest_tpose_source(source_round, allow_symmetric_standin=abbreviated)
    except ValueError as exc:
        details["rejectedReason"] = str(exc)
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    required = (
        "fly_rest_takeoff.glb",
        "fly_rest_cruise.glb",
        "fly_rest_landing.glb",
        "perch_rest.glb",
    )
    copied: dict[str, str] = {}
    dest_tpose = assert_write_path(round_dir / "fly_rest_tpose.glb", repo_root=ROOT)
    shutil.copy2(tpose_src, dest_tpose)
    copied["fly_rest_tpose.glb"] = str(dest_tpose.resolve()).replace("\\", "/")
    for name in required:
        src = source_round / name
        if not src.is_file():
            details["rejectedReason"] = f"architecture round missing {name}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        dest = assert_write_path(round_dir / name, repo_root=ROOT)
        shutil.copy2(src, dest)
        copied[str(name)] = str(dest.resolve()).replace("\\", "/")
    shutil.copy2(source_round / "perch_rest.glb", after_mesh)
    idle_poses = clone_pose_map(poses)
    fly_poses = identity_joint_keep_root_poses(idle_poses, frame_indices)
    write_after_poses(
        after_poses_path, idle_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    groups = flight_phase_groups(
        [
            int(frame)
            for frame in move_frame_positions(len(frame_indices), int(prefix), int(suffix))
        ],
        prefix=prefix,
        suffix=suffix,
        frame_count=len(frame_indices),
    )
    phase_paths = {
        "takeoff": round_dir / "fly_rest_takeoff.glb",
        "cruise": round_dir / "fly_rest_cruise.glb",
        "landing": round_dir / "fly_rest_landing.glb",
    }
    phase_search: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        group_frames = [int(frame) for frame in groups.get(phase) or ()]
        if not group_frames:
            details["rejectedReason"] = f"symmetric bone fit missing frames for {phase}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        if phase not in reps:
            details["rejectedReason"] = f"symmetric bone fit missing representative for {phase}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            fly_poses, search_row = search_symmetric_bones_on_experiment(
                fly_experiment,
                payload,
                fly_poses,
                phase_frames=group_frames,
                representative=int(reps[phase]),
            )
            phase_search[str(phase)] = search_row
        except ValueError as exc:
            details["rejectedReason"] = f"symmetric bone fit failed on {phase}: {exc}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        finally:
            close_experiment(fly_experiment)
    fly_poses_path = round_dir / "fly_symmetric_poses.json"
    write_after_poses(
        fly_poses_path, fly_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    phase_bundles: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            phase_bundles[str(phase)] = raster_bundle(
                fly_experiment,
                fly_poses,
                round_dir / f"raster_{phase}",
            )
        finally:
            close_experiment(fly_experiment)
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices))
        for frame in frame_indices
    ]
    after_raster = composite_phase_rest_bundle(
        perch=before,
        phase_bundles=phase_bundles,
        sources=sources,
        png_dir=after_png,
        frames=frame_indices,
    )
    details["architecture"] = "symmetric_only" if abbreviated else "symmetric_bone_fit"
    details["anatomyFitPipeline"] = list(ANATOMY_FIT_STAGES)
    if abbreviated:
        details["anatomyFitCompleted"] = []
        details["anatomyFitStage"] = "symmetric_only"
        details["abbreviatedSymmetricOnly"] = True
        details["skipAsymmetric"] = True
        details["skipMeshBoneRepair"] = True
        details["snipTposeBridges"] = False
        details["insertMissingSymmetric"] = False
        details["asymmetricFineTune"] = False
        details["sharedSkeletonTemporal"] = False
    else:
        details["anatomyFitCompleted"] = list(ANATOMY_FIT_STAGES[:4])
        details["anatomyFitStage"] = ANATOMY_FIT_STAGES[3]
        details["abbreviatedSymmetricOnly"] = False
    details["earlySymmetry"] = True
    details["wingDivergence"] = False
    details["identityJointsOnMove"] = False
    details["keepRootOnMove"] = True
    details["preservePipelinePoses"] = True
    details["copiedRests"] = copied
    details["phaseRests"] = {
        str(phase): str(path.resolve()).replace("\\", "/") for phase, path in phase_paths.items()
    }
    details["perchRest"] = copied["perch_rest.glb"]
    details["sharedSymmetricRest"] = copied["fly_rest_tpose.glb"]
    details["representatives"] = {str(name): int(frame) for name, frame in reps.items()}
    details["frameRestSources"] = sources
    details["flySymmetricPoses"] = str(fly_poses_path.resolve()).replace("\\", "/")
    details["symmetricBoneSearch"] = phase_search
    details["stepsDeg"] = [float(step) for step in SYMMETRIC_BONE_STEPS_DEG]
    details["notOccupancyGate"] = True
    details["sourceArchitectureRound"] = source_round.name
    details["chatStills"] = write_phase_chat_stills(round_dir, after_png, reps)
    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": after_mesh,
        "poses": idle_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": Path(before["pngDir"]),
        "afterPng": after_png,
        "afterRaster": after_raster,
        "needsReload": False,
        "skipVisionCheck": True,
        "skipReloadOccupancy": True,
        "sprites": sprites,
        "insertName": None,
    }


def operate_asymmetric_fine_tune(
    *,
    round_dir: Path,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    mesh_path: Path,
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    after_mesh: Path,
    after_poses_path: Path,
    after_png: Path,
    details: dict[str, Any],
    class_name: str,
    operator: str,
) -> dict[str, Any]:
    """Anatomy stage 5: independent coarse Euler, then distal rest-length.

    Seeds from the last round's mirrored fly poses. Idle stays on the perch
    rest. Phase fly rests may diverge.
    """
    prefix, suffix = idle_band_from_payload(payload)
    frame_indices = [int(frame) for frame in experiment.frame_indices]
    clip_path = payload.get("_workClip")
    if not clip_path:
        details["rejectedReason"] = "asymmetric fine-tune needs the work clip path"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    source_round = last_architecture_round_dir(round_dir.parent)
    if source_round is None:
        details["rejectedReason"] = "asymmetric fine-tune needs a prior architecture round"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    seed_poses_path = source_round / "fly_symmetric_poses.json"
    if not seed_poses_path.is_file():
        details["rejectedReason"] = "asymmetric fine-tune needs fly_symmetric_poses.json"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    required = (
        "fly_rest_tpose.glb",
        "fly_rest_takeoff.glb",
        "fly_rest_cruise.glb",
        "fly_rest_landing.glb",
        "perch_rest.glb",
    )
    copied: dict[str, str] = {}
    for name in required:
        src = source_round / name
        if not src.is_file():
            details["rejectedReason"] = f"architecture round missing {name}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        dest = assert_write_path(round_dir / name, repo_root=ROOT)
        shutil.copy2(src, dest)
        copied[str(name)] = str(dest.resolve()).replace("\\", "/")
    shutil.copy2(source_round / "perch_rest.glb", after_mesh)
    idle_poses = clone_pose_map(poses)
    fly_poses = load_pose_map_from_after_poses(seed_poses_path)
    write_after_poses(
        after_poses_path, idle_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    groups = flight_phase_groups(
        [
            int(frame)
            for frame in move_frame_positions(len(frame_indices), int(prefix), int(suffix))
        ],
        prefix=prefix,
        suffix=suffix,
        frame_count=len(frame_indices),
    )
    phase_paths = {
        "takeoff": round_dir / "fly_rest_takeoff.glb",
        "cruise": round_dir / "fly_rest_cruise.glb",
        "landing": round_dir / "fly_rest_landing.glb",
    }
    phase_search: dict[str, Any] = {}
    phase_length: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        group_frames = [int(frame) for frame in groups.get(phase) or ()]
        if not group_frames:
            details["rejectedReason"] = f"asymmetric fine-tune missing frames for {phase}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        if phase not in reps:
            details["rejectedReason"] = f"asymmetric fine-tune missing representative for {phase}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            fly_poses, search_row = search_asymmetric_bones_on_experiment(
                fly_experiment,
                payload,
                fly_poses,
                phase_frames=group_frames,
                representative=int(reps[phase]),
            )
            phase_search[str(phase)] = search_row
        except ValueError as exc:
            details["rejectedReason"] = f"asymmetric Euler failed on {phase}: {exc}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        finally:
            close_experiment(fly_experiment)
        try:
            phase_length[str(phase)] = search_asymmetric_rest_length(
                Path(clip_path),
                Path(path),
                payload,
                fly_poses,
                representative=int(reps[phase]),
                round_dir=round_dir,
                phase=str(phase),
            )
        except ValueError as exc:
            details["rejectedReason"] = f"asymmetric rest-length failed on {phase}: {exc}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
    fly_poses_path = round_dir / "fly_asymmetric_poses.json"
    write_after_poses(
        fly_poses_path, fly_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    phase_bundles: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            phase_bundles[str(phase)] = raster_bundle(
                fly_experiment,
                fly_poses,
                round_dir / f"raster_{phase}",
            )
        finally:
            close_experiment(fly_experiment)
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices))
        for frame in frame_indices
    ]
    after_raster = composite_phase_rest_bundle(
        perch=before,
        phase_bundles=phase_bundles,
        sources=sources,
        png_dir=after_png,
        frames=frame_indices,
    )
    details["architecture"] = "asymmetric_fine_tune"
    details["anatomyFitPipeline"] = list(ANATOMY_FIT_STAGES)
    details["anatomyFitCompleted"] = list(ANATOMY_FIT_STAGES[:5])
    details["anatomyFitStage"] = ANATOMY_FIT_STAGES[4]
    details["earlySymmetry"] = False
    details["wingDivergence"] = True
    details["identityJointsOnMove"] = False
    details["keepRootOnMove"] = True
    details["preservePipelinePoses"] = True
    details["copiedRests"] = copied
    details["phaseRests"] = {
        str(phase): str(path.resolve()).replace("\\", "/") for phase, path in phase_paths.items()
    }
    details["perchRest"] = copied["perch_rest.glb"]
    details["sharedSymmetricRest"] = copied["fly_rest_tpose.glb"]
    details["representatives"] = {str(name): int(frame) for name, frame in reps.items()}
    details["frameRestSources"] = sources
    details["flyAsymmetricPoses"] = str(fly_poses_path.resolve()).replace("\\", "/")
    details["seedPoses"] = str(seed_poses_path.resolve()).replace("\\", "/")
    details["asymmetricBoneSearch"] = phase_search
    details["asymmetricRestLength"] = phase_length
    details["stepsDeg"] = [float(step) for step in SYMMETRIC_BONE_STEPS_DEG]
    details["restLengthScales"] = [float(scale) for scale in ASYMMETRIC_REST_LENGTH_SCALES]
    details["notOccupancyGate"] = True
    details["sourceArchitectureRound"] = source_round.name
    details["chatStills"] = write_phase_chat_stills(round_dir, after_png, reps)
    details["compareStills"] = write_readable_compare_stills(
        round_dir=round_dir,
        sprites=sprites,
        before_png=Path(before["pngDir"]),
        after_png=after_png,
        frames=frame_indices,
        representatives=reps,
    )
    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": after_mesh,
        "poses": idle_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": Path(before["pngDir"]),
        "afterPng": after_png,
        "afterRaster": after_raster,
        "needsReload": False,
        "skipVisionCheck": True,
        "skipReloadOccupancy": True,
        "sprites": sprites,
        "insertName": None,
    }


def operate_shared_skeleton_temporal(
    *,
    round_dir: Path,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    mesh_path: Path,
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    after_mesh: Path,
    after_poses_path: Path,
    after_png: Path,
    details: dict[str, Any],
    class_name: str,
    operator: str,
) -> dict[str, Any]:
    """Walk move frames from pipeline-relative joints, leftover-search with strain veto.

    Concatenated idle/move does not wrap. Leftover occupancy cannot see LBS melt;
    strain growth past cascade slack is illegal. Seed is pipeline[frame] minus
    the phase representative, because the fly rest already contains that
    representative. Inertial leftover from leftover-asymmetric Euler is what
    exploded joints to 200°+.
    """
    prefix, suffix = idle_band_from_payload(payload)
    frame_indices = [int(frame) for frame in experiment.frame_indices]
    clip_path = payload.get("_workClip")
    if not clip_path:
        details["rejectedReason"] = "shared-skeleton temporal needs the work clip path"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    rest_round = last_round_with_architecture(round_dir.parent, "anatomy_tpose_snip_rotation")
    if rest_round is None:
        details["rejectedReason"] = "shared-skeleton temporal needs anatomy_tpose_snip_rotation rests"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    identity_poses_path = rest_round / "fly_identity_poses.json"
    if not identity_poses_path.is_file():
        details["rejectedReason"] = "shared-skeleton temporal needs fly_identity_poses.json"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    pipeline_path = round_dir.parent / "round_00" / "gpu_clip_result.json"
    if not pipeline_path.is_file():
        details["rejectedReason"] = "shared-skeleton temporal needs round_00 pipeline poses"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    required = (
        "fly_rest_tpose.glb",
        "fly_rest_takeoff.glb",
        "fly_rest_cruise.glb",
        "fly_rest_landing.glb",
        "perch_rest.glb",
    )
    copied: dict[str, str] = {}
    for name in required:
        src = rest_round / name
        if not src.is_file():
            details["rejectedReason"] = f"architecture round missing {name}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        dest = assert_write_path(round_dir / name, repo_root=ROOT)
        shutil.copy2(src, dest)
        copied[str(name)] = str(dest.resolve()).replace("\\", "/")
    shutil.copy2(rest_round / "perch_rest.glb", after_mesh)
    idle_poses = clone_pose_map(poses)
    fly_poses = load_pose_map_from_after_poses(identity_poses_path)
    pipeline_poses = load_pose_map_from_after_poses(pipeline_path)
    write_after_poses(
        after_poses_path, idle_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    move_frames = [
        int(frame)
        for frame in move_frame_positions(len(frame_indices), int(prefix), int(suffix))
    ]
    if len(move_frames) < 2:
        details["rejectedReason"] = "shared-skeleton temporal needs at least two move frames"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    unique_before = unique_joint_pose_count(fly_poses, move_frames)
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    limit = joint_limit_deg(payload)
    for frame in move_frames:
        phase = frame_rest_source(
            int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices)
        )
        if phase not in reps:
            details["rejectedReason"] = f"no phase representative for {phase}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        seed_frame_pipeline_relative(
            fly_poses,
            pipeline_poses,
            dest_frame=int(frame),
            reference_frame=int(reps[str(phase)]),
            joint_limit_deg=limit,
        )
    phase_paths = {
        "takeoff": round_dir / "fly_rest_takeoff.glb",
        "cruise": round_dir / "fly_rest_cruise.glb",
        "landing": round_dir / "fly_rest_landing.glb",
    }
    loaded: dict[str, Any] = {}
    frame_rows: list[dict[str, Any]] = []
    try:
        for phase, path in phase_paths.items():
            loaded[str(phase)], _payload, _ignore = load_preview_experiment(
                Path(clip_path), Path(path)
            )
        for frame in move_frames:
            phase = frame_rest_source(
                int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices)
            )
            if phase not in loaded:
                raise ValueError(f"no fly rest loaded for phase {phase}")
            fly_poses, row = search_one_frame_leftover(
                loaded[str(phase)],
                payload,
                fly_poses,
                frame=int(frame),
            )
            row["phase"] = str(phase)
            row["pipelineReferenceFrame"] = int(reps[str(phase)])
            row["seededFromInertial"] = False
            row["pipelineRelativeSeed"] = True
            frame_rows.append(row)
    except ValueError as exc:
        details["rejectedReason"] = str(exc)
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    finally:
        for fly_experiment in loaded.values():
            close_experiment(fly_experiment)
    unique_after = unique_joint_pose_count(fly_poses, move_frames)
    if unique_after <= unique_before:
        details["rejectedReason"] = (
            f"temporal walk did not unfreeze joints ({unique_after} unique poses, "
            f"was {unique_before})"
        )
        details["uniqueJointPosesBefore"] = int(unique_before)
        details["uniqueJointPosesAfter"] = int(unique_after)
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    fly_poses_path = round_dir / "fly_temporal_poses.json"
    write_after_poses(
        fly_poses_path, fly_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    phase_bundles: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            phase_bundles[str(phase)] = raster_bundle(
                fly_experiment,
                fly_poses,
                round_dir / f"raster_{phase}",
            )
        finally:
            close_experiment(fly_experiment)
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices))
        for frame in frame_indices
    ]
    after_raster = composite_phase_rest_bundle(
        perch=before,
        phase_bundles=phase_bundles,
        sources=sources,
        png_dir=after_png,
        frames=frame_indices,
    )
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    details["architecture"] = "shared_skeleton_temporal"
    details["anatomyFitPipeline"] = list(ANATOMY_FIT_STAGES)
    details["anatomyFitCompleted"] = list(ANATOMY_FIT_STAGES[:6])
    details["anatomyFitStage"] = ANATOMY_FIT_STAGES[5]
    details["earlySymmetry"] = False
    details["wingDivergence"] = True
    details["identityJointsOnMove"] = False
    details["keepRootOnMove"] = True
    details["preservePipelinePoses"] = True
    details["temporalWrap"] = False
    details["independentPerFrameSearch"] = False
    details["inertialSeed"] = False
    details["pipelineRelativeSeed"] = True
    details["strainVeto"] = True
    details["coarseCombinedAxes"] = True
    details["collisionBoundPrune"] = True
    details["substantialKeep"] = True
    details["copiedRests"] = copied
    details["phaseRests"] = {
        str(phase): str(path.resolve()).replace("\\", "/") for phase, path in phase_paths.items()
    }
    details["perchRest"] = copied["perch_rest.glb"]
    details["representatives"] = {str(name): int(frame) for name, frame in reps.items()}
    details["frameRestSources"] = sources
    details["flyTemporalPoses"] = str(fly_poses_path.resolve()).replace("\\", "/")
    details["seedPoses"] = str(identity_poses_path.resolve()).replace("\\", "/")
    details["pipelinePoses"] = str(pipeline_path.resolve()).replace("\\", "/")
    details["temporalFrames"] = frame_rows
    details["uniqueJointPosesBefore"] = int(unique_before)
    details["uniqueJointPosesAfter"] = int(unique_after)
    details["moveFrames"] = move_frames
    details["notOccupancyGate"] = True
    details["sourceArchitectureRound"] = rest_round.name
    details["chatStills"] = write_phase_chat_stills(round_dir, after_png, reps)
    details["compareStills"] = write_readable_compare_stills(
        round_dir=round_dir,
        sprites=sprites,
        before_png=Path(before["pngDir"]),
        after_png=after_png,
        frames=frame_indices,
        representatives=reps,
    )
    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": after_mesh,
        "poses": idle_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": Path(before["pngDir"]),
        "afterPng": after_png,
        "afterRaster": after_raster,
        "needsReload": False,
        "skipVisionCheck": True,
        "skipReloadOccupancy": True,
        "sprites": sprites,
        "insertName": None,
    }


def insert_symmetric_rows_on_glb(
    src: Path,
    dest: Path,
    rows: Sequence[Mapping[str, Any]],
    verts_by_parent: Mapping[str, Sequence[int]],
    *,
    details: dict[str, Any],
) -> list[dict[str, Any]]:
    """Insert catalog-named children and rebind leftover unique-region verts."""
    doc, blob = load_glb(src)
    rest = primitive_rest_positions(doc, blob)
    existing = {str(node.get("name") or "") for node in (doc.get("nodes") or [])}
    written: list[dict[str, Any]] = []
    max_disp = float(REST_SCULPT_MAX_BODY_LENGTHS) * body_extent(rest)
    for row in rows:
        kind = str(row.get("kind") or "")
        parents: list[tuple[str, str]] = []
        if kind == "bilateral":
            parents = [(str(row["parentA"]), str(row["childA"])), (str(row["parentB"]), str(row["childB"]))]
        elif kind == "central":
            parents = [(str(row["parent"]), str(row["child"]))]
        else:
            raise ValueError(f"insert row kind {kind!r} is not bilateral or central")
        for parent, child in parents:
            if child in existing:
                raise ValueError(f"insert child {child} already exists on {src.name}")
            verts = [int(index) for index in (verts_by_parent.get(parent) or ())]
            if not verts:
                raise ValueError(f"insert parent {parent} has no leftover or distal verts")
            parent_node = node_index_by_name(doc, parent)
            centroid = rest[np.asarray(verts, dtype=np.int64)].mean(axis=0)
            origin = rest_parent_origin(doc, blob, parent, rest)
            world = centroid - origin
            if float(np.linalg.norm(world)) > max_disp:
                raise ValueError(
                    f"insert {child} rest translation exceeds rest sculpt displacement cap"
                )
            inserted = insert_child_bone(
                doc,
                blob,
                parent_node=parent_node,
                name=child,
                translation=(float(world[0]), float(world[1]), float(world[2])),
                vertex_indices=verts,
            )
            existing.add(child)
            written.append(
                {
                    "parent": parent,
                    "child": child,
                    "vertexCount": int(inserted["vertexCount"]),
                    "translation": [float(world[0]), float(world[1]), float(world[2])],
                    "mesh": str(dest.name),
                }
            )
    failed = save_normalized_mesh(dest, doc, blob, details)
    if failed:
        raise ValueError(failed)
    return written


def rest_parent_origin(
    doc: Mapping[str, Any],
    blob: bytes,
    parent: str,
    rest: np.ndarray,
) -> np.ndarray:
    """Mean bind-rest of verts whose dominant joint is the parent node."""
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    from sprite_body_surgery import _accessor_array, joint_slot_for_node

    parent_node = node_index_by_name(doc, parent)
    slot = joint_slot_for_node(doc, parent_node)
    joints = _accessor_array(doc, blob, int(prim["attributes"]["JOINTS_0"])).astype(np.int64)
    weights = _accessor_array(doc, blob, int(prim["attributes"]["WEIGHTS_0"])).astype(np.float64)
    idxs = []
    for vertex in range(int(weights.shape[0])):
        dominant = int(np.argmax(weights[vertex]))
        if int(joints[vertex, dominant]) == int(slot):
            idxs.append(vertex)
    if not idxs:
        raise ValueError(f"parent {parent} owns no rest verts")
    return rest[np.asarray(idxs, dtype=np.int64)].mean(axis=0)


def operate_insert_missing_symmetric(
    *,
    round_dir: Path,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    mesh_path: Path,
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    after_mesh: Path,
    after_poses_path: Path,
    after_png: Path,
    details: dict[str, Any],
    class_name: str,
    operator: str,
) -> dict[str, Any]:
    """Anatomy stage 6: leftover unique-region → paired insert + same-round re-aim.

    Idle stays on the perch rest. Fly GLBs gain the same named children.
    """
    prefix, suffix = idle_band_from_payload(payload)
    frame_indices = [int(frame) for frame in experiment.frame_indices]
    clip_path = payload.get("_workClip")
    if not clip_path:
        details["rejectedReason"] = "insert-missing-symmetric needs the work clip path"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    source_round = last_architecture_round_dir(round_dir.parent)
    if source_round is None:
        details["rejectedReason"] = "insert-missing-symmetric needs a prior architecture round"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    seed_poses_path = source_round / "fly_temporal_poses.json"
    if not seed_poses_path.is_file():
        details["rejectedReason"] = "insert-missing-symmetric needs fly_temporal_poses.json"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    required = (
        "fly_rest_tpose.glb",
        "fly_rest_takeoff.glb",
        "fly_rest_cruise.glb",
        "fly_rest_landing.glb",
        "perch_rest.glb",
    )
    copied: dict[str, str] = {}
    for name in required:
        src = source_round / name
        if not src.is_file():
            details["rejectedReason"] = f"architecture round missing {name}"
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        dest = assert_write_path(round_dir / name, repo_root=ROOT)
        shutil.copy2(src, dest)
        copied[str(name)] = str(dest.resolve()).replace("\\", "/")
    shutil.copy2(source_round / "perch_rest.glb", after_mesh)
    idle_poses = clone_pose_map(poses)
    fly_poses = load_pose_map_from_after_poses(seed_poses_path)
    write_after_poses(
        after_poses_path, idle_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    move_frames = [
        int(frame)
        for frame in move_frame_positions(len(frame_indices), int(prefix), int(suffix))
    ]
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    phase_paths = {
        "takeoff": round_dir / "fly_rest_takeoff.glb",
        "cruise": round_dir / "fly_rest_cruise.glb",
        "landing": round_dir / "fly_rest_landing.glb",
    }
    catalog = anatomy_catalog(payload)
    unique_bones: list[str] = []
    verts_by_parent: dict[str, list[int]] = {}
    classify_rows: list[dict[str, Any]] = []
    classify_snaps: list[dict[str, Any]] = []
    insert_rows: list[dict[str, Any]] = []
    insert_written: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    try:
        for phase, path in phase_paths.items():
            fly_experiment = None
            try:
                fly_experiment, _payload, _ignore = load_preview_experiment(
                    Path(clip_path), Path(path)
                )
                if int(reps[phase]) not in [int(frame) for frame in fly_experiment.frame_indices]:
                    raise ValueError(f"representative {reps[phase]} is not on the clip")
                bundle = raster_bundle(
                    fly_experiment, fly_poses, round_dir / f"raster_classify_{phase}"
                )
                pos_i = [int(frame) for frame in fly_experiment.frame_indices].index(int(reps[phase]))
                leftover = np.asarray(bundle["leftoverMasks"][pos_i], dtype=bool)
                extra = np.asarray(bundle["extraMasks"][pos_i], dtype=bool)
                sprite = fly_experiment.target_masks[pos_i].detach().cpu().numpy() > 0.5
                leftover_ys, leftover_xs = np.nonzero(leftover)
                joints_xy = anatomy_joints_xy(
                    catalog, project_all_joints(fly_experiment, bundle, pos_i)
                )
                bones = unique_region_bones_from_pixels(leftover_xs, leftover_ys, joints_xy)
                for bone in bones:
                    if bone not in unique_bones:
                        unique_bones.append(bone)
                rest, _blends, _rotation = recover_root_and_lbs(fly_experiment, bundle, pos_i)
                owner_names = vertex_dominant_owner_names(fly_experiment)
                xs_v, ys_v = project_points(
                    fly_experiment, posed_first_primitive(fly_experiment, bundle, pos_i)
                )
                doc, _blob = load_glb(path)
                keel_origin = node_world_translation(doc, anatomy_landmark_bone(catalog, "keel"))
                classify_rows.append(
                    {
                        "phase": str(phase),
                        "frame": int(reps[phase]),
                        "uniqueBones": list(bones),
                        "leftoverPixels": int(leftover_xs.size),
                    }
                )
                classify_snaps.append(
                    {
                        "leftover": leftover,
                        "extra": extra,
                        "sprite": sprite,
                        "xs": xs_v,
                        "ys": ys_v,
                        "ownerNames": list(owner_names),
                        "rest": rest,
                        "keelOrigin": keel_origin,
                    }
                )
            finally:
                close_experiment(fly_experiment)
        insert_rows = leftover_symmetric_insert_parents(catalog, unique_bones)
        parents: list[str] = []
        for row in insert_rows:
            if str(row["kind"]) == "bilateral":
                parents.extend([str(row["parentA"]), str(row["parentB"])])
            else:
                parents.append(str(row["parent"]))
        for snap in classify_snaps:
            for parent in parents:
                allow = occupancy_unique_owner_allow(snap["ownerNames"], [parent])
                _deltas, affected = occupancy_vertex_deltas_px(
                    snap["xs"],
                    snap["ys"],
                    snap["leftover"],
                    snap["extra"],
                    snap["sprite"],
                    max_assign_px=OCCUPANCY_REST_FILL_MAX_ASSIGN_PX,
                    fill_leftover=True,
                    shrink_extra=False,
                    owner_allow=allow,
                )
                chosen = [int(vertex) for vertex in np.nonzero(affected)[0]]
                if not chosen:
                    chosen = distal_owner_vertex_indices(
                        snap["rest"], snap["ownerNames"], parent, snap["keelOrigin"]
                    )
                verts_by_parent.setdefault(parent, [])
                for vertex in chosen:
                    if vertex not in verts_by_parent[parent]:
                        verts_by_parent[parent].append(vertex)
        mesh_targets = [
            round_dir / "fly_rest_tpose.glb",
            round_dir / "fly_rest_takeoff.glb",
            round_dir / "fly_rest_cruise.glb",
            round_dir / "fly_rest_landing.glb",
        ]
        for path in mesh_targets:
            insert_written.extend(
                insert_symmetric_rows_on_glb(
                    path,
                    path,
                    insert_rows,
                    verts_by_parent,
                    details=details,
                )
            )
        loaded: dict[str, Any] = {}
        frame_rows: list[dict[str, Any]] = []
        try:
            for phase, path in phase_paths.items():
                loaded[str(phase)], _payload, _ignore = load_preview_experiment(
                    Path(clip_path), Path(path)
                )
            prev: int | None = None
            for frame in move_frames:
                phase = frame_rest_source(
                    int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices)
                )
                if phase not in loaded:
                    raise ValueError(f"no fly rest loaded for phase {phase}")
                if prev is not None:
                    copy_joints_keep_dest_root(
                        fly_poses, dest_frame=int(frame), src_frame=int(prev)
                    )
                fly_poses, row = search_one_frame_insert_bones(
                    loaded[str(phase)],
                    payload,
                    fly_poses,
                    frame=int(frame),
                    insert_rows=insert_rows,
                )
                row["phase"] = str(phase)
                row["copiedFromFrame"] = None if prev is None else int(prev)
                frame_rows.append(row)
                prev = int(frame)
        finally:
            for fly_experiment in loaded.values():
                close_experiment(fly_experiment)
    except ValueError as exc:
        details["rejectedReason"] = str(exc)
        details["leftoverUniqueBones"] = unique_bones
        details["leftoverClassify"] = classify_rows
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    fly_poses_path = round_dir / "fly_insert_poses.json"
    write_after_poses(
        fly_poses_path, fly_poses, frame_indices=frame_indices, camera_fit_path=camera_fit
    )
    phase_bundles: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            phase_bundles[str(phase)] = raster_bundle(
                fly_experiment,
                fly_poses,
                round_dir / f"raster_{phase}",
            )
        finally:
            close_experiment(fly_experiment)
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices))
        for frame in frame_indices
    ]
    after_raster = composite_phase_rest_bundle(
        perch=before,
        phase_bundles=phase_bundles,
        sources=sources,
        png_dir=after_png,
        frames=frame_indices,
    )
    details["architecture"] = "insert_missing_symmetric"
    details["anatomyFitPipeline"] = list(ANATOMY_FIT_STAGES)
    details["anatomyFitCompleted"] = list(ANATOMY_FIT_STAGES[:7])
    details["anatomyFitStage"] = ANATOMY_FIT_STAGES[6]
    details["earlySymmetry"] = True
    details["wingDivergence"] = False
    details["identityJointsOnMove"] = False
    details["keepRootOnMove"] = True
    details["preservePipelinePoses"] = True
    details["temporalWrap"] = False
    details["independentPerFrameSearch"] = False
    details["sameRoundReaim"] = True
    details["copiedRests"] = copied
    details["phaseRests"] = {
        str(phase): str(path.resolve()).replace("\\", "/") for phase, path in phase_paths.items()
    }
    details["perchRest"] = copied["perch_rest.glb"]
    details["representatives"] = {str(name): int(frame) for name, frame in reps.items()}
    details["frameRestSources"] = sources
    details["flyInsertPoses"] = str(fly_poses_path.resolve()).replace("\\", "/")
    details["seedPoses"] = str(seed_poses_path.resolve()).replace("\\", "/")
    details["leftoverUniqueBones"] = unique_bones
    details["leftoverClassify"] = classify_rows
    details["insertRows"] = insert_rows
    details["insertWritten"] = insert_written
    details["insertChildNames"] = [
        str(row["childA"]) if str(row.get("kind")) == "bilateral" else str(row["child"])
        for row in insert_rows
    ] + [
        str(row["childB"])
        for row in insert_rows
        if str(row.get("kind")) == "bilateral"
    ]
    if insert_rows and str(insert_rows[0].get("kind")) == "bilateral":
        if insert_rows[0]["childA"] != insert_child_bone_name(str(insert_rows[0]["groupA"])):
            raise ValueError("insert child name drifted from insert_child_bone_name")
    details["vertsByParent"] = {name: list(idxs) for name, idxs in verts_by_parent.items()}
    details["temporalFrames"] = frame_rows
    details["moveFrames"] = move_frames
    details["notOccupancyGate"] = True
    details["sourceArchitectureRound"] = source_round.name
    details["chatStills"] = write_phase_chat_stills(round_dir, after_png, reps)
    details["compareStills"] = write_readable_compare_stills(
        round_dir=round_dir,
        sprites=sprites,
        before_png=Path(before["pngDir"]),
        after_png=after_png,
        frames=frame_indices,
        representatives=reps,
    )
    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": after_mesh,
        "poses": idle_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": Path(before["pngDir"]),
        "afterPng": after_png,
        "afterRaster": after_raster,
        "needsReload": False,
        "skipVisionCheck": True,
        "skipReloadOccupancy": True,
        "sprites": sprites,
        "insertName": None,
    }


def write_readable_compare_stills(
    *,
    round_dir: Path,
    sprites: Sequence[Path],
    before_png: Path,
    after_png: Path,
    frames: Sequence[int],
    representatives: Mapping[str, int],
) -> dict[str, str]:
    dest = assert_write_path(round_dir / "chat_stills", repo_root=ROOT)
    dest.mkdir(parents=True, exist_ok=True)
    named = {"idle": 0, **{str(name): int(frame) for name, frame in representatives.items()}}
    index_by_frame = {int(frame): int(pos) for pos, frame in enumerate(frames)}
    paths: dict[str, str] = {}
    for name, frame in named.items():
        pos = index_by_frame.get(int(frame))
        if pos is None:
            raise ValueError(f"compare still frame {frame} is not on the clip")
        sprite = Image.open(sprites[pos]).convert("RGB")
        before = Image.open(Path(before_png) / f"{int(frame):02d}.png").convert("RGB")
        after = Image.open(Path(after_png) / f"{int(frame):02d}.png").convert("RGB")

        def _nn(image: Image.Image) -> Image.Image:
            scale = max(1, round(sprite.height / max(image.height, 1)))
            return image.resize((image.width * scale, image.height * scale), Image.NEAREST)

        before = _nn(before)
        after = _nn(after)
        header = 28
        height = max(sprite.height, before.height, after.height)
        width = sprite.width + before.width + after.width
        canvas = Image.new("RGB", (width, height + header), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        x = 0
        for label, image in (("sprite", sprite), ("before", before), ("after", after)):
            draw.text((x + 8, 6), f"{label} f{int(frame):02d} {name}", fill=(230, 230, 235))
            canvas.paste(image, (x, header))
            x += image.width
        dest_png = dest / f"compare_f{int(frame):02d}_{name}.png"
        canvas.save(dest_png)
        paths[str(name)] = str(dest_png.resolve()).replace("\\", "/")
    return paths


def operate_phase_baked_fly_rest(
    *,
    round_dir: Path,
    experiment,
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    mesh_path: Path,
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    after_mesh: Path,
    after_poses_path: Path,
    after_png: Path,
    details: dict[str, Any],
    class_name: str,
    operator: str,
) -> dict[str, Any]:
    """Idle keeps the perch rest. Fly rests follow the anatomy-fit pipeline.

    1. T-pose: straighten and spread every catalog bilateral pair (wings
       dorsal, legs ventral), mirrored.
    2. Snip faces whose mixed-anatomy edges exploded from perch to T-pose.
    3. Rotate that one rest per frame from anatomy (climb / cruise / flare,
       ventral onto camera-down). Stage 4 (`symmetric_bone_fit`) then poses
       existing bones as mirrored pairs. Joint identity on move frames is the
       seed for that later stage; the motion root stays.
    """
    prefix, suffix = idle_band_from_payload(payload)
    frame_indices = [int(frame) for frame in experiment.frame_indices]
    clip_path = payload.get("_workClip")
    if not clip_path:
        details["rejectedReason"] = "phase rest bake needs the work clip path"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    names = [str(name) for name in experiment.node_names]
    parents = [
        None if parent is None or int(parent) < 0 else int(parent) for parent in experiment.parents
    ]
    chain = flyer_visual_body_chain(names, parents, catalog=anatomy_catalog(payload))
    origins = bind_joint_origins(experiment)
    missing = [name for name in chain if name not in origins]
    if missing:
        details["rejectedReason"] = f"glide rest missing joints {missing}"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    tail = np.asarray(origins[str(chain[0])], dtype=np.float64)
    head = np.asarray(origins[str(chain[-1])], dtype=np.float64)
    spine = head - tail
    pivot = 0.5 * (head + tail)
    rest = experiment.primitives[0].positions.detach().cpu().numpy().astype(np.float64)
    camera_right = experiment.camera_right.detach().cpu().numpy().astype(np.float64)
    camera_down = experiment.camera_down.detach().cpu().numpy().astype(np.float64)
    catalog = anatomy_catalog(payload)
    anatomy_bilateral_wing_pair(catalog)
    chest = anatomy_ventral_bind_axis(catalog)
    owner_names = vertex_dominant_owner_names(experiment)
    tpose_positions = np.asarray(rest, dtype=np.float64).copy()
    limb_reports: dict[str, Any] = {}
    try:
        for left, right in anatomy_bilateral_pairs(catalog):
            pole = tpose_pole_for_pair(left, right)
            chain_a = anatomy_wing_chain(catalog, left, names)
            chain_b = anatomy_wing_chain(catalog, right, names)
            missing = [
                bone
                for bone in (chain_a[0], chain_a[-1], chain_b[0], chain_b[-1])
                if bone not in origins
            ]
            if missing:
                raise ValueError(f"T-pose pair {left}/{right} missing joints {missing}")
            src_a = np.asarray(origins[chain_a[-1]], dtype=np.float64) - np.asarray(
                origins[chain_a[0]], dtype=np.float64
            )
            src_b = np.asarray(origins[chain_b[-1]], dtype=np.float64) - np.asarray(
                origins[chain_b[0]], dtype=np.float64
            )
            destinations = symmetric_limb_destinations(
                src_a, src_b, spine=spine, ventral=chest, pole=pole
            )
            spread = spread_labeled_wing_vertices(
                tpose_positions,
                origins=origins,
                owner_names=owner_names,
                catalog=catalog,
                names=names,
                destinations=destinations,
                group_a=left,
                group_b=right,
            )
            tpose_positions = np.asarray(spread["positions"], dtype=np.float64)
            limb_reports[f"{left}+{right}"] = {
                "pole": pole,
                "limbs": dict(spread["limbs"]),
            }
        doc, blob = load_glb(mesh_path)
        faces = skinned_triangle_faces(doc, blob)
        snip = tpose_stretched_bridge_faces(
            rest, tpose_positions, faces, owner_names, catalog
        )
    except ValueError as exc:
        details["rejectedReason"] = f"T-pose / snip failed: {exc}"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    cut = set(int(index) for index in snip["faceIndices"].tolist())
    kept_faces = faces[[i for i in range(int(faces.shape[0])) if i not in cut]]
    if kept_faces.shape[0] < 1:
        details["rejectedReason"] = "T-pose snip removed every triangle"
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    symmetric_rest = tpose_positions
    symmetric_mesh = assert_write_path(round_dir / "fly_rest_tpose.glb", repo_root=ROOT)
    replace_positions(doc, blob, symmetric_rest)
    if cut:
        replace_triangle_indices(doc, blob, kept_faces)
    failed = save_normalized_mesh(symmetric_mesh, doc, blob, details)
    if failed:
        details["rejectedReason"] = failed
        return reject_without_mesh(
            round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
        )
    used_poses = clone_pose_map(poses)
    reps = flight_phase_representative_frames(frame_indices, prefix=prefix, suffix=suffix)
    phase_paths: dict[str, str] = {}
    rotations: dict[str, Any] = {}
    for phase, rep_frame in reps.items():
        axis = flight_phase_sprite_axis(
            int(rep_frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices)
        )
        dst_spine = float(axis[0]) * camera_right + float(axis[1]) * camera_down
        rotation = rotation_aligning_bases(spine, chest, dst_spine, camera_down)
        rotated = rotate_points_about_pivot(symmetric_rest, rotation, pivot)
        dest = assert_write_path(round_dir / f"fly_rest_{phase}.glb", repo_root=ROOT)
        doc, blob = load_glb(symmetric_mesh)
        replace_positions(doc, blob, rotated)
        failed = save_normalized_mesh(dest, doc, blob, details)
        if failed:
            details["rejectedReason"] = failed
            return reject_without_mesh(
                round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
            )
        phase_paths[str(phase)] = str(dest.resolve()).replace("\\", "/")
        rotations[str(phase)] = {
            "representativeFrame": int(rep_frame),
            "spriteAxis": [float(axis[0]), float(axis[1])],
            "rotation": rotation.tolist(),
            "sharedSymmetricRest": True,
        }
    perch_mesh = assert_write_path(round_dir / "perch_rest.glb", repo_root=ROOT)
    shutil.copy2(mesh_path, perch_mesh)
    shutil.copy2(mesh_path, after_mesh)
    write_after_poses(after_poses_path, used_poses, frame_indices=frame_indices, camera_fit_path=camera_fit)
    fly_poses = identity_joint_keep_root_poses(used_poses, frame_indices)
    fly_poses_path = round_dir / "fly_identity_poses.json"
    write_after_poses(fly_poses_path, fly_poses, frame_indices=frame_indices, camera_fit_path=camera_fit)
    phase_bundles: dict[str, Any] = {}
    for phase, path in phase_paths.items():
        fly_experiment = None
        try:
            fly_experiment, _payload, _ignore = load_preview_experiment(Path(clip_path), Path(path))
            phase_bundles[str(phase)] = raster_bundle(
                fly_experiment,
                fly_poses,
                round_dir / f"raster_{phase}",
            )
        finally:
            close_experiment(fly_experiment)
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frame_indices))
        for frame in frame_indices
    ]
    after_raster = composite_phase_rest_bundle(
        perch=before,
        phase_bundles=phase_bundles,
        sources=sources,
        png_dir=after_png,
        frames=frame_indices,
    )
    details["architecture"] = "anatomy_tpose_snip_rotation"
    details["phase_baked_fly_rest"] = False
    details["labeledWingSpread"] = True
    details["earlySymmetry"] = True
    details["wingDivergence"] = False
    details["anatomyFitPipeline"] = list(ANATOMY_FIT_STAGES)
    details["anatomyFitCompleted"] = list(ANATOMY_FIT_STAGES[:3])
    details["anatomyFitStage"] = ANATOMY_FIT_STAGES[2]
    details["tposeLimbSpread"] = limb_reports
    details["snip_tpose_bridges"] = True
    details["tposeSnip"] = {
        "cutCount": int(snip["cutCount"]),
        "faceCount": int(snip["faceCount"]),
        "fraction": float(snip["fraction"]),
        "stretchRatio": float(snip["stretchRatio"]),
        "samples": list(snip["samples"]),
    }
    details["wingSpanSource"] = "tpose_bilateral_poles"
    details["sharedSymmetricRest"] = str(symmetric_mesh.resolve()).replace("\\", "/")
    details["chestSource"] = "anatomy_catalog_ventral"
    details["anatomyLandmarks"] = dict(catalog.get("landmarks") or {})
    details["glideRotations"] = rotations
    details["phaseRests"] = phase_paths
    details["perchRest"] = str(perch_mesh.resolve()).replace("\\", "/")
    details["representatives"] = {str(name): int(frame) for name, frame in reps.items()}
    details["frameRestSources"] = sources
    details["identityJointsOnMove"] = True
    details["keepRootOnMove"] = True
    details["preservePipelinePoses"] = True
    details["flyIdentityPoses"] = str(fly_poses_path.resolve()).replace("\\", "/")
    details["notOccupancyGate"] = True
    details["measureBones"] = list(chain)
    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": after_mesh,
        "poses": used_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": Path(before["pngDir"]),
        "afterPng": after_png,
        "afterRaster": after_raster,
        "needsReload": False,
        "skipVisionCheck": True,
        "skipReloadOccupancy": True,
        "sprites": sprites,
        "insertName": None,
    }


def save_normalized_mesh(
    after_mesh: Path,
    doc: dict[str, Any],
    blob: bytearray,
    details: dict[str, Any],
) -> str | None:
    details["normalizedWeights"] = normalize_skin_weights(doc, blob)
    save_glb(after_mesh, doc, blob)
    try:
        details["validated"] = validate_skinned_glb(after_mesh)
    except ValueError as exc:
        return f"after mesh failed skinned validation: {exc}"
    return None


def operate_round(
    *,
    round_dir: Path,
    class_name: str,
    experiment,
    payload: dict[str, Any],
    poses: dict[int, dict[str, Any]],
    mesh_path: Path,
    occupancy: Mapping[str, Any],
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    camera_fit: Path,
    clip_name: str,
    pose_search_fine: bool = False,
) -> dict[str, Any]:
    round_dir = assert_write_path(round_dir, repo_root=ROOT)
    round_dir.mkdir(parents=True, exist_ok=True)
    operator = OPERATOR_BY_CLASS[class_name]
    after_mesh = round_dir / "after.glb"
    after_poses_path = round_dir / "after_poses.json"
    after_png = round_dir / "raster_after"
    before_png = Path(before["pngDir"])
    used_poses = clone_pose_map(poses)
    used_mesh = mesh_path
    details: dict[str, Any] = {"operator": operator, "class": class_name}
    if class_name == CLASS_POSE_SEARCH_DEBT:
        bones = [
            name
            for name, count in sorted(occupancy["assignedCounts"].items(), key=lambda item: -item[1])
            if count > 0
        ]
        if not bones:
            bones = [str(experiment.node_names[int(index)]) for index in experiment.active_node_indices[:8]]
        used_poses, search_details = leftover_pose_search(
            experiment,
            payload,
            poses,
            bones,
            fine=pose_search_fine,
            clip_name=clip_name,
        )
        details["search"] = search_details
        write_after_poses(after_poses_path, used_poses, frame_indices=experiment.frame_indices, camera_fit_path=camera_fit)
        shutil.copy2(mesh_path, after_mesh)
        used_mesh = after_mesh
    elif class_name == CLASS_WRONG_OWNER:
        target_name = occupancy["uniqueOwner"]
        if not target_name:
            details["rejectedReason"] = "no unique leftover owner"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        vote_owners = occupancy["ownersPerFrame"]
        from sprite_pose_feasibility import aggregate_vertex_owners

        vote = aggregate_vertex_owners(vote_owners) if vote_owners else {"agreed": {}, "disagreed": ()}
        details["disagreedVertices"] = list(vote.get("disagreed") or ())[:32]
        details["agreedVertexCount"] = int(len(vote.get("agreed") or {}))
        verts, reason = agreed_rebind_vertices(vote, target_name)
        if reason:
            details["rejectedReason"] = reason
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        doc, blob = load_glb(mesh_path)
        target_node = node_index_by_name(doc, str(target_name))
        details["rebind"] = rebind_vertices_to_joint(doc, blob, vertex_indices=verts, target_node=target_node)
        failed = save_normalized_mesh(after_mesh, doc, blob, details)
        if failed:
            details["rejectedReason"] = failed
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        used_mesh = after_mesh
        write_after_poses(after_poses_path, used_poses, frame_indices=experiment.frame_indices, camera_fit_path=camera_fit)
    elif class_name == CLASS_BODY_INFEASIBLE_REST:
        prefix, suffix = idle_band_from_payload(payload)
        if int(prefix) or int(suffix):
            completed = last_anatomy_fit_completed(round_dir.parent)
            forced = str(payload.get("_forcedAnatomyStage") or "")
            stage = ""
            if forced:
                if forced not in ANATOMY_FIT_STAGES:
                    details["rejectedReason"] = f"unknown anatomy stage {forced}"
                    return reject_without_mesh(
                        round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
                    )
                stage = forced
            elif completed:
                try:
                    stage = next_anatomy_fit_stage(completed)
                except ValueError as exc:
                    details["rejectedReason"] = str(exc)
                    return reject_without_mesh(
                        round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
                    )
            if stage:
                if stage == "symmetric_bone_fit":
                    return operate_symmetric_bone_fit(
                        round_dir=round_dir,
                        experiment=experiment,
                        payload=payload,
                        poses=used_poses,
                        mesh_path=mesh_path,
                        before=before,
                        sprites=sprites,
                        camera_fit=camera_fit,
                        after_mesh=after_mesh,
                        after_poses_path=after_poses_path,
                        after_png=after_png,
                        details=details,
                        class_name=class_name,
                        operator=operator,
                    )
                if stage == "asymmetric_fine_tune":
                    return operate_asymmetric_fine_tune(
                        round_dir=round_dir,
                        experiment=experiment,
                        payload=payload,
                        poses=used_poses,
                        mesh_path=mesh_path,
                        before=before,
                        sprites=sprites,
                        camera_fit=camera_fit,
                        after_mesh=after_mesh,
                        after_poses_path=after_poses_path,
                        after_png=after_png,
                        details=details,
                        class_name=class_name,
                        operator=operator,
                    )
                if stage == "shared_skeleton_temporal":
                    return operate_shared_skeleton_temporal(
                        round_dir=round_dir,
                        experiment=experiment,
                        payload=payload,
                        poses=used_poses,
                        mesh_path=mesh_path,
                        before=before,
                        sprites=sprites,
                        camera_fit=camera_fit,
                        after_mesh=after_mesh,
                        after_poses_path=after_poses_path,
                        after_png=after_png,
                        details=details,
                        class_name=class_name,
                        operator=operator,
                    )
                if stage == "insert_missing_symmetric":
                    return operate_insert_missing_symmetric(
                        round_dir=round_dir,
                        experiment=experiment,
                        payload=payload,
                        poses=used_poses,
                        mesh_path=mesh_path,
                        before=before,
                        sprites=sprites,
                        camera_fit=camera_fit,
                        after_mesh=after_mesh,
                        after_poses_path=after_poses_path,
                        after_png=after_png,
                        details=details,
                        class_name=class_name,
                        operator=operator,
                    )
                if stage != ANATOMY_FIT_STAGES[0]:
                    details["rejectedReason"] = f"anatomy-fit stage {stage} has no operator yet"
                    return reject_without_mesh(
                        round_dir, class_name, operator, details, before, sprites, experiment.frame_indices
                    )
            return operate_phase_baked_fly_rest(
                round_dir=round_dir,
                experiment=experiment,
                payload=payload,
                poses=used_poses,
                mesh_path=mesh_path,
                before=before,
                sprites=sprites,
                camera_fit=camera_fit,
                after_mesh=after_mesh,
                after_poses_path=after_poses_path,
                after_png=after_png,
                details=details,
                class_name=class_name,
                operator=operator,
            )
        leftover_frac = float(before["fractions"].leftover)
        extra_frac = float(before["fractions"].extra)
        fill_leftover, shrink_extra = occupancy_rest_modes(leftover_frac, extra_frac)
        if (not fill_leftover) and (not shrink_extra):
            details["rejectedReason"] = "occupancy rest has no leftover fill or extra shrink to apply"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        traps = flight_attitude_trap_frames(experiment, payload, used_poses)
        if traps:
            details["rejectedReason"] = "shared_skeleton_pose_first"
            details["attitudeTraps"] = traps
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        stroke = flight_broad_stroke_status(experiment, payload, used_poses)
        if stroke["needed"] and not stroke["ok"]:
            details["rejectedReason"] = "broad_stroke_first"
            details["broadStroke"] = {"needed": True, "ok": False, "measureBones": stroke.get("measureBones")}
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        rest_candidates = flight_rest_frame_candidates(experiment, payload, used_poses)
        if rest_candidates is not None and not rest_candidates:
            details["rejectedReason"] = "flight leftover fill has no side-view fly frame"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        rest_frame = occupancy_rest_frame_index(
            before["leftoverMasks"],
            before["extraMasks"],
            fill_leftover=fill_leftover,
            shrink_extra=shrink_extra,
            candidates=rest_candidates,
        )
        details["flightRestFrames"] = rest_candidates
        leftover = before["leftoverMasks"][rest_frame]
        extra = before["extraMasks"][rest_frame]
        sprite = experiment.target_masks[rest_frame].detach().cpu().numpy() > 0.5
        rest, blends, rotation = recover_root_and_lbs(experiment, before, rest_frame)
        xs, ys = project_points(experiment, posed_first_primitive(experiment, before, rest_frame))
        if (not np.any(leftover)) and (not np.any(extra)):
            details["rejectedReason"] = "rest sculpt has no leftover or extra pixels"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        joints_xy = project_all_joints(experiment, before, rest_frame)
        leftover_ys, leftover_xs = np.nonzero(leftover)
        extra_ys, extra_xs = np.nonzero(extra)
        unique_bones: list[str] = []
        extra_facing_px = float(OCCUPANCY_REST_EXTRA_FACING_PX)
        if fill_leftover and leftover_xs.size:
            unique_bones = occupancy_assigned_unique_bones(
                occupancy.get("assignedCounts") or {},
                occupancy.get("uniqueOwner"),
            )
        elif shrink_extra and extra_xs.size:
            unique_bones = unique_region_bones_from_pixels(extra_xs, extra_ys, joints_xy)
            extra_facing_px = float(OCCUPANCY_REST_FILL_MAX_ASSIGN_PX)
        if not unique_bones:
            details["rejectedReason"] = "unique-region occupancy rest has no leftover or extra bone"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        owner_names = vertex_dominant_owner_names(experiment)
        owner_allow = occupancy_unique_owner_allow(owner_names, unique_bones)
        assign_px = float(OCCUPANCY_REST_FILL_MAX_ASSIGN_PX)
        extra_facing_px = float(OCCUPANCY_REST_EXTRA_FACING_PX)
        volume_shrink = bool(shrink_extra)
        if volume_shrink:
            on_extra = extra_on_vertex_mask(xs, ys, extra)
            vert_allow = np.asarray(owner_allow, dtype=bool) & on_extra
            rest_deltas, affected = unique_region_centroid_shrink_deltas(
                rest,
                owner_names,
                unique_bones,
                frac=UNIQUE_REGION_VOLUME_SHRINK_FRAC,
                vert_allow=vert_allow,
            )
            if not np.any(affected):
                details["rejectedReason"] = "unique-region volume shrink affected vertex set is empty"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            sculpt = apply_rest_space_deltas(
                rest,
                rest_deltas,
                affected,
                max_displacement=float(REST_SCULPT_MAX_BODY_LENGTHS) * body_extent(rest),
            )
        else:
            pixel_deltas, affected = occupancy_vertex_deltas_px(
                xs,
                ys,
                leftover,
                extra,
                sprite,
                max_assign_px=assign_px,
                fill_leftover=fill_leftover,
                shrink_extra=False,
                owner_allow=owner_allow,
                extra_facing_px=extra_facing_px,
            )
            if not np.any(affected):
                details["rejectedReason"] = "rest sculpt affected vertex set is empty"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            right = experiment.camera_right.detach().cpu().numpy()
            down = experiment.camera_down.detach().cpu().numpy()
            px = experiment.px_per_world.detach().cpu().numpy()
            deltas = np.zeros_like(rest)
            for vertex in np.nonzero(affected)[0]:
                world = (float(pixel_deltas[vertex, 0]) / max(float(px[0]), 1e-8)) * right + (
                    float(pixel_deltas[vertex, 1]) / max(float(px[1]), 1e-8)
                ) * down
                deltas[int(vertex)] = rotation.T @ world
            sculpt = rest_sculpt_positions(
                rest,
                blends,
                deltas_world=deltas,
                affected=affected,
                body_length=body_extent(rest),
            )
        details["occupancyRest"] = {
            "affected": int(np.count_nonzero(affected)),
            "leftoverPixels": int(np.count_nonzero(leftover)),
            "extraPixels": int(np.count_nonzero(extra)),
            "fillLeftover": fill_leftover,
            "shrinkExtra": shrink_extra,
            "volumeShrink": volume_shrink,
            "volumeShrinkFrac": float(UNIQUE_REGION_VOLUME_SHRINK_FRAC) if volume_shrink else None,
            "restFrame": int(rest_frame),
            "assignPx": assign_px,
            "uniqueBones": unique_bones,
            "uniqueAffected": int(np.count_nonzero(owner_allow)),
            "extraFacingPx": extra_facing_px,
        }
        details["sculpt"] = {key: sculpt[key] for key in ("rejected", "reason", "skipped", "affected", "moved")}
        if sculpt["rejected"]:
            details["class"] = CLASS_LBS_ILL_CONDITIONED
            return reject_without_mesh(
                round_dir,
                CLASS_LBS_ILL_CONDITIONED,
                operator,
                details,
                before,
                sprites,
                experiment.frame_indices,
            )
        doc, blob = load_glb(mesh_path)
        replace_positions(doc, blob, sculpt["positions"])
        failed = save_normalized_mesh(after_mesh, doc, blob, details)
        if failed:
            details["rejectedReason"] = failed
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        used_mesh = after_mesh
        write_after_poses(after_poses_path, used_poses, frame_indices=experiment.frame_indices, camera_fit_path=camera_fit)
    elif class_name == CLASS_BODY_INFEASIBLE_LENGTH:
        leftover_frac = float(before["fractions"].leftover)
        extra_frac = float(before["fractions"].extra)
        fill_leftover, shrink_extra = occupancy_rest_modes(leftover_frac, extra_frac)
        stroke = flight_broad_stroke_status(experiment, payload, used_poses)
        if stroke["needed"] and not stroke["ok"]:
            details["rejectedReason"] = "broad_stroke_first"
            details["broadStroke"] = {"needed": True, "ok": False, "measureBones": stroke.get("measureBones")}
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        doc, blob = load_glb(mesh_path)
        if shrink_extra:
            rest_frame = occupancy_rest_frame_index(
                before["leftoverMasks"],
                before["extraMasks"],
                fill_leftover=False,
                shrink_extra=True,
            )
            extra = before["extraMasks"][rest_frame]
            extra_ys, extra_xs = np.nonzero(extra)
            if extra_xs.size < 1:
                details["rejectedReason"] = "rest-length extra shrink has no extra pixels"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            joints_xy = project_all_joints(experiment, before, rest_frame)
            unique_bones = unique_region_bones_from_pixels(extra_xs, extra_ys, joints_xy)
            if not unique_bones:
                details["rejectedReason"] = "rest-length extra shrink has no unique extra bone"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            scale = float(REST_LENGTH_EXTRA_SCALE)
            for bone in unique_bones:
                node = node_index_by_name(doc, str(bone))
                scale_bone_rest_translation(doc, blob, joint_node=node, scale=scale)
            details["restLength"] = {
                "mode": "extra_shrink",
                "bones": unique_bones,
                "scale": scale,
                "restFrame": int(rest_frame),
            }
        else:
            traps = flight_attitude_trap_frames(experiment, payload, used_poses)
            if traps:
                details["rejectedReason"] = "shared_skeleton_pose_first"
                details["attitudeTraps"] = traps
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            rest_candidates = flight_rest_frame_candidates(experiment, payload, used_poses)
            if rest_candidates is not None and not rest_candidates:
                details["rejectedReason"] = "flight leftover fill has no side-view fly frame"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            rest_frame = occupancy_rest_frame_index(
                before["leftoverMasks"],
                before["extraMasks"],
                fill_leftover=True,
                shrink_extra=False,
                candidates=rest_candidates,
            )
            joints_xy = project_all_joints(experiment, before, rest_frame)
            leftover = before["leftoverMasks"][rest_frame]
            ys, xs = np.nonzero(leftover)
            leftover_xy = np.stack((xs.astype(np.float64), ys.astype(np.float64)), axis=1) if xs.size else np.zeros((0, 2))
            pixel_bones = unique_region_bones_from_pixels(xs, ys, joints_xy) if xs.size else []
            assigned_bones = occupancy_assigned_unique_bones(
                occupancy.get("assignedCounts") or {},
                occupancy.get("uniqueOwner"),
            )
            insert = "Bone_FeasibilityInsert"
            names = [str(name) for name in experiment.node_names]
            unique_region = list(dict.fromkeys([*pixel_bones, *assigned_bones, insert if insert in names else ""]))
            unique_region = [name for name in unique_region if name]
            target_name = leftover_extend_target_name(unique_region)
            if not target_name:
                details["rejectedReason"] = "no distal leftover bone for rest-length"
                return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
            node = node_index_by_name(doc, str(target_name))
            parent = None
            parent_index = experiment.asset.nodes[node].parent
            if parent_index is not None:
                parent = str(experiment.asset.nodes[int(parent_index)].name)
            joint = np.asarray(joints_xy.get(str(target_name), (0.0, 0.0)))
            parent_xy = np.asarray(joints_xy.get(parent, joint)) if parent else joint
            scale = leftover_extend_scale(joint, parent_xy, leftover_xy)
            details["restLength"] = {
                "mode": "leftover_extend",
                "bone": target_name,
                "bones": [target_name],
                "uniqueRegion": unique_region,
                "scale": scale,
                "restFrame": int(rest_frame),
                "flightRestFrames": rest_candidates,
            }
            scale_bone_rest_translation(doc, blob, joint_node=node, scale=scale)
        failed = save_normalized_mesh(after_mesh, doc, blob, details)
        if failed:
            details["rejectedReason"] = failed
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        used_mesh = after_mesh
        write_after_poses(after_poses_path, used_poses, frame_indices=experiment.frame_indices, camera_fit_path=camera_fit)
    elif class_name == CLASS_MISSING_JOINT:
        stroke = flight_broad_stroke_status(experiment, payload, used_poses)
        if stroke["needed"] and not stroke["ok"]:
            details["rejectedReason"] = "broad_stroke_first"
            details["broadStroke"] = {"needed": True, "ok": False, "measureBones": stroke.get("measureBones")}
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        rest_candidates = flight_rest_frame_candidates(experiment, payload, used_poses)
        if rest_candidates is not None and not rest_candidates:
            details["rejectedReason"] = "flight insert-bone has no side-view fly frame"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        rest_frame = occupancy_rest_frame_index(
            before["leftoverMasks"],
            before["extraMasks"],
            fill_leftover=True,
            shrink_extra=False,
            candidates=rest_candidates,
        )
        leftover = before["leftoverMasks"][rest_frame]
        extra = before["extraMasks"][rest_frame]
        sprite = experiment.target_masks[rest_frame].detach().cpu().numpy() > 0.5
        ys, xs = np.nonzero(leftover)
        if xs.size < 1:
            details["rejectedReason"] = "insert-bone leftover blob is empty"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        parent_name = occupancy.get("uniqueOwner")
        unique_bones = [str(parent_name)]
        if not parent_name:
            details["rejectedReason"] = "insert-bone has no unique leftover owner"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        xs_v, ys_v = project_points(experiment, posed_first_primitive(experiment, before, rest_frame))
        owner_names = vertex_dominant_owner_names(experiment)
        owner_allow = occupancy_unique_owner_allow(owner_names, unique_bones)
        _pixel_deltas, leftover_affected = occupancy_vertex_deltas_px(
            xs_v,
            ys_v,
            leftover,
            extra,
            sprite,
            max_assign_px=OCCUPANCY_REST_FILL_MAX_ASSIGN_PX,
            fill_leftover=True,
            shrink_extra=False,
            owner_allow=owner_allow,
        )
        chosen_verts = [int(vertex) for vertex in np.nonzero(leftover_affected)[0]]
        if not chosen_verts:
            details["rejectedReason"] = "insert-bone unique leftover vertex set is empty"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        rest, _blends, _rotation = recover_root_and_lbs(experiment, before, rest_frame)
        parent_idxs = [index for index, name in enumerate(owner_names) if str(name) == str(parent_name)]
        if not parent_idxs:
            details["rejectedReason"] = "insert-bone parent has no rest verts"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        centroid_rest = rest[np.asarray(chosen_verts, dtype=np.int64)].mean(axis=0)
        parent_origin = rest[np.asarray(parent_idxs, dtype=np.int64)].mean(axis=0)
        world = centroid_rest - parent_origin
        max_disp = float(REST_SCULPT_MAX_BODY_LENGTHS) * body_extent(rest)
        if float(np.linalg.norm(world)) > max_disp:
            details["rejectedReason"] = "insert-bone rest translation exceeds rest sculpt displacement cap"
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        details["insertSelect"] = {
            "parent": str(parent_name),
            "uniqueBones": unique_bones,
            "restFrame": int(rest_frame),
            "vertexCount": int(len(chosen_verts)),
            "translationSpace": "rest_centroid",
        }
        doc, blob = load_glb(mesh_path)
        parent_node = node_index_by_name(doc, str(parent_name))
        inserted = insert_child_bone(
            doc,
            blob,
            parent_node=parent_node,
            name="Bone_FeasibilityInsert",
            translation=(float(world[0]), float(world[1]), float(world[2])),
            vertex_indices=chosen_verts,
        )
        details["insert"] = inserted
        failed = save_normalized_mesh(after_mesh, doc, blob, details)
        if failed:
            details["rejectedReason"] = failed
            return reject_without_mesh(round_dir, class_name, operator, details, before, sprites, experiment.frame_indices)
        used_mesh = after_mesh
        write_after_poses(after_poses_path, used_poses, frame_indices=experiment.frame_indices, camera_fit_path=camera_fit)
    else:
        raise RuntimeError(f"no operator for class {class_name}")

    return {
        "roundDir": round_dir,
        "class": details.get("class", class_name),
        "operator": operator,
        "details": details,
        "mesh": used_mesh,
        "poses": used_poses,
        "afterPosesPath": after_poses_path,
        "afterMesh": after_mesh,
        "beforePng": before_png,
        "afterPng": after_png,
        "needsReload": class_name in {
            CLASS_WRONG_OWNER,
            CLASS_BODY_INFEASIBLE_REST,
            CLASS_BODY_INFEASIBLE_LENGTH,
            CLASS_MISSING_JOINT,
        },
        "sprites": sprites,
        "insertName": "Bone_FeasibilityInsert" if class_name == CLASS_MISSING_JOINT else None,
    }


def reject_without_mesh(
    round_dir: Path,
    class_name: str,
    operator: str,
    details: Mapping[str, Any],
    before: Mapping[str, Any],
    sprites: Sequence[Path],
    frames: Sequence[int],
) -> dict[str, Any]:
    caption = f"{class_name} {operator} leftover={before['fractions'].leftover:.3f} extra={before['fractions'].extra:.3f} strain={before['strain']:.3f} reject"
    gif = write_compare_gif(
        sprite_paths=sprites,
        panel_a=Path(before["pngDir"]),
        panel_b=Path(before["pngDir"]),
        frames=frames,
        dest=round_dir / "compare.gif",
        labels=("sprite", "before", "after (not written)"),
        caption=caption,
    )
    report = {
        "roundId": round_dir.name,
        "accepted": False,
        "class": class_name,
        "operator": operator,
        "leftover": float(before["fractions"].leftover),
        "extra": float(before["fractions"].extra),
        "strain": float(before["strain"]),
        "details": dict(details),
        "gif": str(gif).replace("\\", "/"),
        "afterGlb": None,
    }
    _json_dump(round_dir / "round_report.json", report)
    return {"report": report, "rejectedEarly": True}


def snapshot_live_paths(
    repo: Path,
    unit: str,
    clip: str,
    clip_source: Path | None = None,
) -> dict[str, Path]:
    live_clip = Path(clip_source).resolve() if clip_source is not None else fused_push_clip_path(repo, unit, clip)
    if not live_clip.is_file():
        raise FileNotFoundError(f"clip source is missing: {live_clip}")
    payload = _json_load(live_clip)
    live_camera = Path(str(payload["cameraFitPath"]))
    live_init = Path(str(payload.get("reportPath") or live_camera.parent / "profile_camera_initialization.json"))
    init = _json_load(live_init)
    live_mesh = source_mesh_from_init(init)
    return {
        "clip": live_clip,
        "camera": live_camera,
        "init": live_init,
        "mesh": live_mesh,
    }


def archive_work_tree(work: Path) -> Path:
    """Move an existing surgery tree aside. Writes stay under sprite_feasibility/."""
    work = assert_write_path(work, repo_root=ROOT)
    if not work.is_dir():
        raise RuntimeError(f"cannot archive missing work tree: {work}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = assert_write_path(work.parent / f"{work.name}_from_scratch_archive_{stamp}", repo_root=ROOT)
    shutil.move(str(work), str(dest))
    return dest


def existing_round_indices(work: Path) -> list[int]:
    found: list[int] = []
    for path in work.glob("round_*"):
        if not path.is_dir():
            continue
        suffix = path.name.split("_", 1)[-1]
        if suffix.isdigit():
            found.append(int(suffix))
    return sorted(found)


def png_dir_for_round(work: Path, round_id: str, row: Mapping[str, Any] | None = None) -> Path:
    if row and row.get("pngDir"):
        return Path(str(row["pngDir"]))
    after = work / round_id / "raster_after"
    if after.is_dir() and any(after.glob("*.png")):
        return after
    return work / round_id / "raster"


def load_round_metrics(work: Path, round_id: str) -> dict[str, Any] | None:
    report = work / round_id / "round_report.json"
    metrics = work / round_id / "metrics.json"
    path = report if report.is_file() else metrics
    if not path.is_file():
        return None
    data = _json_load(path)
    if "leftover" not in data:
        return None
    data.setdefault("roundId", round_id)
    data.setdefault("accepted", True)
    return data


def fill_trajectory_metrics(work: Path, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    filled: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        round_id = str(item.get("roundId") or "")
        if "leftover" not in item:
            metrics = load_round_metrics(work, round_id) if round_id else None
            if metrics:
                for key in ("leftover", "extra", "strain", "pngDir"):
                    if key in metrics and key not in item:
                        item[key] = metrics[key]
        if round_id and "pngDir" not in item:
            item["pngDir"] = str(png_dir_for_round(work, round_id, item))
        filled.append(item)
    return filled


def resume_paths(work: Path, index: Mapping[str, Any]) -> dict[str, Any]:
    round00 = work / "round_00"
    camera_file = work / "round_01" / "profile_camera_fit.json"
    camera_resolved = camera_file.is_file() and (
        str(index.get("primaryClass")) == CLASS_CAMERA_RESOLVED_POSE_STALE
        or str(index.get("productRound")) == "round_01"
    )
    if camera_resolved:
        clip_path = work / "round_01" / "gpu_clip_result.json"
        camera_path = camera_file
        baseline_id = "round_01"
    else:
        clip_path = round00 / "gpu_clip_result.json"
        camera_path = round00 / "profile_camera_fit.json"
        baseline_id = "round_00"
    mesh_path = round00 / "source_mesh.glb"
    poses_path = None
    for row in index.get("trajectory") or []:
        if not row.get("accepted"):
            continue
        if row.get("afterGlb"):
            mesh_path = Path(str(row["afterGlb"]))
        after_poses = work / str(row["roundId"]) / "after_poses.json"
        if after_poses.is_file():
            poses_path = after_poses
    return {
        "clip_path": clip_path,
        "camera_path": camera_path,
        "mesh_path": mesh_path,
        "poses_path": poses_path,
        "baseline_id": baseline_id,
        "camera_resolved": camera_resolved,
    }


def collect_work_trajectory(work: Path, index: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in fill_trajectory_metrics(work, index.get("trajectory") or []):
        rid = str(row.get("roundId") or "")
        if rid:
            by_id[rid] = dict(row)
    for path in sorted(work.glob("round_*/round_report.json")):
        data = _json_load(path)
        rid = str(data.get("roundId") or path.parent.name)
        merged = dict(by_id.get(rid) or {})
        merged.update(data)
        merged["roundId"] = rid
        if "pngDir" not in merged:
            merged["pngDir"] = str(png_dir_for_round(work, rid, merged))
        by_id[rid] = merged
    def sort_key(rid: str) -> int:
        suffix = rid.split("_", 1)[-1]
        return int(suffix) if suffix.isdigit() else -1

    return [by_id[rid] for rid in sorted(by_id, key=sort_key)]


def recompose_work_gifs(*, unit: str, clip: str) -> dict[str, Any]:
    """Rebuild the latest round compare GIF and final_compare.gif from stills.

    Occupancy rasters stay at native sprite resolution. This only upscales
    those stills with integer nearest-neighbor so spot-checks are readable.
    """
    work = assert_write_path(work_tree_root(ROOT) / unit / clip, repo_root=ROOT)
    index_path = work / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"cannot recompose GIFs: missing {index_path}")
    index = _json_load(index_path)
    trajectory = collect_work_trajectory(work, index)
    paths = resume_paths(work, {**index, "trajectory": trajectory})
    payload = _json_load(Path(paths["clip_path"]))
    frames = [int(frame) for frame in payload["frameIndices"]]
    sprites = sprite_paths(payload, frames)
    written: list[str] = []
    previous_png: Path | None = None
    latest: tuple[Mapping[str, Any], Path, Path] | None = None
    for row in trajectory:
        round_id = str(row.get("roundId") or "")
        if not round_id:
            continue
        after_png = png_dir_for_round(work, round_id, row)
        if not (after_png.is_dir() and any(after_png.glob("*.png"))):
            continue
        if previous_png is not None:
            latest = (row, previous_png, after_png)
        if bool(row.get("accepted")) or previous_png is None:
            previous_png = after_png
    if latest is not None:
        row, before_png, after_png = latest
        leftover = float(row["leftover"]) if "leftover" in row else float("nan")
        extra = float(row["extra"]) if "extra" in row else float("nan")
        status = "accept" if bool(row.get("accepted")) else "reject"
        gif_path = work / str(row["roundId"]) / "compare.gif"
        write_compare_gif(
            sprite_paths=sprites,
            panel_a=before_png,
            panel_b=after_png,
            frames=frames,
            dest=gif_path,
            labels=("sprite", "before", "after"),
            caption=(
                f"{row.get('class', '')} {row.get('operator', '')} "
                f"leftover={leftover:.3f} extra={extra:.3f} {status}"
            ),
        )
        written.append(str(gif_path).replace("\\", "/"))
    accepted = [row for row in trajectory if bool(row.get("accepted")) and "leftover" in row]
    chosen_id = str(index.get("argmaxRound") or (accepted[-1]["roundId"] if accepted else "round_00"))
    chosen = next((row for row in accepted if str(row.get("roundId")) == chosen_id), None)
    if chosen is None and accepted:
        chosen = accepted[-1]
        chosen_id = str(chosen["roundId"])
    baseline = None
    for row in accepted:
        if str(row.get("roundId")) == chosen_id:
            break
        baseline = row
    if baseline is None and len(accepted) >= 2:
        baseline = accepted[-2]
    if chosen is not None and baseline is not None:
        final = write_compare_gif(
            sprite_paths=sprites,
            panel_a=png_dir_for_round(work, str(baseline["roundId"]), baseline),
            panel_b=png_dir_for_round(work, chosen_id, chosen),
            frames=frames,
            dest=work / "final_compare.gif",
            labels=("sprite", str(baseline["roundId"]), chosen_id),
            caption=(
                f"argmax {chosen_id} leftover={float(chosen['leftover']):.3f} "
                f"extra={float(chosen.get('extra') or 0.0):.3f}"
            ),
        )
        written.append(str(final).replace("\\", "/"))
        index["finalGif"] = str(final).replace("\\", "/")
        index["compareGifScale"] = {
            "maxPanelPx": COMPARE_GIF_MAX_PANEL_PX,
            "resampling": "nearest",
            "occupancyRasterUnchanged": True,
        }
        _json_dump(work / "index.json", index)
    return {
        "ok": True,
        "unit": unit,
        "clip": clip,
        "gifs": written,
        "argmaxRound": chosen_id,
        "proof": "generated-artifact",
    }


def resume_unit_clip(
    *,
    unit: str,
    clip: str,
    acceptance_clip: str | None,
    force_operator: str | None = None,
    anatomy_stage: str | None = None,
    architecture_source: str | None = None,
    abbreviated_symmetric_only: bool = False,
) -> dict[str, Any]:
    work = assert_write_path(work_tree_root(ROOT) / unit / clip, repo_root=ROOT)
    index_path = work / "index.json"
    if not index_path.is_file():
        raise RuntimeError(f"cannot resume: missing {index_path}")
    index = _json_load(index_path)
    round00 = work / "round_00"
    trajectory = collect_work_trajectory(work, index)
    paths = resume_paths(work, {**index, "trajectory": trajectory})
    rounds = existing_round_indices(work)
    if not rounds:
        start_round = 1
    else:
        last = max(rounds)
        last_report = work / f"round_{last:02d}" / "round_report.json"
        start_round = last if not last_report.is_file() else last + 1
    already_pose_search = sum(
        1 for row in trajectory if str(row.get("class")) == CLASS_POSE_SEARCH_DEBT and bool(row.get("accepted"))
    )
    last_frac = None
    for row in reversed(trajectory):
        if row.get("accepted") and "leftover" in row:
            last_frac = row
            break
    pose_shaped = False
    if last_frac is not None:
        leftover = float(last_frac["leftover"])
        extra = float(last_frac.get("extra") or 0.0)
        pose_shaped = leftover > FEASIBLE_LEFTOVER and leftover > 2.0 * max(extra, 0.01)
    force_pose = already_pose_search < 3 and (already_pose_search == 0 or pose_shaped)
    if force_operator == CLASS_POSE_SEARCH_DEBT:
        force_pose = True
    elif force_operator is not None:
        force_pose = False
    latest_accepted = last_frac["roundId"] if last_frac is not None else str(paths["baseline_id"])
    index["resume"] = True
    index["resumeFromRound"] = start_round
    return run_body_loop(
        work=work,
        round00=round00,
        clip_path=Path(paths["clip_path"]),
        camera_path=Path(paths["camera_path"]),
        mesh_path=Path(paths["mesh_path"]),
        index=index,
        unit=unit,
        clip=clip,
        acceptance_clip=acceptance_clip,
        allow_acceptance_switch=False,
        start_round=start_round,
        existing_trajectory=trajectory,
        force_pose_search=force_pose,
        skip_coil=True,
        poses_override_path=paths["poses_path"],
        baseline_round_id=str(latest_accepted),
        raster_dest=work / "_resume_before" / "raster",
        pose_search_fine=already_pose_search >= 1,
        skip_body_ops=force_operator is not None or (pose_shaped and already_pose_search >= 1 and force_operator is None),
        force_operator=force_operator,
        anatomy_stage=anatomy_stage,
        architecture_source=architecture_source,
        abbreviated_symmetric_only=abbreviated_symmetric_only,
    )


def run_unit_clip(
    *,
    unit: str,
    clip: str,
    expected_first_class: str | None,
    acceptance_clip: str | None,
    allow_acceptance_switch: bool = True,
    resume: bool = False,
    operator: str | None = None,
    clip_source: Path | None = None,
    reseed: bool = False,
    anatomy_stage: str | None = None,
    architecture_source: str | None = None,
    abbreviated_symmetric_only: bool = False,
) -> dict[str, Any]:
    repo = ROOT
    work = assert_write_path(work_tree_root(repo) / unit / clip, repo_root=repo)
    if reseed and resume:
        raise RuntimeError("--reseed cannot run with --resume")
    if reseed and work.is_dir() and (work / "index.json").is_file():
        archived = archive_work_tree(work)
        print(json.dumps({"archivedWorkTree": str(archived).replace("\\", "/")}, indent=2), flush=True)
    work.mkdir(parents=True, exist_ok=True)
    if resume:
        return resume_unit_clip(
            unit=unit,
            clip=clip,
            acceptance_clip=acceptance_clip,
            force_operator=operator,
            anatomy_stage=anatomy_stage,
            architecture_source=architecture_source,
            abbreviated_symmetric_only=abbreviated_symmetric_only,
        )
    index_path = work / "index.json"
    if index_path.is_file():
        existing = _json_load(index_path)
        if existing.get("primaryClass") in {
            CLASS_CAMERA_RESOLVED_POSE_STALE,
            CLASS_PARTIAL_SURGERY_EXHAUSTED,
        }:
            raise RuntimeError(
                f"{unit}/{clip} already stopped at {existing.get('primaryClass')}; pass --resume to continue"
            )
    live = snapshot_live_paths(repo, unit, clip, clip_source=clip_source)
    round00 = work / "round_00"
    snap = copy_round_00(
        dest_dir=round00,
        live_clip=live["clip"],
        live_camera=live["camera"],
        live_init=live["init"],
        live_mesh=live["mesh"],
    )
    clip_path = round00 / "gpu_clip_result.json"
    camera_path = round00 / "profile_camera_fit.json"
    init_path = round00 / "profile_camera_initialization.json"
    mesh_path = round00 / "source_mesh.glb"
    init = _json_load(init_path)
    camera_report = classify_camera_from_init(init)
    first_class = str(camera_report["primaryClass"])
    provenance = rig_provenance(mesh_path)
    index: dict[str, Any] = {
        "singleClipOnly": True,
        "unit": unit,
        "clip": clip,
        "firstClass": first_class,
        "camera": camera_report,
        "rigProvenance": provenance,
        "wrongRigLane": False,
        "wrongRigLaneClass": CLASS_WRONG_RIG_LANE,
        "neverMasterGlb": True,
        "proof": "generated-artifact",
        "poseUnits": "degrees",
        "sourceHashes": snap["sourceHashes"],
        "rasterResolution": None,
        "trajectory": [],
    }
    if expected_first_class and first_class != expected_first_class:
        index["stop"] = "classifier_mismatch"
        index["expectedFirstClass"] = expected_first_class
        _json_dump(work / "index.json", index)
        raise RuntimeError(
            f"{unit}/{clip} first class is {first_class}, expected {expected_first_class}; "
            "review the classifier before any camera or body write"
        )
    if first_class == CLASS_CAMERA_MISMATCH_UNRESOLVED:
        index["primaryClass"] = first_class
        _json_dump(work / "index.json", index)
        return index
    if first_class == CLASS_CAMERA_MISMATCH:
        return run_camera_operator(
            work=work,
            round00=round00,
            clip_path=clip_path,
            camera_path=camera_path,
            init=init,
            mesh_path=mesh_path,
            index=index,
        )
    return run_body_loop(
        work=work,
        round00=round00,
        clip_path=clip_path,
        camera_path=camera_path,
        mesh_path=mesh_path,
        index=index,
        unit=unit,
        clip=clip,
        acceptance_clip=acceptance_clip,
        allow_acceptance_switch=allow_acceptance_switch,
        skip_coil=True,
        force_pose_search=operator == CLASS_POSE_SEARCH_DEBT,
        skip_body_ops=operator is not None,
        force_operator=operator,
        anatomy_stage=anatomy_stage,
        architecture_source=architecture_source,
        abbreviated_symmetric_only=abbreviated_symmetric_only,
    )


def run_camera_operator(
    *,
    work: Path,
    round00: Path,
    clip_path: Path,
    camera_path: Path,
    init: Mapping[str, Any],
    mesh_path: Path,
    index: dict[str, Any],
) -> dict[str, Any]:
    candidate = pick_highest_facing_profile(init["candidates"])
    if candidate is None:
        index["primaryClass"] = CLASS_CAMERA_MISMATCH_UNRESOLVED
        _json_dump(work / "index.json", index)
        return index
    round_dir = assert_write_path(work / "round_01", repo_root=ROOT)
    round_dir.mkdir(parents=True, exist_ok=True)
    new_camera = round_dir / "profile_camera_fit.json"
    init_res = tuple(int(value) for value in (init.get("config") or {}).get("resolution") or (0, 0))
    if init_res[0] < 1:
        raise ValueError("profile init is missing raster resolution")
    write_camera_fit_from_candidate(camera_path, new_camera, candidate, source_resolution=init_res)
    new_clip = round_dir / "gpu_clip_result.json"
    payload = rewrite_work_clip(_json_load(clip_path), camera_fit=new_camera, init_path=round00 / "profile_camera_initialization.json")
    _json_dump(new_clip, payload)
    experiment_old, old_payload, poses = load_preview_experiment(clip_path, mesh_path)
    frames = [int(frame) for frame in experiment_old.frame_indices]
    sprites = sprite_paths(old_payload, frames)
    old_bundle = raster_bundle(experiment_old, poses, round00 / "raster")
    index["rasterResolution"] = old_bundle["resolution"]
    close_experiment(experiment_old)
    experiment_new, _new_payload, poses_new = load_preview_experiment(new_clip, mesh_path)
    new_bundle = raster_bundle(experiment_new, poses_new, round_dir / "raster")
    close_experiment(experiment_new)
    caption = (
        f"{CLASS_CAMERA_RESOLVED_POSE_STALE} camera stale pose "
        f"leftover {old_bundle['fractions'].leftover:.3f}->{new_bundle['fractions'].leftover:.3f}"
    )
    gif = write_compare_gif(
        sprite_paths=sprites,
        panel_a=old_bundle["pngDir"],
        panel_b=new_bundle["pngDir"],
        frames=frames,
        dest=round_dir / "compare.gif",
        labels=("sprite", "old camera (stale pose)", "new camera (stale pose)"),
        caption=caption,
    )
    round_report = {
        "roundId": "round_01",
        "accepted": True,
        "class": CLASS_CAMERA_RESOLVED_POSE_STALE,
        "operator": "camera",
        "leftover": float(new_bundle["fractions"].leftover),
        "extra": float(new_bundle["fractions"].extra),
        "strain": float(new_bundle["strain"]),
        "gif": str(gif).replace("\\", "/"),
        "cameraFitPath": str(new_camera.resolve()).replace("\\", "/"),
        "clipCameraFitPath": str(new_clip.resolve()).replace("\\", "/"),
        "note": "poses were not re-searched; no body classes this run",
    }
    _json_dump(round_dir / "round_report.json", round_report)
    original = {
        "roundId": "round_00",
        "accepted": True,
        "leftover": float(old_bundle["fractions"].leftover),
        "extra": float(old_bundle["fractions"].extra),
        "strain": float(old_bundle["strain"]),
        "pngDir": str(old_bundle["pngDir"]),
    }
    _json_dump(round00 / "metrics.json", original)
    final = write_compare_gif(
        sprite_paths=sprites,
        panel_a=old_bundle["pngDir"],
        panel_b=new_bundle["pngDir"],
        frames=frames,
        dest=work / "final_compare.gif",
        labels=("sprite", "round_00", "round_01 camera"),
        caption=caption,
    )
    index.update(
        {
            "primaryClass": CLASS_CAMERA_RESOLVED_POSE_STALE,
            "productRound": "round_01",
            "argmaxSkippedReason": CLASS_CAMERA_RESOLVED_POSE_STALE,
            "finalGif": str(final).replace("\\", "/"),
            "trajectory": [
                {"roundId": "round_00", "class": "original", "accepted": True},
                {"roundId": "round_01", "class": CLASS_CAMERA_RESOLVED_POSE_STALE, "accepted": True},
            ],
            "bodySurgery": False,
        }
    )
    _json_dump(work / "index.json", index)
    _json_dump(round_dir / "candidate_comparison.json", {"selected": candidate, "camera": index["camera"]})
    return index


def run_body_loop(
    *,
    work: Path,
    round00: Path,
    clip_path: Path,
    camera_path: Path,
    mesh_path: Path,
    index: dict[str, Any],
    unit: str,
    clip: str,
    acceptance_clip: str | None,
    allow_acceptance_switch: bool,
    start_round: int = 1,
    existing_trajectory: Sequence[Mapping[str, Any]] | None = None,
    force_pose_search: bool = False,
    skip_coil: bool = False,
    poses_override_path: Path | None = None,
    baseline_round_id: str = "round_00",
    raster_dest: Path | None = None,
    pose_search_fine: bool = False,
    skip_body_ops: bool = False,
    force_operator: str | None = None,
    anatomy_stage: str | None = None,
    architecture_source: str | None = None,
    abbreviated_symmetric_only: bool = False,
) -> dict[str, Any]:
    experiment, payload, poses = load_preview_experiment(clip_path, mesh_path)
    payload["_workClip"] = str(clip_path)
    attach_anatomy_catalog(payload, unit)
    if anatomy_stage:
        if anatomy_stage not in ANATOMY_FIT_STAGES:
            raise ValueError(f"unknown anatomy stage {anatomy_stage}")
        payload["_forcedAnatomyStage"] = str(anatomy_stage)
    if architecture_source:
        payload["_architectureSource"] = str(architecture_source)
    if abbreviated_symmetric_only:
        payload["_abbreviatedSymmetricOnly"] = True
        if not architecture_source:
            raise ValueError("symmetric_only requires --architecture-source")
    if poses_override_path is not None:
        loaded = _json_load(Path(poses_override_path))
        poses = clone_pose_map({int(frame): value for frame, value in loaded["poses"].items()})
    sprites = sprite_paths(payload, experiment.frame_indices)
    dest = raster_dest if raster_dest is not None else round00 / "raster"
    before = raster_bundle(experiment, poses, dest)
    index["rasterResolution"] = before["resolution"]
    if skip_coil:
        coil: dict[str, Any] = {}
    else:
        coil = coil_detect_overlay(mesh_path, round00 / "coil_weld")
    occupancy = unique_and_assignment(experiment, before)
    if force_operator == CLASS_POSE_SEARCH_DEBT:
        debt = False
    elif force_operator == CLASS_BODY_INFEASIBLE_REST:
        debt = False
    else:
        debt = debt_helps(experiment, payload, poses, before, occupancy)
    body_class = classify_occupancy_body(
        leftover_near=bool(occupancy["leftoverNear"]),
        leftover_far=bool(occupancy["leftoverFar"]),
        unassigned_far=bool(occupancy["unassignedFar"]),
        geometry_projects_near=bool(occupancy["geometryProjectsNear"]),
        debt_helps=bool(debt),
        owner_agrees=bool(occupancy["ownerAgrees"]),
        unique_owner=occupancy["uniqueOwner"],
    )
    if coil.get("class") == CLASS_TOPOLOGY_FUSED:
        index["overlayClasses"] = [CLASS_TOPOLOGY_FUSED]
    index["expectedClassBeforeOperators"] = body_class
    index["occupancy"] = {
        "leftoverNear": occupancy["leftoverNear"],
        "leftoverFar": occupancy["leftoverFar"],
        "geometryProjectsNear": occupancy["geometryProjectsNear"],
        "uniqueOwner": occupancy["uniqueOwner"],
        "ownerVote": occupancy["ownerVote"],
        "assignedCounts": occupancy["assignedCounts"],
    }
    _json_dump(work / "index.json", index)
    if body_class == CLASS_MISSING_GEOMETRY and not force_pose_search and not force_operator:
        index["primaryClass"] = CLASS_NEEDS_GEOMETRY_AUTHORING
        close_experiment(experiment)
        _json_dump(work / "index.json", index)
        return index
    if body_class in ARTICULATION_ACCEPTANCE_CLASSES and allow_acceptance_switch:
        target_clip = acceptance_clip or ARTICULATION_CLIP
        if clip != target_clip:
            index["acceptanceClip"] = target_clip
            index["acceptanceSwitch"] = True
            _json_dump(work / "index.json", index)
            close_experiment(experiment)
            accepted = run_unit_clip(
                unit=unit,
                clip=target_clip,
                expected_first_class=None,
                acceptance_clip=target_clip,
                allow_acceptance_switch=False,
            )
            acceptance_index = work_tree_root(ROOT) / unit / target_clip / "index.json"
            index["acceptanceIndex"] = str(acceptance_index.resolve()).replace("\\", "/")
            index["primaryClass"] = accepted.get("primaryClass")
            index["argmaxRound"] = accepted.get("argmaxRound")
            index["finalGif"] = accepted.get("finalGif")
            index["acceptedBodyRounds"] = accepted.get("acceptedBodyRounds")
            index["bodySurgery"] = True
            _json_dump(work / "index.json", index)
            return index
    if existing_trajectory:
        trajectory = [dict(row) for row in existing_trajectory]
        original_metrics = None
        for row in trajectory:
            if str(row.get("roundId")) == str(baseline_round_id) and "leftover" in row:
                original_metrics = dict(row)
        if original_metrics is None:
            original_metrics = {
                "roundId": baseline_round_id,
                "accepted": True,
                "leftover": float(before["fractions"].leftover),
                "extra": float(before["fractions"].extra),
                "strain": float(before["strain"]),
                "class": "resume_baseline",
                "pngDir": str(before["pngDir"]),
            }
            trajectory.append(dict(original_metrics))
    else:
        original_metrics = {
            "roundId": baseline_round_id,
            "accepted": True,
            "leftover": float(before["fractions"].leftover),
            "extra": float(before["fractions"].extra),
            "strain": float(before["strain"]),
            "class": "original" if baseline_round_id == "round_00" else CLASS_CAMERA_RESOLVED_POSE_STALE,
            "pngDir": str(before["pngDir"]),
        }
        trajectory = [dict(original_metrics)]
    if is_feasible(before["fractions"]):
        index["primaryClass"] = CLASS_FEASIBLE
        index["trajectory"] = trajectory
        close_experiment(experiment)
        _json_dump(work / "index.json", index)
        return index
    tried: list[str] = []
    accepted_body = 0
    consecutive_rejects = 0
    current_mesh = mesh_path
    current_poses = clone_pose_map(poses)
    current_before = before
    current_occupancy = occupancy
    round_index = int(start_round)
    pending = (
        force_operator
        if force_operator
        else (
            CLASS_POSE_SEARCH_DEBT
            if force_pose_search or body_class == CLASS_POSE_SEARCH_DEBT
            else next_body_class(tried)
        )
    )
    diagnosed = str(index.get("expectedClassBeforeOperators") or body_class)
    while pending and accepted_body < MAX_BODY_ROUNDS:
        round_dir = work / f"round_{round_index:02d}"
        result = operate_round(
            round_dir=round_dir,
            class_name=pending,
            experiment=experiment,
            payload=payload,
            poses=current_poses,
            mesh_path=current_mesh,
            occupancy=current_occupancy,
            before=current_before,
            sprites=sprites,
            camera_fit=camera_path,
            clip_name=clip,
            pose_search_fine=pose_search_fine,
        )
        if result.get("rejectedEarly"):
            trajectory.append(result["report"])
            index["trajectory"] = trajectory
            _json_dump(work / "index.json", index)
            consecutive_rejects += 1
            tried.append(pending)
            pending = None if skip_body_ops else next_pending_class(
                tried=tried,
                consecutive_rejects=consecutive_rejects,
                diagnosed=diagnosed,
            )
            round_index += 1
            continue
        if result.get("afterRaster") is not None:
            current_poses = result["poses"]
            current_mesh = Path(result["mesh"])
            after = result["afterRaster"]
        elif result.get("needsReload"):
            close_experiment(experiment)
            work_clip = round_dir / "gpu_clip_result.json"
            payload_next = rewrite_work_clip(
                payload,
                camera_fit=camera_path,
                init_path=round00 / "profile_camera_initialization.json",
                poses=result["poses"],
            )
            _json_dump(work_clip, payload_next)
            experiment, payload, _ignore = load_preview_experiment(work_clip, Path(result["mesh"]))
            payload["_workClip"] = str(work_clip)
            attach_anatomy_catalog(payload, unit)
            if result.get("insertName"):
                current_poses, reaim = leftover_pose_search(
                    experiment,
                    payload,
                    result["poses"],
                    [str(result["insertName"])],
                    fine=False,
                    clip_name=clip,
                )
                result.setdefault("details", {})["insertReaim"] = {
                    "keptSharedBones": reaim.get("keptSharedBones"),
                    "keptPerFrame": reaim.get("keptPerFrame"),
                    "bones": reaim.get("bones"),
                    "sharedSkeleton": True,
                    "temporalWrap": reaim.get("temporalWrap"),
                }
                write_after_poses(
                    round_dir / "after_poses.json",
                    current_poses,
                    frame_indices=experiment.frame_indices,
                    camera_fit_path=camera_path,
                )
            else:
                current_poses = result["poses"]
            current_mesh = Path(result["mesh"])
            after = raster_bundle(experiment, current_poses, result["afterPng"])
        else:
            current_poses = result["poses"]
            after = raster_bundle(experiment, current_poses, result["afterPng"])
        gate = accept_surgery(
            current_before["fractions"],
            after["fractions"],
            strain_before=float(current_before["strain"]),
            strain_after=float(after["strain"]),
        )
        if pending == CLASS_POSE_SEARCH_DEBT:
            leftover_drop = float(current_before["fractions"].leftover) - float(after["fractions"].leftover)
            extra_growth = float(after["fractions"].extra) - float(current_before["fractions"].extra)
            flight_attitude = (
                ((result.get("details") or {}).get("search") or {}).get("flightAttitude") or {}
            )
            if bool(flight_attitude.get("pitchedRootCleared")):
                accepted = True
            elif bool(flight_attitude.get("applied")):
                search = ((result.get("details") or {}).get("search") or {})
                attitude_frames = (search.get("perFrameAttitude") or {}).get("frames") or []
                broad_ok = flyer_broad_stroke_ok(attitude_frames) if attitude_frames else False
                fill_deferred = bool(search.get("leftoverFillDeferred"))
                attitude_kept = int((search.get("sharedPhaseAttitude") or {}).get("kept") or 0)
                if leftover_drop < -1e-9 and extra_growth > 1e-9 and not fill_deferred:
                    accepted = False
                elif not broad_ok and not fill_deferred:
                    accepted = False
                elif broad_ok:
                    accepted = True
                elif fill_deferred:
                    phase_scores = [
                        float(row.get("spriteAxisScore") or -2.0)
                        for row in ((search.get("sharedPhaseAttitude") or {}).get("phases") or [])
                    ]
                    accepted = attitude_kept > 0 and bool(phase_scores) and min(phase_scores) >= 0.0
                elif search.get("reseatedIdentitySideView"):
                    seed_drop = float(search.get("leftoverBefore") or 1.0) - float(
                        search.get("leftoverAfter") or after["fractions"].leftover
                    )
                    accepted = seed_drop > 1e-9
                else:
                    accepted = leftover_drop > 1e-9
            else:
                accepted = leftover_drop > 1e-9 and extra_growth <= EPSILON_EXTRA + 1e-12
        elif pending in {CLASS_BODY_INFEASIBLE_REST, CLASS_BODY_INFEASIBLE_LENGTH, CLASS_MISSING_JOINT}:
            occupancy_gate = accept_occupancy_rest(current_before["fractions"], after["fractions"])
            # ARCHITECTURE_ACCEPT_NAMES: phase_baked_fly_rest, phase_glide_rest_rotation,
            # phase_glide_wing_spread, phase_glide_symmetric_wing_spread,
            # anatomy_tpose_snip_rotation, symmetric_bone_fit, asymmetric_fine_tune,
            # shared_skeleton_temporal, insert_missing_symmetric, symmetric_only
            if (result.get("details") or {}).get("architecture") in ARCHITECTURE_ACCEPT_NAMES:
                accepted = True
                gate = {
                    **occupancy_gate,
                    "accepted": True,
                    "architectureAccept": True,
                    "notOccupancyGate": True,
                }
            else:
                gate = occupancy_gate
                accepted = bool(occupancy_gate["accepted"])
        else:
            accepted = bool(gate["accepted"])
        caption = (
            f"{result['class']} {result['operator']} leftover={after['fractions'].leftover:.3f} "
            f"extra={after['fractions'].extra:.3f} strain={after['strain']:.3f} "
            f"{'accept' if accepted else 'reject'}"
        )
        gif = write_compare_gif(
            sprite_paths=sprites,
            panel_a=current_before["pngDir"],
            panel_b=after["pngDir"],
            frames=list(experiment.frame_indices),
            dest=round_dir / "compare.gif",
            labels=("sprite", "before", "after"),
            caption=caption,
        )
        report = {
            "roundId": round_dir.name,
            "accepted": accepted,
            "class": CLASS_SURGERY_REJECTED if not accepted else result["class"],
            "operator": result["operator"],
            "leftover": float(after["fractions"].leftover),
            "extra": float(after["fractions"].extra),
            "strain": float(after["strain"]),
            "gate": gate,
            "details": result["details"],
            "gif": str(gif).replace("\\", "/"),
            "afterGlb": None if not accepted else str(Path(result["mesh"]).resolve()).replace("\\", "/"),
        }
        _json_dump(round_dir / "round_report.json", report)
        if accepted:
            payload_written = rewrite_work_clip(
                payload,
                camera_fit=camera_path,
                init_path=round00 / "profile_camera_initialization.json",
                poses=current_poses,
            )
            _json_dump(round_dir / "gpu_clip_result.json", payload_written)
            if not result.get("skipVisionCheck"):
                vision = write_vision_check(
                    experiment=experiment,
                    payload=payload,
                    poses=current_poses,
                    dest=round_dir / "vision_check",
                    sprites=sprites,
                    world_up=world_up_from_camera_fit(camera_path),
                )
                report["visionCheck"] = {
                    "orbitGif": vision["orbitGif"],
                    "sheets": vision["sheets"],
                    "report": str((round_dir / "vision_check" / "vision_check.json").resolve()).replace("\\", "/"),
                }
                _json_dump(round_dir / "round_report.json", report)
        if (result.get("details") or {}).get("architecture") in ARCHITECTURE_ACCEPT_NAMES:
            index["architectureRound"] = round_dir.name
            index["architectureGif"] = str(gif).replace("\\", "/")
        trajectory.append(report)
        index["trajectory"] = trajectory
        _json_dump(work / "index.json", index)
        tried.append(pending)
        if accepted:
            consecutive_rejects = 0
            if pending != CLASS_POSE_SEARCH_DEBT:
                accepted_body += 1
            current_before = after
            if not result.get("skipReloadOccupancy"):
                current_occupancy = unique_and_assignment(experiment, after)
            if is_feasible(after["fractions"]):
                pending = None
                break
            if skip_body_ops:
                pending = None
            elif accepted:
                pending = next_pending_class(
                    tried=tried,
                    consecutive_rejects=0,
                    diagnosed=diagnosed,
                )
            else:
                consecutive_rejects += 1
                pending = next_pending_class(
                    tried=tried,
                    consecutive_rejects=consecutive_rejects,
                    diagnosed=diagnosed,
                )
        else:
            consecutive_rejects += 1
            pending = None if skip_body_ops else next_pending_class(
                tried=tried,
                consecutive_rejects=consecutive_rejects,
                diagnosed=diagnosed,
            )
        round_index += 1
    close_experiment(experiment)
    exclude_old_camera = str(baseline_round_id) == "round_01"
    candidates = []
    for row in trajectory:
        if "leftover" not in row:
            continue
        if exclude_old_camera and str(row.get("roundId")) == "round_00":
            continue
        if str(row.get("roundId")) == str(baseline_round_id) or row.get("accepted"):
            candidates.append(row)
    chosen = argmax_round(candidates, leftover_tie=0.005)
    selected_png = png_dir_for_round(work, str(chosen["roundId"]), chosen)
    baseline_png = png_dir_for_round(work, str(baseline_round_id), original_metrics)
    final = write_compare_gif(
        sprite_paths=sprites,
        panel_a=baseline_png,
        panel_b=selected_png,
        frames=[int(frame) for frame in _json_load(clip_path)["frameIndices"]],
        dest=work / "final_compare.gif",
        labels=("sprite", str(baseline_round_id), chosen["roundId"]),
        caption=f"argmax {chosen['roundId']} leftover={chosen['leftover']:.3f}",
    )
    if any(is_feasible_row(row) for row in trajectory if row.get("accepted") and "leftover" in row):
        primary = CLASS_FEASIBLE
    elif accepted_body >= MAX_BODY_ROUNDS or next_pending_class(
        tried=tried,
        consecutive_rejects=consecutive_rejects,
        diagnosed=diagnosed,
    ) is None:
        primary = CLASS_PARTIAL_SURGERY_EXHAUSTED
    else:
        primary = str(trajectory[-1]["class"]) if trajectory else body_class
    index.update(
        {
            "primaryClass": primary,
            "expectedClassBeforeOperators": body_class,
            "argmaxRound": chosen["roundId"],
            "finalGif": str(final).replace("\\", "/"),
            "trajectory": trajectory,
            "acceptedBodyRounds": accepted_body,
            "bodySurgery": True,
        }
    )
    _json_dump(work / "index.json", index)
    return index


def is_feasible_row(row: Mapping[str, Any]) -> bool:
    return float(row["leftover"]) <= FEASIBLE_LEFTOVER and float(row["extra"]) <= FEASIBLE_EXTRA


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--clip", required=True)
    parser.add_argument("--expected-first-class", default=None)
    parser.add_argument("--acceptance-clip", default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an existing work tree. Skips camera rewrite. Searches poses under the written camera.",
    )
    parser.add_argument(
        "--operator",
        default=None,
        choices=sorted(set(OPERATOR_ALIASES) | set(ANATOMY_FIT_STAGES) | {"symmetric_only"}),
        help="Run one named operator on --resume. Anatomy stage names redo that fit stage. "
        "symmetric_only is pair search only (no snip, per-side tune, leftover walk, or bone insert).",
    )
    parser.add_argument(
        "--architecture-source",
        default=None,
        help="Round id whose fly rests a symmetric_only pass copies (for example round_08).",
    )
    parser.add_argument(
        "--recompose-gifs",
        action="store_true",
        help="Rebuild compare GIFs from existing stills at integer nearest-neighbor scale. No GPU raster.",
    )
    parser.add_argument(
        "--vision-check",
        action="store_true",
        help="Raster extra cameras for an accepted round. Occupancy leftover is not this gate.",
    )
    parser.add_argument(
        "--vision-check-round",
        default=None,
        help="Round id for --vision-check. Defaults to the last accepted round.",
    )
    parser.add_argument(
        "--clip-source",
        type=Path,
        default=None,
        help="gpu_clip_result.json to snapshot as round_00. Must be poseUnits=degrees. Does not write live fused-push.",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Archive the existing work tree and snapshot a new round_00 from --clip-source.",
    )
    args = parser.parse_args(argv)
    if args.recompose_gifs and args.vision_check:
        parser.error("--recompose-gifs cannot run with --vision-check")
    if args.vision_check and args.operator:
        parser.error("--vision-check cannot run with --operator")
    if args.reseed and args.resume:
        parser.error("--reseed cannot run with --resume")
    if args.reseed and args.clip_source is None:
        parser.error("--reseed requires --clip-source")
    if args.operator == "symmetric_only" and not args.resume:
        parser.error("symmetric_only requires --resume")
    if args.operator == "symmetric_only" and not args.architecture_source:
        parser.error("symmetric_only requires --architecture-source")
    if args.architecture_source and args.operator != "symmetric_only":
        parser.error("--architecture-source only applies to --operator symmetric_only")
    if args.recompose_gifs:
        report = recompose_work_gifs(unit=str(args.unit), clip=str(args.clip))
        print(json.dumps(report, indent=2))
        return 0
    if args.vision_check:
        lock_path = global_cascade_batch_lock_path(ROOT)
        acquire_cascade_batch_lock(lock_path)
        try:
            vision = run_vision_check_work(
                unit=str(args.unit),
                clip=str(args.clip),
                round_id=args.vision_check_round,
            )
            print(json.dumps(vision, indent=2))
            return 0
        finally:
            release_cascade_batch_lock(lock_path)
    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    try:
        anatomy_stage = None
        operator = None
        abbreviated_symmetric_only = False
        architecture_source = args.architecture_source
        if args.operator == "symmetric_only":
            anatomy_stage = "symmetric_bone_fit"
            operator = CLASS_BODY_INFEASIBLE_REST
            abbreviated_symmetric_only = True
        elif args.operator in ANATOMY_FIT_STAGES:
            anatomy_stage = str(args.operator)
            operator = CLASS_BODY_INFEASIBLE_REST
        elif args.operator is not None:
            operator = OPERATOR_ALIASES[str(args.operator)]
        index = run_unit_clip(
            unit=str(args.unit),
            clip=str(args.clip),
            expected_first_class=args.expected_first_class,
            acceptance_clip=args.acceptance_clip,
            resume=bool(args.resume),
            operator=operator,
            clip_source=args.clip_source,
            reseed=bool(args.reseed),
            anatomy_stage=anatomy_stage,
            architecture_source=architecture_source,
            abbreviated_symmetric_only=abbreviated_symmetric_only,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "index": str((work_tree_root(ROOT) / args.unit / args.clip / "index.json").resolve()),
                    "primaryClass": index.get("primaryClass"),
                    "acceptanceIndex": index.get("acceptanceIndex"),
                },
                indent=2,
            )
        )
        return 0
    finally:
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
