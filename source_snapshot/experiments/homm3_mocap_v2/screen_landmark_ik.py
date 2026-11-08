"""CPU fixed-length screen-landmark rotation fitting."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation

from mesh_preview import fk_world_matrices


def solve(local_rotation, offsets, parents, root_world, camera, active_indices,
          sites, targets, confidence, *, max_degrees=100, prior_weight=.02,
          temporal_weight=.02, max_nfev=80):
    baseline = np.asarray(local_rotation, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    roots = np.asarray(root_world, dtype=np.float64)
    target = np.asarray(targets, dtype=np.float64)
    conf = np.asarray(confidence, dtype=np.float64)
    if baseline.ndim != 4 or baseline.shape[-2:] != (3, 3):
        raise ValueError("local_rotation must be [F,J,3,3]")
    frames, joints = baseline.shape[:2]
    if frames < 1 or joints < 1 or not np.allclose(np.matmul(baseline, np.swapaxes(baseline, -1, -2)), np.eye(3), atol=1e-7) or not np.allclose(np.linalg.det(baseline), 1, atol=1e-7):
        raise ValueError("local_rotation must contain proper SO(3) matrices")
    if offsets.shape != (joints, 3) or parents.shape != (joints,) or roots.shape != (frames, 3):
        raise ValueError("offsets, parents, and root_world dimensions do not match rotations")
    if target.ndim != 3 or target.shape[0] != frames or target.shape[2] != 2:
        raise ValueError("targets must be [F,S,2]")
    if conf.shape != target.shape[:2] or not np.isfinite(target).all() or not np.isfinite(conf).all():
        raise ValueError("targets and confidence must be finite and shape-compatible")
    if parents[0] != -1 or np.any(parents[1:] < 0) or np.any(parents[1:] >= np.arange(1, joints)) or np.count_nonzero(parents == -1) != 1:
        raise ValueError("parents must be an ordered single-root hierarchy")
    raw_active = tuple(active_indices)
    if not raw_active or any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int, np.integer)) for i in raw_active):
        raise ValueError("active_indices must be a non-empty list of integer joints")
    active = tuple(int(i) for i in raw_active)
    if len(set(active)) != len(active) or any(i < 0 or i >= joints for i in active):
        raise ValueError("active_indices contains an unknown or duplicate joint")
    if prior_weight < 0 or temporal_weight < 0 or not np.isfinite(prior_weight) or not np.isfinite(temporal_weight) or isinstance(max_nfev, bool) or not isinstance(max_nfev, (int, np.integer)) or max_nfev <= 0:
        raise ValueError("max_degrees must be positive and finite")
    if np.isscalar(max_degrees):
        degree_limits = np.full(len(active), float(max_degrees))
    else:
        degree_limits = np.asarray(max_degrees, dtype=np.float64)
        if degree_limits.shape != (len(active),):
            raise ValueError("max_degrees sequence must match active_indices")
    if not np.isfinite(degree_limits).all() or np.any(degree_limits <= 0):
        raise ValueError("max_degrees must be positive and finite")
    if not np.isfinite(baseline).all() or not np.isfinite(offsets).all() or not np.isfinite(roots).all():
        raise ValueError("rotation, offsets, and roots must be finite")
    names = list(sites)
    if not names or target.shape[1] != len(names):
        raise ValueError("site count does not match targets")
    for name, site in sites.items():
        if not isinstance(site, dict) or int(site.get("joint", -1)) not in range(joints):
            raise ValueError(f"site {name} has an invalid joint")
        point = np.asarray(site.get("localPoint"), dtype=np.float64)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError(f"site {name} localPoint must be finite [3]")
    if np.any(conf < 0):
        raise ValueError("confidence must be non-negative")
    if not np.any(conf > 0):
        raise ValueError("at least one positive-confidence observation is required")
    camera_keys = ("right", "down", "scale", "offset")
    if any(key not in camera for key in camera_keys):
        raise ValueError("camera is missing projection fields")
    right, down = np.asarray(camera["right"], dtype=np.float64), np.asarray(camera["down"], dtype=np.float64)
    scale, offset = float(camera["scale"]), np.asarray(camera["offset"], dtype=np.float64)
    if right.shape != (3,) or down.shape != (3,) or offset.shape != (2,) or scale <= 0 or not np.isfinite(np.r_[right, down, offset, scale]).all():
        raise ValueError("camera projection fields are invalid")

    def evaluate(rotations):
        worlds = np.empty((frames, joints, 4, 4), dtype=np.float64)
        pixels = np.empty((frames, len(names), 2), dtype=np.float64)
        translations = offsets.copy()
        for frame in range(frames):
            worlds[frame] = fk_world_matrices(local_rotation=rotations[frame], local_translation=translations,
                                              parents=parents, root_world=roots[frame])
            for site_index, site in enumerate(sites.values()):
                point = np.r_[np.asarray(site["localPoint"], dtype=np.float64), 1.0]
                projected = worlds[frame, int(site["joint"])] @ point
                pixels[frame, site_index] = [projected[:3] @ right * scale + offset[0],
                                               projected[:3] @ down * scale + offset[1]]
        return worlds, pixels

    active_count = len(active)
    def unpack(values):
        result = baseline.copy()
        delta = values.reshape(frames, active_count, 3)
        for frame in range(frames):
            for slot, joint in enumerate(active):
                result[frame, joint] = (Rotation.from_rotvec(delta[frame, slot]) * Rotation.from_matrix(baseline[frame, joint])).as_matrix()
        return result, delta

    _, initial_pixels = evaluate(baseline)
    valid = conf > 0
    norm = max(scale, 1e-12)
    def residual(values):
        rotations, delta = unpack(values)
        _, pixels = evaluate(rotations)
        terms = [((pixels - target) / norm * conf[..., None])[np.repeat(valid[..., None], 2, axis=2)].reshape(-1)]
        terms.append((prior_weight * values).reshape(-1))
        if frames > 1 and temporal_weight:
            terms.append((temporal_weight * (delta[1:] - delta[:-1])).reshape(-1))
        return np.concatenate(terms)
    # Flattening is frame-major [frame, active-joint, axis]. Repeat each
    # joint's limit for its three rotation-vector components before tiling.
    bound = np.tile(np.repeat(np.deg2rad(degree_limits), 3), frames).reshape(-1)
    start = time.perf_counter()
    fitted_values = np.zeros((frames, active_count, 3), dtype=np.float64)
    variable_count = frames * active_count * 3
    observed_count = int(np.count_nonzero(valid)) * 2
    temporal_rows = max(0, frames - 1) * active_count * 3 if temporal_weight else 0
    rows = observed_count + variable_count + temporal_rows
    sparsity = lil_matrix((rows, variable_count), dtype=np.int8)
    row = 0
    for frame, site in zip(*np.nonzero(valid)):
        col_start = frame * active_count * 3
        sparsity[row:row + 2, col_start:col_start + active_count * 3] = 1
        row += 2
    for variable in range(variable_count):
        sparsity[row + variable, variable] = 1
    row += variable_count
    if temporal_weight:
        for frame in range(frames - 1):
            for slot in range(active_count):
                first = (frame * active_count + slot) * 3
                second = ((frame + 1) * active_count + slot) * 3
                for axis in range(3):
                    sparsity[row + axis, first + axis] = 1
                    sparsity[row + axis, second + axis] = 1
                row += 3
    result = least_squares(residual, fitted_values.reshape(-1), bounds=(-bound, bound), max_nfev=int(max_nfev), jac_sparsity=sparsity.tocsr())
    corrected, _ = unpack(result.x)
    worlds, pixels = evaluate(corrected)
    inactive = [j for j in range(joints) if j not in active]
    inactive_error = float(np.max(np.abs(corrected[:, inactive] - baseline[:, inactive]))) if inactive else 0.0
    parent_lengths = np.linalg.norm(offsets[1:], axis=1) if joints > 1 else np.empty(0)
    positions = worlds[:, :, :3, 3]
    world_lengths = np.linalg.norm(positions[:, 1:] - positions[:, parents[1:]], axis=2) if joints > 1 else np.empty((frames, 0))
    actual_delta = {str(joint): float(np.max(np.abs(np.rad2deg(
        (Rotation.from_matrix(corrected[:, joint]) * Rotation.from_matrix(baseline[:, joint]).inv()).as_rotvec()))))
                    for joint in active}
    geodesic_delta = {str(joint): float(np.max(np.rad2deg(
        (Rotation.from_matrix(corrected[:, joint]) * Rotation.from_matrix(baseline[:, joint]).inv()).magnitude())))
                      for joint in active}
    return corrected, worlds, {"converged": bool(result.success), "status": int(result.status),
        "initialPixelError": float(np.mean(np.linalg.norm((initial_pixels - target)[valid], axis=1))) if np.any(valid) else 0.0,
        "finalPixelError": float(np.mean(np.linalg.norm((pixels - target)[valid], axis=1))) if np.any(valid) else 0.0,
        "elapsedSeconds": time.perf_counter() - start, "unchangedInactiveMatrixError": inactive_error,
        "fixedOffsetParity": bool(np.allclose(world_lengths, parent_lengths[None, :], atol=1e-9)),
         # maxDeltaDegrees is the component-wise bound diagnostic; geodesic
         # rotation may exceed it by combining three components.
         "maxDeltaDegrees": actual_delta, "maxDeltaGeodesicDegrees": geodesic_delta,
         "nfev": int(result.nfev)}
