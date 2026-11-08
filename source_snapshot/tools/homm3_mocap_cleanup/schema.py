"""Pipeline-native cleanup candidate for idle-0 mocap binds.

Allowed operations match what the bind/skin stages already do:

- one global skeleton similarity (yaw/pitch/roll, uniform scale, translation)
- per-bone bind-offset length scale (local translation only; rotation tracks stay)
- optional weight follow that redistributes existing chain mass onto new segments
- bind-proximity weight rewrite from explicit skinRules (distance, ownership, falloff, k)
- per-vertex weight set with renormalize
- trim one bone influence from a vertex, then renormalize

Per-bone rest *rotation* / Apply Pose as Rest Pose is not a cleanup operation.
It would orphan captured motion. This module never invents that path.

A saved candidate is generated-artifact only. It is not ship, not Unity, and
not consumed by the full-set scheduler until a separate apply gate exists.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

_MOCAP = Path(__file__).resolve().parents[2] / "experiments" / "homm3_mocap_v2"
if str(_MOCAP) not in sys.path:
    sys.path.insert(0, str(_MOCAP))

from static_bind_registration import apply_similarity, rotation_matrix

SCHEMA = "homm3.mocap-cleanup-candidate.v1"
PROOF = "generated-artifact"
MAX_INFLUENCES = 4
SKIN_DISTANCES = ("euclidean", "geodesic")
SKIN_OWNERSHIPS = ("outgoing", "incoming")
SKIN_SEEDS = ("largest_voronoi_component", "euclidean_voronoi")
SKIN_WELDS = ("coincident_agreeing_normals", "coincident", "export_position")
SKIN_CONNECTIONS = ("all_edges", "drop_narrow_incidental")
SKIN_FALLOFFS = ("inverse_square", "inverse", "gaussian")
SKIN_PRESETS = ("lab_fast", "pipeline_initializer", "surface_ignore_narrow", "custom")


class CleanupCandidateError(ValueError):
    """Raised when a cleanup payload or edit is not pipeline-legal."""


def default_skin_rules() -> dict[str, Any]:
    return {
        "preset": "lab_fast",
        "distance": "euclidean",
        "ownership": "outgoing",
        "seedPolicy": "largest_voronoi_component",
        "weldPolicy": "coincident_agreeing_normals",
        "connectionPolicy": "all_edges",
        "maxIncidentalCut": 6,
        "k": 4,
        "falloff": "inverse_square",
        "falloffSigma": 0.05,
        "maxDistance": 0.0,
        "excludedBones": [],
    }


def pipeline_initializer_skin_rules() -> dict[str, Any]:
    rules = default_skin_rules()
    rules["preset"] = "pipeline_initializer"
    rules["distance"] = "geodesic"
    rules["connectionPolicy"] = "all_edges"
    return rules


def surface_ignore_narrow_skin_rules() -> dict[str, Any]:
    rules = default_skin_rules()
    rules["preset"] = "surface_ignore_narrow"
    rules["distance"] = "geodesic"
    rules["connectionPolicy"] = "drop_narrow_incidental"
    return rules


def skin_rules_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("skinRules")
    if raw is None:
        return default_skin_rules()
    if not isinstance(raw, dict):
        raise CleanupCandidateError("skinRules must be an object")
    out = default_skin_rules()
    if "preset" in raw:
        preset = str(raw["preset"])
        if preset not in SKIN_PRESETS:
            raise CleanupCandidateError(f"skinRules.preset must be one of {list(SKIN_PRESETS)}")
        if preset == "pipeline_initializer":
            out = pipeline_initializer_skin_rules()
        elif preset == "surface_ignore_narrow":
            out = surface_ignore_narrow_skin_rules()
        elif preset == "lab_fast":
            out = default_skin_rules()
        else:
            out["preset"] = preset
    if "distance" in raw:
        distance = str(raw["distance"])
        if distance not in SKIN_DISTANCES:
            raise CleanupCandidateError(f"skinRules.distance must be one of {list(SKIN_DISTANCES)}")
        out["distance"] = distance
    if "ownership" in raw:
        ownership = str(raw["ownership"])
        if ownership not in SKIN_OWNERSHIPS:
            raise CleanupCandidateError(f"skinRules.ownership must be one of {list(SKIN_OWNERSHIPS)}")
        out["ownership"] = ownership
    if "seedPolicy" in raw:
        seed = str(raw["seedPolicy"])
        if seed not in SKIN_SEEDS:
            raise CleanupCandidateError(f"skinRules.seedPolicy must be one of {list(SKIN_SEEDS)}")
        out["seedPolicy"] = seed
    if "weldPolicy" in raw:
        weld = str(raw["weldPolicy"])
        if weld not in SKIN_WELDS:
            raise CleanupCandidateError(f"skinRules.weldPolicy must be one of {list(SKIN_WELDS)}")
        out["weldPolicy"] = weld
    if "connectionPolicy" in raw:
        connection = str(raw["connectionPolicy"])
        if connection not in SKIN_CONNECTIONS:
            raise CleanupCandidateError(f"skinRules.connectionPolicy must be one of {list(SKIN_CONNECTIONS)}")
        out["connectionPolicy"] = connection
    elif out["preset"] == "surface_ignore_narrow" or (
        out["distance"] == "geodesic" and out["preset"] != "pipeline_initializer"
    ):
        out["connectionPolicy"] = "drop_narrow_incidental"
    if "maxIncidentalCut" in raw:
        cut = int(raw["maxIncidentalCut"])
        if cut < 1 or cut > 16:
            raise CleanupCandidateError("skinRules.maxIncidentalCut must be 1..16")
        out["maxIncidentalCut"] = cut
    if "k" in raw:
        k = int(raw["k"])
        if k < 1 or k > 8:
            raise CleanupCandidateError("skinRules.k must be 1..8")
        out["k"] = k
    if "falloff" in raw:
        falloff = str(raw["falloff"])
        if falloff not in SKIN_FALLOFFS:
            raise CleanupCandidateError(f"skinRules.falloff must be one of {list(SKIN_FALLOFFS)}")
        out["falloff"] = falloff
    if "falloffSigma" in raw:
        sigma = float(raw["falloffSigma"])
        if not np.isfinite(sigma) or sigma <= 0.0:
            raise CleanupCandidateError("skinRules.falloffSigma must be finite and positive")
        out["falloffSigma"] = sigma
    if "maxDistance" in raw:
        limit = float(raw["maxDistance"])
        if not np.isfinite(limit) or limit < 0.0:
            raise CleanupCandidateError("skinRules.maxDistance must be finite and >= 0 (0 means no cutoff)")
        out["maxDistance"] = limit
    if "excludedBones" in raw:
        excluded = raw["excludedBones"]
        if not isinstance(excluded, list) or any(not str(name).strip() for name in excluded):
            raise CleanupCandidateError("skinRules.excludedBones must be a list of bone names")
        out["excludedBones"] = [str(name).strip() for name in excluded]
    return out


def identity_skeleton_delta() -> dict[str, Any]:
    return {
        "yawDeg": 0.0,
        "pitchDeg": 0.0,
        "rollDeg": 0.0,
        "scale": 1.0,
        "translation": [0.0, 0.0, 0.0],
    }


def skeleton_delta_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("skeletonDelta")
    if raw is None:
        return identity_skeleton_delta()
    if not isinstance(raw, dict):
        raise CleanupCandidateError("skeletonDelta must be an object")
    yaw = float(raw.get("yawDeg", 0.0))
    pitch = float(raw.get("pitchDeg", 0.0))
    roll = float(raw.get("rollDeg", 0.0))
    scale = float(raw.get("scale", 1.0))
    translation = np.asarray(raw.get("translation") or [0.0, 0.0, 0.0], dtype=np.float64).reshape(3)
    if not np.isfinite([yaw, pitch, roll, scale]).all() or not np.isfinite(translation).all():
        raise CleanupCandidateError("skeletonDelta values must be finite")
    if scale <= 0.0:
        raise CleanupCandidateError("skeletonDelta.scale must be positive")
    rotation_matrix(yaw, pitch, roll)
    return {
        "yawDeg": yaw,
        "pitchDeg": pitch,
        "rollDeg": roll,
        "scale": scale,
        "translation": translation.tolist(),
    }


def similarity_from_delta(delta: dict[str, Any]) -> dict[str, Any]:
    parsed = skeleton_delta_from_payload({"skeletonDelta": delta})
    rotation = rotation_matrix(parsed["yawDeg"], parsed["pitchDeg"], parsed["rollDeg"])
    return {
        "rotation": rotation,
        "scale": float(parsed["scale"]),
        "translation": np.asarray(parsed["translation"], dtype=np.float64),
        "yawDeg": parsed["yawDeg"],
        "pitchDeg": parsed["pitchDeg"],
        "rollDeg": parsed["rollDeg"],
    }


def compose_similarity(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Apply delta after base: x' = s_d R_d (s_b R_b x + t_b) + t_d."""
    base_rot = np.asarray(base["rotation"], dtype=np.float64)
    delta_sim = similarity_from_delta(delta)
    rotation = delta_sim["rotation"] @ base_rot
    scale = float(delta_sim["scale"]) * float(base["scale"])
    translation = delta_sim["scale"] * (delta_sim["rotation"] @ np.asarray(base["translation"], dtype=np.float64))
    translation = translation + delta_sim["translation"]
    if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-5:
        raise CleanupCandidateError("composed rotation is not a proper rotation")
    if scale <= 0.0 or not np.isfinite(scale) or not np.isfinite(translation).all():
        raise CleanupCandidateError("composed similarity is not finite and positive")
    return {
        "rotation": rotation,
        "scale": scale,
        "translation": translation,
    }


