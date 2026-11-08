#!/usr/bin/env python3
"""Full-3D towns, experiment rx_layer: the terrain decomposed by semantic layer instead of one continuous depth sheet.

    TOWN_FULL3D_FACTION=rampart python town_full3d_layer_terrain.py eval  --variant relief  [--seed bgd_v1]
    TOWN_FULL3D_FACTION=rampart TOWN_FULL3D_CANDIDATE=rx_layer_relief python town_full3d_layer_terrain.py stage --variant relief

Why: the image-to-image background depth (depth/img2img_bg.npy, pinned per candidate by work/background_depth.json)
has real depth steps at painted rock, tree, ridge and horizon edges. The lane's terrain (stronghold_full3d_scene
.stage_terrain) is one screen-space sheet over the whole frame, so every step is a stretched curtain once the camera
pans. Here the same depth is split into three layers, each its own mesh, so no triangle bridges a step:

  * ground   the painted walkable ground: the rect's inverse depth with the upright objects and the far band masked
             out, push-pull filled underneath them and smoothed (variant `groundSigmaPx`), so it has no steps; outside
             the rect the lane's own outer heightfield (T.world_field) rebuilt from the ground-only depth (upright
             objects are not splatted into it, so they no longer raise walls at the rect seams); `fieldDepth: "old"`
             builds that outer field from the old coarse map (da_large) instead, which is what removes the right-seam
             wall the new depth raises outside the rect (measured on Rampart and Castle). Texture: the painting,
             inpainted where an upright object or the far band hid the ground at rest.
  * upright  painted objects standing out of the ground (rocks, trees, ridges): pixels nearer than the local ground
             trend by more than `uprightTau` (relative inverse depth), with their own new-map depth (relief) or a
             per-component camera-facing plane (card); internal steps above `cutRel` are cut, never bridged.
  * far      the far band (camera depth >= `farM`: the forest / mountain backdrop at the far cap), extended
             `farBandPx` px down behind every nearer layer so a pan shows far texture there, not sky; left uncut by
             default (`farCutRel` None), since cutting it opened skyline holes.

Every layer's texture is the lane's own albedo bake (G.Baker), de-lit by the normals of whichever layer is in front at
rest, so the rest pose reproduces the painting. Nothing in the shared lane changes: this module is opt-in, writes only
its candidate's environment terrain bins (Mesh_Terrain*, rows.json, catalog) and keeps the frame-depth cache in its own
work dir. `eval` writes nothing under artifacts/: it swaps the seed candidate's staged terrain for the layered one in
memory and runs the lane's streak metric (town_t2_streak_map) plus a hole count (pose px that are drawn in the seed and
empty here). Proof tier: generated artifact (offline raster / editor render); nothing installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

VARIANTS = {
    # relief: upright objects keep the new map's per-pixel depth (internal steps cut)
    "relief": {"uprightTau": 0.06, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
               "upright": "relief", "minUprightPx": 150, "trendSigma": (60.0, 8.0)},
    # card: each upright component a camera-facing plane fitted to its depth (no internal relief)
    "card": {"uprightTau": 0.06, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
             "upright": "card", "minUprightPx": 150, "trendSigma": (60.0, 8.0)},
    # relief with a smoother ground and the upright depth smoothed inside each object
    "relief_s": {"uprightTau": 0.06, "groundSigmaPx": 14.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
                 "upright": "relief_smooth", "minUprightPx": 150, "trendSigma": (60.0, 8.0)},
    # cliffs-as-ground: a high tau keeps only strongly standing objects upright
    # relief + depth-slope rule (standing faces whose depth does not grow down the frame), tufts left to the ground
    "relief_sl": {"uprightTau": 0.08, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
                  "upright": "relief", "minUprightPx": 400, "trendSigma": (60.0, 8.0), "slopeK": 0.3, "minSteepPx": 400},
    "card_sl": {"uprightTau": 0.08, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
                "upright": "card", "minUprightPx": 400, "trendSigma": (60.0, 8.0), "slopeK": 0.3, "minSteepPx": 400},
    "relief_sl_of": {"uprightTau": 0.08, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 64, "cutRel": 0.08,
                     "upright": "relief", "minUprightPx": 400, "trendSigma": (60.0, 8.0), "slopeK": 0.3,
                     "minSteepPx": 400, "fieldDepth": "old"},
    "relief_of": {"uprightTau": 0.06, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 64, "cutRel": 0.08,
                  "upright": "relief", "minUprightPx": 150, "trendSigma": (60.0, 8.0), "fieldDepth": "old"},
    # finalists (Rampart 2026-09-30): slope rule, old-map outer field, upright as cards / as smoothed relief cut at 3 %
    "card_of": {"uprightTau": 0.08, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 64, "cutRel": 0.08,
                "upright": "card", "minUprightPx": 400, "trendSigma": (60.0, 8.0), "slopeK": 0.3,
                "minSteepPx": 400, "fieldDepth": "old"},
    "relief_of_c03": {"uprightTau": 0.08, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 64, "cutRel": 0.03,
                      "upright": "relief_smooth", "minUprightPx": 400, "trendSigma": (60.0, 8.0), "slopeK": 0.3,
                      "minSteepPx": 400, "fieldDepth": "old"},
    "relief_t12": {"uprightTau": 0.12, "groundSigmaPx": 6.0, "farM": 300.0, "farBandPx": 48, "cutRel": 0.08,
                   "upright": "relief", "minUprightPx": 150, "trendSigma": (60.0, 8.0)},
}


def _env_setup(faction: str | None):
    if faction:
        os.environ["TOWN_FULL3D_FACTION"] = faction


# ------------------------------------------------------------------------------------------------ classification
def norm_blur(val, w, sx, sy):
    v = cv2.GaussianBlur((np.where(w > 0, val, 0) * w).astype(np.float32), (0, 0), sx, sigmaY=sy)
    k = cv2.GaussianBlur(w.astype(np.float32), (0, 0), sx, sigmaY=sy)
    return v / np.maximum(k, 1e-6), k


def classify(rd: dict, V: dict) -> dict:
    """Rect masks: sky, far, upright, ground; and the ground's own trend (inverse depth) under everything."""
    import stronghold_full3d_terrain as T
    from scipy.ndimage import binary_dilation, label
    zc, sky = rd["zc"], rd["sky"]
    fin = np.isfinite(zc) & ~sky
    far = fin & (zc >= V["farM"])
    inv = np.where(fin, 1.0 / np.where(fin, zc, 1.0), 0.0)
    near = fin & ~far
    up = np.zeros_like(near)
    sx, sy = V["trendSigma"]
    for _ in range(4):
        w = (near & ~up).astype(np.float32)
        g, k = norm_blur(inv, w, sx, sy)
        g = np.where(k > 1e-3, g, T.push_pull(np.where(k > 1e-3, g, 0), k > 1e-3))
        up = near & (inv > g * (1 + V["uprightTau"]))
    if V.get("slopeK"):
        # depth slope: walkable ground's inverse depth grows down the frame like the floor plane's (k per px); a
        # standing face (a tree, a cliff) keeps its depth down its height. Smoothed so grass noise does not count.
        gy = np.gradient(cv2.GaussianBlur(inv.astype(np.float32), (0, 0), 4.0), axis=0)
        k = float(rd["floor"].k)
        steep = near & (gy < V["slopeK"] * k)
        lab_s, ns = label(steep, np.ones((3, 3), bool))
        sz = np.bincount(lab_s.ravel(), minlength=ns + 1)
        ok = sz >= V.get("minSteepPx", 400)
        ok[0] = False
        up = up | ok[lab_s]
    # hysteresis: grow into the object's own fringe (nearer than the trend by a third of tau)
    weak = near & (inv > g * (1 + V["uprightTau"] / 3))
    for _ in range(6):
        up = binary_dilation(up, np.ones((3, 3), bool)) & weak
    lab, nl = label(up, np.ones((3, 3), bool))
    sizes = np.bincount(lab.ravel(), minlength=nl + 1)
    keep = sizes >= V["minUprightPx"]
    keep[0] = False
    up = keep[lab]
    lab = np.where(up, lab, 0)
    ground = near & ~up
    return {"fin": fin, "far": far, "up": up, "upLabel": lab, "ground": ground, "trendInv": g, "inv": inv}


