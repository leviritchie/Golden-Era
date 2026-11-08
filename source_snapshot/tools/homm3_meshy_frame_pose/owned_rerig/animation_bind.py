"""Reference-frame-constrained owned bind for AI-generated meshes.

An image-to-3D mesh arrives with no armature we may ship, and for many units the
only motion knowledge available is the source animation itself.  The sprite
motion lane already converts that animation into rigid parts, relative hinges,
and per-frame part centroids.  This module turns those reference frames plus the
mesh volume into an owned bind, so the animation's own articulation - not an
authored AABB template and not an image score - decides where joints go and
which surfaces may move together.

Three decisions are reference-frame-owned:

* the kinematic tree is the hinge graph the animation actually produced, so a
  link exists only where relative motion was measured;
* a joint sits on the camera ray through its hinge and is placed at maximum
  local clearance inside the flesh, using ray-parity containment - never on the
  silhouette boundary and never at an AABB fraction;
* a candidate bind is accepted only if replaying the animation's own relative
  part motion on it stays within the rigid-body bound.  A rigid body cannot
  change its distance to its own hinge, and an orthographic projection only
  contracts, so ``|c_f - carried_hinge_f| <= |c_0 - hinge_0|`` must hold in
  every observed frame.  A joint that is misplaced in depth, in the image
  plane, or on the wrong body part violates that bound.

None of these checks uses silhouette IoU, chroma, or a rendered comparison.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .reference_frames import PART_PREFIX, CameraBasis, ReferenceFrames, ray_origin

AUDIT_SCHEMA = "reference_frame_bind_audit.v1"
BIND_SCHEMA = "reference_frame_bind.v1"


@dataclass
class BindParams:
    # vertex -> part labelling (screen-space match against the reference tracks)
    max_assign_px: float = 18.0
    min_primary_frac: float = 0.55
    min_part_verts: int = 8
    # joint placement
    hinge_search_px: float = 28.0
    min_band_verts: int = 6
    depth_samples: int = 96
    depth_pad_frac: float = 0.25
    min_clearance: float = 1e-6
    max_band_points: int = 400
    # animation-driven hinge-pixel refinement
    refine_hinge: bool = True
    refine_rounds: int = 2
    refine_grid: int = 5
    refine_min_gain: float = 0.01
    # skinning
    power: float = 8.0
    trim: float = 0.03
    max_influences: int = 4
    # reference-frame acceptance
    max_reach_excess: float = 0.06
    max_part_residual_px: float = 4.0
    max_part_residual_worst_px: float = 12.0
    rel_motion_warn_px: float = 1.5


# --------------------------------------------------------------------------- #
# mesh helpers
# --------------------------------------------------------------------------- #


def mesh_boundary_edges(indices: np.ndarray) -> int:
    """Edges used by exactly one triangle.  >0 means ray parity is not a proof."""
    tri = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if tri.size == 0:
        return 0
    edges = np.concatenate((tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]), axis=0)
    _unique, counts = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    return int(np.sum(counts == 1))


def _nearest_chunked(
    points: np.ndarray,
    refs: np.ndarray,
    *,
    chunk: int = 512,
    max_dist: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    idx = np.full(len(points), -1, dtype=np.int64)
    dist = np.full(len(points), np.inf, dtype=np.float64)
    for start in range(0, len(points), chunk):
        block = points[start : start + chunk]
        d2 = ((block[:, None, :] - refs[None, :, :]) ** 2).sum(axis=2)
        best = np.argmin(d2, axis=1)
        d = np.sqrt(d2[np.arange(len(block)), best])
        idx[start : start + chunk] = best
        dist[start : start + chunk] = d
    if max_dist is not None:
        idx = np.where(dist <= float(max_dist), idx, -1)
    return idx, dist


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Chebyshev dilation by ``radius`` using 3x3 passes (no scipy dependency)."""
    out = np.asarray(mask, dtype=bool)
    for _ in range(int(radius)):
        height, width = out.shape
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        grown = np.zeros_like(out)
        for dy in range(3):
            for dx in range(3):
                grown |= padded[dy : dy + height, dx : dx + width]
        out = grown
    return out


