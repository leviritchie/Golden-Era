#!/usr/bin/env python3
"""Modify a prepared SmartRig mesh using only fixed mocap and 3-D surface evidence.

The source rest surface, texture, bind, and mocap transforms are immutable.  The
only learned artifact is a sparse vertex-weight field.  No camera, sprite loss,
or per-frame LLM decision participates in this run; rendering is a read-only
preview after the solve.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from corpus_motion import load_motion  # noqa: E402
from eagle_glb import matrices_to_xyzw, write_skinned_glb  # noqa: E402
from glb_skeleton import _accessor, load_bind_skeleton, read_glb  # noqa: E402
from mocap_skin_solver import (  # noqa: E402
    MocapSparseWeightField,
    dual_quaternion_skin,
    optimize_sequence_weights_3d,
    topology_weight_support,
    validate_weights,
)
from oe_motion_style_v2 import MAX_GAIN, _world as _style_world, style_rotations  # noqa: E402
from run_skin_mesh_pilot import (  # noqa: E402
    _load_frozen_prep,
    comparison,
    deform,
    source_images,
    validate_capture_indices,
)
from run_skin_weight_pilot import (  # noqa: E402
    SkinImageRenderer,
    cascade_batch_lock,
    get_profile,
    sha256_file,
)
from paths import SOURCE_FRAME_MS  # noqa: E402


FOCUS_CLIPS = ("g00_move", "g02_idle", "g12_attack_front")
PREVIEW_STYLE_GAIN = 2.20
STRAIN_REPAIR_SCHEMA = "castle-smartrig-strain-repair-v1"


def _json_default(value):
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    raise TypeError(type(value).__name__)


def _segment_regions(vertices: np.ndarray, bind_world: np.ndarray, parents: np.ndarray, *, min_vertices: int = 12):
    """Assign bind vertices to nearest non-degenerate mocap bone segment."""
    points = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(bind_world, dtype=np.float64)[:, :3, 3]
    segments = []
    for child, parent in enumerate(np.asarray(parents, dtype=np.int64)):
        if int(parent) < 0:
            continue
        start, end = joints[int(parent)], joints[child]
        axis = end - start
        denom = float(axis @ axis)
        if denom <= 1e-12:
            continue
        t = np.clip(((points - start) @ axis) / denom, 0.0, 1.0)
        nearest = start[None] + t[:, None] * axis[None]
        segments.append((child, np.sum((points - nearest) ** 2, axis=1)))
    if not segments:
        raise ValueError("mocap skeleton has no non-degenerate bone segment")
    distances = np.stack([item[1] for item in segments], axis=1)
    assignment = np.argmin(distances, axis=1)
    return {
        int(segments[column][0]): np.flatnonzero(assignment == column).astype(np.int64)
        for column in range(len(segments))
        if int(np.count_nonzero(assignment == column)) >= int(min_vertices)
    }


def _articulation_targets(vertices: np.ndarray, bind_world: np.ndarray, parents: np.ndarray,
                          inverse_bind: np.ndarray, worlds: np.ndarray):
    regions = _segment_regions(vertices, bind_world, parents)
    children = sorted(regions)
    ids = [regions[index] for index in children]
    centroids = np.asarray([vertices[index].mean(axis=0) for index in ids], dtype=np.float64)
    homogeneous = np.column_stack((centroids, np.ones(len(centroids), dtype=np.float64)))
    transforms = np.asarray(worlds, dtype=np.float64) @ np.asarray(inverse_bind, dtype=np.float64)[None]
    targets = np.einsum("frij,rj->fri", transforms[:, children], homogeneous)[..., :3]
    return ids, targets, children


def _edge_pairs(faces: np.ndarray) -> np.ndarray:
    return np.unique(np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]]), axis=0), axis=1), axis=0)


def _surface_metrics(vertices: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> dict:
    edges = _edge_pairs(np.asarray(triangles, dtype=np.int64))
    rest = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    valid = rest > 1e-8
    ratios = np.linalg.norm(posed[:, edges[valid, 1]] - posed[:, edges[valid, 0]], axis=-1) / rest[valid][None]
    log_strain = np.log(np.clip(ratios, 1e-4, None))
    return {
        "edgeCount": int(valid.sum()),
        "p95Ratio": float(np.quantile(ratios, 0.95)),
        "p99Ratio": float(np.quantile(ratios, 0.99)),
        "compressionViolationFraction": float(np.mean(ratios < 0.8)),
        "stretchViolationFraction": float(np.mean(ratios > 1.25)),
        "worst1pctLogStrain": float(np.quantile(np.abs(log_strain), 0.99)),
    }


def _edge_strain_diagnostics(vertices: np.ndarray, posed: np.ndarray, triangles: np.ndarray,
                             weights: np.ndarray, *, max_edges: int = 512) -> dict:
    """Find repeated or catastrophic stretch events from 3-D edge strain.

    The detector is deliberately mesh- and unit-agnostic.  A weight boundary is
    only actionable when it is coupled to a large deformation error, which keeps
    legitimate articulated joints from being flattened merely because their
    neighboring vertices use different bones.  Both persistent offenders and a
    single catastrophic frame are retained for repair.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    posed = np.asarray(posed, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    edges = _edge_pairs(np.asarray(triangles, dtype=np.int64))
    rest = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-8)
    rest_floor = max(diagonal * 0.005, float(np.quantile(rest[rest > 1e-8], 0.10)))
    valid = rest >= rest_floor
    edges = edges[valid]
    rest = rest[valid]
    if len(edges) == 0:
        return {"edgeCount": 0, "selectedEdgeCount": 0, "suspectVertexCount": 0,
                "selectedEdges": [], "frameEvents": [], "restLengthFloor": rest_floor}
    ratios = np.linalg.norm(posed[:, edges[:, 1]] - posed[:, edges[:, 0]], axis=-1) / rest[None]
    abs_log = np.abs(np.log(np.clip(ratios, 1e-4, None)))
    disagreement = 0.5 * np.abs(weights[edges[:, 0]] - weights[edges[:, 1]]).sum(axis=1)
    severe = (ratios > 2.0) | (ratios < 0.5)
    persistent = severe.mean(axis=0) >= 0.12
    catastrophic = abs_log.max(axis=0) >= float(np.log(4.0))
    eligible = (persistent | catastrophic) & (disagreement >= 0.35)
    candidate_ids = np.flatnonzero(eligible)
    if len(candidate_ids) > int(max_edges):
        severity = (np.quantile(abs_log[:, candidate_ids], 0.95, axis=0)
                    + 0.25 * abs_log[:, candidate_ids].max(axis=0)
                    + 0.5 * disagreement[candidate_ids])
        candidate_ids = candidate_ids[np.argsort(-severity)[:int(max_edges)]]
    candidate_ids = np.sort(candidate_ids)
    selected_edges = edges[candidate_ids]
    selected_severity = abs_log[:, candidate_ids]
    event_rows = []
    for column, edge_id in enumerate(candidate_ids):
        event_frames = np.flatnonzero(severe[:, edge_id]).astype(int)
        if len(event_frames) == 0:
            event_frames = [int(np.argmax(abs_log[:, edge_id]))]
        event_rows.append({
            "edge": [int(v) for v in edges[edge_id]],
            "restLength": float(rest[edge_id]),
            "weightDisagreement": float(disagreement[edge_id]),
            "maxAbsLogStrain": float(abs_log[:, edge_id].max()),
            "p95AbsLogStrain": float(np.quantile(abs_log[:, edge_id], 0.95)),
            "eventFrames": event_frames.tolist(),
        })
    suspect = np.unique(selected_edges.reshape(-1)).astype(np.int64)
    return {
        "edgeCount": int(len(edges)),
        "selectedEdgeCount": int(len(selected_edges)),
        "suspectVertexCount": int(len(suspect)),
        "restLengthFloor": float(rest_floor),
        "persistentThreshold": 0.12,
        "weightDisagreementThreshold": 0.35,
        "catastrophicRatio": 4.0,
        "selectedEdges": event_rows,
        "frameEvents": int(sum(len(row["eventFrames"]) for row in event_rows)),
        "suspectVertices": suspect.tolist(),
        "selectedSeverityP95": float(np.quantile(selected_severity, 0.95)) if selected_severity.size else 0.0,
    }


