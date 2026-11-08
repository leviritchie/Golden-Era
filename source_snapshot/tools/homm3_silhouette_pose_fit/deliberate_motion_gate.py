"""Motion-island / branch-trajectory keep-or-hold gate.

Authority is declared source evidence (landmarks, occupancy appear/disappear,
region-scoped appearance). A rejected branch is held at its island-entry pose.
There is no fallback from a rejected trajectory to smaller independent joint
twitches. Physics smoothing is not this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from cascade_sprite_aligned_motion import (
    SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT,
    should_keep_local_pairs,
    should_keep_travel,
)

MIN_LANDMARK_IMPROVEMENT = 0.01
MIN_RENDERED_MOTION_RECALL = 0.5
MAX_TRAVEL_PER_GAIN = 250.0  # geodesic degrees per unit of 0..1 evidence gain
APPEARANCE_FLOOR = 0.0


@dataclass(frozen=True)
class MotionIsland:
    branch: str
    bones: tuple[str, ...]
    frame_start: int
    frame_end: int
    expected_direction: tuple[float, float, float] | None = None
    expected_magnitude: float = 0.0
    evidence: tuple[str, ...] = ("occupancy",)


@dataclass(frozen=True)
class BranchDecision:
    branch: str
    retained: bool
    reason: str
    geodesic_travel: float
    evidence_gain: float


def motion_islands_from_evidence(
    *,
    branch: str,
    bones: Sequence[str],
    frame_evidence: Sequence[bool],
    expected_direction: tuple[float, float, float] | None = None,
    evidence: Sequence[str] = ("occupancy",),
) -> tuple[MotionIsland, ...]:
    flags = [bool(item) for item in frame_evidence]
    if not flags:
        raise ValueError("frame_evidence cannot be empty")
    bone_names = tuple(str(name) for name in bones)
    if not bone_names:
        raise ValueError("motion island needs at least one bone")
    islands: list[MotionIsland] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            islands.append(
                MotionIsland(
                    branch=str(branch),
                    bones=bone_names,
                    frame_start=int(start),
                    frame_end=index - 1,
                    expected_direction=expected_direction,
                    evidence=tuple(evidence),
                )
            )
            start = None
    if start is not None:
        islands.append(
            MotionIsland(
                branch=str(branch),
                bones=bone_names,
                frame_start=int(start),
                frame_end=len(flags) - 1,
                expected_direction=expected_direction,
                evidence=tuple(evidence),
            )
        )
    return tuple(islands)


def hold_branch_at_entry(
    poses: Mapping[int, Mapping[str, Mapping[str, float]]],
    island: MotionIsland,
) -> dict[int, dict[str, dict[str, float]]]:
    """Copy the island-entry pose of ``island.bones`` onto every later island frame."""
    keyed = {int(frame): {str(bone): dict(axes) for bone, axes in pose.items()} for frame, pose in poses.items()}
    entry = int(island.frame_start)
    source = entry - 1 if entry >= 1 and (entry - 1) in keyed else entry
    if source not in keyed:
        raise KeyError(f"island hold source frame {source} is missing")
    for frame in range(island.frame_start, island.frame_end + 1):
        if frame not in keyed:
            raise KeyError(f"island frame {frame} is missing")
        for bone in island.bones:
            keyed[frame][bone] = dict(keyed[source].get(bone) or {"x": 0.0, "y": 0.0, "z": 0.0})
    return keyed


def geodesic_axis_angle_deg(
    current: Mapping[str, float] | None,
    held: Mapping[str, float] | None,
) -> float:
    a = [float((current or {}).get(axis, 0.0)) for axis in ("x", "y", "z")]
    b = [float((held or {}).get(axis, 0.0)) for axis in ("x", "y", "z")]
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


def branch_geodesic_travel_deg(
    poses: Mapping[int, Mapping[str, Mapping[str, float]]],
    island: MotionIsland,
) -> float:
    frames = list(range(island.frame_start, island.frame_end + 1))
    if len(frames) < 2:
        return 0.0
    total = 0.0
    for previous, current in zip(frames, frames[1:]):
        for bone in island.bones:
            total += geodesic_axis_angle_deg(
                (poses[previous] or {}).get(bone),
                (poses[current] or {}).get(bone),
            )
    return float(total)


def root_step_aligns_declared_direction(
    step: Sequence[float],
    expected_direction: Sequence[float],
    *,
    min_cosine: float = 0.25,
) -> bool:
    vector = [float(item) for item in step]
    expected = [float(item) for item in expected_direction]
    mag = math.sqrt(sum(item * item for item in vector))
    exp_mag = math.sqrt(sum(item * item for item in expected))
    if mag <= 1e-12 or exp_mag <= 1e-12:
        return False
    cosine = sum(left * right for left, right in zip(vector, expected)) / (mag * exp_mag)
    return cosine >= float(min_cosine)


def should_retain_branch_trajectory(
    *,
    current_pairs: Sequence[float],
    hold_pairs: Sequence[float],
    landmark_current: float | None,
    landmark_hold: float | None,
    regional_appearance_supports: bool,
    appearance_quality: float,
    appearance_floor: float,
    geodesic_travel_deg: float,
    rendered_or_landmark_gain: float,
    min_pair_improvement: float = SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT,
    min_landmark_improvement: float = MIN_LANDMARK_IMPROVEMENT,
) -> tuple[bool, str]:
    """Retain the complete proposed trajectory or hold it. Never scale it."""
    if float(appearance_quality) < float(appearance_floor):
        return False, "appearance_floor"
    if not should_keep_local_pairs(
        current_pairs, hold_pairs, min_improvement=min_pair_improvement
    ):
        return False, "local_pairs"
    landmark_ok = False
    if landmark_current is not None and landmark_hold is not None:
        landmark_ok = should_keep_travel(
            float(landmark_current),
            float(landmark_hold),
            min_improvement=min_landmark_improvement,
        )
    if not landmark_ok and not bool(regional_appearance_supports):
        return False, "no_landmark_or_regional_support"
    gain = float(rendered_or_landmark_gain)
    travel = float(geodesic_travel_deg)
    if gain <= 1e-12:
        return False, "no_visible_gain"
    if travel / gain > MAX_TRAVEL_PER_GAIN:
        return False, "motion_economy"
    return True, "retain"


def motion_recall(
    *,
    source_island_present: bool,
    rendered_motion: float,
    landmark_motion: float,
    min_rendered: float = MIN_RENDERED_MOTION_RECALL,
    min_landmark: float = MIN_LANDMARK_IMPROVEMENT,
) -> tuple[bool, str]:
    if not source_island_present:
        return True, "no_source_island"
    if float(rendered_motion) < float(min_rendered) and float(landmark_motion) < float(min_landmark):
        return False, "frozen_over_source_motion"
    return True, "recall_ok"


def decide_branch(
    *,
    island: MotionIsland,
    current_pairs: Sequence[float],
    hold_pairs: Sequence[float],
    poses: Mapping[int, Mapping[str, Mapping[str, float]]],
    landmark_current: float | None = None,
    landmark_hold: float | None = None,
    regional_appearance_supports: bool = False,
    appearance_quality: float = 1.0,
    rendered_or_landmark_gain: float | None = None,
    source_island_present: bool = True,
    rendered_motion: float = 0.0,
    landmark_motion: float = 0.0,
    root_step: Sequence[float] | None = None,
) -> BranchDecision:
    travel = branch_geodesic_travel_deg(poses, island)
    gain = (
        float(rendered_or_landmark_gain)
        if rendered_or_landmark_gain is not None
        else max(0.0, float(sum(current_pairs) - sum(hold_pairs)) / max(len(current_pairs), 1))
    )
    if island.expected_direction is not None and root_step is not None:
        if not root_step_aligns_declared_direction(root_step, island.expected_direction):
            return BranchDecision(island.branch, False, "root_direction", travel, gain)
    retained, reason = should_retain_branch_trajectory(
        current_pairs=current_pairs,
        hold_pairs=hold_pairs,
        landmark_current=landmark_current,
        landmark_hold=landmark_hold,
        regional_appearance_supports=regional_appearance_supports,
        appearance_quality=appearance_quality,
        appearance_floor=APPEARANCE_FLOOR,
        geodesic_travel_deg=travel,
        rendered_or_landmark_gain=gain,
    )
    if retained:
        recall_ok, recall_reason = motion_recall(
            source_island_present=source_island_present,
            rendered_motion=rendered_motion if rendered_motion else gain,
            landmark_motion=landmark_motion if landmark_motion else (landmark_current or 0.0),
        )
        if not recall_ok:
            return BranchDecision(island.branch, False, recall_reason, travel, gain)
    return BranchDecision(island.branch, retained, reason, travel, gain)