def label_vertices_by_tracks(
    *,
    positions: np.ndarray,
    proj: np.ndarray,
    frames: ReferenceFrames,
    basis: CameraBasis,
    sprite_alpha: np.ndarray | None,
    params: BindParams,
) -> dict[str, Any]:
    """Label mesh vertices with reference-frame part ids by screen-space match."""
    sw, sh = basis.sprite_size
    count = len(positions)
    labels = np.full(count, -1, dtype=np.int32)
    ix = np.rint(proj[:, 0]).astype(np.int64)
    iy = np.rint(proj[:, 1]).astype(np.int64)
    inside = (proj[:, 2] > 0.0) & (ix >= 0) & (ix < sw) & (iy >= 0) & (iy < sh)
    if sprite_alpha is not None:
        alpha = np.asarray(sprite_alpha)
        if alpha.shape != (sh, sw):
            raise ValueError(
                f"sprite alpha {alpha.shape} does not match the camera sprite size {(sh, sw)}"
            )
        grown = _dilate(alpha >= 8, 3)
        on_sprite = inside & grown[np.clip(iy, 0, sh - 1), np.clip(ix, 0, sw - 1)]
    else:
        on_sprite = inside
    on_sprite_count = int(on_sprite.sum())
    if on_sprite_count == 0:
        raise RuntimeError(
            "fail-closed: no projected vertex lands inside the bind frame; the camera, "
            "root yaw, projection scale, or image offset is wrong"
        )
    candidates = np.flatnonzero(on_sprite)
    hit, _dist = _nearest_chunked(
        proj[candidates, :2], frames.track_xy0, max_dist=params.max_assign_px
    )
    keep = hit >= 0
    labels[candidates[keep]] = frames.track_labels[hit[keep]].astype(np.int32)
    primary = int(keep.sum())
    primary_frac = primary / on_sprite_count
    if primary_frac < params.min_primary_frac:
        raise RuntimeError(
            f"fail-closed: primary screen-assign frac {primary_frac:.1%} of on-sprite verts "
            f"< {params.min_primary_frac:.0%} (primary={primary}, onSprite={on_sprite_count}); "
            "the mesh is not registered to the bind frame or the tracks do not cover it"
        )
    labeled = np.flatnonzero(labels >= 0)
    if labeled.size == 0:
        raise RuntimeError("fail-closed: no vertex matched a reference-frame track")
    unlabeled = np.flatnonzero(labels < 0)
    fill = 0
    if unlabeled.size:
        nearest, _ = _nearest_chunked(positions[unlabeled], positions[labeled])
        labels[unlabeled] = labels[labeled[nearest]]
        fill = int(unlabeled.size)
    counts = [int(np.sum(labels == part)) for part in range(frames.part_count)]
    thin = [
        frames.part_names[part]
        for part, owned in enumerate(counts)
        if owned < params.min_part_verts
    ]
    if thin:
        raise RuntimeError(
            f"fail-closed: parts with fewer than {params.min_part_verts} mesh vertices: {thin}"
        )
    return {
        "labels": labels,
        "partVertCounts": counts,
        "primaryFrac": float(primary_frac),
        "primaryCount": primary,
        "onSpriteCount": on_sprite_count,
        "fillCount": fill,
    }


# --------------------------------------------------------------------------- #
# kinematic tree from the hinge graph
# --------------------------------------------------------------------------- #