def ground_rect_depth(cls: dict, V: dict) -> np.ndarray:
    """Ground camera depth over the rect's non-far, non-sky px (and under the upright objects): ground-only inverse
    depth, push-pull filled under the objects, smoothed by groundSigmaPx."""
    import stronghold_full3d_terrain as T
    inv, gm = cls["inv"], cls["ground"]
    s = V["groundSigmaPx"]
    filled = T.push_pull(np.where(gm, inv, 0), gm)
    w = gm.astype(np.float32)
    # smooth with the object px weighted low (they carry the fill, not data)
    w = np.maximum(w, 0.05).astype(np.float32)
    sm, _ = norm_blur(filled, w, s, s)
    dom = cls["fin"] & ~cls["far"]
    out = np.where(dom, 1.0 / np.maximum(sm, 1e-6), np.nan)
    return out


def upright_rect_depth(cls: dict, zc: np.ndarray, zg: np.ndarray, V: dict) -> np.ndarray:
    up, lab = cls["up"], cls["upLabel"]
    z = np.where(up, zc, np.nan)
    mode = V["upright"]
    if mode == "relief_smooth":
        inv, _ = norm_blur(np.where(up, 1.0 / zc, 0), up.astype(np.float32), 2.0, 2.0)
        z = np.where(up, 1.0 / np.maximum(inv, 1e-6), np.nan)
    elif mode == "card":
        ys, xs = np.nonzero(up)
        L = lab[ys, xs]
        zz = np.empty(len(ys))
        for c in np.unique(L):
            s = L == c
            # a camera-facing card: one depth per component (the median inverse depth: its silhouette's bulk)
            zz[s] = 1.0 / np.median(1.0 / zc[ys[s], xs[s]])
        z = np.full_like(zc, np.nan)
        z[ys, xs] = zz
    # never behind the ground under it (an object stands on / in front of the ground)
    return np.where(up, np.minimum(z, zg * 0.995), np.nan)


