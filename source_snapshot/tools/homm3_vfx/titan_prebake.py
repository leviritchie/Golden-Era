"""Titan (h3_giant_upg) prebake: the prebaked-lighting v6 recipe plus a per-material grade.

Builds on tools/homm3_prebake/prebake_lab.py (imported, not modified): same UV terms, same views, same
Hex/Lit relight model. What it adds is option ``v6m``: the v6 bake graded per material class instead of
with one global grade, because the Titan's DEF mixes saturated gold armour, low-chroma lavender-grey
skin, a dark red crest and a white/pale-blue bolt, and a single global grade cannot fit all four
(the global v6 fit lands on the exposure bound and bleaches the gold).

Classes are soft weights from the Meshy base colour's CIELAB chroma/hue, so the grade is still baked
into the base colour, yaw-invariant, and needs nothing the runtime lacks. Each class grade
[exposure, gamma, sat, wr, wb] is fitted (Nelder-Mead) to the same class's DEF L*a*b* percentiles
under the sand-arena Hex/Lit relight at the sprite camera.

    python tools/homm3_vfx/titan_prebake.py        (after bake_terms.py, render_passes.py, prebake_lab.py)

Proof tier: generated artifact (numpy relight of Blender Cycles passes).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, optimize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
sys.path.insert(0, str(Path(__file__).parent))
import prebake_lab as pl  # noqa: E402
import h3def  # noqa: E402
from titan_vfx_textures import lightning_mask  # noqa: E402

OUT = ROOT / "artifacts/homm3_prebaked_lighting/titan"
UNIT = "h3_giant_upg"
CLASSES = ("gold", "grey", "red", "blue")
KNOBS = {"aoGamma": 1.4, "creviceGammaScale": 2.0, "skyFloor": 0.35, "heightDepth": 0.15,
         "heightPower": 0.6, "detailAmount": 1.0, "detailSigma": 12.0,
         # per-class contrast: the DEF gold reads as polished metal (umber crevices, cream tops), which
         # Hex/Lit cannot make (no specular), so gold gets a steeper occlusion curve and a yaw-invariant
         # top-light sheen baked in; skin a milder one.
         "classShadingPower": {"gold": 2.0, "grey": 1.2, "red": 1.0, "blue": 1.0},
         "goldTopSheen": 1.5}


def smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def class_weights(lab: np.ndarray) -> np.ndarray:
    """Soft material weights (..., 4) from CIELAB: gold, grey, red, blue (sum 1)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360
    gold = smooth(C, 7, 15) * smooth(h, 45, 55) * (1 - smooth(h, 100, 115))
    red = smooth(C, 14, 24) * np.maximum(1 - smooth(h, 38, 50), smooth(h, 330, 345))
    blue = smooth(C, 6, 12) * smooth(h, 185, 200) * (1 - smooth(h, 280, 300))
    grey = np.clip(1 - gold - red - blue, 0, 1)
    w = np.stack([gold, grey, red, blue], -1)
    return w / np.maximum(w.sum(-1, keepdims=True), 1e-6)


def def_targets(views, vmeta, frames_meta):
    """Per-class DEF L*a*b* samples at the sprite frames. The bolt ('blue') target is the DEF's own
    lightning pixels; the other classes use the body minus lightning."""
    d = h3def.read_def("cgtita.def")
    out = {c: [] for c in CLASSES}
    defs = {}
    for n in views:
        frame = vmeta["views"][n]["frame"]
        src = Path(frames_meta["sources"][frame - 1])
        rgba = pl.load_rgba(src)
        mask = pl.def_mask(rgba)
        g, i = (int(x) for x in src.stem.split("_"))
        lm = lightning_mask(d.groups[g][i], d.palette)
        lab = pl.lin_to_lab(pl.srgb_to_lin(rgba[..., :3]))
        w = class_weights(lab)
        body = mask & ~lm
        cls = np.argmax(w, -1)
        for ci, c in enumerate(CLASSES[:3]):
            sel = body & (cls == ci) & (w[..., ci] > 0.6)
            out[c].append(lab[sel])
        out["blue"].append(lab[mask & lm])
        defs[n] = {"src": str(src), "rgba": rgba, "mask": mask}
    return {c: np.concatenate(v) for c, v in out.items()}, defs


