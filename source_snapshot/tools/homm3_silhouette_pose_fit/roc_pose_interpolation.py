#!/usr/bin/env python3
"""Pose interpolation for delivered HoMM3 mesh previews.

The semantic optimizer produces sparse source poses. This module turns those
poses into a renderable timeline without changing the source keyframes or the
fit objective. Rotations are stored as local XYZ Euler radians in the existing
artifact format; quaternion methods use spherical interpolation internally and
convert back only at the worker boundary.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.spatial.transform import Rotation, Slerp


MOTION_ROOT_KEY = "__motion_root__"
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"
ROTATION_METHODS = (
    "euler_linear",
    "quaternion_slerp",
    "quaternion_smoothstep",
)
_ROOT_AXES = ("forward", "lateral", "vertical")
_ROOT_ROTATION_AXES = ("camera_forward", "camera_right", "camera_up")
_EULER_AXES = ("x", "y", "z")


def _validate_method(method: str) -> str:
    value = str(method).strip().lower()
    if value not in ROTATION_METHODS:
        raise ValueError(
            f"unknown interpolation method {method!r}; expected one of {ROTATION_METHODS}"
        )
    return value


def _as_rotation(value: Any) -> Rotation:
    """Normalize a pose entry to a scipy rotation without going through Euler."""

    if isinstance(value, Mapping) and "quaternion" in value:
        raw = np.asarray(value["quaternion"], dtype=np.float64)
        if raw.shape != (4,):
            raise ValueError("quaternion pose entries must contain four values")
        order = str(value.get("quaternionOrder", "wxyz")).lower()
        if order == "wxyz":
            raw = np.array([raw[1], raw[2], raw[3], raw[0]], dtype=np.float64)
        elif order != "xyzw":
            raise ValueError("quaternionOrder must be wxyz or xyzw")
        return Rotation.from_quat(raw)
    # Blender's mathutils Euler("XYZ") matches scipy's lowercase extrinsic
    # sequence, not scipy's uppercase intrinsic sequence.
    return Rotation.from_euler("xyz", _as_euler_radians(value), degrees=False)


def _as_euler_radians(value: Any) -> np.ndarray:
    """Normalize the artifact's supported sparse rotation forms to XYZ radians."""

    if isinstance(value, Mapping):
        if "axis" in value:
            result = np.zeros(3, dtype=np.float64)
            axis = str(value.get("axis", "z")).strip().lower()
            if axis not in _EULER_AXES:
                raise ValueError(f"unsupported sparse pose axis: {axis!r}")
            result[_EULER_AXES.index(axis)] = float(
                value.get("angle", value.get("rad", 0.0))
            )
            return result
        if "quaternion" in value:
            return _as_rotation(value).as_euler("xyz", degrees=False)
        return np.array(
            [float(value.get(axis, 0.0)) for axis in _EULER_AXES],
            dtype=np.float64,
        )
    if isinstance(value, (int, float, np.integer, np.floating)):
        result = np.zeros(3, dtype=np.float64)
        result[2] = float(value)
        return result
    raise TypeError(f"unsupported pose entry type: {type(value)!r}")


