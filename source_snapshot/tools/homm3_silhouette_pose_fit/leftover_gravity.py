"""Greedy leftover gravity for one-bone visit order.

Soft 1/r^2 gravity on every bone is rejected: the torso sits near most
silhouette crumbs and would always win. Each uncovered target pixel is
assigned to at most one remaining bone:

- previous unique-region overlap first (distal identity on a merge);
- else the nearest current unique-region pixel, or the joint if that bone
  has no unique region;
- pixels farther than ``max_assign_px`` stay unassigned so a missing sword
  does not pull the chest.

Closeness then weights the assigned mass. Extra predicted coverage on a
bone's unique region is a smaller secondary pull so overextended limbs are
visited too. Occupancy-ignore pixels are not attractors.
"""
from __future__ import annotations

import math
from typing import Callable, Mapping, Sequence

import numpy as np


def closeness_weight(distance: np.ndarray, sigma_px: float) -> np.ndarray:
    """``1 / (1 + (d/sigma)^2)``. On-region leftover weights 1; far leftover fades."""
    sigma = float(sigma_px)
    if not math.isfinite(sigma) or sigma <= 0.0:
        raise ValueError("leftover_gravity_sigma_px must be positive")
    dist = np.asarray(distance, dtype=np.float64)
    finite = np.isfinite(dist)
    weight = np.zeros(dist.shape, dtype=np.float64)
    weight[finite] = 1.0 / (1.0 + (dist[finite] / sigma) ** 2)
    return weight


def leftover_mask(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    occupancy_ignore: np.ndarray | None,
    *,
    predicted_threshold: float,
) -> np.ndarray:
    """Target-occupied pixels the pose does not cover, minus occupancy-ignore."""
    target = np.asarray(target_mask, dtype=np.float32) > 0.5
    predicted = np.asarray(predicted_mask, dtype=np.float32) > float(predicted_threshold)
    if target.shape != predicted.shape:
        raise ValueError("leftover gravity target and predicted masks must match")
    leftover = target & ~predicted
    if occupancy_ignore is None:
        return leftover
    ignore = np.asarray(occupancy_ignore, dtype=np.float32) > 0.5
    if ignore.shape != leftover.shape:
        raise ValueError("leftover gravity occupancy ignore must match the silhouette")
    return leftover & ~ignore


def extra_predicted_mask(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    occupancy_ignore: np.ndarray | None,
    *,
    predicted_threshold: float,
) -> np.ndarray:
    """Predicted coverage on empty sprite, minus occupancy-ignore."""
    target = np.asarray(target_mask, dtype=np.float32) > 0.5
    predicted = np.asarray(predicted_mask, dtype=np.float32) > float(predicted_threshold)
    if target.shape != predicted.shape:
        raise ValueError("leftover gravity target and predicted masks must match")
    extra = predicted & ~target
    if occupancy_ignore is None:
        return extra
    ignore = np.asarray(occupancy_ignore, dtype=np.float32) > 0.5
    if ignore.shape != extra.shape:
        raise ValueError("leftover gravity occupancy ignore must match the silhouette")
    return extra & ~ignore


