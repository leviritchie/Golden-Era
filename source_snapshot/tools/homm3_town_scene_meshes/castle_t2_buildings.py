#!/usr/bin/env python3
"""Castle town scene: Meshy T2 building meshes in the full-3D lane (docs/homm3_castle_t2_town_buildings.md).

Brief: artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md (2026-09-29). Faction-scoped: the shared
stronghold_full3d_* / fit_mesh_to_sprite modules are imported, never edited. Generation (billed) is
artifacts/meshy_town_scene_meshes/homm3_castle/gen_castle_t2.py; this module only reads its GLBs.

    TOWN_FULL3D_CANDIDATE=t2_v1 python castle_t2_buildings.py fit   [--layer L ...]
    TOWN_FULL3D_CANDIDATE=t2_v1 python castle_t2_buildings.py stage [--layer L ...]
    TOWN_FULL3D_CANDIDATE=t2_v1 python castle_t2_buildings.py sheet --before wall_v4

fit    registers each mesh to its sprite under the native rest camera (fit_mesh_to_sprite.Fitter: yaw, uniform scale,
       ground-contact pixel on the calibrated terrain depth; F0.5 of the projected silhouette vs the layer's body mask).
       Frame px outside the painted rect (x >= TW or y >= TH) are ignored by the objective: a frame-cut building
       (the castle levels and the mage guild at the right edge, the tavern at the bottom) may continue past the cut
       instead of shrinking to it. An optional vertical-stretch pass is kept only when it raises F0.5 by > 0.005.
stage  per meshed layer the seed's Mesh_Body_<layer> is replaced by up to three lit bins (Fx_ pieces are kept):
       Mesh_Body_<layer>      triangles the rest camera sees (either side, any rest px,
                              inside the painted rect): the painting's own texels by rest-camera projection
                              (background + this layer's static plate, x1.8, TEX_K texels / px), de-lit by the Hex/Lit
                              irradiance of the mesh's interpolated normals, so the rest frame is the painting. A
                              projected texel outside the sprite (the fit's overshoot) takes the sprite's interior
                              colour pushed outward (stronghold_full3d_solids.back_fill) instead of the sky / meadow
                              behind it, so the building never carries background colour when the camera moves.
       Mesh_BodyM_<layer>     every other triangle: the Meshy texture, per-channel gain matched (linear medians) to
                              the de-lit painting on the projected triangles.
       Mesh_BodyRest_<layer>  the seed's solid FRONT triangles over sprite px the mesh does not cover at rest (painted
                              skirts: the castle's lake, rocks, shadows; components >= RESID_MIN_PX), with the seed's
                              own texture, so no px of the painting disappears at rest.
Seed = the installed candidate wall_v4 (read only). Proof tier: generated artifact until bundled and rendered.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "castle")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
from fit_mesh_to_sprite import yaw_matrix  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402  (the one T2 bake: rest_geometry_split)
from t2_rest_geometry import RectFitter  # noqa: E402

if SC.FP.FRACTION != "homm3_castle":
    raise SystemExit(f"castle_t2_buildings: TOWN_FULL3D_FACTION resolves to {SC.FP.FRACTION}, not homm3_castle")

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
MESHY = SC.ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_castle"
sys.path.insert(0, str(MESHY))
import gen_castle_t2 as GEN  # noqa: E402

SEED_NAME = "wall_v4"          # the installed candidate (bundle sha256 dbd35b26ce60824f...)
SEED = SC.DATA / "candidates" / SEED_NAME
TEX_K = 2                      # painted texels per 1080p px (the relief lane's BUILD_SCALE)

LIGHT_FLOOR = 0.35             # de-light gain floor (share of the building's median irradiance)
GAIN_CLAMP = (0.5, 2.0)
RESID_MIN_PX = 20
MESHY_TEX_MAX = 2048
SUBDIV_PX = 10.0               # max rest-screen edge (frame px) of a visible triangle: bounds the occluder paint a partly hidden one carries
YAW_PICK: dict[str, int] = {     # layer -> yaw quadrant centre chosen by eye (see fit()); filled from the panels
    "tbcshall": 90,            # painted long roof slope toward the camera, gable at the left: 102
    "tbcsholy": 180,           # the statue faces the camera (270 shows only the shield edge-on)
    "tbcshal2": 180,           # banners on the long side toward the camera
    "tbcshal3": 270,           # white timber facade with the banners and both gables toward the camera
    "tbcscstl": 270,           # keep and gate toward the camera (0 shows the inner colonnade); tbcscas2 inherits
    "tbcscas3": 180,           # bannered keep front (0 shows the bare back wall; normal_err chose it)
    "tbcsmage": 180,           # doorway front with the low wall at the left (0 shows the round-window back)
    "tbcstvrn": 180,           # timbered gable and stair toward the camera (normal_err chose 90: the long flank)
    "tbcsmag4": 180,           # door centred between the two orbs (normal_err chose 0: one orb, side view)
    "tbcssilo": 180,           # porch toward the camera (normal_err chose 0: porch hidden behind)
    "tbcsdw_0": 0,
    "tbcsdw_3": 180,           # gate tower and curtain wall front-on (90 turns the wall's back to the camera)
    "tbcsdw_2_2": 180,         # gate arch toward the camera
             # door and window front toward the camera (normal_err chose 312: blank flank)
}
YAW_FBETA_TIE = 0.03       # quadrant fits this close to the best F0.5 are separated by normal_err (see fit())
# layers that reuse another layer's mesh (gen_castle_t2.PLAN says why); the projection carries each layer's own px
REUSE = {"tbcscas2": "tbcscstl", "tbcshrd2": "tbcsdw_2_2"}
GLB = {"tbcstvrn": MESHY / "tbcstvrn" / "t2_pricecheck" / "model.glb",
       # keep regen 2026-10-04 (pass castle_keep_20261004): input = the original sprite with its right corner tower
       # closed by a mirrored px copy of the left one (t2_b1/complete_tower.py; no concept step); Meshy's sand base
       # plate (faces entirely within the bottom 0.010 model units) stripped -> model_noplate.glb. The t2_a1 fit is
       # kept in tbcscas3/fit_t2_a1/.
       "tbcscas3": MESHY / "tbcscas3" / "t2_b1" / "model_noplate.glb"}


def meshed_layers() -> list[str]:
    return [l for l, p in GEN.PLAN.items() if p in ("mesh", "concept+mesh")] + ["tbcstvrn"] + list(REUSE)


def glb_path(lid: str) -> Path:
    src = REUSE.get(lid, lid)
    return GLB.get(src, MESHY / src / "t2_a1" / "model.glb")


def out_dir(lid: str) -> Path:
    d = MESHY / lid / "fit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_glb(path: Path) -> dict:
    """GLB -> Unity / painting-world convention (x negated, as glTFast imports), winding restored."""
    import trimesh
    m = trimesh.load(str(path), force="mesh", process=False)
    V = np.asarray(m.vertices, np.float64).copy()
    V[:, 0] *= -1.0
    F = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]
    uv = np.asarray(m.visual.uv, np.float64)
    N = np.asarray(m.vertex_normals, np.float64).copy()   # the GLB's own (authored hard-edge) normals
    N[:, 0] *= -1.0
    tex = m.visual.material.baseColorTexture
    return {"V": V, "F": F, "uv": uv, "N": N, "tex": np.asarray(tex.convert("RGB"))}


def outward_sign(V, F) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def body_mask_native(lid: str) -> np.ndarray:
    """The layer's building body (sprite px): the lane's native mask (alpha minus shadow leftovers and px equal to
    the painting) cut by gen_castle_t2.BODY (the lake under the castle, the sky round the lighthouse)."""
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    rgba = np.asarray(SC.sprite(L))
    return BL.native_mask(L) & GEN.body_mask(lid, rgba)


def to_frame(lid: str, m: np.ndarray) -> np.ndarray:
    L = SC.layers()[lid]
    s = cv2.resize(m.astype(np.float32), (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)),
                   interpolation=cv2.INTER_LINEAR) > 0.5
    out = np.zeros((H, W), bool)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    hh, ww = min(s.shape[0], H - y0), min(s.shape[1], W - x0)
    out[y0:y0 + hh, x0:x0 + ww] = s[:hh, :ww]
    return out


_ZS = None


def terrain_z() -> np.ndarray:
    """Frame forward depth of the terrain (sky filled by the nearest ground); cached beside the Meshy outputs."""
    global _ZS
    if _ZS is not None:
        return _ZS
    p = MESHY / "_work" / "terrain_z.npy"
    if p.is_file():
        _ZS = np.load(p)
        return _ZS
    # the rect's calibrated depth + the lane's cached extension raymarch (work/frame_depth.npz, written by the terrain
    # stage of the installed candidate's world field); the building fit needs ground depth, not the terrain mesh
    rd = T.rect_depth(T.camera())
    ys, xs = np.mgrid[0:H, 0:W]
    ext = (xs >= TW) | (ys >= TH)
    with np.load(SC.DATA / "work" / "frame_depth.npz") as d:
        zext = d["zext"]
    zs = np.full((H, W), np.nan)
    zs[:TH, :TW] = rd["zc"]
    zs[ext] = zext
    from scipy.ndimage import distance_transform_edt
    ok = np.isfinite(zs)
    _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
    _ZS = zs[iy, ix]
    np.save(p, _ZS)
    return _ZS


def rest_cam() -> dict:
    c = T.camera()
    return {k: (np.asarray(v, np.float64) if k in ("pos", "fwd", "right", "up") else v) for k, v in c.items()}


_SC = {}


def normal_err(lid: str, fz, g, c: dict, tgt: np.ndarray) -> float:
    """Mean (1 - cos) between the placed model's rest normals and the seed body's (wall_v4: surfaces derived from the
    painting's own depth), over the sprite px both cover. Colour does not decide the yaw (at rest the painting is
    projected anyway, and Meshy's chroma separated the hall's quadrants by < 0.02); what the yaw decides is whether
    the model's walls and roof planes lie where the painting's do - the first hall fit put a gable where the painting
    has the long roof slope."""
    import stronghold_full3d_scene as S
    import town_full3d_houses as HS
    if "sc" not in _SC:
        _SC["sc"] = S.Scene()
    sc = _SC["sc"]
    if lid not in _SC:
        P0, n0, _uv0, t0, _a = seed_bin(lid, sc)
        sid, snb = HS.rest_buffers(sc, [(P0, n0, t0, 0)], W, H)
        _SC[lid] = (sid >= 0, snb)
    shave, snb = _SC[lid]
    _, Vw = fz.transform(c["yaw"], c["scale"], *c["contactPx"], c["stretchY"])
    Fm = g["F"]
    fn = np.cross(Vw[Fm[:, 1]] - Vw[Fm[:, 0]], Vw[Fm[:, 2]] - Vw[Fm[:, 0]])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
    # flat per-face normals, flipped toward the camera (either side of an open part is what the painting shows)
    to_cam = np.asarray(sc.cam["pos"]) - Vw[Fm].mean(1)
    fn = np.where(((fn * to_cam).sum(-1) < 0)[:, None], -fn, fn)
    Vf = Vw[Fm].reshape(-1, 3)
    idb, mnb = HS.rest_buffers(sc, [(Vf, np.repeat(fn, 3, 0), np.arange(len(Vf)).reshape(-1, 3), 0)], W, H)
    m = (idb >= 0) & shave & tgt
    if m.sum() < 50:
        return float("inf")
    a = mnb[m] / (np.linalg.norm(mnb[m], axis=1, keepdims=True) + 1e-9)
    b = snb[m] / (np.linalg.norm(snb[m], axis=1, keepdims=True) + 1e-9)
    return float((1 - (a * b).sum(1)).mean())


def fit(lid: str) -> dict:
    zs = terrain_z()
    g = load_glb(glb_path(lid))
    tgt = to_frame(lid, body_mask_native(lid))
    fz = RectFitter(rest_cam(), zs, (W, H), tgt.astype(np.uint8), g["V"], g["F"], down=2)
    ys, xs = np.nonzero(tgt)
    t0 = time.time()
    # Yaw. T2 re-poses the model (the hall's painted long side came back as its gable front), so neither the camera
    # ray nor the silhouette settles the facing: the silhouette is nearly symmetric under 180 deg (first hall fit: yaw
    # 33, gable on the wrong side) and a window about the camera-facing yaw pinned fits to its edges (hall 202 at
    # the +52 edge, hal2 101 at the -49 edge). So each quadrant gets its own silhouette fit, and among those within
    # YAW_FBETA_TIE of the best F0.5 the one whose rest normals best agree with the seed's painting-derived surfaces wins (normal_err).
    bbox = (xs.min(), ys.min(), xs.max(), ys.max())
    # normal_err is a weak separator (cstl and cas2, one mesh on one silhouette, split 0.32 / 0.34 against 0.31 /
    # 0.34), so a quadrant chosen by eye from _work/yaw_<layer>.png (textured model at rest and the three sweeps
    # beside the painting) overrides it: YAW_PICK. A reused mesh takes its source's pick.
    pick = YAW_PICK.get(lid, YAW_PICK.get(REUSE.get(lid, "")))
    quads = (0, 90, 180, 270) if pick is None else (pick,)
    cands = [fz.fit(bbox, yaws=[q + a for a in (-30, -15, 0, 15, 30)]) for q in quads]
    top = max(c["fbeta"] for c in cands)
    for c in cands:
        c["normalErr"] = normal_err(lid, fz, g, c, tgt) if c["fbeta"] >= top - YAW_FBETA_TIE else None
    base = min((c for c in cands if c["normalErr"] is not None), key=lambda c: c["normalErr"])
    if pick is not None:
        base["yawPick"] = f"quadrant {pick} by visual review (_work/yaw_{REUSE.get(lid, lid)}.png)"
    best = base
    try:
        st = fz.refine_stretch(base, lo=0.8, hi=1.25, top_weight=0.5)
        if st["fbeta"] > base["fbeta"] + 0.005:
            best = st
    except Exception as e:  # noqa: BLE001 - recorded; the base fit stands
        print(lid, "stretch pass failed:", e)
    out = {k: v for k, v in best.items() if k != "silhouette"}
    out["base"] = {k: base[k] for k in ("fbeta", "iou", "precision", "recall")}
    out["yawPick"] = base.get("yawPick")
    out["yawCandidates"] = [{"yaw": round(c["yaw"], 1), "fbeta": round(c["fbeta"], 4),
                              "normalErr": None if c["normalErr"] is None else round(c["normalErr"], 4)} for c in cands]
    out["meshFrom"] = REUSE.get(lid, lid)
    out["glb"] = glb_path(lid).relative_to(SC.ROOT).as_posix()
    out["seconds"] = round(time.time() - t0, 1)
    d = out_dir(lid)
    (d / "fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    sil = cv2.resize(best["silhouette"].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:TH, :TW] = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS)) // 2
    frame[tgt] = (frame[tgt] * 0.5 + np.array([0, 160, 0])).astype(np.uint8)
    frame[sil] = (frame[sil] * 0.6 + np.array([140, 0, 0])).astype(np.uint8)
    frame[:, TW:TW + 1] = (255, 255, 0)
    y0, y1 = max(0, ys.min() - 60), min(H, ys.max() + 60)
    x0, x1 = max(0, xs.min() - 60), min(W, xs.max() + 160)
    Image.fromarray(frame[y0:y1, x0:x1]).save(d / "fit_overlay.png")
    print(lid, {k: round(out[k], 3) for k in ("iou", "precision", "recall", "fbeta", "stretchY", "yaw")}, flush=True)
    return out


def placed(lid: str) -> tuple[dict, dict]:
    g = load_glb(glb_path(lid))
    f = json.loads((out_dir(lid) / "fit.json").read_text(encoding="utf-8"))
    V = g["V"]
    lo, hi = V.min(0), V.max(0)
    v0 = V - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    R = yaw_matrix(f["yaw"])
    Vw = ((v0 * np.array([1.0, f["stretchY"], 1.0])) @ R.T) * f["scale"] + np.asarray(f["position"])
    Nw = (g["N"] * np.array([1.0, 1.0 / f["stretchY"], 1.0])) @ R.T
    Nw /= np.linalg.norm(Nw, axis=1, keepdims=True) + 1e-12
    F = g["F"]
    if outward_sign(Vw, F) < 0:
        F = F[:, [0, 2, 1]]
    g["V"], g["F"], g["N"] = Vw, F, Nw
    return g, f


def vertex_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], fn)
    fl = np.linalg.norm(fn, axis=1, keepdims=True)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    return vn, fn / (fl + 1e-12)


def seed_bin(lid: str, sc) -> tuple:
    """The seed's Mesh_Body_<layer>: painting-world P, n, uv, tris and its albedo png."""
    import stronghold_full3d_scene as S
    d = SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v, n, uv, subs = S.read_bin(d / f"Mesh_Body_{lid}.bytes")
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    nw = n.astype(np.float64) @ sc.C.T
    return P, nw, uv, np.concatenate(subs), d / f"Mesh_Body_{lid}_albedo.png"


