"""Conflux full-3D, phase 6: the world outside the default frame across sampled town-camera pan paths.

The 2026-09-27 review of phase 5: "The default camera actually does pan around for a dramatic look at everything, and it
exceeds the bounds of your projected terrain on the left and right sides. It needs more filler on the outside."
Phases 1-5 built every terrain surface registered to the default 1920x1080 frame (a screen-space grid), so any pose
of the pan (conflux_town_camera_pan: the vanilla BhCityCameraController cursor look, spline sweep and mode
transitions) that looks past the frame edge saw the clear colour or the sky dome below the horizon.

This module adds an outer world in the vanilla town idiom (the cityHuman2 scene carries a terrain mesh and grass-
mountain hills round to azimuth -97 .. +139 deg of its camera, rho up to 140 m, conifers and rocks in the mid field):

  * height   an outer heightfield (OUT_RES m cells) in the painting world: the phase-2 heightmap where it is
             trustworthy (inside its bounds, right of the HoMM3 left edge); the valley walls continued round the pan
             on both sides with the phase-2 right-wall rule (the frame edge column's height-over-distance profile,
             pulled nearer and ridged), the left wall from the HoMM3 x = 0 column; meadow hummocks near the camera;
             the frame mesh's own surface splatted in and blended over SEAM_BLEND_M so the outer ground meets the
             frame edge without a step; both rivers continued along their own meander rule past the frame edge and
             under the camera (carved channels).
  * mesh     a polar grid about the rest camera (THETA_STEP deg x a distance step growing with rho) to RHO_MAX.
             Triangles wholly EDGE_PX inside the default frame are dropped; kept vertices that fall inside the frame
             are moved back along their own rest-camera ray behind the frame surface (or down to the skyline where
             the frame shows sky), aiming to preserve the phase-5 default frame; editor pixels must verify it.
  * albedo   the phase-5 synthesis (vanilla terrain textures in world space, conflux_full3d_nearfield.Synth) on polar
             texture pieces (theta across, rows by the angle a metre of ground subtends from the camera), classes by
             slope / height above the meadow, low-frequency colour from the painting's class colours toned to the
             frame edge colour next to the frame.
  * water    the rivers' outer reaches as FlowWater ribbons whose downstream coordinate continues the frame water's.
  * scatter  conifer clusters, bushes and boulders (the scene's own Meshy props, reused: 0 new credits) on the outer
             ground only: every instance's bounding box projects outside the default frame. Merged per LOD into
             lit bins.
  * coverage a sampled raster of the final retained outer triangles, plus the frame heightfield, for the validator
             (tools/validate_town_scene3d_contract.py). This is a geometry-grounded rejection screen, not an exact
             pixel visibility proof; default and pan renders are still required for visual acceptance.

Proof tier at source: unvalidated phase-6 implementation. Stage, validator, Unity-editor pan renders and runtime
behavior must be reported separately; no in-game proof is implied.
"""
from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np
from PIL import Image

import conflux_full3d_env as E
import conflux_full3d_nearfield as N5
import conflux_town_camera_pan as PAN

W, H, TW, TH = E.W, E.H, E.TW, E.TH
SEED = 606

# --- outer heightfield -----------------------------------------------------------------------------------------------
OUT_RES = 0.5              # m per cell
RHO_MAX = 172.0            # m: inside the sky dome (DOME_R 185)
THETA_MAX = 66.0           # deg either side of the rest heading (the pan reaches ~53 deg from moved cameras)
ALONG_MIN = -16.0          # m behind the rest camera
SEAM_BLEND_M = 5.0         # the frame surface's splat blends into the outer height over this distance
LEFT_ROUGH_DEG = 10.0     # the left wall's ridge noise ramps in over this many degrees past the frame edge
LEFT_BLEND_DEG = 1.5       # the phase-2 heightmap gives way to the left wall over this many degrees past the frame edge
WALL_SHIFT_M, WALL_FALL = 10.0, 0.35   # the phase-2 right-wall rule (foot nearer, ridge lower away from the town)
RIVER_TAIL_ALONG = -14.0   # rivers continue until they are this far behind the rest camera
# --- mesh ------------------------------------------------------------------------------------------------------------
THETA_STEP = 0.5
RHO_MIN = 5.0              # m: the pan never sees ground nearer than ~7.7 m of the rest camera (measured)
EDGE_PX = 12.0             # a triangle wholly this far inside the frame is the frame mesh's
PUSH_REL, PUSH_ABS = 0.004, 0.04   # kept vertices inside the frame sit this far behind the frame surface
# --- texture pieces --------------------------------------------------------------------------------------------------
THETA_SPLIT = 36.0         # |theta| below this: the centre bucket (under / above the frame)
RHO_BANDS = ((0.0, 14.0, 0.015), (14.0, 45.0, 0.02), (45.0, RHO_MAX + 1, 0.03))   # (rho0, rho1, deg per texel)
CAM_H = 4.7                # m: the rest camera's height above the meadow (row density near the camera)
FACE = 0.7                 # far rows: a slope facing the camera subtends ~FACE/rho rad per metre
MAX_TEX = 4096
EDGE_TONE_PX = 200.0       # the outer albedo takes the frame edge colour, e-folding this many 1080p px outside
# --- scatter ---------------------------------------------------------------------------------------------------------
FOREST_RHO = (7.0, 95.0)
TREE_SPACING = 1.7
BUSH_SPACING = 2.2
ROCK_SPACING = 3.0


# ------------------------------------------------------------------------------------------------ geometry helpers
def frame_angles(cam) -> dict:
    f, r = E.heading(cam)

    def az(px, py):
        d = E.rays(cam, np.array(float(px)), np.array(float(py)))
        return math.degrees(math.atan2(float(d @ r), float(d @ f)))
    return {"thL": az(0.0, H * 0.5), "thR": az(float(W), H * 0.5), "thE": az(float(TW), H * 0.5)}


def polar_to_xz(cam, th_deg, rho):
    f, r = E.heading(cam)
    t = np.radians(th_deg)
    X = cam["pos"][0] + rho * (np.cos(t) * f[0] + np.sin(t) * r[0])
    Z = cam["pos"][2] + rho * (np.cos(t) * f[2] + np.sin(t) * r[2])
    return X, Z


class Field:
    """A regular XZ height grid with bilinear lookup (clamped)."""

    def __init__(self, x0, z0, res, h):
        self.x0, self.z0, self.res, self.h = x0, z0, res, h.astype(np.float32)

    def sample(self, arr, X, Z):
        cx = np.clip((np.asarray(X) - self.x0) / self.res, 0, arr.shape[1] - 1.001)
        cz = np.clip((np.asarray(Z) - self.z0) / self.res, 0, arr.shape[0] - 1.001)
        ix, iz = cx.astype(int), cz.astype(int)
        fx, fz = cx - ix, cz - iz
        return ((arr[iz, ix] * (1 - fx) + arr[iz, ix + 1] * fx) * (1 - fz)
                + (arr[iz + 1, ix] * (1 - fx) + arr[iz + 1, ix + 1] * fx) * fz)

    def height(self, X, Z):
        return self.sample(self.h, X, Z)

    def normal(self, X, Z, eps=0.5):
        hx = (self.height(X + eps, Z) - self.height(X - eps, Z)) / (2 * eps)
        hz = (self.height(X, Z + eps) - self.height(X, Z - eps)) / (2 * eps)
        n = np.stack([-hx, np.ones_like(hx), -hz], -1)
        return n / np.linalg.norm(n, axis=-1, keepdims=True)


