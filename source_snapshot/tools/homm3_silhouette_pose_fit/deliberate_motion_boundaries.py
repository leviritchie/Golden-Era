"""C0/C1 seam metrics and cycle-closing keys for deliberate-motion clips."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from roc_gpu_cascade_experiment import _axis_angle_quaternion_np, _quat_multiply


def axis_angle_degrees_to_quat(xyz_deg: Sequence[float]) -> np.ndarray:
    radians = np.radians(np.asarray(xyz_deg, dtype=np.float64).reshape(3))
    return _axis_angle_quaternion_np(radians)


def geodesic_quat_deg(left: np.ndarray, right: np.ndarray) -> float:
    dot = float(abs(np.dot(left, right)))
    dot = min(1.0, max(0.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def bone_delta_quat(pose: Mapping[str, Any] | None, bone: str) -> np.ndarray:
    entry = {} if pose is None else pose.get(bone) or {}
    return axis_angle_degrees_to_quat(
        (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)), float(entry.get("z", 0.0)))
    )


def pose_c0_max_deg(
    first: Mapping[str, Any],
    last: Mapping[str, Any],
    bones: Sequence[str],
) -> tuple[float, str | None]:
    worst = 0.0
    worst_bone = None
    for bone in bones:
        angle = geodesic_quat_deg(bone_delta_quat(last, bone), bone_delta_quat(first, bone))
        if angle > worst:
            worst = angle
            worst_bone = str(bone)
    return float(worst), worst_bone


def pose_c1_max_deg_per_second(
    poses: Mapping[int, Mapping[str, Any]],
    bones: Sequence[str],
    *,
    frame_duration_seconds: float,
) -> tuple[float, str | None]:
    dt = float(frame_duration_seconds)
    if dt <= 0.0:
        raise ValueError("frame_duration_seconds must be positive")
    frames = tuple(sorted(int(frame) for frame in poses))
    if len(frames) < 2:
        return 0.0, None
    first = poses[frames[0]]
    second = poses[frames[1]]
    last = poses[frames[-1]]
    penultimate = poses[frames[-2]] if len(frames) > 2 else first
    worst = 0.0
    worst_bone = None
    for bone in bones:
        start_vel = geodesic_quat_deg(bone_delta_quat(first, bone), bone_delta_quat(second, bone)) / dt
        end_vel = geodesic_quat_deg(bone_delta_quat(penultimate, bone), bone_delta_quat(last, bone)) / dt
        wrap_vel = geodesic_quat_deg(bone_delta_quat(last, bone), bone_delta_quat(first, bone)) / dt
        mismatch = max(abs(wrap_vel - start_vel), abs(wrap_vel - end_vel))
        if mismatch > worst:
            worst = mismatch
            worst_bone = str(bone)
    return float(worst), worst_bone


def bones_in_poses(poses: Mapping[int, Mapping[str, Any]]) -> tuple[str, ...]:
    names: set[str] = set()
    for pose in poses.values():
        names.update(str(name) for name in pose if not str(name).startswith("__"))
    return tuple(sorted(names))


def cycle_seam_report(
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame_duration_seconds: float,
    c0_limit_deg: float | None = None,
    c1_limit_deg_per_second: float | None = None,
) -> dict[str, Any]:
    keyed = {int(frame): pose for frame, pose in poses.items()}
    frames = tuple(sorted(keyed))
    bones = bones_in_poses(keyed)
    if len(frames) < 2:
        return {
            "sourceFrameCount": len(frames),
            "c0MaxDeg": 0.0,
            "c1MaxDegPerSecond": 0.0,
            "c0Pass": False,
            "c1Pass": False,
            "reason": "cycle_needs_at_least_two_poses",
            "worstC0Bone": None,
            "worstC1Bone": None,
        }
    c0, c0_bone = pose_c0_max_deg(keyed[frames[0]], keyed[frames[-1]], bones)
    c1, c1_bone = pose_c1_max_deg_per_second(
        keyed, bones, frame_duration_seconds=frame_duration_seconds
    )
    c0_pass = True if c0_limit_deg is None else c0 <= float(c0_limit_deg)
    c1_pass = True if c1_limit_deg_per_second is None else c1 <= float(c1_limit_deg_per_second)
    return {
        "sourceFrameCount": len(frames),
        "c0MaxDeg": c0,
        "c1MaxDegPerSecond": c1,
        "c0Pass": c0_pass,
        "c1Pass": c1_pass,
        "c0LimitDeg": c0_limit_deg,
        "c1LimitDegPerSecond": c1_limit_deg_per_second,
        "worstC0Bone": c0_bone,
        "worstC1Bone": c1_bone,
        "uncalibrated": c0_limit_deg is None or c1_limit_deg_per_second is None,
    }


def boundary_c0(
    predecessor_last: Mapping[str, Any],
    successor_first: Mapping[str, Any],
    bones: Sequence[str],
    *,
    limit_deg: float | None = None,
) -> dict[str, Any]:
    c0, bone = pose_c0_max_deg(successor_first, predecessor_last, bones)
    return {
        "c0MaxDeg": c0,
        "worstBone": bone,
        "c0Pass": True if limit_deg is None else c0 <= float(limit_deg),
        "uncalibrated": limit_deg is None,
    }


def close_cycle_pose_copy(first_pose: Mapping[str, Any]) -> dict[str, Any]:
    """Quaternion-sign-aligned copy is applied at export; pose dicts stay identical."""
    return {str(bone): dict(axes) for bone, axes in first_pose.items()}
