"""Build a narrowly-scoped coincident-bind candidate for serial zero edges.

Only translation-only bind matrices are supported in this diagnostic lane.
This is an in-memory diagnostic candidate only.  It intentionally refuses
branching or otherwise ambiguous coincident components instead of guessing an
owner or silently changing unrelated rig structure.
"""
from __future__ import annotations

from typing import Any, Sequence
import copy
import numpy as np


_EPS = 1.0e-8


def _fk(offsets: np.ndarray, parents: np.ndarray) -> np.ndarray:
    out = np.zeros_like(offsets, dtype=np.float64)
    for i, parent in enumerate(parents):
        p = int(parent)
        out[i] = offsets[i] if p < 0 else out[p] + offsets[i]
    return out


def _finite_shape(values: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(values)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{label} must be finite with shape {shape}")
    return array


def _neutral_error(vertices, weights, rest, inverse):
    homogeneous = np.concatenate((vertices, np.ones((len(vertices), 1))), axis=1)
    neutral = np.zeros_like(vertices)
    for joint in range(len(rest)):
        transform = np.eye(4, dtype=np.float64)
        transform[:3, 3] = rest[joint]
        neutral += weights[:, joint, None] * (homogeneous @ (transform @ inverse[joint]).T)[:, :3]
    error = float(np.max(np.abs(neutral - vertices))) if len(vertices) else 0.0
    if error > 1e-10:
        raise ValueError('neutral LBS changed vertices')
    return error


def _components(offsets: np.ndarray, parents: np.ndarray, names: Sequence[str]) -> list[tuple[list[int], int]]:
    zero = np.linalg.norm(offsets, axis=1) <= _EPS
    zero[0] = False
    children = [[] for _ in range(len(parents))]
    for child, parent in enumerate(parents):
        if int(parent) >= 0:
            children[int(parent)].append(child)
    seen: set[int] = set()
    result: list[tuple[list[int], int]] = []
    for start in range(1, len(parents)):
        if not zero[start] or start in seen or (int(parents[start]) >= 0 and zero[int(parents[start])]):
            continue
        parent = int(parents[start])
        if len(children[parent]) != 1:
            raise ValueError(f"zero-edge component has ambiguous sibling child at {names[parent]}")
        members = [parent, start]
        seen.update(members)
        current = start
        while True:
            zero_children = [child for child in children[current] if zero[child]]
            if len(zero_children) == 0:
                break
            if len(zero_children) != 1 or len(children[current]) != 1:
                # A nonterminal must have exactly one child, and it must be the
                # next coincident member. Any additional child is ambiguous.
                if len(zero_children) > 1:
                    raise ValueError(f"ambiguous zero-edge fork at {names[current]}")
                raise ValueError(f"zero-edge component has nonzero child at {names[current]}")
            child = zero_children[0]
            members.append(child)
            seen.add(child)
            current = child
        result.append((members, current))
    return result


def build_candidate(original: dict[str, Any]) -> dict[str, Any]:
    """Return a copied candidate and JSON-compatible diagnostic report."""
    required = ("vertices", "triangles", "uvs", "albedo", "names", "parents",
                "offsets", "captureOffsets", "inverseBind", "weights", "regions")
    missing = [key for key in required if key not in original]
    if missing:
        raise ValueError(f"missing required skin fields: {missing}")
    names = [str(name) for name in np.asarray(original["names"]).tolist()]
    joints = len(names)
    if len(set(names)) != joints:
        raise ValueError("names must be unique")
    parents_raw = np.asarray(original["parents"])
    if parents_raw.shape != (joints,) or not np.issubdtype(parents_raw.dtype, np.integer):
        raise ValueError("parents must be an integer [J] array")
    parents = parents_raw.astype(np.int64, copy=False)
    if joints == 0 or int(parents[0]) != -1 or any(int(p) < 0 or int(p) >= i for i, p in enumerate(parents[1:], 1)):
        raise ValueError("parents must be root-first ordered with one root")
    offsets = _finite_shape(original["offsets"], (joints, 3), "offsets").astype(np.float64)
    capture_offsets = _finite_shape(original["captureOffsets"], (joints, 3), "captureOffsets").astype(np.float64)
    rest = _fk(offsets, parents)
    if "restWorld" in original and not np.allclose(_finite_shape(original["restWorld"], (joints, 3), "restWorld"), rest, atol=1e-8, rtol=0.0):
        raise ValueError("original restWorld does not equal FK(offsets)")
    vertices = np.asarray(original["vertices"], dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite [V,3]")
    weights = _finite_shape(original["weights"], (len(vertices), joints), "weights").astype(np.float64)
    if np.any(weights < 0):
        raise ValueError("weights must be nonnegative")
    if len(weights) and not np.allclose(weights.sum(axis=1), 1.0, atol=1e-8, rtol=0.0):
        raise ValueError("weights must be normalized per vertex")
    inverse = _finite_shape(original["inverseBind"], (joints, 4, 4), "inverseBind").astype(np.float64)
    expected_inverse = np.repeat(np.eye(4, dtype=np.float64)[None], joints, axis=0)
    expected_inverse[:, :3, 3] = -rest
    if not np.allclose(inverse, expected_inverse, atol=1e-8, rtol=0.0):
        raise ValueError("inverseBind must be pure-translation inverse of FK rest")
    if 'restAnchors' in original and not np.allclose(
            _finite_shape(original['restAnchors'], (joints, 3), 'restAnchors'), rest, atol=1e-8, rtol=0.):
        raise ValueError('restAnchors differ from FK rest')
    components = _components(capture_offsets, parents, names)
    candidate = {key: copy.deepcopy(value) for key, value in original.items()}
    if not components:
        return {"skin": candidate, "report": {
            "proof": "generic_coincident_bind_candidate_not_accepted", "groups": [],
            "bindModel": "translation_only", "zeroEdgeTolerance": _EPS,
            "invariants": {"neutralLbsMaxAbsError": _neutral_error(vertices, weights, rest, inverse),
                            "sourceZeroEdgesExactZero": True, "restParityMaxAbs": 0.0,
                            "weightsNonnegative": True, "weightsTotalPreserved": True}}}
    candidate["names"] = np.asarray(original["names"]).copy()
    candidate["parents"] = parents_raw.copy()
    candidate["offsets"] = offsets.copy()
    candidate["captureOffsets"] = capture_offsets.copy()
    new_rest = rest.copy()
    new_weights = weights.copy()
    groups: list[dict[str, Any]] = []
    for members, owner in components:
        owner_point = rest[owner].copy()
        for member in members:
            new_rest[member] = owner_point
        transferred = [member for member in members if member != owner]
        reassigned = float(new_weights[:, transferred].sum())
        merged = new_weights[:, members].sum(axis=1)
        for member in members:
            new_weights[:, member] = 0.0
        new_weights[:, owner] = merged
        moved = float(np.linalg.norm(new_rest[members] - rest[members], axis=1).max())
        groups.append({"members": [names[i] for i in members], "owner": names[owner],
                       "sourceEdgeNorms": [float(np.linalg.norm(capture_offsets[i])) for i in members[1:]],
                       "movedRestSites": moved, "reassignedWeightMass": reassigned,
                       "reassignedVertexCount": int(np.count_nonzero(weights[:, transferred].sum(axis=1) > _EPS))})
    new_offsets = np.zeros_like(offsets)
    for i, parent in enumerate(parents):
        new_offsets[i] = new_rest[i] if int(parent) < 0 else new_rest[i] - new_rest[int(parent)]
    new_inverse = np.repeat(np.eye(4, dtype=np.float64)[None], joints, axis=0)
    new_inverse[:, :3, 3] = -new_rest
    candidate["offsets"] = new_offsets
    candidate["inverseBind"] = new_inverse
    candidate["weights"] = new_weights
    if "restWorld" in original:
        candidate["restWorld"] = new_rest
    if "restAnchors" in original:
        anchors = _finite_shape(original["restAnchors"], (joints, 3), "restAnchors").astype(np.float64)
        candidate["restAnchors"] = anchors.copy()
        for members, owner in components:
            candidate["restAnchors"][members] = anchors[owner]
    # Evaluate neutral LBS instead of comparing an array with itself. Every
    # candidate rest-world * inverse-bind transform must be identity.
    neutral_error = _neutral_error(vertices, new_weights, new_rest, new_inverse)
    zero = np.linalg.norm(capture_offsets, axis=1) <= _EPS
    zero[0] = False
    if np.any(new_offsets[zero] != 0.0):
        raise ValueError("source zero-edge components were not made exactly coincident")
    if not np.allclose(new_weights.sum(1), weights.sum(1), atol=1e-10, rtol=0.):
        raise ValueError('weight mass changed')
    if np.any(np.count_nonzero(new_weights > 0., axis=1) > np.count_nonzero(weights > 0., axis=1)):
        raise ValueError('skin influence count increased')
    report = {"proof": "generic_coincident_bind_candidate_not_accepted", "groups": groups,
              "bindModel": "translation_only", "zeroEdgeTolerance": _EPS,
              "invariants": {"neutralLbsMaxAbsError": neutral_error,
                              "sourceZeroEdgesExactZero": bool(np.all(new_offsets[zero] == 0.0)),
                              "restParityMaxAbs": float(np.max(np.abs(new_rest - _fk(new_offsets, parents)))),
                              "weightsNonnegative": bool(np.all(new_weights >= -_EPS)),
                              "weightsTotalPreserved": bool(np.allclose(new_weights.sum(1), weights.sum(1), atol=1e-10, rtol=0.0))}}
    return {"skin": candidate, "report": report}


__all__ = ["build_candidate"]
