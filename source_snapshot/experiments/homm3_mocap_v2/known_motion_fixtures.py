"""Deterministic SmartRig FK trajectories used as stage-isolation fixtures.

These are topology tests, not proposed HoMM3 animations. Twist around a bone
axis is not recoverable from joint positions alone.
"""
from __future__ import annotations

import numpy as np

from mesh_preview import fk_world_matrices
from test_native_rotation import axis_rotation


def _children(parents) -> list[list[int]]:
    out: list[list[int]] = [[] for _ in range(len(parents))]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            out[int(parent)].append(index)
    return out


def pick_actuator(skeleton) -> int:
    parents = np.asarray(skeleton.parents)
    kids = _children(parents)
    translations = np.asarray(skeleton.rest_local_translation, dtype=np.float64)
    actuator = None
    for index, children in enumerate(kids):
        if index == 0 or not children:
            continue
        offsets = [float(np.linalg.norm(translations[child])) for child in children]
        if max(offsets) < 1e-6:
            continue
        actuator = index
        if len(children) == 1:
            break
    if actuator is None:
        raise ValueError("skeleton has no actuatable joint with a child offset")
    return int(actuator)


def rotation_moving_offset(offset: np.ndarray) -> np.ndarray:
    offset = np.asarray(offset, dtype=np.float64).reshape(3)
    best_axis = 0
    best = -1.0
    for axis in range(3):
        basis = np.zeros(3, dtype=np.float64)
        basis[axis] = 1.0
        mag = float(np.linalg.norm(np.cross(offset, basis)))
        if mag > best:
            best = mag
            best_axis = axis
    if best < 1e-8:
        raise ValueError(f"offset {offset} is degenerate for a known-motion rotation")
    return best_axis


def sine_actuator_local(skeleton, frames: int = 8, *, amplitude: float = 0.7) -> np.ndarray:
    rest = np.asarray(skeleton.rest_local_rotation, dtype=np.float64)
    if frames < 2:
        raise ValueError("known-motion fixtures need at least two frames")
    actuator = pick_actuator(skeleton)
    kids = _children(np.asarray(skeleton.parents))
    child = kids[actuator][0]
    axis = rotation_moving_offset(skeleton.rest_local_translation[child])
    out = np.repeat(rest[None, ...], int(frames), axis=0).copy()
    for index in range(int(frames)):
        angle = float(amplitude) * float(np.sin(2.0 * np.pi * index / float(frames)))
        out[index, actuator] = rest[actuator] @ axis_rotation(axis, angle)
    return out


def local_to_source_world(skeleton, local_rotation: np.ndarray) -> np.ndarray:
    local = np.asarray(local_rotation, dtype=np.float64)
    parents = np.asarray(skeleton.parents)
    worlds = []
    for frame in local:
        posed = fk_world_matrices(
            local_rotation=frame,
            local_translation=skeleton.rest_local_translation,
            parents=parents,
            root_world=skeleton.rest_world[0],
        )
        worlds.append(posed[:, :3, 3])
    return np.stack(worlds, axis=0)


def source_world_to_model_positions(
    source_world: np.ndarray,
    *,
    source_to_model: np.ndarray,
    rest_world: np.ndarray,
    global_scale: float,
) -> np.ndarray:
    source = np.asarray(source_world, dtype=np.float64)
    matrix = np.asarray(source_to_model, dtype=np.float64)
    rest = np.asarray(rest_world, dtype=np.float64)
    scale = float(global_scale)
    if source.ndim != 3 or source.shape[-1] != 3:
        raise ValueError(f"source_world must be [T,J,3], got {source.shape}")
    if matrix.shape != (3, 3):
        raise ValueError(f"source_to_model must be 3x3, got {matrix.shape}")
    if rest.shape != source.shape[1:]:
        raise ValueError("rest_world joint count does not match source_world")
    if scale <= 1e-8:
        raise ValueError("global_scale is degenerate")
    relative = source - source[:, 0:1, :]
    model = relative @ matrix.T
    return (model / scale).astype(np.float32)
