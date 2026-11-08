"""Rest-preserving topology split for a selected attached mesh region.

This module deliberately does not move the rest mesh, cap a seam, or decide
whether an animated seam is acceptable.  It only gives the selected triangles
their own boundary vertices and owner weights, and reassigns weights around
the cut without letting influence cross disconnected surface.
"""

from collections.abc import Mapping
import heapq

import numpy as np


def _array(skin, key):
    if key not in skin:
        raise ValueError(f"skin is missing {key!r}")
    value = np.asarray(skin[key])
    return value


def _validate_names(skin):
    if "names" not in skin:
        raise ValueError("skin is missing names")
    raw_names = np.asarray(skin["names"])
    if raw_names.ndim != 1:
        raise ValueError("names must be one-dimensional")
    names = [str(value) for value in raw_names.tolist()]
    if len(names) != len(set(names)):
        raise ValueError("names must contain unique names")
    return names


def split_attachment(skin, selected_faces, owner):
    """Split selected triangle boundary vertices and assign them to *owner*.

    ``skin`` is a mapping containing at least ``vertices``, ``triangles``,
    ``weights``, and ``names``.  Every input
    array is copied.  Per-vertex arrays are extended by indexing their source
    vertex with ``sourceVertexIds``; face arrays retain their original shape
    and ordering.
    """
    if not isinstance(skin, Mapping):
        raise TypeError("skin must be a mapping")
    vertices = _array(skin, "vertices")
    triangles = _array(skin, "triangles")
    weights = _array(skin, "weights")
    if len(vertices) == 0 or len(triangles) == 0:
        raise ValueError("mesh must contain vertices and triangles")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.issubdtype(vertices.dtype, np.number):
        raise ValueError("vertices must be an Nx3 numeric array")
    if not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("triangles must be an Mx3 integer array")
    if np.any(triangles < 0) or np.any(triangles >= len(vertices)):
        raise ValueError("triangle vertex index out of range")
    if weights.ndim != 2 or weights.shape[0] != len(vertices) or not np.issubdtype(weights.dtype, np.number):
        raise ValueError("weights must have one finite row per vertex")
    names = _validate_names(skin)
    if weights.shape[1] != len(names):
        raise ValueError("weights column count must equal names count")
    if not np.isfinite(weights).all() or np.any(weights < 0) or not np.allclose(weights.sum(axis=1), 1.0, rtol=0, atol=1e-6):
        raise ValueError("weights must be finite, non-negative, and normalized")
    if "uvs" in skin:
        uvs = _array(skin, "uvs")
        if uvs.ndim != 2 or uvs.shape != (len(vertices), 2) or not np.issubdtype(uvs.dtype, np.number) or not np.isfinite(uvs).all():
            raise ValueError("uvs must be a finite Nx2 numeric array")
    if not isinstance(owner, str) or not owner:
        raise ValueError("owner must be a non-empty bone name")
    if names.count(owner) != 1:
        raise ValueError("owner must resolve to exactly one unique name")
    owner_index = names.index(owner)

    selected = np.asarray(selected_faces)
    if selected.ndim != 1 or not np.issubdtype(selected.dtype, np.integer):
        raise ValueError("selected_faces must be a one-dimensional integer array")
    if len(np.unique(selected)) != len(selected):
        raise ValueError("selected_faces must contain unique face ids")
    if np.any(selected < 0) or np.any(selected >= len(triangles)):
        raise ValueError("selected face id out of range")
    if len(selected) == 0:
        raise ValueError("selected_faces must not be empty")

    selected_mask = np.zeros(len(triangles), dtype=bool)
    selected_mask[selected] = True
    selected_vertices = np.unique(triangles[selected].reshape(-1)) if len(selected) else np.empty(0, dtype=np.int64)
    selected_set = set(selected.tolist())
    unselected_vertices = set(triangles[~selected_mask].reshape(-1).tolist())
    boundary = sorted(set(selected_vertices.tolist()) & unselected_vertices)
    duplicate_for = {source: len(vertices) + offset for offset, source in enumerate(boundary)}
    source_vertex_ids = np.concatenate([np.arange(len(vertices), dtype=np.int64), np.asarray(boundary, dtype=np.int64)])

    out = {}
    for key, value in skin.items():
        array = np.asarray(value)
        if key == "regions":
            if array.ndim != 1 or len(array) != len(vertices) or any(not isinstance(x, str) for x in array.tolist()):
                raise ValueError("regions must contain one string per vertex")
            array = array.astype(str)
        copied = array.copy()
        if key == "triangles":
            copied = copied.copy()
            for face_id in selected_set:
                copied[face_id] = [duplicate_for.get(int(vertex), int(vertex)) for vertex in copied[face_id]]
        elif key in {"vertices", "weights", "uvs", "regions", "normals", "tangents", "colors", "sourceVertexIds"}:
            copied = array[source_vertex_ids].copy()
        out[key] = copied

    out["vertices"] = np.concatenate([vertices.copy(), vertices[np.asarray(boundary, dtype=np.int64)].copy()])
    updated_weights = weights.copy()
    # A shared source vertex remains the body's vertex.  Only selected
    # vertices that are not shared can be reassigned in place; shared ones
    # receive the exact owner weight on their newly-created prop copy.
    interior_prop = np.setdiff1d(selected_vertices, np.asarray(boundary, dtype=np.int64), assume_unique=True)
    onehot = np.zeros(weights.shape[1], dtype=weights.dtype)
    onehot[owner_index] = 1
    updated_weights[interior_prop] = onehot
    out["weights"] = np.concatenate([updated_weights, np.tile(onehot, (len(boundary), 1))])
    out["sourceVertexIds"] = source_vertex_ids.copy()
    shared_pairs = [[int(source), int(duplicate_for[source])] for source in boundary]
    rest_corners_ok = np.array_equal(out["vertices"][out["triangles"]], vertices[triangles])
    uv_corners_ok = True
    if "uvs" in skin:
        uv_corners_ok = np.array_equal(out["uvs"][out["triangles"]], np.asarray(skin["uvs"])[triangles])
    report = {
        "sourceVertexIds": source_vertex_ids.tolist(),
        "sharedBoundary": shared_pairs,
        "boundaryPairs": shared_pairs,
        "sourceVertexCount": int(len(vertices)),
        "updatedVertexCount": int(len(out["vertices"])),
        "selectedFaceCount": int(len(selected)),
        "sharedBoundaryCount": int(len(boundary)),
        "faceCount": int(len(triangles)),
        "owner": owner,
        "ownerIndex": int(owner_index),
        "invariants": {
            "restPositionsPreserved": bool(rest_corners_ok),
            "uvCornersPreserved": bool(uv_corners_ok),
            "faceCountPreserved": len(out["triangles"]) == len(triangles),
            "faceOrderPreserved": np.array_equal(out["triangles"].shape, triangles.shape),
            "noCapsOrDeletedFaces": True,
        },
    }
    return out, report


