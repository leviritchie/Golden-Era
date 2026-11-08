#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GA="$ROOT/GameAssembly.dll"
META="$ROOT/HeroesOE_Data/il2cpp_data/Metadata/global-metadata.dat"
OUT="$ROOT/tools/il2cpp_out"
DUMPER_DIR="$ROOT/tools/il2cpp_dumper"

if [[ ! -f "$GA" ]]; then
  echo "ERROR: GameAssembly.dll not found: $GA" >&2
  exit 1
fi
if [[ ! -f "$META" ]]; then
  echo "ERROR: global-metadata.dat not found: $META" >&2
  exit 1
fi

if command -v python >/dev/null 2>&1; then
  python "$ROOT/tools/il2cpp_dumper_headless_config.py" "$ROOT" || true
fi

# Prefer Windows exe under Git Bash / WSL if present
EXE="$DUMPER_DIR/Il2CppDumper.exe"
DLL="$DUMPER_DIR/Il2CppDumper.dll"
NIX="$DUMPER_DIR/Il2CppDumper"
if [[ -f "$EXE" ]]; then
  mkdir -p "$OUT"
  echo "Running: $EXE"
  "$EXE" "$GA" "$META" "$OUT"
elif [[ -f "$NIX" && -x "$NIX" ]]; then
  mkdir -p "$OUT"
  echo "Running: $NIX"
  "$NIX" "$GA" "$META" "$OUT"
elif [[ -f "$DLL" ]] && command -v dotnet >/dev/null 2>&1; then
  mkdir -p "$OUT"
  echo "Running: dotnet $DLL"
  dotnet "$DLL" "$GA" "$META" "$OUT"
else
  echo "ERROR: No Il2CppDumper found in $DUMPER_DIR" >&2
  echo "Download: https://github.com/Perfare/Il2CppDumper/releases" >&2
  echo "Place Il2CppDumper.exe (or Il2CppDumper.dll + dotnet) in tools/il2cpp_dumper/" >&2
  exit 1
fi

echo "OK. Output: $OUT (see docs/il2cpp-map-generate-trace.md for LocKit search hints)."
