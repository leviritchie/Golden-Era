#!/usr/bin/env python3
"""Bulwark T2 buildings: fit, stage and review (driven by bulwark_t2_buildings.py; docs/homm3_bulwark_t2_town_buildings.md).

fit    per layer: the Meshy glb (base plate stripped where T2 built one) is registered to the layer's building mask
       (stronghold_full3d_buildings.native_mask at x1.8, the TRIM crop's cut-off pixels are don't-care) under the rest
       camera by town_full3d_houses.Fitter (yaw about world up, uniform scale, foot pixel cast onto the local ground
       plane fitted to the painted terrain around the foot; IoU), repeated over a small set of vertical stretches.
       -> <meshy dir>/<id>/placement.json + placement_viz.png. Candidate data lives in TOWN_FULL3D_CANDIDATE.
stage  per layer, in the candidate's staged Unity project (seeded from the installed candidate): Mesh_Body_<id> is
       replaced by the fitted model. Every triangle the rest camera sees (own-model occlusion only) takes the
       painting's pixels by rest-camera projection (the layer's albedo plate composited over the painting), de-lit by
       the Hex/Lit irradiance of its interpolated normal, so the rest pose reproduces the painting verbatim; every
       other triangle keeps Meshy's own UV and texture (mean/std matched per channel to the building's de-lit front,
       the only colour change, and on Meshy texels only). Mesh_Skirt_<id>: the seed's relief triangles whose rest
       pixel is in the building mask but not under the model (painted ground skirts, missed pieces) are kept with
       their own texture, so no painted pixel of the sprite disappears at rest.
sheet  painting | before (installed candidate) | after, at rest and the three sweeps, plus building zooms.

Proof tier: generated artifact; the bundle / editor render / in-game look need their own runs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
ROOT = SC.ROOT
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_bulwark"
TEX_K = 3                 # front texels per 1080p frame px
FRONT_VIS = 0.3           # share of a triangle's projected area its own rest pixels must cover to take the projection
FRONT_FACING = 0.05       # and its normal . view must exceed this
LIGHT_FLOOR = 0.35        # de-light gain floor (share of the building's median irradiance), as town_full3d_houses
MESHY_TEX = 2048          # the Meshy texture tile in the atlas (texels)
STRETCHES = (0.85, 1.0, 1.2)
SKIRT_DILATE = 2          # frame px the model's rest silhouette is grown before a relief triangle counts as covered
PLATE = {}                # per-layer plate cut override (model-height fraction); default: detected


# ------------------------------------------------------------------------------------------------ model
def load_glb(path: Path) -> dict:
    """Meshy glb -> V (glTF axes, Y up), F, UV (trimesh convention, v up), vn, texture (RGB uint8)."""
    import trimesh
    sc_ = trimesh.load(str(path), force="scene")
    geoms = list(sc_.geometry.values())
    if len(geoms) != 1:
        raise SystemExit(f"{path}: {len(geoms)} geometries (expected one textured Meshy mesh)")
    # apply the node transform
    node = [n for n in sc_.graph.nodes_geometry][0]
    Tm, gname = sc_.graph[node]
    m = geoms[0].copy()
    m.apply_transform(Tm)
    tex = m.visual.material.baseColorTexture
    if tex is None:
        raise SystemExit(f"{path}: no base colour texture")
    return {"V": np.asarray(m.vertices, np.float64), "F": np.asarray(m.faces, np.int64),
            "UV": np.asarray(m.visual.uv, np.float64), "vn": np.asarray(m.vertex_normals, np.float64),
            "tex": np.asarray(tex.convert("RGB")), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def plate_cut(g: dict, lid: str) -> dict:
    """T2 often seats a building on a thin snow plate wider than the building. Detected as the lowest band holding a
    large up-facing area; faces whose centroid lies below plate top + 1% height and outside the xz hull of the
    geometry above it are dropped. Returns the face keep mask and what was measured."""
    V, F = g["V"], g["F"]
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    h = y1 - y0
    tri = V[F]
    c = tri.mean(1)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(n, axis=1)
    ny = n[:, 1] / (2 * area + 1e-12)
    if lid in PLATE:
        top = y0 + PLATE[lid] * h
    else:
        low = (c[:, 1] < y0 + 0.2 * h) & (ny > 0.8)
        if area[low].sum() < 0.15 * area.sum() * 0.2:
            return {"keep": np.ones(len(F), bool), "plate": None}
        # the up-facing area's height histogram: the plate top is its heaviest bin
        hist, edges = np.histogram(c[low, 1], bins=40, range=(y0, y0 + 0.2 * h), weights=area[low])
        top = edges[int(np.argmax(hist)) + 1]
    above = V[V[:, 1] > top + 0.05 * h]
    if len(above) < 50:
        return {"keep": np.ones(len(F), bool), "plate": None}
    hull = cv2.convexHull((above[:, [0, 2]] * 1000).astype(np.float32))
    inside = np.array([cv2.pointPolygonTest(hull, (float(x * 1000), float(z * 1000)), True) for x, z in c[:, [0, 2]]])
    margin = 0.02 * h * 1000
    drop = (c[:, 1] < top + 0.01 * h) & (inside < -margin)
    # the plate's own under side / rim below the building too
    drop |= c[:, 1] < top - 0.005 * h
    keep = ~drop
    return {"keep": keep, "plate": {"topFrac": float((top - y0) / h), "droppedFaces": int(drop.sum()),
                                    "droppedAreaShare": float(area[drop].sum() / area.sum())}}


FIT_FACES = 4000          # the fit registers a decimated copy (silhouette only); stage uses the full mesh


def fit_lod(model: dict) -> dict:
    import fast_simplification
    import trimesh
    if len(model["F"]) <= FIT_FACES:
        return model
    V, F = fast_simplification.simplify(model["V"].astype(np.float32), model["F"].astype(np.int32),
                                        target_reduction=1 - FIT_FACES / len(model["F"]))
    V = V.astype(np.float64)
    tm = trimesh.Trimesh(V, F, process=False)
    rng = np.random.default_rng(0)
    return {**model, "V": V, "F": F.astype(np.int64), "fn": np.asarray(tm.face_normals),
            "gable": np.zeros(len(F), bool), "hull": rng.choice(len(V), min(900, len(V)), replace=False)}


def model_for(lid: str, stretch: float = 1.0) -> dict:
    """The glb as a town_full3d_houses model dict (canonical: base y 0, footprint centred, x extent 1), plus UVs."""
    import trimesh
    src = MESHY / REUSE_SRC.get(lid, lid) / "model.glb"
    g = load_glb(src)
    pc = plate_cut(g, lid)
    F = g["F"][pc["keep"]]
    used = np.unique(F)
    remap = np.full(len(g["V"]), -1)
    remap[used] = np.arange(len(used))
    F = remap[F]
    V = g["V"][used].copy()
    UV = g["UV"][used]
    vn = g["vn"][used]
    V[:, 0] -= (V[:, 0].max() + V[:, 0].min()) / 2
    V[:, 2] -= (V[:, 2].max() + V[:, 2].min()) / 2
    V[:, 1] -= V[:, 1].min()
    k = 1.0 / (V[:, 0].max() - V[:, 0].min())
    V *= k
    V[:, 1] *= stretch
    vn = vn * np.array([1.0, 1.0 / stretch, 1.0])
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    tm = trimesh.Trimesh(V, F, process=False)
    rng = np.random.default_rng(0)
    return {"V": V, "F": F, "fn": np.asarray(tm.face_normals), "vn": vn, "UV": UV, "tex": g["tex"],
            "gable": np.zeros(len(F), bool), "hull": rng.choice(len(V), min(900, len(V)), replace=False),
            "extent": (V.max(0) - V.min(0)).round(4).tolist(), "tris": int(len(F)), "verts": int(len(V)),
            "sha256": g["sha256"], "plate": pc["plate"], "stretch": stretch, "src": str(src.relative_to(ROOT))}


REUSE_SRC: dict = {}


# ------------------------------------------------------------------------------------------------ masks
def frame_mask(lid: str, trim: dict) -> tuple[np.ndarray, np.ndarray]:
    """(building mask, don't-care) in the 1920x1080 frame: the lane's native mask at x1.8; TRIM's cut-off px are
    don't-care (the mesh neither must nor must not cover the painted trail)."""
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    # the lane's mask with the HoMM3 shadow / transparency speckle closed (as the Meshy input was cut)
    m = cv2.morphologyEx(BL.native_mask(L).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
    cut = np.zeros_like(m)
    if lid in trim:
        x0, y0, x1, y1 = trim[lid]
        keep = np.zeros_like(m)
        keep[y0:y1, x0:x1] = True
        cut = m & ~keep
        m = m & keep
    out, dc = np.zeros((374, 800), bool), np.zeros((374, 800), bool)
    x, y = L["x"], L["y"]
    h, w = m.shape
    sy, sx = max(0, -y), max(0, -x)
    ey, ex = min(h, 374 - y), min(w, 800 - x)
    out[y + sy:y + ey, x + sx:x + ex] = m[sy:ey, sx:ex]
    dc[y + sy:y + ey, x + sx:x + ex] = cut[sy:ey, sx:ex]
    M = np.zeros((H, W), bool)
    D = np.zeros((H, W), bool)
    M[:TH, :TW] = cv2.resize(out.astype(np.uint8), (TW, TH), interpolation=cv2.INTER_NEAREST) > 0
    D[:TH, :TW] = cv2.resize(dc.astype(np.uint8), (TW, TH), interpolation=cv2.INTER_NEAREST) > 0
    return M, D


# ------------------------------------------------------------------------------------------------ fit
YAW_WIN = 35.0            # deg either side of the camera-facing yaw (T2 builds the input image as the model's front, +Z)
YAW_STEP = 5.0


class PointGround:
    """The foot pixel's own painted terrain point (the painting without the building is the ground under it): the
    base sits where the foot ray meets the registered terrain. No plane (a castle on its knoll has no ring plane)."""

    def __init__(self, P):
        self.P = P

    def cast(self, cam, u, v):
        x = float(np.clip(u, 0, W - 1.001))
        y = float(np.clip(v, 0, H - 1.001))
        x0, y0 = int(x), int(y)
        fx, fy = x - x0, y - y0
        p = self.P
        return ((p[y0, x0] * (1 - fx) + p[y0, x0 + 1] * fx) * (1 - fy)
                + (p[y0 + 1, x0] * (1 - fx) + p[y0 + 1, x0 + 1] * fx) * fy).astype(np.float64)

    def y(self, x, z):
        return np.full(np.shape(x), np.inf)


def camera_yaw(cam) -> float:
    f = np.asarray(cam["fwd"], np.float64)
    return math.degrees(math.atan2(-f[0], -f[2]))


def fit_one(fz, yaw0: float, s_range) -> dict:
    """Coarse grid over yaw (camera-facing window), log scale and the foot pixel on convex-hull silhouettes, then
    Nelder-Mead from the best four seeds on full silhouettes. IoU over the care region."""
    from scipy.optimize import minimize
    x0, y0 = fz.box[:2]
    ys, xs = np.nonzero(fz.M)
    ux0, uy0, ux1, uy1 = xs.min() + x0, ys.min() + y0, xs.max() + x0, ys.max() + y0
    us = np.linspace(ux0 + 0.2 * (ux1 - ux0), ux1 - 0.2 * (ux1 - ux0), 5)
    vs = np.linspace(uy0 + 0.6 * (uy1 - uy0), uy1, 5)
    ss = np.geomspace(s_range[0], s_range[1], 12)
    yaws = yaw0 + np.arange(-YAW_WIN, YAW_WIN + 0.1, 10.0)
    cand = []
    for yaw in yaws:
        for s_ in ss:
            for u in us:
                for v in vs:
                    cand.append((fz.score(fz.inst(yaw, s_, u, v), False), yaw, s_, u, v))
    cand.sort(key=lambda r: -r[0])
    lo, hi = math.log(s_range[0]), math.log(s_range[1])
    best = None
    for _, yaw, s_, u, v in cand[:4]:
        x0v = np.array([yaw, math.log(s_), u, v])

        def f(x):
            if abs(((x[0] - yaw0 + 180) % 360) - 180) > YAW_WIN:
                return 1.0
            return -fz.score(fz.inst(x[0], math.exp(min(max(x[1], lo), hi)), x[2], x[3]), True)
        r = minimize(f, x0v, method="Nelder-Mead",
                     options={"initial_simplex": np.vstack([x0v, x0v + np.diag([5.0, 0.08, 4.0, 3.0])]),
                              "xatol": 0.3, "fatol": 1e-4, "maxiter": 150})
        if best is None or r.fun < best[0]:
            best = (r.fun, r.x)
    x = best[1]
    ins = fz.inst(x[0], math.exp(min(max(x[1], lo), hi)), x[2], x[3])
    S_ = fz.sil(ins, True)
    c = fz.care
    ins["iou"] = round(float(((S_ & fz.M & c).sum()) / max(((S_ | fz.M) & c).sum(), 1)), 3)
    ins["coverOfMask"] = round(float((S_ & fz.M).sum() / max(fz.M.sum(), 1)), 3)
    ins["yawFromCameraFacing"] = round(float(((ins["yaw"] - yaw0 + 180) % 360) - 180), 1)
    return ins


def fit(ids: list[str], trim: dict) -> dict:
    import stronghold_full3d_scene as S
    import town_full3d_houses as HS
    sc = S.Scene()
    st = S.terrain_state(sc)
    P = st["baker"].P
    sky = st["fd"]["sky"]
    lum = np.zeros((H, W), np.float32)
    t_fov = math.tan(math.radians(sc.cam["fov"]) / 2)
    yaw0 = camera_yaw(sc.cam)
    out = {}
    yy, xx = np.mgrid[0:H, 0:W]
    in_rect = (xx < TW) & (yy < TH)
    for lid in ids:
        t0 = time.time()
        M, D = frame_mask(lid, trim)
        ys, xs = np.nonzero(M)
        pad = 40
        box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad + 1, W), min(ys.max() + pad + 1, H))
        foot = P[ys.max() - 2:ys.max() + 1, int(xs.mean())].astype(np.float64)
        zf = float(np.median(T.project(sc.cam, foot)[2]))
        s0 = (xs.max() - xs.min() + 1) * 2 * zf * t_fov / H
        best = None
        for k in STRETCHES:
            model = model_for(lid, k)
            fz = HS.Fitter(sc, fit_lod(model), M.astype(np.int32), P, sky, lum)
            fz.box = box
            fz.M = M[box[1]:box[3], box[0]:box[2]]
            fz.care = (in_rect & ~D)[box[1]:box[3], box[0]:box[2]]
            fz.ground = PointGround(P)
            fz.fixed = None
            ins = fit_one(fz, yaw0, (0.45 * s0, 2.2 * s0))
            ins["stretch"] = k
            print(lid, "stretch", k, {a: ins[a] for a in ("yawFromCameraFacing", "scale", "iou", "coverOfMask")},
                  flush=True)
            if best is None or ins["iou"] > best[0]["iou"]:
                best = (ins, model)
        ins, model = best
        rep = {"schema": "bulwark_t2_placement.v1", "layer": lid, "model": model["src"], "modelSha256": model["sha256"],
               "plate": model["plate"], "modelTris": model["tris"], "cameraFacingYaw": yaw0, "instance": ins,
               "seconds": round(time.time() - t0, 1)}
        d = MESHY / lid
        (d / "placement.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        viz(sc, lid, model, ins, M)
        out[lid] = {a: ins[a] for a in ("yaw", "scale", "stretch", "iou", "coverOfMask")}
    return out


def placed(model: dict, ins: dict) -> np.ndarray:
    import town_full3d_houses as HS
    return HS.place(model, ins)


def silhouette(sc, V, F) -> np.ndarray:
    px, py, zc = T.project(sc.cam, V)
    q = np.stack([px, py], 1)
    S = np.zeros((H, W), np.uint8)
    ok = (zc[F] > 1e-3).all(1)
    cv2.fillPoly(S, list(np.round(q[F[ok]] * 4).astype(np.int32)), 1, shift=2)
    return S > 0


def viz(sc, lid, model, ins, M):
    paint = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS))
    img = np.zeros((H, W, 3), np.uint8)
    img[:TH, :TW] = (paint * 0.6).astype(np.uint8)
    S = silhouette(sc, placed(model, ins), model["F"])
    img[M & ~S] = (255, 60, 60)
    img[S & ~M] = (60, 120, 255)
    img[S & M] = (img[S & M] * 0.4 + np.array([60, 255, 60]) * 0.6).astype(np.uint8)
    ys, xs = np.nonzero(M | S)
    crop = img[max(ys.min() - 20, 0):ys.max() + 20, max(xs.min() - 20, 0):xs.max() + 20]
    Image.fromarray(crop).save(MESHY / lid / "placement_viz.png")


