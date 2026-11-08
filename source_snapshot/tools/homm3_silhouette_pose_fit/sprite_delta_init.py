"""Preemptive pose seed from consecutive sprite occupancy, not pose leftover.

Copying the previous 3D pose is the baseline. This module looks at pixels that
left the previous sprite and pixels that appeared on the current sprite, then
names a signed image-plane swing around the attributed joint. The solver tries
that magnitude on each local bone axis and keeps it only when the delta
neighborhood IoU improves.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from ik_silhouette_miss_keypoints import SilhouetteMissPair


def sprite_occupancy_delta(
    previous_mask: np.ndarray,
    current_mask: np.ndarray,
    *,
    threshold: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (disappeared, appeared) occupancy between two sprite frames."""
    if not math.isfinite(float(threshold)):
        raise ValueError("threshold must be finite")
    previous = np.asarray(previous_mask) > float(threshold)
    current = np.asarray(current_mask) > float(threshold)
    if previous.shape != current.shape:
        raise ValueError("previous and current sprite masks must have the same shape")
    if previous.ndim != 2:
        raise ValueError("sprite masks must be 2D")
    disappeared = previous & ~current
    appeared = current & ~previous
    return disappeared, appeared


def screen_plane_signed_deg(
    pivot_xy: tuple[float, float],
    from_xy: tuple[float, float],
    to_xy: tuple[float, float],
    *,
    min_radius_px: float,
) -> float:
    """Signed image-plane degrees that rotate ``from_xy`` onto ``to_xy``.

    PNG y grows downward. The sign is the 2D occupancy swing, not a bone-local
    axis. The caller probes +angle and -angle on each searchable axis.
    """
    min_radius = float(min_radius_px)
    if not math.isfinite(min_radius) or min_radius <= 0.0:
        raise ValueError("min_radius_px must be finite and positive")
    px, py = float(pivot_xy[0]), float(pivot_xy[1])
    from_x = float(from_xy[0]) - px
    from_y = float(from_xy[1]) - py
    to_x = float(to_xy[0]) - px
    to_y = float(to_xy[1]) - py
    from_radius = math.hypot(from_x, from_y)
    to_radius = math.hypot(to_x, to_y)
    if from_radius < min_radius or to_radius < min_radius:
        raise ValueError("sprite-delta tips are too close to the joint pivot for a stable swing")
    cross = from_x * to_y - from_y * to_x
    dot = from_x * to_x + from_y * to_y
    return math.degrees(math.atan2(cross, dot))


@dataclass(frozen=True)
class SpriteDeltaMove:
    """One attributed sprite-occupancy swing to apply before bone search."""

    bone_name: str
    angle_deg: float
    disappeared_tip: tuple[float, float]
    appeared_tip: tuple[float, float]
    pivot_xy: tuple[float, float]
    disappeared_area: int
    appeared_area: int


def sprite_delta_moves_from_pairs(
    pairs: Sequence[SilhouetteMissPair],
    *,
    joint_xy: Mapping[str, tuple[float, float]],
    bone_name_for_pair: Callable[[SilhouetteMissPair], str | None],
    min_radius_px: float,
    min_angle_deg: float,
) -> tuple[SpriteDeltaMove, ...]:
    """Convert sprite-to-sprite miss pairs into preemptive joint swings."""
    min_angle = float(min_angle_deg)
    if not math.isfinite(min_angle) or min_angle <= 0.0:
        raise ValueError("min_angle_deg must be finite and positive")
    moves: list[SpriteDeltaMove] = []
    used_bones: set[str] = set()
    for pair in pairs:
        bone_name = bone_name_for_pair(pair)
        if bone_name is None:
            continue
        name = str(bone_name)
        if name in used_bones:
            continue
        if name not in joint_xy:
            raise ValueError(f"attributed bone {name!r} has no projected joint")
        try:
            angle = screen_plane_signed_deg(
                joint_xy[name],
                pair.excess_tip,
                pair.target_tip,
                min_radius_px=float(min_radius_px),
            )
        except ValueError:
            continue
        if abs(float(angle)) < min_angle:
            continue
        used_bones.add(name)
        moves.append(
            SpriteDeltaMove(
                bone_name=name,
                angle_deg=float(angle),
                disappeared_tip=(float(pair.excess_tip[0]), float(pair.excess_tip[1])),
                appeared_tip=(float(pair.target_tip[0]), float(pair.target_tip[1])),
                pivot_xy=(float(joint_xy[name][0]), float(joint_xy[name][1])),
                disappeared_area=int(pair.excess_area),
                appeared_area=int(pair.missing_area),
            )
        )
    return tuple(moves)


def clipped_axis_targets(
    current_by_axis: Mapping[str, float],
    delta_deg: float,
    *,
    joint_limit_deg: float,
) -> tuple[tuple[str, float], ...]:
    """Absolute angles for +delta and -delta on each axis, clipped to limits."""
    limit = float(joint_limit_deg)
    delta = float(delta_deg)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    if not math.isfinite(delta):
        raise ValueError("delta_deg must be finite")
    if not current_by_axis:
        raise ValueError("current_by_axis cannot be empty")
    targets: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for axis, current in current_by_axis.items():
        name = str(axis)
        current_angle = float(current)
        for signed in (delta, -delta):
            angle = max(-limit, min(limit, current_angle + signed))
            key = (name, round(angle, 5))
            if key in seen:
                continue
            seen.add(key)
            targets.append((name, angle))
    return tuple(targets)
