"""VFX stage: build every layer's assets and the fitted dynamic-light curves.

defFlipbook  DEF effect pixels per key of each listed clip, minus the body mask, cut around the effect's
             DEF origin (``anchor.defOrigin``: "auto" = the effect pixels nearest their body contact, or an
             explicit [x, y] / per-frame list) and pinned there to the anchor bone's projected head (or tip,
             ``anchor.boneTip``) in every key, so the DEF-vs-mesh pose difference does not offset the effect.
             ``effectMask.rows`` keeps only rows [y0, y1) relative to the anchor pixel. One point-filtered
             sheet per layer and clip, one cell per key (DEF frames not listed are empty cells).
             ``render``: "billboard" (view-facing, default) or "groundPlane" (laid on the ground: puddles,
             scorch, death pools); opt-in "unitPlane" / "trail" are documented in vfx_depth.py. A flipbook that carries an effectLight stays alive for the whole clip
             whenever that light's curve is non-zero there, drawing nothing on keys without a cell.
effectLight  per-key light position (anchor + pull toward the carrier's effect centroid + toward the
             camera) and, for ``intensitySource: fitted``, per-key intensity fitted so the mesh body's
             mean-L rise over the same pose at the light's floor equals the DEF body's rise over the
             clip's first key (effect pixels excluded) less the rise the pose change alone gives the mesh
             (unlit key i vs unlit key 0); never below ``floor``. A floor also holds in
             clips the light has no curve for (constant). The light is Hex/Lit's point-light term:
             rgb * I * saturate(1-(d2/r2)^2)^2 / d2 * saturate(N.L)  (Homm3VfxHexLitReplicaPoint).
uvAtlas      one atlas cell per source score cell: the look texture with each named defPalette region
             re-ranked by that cell's scores (regions.py), laid out on a grid with edge-padded gutters.
particles / event   carried into the manifest as declared (event actions include hideMesh / showMesh).
volumetricFire  DEF-ripped flame flipbook sheets + emitter mask + explicit ParticleSystem settings (volfire.py).

Timing rule: key i of a clip is DEF frame i at (i+1)/12 s; its cell shows over [(i+0.5)/12, (i+1.5)/12).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import masks as mk
import prebake_lab as pl
import spec as S

FPS = 12.0


class VfxNotSupported(RuntimeError):
    pass


def key_window(i: int):
    return [round((i + 0.5) / FPS, 5), round((i + 1.5) / FPS, 5)]


def view_name(t: int) -> str:
    return f"sprite_f{t + 1:03d}"


def anchor_px(ly, vm):
    b = vm["bones"][ly["anchor"]["bone"]]
    return tuple(b["tailPx"] if ly["anchor"].get("boneTip") else b["headPx"])


def anchor_world(ly, vm):
    b = vm["bones"][ly["anchor"]["bone"]]
    return np.array(b["tail"] if ly["anchor"].get("boneTip") else b["head"], np.float64)


def auto_origin(mask: np.ndarray, body: np.ndarray):
    """The effect pixels nearest their body contact (centroid of those within 1 px of the nearest)."""
    if not body.any():
        raise ValueError("defOrigin auto: the frame has no body pixels to find the effect's contact; give [x, y]")
    d = ndimage.distance_transform_edt(~body)
    ys, xs = np.nonzero(mask)
    dd = d[ys, xs]
    near = dd <= dd.min() + 1.0
    return float(xs[near].mean()), float(ys[near].mean())


def origin_spec(ly, clip, k):
    org = ly["anchor"].get("defOrigin", "auto")
    if isinstance(org, dict):
        seq = org.get(clip)
        return "auto" if seq is None else seq[k]
    return org


def layer_cells(ly, clip, ctx):
    """Masked DEF effect pixels, anchor px and DEF origin for every key of ``clip`` (mask None where not listed)."""
    c = ctx["clips"][clip]
    frames = ly["clips"][clip]["frames"]
    listed = {f: k for k, f in enumerate(frames)}
    body = ly.get("bodyMask", {})
    rows = ly["effectMask"].get("rows")
    out = []
    for (g, f), t in zip(c["defFrames"], c["masterFrames"]):
        vn = view_name(t)
        rec = ctx["def"][vn]
        vm = ctx["vmeta"]["views"][vn]
        ax, ay = anchor_px(ly, vm)
        if f not in listed:
            out.append({"t": t, "defFrame": f, "anchor": (ax, ay), "mask": None, "rgba": rec["rgba"], "origin": None})
            continue
        msk, dbody = mk.effect_mask_and_body(ly["effectMask"], rec["rgba"], ly.get("def") or ctx["defName"], g, f, ctx["unit"])
        if body.get("subtractMeshSilhouette"):
            sil = ctx["meshAlpha"][vn] > 0.5
            if body.get("dilatePx", 0):
                sil = ndimage.binary_dilation(sil, iterations=int(body["dilatePx"]))
            msk &= ~sil
        for r in body.get("rects", {}).get(str(f), []):
            x0, y0, x1, y1 = r
            msk[y0:y1, x0:x1] = False
        if rows:
            yy = np.arange(msk.shape[0])[:, None] - ay
            msk &= (yy >= rows[0]) & (yy < rows[1])
        org, src = None, None
        if msk.any():
            o = origin_spec(ly, clip, listed[f])
            org, src = (auto_origin(msk, dbody), "auto") if o == "auto" else ((float(o[0]), float(o[1])), "explicit")
        out.append({"t": t, "defFrame": f, "anchor": (ax, ay), "mask": msk, "rgba": rec["rgba"], "origin": org,
                    "originSource": src})
    return out


def build_flipbook(ly, ctx, vdir: Path):
    res = {}
    ppu = ctx["spritecam"]["pxPerUnit"]
    tex_scale = int(ly.get("texelsPerDefPx", 1))
    for clip in ly["clips"]:
        cells = layer_cells(ly, clip, ctx)
        hw = hh = 4
        for c in cells:
            if c["mask"] is not None and c["mask"].any():
                ys, xs = np.nonzero(c["mask"])
                ox, oy = c["origin"]
                hw = max(hw, int(math.ceil(max(abs(xs.min() - ox), abs(xs.max() - ox)))) + 3)
                hh = max(hh, int(math.ceil(max(abs(ys.min() - oy), abs(ys.max() - oy)))) + 3)
        tiles = []
        seq = []
        for c in cells:
            if c["mask"] is None or not c["mask"].any():
                seq.append(-1)
                continue
            rgba = (c["rgba"] * 255 + 0.5).astype(np.uint8).copy()
            rgba[~c["mask"]] = 0
            ox, oy = c["origin"]
            x0, y0 = int(round(ox)) - hw, int(round(oy)) - hh
            cell = np.zeros((2 * hh, 2 * hw, 4), np.uint8)
            H, W = rgba.shape[:2]
            sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + 2 * hw), min(H, y0 + 2 * hh)
            if sx1 > sx0 and sy1 > sy0:
                cell[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
            seq.append(len(tiles))
            tiles.append(cell)
        if not tiles:
            raise ValueError(f"layer {ly['id']} clip {clip}: the effect mask selects no pixels in any listed frame")
        n = len(tiles)
        tx = int(math.ceil(math.sqrt(n)))
        ty = int(math.ceil(n / tx))
        sheet = np.zeros((ty * 2 * hh, tx * 2 * hw, 4), np.uint8)
        for k, cell in enumerate(tiles):
            r, cc = divmod(k, tx)
            sheet[r * 2 * hh:(r + 1) * 2 * hh, cc * 2 * hw:(cc + 1) * 2 * hw] = cell
        if tex_scale > 1:
            sheet = sheet.repeat(tex_scale, 0).repeat(tex_scale, 1)
        name = f"{ly['id']}__{clip}.png"
        Image.fromarray(sheet).save(vdir / name)
        render = ly.get("render", "billboard")
        res[clip] = {"sheet": name, "tilesX": tx, "tilesY": ty, "cellPx": [2 * hw, 2 * hh],
                     "texelsPerDefPx": tex_scale, "sizeUnits": [2 * hw / ppu, 2 * hh / ppu],
                     "anchorBone": ly["anchor"]["bone"], "anchorPoint": "tail" if ly["anchor"].get("boneTip") else "head",
                     "pivot": "cell centre = the key's DEF origin, pinned to the anchor point",
                     "keys": [{"defFrame": c["defFrame"], "cell": s, "window": key_window(i),
                               **({"defOriginPx": [round(c["origin"][0], 2), round(c["origin"][1], 2)],
                                   "originSource": c["originSource"]} if s >= 0 else {})}
                              for i, (c, s) in enumerate(zip(cells, seq))],
                     "pixels": [int(c["mask"].sum()) if c["mask"] is not None else 0 for c in cells],
                     "shader": "Sprites/Default", "filter": "point", "blend": "alpha", "render": render,
                     "billboard": "view" if render == "billboard" else "groundPlane", "lifetime": "cells"}
    return res


def paste_cells(base_rgb, fb, clip_entry_key, anchor, vdir: Path, cache: dict):
    """Composite one flipbook key's cell (output-resolution sRGB float, HxWx3) with its centre at ``anchor``.
    A groundPlane layer is composited the same way (the DEF pixels are already the sprite-camera view)."""
    k = clip_entry_key["cell"]
    if k < 0 or not fb.get("sheet"):
        return base_rgb, np.zeros(base_rgb.shape[:2], bool)
    sheet_name = fb["sheet"]
    if sheet_name not in cache:
        cache[sheet_name] = np.asarray(Image.open(vdir / sheet_name).convert("RGBA"), np.float32) / 255
    s = cache[sheet_name]
    sc = fb["texelsPerDefPx"]
    cw, ch = fb["cellPx"]
    r, c = divmod(k, fb["tilesX"])
    cell = s[r * ch * sc:(r + 1) * ch * sc:sc, c * cw * sc:(c + 1) * cw * sc:sc]
    H, W = base_rgb.shape[:2]
    x0, y0 = int(round(anchor[0])) - cw // 2, int(round(anchor[1])) - ch // 2
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + cw), min(H, y0 + ch)
    out = base_rgb.copy()
    cov = np.zeros((H, W), bool)
    if sx1 <= sx0 or sy1 <= sy0:
        return out, cov
    part = cell[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
    a = part[..., 3:4]
    out[sy0:sy1, sx0:sx1] = out[sy0:sy1, sx0:sx1] * (1 - a) + part[..., :3] * a
    cov[sy0:sy1, sx0:sx1] = a[..., 0] > 0.5
    return out, cov


# ----------------------------------------------------------------------------- lights
def light_position(ly, carrier_cells_by_t, ctx, t):
    vn = view_name(t)
    vm = ctx["vmeta"]["views"][vn]
    p = anchor_world(ly, vm)
    ax, ay = anchor_px(ly, vm)
    ppu = ctx["spritecam"]["pxPerUnit"]
    right = np.array(vm["camRight"], np.float64)
    fwd = np.array(vm["camForward"], np.float64)
    up = np.cross(right, fwd)
    pull = ly["anchor"].get("towardLayerCentroid", 0.0)
    cell = carrier_cells_by_t.get(t)
    if pull and cell is not None and cell["mask"] is not None and cell["mask"].any():
        ys, xs = np.nonzero(cell["mask"])
        p = p + pull * ((xs.mean() - ax) / ppu * right - (ys.mean() - ay) / ppu * up)
    p = p - ly["anchor"].get("towardCameraU", 0.0) * fwd
    return p


def point_term(view, pos, rgb_lin, intensity, rng):
    """Per-pixel (ss-res) Hex/Lit point-light irradiance."""
    if intensity <= 0:
        return None
    P = view["position"]
    N = view["normal"]
    d = pos[None, None, :] - P
    d2 = np.maximum((d * d).sum(-1), 1e-5)
    s = np.clip(1 - (d2 / (rng * rng)) ** 2, 0, 1)
    att = s * s / d2
    ndl = np.clip((N * d).sum(-1) / np.sqrt(d2), 0, 1)
    return (att * ndl)[..., None] * (np.asarray(rgb_lin, np.float32) * intensity)


def lit_render(tex_lin, view, vmeta_v, cond, extra=None):
    col = pl.sample_tex(tex_lin, view["uv"])
    light = pl.runtime_light(view, cond)
    if extra is not None:
        light = light + extra
    col, a = pl.downsample(col * light, view["alpha"], vmeta_v["supersample"])
    return col, a


def clip_of(ctx, t):
    for cn, c in ctx["clips"].items():
        if t in c["masterFrames"]:
            return cn
    return None


def floor_extras(spec, ctx, view_names):
    """Irradiance of every dynamic light held at its floor, per view (the grade fit's lighting). Positions
    use the anchor and camera pull only (no carrier-centroid pull: the carrier is not built yet)."""
    extras, floors = {}, {}
    for ly in spec["vfx"]["layers"]:
        if ly["type"] != "effectLight" or not ly.get("floor"):
            continue
        rgb_lin = pl.srgb_to_lin(np.array(ly["rgb"], np.float32))
        for vn in view_names:
            t = ctx["vmeta"]["views"][vn]["frame"] - 1
            cn = clip_of(ctx, t)
            f0 = S.light_floor(ly, cn) if cn else 0.0
            if f0 <= 0:
                continue
            term = point_term(ctx["views"][vn], light_position(ly, {}, ctx, t), rgb_lin, f0, ly["range"])
            extras[vn] = term if extras.get(vn) is None else extras[vn] + term
            floors.setdefault(ly["id"], {})[vn] = f0
    return extras, floors


def fit_light_curves(ly, ctx, tex_lin, carriers):
    cond = ctx["cond"]
    rgb_lin = pl.srgb_to_lin(np.array(ly["rgb"], np.float32))
    out = {}
    for clip in S.light_clips(ly, ctx["clips"]):
        c = ctx["clips"][clip]
        f0 = S.light_floor(ly, clip)
        cells = {cc["t"]: cc for cc in carriers.get(clip, [])}
        rows = []
        if clip not in ly.get("intensity", {}):
            # floor-only clip: the light holds its floor; positions only where the key was baked
            for i, t in enumerate(c["masterFrames"]):
                vn = view_name(t)
                pos = light_position(ly, cells, ctx, t) if vn in ctx["views"] else None
                rows.append({"defFrame": c["defFrames"][i][1], "window": key_window(i), "intensity": round(f0, 3),
                             "floor": round(f0, 3), "source": "floor",
                             "positionWorld": [round(v, 4) for v in pos.tolist()] if pos is not None else None})
            out[clip] = rows
            continue
        seq = ly["intensity"][clip]
        base_def = base_mesh = None
        for i, t in enumerate(c["masterFrames"]):
            vn = view_name(t)
            view = ctx["views"][vn]
            vmv = ctx["vmeta"]["views"][vn]
            rec = ctx["def"][vn]
            dL = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))[..., 0][rec["bodyNoFx"]].mean()
            base_def = dL if base_def is None else base_def
            pos = light_position(ly, cells, ctx, t)
            col0, a = lit_render(tex_lin, view, vmv, cond, point_term(view, pos, rgb_lin, f0, ly["range"]))
            mask = a > 0.9
            L0 = pl.lin_to_lab(col0)[..., 0][mask].mean()
            base_mesh = L0 if base_mesh is None else base_mesh
            # the light supplies only the DEF's rise that the pose change alone does not already give the mesh
            pose_rise = float(L0 - base_mesh)
            target = max(0.0, float(dL - base_def) - pose_rise)

            def rise(I):
                col, _ = lit_render(tex_lin, view, vmv, cond, point_term(view, pos, rgb_lin, I, ly["range"]))
                return float(pl.lin_to_lab(col)[..., 0][mask].mean() - L0)
            if ly.get("intensitySource") == "fitted":
                if target <= 0.05:
                    I = f0
                else:
                    lo, hi = f0, max(1.0, 2 * f0)
                    while rise(hi) < target and hi < 64:
                        hi *= 2
                    for _ in range(18):
                        mid = 0.5 * (lo + hi)
                        lo, hi = (mid, hi) if rise(mid) < target else (lo, mid)
                    I = 0.5 * (lo + hi)
            else:
                I = float(seq[i])
            rows.append({"defFrame": c["defFrames"][i][1], "window": key_window(i), "defRiseL": round(float(dL - base_def), 2),
                         "poseRiseL": round(pose_rise, 2), "targetRiseL": round(target, 2),
                         "intensity": round(max(I, f0), 3), "floor": round(f0, 3),
                         "meshRiseL": round(rise(I), 2) if I > f0 else 0.0,
                         "positionWorld": [round(v, 4) for v in pos.tolist()]})
        out[clip] = rows
    return out


# ----------------------------------------------------------------------------- uvAtlas
def modulate_cells(ly, tex_lin):
    """uvAtlas "modulate" variant: cell k = the look texture x clip(1 + 2 gain (score_k - 0.5)).

    A score of 0.5 is neutral, so a generator leaves texels it does not animate at 0.5. For units with no
    defPalette region to rank-map onto (the conflux elementals' element flow, element_flow_scores.py): the
    look's own colours are kept and only their brightness flows."""
    import regions as RG
    g = float(ly["modulate"]["gain"])
    scores = RG.load_scores(ly, tex_lin.shape[0])
    return [np.clip(tex_lin * np.clip(1 + 2 * g * (sc - 0.5), 0, None)[..., None], 0, 1) for sc in scores]


def build_atlas(ly, spec, ctx, work: Path, vdir: Path, tex_lin):
    """Cells = the look texture with each named defPalette region re-ranked by that cell's scores
    (or, with "modulate", brightness-modulated by them: modulate_cells)."""
    import regions as RG
    if "modulate" in ly:
        return _lay_out_atlas(ly, vdir, modulate_cells(ly, tex_lin), None)
    fitp = work / "regions_fit.json"
    if not fitp.is_file():
        raise VfxNotSupported(f"uvAtlas {ly['id']}: no regions_fit.json (run the fit stage with lighting.regions)")
    fit = json.loads(fitp.read_text())
    m = ctx["maps"]
    size = tex_lin.shape[0]
    W = RG.region_weights(spec, ctx, work, size)
    scores = RG.load_scores(ly, size)
    cell0 = {}
    parts = []
    for rn in ly["regions"]:
        f = fit[rn]
        pal = np.load(work / f"region_{rn}_palette.npy")
        sup = W[rn] > 0.02
        prm = (f["s"], f["skyAlpha"], f["paletteGamma"])
        cell0[rn] = RG.palette_tex(scores[0], sup, pal, m["sky"], prm, tex_lin.shape)
        parts.append((rn, sup, pal, prm))
    cells = []
    for k in range(len(scores)):
        t = tex_lin.copy()
        for rn, sup, pal, prm in parts:
            t = t + W[rn][..., None] * (RG.palette_tex(scores[k], sup, pal, m["sky"], prm, tex_lin.shape) - cell0[rn])
        cells.append(np.clip(t, 0, 1))
    return _lay_out_atlas(ly, vdir, cells, ly["regions"])


def _lay_out_atlas(ly, vdir: Path, cells, regions):
    n = len(cells)
    src_cell = int(np.load(Path(ly["source"]["scores"]) if Path(ly["source"]["scores"]).is_absolute()
                           else S.ROOT / ly["source"]["scores"])["scores"].shape[1])
    gut = int(ly.get("gutterPx", 32))
    tx = int(math.ceil(math.sqrt(n)))
    ty = int(math.ceil(n / tx))
    pitch = src_cell + 2 * gut
    Wd, Hd = tx * pitch, ty * pitch
    atlas = np.zeros((Hd, Wd, 3), np.uint8)
    cells_lin = []
    st = []
    for k in range(n):
        t = cells[k]
        s8 = (pl.lin_to_srgb(t) * 255 + 0.5).astype(np.uint8)
        if s8.shape[0] != src_cell:
            s8 = np.asarray(Image.fromarray(s8).resize((src_cell, src_cell), Image.LANCZOS))
        cells_lin.append(pl.srgb_to_lin(s8.astype(np.float32) / 255).astype(np.float16))
        r, c = divmod(k, tx)
        x0, y0 = c * pitch, r * pitch
        atlas[y0:y0 + pitch, x0:x0 + pitch] = np.pad(s8, ((gut, gut), (gut, gut), (0, 0)), mode="edge")
        st.append([src_cell / Wd, src_cell / Hd, (x0 + gut) / Wd, 1 - (y0 + gut + src_cell) / Hd])
    name = f"{ly['id']}__atlas.png"
    Image.fromarray(atlas).save(vdir / name)
    clips = {cn: [{"cell": int(k), "window": key_window(i)} for i, k in enumerate(seq)] for cn, seq in ly["clips"].items()}
    entry = {"type": "uvAtlas", "atlas": name, "grid": [tx, ty], "cellPx": src_cell, "gutterPx": gut,
             "cellST": [[round(v, 6) for v in s] for s in st], "regions": regions,
             **({"modulate": ly["modulate"]} if "modulate" in ly else {}),
             "material": "body base colour swapped to the atlas; _MainTex_ST stepped per key (cellST, Unity v-up)",
             "source": ly["source"], "clips": clips}
    return entry, cells_lin


def run(spec, ctx, vdir: Path, tex_lin, work: Path | None = None) -> dict:
    vdir.mkdir(parents=True, exist_ok=True)
    for old in vdir.glob("*.png"):          # a rerun must not keep sheets of layers that no longer exist
        old.unlink()
    layers = spec["vfx"]["layers"]
    manifest = {"schema": "homm3_unit_look_vfx.v1", "unit": spec["unit"], "fps": FPS,
                "timingRule": "key i = DEF frame i at (i+1)/12 s; cell window [(i+0.5)/12, (i+1.5)/12)",
                "layers": {}, "assets": {}}
    carriers = {}
    atlas_cells = {}
    for ly in layers:
        t = ly["type"]
        if t == "uvAtlas":
            if not ly.get("source") or not (ly.get("regions") or ly.get("modulate")):
                raise VfxNotSupported(f"layer {ly['id']}: uvAtlas needs source.scores and defPalette regions (or modulate) "
                                      "(the runner grades the cells itself; there is no pre-graded atlas path)")
            entry, cl = build_atlas(ly, spec, ctx, work, vdir, tex_lin)
            manifest["layers"][ly["id"]] = entry
            atlas_cells[ly["id"]] = cl
        elif t == "defFlipbook":
            fb = build_flipbook(ly, ctx, vdir)
            if ly.get("render") in ("unitPlane", "trail"):      # opt-in depth-aware renders (vfx_depth.py)
                import vfx_depth
                fb = vfx_depth.build(ly, ctx, vdir, fb, layer_cells)
            carriers[ly["id"]] = {clip: layer_cells(ly, clip, ctx) for clip in ly["clips"]}
            manifest["layers"][ly["id"]] = {"type": t, "light": ly.get("light"), "render": ly.get("render", "billboard"),
                                            "clips": fb}
        elif t == "volumetricFire":                      # opt-in DEF-ripped volumetric fire (volfire.py)
            import volfire
            manifest["layers"][ly["id"]] = volfire.build(ly, spec, spec["unit"], ctx["spritecam"]["pxPerUnit"], vdir,
                                                         ctx["clips"], ctx.get("defName"))
        elif t in ("particles", "event"):
            manifest["layers"][ly["id"]] = {k: v for k, v in ly.items() if k != "id"}
    fitted = {}
    for ly in layers:
        if ly["type"] != "effectLight":
            continue
        curves = fit_light_curves(ly, ctx, tex_lin, carriers.get(ly["carrier"], {}))
        manifest["layers"][ly["id"]] = {"type": "effectLight", "lightId": ly["lightId"], "carrier": ly["carrier"],
                                        "rgb": ly["rgb"], "range": ly["range"], "treatment": "dynamic",
                                        "floor": ly.get("floor", 0.0),
                                        "module": "ParticleSystem.lights (ratio 1, maxLights 1, template Point light)",
                                        "intensitySource": ly["intensitySource"], "clips": curves}
        if ly["intensitySource"] == "fitted":
            fitted[ly["id"]] = {clip: [r["intensity"] for r in rows] for clip, rows in curves.items()
                                if clip in ly.get("intensity", {})}
        # carrier liveness: a flipbook carrier lives for the whole clip wherever its light is non-zero
        car = manifest["layers"].get(ly["carrier"])
        if car and car.get("type") == "defFlipbook":
            for clip, rows in curves.items():
                if not any(r["intensity"] > 0 for r in rows):
                    continue
                ent = car["clips"].get(clip)
                if ent is None:
                    ent = car["clips"][clip] = {"sheet": None, "keys": [{"defFrame": r["defFrame"], "cell": -1,
                                                                        "window": r["window"]} for r in rows]}
                ent["lifetime"] = "clip"
                ent.setdefault("carries", []).append(ly["lightId"])
    for f in sorted(vdir.glob("*.png")):
        manifest["assets"][f.name] = pl_sha(f)
    (vdir / "vfx_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return {"manifest": manifest, "fittedIntensity": fitted, "atlasCells": atlas_cells}


def pl_sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()
