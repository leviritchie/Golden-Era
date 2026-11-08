"""Key-frame comparison sheet (DEF | sprite camera | side) for one unit.

Usage: python keysheet.py <unit> [scale]
Picks idle start, move middle, hit/defence middle, two attack frames, two shoot frames
(if any) and two death frames from artifacts/homm3_def_retarget/<unit>/renders/cmp_*.png.
"""
import json, sys
from PIL import Image
u = sys.argv[1]; sc = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
O = f"V:/games/Olden Era Playtest Tweak/artifacts/homm3_def_retarget/{u}"
fj = json.load(open(f"{O}/{u}_def_retarget.blend.frames.json"))
seg = {}
for k, a, b in fj["segments"]:
    if k not in seg or b - a > seg[k][1] - seg[k][0]:
        seg[k] = (a, b)
ids = []
for k, picks in [("g02_idle", [0]), ("g00_move", [0.5]), ("g03_hitted", [0.5]), ("g04_defence", [0.5]),
                 ("g12_attack_front", [0.4, 0.7]), ("g15_shoot_front", [0.35, 0.6]), ("g05_death", [0.4, 1.0])]:
    if k in seg:
        a, b = seg[k]
        ids += [min(b - 1, a + int(round(p * (b - a - 1)))) for p in picks]
ims = [Image.open(f"{O}/renders/cmp_{i:03d}.png") for i in ids]
w, h = ims[0].size; rows = (len(ims) + 1) // 2
s = Image.new("RGB", (w * 2, h * rows))
for k, im in enumerate(ims):
    s.paste(im, ((k % 2) * w, (k // 2) * h))
s = s.resize((int(s.width * sc), int(s.height * sc)))
s.save(f"{O}/keyframes_sheet.png")
print(f"{O}/keyframes_sheet.png", s.size)