def edge_profile(cam, zh: np.ndarray, cols: slice) -> np.ndarray:
    """Height-over-distance profile of a HoMM3 edge column band (the phase-2 right-wall rule, build_heightmap B)."""
    cy, cx = np.mgrid[0:TH, cols]
    z = zh[:, cols]
    ok = ~np.isnan(z)
    P = cam["pos"] + E.rays(cam, cx[ok].astype(np.float64), cy[ok].astype(np.float64)) * z[ok][:, None]
    _, re_, _ = E.polar(cam, P[:, 0], P[:, 2])
    rb = np.arange(0.0, 240.0, 0.5)
    prof = np.full(len(rb), np.nan)
    np.fmax.at(prof, np.clip((re_ / 0.5).astype(int), 0, len(rb) - 1), P[:, 1])
    g = ~np.isnan(prof)
    prof = np.interp(rb, rb[g], prof[g])
    prof = np.maximum.accumulate(prof)
    return cv2.GaussianBlur(prof.astype(np.float32)[None], (0, 0), 3.0)[0]


def wall(X, Z, theta, rad, prof, meadow_h, s, seed=7, rough=1.0):
    """The phase-2 valley wall (build_heightmap region B, same noise seeds) with profile `prof` and edge weight s.
    rough (0..1) fades the ridge / crag / gully modulation in: at 0 the wall is the edge profile itself, so a wall
    continued past a frame edge starts on that edge's own skyline."""
    rb = np.arange(0.0, 240.0, 0.5)
    hb = np.interp(rad + WALL_SHIFT_M * s, rb, prof)
    above = np.maximum(hb - meadow_h, 0) * (1.0 - WALL_FALL * s)
    ridge = E.fbm(X, Z, seed, 16.0, 4, ridged=True)
    crag = E.fbm(X, Z, seed + 60, 6.0, 3, ridged=True)
    gully = E.fbm(X, Z, seed + 40, 9.0, 3)
    hummock = (E.fbm(X, Z, seed + 20, 7.0, 4) - 0.5) * 0.55
    mod = 1.0 + rough * (0.55 * ridge - 0.36 + 0.08 * (crag - 0.5) + (gully - 0.5) * 0.25)
    return meadow_h + above * mod + hummock * (1 - E.smoothstep(0, 4, above))


def river_paths(cam, fd: dict, seed: int = 7, taper: bool = True) -> list[dict]:
    """The phase-2 river paths (build_heightmap: same rng draws, same meander rule) continued past their phase-2 end
    until RIVER_TAIL_ALONG behind the rest camera. Points every 0.2 m; s = metres from the HoMM3 exit."""
    f, _ = E.heading(cam)
    rng = np.random.default_rng(seed)
    out = []
    for e in fd["heightmap"]["exits"]:
        p = np.array([e["entry"][0], e["entry"][2]])
        d = np.array(e["dir"])
        hw = max(0.5, e["halfWidth"])
        level = float(e["entry"][1]) - 0.05
        phase = rng.uniform(0, 6.28)
        pts, end2 = [], None
        for i in range(4000):
            pts.append(p.copy())
            tgt = -f[[0, 2]]
            ang = math.atan2(d[1], d[0])
            tang = math.atan2(tgt[1], tgt[0])
            s_m = i * 0.2
            want = tang + E.MEANDER_AMP * math.sin(2 * math.pi * s_m / E.MEANDER_LEN + phase) * E.smoothstep(0.0, 6.0, s_m)
            ang += 0.1 * math.atan2(math.sin(want - ang), math.cos(want - ang))
            d = np.array([math.cos(ang), math.sin(ang)])
            p = p + d * 0.2
            along = (p[0] - cam["pos"][0]) * f[0] + (p[1] - cam["pos"][2]) * f[2]
            if end2 is None and along < 2.0:
                end2 = i + 1           # where phase 2 stopped
            if along < RIVER_TAIL_ALONG:
                break
        pts = np.array(pts)
        s = np.arange(len(pts)) * 0.2
        out.append({"pts": pts, "s": s, "hw": hw, "level": level, "phase": phase, "phase2End": end2, "exit": e,
                    "taper": taper})
    return out


def river_width(rv: dict, idx: np.ndarray) -> np.ndarray:
    """Half-width along the path (the phase-2 carve: widening toward the camera, pools and narrows)."""
    s = idx * 0.2
    w = rv["hw"] * (1.0 + 0.3 * np.clip(s / 10.0, 0, 1))
    if rv["taper"]:
        w = E.entry_taper(w, rv["exit"], s)
    return w * (1.0 + 0.18 * np.sin(s * 2 * math.pi / (E.MEANDER_LEN * 0.55) + rv["phase"] * 1.7))


def carve(field: Field, X, Z, rivers: list[dict]):
    """Carve the continued channels into field.h (the phase-2 bank / bed / surface rule). Returns (channel, wl)."""
    from scipy.spatial import cKDTree

    h = field.h
    channel = np.zeros_like(h)
    wl = np.full_like(h, -1e3)
    for rv in rivers:
        tree = cKDTree(rv["pts"])
        dd, ii = tree.query(np.stack([X.ravel(), Z.ravel()], 1), distance_upper_bound=12.0)
        near = np.isfinite(dd)
        dd, ii = dd[near], ii[near]
        wide = river_width(rv, ii)
        level = rv["level"]
        bed = level - 0.3
        bank = level + 0.12 + 0.35 * np.clip(dd / wide - 1, 0, None)
        hs = h.ravel()[near]
        c = np.clip(1 - (dd / wide) ** 2, 0, 1)
        hs = np.where(dd < wide * 2.5, np.minimum(hs, bank), hs)
        hs = np.where(dd < wide, np.minimum(hs, bed + (level - bed) * (1 - c)), hs)
        hs = np.where(dd < wide * 1.05, np.maximum(hs, level), hs)
        flat = h.reshape(-1)
        flat[np.nonzero(near)[0]] = hs
        ch = channel.reshape(-1)
        ch[np.nonzero(near)[0]] = np.maximum(ch[np.nonzero(near)[0]], (dd < wide * 1.05).astype(np.float32))
        wlf = wl.reshape(-1)
        idx = np.nonzero(near)[0]
        wlf[idx] = np.where(dd < wide * 1.05, np.maximum(wlf[idx], level), wlf[idx])
    return channel, wl


