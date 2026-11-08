#!/usr/bin/env bash
# Idle cadence review for one rolled-out unit: mesh renders (before / after) and the
# native | before | after stick figures, composed into one 1x real-time mp4.
#
#   bash tools/homm3_idle_cadence/make_review.sh <unit> <native_prefab> <native_ctrl>
#
# Reads the unit's roster report (artifacts/homm3_idle_cadence/roster/<unit>/report.json, written by
# rollout_idle.py): its "src" (the retime input) and "dst" (the retimed GLB). Writes
# artifacts/homm3_idle_cadence/review/<unit>/: <unit>_idle_sticks.mp4, <unit>_idle_review.mp4.
# Never writes a GLB. Run rollout_idle.py <unit> first.
set -euo pipefail
U="$1"; NP="$2"; NC="$3"
R="V:/games/Olden Era Playtest Tweak"
B="${BLENDER:-/v/Tools/blender-mcp/blender-5.2.2/blender.exe}"
REP="$R/artifacts/homm3_idle_cadence/roster/$U/report.json"
SRC="$R/$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['src'])" "$REP")"
DST="$R/$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['dst'])" "$REP")"
TRT="$(python -c "import json,sys;r=json.load(open(sys.argv[1]));print(r['treatment']+(' wing x%d'%r['wingCycles'] if r.get('wingCycles') else ''))" "$REP")"
OUT="$R/artifacts/homm3_idle_cadence/review/$U"
TMPD="${TMP:-/tmp}/homm3_idle_cadence/$U"
T=tools/homm3_idle_cadence
SECS=8
mkdir -p "$OUT" "$TMPD"
cd "$R"
for tag in before after; do
  G="$SRC"; [ "$tag" = after ] && G="$DST"
  rm -rf "$TMPD/$tag"
  python tools/homm3_def_retarget/memgate.py --wait 6
  "$B" -b --factory-startup -P $T/render_idle_blender.py -- "$G" Unit_Idle "$TMPD/$tag" 2>&1 | grep -E "^(CLIP|RENDERED|FAIL)"
done
python $T/review_sticks.py --native-prefab "$NP" --native-ctrl "$NC" --before "$SRC" \
  --after "$DST" --out "$OUT/${U}_idle_sticks.mp4" --seconds $SECS \
  --title "$U vs native $NP - idle, 1x real time"
FONT="fontfile='C\:/Windows/Fonts/arial.ttf'"
ffmpeg -y -loglevel error \
  -stream_loop -1 -framerate 30 -i "$TMPD/before/f_%04d.png" \
  -stream_loop -1 -framerate 30 -i "$TMPD/after/f_%04d.png" \
  -i "$OUT/${U}_idle_sticks.mp4" \
  -filter_complex "[0:v]drawtext=$FONT:text='ours BEFORE (DEF 12 fps)':x=10:y=h-th-10:fontsize=18:fontcolor=black[a];\
[1:v]drawtext=$FONT:text='ours AFTER ($TRT x3.2 eased)':x=10:y=h-th-10:fontsize=18:fontcolor=black[b];\
[a][b]hstack[top];[top]scale=1200:-2,pad=1200:ih:0:0:white[t2];[2:v]scale=1200:-2[s];[t2][s]vstack,format=yuv420p[v]" \
  -map "[v]" -t $SECS -r 30 -c:v libx264 -crf 20 "$OUT/${U}_idle_review.mp4"
echo "REVIEW $OUT/${U}_idle_review.mp4"
