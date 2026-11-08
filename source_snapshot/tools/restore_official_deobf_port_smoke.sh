#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE_DIR="$REPO_ROOT/tools/official_deobf_port_smoke"
GAME_ROOT="${GAME_ROOT:-V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era}"
PLUGIN_DIR="$GAME_ROOT/BepInEx/plugins/OfflineUnlockMod"
STAMP_FILE="$SMOKE_DIR/.last_backup"

if [[ ! -f "$STAMP_FILE" ]]; then
  echo "No backup stamp found. Nothing to restore." >&2
  exit 1
fi

BACKUP_DIR="$(cat "$STAMP_FILE")"
if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "Backup directory missing: $BACKUP_DIR" >&2
  exit 1
fi

echo "==> Restoring from $BACKUP_DIR"

restore_or_remove() {
  local backup="$1"
  local dest="$2"
  if [[ -f "$backup" ]]; then
    cp -f "$backup" "$dest"
    echo "    restored $(basename "$dest")"
  elif [[ -f "$dest" ]]; then
    rm -f "$dest"
    echo "    removed $(basename "$dest") (was not present before deploy)"
  fi
}

restore_or_remove "$BACKUP_DIR/OfflineLauncherConfig.json" "$GAME_ROOT/OfflineLauncherConfig.json"
restore_or_remove "$BACKUP_DIR/config.json" "$PLUGIN_DIR/config.json"

for flag in "$SMOKE_DIR/flags/"*.flag; do
  [[ -f "$flag" ]] || continue
  name="$(basename "$flag")"
  backup_flag="$BACKUP_DIR/flags/$name"
  if [[ -f "$backup_flag" ]]; then
    cp -f "$backup_flag" "$PLUGIN_DIR/$name"
    echo "    restored flag $name"
  elif [[ -f "$PLUGIN_DIR/$name" ]]; then
    rm -f "$PLUGIN_DIR/$name"
    echo "    removed flag $name"
  fi
done

echo "Done."