def main() -> int:
    frames_meta = json.loads((ROOT / f"artifacts/homm3_def_retarget/{UNIT}/{UNIT}_def_retarget.blend.frames.json").read_text())
    vmeta = json.loads((OUT / "views/views_meta.json").read_text())
    terms = pl.load_terms(OUT)
    m = pl.base_maps(OUT, terms)
    views = {n: dict(np.load(OUT / "views" / f"{n}.npz")) for n in vmeta["views"]}
    sprite_views = [n for n in views if n.startswith("sprite_")]
    battle_views = ["battle_faces_right", "battle_faces_left", "battle_faces_camera", "battle_faces_away"]

    alb = pl.detail_boost(m["albedo"], m["valid"], KNOBS["detailAmount"], KNOBS["detailSigma"])
    sh6 = pl.shading("v6_sprite_match", m, KNOBS)
    v6raw = alb * sh6[..., None]
    top = m["suns"].get("top", np.zeros_like(sh6))

    def class_raw(c):
        sh = np.power(np.clip(sh6, 1e-4, None), KNOBS["classShadingPower"][c])
        if c == "gold":
            sh = sh * (1 + KNOBS["goldTopSheen"] * np.clip(top, 0, 1) ** 2)
        return alb * sh[..., None]
    craw = {c: class_raw(c) for c in CLASSES}
    wtex = class_weights(pl.lin_to_lab(m["albedo"]))
    wtex = np.stack([ndimage.gaussian_filter(wtex[..., i], 1.5) for i in range(4)], -1)
    wtex /= np.maximum(wtex.sum(-1, keepdims=True), 1e-6)

    targets, defs = def_targets(sprite_views, vmeta, frames_meta)
    q = np.linspace(4, 96, 17)
    samples = {c: [] for c in CLASSES}
    for n in sprite_views:
        v = views[n]
        sel = np.nonzero(v["alpha"] > 0.99)
        idx = np.random.default_rng(3).choice(len(sel[0]), size=min(60000, len(sel[0])), replace=False)
        rows, cols = sel[0][idx], sel[1][idx]
        uv = v["uv"][rows, cols]
        light = pl.runtime_light(v, "sand")[rows, cols]
        wc = pl.sample_tex(wtex, uv[None])[0]
        for ci, c in enumerate(CLASSES):
            s = wc[:, ci] > 0.7
            col = pl.sample_tex(craw[c], uv[s][None])[0]
            samples[c].append((col, light[s]))

    grades = {}
    fit_report = {}
    for c in CLASSES:
        cols = np.concatenate([a for a, _ in samples[c]])
        lights = np.concatenate([b for _, b in samples[c]])
        tgt = [np.percentile(targets[c][:, i], q) for i in range(3)]

        def cost(g):
            if not (0 < g[0] < 30 and 0.4 <= g[1] <= 2.0 and 0.3 <= g[2] <= 3.0
                    and 0.6 <= g[3] <= 1.6 and 0.5 <= g[4] <= 1.4):
                return 1e6
            lab = pl.lin_to_lab(pl.grade(cols, g) * lights)
            return sum(np.mean(np.abs(np.percentile(lab[:, i], q) - tgt[i])) * w for i, w in ((0, 1.0), (1, 0.8), (2, 0.8)))

        best = min((optimize.minimize(cost, x0, method="Nelder-Mead", options={"maxiter": 900, "xatol": 1e-3, "fatol": 1e-3})
                    for x0 in ([3.0, 1.0, 1.2, 1.0, 1.0], [8.0, 0.9, 1.6, 1.1, 0.8], [1.5, 1.1, 0.8, 1.0, 1.0])),
                   key=lambda r: r.fun)
        grades[c] = best.x.astype(np.float32)
        lab = pl.lin_to_lab(pl.grade(cols, grades[c]) * lights)
        fit_report[c] = {"grade": np.round(best.x, 3).tolist(), "cost": round(float(best.fun), 2),
                         "texSamples": int(len(cols)), "defSamples": int(len(targets[c])),
                         "defMedianLab": np.round(np.median(targets[c], 0), 1).tolist(),
                         "fitMedianLab": np.round(np.median(lab, 0), 1).tolist(),
                         "defL_p10_50_90": np.round(np.percentile(targets[c][:, 0], [10, 50, 90]), 1).tolist(),
                         "fitL_p10_50_90": np.round(np.percentile(lab[:, 0], [10, 50, 90]), 1).tolist()}
        print(c, fit_report[c], flush=True)

    v6m = sum(wtex[..., i:i + 1] * pl.grade(craw[c], grades[c]) for i, c in enumerate(CLASSES))
    v6m = np.where(m["valid"][..., None], v6m, m["albedo"])
    tex_dir = OUT / "textures"
    tex_dir.mkdir(exist_ok=True)
    Image.fromarray((pl.lin_to_srgb(v6m) * 255 + 0.5).astype(np.uint8)).save(tex_dir / "v6m_material_grade_basecolor.png")

    variants = {"raw": m["albedo"],
                "v6": pl.srgb_to_lin(np.asarray(Image.open(tex_dir / "v6_sprite_match_basecolor.png").convert("RGB"), np.float32) / 255.0),
                "v6m": v6m}
    metrics = {"proof": "generated artifact: numpy relight of Blender Cycles passes with the Hex/Lit model",
               "knobs": KNOBS, "classFit": fit_report, "sprite": {}, "battle": {}}
    for n in sprite_views:
        metrics["sprite"][n] = {}
        dl = pl.lin_to_lab(pl.srgb_to_lin(defs[n]["rgba"][..., :3]))[..., 0][defs[n]["mask"]]
        for name, t in variants.items():
            col, al = pl.render_view(t, views[n], "game", "sand", vmeta["views"][n]["supersample"])
            mask = al > 0.9
            lab = pl.lin_to_lab(col)
            blur = ndimage.gaussian_filter(lab[..., 0], 1)
            metrics["sprite"][n][name] = {
                "meanL": round(float(lab[..., 0][mask].mean()), 1),
                "LhistDistanceToDEF": round(pl.hist_distance(lab[..., 0][mask], dl), 2),
                "localContrast": round(float(np.abs(lab[..., 0] - blur)[mask].mean()), 2)}
        metrics["sprite"][n]["DEF"] = {"meanL": round(float(dl.mean()), 1)}
    for name, t in variants.items():
        per = {}
        for bv in battle_views:
            col, al = pl.render_view(t, views[bv], "game", "sand", vmeta["views"][bv]["supersample"])
            per[bv] = round(float(pl.lin_to_lab(col)[..., 0][al > 0.9].mean()), 1)
        per["facingSpreadL"] = round(max(per.values()) - min(per.values()), 1)
        metrics["battle"][name] = per
    (OUT / "metrics_titan_v6m.json").write_text(json.dumps(metrics, indent=1))

    # sheets: sprite camera (DEF | raw | v6 | v6m) and four battle facings
    sheets = OUT / "sheets"
    sheets.mkdir(exist_ok=True)
    rows = []
    for n in sprite_views:
        cells = [(defs[n]["rgba"][..., :3], defs[n]["rgba"][..., 3] * defs[n]["mask"], "DEF " + Path(defs[n]["src"]).stem)]
        for name, t in variants.items():
            col, al = pl.render_view(t, views[n], "game", "sand", vmeta["views"][n]["supersample"])
            cells.append((pl.lin_to_srgb(col), al, name + " (Hex/Lit relight)"))
        rows.append(cells)
    sheet_rows(rows, sheets / "titan_sprite_cam_v6m.png", scale=3)
    rows = []
    for name, t in variants.items():
        cells = []
        for bv in battle_views:
            col, al = pl.render_view(t, views[bv], "game", "sand", vmeta["views"][bv]["supersample"])
            cells.append((pl.lin_to_srgb(col), al, f"{name} {bv[7:]}"))
        rows.append(cells)
    sheet_rows(rows, sheets / "titan_battle_facings_v6m.png", scale=3)
    print("wrote", OUT / "metrics_titan_v6m.json")
    return 0


