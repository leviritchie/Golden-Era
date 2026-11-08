"""Per-clip silhouette IoU (DEF vs sprite-camera render) and edge stretch.

Usage: python metrics.py <out.blend> <renders_dir> <stretch.json> <metrics.json>
"""
import json, sys
import numpy as np
from PIL import Image
blend, rdir, stp, out = sys.argv[1:5]
fj = json.load(open(blend + ".frames.json")); st = json.load(open(stp))
iou = []
for t, sp in enumerate(fj["sources"]):
    a = np.asarray(Image.open(sp).convert("RGBA"))[..., 3] == 255
    b = np.asarray(Image.open(f"{rdir}/sprite_{t + 1:03d}.png").convert("RGBA"))[..., 3] > 128
    iou.append(float((a & b).sum() / max((a | b).sum(), 1)))
rep = {}
for k, s0, s1 in fj["segments"]:
    r = rep.setdefault(k, {"frames": 0, "iou": [], "worstFrameEdges2x": 0, "maxStretch": 0.0})
    r["frames"] += s1 - s0; r["iou"] += iou[s0:s1]
    r["worstFrameEdges2x"] = max(r["worstFrameEdges2x"], max(st[i][2] for i in range(s0, s1)))
    r["maxStretch"] = round(max(r["maxStretch"], max(st[i][0] for i in range(s0, s1))), 2)
for k, r in rep.items():
    r["meanIoU"] = round(float(np.mean(r.pop("iou"))), 3)
    print(f"{k:18s} {r}")
print("reel edges>2x summed over frames:", int(sum(s[2] for s in st)))
print("loops:", fj.get("loops"))
json.dump({"perFrameIoU": iou, "stretch": st, "perClip": rep, "loops": fj.get("loops")}, open(out, "w"), indent=1)
