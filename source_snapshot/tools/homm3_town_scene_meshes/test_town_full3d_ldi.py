#!/usr/bin/env python3
"""Synthetic checks of town_full3d_ldi (docs/homm3_town_layered_depth_backfill.md): a frame-registered grid with a near
ridge in front of far ground. The cut removes exactly the curtain (over-cap) triangles and leaves main vertices alone,
the back layer is within the cap and keeps every vertex on its own rest ray behind its main copy, relax_to_cap keeps a
stepping sheet connected, and quilt_fill writes only fill texels. Needs a standalone moderngl context (rest_depth)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_ldi as L  # noqa: E402

FOV = 47.6


def step_grid(nx=64, ny=36, z_near=10.0, z_far=20.0):
    """A screen grid over the 1920x1080 frame: the lower half at z_near, the upper half at z_far (a horizontal ridge)."""
    xs = (np.arange(nx) + 0.5) / nx * L.W
    ys = (np.arange(ny) + 0.5) / ny * L.H
    fx, fy = np.meshgrid(xs, ys)
    z = np.where(fy > L.H / 2, z_near, z_far)
    f = 0.5 * L.H / np.tan(np.radians(FOV) / 2)
    v = np.stack([(fx - L.W / 2) / f * z, -(fy - L.H / 2) / f * z, z], -1).reshape(-1, 3)
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    tris = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, d], -1).reshape(-1, 3)])
    uv = np.stack([fx.ravel() / L.W, 1 - fy.ravel() / L.H], 1)
    n = np.tile([0.0, 0.0, -1.0], (len(v), 1))
    return v, n, uv, tris


def test_cut_and_back_layer():
    v, n, uv, tris = step_grid()
    _, _, z = L.project(v, FOV)
    ratio = L.depth_ratio(z, tris)
    out = L.layer_piece(v, n, uv, tris, FOV)
    assert out is not None
    mv, _, muv, mt = out["main"]
    assert np.array_equal(mv, v) and np.array_equal(muv, uv), "main vertices / uv must be untouched"
    assert int((ratio > L.RATIO_CAP).sum()) == len(out["cut"]) == out["report"]["cutByRatio"]
    assert (L.depth_ratio(z, mt) <= L.RATIO_CAP + 1e-6).all()
    assert (L.depth_ratio(z, out["cut"]) > L.RATIO_CAP).all(), "every stored cut is a curtain (validator negative)"
    vb, _, uvb, tb = out["back"]
    assert len(tb) and (L.depth_ratio(vb[:, 2], tb) <= L.RATIO_CAP + 1e-6).all()
    # back vertices stay on their rest rays (same screen position) and never in front of the original surface
    bx, by, bz = L.project(vb, FOV)
    src = np.unique(out["backSource"][: len(tb) - out["report"]["tilesFlattened"]])
    ox, oy, oz = L.project(v[src], FOV)
    sel = np.arange(len(src))
    assert np.allclose(bx[sel], ox, atol=1e-6) and np.allclose(by[sel], oy, atol=1e-6)
    assert (bz[sel] >= oz - 1e-9).all()
    # the near side under the ridge is continued at the far depth
    near_band = (oy > L.H / 2) & (oy < L.H / 2 + 60)
    assert near_band.any() and np.median(bz[sel][near_band]) > 15.0


def test_backstop_and_hole_loop():
    v, n, uv, tris = step_grid()
    pose = (np.array([0.0, 1.5, 0.0]), np.eye(3))            # camera moved up: the ridge slides down over the far side
    out, rep = L.keep_holes(v, n, uv, tris, FOV, [pose])
    sv, _, _, st = out["stop"]
    assert (L.depth_ratio(sv[:, 2], st) <= L.RATIO_CAP + 1e-6).all() if len(st) else True
    assert rep["history"][-1]["holePx"][0] == 0, rep            # the step grid's gap is filled by back layer + backstop
    before = L.id_render([(v, tris)], FOV, pose)[0]
    after = L.id_render([(out["main"][0], out["main"][3]), (out["back"][0], out["back"][3]), (sv, st)], FOV, pose)[0]
    assert not ((before == 0) & (after < 0)).any()


def test_no_step_is_untouched():
    v, n, uv, tris = step_grid(z_near=20.0, z_far=20.0)
    assert L.layer_piece(v, n, uv, tris, FOV) is None


def post_grid(nx=256, ny=72, z_near=10.0, z_far=40.0):
    """Far ground (z_far) with a near post in the middle columns whose sides are ramps three cells wide (a sharp depth
    map's occlusion edge as the terrain grid samples it)."""
    xs = (np.arange(nx) + 0.5) / nx * L.W
    ys = (np.arange(ny) + 0.5) / ny * L.H
    fx, fy = np.meshgrid(xs, ys)
    d = np.abs(fx - L.W / 2)                                   # px from the post's axis
    core, ramp = 120.0, 3 * L.W / nx
    t = np.clip((d - core) / ramp, 0, 1)
    z = 1.0 / ((1 - t) / z_near + t / z_far)
    f = 0.5 * L.H / np.tan(np.radians(FOV) / 2)
    v = np.stack([(fx - L.W / 2) / f * z, -(fy - L.H / 2) / f * z, z], -1).reshape(-1, 3)
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, e = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    tris = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, e], -1).reshape(-1, 3)])
    uv = np.stack([fx.ravel() / L.W, 1 - fy.ravel() / L.H], 1)
    n = np.tile([0.0, 0.0, -1.0], (len(v), 1))
    return v, n, uv, tris


