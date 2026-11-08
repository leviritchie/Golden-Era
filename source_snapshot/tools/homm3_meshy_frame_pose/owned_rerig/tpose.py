"""Put the reference skeleton in a canonical T-pose, and measure what the mesh does under it.

Every clip audit in this lane asks a pose *relative* question: does the driven surface stay inside the
plate that frame was captured from.  That null is exact, and it is also blind to a family of geometry
faults, because it never says what the surface should have been.  A T-pose does:

* the correct shape is known in advance - arms along the character's own left/right axis, legs
  straight down, spine and neck up - so a deviation from it is a fault map rather than a difference
  from another pose of the same broken mesh;
* the limbs are maximally separated, so a region fused to the wrong part has nowhere to hide; in a
  relaxed idle a bow hanging beside the hip is *also* where the hip geometry is, which is why no clip
  audit could separate them;
* it is the pose a bind is normally authored in, so measuring it is also the precondition for
  re-binding in it.

The pose is built by forward kinematics from the rest pose using **the reference's own bone lengths**,
so it is a rigid reconfiguration of that skeleton and not a second, differently-scaled rig: the driver
applies one swing per bone, and any distortion it produces then belongs to the weights or to the mesh,
never to the target pose.  ``boneLengthDrift`` is reported as proof of that and is zero by
construction.

Two things this module deliberately does not do.  It does not re-fit the reference scale: a T-posed
mesh is wider than the mesh the plates were registered against, so the extent identity would
re-derive a different scale and break the plate correspondence.  And it does not read the pose off the
reference's motion: the canonical directions are authored and tabulated below, and an unknown joint
name is a hard error rather than a bone left at its rest direction, because a silently half-posed
skeleton would produce a flattering picture of a rig it never tested.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .exact_bind import mesh_components, nearby_vertex_pairs, position_groups, tree_order  # noqa: F401

TPOSE_SCHEMA = "reference_tpose.v1"
STRETCH_SCHEMA = "edge_stretch.v1"

#: Canonical direction of every joint of the 25-joint Mixamo reference, in the character's own frame.
#: ``None`` marks the root, which keeps its rest position: a T-pose re-orients limbs, it does not move
#: the character.  Names are matched on the segment after the last colon, so the capture's
#: ``mixamorig:`` prefix is not part of the contract.
#:
#: The direction is the one this joint's own **incoming** bone takes, i.e. from its parent to itself,
#: and Mixamo's names are one bone later than the anatomy suggests.  ``LeftUpLeg`` is the hip joint,
#: so ``Hips -> LeftUpLeg`` is the short lateral pelvis offset and it is the *thigh* that ends at
#: ``LeftLeg``; likewise ``LeftFoot`` ends the shin and ``LeftToeBase`` ends the foot.  Reading the
#: table anatomically instead puts the pelvis in the leg's slot, which measured a 74 deg rotation of a
#: bone that should barely move.
CANONICAL_T_POSE: dict[str, str | None] = {
    "Hips": None,
    "Spine": "up",
    "Spine1": "up",
    "Spine2": "up",
    "Neck": "up",
    "Head": "up",
    "HeadTop_End": "up",
    "LeftShoulder": "left_clavicle",
    "LeftArm": "left",
    "LeftForeArm": "left",
    "LeftHand": "left",
    "RightShoulder": "right_clavicle",
    "RightArm": "right",
    "RightForeArm": "right",
    "RightHand": "right",
    "LeftUpLeg": "left",
    "LeftLeg": "down",
    "LeftFoot": "down",
    "LeftToeBase": "foot",
    "LeftToe_End": "forward",
    "RightUpLeg": "right",
    "RightLeg": "down",
    "RightFoot": "down",
    "RightToeBase": "foot",
    "RightToe_End": "forward",
}

#: How far the clavicle rises above the horizontal and the foot drops below it.  Both are authored
#: proportions rather than axis snaps: a perfectly horizontal clavicle and a perfectly horizontal foot
#: are each anatomically wrong, and an absurd target pose would make the measurement a picture of the
#: pose rather than of the mesh.
CLAVICLE_RISE = 0.35
FOOT_DROP = 0.34

#: The rest pose's own spine must agree with the mesh frame's +Y at least this well.
SPINE_ALIGNMENT_MIN = 0.5


def short_name(name: str) -> str:
    """``mixamorig:LeftArm`` -> ``LeftArm``."""
    return str(name).rsplit(":", 1)[-1]


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("fail-closed: cannot normalise a zero-length direction")
    return np.asarray(vector, dtype=np.float64) / norm


def character_frame(
    *, rest: np.ndarray, parents: list[int | None], joint_names: list[str]
) -> dict[str, Any]:
    """The character's own ``side`` / ``up`` / ``forward`` axes, in the mesh frame.

    ``up`` is the mesh frame's +Y, asserted against the rest pose's own spine rather than assumed.
    The side axis comes from the hip-to-hip axis, which the capture measures directly, and the forward
    axis from the ankle-to-toe direction; the two are cross-checked, and a disagreement means the
    reference is not the upright biped this pose is defined for.  That is a refusal, not something to
    average away.
    """
    rest = np.asarray(rest, dtype=np.float64)
    index = {short_name(name): position for position, name in enumerate(joint_names)}
    required = ("Hips", "LeftUpLeg", "RightUpLeg", "Spine", "LeftFoot", "LeftToeBase")
    missing = [name for name in required if name not in index]
    if missing:
        raise ValueError(
            f"fail-closed: the reference has no {missing}; the canonical T-pose is defined for the "
            f"25-joint Mixamo biped, not for {len(joint_names)} joints of another topology"
        )

    up = np.array([0.0, 1.0, 0.0])
    spine_direction = _unit(rest[index["Spine"]] - rest[index["Hips"]])
    if float(spine_direction @ up) < SPINE_ALIGNMENT_MIN:
        raise ValueError(
            "fail-closed: the rest pose's own spine does not point along the mesh frame's +Y "
            f"(cosine {float(spine_direction @ up):.3f}); the character frame is not Y-up"
        )

    hip_axis = rest[index["LeftUpLeg"]] - rest[index["RightUpLeg"]]
    hip_axis = hip_axis - up * float(hip_axis @ up)
    side = _unit(hip_axis)
    toe_axis = rest[index["LeftToeBase"]] - rest[index["LeftFoot"]]
    toe_axis = toe_axis - up * float(toe_axis @ up)
    forward_from_toes = _unit(toe_axis)
    if float(forward_from_toes @ side) > 0.5:
        raise ValueError(
            "fail-closed: the reference's toes point along its hip-to-hip axis, so it is not a biped "
            "whose forward axis is perpendicular to its stance"
        )
    forward = _unit(np.cross(side, up))
    return {
        "side": side,
        "up": up,
        "forward": forward,
        "spineAlignmentCos": float(spine_direction @ up),
        "toeAlignmentCos": float(forward_from_toes @ forward),
        "hipsPosition": rest[index["Hips"]],
    }


def canonical_directions(frame: dict[str, Any]) -> dict[str, np.ndarray]:
    """The named direction table resolved in one character frame."""
    side = np.asarray(frame["side"], dtype=np.float64)
    up = np.asarray(frame["up"], dtype=np.float64)
    forward = np.asarray(frame["forward"], dtype=np.float64)
    return {
        "up": up,
        "down": -up,
        "left": side,
        "right": -side,
        "forward": forward,
        "left_clavicle": _unit(side + CLAVICLE_RISE * up),
        "right_clavicle": _unit(-side + CLAVICLE_RISE * up),
        "foot": _unit(forward * 0.94 - up * FOOT_DROP),
    }


def tpose_joint_track(
    *,
    rest: np.ndarray,
    parents: list[int | None],
    joint_names: list[str],
    frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One ``(J,3)`` joint track for the canonical T-pose, using the rest pose's own bone lengths.

    Forward kinematics in tree order: the root keeps its rest position and every other joint is its
    parent's placed position plus the canonical direction times that bone's rest length.  Bone lengths
    are therefore preserved exactly, which is what makes this a rigid reconfiguration of the same
    skeleton and what ``boneLengthDrift`` checks.
    """
    rest = np.asarray(rest, dtype=np.float64)
    if len(parents) != len(rest) or len(joint_names) != len(rest):
        raise ValueError(
            f"fail-closed: {len(rest)} joints, {len(parents)} parents, {len(joint_names)} names"
        )
    frame = frame or character_frame(rest=rest, parents=parents, joint_names=joint_names)
    directions = canonical_directions(frame)

    unknown = [short_name(name) for name in joint_names if short_name(name) not in CANONICAL_T_POSE]
    if unknown:
        raise ValueError(
            f"fail-closed: no canonical T-pose direction is authored for {unknown}; leaving those "
            "bones at their rest direction would pose a different skeleton than this module claims"
        )

    track = np.zeros_like(rest)
    rotations: list[dict[str, Any]] = []
    for joint in tree_order(parents):
        parent = parents[joint]
        key = CANONICAL_T_POSE[short_name(joint_names[joint])]
        if parent is None:
            if key is not None:
                raise ValueError(
                    f"fail-closed: {joint_names[joint]} is the root but the canonical table gives it "
                    f"the direction {key!r}; the pose would move the character"
                )
            track[joint] = rest[joint]
            continue
        if key is None:
            raise ValueError(
                f"fail-closed: {joint_names[joint]} has a parent but the canonical table marks it as "
                "the root; the table does not describe this skeleton"
            )
        span = rest[joint] - rest[parent]
        length = float(np.linalg.norm(span))
        direction = directions[key]
        track[joint] = track[parent] + direction * length
        cosine = float(_unit(span) @ direction) if length > 1e-12 else 1.0
        rotations.append(
            {
                "joint": joint_names[joint],
                "canonical": key,
                "restAngleDeg": float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))),
                "restLength": length,
            }
        )

    rest_lengths = np.array(
        [
            0.0 if parents[j] is None else float(np.linalg.norm(rest[j] - rest[parents[j]]))
            for j in range(len(rest))
        ]
    )
    posed_lengths = np.array(
        [
            0.0 if parents[j] is None else float(np.linalg.norm(track[j] - track[parents[j]]))
            for j in range(len(rest))
        ]
    )
    live = rest_lengths > 1e-9
    drift = (
        float(np.abs(posed_lengths[live] / rest_lengths[live] - 1.0).max()) if np.any(live) else 0.0
    )
    if drift > 1e-9:
        raise ValueError(
            f"fail-closed: the T-pose changed a bone length by {drift:.3e}; it must be a rigid "
            "reconfiguration of the reference, not a second rig"
        )
    moves = np.linalg.norm(track - rest, axis=1)
    return {
        "schema": TPOSE_SCHEMA,
        "frame": {
            "side": frame["side"],
            "up": frame["up"],
            "forward": frame["forward"],
            "spineAlignmentCos": frame["spineAlignmentCos"],
            "toeAlignmentCos": frame["toeAlignmentCos"],
        },
        "joints": track,
        "restJoints": rest,
        "boneRotations": rotations,
        "boneLengthDrift": drift,
        "worstJointMove": float(moves.max()),
        "jointMove": moves,
        "wristMove": {
            short_name(joint_names[j]): float(moves[j])
            for j in range(len(rest))
            if short_name(joint_names[j]) in ("LeftHand", "RightHand")
        },
    }


