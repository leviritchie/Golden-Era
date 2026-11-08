"""Clip/joint plan and acceptance gates for linked-master pose refinement.

This stage is explicitly selected. It does not replace capture motion inside the
skin-only solver. Wing joints come from profile `regionJoints` keys that start
with `wing_`; no Roc bone names are hard-coded.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from mesh_preview import rotation_between
from pose_rotation_fk import TWIST_POLICY, so3_geodesic_np

SCHEMA = "homm3.linked-master-pose-refine.v2"
SCHEMA_V1 = "homm3.linked-master-pose-refine.v1"
MOTION_OWNER = "refined_local_rotations_from_linked_master_capture"
IDLE_GROUP = 2
MOVE_GROUP = 0
MOVE_START_GROUP = 20
MOVE_END_GROUP = 21
START_COUNT = 5
SECONDS_PER_START = 24.0
# One wing may fold; collapse is a severe span drop on that wing alone.
COLLAPSE_SPAN_RATIO = 0.25
# Absolute log length-ratio slack vs the original posed mesh, per wing/frame.
ABS_LOG_RATIO_SLACK = 1e-6
TRIANGLE_AREA_RATIO_MIN = 0.15
INTERIOR_FRACTION_SLACK = 0.05
IDLE_MEAN_IOU_GAIN = 0.01
CONTINUITY_GEODESIC_SLACK = 0.12
CONTINUITY_SURFACE_SLACK = 0.02
IOU_REGRESSION_SLACK = 1e-6
ANCHOR_MATRIX_SLACK = 1e-6


def require_cycle(master: dict[str, Any], def_group: int, label: str) -> dict[str, Any]:
    matches = [
        segment
        for segment in master["segments"]
        if int(segment["defGroup"]) == int(def_group) and segment.get("exportsClip")
    ]
    if len(matches) != 1:
        raise ValueError(f"linked master must export exactly one {label} cycle, found {len(matches)}")
    return matches[0]


def pilot_frame_plan(master: dict[str, Any]) -> dict[str, Any]:
    """Idle cycle + native takeoff/landing. Move stays exact; adjacent endpoints stay original."""
    idle = require_cycle(master, IDLE_GROUP, "Idle")
    start = require_cycle(master, MOVE_START_GROUP, "MoveStart")
    move = require_cycle(master, MOVE_GROUP, "Move")
    end = require_cycle(master, MOVE_END_GROUP, "MoveEnd")
    if int(start["globalEnd"]) != int(move["globalStart"]) or int(move["globalEnd"]) != int(end["globalStart"]):
        raise ValueError("MoveStart / Move / MoveEnd must be contiguous in the reel")

    def span(segment: dict[str, Any]) -> list[int]:
        return list(range(int(segment["globalStart"]), int(segment["globalEnd"])))

    idle_frames = span(idle)
    start_frames = span(start)
    move_frames = span(move)
    end_frames = span(end)
    if not idle_frames or len(start_frames) < 2 or not move_frames or len(end_frames) < 2:
        raise ValueError("idle/move-start/move/move-end spans are too short for a transition-anchored pilot")
    adjacent_to_move = (start_frames[-1], end_frames[0])
    pinned = sorted(set(move_frames) | set(adjacent_to_move))
    free = sorted(set(idle_frames + start_frames + end_frames) - set(pinned))
    optimize = sorted(set(idle_frames + start_frames + end_frames))
    clips = {
        "idle": {"clipKey": idle["clipKey"], "defGroup": IDLE_GROUP, "frames": idle_frames, "regularize": True},
        "move_start": {"clipKey": start["clipKey"], "defGroup": MOVE_START_GROUP, "frames": start_frames, "regularize": True},
        "move": {"clipKey": move["clipKey"], "defGroup": MOVE_GROUP, "frames": move_frames, "regularize": False},
        "move_end": {"clipKey": end["clipKey"], "defGroup": MOVE_END_GROUP, "frames": end_frames, "regularize": True},
    }
    return {
        "clips": clips,
        "optimizeFrames": optimize,
        "freeFrames": free,
        "pinnedFrames": pinned,
        "moveFrames": move_frames,
        "adjacentToMove": list(adjacent_to_move),
        "regularizePairs": temporal_pairs(clips),
        "twistPolicy": TWIST_POLICY,
    }


def temporal_pairs(clips: dict[str, dict[str, Any]]) -> list[tuple[int, int]]:
    """Consecutive frames inside a real clip only. Reel cuts are not regularized."""
    pairs: list[tuple[int, int]] = []
    for clip in clips.values():
        if not clip["regularize"]:
            continue
        frames = clip["frames"]
        pairs.extend((frames[index], frames[index + 1]) for index in range(len(frames) - 1))
    return pairs


def wing_region_keys(region_joints: dict[str, Any]) -> list[str]:
    keys = sorted(str(key) for key in region_joints if str(key).startswith("wing_"))
    if not keys:
        raise ValueError("profile regionJoints has no wing_* region; this pilot will not invent other limbs")
    return keys


def wing_joint_indices(names: list[str], region_joints: dict[str, Any]) -> dict[str, Any]:
    keys = wing_region_keys(region_joints)
    index = {name: i for i, name in enumerate(names)}
    by_region: dict[str, list[int]] = {}
    ordered: list[int] = []
    seen: set[int] = set()
    for key in keys:
        members: list[int] = []
        for bone in region_joints[key]:
            if bone not in index:
                raise ValueError(f"wing region {key} names unknown capture joint {bone!r}")
            joint = index[bone]
            if joint in seen:
                raise ValueError(f"joint {bone} is listed in more than one wing region")
            seen.add(joint)
            members.append(joint)
            ordered.append(joint)
        if not members:
            raise ValueError(f"wing region {key} is empty")
        by_region[key] = members
    protected = [i for i in range(len(names)) if i not in seen]
    return {
        "regionKeys": keys,
        "indices": ordered,
        "names": [names[i] for i in ordered],
        "byRegion": {key: [names[i] for i in members] for key, members in by_region.items()},
        "byRegionIndex": by_region,
        "protectedIndices": protected,
        "protectedNames": [names[i] for i in protected],
    }


def proximal_wing_joints(parents: np.ndarray, by_region_index: dict[str, list[int]]) -> dict[str, int]:
    """First joint of each wing whose parent is outside that wing."""
    parent = np.asarray(parents, dtype=np.int64)
    proximal: dict[str, int] = {}
    for key, members in by_region_index.items():
        member_set = set(members)
        roots = [index for index in members if int(parent[index]) < 0 or int(parent[index]) not in member_set]
        if len(roots) != 1:
            raise ValueError(f"wing region {key} must have exactly one proximal joint, found {len(roots)}")
        proximal[key] = roots[0]
    return proximal


def distal_wing_joints(parents: np.ndarray, by_region_index: dict[str, list[int]]) -> dict[str, int]:
    """Wing joint farthest from the proximal joint along the parent walk."""
    parent = np.asarray(parents, dtype=np.int64)
    proximal = proximal_wing_joints(parents, by_region_index)
    distal: dict[str, int] = {}
    for key, members in by_region_index.items():
        root = proximal[key]
        best, best_hops = root, -1
        for joint in members:
            hops, cursor = 0, joint
            seen: set[int] = set()
            while cursor != root:
                if cursor in seen or int(parent[cursor]) < 0:
                    hops = -1
                    break
                seen.add(cursor)
                cursor = int(parent[cursor])
                hops += 1
            if hops > best_hops:
                best, best_hops = joint, hops
        distal[key] = best
    return distal


def fold_toward_torso_deltas(
    *,
    local: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
    names: list[str],
    region_joints: dict[str, Any],
    free_frames: list[int],
    amount: float,
    mid_amount: float = 0.0,
) -> np.ndarray:
    """Deterministic inward swing from each wing's own geometry. No mirrored copy."""
    from mesh_preview import fk_world_matrices

    wings = wing_joint_indices(names, region_joints)
    proximal = proximal_wing_joints(parents, wings["byRegionIndex"])
    distal = distal_wing_joints(parents, wings["byRegionIndex"])
    torso_names = [str(bone) for bone in region_joints.get("torso", ())]
    if not torso_names:
        raise ValueError("profile regionJoints has no torso region to aim a fold toward")
    name_index = {name: i for i, name in enumerate(names)}
    torso = [name_index[name] for name in torso_names]
    parent = np.asarray(parents, dtype=np.int64)
    rest_off = np.asarray(offsets, dtype=np.float64).copy()
    rest_off[0] = 0.0
    omega = np.zeros((len(free_frames), len(wings["indices"]), 3), dtype=np.float64)
    joint_slot = {joint: slot for slot, joint in enumerate(wings["indices"])}
    for row, frame in enumerate(free_frames):
        world = fk_world_matrices(
            local_rotation=local[frame],
            local_translation=rest_off,
            parents=parent,
            root_world=root_world[frame],
        )
        torso_centroid = world[torso, :3, 3].mean(axis=0)
        for key, prox in proximal.items():
            tip = distal[key]
            parent_index = int(parent[prox])
            parent_rot = np.eye(3) if parent_index < 0 else world[parent_index, :3, :3]
            wing_dir = parent_rot.T @ (world[tip, :3, 3] - world[prox, :3, 3])
            fold_dir = parent_rot.T @ (torso_centroid - world[prox, :3, 3])
            extra = rotation_between(wing_dir, fold_dir)
            axis_angle = _log_so3(extra) * float(amount)
            omega[row, joint_slot[prox]] = axis_angle
            if mid_amount:
                mids = [joint for joint in wings["byRegionIndex"][key] if joint != prox and joint != tip]
                for joint in mids:
                    parent_j = int(parent[joint])
                    parent_rot_j = np.eye(3) if parent_j < 0 else world[parent_j, :3, :3]
                    extra_j = reframe_parent_rotation(extra, parent_rot, parent_rot_j)
                    omega[row, joint_slot[joint]] = _log_so3(extra_j) * float(mid_amount)
    return omega


