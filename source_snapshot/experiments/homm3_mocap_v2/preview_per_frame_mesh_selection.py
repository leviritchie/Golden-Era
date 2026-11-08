#!/usr/bin/env python3
"""Score the move-bind and idle-bind Roc surfaces per source frame.

Both surfaces are replayed through the same captured joint motion. Each rendered
frame is scored against its source sprite using silhouette IoU, luma-normalized
chroma error, and normalized DINOv2 cosine quality. The selected column is a
diagnostic *runtime skinned-mesh swap* preview: it is not a Unity asset or a
delivery claim, and it does not pretend different topologies can be blended.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))

from dino_embed import extract_subject_from_rgba  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from hybrid_dinov2 import DinoEncoder, cosine_quality  # noqa: E402
from reconstruct_ab import compute_rest_joints, reconstruct_ab  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_skin_bundle  # noqa: E402
from run_skin_weight_pilot import shared_canvas_source_images, skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402

DEFAULT_CORPUS = REPO / "artifacts/homm3_mocap_v2/skin_mesh_pilot/captures_v2/corpus.json"
DEFAULT_MOVE_BIND = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_bind/h3_roc_move_bind_t2_capture_f0_bind.glb"
DEFAULT_MOVE_WEIGHTS = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit/candidate_weights.npz"
DEFAULT_MOVE_CAMERA = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit/camera.json"
DEFAULT_IDLE_BIND = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_idle_bind_v1/capture_bind/h3_roc_linked_master_bind.glb"
DEFAULT_IDLE_WEIGHTS = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_idle_bind_v1/skin_fit/candidate_weights.npz"
DEFAULT_IDLE_CAMERA = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_idle_bind_v1/skin_fit/camera.json"
DEFAULT_IDLE_STATIC_REGISTRATION = REPO / "artifacts/homm3_mocap_v2/roc_idle_static_bind_v1/static_bind_registration.json"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_mesh_selection_v1"


def letterbox_rgba(path: Path, resolution: int) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        box = rgba.getbbox()
        if box is None:
            raise ValueError(f"empty sprite: {path}")
        crop = rgba.crop(box)
    scale = min(resolution / crop.width, resolution / crop.height)
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    resized = crop.resize(size, Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 0))
    canvas.paste(resized, ((resolution - size[0]) // 2, (resolution - size[1]) // 2), resized)
    return np.asarray(canvas, dtype=np.uint8)


def load_weights(path: Path, skin: dict[str, Any]) -> np.ndarray:
    raw = np.load(path, allow_pickle=False)
    names = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in np.asarray(raw["names"]).tolist()]
    if names != list(skin["names"]):
        raise ValueError(f"weights joint order does not match {path}")
    weights = np.asarray(raw["weights"], dtype=np.float64)
    if weights.shape != (len(skin["vertices"]), len(skin["names"])):
        raise ValueError(f"weights shape {weights.shape} does not match bind")
    return weights


def permute_positions(capture: dict[str, Any], skin: dict[str, Any], indices: list[int]) -> np.ndarray:
    names = [str(x) for x in capture["joint_names"]]
    order = np.asarray([names.index(name) for name in skin["names"]], dtype=np.int64)
    positions = np.asarray(capture["pred_position"], dtype=np.float64)[np.asarray(indices, dtype=np.int64)][:, order]
    return positions


def canonical_bind_positions(skin: dict[str, Any]) -> np.ndarray:
    """Return the candidate's own bind skeleton in the skin joint order."""
    return compute_rest_joints(skin["offsets"], skin["parents"])[None].astype(np.float64)


