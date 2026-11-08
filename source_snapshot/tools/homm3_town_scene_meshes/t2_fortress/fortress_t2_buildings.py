#!/usr/bin/env python3
"""Meshy T2 building meshes integrated into the Fortress full-3D town lane (brief: _BRIEF_t2_towns.md).

    set TOWN_FULL3D_CANDIDATE=<cand>
    python fortress_t2_buildings.py fit   --layers a,b     # register each mesh to its sprite (fit_mesh_to_sprite)
    python fortress_t2_buildings.py stage --layers a,b     # bake + replace Mesh_Body_<layer> in the candidate

Per layer (the layer's Meshy model: artifacts/meshy_town_scene_meshes/homm3_fortress/<layer>/<attempt>/model.glb):
  load    the glb as glTFast imports it (x negated: right-handed glTF -> the lane's left-handed Unity world);
          optional mesh surgery CUT[layer]: triangles wholly below a share of the model height are removed (the
          sprite's painted water reflection that Meshy built as a hanging keel).
  fit     fit_mesh_to_sprite.Fitter under the lane's rest camera (the cityHuman2 MainCamera, sprite at x1.8): yaw,
          uniform scale and ground contact pixel maximising F-beta(0.5) of the rest silhouette against the sprite's
          lane mask (stronghold_full3d_buildings.native_mask); the contact depth is the calibrated terrain depth at the
          contact pixel, or for a canopy-hung layer (profile RELIEF_TUNE hung) the ring footing the relief lane uses.
          An optional vertical stretch pass (refine_stretch, bounds STRETCH) is kept only when it raises F-beta.
  bake    the Rampart lane's painted-front bake (ported: rampart_t2_buildings refuses other factions). Rest-drawn
          faces are split in screen space to SUBDIV_PX edges; a face the rest camera sees (>= VISIBLE_MIN of its px,
          or its centroid / any corner at the rest surface) takes the painting by screen position, de-lit by the
          Hex/Lit irradiance of a smooth camera-facing normal (Mesh_Body_<layer>); every other face keeps the Meshy
          texture, median gain-matched to the de-lit painting (Mesh_BodyM_<layer>). Both two-sided. The sprite's
          texels are never recoloured. Sprite px the body leaves uncovered at rest keep the seed's relief triangles
          (Mesh_Body_resid_<layer>).
  stage   the bins above replace Mesh_Body_<layer> in the candidate's staged prefab; Fx_ bins and particles of the layer are kept. The layer's
          closing-wall rest edges (relief lane only) are dropped from work/closing_walls.npz.

Proof tier: generated artifact (offline fit + bake); bundle / editor render / in-game unproven until exercised.
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

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
sys.path.insert(0, str(LANE))
os.environ["TOWN_FULL3D_FACTION"] = "fortress"
if not os.environ.get("TOWN_FULL3D_CANDIDATE", "").strip():
    raise SystemExit("set TOWN_FULL3D_CANDIDATE=<candidate> (the Meshy buildings go into a candidate, never the base)")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_buildings as BL  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import fit_mesh_to_sprite as FM  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
MESHY = SC.ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_fortress"
FITS = MESHY / "_fits"
Z_EPS_REL = 0.006          # a texel is visible when its camera depth is within this share of the z-buffer's
STRETCH = (0.8, 1.25)      # vertical stretch bounds of the optional refine pass
STRETCH_GAIN_MIN = 0.01    # F-beta gain the stretch pass must bring to be kept
SEED = "fr_v4"             # the installed candidate whose relief solids supply the residual pieces
RESID_GROW = 2             # frame px the model's rest silhouette is grown before the residual is taken
RESID_MIN_PX = 30          # residual components smaller than this (frame px) are dropped
NO_RESID: set[str] = set()

# Mesh surgery (hand-set from each model, see the doc): drop triangles wholly below this share of the model height.
# Measured on the castle models (width per 5% height slice): the keel under the wall base is 0.09-0.24 of the model width,
# the base 0.59-1.0 (fortress_t2 doc).
CUT: dict[str, float] = {"tbfrcstl": 0.39, "tbfrcstl_2": 0.29, "tbfrcstl_3": 0.20}
# Sprite rows (native px) below the painted waterline: the castle's water reflection is painted into its sprite; the
# fit target ends at the waterline (read off the sprite: the landing stones end at row 111 of tbfrcstl; the upgrades
# share the bottom rows, +20 / +63). The reflection pixels stay painted (residual piece).
FIT_ROW_MAX: dict[str, int] = {"tbfrcstl": 111, "tbfrcstl_2": 131, "tbfrcstl_3": 174}
# Attempt folder per layer (default t2).
ATTEMPT: dict[str, str] = {}


# ------------------------------------------------------------------------------------------------ model
def glb_path(lid: str) -> Path:
    return MESHY / lid / ATTEMPT.get(lid, "t2") / "model.glb"


def load_model(lid: str) -> dict:
    import trimesh
    p = glb_path(lid)
    sc = trimesh.load(str(p), force="scene")
    if len(sc.geometry) != 1:
        raise SystemExit(f"{lid}: {p} has {len(sc.geometry)} geometries (expected one textured mesh)")
    node = sc.graph.nodes_geometry[0]
    Tm, gname = sc.graph[node]
    g = sc.geometry[gname]
    V = np.asarray(g.vertices, np.float64) @ Tm[:3, :3].T + Tm[:3, 3]
    VN = np.asarray(g.vertex_normals, np.float64) @ Tm[:3, :3].T
    VN /= np.linalg.norm(VN, axis=1, keepdims=True) + 1e-12
    F = np.asarray(g.faces, np.int64)
    UV = np.asarray(g.visual.uv, np.float64)
    tex = np.asarray(g.visual.material.baseColorTexture.convert("RGB"))
    V[:, 0] *= -1.0          # glTFast: right-handed glTF -> left-handed Unity
    VN[:, 0] *= -1.0
    cut = CUT.get(lid)
    rep = {"glb": str(p.relative_to(SC.ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
           "verts": int(len(V)), "tris": int(len(F)), "tex": list(tex.shape[:2])}
    if cut is not None:
        lo, hi = V[:, 1].min(), V[:, 1].max()
        yc = lo + cut * (hi - lo)
        keep = (V[F][:, :, 1] >= yc).any(1)
        rep["cut"] = {"belowShare": cut, "droppedTris": int((~keep).sum())}
        F = F[keep]
    # wind every triangle so its geometric normal agrees with its vertex normals (the lane's orient(): Unity's front)
    F = BL.orient(V, F, VN[F].mean(1), 1.0)
    used = np.unique(F)
    remap = np.full(len(V), -1)
    remap[used] = np.arange(len(used))
    return {"V": V[used], "VN": VN[used], "UV": UV[used], "F": remap[F], "tex": tex, "rep": rep}


# ------------------------------------------------------------------------------------------------ rest-frame inputs
_RD = None


def rect_depth(sc) -> dict:
    global _RD
    if _RD is None:
        _RD = T.rect_depth(sc.cam)
    return _RD


def z_field(sc, lid: str) -> tuple[np.ndarray, dict]:
    """Frame-size camera depth the Fitter seats the model's base on (painting m)."""
    from scipy.ndimage import distance_transform_edt
    rd = rect_depth(sc)
    tune = BL.TUNE.get(lid, {})
    if tune.get("hung"):
        ld = BL.layer_depth(lid, SC.layers()[lid], rd)
        zf = float(np.median(ld["foot_z"]))
        return np.full((H, W), zf), {"contact": "hung ring footing (RELIEF_TUNE hung)", "zM": round(zf, 2)}
    zc = rd["zc"].copy()
    ok = np.isfinite(zc)
    _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
    zc = zc[iy, ix]
    z = np.pad(zc, ((0, H - TH), (0, W - TW)), mode="edge")
    return z, {"contact": "calibrated terrain depth at the contact pixel"}


