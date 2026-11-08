#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE_DIR="$REPO_ROOT/tools/official_deobf_port_smoke"
GAME_ROOT="${GAME_ROOT:-V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era}"
PROJECT="$REPO_ROOT/Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj"
PLUGIN_DIR="$GAME_ROOT/BepInEx/plugins/OfflineUnlockMod"
BACKUP_DIR="$SMOKE_DIR/backups/$(date +%Y%m%d-%H%M%S)"
STAMP_FILE="$SMOKE_DIR/.last_backup"

mkdir -p "$BACKUP_DIR" "$PLUGIN_DIR"

echo "==> Golden Era port-smoke deploy"
echo "    Game root: $GAME_ROOT"
echo "    Backup:    $BACKUP_DIR"

backup_if_exists() {
  local src="$1"
  local name="$2"
  if [[ -f "$src" ]]; then
    cp -f "$src" "$BACKUP_DIR/$name"
    echo "    backed up $name"
  fi
}

backup_if_exists "$GAME_ROOT/OfflineLauncherConfig.json" "OfflineLauncherConfig.json"
backup_if_exists "$PLUGIN_DIR/config.json" "config.json"

if compgen -G "$PLUGIN_DIR/*.flag" > /dev/null; then
  mkdir -p "$BACKUP_DIR/flags"
  cp -f "$PLUGIN_DIR"/*.flag "$BACKUP_DIR/flags/" 2>/dev/null || true
  echo "    backed up existing *.flag files"
fi

echo "$BACKUP_DIR" > "$STAMP_FILE"

echo "==> Building and deploying mod (OfficialDeobfBuild)..."
dotnet build -c Release \
  "-p:GameRoot=$GAME_ROOT" \
  "-p:DeployPluginToGame=true" \
  "-p:OfficialDeobfBuild=true" \
  "$PROJECT" \
  -clp:ErrorsOnly

echo "==> Installing port-smoke config..."
cp -f "$SMOKE_DIR/config.port_smoke.json" "$PLUGIN_DIR/config.json"
cp -f "$SMOKE_DIR/OfflineLauncherConfig.json" "$GAME_ROOT/OfflineLauncherConfig.json"

echo "==> Enabling diagnostic flags..."
for flag in "$SMOKE_DIR/flags/"*.flag; do
  [[ -f "$flag" ]] || continue
  cp -f "$flag" "$PLUGIN_DIR/$(basename "$flag")"
  echo "    $(basename "$flag")"
done

cat <<EOF

Done. Launch the Golden Era install.

Expected startup log lines:
  - Port-smoke profile active
  - RegisterRequired* registration lines (or LogFatal if symbols drift)

Auto-launch: on when OfflineLauncherConfig.json has autoLaunchOnMenu=true (port-smoke preserves it).
Logs: $GAME_ROOT/BepInEx/LogOutput.log

Restore prior configs: bash tools/restore_official_deobf_port_smoke.sh
Smoke guide: tools/official_deobf_port_smoke/README.md
EOF
