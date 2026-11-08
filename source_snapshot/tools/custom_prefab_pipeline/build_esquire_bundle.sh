#!/usr/bin/env bash
# Same pipeline as build_esquire_bundle.cmd — use from Git Bash on Windows.
# Close the Unity Editor for the project before running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo root = parent of tools/
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Unity 6000.0.66f2 matches oldenera_factions/ProjectSettings/ProjectVersion.txt
UNITY="${UNITY:-${PROGRAMFILES:-C:/Program Files}/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe}"
# Git Bash: PROGRAMFILES may be unset; normalize to Windows path for Unity.exe
if [[ ! -f "$UNITY" ]] && [[ -f "/c/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe" ]]; then
	UNITY="/c/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe"
fi

MANIFEST="$SCRIPT_DIR/custom_units_manifest.json"
OUT="$SCRIPT_DIR/build_out"
LOG="$SCRIPT_DIR/unity_esquire_bundle_build.log"
SOUNDLOG="$SCRIPT_DIR/unity_esquire_sound_prefabs.log"
ANIMLOG="$SCRIPT_DIR/unity_esquire_anim_build.log"

PROJECT_LOCAL="$REPO_ROOT/oldenera_factions"
PROJECT_LEGACY="${OLDENERA_LEGACY:-C:/Users/<user>/oldenera_factions}"

if [[ ! -f "$UNITY" ]]; then
	echo "Unity not found at: $UNITY"
	echo "Set UNITY= to your Editor/Unity.exe (same major as ProjectSettings)."
	exit 1
fi

PROJECT=""
if [[ -n "${OLDENERA_UNITY_PROJECT:-}" ]]; then
	if [[ -f "$OLDENERA_UNITY_PROJECT/ProjectSettings/ProjectVersion.txt" ]]; then
		PROJECT="$OLDENERA_UNITY_PROJECT"
	else
		echo "ERROR: OLDENERA_UNITY_PROJECT set but ProjectSettings/ProjectVersion.txt missing: $OLDENERA_UNITY_PROJECT"
		exit 1
	fi
fi
if [[ -z "$PROJECT" ]] && [[ -f "$PROJECT_LOCAL/ProjectSettings/ProjectVersion.txt" ]]; then
	PROJECT="$PROJECT_LOCAL"
fi
if [[ -z "$PROJECT" ]] && [[ -f "$PROJECT_LEGACY/ProjectSettings/ProjectVersion.txt" ]]; then
	PROJECT="$PROJECT_LEGACY"
fi
if [[ -z "$PROJECT" ]]; then
	echo "ERROR: No Unity project. Expected one of:"
	echo "  $PROJECT_LOCAL"
	echo "  $PROJECT_LEGACY"
	echo "Or set OLDENERA_UNITY_PROJECT to the project root."
	exit 1
fi
echo "Using Unity project: $PROJECT"

STAGE_SND="${HOMM3_SND:-}"
if [[ -z "$STAGE_SND" ]]; then
	DEFAULT_SND="$REPO_ROOT/HoMM 3 Complete/Data/Heroes3.snd"
	if [[ -f "$DEFAULT_SND" ]]; then
		STAGE_SND="$DEFAULT_SND"
	fi
fi

PY=(py -3)
if ! command -v py &>/dev/null; then
	PY=(python3)
fi

if [[ -n "$STAGE_SND" ]]; then
	echo "Step 0/4: Stage Esquire battle WAVs from HoMM3 SND..."
	"${PY[@]}" "$SCRIPT_DIR/stage_esquire_homm3_audio.py" --unity-project "$PROJECT" --snd "$STAGE_SND"
else
	echo "Step 0/4: Skip HoMM3 audio staging (no Heroes3.snd — set HOMM3_SND)."
fi

mkdir -p "$PROJECT/Assets/Editor"
cp -f "$SCRIPT_DIR"/unity_editor/*.cs "$PROJECT/Assets/Editor/"

echo "Step 1/4: Generate Esquire battle sound prefabs..."
"$UNITY" -batchmode -quit -nographics \
	-projectPath "$PROJECT" \
	-executeMethod OldenEra.CustomUnitBuilder.EsquireBattleSoundPrefabsBuild.RebuildFromBatch \
	-logFile "$SOUNDLOG"

echo "Step 2/4: Rebuild battle flip-book + map mesh billboard..."
"$UNITY" -batchmode -quit -nographics \
	-projectPath "$PROJECT" \
	-executeMethod OldenEra.CustomUnitBuilder.EsquireBillboardAnimatorBuild.RebuildFromBatch \
	-logFile "$ANIMLOG"

echo "Step 3/4: Build AssetBundles..."
"$UNITY" -batchmode -quit -nographics \
	-projectPath "$PROJECT" \
	-executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest \
	-manifestPath "$MANIFEST" \
	-outputPath "$OUT" \
	-logFile "$LOG"

echo "Sound prefab log: $SOUNDLOG"
echo "Animator log: $ANIMLOG"
echo "Bundle log: $LOG"
echo "Next: copy build_out/custom_units_esquire to BepInEx/plugins/OfflineUnlockMod/"