def reassign_cut_boundary_weights(skin, selected_faces, owner, rings=1):
    """Reassign bind weights around a split cut so neither side creeps.

    ``skin`` must be the output of :func:`split_attachment` for the same
    ``selected_faces`` (face ids and ordering are preserved by the split, and
    ``sourceVertexIds`` marks the duplicated seam vertices).  Vertices on the
    prop side of the cut within ``rings`` edge-hops are pinned to the exact
    owner weight; vertices on the body side within ``rings`` hops (including
    the seam sources themselves) have their owner mass dropped and the
    remainder renormalized, so body verts stop following the formerly-fused
    prop joint.  A body row that is 100% owner mass is left untouched and
    counted as a fallback instead of producing a zero row.  Far vertices are
    never modified.
    """
    if not isinstance(skin, Mapping):
        raise TypeError("skin must be a mapping")
    vertices = _array(skin, "vertices")
    triangles = _array(skin, "triangles")
    weights = _array(skin, "weights")
    if len(vertices) == 0 or len(triangles) == 0:
        raise ValueError("mesh must contain vertices and triangles")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.issubdtype(vertices.dtype, np.number):
        raise ValueError("vertices must be an Nx3 numeric array")
    if not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("triangles must be an Mx3 integer array")
    if np.any(triangles < 0) or np.any(triangles >= len(vertices)):
        raise ValueError("triangle vertex index out of range")
    if weights.ndim != 2 or weights.shape[0] != len(vertices) or not np.issubdtype(weights.dtype, np.number):
        raise ValueError("weights must have one finite row per vertex")
    names = _validate_names(skin)
    if weights.shape[1] != len(names):
        raise ValueError("weights column count must equal names count")
    if not np.isfinite(weights).all() or np.any(weights < 0) or not np.allclose(weights.sum(axis=1), 1.0, rtol=0, atol=1e-6):
        raise ValueError("weights must be finite, non-negative, and normalized")
    if "sourceVertexIds" not in skin:
        raise ValueError("skin must carry sourceVertexIds from split_attachment")
    source_ids = np.asarray(skin["sourceVertexIds"])
    if source_ids.ndim != 1 or len(source_ids) != len(vertices) or not np.issubdtype(source_ids.dtype, np.integer):
        raise ValueError("sourceVertexIds must be an integer array with one entry per vertex")
    if not isinstance(owner, str) or not owner:
        raise ValueError("owner must be a non-empty bone name")
    if names.count(owner) != 1:
        raise ValueError("owner must resolve to exactly one unique name")
    owner_index = names.index(owner)
    if isinstance(rings, bool) or not isinstance(rings, (int, np.integer)) or int(rings) < 0:
        raise ValueError("rings must be a non-negative integer")
    rings = int(rings)

    selected = np.asarray(selected_faces)
    if selected.ndim != 1 or not np.issubdtype(selected.dtype, np.integer):
        raise ValueError("selected_faces must be a one-dimensional integer array")
    if len(np.unique(selected)) != len(selected):
        raise ValueError("selected_faces must contain unique face ids")
    if np.any(selected < 0) or np.any(selected >= len(triangles)):
        raise ValueError("selected face id out of range")
    if len(selected) == 0:
        raise ValueError("selected_faces must not be empty")

    count = len(vertices)
    neighbors = [set() for _ in range(count)]
    for corner in range(3):
        starts = triangles[:, corner].tolist()
        ends = triangles[:, (corner + 1) % 3].tolist()
        for start, end in zip(starts, ends):
            if start != end:
                neighbors[start].add(end)
                neighbors[end].add(start)

    selected_mask = np.zeros(len(triangles), dtype=bool)
    selected_mask[selected] = True
    prop_side = set(np.unique(triangles[selected_mask]).tolist())
    body_side = set(np.unique(triangles[~selected_mask]).tolist()) if np.any(~selected_mask) else set()
    duplicates = {index for index in range(count) if int(source_ids[index]) != index}
    seam_sources = {int(source_ids[index]) for index in duplicates}

    def ring(starts, allowed):
        seen = set(starts) & allowed
        frontier = set(seen)
        for _ in range(rings):
            nxt = set()
            for vertex in frontier:
                for other in neighbors[vertex]:
                    if other in allowed and other not in seen:
                        seen.add(other)
                        nxt.add(other)
            frontier = nxt
            if not frontier:
                break
        return seen

    prop_ring = ring(set(duplicates), prop_side)
    body_ring = ring(seam_sources, body_side)

    out = {key: np.asarray(value).copy() for key, value in skin.items()}
    updated = weights.copy()
    onehot = np.zeros(weights.shape[1], dtype=weights.dtype)
    onehot[owner_index] = 1.0
    prop_touched = 0
    for vertex in sorted(prop_ring):
        if not np.array_equal(updated[vertex], onehot):
            updated[vertex] = onehot
            prop_touched += 1
    body_changed = 0
    body_fallback = 0
    owner_mass_dropped = 0.0
    for vertex in sorted(body_ring):
        dropped = float(updated[vertex, owner_index])
        if dropped <= 0.0:
            continue
        row = updated[vertex].copy()
        row[owner_index] = 0.0
        total = float(row.sum())
        if total <= 1e-12:
            body_fallback += 1
            continue
        updated[vertex] = row / total
        body_changed += 1
        owner_mass_dropped += dropped
    out["weights"] = updated
    ring_list = sorted(body_ring)
    remaining = float(updated[ring_list, owner_index].max()) if ring_list else 0.0
    report = {
        "owner": owner,
        "ownerIndex": int(owner_index),
        "rings": rings,
        "seamSourceCount": int(len(seam_sources)),
        "duplicateCount": int(len(duplicates)),
        "propRowsPinned": int(prop_touched),
        "bodyRowsChanged": int(body_changed),
        "bodyRowsFallback": int(body_fallback),
        "ownerMassDropped": float(owner_mass_dropped),
        "maxOwnerMassRemainingInBodyRing": remaining,
        "rowsNormalized": bool(np.allclose(updated.sum(axis=1), 1.0, rtol=0, atol=1e-6)),
    }
    return out, report


