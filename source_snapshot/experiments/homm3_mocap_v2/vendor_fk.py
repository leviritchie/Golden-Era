"""Ground-truth FK in the convention that matches stored vendor 6D.

Vendor `rot6d_to_fk_positions` decodes 6D as two columns. Stored zoo/obj
`rot6d` is the first two rows of the local rotation matrix (`matrix_to_rotation_6d`).
Those conventions agree at identity rest and disagree on animated poses.

Vendor `build_inference_batch` also stores `offset_a = (anim.offsets - root_offset) / gscale`,
which subtracts the root offset from every bone. Identity FK of that tensor does
not recover rest. The matching FK offsets are `anim.offsets` with the root zeroed.

Do not use a rotation-error metric until GT 6D FK reconstructs GT positions in
this convention. Mesh2pose `bvh_pose` positions are a different signal from BVH
global FK; image-to-position compares against the pose npz, not this FK pair.
"""
from __future__ import annotations

import sys
from typing import Any

import numpy as np

from motion_metrics import rot6d_to_matrix
from paths import VENDOR
from vendor_reference import load_complete_package

GT_FK_MEAN_TOL = 1e-5
GT_FK_MAX_TOL = 1e-4


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def parent_relative_offsets(offsets: np.ndarray, *, zero_root: bool = True) -> np.ndarray:
    """Vendor `anim.offsets` are already parent-relative bone vectors."""
    values = np.asarray(offsets, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"offsets must be [J,3], got {values.shape}")
    out = values.copy()
    if zero_root:
        out[0] = 0.0
    return out


def vendor_batch_offset_a(offsets: np.ndarray, global_scale: float) -> np.ndarray:
    """Reproduce the tensor `build_inference_batch` puts in `offset_a` (unpadded)."""
    values = np.asarray(offsets, dtype=np.float64)
    scale = float(global_scale)
    if scale <= 0:
        raise ValueError(f"global_scale must be positive, got {scale}")
    return (values - values[0:1, :]) / scale


def storage_rot6d_fk_positions(
    rot6d: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    """FK from stored (first-two-rows) 6D and parent-relative offsets.

    Output is root-centered. `global_scale` is not applied; pass offsets already
    in the same units as the position target.
    """
    rotations = rot6d_to_matrix(rot6d)
    bone = parent_relative_offsets(offsets, zero_root=True)
    parent = np.asarray(parents, dtype=np.int64)
    if rotations.ndim != 4 or rotations.shape[-2:] != (3, 3):
        raise ValueError(f"rot6d must decode to [T,J,3,3], got {rotations.shape}")
    if bone.shape != (rotations.shape[1], 3):
        raise ValueError(f"offsets {bone.shape} do not match joints {rotations.shape[1]}")
    if parent.shape != (rotations.shape[1],):
        raise ValueError(f"parents {parent.shape} do not match joints {rotations.shape[1]}")
    frame_count, joint_count = rotations.shape[:2]
    world_rot = np.zeros((frame_count, joint_count, 3, 3), dtype=np.float64)
    world_pos = np.zeros((frame_count, joint_count, 3), dtype=np.float64)
    for index in range(joint_count):
        parent_index = int(parent[index])
        if parent_index < 0:
            world_rot[:, index] = rotations[:, index]
            world_pos[:, index] = bone[index]
            continue
        world_rot[:, index] = np.matmul(world_rot[:, parent_index], rotations[:, index])
        world_pos[:, index] = world_pos[:, parent_index] + np.einsum(
            "tij,j->ti",
            world_rot[:, parent_index],
            bone[index],
        )
    return world_pos - world_pos[:, 0:1, :]


def bvh_global_positions(anim: Any, joint_count: int) -> np.ndarray:
    _vendor_on_path()
    from utils import animation as animation

    global_xforms = animation.transforms_global(anim)
    positions = np.asarray(global_xforms[:, :, :3, 3] / global_xforms[:, :, 3:, 3], dtype=np.float64)
    return positions[:, :joint_count]


def gt_rot6d_fk_vs_bvh_positions(kind: str, ref_seq: str) -> dict[str, Any]:
    """GT stored 6D FK versus BVH global positions, same units, root-centered."""
    package = load_complete_package(kind, ref_seq)
    joint_count = int(package["jointCount"])
    rot6d = np.asarray(package["poseRot6d"], dtype=np.float32)[:, :joint_count]
    offsets = np.asarray(package["offsets"], dtype=np.float64)[:joint_count]
    parents = np.asarray(package["parents"], dtype=np.int64)[:joint_count]
    fk = storage_rot6d_fk_positions(rot6d, offsets, parents)
    gt = bvh_global_positions(package["anim"], joint_count)
    gt = gt - gt[:, 0:1, :]
    error = np.linalg.norm(fk - gt, axis=-1)
    identity = np.zeros((1, joint_count, 6), dtype=np.float32)
    identity[..., 0] = 1.0
    identity[..., 4] = 1.0
    rest_fk = storage_rot6d_fk_positions(identity, offsets, parents)[0]
    rest_world = np.asarray(package["anim"].joint_rest_global_pos(), dtype=np.float64)[:joint_count]
    rest_world = rest_world - rest_world[0:1, :]
    rest_error = np.linalg.norm(rest_fk - rest_world, axis=-1)
    vendor_offset = vendor_batch_offset_a(offsets, float(package["globalScale"]))
    vendor_rest_fk = storage_rot6d_fk_positions(
        identity,
        vendor_offset * float(package["globalScale"]),
        parents,
    )[0]
    vendor_rest_error = np.linalg.norm(vendor_rest_fk - rest_world, axis=-1)
    pose_npz = np.asarray(package["posePosition"], dtype=np.float64)[:, :joint_count]
    pose_npz = pose_npz - pose_npz[:, 0:1, :]
    npz_error = np.linalg.norm(fk - pose_npz, axis=-1)
    report = {
        "kind": kind,
        "refSeq": ref_seq,
        "convention": "storage_rot6d_first_two_rows_plus_anim_offsets_root_zeroed",
        "jointCount": joint_count,
        "frameCount": int(rot6d.shape[0]),
        "fkVsBvhGlobalMean": float(error.mean()),
        "fkVsBvhGlobalMax": float(error.max()),
        "identityFkVsRestMean": float(rest_error.mean()),
        "identityFkVsRestMax": float(rest_error.max()),
        "vendorOffsetAIdentityFkVsRestMean": float(vendor_rest_error.mean()),
        "vendorOffsetAIsNotFkConvention": bool(vendor_rest_error.max() > GT_FK_MAX_TOL),
        "fkVsPoseNpzMean": float(npz_error.mean()),
        "fkVsPoseNpzMax": float(npz_error.max()),
        "poseNpzIsNotBvhGlobal": bool(npz_error.max() > GT_FK_MAX_TOL),
        "matchesSameConvention": bool(error.max() <= GT_FK_MAX_TOL and rest_error.max() <= GT_FK_MAX_TOL),
        "rotationErrorAllowed": bool(error.max() <= GT_FK_MAX_TOL),
        "note": (
            "Rotation metrics may run only after matchesSameConvention. "
            "Image-to-position still compares pred_position to pose-npz positions. "
            "Learned rotations are diagnosis-only."
        ),
    }
    return report
