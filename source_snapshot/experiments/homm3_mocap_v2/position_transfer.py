"""Topology-driven fixed-length whole-skeleton transfer from predicted positions.

This is an explicit second diagnostic. It is not a fallback for native rotations,
not a per-species chain recipe, and not a motion-limit table.
"""
from __future__ import annotations

import numpy as np

from glb_skeleton import BindSkeleton
from mesh_preview import fk_world_matrices, rest_world_matrices, rotation_between


ACTION_TRAVEL_FRACTION = 0.05
TEMPORAL_BLEND = 0.25
TEMPORAL_PASSES = 4


def _children(parents: np.ndarray) -> list[list[int]]:
    out: list[list[int]] = [[] for _ in range(len(parents))]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            out[int(parent)].append(index)
    return out


def _as_rotation(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=np.float64)
    if values.shape[-2:] != (3, 3) or not np.isfinite(values).all():
        raise ValueError(f"rotation must be finite ...3x3, got {values.shape}")
    u, _singular, vh = np.linalg.svd(values)
    rotation = u @ vh
    det = np.linalg.det(rotation)
    if values.ndim == 2:
        if float(det) < 0:
            u = u.copy()
            u[:, -1] *= -1
            rotation = u @ vh
        return rotation
    bad = det < 0
    if np.any(bad):
        u = u.copy()
        u[bad, :, -1] *= -1
        rotation = u @ vh
    return rotation


