#!/usr/bin/env python3
"""Unit test for town_full3d_step_flap (the recipe's flap rule): step faces are the ones whose depths span more than
STEP_EPS, the far side of a step is its far vertices, the uv map is refused unless affine, and a flap lies only
behind the layer's own rest front (FLAP_HIDE), at the far side's depth, within each px's pose opening, mirrored
across its lip, with no triangle across a step. python test_town_full3d_step_flap.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_step_flap as FL  # noqa: E402


def main() -> int:
    z = np.array([[100.0, 100.0, 101.0], [90.0, 103.0, 103.0], [100.0, 100.0, 100.0]])
    assert FL.step_faces(z).tolist() == [False, True, False]
    F = np.array([[0, 1, 2], [3, 4, 5]])
    zv = np.array([90.0, 103.0, 103.0, 50.0, 50.0, 50.0])
    assert FL.far_vertices(F, zv, np.array([0])).tolist() == [1, 2]
    assert FL.far_vertices(F, zv, np.zeros(0, np.int64)).tolist() == []

    px, py = np.random.default_rng(1).uniform(0, 500, (2, 200))
    uv = np.c_[px * 0.002 + 0.1, 1 - py * 0.002]
    M = FL.uv_affine(px, py, uv, (1000, 1000))
    assert np.allclose(np.c_[px, py, np.ones(200)] @ M, uv)
    try:
        FL.uv_affine(px, py, uv + np.c_[np.sin(px) * 0.01, np.zeros(200)], (1000, 1000))
        raise AssertionError("a non-affine uv must be refused")
    except SystemExit as e:
        assert "not an affine map" in str(e)

    # uv charts: two packed crops of one atlas (two affine maps of rest px), as a triangle soup (no shared vertex
    # index; coincident corners share their uv), plus a third face of crop 1 that the rest camera does not show
    rng = np.random.default_rng(2)
    q = rng.uniform(0, 100, (6, 2))
    soup = np.r_[q[[0, 1, 2]], q[[1, 2, 3]], q[[0, 2, 3]] + 200, q[[2, 3, 4]] + 200, q[[3, 4, 5]] + 200]
    A1 = np.array([[0.002, 0.0], [0.0, -0.002], [0.1, 0.9]])
    A2 = np.array([[0.002, 0.0], [0.0, -0.002], [-0.3, 1.0]])
    hom = np.c_[soup, np.ones(len(soup))]
    uvs = np.r_[hom[:6] @ A1, hom[6:] @ A2]
    Fs = np.arange(15).reshape(5, 3)
    ch, maps, off = FL.uv_affine_charts(soup[:, 0], soup[:, 1], Fs, uvs, np.array([0, 1, 2, 3]), (1000, 1000))
    assert ch[0] == ch[1] and ch[2] == ch[3] == ch[4] and ch[0] != ch[2], ch
    assert np.allclose(maps[int(ch[0])], A1) and np.allclose(maps[int(ch[2])], A2) and not off
    # a chart whose uv is no rest projection (mirrored) has no map and is listed with its deviation
    bent = uvs.copy()
    bent[6:, 0] = 1.0 - bent[6:, 0] + 0.001 * soup[6:, 1] ** 1.5
    ch, maps, off = FL.uv_affine_charts(soup[:, 0], soup[:, 1], Fs, bent, np.array([0, 1, 2, 3]), (1000, 1000))
    assert int(ch[0]) in maps and int(ch[2]) not in maps and off[int(ch[2])] > FL.FLAP_UV_TOL, (maps.keys(), off)
    try:
        FL.uv_affine(soup[:, 0], soup[:, 1], uvs, (1000, 1000))
        raise AssertionError("two crops are not one affine map")
    except SystemExit:
        pass

    # a near side (x < 50, depth 90) beside a far side (x >= 50, depth 103); the lip is the far side's edge at x 50.
    # Rows 30..39 of the near side are not in front (102.5: less than FLAP_HIDE nearer), row 45 is empty.
    W, H = 120, 80
    zf = np.full((H, W), 103.0)
    zf[:, :50] = 90.0
    zf[30:40, :50] = 102.5
    zf[45, :50] = np.inf
    ly = np.arange(10, 70, dtype=np.float64) + 0.5
    lx = np.full_like(ly, 50.2)
    lz = np.full_like(ly, 103.0)
    lv = np.arange(len(ly))
    g = FL.flap_grid(lx, ly, lz, lv, zf, lambda gx, gy, zn, zfar: np.full(len(gx), 10.0), (W, H))
    assert g is not None
    flap = g["x"] < 50                                # flap vertices (the rest are the lip px they attach to)
    assert np.all(g["z"] == 103.0), "a flap sits at its lip's depth"
    assert np.all(g["x"][flap] >= 50 - 12 - 1e-9), "a flap reaches only its opening plus the pad"
    rows = np.floor(g["y"][flap]).astype(int)
    assert not np.isin(rows, list(range(30, 40)) + [45]).any(), "a flap never shows at rest"
    assert np.all(g["mx"][flap] > 50), "flap texels mirror into the far side"
    mid = (g["y"] > 25) & (g["y"] < 55)               # away from the lip's ends, the nearest lip px is on the row
    assert np.allclose(g["mx"][mid] - 50.5, 50.5 - g["x"][mid]) and np.allclose(g["my"][mid], g["y"][mid])
    assert not FL.step_faces(g["z"][g["tris"]]).any()
    assert g["flapPx"] == int(flap.sum())

    # two lips at different depths: the flap between them is never one sheet across the step
    lz2 = np.where(ly < 40, 103.0, 120.0)
    zf2 = zf.copy()
    zf2[30:40, :50] = 90.0
    zf2[45, :50] = 90.0
    g2 = FL.flap_grid(lx, ly, lz2, lv, zf2, lambda gx, gy, zn, zfar: np.full(len(gx), 10.0), (W, H))
    assert not FL.step_faces(g2["z"][g2["tris"]]).any()
    assert {103.0, 120.0} <= set(np.unique(g2["z"]).tolist())

    # no opening, no flap
    assert FL.flap_grid(lx, ly, lz, lv, zf, lambda gx, gy, zn, zfar: np.full(len(gx), -FL.FLAP_PAD_PX - 1), (W, H)) is None

    # winding follows the reference piece
    ref = np.array([[0, 1, 2]])
    rx, ry = np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])
    t = FL.orient_like(np.array([[0, 2, 1], [0, 1, 2]]), rx, ry, ref, rx, ry)
    assert t.tolist() == [[0, 1, 2], [0, 1, 2]]
    print("town_full3d_step_flap: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