def outer_field(ctx, fd: dict, grid: dict, taper: bool = True) -> tuple[Field, dict]:
    """The outer heightfield over the pan's ground footprint (see the module docstring)."""
    from scipy.ndimage import distance_transform_edt

    cam = ctx.cam
    ang = frame_angles(cam)
    th_l, th_e = ang["thL"], ang["thE"]
    hs = fd["heightmap"]
    meadow_h = float(hs["meadowHeight"])
    # Extent: the polar grid's footprint plus a margin.
    tt = np.linspace(-THETA_MAX - 2, THETA_MAX + 2, 200)
    rr = np.array([0.0, RHO_MAX + 4])
    T_, R_ = np.meshgrid(tt, rr)
    Xb, Zb = polar_to_xz(cam, T_, R_)
    f, r = E.heading(cam)
    back = cam["pos"][[0, 2]] + f[[0, 2]] * ALONG_MIN
    x0 = math.floor(min(Xb.min(), back[0] - RHO_MAX * 0.2) / OUT_RES) * OUT_RES - 2
    x1 = math.ceil(max(Xb.max(), back[0] + RHO_MAX * 0.2) / OUT_RES) * OUT_RES + 2
    z0 = math.floor(min(Zb.min(), back[1]) / OUT_RES) * OUT_RES - 2
    z1 = math.ceil(Zb.max() / OUT_RES) * OUT_RES + 2
    nx, nz = int(round((x1 - x0) / OUT_RES)) + 1, int(round((z1 - z0) / OUT_RES)) + 1
    gz, gx = np.mgrid[0:nz, 0:nx]
    X, Z = x0 + gx * OUT_RES, z0 + gz * OUT_RES
    theta, rad, along = E.polar(cam, X, Z)
    hm = fd["hm"]
    # Walls on both sides (the right one is the phase-2 region B itself where the heightmap has it).
    prof_r = edge_profile(cam, fd["zh"], slice(TW - 3, TW))
    prof_l = edge_profile(cam, fd["zh"], slice(0, 3))
    s_r = E.smoothstep(th_e, th_e + 17.0, theta)
    s_l = E.smoothstep(-th_l, -th_l + 17.0, -theta)
    h_r = wall(X, Z, theta, rad, prof_r, meadow_h, s_r)
    h_l = wall(X, Z, theta, rad, prof_l, meadow_h, s_l, seed=17,
               rough=E.smoothstep(th_l - 1.0, th_l - LEFT_ROUGH_DEG, theta))
    # Near the camera (under / beside the frame bottom): meadow with hummocks; the walls take over with their own
    # profile (it starts at the meadow height).
    side = np.where(theta >= 0, h_r, h_l)
    inb = (X > E.HX0 + 1) & (X < E.HX1 - 1) & (Z > E.HZ0 + 1) & (Z < E.HZ1 - 1)
    h_hm = hm.height(np.clip(X, E.HX0, E.HX1), np.clip(Z, E.HZ0, E.HZ1))
    # Trust the phase-2 heightmap inside its bounds and right of the HoMM3 left edge (region A / B / observed); left
    # of it the heightmap is only a push-pull fill, so the left wall takes over over LEFT_BLEND_DEG.
    w_left = E.smoothstep(th_l, th_l - LEFT_BLEND_DEG, theta)
    base = np.where(inb, h_hm * (1 - w_left) + h_l * w_left, side)
    # Out of the heightmap's bounds behind the camera / at the far right: the side walls; a band of 3 m blends the
    # bound so there is no step.
    dist_in = np.minimum.reduce([X - E.HX0, E.HX1 - X, Z - E.HZ0, E.HZ1 - Z])
    wb = E.smoothstep(1.0, 4.0, dist_in)
    h = base * wb + side * (1 - wb)
    # The frame surface itself (phase-5 grid vertices incl. relief), splatted and blended in so the outer ground
    # meets every frame edge without a step.
    P = grid["P"].reshape(-1, 3)
    keep = grid["keep"].ravel()
    P = P[keep]
    ix = np.round((P[:, 0] - x0) / OUT_RES).astype(int)
    iz = np.round((P[:, 2] - z0) / OUT_RES).astype(int)
    ok = (ix >= 0) & (ix < nx) & (iz >= 0) & (iz < nz)
    obs = np.full((nz, nx), -1e9)
    np.maximum.at(obs, (iz[ok], ix[ok]), P[ok, 1])
    known = obs > -1e8
    obs_f = E.push_pull(np.where(known, obs, 0), known)
    d_obs = distance_transform_edt(~known) * OUT_RES
    b = np.exp(-(d_obs / SEAM_BLEND_M) ** 2)
    h = h * (1 - b) + obs_f * b
    field = Field(x0, z0, OUT_RES, h)
    rivers = river_paths(cam, fd, taper=taper)
    channel, wl = carve(field, X, Z, rivers)
    field.h = cv2.GaussianBlur(field.h, (0, 0), 1.0)
    field.channel = cv2.GaussianBlur(channel, (0, 0), 1.0)
    field.wl = wl
    field.known = known
    info = {"thetaLeft": th_l, "thetaHoMM3Right": th_e, "thetaFrameRight": ang["thR"], "meadowHeight": meadow_h,
            "extent": [x0, z0, x1, z1], "res": OUT_RES, "cells": [nz, nx], "frameSplatShare": float(known.mean()),
            "profileLeftMaxM": float(prof_l.max() - meadow_h), "profileRightMaxM": float(prof_r.max() - meadow_h)}
    return field, rivers, info


# ------------------------------------------------------------------------------------------------ polar mesh
def rho_levels() -> np.ndarray:
    out, r = [RHO_MIN], RHO_MIN
    while r < RHO_MAX:
        r = r + float(np.clip(0.012 * r, 0.06, 2.5))
        out.append(min(r, RHO_MAX))
    return np.array(out)


def frame_depth_grid(ctx, grid: dict) -> np.ndarray:
    """Forward depth of the frame mesh at every pixel (vertex depths, max over each 3x3 neighbourhood: conservative
    against the rasterised surface between vertices); NaN on sky."""
    P = grid["P"]
    zc = (P - ctx.cpos) @ ctx.cam["fwd"]
    zc = np.where(grid["keep"], zc, np.nan).astype(np.float32)
    zmax = cv2.dilate(np.nan_to_num(zc, nan=0.0), np.ones((3, 3), np.uint8))
    zmax = np.where(grid["keep"], zmax, np.nan)
    xs, ys = grid["xs"], grid["ys"]
    gx = np.clip(np.searchsorted(xs, np.arange(W)), 0, len(xs) - 1)
    gy = np.clip(np.searchsorted(ys, np.arange(H)), 0, len(ys) - 1)
    return zmax[np.ix_(gy, gx)]


def polar_mesh(ctx, field: Field, zframe: np.ndarray, sky: np.ndarray) -> dict:
    """Polar grid about the rest camera; frame-interior triangles dropped, frame-edge vertices behind the frame."""
    cam = ctx.cam
    ths = np.arange(-THETA_MAX, THETA_MAX + 1e-6, THETA_STEP)
    rhos = rho_levels()
    T, R = np.meshgrid(ths, rhos)                     # rows = rho, cols = theta
    X, Z = polar_to_xz(cam, T, R)
    Y = field.height(X, Z)
    P = np.stack([X, Y, Z], -1).reshape(-1, 3)
    nth = len(ths)
    j, i = np.meshgrid(np.arange(len(rhos) - 1), np.arange(nth - 1), indexing="ij")
    a = (j * nth + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nth], 1), np.stack([a + 1, a + nth + 1, a + nth], 1)])
    P, tris, st = settle(ctx, P, tris, zframe, sky)
    return {"P": P, "tris": tris, "theta": T.ravel(), "rho": R.ravel(), "nth": nth, "ths": ths, "rhos": rhos, **st}


