"""Shared capture-to-SmartRig retargeter: parent-relative directions, fixed lengths.

Predicted capture joint positions are the motion interface. This module does not
copy absolute donor coordinates, does not import `position_transfer`, and does
not manufacture root travel. Twist that positions do not determine is a
minimum-change prior, not captured evidence.

Donor and target may differ in proportion and chain segmentation. Bind-frame
alignment expresses each capture bone direction in that bone's rest frame, then
applies the same local direction to the corresponding target rest frame.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from mesh_preview import fk_world_matrices, rotation_between, validate_pose_world

TWIST_POLICY = "minimum_change_prior_not_captured_evidence"
REGULARIZER_WEIGHT = 0.25
REGULARIZER_MAX_DIRECTION_LOSS = 0.15
MOTION_GATE_RAD = 0.05
DESIRED_CONFLICT_RAD = 0.26


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-8:
        return np.zeros(3, dtype=np.float64)
    return values / norm


def _as_rotation(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    u, _singular, vh = np.linalg.svd(values)
    rotation = u @ vh
    if float(np.linalg.det(rotation)) < 0:
        u[:, -1] *= -1
        rotation = u @ vh
    return rotation


def _rodrigues(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = _unit(axis)
    cosine = float(np.cos(angle))
    sine = float(np.sin(angle))
    skew = np.array(
        [[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]],
        dtype=np.float64,
    )
    return np.eye(3, dtype=np.float64) * cosine + sine * skew + (1.0 - cosine) * np.outer(axis, axis)


def slerp_so3(start: np.ndarray, end: np.ndarray, amount: float) -> np.ndarray:
    a = _as_rotation(start)
    b = _as_rotation(end)
    relative = a.T @ b
    cosine = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
    angle = float(np.arccos(cosine))
    if angle < 1e-8:
        return b
    axis = np.array(
        [relative[2, 1] - relative[1, 2], relative[0, 2] - relative[2, 0], relative[1, 0] - relative[0, 1]],
        dtype=np.float64,
    )
    if float(np.linalg.norm(axis)) < 1e-8:
        return b
    return _as_rotation(a @ _rodrigues(axis, angle * float(amount)))


def kabsch_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(target, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError(f"kabsch inputs must be [N,3], got {src.shape} and {dst.shape}")
    if src.shape[0] == 0:
        return np.eye(3, dtype=np.float64)
    if src.shape[0] == 1:
        return rotation_between(src[0], dst[0])
    covariance = src.T @ dst
    u, _singular, vh = np.linalg.svd(covariance)
    rotation = vh.T @ u.T
    if float(np.linalg.det(rotation)) < 0:
        vh[-1] *= -1
        rotation = vh.T @ u.T
    return _as_rotation(rotation)


def bone_frame(direction: np.ndarray, hint: np.ndarray | None = None) -> np.ndarray:
    axis = _unit(direction)
    if float(np.linalg.norm(axis)) < 1e-8:
        return np.eye(3, dtype=np.float64)
    if hint is None:
        hint = np.array((0.0, 1.0, 0.0), dtype=np.float64)
    binormal = np.cross(_unit(hint), axis)
    if float(np.linalg.norm(binormal)) < 1e-6:
        binormal = np.cross(np.array((1.0, 0.0, 0.0), dtype=np.float64), axis)
    if float(np.linalg.norm(binormal)) < 1e-6:
        binormal = np.cross(np.array((0.0, 0.0, 1.0), dtype=np.float64), axis)
    binormal = _unit(binormal)
    normal = np.cross(axis, binormal)
    return np.stack((axis, binormal, normal), axis=1)


def polyline_directions(points: np.ndarray, sample_count: int) -> np.ndarray:
    path = np.asarray(points, dtype=np.float64)
    if path.ndim != 2 or path.shape[1] != 3 or path.shape[0] < 2:
        raise ValueError(f"polyline must be [N>=2,3], got {path.shape}")
    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    deltas = path[1:] - path[:-1]
    lengths = np.linalg.norm(deltas, axis=-1)
    total = float(lengths.sum())
    out = np.zeros((sample_count, 3), dtype=np.float64)
    if total <= 1e-8:
        return out
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    for index in range(sample_count):
        target = (index + 0.5) / sample_count * total
        segment = int(np.searchsorted(cumulative, target, side="right") - 1)
        segment = min(max(segment, 0), len(deltas) - 1)
        out[index] = _unit(deltas[segment])
    return out


def identity_fk_positions(offsets: np.ndarray, parents: np.ndarray) -> np.ndarray:
    bone = np.asarray(offsets, dtype=np.float64).copy()
    parent = np.asarray(parents, dtype=np.int64)
    if bone.shape != (parent.shape[0], 3):
        raise ValueError("offsets do not match parents")
    bone[0] = 0.0
    positions = np.zeros_like(bone)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            positions[index] = bone[index]
        else:
            positions[index] = positions[int(parent_index)] + bone[index]
    return positions - positions[0:1]


def rest_bone_directions(positions: np.ndarray, parents: np.ndarray) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    directions = np.zeros_like(values)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            continue
        directions[index] = _unit(values[index] - values[int(parent_index)])
    return directions


def _polyline_hint(rest_dirs: np.ndarray, index: int) -> np.ndarray:
    for other in (index - 1, index + 1, index - 2, index + 2):
        if 0 <= other < len(rest_dirs):
            if float(np.linalg.norm(np.cross(rest_dirs[index], rest_dirs[other]))) > 1e-6:
                return rest_dirs[other]
    return np.array((0.0, 1.0, 0.0), dtype=np.float64)


def transfer_chain_directions(
    *,
    capture_polyline: np.ndarray,
    capture_rest_polyline: np.ndarray,
    target_rest_polyline: np.ndarray,
    sample_count: int,
) -> np.ndarray:
    rest_cap = polyline_directions(capture_rest_polyline, sample_count)
    pose_cap = polyline_directions(capture_polyline, sample_count)
    # The capture chain is resampled because its bone count may differ from the
    # target's. The target side is one desired direction per actual target bone,
    # so it must use the real rest bone directions, not an arc-length resample:
    # with unequal bone lengths a resample differs from the bones, and a pose equal
    # to the reference would then no longer map back to the target rest.
    target_points = np.asarray(target_rest_polyline, dtype=np.float64)
    if target_points.shape != (sample_count + 1, 3):
        raise ValueError(
            f"target chain must have exactly sample_count+1={sample_count + 1} points, got {target_points.shape}"
        )
    rest_tgt = np.stack([_unit(target_points[i + 1] - target_points[i]) for i in range(sample_count)])
    desired = np.zeros((sample_count, 3), dtype=np.float64)
    for index in range(sample_count):
        if float(np.linalg.norm(rest_cap[index])) < 1e-8 or float(np.linalg.norm(rest_tgt[index])) < 1e-8:
            continue
        cap_hint = _polyline_hint(rest_cap, index)
        tgt_hint = _polyline_hint(rest_tgt, index)
        local = bone_frame(rest_cap[index], cap_hint).T @ pose_cap[index]
        desired[index] = bone_frame(rest_tgt[index], tgt_hint) @ local
        desired[index] = _unit(desired[index])
    return desired


def _name_index(names: Sequence[str]) -> dict[str, int]:
    return {str(name): index for index, name in enumerate(names)}


def _children_lists(parents: np.ndarray) -> list[list[int]]:
    parent = np.asarray(parents, dtype=np.int64)
    children: list[list[int]] = [[] for _ in range(parent.shape[0])]
    for index, parent_index in enumerate(parent):
        if int(parent_index) >= 0:
            children[int(parent_index)].append(index)
    return children


def _set_desired(store: np.ndarray, frame: int, joint: int, direction: np.ndarray) -> None:
    desired = _unit(direction)
    if float(np.linalg.norm(desired)) < 1e-8:
        return
    existing = store[frame, joint]
    if float(np.linalg.norm(existing)) > 1e-8:
        cosine = float(np.clip(np.dot(_unit(existing), desired), -1.0, 1.0))
        if float(np.arccos(cosine)) > DESIRED_CONFLICT_RAD:
            raise ValueError(f"conflicting desired directions on joint {joint} at frame {frame}")
    store[frame, joint] = desired


def desired_target_directions(
    *,
    capture_positions: np.ndarray,
    capture_rest: np.ndarray,
    capture_names: Sequence[str],
    target_rest: np.ndarray,
    target_names: Sequence[str],
    chains: Sequence[dict[str, Any]],
) -> np.ndarray:
    capture = np.asarray(capture_positions, dtype=np.float64)
    capture = capture - capture[:, 0:1, :]
    rest_c = np.asarray(capture_rest, dtype=np.float64)
    rest_c = rest_c - rest_c[0:1]
    rest_t = np.asarray(target_rest, dtype=np.float64)
    cap_index = _name_index(capture_names)
    tgt_index = _name_index(target_names)
    frame_count = int(capture.shape[0])
    desired = np.zeros((frame_count, len(target_names), 3), dtype=np.float64)
    for chain in chains:
        target_chain = [tgt_index[str(name)] for name in chain["target"]]
        capture_chain = [cap_index[str(name)] for name in chain["capture"]]
        bone_count = len(target_chain) - 1
        if bone_count < 1:
            continue
        rest_poly_t = rest_t[target_chain]
        rest_poly_c = rest_c[capture_chain]
        for frame in range(frame_count):
            dirs = transfer_chain_directions(
                capture_polyline=capture[frame, capture_chain],
                capture_rest_polyline=rest_poly_c,
                target_rest_polyline=rest_poly_t,
                sample_count=bone_count,
            )
            for bone_i, joint_index in enumerate(target_chain[1:]):
                _set_desired(desired, frame, joint_index, dirs[bone_i])
    return desired


def _write_joint_world(
    world: np.ndarray,
    *,
    index: int,
    local: np.ndarray,
    rest_off: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
) -> None:
    parent = int(parents[index])
    if parent < 0:
        world[index, :3, :3] = local[index]
        world[index, :3, 3] = np.asarray(root_world, dtype=np.float64).reshape(3)
    else:
        world[index, :3, :3] = world[parent, :3, :3] @ local[index]
        world[index, :3, 3] = world[parent, :3, 3] + world[parent, :3, :3] @ rest_off[index]
    world[index, 3, :] = (0.0, 0.0, 0.0, 1.0)


def reconstruct_frame_locals(
    *,
    desired: np.ndarray,
    rest_local: np.ndarray,
    rest_off: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
) -> np.ndarray:
    joint_count = rest_local.shape[0]
    children = _children_lists(parents)
    local = np.asarray(rest_local, dtype=np.float64).copy()
    world = np.zeros((joint_count, 4, 4), dtype=np.float64)
    for index in range(joint_count):
        mapped = [
            child
            for child in children[index]
            if float(np.linalg.norm(desired[child])) > 1e-8
        ]
        parent = int(parents[index])
        parent_world = np.eye(3, dtype=np.float64) if parent < 0 else world[parent, :3, :3]
        if mapped:
            src = np.stack([_unit(rest_local[index] @ rest_off[child]) for child in mapped])
            dst = np.stack([_unit(parent_world.T @ desired[child]) for child in mapped])
            extra = kabsch_rotation(src, dst)
            local[index] = extra @ rest_local[index]
        _write_joint_world(
            world,
            index=index,
            local=local,
            rest_off=rest_off,
            parents=parents,
            root_world=root_world,
        )
    return local


def aimed_direction_error(
    *,
    local: np.ndarray,
    rest_off: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
    desired: np.ndarray,
) -> float:
    world = fk_world_matrices(
        local_rotation=local,
        local_translation=rest_off,
        parents=parents,
        root_world=root_world,
    )
    errors: list[float] = []
    for index, parent in enumerate(parents):
        if int(parent) < 0 or float(np.linalg.norm(desired[index])) < 1e-8:
            continue
        actual = _unit(world[index, :3, 3] - world[int(parent), :3, 3])
        cosine = float(np.clip(np.dot(actual, _unit(desired[index])), -1.0, 1.0))
        errors.append(float(np.arccos(cosine)))
    if not errors:
        return 0.0
    return float(np.mean(errors))


def bone_lengths(world: np.ndarray, parents: np.ndarray) -> np.ndarray:
    parent = np.asarray(parents, dtype=np.int64)
    lengths = np.zeros((parent.shape[0],), dtype=np.float64)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            continue
        lengths[index] = float(np.linalg.norm(world[index, :3, 3] - world[int(parent_index), :3, 3]))
    return lengths


def local_swing_vectors(
    *,
    positions: np.ndarray,
    rest: np.ndarray,
    parents: np.ndarray,
    joint_mask: np.ndarray | None = None,
) -> np.ndarray:
    pose = np.asarray(positions, dtype=np.float64)
    rest_pos = np.asarray(rest, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    if joint_mask is None:
        mask = parent >= 0
    else:
        mask = np.asarray(joint_mask, dtype=bool)
    rest_dirs = rest_bone_directions(rest_pos, parent)
    out = np.zeros((pose.shape[0], int(mask.sum()), 3), dtype=np.float64)
    mapped = np.where(mask)[0]
    for frame in range(pose.shape[0]):
        pose_dirs = rest_bone_directions(pose[frame], parent)
        for slot, index in enumerate(mapped):
            if float(np.linalg.norm(rest_dirs[index])) < 1e-8:
                continue
            out[frame, slot] = bone_frame(rest_dirs[index]).T @ pose_dirs[index]
    return out


def swing_excursion(local_dirs: np.ndarray) -> dict[str, float]:
    values = np.asarray(local_dirs, dtype=np.float64)
    rest = np.zeros(values.shape[-1], dtype=np.float64)
    rest[0] = 1.0
    if values.shape[0] < 1:
        raise ValueError("no frames")
    from_rest = np.arccos(np.clip((values * rest.reshape(1, 1, -1)).sum(axis=-1), -1.0, 1.0))
    if values.shape[0] < 2:
        f2f = np.zeros((0, values.shape[1]), dtype=np.float64)
    else:
        f2f = np.arccos(np.clip((values[1:] * values[:-1]).sum(axis=-1), -1.0, 1.0))
    path = f2f.sum(axis=0) if f2f.size else np.zeros((values.shape[1],), dtype=np.float64)
    return {
        "fromRestMaxRad": float(from_rest.max()) if from_rest.size else 0.0,
        "fromRestMeanRad": float(from_rest.mean()) if from_rest.size else 0.0,
        "frameToFrameMaxRad": float(f2f.max()) if f2f.size else 0.0,
        "frameToFrameMeanRad": float(f2f.mean()) if f2f.size else 0.0,
        "totalPathMaxRad": float(path.max()) if path.size else 0.0,
        "totalPathMeanRad": float(path.mean()) if path.size else 0.0,
        "phasePeakFrame": int(np.argmax(from_rest.mean(axis=1))) if from_rest.size else 0,
        "boneCount": int(values.shape[1]),
        "frameCount": int(values.shape[0]),
    }


def temporal_motion_present(excursion: dict[str, float], *, threshold_rad: float = MOTION_GATE_RAD) -> bool:
    return float(excursion["totalPathMaxRad"]) >= float(threshold_rad) or float(
        excursion["frameToFrameMaxRad"]
    ) >= float(threshold_rad)


def motion_preservation_report(
    *,
    capture_local: np.ndarray,
    retarget_local: np.ndarray,
    unsmoothed_local: np.ndarray | None = None,
) -> dict[str, Any]:
    capture = swing_excursion(capture_local)
    retarget = swing_excursion(retarget_local)
    present = temporal_motion_present(capture)
    retarget_present = temporal_motion_present(retarget)
    path_ratio = float(retarget["totalPathMaxRad"] / max(capture["totalPathMaxRad"], 1e-8))
    phase_delta = abs(int(capture["phasePeakFrame"]) - int(retarget["phasePeakFrame"]))
    report: dict[str, Any] = {
        "capture": capture,
        "retarget": retarget,
        "captureHasTemporalMotion": present,
        "retargetHasTemporalMotion": retarget_present,
        "pathRatio": path_ratio,
        "phasePeakDeltaFrames": phase_delta,
        "motionPreserved": bool(present and retarget_present and path_ratio >= 0.5),
        "stationaryDisplacedDoesNotPass": not present,
    }
    if unsmoothed_local is not None:
        unsmoothed = swing_excursion(unsmoothed_local)
        report["unsmoothed"] = unsmoothed
        report["regularizerSuppressedStroke"] = bool(
            unsmoothed["totalPathMaxRad"] >= MOTION_GATE_RAD
            and retarget["totalPathMaxRad"]
            < (1.0 - REGULARIZER_MAX_DIRECTION_LOSS) * unsmoothed["totalPathMaxRad"]
        )
    return report


def transport_bind_deltas(
    *,
    source_local_rotation: np.ndarray,
    source_rest_local_rotation: np.ndarray,
    target_rest_local_rotation: np.ndarray,
    target_to_source: dict[int, int],
) -> np.ndarray:
    """Transport SO(3) motion deltas between anatomical bind frames.

    ``source_local_rotation`` is solved relative to a validated source bind
    frame.  For each mapped bone, the basis change
    ``B = R_target_rest.T @ R_source_rest`` converts source-local coordinates
    into target-local coordinates, so ``D_target = B @ D_source @ B.T``.  The
    returned locals preserve the target bind exactly at source frame 0 when
    that frame is the declared reference.  No camera, mesh silhouette, or
    image objective participates in this operation.
    """
    source_current = np.asarray(source_local_rotation, dtype=np.float64)
    source_rest = np.asarray(source_rest_local_rotation, dtype=np.float64)
    target_rest = np.asarray(target_rest_local_rotation, dtype=np.float64)
    if source_current.ndim != 4 or source_current.shape[-2:] != (3, 3):
        raise ValueError("source_local_rotation must have shape [F,J,3,3]")
    if source_rest.shape != (source_current.shape[1], 3, 3):
        raise ValueError("source_rest_local_rotation does not match source joints")
    if target_rest.ndim != 3 or target_rest.shape[-2:] != (3, 3):
        raise ValueError("target_rest_local_rotation must have shape [J,3,3]")
    if not np.isfinite(source_current).all() or not np.isfinite(source_rest).all() or not np.isfinite(target_rest).all():
        raise ValueError("bind rotations must be finite")
    result = np.repeat(target_rest[None], source_current.shape[0], axis=0)
    for target_index, source_index in target_to_source.items():
        ti, si = int(target_index), int(source_index)
        if not 0 <= ti < target_rest.shape[0] or not 0 <= si < source_rest.shape[0]:
            raise ValueError("target_to_source contains an out-of-range joint")
        source_bind = source_rest[si]
        target_bind = target_rest[ti]
        basis = target_bind.T @ source_bind
        source_delta = source_bind.T[None] @ source_current[:, si]
        target_delta = basis[None] @ source_delta @ basis.T[None]
        result[:, ti] = target_bind[None] @ target_delta
    return result


def _apply_regularizer(
    unsmoothed: np.ndarray,
    *,
    rest_off: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
    desired: np.ndarray,
    weight: float,
) -> tuple[np.ndarray, bool]:
    frame_count = unsmoothed.shape[0]
    if frame_count < 2 or weight <= 0.0:
        return unsmoothed.copy(), False
    smoothed = unsmoothed.copy()
    for frame in range(1, frame_count):
        mixed = np.empty_like(unsmoothed[frame])
        for index in range(unsmoothed.shape[1]):
            mixed[index] = slerp_so3(smoothed[frame - 1, index], unsmoothed[frame, index], 1.0 - float(weight))
        uns_err = aimed_direction_error(
            local=unsmoothed[frame],
            rest_off=rest_off,
            parents=parents,
            root_world=root_world,
            desired=desired[frame],
        )
        mix_err = aimed_direction_error(
            local=mixed,
            rest_off=rest_off,
            parents=parents,
            root_world=root_world,
            desired=desired[frame],
        )
        if mix_err <= uns_err * (1.0 + REGULARIZER_MAX_DIRECTION_LOSS) + 1e-6:
            smoothed[frame] = mixed
        else:
            smoothed[frame] = unsmoothed[frame]
    return smoothed, True


def retarget_clip(
    *,
    capture_positions: np.ndarray,
    capture_rest: np.ndarray,
    capture_names: Sequence[str],
    capture_parents: np.ndarray,
    target_names: Sequence[str],
    target_parents: np.ndarray,
    target_rest_local_rotation: np.ndarray,
    target_rest_local_translation: np.ndarray,
    target_rest_world: np.ndarray,
    chains: Sequence[dict[str, Any]],
    regularize: bool = True,
    regularizer_weight: float = REGULARIZER_WEIGHT,
) -> dict[str, Any]:
    if not chains:
        raise ValueError("retarget_clip requires chain correspondence; missing correspondence is not a bind-pose fallback")
    capture = np.asarray(capture_positions, dtype=np.float64)
    if capture.ndim != 3 or capture.shape[-1] != 3:
        raise ValueError(f"capture_positions must be [T,J,3], got {capture.shape}")
    capture = capture - capture[:, 0:1, :]
    parents = np.asarray(target_parents, dtype=np.int64)
    rest_local = np.asarray(target_rest_local_rotation, dtype=np.float64)
    rest_off = np.asarray(target_rest_local_translation, dtype=np.float64)
    rest_world = np.asarray(target_rest_world, dtype=np.float64)
    root_world = rest_world[0]
    desired = desired_target_directions(
        capture_positions=capture,
        capture_rest=capture_rest,
        capture_names=capture_names,
        target_rest=rest_world,
        target_names=target_names,
        chains=chains,
    )
    frame_count = int(capture.shape[0])
    joint_count = len(target_names)
    unsmoothed = np.repeat(rest_local[None, ...], frame_count, axis=0)
    for frame in range(frame_count):
        unsmoothed[frame] = reconstruct_frame_locals(
            desired=desired[frame],
            rest_local=rest_local,
            rest_off=rest_off,
            parents=parents,
            root_world=root_world,
        )
    accepted = unsmoothed.copy()
    regularizer_used = False
    regularizer_rejected = False
    if regularize:
        candidate, regularizer_used = _apply_regularizer(
            unsmoothed,
            rest_off=rest_off,
            parents=parents,
            root_world=root_world,
            desired=desired,
            weight=regularizer_weight,
        )
        rest_fk = fk_world_matrices(
            local_rotation=rest_local,
            local_translation=rest_off,
            parents=parents,
            root_world=root_world,
        )
        mapped = np.linalg.norm(desired.reshape(frame_count * joint_count, 3), axis=-1).reshape(
            frame_count, joint_count
        ).max(axis=0) > 1e-8
        uns_pos = np.stack(
            [
                fk_world_matrices(
                    local_rotation=unsmoothed[frame],
                    local_translation=rest_off,
                    parents=parents,
                    root_world=root_world,
                )[:, :3, 3]
                for frame in range(frame_count)
            ]
        )
        cand_pos = np.stack(
            [
                fk_world_matrices(
                    local_rotation=candidate[frame],
                    local_translation=rest_off,
                    parents=parents,
                    root_world=root_world,
                )[:, :3, 3]
                for frame in range(frame_count)
            ]
        )
        uns_swing = local_swing_vectors(
            positions=uns_pos, rest=rest_fk[:, :3, 3], parents=parents, joint_mask=mapped
        )
        cand_swing = local_swing_vectors(
            positions=cand_pos, rest=rest_fk[:, :3, 3], parents=parents, joint_mask=mapped
        )
        uns_exc = swing_excursion(uns_swing)
        cand_exc = swing_excursion(cand_swing)
        if (
            uns_exc["totalPathMaxRad"] >= MOTION_GATE_RAD
            and cand_exc["totalPathMaxRad"]
            < (1.0 - REGULARIZER_MAX_DIRECTION_LOSS) * uns_exc["totalPathMaxRad"]
        ):
            regularizer_rejected = True
            accepted = unsmoothed.copy()
        else:
            accepted = candidate
    worlds = np.stack(
        [
            fk_world_matrices(
                local_rotation=accepted[frame],
                local_translation=rest_off,
                parents=parents,
                root_world=root_world,
            )
            for frame in range(frame_count)
        ]
    )
    uns_worlds = np.stack(
        [
            fk_world_matrices(
                local_rotation=unsmoothed[frame],
                local_translation=rest_off,
                parents=parents,
                root_world=root_world,
            )
            for frame in range(frame_count)
        ]
    )
    for frame in range(frame_count):
        validate_pose_world(worlds[frame], joint_count=joint_count)
        validate_pose_world(uns_worlds[frame], joint_count=joint_count)
    rest_worlds = fk_world_matrices(
        local_rotation=rest_local,
        local_translation=rest_off,
        parents=parents,
        root_world=root_world,
    )
    rest_lengths = bone_lengths(rest_worlds, parents)
    posed_lengths = np.stack([bone_lengths(worlds[frame], parents) for frame in range(frame_count)])
    children = _children_lists(parents)
    mapped_parents = [
        index
        for index in range(joint_count)
        if any(float(np.linalg.norm(desired[:, child]).max()) > 1e-8 for child in children[index])
    ]
    unmapped = [index for index in range(joint_count) if index not in mapped_parents]
    capture_mask = np.zeros((len(capture_names),), dtype=bool)
    cap_index = _name_index(capture_names)
    tgt_index = _name_index(target_names)
    target_mask = np.zeros((joint_count,), dtype=bool)
    for chain in chains:
        for name in list(chain["capture"])[1:]:
            capture_mask[cap_index[str(name)]] = True
        for name in list(chain["target"])[1:]:
            target_mask[tgt_index[str(name)]] = True
    capture_swing = local_swing_vectors(
        positions=capture,
        rest=np.asarray(capture_rest, dtype=np.float64) - np.asarray(capture_rest, dtype=np.float64)[0:1],
        parents=np.asarray(capture_parents, dtype=np.int64),
        joint_mask=capture_mask,
    )
    retarget_swing = local_swing_vectors(
        positions=worlds[:, :, :3, 3],
        rest=rest_worlds[:, :3, 3],
        parents=parents,
        joint_mask=target_mask,
    )
    uns_swing = local_swing_vectors(
        positions=uns_worlds[:, :, :3, 3],
        rest=rest_worlds[:, :3, 3],
        parents=parents,
        joint_mask=target_mask,
    )
    preservation = motion_preservation_report(
        capture_local=capture_swing,
        retarget_local=retarget_swing,
        unsmoothed_local=uns_swing,
    )
    root_travel = worlds[:, 0, :3, 3] - rest_worlds[0, :3, 3]
    return {
        "sourceLocalRotation": accepted,
        "unsmoothedLocalRotation": unsmoothed,
        "jointWorld": worlds,
        "unsmoothedJointWorld": uns_worlds,
        "desiredChildDirections": desired,
        "twistPolicy": TWIST_POLICY,
        "rootTranslationAvailable": False,
        "rootTravelMax": float(np.linalg.norm(root_travel, axis=-1).max()),
        "regularizerUsed": bool(regularizer_used and not regularizer_rejected),
        "regularizerRejected": regularizer_rejected,
        "mappedParentJoints": mapped_parents,
        "unmappedParentJoints": unmapped,
        "restBoneLengths": rest_lengths,
        "posedBoneLengths": posed_lengths,
        "lengthErrorMax": float(np.max(np.abs(posed_lengths - rest_lengths.reshape(1, -1)))),
        "motionPreservation": preservation,
        "captureSwing": capture_swing,
        "retargetSwing": retarget_swing,
    }
