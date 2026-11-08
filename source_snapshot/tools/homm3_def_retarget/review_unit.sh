#!/usr/bin/env bash
# High-res review renders for one unit (works on a copy so the build .blend is untouched).
set -euo pipefail
U="$1"; RES="${2:-768}"
T="$(cygpath -m "$(cd "$(dirname "$0")" && pwd)")"
A="V:/games/Olden Era Playtest Tweak/artifacts/homm3_def_retarget/$U"
B="${BLENDER:-/v/Tools/blender-mcp/blender-5.2.2/blender.exe}"
rm -rf "${A:?}/review"; mkdir -p "$A/review"
cp "$A/${U}_def_retarget.blend" "$A/review/tmp.blend"
cp "$A/${U}_def_retarget.blend.frames.json" "$A/review/tmp.blend.frames.json"
cp "$A/stretch.json" "$A/review/stretch.json"
python "$T/launch_guard.py" --exec -- "$B" -b "$A/review/tmp.blend" -P "$T/review.py" -- "$A/review/r" "$RES" 2>&1 | grep -E "Traceback|Error:" || true
rm -f "$A/review/tmp.blend" "$A/review/tmp.blend1"
python - "$A/review" <<'PY'
import json,sys,glob
from PIL import Image,ImageDraw
d=sys.argv[1];j=json.load(open(d+"/r.json"));seg=j["segments"]
ims=[]
for t,s in zip(j["frames"],j["stretch"]):
    a=Image.open(f"{d}/r_{t:03d}_0.png");b=Image.open(f"{d}/r_{t:03d}_1.png")
    w,h=a.size;c=Image.new("RGB",(w*2,h));c.paste(a,(0,0));c.paste(b,(w,0))
    k=[x[0] for x in seg if x[1]<=t<x[2]][0]
    ImageDraw.Draw(c).text((8,8),f"frame {t} {k}  max {s[0]:.1f}x  edges>2x {s[2]}",fill=(255,255,255))
    c.save(f"{d}/pair_{t:03d}.png")
PY
