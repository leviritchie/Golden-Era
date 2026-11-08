"""lighting.regions: per-region grades, each fitted against its own DEF region (docs/homm3_unit_look_pipeline.md).

A region is a texture-space weight (from a UV mask PNG, a GLB vertex-colour channel, or the skin weight of
the joints matching a list of globs) paired with a DEF region (a key of the unit's ``lighting.defSegmenter``).
``grade``      the v7c raw (chroma detail + detail boost + v7 shading) graded to the DEF region's L*a*b*
               percentiles (the unit-level grade model, fitted on this region only).
``defPalette`` rank-map: the region's texels, ordered by a score, take the DEF region's colours ordered by
               luma (``pal^gamma * s * sky^-alpha``, fitted). The score is the raw albedo luminance, or the
               first cell of a uvAtlas layer that grades its cells through this region (so the static base
               colour is that layer's cell 0).
The unmasked rest keeps the unit-level mode (v7c / v6m), fitted on the rest texels and the rest DEF pixels.
uvAtlas cells are the same composite with each cell's scores in place of cell 0's (vfx.build_atlas).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

import prebake_lab as pl
import spec as S
from glbpatch import Glb

_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
PAL_BOUNDS = {"s": (0.2, 4.0), "skyAlpha": (0.0, 1.5), "paletteGamma": (0.6, 1.6)}


def accessor(g: Glb, i: int) -> np.ndarray:
    a = g.json["accessors"][i]
    bv = g.json["bufferViews"][a["bufferView"]]
    dt = np.dtype(_COMP[a["componentType"]])
    nc = _NCOMP[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * nc
    buf = bytes(g.bin)
    if stride == dt.itemsize * nc:
        arr = np.frombuffer(buf, dt, a["count"] * nc, start).reshape(a["count"], nc)
    else:
        arr = np.stack([np.frombuffer(buf, dt, nc, start + k * stride) for k in range(a["count"])])
    if a.get("normalized") and dt.kind in "ui":
        arr = arr.astype(np.float32) / np.iinfo(dt).max
    return arr


def vertex_values(g: Glb, mask: dict) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Per body primitive: (glTF UV, triangle indices, per-vertex value in [0,1])."""
    mi = g.body_mesh_index()
    node = next((n for n in g.json["nodes"] if n.get("mesh") == mi), {})
    joints = []
    if "skin" in node:
        joints = [g.json["nodes"][j].get("name", "") for j in g.json["skins"][node["skin"]]["joints"]]
    out = []
    for p in g.json["meshes"][mi]["primitives"]:
        at = p["attributes"]
        uv = accessor(g, at["TEXCOORD_0"]).astype(np.float64)
        idx = accessor(g, p["indices"]).reshape(-1, 3) if "indices" in p else np.arange(len(uv)).reshape(-1, 3)
        if "vertexColor" in mask:
            if "COLOR_0" not in at:
                raise ValueError("region mask vertexColor: the body mesh has no COLOR_0")
            c = accessor(g, at["COLOR_0"]).astype(np.float32)
            ch = "rgba".index(mask["vertexColor"]["channel"])
            v = c[:, ch] if ch < c.shape[1] else np.ones(len(c), np.float32)
        else:
            if "JOINTS_0" not in at or not joints:
                raise ValueError("region mask bones: the body mesh is not skinned")
            J = accessor(g, at["JOINTS_0"]).astype(np.int64)
            Wt = accessor(g, at["WEIGHTS_0"]).astype(np.float32)
            sel = np.array([any(fnmatch.fnmatchcase(n, pat) for pat in mask["bones"]) for n in joints])
            if not sel.any():
                raise ValueError(f"region mask bones {mask['bones']} match no joint of the body skin")
            v = (Wt * sel[J]).sum(1)
        out.append((uv, idx, np.clip(v, 0, 1)))
    return out


