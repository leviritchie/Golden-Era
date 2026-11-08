"""Texture-guided narrow-cut selection for warp-causing mesh connections.

A warp is a high-strain region dragged across a connection that the texture
already treats as two parts (prop melted into body, tool in hand, and so on).
Blind splitting does not fix strain (see commit b0395770ab): the weight rule is
a function of position and cannot key on a patch.  This module only *selects*
where a cut belongs; it never edits a mesh.  The proposal feeds the reviewed
``attachment_repair.split_attachment`` cutter, which owns the edit and its
invariants.

Selection rule, in order:
1. High-strain faces: max principal stretch above ``STRAIN_STRETCH_LIMIT`` or
   compression below ``STRAIN_COMPRESS_LIMIT``.  These bands match the
   ``audit_frame_deformation`` violation definition, so the detector and the
   audit agree on what a warp is.
2. Severity focus: hot faces are the top 5% by severity (stretch excess or
   compression deficit over the audit bands) via closest-observation
   percentile, so a mesh-wide mild strain field does not merge into one giant
   component while genuinely severe patches fragment into actionable pieces,
   and tied faces are never split by interpolation.
   Components connect over the exact-position-welded face graph, so UV seams
   do not fragment the geometry.
3. Texture divergence across each boundary edge: the two sides' face-corner UVs
   are sampled from the albedo, and the edge counts as a texture seam only when
   its divergence exceeds the mesh-global median over all welded edges (with a
   1.5-texel floor so sub-texel sampling noise never counts).
4. Rank components by violation mass (summed stretch excess plus summed
   compression deficit, which favors substantial warp over sliver outliers)
   times seam fraction.  The suggestion is the top-ranked texture-seamed
   component; when no severe component reaches the seam fraction, the top-mass
   component is suggested instead as a geometric neck with ``textureAgrees:
   false``.  Callers must not apply a ``textureAgrees: false`` proposal
   blindly: it is a review flag, and on same-skin webbing the cut placement
   needs human confirmation.  Texture guides but never vetoes.
   A component with no boundary at all (global warp, nothing to cut around)
   is never suggested.

Known limits (documented, not fixed here): a busy albedo raises the global
median and can hide weak seams; damage spread over more than 5% of faces
raises the p95 floor and hides moderate warps; exact-position welding follows
the repo convention, so near-duplicate positions fragment components.

Sampling convention matches ``mesh_preview.sample_albedo_uv`` exactly
(v = 0 addresses the image first row, bilinear, edge-clamped); see
``test_neck_cut_selection.py::test_sampler_matches_preview_convention``.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

# Violation bands shared with audit_frame_deformation (stretch > 1.5 or
# compression < 0.67 flags a triangle).  Reused, not redefined.
STRAIN_STRETCH_LIMIT = 1.5
STRAIN_COMPRESS_LIMIT = 0.67
# A component boundary must be at least half texture seam to count as texture
# backed.  Below that the suggestion is still returned, but flagged
# textureAgrees=false so no caller mistakes it for a texture-backed cut.
SEAM_FRACTION_MIN = 0.5
# Sub-texel UV differences are sampling noise, not seams: an edge counts as a
# texture seam only above this many texels (normalized by texture size), even
# when the mesh-global median divergence is zero.
SEAM_DIVERGENCE_FLOOR_TEXELS = 1.5


def _check_finite_array(value: Any, name: str, ndim: int) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != ndim or not len(array) or not np.issubdtype(array.dtype, np.number):
        raise ValueError(f"{name} must be a non-empty numeric array with {ndim} dims")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array


def sample_texel(albedo: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Bilinear albedo sample with the preview convention (v = 0 is row 0)."""
    tex = np.asarray(albedo)
    if tex.ndim != 3 or tex.shape[2] not in (3, 4) or not len(tex):
        raise ValueError("albedo must be a non-empty [H,W,3|4] array")
    height, width = tex.shape[:2]
    uu = np.clip(np.asarray(u, dtype=np.float64), 0.0, 1.0) * (width - 1)
    vv = np.clip(np.asarray(v, dtype=np.float64), 0.0, 1.0) * (height - 1)
    x0 = np.floor(uu).astype(np.int64)
    y0 = np.floor(vv).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = (uu - x0)[..., None]
    fy = (vv - y0)[..., None]
    rgb = tex[..., :3]
    if rgb.dtype != np.float64:
        rgb = rgb.astype(np.float64)
    c00 = rgb[y0, x0]
    c10 = rgb[y0, x1]
    c01 = rgb[y1, x0]
    c11 = rgb[y1, x1]
    return c00 * (1.0 - fx) * (1.0 - fy) + c10 * fx * (1.0 - fy) + c01 * (1.0 - fx) * fy + c11 * fx * fy


