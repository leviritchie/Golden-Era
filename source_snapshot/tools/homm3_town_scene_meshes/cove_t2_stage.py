#!/usr/bin/env python3
"""Cove Meshy T2 buildings: register each mesh to its sprite and stage it into a full-3D candidate.

Faction-scoped (the shared stronghold_full3d_* modules are imported, never edited; 11 towns are rebuilt in parallel).
Method and verdict: docs/homm3_cove_t2_town_buildings.md.

    python tools/homm3_town_scene_meshes/cove_t2_stage.py fit   [--only a,b]
    TOWN_FULL3D_CANDIDATE=<c> python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py candidate-init --faction cove --seed-from cv_v11
    TOWN_FULL3D_CANDIDATE=<c> python tools/homm3_town_scene_meshes/cove_t2_stage.py stage [--only a,b]

fit    fit_mesh_to_sprite.Fitter under the lane's rest camera (painting world): yaw searched over the full circle (Meshy's front axis is not fixed), uniform
       scale and the ground contact pixel, F-beta (0.5) of the rest silhouette against the sprite's
       opaque pixels, counted only inside the painted rect (a sprite the frame cuts is fitted to its painted part, the
       model may continue past the cut). The contact depth is the lane's own footing of that sprite column
       (stronghold_full3d_buildings.layer_depth foot_z), the terrain elsewhere. Then Fitter.refine_stretch (vertical
       stretch STRETCH) is kept only when it raises the IoU. Writes <layer>/placement.json + fit_viz.png.
stage  per meshed layer the prefab's Mesh_Body_<id> is replaced by up to three pieces (all Mesh_Body_ names, so the
       see-through metric counts them), every one two-sided:
         Mesh_Body_<id>        the painted front (town_full3d_t2_paint, coordinator rule 2026-09-29): faces the rest
                               camera sees (edges split to 4 px; own-px share or centre/any-corner visibility) take
                               the sprite by screen position, de-lit through the smooth view normal they ship with
         Mesh_Body_<id>_hull   every other face: the Meshy texture on the Meshy UVs, gain-matched to the painting
         Mesh_Body_<id>_rest   the seed candidate's depth solid, only its triangles whose rest projection falls on
                               sprite pixels the Meshy silhouette does not cover (so no painted pixel is lost at rest)
       Layers in STAGE_SKIP keep the seed relief (a genuinely broken mesh, judged by eye; reason recorded).
       The prefab's Fx_ pieces are kept. The stage report, rows, catalog (+ a "meshyBuildings" block) and preview
       are rewritten; the see-through gate runs as in the lane's own building stage.
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "cove")
if os.environ["TOWN_FULL3D_FACTION"] != "cove":
    raise SystemExit("cove_t2_stage: TOWN_FULL3D_FACTION must be cove")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import cove_t2_buildings as CB  # noqa: E402
import fit_mesh_to_sprite as FM  # noqa: E402
import t2_mesh_surgery as MS  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
OUTD = CB.OUTD
STRETCH = (0.8, 1.25)
RESIDUAL_MIN_PX = 150     # frame px of uncovered sprite below which no residual piece is kept (reported)
RESIDUAL_DILATE = 3       # frame px the Meshy silhouette is grown before the residual is taken
HULL_MAX = 1024           # Unity maxSize of the Meshy texture
COARSE_STEP = 15.0        # fit: full-circle yaw step of the coarse pass
COARSE_TRIS = 2500        # fit: decimated triangle count of the coarse pass
COARSE_KEEP = 3           # fit: coarse yaws refined on the full mesh
# mesh surgery (t2_mesh_surgery rules; review of cv_t2 stage 1 at rest and the sweeps). Every layer drops what the
# painting does not show at rest: whole parts mostly off the sprite (offSprite: the tavern's invented deck and beach,
# the hall's and nixie's side scenery), stray one- or two-triangle sheets (loneSheets: the smithy's and market's
# flying slivers), then every remaining face off the sprite (offSpriteFaces: a deck in one piece with its building;
# the Meshy bodies run past the painting edge and under the ground). Measured need: with the tavern deck alone kept,
# the framing aim (union of the building bounds) left ten buildings outside the visible region; with every body kept
# past the sprite the union was 0.94 of the frame wide against the 0.90 visible region.
CUT_DEFAULT = ["offSprite", "loneSheets", "offSpriteFaces"]
PAINT_ORDER_TOL = 0.01    # paintOrder: relative camera-z margin before a face counts as in front of a later layer
CUT: dict = {}
# meshed but not staged: the layer keeps the seed's depth solid (reason recorded in the catalog block)
STAGE_SKIP = {
    "tbcvsay1": "two Meshy attempts (a1 and the stilt-preserving a2 input) both closed the stilt rows into solid grey "
                "slab columns; a slab is worse than the seed relief at the sweeps",
    "tbcvsay2": "two Meshy attempts both closed the stilt rows into solid grey slab columns (as tbcvsay1)",
}


def double_side(P, N, uv, F):
    """Every triangle also gets its reverse (own vertices, negated normals, same texels). The Meshy shells are open
    and the front / hull split cuts them further, so a camera that sees a sheet from behind would lose it to the
    game's Cull Back (town_full3d_cull); at any pixel only one of a pair faces the camera, so the pair never z-fights."""
    n = len(P)
    return (np.concatenate([P, P]), np.concatenate([N, -N]), np.concatenate([uv, uv]),
            np.concatenate([F, F[:, [0, 2, 1]] + n]).astype(np.int32))


