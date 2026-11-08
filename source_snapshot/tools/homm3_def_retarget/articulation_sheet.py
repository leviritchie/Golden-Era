"""Draw a clip of one or more built units as region-coloured point clouds, to check articulation.py by eye.

Usage: python tools/homm3_def_retarget/articulation_sheet.py <out.png> <clip> <unit> [unit ...]

No Blender: skins the GLB with articulation.audit. Per unit two rows (side view = glTF Z/Y and
front view = X/Y), one column per key frame of the clip, fixed framing per unit so travel and
bounce are visible. Colours: torso grey, head white, arms orange, legs blue, wings red, extra green.
"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
import articulation as A

COL = {"torso": (150, 150, 150), "head": (240, 240, 240), "arms": (240, 150, 40), "legs": (70, 130, 240),
       "wings": (230, 50, 50), "extra": (60, 200, 90), "root": (150, 150, 150)}
CELL, MAXF = 150, 10

out, clip, units = sys.argv[1], sys.argv[2], sys.argv[3:]
rows = []
for u in units:
    keep = {}
    rec = A.audit(os.path.join(A.ART, u, f"{u}_def_retarget.glb"), keep)
    if clip not in keep:
        print(u, "has no", clip); continue
    frames, reg = keep[clip]
    frames = frames[:MAXF]
    r = rec["clips"][clip]
    label = f"{u}  rigid {r.get('rigidShare')}  nonRigid {r.get('nonRigid')}  wings {r.get('wings')}"
    cols = np.array([COL[x] for x in reg], np.uint8)
    for axes in ((2, 1), (0, 1)):
        allp = np.concatenate([f[:, axes] for f in frames])
        lo, hi = allp.min(0), allp.max(0); sc = (CELL - 10) / max(hi - lo)
        row = Image.new("RGB", (CELL * MAXF, CELL + (14 if axes == (2, 1) else 0)), (30, 30, 30))
        d = ImageDraw.Draw(row)
        y0 = 14 if axes == (2, 1) else 0
        if axes == (2, 1):
            d.text((4, 1), label, fill=(255, 255, 0))
        for k, f in enumerate(frames):
            p = (f[:, axes] - lo) * sc + 5
            order = np.argsort(f[:, 0 if axes == (2, 1) else 2])        # crude depth order
            px = p[order].astype(int); c = cols[order]
            im = np.full((CELL, CELL, 3), 30, np.uint8)
            x, y = px[:, 0], CELL - 1 - px[:, 1]
            ok = (x >= 0) & (x < CELL) & (y >= 0) & (y < CELL)
            im[y[ok], x[ok]] = c[ok]
            row.paste(Image.fromarray(im), (k * CELL, y0))
        rows.append(row)
sheet = Image.new("RGB", (CELL * MAXF, sum(r.height for r in rows)), (30, 30, 30))
y = 0
for r in rows:
    sheet.paste(r, (0, y)); y += r.height
sheet.save(out); print(out)
