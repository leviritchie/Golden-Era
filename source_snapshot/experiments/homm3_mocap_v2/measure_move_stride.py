"""Measure in-place Move-clip stride from foot travel. No Unity, no fallbacks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .glb_skeleton import load_bind_skeleton, read_glb
from .oe_motion_style_v2 import _animation, _mul, _n

FOOT_NAME_TOKENS = ("foot", "toe", "ankle", "hoof", "paw", "talons")
HAND_NAME_TOKENS = ("hand", "wrist", "finger", "thumb")
MIN_STRIDE_OVER_HEIGHT = 0.05


def _rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    q = _n(q)
    zero = np.zeros(q.shape[:-1] + (1,), dtype=q.dtype)
    qv = np.concatenate((v, zero), axis=-1)
    return _mul(_mul(q, qv), np.concatenate((-q[..., :3], q[..., 3:4]), axis=-1))[..., :3]


def _fk_positions(local_rotations: np.ndarray, translations: np.ndarray, parents: tuple[int, ...]) -> np.ndarray:
    frames, joints = local_rotations.shape[:2]
    world_rot = np.zeros_like(local_rotations)
    world_pos = np.zeros((frames, joints, 3), dtype=np.float64)
    for joint, parent in enumerate(parents):
        if parent < 0:
            world_rot[:, joint] = local_rotations[:, joint]
            world_pos[:, joint] = translations[:, joint]
            continue
        world_rot[:, joint] = _n(_mul(world_rot[:, parent], local_rotations[:, joint]))
        world_pos[:, joint] = world_pos[:, parent] + _rotate(world_rot[:, parent], translations[:, joint])
    return world_pos


def _foot_indices(names: tuple[str, ...], rest_world: np.ndarray, parents: tuple[int, ...]) -> tuple[int, ...]:
    lowered = [(index, name.lower()) for index, name in enumerate(names)]
    mount = [index for index, name in lowered
             if name.startswith("mount:") and any(token in name for token in FOOT_NAME_TOKENS)
             and not any(token in name for token in HAND_NAME_TOKENS)]
    if len(mount) >= 2:
        return tuple(mount)
    named = []
    for index, name in lowered:
        if any(token in name for token in HAND_NAME_TOKENS):
            continue
        if any(token in name for token in FOOT_NAME_TOKENS):
            named.append(index)
    if len(named) >= 2:
        return tuple(named)
    has_child = set()
    for parent in parents:
        if parent >= 0:
            has_child.add(parent)
    leaves = [index for index in range(len(names)) if index not in has_child]
    heights = rest_world[:, 1]
    cutoff = np.quantile(heights, 0.25)
    low_leaves = [index for index in leaves if heights[index] <= cutoff]
    if len(low_leaves) < 2:
        raise ValueError("Move clip has fewer than two ground-contact joints for stride")
    return tuple(low_leaves)


def measure_move_stride(path: Path) -> dict[str, Any]:
    """Return bind-space stride and clip period from an assembled Move GLB."""
    parsed = read_glb(path)
    skeleton = load_bind_skeleton(path)
    _animation_doc, times, rotations, _outputs = _animation(parsed, parsed["bin"], skeleton)
    if len(times) < 2:
        raise ValueError(f"{path}: Move clip needs at least two keys to measure stride")
    translations = np.repeat(skeleton.rest_local_translation[None, :, :], len(times), axis=0)
    worlds = _fk_positions(_n(np.asarray(rotations, float)), translations, skeleton.parents)
    feet = _foot_indices(skeleton.names, skeleton.rest_world, skeleton.parents)
    travel = worlds[:, list(feet), :]
    span_x = float(np.mean(np.ptp(travel[:, :, 0], axis=0)))
    span_z = float(np.mean(np.ptp(travel[:, :, 2], axis=0)))
    axis = "x" if span_x >= span_z else "z"
    stride = span_x if axis == "x" else span_z
    height = float(np.ptp(skeleton.rest_world[:, 1]))
    if not np.isfinite(stride) or stride <= 0:
        raise ValueError(f"{path}: measured Move stride is not a positive length")
    if height > 1e-6 and stride < MIN_STRIDE_OVER_HEIGHT * height:
        raise ValueError(
            f"{path}: measured Move stride {stride:.6f} is below {MIN_STRIDE_OVER_HEIGHT:.2f} of mesh height {height:.6f}"
        )
    cycle = float(times[-1] - times[0])
    if not np.isfinite(cycle) or cycle <= 0:
        raise ValueError(f"{path}: Move clip period is not a positive duration")
    return {
        "schema": "homm3_mocap_v2_move_stride.v1",
        "sourceGlb": str(path.resolve()),
        "strideBindUnits": stride,
        "cycleSeconds": cycle,
        "locomotionAxis": axis,
        "footJoints": [skeleton.names[index] for index in feet],
        "meshHeightBindUnits": height,
    }
