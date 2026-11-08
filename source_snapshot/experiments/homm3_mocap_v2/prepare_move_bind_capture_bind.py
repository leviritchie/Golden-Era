#!/usr/bin/env python3
"""Bind an unrigged Meshy T2 surface to its unit's capture skeleton at the bind frame.

Owned-bones paradigm: the mocap capture skeleton is the rig. The mesh was
generated from the sprite plate at the bind frame, and the capture at that frame
must have an explicitly accepted compatible placement before binding.
No SmartRig, no idle skeleton, no idle-to-flight retarget.

Rest skeleton: joints = bind-frame capture positions, identity local rotations,
bone offsets = bind-frame parent-to-child vectors. The mesh uses the exact
selected static registration composed into capture space. No axis inference
or bounding-box realignment is performed after acceptance. Initial skin weights are a
geodesic nearest-bone-segment initializer (labeled as such); the silhouette
skin solver refines them. The sidecar carries per-vertex region labels
(dominant bone via the unit profile regionJoints, used for welds and
diagnostics) and the per-vertex candidate joint support + train mask the solver
is allowed to redistribute weight over (see candidate_support).

Nothing here is species-specific; every joint name and axis comes from the
unit profile, and a profile without `captureBind` fails closed.

A mesh-specific `homm3.static-bind-registration.v1` artifact must already be
accepted (status=accepted and visualConfirmation=true) for this mesh, capture,
and bind frame. The function refuses before writing a bind GLB if that gate
fails. Image score and rest LBS identity are not acceptance. Front/side/top joint
containment is checked in the registered mesh/source-view frame, the same axes
the idle-0 writer used, not capture-space world slabs after inverse similarity.
Remaining-idle0 sets `HOMM3_ACCEPT_BIND_DEFECTS=1` so registration may keep the
best bind when shrink cannot contain every joint; this binder must consume that
registration instead of raising a second inside-mesh stop.

Generated-artifact only - not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from asset_profiles import get_profile  # noqa: E402
from donor_eagle import bind_world_matrices, inverse_bind_matrices, skin_dense  # noqa: E402
from eagle_glb import inspect_glb_animation, write_skinned_glb  # noqa: E402
from known_rest_mesh import align_surface_to_rest  # noqa: E402
from paths import MOCAP_INTERMEDIATE, REPO  # noqa: E402
from pin import sha256_file  # noqa: E402
from roc_copy import _load_unskinned_triangle_surface  # noqa: E402
from floor_column_bind import CONTAINMENT_POLICY as FLOOR_COLUMN_CONTAINMENT  # noqa: E402
from floor_column_bind import GROUND_HEIGHT_CONTAINMENT  # noqa: E402
from floor_column_bind import SCALE_TO_GROUND_CONTAINMENT  # noqa: E402
from floor_column_bind import SliceVolume  # noqa: E402
from inside_mesh_bind import apply_bone_length_scales, joints_inside_registered_source_view  # noqa: E402
from skeleton_overlay import write_skeleton_overlay  # noqa: E402
from static_bind_registration import (  # noqa: E402
    accepted_bind_rest_joints,
    accepted_bone_length_scales,
    accepted_mesh_alignment,
    apply_similarity,
    require_accepted_static_registration,
)

MOVE_BIND_MESH = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/meshes/h3_roc_move_bind_t2.glb"
MOVE_CAPTURE = MOCAP_INTERMEDIATE / "h3_roc" / "move" / "intermediate_v1_primary" / "capture" / "raw_capture.npz"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_bind/h3_roc_move_bind_t2_capture_f0_bind.glb"
DEFAULT_UNIT = "h3_roc"
K_BONES = 4
WEIGHT_INITIALIZER = "outgoing_segment_largest_voronoi_component_geodesic_inverse_square_k4"
SUPPORT_DISTANCE_RATIO = 2.5
SUPPORT_CAP = 8
# Every rest joint must sit in the 3D AABB and the front/side/top AABBs.
# Length scales may shorten bones; mocap parent-to-child directions stay.
BIND_DEFECT_ENV = "HOMM3_ACCEPT_BIND_DEFECTS"


def accept_bind_defects() -> bool:
    """True when remaining-idle0 asked registration to keep the best bind."""
    return os.environ.get(BIND_DEFECT_ENV) == "1"


def require_capture_bind_spec(profile: dict[str, Any]) -> dict[str, Any]:
    """Profile-declared capture axes and skin region policy for the owned-bones bind."""
    spec = profile.get("captureBind")
    unit = profile.get("assetId")
    if not isinstance(spec, dict):
        raise ValueError(f"profile {unit!r} has no captureBind; declare headJoint/leftJoint/rightJoint/mesh axes")
    for key in ("headJoint", "leftJoint", "rightJoint"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise ValueError(f"profile {unit!r} captureBind.{key} must be a joint name")
    body = np.asarray(spec.get("meshBodyAxis"), dtype=np.float64).reshape(-1)
    second = np.asarray(spec.get("meshSecondAxis"), dtype=np.float64).reshape(-1)
    if body.shape != (3,) or second.shape != (3,):
        raise ValueError(f"profile {unit!r} captureBind mesh axes must be 3-vectors")
    if abs(np.linalg.norm(body) - 1) > 1e-9 or abs(np.linalg.norm(second) - 1) > 1e-9 or abs(body @ second) > 1e-9:
        raise ValueError(f"profile {unit!r} captureBind mesh axes must be orthonormal unit vectors")
    frozen = tuple(str(region) for region in spec.get("skinFrozenRegions", ()))
    regions = set(str(region) for region in profile["regionJoints"])
    unknown = sorted(set(frozen) - regions)
    if unknown:
        raise ValueError(f"profile {unit!r} captureBind.skinFrozenRegions names unknown regions {unknown}")
    return {
        "headJoint": spec["headJoint"],
        "leftJoint": spec["leftJoint"],
        "rightJoint": spec["rightJoint"],
        "meshBodyAxis": body,
        "meshSecondAxis": second,
        "skinFrozenRegions": frozen,
    }


def trainable_regions_for(profile: dict[str, Any], spec: dict[str, Any]) -> tuple[str, ...]:
    """Every profile region is a weight destination unless the profile freezes it."""
    frozen = set(spec["skinFrozenRegions"])
    regions = tuple(str(region) for region in profile["regionJoints"] if str(region) not in frozen)
    if not regions:
        raise ValueError("profile freezes every region; nothing for the skin solver to train")
    return regions


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def regions_sidecar_path(bind_glb: Path) -> Path:
    return bind_glb.with_name(bind_glb.stem + "_regions.json")


def load_capture(capture_path: Path) -> dict[str, Any]:
    raw = np.load(capture_path, allow_pickle=False)
    names = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in np.asarray(raw["joint_names"]).tolist()]
    parents = np.asarray(raw["parents"], dtype=np.int64)
    positions = np.asarray(raw["pred_position"], dtype=np.float64)
    if positions.ndim != 3 or positions.shape[1] != len(names) or positions.shape[2] != 3:
        raise ValueError(f"capture positions must be [T,J,3] matching joint_names, got {positions.shape}")
    if not np.isfinite(positions).all():
        raise ValueError("capture positions contain non-finite values")
    if parents[0] != -1 or any(int(p) < 0 or int(p) >= i for i, p in enumerate(parents[1:], 1)):
        raise ValueError("capture hierarchy must be root-first ordered")
    return {"names": names, "parents": parents, "positions": positions, "sha256": sha256_file(capture_path)}


def frame0_rest_skeleton(
    capture: dict[str, Any],
    bind_frame: int = 0,
    *,
    joints: np.ndarray | None = None,
) -> dict[str, Any]:
    bind_frame = int(bind_frame)
    if bind_frame < 0 or bind_frame >= len(capture["positions"]):
        raise ValueError(f"bind_frame {bind_frame} outside capture length {len(capture['positions'])}")
    if joints is None:
        joints = capture["positions"][bind_frame].copy()
    else:
        joints = np.asarray(joints, dtype=np.float64).copy()
        if joints.shape != capture["positions"][bind_frame].shape:
            raise ValueError(
                f"rest joints shape {joints.shape} != capture bind joints {capture['positions'][bind_frame].shape}"
            )
    parents = capture["parents"]
    offsets = joints - joints[parents.clip(0)]
    offsets[0] = joints[0]
    bind_world = bind_world_matrices(offsets, parents)
    if float(np.abs(bind_world[:, :3, 3] - joints).max()) > 1e-9:
        raise ValueError(f"bind-frame {bind_frame} rest FK does not reproduce capture joints")
    return {
        "joints": joints,
        "offsets": offsets,
        "restLocalRotation": np.repeat(np.eye(3)[None], len(parents), axis=0),
        "bindWorld": bind_world,
        "inverseBind": inverse_bind_matrices(bind_world),
        "boneLengths": np.linalg.norm(offsets, axis=1),
    }


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1e-9:
        raise ValueError("degenerate axis vector")
    return np.asarray(vector, dtype=np.float64) / norm


def semantic_axis_rotation(
    joints: np.ndarray, names: list[str], parents: np.ndarray, spec: dict[str, Any]
) -> dict[str, Any]:
    """Rotation taking the mesh's canonical axes onto the posed capture skeleton's axes.

    Capture side: body = root->headJoint, lateral = leftJoint->rightJoint,
    second = lateral x body, re-orthonormalized. Mesh side: the profile's
    meshBodyAxis / meshSecondAxis in the Meshy canonical frame. The bind-frame
    capture is a camera-relative pose, so this rotation is not a pure 90-degree
    yaw and must not be hard-coded.
    """
    index = {name: i for i, name in enumerate(names)}
    roots = [i for i, parent in enumerate(parents) if int(parent) < 0]
    if len(roots) != 1:
        raise ValueError(f"capture skeleton must have exactly one root, found {len(roots)}")
    for key in ("headJoint", "leftJoint", "rightJoint"):
        if spec[key] not in index:
            raise ValueError(f"captureBind.{key}={spec[key]!r} is not a capture joint")
    body = _unit(joints[index[spec["headJoint"]]] - joints[roots[0]])
    lateral_raw = _unit(joints[index[spec["rightJoint"]]] - joints[index[spec["leftJoint"]]])
    second = _unit(np.cross(lateral_raw, body))
    lateral = np.cross(body, second)
    capture_basis = np.stack([body, second, lateral], axis=1)
    mesh_body = np.asarray(spec["meshBodyAxis"], dtype=np.float64)
    mesh_second = np.asarray(spec["meshSecondAxis"], dtype=np.float64)
    mesh_basis = np.stack([mesh_body, mesh_second, np.cross(mesh_body, mesh_second)], axis=1)
    rotation = capture_basis @ mesh_basis.T
    det = float(np.linalg.det(rotation))
    if abs(det - 1.0) > 1e-9:
        raise ValueError(f"semantic axis rotation is not proper: det={det}")
    return {
        "rotation": rotation,
        "captureBody": body.tolist(),
        "captureSecond": second.tolist(),
        "captureLateral": lateral.tolist(),
        "meshBodyAxis": mesh_body.tolist(),
        "meshSecondAxis": mesh_second.tolist(),
        "rootJoint": names[roots[0]],
        "headJoint": spec["headJoint"],
        "leftJoint": spec["leftJoint"],
        "rightJoint": spec["rightJoint"],
        "policy": "profile_semantic_axes_meshy_canonical_to_capture_bind_frame",
    }


def _segment_distances(verts: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    seg = end - start
    length_sq = float(seg @ seg)
    if length_sq <= 1e-16:
        return np.linalg.norm(verts - end, axis=1)
    t = np.clip(((verts - start) @ seg) / length_sq, 0.0, 1.0)
    closest = start + t[:, None] * seg
    return np.linalg.norm(verts - closest, axis=1)


def _outgoing_child_segment_distances(
    verts: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    *,
    cede_distal: bool,
) -> np.ndarray:
    """Parent shaft distance. A leaf's distal cap is not claimed by the parent.

    On a sausage around the bone, every vertex is closer to the shaft than to
    the tip point, so a leaf's Voronoi cell is empty and geodesic never seeds
    it. Cede vertices that are at least as close to the child joint as to this
    segment. Mid-chain children keep their own outgoing shafts and do not cede.
    """
    segment = _segment_distances(verts, start, end)
    if not cede_distal:
        return segment
    tip = np.linalg.norm(verts - end, axis=1)
    return np.where(tip <= segment + 1e-12, np.inf, segment)


def bone_segment_distances(
    vertices: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    ownership: str = "outgoing",
) -> np.ndarray:
    """[V,J] distance from each vertex to the bone segment owned by each joint.

    ``ownership="outgoing"`` (the skinning contract): joint j owns the segment(s)
    from j to its children. That matches FK — G_j is applied at j and rotates
    those outgoing bones. A leaf has no outgoing segment and is scored by its
    joint point. The parent cedes that distal cap: a vertex at least as close
    to the leaf joint as to the parent shaft belongs to the leaf, so surface
    seeds can start there. Zero-length children are skipped.

    ``ownership="incoming"`` is the previous convention (child owns parent→j).
    It disagrees with outgoing FK transforms and is kept only for diagnostics.
    """
    if ownership not in {"outgoing", "incoming"}:
        raise ValueError(f"ownership must be 'outgoing' or 'incoming', got {ownership!r}")
    verts = np.asarray(vertices, dtype=np.float64)
    rest = np.asarray(joints, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    joint_count = len(rest)
    dist = np.full((len(verts), joint_count), np.inf, dtype=np.float64)
    if ownership == "incoming":
        for index in range(joint_count):
            parent_index = int(parent[index])
            end = rest[index]
            start = rest[parent_index] if parent_index >= 0 else end
            seg = end - start
            length_sq = float(seg @ seg)
            if parent_index >= 0 and length_sq <= 1e-16:
                continue
            dist[:, index] = _segment_distances(verts, start, end)
        return dist
    children: list[list[int]] = [[] for _ in range(joint_count)]
    for index, parent_index in enumerate(parent):
        if int(parent_index) >= 0:
            children[int(parent_index)].append(index)
    usable_children = [
        [
            child
            for child in children[index]
            if float(np.linalg.norm(rest[child] - rest[index]) ** 2) > 1e-16
        ]
        for index in range(joint_count)
    ]
    is_leaf = [len(kids) == 0 for kids in usable_children]
    for index in range(joint_count):
        usable = usable_children[index]
        if not usable:
            dist[:, index] = np.linalg.norm(verts - rest[index], axis=1)
            continue
        stacked = np.stack(
            [
                _outgoing_child_segment_distances(
                    verts, rest[index], rest[child], cede_distal=is_leaf[child]
                )
                for child in usable
            ],
            axis=1,
        )
        dist[:, index] = stacked.min(axis=1)
    return dist


def triangle_vertex_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    verts = np.asarray(vertices, dtype=np.float64)
    tri = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    face = np.cross(verts[tri[:, 1]] - verts[tri[:, 0]], verts[tri[:, 2]] - verts[tri[:, 0]])
    normals = np.zeros_like(verts)
    for corner in range(3):
        np.add.at(normals, tri[:, corner], face)
    length = np.linalg.norm(normals, axis=1)
    length = np.where(length < 1e-12, 1.0, length)
    return normals / length[:, None]


def _mesh_edges(triangles: np.ndarray) -> np.ndarray:
    tri = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    edges = np.concatenate((tri[:, :2], tri[:, 1:], tri[:, [0, 2]]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    return edges[edges[:, 0] != edges[:, 1]]


def _coincident_pairs(vertices: np.ndarray, *, export_position: bool = False) -> list[tuple[int, int]]:
    buckets: dict[tuple[float, ...], list[int]] = {}
    points = (np.asarray(vertices, dtype=np.float32) if export_position
              else np.round(np.asarray(vertices, dtype=np.float64), 6))
    for index, point in enumerate(map(tuple, points)):
        buckets.setdefault(point, []).append(index)
    return [(members[0], other) for members in buckets.values() for other in members[1:]]


def _voronoi_component_seeds(
    nearest: np.ndarray,
    edges: np.ndarray,
    euclidean_col: np.ndarray,
    bone: int,
) -> np.ndarray:
    """Largest surface-connected island of vertices whose nearest bone is `bone`.

    Components are taken on that Voronoi subset, not the whole mesh. A one-vertex
    contact island on a folded wing therefore cannot join the real wing island
    through the body.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    members = np.flatnonzero((nearest == bone) & np.isfinite(euclidean_col))
    if len(members) == 0:
        return members
    remap = {int(vertex): index for index, vertex in enumerate(members)}
    member_set = set(remap)
    rows: list[int] = []
    cols: list[int] = []
    for start, end in np.asarray(edges, dtype=np.int64):
        if int(start) in member_set and int(end) in member_set:
            rows.append(remap[int(start)])
            cols.append(remap[int(end)])
    count = len(members)
    if rows:
        graph = coo_matrix(
            (np.ones(len(rows), dtype=np.float64), (np.asarray(rows), np.asarray(cols))),
            shape=(count, count),
        ).tocsr()
        graph = graph.maximum(graph.T)
        _, labels = connected_components(graph, directed=False)
    else:
        labels = np.arange(count, dtype=np.int32)
    best_label = None
    best: tuple[int, float] | None = None
    for label in np.unique(labels):
        sel = members[labels == label]
        key = (len(sel), -float(euclidean_col[sel].min()))
        if best is None or key > best:
            best = key
            best_label = int(label)
    return members[labels == best_label]


