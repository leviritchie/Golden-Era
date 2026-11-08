#!/usr/bin/env python3
"""Diagnostic animation preview for the Behemoth idle-frame T2 Smart Rig.

Capture positions are retargeted into the actual target bind basis before
named local deltas are applied.  The fitted target bind is explicit; corpus
clips are context windows and their first displayed frame is not assumed to be
that bind.  A bad result can therefore be attributed to the generated mesh,
rig, or motion correspondence rather than an invented T-pose.
"""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))

from asset_profiles import get_profile  # noqa: E402
from eagle_glb import load_bind_skeleton, write_skinned_glb  # noqa: E402
from glb_skeleton import read_glb  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from run_skin_weight_pilot import source_images  # noqa: E402
from skin_camera_registration import _basis_yup, _bbox_scale_offset, _camera, _target_bbox  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from run_roc_move_bind_t2_mocap import load_glb_surface, nearest_bone_weights  # noqa: E402
from direction_retarget import retarget_clip, transport_bind_deltas  # noqa: E402
from mocap_skin_solver import (capsule_bone_weights, dual_quaternion_skin,
                               fit_rest_skeleton_to_surface, local_offsets_from_world,
                               optimize_mocap_weights, optimize_sequence_weights_3d,
                               pose_corrective_residuals_3d,
                               region_capsule_weights, region_capsule_weights_3d,
                               rest_world_from_offsets, sparsify_weights,
                               transfer_weights_from_donor, validate_weights)  # noqa: E402

SOURCE_NAMES = {
    "Hips": "mixamorig:Hips", "Spine": "mixamorig:Spine", "Spine01": "mixamorig:Spine1",
    "Spine02": "mixamorig:Spine2", "neck": "mixamorig:Neck", "Head": "mixamorig:Head",
    "head_end": "mixamorig:HeadTop_End", "LeftShoulder": "mixamorig:LeftShoulder",
    "LeftArm": "mixamorig:LeftArm", "LeftForeArm": "mixamorig:LeftForeArm", "LeftHand": "mixamorig:LeftHand",
    "RightShoulder": "mixamorig:RightShoulder", "RightArm": "mixamorig:RightArm",
    "RightForeArm": "mixamorig:RightForeArm", "RightHand": "mixamorig:RightHand",
    "LeftUpLeg": "mixamorig:LeftUpLeg", "LeftLeg": "mixamorig:LeftLeg", "LeftFoot": "mixamorig:LeftFoot",
    "LeftToeBase": "mixamorig:LeftToeBase", "RightUpLeg": "mixamorig:RightUpLeg",
    "RightLeg": "mixamorig:RightLeg", "RightFoot": "mixamorig:RightFoot", "RightToeBase": "mixamorig:RightToeBase",
}


def dense_weights(skeleton) -> np.ndarray:
    if hasattr(skeleton, "mocap_weights"):
        return skeleton.mocap_weights
    if not hasattr(skeleton, "vertex_joints"):
        bind_world = np.linalg.inv(np.asarray(skeleton.inverse_bind, dtype=np.float64))
        return nearest_bone_weights(skeleton.vertices, bind_world[:, :3, 3], k=4)
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int64)
    sparse = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    dense = np.zeros((len(skeleton.vertices), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        valid = sparse[:, slot] > 1e-8
        dense[np.arange(len(dense))[valid], joints[valid, slot]] += sparse[valid, slot]
    dense /= np.maximum(dense.sum(axis=1, keepdims=True), 1e-12)
    return dense


def render(vertices, weights, worlds, inverse_bind, triangles, uvs, albedo, camera, correction=None, *, return_alpha=False):
    with cascade_batch_lock(REPO), torch.no_grad():
        transforms = torch.as_tensor(worlds @ inverse_bind[None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(np.column_stack((vertices, np.ones(len(vertices)))), dtype=torch.float32, device="cuda")
        dense = torch.as_tensor(weights, dtype=torch.float32, device="cuda")
        if getattr(render, "skin_mode", "dqs") == "dqs":
            posed = dual_quaternion_skin(rest[:, :3], dense, transforms)
        else:
            candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest)
            posed = torch.einsum("vj,fvjk->fvk", dense, candidates)
        if correction is not None:
            posed = posed + torch.as_tensor(correction, dtype=posed.dtype, device=posed.device)
        rgb, alpha = SkinImageRenderer(
            triangles, uvs, albedo, camera, int(camera.get("resolution", 224))
        ).render(posed)
        rgb_np = rgb.detach().cpu().numpy()
        if return_alpha:
            return rgb_np, alpha.detach().cpu().numpy()
        return rgb_np


def rest_local_matrices(bind_world: np.ndarray, parents: np.ndarray) -> np.ndarray:
    local = np.zeros_like(bind_world)
    for index, parent in enumerate(parents):
        local[index] = bind_world[index] if int(parent) < 0 else np.linalg.inv(bind_world[int(parent)]) @ bind_world[index]
    return local


def apply_local_deltas(rest_local: np.ndarray, parents: np.ndarray, deltas: np.ndarray) -> np.ndarray:
    local = np.repeat(rest_local[None], len(deltas), axis=0)
    local[:, :, :3, :3] = rest_local[None, :, :3, :3] @ deltas
    worlds = np.zeros_like(local)
    for index, parent in enumerate(parents):
        worlds[:, index] = local[:, index] if int(parent) < 0 else worlds[:, int(parent)] @ local[:, index]
    return worlds


def bind_relative_local_deltas(current: np.ndarray, anchor: np.ndarray) -> np.ndarray:
    """Return local deltas that move an anchor pose to each current pose.

    Local transforms compose on the right in ``parent_world @ local`` FK, so
    the delta solves ``anchor * delta = current`` and is therefore
    ``anchor.T * current``.  Reversing that order is a subtle but visible
    multi-axis bug: the mesh remains numerically mobile while limbs lose their
    intended articulation.
    """
    current = np.asarray(current, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64)
    if current.ndim != 4 or current.shape[-2:] != (3, 3) or anchor.shape != current.shape[1:]:
        raise ValueError("current/anchor local rotations have incompatible shapes")
    if not np.isfinite(current).all() or not np.isfinite(anchor).all():
        raise ValueError("current/anchor local rotations must be finite")
    return np.swapaxes(anchor, -1, -2)[None] @ current


def _arm_exchange_pairs(names: list[str]) -> list[tuple[int, int]]:
    """Return left/right arm joint pairs present in a target skeleton."""
    by_name = {str(name).lower(): index for index, name in enumerate(names)}
    pairs: list[tuple[int, int]] = []
    for left_name, right_name in (
        ("mixamorig:leftshoulder", "mixamorig:rightshoulder"),
        ("mixamorig:leftarm", "mixamorig:rightarm"),
        ("mixamorig:leftforearm", "mixamorig:rightforearm"),
        ("mixamorig:lefthand", "mixamorig:righthand"),
    ):
        left_index, right_index = by_name.get(left_name), by_name.get(right_name)
        if left_index is not None and right_index is not None:
            pairs.append((left_index, right_index))
    return pairs


def _exchange_arm_motion(current_target: np.ndarray, names: list[str]) -> np.ndarray:
    """Exchange symmetric arm motion without changing the target skeleton."""
    exchanged_target = np.asarray(current_target, dtype=np.float64).copy()
    for left_index, right_index in _arm_exchange_pairs(names):
        exchanged = exchanged_target[:, left_index].copy()
        exchanged_target[:, left_index] = exchanged_target[:, right_index]
        exchanged_target[:, right_index] = exchanged
    return exchanged_target


def _silhouette_compactness(alpha: np.ndarray, *, threshold: float = 0.15) -> np.ndarray:
    """Return per-frame boundary length normalized by occupied area.

    This is a deliberately secondary image diagnostic.  Narrow spikes and
    ragged detached edges increase boundary length even when IoU changes only
    slightly, so the quality gate can reject a visually noisier deformation.
    """
    values = np.asarray(alpha, dtype=np.float64)
    if values.ndim != 3:
        raise ValueError("silhouette compactness expects [F,H,W] alpha")
    mask = values >= float(threshold)
    horizontal = np.count_nonzero(mask[:, :, 1:] != mask[:, :, :-1], axis=(1, 2))
    vertical = np.count_nonzero(mask[:, 1:, :] != mask[:, :-1, :], axis=(1, 2))
    perimeter = horizontal + vertical
    area = np.count_nonzero(mask, axis=(1, 2))
    return perimeter / np.maximum(np.sqrt(area), 1.0)


def _sequence_surface_strain(
    vertices: np.ndarray,
    triangles: np.ndarray,
    weights: np.ndarray,
    inverse_bind: np.ndarray,
    frame_groups: list[np.ndarray],
) -> dict[str, float]:
    """Score a candidate correspondence with camera-free surface ARAP terms."""
    faces = np.asarray(triangles, dtype=np.int64)
    edges = np.unique(
        np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]]), axis=0), axis=1),
        axis=0,
    )
    if len(edges) > 12000:
        edges = edges[np.linspace(0, len(edges) - 1, 12000, dtype=np.int64)]
    rest_edges = np.asarray(vertices, dtype=np.float64)[edges[:, 1]] - np.asarray(vertices, dtype=np.float64)[edges[:, 0]]
    rest_lengths = np.linalg.norm(rest_edges, axis=-1)
    valid_edges = rest_lengths > 1e-8
    edges, rest_lengths = edges[valid_edges], rest_lengths[valid_edges]
    all_worlds = np.concatenate([worlds for _, worlds in frame_groups], axis=0)
    transforms = torch.as_tensor(all_worlds @ np.asarray(inverse_bind)[None], dtype=torch.float32, device="cuda")
    with torch.no_grad():
        posed = dual_quaternion_skin(
            torch.as_tensor(vertices, dtype=torch.float32, device="cuda"),
            torch.as_tensor(weights, dtype=torch.float32, device="cuda"),
            transforms,
        ).detach().cpu().numpy()
    posed_edges = posed[:, edges[:, 1]] - posed[:, edges[:, 0]]
    lengths = np.linalg.norm(posed_edges, axis=-1)
    log_length_error = np.log(np.maximum(lengths, 1e-6) / rest_lengths[None])
    tri_ids = np.arange(len(faces), dtype=np.int64)
    if len(tri_ids) > 4000:
        tri_ids = tri_ids[np.linspace(0, len(tri_ids) - 1, 4000, dtype=np.int64)]
    tri = faces[tri_ids]
    rest_cross = np.cross(np.asarray(vertices)[tri[:, 1]] - np.asarray(vertices)[tri[:, 0]],
                          np.asarray(vertices)[tri[:, 2]] - np.asarray(vertices)[tri[:, 0]])
    rest_area = np.linalg.norm(rest_cross, axis=-1)
    valid_tri = rest_area > 1e-8
    tri, rest_area = tri[valid_tri], rest_area[valid_tri]
    posed_a = posed[:, tri[:, 1]] - posed[:, tri[:, 0]]
    posed_b = posed[:, tri[:, 2]] - posed[:, tri[:, 0]]
    area = np.linalg.norm(np.cross(posed_a, posed_b), axis=-1)
    log_area_error = np.log(np.maximum(area, 1e-6) / rest_area[None])
    return {
        "edgeLogLengthMse": float(np.mean(log_length_error ** 2)),
        "edgeLogLengthP95": float(np.quantile(np.abs(log_length_error), 0.95)),
        "triangleLogAreaMse": float(np.mean(log_area_error ** 2)),
        "total": float(np.mean(log_length_error ** 2) + 0.25 * np.mean(log_area_error ** 2)),
    }


