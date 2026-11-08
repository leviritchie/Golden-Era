#!/usr/bin/env python3
"""Black-box global clip optimization helpers.

The Blender worker is not differentiable, so the clip solver uses coordinate
proposals over frame/bone/axis variables.  The important distinction from the
legacy loop is that every proposal is scored against the complete current
clip state, including temporal regularizers.  The image scorer is injected by
the caller so this module stays independent of Blender and vision models.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import time
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from roc_rotation_search import (
    continuation_proposal,
    pose_value_to_quaternion,
    quaternion_pose_entry,
    quaternion_to_euler_xyz,
    rotation_vector_proposals,
)


FramePose = dict[str, dict[str, Any]]
# Root motion is a delivered animation variable, not a camera/image offset.
# Values are normalized body lengths in the model's forward/lateral/vertical
# basis. Keep the old key readable so prior pose JSON can still be imported.
MOTION_ROOT_KEY = "__motion_root__"
LEGACY_BODY_TRANSLATION_KEY = "__body_translation_px__"
BODY_TRANSLATION_KEY = MOTION_ROOT_KEY
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"
_MOTION_ROOT_TRANSLATION_KEYS = {MOTION_ROOT_KEY, LEGACY_BODY_TRANSLATION_KEY}
_MOTION_ROOT_KEYS = {
    *(_MOTION_ROOT_TRANSLATION_KEYS),
    MOTION_ROOT_ROTATION_KEY,
}
_MOTION_ROOT_AXES = ("forward", "lateral", "vertical")
_MOTION_ROOT_ROTATION_AXES = (
    "camera_forward",
    "camera_right",
    "camera_up",
)
ScoreFrame = Callable[[int, FramePose, str, bool], tuple[float, dict[str, Any], float]]
ScoreFrameBatch = Callable[..., Sequence[tuple[float, dict[str, Any], float]]]
RangeForBone = Callable[[str], tuple[float, float]]
ProgressCallback = Callable[[Mapping[str, Any]], None]


def _progress_stage(label: Any) -> str:
    """Keep the live bar readable without echoing the full proposal label."""
    parts = str(label or "evaluation").split()
    if not parts:
        return "evaluation"
    if parts[0].lower() == "clip" and len(parts) > 1:
        return f"clip {parts[1]}"
    return parts[0]


class ClipProgress:
    """Progress sink shared by warm-start and global clip optimization.

    A clip's exact evaluation count is data-dependent because batching, caches,
    proxy pruning, and adaptive stages can all change the number of proposals.
    The bar therefore reports completed unique evaluations instead of inventing
    a misleading percentage.  A callback or an existing tqdm-like object can
    be supplied for callers that own the display.
    """

    def __init__(self, progress: Any = True, *, description: str = "Clip optimization"):
        self.evaluations = 0
        self._callback: ProgressCallback | None = None
        self._bar = None
        self._owns_bar = False
        if progress is False:
            return
        if isinstance(progress, ClipProgress):
            raise TypeError("ClipProgress cannot wrap another ClipProgress")
        if callable(progress) and not isinstance(progress, bool):
            self._callback = progress
            return
        if hasattr(progress, "update") and not isinstance(progress, bool):
            self._bar = progress
            return
        if progress is not None and progress is not True:
            raise TypeError(
                "progress must be False, True, a callback, or a tqdm-like object"
            )
        try:
            from tqdm.auto import tqdm
        except ImportError as exc:  # pragma: no cover - dependency is part of the notebook env
            raise RuntimeError(
                "progress=True requires tqdm; install it in the notebook environment"
            ) from exc
        self._bar = tqdm(
            total=None,
            desc=description,
            unit="eval",
            dynamic_ncols=True,
            mininterval=0.25,
            leave=True,
        )
        self._owns_bar = True

    def emit(self, event: Mapping[str, Any]) -> None:
        if self._callback is None and self._bar is None:
            return
        payload = dict(event)
        self.evaluations += 1
        payload.setdefault("evaluation", self.evaluations)
        if self._callback is not None:
            self._callback(payload)
        if self._bar is None:
            return
        self._bar.update(1)
        stage = str(payload.get("stage") or _progress_stage(payload.get("label")))
        score = payload.get("score")
        suffix = f"{stage} evals={self.evaluations}"
        if isinstance(score, (int, float)):
            suffix += f" score={float(score):.4f}"
        set_postfix = getattr(self._bar, "set_postfix_str", None)
        if set_postfix is not None:
            set_postfix(suffix, refresh=False)

    def close(self) -> None:
        if self._bar is not None and self._owns_bar:
            self._bar.close()


def _root_enabled(config: "TemporalClipConfig") -> bool:
    value = config.motion_root_enabled
    return bool(config.body_translation_enabled) if value is None else bool(value)


def _root_axes(config: "TemporalClipConfig") -> tuple[str, ...]:
    raw = config.motion_root_axes
    if isinstance(raw, str):
        raw = tuple(part.strip() for part in raw.split(",") if part.strip())
    return tuple(str(axis).strip().lower() for axis in raw)


def _root_limits(config: "TemporalClipConfig") -> dict[str, float]:
    return {
        "forward": float(config.motion_root_forward_radius_body_lengths),
        "lateral": float(config.motion_root_lateral_radius_body_lengths),
        "vertical": float(config.motion_root_vertical_radius_body_lengths),
    }


def _root_rotation_enabled(config: "TemporalClipConfig") -> bool:
    return bool(config.motion_root_rotation_enabled)


def _root_rotation_axes(config: "TemporalClipConfig") -> tuple[str, ...]:
    raw = config.motion_root_rotation_axes
    if isinstance(raw, str):
        raw = tuple(part.strip() for part in raw.split(",") if part.strip())
    return tuple(str(axis).strip().lower() for axis in raw)


def _root_rotation_escape_axes(config: "TemporalClipConfig") -> tuple[str, ...]:
    raw = config.motion_root_rotation_escape_axes
    if isinstance(raw, str):
        raw = tuple(part.strip() for part in raw.split(",") if part.strip())
    return tuple(str(axis).strip().lower() for axis in raw)


def _root_rotation_escape_hypotheses(
    config: "TemporalClipConfig",
    *,
    max_count: int = 16,
) -> list[dict[str, float]]:
    """Build a small diverse rigid-attitude library around the current pose.

    The first seven entries are identity plus signed single-axis quarter turns;
    the remaining budget is filled with pair/triple combinations. This keeps
    the escape wave bounded while allowing a useful orientation to require
    more than one camera-relative axis.
    """
    axes = _root_rotation_escape_axes(config)
    if not axes:
        return []
    limit = float(config.motion_root_rotation_limit_deg)
    configured = [
        float(np.clip(value, -limit, limit))
        for value in config.motion_root_rotation_escape_angles_deg
    ]
    magnitude = min(
        limit,
        min(configured, key=lambda value: abs(abs(value) - 90.0))
        if configured
        else 90.0,
    )
    magnitude = abs(float(magnitude))
    if magnitude <= 1e-8:
        magnitude = min(limit, 90.0)
    values_by_axis = {
        axis: (-magnitude, magnitude)
        for axis in axes
    }
    hypotheses: list[dict[str, float]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()

    def add(values: Mapping[str, float]) -> None:
        normalized = {
            axis: float(np.clip(values.get(axis, 0.0), -limit, limit))
            for axis in axes
        }
        key = tuple((axis, round(normalized[axis], 6)) for axis in axes)
        if key not in seen:
            seen.add(key)
            hypotheses.append(normalized)

    add({})
    for axis in axes:
        for value in values_by_axis[axis]:
            add({axis: value})
    for pair in combinations(axes, 2):
        for signs in product((-1.0, 1.0), repeat=2):
            add({pair[index]: signs[index] * magnitude for index in range(2)})
    if len(axes) >= 3:
        for signs in product((-1.0, 1.0), repeat=len(axes)):
            add({axis: signs[index] * magnitude for index, axis in enumerate(axes)})
    return hypotheses[: max(1, int(max_count))]


def _root_rotation_limits(config: "TemporalClipConfig") -> dict[str, float]:
    limit = float(config.motion_root_rotation_limit_deg)
    return {axis: limit for axis in _MOTION_ROOT_ROTATION_AXES}


def _root_rotation_weight(config: "TemporalClipConfig", name: str) -> float:
    value = getattr(config, f"motion_root_rotation_{name}_weight", None)
    if value is None:
        return 0.0
    return float(value)


def _root_weight(config: "TemporalClipConfig", name: str) -> float:
    """Resolve new root weights while honoring the two old aliases."""
    value = getattr(config, f"motion_root_{name}_weight", None)
    if value is not None:
        return float(value)
    return float(getattr(config, f"body_translation_{name}_weight", 0.0))


def _is_motion_root_bone(bone: str) -> bool:
    return str(bone) in _MOTION_ROOT_KEYS


def _is_motion_root_translation_bone(bone: str) -> bool:
    return str(bone) in _MOTION_ROOT_TRANSLATION_KEYS


def _is_motion_root_rotation_bone(bone: str) -> bool:
    return str(bone) == MOTION_ROOT_ROTATION_KEY


def _motion_root_entry(pose: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = pose.get(MOTION_ROOT_KEY)
    return raw if isinstance(raw, Mapping) else {}


def _motion_root_rotation_entry(pose: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = pose.get(MOTION_ROOT_ROTATION_KEY)
    return raw if isinstance(raw, Mapping) else {}


@dataclass(frozen=True)
class TemporalClipConfig:
    """Configuration for the global objective and local coordinate proposals."""

    rounds: int = 1
    velocity_weight: float = 0.08
    acceleration_weight: float = 0.04
    contact_weight: float = 0.0
    loop_weight: float = 0.0
    loop_velocity_weight: float = 0.0
    robust_scale_deg: float = 16.0
    robust_epsilon: float = 1e-3
    coarse_step_deg: float = 16.0
    refine_step_deg: float = 4.0
    refine_rounds: int = 1
    refine_accepted_only: bool = True
    max_evaluations_per_axis: int = 24
    # A bind-pose warm start can be far from the target. Local +/-step probes
    # can reject both directions before reaching the useful part of the range.
    candidate_mode: str = "range_extremes"
    # Reject embedding-scale numerical blips instead of committing them.
    acceptance_margin: float = 0.001
    acceptance_relative_margin: float = 0.0
    preview_candidates: bool = True
    batch_candidates: bool = True
    axes: tuple[str, ...] = ("x", "z")
    contact_bones: tuple[str, ...] = ()
    loop_enabled: bool = False
    # New root-motion contract. None preserves the old body_translation_enabled
    # switch for callers that have not migrated their config yet.
    motion_root_enabled: bool | None = None
    motion_root_axes: tuple[str, ...] | str = ("forward",)
    motion_root_forward_radius_body_lengths: float = 0.20
    motion_root_lateral_radius_body_lengths: float = 0.05
    motion_root_vertical_radius_body_lengths: float = 0.0
    motion_root_coarse_step_body_lengths: float = 0.05
    motion_root_refine_step_body_lengths: float = 0.0125
    motion_root_magnitude_weight: float = 0.01
    motion_root_velocity_weight: float | None = None
    motion_root_acceleration_weight: float | None = None
    motion_root_loop_weight: float = 0.0
    motion_root_loop_velocity_weight: float | None = None
    # Rigid-body attitude is deliberately separate from local bone rotation.
    # The worker resolves these axes in the fitted camera basis and applies the
    # resulting transform above the Meshy armature.
    motion_root_rotation_enabled: bool = False
    motion_root_rotation_basis: str = "camera"
    motion_root_rotation_axes: tuple[str, ...] | str = ("camera_forward",)
    motion_root_rotation_limit_deg: float = 180.0
    motion_root_rotation_coarse_step_deg: float = 30.0
    motion_root_rotation_refine_step_deg: float = 10.0
    motion_root_rotation_escape_enabled: bool = True
    motion_root_rotation_escape_axes: tuple[str, ...] | str = ("camera_forward",)
    motion_root_rotation_escape_angles_deg: tuple[float, ...] = (
        -180.0,
        -150.0,
        -120.0,
        -90.0,
        -60.0,
        -30.0,
        30.0,
        60.0,
        90.0,
        120.0,
        150.0,
        180.0,
    )
    motion_root_rotation_escape_top_k: int = 4
    motion_root_rotation_escape_force_image_best: bool = True
    motion_root_rotation_escape_min_image_improvement: float = 0.0
    # A rigid attitude can look poor until a few high-level local bones are
    # allowed to relax around it.  This is deliberately order-driven rather
    # than anatomy-driven so the same pass works for arbitrary Meshy rigs.
    motion_root_rotation_escape_relax_enabled: bool = True
    motion_root_rotation_escape_relax_bone_count: int = 3
    motion_root_rotation_escape_relax_rounds: int = 1
    motion_root_rotation_escape_relax_step_deg: float = 12.0
    motion_root_rotation_escape_relax_refine_step_deg: float = 4.0
    motion_root_rotation_magnitude_weight: float = 0.0
    motion_root_rotation_velocity_weight: float | None = None
    motion_root_rotation_acceleration_weight: float | None = None
    motion_root_rotation_loop_weight: float = 0.0
    motion_root_rotation_loop_velocity_weight: float | None = None
    motion_root_coupled_blocks_enabled: bool = True
    motion_root_rotation_coupled_blocks_enabled: bool = True
    # Deprecated pixel-offset aliases. They are retained only to read old
    # configs/poses; new optimization variables never use image pixels.
    body_translation_enabled: bool = False
    body_translation_radius_px: float = 48.0
    body_translation_coarse_step_px: float = 12.0
    body_translation_refine_step_px: float = 3.0
    body_translation_velocity_weight: float = 0.02
    body_translation_acceleration_weight: float = 0.01
    probe_enabled: bool = True
    probe_step_deg: float = 30.0
    probe_top_k: int = 12
    probe_min_improvement: float = -0.005
    adaptive_blocks_enabled: bool = True
    adaptive_block_size: int = 3
    adaptive_rounds: int = 1
    adaptive_step_deg: float = 10.0
    adaptive_beam_width: int = 4
    polish_enabled: bool = True
    polish_rounds: int = 1
    polish_step_deg: float = 2.0
    sensitivity_enabled: bool = True
    sensitivity_score_epsilon: float = 0.002
    polish_include_neighbors: bool = True
    adaptive_groups: tuple[tuple[str, ...], ...] = ()
    # Optional arbitrary-axis probes. The vector frame is derived from the
    # imported rig's rest-space shaft, not from guessed Euler axis names.
    rotation_vector_search_enabled: bool = False
    rotation_vector_probe_count: int = 8
    rotation_vector_probe_step_deg: float = 16.0
    rotation_vector_legacy_euler_fallback_enabled: bool = True
    rotation_vector_informative_min_improvement: float = 0.0
    directional_continuation_enabled: bool = False
    directional_max_steps: int = 4
    directional_step_multiplier: float = 2.0
    directional_top_k: int = 2
    directional_min_improvement: float = 0.0
    adaptive_block_learned_directions_enabled: bool = True
    bone_twist_policy: str = "adaptive"
    bone_twist_overrides: dict[str, str] = field(default_factory=dict)
    bone_vectors: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    def validate(self) -> None:
        if int(self.rounds) < 1:
            raise ValueError("clip rounds must be at least 1")
        if int(self.refine_rounds) < 1:
            raise ValueError("clip refine rounds must be at least 1")
        if int(self.max_evaluations_per_axis) < 1:
            raise ValueError("clip max evaluations per axis must be positive")
        if str(self.candidate_mode).lower() not in {"local", "range_extremes"}:
            raise ValueError("candidate_mode must be local or range_extremes")
        for name in ("acceptance_margin", "acceptance_relative_margin"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "velocity_weight",
            "acceleration_weight",
            "contact_weight",
            "loop_weight",
            "loop_velocity_weight",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not math.isfinite(float(self.robust_scale_deg)) or float(self.robust_scale_deg) <= 0.0:
            raise ValueError("robust_scale_deg must be finite and positive")
        if not math.isfinite(float(self.robust_epsilon)) or float(self.robust_epsilon) <= 0.0:
            raise ValueError("robust_epsilon must be finite and positive")
        if not math.isfinite(float(self.coarse_step_deg)) or float(self.coarse_step_deg) <= 0.0:
            raise ValueError("coarse_step_deg must be finite and positive")
        if not math.isfinite(float(self.refine_step_deg)) or float(self.refine_step_deg) <= 0.0:
            raise ValueError("refine_step_deg must be finite and positive")
        if float(self.refine_step_deg) > float(self.coarse_step_deg):
            raise ValueError("refine_step_deg must not exceed coarse_step_deg")
        root_axes = _root_axes(self)
        if _root_enabled(self) and not root_axes:
            raise ValueError("motion_root_axes must be non-empty when motion root is enabled")
        if any(axis not in _MOTION_ROOT_AXES for axis in root_axes):
            raise ValueError(
                "motion_root_axes must be a subset of forward, lateral, vertical"
            )
        for name in (
            "motion_root_forward_radius_body_lengths",
            "motion_root_lateral_radius_body_lengths",
            "motion_root_vertical_radius_body_lengths",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        root_radii = _root_limits(self)
        if _root_enabled(self):
            for axis in root_axes:
                if root_radii[axis] <= 0.0:
                    raise ValueError(
                        f"motion_root_{axis}_radius_body_lengths must be positive "
                        f"when {axis!r} is enabled"
                    )
        for name in (
            "motion_root_coarse_step_body_lengths",
            "motion_root_refine_step_body_lengths",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if float(self.motion_root_refine_step_body_lengths) > float(self.motion_root_coarse_step_body_lengths):
            raise ValueError(
                "motion_root_refine_step_body_lengths must not exceed "
                "motion_root_coarse_step_body_lengths"
            )
        rotation_axes = _root_rotation_axes(self)
        escape_axes = self.motion_root_rotation_escape_axes
        if isinstance(escape_axes, str):
            escape_axes = tuple(
                part.strip() for part in escape_axes.split(",") if part.strip()
            )
        else:
            escape_axes = tuple(
                str(axis).strip().lower() for axis in escape_axes if str(axis).strip()
            )
        if str(self.motion_root_rotation_basis).strip().lower() != "camera":
            raise ValueError("motion_root_rotation_basis must be 'camera'")
        if _root_rotation_enabled(self) and not rotation_axes:
            raise ValueError(
                "motion_root_rotation_axes must be non-empty when rigid root rotation is enabled"
            )
        if any(axis not in _MOTION_ROOT_ROTATION_AXES for axis in rotation_axes):
            raise ValueError(
                "motion_root_rotation_axes must be a subset of camera_forward, camera_right, camera_up"
            )
        if any(axis not in _MOTION_ROOT_ROTATION_AXES for axis in escape_axes):
            raise ValueError(
                "motion_root_rotation_escape_axes must be a subset of camera_forward, camera_right, camera_up"
            )
        if not set(escape_axes).issubset(set(rotation_axes)):
            raise ValueError(
                "motion_root_rotation_escape_axes must be a subset of motion_root_rotation_axes"
            )
        for name in (
            "motion_root_rotation_limit_deg",
            "motion_root_rotation_coarse_step_deg",
            "motion_root_rotation_refine_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if float(self.motion_root_rotation_refine_step_deg) > float(
            self.motion_root_rotation_coarse_step_deg
        ):
            raise ValueError(
                "motion_root_rotation_refine_step_deg must not exceed "
                "motion_root_rotation_coarse_step_deg"
            )
        escape_angles = tuple(float(angle) for angle in self.motion_root_rotation_escape_angles_deg)
        if not escape_angles:
            raise ValueError("motion_root_rotation_escape_angles_deg must not be empty")
        if any(
            not math.isfinite(angle)
            or abs(angle) > float(self.motion_root_rotation_limit_deg) + 1e-8
            for angle in escape_angles
        ):
            raise ValueError(
                "motion_root_rotation_escape_angles_deg must stay within "
                "motion_root_rotation_limit_deg"
            )
        if int(self.motion_root_rotation_escape_top_k) < 1:
            raise ValueError("motion_root_rotation_escape_top_k must be positive")
        if int(self.motion_root_rotation_escape_relax_bone_count) < 0:
            raise ValueError(
                "motion_root_rotation_escape_relax_bone_count must be non-negative"
            )
        if int(self.motion_root_rotation_escape_relax_rounds) < 1:
            raise ValueError(
                "motion_root_rotation_escape_relax_rounds must be positive"
            )
        for name in (
            "motion_root_rotation_escape_relax_step_deg",
            "motion_root_rotation_escape_relax_refine_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if (
            float(self.motion_root_rotation_escape_relax_refine_step_deg)
            > float(self.motion_root_rotation_escape_relax_step_deg)
        ):
            raise ValueError(
                "motion_root_rotation_escape_relax_refine_step_deg must not exceed "
                "motion_root_rotation_escape_relax_step_deg"
            )
        if not math.isfinite(float(self.motion_root_rotation_escape_min_image_improvement)):
            raise ValueError(
                "motion_root_rotation_escape_min_image_improvement must be finite"
            )
        for name in (
            "motion_root_rotation_magnitude_weight",
            "motion_root_rotation_loop_weight",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "motion_root_rotation_velocity_weight",
            "motion_root_rotation_acceleration_weight",
            "motion_root_rotation_loop_velocity_weight",
        ):
            value = _root_rotation_weight(
                self,
                name.removeprefix("motion_root_rotation_").removesuffix("_weight"),
            )
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "body_translation_radius_px",
            "body_translation_coarse_step_px",
            "body_translation_refine_step_px",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if float(self.body_translation_refine_step_px) > float(self.body_translation_coarse_step_px):
            raise ValueError("body_translation_refine_step_px must not exceed body_translation_coarse_step_px")
        for name in (
            "motion_root_magnitude_weight",
            "motion_root_loop_weight",
            "body_translation_velocity_weight",
            "body_translation_acceleration_weight",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "motion_root_velocity_weight",
            "motion_root_acceleration_weight",
            "motion_root_loop_velocity_weight",
        ):
            value = _root_weight(self, name.removeprefix("motion_root_").removesuffix("_weight"))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in ("probe_step_deg", "adaptive_step_deg", "polish_step_deg"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if int(self.probe_top_k) < 1:
            raise ValueError("probe_top_k must be positive")
        if not math.isfinite(float(self.probe_min_improvement)):
            raise ValueError("probe_min_improvement must be finite")
        if int(self.adaptive_block_size) < 2:
            raise ValueError("adaptive_block_size must be at least 2")
        if int(self.adaptive_beam_width) < 1:
            raise ValueError("adaptive_beam_width must be positive")
        if int(self.adaptive_rounds) < 1 or int(self.polish_rounds) < 1:
            raise ValueError("adaptive/polish rounds must be at least 1")
        if float(self.adaptive_step_deg) > float(self.probe_step_deg):
            raise ValueError("adaptive_step_deg must not exceed probe_step_deg")
        if float(self.polish_step_deg) > float(self.adaptive_step_deg):
            raise ValueError("polish_step_deg must not exceed adaptive_step_deg")
        if not math.isfinite(float(self.sensitivity_score_epsilon)) or float(self.sensitivity_score_epsilon) < 0.0:
            raise ValueError("sensitivity_score_epsilon must be finite and non-negative")
        if int(self.rotation_vector_probe_count) < 4:
            raise ValueError("rotation_vector_probe_count must be at least 4")
        if not math.isfinite(float(self.rotation_vector_probe_step_deg)) or float(self.rotation_vector_probe_step_deg) <= 0.0:
            raise ValueError("rotation_vector_probe_step_deg must be finite and positive")
        if not math.isfinite(float(self.rotation_vector_informative_min_improvement)):
            raise ValueError("rotation_vector_informative_min_improvement must be finite")
        if int(self.directional_max_steps) < 1:
            raise ValueError("directional_max_steps must be at least 1")
        if int(self.directional_top_k) < 1:
            raise ValueError("directional_top_k must be at least 1")
        if not math.isfinite(float(self.directional_step_multiplier)) or float(self.directional_step_multiplier) <= 1.0:
            raise ValueError("directional_step_multiplier must be finite and greater than 1")
        if not math.isfinite(float(self.directional_min_improvement)):
            raise ValueError("directional_min_improvement must be finite")
        twist_policy = str(self.bone_twist_policy).strip().lower()
        if twist_policy not in {"adaptive", "include", "exclude"}:
            raise ValueError("bone_twist_policy must be adaptive, include, or exclude")
        invalid_twist = {
            str(name): str(policy)
            for name, policy in self.bone_twist_overrides.items()
            if str(policy).strip().lower() not in {"adaptive", "include", "exclude"}
        }
        if invalid_twist:
            raise ValueError(f"bone_twist_overrides contains invalid policies: {invalid_twist}")
        axes = tuple(str(axis).lower() for axis in self.axes)
        if not axes or any(axis not in {"x", "y", "z"} for axis in axes):
            raise ValueError("clip axes must be a non-empty subset of x, y, z")


def _axis_values(entry: Any) -> np.ndarray:
    """Convert the pipeline's sparse axis/angle pose form to radians XYZ."""
    if not isinstance(entry, Mapping):
        try:
            return np.array([0.0, 0.0, float(entry)], dtype=np.float64)
        except (TypeError, ValueError):
            return np.zeros(3, dtype=np.float64)
    if "axis" in entry:
        values = np.zeros(3, dtype=np.float64)
        axis = str(entry.get("axis", "z")).lower()
        if axis in {"x", "y", "z"}:
            values["xyz".index(axis)] = float(entry.get("angle", 0.0))
        return values
    if "quaternion" in entry:
        quaternion = pose_value_to_quaternion(entry)
        return np.asarray(
            [float(value) for value in quaternion_to_euler_xyz(quaternion)],
            dtype=np.float64,
        )
    return np.array(
        [float(entry.get(axis, 0.0)) for axis in ("x", "y", "z")],
        dtype=np.float64,
    )