# ------------------------------------------------------------------------------------------------ frame layers
def rect_depth_old(cam) -> dict:
    """T.rect_depth on the old background depth (depth/da_large.npy), whatever the candidate pins."""
    import stronghold_full3d_common as SC
    import stronghold_full3d_terrain as T
    orig = T.background_disparity
    T.background_disparity = lambda: (np.load(SC.DATA / "depth" / "da_large.npy"), {"source": "da_large"})
    try:
        return T.rect_depth(cam)
    finally:
        T.background_disparity = orig


def frame_layers(sc, V: dict, cache_dir: Path) -> dict:
    """Full-frame (H x W) layer depths: ground (rect + outer field), far (rect far band + far ext, extended under the
    ground skyline), upright (rect only); the outer field rebuilt from the ground + far depth."""
    import stronghold_full3d_common as SC
    import stronghold_full3d_ground as G
    import stronghold_full3d_terrain as T
    from scipy.ndimage import distance_transform_edt
    W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
    cam = sc.cam
    rd = T.rect_depth(cam)
    if SC.HOUSES:
        # TOWN_FULL3D_HOUSES (Castle): the painted houses' relief is carved to the surrounding ground first, exactly as
        # G.frame_depth does for the one-sheet terrain (the placed models stand there instead)
        import town_full3d_houses as HS
        zfull = np.full((H, W), np.nan)
        zfull[:TH, :TW] = rd["zc"]
        rd = {**rd, "zc": HS.carve_depth(zfull)[:TH, :TW]}
    cls = classify(rd, V)
    zc = rd["zc"]
    zg_rect = ground_rect_depth(cls, V)
    zu_rect = upright_rect_depth(cls, zc, zg_rect, V)
    if V.get("fieldDepth") == "old":
        # the outer field (outside the painted rect only: walls, skyline fit) from the old map's coarse depth: the new
        # map's steps feed the field's max splat / push-pull / skyline fit and raise a near wall at the rect seam
        field, finfo = T.world_field(cam, rect_depth_old(cam))
    else:
        # the outer field from ground + far only (no upright splats)
        z_field = np.where(cls["far"], zc, zg_rect)
        field, finfo = T.world_field(cam, {**rd, "zc": z_field})
    # extension rays (own cache: never the shared work/frame_depth.npz)
    ys, xs = np.mgrid[0:H, 0:W]
    ext = (xs >= TW) | (ys >= TH)
    key = hashlib.sha256(np.ascontiguousarray(field.h).tobytes()).hexdigest()[:16]
    cp = cache_dir / f"zext_{key}.npy"
    if cp.is_file():
        zext = np.load(cp)
    else:
        zext = np.full(int(ext.sum()), np.nan)
        px, py = xs[ext] + 0.5, ys[ext] + 0.5
        for i in range(0, len(px), 200000):
            zext[i:i + 200000] = T.raymarch(cam, field, px[i:i + 200000], py[i:i + 200000])
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.save(cp, zext)
    zfull_ext = np.full((H, W), np.nan)
    zfull_ext[ext] = zext
    far_ext = ext & np.isfinite(zfull_ext) & (zfull_ext >= V["farM"])
    # ground layer
    zg = np.full((H, W), np.nan)
    zg[:TH, :TW] = zg_rect
    zg[ext & ~far_ext] = zfull_ext[ext & ~far_ext]
    zg = G.seam_smooth(zg)
    # far layer, extended down behind the ground skyline by farBandPx (nearest far depth, kept behind the ground)
    zf = np.full((H, W), np.nan)
    zf[:TH, :TW] = np.where(cls["far"], zc, np.nan)
    zf[far_ext] = zfull_ext[far_ext]
    zf = G.seam_smooth(zf)
    # upright layer
    zu = np.full((H, W), np.nan)
    zu[:TH, :TW] = zu_rect
    # the far layer continues behind every nearer layer for farBandPx (nearest far depth, kept behind them), so a
    # pan shows far texture past a ground skyline or an upright silhouette, never sky
    fm = np.isfinite(zf)
    dpx, (iy, ix) = distance_transform_edt(~fm, return_indices=True)
    nearer = np.fmin(zg, zu)
    band = (~fm) & (dpx <= V["farBandPx"]) & np.isfinite(nearer)
    zf = np.where(band, np.maximum(zf[iy, ix], nearer * 1.02), zf)
    sky = np.zeros((H, W), bool)
    sky[:TH, :TW] = rd["sky"]
    # visible-at-rest label: 2 upright, 1 ground, 0 far, -1 nothing
    vis = np.full((H, W), -1, np.int8)
    vis[np.isfinite(zf)] = 0
    vis[np.isfinite(zg)] = 1
    vis[np.isfinite(zu)] = 2
    zvis = np.where(vis == 2, zu, np.where(vis == 1, zg, np.where(vis == 0, zf, np.nan)))
    sky_full = ~np.isfinite(zvis)
    return {"rd": rd, "cls": cls, "field": field, "finfo": finfo, "zg": zg, "zf": zf, "zu": zu, "vis": vis,
            "zvis": zvis, "sky": sky_full, "farBand": band,
            "stats": {"uprightPx": int(cls["up"].sum()), "uprightComponents": int(len(np.unique(cls["upLabel"])) - 1),
                      "groundPx": int(cls["ground"].sum()), "farPx": int(cls["far"].sum()),
                      "farBandPx": int(band.sum()), "fieldKey": key}}


