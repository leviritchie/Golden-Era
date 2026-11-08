"""Inferno T2 buildings: register the Meshy meshes to their sprites and stage them into a full-3D candidate.

Driven by inferno_t2_buildings.py (fit / stage / sheet). Method (docs/homm3_inferno_t2_town_buildings.md):

  fit    fit_mesh_to_sprite.Fitter under the rest camera in the painting world (left-handed like Unity: the GLB takes
         glTFast's x negation and the winding flip). Yaw within +-YAW_WINDOW of "the model's +Z front faces the camera"
         (Meshy builds the input view as the model's front), scale and ground-contact pixel on the calibrated terrain
         depth, F-beta 0.5 against the layer's native mask at frame resolution; then the optional vertical stretch
         pass, kept only when its F-beta is higher. The base sinks SINK x the height into the terrain (no floating
         corner on the slope). Writes <layer>/<tag>/placement.json (+ a silhouette overlay png).
  stage  in the candidate (TOWN_FULL3D_CANDIDATE, seeded from SEED): Mesh_Body_<layer> becomes the placed mesh.
         * the placed mesh is clipped exactly (cut edges interpolated) to the rest-camera wedge of its sprite's
           horizontal extent, so the framing gate's whole-bounds check sees the extent the profile framing was tuned on;
         * painted-front bake (town_full3d_t2_paint.painted_front, the one T2 bake): rest-drawn triangles are
           midpoint-split to SUBDIV_PX (4 px) projected edges; a triangle is front when it owns >= VISIBLE_MIN of
           its rest px or a centroid / corner passes the rest depth test. The front (Mesh_Body_<layer>) is wound
           toward the rest camera, carries the smooth camera-facing normal, and takes the sprite by screen position
           at SUPER x the frame, de-lit by the Hex/Lit irradiance of that normal, so the rest frame is the painting
           up to rasterisation. Every other triangle (Mesh_BodyM_<layer>) keeps Meshy's uvs and texture with a
           per-channel gain onto the de-lit painting, and its corner normals are welded where they agree with the
           face (NORMAL_AGREE), the face normal elsewhere;
         * skirt: the painted px of the layer's mask that the mesh does not cover at rest (grown SKIRT_GROW px) keep
           the seed's depth-solid triangles frontmost there (seed rest id buffer), as Mesh_Body_<layer>_skirt with the
           seed's own texture (the painted lava stream, gold floor and pit rims are ground, not building);
         * winding: every triangle is wound to its outward side (vertex normal), the lane's orient() (sgn 1), then
           emitted two-sided (two_sided()) so the game's Cull Back never drops a Meshy flap or a skirt cut-out.
         Rows / build spec / catalog are rewritten by stronghold_full3d_scene (save_rows, write_catalog); the catalog
         gains a "t2Buildings" block with the Meshy provenance and the fit numbers.
  review per-layer offline previews (environment + one layer, seed vs T2, rest + sweeps) in <OUTD>/_layer_review
  select every layer keeps its Meshy body except BROKEN (judged by eye in review); rest dE76 is a diagnostic
  sheet  artifacts/claude_takeover_20260927/review/homm3_inferno_t2_buildings.png

Proof tier: generated artifact. Nothing here installs anything.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_scene as S   # reads TOWN_FULL3D_CANDIDATE
import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import stronghold_full3d_ground as G
import stronghold_full3d_buildings as BL
import stronghold_full3d_solids as SL
import fit_mesh_to_sprite as FM
import inferno_t2_buildings as IB
import town_full3d_t2_paint as TP   # the one T2 bake

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
YAW_WINDOW = 60.0
SINK = 0.02
SKIRT_GROW = 2
NORMAL_AGREE = 0.5      # corner normal . face normal below this: the corner takes the face normal (Meshy half)
# painted-front bake: town_full3d_t2_paint (SUPER, SUBDIV_PX 4, VISIBLE_MIN, VIS_TOL, LIGHT_FLOOR, GAIN_CLAMP there)
SEED = IB.SEED_CANDIDATE


# ------------------------------------------------------------------------------------------------ glb
def load_glb(path: Path) -> dict:
    import trimesh
    sc = trimesh.load(str(path), force="scene")
    geos = list(sc.geometry.values())
    if len(geos) != 1:
        raise SystemExit(f"{path}: {len(geos)} geometries (one textured mesh expected)")
    node = sc.graph.nodes_geometry[0]
    Tm, _ = sc.graph[node]
    m = geos[0].copy()
    m.apply_transform(Tm)
    uv = np.asarray(m.visual.uv, np.float64)
    img = getattr(m.visual.material, "baseColorTexture", None)
    if img is None or len(uv) != len(m.vertices):
        raise SystemExit(f"{path}: no base colour texture / per-vertex uv")
    v = np.asarray(m.vertices, np.float64).copy()
    v[:, 0] *= -1.0                                   # glTF right-handed -> left-handed (glTFast)
    f = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]   # the mirror flips the winding back
    return {"v": v, "f": f, "uv": uv, "tex": np.asarray(img.convert("RGB")),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "tris": int(len(f)), "verts": int(len(v))}


def welded_normals(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Vertex normals over the position-welded mesh (Meshy splits vertices along UV seams; a per-split normal would
    light the seams as creases)."""
    key = np.round(P / (np.ptp(P, 0).max() * 1e-5 + 1e-12)).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])   # area weighted
    acc = np.zeros((inv.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, inv[F[:, k]], fn)
    n = acc[inv]
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


# ------------------------------------------------------------------------------------------------ fit
def frame_mask(L: dict) -> np.ndarray:
    m = BL.native_mask(L).astype(np.uint8) * 255
    mf = cv2.resize(m, (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((H, W), np.uint8)
    x, y = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    h_, w_ = min(mf.shape[0], TH - y), min(mf.shape[1], TW - x)
    out[y:y + h_, x:x + w_] = mf[:h_, :w_]
    return out > 127


_Z = None


def ground_depth() -> np.ndarray:
    """Frame camera-z of the terrain (painting m), sky / NaN filled by the nearest ground (contact lookups only)."""
    global _Z
    if _Z is None:
        cache = SC.DATA / "work" / "t2_ground_depth.npy"
        if cache.is_file():
            _Z = np.load(cache)
        else:
            ctx = G.Ctx()
            rd = T.rect_depth(ctx.cam)
            field, _ = T.world_field(ctx.cam, rd)
            fd = G.frame_depth(ctx, rd, field)
            z = np.array(fd["zs"], np.float64)
            bad = ~np.isfinite(z)
            z = BL._fill_nearest(z[..., None], ~bad)[..., 0]
            np.save(cache, z)
            _Z = z
    return _Z


def mesh_dir(src: str, tag: str) -> Path:
    return IB.OUTD / src / tag


def fit_layer(lid: str, tag: str) -> dict:
    src = IB.mesh_source(lid)
    g = load_glb(mesh_dir(src, tag) / "model.glb")
    L = SC.layers()[lid]
    cam = T.camera()
    tgt = frame_mask(L)
    fz = FM.Fitter(cam, ground_depth(), (W, H), tgt, g["v"], g["f"], down=2)
    fh, _ = T.heading(cam)
    yaw0 = math.degrees(math.atan2(-fh[0], -fh[2]))     # the model's +Z toward the camera
    yaws = [yaw0 + d for d in np.arange(-YAW_WINDOW, YAW_WINDOW + 0.1, 10.0)]
    ys, xs = np.nonzero(tgt)
    t0 = time.time()
    base = fz.fit((xs.min(), ys.min(), xs.max(), ys.max()), yaws=yaws)
    best = base
    st = fz.refine_stretch(base)
    if st["fbeta"] > base["fbeta"] + 0.005:
        best = st
    rep = {k: best[k] for k in ("yaw", "scale", "position", "contactPx", "fbeta", "stretchY", "iou", "precision",
                                "recall", "worldHeight")}
    rep.update({"layer": lid, "meshFrom": src, "tag": tag, "modelSha256": g["sha256"], "yawFront": yaw0,
                "yawRel": ((best["yaw"] - yaw0 + 180) % 360) - 180, "sinkM": SINK * best["worldHeight"],
                "base": {k: base[k] for k in ("fbeta", "iou", "precision", "recall")},
                "stretchTried": {k: st[k] for k in ("fbeta", "iou", "stretchY")}, "seconds": round(time.time() - t0, 1)})
    out = IB.OUTD / lid / f"placement_{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)     # a reuse layer has no Meshy folder of its own
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    # overlay: sprite mask (red) vs mesh silhouette (green)
    sil = best["silhouette"]
    x0, y0, x1, y1 = max(xs.min() - 60, 0), max(ys.min() - 60, 0), min(xs.max() + 60, W), min(ys.max() + 60, H)
    t2 = tgt[::2, ::2][y0 // 2:y1 // 2, x0 // 2:x1 // 2]
    s2 = sil[y0 // 2:y1 // 2, x0 // 2:x1 // 2]
    ov = np.zeros(t2.shape + (3,), np.uint8)
    ov[..., 0] = t2 * 255
    ov[..., 1] = s2 * 255
    Image.fromarray(ov).resize((ov.shape[1] * 2, ov.shape[0] * 2), Image.NEAREST).save(
        IB.OUTD / lid / f"placement_{tag}.png")
    print(lid, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rep.items()
                if k in ("iou", "precision", "recall", "stretchY", "yawRel", "seconds")}, flush=True)
    return rep


def fit_all(layers: list[str], tag: str) -> None:
    for lid in layers:
        if IB.mesh_source(lid) is None:
            continue
        if not (mesh_dir(IB.mesh_source(lid), tag) / "model.glb").is_file():
            print(lid, "no model.glb yet")
            continue
        fit_layer(lid, tag)


def clip_plane(P: np.ndarray, uv: np.ndarray, F: np.ndarray, o: np.ndarray, n: np.ndarray):
    """Keep the side dot(p - o, n) >= 0 of a triangle soup; crossing triangles are cut exactly (Sutherland-Hodgman,
    positions and uvs interpolated along the cut edges), so the kept surface ends on the plane."""
    d = (P - o) @ n
    inside = d[F] >= 0
    keep = F[inside.all(1)]
    cross = np.nonzero(inside.any(1) & ~inside.all(1))[0]
    P2, uv2, extra = [P], [uv], []
    nv = len(P)
    for t in cross:
        poly = []
        tri = F[t]
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            if d[a] >= 0:
                poly.append(("v", a))
            if (d[a] >= 0) != (d[b] >= 0):
                w = d[a] / (d[a] - d[b])
                P2.append((P[a] + w * (P[b] - P[a]))[None])
                uv2.append((uv[a] + w * (uv[b] - uv[a]))[None])
                poly.append(("v", nv))
                nv += 1
        ids = [q[1] for q in poly]
        for j in range(1, len(ids) - 1):
            extra.append([ids[0], ids[j], ids[j + 1]])
    P = np.concatenate(P2)
    uv = np.concatenate(uv2)
    F = np.concatenate([keep, np.asarray(extra, np.int64).reshape(-1, 3)]) if extra else keep
    used = np.unique(F)
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    return P[used], uv[used], remap[F]


def sprite_wedge(cam: dict, L: dict):
    """The two vertical planes through the rest camera at the left / right edge of the layer's native mask (frame
    px): the horizontal extent HoMM3 gives the building. Returns [(origin, inward normal)]."""
    xs = np.nonzero(frame_mask(L).any(0))[0]
    x0, x1 = float(xs.min()), float(xs.max() + 1)
    out = []
    for xe, sgn in ((x0, 1.0), (x1, -1.0)):
        d1, d2 = T.rays(cam, np.array([xe, xe]), np.array([0.0, float(H)]))
        n = np.cross(d1, d2)
        mid = T.rays(cam, np.array([(x0 + x1) / 2]), np.array([H / 2.0]))[0]
        if n @ mid < 0:
            n = -n
        out.append((cam["pos"], n / np.linalg.norm(n)))
    return out


def placed(lid: str, tag: str) -> dict:
    """World geometry of the placed mesh (painting world), from placement_<tag>.json, clipped to the rest-camera
    wedge of its sprite's horizontal extent: Meshy's massing past the sprite's left / right edge (the
    concept-completed hall beyond the frame, back walls that stick out behind other buildings) is not in the HoMM3
    picture, and it would move the whole-bounds framing gate (town_full3d_framing: every building inside the
    visible region at rest) off the extent the profile's framing was tuned on."""
    pl = json.loads((IB.OUTD / lid / f"placement_{tag}.json").read_text(encoding="utf-8"))
    g = load_glb(mesh_dir(pl["meshFrom"], tag) / "model.glb")
    if g["sha256"] != pl["modelSha256"]:
        raise SystemExit(f"{lid}: placement_{tag}.json was fitted to another model; fit again")
    cam = T.camera()
    fz = FM.Fitter(cam, ground_depth(), (W, H), np.ones((4, 4), bool), g["v"], g["f"], down=2)
    _, P = fz.transform(pl["yaw"], pl["scale"], *pl["contactPx"], pl["stretchY"])
    P = P - np.array([0.0, pl["sinkM"], 0.0])
    uv, F0 = g["uv"], g["f"]
    n0 = len(F0)
    for o, n in sprite_wedge(cam, SC.layers()[lid]):
        P, uv, F0 = clip_plane(P, uv, F0, o, n)
    N = welded_normals(P, F0)
    F = BL.orient(P, F0, N[F0].mean(1), 1.0)
    # corner normals: the welded normal where it agrees with the wound face (smooth shading across Meshy's uv seams),
    # the face normal where it does not (opposed / folded sheets cancel or flip the welded normal, which shades a
    # triangle through zero light and leaves black slivers at rest that no de-light can undo); unwelded per triangle
    fnF = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    fnF /= np.linalg.norm(fnF, axis=1, keepdims=True) + 1e-12
    Nc = N[F]
    agree = (Nc * fnF[:, None]).sum(-1) >= NORMAL_AGREE
    Nc = np.where(agree[..., None], Nc, fnF[:, None])
    nT = len(F)
    return {"P": P[F].reshape(-1, 3), "N": Nc.reshape(-1, 3), "F": np.arange(3 * nT).reshape(nT, 3),
            "uv": uv[F].reshape(-1, 2), "g": g, "pl": pl, "clippedTris": int(n0 - len(F0)),
            "faceNormalCorners": round(float((~agree).mean()), 4)}


# ------------------------------------------------------------------------------------------------ stage
def rest_painting(L: dict, k: int) -> tuple[np.ndarray, np.ndarray]:
    """The rest image a layer's triangles project (sRGB float, TH*k x TW*k): the painting with the layer's static
    plate over its mask; and the plate mask."""
    bg = np.asarray(SC.albedo_background(carve=False).resize((TW * k, TH * k), Image.LANCZOS)).astype(np.float32) / 255
    spr = SC.albedo_sprite(L)
    sw, sh = round(spr.width * SC.SCALE * k), round(spr.height * SC.SCALE * k)
    big = np.asarray(spr.resize((sw, sh), Image.LANCZOS)).astype(np.float32)[..., :3] / 255
    mn = BL.native_mask(L).astype(np.float32)
    mb = cv2.resize(mn, (sw, sh), interpolation=cv2.INTER_LINEAR) > 0.5
    x, y = round(L["x"] * SC.SCALE * k), round(L["y"] * SC.SCALE * k)
    h_, w_ = min(sh, TH * k - y), min(sw, TW * k - x)
    out = bg.copy()
    m = np.zeros((TH * k, TW * k), bool)
    m[y:y + h_, x:x + w_] = mb[:h_, :w_]
    sub = out[y:y + h_, x:x + w_]
    sub[mb[:h_, :w_]] = big[:h_, :w_][mb[:h_, :w_]]
    return out, m


def seed_stage() -> Path:
    return SC.DATA / "candidates" / SEED / "unity_project" / S.ASSET_ROOT


def skirt(sc, lid: str, cover: np.ndarray, mask_f: np.ndarray):
    """The seed's depth-solid triangles frontmost (seed rest id buffer) at a painted px of the layer that the mesh
    leaves uncovered at rest (grown SKIRT_GROW px so the skirt seals against the mesh's edge)."""
    import town_full3d_houses as HS
    prefab = S.PREFIX + lid
    mb = seed_stage() / prefab / f"Mesh_Body_{lid}.bytes"
    v, n, uv, subs = S.read_bin(mb)
    tris = np.concatenate(subs)
    P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    nw = n.astype(np.float64) @ sc.C.T
    resid0 = mask_f & ~cover
    if resid0.sum() < 30:
        return None, int(resid0.sum())
    resid = cv2.dilate(resid0.astype(np.uint8), np.ones((2 * SKIRT_GROW + 1,) * 2, np.uint8)) > 0
    idb, _ = HS.rest_buffers(sc, [(P, nw, tris, 0)], W, H)
    own = np.round(idb).astype(np.int64)
    hit = own[resid & (own >= 0)]
    keep = np.zeros(len(tris), bool)
    keep[hit] = True
    if not keep.any():
        return None, int(resid0.sum())
    t = tris[keep]
    used = np.unique(t)
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    img = np.asarray(Image.open(mb.with_name(mb.stem + "_albedo.png")).convert("RGB"))
    return {"P": P[used], "n": nw[used], "uv": uv[used], "tris": remap[t], "img": img}, int(resid0.sum())


def sample_bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """img at float px (x, y), px centres at +0.5; cv2.remap takes at most 32767 points per axis, so chunk."""
    out = np.empty((len(x), img.shape[2]), np.float32)
    src = img.astype(np.float32)
    for i in range(0, len(x), 30000):
        mx = (np.asarray(x[i:i + 30000], np.float32) - 0.5).reshape(-1, 1)
        my = (np.asarray(y[i:i + 30000], np.float32) - 0.5).reshape(-1, 1)
        out[i:i + 30000] = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(len(mx), -1)
    return out


def stage_layer(sc, lid: str, tag: str) -> dict:
    """The painted-front bake (town_full3d_t2_paint.painted_front, the one T2 bake) on the placed, wedge-clipped mesh.
    Rest-drawn triangles are split to SUBDIV_PX; a triangle is front when it owns >= VISIBLE_MIN of its rest px or a
    centroid / corner passes the rest depth test. Mesh_Body_<lid>: the front, wound toward the rest camera, with the
    smooth camera-facing normal (vertex -> rest eye) and the sprite by screen position at SUPER x the frame, de-lit
    per px by the Hex/Lit irradiance of that normal. Mesh_BodyM_<lid>: every other triangle on Meshy's uvs with
    Meshy's texture, per-channel gain onto the de-lit painting. Both two-sided. Skirt: the seed's triangles frontmost
    where the painted mask is left uncovered at rest. This lane's by-design values: the rest id buffer uses the dome's
    near / far planes (TP.CLIP_DOME), the sprite_fill mask is native_mask, and the Meshy gain is measured once more
    than 200 px are painted and kept float32."""
    t0 = time.time()
    L = SC.layers()[lid]
    m = placed(lid, tag)
    g = m["g"]
    P, N, uv, F, srep = TP.subdivide_screen(sc.cam, m["P"], m["N"], m["uv"], m["F"], clip=TP.CLIP_DOME)
    res = TP.painted_front(sc, lid, L, BL.native_mask(L), P, N, F, uv, TP.tex_to_lin(g["tex"]), clip=TP.CLIP_DOME,
                           gain_guard=("px", 200), gain_dtype=np.float32)
    pk = S.PREFIX + lid
    sc.add_bin(pk, f"Mesh_Body_{lid}", *res["front"])
    has_m = res["meshy"] is not None
    if has_m:
        sc.add_bin(pk, f"Mesh_BodyM_{lid}", *res["meshy"], max_size=2048)
    bake = {**res["rep"], "subdivide": srep, "meshyPiece": has_m}
    cover = res["sil"]
    mask_f = frame_mask(L)
    sk, resid_px = skirt(sc, lid, cover, mask_f)
    sk_rep = None
    if sk is not None:
        sc.add_bin(pk, f"Mesh_Body_{lid}_skirt", *TP.two_sided(sk["P"], sk["n"], sk["uv"], sk["tris"]),
                   sk["img"], srgb=True)
        sk_rep = {"tris": int(len(sk["tris"])), "residualPx": resid_px}
    rep = {"meshFrom": m["pl"]["meshFrom"], "modelSha256": g["sha256"], "modelTris": g["tris"],
           "wedgeClippedTris": m["clippedTris"], "faceNormalCorners": m["faceNormalCorners"],
           "fit": {k2: m["pl"][k2] for k2 in ("iou", "precision", "recall", "fbeta", "stretchY", "yawRel",
                                              "worldHeight")},
           "bake": bake, "coverOfMask": round(float((cover & mask_f).sum() / max(mask_f.sum(), 1)), 3),
           "overshootPx": int((cover & ~mask_f).sum()), "skirt": sk_rep, "residualPx": resid_px,
           "seconds": round(time.time() - t0, 1)}
    print(lid, json.dumps({k2: rep[k2] for k2 in ("fit", "bake", "coverOfMask", "overshootPx", "skirt", "seconds")}),
          flush=True)
    return rep


def mark_meshy(layers: list[str] | None = None, t2: dict | None = None) -> dict:
    """Mark the stage report's building rows of the Meshy-staged layers method "meshy_t2", as Castle and Factory
    stage them, so town_full3d_building_depth.is_meshy (rest_seams, residual_bins, seam_guard, redepth) reads them as
    Meshy bodies (worklist 870c0da64a: rest_seams refused Mesh_BodyM_<l> as meshy=False). The rows were staged
    "solid" by the depth seed that T2 replaces, and stage() never updated them.
    t2: the Meshy layers ({lid: report row}); stage() passes work/t2_report.json. None (`mark-meshy` on a candidate
    staged before this): the catalog's carried t2Buildings.layers, since candidate-init does not carry the work
    report (zs_v3 seeded from props_v2 has none). layers None: every layer of t2. Fail closed: no t2 source; a layer
    without a t2 row, a stage report row or a staged Mesh_Body_<l>; a row whose method is anything other than the
    seed's "solid", unset or "meshy_t2"."""
    src = "work/t2_report.json"
    if t2 is None:
        cat_p = S.OUT / "catalog.json"
        cat = json.loads(cat_p.read_text(encoding="utf-8")) if cat_p.is_file() else {}
        t2 = (cat.get("t2Buildings") or {}).get("layers")
        src = f"{cat_p} t2Buildings.layers"
        if not t2:
            raise SystemExit(f"mark-meshy: {src} missing: no Meshy layer was staged in this candidate")
    sp = S.WORK / "stage_report.json"
    rep = json.loads(sp.read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    layers = sorted(t2) if layers is None else layers
    done = {}
    for lid in layers:
        b = (rep.get("buildings") or {}).get(lid)
        names = {x["name"] for x in rows.get(S.PREFIX + lid, {}).get("bins", [])}
        if lid not in t2 or b is None or f"Mesh_Body_{lid}" not in names:
            raise SystemExit(f"mark-meshy: {lid}: t2 row ({src}) {lid in t2}, stage report row {b is not None}, "
                             f"Mesh_Body_{lid} staged {f'Mesh_Body_{lid}' in names}")
        if b.get("method") not in (None, "solid", "meshy_t2"):
            raise SystemExit(f"mark-meshy: {lid}: stage report method is {b.get('method')!r}, not the depth seed's "
                             f"'solid' or a Meshy T2 row")
        done[lid] = b.get("method")
        b["method"] = "meshy_t2"
    sp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("MARK MESHY", json.dumps({"source": src, "layers": len(done),
                                    "newlyMarked": sorted(k for k, v in done.items() if v != "meshy_t2")}))
    return done


def stage(layers: list[str], tag: str) -> None:
    if not S.CANDIDATE or S.CANDIDATE == SEED:
        raise SystemExit(f"stage: set TOWN_FULL3D_CANDIDATE to a candidate seeded from {SEED} (never {SEED} itself)")
    if not S.ROWS.is_file():
        raise SystemExit(f"stage: {S.ROWS} missing; run stronghold_full3d_scene.py candidate-init --seed-from {SEED}")
    sc = S.Scene()
    reps = {}
    for lid in layers:
        if IB.mesh_source(lid) is None:
            continue
        reps[lid] = stage_layer(sc, lid, tag)
    # a restaged layer whose skirt disappeared must not keep an old skirt row
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    for lid in reps:
        pf = S.PREFIX + lid
        drop = (() if reps[lid]["skirt"] else (f"Mesh_Body_{lid}_skirt",)) + (
            () if reps[lid]["bake"]["meshyPiece"] else (f"Mesh_BodyM_{lid}",))
        if pf in rows:
            rows[pf]["bins"] = [b for b in rows[pf]["bins"] if b["name"] not in drop]
        for d in drop:
            for f in (S.STAGE / pf).glob(f"{d}.*"):
                f.unlink()
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    S.save_rows(sc)
    rp = S.WORK / "t2_report.json"
    old = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
    old.update(reps)
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    mark_meshy(sorted(reps), old)
    S.write_catalog(sc, carry="fresh")
    cat_p = S.OUT / "catalog.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    cat["t2Buildings"] = t2_catalog_block(old, tag)
    cat_p.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    # offline preview (moderngl) of the default and pan poses
    S.load_staged_preview(sc)
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    print(S.preview(sc, S.WORK / "preview", cams))


def t2_catalog_block(reps: dict, tag: str) -> dict:
    tasks = {}
    for lid in IB.own_layers():
        tf = IB.OUTD / lid / tag / "task.json"
        if tf.is_file():
            tasks[lid] = json.loads(tf.read_text(encoding="utf-8"))["taskId"]
    return {"schema": "inferno_t2_buildings.v1", "seed": SEED, "meshyModel": "meshy-t2 smart-topology textured",
            "texture": "painted front (rampart lane): rest-drawn triangles split to 4 px, the rest-visible front "
                       "takes the de-lit sprite by screen position with a smooth camera-facing normal "
                       "(Mesh_Body_); every other triangle keeps Meshy's uvs and texture with a per-channel gain "
                       "(Mesh_BodyM_); two-sided; seed depth-solid skirt where the mesh leaves painted px uncovered",
            "layers": {lid: {**r, "meshyTask": tasks.get(r["meshFrom"])} for lid, r in reps.items()},
            "skipped": {lid: p["why"] for lid, p in IB.PLAN.items() if p["mesh"] == "skip"},
            "unreachable": IB.UNREACHABLE_NOTE,
            "proofTier": "generated artifact (offline previews; bundle / editor render / in-game per the doc)"}


# ------------------------------------------------------------------------------------------------ select
# Sweep review by eye (layer_review pngs, 2026-09-29; user decision: Meshy geometry is the default because it stays
# consistent at the sweeps where the relief warps). A layer goes back to the seed relief ONLY when its Meshy body is
# genuinely broken at the sweeps; the reason is recorded here and in the doc. Rest dE76 is a diagnostic, not a gate.
BROKEN: dict[str, str] = {
    "tbindw_3_2": "demon gate: the base shatters into painted shards and the horns double at sweep_right / sweep_high",
    "tbindw_4_2": "pentagram gate: the pentagram face breaks into shards at sweep_right / sweep_high",
    "tbindw_5_2": "fire lake: the second dome collapses into a dark hole over a floor slab at sweep_right / sweep_high",
    "tbindw_2_2": "kennels gate: a black slit opens along the top of the wall at sweep_right / sweep_high",
}
SWEEP_NOTES: dict[str, str] = {
    "tbincstl_3": "castle: a solid keep where the relief streaks its sides (sweep_right)",
    "tbindw_1_2": "hall of sins: more solid than the relief's stretched slabs; some edge flaps remain",
    "tbindw_3": "demon gate base: solid, a few jagged edges (sweep_right)",
    "tbinblak": "blacksmith: solid walls; the chimney top steps slightly at sweep_right",
    "tbinmark": "marketplace: timber sheds read as structure; both versions shear at sweep_right",
}
_RVS = """#version 330
uniform mat4 mvp; in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; out vec3 v_n; out vec2 v_uv;
void main(){ gl_Position = mvp * vec4(in_pos,1.0); v_n = in_nrm; v_uv = in_uv; }"""
_RFS = """#version 330
uniform float pid; in vec3 v_n; in vec2 v_uv; layout(location=0) out vec4 o0; layout(location=1) out vec4 o1;
void main(){ o0 = vec4(v_uv, pid, 1.0); o1 = vec4(normalize(v_n), 1.0); }"""


def rest_recon(stage_dir: Path, lid: str, sc):
    """A layer's staged Mesh_ pieces alone at the rest camera, Unity Cull Back (GL front), bilinear albedo x Hex/Lit
    light of the drawn normal: (sRGB image W x H, covered mask)."""
    import moderngl
    import conflux_full3d_env as E
    import stronghold_full3d_preview as PV
    rows = json.loads((stage_dir / "rows.json").read_text(encoding="utf-8"))
    named = {b["name"] for b in rows.get(S.PREFIX + lid, {}).get("bins", [])}
    bins = sorted(b for b in (stage_dir / (S.PREFIX + lid)).glob("Mesh_*.bytes")
                  if b.stem in named and b.with_name(b.stem + "_albedo.png").is_file())
    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader=_RVS, fragment_shader=_RFS)
        c0 = ctx.texture((W, H), 4, dtype="f4")
        c1 = ctx.texture((W, H), 4, dtype="f4")
        fbo = ctx.framebuffer([c0, c1], ctx.depth_texture((W, H)))
        fbo.use()
        fbo.clear(0, 0, -1, 0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        ctx.cull_face = "front"
        cam = sc.cam
        mvp = PV.perspective(cam["fov"], W / H, 2.0, T.DOME_R * 1.2) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                                cam["right"])
        prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
        texs = []
        for i, b in enumerate(bins):
            v_, n_, uv, subs = S.read_bin(b)
            F = np.concatenate(subs)
            P = sc.cpos + (v_.astype(np.float64) / sc.scale) @ sc.C.T
            N = n_.astype(np.float64) @ sc.C.T
            prog["pid"].value = float(i)
            vb = np.concatenate([P, N, uv], 1).astype(np.float32)[F.ravel()]
            ctx.vertex_array(prog, [(ctx.buffer(vb.tobytes()), "3f 3f 2f", "in_pos", "in_nrm", "in_uv")]).render()
            texs.append(G.SC_srgb_to_lin(np.asarray(Image.open(b.with_name(b.stem + "_albedo.png")).convert("RGB"))
                                         .astype(np.float32) / 255))
        a = np.frombuffer(c0.read(), np.float32).reshape(H, W, 4)[::-1].copy()
        n = np.frombuffer(c1.read(), np.float32).reshape(H, W, 4)[::-1, :, :3].copy()
    finally:
        ctx.release()
    pid = np.round(a[..., 2]).astype(int)
    alb = np.zeros((H, W, 3), np.float32)
    for i, t in enumerate(texs):
        sel = pid == i
        if sel.any():
            alb[sel] = sample_bilinear(t, a[..., 0][sel] * t.shape[1], (1 - a[..., 1][sel]) * t.shape[0])
    Lr = E.light(np.nan_to_num(n).reshape(-1, 3).astype(np.float32), sc.rig, sc.sun).reshape(H, W, 3)
    return G.lin_to_srgb(np.clip(alb * Lr, 0, 1)), pid >= 0


def rest_de(lid: str, sc) -> dict:
    """Mean dE76 (CIELAB) inside the layer's native mask between the HoMM3 rest picture and each candidate's layer
    alone at rest (seed = the installed candidate)."""
    L = SC.layers()[lid]
    paint, _ = rest_painting(L, 1)
    full = np.zeros((H, W, 3), np.float32)
    full[:paint.shape[0], :paint.shape[1]] = paint
    mask = frame_mask(L)
    lab = lambda x: cv2.cvtColor(np.clip(x, 0, 1).astype(np.float32), cv2.COLOR_RGB2LAB)
    out = {}
    for tagn, d in (("seed", seed_stage()), ("t2", S.STAGE)):
        rec, cov = rest_recon(d, lid, sc)
        img = full.copy()
        img[cov] = rec[cov]
        de = np.linalg.norm(lab(img) - lab(full), axis=-1)
        out[tagn] = {"dE76": round(float(de[mask].mean()), 2), "covered": round(float(cov[mask].mean()), 3)}
    return out


def select(layers: list[str]) -> None:
    """Per-layer mix (user decision 2026-09-29): every staged layer keeps its Meshy body unless BROKEN names it
    (judged by eye at the sweeps in layer_review); a broken layer goes back to the seed's relief (its bins and rows
    verbatim). Rest dE76 against the painting (seed and T2) is recorded as a diagnostic only, never a gate.
    Run after stage."""
    if not S.CANDIDATE or S.CANDIDATE == SEED:
        raise SystemExit(f"select: set TOWN_FULL3D_CANDIDATE (never {SEED})")
    sc = S.Scene()
    rp = S.WORK / "t2_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    seed_rows = json.loads((seed_stage() / "rows.json").read_text(encoding="utf-8"))
    for lid in layers:
        if lid not in rep:
            raise SystemExit(f"select: {lid} not staged")
        if rep[lid].get("keptSeed"):
            print(lid, "already on the seed relief:", rep[lid]["decision"])
            continue
        d = rest_de(lid, sc)
        broken = lid in BROKEN
        rep[lid]["restDE"] = d
        rep[lid]["keptSeed"] = broken
        rep[lid]["decision"] = BROKEN[lid] if broken else SWEEP_NOTES.get(lid, "Meshy body (default)")
        print(lid, d, "seed relief" if broken else "T2", "-", rep[lid]["decision"], flush=True)
        if broken:
            pf = S.PREFIX + lid
            for f in (S.STAGE / pf).glob(f"Mesh_Body*_{lid}*"):
                f.unlink()
            for f in (seed_stage() / pf).glob(f"Mesh_Body_{lid}*"):
                shutil.copy2(f, S.STAGE / pf / f.name)
            rows[pf]["bins"] = seed_rows[pf]["bins"]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    S.write_catalog(sc, carry="fresh")
    cat_p = S.OUT / "catalog.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    cat["t2Buildings"] = t2_catalog_block(rep, "t2")
    cat_p.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ layer review
LAYER_REVIEW = IB.OUTD / "_layer_review"
REVIEW_POSES = ("rest", "sweep_left", "sweep_right", "sweep_high")


def _stage_pieces(stage_dir: Path, prefabs: list[str], sc) -> list:
    """(name, P, n, uv, tris, img, unlit) of the bins rows.json names in a stage dir (prefab frame -> world)."""
    rows = json.loads((stage_dir / "rows.json").read_text(encoding="utf-8"))
    out = []
    for pf in prefabs:
        named = {b["name"] for b in rows.get(pf, {}).get("bins", [])}
        for mb in sorted((stage_dir / pf).glob("*.bytes")):
            tex = mb.with_name(mb.stem + "_albedo.png")
            if mb.stem not in named or not tex.is_file():
                continue
            v, n, uv, subs = S.read_bin(mb)
            if mb.stem == "Sky_Drift":
                import town_full3d_sky as SKY
                v, n = SKY.holder_to_prefab(v, n, pf)
            P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
            nw = n.astype(np.float64) @ sc.C.T
            out.append((f"{pf}/{mb.stem}", P.astype(np.float32), nw.astype(np.float32), uv,
                        np.concatenate(subs), np.asarray(Image.open(tex)), mb.stem.startswith("Sky_")))
    return out


def layer_review(layers: list[str]) -> list[str]:
    """Offline review (lane preview shading, Cull Back on the Mesh_Body* pieces as the game draws them): the
    environment plus ONE layer, seed relief vs this candidate, at rest and the three sweeps, cropped to the layer;
    one png per layer in LAYER_REVIEW. Used to judge by eye which Meshy bodies are broken (BROKEN). Not an editor
    render: the editor renders only cover the full / start / anim build states."""
    import moderngl
    import stronghold_full3d_preview as PV
    sc = S.Scene()
    pans = S.pan_cams(sc)
    cams = {"rest": sc.cam, **{k: pans[k] for k in REVIEW_POSES[1:]}}
    R = PV.Renderer(sc.rig, sc.sun, W, H)
    for pc in _stage_pieces(S.STAGE, [S.ENV_KEY], sc):
        R.add("env/" + pc[0], *pc[1:6], unlit=pc[6])
    boxes = {}
    for tagn, d in (("seed", seed_stage()), ("t2", S.STAGE)):
        for pc in _stage_pieces(d, [S.PREFIX + l for l in layers], sc):
            R.add(f"{tagn}/{pc[0]}", *pc[1:6], unlit=pc[6])
            lid = pc[0].split("/")[0][len(S.PREFIX):]
            boxes.setdefault(lid, []).append(pc[1])
    R.ctx.front_face = "cw"   # PV.view mirrors handedness: the lane's outward winding is clockwise on screen

    def shot(cam, keep: str) -> Image.Image:
        mvp = PV.perspective(cam["fov"], W / H, 2.0, T.DOME_R * 1.2) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                              cam["right"])
        R.fbo.use()
        R.ctx.clear(1.0, 0.0, 1.0, 1.0)
        p = R.prog
        p["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for k in ("sunColor", "ambSky", "ambEq", "ambGround"):
            p[k].value = tuple(float(x) for x in R.rig[k])
        p["sunDir"].value = tuple(float(x) for x in R.sun)
        p["fillDir"].value = tuple(float(x) for x in R.rig.get("fillDir", (0, -1, 0)))
        p["fillColor"].value = tuple(float(x) for x in R.rig.get("fillColor", (0, 0, 0)))
        for pc in sorted(R.pieces, key=lambda q: not q["unlit"]):
            if not (pc["name"].startswith("env/") or pc["name"].startswith(keep)):
                continue
            p["unlit"].value = int(pc["unlit"])
            p["cutout"].value = float(pc["cutout"])
            (R.ctx.disable if pc["unlit"] else R.ctx.enable)(moderngl.DEPTH_TEST)
            (R.ctx.enable if "/Mesh_Body" in pc["name"] else R.ctx.disable)(moderngl.CULL_FACE)
            pc["tex"].use(0)
            p["tex"].value = 0
            pc["vao"].render()
        R.ctx.disable(moderngl.CULL_FACE)
        R.ctx.copy_framebuffer(R.out, R.fbo)
        return Image.fromarray(np.frombuffer(R.out.read(components=3), np.uint8).reshape(H, W, 3)[::-1].copy())

    LAYER_REVIEW.mkdir(parents=True, exist_ok=True)
    outs = []
    for lid in layers:
        if lid not in boxes:
            continue
        Pall = np.concatenate(boxes[lid]).astype(np.float64)
        paint, _ = rest_painting(SC.layers()[lid], 1)
        pim = Image.fromarray((np.clip(paint, 0, 1) * 255).astype(np.uint8))
        row = []
        for pose in REVIEW_POSES:
            cam = cams[pose]
            px, py, zc = T.project(cam, Pall)
            ok = zc > 0
            bx = (px[ok].min() - 24, py[ok].min() - 24, px[ok].max() + 24, py[ok].max() + 24)
            bx = tuple(int(v) for v in (max(bx[0], 0), max(bx[1], 0), min(bx[2], W), min(bx[3], H)))
            if pose == "rest":
                row.append(_lab(pim.crop(bx), f"{lid} painting"))
            for tagn in ("seed", "t2"):
                row.append(_lab(shot(cam, f"{tagn}/{S.PREFIX}{lid}/").crop(bx), f"{tagn} {pose}"))
        hh = 300
        img = _grid([[i.resize((max(1, round(i.width * hh / i.height)), hh), Image.LANCZOS) for i in row]])
        op = LAYER_REVIEW / f"{lid}.png"
        img.save(op)
        outs.append(str(op))
        print(op, flush=True)
    return outs


# ------------------------------------------------------------------------------------------------ sheet
REVIEW_OUT = SC.ROOT / "artifacts" / "claude_takeover_20260927" / "review" / "homm3_inferno_t2_buildings.png"
POSES = (("rest", "full3d_full.png", None), ("sweep_left", "pan_sweep_left.png", "sweep_left"),
         ("sweep_right", "pan_sweep_right.png", "sweep_right"), ("sweep_high", "pan_sweep_high.png", "sweep_high"))


def _lab(img: Image.Image, text: str) -> Image.Image:
    from PIL import ImageDraw
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, min(img.width, 10 + 7 * len(text)), 16), fill=(0, 0, 0))
    d.text((4, 3), text, fill=(255, 255, 0))
    return img


def _grid(rows: list[list[Image.Image]], gap: int = 6) -> Image.Image:
    wd = max(sum(i.width for i in r) + gap * (len(r) - 1) for r in rows)
    ht = sum(max(i.height for i in r) for r in rows) + gap * (len(rows) - 1)
    out = Image.new("RGB", (wd, ht), (30, 30, 30))
    y = 0
    for r in rows:
        x = 0
        for i in r:
            out.paste(i, (x, y))
            x += i.width + gap
        y += max(i.height for i in r) + gap
    return out


def sheet() -> None:
    """painting | before (fix_v2, the installed candidate) | after (this candidate), both editor renders, at rest and
    the three sweep poses; then zooms of every meshed building of the full state at each pose (crop = the placed
    mesh's projected box in that pose's camera)."""
    if not S.CANDIDATE or S.CANDIDATE == SEED:
        raise SystemExit("sheet: set TOWN_FULL3D_CANDIDATE to the after candidate")
    before = SC.DATA / "candidates" / SEED / "renders"
    after = S.RENDERS
    for d in (before, after):
        if not (d / "render_report.txt").is_file():
            raise SystemExit(f"sheet: no editor renders in {d}")
    ref = S.homm3_reference(S.STATES["full"])
    sc = S.Scene()
    pans = S.pan_cams(sc)
    cams = {p: (sc.cam if key is None else pans[key]) for p, _, key in POSES}
    big = []
    for p, fn, _ in POSES:
        cells = [_lab(Image.open(before / fn).resize((960, 540), Image.LANCZOS), f"before (fix_v2 installed) {p}"),
                 _lab(Image.open(after / fn).resize((960, 540), Image.LANCZOS), f"after ({S.CANDIDATE}) {p}")]
        big.append([_lab(ref.resize((960, 540), Image.LANCZOS), "HoMM3 painting (full), x1.8 top-left")] + cells)
    zooms = []
    rep = json.loads((S.WORK / "t2_report.json").read_text(encoding="utf-8"))
    for lid in S.STATES["full"]:
        if lid not in rep or rep[lid].get("keptSeed"):
            continue
        P = placed(lid, "t2")["P"]
        L = SC.layers()[lid]
        x0, y0 = L["reference_x"] / 2, L["reference_y"] / 2
        rbox = (x0 - 20, y0 - 20, x0 + L["reference_w"] / 2 + 20, y0 + L["reference_h"] / 2 + 20)
        row = [_lab(ref.crop(tuple(int(v) for v in rbox)), f"{lid} painting")]
        for p, fn, _ in POSES:
            px, py, zc = T.project(cams[p], P)
            ok = zc > 0
            if not ok.any():
                continue
            bx = (px[ok].min() - 20, py[ok].min() - 20, px[ok].max() + 20, py[ok].max() + 20)
            bx = tuple(int(v) for v in (max(bx[0], 0), max(bx[1], 0), min(bx[2], W), min(bx[3], H)))
            if bx[2] - bx[0] < 8 or bx[3] - bx[1] < 8:
                continue
            for tagn, d in (("before", before), ("after", after)):
                row.append(_lab(Image.open(d / fn).convert("RGB").crop(bx), f"{tagn} {p}"))
        hh = 220
        zooms.append([i.resize((max(1, round(i.width * hh / i.height)), hh), Image.LANCZOS) for i in row])
    REVIEW_OUT.parent.mkdir(parents=True, exist_ok=True)
    _grid(big).save(REVIEW_OUT)
    zp = REVIEW_OUT.with_name(REVIEW_OUT.stem + "_zooms.png")
    _grid(zooms).save(zp)
    print(REVIEW_OUT, zp)