def build_part_tree(
    *,
    part_vert_counts: list[int],
    frames: ReferenceFrames,
    attach: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Root = largest mesh part; tree edges are the animation's strongest hinges."""
    count = frames.part_count
    if len(part_vert_counts) != count:
        raise ValueError("part_vert_counts length does not match the reference frames")
    root = int(max(range(count), key=lambda part: (int(part_vert_counts[part]), -part)))
    pairs = frames.hinge_pairs()
    ranked = sorted(
        pairs.items(),
        key=lambda item: (-float(item[1].get("relMotionPx") or 0.0), item[0][0], item[0][1]),
    )
    parent: dict[int, int] = {}
    linked = {root}
    dropped: list[dict[str, Any]] = []
    pending = list(ranked)
    while pending:
        progressed = False
        remaining: list[tuple[tuple[int, int], dict[str, Any]]] = []
        for (a, b), hinge in pending:
            a_in, b_in = a in linked, b in linked
            if a_in and b_in:
                dropped.append(
                    {
                        "partA": frames.part_names[a],
                        "partB": frames.part_names[b],
                        "relMotionPx": float(hinge.get("relMotionPx") or 0.0),
                        "reason": "cycle_edge_already_connected",
                    }
                )
                progressed = True
                continue
            if a_in != b_in:
                child, par = (b, a) if a_in else (a, b)
                parent[child] = par
                linked.add(child)
                progressed = True
                continue
            remaining.append(((a, b), hinge))
        pending = remaining
        if not progressed:
            break
    overrides: dict[int, int] = {}
    for raw_child, raw_parent in (attach or {}).items():
        child, par = int(raw_child), int(raw_parent)
        if child in parent:
            continue
        if par not in linked:
            raise ValueError(
                f"attach override parent {frames.part_names[par]} is not linked into the tree"
            )
        parent[child] = par
        linked.add(child)
        overrides[child] = par
    orphan = [
        frames.part_names[part]
        for part in range(count)
        if part != root and part not in parent
    ]
    if orphan:
        raise RuntimeError(
            f"fail-closed: parts with no hinge path from {frames.part_names[root]}: {orphan}. "
            "Re-run articulation discovery with a clip that articulates them "
            "(--min-rel-motion lower, --max-part-pair-dist higher), or declare an explicit "
            "partAttachments entry for a prop that genuinely does not articulate."
        )
    children: dict[int, list[int]] = {part: [] for part in range(count)}
    for child, par in parent.items():
        children[par].append(child)
    order: list[int] = []
    queue = [root]
    while queue:
        node = queue.pop(0)
        order.append(node)
        queue.extend(children[node])
    if len(order) != count:
        raise RuntimeError("fail-closed: part tree does not cover every part")
    undirected_motion = {
        frames.part_names[part]: float(pairs[(min(part, parent[part]), max(part, parent[part]))].get("relMotionPx") or 0.0)
        for part in parent
    }
    return {
        "root": root,
        "parent": parent,
        "children": children,
        "order": order,
        "hingeByPair": pairs,
        "droppedEdges": dropped,
        "attachOverrides": {str(child): par for child, par in overrides.items()},
        "edgeRelMotionPx": undirected_motion,
    }


# --------------------------------------------------------------------------- #
# joint placement inside the flesh
# --------------------------------------------------------------------------- #


def _ray_triangle_ts(
    origin: np.ndarray,
    direction: np.ndarray,
    triangles: np.ndarray,
    positions: np.ndarray,
) -> np.ndarray:
    """Moller-Trumbore.  ``direction`` must be unit so ``t`` is a distance."""
    if len(triangles) == 0:
        return np.zeros(0, dtype=np.float64)
    v0 = positions[triangles[:, 0]]
    v1 = positions[triangles[:, 1]]
    v2 = positions[triangles[:, 2]]
    edge1 = v1 - v0
    edge2 = v2 - v0
    pvec = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, pvec)
    ok = np.abs(det) > 1e-12
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    tvec = origin - v0
    u = (tvec * pvec).sum(axis=1) * inv
    ok &= (u >= 0.0) & (u <= 1.0)
    qvec = np.cross(tvec, edge1)
    v = (qvec @ direction) * inv
    ok &= (v >= 0.0) & (u + v <= 1.0)
    t = (edge2 * qvec).sum(axis=1) * inv
    return np.sort(t[ok])


