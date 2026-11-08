"""Truthful motion metrics for MoCap V2 diagnosis.

Bind-pose offset is pose displacement, not motion. Root joint 0 is replaced with
the reference after video2pose (`static_pos_joint_mask`), so reported root travel
of zero does not prove the source lacked translation. Evaluate root-relative
articulation. Rotations use SO(3) geodesic angles, not 6D-versus-identity.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from position_transfer import bind_extent, kabsch_rotation


ROOT_POLICY = "static_pos_joint_mask_index0_equals_reference"
ROOT_TRAVEL_INTERPRETATION = "zero_does_not_prove_absent_source_movement"
POSE_DISPLACEMENT_IS_NOT_MOTION = True

# Negative-control thresholds are fractions of bind extent or radians.
STATIONARY_EXCURSION_FRACTION = 0.01
ARTICULATION_FRACTION = 0.05
RIGID_DOMINANCE_RATIO = 4.0
WHOLE_BODY_ROTATION_RAD = 0.15


def root_relative_positions(positions: np.ndarray) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float64)
    if values.ndim != 3 or values.shape[-1] != 3:
        raise ValueError(f"positions must be [T,J,3], got {values.shape}")
    if not np.isfinite(values).all():
        raise ValueError("positions contain non-finite values")
    return values - values[:, 0:1, :]


def temporal_joint_excursion(positions: np.ndarray) -> dict[str, float]:
    """Per-joint path length and range over time. Not distance from bind."""
    values = np.asarray(positions, dtype=np.float64)
    if values.ndim != 3 or values.shape[-1] != 3:
        raise ValueError(f"positions must be [T,J,3], got {values.shape}")
    if values.shape[0] < 1:
        raise ValueError("positions have no frames")
    span = values.max(axis=0) - values.min(axis=0)
    range_per_joint = np.linalg.norm(span, axis=-1)
    if values.shape[0] < 2:
        f2f = np.zeros((0, values.shape[1]), dtype=np.float64)
        path = np.zeros((values.shape[1],), dtype=np.float64)
        f2f_max = 0.0
        f2f_mean = 0.0
    else:
        f2f = np.linalg.norm(np.diff(values, axis=0), axis=-1)
        path = f2f.sum(axis=0)
        f2f_max = float(f2f.max())
        f2f_mean = float(f2f.mean())
    return {
        "frameCount": int(values.shape[0]),
        "jointCount": int(values.shape[1]),
        "maxJointRange": float(range_per_joint.max()),
        "meanJointRange": float(range_per_joint.mean()),
        "maxJointPath": float(path.max()),
        "meanJointPath": float(path.mean()),
        "frameToFrameMax": f2f_max,
        "frameToFrameMean": f2f_mean,
        "rootRange": float(range_per_joint[0]),
        "rootPath": float(path[0]),
    }


def pose_displacement_from_bind(
    positions: np.ndarray,
    bind: np.ndarray,
) -> dict[str, float]:
    """Distance from bind. This is pose displacement, not temporal motion."""
    pred = np.asarray(positions, dtype=np.float64)
    rest = np.asarray(bind, dtype=np.float64)
    if pred.ndim != 3 or pred.shape[2] != 3:
        raise ValueError(f"positions must be [T,J,3], got {pred.shape}")
    if rest.shape != pred.shape[1:]:
        raise ValueError("bind does not match pred joints")
    centered = pred - pred[:, 0:1, :]
    rest_centered = rest - rest[0:1]
    offset = np.linalg.norm(centered - rest_centered.reshape(1, rest.shape[0], 3), axis=-1)
    extent = bind_extent(rest)
    return {
        "metricKind": "pose_displacement_from_bind",
        "isMotion": False,
        "bindExtent": extent,
        "maxBindOffset": float(offset.max()),
        "meanBindOffset": float(offset.mean()),
        "maxBindOffsetOverExtent": float(offset.max() / extent),
    }


def parent_relative_bone_directions(
    positions: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    if values.ndim != 3 or values.shape[-1] != 3:
        raise ValueError(f"positions must be [T,J,3], got {values.shape}")
    if parent.shape != (values.shape[1],):
        raise ValueError("parents do not match joint count")
    directions = np.zeros_like(values)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            continue
        delta = values[:, index] - values[:, int(parent_index)]
        length = np.linalg.norm(delta, axis=-1, keepdims=True)
        safe = np.maximum(length, 1e-8)
        directions[:, index] = delta / safe
        directions[:, index] = np.where(length > 1e-8, directions[:, index], 0.0)
    return directions


def bone_direction_temporal_metrics(
    positions: np.ndarray,
    parents: np.ndarray,
) -> dict[str, float]:
    directions = parent_relative_bone_directions(positions, parents)
    parent = np.asarray(parents, dtype=np.int64)
    child = parent >= 0
    if not np.any(child):
        raise ValueError("skeleton has no parent-relative bones")
    bone_dirs = directions[:, child]
    if bone_dirs.shape[0] < 2:
        return {
            "frameToFrameMeanRad": 0.0,
            "frameToFrameMaxRad": 0.0,
            "totalPathMeanRad": 0.0,
            "totalPathMaxRad": 0.0,
            "fromFirstMeanRad": 0.0,
            "fromFirstMaxRad": 0.0,
            "boneCount": int(child.sum()),
        }
    dots_f2f = np.clip((bone_dirs[1:] * bone_dirs[:-1]).sum(axis=-1), -1.0, 1.0)
    f2f = np.arccos(dots_f2f)
    dots_first = np.clip((bone_dirs * bone_dirs[0:1]).sum(axis=-1), -1.0, 1.0)
    from_first = np.arccos(dots_first)
    path = f2f.sum(axis=0)
    return {
        "frameToFrameMeanRad": float(f2f.mean()),
        "frameToFrameMaxRad": float(f2f.max()),
        "totalPathMeanRad": float(path.mean()),
        "totalPathMaxRad": float(path.max()),
        "fromFirstMeanRad": float(from_first.mean()),
        "fromFirstMaxRad": float(from_first.max()),
        "boneCount": int(child.sum()),
    }


def predicted_bone_length_distortion(
    positions: np.ndarray,
    parents: np.ndarray,
    bind: np.ndarray,
) -> dict[str, float]:
    pred = np.asarray(positions, dtype=np.float64)
    rest = np.asarray(bind, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    child = np.flatnonzero(parent >= 0)
    rest_len = np.linalg.norm(rest[child] - rest[parent[child]], axis=-1)
    pred_len = np.linalg.norm(pred[:, child] - pred[:, parent[child]], axis=-1)
    denom = np.maximum(rest_len, 1e-8)
    rel = np.abs(pred_len - rest_len.reshape(1, -1)) / denom.reshape(1, -1)
    return {
        "meanAbsRelLengthError": float(rel.mean()),
        "maxAbsRelLengthError": float(rel.max()),
        "meanAbsLengthError": float(np.abs(pred_len - rest_len.reshape(1, -1)).mean()),
        "maxAbsLengthError": float(np.abs(pred_len - rest_len.reshape(1, -1)).max()),
    }


def rot6d_to_matrix(rot6d: np.ndarray) -> np.ndarray:
    """Zhou 6D → SO(3), matching vendor `rotation_6d_to_matrix` (rows are b1,b2,b3)."""
    d6 = np.asarray(rot6d, dtype=np.float64)
    if d6.shape[-1] != 6:
        raise ValueError(f"rot6d last dim must be 6, got {d6.shape}")
    a1 = d6[..., :3]
    a2 = d6[..., 3:]
    n1 = np.linalg.norm(a1, axis=-1, keepdims=True)
    if np.any(n1 <= 1e-8):
        raise ValueError("rot6d first column is degenerate")
    b1 = a1 / n1
    a2_ortho = a2 - (b1 * a2).sum(axis=-1, keepdims=True) * b1
    n2 = np.linalg.norm(a2_ortho, axis=-1, keepdims=True)
    if np.any(n2 <= 1e-8):
        raise ValueError("rot6d second column is degenerate after Gram-Schmidt")
    b2 = a2_ortho / n2
    b3 = np.cross(b1, b2)
    return np.stack((b1, b2, b3), axis=-2)


def so3_geodesic_angle(rotation_a: np.ndarray, rotation_b: np.ndarray) -> np.ndarray:
    a = np.asarray(rotation_a, dtype=np.float64)
    b = np.asarray(rotation_b, dtype=np.float64)
    if a.shape != b.shape or a.shape[-2:] != (3, 3):
        raise ValueError(f"rotations must match [...,3,3], got {a.shape} and {b.shape}")
    relative = np.matmul(np.swapaxes(a, -1, -2), b)
    cosine = np.clip((np.trace(relative, axis1=-2, axis2=-1) - 1.0) * 0.5, -1.0, 1.0)
    return np.arccos(cosine)


def rotation_temporal_metrics(rot6d: np.ndarray, *, joint_mask: np.ndarray | None = None) -> dict[str, float]:
    matrices = rot6d_to_matrix(rot6d)
    if joint_mask is not None:
        mask = np.asarray(joint_mask, dtype=bool)
        if mask.shape != (matrices.shape[-3],):
            raise ValueError("joint_mask does not match joint count")
        matrices = matrices[..., mask, :, :]
    if matrices.shape[0] < 2:
        return {
            "frameToFrameMeanRad": 0.0,
            "frameToFrameMaxRad": 0.0,
            "totalPathMeanRad": 0.0,
            "totalPathMaxRad": 0.0,
            "fromFirstMeanRad": 0.0,
            "fromFirstMaxRad": 0.0,
            "jointCount": int(matrices.shape[-3]),
        }
    f2f = so3_geodesic_angle(matrices[:-1], matrices[1:])
    from_first = so3_geodesic_angle(np.broadcast_to(matrices[0], matrices.shape), matrices)
    path = f2f.sum(axis=0)
    return {
        "frameToFrameMeanRad": float(f2f.mean()),
        "frameToFrameMaxRad": float(f2f.max()),
        "totalPathMeanRad": float(path.mean()),
        "totalPathMaxRad": float(path.max()),
        "fromFirstMeanRad": float(from_first.mean()),
        "fromFirstMaxRad": float(from_first.max()),
        "jointCount": int(matrices.shape[-3]),
    }


def rot6d_mean_abs_from_identity(rot6d: np.ndarray) -> dict[str, float]:
    """Historical 6D-vs-identity number. Not a rotation metric; kept labeled as such."""
    values = np.asarray(rot6d, dtype=np.float64)
    ident = np.zeros((6,), dtype=np.float64)
    ident[0] = 1.0
    ident[4] = 1.0
    delta = values - ident.reshape((1, 1, 6))
    return {
        "metricKind": "rot6d_mean_abs_from_identity",
        "isSo3": False,
        "doNotUseAsRotationProof": True,
        "predRot6dAbsMean": float(np.abs(delta).mean()),
        "predRot6dAbsMax": float(np.abs(delta).max()),
    }


def align_root_relative_to_first(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kabsch-align each root-relative frame to frame 0. Residual is articulation."""
    relative = root_relative_positions(positions)
    aligned = np.empty_like(relative)
    aligned[0] = relative[0]
    angles = np.zeros((relative.shape[0],), dtype=np.float64)
    identity = np.eye(3, dtype=np.float64)
    for frame in range(1, relative.shape[0]):
        rotation = kabsch_rotation(relative[frame], relative[0])
        aligned[frame] = relative[frame] @ rotation.T
        angles[frame] = float(so3_geodesic_angle(identity, rotation))
    return aligned, angles


