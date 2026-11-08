"""Authored vertex partitions for compound meshes. No silent height-cut fallback."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "owned_bind_part_map.v1"
ALLOWED_PARTS = ("horse", "rider", "lance", "saddle_band")
METHOD = "human_eye_part_authoring"


def _parts_from_authored(authored: dict[str, Any]) -> tuple[str, ...]:
    raw = authored.get("parts")
    if raw is None:
        return ALLOWED_PARTS
    if not isinstance(raw, list) or not raw:
        raise ValueError("part map parts must be a non-empty list")
    names = tuple(str(item) for item in raw)
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate part names: {names}")
    return names


def load_part_map(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"unsupported part map schema: {path}")
    if payload.get("method") != METHOD:
        raise ValueError(f"part map method must be {METHOD}: {path}")
    return payload


def _mesh_adjacency(indices: np.ndarray, n_verts: int) -> list[set[int]]:
    adj: list[set[int]] = [set() for _ in range(n_verts)]
    faces = indices.reshape(-1, 3)
    for a, b, c in faces:
        a, b, c = int(a), int(b), int(c)
        adj[a].update((b, c))
        adj[b].update((a, c))
        adj[c].update((a, b))
    return adj


def apply_part_map(
    positions: np.ndarray,
    indices: np.ndarray,
    authored: dict[str, Any],
    *,
    min_share: dict[str, float],
    max_share: dict[str, float] | None = None,
    parts: tuple[str, ...] | None = None,
) -> np.ndarray:
    """Flood-fill labels from authored 3D seeds. Fail-closed on fused/implausible shares."""
    part_names = parts if parts is not None else _parts_from_authored(authored)
    seeds = authored.get("seeds")
    if not isinstance(seeds, list) or len(seeds) < 2:
        raise ValueError("part map needs authored 3D seeds for at least two parts")
    labels = np.full(len(positions), -1, dtype=np.int32)
    part_to_id = {name: i for i, name in enumerate(part_names)}
    seed_ids: list[tuple[int, int]] = []
    for seed in seeds:
        part = str(seed.get("part") or "")
        if part not in part_to_id:
            raise ValueError(f"unknown part in seed: {part}")
        point = np.asarray(seed["point"], dtype=np.float64).reshape(3)
        nearest = int(np.argmin(np.linalg.norm(positions - point[None, :], axis=1)))
        seed_ids.append((nearest, part_to_id[part]))

    adj = _mesh_adjacency(indices, len(positions))
    queue: deque[int] = deque()
    for vert, part_id in seed_ids:
        if labels[vert] not in (-1, part_id):
            colliding = {part_names[int(labels[vert])], part_names[part_id]}
            if colliding <= {"horse", "rider"}:
                raise RuntimeError(
                    "horse and rider seeds landed on the same connected vertex; mesh is fused (coil-weld class), stop"
                )
            raise RuntimeError(
                f"seeds for {part_names[int(labels[vert])]} and {part_names[part_id]} landed on the same vertex"
            )
        labels[vert] = part_id
        queue.append(vert)

    while queue:
        vi = queue.popleft()
        current = int(labels[vi])
        for nb in adj[vi]:
            if labels[nb] == -1:
                labels[nb] = current
                queue.append(nb)
            elif int(labels[nb]) != current:
                # frontier between parts is allowed; do not overwrite
                continue

    unlabeled = labels < 0
    if np.any(unlabeled):
        # Isolated islands (Meshy island meshes / fixture boxes): nearest authored seed.
        # Horse/rider fusion is caught at seed collision and share checks, not here.
        seed_pos = positions[[s[0] for s in seed_ids]]
        seed_parts = np.array([s[1] for s in seed_ids], dtype=np.int32)
        for vi in np.nonzero(unlabeled)[0]:
            dist = np.linalg.norm(seed_pos - positions[vi], axis=1)
            labels[vi] = seed_parts[int(np.argmin(dist))]

    counts = {name: float(np.mean(labels == part_to_id[name])) for name in part_names}
    for name, minimum in min_share.items():
        if counts.get(name, 0.0) < float(minimum):
            raise RuntimeError(f"part {name} share {counts.get(name, 0.0):.4f} < min {minimum}")
    if max_share:
        for name, maximum in max_share.items():
            if counts.get(name, 0.0) > float(maximum):
                raise RuntimeError(f"part {name} share {counts.get(name, 0.0):.4f} > max {maximum}")
    authored_counts = authored.get("expectedShare")
    if isinstance(authored_counts, dict):
        for name, expected in authored_counts.items():
            # authorship may pin expected ranges; still fail closed if far off
            if abs(counts.get(name, 0.0) - float(expected)) > 0.35:
                raise RuntimeError(f"part {name} share {counts.get(name, 0.0):.4f} disagrees with authored {expected}")
    return labels


def labels_to_names(labels: np.ndarray, parts: tuple[str, ...] | None = None) -> list[str]:
    names = parts if parts is not None else ALLOWED_PARTS
    return [names[int(i)] for i in labels]


load_part_map = load_part_map
apply_part_map = apply_part_map
ALLOWED_PARTS = ALLOWED_PARTS
load_part_map = load_part_map
apply_part_map = apply_part_map
