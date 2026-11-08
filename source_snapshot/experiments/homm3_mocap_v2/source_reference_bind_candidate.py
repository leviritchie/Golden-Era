"""Build an in-memory source-reference similarity bind candidate.

This is deliberately a single rigid similarity fit.  It is not a per-bone
registration or a replacement for a frozen preparation artifact.
"""
from __future__ import annotations

import copy
from typing import Any, Sequence

import numpy as np

from coincident_bind_candidate import build_candidate


_EPS = 1.0e-8


def _finite_points(value: Any, joints: int, label: str) -> np.ndarray:
    points = np.asarray(value, dtype=np.float64)
    if points.shape != (joints, 3) or not np.isfinite(points).all():
        raise ValueError(f"{label} must be finite with shape {(joints, 3)}")
    return points.copy()


def _similarity(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float]:
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    source_centered = source - source_center
    target_centered = target - target_center
    denom = float(np.sum(source_centered * source_centered))
    if denom <= _EPS:
        raise ValueError("source reference hubs are collapsed")
    u, singular, vt = np.linalg.svd(source_centered.T @ target_centered)
    q = vt.T @ u.T
    if float(np.linalg.det(q)) < 0.0:
        vt[-1, :] *= -1.0
        q = vt.T @ u.T
    if float(np.linalg.det(q)) <= 0.0:
        raise ValueError("similarity fit would require a reflection")
    # Recompute the signed least-squares numerator after the determinant
    # correction.  The nuclear norm is only equivalent before a reflection
    # correction; using it afterwards silently overstates scale on mirrored
    # targets.
    scale = float(np.sum(source_centered * (target_centered @ q)) / denom)
    if not np.isfinite(scale) or scale <= _EPS:
        raise ValueError("similarity fit produced a non-positive scale")
    transformed = scale * (source_centered @ q.T) + target_center
    residual = float(np.max(np.linalg.norm(transformed - target, axis=1)))
    return scale, q, target_center - scale * (q @ source_center), residual


def _local_offsets(rest: np.ndarray, parents: np.ndarray) -> np.ndarray:
    offsets = np.empty_like(rest)
    for index, parent in enumerate(parents):
        offsets[index] = rest[index] if int(parent) < 0 else rest[index] - rest[int(parent)]
    return offsets


def build_source_reference_candidate(
    existing: dict[str, Any], reference_positions: Any, hub_names: Sequence[str]
) -> dict[str, Any]:
    """Return a canonicalized candidate fitted by one positive similarity transform.

    The input dictionary and all of its arrays remain untouched.  No artifact
    or freeze file is written.
    """
    # Canonicalize source-coincident owners before changing the world rest.
    base_result = build_candidate(existing)
    base = base_result["skin"]
    names = [str(name) for name in np.asarray(base["names"]).tolist()]
    index = {name: i for i, name in enumerate(names)}
    hubs = [str(name) for name in hub_names]
    if not hubs or len(set(hubs)) != len(hubs) or any(name not in index for name in hubs):
        raise ValueError("hub_names must contain unique existing joint names")
    parents = np.asarray(base["parents"], dtype=np.int64)
    reference = _finite_points(reference_positions, len(names), "reference_positions")

    # A source-zero edge is a structural coincidence, not a license to invent
    # a separated reference position for that child.
    capture = np.asarray(base["captureOffsets"], dtype=np.float64)
    for child in range(1, len(names)):
        parent = int(parents[child])
        if np.linalg.norm(capture[child]) <= _EPS and np.linalg.norm(reference[child] - reference[parent]) > _EPS:
            raise ValueError(f"source-zero reference edge is separated: {names[child]}")
        if np.linalg.norm(capture[child]) > _EPS and np.linalg.norm(reference[child] - reference[parent]) <= _EPS:
            raise ValueError(f'observable reference edge collapsed: {names[child]}')

    # The target is always the original fitted rest, never a possibly stale
    # serialized restWorld field from the candidate input.
    original_rest = np.zeros((len(names), 3), dtype=np.float64)
    original_offsets = np.asarray(existing["offsets"], dtype=np.float64)
    for i, parent in enumerate(parents):
        original_rest[i] = original_offsets[i] if int(parent) < 0 else original_rest[int(parent)] + original_offsets[i]
    source_hubs = reference[[index[name] for name in hubs]]
    target_hubs = original_rest[[index[name] for name in hubs]]
    if np.linalg.matrix_rank(source_hubs - source_hubs.mean(axis=0), tol=_EPS) < 2:
        raise ValueError("source reference hubs have fewer than two observable dimensions")
    scale, rotation, translation, residual = _similarity(source_hubs, target_hubs)
    source_center = source_hubs.mean(axis=0)
    target_center = target_hubs.mean(axis=0)
    rest = scale * (reference - source_center) @ rotation.T + target_center
    offsets = _local_offsets(rest, parents)
    inverse = np.repeat(np.eye(4, dtype=np.float64)[None], len(names), axis=0)
    inverse[:, :3, 3] = -rest

    candidate = {key: copy.deepcopy(value) for key, value in base.items()}
    candidate["restWorld"] = rest
    candidate["restAnchors"] = rest.copy()
    candidate["offsets"] = offsets
    candidate["inverseBind"] = inverse

    # Neutral parity is a hard gate: the candidate must not alter the visible
    # surface before any motion is applied.
    vertices = np.asarray(candidate["vertices"], dtype=np.float64)
    weights = np.asarray(candidate["weights"], dtype=np.float64)
    homogeneous = np.concatenate((vertices, np.ones((len(vertices), 1))), axis=1)
    neutral = np.zeros_like(vertices)
    for joint in range(len(rest)):
        transform = np.eye(4, dtype=np.float64)
        transform[:3, 3] = rest[joint]
        neutral += weights[:, joint, None] * (homogeneous @ (transform @ inverse[joint]).T)[:, :3]
    neutral_error = float(np.max(np.abs(neutral - vertices))) if len(vertices) else 0.0
    if neutral_error > 1.0e-10:
        raise ValueError(f"neutral LBS changed vertices: {neutral_error}")

    report = {
        "proof": "source_reference_bind_candidate_not_accepted",
        "bindModel": "single_rigid_positive_similarity",
        "hubNames": hubs,
        "transform": {"scale": scale, "rotation": rotation.tolist(), "translation": translation.tolist()},
        "similarityResidualMax": residual,
        "sourceZeroTolerance": _EPS,
        "coincidentPreparation": copy.deepcopy(base_result["report"]),
        "invariants": {"neutralLbsMaxAbsError": neutral_error, "reflection": False,
                        "positiveScale": True, "canonicalized": bool(base_result["report"]["groups"]),
                        "sourceInputImmutable": True},
    }
    return {"skin": candidate, "report": report}


__all__ = ["build_source_reference_candidate"]