def apply_points(points: np.ndarray, delta: dict[str, Any]) -> np.ndarray:
    sim = similarity_from_delta(delta)
    return apply_similarity(
        points,
        rotation=sim["rotation"],
        scale=sim["scale"],
        translation=sim["translation"],
    )


def _require_dense_weights(weights: np.ndarray, names: list[str]) -> np.ndarray:
    matrix = np.asarray(weights, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(names):
        raise CleanupCandidateError(f"weights must be [V,{len(names)}], got {matrix.shape}")
    if not np.isfinite(matrix).all():
        raise CleanupCandidateError("weights must be finite")
    if np.any(matrix < -1e-12):
        raise CleanupCandidateError("weights must be non-negative")
    return matrix


def _bone_index(names: list[str], bone: str) -> int:
    try:
        return names.index(bone)
    except ValueError as exc:
        raise CleanupCandidateError(f"unknown bone {bone!r}") from exc


def _renormalize_row(row: np.ndarray) -> np.ndarray:
    total = float(row.sum())
    if total <= 1e-12:
        raise CleanupCandidateError("vertex has no remaining bone influence after edit")
    return row / total


def set_vertex_weight(weights: np.ndarray, names: list[str], *, vertex: int, bone: str, value: float) -> np.ndarray:
    matrix = _require_dense_weights(weights, names).copy()
    if vertex < 0 or vertex >= matrix.shape[0]:
        raise CleanupCandidateError(f"vertex {vertex} is out of range")
    if not np.isfinite(value) or value < 0.0:
        raise CleanupCandidateError("weight value must be finite and >= 0")
    matrix[vertex, _bone_index(names, bone)] = float(value)
    matrix[vertex] = _renormalize_row(matrix[vertex])
    return matrix


def trim_vertex_influence(weights: np.ndarray, names: list[str], *, vertex: int, bone: str) -> np.ndarray:
    return set_vertex_weight(weights, names, vertex=vertex, bone=bone, value=0.0)


def bone_lengths_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("boneLengths")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CleanupCandidateError("boneLengths must be an object of bone name -> scale")
    out: dict[str, float] = {}
    for name, value in raw.items():
        bone = str(name).strip()
        scale = float(value)
        if not bone:
            raise CleanupCandidateError("boneLengths keys must be bone names")
        if not np.isfinite(scale) or scale <= 0.0:
            raise CleanupCandidateError(f"boneLengths[{bone!r}] must be finite and positive")
        out[bone] = scale
    return out


def weight_override_from_payload(payload: dict[str, Any]) -> dict[str, list[list[float]]] | None:
    raw = payload.get("weightOverride")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CleanupCandidateError("weightOverride must be an object with joints and weights")
    joints = raw.get("joints")
    weights = raw.get("weights")
    if not isinstance(joints, list) or not isinstance(weights, list):
        raise CleanupCandidateError("weightOverride.joints and weightOverride.weights must be lists")
    if len(joints) != len(weights) or not joints:
        raise CleanupCandidateError("weightOverride joints/weights must be non-empty and the same length")
    slots = len(joints[0]) if isinstance(joints[0], list) else -1
    if slots < 1 or slots > 8:
        raise CleanupCandidateError("weightOverride row width must be 1..8")
    for index, (joint_row, weight_row) in enumerate(zip(joints, weights)):
        if not isinstance(joint_row, list) or not isinstance(weight_row, list):
            raise CleanupCandidateError(f"weightOverride row {index} must be lists")
        if len(joint_row) != slots or len(weight_row) != slots:
            raise CleanupCandidateError(f"weightOverride row {index} width must stay {slots}")
        if any(int(joint) < 0 for joint in joint_row):
            raise CleanupCandidateError(f"weightOverride.joints[{index}] must be >= 0")
        if not np.isfinite(np.asarray(weight_row, dtype=np.float64)).all():
            raise CleanupCandidateError(f"weightOverride.weights[{index}] must be finite")
        if np.any(np.asarray(weight_row, dtype=np.float64) < -1e-12):
            raise CleanupCandidateError(f"weightOverride.weights[{index}] must be >= 0")
    return {"joints": joints, "weights": weights}


def apply_bone_length_offsets(
    bind_offsets: np.ndarray,
    current_offsets: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    """Keep translation *deltas* from the clip; scale only the bind offset.

    new = scale * bind + (current - bind)
    Local rotations are untouched. That is the captured relative motion.
    """
    bind = np.asarray(bind_offsets, dtype=np.float64)
    current = np.asarray(current_offsets, dtype=np.float64)
    scale = np.asarray(scales, dtype=np.float64)
    if bind.shape != current.shape or bind.ndim != 2 or bind.shape[1] != 3:
        raise CleanupCandidateError("bone offsets must be [J,3]")
    if scale.shape != (bind.shape[0],):
        raise CleanupCandidateError("bone length scales must be [J]")
    if not np.isfinite(bind).all() or not np.isfinite(current).all() or not np.isfinite(scale).all():
        raise CleanupCandidateError("bone length inputs must be finite")
    if np.any(scale <= 0.0):
        raise CleanupCandidateError("bone length scales must be positive")
    return scale[:, None] * bind + (current - bind)


def _segment_distance(vertices: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    start = np.asarray(start, dtype=np.float64).reshape(3)
    end = np.asarray(end, dtype=np.float64).reshape(3)
    vertices = np.asarray(vertices, dtype=np.float64)
    segment = end - start
    length_sq = float(segment @ segment)
    if length_sq <= 1e-16:
        return np.linalg.norm(vertices - start, axis=1)
    t = np.clip(((vertices - start) @ segment) / length_sq, 0.0, 1.0)
    closest = start + t[:, None] * segment
    return np.linalg.norm(vertices - closest, axis=1)


def bone_segment_distances(
    vertices: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    ownership: str = "outgoing",
) -> np.ndarray:
    """Joint j owns its FK bone segment. Leaves use the joint point."""
    if ownership not in SKIN_OWNERSHIPS:
        raise CleanupCandidateError(f"ownership must be one of {list(SKIN_OWNERSHIPS)}")
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3 or vertices.ndim != 2 or vertices.shape[1] != 3:
        raise CleanupCandidateError("joints and vertices must be [N,3]")
    if parents.shape != (len(joints),):
        raise CleanupCandidateError("parents must be [J]")
    dist = np.full((len(vertices), len(joints)), np.inf, dtype=np.float64)
    if ownership == "incoming":
        for index in range(len(joints)):
            parent = int(parents[index])
            start = joints[parent] if parent >= 0 else joints[index]
            dist[:, index] = _segment_distance(vertices, start, joints[index])
        return dist
    return outgoing_segment_distances(vertices, joints, parents)


def outgoing_segment_distances(vertices: np.ndarray, joints: np.ndarray, parents: np.ndarray) -> np.ndarray:
    """Joint j owns the segment from j to each child. Leaves use the joint point.

    The parent cedes the distal cap of a leaf so surface seeds can start there.
    """
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3 or vertices.ndim != 2 or vertices.shape[1] != 3:
        raise CleanupCandidateError("joints and vertices must be [N,3]")
    if parents.shape != (len(joints),):
        raise CleanupCandidateError("parents must be [J]")
    dist = np.full((len(vertices), len(joints)), np.inf, dtype=np.float64)
    children: list[list[int]] = [[] for _ in joints]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            children[int(parent)].append(index)
    usable = [
        [child for child in kids if float(np.linalg.norm(joints[child] - joints[joint]) ** 2) > 1e-16]
        for joint, kids in enumerate(children)
    ]
    is_leaf = [len(kids) == 0 for kids in usable]
    for joint, kids in enumerate(usable):
        if not kids:
            dist[:, joint] = np.linalg.norm(vertices - joints[joint], axis=1)
            continue
        stacked = []
        for child in kids:
            segment = _segment_distance(vertices, joints[joint], joints[child])
            if is_leaf[child]:
                tip = np.linalg.norm(vertices - joints[child], axis=1)
                segment = np.where(tip <= segment + 1e-12, np.inf, segment)
            stacked.append(segment)
        dist[:, joint] = np.min(np.stack(stacked, axis=1), axis=1)
    return dist


def rewrite_weights_from_bind(
    vertices: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    k: int = 4,
    names: list[str] | None = None,
    rules: dict[str, Any] | None = None,
    triangles: np.ndarray | None = None,
) -> np.ndarray:
    """Replace every vertex's weights from the current rest bind and skinRules."""
    joint_count = int(np.asarray(joints).shape[0])
    if names is None:
        names = [str(index) for index in range(joint_count)]
    payload = default_skin_rules() if rules is None else dict(rules)
    payload["k"] = int(k if rules is None else payload.get("k", k))
    return apply_skin_rules(
        vertices,
        joints,
        parents,
        names,
        payload,
        triangles=triangles,
    )


def nearest_from_distance(
    dist: np.ndarray,
    *,
    k: int,
    falloff: str = "inverse_square",
    sigma: float = 0.05,
) -> np.ndarray:
    dist = np.asarray(dist, dtype=np.float64)
    if dist.ndim != 2 or k < 1 or k > dist.shape[1]:
        raise CleanupCandidateError("nearest-segment k is out of range")
    if falloff not in SKIN_FALLOFFS:
        raise CleanupCandidateError(f"unknown falloff {falloff!r}")
    finite = np.isfinite(dist).sum(axis=1)
    if int(finite.min()) < 1:
        raise CleanupCandidateError("a vertex has no reachable bone segment")
    k_use = min(int(k), int(dist.shape[1]))
    safe = np.where(np.isfinite(dist), dist, 1e12)
    nearest = np.argpartition(safe, kth=k_use - 1, axis=1)[:, :k_use]
    picked = np.take_along_axis(dist, nearest, axis=1)
    valid = np.isfinite(picked)
    if falloff == "inverse_square":
        raw = 1.0 / (picked * picked + 1e-8)
    elif falloff == "inverse":
        raw = 1.0 / (picked + 1e-8)
    else:
        if not np.isfinite(sigma) or sigma <= 0.0:
            raise CleanupCandidateError("gaussian falloffSigma must be finite and positive")
        raw = np.exp(-(picked * picked) / (2.0 * sigma * sigma))
    weights = np.where(valid, raw, 0.0)
    total = weights.sum(axis=1, keepdims=True)
    if np.any(total <= 1e-12):
        raise CleanupCandidateError("a vertex has no reachable bone segment")
    weights = weights / total
    dense = np.zeros_like(dist)
    rows = np.repeat(np.arange(len(dist)), k_use)
    dense[rows, nearest.reshape(-1)] = weights.reshape(-1)
    return dense


def nearest_segment_weights(dist: np.ndarray, *, k: int = 4) -> np.ndarray:
    return nearest_from_distance(dist, k=k, falloff="inverse_square")


def apply_skin_rules(
    vertices: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    rules: dict[str, Any],
    *,
    triangles: np.ndarray | None = None,
    progress: Any = None,
) -> np.ndarray:
    """Build dense weights from a bind and an explicit skin-rule recipe."""
    def report(fraction: float, message: str) -> None:
        if progress is None:
            return
        progress(float(np.clip(fraction, 0.0, 1.0)), message)

    recipe = skin_rules_from_payload({"skinRules": rules})
    if len(names) != len(joints):
        raise CleanupCandidateError("skin rule bone names must match joint count")
    unknown = [name for name in recipe["excludedBones"] if name not in names]
    if unknown:
        raise CleanupCandidateError(f"skinRules.excludedBones names unknown bones: {unknown}")
    report(0.05, "measuring bone segments")
    dist = bone_segment_distances(vertices, joints, parents, ownership=recipe["ownership"])
    report(0.2, "bone segments ready")
    if recipe["distance"] == "geodesic":
        if triangles is None:
            raise CleanupCandidateError("geodesic skinRules require triangle faces")
        from prepare_move_bind_capture_bind import geodesic_bone_distances
        if recipe["connectionPolicy"] == "drop_narrow_incidental":
            report(0.22, "dropping narrow incidental contacts")

        def on_bone(done: int, total: int) -> None:
            report(0.2 + 0.7 * (done / max(total, 1)), f"surface bone {done}/{total}")

        geo = geodesic_bone_distances(
            vertices,
            triangles,
            dist,
            seed_policy=recipe["seedPolicy"],
            weld_policy=recipe["weldPolicy"],
            connection_policy=recipe["connectionPolicy"],
            max_incidental_cut=int(recipe["maxIncidentalCut"]),
            progress=on_bone,
        )
        dist = geo["distances"]
    report(0.92, "packing weights")
    if recipe["excludedBones"]:
        exclude = [names.index(name) for name in recipe["excludedBones"]]
        dist = dist.copy()
        dist[:, exclude] = np.inf
    if recipe["maxDistance"] > 0.0:
        dist = np.where(dist > recipe["maxDistance"], np.inf, dist)
    packed = nearest_from_distance(
        dist,
        k=min(int(recipe["k"]), dist.shape[1]),
        falloff=recipe["falloff"],
        sigma=float(recipe["falloffSigma"]),
    )
    report(1.0, "weights ready")
    return packed


def pack_dense_weights(dense: np.ndarray, *, slots: int) -> dict[str, list[list[float]]]:
    matrix = np.asarray(dense, dtype=np.float64)
    if matrix.ndim != 2 or slots < 1 or slots > 8:
        raise CleanupCandidateError("packed weight slots must be 1..8")
    order = np.argpartition(-matrix, kth=min(slots, matrix.shape[1]) - 1, axis=1)[:, :slots]
    picked = np.take_along_axis(matrix, order, axis=1)
    totals = picked.sum(axis=1, keepdims=True)
    if np.any(totals <= 1e-12):
        raise CleanupCandidateError("a packed weight row sums to zero")
    picked = picked / totals
    return {"joints": order.astype(int).tolist(), "weights": picked.tolist()}


def shift_chain_weights(old_weights: np.ndarray, proximity: np.ndarray, chain: list[int]) -> np.ndarray:
    """Keep each vertex's mass on a bone chain; slide that mass to the new segments."""
    old = _require_dense_weights(old_weights, [str(i) for i in range(np.asarray(old_weights).shape[1])])
    prox = np.asarray(proximity, dtype=np.float64)
    if prox.shape != old.shape:
        raise CleanupCandidateError("proximity must match weights")
    if not chain:
        raise CleanupCandidateError("weight-follow chain is empty")
    if any(index < 0 or index >= old.shape[1] for index in chain):
        raise CleanupCandidateError("weight-follow chain index is out of range")
    out = old.copy()
    chain_idx = np.asarray(chain, dtype=np.int64)
    old_mass = old[:, chain_idx].sum(axis=1)
    new_mass = prox[:, chain_idx].sum(axis=1)
    movable = (old_mass > 1e-8) & (new_mass > 1e-8)
    if not np.any(movable):
        return out
    scaled = prox[movable][:, chain_idx] * (old_mass[movable] / new_mass[movable])[:, None]
    out[np.ix_(np.flatnonzero(movable), chain_idx)] = scaled
    for row in np.flatnonzero(movable):
        out[row] = _renormalize_row(out[row])
    return out


def brush_target_weight(
    current: float,
    *,
    mode: str,
    strength: float,
    falloff: float,
    replace_value: float = 1.0,
) -> float:
    if mode not in {"add", "subtract", "replace"}:
        raise CleanupCandidateError(f"brush mode must be add, subtract, or replace, got {mode!r}")
    if not np.isfinite([current, strength, falloff, replace_value]).all():
        raise CleanupCandidateError("brush values must be finite")
    if min(strength, falloff, replace_value, current) < -1e-12:
        raise CleanupCandidateError("brush values must be non-negative")
    amount = float(np.clip(strength, 0.0, 1.0) * np.clip(falloff, 0.0, 1.0))
    current = float(np.clip(current, 0.0, 1.0))
    replace_value = float(np.clip(replace_value, 0.0, 1.0))
    if mode == "add":
        return float(min(1.0, current + amount))
    if mode == "subtract":
        return float(max(0.0, current - amount))
    return float(current * (1.0 - amount) + replace_value * amount)


def packed_set_weight(
    joints: np.ndarray,
    weights: np.ndarray,
    *,
    bone_index: int,
    value: float,
    joint_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Edit one vertex's 4-influence glTF packing, then renormalize."""
    joints = np.asarray(joints, dtype=np.int64).reshape(MAX_INFLUENCES).copy()
    weights = np.asarray(weights, dtype=np.float64).reshape(MAX_INFLUENCES).copy()
    if bone_index < 0 or bone_index >= joint_count:
        raise CleanupCandidateError(f"bone index {bone_index} is out of range")
    if not np.isfinite(value) or value < 0.0:
        raise CleanupCandidateError("weight value must be finite and >= 0")
    if value == 0.0:
        weights[joints == bone_index] = 0.0
        return joints, _renormalize_row(np.maximum(weights, 0.0))
    slots = np.where(joints == bone_index)[0]
    if slots.size:
        weights[slots[0]] = float(value)
    else:
        weakest = int(np.argmin(weights))
        joints[weakest] = int(bone_index)
        weights[weakest] = float(value)
    return joints, _renormalize_row(np.maximum(weights, 0.0))


def packed_trim_influence(
    joints: np.ndarray,
    weights: np.ndarray,
    *,
    bone_index: int,
) -> tuple[np.ndarray, np.ndarray]:
    joints = np.asarray(joints, dtype=np.int64).reshape(MAX_INFLUENCES).copy()
    weights = np.asarray(weights, dtype=np.float64).reshape(MAX_INFLUENCES).copy()
    weights[joints == bone_index] = 0.0
    return joints, _renormalize_row(np.maximum(weights, 0.0))


def validate_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CleanupCandidateError("candidate must be an object")
    if payload.get("schema") != SCHEMA:
        raise CleanupCandidateError(f"schema must be {SCHEMA}")
    if payload.get("proof") != PROOF:
        raise CleanupCandidateError(f"proof must be {PROOF}")
    if payload.get("accepted") is True:
        raise CleanupCandidateError("cleanup candidates cannot self-accept")
    unit = str(payload.get("unit") or "").strip()
    if not unit:
        raise CleanupCandidateError("unit is required")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise CleanupCandidateError("source must be an object")
    for key in ("bindGlb", "bindSha256", "registration", "registrationSha256", "clip"):
        if not str(source.get(key) or "").strip():
            raise CleanupCandidateError(f"source.{key} is required")
    skeleton_delta_from_payload(payload)
    bone_lengths_from_payload(payload)
    skin_rules_from_payload(payload)
    follow = payload.get("weightFollowJoints")
    if follow is None:
        follow = False
    if not isinstance(follow, bool):
        raise CleanupCandidateError("weightFollowJoints must be a boolean")
    weight_override_from_payload(payload)
    rewrite = payload.get("weightRewriteFromBind")
    if rewrite is None:
        rewrite = False
    if not isinstance(rewrite, bool):
        raise CleanupCandidateError("weightRewriteFromBind must be a boolean")
    if (follow or rewrite) and payload.get("weightOverride") is None:
        raise CleanupCandidateError(
            "weightFollowJoints / weightRewriteFromBind requires weightOverride of the previewed packed weights"
        )
    edits = payload.get("edits")
    if edits is None:
        edits = []
    if not isinstance(edits, list):
        raise CleanupCandidateError("edits must be a list")
    allowed = {"weight_set", "influence_trim"}
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise CleanupCandidateError(f"edits[{index}] must be an object")
        kind = edit.get("op")
        if kind not in allowed:
            raise CleanupCandidateError(f"edits[{index}].op must be one of {sorted(allowed)}")
        if int(edit.get("vertex", -1)) < 0:
            raise CleanupCandidateError(f"edits[{index}].vertex must be >= 0")
        if not str(edit.get("bone") or "").strip():
            raise CleanupCandidateError(f"edits[{index}].bone is required")
        if kind == "weight_set" and (not np.isfinite(float(edit.get("value", 0.0))) or float(edit["value"]) < 0.0):
            raise CleanupCandidateError(f"edits[{index}].value must be finite and >= 0")
    return payload


def apply_edits(weights: np.ndarray, names: list[str], edits: list[dict[str, Any]]) -> np.ndarray:
    matrix = _require_dense_weights(weights, names)
    for edit in edits:
        op = edit["op"]
        vertex = int(edit["vertex"])
        bone = str(edit["bone"])
        if op == "weight_set":
            matrix = set_vertex_weight(matrix, names, vertex=vertex, bone=bone, value=float(edit["value"]))
        elif op == "influence_trim":
            matrix = trim_vertex_influence(matrix, names, vertex=vertex, bone=bone)
        else:
            raise CleanupCandidateError(f"unsupported edit op {op!r}")
    return matrix


def new_candidate(
    *,
    unit: str,
    source: dict[str, Any],
    skeleton_delta: dict[str, Any] | None = None,
    bone_lengths: dict[str, float] | None = None,
    weight_follow_joints: bool = False,
    weight_rewrite_from_bind: bool = False,
    weight_override: dict[str, Any] | None = None,
    skin_rules: dict[str, Any] | None = None,
    edits: list[dict[str, Any]] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    payload = {
        "schema": SCHEMA,
        "proof": PROOF,
        "accepted": False,
        "consumable": False,
        "unit": unit,
        "source": source,
        "skeletonDelta": skeleton_delta_from_payload({"skeletonDelta": skeleton_delta or identity_skeleton_delta()}),
        "boneLengths": bone_lengths_from_payload({"boneLengths": bone_lengths or {}}),
        "weightFollowJoints": bool(weight_follow_joints),
        "weightRewriteFromBind": bool(weight_rewrite_from_bind),
        "weightOverride": weight_override_from_payload({"weightOverride": weight_override}),
        "skinRules": skin_rules_from_payload({"skinRules": skin_rules}),
        "edits": list(edits or []),
        "notes": notes,
        "opsOwned": [
            "global_skeleton_similarity",
            "bind_offset_length_scale",
            "chain_weight_follow",
            "bind_proximity_weight_rewrite",
            "bind_skin_rules",
            "per_vertex_weight_set",
            "per_vertex_influence_trim",
        ],
        "opsRefused": [
            "per_bone_rest_rotation",
            "apply_pose_as_rest",
            "overwrite_scheduler_run",
        ],
    }
    return validate_candidate(payload)
