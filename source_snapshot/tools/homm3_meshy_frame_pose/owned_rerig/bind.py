"""Place species-template bones and assign geometric weights with partition walls."""

from __future__ import annotations

from typing import Any

import numpy as np

from .species import parent_index_list, required_bone_names


def template_part_names(template: dict[str, Any]) -> tuple[str, ...]:
    raw = template.get("parts")
    if not isinstance(raw, list) or not raw:
        raise ValueError("species template needs a non-empty parts list")
    names = tuple(str(item) for item in raw)
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate template parts: {names}")
    return names


def _aabb(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return points.min(axis=0), points.max(axis=0)


def _aabb_point(lo: np.ndarray, hi: np.ndarray, u: list[float]) -> np.ndarray:
    uu = np.asarray(u, dtype=np.float64)
    return lo + uu * (hi - lo)


def place_bones(
    positions: np.ndarray,
    labels: np.ndarray,
    template: dict[str, Any],
    *,
    landmarks_3d: dict[str, list[float]] | None = None,
    part_names: tuple[str, ...] | None = None,
) -> tuple[list[str], list[int | None], np.ndarray]:
    names = required_bone_names(template)
    parents = parent_index_list(template)
    parts = part_names if part_names is not None else template_part_names(template)
    part_id = {name: i for i, name in enumerate(parts)}
    part_aabb: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, pid in part_id.items():
        pts = positions[labels == pid]
        if len(pts) == 0:
            raise RuntimeError(f"no vertices labeled {name}; cannot place bones")
        part_aabb[name] = _aabb(pts)
    heads = np.zeros((len(names), 3), dtype=np.float64)
    by_name = {name: i for i, name in enumerate(names)}
    for bone in template["bones"]:
        name = str(bone["name"])
        part = str(bone["part"])
        lo, hi = part_aabb[part]
        if landmarks_3d and name in landmarks_3d:
            heads[by_name[name]] = np.asarray(landmarks_3d[name], dtype=np.float64).reshape(3)
            continue
        mode = bone.get("head") or {}
        if mode.get("mode") != "aabb":
            raise ValueError(f"bone {name} head.mode must be aabb (or provide landmarks_3d)")
        heads[by_name[name]] = _aabb_point(lo, hi, list(mode["u"]))
    return names, parents, heads


def _segment_distance(point: np.ndarray, head: np.ndarray, tail: np.ndarray) -> float:
    seg = tail - head
    length2 = float(np.dot(seg, seg))
    if length2 < 1e-12:
        return float(np.linalg.norm(point - head))
    t = max(0.0, min(1.0, float(np.dot(point - head, seg) / length2)))
    return float(np.linalg.norm(point - (head + seg * t)))


def skin_vertices(
    positions: np.ndarray,
    labels: np.ndarray,
    template: dict[str, Any],
    names: list[str],
    parents: list[int | None],
    heads: np.ndarray,
    *,
    k: int = 4,
    power: float = 10.0,
    trim: float = 0.03,
    part_names: tuple[str, ...] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    walls: dict[str, list[str]] = template["skinWalls"]
    name_index = {name: i for i, name in enumerate(names)}
    parts = part_names if part_names is not None else template_part_names(template)
    tails = np.zeros_like(heads)
    children: dict[int, list[int]] = {i: [] for i in range(len(names))}
    for i, parent in enumerate(parents):
        if parent is not None:
            children[parent].append(i)
    for i, name in enumerate(names):
        kids = children[i]
        if kids:
            tails[i] = heads[kids[0]]
        elif parents[i] is not None:
            direction = heads[i] - heads[parents[i]]
            n = np.linalg.norm(direction)
            tails[i] = heads[i] + (direction / n if n > 1e-8 else np.array([0.0, 0.0, 0.04])) * 0.04
        else:
            tails[i] = heads[i] + np.array([0.0, 0.0, 0.04])

    allowed: dict[int, list[int]] = {}
    for part, bone_names in walls.items():
        allowed[parts.index(part)] = [name_index[n] for n in bone_names]

    joints = np.zeros((len(positions), 4), dtype=np.int32)
    weights = np.zeros((len(positions), 4), dtype=np.float64)
    for vi, point in enumerate(positions):
        part = int(labels[vi])
        candidates = allowed[part]
        dists = []
        for bi in candidates:
            dists.append((_segment_distance(point, heads[bi], tails[bi]), bi))
        dists.sort(key=lambda item: item[0])
        picked = dists[: max(1, min(k, len(dists)))]
        raw = []
        for dist, bi in picked:
            w = 1.0 / ((dist + 1e-4) ** power)
            if trim > 0.0 and w < trim:
                continue
            raw.append((bi, w))
        if not raw:
            raw = [(picked[0][1], 1.0)]
        total = sum(w for _, w in raw) or 1.0
        for slot, (bi, w) in enumerate(raw[:4]):
            joints[vi, slot] = bi
            weights[vi, slot] = w / total

    bone_part: dict[int, int] = {}
    for part_id, bone_ids in allowed.items():
        for bi in bone_ids:
            bone_part[bi] = part_id
    for bi, name in enumerate(names):
        owned = np.any((joints == bi) & (weights > 0.05), axis=1)
        if np.any(owned):
            continue
        part_id = bone_part.get(bi)
        if part_id is None:
            continue
        part_verts = np.nonzero(labels == part_id)[0]
        if len(part_verts) == 0:
            raise RuntimeError(f"bone {name} has no vertices in its partition")
        pts = positions[part_verts]
        nearest = int(part_verts[int(np.argmin(np.linalg.norm(pts - heads[bi], axis=1)))])
        joints[nearest] = 0
        weights[nearest] = 0.0
        joints[nearest, 0] = bi
        weights[nearest, 0] = 1.0
    return joints, weights


def bind_species_mesh(
    positions: np.ndarray,
    labels: np.ndarray,
    template: dict[str, Any],
    *,
    landmarks_3d: dict[str, list[float]] | None = None,
    k: int = 4,
    power: float = 10.0,
    trim: float = 0.03,
) -> dict[str, Any]:
    names, parents, heads = place_bones(positions, labels, template, landmarks_3d=landmarks_3d)
    joints, weights = skin_vertices(
        positions,
        labels,
        template,
        names,
        parents,
        heads,
        k=k,
        power=power,
        trim=trim,
    )
    return {
        "boneNames": names,
        "parents": parents,
        "heads": heads,
        "joints": joints,
        "weights": weights,
    }


bind_species_mesh = bind_species_mesh
skin_vertices = skin_vertices
