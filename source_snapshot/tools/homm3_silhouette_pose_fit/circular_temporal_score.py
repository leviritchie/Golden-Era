"""Circular velocity/acceleration scoring after a clip exists.

Linear temporal terms only see ``p[i]-p[i-1]``. A looping Idle or Move then
carries an un-scored jump from last pose back to first. This module:

- scores velocity both forward (``p[i]-p[i-1]``) and backward (``p[i]-p[i+1]``)
  with wrap-around;
- scores acceleration on the circular 3-point stencil, including the two
  wrap windows ``(N-1, 0, 1)`` and ``(N-2, N-1, 0)``;
- applies a bidirectional periodic follow (tile three periods, inertial-follow
  forward and reversed, take the middle copy, slerp-merge).

One-shot / entry / exit clips must not wrap. Physics smoothing stays a separate
bounded polish pass.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from cascade_physics_smooth import (
    inertial_follow_rotvecs,
    inertial_follow_scalars,
    slerp_rotvec,
)


def require_frame_major(values: np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if int(array.shape[0]) < 1:
        raise ValueError(f"{name} must contain at least one frame")
    return array


def circular_first_difference(values: np.ndarray) -> np.ndarray:
    """Forward wrap: ``out[i] = values[i] - values[i-1]`` with ``i-1`` wrapping."""
    values = require_frame_major(values, name="values")
    return values - np.roll(values, 1, axis=0)


def circular_backward_first_difference(values: np.ndarray) -> np.ndarray:
    """Backward wrap: ``out[i] = values[i] - values[i+1]`` with ``i+1`` wrapping."""
    values = require_frame_major(values, name="values")
    return values - np.roll(values, -1, axis=0)


def circular_second_difference(values: np.ndarray) -> np.ndarray:
    """``out[i] = values[i+1] - 2*values[i] + values[i-1]`` with wrap."""
    values = require_frame_major(values, name="values")
    return np.roll(values, -1, axis=0) - 2.0 * values + np.roll(values, 1, axis=0)


def _rms(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(array * array)))


def linear_velocity_rms(values: np.ndarray) -> float:
    values = require_frame_major(values, name="values")
    if int(values.shape[0]) < 2:
        return 0.0
    return _rms(values[1:] - values[:-1])


def circular_velocity_rms(values: np.ndarray) -> float:
    values = require_frame_major(values, name="values")
    if int(values.shape[0]) < 2:
        return 0.0
    forward = circular_first_difference(values)
    backward = circular_backward_first_difference(values)
    return 0.5 * (_rms(forward) + _rms(backward))


def circular_acceleration_rms(values: np.ndarray) -> float:
    values = require_frame_major(values, name="values")
    if int(values.shape[0]) < 3:
        return 0.0
    return _rms(circular_second_difference(values))


def linear_acceleration_rms(values: np.ndarray) -> float:
    values = require_frame_major(values, name="values")
    if int(values.shape[0]) < 3:
        return 0.0
    return _rms(values[2:] - 2.0 * values[1:-1] + values[:-2])


def wrap_velocity_rms(values: np.ndarray) -> float:
    """Only the loop seam: last→first (forward) and first→last (backward)."""
    values = require_frame_major(values, name="values")
    if int(values.shape[0]) < 2:
        return 0.0
    forward = values[0] - values[-1]
    backward = values[-1] - values[0]
    return 0.5 * (_rms(forward) + _rms(backward))


@dataclass(frozen=True)
class CircularTemporalConfig:
    periods: int = 3
    stiffness: float = 180.0
    dt: float = 1.0 / 12.0
    substeps: int = 4
    blend: float = 1.0

    def validate(self) -> None:
        periods = int(self.periods)
        if periods < 3 or periods % 2 == 0:
            raise ValueError("periods must be an odd integer >= 3 so a middle copy exists")
        if not math.isfinite(float(self.stiffness)) or float(self.stiffness) <= 0.0:
            raise ValueError("stiffness must be finite and positive")
        if not math.isfinite(float(self.dt)) or float(self.dt) <= 0.0:
            raise ValueError("dt must be finite and positive")
        if int(self.substeps) < 1:
            raise ValueError("substeps must be at least 1")
        blend = float(self.blend)
        if not math.isfinite(blend) or blend < 0.0 or blend > 1.0:
            raise ValueError("blend must be in [0, 1]")


def tile_periods(values: np.ndarray, periods: int) -> np.ndarray:
    values = require_frame_major(values, name="values")
    count = int(periods)
    if count < 1:
        raise ValueError("periods must be positive")
    return np.concatenate([values] * count, axis=0)


def take_middle_period(values: np.ndarray, frame_count: int, periods: int) -> np.ndarray:
    start = int(frame_count) * (int(periods) // 2)
    stop = start + int(frame_count)
    if stop > int(values.shape[0]):
        raise ValueError("tiled series is shorter than the requested middle period")
    return np.asarray(values[start:stop], dtype=np.float64).copy()


def _follow_scalars_tiled(
    target: np.ndarray,
    *,
    config: CircularTemporalConfig,
) -> np.ndarray:
    target = require_frame_major(target, name="target")
    if target.ndim == 1:
        tiled = tile_periods(target, config.periods)
        followed = inertial_follow_scalars(
            tiled,
            stiffness=float(config.stiffness),
            dt=float(config.dt),
            substeps=int(config.substeps),
        )
        return take_middle_period(followed, int(target.shape[0]), config.periods)
    if target.ndim != 2:
        raise ValueError("scalar series must have shape (frames,) or (frames, channels)")
    out = np.empty_like(target)
    for channel in range(int(target.shape[1])):
        out[:, channel] = _follow_scalars_tiled(target[:, channel], config=config)
    return out


def _follow_rotvecs_tiled(
    target: np.ndarray,
    *,
    config: CircularTemporalConfig,
) -> np.ndarray:
    tiled = tile_periods(target, config.periods)
    followed = inertial_follow_rotvecs(
        tiled,
        stiffness=float(config.stiffness),
        dt=float(config.dt),
        substeps=int(config.substeps),
    )
    return take_middle_period(followed, int(target.shape[0]), config.periods)


def bidirectional_circular_scalars(
    target: np.ndarray,
    *,
    config: CircularTemporalConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    config.validate()
    target = require_frame_major(target, name="target")
    if int(target.shape[0]) < 2 or float(config.blend) == 0.0:
        return target.copy(), {"applied": False, "reason": "too_short_or_zero_blend"}
    forward = _follow_scalars_tiled(target, config=config)
    reverse = _follow_scalars_tiled(target[::-1].copy(), config=config)[::-1].copy()
    merged = 0.5 * (forward + reverse)
    out = (1.0 - float(config.blend)) * target + float(config.blend) * merged
    return out, {
        "applied": True,
        "direction": "forward_and_backward",
        "periods": int(config.periods),
        "velocityRmsBefore": circular_velocity_rms(target),
        "velocityRmsAfter": circular_velocity_rms(out),
        "accelerationRmsBefore": circular_acceleration_rms(target),
        "accelerationRmsAfter": circular_acceleration_rms(out),
        "wrapVelocityRmsBefore": wrap_velocity_rms(target),
        "wrapVelocityRmsAfter": wrap_velocity_rms(out),
        "linearVelocityRmsBefore": linear_velocity_rms(target),
    }


def bidirectional_circular_rotvecs(
    target: np.ndarray,
    *,
    config: CircularTemporalConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    config.validate()
    target = require_frame_major(target, name="target")
    if target.ndim != 2 or int(target.shape[-1]) != 3:
        raise ValueError("rotvecs must have shape (frames, 3)")
    if int(target.shape[0]) < 2 or float(config.blend) == 0.0:
        return target.copy(), {"applied": False, "reason": "too_short_or_zero_blend"}
    forward = _follow_rotvecs_tiled(target, config=config)
    reverse = _follow_rotvecs_tiled(target[::-1].copy(), config=config)[::-1].copy()
    merged = np.empty_like(target)
    for index in range(int(target.shape[0])):
        merged[index] = slerp_rotvec(forward[index], reverse[index], 0.5)
    if float(config.blend) == 1.0:
        out = merged
    else:
        out = np.empty_like(target)
        for index in range(int(target.shape[0])):
            out[index] = slerp_rotvec(target[index], merged[index], float(config.blend))
    return out, {
        "applied": True,
        "direction": "forward_and_backward",
        "periods": int(config.periods),
        "velocityRmsBefore": circular_velocity_rms(target),
        "velocityRmsAfter": circular_velocity_rms(out),
        "accelerationRmsBefore": circular_acceleration_rms(target),
        "accelerationRmsAfter": circular_acceleration_rms(out),
        "wrapVelocityRmsBefore": wrap_velocity_rms(target),
        "wrapVelocityRmsAfter": wrap_velocity_rms(out),
        "linearVelocityRmsBefore": linear_velocity_rms(target),
    }


def apply_circular_temporal_clip(
    bone_rotvecs: np.ndarray,
    root_translation: np.ndarray,
    root_rotation: np.ndarray,
    *,
    config: CircularTemporalConfig | None = None,
    wrap: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Apply bidirectional circular vel/accel follow to one clip.

    ``wrap=False`` is identity. Physics gravity/outliers are not used here.
    """
    cfg = CircularTemporalConfig() if config is None else config
    cfg.validate()
    bones = np.asarray(bone_rotvecs, dtype=np.float64)
    translation = np.asarray(root_translation, dtype=np.float64)
    rotation = np.asarray(root_rotation, dtype=np.float64)
    if bones.ndim != 3 or int(bones.shape[-1]) != 3:
        raise ValueError("bone_rotvecs must have shape (frames, bones, 3)")
    frames = int(bones.shape[0])
    if int(translation.shape[0]) != frames or int(rotation.shape[0]) != frames:
        raise ValueError("root arrays must use the same frame count as bone_rotvecs")
    if not wrap or frames < 2:
        return bones.copy(), translation.copy(), rotation.copy(), {
            "applied": False,
            "wrap": bool(wrap),
            "reason": "no_wrap_or_too_short",
        }

    bone_out = np.empty_like(bones)
    bone_reports: list[dict[str, Any]] = []
    wrap_before = []
    wrap_after = []
    for bone_index in range(int(bones.shape[1])):
        smoothed, report = bidirectional_circular_rotvecs(bones[:, bone_index, :], config=cfg)
        bone_out[:, bone_index, :] = smoothed
        bone_reports.append(report)
        wrap_before.append(float(report.get("wrapVelocityRmsBefore") or 0.0))
        wrap_after.append(float(report.get("wrapVelocityRmsAfter") or 0.0))
    translation_out, translation_report = bidirectional_circular_scalars(translation, config=cfg)
    rotation_out, rotation_report = bidirectional_circular_rotvecs(rotation, config=cfg)
    return bone_out, translation_out, rotation_out, {
        "applied": True,
        "wrap": True,
        "direction": "forward_and_backward",
        "periods": int(cfg.periods),
        "meanWrapVelocityRmsBefore": float(np.mean(wrap_before)) if wrap_before else 0.0,
        "meanWrapVelocityRmsAfter": float(np.mean(wrap_after)) if wrap_after else 0.0,
        "boneVelocityRmsBefore": circular_velocity_rms(bones),
        "boneVelocityRmsAfter": circular_velocity_rms(bone_out),
        "boneAccelerationRmsBefore": circular_acceleration_rms(bones),
        "boneAccelerationRmsAfter": circular_acceleration_rms(bone_out),
        "linearBoneVelocityRmsBefore": linear_velocity_rms(bones),
        "translation": translation_report,
        "rotation": rotation_report,
        "boneCount": int(bones.shape[1]),
        "frames": frames,
    }
