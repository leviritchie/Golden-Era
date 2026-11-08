"""Measure the water motion the oceanid's DEF (COCEANID) actually draws, per clip.

Regions per frame (from colour, the gold belt and the silhouette):
- HAIR:   light (value >= 0.5) low-saturation opaque pixels above the belt (the grey-white hair).
- TORSO:  gold armour + saturated blue skin (incl. hands).
- COLUMN: water below the belt, above the foam flare.
- FOAM:   water rows where the silhouette flares wider than 1.25x the column's median width
          (the white ring at the floor).
- SPRAY:  low-saturation opaque pixels detached from the main silhouette (droplets).
When the belt is hidden (defence dome, puddle) every low-saturation main-silhouette pixel is
COLUMN/FOAM.

Measurements (units: DEF px per DEF frame; the DEF plays at 12 fps; +y is down on screen):
1. Per consecutive pair (incl. the loop seam for idle / mouseover):
   - the whole silhouette's rigid shift (SSD search +-8 px) = body/column translation;
   - per region, the fraction of overlapping pixels whose colour changed by > 30 (sum RGB)
     after removing that rigid shift ("activity");
   - per COLUMN height band, the band's best rigid shift relative to the silhouette and how much
     better it explains the change than no shift (ratio best/zero; < 0.6 counts as coherent
     motion, ~1.0 means the change is a redraw, not a translation);
   - spray speck count / pixels / centroid and the centroid's velocity;
   - silhouette top / bottom / width.
2. For looping clips (idle, mouseover): a multi-lag velocity search. The texture's velocity v
   must explain frame t -> t+1, t+2 and t+3 at shifts v, 2v, 3v simultaneously, which removes
   the aliasing a single pair has on periodic stripes. Also the lag self-similarity curve: a
   texture that travels is more similar at lag 1 than at lag 4; a texture that is redrawn each
   frame is equally dissimilar at every lag.

Outputs: `<out>/water_motion.json` and `<out>/flow_g<group>.png` (4x contact sheet: change
heat on the water, region outlines, arrows for coherent band motion (cyan), silhouette
translation (white) and spray centroid motion (yellow); arrows are 3x per-frame displacement).

Pure 2D analysis of the extracted DEF PNGs. No Blender, no Unity.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

DEFAULT_DEF_DIR = (
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/"
    "OfflineUnlockMod/homm3_lab/hota_cove_oceanid/extracted_battle_source_12fps/COCEANID.dir"
)
CLIPS = {
    "02": "idle",
    "01": "mouseover",
    "20": "move_start (sink)",
    "21": "move_end (rise)",
    "03": "hitted",
    "04": "defence",
    "12": "attack_front",
    "05": "death",
}
LOOPING = {"02", "01"}
BANDS = 4
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def hsv(rgb: np.ndarray):
    rgbf = rgb.astype(np.float32) / 255.0
    mx = rgbf.max(-1)
    mn = rgbf.min(-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgbf[..., 0], rgbf[..., 1], rgbf[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    return h, s, mx


def segment(rgba: np.ndarray) -> dict:
    rgb = rgba[..., :3]
    opaque = rgba[..., 3] == 255
    h, s, v = hsv(rgb)
    gold = opaque & (h >= 25) & (h <= 65) & (s >= 0.35) & (v >= 0.3)
    skin = opaque & (h >= 195) & (h <= 230) & (s >= 0.42)
    lowsat = opaque & ~gold & ~skin
    lab, n = ndimage.label(opaque, structure=np.ones((3, 3)))
    main = lab == (1 + int(np.argmax(ndimage.sum(opaque, lab, index=np.arange(1, n + 1))))) if n else opaque
    spray = lowsat & ~main
    rows = gold.sum(1)
    belt_y = None
    if gold.sum() >= 25:
        dense = np.nonzero(rows >= max(3, 0.5 * rows.max()))[0]
        belt_y = int(dense.max()) + 1
    water = np.zeros_like(opaque)
    hair = np.zeros_like(opaque)
    if belt_y is not None:
        water[belt_y:] = main[belt_y:] & ~skin[belt_y:] & ~gold[belt_y:]
        hair[:belt_y] = main[:belt_y] & lowsat[:belt_y] & (v[:belt_y] >= 0.5)
    else:
        water = main & lowsat
    torso = main & (gold | skin)
    foam = np.zeros_like(opaque)
    wrows = np.nonzero(water.any(1))[0]
    if len(wrows) >= 6:
        widths = water.sum(1)
        med = np.median(widths[wrows])
        flare = [y for y in wrows if widths[y] > 1.25 * med and y > wrows.min() + 0.5 * (wrows.max() - wrows.min())]
        if flare:
            foam[min(flare):] = water[min(flare):]
    column = water & ~foam
    return {"opaque": opaque, "main": main, "water": water, "column": column, "foam": foam, "hair": hair,
            "torso": torso, "spray": spray, "belt_y": belt_y}


def rigid_shift(a, b, mask, search=8):
    ys, xs = np.nonzero(mask)
    if len(ys) < 20:
        return (0, 0), np.nan, np.nan
    H, W = mask.shape
    costs = {}
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            y2, x2 = ys + dy, xs + dx
            ok = (y2 >= 0) & (y2 < H) & (x2 >= 0) & (x2 < W)
            if ok.mean() < 0.8:
                continue
            costs[(dx, dy)] = float(np.mean((a[ys[ok], xs[ok]] - b[y2[ok], x2[ok]]) ** 2))
    best = min(costs, key=costs.get)
    return best, costs[best], costs.get((0, 0), np.nan)


def highpass(rgba):
    l = rgba[..., :3].astype(np.float32) @ LUMA
    return l - ndimage.gaussian_filter(l, 3)


def multilag_velocity(HP, region, lags=(1, 2, 3), vmax=4.0, step=0.5):
    """Texture velocity that explains t->t+lag at shift lag*v for all lags at once (loops only)."""
    n = len(HP)
    ys, xs = np.nonzero(region)
    if len(ys) < 30:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    vs = np.arange(-vmax, vmax + 1e-6, step)

    def cost(vx, vy):
        c = []
        for lag in lags:
            for t in range(n):
                b = ndimage.shift(HP[(t + lag) % n], (-vy * lag, -vx * lag), order=1, mode="nearest")
                c.append(np.mean((HP[t][y0:y1, x0:x1] - b[y0:y1, x0:x1])[region[y0:y1, x0:x1]] ** 2))
        return float(np.mean(c))

    C = np.array([[cost(vx, vy) for vx in vs] for vy in vs])
    j, i = np.unravel_index(np.argmin(C), C.shape)
    zero = C[len(vs) // 2, len(vs) // 2]
    return {"bestV": [float(vs[i]), float(vs[j])], "bestOverZero": float(C[j, i] / zero),
            "bestOverMedian": float(C[j, i] / np.median(C))}


def lag_similarity(HP, region):
    n = len(HP)
    out = []
    for lag in range(1, n):
        out.append(float(np.mean([np.mean((HP[t][region] - HP[(t + lag) % n][region]) ** 2) for t in range(n)])))
    return out


def boil_stats(rgba, segs, column, foam):
    """Does the texture re-roll? Highlight survival vs chance, silhouette edge jitter, area."""
    n = len(rgba)
    out = {}
    for name, R in (("column", column), ("foam", foam)):
        hl = [((r[..., :3].astype(np.float32) @ LUMA) > 200) & R for r in rgba]
        keep, chance = [], []
        for t in range(n):
            near = ndimage.binary_dilation(hl[(t + 1) % n], np.ones((3, 3)))
            keep.append(float((hl[t] & near).sum() / max(1, hl[t].sum())))
            chance.append(float(near[R].mean()))
        out[name] = {"highlightPxPerFrame": [int(h.sum()) for h in hl],
                     "highlightSurvivesWithin1px": float(np.mean(keep)),
                     "chanceLevel": float(np.mean(chance))}
    main = [s["main"] for s in segs]
    wy = np.nonzero(column.any(1))[0]
    fy = np.nonzero(foam.any(1))[0]

    def edge_std(rows):
        L, R = [], []
        for y in rows:
            l = [np.nonzero(m[y])[0].min() for m in main if m[y].any()]
            r = [np.nonzero(m[y])[0].max() for m in main if m[y].any()]
            if len(l) == n:
                L.append(np.std(l))
                R.append(np.std(r))
        return float(np.mean(L)) if L else None, float(np.mean(R)) if R else None

    out["columnEdgeStdPx"] = edge_std(wy)
    out["foamEdgeStdPx"] = edge_std(fy)
    out["waterAreaPx"] = [int(s["water"].sum()) for s in segs]
    return out


def analyse_clip(files, loop):
    rgba = [np.array(Image.open(f).convert("RGBA")) for f in files]
    F = [r.astype(np.float32) for r in rgba]
    segs = [segment(r) for r in rgba]
    HP = [highpass(r) for r in rgba]
    n = len(files)
    pairs = [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if loop else [])
    recs = []
    for i, j in pairs:
        sa, sb = segs[i], segs[j]
        a, b = F[i][..., :3], F[j][..., :3]
        (sx, sy), _, _ = rigid_shift(a, b, sa["main"])
        H, W = sa["main"].shape
        bs = np.roll(np.roll(b, -sy, 0), -sx, 1)
        segb = {k: (np.roll(np.roll(v, -sy, 0), -sx, 1) if isinstance(v, np.ndarray) else v) for k, v in sb.items()}
        changed = np.abs(a - bs).sum(-1) > 30
        rec = {"pair": [i, j], "beltY": sa["belt_y"], "silhouetteShift": [sx, sy]}
        for k in ("hair", "torso", "column", "foam"):
            ov = sa[k] & segb["opaque"]
            rec[k + "Px"] = int(sa[k].sum())
            rec[k + "Changed"] = float((changed & ov).sum() / ov.sum()) if ov.sum() >= 10 else None
        wy = np.nonzero(sa["main"].any(1))[0]
        wx = np.nonzero(sa["main"].any(0))[0]
        rec["silhouette"] = {"top": int(wy.min()), "bottom": int(wy.max()), "left": int(wx.min()), "right": int(wx.max())}
        # column bands: residual rigid motion relative to the silhouette
        cy = np.nonzero(sa["column"].any(1))[0]
        bands = []
        if len(cy) >= BANDS * 3:
            hb = np.roll(np.roll(HP[j], -sy, 0), -sx, 1)
            for k in range(BANDS):
                y0 = cy.min() + (cy.max() + 1 - cy.min()) * k // BANDS
                y1 = cy.min() + (cy.max() + 1 - cy.min()) * (k + 1) // BANDS
                m = sa["column"].copy()
                m[:y0] = False
                m[y1:] = False
                (dx, dy), cb, cz = rigid_shift(HP[i], hb, m, search=5)
                ratio = cb / cz if cz and cz > 0 else 1.0
                coherent = ratio < 0.6 and max(abs(dx), abs(dy)) < 5
                bands.append({"y0": int(y0), "y1": int(y1), "shift": [dx, dy], "bestOverZero": float(ratio),
                              "coherent": bool(coherent)})
        rec["columnBands"] = bands
        # spray
        lab, ns = ndimage.label(sa["spray"], structure=np.ones((3, 3)))
        rec["spraySpecks"] = int(ns)
        rec["sprayPx"] = int(sa["spray"].sum())
        if sa["spray"].sum() >= 5:
            ys, xs = np.nonzero(sa["spray"])
            rec["sprayCentroid"] = [float(xs.mean()), float(ys.mean())]
            if sb["spray"].sum() >= 5:
                ys2, xs2 = np.nonzero(sb["spray"])
                rec["sprayVelocity"] = [float(xs2.mean() - xs.mean()), float(ys2.mean() - ys.mean())]
        recs.append(rec)
    loopinfo = None
    if loop:
        region = segs[0]["column"].copy()
        for s in segs:
            region &= s["column"]
        foam = segs[0]["foam"].copy()
        for s in segs:
            foam &= s["foam"]
        hair = segs[0]["hair"].copy()
        for s in segs:
            hair &= s["hair"]
        loopinfo = {
            "boil": boil_stats(rgba, segs, region, foam),
            "columnVelocity": multilag_velocity(HP, region),
            "foamVelocity": multilag_velocity(HP, foam),
            "hairVelocity": multilag_velocity(HP, hair),
            "columnLagDissimilarity": lag_similarity(HP, region),
            "foamLagDissimilarity": lag_similarity(HP, foam),
            "hairLagDissimilarity": lag_similarity(HP, hair),
        }
    return rgba, segs, recs, loopinfo


def draw_sheet(rgba, segs, recs, path: Path, box, scale=4):
    x0, y0, x1, y1 = box
    W, H = (x1 - x0) * scale, (y1 - y0) * scale
    sheet = Image.new("RGB", (W * len(recs), H + 16), (58, 86, 58))
    colours = {"hair": (255, 140, 255), "column": (80, 200, 255), "foam": (255, 255, 255), "spray": (255, 230, 40)}
    for k, rec in enumerate(recs):
        i, j = rec["pair"]
        sa = segs[i]
        base = rgba[i].astype(np.float32).copy()
        sx, sy = rec["silhouetteShift"]
        nb = np.roll(np.roll(rgba[j].astype(np.float32), -sy, 0), -sx, 1)
        changed = (np.abs(base[..., :3] - nb[..., :3]).sum(-1) > 30) & (sa["column"] | sa["foam"] | sa["hair"])
        base[..., :3][changed] = 0.45 * base[..., :3][changed] + 0.55 * np.array([255, 60, 60])
        fr = Image.fromarray(base.astype(np.uint8)).crop(box).resize((W, H), Image.NEAREST)
        tile = Image.new("RGB", (W, H), (58, 86, 58))
        tile.paste(fr, (0, 0), fr)
        arr = np.array(tile)
        for name, col in colours.items():
            m = sa[name][y0:y1, x0:x1]
            edge = m & ~ndimage.binary_erosion(m)
            e = np.kron(edge, np.ones((scale, scale), bool))
            arr[e] = col
        tile = Image.fromarray(arr)
        d = ImageDraw.Draw(tile)

        def arrow(px, py, dx, dy, col):
            sxp, syp = (px - x0) * scale, (py - y0) * scale
            ex, ey = sxp + dx * scale * 3, syp + dy * scale * 3
            d.line([(sxp, syp), (ex, ey)], fill=col, width=3)
            d.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], fill=col)

        m = sa["main"]
        ys, xs = np.nonzero(m)
        arrow(xs.mean(), ys.mean(), sx, sy, (255, 255, 255))
        cxs = np.nonzero(sa["column"].any(0))[0]
        for b in rec["columnBands"]:
            if b["coherent"] and len(cxs):
                arrow(0.5 * (cxs.min() + cxs.max()), 0.5 * (b["y0"] + b["y1"]), b["shift"][0], b["shift"][1], (0, 255, 255))
        if "sprayVelocity" in rec:
            arrow(rec["sprayCentroid"][0], rec["sprayCentroid"][1], *rec["sprayVelocity"], (255, 230, 40))
        sheet.paste(tile, (k * W, 0))
        dd = ImageDraw.Draw(sheet)
        dd.text((k * W + 3, H + 2), f"{i}->{j} col{_fmt(rec['columnChanged'])} foam{_fmt(rec['foamChanged'])} hair{_fmt(rec['hairChanged'])}", fill=(255, 255, 255))
    sheet.save(path)


def _fmt(v):
    return "--" if v is None else f"{v:.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--def-dir", default=DEFAULT_DEF_DIR)
    ap.add_argument("--out", default="artifacts/homm3_vfx_experiments/oceanid/evidence")
    ap.add_argument("--clips", default=",".join(CLIPS))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "water_motion.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    report.update({"source": args.def_dir, "units": "DEF px per DEF frame (12 fps); +y is down on screen"})
    report.setdefault("clips", {})
    for g in args.clips.split(","):
        files = sorted(glob.glob(os.path.join(args.def_dir, f"{g}_*.png")))
        rgba, segs, recs, loopinfo = analyse_clip(files, g in LOOPING)
        m = np.zeros(rgba[0].shape[:2], bool)
        for s in segs:
            m |= s["opaque"]
        ys, xs = np.nonzero(m)
        box = (int(xs.min()) - 3, int(ys.min()) - 3, int(xs.max()) + 4, int(ys.max()) + 4)
        draw_sheet(rgba, segs, recs, out / f"flow_g{g}.png", box)
        report["clips"][g] = {"name": CLIPS[g], "frames": len(files), "loop": g in LOOPING, "pairs": recs,
                              "loopAnalysis": loopinfo}
        print(f"== g{g} {CLIPS[g]} ({len(files)} frames)")
        for r in recs:
            cb = " ".join(
                f"{b['shift'][0]:+d},{b['shift'][1]:+d}{'*' if b['coherent'] else ''}({b['bestOverZero']:.2f})"
                for b in r["columnBands"])
            sp = f" spray {r['spraySpecks']}/{r['sprayPx']}px v={np.round(r.get('sprayVelocity', [np.nan, np.nan]), 1).tolist()}" if r["sprayPx"] else ""
            print(f" {r['pair']} sil{r['silhouetteShift']} top={r['silhouette']['top']} chg col={_fmt(r['columnChanged'])} "
                  f"foam={_fmt(r['foamChanged'])} hair={_fmt(r['hairChanged'])} torso={_fmt(r['torsoChanged'])} | bands {cb}{sp}")
        if loopinfo:
            print("  loop:", json.dumps({k: (np.round(v, 0).tolist() if isinstance(v, list) else v) for k, v in loopinfo.items()}))
    report_path.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