def _weld(vertices: np.ndarray) -> np.ndarray:
    _, inverse = np.unique(np.ascontiguousarray(vertices), axis=0, return_inverse=True)
    return inverse.astype(np.int64)


def _welded_face_graph(triangles: np.ndarray, weld: np.ndarray) -> dict[int, set[int]]:
    """Face adjacency over exact-position-welded edges (UV seams stay connected)."""
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face, tri in enumerate(triangles):
        wt = weld[tri]
        for a, b in ((wt[0], wt[1]), (wt[1], wt[2]), (wt[2], wt[0])):
            if a == b:
                continue
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(face)
    graph: dict[int, set[int]] = {face: set() for face in range(len(triangles))}
    for faces in edge_faces.values():
        for i, left in enumerate(faces[:-1]):
            for right in faces[i + 1:]:
                if left != right:
                    graph[left].add(right)
                    graph[right].add(left)
    return graph


def _components(mask: np.ndarray, graph: dict[int, set[int]]) -> list[list[int]]:
    seen = np.zeros(len(mask), dtype=bool)
    parts: list[list[int]] = []
    for face in np.flatnonzero(mask):
        if seen[face]:
            continue
        part = [face]
        seen[face] = True
        queue: deque[int] = deque([face])
        while queue:
            current = queue.popleft()
            for other in graph[current]:
                if mask[other] and not seen[other]:
                    seen[other] = True
                    queue.append(other)
                    part.append(other)
        parts.append(part)
    return parts


def _edge_divergence(
    albedo: np.ndarray,
    uvs: np.ndarray,
    triangles: np.ndarray,
    weld: np.ndarray,
) -> dict[tuple[int, int], float]:
    """Texture divergence per welded edge, from face-corner UVs on both sides.

    For each endpoint position of a welded edge, the corners contributed by the
    incident faces may carry different UVs (seam duplicates).  Divergence is the
    worst endpoint's texel distance (normalized by texture size) plus RGB
    distance (normalized), so an edge counts as a seam when EITHER the UVs jump
    to a far texel OR the sampled colors disagree.
    """
    height, width = albedo.shape[:2]
    pos_faces: dict[tuple[int, int], dict[int, list[int]]] = {}
    for face, tri in enumerate(triangles):
        wt = weld[tri]
        for corner, (a, b) in enumerate(((wt[0], wt[1]), (wt[1], wt[2]), (wt[2], wt[0]))):
            if a == b:
                continue
            key = (min(a, b), max(a, b))
            entry = pos_faces.setdefault(key, {})
            entry.setdefault(a, []).append(int(tri[corner]))
            entry.setdefault(b, []).append(int(tri[(corner + 1) % 3]))
    out: dict[tuple[int, int], float] = {}
    for key, endpoints in pos_faces.items():
        worst = 0.0
        for vert_ids in endpoints.values():
            if len(vert_ids) < 2:
                continue
            uu = uvs[np.asarray(vert_ids, dtype=np.int64)][:, 0]
            vv = uvs[np.asarray(vert_ids, dtype=np.int64)][:, 1]
            colors = sample_texel(albedo, uu, vv) / 255.0
            tex_d = float(np.abs(uu[:, None] - uu[None, :]).max() * width +
                          np.abs(vv[:, None] - vv[None, :]).max() * height) / max(width, height)
            col_d = float(np.linalg.norm(colors[:, None, :] - colors[None, :, :], axis=-1).max() / np.sqrt(3.0))
            worst = max(worst, tex_d + col_d)
        out[key] = worst
    return out


