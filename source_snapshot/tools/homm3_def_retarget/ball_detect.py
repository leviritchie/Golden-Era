"""Track the flail ball through every DEF frame of a capture's master sequence.

Usage: python ball_detect.py <master_sequence.json> <out_prefix> [seedX,seedY]
Writes <out_prefix>.json ({"balls": [[x, y, area, source] ...], "bbox0": ..., "size": ...})
and <out_prefix>.png (contact sheet with the tracked ball circled; interpolated frames in red).

The ball is a dark, low-saturation grey/lavender blob. Robes can be blue (Master Gremlin)
and hair can be grey, so colour alone is not enough: candidates are blobs that survive a
morphological opening (which removes the thin chain), and the one nearest the previous
frame's ball wins. Frames with no candidate within reach (ball hidden behind the body)
are linearly interpolated between their tracked neighbours and marked "interp".
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ms = json.load(open(sys.argv[1])); out = sys.argv[2]
srcs = [f["sourcePng"] for f in ms["frames"]]
SEED = tuple(float(v) for v in sys.argv[3].split(",")) if len(sys.argv) > 3 else None
BALL_COLOURS = None
if SEED:
    # DEFs are paletted: learn the ball's exact colours from a disc on idle frame 0, dropping
    # colours that are used more outside the ball than inside it (robe, chain, hair)
    a0 = np.asarray(Image.open(srcs[0]).convert("RGBA")).astype(int)
    yy, xx = np.mgrid[:a0.shape[0], :a0.shape[1]]
    rr = np.hypot(xx - SEED[0], yy - SEED[1]); op0 = a0[..., 3] == 255
    key = a0[..., 0] * 65536 + a0[..., 1] * 256 + a0[..., 2]
    inside = key[op0 & (rr <= 7)]; outside = key[op0 & (rr > 12)]
    vals, cnt = np.unique(inside, return_counts=True)
    BALL_COLOURS = np.array([v for v, c in zip(vals, cnt) if (outside == v).sum() < c])
    print("ball palette colours:", len(BALL_COLOURS), "of", len(vals))
REACH = 120.0  # px a ball may move away from its predicted position between DEF frames


def candidates(path):
    a = np.asarray(Image.open(path).convert("RGBA")).astype(int)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    mx = np.maximum(np.maximum(r, g), b); mn = np.minimum(np.minimum(r, g), b)
    sat = (mx - mn) / np.maximum(mx, 1)
    if BALL_COLOURS is not None:
        m = (al == 255) & np.isin(r * 65536 + g * 256 + b, BALL_COLOURS)
    else:
        m = (al == 255) & (sat < 0.55) & (b >= r - 6) & (g <= b + 6) & (mx > 22)
    found = []
    for it in (2, 1):
        op = ndimage.binary_opening(m, iterations=it)
        lab, n = ndimage.label(op)
        for k in range(1, n + 1):
            area = int((lab == k).sum())
            if 10 <= area <= 220:
                cy, cx = ndimage.center_of_mass(op, lab, k)
                ys, xs = np.nonzero(lab == k)
                fill = area / ((np.ptp(xs) + 1) * (np.ptp(ys) + 1))
                if fill > 0.45:
                    found.append((float(cx), float(cy), area))
        if found:
            break
    return found


cands = [candidates(p) for p in srcs]
# anchor: the largest round candidate on idle frame 0
track = [None] * len(srcs)
if SEED:
    track[0] = min(cands[0], key=lambda c: np.hypot(c[0] - SEED[0], c[1] - SEED[1])) + ("detected",)
else:
    track[0] = max(cands[0], key=lambda c: c[2]) + ("detected",)
for t in range(1, len(srcs)):
    prev = next(track[k] for k in range(t - 1, -1, -1) if track[k] is not None)
    pred = prev
    if t >= 2 and track[t - 1] is not None and track[t - 2] is not None:
        pred = (2 * track[t - 1][0] - track[t - 2][0], 2 * track[t - 1][1] - track[t - 2][1])
    dist = lambda c: min(np.hypot(c[0] - pred[0], c[1] - pred[1]), np.hypot(c[0] - prev[0], c[1] - prev[1]))
    near = [c for c in cands[t] if dist(c) <= REACH]
    if near:
        c = min(near, key=dist)
        track[t] = c + ("detected",)
# interpolate gaps
for t in range(len(srcs)):
    if track[t] is None:
        a = max(k for k in range(t) if track[k] is not None)
        bs = [k for k in range(t + 1, len(srcs)) if track[k] is not None and track[k][3] == "detected"]
        if bs:
            b = bs[0]; f = (t - a) / (b - a)
            track[t] = (track[a][0] * (1 - f) + track[b][0] * f, track[a][1] * (1 - f) + track[b][1] * f, 0, "interp")
        else:
            track[t] = (track[a][0], track[a][1], 0, "interp")

a0 = np.asarray(Image.open(srcs[0]).convert("RGBA"))[..., 3] == 255
ys, xs = np.nonzero(a0)
json.dump({"balls": [list(b) for b in track],
           "bbox0": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
           "size": list(Image.open(srcs[0]).size)}, open(out + ".json", "w"))

tiles = []
for t, p in enumerate(srcs):
    im = Image.open(p).convert("RGBA").crop((96, 120, 316, 300)); dr = ImageDraw.Draw(im)
    x, y, _, how = track[t]; col = (255, 255, 0) if how == "detected" else (255, 60, 60)
    dr.ellipse((x - 96 - 6, y - 120 - 6, x - 96 + 6, y - 120 + 6), outline=col)
    dr.text((2, 2), str(t), fill=col); tiles.append(im)
W, H = tiles[0].size; cols = 12
sheet = Image.new("RGB", (W * cols, H * ((len(tiles) + cols - 1) // cols)), (40, 40, 40))
for i, im in enumerate(tiles):
    sheet.paste(im, ((i % cols) * W, (i // cols) * H), im)
sheet.save(out + ".png")
print("interpolated frames:", [t for t, b in enumerate(track) if b[3] == "interp"])
