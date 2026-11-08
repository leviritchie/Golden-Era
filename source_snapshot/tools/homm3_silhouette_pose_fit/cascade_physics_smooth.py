"""Metric-free cascade post-pass: outlier pull-in, inertia, and gravity.

Cascade root + articulation already chose the broad-stroke poses. This pass
does not look at silhouette, depth, chroma, or collision. It treats those
poses as a noisy physical trajectory:

1. One-frame (or short) spikes are outliers and are replaced from neighbors.
2. A critically damped spring follows the cleaned targets, so velocity is
   continuous and leftover jitter dies.
3. Gravity acts only on outlier frames: root vertical hops fall, and distal
   bones get a hang torque. Consistent raised poses are not drooped.

Units: bone angles are axis-angle radians, root translation is body lengths,
``dt`` is seconds per DEF frame (1/12). Gravity is body-lengths / s^2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

_QUAT_XYZW = 4


@dataclass(frozen=True)
class PhysicsSmoothConfig:
    enabled: bool = True
    outlier_window: int = 5
    outlier_sigma: float = 3.5
    outlier_min_deg: float = 10.0
    outlier_min_translation: float = 0.08
    stiffness: float = 180.0
    dt: float = 1.0 / 12.0
    substeps: int = 4
    gravity: float = 9.81
    gravity_weight: float = 0.6
    gravity_min_bone_depth: int = 3
    root_vertical_axis: int = 2
    world_up: tuple[float, float, float] = (0.0, 1.0, 0.0)

    def validate(self) -> None:
        if int(self.outlier_window) < 3 or int(self.outlier_window) % 2 == 0:
            raise ValueError("outlier_window must be an odd integer >= 3")
        for name in ("outlier_sigma", "stiffness", "dt"):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("outlier_min_deg", "outlier_min_translation", "gravity", "gravity_weight"):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if int(self.substeps) < 1:
            raise ValueError("substeps must be at least 1")
        if int(self.gravity_min_bone_depth) < 0:
            raise ValueError("gravity_min_bone_depth must be non-negative")
        if int(self.root_vertical_axis) not in (0, 1, 2):
            raise ValueError("root_vertical_axis must be 0, 1, or 2")
        up = np.asarray(self.world_up, dtype=np.float64).reshape(-1)
        if int(up.shape[0]) != 3:
            raise ValueError("world_up must have 3 components")
        if float(np.linalg.norm(up)) <= 1e-12:
            raise ValueError("world_up must be a non-zero vector")


def _as_rotvecs(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 3 or int(array.shape[-1]) != 3:
        raise ValueError("bone rotations must have shape (frames, bones, 3)")
    if int(array.shape[0]) < 1 or int(array.shape[1]) < 1:
        raise ValueError("bone rotations must contain at least one frame and one bone")
    return array


def _as_root(values: np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or int(array.shape[-1]) != 3:
        raise ValueError(f"{name} must have shape (frames, 3)")
    return array


def rotvec_to_quat(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64).reshape(3)
    angle = float(np.linalg.norm(vector))
    if angle <= 1e-12:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    axis = vector / angle
    half = angle * 0.5
    sine = math.sin(half)
    return np.asarray((axis[0] * sine, axis[1] * sine, axis[2] * sine, math.cos(half)), dtype=np.float64)


def quat_to_rotvec(quat: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat, dtype=np.float64).reshape(_QUAT_XYZW)
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-12:
        raise ValueError("zero quaternion")
    quat = quat / norm
    if quat[3] < 0.0:
        quat = -quat
    w = float(np.clip(quat[3], -1.0, 1.0))
    xyz = quat[:3]
    angle = 2.0 * math.acos(w)
    sine = math.sin(angle * 0.5)
    if abs(sine) <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    return xyz * (angle / sine)


def quat_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = np.asarray(left, dtype=np.float64).reshape(_QUAT_XYZW)
    rx, ry, rz, rw = np.asarray(right, dtype=np.float64).reshape(_QUAT_XYZW)
    product = np.asarray(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(product))
    if norm <= 1e-12:
        raise ValueError("quaternion multiply produced a zero quaternion")
    return product / norm


def geodesic_radians(left: np.ndarray, right: np.ndarray) -> float:
    delta = quat_multiply(rotvec_to_quat(right), _quat_inverse(rotvec_to_quat(left)))
    return float(np.linalg.norm(quat_to_rotvec(delta)))


def _quat_inverse(quat: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat, dtype=np.float64).reshape(_QUAT_XYZW)
    return np.asarray((-quat[0], -quat[1], -quat[2], quat[3]), dtype=np.float64)


def relative_rotvec(target: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Axis-angle that takes ``current`` onto ``target`` (R_target * R_current^{-1})."""
    delta = quat_multiply(rotvec_to_quat(target), _quat_inverse(rotvec_to_quat(current)))
    return quat_to_rotvec(delta)


