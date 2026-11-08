"""Region-restricted barycentric weight transfer from the Eagle donor surface."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from donor_eagle import REGION_JOINTS, region_for_joint

CLOSE_FACTOR = 2.5


class UnmatchedCorrespondenceError(ValueError):
    def __init__(self, unmatched: list[dict[str, Any]]) -> None:
        self.unmatched = unmatched
        preview = unmatched[:5]
        super().__init__(
            f"{len(unmatched)} Roc vertices have no region-restricted donor correspondence; "
            f"registration must be refined. First: {preview}"
        )


def donor_vertex_regions(weights: np.ndarray, names: list[str]) -> np.ndarray:
    argmax = np.argmax(np.asarray(weights, dtype=np.float64), axis=1)
    return np.array([region_for_joint(names[int(index)]) for index in argmax], dtype=object)


def _triangle_allowed(regions: np.ndarray, faces: np.ndarray, allowed: set[str]) -> np.ndarray:
    a = regions[faces[:, 0]]
    b = regions[faces[:, 1]]
    c = regions[faces[:, 2]]
    keep = np.array(
        [ra in allowed and rb in allowed and rc in allowed for ra, rb, rc in zip(a, b, c)],
        dtype=bool,
    )
    return keep


def _closest_on_triangles(
    point: np.ndarray,
    vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[int, np.ndarray, float]:
    """Closest point on each candidate triangle (Ericson), then the nearest triangle."""
    pts = np.asarray(point, dtype=np.float64).reshape(3)
    tris = np.asarray(vertices, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    a = tris[:, 0]
    b = tris[:, 1]
    c = tris[:, 2]
    closest, bary = _closest_points_on_triangles(pts, a, b, c)
    dist = np.linalg.norm(closest - pts.reshape(1, 3), axis=1)
    index = int(np.argmin(dist))
    return index, bary[index], float(dist[index])


def _closest_points_on_triangles(
    point: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(point, dtype=np.float64).reshape(1, 3)
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = (ab * ap).sum(axis=1)
    d2 = (ac * ap).sum(axis=1)
    bp = p - b
    d3 = (ab * bp).sum(axis=1)
    d4 = (ac * bp).sum(axis=1)
    cp = p - c
    d5 = (ab * cp).sum(axis=1)
    d6 = (ac * cp).sum(axis=1)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    closest = np.empty_like(a)
    bary = np.empty((len(a), 3), dtype=np.float64)
    assigned = np.zeros(len(a), dtype=bool)

    def take(mask: np.ndarray, points: np.ndarray, u: np.ndarray, v: np.ndarray, w: np.ndarray) -> None:
        use = mask & ~assigned
        if not np.any(use):
            return
        closest[use] = points[use]
        bary[use, 0] = u[use]
        bary[use, 1] = v[use]
        bary[use, 2] = w[use]
        assigned[use] = True

    ones = np.ones(len(a), dtype=np.float64)
    zeros = np.zeros(len(a), dtype=np.float64)
    take((d1 <= 0.0) & (d2 <= 0.0), a, ones, zeros, zeros)
    take((d3 >= 0.0) & (d4 <= d3), b, zeros, ones, zeros)
    take((d6 >= 0.0) & (d5 <= d6), c, zeros, zeros, ones)
    v_ab = d1 / np.maximum(d1 - d3, 1e-12)
    take((vc <= 0.0) & (d1 >= 0.0) & (d3 <= 0.0), a + v_ab[:, None] * ab, 1.0 - v_ab, v_ab, zeros)
    w_ac = d2 / np.maximum(d2 - d6, 1e-12)
    take((vb <= 0.0) & (d2 >= 0.0) & (d6 <= 0.0), a + w_ac[:, None] * ac, 1.0 - w_ac, zeros, w_ac)
    w_bc = (d4 - d3) / np.maximum((d4 - d3) + (d5 - d6), 1e-12)
    take(
        (va <= 0.0) & ((d4 - d3) >= 0.0) & ((d5 - d6) >= 0.0),
        b + w_bc[:, None] * (c - b),
        zeros,
        1.0 - w_bc,
        w_bc,
    )
    denom = np.maximum(va + vb + vc, 1e-12)
    v_face = vb / denom
    w_face = vc / denom
    take(~assigned, a + ab * v_face[:, None] + ac * w_face[:, None], 1.0 - v_face - w_face, v_face, w_face)
    return closest, bary


def opposite_region(region: str) -> str | None:
    if region == "wing_left":
        return "wing_right"
    if region == "wing_right":
        return "wing_left"
    if region == "leg_left":
        return "leg_right"
    if region == "leg_right":
        return "leg_left"
    return None


def allowed_regions_for(roc_region: str) -> set[str]:
    if roc_region == "beak":
        return {"beak", "neck_head"}
    if roc_region.startswith("wing_"):
        return {roc_region}
    if roc_region.startswith("leg_"):
        return {roc_region}
    if roc_region == "tail":
        return {"tail"}
    if roc_region == "neck_head":
        return {"neck_head", "beak"}
    if roc_region == "torso":
        return {"torso", "neck_head"}
    return {"torso"}


def transfer_weights(
    *,
    roc_vertices: np.ndarray,
    roc_regions: np.ndarray,
    donor_vertices: np.ndarray,
    donor_faces: np.ndarray,
    donor_weights: np.ndarray,
    donor_names: list[str],
) -> dict[str, Any]:
    donor_regions = donor_vertex_regions(donor_weights, donor_names)
    transferred = np.zeros((len(roc_vertices), donor_weights.shape[1]), dtype=np.float64)
    unmatched: list[dict[str, Any]] = []
    centroids = donor_vertices[donor_faces].mean(axis=1)
    region_thresholds: dict[str, float] = {}
    for region in sorted(set(roc_regions.tolist())):
        query_region = "neck_head" if str(region) == "beak" else str(region)
        allowed = allowed_regions_for(query_region)
        keep = _triangle_allowed(donor_regions, donor_faces, allowed)
        roc_idx = np.where(roc_regions == region)[0]
        if roc_idx.size == 0:
            continue
        if not np.any(keep):
            for index in roc_idx:
                unmatched.append({"vertex": int(index), "region": str(region), "reason": "no_donor_triangle_in_region"})
            continue
        span_idx = roc_idx
        if str(region) in {"beak", "neck_head"}:
            span_idx = np.where((roc_regions == "beak") | (roc_regions == "neck_head"))[0]
        donor_span = float(np.linalg.norm(donor_vertices[donor_faces[keep]].reshape(-1, 3).max(0) - donor_vertices[donor_faces[keep]].reshape(-1, 3).min(0)))
        roc_span = float(np.linalg.norm(roc_vertices[span_idx].max(0) - roc_vertices[span_idx].min(0)))
        threshold = 1.05 * max(donor_span, roc_span, 1e-8)
        region_thresholds[str(region)] = threshold
        faces = donor_faces[keep]
        tree = cKDTree(centroids[keep])
        k_allowed = min(96, len(faces))
        _, cand = tree.query(roc_vertices[roc_idx], k=k_allowed)
        cand = np.atleast_2d(cand)
        for row, index in enumerate(roc_idx):
            local_faces = faces[np.unique(cand[row])]
            tri_index, bary, distance = _closest_on_triangles(
                roc_vertices[index], donor_vertices, local_faces
            )
            if distance > threshold:
                unmatched.append(
                    {
                        "vertex": int(index),
                        "region": str(region),
                        "reason": "outside_region_surface",
                        "distance": distance,
                        "threshold": threshold,
                    }
                )
                continue
            corners = local_faces[tri_index]
            transferred[index] = (
                bary[0] * donor_weights[corners[0]]
                + bary[1] * donor_weights[corners[1]]
                + bary[2] * donor_weights[corners[2]]
            )
    if unmatched:
        raise UnmatchedCorrespondenceError(unmatched)
    transferred = _regularize(transferred, roc_regions, donor_names)
    if not np.isfinite(transferred).all() or np.any(transferred < -1e-8):
        raise ValueError("transferred weights are not finite nonnegative")
    row = transferred.sum(axis=1)
    if np.any(row < 1e-6):
        raise ValueError("transferred weights leave vertices uncovered")
    transferred = transferred / row[:, None]
    return {
        "weights": transferred,
        "threshold": region_thresholds,
        "unmatchedCount": 0,
        "influenceCountDeferred": True,
        "maxInfluencesPerVertex": int((transferred > 1e-6).sum(axis=1).max()),
    }


def _regularize(weights: np.ndarray, roc_regions: np.ndarray, names: list[str]) -> np.ndarray:
    out = np.asarray(weights, dtype=np.float64).copy()
    name_index = {name: index for index, name in enumerate(names)}
    for region in sorted(set(roc_regions.tolist())):
        mask = roc_regions == region
        if not np.any(mask):
            continue
        allowed = allowed_regions_for(str(region))
        columns = [
            name_index[name]
            for group, joints in REGION_JOINTS.items()
            if group in allowed
            for name in joints
        ]
        if str(region) == "beak":
            columns = [name_index["BN_Jaw"], name_index["Bip01_Head"]]
        keep = np.zeros_like(out[mask])
        keep[:, columns] = out[mask][:, columns]
        out[mask] = keep
    return out


def surface_handles_from_unmatched(
    unmatched: list[dict[str, Any]],
    *,
    roc_vertices: np.ndarray,
    roc_regions: np.ndarray,
    donor_vertices: np.ndarray,
    donor_faces: np.ndarray,
    donor_weights: np.ndarray,
    donor_names: list[str],
    limit: int = 48,
) -> tuple[np.ndarray, np.ndarray]:
    """Pin unmatched Roc verts to the closest allowed donor surface point. Skeleton stays fixed."""
    if not unmatched:
        raise ValueError("no unmatched vertices to turn into handles")
    donor_regions = donor_vertex_regions(donor_weights, donor_names)
    chosen = unmatched[: int(limit)]
    indices = []
    targets = []
    for item in chosen:
        vertex = int(item["vertex"])
        region = str(roc_regions[vertex])
        allowed = allowed_regions_for(region)
        keep = _triangle_allowed(donor_regions, donor_faces, allowed)
        if not np.any(keep):
            continue
        tri_index, _bary, _dist = _closest_on_triangles(roc_vertices[vertex], donor_vertices, donor_faces[keep])
        faces = donor_faces[keep]
        corners = faces[tri_index]
        # Recompute the actual closest point rather than a joint guess.
        a, b, c = donor_vertices[corners]
        closest, bary = _closest_points_on_triangles(roc_vertices[vertex], a[None], b[None], c[None])
        indices.append(vertex)
        targets.append(closest[0])
    if not indices:
        raise ValueError("unmatched vertices have no donor surface in their anatomical region")
    return np.asarray(indices, dtype=np.int64), np.stack(targets)