def _as_root(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {axis: 0.0 for axis in _ROOT_AXES}
    return {axis: float(value.get(axis, 0.0)) for axis in _ROOT_AXES}


def _as_root_rotation(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {axis: 0.0 for axis in _ROOT_ROTATION_AXES}
    return {
        axis: float(value.get(axis, 0.0))
        for axis in _ROOT_ROTATION_AXES
    }


def _shortest_angle_delta(start: float, end: float) -> float:
    return float((float(end) - float(start) + math.pi) % (2.0 * math.pi) - math.pi)


def _linear_euler(start: np.ndarray, end: np.ndarray, t: float) -> np.ndarray:
    delta = np.array(
        [_shortest_angle_delta(left, right) for left, right in zip(start, end)],
        dtype=np.float64,
    )
    return start + float(t) * delta


def _slerp_rotation(start: Any, end: Any, t: float) -> Rotation:
    rotations = Rotation.from_quat(
        np.stack([_as_rotation(start).as_quat(), _as_rotation(end).as_quat()])
    )
    interpolator = Slerp([0.0, 1.0], rotations)
    return interpolator([float(t)])[0]


def _smoothstep(t: float) -> float:
    value = float(np.clip(t, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def _rotation_between(start: Any, end: Any, t: float, method: str) -> dict[str, Any]:
    if method == "euler_linear":
        result = _linear_euler(_as_euler_radians(start), _as_euler_radians(end), t)
        return {axis: float(result[index]) for index, axis in enumerate(_EULER_AXES)}
    if method == "quaternion_slerp":
        result = _slerp_rotation(start, end, t)
    else:
        result = _slerp_rotation(start, end, _smoothstep(t))
    xyzw = result.as_quat()
    return {
        "quaternion": [
            float(xyzw[3]),
            float(xyzw[0]),
            float(xyzw[1]),
            float(xyzw[2]),
        ],
        "quaternionOrder": "wxyz",
    }


def interpolate_pose(
    start: Mapping[str, Any],
    end: Mapping[str, Any],
    t: float,
    *,
    method: str,
) -> dict[str, dict[str, Any]]:
    """Interpolate one pose pair, preserving the worker's pose contract."""

    method = _validate_method(method)
    t = float(np.clip(t, 0.0, 1.0))
    keys = list(dict.fromkeys([*start.keys(), *end.keys()]))
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        if key == MOTION_ROOT_KEY:
            left = _as_root(start.get(key, {}))
            right = _as_root(end.get(key, {}))
            result[key] = {
                axis: float(left[axis] + t * (right[axis] - left[axis]))
                for axis in _ROOT_AXES
            }
        elif key == MOTION_ROOT_ROTATION_KEY:
            left = _as_root_rotation(start.get(key, {}))
            right = _as_root_rotation(end.get(key, {}))
            result[key] = {
                axis: float(
                    left[axis]
                    + t * math.degrees(
                        _shortest_angle_delta(
                            math.radians(left[axis]),
                            math.radians(right[axis]),
                        )
                    )
                )
                for axis in _ROOT_ROTATION_AXES
            }
        else:
            result[key] = _rotation_between(
                start.get(key, {}), end.get(key, {}), t, method
            )
    return result


def interpolate_clip(
    poses: Sequence[Mapping[str, Any]],
    *,
    method: str,
    samples_per_interval: int = 5,
    loop: bool = True,
) -> list[dict[str, dict[str, float]]]:
    """Resample a sparse pose clip at a fixed number of samples per interval.

    For a six-pose loop and five samples per interval this returns thirty
    renders: each source pose occurs at the beginning of its interval and the
    repeated first pose is intentionally omitted at the end of the cycle.
    """

    method = _validate_method(method)
    if int(samples_per_interval) < 1:
        raise ValueError("samples_per_interval must be at least 1")
    samples = int(samples_per_interval)
    source = [copy.deepcopy(dict(pose)) for pose in poses]
    if not source:
        raise ValueError("cannot interpolate an empty pose clip")
    if len(source) == 1:
        return source

    segment_count = len(source) if loop else len(source) - 1
    result: list[dict[str, dict[str, float]]] = []
    for index in range(segment_count):
        next_index = (index + 1) % len(source)
        for sample in range(samples):
            result.append(
                interpolate_pose(
                    source[index],
                    source[next_index],
                    sample / float(samples),
                    method=method,
                )
            )
    if not loop:
        result.append(copy.deepcopy(source[-1]))
    return result


def load_pose_artifact(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the notebook's ``clip_poses.json`` and return ordered poses + metadata."""

    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    metadata: dict[str, Any] = {"sourcePoseArtifact": str(source_path)}
    provenance_path = source_path.with_name(source_path.stem + ".provenance.json")
    if provenance_path.is_file():
        metadata["provenancePath"] = str(provenance_path)
        metadata["provenance"] = json.loads(provenance_path.read_text(encoding="utf-8"))
    raw_poses: Any = payload
    if isinstance(payload, Mapping) and "poses" in payload:
        raw_poses = payload["poses"]
        metadata.update(
            {
                str(key): value
                for key, value in payload.items()
                if key != "poses" and isinstance(value, (str, int, float, bool, type(None)))
            }
        )
    if isinstance(raw_poses, Mapping):
        ordered = sorted(raw_poses.items(), key=lambda item: int(item[0]))
        poses = [dict(value) for _frame, value in ordered]
        metadata["sourceFrameIndices"] = [int(frame) for frame, _value in ordered]
    elif isinstance(raw_poses, list):
        poses = [dict(value) for value in raw_poses]
        metadata["sourceFrameIndices"] = list(range(len(poses)))
    else:
        raise ValueError(f"pose artifact must contain a mapping or list, got {type(raw_poses)!r}")
    if not poses:
        raise ValueError(f"pose artifact has no poses: {source_path}")
    return poses, metadata


def write_pose_artifact(
    path: str | Path,
    poses: Sequence[Mapping[str, Any]],
    *,
    method: str,
    source_metadata: Mapping[str, Any],
    samples_per_interval: int,
    loop: bool,
    fps: int,
) -> None:
    """Write a self-describing interpolated pose sequence."""

    payload = {
        "interpolationMethod": _validate_method(method),
        "sourceFrameCount": int(len(source_metadata.get("sourceFrameIndices", []))),
        "outputFrameCount": int(len(poses)),
        "samplesPerInterval": int(samples_per_interval),
        "loop": bool(loop),
        "fps": int(fps),
        "source": dict(source_metadata),
        "poses": {str(index): dict(pose) for index, pose in enumerate(poses)},
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")


def pose_delta_summary(poses: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Summarize rotation/root movement for comparing interpolation curves."""

    rotation_deltas: list[float] = []
    root_deltas: list[float] = []
    root_rotation_deltas: list[float] = []
    for left, right in zip(poses, poses[1:]):
        for key in set(left) | set(right):
            if key == MOTION_ROOT_KEY:
                a = _as_root(left.get(key, {}))
                b = _as_root(right.get(key, {}))
                root_deltas.append(
                    float(
                        np.linalg.norm(
                            [b[axis] - a[axis] for axis in _ROOT_AXES]
                        )
                    )
                )
            elif key == MOTION_ROOT_ROTATION_KEY:
                a = _as_root_rotation(left.get(key, {}))
                b = _as_root_rotation(right.get(key, {}))
                root_rotation_deltas.append(
                    float(
                        np.linalg.norm(
                            [
                                math.degrees(
                                    _shortest_angle_delta(
                                        math.radians(a[axis]),
                                        math.radians(b[axis]),
                                    )
                                )
                                for axis in _ROOT_ROTATION_AXES
                            ]
                        )
                    )
                )
            else:
                relative = _as_rotation(left.get(key, {})).inv() * _as_rotation(
                    right.get(key, {})
                )
                xyzw = relative.as_quat()
                rotation_deltas.append(
                    float(
                        2.0
                        * math.atan2(
                            float(np.linalg.norm(xyzw[:3])),
                            abs(float(xyzw[3])),
                        )
                    )
                )
    return {
        "meanRotationDeltaRad": float(np.mean(rotation_deltas)) if rotation_deltas else 0.0,
        "maxRotationDeltaRad": float(np.max(rotation_deltas)) if rotation_deltas else 0.0,
        "meanRootDeltaBodyLengths": float(np.mean(root_deltas)) if root_deltas else 0.0,
        "maxRootDeltaBodyLengths": float(np.max(root_deltas)) if root_deltas else 0.0,
        "meanRootRotationDeltaDeg": float(np.mean(root_rotation_deltas)) if root_rotation_deltas else 0.0,
        "maxRootRotationDeltaDeg": float(np.max(root_rotation_deltas)) if root_rotation_deltas else 0.0,
    }