def settle(ctx, P: np.ndarray, tris: np.ndarray, zframe: np.ndarray, sky: np.ndarray):
    """Aim to preserve the phase-5 default frame: drop triangles wholly EDGE_PX inside the frame; move
    kept vertices that fall inside the frame behind the frame surface along their own rest ray (screen position
    unchanged), or, where the frame shows sky, down to just under the skyline of their column and behind that."""
    cam = ctx.cam
    P = P.copy()
    px, py, zc = E.project(cam, P)
    infr = (px >= 0) & (px <= W) & (py >= 0) & (py <= H) & (zc > 0.05)
    deep = (px >= EDGE_PX) & (px <= W - EDGE_PX) & (py >= EDGE_PX) & (py <= H - EDGE_PX) & (zc > 0.05)
    tris = tris[~deep[tris].all(1)]
    used = np.zeros(len(P), bool)
    used[tris.ravel()] = True
    moved = used & infr
    qx = np.clip(px[moved], 0, W - 1)
    qy = np.clip(py[moved], 0, H - 1)
    xi, yi = np.round(qx).astype(int), np.round(qy).astype(int)
    zf = zframe[yi, xi]
    is_sky = sky[yi, xi] | ~np.isfinite(zf)
    first = np.where((~sky).any(0), np.argmax(~sky, 0), H - 1)   # skyline row per column
    ys_ = np.where(is_sky, np.minimum(first[xi] + 2, H - 1), qy)
    zf2 = zframe[np.round(ys_).astype(int), xi]
    zf2 = np.where(np.isfinite(zf2), zf2, np.nanmax(zframe))
    ztgt = np.maximum(zc[moved], zf2 * (1 + PUSH_REL) + PUSH_ABS)
    P[moved] = ctx.cpos + E.rays(cam, qx, ys_) * ztgt[:, None]
    return P, tris, {"moved": int(moved.sum()), "loweredToSkyline": int(is_sky.sum()), "infr": infr}