def select_neck_cut(
    *,
    rest_vertices: Any,
    triangles: Any,
    uvs: Any,
    albedo: Any,
    face_stretch_max: Any,
    face_compress_min: Any,
    joint_names: list[str],
    vertex_joint_ids: Any,
    vertex_joint_weights: Any,
) -> dict[str, Any]:
    """Propose one texture-seamed narrow cut around the worst warp, or no cut.

    Returns a report with ``selectedFaces`` (possibly empty), ``owner`` (the
    prop side's dominant joint, or None), metrics, and a ``reason`` string.
    Never edits its inputs.  Raises only on malformed inputs, never on a mesh
    that simply needs no cut.
    """
    rest = _check_finite_array(rest_vertices, "rest_vertices", 2)
    tri = np.asarray(triangles)
    uv = _check_finite_array(uvs, "uvs", 2)
    tex = np.asarray(albedo)
    if rest.shape[1] != 3:
        raise ValueError("rest_vertices must have shape [V,3]")
    if tri.ndim != 2 or tri.shape[1] != 3 or not np.issubdtype(tri.dtype, np.integer):
        raise ValueError("triangles must be an integer [T,3] array")
    if np.any(tri < 0) or np.any(tri >= len(rest)):
        raise ValueError("triangle indices are outside vertices")
    if uv.shape != (len(rest), 2):
        raise ValueError("uvs must have shape [V,2] matching vertices")
    if tex.ndim != 3 or tex.shape[2] not in (3, 4) or tex.shape[0] == 0 or tex.shape[1] == 0:
        raise ValueError("albedo must be a non-empty [H,W,3|4] array")
    # Convert once here: per-edge sampling must not reallocate a 100MB float
    # copy of a production texture on every call.
    if tex.dtype != np.float64:
        tex = tex.astype(np.float64)
    stretch = np.asarray(face_stretch_max, dtype=np.float64).reshape(-1)
    compress = np.asarray(face_compress_min, dtype=np.float64).reshape(-1)
    if stretch.shape != (len(tri),) or compress.shape != (len(tri),):
        raise ValueError("face strain arrays must have one row per triangle")
    if not np.isfinite(stretch).all() or not np.isfinite(compress).all():
        raise ValueError("face strain arrays must be finite")
    if not joint_names or len(set(joint_names)) != len(joint_names):
        raise ValueError("joint_names must be non-empty and unique")
    ids = np.asarray(vertex_joint_ids)
    wts = np.asarray(vertex_joint_weights, dtype=np.float64)
    if ids.shape != wts.shape or ids.ndim != 2 or ids.shape[0] != len(rest):
        raise ValueError("vertex joint ids/weights must be [V,S] slot arrays")
    if np.any(ids < 0) or np.any(ids >= len(joint_names)):
        raise ValueError("vertex joint ids are outside joint_names")
    if not np.isfinite(wts).all() or np.any(wts < 0):
        raise ValueError("vertex joint weights must be finite and non-negative")

    weld = _weld(rest)
    graph = _welded_face_graph(tri, weld)
    # Severity unifies stretch excess and compression deficit so crush-only
    # warps count.  Focus is the top 5% by severity via closest-observation
    # percentile (an actual data value, so interpolation never splits faces
    # tied at the boundary).  Fixtures carry cold padding for the same reason
    # tiny meshes knife-edge; production meshes are overwhelmingly cold.
    severity = np.maximum(stretch - STRAIN_STRETCH_LIMIT, STRAIN_COMPRESS_LIMIT - compress)
    severity = np.maximum(severity, 0.0)
    sev_floor = float(np.percentile(severity, 95, method="closest_observation"))
    hot = (severity > 0.0) & (severity >= sev_floor)
    if not hot.any():
        return {"selectedFaces": [], "owner": None, "ownerIndex": None,
                "textureAgrees": False,
                "reason": "no faces exceed the strain violation bands",
                "metrics": None, "medianEdgeDivergence": None,
                "ranking": [], "thresholds": _thresholds()}
    divergence = _edge_divergence(tex, uv, tri, weld)
    median_div = float(np.median(list(divergence.values()))) if divergence else 0.0
    seam_limit = max(median_div, SEAM_DIVERGENCE_FLOOR_TEXELS / max(tex.shape[0], tex.shape[1]))

    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face, t in enumerate(tri):
        wt = weld[t]
        for a, b in ((wt[0], wt[1]), (wt[1], wt[2]), (wt[2], wt[0])):
            if a != b:
                edge_faces.setdefault((min(a, b), max(a, b)), []).append(face)
    ranking = []
    for part in _components(hot, graph):
        part_set = set(part)
        seam = total = 0
        for key, faces in edge_faces.items():
            inside = [f for f in faces if f in part_set]
            outside = [f for f in faces if f not in part_set]
            if inside and outside:
                total += 1
                if divergence.get(key, 0.0) > seam_limit:
                    seam += 1
        seam_fraction = seam / total if total else 0.0
        violation_mass = float(severity[part].sum())
        ranking.append({
            "faceCount": len(part),
            "maxStretch": float(stretch[part].max()),
            "violationMass": violation_mass,
            "boundaryEdges": total,
            "seamBoundaryEdges": seam,
            "seamFraction": seam_fraction,
            "score": violation_mass * seam_fraction,
            "faces": [int(face) for face in sorted(part)],
        })
    ranking.sort(key=lambda row: -row["score"])
    ringed = [row for row in ranking if row["boundaryEdges"] > 0]
    seamed = [row for row in ringed if row["seamFraction"] >= SEAM_FRACTION_MIN]
    if not ringed:
        return {"selectedFaces": [], "owner": None, "ownerIndex": None,
                "textureAgrees": False,
                "reason": "severe warp has no boundary to cut around",
                "metrics": None, "medianEdgeDivergence": median_div,
                "ranking": [{k: v for k, v in row.items() if k != "faces"} for row in ranking],
                "thresholds": _thresholds()}
    if seamed:
        best = seamed[0]
        texture_agrees = True
        reason = "cut proposed at a texture-seamed warp neck"
    else:
        best = max(ringed, key=lambda row: row["violationMass"])
        texture_agrees = False
        reason = ("no severe warp follows a texture seam; geometric neck suggested, "
                  "review carefully before cutting same-skin webbing")
    comp_verts = np.unique(tri[best["faces"]].reshape(-1))
    joint_mass = np.zeros(len(joint_names))
    np.add.at(joint_mass, ids[comp_verts].reshape(-1), wts[comp_verts].reshape(-1))
    owner_index = int(np.argmax(joint_mass))
    return {"selectedFaces": best["faces"], "owner": joint_names[owner_index],
            "ownerIndex": owner_index,
            "textureAgrees": texture_agrees,
            "reason": reason,
            "metrics": {k: best[k] for k in
                        ("faceCount", "maxStretch", "violationMass", "boundaryEdges",
                         "seamBoundaryEdges", "seamFraction", "score")},
            "medianEdgeDivergence": median_div,
            "ranking": [{k: v for k, v in row.items() if k != "faces"} for row in ranking],
            "thresholds": _thresholds()}


def _thresholds() -> dict[str, float]:
    return {"stretchLimit": STRAIN_STRETCH_LIMIT,
            "compressLimit": STRAIN_COMPRESS_LIMIT,
            "seamFractionMin": SEAM_FRACTION_MIN,
            "seamFloorTexels": SEAM_DIVERGENCE_FLOOR_TEXELS}