def stage_layer(sc, lid: str) -> dict:
    g, f = placed(lid)
    return TP.rest_geometry_split(sc, lid, g, f, seed_bin, to_frame, tex_k=TEX_K, subdiv_px=SUBDIV_PX,
                                  light_floor=LIGHT_FLOOR, gain_clamp=GAIN_CLAMP, meshy_tex_max=MESHY_TEX_MAX,
                                  resid_min_px=RESID_MIN_PX)


def stage(layers: list[str]) -> int:
    import stronghold_full3d_scene as S
    if not S.CANDIDATE or S.CANDIDATE == SEED_NAME:
        raise SystemExit(f"set TOWN_FULL3D_CANDIDATE to the T2 candidate (never the {SEED_NAME} seed)")
    sc = S.Scene()
    rp = S.WORK / "stage_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    t2 = report.setdefault("t2Buildings", {})
    for lid in layers:
        t0 = time.time()
        rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
        pk = S.PREFIX + lid
        # every Mesh_Body* bin of the layer is re-emitted (a layer with no painted triangles keeps no seed body)
        rows[pk]["bins"] = [b for b in rows[pk]["bins"] if not b["name"].startswith("Mesh_Body")]
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        sc.pieces = {}
        r = stage_layer(sc, lid)
        S.save_rows(sc)
        r["seconds"] = round(time.time() - t0, 1)
        t2[lid] = r
        b = report["buildings"][lid]
        b.update({"method": "meshy_t2", "texelsPerPx": r["texelsPerPx"], "tris": r["tris"] + r["residualTris"],
                  "frontTris": r["frontTris"]})
        rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(lid, json.dumps(r), flush=True)
    S.write_catalog(sc, carry="fresh")
    return 0