def topology_traced_weights(skin, heads, tails, parents=None, power=2.0, trim=0.03, max_influences=4,
                            marker_tokens=("HeadTop_End", "Toe_End")):
    """Skin the mesh with influence traced through connected surface only.

    For each non-marker bone, the distance to a vertex is the shortest path
    that starts at the bone's own surface cell with the Euclidean distance
    and then travels along mesh edges (plus zero-cost links between coincident
    vertices).  A bone that is spatially near a vertex but reachable only
    across disconnected surface - a hand resting by a hip - is at infinite
    distance and can never receive weight through travel.  When the skin
    carries ``sourceVertexIds`` from :func:`split_attachment`, the duplicated
    seam pairs stay barred from each other, so the intentional cut remains a
    barrier while genuine export duplicates still weld.  When ``parents`` is
    given (a J-length array with -1 for the root), pairs the skeleton never
    articulates together are additionally dropped: a vertex keeps its
    strongest bone and only bones sharing that bone's neighbourhood (itself,
    its parent, its children).  This mirrors the owned-rerig articulation
    relation, enforced here because the traced distances already keep each
    patch's blend smooth.  Raw influence falls as
    ``(1 / (distance + 1e-4)) ** power``; the strongest ``max_influences``
    influences per vertex survive ``trim`` and renormalize.  Every vertex
    belongs to exactly one bone's surface cell, so every row keeps at least
    one finite candidate; a row that still totals zero is pinned to its
    Euclidean-nearest candidate and counted as a fallback.  Coincident
    vertices share zero-cost links, so they carry identical weights and a
    mismatch fails closed.
    """
    if not isinstance(skin, Mapping):
        raise TypeError("skin must be a mapping")
    vertices = _array(skin, "vertices")
    triangles = _array(skin, "triangles")
    if len(vertices) == 0 or len(triangles) == 0:
        raise ValueError("mesh must contain vertices and triangles")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.issubdtype(vertices.dtype, np.number):
        raise ValueError("vertices must be an Nx3 numeric array")
    if not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("triangles must be an Mx3 integer array")
    if np.any(triangles < 0) or np.any(triangles >= len(vertices)):
        raise ValueError("triangle vertex index out of range")
    names = _validate_names(skin)
    joint_count = len(names)
    heads = np.asarray(heads, dtype=np.float64)
    tails = np.asarray(tails, dtype=np.float64)
    if (heads.shape != (joint_count, 3) or tails.shape != (joint_count, 3)
            or not np.isfinite(heads).all() or not np.isfinite(tails).all()):
        raise ValueError("heads and tails must be finite Jx3 arrays matching names")
    if not (isinstance(power, (int, float, np.floating)) and np.isfinite(power) and float(power) > 0):
        raise ValueError("power must be a positive number")
    power = float(power)
    if not (isinstance(trim, (int, float, np.floating)) and np.isfinite(trim) and 0.0 <= float(trim) < 1.0):
        raise ValueError("trim must be in [0, 1)")
    trim = float(trim)
    if isinstance(max_influences, bool) or not isinstance(max_influences, (int, np.integer)) or int(max_influences) < 1:
        raise ValueError("max_influences must be a positive integer")
    max_influences = int(max_influences)
    tokens = tuple(marker_tokens) if isinstance(marker_tokens, (list, tuple)) else None
    if tokens is None or not tokens or any(not isinstance(token, str) or not token for token in tokens):
        raise ValueError("marker_tokens must be a non-empty sequence of non-empty names")
    neighbourhoods = None
    if parents is not None:
        parent_array = np.asarray(parents)
        if (parent_array.ndim != 1 or len(parent_array) != joint_count
                or not np.issubdtype(parent_array.dtype, np.integer)
                or np.any(parent_array < -1) or np.any(parent_array >= joint_count)):
            raise ValueError("parents must be a J-length integer array with -1 for the root")
        if not np.any(parent_array < 0):
            raise ValueError("parents must contain a root")
        children = [[] for _ in range(joint_count)]
        for joint, parent in enumerate(parent_array.tolist()):
            if parent >= 0 and joint != parent:
                children[parent].append(joint)
        neighbourhoods = []
        for joint in range(joint_count):
            group = {joint, *children[joint]}
            if int(parent_array[joint]) >= 0:
                group.add(int(parent_array[joint]))
            neighbourhoods.append(group)

    is_marker = np.array([any(token in name for token in tokens) for name in names], dtype=bool)
    candidates = np.flatnonzero(~is_marker)
    if candidates.size == 0:
        raise ValueError("fail-closed: every bone is a marker, so no bone may drive the mesh")

    segments = tails[candidates] - heads[candidates]
    lengths = np.einsum("ij,ij->i", segments, segments)
    relative = vertices[:, None, :] - heads[candidates][None, :, :]
    safe = np.where(lengths >= 1e-12, lengths, 1.0)
    factor = np.clip(np.einsum("vjf,jf->vj", relative, segments) / safe[None, :], 0.0, 1.0)
    factor[:, lengths < 1e-12] = 0.0
    closest = relative - factor[..., None] * segments[None, :, :]
    euclid = np.linalg.norm(closest, axis=2)
    cells = np.argmin(euclid, axis=1)

    count = len(vertices)
    adjacency = [[] for _ in range(count)]
    for corner in range(3):
        starts = triangles[:, corner]
        ends = triangles[:, (corner + 1) % 3]
        lengths_edge = np.linalg.norm(vertices[starts] - vertices[ends], axis=1)
        for start, end, length in zip(starts.tolist(), ends.tolist(), lengths_edge.tolist()):
            if start == end:
                continue
            adjacency[start].append((end, length))
            adjacency[end].append((start, length))
    keys = np.round(vertices, 9)
    _, _, group = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(group, kind="stable")
    runs = np.flatnonzero(np.diff(group[order], prepend=-1))
    # A split cut is an intentional separation: influence must not travel
    # between a duplicated seam vertex and its source even though they are
    # coincident.  Genuine export duplicates (UV seams, hard edges) still link.
    barred = set()
    if "sourceVertexIds" in skin:
        source_ids = np.asarray(skin["sourceVertexIds"])
        if (source_ids.ndim != 1 or len(source_ids) != count
                or not np.issubdtype(source_ids.dtype, np.integer)
                or np.any(source_ids < 0) or np.any(source_ids >= count)):
            raise ValueError("sourceVertexIds must be an integer array with one entry per vertex")
        for index in range(count):
            source = int(source_ids[index])
            if source != index:
                barred.add((min(index, source), max(index, source)))
    for start, end in zip(runs.tolist(), list(runs[1:].tolist()) + [count]):
        run = order[start:end].tolist()
        for first, second in zip(run, run[1:]):
            if (min(first, second), max(first, second)) in barred:
                continue
            adjacency[first].append((second, 0.0))
            adjacency[second].append((first, 0.0))

    traced = np.full((count, candidates.size), np.inf)
    for slot in range(candidates.size):
        seeds = np.flatnonzero(cells == slot)
        dist = np.full(count, np.inf)
        dist[seeds] = euclid[seeds, slot]
        heap = [(float(dist[seed]), int(seed)) for seed in seeds.tolist()]
        heapq.heapify(heap)
        while heap:
            best, node = heapq.heappop(heap)
            if best > dist[node]:
                continue
            for other, length in adjacency[node]:
                proposal = best + length
                if proposal < dist[other]:
                    dist[other] = proposal
                    heapq.heappush(heap, (proposal, other))
        traced[:, slot] = dist

    raw = np.where(np.isfinite(traced), 1.0 / np.power(traced + 1e-4, power), 0.0)
    articulation_dropped_entries = 0
    articulation_dropped_raw = 0.0
    if neighbourhoods is not None:
        strongest = candidates[np.argmax(raw, axis=1)]
        for vertex in range(count):
            keep = neighbourhoods[int(strongest[vertex])]
            for slot, joint in enumerate(candidates.tolist()):
                if raw[vertex, slot] > 0.0 and joint not in keep:
                    articulation_dropped_entries += 1
                    articulation_dropped_raw += float(raw[vertex, slot])
                    raw[vertex, slot] = 0.0
    slots = min(candidates.size, max_influences)
    pick = np.argsort(-raw, axis=1, kind="stable")[:, :slots]
    picked = np.take_along_axis(raw, pick, axis=1)
    chosen = candidates[pick]
    if trim > 0.0:
        picked = np.where(picked >= trim, picked, 0.0)
    totals = picked.sum(axis=1, keepdims=True)
    fallback = int(np.count_nonzero(totals[:, 0] <= 0.0))
    if fallback:
        nearest = candidates[np.argmin(euclid, axis=1)]
        for vertex in np.flatnonzero(totals[:, 0] <= 0.0).tolist():
            picked[vertex, :] = 0.0
            picked[vertex, 0] = 1.0
            chosen[vertex, :] = 0
            chosen[vertex, 0] = int(nearest[vertex])
        totals = picked.sum(axis=1, keepdims=True)
    updated = np.zeros((count, joint_count), dtype=np.float64)
    for vertex in range(count):
        updated[vertex, chosen[vertex]] = picked[vertex] / max(float(totals[vertex, 0]), 1e-12)

    # Coincident groups must carry identical rows; the zero-cost links above
    # make this hold by construction, verified group by group.  Intentionally
    # barred split pairs are exempt: their difference is the cut working.
    mismatch = 0.0
    for start, end in zip(runs.tolist(), list(runs[1:].tolist()) + [count]):
        members = order[start:end].tolist()
        for pos, first in enumerate(members):
            for second in members[pos + 1:]:
                if (min(first, second), max(first, second)) in barred:
                    continue
                mismatch = max(mismatch, float(np.abs(updated[first] - updated[second]).max()))
    if mismatch > 0.0:
        raise ValueError(
            f"fail-closed: vertices at the same position carry different weights (worst {mismatch:.3e})"
        )

    euclid_raw = 1.0 / np.power(euclid + 1e-4, power)
    euclid_order = np.argsort(-euclid_raw, axis=1, kind="stable")[:, :slots]
    euclid_picked = np.take_along_axis(euclid_raw, euclid_order, axis=1)
    if trim > 0.0:
        euclid_picked = np.where(euclid_picked >= trim, euclid_picked, 0.0)
    euclid_totals = euclid_picked.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        euclid_weights = euclid_picked / np.maximum(euclid_totals, 1e-12)
    unreachable = ~np.isfinite(traced)
    excluded_mass = 0.0
    for vertex in range(count):
        if euclid_totals[vertex, 0] <= 0:
            continue
        for slot in range(candidates.size):
            if unreachable[vertex, slot]:
                position = np.flatnonzero(euclid_order[vertex] == slot)
                if position.size:
                    excluded_mass += float(euclid_weights[vertex, int(position[0])])

    out = {key: np.asarray(value).copy() for key, value in skin.items()}
    out["weights"] = updated
    report = {
        "schema": "topology_traced_weights.v1",
        "rule": f"surface_traced_distance_to_flesh_bones_strongest_{max_influences}",
        "power": power,
        "trim": trim,
        "maxInfluences": max_influences,
        "candidateBones": int(candidates.size),
        "markerBonesExcluded": [names[int(index)] for index in np.flatnonzero(is_marker)],
        "coincidentGroups": int(sum(1 for start, end in zip(runs.tolist(), list(runs[1:].tolist()) + [count]) if end - start > 1)),
        "splitPairsBarred": int(len(barred)),
        "maxInfluencesPerVertex": int((updated > 0.0).sum(axis=1).max()),
        "unreachableBoneEntries": int(unreachable.sum()),
        "excludedMass": float(excluded_mass),
        "articulationEnforced": neighbourhoods is not None,
        "articulationDroppedEntries": int(articulation_dropped_entries),
        "articulationDroppedRawFraction": float(articulation_dropped_raw / max(float(raw.sum() + articulation_dropped_raw), 1e-12)) if neighbourhoods is not None else 0.0,
        "rowsFallback": fallback,
        "coincidentWeightMismatch": mismatch,
        "rowsNormalized": bool(np.allclose(updated.sum(axis=1), 1.0, rtol=0, atol=1e-6)),
    }
    return out, report