def load_idle_bind_view(bind_glb: Path, static_registration: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Undo capture-space bind alignment before applying the registered source view."""
    bind_report_path = bind_glb.with_suffix(".report.json")
    registration = json.loads(static_registration.read_text(encoding="utf-8"))
    bind_report = json.loads(bind_report_path.read_text(encoding="utf-8"))
    expected_mesh = registration.get("inputHashes", {}).get("mesh")
    expected_capture = registration.get("inputHashes", {}).get("capture")
    if expected_mesh and expected_mesh != bind_report.get("meshSha256"):
        raise ValueError("idle static registration mesh hash does not match idle bind provenance")
    if expected_capture and expected_capture != bind_report.get("captureSha256"):
        raise ValueError("idle static registration capture hash does not match idle bind provenance")
    alignment = np.asarray(bind_report.get("surfaceAlignment", {}).get("rotation"), dtype=np.float64)
    if alignment.shape != (3, 3):
        raise ValueError("idle bind report is missing a 3x3 surfaceAlignment.rotation")
    candidates = registration.get("views", {}).get("candidates") or []
    if not candidates:
        raise ValueError("idle static registration has no view candidates")
    candidate = max(candidates, key=lambda item: float(item.get("view", {}).get("iou", -1.0)))
    view_rotation = np.asarray(candidate.get("view", {}).get("rotation"), dtype=np.float64)
    if view_rotation.shape != (3, 3):
        raise ValueError("idle static registration candidate is missing a 3x3 view rotation")
    metadata = {
        "registration": str(static_registration.resolve()).replace("\\", "/"),
        "candidateId": candidate.get("id"),
        "candidateIoU": float(candidate.get("view", {}).get("iou", 0.0)),
        "policy": "registered_source_view_after_inverse_capture_bind_alignment",
    }
    return view_rotation @ alignment.T, metadata


def pose_and_render(skin: dict[str, Any], weights: np.ndarray, positions: np.ndarray, camera: dict[str, Any], resolution: int, world_rotation: np.ndarray | None = None) -> tuple[np.ndarray, list[dict[str, float]]]:
    ab = reconstruct_ab(capture_positions=positions, offsets=skin["offsets"], parents=skin["parents"], reference_frame=0)
    worlds = np.asarray(ab["jointWorldA"], dtype=np.float64)
    if world_rotation is not None:
        rotation = np.eye(4, dtype=np.float64)
        rotation[:3, :3] = np.asarray(world_rotation, dtype=np.float64)
        worlds = rotation[None, None] @ worlds
    with cascade_batch_lock(REPO), torch.no_grad():
        transforms = torch.as_tensor(worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"]))),), dtype=torch.float32, device="cuda")
        candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest)
        posed = skin_with(candidates, torch.as_tensor(weights, dtype=torch.float32, device="cuda"))
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, alpha = renderer.render(posed)
        rgb_np = rgb.detach().cpu().numpy()
        alpha_np = alpha.detach().cpu().numpy()
        posed_np = posed.detach().cpu().numpy()
    health = deformation_health(skin, posed_np)
    rgba = np.zeros((*rgb_np.shape[:3], 4), dtype=np.uint8)
    rgba[..., :3] = np.uint8(np.clip(rgb_np, 0.0, 1.0) * 255.0)
    rgba[..., 3] = np.uint8(np.clip(alpha_np[..., 0], 0.0, 1.0) * 255.0)
    return rgba, health


def deformation_health(skin: dict[str, Any], posed: np.ndarray) -> list[dict[str, float]]:
    """Summarize edge strain so collapsed/fused poses cannot win appearance alone."""
    triangles = np.asarray(skin["triangles"], dtype=np.int64)
    edges = np.unique(np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, ::2]), axis=0), axis=1), axis=0)
    rest = np.asarray(skin["vertices"], dtype=np.float64)
    rest_lengths = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    valid = rest_lengths > 1e-8
    rest_lengths = rest_lengths[valid]
    edges = edges[valid]
    result: list[dict[str, float]] = []
    for frame in np.asarray(posed, dtype=np.float64):
        lengths = np.linalg.norm(frame[edges[:, 0]] - frame[edges[:, 1]], axis=1)
        ratios = lengths / np.maximum(rest_lengths, 1e-8)
        result.append({"edgeRatioQ01": float(np.quantile(ratios, 0.01)), "edgeRatioMedian": float(np.median(ratios)), "edgeRatioQ99": float(np.quantile(ratios, 0.99)), "edgeExtremeFraction": float(np.mean((ratios < 0.35) | (ratios > 2.50)))})
    return result


def deformation_cost(health: dict[str, float]) -> float:
    """Robust strain cost used only to compare the two candidates for one frame."""
    return float(abs(np.log(max(health["edgeRatioQ01"], 1e-9)))
                 + abs(np.log(max(health["edgeRatioQ99"], 1e-9)))
                 + 5.0 * health["edgeExtremeFraction"])


def common_camera(move_camera: dict[str, Any], resolution: int) -> dict[str, Any]:
    """Rescale a saved registration from its actual renderer resolution."""
    required = ("resolution", "scale", "offset", "sourceCrop", "sourceSize")
    missing = [key for key in required if key not in move_camera]
    if missing:
        raise ValueError(f"move camera missing required metadata: {missing}")
    base_resolution = int(move_camera["resolution"])
    if base_resolution < 2:
        raise ValueError(f"invalid move camera resolution: {base_resolution}")
    factor = float(resolution) / float(base_resolution)
    camera = dict(move_camera)
    camera["scale"] = float(move_camera["scale"]) * factor
    camera["pxPerWorld"] = camera["scale"]
    camera["offset"] = [float(value) * factor for value in move_camera["offset"]]
    camera["screenOffsetPx"] = list(camera["offset"])
    camera["resolution"] = resolution
    camera["framingPolicy"] = "saved_registration_rescaled_to_requested_output"
    return camera


def basis_rotation(source_camera: dict[str, Any], target_camera: dict[str, Any]) -> np.ndarray:
    source = np.stack((np.asarray(source_camera["right"]), np.asarray(source_camera["down"]), np.asarray(source_camera["forward"])), axis=0)
    target = np.stack((np.asarray(target_camera["right"]), np.asarray(target_camera["down"]), np.asarray(target_camera["forward"])), axis=0)
    return target.T @ source


def wing_span_torso_ratio(rgba: np.ndarray) -> float:
    mask = rgba[..., 3] > 24
    ys, xs = np.where(mask)
    if len(xs) < 8:
        return 0.0
    span = float(xs.max() - xs.min() + 1)
    center = float(np.median(xs))
    y0, y1 = float(ys.min()), float(ys.max())
    band = mask & (np.indices(mask.shape)[0] >= y0 + 0.25 * (y1 - y0)) & (np.indices(mask.shape)[0] <= y0 + 0.75 * (y1 - y0))
    widths = []
    for row in np.flatnonzero(band.any(axis=1)):
        row_x = np.flatnonzero(band[row])
        row_x = row_x[np.abs(row_x - center) <= 0.35 * span]
        if len(row_x) >= 2:
            widths.append(float(row_x[-1] - row_x[0] + 1))
    torso = float(np.median(widths)) if widths else span
    return span / max(torso, 1.0)


def projected_bbox_aspect(rgba: np.ndarray) -> float:
    mask = rgba[..., 3] > 24
    ys, xs = np.where(mask)
    if len(xs) < 8:
        return 0.0
    return float((ys.max() - ys.min() + 1) / max(xs.max() - xs.min() + 1, 1))


def anatomy_visibility_compatibility(source: np.ndarray, mesh: np.ndarray) -> dict[str, Any]:
    """Reject compact candidates that turn visible body landmarks into a wing shell.

    This is deliberately a low-cost image-space guard, not a detector claiming to
    understand anatomy. It only runs for upright source silhouettes and compares
    alpha support in source-derived head, breast, and feet regions. A candidate
    must retain enough support without filling those regions with a much larger
    wing mass. Horizontal attack/death silhouettes are left to the other gates.
    """
    source_mask = source[..., 3] > 24
    mesh_mask = mesh[..., 3] > 24
    ys, xs = np.where(source_mask)
    if len(xs) < 8:
        return {"applicable": False, "compatibility": True, "landmarkRatios": {}}
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    span = max(1, x1 - x0)
    height = max(1, y1 - y0)
    if height / span < 1.15:
        return {"applicable": False, "compatibility": True, "landmarkRatios": {}}

    row_grid = np.indices(source_mask.shape)[0]
    col_grid = np.indices(source_mask.shape)[1]
    def region(y_start: float, y_end: float, x_center: float, x_half: float) -> np.ndarray:
        return ((row_grid >= y0 + y_start * height) & (row_grid < y0 + y_end * height)
                & (col_grid >= x_center - x_half) & (col_grid <= x_center + x_half))

    head_band = source_mask & (row_grid >= y0) & (row_grid < y0 + 0.30 * height)
    feet_band = source_mask & (row_grid >= y0 + 0.80 * height) & (row_grid < y1)
    head_x = float(np.median(np.where(head_band)[1])) if head_band.any() else float((x0 + x1) / 2)
    feet_x = float(np.median(np.where(feet_band)[1])) if feet_band.any() else float((x0 + x1) / 2)
    regions = {
        "head": region(0.00, 0.30, head_x, max(6.0, 0.16 * span)),
        "breast": region(0.30, 0.72, (x0 + x1) / 2, max(7.0, 0.24 * span)),
        "feet": region(0.80, 1.00, feet_x, max(6.0, 0.18 * span)),
    }
    ratios: dict[str, float] = {}
    for name, mask in regions.items():
        source_count = int((source_mask & mask).sum())
        if source_count < max(3, int(0.002 * source_mask.size)):
            continue
        candidate_count = int((mesh_mask & mask).sum())
        ratios[name] = float(candidate_count / source_count)
    compatible = all(0.35 <= value <= 2.50 for value in ratios.values())
    return {"applicable": True, "compatibility": compatible, "landmarkRatios": ratios}


def frame_metrics(source: np.ndarray, mesh: np.ndarray, source_embedding: np.ndarray, mesh_embedding: np.ndarray, source_ratio: float, health: dict[str, float]) -> dict[str, Any]:
    sa = source[..., 3].astype(np.float64) / 255.0
    ma = mesh[..., 3].astype(np.float64) / 255.0
    inter = float((sa * ma).sum())
    union = float((sa + ma - sa * ma).sum())
    silhouette = inter / max(union, 1e-9)
    sr = source[..., :3].astype(np.float64) / 255.0
    mr = mesh[..., :3].astype(np.float64) / 255.0
    sl = (sr * np.asarray((0.299, 0.587, 0.114))).sum(-1, keepdims=True)
    ml = (mr * np.asarray((0.299, 0.587, 0.114))).sum(-1, keepdims=True)
    chroma_delta = np.abs(sr / np.maximum(sl, 1e-3) - mr / np.maximum(ml, 1e-3))
    overlap = sa * ma + 0.05 * sa
    chroma = float((chroma_delta * overlap[..., None]).sum() / max(overlap.sum() * 3.0, 1e-9))
    chroma_quality = float(np.clip(1.0 - chroma, 0.0, 1.0))
    dino = cosine_quality(source_embedding, mesh_embedding)
    composite = float((silhouette + chroma_quality + dino) / 3.0)
    anatomy = anatomy_visibility_compatibility(source, mesh)
    return {"silhouette": float(silhouette), "chroma": chroma_quality, "normalizedDinoV2": float(dino), "score": composite, "wingSpanTorsoRatio": wing_span_torso_ratio(mesh), "sourceWingSpanTorsoRatio": float(source_ratio), "projectedBBoxAspect": projected_bbox_aspect(mesh), "sourceProjectedBBoxAspect": projected_bbox_aspect(source), "anatomyVisibility": anatomy, "deformationHealth": health}


def encode_subjects(encoder: DinoEncoder, images: list[np.ndarray], window: dict[str, Any], batch: int = 8) -> np.ndarray:
    subjects = [extract_subject_from_rgba(image, window) for image in images]
    # DINO and raster work share one GPU; keep the cascade lock around both.
    with cascade_batch_lock(REPO), torch.no_grad():
        chunks = [encoder.encode_rgb(subjects[i : i + batch]) for i in range(0, len(subjects), batch)]
    return np.concatenate(chunks, axis=0)


def clip_window(images: list[np.ndarray], resolution: int) -> dict[str, Any]:
    alpha = np.stack([image[..., 3] for image in images], axis=0)
    rows, cols = np.where(np.any(alpha > 0, axis=0))
    if len(rows) == 0:
        raise ValueError("source clip has no alpha")
    return {"policy": "clip_locked_union_alpha_aabb", "paddingRatio": 0.1, "bg": [1.0, 1.0, 1.0], "bboxXyxy": [int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1], "canvas": [resolution, resolution]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--move-bind", type=Path, default=DEFAULT_MOVE_BIND)
    parser.add_argument("--move-weights", type=Path, default=DEFAULT_MOVE_WEIGHTS)
    parser.add_argument("--move-camera", type=Path, default=DEFAULT_MOVE_CAMERA)
    parser.add_argument("--idle-bind", type=Path, default=DEFAULT_IDLE_BIND)
    parser.add_argument("--idle-weights", type=Path, default=DEFAULT_IDLE_WEIGHTS)
    parser.add_argument("--idle-camera", type=Path, default=DEFAULT_IDLE_CAMERA)
    parser.add_argument("--idle-static-registration", type=Path, default=DEFAULT_IDLE_STATIC_REGISTRATION)
    parser.add_argument("--strict-gates", action="store_true", help="leave a frame unresolved when neither candidate passes every gate")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--dino-batch", type=int, default=8)
    parser.add_argument("--idle-extra-yaw-deg", type=float, default=0.0, help="optional additional world-Y correction after registered idle view")
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    entries = {str(item["key"]): item for item in corpus["captures"]}
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    move_skin = load_skin_bundle(args.move_bind.resolve()); move_skin["weights"] = load_weights(args.move_weights.resolve(), move_skin)
    idle_skin = load_skin_bundle(args.idle_bind.resolve()); idle_skin["weights"] = load_weights(args.idle_weights.resolve(), idle_skin)
    move_camera = json.loads(args.move_camera.read_text(encoding="utf-8")); idle_camera = json.loads(args.idle_camera.read_text(encoding="utf-8"))
    camera = common_camera(move_camera, args.resolution)
    idle_to_move, idle_orientation_metadata = load_idle_bind_view(args.idle_bind.resolve(), args.idle_static_registration.resolve())
    if abs(float(args.idle_extra_yaw_deg)) > 1e-9:
        yaw = math.radians(float(args.idle_extra_yaw_deg))
        yaw_rotation = np.asarray(((math.cos(yaw), 0.0, math.sin(yaw)), (0.0, 1.0, 0.0), (-math.sin(yaw), 0.0, math.cos(yaw))), dtype=np.float64)
        idle_to_move = yaw_rotation @ idle_to_move
        idle_orientation_metadata = dict(idle_orientation_metadata)
        idle_orientation_metadata["additionalYawDeg"] = float(args.idle_extra_yaw_deg)
    encoder = DinoEncoder("cuda")
    rows: list[dict[str, Any]] = []
    max_motion_delta = 0.0
    ratio_gate = 0.25
    deformation_margin = 1.05
    gif_frames: list[Image.Image] = []
    for key, entry in entries.items():
        indices = [int(i) for i in entry["sourceIndices"]]
        source_paths = [Path(p) for p in entry["frames"]]
        source_targets, _, _ = shared_canvas_source_images(source_paths, args.resolution)
        source_rgb = source_targets[0].detach().cpu().numpy()
        source_alpha = source_targets[1].detach().cpu().numpy()
        sources = np.zeros((*source_rgb.shape[:3], 4), dtype=np.uint8)
        sources[..., :3] = np.uint8(np.clip(source_rgb, 0.0, 1.0) * 255.0)
        sources[..., 3] = np.uint8(np.clip(source_alpha[..., 0], 0.0, 1.0) * 255.0)
        window = clip_window(sources, args.resolution)
        source_embeddings = encode_subjects(encoder, sources, window, args.dino_batch)
        capture = np.load(Path(entry["capture"]), allow_pickle=False)
        capture_dict = {name: capture[name] for name in capture.files}
        move_positions = permute_positions(capture_dict, move_skin, indices)
        idle_positions = permute_positions(capture_dict, idle_skin, indices)
        if move_positions.shape != idle_positions.shape:
            raise ValueError(f"candidate joint position shapes differ for {key}: {move_positions.shape} vs {idle_positions.shape}")
        motion_delta = float(np.max(np.abs(move_positions - idle_positions)))
        max_motion_delta = max(max_motion_delta, motion_delta)
        if motion_delta > 1e-8:
            raise ValueError(f"candidate joint position parity failed for {key}: max delta {motion_delta:.3e}")
        # The corpus has eight context frames before g02_idle. Its first
        # source frame therefore arrives as capture index 8, not the linked
        # master's canonical bind frame. Render idle frame 00 from each
        # candidate's own bind skeleton, then reconstruct the rest of the clip
        # relative to that identity pose. Do not alter the shared capture
        # arrays used for motion-parity validation above.
        canonical_bind_override = key == "g02_idle" and bool(move_positions.shape[0])
        move_render_positions = move_positions.copy()
        idle_render_positions = idle_positions.copy()
        if canonical_bind_override:
            move_render_positions[0] = canonical_bind_positions(move_skin)[0]
            idle_render_positions[0] = canonical_bind_positions(idle_skin)[0]
        move_rgba, move_health = pose_and_render(move_skin, move_skin["weights"], move_render_positions, camera, args.resolution)
        idle_rgba, idle_health = pose_and_render(idle_skin, idle_skin["weights"], idle_render_positions, camera, args.resolution, idle_to_move)
        move_embeddings = encode_subjects(encoder, list(move_rgba), window, args.dino_batch)
        idle_embeddings = encode_subjects(encoder, list(idle_rgba), window, args.dino_batch)
        for frame, (source, move, idle) in enumerate(zip(sources, move_rgba, idle_rgba)):
            source_ratio = wing_span_torso_ratio(source)
            move_score = frame_metrics(source, move, source_embeddings[frame], move_embeddings[frame], source_ratio, move_health[frame])
            idle_score = frame_metrics(source, idle, source_embeddings[frame], idle_embeddings[frame], source_ratio, idle_health[frame])
            for candidate in (move_score, idle_score):
                relative_error = abs(candidate["wingSpanTorsoRatio"] - source_ratio) / max(source_ratio, 1e-9)
                candidate["shapeRatioRelativeError"] = float(relative_error)
                candidate["shapeCompatibility"] = bool(relative_error <= ratio_gate)
                aspect_error = abs(candidate["projectedBBoxAspect"] - candidate["sourceProjectedBBoxAspect"]) / max(candidate["sourceProjectedBBoxAspect"], 1e-9)
                candidate["bboxAspectRelativeError"] = float(aspect_error)
                candidate["bboxAspectCompatibility"] = bool(aspect_error <= 0.50)
                candidate["anatomyCompatibility"] = bool(candidate["anatomyVisibility"]["compatibility"])
                candidate["deformationCost"] = deformation_cost(candidate["deformationHealth"])
                candidate["deformationCompatibility"] = bool(candidate["deformationHealth"]["edgeRatioQ01"] >= 0.30 and candidate["deformationHealth"]["edgeRatioQ99"] <= 5.00 and candidate["deformationHealth"]["edgeExtremeFraction"] <= 0.08)
            minimum_cost = min(move_score["deformationCost"], idle_score["deformationCost"])
            for candidate in (move_score, idle_score):
                # Near identity both candidates can have only floating-point
                # edge noise. Do not turn that noise into a 25% relative-cost
                # penalty by dividing two values close to zero.
                if minimum_cost < 1e-3:
                    relative_cost = 1.0
                else:
                    relative_cost = candidate["deformationCost"] / minimum_cost
                candidate["relativeDeformationCost"] = float(relative_cost)
                candidate["deformationCompatibility"] = bool(candidate["deformationCompatibility"] and candidate["relativeDeformationCost"] <= deformation_margin)
                candidate["eligible"] = bool(candidate["shapeCompatibility"] and candidate["bboxAspectCompatibility"] and candidate["anatomyCompatibility"] and candidate["deformationCompatibility"])
            eligible = [("move", move_score), ("idle", idle_score)]
            eligible = [(name, score) for name, score in eligible if score["eligible"]]
            selection_gate_override = False
            if eligible:
                winner = max(eligible, key=lambda item: (item[1]["score"], item[0] == "move"))[0]
                selected = move if winner == "move" else idle
            else:
                if args.strict_gates:
                    winner = "unresolved"
                    selected = np.zeros_like(source)
                else:
                    winner = max((("move", move_score), ("idle", idle_score)), key=lambda item: (item[1]["score"], item[0] == "move"))[0]
                    selected = move if winner == "move" else idle
                    selection_gate_override = True
            item = {"clip": key, "frame": frame, "sourceIndex": indices[frame], "canonicalBindOverride": bool(canonical_bind_override and frame == 0), "selectionGateOverride": selection_gate_override, "winner": winner, "move": move_score, "idle": idle_score}
            rows.append(item)
            row = Image.new("RGB", (args.resolution * 4, args.resolution + 30), (10, 10, 14)); draw = ImageDraw.Draw(row)
            override_mark = "*" if selection_gate_override else ""
            draw.text((4, 5), f"{key} f{frame:02d} winner={winner}{override_mark}", fill="white")
            move_mark = "" if move_score["eligible"] else " X"
            idle_mark = "" if idle_score["eligible"] else " X"
            for col, label, image in ((0, "source", source), (1, f"move {move_score['score']:.3f}{move_mark}", move), (2, f"idle {idle_score['score']:.3f}{idle_mark}", idle), (3, f"selected {winner}{override_mark}", selected)):
                rgb = image[..., :3].astype(np.float32) / 255.0
                row.paste(Image.fromarray(np.uint8(rgb * 255.0)), (col * args.resolution, 30)); draw.text((col * args.resolution + 4, 17), label, fill=(190, 190, 205))
            gif_frames.append(row)
    gif = out / "roc_per_frame_mesh_selection.gif"
    gif_frames[0].save(gif, save_all=True, append_images=gif_frames[1:], duration=85, loop=0)
    contact = out / "roc_per_frame_mesh_selection_contact.png"; contact_img = Image.new("RGB", (gif_frames[0].width, gif_frames[0].height * min(12, len(gif_frames))))
    step = max(1, len(gif_frames) // 12)
    for i, image in enumerate(gif_frames[::step][:12]): contact_img.paste(image, (0, i * gif_frames[0].height))
    contact_img.save(contact)
    unique_captures = sorted({str(Path(entry["capture"]).resolve()) for entry in entries.values()})
    unique_sources = sorted({str(Path(frame).resolve()) for entry in entries.values() for frame in entry["frames"]})
    def sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    input_paths = [args.corpus.resolve(), args.move_bind.resolve(), args.move_weights.resolve(), args.move_camera.resolve(), args.idle_bind.resolve(), args.idle_weights.resolve(), args.idle_camera.resolve(), args.idle_static_registration.resolve(), args.idle_bind.resolve().with_suffix(".report.json"), *map(Path, unique_captures), *map(Path, unique_sources)]
    report = {"proof": "generated-candidate visual preview; per-frame runtime skinned-mesh swap hypothesis; not Unity delivery", "selectionPolicy": "best_score_even_if_gated" if not args.strict_gates else "strict_all_gates", "scoring": {"components": ["silhouetteIoU", "lumaNormalizedChromaQuality", "normalizedDinoV2Cosine"], "composite": "equal_mean", "dinoModel": "facebook/dinov2-large", "windowPolicy": "clip_locked_union_alpha_aabb", "shapeCompatibilityGate": {"metric": "wingSpanTorsoRatio", "maxRelativeError": ratio_gate, "ineligiblePolicy": "unresolved"}, "bboxAspectCompatibilityGate": {"metric": "projectedBBoxHeightWidthRatio", "maxRelativeError": 0.50, "ineligiblePolicy": "unresolved"}, "anatomyVisibilityGate": {"metric": "sourceDerivedHeadBreastFeetAlphaSupport", "uprightAspectMinimum": 1.15, "candidateToSourceRatioRange": [0.35, 2.50], "ineligiblePolicy": "unresolved", "interpretation": "regional occupancy compatibility heuristic; not landmark-occlusion proof"}, "deformationHealthGate": {"metric": "posedToBindEdgeLengthRatio", "q01Minimum": 0.30, "q99Maximum": 5.00, "extremeFractionMaximum": 0.08, "relativeCostMargin": deformation_margin, "relativeCostFloor": 1e-3, "ineligiblePolicy": "unresolved"}}, "meshCandidates": {"move": str(args.move_bind.resolve()), "idle": str(args.idle_bind.resolve())}, "cameraPolicy": "move_registration_rescaled_from_saved_output_resolution", "idleOrientationTransfer": idle_orientation_metadata, "idleExtraYawDeg": float(args.idle_extra_yaw_deg), "motionParity": {"positionOrder": "candidate-joint-name permutation", "maxAbsDelta": max_motion_delta, "referenceFramePolicy": "g02_idle frame 00 canonical bind rest; later frames reconstructed from that identity pose"}, "canonicalBindOverrides": {"g02_idle": "frame 00 rendered from each candidate bind skeleton; corpus context frame 8 is not used as replay reference"}, "inputHashes": {str(path): sha256(str(path)) for path in input_paths}, "frameCount": len(rows), "winnerCounts": {name: sum(row["winner"] == name for row in rows) for name in ("move", "idle", "unresolved")}, "frames": rows, "gif": str(gif), "contact": str(contact)}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "frameCount": len(rows), "winnerCounts": report["winnerCounts"], "gif": str(gif), "contact": str(contact)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
