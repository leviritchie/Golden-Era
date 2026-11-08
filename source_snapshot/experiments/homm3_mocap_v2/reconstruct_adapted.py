"""Capture-relative directions on a fitted bind. Not exact-joint replay."""
from __future__ import annotations

from typing import Any

import numpy as np

from direction_retarget import TWIST_POLICY, kabsch_rotation, reconstruct_frame_locals, retarget_clip
from donor_eagle import compute_rest_joints
from motion_metrics import so3_geodesic_angle


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-8:
        return np.zeros(3, dtype=np.float64)
    return values / norm


def whole_body_rotation(
    capture_rest: np.ndarray,
    fitted_rest: np.ndarray,
    names: list[str],
    hub_names: tuple[str, ...],
) -> np.ndarray:
    index = {name: i for i, name in enumerate(names)}
    src = np.stack([capture_rest[index[name]] for name in hub_names])
    dst = np.stack([fitted_rest[index[name]] for name in hub_names])
    src = src - src.mean(0)
    dst = dst - dst.mean(0)
    return kabsch_rotation(src, dst)


def one_to_one_bone_chains(names: list[str], parents: np.ndarray) -> list[dict[str, list[str]]]:
    chains = []
    for index, parent_index in enumerate(np.asarray(parents, dtype=np.int64)):
        if int(parent_index) < 0:
            continue
        parent_name = names[int(parent_index)]
        child_name = names[index]
        chains.append({"target": [parent_name, child_name], "capture": [parent_name, child_name]})
    return chains


