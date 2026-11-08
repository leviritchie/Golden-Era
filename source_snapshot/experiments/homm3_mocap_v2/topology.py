"""Skeleton graph tensors in the vendor pad layout."""
from __future__ import annotations

import numpy as np

from paths import MAX_JOINTS


def ancestor_mask(parents: np.ndarray, joint_count: int) -> np.ndarray:
    mask = np.zeros((MAX_JOINTS, MAX_JOINTS), dtype=np.bool_)
    for index in range(joint_count):
        mask[index, index] = True
        parent = int(parents[index])
        seen = {index}
        while parent != -1:
            if parent in seen:
                raise ValueError(f"parent cycle at joint {parent}")
            seen.add(parent)
            mask[index, parent] = True
            parent = int(parents[parent])
    return mask


def pad_joints(values: np.ndarray, *, fill: float | int | bool, width: int | None = None) -> np.ndarray:
    if values.ndim == 1:
        out = np.full((MAX_JOINTS,), fill, dtype=values.dtype)
        out[: values.shape[0]] = values
        return out
    if values.ndim == 2:
        channels = values.shape[1] if width is None else width
        out = np.full((MAX_JOINTS, channels), fill, dtype=values.dtype)
        out[: values.shape[0], : values.shape[1]] = values
        return out
    raise ValueError(f"unsupported pad rank {values.ndim}")


def identity_rot6d(joint_count: int) -> np.ndarray:
    """Vendor BVH rest is identity local rotation; 6D is the first two rows of I."""
    values = np.zeros((int(joint_count), 6), dtype=np.float32)
    values[:, 0] = 1.0
    values[:, 4] = 1.0
    return values


def local_offsets(rest_world: np.ndarray, parents: np.ndarray) -> np.ndarray:
    offsets = np.zeros_like(rest_world)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            offsets[index] = rest_world[index]
        else:
            offsets[index] = rest_world[index] - rest_world[int(parent)]
    return offsets
