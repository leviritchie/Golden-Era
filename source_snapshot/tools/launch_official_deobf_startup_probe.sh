#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME_ROOT="${GAME_ROOT:-V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era}"
EXE="$GAME_ROOT/HeroesOldenEra.exe"
LOG="$GAME_ROOT/BepInEx/LogOutput.log"
PLAYER_LOG="${LOCALAPPDATA:-$HOME/AppData/LocalLow}/Unfrozen/HeroesOldenEra/Player.log"
WAIT_SEC="${WAIT_SEC:-55}"
DEPLOY="${DEPLOY:-1}"

if [[ ! -f "$EXE" ]]; then
  echo "Missing game executable: $EXE" >&2
  exit 1
fi

if [[ "$DEPLOY" == "1" ]]; then
  echo "==> Deploying latest port-smoke build..."
  bash "$REPO_ROOT/tools/deploy_official_deobf_port_smoke.sh"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
ARTIFACT_DIR="$REPO_ROOT/artifacts/official_deobf_startup_probe_$STAMP"
mkdir -p "$ARTIFACT_DIR"
if [[ -f "$LOG" ]]; then
  cp -f "$LOG" "$ARTIFACT_DIR/LogOutput.before.log"
fi

echo "==> Launching game ($WAIT_SEC s startup window)..."
cd "$GAME_ROOT"
"$EXE" &
GAME_PID=$!
echo "    PID=$GAME_PID"

cleanup() {
  if kill -0 "$GAME_PID" 2>/dev/null; then
    taskkill //F //PID "$GAME_PID" >/dev/null 2>&1 || kill "$GAME_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

sleep "$WAIT_SEC"
cleanup
trap - EXIT

if [[ -f "$LOG" ]]; then
  cp -f "$LOG" "$ARTIFACT_DIR/LogOutput.after.log"
fi
if [[ -f "$PLAYER_LOG" ]]; then
  cp -f "$PLAYER_LOG" "$ARTIFACT_DIR/Player.log"
fi

python "$REPO_ROOT/tools/parse_official_deobf_startup_log.py" "$ARTIFACT_DIR/LogOutput.after.log" "$ARTIFACT_DIR/startup_report.txt" || true

echo
echo "Report: $ARTIFACT_DIR/startup_report.txt"
