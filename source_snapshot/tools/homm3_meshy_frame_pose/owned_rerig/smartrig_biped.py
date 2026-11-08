"""Extract a conservative 25-joint biped rest skeleton from Meshy's UniRig output.

Meshy SmartRig meshes are commonly authored in an A-pose and may contain arbitrary
finger bones.  This adapter consumes only the main body topology: an extra armature
root, seven trunk joints, two four-joint arm chains, and two leg chains.  It refuses
other topologies instead of treating a quadruped or a mounted composite as a biped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
import numpy as np

from .glb_io import read_glb


def _rotation_matrix(quaternion: Sequence[float]) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float64)


def _local_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        # glTF stores matrices column-major.
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    matrix = _rotation_matrix(node.get("rotation", (0.0, 0.0, 0.0, 1.0)))
    scale = np.asarray(node.get("scale", (1.0, 1.0, 1.0)), dtype=np.float64)
    matrix[:3, :3] = matrix[:3, :3] @ np.diag(scale)
    matrix[:3, 3] = np.asarray(node.get("translation", (0.0, 0.0, 0.0)), dtype=np.float64)
    return matrix


def _world_node_matrices(nodes: list[dict[str, Any]]) -> tuple[list[np.ndarray], dict[int, int]]:
    parent = {child: index for index, node in enumerate(nodes) for child in node.get("children", [])}
    world: list[np.ndarray | None] = [None] * len(nodes)

    def resolve(index: int) -> np.ndarray:
        if world[index] is None:
            local = _local_matrix(nodes[index])
            world[index] = resolve(parent[index]) @ local if index in parent else local
        return world[index]  # type: ignore[return-value]

    for index in range(len(nodes)):
        resolve(index)
    return [matrix for matrix in world if matrix is not None], parent


def _path_from(start: int, children: dict[int, list[int]], positions: dict[int, np.ndarray],
               count: int, *, lateral: np.ndarray, direction: float) -> list[int]:
    path = [start]
    while len(path) < count:
        candidates = children.get(path[-1], [])
        if not candidates:
            break
        current = positions[path[-1]]
        # Main limbs move away from the body.  Finger branches are ignored once
        # the four-joint arm path has been recovered.
        path.append(max(candidates, key=lambda child: direction * float(positions[child] @ lateral)))
        if np.linalg.norm(positions[path[-1]] - current) <= 1e-9:
            break
    return path


def _paths_from(start: int, children: dict[int, list[int]], count: int) -> list[list[int]]:
    """Enumerate short root-to-leaf paths instead of guessing through accessory branches."""
    if count <= 0:
        return [[]]
    if count == 1:
        return [[start]]
    return [
        [start, *tail]
        for child in children.get(start, [])
        for tail in _paths_from(child, children, count - 1)
    ]


def _graph_paths_from(start: int, neighbors: dict[int, list[int]], count: int) -> list[list[int]]:
    """Enumerate short simple paths when an exporter reverses a trunk segment."""
    if count <= 0:
        return [[]]
    if count == 1:
        return [[start]]
    paths = []
    for neighbor in neighbors.get(start, []):
        for tail in _graph_paths_from(neighbor, neighbors, count - 1):
            if start not in tail:
                paths.append([start, *tail])
    return paths


def _body_frame(points: np.ndarray, index: dict[str, int]) -> np.ndarray:
    """Columns are character-left, up, and forward for a registered biped."""
    side = points[index["LeftUpLeg"]] - points[index["RightUpLeg"]]
    side[1] = 0.0
    side /= max(float(np.linalg.norm(side)), 1e-12)
    up = points[index["Spine"]] - points[index["Hips"]]
    up -= side * float(up @ side)
    up /= max(float(np.linalg.norm(up)), 1e-12)
    return np.column_stack((side, up, np.cross(side, up)))


def _horizontal_body_frame(horizontal: np.ndarray) -> np.ndarray:
    """Build a unit body frame from a horizontal left/right direction."""
    side = np.asarray(horizontal, dtype=np.float64).copy()
    side[1] = 0.0
    side /= max(float(np.linalg.norm(side)), 1e-12)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    return np.column_stack((side, up, np.cross(side, up)))


def _arm_path_cost(
    path: list[int],
    *,
    positions: dict[int, np.ndarray],
    target_frame: np.ndarray,
    reference: np.ndarray,
    reference_index: dict[str, int],
    side: str,
    parent: int,
    target_trunk_index: int,
    reference_trunk: list[str],
) -> float:
    """Score a candidate against the registered arm shape, not just its span."""
    reference_chain = [
        reference_index[side + label]
        for label in ("Shoulder", "Arm", "ForeArm", "Hand")
    ]
    source_frame = _body_frame(reference, reference_index)
    source_vectors = np.diff(reference[reference_chain], axis=0) @ source_frame
    target_points = np.asarray([positions[node] for node in path], dtype=np.float64)
    target_vectors = np.diff(target_points, axis=0) @ target_frame
    source_lengths = np.linalg.norm(source_vectors, axis=1)
    target_lengths = np.linalg.norm(target_vectors, axis=1)
    if np.any(source_lengths <= 1e-12) or np.any(target_lengths <= 1e-12):
        return float("inf")
    source_unit = source_vectors / source_lengths[:, None]
    target_unit = target_vectors / target_lengths[:, None]
    direction_error = np.sum(1.0 - np.sum(source_unit * target_unit, axis=1))
    source_profile = source_lengths / source_lengths.sum()
    target_profile = target_lengths / target_lengths.sum()
    length_error = float(np.abs(source_profile - target_profile).sum())

    # The path root must also sit where the corresponding shoulder belongs.  Use
    # the actual parent trunk joint so exporters that hang arms from Neck or Head
    # remain supported without making an accessory branch look like an arm.
    target_anchor = positions[parent]
    source_anchor = reference[reference_index[reference_trunk[target_trunk_index]]]
    source_root = reference[reference_chain[0]] - source_anchor
    target_root = target_points[0] - target_anchor
    source_root = source_root @ source_frame
    target_root = target_root @ target_frame
    root_scale = max(float(np.linalg.norm(source_root)), 1e-12)
    root_error = float(np.linalg.norm(target_root / root_scale - source_root / root_scale))
    return float(direction_error + 0.75 * length_error + 0.5 * root_error)


def _descendant_depth(start: int, children: dict[int, list[int]]) -> int:
    descendants = children.get(start, [])
    return 1 + max((_descendant_depth(child, children) for child in descendants), default=0)


def _lowest_descendant_y(
    start: int,
    children: dict[int, list[int]],
    positions: dict[int, np.ndarray],
) -> float:
    return min(
        [float(positions[start][1])]
        + [_lowest_descendant_y(child, children, positions) for child in children.get(start, [])]
    )


def extract_smartrig_biped_heads(
    mesh_path: Path,
    reference_heads: np.ndarray,
    names: Sequence[str],
) -> dict[str, Any]:
    """Return target rest heads for a UniRig biped in the mesh's A-pose coordinates."""
    labels = [str(name).rsplit(":", 1)[-1] for name in names]
    required = {
        "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End",
        *(side + part for side in ("Left", "Right") for part in
          ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase", "Toe_End")),
    }
    if set(labels) != required:
        raise ValueError("Expected the named 25-joint Mixamo biped topology")

    document = read_glb(mesh_path)["json"]
    nodes = document.get("nodes") or []
    skins = document.get("skins") or []
    if len(skins) != 1 or not skins[0].get("joints"):
        raise ValueError("Meshy candidate must contain exactly one skin skeleton")
    world, parent = _world_node_matrices(nodes)
    skin_nodes = [int(index) for index in skins[0]["joints"]]
    skin_set = set(skin_nodes)
    children = {
        index: [child for child in node.get("children", []) if child in skin_set]
        for index, node in enumerate(nodes)
        if any(child in skin_set for child in node.get("children", []))
    }
    neighbors = {index: list(children.get(index, [])) for index in skin_nodes}
    for index in skin_nodes:
        ancestor = parent.get(index)
        if ancestor in skin_set and ancestor not in neighbors[index]:
            neighbors[index].append(ancestor)
        for child in list(neighbors[index]):
            if index not in neighbors[child]:
                neighbors[child].append(index)
    roots = [index for index in skin_nodes if parent.get(index) not in skin_set]
    if len(roots) != 1:
        raise ValueError(f"Expected one UniRig body root, found {len(roots)}")
    root = roots[0]
    positions = {index: world[index][:3, 3].copy() for index in skin_nodes}

    prior = np.asarray(reference_heads, dtype=np.float64)
    index = {label: number for number, label in enumerate(labels)}

    # Meshy sometimes inserts one or more body-root nodes above Hips.  Do not
    # assume the first child of the skin root is Hips: in those exports it is
    # often a pelvis/torso branch, and treating it as Hips makes one real leg
    # compete with the torso for the second leg slot.  Find the node whose
    # upward continuation resembles the registered trunk and whose two most
    # separated downward branches resemble legs.  This remains structural and
    # fail-closed; it is not a global left/right remap.
    prior_leg_delta = prior[index["LeftUpLeg"]] - prior[index["Hips"]]
    prior_leg_delta[0] = 0.0
    prior_leg_delta[2] = 0.0
    if float(prior_leg_delta[1]) >= -1e-9:
        raise ValueError("Reference biped has no downward leg direction")
    trunk_labels = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End")
    source_frame = _body_frame(prior, index)
    source_vectors = np.diff(prior[[index[label] for label in trunk_labels]], axis=0) @ source_frame
    source_lengths = np.linalg.norm(source_vectors, axis=1)
    hip_options = []
    for candidate in skin_nodes:
        candidate_y = float(positions[candidate][1])
        leg_candidates = [child for child in children.get(candidate, [])
                          if _descendant_depth(child, children) >= 4
                          and _lowest_descendant_y(child, children, positions) < candidate_y - 1e-6]
        if len(leg_candidates) < 2:
            continue
        candidate_legs = sorted(
            leg_candidates,
            key=lambda child: (_lowest_descendant_y(child, children, positions),
                               -_descendant_depth(child, children)),
        )[:2]
        leg_axis = positions[candidate_legs[0]] - positions[candidate_legs[1]]
        leg_axis[1] = 0.0
        if np.linalg.norm(leg_axis) <= 1e-4:
            continue
        # A valid candidate must have a complete trunk continuation.  The
        # first exported trunk link is not required to point upward: some
        # SmartRig rest poses place the pelvis helper a few pixels below Hips.
        # Requiring positive Y here would reject those otherwise valid rigs.
        trunk_paths = [
            path
            for count in (7, 6)
            for path in _graph_paths_from(candidate, neighbors, count)
        ]
        if not trunk_paths:
            continue
        candidate_frame = _horizontal_body_frame(leg_axis)
        path_scores = []
        for path in trunk_paths:
            target_vectors = np.diff(np.asarray([positions[node] for node in path]), axis=0) @ candidate_frame
            target_lengths = np.linalg.norm(target_vectors, axis=1)
            count = len(path) - 1
            source_slice = source_vectors[:count]
            source_length_slice = source_lengths[:count]
            source_unit = source_slice / np.maximum(source_length_slice[:, None], 1e-12)
            target_unit = target_vectors / np.maximum(target_lengths[:, None], 1e-12)
            direction_error = float(np.mean(1.0 - np.sum(source_unit * target_unit, axis=1)))
            source_profile = source_length_slice / max(float(source_length_slice.sum()), 1e-12)
            target_profile = target_lengths / max(float(target_lengths.sum()), 1e-12)
            path_scores.append(direction_error + 0.75 * float(np.abs(source_profile - target_profile).sum()))
        hip_options.append((min(path_scores), float(np.linalg.norm(leg_axis)), candidate))
    if not hip_options:
        raise ValueError("Could not find two UniRig leg roots")
    # The false candidate at a torso junction usually pairs one actual leg
    # with the trunk.  Prefer the wider bilateral leg spread when the trunk
    # shape scores are close, while retaining a strong trunk-shape veto for
    # lateral accessory branches.
    best_trunk = min(item[0] for item in hip_options)
    eligible = [item for item in hip_options if item[0] <= best_trunk + 0.45]
    hips = max(eligible, key=lambda item: item[1])[2]
    hip_y = float(positions[hips][1])
    leg_candidates = [child for child in children.get(hips, [])
                      if _descendant_depth(child, children) >= 4
                      and _lowest_descendant_y(child, children, positions) < hip_y - 1e-6]
    if len(leg_candidates) < 2:
        raise ValueError("Could not find two UniRig leg roots")
    # Prefer the branches that actually reach the lower body.  A torso or
    # weapon branch can still be deeper than a leg, but it should not outrank
    # a branch whose descendants descend to the registered leg region.
    leg_roots = sorted(leg_candidates, key=lambda child: (
        _lowest_descendant_y(child, children, positions),
        -_descendant_depth(child, children),
    ))[:2]
    prior_side = prior[index["LeftUpLeg"]] - prior[index["RightUpLeg"]]
    prior_side[1] = 0.0
    if np.linalg.norm(prior_side) <= 1e-9:
        raise ValueError("Reference biped has no horizontal left/right separation")
    leg_axis = positions[leg_roots[0]] - positions[leg_roots[1]]
    leg_axis[1] = 0.0
    if np.linalg.norm(leg_axis) <= 1e-9:
        raise ValueError("UniRig leg roots have no horizontal separation")
    leg_axis /= np.linalg.norm(leg_axis)
    if float(leg_axis @ prior_side) < 0.0:
        leg_axis *= -1.0

    target_frame = _horizontal_body_frame(leg_axis)
    # Do not select the highest child as a trunk joint: some exports place an
    # arm root above the neck.  Score complete seven-node paths against the
    # registered trunk shape so the arm branches remain available to the arm
    # selector below.
    trunk_paths = [
        path
        for count in (len(trunk_labels), len(trunk_labels) - 1)
        for path in _graph_paths_from(hips, neighbors, count)
    ]
    if not trunk_paths:
        raise ValueError("UniRig trunk ended before seven Mixamo joints")
    def trunk_cost(path: list[int]) -> float:
        target_vectors = np.diff(np.asarray([positions[node] for node in path]), axis=0) @ target_frame
        target_lengths = np.linalg.norm(target_vectors, axis=1)
        source_count = len(path) - 1
        source_slice = source_vectors[:source_count]
        source_length_slice = source_lengths[:source_count]
        source_unit = source_slice / np.maximum(source_length_slice[:, None], 1e-12)
        target_unit = target_vectors / np.maximum(target_lengths[:, None], 1e-12)
        direction_error = float(np.mean(1.0 - np.sum(source_unit * target_unit, axis=1)))
        source_profile = source_length_slice / max(float(source_length_slice.sum()), 1e-12)
        target_profile = target_lengths / max(float(target_lengths.sum()), 1e-12)
        return direction_error + 0.75 * float(np.abs(source_profile - target_profile).sum())

    trunk = min(trunk_paths, key=trunk_cost)
    synthetic_trunk = []
    if len(trunk) == len(trunk_labels) - 1:
        synthetic_trunk = ["HeadTop_End"]

    # Exporters differ on whether the shoulder branch hangs from Spine2, Neck,
    # or Head.  Several exports also contain a long armor/accessory branch that
    # is more lateral than the actual arm.  Select the candidate whose link
    # directions and proportions match the registered arm, rather than treating
    # maximum separation as semantic evidence.
    hip_y = float(positions[hips][1])
    arm_candidate_roots: list[tuple[int, int, list[int]]] = []
    for node in trunk:
        elevated = [child for child in children.get(node, []) if child not in trunk
                     and float(positions[child][1]) > hip_y + 0.12
                     and _descendant_depth(child, children) >= 4]
        for root_candidate in elevated:
            for path in _paths_from(root_candidate, children, 4):
                arm_candidate_roots.append((root_candidate, node, path))
    if len(arm_candidate_roots) < 2:
        raise ValueError("Could not find two elevated UniRig arm roots")

    def ranked_paths(side: str, direction: float) -> list[tuple[float, int, int, list[int]]]:
        candidates = []
        for root_candidate, parent, path in arm_candidate_roots:
            # Some exports place both shoulder helpers on the centerline and
            # fan the actual arm sides out over the next joints.  Classify the
            # complete candidate by its hand-side endpoint, not by that helper
            # root, or one side is silently rejected and later motion twists.
            lateral = float((positions[path[-1]] - positions[hips]) @ leg_axis)
            if direction * lateral <= 0.0:
                continue
            parent_trunk_index = trunk.index(parent)
            cost = _arm_path_cost(
                path,
                positions=positions,
                target_frame=target_frame,
                reference=prior,
                reference_index=index,
                side=side,
                parent=parent,
                target_trunk_index=parent_trunk_index,
                reference_trunk=list(trunk_labels),
            )
            candidates.append((cost, root_candidate, parent, path))
        if not candidates:
            raise ValueError(f"Could not find a {side} UniRig arm chain")
        return sorted(candidates, key=lambda item: item[0])

    def side_value(node: int) -> float:
        return float((positions[node] - positions[hips]) @ leg_axis)

    left_candidates = ranked_paths("Left", 1.0)
    right_candidates = ranked_paths("Right", -1.0)
    left_arm_cost, left_arm, left_parent, left_arm_path = left_candidates[0]
    right_arm_cost, right_arm, right_parent, right_arm_path = right_candidates[0]
    if left_arm == right_arm:
        raise ValueError("Left and right arm selector chose the same UniRig branch")
    left_leg, right_leg = sorted(leg_roots, key=side_value, reverse=True)
    arm_paths = {
        "Left": left_arm_path,
        "Right": right_arm_path,
    }
    leg_paths = {
        "Left": _path_from(left_leg, children, positions, 5, lateral=leg_axis, direction=1.0),
        "Right": _path_from(right_leg, children, positions, 5, lateral=leg_axis, direction=-1.0),
    }
    if any(len(path) < 4 for path in arm_paths.values()) or any(len(path) < 4 for path in leg_paths.values()):
        raise ValueError("UniRig biped limb chain is shorter than the required Mixamo topology")

    heads = np.zeros((len(labels), 3), dtype=np.float64)

    def put(label: str, point: np.ndarray) -> None:
        heads[index[label]] = point

    for label, node in zip(("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"), trunk):
        put(label, positions[node])
    if synthetic_trunk:
        tail = positions[trunk[-1]] + (positions[trunk[-1]] - positions[trunk[-2]])
        put("HeadTop_End", tail)
    for side, arm_path, leg_path in (("Left", arm_paths["Left"], leg_paths["Left"]),
                                     ("Right", arm_paths["Right"], leg_paths["Right"])):
        for label, node in zip(("Shoulder", "Arm", "ForeArm", "Hand"), arm_path):
            put(side + label, positions[node])
        for label, node in zip(("UpLeg", "Leg", "Foot", "ToeBase"), leg_path[:4]):
            put(side + label, positions[node])
        if len(leg_path) >= 5:
            put(side + "Toe_End", positions[leg_path[4]])
        else:
            toe_base = positions[leg_path[3]]
            foot = positions[leg_path[2]]
            put(side + "Toe_End", toe_base + (toe_base - foot))

    if not np.isfinite(heads).all():
        raise ValueError("UniRig adapter produced non-finite joint heads")
    return {
        "heads": heads,
        "schema": "smartrig_biped_adapter.v1",
        "restStyle": "smartrig_a_pose",
        "skinJointCount": len(skin_nodes),
        "extraRoot": nodes[root].get("name", str(root)),
        "syntheticToeEnd": [side for side, path in leg_paths.items() if len(path) < 5],
        "syntheticTrunk": synthetic_trunk,
        "trunkNodes": [nodes[node].get("name", str(node)) for node in trunk] + [f"synthetic:{label}" for label in synthetic_trunk],
        "armNodes": {side: [nodes[node].get("name", str(node)) for node in path]
                     for side, path in arm_paths.items()},
        "armPathCost": {"Left": float(left_arm_cost), "Right": float(right_arm_cost)},
        "armPathParent": {"Left": nodes[left_parent].get("name", str(left_parent)),
                          "Right": nodes[right_parent].get("name", str(right_parent))},
        "legNodes": {side: [nodes[node].get("name", str(node)) for node in path]
                     for side, path in leg_paths.items()},
    }
