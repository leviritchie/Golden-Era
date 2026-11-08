"""Model-frame axes and sagittal mirroring for paired joints.

Bone-local x/y/z are rest-pose frames. Copying the same Euler onto a
catalog pair is not a left/right mirror unless those rest frames are
already mirrored. Convert through the model's sagittal frame instead.

Proof: CPU tests. Not OE battle.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from sprite_anatomy import anatomy_landmark_bone, anatomy_ventral_bind_axis
from sprite_pose_feasibility import require_unit3, rotation_matrix_deg

MODEL_AXES = ("lateral", "spine", "ventral")
SAGITTAL_MODEL_AXES = ("spine", "ventral")
ANATOMICAL_AXES = ("raise", "sweep", "twist")


def orthonormal_rotation(matrix: np.ndarray) -> np.ndarray:
    raw = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    u_mat, _, vt_mat = np.linalg.svd(raw)
    rot = u_mat @ vt_mat
    if float(np.linalg.det(rot)) < 0.0:
        u_mat[:, -1] *= -1.0
        rot = u_mat @ vt_mat
    return rot


def axis_angle_deg_to_matrix(xyz_deg: np.ndarray) -> np.ndarray:
    vec = np.asarray(xyz_deg, dtype=np.float64).reshape(3)
    angle = float(np.linalg.norm(vec))
    if angle <= 1e-12:
        return np.eye(3, dtype=np.float64)
    return rotation_matrix_deg(vec, angle)


def rotation_matrix_to_axis_angle_deg(matrix: np.ndarray) -> np.ndarray:
    rot = orthonormal_rotation(matrix)
    cosine = float(np.clip((np.trace(rot) - 1.0) * 0.5, -1.0, 1.0))
    angle = math.acos(cosine)
    if angle <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    if math.pi - angle <= 1e-6:
        diag = np.diag(rot)
        axis = np.sqrt(np.maximum(0.0, (diag + 1.0) * 0.5))
        if rot[0, 1] < 0.0:
            axis[1] = -axis[1]
        if rot[0, 2] < 0.0:
            axis[2] = -axis[2]
        if rot[1, 2] < 0.0 and axis[1] * axis[2] > 0.0:
            axis[2] = -axis[2]
        length = float(np.linalg.norm(axis))
        if length <= 1e-12:
            raise ValueError("180-degree rotation has no recoverable axis")
        return (axis / length) * 180.0
    skew = np.asarray(
        (rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]),
        dtype=np.float64,
    )
    axis = skew / (2.0 * math.sin(angle))
    return axis * math.degrees(angle)


def model_bind_frame(
    catalog: Mapping[str, Any],
    origins: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Orthonormal model frame: lateral, spine, ventral.

    Spine is headTip − tailTip in the rest GLB. Lateral is spine × catalog
    ventral. This is the same construction T-pose uses, so leftover search
    and editor symmetry share one midline.
    """
    ventral = anatomy_ventral_bind_axis(catalog)
    tail_name = anatomy_landmark_bone(catalog, "tailTip")
    head_name = anatomy_landmark_bone(catalog, "headTip")
    missing = [name for name in (tail_name, head_name) if name not in origins]
    if missing:
        raise ValueError(f"model bind frame missing landmark origins {missing}")
    tail = np.asarray(origins[tail_name], dtype=np.float64).reshape(3)
    head = np.asarray(origins[head_name], dtype=np.float64).reshape(3)
    spine = require_unit3(head - tail, "model spine (headTip - tailTip)")
    lateral = require_unit3(np.cross(spine, ventral), "model lateral (spine × ventral)")
    ventral_o = require_unit3(np.cross(lateral, spine), "model ventral")
    return {"lateral": lateral, "spine": spine, "ventral": ventral_o}


