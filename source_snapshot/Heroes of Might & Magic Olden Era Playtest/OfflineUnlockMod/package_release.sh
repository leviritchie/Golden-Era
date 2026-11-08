#!/usr/bin/env bash
# Builds Release and zips a public distribution. Requires zip(1), or use package_release.ps1 on Windows.
set -euo pipefail
cd "$(dirname "$0")"

ver="$(sed -n 's/.*const string PluginVersion = "\([^"]*\)".*/\1/p' Plugin.cs | head -1)"
if [[ -z "$ver" ]]; then
  echo "Could not read PluginVersion from Plugin.cs" >&2
  exit 1
fi
echo "Plugin version: $ver"

dotnet build -c Release -p:DeployPluginToGame=false
bin="bin/Release/netstandard2.1"
test -f "$bin/OfflineUnlockMod.dll" || { echo "Missing build output" >&2; exit 1; }
test -f "$bin/OfflineUnlockMod.deps.json" || { echo "Missing deps.json" >&2; exit 1; }

out="dist_package"
rm -rf "$out"
mkdir -p "$out/BepInEx/plugins/OfflineUnlockMod"
cp "$bin/OfflineUnlockMod.dll" "$bin/OfflineUnlockMod.deps.json" "$out/BepInEx/plugins/OfflineUnlockMod/"
cp publish/config.json.example "$out/BepInEx/plugins/OfflineUnlockMod/"
cp -R histogram_icons "$out/BepInEx/plugins/OfflineUnlockMod/"
cp -R homm3_runtime_assets "$out/BepInEx/plugins/OfflineUnlockMod/"
cp -R homm3_town_prefabs "$out/BepInEx/plugins/OfflineUnlockMod/"
cp publish/README-INSTALL.txt "$out/"

zipname="HeroesOE-DamageHistogram-v${ver}.zip"
rm -f "$zipname"
if command -v zip &>/dev/null; then
  ( cd "$out" && zip -r "../$zipname" . )
else
  echo "zip(1) not in PATH. On Windows use:  powershell -File package_release.ps1" >&2
  exit 1
fi
rm -rf "$out"
ls -la "$zipname"
