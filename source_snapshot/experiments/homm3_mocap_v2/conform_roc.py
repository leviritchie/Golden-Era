"""Articulated registration of the Roc copy onto the fixed Eagle T-pose bind."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from donor_eagle import compute_rest_joints
from mesh_preview import rotation_between
from roc_copy import (
    FOOT_BONES,
    HEAD_BONE,
    ROC_TO_EAGLE_LANDMARKS,
    coalesce_coincidences,
    component_representatives,
    roc_to_eagle_bones,
)

MAX_REVISIONS = 3
HANDLE_SOFT = 40.0
COINCIDENCE_WEIGHT = 80.0
NUMERICAL_STAY = 1e-10
LOCAL_EDGE_P95_LIMIT = 1.8
LOCAL_EDGE_MAX_LIMIT = 10.0
LOCAL_EDGE_P05_MIN = 0.25
ATTACHMENT_RATIO_MIN = 0.45
ATTACHMENT_RATIO_MAX = 2.2
NEW_DEGENERATE_LIMIT = 0

REVISION_SOLVERS = (
    {"name": "lbs_arap_patches", "arap_iterations": 8, "patch_size": 32, "coincidence_weight": COINCIDENCE_WEIGHT},
    {"name": "lbs_arap_islands", "arap_iterations": 12, "patch_size": 48, "coincidence_weight": 200.0},
    {"name": "lbs_arap_hard_coincidence", "arap_iterations": 16, "patch_size": 64, "coincidence_weight": 500.0},
)


class ConformFailed(ValueError):
    def __init__(self, revisions: list[dict[str, Any]]) -> None:
        self.revisions = revisions
        super().__init__(
            f"articulated registration failed after {len(revisions)} revisions; "
            f"diagnostics were left intact: {revisions}"
        )


def similarity_from_landmarks(source: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(target, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3 or src.shape[0] < 3:
        raise ValueError(f"landmarks must be [N>=3,3], got {src.shape} {dst.shape}")
    src_c = src.mean(axis=0)
    dst_c = dst.mean(axis=0)
    src0 = src - src_c
    dst0 = dst - dst_c
    src_rms = float(np.sqrt((src0 ** 2).sum() / len(src)))
    dst_rms = float(np.sqrt((dst0 ** 2).sum() / len(dst)))
    if src_rms <= 1e-8 or dst_rms <= 1e-8:
        raise ValueError("landmark span is degenerate")
    scale = dst_rms / src_rms
    covariance = (src0 * scale).T @ dst0
    u, _singular, vh = np.linalg.svd(covariance)
    rotation = vh.T @ u.T
    if float(np.linalg.det(rotation)) < 0:
        vh[-1] *= -1
        rotation = vh.T @ u.T
    translation = dst_c - scale * (rotation @ src_c)
    mapped = scale * (rotation @ src.T).T + translation
    residual = np.linalg.norm(mapped - dst, axis=1)
    return {
        "scale": float(scale),
        "rotation": rotation,
        "translation": translation,
        "det": float(np.linalg.det(rotation)),
        "residualMax": float(residual.max()),
        "residualMean": float(residual.mean()),
    }


def apply_similarity(points: np.ndarray, xform: dict[str, Any]) -> np.ndarray:
    return float(xform["scale"]) * (np.asarray(xform["rotation"]) @ np.asarray(points, dtype=np.float64).T).T + np.asarray(
        xform["translation"], dtype=np.float64
    )


def bbox_diagonal(points: np.ndarray) -> float:
    values = np.asarray(points, dtype=np.float64)
    return float(np.linalg.norm(values.max(axis=0) - values.min(axis=0)))


def export_error_limit(points: np.ndarray) -> float:
    return 1e-5 * max(bbox_diagonal(points), 1e-8)


def _children(parents: np.ndarray) -> list[list[int]]:
    child = [[] for _ in range(len(parents))]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            child[int(parent)].append(index)
    return child


def _bone_direction(positions: np.ndarray, parents: np.ndarray, children: list[list[int]], index: int) -> np.ndarray:
    kids = children[index]
    if kids:
        direction = positions[kids].mean(axis=0) - positions[index]
    elif int(parents[index]) >= 0:
        direction = positions[index] - positions[int(parents[index])]
    else:
        direction = np.array((0.0, 1.0, 0.0), dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-8:
        return np.array((0.0, 1.0, 0.0), dtype=np.float64)
    return direction / norm


def _rigid_map(src_pos: np.ndarray, src_dir: np.ndarray, dst_pos: np.ndarray, dst_dir: np.ndarray) -> np.ndarray:
    rotation = rotation_between(src_dir, dst_dir)
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = np.asarray(dst_pos, dtype=np.float64) - rotation @ np.asarray(src_pos, dtype=np.float64)
    return matrix


def _apply4(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return (matrix[:3, :3] @ np.asarray(points, dtype=np.float64).T).T + matrix[:3, 3]


def _lbs(vertices: np.ndarray, weights: np.ndarray, matrices: np.ndarray) -> np.ndarray:
    verts = np.asarray(vertices, dtype=np.float64)
    skin = np.asarray(weights, dtype=np.float64)
    posed = np.zeros_like(verts)
    hom = np.concatenate([verts, np.ones((len(verts), 1), dtype=np.float64)], axis=1)
    for joint in range(skin.shape[1]):
        column = skin[:, joint : joint + 1]
        if float(column.max()) <= 0.0:
            continue
        posed += column * (hom @ matrices[joint].T)[:, :3]
    return posed


def articulated_bone_matrices(
    *,
    roc_aligned_joints: np.ndarray,
    roc_parents: np.ndarray,
    roc_names: list[str],
    eagle_rest: np.ndarray,
    eagle_names: list[str],
    bone_map: dict[str, str],
) -> np.ndarray:
    roc_children = _children(roc_parents)
    eagle_index = {name: index for index, name in enumerate(eagle_names)}
    matrices = np.repeat(np.eye(4, dtype=np.float64)[None], len(roc_names), axis=0)
    eagle_pos = np.asarray(eagle_rest, dtype=np.float64)
    missing = [name for name in roc_names if name not in bone_map]
    if missing:
        raise ValueError(f"Roc bones missing from the capture binding: {missing}")
    for index, name in enumerate(roc_names):
        eagle_joint = eagle_index[bone_map[name]]
        src_dir = _bone_direction(roc_aligned_joints, roc_parents, roc_children, index)
        parent = int(roc_parents[index])
        if roc_children[index]:
            child_eagle = [eagle_index[bone_map[roc_names[child]]] for child in roc_children[index]]
            dst_dir = eagle_pos[child_eagle].mean(axis=0) - eagle_pos[eagle_joint]
        elif parent >= 0:
            dst_dir = eagle_pos[eagle_joint] - eagle_pos[eagle_index[bone_map[roc_names[parent]]]]
        else:
            dst_dir = np.array((0.0, 1.0, 0.0), dtype=np.float64)
        dest_norm = float(np.linalg.norm(dst_dir))
        if dest_norm < 1e-8:
            dst_dir = src_dir
        else:
            dst_dir = dst_dir / dest_norm
        matrices[index] = _rigid_map(
            roc_aligned_joints[index],
            src_dir,
            eagle_pos[eagle_joint],
            dst_dir,
        )
    return matrices


def rigid_feature_indices(copy: dict[str, Any]) -> np.ndarray:
    """Beak and claw vertices that must stay with the head/foot bone maps."""
    names = copy["nameIndex"]
    regions = copy["vertexRegions"]
    dense = copy["sourceDenseWeights"]
    chosen: list[int] = []
    beak = np.where(regions == "beak")[0]
    chosen.extend(int(index) for index in beak.tolist())
    for bone in FOOT_BONES:
        claws = np.where(dense[:, names[bone]] >= 0.5)[0]
        chosen.extend(int(index) for index in claws.tolist())
    if not chosen:
        return np.zeros((0,), dtype=np.int64)
    return np.unique(np.asarray(chosen, dtype=np.int64))


def carry_rigid_features(
    aligned: np.ndarray,
    posed: np.ndarray,
    copy: dict[str, Any],
    matrices: np.ndarray,
) -> np.ndarray:
    """Initializer only: beak with the head, claws with their feet, before ARAP handles."""
    out = np.asarray(posed, dtype=np.float64).copy()
    names = copy["nameIndex"]
    regions = copy["vertexRegions"]
    dense = copy["sourceDenseWeights"]
    head = names[HEAD_BONE]
    beak = regions == "beak"
    if np.any(beak):
        out[beak] = _apply4(matrices[head], aligned[beak])
    for bone in FOOT_BONES:
        column = dense[:, names[bone]]
        claws = column >= 0.5
        if np.any(claws):
            out[claws] = _apply4(matrices[names[bone]], aligned[claws])
    return out


def merge_rigid_feature_handles(
    handle_index: np.ndarray,
    handle_target: np.ndarray,
    copy: dict[str, Any],
    lbs_vertices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Keep beak/claw attachment as ARAP handles. Do not overwrite the solved mesh afterward."""
    feature = rigid_feature_indices(copy)
    if len(feature) == 0:
        return handle_index, handle_target
    present = np.isin(feature, handle_index)
    missing = feature[~present]
    if len(missing) == 0:
        return handle_index, handle_target
    lbs = np.asarray(lbs_vertices, dtype=np.float64)
    return (
        np.concatenate([handle_index, missing]),
        np.concatenate([handle_target, lbs[missing]]),
    )


