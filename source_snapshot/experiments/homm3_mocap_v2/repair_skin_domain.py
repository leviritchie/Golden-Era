"""CPU-only support-domain construction for a split attachment skin refit.

This module proposes trainable vertices and joint support only.  It does not
change rest positions, triangles, or weights, and it never welds across the
explicit prop/body ownership boundary.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def _validate(vertices: Any, triangles: Any, initial_weights: Any,
              selected_face_ids: Any, neighbor_rings: int, max_influences: int):
    v = np.asarray(vertices)
    t = np.asarray(triangles)
    w = np.asarray(initial_weights)
    selected = np.asarray(selected_face_ids)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.issubdtype(v.dtype, np.number) or not np.isfinite(v).all():
        raise ValueError("vertices must be finite non-empty numeric [V,3]")
    if t.ndim != 2 or t.shape[1] != 3 or not len(t) or not np.issubdtype(t.dtype, np.integer):
        raise ValueError("triangles must be non-empty integer [F,3]")
    if np.any(t < 0) or np.any(t >= len(v)):
        raise ValueError("triangle indices are outside vertices")
    if w.ndim != 2 or w.shape[0] != len(v) or not w.shape[1] or not np.issubdtype(w.dtype, np.number):
        raise ValueError("initial_weights must be numeric [V,J]")
    if not np.isfinite(w).all() or np.any(w < 0) or not np.allclose(w.sum(axis=1), 1.0, atol=1e-6, rtol=0):
        raise ValueError("initial_weights must be finite, non-negative, and normalized")
    if selected.ndim != 1 or not np.issubdtype(selected.dtype, np.integer) or not len(selected):
        raise ValueError("selected_face_ids must be a non-empty integer vector")
    if len(np.unique(selected)) != len(selected) or np.any(selected < 0) or np.any(selected >= len(t)):
        raise ValueError("selected_face_ids must be valid and unique")
    if isinstance(neighbor_rings, (bool, np.bool_)) or not isinstance(neighbor_rings, (int, np.integer)) or not 1 <= int(neighbor_rings) <= 4:
        raise ValueError("neighbor_rings must be an integer in [1,4]")
    if isinstance(max_influences, (bool, np.bool_)) or not isinstance(max_influences, (int, np.integer)) or not 1 <= int(max_influences) <= 8:
        raise ValueError("max_influences must be an integer in [1,8]")
    return (v.astype(np.float64, copy=False), t.astype(np.int64, copy=False),
            w.astype(np.float64, copy=False), selected.astype(np.int64, copy=False),
            int(neighbor_rings), int(max_influences))


def _ownership_groups(vertices: np.ndarray, triangles: np.ndarray,
                      weights: np.ndarray, selected: np.ndarray):
    selected_mask = np.zeros(len(triangles), dtype=bool)
    selected_mask[selected] = True
    selected_vertices = set(triangles[selected].reshape(-1).tolist())
    other_vertices = set(triangles[~selected_mask].reshape(-1).tolist())
    shared = sorted(selected_vertices & other_vertices)
    if shared:
        raise ValueError(f"selected attachment still shares body vertices: {shared[:8]}")
    ownership = np.zeros(len(vertices), dtype=np.int8)
    ownership[np.asarray(sorted(selected_vertices), dtype=np.int64)] = 1
    groups_by_key: dict[tuple[int, tuple[float, float, float]], list[int]] = {}
    for index, point in enumerate(vertices):
        groups_by_key.setdefault((int(ownership[index]), tuple(point.tolist())), []).append(index)
    groups = list(groups_by_key.values())
    group_of = np.empty(len(vertices), dtype=np.int64)
    for gid, members in enumerate(groups):
        group_of[members] = gid
    prop_owner_joints: set[int] = set()
    for members in groups:
        if ownership[members[0]] != 1:
            continue
        rows = weights[members]
        if not np.all((rows > 0).sum(axis=1) == 1) or not np.allclose(rows, rows[[0]], atol=1e-6, rtol=0):
            raise ValueError("frozen prop weights must be identical one-hot rows within each weld")
        prop_owner_joints.add(int(np.argmax(rows[0])))
    return ownership, groups, group_of, prop_owner_joints


def condition_body_welds(vertices: Any, triangles: Any, weights: Any,
                         selected_face_ids: Any) -> dict[str, Any]:
    """Condition divergent body-side equal-position welds before refitting.

    Body groups are replaced by their uniform arithmetic mean, the least
    squares minimizer for one shared weight row.  Prop groups are frozen and
    must already be exact one-hot rows.  This is an explicit conditioning
    operation, never a recovery path for a failed domain proposal.
    """
    v, t, w, selected, _, _ = _validate(vertices, triangles, weights,
                                         selected_face_ids, 1, 8)
    ownership, groups, _, _ = _ownership_groups(v, t, w, selected)
    conditioned = w.copy()
    original_max = 0.0
    affected_groups = 0
    affected_vertices = 0
    for members in groups:
        if ownership[members[0]] == 1:
            continue
        rows = w[members]
        delta = float(np.max(np.abs(rows - rows[0])))
        original_max = max(original_max, delta)
        if delta > 0:
            affected_groups += 1
            affected_vertices += len(members)
        mean = rows.mean(axis=0)
        if int(np.count_nonzero(mean > 0)) > 8:
            raise ValueError("conditioned body weld support exceeds max_influences")
        conditioned[members] = mean
    return {
        "conditionedWeights": conditioned,
        "maxRowDelta": float(np.max(np.abs(conditioned - w))) if len(w) else 0.0,
        "affectedGroupCount": int(affected_groups),
        "affectedVertexCount": int(affected_vertices),
        "originalWithinWeldMaxDelta": float(original_max),
        "motionChanged": False,
        "restChanged": False,
        "accepted": False,
    }


def restore_source_owner_support(domain: dict[str, Any], vertices: Any,
                                 source_weights_mapped: Any, owner_id: int) -> dict[str, Any]:
    """Add mapped-source owner support to body weld groups without changing labels."""
    if not isinstance(domain, dict) or not isinstance(owner_id, (int, np.integer)) or isinstance(owner_id, (bool, np.bool_)):
        raise ValueError("domain must be a mapping and owner_id must be an integer")
    v = np.asarray(vertices)
    source = np.asarray(source_weights_mapped)
    required = ("ownershipIds", "trainMask", "allowedSupport")
    if any(key not in domain for key in required):
        raise ValueError("domain lacks required ownership/support arrays")
    ownership = np.asarray(domain["ownershipIds"])
    train = np.asarray(domain["trainMask"])
    support = np.asarray(domain["allowedSupport"])
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.issubdtype(v.dtype, np.number) or not np.isfinite(v).all():
        raise ValueError("vertices must be finite numeric [V,3]")
    if ownership.shape != (len(v),) or ownership.dtype.kind not in "iu" or np.any((ownership != 0) & (ownership != 1)):
        raise ValueError("ownershipIds must be binary integer [V]")
    if train.shape != (len(v),) or train.dtype != np.bool_:
        raise ValueError("trainMask must be boolean [V]")
    if np.any(train != (ownership == 0)):
        raise ValueError("trainMask must agree with body/prop ownership")
    if source.ndim != 2 or source.shape[0] != len(v) or not source.shape[1] or not np.issubdtype(source.dtype, np.number):
        raise ValueError("source_weights_mapped must be numeric [V,J]")
    if not np.isfinite(source).all() or np.any(source < 0) or not np.allclose(source.sum(axis=1), 1.0, atol=1e-6, rtol=0):
        raise ValueError("source_weights_mapped must be finite, non-negative, and normalized")
    if support.shape != source.shape or support.dtype != np.bool_:
        raise ValueError("allowedSupport must be boolean and match source weights")
    if owner_id < 0 or owner_id >= source.shape[1]:
        raise ValueError("owner_id is outside joint range")
    if np.any(support.sum(axis=1) > 8) or np.any(support.sum(axis=1) == 0):
        raise ValueError("initial support must contain one to eight influences")
    expanded = support.copy()
    groups: dict[tuple[int, tuple[float, float, float]], list[int]] = {}
    for index, point in enumerate(v):
        groups.setdefault((int(ownership[index]), tuple(point.tolist())), []).append(index)
    added_groups = 0
    added_vertices = 0
    evidence_groups = 0
    for members in groups.values():
        if ownership[members[0]] != 0:
            continue
        if not np.all(train[members]):
            raise ValueError("body weld has inconsistent trainMask")
        if not np.all(support[members] == support[members[0]]):
            raise ValueError("body weld has inconsistent allowed support")
        if np.any(source[members, owner_id] > 0):
            evidence_groups += 1
            new_rows = ~expanded[members, owner_id]
            if np.any(new_rows):
                if int(expanded[members[0]].sum()) >= 8:
                    raise ValueError("restored owner support exceeds max influences")
                expanded[members, owner_id] = True
                added_groups += 1
                added_vertices += int(np.count_nonzero(new_rows))
    result = dict(domain)
    result["allowedSupport"] = expanded
    result["report"] = dict(domain.get("report", {}), sourceOwnerSupportEvidenceGroups=int(evidence_groups),
                             sourceOwnerSupportAddedGroups=int(added_groups),
                             sourceOwnerSupportAddedVertices=int(added_vertices),
                             sourceOwnerSupportOwnerId=int(owner_id))
    return result


def make_repair_domain(vertices: Any, triangles: Any, initial_weights: Any,
                       selected_face_ids: Any, *, neighbor_rings: int = 1,
                       max_influences: int = 8, source_weights_mapped: Any = None,
                       owner_id: int | None = None) -> dict[str, Any]:
    """Build an explicit body-train/prop-frozen support proposal."""
    v, t, initial, selected, rings, limit = _validate(
        vertices, triangles, initial_weights, selected_face_ids,
        neighbor_rings, max_influences)
    ownership, groups, group_of, prop_owner_joints = _ownership_groups(v, t, initial, selected)
    if (source_weights_mapped is None) != (owner_id is None):
        raise ValueError("source_weights_mapped and owner_id must be provided together")
    for members in groups:
        if ownership[members[0]] == 0 and not np.allclose(initial[members], initial[members[0]], atol=1e-6, rtol=0):
            raise ValueError("divergent initial weights within a train weld")
    prop_groups = [group for group in groups if ownership[group[0]] == 1]
    required_support = initial > 0
    source_report: dict[str, Any] = {}
    if source_weights_mapped is not None:
        restored = restore_source_owner_support(
            {"ownershipIds": ownership, "trainMask": ownership == 0,
             "allowedSupport": required_support}, v, source_weights_mapped, owner_id)
        required_support = restored["allowedSupport"]
        source_report = restored["report"]

    train_groups = [group for group in groups if ownership[group[0]] == 0]
    train_group_ids = {gid for gid, group in enumerate(groups) if ownership[group[0]] == 0}
    adjacency = {gid: set() for gid in train_group_ids}
    # Only body triangles contribute neighbors; UV seams share exact endpoint
    # groups, while prop-only edges cannot connect otherwise separate regions.
    edge_groups: dict[tuple[tuple[float, float, float], tuple[float, float, float]], set[int]] = {}
    for tri in t:
        if not np.all(ownership[tri] == 0):
            continue
        for left, right in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            a, b = tuple(v[int(left)].tolist()), tuple(v[int(right)].tolist())
            key = tuple(sorted((a, b)))
            edge_groups.setdefault(key, set()).update((int(group_of[left]), int(group_of[right])))
    for edge_group_ids in edge_groups.values():
        for left in edge_group_ids:
            for right in edge_group_ids:
                if left != right and left in train_group_ids and right in train_group_ids:
                    adjacency[left].add(right)

    allowed = np.zeros_like(initial, dtype=bool)
    dropped = 0
    truncated = []
    for gid, members in ((gid, group) for gid, group in enumerate(groups) if ownership[group[0]] == 0):
        base = set(np.flatnonzero(required_support[members[0]]).tolist())
        if len(base) > limit:
            raise ValueError("initial support exceeds max_influences")
        scores: dict[int, list[float]] = {}
        distance = {gid: 0}
        queue: deque[int] = deque([gid])
        while queue:
            current = queue.popleft()
            if distance[current] >= rings:
                continue
            for neighbor in sorted(adjacency[current]):
                if neighbor not in distance:
                    distance[neighbor] = distance[current] + 1
                    queue.append(neighbor)
        for neighbor, depth in distance.items():
            if neighbor == gid or depth > rings:
                continue
            neighbor_rows = groups[neighbor]
            for joint, score in enumerate(initial[neighbor_rows].mean(axis=0)):
                if joint not in prop_owner_joints:
                    scores.setdefault(joint, []).append(float(score))
        candidates = sorted(((float(np.mean(values)), joint) for joint, values in scores.items()
                             if joint not in base and float(np.mean(values)) > 0),
                            key=lambda item: (-item[0], item[1]))
        available = max(0, limit - len(base))
        chosen = base | {joint for _, joint in candidates[:available]}
        dropped += max(0, len(candidates) - available)
        if len(candidates) > available:
            truncated.append({"weldId": int(gid), "candidateCount": len(candidates), "keptCount": available})
        for member in members:
            allowed[member, sorted(chosen)] = True
    for members in prop_groups:
        prop_joint = int(np.argmax(initial[members[0]]))
        allowed[members, prop_joint] = True

    return {
        "ownershipIds": ownership,
        "trainMask": ownership == 0,
        "allowedSupport": allowed,
        "report": {
            "schema": "repair-skin-domain-v1",
            "selectedFaceCount": int(len(selected)),
            "propVertexCount": int(np.count_nonzero(ownership == 1)),
            "trainVertexCount": int(np.count_nonzero(ownership == 0)),
            "trainWeldCount": int(len(train_groups)),
            "propWeldCount": int(len(prop_groups)),
            "neighborRings": rings,
            "maxInfluences": limit,
            "propOwnerJointIds": sorted(prop_owner_joints),
            "droppedNeighborCandidateCount": int(dropped),
            "truncatedWelds": truncated,
            "initialSupportNeverRemoved": True,
            **source_report,
            "motionChanged": False,
            "meshChanged": False,
            "accepted": False,
        },
    }


__all__ = ["condition_body_welds", "make_repair_domain", "restore_source_owner_support"]
