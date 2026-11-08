"""Phoenix fire: side-by-side DEF vs candidates (same scale, 12 fps) plus metrics.

Reads the composites from phoenix_fire_lab.py (lab/frames/<cand>/<clip>_NN.png) and the DEF itself, and writes
to artifacts/homm3_vfx_experiments/phoenix/compare/:
  sheet_<clip>.png   rows = DEF + candidates, columns = DEF frames, 2 screen px per DEF px
  <clip>.gif / .mp4  panels side by side at 12 fps (mp4 at 2x nearest)
  metrics.json, metrics_summary.txt

Metrics use the same region code as phoenix_fire_motion.py on the DEF and on every candidate:
  colour   : L* histogram distance (Wasserstein over percentiles) to the DEF over the whole unit (effects on),
             median a*/b*, and the hot-core share of the body (luma >= 225)
  coverage : silhouette IoU with the DEF, flame+ember px relative to the DEF
  flicker  : body colour-change fraction per frame pair; flame-zone membership flip rate by lag (flat = redraw in
             place, rising = travel / smooth motion); multi-lag texture velocity best/zero in the flame zone
             (idle only; < 0.6 would be coherent travel)
Proof tier: generated artifact (CPU composite).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "homm3_prebake"))
import phoenix_fire_lab as lab  # noqa: E402
import phoenix_fire_motion as fm  # noqa: E402
import prebake_lab as pl  # noqa: E402

OUT = lab.BASE / "compare"
BG = (72, 88, 64)
LABELS = {"DEF": "DEF CPHX", "C0_raw": "C0 raw mesh", "C1_look": "C1 grade+glow", "C2_boil": "C2 +boil atlas",
          "C3_defflip": "C3 +DEF flames", "C4_tongues": "C4 +tongues", "C5_defflip_light": "C5 C3+light",
          "C6_tongues_light": "C6 C4+light"}


def load(cand, clip, n):
    return [np.array(Image.open(lab.LAB / "frames" / cand / f"{clip}_{i:02d}.png").convert("RGBA")) for i in range(n)]


def lab_px(rgba, mask):
    return pl.lin_to_lab(pl.srgb_to_lin(rgba[..., :3][mask].astype(np.float32) / 255))


def flame_flip(segs):
    n = len(segs)
    zone = np.zeros_like(segs[0]["flame"])
    for s in segs:
        zone |= ndimage.binary_dilation(s["flame"] | s["ember"], fm.disk(1))
    fl = [s["flame"] | s["ember"] for s in segs]
    out = []
    for lag in range(1, min(n, 5)):
        out.append(round(float(np.mean([(fl[t] ^ fl[(t + lag) % n])[zone].mean() for t in range(n)])), 3))
    return out


def metrics(frames, ref, loop):
    segs = [fm.segment(f) for f in frames]
    rsegs = [fm.segment(f) for f in ref]
    op = np.concatenate([lab_px(f, f[..., 3] == 255) for f in frames])
    rop = np.concatenate([lab_px(f, f[..., 3] == 255) for f in ref])
    iou = [float((s["opaque"] & r["opaque"]).sum() / max(1, (s["opaque"] | r["opaque"]).sum())) for s, r in zip(segs, rsegs)]
    fl = [int((s["flame"] | s["ember"]).sum()) for s in segs]
    rfl = [int((s["flame"] | s["ember"]).sum()) for s in rsegs]
    m = {
        "LhistDist": round(pl.hist_distance(op[:, 0], rop[:, 0]), 2),
        "Lp10_50_90": np.percentile(op[:, 0], [10, 50, 90]).round(1).tolist(),
        "a50": round(float(np.median(op[:, 1])), 1), "b50": round(float(np.median(op[:, 2])), 1),
        "coreShare": round(float(np.mean([s["core"].sum() / max(1, s["body"].sum()) for s in segs])), 3),
        "IoU": round(float(np.mean(iou)), 3),
        "flamePxRatio": round(float(np.sum(fl) / max(1, np.sum(rfl))), 2),
        "bodyChange": round(lab.body_change(frames), 3),
        "flameFlipByLag": flame_flip(segs),
    }
    if loop:
        zone = np.zeros_like(segs[0]["flame"])
        for s in segs:
            zone |= s["flame"]
        v = fm.multilag_velocity([s["luma"] for s in segs], zone, vmax=3.0, step=1.0)
        m["flameVelocityBestOverZero"] = v["bestOverZero"] if v else None
        m["flameVelocity"] = v["bestV"] if v else None
    return m


def panel_box(all_frames):
    m = np.zeros(all_frames[0].shape[:2], bool)
    for f in all_frames:
        m |= f[..., 3] == 255
    ys, xs = np.nonzero(m)
    return xs.min() - 4, ys.min() - 4, xs.max() + 5, ys.max() + 5


def on_bg(rgba):
    bg = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), BG + (255,))
    return Image.alpha_composite(bg, Image.fromarray(rgba, "RGBA")).convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d, defs = lab.def_frames()
    allm, lines = {}, []
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    for clip in lab.CLIPS:
        ref = defs[clip]["rgba"]
        n = len(ref)
        cands = {c: load(c, clip, n) for c in lab.CANDS}
        rows = {"DEF": ref} | cands
        box = panel_box([f for fs in rows.values() for f in fs])
        allm[clip] = {}
        for c, fs in rows.items():
            allm[clip][c] = metrics(fs, ref, clip == "Unit_Idle")
            lines.append(f"{clip:18s} {c:18s} " + json.dumps(allm[clip][c]))
        s = 2
        w, h = (box[2] - box[0]) * s, (box[3] - box[1]) * s
        sheet = Image.new("RGB", (120 + w * n, (h + 2) * len(rows)), (24, 24, 24))
        dr = ImageDraw.Draw(sheet)
        for r, (c, fs) in enumerate(rows.items()):
            dr.text((4, r * (h + 2) + 4), LABELS[c], fill=(235, 235, 235))
            for i, f in enumerate(fs):
                sheet.paste(on_bg(f).crop(box).resize((w, h), Image.NEAREST), (120 + i * w, r * (h + 2)))
        sheet.save(OUT / f"sheet_{clip}.png")
        # animation: panels side by side (2 rows of 4) at 12 fps
        names = list(rows)
        cols = 4
        grid_rows = (len(names) + cols - 1) // cols
        gif = []
        for i in range(n):
            im = Image.new("RGB", (w * cols, (h + 14) * grid_rows), (24, 24, 24))
            dd = ImageDraw.Draw(im)
            for k, c in enumerate(names):
                x, y = (k % cols) * w, (k // cols) * (h + 14)
                im.paste(on_bg(rows[c][i]).crop(box).resize((w, h), Image.NEAREST), (x, y + 14))
                dd.text((x + 3, y + 1), f"{LABELS[c]}  f{i}", fill=(235, 235, 235))
            gif.append(im)
        loops = 3 if n < 8 else 2
        seq = gif * loops
        seq[0].save(OUT / f"{clip}.gif", save_all=True, append_images=seq[1:], duration=int(1000 / 12), loop=0)
        W2, H2 = (gif[0].width + 1) // 2 * 2, (gif[0].height + 1) // 2 * 2
        proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W2}x{H2}",
                                 "-r", "12", "-i", "-", "-pix_fmt", "yuv420p", "-vcodec", "libx264", "-crf", "16",
                                 str(OUT / f"{clip}.mp4")], stdin=subprocess.PIPE)
        for im in seq:
            canvas = Image.new("RGB", (W2, H2))
            canvas.paste(im, (0, 0))
            proc.stdin.write(canvas.tobytes())
        proc.stdin.close()
        proc.wait()
        print("wrote", clip)
    (OUT / "metrics.json").write_text(json.dumps(allm, indent=1))
    (OUT / "metrics_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