def compose_rotvec(current: np.ndarray, delta: np.ndarray) -> np.ndarray:
    return quat_to_rotvec(quat_multiply(rotvec_to_quat(delta), rotvec_to_quat(current)))


def slerp_rotvec(left: np.ndarray, right: np.ndarray, fraction: float) -> np.ndarray:
    t = float(np.clip(fraction, 0.0, 1.0))
    return quat_to_rotvec(
        _quat_slerp(rotvec_to_quat(left), rotvec_to_quat(right), t)
    )


def _quat_slerp(left: np.ndarray, right: np.ndarray, fraction: float) -> np.ndarray:
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    dot = float(np.clip(np.dot(left, right), -1.0, 1.0))
    if dot < 0.0:
        right = -right
        dot = -dot
    if dot > 0.9995:
        blended = left + fraction * (right - left)
        return blended / max(float(np.linalg.norm(blended)), 1e-12)
    theta = math.acos(dot)
    sine = math.sin(theta)
    a = math.sin((1.0 - fraction) * theta) / sine
    b = math.sin(fraction * theta) / sine
    blended = a * left + b * right
    return blended / max(float(np.linalg.norm(blended)), 1e-12)


def _window_slice(index: int, count: int, window: int) -> slice:
    half = int(window) // 2
    start = max(0, int(index) - half)
    stop = min(int(count), int(index) + half + 1)
    return slice(start, stop)


def hampel_mask_scalars(values: np.ndarray, *, window: int, n_sigma: float, minimum: float) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    count = int(values.shape[0])
    mask = np.zeros(count, dtype=bool)
    for index in range(count):
        chunk = values[_window_slice(index, count, window)]
        median = float(np.median(chunk))
        deviations = np.abs(chunk - median)
        mad = float(np.median(deviations))
        scale = 1.4826 * mad
        threshold = max(float(minimum), float(n_sigma) * max(scale, 1e-12))
        mask[index] = abs(float(values[index]) - median) > threshold
    return mask


def hampel_mask_rotvecs(rotvecs: np.ndarray, *, window: int, n_sigma: float, min_deg: float) -> np.ndarray:
    rotvecs = np.asarray(rotvecs, dtype=np.float64)
    if rotvecs.ndim != 2 or int(rotvecs.shape[-1]) != 3:
        raise ValueError("rotvecs must have shape (frames, 3)")
    count = int(rotvecs.shape[0])
    mask = np.zeros(count, dtype=bool)
    min_rad = math.radians(float(min_deg))
    for index in range(count):
        chunk = rotvecs[_window_slice(index, count, window)]
        median = np.median(chunk, axis=0)
        distances = np.asarray([geodesic_radians(row, median) for row in chunk], dtype=np.float64)
        mad = float(np.median(distances))
        scale = 1.4826 * mad
        threshold = max(min_rad, float(n_sigma) * max(scale, 1e-12))
        mask[index] = geodesic_radians(rotvecs[index], median) > threshold
    return mask


