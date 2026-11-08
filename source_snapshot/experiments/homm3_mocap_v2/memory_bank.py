"""Kinematic range memory for pose2rot. Not clip motion and not duplicated rest."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from paths import MAX_JOINTS, require_file
from preview import fk_world_positions
from topology import identity_rot6d


ALLOWED_MODES = frozenset({"flexion", "abduction", "twist"})
MAX_MEMORY_POSES = 32


def matrix_to_rot6d(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=np.float64)
    if values.shape != (3, 3) or not np.isfinite(values).all():
        raise ValueError(f"rotation matrix must be finite 3x3, got {values.shape}")
    return np.concatenate((values[:, 0], values[:, 1])).astype(np.float32)


def rot6d_to_matrix(rot6d: np.ndarray) -> np.ndarray:
    values = np.asarray(rot6d, dtype=np.float64).reshape(6)
    col0 = values[:3]
    col1 = values[3:]
    n0 = float(np.linalg.norm(col0))
    if n0 <= 1e-8:
        raise ValueError("rot6d first column is degenerate")
    col0 = col0 / n0
    col1 = col1 - col0 * float(np.dot(col0, col1))
    n1 = float(np.linalg.norm(col1))
    if n1 <= 1e-8:
        raise ValueError("rot6d second column is degenerate")
    col1 = col1 / n1
    col2 = np.cross(col0, col1)
    return np.stack((col0, col1, col2), axis=1)


def axis_angle_matrix(axis: np.ndarray, degrees: float) -> np.ndarray:
    vector = np.asarray(axis, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(vector))
    if length <= 1e-8:
        raise ValueError("rotation axis is degenerate")
    if not np.isfinite(degrees):
        raise ValueError("rotation angle must be finite")
    axis_u = vector / length
    theta = np.deg2rad(float(degrees))
    cosine = float(np.cos(theta))
    sine = float(np.sin(theta))
    x, y, z = axis_u
    skew = np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)), dtype=np.float64)
    return np.eye(3, dtype=np.float64) + sine * skew + (1.0 - cosine) * (skew @ skew)


def _children(parents: np.ndarray) -> list[list[int]]:
    out: list[list[int]] = [[] for _ in range(len(parents))]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            out[int(parent)].append(index)
    return out


def _name_index(readable_names: list[str]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for index, name in enumerate(readable_names):
        key = str(name)
        if key in lookup:
            raise ValueError(f"readable joint name collided: {key!r}")
        lookup[key] = index
    return lookup


def _bone_axis(offsets: np.ndarray, child_index: int) -> np.ndarray:
    axis = np.asarray(offsets[child_index], dtype=np.float64)
    length = float(np.linalg.norm(axis))
    if length <= 1e-8:
        raise ValueError(f"child joint {child_index} has a zero rest offset")
    return axis / length


def _mode_axis(bone: np.ndarray, mode: str) -> np.ndarray:
    if mode == "twist":
        return bone
    flexion = np.cross(bone, np.asarray((1.0, 0.0, 0.0)))
    if float(np.linalg.norm(flexion)) <= 1e-3:
        flexion = np.cross(bone, np.asarray((0.0, 0.0, 1.0)))
    length = float(np.linalg.norm(flexion))
    if length <= 1e-8:
        raise ValueError("could not build a flexion axis")
    flexion = flexion / length
    if mode == "flexion":
        return flexion
    abduction = np.cross(bone, flexion)
    ab_len = float(np.linalg.norm(abduction))
    if ab_len <= 1e-8:
        raise ValueError("could not build an abduction axis")
    return abduction / ab_len


def load_clip_recipe(path: Path, *, frame_count: int, mesh_sha256: str) -> dict[str, Any]:
    payload = json.loads(require_file(path, label="clip recipe").read_text(encoding="utf-8"))
    if payload.get("policy") != "weighted_memory_poses":
        raise ValueError("clip recipe policy must be weighted_memory_poses")
    if str(payload.get("meshSha256", "")).lower() != str(mesh_sha256).lower():
        raise ValueError("clip recipe is not pinned to this exact mesh")
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) != int(frame_count):
        raise ValueError(
            f"clip recipe has {0 if not isinstance(frames, list) else len(frames)} frames; "
            f"clip has {frame_count}"
        )
    for index, blend in enumerate(frames):
        if not isinstance(blend, dict) or not blend:
            raise ValueError(f"clip recipe frame {index} must be a non-empty pose blend")
        for key, value in blend.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"clip recipe frame {index} has a nameless pose")
            float(value)
    memory_recipe = payload.get("memoryRecipe")
    if not isinstance(memory_recipe, str) or not memory_recipe:
        raise ValueError("clip recipe is missing memoryRecipe")
    memory_path = Path(memory_recipe)
    if not memory_path.is_absolute():
        from paths import REPO

        memory_path = REPO / memory_path
    payload["memoryRecipePath"] = memory_path
    return payload


def load_memory_recipe(path: Path) -> dict[str, Any]:
    payload = json.loads(require_file(path, label="memory recipe").read_text(encoding="utf-8"))
    if payload.get("policy") != "kinematic_range_prior":
        raise ValueError("memory recipe policy must be kinematic_range_prior")
    poses = payload.get("poses")
    if not isinstance(poses, list) or len(poses) < 2:
        raise ValueError("memory recipe must list rest plus at least one articulated pose")
    if len(poses) > MAX_MEMORY_POSES:
        raise ValueError(f"memory recipe has {len(poses)} poses; cap is {MAX_MEMORY_POSES}")
    return payload


def build_kinematic_memory(
    *,
    readable_names: list[str],
    offsets: np.ndarray,
    parents: np.ndarray,
    recipe: dict[str, Any],
    names_mesh_sha256: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return padded [N,150,3] poses and [N,150,6] rotations. Slot 0 is rest."""
    recipe_sha = str(recipe.get("meshSha256", "")).lower()
    names_sha = str(names_mesh_sha256).lower()
    if not recipe_sha or recipe_sha != names_sha:
        raise ValueError("memory recipe is not pinned to this exact mesh")
    names = [str(name) for name in readable_names]
    lookup = _name_index(names)
    parent = np.asarray(parents, dtype=np.int64).reshape(-1)
    offset = np.asarray(offsets, dtype=np.float64)
    if offset.shape != (parent.size, 3):
        raise ValueError("offsets must match parents")
    children = _children(parent)
    poses = recipe["poses"]
    if str(poses[0].get("id")) != "rest" or list(poses[0].get("rotations") or ()) != []:
        raise ValueError("memory slot 0 must be id 'rest' with no rotations")
    seen_ids: set[str] = set()
    memory_pose = []
    memory_rot6d = []
    ids: list[str] = []
    identity = identity_rot6d(parent.size)
    rest_pose = None
    for pose in poses:
        pose_id = str(pose.get("id") or "").strip()
        if not pose_id:
            raise ValueError("memory pose is missing id")
        if pose_id in seen_ids:
            raise ValueError(f"memory pose id collided: {pose_id!r}")
        seen_ids.add(pose_id)
        rot6d = identity.copy()
        matrices = np.broadcast_to(np.eye(3), (parent.size, 3, 3)).copy()
        for item in pose.get("rotations") or ():
            joint_name = str(item.get("joint") or "")
            child_name = str(item.get("child") or "")
            mode = str(item.get("mode") or "")
            degrees = float(item.get("deg"))
            if joint_name not in lookup:
                raise ValueError(f"memory joint {joint_name!r} is not in the bind names")
            if child_name not in lookup:
                raise ValueError(f"memory child {child_name!r} is not in the bind names")
            if mode not in ALLOWED_MODES:
                raise ValueError(f"unknown rotation mode {mode!r}")
            if abs(degrees) < 1e-6:
                raise ValueError(f"{pose_id}: zero-degree rotations are not stored")
            joint_index = lookup[joint_name]
            child_index = lookup[child_name]
            if child_index not in children[joint_index]:
                raise ValueError(f"{child_name!r} is not a child of {joint_name!r}")
            axis = _mode_axis(_bone_axis(offset, child_index), mode)
            matrix = axis_angle_matrix(axis, degrees)
            matrices[joint_index] = matrix
            rot6d[joint_index] = matrix_to_rot6d(matrix)
        positions = fk_world_positions(
            local_matrices=matrices,
            rest_local_translation=offset,
            parents=parent,
            root_world=np.zeros(3),
        )
        if rest_pose is None:
            rest_pose = positions
            if float(np.max(np.abs(rot6d - identity))) > 1e-6:
                raise ValueError("rest memory is not identity rotation")
        else:
            moved = float(np.linalg.norm(positions - rest_pose))
            if moved < 1e-4:
                raise ValueError(f"{pose_id} does not move the skeleton")
        padded_pose = np.zeros((MAX_JOINTS, 3), dtype=np.float32)
        padded_rot = np.zeros((MAX_JOINTS, 6), dtype=np.float32)
        padded_pose[: parent.size] = positions.astype(np.float32)
        padded_rot[: parent.size] = rot6d.astype(np.float32)
        memory_pose.append(padded_pose)
        memory_rot6d.append(padded_rot)
        ids.append(pose_id)
    return np.stack(memory_pose), np.stack(memory_rot6d), ids