def swing_from_bone_directions(
    positions: np.ndarray,
    parents: np.ndarray,
) -> dict[str, float]:
    """Observable swing (bone-direction change). Axial twist is not recoverable from positions."""
    bone = bone_direction_temporal_metrics(positions, parents)
    bone["twistRecoverableFromJointPositions"] = False
    bone["metricKind"] = "parent_relative_bone_direction_swing"
    return bone


def classify_motion(
    *,
    positions: np.ndarray,
    parents: np.ndarray,
    bind: np.ndarray,
) -> dict[str, Any]:
    relative = root_relative_positions(positions)
    rest = np.asarray(bind, dtype=np.float64)
    extent = bind_extent(rest)
    displacement = pose_displacement_from_bind(positions, rest)
    temporal = temporal_joint_excursion(relative)
    aligned, rigid_angles = align_root_relative_to_first(positions)
    articulation = temporal_joint_excursion(aligned)
    bones = bone_direction_temporal_metrics(relative, parents)
    lengths = predicted_bone_length_distortion(relative, parents, rest - rest[0:1])
    stationary = temporal["maxJointRange"] <= STATIONARY_EXCURSION_FRACTION * extent
    displaced_from_bind = displacement["maxBindOffset"] >= ARTICULATION_FRACTION * extent
    articulated = articulation["maxJointRange"] >= ARTICULATION_FRACTION * extent
    rigid_angle = float(np.max(rigid_angles)) if rigid_angles.size else 0.0
    rigid_dominant = (
        rigid_angle >= WHOLE_BODY_ROTATION_RAD
        and articulation["maxJointRange"] <= temporal["maxJointRange"] / RIGID_DOMINANCE_RATIO
        and not articulated
    )
    if stationary and displaced_from_bind:
        label = "stationary_non_bind_pose"
        counts_as_motion = False
        counts_as_limb_action = False
    elif stationary:
        label = "stationary_near_bind"
        counts_as_motion = False
        counts_as_limb_action = False
    elif rigid_dominant:
        label = "whole_body_rotation_fixed_articulation"
        counts_as_motion = True
        counts_as_limb_action = False
    elif articulated:
        label = "articulated_motion"
        counts_as_motion = True
        counts_as_limb_action = True
    else:
        label = "weak_or_ambiguous"
        counts_as_motion = temporal["maxJointRange"] > STATIONARY_EXCURSION_FRACTION * extent
        counts_as_limb_action = False
    return {
        "rootPolicy": ROOT_POLICY,
        "rootTravelInterpretation": ROOT_TRAVEL_INTERPRETATION,
        "poseDisplacementIsNotMotion": POSE_DISPLACEMENT_IS_NOT_MOTION,
        "bindExtent": extent,
        "poseDisplacementFromBind": displacement,
        "rootRelativeTemporal": temporal,
        "rigidAlignedArticulation": articulation,
        "wholeBodyRotationMaxRad": rigid_angle,
        "boneDirection": bones,
        "boneLengthDistortion": lengths,
        "label": label,
        "countsAsMotion": counts_as_motion,
        "countsAsLimbAction": counts_as_limb_action,
        "thresholds": {
            "stationaryExcursionFraction": STATIONARY_EXCURSION_FRACTION,
            "articulationFraction": ARTICULATION_FRACTION,
            "rigidDominanceRatio": RIGID_DOMINANCE_RATIO,
            "wholeBodyRotationRad": WHOLE_BODY_ROTATION_RAD,
        },
    }


def report_proposal_motion(
    *,
    pred_position: np.ndarray,
    pred_rot6d: np.ndarray,
    parents: np.ndarray,
    bind_model: np.ndarray,
    joint_count: int,
) -> dict[str, Any]:
    positions = np.asarray(pred_position, dtype=np.float64)[:, :joint_count]
    rotations = np.asarray(pred_rot6d, dtype=np.float64)[:, :joint_count]
    parent = np.asarray(parents, dtype=np.int64)[:joint_count]
    bind = np.asarray(bind_model, dtype=np.float64)[:joint_count]
    classified = classify_motion(positions=positions, parents=parent, bind=bind)
    classified["rotationSo3"] = rotation_temporal_metrics(rotations)
    classified["historicalRot6dVsIdentity"] = rot6d_mean_abs_from_identity(rotations)
    classified["swing"] = swing_from_bone_directions(positions, parent)
    return classified
