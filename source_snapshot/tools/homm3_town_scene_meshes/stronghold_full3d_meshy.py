#!/usr/bin/env python3
"""Stronghold full-3D town: Meshy T2 building meshes registered to their HoMM3 sprites (docs/homm3_stronghold_t2_town_buildings.md).

Replaces the Mesh_Body_<layer> bin of each layer in the profile's MESHY_T2 table inside a candidate seeded from the
installed lane (TOWN_FULL3D_CANDIDATE, `stronghold_full3d_scene.py candidate-init --seed-from wall_v40`). Every other
layer, the terrain, sky, periphery, near field and effects stay the seed's staged bins, byte for byte.

Per layer:
  * register  fit_mesh_to_sprite.Fitter under the rest camera (painting world; the painting world is left-handed like
              Unity, so the GLB takes the glTFast x negation): yaw searched within +-YAW_WINDOW of "front faces the
              camera", scale and ground-contact pixel on the calibrated terrain depth, then the optional vertical-stretch
              pass; F-beta 0.5 against the layer's native mask (precision-weighted: painted ground skirts stay terrain).
              A layer cut by the painting's right edge ("openRight") does not score the silhouette past x = TW.
  * surgery   per-layer "cut" rules (t2_mesh_surgery.PARTS_RULES) drop whole connected parts the review found broken; clipLeft /
              EDGE_FRAY cut a sprite the painting's frame cuts.
  * texture   painted front (town_full3d_t2_paint, coordinator rule 2026-09-29): drawn faces are split to 4 px edges;
              faces seen at rest (own-px share, or centre / any corner at the rest surface) take the sprite by screen
              position, de-lit through the smooth view normal they ship with (Mesh_Body_<layer>); every other face
              keeps the Meshy texture in its own UVs, gain-matched to the painting (Mesh_Body_<layer>_hull). Both
              two-sided (T2 shells are open; the game culls back faces).
  * residual  sprite px the body leaves uncovered at rest keep the seed relief's triangles (Mesh_Body_<layer>_rest).

    TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_meshy.py stage [--only a,b]

Proof tier: generated artifact (offline previews; Unity editor renders are the review evidence).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_scene as S  # noqa: E402  (reads TOWN_FULL3D_CANDIDATE)
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_ground as G  # noqa: E402
import stronghold_full3d_buildings as BL  # noqa: E402
import fit_mesh_to_sprite as FM  # noqa: E402
import t2_mesh_surgery as MS  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
MESHY = SC.ROOT / "artifacts" / "meshy_town_scene_meshes" / SC.FRACTION
YAW_WINDOW = 45.0     # deg either side of "the model's +Z front faces the camera"
SS = 2                # rest id/depth buffer and sprite sampling: SS x the 1080p frame


def table() -> dict:
    t = getattr(SC.FP, "MESHY_T2", None)
    if not t:
        raise SystemExit("profile has no MESHY_T2 table")
    return t


# ------------------------------------------------------------------------------------------------ glb
def load_glb(path: Path) -> dict:
    import trimesh
    sc = trimesh.load(str(path), force="scene")
    geos = list(sc.geometry.values())
    if len(geos) != 1:
        raise SystemExit(f"{path}: {len(geos)} geometries (one textured mesh expected)")
    # the node transform (Meshy writes identity, but apply it anyway)
    node = sc.graph.nodes_geometry[0]
    Tm, _ = sc.graph[node]
    m = geos[0].copy()
    m.apply_transform(Tm)
    vis = m.visual
    uv = np.asarray(vis.uv, np.float64).copy()
    if uv.ndim == 2:
        uv[:, 1] = 1.0 - uv[:, 1]   # trimesh stores glTF uv flipped to bottom-origin; this module uses glTF's top-origin
    mat = vis.material
    img = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
    if img is None or uv is None or len(uv) != len(m.vertices):
        raise SystemExit(f"{path}: no base colour texture / per-vertex uv")
    v = np.asarray(m.vertices, np.float64).copy()
    n = np.asarray(m.vertex_normals, np.float64).copy()
    v[:, 0] *= -1.0          # glTF right-handed -> left-handed (Unity / painting world)
    n[:, 0] *= -1.0
    f = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]   # the mirror flips the winding back
    return {"v": v, "n": n, "f": f, "uv": uv, "tex": np.asarray(img.convert("RGB"))}


# ------------------------------------------------------------------------------------------------ fit
class OpenFitter(FM.Fitter):
    """Fitter that ignores the silhouette right of open_x (frame px): the sprite is cut by the painting's edge there."""

    def __init__(self, *a, open_x: float | None = None, **k):
        super().__init__(*a, **k)
        self.open_x = open_x

    def silhouette(self, w, full=False):
        s = super().silhouette(w, full)
        if self.open_x is not None:
            x0 = 0 if full else self.win[0]
            c = int(math.floor(self.open_x / self.down)) - x0
            if c < s.shape[1]:
                s[:, max(0, c):] = False
        return s


