#!/usr/bin/env bash
# Launch / env helpers for the V:-only ComfyUI install.
# All caches and models stay on V: — do not let pip/HF/torch spill to C:.

set -euo pipefail

ML_ROOT="V:/ml"
COMFY_ROOT="${ML_ROOT}/ComfyUI"
VENV_PY="${COMFY_ROOT}/.venv/Scripts/python.exe"

export PIP_CACHE_DIR="${ML_ROOT}/caches/pip"
export HF_HOME="${ML_ROOT}/caches/huggingface"
export HUGGINGFACE_HUB_CACHE="${ML_ROOT}/caches/huggingface/hub"
export TORCH_HOME="${ML_ROOT}/caches/torch"
export TMPDIR="${ML_ROOT}/caches/tmp"
export TEMP="${ML_ROOT}/caches/tmp"
export TMP="${ML_ROOT}/caches/tmp"
export PYTHONNOUSERSITE=1
# Keep CUDA on the discrete GPU (Blackwell RTX 5070 Ti).
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.0}"

mkdir -p \
  "${PIP_CACHE_DIR}" \
  "${HUGGINGFACE_HUB_CACHE}" \
  "${TORCH_HOME}" \
  "${TMPDIR}" \
  "${COMFY_ROOT}/models/checkpoints" \
  "${COMFY_ROOT}/models/loras" \
  "${COMFY_ROOT}/models/controlnet" \
  "${COMFY_ROOT}/models/upscale_models" \
  "${COMFY_ROOT}/output" \
  "${COMFY_ROOT}/input"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "ERROR: ComfyUI venv missing at ${VENV_PY}" >&2
  exit 1
fi

cmd="${1:-serve}"
shift || true

case "${cmd}" in
  env)
    echo "ML_ROOT=${ML_ROOT}"
    echo "COMFY_ROOT=${COMFY_ROOT}"
    echo "PIP_CACHE_DIR=${PIP_CACHE_DIR}"
    echo "HF_HOME=${HF_HOME}"
    echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
    "${VENV_PY}" - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    print("capability", torch.cuda.get_device_capability(0))
    print("vram_gb", round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2))
PY
    ;;
  serve)
    cd "${COMFY_ROOT}"
    # Exact-size workflows + API for the collapse-authentic loop.
    exec "${VENV_PY}" main.py --listen 127.0.0.1 --port 8188 "$@"
    ;;
  python)
    exec "${VENV_PY}" "$@"
    ;;
  pip)
    exec "${VENV_PY}" -m pip "$@"
    ;;
  *)
    echo "Usage: $0 {env|serve|python|pip} ..." >&2
    exit 2
    ;;
esac