# ------------------------------------------------------------------------------------------------ model
def load_meshy(path: Path) -> dict:
    """The glb in the lane's frame (Unity-handed: x negated, winding reversed so numeric normals point outward), with
    its UVs (trimesh: v up) and base-colour texture."""
    import trimesh
    scn = trimesh.load(str(path), force="scene")
    nodes = list(scn.graph.nodes_geometry)
    if len(nodes) != 1:
        raise SystemExit(f"{path}: {len(nodes)} geometry nodes (expected 1)")
    tf, gname = scn.graph[nodes[0]]
    g = scn.geometry[gname]
    V = trimesh.transformations.transform_points(np.asarray(g.vertices, np.float64), tf)
    N = np.asarray(g.vertex_normals, np.float64) @ np.asarray(tf)[:3, :3].T
    F = np.asarray(g.faces, np.int64)
    uv = np.asarray(g.visual.uv, np.float64)
    tex = g.visual.material.baseColorTexture
    if tex is None:
        raise SystemExit(f"{path}: no base colour texture")
    V[:, 0] *= -1
    N[:, 0] *= -1
    F = F[:, [0, 2, 1]]
    N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    out = float(((V[F].mean(1) - V.mean(0)) * fn).sum())
    return {"V": V, "N": N, "F": F, "uv": uv, "tex": tex.convert("RGB"), "outward": out > 0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "tris": int(len(F)), "verts": int(len(V))}


def facing_yaw(cam) -> float:
    f = T.heading(cam)[0]
    return math.degrees(math.atan2(-f[0], -f[2]))


# ------------------------------------------------------------------------------------------------ fit
class CareFitter(FM.Fitter):
    """Fitter whose silhouette is only scored inside `care` (frame bool, the painted rect)."""

    def __init__(self, *a, care=None, **k):
        super().__init__(*a, **k)
        full = care[::self.down, ::self.down]
        self.care_full = full
        self.care = full[self.win[1]:self.win[3], self.win[0]:self.win[2]]

    def score(self, yaw, scale, px, py, beta=0.5, stretch_y=1.0) -> float:
        if scale <= 0:
            return 0.0
        _, w = self.transform(yaw, scale, px, py, stretch_y)
        s = self.silhouette(w) & self.care
        tp = float(np.logical_and(s, self.tgt).sum())
        if tp == 0:
            return 0.0
        prec = tp / float(s.sum())
        rec = tp / float(self.tgt.sum())
        b2 = beta * beta
        return (1 + b2) * prec * rec / (b2 * prec + rec)

    def _result(self, yaw, scale, px, py, stretch_y, fbeta) -> dict:
        r = super()._result(yaw, scale, px, py, stretch_y, fbeta)
        full = r["silhouette"] & self.care_full
        tgt = self.target
        inter = np.logical_and(full, tgt).sum()
        r.update({"iou": float(inter / max(1, np.logical_or(full, tgt).sum())),
                  "precision": float(inter / max(1, full.sum())), "recall": float(inter / max(1, tgt.sum()))})
        return r