def sheet_rows(rows, path, scale=3, bg=(46, 46, 46)):
    imgs = []
    for cells in rows:
        boxes = [np.argwhere(a > 0.5) for _, a, _ in cells]
        y0 = min(b[:, 0].min() for b in boxes) - 4
        y1 = max(b[:, 0].max() for b in boxes) + 4
        row = []
        for (rgb, a, lab), b in zip(cells, boxes):
            x0, x1 = b[:, 1].min() - 4, b[:, 1].max() + 4
            c = np.clip(rgb[y0:y1, x0:x1], 0, 1)
            al = np.clip(a[y0:y1, x0:x1], 0, 1)[..., None]
            im = (c * al + np.array(bg) / 255 * (1 - al)) * 255
            img = Image.fromarray(im.astype(np.uint8)).resize((im.shape[1] * scale, im.shape[0] * scale), Image.NEAREST)
            canvas = Image.new("RGB", (img.width, img.height + 16), bg)
            canvas.paste(img, (0, 16))
            ImageDraw.Draw(canvas).text((3, 2), lab, fill=(255, 255, 0))
            row.append(canvas)
        w = sum(r.width for r in row) + 6 * len(row)
        out = Image.new("RGB", (w, max(r.height for r in row)), bg)
        x = 0
        for r in row:
            out.paste(r, (x, 0))
            x += r.width + 6
        imgs.append(out)
    sheet = Image.new("RGB", (max(i.width for i in imgs), sum(i.height + 6 for i in imgs)), bg)
    y = 0
    for i in imgs:
        sheet.paste(i, (0, y))
        y += i.height + 6
    sheet.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