def frame_mask(L: dict) -> np.ndarray:
    m = BL.native_mask(L).astype(np.uint8) * 255
    mf = cv2.resize(m, (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((H, W), np.uint8)
    x, y = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    sy, sx = max(0, -y), max(0, -x)
    h_, w_ = min(mf.shape[0] - sy, H - max(0, y)), min(mf.shape[1] - sx, W - max(0, x))
    out[max(0, y):max(0, y) + h_, max(0, x):max(0, x) + w_] = mf[sy:sy + h_, sx:sx + w_]
    return out > 127


def ground_depth(sc) -> np.ndarray:
    st = S.terrain_state(sc)
    z = np.array(st["fd"]["zs"], np.float64)
    bad = ~np.isfinite(z)
    if bad.any():
        z = BL._fill_nearest(z[..., None], ~bad)[..., 0]
    return z


def fit_path(spec: dict) -> Path:
    return (MESHY / spec["glb"]).with_name("fit.json")


def fit_search(sc, lid: str, L: dict, g: dict, spec: dict, z: np.ndarray) -> dict:
    """The registration search (slow); its result is cached next to the GLB as fit.json, keyed by the GLB's sha256
    and the spec's fit keys, and re-used by every stage."""
    import hashlib
    tgt = frame_mask(L)
    open_x = float(TW) if spec.get("openRight") else None
    fz = OpenFitter(sc.cam, z, (W, H), tgt, g["v"], g["f"], down=2, open_x=open_x)
    fh, _ = T.heading(sc.cam)
    yaw0 = math.degrees(math.atan2(-fh[0], -fh[2])) + float(spec.get("yawOffset", 0.0))
    yaws = [yaw0 + d for d in np.arange(-YAW_WINDOW, YAW_WINDOW + 0.1, 15.0)]
    ys, xs = np.nonzero(tgt)
    base = fz.fit((xs.min(), ys.min(), xs.max(), ys.max()), yaws=yaws)
    best = base
    if spec.get("stretch", True):
        st = fz.refine_stretch(base)
        if st["fbeta"] > base["fbeta"]:
            best = st
    rep = {k: best[k] for k in ("yaw", "scale", "contactPx", "fbeta", "stretchY", "iou", "precision", "recall",
                                "worldHeight")}
    rep.update({"yawFront": yaw0, "yawRel": ((best["yaw"] - yaw0 + 180) % 360) - 180,
                "openRight": open_x is not None, "key": fit_key(spec),
                "glbSha256": hashlib.sha256((MESHY / spec["glb"]).read_bytes()).hexdigest()})
    fit_path(spec).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def fit_key(spec: dict) -> dict:
    return {k: spec.get(k) for k in ("openRight", "yawOffset", "stretch")}


def fit_cached(spec: dict) -> dict:
    import hashlib
    p = fit_path(spec)
    if not p.is_file():
        raise SystemExit(f"{spec['glb']}: no fit.json (run the fit command)")
    rep = json.loads(p.read_text(encoding="utf-8"))
    if rep.get("key") != fit_key(spec) or rep.get("glbSha256") != hashlib.sha256((MESHY / spec["glb"]).read_bytes()).hexdigest():
        raise SystemExit(f"{spec['glb']}: fit.json is stale (spec or GLB changed; rerun fit)")
    return rep


def place(sc, g: dict, spec: dict, fit: dict, z: np.ndarray) -> dict:
    fz = FM.Fitter(sc.cam, z, (W, H), np.ones((4, 4), bool), g["v"], g["f"], down=2)
    pos, w = fz.transform(fit["yaw"], fit["scale"], *fit["contactPx"], fit["stretchY"])
    R = FM.yaw_matrix(fit["yaw"])
    n = (g["n"] * np.array([1.0, 1.0 / fit["stretchY"], 1.0])) @ R.T   # inverse-transpose under the vertical stretch
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    sink = float(spec.get("sink", 0.02)) * fit["worldHeight"]
    w = w - np.array([0.0, sink, 0.0])
    return {"P": w, "n": n, "fit": {**{k: v for k, v in fit.items() if k not in ("key",)}, "sinkM": sink}}


# ------------------------------------------------------------------------------------------------ rest visibility
def rest_depth(cam: dict, P: np.ndarray, F: np.ndarray):
    """Nearest forward depth per SS x frame pixel of the mesh at the rest pose (painter's order, per-pixel plane)."""
    px, py, zc = T.project(cam, P)
    X, Y = px * SS, py * SS
    ids = np.full((H * SS, W * SS), -1, np.int32)
    order = np.argsort(-zc[F].mean(1))
    pts = np.round(np.stack([X, Y], 1) * 4).astype(np.int32)
    for t in order:
        cv2.fillPoly(ids, [pts[F[t]]], int(t), lineType=cv2.LINE_8, shift=2)
    yy, xx = np.nonzero(ids >= 0)
    t = ids[yy, xx]
    a, b, c = F[t, 0], F[t, 1], F[t, 2]
    qx, qy = xx + 0.5, yy + 0.5
    d = (Y[b] - Y[c]) * (X[a] - X[c]) + (X[c] - X[b]) * (Y[a] - Y[c])
    d = np.where(np.abs(d) < 1e-9, 1e-9, d)
    l1 = ((Y[b] - Y[c]) * (qx - X[c]) + (X[c] - X[b]) * (qy - Y[c])) / d
    l2 = ((Y[c] - Y[a]) * (qx - X[c]) + (X[a] - X[c]) * (qy - Y[c])) / d
    l1, l2 = np.clip(l1, 0, 1), np.clip(l2, 0, 1)
    l3 = np.clip(1 - l1 - l2, 0, 1)
    inv = l1 / zc[a] + l2 / zc[b] + l3 / zc[c]          # perspective-correct: 1/z is affine in screen space
    dep = np.full(ids.shape, np.inf)
    dep[yy, xx] = 1.0 / np.maximum(inv, 1e-9)
    return dep, ids


_W: dict = {}


def _worker():
    """Per-process scene and ground depth (the pool's workers build them once)."""
    if not _W:
        _W["sc"] = S.Scene()
        _W["z"] = ground_depth(_W["sc"])
    return _W["sc"], _W["z"]


def fit_one(lid: str) -> dict:
    sc, z = _worker()
    spec = table()[lid]
    g = load_glb(MESHY / spec["glb"])
    rep = fit_search(sc, lid, SC.layers()[lid], g, spec, z)
    print(lid, "fit", json.dumps({k: rep[k] for k in ("iou", "precision", "recall", "yawRel", "stretchY")}), flush=True)
    return rep


def clip_edges(sc, lid: str, spec: dict, P, N, uv, F):
    """A sprite cut by the painting's frame edge: the mesh past that edge is not the painting's building (it would
    hang past the frame the lane's framing keeps in view). clipLeft drops every triangle with a vertex left of the
    frame's x = 0 at rest; the profile's EDGE_FRAY (right edge) applies the relief lane's own ragged cut
    (stronghold_full3d_buildings.edge_fray, geometry only). Unused vertices are dropped."""
    rep = {}
    F = np.asarray(F)
    if spec.get("clipLeft"):
        px, _py, _ = T.project(sc.cam, P)
        drop = (px[F] < 0).any(1)
        F = F[~drop]
        rep["clipLeftDroppedTris"] = int(drop.sum())
    fray = (getattr(SC.FP, "EDGE_FRAY", None) or {}).get(lid)
    if fray and spec.get("openRight"):
        m = {"P": P, "tris": F, "frontTris": len(F)}
        rep["edgeFray"] = BL.edge_fray(lid, m, sc.cam, fray)
        F = np.asarray(m["tris"])
    if not rep:
        return P, N, uv, F, None
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], N[used], uv[used], remap[F].astype(np.int32), rep


def build_one(lid: str) -> dict:
    """The layer's placed body, painted-front baked (town_full3d_t2_paint) and staged by this worker; returns its rows
    and report (the parent merges the rows)."""
    import town_full3d_t2_paint as PF
    sc, z = _worker()
    sc.pieces = {}
    spec = table()[lid]
    L = SC.layers()[lid]
    g = load_glb(MESHY / spec["glb"])
    fit = place(sc, g, spec, fit_cached(spec), z)
    P, N = fit["P"], fit["n"]
    uv_t = np.stack([g["uv"][:, 0], 1.0 - g["uv"][:, 1]], 1)      # trimesh / Unity convention (v up)
    P, N, uv_t, F, cut = MS.cut_parts(P, N, uv_t, g["f"], g, spec)
    F = PF.outward(P, N, F)
    P, N, uv_t, F, clip = clip_edges(sc, lid, spec, P, N, uv_t, F)
    P, N, uv_t, F, srep = PF.subdivide_screen(sc.cam, P, N, uv_t, F)
    tex_lin = G.SC_srgb_to_lin(np.asarray(g["tex"]).astype(np.float32) / 255)
    brep = PF.painted_split(sc, lid, L, BL.native_mask(L), P, N, F, uv_t, tex_lin, f"Mesh_Body_{lid}",
                            f"Mesh_Body_{lid}_hull")
    brep["subdivide"] = srep
    if cut:
        brep["cut"] = cut
    if clip:
        brep["edgeClip"] = clip
    rep = {"method": "meshy_t2", "glb": spec["glb"], "tris": int(2 * (brep["frontTris"] + brep["meshyTris"])),
           "doubleSided": True, "texelsPerPx": brep["texelsPerPx"], "fit": fit["fit"], "bake": brep}
    print(lid, json.dumps(rep), flush=True)
    return {"lid": lid, "rows": sc.pieces.get(S.PREFIX + lid, []), "rep": rep}


def pool_map(fn, items, procs: int):
    if procs <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(min(procs, len(items))) as ex:
        return list(ex.map(fn, items))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "finish"])
    ap.add_argument("--only", default="")
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE (never stage over the installed base outputs)")
    tab = table()
    only = [x for x in a.only.split(",") if x] or list(tab)
    unknown = [x for x in only if x not in tab]
    if unknown:
        raise SystemExit(f"not in MESHY_T2: {unknown}")
    if a.cmd == "fit":
        pool_map(fit_one, only, a.procs)
        return 0
    for lid in only:
        fit_cached(tab[lid])
    sc = S.Scene()
    rep = {}
    if a.cmd == "finish":
        # the post-bin steps only (report, walls, catalog, preview, see-through) over already staged bins
        return finish(sc, {})
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    for m in pool_map(build_one, only, a.procs):
        pk = S.PREFIX + m["lid"]
        emitted = {b["name"] for b in m["rows"]}
        # a restaged layer keeps no body piece it no longer emits (the _rest residual is finish's)
        rows[pk]["bins"] = [b for b in rows[pk]["bins"] if not b["name"].startswith(f"Mesh_Body_{m['lid']}")
                            or b["name"] in emitted or b["name"] == f"Mesh_Body_{m['lid']}_rest"]
        sc.pieces[pk] = m["rows"]
        rep[m["lid"]] = m["rep"]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    S.save_rows(sc)
    return finish(sc, rep)


