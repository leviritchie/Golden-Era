"""Generic binary Potts refinement for semantic attachment face masks.

This module only proposes face ids.  It never edits vertices, triangles, or
weights.  Triangle adjacency is built after exact-position welding so UV seams
do not break the geometric graph.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow


_SCALE = 100_000
# scipy's graph backend may materialize capacities as signed 32-bit integers.
# Keep the contract below that limit rather than relying on platform width.
_MAX_CAPACITY = np.iinfo(np.int32).max


def _validate(vertices: Any, triangles: Any, sample_passed: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    v = np.asarray(vertices)
    t = np.asarray(triangles)
    passed = np.asarray(sample_passed)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.issubdtype(v.dtype, np.number):
        raise ValueError("vertices must be a non-empty numeric [V,3] array")
    if not np.isfinite(v).all():
        raise ValueError("vertices must be finite")
    if t.ndim != 2 or t.shape[1] != 3 or not np.issubdtype(t.dtype, np.integer) or not len(t):
        raise ValueError("triangles must be a non-empty integer [T,3] array")
    if t.min() < 0 or t.max() >= len(v):
        raise ValueError("triangle indices are outside vertices")
    if passed.ndim != 2 or passed.shape[0] != len(t) or not passed.shape[1]:
        raise ValueError("sample_passed must be bool [T,S]")
    if passed.dtype != np.bool_:
        raise ValueError("sample_passed must have boolean dtype")
    return v.astype(np.float64, copy=False), t.astype(np.int64, copy=False), passed.copy()


def _welded_adjacency(vertices: np.ndarray, triangles: np.ndarray) -> tuple[dict[tuple[int, int], float], np.ndarray]:
    unique_vertices, weld = np.unique(vertices, axis=0, return_inverse=True)
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face, tri in enumerate(triangles):
        wt = weld[tri]
        for a, b in ((wt[0], wt[1]), (wt[1], wt[2]), (wt[2], wt[0])):
            if a == b:
                continue
            key = (int(min(a, b)), int(max(a, b)))
            edge_faces.setdefault(key, []).append(face)
    pairs: dict[tuple[int, int], float] = {}
    for (a, b), faces in edge_faces.items():
        if len(faces) < 2:
            continue
        length = float(np.linalg.norm(unique_vertices[a] - unique_vertices[b]))
        if not np.isfinite(length) or length <= 0:
            raise ValueError("welded adjacency contains a non-positive edge")
        for i, left in enumerate(faces[:-1]):
            for right in faces[i + 1:]:
                if left != right:
                    key = (min(left, right), max(left, right))
                    pairs[key] = pairs.get(key, 0.0) + length
    return pairs, weld


def _reachable_foreground(capacity: coo_matrix, flow: coo_matrix, source: int) -> np.ndarray:
    residual = (capacity - flow).tocsr()
    seen = np.zeros(residual.shape[0], dtype=bool)
    seen[source] = True
    queue: deque[int] = deque([source])
    while queue:
        row = residual.getrow(queue.popleft())
        for col, value in zip(row.indices, row.data):
            if value > 0 and not seen[col]:
                seen[col] = True
                queue.append(int(col))
    return seen


def refine_mask(vertices: Any, triangles: Any, sample_passed: Any, *, smoothness: float = 0.5) -> dict[str, Any]:
    """Return a conservative binary Potts proposal over triangle ids.

    Source-side nodes are foreground.  Samples with probability zero are hard
    background and probability one is hard foreground.  The returned proposal
    is diagnostic only and intentionally contains no edited mesh data.
    """
    v, t, passed = _validate(vertices, triangles, sample_passed)
    if not np.isfinite(smoothness) or smoothness < 0:
        raise ValueError("smoothness must be finite and non-negative")
    probability = passed.mean(axis=1, dtype=np.float64)
    tri_vertices = v[t]
    cross = np.cross(tri_vertices[:, 1] - tri_vertices[:, 0], tri_vertices[:, 2] - tri_vertices[:, 0])
    area = 0.5 * np.linalg.norm(cross, axis=1)
    valid_area = area[np.isfinite(area) & (area > 0)]
    if not len(valid_area):
        raise ValueError("triangles have no positive finite area")
    median_area = float(np.median(valid_area))
    area_factor = area / median_area
    edge_lengths = np.linalg.norm(tri_vertices[:, [1, 2, 0]] - tri_vertices[:, [0, 1, 2]], axis=2)
    valid_edges = edge_lengths[np.isfinite(edge_lengths) & (edge_lengths > 0)]
    if not len(valid_edges):
        raise ValueError("triangles have no positive finite edge")
    median_edge = float(np.median(valid_edges))
    pairs, weld = _welded_adjacency(v, t)
    n = len(t)
    source, sink = n, n + 1
    rows: list[int] = []
    cols: list[int] = []
    values: list[int] = []
    finite_unary: list[float] = []
    eps = np.finfo(np.float64).tiny
    for i, p in enumerate(probability):
        if p == 0.0:
            d0, d1 = 0.0, np.inf
        elif p == 1.0:
            d0, d1 = np.inf, 0.0
        else:
            d0 = -np.log1p(-p) * area_factor[i]
            d1 = -np.log(max(p, eps)) * area_factor[i]
        finite_unary.extend(x for x in (d0, d1) if np.isfinite(x))
    def cap(value: float, *, hard: int | None = None) -> int:
        if np.isinf(value):
            if hard is None:
                raise ValueError("hard capacity was requested before finite capacities were measured")
            value = hard
        scaled = int(np.ceil(value * _SCALE))
        if scaled < 0 or scaled >= _MAX_CAPACITY:
            raise ValueError("capacity is outside supported integer range")
        return scaled
    unary_caps: list[tuple[int, int]] = []
    for i, p in enumerate(probability):
        if p == 0.0: d0, d1 = 0.0, np.inf
        elif p == 1.0: d0, d1 = np.inf, 0.0
        else: d0, d1 = -np.log1p(-p) * area_factor[i], -np.log(max(p, eps)) * area_factor[i]
        unary_caps.append((cap(d0) if np.isfinite(d0) else -1, cap(d1) if np.isfinite(d1) else -1))
    pair_caps = {key: cap(smoothness * length / median_edge) for key, length in pairs.items()}
    finite_total = sum(value for pair in unary_caps for value in pair if value >= 0) + sum(pair_caps.values()) * 2
    if finite_total >= _MAX_CAPACITY - 1:
        raise ValueError("total integer capacity exceeds signed 32-bit contract")
    hard = finite_total + 1
    for i, p in enumerate(probability):
        d0, d1 = unary_caps[i]
        rows += [source, i]; cols += [i, sink]; values += [hard if d0 < 0 else d0, hard if d1 < 0 else d1]
    for (left, right), length in pairs.items():
        value = pair_caps[(left, right)]
        rows += [left, right]; cols += [right, left]; values += [value, value]
    capacity = coo_matrix((np.asarray(values, dtype=np.int64), (rows, cols)), shape=(n + 2, n + 2)).tocsr()
    flow = maximum_flow(capacity, source, sink).flow
    reachable = _reachable_foreground(capacity, flow, source)
    selected = np.flatnonzero(reachable[:n]).astype(np.int64)
    if np.any(probability == 0.0) and np.intersect1d(selected, np.flatnonzero(probability == 0.0)).size:
        raise RuntimeError("max-flow cut violated hard background seeds")
    if np.any(probability == 1.0) and not np.all(np.isin(np.flatnonzero(probability == 1.0), selected)):
        raise RuntimeError("max-flow cut violated hard foreground seeds")
    return {
        "selectedFaceIds": selected,
        "probability": probability,
        "area": area,
        "weldedVertexCount": int(len(np.unique(weld))),
        "adjacencyEdgeCount": int(len(pairs)),
        "hardSeedBackgroundCount": int(np.count_nonzero(probability == 0)),
        "hardSeedForegroundCount": int(np.count_nonzero(probability == 1)),
        "selectedFaceCount": int(len(selected)),
        "smoothness": float(smoothness),
        "accepted": False,
        "proof": "diagnostic-mask-proposal",
    }


def complete_enclosed_mask_faces(vertices: Any, triangles: Any, selected_face_ids: Any,
                                 *, background_seed_face_ids: Any = None) -> dict[str, Any]:
    """Add only enclosed background face components surrounded by selection.

    This is a topology-label diagnostic.  It never edits mesh geometry,
    creates caps, deletes faces, or claims that a segmentation is accepted.
    Exact-position welding makes UV seams part of one geometric adjacency.
    """
    v = np.asarray(vertices)
    t = np.asarray(triangles)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.issubdtype(v.dtype, np.number) or not np.isfinite(v).all():
        raise ValueError("vertices must be a finite non-empty numeric [V,3] array")
    if t.ndim != 2 or t.shape[1] != 3 or not len(t) or not np.issubdtype(t.dtype, np.integer):
        raise ValueError("triangles must be a non-empty integer [T,3] array")
    if np.any(t < 0) or np.any(t >= len(v)):
        raise ValueError("triangle indices are outside vertices")
    selected = np.asarray(selected_face_ids)
    if selected.ndim != 1 or not np.issubdtype(selected.dtype, np.integer):
        raise ValueError("selected_face_ids must be a one-dimensional integer array")
    if len(np.unique(selected)) != len(selected) or np.any(selected < 0) or np.any(selected >= len(t)):
        raise ValueError("selected_face_ids must be valid and unique")
    if background_seed_face_ids is None:
        seeds = np.empty(0, dtype=np.int64)
    else:
        seeds = np.asarray(background_seed_face_ids)
        if seeds.ndim != 1 or not np.issubdtype(seeds.dtype, np.integer):
            raise ValueError("background_seed_face_ids must be one-dimensional integers")
        if len(np.unique(seeds)) != len(seeds) or np.any(seeds < 0) or np.any(seeds >= len(t)):
            raise ValueError("background_seed_face_ids must be valid and unique")
        if np.intersect1d(seeds, selected).size:
            raise ValueError("background seeds cannot also be selected")
    unique, weld = np.unique(v.astype(np.float64, copy=False), axis=0, return_inverse=True)
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face, tri in enumerate(t):
        wt = weld[tri]
        if len(set(wt.tolist())) != 3:
            raise ValueError("degenerate welded triangle")
        for a, b in ((wt[0], wt[1]), (wt[1], wt[2]), (wt[2], wt[0])):
            key = (int(min(a, b)), int(max(a, b)))
            edge_faces.setdefault(key, []).append(face)
    rejected: list[dict[str, Any]] = []
    nonmanifold = [edge for edge, faces in edge_faces.items() if len(faces) > 2]
    if nonmanifold:
        rejected.append({"reason": "nonmanifold_edges", "edges": [list(e) for e in nonmanifold]})
    adjacency = [set() for _ in range(len(t))]
    for faces in edge_faces.values():
        for left in faces:
            adjacency[left].update(right for right in faces if right != left)
    selected_set = set(int(x) for x in selected)
    # Full face-connected components isolate unrelated background-only meshes.
    full_components: list[list[int]] = []
    unseen = set(range(len(t)))
    while unseen:
        start = unseen.pop()
        component = [start]
        queue = [start]
        while queue:
            current = queue.pop()
            for neighbor in adjacency[current] & unseen:
                unseen.remove(neighbor)
                component.append(neighbor)
                queue.append(neighbor)
        full_components.append(sorted(component))
    areas = 0.5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1)
    added_components: list[dict[str, Any]] = []
    expanded = set(selected_set)
    for component in full_components:
        component_set = set(component)
        component_selected = component_set & selected_set
        if not component_selected:
            continue
        background = component_set - selected_set
        bg_seen: set[int] = set()
        bg_components: list[list[int]] = []
        for start in sorted(background):
            if start in bg_seen:
                continue
            bg_seen.add(start)
            group = [start]
            queue = [start]
            while queue:
                current = queue.pop()
                for neighbor in adjacency[current] & background - bg_seen:
                    bg_seen.add(neighbor)
                    group.append(neighbor)
                    queue.append(neighbor)
            bg_components.append(sorted(group))
        if not bg_components:
            continue
        # Exterior is always the largest background component.  Protected
        # seeds preserve additional components; they never redefine exterior.
        exterior_index = int(np.argmax([sum(float(areas[f]) for f in group) for group in bg_components]))
        for index, group in enumerate(bg_components):
            if index == exterior_index or set(group) & set(seeds):
                continue
            group_set = set(group)
            boundary_edges = []
            boundary_neighbors: set[int] = set()
            has_open = False
            for edge, faces in edge_faces.items():
                inside = group_set & set(faces)
                if not inside:
                    continue
                outside = set(faces) - group_set
                if len(faces) == 1:
                    has_open = True
                elif outside:
                    boundary_edges.append(edge)
                    boundary_neighbors.update(outside)
            reason = None
            if has_open:
                reason = "open_boundary_edge"
            elif not boundary_neighbors or not boundary_neighbors <= selected_set:
                reason = "boundary_not_exclusively_selected"
            elif nonmanifold:
                reason = "nonmanifold_edges"
            if reason:
                rejected.append({"reason": reason, "faceIds": group})
                continue
            expanded.update(group_set)
            added_components.append({"faceIds": group, "area": float(sum(float(areas[f]) for f in group)),
                                     "selectedNeighborFaceIds": sorted(boundary_neighbors)})
    return {"expandedFaceIds": np.asarray(sorted(expanded), dtype=np.int64),
            "addedComponents": added_components, "rejectedReasons": rejected,
            "selectedFaceIds": np.asarray(sorted(selected_set), dtype=np.int64),
            "weldedVertexCount": int(len(unique)), "accepted": False,
            "proof": "diagnostic-enclosed-mask-completion"}


__all__ = ["refine_mask", "complete_enclosed_mask_faces"]
