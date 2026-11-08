"""Geodesically-distant sample pairs for GPU pose self-collision.

This is the GPU counterpart of Blender ``collisionBias``: sample mesh
vertices, keep pairs that are far along the surface (or on a separate
island such as a sword), drop pairs that already touch at bind, and
penalize Euclidean approach closer than the margin. Rest contacts such as
armpits are not fought. Detached props are always eligible if they start
far enough apart.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np


def linear_blend_skin_vertices(worlds: Any, primitive: Any, positions: Any, joints: Any, weights: Any):
    """Apply LBS without allocating ``[batch, verts, influences, 4, 4]``.

    Expanding every influence matrix at once is what pushes a 400-pose
    branch raster into Windows Shared GPU memory. Blend one influence
    slot at a time so peak memory scales with vertices, not vertices
    times influences.
    """
    import torch

    if int(positions.shape[0]) < 1:
        raise ValueError("LBS requires at least one vertex")
    if joints.ndim != 2 or weights.ndim != 2:
        raise ValueError("LBS joints and weights must have shape (vertices, influences)")
    if tuple(joints.shape) != tuple(weights.shape):
        raise ValueError("LBS joints and weights must share the same shape")
    if int(joints.shape[0]) != int(positions.shape[0]):
        raise ValueError("LBS vertex count does not match joint indices")
    if int(positions.shape[-1]) != 4:
        raise ValueError("LBS positions must be homogeneous (vertices, 4)")
    influence_count = int(joints.shape[1])
    if influence_count < 1:
        raise ValueError("LBS requires at least one influence")
    joint_matrices = torch.matmul(
        worlds[:, primitive.skin_joints],
        primitive.inverse_bind.unsqueeze(0),
    )
    vertex_count = int(positions.shape[0])
    pos_col = positions.view(1, vertex_count, 4, 1)
    skinned = None
    for influence in range(influence_count):
        mats = joint_matrices[:, joints[:, influence]]
        posed = torch.matmul(mats, pos_col).squeeze(-1)
        contrib = posed * weights[:, influence].reshape(1, vertex_count, 1)
        skinned = contrib if skinned is None else skinned + contrib
    return torch.einsum("bkl,bnl->bnk", worlds[:, primitive.node], skinned)[..., :3]


def coincident_vertex_ids(
    bind_positions: np.ndarray,
    *,
    relative_epsilon: float = 1e-5,
) -> tuple[np.ndarray, np.ndarray]:
    """Map duplicate-at-the-same-point vertices onto one spatial id.

    Meshy hard-edge / UV splits copy a vertex without moving it. The index
    graph then looks like thousands of tiny islands, and collision sampling
    takes one sample from each island. Geodesic hops must walk the spatial
    surface, not that split index graph. A club that is actually detached
    still stays a separate island after this merge.
    """
    bind = np.asarray(bind_positions, dtype=np.float64)
    if bind.ndim != 2 or bind.shape[1] != 3 or int(bind.shape[0]) < 1:
        raise ValueError("bind positions must have shape (vertices, 3)")
    if not math.isfinite(float(relative_epsilon)) or float(relative_epsilon) <= 0.0:
        raise ValueError("relative_epsilon must be finite and positive")
    extent = bind_extent_length(bind)
    quantum = max(float(extent) * float(relative_epsilon), 1e-12)
    keys = np.round(bind / quantum)
    _unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.astype(np.int64)
    _ids, first = np.unique(inverse, return_index=True)
    representatives = first.astype(np.int64)
    if int(representatives.shape[0]) != int(_ids.shape[0]):
        raise RuntimeError("coincident vertex ids are not dense")
    return inverse, representatives


def _welded_faces(faces: np.ndarray, weld_of: np.ndarray) -> np.ndarray:
    remapped = np.asarray(weld_of, dtype=np.int64)[np.asarray(faces, dtype=np.int64)]
    keep = (
        (remapped[:, 0] != remapped[:, 1])
        & (remapped[:, 1] != remapped[:, 2])
        & (remapped[:, 2] != remapped[:, 0])
    )
    if not bool(np.any(keep)):
        raise ValueError("collision mesh has no triangles after coincident-vertex weld")
    return remapped[keep]


def bind_extent_length(bind_positions: np.ndarray) -> float:
    points = np.asarray(bind_positions, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 2:
        raise ValueError("bind positions must have shape (vertices, 3)")
    extent = points.max(axis=0) - points.min(axis=0)
    length = float(np.max(extent))
    if not np.isfinite(length) or length <= 1e-8:
        raise ValueError("collision margin needs a non-degenerate bind bbox")
    return length


def collision_margin_from_bind(
    bind_positions: np.ndarray,
    margin_body_lengths: float,
) -> float:
    if not np.isfinite(float(margin_body_lengths)) or float(margin_body_lengths) <= 0.0:
        raise ValueError("collision_margin_body_lengths must be positive")
    return float(margin_body_lengths) * bind_extent_length(bind_positions)


def _vertex_adjacency(vertex_count: int, triangles: np.ndarray) -> list[list[int]]:
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if vertex_count < 1:
        raise ValueError("collision mesh has no vertices")
    if faces.size == 0:
        raise ValueError("collision mesh has no triangles")
    if int(faces.min()) < 0 or int(faces.max()) >= int(vertex_count):
        raise ValueError("collision triangles reference a vertex outside the mesh")
    adj: list[list[int]] = [[] for _ in range(int(vertex_count))]
    seen: set[tuple[int, int]] = set()
    for a, b, c in faces:
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


def _geodesic_hops(adjacency: Sequence[Sequence[int]], source: int) -> np.ndarray:
    dist = np.full(len(adjacency), -1, dtype=np.int32)
    dist[int(source)] = 0
    queue: deque[int] = deque([int(source)])
    while queue:
        current = queue.popleft()
        next_hop = int(dist[current]) + 1
        for neighbor in adjacency[current]:
            if dist[neighbor] >= 0:
                continue
            dist[neighbor] = next_hop
            queue.append(int(neighbor))
    return dist


def _connected_components(adjacency: Sequence[Sequence[int]]) -> list[np.ndarray]:
    seen = np.zeros(len(adjacency), dtype=bool)
    components: list[np.ndarray] = []
    for start in range(len(adjacency)):
        if seen[start]:
            continue
        order: list[int] = []
        queue: deque[int] = deque([start])
        seen[start] = True
        while queue:
            current = queue.popleft()
            order.append(int(current))
            for neighbor in adjacency[current]:
                if seen[neighbor]:
                    continue
                seen[neighbor] = True
                queue.append(int(neighbor))
        components.append(np.asarray(order, dtype=np.int64))
    edged = [
        component
        for component in components
        if any(adjacency[int(vertex)] for vertex in component.tolist())
    ]
    if not edged:
        raise ValueError("collision mesh has no connected surface vertices")
    return edged


def _sample_components(components: Sequence[np.ndarray], sample_count: int) -> np.ndarray:
    """Take surface samples from every island, not only the largest primitive."""
    if int(sample_count) < 2:
        raise ValueError("collision_sample_count must be at least 2")
    sizes = np.asarray([int(component.shape[0]) for component in components], dtype=np.int64)
    total = int(sizes.sum())
    if total < 2:
        raise ValueError("collision sampling needs at least two vertices")
    chosen: list[int] = []
    for component in components:
        take = max(1, int(round(int(sample_count) * int(component.shape[0]) / total)))
        take = min(int(component.shape[0]), take)
        stride = max(1, int(component.shape[0]) // take)
        chosen.extend(int(vertex) for vertex in component[::stride][:take].tolist())
    unique: list[int] = []
    seen: set[int] = set()
    for vertex in chosen:
        if vertex in seen:
            continue
        seen.add(vertex)
        unique.append(vertex)
    if len(unique) < 2:
        raise ValueError(f"collision sampling produced too few unique vertices: {len(unique)}")
    return np.asarray(unique, dtype=np.int64)


@dataclass(frozen=True)
class MeshCollisionPairs:
    sample_vertices: np.ndarray
    pairs: np.ndarray
    margin: float
    sample_count: int
    pair_count: int
    geodesic_min_hops: int
    cross_component_pairs: int
    bind_extent: float
    raw_island_count: int
    welded_island_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampleCount": int(self.sample_count),
            "pairCount": int(self.pair_count),
            "geodesicMinHops": int(self.geodesic_min_hops),
            "margin": float(self.margin),
            "crossComponentPairs": int(self.cross_component_pairs),
            "bindExtent": float(self.bind_extent),
            "rawIslandCount": int(self.raw_island_count),
            "weldedIslandCount": int(self.welded_island_count),
        }


def build_mesh_collision_pairs(
    *,
    triangles: np.ndarray,
    bind_positions: np.ndarray,
    sample_count: int,
    geodesic_min_hops: int,
    margin: float,
) -> MeshCollisionPairs:
    """Select geodesically-distant (or island) pairs that do not already touch at bind."""
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    bind = np.asarray(bind_positions, dtype=np.float64)
    if bind.ndim != 2 or bind.shape[1] != 3:
        raise ValueError("bind positions must have shape (vertices, 3)")
    if int(geodesic_min_hops) < 1:
        raise ValueError("collision_geodesic_min_hops must be at least 1")
    if not np.isfinite(float(margin)) or float(margin) <= 0.0:
        raise ValueError("collision margin must be positive")
    raw_adjacency = _vertex_adjacency(int(bind.shape[0]), faces)
    raw_island_count = len(_connected_components(raw_adjacency))
    weld_of, representatives = coincident_vertex_ids(bind)
    weld_faces = _welded_faces(faces, weld_of)
    adjacency = _vertex_adjacency(int(representatives.shape[0]), weld_faces)
    welded_components = _connected_components(adjacency)
    weld_samples = _sample_components(welded_components, int(sample_count))
    samples = representatives[weld_samples]
    max_samples = int(sample_count) * 4
    if int(samples.shape[0]) > max_samples:
        raise RuntimeError(
            "collision sampling exploded after coincident-vertex weld: "
            f"samples={int(samples.shape[0])} cap={max_samples} "
            f"rawIslands={raw_island_count} weldedIslands={len(welded_components)}. "
            "Geodesic pairing cannot score every UV-split flake as a separate body"
        )
    gmin = int(geodesic_min_hops)
    pairs: list[tuple[int, int]] = []
    cross_component = 0
    sample_welds = weld_of[samples]
    for sample_i, weld_i in enumerate(sample_welds.tolist()):
        hops = _geodesic_hops(adjacency, int(weld_i))
        for sample_j in range(sample_i + 1, int(samples.shape[0])):
            hop = int(hops[int(sample_welds[sample_j])])
            if hop >= 0 and hop < gmin:
                continue
            if hop < 0:
                cross_component += 1
            bind_distance = float(np.linalg.norm(bind[int(samples[sample_i])] - bind[int(samples[sample_j])]))
            if bind_distance < float(margin):
                continue
            pairs.append((sample_i, sample_j))
    if not pairs:
        raise RuntimeError(
            "collision sampling produced no geodesically-distant pairs "
            f"(samples={int(samples.shape[0])} hops={gmin} margin={float(margin):.4f})"
        )
    return MeshCollisionPairs(
        sample_vertices=samples,
        pairs=np.asarray(pairs, dtype=np.int64),
        margin=float(margin),
        sample_count=int(samples.shape[0]),
        pair_count=len(pairs),
        geodesic_min_hops=gmin,
        cross_component_pairs=int(cross_component),
        bind_extent=bind_extent_length(bind),
        raw_island_count=int(raw_island_count),
        welded_island_count=int(len(welded_components)),
    )


def pair_collision_error(
    positions: np.ndarray,
    pairs: np.ndarray,
    margin: float,
) -> np.ndarray:
    """Return a per-pose error in ``[0, 1)`` for pairs closer than ``margin``.

    ``tanh(sum((clip/margin)^2))`` stays small for one hairline contact and
    saturates when many distant samples overlap, so covering a silhouette hole
    by driving a limb through the torso loses to an unclipped pose.
    """
    points = np.asarray(positions, dtype=np.float64)
    if points.ndim == 2:
        points = points[None, ...]
    if points.ndim != 3 or points.shape[-1] != 3:
        raise ValueError("collision positions must have shape (batch, samples, 3)")
    index = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    if index.shape[0] < 1:
        raise ValueError("collision pairs cannot be empty")
    if not np.isfinite(float(margin)) or float(margin) <= 0.0:
        raise ValueError("collision margin must be positive")
    a = points[:, index[:, 0], :]
    b = points[:, index[:, 1], :]
    distance = np.linalg.norm(a - b, axis=-1)
    violation = np.maximum(0.0, (float(margin) - distance) / float(margin))
    return np.tanh(np.sum(violation * violation, axis=-1)).astype(np.float64)


def pair_collision_error_torch(positions, pairs, margin: float):
    """Torch form of ``pair_collision_error`` for GPU candidate batches."""
    import torch

    points = positions
    if points.ndim != 3 or int(points.shape[-1]) != 3:
        raise ValueError("collision positions must have shape (batch, samples, 3)")
    if int(pairs.shape[0]) < 1:
        raise ValueError("collision pairs cannot be empty")
    a = points[:, pairs[:, 0], :]
    b = points[:, pairs[:, 1], :]
    distance = torch.linalg.vector_norm(a - b, dim=-1)
    violation = torch.clamp((float(margin) - distance) / float(margin), min=0.0)
    return torch.tanh(torch.sum(violation * violation, dim=-1))


def pair_penetration_norm_torch(positions, pairs, margin: float):
    """Unsaturated penetration magnitude: the L2 norm of per-pair violations.

    Companion to ``pair_collision_error_torch``, which compresses the same
    violations through ``tanh`` and therefore stops discriminating once many pairs
    overlap. This one has usable slope over the whole range, which is what an
    incremental solver needs to pull two parts back apart.

    Zero for a pose whose pairs all sit at or beyond ``margin``. Units are multiples
    of ``margin``, so values are not comparable with the ``tanh`` form.
    """
    import torch

    points = positions
    if points.ndim != 3 or int(points.shape[-1]) != 3:
        raise ValueError("collision positions must have shape (batch, samples, 3)")
    if int(pairs.shape[0]) < 1:
        raise ValueError("collision pairs cannot be empty")
    if not float(margin) > 0.0:
        raise ValueError("collision margin must be positive")
    delta = points[:, pairs[:, 0], :] - points[:, pairs[:, 1], :]
    distance = torch.linalg.vector_norm(delta, dim=-1)
    violation = torch.clamp((float(margin) - distance) / float(margin), min=0.0)
    return torch.sqrt((violation * violation).sum(dim=-1) + 1e-12)


def skinned_indexed_vertices(backend: Any, worlds: Any, primitive: Any, local_indices: Any):
    """LBS a vertex subset of one GPU primitive."""
    import torch

    index = torch.as_tensor(local_indices, dtype=torch.long, device=worlds.device)
    positions = primitive.homogeneous_positions.index_select(0, index)
    if primitive.skin_joints is None or primitive.joints is None or primitive.normalized_weights is None:
        return torch.einsum("bkl,nl->bnk", worlds[:, primitive.node], positions)[..., :3]
    joints = primitive.joints.index_select(0, index)
    weights = primitive.normalized_weights.index_select(0, index)
    return linear_blend_skin_vertices(worlds, primitive, positions, joints, weights)


def build_backend_collision_table(
    backend: Any,
    *,
    sample_count: int,
    geodesic_min_hops: int,
    margin_body_lengths: float,
) -> dict[str, Any]:
    """Bind-pose geodesic pairs for one loaded GPU mesh."""
    import torch

    triangles, offsets = concatenate_primitive_triangles(backend.primitives)
    zero_bones = torch.zeros(
        (1, len(backend.asset.nodes), 3),
        dtype=torch.float32,
        device=backend.device,
    )
    worlds = backend._forward_kinematics(
        zero_bones,
        bone_mask=backend.active_node_mask,
    )
    bind_parts = []
    with torch.no_grad():
        for primitive in backend.primitives:
            bind_parts.append(backend._skinned_vertices(worlds, primitive)[0])
    bind = torch.cat(bind_parts, dim=0).detach().cpu().numpy()
    margin = collision_margin_from_bind(bind, float(margin_body_lengths))
    table = build_mesh_collision_pairs(
        triangles=triangles,
        bind_positions=bind,
        sample_count=int(sample_count),
        geodesic_min_hops=int(geodesic_min_hops),
        margin=margin,
    )
    per_primitive: list[tuple[int, Any]] = []
    for primitive_index, start in enumerate(offsets):
        count = int(backend.primitives[primitive_index].positions.shape[0])
        end = start + count
        mask = (table.sample_vertices >= start) & (table.sample_vertices < end)
        if not bool(np.any(mask)):
            continue
        local = table.sample_vertices[mask] - start
        per_primitive.append(
            (
                primitive_index,
                torch.as_tensor(local, dtype=torch.long, device=backend.device),
            )
        )
    if not per_primitive:
        raise RuntimeError("collision samples did not land on any mesh primitive")
    gather_from = np.full(int(table.sample_count), -1, dtype=np.int64)
    cursor = 0
    for primitive_index, local in per_primitive:
        start = offsets[primitive_index]
        globals_for_prim = (local.detach().cpu().numpy() + start).astype(np.int64)
        for local_row, global_vertex in enumerate(globals_for_prim.tolist()):
            matches = np.nonzero(table.sample_vertices == int(global_vertex))[0]
            if matches.size != 1:
                raise RuntimeError("collision sample vertex mapping is not unique")
            gather_from[int(matches[0])] = cursor + local_row
        cursor += int(local.shape[0])
    if np.any(gather_from < 0):
        raise RuntimeError("collision sample order is incomplete")
    return {
        "perPrimitive": tuple(per_primitive),
        "gather": torch.as_tensor(gather_from, dtype=torch.long, device=backend.device),
        "pairs": torch.as_tensor(table.pairs, dtype=torch.long, device=backend.device),
        "margin": float(table.margin),
        "report": table.to_dict(),
    }


def collision_sample_positions(
    backend: Any,
    table: Mapping[str, Any],
    bone_vectors,
    vertex_offsets=None,
):
    """Posed world positions of the collision samples, in sample order.

    Rigid root translation/rotation does not change relative vertex
    distances, so this uses FK worlds only. Optional ``vertex_offsets`` are
    bind-space displacements applied after LBS, matching the exact raster path.
    """
    import torch

    worlds = backend._forward_kinematics(
        bone_vectors,
        bone_mask=backend.active_node_mask,
    )
    offset_chunks: list[Any] | None = None
    if vertex_offsets is not None:
        offset_chunks = []
        cursor = 0
        for primitive in backend.primitives:
            vertex_count = int(primitive.positions.shape[0])
            offset_chunks.append(vertex_offsets[:, cursor : cursor + vertex_count, :])
            cursor += vertex_count
    chunks = []
    for primitive_index, local in table["perPrimitive"]:
        primitive = backend.primitives[primitive_index]
        skinned = skinned_indexed_vertices(backend, worlds, primitive, local)
        if offset_chunks is not None:
            skinned = skinned + offset_chunks[primitive_index].index_select(1, local)
        chunks.append(skinned)
    return torch.cat(chunks, dim=1)[:, table["gather"], :]


def collision_error_from_table(
    backend: Any,
    table: Mapping[str, Any] | None,
    bone_vectors,
    vertex_offsets=None,
):
    """Saturating pair-distance collision for a pose batch.

    See ``pair_collision_error_torch``: this is ``tanh``-compressed, which makes it
    a good tiebreaker between a clean pose and a clipping one but useless as a
    descent signal once a pose already interpenetrates deeply, because the tail is
    flat. Incremental solvers that start from an already-clipping pose want
    ``penetration_norm_from_table`` instead.
    """
    count = int(bone_vectors.shape[0])
    if table is None:
        import torch

        return torch.zeros((count,), dtype=torch.float32, device=backend.device)
    samples = collision_sample_positions(backend, table, bone_vectors, vertex_offsets)
    return pair_collision_error_torch(samples, table["pairs"], float(table["margin"]))


def penetration_norm_from_table(
    backend: Any,
    table: Mapping[str, Any] | None,
    bone_vectors,
    vertex_offsets=None,
):
    """Unsaturated penetration magnitude for a pose batch: ``||violation||_2``.

    Why this exists next to ``collision_error_from_table``
    -----------------------------------------------------
    That function ends in ``tanh(sum(violation^2))``. With roughly a hundred sample
    pairs overlapping, the sum reaches tens and ``tanh`` pins to 1.0 with a slope
    indistinguishable from zero, so every candidate pose scores identically on it
    and a search gets no instruction to pull the parts apart. Raising the weight
    does not help: a flat term stays flat however it is scaled.

    This returns the L2 norm of the per-pair violations instead, which is zero for
    a clean pose and strictly increasing in both penetration depth and the number
    of overlapping pairs, with usable slope across the entire range. It is
    deliberately *not* normalised by pair count: dividing by the (large, mostly
    non-colliding) pair set would shrink the term into noise and remove the
    incentive to reduce how many pairs overlap.

    Units are multiples of the collision margin, so it is not interchangeable with
    ``collision_error_from_table`` and weights tuned against that scale do not
    transfer.
    """
    import torch

    count = int(bone_vectors.shape[0])
    if table is None:
        return torch.zeros((count,), dtype=torch.float32, device=backend.device)
    samples = collision_sample_positions(backend, table, bone_vectors, vertex_offsets)
    return pair_penetration_norm_torch(samples, table["pairs"], float(table["margin"]))


def concatenate_primitive_triangles(primitives: Sequence[Any]) -> tuple[np.ndarray, list[int]]:
    """Return global triangles and the starting vertex offset of each primitive."""
    offsets: list[int] = []
    faces: list[np.ndarray] = []
    cursor = 0
    for primitive in primitives:
        count = int(primitive.positions.shape[0])
        offsets.append(cursor)
        local = np.asarray(primitive.indices.detach().cpu().numpy(), dtype=np.int64).reshape(-1, 3)
        local = local[(local >= 0).all(axis=1)]
        if local.size == 0:
            raise ValueError("collision primitive has no triangles")
        faces.append(local + cursor)
        cursor += count
    if not faces:
        raise ValueError("collision sampling found no mesh primitives")
    return np.concatenate(faces, axis=0), offsets
