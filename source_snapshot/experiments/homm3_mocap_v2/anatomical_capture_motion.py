"""Diagnostic anatomical direction transfer over a complete hierarchy."""
from __future__ import annotations

from typing import Any
import numpy as np

from anatomical_direction_transfer import transfer_direction
from direction_retarget import kabsch_rotation, reconstruct_frame_locals
from donor_eagle import compute_rest_joints
from mesh_preview import fk_world_matrices
from reconstruct_adapted import reconstruct_adapted


def _edge_hints(source, target, parents, index, names, inactive=()):
    parent = int(parents[index])
    main_s = source[index] - source[parent]
    main_t = target[index] - target[parent]
    if np.linalg.norm(main_s) <= 1e-8:
        return None
    inactive = set(inactive)
    edges = [(int(p), child) for child, p in enumerate(parents) if int(p) >= 0 and child not in inactive]
    current = (parent, index)
    adjacency = {edge: set() for edge in edges}
    for left in edges:
        for right in edges:
            if left != right and set(left) & set(right):
                adjacency[left].add(right)
    distances = {current: 0}
    queue = [current]
    while queue:
        edge = queue.pop(0)
        for neighbor in adjacency.get(edge, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[edge] + 1
                queue.append(neighbor)
    ranked = []
    for edge in edges:
        if edge == current or edge not in distances:
            continue
        start, end = edge
        hs = source[end] - source[start]
        ht = target[end] - target[start]
        score = min(np.linalg.norm(np.cross(main_s, hs)) / (np.linalg.norm(main_s)*np.linalg.norm(hs)+1e-15),
                    np.linalg.norm(np.cross(main_t, ht)) / (np.linalg.norm(main_t)*np.linalg.norm(ht)+1e-15))
        if score < 1e-4:
            continue
        ranked.append((distances[edge], -float(score), names[start], names[end], hs, ht, float(score)))
    ranked.sort(key=lambda row: row[:4])
    if not ranked or ranked[0][6] < 1e-4:
        return None
    distance, _negative, start_name, end_name, hs, ht, score = ranked[0]
    return score, f"{start_name}->{end_name}", hs, ht, distance


def reconstruct_anatomical_capture(*, capture_positions, capture_reference_positions,
                                   capture_offsets, fitted_offsets, parents, names, hub_names,
                                   target_weights=None):
    baseline = reconstruct_adapted(capture_positions=capture_positions,
        capture_reference_positions=capture_reference_positions, capture_offsets=capture_offsets,
        fitted_offsets=fitted_offsets, parents=parents, names=names, hub_names=hub_names)
    capture = np.asarray(capture_positions, dtype=float)
    source_rest = np.asarray(capture_reference_positions, dtype=float)
    parent = np.asarray(parents, dtype=np.int64)
    target_rest = compute_rest_joints(np.asarray(fitted_offsets, dtype=float), parent)
    coincident = np.linalg.norm(np.asarray(capture_offsets), axis=1) <= 1e-8
    hub_indices = {names.index(name) for name in hub_names}
    inactive = set()
    weights = None if target_weights is None else np.asarray(target_weights, dtype=float)
    if weights is not None:
        if weights.ndim != 2 or weights.shape[1] != len(names) or not np.isfinite(weights).all() or np.any(weights < 0) or not np.allclose(weights.sum(1), 1.0, atol=1e-8, rtol=0):
            raise ValueError("target_weights must be finite, nonnegative, and normalized [V,J]")
    # Resolve all inactive leaves before selecting any hint so no later
    # collapsed leaf can influence an earlier joint's candidate set.
    for index in range(1, len(names)):
        if coincident[index] or np.linalg.norm(target_rest[index] - target_rest[parent[index]]) > 1e-8:
            continue
        children = [i for i, p in enumerate(parent) if int(p) == index]
        if weights is None or children or index in hub_indices or not np.all(weights[:, index] == 0.0):
            raise ValueError(f"target observable edge is zero-length: {names[index]}")
        inactive.add(index)
    hints = {}
    unresolved = []
    for index in range(1, len(names)):
        if coincident[index]:
            continue
        if index in inactive:
            continue
        selected = _edge_hints(source_rest, target_rest, parent, index, names, inactive)
        if selected is None:
            unresolved.append(names[index])
        else:
            score, hint_name, hs, ht, graph_distance = selected
            hints[names[index]] = {"hintJoint": hint_name, "quality": score,
                                   "graphDistance": graph_distance,
                                   "sourceHint": hs.tolist(), "targetHint": ht.tolist()}
    if unresolved:
        raise ValueError(f"anatomical direction hints unresolved: {unresolved}")
    hubs = [names.index(h) for h in hub_names]
    ref_hubs = source_rest[hubs] - source_rest[hubs].mean(0)
    fitted_hubs = target_rest[hubs] - target_rest[hubs].mean(0)
    if np.linalg.matrix_rank(ref_hubs, tol=1e-6) < 2 or np.linalg.matrix_rank(fitted_hubs, tol=1e-6) < 2:
        raise ValueError("body hubs are collinear or numerically ill-conditioned")
    gauge = kabsch_rotation(ref_hubs, fitted_hubs)
    body = []
    for frame in capture:
        posed_hubs = frame[hubs] - frame[hubs].mean(0)
        if np.linalg.matrix_rank(posed_hubs, tol=1e-6) < 2:
            raise ValueError("posed body hubs are collinear or numerically ill-conditioned")
        body.append(kabsch_rotation(ref_hubs, posed_hubs))
    body = np.stack(body)
    rest_local = np.repeat(np.eye(3)[None], len(names), axis=0)
    rest_off = np.asarray(fitted_offsets, dtype=float).copy(); rest_off[0] = 0.
    worlds = []
    locals_out = []
    for frame, rotation in zip(capture, body):
        residual = rotation.T @ (frame - frame[0:1]).T
        residual = residual.T + source_rest[0]
        desired = np.zeros((len(names), 3))
        for index in range(1, len(names)):
            if coincident[index]:
                continue
            if index in inactive:
                continue
            p = parent[index]; key = names[index]; hint = hints[key]
            desired[index] = transfer_direction(source_rest[index]-source_rest[p],
                target_rest[index]-target_rest[p], residual[index]-residual[p],
                hint["sourceHint"], hint["targetHint"])
        local = reconstruct_frame_locals(desired=desired, rest_local=rest_local,
            rest_off=rest_off, parents=parent, root_world=target_rest[0])
        locals_out.append(local)
        target_body = gauge @ rotation @ gauge.T
        root = target_rest[0]
        world = fk_world_matrices(local_rotation=local, local_translation=rest_off,
            parents=parent, root_world=root)
        world[:, :3, :3] = target_body[None] @ world[:, :3, :3]
        world[:, :3, 3] = ((target_body @ (world[:, :3, 3] - target_rest[0]).T).T
                           + target_rest[0])
        world[:, :3, 3] += (gauge @ (frame[0] - source_rest[0]))[None, :]
        local[0] = target_body @ local[0]
        worlds.append(world)
    world = np.stack(worlds)
    positions = world[:, :, :3, 3]
    return {"jointWorld": world, "positions": positions, "hints": hints,
            "fittedRest": target_rest, "captureRest": source_rest,
            "localRotation": np.stack(locals_out),
            "wholeBodyRotation": gauge, "captureBodyRotation": body,
            "fixedLengthErrorMax": float(np.max(np.abs(np.linalg.norm(positions[:,1:]-positions[:,parent[1:]],axis=-1)-np.linalg.norm(rest_off[1:],axis=-1)))),
            "inactiveTargetLeaves": [{"joint": names[i], "reason": "zero target edge and exact zero target weight column"} for i in sorted(inactive)],
            "diagnosticOnly": True, "notProductionSelector": True}


__all__ = ["reconstruct_anatomical_capture"]
