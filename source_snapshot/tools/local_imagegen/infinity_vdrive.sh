#!/usr/bin/env bash
# V:-only launcher for Infinity-2B sparse invent.
# Keeps pip/HF/torch caches on V: — do not spill to C:.

set -euo pipefail

ML_ROOT="V:/ml"
INFINITY_ROOT="${ML_ROOT}/Infinity"
VENV_PY="${ML_ROOT}/infinity_venv/Scripts/python.exe"
WEIGHTS="${ML_ROOT}/models/infinity"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

export PIP_CACHE_DIR="${ML_ROOT}/caches/pip"
export HF_HOME="${ML_ROOT}/caches/huggingface"
export HUGGINGFACE_HUB_CACHE="${ML_ROOT}/caches/huggingface/hub"
export TORCH_HOME="${ML_ROOT}/caches/torch"
export TMPDIR="${ML_ROOT}/caches/tmp"
export TEMP="${ML_ROOT}/caches/tmp"
export TMP="${ML_ROOT}/caches/tmp"
export PYTHONNOUSERSITE=1
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.0}"
export TORCHDYNAMO_DISABLE="${TORCHDYNAMO_DISABLE:-1}"
# Offload T5 to CPU between encodes so Infinity AR has headroom on 16GB.
export INFINITY_OFFLOAD_T5="${INFINITY_OFFLOAD_T5:-1}"
export INFINITY_ROOT
export INFINITY_WEIGHTS="${WEIGHTS}"
export INFINITY_MODEL_PATH="${WEIGHTS}/infinity_2b_reg.pth"
export INFINITY_VAE_PATH="${WEIGHTS}/infinity_vae_d32reg.pth"
export INFINITY_T5_PATH="${WEIGHTS}/flan-t5-xl"
export PYTHONPATH="${INFINITY_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

mkdir -p \
  "${PIP_CACHE_DIR}" \
  "${HUGGINGFACE_HUB_CACHE}" \
  "${TORCH_HOME}" \
  "${TMPDIR}" \
  "${WEIGHTS}"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "ERROR: Infinity venv missing at ${VENV_PY}" >&2
  exit 1
fi
if [[ ! -d "${INFINITY_ROOT}" ]]; then
  echo "ERROR: Infinity clone missing at ${INFINITY_ROOT}" >&2
  exit 1
fi

cmd="${1:-help}"
shift || true

case "${cmd}" in
  env)
    echo "ML_ROOT=${ML_ROOT}"
    echo "INFINITY_ROOT=${INFINITY_ROOT}"
    echo "INFINITY_MODEL_PATH=${INFINITY_MODEL_PATH}"
    echo "HF_HOME=${HF_HOME}"
    "${VENV_PY}" - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    print("vram_gb", round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2))
PY
    ;;
  python)
    exec "${VENV_PY}" "$@"
    ;;
  pip)
    exec "${VENV_PY}" -m pip "$@"
    ;;
  smoke|infer|ab)
    cd "${REPO_ROOT}"
    exec "${VENV_PY}" "${REPO_ROOT}/tools/local_imagegen/infinity_sparse_invent/__main__.py" "${cmd}" "$@"
    ;;
  help|-h|--help)
    echo "Usage: $0 {env|python|pip|smoke|infer|ab} ..." >&2
    exit 0
    ;;
  *)
    echo "Usage: $0 {env|python|pip|smoke|infer|ab} ..." >&2
    exit 2
    ;;
esac