def _area_collapse_fraction(vertices: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> float:
    rest_tri = vertices[np.asarray(triangles, dtype=np.int64)]
    pose_tri = posed[:, np.asarray(triangles, dtype=np.int64)]
    rest_area = np.linalg.norm(np.cross(rest_tri[:, 1] - rest_tri[:, 0], rest_tri[:, 2] - rest_tri[:, 0]), axis=-1)
    pose_area = np.linalg.norm(np.cross(pose_tri[:, :, 1] - pose_tri[:, :, 0], pose_tri[:, :, 2] - pose_tri[:, :, 0]), axis=-1)
    valid = rest_area > 1e-10
    if not np.any(valid):
        return 0.0
    return float(np.mean((pose_area[:, valid] / rest_area[valid][None]) < 0.20))


def _strain_tail(vertices: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> dict:
    edges = _edge_pairs(np.asarray(triangles, dtype=np.int64))
    rest = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    valid = rest > 1e-8
    ratios = np.linalg.norm(posed[:, edges[valid, 1]] - posed[:, edges[valid, 0]], axis=-1) / rest[valid][None]
    abs_log = np.abs(np.log(np.clip(ratios, 1e-4, None)))
    return {
        "p95AbsLogStrain": float(np.quantile(abs_log, 0.95)),
        "p99AbsLogStrain": float(np.quantile(abs_log, 0.99)),
        "maxAbsLogStrain": float(np.max(abs_log)),
        "collapsedEdgeFraction": float(np.mean(ratios < 0.25)),
        "areaCollapseFraction": _area_collapse_fraction(vertices, posed, triangles),
    }


def _repair_strain_weights(vertices: np.ndarray, triangles: np.ndarray, weights: np.ndarray,
                           transforms: torch.Tensor, *, max_influences: int,
                           train_frames: np.ndarray | None = None, steps: int = 72) -> tuple[np.ndarray, dict]:
    """Bounded, camera-free weight repair for detected fused-boundary events.

    Only suspect rows are optimized.  Their support is expanded by one-ring
    dominant-joint votes, while a strong prior keeps the repair near SmartRig.
    The repair is accepted only when held-out edge strain improves and motion
    retention does not regress; otherwise the original candidate is returned.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    weights = np.asarray(weights, dtype=np.float64)
    edges = _edge_pairs(triangles)
    rest = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
    diag = _edge_strain_diagnostics(vertices, dual_quaternion_skin(
        torch.as_tensor(vertices, dtype=torch.float32, device=transforms.device),
        torch.as_tensor(weights, dtype=torch.float32, device=transforms.device), transforms
    ).detach().cpu().numpy(), triangles, weights, max_edges=512)
    if not diag["selectedEdgeCount"]:
        return weights.copy(), {"schema": STRAIN_REPAIR_SCHEMA, "accepted": False, "reason": "no_actionable_strain", "detector": diag}
    selected_edges = np.asarray([row["edge"] for row in diag["selectedEdges"]], dtype=np.int64)
    core_suspect = np.asarray(diag["suspectVertices"], dtype=np.int64)
    # Include a one-ring boundary so the optimizer cannot simply move a seam
    # defect to the first untouched neighbor.
    incident_mask = np.any(np.isin(edges, core_suspect), axis=1)
    boundary = np.unique(edges[incident_mask].reshape(-1)).astype(np.int64)
    suspect = np.unique(np.concatenate((core_suspect, boundary))).astype(np.int64)
    support = topology_weight_support(weights, edges, max_influences=int(max_influences), neighbor_vote=0.20)
    local_support = support[suspect]
    local_index = {int(vertex): index for index, vertex in enumerate(suspect)}
    incident_edges = edges[incident_mask]
    incident_edges = incident_edges[
        np.linalg.norm(vertices[incident_edges[:, 1]] - vertices[incident_edges[:, 0]], axis=1) > 1e-8
    ]
    local_edges = np.asarray([[local_index[int(a)], local_index[int(b)]] for a, b in incident_edges], dtype=np.int64)
    local_rest = np.linalg.norm(vertices[incident_edges[:, 1]] - vertices[incident_edges[:, 0]], axis=1)
    selected_keys = {tuple(sorted((int(a), int(b)))) for a, b in selected_edges}
    edge_strength = np.asarray([
        1.0 if tuple(sorted((int(a), int(b)))) in selected_keys else 0.08
        for a, b in incident_edges
    ], dtype=np.float32)
    selected_mask = np.asarray([
        tuple(sorted((int(a), int(b)))) in selected_keys for a, b in incident_edges
    ], dtype=bool)
    if train_frames is None:
        train_frames = np.arange(transforms.shape[0], dtype=np.int64)
    train_frames = np.asarray(train_frames, dtype=np.int64)
    train_transforms = transforms[torch.as_tensor(train_frames, dtype=torch.long, device=transforms.device)]
    device = transforms.device
    local_vertices = torch.as_tensor(vertices[suspect], dtype=torch.float32, device=device)
    local_initial = torch.as_tensor(weights[suspect], dtype=torch.float32, device=device)
    field = MocapSparseWeightField(weights[suspect], max_influences=int(max_influences),
                                   device=str(device), support=local_support)
    optimizer = torch.optim.Adam(field.parameters(), lr=0.025)
    edge_tensor = torch.as_tensor(local_edges, dtype=torch.long, device=device)
    rest_tensor = torch.as_tensor(local_rest, dtype=torch.float32, device=device)
    strength_tensor = torch.as_tensor(edge_strength, dtype=torch.float32, device=device)
    selected_mask_tensor = torch.as_tensor(selected_mask, dtype=torch.bool, device=device)
    for _ in range(int(steps)):
        optimizer.zero_grad(set_to_none=True)
        local_weights = field.weights()
        posed = dual_quaternion_skin(local_vertices, local_weights, train_transforms)
        actual = torch.linalg.vector_norm(posed[:, edge_tensor[:, 1]] - posed[:, edge_tensor[:, 0]], dim=-1)
        log_strain = torch.log((actual / rest_tensor).clamp_min(1e-4))
        severity = strength_tensor / strength_tensor.mean().clamp_min(1e-4)
        edge_loss = (log_strain.square() * severity[None]).mean()
        prior = ((local_weights - local_initial) ** 2).mean()
        smooth = ((local_weights[edge_tensor[:, 0]] - local_weights[edge_tensor[:, 1]]) ** 2).mean()
        continuity = ((local_weights[edge_tensor[selected_mask_tensor, 0]]
                       - local_weights[edge_tensor[selected_mask_tensor, 1]]) ** 2).mean()
        objective = edge_loss + 1.5 * prior + 0.02 * smooth + 0.50 * continuity
        if not torch.isfinite(objective):
            raise ValueError("nonfinite strain repair objective")
        objective.backward()
        torch.nn.utils.clip_grad_norm_(field.parameters(), 0.5)
        optimizer.step()
    repaired = weights.copy()
    repaired[suspect] = field.weights().detach().cpu().numpy()
    validate_weights(repaired, max_influences=int(max_influences))
    delta = np.abs(repaired[suspect] - weights[suspect])
    return repaired, {"schema": STRAIN_REPAIR_SCHEMA, "accepted": False, "detector": diag,
                      "suspectVertices": int(len(suspect)), "optimizedSteps": int(steps),
                      "meanAbsWeightDelta": float(delta.mean()), "maxAbsWeightDelta": float(delta.max()),
                      "trainFrameCount": int(len(train_frames)), "heldOutFrameCount": int(transforms.shape[0] - len(train_frames))}


def _quat_to_matrix(quaternions: np.ndarray) -> np.ndarray:
    q = np.asarray(quaternions, dtype=np.float64)
    q = q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)
    x, y, z, w = np.moveaxis(q, -1, 0)
    return np.stack((
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    ), axis=-1).reshape(q.shape[:-1] + (3, 3))


def _preview_worlds(motion: dict, skin: dict, key: str) -> tuple[np.ndarray, dict]:
    """Apply the established Stronghold preview exaggeration without changing solve/export authority."""
    if key == "g00_move":
        mode = "move"
    elif key.startswith(("g11_attack", "g12_attack", "g13_attack", "g14_shoot", "g15_shoot", "g16_shoot")):
        mode = "attack"
    else:
        mode = "preserve"
    raw_world = np.asarray(motion["jointWorld"], dtype=np.float64)
    if mode == "preserve":
        return raw_world, {"mode": mode, "gain": 1.0, "profile": "stronghold_standard_v2", "solveAuthorityUnchanged": True}
    raw_local = matrices_to_xyzw(np.asarray(motion["localRotation"], dtype=np.float64))
    times = np.arange(len(raw_local), dtype=np.float64) * float(SOURCE_FRAME_MS) / 1000.0
    styled_local = style_rotations(raw_local, np.asarray(skin["parents"], dtype=np.int64), times,
                                   mode=mode, gain=PREVIEW_STYLE_GAIN)
    styled_world_q = _style_world(styled_local, np.asarray(skin["parents"], dtype=np.int64))
    styled_world = raw_world.copy()
    styled_world[:, :, :3, :3] = _quat_to_matrix(styled_world_q)
    return styled_world, {"mode": mode, "gain": PREVIEW_STYLE_GAIN, "profile": "stronghold_standard_v2", "solveAuthorityUnchanged": True}


def _split_strain_seams(vertices: np.ndarray, triangles: np.ndarray, uvs: np.ndarray, weights: np.ndarray,
                        detector: dict, *, max_cuts: int = 256) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """Split high-confidence fused edges into per-face vertices.

    A generated mesh can place a hand/weapon or garment bridge directly against
    the torso.  No static weight can satisfy both sides of that connection.  A
    deterministic seam split preserves the bind surface while allowing each
    incident face to keep the local joint ownership implied by its third vertex.
    This is topology repair, not unit-authored geometry or an image-conditioned
    exception.
    """
    vertices = np.asarray(vertices, dtype=np.float64).copy()
    original_vertex_count = len(vertices)
    if int(max_cuts) < 1:
        raise ValueError("max_cuts must be positive")
    triangles = np.asarray(triangles, dtype=np.int64).copy()
    uvs = np.asarray(uvs, dtype=np.float64).copy()
    weights = np.asarray(weights, dtype=np.float64).copy()
    edge_to_faces: dict[tuple[int, int], list[int]] = {}
    for face, tri in enumerate(triangles):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge_to_faces.setdefault(tuple(sorted((int(a), int(b)))), []).append(face)
    rows = sorted(
        detector.get("selectedEdges", ()),
        key=lambda row: (float(row.get("p95AbsLogStrain", 0.0)) + 0.25 * float(row.get("maxAbsLogStrain", 0.0)),
                         float(row.get("weightDisagreement", 0.0))),
        reverse=True,
    )
    # Select non-conflicting two-face seams before mutating the triangle list.
    # A face is split at most once per pass, so every recorded operation is
    # completed against the same connectivity used by the detector.
    operations = []
    claimed_faces: set[int] = set()
    for row in rows:
        edge = tuple(sorted(int(v) for v in row["edge"]))
        if float(row.get("weightDisagreement", 0.0)) < 0.80:
            continue
        faces = edge_to_faces.get(edge, [])
        if len(faces) != 2 or claimed_faces.intersection(faces):
            continue
        operations.append((row, edge, faces))
        claimed_faces.update(int(face) for face in faces)
        if len(operations) >= int(max_cuts):
            break
    cuts = []
    for row, edge, faces in operations:
        for face in faces:
            tri = triangles[face].copy()
            slots = np.flatnonzero(np.isin(tri, edge))
            if len(slots) != 2:
                raise ValueError("planned seam operation no longer matches its face")
            third = int(next(value for value in tri if int(value) not in edge))
            replacements = {}
            for slot in slots:
                source = int(tri[slot])
                replacements[slot] = len(vertices)
                vertices = np.vstack((vertices, vertices[source]))
                uvs = np.vstack((uvs, uvs[source]))
                weights = np.vstack((weights, weights[third]))
            for slot, replacement in replacements.items():
                triangles[face, slot] = replacement
        cuts.append({"edge": list(edge), "faces": [int(v) for v in faces],
                     "p95AbsLogStrain": float(row.get("p95AbsLogStrain", 0.0)),
                     "weightDisagreement": float(row.get("weightDisagreement", 0.0))})
    return vertices, triangles, uvs, weights, {
        "schema": "castle-smartrig-seam-split-v1", "accepted": bool(cuts), "cutCount": int(len(cuts)),
        "duplicatedVertexCount": int(len(vertices) - original_vertex_count),
        "cuts": cuts, "maxCuts": int(max_cuts),
        "policy": "two-face high-confidence strain seams only",
    }


def _motion_retention(initial: np.ndarray, candidate: np.ndarray) -> dict:
    def energy(value):
        centered = value - value.mean(axis=0, keepdims=True)
        return np.square(centered).sum(axis=-1).mean(axis=0)
    a, b = energy(initial), energy(candidate)
    active = a > 1e-8
    ratios = np.divide(b, np.maximum(a, 1e-8))
    return {
        "activeVertexCount": int(active.sum()),
        "p05EnergyRatio": float(np.quantile(ratios[active], 0.05)) if np.any(active) else 1.0,
        "medianEnergyRatio": float(np.median(ratios[active])) if np.any(active) else 1.0,
        "belowFloorFraction": float(np.mean(ratios[active] < 0.70)) if np.any(active) else 0.0,
    }


def _parent_names(names, parents):
    names = [str(value) for value in names]
    return {
        name: (None if int(parents[index]) < 0 else names[int(parents[index])])
        for index, name in enumerate(names)
    }


def _serialized_animation_check(path: Path, expected_names, expected_times, expected_rotations):
    """Read back every animation accessor and compare by joint name, not node order."""
    doc = read_glb(path)
    animations = doc["json"].get("animations") or []
    nodes = doc["json"].get("nodes") or []
    expected_names = [str(value) for value in expected_names]
    expected_by_name = {name: index for index, name in enumerate(expected_names)}
    result = {
        "ok": False,
        "animationCount": len(animations),
        "rotationChannelCount": 0,
        "translationChannelCount": 0,
        "maxTimeError": float("inf"),
        "maxQuaternionError": float("inf"),
        "missingJoints": list(expected_names),
        "duplicateJoints": [],
    }
    if len(animations) != 1:
        return result
    animation = animations[0]
    seen = []
    max_time_error = 0.0
    max_quaternion_error = 0.0
    for channel in animation.get("channels") or ():
        target = channel.get("target") or {}
        node_index = int(target.get("node", -1))
        node_name = str(nodes[node_index].get("name") or f"node{node_index}") if 0 <= node_index < len(nodes) else ""
        path_name = str(target.get("path") or "")
        if path_name == "translation":
            result["translationChannelCount"] += 1
            continue
        if path_name != "rotation":
            continue
        result["rotationChannelCount"] += 1
        if node_name not in expected_by_name:
            continue
        seen.append(node_name)
        sampler_index = int(channel.get("sampler", -1))
        samplers = animation.get("samplers") or []
        if sampler_index < 0 or sampler_index >= len(samplers):
            continue
        sampler = samplers[sampler_index]
        times = np.asarray(_accessor(doc, doc["bin"], int(sampler["input"])), dtype=np.float64).reshape(-1)
        rotations = np.asarray(_accessor(doc, doc["bin"], int(sampler["output"])), dtype=np.float64).reshape(-1, 4)
        expected_time_array = np.asarray(expected_times, dtype=np.float64).reshape(-1)
        expected_quat = np.asarray(expected_rotations[:, expected_by_name[node_name]], dtype=np.float64).reshape(-1, 4)
        if times.shape != expected_time_array.shape or rotations.shape != expected_quat.shape:
            continue
        max_time_error = max(max_time_error, float(np.max(np.abs(times - expected_time_array))))
        dots = np.abs(np.sum(rotations * expected_quat, axis=1))
        max_quaternion_error = max(max_quaternion_error, float(np.max(1.0 - np.clip(dots, 0.0, 1.0))))
    duplicates = sorted({name for name in seen if seen.count(name) > 1})
    result.update({
        "ok": (result["rotationChannelCount"] == len(expected_names)
               and result["translationChannelCount"] == 0
               and set(seen) == set(expected_names)
               and not duplicates
               and max_time_error <= 2e-6
               and max_quaternion_error <= 2e-5),
        "maxTimeError": max_time_error,
        "maxQuaternionError": max_quaternion_error,
        "missingJoints": sorted(set(expected_names) - set(seen)),
        "duplicateJoints": duplicates,
    })
    return result


def _write_preview(path: Path, source, original, candidate, title: str):
    arrays = [source, original, candidate]
    frames = []
    for index in range(len(source)):
        row = Image.new("RGB", (source.shape[2] * 3, source.shape[1] + 30), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 2), f"{title} frame {index:02d}", fill="white")
        for column, (label, value) in enumerate(zip(("Source", "SmartRig", "Modified"), arrays)):
            image = Image.fromarray(np.uint8(np.clip(value[index], 0, 1) * 255))
            row.paste(image, (column * source.shape[2], 30))
            draw.text((column * source.shape[2] + 4, 16), label, fill=(205, 205, 215))
        frames.append(row)
    if not frames:
        raise ValueError("cannot write an empty preview")
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(round(SOURCE_FRAME_MS)), loop=0)
    selected = np.linspace(0, len(frames) - 1, min(8, len(frames))).astype(int)
    sheet = Image.new("RGB", (frames[0].width, frames[0].height * len(selected)))
    for row, index in enumerate(selected):
        sheet.paste(frames[index], (0, row * frames[0].height))
    sheet.save(path.with_suffix(".png"))


def run(*, asset: str, corpus_path: Path, baseline_dir: Path, output: Path,
        steps: int = 60, max_influences: int = 4) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if int(steps) < 1 or int(max_influences) < 1:
        raise ValueError("steps and max_influences must be positive")
    freeze, skin = _load_frozen_prep(asset)
    profile = get_profile(asset)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("unit") != asset:
        raise ValueError(f"corpus unit {corpus.get('unit')!r} does not match {asset!r}")
    # Frozen corpora are immutable inputs.  Validate every capture and source
    # frame before touching CUDA so a stale frame cannot silently enter a run.
    for entry in corpus["captures"]:
        capture_path = Path(entry["capture"])
        if sha256_file(capture_path) != entry["captureSha256"]:
            raise ValueError(f"capture hash changed: {capture_path}")
    source_frame_metadata = corpus.get("sourceFrames")
    if not isinstance(source_frame_metadata, dict):
        raise ValueError("corpus must provide a complete sourceFrames hash map")
    referenced_frames = {
        str(path)
        for entry in corpus["captures"]
        for path in entry.get("frames", ())
    }
    missing_frames = sorted(referenced_frames - set(source_frame_metadata))
    if missing_frames:
        raise ValueError(f"sourceFrames is missing referenced frames: {missing_frames[:3]}")
    for path in referenced_frames:
        metadata = source_frame_metadata[path]
        if sha256_file(Path(path)) != metadata["sha256"]:
            raise ValueError(f"source frame hash changed: {path}")
    calibration_path = Path(json.loads((baseline_dir / "pilot_report.json").read_text())["inputs"]["calibrationPath"])
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    reference = np.asarray(calibration["referencePositions"], dtype=np.float64)
    motions, frame_paths = {}, {}
    for entry in corpus["captures"]:
        key = str(entry["key"])
        with np.load(Path(entry["capture"]), allow_pickle=False) as raw:
            validate_capture_indices(entry, len(raw["pred_position"]))
            if list(raw["joint_names"].astype(str)) != list(skin["names"]) or not np.array_equal(raw["parents"], skin["parents"]):
                raise ValueError(f"capture skeleton differs from frozen preparation: {key}")
            motions[key] = load_motion(raw, entry, corpus, skin, reference, profile["wholeBodyHubs"])
        frame_paths[key] = [Path(path) for path in entry["frames"]]
    keys = list(motions)
    bind_world = np.linalg.inv(np.asarray(skin["inverseBind"], dtype=np.float64))
    all_worlds = np.concatenate([motions[key]["jointWorld"] for key in keys], axis=0)
    all_transforms = torch.as_tensor(all_worlds @ np.asarray(skin["inverseBind"])[None], dtype=torch.float32, device="cuda")
    region_ids, region_targets, region_children = _articulation_targets(
        np.asarray(skin["vertices"], dtype=np.float64), bind_world, np.asarray(skin["parents"], dtype=np.int64),
        np.asarray(skin["inverseBind"], dtype=np.float64), all_worlds,
    )
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        learned, history = optimize_sequence_weights_3d(
            np.asarray(skin["vertices"], dtype=np.float64), np.asarray(skin["triangles"], dtype=np.int64),
            np.asarray(skin["weights"], dtype=np.float64), all_transforms,
            max_influences=int(max_influences), steps=int(steps), learning_rate=0.025,
            prior_weight=4.0, rigidity_weight=1.0, length_weight=0.35, area_weight=0.15,
            smoothness_weight=0.08, motion_weight=0.45, motion_floor=0.70,
            max_total_variation=0.20, max_edges=16000, max_triangles=8000,
            articulation_regions=region_ids, articulation_targets=region_targets,
            articulation_weight=0.55,
        )
        validate_weights(learned, max_influences=int(max_influences))
        rest_tensor = torch.as_tensor(skin["vertices"], dtype=torch.float32, device="cuda")
        initial_tensor = torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda")
        candidate_tensor = torch.as_tensor(learned, dtype=torch.float32, device="cuda")
        initial_pose = dual_quaternion_skin(rest_tensor, initial_tensor, all_transforms).detach().cpu().numpy()
        candidate_pose = dual_quaternion_skin(rest_tensor, candidate_tensor, all_transforms).detach().cpu().numpy()
        # Detect and repair only repeated/catastrophic high-strain connections.
        # Every fifth frame is held out from the local repair objective so a
        # global tail improvement cannot be produced by fitting one pose.
        train_frames = np.flatnonzero((np.arange(len(all_worlds), dtype=np.int64) % 5) != 0)
        repaired, repair_report = _repair_strain_weights(
            np.asarray(skin["vertices"], dtype=np.float64), np.asarray(skin["triangles"], dtype=np.int64),
            learned, all_transforms, max_influences=int(max_influences), train_frames=train_frames,
        )
        if repair_report.get("detector", {}).get("selectedEdgeCount", 0):
            repaired_tensor = torch.as_tensor(repaired, dtype=torch.float32, device="cuda")
            repaired_pose = dual_quaternion_skin(rest_tensor, repaired_tensor, all_transforms).detach().cpu().numpy()
            before_tail = _strain_tail(np.asarray(skin["vertices"]), candidate_pose, skin["triangles"])
            after_tail = _strain_tail(np.asarray(skin["vertices"]), repaired_pose, skin["triangles"])
            repair_motion = _motion_retention(candidate_pose, repaired_pose)
            accepted = bool(
                after_tail["p99AbsLogStrain"] <= before_tail["p99AbsLogStrain"] * 0.90
                and after_tail["areaCollapseFraction"] <= before_tail["areaCollapseFraction"] + 1e-4
                and after_tail["collapsedEdgeFraction"] <= before_tail["collapsedEdgeFraction"] + 0.002
                and repair_motion["p05EnergyRatio"] >= 0.95
                and repair_motion["belowFloorFraction"] <= 0.05
            )
            repair_report.update({"accepted": accepted, "before": before_tail, "after": after_tail,
                                  "motionRetention": repair_motion,
                                  "acceptance": {
                                      "heldOutP99Reduction": 0.10,
                                      "maxAreaCollapseIncrease": 0.0001,
                                      "maxCollapsedEdgeFractionIncrease": 0.002,
                                      "minMotionEnergyRatio": 0.95,
                                  }})
            if accepted:
                learned = repaired
                candidate_tensor = repaired_tensor
                candidate_pose = repaired_pose
            else:
                repair_report["reason"] = "quality_gate_rejected"
        else:
            repair_report.setdefault("reason", "no_actionable_strain")
        pre_topology_candidate_tail = _strain_tail(
            np.asarray(skin["vertices"], dtype=np.float64), candidate_pose,
            np.asarray(skin["triangles"], dtype=np.int64),
        )
        base_vertices = np.asarray(skin["vertices"], dtype=np.float64)
        base_triangles = np.asarray(skin["triangles"], dtype=np.int64)
        base_uvs = np.asarray(skin["uvs"], dtype=np.float64)
        base_initial_weights = np.asarray(skin["weights"], dtype=np.float64)
        pre_split_learned = learned.copy()
        mesh_vertices, mesh_triangles, mesh_uvs, learned, seam_report = _split_strain_seams(
            base_vertices, base_triangles, base_uvs, learned,
            repair_report.get("detector", {}), max_cuts=256,
        )
        if seam_report["cutCount"]:
            initial_vertices, initial_triangles, initial_uvs, mesh_initial_weights, initial_seam = _split_strain_seams(
                base_vertices, base_triangles, base_uvs, base_initial_weights,
                repair_report.get("detector", {}), max_cuts=256,
            )
            if not (np.array_equal(mesh_vertices, initial_vertices)
                    and np.array_equal(mesh_triangles, initial_triangles)
                    and np.array_equal(mesh_uvs, initial_uvs)
                    and seam_report["cutCount"] == initial_seam["cutCount"]):
                raise ValueError("initial/candidate seam split topology diverged")
            split_pose = dual_quaternion_skin(
                torch.as_tensor(mesh_vertices, dtype=torch.float32, device="cuda"),
                torch.as_tensor(learned, dtype=torch.float32, device="cuda"), all_transforms,
            ).detach().cpu().numpy()
            split_tail = _strain_tail(mesh_vertices, split_pose, mesh_triangles)
            pre_tail = pre_topology_candidate_tail
            # Compare every face corner against its original correspondence;
            # original vertices alone omit the newly detached surface.
            seam_motion = _motion_retention(
                candidate_pose[:, base_triangles.reshape(-1)],
                split_pose[:, mesh_triangles.reshape(-1)],
            )
            seam_quality = {
                "p99Reduction": float(pre_tail["p99AbsLogStrain"] - split_tail["p99AbsLogStrain"]),
                "areaCollapseIncrease": float(split_tail["areaCollapseFraction"] - pre_tail["areaCollapseFraction"]),
                "collapsedEdgeIncrease": float(split_tail["collapsedEdgeFraction"] - pre_tail["collapsedEdgeFraction"]),
                "motionRetention": seam_motion,
            }
            seam_accepted = bool(
                split_tail["p99AbsLogStrain"] <= pre_tail["p99AbsLogStrain"] * 0.95
                and split_tail["areaCollapseFraction"] <= pre_tail["areaCollapseFraction"] + 1e-4
                and split_tail["collapsedEdgeFraction"] <= pre_tail["collapsedEdgeFraction"] + 0.002
                and seam_motion["p05EnergyRatio"] >= 0.95
            )
            seam_report.update({"accepted": seam_accepted, "qualityGate": seam_quality})
            if not seam_accepted:
                # Do not promote a topology cut merely because it ran.  Keep
                # the failed attempt in provenance while emitting the untouched
                # mesh and weights as the candidate.
                seam_report.update({"reason": "quality_gate_rejected",
                                    "attemptedCutCount": seam_report["cutCount"],
                                    "attemptedCuts": seam_report["cuts"],
                                    "cutCount": 0, "duplicatedVertexCount": 0, "cuts": []})
                mesh_vertices, mesh_triangles, mesh_uvs = base_vertices, base_triangles, base_uvs
                mesh_initial_weights, learned = base_initial_weights, pre_split_learned
        else:
            mesh_initial_weights = base_initial_weights
        validate_weights(learned, max_influences=int(max_influences))
        base_rest_tensor = torch.as_tensor(base_vertices, dtype=torch.float32, device="cuda")
        base_initial_tensor = torch.as_tensor(base_initial_weights, dtype=torch.float32, device="cuda")
        rest_tensor = torch.as_tensor(mesh_vertices, dtype=torch.float32, device="cuda")
        initial_tensor = torch.as_tensor(mesh_initial_weights, dtype=torch.float32, device="cuda")
        candidate_tensor = torch.as_tensor(learned, dtype=torch.float32, device="cuda")
        # Keep the untouched SmartRig baseline for the comparison column.  A
        # same-topology baseline is retained separately for motion-retention
        # accounting when seam splits add vertices.
        baseline_pose = dual_quaternion_skin(base_rest_tensor, base_initial_tensor, all_transforms).detach().cpu().numpy()
        topology_initial_pose = dual_quaternion_skin(rest_tensor, initial_tensor, all_transforms).detach().cpu().numpy()
        candidate_pose = dual_quaternion_skin(rest_tensor, candidate_tensor, all_transforms).detach().cpu().numpy()
        initial_motion = _motion_retention(topology_initial_pose, topology_initial_pose)
        candidate_motion = _motion_retention(topology_initial_pose, candidate_pose)
        report = {
            "proof": "generated-candidate",
            "visualAcceptance": "unreviewed",
            "asset": asset,
            "geometryMode": ("source_rest_autonomous_seam_split" if seam_report["cutCount"]
                             else "source_rest_immutable"),
            "motionOwner": "frozen_mocap_corpus",
            "skinningPolicy": "dual_quaternion_sequence_solve",
            "llmInLoop": False,
            "sourceMesh": str(profile["mesh"]).replace("\\", "/"),
            "sourceMeshSha256": str(profile["expectedMeshSha256"]),
            "structuredProfileSha256": profile.get("structuredProfileSha256"),
            "inputs": {"corpus": str(corpus_path), "corpusSha256": sha256_file(corpus_path),
                       "calibration": str(calibration_path), "calibrationSha256": sha256_file(calibration_path),
                       "researchSkin": str(Path(freeze["researchSkin"])),
                       "researchSkinSha256": sha256_file(Path(freeze["researchSkin"])),
                       "sourceFrameCount": len(referenced_frames)},
            "clipKeys": keys,
            "steps": int(steps),
            "history": history,
            "articulation": {"regionCount": len(region_ids), "children": [int(v) for v in region_children],
                             "assignment": "nearest_bind_mocap_segment"},
            "motionRetention": {"initial": initial_motion, "candidate": candidate_motion},
            "surface": {"initial": _surface_metrics(base_vertices, baseline_pose, base_triangles),
                        "candidate": _surface_metrics(mesh_vertices, candidate_pose, mesh_triangles)},
            "strainRepair": repair_report,
            "meshTopologyRepair": seam_report,
            "strainTail": {"initial": _strain_tail(base_vertices, baseline_pose, base_triangles),
                           "candidate": _strain_tail(mesh_vertices, candidate_pose, mesh_triangles),
                           "candidateBeforeTopologyRepair": pre_topology_candidate_tail},
            "weightDelta": {"meanAbs": float(np.abs(learned - mesh_initial_weights).mean()),
                            "maxAbs": float(np.abs(learned - mesh_initial_weights).max()),
                            "changedVertexFraction": float(np.mean(np.max(np.abs(learned - mesh_initial_weights), axis=1) > 1e-3))},
        }
        np.savez_compressed(
            output / "candidate_weights.npz",
            weights=learned,
            names=np.asarray(skin["names"]),
            parents=skin["parents"],
            vertices=mesh_vertices,
            triangles=mesh_triangles,
            uvs=mesh_uvs,
            offsets=np.asarray(skin["offsets"], dtype=np.float64),
            inverseBind=np.asarray(skin["inverseBind"], dtype=np.float64),
        )
        camera = json.loads((baseline_dir / "camera.json").read_text(encoding="utf-8"))
        baseline_renderer = SkinImageRenderer(base_triangles, base_uvs, skin["albedo"], camera, int(camera.get("resolution", 224)), device="cuda")
        renderer = SkinImageRenderer(mesh_triangles, mesh_uvs, skin["albedo"], camera, int(camera.get("resolution", 224)), device="cuda")
        cursor = 0
        report["clips"] = {}
        export_checks = {}
        preview_frames = []
        for key in keys:
            count = len(motions[key]["jointWorld"])
            local_transforms = all_transforms[cursor:cursor + count]
            preview_worlds, preview_style = _preview_worlds(motions[key], skin, key)
            preview_transforms = torch.as_tensor(
                preview_worlds @ np.asarray(skin["inverseBind"])[None], dtype=torch.float32, device="cuda"
            )
            with torch.no_grad():
                original = dual_quaternion_skin(base_rest_tensor, base_initial_tensor, preview_transforms)
                candidate = dual_quaternion_skin(rest_tensor, candidate_tensor, preview_transforms)
                original_rgb = baseline_renderer.render(original)[0].detach().cpu().numpy()
                candidate_rgb = renderer.render(candidate)[0].detach().cpu().numpy()
            source_rgb = source_images(frame_paths[key], camera["sourceCrop"], int(camera.get("resolution", 224)))[0].detach().cpu().numpy()
            _write_preview(output / f"{key}_comparison.gif", source_rgb, original_rgb, candidate_rgb, key)
            if key in FOCUS_CLIPS:
                preview_frames.extend([Image.fromarray(np.uint8(np.clip(frame, 0, 1) * 255)) for frame in candidate_rgb])
            times = np.arange(count, dtype=np.float32) * float(SOURCE_FRAME_MS) / 1000.0
            write_skinned_glb(
                output / f"{key}_candidate.glb", names=skin["names"], parents=skin["parents"],
                rest_local_rotation=np.repeat(np.eye(3)[None], len(skin["names"]), axis=0),
                rest_local_translation=skin["offsets"], inverse_bind=skin["inverseBind"],
                vertices=mesh_vertices, triangles=mesh_triangles, uvs=mesh_uvs,
                albedo=skin["albedo"], weights=learned,
                animation={"name": "smartrig_modified_mocap", "times": times,
                           "rotations": matrices_to_xyzw(motions[key]["localRotation"])},
            )
            exported = load_bind_skeleton(output / f"{key}_candidate.glb")
            name_to_expected = {str(name): index for index, name in enumerate(skin["names"])}
            name_to_loaded = {str(name): index for index, name in enumerate(exported.names)}
            loaded_weights = np.zeros_like(learned)
            joints = np.asarray(exported.vertex_joints, dtype=np.int64)
            values = np.asarray(exported.vertex_weights, dtype=np.float64)
            for slot in range(joints.shape[1]):
                loaded_joint_names = np.asarray(exported.names, dtype=object)[joints[:, slot]]
                expected_ids = np.fromiter((name_to_expected[str(name)] for name in loaded_joint_names), dtype=np.int64, count=len(loaded_joint_names))
                loaded_weights[np.arange(len(loaded_weights)), expected_ids] += values[:, slot]
            expected_parent_names = _parent_names(skin["names"], skin["parents"])
            loaded_parent_names = _parent_names(exported.names, exported.parents)
            hierarchy_ok = all(loaded_parent_names.get(name) == parent for name, parent in expected_parent_names.items())
            expected_inverse_by_name = {str(name): np.asarray(skin["inverseBind"])[index] for index, name in enumerate(skin["names"])}
            loaded_inverse_by_name = {str(name): np.asarray(exported.inverse_bind)[index] for index, name in enumerate(exported.names)}
            inverse_bind_error = max(
                float(np.max(np.abs(loaded_inverse_by_name[name] - expected_inverse_by_name[name])))
                for name in expected_parent_names
            )
            expected_offsets_by_name = {str(name): np.asarray(skin["offsets"])[index] for index, name in enumerate(skin["names"])}
            loaded_offsets_by_name = {str(name): np.asarray(exported.rest_local_translation)[index] for index, name in enumerate(exported.names)}
            offset_error = max(
                float(np.max(np.abs(loaded_offsets_by_name[name] - expected_offsets_by_name[name])))
                for name in expected_parent_names
            )
            rest_rotation_error = float(np.max(np.abs(np.asarray(exported.rest_local_rotation) - np.eye(3)[None])))
            bind_ok = bool(hierarchy_ok and inverse_bind_error <= 2e-5 and offset_error <= 2e-5 and rest_rotation_error <= 2e-5)
            expected_rotation_quat = matrices_to_xyzw(motions[key]["localRotation"])
            animation_check = _serialized_animation_check(output / f"{key}_candidate.glb", skin["names"], times, expected_rotation_quat)
            row_ok = (
                set(exported.names) == set(skin["names"])
                and np.allclose(np.asarray(exported.vertices), mesh_vertices, atol=2e-5, rtol=0.0)
                and np.allclose(loaded_weights, learned, atol=2e-5, rtol=0.0)
                and np.array_equal(np.asarray(exported.triangles), mesh_triangles)
                and exported.uvs is not None
                and np.asarray(exported.uvs).shape == mesh_uvs.shape
                and np.allclose(np.asarray(exported.uvs), mesh_uvs, atol=2e-5, rtol=0.0)
                and bind_ok
                and animation_check["ok"]
            )
            export_checks[key] = {
                "ok": bool(row_ok), "vertexCount": int(len(exported.vertices)),
                "jointCount": int(len(exported.names)), "weightMaxError": float(np.max(np.abs(loaded_weights - learned))),
                "hierarchyOk": hierarchy_ok, "bindOk": bind_ok,
                "inverseBindMaxError": inverse_bind_error, "offsetMaxError": offset_error,
                "restRotationMaxError": rest_rotation_error,
                "animationOk": bool(animation_check["ok"]),
                "animation": animation_check,
                "sha256": sha256_file(output / f"{key}_candidate.glb"),
            }
            if not row_ok:
                raise ValueError(f"serialized SmartRig modifier export failed readback: {key}")
            report["clips"][key] = {"frameCount": count, "candidateGlb": str(output / f"{key}_candidate.glb"),
                                    "motionSha256": hashlib.sha256(np.ascontiguousarray(motions[key]["jointWorld"]).tobytes()).hexdigest(),
                                    "animationQuaternionSha256": hashlib.sha256(np.ascontiguousarray(expected_rotation_quat).tobytes()).hexdigest(),
                                    "candidateGlbSha256": export_checks[key]["sha256"],
                                    "previewMotionStyle": preview_style}
            cursor += count
        if preview_frames:
            preview_frames[0].save(output / "focus_modified_animation.gif", save_all=True,
                                   append_images=preview_frames[1:], duration=int(round(SOURCE_FRAME_MS)), loop=0)
        report["focusPreview"] = str(output / "focus_modified_animation.gif")
        report["exportValidation"] = export_checks
        report["previewMotionStyle"] = {
            "profile": "stronghold_standard_v2", "gain": PREVIEW_STYLE_GAIN,
            "appliesTo": "preview-renders-only", "solveAndRawGlbUnchanged": True,
            "clipModes": {key: report["clips"][key]["previewMotionStyle"]["mode"] for key in keys},
        }
    report["exportParity"] = {
        "solver": "dual_quaternion",
        "serialized": "gltf_linear_blend",
        "status": "not_equivalent",
        "note": "GLB exports use standard glTF linear-blend skinning; DQ is limited to the camera-free solve and diagnostic preview.",
    }
    report["disposition"] = "candidate_requires_visual_review_nonparity_export"
    (output / "report.json").write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--max-influences", type=int, default=4)
    args = parser.parse_args()
    report = run(asset=args.asset, corpus_path=args.corpus.resolve(), baseline_dir=args.baseline_dir.resolve(),
                 output=args.out.resolve(), steps=args.steps, max_influences=args.max_influences)
    print(json.dumps({"report": str(args.out / "report.json"), "focusPreview": report["focusPreview"],
                      "disposition": report["disposition"]}, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
