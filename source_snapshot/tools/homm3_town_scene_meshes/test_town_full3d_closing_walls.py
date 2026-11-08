"""Regression test for the depth-step closing walls (stronghold_full3d_buildings.closing_walls).

A synthetic solid on its camera rays: a near block (depth 50) standing in front of a far wall (depth 80), the front
grid cut and sunk at the step the way front_surface(sink_cuts=True) does, and a back sheet (smoothed front depth +
thickness, welded at the outline, wound away from the camera) the way build_solid closes it. From a camera moved
toward the far side the back sheet shows its back through the sunk step: the game (Cull Back) sees through it. The
closing walls must (1) project to zero area at the rest camera, (2) share their top edge with the near sheet and their
bottom edge with the sunk triangles, (3) face the far side, and (4) remove the see-through px at a side camera.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_closing_walls.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_buildings as BL  # noqa: E402
import town_full3d_cull as CULL  # noqa: E402

SGN = 1.0


def scene():
    cam = np.zeros(3)
    nx, ny = 61, 41
    u, w = np.meshgrid(np.linspace(-0.3, 0.3, nx), np.linspace(-0.2, 0.2, ny))
    rays = np.stack([u, w, np.ones_like(u)], -1)
    block = (np.abs(u) < 0.1) & (np.abs(w) < 0.12)
    zz = np.where(block, 50.0, 80.0)
    P = cam + rays * zz[..., None]
    a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])
    zr = zz.ravel()[tris]
    cut = zr.max(1) / zr.min(1) > BL.CUT_RATIO
    return cam, rays, zz, P, tris[~cut], tris[cut], u, w


def front_mesh(cam, P, zz, kept, cut_tris, u, w, walls):
    Pr = P.reshape(-1, 3)
    ct = cut_tris.ravel()
    zmax = np.repeat(zz.ravel()[cut_tris].max(1), 3)
    Ps = cam + (Pr[ct] - cam) * (zmax / zz.ravel()[ct])[:, None]
    V = np.concatenate([Pr, Ps])
    F = np.concatenate([kept, len(Pr) + np.arange(len(ct)).reshape(-1, 3)])
    F = BL.wind_to_camera(V, F, cam, SGN)
    if walls:
        Pw, _, _, _, _, tw, _ = BL.closing_walls(P, zz, cut_tris, cam, SGN, u, w)
        F = np.concatenate([F, len(V) + tw])
        V = np.concatenate([V, Pw])
    return V, F


def back_mesh(cam, rays, zz):
    import cv2
    ny, nx = zz.shape
    zs = cv2.blur(zz.astype(np.float32), (7, 7), borderType=cv2.BORDER_REPLICATE).astype(np.float64)
    zb = np.maximum(zz, zs) + 10.0
    rim = np.zeros_like(zz, bool)
    rim[0], rim[-1], rim[:, 0], rim[:, -1] = True, True, True, True
    zb[rim] = zz[rim]
    Pb = (cam + rays * zb[..., None]).reshape(-1, 3)
    a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]).ravel()
    bt = np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])
    r = rays.reshape(-1, 3)
    return Pb, BL.orient(Pb, bt, r[bt].mean(1), SGN)


def facing(V, F, cam):
    g = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    return (g * (cam - V[F].mean(1))).sum(1) * SGN


def piece(name, V, F):
    return (name, V.astype(np.float32), np.tile([[0, 0, -1]], (len(V), 1)).astype(np.float32),
            np.zeros((len(V), 2), np.float32), F.astype(np.int32))


def main() -> int:
    cam, rays, zz, P, kept, cut_tris, u, w = scene()
    Pw, Nw, Uw, Vw, Zw, tw, we = BL.closing_walls(P, zz, cut_tris, cam, SGN, u, w)
    assert len(tw), "no walls on a step"
    # (1) zero projected area at the rest camera
    q = Pw[:, :2] / Pw[:, 2:3]
    d1, d2 = q[tw[:, 1]] - q[tw[:, 0]], q[tw[:, 2]] - q[tw[:, 0]]
    area = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])
    assert area.max() < 1e-12, f"a wall is visible at rest (projected area {area.max():.3g})"
    # (2) watertight: top corners are near grid vertices, bottom corners sit at the step's far depth on the same rays
    near = {tuple(np.round(p, 9)) for p in P.reshape(-1, 3)[zz.ravel() == 50.0]}
    tops = Pw.reshape(-1, 4, 3)[:, :2].reshape(-1, 3)
    assert all(tuple(np.round(p, 9)) in near for p in tops), "a wall top is not on the near sheet"
    assert np.allclose(Zw.reshape(-1, 4)[:, 2:], 80.0), "a wall bottom is not at the sunk depth"
    # closed edge loop: the walls' top edges run all the way round the block (every corner vertex on exactly two)
    import collections
    deg = collections.Counter()
    for c in Pw.reshape(-1, 4, 3):
        for p in c[:2]:
            deg[tuple(np.round(p, 9))] += 1
    assert set(deg.values()) == {2}, f"the walls' top edges are not one closed loop: degrees {collections.Counter(deg.values())}"
    # (3) facing the far side: a camera moved right sees the walls on the block's right side from the front
    c4 = Pw.reshape(-1, 4, 3)
    # walls on the block's right edge: a vertical near edge (both tops in one ray column) right of centre
    right = (c4[:, 0, 0] > 0) & np.isclose(c4[:, 0, 0] / c4[:, 0, 2], c4[:, 1, 0] / c4[:, 1, 2])
    right_t = np.concatenate([right, right])
    side = np.array([12.0, 0.0, 0.0])
    fr = facing(Pw, tw, side)
    assert (fr[right_t] > 0).all(), "a right-side wall faces away from a camera moved right"
    assert (Nw.reshape(-1, 4, 3)[right, 0, 0] > 0).all(), "a right-side wall's normal does not point right"
    # (4) see-through at a side camera: present without the walls, gone with them
    Pb, bt = back_mesh(cam, rays, zz)
    cams = {"side": {"fov": 40.0, "pos": side, "fwd": np.array([0.0, 0.0, 1.0]), "up": np.array([0.0, 1.0, 0.0]),
                     "right": np.array([1.0, 0.0, 0.0])}}
    out = {}
    for walls in (False, True):
        V, F = front_mesh(cam, P, zz, kept, cut_tris, u, w, walls)
        Vall, Fall = np.concatenate([V, Pb]), np.concatenate([F, len(V) + bt])
        out[walls] = CULL.see_through([piece("b/Mesh_Body_block", Vall, Fall)], cams, 320, 180, 1.0, 400.0)["side"]
    assert out[False]["seeThroughPx"] > 50, f"the synthetic step does not see through without walls: {out[False]}"
    assert out[True]["seeThroughPx"] == 0, f"closing walls leave see-through px: {out[True]}"
    print(f"OK closing_walls: {len(tw) // 2} walls, zero area at rest, watertight, facing the far side; side-camera "
          f"see-through {out[False]['seeThroughPx']} -> {out[True]['seeThroughPx']} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
