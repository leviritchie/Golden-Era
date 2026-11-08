#!/usr/bin/env bash
# Lane B driver (Git Bash). Usage: ./build_homm3_units.sh <homm3UnitSid> [--unity-direct]
# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out (one direct launch per step through tools/homm3_vfx/unitylock.py).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export UNITY="${UNITY:-/c/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe}"
SID="${1:-}"
UNITY_DIRECT="${2:-}"
if [[ -z "$SID" ]]; then
  echo "usage: $0 <homm3UnitSid>" >&2
  exit 1
fi
mkdir -p "$SCRIPT_DIR/build_out"
UNIT_LIST="$SCRIPT_DIR/build_out/homm3_bundle_unit_${SID}.txt"
printf '%s\n' "$SID" > "$UNIT_LIST"

if [[ -n "${OLDENERA_UNITY_PROJECT:-}" && -f "$OLDENERA_UNITY_PROJECT/ProjectSettings/ProjectVersion.txt" ]]; then
  PROJECT="$OLDENERA_UNITY_PROJECT"
elif [[ -f "$REPO_ROOT/oldenera_factions/ProjectSettings/ProjectVersion.txt" ]]; then
  PROJECT="$REPO_ROOT/oldenera_factions"
elif [[ -f "/c/Users/<user>/oldenera_factions/ProjectSettings/ProjectVersion.txt" ]]; then
  PROJECT="/c/Users/<user>/oldenera_factions"
else
  echo "No Unity project; set OLDENERA_UNITY_PROJECT" >&2
  exit 1
fi

if [[ "${HOM3_EXTRACT:-}" == "1" ]]; then
  py -3 "$SCRIPT_DIR/extract_creature.py" --unit "$SID" --unity-project "$PROJECT"
fi

mkdir -p "$PROJECT/Assets/Editor"
cp -f "$SCRIPT_DIR/unity_editor/"*.cs "$PROJECT/Assets/Editor/"
cp -f "$SCRIPT_DIR/../custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs" "$PROJECT/Assets/Editor/"

py -3 "$SCRIPT_DIR/stage_homm3_unit_audio.py" --unity-project "$PROJECT" --unit "$SID"

# unity_job <kind> <executeMethod> <log> <output-dir|-> <job args...>
unity_job() {
  local kind="$1" method="$2" log="$3" outdir="$4"
  shift 4
  if [[ "$UNITY_DIRECT" == "--unity-direct" ]]; then
    echo "UNITY_QUEUE BYPASS: --unity-direct launches $method outside the queue (docs/unity_queue_runner.md)" >&2
    py -3 "$REPO_ROOT/tools/homm3_vfx/unitylock.py" run --wait 60 -- "$UNITY" -batchmode -quit -nographics \
      -projectPath "$PROJECT" -executeMethod "$method" "$@" -logFile "$log"
    return
  fi
  local extra=()
  [[ "$outdir" != "-" ]] && extra+=(--output-dir "$(cygpath -w "$outdir")")
  py -3 "$REPO_ROOT/tools/unity_queue/unity_queue.py" submit --wait --kind "$kind" --method "$method" \
    --project "$(cygpath -w "$PROJECT")" --unity "$(cygpath -w "$UNITY")" --log "$(cygpath -w "$log")" \
    --requester "build_homm3_units.sh $SID" "${extra[@]}" -- "$@"
}

unity_job homm3_battle_sound_prefabs OldenEra.Homm3Import.Homm3BattleSoundPrefabsBuild.RebuildFromBatch \
  "$SCRIPT_DIR/unity_homm3_sound_prefab_build.log" - -homm3UnitSid "$SID"

unity_job homm3_billboard_animator OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildFromBatch \
  "$SCRIPT_DIR/unity_homm3_anim_build.log" - -homm3UnitSid "$SID"

unity_job homm3_unit_bundles OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest \
  "$SCRIPT_DIR/unity_homm3_bundle_build.log" "$SCRIPT_DIR/build_out" \
  -manifestPath "$(cygpath -w "$SCRIPT_DIR/homm3_units_manifest.json")" \
  -homm3UnitListPath "$(cygpath -w "$UNIT_LIST")" \
  -outputPath "$(cygpath -w "$SCRIPT_DIR/build_out")"

echo "OK — $SCRIPT_DIR/build_out"
