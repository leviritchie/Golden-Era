#!/usr/bin/env python3
"""Factory: stage the Meshy T2 building meshes (factory_t2_meshy.py) into a full-3D candidate.

    TOWN_FULL3D_CANDIDATE=fa_v9_t2 python tools/homm3_town_scene_meshes/factory_t2_stage.py fit   [--layer L ...]
    TOWN_FULL3D_CANDIDATE=fa_v9_t2 python tools/homm3_town_scene_meshes/factory_t2_stage.py stage [--layer L ...]

fit    register each mesh to its HoMM3 sprite under the rest camera (fit_mesh_to_sprite.Fitter: yaw, uniform scale and
       ground-contact pixel on the calibrated terrain depth, F0.5 of silhouette vs the sprite's building mask), then an
       optional vertical-stretch pass (kept only when its F0.5 is higher). Writes <meshy dir>/<layer>/fit.json.
stage  per meshed layer the seed's Mesh_Body_<layer> is replaced by the painted-front bake
       (town_full3d_t2_paint.painted_front, the Rampart / Fortress rule; Fx_ pieces are kept as they are):
       Mesh_Body_<layer>     faces the rest camera sees, textured by the painting in screen space, de-lit.
       Mesh_BodyM_<layer>    every other face: the Meshy texture, median gain-matched to the de-lit painting.
       Mesh_BodyRest_<layer> the seed's relief FRONT triangles over sprite px the body leaves uncovered at rest.
       All three are two-sided (open Meshy shells, Cull Back in game).
Seed = the installed fa_v4 (its Mesh_Body_<layer> bins are read from candidates/fa_v4, never modified).
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "factory")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import factory_t2_meshy as FM  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SEED = SC.DATA / "candidates" / "fa_v4"
# Shading normals of the Meshy-textured remainder lean toward the key light: n' = normalize(n + NORMAL_WRAP * to_sun).
# The Factory rig is a hard key with near-zero equatorial ambient (ambEq 0.012), so the walls hidden at rest that face
# away from the key would render near-black at the sweeps with their true normals. (The painted front uses
# painted_front's own camera-facing de-light normal.)
NORMAL_WRAP = 0.5
RESID_GROW = 2         # frame px the body's rest silhouette is grown before the residual is taken
RESID_MIN_PX = 20      # frame px: residual sprite components smaller than this are not re-covered by the seed relief
MESHY_TEX_MAX = 2048
# Meshy T2 puts the input view's front at yaw 180 under the rest camera (x-negated glTF). A free 0-360 search lands on
# the back or a side for near-symmetric silhouettes (tbfahal2 24, tbfahall 27, tbfacstl 342: the blank back wall at
# rest and the gate behind), so the search is kept to the input's own hemisphere; the fine pass adds +-12.
YAWS = range(140, 221, 10)
# Layers judged broken by eye at the sweeps (the 2026-09-29 rule: revert only a broken mesh) keep the fa_v4 relief
# (`restore`); the default stage list skips them.
REVERTED = {"tbfadw_4": "the dark mine doorway reads at rest as faceted Meshy-textured wood (the painted front "
                        "misses the opening's interior; weakest fit, F0.5 0.787 at the yaw window's edge)"}


def mesh_dir(lid: str) -> Path:
    return FM.OUT / FM.REUSE.get(lid, lid)


def load_glb(path: Path) -> dict:
    """GLB -> left-handed painting-world convention (x negated, as glTFast imports), faces rewound outward."""
    import trimesh
    m = trimesh.load(str(path), force="mesh", process=False)
    V = np.asarray(m.vertices, np.float64).copy()
    V[:, 0] *= -1.0
    F = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]   # x negation mirrors; restore outward winding
    uv = np.asarray(m.visual.uv, np.float64)
    tex = m.visual.material.baseColorTexture
    return {"V": V, "F": F, "uv": uv, "tex": np.asarray(tex.convert("RGB"))}


def outward_sign(V: np.ndarray, F: np.ndarray) -> float:
    """Signed volume of the mesh (>0: cross(b-a, c-a) points outward)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def frame_mask(lid: str) -> np.ndarray:
    L = SC.layers()[lid]
    m = FM.building_mask(lid)
    s = cv2.resize(m.astype(np.float32), (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)),
                   interpolation=cv2.INTER_LINEAR) > 0.5
    out = np.zeros((H, W), bool)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    hh, ww = min(s.shape[0], H - y0), min(s.shape[1], W - x0)
    out[y0:y0 + hh, x0:x0 + ww] = s[:hh, :ww]
    return out


