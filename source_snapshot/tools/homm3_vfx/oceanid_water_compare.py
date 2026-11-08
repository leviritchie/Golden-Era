"""Compare the oceanid flowing-water variants against the DEF on motion, not on looks.

Inputs: DEF frames (oceanid_water_motion.DEFAULT_DEF_DIR) and the Unity-editor renders from
oceanid_unity_lab.py (renders/<variant>/<clip>_<i>.png at 2x, plus renders/mask/ with vertex-colour
region masks r = water, g = foam). Renders are box-reduced to DEF resolution and every metric runs the
same code on the DEF and on each variant:

  waterChanged / torsoChanged  fraction of region pixels whose colour changes frame to frame
                               (after the rigid silhouette shift, as in the characterisation)
  velocity                     multi-lag texture velocity in the column over the idle loop; the DEF
                               boils in place (bestOverZero ~1, no velocity)
  lagFlatness                  min/max of the lag dissimilarity curve; ~1 = independent redraws
  highlightSurvival            share of the brightest 5.4% water pixels that are still highlights
                               within 1 px next frame, against the chance level
  silhouetteIoU                DEF opaque vs render alpha, per frame (alignment check)

Outputs under artifacts/homm3_vfx_experiments/oceanid/compare/: compare_metrics.json,
compare_summary.txt, sheet_<clip>.png (DEF | current | variants, rows = frames), <clip>.gif and
<clip>.mp4 (same panels side by side at the DEF's 12 fps), and a water-zoom sheet.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from oceanid_water_motion import DEFAULT_DEF_DIR, LUMA, highpass, lag_similarity, multilag_velocity, rigid_shift

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "artifacts/homm3_vfx_experiments/oceanid"
RENDERS = EXP / "renders"
OUT = EXP / "compare"
VARIANTS = ["current", "A_uvscroll", "B_flipbook", "B2_defpalette", "C_shell", "D_flag"]
LABELS = {"DEF": "DEF (HoMM3)", "current": "current mesh", "A_uvscroll": "A native _UvScroll",
          "B_flipbook": "B stepped boil atlas", "B2_defpalette": "B2 boil, DEF palette", "C_shell": "C sparkle shell", "D_flag": "D Hex/Lit flag"}
HL_FRAC = 0.054  # DEF column highlight fraction (cells.json defStats)
DISP = 4         # display scale relative to DEF px


def load_clip(variant: str, clip: str, n: int):
    if variant == "DEF":
        return None
    out = []
    for i in range(n):
        im = Image.open(RENDERS / variant / f"{clip}_{i:02d}.png").convert("RGBA")
        out.append(im)
    return out


def def_frames(group: str):
    files = sorted(Path(DEFAULT_DEF_DIR).glob(f"{group}_*.png"))
    return [Image.open(f).convert("RGBA") for f in files]


def reduce(im: Image.Image) -> np.ndarray:
    return np.array(im.reduce(2))


def regions_from_mask(mask_rgba: np.ndarray):
    a = mask_rgba[..., 3] > 127
    water = a & (mask_rgba[..., 0] > 127)
    foam = water & (mask_rgba[..., 1] > 127)
    return {"opaque": a, "water": water, "column": water & ~foam, "foam": foam, "torso": a & ~water}


def changed_fracs(frames, regs, loop):
    n = len(frames)
    pairs = [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if loop else [])
    rec = {"water": [], "torso": [], "waterNorm": [], "torsoNorm": []}
    for i, j in pairs:
        a = frames[i][..., :3].astype(np.float32)
        b = frames[j][..., :3].astype(np.float32)
        (sx, sy), _, _ = rigid_shift(a, b, regs[i]["opaque"])
        bs = np.roll(np.roll(b, -sy, 0), -sx, 1)
        ob = np.roll(np.roll(regs[j]["opaque"], -sy, 0), -sx, 1)
        ch = np.abs(a - bs).sum(-1) > 30
        dl = np.abs((a - bs) @ LUMA)
        la = a @ LUMA
        for k in ("water", "torso"):
            m = regs[i][k] & ob
            ok = m.sum() >= 10
            rec[k].append(float((ch & m).sum() / m.sum()) if ok else None)
            # contrast-invariant: change larger than half the region's own luma spread this frame
            rec[k + "Norm"].append(float(((dl > 0.5 * la[m].std()) & m).sum() / m.sum()) if ok else None)
    return {k: (float(np.mean([x for x in v if x is not None])) if any(x is not None for x in v) else None) for k, v in rec.items()}


def highlight_survival(frames, region, base=None):
    """base: the current-mesh frames; dividing by them removes lighting and the static albedo, so the
    highlights ranked are the ones the variant adds (the DEF has no base: its pixels are the art)."""
    n = len(frames)
    L = [f[..., :3].astype(np.float32) @ LUMA for f in frames]
    if base is not None:
        L = [l / np.maximum(b[..., :3].astype(np.float32) @ LUMA, 8.0) for l, b in zip(L, base)]
    hl = []
    for l in L:
        thr = np.quantile(l[region], 1 - HL_FRAC)
        hl.append((l >= thr) & region)
    keep, chance = [], []
    for t in range(n):
        near = ndimage.binary_dilation(hl[(t + 1) % n], np.ones((3, 3)))
        keep.append(float((hl[t] & near).sum() / max(1, hl[t].sum())))
        chance.append(float(near[region].mean()))
    return {"survival": float(np.mean(keep)), "chance": float(np.mean(chance))}


def loop_metrics(frames, regs, base=None):
    col = regs[0]["column"].copy()
    for r in regs:
        col &= r["column"]
    col = ndimage.binary_erosion(col, np.ones((3, 3)))
    HP = [highpass(f) for f in frames]
    lag = lag_similarity(HP, col)
    return {"columnPx": int(col.sum()), "velocity": multilag_velocity(HP, col),
            "lagDissimilarity": lag, "lagFlatness": float(min(lag) / max(lag)) if lag else None,
            "highlight": highlight_survival(frames, col, base)}


def def_regions(frames):
    from oceanid_water_motion import segment
    out = []
    for f in frames:
        s = segment(f)
        out.append({"opaque": s["opaque"], "water": s["water"], "column": s["column"], "foam": s["foam"], "torso": s["torso"]})
    return out


def bbox_union(arrs, margin=6):
    ys, xs = [], []
    for a in arrs:
        yy, xx = np.nonzero(a[..., 3] > 0)
        if len(yy):
            ys += [yy.min(), yy.max()]
            xs += [xx.min(), xx.max()]
    H, W = arrs[0].shape[:2]
    return (max(0, min(xs) - margin), max(0, min(ys) - margin), min(W, max(xs) + margin + 1), min(H, max(ys) + margin + 1))


def panel(im_def_px: np.ndarray, box, bg=(38, 44, 52)):
    x0, y0, x1, y1 = box
    crop = Image.fromarray(im_def_px[y0:y1, x0:x1])
    base = Image.new("RGBA", crop.size, bg + (255,))
    base.alpha_composite(crop)
    return base.convert("RGB")


def render_panel(im2x: Image.Image, box, bg=(38, 44, 52)):
    x0, y0, x1, y1 = box
    crop = im2x.crop((2 * x0, 2 * y0, 2 * x1, 2 * y1))
    base = Image.new("RGBA", crop.size, bg + (255,))
    base.alpha_composite(crop)
    return base.convert("RGB")


def compose_row(def_img, renders2x, box, labels=True):
    w, h = (box[2] - box[0]) * DISP, (box[3] - box[1]) * DISP
    cols = [panel(def_img, box).resize((w, h), Image.NEAREST)]
    for r in renders2x:
        cols.append(render_panel(r, box).resize((w, h), Image.LANCZOS))
    head = 16 if labels else 0
    row = Image.new("RGB", (w * len(cols), h + head), (20, 22, 26))
    d = ImageDraw.Draw(row)
    names = ["DEF"] + VARIANTS
    for k, c in enumerate(cols):
        row.paste(c, (k * w, head))
        if labels:
            d.text((k * w + 4, 2), LABELS[names[k]], fill=(230, 230, 230))
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cells = json.loads((EXP / "work/cells.json").read_text())
    report = json.loads((RENDERS / "lab_report.json").read_text())
    metrics = {"proofTier": "Unity-editor-rendered (lab replica of Hex/Lit), DEF = shipped HoMM3 sprite",
               "labReport": {k: report[k] for k in ("import", "importedIdleCurveKinds") if k in report}, "clips": {}}
    st = report.get("animatorMaterialST", [])
    metrics["animatorSTMatches"] = {v: f"{sum(1 for r in st if r['variant'] == v and r['matches'])}/{sum(1 for r in st if r['variant'] == v)}"
                                   for v in ("B_flipbook", "B2_defpalette", "C_shell")}
    ff = shutil.which("ffmpeg")
    for clip, info in cells["clips"].items():
        dframes = def_frames(info["group"])
        n = len(dframes)
        D = [np.array(f) for f in dframes]
        dregs = def_regions(D)
        loop = info["group"] in ("02", "01")
        masks = [regions_from_mask(reduce(m)) for m in load_clip("mask", clip, n)]
        R2 = {v: load_clip(v, clip, n) for v in VARIANTS}
        R = {v: [reduce(im) for im in R2[v]] for v in VARIANTS}
        cm = {"DEF": changed_fracs(D, dregs, loop)}
        for v in VARIANTS:
            cm[v] = changed_fracs(R[v], masks, loop)
        iou = []
        for i in range(n):
            a = D[i][..., 3] == 255
            b = masks[i]["opaque"]
            iou.append(float((a & b).sum() / max(1, (a | b).sum())))
        rec = {"frames": n, "changed": cm, "silhouetteIoUMeanMin": [float(np.mean(iou)), float(np.min(iou))]}
        if clip == "Unit_Idle":
            rec["loop"] = {"DEF": loop_metrics(D, dregs)}
            for v in VARIANTS:
                rec["loop"][v] = loop_metrics(R[v], masks, None if v == "current" else R["current"])
        metrics["clips"][clip] = rec

        box = bbox_union(D + [np.array(m) for m in [R2["current"][i].reduce(2) for i in range(n)]])
        rows = [compose_row(D[i], [R2[v][i] for v in VARIANTS], box, labels=(i == 0)) for i in range(n)]
        sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), (20, 22, 26))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height
        sheet.save(OUT / f"sheet_{clip}.png")
        gif_rows = [compose_row(D[i], [R2[v][i] for v in VARIANTS], box, labels=True) for i in range(n)]
        gif_rows[0].save(OUT / f"{clip}.gif", save_all=True, append_images=gif_rows[1:], duration=83, loop=0)
        if ff:
            tmp = OUT / "_mp4"
            tmp.mkdir(exist_ok=True)
            reps = 4 if loop else 1
            k = 0
            for _ in range(reps):
                for r in gif_rows:
                    r.save(tmp / f"f{k:04d}.png")
                    k += 1
            W, H = gif_rows[0].size
            subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", "12", "-i", str(tmp / "f%04d.png"),
                            "-vf", f"pad={W + W % 2}:{H + H % 2}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                            str(OUT / f"{clip}.mp4")], check=True)
            shutil.rmtree(tmp)

    # water zoom (idle, first 4 frames): the column at 8x DEF px
    dframes = [np.array(f) for f in def_frames("02")]
    ys, xs = np.nonzero(def_regions(dframes)[0]["water"])
    zbox = (int(xs.min()) - 3, int(ys.min()) - 3, int(xs.max()) + 4, int(ys.max()) + 4)
    global DISP
    DISP = 8
    zrows = [compose_row(dframes[i], [load_clip(v, "Unit_Idle", 8)[i] for v in VARIANTS], zbox, labels=(i == 0)) for i in range(4)]
    z = Image.new("RGB", (zrows[0].width, sum(r.height for r in zrows)), (20, 22, 26))
    y = 0
    for r in zrows:
        z.paste(r, (0, y))
        y += r.height
    z.save(OUT / "water_zoom_idle.png")

    (OUT / "compare_metrics.json").write_text(json.dumps(metrics, indent=1))
    lines = [f"proof tier: {metrics['proofTier']}", f"animator ST readback: {metrics['animatorSTMatches']}", ""]
    for clip, rec in metrics["clips"].items():
        lines.append(f"{clip}: IoU mean/min {rec['silhouetteIoUMeanMin'][0]:.2f}/{rec['silhouetteIoUMeanMin'][1]:.2f}")
        for v, c in rec["changed"].items():
            w = "--" if c["water"] is None else f"{c['water']:.2f}"
            t = "--" if c["torso"] is None else f"{c['torso']:.2f}"
            wn = "--" if c["waterNorm"] is None else f"{c['waterNorm']:.2f}"
            tn = "--" if c["torsoNorm"] is None else f"{c['torsoNorm']:.2f}"
            lines.append(f"   {v:13s} waterChanged {w} (norm {wn})  torsoChanged {t} (norm {tn})")
        if "loop" in rec:
            for v, L in rec["loop"].items():
                vel = L["velocity"]
                lines.append(f"   loop {v:12s} vel {vel['bestV'] if vel else None} best/zero {vel['bestOverZero'] if vel else float('nan'):.3f}"
                             f"  lagFlat {L['lagFlatness']:.2f}  hl {L['highlight']['survival']:.2f} vs chance {L['highlight']['chance']:.2f}")
    (OUT / "compare_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