def rasterise_values(prims, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Barycentric raster of per-vertex values into a top-down texture (glTF UV, v down)."""
    val = np.zeros((size, size), np.float32)
    cov = np.zeros((size, size), bool)
    for uv, tris, v in prims:
        P = uv * size - 0.5
        for a, b, c in tris:
            x0, y0 = P[a]
            x1, y1 = P[b]
            x2, y2 = P[c]
            xmin, xmax = max(int(np.floor(min(x0, x1, x2))), 0), min(int(np.ceil(max(x0, x1, x2))), size - 1)
            ymin, ymax = max(int(np.floor(min(y0, y1, y2))), 0), min(int(np.ceil(max(y0, y1, y2))), size - 1)
            if xmax < xmin or ymax < ymin:
                continue
            d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(d) < 1e-12:
                continue
            gx, gy = np.meshgrid(np.arange(xmin, xmax + 1), np.arange(ymin, ymax + 1))
            l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / d
            l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / d
            l2 = 1 - l0 - l1
            ins = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
            if ins.any():
                val[gy[ins], gx[ins]] = (l0 * v[a] + l1 * v[b] + l2 * v[c])[ins]
                cov[gy[ins], gx[ins]] = True
    return val, cov


def texture_weight(region: dict, glb_bytes: bytes, size: int) -> np.ndarray:
    m = region["mask"]
    if "maskPath" in m:
        p = Path(m["maskPath"])
        p = p if p.is_absolute() else S.ROOT / p
        return np.asarray(Image.open(p).convert("L").resize((size, size), Image.BILINEAR), np.float32) / 255
    val, cov = rasterise_values(vertex_values(Glb(glb_bytes), m), size)
    if "vertexColor" in m:
        val = (val >= m["vertexColor"]["threshold"]).astype(np.float32)
    if cov.any():                                   # seam padding: uncovered texels take the nearest covered value
        idx = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
        val = val[idx[0], idx[1]]
    return np.clip(ndimage.gaussian_filter(val, 1.0), 0, 1)


def mask_inputs_sha(glb_bytes: bytes, mask: dict) -> str | None:
    """sha256 of the body vertex streams texture_weight reads beyond the geometry key (COLOR_0 for a vertexColor
    mask; JOINTS_0 / WEIGHTS_0 and the skin's joint names for a bones mask), so a rebuild that re-weights the skin
    with the mesh unchanged recomputes the region instead of reading a stale cache. None for a maskPath mask."""
    if "maskPath" in mask:
        return None
    g = Glb(glb_bytes)
    mi = g.body_mesh_index()
    h = hashlib.sha256()
    streams = ("COLOR_0",) if "vertexColor" in mask else ("JOINTS_0", "WEIGHTS_0")
    if "vertexColor" not in mask:
        node = next((n for n in g.json["nodes"] if n.get("mesh") == mi), {})
        if "skin" in node:
            h.update(json.dumps([g.json["nodes"][j].get("name", "") for j in g.json["skins"][node["skin"]]["joints"]]).encode())
    for prim in g.json["meshes"][mi]["primitives"]:
        for k in streams:
            if k in prim["attributes"]:
                h.update(k.encode() + g.accessor_bytes(prim["attributes"][k]))
    return h.hexdigest()


def region_weights(spec, ctx, work: Path, size: int) -> dict[str, np.ndarray]:
    """Texture weight per region, cached in work/ keyed by the source geometry, the mask spec and the vertex streams
    the mask reads (mask_inputs_sha). Stored exactly as computed, so a cache hit returns what a fresh computation does
    (the float16 cache before 2026-10-05 rounded the weights a fresh run used unrounded)."""
    regs = spec["lighting"].get("regions") or []
    fs = json.loads((work / "fit_source.json").read_text())
    out = {}
    src = None
    for r in regs:
        if src is None and "maskPath" not in r["mask"]:
            src = ctx["srcGlb"]()
        key = S.canonical_sha({"geo": fs["geometrySha256"], "mask": r["mask"], "size": size,
                               "file": _file_sha(r["mask"].get("maskPath")),
                               "streams": mask_inputs_sha(src, r["mask"]) if src is not None else None, "cache": "exact"})
        cp = work / f"region_{r['name']}_{key[:12]}.npy"
        if cp.is_file():
            out[r["name"]] = np.load(cp)
            continue
        w = texture_weight(r, src if src is not None else ctx["srcGlb"](), size)
        np.save(cp, w)   # the array as computed (dtype included): a hit is bit-identical to a fresh run
        out[r["name"]] = w
    tot = sum(out.values()) if out else None
    if tot is not None and (tot > 1).any():        # overlapping regions share a texel in proportion
        sc = np.maximum(tot, 1.0)
        out = {k: v / sc for k, v in out.items()}
    return out


def _file_sha(p):
    if not p:
        return None
    pp = Path(p)
    pp = pp if pp.is_absolute() else S.ROOT / pp
    return hashlib.sha256(pp.read_bytes()).hexdigest() if pp.is_file() else None


def def_region_masks(spec, ctx, views_) -> dict[str, dict[str, np.ndarray]]:
    """{region name: {view: DEF pixels of that region (body, effects removed)}}."""
    regs = spec["lighting"].get("regions") or []
    if not regs:
        return {}
    seg = S.load_segmenter(spec["lighting"]["defSegmenter"])
    out = {r["name"]: {} for r in regs}
    for vn in views_:
        rec = ctx["def"][vn]
        sg = seg((np.clip(rec["rgba"], 0, 1) * 255 + 0.5).astype(np.uint8))
        for r in regs:
            if r["defRegion"] not in sg:
                raise ValueError(f"defSegmenter returned no {r['defRegion']!r} (keys {sorted(sg)})")
            out[r["name"]][vn] = np.asarray(sg[r["defRegion"]], bool) & rec["bodyNoFx"]
    return out


def atlas_scores(spec, region_name, size):
    """Cell-0 scores of the uvAtlas layer that grades its cells through this region (None when none does)."""
    for ly in spec["vfx"]["layers"]:
        if ly["type"] == "uvAtlas" and region_name in (ly.get("regions") or []) and ly.get("source"):
            return load_scores(ly, size)[0]
    return None


def load_scores(ly, size) -> np.ndarray:
    p = Path(ly["source"]["scores"])
    p = p if p.is_absolute() else S.ROOT / p
    if not p.is_file():
        raise FileNotFoundError(f"uvAtlas {ly['id']}: source.scores {p} missing; run {ly['source'].get('generator')}")
    sc = np.load(p)["scores"].astype(np.float32)
    if sc.ndim != 3:
        raise ValueError(f"uvAtlas {ly['id']}: scores must be (cells, H, W)")
    if sc.shape[1] != size:
        sc = np.stack([np.asarray(Image.fromarray(c).resize((size, size), Image.BILINEAR)) for c in sc])
    return sc


def rank_map(score: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """The texel at score-quantile q takes the DEF colour at luma-quantile q (oceanid_water_lab.palette_map)."""
    r = np.argsort(np.argsort(score, kind="stable"), kind="stable") / max(1, len(score) - 1)
    return palette[np.minimum((r * len(palette)).astype(int), len(palette) - 1)]


def palette_tex(score, support, palette, sky, params, shape):
    s, a, gam = params
    t = np.zeros(shape, np.float32)
    comp = np.power(np.clip(sky, 0.2, 1.0), -a)[support][:, None]
    t[support] = np.power(rank_map(score[support], palette), gam) * s * comp
    return np.clip(t, 0, 1)


def pct_cost(lab, tgt, q):
    return sum(np.mean(np.abs(np.percentile(lab[:, i], q) - tgt[i])) * w for i, w in ((0, 1.0), (1, 0.7), (2, 0.7)))


def fit_regions(spec, ctx, work: Path, samples_for, fit_grade, v7_raw, bounds, bound_hits):
    """Fit every region. Returns (weights, {name: texture}, report, def masks per region)."""
    regs = spec["lighting"].get("regions") or []
    m, views, cond = ctx["maps"], ctx["views"], ctx["cond"]
    size = m["albedo"].shape[0]
    W = region_weights(spec, ctx, work, size)
    dmask = def_region_masks(spec, ctx, ctx["fitViews"])
    q = np.linspace(2, 98, 25)
    texes, report = {}, {}
    for r in regs:
        n = r["name"]
        w = W[n]
        labs, pal = [], []
        for vn, dm in dmask[n].items():
            rgb = ctx["def"][vn]["rgba"][..., :3]
            labs.append(pl.lin_to_lab(pl.srgb_to_lin(rgb))[dm])
            pal.append(pl.srgb_to_lin(rgb[dm]))
        tl = np.concatenate(labs) if labs else np.zeros((0, 3))
        if len(tl) < 200:
            raise ValueError(f"region {n}: only {len(tl)} DEF pixels in {r['defRegion']!r} on the fit frames")
        tgt = [np.percentile(tl[:, i], q) for i in range(3)]
        smp = samples_for(views, ctx["fitViews"], cond, keep=w, keep_min=0.8, extras=ctx.get("floorExtras"))
        nsmp = sum(len(x[0]) for x in smp.values())
        if nsmp < 200:
            raise ValueError(f"region {n}: only {nsmp} visible texels with weight > 0.8 on the fit views")
        kn = r.get("knobs", {})
        if r["target"] == "grade":
            raw = v7_raw
            cols = [(pl.sample_tex(raw, views[v]["uv"][rr, cc][None])[0], l) for v, (rr, cc, l) in smp.items()]
            toe = kn.get("toeMax", 0.08)
            g, cost = fit_grade(cols, tgt, q, bounds, ([2.0, 1.0, 1.3, 1.0, 1.0, 0.02], [4.0, 0.9, 1.6, 1.1, 0.8, 0.02]),
                                toe_max=toe)
            texes[n] = pl.grade(raw, g)
            report[n] = {"target": "grade", "defRegion": r["defRegion"], "grade": np.round(g, 4).tolist(),
                         "cost": round(cost, 3), "defPixels": int(len(tl)), "texSamples": nsmp,
                         "boundHits": bound_hits(g, bounds, f"region:{n}", toe)}
        else:
            palette = np.concatenate(pal)
            palette = palette[np.argsort(pl.luminance(palette), kind="stable")]
            support = w > 0.02
            sc = atlas_scores(spec, n, size)
            score_from = "uvAtlas cell 0" if sc is not None else "raw albedo luminance"
            score = sc if sc is not None else pl.luminance(m["albedo"])
            sky = m["sky"]
            skyc = kn.get("skyCompensation", True)

            def tex_of(x):
                return palette_tex(score, support, palette, sky, (x[0], x[1] if skyc else 0.0, x[2]), m["albedo"].shape)

            def cost(x):
                s_, a_, g_ = x
                if not (PAL_BOUNDS["s"][0] < s_ < PAL_BOUNDS["s"][1] and PAL_BOUNDS["skyAlpha"][0] <= a_ <= PAL_BOUNDS["skyAlpha"][1]
                        and PAL_BOUNDS["paletteGamma"][0] <= g_ <= PAL_BOUNDS["paletteGamma"][1]):
                    return 1e6
                t = tex_of(x)
                lab = np.concatenate([pl.lin_to_lab(pl.sample_tex(t, views[v]["uv"][rr, cc][None])[0] * l)
                                      for v, (rr, cc, l) in smp.items()])
                return pct_cost(lab, tgt, q)
            best = min((optimize.minimize(cost, np.array(x0), method="Nelder-Mead",
                                          options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-3})
                        for x0 in ([1.0, 0.3, 1.0], [1.6, 0.6, 0.9])), key=lambda rr: rr.fun)
            x = best.x
            params = [float(x[0]), float(x[1]) if skyc else 0.0, float(x[2])]
            texes[n] = tex_of(x)
            np.save(work / f"region_{n}_palette.npy", palette.astype(np.float32))
            hits = [f"region:{n}:{k}={v:.3f}" for (k, (lo, hi)), v in zip(PAL_BOUNDS.items(), params)
                    if min(abs(v - lo), abs(v - hi)) < 1e-2 * (hi - lo) and not (k == "skyAlpha" and not skyc)]
            report[n] = {"target": "defPalette", "defRegion": r["defRegion"], "s": round(params[0], 4),
                         "skyAlpha": round(params[1], 4), "paletteGamma": round(params[2], 4), "cost": round(float(best.fun), 3),
                         "paletteSize": int(len(palette)), "scoreFrom": score_from, "defPixels": int(len(tl)),
                         "texSamples": nsmp, "boundHits": hits}
    return W, texes, report, dmask


def compose(rest, W, texes):
    tot = sum(W.values())
    out = rest * (1 - tot)[..., None]
    for n, t in texes.items():
        out = out + W[n][..., None] * t
    return out.astype(np.float32)