def pose_matrix(
    pose: Mapping[str, Any],
    bones: Sequence[str],
) -> np.ndarray:
    """Return a deterministic ``bone x xyz`` pose matrix in degrees."""
    return np.stack(
        [
            np.degrees(_axis_values(pose.get(bone, {})))
            for bone in bones
            if not _is_motion_root_bone(bone)
        ],
        axis=0,
    ) if any(not _is_motion_root_bone(bone) for bone in bones) else np.zeros((0, 3), dtype=np.float64)


def translation_matrix(
    poses: Mapping[int, Mapping[str, Any]],
    frame_indices: Sequence[int],
) -> np.ndarray:
    """Return new-contract root motion as forward/lateral/vertical body lengths.

    Legacy ``__body_translation_px__`` entries are intentionally not converted
    here.  This module has no camera pixel scale, so treating those values as
    body lengths would silently turn a small pixel offset into a huge world
    displacement.  The Blender worker still accepts an explicit legacy pixel
    request through its compatibility path.
    """
    return np.asarray(
        [
            [
                float(
                    _motion_root_entry(poses.get(frame, {})).get(
                        axis,
                        0.0,
                    )
                )
                for axis in _MOTION_ROOT_AXES
            ]
            for frame in frame_indices
        ],
        dtype=np.float64,
    )


def rotation_matrix(
    poses: Mapping[int, Mapping[str, Any]],
    frame_indices: Sequence[int],
) -> np.ndarray:
    """Return camera-relative rigid-root rotation components in degrees."""
    return np.asarray(
        [
            [
                float(
                    _motion_root_rotation_entry(poses.get(frame, {})).get(
                        axis,
                        0.0,
                    )
                )
                for axis in _MOTION_ROOT_ROTATION_AXES
            ]
            for frame in frame_indices
        ],
        dtype=np.float64,
    )


def _wrapped_degree_delta(end: np.ndarray, start: np.ndarray) -> np.ndarray:
    """Return shortest component-wise degree deltas for root rotation."""
    return (np.asarray(end, dtype=np.float64) - np.asarray(start, dtype=np.float64) + 180.0) % 360.0 - 180.0


def _robust_mean(values: np.ndarray, scale: float, epsilon: float) -> float:
    if values.size == 0:
        return 0.0
    normalized = np.asarray(values, dtype=np.float64) / float(scale)
    rho = np.sqrt(normalized * normalized + float(epsilon) ** 2) - float(epsilon)
    return float(np.mean(rho))