def frame_mask(L: dict, m: np.ndarray) -> np.ndarray:
    """A native-px sprite mask placed in the 1920x1080 frame (x1.8 at the layer position)."""
    out = np.zeros((H, W), np.uint8)
    x0, y0 = int(round(L["x"] * SC.SCALE)), int(round(L["y"] * SC.SCALE))
    w, h = int(round(m.shape[1] * SC.SCALE)), int(round(m.shape[0] * SC.SCALE))
    big = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(W, x0 + w), min(H, y0 + h)
    out[ya:yb, xa:xb] = big[ya - y0:yb - y0, xa - x0:xb - x0]
    return out.astype(bool)


def contact_depth(lid: str, L: dict, rd: dict) -> np.ndarray:
    """Frame camera depth for the contact pixel: the lane's footing of the sprite's columns inside the sprite's
    columns, the calibrated terrain elsewhere (sky / outside the rect: the terrain's median)."""
    import stronghold_full3d_buildings as BL
    z = np.full((H, W), np.nan)
    zc = rd["zc"]
    z[:TH, :TW] = zc
    z[~np.isfinite(z)] = float(np.nanmedian(zc))
    ld = BL.layer_depth(lid, L, rd)
    foot = ld["foot_z"]
    for c in range(len(foot)):
        xa = int(math.floor((L["x"] + c) * SC.SCALE))
        xb = int(math.ceil((L["x"] + c + 1) * SC.SCALE))
        xa, xb = max(xa, 0), min(xb, W)
        if xb > xa and np.isfinite(foot[c]):
            z[:, xa:xb] = foot[c]
    return z, ld


