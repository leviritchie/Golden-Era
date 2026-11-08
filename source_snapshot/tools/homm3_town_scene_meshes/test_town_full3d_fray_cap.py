"""Regression test for the fray cap (stronghold_full3d_solids.cap_cut).

A synthetic solid on its camera rays: a camera-facing front grid (depth 50) and a back sheet 10 deeper, welded to the
front on the grid's outline and wound away from the camera, the way build_solid closes a building. A frame-edge fray
(BL.edge_fray) removes every triangle whose rest-camera centroid lies right of a line, which leaves an open
cross-section: a camera moved right sees the back sheet's inside (the game's Cull Back drops it). The cap must
(1) project to zero area at the rest camera, (2) remove the see-through px at the side camera, (3) carry one in-mask
front texel per cap, unmodified, and (4) fail closed when the back has a cut edge the front does not.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fray_cap.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_buildings as BL  # noqa: E402
import stronghold_full3d_solids as SO  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import town_full3d_cull as CULL  # noqa: E402

SGN = 1.0
CAM = {"fov": 40.0, "pos": np.zeros(3), "fwd": np.array([0.0, 0.0, 1.0]), "up": np.array([0.0, 1.0, 0.0]),
       "right": np.array([1.0, 0.0, 0.0])}
NX, NY = 61, 41
TWP, THP = 64, 48


def solid():
    u, w = np.meshgrid(np.linspace(-0.3, 0.3, NX), np.linspace(0.2, -0.2, NY))
    rays = np.stack([u, w, np.ones_like(u)], -1).reshape(-1, 3)
    zz = np.full(NX * NY, 50.0)
    rim = np.zeros((NY, NX), bool)
    rim[0], rim[-1], rim[:, 0], rim[:, -1] = True, True, True, True
    zb = np.where(rim.ravel(), zz, zz + 10.0)
    Pf, Pb = rays * zz[:, None], rays * zb[:, None]
    a = (np.arange(NY - 1)[:, None] * NX + np.arange(NX - 1)[None, :]).ravel()
    g = np.concatenate([np.stack([a, a + 1, a + NX], 1), np.stack([a + 1, a + NX + 1, a + NX], 1)])
    tf = BL.wind_to_camera(Pf, g, CAM["pos"], SGN)
    V = np.concatenate([Pf, Pb])
    bt = BL.orient(V, g + len(Pf), rays[g].mean(1), SGN)
    F = np.concatenate([tf, bt])
    j, i = np.divmod(np.arange(NX * NY), NX)
    uvf = np.stack([(i + 0.5) / (2 * TWP), 1 - (j + 0.5) / THP], 1)
    uv = np.concatenate([uvf, uvf + [0.5, 0.0]])
    rng = np.random.default_rng(7)
    atlas = rng.uniform(0.1, 0.9, (THP, 2 * TWP, 3)).astype(np.float32)
    mbig = np.zeros((NY, NX), bool)
    mbig[1:-1, 1:-1] = True
    n = np.concatenate([np.tile([[0, 0, -1.0]], (len(Pf), 1)), np.tile([[0, 0, 1.0]], (len(Pb), 1))])
    # frame box of the front texels: vertex (i, j) projects on texel centre (i + 0.5, j + 0.5)
    px, py, _ = T.project(CAM, Pf)
    ax, bx = np.polyfit(i, px, 1)
    ay, by = np.polyfit(j, py, 1)
    frame = [float(bx - 0.5 * ax), float(by - 0.5 * ay), float(ax * NX), float(ay * NY)]
    return {"P": V, "n": n, "uv": uv, "tris": F, "frontTris": len(tf), "albedo": atlas, "frontMask": mbig,
            "frontFrame": frame, "wallVerts": [0, 0], "solid": {}, "wallEdges": np.zeros((0, 2, 3))}


def fray(m, xcut):
    F = np.asarray(m["tris"])
    px, _, _ = T.project(CAM, m["P"])
    return F, px[F].mean(1) > xcut


def piece(m):
    return ("b/Mesh_Body_block", np.asarray(m["P"], np.float32), np.asarray(m["n"], np.float32),
            np.asarray(m["uv"], np.float32), np.asarray(m["tris"], np.int32))


def main() -> int:
    side = {"side": {**CAM, "pos": np.array([14.0, 0.0, 0.0])}}
    px, _, _ = T.project(CAM, solid()["P"])
    xcut = float(np.quantile(px, 0.7))
    # plain removal (the relief path): the cross-section is open
    m0 = solid()
    F, drop = fray(m0, xcut)
    m0["tris"] = F[~drop]
    open_px = CULL.see_through([piece(m0)], side, 320, 180, 1.0, 400.0)["side"]["seeThroughPx"]
    assert open_px > 50, f"the synthetic fray does not open the solid: {open_px} px"
    # capped
    m = solid()
    F, drop = fray(m, xcut)
    nv = len(m["P"])
    rep = SO.cap_cut("syn", m, F, drop, CAM, SGN)
    assert rep["capWalls"] > 0, rep
    assert rep["capRestAreaMaxPx2"] < 1e-6, rep                      # (1) edge-on at rest
    closed = CULL.see_through([piece(m)], side, 320, 180, 1.0, 400.0)["side"]["seeThroughPx"]
    assert closed == 0, f"the cap leaves {closed} see-through px (open {open_px})"      # (2)
    # (3) every cap vertex on a texel centre of the front half, in mask, colour = that front texel unmodified
    uvc = np.asarray(m["uv"], np.float64)[nv:]
    ax, ay = uvc[:, 0] * 2 * TWP - 0.5, (1 - uvc[:, 1]) * THP - 0.5
    assert np.allclose(ax, np.round(ax)) and np.allclose(ay, np.round(ay)), "a cap uv is off a texel centre"
    ax, ay = np.round(ax).astype(int), np.round(ay).astype(int)
    assert (ax < NX).all() and m["frontMask"][ay, ax].all(), "a cap texel is outside the building's mask"
    assert len(m["wallEdges"]) == rep["capWalls"], "cap near edges are not exported for the Unity rest check"
    assert m["capTris"] == len(m["tris"]) - len(F[~drop]), m["capTris"]
    # a second fray on the capped mesh (bottom after right) still closes
    F2 = np.asarray(m["tris"])
    _, py, _ = T.project(CAM, m["P"])
    drop2 = py[F2].mean(1) > float(np.quantile(py, 0.75))
    SO.cap_cut("syn", m, F2, drop2, CAM, SGN)
    side2 = {"low": {**CAM, "pos": np.array([0.0, -14.0, 0.0])}, **side}
    two = CULL.see_through([piece(m)], side2, 320, 180, 1.0, 400.0)
    assert all(v["seeThroughPx"] == 0 for v in two.values()), two
    # (4) fail closed: a back cut the front does not share
    m4 = solid()
    F, drop = fray(m4, xcut)
    nf = m4["frontTris"]
    drop4 = drop.copy()
    drop4[:nf] = False                                                # the front stays whole, the back is cut
    try:
        SO.cap_cut("syn", m4, F, drop4, CAM, SGN)
    except SystemExit as e:
        assert "open" in str(e), e
    else:
        raise AssertionError("a back cut with no front cut must fail closed")
    print(f"OK fray cap: {rep['capWalls']} caps, rest area {rep['capRestAreaMaxPx2']:.3g} px^2, side-camera "
          f"see-through {open_px} -> {closed} px, second fray closed, one-sided cut refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