# ------------------------------------------------------------------------------------------------ coverage
def coverage_raster(field: Field, mesh: dict) -> dict:
    """Sample final retained triangle heights on the XZ grid; never credit pre-settle or neighboring geometry.

    This is a sampled proxy, not exact ray/triangle visibility. The separately stored frame heightfield is used only
    for rays projecting onto the default frame's terrain, and editor renders decide pixel-level acceptance.
    """
    P = mesh["P"]
    t = mesh["tris"]
    nz, nx = field.h.shape
    outer_h = np.full((nz, nx), -np.inf, np.float32)
    xz = np.stack([(P[:, 0] - field.x0) / field.res, (P[:, 2] - field.z0) / field.res], -1)
    for face in t:
        q = xz[face]
        lo = np.maximum(np.ceil(q.min(0)).astype(int), 0)
        hi = np.minimum(np.floor(q.max(0)).astype(int), [nx - 1, nz - 1])
        if np.any(lo > hi):
            continue
        a, b, c = q
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-10:
            continue
        xx, zz = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        wa = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (zz - c[1])) / den
        wb = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (zz - c[1])) / den
        wc = 1 - wa - wb
        inside = (wa >= -1e-8) & (wb >= -1e-8) & (wc >= -1e-8)
        if inside.any():
            y = wa * P[face[0], 1] + wb * P[face[1], 1] + wc * P[face[2], 1]
            patch = outer_h[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            np.maximum(patch, y, out=patch, where=inside)
    return {"x0": field.x0, "z0": field.z0, "res": field.res, "h": field.h.astype(np.float32),
            "outer_h": outer_h, "covered": np.isfinite(outer_h)}


# ------------------------------------------------------------------------------------------------ texture pieces
def row_density(rho) -> np.ndarray:
    """Radians the camera sees per metre of ground at distance rho (flat ground below the camera, or a slope that
    faces it): texture rows are spent where the view spends pixels."""
    rho = np.asarray(rho, np.float64)
    return np.maximum(CAM_H / (rho * rho + CAM_H * CAM_H), FACE / np.maximum(rho, 1e-3))


def row_map(rho0: float, rho1: float, rad_per_row: float):
    """G(rho) -> row coordinate (0 at rho0), sampled finely (rr, g)."""
    rr = np.linspace(rho0, rho1, 20001)
    g = np.concatenate([[0.0], np.cumsum(0.5 * (row_density(rr[1:]) + row_density(rr[:-1])) * np.diff(rr))]) / rad_per_row
    return rr, g


def piece_layout(mesh: dict) -> list[dict]:
    """Split the outer triangles into texture pieces: theta bucket (left / centre / right) x rho band."""
    th, rho = mesh["theta"], mesh["rho"]
    t = mesh["tris"]
    ct, cr = th[t].mean(1), rho[t].mean(1)
    bucket = np.where(ct < -THETA_SPLIT, 0, np.where(ct > THETA_SPLIT, 2, 1))
    pieces = []
    for b, bname in enumerate(("L", "C", "R")):
        for k, (r0, r1, deg) in enumerate(RHO_BANDS):
            sel = (bucket == b) & (cr >= r0) & (cr < r1)
            if not sel.any():
                continue
            tt = t[sel]
            used = np.unique(tt)
            th0, th1 = float(th[used].min()), float(th[used].max())
            q0, q1 = float(rho[used].min()), float(rho[used].max())
            w = min(MAX_TEX, int(math.ceil((th1 - th0) / deg)))
            rad = math.radians(deg)
            rr, g = row_map(q0, q1, rad)
            h = int(math.ceil(g[-1]))
            if h > MAX_TEX:
                rad *= h / MAX_TEX
                rr, g = row_map(q0, q1, rad)
                h = MAX_TEX
            pieces.append({"name": f"Mesh_Outer{bname}{k}", "tris": tt, "used": used, "th": (th0, th1), "rho": (q0, q1),
                           "size": (max(w, 8), max(h, 8)), "rr": rr, "g": g,
                           "degPerTexel": [(th1 - th0) / max(w, 8), math.degrees(rad)]})
    return pieces


def piece_uv(pc: dict, th, rho) -> np.ndarray:
    """UV of (theta, rho) in a piece: u across theta, v by the row map; image row 0 = the far end (v = 1)."""
    w, h = pc["size"]
    u = (np.asarray(th) - pc["th"][0]) / max(pc["th"][1] - pc["th"][0], 1e-9)
    v = np.interp(rho, pc["rr"], pc["g"]) / pc["g"][-1]
    return np.stack([(u * (w - 1) + 0.5) / w, (v * (h - 1) + 0.5) / h], -1).astype(np.float32)


def river_distance(rivers: list[dict], X, Z) -> np.ndarray:
    """Metres from the nearest outer river's water edge (negative inside the channel)."""
    from scipy.spatial import cKDTree

    out = np.full(np.shape(X), 1e3, np.float64)
    q = np.stack([np.ravel(X), np.ravel(Z)], 1)
    for rv in rivers:
        dd, ii = cKDTree(rv["pts"]).query(q, distance_upper_bound=15.0)
        ok = np.isfinite(dd)
        e = np.full(len(q), 1e3)
        e[ok] = dd[ok] - river_width(rv, ii[ok]) * 1.05
        out = np.minimum(out, e.reshape(out.shape))
    return out


class ToneMap:
    """The frame's low-frequency colour (phase-5 L0, sky gaps filled from the ground) at a point's rest projection,
    and the weight with which an outer texel takes it (1 at the frame edge, e-folding EDGE_TONE_PX outside)."""

    def __init__(self, ctx, S5: dict):
        L0 = S5["L0"].astype(np.float32)
        sky = S5["sky"]
        self.L0 = E.fill_from_interior(L0, sky) if sky.any() else L0
        self.cam = ctx.cam

    def __call__(self, P):
        px, py, zc = E.project(self.cam, P)
        front = zc > 0.1
        cx, cy = np.clip(px, 0, W - 1), np.clip(py, 0, H - 1)
        d = np.hypot(np.maximum(0, np.maximum(-px, px - W)), np.maximum(0, np.maximum(-py, py - H)))
        w = np.where(front, np.exp(-d / EDGE_TONE_PX), 0.0).astype(np.float32)
        return N5._sample(self.L0, cx.astype(np.float32), cy.astype(np.float32)), w


def ground_classes(field: Field, meadow_h: float, X, Z):
    """The phase-5 extension classes (slope, height above the meadow, noise) at world points."""
    Y = field.height(X, Z)
    Ns = field.normal(X, Z, eps=1.0).astype(np.float32)
    slope = np.degrees(np.arccos(np.clip(Ns[..., 1], -1, 1)))
    ha = Y - meadow_h
    nz1 = E.fbm(X, Z, 11, 6.0, 3)
    w_rock = E.smoothstep(30, 44, slope + (nz1 - 0.5) * 16) * E.smoothstep(1.5, 4.0, ha)
    w_snow = E.smoothstep(21, 28, ha + (nz1 - 0.5) * 6) * (1 - E.smoothstep(48, 62, slope))
    w_slope = E.smoothstep(0.8, 3.5, ha + (nz1 - 0.5) * 2.0) * (1 - w_rock) * (1 - w_snow)
    w_mead = np.clip(1 - w_rock - w_slope - w_snow, 0, 1)
    return Y, Ns, slope, ha, (w_mead, w_slope, w_rock, w_snow)


def texel_inputs(ctx, field: Field, S5: dict, tone: ToneMap, rivers, meadow_h, th, rho):
    """Per-texel inputs of Synth.colour for outer texels at (theta, rho): the phase-5 extension rules."""
    X, Z = polar_to_xz(ctx.cam, th, rho)
    Y, Ns, slope, ha, (w_mead, w_slope, w_rock, w_snow) = ground_classes(field, meadow_h, X, Z)
    P = np.stack([X, Y, Z], -1)
    wd = river_distance(rivers, X, Z)
    bank = (1 - E.smoothstep(0.5 * N5.BANK_M, N5.BANK_M, wd)).astype(np.float32)
    patch = 0.35 * E.smoothstep(0.66, 0.74, E.fbm(X, Z, N5.SEED + 5, 2.5, 3))
    wx = np.stack([w_mead * (1 - patch) + 0.75 * w_slope, 0.25 * w_slope + patch * w_mead, w_rock, w_snow], -1)
    wx = np.stack([wx[:, 0] * (1 - bank), wx[:, 1] + bank * (wx[:, 0] + 0.5 * wx[:, 2]), wx[:, 2] * (1 - 0.5 * bank),
                   wx[:, 3]], -1)
    wx[wd < 0] = (0, 1, 0, 0)
    wl = (wx / np.maximum(wx.sum(-1, keepdims=True), 1e-6)).astype(np.float32)
    wet = np.where(wd < 0, 1.0, 1 - E.smoothstep(0.0, N5.WET_M, wd)).astype(np.float32)
    cc = {k: np.asarray(v, np.float32) for k, v in S5["classColours"].items()}
    w_near = (1 - E.smoothstep(22, 32, rho)).astype(np.float32)
    C = ((w_mead * w_near)[:, None] * cc["meadow_near"] + (w_mead * (1 - w_near))[:, None] * cc["meadow_mid"]
         + w_slope[:, None] * cc["slope_green"] + w_rock[:, None] * cc["rock"] + w_snow[:, None] * cc["snow"])
    C = C / np.maximum(w_mead + w_slope + w_rock + w_snow, 1e-6)[:, None]
    Ec, ws = tone(P)
    L0 = (C * (1 - ws[:, None]) + Ec * ws[:, None]).astype(np.float32)
    return P, Ns, wl, L0, wet


def bake_piece(ctx, field: Field, S5: dict, synth, tone: ToneMap, rivers, meadow_h, pc: dict, mesh: dict,
               chunk: int = 300000) -> np.ndarray:
    """Linear albedo of one polar piece. Only texels under (a dilation of) the piece's triangles are synthesised;
    the rest take the nearest baked texel (they only reach the screen through mip bleed)."""
    from scipy.ndimage import distance_transform_edt

    w, h = pc["size"]
    uv = piece_uv(pc, mesh["theta"], mesh["rho"])
    pix = np.stack([uv[:, 0] * w, (1 - uv[:, 1]) * h], -1)
    mask = np.zeros((h, w), np.uint8)
    tri = np.round(pix[pc["tris"]] * 4).astype(np.int32)
    for k in range(0, len(tri), 100000):
        cv2.fillPoly(mask, list(tri[k:k + 100000]), 1, lineType=cv2.LINE_8, shift=2)
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8)).astype(bool)
    ys, xs = np.nonzero(mask)
    th = pc["th"][0] + ((xs + 0.5) / w * w - 0.5) / (w - 1) * (pc["th"][1] - pc["th"][0])
    grow = ((h - ys - 0.5) - 0.5) / (h - 1) * pc["g"][-1]
    rho = np.interp(grow, pc["g"], pc["rr"])
    dth = math.radians((pc["th"][1] - pc["th"][0]) / max(w - 1, 1))
    rad_row = math.radians(pc["degPerTexel"][1])
    out = np.zeros((h, w, 3), np.float32)
    for k in range(0, len(xs), chunk):
        s = slice(k, k + chunk)
        P, Ns, wl, L0, wet = texel_inputs(ctx, field, S5, tone, rivers, meadow_h, th[s], rho[s])
        across = rho[s] * dth
        along = rad_row / row_density(rho[s]) / np.maximum(Ns[:, 1], 0.25)
        foot = np.maximum(across, along).astype(np.float32)
        out[ys[s], xs[s]] = synth.colour(P, Ns, foot, rho[s].astype(np.float32), wl, L0, wet)
    if (~mask).any():
        _, (iy, ix) = distance_transform_edt(~mask, return_indices=True)
        out = out[iy, ix]
    mx = out.max(-1, keepdims=True)
    return np.where(mx > 0.95, out * 0.95 / np.maximum(mx, 1e-6), out).astype(np.float32), int(mask.sum())