CONNECTION_POLICIES = ("all_edges", "drop_narrow_incidental")


def _undirected_adj(count: int, edges: np.ndarray) -> list[list[int]]:
    adj: list[list[int]] = [[] for _ in range(count)]
    for start, end in np.asarray(edges, dtype=np.int64):
        adj[int(start)].append(int(end))
        adj[int(end)].append(int(start))
    return adj


def _bfs_hops(
    start: int,
    adj: list[list[int]],
    *,
    blocked: set[tuple[int, int]] | None = None,
    allowed: set[int] | None = None,
    skip: set[int] | None = None,
    max_hops: int | None = None,
) -> dict[int, int]:
    from collections import deque

    dist = {start: 0}
    queue = deque([start])
    while queue:
        vertex = queue.popleft()
        if max_hops is not None and dist[vertex] >= max_hops:
            continue
        for other in adj[vertex]:
            if skip is not None and other in skip:
                continue
            if allowed is not None and other not in allowed:
                continue
            if blocked is not None and (min(vertex, other), max(vertex, other)) in blocked:
                continue
            if other in dist:
                continue
            dist[other] = dist[vertex] + 1
            queue.append(other)
    return dist


def _local_crossing_edges(
    start: int,
    end: int,
    adj: list[list[int]],
    edge_index: dict[tuple[int, int], int],
    *,
    hops: int,
    max_cut: int,
    min_side: int,
) -> list[int]:
    """Min-cut of the 2-hop ball after the seed edge is removed, plus that edge."""
    from collections import deque

    ball = set(_bfs_hops(start, adj, max_hops=hops))
    ball.update(_bfs_hops(end, adj, max_hops=hops))
    seed = (min(start, end), max(start, end))
    residual: dict[int, dict[int, int]] = {vertex: {} for vertex in ball}
    for vertex in ball:
        for other in adj[vertex]:
            if other not in ball:
                continue
            if (min(vertex, other), max(vertex, other)) == seed:
                continue
            residual[vertex][other] = 1

    def augment() -> list[int] | None:
        prev = {start: start}
        queue = deque([start])
        while queue:
            vertex = queue.popleft()
            for other, cap in residual[vertex].items():
                if cap <= 0 or other in prev:
                    continue
                prev[other] = vertex
                if other == end:
                    path = [end]
                    while path[-1] != start:
                        path.append(prev[path[-1]])
                    path.reverse()
                    return path
                queue.append(other)
        return None

    flow = 0
    while flow < max_cut:
        path = augment()
        if path is None:
            break
        flow += 1
        for left, right in zip(path, path[1:]):
            residual[left][right] -= 1
            residual[right][left] = residual[right].get(left, 0) + 1
    if flow >= max_cut or seed not in edge_index:
        return []
    residual_adj = {vertex: [other for other, cap in residual[vertex].items() if cap > 0] for vertex in residual}
    reachable = set(_bfs_hops(start, residual_adj, allowed=ball))
    if len(reachable) < min_side or len(ball - reachable) < min_side:
        return []
    cut = {edge_index[seed]}
    for vertex in reachable:
        for other in adj[vertex]:
            if other in reachable or other not in ball:
                continue
            key = (min(vertex, other), max(vertex, other))
            if key in edge_index:
                cut.add(edge_index[key])
    return list(cut)


