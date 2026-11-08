#!/usr/bin/env bash
# Build, render, measure and export one unit.  Usage: run_unit.sh <unit>   (config in units/<unit>.json)
# RENDER_ONLY=1 skips the build and re-renders / re-measures / re-exports an existing .blend.
# Fails closed: every Blender step runs with --python-exit-code 1, its full output goes to <out>/logs/<step>.log,
# and a nonzero exit, a Python traceback or a missing completion marker (SAVED / EXPORTED) stops the run. Before
# 2026-09-27 each step was piped through `grep ... || true`, so a build that raised after its hooks exported the
# previous .blend as if it were new. The .blend (full build), stretch.json and the GLB must also be newer than the run.
set -euo pipefail
U="$1"
T="$(cygpath -m "$(cd "$(dirname "$0")" && pwd)")"
R="V:/games/Olden Era Playtest Tweak"
B="${BLENDER:-/v/Tools/blender-mcp/blender-5.2.2/blender.exe}"
LM="$R/artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/$U/linked_master"
MS="$LM/master_sequence/master_sequence.json"
O="$R/artifacts/homm3_def_retarget/$U${OUT_TAG:-}"   # OUT_TAG / CFG_OVERRIDE / MESH_OVERRIDE: side-by-side experiments
CFG="${CFG_OVERRIDE:-$T/units/$U.json}"
BLEND="$O/${U}_def_retarget.blend"
L="$O/logs"
mkdir -p "$O/renders" "$L"
START=$(date +%s)
# newer <file>: the file was written by this run (a failed step must never pass off an earlier run's output)
newer() {
  local m; m=$(stat -c %Y "$1" 2>/dev/null || echo 0)
  if [ "$m" -lt "$START" ]; then echo "run_unit.sh $U: $1 was not written by this run (mtime $m < start $START)" >&2; exit 1; fi
}

# bl <step> <marker regex | -> <blender args...>: run Blender, keep its log, fail on exit code / traceback / marker
bl() {
  local step="$1" marker="$2"; shift 2
  local log="$L/$step.log" rc=0
  # launch_guard --exec: the guard, then Blender with the child env it owns (blender_env); both land in the step log
  python "$T/launch_guard.py" --exec -- "$B" -b --python-exit-code 1 "$@" > "$log" 2>&1 || rc=$?
  if ! grep -q "^LAUNCH_GUARD OK" "$log"; then
    grep "LAUNCH_GUARD" "$log" >&2 || true
    echo "run_unit.sh $U: launch guard refused Blender step '$step'; log $log" >&2
    exit 1
  fi
  if [ "$rc" -ne 0 ] || grep -q "Traceback" "$log" || { [ "$marker" != "-" ] && ! grep -qE "$marker" "$log"; }; then
    grep -E -A12 "Traceback" "$log" | head -40 >&2 || true
    echo "run_unit.sh $U: blender step '$step' failed (exit $rc, marker '$marker'); log $log" >&2
    exit 1
  fi
}
# show <regex> <log>: print matching lines; no match is not an error, a grep error is
show() { grep -E "$1" "$2" || [ $? -eq 1 ]; }
# txn <flag>: a run that writes the canonical GLB outside fleet_rebuild snapshots the delivered state before it writes
# anything, so the fleet_rebuild that follows restores the previous delivery, not this raw export, when it fails
# (2026-10-09 h3_sharpshooter). Side-by-side runs (OUT_TAG) and fleet_rebuild's own calls (inside its transaction) skip.
txn() {
  if [ -z "${OUT_TAG:-}" ] && [ -z "${FLEET_REBUILD_TXN:-}" ]; then
    python "$R/tools/homm3_def_retarget_delivery/fleet_rebuild.py" "$1" "$U"
  fi
}
txn --pre-run-snapshot

if [ -z "${RENDER_ONLY:-}" ]; then
  if python -c "import json,sys;sys.exit(0 if 'flail' in json.load(open(r'$CFG')) else 1)"; then
    SEED=$(python -c "import json;print(','.join(str(v) for v in json.load(open(r'$CFG'))['ballSeed']))")
    python "$T/ball_detect.py" "$MS" "$O/def_ball_track" "$SEED"
    SPRITE="$O/def_ball_track.json"
  else
    python "$T/sprite_info.py" "$MS" "$O/sprite_info.json"
    SPRITE="$O/sprite_info.json"
  fi
  # source mesh: MESH_OVERRIDE (side-by-side experiments, with OUT_TAG), else the config's "sourceMesh" (repo-relative;
  # a unit built from a reviewed mesh other than its own smartrigged file, which identity_reviews.json must then pin),
  # else artifacts/meshy_downloads/<unit>_smartrigged.glb
  CFG_MESH=$(python -c "import json;print(json.load(open(r'$CFG')).get('sourceMesh',''))")
  MESH="${MESH_OVERRIDE:-${CFG_MESH:+$R/$CFG_MESH}}"
  MESH="${MESH:-$R/artifacts/meshy_downloads/${U}_smartrigged.glb}"
  ARGS=("$CFG" "$MESH" "$LM/capture/capture/raw_capture.npz" "$MS" "$SPRITE" "$BLEND")
  rm -f "${BLEND:?}.weights.npz" "${BLEND:?}.heat.npz" "${BLEND:?}1"
  bl build_heat "EXPORTED heat graph" --factory-startup -P "$T/build_unit.py" -- "${ARGS[@]}"
  show "EXPORTED|Error" "$L/build_heat.log"
  python "$T/surface_weights.py" "$BLEND.heat.npz" "$BLEND.weights.npz" "$CFG"
  bl build "^SAVED " --factory-startup -P "$T/build_unit.py" -- "${ARGS[@]}"
  newer "$BLEND"
  show "HOOK|REGION|SLEEVE|TAIL|BLADES|forward|LOOPS|REFINE|BORROWED|SHRINK|SHATTER|GROUND|SAVED|Error" "$L/build.log"
fi
rm -f "${BLEND:?}1" "${O:?}"/renders/*.png
bl render_reel "[Ss]aved" "$BLEND" -P "$T/render_reel.py" -- "$O/renders"
grep -ciE "saved" "$L/render_reel.log"
python "$T/compose.py" "$BLEND" "$O/renders" "$O/${U}_compare.gif"
ffmpeg -y -loglevel error -framerate 8 -i "$O/renders/cmp_%03d.png" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -pix_fmt yuv420p "$O/${U}_compare.mp4"
bl stretch - "$BLEND" -P "$T/stretch.py" -- "$O/stretch.json"
newer "$O/stretch.json"
python "$T/metrics.py" "$BLEND" "$O/renders" "$O/stretch.json" "$O/metrics.json"
bl export "^EXPORTED " "$BLEND" -P "$T/export_glb.py" -- "$O/${U}_def_retarget.glb"
newer "$O/${U}_def_retarget.glb"
txn --pre-run-export
show "EXPORTED|Error" "$L/export.log"