def bone_distal_directions(
    catalog: Mapping[str, Any],
    origins: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Parent-to-child vectors along each catalog group chain."""
    from sprite_anatomy import (
        anatomy_bilateral_pairs,
        anatomy_central_search_groups,
        anatomy_group_bones,
    )

    groups: list[str] = []
    for left, right in anatomy_bilateral_pairs(catalog):
        groups.append(str(left))
        groups.append(str(right))
    groups.extend(str(name) for name in anatomy_central_search_groups(catalog))
    directions: dict[str, np.ndarray] = {}
    for group in groups:
        bones = anatomy_group_bones(catalog, group)
        for index, bone in enumerate(bones):
            name = str(bone)
            if name not in origins:
                raise ValueError(f"distal direction missing origin {name}")
            here = np.asarray(origins[name], dtype=np.float64).reshape(3)
            if index + 1 < len(bones):
                child = str(bones[index + 1])
                if child not in origins:
                    raise ValueError(f"distal direction missing origin {child}")
                there = np.asarray(origins[child], dtype=np.float64).reshape(3)
                directions[name] = there - here
            elif index > 0:
                parent = str(bones[index - 1])
                prev = np.asarray(origins[parent], dtype=np.float64).reshape(3)
                directions[name] = here - prev
            else:
                raise ValueError(f"group {group} has one bone; cannot distal-aim")
    return directions


def bone_anatomical_axes(
    bone_dir_world: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Per-bone raise/sweep/twist. +raise moves this bone toward dorsal.

    Do not sagittal-sandwich the rotation tensor. This smartrig already
    mirrors limb directions at rest; conjugating with M R M inverts flap.
    """
    bone = require_unit3(bone_dir_world, "bone distal direction")
    ventral = require_unit3(model_frame["ventral"], "ventral")
    spine = require_unit3(model_frame["spine"], "spine")
    dorsal = -ventral
    raise_axis = np.cross(bone, dorsal)
    if float(np.linalg.norm(raise_axis)) <= 1e-8:
        raise_axis = np.cross(bone, spine)
    raise_axis = require_unit3(raise_axis, "raise axis")
    if float(np.dot(np.cross(raise_axis, bone), dorsal)) < 0.0:
        raise_axis = -raise_axis
    twist = bone
    sweep = np.cross(raise_axis, twist)
    sweep = require_unit3(sweep, "sweep axis")
    if float(np.dot(np.cross(sweep, bone), spine)) < 0.0:
        sweep = -sweep
    return {"raise": raise_axis, "sweep": sweep, "twist": twist}


def world_axis_angle_from_local(delta_xyz: np.ndarray, rest_rotation: np.ndarray) -> np.ndarray:
    rest = orthonormal_rotation(rest_rotation)
    return rest @ np.asarray(delta_xyz, dtype=np.float64).reshape(3)


def local_from_world_axis_angle(world_xyz: np.ndarray, rest_rotation: np.ndarray) -> np.ndarray:
    rest = orthonormal_rotation(rest_rotation)
    return rest.T @ np.asarray(world_xyz, dtype=np.float64).reshape(3)


def anatomical_components(
    delta_xyz: np.ndarray,
    rest_rotation: np.ndarray,
    bone_dir_world: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
) -> np.ndarray:
    axes = bone_anatomical_axes(bone_dir_world, model_frame)
    world = world_axis_angle_from_local(delta_xyz, rest_rotation)
    return np.asarray(
        (
            float(np.dot(world, axes["raise"])),
            float(np.dot(world, axes["sweep"])),
            float(np.dot(world, axes["twist"])),
        ),
        dtype=np.float64,
    )


def local_delta_from_anatomical(
    components: np.ndarray,
    rest_rotation: np.ndarray,
    bone_dir_world: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
) -> np.ndarray:
    axes = bone_anatomical_axes(bone_dir_world, model_frame)
    combo = np.asarray(components, dtype=np.float64).reshape(3)
    world = axes["raise"] * combo[0] + axes["sweep"] * combo[1] + axes["twist"] * combo[2]
    return local_from_world_axis_angle(world, rest_rotation)


def copy_anatomical_delta(
    delta_a: np.ndarray,
    rest_a: np.ndarray,
    rest_b: np.ndarray,
    dir_a: np.ndarray,
    dir_b: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
) -> np.ndarray:
    """Copy A's pose onto B as the same raise/sweep/twist, not the same local xyz."""
    combo = anatomical_components(delta_a, rest_a, dir_a, model_frame)
    return local_delta_from_anatomical(combo, rest_b, dir_b, model_frame)


def paired_anatomical_local_adds(
    rest_a: np.ndarray,
    rest_b: np.ndarray,
    dir_a: np.ndarray,
    dir_b: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
    axis: str,
    delta_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    name = str(axis)
    if name not in ANATOMICAL_AXES:
        raise ValueError(f"anatomical axis must be one of {ANATOMICAL_AXES}, got {name!r}")
    extra = float(delta_deg)
    if not math.isfinite(extra) or extra == 0.0:
        raise ValueError("delta_deg must be a non-zero finite number")
    axes_a = bone_anatomical_axes(dir_a, model_frame)
    axes_b = bone_anatomical_axes(dir_b, model_frame)
    add_a = local_from_world_axis_angle(axes_a[name] * extra, rest_a)
    add_b = local_from_world_axis_angle(axes_b[name] * extra, rest_b)
    return add_a, add_b


def model_combo_local_add(
    rest_rotation: np.ndarray,
    model_frame: Mapping[str, np.ndarray],
    combo: tuple[float, float, float],
) -> np.ndarray:
    """Local axis-angle degrees for a (lateral, spine, ventral) combo."""
    if len(combo) != 3:
        raise ValueError("model combo must be (lateral, spine, ventral) degrees")
    rest = orthonormal_rotation(rest_rotation)
    world = (
        np.asarray(model_frame["lateral"], dtype=np.float64).reshape(3) * float(combo[0])
        + np.asarray(model_frame["spine"], dtype=np.float64).reshape(3) * float(combo[1])
        + np.asarray(model_frame["ventral"], dtype=np.float64).reshape(3) * float(combo[2])
    )
    return rest.T @ world


def experiment_rest_worlds(experiment) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Bind rest-world rotations and origins from a loaded GPU experiment."""
    from roc_gpu_cascade_experiment import _gpu_world_matrices

    asset = getattr(experiment, "asset", None)
    names = getattr(experiment, "node_names", None)
    if asset is None or names is None:
        raise ValueError("experiment_rest_worlds needs experiment.asset and node_names")
    worlds = _gpu_world_matrices(asset, None)
    rotations: dict[str, np.ndarray] = {}
    origins: dict[str, np.ndarray] = {}
    for index, name in enumerate(names):
        matrix = np.asarray(worlds[int(index)], dtype=np.float64)
        rotations[str(name)] = orthonormal_rotation(matrix[:3, :3])
        origins[str(name)] = matrix[:3, 3].copy()
    if not rotations:
        raise ValueError("experiment rest worlds are empty")
    return rotations, origins
