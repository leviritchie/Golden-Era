"""DEF-over-mesh strip for one clip. Usage: python clipstrip.py <unit> <clipKey> [every]"""
import json, sys
from PIL import Image
u, key = sys.argv[1], sys.argv[2]; every = int(sys.argv[3]) if len(sys.argv) > 3 else 1
O = f"V:/games/Olden Era Playtest Tweak/artifacts/homm3_def_retarget/{u}"
fj = json.load(open(f"{O}/{u}_def_retarget.blend.frames.json"))
a, b = max(((s[1], s[2]) for s in fj["segments"] if s[0] == key), key=lambda x: x[1] - x[0])
C = (70, 60, 380, 320); w, h = C[2] - C[0], C[3] - C[1]
ids = list(range(a, b, every))
s = Image.new("RGB", (w * len(ids), h * 2), (45, 45, 45))
for k, t in enumerate(ids):
    x = Image.open(fj["sources"][t]).convert("RGBA").crop(C); s.paste(x, (k * w, 0), x)
    y = Image.open(f"{O}/renders/sprite_{t + 1:03d}.png").convert("RGBA").crop(C); s.paste(y, (k * w, h), y)
if s.width > 2400:
    s = s.resize((2400, int(s.height * 2400 / s.width)))
s.save(f"{O}/strip_{key}.png"); print(f"{O}/strip_{key}.png")
