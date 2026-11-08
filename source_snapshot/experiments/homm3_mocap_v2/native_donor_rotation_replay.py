"""Diagnostic replay of decoded native rotations on a donor bind skeleton.

This module deliberately does not infer translations from the pose or apply a
scale/camera correction.  It is a control for asking whether the supplied
rotations and native offsets alone reproduce a donor result.
"""
from __future__ import annotations

import numpy as np

from donor_eagle import skin_dense
from mesh_preview import fk_world_matrices
from model_runner import rotations_from_6d


def _parents(value, joint_count: int) -> np.ndarray:
    raw = np.asarray(value)
    if raw.shape != (joint_count,) or raw.dtype.kind not in "iu":
        raise ValueError("parents must be an integer [J] array")
    parent = raw.astype(np.int64, copy=True)
    if parent[0] != -1:
        raise ValueError("parents must have exactly one root at index 0")
    roots = np.flatnonzero(parent < 0)
    if roots.tolist() != [0]:
        raise ValueError("parents must have exactly one root at index 0")
    for index in range(1, joint_count):
        if not 0 <= int(parent[index]) < index:
            raise ValueError("parents must be root-first ordered")
    return parent


def _rotations(rot6d: np.ndarray) -> np.ndarray:
    matrices, _ = rotations_from_6d(rot6d)
    matrices = np.array(matrices, dtype=np.float64, copy=True)
    if matrices.shape != rot6d.shape[:-1] + (3, 3) or not np.isfinite(matrices).all():
        raise ValueError("decoded rotations must be finite [F,J,3,3]")
    gram = np.matmul(np.swapaxes(matrices, -1, -2), matrices)
    if not np.allclose(gram, np.eye(3), rtol=0.0, atol=2e-5):
        raise ValueError("decoded rotations are not orthonormal")
    determinant = np.linalg.det(matrices)
    if np.any(~np.isfinite(determinant)) or np.any(determinant <= 0.0) or not np.allclose(determinant, 1.0, rtol=0.0, atol=2e-5):
        raise ValueError("decoded rotations must be proper SO(3) matrices")
    return matrices


def _mesh_inputs(vertices, weights, inverse_bind, joint_count: int):
    supplied = (vertices is not None, weights is not None, inverse_bind is not None)
    if any(supplied) and not all(supplied):
        raise ValueError("vertices, weights, and inverse_bind must be supplied together")
    if not any(supplied):
        return None
    verts = np.array(vertices, dtype=np.float64, copy=True)
    skin = np.array(weights, dtype=np.float64, copy=True)
    bind = np.array(inverse_bind, dtype=np.float64, copy=True)
    if verts.ndim != 2 or verts.shape[1] != 3 or len(verts) == 0 or not np.isfinite(verts).all():
        raise ValueError("vertices must be nonempty finite [V,3]")
    if skin.shape != (len(verts), joint_count) or not np.isfinite(skin).all() or np.any(skin < 0.0):
        raise ValueError("weights must be finite nonnegative [V,J]")
    if not np.allclose(skin.sum(axis=1), 1.0, rtol=0.0, atol=1e-7):
        raise ValueError("weights rows must be normalized")
    if bind.shape != (joint_count, 4, 4) or not np.isfinite(bind).all():
        raise ValueError("inverse_bind must be finite [J,4,4]")
    return verts, skin, bind


def replay_native_rotations(rot6d, offsets, parents, root_anchor, *, vertices=None, weights=None, inverse_bind=None):
    """Replay native rotations, offsets, and explicit root anchor without retargeting."""
    encoded = np.array(rot6d, dtype=np.float64, copy=True)
    if encoded.ndim != 3 or encoded.shape[-1] != 6 or encoded.shape[0] == 0 or encoded.shape[1] == 0 or not np.isfinite(encoded).all():
        raise ValueError("rot6d must be nonempty finite [F,J,6]")
    frames, joint_count = encoded.shape[:2]
    translation = np.array(offsets, dtype=np.float64, copy=True)
    if translation.shape != (joint_count, 3) or not np.isfinite(translation).all():
        raise ValueError("offsets must be finite [J,3]")
    parent = _parents(parents, joint_count)
    anchor = np.array(root_anchor, dtype=np.float64, copy=True)
    if anchor.shape == (3,):
        anchor = np.broadcast_to(anchor, (frames, 3)).copy()
    elif anchor.shape != (frames, 3):
        raise ValueError("root_anchor must have shape [3] or [F,3]")
    if not np.isfinite(anchor).all():
        raise ValueError("root_anchor must be finite")
    mesh = _mesh_inputs(vertices, weights, inverse_bind, joint_count)
    local = _rotations(encoded)
    worlds = np.stack([
        fk_world_matrices(local_rotation=local[index], local_translation=translation,
                          parents=parent, root_world=anchor[index])
        for index in range(frames)
    ])
    result = {
        "localRotation": local,
        "jointWorld": worlds,
        "positions": worlds[:, :, :3, 3].copy(),
        "motionOwner": "native_donor_rotation_replay_diagnostic",
        "accepted": False,
    }
    if mesh is not None:
        verts, skin, bind = mesh
        result["meshes"] = np.stack([skin_dense(verts, skin, world, bind) for world in worlds])
    return result


__all__ = ["replay_native_rotations"]
