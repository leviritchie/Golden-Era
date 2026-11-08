"""Pure rotation-search geometry shared by frame and clip optimizers.

The Blender worker accepts quaternions, so the optimizer does not need to
pretend that the imported rig's Euler axes are an anatomical coordinate frame.
This module deliberately contains no Blender or NumPy dependency.  It keeps
proposal construction deterministic and easy to test outside the worker.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


Quaternion = tuple[float, float, float, float]
Vector3 = tuple[float, float, float]


def _finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"rotation value must be finite, got {value!r}")
    return value


def normalize_vector(value: Sequence[float], *, fallback: Vector3 = (0.0, 1.0, 0.0)) -> Vector3:
    if len(value) != 3:
        raise ValueError("rotation vectors must contain three values")
    vector = tuple(_finite(part) for part in value)
    length = math.sqrt(sum(part * part for part in vector))
    if length < 1e-12:
        if fallback is None:
            raise ValueError("rotation vector cannot have zero length")
        return normalize_vector(fallback, fallback=None)
    return tuple(part / length for part in vector)  # type: ignore[return-value]


def cross(left: Sequence[float], right: Sequence[float]) -> Vector3:
    return (
        float(left[1]) * float(right[2]) - float(left[2]) * float(right[1]),
        float(left[2]) * float(right[0]) - float(left[0]) * float(right[2]),
        float(left[0]) * float(right[1]) - float(left[1]) * float(right[0]),
    )


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def add_scaled(left: Sequence[float], right: Sequence[float], scale: float) -> Vector3:
    return tuple(
        float(a) + float(scale) * float(b)
        for a, b in zip(left, right)
    )  # type: ignore[return-value]


def normalize_quaternion(value: Sequence[float]) -> Quaternion:
    if len(value) != 4:
        raise ValueError("quaternions must contain four values in wxyz order")
    quaternion = tuple(_finite(part) for part in value)
    length = math.sqrt(sum(part * part for part in quaternion))
    if length < 1e-12:
        raise ValueError("quaternion cannot have zero magnitude")
    return tuple(part / length for part in quaternion)  # type: ignore[return-value]


def quaternion_multiply(left: Sequence[float], right: Sequence[float]) -> Quaternion:
    lw, lx, ly, lz = normalize_quaternion(left)
    rw, rx, ry, rz = normalize_quaternion(right)
    return normalize_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def quaternion_from_axis_angle(axis: Sequence[float], angle_rad: float) -> Quaternion:
    axis = normalize_vector(axis)
    half = 0.5 * _finite(angle_rad)
    sine = math.sin(half)
    return normalize_quaternion((math.cos(half), axis[0] * sine, axis[1] * sine, axis[2] * sine))


def quaternion_from_euler_xyz(x: float, y: float, z: float) -> Quaternion:
    cx, cy, cz = (math.cos(float(value) * 0.5) for value in (x, y, z))
    sx, sy, sz = (math.sin(float(value) * 0.5) for value in (x, y, z))
    return normalize_quaternion(
        (
            cx * cy * cz + sx * sy * sz,
            sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
        )
    )


def quaternion_to_euler_xyz(value: Sequence[float]) -> Vector3:
    w, x, y, z = normalize_quaternion(value)
    sin_x = 2.0 * (w * x + y * z)
    cos_x = 1.0 - 2.0 * (x * x + y * y)
    euler_x = math.atan2(sin_x, cos_x)
    sin_y = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    euler_y = math.asin(sin_y)
    sin_z = 2.0 * (w * z + x * y)
    cos_z = 1.0 - 2.0 * (y * y + z * z)
    euler_z = math.atan2(sin_z, cos_z)
    return (euler_x, euler_y, euler_z)


def quaternion_angle_deg(value: Sequence[float]) -> float:
    w, x, y, z = normalize_quaternion(value)
    scalar = max(-1.0, min(1.0, abs(w)))
    return math.degrees(2.0 * math.acos(scalar))


def pose_value_to_quaternion(value: Any) -> Quaternion:
    """Normalize the pipeline's float, axis/angle, Euler, or quaternion forms."""
    if isinstance(value, (int, float)):
        return quaternion_from_axis_angle((0.0, 0.0, 1.0), float(value))
    if not isinstance(value, Mapping):
        return (1.0, 0.0, 0.0, 0.0)
    if "quaternion" in value:
        raw = value["quaternion"]
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            raise ValueError("quaternion pose entries must contain four values")
        order = str(value.get("quaternionOrder", "wxyz")).lower()
        if order == "xyzw":
            raw = (raw[3], raw[0], raw[1], raw[2])
        elif order != "wxyz":
            raise ValueError("quaternionOrder must be wxyz or xyzw")
        return normalize_quaternion(raw)
    if "axis" in value:
        axis = value["axis"]
        if isinstance(axis, str):
            axis = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}.get(
                axis.lower()
            )
            if axis is None:
                raise ValueError(f"unsupported rotation axis: {value['axis']!r}")
        return quaternion_from_axis_angle(
            axis,
            float(value.get("angle", value.get("rad", 0.0))),
        )
    return quaternion_from_euler_xyz(
        float(value.get("x", 0.0)),
        float(value.get("y", 0.0)),
        float(value.get("z", 0.0)),
    )