def narrow_incidental_edge_mask(
    vertices: np.ndarray,
    edges: np.ndarray,
    *,
    max_cut: int = 6,
    local_hops: int = 2,
    min_detour_hops: int = 16,
    min_side: int = 8,
) -> np.ndarray:
    """True for edges that are only a narrow accidental contact.

    Around each edge, the local crossing belt is the small set of edges that
    actually join the two sides of a 2-hop ball. A wide surface has a large
    belt, so it is left alone. A 1–few-triangle glue has a small belt.

    The belt is dropped only when both sides of that local ball are bulky
    and a long walk still exists after it is gone. A tube slice is not
    dropped. Extra glue between two masses is.
    """
    if max_cut < 1:
        raise ValueError(f"max_cut must be >= 1, got {max_cut}")
    mesh_edges = np.asarray(edges, dtype=np.int64)
    count = len(np.asarray(vertices))
    if len(mesh_edges) == 0:
        return np.zeros(0, dtype=bool)
    adj = _undirected_adj(count, mesh_edges)
    edge_index = {
        (int(min(start, end)), int(max(start, end))): index
        for index, (start, end) in enumerate(mesh_edges)
    }
    drop = np.zeros(len(mesh_edges), dtype=bool)
    seen: dict[frozenset[int], int | None] = {}
    for start, end in mesh_edges:
        start_i, end_i = int(start), int(end)
        cut_list = _local_crossing_edges(
            start_i,
            end_i,
            adj,
            edge_index,
            hops=local_hops,
            max_cut=max_cut,
            min_side=min_side,
        )
        if not cut_list or len(cut_list) > max_cut:
            continue
        key = frozenset(cut_list)
        if key not in seen:
            blocked = {(int(min(mesh_edges[i, 0], mesh_edges[i, 1])), int(max(mesh_edges[i, 0], mesh_edges[i, 1]))) for i in cut_list}
            hops = _bfs_hops(start_i, adj, blocked=blocked).get(end_i)
            seen[key] = hops
        hops = seen[key]
        if hops is not None and int(hops) >= min_detour_hops:
            drop[cut_list] = True
    return drop


