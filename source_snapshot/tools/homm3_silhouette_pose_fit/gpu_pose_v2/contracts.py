"""Small, serializable contracts shared by the V2 solver and notebook.

The tensors in these dataclasses are intentionally typed as ``Any`` so the
contracts remain importable in a CPU-only documentation process.  Runtime
validation in the renderer and solver requires CUDA tensors where appropriate.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class CameraSpec:
    """Orthographic camera in the GLB world coordinate system."""

    width: int = 128
    height: int = 116
    right: tuple[float, float, float] = (1.0, 0.0, 0.0)
    down: tuple[float, float, float] = (0.0, -1.0, 0.0)
    forward: tuple[float, float, float] = (0.0, 0.0, 1.0)
    offset: tuple[float, float] = (64.0, 58.0)
    px_per_world: tuple[float, float] = (64.0, 64.0)
    near: float = -10.0
    far: float = 10.0

    def validate(self) -> None:
        if int(self.width) < 16 or int(self.height) < 16:
            raise ValueError("camera resolution must be at least 16x16")
        for name in ("right", "down", "forward"):
            values = tuple(float(value) for value in getattr(self, name))
            length = math.sqrt(sum(value * value for value in values))
            if length <= 1e-8:
                raise ValueError(f"camera {name} basis vector is zero")
        if not float(self.far) > float(self.near):
            raise ValueError("camera far must be greater than near")
        if any(float(value) <= 0.0 for value in self.px_per_world):
            raise ValueError("camera px_per_world must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None, *, width: int | None = None, height: int | None = None) -> "CameraSpec":
        raw = dict(value or {})
        rows = raw.get("basisScreenRows")
        if rows is not None and len(rows) >= 2:
            right = rows[0]
            down = rows[1]
        else:
            right = raw.get("right", raw.get("cameraRight", (1.0, 0.0, 0.0)))
            down = raw.get("down", raw.get("cameraDown", (0.0, -1.0, 0.0)))
        forward = raw.get("forward", raw.get("cameraForward", (0.0, 0.0, 1.0)))
        if raw.get("forward") is None and raw.get("cameraForward") is None and rows is not None and len(rows) >= 2:
            right_array = np.asarray(right, dtype=np.float64)
            down_array = np.asarray(down, dtype=np.float64)
            forward = np.cross(right_array, down_array).tolist()
        source_resolution = raw.get("sourceResolution", (raw.get("sourceWidth", 0), raw.get("sourceHeight", 0)))
        target_width = int(width if width is not None else raw.get("width", 128))
        target_height = int(height if height is not None else raw.get("height", 116))
        source_width = float(source_resolution[0] or target_width)
        source_height = float(source_resolution[1] or target_height)
        scale_x = target_width / max(source_width, 1.0)
        scale_y = target_height / max(source_height, 1.0)
        raw_offset = raw.get("offset", raw.get("screenOffset", raw.get("screenOffsetPx", (target_width / 2.0, target_height / 2.0))))
        offset = (float(raw_offset[0]) * scale_x, float(raw_offset[1]) * scale_y)
        raw_px = raw.get("pxPerWorld", raw.get("px_per_world", (64.0, 64.0)))
        if isinstance(raw_px, (int, float)):
            raw_px = (raw_px, raw_px)
        px = (float(raw_px[0]) * scale_x, float(raw_px[1]) * scale_y)
        result = cls(
            width=target_width,
            height=target_height,
            right=tuple(float(v) for v in right),
            down=tuple(float(v) for v in down),
            forward=tuple(float(v) for v in forward),
            offset=tuple(float(v) for v in offset),
            px_per_world=tuple(float(v) for v in px),
            near=float(raw.get("near", -10.0)),
            far=float(raw.get("far", 10.0)),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class V2Config:
    """Experiment controls; notebook presets should cover normal use."""

    device: str = "cuda"
    resolution: tuple[int, int] = (128, 116)
    source_kind: str = "def"
    alpha_threshold: int = 8
    mesh_scale: float = 1.0
    registration_hypotheses: int = 256
    registration_keep: int = 8
    articulated_keep: int = 4
    semantic_keep: int = 2
    registration_iterations: int = 80
    motion_root_iterations: int = 48
    motion_root_hypotheses: int = 1
    proximal_iterations: int = 120
    articulated_iterations: int = 180
    fine_iterations: int = 100
    registration_frame_position: int = 0
    registration_learning_rate: float = 0.025
    articulated_learning_rate: float = 0.012
    fine_learning_rate: float = 0.004
    registration_rotation_limit_deg: float = 180.0
    registration_translation_body_lengths: float = 0.50
    registration_scale_log_limit: float = 0.55
    motion_rotation_limit_deg: float = 180.0
    motion_translation_body_lengths: float = 0.65
    joint_limit_deg: float = 180.0
    proximal_depth: int = 2
    raster_antialias: bool = True
    silhouette_weight: float = 1.0
    missing_weight: float = 0.35
    excess_weight: float = 0.35
    edge_weight: float = 0.20
    sdf_weight: float = 0.20
    depth_weight: float = 0.15
    centroid_weight: float = 0.08
    occupancy_weight: float = 0.08
    global_semantic_weight: float = 0.08
    dense_semantic_weight: float = 0.16
    anatomy_weight: float = 0.08
    rigidity_weight: float = 0.25
    pose_prior_weight: float = 0.015
    root_prior_weight: float = 0.025
    velocity_weight: float = 0.025
    acceleration_weight: float = 0.018
    loop_weight: float = 0.002
    loop_objective_enabled: bool = False
    robust_scale_deg: float = 48.0
    semantic_enabled: bool = True
    semantic_model_id: str = "google/siglip2-base-patch16-512"
    semantic_layers: tuple[str, ...] = ("projected", "pooler")
    dense_semantic_enabled: bool = True
    dense_model_id: str = "google/siglip2-base-patch16-512"
    dense_model_family: str = "auto"
    dense_layers: tuple[str, ...] = ("last",)
    dense_model_revision: str | None = None
    dense_trust_remote_code: bool = False
    dense_local_files_only: bool = False
    dense_local_radius: int = 1
    dense_position_weight: float = 0.15
    semantic_rescue_iterations: int = 24
    semantic_microbatch: int = 1
    interpolation_mode: str = "quaternion_slerp"
    interpolation_output_fps: float = 60.0
    interpolation_loop: bool = False
    blender_lighting_mode: str = "sun_above"
    blender_sun_energy: float = 2.0
    blender_sun_azimuth_deg: float = -35.0
    blender_sun_elevation_deg: float = 55.0
    blender_sun_angle_deg: float = 5.0
    blender_render_scale: float = 0.5
    target_depth_dir: str | None = None
    # Optional generated front-view auxiliary target.  It is deliberately
    # separate from the authentic profile target: the DEF silhouette remains
    # authoritative, while this view supplies soft left/right and depth-axis
    # disambiguation for otherwise equivalent poses.
    front_view_enabled: bool = False
    front_view_silhouette_weight: float = 0.22
    front_view_missing_weight: float = 0.08
    front_view_excess_weight: float = 0.08
    front_view_edge_weight: float = 0.06
    front_view_sdf_weight: float = 0.10
    front_view_global_semantic_weight: float = 0.04
    front_view_dense_semantic_weight: float = 0.08
    front_view_camera_scale: float = 1.0
    front_view_fit_camera_scale: bool = True
    front_view_background_threshold: int = 12
    front_view_subject_extent: float = 0.72
    front_view_subject_padding: float = 0.08
    return_buffers: bool = True
    checkpoint_every_stage: bool = True
    progress_every: int = 1

    def validate(self) -> None:
        width, height = (int(value) for value in self.resolution)
        if width < 16 or height < 16:
            raise ValueError("resolution must be at least 16x16")
        if self.source_kind.lower() != "def":
            raise ValueError("V2 only accepts authentic DEF source frames")
        if not 0 <= int(self.alpha_threshold) <= 255:
            raise ValueError("alpha_threshold must be between 0 and 255")
        if not 0 <= int(self.front_view_background_threshold) <= 255:
            raise ValueError("front_view_background_threshold must be between 0 and 255")
        if float(self.mesh_scale) <= 0.0:
            raise ValueError("mesh_scale must be positive")
        for name in (
            "registration_hypotheses", "registration_keep", "motion_root_hypotheses",
            "articulated_keep", "semantic_keep",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if int(self.registration_keep) > int(self.registration_hypotheses):
            raise ValueError("registration_keep cannot exceed registration_hypotheses")
        if int(self.articulated_keep) > int(self.registration_keep):
            raise ValueError("articulated_keep cannot exceed registration_keep")
        if int(self.semantic_keep) > int(self.articulated_keep):
            raise ValueError("semantic_keep cannot exceed articulated_keep")
        for name in (
            "registration_iterations", "motion_root_iterations", "proximal_iterations", "articulated_iterations", "fine_iterations",
            "semantic_rescue_iterations", "proximal_depth", "dense_local_radius", "progress_every",
            "registration_frame_position",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        for name in (
            "registration_learning_rate", "articulated_learning_rate", "fine_learning_rate",
            "registration_rotation_limit_deg", "registration_translation_body_lengths",
            "registration_scale_log_limit", "motion_rotation_limit_deg", "motion_translation_body_lengths",
            "joint_limit_deg", "robust_scale_deg", "front_view_camera_scale",
            "front_view_subject_extent",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if str(self.interpolation_mode).lower() not in {
            "axis_angle_linear", "quaternion_slerp", "cubic_quaternion", "motion_aware",
        }:
            raise ValueError(
                "interpolation_mode must be axis_angle_linear, quaternion_slerp, "
                "cubic_quaternion, or motion_aware"
            )
        if str(self.dense_model_family).lower() not in {"auto", "siglip2", "dino"}:
            raise ValueError("dense_model_family must be auto, siglip2, or dino")
        if not math.isfinite(float(self.interpolation_output_fps)) or float(self.interpolation_output_fps) <= 0.0:
            raise ValueError("interpolation_output_fps must be finite and positive")
        if str(self.blender_lighting_mode).lower() not in {"sun_above", "flat_emission"}:
            raise ValueError("blender_lighting_mode must be sun_above or flat_emission")
        for name in (
            "blender_sun_energy", "blender_sun_angle_deg", "blender_render_scale",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in ("blender_sun_azimuth_deg", "blender_sun_elevation_deg"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        for name in (
            "silhouette_weight", "missing_weight", "excess_weight", "edge_weight", "sdf_weight",
            "depth_weight", "centroid_weight", "occupancy_weight", "global_semantic_weight",
            "dense_semantic_weight", "anatomy_weight", "rigidity_weight", "pose_prior_weight",
            "root_prior_weight", "velocity_weight", "acceleration_weight", "loop_weight",
            "dense_position_weight", "front_view_silhouette_weight", "front_view_missing_weight",
            "front_view_excess_weight", "front_view_edge_weight", "front_view_sdf_weight",
            "front_view_global_semantic_weight", "front_view_dense_semantic_weight",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if int(self.semantic_microbatch) < 1:
            raise ValueError("semantic_microbatch must be positive")
        if not 0.0 <= float(self.front_view_subject_padding) < 1.0:
            raise ValueError("front_view_subject_padding must be in [0, 1)")

    def to_jsonable(self) -> dict[str, Any]:
        value = asdict(self)
        value["resolution"] = list(self.resolution)
        value["semantic_layers"] = list(self.semantic_layers)
        value["dense_layers"] = list(self.dense_layers)
        return value


def preset_config(name: str = "plausible_3d", **overrides: Any) -> V2Config:
    """Return a validated preset with explicit, reproducible defaults."""
    normalized = str(name).strip().lower()
    if normalized == "fast":
        base = V2Config(
            registration_hypotheses=96,
            registration_keep=4,
            articulated_keep=2,
            semantic_keep=1,
            registration_iterations=32,
            motion_root_iterations=32,
            motion_root_hypotheses=1,
            proximal_iterations=48,
            articulated_iterations=72,
            fine_iterations=32,
            semantic_rescue_iterations=8,
        )
    elif normalized == "balanced":
        base = V2Config(
            registration_hypotheses=160,
            registration_keep=6,
            articulated_keep=3,
            semantic_keep=2,
            registration_iterations=56,
            motion_root_iterations=48,
            motion_root_hypotheses=1,
            proximal_iterations=84,
            articulated_iterations=128,
            fine_iterations=64,
            semantic_rescue_iterations=16,
        )
    elif normalized == "plausible_3d":
        base = V2Config()
    else:
        raise ValueError(f"unknown V2 preset: {name!r}")
    result = replace(base, **overrides)
    result.validate()
    return result


@dataclass(frozen=True)
class PreparedRig:
    path: Path
    asset: Any
    mesh_scale: float
    node_names: tuple[str, ...]
    parents: tuple[int | None, ...]
    node_depths: tuple[int, ...]
    pivot: Any
    primitives: tuple[Any, ...]
    rigidization: Mapping[str, Any] | None
    fingerprint: str
    device: str
    semantic_surface_descriptors: Mapping[str, Any] | None = None
    # Scene nodes are not interchangeable with bones. Mesh and armature
    # container nodes can appear in the glTF node list but are not skin joints
    # and must never become optimization variables.
    skeleton_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class PreparedClip:
    source_dir: Path
    frame_paths: tuple[Path, ...]
    frame_indices: tuple[int, ...]
    source_fps: float
    frame_durations: tuple[float, ...]
    rgb: Any
    masks: Any
    depth: Any | None
    depth_confidence: Any | None
    edge: Any
    sdf: Any
    feature_points: tuple[Any, ...]
    fingerprint: str
    shadow_cull_report: Mapping[str, Any]
    # Generated front-view references are optional auxiliary evidence.  They
    # are kept in the clip contract so every solver stage uses the same frame
    # mapping and provenance rather than rebuilding it in notebook code.
    front_frame_paths: tuple[Path, ...] = ()
    front_rgb: Any | None = None
    front_masks: Any | None = None
    front_edge: Any | None = None
    front_sdf: Any | None = None
    front_feature_points: tuple[Any, ...] = ()
    front_fingerprint: str | None = None
    front_provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PoseState:
    """Canonical pose: registration is shared; motion is per-frame."""

    registration: Any
    motion_translation: Any
    motion_rotation: Any
    bone_rotation: Any
    frame_indices: tuple[int, ...]

    def detached(self) -> "PoseState":
        def detach(value: Any) -> Any:
            return value.detach().clone() if hasattr(value, "detach") else value
        return PoseState(
            registration=detach(self.registration),
            motion_translation=detach(self.motion_translation),
            motion_rotation=detach(self.motion_rotation),
            bone_rotation=detach(self.bone_rotation),
            frame_indices=tuple(self.frame_indices),
        )


@dataclass(frozen=True)
class RenderBuffers:
    rgb: Any
    alpha: Any
    depth: Any
    triangle_id: Any
    barycentrics: Any
    world_position: Any
    normal: Any | None
    dominant_bone: Any | None


@dataclass(frozen=True)
class ObjectiveBreakdown:
    total: Any
    per_frame: Mapping[str, Any]
    diagnostics: Mapping[str, Any]
    rejection_reasons: tuple[str, ...] = ()
    observability: Mapping[str, Any] = field(default_factory=dict)
    gradients: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PoseHypothesis:
    pose: PoseState
    objective: ObjectiveBreakdown
    stage: str
    lineage: tuple[int, ...] = ()
    semantic: Mapping[str, Any] | None = None
    optimizer_state: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ExperimentResult:
    selected: PoseHypothesis
    alternatives: tuple[PoseHypothesis, ...]
    history: tuple[Mapping[str, Any], ...]
    artifacts: Mapping[str, str]
    provenance: Mapping[str, Any]
    timings: Mapping[str, float]
    parity: Mapping[str, Any] | None = None
    previews: Mapping[str, str] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        canonical_pose = {
            "registration": _jsonable(self.selected.pose.registration),
            "motionTranslation": _jsonable(self.selected.pose.motion_translation),
            "motionRotation": _jsonable(self.selected.pose.motion_rotation),
            "boneRotation": _jsonable(self.selected.pose.bone_rotation),
            "frameIndices": list(self.selected.pose.frame_indices),
            "rotationRepresentation": "axis_angle_radians_glTF_world_axes",
            "rootRepresentation": "camera_basis_registration_then_motion",
        }
        return {
            "schemaVersion": 2,
            "selected": _jsonable_hypothesis(self.selected),
            "alternatives": [_jsonable_hypothesis(value) for value in self.alternatives],
            "canonicalPose": canonical_pose,
            "history": [_jsonable(value) for value in self.history],
            "artifacts": dict(self.artifacts),
            "provenance": _jsonable(self.provenance),
            "timings": dict(self.timings),
            "parity": _jsonable(self.parity),
            "previews": dict(self.previews),
        }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "detach"):
        return value.detach().cpu().tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _jsonable_hypothesis(value: PoseHypothesis) -> dict[str, Any]:
    return {
        "stage": value.stage,
        "lineage": list(value.lineage),
        "pose": {
            "registration": _jsonable(value.pose.registration),
            "motionTranslation": _jsonable(value.pose.motion_translation),
            "motionRotation": _jsonable(value.pose.motion_rotation),
            "boneRotation": _jsonable(value.pose.bone_rotation),
            "frameIndices": list(value.pose.frame_indices),
        },
        "objective": {
            "total": _jsonable(value.objective.total),
            "perFrame": _jsonable(value.objective.per_frame),
            "diagnostics": _jsonable(value.objective.diagnostics),
            "rejectionReasons": list(value.objective.rejection_reasons),
            "observability": _jsonable(value.objective.observability),
            "gradients": _jsonable(value.objective.gradients),
        },
        "semantic": _jsonable(value.semantic),
        "optimizerState": _jsonable(value.optimizer_state),
    }


def fingerprint_paths(paths: Sequence[Path], *, extra: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(extra.encode("utf-8"))
    for path in paths:
        resolved = Path(path).resolve()
        digest.update(str(resolved).encode("utf-8"))
        stat = resolved.stat()
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()