def reconstruct_adapted(
    *,
    capture_positions: np.ndarray,
    capture_reference_positions: np.ndarray,
    capture_offsets: np.ndarray,
    fitted_offsets: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    hub_names: tuple[str, ...],
) -> dict[str, Any]:
    capture = np.asarray(capture_positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    cap_off = np.asarray(capture_offsets, dtype=np.float64)
    fit_off = np.asarray(fitted_offsets, dtype=np.float64)
    # The mesh already represents idle. Donor rest is not that captured posture.
    # This asset-wide reference must be shared across clips, never taken from
    # the current clip's first frame implicitly.
    capture_rest = np.asarray(capture_reference_positions, dtype=np.float64).copy()
    if capture_rest.shape != (len(parent), 3) or not np.isfinite(capture_rest).all():
        raise ValueError("capture reference must be finite [J,3] positions")
    if capture.ndim != 3 or capture.shape[1:] != capture_rest.shape or not len(capture) or not np.isfinite(capture).all():
        raise ValueError("capture must be nonempty finite [T,J,3] positions")
    if len(names) != len(parent) or parent[0] != -1 or any(p < 0 or p >= i for i, p in enumerate(parent[1:], 1)):
        raise ValueError("capture reference requires matching names and root-first ordered hierarchy")
    reference_offsets = capture_rest - capture_rest[parent.clip(0)]
    if cap_off.shape != capture_rest.shape or not np.isfinite(cap_off).all():
        raise ValueError("capture offsets must be finite [J,3]")
    coincident = np.linalg.norm(cap_off, axis=1) <= 1e-8
    reference_lengths = np.linalg.norm(reference_offsets, axis=1)
    if np.any((reference_lengths[1:] <= 1e-8) & ~coincident[1:]):
        raise ValueError("capture reference contains zero-length bones")
    # Structural coincident hubs have no observable direction, unlike a
    # collapsed anatomical bone. Keep their target offset at its fitted rest.
    captured_lengths = np.linalg.norm(capture - capture[:, parent.clip(0)], axis=2)
    if np.any(captured_lengths[:, coincident] > 1e-8) or np.any(reference_lengths[coincident] > 1e-8):
        raise ValueError("structurally coincident capture hubs separated")
    observable = (parent >= 0) & ~coincident
    if np.any(captured_lengths[:, observable] <= 1e-8):
        raise ValueError("capture contains collapsed observable bones")
    fitted_rest = compute_rest_joints(fit_off, parent)
    rotation = whole_body_rotation(capture_rest, fitted_rest, names, hub_names)
    rest_off = fit_off.copy()
    rest_off[0] = 0.0
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], len(parent), axis=0)
    cap_off_fk = reference_offsets.copy()
    cap_off_fk[0] = 0.0
    mapped_capture = np.einsum("ij,tfj->tfi", rotation, capture - capture_rest[0]) + fitted_rest[0]
    chains = one_to_one_bone_chains(names, parent)
    unobservable = {names[i] for i in range(1, len(names)) if coincident[i]}
    # A zero vector has no swing angle. Exclude structural hubs from both
    # correspondence and motion metrics rather than counting phantom motion.
    chains = [chain for chain in chains if chain["capture"][-1] not in unobservable]
    retargeted = retarget_clip(
        capture_positions=capture,
        capture_rest=capture_rest,
        capture_names=names,
        capture_parents=parent,
        target_names=names,
        target_parents=parent,
        target_rest_local_rotation=rest_local,
        target_rest_local_translation=rest_off,
        target_rest_world=fitted_rest,
        chains=chains,
    )
    local = np.asarray(retargeted["sourceLocalRotation"], dtype=np.float64)
    capture_locals = []
    desired_cap = np.zeros((len(capture), len(parent), 3), dtype=np.float64)
    for frame in range(len(capture)):
        for index, parent_index in enumerate(parent):
            if int(parent_index) < 0:
                continue
            desired_cap[frame, index] = _unit(capture[frame, index] - capture[frame, int(parent_index)])
        capture_locals.append(
            reconstruct_frame_locals(
                desired=desired_cap[frame],
                rest_local=rest_local,
                rest_off=cap_off_fk,
                parents=parent,
                root_world=capture_rest[0],
            )
        )
    local_cap = np.stack(capture_locals)
    capture_frame0_from_rest = float(np.linalg.norm(capture[0] - capture_rest, axis=1).max())
    initial_directions = capture[0] - capture[0, parent.clip(0)]
    initial_lengths = np.linalg.norm(initial_directions, axis=1)
    cosine = np.sum(initial_directions[observable] * reference_offsets[observable], axis=1)
    cosine /= initial_lengths[observable] * reference_lengths[observable]
    initial_direction_error = float(np.arccos(np.clip(cosine, -1.0, 1.0)).max())
    frame0_identity = bool(float(np.abs(local[0] - np.eye(3)[None]).max()) < 1e-5)
    rest_len = np.linalg.norm(rest_off, axis=1)
    root_travel = np.einsum("ij,fj->fi", rotation, capture[:, 0] - capture_rest[0])
    worlds = np.asarray(retargeted["jointWorld"], dtype=np.float64).copy()
    worlds[:, :, :3, 3] = worlds[:, :, :3, 3] + root_travel[:, None, :]
    lengths = []
    for frame in range(len(capture)):
        lengths.append(np.linalg.norm(worlds[frame, :, :3, 3] - worlds[frame, parent.clip(0), :3, 3], axis=1))
    pos = worlds[:, :, :3, 3]
    residual = np.linalg.norm(pos - mapped_capture, axis=-1)
    length_err = np.abs(np.stack(lengths)[:, parent >= 0] - rest_len[parent >= 0])
    angles = so3_geodesic_angle(local.reshape(-1, 3, 3), local_cap.reshape(-1, 3, 3)).reshape(len(capture), len(parent))
    local_from_ident = so3_geodesic_angle(
        local.reshape(-1, 3, 3),
        np.repeat(np.eye(3)[None], local.shape[0] * local.shape[1], axis=0),
    ).reshape(len(capture), len(parent))
    return {
        "localRotation": local,
        "localTranslation": np.repeat(rest_off[None, :, :], len(capture), axis=0),
        "jointWorld": worlds,
        "positions": pos,
        "mappedCapture": mapped_capture,
        "wholeBodyRotation": rotation,
        "residualVsMappedCaptureMax": float(residual.max()),
        "residualVsMappedCaptureMean": float(residual.mean()),
        "fixedLengthErrorMax": float(length_err.max()),
        "angularVsCaptureMeanRad": float(angles.mean()),
        "angularVsCaptureMaxRad": float(angles.max()),
        "frame0LocalFromIdentityMaxRad": float(local_from_ident[0].max()),
        "clipFrame0IsBind": bool(frame0_identity),
        "captureFrame0FromRestMax": capture_frame0_from_rest,
        "captureFrame0DirectionFromReferenceMaxRad": initial_direction_error,
        "notExactJointReplay": True,
        "twistPolicy": TWIST_POLICY,
        "proportionDifferenceNotOverlap": True,
        "captureRest": capture_rest,
        "fittedRest": fitted_rest,
        "motionPreservation": retargeted["motionPreservation"],
        "usedWorldDirectionMatching": False,
        "unobservableDirectionJoints": [names[i] for i in range(1, len(names)) if coincident[i]],
    }