def quaternion_pose_entry(
    value: Sequence[float],
    *,
    twist_policy: str = "exclude",
) -> dict[str, Any]:
    return {
        "quaternion": [float(part) for part in normalize_quaternion(value)],
        "quaternionOrder": "wxyz",
        "twistPolicy": str(twist_policy).lower(),
    }


def virtual_search_frame(bone_vector: Sequence[float]) -> dict[str, Vector3]:
    """Build a deterministic swing/twist frame from a bone's rest shaft."""
    shaft = normalize_vector(bone_vector)
    references = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    reference = min(references, key=lambda candidate: abs(dot(shaft, candidate)))
    swing_a = normalize_vector(cross(shaft, reference), fallback=(1.0, 0.0, 0.0))
    swing_b = normalize_vector(cross(shaft, swing_a), fallback=(0.0, 0.0, 1.0))
    return {"shaft": shaft, "swingA": swing_a, "swingB": swing_b}


def rotation_vector_proposals(
    current_quaternion: Sequence[float],
    bone_vector: Sequence[float],
    step_deg: float,
    probe_count: int,
    max_abs_deg: float,
    *,
    include_twist: bool,
    twist_policy: str = "exclude",
) -> list[dict[str, Any]]:
    """Return legal first-shell arbitrary-axis proposals around the current pose."""
    if float(step_deg) <= 0.0:
        raise ValueError("rotation-vector step must be positive")
    if int(probe_count) < 4:
        raise ValueError("rotation-vector probe_count must be at least 4")
    frame = virtual_search_frame(bone_vector)
    current = normalize_quaternion(current_quaternion)
    max_abs_deg = abs(float(max_abs_deg))
    proposals: list[dict[str, Any]] = []

    def add(axis: Sequence[float], angle_deg: float, *, kind: str, direction: int, policy: str) -> None:
        angle_deg = float(angle_deg)
        if angle_deg <= 1e-9:
            return
        increment = quaternion_from_axis_angle(axis, math.radians(angle_deg))
        candidate = quaternion_multiply(increment, current)
        if quaternion_angle_deg(candidate) > max_abs_deg + 1e-6:
            return
        proposals.append(
            {
                "quaternion": candidate,
                "axis": [float(part) for part in normalize_vector(axis)],
                "angleDeg": angle_deg,
                "kind": kind,
                "direction": int(direction),
                "twistPolicy": policy,
            }
        )

    count = int(probe_count)
    swing_policy = "include" if str(twist_policy).lower() == "include" else "exclude"
    for index in range(count):
        phase = 2.0 * math.pi * index / count
        axis = add_scaled(
            add_scaled((0.0, 0.0, 0.0), frame["swingA"], math.cos(phase)),
            frame["swingB"],
            math.sin(phase),
        )
        add(axis, step_deg, kind="swing", direction=index, policy=swing_policy)
    if include_twist:
        add(frame["shaft"], step_deg, kind="twist", direction=count, policy="include")
        add(tuple(-part for part in frame["shaft"]), step_deg, kind="twist", direction=count + 1, policy="include")
    return proposals


def continuation_proposal(
    current_quaternion: Sequence[float],
    axis: Sequence[float],
    angle_deg: float,
    max_abs_deg: float,
    *,
    kind: str,
    direction: int,
    twist_policy: str,
) -> dict[str, Any] | None:
    """Extend one accepted/probable direction without violating the range cap."""
    increment = quaternion_from_axis_angle(axis, math.radians(float(angle_deg)))
    candidate = quaternion_multiply(increment, current_quaternion)
    if quaternion_angle_deg(candidate) > abs(float(max_abs_deg)) + 1e-6:
        return None
    return {
        "quaternion": candidate,
        "axis": [float(part) for part in normalize_vector(axis)],
        "angleDeg": float(angle_deg),
        "kind": str(kind),
        "direction": int(direction),
        "twistPolicy": str(twist_policy).lower(),
    }


__all__ = [
    "continuation_proposal",
    "normalize_quaternion",
    "pose_value_to_quaternion",
    "quaternion_angle_deg",
    "quaternion_from_axis_angle",
    "quaternion_from_euler_xyz",
    "quaternion_multiply",
    "quaternion_pose_entry",
    "quaternion_to_euler_xyz",
    "rotation_vector_proposals",
    "virtual_search_frame",
]
