"""Geometry-preservation, rig, weight, and export gates for shape-preserved preparation."""
from __future__ import annotations

from typing import Any

import numpy as np

from conform_roc import bbox_diagonal, edge_lengths
from eagle_glb import inspect_glb_animation, own_bind_identity_gate, reload_and_compare
from glb_skeleton import load_bind_skeleton
from hidden_proxy import vertex_normals

PRESERVE_FACTOR = 1e-5
NON_SLIVER_EDGE_FRACTION = 1e-4
MAX_ISOLATED_NON_SLIVER_STRETCH = 2.5
MIN_PRESERVED_DONOR_MASS = 20.0
MIN_PRESERVED_TARGET_MASS = 1.0


def preservation_limit(vertices: np.ndarray) -> float:
    return PRESERVE_FACTOR * bbox_diagonal(vertices)


def assert_visible_mesh_preserved(
    original: dict[str, Any],
    prepared_vertices: np.ndarray,
    prepared_triangles: np.ndarray,
    prepared_uvs: np.ndarray,
    prepared_albedo: np.ndarray,
) -> dict[str, Any]:
    verts = np.asarray(prepared_vertices, dtype=np.float64)
    src = np.asarray(original["vertices"], dtype=np.float64)
    if verts.shape != src.shape:
        raise ValueError(f"prepared vertex count {verts.shape} != original {src.shape}")
    err = np.linalg.norm(verts - src, axis=1)
    gate = preservation_limit(src)
    max_err = float(err.max())
    if max_err > gate:
        raise ValueError(
            f"visible vertices moved during preparation: max {max_err} > {gate} "
            "(1e-5 * original bbox diagonal)"
        )
    tris = np.asarray(prepared_triangles, dtype=np.int64)
    src_tris = np.asarray(original["triangles"], dtype=np.int64)
    if tris.shape != src_tris.shape or not np.array_equal(tris, src_tris):
        raise ValueError("visible triangle topology changed during preparation")
    uvs = np.asarray(prepared_uvs, dtype=np.float64)
    src_uvs = np.asarray(original["uvs"], dtype=np.float64)
    if uvs.shape != src_uvs.shape or float(np.abs(uvs - src_uvs).max()) > 1e-7:
        raise ValueError("UVs changed during preparation")
    albedo = np.asarray(prepared_albedo)
    src_albedo = np.asarray(original["albedo"])
    if albedo.shape != src_albedo.shape or not np.array_equal(albedo, src_albedo):
        raise ValueError("materials/albedo changed during preparation")
    return {
        "vertexMax": max_err,
        "gate": gate,
        "bboxDiagonal": bbox_diagonal(src),
        "topologyEqual": True,
        "uvsEqual": True,
        "albedoEqual": True,
        "ok": True,
    }


def rig_gate(
    *,
    names: list[str],
    parents: np.ndarray,
    fitted: np.ndarray,
    offsets: np.ndarray,
    profile: dict[str, Any],
    helpers: list[str],
) -> dict[str, Any]:
    expected = list(profile["regionJoints"].values())
    listed = [name for group in expected for name in group]
    missing = [name for name in listed if name not in names]
    extra = [name for name in names if name not in listed]
    if missing:
        raise ValueError(f"fitted bind is missing required donor joints: {missing}")
    if extra:
        raise ValueError(f"fitted bind has unexpected joints: {extra}")
    if int((np.asarray(parents) < 0).sum()) != 1:
        raise ValueError("fitted bind must have exactly one root")
    helper_set = set(helpers)
    degenerate = []
    for index, name in enumerate(names):
        if int(parents[index]) < 0 or name in helper_set:
            continue
        if float(np.linalg.norm(offsets[index])) < 1e-8:
            degenerate.append(name)
    if degenerate:
        raise ValueError(f"degenerate articulated segments: {degenerate}")
    d_index = {name: index for index, name in enumerate(names)}
    for chain in profile["chains"]:
        if chain["kind"] != "polyline" or "wing_" not in str(chain["name"]):
            continue
        donor = list(chain["donor"])
        if len(donor) < 4:
            continue
        a = fitted[d_index[donor[2]]]
        b = fitted[d_index[donor[3]]]
        if float(np.linalg.norm(a - b)) < 1e-8:
            raise ValueError(f"{chain['name']} collapsed donor joints {donor[2]} and {donor[3]}")
    return {
        "jointCount": int(len(names)),
        "requiredBranches": list(profile["requiredBranches"]),
        "helpers": list(helpers),
        "ok": True,
    }


