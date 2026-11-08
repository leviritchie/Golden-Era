"""Analytic screen-plane direction correction for a leaf attachment."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def _angle(v):
    return np.arctan2(float(v[1]), float(v[0]))


def _wrap(v):
    return (v + np.pi) % (2 * np.pi) - np.pi


def correct(local_rotation, joint_world, parents, joint_index, local_axis, camera,
            source_directions, *, anchor_frame=0, max_correction_degrees=150):
    local = np.asarray(local_rotation, dtype=np.float64)
    worlds = np.asarray(joint_world, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    axis = np.asarray(local_axis, dtype=np.float64)
    source = np.asarray(source_directions, dtype=np.float64)
    if local.ndim != 4 or local.shape[-2:] != (3, 3) or worlds.shape != (local.shape[0], local.shape[1], 4, 4):
        raise ValueError("local_rotation and joint_world dimensions are invalid")
    frames, joints = local.shape[:2]
    if frames == 0 or joints == 0:
        raise ValueError("rotation inputs must contain at least one frame and joint")
    if not np.allclose(worlds[..., 3, :], np.array([0, 0, 0, 1]), atol=1e-7):
        raise ValueError("joint_world homogeneous bottom rows are invalid")
    if parents.shape != (joints,) or parents[0] != -1 or np.any(parents[1:] < 0) or np.any(parents[1:] >= np.arange(1, joints)):
        raise ValueError("parents must be an ordered rooted hierarchy")
    if isinstance(joint_index, (bool, np.bool_)) or not isinstance(joint_index, (int, np.integer)) or joint_index < 0 or joint_index >= joints:
        raise ValueError("joint_index is invalid")
    if parents[joint_index] < 0:
        raise ValueError("joint_index must be a non-root leaf")
    if np.any(parents == joint_index):
        raise ValueError("joint_index must be a leaf")
    if axis.shape != (3,) or not np.isfinite(axis).all() or np.linalg.norm(axis) <= 1e-10:
        raise ValueError("local_axis must be finite and nonzero")
    if source.shape != (frames, 2) or not np.isfinite(source).all() or np.linalg.norm(source, axis=1).min() <= 1e-10:
        raise ValueError("source_directions must be finite [F,2] directions")
    if isinstance(anchor_frame, (bool, np.bool_)) or not isinstance(anchor_frame, (int, np.integer)) or anchor_frame < 0 or anchor_frame >= frames or max_correction_degrees <= 0 or max_correction_degrees > 180 or not np.isfinite(max_correction_degrees):
        raise ValueError("anchor_frame or correction bound is invalid")
    if not isinstance(camera, dict):
        raise ValueError("camera must be a mapping")
    right, down = np.asarray(camera.get("right")), np.asarray(camera.get("down"))
    if right.shape != (3,) or down.shape != (3,) or not np.isfinite(np.r_[right, down]).all():
        raise ValueError("camera basis is invalid")
    normal = np.cross(right, down).astype(np.float64); normal_norm = np.linalg.norm(normal)
    if normal_norm <= 1e-10 or abs(np.dot(right, down)) > 1e-7 or abs(np.linalg.norm(right) - 1) > 1e-7 or abs(np.linalg.norm(down) - 1) > 1e-7:
        raise ValueError("camera basis must be orthonormal")
    normal /= normal_norm
    if not np.isfinite(local).all() or not np.isfinite(worlds).all():
        raise ValueError("rotation inputs must be finite")
    if not np.allclose(np.matmul(local, np.swapaxes(local, -1, -2)), np.eye(3), atol=1e-7) or not np.allclose(np.linalg.det(local), 1, atol=1e-7):
        raise ValueError("local rotations must be proper SO(3)")
    for frame in range(frames):
        for joint in range(joints):
            parent = parents[joint]
            expected = local[frame, joint] if parent < 0 else worlds[frame, parent, :3, :3] @ local[frame, joint]
            if not np.allclose(expected, worlds[frame, joint, :3, :3], atol=1e-6):
                raise ValueError("joint_world is inconsistent with local rotations")
    projected = np.empty((frames, 2))
    for frame in range(frames):
        vector = worlds[frame, joint_index, :3, :3] @ axis
        projected[frame] = [vector @ right, vector @ down]
    if np.linalg.norm(projected, axis=1).min() <= 1e-10:
        raise ValueError("attachment axis has degenerate screen projection")
    baseline_angles = np.array([_angle(value) for value in projected])
    source_angles = np.array([_angle(value) for value in source])
    desired = baseline_angles[anchor_frame] + _wrap(source_angles - source_angles[anchor_frame])
    corrections = _wrap(desired - baseline_angles)
    bound = np.deg2rad(max_correction_degrees)
    if np.max(np.abs(corrections)) > bound + 1e-10:
        raise ValueError("required attachment correction exceeds bound")
    corrected_local, corrected_world = local.copy(), worlds.copy()
    for frame, correction in enumerate(corrections):
        if frame == anchor_frame: continue
        rotation = Rotation.from_rotvec(normal * correction).as_matrix()
        world_rot = rotation @ worlds[frame, joint_index, :3, :3]
        corrected_world[frame, joint_index, :3, :3] = world_rot
        parent = parents[joint_index]
        corrected_local[frame, joint_index] = world_rot if parent < 0 else worlds[frame, parent, :3, :3].T @ world_rot
    corrected_vectors = np.array([corrected_world[frame, joint_index, :3, :3] @ axis for frame in range(frames)])
    corrected_projected = np.column_stack((corrected_vectors @ right, corrected_vectors @ down))
    actual = np.array([_angle(value) for value in corrected_projected])
    baseline_vectors = np.array([worlds[frame, joint_index, :3, :3] @ axis for frame in range(frames)])
    depth_error = float(np.max(np.abs(corrected_vectors @ normal - baseline_vectors @ normal)))
    length_error = float(np.max(np.abs(np.linalg.norm(corrected_vectors, axis=1) - np.linalg.norm(baseline_vectors, axis=1))))
    inactive = [index for index in range(joints) if index != joint_index]
    return corrected_local, corrected_world, {"anchorFrame": int(anchor_frame),
        "correctionDegrees": np.rad2deg(corrections).tolist(),
        "maxCorrectionDegrees": float(np.max(np.abs(np.rad2deg(corrections)))),
        "beforeAngularErrorDegrees": float(np.mean(np.abs(_wrap(baseline_angles - desired)) * 180 / np.pi)),
        "afterAngularErrorDegrees": float(np.mean(np.abs(_wrap(actual - desired)) * 180 / np.pi)),
        "anchorUnchanged": bool(np.array_equal(corrected_local[anchor_frame], local[anchor_frame])),
        "anchorWorldMax": float(np.max(np.abs(corrected_world[anchor_frame, joint_index] - worlds[anchor_frame, joint_index]))),
        "inactiveLocalMax": float(np.max(np.abs(np.delete(corrected_local, joint_index, axis=1) - np.delete(local, joint_index, axis=1)))),
        "inactiveWorldMax": float(np.max(np.abs(corrected_world[:, inactive] - worlds[:, inactive]))) if inactive else 0.0,
        "translationsUnchanged": bool(np.array_equal(corrected_world[..., :3, 3], worlds[..., :3, 3])),
        "depthError": depth_error, "axisLengthError": length_error,
        "depthAndLengthPreserved": bool(depth_error <= 1e-9 and length_error <= 1e-9)}
