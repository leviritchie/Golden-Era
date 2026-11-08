"""Write the DEF sprite frame size, idle-frame-0 opaque bbox and per-frame opaque widths.

Widths drive wing spread for winged units (the wings dominate a gargoyle's width change).

Usage: python sprite_info.py <master_sequence.json> <out.json>
"""
import json, sys
import numpy as np
from PIL import Image
ms = json.load(open(sys.argv[1]))
src = ms["frames"][0]["sourcePng"]
a = np.asarray(Image.open(src).convert("RGBA"))[..., 3] == 255
ys, xs = np.nonzero(a)
widths = []
for f in ms["frames"]:
    m = np.asarray(Image.open(f["sourcePng"]).convert("RGBA"))[..., 3] == 255
    cols = np.nonzero(m.any(0))[0]
    widths.append(int(cols.max() - cols.min() + 1) if len(cols) else 0)
json.dump({"bbox0": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
           "size": list(Image.open(src).size), "widths": widths}, open(sys.argv[2], "w"))