def reframe_parent_rotation(extra_from: np.ndarray, parent_from: np.ndarray, parent_to: np.ndarray) -> np.ndarray:
    """Express a parent-frame extra rotation in another joint's parent frame."""
    source = np.asarray(parent_from, dtype=np.float64).reshape(3, 3)
    dest = np.asarray(parent_to, dtype=np.float64).reshape(3, 3)
    extra = np.asarray(extra_from, dtype=np.float64).reshape(3, 3)
    world = source @ extra @ source.T
    return dest.T @ world @ dest


def _log_so3(matrix: np.ndarray) -> np.ndarray:
    rotation = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    cosine = float(np.clip((np.trace(rotation) - 1.0) * 0.5, -1.0, 1.0))
    angle = float(np.arccos(cosine))
    if angle < 1e-8:
        return np.zeros(3, dtype=np.float64)
    axis = np.array(
        [rotation[2, 1] - rotation[1, 2], rotation[0, 2] - rotation[2, 0], rotation[1, 0] - rotation[0, 1]],
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(axis))
    if norm < 1e-8:
        return np.zeros(3, dtype=np.float64)
    return axis / norm * angle


def vertex_region_mask(regions: np.ndarray, prefix: str) -> np.ndarray:
    labels = np.asarray(regions, dtype=object).astype(str)
    return np.array([label.startswith(prefix) for label in labels], dtype=bool)