SEED = "wall_v40"          # the installed candidate this lane is seeded from (the residual's source)
RESIDUAL_DILATE = 3       # frame px the Meshy rest silhouette is grown before the uncovered sprite is taken
RESIDUAL_MIN_PX = 150     # uncovered sprite px below which no residual piece is emitted (reported)


def residual(sc, lid: str) -> dict:
    """Mesh_Body_<lid>_rest: the seed's own depth solid, only its triangles whose rest centroid falls on sprite pixels
    the Meshy silhouette leaves uncovered (fit recall < 1: fountain basins, plaza steps, thin poles). The rest frame
    then keeps the painting there instead of showing terrain; the Meshy body is unchanged. (Pattern of cove_t2_stage.)"""
    prefab = S.PREFIX + lid
    L = SC.layers()[lid]
    parts = []
    for nm in (f"Mesh_Body_{lid}", f"Mesh_Body_{lid}_hull"):
        if (S.STAGE / prefab / f"{nm}.bytes").is_file():
            v_, _n, _uv, subs = S.read_bin(S.STAGE / prefab / f"{nm}.bytes")
            parts.append((sc.cpos + (v_.astype(np.float64) / sc.scale) @ sc.C.T,
                          np.concatenate(subs).astype(np.int64).reshape(-1, 3)))
    off = np.cumsum([0] + [len(p_) for p_, _ in parts])
    Pm = np.concatenate([p_ for p_, _ in parts])
    dep, _ = rest_depth(sc.cam, Pm, np.concatenate([f_ + o for (_, f_), o in zip(parts, off)]))
    sil = np.isfinite(dep).reshape(H, SS, W, SS).any(axis=(1, 3))
    grown = cv2.dilate(sil.astype(np.uint8), np.ones((2 * RESIDUAL_DILATE + 1,) * 2, np.uint8)).astype(bool)
    spr = frame_mask(L)
    resid = spr & ~grown
    resid[TH:, :] = False
    resid[:, TW:] = False
    out = {"spritePx": int(spr.sum()), "restCoverOfSprite": round(float((sil & spr).sum() / max(1, spr.sum())), 4),
           "uncoveredPx": int(resid.sum()), "tris": 0, "seed": SEED}
    name = f"Mesh_Body_{lid}_rest"
    if resid.sum() < RESIDUAL_MIN_PX:
        return out
    seedb = SC.DATA / "candidates" / SEED / "unity_project" / S.ASSET_ROOT / prefab / f"Mesh_Body_{lid}.bytes"
    if not seedb.is_file():
        raise SystemExit(f"residual: no seed body {seedb}")
    v, n, uv, ss = S.read_bin(seedb)
    tris = np.concatenate(ss).astype(np.int64).reshape(-1, 3)
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    nw = n.astype(np.float64) @ sc.C.T
    rx, ry, _ = T.project(sc.cam, P)
    cx = np.clip(np.round(rx[tris].mean(1)).astype(int), 0, W - 1)
    cy = np.clip(np.round(ry[tris].mean(1)).astype(int), 0, H - 1)
    import town_full3d_t2_paint as PF
    on = resid[cy, cx]
    keep = on & PF.facing_rest(sc.cam, P, tris)     # grazing relief sides streak at the sweeps (cv_t2 review)
    out["grazingDropped"] = int((on & ~keep).sum())
    if not keep.any():
        return out
    used = np.unique(tris[keep])
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    img = np.asarray(Image.open(seedb.with_name(seedb.stem + "_albedo.png")).convert("RGB"))
    # a cut-out of a closed solid is open at the cut: double-sided like the Meshy body (see-through gate)
    Pr, Nr, uvr, Fr = PF.two_sided(P[used], nw[used], uv[used], remap[tris[keep]])
    sc.add_bin(prefab, name, Pr, Nr, uvr, Fr.astype(np.int32), img, srgb=True)
    out["tris"] = int(keep.sum())
    return out


