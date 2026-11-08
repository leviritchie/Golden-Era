"""Storm elemental missile (CPRGTIX.DEF, shared with the Titan) flight comparison.

HoMM3/VCMI pick ONE missile frame per shot from the trajectory angle (CRANIM.TXT
frameAngles 90,72,45,27,0,-27,-45,-72,-90 for frames 0..8; mirrored for leftward shots)
and translate it; the frames are not a time flipbook. Rows:
  A  DEF frame chosen by angle, translated (what HoMM3 does)
  B  procedural 1-px strands re-drawn every tick in the DEF's pale-cyan/white palette
  M  modern soft additive bolt
Generated-artifact 2D composite only (no Unity, no game).
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import h3def  # noqa: E402
from storm_experiments import bolt_paths, raster_1px  # noqa: E402

EXP = pathlib.Path(__file__).resolve().parents[2] / "artifacts/homm3_vfx_experiments/storm_elemental"
ANGLES = [90, 72, 45, 27, 0, -27, -45, -72, -90]
BG = np.array([72, 88, 64], float)
S = 2
W, H = 320, 170
SPEED_PX_S = 1250  # VCMI projectile speed at speedFactor 1 (x2 at its default speed)
TICK_MS = 20


def pick_frame(angle_deg):
    return int(np.argmin([abs(a - angle_deg) for a in ANGLES]))


def main():
    d = h3def.read_def("cprgtix.def")
    frames = d.groups[0]
    rng = np.random.default_rng(7)
    shots = [("level", (40, 110), (290, 110)), ("up 27deg", (40, 140), (290, 13)), ("down 45deg", (40, 20), (190, 160))]
    out_frames = []
    for name, p0, p1 in shots:
        p0, p1 = np.array(p0, float), np.array(p1, float)
        v = p1 - p0
        ang = math.degrees(math.atan2(-v[1], v[0]))  # screen y down; positive = up
        fi = pick_frame(ang)
        spr = h3def.to_rgba(frames[fi], d.palette)
        dist = float(np.linalg.norm(v))
        n = max(2, int(dist / SPEED_PX_S * 1000 / TICK_MS))
        for k in range(n + 1):
            pos = p0 + v * k / n
            rows = []
            # A
            canvas = np.zeros((H, W, 4), np.uint8)
            sh, sw = spr.shape[:2]
            x0, y0 = int(pos[0] - sw / 2), int(pos[1] - sh / 2)
            xa, ya = max(0, x0), max(0, y0)
            xb, yb = min(W, x0 + sw), min(H, y0 + sh)
            if xb > xa and yb > ya:
                canvas[ya:yb, xa:xb] = spr[ya - y0:yb - y0, xa - x0:xb - x0]
            rows.append(canvas)
            # B: new strands every tick along the flight direction, DEF-sized (~70 px)
            hd = math.atan2(v[1], v[0])
            paths = []
            for s in (-1, 1):
                paths += bolt_paths(rng, pos, hd + (0 if s > 0 else math.pi), 26, 6)
            for _ in range(3):
                paths += bolt_paths(rng, pos, rng.uniform(0, 2 * math.pi), 14, 2)
            b = raster_1px((H, W), paths, (214, 255, 255, 255))
            core = raster_1px((H, W), [[pos - 12 * np.array([math.cos(hd), math.sin(hd)]),
                                        pos + 12 * np.array([math.cos(hd), math.sin(hd)])]], (255, 255, 255, 255))
            b[core[..., 3] > 0] = core[core[..., 3] > 0]
            rows.append(b)
            rows.append(b)  # M uses the same strands, soft-rendered below
            panels = []
            for j, lay in enumerate(rows):
                bg = np.ones((H * S, W * S, 3)) * BG
                L = lay.repeat(S, 0).repeat(S, 1)
                if j < 2:
                    a = L[..., 3:4] / 255.0
                    im = bg * (1 - a) + L[..., :3] * a
                else:
                    a2 = np.array(Image.fromarray(lay[..., 3]).resize((W * S, H * S), Image.BILINEAR)) / 255.0
                    im = np.clip(bg + gaussian_filter(a2, 5)[..., None] * 6 * np.array([110, 200, 255.0]) * .9
                                 + gaussian_filter(a2, 1.2)[..., None] * 255 * 1.5, 0, 255)
                panels.append(Image.fromarray(im.astype(np.uint8)))
            sheet = Image.new("RGB", (W * S, (H * S + 14) * 3), (18, 18, 18))
            dr = ImageDraw.Draw(sheet)
            labels = [f"A: CPRGTIX frame {fi} (angle {ANGLES[fi]}) translated", "B: procedural strands, DEF palette",
                      "M: modern soft additive"]
            for j, p in enumerate(panels):
                sheet.paste(p, (0, j * (H * S + 14) + 14))
                dr.text((3, j * (H * S + 14) + 1), f"{labels[j]}   shot {name}, t={k * TICK_MS} ms", fill=(230, 230, 230))
            out_frames.append(sheet)
    out_frames[0].save(EXP / "compare_missile.gif", save_all=True, append_images=out_frames[1:], duration=TICK_MS * 5, loop=0)
    idx = [0, len(out_frames) // 6, len(out_frames) // 2]
    strip = Image.new("RGB", (W * S * 3, out_frames[0].height), (18, 18, 18))
    for i, k in enumerate(idx):
        strip.paste(out_frames[k], (i * W * S, 0))
    strip.save(EXP / "compare_missile_sheet.png")
    print("frames", len(out_frames))


if __name__ == "__main__":
    main()
