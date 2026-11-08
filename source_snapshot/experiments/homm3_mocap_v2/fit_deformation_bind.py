"""Fit a donor joint graph into the original target bind. Identities stay; lengths change."""
from __future__ import annotations

from typing import Any

import numpy as np

from donor_eagle import compute_rest_joints
from mesh_preview import rotation_between


class BindFitError(ValueError):
    pass


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-8:
        return np.zeros(3, dtype=np.float64)
    return values / norm


def _polyline_arclength(points: np.ndarray) -> tuple[np.ndarray, float]:
    path = np.asarray(points, dtype=np.float64)
    if path.ndim != 2 or path.shape[1] != 3 or path.shape[0] < 1:
        raise BindFitError(f"polyline must be [N>=1,3], got {path.shape}")
    if path.shape[0] == 1:
        return np.zeros(1, dtype=np.float64), 0.0
    lengths = np.linalg.norm(path[1:] - path[:-1], axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    total = float(cumulative[-1])
    if total <= 1e-8:
        return np.zeros(len(path), dtype=np.float64), 0.0
    return cumulative / total, total


def _point_at_fraction(points: np.ndarray, fraction: float) -> np.ndarray:
    path = np.asarray(points, dtype=np.float64)
    amount = float(np.clip(fraction, 0.0, 1.0))
    if len(path) == 1:
        return path[0].copy()
    lengths = np.linalg.norm(path[1:] - path[:-1], axis=1)
    total = float(lengths.sum())
    if total <= 1e-8:
        return path[0].copy()
    target = amount * total
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    segment = int(np.searchsorted(cumulative, target, side="right") - 1)
    segment = min(max(segment, 0), len(lengths) - 1)
    span = float(lengths[segment])
    if span <= 1e-8:
        return path[segment].copy()
    alpha = (target - float(cumulative[segment])) / span
    return path[segment] + alpha * (path[segment + 1] - path[segment])


def _bone_frame(direction: np.ndarray, hint: np.ndarray) -> np.ndarray:
    axis = _unit(direction)
    if float(np.linalg.norm(axis)) < 1e-8:
        return np.eye(3, dtype=np.float64)
    binormal = np.cross(_unit(hint), axis)
    if float(np.linalg.norm(binormal)) < 1e-6:
        binormal = np.cross(np.array((1.0, 0.0, 0.0), dtype=np.float64), axis)
    if float(np.linalg.norm(binormal)) < 1e-6:
        binormal = np.cross(np.array((0.0, 0.0, 1.0), dtype=np.float64), axis)
    binormal = _unit(binormal)
    normal = np.cross(axis, binormal)
    return np.stack((axis, binormal, normal), axis=1)


def _region_hint(vertices: np.ndarray, mask: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    pts = np.asarray(vertices, dtype=np.float64)[mask]
    if len(pts) < 3:
        return _unit(fallback)
    centered = pts - pts.mean(0)
    _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
    return _unit(vh[1] if len(vh) > 1 else vh[0])


def _clamp_to_bbox(point: np.ndarray, bbox_min: np.ndarray, bbox_max: np.ndarray) -> tuple[np.ndarray, bool]:
    clamped = np.minimum(np.maximum(point, bbox_min), bbox_max)
    moved = float(np.linalg.norm(clamped - point)) > 1e-8
    return clamped, moved


def _offsets_from_positions(positions: np.ndarray, parents: np.ndarray) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    offsets = np.zeros_like(values)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            offsets[index] = values[index]
        else:
            offsets[index] = values[index] - values[int(parent_index)]
    return offsets


def fit_deformation_bind(
    *,
    donor_names: list[str],
    donor_parents: np.ndarray,
    donor_rest: np.ndarray,
    target_names: list[str],
    target_rest: np.ndarray,
    target_vertices: np.ndarray,
    target_regions: np.ndarray,
    profile: dict[str, Any],
) -> dict[str, Any]:
    names = list(donor_names)
    parent = np.asarray(donor_parents, dtype=np.int64)
    donor = np.asarray(donor_rest, dtype=np.float64)
    target = np.asarray(target_rest, dtype=np.float64)
    if len(names) != len(parent) or donor.shape != (len(names), 3):
        raise BindFitError("donor rest does not match names/parents")
    d_index = {name: index for index, name in enumerate(names)}
    t_index = {name: index for index, name in enumerate(target_names)}
    fitted = np.full((len(names), 3), np.nan, dtype=np.float64)
    notes: list[dict[str, Any]] = []
    helpers: list[str] = []
    limitations: list[str] = []
    authored_positions: dict[str, np.ndarray] = {}

    for donor_joint, target_bone in profile["hubs"].items():
        if donor_joint not in d_index:
            raise BindFitError(f"hub {donor_joint!r} is missing from the donor")
        if target_bone not in t_index:
            raise BindFitError(f"hub evidence {target_bone!r} is missing from the target")
        fitted[d_index[donor_joint]] = target[t_index[target_bone]]
        notes.append({"joint": donor_joint, "kind": "hub", "evidence": target_bone})

    region_bbox: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for region in sorted(set(np.asarray(target_regions).tolist())):
        mask = np.asarray(target_regions) == region
        pts = np.asarray(target_vertices, dtype=np.float64)[mask]
        if len(pts) == 0:
            continue
        region_bbox[str(region)] = (pts.min(0), pts.max(0))

    def _require_placed(joint: str) -> int:
        index = d_index[joint]
        if not np.isfinite(fitted[index]).all():
            raise BindFitError(f"parent {joint!r} is not placed yet")
        return index

    for chain in profile["chains"]:
        kind = str(chain["kind"])
        donor_chain = tuple(chain["donor"])
        if kind == "authored_positions":
            source_hash = chain.get("sourceMeshSha256")
            if (not isinstance(source_hash, str) or len(source_hash) != 64
                    or any(c not in "0123456789abcdef" for c in source_hash)
                    or source_hash != profile.get("expectedMeshSha256")):
                raise BindFitError("authored positions require the exact pinned source mesh hash")
            if chain.get("coordinateSpace") != "target_mesh_space":
                raise BindFitError("authored positions require target_mesh_space coordinates")
            if not isinstance(chain.get("evidence"), str) or not chain["evidence"].strip():
                raise BindFitError("authored positions require explicit review evidence")
            if (not donor_chain or len(set(donor_chain)) != len(donor_chain)
                    or any(joint not in d_index for joint in donor_chain)):
                raise BindFitError("authored positions require unique known donor joints")
            try:
                raw_points = np.asarray(chain.get("positions"))
            except (TypeError, ValueError) as exc:
                raise BindFitError("authored positions require rectangular numeric coordinates") from exc
            if raw_points.dtype.kind not in "fiu":
                raise BindFitError("authored positions require numeric coordinates")
            points = raw_points.astype(np.float64)
            if points.shape != (len(donor_chain), 3) or not np.isfinite(points).all():
                raise BindFitError("authored positions must be finite [N,3] coordinates")
            vertices = np.asarray(target_vertices, dtype=np.float64)
            if (vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices)
                    or not np.isfinite(vertices).all()):
                raise BindFitError("authored positions require a finite source surface")
            if np.any(points < vertices.min(0) - 1e-8) or np.any(points > vertices.max(0) + 1e-8):
                raise BindFitError("authored positions are outside the source bounds; no implicit clamp")
            for joint, point in zip(donor_chain, points):
                if np.isfinite(fitted[d_index[joint]]).any():
                    raise BindFitError(f"authored position would overwrite placed joint {joint}")
                fitted[d_index[joint]] = point
                authored_positions[joint] = point.copy()
            notes.append({"chain": chain["name"], "kind": kind, "donor": list(donor_chain),
                          "positions": points.tolist(), "coordinateSpace": "target_mesh_space",
                          "sourceMeshSha256": source_hash, "evidence": chain["evidence"]})
            continue
        if kind == "paired_landmarks":
            evidence = tuple(chain["evidence"])
            if not donor_chain or len(donor_chain) != len(evidence):
                raise BindFitError(f"chain {chain['name']} requires one target landmark per donor joint")
            if len(set(donor_chain)) != len(donor_chain) or len(set(evidence)) != len(evidence):
                raise BindFitError(f"chain {chain['name']} repeats a paired landmark")
            for joint, source_bone in zip(donor_chain, evidence):
                if joint not in d_index or source_bone not in t_index:
                    raise BindFitError(f"chain {chain['name']} has an unknown paired landmark")
                fitted[d_index[joint]] = target[t_index[source_bone]]
            notes.append({"chain": chain["name"], "kind": kind,
                          "donor": list(donor_chain), "evidence": list(evidence)})
            continue
        if kind == "polyline":
            evidence = tuple(chain["evidence"])
            src = np.stack([donor[d_index[name]] for name in donor_chain])
            dst = np.stack([target[t_index[name]] for name in evidence])
            src_frac, _src_len = _polyline_arclength(src)
            if float(np.linalg.norm(dst[0] - dst[-1])) < 1e-8 and len(dst) < 2:
                raise BindFitError(f"chain {chain['name']} evidence is degenerate")
            for name, fraction in zip(donor_chain, src_frac):
                fitted[d_index[name]] = _point_at_fraction(dst, float(fraction))
            notes.append(
                {
                    "joint": donor_chain[0],
                    "kind": "polyline",
                    "chain": chain["name"],
                    "evidence": list(evidence),
                    "donorFractions": src_frac.tolist(),
                }
            )
            continue
        if kind == "fork":
            parent_name = str(chain["parent"])
            primary_name = str(chain["primary"])
            parent_i = _require_placed(parent_name)
            primary_i = _require_placed(primary_name)
            donor_primary = donor[d_index[primary_name]] - donor[d_index[parent_name]]
            target_primary = fitted[primary_i] - fitted[parent_i]
            scale = float(np.linalg.norm(target_primary) / max(float(np.linalg.norm(donor_primary)), 1e-12))
            region = str(chain.get("region") or "")
            hint_donor = donor[d_index[donor_chain[0]]] - donor[d_index[parent_name]]
            if float(np.linalg.norm(np.cross(_unit(donor_primary), hint_donor))) < 1e-6 and len(donor_chain) > 1:
                hint_donor = donor[d_index[donor_chain[-1]]] - donor[d_index[parent_name]]
            hint_target = _region_hint(
                target_vertices,
                np.asarray(target_regions) == region if region else np.ones(len(target_vertices), dtype=bool),
                target_primary,
            )
            src_frame = _bone_frame(donor_primary, hint_donor)
            dst_frame = _bone_frame(target_primary, hint_target)
            for name in donor_chain:
                local = src_frame.T @ (donor[d_index[name]] - donor[d_index[parent_name]])
                point = fitted[parent_i] + dst_frame @ (scale * local)
                clamped = False
                if region in region_bbox:
                    point, clamped = _clamp_to_bbox(point, *region_bbox[region])
                fitted[d_index[name]] = point
                if chain.get("helper"):
                    helpers.append(name)
                if clamped:
                    limitations.append(f"{name} clamped into {region} bbox; trailing chain may be under-supported")
            notes.append({"joint": donor_chain[0], "kind": "fork", "chain": chain["name"], "scale": scale})
            continue
        if kind == "relative_to_parent":
            anchor = str(chain["anchor"])
            anchor_i = _require_placed(anchor)
            region = str(chain.get("region") or "")
            parent_of_anchor = int(parent[d_index[anchor]])
            if parent_of_anchor < 0:
                raise BindFitError(f"relative chain {chain['name']} anchor has no parent")
            _require_placed(names[parent_of_anchor])
            donor_axis = donor[d_index[anchor]] - donor[parent_of_anchor]
            target_axis = fitted[anchor_i] - fitted[parent[d_index[anchor]]]
            scale = float(np.linalg.norm(target_axis) / max(float(np.linalg.norm(donor_axis)), 1e-12))
            rot = rotation_between(donor_axis, target_axis)
            for name in donor_chain:
                src_parent = int(parent[d_index[name]])
                if src_parent < 0 or not np.isfinite(fitted[src_parent]).all():
                    raise BindFitError(f"{name} parent is not placed")
                delta = donor[d_index[name]] - donor[src_parent]
                point = fitted[src_parent] + rot @ (scale * delta)
                clamped = False
                if region in region_bbox:
                    point, clamped = _clamp_to_bbox(point, *region_bbox[region])
                fitted[d_index[name]] = point
                if chain.get("helper"):
                    helpers.append(name)
                if clamped:
                    limitations.append(f"{name} clamped into {region} bbox")
            notes.append({"joint": donor_chain[0], "kind": "relative_to_parent", "chain": chain["name"], "scale": scale})
            continue
        if kind == "toward_region":
            parent_name = str(chain["parent"])
            parent_i = _require_placed(parent_name)
            region = str(chain["region"])
            mask = np.asarray(target_regions) == region
            if not np.any(mask):
                raise BindFitError(f"toward_region {chain['name']} has no {region} vertices")
            centroid = np.asarray(target_vertices, dtype=np.float64)[mask].mean(0)
            for name in donor_chain:
                donor_len = float(np.linalg.norm(donor[d_index[name]] - donor[d_index[parent_name]]))
                direction = centroid - fitted[parent_i]
                span = float(np.linalg.norm(direction))
                if span <= 1e-8:
                    fitted[d_index[name]] = fitted[parent_i]
                else:
                    step = donor_len
                    target_span = 0.55 * span
                    fitted[d_index[name]] = fitted[parent_i] + _unit(direction) * min(step * (span / max(donor_len, 1e-8)), target_span)
                if chain.get("helper"):
                    helpers.append(name)
            notes.append({"joint": donor_chain[0], "kind": "toward_region", "chain": chain["name"], "region": region})
            continue
        raise BindFitError(f"unknown chain kind {kind!r}")

    for joint, point in authored_positions.items():
        if not np.array_equal(fitted[d_index[joint]], point):
            raise BindFitError(f"a later chain overwrote authored position {joint}")
    missing = [name for name, index in d_index.items() if not np.isfinite(fitted[index]).all()]
    if missing:
        raise BindFitError(f"unplaced joints: {missing}")

    swaps = []
    for pair in profile["leftRightPairs"]:
        left_d, right_d = pair["donor"]
        left_t, right_t = pair["evidence"]
        left_fit = fitted[d_index[left_d]]
        right_fit = fitted[d_index[right_d]]
        left_ev = target[t_index[left_t]]
        right_ev = target[t_index[right_t]]
        if float(np.linalg.norm(left_fit - left_ev)) >= float(np.linalg.norm(left_fit - right_ev)):
            swaps.append(f"{left_d} is closer to {right_t} than to {left_t}")
        if float(np.linalg.norm(right_fit - right_ev)) >= float(np.linalg.norm(right_fit - left_ev)):
            swaps.append(f"{right_d} is closer to {left_t} than to {right_t}")
    if swaps:
        raise BindFitError(f"left/right swap: {swaps}")

    offsets = _offsets_from_positions(fitted, parent)
    recomputed = compute_rest_joints(offsets, parent)
    recon_err = float(np.linalg.norm(recomputed - fitted, axis=1).max())
    if recon_err > 1e-8:
        raise BindFitError(f"fitted offsets do not reconstruct positions: {recon_err}")

    bbox = float(np.linalg.norm(np.asarray(target_vertices).max(0) - np.asarray(target_vertices).min(0)))
    lengths = np.linalg.norm(offsets, axis=1)
    lengths[0] = 0.0
    degenerate = []
    helper_set = set(helpers)
    for index, name in enumerate(names):
        if int(parent[index]) < 0:
            continue
        if name in helper_set:
            continue
        if float(lengths[index]) < 1e-6 * max(bbox, 1.0):
            degenerate.append(name)
    if degenerate:
        raise BindFitError(f"degenerate articulated segments: {degenerate}")

    unique_positions = len({tuple(np.round(row, 6)) for row in fitted})
    return {
        "names": names,
        "parents": parent,
        "fittedPositions": fitted,
        "offsets": offsets,
        "helpers": sorted(set(helpers)),
        "limitations": limitations,
        "notes": notes,
        "spaces": {
            "deformationBind": "target_mesh_space_identity_local_rotation",
            "captureBind": "donor_offset_tpose_immutable",
            "notClipFrame0": True,
        },
        "uniqueRoundedPositions": int(unique_positions),
        "ok": True,
    }