def catalog_block(rep: dict) -> None:
    """The catalog's own record of the Meshy building layers (the lane's nearField/periphery meshyCredits stay 0: those
    parts use none). Credits are the faction's ledger lines (stronghold_t2_meshy.spend)."""
    import stronghold_t2_meshy as MT
    cp = S.OUT / "catalog.json"
    cat = json.loads(cp.read_text(encoding="utf-8"))
    sp = MT.spend()
    cat["meshyBuildings"] = {
        "method": "meshy_t2 image-to-3d per building sprite, fitted to the sprite under the rest camera; painted front "
                  "(town_full3d_t2_paint: faces seen at rest take the sprite by screen position, de-lit through the smooth "
                  "view normal), the Meshy texture elsewhere; two-sided; seed relief residual "
                  f"({SEED}) on sprite px the mesh leaves uncovered",
        "layers": sorted(rep), "meshyCredits": sp["spent"], "ledgerCalls": sp["calls"],
        "doc": "docs/homm3_stronghold_t2_town_buildings.md"}
    cp.write_text(json.dumps(cat, indent=1) + chr(10), encoding="utf-8")


def finish(sc, rep: dict) -> int:
    rp = S.WORK / "stage_report.json"
    old = json.loads(rp.read_text(encoding="utf-8"))
    for lid, r in rep.items():
        old.setdefault("buildings", {})[lid] = r
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    for lid in table():
        if lid not in old.get("buildings", {}) or old["buildings"][lid].get("method") != "meshy_t2":
            continue
        r = residual(sc, lid)
        old["buildings"][lid]["residual"] = r
        if not r["tris"]:
            # a restaged layer that no longer needs a residual keeps no stale _rest row
            row = rows.get(S.PREFIX + lid)
            if row:
                row["bins"] = [x for x in row["bins"] if x["name"] != f"Mesh_Body_{lid}_rest"]
        b = old["buildings"][lid]
        b["tris"] = 2 * (b["bake"]["frontTris"] + b["bake"]["meshyTris"] + r["tris"])   # all pieces two-sided
        print(lid, "residual", json.dumps(r), flush=True)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    S.save_rows(sc)
    rep = {lid: r for lid, r in old.get("buildings", {}).items() if r.get("method") == "meshy_t2"}
    old["meshyT2"] = {"layers": sorted(set(old.get("meshyT2", {}).get("layers", [])) | set(rep)),
                      "method": "Meshy T2 mesh fitted to the sprite; painted front (town_full3d_t2_paint) + Meshy remainder"}
    rp.write_text(json.dumps(json.loads(json.dumps(old, default=lambda o: o.tolist() if hasattr(o, "tolist")
                                                   else str(o))), indent=1), encoding="utf-8")
    # a Meshy layer has no closing walls: drop its seed entry so the Unity rest-walls check does not look for them
    wf = S.WORK / "closing_walls.npz"
    if wf.is_file():
        edges = {k: v for k, v in dict(np.load(wf)).items() if k not in rep}
        np.savez(wf, **edges)
    S.write_catalog(sc, carry="fresh")
    catalog_block(rep)
    S.load_staged_preview(sc)
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    print(S.preview(sc, S.WORK / "preview", cams))
    st = S.see_through_report(sc)
    (S.WORK / "see_through.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    old = json.loads(rp.read_text(encoding="utf-8"))
    old["seeThrough"] = {k: st[k] for k in ("metric", "totalPx", "mode", "baseline", "worse")}
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    print(json.dumps({"seeThrough": old["seeThrough"]}))
    S.cull_gate_or_exit(st)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
