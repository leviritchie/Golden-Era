"""Measure the stylistic axes of every rendered pair (ours vs vanilla) from the Hex/Lit relight renders.

    python tools/homm3_style_compare/measure.py      # -> artifacts/homm3_style_compare/metrics.json

All colour statistics are CIELAB (D65, sRGB input) over the unit's opaque pixels (alpha > 0.5, eroded 2 px).
Scale conventions:
  detail / noise / silhouette shape: each unit's crop resampled to NORM_H px tall (so a taller unit is not
  credited with more texels on screen);
  battle readability: resampled to its battle height in px = world height * PX_PER_WU, composited on the sand
  colour.
Proof tier: generated-artifact measurements of offline renders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "homm3_unit_look"))
import pairs as PR  # noqa: E402
import spec as S  # noqa: E402

RENDER = PR.OUT / "render"
NORM_H = 400
PX_PER_WU = 55.0          # battle px per world unit at 1080p: an assumption (see the page), not a measurement
SAND = (196, 170, 120)


def srgb_to_lab(rgb):
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    return np.stack([L, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_srgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * np.array([0.95047, 1.0, 1.08883])
    Mi = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ Mi.T, 0, 1)
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def load(p):
    return np.asarray(Image.open(p).convert("RGBA"))


def crop_box(*imgs):
    box = None
    for im in imgs:
        b = Image.fromarray(im).getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def own_crop(im, pad=4):
    b = Image.fromarray(im).getchannel("A").getbbox()
    b = (max(0, b[0] - pad), max(0, b[1] - pad), min(im.shape[1], b[2] + pad), min(im.shape[0], b[3] + pad))
    return im[b[1]:b[3], b[0]:b[2]]


def resize_h(im, h):
    w = max(1, round(im.shape[1] * h / im.shape[0]))
    pil = Image.fromarray(im)
    # premultiplied resample so the transparent background does not bleed into edges
    a = np.asarray(pil.getchannel("A"), dtype=np.float64) / 255
    rgb = np.asarray(pil.convert("RGB"), dtype=np.float64) * a[..., None]
    rs = lambda x: np.asarray(Image.fromarray(x.astype(np.float32), "F").resize((w, h), Image.LANCZOS), dtype=np.float64)
    A = np.clip(rs(a * 255), 0, 255)
    RGB = np.stack([rs(rgb[..., i]) for i in range(3)], -1)
    RGB = np.where(A[..., None] > 1, RGB / np.maximum(A[..., None] / 255, 1e-6), 0)
    return np.dstack([np.clip(RGB, 0, 255), A]).astype(np.uint8)


def mask_of(im, erode=2):
    m = im[..., 3] > 127
    return ndi.binary_erosion(m, iterations=erode) if erode else m


def pct(x, q):
    return float(np.percentile(x, q)) if x.size else float("nan")


def palette(lab, k=5, seed=0):
    from sklearn.cluster import KMeans
    x = lab if len(lab) < 40000 else lab[np.random.default_rng(seed).choice(len(lab), 40000, replace=False)]
    km = KMeans(n_clusters=k, n_init=4, random_state=seed).fit(x)
    share = np.bincount(km.labels_, minlength=k) / len(km.labels_)
    order = np.argsort(-share)
    cols = lab_to_srgb(km.cluster_centers_[order][None])[0]
    return [{"rgb": [int(v) for v in c], "share": round(float(share[i]), 3),
             "lab": [round(float(v), 1) for v in km.cluster_centers_[i]]} for c, i in zip(cols, order)]


def side_metrics(d: Path, height_world: float, has_emi: bool):
    lit, alb = load(d / "lit_battle.png"), load(d / "albedo_battle.png")
    rm = json.loads((d / "render_meta.json").read_text())
    out = {"triangles": rm["triangles"], "heightWorld": round(height_world, 3)}
    # ---- colour on the full-resolution render
    m = mask_of(lit)
    lab = srgb_to_lab(lit[..., :3])[m]
    labA = srgb_to_lab(alb[..., :3])[mask_of(alb)]
    C = np.hypot(lab[:, 1], lab[:, 2]); CA = np.hypot(labA[:, 1], labA[:, 2])
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    hv = np.sum(C * np.exp(1j * np.radians(hue))) / max(C.sum(), 1e-9)
    out.update({
        "Lmean": float(lab[:, 0].mean()), "Lspread": pct(lab[:, 0], 95) - pct(lab[:, 0], 5), "Lstd": float(lab[:, 0].std()),
        "Cmean": float(C.mean()), "Cp90": pct(C, 90), "hueMeanDeg": float(np.degrees(np.angle(hv)) % 360),
        "hueConcentration": float(abs(hv)),
        "albedoLmean": float(labA[:, 0].mean()), "albedoCmean": float(CA.mean()),
        "palette": palette(lab),
    })
    # ---- normalised-height detail, noise, shading
    litn, albn = resize_h(own_crop(lit), NORM_H), resize_h(own_crop(alb), NORM_H)
    mn = mask_of(litn, 3)
    Ln = srgb_to_lab(litn[..., :3])[..., 0]
    LAn = srgb_to_lab(albn[..., :3])[..., 0]
    mA = mask_of(albn, 3)

    def band(L, s0, s1, mk):
        # masked (normalised-convolution) blur so the transparent surround does not count as an edge
        w = mk.astype(np.float64)
        blur = lambda s: ndi.gaussian_filter(L * w, s) / np.maximum(ndi.gaussian_filter(w, s), 1e-6) if s else L
        return blur(s0) - blur(s1)
    fine = band(Ln, 0, 1.2, mn)[mn]
    mid = band(Ln, 1.2, 5.0, mn)[mn]
    med = ndi.median_filter(LAn, 3)
    speck = np.abs(LAn - med)[mA]
    w = mA.astype(np.float64)
    low = ndi.gaussian_filter(LAn * w, 8) / np.maximum(ndi.gaussian_filter(w, 8), 1e-6)
    mlit = mask_of(litn, 3) & mA
    out.update({
        "detailFineRms": float(np.sqrt(np.mean(fine ** 2))), "detailMidRms": float(np.sqrt(np.mean(mid ** 2))),
        "speckleFrac": float(np.mean(speck > 6.0)), "speckleMean": float(speck.mean()),
        "albedoLowpassSpread": pct(low[mA], 95) - pct(low[mA], 5),
        "liveShadingMeanDL": float((Ln - LAn)[mlit].mean()), "liveShadingStd": float((Ln - LAn)[mlit].std()),
    })
    # ---- silhouette shape (normalised height, binary)
    sil = litn[..., 3] > 127
    area = sil.sum()
    per = (sil ^ ndi.binary_erosion(sil)).sum()
    from scipy.spatial import ConvexHull
    ys, xs = np.nonzero(sil)
    hull = ConvexHull(np.c_[xs, ys]).volume
    out.update({"silhouetteIsoperimetric": float(per ** 2 / (4 * np.pi * area)), "silhouetteSolidity": float(area / hull),
                "aspectWH": float(sil.shape[1] / sil.shape[0])})
    # ---- battle scale readability on sand
    bh = max(8, round(height_world * PX_PER_WU))
    litb = resize_h(own_crop(lit, 0), bh)
    a = litb[..., 3:4].astype(np.float64) / 255
    comp = (litb[..., :3] * a + np.array(SAND) * (1 - a)).astype(np.uint8)
    Lb = srgb_to_lab(comp)[..., 0]
    Lsand = float(srgb_to_lab(np.array([[SAND]], dtype=np.uint8))[0, 0, 0])
    sb = litb[..., 3] > 127
    ring = sb & ~ndi.binary_erosion(sb, iterations=2)
    inner = ndi.binary_erosion(sb, iterations=2)
    sob = np.hypot(ndi.sobel(Lb, 0), ndi.sobel(Lb, 1)) / 8
    out.update({"battlePxHeight": int(bh), "battlePxWidth": int(litb.shape[1]),
                "edgeContrastVsSand": float(np.abs(Lb[ring] - Lsand).mean()),
                "bodyVsSandDL": float(Lb[sb].mean() - Lsand),
                "internalEdgeMean": float(sob[inner].mean()) if inner.any() else float("nan"),
                "internalEdgeFrac": float(np.mean(sob[inner] > 4.0)) if inner.any() else float("nan")})
    # ---- metal proxy: neutral, light albedo texels (steel / silver / white-metal candidates)
    albc = srgb_to_lab(alb[..., :3])
    mm = mask_of(alb) & mask_of(lit)
    CAf = np.hypot(albc[..., 1], albc[..., 2])
    metal = mm & (CAf < 10) & (albc[..., 0] > 45)
    Llit = srgb_to_lab(lit[..., :3])[..., 0]
    out["metalProxy"] = {"frac": float(metal.sum() / max(mm.sum(), 1)),
                         "albedoL": float(albc[..., 0][metal].mean()) if metal.any() else None,
                         "litL": float(Llit[metal].mean()) if metal.any() else None,
                         "litSheenP95minusP50": (pct(Llit[metal], 95) - pct(Llit[metal], 50)) if metal.sum() > 50 else None,
                         "albedoSpread": (pct(albc[..., 0][metal], 95) - pct(albc[..., 0][metal], 5)) if metal.sum() > 50 else None}
    # ---- emission (vanilla emission maps, assumed additive at weight 1)
    if has_emi and (d / "emi_battle.png").is_file():
        emi = load(d / "emi_battle.png")
        dl = srgb_to_lab(emi[..., :3])[..., 0] - Llit
        me = mask_of(lit)
        out["emission"] = {"fracLit": float(np.mean(dl[me] > 3)), "meanDL": float(dl[me].mean()),
                           "p99DL": pct(dl[me], 99)}
    return out


def ours_vfx(unit):
    mp = S.out_dir(unit) / "vfx" / "vfx_manifest.json"
    if not mp.is_file():
        return {"layers": 0, "types": []}
    man = json.loads(mp.read_text(encoding="utf-8"))
    types = sorted({ly.get("type") for ly in man.get("layers", {}).values()} - {"event", None})
    return {"layers": len([1 for ly in man.get("layers", {}).values() if ly.get("type") != "event"]), "types": types}


def main():
    rows = []
    for ours, pref, vname, cat, why in PR.PAIRS:
        pd = RENDER / ours
        pj = json.loads((pd / "pair.json").read_text())
        nm = json.loads((PR.NATIVE / PR.native_name(pref) / "meta.json").read_text())
        has_emi = any("HEX_EMISSION_MAP_ENABLED" in (m.get("keywords") or []) for m in nm["materials"])
        spec = S.load(ours)
        o = side_metrics(pd / "ours", pj["heightOurs"], False)
        v = side_metrics(pd / "vanilla", pj["heightVanilla"], has_emi)
        o["vfx"] = ours_vfx(ours)
        o["metalBaked"] = bool(spec.get("lighting", {}).get("metal"))
        o["lookApplied"] = (S.out_dir(ours) / "stamp.json").is_file()
        o["lookMode"] = spec.get("lighting", {}).get("mode")
        v["emissionMap"] = has_emi
        v["viewScale"] = nm["view"].get("scale")
        v["materials"] = [{"name": m["name"], "shader": m["shader"], "keywords": m.get("keywords"),
                           "metallic": m["floats"].get("_Metallic"), "glossiness": m["floats"].get("_Glossiness")}
                          for m in nm["materials"]]
        rows.append({"ours": ours, "vanilla": PR.native_name(pref), "vanillaName": vname, "category": cat, "why": why,
                     "pair": pj, "o": o, "v": v})
        print(f"{ours:18s} L {o['Lmean']:.1f}/{v['Lmean']:.1f} C {o['Cmean']:.1f}/{v['Cmean']:.1f} "
              f"fine {o['detailFineRms']:.2f}/{v['detailFineRms']:.2f} speck {o['speckleFrac']:.3f}/{v['speckleFrac']:.3f} "
              f"h {o['heightWorld']}/{v['heightWorld']}", flush=True)
    # vanilla scale anchor (write_battle_height_hexes.py): skeleton world height / h3_skeleton hexes
    sk = json.loads((PR.NATIVE / PR.native_name(PR.SCALE_ANCHOR[1]) / "meta.json").read_text())
    anchor = {"vanillaSkeletonWorldHeight": sk["worldHeight"], "h3SkeletonHexes": PR.hexes(PR.SCALE_ANCHOR[0]),
              "perHexAnchored": sk["worldHeight"] / PR.hexes(PR.SCALE_ANCHOR[0]), "perHexInstalled": PR.per_hex()}
    (PR.OUT / "metrics.json").write_text(json.dumps({"schema": "homm3_style_compare.metrics.v1", "normH": NORM_H,
                                                     "pxPerWorldUnit": PX_PER_WU, "sand": SAND, "scaleAnchor": anchor,
                                                     "pairs": rows}, indent=1))
    print("anchor", anchor)


if __name__ == "__main__":
    main()