def fill_scalar_outliers(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    mask = np.asarray(mask, dtype=bool).reshape(-1)
    if values.shape != mask.shape:
        raise ValueError("values/mask length mismatch")
    filled = values.copy()
    inliers = np.flatnonzero(~mask)
    if inliers.size == 0:
        return filled
    for index in np.flatnonzero(mask):
        left = inliers[inliers < index]
        right = inliers[inliers > index]
        if left.size == 0 and right.size == 0:
            continue
        if left.size == 0:
            filled[index] = values[int(right[0])]
            continue
        if right.size == 0:
            filled[index] = values[int(left[-1])]
            continue
        a = int(left[-1])
        b = int(right[0])
        fraction = (index - a) / max(b - a, 1)
        filled[index] = (1.0 - fraction) * values[a] + fraction * values[b]
    return filled


def fill_rotvec_outliers(rotvecs: np.ndarray, mask: np.ndarray) -> np.ndarray:
    rotvecs = np.asarray(rotvecs, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool).reshape(-1)
    if rotvecs.ndim != 2 or int(rotvecs.shape[0]) != int(mask.shape[0]):
        raise ValueError("rotvecs/mask length mismatch")
    filled = rotvecs.copy()
    inliers = np.flatnonzero(~mask)
    if inliers.size == 0:
        return filled
    for index in np.flatnonzero(mask):
        left = inliers[inliers < index]
        right = inliers[inliers > index]
        if left.size == 0 and right.size == 0:
            continue
        if left.size == 0:
            filled[index] = rotvecs[int(right[0])]
            continue
        if right.size == 0:
            filled[index] = rotvecs[int(left[-1])]
            continue
        a = int(left[-1])
        b = int(right[0])
        fraction = (index - a) / max(b - a, 1)
        filled[index] = slerp_rotvec(rotvecs[a], rotvecs[b], fraction)
    return filled


def _critical_damping(stiffness: float) -> float:
    return 2.0 * math.sqrt(float(stiffness))


def _rotvec_matrix(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64).reshape(3)
    angle = float(np.linalg.norm(vector))
    if angle <= 1e-12:
        return np.eye(3, dtype=np.float64)
    axis = vector / angle
    x, y, z = axis
    cosine = math.cos(angle)
    sine = math.sin(angle)
    one = 1.0 - cosine
    return np.asarray(
        (
            (cosine + x * x * one, x * y * one - z * sine, x * z * one + y * sine),
            (y * x * one + z * sine, cosine + y * y * one, y * z * one - x * sine),
            (z * x * one - y * sine, z * y * one + x * sine, cosine + z * z * one),
        ),
        dtype=np.float64,
    )


def hang_torque(rotvec: np.ndarray, bind_direction: np.ndarray, down: np.ndarray) -> np.ndarray:
    """Angular acceleration that rotates the bone axis toward world-down."""
    direction = _rotvec_matrix(rotvec) @ np.asarray(bind_direction, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    direction = direction / norm
    down = np.asarray(down, dtype=np.float64).reshape(3)
    down_norm = float(np.linalg.norm(down))
    if down_norm <= 1e-12:
        raise ValueError("down must be a non-zero vector")
    down = down / down_norm
    torque = np.cross(direction, down)
    magnitude = float(np.linalg.norm(torque))
    if magnitude > 1e-8:
        return torque
    if float(np.dot(direction, down)) >= 0.0:
        return np.zeros(3, dtype=np.float64)
    helper = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    if abs(float(np.dot(direction, helper))) > 0.9:
        helper = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    axis = np.cross(direction, helper)
    axis_norm = float(np.linalg.norm(axis))
    if axis_norm <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    return axis / axis_norm


def inertial_follow_scalars(
    target: np.ndarray,
    *,
    stiffness: float,
    dt: float,
    substeps: int,
    extra_accel: np.ndarray | None = None,
) -> np.ndarray:
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    count = int(target.shape[0])
    accel = np.zeros(count, dtype=np.float64) if extra_accel is None else np.asarray(extra_accel, dtype=np.float64).reshape(-1)
    if accel.shape != target.shape:
        raise ValueError("extra_accel length mismatch")
    damping = _critical_damping(stiffness)
    step = float(dt) / float(substeps)
    position = float(target[0])
    velocity = 0.0
    out = np.empty(count, dtype=np.float64)
    out[0] = position
    for index in range(1, count):
        for _ in range(int(substeps)):
            force = float(stiffness) * (float(target[index]) - position) - damping * velocity + float(accel[index])
            velocity += force * step
            position += velocity * step
        out[index] = position
    return out


def inertial_follow_rotvecs(
    target: np.ndarray,
    *,
    stiffness: float,
    dt: float,
    substeps: int,
    extra_torque: np.ndarray | None = None,
    hang_bind: np.ndarray | None = None,
    hang_down: np.ndarray | None = None,
    hang_scale: float = 0.0,
    hang_mask: np.ndarray | None = None,
) -> np.ndarray:
    target = np.asarray(target, dtype=np.float64)
    if target.ndim != 2 or int(target.shape[-1]) != 3:
        raise ValueError("target must have shape (frames, 3)")
    count = int(target.shape[0])
    torque_table = np.zeros_like(target) if extra_torque is None else np.asarray(extra_torque, dtype=np.float64)
    if torque_table.shape != target.shape:
        raise ValueError("extra_torque shape mismatch")
    if hang_bind is not None:
        if hang_down is None:
            raise ValueError("hang_down is required when hang_bind is set")
        if hang_mask is None:
            raise ValueError("hang_mask is required when hang_bind is set")
        hang_mask = np.asarray(hang_mask, dtype=bool).reshape(-1)
        if int(hang_mask.shape[0]) != count:
            raise ValueError("hang_mask length mismatch")
        if not math.isfinite(float(hang_scale)) or float(hang_scale) < 0.0:
            raise ValueError("hang_scale must be finite and non-negative")
    damping = _critical_damping(stiffness)
    step = float(dt) / float(substeps)
    position = target[0].copy()
    velocity = np.zeros(3, dtype=np.float64)
    out = np.empty_like(target)
    out[0] = position
    for index in range(1, count):
        for _ in range(int(substeps)):
            error = relative_rotvec(target[index], position)
            torque = torque_table[index]
            if hang_bind is not None and bool(hang_mask[index]) and float(hang_scale) > 0.0:
                torque = torque + float(hang_scale) * hang_torque(position, hang_bind, hang_down)
            force = float(stiffness) * error - damping * velocity + torque
            velocity = velocity + force * step
            position = compose_rotvec(position, velocity * step)
        out[index] = position
    return out


def _rms_accel(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=np.float64)
    if int(values.shape[0]) < 3:
        return 0.0
    accel = values[2:] - 2.0 * values[1:-1] + values[:-2]
    if accel.ndim == 1:
        return float(np.sqrt(np.mean(accel * accel)))
    return float(np.sqrt(np.mean(np.sum(accel * accel, axis=-1))))


def smooth_cascade_clip(
    bone_rotvecs: np.ndarray,
    root_translation: np.ndarray,
    root_rotation: np.ndarray,
    *,
    config: PhysicsSmoothConfig,
    bone_depths: np.ndarray | None = None,
    bind_directions: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Smooth a clip. Does not accept or use sprite/geometry scores."""
    config.validate()
    bones = _as_rotvecs(bone_rotvecs)
    translation = _as_root(root_translation, name="root_translation")
    rotation = _as_root(root_rotation, name="root_rotation")
    frames = int(bones.shape[0])
    if int(translation.shape[0]) != frames or int(rotation.shape[0]) != frames:
        raise ValueError("root arrays must use the same frame count as bone_rotvecs")
    if not bool(config.enabled):
        report = {
            "enabled": False,
            "outlierBoneFrames": 0,
            "outlierRootFrames": 0,
        }
        return bones.copy(), translation.copy(), rotation.copy(), report

    depths = (
        np.zeros(int(bones.shape[1]), dtype=np.int32)
        if bone_depths is None
        else np.asarray(bone_depths, dtype=np.int32).reshape(-1)
    )
    if int(depths.shape[0]) != int(bones.shape[1]):
        raise ValueError("bone_depths length must match bone count")
    directions = (
        None
        if bind_directions is None
        else np.asarray(bind_directions, dtype=np.float64)
    )
    if directions is not None and directions.shape != (int(bones.shape[1]), 3):
        raise ValueError("bind_directions must have shape (bones, 3)")

    down = -np.asarray(config.world_up, dtype=np.float64).reshape(3)
    down = down / max(float(np.linalg.norm(down)), 1e-12)
    vertical = int(config.root_vertical_axis)

    bone_mask = np.zeros((frames, int(bones.shape[1])), dtype=bool)
    cleaned_bones = np.empty_like(bones)
    for bone in range(int(bones.shape[1])):
        mask = hampel_mask_rotvecs(
            bones[:, bone, :],
            window=int(config.outlier_window),
            n_sigma=float(config.outlier_sigma),
            min_deg=float(config.outlier_min_deg),
        )
        bone_mask[:, bone] = mask
        cleaned_bones[:, bone, :] = fill_rotvec_outliers(bones[:, bone, :], mask)

    trans_mask = np.zeros(frames, dtype=bool)
    cleaned_translation = translation.copy()
    for axis in range(3):
        mask = hampel_mask_scalars(
            translation[:, axis],
            window=int(config.outlier_window),
            n_sigma=float(config.outlier_sigma),
            minimum=float(config.outlier_min_translation),
        )
        trans_mask = trans_mask | mask
        cleaned_translation[:, axis] = fill_scalar_outliers(translation[:, axis], mask)

    rot_mask = hampel_mask_rotvecs(
        rotation,
        window=int(config.outlier_window),
        n_sigma=float(config.outlier_sigma),
        min_deg=float(config.outlier_min_deg),
    )
    cleaned_rotation = fill_rotvec_outliers(rotation, rot_mask)

    trans_accel = np.zeros_like(cleaned_translation)
    trans_accel[:, vertical] = -float(config.gravity) * float(config.gravity_weight) * trans_mask.astype(np.float64)
    smoothed_translation = np.stack(
        [
            inertial_follow_scalars(
                cleaned_translation[:, axis],
                stiffness=float(config.stiffness),
                dt=float(config.dt),
                substeps=int(config.substeps),
                extra_accel=trans_accel[:, axis],
            )
            for axis in range(3)
        ],
        axis=1,
    )
    smoothed_rotation = inertial_follow_rotvecs(
        cleaned_rotation,
        stiffness=float(config.stiffness),
        dt=float(config.dt),
        substeps=int(config.substeps),
    )

    smoothed_bones = np.empty_like(cleaned_bones)
    hang_scale = float(config.gravity) * float(config.gravity_weight)
    for bone in range(int(bones.shape[1])):
        distal = int(depths[bone]) >= int(config.gravity_min_bone_depth)
        hang_bind = None
        hang_mask = None
        bone_hang_scale = 0.0
        if distal and directions is not None and hang_scale > 0.0:
            bind = directions[bone]
            bind_norm = float(np.linalg.norm(bind))
            if bind_norm > 1e-12:
                hang_bind = bind / bind_norm
                hang_mask = bone_mask[:, bone]
                bone_hang_scale = hang_scale
        smoothed_bones[:, bone, :] = inertial_follow_rotvecs(
            cleaned_bones[:, bone, :],
            stiffness=float(config.stiffness),
            dt=float(config.dt),
            substeps=int(config.substeps),
            hang_bind=hang_bind,
            hang_down=down,
            hang_scale=bone_hang_scale,
            hang_mask=hang_mask,
        )

    report = {
        "enabled": True,
        "outlierBoneFrames": int(np.count_nonzero(bone_mask)),
        "outlierRootFrames": int(np.count_nonzero(trans_mask | rot_mask)),
        "peakBoneDegBefore": float(np.max(np.linalg.norm(bones, axis=-1)) * (180.0 / math.pi)),
        "peakBoneDegAfter": float(np.max(np.linalg.norm(smoothed_bones, axis=-1)) * (180.0 / math.pi)),
        "rmsBoneAccelBefore": _rms_accel(bones.reshape(frames, -1)),
        "rmsBoneAccelAfter": _rms_accel(smoothed_bones.reshape(frames, -1)),
        "rmsRootAccelBefore": _rms_accel(translation),
        "rmsRootAccelAfter": _rms_accel(smoothed_translation),
    }
    return smoothed_bones, smoothed_translation, smoothed_rotation, report


def physics_smooth_config_from_mapping(payload: Mapping[str, Any]) -> PhysicsSmoothConfig:
    world_up = tuple(float(axis) for axis in payload.get("physics_smooth_world_up", (0.0, 1.0, 0.0)))
    if len(world_up) != 3:
        raise ValueError("physics_smooth_world_up must have 3 components")
    return PhysicsSmoothConfig(
        enabled=bool(payload.get("physics_smooth_enabled", True)),
        outlier_window=int(payload.get("physics_smooth_outlier_window", 5)),
        outlier_sigma=float(payload.get("physics_smooth_outlier_sigma", 3.5)),
        outlier_min_deg=float(payload.get("physics_smooth_outlier_min_deg", 10.0)),
        outlier_min_translation=float(payload.get("physics_smooth_outlier_min_translation", 0.08)),
        stiffness=float(payload.get("physics_smooth_stiffness", 180.0)),
        dt=float(payload.get("physics_smooth_dt", 1.0 / 12.0)),
        substeps=int(payload.get("physics_smooth_substeps", 4)),
        gravity=float(payload.get("physics_smooth_gravity", 9.81)),
        gravity_weight=float(payload.get("physics_smooth_gravity_weight", 0.6)),
        gravity_min_bone_depth=int(payload.get("physics_smooth_gravity_min_bone_depth", 3)),
        root_vertical_axis=int(payload.get("physics_smooth_root_vertical_axis", 2)),
        world_up=world_up,
    )