def _place_joint_at_pixel(
    *,
    pixel: tuple[float, float],
    band_ids: np.ndarray,
    positions: np.ndarray,
    proj: np.ndarray,
    indices: np.ndarray,
    basis: CameraBasis,
    params: BindParams,
) -> dict[str, Any]:
    """Place a joint on the camera ray at maximum local clearance inside the flesh.

    The band's own depth span bounds the search, so the joint cannot slide onto a
    different limb that happens to share the same pixel.
    """
    if band_ids.size < params.min_band_verts:
        return {"ok": False, "reason": "band_too_small", "bandCount": int(band_ids.size)}
    px, py = float(pixel[0]), float(pixel[1])
    depths = proj[band_ids, 2]
    lo, hi = float(depths.min()), float(depths.max())
    pad = params.depth_pad_frac * max(hi - lo, 1e-6)
    samples = np.linspace(lo - pad, hi + pad, int(params.depth_samples))
    origin = ray_origin(px, py, basis)
    points = origin + basis.forward * samples[:, None]

    tri = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    projected = proj[:, :2]
    tri_proj = projected[tri]
    tri_min = tri_proj.min(axis=1)
    tri_max = tri_proj.max(axis=1)
    covers = (tri_min[:, 0] <= px) & (px <= tri_max[:, 0]) & (tri_min[:, 1] <= py) & (py <= tri_max[:, 1])
    crossings = _ray_triangle_ts(origin, basis.forward, tri[covers], positions)
    parity = np.searchsorted(crossings, samples, side="left") % 2 == 1

    band_positions = positions[band_ids]
    if len(band_positions) > params.max_band_points:
        stride = int(np.ceil(len(band_positions) / params.max_band_points))
        band_positions = band_positions[::stride]
    clearance = np.linalg.norm(
        points[:, None, :] - band_positions[None, :, :], axis=2
    ).min(axis=1)

    valid = parity & (clearance > params.min_clearance)
    if not np.any(valid):
        return {
            "ok": False,
            "reason": "no_contained_sample",
            "bandCount": int(band_ids.size),
            "depthRange": [lo, hi],
            "crossingCount": int(crossings.size),
        }
    best = int(np.flatnonzero(valid)[int(np.argmax(clearance[valid]))])
    return {
        "ok": True,
        "point": points[best].copy(),
        "depth": float(samples[best]),
        "clearance": float(clearance[best]),
        "bandCount": int(band_ids.size),
        "crossingCount": int(crossings.size),
    }


# --------------------------------------------------------------------------- #
# reference-frame replay: acceptance signal and hinge refinement
# --------------------------------------------------------------------------- #


def _affine_apply(mats: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """``mats`` (...,3,3) applied to ``pts`` (...,2)."""
    ones = np.ones(pts.shape[:-1] + (1,), dtype=np.float64)
    homo = np.concatenate((pts, ones), axis=-1)
    return np.einsum("...ij,...j->...i", mats, homo)[..., :2]


def _translation(tx: float, ty: float) -> np.ndarray:
    return np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]])