def wing_vertex_masks(regions: np.ndarray) -> dict[str, np.ndarray]:
    labels = np.asarray(regions, dtype=object).astype(str)
    keys = sorted({label for label in labels if label.startswith("wing_")})
    if not keys:
        raise ValueError("bind sidecar must label wing_* vertices")
    return {key: labels == key for key in keys}


def wing_span(vertices: np.ndarray, mask: np.ndarray) -> float:
    points = np.asarray(vertices, dtype=np.float64)[mask]
    if len(points) < 2:
        raise ValueError("wing mask selected fewer than two vertices")
    return float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))


def interior_fraction(points: np.ndarray, box_min: np.ndarray, box_max: np.ndarray) -> float:
    inside = np.all((points >= box_min) & (points <= box_max), axis=1)
    return float(inside.mean()) if len(points) else 0.0


def shrunken_aabb(points: np.ndarray, *, shrink: float = 0.2) -> tuple[np.ndarray, np.ndarray] | None:
    if len(points) < 2:
        return None
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    if np.any(hi - lo < 1e-8):
        return None
    mid = 0.5 * (lo + hi)
    return mid + (lo - mid) * (1.0 - shrink), mid + (hi - mid) * (1.0 - shrink)


def region_edges(edges: np.ndarray, mask: np.ndarray) -> np.ndarray:
    both = mask[edges[:, 0]] & mask[edges[:, 1]]
    return np.asarray(edges, dtype=np.int64)[both]


