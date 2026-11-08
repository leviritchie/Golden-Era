#!/usr/bin/env bash
# Review media for the roster rollout: every exception class plus six normal units, each against the
# nearest native idle (make_review.sh), then one contact grid of the exception reviews.
#
#   bash tools/homm3_idle_cadence/review_roster.sh [unit ...]      (default: the whole list below)
#
# Writes artifacts/homm3_idle_cadence/review/<unit>/<unit>_idle_review.mp4 and
# artifacts/homm3_idle_cadence/review/exceptions_grid.mp4. make_review.sh runs memgate before each
# Blender launch. Run rollout_idle.py first.
set -euo pipefail
R="V:/games/Olden Era Playtest Tweak"
cd "$R"
# unit  native_prefab  native_ctrl  class
LIST="
h3_dragon_fly wasp wasp_ctrl wingDecouple
h3_damsel_fly wasp wasp_ctrl wingDecouple
h3_serpent_fly wasp wasp_ctrl wingDecouple
h3_fargazer world_watcher world_watcher fastAfterRule
h3_hurricane_elemental eldritch_flyer eldritch_flyer_ctrl fastAfterRule
h3_hydra hydra hydra_ctrl nearStatic
h3_basilisk giant_turtle giant_turtle_ctrl nearStatic
hota_bulwark_mammoth giant_turtle giant_turtle_ctrl nearStatic
hota_cove_nix naiad Naiad_ctrl nearStatic
h3_elf_wardancer blade_dancer blade_dancer_ctrl static
h3_automaton_upg_alt Animated_Armor animated_armor_ctrl static
h3_angel angel h_angel_ctrl normal
h3_skeleton Skeleton Skeleton_Anim normal
h3_black_dragon black_dragon black_dragon_ctrl normal
h3_unicorn Unicorn unicorn_ctrl normal
h3_troglodyte troglodyte troglodyte_unit__ctrl normal
h3_crossbowman crossbowman crossbowman_ctrl normal
"
want=" $* "
echo "$LIST" | while read -r U NP NC CLS; do
  [ -z "${U:-}" ] && continue
  [ $# -gt 0 ] && [[ "$want" != *" $U "* ]] && continue
  echo "== $U ($CLS) vs native $NP"
  bash tools/homm3_idle_cadence/make_review.sh "$U" "$NP" "$NC" < /dev/null
done
# contact grid: exception reviews, 3 per row, 8 s, 1x real time
OUT="$R/artifacts/homm3_idle_cadence/review"
EX=$(echo "$LIST" | awk '$4 != "normal" && NF {print $1}')
ins=(); n=0
for U in $EX; do
  f="$OUT/$U/${U}_idle_review.mp4"; [ -f "$f" ] || continue
  ins+=(-i "$f"); n=$((n+1))
done
[ $n -eq 0 ] && exit 0
cols=3
# xstack needs pixel offsets; every tile gets the first review's aspect at 640 px wide
FIRST=$(echo $EX | awk '{print $1}')
H=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$OUT/$FIRST/${FIRST}_idle_review.mp4" | awk -F, '{printf "%d", 640*$2/$1}')
H=$(( (H / 2) * 2 ))
layout=""
for ((i=0;i<n;i++)); do layout+="$(( (i % cols) * 640 ))_$(( (i / cols) * H ))|"; done
inputs=""; for ((i=0;i<n;i++)); do inputs+="[v$i]"; done
fc=""; for ((i=0;i<n;i++)); do fc+="[$i:v]scale=640:$H,setsar=1[v$i];"; done
ffmpeg -y -loglevel error "${ins[@]}" -filter_complex "${fc}${inputs}xstack=inputs=$n:layout=${layout%|}:fill=white,format=yuv420p[v]" \
  -map "[v]" -t 8 -r 30 -c:v libx264 -crf 23 "$OUT/exceptions_grid.mp4"
echo "GRID $OUT/exceptions_grid.mp4"