def _undirected_edges(indices: np.ndarray) -> np.ndarray:
    """Unique undirected edges, each appearing **once**.

    The clip audit keys its edges by *winding* - it stacks the three directed pairs of every triangle
    and takes ``np.unique`` of the rows - so an interior edge is counted twice there, once as
    ``(a,b)`` and once as ``(b,a)``.  That is invisible in its distribution statistics, because both
    rows carry the same stretch, but it doubles its ``edges`` and ``edgesPastReviewLimit`` fields, and
    a new module should not inherit a double count.  Sorted endpoints make each undirected edge one
    row, so ``edges`` here is about half the audit's for the same surface while ``median``/``p99``/
    ``max`` are identical; a count quoted against an audit count has to say which convention it is in.
    """
    triangles = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    pairs = np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    return np.unique(np.sort(pairs, axis=1), axis=0)


def weight_by_bone(*, joints: np.ndarray, weights: np.ndarray, vertex_count: int) -> np.ndarray:
    """``(N, B)`` summed weight per vertex per bone, the layout the audit's weight-jump test uses."""
    total = np.zeros((int(vertex_count), int(joints.max()) + 1), dtype=np.float64)
    for slot in range(joints.shape[1]):
        np.add.at(total, (np.arange(vertex_count), joints[:, slot]), weights[:, slot])
    return total