def preview(state: str, poses: list[str], only: list[str] | None) -> int:
    """Offline moderngl preview (the lane's own renderer) of the candidate's staged environment + one build state's
    layers at the named proof poses -> artifacts/meshy_town_scene_meshes/homm3_castle/_work/preview/<cand>/."""
    import stronghold_full3d_scene as S
    sc = S.Scene()
    lays = only or S.STATES[state]
    S.load_staged_preview(sc, [S.PREFIX + "environment"] + [S.PREFIX + l for l in lays])
    cams = {"default": sc.cam}
    cams.update(S.pan_cams(sc))
    cams = {k: v for k, v in cams.items() if k in poses}
    out = MESHY / "_work" / "preview" / (S.CANDIDATE or "base")
    # the lane renderer draws both faces; Unity culls back faces (town_full3d_cull: a triangle survives when its
    # geometric normal (P1-P0)x(P2-P0) faces the camera, checked on the hall: 1830 / 0). The two-sided T2 bins
    # depth-tie with their reversed copies without culling, so each pose is rendered from the Unity-surviving set.
    allp = sc.preview
    for name, cam in cams.items():
        cp = np.asarray(cam["pos"], np.float64)
        keep = []
        for pc in allp:
            P, tris = pc[1].astype(np.float64), np.asarray(pc[4])
            if pc[6]:
                keep.append(pc)
                continue
            fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
            m = (fn * (cp - P[tris].mean(1))).sum(-1) > 0
            keep.append((*pc[:4], tris[m], *pc[5:]))
        sc.preview = keep
        print(S.preview(sc, out, {name: cam}))
    return 0