def sprite_mask_frame(lid: str) -> np.ndarray:
    L = SC.layers()[lid]
    m = BL.native_mask(L).astype(np.uint8) * 255
    mh, mw = m.shape
    big = cv2.resize(m, (round(mw * SC.SCALE), round(mh * SC.SCALE)), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((H, W), np.uint8)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    xs, ys = max(0, -x0), max(0, -y0)
    x1, y1 = min(W, x0 + big.shape[1]), min(H, y0 + big.shape[0])
    out[max(0, y0):y1, max(0, x0):x1] = big[ys:ys + y1 - max(0, y0), xs:xs + x1 - max(0, x0)]
    return out


# ------------------------------------------------------------------------------------------------ fit
def fit_layer(sc, lid: str) -> dict:
    t0 = time.time()
    M = load_model(lid)
    z, zrep = z_field(sc, lid)
    tgt = sprite_mask_frame(lid) >= 128
    if lid in FIT_ROW_MAX:
        L = SC.layers()[lid]
        tgt[round((L["y"] + FIT_ROW_MAX[lid] + 1) * SC.SCALE):] = False
    cam = {k: np.asarray(sc.cam[k], np.float64) if k != "fov" else float(sc.cam[k])
           for k in ("pos", "fwd", "right", "up", "fov")}
    fitter = FM.Fitter(cam, z, (W, H), tgt.astype(np.uint8), M["V"], M["F"], down=2)
    ys, xs = np.nonzero(tgt)
    concept = (SC.ROOT / M["rep"]["glb"]).parent.joinpath("concept.png").is_file()
    base = fitter.fit((xs.min(), ys.min(), xs.max(), ys.max()), yaws=YAWS_CONCEPT if concept else YAWS_DIRECT)
    best = base
    st = fitter.refine_stretch(base, lo=STRETCH[0], hi=STRETCH[1], top_weight=0.5)
    kept = st["fbeta"] > base["fbeta"] + STRETCH_GAIN_MIN
    if kept:
        best = st
    pos, Pw = fitter.transform(best["yaw"], best["scale"], *best["contactPx"], best["stretchY"])
    sil = best.pop("silhouette")
    for r in (base, st):
        r.pop("silhouette", None)
    rep = {"layer": lid, "model": M["rep"], **zrep, "fit": {k: v for k, v in best.items()},
           "baseFit": {k: base[k] for k in ("yaw", "scale", "fbeta", "iou", "precision", "recall")},
           "stretchPass": {"fbeta": st["fbeta"], "stretchY": st["stretchY"], "kept": bool(kept)},
           "modelNormalisation": {"centre": [float(x) for x in (M["V"].min(0) + M["V"].max(0)) / 2],
                                  "baseY": float(M["V"][:, 1].min())},
           "yawWindow": "concept" if concept else "direct",
           "restAppearance": appearance(sc, lid, M, Pw), "seconds": round(time.time() - t0, 1)}
    FITS.mkdir(parents=True, exist_ok=True)
    (FITS / f"{lid}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    np.save(FITS / f"{lid}_world.npy", Pw.astype(np.float64))
    # viz: sprite mask (green) vs rest silhouette (red), overlap yellow, on the sprite composite
    full = np.zeros((H // 2, W // 2, 3), np.uint8)
    t2 = tgt[::2, ::2]
    full[..., 1] = t2 * 200
    full[..., 2] = sil * 200
    ys2, xs2 = np.nonzero(t2 | sil)
    crop = full[max(0, ys2.min() - 10):ys2.max() + 10, max(0, xs2.min() - 10):xs2.max() + 10]
    Image.fromarray(crop[..., ::-1]).save(FITS / f"{lid}_fit.png")
    print(lid, json.dumps({k: rep["fit"][k] for k in ("yaw", "scale", "stretchY", "fbeta", "iou", "precision",
                                                      "recall", "worldHeight")}), flush=True)
    return rep


# ------------------------------------------------------------------------------------------------ rest appearance
APP_S = 512                # UV raster size of the appearance check
# Meshy T2 puts its input view's front at yaw 180 under the rest camera (x-negated glTF; the Factory lane measured the
# same). A free 0-360 search lands on the back or a side of near-symmetric silhouettes (tbfrcstl 12 / 180, tbfrspec 0 /
# 180 within 0.002 F-beta; tbfrhall_2 45), and the rest-view colour correlation cannot break those ties (|r| < 0.05 on
# most layers, see appearance()), so the search is kept to the input's own hemisphere. A concept layer's input is a
# re-drawn three-quarter view, so its window is wider.
YAWS_DIRECT = range(140, 221, 10)
YAWS_CONCEPT = range(120, 241, 10)


def appearance(sc, lid: str, M: dict, P: np.ndarray) -> dict:
    """Mean Pearson correlation (CIELAB L, a, b) between the Meshy texture the rest camera sees on the model's
    front-facing, visible texels inside the sprite mask and the sprite's own pixels there: a silhouette is often
    symmetric under a half turn, the painted door / windows / emblems are not."""
    F, UV = M["F"], M["UV"]
    tex = cv2.resize(M["tex"], (APP_S, APP_S), interpolation=cv2.INTER_AREA)
    ids = uv_raster(UV, F, APP_S)
    rows, cols = np.nonzero(ids >= 0)
    tid = ids[rows, cols]
    uvp = np.stack([(cols + 0.5) / APP_S, 1 - (rows + 0.5) / APP_S], 1)
    bc = np.clip(barycentric(uvp, UV[F[tid, 0]], UV[F[tid, 1]], UV[F[tid, 2]]), 0, None)
    bc /= bc.sum(1, keepdims=True)
    Pt = np.einsum("ij,ijk->ik", bc, P[F[tid]])
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
    view = sc.cam["pos"] - Pt
    view /= np.linalg.norm(view, axis=1, keepdims=True)
    zmin = zbuffer(sc, P, F, 1)
    px, py, zc = T.project(sc.cam, Pt)
    xi, yi = np.clip(px.astype(int), 0, W - 1), np.clip(py.astype(int), 0, H - 1)
    msk = sprite_mask_frame(lid) >= 200
    ok = ((fn[tid] * view).sum(1) > 0.15) & (zc <= zmin[yi, xi] * (1 + Z_EPS_REL) + 0.05) & msk[yi, xi]
    if ok.sum() < 200:
        return {"corr": -1.0, "texels": int(ok.sum())}
    spr = SC.sprite_frame(SC.layers()[lid])[..., :3].astype(np.float32) / 255
    a = cv2.cvtColor(spr[yi[ok], xi[ok]][None], cv2.COLOR_RGB2LAB)[0]
    b = cv2.cvtColor(tex[rows[ok], cols[ok]].astype(np.float32)[None] / 255, cv2.COLOR_RGB2LAB)[0]
    cs = [float(np.corrcoef(a[:, c], b[:, c])[0, 1]) for c in range(3)]
    return {"corr": float(np.nanmean(cs)), "perChannel": [round(c, 3) for c in cs], "texels": int(ok.sum())}


# ------------------------------------------------------------------------------------------------ bake
def uv_raster(UV: np.ndarray, F: np.ndarray, S_: int) -> np.ndarray:
    """Triangle id per texel of the model's UV layout (-1 none); rows top-down (row = (1 - v) * S)."""
    q = np.stack([UV[:, 0] * S_, (1 - UV[:, 1]) * S_], 1)
    ids = np.full((S_, S_), -1, np.int32)
    tri = np.round(q[F] * 4).astype(np.int32)
    for i, t in enumerate(tri):
        cv2.fillPoly(ids, [t], int(i), lineType=cv2.LINE_8, shift=2)
    # conservative: triangle outlines too (sub-texel slivers fillPoly drops), only into texels no fill owns
    edge = np.full((S_, S_), -1, np.int32)
    for i, t in enumerate(tri):
        cv2.polylines(edge, [t], True, int(i), thickness=1, lineType=cv2.LINE_8, shift=2)
    hole = (ids < 0) & (edge >= 0)
    ids[hole] = edge[hole]
    return ids


def barycentric(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(-1)
    d01 = (v0 * v1).sum(-1)
    d11 = (v1 * v1).sum(-1)
    d20 = (v2 * v0).sum(-1)
    d21 = (v2 * v1).sum(-1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-18, 1e-18, den)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.stack([1 - v - w, v, w], -1)


def zbuffer(sc, P: np.ndarray, F: np.ndarray, k: int) -> np.ndarray:
    """Rest-camera depth buffer (camera z, painting m) of the model alone at k px per frame px (inf = none)."""
    px, py, zc = T.project(sc.cam, P)
    q = np.stack([px * k, py * k], 1)
    zb = np.full((H * k, W * k), np.inf, np.float32)
    iz = 1.0 / np.maximum(zc, 1e-6)
    for t in F:
        a, b, c = q[t]
        x0, x1 = int(max(0, math.floor(min(a[0], b[0], c[0])))), int(min(W * k - 1, math.ceil(max(a[0], b[0], c[0]))))
        y0, y1 = int(max(0, math.floor(min(a[1], b[1], c[1])))), int(min(H * k - 1, math.ceil(max(a[1], b[1], c[1]))))
        if x1 < x0 or y1 < y0:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        pts = np.stack([xx + 0.5, yy + 0.5], -1).astype(np.float64)
        bc = barycentric(pts, a, b, c)
        inside = (bc >= -1e-3).all(-1)
        if not inside.any():
            continue
        zz = 1.0 / (bc @ iz[t])
        cur = zb[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (zz < cur)
        cur[upd] = zz[upd]
    return zb


def bake_layer(sc, lid: str) -> dict:
    """Mesh_Body_<layer>: the faces the rest camera sees (>= VISIBLE_MIN of their projected px, or centroid / any
    corner at the rest surface), textured by the painting in screen space and de-lit per px by the Hex/Lit irradiance
    of a smooth camera-facing normal (the painting already carries its shading). Mesh_BodyM_<layer>: every other face
    with the Meshy texture, per-channel median gain-matched (linear) to the de-lit painting. Both two-sided."""
    t0 = time.time()
    fit = json.loads((FITS / f"{lid}.json").read_text(encoding="utf-8"))
    M = load_model(lid)
    if M["rep"]["sha256"] != fit["model"]["sha256"]:
        raise SystemExit(f"{lid}: fit was made for another model; run fit again")
    P = np.load(FITS / f"{lid}_world.npy")
    F, UV, tex = M["F"], M["UV"], M["tex"]
    # geometry past the painted rect at rest is beyond the HoMM3 world (a frame-cut sprite Meshy completed); its extent
    # re-aims the profile framing (aim 'buildings'). Left / top: any vertex past the edge drops the triangle; right /
    # bottom: only triangles wholly past the rect (the Factory lane's rule).
    ox, oy, _ = T.project(sc.cam, P)
    tx, ty = ox[F], oy[F]
    out = (tx.min(1) < 0) | (ty.min(1) < 0) | (tx.min(1) > TW) | (ty.min(1) > TH)
    trim = {"droppedTris": int(out.sum()), "tris": int(len(F))}
    F = F[~out]
    R = FM.yaw_matrix(fit["fit"]["yaw"])
    N = (M["VN"] * np.array([1.0, 1.0 / fit["fit"]["stretchY"], 1.0])) @ R.T
    N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    P, N, UV, F = P[used], N[used], UV[used], remap[F]
    P, N, UV, F, srep = TP.subdivide_screen(sc.cam, P, N, UV, F)
    L = SC.layers()[lid]
    res = TP.painted_front(sc, lid, L, BL.native_mask(L), P, N, F, UV, TP.tex_to_lin(tex))
    res["rep"].update({"layer": lid, "subdivide": srep})
    res["rep"]["framingTrim"] = trim
    res["rep"]["seconds"] = round(time.time() - t0, 1)
    return res


def residual(sc, lid: str, sil: np.ndarray) -> dict | None:
    """The seed candidate's relief-solid triangles over the sprite pixels the Meshy model does not cover at rest
    (sprite mask minus the model's rest silhouette grown RESID_GROW px, components >= RESID_MIN_PX): the painting
    stays whole at rest; these pieces keep the old method's look under the sweeps (reported per layer)."""
    d = SC.DATA / "candidates" / SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v, n, uv, subs = S.read_bin(d / f"Mesh_Body_{lid}.bytes")
    tex = np.asarray(Image.open(d / f"Mesh_Body_{lid}_albedo.png").convert("RGB"))
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    N = n.astype(np.float64) @ sc.C.T
    tris = np.concatenate(subs).astype(np.int64)
    tgt = sprite_mask_frame(lid) >= 128
    grow = cv2.dilate(sil.astype(np.uint8), np.ones((2 * RESID_GROW + 1,) * 2, np.uint8)).astype(bool)
    res = (tgt & ~grow).astype(np.uint8)
    k, labl, st, _ = cv2.connectedComponentsWithStats(res, connectivity=8)
    keep_c = np.zeros(k, bool)
    keep_c[1:] = st[1:, cv2.CC_STAT_AREA] >= RESID_MIN_PX
    res = keep_c[labl]
    if res.sum() == 0:
        return None
    px, py, _ = T.project(sc.cam, P[tris].mean(1))
    xi, yi = np.clip(px.astype(int), 0, W - 1), np.clip(py.astype(int), 0, H - 1)
    keep = res[yi, xi]
    if not keep.any():
        return None
    t = tris[keep]
    used = np.unique(t)
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    # double-sided like the Meshy body: the relief fragment has lost its closing walls, and Cull Back dropped its
    # back side at the sweeps and orbits (see-through 25015 -> 68621 px, all of it resid_* pieces)
    Pu, Nu, Uu, Fu = P[used], N[used], uv[used], remap[t]
    nv = len(Pu)
    return {"P": np.concatenate([Pu, Pu]), "N": np.concatenate([Nu, -Nu]), "UV": np.concatenate([Uu, Uu]),
            "F": np.concatenate([Fu, Fu[:, ::-1] + nv]), "tex": tex,
            "rep": {"doubleSided": True, "residualPx": int(res.sum()), "spritePx": int(tgt.sum()),
                    "residualShare": round(float(res.sum() / max(1, tgt.sum())), 4), "tris": int(keep.sum()),
                    "source": f"{SEED} Mesh_Body_{lid}"}}


# ------------------------------------------------------------------------------------------------ stage
def _drop_bin(prefab: str, name: str) -> None:
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if prefab in rows:
        rows[prefab]["bins"] = [b for b in rows[prefab]["bins"] if b["name"] != name]
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def stage(lids: list[str]) -> dict:
    sc = S.Scene()
    rp = S.WORK / "stage_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    reps = {}
    for lid in lids:
        b = bake_layer(sc, lid)
        prefab = S.PREFIX + lid
        for name, piece, extra in ((f"Mesh_Body_{lid}", b["front"], {}),
                                   (f"Mesh_BodyM_{lid}", b["meshy"], {"max_size": 2048})):
            if piece is None:
                _drop_bin(prefab, name)
            else:
                sc.add_bin(prefab, name, *piece, preview=False, **extra)
        r = residual(sc, lid, b["sil"]) if lid not in NO_RESID else None
        if r is not None:
            sc.add_bin(prefab, f"Mesh_Body_resid_{lid}", r["P"], r["N"], r["UV"], r["F"], r["tex"], srgb=True,
                       preview=False)
            b["rep"]["residual"] = r["rep"]
        else:
            b["rep"]["residual"] = None
            _drop_bin(prefab, f"Mesh_Body_resid_{lid}")
        fit = json.loads((FITS / f"{lid}.json").read_text(encoding="utf-8"))
        old = report["buildings"].get(lid, {})
        report["buildings"][lid] = {
            "kind": old.get("kind", "building"), "method": "meshy_t2",
            "texelsPerPx": b["rep"]["texelsPerPx"], "tris": b["rep"]["frontTris"] + b["rep"]["meshyTris"],
            "frontTris": b["rep"]["frontTris"],
            "meshy": {"model": fit["model"], "fit": {k: fit["fit"][k] for k in ("yaw", "scale", "stretchY", "fbeta",
                                                                               "iou", "precision", "recall",
                                                                               "worldHeight", "contactPx")},
                      "contact": fit["contact"], "bake": b["rep"]},
            "replaced": {k: old.get(k) for k in ("method", "tris", "texelsPerPx")}}
        reps[lid] = b["rep"]
        print(lid, json.dumps(b["rep"]), flush=True)
    S.save_rows(sc)
    rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    wf = S.WORK / "closing_walls.npz"
    if wf.is_file():
        edges = {k: v for k, v in dict(np.load(wf)).items() if k not in lids}
        np.savez(wf, **edges)
    S.write_catalog(sc)   # v2 catalog + the profile framing gate over every staged prefab
    return reps


def restore(lids: list[str]) -> None:
    """Put the seed candidate's relief back for layers whose Meshy body loses at rest (per-layer mix): the prefab's
    staged files and rows, its stage_report entry and its closing-wall edges, verbatim from SEED."""
    import shutil
    seed = SC.DATA / "candidates" / SEED
    sstage = seed / S.STAGE.relative_to(S.CAND)
    srows = json.loads((sstage / "rows.json").read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    sreport = json.loads((seed / "work" / "stage_report.json").read_text(encoding="utf-8"))
    wf, swf = S.WORK / "closing_walls.npz", seed / "work" / "closing_walls.npz"
    edges = dict(np.load(wf)) if wf.is_file() else {}
    sedges = dict(np.load(swf)) if swf.is_file() else {}
    for lid in lids:
        prefab = S.PREFIX + lid
        shutil.rmtree(S.STAGE / prefab)
        shutil.copytree(sstage / prefab, S.STAGE / prefab)
        rows[prefab] = srows[prefab]
        report["buildings"][lid] = sreport["buildings"][lid]
        if lid in sedges:
            edges[lid] = sedges[lid]
        print("restored", lid, flush=True)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    if edges:
        np.savez(wf, **edges)
    S.write_catalog(S.Scene())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "restore"])
    ap.add_argument("--layers", required=True)
    ap.add_argument("--faction", default="fortress")
    a = ap.parse_args()
    lids = [x for x in a.layers.split(",") if x]
    reach = set(SC.reachable_layers())
    bad = [l for l in lids if l not in reach]
    if bad:
        raise SystemExit(f"not reachable layers: {bad}")
    if a.cmd == "fit":
        sc = S.Scene()
        for lid in lids:
            fit_layer(sc, lid)
        return 0
    if a.cmd == "restore":
        restore(lids)
        return 0
    stage(lids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