def test_zone_cut_takes_the_whole_ramp_and_continues_the_far_plateau():
    v, n, uv, tris = post_grid()
    _, _, z = L.project(v, FOV)
    pose = (np.array([1.5, 0.0, 0.0]), np.eye(3))            # a sideways sweep: the post's sides smear
    out = L.layer_piece(v, n, uv, tris, FOV, [pose], zone={})
    assert out is not None and out["report"]["zoneCut"]["zoneCutTris"] > 0
    mid = (z > 10.0 * L.ZONE_DEFAULTS["near_tol"]) & (z < 40.0 / L.ZONE_DEFAULTS["far_tol"])
    assert mid.any()
    mt = out["main"][3]
    assert not mid[mt].any(), "no ramp vertex may stay in a main triangle (the curtain is cut whole)"
    vb, _, _, tb = out["back"]
    nb = len(tb) - out["report"]["tilesFlattened"]
    src = np.unique(out["backSource"][:nb])
    bz = L.project(vb[: len(src)], FOV)[2]
    ramp_src = mid[src]
    assert ramp_src.any() and np.median(bz[ramp_src]) > 40.0 / L.NEAR_RATIO - 1e-6, \
        "the ramp's back copies continue the far plateau, not the middle of the ramp"
    assert L.layer_piece(v, n, uv, tris, FOV, [pose]) is not None    # zone=None: the default rule is unchanged


def test_relax_to_cap_keeps_one_sheet():
    z = np.array([10.0, 30.0, 10.0, 30.0])
    tris = np.array([[0, 1, 2], [1, 3, 2]])
    free = np.array([True, False, True, False])
    zr = L.relax_to_cap(z, tris, free, 1.25)
    assert (L.depth_ratio(zr, tris) <= 1.25 + 1e-9).all()
    assert zr[1] == 30.0 and zr[3] == 30.0 and (zr >= z).all()


def test_quilt_fill_writes_only_fill():
    rng = np.random.default_rng(1)
    img = rng.uniform(0, 255, (120, 160, 3)).astype(np.float32)
    fill = np.zeros((120, 160), bool)
    fill[40:80, 60:110] = True
    src = ~fill
    src[30:90, 50:120] = False
    out, rep = L.quilt_fill(img, fill, src)
    assert np.array_equal(out[~fill], img[~fill])
    assert rep["tiles"] > 0 and not np.allclose(out[fill], img[fill])


def test_floor_clamp():
    """town_full3d_ldi_floor.floor_clamp: only pushed vertices below the floor move, up to the floor but never nearer
    than BEHIND x the main surface; unpushed (welded) vertices keep their depth; the result is within the cap."""
    import town_full3d_ldi_floor as LF
    tris = np.array([[0, 1, 2], [1, 3, 2], [2, 3, 4]])
    zmain = np.array([10.0, 10.0, 10.0, 10.0, 12.0])
    zb = np.array([10.0, 12.0, 12.4, 12.4, 12.0])     # 0 and 4 unpushed (welded); 1-3 pushed
    zfloor = np.array([9.0, 13.0, 11.0, 9.0, 9.0])    # 1 above the floor; 2 below; 3 below a floor nearer than main
    z, rep = LF.floor_clamp(zb, zmain, zfloor, tris)
    assert z[0] == 10.0 and z[4] == 12.0 and z[1] == 12.0, "unpushed and above-floor vertices never move"
    assert np.isclose(z[2], 11.0) and np.isclose(z[3], 10.0 * L.BEHIND)
    assert rep["belowFloorVerts"] == 2 and (L.depth_ratio(z, tris) <= L.RATIO_CAP + 1e-6).all()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
