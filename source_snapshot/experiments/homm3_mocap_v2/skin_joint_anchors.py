"""CPU-only mesh-anchor diagnostics for fixed joint trajectories."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize


def _skin_arrays(skin):
    required = ("vertices", "triangles", "weights", "names", "parents", "inverseBind")
    if not isinstance(skin, dict) or any(key not in skin for key in required):
        raise ValueError("skin is missing required arrays")
    vertices = np.asarray(skin["vertices"], dtype=np.float64)
    triangles = np.asarray(skin["triangles"])
    weights = np.asarray(skin["weights"], dtype=np.float64)
    names = np.asarray(skin["names"]).astype(str)
    parents = np.asarray(skin["parents"])
    inverse_bind = np.asarray(skin["inverseBind"], dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite [V,3]")
    if (triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer)
            or np.any(triangles < 0) or np.any(triangles >= len(vertices))):
        raise ValueError("triangles must be valid integer [F,3]")
    if (weights.shape != (len(vertices), len(names)) or not np.isfinite(weights).all()
            or np.any(weights < 0) or not np.allclose(weights.sum(1), 1, atol=1e-6, rtol=0)):
        raise ValueError("weights must be finite normalized [V,J]")
    if (len(np.unique(names)) != len(names) or parents.shape != (len(names),)
            or not np.issubdtype(parents.dtype, np.integer)
            or np.any((parents < -1) | (parents >= len(names)))
            or inverse_bind.shape != (len(names), 4, 4)
            or not np.isfinite(inverse_bind).all()):
        raise ValueError("names/parents/inverseBind are malformed")
    return vertices, triangles.astype(np.int64), weights, names, parents, inverse_bind


def _affine_nnls(points, target):
    if not len(points):
        return None, None, "no_support_points"
    matrix = np.vstack((points.T, np.ones((1, len(points)))))
    desired = np.r_[target, 1.0]
    initial = np.full(len(points), 1.0 / len(points))
    result = minimize(lambda x: float(np.sum((matrix @ x - desired) ** 2)), initial,
                      method="SLSQP", bounds=[(0.0, None)] * len(points),
                      constraints={"type": "eq", "fun": lambda x: float(x.sum() - 1.0)},
                      options={"ftol": 1e-12, "maxiter": 1000})
    if not result.success or not np.isfinite(result.x).all():
        return None, None, "affine_nnls_failed"
    values = np.maximum(result.x, 0.0)
    values /= values.sum()
    return values, float(np.linalg.norm(points.T @ values - target)), None


def _body_support(skin, prop_mask, chain_name, routing):
    vertices, _, _, _, _, _ = _skin_arrays(skin)
    prop = np.asarray(prop_mask)
    regions = np.asarray(skin.get("regions"))
    if prop.shape != (len(vertices),) or prop.dtype != np.bool_ or regions.shape != (len(vertices),):
        raise ValueError("prop_mask and skin regions must be boolean/string [V]")
    labels = regions.astype(str)
    effective = {chain_name}
    if routing is not None:
        if not isinstance(routing, dict):
            raise ValueError("body_region_routing must be a mapping")
        for label, evidence in routing.items():
            if not isinstance(label, str) or not isinstance(evidence, dict):
                raise ValueError("body_region_routing is malformed")
            if evidence.get("chain") == chain_name:
                effective.add(label)
    ids = np.flatnonzero((~prop) & np.isin(labels, sorted(effective)))
    unique = {}
    for index in ids:
        unique.setdefault(tuple(vertices[int(index)].tolist()), int(index))
    return np.asarray(sorted(unique.values()), dtype=np.int64)


def build_anchors(skin: dict[str, Any], prop_mask: Any, profile: dict[str, Any],
                  chain_regions: Any, body_region_routing: dict[str, Any] | None = None,
                  *, max_points: int = 32, residual_fraction: float = 0.05) -> dict[str, Any]:
    """Build a JSON-serializable fixed-rest anchor model; never invent support."""
    vertices, _, _, names, parents, inverse_bind = _skin_arrays(skin)
    if (not isinstance(chain_regions, (tuple, list)) or not chain_regions
            or any(not isinstance(region, str) or not region for region in chain_regions)
            or len(set(chain_regions)) != len(chain_regions)):
        raise ValueError("chain_regions must be a non-empty unique sequence")
    if (isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 1
            or not np.isfinite(residual_fraction) or residual_fraction <= 0):
        raise ValueError("invalid anchor limits")
    joint_rest = np.linalg.inv(inverse_bind)[:, :3, 3]
    chains = {}
    for region in chain_regions:
        matches = [chain for chain in profile.get("chains", ())
                   if chain.get("name") == region and chain.get("kind") == "polyline"]
        if len(matches) != 1:
            raise ValueError("each chain region must name one profile polyline")
        donor = matches[0].get("donor", ())
        if not isinstance(donor, (tuple, list)) or len(donor) < 2 or any(name not in names for name in donor):
            raise ValueError("chain donor joints are invalid")
        joint_ids = [int(np.flatnonzero(names == name)[0]) for name in donor]
        if len(set(joint_ids)) != len(joint_ids) or np.any(parents[joint_ids[1:]] != joint_ids[:-1]):
            raise ValueError("chain donor joints must be unique direct-parent links")
        support = _body_support(skin, prop_mask, region, body_region_routing)
        segment_lengths = np.linalg.norm(np.diff(joint_rest[joint_ids], axis=0), axis=1)
        joints = {}
        for position, joint_id in enumerate(joint_ids):
            nearest = support[np.argsort(np.linalg.norm(vertices[support] - joint_rest[joint_id], axis=1))[:max_points]]
            values, residual, reason = _affine_nnls(vertices[nearest], joint_rest[joint_id])
            adjacent_length = float(segment_lengths[0 if position == 0 else position - 1])
            limit = adjacent_length * residual_fraction
            if len(nearest):
                singular = np.linalg.svd(vertices[nearest] - vertices[nearest].mean(axis=0), compute_uv=False)
                rank = int(np.count_nonzero(singular > max(1e-12, singular[0] * 1e-8)))
                condition = None if not len(singular) or singular[-1] <= 1e-12 else float(singular[0] / singular[-1])
            else:
                rank, condition = 0, None
            item = {"vertexIds": nearest.astype(int).tolist(),
                    "coefficients": None if values is None else values.tolist(),
                    "restResidual": residual, "restResidualLimit": limit,
                    "adjacentSegmentLength": adjacent_length,
                    "restResidualFraction": None if residual is None else float(residual / adjacent_length),
                    "supportRank": rank, "supportConditionNumber": condition,
                    "supported": bool(values is not None and residual <= limit)}
            if reason:
                item["unsupportedReason"] = reason
            joints[str(joint_id)] = item
        chains[region] = {"jointNames": list(donor), "jointIds": joint_ids,
                          "supportVertexCount": int(len(support)), "joints": joints,
                          "supported": all(item["supported"] for item in joints.values())}
    return {"schema": "skin-joint-anchor-model-v1", "maxPoints": max_points,
            "residualFraction": float(residual_fraction), "chains": chains,
            "jointNames": names.tolist(), "jointRestPositions": joint_rest.tolist(),
            "accepted": False}


def evaluate_anchors(model: dict[str, Any], posed_mesh: Any, joint_world: Any,
                     clip_slices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare anchor trajectories against fixed joint-world origins."""
    if not isinstance(model, dict) or model.get("schema") != "skin-joint-anchor-model-v1":
        raise ValueError("invalid anchor model")
    names = model.get("jointNames")
    rest_positions = np.asarray(model.get("jointRestPositions"), dtype=np.float64)
    if (not isinstance(names, list) or len(names) == 0 or rest_positions.shape != (len(names), 3)
            or not np.isfinite(rest_positions).all() or not isinstance(model.get("chains"), dict)):
        raise ValueError("anchor model joint inventory is malformed")
    matrices = np.asarray(joint_world, dtype=np.float64)
    if (matrices.ndim != 4 or matrices.shape[1:] != (len(names), 4, 4)
            or not np.isfinite(matrices).all()):
        raise ValueError("joint_world must be finite [F,J,4,4]")
    meshes = posed_mesh if isinstance(posed_mesh, dict) else {"mesh": posed_mesh}
    for key, mesh in meshes.items():
        array = np.asarray(mesh, dtype=np.float64)
        if array.ndim != 3 or array.shape[0] != len(matrices) or array.shape[2] != 3 or not np.isfinite(array).all():
            raise ValueError(f"posed mesh {key} must be finite [F,V,3]")
        for chain in model["chains"].values():
            if not isinstance(chain, dict) or not isinstance(chain.get("joints"), dict):
                raise ValueError("anchor model chain is malformed")
            for joint_text, anchor in chain["joints"].items():
                joint_id = int(joint_text)
                if not 0 <= joint_id < len(names) or not isinstance(anchor, dict):
                    raise ValueError("anchor model joint is malformed")
                ids = np.asarray(anchor.get("vertexIds"), dtype=np.int64)
                coeff = np.asarray(anchor.get("coefficients"), dtype=np.float64)
                if anchor.get("supported"):
                    if (ids.ndim != 1 or coeff.shape != ids.shape or not len(ids)
                            or np.any(ids < 0) or np.any(ids >= array.shape[1])
                            or not np.isfinite(coeff).all() or np.any(coeff < 0)
                            or not np.isclose(coeff.sum(), 1.0, atol=1e-6, rtol=0)):
                        raise ValueError("supported anchor has malformed support")
    slices = clip_slices or {"all": (0, len(matrices))}
    if not isinstance(slices, dict) or not slices:
        raise ValueError("clip_slices must be a non-empty mapping")
    intervals = []
    for clip, bounds in slices.items():
        start, end = (int(bounds.start), int(bounds.stop)) if isinstance(bounds, slice) else tuple(map(int, bounds))
        if not 0 <= start < end <= len(matrices):
            raise ValueError("clip slices must be non-empty and in range")
        intervals.append((start, end, clip))
    intervals.sort()
    if intervals[0][0] != 0 or any(left[1] != right[0] for left, right in zip(intervals, intervals[1:])) or intervals[-1][1] != len(matrices):
        raise ValueError("clip slices must be disjoint and cover the trajectory")
    report = {"schema": "skin-joint-anchor-evaluation-v1", "clips": {}, "accepted": False}
    for clip, bounds in slices.items():
        start, end = next((a, b) for a, b, name in intervals if name == clip)
        clip_report = {}
        for mesh_name, mesh in meshes.items():
            errors = []
            for chain in model["chains"].values():
                for joint_text, anchor in chain["joints"].items():
                    if not anchor["supported"]:
                        continue
                    joint_id = int(joint_text)
                    ids = np.asarray(anchor["vertexIds"], dtype=np.int64)
                    coeff = np.asarray(anchor["coefficients"], dtype=np.float64)
                    mesh_anchor = np.einsum("v,fvC->fC", coeff, mesh[start:end, ids])
                    rest = np.asarray(model["jointRestPositions"][joint_id], dtype=np.float64)
                    target = matrices[start:end, joint_id, :3, 3]
                    errors.extend(np.linalg.norm(mesh_anchor - target, axis=1).tolist())
                    joint_error = np.linalg.norm(mesh_anchor - target, axis=1)
                    clip_report.setdefault(mesh_name, {}).setdefault("joints", {})[joint_text] = {
                        "anchorCount": int(len(joint_error)), "meanError": float(np.mean(joint_error)),
                        "maxError": float(np.max(joint_error))}
            summary = clip_report.setdefault(mesh_name, {})
            summary.update({"anchorCount": len(errors),
                                      "meanError": None if not errors else float(np.mean(errors)),
                                      "maxError": None if not errors else float(np.max(errors))})
        report["clips"][clip] = clip_report
    return report


__all__ = ["build_anchors", "evaluate_anchors"]