def fit_layer(sc, rd, lid: str) -> dict:
    L = SC.layers()[lid]
    d = OUTD / lid
    model = load_meshy(d / "model.glb")
    tgt = frame_mask(L, CB.sprite_mask(L))
    care = np.zeros((H, W), bool)
    care[:TH, :TW] = True
    z, ld = contact_depth(lid, L, rd)
    fz = CareFitter(sc.cam, z, (W, H), tgt.astype(np.uint8), model["V"], model["F"], care=care)
    ys, xs = np.nonzero(tgt)
    bbox = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
    y0 = facing_yaw(sc.cam)
    t0 = time.time()
    # Coarse: the full circle on a decimated copy at quarter resolution (the full mesh at half resolution is ~0.1 s
    # a score); fine: the full mesh at half resolution from the COARSE_KEEP best coarse yaws.
    import fast_simplification
    cv_, cf_ = fast_simplification.simplify(model["V"].astype(np.float32), model["F"].astype(np.int32),
                                            target_reduction=max(0.0, 1.0 - COARSE_TRIS / len(model["F"])))
    fc = CareFitter(sc.cam, z, (W, H), tgt.astype(np.uint8), np.asarray(cv_, np.float64),
                    np.asarray(cf_, np.int64), down=4, care=care)
    from scipy.optimize import minimize
    x0_, y0b, x1_, y1b = bbox
    px0, py0 = (x0_ + x1_) / 2, y1b - 0.05 * (y1b - y0b)
    zf = float(z[int(np.clip(py0, 0, H - 1)), int(np.clip(px0, 0, W - 1))])
    s0 = ((y1b - y0b) / H * 2 * zf * fc.t) / max(1e-6, fc.model_h)
    coarse = []
    for a in np.arange(0.0, 360.0, COARSE_STEP):   # the same start and simplex as Fitter.fit, one yaw at a time
        r = minimize(lambda p_: -fc.score(float(a), p_[0], p_[1], p_[2]), [s0, px0, py0], method="Nelder-Mead",
                     options={"xatol": 0.5, "fatol": 1e-4, "maxiter": 160,
                              "initial_simplex": [[s0, px0, py0], [s0 * 1.25, px0, py0],
                                                  [s0, px0 + 25, py0], [s0, px0, py0 - 25]]})
        coarse.append((float(-r.fun), float(a)))
    coarse.sort(reverse=True)
    keep = [y for _, y in coarse[:COARSE_KEEP]]
    base = fz.fit(bbox, yaws=keep)
    base["coarseYaws"] = [[round(y, 1), round(f, 4)] for f, y in coarse[:COARSE_KEEP]]
    res = base
    st = fz.refine_stretch(base, lo=STRETCH[0], hi=STRETCH[1])
    if st["iou"] > base["iou"] + 0.005:
        res = st
    sil = res.pop("silhouette")
    st.pop("silhouette", None)
    out = {"layer": lid, "modelSha256": model["sha256"], "modelTris": model["tris"], "outward": model["outward"],
           "cameraFacingYaw": round(y0, 2), "yawSearch": f"coarse 0..360 step {COARSE_STEP} (decimated {COARSE_TRIS} tris, 1/4 res), fine best {COARSE_KEEP}", **{k: v for k, v in res.items()},
           "stretchTried": {"iou": round(st["iou"], 4), "stretchY": round(st["stretchY"], 3), "kept": res is st},
           "baseFit": {k: round(base[k], 4) for k in ("iou", "precision", "recall", "fbeta")},
           "footZmMedian": round(float(np.nanmedian(ld["foot_z"])), 2), "seconds": round(time.time() - t0, 1),
           "fitter": "fit_mesh_to_sprite.Fitter (F-beta 0.5, care = painted rect)"}
    (d / "placement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # viz: painting + sprite, the fitted silhouette outline
    ref = np.asarray(reference_frame([lid]))
    img = ref.copy()
    full = sil if sil.shape == (H, W) else cv2.resize(sil.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
    cnt, _ = cv2.findContours(full.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnt, -1, (0, 255, 255), 1)
    cnt2, _ = cv2.findContours(tgt.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnt2, -1, (255, 0, 255), 1)
    x0, y0_, x1, y1 = int(bbox[0]) - 40, int(bbox[1]) - 40, int(bbox[2]) + 40, int(bbox[3]) + 40
    crop = img[max(0, y0_):min(H, y1), max(0, x0):min(W, x1)]
    Image.fromarray(crop).resize((crop.shape[1] * 2, crop.shape[0] * 2), Image.NEAREST).save(d / "fit_viz.png")
    print(lid, {k: out[k] for k in ("yaw", "scale", "stretchY", "iou", "precision", "recall")}, flush=True)
    return out


def reference_frame(layers: list[str]) -> Image.Image:
    lays = SC.layers()
    bg = SC.background_rgba()
    for L in sorted((lays[l] for l in layers), key=lambda L: L.get("z", 0)):
        bg.alpha_composite(SC.sprite(L), (int(L["x"]), int(L["y"])))
    frame = Image.new("RGB", (W, H), (0, 0, 0))
    frame.paste(bg.convert("RGB").resize((TW, TH), Image.LANCZOS), (0, 0))
    return frame


def placed(lid: str, sc=None) -> tuple[dict, dict, np.ndarray, np.ndarray]:
    """(model, placement, world vertices, world vertex normals)."""
    d = OUTD / lid
    model = load_meshy(d / "model.glb")
    pl = json.loads((d / "placement.json").read_text(encoding="utf-8"))
    if pl["modelSha256"] != model["sha256"]:
        raise SystemExit(f"{lid}: placement.json was fitted to another model.glb; run fit")
    V = model["V"]
    lo, hi = V.min(0), V.max(0)
    v0 = V - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    k = float(pl["stretchY"])
    R = FM.yaw_matrix(pl["yaw"])
    Pw = ((v0 * np.array([1.0, k, 1.0])) @ R.T) * pl["scale"] + np.asarray(pl["position"])
    Nw = (model["N"] * np.array([1.0, 1.0 / k, 1.0])) @ R.T
    Nw /= np.linalg.norm(Nw, axis=1, keepdims=True) + 1e-12
    return model, pl, Pw, Nw


# ------------------------------------------------------------------------------------------------ stage
def rest_silhouette(sc, P, F) -> np.ndarray:
    px, py, _ = T.project(sc.cam, P)
    q = np.round(np.stack([px, py], 1)[F] * 4).astype(np.int32)
    m = np.zeros((H, W), np.uint8)
    for t in range(0, len(q), 20000):
        cv2.fillPoly(m, list(q[t:t + 20000]), 1, lineType=cv2.LINE_8, shift=2)
    cv2.polylines(m, list(q), True, 1, thickness=1, lineType=cv2.LINE_8, shift=2)
    return m.astype(bool)


def seed_stage() -> Path:
    import stronghold_full3d_scene as S
    return S.STAGE


def surgery(sc, lid: str, L: dict, model: dict, Pw, Nw):
    """CUT rules on the placed layer: (P, N, uv, F, report)."""
    spr = frame_mask(L, CB.sprite_mask(L)).astype(np.uint8)
    k = 2 * MS.OFF_SPRITE_DILATE + 1
    spr = cv2.dilate(spr, np.ones((k, k), np.uint8)).astype(bool)
    F = model["F"]
    px, py, _ = T.project(sc.cam, Pw)

    def on(x, y):
        x, y = np.round(x).astype(int), np.round(y).astype(int)
        ok = (x >= 0) & (y >= 0) & (x < spr.shape[1]) & (y < spr.shape[0])
        r = np.zeros(x.shape, bool)
        r[ok] = spr[y[ok], x[ok]]
        return r
    inside = on(px[F].mean(1), py[F].mean(1))
    vin = on(px, py)
    inside_all = vin[F].all(1)
    uv = model["uv"]
    g = {"v": model["V"], "f": F, "uv": np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1), "tex": np.asarray(model["tex"])}
    return MS.cut_parts(Pw, Nw, uv, F, g, {"cut": CUT.get(lid, CUT_DEFAULT)}, {"inside": inside, "insideAll": inside_all})


def coexist(a: str, b: str) -> bool:
    """Both layers are built in some state of the HoMM3 building tree (town_full3d_build_states, as recipe v2
    measures). The profile's three STATES left out every layer built only in a min_ state (Cove zs_v1, 2026-10-02:
    tbcvsa2p over the hall, tbcvsor1 over the mage guild; town_full3d_recipe.paint_order_cut)."""
    global _STATES
    if _STATES is None:
        import town_full3d_build_states as BS
        _STATES = list(BS.enumerate_states(SC.FP, SC.layer_map()).values())
    return any(a in st and b in st for st in _STATES)


_STATES = None


def order_cut(sc, prep: dict, meshed: list[str]) -> None:
    """Painting order at rest (paintOrder). HoMM3 draws the layers in list order (z, then order), so a layer drawn
    later covers an earlier one on its own sprite. A Meshy body placed at its own contact depth can stand in front of
    a later layer in 3D (cv_t2 stage 3: the hall's deck over the tavern's upper storey at rest). For every Meshy layer
    A and every later-drawn layer B that shares a state with A, the faces of A whose rest centroid is on B's sprite
    and nearer the camera than B's own surface there (by PAINT_ORDER_TOL) are dropped. B's surface is its placed,
    cut Meshy body, or the staged seed body for a relief layer."""
    import stronghold_full3d_scene as S
    import town_full3d_t2_paint as PF
    order = list(SC.layers())
    depth: dict = {}

    def b_depth(b):
        if b not in depth:
            if b in prep:
                P, F = prep[b]["P"], prep[b]["F"]
            else:
                mb = S.STAGE / (S.PREFIX + b) / f"Mesh_Body_{b}.bytes"
                if not mb.is_file():
                    depth[b] = None
                    return None
                v, _n, _uv, subs = S.read_bin(mb)
                P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
                F = np.concatenate(subs).reshape(-1, 3)
            if not len(F):
                depth[b] = None
                return None
            z, _ = PF.zbuffer(sc.cam, P, F)
            z = z.reshape(H, PF.SUPER, W, PF.SUPER).max(axis=(1, 3))    # frame px: B covers the whole px
            LB = SC.layers()[b]
            z[~frame_mask(LB, CB.sprite_mask(LB))] = np.inf
            depth[b] = z
        return depth[b]

    for a in meshed:
        d = prep[a]
        P, F = d["P"], d["F"]
        px, py, zc = T.project(sc.cam, P)
        cx = np.round(px[F].mean(1)).astype(int)
        cy = np.round(py[F].mean(1)).astype(int)
        zf = zc[F].mean(1)
        ok = (cx >= 0) & (cy >= 0) & (cx < W) & (cy < H)
        drop = np.zeros(len(F), bool)
        over = {}
        for b in order[order.index(a) + 1:]:
            if not coexist(a, b):
                continue
            z = b_depth(b)
            if z is None:
                continue
            zb = np.full(len(F), np.inf)
            zb[ok] = z[cy[ok], cx[ok]]
            sel = np.isfinite(zb) & (zf < zb * (1 - PAINT_ORDER_TOL))
            if (sel & ~drop).any():
                over[b] = int((sel & ~drop).sum())
            drop |= sel
        rep = {"rule": "paintOrder", "droppedTris": int(drop.sum()), "over": over}
        d["cut"] = (d["cut"] or []) + [rep]
        if drop.any():
            keep = ~drop
            used = np.unique(F[keep])
            remap = np.full(len(P), -1, np.int64)
            remap[used] = np.arange(len(used))
            d["P"], d["N"], d["uv"], d["F"] = P[used], d["N"][used], d["uv"][used], remap[F[keep]]


def prepare(sc, lid: str) -> dict:
    L = SC.layers()[lid]
    model, pl, Pw, Nw = placed(lid)
    P, N, uv, F, cut = surgery(sc, lid, L, model, Pw, Nw)
    return {"model": model, "pl": pl, "P": P, "N": N, "uv": uv, "F": F, "cut": cut}


def stage_layer(sc, lid: str, seed_bins: dict, d: dict) -> dict:
    """Painted-front bake (town_full3d_t2_paint, coordinator rule 2026-09-29), then the seed residual."""
    import stronghold_full3d_scene as S
    import stronghold_full3d_ground as G
    import town_full3d_t2_paint as PF
    L = SC.layers()[lid]
    model, pl, Pw, Nw, uv0, cut = d["model"], d["pl"], d["P"], d["N"], d["uv"], d["cut"]
    F = PF.outward(Pw, Nw, d["F"])
    P, n, uv, f, srep = PF.subdivide_screen(sc.cam, Pw, Nw, uv0, F)
    tex_lin = G.SC_srgb_to_lin(np.asarray(model["tex"]).astype(np.float32) / 255)
    brep = PF.painted_split(sc, lid, L, CB.sprite_mask(L), P, n, f, uv, tex_lin, f"Mesh_Body_{lid}",
                            f"Mesh_Body_{lid}_hull", meshy_max=HULL_MAX)
    brep["subdivide"] = srep
    prefab = S.PREFIX + lid
    pieces = {k: {"name": nm} for k, nm in (("front", f"Mesh_Body_{lid}"), ("hull", f"Mesh_Body_{lid}_hull"))
              if brep["meshyTris" if k == "hull" else "frontTris"]}
    _, _, zc = T.project(sc.cam, Pw)
    # ---- residual: the seed's depth solid where the Meshy silhouette leaves sprite pixels uncovered
    import stronghold_full3d_buildings as BL
    sil = rest_silhouette(sc, Pw, F)
    grown = cv2.dilate(sil.astype(np.uint8), np.ones((2 * RESIDUAL_DILATE + 1,) * 2, np.uint8)).astype(bool)
    spr = frame_mask(L, BL.native_mask(L))
    resid = spr & ~grown
    resid[TH:, :] = False
    resid[:, TW:] = False
    rrep = {"uncoveredPx": int(resid.sum()), "spritePx": int(spr.sum())}
    if resid.sum() >= RESIDUAL_MIN_PX and lid in seed_bins:
        v, n, uvs, tris, img = seed_bins[lid]
        P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
        nw = n.astype(np.float64) @ sc.C.T
        rx, ry, _ = T.project(sc.cam, P)
        cx = np.clip(np.round(rx[tris].mean(1)).astype(int), 0, W - 1)
        cy = np.clip(np.round(ry[tris].mean(1)).astype(int), 0, H - 1)
        on = resid[cy, cx]
        keep = on & PF.facing_rest(sc.cam, P, tris)
        rrep["grazingDropped"] = int((on & ~keep).sum())
        if keep.any():
            used = np.unique(tris[keep])
            remap = np.full(len(P), -1)
            remap[used] = np.arange(len(used))
            pieces["rest"] = sc.add_bin(prefab, f"Mesh_Body_{lid}_rest", *double_side(
                P[used], nw[used], uvs[used], remap[tris[keep]]), img, srgb=True)
            rrep["tris"] = int(keep.sum())
    covered = sil & spr
    rep = {"kind": "building", "method": "meshy_t2", "texelsPerPx": brep["texelsPerPx"],
           "tris": int(2 * (brep["frontTris"] + brep["meshyTris"] + rrep.get("tris", 0))), "doubleSided": True,
           "frontTris": brep["frontTris"], "hullTris": brep["meshyTris"], "sideQuads": 0,
           "texSize": brep["paintTex"], "delitClippedShare": brep["delitClippedShare"], "bake": brep,
           "fit": {k2: round(pl[k2], 4) if isinstance(pl[k2], float) else pl[k2]
                   for k2 in ("yaw", "scale", "stretchY", "iou", "precision", "recall")},
           "restCoverOfSprite": round(float(covered.sum() / max(spr.sum(), 1)), 4),
           "silhouetteOutsideSpritePx": int((sil & ~frame_mask(L, CB.sprite_mask(L)))[:TH, :TW].sum()),
           "residual": rrep, "cut": cut, "modelSha256": model["sha256"], "footZm": round(float(np.median(zc)), 1),
           "pieces": sorted(p["name"] for p in pieces.values())}
    return rep


def load_seed_bins(seed_stage_dir: Path, lids) -> dict:
    import stronghold_full3d_scene as S
    out = {}
    for lid in lids:
        mb = seed_stage_dir / (S.PREFIX + lid) / f"Mesh_Body_{lid}.bytes"
        if not mb.is_file():
            continue
        v, n, uv, subs = S.read_bin(mb)
        img = np.asarray(Image.open(mb.with_name(mb.stem + "_albedo.png")).convert("RGB"))
        out[lid] = (v, n, uv, np.concatenate(subs).reshape(-1, 3), img)
    return out


def stage(only=None) -> int:
    import stronghold_full3d_scene as S
    if not S.CANDIDATE:
        raise SystemExit("stage: set TOWN_FULL3D_CANDIDATE (seeded by candidate-init --seed-from cv_v11)")
    lids = [l for l in CB.MESH_LAYERS if (not only or l in only)]
    lids = [l for l in lids if (OUTD / l / "placement.json").is_file() and l not in STAGE_SKIP]
    seedd = S.STAGE  # the candidate's own staged bins (seeded from cv_v11); cached once as the residual source
    cache = S.CAND / "work" / "seed_bodies"
    cache.mkdir(parents=True, exist_ok=True)
    for lid in lids:
        src = seedd / (S.PREFIX + lid)
        dst = cache / (S.PREFIX + lid)
        if not dst.is_dir():
            dst.mkdir()
            for f in (f"Mesh_Body_{lid}.bytes", f"Mesh_Body_{lid}_albedo.png"):
                shutil.copy2(src / f, dst / f)
    seed_bins = load_seed_bins(cache, lids)
    sc = S.Scene()
    # every staged Meshy layer is prepared (placement + surgery) even under --only: it can be a paint-order occluder
    allm = [l for l in CB.MESH_LAYERS if (OUTD / l / "placement.json").is_file() and l not in STAGE_SKIP]
    prep = {l: prepare(sc, l) for l in allm}
    order_cut(sc, prep, lids)
    rep_all = {}
    for lid in lids:
        rep_all[lid] = stage_layer(sc, lid, seed_bins, prep[lid])
        print(lid, {kk: rep_all[lid][kk] for kk in ("frontTris", "hullTris", "restCoverOfSprite", "residual")},
              flush=True)
    # rows: drop a stale _rest / _hull row of a restaged layer that no longer emits it
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    for lid in lids:
        pf = S.PREFIX + lid
        emitted = {b["name"] for b in sc.pieces.get(pf, [])}
        rows[pf]["bins"] = [b for b in rows[pf]["bins"]
                            if not (b["name"].startswith(f"Mesh_Body_{lid}") and b["name"] not in emitted)]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    S.save_rows(sc)
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["buildings"].update(rep_all)
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    wf = S.WORK / "closing_walls.npz"
    if wf.is_file():
        edges = {kk: vv for kk, vv in np.load(wf).items() if kk not in lids}
        np.savez(wf, **edges)
    S.write_catalog(sc, carry="fresh")
    catalog_block()
    S.load_staged_preview(sc)
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    print(S.preview(sc, S.WORK / "preview", cams))
    st = S.see_through_report(sc)
    (S.WORK / "see_through.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["seeThrough"] = {kk: st[kk] for kk in ("metric", "totalPx", "mode", "baseline", "worse")}
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"seeThrough": rep["seeThrough"]}))
    S.cull_gate_or_exit(st)
    return 0


