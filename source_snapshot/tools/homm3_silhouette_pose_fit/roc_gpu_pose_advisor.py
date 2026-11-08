"""CUDA proposal advisor for the original chromatic pose optimizer.

This module is deliberately not a scorer or renderer.  It keeps a compact,
resident FK/LBS representation of the selected Meshy GLB and uses projected
surface points plus a target signed-distance field to suggest search
directions.  Every suggestion is still evaluated by the original Blender
worker, chromatic/depth ledger, and semantic scorer before it can be accepted.

The separation is important: the advisor is allowed to be approximate, while
the result shown in the notebook and exported to Blender remains the proven
original path.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from gpu_pose_v2.rig import prepare_rig
from gpu_pose_v2.renderer import _axis_angle_matrix


def _normalize(value: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    return value / torch.clamp(torch.linalg.vector_norm(value, dim=-1, keepdim=True), min=eps)


def _quat_xyzw_matrix(value: Sequence[float]) -> torch.Tensor:
    x, y, z, w = (float(part) for part in value)
    norm = max(math.sqrt(x * x + y * y + z * z + w * w), 1e-8)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return torch.tensor(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=torch.float32,
    )


def _normalize_quaternion(value: Sequence[float]) -> tuple[float, float, float, float]:
    raw = np.asarray(tuple(float(part) for part in value), dtype=np.float64)
    if raw.shape != (4,):
        raise ValueError("advisor quaternions must contain four values")
    norm = float(np.linalg.norm(raw))
    if norm <= 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    raw /= norm
    return tuple(float(part) for part in raw)


def _pose_quaternion(value: Any) -> tuple[float, float, float, float]:
    """Decode the original notebook's wxyz pose entry without importing it."""
    if isinstance(value, (int, float)):
        angle = float(value) * 0.5
        return (math.cos(angle), 0.0, 0.0, math.sin(angle))
    if not isinstance(value, Mapping):
        return (1.0, 0.0, 0.0, 0.0)
    if "quaternion" in value:
        raw = tuple(float(part) for part in value["quaternion"])
        if str(value.get("quaternionOrder", "wxyz")).lower() == "xyzw":
            raw = (raw[3], raw[0], raw[1], raw[2])
        return _normalize_quaternion(raw)
    if "axis" in value:
        axis = value["axis"]
        if isinstance(axis, str):
            axis = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}.get(axis.lower())
        axis = np.asarray(axis, dtype=np.float64)
        axis /= max(float(np.linalg.norm(axis)), 1e-12)
        half = 0.5 * float(value.get("angle", value.get("rad", 0.0)))
        return _normalize_quaternion((math.cos(half), *(axis * math.sin(half))))
    x = float(value.get("x", 0.0))
    y = float(value.get("y", 0.0))
    z = float(value.get("z", 0.0))
    cx, cy, cz = (math.cos(part * 0.5) for part in (x, y, z))
    sx, sy, sz = (math.sin(part * 0.5) for part in (x, y, z))
    return _normalize_quaternion(
        (
            cx * cy * cz + sx * sy * sz,
            sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
        )
    )