# ------------------------------------------------------------------------------------------------ stage
def stage(ids: list[str], trim: dict) -> dict:
    import conflux_full3d_env as E
    import stronghold_full3d_ground as G
    import stronghold_full3d_scene as S
    import stronghold_full3d_solids as SL
    import town_full3d_houses as HS
    if not S.CANDIDATE:
        raise SystemExit("stage: set TOWN_FULL3D_CANDIDATE (never the base outputs)")
    sc = S.Scene()
    orig = S.WORK / "t2_orig"          # the seed's relief bins, kept once (the skirt source)
    orig.mkdir(parents=True, exist_ok=True)
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    lays = SC.layers()
    k = TEX_K
    report = {}
    for lid in ids:
        t0 = time.time()
        prefab = S.PREFIX + lid
        body = f"Mesh_Body_{lid}"
        ob = orig / f"{body}.bytes"
        if not ob.is_file():
            shutil.copy2(S.STAGE / prefab / f"{body}.bytes", ob)
            shutil.copy2(S.STAGE / prefab / f"{body}_albedo.png", orig / f"{body}_albedo.png")
        plc = json.loads((MESHY / lid / "placement.json").read_text(encoding="utf-8"))
        ins = plc["instance"]
        model = model_for(lid, ins["stretch"])
        if model["sha256"] != plc["modelSha256"]:
            raise SystemExit(f"{lid}: placement.json was fitted to another model")
        R = HS.rot_y(ins["yaw"])
        V = placed(model, ins)
        Nv = model["vn"] @ R.T
        F = model["F"]
        Fn = model["fn"] * np.array([1.0, 1.0, 1.0])
        # face normals of the placed (stretched, rotated) mesh
        tri = V[F]
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
        # rest buffers: own triangles only
        idb, nb = HS.rest_buffers(sc, [(V, Nv, F, 0)], W * k, H * k)
        own = np.round(idb).astype(np.int64)
        counts = np.bincount(own[own >= 0].ravel(), minlength=len(F))
        px, py, zc = T.project(sc.cam, V)
        q = np.stack([px, py], 1)
        tq = q[F]
        area = 0.5 * np.abs((tq[:, 1, 0] - tq[:, 0, 0]) * (tq[:, 2, 1] - tq[:, 0, 1])
                            - (tq[:, 1, 1] - tq[:, 0, 1]) * (tq[:, 2, 0] - tq[:, 0, 0])) * k * k
        view = sc.cam["pos"] - tri.mean(1)
        view /= np.linalg.norm(view, axis=-1, keepdims=True)
        facing = (fn * view).sum(-1)
        inside = (tq[:, :, 0].max(1) < TW) & (tq[:, :, 1].max(1) < TH) & (tq.min((1, 2)) >= 0)
        vis = counts / np.maximum(area, 1e-6)
        front = inside & (facing > FRONT_FACING) & ((vis >= FRONT_VIS) | ((counts > 0) & (area < 1.0)))
        # the painting as the player sees this level: its albedo plate over the painting (native), then x1.8 x k
        L = lays[lid]
        comp = SC.background_rgba().copy()
        comp.alpha_composite(SC.albedo_sprite(L), (int(L["x"]), int(L["y"])))
        big = np.asarray(comp.convert("RGB").resize((TW * k, TH * k), Image.LANCZOS)).astype(np.float32) / 255
        # front tile box: the front triangles' projection (frame px), inside the rect
        fx = tq[front][:, :, 0]
        fy = tq[front][:, :, 1]
        bx0, by0 = max(int(math.floor(fx.min())) - 2, 0), max(int(math.floor(fy.min())) - 2, 0)
        bx1, by1 = min(int(math.ceil(fx.max())) + 3, TW), min(int(math.ceil(fy.max())) + 3, TH)
        sl = (slice(by0 * k, by1 * k), slice(bx0 * k, bx1 * k))
        crop = G.SC_srgb_to_lin(big[sl])
        idc = own[sl]
        nc = nb[sl]
        mine = idc >= 0
        mine_front = mine & front[np.clip(idc, 0, len(F) - 1)]
        Lr = E.light(nc / (np.linalg.norm(nc, axis=-1, keepdims=True) + 1e-9), sc.rig, sc.sun)
        lm = Lr.mean(-1)
        floor = LIGHT_FLOOR * float(np.median(lm[mine_front]))
        alb = np.clip(crop / np.maximum(Lr, floor), 0, 1).astype(np.float32)
        ftile = SL.back_fill(alb, mine_front, erode_tx=0)
        ftile[mine_front] = alb[mine_front]
        # Meshy texture tile, matched per channel (mean / std, linear) to the de-lit front of this building
        mt = np.asarray(Image.fromarray(model["tex"]).resize((MESHY_TEX, MESHY_TEX), Image.LANCZOS)).astype(np.float32) / 255
        mt = G.SC_srgb_to_lin(mt)
        buv = model["UV"]
        back_used = np.unique(F[~front])
        if len(back_used):
            su = np.clip((buv[back_used, 0] * MESHY_TEX).astype(int), 0, MESHY_TEX - 1)
            sv = np.clip(((1 - buv[back_used, 1]) * MESHY_TEX).astype(int), 0, MESHY_TEX - 1)
            src = mt[sv, su]
        else:
            src = mt.reshape(-1, 3)
        ref = alb[mine_front]
        mu_s, sd_s = src.mean(0), src.std(0) + 1e-4
        mu_r, sd_r = ref.mean(0), ref.std(0)
        gain = np.clip(sd_r / sd_s, 0.3, 2.0)
        btile = np.clip((mt - mu_s) * gain + mu_r, 0, 1).astype(np.float32)
        # atlas: [front tile | Meshy tile], 2 px edge padding each
        fh, fw = ftile.shape[:2]
        AW = fw + 4 + MESHY_TEX + 4
        AH = max(fh + 4, MESHY_TEX + 4)
        AH = -(-AH // 16) * 16
        AW = -(-AW // 16) * 16
        if AW > 4096 or AH > 4096:
            raise SystemExit(f"{lid}: atlas {AW}x{AH} exceeds 4096")
        atlas = np.zeros((AH, AW, 3), np.float32)
        atlas[0:fh + 4, 0:fw + 4] = np.pad(ftile, ((2, 2), (2, 2), (0, 0)), mode="edge")
        bxo = fw + 4
        atlas[0:MESHY_TEX + 4, bxo:bxo + MESHY_TEX + 4] = np.pad(btile, ((2, 2), (2, 2), (0, 0)), mode="edge")
        # unweld: front triangles use projected uv, back ones Meshy's
        P_all, N_all, UV_all, T_all = [], [], [], []
        off = 0
        for sel, kind in ((front, "f"), (~front, "b")):
            if not sel.any():
                continue
            used = np.unique(F[sel])
            remap = np.full(len(V), -1)
            remap[used] = np.arange(len(used))
            if kind == "f":
                u = (2 + (px[used] - bx0) * k) / AW
                v = 1 - (2 + (py[used] - by0) * k) / AH
            else:
                u = (bxo + 2 + buv[used, 0] * MESHY_TEX) / AW
                v = 1 - (2 + (1 - buv[used, 1]) * MESHY_TEX) / AH
            P_all.append(V[used])
            N_all.append(Nv[used])
            UV_all.append(np.stack([u, v], 1))
            T_all.append(remap[F[sel]] + off)
            off += len(used)
        Pm, Nm, UVm, Tm = (np.concatenate(x) for x in (P_all, N_all, UV_all, T_all))
        S_px = silhouette(sc, V, F)
        sc.add_bin(prefab, body, Pm, Nm, UVm, Tm, atlas, extra={"mipBias": S.TERRAIN_MIP_BIAS, "aniso": S.TERRAIN_ANISO})
        # skirt: seed relief triangles on building-mask px the model does not cover
        v0, n0, uv0, subs0 = S.read_bin(ob)
        P0 = sc.cpos + (v0.astype(np.float64) / sc.scale) @ sc.C.T
        N0 = n0.astype(np.float64) @ sc.C.T
        T0 = np.concatenate(subs0)
        M, D = frame_mask(lid, trim)
        cover = cv2.dilate(S_px.astype(np.uint8), np.ones((2 * SKIRT_DILATE + 1,) * 2, np.uint8)) > 0
        c0 = P0[T0].mean(1)
        cx, cy, cz = T.project(sc.cam, c0)
        ix, iy = np.clip(np.round(cx).astype(int), 0, W - 1), np.clip(np.round(cy).astype(int), 0, H - 1)
        t0n = np.cross(P0[T0[:, 1]] - P0[T0[:, 0]], P0[T0[:, 2]] - P0[T0[:, 0]])
        fac = (t0n * (sc.cam["pos"] - c0)).sum(-1)
        want = (M | D)[iy, ix] & ~cover[iy, ix] & (cz > 0)
        sgn = 1.0 if (fac[want] > 0).mean() >= 0.5 else -1.0 if want.any() else 1.0
        keep = want & (fac * sgn > 0)
        skirt_rep = {"tris": int(keep.sum()), "px": int(((M | D) & ~cover).sum())}
        name_sk = f"Mesh_Skirt_{lid}"
        cur = rows.get(prefab, {"bins": []})["bins"]
        if keep.sum() >= 4:
            used = np.unique(T0[keep])
            remap = np.full(len(P0), -1)
            remap[used] = np.arange(len(used))
            img0 = np.asarray(Image.open(orig / f"{body}_albedo.png").convert("RGB"))
            sc.add_bin(prefab, name_sk, P0[used], N0[used], uv0[used], remap[T0[keep]], img0, srgb=True,
                       extra={k_: v_ for k_, v_ in next(b for b in cur if b["name"] == body).items()
                              if k_ not in ("name", "mesh", "texture", "kind")})
        # rest-pose check: share of the building mask the new pieces reproduce
        report[lid] = {"placement": {a: ins[a] for a in ("yaw", "scale", "stretch", "iou", "coverOfMask")},
                       "plate": model["plate"], "tris": int(len(F)), "frontTris": int(front.sum()),
                       "backTris": int((~front).sum()), "atlas": [AW, AH], "frontTilePx": [fw, fh],
                       "irradianceP10P50": [round(float(x), 3) for x in np.quantile(lm[mine_front], [.1, .5])],
                       "clippedShare": round(float((alb[mine_front] >= 0.999).any(-1).mean()), 4),
                       "meshyMatch": {"gain": gain.round(3).tolist(), "srcMean": mu_s.round(4).tolist(),
                                      "refMean": mu_r.round(4).tolist()},
                       "maskPx": int(M.sum()), "modelPxOnMask": int((S_px & M).sum()),
                       "modelPxOffMask": int((S_px & ~M & ~D).sum()), "skirt": skirt_rep,
                       "seconds": round(time.time() - t0, 1)}
        print(lid, json.dumps(report[lid]["placement"]), "front", report[lid]["frontTris"], "skirt", skirt_rep,
              flush=True)
    rows_after = S.save_rows(sc)
    # a skirt row this run did not emit (the model now covers it) is dropped
    for lid in ids:
        pf = S.PREFIX + lid
        emitted = {b["name"] for b in sc.pieces.get(pf, [])}
        rows_after[pf]["bins"] = [b for b in rows_after[pf]["bins"]
                                  if not b["name"].startswith("Mesh_Skirt_") or b["name"] in emitted]
    S.ROWS.write_text(json.dumps(rows_after, indent=1), encoding="utf-8")
    rp = S.WORK / "t2_stage_report.json"
    old = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
    old.update(report)
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    catalog(sc)
    return report


def catalog(sc) -> None:
    """The lane's catalog from the staged rows, plus the T2 provenance block."""
    import stronghold_full3d_scene as S
    S.write_catalog(sc, carry="fresh")
    cat_p = S.OUT / "catalog.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    rep = json.loads((S.WORK / "t2_stage_report.json").read_text(encoding="utf-8"))
    rows = []
    for lid in sorted(rep):
        plc = json.loads((MESHY / lid / "placement.json").read_text(encoding="utf-8"))
        src_id = Path(plc["model"]).parent.name
        meta = json.loads((MESHY / src_id / "meshy.json").read_text(encoding="utf-8"))
        rows.append({"layer": lid, "model": plc["model"], "modelSha256": plc["modelSha256"], "meshyTask": meta["taskId"],
                     "credits": meta["credits"] if src_id == lid else 0, "reusedFrom": src_id if src_id != lid else None,
                     "iou": plc["instance"]["iou"]})
    cat["t2Buildings"] = {"schema": "bulwark_t2_buildings.v1", "layers": rows,
                          "texture": "rest-camera projection of the painting (de-lit) on the triangles the rest pose "
                                     "sees; Meshy texture (per-channel mean/std matched) elsewhere",
                          "proofTier": "generated artifact"}
    cat_p.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ review sheet
def sheet(before: str, after: str, out: Path) -> None:
    from PIL import ImageDraw
    import stronghold_full3d_scene as S
    B = SC.DATA / "candidates" / before / "renders"
    A = SC.DATA / "candidates" / after / "renders"
    ref = S.homm3_reference(S.STATES["full"])

    def lab(img, text):
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 12 + 7 * len(text), 16), fill=(0, 0, 0))
        d.text((4, 3), text, fill=(255, 255, 255))
        return img

    wcell, hcell = 960, 540
    rowsimg = []
    poses = [("full3d_full.png", "rest"), ("pan_sweep_left.png", "sweep_left"), ("pan_sweep_right.png", "sweep_right"),
             ("pan_sweep_high.png", "sweep_high")]
    for fn, name in poses:
        cells = [lab(ref.resize((wcell, hcell)), "HoMM3 painting (x1.8 top-left)") if name == "rest"
                 else Image.new("RGB", (wcell, hcell), (30, 30, 30)),
                 lab(Image.open(B / fn).resize((wcell, hcell), Image.LANCZOS), f"before ({before}) {name}"),
                 lab(Image.open(A / fn).resize((wcell, hcell), Image.LANCZOS), f"after ({after}) {name}")]
        rowsimg.append(cells)
    # zooms: three building boxes (frame px) at rest and sweep_left
    zooms = [((1150, 180, 1480, 680), "town hall + Tier 3"), ((130, 0, 480, 340), "castle"),
             ((520, 380, 1130, 620), "tavern / market / forge")]
    zrows = []
    for fn, name in (poses[0], poses[1], poses[2]):
        for box, zl in zooms:
            zrows.append([lab(Image.open(B / fn).crop(box).resize((640, round(640 * (box[3] - box[1]) / (box[2] - box[0])))),
                              f"before {name}: {zl}"),
                          lab(Image.open(A / fn).crop(box).resize((640, round(640 * (box[3] - box[1]) / (box[2] - box[0])))),
                              f"after {name}: {zl}")])
    Wd = 3 * wcell + 16
    top_h = 4 * hcell + 24
    zh = sum(max(c.height for c in r) + 8 for r in zrows[0::1])
    # zooms laid out 2 pairs per row
    pairs = [zrows[i] + (zrows[i + 1] if i + 1 < len(zrows) else []) for i in range(0, len(zrows), 2)]
    zh = sum(max(c.height for c in p) + 8 for p in pairs)
    sheet_img = Image.new("RGB", (max(Wd, 4 * 648), top_h + zh), (40, 40, 40))
    y = 0
    for cells in rowsimg:
        x = 0
        for c in cells:
            sheet_img.paste(c, (x, y))
            x += wcell + 8
        y += hcell + 8
    for p in pairs:
        x = 0
        for c in p:
            sheet_img.paste(c, (x, y))
            x += 648
        y += max(c.height for c in p) + 8
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet_img.save(out)
    print("sheet", out, sheet_img.size)


def run(cmd: str, ids: list[str], candidate: str) -> int:
    import bulwark_t2_buildings as B
    REUSE_SRC.update(B.REUSE)
    if cmd == "fit":
        print(json.dumps(fit(ids, B.TRIM), indent=1))
    elif cmd == "stage":
        stage(ids, B.TRIM)
    elif cmd == "sheet":
        sheet(os.environ.get("T2_BEFORE", "wall_v2"), candidate,
              ROOT / "artifacts" / "claude_takeover_20260927" / "review" / "homm3_bulwark_t2_buildings.png")
    return 0