_ZS = None


def terrain_z(sc) -> np.ndarray:
    """Frame forward depth of the terrain (sky filled by the nearest ground), cached in the candidate's work dir."""
    global _ZS
    import stronghold_full3d_scene as S
    if _ZS is not None:
        return _ZS
    p = S.WORK / "t2_terrain_z.npy"
    if p.is_file():
        _ZS = np.load(p)
        return _ZS
    st = S.terrain_state(sc)
    zs = st["fd"]["zs"].astype(np.float64)
    ok = np.isfinite(zs)
    from scipy.ndimage import distance_transform_edt
    _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
    zs = zs[iy, ix]
    np.save(p, zs)
    _ZS = zs
    return zs


def fit(lid: str) -> dict:
    import stronghold_full3d_scene as S
    from fit_mesh_to_sprite import Fitter
    sc = S.Scene()
    zs = terrain_z(sc)
    g = load_glb(mesh_dir(lid) / "mesh_a1" / "model.glb")
    tgt = frame_mask(lid)
    cam = {k: (np.asarray(v, np.float64) if k in ("pos", "fwd", "right", "up") else v) for k, v in sc.cam.items()}
    fz = Fitter(cam, zs, (W, H), tgt.astype(np.uint8), g["V"], g["F"], down=2)
    ys, xs = np.nonzero(tgt)
    t0 = time.time()
    base = fz.fit((xs.min(), ys.min(), xs.max(), ys.max()), yaws=YAWS)
    best = base
    try:
        st = fz.refine_stretch(base, lo=0.8, hi=1.25, top_weight=0.5)
        if st["fbeta"] > base["fbeta"] + 0.005:
            best = st
    except Exception as e:  # noqa: BLE001 - recorded, base fit kept
        print(lid, "stretch pass failed:", e)
    out = {k: v for k, v in best.items() if k != "silhouette"}
    out["base"] = {k: base[k] for k in ("fbeta", "iou", "precision", "recall")}
    out["meshFrom"] = FM.REUSE.get(lid, lid)
    out["seconds"] = round(time.time() - t0, 1)
    d = FM.OUT / lid
    d.mkdir(parents=True, exist_ok=True)
    (d / "fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # overlay: sprite mask (green) vs fitted silhouette (red)
    sil = best["silhouette"]
    sil = cv2.resize(sil.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:TH, :TW] = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS)) // 2
    frame[tgt] = (frame[tgt] * 0.5 + np.array([0, 160, 0])).astype(np.uint8)
    frame[sil] = (frame[sil] * 0.6 + np.array([140, 0, 0])).astype(np.uint8)
    y0, y1 = max(0, ys.min() - 40), min(H, ys.max() + 40)
    x0, x1 = max(0, xs.min() - 40), min(W, xs.max() + 40)
    Image.fromarray(frame[y0:y1, x0:x1]).save(d / "fit_overlay.png")
    print(lid, {k: round(out[k], 3) for k in ("iou", "precision", "recall", "fbeta", "stretchY", "yaw")}, flush=True)
    return out


def placed(lid: str) -> tuple[dict, dict]:
    from fit_mesh_to_sprite import yaw_matrix
    g = load_glb(mesh_dir(lid) / "mesh_a1" / "model.glb")
    f = json.loads((FM.OUT / lid / "fit.json").read_text(encoding="utf-8"))
    V = g["V"]
    lo, hi = V.min(0), V.max(0)
    v0 = V - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    Vw = ((v0 * np.array([1.0, f["stretchY"], 1.0])) @ yaw_matrix(f["yaw"]).T) * f["scale"] + np.asarray(f["position"])
    F = g["F"]
    if outward_sign(Vw, F) < 0:
        F = F[:, [0, 2, 1]]
    g["V"], g["F"] = Vw, F
    return g, f