# ------------------------------------------------------------------------------------------------ water
def water_ribbons(ctx, fd: dict, rivers: list[dict], vfull: np.ndarray, zframe, sky) -> dict:
    """The rivers' outer reaches as ribbons over the continued channels (FlowWater: UV0.x = the shore coordinate
    through a ramp texture, UV1 = (camera-right metres, metres downstream continuing the frame water's v))."""
    _, rgt = E.heading(ctx.cam)
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    Ps, U0, U1, T = [], [], [], []
    base = 0
    rep = []
    for rv in rivers:
        pts, s = rv["pts"][::2], rv["s"][::2]
        idx = np.arange(len(rv["pts"]))[::2]
        tang = np.gradient(pts, axis=0)
        tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
        nrm = np.stack([-tang[:, 1], tang[:, 0]], 1)
        wide = river_width(rv, idx) * 1.05
        P3 = np.stack([pts[:, 0], np.full(len(pts), rv["level"] + 0.01), pts[:, 1]], -1)
        px, py, zc = E.project(ctx.cam, P3)
        m_px = 2 * np.maximum(np.linalg.norm(P3 - ctx.cpos, axis=1), 1.0) * t / H
        # downstream coordinate: the frame water's v at the last path point well inside the frame on water
        ins = (px > 30) & (px < W - 30) & (py > 30) & (py < H - 30) & (zc > 0)
        ok = np.nonzero(ins)[0]
        ok = [i for i in ok if fd["water"][int(py[i]), int(px[i])]]
        if not ok:
            raise SystemExit("periphery water: no in-frame water sample for downstream UV continuity")
        v0 = float(vfull[int(py[ok[-1]]), int(px[ok[-1]])] - s[ok[-1]])
        out_m = E.SHORE_OUT * m_px
        offs = np.stack([-(wide + out_m), -wide, -0.5 * wide, 0 * wide, 0.5 * wide, wide, wide + out_m], 1)
        sd = (wide[:, None] - np.abs(offs)) / m_px[:, None]
        V = P3[:, None, :] + np.stack([nrm[:, 0][:, None] * offs, np.zeros_like(offs), nrm[:, 1][:, None] * offs], -1)
        nc = offs.shape[1]
        V = V.reshape(-1, 3)
        a0 = np.clip((sd + E.SHORE_OUT) / E.SHORE_RANGE, 0, 1).reshape(-1)
        uv0 = np.stack([a0 * (255 / 256) + 0.5 / 256, np.full(len(a0), 0.5)], 1)
        uv1 = np.stack([(V - ctx.cpos) @ rgt, np.repeat(v0 + s, nc)], 1)
        j, i = np.meshgrid(np.arange(len(pts) - 1), np.arange(nc - 1), indexing="ij")
        a = (j * nc + i).ravel()
        tri = np.concatenate([np.stack([a, a + 1, a + nc], 1), np.stack([a + 1, a + nc + 1, a + nc], 1)])
        Ps.append(V); U0.append(uv0); U1.append(uv1); T.append(tri + base)
        base += len(V)
        rep.append({"levelM": round(rv["level"], 3), "pathM": round(float(s[-1]), 1), "v0": round(v0, 2),
                    "phase2EndM": round(rv["phase2End"] * 0.2, 1) if rv["phase2End"] else None})
    P = np.concatenate(Ps)
    tris = np.concatenate(T)
    P, tris, st = settle(ctx, P, tris, zframe, sky)
    used = np.unique(tris)
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    paint = fd["paint"]
    hw = fd["water"][:TH, :TW]
    col = np.median(paint[hw], 0) if hw.any() else np.array([150.0, 170.0, 190.0])
    tint = np.zeros((4, 256, 4), np.uint8)
    tint[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
    tint[..., 3] = np.arange(256, dtype=np.uint8)[None]
    return {"P": P[used], "n": np.tile([0.0, 1.0, 0.0], (len(used), 1)), "uv0": np.concatenate(U0)[used].astype(np.float32),
            "uv1": np.concatenate(U1)[used].astype(np.float32), "tris": remap[tris], "tint": tint, "rivers": rep,
            "moved": st["moved"]}


# ------------------------------------------------------------------------------------------------ scatter
def outside_frame(ctx, base: np.ndarray, hgt: np.ndarray, rad: np.ndarray, margin: float = 3.0) -> np.ndarray:
    """True where an upright box (base, height, radius) projects wholly outside the default frame."""
    ok = np.ones(len(base), bool)
    for dx in (-1, 1):
        for dz in (-1, 1):
            for dy in (0, 1):
                c = base + np.stack([dx * rad, dy * hgt, dz * rad], 1)
                px, py, zc = E.project(ctx.cam, c)
                inside = (zc > 0.05) & (px > -margin) & (px < W + margin) & (py > -margin) & (py < H + margin)
                ok &= ~inside
    # a box can straddle the frame with every corner outside only when it is larger than the frame: not here
    return ok


def scatter_sites(ctx, field: Field, meadow_h: float, rivers, rng, taken_xz: np.ndarray) -> dict:
    """World Poisson sites on the outer ground: conifer clusters (world noise, denser on the valley slopes), bushes
    at the cluster rims and along the banks, boulders on rocky ground and the banks."""
    from scipy.spatial import cKDTree

    x0, z0 = field.x0, field.z0
    nz, nx = field.h.shape
    area = nx * nz * field.res ** 2
    out = {}
    tree_pts: list = []
    kd_taken = cKDTree(taken_xz) if len(taken_xz) else None
    for kid, (kind, spacing) in enumerate((("tree", TREE_SPACING), ("bush", BUSH_SPACING), ("rock", ROCK_SPACING))):
        n = int(area / (spacing * spacing) * (1.2 if kind == "tree" else 4.0))
        X = x0 + rng.random(n) * (nx - 1) * field.res
        Z = z0 + rng.random(n) * (nz - 1) * field.res
        th, rho, _ = E.polar(ctx.cam, X, Z)
        keep = (np.abs(th) < THETA_MAX - 2) & (rho > FOREST_RHO[0]) & (rho < FOREST_RHO[1])
        X, Z, th, rho = X[keep], Z[keep], th[keep], rho[keep]
        Y, Ns, slope, ha, (w_mead, w_slope, w_rock, w_snow) = ground_classes(field, meadow_h, X, Z)
        wd = river_distance(rivers, X, Z)
        clus = E.fbm(X, Z, SEED + 3, 14.0, 3)
        rim = E.fbm(X, Z, SEED + 9, 5.0, 2)
        if kind == "tree":
            p = E.smoothstep(0.50, 0.58, clus + 0.10 * w_slope) * (1 - E.smoothstep(0.2, 0.5, w_rock)) \
                * (1 - E.smoothstep(0.05, 0.2, w_snow)) * (slope < 34) * (wd > 1.5)
        elif kind == "bush":
            p = ((0.7 * E.smoothstep(0.42, 0.5, clus) * (1 - E.smoothstep(0.52, 0.6, clus))
                  + 0.6 * ((wd > 0.8) & (wd < 3.5)) + 0.25 * E.smoothstep(0.55, 0.65, rim) * w_mead)
                 * (slope < 30) * (w_snow < 0.1) * (wd > 0.8))
        else:
            p = (0.6 * E.smoothstep(0.1, 0.4, w_rock) + 0.4 * ((wd > 0.4) & (wd < 2.5))
                 + 0.3 * w_slope * (rim > 0.6)) * (slope < 42) * (w_snow < 0.4) * (wd > 0.4)
        sel = rng.random(len(X)) < np.clip(p, 0, 1)
        X, Z, Y, rho = X[sel], Z[sel], Y[sel], rho[sel]
        # Poisson thinning against everything placed so far (frame scatter and earlier kinds)
        order = rng.permutation(len(X))
        grid: dict = {}
        cell = spacing
        placed = []
        prev = np.array(tree_pts) if tree_pts else np.zeros((0, 2))
        for q in prev:
            grid.setdefault((int(q[0] // cell), int(q[1] // cell)), []).append((q[0], q[1], -1))
        for k in order:
            x, z = X[k], Z[k]
            if kd_taken is not None and kd_taken.query([x, z])[0] < spacing:
                continue
            gx, gz = int(x // cell), int(z // cell)
            if any((q[0] - x) ** 2 + (q[1] - z) ** 2 < (spacing * spacing if q[2] == kid else 0.36 * spacing * spacing)
                   for ddx in (-1, 0, 1) for ddz in (-1, 0, 1) for q in grid.get((gx + ddx, gz + ddz), ())):
                continue
            grid.setdefault((gx, gz), []).append((x, z, kid))
            placed.append(k)
        placed = np.array(placed, int)
        out[kind] = {"X": X[placed], "Z": Z[placed], "Y": Y[placed], "rho": rho[placed]}
        tree_pts += [np.array([X[k], Z[k]]) for k in placed]
    return out


LODS = ((0.0, 25.0), (25.0, 60.0), (60.0, 1e9))


def merge_instances(proto: dict, base, yaw_deg, s):
    """World-space copies of a prototype mesh (v, n, uv, f; base at 0) at bases with yaw / scale."""
    v, n, uv, f = proto
    Vs, Ns, UVs, Fs = [], [], [], []
    off = 0
    for b, yw, sc in zip(base, yaw_deg, s):
        a = math.radians(yw)
        c, sn = math.cos(a), math.sin(a)
        R = np.array([[c, 0, sn], [0, 1, 0], [-sn, 0, c]])
        Vs.append(b + (v * sc) @ R.T)
        Ns.append(n @ R.T)
        UVs.append(uv)
        Fs.append(f + off)
        off += len(v)
    return np.concatenate(Vs), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Fs)


# ------------------------------------------------------------------------------------------------ stage
SCATTER_PROPS = {   # kind -> (props alternating, height range m, tris per LOD (near, mid, far))
    "tree": (("prop_conifer_a", "prop_conifer_b"), (2.4, 4.0), (1200, 500, 200)),
    "bush": (("prop_bush",), (0.5, 0.95), (900, 300, 120)),
    "rock": (("prop_boulders",), (0.45, 1.1), (900, 300, 120)),
}


def frame_intrusions(ctx, P: np.ndarray, zframe: np.ndarray, sky: np.ndarray) -> int:
    """Outer vertices that would draw over the default frame: inside it and in front of its surface (on sky
    pixels: inside at all, since settle() lowers those to the skyline)."""
    px, py, zc = E.project(ctx.cam, P)
    ins = (zc > 0.05) & (px >= 0) & (px <= W - 1) & (py >= 0) & (py <= H - 1)
    if not ins.any():
        return 0
    xi, yi = np.round(px[ins]).astype(int), np.round(py[ins]).astype(int)
    zf = zframe[yi, xi]
    s = sky[yi, xi]
    bad = np.where(s, True, np.isfinite(zf) & (zc[ins] < zf * (1 + 0.5 * PUSH_REL)))
    return int(bad.sum())


def build(F, ctx, fd: dict, grid: dict, S5: dict, vfull: np.ndarray, water_mat: dict, taken: list,
          fd_place: dict, grid_place: dict) -> dict:
    """Phase 6 stage step: writes the outer terrain / water / scatter bins into F.IN_DIR and the coverage raster into
    F.OUT; returns {"bins": [...], "report": {...}}. F is build_conflux_full3d_scene (passed in: no import cycle)."""
    import copy
    import time

    t0 = time.time()
    field, rivers, info = outer_field(ctx, fd, grid)
    sky = np.isnan(fd["zs"])
    zframe = frame_depth_grid(ctx, grid)
    mesh = polar_mesh(ctx, field, zframe, sky)
    meadow_h = info["meadowHeight"]
    sgn = N5.winding_sign(grid, ctx)
    X0, Z0 = polar_to_xz(ctx.cam, mesh["theta"], mesh["rho"])
    nrm = field.normal(X0, Z0, eps=1.0)
    bins, rep_pieces = [], {}
    synth = S5["synth"]
    tone = ToneMap(ctx, S5)
    texels = 0
    for pc in piece_layout(mesh):
        lin, n_tex = bake_piece(ctx, field, S5, synth, tone, rivers, meadow_h, pc, mesh)
        texels += n_tex
        name = pc["name"]
        Image.fromarray((E.lin_to_srgb(lin) * 255 + 0.5).astype(np.uint8)).save(F.IN_DIR / f"{name}_albedo.png")
        del lin
        used = pc["used"]
        remap = np.full(len(mesh["P"]), -1)
        remap[used] = np.arange(len(used))
        v = mesh["P"][used]
        tl = remap[pc["tris"]]
        f = N5.orient(v, tl, nrm[used][tl].mean(1), sgn)
        uv = piece_uv(pc, mesh["theta"][used], mesh["rho"][used])
        F.write_bin(F.IN_DIR / f"{name}.bytes", ctx.local(v), ctx.local_dir(nrm[used]), uv, [f])
        bins.append({"name": name, "mesh": f"{F.ASSET_ROOT}/{name}.bytes", "texture": f"{F.ASSET_ROOT}/{name}_albedo.png",
                     "kind": "lit", "maxSize": MAX_TEX, "mipBias": F.TERRAIN_MIP_BIAS, "aniso": F.TERRAIN_ANISO})
        rep_pieces[name] = {"size": list(pc["size"]), "thetaDeg": [round(x, 2) for x in pc["th"]],
                            "rhoM": [round(x, 1) for x in pc["rho"]], "tris": int(len(f)), "verts": int(len(used)),
                            "degPerTexel": [round(x, 4) for x in pc["degPerTexel"]], "texelsBaked": n_tex}
    t_bake = time.time() - t0

    # water: the rivers' outer reaches
    wr = water_ribbons(ctx, fd, rivers, vfull, zframe, sky)
    Image.fromarray(wr["tint"]).save(F.IN_DIR / "water_outer_tint.png")
    wmat = copy.deepcopy(water_mat)
    for t in wmat["textures"]:
        if t["prop"] == "_MainTex":
            t["path"] = f"{F.ASSET_ROOT}/water_outer_tint.png"
            t["clamp"] = True
    wf = N5.orient(wr["P"], wr["tris"], np.tile([0.0, 1.0, 0.0], (len(wr["tris"]), 1)), sgn)
    bins.append(F.fxmesh_row("Fx_WaterOuter", ctx.local(wr["P"]), ctx.local_dir(wr["n"]), wr["uv0"], wf, wmat,
                             uv2=wr["uv1"]))

    # scatter: the scene's own Meshy props (no new credits), merged per prop per distance band
    rng = np.random.default_rng(SEED)
    txz = np.asarray(taken, np.float64)[:, [0, 2]] if len(taken) else np.zeros((0, 2))
    # Sites come from the placement frame (fd_place / grid_place: the channels without the entry taper), so the
    # taper reshapes the rendered channel and leaves the scatter's draws, and so every site, where they were. Sites
    # it would move lie at the HoMM3 exits, inside the rest frame, where outside_frame drops them anyway.
    field_place, rivers_place, _ = outer_field(ctx, fd_place, grid_place, taper=False)
    sites = scatter_sites(ctx, field_place, meadow_h, rivers_place, rng, txz)
    scat_rep = {}
    protos: dict = {}
    for kind, (pnames, (h0, h1), lod_tris) in SCATTER_PROPS.items():
        s = sites[kind]
        base = np.stack([s["X"], s["Y"], s["Z"]], 1)
        hgt = rng.uniform(h0, h1, len(base))
        yaw = rng.uniform(0, 360, len(base))
        ok = outside_frame(ctx, base, hgt, 0.35 * hgt)
        which = np.arange(len(base)) % len(pnames)
        for pi, pname in enumerate(pnames):
            glb = F.MESHY / pname / F.B.MESH_ATTEMPT / "model.glb"
            if not glb.is_file():
                raise SystemExit(f"periphery scatter: prop mesh missing: {glb}")
            v_full, n_full, uv_full, f_full = F.load_glb_full(glb)
            lo, hi = v_full.min(0), v_full.max(0)
            ctr = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
            mh = float(hi[1] - lo[1])
            for k, (r0, r1) in enumerate(LODS):
                sel = ok & (which == pi) & (s["rho"] >= r0) & (s["rho"] < r1)
                if not sel.any():
                    continue
                key = (pname, k)
                if key not in protos:
                    v, n, uv, f = F.decimate(v_full, n_full, uv_full, f_full, lod_tris[k])
                    protos[key] = (v - ctr, n, uv, f)
                b = base[sel] - np.stack([np.zeros(sel.sum()), 0.08 * hgt[sel], np.zeros(sel.sum())], 1)
                V, Nn, UV, Fc = merge_instances(protos[key], b, yaw[sel], hgt[sel] / mh)
                name = f"Mesh_Outer_{pname.replace('prop_', '')}_{k}"
                F.write_bin(F.IN_DIR / f"{name}.bytes", ctx.local(V), ctx.local_dir(Nn), UV, [Fc])
                bins.append({"name": name, "mesh": f"{F.ASSET_ROOT}/{name}.bytes",
                             "texture": f"{F.ASSET_ROOT}/{pname}_albedo.png", "kind": "lit", "maxSize": 1024})
                scat_rep[name] = {"instances": int(sel.sum()), "tris": int(len(Fc)),
                                  "rhoM": [r0, r1 if r1 < 1e8 else None]}
        scat_rep[f"_{kind}"] = {"sites": int(len(base)), "outsideFrame": int(ok.sum())}

    # coverage raster + registration check
    cov = coverage_raster(field, mesh)
    intr = frame_intrusions(ctx, mesh["P"][np.unique(mesh["tris"])], zframe, sky) \
        + frame_intrusions(ctx, wr["P"], zframe, sky)
    if intr:
        raise SystemExit(f"periphery: {intr} outer vertices draw over the default frame (registration broken)")
    F.OUT.mkdir(parents=True, exist_ok=True)
    npz = F.OUT / "pan_coverage.npz"
    np.savez_compressed(npz, x0=cov["x0"], z0=cov["z0"], res=cov["res"], h=cov["h"],
                        outer_h=cov["outer_h"], covered=cov["covered"],
                        cam_pos=ctx.cam["pos"], cam_fwd=ctx.cam["fwd"], cam_up=ctx.cam["up"],
                        cam_right=ctx.cam["right"], fov=ctx.cam["fov"], frame_wh=np.array([W, H]),
                        frame_sky=sky, C=ctx.C, cpos=ctx.cpos, depth_scale=ctx.scale,
                        dome_r=F.DOME_R, sky_az=np.array(E.SKY_AZ), sky_el=np.array(E.SKY_EL))
    report = {
        "request": "2026-09-27: the default camera pans past the projected terrain on the left and right; fill the "
                   "outside in the vanilla idiom",
        "panSource": "vanilla_city_camera_pan.json (cityHuman2 BhCityCameraController / SoCityCameraSettings human2)",
        "vanillaReference": {"scene": "cityHuman2", "terrainAzimuthDeg": [-97, 139], "terrainRhoMaxM": 140,
                             "note": "terrain + grass_mountain hills all round the camera's sweep; conifer and rock "
                                     "dressing in the mid field"},
        "field": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in info.items()},
        "mesh": {"thetaDeg": [-THETA_MAX, THETA_MAX], "rhoM": [RHO_MIN, RHO_MAX], "verts": int(len(mesh["P"])),
                 "tris": int(len(mesh["tris"])), "movedBehindFrame": mesh["moved"],
                 "loweredToSkyline": mesh["loweredToSkyline"], "frameIntrusions": intr},
        "pieces": rep_pieces, "texelsBaked": texels, "bakeSeconds": round(t_bake, 1),
        "albedo": "phase-5 synthesis (vanilla terrain textures, world space); low-frequency colour from the painting's "
                  f"class colours, toned to the frame edge colour (e-folding {EDGE_TONE_PX} 1080p px)",
        "water": {"tris": int(len(wf)), "rivers": wr["rivers"], "movedBehindFrame": wr["moved"]},
        "scatter": scat_rep,
        "coverage": {"file": npz.name, "sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
                     "cells": list(cov["covered"].shape), "coveredShare": round(float(cov["covered"].mean()), 4)},
        "meshyCredits": 0,
        "registration": "outer triangles EDGE_PX inside the frame dropped; kept in-frame vertices moved back along "
                        "their rest ray behind the frame surface; scatter only where the whole instance box projects "
                        "outside the frame. Vertex intrusion check only; editor pixels must verify the default frame",
    }
    return {"bins": bins, "report": report}