def kabsch_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(target, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError(f"kabsch inputs must be [N,3], got {src.shape} and {dst.shape}")
    if src.shape[0] == 0:
        return np.eye(3, dtype=np.float64)
    if src.shape[0] == 1:
        return rotation_between(src[0], dst[0])
    covariance = src.T @ dst
    u, _singular, vh = np.linalg.svd(covariance)
    rotation = vh.T @ u.T
    if float(np.linalg.det(rotation)) < 0:
        vh[-1] *= -1
        rotation = vh.T @ u.T
    return _as_rotation(rotation)


def bind_extent(rest_world: np.ndarray) -> float:
    values = np.asarray(rest_world, dtype=np.float64)
    span = float(np.linalg.norm(values.max(axis=0) - values.min(axis=0)))
    if not np.isfinite(span) or span <= 1e-8:
        raise ValueError("bind extent is degenerate")
    return span


def position_action_present(
    pred_world: np.ndarray,
    rest_world: np.ndarray,
    *,
    fraction: float = ACTION_TRAVEL_FRACTION,
) -> tuple[bool, dict[str, float]]:
    pred = np.asarray(pred_world, dtype=np.float64)
    rest = np.asarray(rest_world, dtype=np.float64)
    if pred.ndim != 3 or pred.shape[2] != 3:
        raise ValueError(f"pred_world must be [T,J,3], got {pred.shape}")
    if rest.shape != pred.shape[1:]:
        raise ValueError("rest_world does not match pred joints")
    centered = pred - pred[:, 0:1, :]
    rest_centered = rest - rest[0:1]
    articulation = centered - rest_centered.reshape(1, rest.shape[0], 3)
    per_joint = np.linalg.norm(articulation, axis=-1).max(axis=0)
    root_travel = float(np.linalg.norm(pred[:, 0] - pred[0, 0], axis=-1).max())
    max_art = float(per_joint.max())
    extent = bind_extent(rest)
    threshold = fraction * extent
    return max_art >= threshold, {
        "bindExtent": extent,
        "maxArticulationTravel": max_art,
        "rootTravel": root_travel,
        "actionThreshold": threshold,
        "actionFraction": float(fraction),
    }


def _local_from_world_rotations(
    world_rot: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    local = np.zeros_like(world_rot)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            local[index] = world_rot[index]
        else:
            local[index] = world_rot[int(parent)].T @ world_rot[index]
    return local


def _smooth_local_rotations(local: np.ndarray, *, blend: float, passes: int) -> np.ndarray:
    values = np.asarray(local, dtype=np.float64)
    if values.ndim != 4 or values.shape[-2:] != (3, 3):
        raise ValueError(f"local rotations must be [T,J,3,3], got {values.shape}")
    if values.shape[0] < 3 or blend <= 0:
        return values
    out = values.copy()
    weight = float(blend)
    for _ in range(int(passes)):
        nxt = out.copy()
        for frame in range(1, out.shape[0] - 1):
            neighbor = _as_rotation(0.5 * (out[frame - 1] + out[frame + 1]))
            nxt[frame] = _as_rotation((1.0 - weight) * out[frame] + weight * neighbor)
        out = nxt
    return out


def solve_fixed_length_frame(
    *,
    pred_world: np.ndarray,
    skeleton: BindSkeleton,
) -> np.ndarray:
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    children = _children(parents)
    rest_local = np.asarray(skeleton.rest_local_translation, dtype=np.float64)
    rest_bind = rest_world_matrices(skeleton)
    pred = np.asarray(pred_world, dtype=np.float64)
    joint_count = len(parents)
    if pred.shape != (joint_count, 3) or not np.isfinite(pred).all():
        raise ValueError(f"pred_world must be finite [{joint_count},3], got {pred.shape}")
    world_rot = np.zeros((joint_count, 3, 3), dtype=np.float64)
    world_pos = np.zeros((joint_count, 3), dtype=np.float64)
    world_pos[0] = pred[0]
    for index in range(joint_count):
        if index == 0:
            carried = np.asarray(skeleton.rest_local_rotation[0], dtype=np.float64)
        else:
            parent = int(parents[index])
            carried = world_rot[parent] @ skeleton.rest_local_rotation[index]
        kids = children[index]
        if kids:
            rest_offsets = np.stack([carried @ rest_local[child] for child in kids], axis=0)
            want = np.zeros_like(rest_offsets)
            for child_i, child in enumerate(kids):
                rest_len = float(np.linalg.norm(rest_offsets[child_i]))
                if rest_len < 1e-8:
                    rest_len = float(np.linalg.norm(rest_local[child]))
                direction = pred[child] - pred[index]
                length = float(np.linalg.norm(direction))
                if length < 1e-8 or rest_len < 1e-8:
                    want[child_i] = rest_offsets[child_i]
                else:
                    want[child_i] = direction * (rest_len / length)
            world_rot[index] = kabsch_rotation(rest_offsets, want) @ carried
        else:
            world_rot[index] = carried
        for child in kids:
            world_pos[child] = world_pos[index] + world_rot[index] @ rest_local[child]
    world = np.zeros((joint_count, 4, 4), dtype=np.float64)
    world[:, :3, :3] = world_rot
    world[:, :3, 3] = world_pos
    world[:, 3, 3] = 1.0
    _ = rest_bind
    return world


def solve_fixed_length_clip(
    *,
    pred_world: np.ndarray,
    skeleton: BindSkeleton,
    temporal_blend: float = TEMPORAL_BLEND,
    temporal_passes: int = TEMPORAL_PASSES,
) -> np.ndarray:
    pred = np.asarray(pred_world, dtype=np.float64)
    if pred.ndim != 3 or pred.shape[2] != 3:
        raise ValueError(f"pred_world must be [T,J,3], got {pred.shape}")
    frames = [
        solve_fixed_length_frame(pred_world=frame, skeleton=skeleton) for frame in pred
    ]
    stacked = np.stack(frames, axis=0)
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    local = np.stack(
        [_local_from_world_rotations(frame[:, :3, :3], parents) for frame in stacked],
        axis=0,
    )
    local = _smooth_local_rotations(local, blend=temporal_blend, passes=temporal_passes)
    roots = stacked[:, 0, :3, 3]
    posed = []
    for frame_index, local_frame in enumerate(local):
        posed.append(
            fk_world_matrices(
                local_rotation=local_frame,
                local_translation=skeleton.rest_local_translation,
                parents=parents,
                root_world=roots[frame_index],
            )
        )
    return np.stack(posed, axis=0)


def transfer_residuals(
    *,
    pred_world: np.ndarray,
    posed_world: np.ndarray,
) -> dict[str, float]:
    pred = np.asarray(pred_world, dtype=np.float64)
    posed = np.asarray(posed_world, dtype=np.float64)
    if posed.ndim != 4 or posed.shape[-2:] != (4, 4):
        raise ValueError(f"posed_world must be [T,J,4,4], got {posed.shape}")
    joint_pos = posed[:, :, :3, 3]
    delta = joint_pos - pred
    lengths = np.linalg.norm(delta, axis=-1)
    root_delta = np.linalg.norm(joint_pos[:, 0] - pred[:, 0], axis=-1)
    return {
        "positionResidualMean": float(lengths.mean()),
        "positionResidualMax": float(lengths.max()),
        "rootResidualMax": float(root_delta.max()),
    }