def top_layer_map(layers: list[str]) -> np.ndarray:
    """Frame-sized index of the full-state layer each rest px shows (-1: background), by positions.json z order."""
    lays = SC.layers()
    top = np.full((H, W), -1, np.int32)
    for i, lid in sorted(enumerate(layers), key=lambda t: lays[t[1]].get("z", 0)):
        m = to_frame(lid, np.asarray(SC.sprite(lays[lid]))[..., 3] > 8)
        top[m] = i
    top[TH:] = -1
    top[:, TW:] = -1
    return top


def rest_de(state: str) -> int:
    """Per layer: mean CIE76 dE between the rest render and the HoMM3 painting over the px where that layer is the
    topmost sprite, for the seed (SEED_NAME) and this candidate, both from this module's preview renders (the same
    renderer and culling). A layer whose T2 build loses at rest is a restore candidate."""
    import stronghold_full3d_scene as S
    from skimage.color import rgb2lab
    lays = S.STATES[state]
    ref = np.asarray(S.homm3_reference(lays)).astype(np.float32) / 255
    base = MESHY / "_work" / "preview"
    imgs = {}
    for c in (SEED_NAME, S.CANDIDATE):
        pth = base / c / "default.png"
        if not pth.is_file():
            raise SystemExit(f"rest-de: no preview {pth} (run preview with TOWN_FULL3D_CANDIDATE={c})")
        imgs[c] = rgb2lab(np.asarray(Image.open(pth).convert("RGB")).astype(np.float32) / 255)
    lr = rgb2lab(ref)
    top = top_layer_map(lays)
    t2 = set(json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8")).get("t2Buildings", {}))
    rows = []
    for i, lid in enumerate(lays):
        m = top == i
        if m.sum() < 30:
            continue
        d = {c: float(np.linalg.norm(imgs[c][m] - lr[m], axis=1).mean()) for c in imgs}
        rows.append({"layer": lid, "px": int(m.sum()), "t2Staged": lid in t2, "seedDE": round(d[SEED_NAME], 2),
                     "candDE": round(d[S.CANDIDATE], 2)})
    out = {"metric": "mean CIE76 dE, rest preview vs HoMM3 painting, px where the layer is topmost", "state": state,
           "seed": SEED_NAME, "candidate": S.CANDIDATE, "layers": rows}
    (MESHY / "_work" / f"rest_de_{S.CANDIDATE}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for r in rows:
        flag = "" if not r["t2Staged"] else ("  T2 wins" if r["candDE"] <= r["seedDE"] else "  T2 LOSES")
        print(f'{r["layer"]:12s} px {r["px"]:6d} seed {r["seedDE"]:6.2f} cand {r["candDE"]:6.2f}{flag}')
    return 0


def restore(layers: list[str]) -> int:
    """Put layers back to the seed build: the seed's prefab folder, rows entry and stage-report entry (the per-layer
    mix: a layer whose T2 build loses at rest keeps the installed relief)."""
    import stronghold_full3d_scene as S
    if not S.CANDIDATE or S.CANDIDATE == SEED_NAME:
        raise SystemExit("restore: set TOWN_FULL3D_CANDIDATE to the T2 candidate")
    seed = SC.DATA / "candidates" / SEED_NAME
    sstage = seed / "unity_project" / S.ASSET_ROOT
    srows = json.loads((sstage / "rows.json").read_text(encoding="utf-8"))
    srep = json.loads((seed / "work" / "stage_report.json").read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    import shutil
    for lid in layers:
        pk = S.PREFIX + lid
        dst = S.STAGE / pk
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(sstage / pk, dst)
        rows[pk] = srows[pk]
        rep["buildings"][lid] = srep["buildings"][lid]
        rep.get("t2Buildings", {}).pop(lid, None)
        rep.setdefault("t2Restored", {})[lid] = "seed relief kept: the T2 build lost at rest (rest_de)"
        print("restored", lid)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    S.write_catalog(S.Scene(), carry="fresh")
    return 0


SHEET = SC.ROOT / "artifacts" / "claude_takeover_20260927" / "review" / "homm3_castle_t2_buildings.png"
SHEET_POSES = ["default", "sweep_left", "sweep_right", "sweep_high"]
SHEET_ZOOMS = [("tbcshal3", "capitol"), ("tbcscas3", "castle"), ("tbcsmag4", "mage guild"), ("tbcstvrn", "tavern"),
               ("tbcmark", "marketplace"), ("tbcsblak", "blacksmith"), ("tbcsdw_2_2", "griffin bastion"),
               ("tbcsdw_5_2", "training grounds"), ("tbcsdw_4_2", "cathedral"), ("tbcsholy", "brotherhood")]


def sheet() -> int:
    """painting | before (the installed wall_v4) | after (this candidate): the editor renders of both
    (renders/full3d_full.png at rest, pan_sweep_*.png; the pan renders show the full state), plus rest zooms."""
    from PIL import ImageDraw
    import stronghold_full3d_scene as S
    cand = S.CAND
    if cand.name == SEED_NAME:
        raise SystemExit("sheet: set TOWN_FULL3D_CANDIDATE to the T2 candidate")

    def shot(root, pose):
        f = root / "renders" / ("full3d_full.png" if pose == "default" else f"pan_{pose}.png")
        if not f.is_file():
            raise SystemExit(f"sheet: missing render {f}")
        return Image.open(f).convert("RGB")
    paint = S.homm3_reference(SC.FP.STATES["full"])
    lays = SC.layers()
    sx = TW / SC.background_rgba().size[0]

    def box(lid):
        L = lays[lid]
        w, h = SC.sprite(L).size
        x0, y0 = L["x"] * sx - 24, L["y"] * sx - 24
        return (int(max(x0, 0)), int(max(y0, 0)), int(min((L["x"] + w) * sx + 24, TW)),
                int(min((L["y"] + h) * sx + 24, TH)))
    cw, ch, lab = 960, 540, 28
    cols = ["HoMM3 painting (full state)", f"before: installed {SEED_NAME}", f"after: {cand.name} (Meshy T2)"]
    rows = [(f"pose: {p}", [paint if p == "default" else None, shot(SEED, p), shot(cand, p)], True)
            for p in SHEET_POSES]
    rest = [paint, shot(SEED, "default"), shot(cand, "default")]
    rows += [(f"{lid} {nm} (rest)", [im.crop(box(lid)) for im in rest], False) for lid, nm in SHEET_ZOOMS]
    Ht = lab + len(rows) * (ch + lab)
    out = Image.new("RGB", (3 * cw, Ht), (24, 24, 24))
    d = ImageDraw.Draw(out)
    for i, c in enumerate(cols):
        d.text((i * cw + 8, 6), c, fill=(255, 255, 255))
    y = lab
    for title, ims, full in rows:
        d.text((8, y + 4), title, fill=(255, 220, 120))
        for i, im in enumerate(ims):
            if im is None:
                d.text((i * cw + 20, y + lab + 20), "(HoMM3 has one fixed view)", fill=(160, 160, 160))
                continue
            s = min(cw / im.width, ch / im.height)
            r = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
            out.paste(r, (i * cw + (cw - r.width) // 2, y + lab))
        y += ch + lab
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    out.save(SHEET)
    print(SHEET)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "preview", "rest-de", "restore", "sheet"])
    ap.add_argument("--state", default="full")
    ap.add_argument("--poses", default="default,sweep_left,sweep_right,sweep_high")
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--faction", default="castle")
    a = ap.parse_args()
    if a.cmd == "preview":
        return preview(a.state, a.poses.split(","), a.layer or None)
    if a.cmd == "sheet":
        return sheet()
    if a.cmd == "rest-de":
        return rest_de(a.state)
    if a.cmd == "restore":
        if not a.layer:
            raise SystemExit("restore: name the layers (--layer L ...)")
        return restore(a.layer)
    layers = a.layer or meshed_layers()
    if a.cmd == "fit":
        for lid in layers:
            fit(lid)
        return 0
    return stage(layers)


if __name__ == "__main__":
    raise SystemExit(main())
