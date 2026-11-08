"""Occupancy-lane repairs for sprite crossovers (no part labels).

A DEF plate stores one occupancy bit per pixel. When two body parts occupy
the same plate pixels, IoU is already satisfied if any bone covers them.
These helpers:

- mark pixels where two bones both have high skinning weight (occupancy
  abstains; chroma/depth still score);
- keep a distal bone's identity when a 2D blob is a merge of earlier unique
  regions, instead of re-attributing by torso influence;
- hold a distal bone when its unique visible region vanished and nothing
  moved it this frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


import numpy as np


@dataclass(frozen=True)
class OccupancyLaneMaps:
    """Per-pixel unique vs ambiguous skinning from one pose."""

    bone_names: tuple[str, ...]
    ambiguous: np.ndarray
    unique: dict[str, np.ndarray]


def occupancy_lane_maps(
    weight_maps: Mapping[str, np.ndarray],
    *,
    min_weight: float,
    ambiguous_ratio: float,
) -> OccupancyLaneMaps:
    """Build unique/ambiguous masks from per-bone accumulated skin weights."""
    min_w = float(min_weight)
    ratio = float(ambiguous_ratio)
    if not math.isfinite(min_w) or min_w <= 0.0:
        raise ValueError("min_weight must be finite and positive")
    if not math.isfinite(ratio) or ratio <= 0.0 or ratio > 1.0:
        raise ValueError("ambiguous_ratio must be in (0, 1]")
    names = tuple(str(name) for name in weight_maps)
    if not names:
        raise ValueError("weight_maps cannot be empty")
    stacked = np.stack(
        [np.asarray(weight_maps[name], dtype=np.float64) for name in names],
        axis=0,
    )
    if stacked.ndim != 3:
        raise ValueError("each bone weight map must be 2D")
    if not np.isfinite(stacked).all():
        raise ValueError("bone weight maps must be finite")
    top1_index = np.argmax(stacked, axis=0)
    top1_weight = np.take_along_axis(stacked, top1_index[None, ...], axis=0)[0]
    without_top1 = stacked.copy()
    np.put_along_axis(without_top1, top1_index[None, ...], -np.inf, axis=0)
    top2_weight = np.max(without_top1, axis=0)
    occupied = top1_weight >= min_w
    second = np.isfinite(top2_weight) & (top2_weight > 0.0)
    ambiguous = occupied & second & (top2_weight >= ratio * top1_weight)
    unique = {
        name: occupied & ~ambiguous & (top1_index == index)
        for index, name in enumerate(names)
    }
    return OccupancyLaneMaps(bone_names=names, ambiguous=ambiguous, unique=unique)


def sprite_visible_unique(
    unique_masks: Mapping[str, np.ndarray],
    sprite_mask: np.ndarray,
) -> dict[str, np.ndarray]:
    """Keep unique skinning only on sprite-occupied pixels."""
    sprite = np.asarray(sprite_mask, dtype=bool)
    if sprite.ndim != 2:
        raise ValueError("sprite_mask must be 2D")
    visible: dict[str, np.ndarray] = {}
    for name, mask in unique_masks.items():
        unique = np.asarray(mask, dtype=bool)
        if unique.shape != sprite.shape:
            raise ValueError("unique mask shape must match the sprite mask")
        visible[str(name)] = unique & sprite
    return visible


def persist_blob_bone(
    blob_mask: np.ndarray,
    unique_masks: Mapping[str, np.ndarray],
    *,
    node_depth: Callable[[str], int],
    min_overlap: int,
) -> str | None:
    """Name a blob from previous unique regions; merged blobs keep the distal bone.

    Returns None when the blob does not overlap any stored unique region so the
    caller can fall back to skinning influence.
    """
    if int(min_overlap) < 1:
        raise ValueError("min_overlap must be at least 1")
    blob = np.asarray(blob_mask, dtype=bool)
    if blob.ndim != 2:
        raise ValueError("blob_mask must be 2D")
    overlaps: list[tuple[str, int, int]] = []
    for name, unique in unique_masks.items():
        region = np.asarray(unique, dtype=bool)
        if region.shape != blob.shape:
            raise ValueError("unique mask shape must match the blob mask")
        area = int(np.count_nonzero(blob & region))
        if area >= int(min_overlap):
            overlaps.append((str(name), area, int(node_depth(str(name)))))
    if not overlaps:
        return None
    if len(overlaps) == 1:
        return overlaps[0][0]
    return max(overlaps, key=lambda item: (item[2], item[1]))[0]


def vanished_unique_bones(
    previous_unique: Mapping[str, np.ndarray],
    current_unique: Mapping[str, np.ndarray],
    *,
    min_area: int,
    vanish_frac: float,
    min_bone_depth: int,
    node_depth: Callable[[str], int],
    exclude: Sequence[str] = (),
) -> tuple[str, ...]:
    """Bones whose unique visible region collapsed and were not moved this frame."""
    if int(min_area) < 1:
        raise ValueError("min_area must be at least 1")
    frac = float(vanish_frac)
    if not math.isfinite(frac) or frac <= 0.0 or frac > 1.0:
        raise ValueError("vanish_frac must be in (0, 1]")
    if int(min_bone_depth) < 0:
        raise ValueError("min_bone_depth must be non-negative")
    skipped = {str(name) for name in exclude}
    held: list[str] = []
    for name, previous in previous_unique.items():
        bone = str(name)
        if bone in skipped:
            continue
        if int(node_depth(bone)) < int(min_bone_depth):
            continue
        previous_area = int(np.count_nonzero(np.asarray(previous, dtype=bool)))
        if previous_area < int(min_area):
            continue
        current = current_unique.get(bone)
        current_area = (
            0 if current is None else int(np.count_nonzero(np.asarray(current, dtype=bool)))
        )
        if current_area < int(min_area) and current_area < frac * previous_area:
            held.append(bone)
    return tuple(held)