def attachment_patch_handles(
    copy: dict[str, Any],
    lbs_vertices: np.ndarray,
    *,
    patch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    dense = copy["sourceDenseWeights"]
    indices: list[int] = []
    for bone in range(dense.shape[1]):
        column = dense[:, bone]
        if float(column.max()) <= 0.05:
            continue
        count = min(int(patch_size), int(np.sum(column > 0.15)))
        if count <= 0:
            indices.append(int(np.argmax(column)))
            continue
        top = np.argpartition(column, -count)[-count:]
        indices.extend(int(value) for value in top.tolist())
    reps = component_representatives(copy["componentIds"], dense)
    indices.extend(int(value) for value in reps.tolist())
    handle_index = np.unique(np.asarray(indices, dtype=np.int64))
    return handle_index, np.asarray(lbs_vertices, dtype=np.float64)[handle_index]


def _cotangent_laplacian(vertices: np.ndarray, triangles: np.ndarray) -> sparse.csr_matrix:
    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    n = len(verts)
    i_idx: list[int] = []
    j_idx: list[int] = []
    values: list[float] = []
    for a, b, c in faces:
        for src, dst, opp in ((a, b, c), (b, c, a), (c, a, b)):
            u = verts[src] - verts[opp]
            v = verts[dst] - verts[opp]
            denom = float(np.linalg.norm(np.cross(u, v)))
            if denom <= 1e-12:
                weight = 0.0
            else:
                weight = float(np.dot(u, v) / denom)
            i_idx.extend((src, dst, src, dst))
            j_idx.extend((dst, src, src, dst))
            values.extend((-weight, -weight, weight, weight))
    return sparse.coo_matrix((values, (i_idx, j_idx)), shape=(n, n)).tocsr()


def _coincidence_laplacian(groups: list[np.ndarray], vertex_count: int, weight: float) -> sparse.csr_matrix:
    i_idx: list[int] = []
    j_idx: list[int] = []
    values: list[float] = []
    for group in groups:
        if len(group) < 2:
            continue
        for src in group:
            for dst in group:
                if int(src) == int(dst):
                    continue
                i_idx.extend((int(src), int(src)))
                j_idx.extend((int(dst), int(src)))
                values.extend((-float(weight), float(weight)))
    if not i_idx:
        return sparse.csr_matrix((vertex_count, vertex_count))
    return sparse.coo_matrix((values, (i_idx, j_idx)), shape=(vertex_count, vertex_count)).tocsr()


def arap_deform(
    rest: np.ndarray,
    triangles: np.ndarray,
    *,
    initial: np.ndarray,
    handle_index: np.ndarray,
    handle_target: np.ndarray,
    coincidence_groups: list[np.ndarray] | None = None,
    coincidence_weight: float = COINCIDENCE_WEIGHT,
    iterations: int = 8,
    handle_weight: float | np.ndarray = HANDLE_SOFT,
) -> np.ndarray:
    """Sorkine-Alexa ARAP. Local rotations are estimated; handles are offset-preserving, not joint centers."""
    rest_v = np.asarray(rest, dtype=np.float64)
    posed = np.asarray(initial, dtype=np.float64).copy()
    n = len(rest_v)
    handle_index = np.asarray(handle_index, dtype=np.int64)
    handle_target = np.asarray(handle_target, dtype=np.float64)
    weights = np.broadcast_to(np.asarray(handle_weight, dtype=np.float64).reshape(-1), handle_index.shape).copy()
    if handle_index.size == 0:
        raise ValueError("ARAP requires offset-preserving handles")
    if np.allclose(handle_target, 0.0) and float(np.linalg.norm(rest_v[handle_index]).max()) > 1e-4:
        raise ValueError("refusing joint-center-like zero handles on a non-origin patch")
    faces = np.asarray(triangles, dtype=np.int64)
    neighbors: list[list[int]] = [[] for _ in range(n)]
    for a, b, c in faces:
        neighbors[int(a)].extend((int(b), int(c)))
        neighbors[int(b)].extend((int(a), int(c)))
        neighbors[int(c)].extend((int(a), int(b)))
    if coincidence_groups:
        for group in coincidence_groups:
            members = [int(value) for value in np.asarray(group).tolist()]
            for src in members:
                neighbors[src].extend(members)
    neighbors = [sorted(set(item)) for item in neighbors]
    lap = _cotangent_laplacian(rest_v, faces)
    if coincidence_groups:
        lap = lap + _coincidence_laplacian(coincidence_groups, n, float(coincidence_weight))
    eye = sparse.csr_matrix(
        (weights, (handle_index, handle_index)),
        shape=(n, n),
    )
    stay = NUMERICAL_STAY * sparse.eye(n, format="csr")
    system = lap + eye + stay
    for _ in range(max(1, int(iterations))):
        rotations = np.repeat(np.eye(3, dtype=np.float64)[None], n, axis=0)
        for index in range(n):
            nbr = neighbors[index]
            if len(nbr) < 2:
                continue
            src = rest_v[nbr] - rest_v[index]
            dst = posed[nbr] - posed[index]
            covariance = src.T @ dst
            u, _s, vh = np.linalg.svd(covariance)
            rotation = vh.T @ u.T
            if float(np.linalg.det(rotation)) < 0:
                vh[-1] *= -1
                rotation = vh.T @ u.T
            rotations[index] = rotation
        rhs = np.zeros((n, 3), dtype=np.float64)
        coo = lap.tocoo()
        for row, col, weight in zip(coo.row, coo.col, coo.data):
            if int(row) == int(col):
                continue
            mid = 0.5 * (rotations[int(row)] + rotations[int(col)])
            rhs[int(row)] += -float(weight) * (mid @ (rest_v[int(row)] - rest_v[int(col)]))
        for handle, target, weight in zip(handle_index, handle_target, weights):
            rhs[int(handle)] += float(weight) * np.asarray(target, dtype=np.float64)
        posed = np.column_stack([spsolve(system, rhs[:, axis]) for axis in range(3)])
        if not np.isfinite(posed).all():
            raise ValueError("ARAP produced non-finite vertices")
    return posed


def triangle_areas_and_normals(vertices: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tris = np.asarray(vertices, dtype=np.float64)[np.asarray(triangles, dtype=np.int64)]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    areas = np.linalg.norm(normals, axis=1)
    return areas, normals


def edge_lengths(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    tris = np.asarray(vertices, dtype=np.float64)[np.asarray(triangles, dtype=np.int64)]
    return np.concatenate(
        [
            np.linalg.norm(tris[:, 1] - tris[:, 0], axis=1),
            np.linalg.norm(tris[:, 2] - tris[:, 1], axis=1),
            np.linalg.norm(tris[:, 0] - tris[:, 2], axis=1),
        ]
    )


def triangle_distortion(rest: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> dict[str, float]:
    before = edge_lengths(rest, triangles)
    after = edge_lengths(posed, triangles)
    ratio = after / np.maximum(before, 1e-8)
    return {
        "maxEdgeRatio": float(ratio.max()),
        "medianEdgeRatio": float(np.median(ratio)),
        "p95EdgeRatio": float(np.quantile(ratio, 0.95)),
    }


def inverted_by_kabsch(rest: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """True when the triangle remains inverted after the best rigid rotation is removed.

    A world-space normal flip from a rigid rotation is not an inversion.
    """
    faces = np.asarray(triangles, dtype=np.int64)
    rest_v = np.asarray(rest, dtype=np.float64)
    posed_v = np.asarray(posed, dtype=np.float64)
    inverted = np.zeros(len(faces), dtype=bool)
    for index, tri in enumerate(faces):
        src = rest_v[tri] - rest_v[tri].mean(axis=0)
        dst = posed_v[tri] - posed_v[tri].mean(axis=0)
        covariance = src.T @ dst
        u, _s, vh = np.linalg.svd(covariance)
        rotation = vh.T @ u.T
        if float(np.linalg.det(rotation)) < 0:
            vh = vh.copy()
            vh[-1] *= -1
            rotation = vh.T @ u.T
        aligned = (rotation.T @ dst.T).T
        normal = np.cross(src[1] - src[0], src[2] - src[0])
        rest_area = float(np.dot(normal, normal))
        if rest_area < 1e-16:
            continue
        aligned_area = float(
            np.dot(normal, np.cross(aligned[1] - aligned[0], aligned[2] - aligned[0]))
        )
        inverted[index] = aligned_area < -0.01 * rest_area
    return inverted


def world_normal_flips(rest: np.ndarray, posed: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    area_before, n_before = triangle_areas_and_normals(rest, triangles)
    _area_after, n_after = triangle_areas_and_normals(posed, triangles)
    significant = area_before > 1e-10
    return ((n_before * n_after).sum(axis=1) < 0) & significant


def _segment_triangle(p0: np.ndarray, p1: np.ndarray, tri: np.ndarray) -> bool:
    direction = p1 - p0
    edge1 = tri[1] - tri[0]
    edge2 = tri[2] - tri[0]
    perp = np.cross(direction, edge2)
    det = float(np.dot(edge1, perp))
    if abs(det) < 1e-12:
        return False
    inv = 1.0 / det
    tvec = p0 - tri[0]
    u = float(np.dot(tvec, perp)) * inv
    if u < 0.0 or u > 1.0:
        return False
    qvec = np.cross(tvec, edge1)
    v = float(np.dot(direction, qvec)) * inv
    if v < 0.0 or u + v > 1.0:
        return False
    t = float(np.dot(edge2, qvec)) * inv
    return 1e-6 < t < 1.0 - 1e-6


def triangles_pierce(t1: np.ndarray, t2: np.ndarray) -> bool:
    for a, b in ((0, 1), (1, 2), (2, 0)):
        if _segment_triangle(t1[a], t1[b], t2) or _segment_triangle(t2[a], t2[b], t1):
            return True
    return False


def count_triangle_intersections(vertices: np.ndarray, triangles: np.ndarray) -> int:
    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    pts = verts[faces]
    mins = pts.min(axis=1)
    maxs = pts.max(axis=1)
    edges = np.linalg.norm(pts[:, 1] - pts[:, 0], axis=1)
    usable = edges > 1e-8
    cell = float(np.median(edges[usable])) if np.any(usable) else 0.05
    cell = max(cell, 1e-4)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    origin = mins.min(axis=0)
    for index in range(len(faces)):
        a = np.floor((mins[index] - origin) / cell).astype(np.int64)
        b = np.floor((maxs[index] - origin) / cell).astype(np.int64)
        b = a + np.minimum(b - a, 3)
        for x in range(int(a[0]), int(b[0]) + 1):
            for y in range(int(a[1]), int(b[1]) + 1):
                for z in range(int(a[2]), int(b[2]) + 1):
                    buckets.setdefault((x, y, z), []).append(index)
    seen: set[tuple[int, int]] = set()
    count = 0
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        for i_pos in range(len(ids)):
            for j_pos in range(i_pos + 1, len(ids)):
                i = ids[i_pos]
                j = ids[j_pos]
                pair = (i, j) if i < j else (j, i)
                if pair in seen:
                    continue
                seen.add(pair)
                if len({int(v) for v in faces[i].tolist()} & {int(v) for v in faces[j].tolist()}):
                    continue
                if np.any(maxs[i] + 1e-12 < mins[j]) or np.any(maxs[j] + 1e-12 < mins[i]):
                    continue
                if triangles_pierce(pts[i], pts[j]):
                    count += 1
    return count


def _centroid(vertices: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    if not np.any(mask):
        return None
    return np.asarray(vertices, dtype=np.float64)[mask].mean(axis=0)


def _safe_dist(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    return float(np.linalg.norm(a - b))


def diagnose_conform(
    *,
    original: np.ndarray,
    after: np.ndarray,
    triangles: np.ndarray,
    xform: dict[str, Any],
    eagle_rest: np.ndarray,
    eagle_names: list[str],
    copy: dict[str, Any],
    intersections_original: int | None = None,
    intersections_after: int | None = None,
) -> dict[str, Any]:
    authorized = float(xform["scale"])
    area_before, _n_before = triangle_areas_and_normals(original, triangles)
    area_after, _n_after = triangle_areas_and_normals(after, triangles)
    edges_before = edge_lengths(original, triangles)
    edges_after = edge_lengths(after, triangles)
    local_edge = edges_after / np.maximum(edges_before * authorized, 1e-8)
    local_area = area_after / np.maximum(area_before * (authorized ** 2), 1e-16)
    significant = area_before > 1e-10
    inverted = inverted_by_kabsch(original, after, triangles)
    inverted_count = int(np.sum(inverted & significant))
    world_flips = int(np.sum(world_normal_flips(original, after, triangles)))
    new_degenerate = int(
        np.sum((area_after < 1e-12) & (area_before * (authorized ** 2) > 1e-10))
    )
    regions = copy["vertexRegions"]
    attachments = {}
    for name, src, dst in (
        ("beak_to_head", "beak", "neck_head"),
        ("tail_to_torso", "tail", "torso"),
        ("wing_left_to_torso", "wing_left", "torso"),
        ("wing_right_to_torso", "wing_right", "torso"),
        ("leg_left_to_torso", "leg_left", "torso"),
        ("leg_right_to_torso", "leg_right", "torso"),
    ):
        before = _safe_dist(_centroid(original, regions == src), _centroid(original, regions == dst))
        after_d = _safe_dist(_centroid(after, regions == src), _centroid(after, regions == dst))
        ratio = None if before is None or after_d is None or before < 1e-8 else after_d / (before * authorized)
        attachments[name] = {"before": before, "after": after_d, "scaleNormalizedRatio": ratio}
    attachment_ok = True
    for item in attachments.values():
        ratio = item["scaleNormalizedRatio"]
        if ratio is None:
            continue
        if ratio < ATTACHMENT_RATIO_MIN or ratio > ATTACHMENT_RATIO_MAX:
            attachment_ok = False
    roc_index = copy["nameIndex"]
    dense = copy["sourceDenseWeights"]
    wing_l = after[np.argmax(dense[:, roc_index["Bone_022"]])]
    wing_r = after[np.argmax(dense[:, roc_index["Bone_019"]])]
    name_index = {name: index for index, name in enumerate(eagle_names)}
    collapsed = float(np.linalg.norm(wing_l - wing_r)) < 0.15 * float(
        np.linalg.norm(eagle_rest[name_index["BN_Wing_L_01"]] - eagle_rest[name_index["BN_Wing_R_01"]])
    )
    left_ok = float(wing_l[0] - wing_r[0]) > 0.0
    mirrored = float(xform["det"]) < 0
    new_intersections = None
    if intersections_original is not None and intersections_after is not None:
        new_intersections = int(max(0, intersections_after - intersections_original))
    p95 = float(np.quantile(local_edge, 0.95))
    p05 = float(np.quantile(local_edge, 0.05))
    max_edge = float(local_edge.max())
    beak_attached = True
    beak_mask = regions == "beak"
    if np.any(beak_mask):
        beak_ratio = attachments["beak_to_head"]["scaleNormalizedRatio"]
        beak_attached = beak_ratio is not None and ATTACHMENT_RATIO_MIN <= beak_ratio <= ATTACHMENT_RATIO_MAX
    ok = bool(
        not mirrored
        and not collapsed
        and left_ok
        and inverted_count == 0
        and new_degenerate <= NEW_DEGENERATE_LIMIT
        and attachment_ok
        and beak_attached
        and p95 <= LOCAL_EDGE_P95_LIMIT
        and p05 >= LOCAL_EDGE_P05_MIN
        and max_edge <= LOCAL_EDGE_MAX_LIMIT
    )
    return {
        "globalDet": float(xform["det"]),
        "authorizedScale": authorized,
        "mirroredRegistration": mirrored,
        "invertedTriangles": inverted_count,
        "worldNormalFlipsNotInversion": world_flips,
        "newDegenerateTriangles": new_degenerate,
        "maxEdgeStretchRaw": float((edges_after / np.maximum(edges_before, 1e-8)).max()),
        "maxEdgeStretchLocal": max_edge,
        "p95EdgeStretchLocal": p95,
        "p05EdgeStretchLocal": p05,
        "medianEdgeStretchLocal": float(np.median(local_edge)),
        "p95AreaStretchLocal": float(np.quantile(local_area[significant], 0.95)) if np.any(significant) else 1.0,
        "collapsedWingRoots": collapsed,
        "leftWingPlusX": left_ok,
        "beakAttached": beak_attached,
        "attachments": attachments,
        "intersectionsOriginal": intersections_original,
        "intersectionsAfter": intersections_after,
        "newIntersections": new_intersections,
        "componentCount": int(copy["componentCount"]),
        "landmarkResidualMax": float(xform["residualMax"]),
        "measuredAgainst": "original_mesh_with_authorized_global_scale",
        "ok": ok,
    }


def _one_revision(
    copy: dict[str, Any],
    *,
    aligned: np.ndarray,
    aligned_joints: np.ndarray,
    xform: dict[str, Any],
    eagle_rest: np.ndarray,
    eagle_names: list[str],
    solver: dict[str, Any],
    intersections_original: int,
) -> dict[str, Any]:
    bone_map = copy.get("boneMap") or roc_to_eagle_bones()
    matrices = articulated_bone_matrices(
        roc_aligned_joints=aligned_joints,
        roc_parents=copy["parents"],
        roc_names=copy["names"],
        eagle_rest=eagle_rest,
        eagle_names=eagle_names,
        bone_map=bone_map,
    )
    lbs = _lbs(aligned, copy["sourceDenseWeights"], matrices)
    lbs = carry_rigid_features(aligned, lbs, copy, matrices)
    lbs = coalesce_coincidences(lbs, copy["coincidenceGroups"])
    handles, targets = attachment_patch_handles(copy, lbs, patch_size=int(solver["patch_size"]))
    handles, targets = merge_rigid_feature_handles(handles, targets, copy, lbs)
    deformed = arap_deform(
        aligned,
        copy["triangles"],
        initial=lbs,
        handle_index=handles,
        handle_target=targets,
        coincidence_groups=copy["coincidenceGroups"],
        coincidence_weight=float(solver["coincidence_weight"]),
        iterations=int(solver["arap_iterations"]),
    )
    deformed = coalesce_coincidences(deformed, copy["coincidenceGroups"])
    report = diagnose_conform(
        original=copy["vertices"],
        after=deformed,
        triangles=copy["triangles"],
        xform=xform,
        eagle_rest=eagle_rest,
        eagle_names=eagle_names,
        copy=copy,
        intersections_original=intersections_original,
        intersections_after=None,
    )
    report["solver"] = solver["name"]
    report["handleCount"] = int(len(handles))
    report["lbsToArapMax"] = float(np.linalg.norm(deformed - lbs, axis=1).max())
    return {
        "vertices": deformed,
        "lbsVertices": lbs,
        "diagnostics": report,
        "handleCount": int(len(handles)),
        "solver": solver["name"],
        "boneMatrices": matrices,
    }


def align_roc_global_to_eagle(
    copy: dict[str, Any],
    *,
    eagle_offsets: np.ndarray,
    eagle_parents: np.ndarray,
    eagle_names: list[str],
) -> dict[str, Any]:
    """Landmark similarity only — no articulated ARAP conform.

    Use when the surface topology/pose is too far from the SmartRig reference for
    full conform but should still share Eagle bind scale/orientation for weight transfer.
    """
    eagle_rest = compute_rest_joints(eagle_offsets, eagle_parents)
    eagle_index = {name: index for index, name in enumerate(eagle_names)}
    roc_index = copy["nameIndex"]
    src = []
    dst = []
    for roc_bone, eagle_joint in ROC_TO_EAGLE_LANDMARKS:
        src.append(copy["restWorld"][roc_index[roc_bone]])
        dst.append(eagle_rest[eagle_index[eagle_joint]])
    xform = similarity_from_landmarks(np.stack(src), np.stack(dst))
    if float(xform["det"]) < 0:
        raise ValueError("global similarity is a reflection")
    aligned = apply_similarity(copy["vertices"], xform)
    return {
        "vertices": aligned,
        "globallyAligned": aligned,
        "lbsInitialized": aligned,
        "similarity": {
            "scale": xform["scale"],
            "rotation": np.asarray(xform["rotation"]).tolist(),
            "translation": np.asarray(xform["translation"]).tolist(),
            "det": xform["det"],
            "residualMax": xform["residualMax"],
        },
        "diagnostics": {
            "ok": True,
            "mode": "global_similarity_only",
            "landmarkResidualMax": float(xform["residualMax"]),
            "vertexCount": int(len(aligned)),
        },
        "revisions": [],
        "handleCount": 0,
        "solver": "global_similarity_only",
        "eagleRestJoints": eagle_rest,
    }


def conform_roc_to_eagle(
    copy: dict[str, Any],
    *,
    eagle_offsets: np.ndarray,
    eagle_parents: np.ndarray,
    eagle_names: list[str],
) -> dict[str, Any]:
    eagle_rest = compute_rest_joints(eagle_offsets, eagle_parents)
    eagle_index = {name: index for index, name in enumerate(eagle_names)}
    roc_index = copy["nameIndex"]
    src = []
    dst = []
    for roc_bone, eagle_joint in ROC_TO_EAGLE_LANDMARKS:
        src.append(copy["restWorld"][roc_index[roc_bone]])
        dst.append(eagle_rest[eagle_index[eagle_joint]])
    xform = similarity_from_landmarks(np.stack(src), np.stack(dst))
    if float(xform["det"]) < 0:
        raise ValueError("global similarity is a reflection")
    aligned = apply_similarity(copy["vertices"], xform)
    aligned_joints = apply_similarity(copy["restWorld"], xform)
    intersections_original = count_triangle_intersections(copy["vertices"], copy["triangles"])
    revisions: list[dict[str, Any]] = []
    chosen = None
    for revision, solver in enumerate(REVISION_SOLVERS[:MAX_REVISIONS]):
        result = _one_revision(
            copy,
            aligned=aligned,
            aligned_joints=aligned_joints,
            xform=xform,
            eagle_rest=eagle_rest,
            eagle_names=eagle_names,
            solver=solver,
            intersections_original=intersections_original,
        )
        entry = {"revision": revision, **result["diagnostics"]}
        revisions.append(entry)
        if result["diagnostics"]["ok"]:
            chosen = result
            break
    if chosen is None:
        raise ConformFailed(revisions)
    intersections_after = count_triangle_intersections(chosen["vertices"], copy["triangles"])
    chosen["diagnostics"]["intersectionsAfter"] = intersections_after
    chosen["diagnostics"]["newIntersections"] = int(max(0, intersections_after - intersections_original))
    return {
        "vertices": chosen["vertices"],
        "globallyAligned": aligned,
        "lbsInitialized": chosen["lbsVertices"],
        "similarityPosed": aligned,
        "similarity": {
            "scale": xform["scale"],
            "rotation": np.asarray(xform["rotation"]).tolist(),
            "translation": np.asarray(xform["translation"]).tolist(),
            "det": xform["det"],
            "residualMax": xform["residualMax"],
        },
        "diagnostics": chosen["diagnostics"],
        "revisions": revisions,
        "handleCount": chosen["handleCount"],
        "eagleRestJoints": eagle_rest,
        "solver": chosen["solver"],
    }
