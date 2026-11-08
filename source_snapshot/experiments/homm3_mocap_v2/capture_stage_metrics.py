"""CPU-only diagnostics for the capture-to-FK stages.

This module deliberately does not write artifacts or choose a production stage.  It
keeps the raw capture as the comparison authority and reports the consequences of
each reconstruction independently.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

try:  # Supports both package imports and the experiment's script-style imports.
    from .direction_retarget import reconstruct_frame_locals
    from .mesh_preview import fk_world_matrices
    from .reconstruct_adapted import reconstruct_adapted
except ImportError:  # pragma: no cover - exercised by existing script entrypoints
    from direction_retarget import reconstruct_frame_locals
    from mesh_preview import fk_world_matrices
    from reconstruct_adapted import reconstruct_adapted


_EPS = 1.0e-8
_STAGE_NAMES = (
    "raw",
    "fixed_lengths_independent_edges",
    "unsmoothed_same_rest_fk",
    "current_same_rest_fk",
)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return np.zeros(3, dtype=np.float64) if n <= _EPS else np.asarray(v, dtype=np.float64) / n


def _json_number(value: float) -> float:
    if not np.isfinite(value):
        raise ValueError('nonfinite diagnostic metric')
    return float(value)


def _validate(
    capture: np.ndarray,
    reference: np.ndarray,
    capture_offsets: np.ndarray,
    parents: np.ndarray,
    names: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    cap = np.asarray(capture, dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    offsets = np.asarray(capture_offsets, dtype=np.float64)
    parent = np.asarray(parents)
    if parent.dtype.kind not in 'iu':
        raise ValueError('parents must be integer indices')
    parent = parent.astype(np.int64)
    names_out = [str(x) for x in names]
    if cap.ndim != 3 or cap.shape[0] < 1 or cap.shape[2:] != (3,):
        raise ValueError(f"capture must be finite [T,J,3], got {cap.shape}")
    joints = cap.shape[1]
    if ref.shape != (joints, 3) or offsets.shape != (joints, 3):
        raise ValueError("reference and capture_offsets must be [J,3] matching capture")
    if parent.shape != (joints,) or len(names_out) != joints:
        raise ValueError("parents and names must match capture joint count")
    if len(set(names_out)) != joints:
        raise ValueError('joint names must be unique')
    if not np.isfinite(cap).all() or not np.isfinite(ref).all() or not np.isfinite(offsets).all():
        raise ValueError("capture, reference, and capture_offsets must be finite")
    if joints == 0 or int(parent[0]) != -1:
        raise ValueError("hierarchy must be nonempty and root-first with parents[0] == -1")
    for index, value in enumerate(parent[1:], 1):
        if int(value) < 0 or int(value) >= index:
            raise ValueError("hierarchy must be root-first, acyclic, and parent-before-child")
    # The root of each position representation is the coordinate origin for rest
    # offsets; root travel remains explicit in the raw and FK stages.
    return cap, ref, offsets, parent, names_out


def _edge_dirs(positions: np.ndarray, parent: np.ndarray) -> np.ndarray:
    out = np.zeros_like(positions, dtype=np.float64)
    for joint, p in enumerate(parent):
        if int(p) >= 0:
            out[:, joint] = np.asarray([_unit(frame[joint] - frame[int(p)]) for frame in positions])
    return out


def _fixed_edges(raw: np.ndarray, lengths: np.ndarray, parent: np.ndarray) -> np.ndarray:
    out = np.zeros_like(raw, dtype=np.float64)
    out[:, 0] = raw[:, 0]
    for joint, p in enumerate(parent[1:], 1):
        p = int(p)
        for frame in range(raw.shape[0]):
            delta = raw[frame, joint] - raw[frame, p]
            direction = _unit(delta)
            # A structural zero from capture_offsets is the only legal zero edge.
            out[frame, joint] = out[frame, p] + direction * lengths[joint]
    return out


def _stage_metrics(
    positions: np.ndarray,
    raw: np.ndarray,
    reference: np.ndarray,
    parent: np.ndarray,
    names: Sequence[str],
    structural_zero: np.ndarray,
) -> dict[str, Any]:
    raw_dirs = _edge_dirs(raw, parent)
    dirs = _edge_dirs(positions, parent)
    lengths = np.linalg.norm(positions - positions[:, parent.clip(0)], axis=-1)
    reference_lengths = np.linalg.norm(reference - reference[parent.clip(0)], axis=-1)
    active = (parent >= 0) & ~structural_zero
    if np.any(active):
        delta = positions - raw
        bbox = np.ptp(reference, axis=0)
        bbox_diag = max(float(np.linalg.norm(bbox)), _EPS)
        rms = float(np.sqrt(np.mean(np.sum(delta * delta, axis=-1))) / bbox_diag)
        cos = np.clip(np.sum(dirs[:, active] * raw_dirs[:, active], axis=-1), -1.0, 1.0)
        angular = np.arccos(cos)
        ratio = lengths[:, active] / np.maximum(reference_lengths[active], _EPS)
        deviation = np.abs(lengths[:, active] - reference_lengths[active])
        ratio_values = ratio.reshape(-1)
        max_dev = float(deviation.max())
        angular_mean = float(angular.mean())
        angular_max = float(angular.max())
    else:
        rms = angular_mean = angular_max = max_dev = 0.0
        ratio_values = np.zeros(1, dtype=np.float64)
    per_bone: dict[str, dict[str, Any]] = {}
    for joint, name in enumerate(names):
        if not active[joint]:
            continue
        bone_angles = np.arccos(np.clip(np.sum(dirs[:, joint] * raw_dirs[:, joint], axis=-1), -1.0, 1.0))
        bone_ratio = lengths[:, joint] / max(float(reference_lengths[joint]), _EPS)
        per_bone[name] = {
            "jointIndex": int(joint),
            "boneAngularErrorMeanRad": _json_number(float(bone_angles.mean())),
            "boneAngularErrorMaxRad": _json_number(float(bone_angles.max())),
            "lengthRatioP05": _json_number(float(np.percentile(bone_ratio, 5))),
            "lengthRatioP50": _json_number(float(np.percentile(bone_ratio, 50))),
            "lengthRatioP95": _json_number(float(np.percentile(bone_ratio, 95))),
            "maxLengthDeviation": _json_number(float(np.max(np.abs(lengths[:, joint] - reference_lengths[joint])))),
        }
    # A parent rotation preserves all pairwise child direction dot products.
    # This diagnostic exposes branch shape changes that a single rigid parent
    # transform cannot satisfy, without treating them as a universal failure.
    per_branch: dict[str, dict[str, Any]] = {}
    reference_dirs = _edge_dirs(reference[None], parent)[0]
    for parent_index, parent_name in enumerate(names):
        children = [child for child, value in enumerate(parent) if int(value) == parent_index and active[child]]
        discrepancies: list[float] = []
        raw_reference_discrepancies = []
        for left_slot, left in enumerate(children):
            for right in children[left_slot + 1 :]:
                reference_dot = np.sum(raw_dirs[:, left] * raw_dirs[:, right], axis=-1)
                stage_dot = np.sum(dirs[:, left] * dirs[:, right], axis=-1)
                discrepancies.extend(np.abs(reference_dot - stage_dot).tolist())
                raw_reference_discrepancies.extend(np.abs(reference_dot - np.dot(reference_dirs[left], reference_dirs[right])).tolist())
        if discrepancies:
            per_branch[str(parent_name)] = {
                "childJointNames": [str(names[index]) for index in children],
                "maxAbsDotDiscrepancy": _json_number(float(np.max(discrepancies))),
                "meanAbsDotDiscrepancy": _json_number(float(np.mean(discrepancies))),
                "rawVsReferenceMaxAbsDotChange": float(np.max(raw_reference_discrepancies)),
                "rawVsReferenceMeanAbsDotChange": float(np.mean(raw_reference_discrepancies)),
            }
    return {
        "jointPositionRmsNormalizedReferenceBboxDiag": _json_number(rms),
        "boneAngularErrorMeanRad": _json_number(angular_mean),
        "boneAngularErrorMaxRad": _json_number(angular_max),
        "lengthRatioP05": _json_number(float(np.percentile(ratio_values, 5))),
        "lengthRatioP50": _json_number(float(np.percentile(ratio_values, 50))),
        "lengthRatioP95": _json_number(float(np.percentile(ratio_values, 95))),
        "maxLengthDeviationFromReference": _json_number(max_dev),
        "perBone": per_bone,
        "perBranch": per_branch,
        "excludedStructuralZeroBones": [str(names[i]) for i in range(len(names)) if structural_zero[i]],
    }


def analyze(
    capture: np.ndarray,
    reference: np.ndarray,
    capture_offsets: np.ndarray,
    parents: np.ndarray,
    nameslist: Sequence[str],
    hubs: tuple[str, ...],
) -> dict[str, Any]:
    """Analyze raw, fixed-edge, unsmoothed FK, and current production FK stages."""
    cap, ref, cap_offsets, parent, names = _validate(capture, reference, capture_offsets, parents, nameslist)
    if not hubs or any(str(hub) not in names for hub in hubs):
        raise ValueError("hubs must be a nonempty tuple of names present in nameslist")
    reference_offsets = ref - ref[parent.clip(0)]
    reference_offsets[0] = 0.0
    reference_bbox_diag = float(np.linalg.norm(np.ptp(ref, axis=0)))
    if reference_bbox_diag <= _EPS:
        raise ValueError("reference bounding box must have positive diagonal")
    structural_zero = np.linalg.norm(cap_offsets, axis=1) <= _EPS
    if np.any((np.linalg.norm(reference_offsets, axis=1) <= _EPS)[1:] & ~structural_zero[1:]):
        raise ValueError("non-structural reference bone has zero length")
    raw_dirs = _edge_dirs(cap, parent)
    if np.any(np.linalg.norm(raw_dirs[:, (parent >= 0) & ~structural_zero], axis=-1) <= _EPS):
        raise ValueError("capture contains collapsed observable bones")

    fixed = _fixed_edges(cap, np.linalg.norm(reference_offsets, axis=1), parent)
    identity = np.repeat(np.eye(3, dtype=np.float64)[None], len(parent), axis=0)
    unsmoothed = []
    for frame in range(len(cap)):
        local = reconstruct_frame_locals(
            desired=raw_dirs[frame], rest_local=identity, rest_off=reference_offsets,
            parents=parent, root_world=cap[frame, 0],
        )
        world = fk_world_matrices(local_rotation=local, local_translation=reference_offsets,
                                  parents=parent, root_world=cap[frame, 0])
        unsmoothed.append(world[:, :3, 3])
    unsmoothed = np.stack(unsmoothed)
    fitted_offsets = reference_offsets.copy()
    fitted_offsets[0] = ref[0]
    current_result = reconstruct_adapted(
        capture_positions=cap, capture_reference_positions=ref, capture_offsets=cap_offsets,
        fitted_offsets=fitted_offsets, parents=parent, names=names, hub_names=tuple(hubs),
    )
    current = np.asarray(current_result["positions"], dtype=np.float64)
    if current.shape != cap.shape or not np.isfinite(current).all():
        raise ValueError("reconstruct_adapted returned invalid current positions")
    current_lengths = np.linalg.norm(current - current[:, parent.clip(0)], axis=-1)
    if np.any(np.abs(current_lengths[:, 1:] - np.linalg.norm(reference_offsets, axis=1)[1:]) > 1e-5):
        raise ValueError("current_same_rest_fk did not preserve fitted reference offsets")
    stages = {"raw": cap, "fixed_lengths_independent_edges": fixed,
              "unsmoothed_same_rest_fk": unsmoothed, "current_same_rest_fk": current}
    metrics = {name: _stage_metrics(value, cap, ref, parent, names, structural_zero)
               for name, value in stages.items()}
    return {"stages": stages, "metrics": metrics}


__all__ = ["analyze"]