def catalog_block() -> None:
    import stronghold_full3d_scene as S
    cat_p = S.OUT / "catalog.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))["buildings"]
    meshed = {l: r for l, r in rep.items() if r.get("method") == "meshy_t2"}
    cat["meshyBuildings"] = {
        "layers": sorted(meshed), "skipped": CB.SKIP, "meshedNotStaged": STAGE_SKIP,
        "surgery": {"default": CUT_DEFAULT, "perLayer": CUT, "rules": "tools/homm3_town_scene_meshes/t2_mesh_surgery.py"},
        "credits": CB.spend()["spent"],
        "model": "Meshy image-to-3d meshy-t2 smart-topology textured (no texture prompt)",
        "texture": "painted front (town_full3d_t2_paint): faces seen at rest take the sprite by screen position, de-lit "
                   "through the smooth view normal; the Meshy texture elsewhere; the seed depth solid on sprite "
                   "pixels the mesh leaves",
        "registration": "tools/homm3_town_scene_meshes/fit_mesh_to_sprite.py Fitter under the rest camera",
        "proofTier": "generated artifact"}
    cat_p.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage"])
    ap.add_argument("--only", default="")
    ap.add_argument("--faction", default="cove")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.cmd == "fit":
        import stronghold_full3d_scene as S
        sc = S.Scene()
        rd = T.rect_depth(sc.cam)
        for lid in CB.MESH_LAYERS:
            if only and lid not in only:
                continue
            if not (OUTD / lid / "model.glb").is_file():
                print(lid, "no model.glb", flush=True)
                continue
            fit_layer(sc, rd, lid)
        return 0
    return stage(only)


if __name__ == "__main__":
    raise SystemExit(main())
