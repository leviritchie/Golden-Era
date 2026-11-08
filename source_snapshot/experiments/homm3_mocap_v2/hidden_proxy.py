"""Hidden donor registration and barycentric weight transfer. The visible mesh is never deformed."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from barycentric_transfer import (
    UnmatchedCorrespondenceError,
    _closest_points_on_triangles,
    _triangle_allowed,
)
from conform_roc import arap_deform
from donor_eagle import bind_world_matrices, inverse_bind_matrices, skin_dense
from shape_donor import region_for_joint

MAX_REVISIONS = 3
CLOSE_FACTOR = 2.5
ABSOLUTE_CLOSE_FRACTION = 0.12
NORMAL_COSINE_MIN = 0.1
ON_SURFACE_FACTOR = 1e-4
SHEET_FACTOR = 0.08
CANDIDATE_K = 48
NEIGHBOR_BLEND = 0.25
UV_NORMAL_COSINE = 0.5


def allowed_regions_for(target_region: str) -> set[str]:
    region = str(target_region)
    if region == "beak":
        return {"beak"}
    if region == "neck_head":
        return {"neck_head"}
    if region == "torso":
        return {"torso", "pelvis_aux"}
    if region == "pelvis_aux":
        return {"torso", "pelvis_aux"}
    if region.startswith(("wing_", "arm_", "leg_")):
        return {region}
    return {region}


def donor_vertex_regions(weights: np.ndarray, names: list[str], region_joints: dict[str, tuple[str, ...]]) -> np.ndarray:
    argmax = np.argmax(np.asarray(weights, dtype=np.float64), axis=1)
    return np.array([region_for_joint(names[int(index)], region_joints) for index in argmax], dtype=object)


def vertex_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    tris = np.asarray(vertices, dtype=np.float64)[np.asarray(triangles, dtype=np.int64)]
    face = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.where(lengths < 1e-8, 1.0, lengths)


def _triangle_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    tris = np.asarray(vertices, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.where(lengths < 1e-8, 1.0, lengths)


def _rigid_region_set(profile: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    return {str(item["region"]): tuple(item["donorJoints"]) for item in profile.get("rigidAttachments", ())}


def assign_rigid_weights(
    *,
    vertex_count: int,
    joint_count: int,
    names: list[str],
    regions: np.ndarray,
    profile: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    weights = np.zeros((vertex_count, joint_count), dtype=np.float64)
    assigned = np.zeros(vertex_count, dtype=bool)
    name_index = {name: index for index, name in enumerate(names)}
    for item in profile.get("rigidAttachments", ()):
        region = str(item["region"])
        mask = np.asarray(regions) == region
        if not np.any(mask):
            continue
        joints = [name_index[name] for name in item["donorJoints"]]
        share = 1.0 / float(len(joints))
        for joint in joints:
            weights[mask, joint] = share
        assigned[mask] = True
    return weights, assigned


def _best_match_on_faces(
    point: np.ndarray,
    normal: np.ndarray,
    donor_vertices: np.ndarray,
    donor_weights: np.ndarray,
    faces: np.ndarray,
    tri_normals: np.ndarray,
    *,
    threshold: float,
    on_surface: float,
) -> tuple[np.ndarray | None, dict[str, Any] | None]:
    if len(faces) == 0:
        return None, {"reason": "no_donor_triangle_in_region"}
    closest, bary = _closest_points_on_triangles(
        point,
        donor_vertices[faces[:, 0]],
        donor_vertices[faces[:, 1]],
        donor_vertices[faces[:, 2]],
    )
    dist = np.linalg.norm(closest - point, axis=1)
    cosine = tri_normals @ normal
    oriented = (dist <= threshold) & (cosine >= 0.0)
    sheet = (dist <= on_surface) & (np.abs(cosine) >= NORMAL_COSINE_MIN)
    accept = oriented | sheet
    if not np.any(accept):
        nearest = int(np.argmin(dist))
        if float(dist[nearest]) > threshold:
            return None, {
                "reason": "outside_region_surface",
                "distance": float(dist[nearest]),
                "threshold": threshold,
            }
        return None, {
            "reason": "orientation_rejected",
            "cosine": float(cosine[nearest]),
            "distance": float(dist[nearest]),
        }
    chosen = int(np.argmin(np.where(accept, dist, np.inf)))
    corners = faces[chosen]
    weights = (
        bary[chosen, 0] * donor_weights[corners[0]]
        + bary[chosen, 1] * donor_weights[corners[1]]
        + bary[chosen, 2] * donor_weights[corners[2]]
    )
    return weights, None


def transfer_through_proxy(
    *,
    target_vertices: np.ndarray,
    target_regions: np.ndarray,
    target_normals: np.ndarray,
    target_triangles: np.ndarray,
    donor_vertices: np.ndarray,
    donor_faces: np.ndarray,
    donor_weights: np.ndarray,
    donor_names: list[str],
    region_joints: dict[str, tuple[str, ...]],
    skip: np.ndarray,
) -> dict[str, Any]:
    donor_regions = donor_vertex_regions(donor_weights, donor_names, region_joints)
    transferred = np.zeros((len(target_vertices), donor_weights.shape[1]), dtype=np.float64)
    unmatched: list[dict[str, Any]] = []
    donor_tri_normals = _triangle_normals(donor_vertices, donor_faces)
    centroids = donor_vertices[donor_faces].mean(axis=1)
    region_thresholds: dict[str, float] = {}
    region_sheets: dict[str, float] = {}
    region_faces: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    bbox = float(np.linalg.norm(target_vertices.max(0) - target_vertices.min(0)))
    for region in sorted(set(target_regions.tolist())):
        roc_idx = np.where((target_regions == region) & (~skip))[0]
        if roc_idx.size == 0:
            continue
        allowed = allowed_regions_for(str(region))
        keep = _triangle_allowed(donor_regions, donor_faces, allowed)
        if not np.any(keep):
            for index in roc_idx:
                unmatched.append({"vertex": int(index), "region": str(region), "reason": "no_donor_triangle_in_region"})
            continue
        faces = donor_faces[keep]
        tri_normals = donor_tri_normals[keep]
        region_faces[str(region)] = (faces, tri_normals)
        tree = cKDTree(centroids[keep])
        query = target_vertices[roc_idx]
        knn = min(CANDIDATE_K, len(faces))
        _dist, cand = tree.query(query, k=knn)
        cand = np.atleast_2d(cand)
        nn = np.linalg.norm(query[:, None, :] - centroids[keep][cand], axis=2)
        median = float(np.median(nn.min(axis=1)))
        span = max(bbox, 1e-8)
        if bbox >= 1e-4:
            threshold = ABSOLUTE_CLOSE_FRACTION * bbox
            on_surface = SHEET_FACTOR * bbox
        else:
            threshold = max(CLOSE_FACTOR * median, ON_SURFACE_FACTOR * span)
            on_surface = ON_SURFACE_FACTOR * span
        region_thresholds[str(region)] = threshold
        region_sheets[str(region)] = on_surface
        for row, index in enumerate(roc_idx):
            local_ids = np.unique(cand[row])
            weights, error = _best_match_on_faces(
                target_vertices[index],
                target_normals[index],
                donor_vertices,
                donor_weights,
                faces[local_ids],
                tri_normals[local_ids],
                threshold=threshold,
                on_surface=on_surface,
            )
            if weights is None:
                unmatched.append({"vertex": int(index), "region": str(region), **(error or {})})
                continue
            transferred[index] = weights
    still: list[dict[str, Any]] = []
    for item in unmatched:
        region = str(item["region"])
        if region not in region_faces:
            still.append(item)
            continue
        faces, tri_normals = region_faces[region]
        weights, error = _best_match_on_faces(
            target_vertices[int(item["vertex"])],
            target_normals[int(item["vertex"])],
            donor_vertices,
            donor_weights,
            faces,
            tri_normals,
            threshold=float(region_thresholds[region]),
            on_surface=float(region_sheets[region]),
        )
        if weights is None:
            still.append({"vertex": int(item["vertex"]), "region": region, **(error or {})})
            continue
        transferred[int(item["vertex"])] = weights
    if still:
        raise UnmatchedCorrespondenceError(still)
    transferred = _regularize(transferred, target_regions, target_triangles, donor_names, region_joints, skip)
    transferred = _unify_uv_duplicates(transferred, target_vertices, target_normals, target_regions, skip)
    if not np.isfinite(transferred).all() or np.any(transferred < -1e-8):
        raise ValueError("transferred weights are not finite nonnegative")
    active = ~skip
    row = transferred[active].sum(axis=1)
    if np.any(row < 1e-6):
        raise ValueError("transferred weights leave non-rigid vertices uncovered")
    transferred[active] = transferred[active] / row[:, None]
    return {
        "weights": transferred,
        "threshold": region_thresholds,
        "unmatchedCount": 0,
        "maxInfluencesPerVertex": int((transferred > 1e-6).sum(axis=1).max()),
    }


def _regularize(
    weights: np.ndarray,
    regions: np.ndarray,
    triangles: np.ndarray,
    names: list[str],
    region_joints: dict[str, tuple[str, ...]],
    skip: np.ndarray,
) -> np.ndarray:
    out = np.asarray(weights, dtype=np.float64).copy()
    name_index = {name: index for index, name in enumerate(names)}
    blended = out.copy()
    counts = np.zeros(len(out), dtype=np.float64)
    for a, b, c in np.asarray(triangles, dtype=np.int64):
        for src, dst in ((a, b), (b, c), (c, a)):
            if skip[int(src)] or skip[int(dst)]:
                continue
            if regions[int(src)] != regions[int(dst)]:
                continue
            blended[int(src)] += NEIGHBOR_BLEND * out[int(dst)]
            counts[int(src)] += NEIGHBOR_BLEND
    denom = 1.0 + counts
    out = blended / denom[:, None]
    for region in sorted(set(regions.tolist())):
        mask = (regions == region) & (~skip)
        if not np.any(mask):
            continue
        allowed = allowed_regions_for(str(region))
        columns = [
            name_index[name]
            for group, joints in region_joints.items()
            if group in allowed
            for name in joints
        ]
        keep = np.zeros_like(out[mask])
        keep[:, columns] = out[mask][:, columns]
        out[mask] = keep
    return out


def _unify_uv_duplicates(
    weights: np.ndarray,
    vertices: np.ndarray,
    normals: np.ndarray,
    regions: np.ndarray,
    skip: np.ndarray,
) -> np.ndarray:
    """Same rest position, region, and facing: UV-split copies of one sheet share weights."""
    out = np.asarray(weights, dtype=np.float64).copy()
    rounded = np.round(np.asarray(vertices, dtype=np.float64), 6)
    buckets: dict[tuple, list[int]] = {}
    for index, point in enumerate(map(tuple, rounded)):
        if skip[index]:
            continue
        buckets.setdefault(point, []).append(index)
    for group in buckets.values():
        if len(group) < 2:
            continue
        arr = np.asarray(group, dtype=np.int64)
        used = np.zeros(len(arr), dtype=bool)
        for start in range(len(arr)):
            if used[start]:
                continue
            cluster = [start]
            used[start] = True
            for other in range(start + 1, len(arr)):
                if used[other]:
                    continue
                if str(regions[arr[start]]) != str(regions[arr[other]]):
                    continue
                if float(np.dot(normals[arr[start]], normals[arr[other]])) < UV_NORMAL_COSINE:
                    continue
                used[other] = True
                cluster.append(other)
            if len(cluster) < 2:
                continue
            idx = arr[cluster]
            mean = out[idx].mean(axis=0)
            total = float(mean.sum())
            if total > 1e-8:
                out[idx] = mean / total
    return out


def _region_constrained_handles(
    *,
    lbs: np.ndarray,
    posed: np.ndarray,
    donor_regions: np.ndarray,
    target_vertices: np.ndarray,
    target_regions: np.ndarray,
    unmatched: list[dict[str, Any]],
    extra_weight: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    problem = {str(item["region"]) for item in unmatched}
    problem_allowed: set[str] = set()
    for region in problem:
        problem_allowed |= allowed_regions_for(region)
    handle_index: list[int] = []
    handle_target: list[np.ndarray] = []
    handle_weight: list[float] = []
    stay = np.array([str(region) not in problem_allowed for region in donor_regions], dtype=bool)
    stay_idx = np.where(stay)[0]
    handle_index.extend(int(index) for index in stay_idx)
    handle_target.extend(lbs[stay_idx])
    handle_weight.extend([1.0e4] * len(stay_idx))
    for region in sorted(problem):
        allowed = allowed_regions_for(region)
        donor_idx = np.where(np.isin(donor_regions, list(allowed)))[0]
        target_idx = np.where(np.isin(target_regions, list(allowed)))[0]
        if donor_idx.size == 0 or target_idx.size == 0:
            continue
        tree = cKDTree(target_vertices[target_idx])
        _dist, nn = tree.query(posed[donor_idx], k=1)
        handle_index.extend(int(index) for index in donor_idx)
        handle_target.extend(target_vertices[target_idx][np.atleast_1d(nn)])
        handle_weight.extend([40.0] * len(donor_idx))
    extra_idx, extra_tgt = _unique_extra_handles(
        posed,
        donor_regions,
        unmatched,
        target_vertices,
        target_regions,
    )
    handle_index.extend(int(index) for index in extra_idx)
    handle_target.extend(extra_tgt)
    handle_weight.extend([float(extra_weight)] * len(extra_idx))
    if not handle_index:
        raise UnmatchedCorrespondenceError(unmatched)
    return (
        np.asarray(handle_index, dtype=np.int64),
        np.asarray(handle_target, dtype=np.float64),
        np.asarray(handle_weight, dtype=np.float64),
    )


def _unique_extra_handles(
    posed: np.ndarray,
    donor_regions: np.ndarray,
    unmatched: list[dict[str, Any]],
    target_vertices: np.ndarray,
    target_regions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    trees: dict[tuple[str, ...], cKDTree] = {}
    index_maps: dict[tuple[str, ...], np.ndarray] = {}
    buckets: dict[int, tuple[float, np.ndarray]] = {}
    for item in unmatched:
        vertex = int(item["vertex"])
        allowed = tuple(sorted(allowed_regions_for(str(target_regions[vertex]))))
        if allowed not in trees:
            keep = np.isin(donor_regions, list(allowed))
            if not np.any(keep):
                continue
            mapped = np.where(keep)[0]
            trees[allowed] = cKDTree(posed[mapped])
            index_maps[allowed] = mapped
        if allowed not in trees:
            continue
        dist, nn = trees[allowed].query(target_vertices[vertex], k=1)
        donor_index = int(index_maps[allowed][int(nn)])
        current = buckets.get(donor_index)
        if current is None or float(dist) > current[0]:
            buckets[donor_index] = (float(dist), np.asarray(target_vertices[vertex], dtype=np.float64))
    if not buckets:
        raise UnmatchedCorrespondenceError(unmatched)
    extra_idx = np.asarray(list(buckets.keys()), dtype=np.int64)
    extra_tgt = np.stack([item[1] for item in buckets.values()])
    return extra_idx, extra_tgt


def register_hidden_proxy(
    *,
    donor_vertices: np.ndarray,
    donor_faces: np.ndarray,
    donor_weights: np.ndarray,
    donor_names: list[str],
    donor_offsets: np.ndarray,
    donor_parents: np.ndarray,
    fitted_offsets: np.ndarray,
    target_vertices: np.ndarray,
    target_faces: np.ndarray,
    target_regions: np.ndarray,
    region_joints: dict[str, tuple[str, ...]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    donor_bind = bind_world_matrices(donor_offsets, donor_parents)
    fitted_bind = bind_world_matrices(fitted_offsets, donor_parents)
    ibm = inverse_bind_matrices(donor_bind)
    lbs = skin_dense(donor_vertices, donor_weights, fitted_bind, ibm)
    donor_regions = donor_vertex_regions(donor_weights, donor_names, region_joints)
    target_normals = vertex_normals(target_vertices, target_faces)
    rigid_weights, skip = assign_rigid_weights(
        vertex_count=len(target_vertices),
        joint_count=len(donor_names),
        names=donor_names,
        regions=target_regions,
        profile=profile,
    )
    posed = lbs.copy()
    revisions: list[dict[str, Any]] = []
    last_error: UnmatchedCorrespondenceError | None = None
    transferred = None
    extra_weight = float(profile.get("proxyExtraHandleWeight") or 1.0e4)
    for revision in range(MAX_REVISIONS):
        try:
            transferred = transfer_through_proxy(
                target_vertices=target_vertices,
                target_regions=target_regions,
                target_normals=target_normals,
                target_triangles=target_faces,
                donor_vertices=posed,
                donor_faces=donor_faces,
                donor_weights=donor_weights,
                donor_names=donor_names,
                region_joints=region_joints,
                skip=skip,
            )
            last_error = None
            revisions.append(
                {
                    "revision": revision,
                    "ok": True,
                    "handles": 0 if revision == 0 else None,
                    "usedArticulatedInitialization": True,
                    "shrinkWrapAllVertices": False,
                    "handleWeight": 0.0 if revision == 0 else extra_weight,
                }
            )
            break
        except UnmatchedCorrespondenceError as exc:
            last_error = exc
            revisions.append(
                {
                    "revision": revision,
                    "ok": False,
                    "unmatched": int(len(exc.unmatched)),
                    "reasons": sorted({item["reason"] for item in exc.unmatched}),
                    "shrinkWrapAllVertices": False,
                }
            )
            if revision >= MAX_REVISIONS - 1:
                break
            handle_index, handle_target, handle_weight = _region_constrained_handles(
                lbs=lbs,
                posed=posed,
                donor_regions=donor_regions,
                target_vertices=target_vertices,
                target_regions=target_regions,
                unmatched=exc.unmatched,
                extra_weight=extra_weight,
            )
            posed = arap_deform(
                lbs,
                donor_faces,
                initial=posed,
                handle_index=handle_index,
                handle_target=handle_target,
                iterations=8 + 6 * (revision + 1),
                handle_weight=handle_weight,
            )
            revisions[-1]["handles"] = int(len(handle_index))
            revisions[-1]["handleWeight"] = extra_weight
    if transferred is None or last_error is not None:
        raise UnmatchedCorrespondenceError(last_error.unmatched if last_error else [])
    weights = np.asarray(transferred["weights"], dtype=np.float64)
    weights[skip] = rigid_weights[skip]
    row = weights.sum(axis=1)
    if np.any(row < 1e-6):
        raise ValueError("combined weights leave vertices uncovered")
    weights = weights / row[:, None]
    return {
        "weights": weights,
        "hiddenVertices": posed,
        "articulatedVertices": lbs,
        "revisions": revisions,
        "revisionCount": int(len(revisions)),
        "rigidVertexCount": int(skip.sum()),
        "transfer": {key: value for key, value in transferred.items() if key != "weights"},
        "hiddenProxyNotExported": True,
        "shrinkWrapAllVertices": False,
    }