def _sequence_topology_metrics(
    vertices: np.ndarray,
    triangles: np.ndarray,
    posed: np.ndarray,
) -> dict[str, float]:
    """Report worst-case topology deformation without a camera or image loss.

    These are promotion guards, not a quality score.  A low ARAP objective can
    still be purchased by collapsing a limb or stretching a narrow bridge, so
    the gate needs explicit per-triangle and per-edge failure fractions.
    """
    rest = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    sequence = np.asarray(posed, dtype=np.float64)
    if rest.ndim != 2 or rest.shape[1] != 3 or sequence.ndim != 3 or sequence.shape[1:] != rest.shape:
        raise ValueError("topology metrics require rest [V,3] and posed [F,V,3]")
    tri = faces[:, :3]
    rest_cross = np.cross(rest[tri[:, 1]] - rest[tri[:, 0]], rest[tri[:, 2]] - rest[tri[:, 0]])
    rest_area = np.linalg.norm(rest_cross, axis=1)
    valid_tri = rest_area > max(float(np.median(rest_area)) * 1e-8, 1e-12)
    if not np.any(valid_tri):
        raise ValueError("topology metrics require a nondegenerate triangle")
    tri = tri[valid_tri]
    rest_area = rest_area[valid_tri]
    posed_a = sequence[:, tri[:, 1]] - sequence[:, tri[:, 0]]
    posed_b = sequence[:, tri[:, 2]] - sequence[:, tri[:, 0]]
    posed_area = np.linalg.norm(np.cross(posed_a, posed_b), axis=-1)
    area_ratio = posed_area / np.maximum(rest_area[None], 1e-12)
    edges = np.unique(
        np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]]), axis=0), axis=1),
        axis=0,
    )
    if len(edges) > 16000:
        edges = edges[np.linspace(0, len(edges) - 1, 16000, dtype=np.int64)]
    rest_edge = np.linalg.norm(rest[edges[:, 1]] - rest[edges[:, 0]], axis=1)
    valid_edge = rest_edge > 1e-8
    edges, rest_edge = edges[valid_edge], rest_edge[valid_edge]
    posed_edge = np.linalg.norm(sequence[:, edges[:, 1]] - sequence[:, edges[:, 0]], axis=-1)
    edge_ratio = posed_edge / np.maximum(rest_edge[None], 1e-12)
    return {
        "triangleCount": float(len(rest_area)),
        "edgeCount": float(len(rest_edge)),
        "triangleAreaRatioP01": float(np.quantile(area_ratio, 0.01)),
        "triangleAreaRatioP99": float(np.quantile(area_ratio, 0.99)),
        "triangleCollapseFraction": float(np.mean(area_ratio < 0.25)),
        "triangleSevereCollapseFraction": float(np.mean(area_ratio < 0.10)),
        "edgeLengthRatioP01": float(np.quantile(edge_ratio, 0.01)),
        "edgeLengthRatioP99": float(np.quantile(edge_ratio, 0.99)),
        "edgeStretchFraction": float(np.mean((edge_ratio < 0.57) | (edge_ratio > 1.75))),
    }


def _sequence_motion_retention(
    vertices: np.ndarray,
    weights_before: np.ndarray,
    weights_after: np.ndarray,
    inverse_bind: np.ndarray,
    frame_groups: list[tuple[str, np.ndarray]],
    *,
    floor: float,
) -> dict[str, object]:
    """Measure per-clip motion energy retained by a weight refinement.

    Energy is computed after subtracting each clip's temporal centroid, so a
    uniform root translation cannot masquerade as articulated motion. This is
    a diagnostic guard against the common ARAP failure mode where a low surface
    strain is purchased by attaching moving geometry to a stationary hub.
    """
    def _energy(weights: np.ndarray, worlds: np.ndarray) -> np.ndarray:
        transforms = torch.as_tensor(
            worlds @ np.asarray(inverse_bind)[None], dtype=torch.float32, device="cuda"
        )
        with torch.no_grad():
            posed = dual_quaternion_skin(
                torch.as_tensor(vertices, dtype=torch.float32, device="cuda"),
                torch.as_tensor(weights, dtype=torch.float32, device="cuda"),
                transforms,
            ).detach().cpu().numpy()
        centered = posed - posed.mean(axis=0, keepdims=True)
        return np.mean(np.sum(centered * centered, axis=-1), axis=0)

    clips: dict[str, dict[str, float]] = {}
    all_before: list[np.ndarray] = []
    all_after: list[np.ndarray] = []
    for key, worlds in frame_groups:
        before = _energy(weights_before, worlds)
        after = _energy(weights_after, worlds)
        active = before > 1e-8
        ratio = after[active] / np.maximum(before[active], 1e-8)
        clips[key] = {
            "frames": float(len(worlds)),
            "activeVertices": float(active.sum()),
            "meanRatio": float(np.mean(ratio)) if len(ratio) else 1.0,
            "p05Ratio": float(np.quantile(ratio, 0.05)) if len(ratio) else 1.0,
            "belowFloorFraction": float(np.mean(ratio < float(floor))) if len(ratio) else 0.0,
        }
        all_before.append(before)
        all_after.append(after)
    before_pool = np.concatenate(all_before)
    after_pool = np.concatenate(all_after)
    active_pool = before_pool > 1e-8
    ratio_pool = after_pool[active_pool] / np.maximum(before_pool[active_pool], 1e-8)
    return {
        "floor": float(floor),
        "clips": clips,
        "pooled": {
            "activeVertices": float(active_pool.sum()),
            "meanRatio": float(np.mean(ratio_pool)) if len(ratio_pool) else 1.0,
            "p05Ratio": float(np.quantile(ratio_pool, 0.05)) if len(ratio_pool) else 1.0,
            "belowFloorFraction": float(np.mean(ratio_pool < float(floor))) if len(ratio_pool) else 0.0,
        },
    }


def _segment_surface_regions(
    vertices: np.ndarray,
    bind_world: np.ndarray,
    parents: np.ndarray,
    *,
    min_vertices: int = 12,
) -> dict[int, np.ndarray]:
    """Assign bind-surface vertices to the nearest anatomical bone segment.

    Region assignment is deliberately geometric and performed before any
    candidate weight optimization.  It therefore cannot be gamed by moving
    weights between neighboring joints, unlike a dominant-weight partition.
    """
    points = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(bind_world, dtype=np.float64)[:, :3, 3]
    parent_ids = np.asarray(parents, dtype=np.int64)
    segments: list[tuple[int, np.ndarray, np.ndarray]] = []
    for child, parent in enumerate(parent_ids):
        if int(parent) < 0:
            continue
        start, end = joints[int(parent)], joints[child]
        delta = end - start
        denom = float(np.dot(delta, delta))
        if denom <= 1e-12:
            continue
        t = np.clip(((points - start[None]) @ delta) / denom, 0.0, 1.0)
        closest = start[None] + t[:, None] * delta[None]
        segments.append((child, closest, np.sum((points - closest) ** 2, axis=1)))
    if not segments:
        raise ValueError("articulation metrics require at least one nondegenerate bone segment")
    distances = np.stack([entry[2] for entry in segments], axis=1)
    nearest = np.argmin(distances, axis=1)
    regions: dict[int, np.ndarray] = {}
    for segment_index, (child, _closest, _distance) in enumerate(segments):
        ids = np.flatnonzero(nearest == segment_index)
        if len(ids) >= int(min_vertices):
            regions[int(child)] = ids.astype(np.int64)
    return regions


def _sequence_articulation_retention(
    vertices: np.ndarray,
    names: list[str],
    parents: np.ndarray,
    bind_world: np.ndarray,
    inverse_bind: np.ndarray,
    weights: np.ndarray,
    frame_groups: list[tuple[str, np.ndarray]],
    *,
    floor: float,
) -> dict[str, object]:
    """Compare candidate surface articulation to the fixed mocap bone motion.

    Each geometric region is assigned to a bind-pose bone segment, then its
    centroid is compared with the same region transformed by that *single*
    mocap joint.  The parent-joint translation is removed, so root travel or a
    globally wiggling mesh cannot satisfy the metric.  No image or optimized
    weight information enters region construction.
    """
    regions = _segment_surface_regions(vertices, bind_world, parents)
    points = np.asarray(vertices, dtype=np.float64)
    parent_ids = np.asarray(parents, dtype=np.int64)
    inv_bind = np.asarray(inverse_bind, dtype=np.float64)
    dense = np.asarray(weights, dtype=np.float64)
    joint_names = [str(name) for name in names]
    clips: dict[str, dict[str, object]] = {}
    pooled_joint_ratios: list[float] = []
    pooled_frame_ratios: list[float] = []
    pooled_errors: list[float] = []

    for key, worlds in frame_groups:
        world = np.asarray(worlds, dtype=np.float64)
        transforms = torch.as_tensor(world @ inv_bind[None], dtype=torch.float32, device="cuda")
        with torch.no_grad():
            posed = dual_quaternion_skin(
                torch.as_tensor(points, dtype=torch.float32, device="cuda"),
                torch.as_tensor(dense, dtype=torch.float32, device="cuda"),
                transforms,
            ).detach().cpu().numpy()
        joints_world = world[:, :, :3, 3]
        joint_rows: dict[str, dict[str, float]] = {}
        for child, ids in regions.items():
            parent = int(parent_ids[child])
            if parent < 0:
                continue
            # Expected motion is the single-bone transform that the region's
            # bind centroid would receive from this mocap joint.
            bind_centroid = np.mean(points[ids], axis=0)
            homogeneous = np.concatenate((bind_centroid, [1.0]))
            expected = np.einsum(
                "fij,j->fi",
                transforms.detach().cpu().numpy()[:, child],
                homogeneous,
            )[:, :3]
            observed = np.mean(posed[:, ids], axis=1)
            expected_relative = expected - joints_world[:, parent]
            observed_relative = observed - joints_world[:, parent]
            expected_delta = expected_relative - expected_relative[0:1]
            observed_delta = observed_relative - observed_relative[0:1]
            expected_norm = np.linalg.norm(expected_delta, axis=1)
            observed_norm = np.linalg.norm(observed_delta, axis=1)
            expected_amp = float(np.sqrt(np.mean(expected_norm ** 2)))
            if expected_amp <= 1e-5:
                continue
            observed_amp = float(np.sqrt(np.mean(observed_norm ** 2)))
            amp_ratio = observed_amp / max(expected_amp, 1e-8)
            frame_active = expected_norm >= max(expected_amp * 0.10, 1e-5)
            frame_ratio = observed_norm[frame_active] / np.maximum(expected_norm[frame_active], 1e-8)
            error = float(np.sqrt(np.mean((observed_delta - expected_delta) ** 2)) / max(expected_amp, 1e-8))
            cosine_values = np.sum(observed_delta[frame_active] * expected_delta[frame_active], axis=1)
            cosine_values /= np.maximum(
                np.linalg.norm(observed_delta[frame_active], axis=1)
                * np.linalg.norm(expected_delta[frame_active], axis=1),
                1e-8,
            )
            row = {
                "vertices": float(len(ids)),
                "expectedAmplitude": expected_amp,
                "observedAmplitude": observed_amp,
                "amplitudeRatio": float(amp_ratio),
                "p05FrameRatio": float(np.quantile(frame_ratio, 0.05)) if len(frame_ratio) else float(amp_ratio),
                "belowFloorFraction": float(np.mean(frame_ratio < float(floor))) if len(frame_ratio) else 0.0,
                "normalizedRmse": error,
                "meanDirectionCosine": float(np.mean(cosine_values)) if len(cosine_values) else 1.0,
            }
            joint_rows[joint_names[child]] = row
            pooled_joint_ratios.append(float(amp_ratio))
            pooled_frame_ratios.extend(frame_ratio.tolist())
            pooled_errors.append(error)
        joint_values = list(joint_rows.values())
        clips[key] = {
            "frames": float(len(world)),
            "activeJoints": float(len(joint_values)),
            "p05AmplitudeRatio": float(np.quantile([row["amplitudeRatio"] for row in joint_values], 0.05)) if joint_values else 1.0,
            "worstJointAmplitudeRatio": float(min((row["amplitudeRatio"] for row in joint_values), default=1.0)),
            "p05FrameRatio": float(np.quantile([value for row in joint_values for value in [row["p05FrameRatio"]]], 0.05)) if joint_values else 1.0,
            "belowFloorFraction": float(np.mean([row["belowFloorFraction"] for row in joint_values])) if joint_values else 0.0,
            "joints": joint_rows,
        }
    return {
        "floor": float(floor),
        "regionAssignment": "nearest_bind_bone_segment",
        "activeJointCount": float(len(pooled_joint_ratios)),
        "clips": clips,
        "pooled": {
            "p05AmplitudeRatio": float(np.quantile(pooled_joint_ratios, 0.05)) if pooled_joint_ratios else 1.0,
            "worstJointAmplitudeRatio": float(min(pooled_joint_ratios, default=1.0)),
            "p05FrameRatio": float(np.quantile(pooled_frame_ratios, 0.05)) if pooled_frame_ratios else 1.0,
            "belowFloorFraction": float(np.mean(np.asarray(pooled_frame_ratios) < float(floor))) if pooled_frame_ratios else 0.0,
            "meanNormalizedRmse": float(np.mean(pooled_errors)) if pooled_errors else 0.0,
        },
    }