def _quaternion_multiply(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = _normalize_quaternion(left)
    rw, rx, ry, rz = _normalize_quaternion(right)
    return _normalize_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def _quaternion_from_axis(axis: Sequence[float], angle_rad: float) -> tuple[float, float, float, float]:
    raw = np.asarray(tuple(float(part) for part in axis), dtype=np.float64)
    raw /= max(float(np.linalg.norm(raw)), 1e-12)
    half = 0.5 * float(angle_rad)
    return _normalize_quaternion((math.cos(half), *(raw * math.sin(half))))


def _quaternion_angle_deg(value: Sequence[float]) -> float:
    scalar = abs(max(-1.0, min(1.0, _normalize_quaternion(value)[0])))
    return math.degrees(2.0 * math.acos(scalar))


def _quaternion_to_rotvec(value: Sequence[float]) -> np.ndarray:
    w, x, y, z = _normalize_quaternion(value)
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    angle = 2.0 * math.acos(max(-1.0, min(1.0, w)))
    sine = math.sin(0.5 * angle)
    if abs(sine) <= 1e-7:
        return np.zeros(3, dtype=np.float32)
    return np.asarray((x, y, z), dtype=np.float32) / float(sine) * float(angle)


def _frame_number(path: Path) -> int | None:
    match = re.search(r"(?:frame[_-]?)?(\d+)(?:\D*)$", path.stem, re.IGNORECASE)
    return None if match is None else int(match.group(1))


def _unit_vector(value: Sequence[float], fallback: Sequence[float]) -> np.ndarray:
    raw = np.asarray(tuple(float(part) for part in value), dtype=np.float64)
    norm = float(np.linalg.norm(raw))
    if norm <= 1e-12:
        raw = np.asarray(tuple(float(part) for part in fallback), dtype=np.float64)
        norm = max(float(np.linalg.norm(raw)), 1e-12)
    return raw / norm


@dataclass(frozen=True)
class GpuPoseAdvisorConfig:
    device: str = "cuda"
    resolution: tuple[int, int] = (96, 86)
    max_points: int = 6000
    sdf_weight: float = 1.0
    centroid_weight: float = 0.35
    extent_weight: float = 0.25
    sdf_temperature_px: float = 1.5
    min_gradient_norm: float = 1e-5
    medium_sensitivity_ratio: float = 0.08
    high_sensitivity_ratio: float = 0.35
    orthogonal_count: int = 1
    root_hypothesis_count: int = 256
    root_keep: int = 8
    seed: int = 17


class GpuPoseAdvisor:
    """Resident differentiable point geometry used only to propose candidates."""

    def __init__(
        self,
        src_glb: str | Path,
        target_dir: str | Path,
        *,
        camera: Mapping[str, Any],
        root_context: Mapping[str, Any] | None,
        mesh_scale: float,
        config: GpuPoseAdvisorConfig,
        rigidization_report: str | Path | None = None,
        frame_indices: Sequence[int] = (),
    ) -> None:
        if not torch.cuda.is_available() or not str(config.device).lower().startswith("cuda"):
            raise RuntimeError(
                "GPU pose advisor requires CUDA; set gpu_pose_advisor_enabled=False for the original-only path"
            )
        self.config = config
        self.device = torch.device(config.device)
        self.width, self.height = (int(config.resolution[0]), int(config.resolution[1]))
        if self.width < 16 or self.height < 16:
            raise ValueError("GPU pose advisor resolution must be at least 16x16")
        self.rig = prepare_rig(
            src_glb,
            device=str(self.device),
            mesh_scale=float(mesh_scale),
            rigidization_report=rigidization_report,
        )
        self.node_names = tuple(str(name) for name in self.rig.node_names)
        self.node_by_name = {name: index for index, name in enumerate(self.node_names)}
        self.node_count = len(self.node_names)
        self.parents = self.rig.parents
        self.base_rotation = torch.stack(
            [
                _quat_xyzw_matrix(node.rotation).to(self.device)
                for node in self.rig.asset.nodes
            ],
            dim=0,
        )
        self.translation = torch.as_tensor(
            np.asarray([node.translation for node in self.rig.asset.nodes], dtype=np.float32),
            device=self.device,
        )
        self.scale = torch.as_tensor(
            np.asarray([node.scale for node in self.rig.asset.nodes], dtype=np.float32),
            device=self.device,
        )
        skeleton_mask = torch.zeros(self.node_count, dtype=torch.float32, device=self.device)
        if self.rig.skeleton_indices:
            skeleton_mask[torch.as_tensor(self.rig.skeleton_indices, dtype=torch.long, device=self.device)] = 1.0
        self.skeleton_mask = skeleton_mask
        self.camera_right = torch.as_tensor(camera["right"], dtype=torch.float32, device=self.device)
        self.camera_down = torch.as_tensor(
            camera.get("up", camera.get("down")), dtype=torch.float32, device=self.device
        )
        self.camera_forward = torch.as_tensor(camera["forward"], dtype=torch.float32, device=self.device)
        self.camera_px = float(camera["pxPerWorld"])
        self.camera_offset = torch.as_tensor(
            camera.get("screenOffset", camera.get("offset", (self.width / 2.0, self.height / 2.0))),
            dtype=torch.float32,
            device=self.device,
        )
        self.root_context = dict(root_context or {})
        self.translation_basis = {
            axis: torch.as_tensor(
                _unit_vector(
                    (self.root_context.get("basis") or {}).get(axis, (0.0, 0.0, 0.0)),
                    self.camera_forward.detach().cpu().numpy(),
                ),
                dtype=torch.float32,
                device=self.device,
            )
            for axis in ("forward", "lateral", "vertical")
        }
        rotation_context = self.root_context.get("rotation") or {}
        fallback_rotation_basis = {
            "camera_forward": self.camera_forward,
            "camera_right": self.camera_right,
            "camera_up": -self.camera_down,
        }
        self.rotation_basis = {
            axis: torch.as_tensor(
                _unit_vector(
                    (rotation_context.get("basisVectors") or {}).get(
                        axis,
                        fallback_rotation_basis[axis].detach().cpu().numpy(),
                    ),
                    fallback_rotation_basis[axis].detach().cpu().numpy(),
                ),
                dtype=torch.float32,
                device=self.device,
            )
            for axis in ("camera_forward", "camera_right", "camera_up")
        }
        pivot = rotation_context.get("pivot", (0.0, 0.0, 0.0))
        self.root_pivot = torch.as_tensor(tuple(float(part) for part in pivot), dtype=torch.float32, device=self.device)
        self.reference_length_world = float(self.root_context.get("referenceLengthWorld", 1.0))
        self.points = self._prepare_points()
        self.influence_by_node = self._prepare_influence()
        self.target_sdf, self.target_stats, self.frame_to_slot = self._prepare_targets(
            Path(target_dir), tuple(int(value) for value in frame_indices)
        )
        self._last_analysis_key: tuple[int, str] | None = None
        self._last_analysis: dict[str, Any] | None = None

    @classmethod
    def from_runtime(
        cls,
        src_glb: str | Path,
        target_dir: str | Path,
        *,
        camera: Mapping[str, Any],
        root_context: Mapping[str, Any] | None,
        mesh_scale: float,
        device: str = "cuda",
        resolution: Sequence[int] = (96, 86),
        max_points: int = 6000,
        sdf_weight: float = 1.0,
        centroid_weight: float = 0.35,
        extent_weight: float = 0.25,
        min_gradient_norm: float = 1e-5,
        medium_sensitivity_ratio: float = 0.08,
        high_sensitivity_ratio: float = 0.35,
        orthogonal_count: int = 1,
        root_hypothesis_count: int = 256,
        root_keep: int = 8,
        seed: int = 17,
        rigidization_report: str | Path | None = None,
        frame_indices: Sequence[int] = (),
    ) -> "GpuPoseAdvisor":
        config = GpuPoseAdvisorConfig(
            device=str(device),
            resolution=(int(resolution[0]), int(resolution[1])),
            max_points=int(max_points),
            sdf_weight=float(sdf_weight),
            centroid_weight=float(centroid_weight),
            extent_weight=float(extent_weight),
            min_gradient_norm=float(min_gradient_norm),
            medium_sensitivity_ratio=float(medium_sensitivity_ratio),
            high_sensitivity_ratio=float(high_sensitivity_ratio),
            orthogonal_count=int(orthogonal_count),
            root_hypothesis_count=int(root_hypothesis_count),
            root_keep=int(root_keep),
            seed=int(seed),
        )
        if config.max_points < 32 or config.root_hypothesis_count < 1 or config.root_keep < 1:
            raise ValueError("GPU pose advisor point and hypothesis budgets must be positive")
        if not 0.0 <= config.medium_sensitivity_ratio <= config.high_sensitivity_ratio <= 1.0:
            raise ValueError(
                "GPU pose advisor sensitivity ratios must satisfy "
                "0 <= medium <= high <= 1"
            )
        if config.orthogonal_count < 0 or config.orthogonal_count > 2:
            raise ValueError("GPU pose advisor orthogonal_count must be 0, 1, or 2")
        return cls(
            src_glb,
            target_dir,
            camera=camera,
            root_context=root_context,
            mesh_scale=mesh_scale,
            config=config,
            rigidization_report=rigidization_report,
            frame_indices=frame_indices,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "device": str(self.device),
            "resolution": [self.width, self.height],
            "pointCount": int(self.points.shape[0]),
            "nodeCount": int(self.node_count),
            "frameCount": int(self.target_sdf.shape[0]),
            "rootHypothesisCount": int(self.config.root_hypothesis_count),
            "rootKeep": int(self.config.root_keep),
            "mediumSensitivityRatio": float(self.config.medium_sensitivity_ratio),
            "highSensitivityRatio": float(self.config.high_sensitivity_ratio),
            "objective": "projected surface points + target SDF + centroid + extent",
            "authority": "original Blender chromatic/depth/DINO/SigLIP scorer",
        }

    def _prepare_points(self):
        total = sum(int(primitive.positions.shape[0]) for primitive in self.rig.primitives)
        self._sample_stride = max(1, int(math.ceil(total / max(int(self.config.max_points), 1))))
        self._sample_indices_by_primitive = tuple(
            torch.arange(
                0,
                int(primitive.positions.shape[0]),
                self._sample_stride,
                dtype=torch.long,
                device=self.device,
            )
            for primitive in self.rig.primitives
        )
        positions: list[torch.Tensor] = []
        for primitive, indices in zip(self.rig.primitives, self._sample_indices_by_primitive):
            if indices.numel() > 0:
                positions.append(primitive.positions.index_select(0, indices))
        return (
            torch.cat(positions, dim=0)
            if positions
            else torch.zeros((0, 3), dtype=torch.float32, device=self.device)
        )

    def _prepare_influence(self) -> torch.Tensor:
        influence = torch.zeros(self.node_count, dtype=torch.float32, device=self.device)
        for primitive in self.rig.primitives:
            if primitive.joints is None or primitive.weights is None or primitive.skin is None:
                continue
            skin = self.rig.asset.skins[int(primitive.skin)]
            joints = torch.as_tensor(skin.joints, dtype=torch.long, device=self.device)
            selected = primitive.joints
            weights = primitive.weights / torch.clamp(primitive.weights.sum(dim=1, keepdim=True), min=1e-8)
            for slot in range(4):
                valid = weights[:, slot] > 1e-4
                if valid.any():
                    influence.index_add_(0, joints[selected[valid, slot]], weights[valid, slot])
        return influence / max(float(influence.sum().item()), 1e-8)

    def _prepare_targets(self, directory: Path, requested: tuple[int, ...]):
        if not directory.is_dir():
            raise FileNotFoundError(f"GPU pose advisor target directory is missing: {directory}")
        paths = sorted(
            (path for path in directory.glob("*.png") if _frame_number(path) is not None),
            key=lambda path: (_frame_number(path) or 0, path.name.lower()),
        )
        by_number = {_frame_number(path): path for path in paths}
        frame_indices = requested or tuple(int(value) for value in by_number if value is not None)
        resolved = []
        for frame in frame_indices:
            path = by_number.get(int(frame))
            if path is None:
                raise FileNotFoundError(f"GPU pose advisor target frame {frame} is missing under {directory}")
            resolved.append(path)
        sdf_values = []
        stats = {}
        for frame, path in zip(frame_indices, resolved):
            with Image.open(path) as image:
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
            alpha = rgba[..., 3]
            if int(alpha.max()) <= 0:
                raise ValueError(f"GPU pose advisor target has no alpha foreground: {path}")
            source_mask = alpha >= 8
            resized = Image.fromarray((source_mask.astype(np.uint8) * 255), mode="L").resize(
                (self.width, self.height), Image.Resampling.NEAREST
            )
            mask = np.asarray(resized, dtype=np.uint8) > 0
            if not mask.any():
                raise ValueError(f"GPU pose advisor target became empty at {self.width}x{self.height}: {path}")
            try:
                from scipy.ndimage import distance_transform_edt
            except Exception as exc:
                raise RuntimeError("GPU pose advisor requires scipy for target SDF preparation") from exc
            sdf_values.append(
                distance_transform_edt(~mask).astype(np.float32)
                - distance_transform_edt(mask).astype(np.float32)
            )
            ys, xs = np.where(mask)
            stats[int(frame)] = {
                "centroid": (float(xs.mean()), float(ys.mean())),
                "extent": (float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1)),
                "foreground": float(mask.mean()),
            }
        return (
            torch.as_tensor(np.stack(sdf_values), dtype=torch.float32, device=self.device),
            stats,
            {int(frame): index for index, frame in enumerate(frame_indices)},
        )

    def _forward_kinematics(self, bone_rotation: torch.Tensor) -> torch.Tensor:
        batch = int(bone_rotation.shape[0])
        masked = bone_rotation * self.skeleton_mask.view(1, self.node_count, 1)
        local_rotation = torch.matmul(self.base_rotation.unsqueeze(0), _axis_angle_matrix(masked))
        local = torch.zeros((batch, self.node_count, 4, 4), dtype=torch.float32, device=self.device)
        local[..., 3, 3] = 1.0
        local[..., :3, :3] = local_rotation * self.scale.unsqueeze(0).unsqueeze(-2)
        local[..., :3, 3] = self.translation.unsqueeze(0)
        world: list[torch.Tensor | None] = [None] * self.node_count
        visiting: set[int] = set()

        def visit(index: int) -> torch.Tensor:
            if world[index] is not None:
                return world[index]  # type: ignore[return-value]
            if index in visiting:
                raise ValueError("GLB node hierarchy contains a cycle")
            visiting.add(index)
            parent = self.parents[index]
            current = local[:, index]
            world[index] = current if parent is None else torch.matmul(visit(int(parent)), current)
            visiting.remove(index)
            return world[index]  # type: ignore[return-value]

        return torch.stack([visit(index) for index in range(self.node_count)], dim=1)

    def _points_from_worlds(self, worlds: torch.Tensor) -> torch.Tensor:
        # Primitive boundaries are sampled once, but skinning is still linear
        # blend skinning, so the proposal geometry follows Meshy's rig rather
        # than a Gaussian or bone-only proxy.
        values: list[torch.Tensor] = []
        cursor = 0
        for primitive, source_indices in zip(self.rig.primitives, self._sample_indices_by_primitive):
            count = int(source_indices.numel())
            if count <= 0:
                continue
            positions = self.points[cursor : cursor + count]
            cursor += count
            if primitive.skin is None or primitive.joints is None or primitive.weights is None:
                values.append(torch.einsum("bkl,nl->bnk", worlds[:, primitive.node], positions)[..., :3])
                continue
            skin = self.rig.asset.skins[int(primitive.skin)]
            joints = torch.as_tensor(skin.joints, dtype=torch.long, device=self.device)
            inverse_bind = torch.as_tensor(skin.inverse_bind, dtype=torch.float32, device=self.device)
            primitive_joints = primitive.joints.index_select(0, source_indices)
            primitive_weights = primitive.weights.index_select(0, source_indices)
            joint_matrices = torch.matmul(worlds[:, joints], inverse_bind.unsqueeze(0))
            transformed = torch.einsum("bjkl,nl->bjnk", joint_matrices, positions)
            gather_index = primitive_joints.T.unsqueeze(0).unsqueeze(-1).expand(worlds.shape[0], 4, -1, 4)
            selected = torch.gather(transformed, 1, gather_index)
            weights = primitive_weights / torch.clamp(primitive_weights.sum(dim=1, keepdim=True), min=1e-8)
            skinned = (selected * weights.T.unsqueeze(0).unsqueeze(-1)).sum(dim=1)
            values.append(torch.einsum("bkl,bnl->bnk", worlds[:, primitive.node], skinned)[..., :3])
        if not values:
            return torch.zeros((int(worlds.shape[0]), 0, 3), dtype=torch.float32, device=self.device)
        return torch.cat(values, dim=1) * float(self.rig.mesh_scale)

    def _rotations_from_pose(self, pose: Mapping[str, Any]) -> torch.Tensor:
        result = np.zeros((self.node_count, 3), dtype=np.float32)
        for name, index in self.node_by_name.items():
            if name in pose:
                result[index] = _quaternion_to_rotvec(pose[name])
        return torch.as_tensor(result, dtype=torch.float32, device=self.device)

    def _root_values(self, pose: Mapping[str, Any]) -> tuple[torch.Tensor, torch.Tensor]:
        translation = pose.get("__motion_root__")
        rotation = pose.get("__motion_root_rotation__")
        trans = torch.as_tensor(
            [float(translation.get(axis, 0.0)) if isinstance(translation, Mapping) else 0.0 for axis in ("forward", "lateral", "vertical")],
            dtype=torch.float32,
            device=self.device,
        )
        rot = torch.as_tensor(
            [float(rotation.get(axis, 0.0)) if isinstance(rotation, Mapping) else 0.0 for axis in ("camera_forward", "camera_right", "camera_up")],
            dtype=torch.float32,
            device=self.device,
        )
        return trans, rot

    def _apply_root(self, points: torch.Tensor, translation: torch.Tensor, rotation_deg: torch.Tensor) -> torch.Tensor:
        if translation.ndim == 1:
            translation = translation.unsqueeze(0)
        if rotation_deg.ndim == 1:
            rotation_deg = rotation_deg.unsqueeze(0)
        batch = int(points.shape[0])
        rotation_matrix = torch.eye(3, dtype=torch.float32, device=self.device).unsqueeze(0).expand(batch, -1, -1).clone()
        for index, axis in enumerate(("camera_forward", "camera_right", "camera_up")):
            axis_vector = self.rotation_basis[axis].view(1, 3).expand(batch, -1)
            increment = _axis_angle_matrix(axis_vector * torch.deg2rad(rotation_deg[:, index:index + 1]))
            rotation_matrix = torch.matmul(increment, rotation_matrix)
        displacement = torch.zeros((batch, 3), dtype=torch.float32, device=self.device)
        for index, axis in enumerate(("forward", "lateral", "vertical")):
            displacement = displacement + self.translation_basis[axis].view(1, 3) * translation[:, index:index + 1]
        displacement = displacement * float(self.reference_length_world)
        pivot = self.root_pivot.view(1, 1, 3)
        return torch.matmul(points - pivot, rotation_matrix.transpose(-1, -2)) + pivot + displacement.view(batch, 1, 3)

    def _project(self, points: torch.Tensor) -> torch.Tensor:
        x = torch.einsum("bnk,k->bn", points, self.camera_right) * self.camera_px + self.camera_offset[0]
        y = torch.einsum("bnk,k->bn", points, self.camera_down) * self.camera_px + self.camera_offset[1]
        return torch.stack((x, y), dim=-1)

    def _points_for_pose(self, pose: Mapping[str, Any], bone_rotation: torch.Tensor | None = None) -> torch.Tensor:
        rotations = self._rotations_from_pose(pose) if bone_rotation is None else bone_rotation
        if rotations.ndim == 2:
            rotations = rotations.unsqueeze(0)
        points = self._points_from_worlds(self._forward_kinematics(rotations))
        translation, rotation = self._root_values(pose)
        return self._apply_root(points, translation, rotation)

    def _loss(self, projected: torch.Tensor, frame_index: int) -> torch.Tensor:
        slot = self.frame_to_slot.get(int(frame_index))
        if slot is None:
            raise KeyError(f"GPU pose advisor has no target for frame {frame_index}")
        sdf = self.target_sdf[slot].view(1, 1, self.height, self.width).expand(projected.shape[0], -1, -1, -1)
        grid = torch.stack(
            (
                projected[..., 0] / max(self.width - 1, 1) * 2.0 - 1.0,
                projected[..., 1] / max(self.height - 1, 1) * 2.0 - 1.0,
            ),
            dim=-1,
        ).view(projected.shape[0], 1, -1, 2)
        sampled_sdf = F.grid_sample(sdf, grid, mode="bilinear", padding_mode="border", align_corners=True).view(projected.shape[0], -1)
        temperature = max(float(self.config.sdf_temperature_px), 0.25)
        sdf_loss = F.softplus(sampled_sdf / temperature).mean(dim=1) * temperature / max(float(max(self.width, self.height)), 1.0)
        target = self.target_stats[int(frame_index)]
        centroid = projected.mean(dim=1)
        centroid_target = projected.new_tensor(target["centroid"])
        centroid_loss = torch.linalg.vector_norm(centroid - centroid_target.view(1, 2), dim=-1) / max(float(max(self.width, self.height)), 1.0)
        extent = projected.amax(dim=1) - projected.amin(dim=1)
        extent_target = projected.new_tensor(target["extent"])
        extent_loss = torch.abs(extent - extent_target.view(1, 2)).mean(dim=-1) / max(float(max(self.width, self.height)), 1.0)
        return (
            float(self.config.sdf_weight) * sdf_loss
            + float(self.config.centroid_weight) * centroid_loss
            + float(self.config.extent_weight) * extent_loss
        )

    def _pose_signature(self, pose: Mapping[str, Any]) -> str:
        parts = []
        for name in self.node_names:
            parts.append(tuple(round(float(value), 6) for value in _quaternion_to_rotvec(_pose_quaternion(pose.get(name, {})))))
        for key in ("__motion_root__", "__motion_root_rotation__"):
            value = pose.get(key, {})
            parts.append(tuple(sorted((str(k), round(float(v), 6)) for k, v in value.items())) if isinstance(value, Mapping) else ())
        return repr(parts)

    def analyze(self, frame_index: int, pose: Mapping[str, Any]) -> dict[str, Any]:
        signature = (int(frame_index), self._pose_signature(pose))
        if signature == self._last_analysis_key and self._last_analysis is not None:
            return self._last_analysis
        rotations = self._rotations_from_pose(pose).detach().clone().requires_grad_(True)
        with torch.enable_grad():
            points = self._points_for_pose(pose, rotations)
            projected = self._project(points)
            loss = self._loss(projected, int(frame_index))[0]
            gradients = torch.autograd.grad(loss, rotations, allow_unused=False)[0]
        rows = {}
        raw_sensitivities = {
            name: float(
                torch.linalg.vector_norm(gradients[index]).item()
                * float(self.influence_by_node[index].item())
            )
            for name, index in self.node_by_name.items()
        }
        max_sensitivity = max(raw_sensitivities.values(), default=0.0)
        for name, index in self.node_by_name.items():
            gradient = gradients[index].detach()
            norm = float(torch.linalg.vector_norm(gradient).item())
            direction = (-gradient / max(norm, 1e-12)).detach().cpu().numpy().astype(np.float64)
            projected_sensitivity = raw_sensitivities[name]
            relative_sensitivity = projected_sensitivity / max(max_sensitivity, 1e-12)
            if relative_sensitivity >= float(self.config.high_sensitivity_ratio):
                sensitivity_class = "high"
            elif relative_sensitivity >= float(self.config.medium_sensitivity_ratio):
                sensitivity_class = "medium"
            else:
                sensitivity_class = "low"
            rows[name] = {
                "gradient": [float(value) for value in gradient.cpu().numpy()],
                "direction": [float(value) for value in direction],
                "gradientNorm": norm,
                "projectedSensitivity": projected_sensitivity,
                "relativeProjectedSensitivity": float(relative_sensitivity),
                "sensitivityClass": sensitivity_class,
                "influence": float(self.influence_by_node[index].item()),
                "wellConditioned": bool(norm >= float(self.config.min_gradient_norm)),
            }
        result = {
            "frame": int(frame_index),
            "loss": float(loss.detach().item()),
            "maxProjectedSensitivity": float(max_sensitivity),
            "perBone": rows,
            "objective": "target_sdf_plus_centroid_extent",
        }
        self._last_analysis_key = signature
        self._last_analysis = result
        return result

    def rotation_proposals(
        self,
        frame_index: int,
        pose: Mapping[str, Any],
        bone: str,
        current_quaternion: Sequence[float],
        *,
        step_deg: float,
        max_abs_deg: float,
        bone_vector: Sequence[float],
        twist_policy: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        analysis = self.analyze(frame_index, pose)
        row = analysis["perBone"].get(str(bone))
        if not row or not row.get("wellConditioned"):
            return [], {"used": False, "reason": "weak_or_unobserved_gradient", "analysis": row}
        sensitivity_class = str(row.get("sensitivityClass", "medium"))
        if sensitivity_class == "low":
            return [], {
                "used": False,
                "mode": "skip_coarse",
                "reason": "low_projected_sensitivity",
                "analysis": row,
                "gradientNorm": float(row["gradientNorm"]),
                "projectedSensitivity": float(row["projectedSensitivity"]),
            }
        direction = np.asarray(row["direction"], dtype=np.float64)
        shaft = _unit_vector(bone_vector, (0.0, 1.0, 0.0))
        if str(twist_policy).lower() != "include":
            direction = direction - shaft * float(np.dot(direction, shaft))
        direction = _unit_vector(direction, (1.0, 0.0, 0.0))
        axes = [direction, -direction]
        references = (np.asarray((1.0, 0.0, 0.0)), np.asarray((0.0, 1.0, 0.0)), np.asarray((0.0, 0.0, 1.0)))
        reference = min(references, key=lambda value: abs(float(np.dot(value, direction))))
        orthogonal_a = _unit_vector(np.cross(direction, reference), (0.0, 0.0, 1.0))
        orthogonal_b = _unit_vector(np.cross(direction, orthogonal_a), (0.0, 1.0, 0.0))
        orthogonal_count = int(self.config.orthogonal_count) if sensitivity_class == "high" else 0
        if orthogonal_count >= 1:
            axes.extend((orthogonal_a, -orthogonal_a))
        if orthogonal_count >= 2:
            axes.extend((orthogonal_b, -orthogonal_b))
        angle = min(abs(float(step_deg)), abs(float(max_abs_deg)))
        proposals = []
        seen = set()
        current = _normalize_quaternion(current_quaternion)
        for index, axis in enumerate(axes):
            axis = _unit_vector(axis, (1.0, 0.0, 0.0))
            candidate = _quaternion_multiply(_quaternion_from_axis(axis, math.radians(angle)), current)
            if _quaternion_angle_deg(candidate) > abs(float(max_abs_deg)) + 1e-6:
                continue
            key = tuple(round(float(value), 6) for value in candidate)
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "quaternion": candidate,
                    "axis": [float(value) for value in axis],
                    "angleDeg": float(angle),
                    "kind": "advisor_gradient" if index == 0 else "advisor_escape",
                    "direction": int(index),
                    "twistPolicy": "include" if str(twist_policy).lower() == "include" else "exclude",
                }
            )
        return proposals, {
            "used": bool(proposals),
            "reason": "gradient_direction",
            "gradientNorm": float(row["gradientNorm"]),
            "projectedSensitivity": float(row["projectedSensitivity"]),
            "relativeProjectedSensitivity": float(row.get("relativeProjectedSensitivity", 0.0)),
            "sensitivityClass": sensitivity_class,
            "proposalCount": len(proposals),
            "analysisLoss": float(analysis["loss"]),
        }

    def _cheap_root_candidates(
        self,
        frame_index: int,
        pose: Mapping[str, Any],
        *,
        translation_limits: Mapping[str, float],
        translation_axes: Sequence[str],
        rotation_limit_deg: float,
        rotation_axes: Sequence[str],
        count: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        rotations = self._rotations_from_pose(pose).detach()
        base_points = self._points_from_worlds(self._forward_kinematics(rotations.unsqueeze(0))).detach()
        engine = torch.quasirandom.SobolEngine(dimension=6, scramble=True, seed=int(self.config.seed) + int(frame_index))
        samples = engine.draw(max(1, int(count))).to(self.device, dtype=torch.float32) * 2.0 - 1.0
        current_translation, current_rotation = self._root_values(pose)
        samples[0, :3] = current_translation
        samples[0, 3:] = current_rotation / max(abs(float(rotation_limit_deg)), 1e-6)
        if samples.shape[0] > 1:
            samples[1] = 0.0
        translation = torch.zeros((samples.shape[0], 3), dtype=torch.float32, device=self.device)
        for index, axis in enumerate(("forward", "lateral", "vertical")):
            if axis in translation_axes:
                translation[:, index] = samples[:, index] * float(translation_limits.get(axis, 0.0))
        rotation = torch.zeros((samples.shape[0], 3), dtype=torch.float32, device=self.device)
        for index, axis in enumerate(("camera_forward", "camera_right", "camera_up")):
            if axis in rotation_axes:
                rotation[:, index] = samples[:, index + 3] * float(rotation_limit_deg)
        projected = self._project(self._apply_root(base_points.expand(samples.shape[0], -1, -1), translation, rotation))
        losses = self._loss(projected, int(frame_index)).detach()
        return translation, rotation, losses

    def root_hypotheses(
        self,
        frame_index: int,
        pose: Mapping[str, Any],
        *,
        translation_limits: Mapping[str, float],
        translation_axes: Sequence[str],
        rotation_limit_deg: float,
        rotation_axes: Sequence[str],
    ) -> list[dict[str, Any]]:
        count = max(1, int(self.config.root_hypothesis_count))
        translation, rotation, losses = self._cheap_root_candidates(
            frame_index,
            pose,
            translation_limits=translation_limits,
            translation_axes=translation_axes,
            rotation_limit_deg=rotation_limit_deg,
            rotation_axes=rotation_axes,
            count=count,
        )
        ranked = torch.argsort(losses).tolist()
        selected: list[int] = []
        pool = ranked[: max(int(self.config.root_keep) * 8, int(self.config.root_keep))]
        normalized = torch.cat(
            (
                translation / max(float(max(translation_limits.values(), default=1.0)), 1e-6),
                rotation / max(abs(float(rotation_limit_deg)), 1e-6),
            ),
            dim=1,
        )
        while pool and len(selected) < int(self.config.root_keep):
            if not selected:
                selected.append(int(pool.pop(0)))
                continue
            distances = []
            for candidate in pool:
                distance = torch.linalg.vector_norm(normalized[candidate] - normalized[selected], dim=1).min()
                distances.append((float(distance.item()), int(candidate)))
            _, chosen = max(distances, key=lambda item: (item[0], -float(losses[item[1]].item())))
            selected.append(chosen)
            pool.remove(chosen)
        result = []
        for index in selected:
            result.append(
                {
                    "translation": {
                        axis: float(translation[index, slot].item())
                        for slot, axis in enumerate(("forward", "lateral", "vertical"))
                    },
                    "rotation": {
                        axis: float(rotation[index, slot].item())
                        for slot, axis in enumerate(("camera_forward", "camera_right", "camera_up"))
                    },
                    "cheapLoss": float(losses[index].item()),
                }
            )
        return result


__all__ = ["GpuPoseAdvisor", "GpuPoseAdvisorConfig"]
