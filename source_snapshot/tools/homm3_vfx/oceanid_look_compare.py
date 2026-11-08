"""Compare the oceanid look-lab v2 renders (lighting + flow + accents) against the DEF.

Inputs: renders_v2/<variant>/<clip>_<i>.png (Unity-editor-rendered, 2x, oceanid_unity_lab.py --v2),
renders_v2/mask (COLOR_0 r = water, g = foam), look/accents/<id>_mask_<i>.png (DEF effect masks) and the DEF.

Metrics (same code on the DEF and every variant, renders box-reduced to DEF px):
  colour      L*a*b* percentile distance (p10..p90, weights L 1, a/b 0.7) per region, pooled over every clip
              frame: column, foam, body, and "all" = whole opaque sprite incl. spray/accents (effects on)
  motion      waterChanged norm, lag flatness, highlight survival (oceanid_water_compare), and the column
              texture velocity: the DEF boils in place (bestOverZero ~1); a readable flow has a clear
              downward velocity (bestV y > 0, bestOverZero well below 1)
  stepping    share of the column's high-pass change that happens across DEF frame boundaries in the
              48 fps idle subsample: 1.0 = holds for a whole 12 fps frame like the DEF, 0.25 = continuous
  accents     IoU / precision / recall of accents_only alpha against the DEF effect mask, per layer

Outputs: artifacts/homm3_vfx_experiments/oceanid/compare_v2/ (look_metrics.json, look_summary.txt,
sheet_<clip>.png, <clip>.gif/.mp4, idle_sub48.gif/.mp4, colour_idle.png).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools/homm3_prebake"))
import prebake_lab as pl  # noqa: E402
from oceanid_water_compare import changed_fracs, def_regions, loop_metrics, regions_from_mask  # noqa: E402
from oceanid_water_motion import DEFAULT_DEF_DIR, highpass, segment  # noqa: E402
from oceanid_water_lab import CLIP_GROUPS  # noqa: E402

ROOT = HERE.parents[1]
EXP = ROOT / "artifacts/homm3_vfx_experiments/oceanid"
R2D = EXP / "renders_v2"
LOOK = EXP / "look"
OUT = EXP / "compare_v2"
VARIANTS = ["current", "L", "B2L", "F", "F2", "A2", "A", "FX"]
LABELS = {"DEF": "DEF (HoMM3)", "current": "current", "L": "L lighting", "B2L": "B2L boil", "F": "F flow atlas", "F2": "F2 coarse flow",
          "A2": "A2 split+ST scroll", "A": "A split+_UvScroll", "FX": "FX = F + accents"}
Q = np.linspace(10, 90, 9)
DISP = 3
BG = (194, 170, 120)  # sand, the colour the fit targets


def lab(rgb8):
    return pl.lin_to_lab(pl.srgb_to_lin(rgb8[..., :3].astype(np.float32) / 255))


def lab_dist(a, b):
    if len(a) < 20 or len(b) < 20:
        return None
    pa, pb = np.percentile(a, Q, axis=0), np.percentile(b, Q, axis=0)
    return float(np.mean(np.abs(pa - pb) @ np.array([1.0, 0.7, 0.7])))


def lab_median(a):
    return np.round(np.median(a, 0), 1).tolist() if len(a) else None


def load(variant, clip, n):
    return [Image.open(R2D / variant / f"{clip}_{i:02d}.png").convert("RGBA") for i in range(n)]


def reduce(im):
    return np.array(im.reduce(2))


def row(def_rgba, renders2x, box, labels):
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) * DISP, (y1 - y0) * DISP
    cells = []
    c = Image.new("RGBA", (x1 - x0, y1 - y0), BG + (255,))
    c.alpha_composite(Image.fromarray(def_rgba[y0:y1, x0:x1]))
    cells.append(c.convert("RGB").resize((w, h), Image.NEAREST))
    for r in renders2x:
        c = Image.new("RGBA", (2 * (x1 - x0), 2 * (y1 - y0)), BG + (255,))
        c.alpha_composite(r.crop((2 * x0, 2 * y0, 2 * x1, 2 * y1)))
        cells.append(c.convert("RGB").resize((w, h), Image.LANCZOS))
    head = 16 if labels else 0
    out = Image.new("RGB", (w * len(cells), h + head), (20, 22, 26))
    d = ImageDraw.Draw(out)
    for k, c in enumerate(cells):
        out.paste(c, (k * w, head))
        if labels:
            d.text((k * w + 4, 2), LABELS[(["DEF"] + VARIANTS)[k]] if k <= len(VARIANTS) else "", fill=(235, 235, 235))
    return out


def movie(frames, path_stem, fps, reps):
    frames[0].save(path_stem.with_suffix(".gif"), save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0)
    ff = shutil.which("ffmpeg")
    if not ff:
        return
    tmp = path_stem.parent / "_mp4"
    tmp.mkdir(exist_ok=True)
    k = 0
    for _ in range(reps):
        for r in frames:
            r.save(tmp / f"f{k:04d}.png")
            k += 1
    W, H = frames[0].size
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
                    "-vf", f"pad={W + W % 2}:{H + H % 2}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                    str(path_stem.with_suffix(".mp4"))], check=True)
    shutil.rmtree(tmp)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads((LOOK / "look_meta.json").read_text())
    clips = meta["cells"]["clips"]
    pools = {v: {k: [] for k in ("column", "foam", "body", "all")} for v in ["DEF"] + VARIANTS}
    M = {"proofTier": "Unity-editor-rendered (lab replica of Hex/Lit, camera-relative sand arena sun); DEF = shipped HoMM3 sprite",
         "lighting": meta["lighting"], "clips": {}}
    box_all = None
    for clip, info in clips.items():
        grp = CLIP_GROUPS[clip]
        D = [np.array(Image.open(f).convert("RGBA")) for f in sorted(Path(DEFAULT_DEF_DIR).glob(f"{grp}_*.png"))]
        n = len(D)
        masks = [regions_from_mask(reduce(m)) for m in load("mask", clip, n)]
        R2 = {v: load(v, clip, n) for v in VARIANTS}
        R = {v: [reduce(im) for im in R2[v]] for v in VARIANTS}
        for i in range(n):
            sg = segment(D[i])
            L = lab(D[i])
            body = pl.def_mask(D[i].astype(np.float32) / 255) & ~sg["water"] & ~sg["spray"]
            pools["DEF"]["column"].append(L[sg["column"]]); pools["DEF"]["foam"].append(L[sg["foam"]])
            pools["DEF"]["body"].append(L[body]); pools["DEF"]["all"].append(L[D[i][..., 3] == 255])
            for v in VARIANTS:
                Lr = lab(R[v][i])
                a = R[v][i][..., 3] > 200
                pools[v]["column"].append(Lr[masks[i]["column"] & a]); pools[v]["foam"].append(Lr[masks[i]["foam"] & a])
                pools[v]["body"].append(Lr[masks[i]["torso"] & a]); pools[v]["all"].append(Lr[a])
        loop = grp in ("02", "01")
        rec = {"frames": n, "changed": {"DEF": changed_fracs(D, def_regions(D), loop)}}
        for v in VARIANTS:
            rec["changed"][v] = changed_fracs(R[v], masks, loop)
        if clip == "Unit_Idle":
            rec["loop"] = {"DEF": loop_metrics(D, def_regions(D))}
            for v in VARIANTS:
                rec["loop"][v] = loop_metrics(R[v], masks, None if v == "current" else R["current"])
        M["clips"][clip] = rec

        ys, xs = [], []
        for arr in D + R["FX"] + R["current"]:
            yy, xx = np.nonzero(arr[..., 3] > 0)
            if len(yy):
                ys += [yy.min(), yy.max()]; xs += [xx.min(), xx.max()]
        box = (max(0, min(xs) - 4), max(0, min(ys) - 4), min(450, max(xs) + 5), min(400, max(ys) + 5))
        rows = [row(D[i], [R2[v][i] for v in VARIANTS], box, labels=True) for i in range(n)]
        sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), (20, 22, 26))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y)); y += r.height
        sheet.save(OUT / f"sheet_{clip}.png")
        movie(rows, OUT / clip, 12, 4 if loop else 2)

    M["colour"] = {}
    for v in VARIANTS:
        M["colour"][v] = {}
        for k in ("column", "foam", "body", "all"):
            a, b = np.concatenate(pools[v][k]), np.concatenate(pools["DEF"][k])
            M["colour"][v][k] = {"dist": lab_dist(a, b), "median": lab_median(a)}
    M["colour"]["DEF"] = {k: {"median": lab_median(np.concatenate(pools["DEF"][k]))} for k in ("column", "foam", "body", "all")}

    # stepping ratio from the 48 fps idle subsample
    subs = sorted((R2D / "F").glob("sub48_*.png"))
    nsub = len(subs)
    mask0 = regions_from_mask(reduce(Image.open(R2D / "mask/Unit_Idle_00.png")))
    col = ndimage.binary_erosion(mask0["column"], np.ones((3, 3)))
    M["stepping"] = {}
    sub_frames = {}
    for v in ("B2L", "F", "F2", "A2", "A"):
        fr = [Image.open(R2D / v / f"sub48_{j:03d}.png").convert("RGBA") for j in range(nsub)]
        sub_frames[v] = fr
        HP = [highpass(reduce(f)) for f in fr]
        ch = [float(np.mean((HP[j + 1][col] - HP[j][col]) ** 2)) for j in range(nsub - 1)]
        boundary = [c for j, c in enumerate(ch) if j % 4 == 1]  # j=4i+1 -> 4i+2 straddles the key at (i+1.5)/12
        M["stepping"][v] = {"boundaryShare": float(sum(boundary) / max(1e-9, sum(ch))), "pairs": len(ch)}
    D0 = [np.array(Image.open(f).convert("RGBA")) for f in sorted(Path(DEFAULT_DEF_DIR).glob("02_*.png"))]
    ys, xs = np.nonzero(D0[0][..., 3] > 0)
    zb = (int(xs.min()) - 3, int(ys.min()) - 3, int(xs.max()) + 4, int(ys.max()) + 4)
    global DISP
    DISP = 4
    sub_rows = []
    for j in range(nsub):
        i = min(len(D0) - 1, (j + 2) // 4)
        r = row(D0[i], [sub_frames[v][j] for v in ("B2L", "F", "F2", "A2", "A")], zb, labels=False)
        d = ImageDraw.Draw(r)
        for k, name in enumerate(["DEF", "B2L", "F", "F2", "A2", "A"]):
            d.text((k * (zb[2] - zb[0]) * DISP + 4, 2), name, fill=(20, 20, 20))
        sub_rows.append(r)
    movie(sub_rows, OUT / "idle_sub48", 48, 4)

    # accents IoU against the DEF effect masks
    M["accents"] = {}
    for aid, a in meta["accents"].items():
        ious, prec, recl = [], [], []
        for i in a["frames"]:
            dm = np.array(Image.open(LOOK / "accents" / f"{aid}_mask_{i:02d}.png")) > 127
            rm = reduce(Image.open(R2D / "accents_only" / f"{a['clip']}_{i:02d}.png").convert("RGBA"))[..., 3] > 127
            inter = (dm & rm).sum()
            ious.append(inter / max(1, (dm | rm).sum())); prec.append(inter / max(1, rm.sum())); recl.append(inter / max(1, dm.sum()))
        M["accents"][aid] = {"clip": a["clip"], "frames": a["frames"], "iou": float(np.mean(ious)),
                             "precision": float(np.mean(prec)), "recall": float(np.mean(recl))}

    # colour close-up: idle frame 2, DEF vs every variant, 6x
    DISP = 6
    row(D0[2], [Image.open(R2D / v / "Unit_Idle_02.png").convert("RGBA") for v in VARIANTS], zb, True).save(OUT / "colour_idle.png")

    # animator ST readback after the restamp-style material swap (F: body cell; A2: water tile cell + scroll)
    rep = json.loads((R2D / "lab_report.json").read_text())
    sp = json.loads((R2D / "unity_lab_spec.json").read_text())
    cl = {c["name"]: c for c in sp["clips"]}
    hits = {}
    for e in rep.get("animatorST", []):
        k = cl[e["clip"]]["flow"][e["frame"]]
        exp = sp["cellST"][4 * k:4 * k + 4] if e["variant"] == "F" else             [sp["tileCellScaleX"], 1.0, sp["tileCellOffsetX"][k], sp["tileScrollPerSecond"] * e["t"]]
        h = hits.setdefault(e["variant"], [0, 0])
        h[0] += all(abs(a - b) < 2e-3 for a, b in zip(e["mpbST"], exp))
        h[1] += 1
    M["animatorSTMatches"] = {v: f"{a}/{b}" for v, (a, b) in hits.items()}

    (OUT / "look_metrics.json").write_text(json.dumps(M, indent=1))
    L = [f"proof tier: {M['proofTier']}", "", "colour (Lab percentile distance to DEF, lower is better; medians L*,a*,b*)"]
    L.append(f"   {'DEF':8s} " + "  ".join(f"{k} {M['colour']['DEF'][k]['median']}" for k in ("column", "foam", "body")))
    for v in VARIANTS:
        c = M["colour"][v]
        L.append(f"   {v:8s} " + "  ".join(f"{k} {c[k]['dist']:.1f} {c[k]['median']}" for k in ("column", "foam", "body", "all")))
    idle = M["clips"]["Unit_Idle"]
    L += ["", "idle motion (waterNorm, torsoNorm, velocity px/frame, best/zero, lagFlat, highlight survival/chance)"]
    for v in ["DEF"] + VARIANTS:
        c, lp = idle["changed"][v], idle["loop"][v]
        vel = lp["velocity"]
        L.append(f"   {v:8s} {c['waterNorm']:.2f} {c['torsoNorm']:.2f}  v {vel['bestV']} {vel['bestOverZero']:.3f}  "
                 f"lagFlat {lp['lagFlatness']:.2f}  hl {lp['highlight']['survival']:.2f}/{lp['highlight']['chance']:.2f}")
    L += ["", "stepping (share of change at DEF frame boundaries, 48 fps idle): "
          + "  ".join(f"{v} {s['boundaryShare']:.2f}" for v, s in M["stepping"].items())]
    L += ["", f"animator _MainTex_ST after restamp swap: {M['animatorSTMatches']}"]
    L += ["", "accents vs DEF effect mask (IoU / precision / recall)"]
    for aid, a in M["accents"].items():
        L.append(f"   {aid:20s} {a['clip']:17s} frames {a['frames']}  {a['iou']:.2f} / {a['precision']:.2f} / {a['recall']:.2f}")
    (OUT / "look_summary.txt").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def runner_vs_lab():
    """Runner-graded uvAtlas (artifacts/homm3_unit_look/hota_cove_oceanid/vfx) against the lab F2 atlas (texture space).
    Per cell: L*a*b* percentile distance and medians on the column / foam texels, and the correlation of the
    cell-to-cell luma change (does the runner's atlas move like the lab's); body: static base colour distance."""
    ul = ROOT / "artifacts/homm3_unit_look/hota_cove_oceanid"
    man = json.loads((ul / "vfx/vfx_manifest.json").read_text())
    ent = man["layers"]["water_flow"]
    at = np.asarray(Image.open(ul / "vfx" / ent["atlas"]).convert("RGB"))
    H, W = at.shape[:2]
    cp = ent["cellPx"]
    run_cells = []
    for st in ent["cellST"]:
        x0 = int(round(st[2] * W)); y0 = int(round((1 - st[3]) * H)) - cp
        run_cells.append(at[y0:y0 + cp, x0:x0 + cp])
    lab_at = np.asarray(Image.open(LOOK / "look_flow2_atlas.png").convert("RGB"))
    g, pitch = 32, 1024 + 64
    lab_cells = [lab_at[(k // 2) * pitch + g:(k // 2) * pitch + g + 1024, (k % 2) * pitch + g:(k % 2) * pitch + g + 1024] for k in range(8)]
    sc = np.load(LOOK / "flow2_scores.npz")
    regs = {"column": sc["column"], "foam": sc["foam"]}
    if cp != 1024:
        regs = {k: np.asarray(Image.fromarray(v).resize((cp, cp), Image.NEAREST)) for k, v in regs.items()}
        lab_cells = [np.asarray(Image.fromarray(c).resize((cp, cp), Image.LANCZOS)) for c in lab_cells]
    out = {"cells": []}
    for k in range(min(len(run_cells), 8)):
        rl, ll = lab(run_cells[k]), lab(lab_cells[k])
        out["cells"].append({r: {"dist": lab_dist(rl[m], ll[m]), "runnerMedian": lab_median(rl[m]), "labMedian": lab_median(ll[m])}
                             for r, m in regs.items()})
    wmask = regs["column"]
    lum = lambda c: c.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    corr = []
    for k in range(7):
        a = (lum(run_cells[k + 1]) - lum(run_cells[k]))[wmask]
        b = (lum(lab_cells[k + 1]) - lum(lab_cells[k]))[wmask]
        corr.append(float(np.corrcoef(a, b)[0, 1]))
    out["cellChangeCorrelation"] = corr
    bc = np.asarray(Image.open(ul / "basecolor.png").convert("RGB"))
    ls = np.asarray(Image.open(LOOK / "look_static.png").convert("RGB"))
    if bc.shape != ls.shape:
        ls = np.asarray(Image.fromarray(ls).resize(bc.shape[1::-1], Image.LANCZOS))
    rest = np.asarray(Image.fromarray(((regs["column"] | regs["foam"]) * 255).astype(np.uint8)).resize(bc.shape[1::-1])) < 128
    rest &= bc.sum(-1) > 0
    out["bodyStatic"] = {"dist": lab_dist(lab(bc)[rest], lab(ls)[rest]), "runnerMedian": lab_median(lab(bc)[rest]),
                         "labMedian": lab_median(lab(ls)[rest])}
    (OUT / "runner_vs_lab.json").write_text(json.dumps(out, indent=1))
    side = [np.concatenate([run_cells[k], lab_cells[k]], 0) for k in range(min(4, len(run_cells)))]
    Image.fromarray(np.concatenate(side, 1)).resize((1024, 512), Image.LANCZOS).save(OUT / "runner_vs_lab_cells.png")
    print(json.dumps({"cell0": out["cells"][0], "cellChangeCorrelation": [round(c, 3) for c in corr],
                      "bodyStatic": out["bodyStatic"]}, indent=1))


if __name__ == "__main__":
    if "--runner" in sys.argv:
        OUT.mkdir(parents=True, exist_ok=True)
        runner_vs_lab()
    else:
        main()