def weight_gate(weights: np.ndarray, vertex_count: int, joint_count: int) -> dict[str, Any]:
    values = np.asarray(weights, dtype=np.float64)
    if values.shape != (vertex_count, joint_count):
        raise ValueError(f"weights {values.shape} != ({vertex_count}, {joint_count})")
    if not np.isfinite(values).all() or np.any(values < -1e-8):
        raise ValueError("weights are not finite nonnegative")
    row = values.sum(axis=1)
    if np.any(row < 0.999) or np.any(row > 1.001):
        raise ValueError("weights are not normalized")
    return {
        "vertexCount": int(vertex_count),
        "maxInfluences": int((values > 1e-6).sum(axis=1).max()),
        "ok": True,
    }


def influence_preservation_gate(
    donor_weights: np.ndarray,
    target_weights: np.ndarray,
    names: list[str],
    helpers: list[str],
) -> dict[str, Any]:
    helper_set = set(helpers)
    lost = []
    for index, name in enumerate(names):
        if name in helper_set:
            continue
        donor_mass = float(np.asarray(donor_weights, dtype=np.float64)[:, index].sum())
        target_mass = float(np.asarray(target_weights, dtype=np.float64)[:, index].sum())
        if donor_mass >= MIN_PRESERVED_DONOR_MASS and target_mass < MIN_PRESERVED_TARGET_MASS:
            lost.append(f"{name} donorMass={donor_mass:.1f} targetMass={target_mass:.3f}")
    if lost:
        raise ValueError(f"proxy transfer dropped donor articulations: {lost}")
    return {"ok": True, "lostArticulations": []}


def export_reload_gate(
    glb_path,
    *,
    working,
    original_vertices: np.ndarray,
) -> dict[str, Any]:
    reload = reload_and_compare(glb_path, working)
    loaded = load_bind_skeleton(glb_path)
    if loaded.vertices is None:
        raise ValueError("reloaded GLB has no vertices")
    src = np.asarray(original_vertices, dtype=np.float64)
    err = float(np.linalg.norm(np.asarray(loaded.vertices) - src, axis=1).max())
    gate = preservation_limit(src)
    if err > gate:
        raise ValueError(f"exported/reloaded vertices drifted from the original: max {err} > {gate}")
    inspect = inspect_glb_animation(glb_path)
    if inspect["materialCount"] < 1 or not inspect["hasBaseColor"]:
        raise ValueError("exported GLB lost materials")
    own = own_bind_identity_gate(loaded)
    return {
        **reload,
        "originalReloadMax": err,
        "originalReloadGate": gate,
        "ownBind": own,
        "inspect": inspect,
        "ok": bool(reload["ok"] and err <= gate),
    }


def hidden_donor_absent(glb_path, visible_vertex_count: int) -> dict[str, Any]:
    loaded = load_bind_skeleton(glb_path)
    if loaded.vertices is None:
        raise ValueError("reloaded GLB has no vertices")
    if len(loaded.vertices) != visible_vertex_count:
        raise ValueError(
            f"exported GLB vertex count {len(loaded.vertices)} != visible {visible_vertex_count}; "
            "hidden donor must not be in the deliverable"
        )
    return {"hiddenDonorAbsent": True, "vertexCount": int(len(loaded.vertices))}


def deformation_preview_stats(
    rest: np.ndarray,
    posed: np.ndarray,
    triangles: np.ndarray,
) -> dict[str, float]:
    from conform_roc import triangle_distortion

    rest_n = vertex_normals(rest, triangles)
    posed_n = vertex_normals(posed, triangles)
    flip = float((np.sum(rest_n * posed_n, axis=1) < 0).mean())
    dist = triangle_distortion(rest, posed, triangles)
    before = edge_lengths(rest, triangles)
    after = edge_lengths(posed, triangles)
    ratio = after / np.maximum(before, 1e-8)
    min_len = NON_SLIVER_EDGE_FRACTION * bbox_diagonal(rest)
    non_sliver = ratio[before >= min_len]
    return {
        "normalFlipFraction": flip,
        **{key: float(value) for key, value in dist.items()},
        "nonSliverMaxEdgeRatio": float(non_sliver.max()) if len(non_sliver) else float(dist["maxEdgeRatio"]),
        "nonSliverP95EdgeRatio": float(np.quantile(non_sliver, 0.95)) if len(non_sliver) else float(dist["p95EdgeRatio"]),
        "nonSliverEdgeCount": int(len(non_sliver)),
    }


def isolated_deformation_gate(isolation: dict[str, Any]) -> dict[str, Any]:
    failed = []
    for label, item in isolation.items():
        p95 = float(item["deformation"]["nonSliverP95EdgeRatio"])
        if p95 > MAX_ISOLATED_NON_SLIVER_STRETCH:
            failed.append(f"{label} nonSliverP95EdgeRatio={p95:.3f}")
    if failed:
        raise ValueError(
            "isolated actuation stretched the mesh beyond the deformation gate: " + "; ".join(failed)
        )
    return {"ok": True, "maxIsolatedNonSliverP95": MAX_ISOLATED_NON_SLIVER_STRETCH}