def layer_grid(sc, z: np.ndarray, cut_rel: float | None):
    """The lane's screen-space grid over one layer's depth (E.terrain_mesh, grid 3), triangles bridging a relative
    depth step above cut_rel dropped (never stretched)."""
    import conflux_full3d_env as E
    import stronghold_full3d_scene as S
    g = E.terrain_mesh(sc.ctx, z, grid=3)
    g["n"] = S.soften_normals(sc, g)
    if cut_rel is not None and len(g["tris"]):
        P = g["P"].reshape(-1, 3)
        zc = (P - sc.cam["pos"]) @ sc.cam["fwd"]
        zt = zc[g["tris"]]
        ratio = zt.max(1) / np.maximum(zt.min(1), 1e-6)
        g["cut"] = int((ratio > 1 + cut_rel).sum())
        g["tris"] = g["tris"][ratio <= 1 + cut_rel]
    return g


# ------------------------------------------------------------------------------------------------ pieces
def inpaint_hidden(lin: np.ndarray, box, scale: int, hidden: np.ndarray) -> np.ndarray:
    """Replace texels whose frame px is hidden at rest (another layer in front) from the visible texels around them."""
    import stronghold_full3d_ground as G
    hm = G.upsample(hidden.astype(np.float32), box, scale) > 0.25
    if not hm.any():
        return lin
    hm = cv2.dilate(hm.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    srgb = (G.lin_to_srgb(np.clip(lin, 0, 1)) * 255 + 0.5).astype(np.uint8)
    out = cv2.inpaint(srgb, hm.astype(np.uint8), 4, cv2.INPAINT_TELEA)
    o = out.astype(np.float32) / 255
    return np.where(hm[..., None], G.SC_srgb_to_lin(o), lin).astype(np.float32)


def build_pieces(sc, V: dict, cache_dir: Path) -> tuple[list, dict]:
    """[(name, Pworld, n, uv, tris, lin_albedo, extra)] for the layered terrain, and a report."""
    import conflux_full3d_env as E
    import stronghold_full3d_common as SC
    import stronghold_full3d_ground as G
    import stronghold_full3d_scene as S
    W, H = SC.W, SC.H
    t0 = time.time()
    fl = frame_layers(sc, V, cache_dir)
    grids = {"ground": layer_grid(sc, fl["zg"], None), "far": layer_grid(sc, fl["zf"], V.get("farCutRel")),
             "upright": layer_grid(sc, fl["zu"], V["cutRel"])}
    # the front layer per frame px at rest, from the layer meshes themselves (after their cuts): a cut leaves the
    # layer behind visible at rest, so that px keeps the painting there instead of the hidden-region inpaint
    import town_full3d_t2_paint as TP
    Ps, Fs, own, off = [], [], [], 0
    for code, nm in ((0, "far"), (1, "ground"), (2, "upright")):
        g = grids[nm]
        Ps.append(g["P"].reshape(-1, 3)); Fs.append(g["tris"] + off); own.append(np.full(len(g["tris"]), code, np.int8))
        off += len(Ps[-1])
    _, fid = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(Fs), sup=1)
    own = np.concatenate(own)
    vis_mesh = np.where(fid >= 0, own[np.where(fid >= 0, fid, 0)], -1).astype(np.int8)
    rep_vis = {f"restFront_{nm}": int((vis_mesh == c).sum()) for c, nm in ((0, "far"), (1, "ground"), (2, "upright"))}
    rep_vis["restFrontChangedPx"] = int(((vis_mesh != fl["vis"]) & (vis_mesh >= 0)).sum())
    fl["vis"] = np.where(vis_mesh >= 0, vis_mesh, fl["vis"])
    # baker on the visible-at-rest composite; its frame normals = the front layer's own normals
    fd = {"zs": fl["zvis"], "sky": fl["sky"], "ext": None, "escaped": 0}
    baker = G.Baker(sc.ctx, fd, grids["ground"], fl["rd"]["floor"], sc.rig, sc.sun, fl["field"])
    nf = np.zeros((H, W, 3), np.float32)
    for code, nm in ((0, "far"), (1, "ground"), (2, "upright")):
        m = fl["vis"] == code
        if m.any():
            nf[m] = E.frame_normals(grids[nm])[m]
    nf[fl["vis"] < 0] = [0, 1, 0]
    baker.nf = nf
    pieces = []
    rep = {"variant": V, "layers": {**fl["stats"], **rep_vis}, "pieces": []}

    def piece(name, g, sel, box, scale, hidden):
        t = g["tris"][sel]
        if not len(t):
            return
        P = g["P"].reshape(-1, 3)
        n = g["n"].reshape(-1, 3)
        fx, fy = g["fx"].ravel(), g["fy"].ravel()
        used = np.unique(t)
        remap = np.full(len(P), -1)
        remap[used] = np.arange(len(used))
        x0, y0, x1, y1 = box
        uv = np.stack([(fx[used] - x0) / (x1 - x0), 1 - (fy[used] - y0) / (y1 - y0)], -1)
        lin = baker.bake(box, scale)
        lin = inpaint_hidden(lin, box, scale, hidden)
        pieces.append((name, P[used], n[used], uv, remap[t], lin, {"mipBias": S.TERRAIN_MIP_BIAS,
                                                                    "aniso": S.TERRAIN_ANISO}))
        rep["pieces"].append({"name": name, "tris": int(len(t)), "box": list(box), "texelsPerPx": scale,
                              "size": [lin.shape[1], lin.shape[0]]})

    g = grids["ground"]
    fx, fy = g["fx"].ravel(), g["fy"].ravel()
    cy, cx = fy[g["tris"]].mean(1), fx[g["tris"]].mean(1)
    hid_g = fl["vis"] != 1
    piece("Mesh_Terrain", g, cy < G.NEAR_Y, (0, 0, W, G.NEAR_Y + 6), G.MAIN_SCALE, hid_g)
    piece("Mesh_TerrainNear_0", g, (cy >= G.NEAR_Y) & (cx < W / 2), (0, G.NEAR_Y - 6, W // 2 + 6, H), G.NEAR_SCALE, hid_g)
    piece("Mesh_TerrainNear_1", g, (cy >= G.NEAR_Y) & (cx >= W / 2), (W // 2 - 6, G.NEAR_Y - 6, W, H), G.NEAR_SCALE,
          hid_g)
    for nm, pname in (("far", "Mesh_TerrainFar"), ("upright", "Mesh_TerrainUpright")):
        g = grids[nm]
        if not len(g["tris"]):
            continue
        fx, fy = g["fx"].ravel(), g["fy"].ravel()
        vx, vy = fx[np.unique(g["tris"])], fy[np.unique(g["tris"])]
        box = (max(0, int(vx.min()) - 4), max(0, int(vy.min()) - 4), min(W, int(math.ceil(vx.max())) + 4),
               min(H, int(math.ceil(vy.max())) + 4))
        piece(pname, g, np.ones(len(g["tris"]), bool), box, G.MAIN_SCALE, fl["vis"] != (0 if nm == "far" else 2))
        rep[f"{nm}Cut"] = g.get("cut", 0)
    rep["fieldInfo"] = {k: v for k, v in fl["finfo"].items() if k != "extSkyline"}
    rep["seconds"] = round(time.time() - t0, 1)
    fl["baker"], fl["fd"] = baker, fd
    return pieces, rep, fl


# ------------------------------------------------------------------------------------------------ eval
def seed_bins(seed: str, drop_env_terrain: bool):
    """The seed candidate's staged lit bins (town_t2_streak_map.load_bins rules), optionally without its terrain."""
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import town_t2_streak_map as SM
    stage = SC.DATA / "candidates" / seed / "unity_project" / SC.FP.ASSET_ROOT
    rows = json.loads((stage / "rows.json").read_text(encoding="utf-8"))
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES["full"]]
    sc = S.Scene()
    to_world = lambda v: sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T
    out = []
    for k in keys:
        for b in rows.get(k, {}).get("bins", []):
            if not b["name"].startswith("Mesh_") or b.get("kind", "lit") != "lit" or b.get("pos") or b.get("rot"):
                continue
            if drop_env_terrain and k.endswith("environment") and b["name"].startswith("Mesh_Terrain"):
                continue
            v, _, uv, subs = S.read_bin(stage / k / f"{b['name']}.bytes")
            out.append((f"{k[len(S.PREFIX):]}/{b['name']}", to_world(v), np.asarray(uv, np.float64),
                        np.concatenate(subs).reshape(-1, 3), SM.png_size(stage / k / f"{b['name']}_albedo.png")))
    return sc, out


def streak_eval(sc, bins: list, poses: list[str], out: Path | None, ref_z: dict | None = None) -> dict:
    import stronghold_full3d_scene as S
    import town_full3d_t2_paint as TP
    import town_t2_streak_map as SM
    from PIL import Image
    Ps, UVs, Fs, owner, names, texs = [], [], [], [], [], []
    off = 0
    for i, (nm, P, uv, F, wh) in enumerate(bins):
        Ps.append(P); UVs.append(uv); Fs.append(F + off); owner.append(np.full(len(F), i, np.int32))
        names.append(nm); texs.append(wh); off += len(P)
    P, UV, F, owner = np.concatenate(Ps), np.concatenate(UVs), np.concatenate(Fs), np.concatenate(owner)
    texs = np.asarray(texs, np.float64)
    cams = {"default": sc.cam, **S.pan_cams(sc), **{f"orbit_y{y:+d}_p{p:+d}": S.orbit_cam(sc, y, p)
                                                    for y, p in S.ORBITS}}
    res = {}
    zs = {}
    for pose in poses:
        cam = cams[pose]
        z, fid = TP.zbuffer(cam, P, F, sup=SM.SUP)
        vis = fid >= 0
        faces = np.unique(fid[vis])
        s1, s2 = SM.face_stretch(cam, P, UV, F, owner, texs, faces)
        lut = np.zeros(len(F), bool)
        lut[faces[(s1 >= SM.S1_MIN) & (s1 / s2 >= SM.ANISO_MIN)]] = True
        m = vis & lut[np.where(vis, fid, 0)]
        ob = np.where(vis, owner[np.where(vis, fid, 0)], -1)
        per = {}
        for i in np.unique(ob[m]):
            per[names[i]] = int((m & (ob == i)).sum())
        from scipy.ndimage import label as _label
        el, ne = _label(~vis)
        top = np.unique(np.r_[el[0], el[:, 0], el[:, -1]])
        enclosed = (~vis) & ~np.isin(el, top)
        r = {"streakPx": int(m.sum()), "drawnPx": int(vis.sum()), "enclosedEmptyPx": int(enclosed.sum()),
             "terrainStreakPx": int(sum(v for k, v in per.items() if "Mesh_Terrain" in k)),
             "perBin": dict(sorted(per.items(), key=lambda kv: -kv[1])[:8])}
        for rn, rz in (ref_z or {}).items():
            if pose in rz:
                r[f"holePx_{rn}"] = int((np.isfinite(rz[pose]) & ~vis).sum())
        res[pose] = r
        zs[pose] = np.where(vis, z, np.inf)
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            shade = np.where(vis, 70 + (ob * 37) % 120, 20).astype(np.uint8)
            img = np.stack([shade] * 3, -1)
            img[m] = [230, 30, 30]
            for rn, rz in (ref_z or {}).items():
                if pose in rz:
                    img[np.isfinite(rz[pose]) & ~vis] = [0, 120, 255] if rn == "props_v1" else [0, 200, 120]
            img[enclosed] = [255, 0, 255]
            Image.fromarray(img).save(out / f"streak_{pose}.png")
    return res, zs


EVAL_POSES = ["sweep_left", "sweep_right", "sweep_high", "cursor_left", "cursor_right", "default",
              "orbit_y-18_p+6", "orbit_y+18_p+6", "orbit_y+0_p+14"]


def cmd_eval(args) -> int:
    import stronghold_full3d_common as SC
    scratch = Path(args.scratch)
    refs, ref_z = {}, {}
    for rn in (args.seed, "props_v1"):
        cf = scratch / SC.FACTION / f"ref_{rn}.npz"
        cj = scratch / SC.FACTION / f"ref_{rn}.json"
        if cf.is_file() and cj.is_file():
            with np.load(cf) as d:
                ref_z[rn] = {k: d[k] for k in d.files}
            refs[rn] = json.loads(cj.read_text(encoding="utf-8"))
            continue
        sc, seed = seed_bins(rn, drop_env_terrain=False)
        refs[rn], ref_z[rn] = streak_eval(sc, seed, EVAL_POSES, None)
        cf.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cf, **{k: v.astype(np.float32) for k, v in ref_z[rn].items()})
        cj.write_text(json.dumps(refs[rn], indent=1), encoding="utf-8")
    ref = refs[args.seed]
    # the other references' own empty px (sky) are only holes where the reference drew something
    ref_z = {k: {p: np.where(np.isfinite(v), v, np.nan) for p, v in d.items()} for k, d in ref_z.items()}
    V = VARIANTS[args.variant]
    import stronghold_full3d_scene as S
    sc = S.Scene()
    pieces, rep, fl = build_pieces(sc, V, scratch / SC.FACTION / "cache")
    sc, keep = seed_bins(args.seed, drop_env_terrain=True)
    mine = [(f"environment/{nm}", P, uv, tris, (lin.shape[1], lin.shape[0])) for nm, P, n, uv, tris, lin, _ in pieces]
    vdir = scratch / SC.FACTION / (args.name or args.variant)
    res, _ = streak_eval(sc, keep + mine, EVAL_POSES, vdir, ref_z)
    out = {"faction": SC.FACTION, "seed": args.seed, "variant": args.variant, "build": rep,
           "refPoses": {rn: {p: {k: v for k, v in r.items() if k != "perBin"} for p, r in rr.items()}
                        for rn, rr in refs.items()}, "poses": res}
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "eval.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    _debug_masks(fl, vdir)
    for p in EVAL_POSES:
        print(f"{p:16s} props_v1 {refs['props_v1'][p]['streakPx']:6d} seed {ref[p]['streakPx']:6d}  {args.variant} "
              f"{res[p]['streakPx']:6d} (terrain {res[p]['terrainStreakPx']:6d}) holes vs seed "
              f"{res[p].get('holePx_' + args.seed)} vs props_v1 {res[p].get('holePx_props_v1')} enclosed "
              f"{res[p]['enclosedEmptyPx']} (refs {ref[p]['enclosedEmptyPx']} / {refs['props_v1'][p]['enclosedEmptyPx']})")
    print(json.dumps(rep["layers"]), rep.get("farCut"), rep.get("uprightCut"))
    return 0


def _debug_masks(fl, vdir: Path) -> None:
    from PIL import Image
    import stronghold_full3d_common as SC
    TW, TH = SC.TW, SC.TH
    paint = fl["rd"]["paint"].astype(np.float32)
    cls = fl["cls"]
    col = paint.copy()
    col[cls["up"]] = col[cls["up"]] * 0.4 + np.array([255, 60, 0]) * 0.6
    col[cls["far"]] = col[cls["far"]] * 0.5 + np.array([0, 80, 255]) * 0.5
    Image.fromarray(col.clip(0, 255).astype(np.uint8)).save(vdir / "layers_rect.png")


# ------------------------------------------------------------------------------------------------ stage
def cmd_stage(args) -> int:
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    if not S.CANDIDATE.startswith("rx_layer_") or S.CANDIDATE in ("props_v1", "bgd_v1", "pb_v1"):
        raise SystemExit("stage: TOWN_FULL3D_CANDIDATE must be an rx_layer_* candidate")
    if not (S.WORK / "background_depth.json").is_file():
        raise SystemExit("stage: the candidate has no work/background_depth.json pin (copy the seed's)")
    V = VARIANTS[args.variant]
    sc = S.Scene()
    pieces, rep, fl = build_pieces(sc, V, S.WORK / "layer_cache")
    env = S.PREFIX + "environment"
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rows[env]["bins"] = [b for b in rows[env]["bins"] if not b["name"].startswith("Mesh_Terrain")]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for nm, P, n, uv, tris, lin, extra in pieces:
        sc.add_bin(env, nm, P, n, uv, tris, lin, extra=extra, preview=False)
    # the periphery (Mesh_Outer*) is rebuilt from the same field and frame surface: the seed's outer pieces were
    # settled behind the seed's frame mesh and built on its field, so carried over they poke in front of the layered
    # frame's edges at rest (Rampart rx_layer_card 2026-09-30: streaked strips along the left/right/bottom borders)
    import conflux_full3d_env as E
    import stronghold_full3d_periphery as PP
    import stronghold_full3d_terrain as T
    front = E.terrain_mesh(sc.ctx, fl["zvis"], grid=3)
    state = {"cam": sc.cam, "field": fl["field"], "floor": fl["rd"]["floor"], "fd": fl["fd"], "grid": front,
             "baker": fl["baker"]}
    per = PP.build(sc, env, state, S.OUT, T.DOME_R, S.SKY_AZ, S.SKY_EL)
    # the near-field dressing (Mesh_Near_*) is seated on the same outer field
    import stronghold_full3d_nearfield as NF
    near = NF.build(sc, env, state)
    S.save_rows(sc, None, env)
    rp = S.WORK / "stage_report.json"
    old = json.loads(rp.read_text(encoding="utf-8"))
    old["periphery"], old["panCoverage"], old["nearField"] = per["periphery"], per["coverage"], near
    old["layerTerrain"] = json.loads(json.dumps(rep, default=float))
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    S.write_catalog(sc, carry="previous")
    S.load_staged_preview(sc)
    print(S.preview(sc, S.WORK / "preview"))
    print(json.dumps({k: v for k, v in rep.items() if k != "variant"}, default=float)[:2000])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["eval", "stage"])
    ap.add_argument("--variant", default="relief", choices=sorted(VARIANTS) + ["_probe"])
    ap.add_argument("--seed", default="bgd_v1")
    ap.add_argument("--faction", default=None)
    ap.add_argument("--scratch", default="V:/rx_layer_scratch")
    ap.add_argument("--set", action="append", default=[], help="eval only: key=json override of the variant")
    ap.add_argument("--name", default="", help="eval only: output folder name (default the variant)")
    a = ap.parse_args()
    if a.set:
        if a.cmd != "eval":
            raise SystemExit("--set is an eval-only probe; stage a named variant")
        V = dict(VARIANTS[a.variant])
        for kv in a.set:
            k, v = kv.split("=", 1)
            V[k] = json.loads(v)
        VARIANTS["_probe"] = V
        a.variant, a.name = "_probe", a.name or "probe"
    if a.cmd == "eval":
        os.environ["TOWN_FULL3D_CANDIDATE"] = a.seed   # read-only: the seed's depth pin and staged bins
        return cmd_eval(a)
    return cmd_stage(a)


if __name__ == "__main__":
    _env_setup(next((sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == "--faction" and i + 1 < len(sys.argv)),
                    None))
    raise SystemExit(main())
