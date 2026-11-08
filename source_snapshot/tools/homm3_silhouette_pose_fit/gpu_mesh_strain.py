"""Bind rest-length strain for LBS blend edges.

Joint rotation is rotate-only. Shared-weight vertices still stretch when two
bones rotate apart. Occupancy IoU and regional blob search do not see that.
This module names triangle edges whose vertices are not exclusive to the same
bone, then scores how far posed length drifted from bind length.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np


def unique_triangle_edges(triangles: np.ndarray) -> np.ndarray:
    """Return undirected unique edges as (E, 2) with i < j."""
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if faces.size == 0:
        raise ValueError("strain mesh has no triangles")
    if int(faces.min()) < 0:
        raise ValueError("strain triangles reference a negative vertex")
    stacked = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    stacked.sort(axis=1)
    stacked = stacked[stacked[:, 0] != stacked[:, 1]]
    if stacked.shape[0] < 1:
        raise ValueError("strain mesh has no unique edges")
    return np.unique(stacked, axis=0)


def mixed_influence_edge_mask(
    edges: np.ndarray,
    *,
    joints: np.ndarray,
    weights: np.ndarray,
    exclusive_weight: float,
) -> np.ndarray:
    """True where an edge is not a rigid exclusive-bone segment."""
    exclusive = float(exclusive_weight)
    if not math.isfinite(exclusive) or exclusive <= 0.0 or exclusive > 1.0:
        raise ValueError("exclusive_weight must be in (0, 1]")
    index = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    joint_slots = np.asarray(joints, dtype=np.int64)
    skin_weights = np.asarray(weights, dtype=np.float64)
    if joint_slots.shape != skin_weights.shape or joint_slots.ndim != 2:
        raise ValueError("joints and weights must share shape (vertices, influences)")
    if int(index.min()) < 0 or int(index.max()) >= int(joint_slots.shape[0]):
        raise ValueError("strain edges reference a vertex outside the primitive")
    dominant = np.argmax(skin_weights, axis=1)
    vertex_index = np.arange(int(joint_slots.shape[0]))
    dominant_joint = joint_slots[vertex_index, dominant]
    peak = skin_weights[vertex_index, dominant]
    exclusive_vertex = peak >= exclusive
    left = index[:, 0]
    right = index[:, 1]
    rigid = (
        exclusive_vertex[left]
        & exclusive_vertex[right]
        & (dominant_joint[left] == dominant_joint[right])
    )
    return ~rigid


def rest_edge_lengths(bind_positions: np.ndarray, edges: np.ndarray) -> np.ndarray:
    points = np.asarray(bind_positions, dtype=np.float64)
    index = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("bind positions must have shape (vertices, 3)")
    delta = points[index[:, 0]] - points[index[:, 1]]
    lengths = np.linalg.norm(delta, axis=1)
    if not np.isfinite(lengths).all():
        raise ValueError("bind edge lengths must be finite")
    return lengths


def strain_excess_from_lengths(
    posed_lengths: np.ndarray,
    rest_lengths: np.ndarray,
    *,
    tolerance: float,
) -> np.ndarray:
    """Per-edge relative length error above ``tolerance``."""
    rest = np.asarray(rest_lengths, dtype=np.float64)
    posed = np.asarray(posed_lengths, dtype=np.float64)
    if rest.shape != posed.shape:
        raise ValueError("posed and rest edge lengths must match")
    if rest.size < 1:
        raise ValueError("strain needs at least one mixed-influence edge")
    if np.any(rest <= 0.0):
        raise ValueError("rest edge lengths must be positive")
    limit = float(tolerance)
    if not math.isfinite(limit) or limit < 0.0:
        raise ValueError("strain_tolerance must be finite and non-negative")
    relative = np.abs(posed / rest - 1.0)
    return np.maximum(0.0, relative - limit)


def strain_error_from_excess(excess: np.ndarray) -> float:
    """RMS of per-edge excess. One melted blend region is not diluted by rigid faces."""
    values = np.asarray(excess, dtype=np.float64).reshape(-1)
    if values.size < 1:
        raise ValueError("strain excess cannot be empty")
    if not np.isfinite(values).all():
        raise ValueError("strain excess must be finite")
    return float(np.sqrt(np.mean(values * values)))


def posed_edge_lengths(positions: np.ndarray, edges: np.ndarray) -> np.ndarray:
    points = np.asarray(positions, dtype=np.float64)
    index = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    if points.ndim == 2:
        points = points[None, ...]
    if points.ndim != 3 or points.shape[-1] != 3:
        raise ValueError("posed positions must have shape (batch, vertices, 3)")
    delta = points[:, index[:, 0], :] - points[:, index[:, 1], :]
    return np.linalg.norm(delta, axis=-1)


def strain_error_from_positions(
    positions: np.ndarray,
    edges: np.ndarray,
    rest_lengths: np.ndarray,
    *,
    tolerance: float,
) -> np.ndarray:
    posed = posed_edge_lengths(positions, edges)
    errors = [
        strain_error_from_excess(
            strain_excess_from_lengths(row, rest_lengths, tolerance=tolerance)
        )
        for row in np.asarray(posed, dtype=np.float64)
    ]
    return np.asarray(errors, dtype=np.float64)


def strain_error_from_positions_torch(positions, edges, rest_lengths, *, tolerance: float):
    import torch

    if positions.ndim != 3 or int(positions.shape[-1]) != 3:
        raise ValueError("posed positions must have shape (batch, vertices, 3)")
    if int(edges.shape[0]) < 1:
        raise ValueError("strain needs at least one mixed-influence edge")
    rest = rest_lengths.to(dtype=positions.dtype)
    if torch.any(rest <= 0.0):
        raise ValueError("rest edge lengths must be positive")
    limit = float(tolerance)
    if not math.isfinite(limit) or limit < 0.0:
        raise ValueError("strain_tolerance must be finite and non-negative")
    delta = positions[:, edges[:, 0], :] - positions[:, edges[:, 1], :]
    posed = torch.linalg.vector_norm(delta, dim=-1)
    relative = torch.abs(posed / rest.reshape(1, -1) - 1.0)
    excess = torch.clamp(relative - limit, min=0.0)
    return torch.sqrt(torch.mean(excess * excess, dim=-1))


def build_backend_strain_table(
    backend: Any,
    *,
    exclusive_weight: float,
    min_rest_length_body_lengths: float = 1e-4,
) -> dict[str, Any]:
    """Mixed-influence bind edges for one loaded GPU mesh."""
    import torch
    from gpu_mesh_collision import bind_extent_length

    exclusive = float(exclusive_weight)
    min_frac = float(min_rest_length_body_lengths)
    if not math.isfinite(min_frac) or min_frac <= 0.0:
        raise ValueError("min_rest_length_body_lengths must be positive")
    zero_bones = torch.zeros(
        (1, len(backend.asset.nodes), 3),
        dtype=torch.float32,
        device=backend.device,
    )
    worlds = backend._forward_kinematics(
        zero_bones,
        bone_mask=backend.active_node_mask,
    )
    records: list[dict[str, Any]] = []
    bind_parts: list[np.ndarray] = []
    with torch.no_grad():
        for primitive_index, primitive in enumerate(backend.primitives):
            bind = backend._skinned_vertices(worlds, primitive)[0].detach().cpu().numpy()
            bind_parts.append(bind)
            if primitive.indices is None:
                raise ValueError(f"strain primitive {primitive_index} has no triangles")
            faces = np.asarray(primitive.indices.detach().cpu().numpy(), dtype=np.int64).reshape(-1, 3)
            faces = faces[(faces >= 0).all(axis=1)]
            if faces.size == 0:
                raise ValueError(f"strain primitive {primitive_index} has no triangles")
            if primitive.joints is None or primitive.normalized_weights is None:
                continue
            edges = unique_triangle_edges(faces)
            mixed = mixed_influence_edge_mask(
                edges,
                joints=primitive.joints.detach().cpu().numpy(),
                weights=primitive.normalized_weights.detach().cpu().numpy(),
                exclusive_weight=exclusive,
            )
            mixed_edges = edges[mixed]
            if mixed_edges.shape[0] < 1:
                continue
            rest = rest_edge_lengths(bind, mixed_edges)
            records.append(
                {
                    "primitiveIndex": int(primitive_index),
                    "edges": mixed_edges,
                    "rest": rest,
                }
            )
    if not bind_parts:
        raise ValueError("strain sampling found no mesh primitives")
    bind_all = np.concatenate(bind_parts, axis=0)
    min_rest = min_frac * bind_extent_length(bind_all)
    kept: list[dict[str, Any]] = []
    edge_count = 0
    for record in records:
        rest = record["rest"]
        long_enough = rest >= min_rest
        if not bool(np.any(long_enough)):
            continue
        edges = record["edges"][long_enough]
        rest = rest[long_enough]
        kept.append(
            {
                "primitiveIndex": int(record["primitiveIndex"]),
                "edges": torch.as_tensor(edges, dtype=torch.long, device=backend.device),
                "rest": torch.as_tensor(rest, dtype=torch.float32, device=backend.device),
            }
        )
        edge_count += int(edges.shape[0])
    if not kept:
        raise RuntimeError(
            "strain sampling found no mixed-influence edges; "
            "the mesh has no LBS blend region to regularize"
        )
    return {
        "perPrimitive": tuple(kept),
        "edgeCount": int(edge_count),
        "exclusiveWeight": exclusive,
        "minRest": float(min_rest),
        "report": {
            "edgeCount": int(edge_count),
            "primitiveCount": int(len(kept)),
            "exclusiveWeight": exclusive,
            "minRest": float(min_rest),
        },
    }


def strain_error_from_table(backend: Any, table: Mapping[str, Any] | None, bone_vectors, *, tolerance: float):
    """RMS mixed-edge stretch for a pose batch. Root motion does not change it."""
    import torch

    count = int(bone_vectors.shape[0])
    if table is None:
        return torch.zeros((count,), dtype=torch.float32, device=backend.device)
    worlds = backend._forward_kinematics(
        bone_vectors,
        bone_mask=backend.active_node_mask,
    )
    squares = []
    widths = []
    for record in table["perPrimitive"]:
        primitive = backend.primitives[int(record["primitiveIndex"])]
        vertices = backend._skinned_vertices(worlds, primitive)
        excess = _edge_excess_torch(
            vertices,
            record["edges"],
            record["rest"],
            tolerance=float(tolerance),
        )
        squares.append(torch.sum(excess * excess, dim=-1))
        widths.append(int(record["edges"].shape[0]))
    total = torch.stack(squares, dim=0).sum(dim=0)
    edge_count = int(sum(widths))
    if edge_count < 1:
        raise RuntimeError("strain table has no mixed-influence edges")
    return torch.sqrt(total / float(edge_count))


def _edge_excess_torch(positions, edges, rest_lengths, *, tolerance: float):
    import torch

    rest = rest_lengths.to(dtype=positions.dtype)
    delta = positions[:, edges[:, 0], :] - positions[:, edges[:, 1], :]
    posed = torch.linalg.vector_norm(delta, dim=-1)
    relative = torch.abs(posed / rest.reshape(1, -1) - 1.0)
    return torch.clamp(relative - float(tolerance), min=0.0)


def regional_winner_index(
    iou_scores: Sequence[float],
    strain_errors: Sequence[float] | None,
    *,
    strain_slack: float,
) -> int:
    """Keep identity unless a later pose has higher regional IoU without extra stretch.

    Candidate 0 is the opening pose. Strain-legal means RMS excess no higher
    than the opening plus ``strain_slack``. Occupancy ignore and leftover
    blob search do not see LBS melt; this gate is what stops that path.
    """
    scores = [float(value) for value in iou_scores]
    if len(scores) < 1:
        raise ValueError("regional winner needs at least the identity candidate")
    opening_iou = float(scores[0])
    if strain_errors is None:
        allowed = list(range(len(scores)))
    else:
        errors = [float(value) for value in strain_errors]
        if len(errors) != len(scores):
            raise ValueError("strain errors must match regional IoU scores")
        slack = float(strain_slack)
        if not math.isfinite(slack) or slack < 0.0:
            raise ValueError("strain_accept_slack must be finite and non-negative")
        opening_strain = float(errors[0])
        allowed = [
            index
            for index in range(len(scores))
            if float(errors[index]) <= opening_strain + slack
        ]
        if not allowed:
            raise RuntimeError("strain gate rejected every regional candidate including identity")
    winner = int(max(allowed, key=lambda index: (float(scores[index]), -int(index))))
    if float(scores[winner]) <= opening_iou:
        return 0
    return winner
