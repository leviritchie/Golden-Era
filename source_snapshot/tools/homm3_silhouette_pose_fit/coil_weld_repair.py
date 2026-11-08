"""Detect and cut Meshy coil-on-coil welds on a snakelike mesh.

A coiled idle sprite makes two body loops touch in 3D. Meshy often fuses those
contacts into real faces. Strain, leftover-gravity, and occupancy scoring cannot
uncoil a fused tube: the bind mesh itself is wrong.

Pipeline (fail-closed):

1. Same-sheet weld of *duplicate* vertices (UV/hard-edge splits at ~0 distance).
   The epsilon must stay on the duplicate plateau. A larger weld would join
   coil-to-coil contacts and is rejected.
2. Geometric detect: faces whose centroids are closer than a small multiple of
   the median edge, whose normals are opposed, and that are only a few dual-graph
   hops apart. Cluster those faces. This is a proposal, not a cut list.
3. LLM authorship against the sprite + overlay. Every cluster id is cut or keep.
   Mouth, fins, and scale grooves can look like contacts.
4. Delete authored faces on the *original* vertex buffer (UVs stay). Split
   vertices whose remaining faces form more than one fan so coils do not stay
   pinched at shared verts.

Detection uses the welded topology so geodesic adjacency is a real surface.
Cuts are applied with original face indices so UV islands are not merged.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

AUTHORING_METHOD = "human_eye_coil_weld_authoring"


@dataclass(frozen=True)
class CoilWeldDetectSettings:
    same_sheet_weld_body_lengths: float = 1e-4
    same_sheet_reference_body_lengths: float = 1e-6
    same_sheet_unique_rel_tol: float = 0.02
    contact_edge_scale: float = 1.3
    opposed_normal_dot: float = -0.5
    max_dual_hops: int = 2
    min_cluster_faces: int = 8
    max_cluster_face_fraction: float = 0.20


@dataclass(frozen=True)
class CoilWeldCluster:
    cluster_id: int
    face_indices: np.ndarray
    source_face_indices: np.ndarray
    centroid: np.ndarray
    face_count: int
    face_fraction: float
    too_large: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "clusterId": int(self.cluster_id),
            "faceCount": int(self.face_count),
            "faceFraction": float(self.face_fraction),
            "tooLarge": bool(self.too_large),
            "centroid": [float(axis) for axis in np.asarray(self.centroid, dtype=np.float64).reshape(3)],
            "sourceFaceIndices": [int(index) for index in np.asarray(self.source_face_indices, dtype=np.int64).tolist()],
        }


@dataclass(frozen=True)
class SameSheetWeld:
    verts: np.ndarray
    faces: np.ndarray
    inverse: np.ndarray
    source_face_indices: np.ndarray
    unique_count: int
    unique_count_reference: int
    eps: float


@dataclass(frozen=True)
class CoilWeldDetectResult:
    settings: CoilWeldDetectSettings
    body_extent: float
    median_edge: float
    original_vertex_count: int
    original_face_count: int
    welded_vertex_count: int
    welded_face_count: int
    component_count: int
    geodesic_diameter_hops: int
    clusters: tuple[CoilWeldCluster, ...]
    ignored_tiny_clusters: int
    ignored_tiny_faces: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": {
                "sameSheetWeldBodyLengths": float(self.settings.same_sheet_weld_body_lengths),
                "sameSheetReferenceBodyLengths": float(self.settings.same_sheet_reference_body_lengths),
                "sameSheetUniqueRelTol": float(self.settings.same_sheet_unique_rel_tol),
                "contactEdgeScale": float(self.settings.contact_edge_scale),
                "opposedNormalDot": float(self.settings.opposed_normal_dot),
                "maxDualHops": int(self.settings.max_dual_hops),
                "minClusterFaces": int(self.settings.min_cluster_faces),
                "maxClusterFaceFraction": float(self.settings.max_cluster_face_fraction),
            },
            "bodyExtent": float(self.body_extent),
            "medianEdge": float(self.median_edge),
            "originalVertexCount": int(self.original_vertex_count),
            "originalFaceCount": int(self.original_face_count),
            "weldedVertexCount": int(self.welded_vertex_count),
            "weldedFaceCount": int(self.welded_face_count),
            "componentCount": int(self.component_count),
            "geodesicDiameterHops": int(self.geodesic_diameter_hops),
            "clusterCount": int(len(self.clusters)),
            "ignoredTinyClusters": int(self.ignored_tiny_clusters),
            "ignoredTinyFaces": int(self.ignored_tiny_faces),
            "clusters": [cluster.to_dict() for cluster in self.clusters],
        }


def body_extent(verts: np.ndarray) -> float:
    points = np.asarray(verts, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 3:
        raise ValueError("mesh positions must have shape (vertices, 3) with at least 3 vertices")
    extent = float((points.max(axis=0) - points.min(axis=0)).max())
    if not np.isfinite(extent) or extent <= 1e-12:
        raise ValueError("mesh bounding box is degenerate")
    return extent


def median_edge_length(verts: np.ndarray, faces: np.ndarray) -> float:
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    verts = np.asarray(verts, dtype=np.float64)
    if faces.shape[0] < 1:
        raise ValueError("mesh has no triangles")
    lengths = np.concatenate(
        [
            np.linalg.norm(verts[faces[:, 0]] - verts[faces[:, 1]], axis=1),
            np.linalg.norm(verts[faces[:, 1]] - verts[faces[:, 2]], axis=1),
            np.linalg.norm(verts[faces[:, 2]] - verts[faces[:, 0]], axis=1),
        ]
    )
    finite = lengths[np.isfinite(lengths) & (lengths > 1e-12)]
    if finite.size < 1:
        raise ValueError("mesh has no finite triangle edges")
    return float(np.median(finite))


def _validate_faces(verts: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(verts, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("mesh positions must have shape (vertices, 3)")
    if triangles.shape[0] < 1:
        raise ValueError("mesh has no triangles")
    if int(triangles.min()) < 0 or int(triangles.max()) >= int(points.shape[0]):
        raise ValueError("triangle index is outside the vertex buffer")
    return points, triangles


def _union_find_merge(verts: np.ndarray, eps: float) -> np.ndarray:
    points = np.asarray(verts, dtype=np.float64)
    count = int(points.shape[0])
    parent = np.arange(count, dtype=np.int64)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return int(index)

    cell_size = max(float(eps), 1e-12)
    cell = np.floor(points / cell_size).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, coords in enumerate(cell):
        buckets[(int(coords[0]), int(coords[1]), int(coords[2]))].append(index)
    eps2 = float(eps) * float(eps)
    for key, members in buckets.items():
        x, y, z = key
        neighbors: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbors.extend(buckets.get((x + dx, y + dy, z + dz), ()))
        for i in members:
            point = points[i]
            for j in neighbors:
                if j <= i:
                    continue
                if float(np.sum((point - points[j]) ** 2)) <= eps2:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri
    return np.asarray([find(index) for index in range(count)], dtype=np.int64)


def unique_vertex_count(verts: np.ndarray, eps: float) -> int:
    if not np.isfinite(float(eps)) or float(eps) <= 0.0:
        raise ValueError("same-sheet weld epsilon must be positive")
    roots = _union_find_merge(verts, eps)
    return int(np.unique(roots).shape[0])


def same_sheet_weld(
    verts: np.ndarray,
    faces: np.ndarray,
    *,
    eps: float,
    reference_eps: float,
    unique_rel_tol: float,
) -> SameSheetWeld:
    points, triangles = _validate_faces(verts, faces)
    if not np.isfinite(float(eps)) or float(eps) <= 0.0:
        raise ValueError("same-sheet weld epsilon must be positive")
    if not np.isfinite(float(reference_eps)) or float(reference_eps) <= 0.0:
        raise ValueError("same-sheet reference epsilon must be positive")
    if not np.isfinite(float(unique_rel_tol)) or float(unique_rel_tol) <= 0.0:
        raise ValueError("same-sheet unique relative tolerance must be positive")
    if float(eps) + 1e-15 < float(reference_eps):
        raise ValueError("same-sheet weld epsilon must be at least the reference epsilon")
    unique_ref = unique_vertex_count(points, reference_eps)
    unique_eps = unique_vertex_count(points, eps)
    allowed = float(unique_rel_tol) * float(unique_ref)
    if abs(unique_eps - unique_ref) > allowed:
        raise ValueError(
            "same-sheet weld epsilon merges non-duplicate vertices "
            f"(unique {unique_ref} at reference {float(reference_eps):.3e} vs "
            f"{unique_eps} at {float(eps):.3e}; relTol={float(unique_rel_tol)})"
        )
    roots = _union_find_merge(points, eps)
    _, inverse = np.unique(roots, return_inverse=True)
    inverse = inverse.astype(np.int64)
    welded_count = int(inverse.max()) + 1
    welded_verts = np.zeros((welded_count, 3), dtype=np.float64)
    counts = np.zeros(welded_count, dtype=np.int32)
    np.add.at(welded_verts, inverse, points)
    np.add.at(counts, inverse, 1)
    if int((counts < 1).sum()) != 0:
        raise ValueError("same-sheet weld produced an empty vertex cluster")
    welded_verts /= counts[:, None]
    welded_faces = inverse[triangles]
    degenerate = (
        (welded_faces[:, 0] == welded_faces[:, 1])
        | (welded_faces[:, 1] == welded_faces[:, 2])
        | (welded_faces[:, 2] == welded_faces[:, 0])
    )
    source = np.arange(int(triangles.shape[0]), dtype=np.int64)
    return SameSheetWeld(
        verts=welded_verts,
        faces=welded_faces[~degenerate],
        inverse=inverse,
        source_face_indices=source[~degenerate],
        unique_count=int(unique_eps),
        unique_count_reference=int(unique_ref),
        eps=float(eps),
    )


def vertex_adjacency(vertex_count: int, faces: np.ndarray) -> list[list[int]]:
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if vertex_count < 1:
        raise ValueError("mesh has no vertices")
    adj: list[list[int]] = [[] for _ in range(int(vertex_count))]
    seen: set[tuple[int, int]] = set()
    for a, b, c in triangles:
        for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            if u == v:
                continue
            edge = (u, v) if u < v else (v, u)
            if edge in seen:
                continue
            seen.add(edge)
            adj[u].append(v)
            adj[v].append(u)
    return adj


def connected_component_sizes(adjacency: Sequence[Sequence[int]]) -> list[int]:
    seen = np.zeros(len(adjacency), dtype=bool)
    sizes: list[int] = []
    for start in range(len(adjacency)):
        if seen[start] or not adjacency[start]:
            continue
        queue = deque([start])
        seen[start] = True
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for neighbor in adjacency[current]:
                if seen[neighbor]:
                    continue
                seen[neighbor] = True
                queue.append(int(neighbor))
        sizes.append(size)
    sizes.sort(reverse=True)
    return sizes


def geodesic_hops(adjacency: Sequence[Sequence[int]], source: int) -> np.ndarray:
    dist = np.full(len(adjacency), -1, dtype=np.int32)
    dist[int(source)] = 0
    queue = deque([int(source)])
    while queue:
        current = queue.popleft()
        next_hop = int(dist[current]) + 1
        for neighbor in adjacency[current]:
            if dist[neighbor] >= 0:
                continue
            dist[neighbor] = next_hop
            queue.append(int(neighbor))
    return dist


def geodesic_diameter_hops(adjacency: Sequence[Sequence[int]]) -> int:
    nodes = [index for index, neighbors in enumerate(adjacency) if neighbors]
    if len(nodes) < 2:
        raise ValueError("geodesic diameter needs at least two connected vertices")
    first = geodesic_hops(adjacency, nodes[0])
    usable = [node for node in nodes if int(first[node]) >= 0]
    if len(usable) < 2:
        raise ValueError("geodesic diameter source does not reach a second vertex")
    far = int(usable[int(np.argmax(first[usable]))])
    second = geodesic_hops(adjacency, far)
    reached = second[second >= 0]
    if reached.size < 1:
        raise ValueError("geodesic diameter sweep reached no vertices")
    return int(reached.max())


def face_centroids_and_normals(verts: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points, triangles = _validate_faces(verts, faces)
    v0 = points[triangles[:, 0]]
    v1 = points[triangles[:, 1]]
    v2 = points[triangles[:, 2]]
    crossed = np.cross(v1 - v0, v2 - v0)
    lengths = np.linalg.norm(crossed, axis=1)
    ok = lengths > 1e-12
    normals = np.zeros_like(crossed)
    normals[ok] = crossed[ok] / lengths[ok, None]
    centroids = (v0 + v1 + v2) / 3.0
    return centroids, normals, ok


def _face_dual(faces: np.ndarray, face_count: int) -> list[list[int]]:
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    edge_to_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    for face_index, (a, b, c) in enumerate(triangles):
        for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            edge = (u, v) if u < v else (v, u)
            edge_to_faces[edge].append(int(face_index))
    dual: list[list[int]] = [[] for _ in range(int(face_count))]
    for face_list in edge_to_faces.values():
        for i in range(len(face_list)):
            for j in range(i + 1, len(face_list)):
                dual[face_list[i]].append(face_list[j])
                dual[face_list[j]].append(face_list[i])
    return dual


def _spatial_pairs(
    centroids: np.ndarray,
    normals: np.ndarray,
    ok: np.ndarray,
    *,
    contact: float,
    opposed_dot: float,
) -> list[tuple[int, int]]:
    face_count = int(centroids.shape[0])
    cell = np.floor(centroids / max(float(contact), 1e-12)).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index in range(face_count):
        if not bool(ok[index]):
            continue
        buckets[(int(cell[index, 0]), int(cell[index, 1]), int(cell[index, 2]))].append(index)
    pairs: list[tuple[int, int]] = []
    radius = float(contact)
    for i in range(face_count):
        if not bool(ok[i]):
            continue
        x, y, z = map(int, cell[i])
        neighbors: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbors.extend(buckets.get((x + dx, y + dy, z + dz), ()))
        for j in neighbors:
            if j <= i or not bool(ok[j]):
                continue
            if float(np.dot(normals[i], normals[j])) >= float(opposed_dot):
                continue
            if float(np.linalg.norm(centroids[i] - centroids[j])) > radius:
                continue
            pairs.append((i, j))
    return pairs


def _dual_reaches(dual: Sequence[Sequence[int]], src: int, dst: int, limit: int) -> bool:
    hops = {int(src): 0}
    queue = deque([int(src)])
    while queue:
        current = queue.popleft()
        if current == int(dst):
            return True
        if hops[current] >= int(limit):
            continue
        for neighbor in dual[current]:
            if neighbor in hops:
                continue
            hops[int(neighbor)] = hops[current] + 1
            queue.append(int(neighbor))
    return False


def _cluster_faces(dual: Sequence[Sequence[int]], members: Sequence[int]) -> list[np.ndarray]:
    member_set = {int(index) for index in members}
    if not member_set:
        return []
    visited: set[int] = set()
    clusters: list[np.ndarray] = []
    for seed in sorted(member_set):
        if seed in visited:
            continue
        queue = deque([seed])
        visited.add(seed)
        group = [seed]
        while queue:
            current = queue.popleft()
            for neighbor in dual[current]:
                neighbor_i = int(neighbor)
                if neighbor_i in visited or neighbor_i not in member_set:
                    continue
                visited.add(neighbor_i)
                queue.append(neighbor_i)
                group.append(neighbor_i)
        clusters.append(np.asarray(group, dtype=np.int64))
    clusters.sort(key=lambda cluster: (-int(cluster.shape[0]), int(cluster.min())))
    return clusters


def detect_coil_weld_clusters(
    verts: np.ndarray,
    faces: np.ndarray,
    settings: CoilWeldDetectSettings | None = None,
) -> CoilWeldDetectResult:
    cfg = settings or CoilWeldDetectSettings()
    if int(cfg.max_dual_hops) < 1:
        raise ValueError("max_dual_hops must be at least 1")
    if int(cfg.min_cluster_faces) < 1:
        raise ValueError("min_cluster_faces must be at least 1")
    if not np.isfinite(float(cfg.contact_edge_scale)) or float(cfg.contact_edge_scale) <= 0.0:
        raise ValueError("contact_edge_scale must be positive")
    if not np.isfinite(float(cfg.opposed_normal_dot)):
        raise ValueError("opposed_normal_dot must be finite")
    if float(cfg.opposed_normal_dot) >= 0.0:
        raise ValueError("opposed_normal_dot must be negative so only facing sheets pair")
    if not np.isfinite(float(cfg.max_cluster_face_fraction)) or not (
        0.0 < float(cfg.max_cluster_face_fraction) <= 1.0
    ):
        raise ValueError("max_cluster_face_fraction must be in (0, 1]")
    points, triangles = _validate_faces(verts, faces)
    extent = body_extent(points)
    weld = same_sheet_weld(
        points,
        triangles,
        eps=float(cfg.same_sheet_weld_body_lengths) * extent,
        reference_eps=float(cfg.same_sheet_reference_body_lengths) * extent,
        unique_rel_tol=float(cfg.same_sheet_unique_rel_tol),
    )
    if int(weld.faces.shape[0]) < 1:
        raise ValueError("same-sheet weld left no triangles")
    edge = median_edge_length(weld.verts, weld.faces)
    contact = float(cfg.contact_edge_scale) * edge
    centroids, normals, ok = face_centroids_and_normals(weld.verts, weld.faces)
    if int(ok.sum()) < 2:
        raise ValueError("mesh has fewer than two non-degenerate faces")
    pairs = _spatial_pairs(
        centroids,
        normals,
        ok,
        contact=contact,
        opposed_dot=float(cfg.opposed_normal_dot),
    )
    dual = _face_dual(weld.faces, int(weld.faces.shape[0]))
    members: list[int] = []
    seen: set[int] = set()
    for i, j in pairs:
        if not _dual_reaches(dual, i, j, int(cfg.max_dual_hops)):
            continue
        for face_index in (i, j):
            if face_index in seen:
                continue
            seen.add(face_index)
            members.append(face_index)
    raw_clusters = _cluster_faces(dual, members)
    kept: list[CoilWeldCluster] = []
    ignored = 0
    ignored_faces = 0
    welded_face_count = int(weld.faces.shape[0])
    for cluster in raw_clusters:
        if int(cluster.shape[0]) < int(cfg.min_cluster_faces):
            ignored += 1
            ignored_faces += int(cluster.shape[0])
            continue
        source = weld.source_face_indices[cluster]
        fraction = float(cluster.shape[0]) / float(welded_face_count)
        kept.append(
            CoilWeldCluster(
                cluster_id=len(kept),
                face_indices=cluster,
                source_face_indices=source,
                centroid=centroids[cluster].mean(axis=0),
                face_count=int(cluster.shape[0]),
                face_fraction=fraction,
                too_large=fraction > float(cfg.max_cluster_face_fraction),
            )
        )
    adjacency = vertex_adjacency(int(weld.verts.shape[0]), weld.faces)
    sizes = connected_component_sizes(adjacency)
    return CoilWeldDetectResult(
        settings=cfg,
        body_extent=extent,
        median_edge=edge,
        original_vertex_count=int(points.shape[0]),
        original_face_count=int(triangles.shape[0]),
        welded_vertex_count=int(weld.verts.shape[0]),
        welded_face_count=welded_face_count,
        component_count=len(sizes),
        geodesic_diameter_hops=geodesic_diameter_hops(adjacency),
        clusters=tuple(kept),
        ignored_tiny_clusters=ignored,
        ignored_tiny_faces=ignored_faces,
    )


def parse_coil_weld_authorship(payload: Mapping[str, Any], *, cluster_count: int) -> tuple[int, ...]:
    if int(cluster_count) < 0:
        raise ValueError("cluster_count must be non-negative")
    method = payload.get("method")
    if method != AUTHORING_METHOD:
        raise ValueError(
            f"coil-weld authorship method must be {AUTHORING_METHOD!r}, not {method!r}"
        )
    cut = payload.get("cutClusterIds")
    keep = payload.get("keepClusterIds")
    if not isinstance(cut, list) or not isinstance(keep, list):
        raise ValueError("cutClusterIds and keepClusterIds must be JSON arrays")
    try:
        cut_ids = tuple(int(value) for value in cut)
        keep_ids = tuple(int(value) for value in keep)
    except (TypeError, ValueError) as exc:
        raise ValueError("cluster ids must be integers") from exc
    if len(cut_ids) != len(set(cut_ids)) or len(keep_ids) != len(set(keep_ids)):
        raise ValueError("cluster ids must not repeat inside cut or keep")
    cut_set = set(cut_ids)
    keep_set = set(keep_ids)
    overlap = cut_set & keep_set
    if overlap:
        raise ValueError(f"cluster ids listed as both cut and keep: {sorted(overlap)}")
    expected = set(range(int(cluster_count)))
    found = cut_set | keep_set
    missing = expected - found
    extra = found - expected
    if missing or extra:
        raise ValueError(
            "every detect cluster id must be listed as cut or keep exactly once "
            f"(missing={sorted(missing)} extra={sorted(extra)})"
        )
    return tuple(sorted(cut_ids))


def authorship_template(result: CoilWeldDetectResult, *, src_glb: str, sprite: str) -> dict[str, Any]:
    return {
        "method": AUTHORING_METHOD,
        "srcGlb": src_glb,
        "sprite": sprite,
        "cutClusterIds": [],
        "keepClusterIds": [],
        "notes": (
            "Fill every cluster id as cut (coil-on-coil / false weld) or keep "
            "(mouth, fin, scale groove, real anatomy). Do not apply this template."
        ),
        "clusterCount": int(len(result.clusters)),
    }


def cut_source_faces_from_authorship(
    result: CoilWeldDetectResult,
    payload: Mapping[str, Any],
) -> np.ndarray:
    cut_ids = parse_coil_weld_authorship(payload, cluster_count=len(result.clusters))
    faces: list[int] = []
    seen: set[int] = set()
    for cluster_id in cut_ids:
        cluster = result.clusters[int(cluster_id)]
        for face_index in np.asarray(cluster.source_face_indices, dtype=np.int64).tolist():
            if face_index in seen:
                continue
            seen.add(int(face_index))
            faces.append(int(face_index))
    return np.asarray(faces, dtype=np.int64)


def split_nonmanifold_fans(
    verts: np.ndarray,
    faces: np.ndarray,
    attributes: Mapping[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    points, triangles = _validate_faces(verts, faces)
    triangles = triangles.copy()
    extras = _copy_vertex_attributes(attributes, int(points.shape[0]))
    incident: list[list[int]] = [[] for _ in range(int(points.shape[0]))]
    for face_index, (a, b, c) in enumerate(triangles):
        incident[int(a)].append(face_index)
        incident[int(b)].append(face_index)
        incident[int(c)].append(face_index)

    new_verts = [points]
    new_attrs = {name: [array] for name, array in extras.items()}

    def append_vertex(source: int) -> int:
        new_index = int(sum(block.shape[0] for block in new_verts))
        new_verts.append(points[source][None, :])
        for name, blocks in new_attrs.items():
            blocks.append(extras[name][source][None, ...])
        return new_index

    for vertex, face_list in enumerate(incident):
        if len(face_list) < 2:
            continue
        fans = _incident_fans(triangles, vertex, face_list)
        if len(fans) < 2:
            continue
        for fan in fans[1:]:
            cloned = append_vertex(vertex)
            for face_index in fan:
                for corner in range(3):
                    if int(triangles[face_index, corner]) == vertex:
                        triangles[face_index, corner] = cloned
    positions = np.concatenate(new_verts, axis=0)
    merged_attrs = {
        name: np.concatenate(blocks, axis=0) for name, blocks in new_attrs.items()
    }
    return positions, triangles, merged_attrs


def _incident_fans(faces: np.ndarray, vertex: int, face_list: Sequence[int]) -> list[list[int]]:
    members = [int(index) for index in face_list]
    member_set = set(members)
    adjacency: dict[int, list[int]] = {index: [] for index in members}
    for i, face_i in enumerate(members):
        verts_i = {int(value) for value in faces[face_i].tolist()}
        for face_j in members[i + 1 :]:
            verts_j = {int(value) for value in faces[face_j].tolist()}
            shared = verts_i & verts_j
            if vertex in shared and len(shared) == 2:
                adjacency[face_i].append(face_j)
                adjacency[face_j].append(face_i)
    visited: set[int] = set()
    fans: list[list[int]] = []
    for seed in members:
        if seed in visited:
            continue
        queue = deque([seed])
        visited.add(seed)
        group = [seed]
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
                group.append(neighbor)
        fans.append(group)
    unused = member_set - visited
    if unused:
        raise ValueError(f"fan split missed incident faces at vertex {vertex}: {sorted(unused)}")
    fans.sort(key=lambda group: (len(group), min(group)))
    return fans


def compact_unused_vertices(
    verts: np.ndarray,
    faces: np.ndarray,
    attributes: Mapping[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    points, triangles = _validate_faces(verts, faces)
    extras = _copy_vertex_attributes(attributes, int(points.shape[0]))
    used = np.unique(triangles.reshape(-1))
    if used.shape[0] < 3:
        raise ValueError("mesh has fewer than three used vertices after compact")
    remap = np.full(int(points.shape[0]), -1, dtype=np.int64)
    remap[used] = np.arange(int(used.shape[0]), dtype=np.int64)
    compact_faces = remap[triangles]
    compact_verts = points[used]
    compact_attrs = {name: array[used] for name, array in extras.items()}
    return compact_verts, compact_faces, compact_attrs


def _copy_vertex_attributes(
    attributes: Mapping[str, np.ndarray] | None,
    vertex_count: int,
) -> dict[str, np.ndarray]:
    copied: dict[str, np.ndarray] = {}
    if not attributes:
        return copied
    for name, array in attributes.items():
        values = np.asarray(array)
        if values.shape[0] != int(vertex_count):
            raise ValueError(
                f"vertex attribute {name!r} length {values.shape[0]} != vertex count {vertex_count}"
            )
        copied[str(name)] = values.copy()
    return copied


def apply_coil_weld_cuts(
    verts: np.ndarray,
    faces: np.ndarray,
    cut_source_faces: np.ndarray,
    attributes: Mapping[str, np.ndarray] | None = None,
    *,
    min_largest_component_fraction: float = 0.85,
    same_sheet_weld_body_lengths: float = 1e-4,
    same_sheet_reference_body_lengths: float = 1e-6,
    same_sheet_unique_rel_tol: float = 0.02,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], dict[str, Any]]:
    points, triangles = _validate_faces(verts, faces)
    if not np.isfinite(float(min_largest_component_fraction)) or not (
        0.0 < float(min_largest_component_fraction) <= 1.0
    ):
        raise ValueError("min_largest_component_fraction must be in (0, 1]")
    cut = np.asarray(cut_source_faces, dtype=np.int64).reshape(-1)
    if cut.shape[0] < 1:
        raise ValueError("apply requires at least one authored cut face")
    if int(cut.min()) < 0 or int(cut.max()) >= int(triangles.shape[0]):
        raise ValueError("authored cut face index is outside the source mesh")
    keep = np.ones(int(triangles.shape[0]), dtype=bool)
    keep[cut] = False
    kept_faces = triangles[keep]
    if int(kept_faces.shape[0]) < 1:
        raise ValueError("authored cuts would delete every triangle")
    extras = _copy_vertex_attributes(attributes, int(points.shape[0]))
    split_verts, split_faces, split_attrs = split_nonmanifold_fans(points, kept_faces, extras)
    compact_verts, compact_faces, compact_attrs = compact_unused_vertices(
        split_verts, split_faces, split_attrs
    )
    extent = body_extent(compact_verts)
    welded = same_sheet_weld(
        compact_verts,
        compact_faces,
        eps=float(same_sheet_weld_body_lengths) * extent,
        reference_eps=float(same_sheet_reference_body_lengths) * extent,
        unique_rel_tol=float(same_sheet_unique_rel_tol),
    )
    adjacency = vertex_adjacency(int(welded.verts.shape[0]), welded.faces)
    sizes = connected_component_sizes(adjacency)
    if not sizes:
        raise ValueError("cut mesh has no connected surface vertices after same-sheet weld")
    largest_fraction = float(sizes[0]) / float(welded.verts.shape[0])
    if largest_fraction < float(min_largest_component_fraction):
        raise ValueError(
            "authored cuts split the mesh into fragments "
            f"(largest welded component {sizes[0]} / {welded.verts.shape[0]} verts "
            f"< {float(min_largest_component_fraction)})"
        )
    report = {
        "cutFaceCount": int(np.unique(cut).shape[0]),
        "keptFaceCount": int(compact_faces.shape[0]),
        "vertexCount": int(compact_verts.shape[0]),
        "weldedVertexCount": int(welded.verts.shape[0]),
        "weldedComponentCount": len(sizes),
        "weldedComponentSizes": [int(size) for size in sizes[:12]],
        "largestComponentFraction": largest_fraction,
        "geodesicDiameterHops": geodesic_diameter_hops(adjacency),
        "fanSplitVertexCount": int(split_verts.shape[0] - points.shape[0]),
    }
    return compact_verts, compact_faces, compact_attrs, report


def compute_vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    points, triangles = _validate_faces(verts, faces)
    normals = np.zeros_like(points)
    v0 = points[triangles[:, 0]]
    v1 = points[triangles[:, 1]]
    v2 = points[triangles[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)
    np.add.at(normals, triangles[:, 0], face_normals)
    np.add.at(normals, triangles[:, 1], face_normals)
    np.add.at(normals, triangles[:, 2], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    ok = lengths > 1e-12
    if int((~ok).sum()) == int(points.shape[0]):
        raise ValueError("cut mesh has no finite vertex normals")
    normals[ok] /= lengths[ok, None]
    return normals