def region_triangles(triangles: np.ndarray, mask: np.ndarray) -> np.ndarray:
    keep = mask[triangles[:, 0]] & mask[triangles[:, 1]] & mask[triangles[:, 2]]
    return np.asarray(triangles, dtype=np.int64)[keep]


def edge_log_ratios(vertices: np.ndarray, edges: np.ndarray, rest_lengths: np.ndarray) -> np.ndarray:
    if len(edges) == 0:
        return np.zeros((len(vertices), 0), dtype=np.float64)
    verts = np.asarray(vertices, dtype=np.float64)
    rest = np.asarray(rest_lengths, dtype=np.float64)
    actual = np.linalg.norm(verts[:, edges[:, 0]] - verts[:, edges[:, 1]], axis=-1)
    return np.log(np.maximum(actual, 1e-8) / np.maximum(rest, 1e-8))


def triangle_areas(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    if len(triangles) == 0:
        return np.zeros((len(vertices), 0), dtype=np.float64)
    verts = np.asarray(vertices, dtype=np.float64)
    a = verts[:, triangles[:, 0]]
    b = verts[:, triangles[:, 1]]
    c = verts[:, triangles[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=-1)


def search_time_slices(gpu_budget: float, start_count: int = START_COUNT) -> list[float]:
    if int(start_count) < 1:
        raise ValueError("start_count must be at least 1")
    if float(gpu_budget) <= 0:
        raise ValueError("gpu_budget must be positive")
    slice_s = float(gpu_budget) / int(start_count)
    return [slice_s] * int(start_count)


def playback_continuity_pairs(plan: dict[str, Any]) -> dict[str, list[tuple[int, int]]]:
    """Real playback boundaries only. Reel cuts are not continuity pairs."""
    idle = plan["clips"]["idle"]["frames"]
    start = plan["clips"]["move_start"]["frames"]
    end = plan["clips"]["move_end"]["frames"]
    pinned = set(plan["pinnedFrames"])
    pairs: dict[str, list[tuple[int, int]]] = {"idleLoop": [], "transition": []}
    if len(idle) >= 2:
        pairs["idleLoop"].append((idle[0], idle[-1]))
    if len(start) >= 2 and start[-1] in pinned and start[-2] not in pinned:
        pairs["transition"].append((start[-2], start[-1]))
    if len(end) >= 2 and end[0] in pinned and end[1] not in pinned:
        pairs["transition"].append((end[0], end[1]))
    return pairs


def continuity_hinge_losses(
    *, plan, before_local, after_local, before_verts, after_verts,
    wing_joints, wing_mask,
):
    """Squared gate excess, normalized by angular/surface acceptance slack.

    One unit means an excess equal to the allowed slack. Baselines are detached;
    the exact playback pairs and per-pair maxima mirror evaluate_continuity.
    """
    import torch

    mask = torch.as_tensor(wing_mask, dtype=torch.bool, device=after_verts.device)
    if not wing_joints or not bool(mask.any()):
        raise ValueError("continuity loss requires joints and surface vertices")

    def angles(first, second):
        relative = first.double().transpose(-1, -2) @ second.double()
        cosine = (relative.diagonal(dim1=-2, dim2=-1).sum(-1) - 1.0) * 0.5
        # Match the float64 trace gate even for imperfect capture matrices;
        # only the backward path clamps away acos's singular endpoints.
        safe = torch.acos(cosine.clamp(-1.0 + 1e-7, 1.0 - 1e-7))
        exact = torch.acos(cosine.detach().clamp(-1.0, 1.0))
        return safe + (exact - safe).detach()

    angular, surface = [], []
    for group in playback_continuity_pairs(plan).values():
        for first, second in group:
            base_angle = angles(before_local[first, wing_joints], before_local[second, wing_joints]).max().detach()
            angle = angles(after_local[first, wing_joints], after_local[second, wing_joints]).max()
            base_travel = torch.linalg.vector_norm(
                before_verts[second, mask] - before_verts[first, mask], dim=-1).max().detach()
            travel = torch.linalg.vector_norm(
                after_verts[second, mask] - after_verts[first, mask], dim=-1).max()
            angular.append(torch.relu(angle - base_angle - CONTINUITY_GEODESIC_SLACK)
                           / CONTINUITY_GEODESIC_SLACK)
            surface.append(torch.relu(travel - base_travel - CONTINUITY_SURFACE_SLACK)
                           / CONTINUITY_SURFACE_SLACK)
    if not angular:
        return {"angular": after_local.sum() * 0.0, "surface": after_verts.sum() * 0.0}
    return {"angular": torch.stack(angular).square().mean(),
            "surface": torch.stack(surface).square().mean()}


def per_frame_iou_regression_hinge(before_iou, after_iou, frames):
    """Mean positive IoU deficit; restoring gradients persist near the gate.

    The exact gate tolerance is unchanged. Unlike a squared deficit, this loss
    keeps a constant restoring gradient for each frame still below tolerance.
    """
    import torch

    if not frames:
        return after_iou.sum() * 0.0
    deficit = torch.relu(before_iou[frames].detach() - after_iou[frames] - IOU_REGRESSION_SLACK)
    return deficit.mean()


def evaluate_deformation(
    *,
    before_verts: np.ndarray,
    after_verts: np.ndarray,
    rest_verts: np.ndarray,
    regions: np.ndarray,
    triangles: np.ndarray,
    edges: np.ndarray,
    rest_lengths: np.ndarray,
) -> dict[str, Any]:
    masks = wing_vertex_masks(regions)
    before = np.asarray(before_verts, dtype=np.float64)
    after = np.asarray(after_verts, dtype=np.float64)
    rest = np.asarray(rest_verts, dtype=np.float64)
    edge_index = {tuple(sorted(edge)): i for i, edge in enumerate(np.asarray(edges, dtype=np.int64))}
    per_wing = {}
    worst_abs_log = 0.0
    worst_contract = 0.0
    worst_stretch = 0.0
    worst_area = 1.0
    min_span_ratio = 1.0
    for key, mask in masks.items():
        selected = region_edges(edges, mask)
        selected_rest = np.array(
            [rest_lengths[edge_index[tuple(sorted(edge))]] for edge in selected], dtype=np.float64
        ) if len(selected) else np.zeros(0, dtype=np.float64)
        before_log = edge_log_ratios(before, selected, selected_rest)
        after_log = edge_log_ratios(after, selected, selected_rest)
        before_contract = float(np.max(np.maximum(-before_log, 0.0))) if before_log.size else 0.0
        after_contract = float(np.max(np.maximum(-after_log, 0.0))) if after_log.size else 0.0
        before_stretch = float(np.max(np.maximum(before_log, 0.0))) if before_log.size else 0.0
        after_stretch = float(np.max(np.maximum(after_log, 0.0))) if after_log.size else 0.0
        after_abs = float(np.max(np.abs(after_log))) if after_log.size else 0.0
        before_abs = float(np.max(np.abs(before_log))) if before_log.size else 0.0
        tris = region_triangles(triangles, mask)
        rest_area = triangle_areas(rest[None], tris)[0] if len(tris) else np.zeros(0)
        before_area = triangle_areas(before, tris)
        after_area = triangle_areas(after, tris)
        rest_safe = np.maximum(rest_area, 1e-12)
        before_area_min = float(np.min(before_area / rest_safe)) if before_area.size else 1.0
        after_area_min = float(np.min(after_area / rest_safe)) if after_area.size else 1.0
        before_span = [wing_span(frame, mask) for frame in before]
        after_span = [wing_span(frame, mask) for frame in after]
        span_ratio = float(np.min(np.asarray(after_span) / np.maximum(np.asarray(before_span), 1e-8)))
        per_wing[key] = {
            "spanRatioMin": span_ratio,
            "beforeAbsLogMax": before_abs,
            "afterAbsLogMax": after_abs,
            "beforeContractMax": before_contract,
            "afterContractMax": after_contract,
            "beforeStretchMax": before_stretch,
            "afterStretchMax": after_stretch,
            "beforeAreaRatioMin": before_area_min,
            "afterAreaRatioMin": after_area_min,
        }
        worst_abs_log = max(worst_abs_log, after_abs)
        worst_contract = max(worst_contract, after_contract)
        worst_stretch = max(worst_stretch, after_stretch)
        worst_area = min(worst_area, after_area_min)
        min_span_ratio = min(min_span_ratio, span_ratio)
    return {
        "perWing": per_wing,
        "absLogMax": worst_abs_log,
        "contractMax": worst_contract,
        "stretchMax": worst_stretch,
        "areaRatioMin": worst_area,
        "spanRatioMin": min_span_ratio,
    }


def evaluate_geometry_gates(
    *,
    before_verts: np.ndarray,
    after_verts: np.ndarray,
    regions: np.ndarray,
    rest_verts: np.ndarray,
    triangles: np.ndarray,
    edges: np.ndarray,
    rest_lengths: np.ndarray,
    before_strain_p95: float | None = None,
    after_strain_p95: float | None = None,
) -> dict[str, Any]:
    torso_mask = vertex_region_mask(regions, "torso")
    if not torso_mask.any():
        raise ValueError("bind sidecar must label torso vertices")
    deformation = evaluate_deformation(
        before_verts=before_verts, after_verts=after_verts, rest_verts=rest_verts,
        regions=regions, triangles=triangles, edges=edges, rest_lengths=rest_lengths,
    )
    collapsed = any(row["spanRatioMin"] < COLLAPSE_SPAN_RATIO for row in deformation["perWing"].values())
    worse_contract = any(
        row["afterContractMax"] > row["beforeContractMax"] + ABS_LOG_RATIO_SLACK
        for row in deformation["perWing"].values()
    )
    worse_stretch = any(
        row["afterStretchMax"] > row["beforeStretchMax"] + ABS_LOG_RATIO_SLACK
        for row in deformation["perWing"].values()
    )
    degenerated = any(
        row["afterAreaRatioMin"] < min(TRIANGLE_AREA_RATIO_MIN, row["beforeAreaRatioMin"] - 1e-6)
        for row in deformation["perWing"].values()
    )
    before = np.asarray(before_verts, dtype=np.float64)
    after = np.asarray(after_verts, dtype=np.float64)
    interior_delta = []
    verified = True
    wing_union = vertex_region_mask(regions, "wing_")
    for frame in range(len(after)):
        box = shrunken_aabb(after[frame, torso_mask])
        if box is None:
            verified = False
            continue
        before_in = interior_fraction(before[frame, wing_union], box[0], box[1])
        after_in = interior_fraction(after[frame, wing_union], box[0], box[1])
        interior_delta.append(after_in - before_in)
    hide = bool(interior_delta) and float(np.max(interior_delta)) > INTERIOR_FRACTION_SLACK
    if not interior_delta:
        verified = False
    intersection = "verified_increased" if hide else ("verified_clear" if verified and not hide else "unverified")
    geometry_fail = collapsed or worse_contract or worse_stretch or degenerated or hide or intersection == "unverified"
    return {
        "perWing": deformation["perWing"],
        "wingSpanRatioMin": deformation["spanRatioMin"],
        "absLogMax": deformation["absLogMax"],
        "contractMax": deformation["contractMax"],
        "stretchMax": deformation["stretchMax"],
        "areaRatioMin": deformation["areaRatioMin"],
        "wingInteriorDeltaMax": float(np.max(interior_delta)) if interior_delta else None,
        "collapsedWing": collapsed,
        "worseContraction": worse_contract,
        "worseStretch": worse_stretch,
        "triangleDegenerated": degenerated,
        "hidThroughTorso": hide,
        "torsoIntersection": intersection,
        "beforeStrainP95": None if before_strain_p95 is None else float(before_strain_p95),
        "afterStrainP95": None if after_strain_p95 is None else float(after_strain_p95),
        "passed": not geometry_fail,
        "meshFeasibilityUnresolved": True,
    }


def evaluate_continuity(
    *,
    plan: dict[str, Any],
    before_local: np.ndarray,
    after_local: np.ndarray,
    before_verts: np.ndarray,
    after_verts: np.ndarray,
    wing_joints: list[int],
    wing_mask: np.ndarray,
) -> dict[str, Any]:
    pairs = playback_continuity_pairs(plan)
    rows = []
    failed = False
    for kind, group in pairs.items():
        for first, second in group:
            before_rot = so3_geodesic_np(before_local[first, wing_joints], before_local[second, wing_joints])
            after_rot = so3_geodesic_np(after_local[first, wing_joints], after_local[second, wing_joints])
            before_surf = float(np.linalg.norm(before_verts[second, wing_mask] - before_verts[first, wing_mask], axis=-1).max())
            after_surf = float(np.linalg.norm(after_verts[second, wing_mask] - after_verts[first, wing_mask], axis=-1).max())
            rot_max = float(np.max(after_rot)) if np.size(after_rot) else 0.0
            rot_before = float(np.max(before_rot)) if np.size(before_rot) else 0.0
            popped = rot_max > rot_before + CONTINUITY_GEODESIC_SLACK or after_surf > before_surf + CONTINUITY_SURFACE_SLACK
            failed = failed or popped
            rows.append(
                {
                    "kind": kind,
                    "frames": [int(first), int(second)],
                    "beforeGeodesicMax": rot_before,
                    "afterGeodesicMax": rot_max,
                    "beforeSurfaceMax": before_surf,
                    "afterSurfaceMax": after_surf,
                    "popped": popped,
                }
            )
    return {"pairs": rows, "passed": not failed, "idleLoopChecked": bool(pairs["idleLoop"]), "transitionChecked": bool(pairs["transition"])}


def per_clip_metrics(
    *,
    plan: dict[str, Any],
    before_iou: list[float],
    after_iou: list[float],
    before_color: list[float],
    after_color: list[float],
    before_strain_p95: list[float],
    after_strain_p95: list[float],
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for name, clip in plan["clips"].items():
        frames = clip["frames"]
        iou_gain = [after_iou[i] - before_iou[i] for i in frames]
        worst = int(np.argmin(np.asarray(iou_gain)))
        rows[name] = {
            "clipKey": clip["clipKey"],
            "frames": frames,
            "beforeIou": [before_iou[i] for i in frames],
            "afterIou": [after_iou[i] for i in frames],
            "iouImprovement": iou_gain,
            "meanIouImprovement": float(np.mean(iou_gain)),
            "worstFrame": frames[worst],
            "worstFrameIouImprovement": float(iou_gain[worst]),
            "beforeColor": [before_color[i] for i in frames],
            "afterColor": [after_color[i] for i in frames],
            "beforeStrainP95": [before_strain_p95[i] for i in frames],
            "afterStrainP95": [after_strain_p95[i] for i in frames],
            "maxStrainP95After": float(np.max([after_strain_p95[i] for i in frames])),
            "maxStrainP95Before": float(np.max([before_strain_p95[i] for i in frames])),
        }
    return rows


def per_frame_non_regression(before_iou: list[float], after_iou: list[float], frames: list[int]) -> dict[str, Any]:
    deltas = [after_iou[i] - before_iou[i] for i in frames]
    worst = int(np.argmin(np.asarray(deltas))) if deltas else 0
    return {
        "passed": all(delta >= -IOU_REGRESSION_SLACK for delta in deltas),
        "worstFrame": frames[worst] if frames else None,
        "worstFrameIouImprovement": float(deltas[worst]) if deltas else 0.0,
    }


def candidate_eligibility(
    *,
    geometry: dict[str, Any],
    continuity: dict[str, Any],
    clips: dict[str, Any],
    move_rotation_max: float,
    pinned_rotation_max: float,
    optimize_frames: list[int],
    before_iou: list[float],
    after_iou: list[float],
) -> dict[str, Any]:
    image = per_frame_non_regression(before_iou, after_iou, optimize_frames)
    flight_ok = move_rotation_max <= ANCHOR_MATRIX_SLACK
    anchors_ok = pinned_rotation_max <= ANCHOR_MATRIX_SLACK
    reasons: list[str] = []
    if not geometry["passed"]:
        reasons.append("geometry")
    if not continuity["passed"]:
        reasons.append("continuity")
    if not image["passed"]:
        reasons.append("per_frame_iou_regression")
    if not flight_ok:
        reasons.append("move_clip_changed")
    if not anchors_ok:
        reasons.append("anchor_matrices_changed")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "geometryOk": geometry["passed"],
        "continuityOk": continuity["passed"],
        "perFrameIouOk": image["passed"],
        "flightPreserved": flight_ok,
        "anchorsPreserved": anchors_ok,
        "idleLoopOk": continuity["passed"] if continuity["idleLoopChecked"] else False,
        "transitionContinuityOk": continuity["passed"] if continuity["transitionChecked"] else False,
        "moveRotationMax": move_rotation_max,
        "pinnedRotationMax": pinned_rotation_max,
        "worstOptimizeFrame": image["worstFrame"],
        "worstOptimizeIouImprovement": image["worstFrameIouImprovement"],
        "idleMeanIouImprovement": clips["idle"]["meanIouImprovement"],
    }


def acceptance(*, eligibility: dict[str, Any], clips: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    idle = clips["idle"]
    idle_gain_ok = idle["meanIouImprovement"] >= IDLE_MEAN_IOU_GAIN
    reasons = list(eligibility["reasons"])
    if eligibility["passed"] and not idle_gain_ok:
        reasons.append("idle_mean_iou")
    passed = eligibility["passed"] and idle_gain_ok
    if passed:
        disposition = "generated_candidate_pending_visual_acceptance"
    elif not eligibility["geometryOk"] or geometry.get("torsoIntersection") == "unverified":
        disposition = "rejected_for_geometry"
    elif "continuity" in eligibility["reasons"]:
        disposition = "rejected_for_continuity"
    elif not reasons:
        disposition = "rejected_no_eligible_start"
    else:
        disposition = "rejected_" + "_and_".join(reasons)
    return {
        "passed": passed,
        "disposition": disposition,
        "reasons": reasons,
        "eligible": eligibility["passed"],
        "idleOk": idle_gain_ok and eligibility["perFrameIouOk"],
        "flightPreserved": eligibility["flightPreserved"],
        "anchorsPreserved": eligibility["anchorsPreserved"],
        "transitionContinuityOk": eligibility["transitionContinuityOk"],
        "idleLoopOk": eligibility["idleLoopOk"],
        "geometryOk": eligibility["geometryOk"],
        "visualAcceptanceSeparate": True,
        "meshFeasibilityUnresolved": True,
        "masterMeanIouImprovementIsNotAcceptance": True,
        "doesNotProveMeshCannotFold": True,
    }


def rotation_change_max(before: np.ndarray, after: np.ndarray, frames: list[int], joints: list[int] | None = None) -> float:
    """Max |ΔR| on the selected locals. Not geodesic: float32 acos(RᵀR) is a ~5e-4 false change."""
    first = np.asarray(before, dtype=np.float64)[np.asarray(frames)]
    second = np.asarray(after, dtype=np.float64)[np.asarray(frames)]
    if joints is not None:
        first = first[:, joints]
        second = second[:, joints]
    if first.size == 0:
        return 0.0
    return float(np.max(np.abs(second - first)))


def identical_panel_close_box(*panels: np.ndarray, pad_frac: float = 0.12) -> tuple[int, int, int, int]:
    """One crop in panel coordinates, applied identically to every equally sized panel."""
    if not panels:
        raise ValueError("close-up needs at least one panel")
    height, width = panels[0].shape[:2]
    if any(panel.shape[:2] != (height, width) for panel in panels):
        raise ValueError("close-up panels must share the optimization canvas size")
    union = None
    for panel in panels:
        luma = np.max(np.asarray(panel), axis=-1) if panel.ndim == 3 else np.asarray(panel)
        ys, xs = np.nonzero(luma > 1e-3)
        if len(xs) == 0:
            continue
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        if union is None:
            union = list(box)
        else:
            union[0] = min(union[0], box[0])
            union[1] = min(union[1], box[1])
            union[2] = max(union[2], box[2])
            union[3] = max(union[3], box[3])
    if union is None:
        return (0, 0, width, height)
    pad = max(8, int(pad_frac * max(width, height)))
    left = max(0, union[0] - pad)
    top = max(0, union[1] - pad)
    right = min(width, union[2] + pad)
    bottom = min(height, union[3] + pad)
    return (left, top, right, bottom)


def crop_panels_identically(panels: list[np.ndarray], box: tuple[int, int, int, int]) -> list[np.ndarray]:
    left, top, right, bottom = box
    return [np.asarray(panel)[top:bottom, left:right] for panel in panels]


def source_matches_optimization_canvas(source_rgb: np.ndarray, rendered_rgb: np.ndarray) -> None:
    if np.asarray(source_rgb).shape != np.asarray(rendered_rgb).shape:
        raise ValueError("source sprites must use the optimization target canvas; independent letterbox/rescale is forbidden")
