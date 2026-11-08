"""Regression test for the closing walls' texels (stronghold_full3d_solids.wall_texels).

A closing wall must show an existing texel of its own building, unmodified (buildings are never regraded), chosen
spatially: not the near edge's own texel (an edge highlight such as a lit window smeared along the wall's depth read
as a bright streak), not a far-layer texel across the step, not an out-of-mask texel. A synthetic building: a
near block over a far wall, a one-texel bright "window" line along the block's edge, noise elsewhere.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_wall_texels.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_solids as SO  # noqa: E402


def main() -> int:
    rng = np.random.default_rng(7)
    th, tw = 80, 120
    front = (0.25 + 0.2 * rng.random((th, tw, 3))).astype(np.float32)
    mbig = np.ones((th, tw), bool)
    mbig[:, :4] = False                       # out of mask on the left
    front[~mbig] = 0.0
    ztex = np.full((th, tw), 80.0, np.float32)
    ztex[20:60, 30:70] = 50.0                 # the near block
    front[20:60, 69] = 0.98                   # a lit "window" line on the block's right edge
    front[20:60, 70:] = np.array([0.1, 0.6, 0.1], np.float32)   # the far layer across the step: green
    # walls on the block's right edge (near edge between x = 69.5 and 70, one per 2 texel rows)
    ys = np.arange(28, 50, 2) + 0.5          # away from the block's top and bottom steps (radius 16)
    edge = np.stack([np.stack([np.full_like(ys, 70.0), ys], 1), np.stack([np.full_like(ys, 70.0), ys + 2], 1)], 1)
    m = len(edge)
    far = np.stack([np.full(m, 71.0), ys + 1], 1)              # the far vertex: across the step, right of the edge
    tx, sil = SO.wall_texels(front, mbig, edge, far)
    assert sil == 0, sil
    src = {tuple(c) for c in front[mbig].round(7)}
    got = front[tx[:, 1], tx[:, 0]]
    # (1) every wall colour is an existing in-mask texel of the building, unmodified
    assert mbig[tx[:, 1], tx[:, 0]].all(), "a wall texel is outside the mask"
    assert all(tuple(c) in src for c in got.round(7)), "a wall colour is not one of the building's texels"
    # (2) on the step's near side (away from the far vertex), never the far layer
    assert (ztex[tx[:, 1], tx[:, 0]] == 50.0).all(), "a wall took a far-layer texel"
    # (3) not the edge highlight, and a few texels in from the edge
    assert (got.max(1) < 0.98).all(), "a wall took the edge highlight"
    d = 70.0 - (tx[:, 0] + 0.5)
    assert (d >= SO.WALL_INNER_TX).all(), f"a wall texel is inside the edge band: {d.min():.2f}"
    # (4) a step on the silhouette (Cove tbcvdock): the near part is the outline ring, no near-side texel 3+ in; the
    # band is taken inward on the far side and the wall is counted
    mo = np.zeros_like(mbig)
    mo[:, :72] = True                            # the mask ends 2 texels right of the edge line x = 70
    far_in = np.stack([np.full(m, 69.0), ys + 1], 1)   # the far vertex inside the building, left of the edge
    ts, sil2 = SO.wall_texels(front, mo, edge, far_in)
    assert sil2 == m and (ts[:, 0] + 0.5 <= 70.0 - SO.WALL_INNER_TX).all() and mo[ts[:, 1], ts[:, 0]].all(), (sil2, ts)
    # (5) fail closed: a building with no in-mask texel raises
    try:
        SO.wall_texels(front, np.zeros_like(mbig), edge[:1], far[:1])
    except SystemExit:
        pass
    else:
        raise AssertionError("a wall without a near-side texel must fail, not fall back")
    print(f"OK wall_texels: {m} walls on {len(np.unique(tx, axis=0))} distinct in-mask near-side texels, no edge "
          f"highlight, all colours existing texels of the building")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
