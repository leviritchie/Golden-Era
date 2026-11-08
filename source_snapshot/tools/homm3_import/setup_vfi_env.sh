#!/usr/bin/env bash
# Install VFI dependencies on V: (not C:). Run from repo root:
#   bash tools/homm3_import/setup_vfi_env.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="$ROOT/tools"
export PIP_CACHE_DIR="$TOOLS/.cache/pip"
export TMPDIR="$TOOLS/.cache/tmp"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
export LOCALAPPDATA="$TOOLS/.cache/localappdata"
export PYTHONPYCACHEPREFIX="$TOOLS/.cache/pycache"
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR" "$LOCALAPPDATA" "$PYTHONPYCACHEPREFIX" "$TOOLS/vendor"

if [[ ! -x "$TOOLS/.venv-homm3-vfi/Scripts/python.exe" && ! -x "$TOOLS/.venv-homm3-vfi/bin/python" ]]; then
  python -m venv "$TOOLS/.venv-homm3-vfi"
fi
PY="$TOOLS/.venv-homm3-vfi/Scripts/python.exe"
[[ -x "$PY" ]] || PY="$TOOLS/.venv-homm3-vfi/bin/python"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install --cache-dir "$PIP_CACHE_DIR" pillow numpy opencv-python-headless imageio-ffmpeg

RIFE_ZIP="$TOOLS/vendor/rife-ncnn-vulkan-20221029-windows.zip"
RIFE_DIR="$TOOLS/vendor/rife-ncnn-vulkan-20221029-windows"
if [[ ! -f "$RIFE_DIR/rife-ncnn-vulkan.exe" ]]; then
  echo "Downloading rife-ncnn-vulkan (~412MB) to $TOOLS/vendor ..."
  curl -L -o "$RIFE_ZIP" "https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-windows.zip"
  unzip -q -o "$RIFE_ZIP" -d "$TOOLS/vendor"
fi

if [[ ! -d "$TOOLS/vendor/Practical-RIFE" ]]; then
  git clone --depth 1 https://github.com/hzwer/Practical-RIFE.git "$TOOLS/vendor/Practical-RIFE"
fi

echo "OK: venv=$TOOLS/.venv-homm3-vfi"
echo "OK: rife=$RIFE_DIR/rife-ncnn-vulkan.exe"
echo "Run: \"$PY\" tools/homm3_import/build_animation_ai_interpolation_comparison.py"
