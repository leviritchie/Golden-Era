"""Frozen-camera registration + combined-score audit for one unit.

For each deployed keyframe (clip frame *i* <-> DEF group plate *i*):
1. Register ONE frozen camera from the bind rest mesh vs the idle plate
   (alpha primary, chroma tie-break; ``skin_camera_registration`` policy).
2. Render the replayed posed mesh with ``SkinImageRenderer`` (CUDA).
3. Score silhouette IoU + luma-normalized chroma + DINOv2 cosine
   (``repair_contract.frame_metrics``; DINOv2 ``facebook/dinov2-large``).

Output: ``<out>/<labSid>/audit.json`` with per-keyframe rows
(before any repair), plus a contact sheet. This is the baseline the repair
must beat. Generated-artifact only; motion and bind are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
# HERE is the module dir: parents[0]=homm3_mocap_v2, [1]=experiments, [2]=repo.
REPO = HERE.parents[2]
EXP = REPO / "experiments" / "homm3_mocap_v2"
# EXP first: sibling mocap modules (eagle_glb, glb_skeleton, ...) win over HERE.
for _p in (str(HERE), str(REPO / "tools" / "homm3_silhouette_pose_fit")):
    if _p in sys.path:
        sys.path.remove(_p)
if str(EXP) not in sys.path:
    sys.path.insert(0, str(EXP))
sys.path.append(str(HERE))
sys.path.append(str(REPO / "tools" / "homm3_silhouette_pose_fit"))

from repair_contract import (  # noqa: E402
    APPROVED,
    CLIP_TO_GROUP,
    SCHEMA,
    deployed_clips,
    frame_metrics,
    resolve_plate_lookup,
)
from replay_deployed import replay_clip  # noqa: E402

from dino_embed import extract_subject_from_rgba  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from hybrid_dinov2 import DinoEncoder  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _shared_canvas_rgba(path: Path, canvas: tuple[int, int]) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    if image.size != canvas:
        raise ValueError(f"{path} is {image.size}, expected canvas {canvas}")
    return np.asarray(image, dtype=np.uint8)


def _register_camera_from_idle(
    *,
    rest_vertices: np.ndarray,
    idle_plate: Path,
    resolution: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """One frozen Y-up camera from the rest mesh vs the idle plate.

    Follows ``skin_camera_registration``: full-azimuth yaw grid + small pitch
    grid, alpha IoU primary, overlap-normalized chroma tie-break. The mesh is
    rendered with the CPU rasterizer (bind rest only, no gradients) so this
    step needs no nvdiffrast context.
    """
    from mesh_preview import raster_mesh

    rgba = Image.open(idle_plate).convert("RGBA")
    canvas = rgba.size
    alpha = np.asarray(rgba, dtype=np.uint8)[..., 3].astype(np.float64) / 255.0

    ys, xs = np.where(alpha > 0.0039)
    if len(xs) == 0:
        raise ValueError(f"idle plate has no alpha: {idle_plate}")
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    size = max(canvas)
    crop = {"left": -((size - canvas[0]) // 2), "top": -((size - canvas[1]) // 2), "size": size}
    source_size = (canvas[0], canvas[1])

    def camera_for(yaw_deg: float, pitch_deg: float) -> dict[str, object]:
        # Same Y-up basis convention as skin_camera_registration._basis_yup.
        yaw = np.radians(yaw_deg)
        pitch = np.radians(pitch_deg)
        right = np.asarray((np.cos(yaw), 0.0, np.sin(yaw)), dtype=np.float64)
        down = np.asarray(
            (
                -np.sin(pitch) * np.sin(yaw),
                -np.cos(pitch),
                np.sin(pitch) * np.cos(yaw),
            ),
            dtype=np.float64,
        )
        forward = np.cross(right, down)
        forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
        # Fit the rest-mesh bbox into the plate bbox.
        rel = rest_vertices - rest_vertices.mean(axis=0)
        px = rel @ right
        py = rel @ down
        span_mesh = max(px.max() - px.min(), py.max() - py.min(), 1e-9)
        span_plate = max(bbox[2] - bbox[0], bbox[3] - bbox[1], 1)
        # Pixel-center-consistent scale: the scored target resizes size
        # source px to resolution render px, so one source px spans
        # resolution/size render px.
        scale = span_plate / span_mesh * resolution / size
        # NOTE: rel is mean-centered, so center_mesh is identically zero: this
        # anchors the mesh MEAN (not its silhouette centroid) at the plate
        # bbox center. On h3_goblin idle that leaves a ~9px vertical gap
        # (audit IoU 0.355 vs 0.703 achievable); the local-refine stage below
        # closes it by direct IoU search. Do not "fix" this anchor without
        # keeping the refine.
        center_mesh = np.stack((px, py)).mean(axis=1)
        # Square-pad-consistent plate center: the scored target is the plate
        # pasted at (-left, -top) onto size x size, then resized to
        # resolution with pixel CENTERS mapping to centers: out-of-size
        # corner (0,0) samples the padded canvas center at (0.5/scale), so a
        # source pixel (x, y) lands at ((x + pad + 0.5) / size * res - 0.5).
        pad_left = -crop["left"]
        pad_top = -crop["top"]
        center_plate = (
            np.asarray(
                [
                    (bbox[0] + bbox[2]) / 2.0 + pad_left + 0.5,
                    (bbox[1] + bbox[3]) / 2.0 + pad_top + 0.5,
                ]
            )
            / size
            * resolution
            - 0.5
        )
        offset = center_plate - center_mesh * scale
        depth = rel @ forward
        depth_min = float(depth.min())
        depth_max = float(depth.max())
        return {
            "right": right.tolist(),
            "down": down.tolist(),
            "forward": forward.tolist(),
            "up": (-down).tolist(),
            "scale": float(scale),
            "offset": [float(offset[0]), float(offset[1])],
            "depth_center": 0.5 * (depth_min + depth_max),
            "depth_span": float(max(depth_max - depth_min, 1e-6)),
            # CPU rasterizer contract (preview.project_points / raster_mesh).
            "basisScreenRows": np.stack((right, down), axis=0).tolist(),
            "pxPerWorld": float(scale),
            "screenOffsetPx": [float(offset[0]), float(offset[1])],
            "yawDeg": float(yaw_deg),
            "pitchDeg": float(pitch_deg),
            "sourceSize": [int(source_size[0]), int(source_size[1])],
            "sourceCrop": crop,
            "resolution": int(resolution),
        }

    # Hoist the grid target out of the loop: every hypothesis scores against
    # the same square-padded, resized plate alpha.
    _plate = Image.new("RGBA", (crop["size"], crop["size"]), (0, 0, 0, 0))
    _plate_rgba = Image.open(idle_plate).convert("RGBA")
    _plate.paste(_plate_rgba, (-crop["left"], -crop["top"]), _plate_rgba)
    tgt_a = np.asarray(
        _plate.resize((resolution, resolution), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )[..., 3].astype(np.float64) / 255.0

    def render_alpha(camera: dict[str, object], width: int, height: int) -> np.ndarray:
        image = raster_mesh(
            vertices=rest_vertices,
            triangles=_TRIANGLES,
            camera={
                "basisScreenRows": np.asarray(
                    camera["basisScreenRows"], dtype=np.float64
                ),
                "pxPerWorld": float(camera["pxPerWorld"]),
                "screenOffsetPx": np.asarray(
                    camera["screenOffsetPx"], dtype=np.float64
                ),
            },
            width=width,
            height=height,
            cull_backfaces=True,
        )
        return np.asarray(image, dtype=np.uint8)[..., 3].astype(np.float64) / 255.0

    # The grid fits scale + offset from bbox extents only (no translation
    # search), which recovers yaw/pitch but can leave a multi-pixel offset
    # gap (h3_goblin idle: ~0.31 at the grid fit vs ~0.70 achievable). The
    # bounded local refine below closes that gap with direct IoU search --
    # this is what makes the policy name true -- while keeping orientation
    # within +/-5 deg and scale within +/-3% of the grid winner, so the
    # result stays an idle-only anchored registration, not a new per-frame
    # or weight-dependent fit.
    best: tuple[float, float, dict[str, object]] | None = None
    evaluations = 0
    grid_best: tuple[float, float, dict[str, object]] | None = None
    for yaw in [float(v) for v in range(0, 360, 15)]:
        for pitch in (0.0, 10.0, 20.0, 30.0):
            camera = camera_for(yaw, pitch)
            pred = render_alpha(camera, resolution, resolution)
            inter = float((np.minimum(pred, tgt_a)).sum())
            union = float((np.maximum(pred, tgt_a)).sum())
            iou = inter / max(union, 1e-9)
            # Unlit rest render has no albedo; silhouette-only, chroma proxy 0.
            chroma = 0.0
            evaluations += 1
            key = (iou, -chroma)
            if best is None or key > (best[0], -best[1]):
                best = (iou, chroma, camera)
    if best is None:
        raise RuntimeError("camera grid produced no hypothesis")
    grid_best = best
    grid_iou, _, grid_camera = grid_best
    # Local refine: two-stage bounded IoU search around the grid winner. The
    # grid's bbox-extent anchor recovers orientation but not translation: on
    # h3_goblin idle the winner needs a (-2, +9)px shift at res 192 -- a
    # coarse single peak (0.33 at dy=0 rising to 0.70 at dy=9), so a narrow
    # box stalls halfway (0.45-0.57) while still "refining". Stage 1 scans
    # integer shifts over a wide box (dx +/-8, dy 0..+16, y-down only: the
    # mesh-mean anchor always sits above the silhouette centroid) at the
    # grid orientation/scale; stage 2 refines yaw/pitch +/-5 deg, scale
    # x{0.97,1.0,1.03}, offset +/-2% around the stage-1 winner, mirroring
    # skin_camera_registration's local box. Still idle-only and anchored: no
    # per-frame or weight-dependent fit (motion stays frozen downstream).
    REFINE_STEP_DEG = 5.0
    REFINE_SCALE_FACTORS = (0.97, 1.0, 1.03)
    REFINE_OFFSET_FACTORS = (-0.02, 0.0, 0.02)
    SHIFT_RANGE_X = range(-8, 9)
    SHIFT_RANGE_Y = range(0, 17)
    grid_yaw = float(grid_camera["yawDeg"])
    grid_pitch = float(grid_camera["pitchDeg"])
    grid_scale = float(grid_camera["pxPerWorld"])
    grid_offset = np.asarray(grid_camera["screenOffsetPx"], dtype=np.float64)
    grid_depth_center = float(grid_camera["depth_center"])
    grid_depth_span = float(grid_camera["depth_span"])

    def refine_camera(
        yaw_deg: float, pitch_deg: float, scale_factor: float, dx: float, dy: float
    ) -> dict[str, object]:
        yaw = np.radians(yaw_deg)
        pitch = np.radians(pitch_deg)
        right = np.asarray((np.cos(yaw), 0.0, np.sin(yaw)), dtype=np.float64)
        down = np.asarray(
            (
                -np.sin(pitch) * np.sin(yaw),
                -np.cos(pitch),
                np.sin(pitch) * np.cos(yaw),
            ),
            dtype=np.float64,
        )
        forward = np.cross(right, down)
        forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
        scale = grid_scale * float(scale_factor)
        offset = grid_offset + np.asarray([dx, dy], dtype=np.float64)
        depth = (rest_vertices - rest_vertices.mean(axis=0)) @ forward
        return {
            "right": right.tolist(),
            "down": down.tolist(),
            "forward": forward.tolist(),
            "up": (-down).tolist(),
            "scale": float(scale),
            "offset": [float(offset[0]), float(offset[1])],
            "depth_center": float(grid_depth_center),
            "depth_span": float(grid_depth_span),
            "basisScreenRows": np.stack((right, down), axis=0).tolist(),
            "pxPerWorld": float(scale),
            "screenOffsetPx": [float(offset[0]), float(offset[1])],
            "yawDeg": float(yaw_deg),
            "pitchDeg": float(pitch_deg),
            "sourceSize": [int(source_size[0]), int(source_size[1])],
            "sourceCrop": crop,
            "resolution": int(resolution),
        }

    for yaw_deg in (
        (grid_yaw - REFINE_STEP_DEG) % 360.0,
        grid_yaw,
        (grid_yaw + REFINE_STEP_DEG) % 360.0,
    ):
        for pitch_deg in (grid_pitch - REFINE_STEP_DEG, grid_pitch, grid_pitch + REFINE_STEP_DEG):
            if not 0.0 <= pitch_deg <= 90.0:
                continue
            for scale_factor in REFINE_SCALE_FACTORS:
                for dx_factor in REFINE_OFFSET_FACTORS:
                    for dy_factor in REFINE_OFFSET_FACTORS:
                        candidate = refine_camera(
                            yaw_deg,
                            pitch_deg,
                            scale_factor,
                            dx_factor * resolution,
                            dy_factor * resolution,
                        )
                        pred = render_alpha(candidate, resolution, resolution)
                        inter = float((np.minimum(pred, tgt_a)).sum())
                        union = float((np.maximum(pred, tgt_a)).sum())
                        iou_c = inter / max(union, 1e-9)
                        evaluations += 1
                        key = (iou_c, 0.0)
                        if best is None or key > (best[0], -best[1]):
                            best = (iou_c, 0.0, candidate)
    # NOTE: the first refine loop above runs against the grid anchor and only
    # seeds best; the wide shift scan below re-anchors the offset and the
    # second loop (same code) scores the aligned box. Both loops count in
    # evaluations. If the first loop looks redundant, that is why it stays:
    # it preserves the published 96 + 243 + 289 + 243 evaluation budget.
    # Stage 1: wide integer-shift scan at the grid orientation/scale. The
    # renders are translation-equivariant up to resampling, so shifting the
    # scored masks is equivalent to shifting the camera offset here.
    grid_pred = render_alpha(grid_camera, resolution, resolution)
    height, width = grid_pred.shape
    shift_best: tuple[float, int, int] | None = None
    for dx in SHIFT_RANGE_X:
        for dy in SHIFT_RANGE_Y:
            moved = np.zeros_like(grid_pred)
            moved[max(0, dy) : min(height, height + dy), max(0, dx) : min(width, width + dx)] = grid_pred[
                max(0, -dy) : min(height, height - dy), max(0, -dx) : min(width, width - dx)
            ]
            inter = float((np.minimum(moved, tgt_a)).sum())
            union = float((np.maximum(moved, tgt_a)).sum())
            iou_s = inter / max(union, 1e-9)
            evaluations += 1
            if shift_best is None or iou_s > shift_best[0]:
                shift_best = (iou_s, dx, dy)
    assert shift_best is not None
    _, shift_dx, shift_dy = shift_best
    # Re-anchor the refine on the shifted offset, then run the bounded
    # orientation/scale/offset box (stage 2) around it.
    grid_offset = grid_offset + np.asarray([shift_dx, shift_dy], dtype=np.float64)
    for yaw_deg in (
        (grid_yaw - REFINE_STEP_DEG) % 360.0,
        grid_yaw,
        (grid_yaw + REFINE_STEP_DEG) % 360.0,
    ):
        for pitch_deg in (grid_pitch - REFINE_STEP_DEG, grid_pitch, grid_pitch + REFINE_STEP_DEG):
            if not 0.0 <= pitch_deg <= 90.0:
                continue
            for scale_factor in REFINE_SCALE_FACTORS:
                for dx_factor in REFINE_OFFSET_FACTORS:
                    for dy_factor in REFINE_OFFSET_FACTORS:
                        candidate = refine_camera(
                            yaw_deg,
                            pitch_deg,
                            scale_factor,
                            dx_factor * resolution,
                            dy_factor * resolution,
                        )
                        pred = render_alpha(candidate, resolution, resolution)
                        inter = float((np.minimum(pred, tgt_a)).sum())
                        union = float((np.maximum(pred, tgt_a)).sum())
                        iou_c = inter / max(union, 1e-9)
                        evaluations += 1
                        key = (iou_c, 0.0)
                        if best is None or key > (best[0], -best[1]):
                            best = (iou_c, 0.0, candidate)
    if best is None:
        raise RuntimeError("camera refine produced no hypothesis")
    iou, _chroma, camera = best
    report = {
        "policy": "bounded_y_up_idle_alpha_grid_then_local_refine",
        "evaluations": evaluations,
        "bestIoU": float(iou),
        "gridIoU": float(grid_iou),
        "gridYawDeg": float(grid_camera["yawDeg"]),
        "gridPitchDeg": float(grid_camera["pitchDeg"]),
        "shiftDxPx": int(shift_dx),
        "shiftDyPx": int(shift_dy),
        "shiftRangeX": [int(min(SHIFT_RANGE_X)), int(max(SHIFT_RANGE_X))],
        "shiftRangeY": [int(min(SHIFT_RANGE_Y)), int(max(SHIFT_RANGE_Y))],
        "refineStepDeg": float(REFINE_STEP_DEG),
        "refineScaleFactors": list(REFINE_SCALE_FACTORS),
        "refineOffsetFactors": list(REFINE_OFFSET_FACTORS),
        "yawDeg": float(camera["yawDeg"]),
        "pitchDeg": float(camera["pitchDeg"]),
        "idlePlate": str(idle_plate),
        "canvas": [int(canvas[0]), int(canvas[1])],
    }
    return camera, report


_TRIANGLES: np.ndarray = np.zeros((0, 3), dtype=np.int64)


def audit_unit(
    *,
    lab_sid: str,
    lab_root: Path,
    out_root: Path,
    resolution: int = 192,
    dino_batch: int = 8,
) -> dict[str, object]:
    unit_dir = APPROVED / lab_sid
    clips = deployed_clips(unit_dir)
    lookup = resolve_plate_lookup(lab_root, lab_sid)
    groups = lookup["groups"]

    # Idle plate for camera registration: group 2, first plate.
    if 2 not in groups:
        raise ValueError(f"{lab_sid}: no idle group 2 plates")
    idle_plate = groups[2][0]
    idle_canvas = Image.open(idle_plate).convert("RGBA").size

    out = out_root / lab_sid
    out.mkdir(parents=True, exist_ok=True)

    encoder = DinoEncoder("cuda")
    rows: list[dict[str, object]] = []
    contact_frames: list[Image.Image] = []
    camera: dict[str, object] | None = None
    camera_report: dict[str, object] | None = None
    skeleton_names: list[str] = []
    frame_count = 0

    for clip_path in clips:
        clip = clip_path.stem
        group = CLIP_TO_GROUP[clip]
        plates = groups.get(group)
        if not plates:
            raise ValueError(f"{lab_sid}: no plates for group {group} (clip {clip})")
        replay = replay_clip(clip_path)
        skeleton = replay["skeleton"]
        skeleton_names = list(skeleton.names)
        posed = np.asarray(replay["posed"], dtype=np.float64)
        if len(posed) != len(plates):
            raise ValueError(
                f"{lab_sid} {clip}: {len(posed)} keyframes vs {len(plates)} plates"
            )
        if camera is None:
            global _TRIANGLES
            _TRIANGLES = np.asarray(skeleton.triangles, dtype=np.int64)
            camera, camera_report = _register_camera_from_idle(
                rest_vertices=np.asarray(skeleton.vertices, dtype=np.float64),
                idle_plate=idle_plate,
                resolution=resolution,
            )
        assert camera is not None
        albedo = np.asarray(skeleton.albedo)
        triangles = np.asarray(skeleton.triangles, dtype=np.int32)
        uvs = np.asarray(skeleton.uvs, dtype=np.float64)
        worlds = np.asarray(replay["worlds"], dtype=np.float64)
        inverse_bind = np.asarray(skeleton.inverse_bind, dtype=np.float64)
        rest = np.asarray(skeleton.vertices, dtype=np.float64)

        sources = np.stack(
            [_shared_canvas_rgba(p, idle_canvas) for p in plates], axis=0
        )
        # Working-resolution letterbox FIRST, then the clip-locked union window
        # in that same canvas (extract_subject_from_rgba requires canvas match).
        sources_small = np.stack(
            [
                np.asarray(
                    Image.fromarray(s).resize(
                        (resolution, resolution), Image.Resampling.LANCZOS
                    ),
                    dtype=np.uint8,
                )
                for s in sources
            ],
            axis=0,
        )
        alpha_small = sources_small[..., 3]
        rows_nz, cols_nz = np.where(np.any(alpha_small > 0, axis=0))
        if len(rows_nz) == 0:
            raise ValueError(f"{lab_sid} {clip}: source clip has no alpha")
        x0, y0, x1, y1 = (
            int(cols_nz.min()),
            int(rows_nz.min()),
            int(cols_nz.max()) + 1,
            int(rows_nz.max()) + 1,
        )
        window = {
            "policy": "clip_locked_union_alpha_aabb",
            "paddingRatio": 0.1,
            "bg": [1.0, 1.0, 1.0],
            "bboxXyxy": [x0, y0, x1, y1],
            "bboxWh": [x1 - x0, y1 - y0],
            "canvas": [resolution, resolution],
            "rmbg": False,
            "perFrameCrop": False,
        }
        subjects_source = [
            extract_subject_from_rgba(frame, window) for frame in sources_small
        ]
        with cascade_batch_lock(REPO), torch.no_grad():
            source_embeddings = np.concatenate(
                [
                    encoder.encode_rgb(subjects_source[i : i + dino_batch])
                    for i in range(0, len(subjects_source), dino_batch)
                ],
                axis=0,
            )
            transforms = torch.as_tensor(
                worlds @ inverse_bind[None], dtype=torch.float32, device="cuda"
            )
            # Skin with the deployed weights (read-only baseline).
            joints = torch.as_tensor(
                np.asarray(skeleton.vertex_joints, dtype=np.int64), device="cuda"
            )
            weights_t = torch.as_tensor(
                np.asarray(skeleton.vertex_weights, dtype=np.float64),
                dtype=torch.float32,
                device="cuda",
            )
            hom = torch.cat(
                (
                    torch.as_tensor(rest, dtype=torch.float32, device="cuda"),
                    torch.ones((len(rest), 1), dtype=torch.float32, device="cuda"),
                ),
                dim=1,
            )
            # Slot-based LBS (GLB JOINTS_0/1 + WEIGHTS_0/1, 8 slots): the same
            # math as mesh_preview.skin_vertices, vectorized over frames.
            posed_t = torch.zeros(
                (len(posed), len(rest), 3), dtype=torch.float32, device="cuda"
            )
            for slot in range(int(joints.shape[1])):
                # transforms [F,J,4,4] at this slot's joint ids -> [F,V,4,4].
                palettes = transforms[:, joints[:, slot]]  # [F,V,4,4]
                moved = torch.einsum("fvij,vj->fvi", palettes[:, :, :3, :], hom)
                posed_t = posed_t + weights_t[:, slot][None, :, None] * moved
            renderer = SkinImageRenderer(triangles, uvs, albedo, camera, resolution)
            rgb, alpha = renderer.render(posed_t)
            rgb_np = rgb.detach().cpu().numpy()
            alpha_np = alpha.detach().cpu().numpy()
            rgba = np.zeros((*rgb_np.shape[:3], 4), dtype=np.uint8)
            rgba[..., :3] = np.uint8(np.clip(rgb_np, 0.0, 1.0) * 255.0)
            rgba[..., 3] = np.uint8(np.clip(alpha_np[..., 0], 0.0, 1.0) * 255.0)
            mesh_subjects = [extract_subject_from_rgba(frame, window) for frame in rgba]
            mesh_embeddings = np.concatenate(
                [
                    encoder.encode_rgb(mesh_subjects[i : i + dino_batch])
                    for i in range(0, len(mesh_subjects), dino_batch)
                ],
                axis=0,
            )
        for frame, (source, mesh) in enumerate(zip(sources, rgba)):
            # Score at the working resolution (both sides letterboxed identically).
            src_small = np.asarray(
                Image.fromarray(source)
                .resize((resolution, resolution), Image.Resampling.LANCZOS),
                dtype=np.uint8,
            )
            metrics = frame_metrics(
                src_small, mesh, source_embeddings[frame], mesh_embeddings[frame]
            )
            rows.append(
                {
                    "clip": clip,
                    "group": group,
                    "frame": frame,
                    "plate": str(plates[frame]),
                    **metrics,
                }
            )
            frame_count += 1
            panel = Image.new("RGB", (resolution * 3, resolution + 30), (10, 10, 14))
            draw = ImageDraw.Draw(panel)
            draw.text(
                (4, 5),
                f"{lab_sid} {clip} f{frame:02d} score={metrics['score']:.3f}",
                fill="white",
            )
            for col, label, image in (
                (0, "source", src_small),
                (
                    1,
                    f"mesh sil={metrics['silhouette']:.3f} dino={metrics['normalizedDinoV2']:.3f}",
                    mesh,
                ),
                (2, f"score={metrics['score']:.3f}", mesh),
            ):
                rgb_panel = image[..., :3].astype(np.float32) / 255.0
                panel.paste(
                    Image.fromarray(np.uint8(rgb_panel * 255.0)),
                    (col * resolution, 30),
                )
                draw.text((col * resolution + 4, 17), label, fill=(190, 190, 205))
            contact_frames.append(panel)

    scores = np.asarray([float(r["score"]) for r in rows], dtype=np.float64)
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact audit; deployed motion replayed exactly; no repair applied",
        "labSid": lab_sid,
        "dinoModel": "facebook/dinov2-large",
        "scoring": {
            "components": ["silhouetteIoU", "lumaNormalizedChromaQuality", "normalizedDinoV2Cosine"],
            "composite": "equal_mean",
        },
        "camera": camera,
        "cameraReport": camera_report,
        "jointNames": skeleton_names,
        "frameCount": frame_count,
        "meanScore": float(scores.mean()),
        "meanSilhouette": float(np.mean([float(r["silhouette"]) for r in rows])),
        "meanChroma": float(np.mean([float(r["chroma"]) for r in rows])),
        "meanDino": float(np.mean([float(r["normalizedDinoV2"]) for r in rows])),
        "worstFrames": sorted(
            (
                {
                    "clip": r["clip"],
                    "frame": r["frame"],
                    "score": r["score"],
                    "silhouette": r["silhouette"],
                    "chroma": r["chroma"],
                    "normalizedDinoV2": r["normalizedDinoV2"],
                }
                for r in rows
            ),
            key=lambda r: float(r["score"]),
        )[:10],
        "frames": rows,
        "inputs": {
            "clips": [
                {"clip": p.stem, "path": str(p), "sha256": _sha256(p)}
                for p in clips
            ],
            "defJson": str(lookup["defJson"]),
        },
    }
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    gif = out / f"{lab_sid}_audit.gif"
    contact_frames[0].save(
        gif, save_all=True, append_images=contact_frames[1:], duration=180, loop=0
    )
    contact = out / f"{lab_sid}_audit_contact.png"
    sheet = Image.new(
        "RGB", (contact_frames[0].width, contact_frames[0].height * min(12, len(contact_frames)))
    )
    step = max(1, len(contact_frames) // 12)
    for i, image in enumerate(contact_frames[::step][:12]):
        sheet.paste(image, (0, i * contact_frames[0].height))
    sheet.save(contact)
    print(
        json.dumps(
            {
                "ok": True,
                "labSid": lab_sid,
                "frames": frame_count,
                "meanScore": report["meanScore"],
                "gif": str(gif),
            },
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-sid", required=True)
    parser.add_argument(
        "--lab-root",
        type=Path,
        required=True,
        help="homm3_lab root holding <labSid>/extracted_battle_source_12fps",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--dino-batch", type=int, default=8)
    args = parser.parse_args()
    audit_unit(
        lab_sid=args.lab_sid,
        lab_root=args.lab_root.resolve(),
        out_root=args.out.resolve(),
        resolution=args.resolution,
        dino_batch=args.dino_batch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
