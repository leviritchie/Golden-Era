#!/usr/bin/env python3
"""Tower: stage the Meshy T2 building meshes (tower_t2_meshy.py) into a full-3D candidate (docs/homm3_tower_t2_town_buildings.md).

    TOWN_FULL3D_CANDIDATE=tw_t2 python tools/homm3_town_scene_meshes/tower_t2_stage.py fit   [--layer L ...]
    TOWN_FULL3D_CANDIDATE=tw_t2 python tools/homm3_town_scene_meshes/tower_t2_stage.py stage [--layer L ...]

The candidate is seeded from the installed tw_v4 (`stronghold_full3d_scene.py candidate-init --faction tower
--seed-from tw_v4`); terrain, sky, periphery, near field and effects stay the seed's bins byte for byte, and the shared
stronghold_full3d_* / town_full3d_* modules are only imported (11 factions rebuild in parallel).

fit    register each mesh to its HoMM3 sprite under the rest camera (t2_rest_geometry.RectFitter: scale and ground-contact
       pixel on the calibrated terrain's frame depth, F0.5 of the silhouette against the lane's native_mask inside the
       painted rect). Yaw: t2_rest_geometry.quadrant_fit over the full circle (Meshy re-poses buildings, so the facing
       is a quadrant choice: YAW_PICK by eye from _work/yaw_<layer>.png, else the best coarse F0.5), refined +-12 deg,
       then the vertical-stretch pass (kept only when its F0.5 is higher). A profile floatZm layer (the Skyship) is
       fitted at that depth instead of the terrain. Writes <meshy dir>/<layer>/fit_quadrants.json, fit.json and
       fit_overlay.png.
yaw-panel  the per-quadrant review panels (_work/yaw_<layer>.png).
stage  per meshed layer: the fitted mesh's rest silhouette is snapped onto the sprite mask by a smooth image-plane
       field at each vertex's own camera depth (silhouette_warp), then town_full3d_t2_paint.rest_geometry_split (the
       Castle method) replaces every Mesh_Body* bin of the layer (Fx_ pieces are kept):
       Mesh_Body_<layer>     rest-visible triangles (subdivided to <= SUBDIV_PX, clipped at the painted rect): the
                             painting by rest-camera projection, de-lit by the seed's painting-derived normals.
       Mesh_BodyM_<layer>    every other triangle: the Meshy texture, per-channel gain matched. Hidden at rest.
       Mesh_BodyRest_<layer> the seed's front triangles over sprite px the mesh does not cover at rest.
       All bins two-sided (the game culls back faces; T2 shells are open).
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "tower")
if os.environ["TOWN_FULL3D_FACTION"] != "tower":
    raise SystemExit("tower_t2_stage: TOWN_FULL3D_FACTION must be tower")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import tower_t2_meshy as TM  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SEED = "tw_v4"
TEX_K = 2              # painted texels per 1080p px (the relief lane's BUILD_SCALE)
LIGHT_FLOOR = 0.35     # de-light gain floor (share of the building's median irradiance), town_full3d_houses'
GAIN_CLAMP = (0.5, 2.0)
RESID_MIN_PX = 20      # frame px: residual sprite components smaller than this are not re-covered by the seed relief
MESHY_TEX_MAX = 2048
# yaw quadrant (0/90/180/270, the quadrant_fit key) chosen by eye from _work/yaw_<layer>.png; a reused mesh takes its
# source's pick; a layer absent here takes the best coarse F0.5 quadrant (fit())
YAW_PICK: dict[str, int] = {
    "tbtwhall_3": 180,         # sunburst pediment and colonnade toward the camera (90 / 270: flank)
    "tbtwdw_2": 0,             # timber scaffold left, pipe elbow right as painted (best F0.5 270: pipe low centre)
    "tbtwmage_3": 180,         # stair toward the camera like the other guild levels (best F0.5 0: stair behind)
    "tbtwdw_5": 270,           # arched stair at the dome's front left (best F0.5 180: stair at the right)
    "tbtwsilo": 180,           # clock face toward the camera (F0.5 tie with 90)
}
WARP_SIGMAS = (24.0, 16.0, 10.0, 6.0, 4.0, 3.0)   # frame px, coarse to fine (hand-set)
WARP_MAX_STEP_PX = 12.0
SUBDIV_PX = 10.0       # max rest-screen edge (frame px) of a visible triangle (town_full3d_t2_paint.subdivide_screen)
# Reused meshes (the upgrade only adds a piece; the base mesh is refitted to the upgrade's own sprite, and the added
# piece is covered at rest by the residual relief if the mesh misses it).
REUSE = {"tbtwcstl_3": "tbtwcstl_2", "tbtwhall_4": "tbtwhall_3", "tbtwdw_2_2": "tbtwdw_2"}
LAYERS = TM.PLAN + list(REUSE)


def glb_path(lid: str, tag: str = "t2") -> Path:
    return TM.OUT / REUSE.get(lid, lid) / tag / "model.glb"


def load_glb(path: Path) -> dict:
    """GLB -> the painting world (left-handed like Unity: x negated, as glTFast imports); faces rewound outward."""
    import trimesh
    m = trimesh.load(str(path), force="mesh", process=False)
    V = np.asarray(m.vertices, np.float64).copy()
    V[:, 0] *= -1.0
    F = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]
    uv = np.asarray(m.visual.uv, np.float64)
    N = np.asarray(m.vertex_normals, np.float64).copy()   # the GLB's own normals, into the same frame
    N[:, 0] *= -1.0
    tex = m.visual.material.baseColorTexture
    return {"V": V, "F": F, "uv": uv, "N": N, "tex": np.asarray(tex.convert("RGB"))}


def signed_volume(V: np.ndarray, F: np.ndarray) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def frame_mask(lid: str) -> np.ndarray:
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    m = BL.native_mask(L)
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
    zs = S.terrain_state(sc)["fd"]["zs"].astype(np.float64)
    from scipy.ndimage import distance_transform_edt
    _, (iy, ix) = distance_transform_edt(~np.isfinite(zs), return_indices=True)
    _ZS = zs[iy, ix]
    np.save(p, _ZS)
    return _ZS


def front_yaw(cam: dict) -> float:
    f = np.asarray(cam["fwd"], np.float64)
    return math.degrees(math.atan2(-f[0], -f[2]))


_SCN: dict = {}


def fit_setup(lid: str, down: int):
    import stronghold_full3d_scene as S
    from t2_rest_geometry import RectFitter
    if "sc" not in _SCN:
        _SCN["sc"] = S.Scene()
    sc = _SCN["sc"]
    float_z = SC.FP.RELIEF_TUNE.get(lid, {}).get("floatZm")
    zs = np.full((H, W), float(float_z)) if float_z else terrain_z(sc)
    g = load_glb(glb_path(lid))
    tgt = frame_mask(lid)
    tgt[:, TW:] = False
    tgt[TH:] = False
    cam = {k: (np.asarray(v, np.float64) if k in ("pos", "fwd", "right", "up") else v) for k, v in sc.cam.items()}
    fz = RectFitter(cam, zs, (W, H), tgt.astype(np.uint8), g["V"], g["F"], down=down)
    ys, xs = np.nonzero(tgt)
    return sc, g, tgt, fz, (xs.min(), ys.min(), xs.max(), ys.max()), float_z


def fit(lid: str) -> dict:
    """Yaw over the full circle (t2_rest_geometry.quadrant_fit at 1/4 resolution, best per 90 deg quadrant): the
    first Tower fits searched +-45 deg about front-to-camera, but Meshy re-poses buildings (Castle: the hall's painted
    long side came back as its gable front, 90 deg off), so the facing is a quadrant choice. The quadrant is YAW_PICK
    (by eye from _work/yaw_<layer>.png) or else the best coarse F0.5; it is refined at 1/2 resolution
    (Fitter.fit: +-12 deg in 3 deg steps) and then the vertical-stretch pass."""
    import t2_rest_geometry as RG
    t0 = time.time()
    qpath = TM.OUT / lid / "fit_quadrants.json"
    if qpath.is_file():
        quads = {int(k): v for k, v in json.loads(qpath.read_text(encoding="utf-8")).items()}
    else:
        _, _, _, fq, bbox, _ = fit_setup(lid, 4)
        quads = RG.quadrant_fit(fq, bbox)
        qpath.parent.mkdir(parents=True, exist_ok=True)
        qpath.write_text(json.dumps(quads, indent=1), encoding="utf-8")
    src = REUSE.get(lid, lid)
    pick = YAW_PICK.get(lid, YAW_PICK.get(src))
    q = pick if pick is not None else max(quads, key=lambda k: quads[k]["fbeta"])
    sc, g, tgt, fz, bbox, float_z = fit_setup(lid, 2)
    base = fz.fit(bbox, yaws=[quads[q]["yaw"]])
    best = base
    st = fz.refine_stretch(base, lo=0.8, hi=1.25, top_weight=0.5)
    if st["fbeta"] > base["fbeta"] + 0.005:
        best = st
    y0 = front_yaw(fz.cam)
    out = {k: v for k, v in best.items() if k != "silhouette"}
    out["base"] = {k: base[k] for k in ("fbeta", "iou", "precision", "recall")}
    out["quadrant"] = q
    out["quadrantSource"] = f"YAW_PICK (visual review, _work/yaw_{src}.png)" if pick is not None else "best coarse F0.5"
    out["quadrants"] = {str(k): {"yaw": v["yaw"], "fbeta": round(v["fbeta"], 4)} for k, v in sorted(quads.items())}
    out["frontYaw"] = y0
    out["yawFromFront"] = ((best["yaw"] - y0 + 180) % 360) - 180
    out["meshFrom"] = src
    out["depthSource"] = f"floatZm {float_z}" if float_z else "terrain frame depth"
    out["seconds"] = round(time.time() - t0, 1)
    d = TM.OUT / lid
    (d / "fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    ys, xs = np.nonzero(tgt)
    sil = cv2.resize(best["silhouette"].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:TH, :TW] = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS)) // 2
    frame[tgt] = (frame[tgt] * 0.5 + np.array([0, 160, 0])).astype(np.uint8)
    frame[sil] = (frame[sil] * 0.6 + np.array([140, 0, 0])).astype(np.uint8)
    yy0, yy1 = max(0, ys.min() - 40), min(H, ys.max() + 40)
    xx0, xx1 = max(0, xs.min() - 40), min(W, xs.max() + 40)
    Image.fromarray(frame[yy0:yy1, xx0:xx1]).save(d / "fit_overlay.png")
    print(lid, {k: round(out[k], 3) for k in ("iou", "precision", "recall", "fbeta", "stretchY", "yaw")},
          "quadrant", q, {k: round(v["fbeta"], 3) for k, v in sorted(quads.items())}, flush=True)
    return out


def yaw_panel(lid: str) -> Path:
    """Diagnostic for the quadrant choice: each quadrant's coarse fit, the textured Meshy model at rest (crop) and at
    sweep_left / sweep_right / sweep_high, beside the painting -> _work/yaw_<layer>.png."""
    import stronghold_full3d_preview as PV
    import stronghold_full3d_scene as S
    from fit_mesh_to_sprite import yaw_matrix
    from PIL import ImageDraw
    quads = {int(k): v for k, v in json.loads((TM.OUT / lid / "fit_quadrants.json").read_text(encoding="utf-8")).items()}
    sc, g, tgt, fz, bbox, _ = fit_setup(lid, 4)
    R = PV.Renderer(sc.rig, sc.sun, W, H)
    pc = S.pan_cams(sc)
    x0, y0, x1, y1 = bbox
    cx0, cy0, cx1, cy1 = max(x0 - 20, 0), max(y0 - 20, 0), min(x1 + 20, W), min(y1 + 20, H)
    L = SC.layers()[lid]
    bg = SC.albedo_background(carve=False).convert("RGBA")
    bg.alpha_composite(SC.albedo_sprite(L), (int(L["x"]), int(L["y"])))
    fr = Image.new("RGB", (W, H))
    fr.paste(bg.convert("RGB").resize((TW, TH), Image.LANCZOS), (0, 0))
    vn, _ = vertex_normals(fz.v0, g["F"])
    Tn = 220

    def crop_obj(img):
        arr = np.asarray(img)
        m = np.abs(arr.astype(int) - [255, 0, 255]).sum(-1) > 10
        yy, xx = np.nonzero(m)
        if not len(yy):
            return Image.new("RGB", (Tn, Tn))
        c = img.crop((xx.min(), yy.min(), xx.max() + 1, yy.max() + 1))
        c.thumbnail((Tn, Tn))
        return c
    ref = fr.crop((cx0, cy0, cx1, cy1))
    ref.thumbnail((Tn, Tn))
    out = Image.new("RGB", (Tn * 5, Tn * 4), (40, 40, 40))
    d = ImageDraw.Draw(out)
    for i, q in enumerate(sorted(quads)):
        c = quads[q]
        _, Vw = fz.transform(c["yaw"], c["scale"], *c["contactPx"], 1.0)
        R.pieces = []
        R.add("m", Vw, vn @ yaw_matrix(c["yaw"]).T, g["uv"], g["F"], g["tex"])
        rest = Image.fromarray(R.render(fz.cam)).crop((cx0, cy0, cx1, cy1))
        rest.thumbnail((Tn, Tn))
        tiles = [ref, rest] + [crop_obj(Image.fromarray(R.render(pc[p]))) for p in ("sweep_left", "sweep_right",
                                                                                    "sweep_high")]
        for j, t in enumerate(tiles):
            out.paste(t, (j * Tn, i * Tn))
        d.text((4, i * Tn + 4), f"{lid} q{q} yaw {c['yaw']:.0f} F {c['fbeta']:.3f}", fill=(255, 255, 0))
    p = TM.OUT / "_work" / f"yaw_{lid}.png"
    out.save(p)
    return p


def placed(lid: str) -> tuple[dict, dict]:
    from fit_mesh_to_sprite import yaw_matrix
    g = load_glb(glb_path(lid))
    f = json.loads((TM.OUT / lid / "fit.json").read_text(encoding="utf-8"))
    V = g["V"]
    lo, hi = V.min(0), V.max(0)
    v0 = V - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    R = yaw_matrix(f["yaw"])
    Vw = ((v0 * np.array([1.0, f["stretchY"], 1.0])) @ R.T) * f["scale"] + np.asarray(f["position"])
    Nw = (g["N"] * np.array([1.0, 1.0 / f["stretchY"], 1.0])) @ R.T
    Nw /= np.linalg.norm(Nw, axis=1, keepdims=True) + 1e-12
    F = g["F"]
    if signed_volume(Vw, F) < 0:
        F = F[:, [0, 2, 1]]
    g["V"], g["F"], g["N"] = Vw, F, Nw
    return g, f


def vertex_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    return vn, fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)


RECT = np.zeros((H, W), bool)
RECT[:TH, :TW] = True    # the painted rect: mesh px outside it are not pulled (the building may continue off-frame)


def _smooth_field(pts: np.ndarray, vec: np.ndarray, sigma: float) -> np.ndarray:
    """Dense (H, W, 2) field from scattered displacement samples: Gaussian normalised convolution."""
    acc = np.zeros((H, W, 2), np.float32)
    wgt = np.zeros((H, W), np.float32)
    if len(pts):
        np.add.at(acc, (pts[:, 1], pts[:, 0]), vec.astype(np.float32))
        np.add.at(wgt, (pts[:, 1], pts[:, 0]), 1.0)
    acc = cv2.GaussianBlur(acc, (0, 0), sigma)
    wgt = cv2.GaussianBlur(wgt, (0, 0), sigma)
    # far from any sample the field fades to 0 (the weight's own falloff), never extrapolates
    return acc / np.maximum(wgt, 1e-3)[..., None] * np.clip(wgt / 0.02, 0, 1)[..., None]


def silhouette_warp(sc, V: np.ndarray, vn: np.ndarray, F: np.ndarray, tgt: np.ndarray) -> tuple[np.ndarray, dict]:
    """Snap the rest silhouette onto the sprite mask: every vertex moves in the image plane by a smooth field, at its
    own camera depth (so the rest view changes only laterally; the 3D form is kept under the sweeps). Samples: an
    overflow px (mesh, not sprite) pulls toward its nearest sprite px; an uncovered sprite px pulls its nearest mesh px
    toward itself. Coarse-to-fine (WARP_SIGMAS), each step's move capped at WARP_MAX_STEP_PX."""
    import town_full3d_houses as HS
    from scipy.ndimage import distance_transform_edt
    cam = sc.cam
    V = V.copy()
    hist = []
    for sigma in WARP_SIGMAS:
        idb, _ = HS.rest_buffers(sc, [(V, vn, F, 0)], W, H)
        S = idb >= 0
        over = S & ~tgt & RECT
        under = tgt & ~S
        hist.append({"sigma": sigma, "overPx": int(over.sum()), "underPx": int(under.sum())})
        _, (ty, tx) = distance_transform_edt(~tgt, return_indices=True)
        _, (sy, sx) = distance_transform_edt(~S, return_indices=True)
        oy, ox = np.nonzero(over)
        uy, ux = np.nonzero(under)
        pts = np.concatenate([np.stack([ox, oy], 1), np.stack([sx[uy, ux], sy[uy, ux]], 1)])
        vec = np.concatenate([np.stack([tx[oy, ox] - ox, ty[oy, ox] - oy], 1),
                              np.stack([ux - sx[uy, ux], uy - sy[uy, ux]], 1)]).astype(np.float32)
        D = _smooth_field(pts, vec, sigma)
        px, py, zc = T.project(cam, V)
        xi = np.clip(np.round(px).astype(int), 0, W - 1)
        yi = np.clip(np.round(py).astype(int), 0, H - 1)
        d = D[yi, xi]
        mag = np.linalg.norm(d, axis=1, keepdims=True)
        d = d * np.minimum(1.0, WARP_MAX_STEP_PX / np.maximum(mag, 1e-6))
        V = cam["pos"] + T.rays(cam, px + d[:, 0], py + d[:, 1]) * zc[:, None]
    idb, _ = HS.rest_buffers(sc, [(V, vn, F, 0)], W, H)
    S = idb >= 0
    inter, union = (S & tgt).sum(), (S | tgt).sum()
    hist.append({"final": True, "overPx": int((S & ~tgt & RECT).sum()), "underPx": int((tgt & ~S).sum()),
                 "iou": round(float(inter / max(union, 1)), 4)})
    return V, {"steps": hist}