def temporal_terms(
    poses: Mapping[int, Mapping[str, Any]],
    frame_indices: Sequence[int],
    bones: Sequence[str],
    config: TemporalClipConfig,
) -> dict[str, float]:
    """Compute normalized robust temporal penalties for the current clip."""
    config.validate()
    frames = list(frame_indices)
    rotation_bones = [bone for bone in bones if not _is_motion_root_bone(bone)]
    matrices = [pose_matrix(poses.get(frame, {}), rotation_bones) for frame in frames]
    translations = translation_matrix(poses, frames)
    root_rotations = rotation_matrix(poses, frames)
    root_enabled = _root_enabled(config)
    root_axes = _root_axes(config) if root_enabled else ()
    root_rotation_enabled = _root_rotation_enabled(config)
    root_rotation_axes = (
        _root_rotation_axes(config) if root_rotation_enabled else ()
    )
    if root_enabled:
        active_indices = [
            index for index, axis in enumerate(_MOTION_ROOT_AXES) if axis in root_axes
        ]
        inactive_indices = [
            index for index in range(len(_MOTION_ROOT_AXES)) if index not in active_indices
        ]
        if inactive_indices and translations.size:
            translations[:, inactive_indices] = 0.0
    elif translations.size:
        translations[...] = 0.0
    root_scale = max(_root_limits(config).get(axis, 0.0) for axis in root_axes) if root_axes else 1.0
    root_scale = max(float(root_scale), 1e-6)
    if root_rotation_enabled:
        active_rotation_indices = [
            index
            for index, axis in enumerate(_MOTION_ROOT_ROTATION_AXES)
            if axis in root_rotation_axes
        ]
        inactive_rotation_indices = [
            index
            for index in range(len(_MOTION_ROOT_ROTATION_AXES))
            if index not in active_rotation_indices
        ]
        if inactive_rotation_indices and root_rotations.size:
            root_rotations[:, inactive_rotation_indices] = 0.0
    elif root_rotations.size:
        root_rotations[...] = 0.0
    root_rotation_scale = max(
        float(config.motion_root_rotation_limit_deg),
        1e-6,
    )
    if len(matrices) < 2:
        velocity = 0.0
        contact = 0.0
        motion_root_velocity = 0.0
        motion_root_rotation_velocity = 0.0
    else:
        velocities = [matrices[i] - matrices[i - 1] for i in range(1, len(matrices))]
        velocity = _robust_mean(
            np.concatenate([value.reshape(-1) for value in velocities]),
            config.robust_scale_deg,
            config.robust_epsilon,
        )
        contact_indices = [rotation_bones.index(bone) for bone in config.contact_bones if bone in rotation_bones]
        contact_values = [
            velocity_matrix[contact_indices].reshape(-1)
            for velocity_matrix in velocities
            if contact_indices
        ]
        contact = (
            _robust_mean(np.concatenate(contact_values), config.robust_scale_deg, config.robust_epsilon)
            if contact_values
            else 0.0
        )
        motion_root_velocity = _robust_mean(
            np.concatenate(
                [
                    (translations[i] - translations[i - 1]).reshape(-1)
                    for i in range(1, len(translations))
                ]
            ),
            root_scale,
            config.robust_epsilon,
        )
        motion_root_rotation_velocity = _robust_mean(
            np.concatenate(
                [
                    _wrapped_degree_delta(root_rotations[i], root_rotations[i - 1]).reshape(-1)
                    for i in range(1, len(root_rotations))
                ]
            ),
            root_rotation_scale,
            config.robust_epsilon,
        )
    root_magnitude = (
        _robust_mean(
            np.linalg.norm(translations, axis=1),
            root_scale,
            config.robust_epsilon,
        )
        if root_enabled
        else 0.0
    )
    root_rotation_magnitude = (
        _robust_mean(
            np.linalg.norm(root_rotations, axis=1),
            root_rotation_scale,
            config.robust_epsilon,
        )
        if root_rotation_enabled
        else 0.0
    )

    if len(matrices) < 3:
        acceleration = 0.0
        motion_root_acceleration = 0.0
        motion_root_rotation_acceleration = 0.0
    else:
        accelerations = [
            (matrices[i + 1] - matrices[i]) - (matrices[i] - matrices[i - 1])
            for i in range(1, len(matrices) - 1)
        ]
        acceleration = _robust_mean(
            np.concatenate([value.reshape(-1) for value in accelerations]),
            config.robust_scale_deg,
            config.robust_epsilon,
        )
        motion_root_acceleration = _robust_mean(
            np.concatenate(
                [
                    ((translations[i + 1] - translations[i]) - (translations[i] - translations[i - 1])).reshape(-1)
                    for i in range(1, len(translations) - 1)
                ]
            ),
            root_scale,
            config.robust_epsilon,
        )
        root_rotation_velocities = [
            _wrapped_degree_delta(root_rotations[i], root_rotations[i - 1])
            for i in range(1, len(root_rotations))
        ]
        motion_root_rotation_acceleration = _robust_mean(
            np.concatenate(
                [
                    _wrapped_degree_delta(
                        root_rotation_velocities[i],
                        root_rotation_velocities[i - 1],
                    ).reshape(-1)
                    for i in range(1, len(root_rotation_velocities))
                ]
            ),
            root_rotation_scale,
            config.robust_epsilon,
        )
    if not root_enabled:
        motion_root_velocity = 0.0
        motion_root_acceleration = 0.0
    if not root_rotation_enabled:
        motion_root_rotation_velocity = 0.0
        motion_root_rotation_acceleration = 0.0

    loop = 0.0
    loop_velocity = 0.0
    motion_root_loop = 0.0
    motion_root_loop_velocity = 0.0
    motion_root_rotation_loop = 0.0
    motion_root_rotation_loop_velocity = 0.0
    root_loop_enabled = root_enabled and (
        bool(config.loop_enabled)
        or float(config.motion_root_loop_weight) > 0.0
        or _root_weight(config, "loop_velocity") > 0.0
    )
    root_rotation_enabled = _root_rotation_enabled(config)
    root_rotation_loop_enabled = root_rotation_enabled and (
        bool(config.loop_enabled)
        or float(config.motion_root_rotation_loop_weight) > 0.0
        or _root_rotation_weight(config, "loop_velocity") > 0.0
    )
    if config.loop_enabled and len(matrices) >= 2:
        loop = _robust_mean(
            (matrices[0] - matrices[-1]).reshape(-1),
            config.robust_scale_deg,
            config.robust_epsilon,
        )
        if len(matrices) >= 3:
            first_velocity = matrices[1] - matrices[0]
            last_velocity = matrices[-1] - matrices[-2]
            seam = first_velocity - last_velocity
            loop_velocity = _robust_mean(
                seam.reshape(-1),
                config.robust_scale_deg,
                config.robust_epsilon,
            )
    if root_loop_enabled and len(translations) >= 2:
        motion_root_loop = _robust_mean(
            (translations[0] - translations[-1]).reshape(-1),
            root_scale,
            config.robust_epsilon,
        )
        if len(translations) >= 3:
            first_root_velocity = translations[1] - translations[0]
            last_root_velocity = translations[-1] - translations[-2]
            motion_root_loop_velocity = _robust_mean(
                (first_root_velocity - last_root_velocity).reshape(-1),
                root_scale,
                config.robust_epsilon,
            )
    root_rotation_loop_enabled = root_rotation_enabled and (
        bool(config.loop_enabled)
        or float(config.motion_root_rotation_loop_weight) > 0.0
        or _root_rotation_weight(config, "loop_velocity") > 0.0
    )
    if root_rotation_loop_enabled and len(root_rotations) >= 2:
        motion_root_rotation_loop = _robust_mean(
            _wrapped_degree_delta(root_rotations[0], root_rotations[-1]).reshape(-1),
            root_rotation_scale,
            config.robust_epsilon,
        )
        if len(root_rotations) >= 3:
            first_root_rotation_velocity = _wrapped_degree_delta(
                root_rotations[1], root_rotations[0]
            )
            last_root_rotation_velocity = _wrapped_degree_delta(
                root_rotations[-1], root_rotations[-2]
            )
            motion_root_rotation_loop_velocity = _robust_mean(
                _wrapped_degree_delta(
                    first_root_rotation_velocity,
                    last_root_rotation_velocity,
                ).reshape(-1),
                root_rotation_scale,
                config.robust_epsilon,
            )
    return {
        "velocity": float(velocity),
        "acceleration": float(acceleration),
        "contact": float(contact),
        "loop": float(loop),
        "loopVelocity": float(loop_velocity),
        "motionRootMagnitude": float(root_magnitude),
        "motionRootVelocity": float(motion_root_velocity),
        "motionRootAcceleration": float(motion_root_acceleration),
        "motionRootLoop": float(motion_root_loop),
        "motionRootLoopVelocity": float(motion_root_loop_velocity),
        "motionRootRotationMagnitude": float(root_rotation_magnitude),
        "motionRootRotationVelocity": float(motion_root_rotation_velocity),
        "motionRootRotationAcceleration": float(motion_root_rotation_acceleration),
        "motionRootRotationLoop": float(motion_root_rotation_loop),
        "motionRootRotationLoopVelocity": float(motion_root_rotation_loop_velocity),
        # Compatibility names for old notebook output readers. They are not
        # separate penalties and are never added twice to the objective.
        "bodyTranslationVelocity": float(motion_root_velocity),
        "bodyTranslationAcceleration": float(motion_root_acceleration),
    }


def clip_objective(
    image_scores: Mapping[int, float],
    poses: Mapping[int, Mapping[str, Any]],
    frame_indices: Sequence[int],
    bones: Sequence[str],
    config: TemporalClipConfig,
) -> tuple[float, dict[str, Any]]:
    """Return quality to maximize and its component ledger."""
    terms = temporal_terms(poses, frame_indices, bones, config)
    root_enabled = _root_enabled(config)
    root_loop_enabled = root_enabled and (
        bool(config.loop_enabled)
        or float(config.motion_root_loop_weight) > 0.0
        or _root_weight(config, "loop_velocity") > 0.0
    )
    root_rotation_enabled = _root_rotation_enabled(config)
    root_rotation_loop_enabled = root_rotation_enabled and (
        bool(config.loop_enabled)
        or float(config.motion_root_rotation_loop_weight) > 0.0
        or _root_rotation_weight(config, "loop_velocity") > 0.0
    )
    scores = [float(image_scores[frame]) for frame in frame_indices]
    image = float(np.mean(scores)) if scores else 0.0
    penalties = {
        "velocity": float(config.velocity_weight) * terms["velocity"],
        "acceleration": float(config.acceleration_weight) * terms["acceleration"],
        "contact": float(config.contact_weight) * terms["contact"],
        "loop": float(config.loop_weight) * terms["loop"] if config.loop_enabled else 0.0,
        "loopVelocity": (
            float(config.loop_velocity_weight) * terms["loopVelocity"]
            if config.loop_enabled
            else 0.0
        ),
        "motionRootMagnitude": (
            float(config.motion_root_magnitude_weight) * terms["motionRootMagnitude"]
            if root_enabled
            else 0.0
        ),
        "motionRootVelocity": (
            _root_weight(config, "velocity") * terms["motionRootVelocity"]
            if root_enabled
            else 0.0
        ),
        "motionRootAcceleration": (
            _root_weight(config, "acceleration") * terms["motionRootAcceleration"]
            if root_enabled
            else 0.0
        ),
        "motionRootLoop": float(config.motion_root_loop_weight)
        * terms["motionRootLoop"]
        if root_loop_enabled
        else 0.0,
        "motionRootLoopVelocity": _root_weight(config, "loop_velocity")
        * terms["motionRootLoopVelocity"]
        if root_loop_enabled
        else 0.0,
        "motionRootRotationMagnitude": (
            float(config.motion_root_rotation_magnitude_weight)
            * terms["motionRootRotationMagnitude"]
            if root_rotation_enabled
            else 0.0
        ),
        "motionRootRotationVelocity": (
            _root_rotation_weight(config, "velocity")
            * terms["motionRootRotationVelocity"]
            if root_rotation_enabled
            else 0.0
        ),
        "motionRootRotationAcceleration": (
            _root_rotation_weight(config, "acceleration")
            * terms["motionRootRotationAcceleration"]
            if root_rotation_enabled
            else 0.0
        ),
        "motionRootRotationLoop": (
            float(config.motion_root_rotation_loop_weight)
            * terms["motionRootRotationLoop"]
            if root_rotation_loop_enabled
            else 0.0
        ),
        "motionRootRotationLoopVelocity": (
            _root_rotation_weight(config, "loop_velocity")
            * terms["motionRootRotationLoopVelocity"]
            if root_rotation_loop_enabled
            else 0.0
        ),
    }
    score = float(image - sum(penalties.values()))
    return score, {
        "image": image,
        "temporal": terms,
        "penalties": penalties,
        "objective": score,
        "frameScores": {str(frame): float(image_scores[frame]) for frame in frame_indices},
    }


def _pose_key(pose: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(pose, sort_keys=True, separators=(",", ":"), default=float).encode("utf-8")
    ).hexdigest()


def _canonical_pose(pose: Mapping[str, Any], bones: Sequence[str]) -> FramePose:
    result: FramePose = {}
    for bone in bones:
        if _is_motion_root_translation_bone(bone):
            raw = _motion_root_entry(pose)
            result[bone] = {
                axis: float(
                    raw.get(
                        axis,
                        raw.get(
                            {"forward": "z", "lateral": "x", "vertical": "y"}[axis],
                            0.0,
                        ),
                    )
                )
                for axis in _MOTION_ROOT_AXES
            }
            continue
        if _is_motion_root_rotation_bone(bone):
            raw = _motion_root_rotation_entry(pose)
            result[bone] = {
                axis: float(raw.get(axis, 0.0))
                for axis in _MOTION_ROOT_ROTATION_AXES
            }
            continue
        raw = pose.get(bone, {})
        if isinstance(raw, Mapping) and "quaternion" in raw:
            entry = quaternion_pose_entry(
                pose_value_to_quaternion(raw),
                twist_policy=str(raw.get("twistPolicy", "exclude")),
            )
            result[bone] = entry
        else:
            values = _axis_values(raw)
            result[bone] = {axis: float(values[index]) for index, axis in enumerate(("x", "y", "z"))}
    return result


def _clip_axis_state(
    pose: Mapping[str, Any],
    bone: str,
    axis: str,
) -> float:
    if _is_motion_root_translation_bone(bone):
        entry = _motion_root_entry(pose)
        if axis in _MOTION_ROOT_AXES:
            return float(entry.get(axis, 0.0))
        return float(entry.get({"x": "lateral", "y": "vertical", "z": "forward"}.get(axis, axis), 0.0))
    if _is_motion_root_rotation_bone(bone):
        entry = _motion_root_rotation_entry(pose)
        return float(entry.get(axis, 0.0))
    index = "xyz".index(axis)
    return float(np.degrees(_axis_values(pose.get(bone, {}))[index]))


def _clip_set_axis(
    pose: FramePose,
    bone: str,
    axis: str,
    value: float,
) -> None:
    if _is_motion_root_translation_bone(bone):
        target_axis = {"x": "lateral", "y": "vertical", "z": "forward"}.get(axis, axis)
        pose.setdefault(MOTION_ROOT_KEY, {root_axis: 0.0 for root_axis in _MOTION_ROOT_AXES})[
            target_axis
        ] = float(value)
    elif _is_motion_root_rotation_bone(bone):
        if axis not in _MOTION_ROOT_ROTATION_AXES:
            raise ValueError(f"unknown rigid-root rotation axis: {axis!r}")
        pose.setdefault(
            MOTION_ROOT_ROTATION_KEY,
            {root_axis: 0.0 for root_axis in _MOTION_ROOT_ROTATION_AXES},
        )[axis] = float(value)
    else:
        entry = pose.get(bone)
        if isinstance(entry, Mapping) and "quaternion" in entry:
            twist_policy = str(entry.get("twistPolicy", "")).strip()
            euler = quaternion_to_euler_xyz(pose_value_to_quaternion(entry))
            entry = {
                axis_name: float(euler[index])
                for index, axis_name in enumerate(("x", "y", "z"))
            }
            if twist_policy:
                entry["twistPolicy"] = twist_policy
            pose[bone] = entry
        pose.setdefault(bone, {"x": 0.0, "y": 0.0, "z": 0.0})[axis] = math.radians(float(value))


def _clip_group_for_bone(
    bone: str,
    bones: Sequence[str],
    groups: Sequence[Sequence[str]],
) -> list[str]:
    for group in groups:
        if bone in group:
            return [candidate for candidate in group if candidate in bones]
    return [bone]


