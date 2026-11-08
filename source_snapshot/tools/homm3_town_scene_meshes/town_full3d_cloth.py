#!/usr/bin/env python3
"""Full-3D towns: banners and flags wave as cloth on the building meshes themselves (Hex/Lit FLAG vertex wave).

    set TOWN_FULL3D_FACTION=castle & set TOWN_FULL3D_CANDIDATE=<cand>
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py plan     # masks + banner frames, writes nothing staged
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py apply    # stage Mesh_Cloth_* bins, rewrite the catalog
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py check [--base <cand>]   # zero-streak with the wave on

Why (user verdict 2026-10-01: "The castle flag waving effect is also inadequate"): town_t2_anim_pass's `cloth`
recipe was a pair of VfxUber particles (a dark "fold" and an additive "sheen" system) laid over the painted banners
inside the DEF's widened change mask. Nothing on the mesh moved: the banner silhouette and its fly end were fixed,
the noise bands crossed the blurred mask onto the wall around each banner, and the particles sat at one group depth,
so at a pan they slid off banners standing at other depths. It read as flickering shading, not as cloth.

Method (one pass, any town; the faction's recipe is RECIPES[faction]):
  1. cloth mask per layer, in the HoMM3 sprite: the DEF's animated patches (frames 1..) restricted to px that move
     across the frames (dilated), whose colour is the recipe's cloth colour (castle: the banner blue; the gold trim
     and heraldry inside it are taken by a near-blue closure and a hole fill). One connected component = one banner;
     a component much wider than its siblings is split at its column-coverage gaps (two banners touching via a tent).
  2. mesh surgery, no new geometry: the faces of the layer's rest-front bins (Mesh_Body_<l> = the painted Meshy front,
     Mesh_BodyRest_<l> = the seed residual) that the rest camera draws inside a banner's mask are COPIED into one bin
     per banner, Mesh_Cloth_<l>_<k>, with a packed crop of their source textures. The copy is moved toward the
     camera along each vertex's own rest ray (the rest projection is unchanged) by the wave's out-of-plane amplitude
     plus a depth epsilon, so the wave never dips behind the static surface. The source faces stay where they were
     (static backing) and their texels are darkened to a cloth-shadow tone: whatever the moving copy uncovers is the
     banner's shadow on the wall, never a hole, a ghost banner or a curtain.
  3. per-vertex weight in COLOR.r (Hex/Lit FLAG reads COLOR.x only): 0 on the hoist band (the top edge it hangs from),
     rising as ((s - HOIST) / (1 - HOIST)) ** WEIGHT_POW with s the normalised distance down the banner, times a small
     across-width skew (1 + SKEW * a * s, a = -1..1 across): the two fly corners lag each other, a secondary twist the
     single native sine cannot make by itself. The weight is a pure function of position, so coincident vertices of
     the triangle soup get identical displacement: the copy cannot tear.
  4. the wave is the installed Hex/Lit FLAG variant, unchanged: posWS += _FlagPower * sin(dot(posWS, _FlagDirection)
     + _Time.y * _FlagSpeed) * COLOR.r, declared per piece in the prefab frame (catalog clothLook) and converted to
     world space by the runtime (Homm3TownScene3d: power by the renderer's localToWorld, direction by its inverse
     transpose). Per banner: power = AMP * H * (lateral_w + OUT * n) (lateral_w the in-plane horizontal, oriented
     downwind; n the banner's outward normal); direction = -k_len * down + k_wind * wind (a travelling sine from hoist
     to fly whose fronts also travel downwind across the town: neighbouring banners and buildings are offset in phase
     by where they stand); speed = 2 pi / PERIOD_S with a fixed per-banner jitter so banners drift apart. One wind
     vector (WIND_LOCAL, the prefab frame) for the whole town. Normals are not rewritten by the native wave; the
     displacement is a few % of the banner, so the static normals stay plausible and lighting is the town's own Hex/Lit.
  5. the old fold/sheen Fx_Glow_ groups of those layers are removed; animationAudit names the cloth pieces.

The pass is applied last, on a copy (refused when the candidate already stages Mesh_Cloth_ bins, or when a cloth
layer's source bins are gone): any later restage of buildings or effects must re-run it.
Proof tier of apply: generated artifact. The editor render (Homm3TownLabHexLit's FLAG replica, the same world-space
conversion as the runtime) is a lab render; how it looks in game is unproven until seen there.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes, label

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402

SCHEMA = "town_full3d_cloth.v1"
PIECE = "Mesh_Cloth_"
HOIST = 0.06            # share of the banner length at the top that stays pinned (r = 0)
WEIGHT_POW = 1.4        # weight ramp exponent down the banner (fly end moves most)
SKEW = 0.25             # across-width weight skew at the fly end (secondary twist)
AMP = 0.085             # peak in-plane displacement at the fly end, share of the banner length
OUT = 0.35              # out-of-plane share of the displacement vector
WAVELEN = 1.15          # travelling wavelength along the banner, in banner lengths
WIND_WAVELEN = 32.0     # gust wavelength across the town (prefab units)
PERIOD_S = 1.7          # wave period, s
SPEED_JITTER = 0.1      # +- share of the speed per banner (fixed hash)
EPS = 0.08              # prefab units: the copy's minimum lead over the static backing along the rest ray
BACK_SHADE = 0.5        # backing texel multiplier (cloth shadow on the wall)
BACK_DESAT = 0.35       # backing desaturation toward its own luminance
PAD = 4                 # texels around each packed crop
MIN_COMP_PX = 30        # sprite px: smaller cloth components are noise
DEPTH_BIN = 0.2         # banner lengths: the depth histogram bin that finds the drawn banner surface
DEPTH_KEEP = 1.0        # banner lengths: a cloth face's vertices lie within this ray distance of that surface
VERTEX_SLACK_PX = 4     # frame px: a cloth face's vertices project at most this far outside its banner's mask
SOURCE_BINS = ("Mesh_Body_{l}", "Mesh_BodyRest_{l}")
WIND_LOCAL = (1.0, 0.0, 0.35)   # prefab frame (x right, y up, z forward): the wind blows to the right and away

# faction -> recipe. layers: the DEF-animated layers whose motion is cloth (decided from the DEF frames, recorded in the
# town's doc); colour: the cloth colour rule (COLOUR_RULES).
RECIPES = {
    "castle": {"layers": ["tbcshall", "tbcshal2", "tbcshal3", "tbcsdw_5", "tbcsdw_5_2"], "colour": "blue_gold"},
}


def rule_blue_gold(rgb: np.ndarray, region: np.ndarray) -> np.ndarray:
    """Castle banners: the heraldic blue, plus the gold trim / griffin next to it (closure + hole fill)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    blue = (b > r + 25) & (b > g + 10) & region
    m = cv2.morphologyEx(blue.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    m = binary_fill_holes(m)
    gold = (r > 140) & (g > 100) & (b < 120) & (r > b + 50) & region
    near = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return binary_fill_holes(m | (gold & near)) & region


COLOUR_RULES = {"blue_gold": rule_blue_gold}


def recipe() -> dict:
    r = RECIPES.get(SC.FACTION)
    if r is None:
        raise SystemExit(f"cloth: no recipe for faction {SC.FACTION} (RECIPES)")
    return r


def def_frames(lid: str) -> np.ndarray:
    d = SC.LAYERS / "anims" / lid
    fs = sorted(d.glob("frame_*.png"))
    if len(fs) < 3:
        raise SystemExit(f"cloth: {lid}: the HoMM3 DEF has {len(fs)} frames under {d} (the recipe needs an animated DEF)")
    return np.stack([np.asarray(Image.open(f).convert("RGBA"), np.float32) for f in fs])


def split_wide(comp: np.ndarray, med_w: float) -> list[np.ndarray]:
    """A component much wider than the median banner is split at its column-coverage gaps."""
    ys, xs = np.nonzero(comp)
    w = xs.max() - xs.min() + 1
    if w <= 1.5 * med_w:
        return [comp]
    col = comp.sum(0).astype(np.float64)
    lo = col <= 0.3 * col.max()
    parts, cur = [], np.zeros_like(comp)
    for x in range(xs.min(), xs.max() + 1):
        if lo[x]:
            if cur.sum() >= MIN_COMP_PX:
                parts.append(cur)
            cur = np.zeros_like(comp)
            continue
        cur[:, x] = comp[:, x]
    if cur.sum() >= MIN_COMP_PX:
        parts.append(cur)
    return parts or [comp]


def banner_masks(lid: str, rule: str) -> tuple[list[np.ndarray], dict]:
    """Sprite-space boolean masks, one per banner, and their stats."""
    a = def_frames(lid)
    anim = a[1:, ..., 3].max(0) > 0
    moving = cv2.dilate(((a[1:, ..., :3].std(0).max(-1) > 8) & anim).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    m = COLOUR_RULES[rule](a[0][..., :3], anim & moving) & (a[0][..., 3] > 0) & anim
    lab, n = label(m)
    comps = [lab == i for i in range(1, n + 1) if (lab == i).sum() >= MIN_COMP_PX]
    if not comps:
        raise SystemExit(f"cloth: {lid}: no cloth px under rule {rule}")
    med_w = float(np.median([np.ptp(np.nonzero(c)[1]) + 1 for c in comps]))
    out = []
    for c in comps:
        out.extend(split_wide(c, med_w))
    out.sort(key=lambda c: float(np.nonzero(c)[1].mean()))
    return out, {"spritePx": int(m.sum()), "banners": len(out), "medianWidthPx": med_w}


def to_frame(L: dict, mask: np.ndarray) -> np.ndarray:
    """Sprite mask -> 1920x1080 frame mask (x1.8 nearest, placed as SC.sprite_frame places the sprite)."""
    h, w = mask.shape
    big = cv2.resize(mask.astype(np.uint8), (round(w * SC.SCALE), round(h * SC.SCALE)), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((SC.H, SC.W), bool)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    hh, ww = min(big.shape[0], SC.H - y0), min(big.shape[1], SC.W - x0)
    out[y0:y0 + hh, x0:x0 + ww] = big[:hh, :ww] > 0
    return out


def project_local(cam: dict, v: np.ndarray):
    """Prefab-frame vertices (the rest camera at the origin, x right, y up, z forward) -> frame px."""
    t = math.tan(math.radians(cam["fov"]) / 2)
    z = v[:, 2]
    px = (v[:, 0] / (z * t * SC.W / SC.H) + 1) * 0.5 * SC.W
    py = (1 - v[:, 1] / (z * t)) * 0.5 * SC.H
    return px, py, z


def hash01(*keys) -> float:
    return int(hashlib.sha256("|".join(map(str, keys)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _norm(v):
    v = np.asarray(v, np.float64)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def pack_crops(crops: list[tuple[np.ndarray, tuple[int, int, int, int]]]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Stack texture crops vertically (RGBA uint8). Returns the atlas and each crop's (ox, oy) in it."""
    W = max(c.shape[1] for c, _ in crops)
    H = sum(c.shape[0] for c, _ in crops)
    atlas = np.zeros((H, W, 4), np.uint8)
    offs, y = [], 0
    for c, _ in crops:
        atlas[y:y + c.shape[0], :c.shape[1]] = c
        offs.append((0, y))
        y += c.shape[0]
    return atlas, offs


def plan(write: bool) -> dict:
    rc = recipe()
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if any(b["name"].startswith(PIECE) for r in rows.values() for b in r["bins"]):
        raise SystemExit("cloth: the candidate already stages Mesh_Cloth_ bins (apply on a fresh copy)")
    lays = SC.layers()
    cam0 = {**sc.cam}
    up = _norm(sc.local_dir(np.array([[0.0, 1.0, 0.0]]))[0])
    wind = _norm(WIND_LOCAL)
    wind_h = _norm(wind - (wind @ up) * up)
    report = {"schema": SCHEMA, "faction": SC.FACTION, "colourRule": rc["colour"], "windLocal": [float(x) for x in wind],
              "params": {"hoist": HOIST, "weightPow": WEIGHT_POW, "skew": SKEW, "amp": AMP, "out": OUT,
                         "wavelen": WAVELEN, "windWavelen": WIND_WAVELEN, "periodS": PERIOD_S,
                         "speedJitter": SPEED_JITTER, "eps": EPS, "backShade": BACK_SHADE, "backDesat": BACK_DESAT},
              "layers": {}, "pieces": [],
              "proofTier": "generated artifact (mesh surgery + wave parameters); lab render / runtime separate"}
    new_bins: dict[str, list] = {}
    backing: dict[tuple[str, str], np.ndarray] = {}
    for lid in rc["layers"]:
        pk = S.PREFIX + lid
        if pk not in rows:
            raise SystemExit(f"cloth: recipe layer {lid} is not staged ({pk})")
        L = lays[lid]
        masks, mstat = banner_masks(lid, rc["colour"])
        fmasks = [to_frame(L, m) for m in masks]
        lab = np.zeros((SC.H, SC.W), np.int32)
        for k, fm in enumerate(fmasks):
            lab[fm & (lab == 0)] = k + 1
        # the layer's rest-front bins, rasterised together: a face is cloth where the rest camera draws it in a mask
        srcs = []
        for tmpl in SOURCE_BINS:
            nm = tmpl.format(l=lid)
            row = next((b for b in rows[pk]["bins"] if b["name"] == nm), None)
            if row is None:
                continue
            if row.get("pos") or row.get("rot"):
                raise SystemExit(f"cloth: {lid}/{nm} is a posed bin; the cloth pass reads prefab-frame vertices")
            v, n, uv, subs = S.read_bin(S.STAGE / pk / f"{nm}.bytes")
            srcs.append({"name": nm, "row": row, "v": np.asarray(v, np.float64), "n": np.asarray(n, np.float64),
                         "uv": np.asarray(uv, np.float64), "F": np.concatenate(subs).reshape(-1, 3)})
        if not srcs:
            raise SystemExit(f"cloth: {lid}: none of {SOURCE_BINS} is staged")
        Pw = np.concatenate([sc.cpos + (s["v"] / sc.scale) @ sc.C.T for s in srcs])
        offs = np.cumsum([0] + [len(s["v"]) for s in srcs])
        Fall = np.concatenate([s["F"] + o for s, o in zip(srcs, offs[:-1])])
        fsrc = np.concatenate([np.full(len(s["F"]), i) for i, s in enumerate(srcs)])
        fbase = np.concatenate([[0], np.cumsum([len(s["F"]) for s in srcs])])
        z, fid = TP.zbuffer(cam0, Pw, Fall, sup=1)
        ok = (fid >= 0) & (lab > 0)
        face_lab = np.zeros(len(Fall), np.int32)
        # majority label of the px each face wins
        ids, labs = fid[ok], lab[ok]
        if len(ids):
            order = np.lexsort((labs, ids))
            ids, labs = ids[order], labs[order]
            uniq, start = np.unique(ids, return_index=True)
            for j, f in enumerate(uniq):
                e = start[j + 1] if j + 1 < len(start) else len(ids)
                face_lab[f] = np.bincount(labs[start[j]:e]).argmax()
        # faces too small to win a px: centroid inside a mask and on the drawn surface there
        allv = np.concatenate([s["v"] for s in srcs])
        px, py, zc = project_local(cam0, allv)
        cx, cy = px[Fall].mean(1), py[Fall].mean(1)
        czz = zc[Fall].mean(1)
        ix = np.clip(cx.astype(int), 0, SC.W - 1)
        iy = np.clip(cy.astype(int), 0, SC.H - 1)
        zdrawn = z[iy, ix] * sc.scale     # zbuffer z is painting metres; prefab z = metres * scale
        small = (face_lab == 0) & (lab[iy, ix] > 0) & np.isfinite(zdrawn) & (czz <= zdrawn * 1.01 + 1e-6)
        face_lab[small] = lab[iy, ix][small]
        # long sliver faces that win a few banner px but reach far outside it are not cloth: every vertex of a cloth
        # face projects inside its own banner's mask, dilated by VERTEX_SLACK_PX
        vx = np.clip(np.round(px).astype(int), 0, SC.W - 1)
        vy = np.clip(np.round(py).astype(int), 0, SC.H - 1)
        inside = np.zeros(len(Fall), bool)
        for k in range(len(masks)):
            dm = cv2.dilate(fmasks[k].astype(np.uint8), np.ones((2 * VERTEX_SLACK_PX + 1,) * 2, np.uint8)) > 0
            sel = face_lab == k + 1
            inside[sel] = dm[vy[Fall[sel]], vx[Fall[sel]]].all(1)
        lrep_dropped = int(((face_lab > 0) & ~inside).sum())
        face_lab[~inside] = 0
        # a banner is thin in depth: keep the faces near the depth the rest camera actually draws there (the mode of
        # the drawn faces' ray distance, weighted by the px each wins); the hedge / wall behind it and ray-long residual
        # faces that leak through the mask stay static
        won = np.bincount(fid[fid >= 0], minlength=len(Fall)).astype(np.float64)
        vdist = np.linalg.norm(allv, axis=1)[Fall]
        lrep_depth = 0
        for k in range(len(masks)):
            sel = np.nonzero(face_lab == k + 1)[0]
            if len(sel) < 8:
                continue
            hgt = allv[np.unique(Fall[sel].ravel())] @ up
            hb = max(float(np.ptp(hgt)), 1e-6)
            c = vdist[sel].mean(1)
            bw = DEPTH_BIN * hb
            bins = np.floor((c - c.min()) / bw).astype(int)
            mode = c.min() + (np.argmax(np.bincount(bins, weights=won[sel] + 1e-3)) + 0.5) * bw
            far = (np.abs(vdist[sel] - mode) > DEPTH_KEEP * hb).any(1)
            face_lab[sel[far]] = 0
            lrep_depth += int(far.sum())
        lrep = {"mask": mstat, "banners": [], "sliverFacesDropped": lrep_dropped, "offDepthFacesDropped": lrep_depth}
        for k in range(len(masks)):
            fsel = np.nonzero(face_lab == k + 1)[0]
            if len(fsel) < 8:
                lrep["banners"].append({"k": k, "faces": int(len(fsel)), "skipped": "too few faces"})
                continue
            name = f"{PIECE}{lid}_b{k}"
            # banner frame from its own vertices (prefab frame)
            vi = np.unique(Fall[fsel].ravel())
            V = allv[vi]
            hgt = V @ up
            ytop, Hb = float(hgt.max()), float(np.ptp(hgt))
            if Hb <= 1e-6:
                raise SystemExit(f"cloth: {lid} banner {k} has no height")
            tri = allv[Fall[fsel]]
            an = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).sum(0)
            nrm = _norm(an - (an @ up) * up)
            if nrm @ (-V.mean(0)) < 0:
                nrm = -nrm                                    # outward = toward the camera side
            lat = _norm(np.cross(up, nrm))
            if lat @ wind_h < 0:
                lat = -lat
            across = V @ lat
            ac, aw = float(across.mean()), max(float(np.ptp(across)) / 2, 1e-6)
            down = -up
            kl = 2 * math.pi / (WAVELEN * Hb)
            kw = 2 * math.pi / WIND_WAVELEN
            power = AMP * Hb * _norm(lat + OUT * nrm) * math.sqrt(1 + OUT * OUT)
            direction = -kl * down + kw * wind_h
            speed = 2 * math.pi / PERIOD_S * (1 + SPEED_JITTER * (2 * hash01(SC.FACTION, lid, k) - 1))
            # copy the faces per source, crop + pack their texels, weight + pre-offset their vertices
            crops, parts = [], []
            for si, s in enumerate(srcs):
                fs = fsel[fsrc[fsel] == si] - fbase[si]
                if not len(fs):
                    continue
                tex = np.asarray(Image.open(S.STAGE / pk / f"{s['name']}_albedo.png").convert("RGBA"))
                th, tw = tex.shape[:2]
                lv = np.unique(s["F"][fs].ravel())
                tx, ty = s["uv"][lv, 0] * tw, (1 - s["uv"][lv, 1]) * th
                x0, y0 = max(int(math.floor(tx.min())) - PAD, 0), max(int(math.floor(ty.min())) - PAD, 0)
                x1, y1 = min(int(math.ceil(tx.max())) + PAD, tw), min(int(math.ceil(ty.max())) + PAD, th)
                crops.append((tex[y0:y1, x0:x1].copy(), (x0, y0, tw, th)))
                parts.append((si, fs, lv))
                # backing: the source faces' texels, darkened in place (written after every banner of the layer)
                key = (pk, s["name"])
                if key not in backing:
                    backing[key] = np.zeros((th, tw), np.uint8)
                pts = np.stack([s["uv"][:, 0] * tw, (1 - s["uv"][:, 1]) * th], 1)
                for f in s["F"][fs]:
                    cv2.fillConvexPoly(backing[key], np.round(pts[f] * 4).astype(np.int32), 1, lineType=cv2.LINE_8,
                                       shift=2)
            atlas, aoffs = pack_crops(crops)
            AH, AW = atlas.shape[:2]
            vs, ns, uvs, rs, tris = [], [], [], [], []
            base = 0
            for (si, fs, lv), (crop, (x0, y0, tw, th)), (ox, oy) in zip(parts, crops, aoffs):
                s = srcs[si]
                remap = -np.ones(len(s["v"]), np.int64)
                remap[lv] = np.arange(len(lv)) + base
                v = s["v"][lv].copy()
                sdown = np.clip((ytop - v @ up) / Hb, 0, 1)
                w = np.clip((sdown - HOIST) / (1 - HOIST), 0, 1) ** WEIGHT_POW
                a = np.clip((v @ lat - ac) / aw, -1, 1)
                w = w * (1 + SKEW * a * sdown)
                w = np.clip(w / (1 + SKEW), 0, 1)
                # lead over the backing along the rest ray: the out-of-plane half-swing plus EPS, over the ray's cosine
                ray = v / np.linalg.norm(v, axis=1, keepdims=True)
                cos = np.maximum(np.abs(ray @ nrm), 0.3)
                lead = (abs(power @ nrm) * w + EPS) / cos
                v = v - ray * lead[:, None]
                u = (s["uv"][lv, 0] * tw - x0 + ox) / AW
                vv = 1 - ((1 - s["uv"][lv, 1]) * th - y0 + oy) / AH
                vs.append(v); ns.append(s["n"][lv]); uvs.append(np.stack([u, vv], 1)); rs.append(w)
                tris.append(remap[s["F"][fs]])
                base += len(lv)
            V2 = np.concatenate(vs)
            T2 = np.concatenate(tris).astype(np.int32)
            R2 = np.concatenate(rs)
            mx = float(np.abs(power).max())
            piece = {"prefab": pk, "layerId": lid, "piece": name, "banner": k, "faces": int(len(T2)),
                     "verts": int(len(V2)), "sources": [srcs[si]["name"] for si, _, _ in parts],
                     "heightUnits": Hb, "power": [float(x) for x in power], "direction": [float(x) for x in direction],
                     "speed": float(speed), "normal": [float(x) for x in nrm], "lateral": [float(x) for x in lat],
                     "weightMax": float(R2.max()), "weightMean": float(R2.mean()), "peakDispUnits": mx,
                     "leadMaxUnits": float(((abs(power @ nrm) + EPS) / 0.3)), "atlas": [AW, AH],
                     "colors": f"{S.ASSET_ROOT}/{pk}/{name}.vcol"}
            report["pieces"].append(piece)
            lrep["banners"].append({k2: piece[k2] for k2 in ("banner", "piece", "faces", "verts", "heightUnits",
                                                               "peakDispUnits", "speed")})
            new_bins.setdefault(pk, []).append((name, V2, np.concatenate(ns), np.concatenate(uvs), T2, R2, atlas,
                                                srcs[0]["row"]))
        report["layers"][lid] = lrep
        print(json.dumps({"layer": lid, **mstat, "cloth": [(b.get("piece"), b.get("faces")) for b in lrep["banners"]]}))
    if not report["pieces"]:
        raise SystemExit("cloth: no banner produced a cloth piece")
    if not write:
        return report
    # ---- write: bins, textures, colours, backing, rows (cloth bins in, fold/sheen out)
    for pk, items in new_bins.items():
        for name, V2, N2, UV2, T2, R2, atlas, srow in items:
            S.write_bin(S.STAGE / pk / f"{name}.bytes", V2, N2, UV2, [T2])
            Image.fromarray(atlas).save(S.STAGE / pk / f"{name}_albedo.png")
            col = np.zeros((len(R2), 4), np.float32)
            col[:, 0] = R2
            col[:, 1:] = 1.0
            (S.STAGE / pk / f"{name}.vcol").write_bytes(col.tobytes())
            row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{pk}/{name}.bytes",
                   "texture": f"{S.ASSET_ROOT}/{pk}/{name}_albedo.png", "kind": "lit",
                   "maxSize": int(max(atlas.shape[:2])), "colors": f"{S.ASSET_ROOT}/{pk}/{name}.vcol",
                   "boundsPad": float(np.abs(next(p for p in report["pieces"] if p["piece"] == name)["power"]).max()
                                      * 1.05)}
            for k2 in ("mipBias", "aniso"):
                if srow.get(k2):
                    row[k2] = srow[k2]
            rows[pk]["bins"].append(row)
    for (pk, nm), m in backing.items():
        p = S.STAGE / pk / f"{nm}_albedo.png"
        im = np.asarray(Image.open(p).convert("RGBA")).copy()
        sel = m > 0
        rgb = im[..., :3].astype(np.float32)
        lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        rgb[sel] = (rgb[sel] * (1 - BACK_DESAT) + lum[sel, None] * BACK_DESAT) * BACK_SHADE
        im[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
        mode = Image.open(p).mode
        Image.fromarray(im if mode == "RGBA" else im[..., :3]).save(p)
        report.setdefault("backing", []).append({"prefab": pk, "bin": nm, "texels": int(sel.sum())})
    removed = []
    for lid in rc["layers"]:
        pk = S.PREFIX + lid
        keep = [g for g in rows[pk].get("particles", []) if not g["name"].startswith("Fx_Glow_")]
        removed += [g["name"] for g in rows[pk].get("particles", []) if g["name"].startswith("Fx_Glow_")]
        rows[pk]["particles"] = keep
    report["removedEffects"] = removed
    for p in report["pieces"]:
        p["colorsSha256"] = hashlib.sha256((S.STAGE / p["prefab"] / f"{p['piece']}.vcol").read_bytes()).hexdigest()
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["cloth"] = report
    rp.write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    import town_t2_anim_pass as AP
    AP.refresh_catalog()
    (S.WORK / "cloth.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


LOOK_KEYS = ("prefab", "layerId", "piece", "power", "direction", "speed", "colorsSha256", "verts", "heightUnits")
SEQ_POSES = ("", "sweep_left", "sweep_right", "sweep_high", "orbit_y+0_p+14")   # "" = the rest pose
SEQ_FRAMES = 8


def catalog_block(rows: dict, rep: dict) -> dict | None:
    """write_catalog's hook (opt-in: the stage report's "cloth" block). Fails closed when a declared piece is no longer
    staged or its colour file changed, or when a cloth layer got its old fold/sheen groups back (a later fx restage):
    re-run apply on a fresh copy."""
    cl = rep.get("cloth")
    if not cl:
        stray = [f"{k}/{b['name']}" for k, r in rows.items() for b in r["bins"] if b["name"].startswith(PIECE)]
        if stray:
            raise SystemExit(f"catalog: rows stage cloth pieces {stray[:4]} but the stage report has no cloth block")
        return None
    if cl.get("schema") != SCHEMA:
        raise SystemExit(f"catalog: stage report cloth is not {SCHEMA}")
    look = []
    for p in cl["pieces"]:
        row = next((b for b in rows.get(p["prefab"], {}).get("bins", []) if b["name"] == p["piece"]), None)
        vc = S.STAGE / p["prefab"] / f"{p['piece']}.vcol"
        if row is None or not vc.is_file() or hashlib.sha256(vc.read_bytes()).hexdigest() != p["colorsSha256"]:
            raise SystemExit(f"catalog: cloth piece {p['prefab']}/{p['piece']} is not staged as applied (re-run "
                             f"town_full3d_cloth.py apply on a fresh copy)")
        look.append({k: p[k] for k in LOOK_KEYS})
    for lid in cl["layers"]:
        back = [g["name"] for g in rows[S.PREFIX + lid].get("particles", []) if g["name"].startswith("Fx_Glow_")]
        if back:
            raise SystemExit(f"catalog: cloth layer {lid} stages {back} again (a later fx restage): re-run the cloth pass")
    declared = {f"{p['prefab']}/{p['piece']}" for p in look}
    stray = [f"{k}/{b['name']}" for k, r in rows.items() for b in r["bins"]
             if b["name"].startswith(PIECE) and f"{k}/{b['name']}" not in declared]
    if stray:
        raise SystemExit(f"catalog: rows stage undeclared cloth pieces {stray[:4]}")
    return {"schema": SCHEMA, "displacement": "Hex/Lit HEX_VERTEX_DISPLACEMENT_FLAG (_VertexDisplacementType 1)",
            "formula": "posWS += _FlagPower * sin(dot(posWS, _FlagDirection) + _Time.y * _FlagSpeed) * COLOR.r",
            "space": "prefab (the runtime converts: power by localToWorld, direction by its inverse transpose)",
            "windLocal": cl["windLocal"], "layers": sorted(cl["layers"]), "pieces": look,
            "removedEffects": cl.get("removedEffects", []), "params": cl["params"], "proofTier": cl["proofTier"],
            "method": "town_full3d_cloth.v1 (docs/homm3_town_cloth_wave.md)"}


def audit_rows(block: dict, audit: dict) -> dict:
    """animationAudit with each cloth layer's effects = its cloth pieces (kind clothWave, placement mesh)."""
    out = copy.deepcopy(audit)
    for lid in block["layers"]:
        row = out.get(lid)
        if row is None:
            raise SystemExit(f"catalog: cloth layer {lid} has no animationAudit row")
        row["effects"] = [p["piece"] for p in block["pieces"] if p["layerId"] == lid]
        row["kinds"] = ["clothWave"]
        row["placements"] = ["mesh"]
    return out


def render_spec(block: dict) -> dict:
    period = 2 * math.pi / min(p["speed"] for p in block["pieces"])
    times = [round(period * i / SEQ_FRAMES, 4) for i in range(SEQ_FRAMES)]
    return {"pieces": [{k: p[k] for k in ("prefab", "piece", "power", "direction", "speed")} for p in block["pieces"]],
            "seqs": [{"name": (pz or "rest").replace("+", "p").replace("-", "m"), "state": "full", "pose": pz,
                      "times": times} for pz in SEQ_POSES]}


def displaced(P_local: np.ndarray, R: np.ndarray, piece: dict, t: float) -> np.ndarray:
    """The Hex/Lit FLAG wave in the prefab frame (the runtime's world conversion only adds a constant phase)."""
    pw = np.asarray(piece["power"], np.float64)
    d = np.asarray(piece["direction"], np.float64)
    return P_local + pw[None] * (np.sin(P_local @ d + t * piece["speed"]) * R)[:, None]


def check(base: str, loop: int, phases: int) -> int:
    """town_full3d_zero_streak's certificate on the full state with every cloth piece displaced at `phases` times of
    the wave, against the same certificate of the base candidate (no cloth): the cloth may add no visible behind-streak
    component at any pose / time."""
    import town_full3d_zero_streak as ZS
    import town_t2_streak_map as SM
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    cl = rep.get("cloth")
    if not cl:
        raise SystemExit("cloth check: the candidate has no cloth stage report")
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES["full"]]
    P, UV, F, owner, names, texs = SM.load_bins(sc, rows, keys)
    cams = ZS.reachable_cams(sc, loop)
    offs = {}
    o = 0
    for k in keys:
        for b in rows.get(k, {}).get("bins", []):
            if not b["name"].startswith("Mesh_") or b.get("kind", "lit") != "lit" or b.get("pos") or b.get("rot"):
                continue
            nv = int(np.frombuffer((S.STAGE / k / f"{b['name']}.bytes").read_bytes()[:4], np.int32)[0])
            offs[f"{k}/{b['name']}"] = (o, nv)
            o += nv
    pieces = [p for p in cl["pieces"] if f"{p['prefab']}/{p['piece']}" in offs]
    out = {"schema": SCHEMA + ".check", "candidate": S.CANDIDATE, "base": base, "phases": {}, "pieces": len(pieces)}
    period = 2 * math.pi / min(p["speed"] for p in pieces)
    for j in range(phases):
        t = period * j / phases
        Pd = P.copy()
        for p in pieces:
            o0, nv = offs[f"{p['prefab']}/{p['piece']}"]
            loc = ((Pd[o0:o0 + nv] - sc.cpos) @ sc.C) * sc.scale
            R = np.frombuffer((S.STAGE / p["prefab"] / f"{p['piece']}.vcol").read_bytes(), np.float32).reshape(-1, 4)[:, 0]
            loc = displaced(loc, R.astype(np.float64), p, t)
            Pd[o0:o0 + nv] = sc.cpos + (loc / sc.scale) @ sc.C.T
        r = ZS.certify(sc, Pd, UV, F, owner, names, texs, cams, ZS.MIN_AREA, None, 0)
        out["phases"][f"t{j}"] = {"t": t, "summary": r["summary"],
                                  "visibleByPose": {k: v.get("visibleBehindPx", v.get("visiblePx"))
                                                    for k, v in r["poses"].items()}}
        print("phase", j, json.dumps(r["summary"])[:400])
    if base:
        bc = SC.DATA / "candidates" / base
        brows = json.loads((bc / S.ROWS.relative_to(S.CAND)).read_text(encoding="utf-8"))
        stage_b = bc / S.STAGE.relative_to(S.CAND)
        old = S.STAGE
        S.STAGE = stage_b
        SM.S.STAGE = stage_b
        try:
            Pb, UVb, Fb, ob, nb, tb = SM.load_bins(sc, brows, keys)
        finally:
            S.STAGE = old
            SM.S.STAGE = old
        rb = ZS.certify(sc, Pb, UVb, Fb, ob, nb, tb, cams, ZS.MIN_AREA, None, 0)
        out["baseSummary"] = rb["summary"]
        out["baseVisibleByPose"] = {k: v.get("visibleBehindPx", v.get("visiblePx")) for k, v in rb["poses"].items()}
        print("base", json.dumps(rb["summary"])[:400])
    (S.WORK / "cloth_check.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "apply", "check"])
    ap.add_argument("--base", default="", help="check: the candidate the cloth pass was applied on (a copy of it)")
    ap.add_argument("--loop", type=int, default=12)
    ap.add_argument("--phases", type=int, default=4)
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    if a.cmd == "check":
        return check(a.base, a.loop, a.phases)
    rep = plan(write=a.cmd == "apply")
    print(json.dumps({"pieces": len(rep["pieces"]), "layers": list(rep["layers"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