def vertex_normals(V, F):
    """Area-weighted vertex normals, accumulated by position so UV-seam duplicates share one normal."""
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    _, pid = np.unique(np.round(V, 6), axis=0, return_inverse=True)
    pid = pid.ravel()
    acc = np.zeros((pid.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, pid[F[:, k]], fn)
    vn = acc[pid]
    fl = np.linalg.norm(fn, axis=1, keepdims=True)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    return vn, fn / (fl + 1e-12)


def seed_relief(lid: str, sc) -> tuple:
    """The seed's (fa_v4) Mesh_Body_<layer>: painting-world P, n, uv, tris and its albedo png path."""
    import stronghold_full3d_scene as S
    d = SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v, n, uv, subs = S.read_bin(d / f"Mesh_Body_{lid}.bytes")
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    nw = n.astype(np.float64) @ sc.C.T
    return P, nw, uv, np.concatenate(subs), d / f"Mesh_Body_{lid}_albedo.png"


def stage_layer(sc, lid: str) -> dict:
    """The painted-front bake (town_full3d_t2_paint.painted_front, the Rampart lane's rule): rest-seen faces take the
    painting in screen space (Mesh_Body_), the rest keep the gain-matched Meshy texture (Mesh_BodyM_), both two-sided;
    sprite px the body leaves uncovered keep the seed relief (Mesh_BodyRest_, two-sided)."""
    import stronghold_full3d_scene as S
    import town_full3d_t2_paint as TP
    t0 = time.time()
    g, f = placed(lid)
    V, F, uvm = g["V"], g["F"], g["uv"]
    nT0 = len(F)
    # geometry wholly outside the painted rect at rest is beyond the HoMM3 world (a sprite cut by the screen edge
    # that Meshy completed): the relief ended at the edge too, and the extra extent re-aims the framing
    # (tbfahal3's completed left half moved the building union 0.022 left and pushed tbfatvrn / tbfaup_5 out of view).
    # Left / top / bottom: any vertex past the edge drops the triangle; right: only triangles wholly past the rect.
    # The bottom joined the strict rule on fa_v9_t2: tbfatvrn's Meshy base reached 10 px below the painted rect
    # (union bottom 0.6236 -> 0.6323 of the frame), which re-aimed the 'buildings' framing and put tbfatvrn and
    # tbfaup_5 out of the visible region at rest (framing gate). Sprite px the trim uncovers go to the residual.
    ox, oy, _oz = T.project(sc.cam, V)
    tx, ty = ox[F], oy[F]
    outside = (tx.min(1) < 0) | (ty.min(1) < 0) | (tx.min(1) > TW) | (ty.max(1) > TH)
    F = F[~outside]
    used = np.unique(F)
    remap = np.full(len(V), -1, np.int64)
    remap[used] = np.arange(len(used))
    V, uvm, F = V[used], uvm[used], remap[F]
    vn, _fn = vertex_normals(V, F)
    vn = vn + NORMAL_WRAP * (-np.asarray(sc.sun, np.float64))
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    V, vn, uvm, F, srep = TP.subdivide_screen(sc.cam, V, vn, uvm, F)
    res = TP.painted_front(sc, lid, L, BL.native_mask(L), V, vn, F, uvm, TP.tex_to_lin(g["tex"]))
    res["rep"].update({"layer": lid, "subdivide": srep})
    prefab = S.PREFIX + lid
    rep = res["rep"]
    rep.update({"meshFrom": f["meshFrom"],
                "fit": {k_: round(f[k_], 3) for k_ in ("iou", "precision", "recall", "fbeta", "stretchY", "yaw",
                                                       "worldHeight")},
                "meshyTris0": int(nT0), "outsideRectTrisDropped": int(outside.sum()),
                "tris": int(rep["frontTris"] + rep["meshyTris"])})
    if res["front"] is not None:
        sc.add_bin(prefab, f"Mesh_Body_{lid}", *res["front"], preview=False)
    if res["meshy"] is not None:
        sc.add_bin(prefab, f"Mesh_BodyM_{lid}", *res["meshy"], max_size=MESHY_TEX_MAX, preview=False)
    rep["hasFront"] = res["front"] is not None
    # residual: sprite building px the body leaves uncovered at rest -> the seed relief's front triangles there
    tgt = frame_mask(lid)
    grow = cv2.dilate(res["sil"].astype(np.uint8), np.ones((2 * RESID_GROW + 1,) * 2, np.uint8)).astype(bool)
    resid = tgt & ~grow
    resid[TH:] = False
    resid[:, TW:] = False
    n_, lab_, st_, _ = cv2.connectedComponentsWithStats(resid.astype(np.uint8), connectivity=8)
    keep = np.zeros(n_, bool)
    keep[1:] = st_[1:, cv2.CC_STAT_AREA] >= RESID_MIN_PX
    resid = keep[lab_]
    rep["spritePx"] = int(tgt[:TH, :TW].sum())
    rep["residualPx"] = int(resid.sum())
    rep["residualShare"] = round(rep["residualPx"] / max(1, rep["spritePx"]), 4)
    rep["residualTris"] = 0
    if resid.sum():
        P0, n0, uv0, t0_, albp = seed_relief(lid, sc)
        rx, ry, _ = T.project(sc.cam, P0)
        cx, cy = rx[t0_].mean(1), ry[t0_].mean(1)
        fn0 = np.cross(P0[t0_[:, 1]] - P0[t0_[:, 0]], P0[t0_[:, 2]] - P0[t0_[:, 0]])
        vw = sc.cam["pos"] - P0[t0_].mean(1)
        fr = (fn0 * vw).sum(-1) / (np.linalg.norm(fn0, axis=1) * np.linalg.norm(vw, axis=1) + 1e-12) > 0.05
        rd = cv2.dilate(resid.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        ok = (cx >= 0) & (cy >= 0) & (cx < W) & (cy < H)
        inr = np.zeros(len(t0_), bool)
        inr[ok] = rd[cy[ok].astype(int), cx[ok].astype(int)]
        selr = fr & inr
        rep["residualTris"] = int(selr.sum())
        if selr.any():
            u = np.unique(t0_[selr])
            rm = np.full(len(P0), -1)
            rm[u] = np.arange(len(u))
            img = np.asarray(Image.open(albp).convert("RGB"))
            # two-sided: the relief fragment has lost its closing walls and the game culls back faces
            sc.add_bin(prefab, f"Mesh_BodyRest_{lid}", *TP.two_sided(P0[u], n0[u], uv0[u], rm[t0_[selr]]), img,
                       srgb=True, preview=False)
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def stage(layers: list[str]) -> int:
    import stronghold_full3d_scene as S
    if not S.CANDIDATE or S.CANDIDATE == "fa_v4":
        raise SystemExit("set TOWN_FULL3D_CANDIDATE to the T2 candidate (never the fa_v4 seed)")
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    t2 = report.setdefault("t2Buildings", {})
    for lid in layers:
        t0 = time.time()
        # a restage drops this layer's body bins (seed relief or earlier T2); stage_layer re-emits what it has
        pk = S.PREFIX + lid
        rows[pk]["bins"] = [b for b in rows[pk]["bins"] if b["name"] != f"Mesh_Body_{lid}"
                            and not b["name"].startswith(("Mesh_BodyM_", "Mesh_BodyRest_"))]
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        sc.pieces = {}
        r = stage_layer(sc, lid)
        S.save_rows(sc)
        rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
        r["seconds"] = round(time.time() - t0, 1)
        t2[lid] = r
        b = report["buildings"][lid]
        b.update({"method": "meshy_t2", "texelsPerPx": r["texelsPerPx"], "tris": r["tris"] + r.get("residualTris", 0),
                  "frontTris": r["frontTris"]})
        rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(lid, json.dumps(r), flush=True)
    S.write_catalog(sc, carry="fresh")
    return 0


def restore(layers: list[str]) -> int:
    """Put the seed's (fa_v4) relief back for a layer whose Meshy body is broken (the revert list in
    docs/homm3_factory_t2_town_buildings.md): the prefab's staged files and rows and its stage_report entry, verbatim."""
    import stronghold_full3d_scene as S
    if not S.CANDIDATE or S.CANDIDATE == "fa_v4":
        raise SystemExit("set TOWN_FULL3D_CANDIDATE to the T2 candidate (never the fa_v4 seed)")
    sstage = SEED / S.STAGE.relative_to(S.CAND)
    srows = json.loads((sstage / "rows.json").read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    sreport = json.loads((SEED / "work" / "stage_report.json").read_text(encoding="utf-8"))
    for lid in layers:
        prefab = S.PREFIX + lid
        shutil.rmtree(S.STAGE / prefab)
        shutil.copytree(sstage / prefab, S.STAGE / prefab)
        rows[prefab] = srows[prefab]
        report["buildings"][lid] = sreport["buildings"][lid]
        report.setdefault("t2Buildings", {}).pop(lid, None)
        report.setdefault("t2Reverted", {})[lid] = REVERTED.get(lid, "relief restored from fa_v4 (broken Meshy body)")
        print("restored", lid, flush=True)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    S.write_catalog(S.Scene(), carry="fresh")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "restore"])
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--faction", default="factory")
    a = ap.parse_args()
    layers = a.layer or [x for x in FM.MESH_LAYERS + list(FM.REUSE) if x not in REVERTED]
    if a.cmd == "fit":
        for lid in layers:
            fit(lid)
        return 0
    if a.cmd == "restore":
        if not a.layer:
            raise SystemExit("restore: name the layers (--layer L)")
        return restore(a.layer)
    return stage(layers)


if __name__ == "__main__":
    raise SystemExit(main())