def geodesic_bone_distances(
    vertices: np.ndarray,
    triangles: np.ndarray,
    euclidean: np.ndarray,
    *,
    seed_policy: str = "largest_voronoi_component",
    weld_policy: str = "coincident_agreeing_normals",
    connection_policy: str = "all_edges",
    max_incidental_cut: int = 6,
    progress: Any = None,
) -> dict[str, Any]:
    """[V,J] bone distance along the mesh surface.

    Seeds and propagation are separate. The default seed is the largest
    triangle-connected Euclidean-Voronoi island of that bone on each welded
    surface component, not every raw UV flake that happens to be nearest in
    empty space. Meshy meshes split one sheet into thousands of index islands
    at UV/hard edges. Those flakes occupy the same surface after a weld. A
    flake on the far side of a visible gap is therefore not a seed just
    because a foreign bone is closer through the air.

    Voronoi islands still use triangle edges only. A weld may join two UV
    copies of one point; it must not merge a belly contact vertex into the
    wing's seed island.

    Welds reconnect UV splits whose normals agree. Coincident vertices from
    two touching parts with opposing normals stay separate.

    The capture binder explicitly selects ``export_position`` instead: its
    whole-mesh repair field welds all exact float32 GLB positions, irrespective
    of normals. Distances, initial weights, and candidate support must therefore
    agree at those positions before the field is constructed.

    ``seed_policy="euclidean_voronoi"`` is the previous self-seeding helper
    and is kept only so tests can show that it preserves the Euclidean winner.

    ``connection_policy="drop_narrow_incidental"`` deletes a small local
    crossing belt when a long surface walk still exists without it. Extra
    glue is ignored. The only root of a wing or tail stays. The pipeline
    initializer keeps ``all_edges``.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components, dijkstra

    if seed_policy not in {"largest_voronoi_component", "euclidean_voronoi"}:
        raise ValueError(f"unknown seed_policy {seed_policy!r}")
    if weld_policy not in {"coincident_agreeing_normals", "coincident", "export_position"}:
        raise ValueError(f"unknown weld_policy {weld_policy!r}")
    if connection_policy not in CONNECTION_POLICIES:
        raise ValueError(f"unknown connection_policy {connection_policy!r}")
    if max_incidental_cut < 1 or max_incidental_cut > 16:
        raise ValueError(f"max_incidental_cut must be 1..16, got {max_incidental_cut}")

    verts = np.asarray(vertices, dtype=np.float64)
    euclid = np.asarray(euclidean, dtype=np.float64)
    count = len(verts)
    edges = _mesh_edges(triangles)
    dropped_incidental = 0
    if connection_policy == "drop_narrow_incidental":
        drop = narrow_incidental_edge_mask(verts, edges, max_cut=int(max_incidental_cut))
        dropped_incidental = int(drop.sum())
        edges = edges[~drop]
    lengths = np.linalg.norm(verts[edges[:, 0]] - verts[edges[:, 1]], axis=1)
    normals = triangle_vertex_normals(verts, triangles)
    pairs = _coincident_pairs(verts, export_position=weld_policy == "export_position")
    if weld_policy == "coincident_agreeing_normals":
        weld_pairs = [(a, b) for a, b in pairs if float(np.dot(normals[a], normals[b])) > 0.0]
    else:
        weld_pairs = pairs
    weld_cost = 1e-9
    rows = np.concatenate([edges[:, 0], np.asarray([a for a, _ in weld_pairs], dtype=np.int64)])
    cols = np.concatenate([edges[:, 1], np.asarray([b for _, b in weld_pairs], dtype=np.int64)])
    costs = np.concatenate([lengths, np.full(len(weld_pairs), weld_cost)])
    graph = coo_matrix((costs, (rows, cols)), shape=(count, count)).tocsr()
    graph = graph.maximum(graph.T)
    base = graph.tocoo()
    _, mesh_labels = connected_components(graph, directed=False)
    finite = np.where(np.isfinite(euclid), euclid, np.inf)
    nearest = np.argmin(finite, axis=1)
    nearest = np.where(np.isfinite(np.take_along_axis(euclid, nearest[:, None], axis=1)[:, 0]), nearest, -1)
    geodesic = np.full_like(euclid, np.inf)
    seeded_bones = 0
    seed_counts: list[int] = []
    for bone in range(euclid.shape[1]):
        if progress is not None:
            progress(bone, euclid.shape[1])
        if seed_policy == "euclidean_voronoi":
            seeds = np.flatnonzero(nearest == bone)
        else:
            parts = []
            masked = nearest.copy()
            for label in np.unique(mesh_labels):
                masked[:] = nearest
                masked[mesh_labels != label] = -1
                part = _voronoi_component_seeds(masked, edges, euclid[:, bone], bone)
                if len(part):
                    parts.append(part)
            seeds = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)
        if len(seeds) == 0:
            seed_counts.append(0)
            continue
        seeded_bones += 1
        seed_counts.append(int(len(seeds)))
        seed_cost = np.maximum(euclid[seeds, bone], weld_cost)
        source = np.full(len(seeds), count, dtype=np.int64)
        aug = coo_matrix(
            (np.concatenate([base.data, seed_cost]), (np.concatenate([base.row, source]), np.concatenate([base.col, seeds]))),
            shape=(count + 1, count + 1),
        ).tocsr()
        geodesic[:, bone] = dijkstra(aug, directed=False, indices=count)[:count]
    if progress is not None:
        progress(euclid.shape[1], euclid.shape[1])
    if weld_policy == "export_position":
        # The fitter owns one degree of freedom per exact exported position.
        # Remove the artificial positive weld-edge cost before deriving weights
        # and support, so both are computed from the same quotient-node distance.
        groups: dict[int, list[int]] = {}
        for first, other in weld_pairs:
            groups.setdefault(first, [first]).append(other)
        for members in groups.values():
            geodesic[members] = geodesic[members].min(axis=0)
    reachable = np.isfinite(geodesic).sum(axis=1)
    if int(reachable.min()) < 1:
        raise ValueError("a vertex reaches no bone along the surface")
    return {
        "distances": geodesic,
        "seededBones": seeded_bones,
        "seedCounts": seed_counts,
        "weldedPairs": len(weld_pairs),
        "minReachableBonesPerVertex": int(reachable.min()),
        "seedPolicy": seed_policy,
        "weldPolicy": weld_policy,
        "connectionPolicy": connection_policy,
        "maxIncidentalCut": int(max_incidental_cut),
        "droppedIncidentalEdges": dropped_incidental,
        "policy": f"surface_dijkstra_{seed_policy}_{weld_policy}_{connection_policy}",
    }


def build_initializer_weights(
    vertices: np.ndarray,
    triangles: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    k: int = K_BONES,
    ownership: str = "outgoing",
    seed_policy: str = "largest_voronoi_component",
    weld_policy: str = "coincident_agreeing_normals",
) -> dict[str, Any]:
    euclidean = bone_segment_distances(vertices, joints, parents, ownership=ownership)
    geodesic = geodesic_bone_distances(
        vertices, triangles, euclidean, seed_policy=seed_policy, weld_policy=weld_policy
    )
    weights = nearest_bone_segment_weights(geodesic["distances"], k=k)
    return {
        "weights": weights,
        "euclidean": euclidean,
        "geodesic": geodesic,
        "ownership": ownership,
        "seedPolicy": seed_policy,
        "weldPolicy": weld_policy,
        "k": int(k),
    }


def nearest_bone_segment_weights(dist: np.ndarray, *, k: int) -> np.ndarray:
    """Inverse-square weights over up to k nearest reachable bones from a [V,J] distance table."""
    finite = np.isfinite(dist).sum(axis=1)
    if int(finite.min()) < 1:
        raise ValueError("a vertex has no reachable bone")
    verts_count, joint_count = dist.shape
    nearest = np.argpartition(dist, kth=k - 1, axis=1)[:, :k]
    picked = np.take_along_axis(dist, nearest, axis=1)
    weights = 1.0 / (picked * picked + 1e-8)
    weights = weights / weights.sum(axis=1, keepdims=True)
    dense = np.zeros((verts_count, joint_count), dtype=np.float64)
    rows = np.repeat(np.arange(verts_count), k)
    dense[rows, nearest.reshape(-1)] = weights.reshape(-1)
    return dense


def candidate_support(
    dist: np.ndarray,
    initial_weights: np.ndarray,
    joint_regions: list[str],
    *,
    trainable_regions: tuple[str, ...],
    ratio: float,
    cap: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-vertex joint support the solver may redistribute weight over.

    Support = the initializer's bones (so the initial weights are inside it) plus
    the nearest bone of every trainable region whose distance is within `ratio`
    times the vertex's nearest-bone distance, kept to `cap` joints by distance.
    A vertex is trainable when its support holds more than one joint and at
    least one of them is in a trainable region. This is what lets a belly or
    wing-root vertex that the initializer handed to a folded leg bone follow the
    wing instead: the wing bone is a geometric candidate, so the solver may move
    weight onto it.
    """
    verts_count, joint_count = dist.shape
    joint_regions = list(joint_regions)
    if len(joint_regions) != joint_count:
        raise ValueError("joint_regions must name a region per joint")
    trainable_joint = np.asarray([region in trainable_regions for region in joint_regions])
    support = initial_weights > 1e-8
    nearest_distance = np.where(support, dist, np.inf).min(axis=1)
    if not np.isfinite(nearest_distance).all():
        raise ValueError("every vertex needs at least one finite initializer bone distance")
    for region in trainable_regions:
        members = np.asarray([r == region for r in joint_regions])
        if not members.any():
            raise ValueError(f"trainable region {region} has no joints")
        region_dist = np.where(members[None, :], dist, np.inf)
        best = np.argmin(region_dist, axis=1)
        best_dist = region_dist[np.arange(verts_count), best]
        add = np.isfinite(best_dist) & (best_dist <= ratio * nearest_distance)
        support[np.arange(verts_count)[add], best[add]] = True
    over = support.sum(axis=1) > cap
    if over.any():
        ranked = np.argsort(np.where(support, dist, np.inf), axis=1)
        keep = np.zeros_like(support)
        rows = np.repeat(np.arange(verts_count), cap)
        keep[rows, ranked[:, :cap].reshape(-1)] = True
        # Never drop an initializer bone: it carries the initial weight.
        keep |= initial_weights > 1e-8
        if np.any(keep.sum(axis=1) > cap):
            raise ValueError("initializer bones alone exceed the support cap")
        support = np.where(over[:, None], keep, support)
    trainable = (support.sum(axis=1) > 1) & (support & trainable_joint[None, :]).any(axis=1)
    return support, trainable