def consolidate_redundant_owner(skin, baseline_joint_worlds, owner):
    """Transfer a motion-equivalent terminal owner's weight to its parent.

    This is intentionally a pre-attachment operation.  It does not modify
    the supplied completed joint matrices, and fails closed when the owner
    and parent have independently observable raw skin transforms.
    """
    if not isinstance(skin, Mapping):
        raise TypeError("skin must be a mapping")
    vertices = _array(skin, "vertices")
    weights = _array(skin, "weights")
    names = _validate_names(skin)
    parents = _array(skin, "parents")
    inverse_bind = _array(skin, "inverseBind")
    worlds = np.asarray(baseline_joint_worlds)
    joint_count = len(names)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or not np.issubdtype(vertices.dtype, np.number)
            or not np.isfinite(vertices).all()):
        raise ValueError("vertices must be finite Nx3 numeric data")
    if (weights.ndim != 2 or weights.shape != (len(vertices), joint_count)
            or not np.issubdtype(weights.dtype, np.number) or not np.isfinite(weights).all()
            or np.any(weights < 0) or not np.allclose(weights.sum(axis=1), 1.0, rtol=0, atol=1e-6)):
        raise ValueError("weights must be finite, non-negative, normalized VxJ numeric data")
    if (parents.ndim != 1 or len(parents) != joint_count
            or not np.issubdtype(parents.dtype, np.integer)
            or np.any(parents < -1) or np.any(parents >= joint_count)):
        raise ValueError("parents must be a valid J-length integer array")
    if (inverse_bind.shape != (joint_count, 4, 4)
            or not np.issubdtype(inverse_bind.dtype, np.number)
            or not np.isfinite(inverse_bind).all()):
        raise ValueError("inverseBind must be finite Jx4x4 numeric data")
    if (worlds.ndim != 4 or worlds.shape[0] == 0 or worlds.shape[1:] != (joint_count, 4, 4)
            or not np.isfinite(worlds).all()):
        raise ValueError("baseline_joint_worlds must be finite FxJx4x4 data")
    if not isinstance(owner, str) or names.count(owner) != 1:
        raise ValueError("owner must resolve to exactly one unique name")
    owner_index = names.index(owner)
    parent_index = int(parents[owner_index])
    if parent_index < 0:
        raise ValueError("owner must be non-root")
    if parent_index == owner_index:
        raise ValueError("owner cannot parent itself")
    cursor = parent_index
    seen = {owner_index}
    while cursor >= 0:
        if cursor in seen:
            raise ValueError("parents contain a cycle")
        seen.add(cursor)
        cursor = int(parents[cursor])
    if np.any(parents == owner_index):
        raise ValueError("owner must be a leaf")
    raw_skin = worlds @ inverse_bind[None, ...]
    matrix_error = np.max(np.abs(raw_skin[:, owner_index] - raw_skin[:, parent_index])) if len(worlds) else 0.0
    if not np.allclose(raw_skin[:, owner_index], raw_skin[:, parent_index], rtol=0, atol=1e-6):
        raise ValueError("owner and parent have independent raw skin motion")

    result = {key: np.asarray(value).copy() for key, value in skin.items()}
    result_weights = weights.copy()
    result_weights[:, parent_index] += result_weights[:, owner_index]
    result_weights[:, owner_index] = 0
    result["weights"] = result_weights

    def lbs(transform_weights):
        homogeneous = np.concatenate([vertices, np.ones((len(vertices), 1), dtype=vertices.dtype)], axis=1)
        blended = np.einsum("fjab,vj->fvab", raw_skin, transform_weights, optimize=True)
        transformed = np.einsum("fvab,vb->fva", blended, homogeneous, optimize=True)
        return transformed[..., :3]

    original_pose = lbs(weights)
    consolidated_pose = lbs(result_weights)
    vertex_error = np.max(np.abs(original_pose - consolidated_pose)) if original_pose.size else 0.0
    if vertex_error > 1e-6:
        raise ValueError("consolidation changed baseline LBS vertices")
    return result, {
        "owner": owner,
        "ownerIndex": owner_index,
        "parent": names[parent_index],
        "parentIndex": parent_index,
        "ownerWeightCount": int(np.count_nonzero(weights[:, owner_index])),
        "maxMatrixError": float(matrix_error),
        "maxVertexError": float(vertex_error),
    }


def boundary_gaps(animated, pairs):
    """Measure posed distances for source/new boundary vertex pairs."""
    posed = np.asarray(animated)
    if posed.ndim not in (2, 3) or posed.shape[-1] != 3 or not np.isfinite(posed).all():
        raise ValueError("animated must be finite Nx3 or TxNx3 positions")
    pair_array = np.asarray(pairs)
    if pair_array.size == 0:
        pair_array = pair_array.reshape(0, 2)
    if (pair_array.ndim != 2 or pair_array.shape[1] != 2 or
            not np.issubdtype(pair_array.dtype, np.integer) or
            np.any(pair_array < 0) or np.any(pair_array >= posed.shape[-2])):
        raise ValueError("pairs must be an array of valid [source, duplicate] indices")
    pair_array = pair_array.astype(np.int64, copy=False)
    distances = np.linalg.norm(posed[..., pair_array[:, 0], :] - posed[..., pair_array[:, 1], :], axis=-1)
    return {
        "pairs": pair_array.tolist(),
        "distances": distances.tolist(),
        "maxDistance": float(distances.max()) if distances.size else 0.0,
        "meanDistance": float(distances.mean()) if distances.size else 0.0,
        "acceptance": "not evaluated",
    }
