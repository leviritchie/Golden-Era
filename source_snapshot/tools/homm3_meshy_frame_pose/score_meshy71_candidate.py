#!/usr/bin/env python3
"""Run a cheap geometry preflight for a Meshy 7.1 candidate.

This deliberately does not score a bind. It distinguishes exporter-created
duplicate-position boundaries from genuine open/non-manifold geometry and emits
the measurements needed before spending time on owned binding. A candidate is
never promoted by this report; deformation proof requires the reference replay.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.glb_io import load_render_surface

SCHEMA = "meshy71.geometry_preflight.v1"


def _edge_counts(indices: np.ndarray) -> Counter[tuple[int, int]]:
    counts: Counter[tuple[int, int]] = Counter()
    for tri in indices.reshape(-1, 3):
        a, b, c = (int(value) for value in tri)
        for left, right in ((a, b), (b, c), (c, a)):
            counts[tuple(sorted((left, right)))] += 1
    return counts


def _position_ids(points: np.ndarray) -> tuple[np.ndarray, int]:
    keys = [tuple(float(value) for value in row) for row in points]
    lookup: dict[tuple[float, float, float], int] = {}
    ids = np.empty(len(keys), dtype=np.int64)
    for index, key in enumerate(keys):
        ids[index] = lookup.setdefault(key, len(lookup))
    return ids, len(lookup)


def _components(indices: np.ndarray, vertex_count: int) -> list[int]:
    graph: dict[int, set[int]] = defaultdict(set)
    for tri in indices.reshape(-1, 3):
        a, b, c = (int(value) for value in tri)
        graph[a].update((b, c))
        graph[b].update((a, c))
        graph[c].update((a, b))
    seen: set[int] = set()
    sizes: list[int] = []
    for start in range(vertex_count):
        if start in seen or start not in graph:
            continue
        queue = deque([start])
        seen.add(start)
        count = 0
        while queue:
            node = queue.popleft()
            count += 1
            for neighbour in graph[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        sizes.append(count)
    return sorted(sizes, reverse=True)


def inspect(path: Path) -> dict:
    surface = load_render_surface(path)
    points = np.asarray(surface["positions"], dtype=np.float64)
    indices = np.asarray(surface["indices"], dtype=np.int64).reshape(-1, 3)
    if not np.isfinite(points).all():
        raise SystemExit(f"fail-closed: non-finite positions in {path}")
    raw_edges = _edge_counts(indices)
    position_ids, position_count = _position_ids(points)
    welded_indices = position_ids[indices]
    welded_edges = _edge_counts(welded_indices)
    raw_boundary = sum(count == 1 for count in raw_edges.values())
    raw_non_manifold = sum(count > 2 for count in raw_edges.values())
    welded_boundary = sum(count == 1 for count in welded_edges.values())
    welded_non_manifold = sum(count > 2 for count in welded_edges.values())
    components = _components(welded_indices, position_count)
    extent = points.max(axis=0) - points.min(axis=0)
    height = float(extent[1])
    return {
        "schema": SCHEMA,
        "mesh": str(path.resolve()).replace("\\", "/"),
        "vertices": int(len(points)),
        "triangles": int(len(indices)),
        "exactPositionNodes": int(position_count),
        "duplicatePositionFraction": float(1.0 - position_count / max(len(points), 1)),
        "raw": {"boundaryEdges": int(raw_boundary), "nonManifoldEdges": int(raw_non_manifold)},
        "welded": {
            "boundaryEdges": int(welded_boundary),
            "nonManifoldEdges": int(welded_non_manifold),
            "componentCount": int(len(components)),
            "componentVertexCounts": components[:20],
        },
        "extent": [float(value) for value in extent],
        "spanOverHeight": float(extent[0] / height) if height > 1e-12 else None,
        "depthOverHeight": float(extent[2] / height) if height > 1e-12 else None,
        "classification": {
            "rawBoundaryLikelyExporterSplits": bool(raw_boundary > welded_boundary * 4 and welded_boundary < raw_boundary),
            "genuineOpenSurface": bool(welded_boundary > 0),
            "genuineNonManifoldSurface": bool(welded_non_manifold > 0),
            "requiresOwnedBindAudit": True,
        },
        "proof": "geometry preflight only; no bind or runtime proof",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.mesh)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
