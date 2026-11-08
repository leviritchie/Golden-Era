#!/usr/bin/env bash
# run_chest_panel.sh <unit> <out_tag> <scratch_dir> [--edge 0.03]
# Chest-panel surgery for robed casters whose forearms Meshy fused across the chest (h3_zealot, h3_monk):
# prep.py (cut + hidden-front removal) -> blender_panel.py (Blender bmesh fill, via launch_guard) -> fair.py
# (sparse min-curvature fairing + arm clamp) -> finish.py (artifacts/homm3_mesh_surgery/<unit>_<out_tag>.glb).
# The weights reference is the unit's current retarget GLB (ForeArm/Hand shares by position); once a surgery mesh has
# been delivered, pass the pre-surgery GLB instead (REF=<authenticity before/shipped.glb>).
# FAIR="--inflate 0.03 --clamp back" passes fairing options (h3_zealot chest_c3).
set -euo pipefail
U=$1; TAG=$2; S=$3; shift 3
EDGE=${EDGE:-0.03}
R=$(cd "$(dirname "$0")/../../.." && pwd); D="$R/tools/homm3_def_retarget/chest_panel"
B="${BLENDER:-/v/Tools/blender-mcp/blender-5.2.2/blender.exe}"
mkdir -p "$S"
python "$D/prep.py" "$R/artifacts/meshy_downloads/${U}_smartrigged.glb" "${REF:-$R/artifacts/homm3_def_retarget/$U/${U}_def_retarget.glb}" "$S/p1.npz" "$@"
python "$R/tools/homm3_def_retarget/launch_guard.py" --exec -- "$B" -b --factory-startup --python "$D/blender_panel.py" -- "$S/p1.npz" "$S/p2.npz" --edge "$EDGE" | grep -E "PANEL|Traceback|Error" || true
test -f "$S/p2.npz"
python "$D/fair.py" "$S/p1.npz" "$S/p2.npz" "$S/p3.npz" ${FAIR:-}
python "$D/finish.py" "$R/artifacts/meshy_downloads/${U}_smartrigged.glb" "$S/p1.npz" "$S/p3.npz" "$R/artifacts/homm3_mesh_surgery/${U}_${TAG}.glb" --reason "${REASON:-}"
