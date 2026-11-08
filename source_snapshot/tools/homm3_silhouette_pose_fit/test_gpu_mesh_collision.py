"""Self-collision pair sampling: distant/island contacts, not rest armpits."""
from __future__ import annotations

import numpy as np

from gpu_depth_silhouette_solver import DepthSilhouetteConfig
from gpu_mesh_collision import (
    bind_extent_length,
    build_mesh_collision_pairs,
    collision_margin_from_bind,
    pair_collision_error,
)


def _grid_and_island() -> tuple[np.ndarray, np.ndarray]:
    """Connected patch plus a detached prop triangle."""
    width = 5
    patch = np.array(
        [[float(x), float(y), 0.0] for y in range(width) for x in range(width)],
        dtype=np.float64,
    )
    island = np.array(
        [[20.0, 0.0, 0.0], [21.0, 0.0, 0.0], [20.0, 1.0, 0.0]],
        dtype=np.float64,
    )
    vertices = np.concatenate((patch, island), axis=0)
    faces = []
    for row in range(width - 1):
        for col in range(width - 1):
            origin = row * width + col
            faces.append((origin, origin + 1, origin + width))
            faces.append((origin + 1, origin + 1 + width, origin + width))
    offset = width * width
    faces.append((offset, offset + 1, offset + 2))
    return vertices, np.asarray(faces, dtype=np.int64)


def _uv_split_connected_strip() -> tuple[np.ndarray, np.ndarray]:
    """One connected strip whose triangles do not share vertex indices."""
    positions: list[list[float]] = []
    faces: list[tuple[int, int, int]] = []
    for index in range(4):
        base = len(positions)
        positions.extend(
            (
                [float(index), 0.0, 0.0],
                [float(index + 1), 0.0, 0.0],
                [float(index), 1.0, 0.0],
                [float(index + 1), 1.0, 0.0],
            )
        )
        faces.append((base, base + 1, base + 2))
        faces.append((base + 1, base + 3, base + 2))
    return np.asarray(positions, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def run() -> dict[str, object]:
    DepthSilhouetteConfig().validate()
    DepthSilhouetteConfig(collision_enabled=False, collision_weight=0.0).validate()
    try:
        DepthSilhouetteConfig(collision_enabled=True, collision_weight=0.0).validate()
        raise AssertionError("collision_enabled with weight 0 must stay fail-closed")
    except ValueError as exc:
        assert "collision_weight must be positive" in str(exc), str(exc)

    vertices, faces = _grid_and_island()
    margin = collision_margin_from_bind(vertices, 0.04)
    assert 4.0 < bind_extent_length(vertices) < 30.0, bind_extent_length(vertices)
    table = build_mesh_collision_pairs(
        triangles=faces,
        bind_positions=vertices,
        sample_count=8,
        geodesic_min_hops=8,
        margin=margin,
    )
    assert table.pair_count >= 1, table.to_dict()
    assert table.cross_component_pairs >= 1, table.to_dict()
    assert int(table.welded_island_count) >= 2, table.to_dict()

    split_vertices, split_faces = _uv_split_connected_strip()
    split_table = build_mesh_collision_pairs(
        triangles=split_faces,
        bind_positions=split_vertices,
        sample_count=8,
        geodesic_min_hops=2,
        margin=0.05,
    )
    assert int(split_table.raw_island_count) == 4, split_table.to_dict()
    assert int(split_table.welded_island_count) == 1, split_table.to_dict()
    assert int(split_table.sample_count) <= 8, split_table.to_dict()
    assert int(split_table.cross_component_pairs) == 0, split_table.to_dict()

    samples = vertices[table.sample_vertices]
    pair_bind = np.linalg.norm(samples[table.pairs[:, 0]] - samples[table.pairs[:, 1]], axis=1)
    assert np.all(pair_bind >= table.margin - 1e-9), pair_bind.min()
    bind_error = float(pair_collision_error(samples, table.pairs, table.margin)[0])
    assert bind_error < 1e-9, bind_error

    i, j = (int(table.pairs[0, 0]), int(table.pairs[0, 1]))
    clipped = samples.copy()
    clipped[i] = clipped[j]
    clip_error = float(pair_collision_error(clipped, table.pairs, table.margin)[0])
    assert clip_error > 0.5, clip_error

    close_island = vertices.copy()
    close_island[-3:] = np.array(
        [[0.01, 0.01, 0.0], [0.02, 0.01, 0.0], [0.01, 0.02, 0.0]],
        dtype=np.float64,
    )
    try:
        close_table = build_mesh_collision_pairs(
            triangles=faces,
            bind_positions=close_island,
            sample_count=8,
            geodesic_min_hops=8,
            margin=0.05,
        )
        close_samples = close_island[close_table.sample_vertices]
        close_dist = np.linalg.norm(
            close_samples[close_table.pairs[:, 0]] - close_samples[close_table.pairs[:, 1]],
            axis=1,
        )
        assert np.all(close_dist >= 0.05 - 1e-9), float(close_dist.min())
    except RuntimeError as exc:
        assert "no geodesically-distant pairs" in str(exc), str(exc)

    return {
        "ok": True,
        "pairs": int(table.pair_count),
        "crossIsland": int(table.cross_component_pairs),
        "splitRawIslands": int(split_table.raw_island_count),
        "splitWeldedIslands": int(split_table.welded_island_count),
        "clipError": clip_error,
        "margin": float(table.margin),
    }


if __name__ == "__main__":
    print(run())