def _hinge_rotation(hinge: np.ndarray, theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    return _translation(hinge[0], hinge[1]) @ rot @ _translation(-hinge[0], -hinge[1])


def _wrap_pi(values: float) -> float:
    return (values + math.pi) % (2.0 * math.pi) - math.pi


def _radial_anomaly(
    *,
    pixel: tuple[float, float],
    child: int,
    affine_parent: np.ndarray,
    frames: ReferenceFrames,
) -> tuple[np.ndarray, np.ndarray, float]:
    """``radial_f / radial_0 - 1`` per observed frame for one hinge candidate.

    A rigid body keeps a constant distance to its own hinge, so a positive value
    is impossible and means the joint is not where the animation puts it.
    """
    hinge = np.array([float(pixel[0]), float(pixel[1])])
    c0 = frames.centroids[0, child]
    u0 = c0 - hinge
    r0 = float(np.linalg.norm(u0))
    observed = frames.centroids[:, child]
    carried = _affine_apply(affine_parent, hinge)
    radial = np.linalg.norm(observed - carried, axis=1)
    valid = np.isfinite(radial) & np.isfinite(observed).all(axis=1) & (r0 > 1e-6)
    rel = radial[valid] / r0 - 1.0 if r0 > 1e-6 else np.zeros(0)
    return np.flatnonzero(valid), rel, r0


def _refine_hinge_pixel(
    *,
    pixel: tuple[float, float],
    child: int,
    affine_parent: np.ndarray,
    frames: ReferenceFrames,
    params: BindParams,
) -> dict[str, Any]:
    """Search the hinge pixel that best satisfies the rigid-reach bound.

    The animation itself corrects the joint: the accepted pixel minimizes both
    the worst positive radial excess and the mean absolute radial drift, with no
    image comparison involved.
    """

    def score(candidate: tuple[float, float]) -> float:
        _idx, rel, _r0 = _radial_anomaly(
            pixel=candidate, child=child, affine_parent=affine_parent, frames=frames
        )
        if rel.size == 0:
            return float("inf")
        return max(0.0, float(rel.max())) + 0.25 * float(np.abs(rel).mean())

    base_pixel = (float(pixel[0]), float(pixel[1]))
    base = score(base_pixel)
    best_pixel, best = base_pixel, base
    step = float(params.hinge_search_px)
    grid = max(2, int(params.refine_grid))
    for _round in range(int(params.refine_rounds) + 1):
        center = best_pixel
        for i in range(grid):
            for j in range(grid):
                dx = (-1.0 + 2.0 * i / (grid - 1)) * step
                dy = (-1.0 + 2.0 * j / (grid - 1)) * step
                candidate = (center[0] + dx, center[1] + dy)
                value = score(candidate)
                if value < best:
                    best_pixel, best = candidate, value
        step *= 0.5
    gain = 0.0 if not np.isfinite(base) else (base - best) / max(base, 1e-9)
    accepted = bool(np.isfinite(best)) and gain >= params.refine_min_gain
    return {
        "accepted": bool(accepted),
        "pixel": list(best_pixel if accepted else base_pixel),
        "basePixel": list(base_pixel),
        "searchedPixel": list(best_pixel),
        "baseScore": None if not np.isfinite(base) else float(base),
        "bestScore": None if not np.isfinite(best) else float(best),
        "gain": float(gain),
    }


# --------------------------------------------------------------------------- #
# skin weights restricted to hinge neighbours
# --------------------------------------------------------------------------- #


def _point_segment_distance(points: np.ndarray, head: np.ndarray, tail: np.ndarray) -> np.ndarray:
    seg = tail - head
    length2 = float(np.dot(seg, seg))
    rel = points - head
    if length2 < 1e-12:
        return np.linalg.norm(rel, axis=1)
    t = np.clip((rel @ seg) / length2, 0.0, 1.0)
    return np.linalg.norm(rel - t[:, None] * seg[None, :], axis=1)


def _bone_tails(
    *,
    positions: np.ndarray,
    labels: np.ndarray,
    heads: np.ndarray,
    tree: dict[str, Any],
    part_count: int,
) -> np.ndarray:
    """Tail = the part's distal end, so a bone spans the flesh it carries."""
    tails = np.zeros_like(heads)
    for part in range(part_count):
        head = heads[part]
        rows = positions[labels == part]
        if rows.size == 0:
            raise RuntimeError(f"fail-closed: {PART_PREFIX}{part:02d} has no labelled vertices")
        offsets = rows - head
        distances = np.linalg.norm(offsets, axis=1)
        far = float(distances.max())
        if far < 1e-9:
            raise RuntimeError(
                f"fail-closed: {PART_PREFIX}{part:02d} is degenerate; every vertex is at the joint"
            )
        distal = offsets[int(np.argmax(distances))] / far
        kids = tree["children"].get(part, [])
        if kids:
            directions = []
            spans = []
            for kid in kids:
                vector = heads[kid] - head
                span = float(np.linalg.norm(vector))
                if span > 1e-9:
                    directions.append(vector / span)
                    spans.append(span)
            if directions:
                mean_direction = np.mean(directions, axis=0)
                norm = float(np.linalg.norm(mean_direction))
                direction = mean_direction / norm if norm > 1e-9 else distal
                length = float(np.median(spans))
            else:
                direction, length = distal, far
        else:
            direction, length = distal, far
        radius = float(np.linalg.norm(rows.mean(axis=0) - head))
        tails[part] = head + direction * max(length, radius, 1e-6)
    return tails


def skin_by_hinge_neighbourhood(
    *,
    positions: np.ndarray,
    labels: np.ndarray,
    tree: dict[str, Any],
    heads: np.ndarray,
    tails: np.ndarray,
    params: BindParams,
) -> dict[str, Any]:
    """Weights restricted to a part's hinge neighbours.

    Parts that share a hinge may blend (they meet at that joint); parts that the
    animation never linked cannot, so the reference frames supply the partition
    wall that used to be an authored rule list.
    """
    if params.max_influences != 4:
        raise ValueError("glTF JOINTS_0/WEIGHTS_0 are VEC4; max_influences must be 4")
    part_count = len(heads)
    allowed: dict[int, list[int]] = {}
    for part in range(part_count):
        bones = [part]
        parent = tree["parent"].get(part)
        if parent is not None:
            bones.append(parent)
        bones.extend(tree["children"].get(part, []))
        allowed[part] = sorted(set(bones))
    joints = np.zeros((len(positions), 4), dtype=np.int32)
    weights = np.zeros((len(positions), 4), dtype=np.float64)
    for part in range(part_count):
        rows = np.flatnonzero(labels == part)
        if rows.size == 0:
            continue
        points = positions[rows]
        candidates = allowed[part]
        distances = np.stack(
            [_point_segment_distance(points, heads[bone], tails[bone]) for bone in candidates], axis=1
        )
        raw = 1.0 / np.power(distances + 1e-4, params.power)
        order = np.argsort(-raw, axis=1)
        picked = np.take_along_axis(raw, order, axis=1)
        bone_ids = np.asarray(candidates, dtype=np.int32)[order]
        if params.trim > 0.0:
            picked = np.where(picked >= params.trim, picked, 0.0)
        totals = picked.sum(axis=1, keepdims=True)
        zero = totals[:, 0] <= 0.0
        if np.any(zero):
            picked[zero, :] = 0.0
            picked[zero, 0] = 1.0
            totals = picked.sum(axis=1, keepdims=True)
        normalized = picked / np.maximum(totals, 1e-12)
        joints[rows, :4] = bone_ids[:, :4]
        weights[rows, :4] = normalized[:, :4]
    forced: list[str] = []
    for bone in range(part_count):
        owned = np.any((joints == bone) & (weights > 0.05), axis=1)
        if np.any(owned):
            continue
        rows = np.flatnonzero(labels == bone)
        if rows.size == 0:
            forced.append(f"{PART_PREFIX}{bone:02d}:no_vertices")
            continue
        nearest = int(rows[int(np.argmin(np.linalg.norm(positions[rows] - heads[bone], axis=1)))])
        joints[nearest, :] = 0
        weights[nearest, :] = 0.0
        joints[nearest, 0] = bone
        weights[nearest, 0] = 1.0
        forced.append(f"{PART_PREFIX}{bone:02d}:nearest_vertex")
    return {"joints": joints, "weights": weights, "forcedOwnership": forced}


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #


def audit_reference_bind(
    *,
    frames: ReferenceFrames,
    tree: dict[str, Any],
    bone_names: list[str],
    parents: list[int | None],
    heads: np.ndarray,
    tails: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    placements: dict[int, dict[str, Any]],
    radial: dict[int, dict[str, Any]],
    boundary_edges: int,
    params: BindParams,
) -> dict[str, Any]:
    issues: list[str] = []
    review: list[str] = []
    part_count = len(bone_names)
    for bone, name in enumerate(bone_names):
        owned = int(np.sum(np.any((joints == bone) & (weights > 0.05), axis=1)))
        if owned <= 0:
            issues.append(f"bone {name} owns no vertices")
        if float(np.linalg.norm(tails[bone] - heads[bone])) < 1e-6:
            issues.append(f"bone {name} has zero length")
    per_part: list[dict[str, Any]] = []
    for part in range(part_count):
        name = bone_names[part]
        placement = placements.get(part) or {}
        if not placement.get("ok"):
            issues.append(f"{name} has no contained joint ({placement.get('reason')})")
        entry: dict[str, Any] = {
            "part": name,
            "parent": None if parents[part] is None else bone_names[int(parents[part])],
            "outsideRing": int(tree["parent"].get(part) is None),
            "bandCount": placement.get("bandCount"),
            "jointClearance": placement.get("clearance"),
            "hingeRelMotionPx": tree["edgeRelMotionPx"].get(name),
        }
        if parents[part] is None:
            entry.update(
                {
                    "root": True,
                    "framesUsed": frames.frame_count,
                    "radial0Px": None,
                    "meanAbsResidualPx": None,
                    "worstResidualPx": None,
                    "worstRel": None,
                }
            )
            per_part.append(entry)
            continue
        stats = radial.get(part)
        if not stats or int(stats["framesUsed"]) == 0:
            issues.append(
                f"{name} has no usable reference frame; its joint is unvalidated by the animation"
            )
            entry.update({"root": False, "framesUsed": 0})
            per_part.append(entry)
            continue
        rel = np.asarray(stats["rel"], dtype=np.float64)
        r0 = float(stats["radial0Px"] or 0.0)
        if r0 <= 1e-6:
            issues.append(f"{name} has a degenerate hinge radius in the bind frame")
        mean_abs_px = float(np.abs(rel).mean()) * r0
        worst_px = float(np.abs(rel).max()) * r0
        worst_rel = float(rel.max())
        entry.update(
            {
                "root": False,
                "framesUsed": int(stats["framesUsed"]),
                "radial0Px": r0,
                "meanAbsResidualPx": mean_abs_px,
                "worstResidualPx": worst_px,
                "worstRel": worst_rel,
            }
        )
        per_part.append(entry)
        if worst_rel > params.max_reach_excess:
            offenders = int(np.sum(rel > params.max_reach_excess))
            issues.append(
                f"{name} exceeds the rigid reach bound in {offenders} frame(s): worst "
                f"+{worst_rel:.1%} (limit {params.max_reach_excess:.1%})"
            )
        if mean_abs_px > params.max_part_residual_px:
            issues.append(
                f"{name} mean replay residual {mean_abs_px:.2f}px > "
                f"{params.max_part_residual_px:.2f}px"
            )
        if worst_px > params.max_part_residual_worst_px:
            issues.append(
                f"{name} worst replay residual {worst_px:.2f}px > "
                f"{params.max_part_residual_worst_px:.2f}px"
            )
        rel_motion = tree["edgeRelMotionPx"].get(name)
        if rel_motion is not None and rel_motion < params.rel_motion_warn_px:
            review.append(
                f"{name} hinge moved only {rel_motion:.2f}px in the bind clip; "
                "validate it against a clip that articulates it"
            )
    containment_proof = (
        "closed_mesh_ray_parity"
        if boundary_edges == 0
        else "open_mesh_clearance_heuristic_unproven"
    )
    if boundary_edges:
        review.append(
            f"mesh has {boundary_edges} boundary edge(s); joint containment is a clearance "
            "heuristic here, not a parity proof - weld or remesh before treating it as one"
        )
    return {
        "schema": AUDIT_SCHEMA,
        "ok": not issues,
        "issues": issues,
        "reviewNotes": review,
        "containmentProof": containment_proof,
        "boundaryEdges": int(boundary_edges),
        "partCount": part_count,
        "parts": per_part,
        "droppedEdges": tree["droppedEdges"],
        "attachOverrides": tree["attachOverrides"],
        "proof": "generated-artifact",
    }


# --------------------------------------------------------------------------- #
# solver
# --------------------------------------------------------------------------- #


def bind_from_reference_frames(
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    proj: np.ndarray,
    frames: ReferenceFrames,
    basis: CameraBasis,
    params: BindParams | None = None,
    sprite_alpha: np.ndarray | None = None,
    attach: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Solve the owned bind for an unrigged mesh from the reference animation."""
    params = params or BindParams()
    positions = np.asarray(positions, dtype=np.float64)
    indices = np.asarray(indices, dtype=np.int64).reshape(-1)
    labeling = label_vertices_by_tracks(
        positions=positions,
        proj=proj,
        frames=frames,
        basis=basis,
        sprite_alpha=sprite_alpha,
        params=params,
    )
    labels = labeling["labels"]
    tree = build_part_tree(
        part_vert_counts=labeling["partVertCounts"], frames=frames, attach=attach
    )
    part_count = frames.part_count
    boundary_edges = mesh_boundary_edges(indices)
    heads = np.zeros((part_count, 3), dtype=np.float64)
    affines = np.tile(np.eye(3), (frames.frame_count, part_count, 1, 1))
    placements: dict[int, dict[str, Any]] = {}
    refinements: dict[int, dict[str, Any]] = {}
    hinges_used: dict[int, list[float] | None] = {}
    radial: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for part in tree["order"]:
        parent = tree["parent"].get(part)
        if parent is None:
            pixel = (float(frames.centroid_f0(part)[0]), float(frames.centroid_f0(part)[1]))
            refinements[part] = {"accepted": False, "reason": "root_centroid"}
        else:
            hinge = tree["hingeByPair"][(min(part, parent), max(part, parent))]
            base_pixel = (float(hinge["x"]), float(hinge["y"]))
            if params.refine_hinge:
                refinements[part] = _refine_hinge_pixel(
                    pixel=base_pixel,
                    child=part,
                    affine_parent=affines[:, parent],
                    frames=frames,
                    params=params,
                )
            else:
                refinements[part] = {
                    "accepted": False,
                    "reason": "refinement_disabled",
                    "pixel": list(base_pixel),
                }
            pixel = (float(refinements[part]["pixel"][0]), float(refinements[part]["pixel"][1]))
        hinges_used[part] = [pixel[0], pixel[1]]
        band_members = [part] if parent is None else [part, parent]
        band_mask = np.isin(labels, band_members)
        in_radius = (
            np.linalg.norm(proj[:, :2] - np.array(pixel), axis=1) <= params.hinge_search_px
        )
        placement = _place_joint_at_pixel(
            pixel=pixel,
            band_ids=np.flatnonzero(band_mask & in_radius),
            positions=positions,
            proj=proj,
            indices=indices,
            basis=basis,
            params=params,
        )
        placements[part] = placement
        if not placement["ok"]:
            failures.append(
                {
                    "part": frames.part_names[part],
                    "reason": placement.get("reason"),
                    "bandCount": placement.get("bandCount"),
                }
            )
            continue
        heads[part] = placement["point"]
        c0 = frames.centroids[0, part]
        if parent is None:
            observed = frames.centroids[:, part]
            for frame_index in range(frames.frame_count):
                if np.isfinite(observed[frame_index]).all() and np.isfinite(c0).all():
                    delta = observed[frame_index] - c0
                    affines[frame_index, part] = _translation(float(delta[0]), float(delta[1]))
            continue
        hinge_vec = np.array(pixel, dtype=np.float64)
        u0 = c0 - hinge_vec
        for frame_index in range(frames.frame_count):
            affines[frame_index, part] = affines[frame_index, parent]
            child_centroid = frames.centroids[frame_index, part]
            if not np.isfinite(child_centroid).all() or not np.isfinite(u0).all():
                continue
            carried = _affine_apply(affines[frame_index, parent], hinge_vec)
            offset = child_centroid - carried
            if float(np.linalg.norm(offset)) < 1e-6 or float(np.linalg.norm(u0)) < 1e-6:
                continue
            theta = _wrap_pi(
                math.atan2(offset[1], offset[0]) - math.atan2(u0[1], u0[0])
            )
            affines[frame_index, part] = affines[frame_index, parent] @ _hinge_rotation(
                hinge_vec, theta
            )
        used, rel, radius = _radial_anomaly(
            pixel=pixel, child=part, affine_parent=affines[:, parent], frames=frames
        )
        radial[part] = {
            "framesUsed": int(used.size),
            "radial0Px": float(radius),
            "rel": rel,
        }
    if failures:
        detail = "; ".join(
            f"{f['part']}({f.get('reason')}, band={f.get('bandCount')})" for f in failures
        )
        raise RuntimeError(
            f"fail-closed: joint placement failed for {len(failures)} part(s): {detail}"
        )
    tails = _bone_tails(
        positions=positions, labels=labels, heads=heads, tree=tree, part_count=part_count
    )
    skin = skin_by_hinge_neighbourhood(
        positions=positions, labels=labels, tree=tree, heads=heads, tails=tails, params=params
    )
    bone_names = [f"{PART_PREFIX}{part:02d}" for part in range(part_count)]
    parents = [tree["parent"].get(part) for part in range(part_count)]
    audit = audit_reference_bind(
        frames=frames,
        tree=tree,
        bone_names=bone_names,
        parents=parents,
        heads=heads,
        tails=tails,
        joints=skin["joints"],
        weights=skin["weights"],
        placements=placements,
        radial=radial,
        boundary_edges=boundary_edges,
        params=params,
    )
    return {
        "schema": BIND_SCHEMA,
        "boneNames": bone_names,
        "parents": parents,
        "heads": heads,
        "tails": tails,
        "joints": skin["joints"],
        "weights": skin["weights"],
        "labels": labels,
        "root": tree["root"],
        "audit": audit,
        "labeling": {
            "primaryFrac": labeling["primaryFrac"],
            "primaryCount": labeling["primaryCount"],
            "onSpriteCount": labeling["onSpriteCount"],
            "fillCount": labeling["fillCount"],
            "partVertCounts": labeling["partVertCounts"],
        },
        "jointPlacement": {
            frames.part_names[part]: {
                "hingePixel": hinges_used.get(part),
                "refinement": refinements.get(part),
                "contained": bool((placements.get(part) or {}).get("ok")),
                "clearance": (placements.get(part) or {}).get("clearance"),
            }
            for part in range(part_count)
        },
        "skin": {"forcedOwnership": skin["forcedOwnership"]},
        "params": params.__dict__,
        "proof": "generated-artifact",
    }


bind_from_reference_frames = bind_from_reference_frames
audit_reference_bind = audit_reference_bind