def _candidate_angles(
    current: float,
    lo: float,
    hi: float,
    step: float,
    limit: int,
    mode: str = "range_extremes",
) -> list[float]:
    current = float(np.clip(current, lo, hi))
    if str(mode).lower() == "range_extremes":
        values = []
        # With the common three-evaluation budget this is current, low bound,
        # high bound, guaranteeing both legal directions are actually sampled.
        for value in (current, lo, hi):
            value = float(np.clip(value, lo, hi))
            if all(abs(value - old) > 1e-8 for old in values):
                values.append(value)
            if len(values) >= limit:
                return values[:limit]
    else:
        values = [current]
    # Local proposals keep the global solver tractable. A warm start should be
    # used for large bind-pose corrections; the clip objective then resolves
    # ambiguous frame-to-frame choices rather than repeating a full exhaustive fit.
    for delta in np.arange(step, step * (limit // 2 + 1), step):
        for sign in (-1.0, 1.0):
            value = float(np.clip(current + sign * float(delta), lo, hi))
            if all(abs(value - old) > 1e-8 for old in values):
                values.append(value)
            if len(values) >= limit:
                return values[:limit]
    return values[:limit]


def _vector_axis_key(axis: Sequence[float]) -> tuple[float, float, float] | tuple[()]:
    vector = np.asarray(list(axis), dtype=float)
    if vector.size != 3:
        return ()
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 1e-9:
        return ()
    normalized = vector / norm
    return tuple(float(round(value, 6)) for value in normalized)


def _rotation_vector_learning_summary(
    rows_by_frame: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    informative_min_improvement: float,
    top_k: int,
    boundary_limited_by_frame: Mapping[int, Sequence[str]],
    missing_by_frame: Mapping[int, Sequence[str]],
) -> tuple[
    dict[int, dict[str, list[dict[str, Any]]]],
    dict[int, list[str]],
]:
    """Summarize directional evidence for downstream legacy and block stages."""

    learned_by_frame: dict[int, dict[str, list[dict[str, Any]]]] = {}
    rescue_by_frame: dict[int, list[str]] = {}
    for frame, rows in rows_by_frame.items():
        learned: dict[str, list[dict[str, Any]]] = {}
        rescue: list[str] = []
        rows_by_bone: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_bone.setdefault(str(row["bone"]), []).append(dict(row))
        boundary_limited = set(str(bone) for bone in boundary_limited_by_frame.get(frame, ()))
        missing = set(str(bone) for bone in missing_by_frame.get(frame, ()))
        for bone, bone_rows in rows_by_bone.items():
            bone_rows.sort(key=lambda row: float(row.get("improvement", 0.0)), reverse=True)
            informative_rows = [
                row
                for row in bone_rows
                if float(row.get("improvement", 0.0)) >= float(informative_min_improvement)
            ]
            if bone in boundary_limited or bone in missing or not informative_rows:
                rescue.append(bone)
                continue
            selected: list[dict[str, Any]] = []
            seen_axes: set[tuple[float, float, float] | tuple[()]] = set()
            for row in informative_rows:
                axis_key = _vector_axis_key(row.get("axis", ()))
                if axis_key in seen_axes:
                    continue
                seen_axes.add(axis_key)
                selected.append(row)
                if len(selected) >= int(top_k):
                    break
            if selected:
                learned[bone] = selected
            else:
                rescue.append(bone)
        for bone in sorted(boundary_limited | missing):
            if bone not in rescue:
                rescue.append(bone)
        if learned:
            learned_by_frame[int(frame)] = learned
        if rescue:
            rescue_by_frame[int(frame)] = sorted(set(rescue))
    return learned_by_frame, rescue_by_frame


def _optimize_clip_impl(
    frame_indices: Sequence[int],
    bones: Sequence[str],
    initial_poses: Mapping[int, Mapping[str, Any]] | None,
    score_frame: ScoreFrame,
    range_for: RangeForBone,
    config: TemporalClipConfig,
    *,
    score_frame_batch: ScoreFrameBatch | None = None,
    progress: bool = True,
    live_preview: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Optimize all requested frame poses against one global clip objective.

    ``score_frame`` receives ``(frame, pose, label, live)`` and returns
    ``(image_quality, renderer_result, elapsed_seconds)``.  The callback is
    responsible for RGB/depth/semantic scoring; this function only adds the
    clip-level regularization and proposal policy.
    """
    config.validate()
    frames = [int(frame) for frame in frame_indices]
    root_enabled = _root_enabled(config)
    root_axes = _root_axes(config) if root_enabled else ()
    root_limits = _root_limits(config)
    root_rotation_enabled = _root_rotation_enabled(config)
    root_rotation_axes = (
        _root_rotation_axes(config) if root_rotation_enabled else ()
    )
    root_rotation_limits = _root_rotation_limits(config)
    bone_names = [
        MOTION_ROOT_KEY if str(bone) == LEGACY_BODY_TRANSLATION_KEY else str(bone)
        for bone in bones
    ]
    if not root_enabled:
        bone_names = [
            bone for bone in bone_names if not _is_motion_root_translation_bone(bone)
        ]
    if not root_rotation_enabled:
        bone_names = [
            bone for bone in bone_names if not _is_motion_root_rotation_bone(bone)
        ]
    if not frames:
        raise ValueError("clip optimization requires at least one frame")
    if root_enabled and MOTION_ROOT_KEY not in bone_names:
        bone_names.append(MOTION_ROOT_KEY)
    if root_rotation_enabled and MOTION_ROOT_ROTATION_KEY not in bone_names:
        bone_names.append(MOTION_ROOT_ROTATION_KEY)
    poses: dict[int, FramePose] = {
        frame: _canonical_pose((initial_poses or {}).get(frame, {}), bone_names)
        for frame in frames
    }
    image_scores: dict[int, float] = {}
    frame_results: dict[int, dict[str, Any]] = {}
    evaluation_cache: dict[tuple[int, str], tuple[float, dict[str, Any], float]] = {}
    history: list[dict[str, Any]] = []
    timings: list[dict[str, Any]] = []
    started = time.perf_counter()

    def report_evaluation(
        frame: int,
        label: str,
        score: float,
        elapsed: float,
        *,
        batched: bool,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "kind": "evaluation",
                "frame": int(frame),
                "label": str(label),
                "score": float(score),
                "elapsed": float(elapsed),
                "batched": bool(batched),
            }
        )

    def evaluate_frame(frame: int, candidate: FramePose, label: str, *, live: bool):
        key = (frame, _pose_key(candidate))
        if key not in evaluation_cache:
            evaluation_cache[key] = score_frame(frame, copy.deepcopy(candidate), label, live)
            score, _result, elapsed = evaluation_cache[key]
            report_evaluation(
                frame,
                label,
                float(score),
                float(elapsed),
                batched=False,
            )
        score, result, elapsed = evaluation_cache[key]
        if isinstance(result, dict) and "elapsed" not in result:
            result = {**result, "elapsed": float(elapsed)}
        return float(score), result, float(elapsed)

    def evaluate_frame_batch(
        frame: int,
        candidates: Sequence[tuple[FramePose, str, bool]],
    ) -> None:
        """Fill the cache for one axis proposal set in one renderer call.

        The proposal loop remains sequential and deterministic. Only the
        independent render requests are grouped, so temporal regularization
        and acceptance semantics do not change when batching is enabled.
        """
        pending = []
        pending_keys = set()
        for candidate, label, live in candidates:
            key = (frame, _pose_key(candidate))
            if key not in evaluation_cache and key not in pending_keys:
                pending.append((candidate, label, live))
                pending_keys.add(key)
        if not pending:
            return
        if (
            score_frame_batch is None
            or not config.batch_candidates
            or any(live for _candidate, _label, live in pending)
        ):
            for candidate, label, live in pending:
                evaluate_frame(frame, candidate, label, live=live)
            return
        # The per-frame semantic bound is conservative for the global clip:
        # it substitutes each candidate's exact temporal penalty and lets all
        # unknown image terms improve to their best possible values. This
        # keeps pruning lossless while avoiding the overly loose scalar bound.
        incumbent_score = None
        required_image_scores = None
        try:
            parameters = inspect.signature(score_frame_batch).parameters
            supports_incumbent = (
                "incumbent_score" in parameters
                or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
            )
            supports_required = (
                "required_image_scores" in parameters
                or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
            )
        except (TypeError, ValueError):
            supports_incumbent = False
            supports_required = False
        if supports_incumbent and image_scores and len(image_scores) == len(frames):
            other_sum = sum(
                float(image_scores[other_frame])
                for other_frame in frames
                if int(other_frame) != int(frame)
            )
            incumbent_score = float(len(frames) * current_objective - other_sum)
        if supports_required and image_scores and len(image_scores) == len(frames):
            zero_scores = {int(other_frame): 0.0 for other_frame in frames}
            required_image_scores = []
            other_sum = sum(
                float(image_scores[other_frame])
                for other_frame in frames
                if int(other_frame) != int(frame)
            )
            for candidate, _label, _live in pending:
                candidate_objective, _ = clip_objective(
                    zero_scores,
                    {**poses, frame: candidate},
                    frames,
                    bone_names,
                    config,
                )
                candidate_penalty = float(-candidate_objective)
                required_image_scores.append(
                    float(
                        len(frames) * (current_objective + candidate_penalty)
                        - other_sum
                    )
                )
        if supports_incumbent or supports_required:
            kwargs: dict[str, Any] = {}
            if supports_incumbent:
                kwargs["incumbent_score"] = incumbent_score
            if supports_required:
                kwargs["required_image_scores"] = required_image_scores
            results = list(
                score_frame_batch(
                    frame,
                    pending,
                    **kwargs,
                )
            )
        else:
            results = list(score_frame_batch(frame, pending))
        if len(results) != len(pending):
            raise RuntimeError(
                "score_frame_batch returned an unexpected number of results: "
                f"expected {len(pending)}, got {len(results)}"
            )
        for (candidate, _label, _live), result in zip(pending, results):
            key = (frame, _pose_key(candidate))
            score, renderer_result, elapsed = result
            evaluation_cache[key] = (
                float(score),
                dict(renderer_result),
                float(elapsed),
            )
            report_evaluation(
                frame,
                _label,
                float(score),
                float(elapsed),
                batched=True,
            )

    # Establish a complete image-score vector before applying any temporal
    # regularization. These are also the live previews for the initial state.
    for frame in frames:
        score, result, _ = evaluate_frame(
            frame, poses[frame], f"clip f{frame:02d} initial", live=live_preview
        )
        image_scores[frame] = score
        frame_results[frame] = result
    current_objective, current_details = clip_objective(
        image_scores, poses, frames, bone_names, config
    )

    # Treat whole-body translation and rigid attitude as one hypothesis before
    # the ordinary per-variable clip probes. The two keys remain separate in
    # the delivered pose, but a candidate is accepted only after both are
    # rendered together. This is what lets a knockdown keep the translation
    # that makes its rolled orientation useful.
    rigid_root_escape_history: list[dict[str, Any]] = []
    coupled_root_stage = bool(
        root_enabled
        and root_rotation_enabled
        and config.motion_root_coupled_blocks_enabled
        and config.motion_root_rotation_coupled_blocks_enabled
    )
    if coupled_root_stage:
        coupled_started = time.perf_counter()
        for frame in frames:
            current_pose = poses[frame]
            root_limits = _root_limits(config)
            rotation_limit = float(config.motion_root_rotation_limit_deg)
            base_translation = _motion_root_entry(current_pose)
            base_rotation = _motion_root_rotation_entry(current_pose)
            base_translation = {
                axis: float(
                    np.clip(base_translation.get(axis, 0.0), -root_limits[axis], root_limits[axis])
                )
                for axis in _MOTION_ROOT_AXES
            }
            base_rotation = {
                axis: float(
                    np.clip(base_rotation.get(axis, 0.0), -rotation_limit, rotation_limit)
                )
                for axis in _MOTION_ROOT_ROTATION_AXES
            }

            def rigid_pose(translation, rotation):
                candidate = copy.deepcopy(current_pose)
                candidate[MOTION_ROOT_KEY] = dict(translation)
                candidate[MOTION_ROOT_ROTATION_KEY] = dict(rotation)
                return candidate

            def unique_pairs(pairs):
                result = []
                seen = set()
                for translation, rotation in pairs:
                    key = (
                        tuple(
                            (axis, round(float(translation.get(axis, 0.0)), 8))
                            for axis in _MOTION_ROOT_AXES
                        ),
                        tuple(
                            (axis, round(float(rotation.get(axis, 0.0)), 6))
                            for axis in _MOTION_ROOT_ROTATION_AXES
                        ),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append((dict(translation), dict(rotation)))
                return result

            def score_rigid_pairs(pairs, region):
                pairs = unique_pairs(pairs)
                entries = [
                    (
                        rigid_pose(translation, rotation),
                        f"clip rigid root f{frame:02d} {region}",
                        False,
                    )
                    for translation, rotation in pairs
                ]
                evaluate_frame_batch(frame, entries)
                rows = []
                for (translation, rotation), (candidate, label, _live) in zip(
                    pairs,
                    entries,
                ):
                    image_score, _result, elapsed = evaluate_frame(
                        frame,
                        candidate,
                        label,
                        live=False,
                    )
                    candidate_scores = dict(image_scores)
                    candidate_scores[frame] = image_score
                    objective, _details = clip_objective(
                        candidate_scores,
                        {**poses, frame: candidate},
                        frames,
                        bone_names,
                        config,
                    )
                    rows.append(
                        {
                            "frame": int(frame),
                            "region": str(region),
                            "translation": dict(translation),
                            "rotation": dict(rotation),
                            "imageScore": float(image_score),
                            "objective": float(objective),
                            "imageDelta": float(image_score - image_scores[frame]),
                            "objectiveDelta": float(objective - current_objective),
                            "elapsed": float(elapsed),
                            "candidate": candidate,
                        }
                    )
                return rows

            translation_pairs = [(base_translation, base_rotation)]
            translation_step = float(config.motion_root_coarse_step_body_lengths)
            for axis in _root_axes(config):
                for raw in (
                    base_translation[axis] - translation_step,
                    base_translation[axis] + translation_step,
                    -root_limits[axis],
                    root_limits[axis],
                ):
                    candidate = dict(base_translation)
                    candidate[axis] = float(
                        np.clip(raw, -root_limits[axis], root_limits[axis])
                    )
                    translation_pairs.append((candidate, base_rotation))
            translation_rows = score_rigid_pairs(translation_pairs, "translation")
            translation_rows.sort(key=lambda row: float(row["imageScore"]), reverse=True)
            translation_rows = translation_rows[: max(2, int(config.motion_root_rotation_escape_top_k))]

            translation_beam = [
                (row["translation"], row["rotation"])
                for row in translation_rows
            ] or [(base_translation, base_rotation)]
            rotation_pairs = [(translation_beam[0][0], translation_beam[0][1])]
            rotation_step = float(config.motion_root_rotation_coarse_step_deg)
            for axis in _root_rotation_axes(config):
                for raw in (
                    base_rotation[axis] - rotation_step,
                    base_rotation[axis] + rotation_step,
                    -rotation_limit,
                    rotation_limit,
                ):
                    candidate = dict(base_rotation)
                    candidate[axis] = float(np.clip(raw, -rotation_limit, rotation_limit))
                    rotation_pairs.append((translation_beam[0][0], candidate))
            if config.motion_root_rotation_escape_enabled:
                for hypothesis in _root_rotation_escape_hypotheses(config):
                    candidate = dict(base_rotation)
                    for axis in _root_rotation_escape_axes(config):
                        candidate[axis] = float(
                            np.clip(
                                base_rotation[axis] + hypothesis.get(axis, 0.0),
                                -rotation_limit,
                                rotation_limit,
                            )
                        )
                    rotation_pairs.append((translation_beam[0][0], candidate))
            rotation_rows = score_rigid_pairs(rotation_pairs, "rotation")
            rotation_rows.sort(key=lambda row: float(row["imageScore"]), reverse=True)
            rotation_rows = rotation_rows[: max(2, int(config.motion_root_rotation_escape_top_k))]

            coupled_rows = score_rigid_pairs(
                [
                    (translation_row["translation"], rotation_row["rotation"])
                    for translation_row in translation_rows
                    for rotation_row in rotation_rows
                ],
                "coupled",
            )
            best_image = max(coupled_rows, key=lambda row: float(row["imageScore"]), default=None)
            best_objective = max(coupled_rows, key=lambda row: float(row["objective"]), default=None)
            chosen = best_image if config.motion_root_rotation_escape_force_image_best else best_objective
            relaxation_summary: dict[str, Any] | None = None
            if chosen is not None:
                final_chosen = dict(chosen)
                final_pose = copy.deepcopy(chosen["candidate"])
                final_score = float(chosen["imageScore"])
                final_objective = float(chosen["objective"])
                if (
                    config.motion_root_rotation_escape_relax_enabled
                    and int(config.motion_root_rotation_escape_relax_bone_count) > 0
                ):
                    relax_pose = copy.deepcopy(final_pose)
                    relax_score = float(final_score)
                    relax_objective = float(final_objective)
                    relax_bones = [
                        bone
                        for bone in bone_names
                        if not _is_motion_root_bone(bone)
                        and not _is_motion_root_rotation_bone(bone)
                    ][: int(config.motion_root_rotation_escape_relax_bone_count)]
                    relax_axes = tuple(str(axis) for axis in config.axes)
                    relax_trials = 1
                    accepted_bones = []
                    for relax_round in range(
                        int(config.motion_root_rotation_escape_relax_rounds)
                    ):
                        step = (
                            float(config.motion_root_rotation_escape_relax_step_deg)
                            if relax_round == 0
                            else float(
                                config.motion_root_rotation_escape_relax_refine_step_deg
                            )
                        )
                        for bone in relax_bones:
                            lo, hi = map(float, range_for(bone))
                            candidates: list[tuple[FramePose, str, bool]] = []
                            candidate_values: list[tuple[str, float, FramePose]] = []
                            for axis in relax_axes:
                                current = _clip_axis_state(relax_pose, bone, axis)
                                for direction in (-1.0, 1.0):
                                    value = float(np.clip(current + direction * step, lo, hi))
                                    if abs(value - current) <= 1e-8:
                                        continue
                                    candidate = copy.deepcopy(relax_pose)
                                    _clip_set_axis(candidate, bone, axis, value)
                                    candidates.append(
                                        (
                                            candidate,
                                            f"clip root accepted relax f{frame:02d} "
                                            f"{bone} {axis} {value:+.1f}",
                                            False,
                                        )
                                    )
                                    candidate_values.append((axis, value, candidate))
                            evaluate_frame_batch(frame, candidates)
                            best_local = {
                                "pose": relax_pose,
                                "score": float(relax_score),
                                "objective": float(relax_objective),
                                "axis": None,
                                "value": None,
                            }
                            for (axis, value, candidate_pose), (
                                candidate_pose_eval,
                                _label,
                                _live,
                            ) in zip(candidate_values, candidates):
                                score, _result, _elapsed = evaluate_frame(
                                    frame,
                                    candidate_pose_eval,
                                    f"clip root accepted relax f{frame:02d}",
                                    live=False,
                                )
                                objective, _ = clip_objective(
                                    {**image_scores, frame: score},
                                    {**poses, frame: candidate_pose_eval},
                                    frames,
                                    bone_names,
                                    config,
                                )
                                relax_trials += 1
                                if float(objective) > float(best_local["objective"]) + 1e-9:
                                    best_local = {
                                        "pose": candidate_pose_eval,
                                        "score": float(score),
                                        "objective": float(objective),
                                        "axis": str(axis),
                                        "value": float(value),
                                    }
                            if best_local["pose"] is not relax_pose:
                                relax_pose = copy.deepcopy(best_local["pose"])
                                relax_score = float(best_local["score"])
                                relax_objective = float(best_local["objective"])
                                accepted_bones.append(
                                    {
                                        "bone": str(bone),
                                        "axis": best_local["axis"],
                                        "valueDeg": best_local["value"],
                                    }
                                )
                    relaxation_summary = {
                        "enabled": True,
                        "boneCount": len(relax_bones),
                        "rounds": int(config.motion_root_rotation_escape_relax_rounds),
                        "trials": int(relax_trials),
                        "acceptedBones": accepted_bones,
                        "applied": bool(accepted_bones),
                    }
                    if accepted_bones:
                        final_pose = copy.deepcopy(relax_pose)
                        final_score = float(relax_score)
                        final_objective = float(relax_objective)
                        final_chosen["candidate"] = copy.deepcopy(final_pose)
                        final_chosen["imageScore"] = float(final_score)
                        final_chosen["objective"] = float(final_objective)
                        final_chosen["imageDelta"] = float(
                            final_score - image_scores[frame]
                        )
                        final_chosen["objectiveDelta"] = float(
                            final_objective - current_objective
                        )
                        final_chosen["relaxation"] = dict(relaxation_summary)
                if relaxation_summary is not None and "relaxation" not in final_chosen:
                    final_chosen["relaxation"] = dict(relaxation_summary)
                poses[frame] = copy.deepcopy(final_pose)
                image_scores[frame], frame_results[frame], _ = evaluate_frame(
                    frame,
                    poses[frame],
                    f"clip rigid root accepted f{frame:02d}",
                    live=live_preview,
                )
                current_objective, current_details = clip_objective(
                    image_scores,
                    poses,
                    frames,
                    bone_names,
                    config,
                )
                chosen = final_chosen
            rigid_root_escape_history.append(
                {
                    "frame": int(frame),
                    "translationCandidates": len(translation_rows),
                    "rotationCandidates": len(rotation_rows),
                    "coupledCandidates": len(coupled_rows),
                    "topCandidates": [
                        {
                            key: value
                            for key, value in row.items()
                            if key != "candidate"
                        }
                        for row in sorted(
                            coupled_rows,
                            key=lambda row: float(row["imageScore"]),
                            reverse=True,
                        )[: max(2, int(config.motion_root_rotation_escape_top_k))]
                    ],
                    "chosen": (
                        {
                            key: value
                            for key, value in chosen.items()
                            if key != "candidate"
                        }
                        if chosen is not None
                        else None
                    ),
                }
            )
        history.append(
            {
                "kind": "clip_motion_root_rigid_escape",
                "frames": rigid_root_escape_history,
                "coupledBlocksEnabled": True,
                "elapsed": time.perf_counter() - coupled_started,
            }
        )

    # A local joint sweep cannot reach a fallen/rolled body when the Meshy
    # trunk remains upright. Search the rigid root in the camera basis before
    # ordinary bone probes. This stage intentionally keeps the best image
    # hypothesis even when its temporary temporal objective is worse: the
    # subsequent clip passes are the relaxation stage that restores continuity.
    root_rotation_escape_history: list[dict[str, Any]] = []
    if (
        root_rotation_enabled
        and not coupled_root_stage
        and config.motion_root_rotation_escape_enabled
        and _root_rotation_escape_axes(config)
    ):
        escape_started = time.perf_counter()
        escape_axes = _root_rotation_escape_axes(config)
        escape_limit = float(config.motion_root_rotation_limit_deg)
        escape_angles = tuple(
            float(np.clip(angle, -escape_limit, escape_limit))
            for angle in config.motion_root_rotation_escape_angles_deg
        )
        escape_hypotheses = _root_rotation_escape_hypotheses(config)
        for frame in frames:
            current_pose = poses[frame]
            entries: list[tuple[FramePose, str, bool]] = []
            metadata: list[tuple[str, dict[str, float], FramePose]] = []
            base_rotation = {
                axis: float(
                    np.clip(
                        _motion_root_rotation_entry(current_pose).get(axis, 0.0),
                        -escape_limit,
                        escape_limit,
                    )
                )
                for axis in _MOTION_ROOT_ROTATION_AXES
            }
            for hypothesis in escape_hypotheses:
                candidate_pose = copy.deepcopy(current_pose)
                candidate_values = dict(base_rotation)
                for axis in escape_axes:
                    candidate_values[axis] = float(
                        np.clip(
                            base_rotation[axis] + hypothesis.get(axis, 0.0),
                            -escape_limit,
                            escape_limit,
                        )
                    )
                    _clip_set_axis(
                        candidate_pose,
                        MOTION_ROOT_ROTATION_KEY,
                        axis,
                        candidate_values[axis],
                    )
                active = [
                    f"{axis}={candidate_values[axis]:+.1f}"
                    for axis in escape_axes
                    if abs(candidate_values[axis]) > 1e-8
                ]
                label = (
                    f"clip root escape f{frame:02d} "
                    f"({' '.join(active) if active else 'identity'})"
                )
                entries.append((candidate_pose, label, False))
                metadata.append(("combined", candidate_values, candidate_pose))
            # Deduplicate poses generated by repeated/clipped escape values.
            unique_entries: list[tuple[FramePose, str, bool]] = []
            unique_metadata: list[tuple[str, dict[str, float], FramePose]] = []
            seen_keys: set[str] = set()
            for entry, meta in zip(entries, metadata):
                key = _pose_key(entry[0])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                unique_entries.append(entry)
                unique_metadata.append(meta)
            evaluate_frame_batch(frame, unique_entries)
            rows: list[dict[str, Any]] = []
            for (candidate_pose, label, _live), (axis, value, _meta_pose) in zip(
                unique_entries,
                unique_metadata,
            ):
                image_score, result, elapsed = evaluate_frame(
                    frame,
                    candidate_pose,
                    label,
                    live=False,
                )
                candidate_scores = dict(image_scores)
                candidate_scores[frame] = image_score
                objective, _details = clip_objective(
                    candidate_scores,
                    {**poses, frame: candidate_pose},
                    frames,
                    bone_names,
                    config,
                )
                rows.append(
                    {
                        "frame": int(frame),
                        "axis": str(axis),
                        "valueDeg": float(value.get(axis, 0.0)) if axis != "combined" else None,
                        "valuesDeg": dict(value),
                        "imageScore": float(image_score),
                        "objective": float(objective),
                        "objectiveDelta": float(objective - current_objective),
                        "imageDelta": float(image_score - image_scores[frame]),
                        "elapsed": float(elapsed),
                        "candidate": candidate_pose,
                    }
                )
            rows.sort(key=lambda row: float(row["imageScore"]), reverse=True)
            top_rows = rows[: int(config.motion_root_rotation_escape_top_k)]

            # A root attitude is only a useful hypothesis after a small local
            # relaxation.  Without this, a lying body can be discarded simply
            # because the standing bind pose's shoulders/hips are still in the
            # old configuration.  Keep this bounded: ordered high-level bones,
            # a few signed axis steps, and a single refinement round by default.
            relaxation_rows: list[dict[str, Any]] = []
            if (
                config.motion_root_rotation_escape_relax_enabled
                and int(config.motion_root_rotation_escape_relax_bone_count) > 0
                and top_rows
            ):
                relax_bones = [
                    bone
                    for bone in bone_names
                    if not _is_motion_root_bone(bone)
                    and not _is_motion_root_rotation_bone(bone)
                ][: int(config.motion_root_rotation_escape_relax_bone_count)]
                relax_axes = tuple(str(axis) for axis in config.axes)
                for seed_index, seed_row in enumerate(top_rows):
                    relaxed_pose = copy.deepcopy(seed_row["candidate"])
                    relaxed_score, relaxed_result, relaxed_elapsed = evaluate_frame(
                        frame,
                        relaxed_pose,
                        f"clip root escape relax f{frame:02d} seed {seed_index} baseline",
                        live=False,
                    )
                    relaxed_objective, _ = clip_objective(
                        {**image_scores, frame: relaxed_score},
                        {**poses, frame: relaxed_pose},
                        frames,
                        bone_names,
                        config,
                    )
                    relax_trials = 1
                    accepted_bones = []
                    for relax_round in range(
                        int(config.motion_root_rotation_escape_relax_rounds)
                    ):
                        step = (
                            float(config.motion_root_rotation_escape_relax_step_deg)
                            if relax_round == 0
                            else float(
                                config.motion_root_rotation_escape_relax_refine_step_deg
                            )
                        )
                        for bone in relax_bones:
                            lo, hi = map(float, range_for(bone))
                            candidates: list[tuple[FramePose, str, bool]] = []
                            candidate_values: list[tuple[str, float, FramePose]] = []
                            for axis in relax_axes:
                                current = _clip_axis_state(relaxed_pose, bone, axis)
                                for direction in (-1.0, 1.0):
                                    value = float(np.clip(current + direction * step, lo, hi))
                                    if abs(value - current) <= 1e-8:
                                        continue
                                    candidate = copy.deepcopy(relaxed_pose)
                                    _clip_set_axis(candidate, bone, axis, value)
                                    candidates.append(
                                        (
                                            candidate,
                                            f"clip root escape relax f{frame:02d} "
                                            f"seed {seed_index} {bone} {axis} {value:+.1f}",
                                            False,
                                        )
                                    )
                                    candidate_values.append((axis, value, candidate))
                            evaluate_frame_batch(frame, candidates)
                            best_local = {
                                "pose": relaxed_pose,
                                "score": float(relaxed_score),
                                "objective": float(relaxed_objective),
                                "axis": None,
                                "value": None,
                            }
                            for (axis, value, candidate), (candidate_pose, _label, _live) in zip(
                                candidate_values,
                                candidates,
                            ):
                                score, _result, _elapsed = evaluate_frame(
                                    frame,
                                    candidate_pose,
                                    f"clip root escape relax f{frame:02d} seed {seed_index}",
                                    live=False,
                                )
                                objective, _ = clip_objective(
                                    {**image_scores, frame: score},
                                    {**poses, frame: candidate_pose},
                                    frames,
                                    bone_names,
                                    config,
                                )
                                relax_trials += 1
                                if float(objective) > float(best_local["objective"]) + 1e-9:
                                    best_local = {
                                        "pose": candidate_pose,
                                        "score": float(score),
                                        "objective": float(objective),
                                        "axis": str(axis),
                                        "value": float(value),
                                    }
                            if best_local["pose"] is not relaxed_pose:
                                relaxed_pose = copy.deepcopy(best_local["pose"])
                                relaxed_score = float(best_local["score"])
                                relaxed_objective = float(best_local["objective"])
                                accepted_bones.append(
                                    {
                                        "bone": str(bone),
                                        "axis": best_local["axis"],
                                        "valueDeg": best_local["value"],
                                    }
                                )
                    relaxation_rows.append(
                        {
                            **seed_row,
                            "candidate": relaxed_pose,
                            "imageScore": float(relaxed_score),
                            "objective": float(relaxed_objective),
                            "imageDelta": float(relaxed_score - image_scores[frame]),
                            "objectiveDelta": float(relaxed_objective - current_objective),
                            "relaxSeedIndex": int(seed_index),
                            "relaxBones": list(relax_bones),
                            "relaxTrials": int(relax_trials),
                            "relaxAccepted": accepted_bones,
                        }
                    )
                if relaxation_rows:
                    rows = relaxation_rows

            rows.sort(key=lambda row: float(row["imageScore"]), reverse=True)
            top_rows = rows[: int(config.motion_root_rotation_escape_top_k)]
            best_image = top_rows[0] if top_rows else None
            best_objective = max(
                rows,
                key=lambda row: float(row["objective"]),
                default=None,
            )
            chosen = None
            if best_image is not None and config.motion_root_rotation_escape_force_image_best:
                if float(best_image["imageDelta"]) >= float(
                    config.motion_root_rotation_escape_min_image_improvement
                ):
                    chosen = best_image
            if chosen is None and best_objective is not None:
                if float(best_objective["objectiveDelta"]) > float(config.acceptance_margin):
                    chosen = best_objective
            if chosen is not None:
                poses[frame] = copy.deepcopy(chosen["candidate"])
                image_scores[frame], frame_results[frame], _ = evaluate_frame(
                    frame,
                    poses[frame],
                    f"clip root escape accepted f{frame:02d} "
                    f"{chosen['axis']} {chosen['valuesDeg']}",
                    live=live_preview,
                )
                current_objective, current_details = clip_objective(
                    image_scores,
                    poses,
                    frames,
                    bone_names,
                    config,
                )
            root_rotation_escape_history.append(
                {
                    "frame": int(frame),
                    "topCandidates": [
                        {
                            key: value
                            for key, value in row.items()
                            if key != "candidate"
                        }
                        for row in top_rows
                    ],
                    "chosen": (
                        {
                            key: value
                            for key, value in chosen.items()
                            if key != "candidate"
                        }
                        if chosen is not None
                        else None
                    ),
                }
            )
        history.append(
            {
                "kind": "clip_motion_root_rotation_escape",
                "axes": list(escape_axes),
                "anglesDeg": list(escape_angles),
                "hypothesisCount": len(_root_rotation_escape_hypotheses(config)),
                "topK": int(config.motion_root_rotation_escape_top_k),
                "forceImageBest": bool(config.motion_root_rotation_escape_force_image_best),
                "minImageImprovement": float(
                    config.motion_root_rotation_escape_min_image_improvement
                ),
                "frames": root_rotation_escape_history,
                "elapsed": time.perf_counter() - escape_started,
            }
        )

    # Arbitrary-axis shell: search in the rest-space shaft frame before the
    # legacy Euler coordinate passes.  This is intentionally a separate stage
    # so its diagnostics distinguish "not tried" from "tried and rejected".
    vector_rows_by_frame: dict[int, list[dict[str, Any]]] = {}
    vector_learned_by_frame: dict[int, dict[str, list[dict[str, Any]]]] = {}
    vector_rescue_by_frame: dict[int, list[str]] = {}
    vector_boundary_limited: set[str] = set()
    vector_missing: set[str] = set()
    if config.rotation_vector_search_enabled:
        vector_started = time.perf_counter()
        vector_boundary_limited_by_frame: dict[int, list[str]] = {}
        vector_missing_by_frame: dict[int, list[str]] = {}
        for frame in frames:
            proposal_entries: list[tuple[FramePose, str, bool]] = []
            proposal_meta: list[tuple[str, dict[str, Any], FramePose]] = []
            boundary_limited: list[str] = []
            for bone in bone_names:
                if _is_motion_root_bone(bone):
                    continue
                vector = config.bone_vectors.get(str(bone))
                if vector is None:
                    vector_missing.add(str(bone))
                    continue
                lo, hi = map(float, range_for(bone))
                policy = str(
                    config.bone_twist_overrides.get(
                        str(bone),
                        config.bone_twist_policy,
                    )
                ).lower()
                current = pose_value_to_quaternion(poses[frame].get(bone, {}))
                shell = rotation_vector_proposals(
                    current,
                    vector,
                    float(config.rotation_vector_probe_step_deg),
                    int(config.rotation_vector_probe_count),
                    max(abs(lo), abs(hi)),
                    include_twist=policy != "exclude",
                    twist_policy=policy,
                )
                if not shell:
                    boundary_limited.append(str(bone))
                for proposal in shell:
                    candidate_pose = copy.deepcopy(poses[frame])
                    candidate_pose[bone] = quaternion_pose_entry(
                        proposal["quaternion"],
                        twist_policy=proposal["twistPolicy"],
                    )
                    label = (
                        f"clip vector f{frame:02d} {bone} {proposal['kind']} "
                        f"{proposal['angleDeg']:+.1f}"
                    )
                    proposal_entries.append((candidate_pose, label, False))
                    proposal_meta.append((str(bone), proposal, candidate_pose))
            evaluate_frame_batch(frame, proposal_entries)
            rows: list[dict[str, Any]] = []
            for (candidate_pose, label, _live), (bone, proposal, _meta_pose) in zip(
                proposal_entries, proposal_meta
            ):
                image_score, _result, elapsed = evaluate_frame(
                    frame, candidate_pose, label, live=False
                )
                candidate_scores = dict(image_scores)
                candidate_scores[frame] = image_score
                objective, _details = clip_objective(
                    candidate_scores,
                    {**poses, frame: candidate_pose},
                    frames,
                    bone_names,
                    config,
                )
                rows.append(
                    {
                        "frame": int(frame),
                        "bone": bone,
                        "kind": str(proposal["kind"]),
                        "direction": int(proposal["direction"]),
                        "axis": list(proposal["axis"]),
                        "angleDeg": float(proposal["angleDeg"]),
                        "twistPolicy": str(proposal["twistPolicy"]),
                        "improvement": float(objective - current_objective),
                        "imageScore": float(image_score),
                        "objective": float(objective),
                        "elapsed": float(elapsed),
                    }
                )
            rows.sort(key=lambda row: float(row["objective"]), reverse=True)

            # Continue only a small number of directions.  The top directions
            # are continued even when their first step is not an improvement;
            # that is the deliberate valley-crossing escape hatch.
            continuation_entries: list[tuple[FramePose, str, bool]] = []
            continuation_meta: list[tuple[str, dict[str, Any], FramePose]] = []
            if config.directional_continuation_enabled and rows:
                seen_directions: set[tuple[str, int]] = set()
                for row in rows:
                    key = (str(row["bone"]), int(row["direction"]))
                    if key in seen_directions:
                        continue
                    if (
                        float(row["improvement"]) < float(config.directional_min_improvement)
                        and seen_directions
                    ):
                        continue
                    seen_directions.add(key)
                    if len(seen_directions) > int(config.directional_top_k):
                        break
                    bone = str(row["bone"])
                    vector = config.bone_vectors.get(bone)
                    if vector is None:
                        continue
                    lo, hi = map(float, range_for(bone))
                    current = pose_value_to_quaternion(poses[frame].get(bone, {}))
                    for continuation_index in range(1, int(config.directional_max_steps)):
                        angle = float(config.rotation_vector_probe_step_deg) * (
                            float(config.directional_step_multiplier) ** continuation_index
                        )
                        proposal = continuation_proposal(
                            current,
                            row["axis"],
                            angle,
                            max(abs(lo), abs(hi)),
                            kind=str(row["kind"]),
                            direction=int(row["direction"]),
                            twist_policy=str(row["twistPolicy"]),
                        )
                        if proposal is None:
                            boundary_limited.append(bone)
                            break
                        candidate_pose = copy.deepcopy(poses[frame])
                        candidate_pose[bone] = quaternion_pose_entry(
                            proposal["quaternion"],
                            twist_policy=proposal["twistPolicy"],
                        )
                        label = (
                            f"clip continue f{frame:02d} {bone} {proposal['kind']} "
                            f"{angle:+.1f}"
                        )
                        continuation_entries.append((candidate_pose, label, False))
                        continuation_meta.append((bone, proposal, candidate_pose))
            evaluate_frame_batch(frame, continuation_entries)
            for (candidate_pose, label, _live), (bone, proposal, _meta_pose) in zip(
                continuation_entries, continuation_meta
            ):
                image_score, _result, elapsed = evaluate_frame(
                    frame, candidate_pose, label, live=False
                )
                candidate_scores = dict(image_scores)
                candidate_scores[frame] = image_score
                objective, _details = clip_objective(
                    candidate_scores,
                    {**poses, frame: candidate_pose},
                    frames,
                    bone_names,
                    config,
                )
                rows.append(
                    {
                        "frame": int(frame),
                        "bone": bone,
                        "kind": f"{proposal['kind']}_continuation",
                        "direction": int(proposal["direction"]),
                        "axis": list(proposal["axis"]),
                        "angleDeg": float(proposal["angleDeg"]),
                        "twistPolicy": str(proposal["twistPolicy"]),
                        "improvement": float(objective - current_objective),
                        "imageScore": float(image_score),
                        "objective": float(objective),
                        "elapsed": float(elapsed),
                    }
                )
            best_row = max(rows, key=lambda row: float(row["objective"]), default=None)
            accepted = bool(
                best_row is not None
                and float(best_row["objective"])
                > float(current_objective) + float(config.acceptance_margin)
            )
            if accepted:
                # Reconstruct the accepted proposal from its diagnostic axis
                # and magnitude rather than retaining an opaque row object.
                bone = str(best_row["bone"])
                current = pose_value_to_quaternion(poses[frame].get(bone, {}))
                proposal = continuation_proposal(
                    current,
                    best_row["axis"],
                    float(best_row["angleDeg"]),
                    max(map(abs, range_for(bone))),
                    kind=str(best_row["kind"]),
                    direction=int(best_row["direction"]),
                    twist_policy=str(best_row["twistPolicy"]),
                )
                if proposal is not None:
                    poses[frame][bone] = quaternion_pose_entry(
                        proposal["quaternion"],
                        twist_policy=proposal["twistPolicy"],
                    )
                    image_scores[frame] = float(best_row["imageScore"])
                    frame_results[frame] = evaluate_frame(
                        frame,
                        poses[frame],
                        f"clip vector accepted f{frame:02d} {bone}",
                        live=live_preview,
                    )[1]
                    current_objective, current_details = clip_objective(
                        image_scores, poses, frames, bone_names, config
                    )
            vector_rows_by_frame[frame] = rows
            vector_boundary_limited_by_frame[int(frame)] = list(boundary_limited)
            vector_missing_by_frame[int(frame)] = [
                bone
                for bone in bone_names
                if bone in vector_missing
            ]
            vector_boundary_limited.update(boundary_limited)
        vector_learned_by_frame, vector_rescue_by_frame = _rotation_vector_learning_summary(
            vector_rows_by_frame,
            informative_min_improvement=float(
                config.rotation_vector_informative_min_improvement
            ),
            top_k=int(config.directional_top_k),
            boundary_limited_by_frame=vector_boundary_limited_by_frame,
            missing_by_frame=vector_missing_by_frame,
        )
        history.append(
            {
                "kind": "clip_rotation_vector_probe",
                "rows": [row for rows in vector_rows_by_frame.values() for row in rows],
                "boundaryLimitedBones": sorted(vector_boundary_limited),
                "notAttemptedBones": sorted(vector_missing),
                "informativeBones": sorted(
                    {
                        bone
                        for frame_learned in vector_learned_by_frame.values()
                        for bone in frame_learned
                    }
                ),
                "legacyEulerRescueBones": sorted(
                    {
                        bone
                        for frame_rescue in vector_rescue_by_frame.values()
                        for bone in frame_rescue
                    }
                ),
                "probeCount": int(config.rotation_vector_probe_count),
                "probeStepDeg": float(config.rotation_vector_probe_step_deg),
                "informativeMinImprovement": float(
                    config.rotation_vector_informative_min_improvement
                ),
                "directionalContinuation": bool(config.directional_continuation_enabled),
                "elapsed": time.perf_counter() - vector_started,
            }
        )

    # First probe: score independent signed perturbations in renderer/encoder
    # batches, then use the measured improvements to choose dependency-local
    # blocks. This is deliberately separate from acceptance so the probe can
    # discover variables that are individually weak but jointly promising.
    probe_rows_by_frame: dict[int, list[dict[str, Any]]] = {}
    probe_ranked_rows_by_frame: dict[int, list[dict[str, Any]]] = {}
    legacy_probe_bones_by_frame = {
        int(frame): (
            vector_rescue_by_frame.get(int(frame), list(bone_names))
            if config.rotation_vector_search_enabled
            and config.rotation_vector_legacy_euler_fallback_enabled
            else list(bone_names)
        )
        for frame in frames
    }
    if config.probe_enabled:
        probe_started = time.perf_counter()
        for frame in frames:
            proposal_entries: list[tuple[FramePose, str, bool]] = []
            proposal_meta: list[tuple[str, str, float, FramePose]] = []
            for bone in legacy_probe_bones_by_frame.get(int(frame), list(bone_names)):
                is_translation_root = _is_motion_root_translation_bone(bone)
                is_rotation_root = _is_motion_root_rotation_bone(bone)
                is_root = is_translation_root or is_rotation_root
                axes = (
                    root_axes
                    if is_translation_root
                    else root_rotation_axes
                    if is_rotation_root
                    else config.axes
                )
                for axis in axes:
                    current = _clip_axis_state(poses[frame], bone, axis)
                    if is_translation_root:
                        lo, hi = -root_limits[axis], root_limits[axis]
                        step = float(config.motion_root_coarse_step_body_lengths)
                    elif is_rotation_root:
                        lo, hi = (
                            -root_rotation_limits[axis],
                            root_rotation_limits[axis],
                        )
                        step = float(config.motion_root_rotation_coarse_step_deg)
                    else:
                        lo, hi = map(float, range_for(bone))
                        step = float(config.probe_step_deg)
                    probe_values = (
                        current - step,
                        current + step,
                        lo,
                        hi,
                    )
                    seen_values = set()
                    for raw_value in probe_values:
                        value = float(np.clip(raw_value, lo, hi))
                        if abs(value - current) <= 1e-8:
                            continue
                        value_key = round(value, 8)
                        if value_key in seen_values:
                            continue
                        seen_values.add(value_key)
                        candidate_pose = copy.deepcopy(poses[frame])
                        _clip_set_axis(candidate_pose, bone, axis, value)
                        proposal_entries.append(
                            (
                                candidate_pose,
                                f"clip probe f{frame:02d} {bone} {axis} {value:+.3f}"
                                if is_translation_root
                                else f"clip probe f{frame:02d} {bone} {axis} {value:+.1f}",
                                False,
                            )
                        )
                        proposal_meta.append((bone, axis, value, candidate_pose))
            evaluate_frame_batch(frame, proposal_entries)
            rows: list[dict[str, Any]] = []
            for (candidate_pose, label, _live), (bone, axis, value, _meta_pose) in zip(
                proposal_entries, proposal_meta
            ):
                image_score, _result, elapsed = evaluate_frame(
                    frame, candidate_pose, label, live=False
                )
                candidate_scores = dict(image_scores)
                candidate_scores[frame] = image_score
                objective, _details = clip_objective(
                    candidate_scores,
                    {**poses, frame: candidate_pose},
                    frames,
                    bone_names,
                    config,
                )
                rows.append(
                    {
                        "frame": int(frame),
                        "bone": str(bone),
                        "axis": str(axis),
                        "value": float(value),
                        "improvement": float(objective - current_objective),
                        "imageScore": float(image_score),
                        "objective": float(objective),
                        "elapsed": float(elapsed),
                    }
                )
            rows.sort(key=lambda row: float(row["improvement"]), reverse=True)
            probe_ranked_rows_by_frame[frame] = rows[: int(config.probe_top_k)]
            probe_rows_by_frame[frame] = [
                row
                for row in rows
                if float(row["improvement"]) >= float(config.probe_min_improvement)
            ][: int(config.probe_top_k)]
        history.append(
            {
                "kind": "clip_batch_probe",
                "rows": [row for rows in probe_rows_by_frame.values() for row in rows],
                "sensitivity": {
                    str(frame): {
                        f"{row['bone']}:{row['axis']}": float(row["improvement"])
                        for row in probe_ranked_rows_by_frame.get(frame, [])
                    }
                    for frame in frames
                },
                "topKPerFrame": int(config.probe_top_k),
                "stepDeg": float(config.probe_step_deg),
                "elapsed": time.perf_counter() - probe_started,
            }
        )

    # Sparse temporal combinations are the smallest useful step beyond
    # independent probes. Pair only adjacent frames and cap each side by the
    # beam width; this can discover coherent motion that is individually
    # penalized by velocity or acceleration without creating a Cartesian grid.
    if config.adaptive_blocks_enabled and len(frames) >= 2:
        combo_started = time.perf_counter()
        top_per_frame = max(
            2,
            min(int(config.probe_top_k), int(config.adaptive_beam_width)),
        )
        combo_entries_by_frame: dict[int, list[tuple[FramePose, str, bool]]] = {
            frame: [] for frame in frames
        }
        combo_meta = []
        seen_combos = set()
        for left_frame, right_frame in zip(frames, frames[1:]):
            left_rows = probe_ranked_rows_by_frame.get(left_frame, [])[:top_per_frame]
            right_rows = probe_ranked_rows_by_frame.get(right_frame, [])[:top_per_frame]
            for left_row in left_rows:
                matching = [
                    row
                    for row in right_rows
                    if str(row["bone"]) == str(left_row["bone"])
                    and str(row["axis"]) == str(left_row["axis"])
                ] or right_rows
                for right_row in matching[:top_per_frame]:
                    combo_key = (
                        int(left_frame),
                        int(right_frame),
                        str(left_row["bone"]),
                        str(left_row["axis"]),
                        float(left_row["value"]),
                        str(right_row["bone"]),
                        str(right_row["axis"]),
                        float(right_row["value"]),
                    )
                    if combo_key in seen_combos:
                        continue
                    seen_combos.add(combo_key)
                    candidate_poses = copy.deepcopy(poses)
                    _clip_set_axis(
                        candidate_poses[left_frame],
                        str(left_row["bone"]),
                        str(left_row["axis"]),
                        float(left_row["value"]),
                    )
                    _clip_set_axis(
                        candidate_poses[right_frame],
                        str(right_row["bone"]),
                        str(right_row["axis"]),
                        float(right_row["value"]),
                    )
                    label = (
                        f"clip sparse combo f{left_frame:02d}/f{right_frame:02d} "
                        f"{left_row['bone']}:{left_row['axis']}"
                    )
                    combo_meta.append(
                        {
                            "poses": candidate_poses,
                            "frames": (int(left_frame), int(right_frame)),
                            "label": label,
                        }
                    )
                    for changed_frame in (left_frame, right_frame):
                        combo_entries_by_frame[changed_frame].append(
                            (candidate_poses[changed_frame], label, False)
                        )

        for frame, entries in combo_entries_by_frame.items():
            evaluate_frame_batch(frame, entries)
        combo_rows = []
        for combo in combo_meta:
            candidate_scores = dict(image_scores)
            candidate_results = {}
            elapsed_values = []
            for frame in combo["frames"]:
                score, result, elapsed = evaluate_frame(
                    frame,
                    combo["poses"][frame],
                    combo["label"],
                    live=False,
                )
                candidate_scores[frame] = score
                candidate_results[frame] = result
                elapsed_values.append(float(elapsed))
            objective, _details = clip_objective(
                candidate_scores,
                combo["poses"],
                frames,
                bone_names,
                config,
            )
            combo_rows.append(
                {
                    "label": combo["label"],
                    "frames": list(combo["frames"]),
                    "objective": float(objective),
                    "improvement": float(objective - current_objective),
                    "imageScores": {
                        str(frame): float(candidate_scores[frame])
                        for frame in combo["frames"]
                    },
                    "elapsed": max(elapsed_values, default=0.0),
                    "poses": combo["poses"],
                    "results": candidate_results,
                }
            )
        combo_accepted = False
        best_combo = None
        if combo_rows:
            best_combo = max(combo_rows, key=lambda row: float(row["objective"]))
            if float(best_combo["objective"]) > float(current_objective) + 1e-9:
                combo_accepted = True
                poses = copy.deepcopy(best_combo["poses"])
                for frame in best_combo["frames"]:
                    image_scores[frame] = float(best_combo["imageScores"][str(frame)])
                    frame_results[frame] = dict(best_combo["results"][frame])
                current_objective, current_details = clip_objective(
                    image_scores,
                    poses,
                    frames,
                    bone_names,
                    config,
                )
        history.append(
            {
                "kind": "clip_sparse_combo",
                "rows": [
                    {
                        key: row[key]
                        for key in (
                            "label",
                            "frames",
                            "objective",
                            "improvement",
                            "imageScores",
                            "elapsed",
                        )
                    }
                    for row in combo_rows
                ],
                "topPerFrame": int(top_per_frame),
                "beamWidth": int(config.adaptive_beam_width),
                "accepted": bool(combo_accepted),
                "elapsed": time.perf_counter() - combo_started,
            }
        )

    block_seed_rows_by_frame = {
        int(frame): sorted(
            [
                *vector_rows_by_frame.get(int(frame), []),
                *probe_rows_by_frame.get(int(frame), []),
            ],
            key=lambda row: float(row["improvement"]),
            reverse=True,
        )
        for frame in frames
        if vector_rows_by_frame.get(int(frame), []) or probe_rows_by_frame.get(int(frame), [])
    }
    if config.adaptive_blocks_enabled and block_seed_rows_by_frame:
        raw_groups = [list(group) for group in config.adaptive_groups if group]
        if not raw_groups:
            raw_groups = [
                list(bone_names[start : start + int(config.adaptive_block_size)])
                for start in range(0, len(bone_names), int(config.adaptive_block_size))
            ]
        adaptive_blocks: dict[int, list[list[str]]] = {}
        for frame in frames:
            rows = block_seed_rows_by_frame.get(int(frame), [])
            ranked_bones = []
            for row in rows:
                bone = str(row["bone"])
                if bone not in ranked_bones:
                    ranked_bones.append(bone)
            frame_blocks = []
            seen_blocks = set()
            for seed in ranked_bones:
                group = _clip_group_for_bone(seed, bone_names, raw_groups)
                ordered = [
                    bone
                    for bone in sorted(
                        group,
                        key=lambda name: next(
                            (
                                -float(row["improvement"])
                                for row in rows
                                if str(row["bone"]) == name
                            ),
                            0.0,
                        ),
                    )
                    if bone in bone_names
                ]
                control_keys = [
                    control
                    for control, enabled in (
                        (MOTION_ROOT_KEY, root_enabled),
                        (MOTION_ROOT_ROTATION_KEY, root_rotation_enabled),
                    )
                    if enabled and control in group
                ]
                if control_keys:
                    ordered = [
                        *control_keys,
                        *[bone for bone in ordered if bone not in control_keys],
                    ]
                block = tuple(ordered[: int(config.adaptive_block_size)])
                if seed not in block:
                    block = tuple([seed, *block][: int(config.adaptive_block_size)])
                if block and block not in seen_blocks:
                    seen_blocks.add(block)
                    frame_blocks.append(list(block))
            adaptive_blocks[frame] = frame_blocks

        for adaptive_round in range(int(config.adaptive_rounds)):
            for frame in frames:
                for block_index, block in enumerate(adaptive_blocks.get(frame, [])):
                    block_started = time.perf_counter()
                    states = [
                        {
                            "pose": copy.deepcopy(poses[frame]),
                            "score": float(image_scores[frame]),
                            "objective": float(current_objective),
                            "result": frame_results.get(frame, {}),
                        }
                    ]
                    trial_rows = []
                    learned_bones_used: set[str] = set()
                    fallback_bones_used: set[str] = set()
                    for bone in block:
                        expanded = [
                            {
                                "pose": copy.deepcopy(state["pose"]),
                                "score": float(state["score"]),
                                "objective": float(state["objective"]),
                                "result": dict(state.get("result", {})),
                            }
                            for state in states
                        ]
                        entries = []
                        metadata = []
                        for state_index, state in enumerate(states):
                            is_translation_root = _is_motion_root_translation_bone(bone)
                            is_rotation_root = _is_motion_root_rotation_bone(bone)
                            is_root = is_translation_root or is_rotation_root
                            learned_rows = (
                                vector_learned_by_frame.get(int(frame), {}).get(str(bone), [])
                                if config.adaptive_block_learned_directions_enabled
                                and not is_root
                                else []
                            )
                            state_entries = []
                            state_metadata = []
                            if learned_rows and not is_root:
                                current_quaternion = pose_value_to_quaternion(
                                    state["pose"].get(bone, {})
                                )
                                lo, hi = map(float, range_for(bone))
                                max_abs = max(abs(lo), abs(hi))
                                for learned_row in learned_rows:
                                    for candidate_angle in (
                                        -float(config.adaptive_step_deg),
                                        float(config.adaptive_step_deg),
                                    ):
                                        proposal = continuation_proposal(
                                            current_quaternion,
                                            learned_row["axis"],
                                            candidate_angle,
                                            max_abs,
                                            kind=f"{learned_row['kind']}_adaptive",
                                            direction=int(learned_row["direction"]),
                                            twist_policy=str(learned_row["twistPolicy"]),
                                        )
                                        if proposal is None:
                                            continue
                                        candidate_pose = copy.deepcopy(state["pose"])
                                        candidate_pose[bone] = quaternion_pose_entry(
                                            proposal["quaternion"],
                                            twist_policy=proposal["twistPolicy"],
                                        )
                                        state_entries.append(
                                            (
                                                candidate_pose,
                                                f"clip block f{frame:02d} r{adaptive_round + 1} "
                                                f"b{block_index + 1} {bone} learned "
                                                f"{proposal['kind']} {candidate_angle:+.1f}",
                                                False,
                                            )
                                        )
                                        state_metadata.append(
                                            {
                                                "state": int(state_index),
                                                "bone": str(bone),
                                                "proposalMode": "learned_vector",
                                                "kind": str(proposal["kind"]),
                                                "direction": int(proposal["direction"]),
                                                "axis": list(proposal["axis"]),
                                                "angleDeg": float(proposal["angleDeg"]),
                                            }
                                        )
                                if state_entries:
                                    learned_bones_used.add(str(bone))
                            if not state_entries:
                                axes = (
                                    root_axes
                                    if is_translation_root
                                    else root_rotation_axes
                                    if is_rotation_root
                                    else config.axes
                                )
                                for axis in axes:
                                    current = _clip_axis_state(state["pose"], bone, axis)
                                    if is_translation_root:
                                        lo, hi = -root_limits[axis], root_limits[axis]
                                    elif is_rotation_root:
                                        lo, hi = (
                                            -root_rotation_limits[axis],
                                            root_rotation_limits[axis],
                                        )
                                    else:
                                        lo, hi = map(float, range_for(bone))
                                    candidates = _candidate_angles(
                                        current,
                                        lo,
                                        hi,
                                        float(config.adaptive_step_deg),
                                        5,
                                        "local",
                                    )
                                    for candidate_value in candidates:
                                        if abs(candidate_value - current) <= 1e-8:
                                            continue
                                        candidate_pose = copy.deepcopy(state["pose"])
                                        _clip_set_axis(candidate_pose, bone, axis, candidate_value)
                                        state_entries.append(
                                            (
                                                candidate_pose,
                                                f"clip block f{frame:02d} r{adaptive_round + 1} "
                                                f"b{block_index + 1} {bone} {axis} "
                                                f"{candidate_value:+.3f}"
                                                if is_translation_root
                                                else f"clip block f{frame:02d} r{adaptive_round + 1} "
                                                f"b{block_index + 1} {bone} {axis} {candidate_value:+.1f}",
                                                False,
                                            )
                                        )
                                        state_metadata.append(
                                            {
                                                "state": int(state_index),
                                                "bone": str(bone),
                                                "proposalMode": "legacy_euler",
                                                "axis": str(axis),
                                                "value": float(candidate_value),
                                            }
                                        )
                                fallback_bones_used.add(str(bone))
                            entries.extend(state_entries)
                            metadata.extend(state_metadata)
                        evaluate_frame_batch(frame, entries)
                        for (candidate_pose, label, _live), meta in zip(entries, metadata):
                            score, result, elapsed = evaluate_frame(
                                frame, candidate_pose, label, live=False
                            )
                            candidate_scores = dict(image_scores)
                            candidate_scores[frame] = score
                            objective, _details = clip_objective(
                                candidate_scores,
                                {**poses, frame: candidate_pose},
                                frames,
                                bone_names,
                                config,
                            )
                            expanded.append(
                                {
                                    "pose": candidate_pose,
                                    "score": float(score),
                                    "objective": float(objective),
                                    "result": result,
                                }
                            )
                            trial_row = {
                                "frame": int(frame),
                                "bone": str(meta["bone"]),
                                "state": int(meta["state"]),
                                "objective": float(objective),
                                "elapsed": float(elapsed),
                                "proposalMode": str(meta["proposalMode"]),
                            }
                            if meta["proposalMode"] == "learned_vector":
                                trial_row.update(
                                    {
                                        "kind": str(meta["kind"]),
                                        "direction": int(meta["direction"]),
                                        "axis": list(meta["axis"]),
                                        "angleDeg": float(meta["angleDeg"]),
                                    }
                                )
                            else:
                                trial_row.update(
                                    {
                                        "axis": str(meta["axis"]),
                                        "value": float(meta["value"]),
                                    }
                                )
                            trial_rows.append(trial_row)
                        if expanded:
                            expanded.sort(key=lambda state: float(state["objective"]), reverse=True)
                            states = expanded[: int(config.adaptive_beam_width)]
                    if states:
                        best_state = max(states, key=lambda state: float(state["objective"]))
                        if float(best_state["objective"]) > float(current_objective) + 1e-9:
                            poses[frame] = copy.deepcopy(best_state["pose"])
                            image_scores[frame] = float(best_state["score"])
                            frame_results[frame] = dict(best_state["result"])
                            current_objective, current_details = clip_objective(
                                image_scores, poses, frames, bone_names, config
                            )
                    timings.append(
                        {
                            "kind": "clip_adaptive_block",
                            "frame": int(frame),
                            "block": list(block),
                            "round": int(adaptive_round + 1),
                            "beamWidth": int(config.adaptive_beam_width),
                            "stepDeg": float(config.adaptive_step_deg),
                            "evaluations": len(trial_rows),
                            "elapsed": time.perf_counter() - block_started,
                            "objective": float(current_objective),
                        }
                    )
                    history.append(
                        {
                            "kind": "clip_adaptive_block",
                            "frame": int(frame),
                            "block": list(block),
                            "round": int(adaptive_round + 1),
                            "beamWidth": int(config.adaptive_beam_width),
                            "stepDeg": float(config.adaptive_step_deg),
                            "trials": trial_rows,
                            "learnedDirectionalBones": sorted(learned_bones_used),
                            "legacyEulerBones": sorted(fallback_bones_used),
                            "learnedDirectionsEnabled": bool(
                                config.adaptive_block_learned_directions_enabled
                            ),
                            "objective": float(current_objective),
                        }
                    )

    coarse_rounds = int(config.rounds)
    refine_rounds = (
        int(config.polish_rounds)
        if config.polish_enabled
        else int(config.refine_rounds)
    )

    total_rounds = coarse_rounds + refine_rounds
    accepted = 0
    refine_targets: set[tuple[int, str, str]] | None = None
    for round_index in range(total_rounds):
        step = (
            config.coarse_step_deg
            if round_index < coarse_rounds
            else (config.polish_step_deg if config.polish_enabled else config.refine_step_deg)
        )
        round_start = time.perf_counter()
        round_rows = []
        skipped_refine_axes = 0
        for frame in frames:
            for bone in bone_names:
                is_translation_root = _is_motion_root_translation_bone(bone)
                is_rotation_root = _is_motion_root_rotation_bone(bone)
                is_root = is_translation_root or is_rotation_root
                axes = (
                    root_axes
                    if is_translation_root
                    else root_rotation_axes
                    if is_rotation_root
                    else config.axes
                )
                for axis in axes:
                    if (
                        round_index >= int(config.rounds)
                        and config.refine_accepted_only
                        and refine_targets is not None
                        and (frame, bone, axis) not in refine_targets
                    ):
                        skipped_refine_axes += 1
                        continue
                    if is_translation_root:
                        current = _clip_axis_state(poses[frame], bone, axis)
                        lo, hi = -root_limits[axis], root_limits[axis]
                        step_for_axis = (
                            float(config.motion_root_coarse_step_body_lengths)
                            if round_index < int(config.rounds)
                            else float(config.motion_root_refine_step_body_lengths)
                        )
                    elif is_rotation_root:
                        current = _clip_axis_state(poses[frame], bone, axis)
                        lo, hi = (
                            -root_rotation_limits[axis],
                            root_rotation_limits[axis],
                        )
                        step_for_axis = (
                            float(config.motion_root_rotation_coarse_step_deg)
                            if round_index < int(config.rounds)
                            else float(config.motion_root_rotation_refine_step_deg)
                        )
                    else:
                        axis_index = "xyz".index(axis)
                        current = float(np.degrees(_axis_values(poses[frame][bone])[axis_index]))
                        lo, hi = map(float, range_for(bone))
                        step_for_axis = float(step)
                    candidates = _candidate_angles(
                        current,
                        lo,
                        hi,
                        step_for_axis,
                        int(config.max_evaluations_per_axis),
                        str(config.candidate_mode),
                    )
                    axis_baseline_objective = float(current_objective)
                    best_local = axis_baseline_objective
                    best_angle = current
                    acceptance_threshold = max(
                        float(config.acceptance_margin),
                        abs(axis_baseline_objective)
                        * float(config.acceptance_relative_margin),
                    )
                    axis_rows = []
                    proposal_entries = []
                    for candidate_angle in candidates:
                        if abs(candidate_angle - current) <= 1e-8:
                            continue
                        candidate_pose = copy.deepcopy(poses[frame])
                        _clip_set_axis(candidate_pose, bone, axis, candidate_angle)
                        proposal_entries.append((
                            candidate_pose,
                            f"clip r{round_index + 1} f{frame:02d} {bone} {axis} "
                            f"{candidate_angle:+.3f}"
                            if is_translation_root
                            else f"clip r{round_index + 1} f{frame:02d} {bone} {axis} {candidate_angle:+.1f}",
                            live_preview and config.preview_candidates,
                        ))
                    evaluate_frame_batch(frame, proposal_entries)
                    for candidate_pose, proposal_label, proposal_live in proposal_entries:
                        candidate_angle = _clip_axis_state(candidate_pose, bone, axis)
                        image_score, result, elapsed = evaluate_frame(
                            frame,
                            candidate_pose,
                            proposal_label,
                            live=proposal_live,
                        )
                        candidate_scores = dict(image_scores)
                        candidate_scores[frame] = image_score
                        candidate_objective, details = clip_objective(
                            candidate_scores,
                            {**poses, frame: candidate_pose},
                            frames,
                            bone_names,
                            config,
                        )
                        axis_rows.append({
                            "angleDeg": candidate_angle,
                            "imageScore": image_score,
                            "objective": candidate_objective,
                            "improvement": float(candidate_objective - axis_baseline_objective),
                            "triageRejected": bool(
                                isinstance(result, dict) and result.get("triageRejected")
                            ),
                            "branchBoundRejected": bool(
                                isinstance(result, dict)
                                and result.get("semanticBranchBoundRejected")
                            ),
                            "elapsed": elapsed,
                        })
                        if candidate_objective > best_local + 1e-9:
                            best_local = candidate_objective
                            best_angle = candidate_angle
                    accepted_move = (
                        abs(best_angle - current) > 1e-8
                        and best_local > axis_baseline_objective + acceptance_threshold
                    )
                    if accepted_move:
                        _clip_set_axis(poses[frame], bone, axis, best_angle)
                        image_scores[frame], frame_results[frame], _ = evaluate_frame(
                            frame,
                            poses[frame],
                            f"clip r{round_index + 1} accepted f{frame:02d} {bone} {axis} {best_angle:+.1f}",
                            live=live_preview,
                        )
                        current_objective, current_details = clip_objective(
                            image_scores, poses, frames, bone_names, config
                        )
                        accepted += 1
                    else:
                        best_angle = current
                    objective_values = [
                        float(candidate.get("objective", axis_baseline_objective))
                        for candidate in axis_rows
                        if not candidate.get("triageRejected")
                        and not candidate.get("branchBoundRejected")
                    ]
                    sensitivity_span = (
                        max(objective_values) - min(objective_values)
                        if objective_values
                        else 0.0
                    )
                    round_rows.append({
                        "frame": frame,
                        "bone": bone,
                        "axis": axis,
                        "range": [float(lo), float(hi)],
                        "rangeDeg": None if is_translation_root else [float(lo), float(hi)],
                        "units": "body_lengths" if is_translation_root else "degrees",
                        "candidateMode": str(config.candidate_mode),
                        "candidateAnglesDeg": [float(value) for value in candidates],
                        "acceptanceThreshold": float(acceptance_threshold),
                        "bestImprovement": float(max(0.0, best_local - axis_baseline_objective)),
                        "current": current,
                        "chosen": best_angle,
                        "currentDeg": None if is_translation_root else current,
                        "chosenDeg": None if is_translation_root else best_angle,
                        "accepted": bool(accepted_move),
                        "sensitivity": float(sensitivity_span),
                        "sensitivityEpsilon": float(config.sensitivity_score_epsilon),
                        "objective": current_objective,
                        "candidates": axis_rows,
                    })
        if round_index == int(config.rounds) - 1:
            if config.refine_accepted_only:
                refine_targets = {
                    (int(row["frame"]), str(row["bone"]), str(row["axis"]))
                    for row in round_rows
                    if row["accepted"]
                    or (
                        config.sensitivity_enabled
                        and float(row.get("sensitivity", 0.0))
                        >= float(config.sensitivity_score_epsilon)
                    )
                }
                if config.polish_include_neighbors and refine_targets:
                    # Keep neighbor expansion local to the frame that made a
                    # bone sensitive. A sensitive arm on frame 2 should not
                    # silently force every arm axis on every other frame into
                    # the polish pass.
                    for frame in {row["frame"] for row in round_rows}:
                        frame_bones = {
                            bone
                            for candidate_frame, bone, _axis in refine_targets
                            if candidate_frame == frame
                        }
                        neighbor_bones = set()
                        for group in config.adaptive_groups:
                            group_set = set(group)
                            if frame_bones & group_set:
                                neighbor_bones.update(group_set)
                        for _frame, _bone, axis in list(refine_targets):
                            if _frame != frame:
                                continue
                            for neighbor in neighbor_bones:
                                if neighbor in bone_names:
                                    refine_targets.add((frame, neighbor, axis))
            else:
                refine_targets = None
        timings.append({
            "round": round_index + 1,
            "stepDeg": float(step),
            "elapsed": time.perf_counter() - round_start,
            "accepted": sum(1 for row in round_rows if row["accepted"]),
            "skippedRefineAxes": skipped_refine_axes,
            "rows": round_rows,
            "objective": current_objective,
            "details": current_details,
        })
        history.append({
            "kind": "clip_round",
            "round": round_index + 1,
            "stepDeg": float(step),
            "objective": current_objective,
            "details": current_details,
            "accepted": timings[-1]["accepted"],
            "skippedRefineAxes": skipped_refine_axes,
            "elapsed": timings[-1]["elapsed"],
        })
        print(
            f"clip round {round_index + 1}/{total_rounds}: "
            f"objective={current_objective:.6f} image={current_details['image']:.6f} "
            f"velocity={current_details['temporal']['velocity']:.4f} "
            f"acceleration={current_details['temporal']['acceleration']:.4f} "
            f"accepted={timings[-1]['accepted']} "
            f"elapsed={timings[-1]['elapsed']:.2f}s"
        )

    # Re-render one committed final state so the live panel cannot be left on
    # a rejected proposal from the last coordinate scan.
    if live_preview and frames:
        final_frame = frames[-1]
        score_frame(
            final_frame,
            poses[final_frame],
            f"clip final committed f{final_frame:02d}",
            True,
        )

    return {
        "poses": poses,
        "history": history,
        "timings": timings,
        "frameResults": frame_results,
        "frameScores": image_scores,
        "objective": current_objective,
        "objectiveDetails": current_details,
        "evaluations": len(evaluation_cache),
        "accepted": accepted,
        "elapsed": time.perf_counter() - started,
        "config": {
            "frameIndices": list(frames),
            "bones": list(bone_names),
            "rounds": config.rounds,
            "refineRounds": config.refine_rounds,
            "velocityWeight": config.velocity_weight,
            "accelerationWeight": config.acceleration_weight,
            "contactWeight": config.contact_weight,
            "loopWeight": config.loop_weight,
            "loopVelocityWeight": config.loop_velocity_weight,
            "motionRootEnabled": bool(root_enabled),
            "motionRootAxes": list(root_axes),
            "motionRootForwardRadiusBodyLengths": config.motion_root_forward_radius_body_lengths,
            "motionRootLateralRadiusBodyLengths": config.motion_root_lateral_radius_body_lengths,
            "motionRootVerticalRadiusBodyLengths": config.motion_root_vertical_radius_body_lengths,
            "motionRootCoarseStepBodyLengths": config.motion_root_coarse_step_body_lengths,
            "motionRootRefineStepBodyLengths": config.motion_root_refine_step_body_lengths,
            "motionRootMagnitudeWeight": config.motion_root_magnitude_weight,
            "motionRootVelocityWeight": _root_weight(config, "velocity"),
            "motionRootAccelerationWeight": _root_weight(config, "acceleration"),
            "motionRootLoopWeight": config.motion_root_loop_weight,
            "motionRootCoupledBlocksEnabled": bool(
                config.motion_root_coupled_blocks_enabled
            ),
            "motionRootRotationEnabled": bool(root_rotation_enabled),
            "motionRootRotationBasis": str(config.motion_root_rotation_basis),
            "motionRootRotationAxes": list(root_rotation_axes),
            "motionRootRotationLimitDeg": config.motion_root_rotation_limit_deg,
            "motionRootRotationCoarseStepDeg": config.motion_root_rotation_coarse_step_deg,
            "motionRootRotationRefineStepDeg": config.motion_root_rotation_refine_step_deg,
            "motionRootRotationEscapeEnabled": bool(
                config.motion_root_rotation_escape_enabled
            ),
            "motionRootRotationEscapeAxes": list(
                _root_rotation_escape_axes(config)
            ),
            "motionRootRotationEscapeAnglesDeg": [
                float(value) for value in config.motion_root_rotation_escape_angles_deg
            ],
            "motionRootRotationEscapeTopK": config.motion_root_rotation_escape_top_k,
            "motionRootRotationEscapeForceImageBest": bool(
                config.motion_root_rotation_escape_force_image_best
            ),
            "motionRootRotationEscapeMinImageImprovement": config.motion_root_rotation_escape_min_image_improvement,
            "motionRootRotationEscapeRelaxEnabled": bool(
                config.motion_root_rotation_escape_relax_enabled
            ),
            "motionRootRotationEscapeRelaxBoneCount": int(
                config.motion_root_rotation_escape_relax_bone_count
            ),
            "motionRootRotationEscapeRelaxRounds": int(
                config.motion_root_rotation_escape_relax_rounds
            ),
            "motionRootRotationEscapeRelaxStepDeg": float(
                config.motion_root_rotation_escape_relax_step_deg
            ),
            "motionRootRotationEscapeRelaxRefineStepDeg": float(
                config.motion_root_rotation_escape_relax_refine_step_deg
            ),
            "motionRootRotationMagnitudeWeight": config.motion_root_rotation_magnitude_weight,
            "motionRootRotationVelocityWeight": _root_rotation_weight(
                config, "velocity"
            ),
            "motionRootRotationAccelerationWeight": _root_rotation_weight(
                config, "acceleration"
            ),
            "motionRootRotationLoopWeight": config.motion_root_rotation_loop_weight,
            "motionRootRotationLoopVelocityWeight": _root_rotation_weight(
                config, "loop_velocity"
            ),
            "motionRootRotationCoupledBlocksEnabled": bool(
                config.motion_root_rotation_coupled_blocks_enabled
            ),
            "bodyTranslationVelocityWeight": _root_weight(config, "velocity"),
            "bodyTranslationAccelerationWeight": _root_weight(config, "acceleration"),
            "contactBones": list(config.contact_bones),
            "loopEnabled": config.loop_enabled,
            "robustScaleDeg": config.robust_scale_deg,
            "coarseStepDeg": config.coarse_step_deg,
            "refineStepDeg": config.refine_step_deg,
            "maxEvaluationsPerAxis": config.max_evaluations_per_axis,
            "candidateMode": str(config.candidate_mode),
            "acceptanceMargin": config.acceptance_margin,
            "acceptanceRelativeMargin": config.acceptance_relative_margin,
            "axes": list(config.axes),
            "batchCandidates": bool(config.batch_candidates and score_frame_batch is not None),
            "probeEnabled": bool(config.probe_enabled),
            "probeStepDeg": config.probe_step_deg,
            "probeTopK": config.probe_top_k,
            "adaptiveBlocksEnabled": bool(config.adaptive_blocks_enabled),
            "adaptiveBlockSize": config.adaptive_block_size,
            "adaptiveRounds": config.adaptive_rounds,
            "adaptiveStepDeg": config.adaptive_step_deg,
            "adaptiveBeamWidth": config.adaptive_beam_width,
            "adaptiveGroups": [list(group) for group in config.adaptive_groups],
            "polishEnabled": bool(config.polish_enabled),
            "polishRounds": config.polish_rounds,
            "polishStepDeg": config.polish_step_deg,
            "sensitivityEnabled": bool(config.sensitivity_enabled),
            "sensitivityScoreEpsilon": config.sensitivity_score_epsilon,
            "polishIncludeNeighbors": bool(config.polish_include_neighbors),
            "rotationVectorSearchEnabled": bool(config.rotation_vector_search_enabled),
            "rotationVectorProbeCount": config.rotation_vector_probe_count,
            "rotationVectorProbeStepDeg": config.rotation_vector_probe_step_deg,
            "rotationVectorLegacyEulerFallbackEnabled": bool(
                config.rotation_vector_legacy_euler_fallback_enabled
            ),
            "rotationVectorInformativeMinImprovement": float(
                config.rotation_vector_informative_min_improvement
            ),
            "directionalContinuationEnabled": bool(config.directional_continuation_enabled),
            "directionalMaxSteps": config.directional_max_steps,
            "directionalStepMultiplier": config.directional_step_multiplier,
            "directionalTopK": config.directional_top_k,
            "directionalMinImprovement": config.directional_min_improvement,
            "adaptiveBlockLearnedDirectionsEnabled": bool(
                config.adaptive_block_learned_directions_enabled
            ),
            "boneTwistPolicy": config.bone_twist_policy,
            "boneTwistOverrides": dict(config.bone_twist_overrides),
        },
    }


def optimize_clip(
    frame_indices: Sequence[int],
    bones: Sequence[str],
    initial_poses: Mapping[int, Mapping[str, Any]] | None,
    score_frame: ScoreFrame,
    range_for: RangeForBone,
    config: TemporalClipConfig,
    *,
    score_frame_batch: ScoreFrameBatch | None = None,
    progress: Any = True,
    live_preview: bool = True,
) -> dict[str, Any]:
    """Run the clip solver and own its progress display when requested.

    ``ClipProgress`` is deliberately accepted here so the notebook can keep
    one bar alive across warm-start fitting and the global search. Direct
    callers that pass ``True`` still get a self-contained bar.
    """
    reporter = progress if isinstance(progress, ClipProgress) else ClipProgress(progress)
    owns_reporter = reporter is not progress
    try:
        return _optimize_clip_impl(
            frame_indices,
            bones,
            initial_poses,
            score_frame,
            range_for,
            config,
            score_frame_batch=score_frame_batch,
            progress=progress,
            live_preview=live_preview,
            progress_callback=reporter.emit,
        )
    finally:
        if owns_reporter:
            reporter.close()


__all__ = [
    "ClipProgress",
    "TemporalClipConfig",
    "clip_objective",
    "optimize_clip",
    "pose_matrix",
    "rotation_matrix",
    "temporal_terms",
]