def source_local_from_pose_blend(
    *,
    rest_local_rotation: np.ndarray,
    rest_local_translation: np.ndarray,
    parents: np.ndarray,
    readable_names: list[str],
    recipe: dict[str, Any],
    blend: dict[str, float],
) -> np.ndarray:
    """Apply weighted memory poses as extra local rotations on the source bind."""
    lookup = _name_index([str(name) for name in readable_names])
    parent = np.asarray(parents, dtype=np.int64).reshape(-1)
    children = _children(parent)
    poses_by_id = {str(pose.get("id") or ""): pose for pose in recipe["poses"]}
    if "" in poses_by_id:
        raise ValueError("memory pose is missing id")
    extras: dict[tuple[int, int, str], float] = {}
    for pose_id, weight in blend.items():
        amount = float(weight)
        if not np.isfinite(amount) or amount == 0.0:
            raise ValueError(f"blend weight for {pose_id!r} must be finite and non-zero")
        if pose_id not in poses_by_id:
            raise ValueError(f"clip recipe pose {pose_id!r} is not in the memory recipe")
        if pose_id == "rest":
            raise ValueError("rest cannot be blended; omit a joint to leave it at bind")
        for item in poses_by_id[pose_id].get("rotations") or ():
            joint_index = lookup[str(item["joint"])]
            child_index = lookup[str(item["child"])]
            mode = str(item["mode"])
            if child_index not in children[joint_index]:
                raise ValueError(f"{item['child']!r} is not a child of {item['joint']!r}")
            key = (joint_index, child_index, mode)
            extras[key] = extras.get(key, 0.0) + amount * float(item["deg"])
    local = np.asarray(rest_local_rotation, dtype=np.float64).copy()
    offset = np.asarray(rest_local_translation, dtype=np.float64)
    composed: dict[int, np.ndarray] = {}
    for (joint_index, child_index, mode), degrees in extras.items():
        if abs(degrees) < 1e-6:
            continue
        axis = _mode_axis(_bone_axis(offset, child_index), mode)
        extra = axis_angle_matrix(axis, degrees)
        composed[joint_index] = extra @ composed.get(joint_index, np.eye(3, dtype=np.float64))
    for joint_index, extra in composed.items():
        local[joint_index] = local[joint_index] @ extra
    return local
