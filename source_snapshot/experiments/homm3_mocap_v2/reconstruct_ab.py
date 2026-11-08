"""A: fixed-length rotations on the Eagle bind. B: exact captured joint replay."""
from __future__ import annotations

from typing import Any

import numpy as np

from direction_retarget import TWIST_POLICY, reconstruct_frame_locals
from donor_eagle import compute_rest_joints
from mesh_preview import fk_world_matrices, rotation_between
from pose_rotation_fk import so3_geodesic_np

B_POSITION_TOL = 1e-6


def _unit_or_none(vector: np.ndarray) -> np.ndarray | None:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-8:
        return None
    return values / norm


def _primary_child_rest_axis(index: int, rest_off: np.ndarray, parents: np.ndarray) -> np.ndarray | None:
    children = [
        child
        for child, parent in enumerate(parents)
        if int(parent) == int(index) and float(np.linalg.norm(rest_off[child])) > 1e-8
    ]
    if not children:
        return None
    return _unit_or_none(rest_off[max(children, key=lambda child: float(np.linalg.norm(rest_off[child])))])


def align_world_twist_to_previous(
    worlds: np.ndarray,
    *,
    rest_off: np.ndarray,
    parents: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep joint positions; pick the bone-axis twist closest to the previous frame.

    Independent Kabsch from rest leaves twist free around the aimed child.
    That twist can jump ~180° and squash LBS. Joint positions stay exactly
    as reconstructed. The primary (longest) child axis is the twist axis.
    """
    out = np.asarray(worlds, dtype=np.float64).copy()
    rest_off = np.asarray(rest_off, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if out.ndim != 4 or out.shape[-2:] != (4, 4):
        raise ValueError(f"worlds must be [T,J,4,4], got {out.shape}")
    aligned = 0
    max_before = 0.0
    max_after = 0.0
    for frame in range(1, len(out)):
        for index in range(out.shape[1]):
            axis = _primary_child_rest_axis(index, rest_off, parents)
            if axis is None:
                continue
            current = out[frame, index, :3, :3]
            previous = out[frame - 1, index, :3, :3]
            before = float(so3_geodesic_np(previous, current))
            max_before = max(max_before, before)
            relative = current.T @ previous
            swing = rotation_between(axis, relative @ axis)
            twist = swing.T @ relative
            aligned_rot = current @ twist
            if float(np.linalg.det(aligned_rot)) < 0:
                raise RuntimeError("aligned twist is not a proper rotation")
            direction_err = float(np.linalg.norm(aligned_rot @ axis - current @ axis))
            if direction_err > 1e-8:
                raise RuntimeError(f"aligned twist moved the bone axis by {direction_err}")
            after = float(so3_geodesic_np(previous, aligned_rot))
            max_after = max(max_after, after)
            if after + 1e-9 < before:
                out[frame, index, :3, :3] = aligned_rot
                aligned += 1
    if float(np.linalg.norm(out[:, :, :3, 3] - np.asarray(worlds)[:, :, :3, 3])) > 1e-12:
        raise RuntimeError("twist alignment moved joint positions")
    return out, {
        "alignedJoints": int(aligned),
        "maxGeodesicBefore": float(max_before),
        "maxGeodesicAfter": float(max_after),
    }


_BONE_AXIS = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)


_DO_NOT_AIM_AT = frozenset({"BN_Jaw"})


def _outgoing_direction(
    positions: np.ndarray,
    index: int,
    parents: np.ndarray,
    *,
    names: list[str] | None = None,
) -> np.ndarray:
    skip = set()
    if names is not None:
        skip = {child for child, parent in enumerate(parents) if int(parent) == int(index) and names[child] in _DO_NOT_AIM_AT}
    children = [
        child
        for child, parent in enumerate(parents)
        if int(parent) == int(index)
        and child not in skip
        and float(np.linalg.norm(positions[child] - positions[index])) > 1e-8
    ]
    if children:
        child = max(children, key=lambda item: float(np.linalg.norm(positions[item] - positions[index])))
        return positions[child] - positions[index]
    parent_index = int(parents[index])
    if parent_index >= 0:
        return positions[index] - positions[parent_index]
    return _BONE_AXIS


def bone_aligned_worlds(
    positions: np.ndarray,
    parents: np.ndarray,
    *,
    names: list[str] | None = None,
) -> np.ndarray:
    """World matrices at the capture joints with +Y along each outgoing bone.

    Joint j's transform is applied at j and rotates the segment(s) leaving j.
    Weight column j must own those same outgoing segments
    (`bone_segment_distances(..., ownership="outgoing")`). The leaf uses the
    incoming segment only because it has no child to aim at.

    Jaw is not an aim target: it is a short accessory and would spin the skull.
    Later frames parallel-transport that frame with the smallest rotation that
    keeps +Y on the posed segment, so twist cannot jump a half turn.
    """
    pos = np.asarray(positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    if pos.ndim != 3 or pos.shape[-1] != 3:
        raise ValueError(f"positions must be [T,J,3], got {pos.shape}")
    if parent.shape != (pos.shape[1],):
        raise ValueError("parents do not match joint count")
    if names is not None and len(names) != pos.shape[1]:
        raise ValueError("names do not match joint count")
    worlds = np.zeros((pos.shape[0], pos.shape[1], 4, 4), dtype=np.float64)
    worlds[:, :, 3, 3] = 1.0
    worlds[:, :, :3, 3] = pos
    axis = _BONE_AXIS

    def aimed(direction: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
        direction = _unit_or_none(direction)
        if direction is None:
            return np.eye(3, dtype=np.float64) if previous is None else previous
        if previous is None:
            return rotation_between(axis, direction)
        return rotation_between(previous @ axis, direction) @ previous

    for index in range(pos.shape[1]):
        worlds[0, index, :3, :3] = aimed(_outgoing_direction(pos[0], index, parent, names=names), None)
    for frame in range(1, pos.shape[0]):
        for index in range(pos.shape[1]):
            worlds[frame, index, :3, :3] = aimed(
                _outgoing_direction(pos[frame], index, parent, names=names),
                worlds[frame - 1, index, :3, :3],
            )
    if float(np.linalg.norm(worlds[:, :, :3, 3] - pos)) > 1e-12:
        raise RuntimeError("bone-aligned worlds moved joint positions")
    return worlds


def reconstruct_ab(
    *,
    capture_positions: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    reference_frame: int = 0,
    aim_offsets: np.ndarray | None = None,
) -> dict[str, Any]:
    capture = np.asarray(capture_positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    reference_frame = int(reference_frame)
    if reference_frame < 0 or reference_frame >= len(capture):
        raise ValueError(f"reference_frame {reference_frame} outside capture length {len(capture)}")
    rest_off = np.asarray(offsets, dtype=np.float64).copy()
    rest_off[0] = 0.0
    aim_off = rest_off if aim_offsets is None else np.asarray(aim_offsets, dtype=np.float64).copy()
    if aim_off.shape != rest_off.shape:
        raise ValueError(f"aim_offsets must match offsets {rest_off.shape}, got {aim_off.shape}")
    aim_off[0] = 0.0
    rest_joints = compute_rest_joints(offsets, parent)
    rest_local = np.zeros((len(parent), 3, 3), dtype=np.float64)
    rest_local[:] = np.eye(3, dtype=np.float64)
    root = np.asarray(rest_joints[0], dtype=np.float64).copy()
    capture = np.asarray(capture, dtype=np.float64).copy()
    # Re-anchor only the hips to the bind root. Subtracting the full reference
    # skeleton would rewrite every bone offset and breaks exact joint replay.
    ref_hips = np.asarray(capture[reference_frame, 0, :], dtype=np.float64)
    capture[:, 0, :] = capture[:, 0, :] - ref_hips + root
    locals_a = []
    desired = np.zeros_like(capture)
    for frame in range(len(capture)):
        for index, parent_index in enumerate(parent):
            if int(parent_index) < 0:
                continue
            desired[frame, index] = capture[frame, index] - capture[frame, int(parent_index)]
        locals_a.append(
            reconstruct_frame_locals(
                desired=desired[frame],
                rest_local=rest_local,
                rest_off=aim_off,
                parents=parent,
                root_world=root,
            )
        )
    local_a = np.stack(locals_a)
    worlds_a = []
    worlds_b = []
    local_t_b = np.zeros((len(capture), len(parent), 3), dtype=np.float64)
    local_t_b[:, :] = np.asarray(offsets, dtype=np.float64)
    # Keep root local translation at offsets[0] for glTF. fk_world_matrices
    # still ignores it and uses root_world.
    length_a = []
    rest_len = np.linalg.norm(rest_off, axis=1)
    for frame in range(len(capture)):
        world_a = fk_world_matrices(
            local_rotation=local_a[frame],
            local_translation=rest_off,
            parents=parent,
            root_world=root,
        )
        worlds_a.append(world_a)
        length_a.append(np.linalg.norm(world_a[:, :3, 3] - world_a[parent.clip(0), :3, 3], axis=1))
        world_rot = world_a[:, :3, :3]
        for index, parent_index in enumerate(parent):
            if int(parent_index) < 0:
                continue
            delta = capture[frame, index] - capture[frame, int(parent_index)]
            local_t_b[frame, index] = world_rot[int(parent_index)].T @ delta
        world_b = fk_world_matrices(
            local_rotation=local_a[frame],
            local_translation=local_t_b[frame],
            parents=parent,
            root_world=root,
        )
        worlds_b.append(world_b)
    worlds_a = np.stack(worlds_a)
    worlds_b = np.stack(worlds_b)
    pos_a = worlds_a[:, :, :3, 3]
    pos_b = worlds_b[:, :, :3, 3]
    residual_a = np.linalg.norm(pos_a - capture, axis=-1)
    residual_b = np.linalg.norm(pos_b - capture, axis=-1)
    if float(residual_b.max()) > B_POSITION_TOL:
        raise ValueError(f"exact-joint replay missed capture positions: max {residual_b.max()}")
    length_a = np.stack(length_a)
    length_err = np.abs(length_a[:, parent >= 0] - rest_len[parent >= 0])
    stretch_b = np.linalg.norm(local_t_b, axis=-1)
    rest_nz = rest_len > 1e-8
    stretch_ratio = np.zeros_like(stretch_b)
    stretch_ratio[:, rest_nz] = stretch_b[:, rest_nz] / rest_len[rest_nz]
    return {
        "localRotation": local_a,
        "localTranslationA": np.repeat(rest_off[None, :, :], len(capture), axis=0),
        "localTranslationB": local_t_b,
        "jointWorldA": worlds_a,
        "jointWorldB": worlds_b,
        "positionsA": pos_a,
        "positionsB": pos_b,
        "captureRootCentered": capture,
        "residualAMax": float(residual_a.max()),
        "residualAMean": float(residual_a.mean()),
        "residualBMax": float(residual_b.max()),
        "fixedLengthErrorMax": float(length_err.max()),
        "stretchBMax": float(stretch_ratio.max()),
        "stretchBMedian": float(np.median(stretch_ratio[:, rest_nz])),
        "twistPolicy": TWIST_POLICY,
        "bindRestJoints": rest_joints,
        "captureToBind": {
            "policy": "pred_position_already_in_bvh_obj_units",
            "scale": 1.0,
            "rotation": np.eye(3, dtype=np.float64).tolist(),
            "root": "per_frame_hips_moved_to_bind_hips",
            "referenceFrame": reference_frame,
            "globalScaleNotApplied": True,
        },
        "notLearnedRotations": True,
    }
