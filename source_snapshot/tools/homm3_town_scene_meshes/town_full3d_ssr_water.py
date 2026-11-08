#!/usr/bin/env python3
"""Screen-space-reflection water for a full-3D town candidate (prototype; Cove and Fortress).

    TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=ssr_v1 python tools/homm3_town_scene_meshes/town_full3d_ssr_water.py stage
    ...                                                                                     town_full3d_ssr_water.py preview
    ...                                                                                     town_full3d_ssr_water.py sheet --before pb_v1

The Cove lagoon and the Fortress swamp are painted into the terrain albedo (Mesh_Terrain*, Hex/Lit): there is no water
mesh beyond the buildings' Fx_Water_* strips (waterfalls, whirlpools, the Fortress drawbridge moat), which stay
FlowWater. This lane:
  mask     classifies the painted water in frame space (floor height + colour + texture + ripple anisotropy, the
           hand-set per-town parameters in TOWNS) on the candidate's own staged terrain albedo;
  stage    copies the terrain triangles under the (dilated) mask into Fx_SsrWater_<piece> fxmesh bins on the
           environment prefab - the same prefab-frame vertices, so the water lies exactly on the floor it replaces
           (the shader's Offset -1,-1 wins the tie) - with the painting's world up as the normal, uv0 = a frame-space
           tint texture, uv2 = world XZ metres. The tint is the floor's rest-lit colour with the baked reflections
           painted out (a robust body colour plus a small share of the masked low-pass and of the fine ripple detail);
           its alpha is FlowWater's shore coordinate. Writes stage_report["ssrWater"], which write_catalog turns into
           catalog waterLook.screenSpaceReflection (requiresCameraDepthTexture) and the bundleShaders entry, and rewrites the catalog
           keeping every key the fresh catalog does not own (the props block), as town_t2_props.py stage does;
  preview  an offline composite of the tint over the seed candidate's rest render (no Unity, no SSR term);
  sheet    side-by-side review sheets of this candidate's editor renders against another candidate's.
Opt-in: only a candidate whose stage report carries ssrWater ships the shader; the base outputs are refused, and
every other town's catalog is unchanged. Upright sprites that paint their own reflection (Cove tbcvnmp1 waterfall,
tbcvsay1/2 stilt houses) are not touched: their footing sits on the reflection's bottom row (see the doc).
Proof tier: generated artifact + editor render; unproven in game. Doc: docs/homm3_cove_t2_town_buildings.md (SSR water).
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_ground as G  # noqa: E402

SHADER = "Homm3Town/SsrWater"
SHADER_FILE = "Homm3TownSsrWater.shader"
SCHEMA = "town_full3d_ssr_water.v1"
RECT_W, RECT_H = SC.TW, SC.TH          # the painted rect (1440 x 673) inside the 1920 x 1080 frame
SHORE_OUT, SHORE_RANGE, FEATHER = 6.0, 32.0, 4.0
SELECT_DILATE = 9                      # px: triangles kept around the mask (covers the shore feather)

# Hand-set per painting (measured on the pb_v1 albedo, 2026-09-30; overlays in the ssr_v1 candidate's work/).
#   ytop      floor height (painting world m): water lies below it
#   poly      optional painting-px polygon (x1.8 to frame px) of the floor inside the painted rect
#   Lmax/Cmax/amin  dark water: CIELAB L*, chroma and a* bounds;  Lwarm  sunset-reflection L* bound (0 = off)
#   texmax    horizontal-gradient texture bound; anisomax  ripple anisotropy bound outside the painted rect
#             (anisoNear: the near band below it, where the painted rocks are)
#   bayClose  px: close the dry (non-water) region so rocks keep their whole painted outline (0 = off)
#   holeFill  enclosed dark, non-green holes (baked reflections of the banks) folded into the water
TOWNS = {
    "cove": {"mask": {"ytop": -6.3, "Lmax": 20, "Cmax": 14, "amin": -3, "Lwarm": 50, "texmax": 0.9,
                      "anisomax": 0.55, "anisoNear": 0.4, "win": 21, "bayClose": 15},
             "tint": {"bodyShare": 0.4, "keepLow": 0.25, "keepHigh": 0.35, "lowSigma": 24},
             # the MoGe-depth cove is 3-4x deeper than the march was tuned for: longer reach (fade starts ~4.6x eye
             # depth instead of ~1.25x) so the cliff and buildings still reflect across the whole lagoon
             "floats": {"_Reflect": 1.0, "_F0": 0.05, "_ReflectMin": 0.06, "_MissReflect": 0.35, "_Distort": 0.05,
                        "_Glint": 0.1, "_SpecStrength": 0.25, "_NormalStrength": 0.25, "_Ripple": 0.15,
                        "_Deep": 0.25, "_SsrSteps": 64, "_SsrGrow": 1.1}},
    "fortress": {"mask": {"ytop": -4.8, "poly": [[0, 190], [100, 180], [200, 172], [300, 168], [420, 165], [500, 162],
                                                 [600, 165], [700, 172], [800, 185], [800, 374], [0, 374]],
                          "Lmax": 22, "Cmax": 14, "amin": -9, "Lwarm": 0, "texmax": 0.7, "anisomax": 0.6, "win": 21,
                          "holeFill": {"greenA": -9, "greenL": 18, "maxArea": 60000, "enclosed": 0.6, "Lmax": 20,
                                       "greenShare": 0.2}},
                 "tint": {"bodyShare": 0.4, "keepLow": 0.2, "keepHigh": 0.2, "lowSigma": 24},
                 "floats": {"_Reflect": 1.0, "_F0": 0.04, "_ReflectMin": 0.06, "_MissReflect": 0.35, "_Distort": 0.05,
                            "_Glint": 0.1, "_SpecStrength": 0.25, "_NormalStrength": 0.25, "_Ripple": 0.15,
                            "_Deep": 0.25}},
}


def town() -> dict:
    if SC.FACTION not in TOWNS:
        raise SystemExit(f"ssr water: no hand-set parameters for {SC.FACTION} (prototype towns: {sorted(TOWNS)})")
    if not S.CANDIDATE:
        raise SystemExit("ssr water: opt-in per candidate only - set TOWN_FULL3D_CANDIDATE (the base outputs are "
                         "the installed 'before')")
    return TOWNS[SC.FACTION]


def read_bin(p: Path):
    b = p.read_bytes()
    nv, ns = struct.unpack_from("<ii", b, 0)
    o = 8
    v = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3).astype(np.float64)
    o += nv * 12
    n = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3).astype(np.float64)
    o += nv * 12
    uv = np.frombuffer(b, np.float32, nv * 2, o).reshape(-1, 2).astype(np.float64)
    o += nv * 8
    tris = []
    for _ in range(ns):
        c, = struct.unpack_from("<i", b, o)
        o += 4
        tris.append(np.frombuffer(b, np.int32, c, o).reshape(-1, 3))
        o += c * 4
    return v, n, uv, np.concatenate(tris)


def terrain_pieces() -> list[dict]:
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    env = S.STAGE / S.ENV_KEY
    out = []
    for pc in rep["terrain"]["pieces"]:
        mesh = env / f"{pc['name']}.bytes"
        if not mesh.is_file():
            raise SystemExit(f"ssr water: terrain piece {mesh} is not staged")
        out.append({**pc, "mesh": mesh, "albedo": env / f"{pc['name']}_albedo.png"})
    return out


def owner_of(px, py) -> np.ndarray:
    """Frame px -> the terrain piece that owns it (one water layer per px where the piece boxes overlap)."""
    return np.where(py < 700, 0, np.where(px < 960, 1, 2))


def floor_frame(sc: S.Scene, pieces: list[dict]):
    """Frame-space floor: albedo (sRGB uint8), world height Y and the rest-lit linear colour (the lab Hex/Lit
    formula with the candidate's own rig), each from the piece that owns the px."""
    from scipy.spatial import cKDTree
    spec = json.loads((S.WORK / "render_spec.json").read_text(encoding="utf-8"))
    rig = {k: np.asarray(v) for k, v in spec["rig"].items()}
    sun = np.asarray(spec["sunDir"], np.float64)
    fill_d, fill_c = np.asarray(spec["fill"]["dir"]), np.asarray(spec["fill"]["color"])
    W, H = SC.W, SC.H
    alb = np.zeros((H, W, 3), np.uint8)
    Y = np.full((H, W), np.nan, np.float32)
    lit = np.zeros((H, W, 3), np.float32)
    gy, gx = np.mgrid[0:H, 0:W]
    own = owner_of(gx, gy)
    names = [p["name"] for p in pieces]
    order = [names.index(n) for n in ("Mesh_Terrain", "Mesh_TerrainNear_0", "Mesh_TerrainNear_1")]
    for oi, pi in enumerate(order):
        pc = pieces[pi]
        x0, y0, x1, y1 = pc["box"]
        im = np.asarray(Image.open(pc["albedo"]).convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS))
        v, n, uv, _ = read_bin(pc["mesh"])
        w = v / sc.scale @ sc.C.T + sc.cpos
        nw = n @ sc.C.T
        nw /= np.linalg.norm(nw, axis=1, keepdims=True) + 1e-12
        fx = x0 + uv[:, 0] * (x1 - x0)
        fy = y0 + (1 - uv[:, 1]) * (y1 - y0)
        sel = own[y0:y1, x0:x1] == oi
        qy, qx = gy[y0:y1, x0:x1][sel], gx[y0:y1, x0:x1][sel]
        _, idx = cKDTree(np.stack([fx, fy], 1)).query(np.stack([qx + 0.5, qy + 0.5], 1))
        alb[qy, qx] = im[qy - y0, qx - x0]
        Y[qy, qx] = w[idx, 1]
        nn = nw[idx]
        ndl = np.clip(nn @ -sun, 0, None)[:, None]
        fdl = np.clip(nn @ -(fill_d / np.linalg.norm(fill_d)), 0, None)[:, None]
        ny = nn[:, 1:2]
        amb = np.where(ny >= 0, rig["ambEq"] + (rig["ambSky"] - rig["ambEq"]) * np.sqrt(np.clip(ny, 0, 1)),
                       rig["ambEq"] + (rig["ambGround"] - rig["ambEq"]) * np.sqrt(np.clip(-ny, 0, 1)))
        a_lin = G.SC_srgb_to_lin(im[qy - y0, qx - x0].astype(np.float32) / 255.0)
        lit[qy, qx] = np.clip(a_lin * (rig["sunColor"] * ndl + fill_c * fdl + amb), 0, 1)
    return alb, Y, lit