def _articulation_fit_inputs(
    vertices: np.ndarray,
    bind_world: np.ndarray,
    parents: np.ndarray,
    inverse_bind: np.ndarray,
    worlds: np.ndarray,
) -> tuple[list[np.ndarray], np.ndarray, list[int]]:
    """Build camera-free geometric regions and fixed mocap targets for fitting."""
    regions = _segment_surface_regions(vertices, bind_world, parents)
    children = sorted(regions)
    region_ids = [regions[child] for child in children]
    centroids = np.asarray([np.mean(np.asarray(vertices)[ids], axis=0) for ids in region_ids], dtype=np.float64)
    homogeneous = np.column_stack((centroids, np.ones(len(centroids), dtype=np.float64)))
    matrices = np.asarray(worlds, dtype=np.float64) @ np.asarray(inverse_bind, dtype=np.float64)[None]
    targets = np.einsum("frij,rj->fri", matrices[:, children], homogeneous)[..., :3]
    return region_ids, targets, children


def _vertex_articulation_fit_inputs(
    vertices: np.ndarray,
    bind_world: np.ndarray,
    parents: np.ndarray,
    inverse_bind: np.ndarray,
    worlds: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Assign every vertex a bounded single-bone mocap trajectory target."""
    points = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(bind_world, dtype=np.float64)[:, :3, 3]
    parent_ids = np.asarray(parents, dtype=np.int64)
    segments: list[tuple[int, np.ndarray, float]] = []
    for child, parent in enumerate(parent_ids):
        if int(parent) < 0:
            continue
        start, end = joints[int(parent)], joints[child]
        delta = end - start
        length_sq = float(np.dot(delta, delta))
        if length_sq <= 1e-12:
            continue
        t = np.clip(((points - start[None]) @ delta) / length_sq, 0.0, 1.0)
        closest = start[None] + t[:, None] * delta[None]
        segments.append((child, np.sum((points - closest) ** 2, axis=1), float(np.sqrt(length_sq))))
    if not segments:
        raise ValueError("vertex articulation targets require at least one nondegenerate bone segment")
    distances = np.stack([entry[1] for entry in segments], axis=1)
    nearest = np.argmin(distances, axis=1)
    child_ids = np.asarray([segments[int(index)][0] for index in nearest], dtype=np.int64)
    lengths = np.asarray([segments[int(index)][2] for index in nearest], dtype=np.float64)
    distance = np.sqrt(np.maximum(distances[np.arange(len(points)), nearest], 0.0))
    # Far-from-segment vertices should not be pulled toward an arbitrary
    # terminal bone merely because every vertex needs a label.  Their tiny
    # confidence keeps the target available for broad bodies while preserving
    # the embedded surface around unrelated limbs.
    confidence = np.clip(np.exp(-distance / np.maximum(0.5 * lengths, 1e-6)), 0.0, 1.0)
    matrices = np.asarray(worlds, dtype=np.float64) @ np.asarray(inverse_bind, dtype=np.float64)[None]
    homogeneous = np.column_stack((points, np.ones(len(points), dtype=np.float64)))
    targets = np.einsum("fvij,vj->fvi", matrices[:, child_ids], homogeneous)[..., :3]
    return targets, confidence, child_ids.tolist()


def retarget_capture_to_target(
    raw: np.lib.npyio.NpzFile,
    entry: dict,
    source_skin: dict,
    reference: np.ndarray,
    target,
    bind_world: np.ndarray,
) -> dict:
    """Retarget capture positions in the *actual target bind basis*.

    ``load_motion`` historically reconstructed local rotations against the
    capture skeleton's proportions, then the preview reused those matrices on
    a separately fitted Meshy skeleton.  That is not a valid local-rotation
    transfer when the target bind has a different orientation or scale.  This
    helper keeps the mocap positions as the motion source but solves the
    desired directions again against the target's real rest offsets.
    """
    # Both supported corpus representations retain predicted joint positions.
    # Use that common motion interface here instead of importing a
    # representation-specific local-rotation basis from the capture rig.
    source_indices = np.asarray(entry["sourceIndices"], dtype=np.int64)
    capture = np.asarray(raw["pred_position"], dtype=np.float64)[source_indices]
    if capture.ndim != 3 or capture.shape[1:] != (len(source_skin["names"]), 3) or not np.isfinite(capture).all():
        raise ValueError("target-basis retarget requires finite predicted joint positions")
    target_names = [str(name) for name in target.names]
    target_parents = np.asarray(target.parents, dtype=np.int64)
    source_names = [str(name) for name in source_skin["names"]]
    source_index = {name: index for index, name in enumerate(source_names)}
    target_index = {name: index for index, name in enumerate(target_names)}
    # Build one-bone chains only where both the target joint and its parent have
    # an explicit source counterpart.  Unmapped helper joints keep their bind
    # local rotation instead of receiving a fabricated motion.
    chains: list[dict[str, list[str]]] = []
    for child_index, parent_index in enumerate(target_parents):
        if int(parent_index) < 0:
            continue
        child_name = target_names[child_index]
        parent_name = target_names[int(parent_index)]
        source_child = SOURCE_NAMES.get(child_name, child_name)
        source_parent = SOURCE_NAMES.get(parent_name, parent_name)
        if source_child not in source_index or source_parent not in source_index:
            continue
        chains.append({"target": [parent_name, child_name],
                       "capture": [source_parent, source_child]})
    if len(chains) < 20:
        raise ValueError(f"target bind has only {len(chains)} explicit mocap chains")
    rest_local = rest_local_matrices(bind_world, target_parents)[:, :3, :3]
    rest_offsets = local_offsets_from_world(bind_world, target_parents)
    result = retarget_clip(
        capture_positions=capture,
        capture_rest=np.asarray(reference, dtype=np.float64),
        capture_names=source_names,
        capture_parents=np.asarray(source_skin["parents"], dtype=np.int64),
        target_names=target_names,
        target_parents=target_parents,
        target_rest_local_rotation=rest_local,
        target_rest_local_translation=rest_offsets,
        target_rest_world=np.asarray(bind_world[:, :3, 3], dtype=np.float64),
        chains=chains,
    )
    # Normalize the retarget_clip contract to the capture_motion contract used
    # below by the preview assembler.
    result["localRotation"] = result["sourceLocalRotation"]
    result["clipFrame0IsBind"] = bool(
        np.max(np.abs(result["localRotation"][0] - rest_local)) < 1e-5
    )
    direction_errors = []
    desired = np.asarray(result["desiredChildDirections"], dtype=np.float64)
    worlds = np.asarray(result["jointWorld"], dtype=np.float64)
    for frame in range(len(worlds)):
        for joint, parent in enumerate(target_parents):
            if int(parent) < 0 or np.linalg.norm(desired[frame, joint]) <= 1e-8:
                continue
            actual = worlds[frame, joint, :3, 3] - worlds[frame, int(parent), :3, 3]
            actual /= max(float(np.linalg.norm(actual)), 1e-8)
            wanted = desired[frame, joint] / max(float(np.linalg.norm(desired[frame, joint])), 1e-8)
            direction_errors.append(float(np.arccos(np.clip(actual @ wanted, -1.0, 1.0))))
    result["targetDirectionErrorMeanRad"] = float(np.mean(direction_errors)) if direction_errors else 0.0
    result["targetDirectionErrorMaxRad"] = float(np.max(direction_errors)) if direction_errors else 0.0
    return result


def retarget_capture_bind_delta_transport(
    raw: np.lib.npyio.NpzFile,
    entry: dict,
    source_skin: dict,
    reference: np.ndarray,
    target,
    bind_world: np.ndarray,
) -> dict:
    """Transport source-frame deltas between explicit anatomical bind frames.

    The source capture is measured from ``reference`` (the validated frame-0
    pose), while a generated target mesh has its own fitted bind frame.  Solving
    absolute target directions against mismatched rest positions can invent a
    swing on an otherwise stationary limb.  This path first solves local source
    rotations in the reference frame, then conjugates each source delta into
    the corresponding target local frame.  It uses no camera or image loss.
    """
    source_indices = np.asarray(entry["sourceIndices"], dtype=np.int64)
    capture = np.asarray(raw["pred_position"], dtype=np.float64)[source_indices]
    source_names = [str(name) for name in source_skin["names"]]
    source_parents = np.asarray(source_skin["parents"], dtype=np.int64)
    target_names = [str(name) for name in target.names]
    target_parents = np.asarray(target.parents, dtype=np.int64)
    if capture.ndim != 3 or capture.shape[1:] != (len(source_names), 3) or not np.isfinite(capture).all():
        raise ValueError("bind-delta transport requires finite predicted joint positions")

    source_bind_world = np.linalg.inv(np.asarray(source_skin["inverseBind"], dtype=np.float64))
    source_reference_world = source_bind_world.copy()
    source_reference_world[:, :3, 3] = np.asarray(reference, dtype=np.float64)
    source_rest_local = rest_local_matrices(source_reference_world, source_parents)[:, :3, :3]
    source_rest_offsets = local_offsets_from_world(source_reference_world, source_parents)
    source_chains = [
        {"target": [source_names[int(parent)], source_names[index]],
         "capture": [source_names[int(parent)], source_names[index]]}
        for index, parent in enumerate(source_parents) if int(parent) >= 0
    ]
    source_result = retarget_clip(
        capture_positions=capture,
        capture_rest=np.asarray(reference, dtype=np.float64),
        capture_names=source_names,
        capture_parents=source_parents,
        target_names=source_names,
        target_parents=source_parents,
        target_rest_local_rotation=source_rest_local,
        target_rest_local_translation=source_rest_offsets,
        target_rest_world=np.asarray(reference, dtype=np.float64),
        chains=source_chains,
    )
    source_current = np.asarray(source_result["sourceLocalRotation"], dtype=np.float64)
    reference_index = int(entry.get("referenceIndex", -1))
    starts_at_reference = bool(len(source_indices) and int(source_indices[0]) == reference_index)
    if starts_at_reference:
        # Only a clip whose selected source index is explicitly the validated
        # reference receives this numerical twist cleanup. Context windows do
        # not start at bind and must retain their authored first pose.
        source_current[0] = source_rest_local
    target_rest_local = rest_local_matrices(bind_world, target_parents)[:, :3, :3]
    source_index = {name: index for index, name in enumerate(source_names)}
    target_to_source: dict[int, int] = {}
    for target_index, target_name in enumerate(target_names):
        source_name = SOURCE_NAMES.get(target_name, target_name)
        if source_name not in source_index:
            continue
        target_to_source[target_index] = source_index[source_name]
    target_current = transport_bind_deltas(
        source_local_rotation=source_current,
        source_rest_local_rotation=source_rest_local,
        target_rest_local_rotation=target_rest_local,
        target_to_source=target_to_source,
    )
    target_rest_local4 = rest_local_matrices(bind_world, target_parents)
    target_deltas = np.swapaxes(target_rest_local, -1, -2)[None] @ target_current
    worlds = apply_local_deltas(target_rest_local4, target_parents, target_deltas)
    desired = np.zeros((len(worlds), len(target_names), 3), dtype=np.float64)
    for index, parent in enumerate(target_parents):
        if int(parent) >= 0:
            desired[:, index] = worlds[:, index, :3, 3] - worlds[:, int(parent), :3, 3]
            norms = np.linalg.norm(desired[:, index], axis=-1, keepdims=True)
            desired[:, index] /= np.maximum(norms, 1e-8)
    posed_lengths = np.stack([
        np.linalg.norm(worlds[frame, :, :3, 3] - worlds[frame, target_parents.clip(min=0), :3, 3], axis=-1)
        for frame in range(len(worlds))
    ])
    posed_lengths[:, target_parents < 0] = 0.0
    rest_lengths = posed_lengths[0].copy()
    return {
        "sourceLocalRotation": target_current,
        "localRotation": target_current,
        "unsmoothedLocalRotation": target_current.copy(),
        "jointWorld": worlds,
        "unsmoothedJointWorld": worlds.copy(),
        "desiredChildDirections": desired,
        "twistPolicy": "bind_delta_transport",
        "rootTranslationAvailable": False,
        "rootTravelMax": 0.0,
        "regularizerUsed": False,
        "regularizerRejected": False,
        "mappedParentJoints": [index for index, parent in enumerate(target_parents) if int(parent) >= 0],
        "unmappedParentJoints": [],
        "restBoneLengths": rest_lengths,
        "posedBoneLengths": posed_lengths,
        "lengthErrorMax": float(np.max(np.abs(posed_lengths - rest_lengths.reshape(1, -1)))),
        "motionPreservation": source_result.get("motionPreservation", {}),
        "clipFrame0IsBind": bool(starts_at_reference),
        "referenceFrameIndex": reference_index,
        "targetDirectionErrorMeanRad": 0.0,
        "targetDirectionErrorMaxRad": 0.0,
        "targetDirectionErrorBasis": "not_applicable_bind_delta_transport",
    }


def load_capture_skeleton(capture_path: Path) -> dict:
    """Load only the mocap skeleton contract; no donor mesh or rig metadata."""
    with np.load(capture_path, allow_pickle=False) as raw:
        names = list(raw["joint_names"].astype(str))
        parents = np.asarray(raw["parents"], dtype=np.int64)
        offsets = np.asarray(raw["offsets"], dtype=np.float64)
        capture_offsets = np.asarray(raw["vendor_offset_a"], dtype=np.float64)
    bind_world = rest_world_from_offsets(offsets, parents)
    return {
        "names": names,
        "parents": parents,
        "offsets": offsets,
        "captureOffsets": capture_offsets,
        "inverseBind": np.linalg.inv(bind_world),
    }


def envelope_camera(camera: dict, basis: np.ndarray, posed_vertices: np.ndarray,
                    target_bbox: tuple[float, float, float, float], resolution: int) -> dict:
    """Keep every predicted frame visible without moving the source sprites."""
    projected = np.asarray(posed_vertices, dtype=np.float64) @ np.asarray(basis[:2], dtype=np.float64).T
    lo, hi = projected.min((0, 1)), projected.max((0, 1))
    span = np.maximum(hi - lo, 1e-6)
    x0, y0, x1, y1 = target_bbox
    source_center = np.asarray((0.5 * (x0 + x1), 0.5 * (y0 + y1)), dtype=np.float64)
    edge_margin = 4.0
    available = max(2.0 * min(source_center[0] - edge_margin,
                               resolution - edge_margin - source_center[0],
                               source_center[1] - edge_margin,
                               resolution - edge_margin - source_center[1]), 1.0)
    scale = min(float(camera["scale"]), available / float(np.max(span)))
    predicted_center = 0.5 * (lo + hi)
    adjusted = dict(camera)
    adjusted["scale"] = scale
    adjusted["offset"] = source_center - scale * predicted_center
    adjusted["envelopeWorldSpan"] = span.tolist()
    depth = np.asarray(posed_vertices, dtype=np.float64) @ np.asarray(basis[2], dtype=np.float64)
    depth_lo, depth_hi = float(depth.min()), float(depth.max())
    depth_pad = max(0.02 * (depth_hi - depth_lo), 1e-6)
    adjusted["depth_center"] = 0.5 * (depth_lo + depth_hi)
    adjusted["depth_span"] = max(depth_hi - depth_lo + 2.0 * depth_pad, 1e-6)
    return adjusted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        type=Path,
        default=REPO / "artifacts/homm3_mocap_v2/behemoth_idle_bind_t2_v1/rigged/h3_behemoth_idle_bind_t2_rigged.glb",
        help="Rigged GLB to diagnose; defaults to the original T2 candidate.",
    )
    parser.add_argument(
        "--candidate-mode",
        choices=("auto", "smartrig", "m7"),
        default="auto",
        help=("Candidate contract. 'smartrig' requires embedded skin; 'm7' "
              "requires a static surface and makes the geometric initializer "
              "explicit; 'auto' preserves legacy detection."),
    )
    # Confirmed against the original Behemoth sprite orientation.
    parser.add_argument("--yaw", type=float, default=76)
    parser.add_argument("--pitch", type=float, default=14)
    parser.add_argument("--resolution", type=int, default=224)
    parser.add_argument(
        "--camera-from-report",
        type=Path,
        default=None,
        help=("Reuse the serialized camera from a matched baseline report. "
              "This is required for a strict same-mesh A/B because automatic "
              "enveloping can otherwise hide small regressions behind framing."),
    )
    parser.add_argument(
        "--clip-keys",
        default="g00_move,g02_idle",
        help=("Comma-separated corpus clip keys used for the multi-frame solve. "
              "The default is the compact move+idle pilot; pass additional "
              "validated keys to include more mocap examples."),
    )
    parser.add_argument(
        "--fit-clip-keys",
        default="",
        help=("Optional comma-separated subset of --clip-keys used to fit "
              "weights. Empty means every selected clip."),
    )
    parser.add_argument(
        "--validation-clip-keys",
        default="",
        help=("Optional held-out subset of --clip-keys scored after fitting. "
              "Validation clips must not overlap --fit-clip-keys."),
    )
    parser.add_argument("--weight-policy", choices=("capsule", "region", "region3d", "joint", "geodesic3d", "donor"), default="capsule")
    parser.add_argument(
        "--retarget-policy",
        choices=("target_directions", "bind_delta_transport"),
        default="bind_delta_transport",
        help=("Motion retarget basis. 'bind_delta_transport' extracts source "
              "deltas from the validated frame-0 mocap bind and transports "
              "them into each fitted target bone frame; 'target_directions' "
              "keeps the legacy absolute-direction solve."),
    )
    parser.add_argument("--fit-policy", choices=("bone_surface", "symmetric_3d", "surface_pca"), default="bone_surface",
                        help="Camera-free 3D bind objective. 'surface_pca' is a compatibility alias for bone_surface; symmetric_3d adds surface coverage.")
    parser.add_argument(
        "--fit-rest",
        choices=("source_offsets", "capture_reference", "capture_reference_constrained"),
        default="source_offsets",
        help=("Bind-position source for the camera-free skeleton fit. "
              "'capture_reference' uses the validated frame-0 mocap pose so "
              "retarget directions and fitted bind geometry share one rest basis; "
              "'capture_reference_constrained' transfers that pose through the "
              "same affine fit as the vendor-rest skeleton to avoid PCA flips."),
    )
    parser.add_argument("--fit-weights-steps", type=int, default=0,
                        help="Optional image-supervised sparse-weight refinement steps; 0 disables fitting.")
    parser.add_argument("--fit-max-influences", type=int, default=4)
    parser.add_argument("--fit-3d-steps", type=int, default=0,
                        help="Sequence-aware 3-D weight optimization steps; 0 disables this camera-free pass.")
    parser.add_argument("--fit-3d-max-influences", type=int, default=2,
                        help="Sparse influence budget for the sequence-aware 3-D pass.")
    parser.add_argument("--fit-3d-init", choices=("embedded", "segment", "blend"), default="embedded",
                        help=("Initialization for sequence-aware fitting: preserve embedded/vendor weights, "
                              "replace with nearest geometric bone-segment ownership, or blend the two."))
    parser.add_argument("--fit-3d-init-blend", type=float, default=0.5,
                        help="Geometric share for --fit-3d-init blend (0..1).")
    parser.add_argument("--fit-3d-prior-weight", type=float, default=8.0)
    parser.add_argument("--fit-3d-smoothness-weight", type=float, default=0.75)
    parser.add_argument("--fit-3d-motion-weight", type=float, default=0.50,
                        help="Lower-bound motion-preservation weight for the sequence-aware 3-D pass.")
    parser.add_argument("--fit-3d-motion-floor", type=float, default=0.70,
                        help="Minimum fraction of initial per-vertex motion energy to retain (0,1].")
    parser.add_argument("--fit-3d-articulation-weight", type=float, default=0.75,
                        help="Camera-free geometric limb-motion target weight; 0 disables this term.")
    parser.add_argument("--fit-3d-vertex-motion-weight", type=float, default=0.25,
                        help="Camera-free per-vertex single-bone trajectory weight; 0 disables this term.")
    parser.add_argument("--fit-3d-max-total-variation", type=float, default=0.25,
                        help="Soft trust-region cap on per-vertex weight total variation (0,2].")
    parser.add_argument("--pose-corrective-steps", type=int, default=0,
                        help="Bounded 3-D pose-corrective residual iterations; 0 disables the morph-like pass.")
    parser.add_argument("--pose-corrective-strength", type=float, default=0.25)
    parser.add_argument("--capsule-radius-scale", type=float, default=0.30,
                        help="Radius of geometry-derived bone capsules relative to segment length.")
    parser.add_argument("--capsule-max-influences", type=int, default=2,
                        help="Maximum geometry-derived mocap influences per vertex.")
    parser.add_argument("--capsule-torso-bias", type=float, default=1.5,
                        help="Soft prior keeping vertices near the spine chain on torso bones.")
    parser.add_argument("--capsule-torso-radius-scale", type=float, default=0.35,
                        help="Torso-prior radius relative to mesh span.")
    parser.add_argument("--capsule-terminal-radius-scale", type=float, default=0.15,
                        help="Radius multiplier for terminal helper joints.")
    parser.add_argument("--capsule-torso-core", type=float, default=0.0,
                        help="Screen-space torso-core radius relative to mesh span; 0 disables region ownership.")
    parser.add_argument("--capsule-torso-core-blend", type=float, default=0.35,
                        help="Blend toward torso-only support inside the optional torso core.")
    parser.add_argument("--skin-mode", choices=("dqs", "lbs"), default="dqs",
                        help="Deformation blend used for the diagnostic preview.")
    parser.add_argument(
        "--hold-joints",
        default="",
        help=("Optional comma-separated target-joint glob patterns to hold at the "
              "idle bind during a diagnostic render. This is a generic motion "
              "isolation control, not an asset-specific repair."),
    )
    parser.add_argument(
        "--swap-arm-motion",
        action="store_true",
        help=("Diagnostic correspondence test: exchange left/right shoulder, "
              "arm, forearm, and hand motion columns before retarget deltas. "
              "This does not alter geometry or weights."),
    )
    parser.add_argument(
        "--auto-swap-arm",
        action="store_true",
        help=("Choose left/right arm correspondence by the lower all-frame "
              "camera-free surface strain score. This is a generic discrete "
              "correspondence solve, not image-IoU fitting."),
    )
    args = parser.parse_args()
    if not 0.0 <= float(args.fit_3d_init_blend) <= 1.0:
        raise ValueError("--fit-3d-init-blend must be between 0 and 1")
    # Keep the historical surface_pca spelling accepted, but report and route
    # the actual solver objective so manifests cannot mistake an alias for a
    # distinct fitting algorithm.
    fit_objective = "symmetric_3d" if args.fit_policy == "symmetric_3d" else "bone_surface"
    render.skin_mode = args.skin_mode
    hold_patterns = tuple(
        pattern.strip().lower() for pattern in args.hold_joints.split(",") if pattern.strip()
    )
    sequence_keys = tuple(key.strip() for key in args.clip_keys.split(",") if key.strip())
    if not sequence_keys:
        raise ValueError("--clip-keys must contain at least one corpus key")
    fit_keys_arg = tuple(key.strip() for key in args.fit_clip_keys.split(",") if key.strip())
    validation_keys = tuple(key.strip() for key in args.validation_clip_keys.split(",") if key.strip())
    unknown_fit = sorted(set(fit_keys_arg) - set(sequence_keys))
    unknown_validation = sorted(set(validation_keys) - set(sequence_keys))
    if unknown_fit or unknown_validation:
        raise ValueError(f"fit/validation clips must be contained in --clip-keys; unknown={unknown_fit + unknown_validation}")
    if set(fit_keys_arg).intersection(validation_keys):
        raise ValueError("--fit-clip-keys and --validation-clip-keys must be disjoint")
    basis = _basis_yup(args.yaw, args.pitch)
    if args.out.exists():
        raise FileExistsError(args.out)
    corpus_path = REPO / "artifacts/homm3_mocap_v2/skin_mesh_pilot/behemoth/captures_v1/corpus.json"
    calibration = REPO / "artifacts/homm3_mocap_v2/shape_preserved/h3_behemoth/calibration/idle_reference_v1.json"
    candidate = args.candidate if args.candidate.is_absolute() else REPO / args.candidate
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    reference = np.asarray(json.loads(calibration.read_text(encoding="utf-8"))["referencePositions"], dtype=np.float64)
    entries = [e for e in corpus["captures"] if e["key"] in sequence_keys]
    by_key = {e["key"]: e for e in entries}
    if set(by_key) != set(sequence_keys):
        missing = [key for key in sequence_keys if key not in by_key]
        raise ValueError(f"requested corpus clip keys are missing: {missing}")
    source_skin = load_capture_skeleton(Path(by_key[sequence_keys[0]]["capture"]))
    # Motion is retargeted only after the actual target bind is known.  Do not
    # precompute local rotations against the capture skeleton and reuse them on
    # a differently scaled/oriented Meshy surface.
    motions = {}
    candidate_doc = read_glb(candidate)["json"]
    geodesic_diagnostics = None
    candidate_has_skin = bool(candidate_doc.get("skins"))
    if args.candidate_mode == "smartrig" and not candidate_has_skin:
        raise ValueError("--candidate-mode smartrig requires a GLB with embedded skin")
    if args.candidate_mode == "m7" and candidate_has_skin:
        raise ValueError("--candidate-mode m7 requires a static GLB without embedded skin")
    if candidate_has_skin and args.candidate_mode != "m7":
        # A skinned candidate must parse cleanly. Do not hide malformed rig
        # metadata by silently replacing it with a synthesized fallback.
        target = load_bind_skeleton(candidate)
        unrigged_fallback = False
    else:
        # M7 Standard can produce a valid static GLB that Meshy's Smart Rig
        # rejects. Reuse the owned Behemoth skeleton as a diagnostic skin
        # owner, never as proof that Meshy rigging succeeded.
        surface = load_glb_surface(candidate)
        bind_world_source = np.linalg.inv(np.asarray(source_skin["inverseBind"], dtype=np.float64))
        fit_rest_source = bind_world_source.copy()
        if args.fit_rest == "capture_reference":
            # The capture reference is the actual frame-0 pose used by the
            # direction retargeter.  Fitting against the vendor offset/T-pose
            # while measuring motion from this pose mixes two rest bases and
            # can send a limb across the head even when bone directions are
            # numerically preserved.
            fit_rest_source[:, :3, 3] = reference
        bind_world_fit, _fit_scale = fit_rest_skeleton_to_surface(
            fit_rest_source, surface["vertices"], source_skin["parents"],
            objective=fit_objective,
        )
        if args.fit_rest == "capture_reference_constrained":
            # Keep the orientation/scale selected by the camera-free fit, but
            # express the actual frame-0 mocap pose in that same coordinate
            # basis.  A fresh PCA fit of the folded pose is underconstrained
            # and can choose a mirrored principal-axis permutation.
            source_root = bind_world_source[0, :3, 3]
            target_root = bind_world_fit[0, :3, 3]
            source_offsets = bind_world_source[:, :3, 3] - source_root[None]
            target_offsets = bind_world_fit[:, :3, 3] - target_root[None]
            linear_map, *_ = np.linalg.lstsq(source_offsets, target_offsets, rcond=None)
            transferred_reference = (reference - source_root[None]) @ linear_map + target_root[None]
            bind_world_fit[:, :3, 3] = transferred_reference
        placed = surface["vertices"]
        target = SimpleNamespace(
            names=list(source_skin["names"]),
            parents=np.asarray(source_skin["parents"], dtype=np.int64),
            inverse_bind=np.linalg.inv(bind_world_fit),
            vertices=placed,
            triangles=surface["triangles"],
            uvs=surface["uvs"],
            albedo=surface["albedo"],
        )
        if args.weight_policy == "donor":
            # This is retained as an explicitly opt-in comparison lane only;
            # the default capsule path is fully independent of frozen donor
            # preparation.
            from run_skin_weight_pilot import _load_frozen_prep
            _, donor_skin = _load_frozen_prep("h3_behemoth")
            source_points = np.column_stack((bind_world_source[:, :3, 3], np.ones(len(bind_world_source))))
            affine, *_ = np.linalg.lstsq(source_points, bind_world_fit[:, :3, 3], rcond=None)
            donor_placed = np.column_stack((donor_skin["vertices"], np.ones(len(donor_skin["vertices"])))) @ affine
            donor_placed = donor_placed[:, :3]
            target.mocap_weights = transfer_weights_from_donor(
                target.vertices, donor_placed, donor_skin["weights"], neighbors=8, max_influences=4
            )
        elif args.weight_policy == "region3d":
            target.mocap_weights = region_capsule_weights_3d(
                target.vertices,
                local_offsets_from_world(bind_world_fit, target.parents),
                target.parents,
                list(target.names),
                get_profile("h3_behemoth")["regionJoints"],
                max_influences=args.capsule_max_influences,
                radius_scale=args.capsule_radius_scale,
                terminal_radius_scale=args.capsule_terminal_radius_scale,
            )
        elif args.weight_policy == "geodesic3d":
            # Surface-Dijkstra ownership is entirely camera-free.  It seeds
            # each reachable mocap segment from the target mesh and lets
            # influence spread only along triangle connectivity, preventing a
            # leg capsule from claiming a disconnected torso in empty space.
            from prepare_move_bind_capture_bind import build_initializer_weights
            geodesic = build_initializer_weights(
                target.vertices,
                target.triangles,
                bind_world_fit[:, :3, 3],
                target.parents,
                k=args.capsule_max_influences,
                weld_policy="export_position",
            )
            target.mocap_weights = geodesic["weights"]
            # Keep the report compact; the dense [vertex,bone] distance field
            # is an intermediate and must not be serialized into every preview.
            geodesic_diagnostics = {
                key: value for key, value in geodesic["geodesic"].items()
                if key != "distances"
            }
        elif args.weight_policy == "region":
            target.mocap_weights = region_capsule_weights(
                target.vertices,
                local_offsets_from_world(bind_world_fit, target.parents),
                target.parents,
                list(target.names),
                basis,
                get_profile("h3_behemoth")["regionJoints"],
                region_widths={
                    "torso": 0.25, "neck_head": 0.12,
                    "arm_left": 0.08, "arm_right": 0.08,
                    "leg_left": 0.10, "leg_right": 0.10,
                },
                max_influences=args.capsule_max_influences,
                radius_scale=args.capsule_radius_scale,
                terminal_radius_scale=args.capsule_terminal_radius_scale,
            )
        elif args.weight_policy == "joint":
            target.mocap_weights = nearest_bone_weights(
                target.vertices, bind_world_fit[:, :3, 3], k=args.capsule_max_influences
            )
        else:
            name_index = {name: index for index, name in enumerate(target.names)}
            left = next((name_index[name] for name in ("mixamorig:LeftShoulder", "LeftShoulder") if name in name_index), None)
            right = next((name_index[name] for name in ("mixamorig:RightShoulder", "RightShoulder") if name in name_index), None)
            gate_axis = None
            gate_labels = None
            if left is not None and right is not None:
                gate_axis = bind_world_fit[left, :3, 3] - bind_world_fit[right, :3, 3]
                root = bind_world_fit[0, :3, 3]
                relative = bind_world_fit[:, :3, 3] - root[None]
                projection = relative @ (gate_axis / np.linalg.norm(gate_axis))
                gate_labels = np.sign(projection).astype(np.int8)
                gate_labels[np.abs(projection) < 0.06 * np.ptp(surface["vertices"], axis=0).max()] = 0
            torso_mask = np.asarray([
                ("Hips" in name or "Spine" in name or name.endswith(":Neck"))
                for name in target.names
            ], dtype=bool)
            target.mocap_weights = capsule_bone_weights(
                target.vertices,
                local_offsets_from_world(bind_world_fit, target.parents),
                target.parents,
                max_influences=args.capsule_max_influences,
                side_axis=gate_axis,
                side_labels=gate_labels,
                side_origin=bind_world_fit[0, :3, 3],
                radius_scale=args.capsule_radius_scale,
                torso_mask=torso_mask,
                torso_bias=args.capsule_torso_bias,
                torso_radius_scale=args.capsule_torso_radius_scale,
                terminal_radius_scale=args.capsule_terminal_radius_scale,
            )
            if args.capsule_torso_core > 0.0:
                if not 0.0 <= args.capsule_torso_core_blend <= 1.0:
                    raise ValueError("--capsule-torso-core-blend must be between 0 and 1")
                projected_vertices = target.vertices @ basis[:2].T
                projected_joints = bind_world_fit[:, :3, 3] @ basis[:2].T
                span = max(float(np.ptp(projected_vertices, axis=0).max()), 1e-8)
                center = projected_joints[torso_mask].mean(axis=0)
                radius = float(args.capsule_torso_core) * span
                core = np.sum(((projected_vertices - center[None]) / max(radius, 1e-8)) ** 2, axis=1) <= 1.0
                if np.any(core):
                    torso_weights = capsule_bone_weights(
                        target.vertices[core],
                        local_offsets_from_world(bind_world_fit, target.parents),
                        target.parents,
                        max_influences=min(args.capsule_max_influences, int(torso_mask.sum())),
                        radius_scale=args.capsule_radius_scale,
                        torso_mask=torso_mask,
                        torso_bias=args.capsule_torso_bias,
                        torso_radius_scale=args.capsule_torso_radius_scale,
                        terminal_radius_scale=args.capsule_terminal_radius_scale,
                        allowed_mask=torso_mask,
                    )
                    target.mocap_weights[core] = (
                        (1.0 - args.capsule_torso_core_blend) * target.mocap_weights[core]
                        + args.capsule_torso_core_blend * torso_weights
                    )
                    target.mocap_weights[core] = sparsify_weights(
                        target.mocap_weights[core], max_influences=args.capsule_max_influences
                    )
        validate_weights(
            target.mocap_weights,
            max_influences=args.capsule_max_influences if args.weight_policy in {"capsule", "region3d", "geodesic3d"} else 4,
        )
        unrigged_fallback = True
    weights = dense_weights(target)
    initial_weights_for_sequence = np.asarray(weights, dtype=np.float64).copy()
    source_index = {name: index for index, name in enumerate(source_skin["names"])}
    mapped = {}
    for index, target_name in enumerate(target.names):
        # Accept both the target-side short names used by the owned fallback
        # skeleton and the already-canonical ``mixamorig:*`` names present in
        # the older SmartRig delivery.  The previous branch only mapped the
        # fallback path, so a valid embedded SmartRig could be rejected as
        # having zero usable mocap joints even though its names already matched
        # the capture skeleton.
        source_name = SOURCE_NAMES.get(target_name, target_name)
        if source_name in source_index:
            mapped[index] = source_index[source_name]
    if len(mapped) < 20:
        raise ValueError(f"only {len(mapped)} named joints map to corpus motion")
    bind_world = np.linalg.inv(np.asarray(target.inverse_bind, dtype=np.float64))
    for key, entry in by_key.items():
        with np.load(entry["capture"], allow_pickle=False) as raw:
            if args.retarget_policy == "bind_delta_transport":
                motions[key] = retarget_capture_bind_delta_transport(
                    raw, entry, source_skin, reference, target, bind_world
                )
            else:
                motions[key] = retarget_capture_to_target(
                    raw, entry, source_skin, reference, target, bind_world
                )
    rest_local = rest_local_matrices(bind_world, np.asarray(target.parents, dtype=np.int64))
    # Corpus clips are context windows: ``sourceIndices`` need not include the
    # validated reference frame (and often start several frames after it).
    # The bind anchor is therefore the actual target rest pose, never the first
    # frame of an arbitrary clip.  Using any selected clip's first frame here
    # silently re-anchors every animation to a non-bind pose and produces the
    # apparent mouth/limb jumps reported in previews.
    anchor_target = rest_local[:, :3, :3].copy()
    held = [
        index for index, name in enumerate(target.names)
        if any(fnmatchcase(str(name).lower(), pattern) for pattern in hold_patterns)
    ]

    def build_frame_groups(swap_arm: bool) -> list[tuple[str, np.ndarray]]:
        groups: list[tuple[str, np.ndarray]] = []
        candidate_anchor = (
            _exchange_arm_motion(anchor_target[None], list(target.names))[0]
            if swap_arm else anchor_target
        )
        for key in sequence_keys:
            current_target = np.repeat(
                np.eye(3, dtype=np.float64)[None, None],
                len(motions[key]["localRotation"]) * len(target.names), axis=0
            ).reshape(len(motions[key]["localRotation"]), len(target.names), 3, 3)
            for target_index, source_joint in mapped.items():
                current_target[:, target_index] = motions[key]["localRotation"][:, source_joint]
            if swap_arm:
                current_target = _exchange_arm_motion(current_target, list(target.names))
            # The mesh bind is the idle-anchor pose. Convert every absolute
            # retargeted local rotation into a bind-relative delta by solving
            # ``anchor * delta = current``. This keeps the target rest basis
            # explicit while leaving motion provenance in mocap rotations.
            deltas = bind_relative_local_deltas(current_target, candidate_anchor)
            if held:
                deltas[:, held] = np.eye(3, dtype=np.float64)
            groups.append((key, apply_local_deltas(rest_local, np.asarray(target.parents, dtype=np.int64), deltas)))
        return groups

    candidate_groups = {False: build_frame_groups(False)}
    strain_candidates: dict[str, dict[str, float]] = {}
    if args.auto_swap_arm and not args.swap_arm_motion:
        candidate_groups[True] = build_frame_groups(True)
        with cascade_batch_lock(REPO):
            strain_candidates["default"] = _sequence_surface_strain(
                target.vertices, target.triangles, weights, target.inverse_bind, candidate_groups[False]
            )
            strain_candidates["swapped"] = _sequence_surface_strain(
                target.vertices, target.triangles, weights, target.inverse_bind, candidate_groups[True]
            )
        selected_swap_arm = strain_candidates["swapped"]["total"] < strain_candidates["default"]["total"]
    else:
        selected_swap_arm = bool(args.swap_arm_motion)
        if selected_swap_arm:
            candidate_groups[True] = build_frame_groups(True)
    all_frames = candidate_groups[bool(selected_swap_arm)]
    fit_keys = fit_keys_arg or tuple(sequence_keys)
    fit_key_set = set(fit_keys)
    validation_key_set = set(validation_keys)
    fit_frames = [(key, worlds) for key, worlds in all_frames if key in fit_key_set]
    validation_frames = [(key, worlds) for key, worlds in all_frames if key in validation_key_set]
    if not fit_frames:
        raise ValueError("the fit clip set produced no frames")
    identity_deltas = np.repeat(
        np.eye(3, dtype=np.float64)[None, None], len(target.names), axis=1
    )
    bind_from_identity = apply_local_deltas(
        rest_local, np.asarray(target.parents, dtype=np.int64), identity_deltas
    )[0]
    idle_bind_world_error = float(np.max(np.abs(bind_from_identity - bind_world)))
    clip_frame0_world_error = {
        key: float(np.max(np.abs(worlds[0] - bind_world))) for key, worlds in all_frames
    }
    motion_frame0_is_bind = {
        key: bool(np.max(np.abs(worlds[0] - bind_world)) < 1e-6)
        for key, worlds in all_frames
    }
    first = Path(by_key[sequence_keys[0]]["frames"][0])
    with Image.open(first) as image:
        source_size = image.size
    side = max(source_size)
    crop = {"left": -((side - source_size[0]) // 2), "top": -((side - source_size[1]) // 2), "size": side}
    alpha = source_images([first], crop, args.resolution)[1][0].detach().cpu().numpy()
    scale, offset = _bbox_scale_offset(target.vertices, basis, _target_bbox(alpha[..., 0]))
    camera = _camera(basis, scale=scale, offset=offset, vertices=target.vertices, source_size=source_size, source_crop=crop,
                     resolution=args.resolution, yaw_deg=args.yaw, pitch_deg=args.pitch)
    fixed_camera = None
    if args.camera_from_report is not None:
        camera_doc = json.loads(args.camera_from_report.read_text(encoding="utf-8"))
        fixed_camera = camera_doc.get("camera")
        if not isinstance(fixed_camera, dict):
            raise ValueError("--camera-from-report must point to a report with a camera object")
        if int(fixed_camera.get("resolution", -1)) != int(args.resolution):
            raise ValueError("baseline camera resolution does not match --resolution")
    args.out.mkdir(parents=True)
    fit_history = []
    fit_3d_history = []
    corrective_history = []
    if args.fit_3d_steps:
        if args.fit_3d_steps < 1:
            raise ValueError("--fit-3d-steps must be positive when supplied")
        if args.fit_3d_max_influences < 1:
            raise ValueError("--fit-3d-max-influences must be positive")
        # The 3-D sequence solver is the only authority in this lane. It sees
        # all move and idle frames, but never source pixels or the render
        # camera. Sparsify explicitly before optimization so an embedded Meshy
        # skin cannot exceed the declared influence budget silently.
        current_max_influences = int((weights > 1e-8).sum(axis=1).max())
        if current_max_influences > args.fit_3d_max_influences:
            weights = sparsify_weights(weights, max_influences=args.fit_3d_max_influences)
        all_worlds_for_fit = np.concatenate([worlds for _, worlds in fit_frames], axis=0)
        transforms_3d = torch.as_tensor(
            all_worlds_for_fit @ target.inverse_bind[None], dtype=torch.float32, device="cuda"
        )
        articulation_regions, articulation_targets, articulation_children = _articulation_fit_inputs(
            target.vertices, bind_world, np.asarray(target.parents, dtype=np.int64),
            target.inverse_bind, all_worlds_for_fit,
        )
        vertex_motion_targets, vertex_motion_confidence, vertex_motion_children = _vertex_articulation_fit_inputs(
            target.vertices, bind_world, np.asarray(target.parents, dtype=np.int64),
            target.inverse_bind, all_worlds_for_fit,
        )
        if args.fit_3d_init != "embedded":
            geometric_init = np.zeros_like(weights, dtype=np.float64)
            geometric_init[np.arange(len(geometric_init)), np.asarray(vertex_motion_children, dtype=np.int64)] = 1.0
            if args.fit_3d_init == "blend":
                geometric_share = float(args.fit_3d_init_blend)
                weights = sparsify_weights((1.0 - geometric_share) * weights + geometric_share * geometric_init,
                                           max_influences=args.fit_3d_max_influences)
            else:
                weights = geometric_init
        fit_3d_weights, fit_3d_history = optimize_sequence_weights_3d(
            target.vertices,
            target.triangles,
            weights,
            transforms_3d,
            max_influences=args.fit_3d_max_influences,
            steps=args.fit_3d_steps,
            prior_weight=args.fit_3d_prior_weight,
            smoothness_weight=args.fit_3d_smoothness_weight,
            motion_weight=args.fit_3d_motion_weight,
            motion_floor=args.fit_3d_motion_floor,
            max_total_variation=args.fit_3d_max_total_variation,
            articulation_regions=articulation_regions,
            articulation_targets=articulation_targets,
            articulation_weight=args.fit_3d_articulation_weight,
            vertex_motion_targets=vertex_motion_targets,
            vertex_motion_confidence=vertex_motion_confidence,
            vertex_motion_weight=args.fit_3d_vertex_motion_weight,
        )
        weights = fit_3d_weights
    if args.fit_weights_steps:
        if args.fit_weights_steps < 1:
            raise ValueError("--fit-weights-steps must be positive when supplied")
        all_paths = [Path(path) for key in sequence_keys for path in by_key[key]["frames"]]
        target_tensors = source_images(all_paths, crop, args.resolution)
        all_worlds = np.concatenate([worlds for _, worlds in all_frames], axis=0)
        transforms = torch.as_tensor(all_worlds @ target.inverse_bind[None], dtype=torch.float32, device="cuda")
        # Mesh edges provide a mild volume/continuity prior, while the image
        # objective remains the authority for silhouette and chroma.
        tri = np.asarray(target.triangles, dtype=np.int64)
        edge_pairs = np.unique(np.sort(np.concatenate((tri[:, :2], tri[:, 1:], tri[:, [0, 2]])), axis=1), axis=0)
        edge_lengths = np.linalg.norm(target.vertices[edge_pairs[:, 0]] - target.vertices[edge_pairs[:, 1]], axis=1)
        with cascade_batch_lock(REPO):
            renderer = SkinImageRenderer(target.triangles, target.uvs, target.albedo, camera, args.resolution)
            weights, fit_history = optimize_mocap_weights(
                target.vertices, weights, transforms, renderer, target_tensors,
                max_influences=args.fit_max_influences, steps=args.fit_weights_steps,
                edge_pairs=edge_pairs, edge_lengths=edge_lengths,
            )
        validate_weights(weights, max_influences=args.fit_max_influences)
    # Record a camera-free whole-sequence deformation diagnostic for the
    # selected correspondence and final weight field.  This is deliberately a
    # report metric, not a promotion score: it cannot establish sprite
    # fidelity or motion quality.
    with cascade_batch_lock(REPO):
        selected_surface_strain = _sequence_surface_strain(
            target.vertices, target.triangles, weights, target.inverse_bind, all_frames
        )
        fit_surface_strain = _sequence_surface_strain(
            target.vertices, target.triangles, weights, target.inverse_bind, fit_frames
        )
        validation_surface_strain = (
            _sequence_surface_strain(
                target.vertices, target.triangles, weights, target.inverse_bind, validation_frames
            )
            if validation_frames else None
        )
        motion_retention = _sequence_motion_retention(
            target.vertices, initial_weights_for_sequence, weights,
            target.inverse_bind, all_frames, floor=args.fit_3d_motion_floor,
        )
        validation_motion_retention = (
            _sequence_motion_retention(
                target.vertices, initial_weights_for_sequence, weights,
                target.inverse_bind, validation_frames, floor=args.fit_3d_motion_floor,
            )
            if validation_frames else None
        )
        articulation_retention = _sequence_articulation_retention(
            target.vertices, list(target.names), np.asarray(target.parents, dtype=np.int64),
            bind_world, target.inverse_bind, weights, all_frames,
            floor=args.fit_3d_motion_floor,
        )
        fit_articulation_retention = _sequence_articulation_retention(
            target.vertices, list(target.names), np.asarray(target.parents, dtype=np.int64),
            bind_world, target.inverse_bind, weights, fit_frames,
            floor=args.fit_3d_motion_floor,
        )
        validation_articulation_retention = (
            _sequence_articulation_retention(
                target.vertices, list(target.names), np.asarray(target.parents, dtype=np.int64),
                bind_world, target.inverse_bind, weights, validation_frames,
                floor=args.fit_3d_motion_floor,
            )
            if validation_frames else None
        )
    weight_shift = np.abs(np.asarray(weights, dtype=np.float64) - initial_weights_for_sequence).sum(axis=1)
    # Camera registration starts from the bind surface, but motion can carry
    # claws or root travel outside that box. Envelope all solved frames before
    # rasterization so clipping cannot masquerade as a skinning failure.
    all_worlds = np.concatenate([worlds for _, worlds in all_frames], axis=0)
    transforms_preview = torch.as_tensor(all_worlds @ target.inverse_bind[None], dtype=torch.float32, device="cuda")
    with cascade_batch_lock(REPO), torch.no_grad():
        posed_preview = dual_quaternion_skin(
                torch.as_tensor(target.vertices, dtype=torch.float32, device="cuda"),
                torch.as_tensor(weights, dtype=torch.float32, device="cuda"),
                transforms_preview,
            ).detach().cpu().numpy()
    pose_corrections = np.zeros_like(posed_preview)
    if args.pose_corrective_steps:
        if args.pose_corrective_steps < 1:
            raise ValueError("--pose-corrective-steps must be positive when supplied")
        pose_corrections, corrective_history = pose_corrective_residuals_3d(
            target.vertices,
            posed_preview,
            target.triangles,
            weights,
            all_worlds @ target.inverse_bind[None],
            steps=args.pose_corrective_steps,
            strength=args.pose_corrective_strength,
        )
        posed_preview = posed_preview + pose_corrections
    camera = fixed_camera if fixed_camera is not None else envelope_camera(
        camera, basis, posed_preview, _target_bbox(alpha[..., 0]), args.resolution
    )
    frames = []
    frame_cursor = 0
    image_iou: list[float] = []
    image_alpha_l1: list[float] = []
    image_compactness: list[float] = []
    image_validation_by_key: dict[str, dict[str, float]] = {}
    for key, worlds in all_frames:
        source_tensor, source_alpha_tensor, _ = source_images(
            [Path(p) for p in by_key[key]["frames"]], crop, args.resolution
        )
        source = source_tensor.detach().cpu().numpy()
        source_alpha = source_alpha_tensor.detach().cpu().numpy()[..., 0]
        count = len(worlds)
        prediction, prediction_alpha = render(
            target.vertices, weights, worlds, target.inverse_bind, target.triangles,
            target.uvs, target.albedo, camera,
            correction=pose_corrections[frame_cursor:frame_cursor + count],
            return_alpha=True,
        )
        frame_cursor += count
        pred_alpha = np.asarray(prediction_alpha)[..., 0]
        intersection = (pred_alpha * source_alpha).sum(axis=(1, 2))
        union = (pred_alpha + source_alpha - pred_alpha * source_alpha).sum(axis=(1, 2))
        image_iou.extend((intersection / np.maximum(union, 1e-8)).tolist())
        image_alpha_l1.extend(np.abs(pred_alpha - source_alpha).mean(axis=(1, 2)).tolist())
        image_compactness.extend(_silhouette_compactness(pred_alpha).tolist())
        key_iou = intersection / np.maximum(union, 1e-8)
        key_l1 = np.abs(pred_alpha - source_alpha).mean(axis=(1, 2))
        image_validation_by_key[key] = {
            "meanSilhouetteIou": float(np.mean(key_iou)),
            "p05SilhouetteIou": float(np.quantile(key_iou, 0.05)),
            "meanAlphaL1": float(np.mean(key_l1)),
            "meanSilhouetteCompactness": float(np.mean(_silhouette_compactness(pred_alpha))),
            "frames": float(count),
            "heldOut": bool(key in validation_key_set),
        }
        for index, (left, right) in enumerate(zip(source, prediction)):
            panel = Image.new("RGB", (args.resolution * 2, args.resolution + 28), (10, 10, 14)); draw = ImageDraw.Draw(panel)
            draw.text((4, 4), f"Mocap bones {key} f{index:02d} y{args.yaw:g} p{args.pitch:g}", fill="white")
            panel.paste(Image.fromarray(np.uint8(np.clip(left, 0, 1) * 255)), (0, 28))
            panel.paste(Image.fromarray(np.uint8(np.clip(right, 0, 1) * 255)), (args.resolution, 28))
            draw.text((4, 17), "source", fill=(190, 190, 205)); draw.text((args.resolution + 4, 17), "mocap skin", fill=(190, 190, 205)); frames.append(panel)
    frames[0].save(args.out / "preview.gif", save_all=True, append_images=frames[1:], duration=85, loop=0)
    sheet = Image.new("RGB", (args.resolution * 2, (args.resolution + 28) * min(8, len(frames))))
    for index, frame in enumerate(frames[:8]): sheet.paste(frame, (0, index * (args.resolution + 28)))
    sheet.save(args.out / "contact.png")
    proof = ("diagnostic capture-position retarget onto the owned Behemoth skeleton "
             f"with {args.weight_policy} weights and dual-quaternion skinning for an unrigged M7 surface; generated artifact only"
             if unrigged_fallback else
             "diagnostic capture-position retarget onto T2 Smart Rig; generated artifact only")
    weight_policy = args.weight_policy if unrigged_fallback else "mesh_embedded"
    motion_diagnostics = {}
    frame_cursor = 0
    for key, worlds in all_frames:
        count = len(worlds)
        sequence = posed_preview[frame_cursor:frame_cursor + count]
        projected = sequence @ basis[:2].T
        low, high = projected.min(axis=1), projected.max(axis=1)
        bbox_center = 0.5 * (low + high)
        displacement = np.linalg.norm(sequence - sequence[0:1], axis=2)
        motion_diagnostics[key] = {
            "frames": count,
            "meanVertexDisplacementMax": float(displacement.mean(axis=1).max()),
            "maxVertexDisplacement": float(displacement.max()),
            "maxProjectedBboxCenterDelta": float(np.linalg.norm(bbox_center - bbox_center[0:1], axis=1).max()),
            "maxProjectedBboxSpanDelta": float(np.linalg.norm((high - low) - (high[0] - low[0]), axis=1).max()),
        }
        frame_cursor += count
    initialization_provenance = (
        "embedded_skin"
        if not unrigged_fallback else
        f"geometric_{args.weight_policy}"
    )
    weights_sidecar = args.out / "weights.npz"
    np.savez_compressed(
        weights_sidecar,
        weights=np.asarray(weights, dtype=np.float32),
        names=np.asarray([str(name) for name in target.names]),
        candidate=np.asarray(str(candidate)),
        initialization=np.asarray(initialization_provenance),
    )
    optimized_glb = args.out / f"{candidate.stem}.autorig.glb"
    target_rest_local = rest_local_matrices(bind_world, np.asarray(target.parents, dtype=np.int64))
    write_skinned_glb(
        optimized_glb,
        names=[str(name) for name in target.names],
        parents=np.asarray(target.parents, dtype=np.int64),
        rest_local_rotation=target_rest_local[:, :3, :3],
        rest_local_translation=target_rest_local[:, :3, 3],
        inverse_bind=np.asarray(target.inverse_bind, dtype=np.float64),
        vertices=np.asarray(target.vertices, dtype=np.float64),
        triangles=np.asarray(target.triangles, dtype=np.int32),
        uvs=np.asarray(target.uvs, dtype=np.float64),
        albedo=np.asarray(target.albedo),
        weights=np.asarray(weights, dtype=np.float64),
    )
    # Promotion must inspect the serialized delivery, not only the in-memory
    # optimizer state.  Float32 GLB quantization is allowed within the explicit
    # tolerance; stale, reordered, or differently deformed exports fail closed.
    loaded_export = load_bind_skeleton(optimized_glb)
    if list(loaded_export.names) != [str(name) for name in target.names]:
        raise ValueError("optimized GLB changed joint order during export")
    loaded_weights = dense_weights(loaded_export)
    loaded_world = np.asarray(loaded_export.rest_world, dtype=np.float64)
    export_bind_error = float(np.max(np.abs(np.linalg.inv(np.asarray(loaded_export.inverse_bind)) - bind_world)))
    export_vertex_error = float(np.max(np.linalg.norm(np.asarray(loaded_export.vertices) - np.asarray(target.vertices), axis=1)))
    export_weight_error = float(np.max(np.abs(loaded_weights - np.asarray(weights, dtype=np.float64))))
    sample_worlds = np.concatenate([worlds[: min(len(worlds), 3)] for _, worlds in all_frames], axis=0)
    export_transforms = torch.as_tensor(sample_worlds @ np.asarray(loaded_export.inverse_bind)[None], dtype=torch.float32, device="cuda")
    with torch.no_grad():
        export_posed = dual_quaternion_skin(
            torch.as_tensor(np.asarray(loaded_export.vertices), dtype=torch.float32, device="cuda"),
            torch.as_tensor(loaded_weights, dtype=torch.float32, device="cuda"),
            export_transforms,
        ).detach().cpu().numpy()
        working_posed = dual_quaternion_skin(
            torch.as_tensor(np.asarray(target.vertices), dtype=torch.float32, device="cuda"),
            torch.as_tensor(np.asarray(weights), dtype=torch.float32, device="cuda"),
            torch.as_tensor(sample_worlds @ np.asarray(target.inverse_bind)[None], dtype=torch.float32, device="cuda"),
        ).detach().cpu().numpy()
    export_pose_error = float(np.max(np.linalg.norm(export_posed - working_posed, axis=2)))
    export_validation = {
        "exists": bool(optimized_glb.is_file()),
        "jointCount": int(len(loaded_export.names)),
        "bindWorldMaxError": export_bind_error,
        "vertexMaxError": export_vertex_error,
        "weightMaxError": export_weight_error,
        "samplePoseMaxError": export_pose_error,
        "sampleFrameCount": int(len(sample_worlds)),
        "loadedRestWorldFinite": bool(np.isfinite(loaded_world).all()),
        "passed": bool(
            optimized_glb.is_file()
            and np.isfinite(loaded_world).all()
            and export_bind_error <= 2e-4
            and export_vertex_error <= 2e-4
            and export_weight_error <= 2e-4
            and export_pose_error <= 4e-4
        ),
    }
    if not export_validation["passed"]:
        raise ValueError(f"serialized optimized GLB failed export validation: {export_validation}")
    topology_metrics = _sequence_topology_metrics(target.vertices, target.triangles, posed_preview)
    report = {"proof": proof, "candidate": str(candidate), "candidateMode": args.candidate_mode,
              "candidateHasSkin": candidate_has_skin, "initializationProvenance": initialization_provenance,
              "weightsSidecar": str(weights_sidecar), "optimizedGlb": str(optimized_glb),
              "unriggedFallback": unrigged_fallback,
              "boneOwner": "h3_behemoth_owned_mocap_skeleton", "weightPolicy": weight_policy,
              "fitPolicy": fit_objective if unrigged_fallback else "mesh_embedded",
              "fitPolicyAlias": args.fit_policy if args.fit_policy == "surface_pca" else None,
              "fitRest": args.fit_rest if unrigged_fallback else "mesh_embedded",
              "deformationPolicy": args.skin_mode + "_skinning", "mappedJointCount": len(mapped),
              "retargetPolicy": args.retarget_policy,
              "clipKeys": list(sequence_keys),
              "heldTargetJoints": [
                  str(name) for name in target.names
                  if any(fnmatchcase(str(name).lower(), pattern) for pattern in hold_patterns)
              ],
              "swappedArmMotion": bool(args.swap_arm_motion),
              "autoSwapArm": bool(args.auto_swap_arm),
              "selectedArmCorrespondence": "swapped" if selected_swap_arm else "default",
              "armCorrespondenceStrain": strain_candidates,
              "selectedSurfaceStrain": selected_surface_strain,
              "fitClipKeys": list(fit_keys),
              "validationClipKeys": list(validation_keys),
              "fitSurfaceStrain": fit_surface_strain,
              "validationSurfaceStrain": validation_surface_strain,
              "topologyMetrics": topology_metrics,
              "motionRetention": motion_retention,
              "validationMotionRetention": validation_motion_retention,
              "articulationRetention": articulation_retention,
              "fitArticulationRetention": fit_articulation_retention,
              "validationArticulationRetention": validation_articulation_retention,
              "exportValidation": export_validation,
              "weightFieldChange": {
                  "meanTotalVariation": float(np.mean(weight_shift)),
                  "p95TotalVariation": float(np.quantile(weight_shift, 0.95)),
                  "maxTotalVariation": float(np.max(weight_shift)),
              },
              "motionFrame0IsBind": motion_frame0_is_bind,
              "clipFrame0WorldError": clip_frame0_world_error,
              "retargetDirectionError": {
                  key: {"meanRad": float(value.get("targetDirectionErrorMeanRad", 0.0)),
                        "maxRad": float(value.get("targetDirectionErrorMaxRad", 0.0)),
                        "basis": value.get("targetDirectionErrorBasis", "absolute_target_direction")}
                  for key, value in motions.items()
              },
              "unmappedTargetJoints": [name for i, name in enumerate(target.names) if i not in mapped],
              "idleBindWorldMaxError": idle_bind_world_error,
              "cameraSource": "baseline_report" if fixed_camera is not None else "auto_envelope",
              "camera": camera,
              "motionDiagnostics": motion_diagnostics,
              "imageValidation": {
                  "meanSilhouetteIou": float(np.mean(image_iou)) if image_iou else 0.0,
                  "p05SilhouetteIou": float(np.quantile(image_iou, 0.05)) if image_iou else 0.0,
                  "meanAlphaL1": float(np.mean(image_alpha_l1)) if image_alpha_l1 else 1.0,
                  "meanSilhouetteCompactness": float(np.mean(image_compactness)) if image_compactness else 0.0,
                  "p95SilhouetteCompactness": float(np.quantile(image_compactness, 0.95)) if image_compactness else 0.0,
                  "frames": len(image_iou),
                  "role": "secondary_matched_view_validation",
              },
              "imageValidationByClip": image_validation_by_key,
              "capsuleConfig": {"radiusScale": args.capsule_radius_scale,
                                "maxInfluences": args.capsule_max_influences,
                                "torsoBias": args.capsule_torso_bias,
                                "torsoRadiusScale": args.capsule_torso_radius_scale,
                                "terminalRadiusScale": args.capsule_terminal_radius_scale,
                                "torsoCore": args.capsule_torso_core,
                                "torsoCoreBlend": args.capsule_torso_core_blend},
              "geodesic3d": geodesic_diagnostics,
              "sequenceFit3d": {"method": "local_global_arap" if args.fit_3d_steps else "disabled",
                                "steps": args.fit_3d_steps,
                                "initialization": args.fit_3d_init,
                                "initializationGeometricShare": args.fit_3d_init_blend,
                                "maxInfluences": args.fit_3d_max_influences,
                                "priorWeight": args.fit_3d_prior_weight,
                                "smoothnessWeight": args.fit_3d_smoothness_weight,
                                "motionWeight": args.fit_3d_motion_weight,
                                "motionFloor": args.fit_3d_motion_floor,
                                "articulationWeight": args.fit_3d_articulation_weight,
                                "articulationRegionJointIndices": articulation_children if args.fit_3d_steps else [],
                                "vertexMotionWeight": args.fit_3d_vertex_motion_weight,
                                "vertexMotionTargetJointIndices": vertex_motion_children if args.fit_3d_steps else [],
                                "maxTotalVariation": args.fit_3d_max_total_variation,
                                "history": fit_3d_history},
              "poseCorrective3d": {"steps": args.pose_corrective_steps,
                                   "strength": args.pose_corrective_strength,
                                   "history": corrective_history},
              "weightFit": {"steps": args.fit_weights_steps, "maxInfluences": args.fit_max_influences,
                             "history": fit_history}}
    (args.out / "report.json").write_text(json.dumps(report, indent=2,
        default=lambda value: value.tolist() if isinstance(value, np.ndarray) else float(value)) + "\n", encoding="utf-8")
    print(args.out / "preview.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