def bone_distance_map(
    unique_mask: np.ndarray,
    joint_xy: tuple[float, float],
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    """Image-plane distance to unique geometry, or to the joint if unique is empty."""
    from scipy.ndimage import distance_transform_edt

    height, width = (int(shape[0]), int(shape[1]))
    if height < 1 or width < 1:
        raise ValueError("leftover gravity distance map needs a positive raster")
    unique = np.asarray(unique_mask, dtype=bool)
    if unique.shape != (height, width):
        raise ValueError("unique mask shape must match the leftover raster")
    if np.any(unique):
        return distance_transform_edt(~unique).astype(np.float64)
    joint_x, joint_y = (float(joint_xy[0]), float(joint_xy[1]))
    if not math.isfinite(joint_x) or not math.isfinite(joint_y):
        raise ValueError("leftover gravity joint coordinates must be finite")
    rows, cols = np.indices((height, width), dtype=np.float64)
    return np.hypot(cols - joint_x, rows - joint_y)


def unique_median_depths(
    unique_masks: Mapping[str, np.ndarray],
    depth: np.ndarray,
    sprite_mask: np.ndarray,
) -> dict[str, float]:
    """Median target depth on each bone's unique sprite-visible region."""
    depth_map = np.asarray(depth, dtype=np.float64)
    sprite = np.asarray(sprite_mask, dtype=bool)
    if depth_map.shape != sprite.shape:
        raise ValueError("depth map must match the sprite mask")
    medians: dict[str, float] = {}
    for name, mask in unique_masks.items():
        unique = np.asarray(mask, dtype=bool)
        if unique.shape != sprite.shape:
            raise ValueError("unique mask shape must match the sprite mask")
        sample = unique & sprite & np.isfinite(depth_map)
        if int(np.count_nonzero(sample)) < 1:
            continue
        medians[str(name)] = float(np.median(depth_map[sample]))
    return medians


def leftover_gravity_pull(
    leftover: np.ndarray,
    *,
    remaining: Sequence[str],
    unique_distance: Mapping[str, np.ndarray],
    unique_masks: Mapping[str, np.ndarray],
    previous_unique: Mapping[str, np.ndarray] | None,
    node_depth: Callable[[str], int],
    extra: np.ndarray | None,
    extra_weight: float,
    max_assign_px: float,
    sigma_px: float,
    depth: np.ndarray | None,
    unique_median_depth: Mapping[str, float],
    depth_gate: float,
    blocked_unique: Mapping[str, np.ndarray] | None = None,
) -> dict[str, dict[str, float]]:
    """Assign leftover pixels and return per-bone pull, assigned count, extra count."""
    names = tuple(str(name) for name in remaining)
    if not names:
        raise ValueError("leftover gravity remaining set is empty")
    miss = np.asarray(leftover, dtype=bool)
    if miss.ndim != 2:
        raise ValueError("leftover mask must be 2D")
    if blocked_unique:
        for mask in blocked_unique.values():
            blocked = np.asarray(mask, dtype=bool)
            if blocked.shape != miss.shape:
                raise ValueError("blocked unique mask shape must match leftover")
            miss = miss & ~blocked
    limit = float(max_assign_px)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("leftover_gravity_max_assign_px must be positive")
    extra_scale = float(extra_weight)
    if not math.isfinite(extra_scale) or extra_scale < 0.0:
        raise ValueError("leftover_gravity_extra_weight must be finite and non-negative")
    gate = float(depth_gate)
    if not math.isfinite(gate) or gate < 0.0:
        raise ValueError("leftover_gravity_depth_gate must be finite and non-negative")
    height, width = miss.shape
    persist_depth = np.full((height, width), -1, dtype=np.int32)
    persist_id = np.full((height, width), -1, dtype=np.int32)
    if previous_unique is not None:
        for index, name in enumerate(names):
            previous = previous_unique.get(name)
            if previous is None:
                continue
            region = np.asarray(previous, dtype=bool)
            if region.shape != miss.shape:
                raise ValueError("previous unique mask shape must match leftover")
            hit = miss & region
            depth_i = int(node_depth(name))
            better = hit & (depth_i > persist_depth)
            persist_depth[better] = depth_i
            persist_id[better] = int(index)
    best_distance = np.full((height, width), np.inf, dtype=np.float64)
    nearest_id = np.full((height, width), -1, dtype=np.int32)
    depth_map = None if depth is None else np.asarray(depth, dtype=np.float64)
    if depth_map is not None and depth_map.shape != miss.shape:
        raise ValueError("leftover gravity depth map must match leftover")
    for index, name in enumerate(names):
        distance = np.asarray(unique_distance[name], dtype=np.float64)
        if distance.shape != miss.shape:
            raise ValueError("unique distance map shape must match leftover")
        gated = distance
        median = unique_median_depth.get(name)
        if gate > 0.0 and depth_map is not None and median is not None:
            ok = np.abs(depth_map - float(median)) <= gate
            gated = np.where(ok, distance, np.inf)
        closer = miss & (gated < best_distance) & (gated <= limit)
        best_distance[closer] = gated[closer]
        nearest_id[closer] = int(index)
    assignment = np.where(persist_id >= 0, persist_id, nearest_id)
    reports: dict[str, dict[str, float]] = {}
    extra_mask = None if extra is None else np.asarray(extra, dtype=bool)
    if extra_mask is not None and extra_mask.shape != miss.shape:
        raise ValueError("extra predicted mask must match leftover")
    for index, name in enumerate(names):
        assigned = miss & (assignment == int(index))
        distance = np.asarray(unique_distance[name], dtype=np.float64)
        weight = closeness_weight(distance[assigned], sigma_px) if np.any(assigned) else np.zeros((0,), dtype=np.float64)
        extra_count = 0.0
        if extra_mask is not None and extra_scale > 0.0:
            unique = np.asarray(unique_masks[name], dtype=bool)
            if unique.shape != miss.shape:
                raise ValueError("unique mask shape must match leftover")
            extra_count = float(np.count_nonzero(extra_mask & unique))
        pull = float(weight.sum()) + extra_scale * extra_count
        reports[name] = {
            "pull": pull,
            "assigned": float(np.count_nonzero(assigned)),
            "extra": extra_count,
        }
    return reports


def pick_next_gravity_bone(
    reports: Mapping[str, Mapping[str, float]],
    remaining: Sequence[str],
    *,
    fallback: Sequence[str],
    min_pull: float,
) -> str:
    """Highest leftover pull among remaining bones; fallback order if none qualify."""
    names = tuple(str(name) for name in remaining)
    if not names:
        raise ValueError("leftover gravity remaining set is empty")
    floor = float(min_pull)
    if not math.isfinite(floor) or floor < 0.0:
        raise ValueError("leftover_gravity_min_pull must be finite and non-negative")
    fallback_rank = {str(name): index for index, name in enumerate(fallback)}
    remaining_set = set(names)
    missing = [name for name in names if name not in reports]
    if missing:
        raise ValueError(f"leftover gravity reports missing remaining bones: {missing}")
    qualified = [
        name
        for name in names
        if float(reports[name]["pull"]) >= floor and float(reports[name]["pull"]) > 0.0
    ]
    if qualified:
        return max(
            qualified,
            key=lambda name: (
                float(reports[name]["pull"]),
                -int(fallback_rank.get(name, 10**9)),
            ),
        )
    for name in fallback:
        if str(name) in remaining_set:
            return str(name)
    return names[0]