def classify(alb: np.ndarray, Y: np.ndarray, P: dict) -> np.ndarray:
    """The painted water in frame space (hand-set rules, TOWNS[town]['mask'])."""
    lab = cv2.cvtColor(cv2.GaussianBlur(alb, (0, 0), 1.5), cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128
    g = cv2.cvtColor(alb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gxs = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
    gys = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    k = P.get("win", 15)
    ex, ey, mean = cv2.blur(gxs, (k, k)), cv2.blur(gys, (k, k)), cv2.blur(g, (k, k))
    aniso = ex / (ey + 1.0)            # painted ripples: horizontal streaks, small x-gradient against y
    tex = ex / (mean + 8.0)
    rect = np.zeros(Y.shape, bool)
    rect[:RECT_H, :RECT_W] = True
    floor = np.nan_to_num(Y, nan=1e9) < P["ytop"]
    if P.get("poly"):
        pm = np.zeros(Y.shape, np.uint8)
        cv2.fillPoly(pm, [np.round(np.asarray(P["poly"], np.float64) * SC.SCALE).astype(np.int32)], 1)
        floor = np.where(rect, pm > 0, floor)
    C = np.hypot(a, b)
    dark = (L < P["Lmax"]) & (C < P["Cmax"]) & (a > P["amin"])
    warm = (L < P["Lwarm"]) & (a > 4) & (b > 0) & (a > 0.35 * b)     # sunset reflection (orange / red)
    amax = np.full(Y.shape, P["anisomax"], np.float32)
    amax[RECT_H:, :] = P.get("anisoNear", P["anisomax"])     # the near band below the painted rect
    c = floor & (dark | warm) & (tex < P["texmax"]) & (rect | (aniso < amax))
    c = cv2.medianBlur(c.astype(np.uint8) * 255, 9) > 0
    c = cv2.morphologyEx(c.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    c = cv2.morphologyEx(c, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool) & floor
    n, lab_, st, _ = cv2.connectedComponentsWithStats(c.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= P.get("minArea", 4000)
    c = keep[lab_]
    n2, l2, s2, _ = cv2.connectedComponentsWithStats((~c).astype(np.uint8), 4)
    small = np.zeros(n2, bool)
    small[1:] = s2[1:, cv2.CC_STAT_AREA] < P.get("holeMax", 400)
    c = c | (small[l2] & floor)
    bay = int(P.get("bayClose", 0))
    if bay:
        # rocks / islands: close the non-water region so the water does not bite bays into a rock's painted top
        dry = cv2.morphologyEx((~c).astype(np.uint8), cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bay, bay))).astype(bool)
        c = c & ~dry
    hf = P.get("holeFill")
    if hf:
        green = (a < hf["greenA"]) & (L > hf["greenL"])
        n3, l3, s3, _ = cv2.connectedComponentsWithStats((floor & ~c).astype(np.uint8), 4)
        for i in range(1, n3):
            if s3[i, cv2.CC_STAT_AREA] > hf["maxArea"]:
                continue
            m = l3 == i
            edge = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~m
            if edge.sum() == 0 or c[edge].mean() < hf["enclosed"]:
                continue
            if np.median(L[m]) < hf["Lmax"] and green[m].mean() < hf["greenShare"]:
                c |= m
    return c


def paint_out(lit: np.ndarray, mask: np.ndarray, P: dict) -> np.ndarray:
    """The water body with the painting's baked reflections removed (linear rgb, frame space). Body = the median of
    the darkest bodyShare of each connected water region; a keepLow share of the masked low-pass keeps the painting's
    broad gradient (the sunset glow toward the horizon) and keepHigh of the fine detail keeps its painted ripples."""
    m = mask.astype(np.float32)
    s = P["lowSigma"]
    low = cv2.GaussianBlur(lit * m[..., None], (0, 0), s) / (cv2.GaussianBlur(m, (0, 0), s)[..., None] + 1e-6)
    fine = cv2.GaussianBlur(lit * m[..., None], (0, 0), 2.0) / (cv2.GaussianBlur(m, (0, 0), 2.0)[..., None] + 1e-6)
    lum = lit @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    body = np.zeros_like(lit)
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        r = lab == i
        cut = np.quantile(lum[r], P["bodyShare"])
        body[r] = np.median(lit[r & (lum <= cut)], 0)
    # outside the mask (the shore band the feather fades through) the body of the nearest region continues
    dist, idx = cv2.distanceTransformWithLabels((~mask).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(mask)
    lut = np.zeros((idx.max() + 1, 2), np.int64)
    lut[idx[ys, xs]] = np.stack([ys, xs], 1)
    near = lut[idx]
    body = body[near[..., 0], near[..., 1]]
    low = low[near[..., 0], near[..., 1]]
    fine_n = np.where(mask[..., None], fine, low)
    out = body * (1 - P["keepLow"]) + low * P["keepLow"] + (fine_n - low) * P["keepHigh"]
    return np.clip(out, 0, 1)


def shore_alpha(mask: np.ndarray) -> np.ndarray:
    inside = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    outside = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
    sd = np.where(mask, inside - 0.5, -(outside - 0.5))
    return np.clip((sd + SHORE_OUT) / SHORE_RANGE, 0, 1)


def mask_overlay(alb: np.ndarray, mask: np.ndarray, path: Path) -> None:
    ov = alb.copy()
    ov[mask] = (ov[mask] * 0.45 + np.array([0, 90, 255]) * 0.55).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(ov).resize((960, 540), Image.LANCZOS).save(path)


def stage() -> dict:
    cfg = town()
    sc = S.Scene()
    pieces = terrain_pieces()
    alb, Y, lit = floor_frame(sc, pieces)
    mask = classify(alb, Y, cfg["mask"])
    tint_lin = paint_out(lit, mask, cfg["tint"])
    alpha = shore_alpha(mask)
    mask_overlay(alb, mask, S.WORK / "ssr_water_mask.png")
    sel_mask = cv2.dilate(mask.astype(np.uint8), np.ones((2 * SELECT_DILATE + 1,) * 2, np.uint8)) > 0
    spec_l, sky_c, _ = S.water_light(sc)
    up_local = sc.local_dir(np.array([[0.0, 1.0, 0.0]]))[0]
    up_local /= np.linalg.norm(up_local)
    env = S.ENV_KEY
    root = S.STAGE
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rows[env]["bins"] = [b for b in rows[env]["bins"] if not b["name"].startswith("Fx_SsrWater_")]
    for stale in (root / env).glob("Fx_SsrWater_*"):
        stale.unlink()
    names = [p["name"] for p in pieces]
    staged, report_pieces = [], []
    floats0 = {"_ShoreRange": SHORE_RANGE, "_ShoreOut": SHORE_OUT, "_Feather": FEATHER, "_Speed": 0.25,
               "_Scale": 0.19, "_Stretch": 1.0, "_NormalScale": 0.25}
    for oi, pn in enumerate(("Mesh_Terrain", "Mesh_TerrainNear_0", "Mesh_TerrainNear_1")):
        pc = pieces[names.index(pn)]
        x0, y0, x1, y1 = pc["box"]
        v, n, uv, tris = read_bin(pc["mesh"])
        fx = x0 + uv[:, 0] * (x1 - x0)
        fy = y0 + (1 - uv[:, 1]) * (y1 - y0)
        cx, cy = fx[tris].mean(1), fy[tris].mean(1)
        cxi = np.clip(cx.astype(np.int64), 0, SC.W - 1)
        cyi = np.clip(cy.astype(np.int64), 0, SC.H - 1)
        hit = sel_mask[cyi, cxi] & (owner_of(cxi, cyi) == oi)
        # a triangle any of whose vertices sits on the mask is kept too (thin channels narrower than a cell)
        vx = np.clip(fx.astype(np.int64), 0, SC.W - 1)
        vy = np.clip(fy.astype(np.int64), 0, SC.H - 1)
        hit |= sel_mask[vy, vx][tris].any(1) & (owner_of(cxi, cyi) == oi)
        if not hit.any():
            continue
        t = tris[hit]
        used = np.unique(t)
        remap = np.full(len(v), -1, np.int64)
        remap[used] = np.arange(len(used))
        t2 = remap[t].astype(np.int32)
        vv = v[used]
        bx0, by0 = int(math.floor(fx[used].min())), int(math.floor(fy[used].min()))
        bx1, by1 = int(math.ceil(fx[used].max())) + 1, int(math.ceil(fy[used].max())) + 1
        bx0, by0, bx1, by1 = max(bx0, 0), max(by0, 0), min(bx1, SC.W), min(by1, SC.H)
        uv0 = np.stack([(fx[used] - bx0) / (bx1 - bx0), 1 - (fy[used] - by0) / (by1 - by0)], 1)
        w = vv / sc.scale @ sc.C.T + sc.cpos
        uv2 = np.stack([w[:, 0], w[:, 2]], 1).astype(np.float32)
        name = f"Fx_SsrWater_{oi}"
        S.write_bin(root / env / f"{name}.bytes", vv, np.repeat(up_local[None, :], len(vv), 0), uv0, [t2])
        (root / env / f"{name}_uv2.bytes").write_bytes(uv2.tobytes())
        rgb = (G.lin_to_srgb(tint_lin[by0:by1, bx0:bx1]) * 255 + 0.5).astype(np.uint8)
        a8 = (alpha[by0:by1, bx0:bx1] * 255 + 0.5).astype(np.uint8)
        Image.fromarray(np.dstack([rgb, a8]), "RGBA").save(root / env / f"{name}_tint.png")
        floats = {**floats0, **cfg["floats"]}
        mat = {"shader": f"{S.SHADER_DIR}/{SHADER_FILE}",
               "textures": [{"prop": "_MainTex", "path": f"{S.ASSET_ROOT}/{env}/{name}_tint.png",
                             "st": [1.0, 1.0, 0.0, 0.0], "clamp": True, "srgb": True},
                            vtex_row("_Noise", "TileNoise_23_vfx", True),
                            vtex_row("_Noise2", "TileNoise_07_vfx", True),
                            vtex_row("_NormalMap", "WaterNormal", False)],
               "floats": [{"name": k, "value": float(x)} for k, x in floats.items()],
               "colors": [{"name": "_SpecDir", "rgba": [float(spec_l[0]), float(spec_l[1]), float(spec_l[2]), 0.0]},
                          {"name": "_SkyColor", "rgba": [float(sky_c[0]), float(sky_c[1]), float(sky_c[2]), 1.0]}],
               "queue": 0}
        staged.append({"name": name, "mesh": f"{S.ASSET_ROOT}/{env}/{name}.bytes", "kind": "fxmesh",
                       "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0, 1.0],
                       "uv2": f"{S.ASSET_ROOT}/{env}/{name}_uv2.bytes", "material": mat})
        report_pieces.append({"name": name, "fromPiece": pn, "tris": int(len(t2)), "verts": int(len(vv)),
                              "tintBox": [bx0, by0, bx1, by1]})
    if not staged:
        raise SystemExit("ssr water: the mask selected no terrain triangles")
    cur = {b["name"]: b for b in rows[env]["bins"]}
    cur.update({b["name"]: b for b in staged})
    rows[env]["bins"] = [cur[k] for k in sorted(cur)]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    block = {"schema": SCHEMA, "shader": SHADER, "shaderFile": SHADER_FILE, "requiresCameraDepthTexture": True,
             "requiresCameraColorTexture": True, "colorSource": "_CameraColorTexture (pipeline opaque copy; no GrabPass)",
             "depthSource": "_CameraDepthTexture", "pieces": [p["name"] for p in staged],
             "pieceDetail": report_pieces, "waterPx": int(mask.sum()),
             "maskParams": cfg["mask"], "tintParams": cfg["tint"],
             "bakedReflections": "painted out of the water tint inside the mask (body colour + keepLow low-pass + "
                                 "keepHigh fine detail); the terrain albedo under the water is unchanged and covered",
             "uprightSpriteReflections": "not removed (tbcvnmp1 / tbcvsay1 / tbcvsay2 footing sits on the baked "
                                         "reflection's bottom row; a restage is a separate change)",
             "sameAsFlowWater": ["Fx_Water_* strips (waterfalls, whirlpools, moat) keep Homm3Conflux/FlowWater"],
             "proofTier": "generated artifact (offline stage); editor render and runtime unproven"}
    rep["ssrWater"] = block
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    S.write_catalog(sc, carry="previous")   # the props block and every other block it does not own
    np.save(S.WORK / "ssr_water_mask.npy", mask)
    print(json.dumps({k: block[k] for k in ("pieces", "waterPx", "pieceDetail")}, indent=1))
    return block


def vtex_row(prop: str, name: str, srgb: bool) -> dict:
    """A vanilla VFX texture the FlowWater rows already staged in <stage>/vfx (provenance in the catalog)."""
    path = S.STAGE / "vfx" / f"{name}.png"
    if not path.is_file():
        raise SystemExit(f"ssr water: {path} is not staged (the candidate's fx stage copies it)")
    return {"prop": prop, "path": f"{S.ASSET_ROOT}/vfx/{name}.png", "st": [1.0, 1.0, 0.0, 0.0], "clamp": False,
            "srgb": srgb}


def preview(before: str) -> int:
    """Offline: the tint (alpha-blended) over the <before> candidate's rest render, beside the render itself."""
    town()
    sc = S.Scene()
    pieces = terrain_pieces()
    alb, Y, lit = floor_frame(sc, pieces)
    cfg = TOWNS[SC.FACTION]
    mask = classify(alb, Y, cfg["mask"])
    tint = G.lin_to_srgb(paint_out(lit, mask, cfg["tint"]))
    sd = shore_alpha(mask) * SHORE_RANGE - SHORE_OUT
    a = np.clip((sd + FEATHER) / (FEATHER + 0.8), 0, 1)[..., None]
    rest = SC.DATA / "candidates" / before / "renders" / "full3d_full.png"
    base = np.asarray(Image.open(rest).convert("RGB")).astype(np.float32) / 255 if rest.is_file() \
        else alb.astype(np.float32) / 255
    # the rest render shows the floor itself only where nothing stands in front of it: blend there only (the game's
    # depth test keeps buildings, props and dressing in front of the water; this offline preview has no depth)
    vis = (np.abs(base - G.lin_to_srgb(lit)).max(-1) < 0.1).astype(np.float32)
    vis = cv2.GaussianBlur(cv2.morphologyEx(vis, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)), (0, 0), 1.5)[..., None]
    a = a * vis
    out = base * (1 - a) + tint * a
    pair = np.concatenate([base, out], 1)
    p = S.WORK / "ssr_water_preview.png"
    Image.fromarray((pair * 255 + 0.5).astype(np.uint8)).resize((1920, 540), Image.LANCZOS).save(p)
    mask_overlay(alb, mask, S.WORK / "ssr_water_mask.png")
    print(p, int(mask.sum()))
    return 0


def sheet(before: str) -> int:
    """Side-by-side review sheets: <before> candidate render | this candidate's render, per shared image name."""
    town()
    other = SC.DATA / "candidates" / before / "renders"
    names = ["full3d_full.png", "full3d_full_t1.png", "full3d_full_t2.png", "pan_sweep_left.png",
             "pan_sweep_right.png", "pan_default.png", "full3d_full_sway_0.png", "full3d_full_sway_2.png"]
    out_dir = S.RENDERS / "ssr_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for nm in names:
        a, b = other / nm, S.RENDERS / nm
        if not (a.is_file() and b.is_file()):
            continue
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        w, h = 1280, round(1280 * ia.height / ia.width)
        ia, ib = ia.resize((w, h), Image.LANCZOS), ib.resize((w, h), Image.LANCZOS)
        s = Image.new("RGB", (2 * w + 8, h), (40, 40, 40))
        s.paste(ia, (0, 0))
        s.paste(ib, (w + 8, 0))
        p = out_dir / f"{before}_vs_{S.CANDIDATE}_{nm}"
        s.save(p)
        made.append(str(p))
    if not made:
        raise SystemExit(f"sheet: no shared renders between {other} and {S.RENDERS}")
    print("\n".join(made))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["stage", "preview", "sheet"])
    ap.add_argument("--before", default="pb_v1")
    a = ap.parse_args()
    if a.cmd == "stage":
        stage()
        return 0
    if a.cmd == "preview":
        return preview(a.before)
    return sheet(a.before)


if __name__ == "__main__":
    raise SystemExit(main())