def rigid_weights(
    *, positions: np.ndarray, joints: np.ndarray, weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """One bone per **welded node**: every vertex sharing a position gets the same single bone.

    The control for a blend measurement.  A position-field skin can only distort an edge by giving
    its two ends different transforms, so *every* stretch under this driver is a blend effect by
    construction - which means a stretched surface is not yet evidence of bad geometry.  Collapsing
    each welded node onto its dominant bone removes the blend entirely and leaves the question the
    picture cannot answer on its own: does the surface *fit* the target pose at all, or does it
    fold and collide when it is allowed to move rigidly?

    Per node rather than per vertex, because this mesh is delivered split: one sheet of flesh is
    hundreds of patches that share no indices, so a per-vertex assignment could split a patch from
    its own duplicate and tear the surface along a seam that exists only in the index buffer.
    """
    node_of, _representative = position_groups(positions)
    vertex_count = len(positions)
    by_bone = weight_by_bone(joints=joints, weights=weights, vertex_count=vertex_count)
    node_count = int(node_of.max()) + 1
    node_load = np.zeros((node_count, by_bone.shape[1]), dtype=np.float64)
    np.add.at(node_load, node_of, by_bone)
    chosen = np.argmax(node_load, axis=1)
    bone_of_vertex = chosen[node_of]
    return (
        bone_of_vertex[:, None].astype(np.int64),
        np.ones((vertex_count, 1), dtype=np.float64),
    )


def edge_stretch(
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    deformed: np.ndarray,
    joints: np.ndarray | None = None,
    weights: np.ndarray | None = None,
    review_limit: float = 1.0,
    subject_height: float | None = None,
) -> dict[str, Any]:
    """Per-edge distortion of one posed surface, in the audit's own ``edge_stretch.v1`` convention.

    Same fields, same definitions and the same review limit as ``audit.tearing``, so a T-pose number
    and a clip number can be read side by side: the point of this pose is to be a stronger stress
    than any single animation frame, and that claim is only checkable if the two are measured the same
    way.  The three weight-jump fields need the bind that drove the surface and are reported as
    ``None`` when it is not supplied - they are what separates a *weight* defect (an edge straddling a
    hard change of bone) from a *geometry* defect (an edge whose two ends are on the same bone and
    still cannot span the pose).
    """
    edges = _undirected_edges(indices)
    rest_edge = np.linalg.norm(positions[edges[:, 0]] - positions[edges[:, 1]], axis=1)
    posed_edge = np.linalg.norm(deformed[edges[:, 0]] - deformed[edges[:, 1]], axis=1)
    live = rest_edge > 1e-9
    stretch = np.zeros(len(edges), dtype=np.float64)
    stretch[live] = np.abs(posed_edge[live] / rest_edge[live] - 1.0)

    jump = None
    if joints is not None and weights is not None:
        by_bone = weight_by_bone(
            joints=joints, weights=weights, vertex_count=len(positions)
        )
        jump = np.abs(by_bone[edges[:, 0]] - by_bone[edges[:, 1]]).sum(axis=1)

    over = jump > 0.5 if jump is not None else None
    growth = posed_edge - rest_edge
    block: dict[str, Any] = {
        "schema": STRETCH_SCHEMA,
        "edges": int(len(edges)),
        "edgeKeying": "undirected_unique",
        "median": float(np.median(stretch)),
        "p99": float(np.percentile(stretch, 99)),
        "max": float(stretch.max()),
        "edgesPastReviewLimit": int((stretch > review_limit).sum()),
        "edgesPastTenTimesReviewLimit": int((stretch > 10.0 * review_limit).sum()),
        "reviewLimit": float(review_limit),
        "edgesWithWeightJumpOverHalf": None if over is None else int(over.sum()),
        "meanStretchAtWeightJump": (
            None if over is None else (float(stretch[over].mean()) if np.any(over) else 0.0)
        ),
        "meanStretchElsewhere": (
            None if over is None else float(stretch[~over].mean()) if np.any(~over) else 0.0
        ),
        # Relative stretch is measured on a mesh whose median edge is 1.44 px of a 39x77 px plate, so
        # a short edge can triple while moving a thousandth of the body.  The absolute growth is what
        # the eye can see, and it is reported beside the ratio so neither can be quoted alone.
        "medianEdgeGrowth": float(np.median(growth)),
        "p99EdgeGrowth": float(np.percentile(growth, 99)),
        "maxEdgeGrowth": float(growth.max()),
    }
    if subject_height is not None and subject_height > 0.0:
        block["maxEdgeGrowthFractionOfHeight"] = float(growth.max() / float(subject_height))
        block["edgesGrowingPastFivePercentOfHeight"] = int(
            (growth > 0.05 * float(subject_height)).sum()
        )
    return block


def stretch_regions(
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    deformed: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    bone_names: list[str],
    rest_joints: np.ndarray | None = None,
    joint_names: list[str] | None = None,
    limit: float = 1.0,
    radius: float = 0.02,
    min_vertices: int = 3,
    max_regions: int = 8,
    subject_height: float | None = None,
) -> dict[str, Any]:
    """Group the surface that cannot survive the T-pose, and say what drives it and where it is.

    A single worst-edge number localises nothing, which is the same reason acceptance counts escapes
    over the whole surface and reporting groups them.  Vertices are grouped by rest proximity on the
    welded graph - the graph the mesh actually is, since the exporter delivered one sheet as hundreds
    of patches that share no indices - and each group reports the bones that drive it, the rest joint
    nearest its centroid, and the share of its own edges that straddle a hard weight change.  That
    last field is the one that answers the question a picture cannot: a region whose internal edges
    have no weight jump at all is geometry the bind never had a choice about.
    """
    edges = _undirected_edges(indices)
    rest_edge = np.linalg.norm(positions[edges[:, 0]] - positions[edges[:, 1]], axis=1)
    posed_edge = np.linalg.norm(deformed[edges[:, 0]] - deformed[edges[:, 1]], axis=1)
    live = rest_edge > 1e-9
    stretch = np.zeros(len(edges), dtype=np.float64)
    stretch[live] = np.abs(posed_edge[live] / rest_edge[live] - 1.0)

    node_of, _per_vertex_representative = position_groups(positions)
    node_count = int(node_of.max()) + 1
    node_worst = np.zeros(node_count, dtype=np.float64)
    np.maximum.at(node_worst, node_of[edges[:, 0]], stretch)
    np.maximum.at(node_worst, node_of[edges[:, 1]], stretch)
    hot = np.flatnonzero(node_worst > limit)
    if hot.size == 0:
        return {
            "schema": "stretch_regions.v1",
            "limit": float(limit),
            "radius": float(radius),
            "groupedNodes": 0,
            "regionCount": 0,
            "regions": [],
        }

    # ``position_groups`` returns a *per-vertex* representative, so indexing it by a node id reads an
    # unrelated vertex's position.  The node's own position comes from the vertices that share it.
    node_positions = np.zeros((node_count, 3), dtype=np.float64)
    node_positions[node_of] = positions
    pairs = nearby_vertex_pairs(node_positions[hot], float(radius))
    parent = np.arange(hot.size, dtype=np.int64)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for left, right in pairs:
        root_left, root_right = find(int(left)), find(int(right))
        if root_left != root_right:
            parent[root_right] = root_left

    components = mesh_components(indices, len(positions))
    by_bone = weight_by_bone(joints=joints, weights=weights, vertex_count=len(positions))
    weight_jump = np.abs(by_bone[edges[:, 0]] - by_bone[edges[:, 1]]).sum(axis=1)
    groups: dict[int, list[int]] = {}
    for local, node in enumerate(hot.tolist()):
        groups.setdefault(find(local), []).append(int(node))

    regions: list[dict[str, Any]] = []
    for root, nodes in groups.items():
        if len(nodes) < min_vertices:
            continue
        node_ids = np.asarray(nodes, dtype=np.int64)
        vertex_ids = np.flatnonzero(np.isin(node_of, node_ids))
        places = node_positions[node_ids]
        load = by_bone[vertex_ids].sum(axis=0)
        order = np.argsort(-load)[:4]
        touched = np.unique(components[vertex_ids])
        own = np.isin(node_of[edges[:, 0]], node_ids) & np.isin(node_of[edges[:, 1]], node_ids)
        jumps = weight_jump[own]
        entry: dict[str, Any] = {
            "nodes": int(node_ids.size),
            "vertices": int(vertex_ids.size),
            "patches": int(touched.size),
            "centroid": places.mean(axis=0),
            # A centroid alone cannot say whether a region is the head or the shoulder beside it, and
            # a reader has no picture to fall back on: the box is what makes the reported place
            # checkable against the joint it is named after.
            "boundsMin": places.min(axis=0),
            "boundsMax": places.max(axis=0),
            "maxStretch": float(node_worst[node_ids].max()),
            "medianNodeStretch": float(np.median(node_worst[node_ids])),
            "maxEdgeGrowth": float((posed_edge - rest_edge)[own].max()) if own.any() else 0.0,
            "dominantBones": [bone_names[int(b)] for b in order if load[b] > 0.0],
            "ownEdges": int(own.sum()),
            "ownEdgesWithWeightJumpOverHalf": int((jumps > 0.5).sum()),
            "meanWeightJumpOnOwnEdges": float(jumps.mean()) if jumps.size else 0.0,
        }
        if subject_height is not None and subject_height > 0.0:
            entry["maxEdgeGrowthFractionOfHeight"] = float(
                entry["maxEdgeGrowth"] / float(subject_height)
            )
        if rest_joints is not None and joint_names is not None:
            centroid = entry["centroid"]
            nearest = int(np.argmin(np.linalg.norm(rest_joints - centroid, axis=1)))
            entry["nearestRestJoint"] = joint_names[nearest]
            entry["nearestRestJointDistance"] = float(
                np.linalg.norm(rest_joints[nearest] - centroid)
            )
        regions.append(entry)

    regions.sort(key=lambda row: -float(row["maxStretch"]))
    return {
        "schema": "stretch_regions.v1",
        "limit": float(limit),
        "radius": float(radius),
        "groupedNodes": int(hot.size),
        "regionCount": len(groups),
        "reportedRegions": min(len(regions), int(max_regions)),
        "regions": regions[: int(max_regions)],
    }