def dominant_bone_regions(dense: np.ndarray, names: list[str], region_joints: dict[str, list[str]]) -> np.ndarray:
    bone_region: dict[str, str] = {}
    for region, bones in region_joints.items():
        for bone in bones:
            if bone in bone_region:
                raise ValueError(f"joint {bone} belongs to two regions: {bone_region[bone]} and {region}")
            bone_region[bone] = region
    missing = [name for name in names if name not in bone_region]
    if missing:
        raise ValueError(f"profile regionJoints does not cover capture joints: {missing}")
    argmax = np.argmax(dense, axis=1)
    return np.asarray([bone_region[names[int(index)]] for index in argmax], dtype=object)


def prepare_move_bind_capture_bind(
    *,
    mesh_glb: Path,
    capture_path: Path,
    out_glb: Path,
    bind_frame: int = 0,
    unit: str = DEFAULT_UNIT,
    static_registration: Path | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not mesh_glb.is_file():
        raise FileNotFoundError(mesh_glb)
    if not capture_path.is_file():
        raise FileNotFoundError(capture_path)
    capture = load_capture(capture_path)
    registration = require_accepted_static_registration(
        static_registration,
        mesh_sha256=sha256_file(mesh_glb),
        capture_sha256=capture["sha256"],
        bind_frame=int(bind_frame),
    )
    if profile is None:
        profile = get_profile(unit)
    if profile.get("assetId") != unit:
        raise ValueError(f"profile for {unit!r} reports assetId {profile.get('assetId')!r}")
    spec = require_capture_bind_spec(profile)
    trainable_regions = trainable_regions_for(profile, spec)
    region_joints = {str(region): [str(bone) for bone in bones] for region, bones in profile["regionJoints"].items()}

    names = list(capture["names"])
    parents = capture["parents"]
    length_scales = accepted_bone_length_scales(registration, len(names))
    bind_rest = accepted_bind_rest_joints(registration, len(names))
    if bind_rest is not None:
        rest_joints = bind_rest
    else:
        rest_joints = apply_bone_length_scales(
            capture["positions"][int(bind_frame)], parents, length_scales
        )
    rest = frame0_rest_skeleton(capture, bind_frame=bind_frame, joints=rest_joints)
    surface = _load_unskinned_triangle_surface(mesh_glb)
    aligned = accepted_mesh_alignment(registration)
    vertices = (
        aligned["scale"] * (np.asarray(surface["vertices"], dtype=np.float64)
                            @ np.asarray(aligned["rotation"]).T)
        + np.asarray(aligned["translation"])
    )
    # GLB POSITION is float32; use the consumer's exact coordinates already when
    # constructing its welded initial field, rather than a float64 near-match.
    vertices = vertices.astype(np.float32).astype(np.float64)
    selected_id = registration["acceptance"]["selectedCandidateId"]
    selected = next(row for row in registration["views"]["candidates"] if row.get("id") == selected_id)
    skeleton = selected["skeletonSimilarity"]
    containment = str(skeleton.get("containmentPolicy") or "")
    if bind_rest is not None and containment == FLOOR_COLUMN_CONTAINMENT:
        bind_policy = "floor_column_xz"
    elif bind_rest is not None and containment == GROUND_HEIGHT_CONTAINMENT:
        bind_policy = "ground_height_only"
    elif bind_rest is not None and containment == SCALE_TO_GROUND_CONTAINMENT:
        bind_policy = "scale_to_ground"
    elif bind_rest is not None:
        bind_policy = "bind_first_inside_mesh"
    else:
        bind_policy = "length_scales_or_identity"
    registration_provenance = {
        "artifact": str(Path(static_registration).resolve()),
        "sha256": sha256_file(Path(static_registration)),
        "selectedCandidateId": aligned["selectedCandidateId"],
        "boneLengthScales": length_scales.tolist(),
        "bindRestJoints": None if bind_rest is None else bind_rest.tolist(),
        "bindPolicy": bind_policy,
    }
    mesh_rotation = np.asarray(selected["meshToSourceView"]["rotation"], dtype=np.float64)
    if containment == FLOOR_COLUMN_CONTAINMENT:
        mesh_source = np.asarray(surface["vertices"], dtype=np.float64) @ mesh_rotation.T
        placed = apply_similarity(
            rest["joints"],
            rotation=np.asarray(skeleton["rotation"], dtype=np.float64),
            scale=float(skeleton["scale"]),
            translation=np.asarray(skeleton["translation"], dtype=np.float64),
        )
        volume = SliceVolume(mesh_source, surface["triangles"])
        inside = volume.all_joints_inside(placed)
        placement = volume.placement_report(placed)
        feet = [int(index) for index in skeleton.get("footIndices") or ()]
        if feet and abs(float(placed[np.asarray(feet, dtype=np.int64), 1].min()) - volume.floor_y) > 1e-4:
            inside = False
            placement = {**placement, "reason": "feet_not_on_mesh_floor"}
    elif containment == GROUND_HEIGHT_CONTAINMENT:
        mesh_source = np.asarray(surface["vertices"], dtype=np.float64) @ mesh_rotation.T
        placed = apply_similarity(
            rest["joints"],
            rotation=np.asarray(skeleton["rotation"], dtype=np.float64),
            scale=float(skeleton["scale"]),
            translation=np.asarray(skeleton["translation"], dtype=np.float64),
        )
        floor_y = float(mesh_source[:, 1].min())
        top_y = float(mesh_source[:, 1].max())
        feet = [int(index) for index in skeleton.get("footIndices") or ()]
        feet_on_floor = bool(feet) and abs(
            float(placed[np.asarray(feet, dtype=np.int64), 1].min()) - floor_y
        ) <= 1e-4
        top_ok = abs(float(placed[:, 1].max()) - top_y) <= 1e-4
        inside = feet_on_floor and top_ok
        placement = {
            "policy": GROUND_HEIGHT_CONTAINMENT,
            "feetOnFloor": feet_on_floor,
            "topOnMeshTop": top_ok,
            "reason": None
            if inside
            else ("feet_not_on_mesh_floor" if not feet_on_floor else "top_not_on_mesh_top"),
            "worstViewOutsideFraction": 0.0,
            "worstViewMaxDistanceOutsideFractionOfDiagonal": 0.0,
        }
    elif containment == SCALE_TO_GROUND_CONTAINMENT:
        mesh_source = np.asarray(surface["vertices"], dtype=np.float64) @ mesh_rotation.T
        placed = apply_similarity(
            rest["joints"],
            rotation=np.asarray(skeleton["rotation"], dtype=np.float64),
            scale=float(skeleton["scale"]),
            translation=np.asarray(skeleton["translation"], dtype=np.float64),
        )
        floor_y = float(mesh_source[:, 1].min())
        feet = [int(index) for index in skeleton.get("footIndices") or ()]
        feet_on_floor = bool(feet) and abs(
            float(placed[np.asarray(feet, dtype=np.int64), 1].min()) - floor_y
        ) <= 1e-4
        inside = feet_on_floor
        placement = {
            "policy": SCALE_TO_GROUND_CONTAINMENT,
            "feetOnFloor": feet_on_floor,
            "reason": None if inside else "feet_not_on_mesh_floor",
            "worstViewOutsideFraction": 0.0,
            "worstViewMaxDistanceOutsideFractionOfDiagonal": 0.0,
        }
    else:
        check_joints = rest["joints"]
        named = skeleton.get("containmentJointNames")
        if named is not None:
            wanted = {str(name) for name in named}
            missing = sorted(wanted - set(names))
            if missing:
                raise ValueError(f"containmentJointNames not in bind skeleton: {missing}")
            mask = np.array([name in wanted for name in names], dtype=bool)
            check_joints = rest["joints"][mask]
        inside, placement = joints_inside_registered_source_view(
            surface["vertices"],
            check_joints,
            mesh_rotation=mesh_rotation,
            skeleton_rotation=np.asarray(skeleton["rotation"], dtype=np.float64),
            scale=float(skeleton["scale"]),
            translation=np.asarray(skeleton["translation"], dtype=np.float64),
        )
    if not inside:
        diagnostic = out_glb.with_name(out_glb.stem + "_placement_failed.json")
        if containment in (GROUND_HEIGHT_CONTAINMENT, SCALE_TO_GROUND_CONTAINMENT):
            reason = str(placement.get("reason") or "ground_height_extents_miss")
            _write_json(
                diagnostic,
                {
                    "ok": False,
                    "unit": unit,
                    "reason": reason,
                    "placement": placement,
                    "staticRegistration": registration_provenance,
                },
            )
            label = (
                "scale-to-ground bind left feet off the mesh floor"
                if containment == SCALE_TO_GROUND_CONTAINMENT
                else "ground-height bind left feet or top off the mesh extents"
            )
            raise RuntimeError(f"{label}; reason={reason} wrote {diagnostic}")
        _write_json(
            diagnostic,
            {
                "ok": False,
                "unit": unit,
                "reason": "skeleton_outside_mesh_front_side_top",
                "worstViewOutsideFraction": placement["worstViewOutsideFraction"],
                "worstViewMaxDistanceOutsideFractionOfDiagonal": placement[
                    "worstViewMaxDistanceOutsideFractionOfDiagonal"
                ],
                "placement": placement,
                "staticRegistration": registration_provenance,
            },
        )
        if accept_bind_defects() and containment not in {
            GROUND_HEIGHT_CONTAINMENT,
            SCALE_TO_GROUND_CONTAINMENT,
            FLOOR_COLUMN_CONTAINMENT,
        }:
            placement = {
                **placement,
                "acceptedDefect": "joints_outside_mesh",
                "acceptedDefectSource": BIND_DEFECT_ENV,
            }
            registration_provenance = {
                **registration_provenance,
                "acceptedDefect": "joints_outside_mesh",
            }
        else:
            raise RuntimeError(
                "accepted static registration leaves joints outside the mesh; "
                f"worstViewOutside={placement['worstViewOutsideFraction']:.3f} "
                f"maxOutsideDiag={placement['worstViewMaxDistanceOutsideFractionOfDiagonal']:.3f} "
                f"wrote {diagnostic}"
            )

    initial = build_initializer_weights(
        vertices, surface["triangles"], rest["joints"], parents,
        weld_policy="export_position",
    )
    geodesic = initial["geodesic"]
    dist = geodesic["distances"]
    weights = initial["weights"]
    regions = dominant_bone_regions(weights, names, region_joints)
    joint_region = {bone: region for region, bones in region_joints.items() for bone in bones}
    support, trainable = candidate_support(
        dist, weights, [joint_region[name] for name in names],
        trainable_regions=trainable_regions, ratio=SUPPORT_DISTANCE_RATIO, cap=SUPPORT_CAP,
    )
    identity = skin_dense(vertices, weights, rest["bindWorld"], rest["inverseBind"])
    identity_err = float(np.linalg.norm(identity - vertices, axis=1).max())
    if identity_err > 1e-6:
        raise RuntimeError(f"capture-f0 bind is not identity at rest: {identity_err}")

    out_glb.parent.mkdir(parents=True, exist_ok=True)
    export = write_skinned_glb(
        out_glb,
        names=names,
        parents=parents,
        rest_local_rotation=rest["restLocalRotation"],
        rest_local_translation=rest["offsets"],
        inverse_bind=rest["inverseBind"],
        vertices=vertices,
        triangles=np.asarray(surface["triangles"], dtype=np.int64),
        uvs=np.asarray(surface["uvs"], dtype=np.float64),
        albedo=np.asarray(surface["albedo"]),
        weights=weights,
    )
    inspect = inspect_glb_animation(out_glb)
    if inspect["animationCount"] != 0:
        raise RuntimeError("bind GLB must not carry clip animation")

    region_counts = {str(region): int((regions == region).sum()) for region in sorted(set(regions.tolist()))}
    trainable_by_region = {
        str(region): int((trainable & (regions == region)).sum()) for region in sorted(set(regions.tolist()))
    }
    _write_json(
        regions_sidecar_path(out_glb),
        {
            "schema": "vertex_regions_v2",
            "bindGlb": str(out_glb).replace("\\", "/"),
            "bindSha256": sha256_file(out_glb),
            "unit": unit,
            "staticRegistration": registration_provenance,
            "surfaceAlignment": aligned,
            "regionSource": "dominant_bone_of_initializer_weights_via_unit_profile_regionJoints",
            "regionJoints": region_joints,
            "regions": regions.astype(str).tolist(),
            "regionCounts": region_counts,
            "jointNames": names,
            "supportRule": {
                "policy": "initializer_bones_plus_nearest_bone_per_trainable_region_within_ratio",
                "trainableRegions": list(trainable_regions),
                "frozenRegions": list(spec["skinFrozenRegions"]),
                "distanceRatio": SUPPORT_DISTANCE_RATIO,
                "cap": SUPPORT_CAP,
                "trainableWhen": "support_size_gt_1_and_contains_trainable_region_joint",
            },
            "candidateSupport": [np.flatnonzero(row).tolist() for row in support],
            "trainable": trainable.tolist(),
            "trainableCount": int(trainable.sum()),
            "trainableByRegion": trainable_by_region,
            "supportSizeHistogram": {int(k): int(v) for k, v in zip(*np.unique(support.sum(axis=1), return_counts=True))},
        },
    )
    overlay = out_glb.with_name(out_glb.stem + "_skeleton_overlay.png")
    write_skeleton_overlay(
        overlay,
        vertices=vertices,
        regions=regions,
        joints=rest["joints"],
        parents=parents,
        names=names,
        title=f"{mesh_glb.name} aligned to {unit} capture skeleton at bind frame {bind_frame}",
    )
    report = {
        "ok": True,
        "paradigm": "owned_bones_capture_skeleton_bind_frame_rest",
        "unit": unit,
        "mesh": str(mesh_glb).replace("\\", "/"),
        "meshSha256": sha256_file(mesh_glb),
        "capture": str(capture_path).replace("\\", "/"),
        "captureSha256": capture["sha256"],
        "restFrame": int(bind_frame),
        "bindGlb": str(out_glb).replace("\\", "/"),
        "bindSha256": sha256_file(out_glb),
        "regionsSidecar": str(regions_sidecar_path(out_glb)).replace("\\", "/"),
        "vertexCount": int(len(vertices)),
        "jointCount": len(names),
        "zeroLengthBones": [names[i] for i in range(1, len(names)) if rest["boneLengths"][i] <= 1e-8],
        "staticRegistration": registration_provenance,
        "surfaceAlignment": aligned,
        "weightInitializer": WEIGHT_INITIALIZER,
        "boneDistance": {key: value for key, value in geodesic.items() if key != "distances"},
        "regionCounts": region_counts,
        "trainableCount": int(trainable.sum()),
        "trainableByRegion": trainable_by_region,
        "skeletonPlacement": placement,
        "skeletonOverlayPng": str(overlay).replace("\\", "/"),
        "bindSkinIdentityMax": identity_err,
        "exportTruncation": export["truncation"],
        "glbInspect": inspect,
        "proof": "generated-artifact - T2 surface on capture bind-frame skeleton with initializer weights; not OE runtime",
    }
    _write_json(out_glb.with_suffix(".report.json"), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="profile id (asset_profiles.get_profile)")
    parser.add_argument("--mesh", type=Path, default=MOVE_BIND_MESH)
    parser.add_argument("--capture", type=Path, default=MOVE_CAPTURE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bind-frame", type=int, default=0)
    parser.add_argument(
        "--static-registration",
        type=Path,
        required=True,
        help="accepted homm3.static-bind-registration.v1 artifact; required before any bind GLB is written",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else REPO / args.out
    if out.exists() and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite {out} (pass --overwrite)")
    report = prepare_move_bind_capture_bind(
        mesh_glb=args.mesh if args.mesh.is_absolute() else REPO / args.mesh,
        capture_path=args.capture if args.capture.is_absolute() else REPO / args.capture,
        out_glb=out,
        bind_frame=int(args.bind_frame),
        unit=args.unit,
        static_registration=args.static_registration if args.static_registration.is_absolute() else REPO / args.static_registration,
    )
    summary = {
        k: report[k]
        for k in ("ok", "bindGlb", "vertexCount", "jointCount", "regionCounts", "trainableCount", "trainableByRegion", "skeletonOverlayPng", "zeroLengthBones")
    }
    summary["jointsOutsideMeshBbox"] = report["skeletonPlacement"]["jointsOutsideCount"]
    summary["maxOutsideFractionOfDiagonal"] = report["skeletonPlacement"]["maxDistanceOutsideFractionOfDiagonal"]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
