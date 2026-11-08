"""Explicit anatomical initialization for diagnostic skin-only refits.

Preserves unmasked rows, geometry, and joints. The shared refit runner uses
this initializer only when profile chain regions are explicitly selected.
Generated candidates still require separate visual and delivery validation.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def initialize_chain_weights(
    vertices: Any,
    joint_positions: Any,
    chain_joint_ids: Any,
    parents: Any,
    region_mask: Any,
    initial_weights: Any,
) -> dict[str, Any]:
    """Initialize masked vertices from the nearest two chain features.

    Each non-terminal segment contributes a point-to-segment feature owned by
    its start joint; the terminal joint contributes a point feature owned by
    the final chain joint.  Feature weights are inverse squared distances
    using a fixed one-percent median-segment-length regularizer.
    """
    v = np.asarray(vertices)
    joints = np.asarray(joint_positions)
    chain = np.asarray(chain_joint_ids)
    parent = np.asarray(parents)
    mask = np.asarray(region_mask)
    weights = np.asarray(initial_weights)
    if (v.ndim != 2 or v.shape[1] != 3 or not len(v)
            or not np.issubdtype(v.dtype, np.number) or not np.isfinite(v).all()):
        raise ValueError("vertices must be finite numeric [N,3]")
    if (joints.ndim != 2 or joints.shape[1] != 3 or not len(joints)
            or not np.issubdtype(joints.dtype, np.number) or not np.isfinite(joints).all()):
        raise ValueError("joint_positions must be finite numeric [J,3]")
    if (chain.ndim != 1 or len(chain) < 2 or not np.issubdtype(chain.dtype, np.integer)
            or len(np.unique(chain)) != len(chain) or np.any(chain < 0)
            or np.any(chain >= len(joints))):
        raise ValueError("chain_joint_ids must be unique integer ids of length >= 2")
    if (parent.ndim != 1 or len(parent) != len(joints)
            or not np.issubdtype(parent.dtype, np.integer)
            or np.any((parent < -1) | (parent >= len(joints)))):
        raise ValueError("parents must be integer [J] with -1 or valid ids")
    if mask.shape != (len(v),) or mask.dtype != np.bool_:
        raise ValueError("region_mask must be boolean [N]")
    if (weights.ndim != 2 or weights.shape != (len(v), len(joints))
            or not np.issubdtype(weights.dtype, np.number)
            or not np.isfinite(weights).all() or np.any(weights < 0)
            or not np.allclose(weights.sum(axis=1), 1.0, atol=1e-6, rtol=0)):
        raise ValueError("initial_weights must be finite, non-negative, normalized [N,J]")
    if np.any(parent[chain[1:]] != chain[:-1]):
        raise ValueError("chain_joint_ids must follow direct parent relationships")

    starts = joints[chain[:-1]]
    ends = joints[chain[1:]]
    vectors = ends - starts
    lengths = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths <= 0):
        raise ValueError("chain segments must have finite non-zero length")
    median_length = float(np.median(lengths))
    regularizer = 0.01 * median_length
    regularizer_sq = regularizer * regularizer

    result = weights.astype(np.float64, copy=True)
    masked_ids = np.flatnonzero(mask)
    if len(masked_ids):
        points = v[masked_ids]
        delta = points[:, None, :] - starts[None, :, :]
        denom = np.einsum("sC,sC->s", vectors, vectors)
        projection = np.einsum("nsc,sc->ns", delta, vectors) / denom[None, :]
        projection = np.clip(projection, 0.0, 1.0)
        nearest = starts[None, :, :] + projection[:, :, None] * vectors[None, :, :]
        distances_sq = np.einsum("nsc,nsc->ns", points[:, None, :] - nearest,
                                 points[:, None, :] - nearest)
        terminal_delta = points - joints[chain[-1]]
        feature_distances_sq = np.concatenate(
            (distances_sq, np.einsum("nc,nc->n", terminal_delta, terminal_delta)[:, None]), axis=1
        )
        feature_owners = np.concatenate((chain[:-1], chain[-1:])).astype(np.int64)
        order = np.argsort(feature_distances_sq, axis=1, kind="stable")[:, :2]
        scores = 1.0 / (feature_distances_sq[np.arange(len(points))[:, None], order] + regularizer_sq)
        scores /= scores.sum(axis=1, keepdims=True)
        result[masked_ids] = 0.0
        for row, vertex_id in enumerate(masked_ids):
            result[vertex_id, feature_owners[order[row]]] = scores[row]

    return {
        "weights": result,
        "report": {
            "schema": "anatomical-chain-skin-diagnostic-v1",
            "maskedVertexCount": int(len(masked_ids)),
            "featureCount": int(len(chain)),
            "chainJointIds": chain.astype(int).tolist(),
            "medianSegmentLength": median_length,
            "distanceRegularizerFraction": 0.01,
            "distanceRegularizer": regularizer,
            "nearestFeatureCount": 2,
            "maskedOnly": True,
            "accepted": False,
        },
    }


def _require_body_label_adjacency(skin, prop, label, target_label):
    """Reject stale-label islands with no non-prop topology contact to target."""
    vertices = np.asarray(skin["vertices"])
    triangles = np.asarray(skin["triangles"])
    labels = np.asarray(skin["regions"]).astype(str)
    body = ~prop
    stale = set(np.flatnonzero(body & (labels == label)).tolist())
    target = set(np.flatnonzero(body & (labels == target_label)).tolist())
    if not stale:
        return
    adjacency = {int(vertex): set() for vertex in np.flatnonzero(body)}
    for triangle in triangles:
        if not np.all(body[triangle]):
            continue
        for left, right in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            left, right = int(left), int(right)
            adjacency[left].add(right)
            adjacency[right].add(left)
    welds = {}
    for vertex in np.flatnonzero(body):
        welds.setdefault(tuple(vertices[vertex].tolist()), []).append(int(vertex))
    for members in welds.values():
        for vertex in members:
            adjacency[vertex].update(members)
    visited = set()
    for start in sorted(stale):
        if start in visited:
            continue
        component = set()
        stack = [start]
        visited.add(start)
        while stack:
            vertex = stack.pop()
            component.add(vertex)
            for neighbor in adjacency[vertex]:
                if neighbor in stale and neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        boundary = set().union(*(adjacency[vertex] for vertex in component)) - component
        if not boundary & target:
            raise ValueError("routed body label has a disconnected topology island")


def initialize_profile_chains(skin, selected_faces, profile, regions, *, schema="profile-chain-initialization-v1"):
    """Apply explicitly selected profile chains while freezing attachment rows."""
    if schema not in ("profile-chain-initialization-v1", "profile-chain-initialization-v2"):
        raise ValueError("unsupported profile-chain initialization schema")
    if not isinstance(regions, (tuple, list)) or any(not isinstance(r, str) or not r for r in regions):
        raise ValueError("regions must be an explicit list of names")
    if len(set(regions)) != len(regions):
        raise ValueError("duplicate chain regions")
    faces = np.asarray(skin["triangles"])
    selected = np.asarray(selected_faces)
    if selected.ndim != 1 or selected.dtype.kind not in "iu" or np.any(selected < 0) or np.any(selected >= len(faces)):
        raise ValueError("selected faces must be valid integer IDs")
    prop = np.zeros(len(skin["vertices"]), dtype=bool)
    prop[np.unique(faces[selected])] = True
    weights = skin["weights"].copy()
    names = list(skin["names"])
    if len(set(names)) != len(names):
        raise ValueError("joint names must be unique")
    joints = np.linalg.inv(skin["inverseBind"])[:, :3, 3]
    evidence = []
    for region in regions:
        chains = [c for c in profile["chains"] if c["name"] == region and c["kind"] == "polyline"]
        if len(chains) != 1:
            raise ValueError("region must name exactly one profile polyline chain")
        chain = chains[0]
        mask = (skin["regions"] == region) & ~prop
        if not mask.any():
            raise ValueError("requested region has no body vertices")
        result = initialize_chain_weights(skin["vertices"], joints,
            np.asarray([names.index(name) for name in chain["donor"]]),
            skin["parents"], mask, weights)
        weights = result["weights"]
        evidence.append({"region": region, "jointNames": list(chain["donor"]), "initializer": result["report"]})
    if not np.array_equal(weights[prop], skin["weights"][prop]):
        raise ValueError("anatomical initialization changed attachment weights")
    routing = {}
    if schema == "profile-chain-initialization-v2" and regions:
        names = list(skin["names"])
        rigid = profile.get("rigidAttachments", ())
        for descriptor in rigid:
            label = descriptor.get("region")
            if not isinstance(label, str) or label not in set(np.asarray(skin["regions"])[prop].astype(str)):
                continue
            donor = descriptor.get("donorJoints")
            if not isinstance(donor, (tuple, list)) or len(donor) != 1 or not isinstance(donor[0], str):
                raise ValueError("selected rigid attachment donor must name exactly one joint")
            label_ids = np.flatnonzero(prop & (np.asarray(skin["regions"]).astype(str) == label))
            counts = np.count_nonzero(skin["weights"][label_ids] > 0, axis=1)
            if not len(label_ids) or np.any(counts != 1):
                raise ValueError("selected rigid attachment has non-one-hot owner evidence")
            onehot = [int(np.flatnonzero(skin["weights"][vertex] > 0)[0]) for vertex in label_ids]
            owners = sorted(set(onehot))
            if len(owners) != 1 or names[owners[0]] != donor[0]:
                raise ValueError("selected rigid attachment has ambiguous owner evidence")
            owner_name = donor[0]
            chains_for_owner = [chain for chain in profile.get("chains", ())
                                if chain.get("kind") == "polyline" and owner_name in chain.get("donor", ())]
            if len(chains_for_owner) != 1:
                if any(chain.get("name") in regions for chain in chains_for_owner) or not chains_for_owner:
                    raise ValueError("selected rigid attachment owner chain is ambiguous or missing")
                continue
            chain_name = chains_for_owner[0].get("name")
            if chain_name not in regions:
                continue
            body_mask = (np.asarray(skin["regions"]).astype(str) == label) & ~prop
            if body_mask.any():
                _require_body_label_adjacency(skin, prop, label, chain_name)
                chain_evidence = next(item for item in evidence if item["region"] == chain_name)
                chain_spec = next(chain for chain in profile["chains"] if chain.get("name") == chain_name
                                  and chain.get("kind") == "polyline")
                result = initialize_chain_weights(
                    skin["vertices"], joints,
                    np.asarray([names.index(name) for name in chain_spec["donor"]]),
                    skin["parents"], body_mask, weights)
                weights = result["weights"]
                chain_evidence["initializer"]["maskedVertexCount"] += int(body_mask.sum())
                if label in routing:
                    raise ValueError("duplicate selected rigid attachment region routing")
                routing[label] = {"chain": chain_name, "owner": owner_name,
                                  "vertexCount": int(body_mask.sum())}
    if not np.array_equal(weights[prop], skin["weights"][prop]):
        raise ValueError("anatomical initialization changed attachment weights")
    report = {"schema": schema, "regions": list(regions), "chains": evidence, "accepted": False}
    if schema == "profile-chain-initialization-v2":
        report["bodyRegionRouting"] = routing
    return {"weights": weights, "report": report}


__all__ = ["initialize_chain_weights", "initialize_profile_chains"]