def seed_body(lid: str, sc) -> tuple:
    """The seed's Mesh_Body_<layer>: painting-world P, n, uv, tris and its albedo png path."""
    import stronghold_full3d_scene as S
    d = SC.DATA / "candidates" / SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v, n, uv, subs = S.read_bin(d / f"Mesh_Body_{lid}.bytes")
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    return P, n.astype(np.float64) @ sc.C.T, uv, np.concatenate(subs), d / f"Mesh_Body_{lid}_albedo.png"


def to_frame(lid: str, m: np.ndarray) -> np.ndarray:
    """A native-size sprite mask placed in the 1920x1080 frame (x SC.SCALE)."""
    L = SC.layers()[lid]
    s = cv2.resize(m.astype(np.float32), (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)),
                   interpolation=cv2.INTER_LINEAR) > 0.5
    out = np.zeros((H, W), bool)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    hh, ww = min(s.shape[0], H - y0), min(s.shape[1], W - x0)
    out[y0:y0 + hh, x0:x0 + ww] = s[:hh, :ww]
    return out


def stage_layer(sc, lid: str) -> dict:
    """The silhouette warp (this module's own step), then the shared painted-front bake
    (town_full3d_t2_paint.rest_geometry_split, the Castle method: rest-visible triangles subdivided to <= SUBDIV_PX,
    clipped at the painted rect, painted and de-lit by the seed's painting-derived normals; the rest Meshy; the
    seed relief over uncovered sprite px)."""
    import town_full3d_t2_paint as TP
    g, f = placed(lid)
    vn, _ = vertex_normals(g["V"], g["F"])
    g["V"], warp = silhouette_warp(sc, g["V"], vn, g["F"], frame_mask(lid) & RECT)
    rep = TP.rest_geometry_split(sc, lid, g, f, seed_body, to_frame, tex_k=TEX_K, subdiv_px=SUBDIV_PX,
                                 light_floor=LIGHT_FLOOR, gain_clamp=GAIN_CLAMP, meshy_tex_max=MESHY_TEX_MAX,
                                 resid_min_px=RESID_MIN_PX)
    rep["warp"] = warp
    return rep


def stage(layers: list[str]) -> int:
    import stronghold_full3d_scene as S
    if not S.CANDIDATE or S.CANDIDATE == SEED:
        raise SystemExit(f"set TOWN_FULL3D_CANDIDATE to the T2 candidate (never the {SEED} seed)")
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
        report["buildings"][lid].update({"method": "meshy_t2", "texelsPerPx": r["texelsPerPx"],
                                         "tris": r["tris"] + r["residualTris"], "frontTris": r["frontTris"]})
        rp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(lid, json.dumps(r), flush=True)
    S.write_catalog(sc, carry="fresh")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "yaw-panel", "stage"])
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--faction", default="tower")
    a = ap.parse_args()
    layers = a.layer or LAYERS
    layers = [lid for lid in layers if glb_path(lid).is_file()]
    if a.cmd == "fit":
        for lid in layers:
            fit(lid)
        return 0
    if a.cmd == "yaw-panel":
        for lid in layers:
            if lid not in REUSE:
                print(yaw_panel(lid), flush=True)
        return 0
    return stage(layers)


if __name__ == "__main__":
    raise SystemExit(main())
