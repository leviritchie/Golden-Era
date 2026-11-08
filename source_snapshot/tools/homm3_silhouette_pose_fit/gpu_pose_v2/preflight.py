"""Fail-closed environment checks for the V2 notebook."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

_TOOL_DIR = Path(__file__).resolve().parent.parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))
from nvdiffrast_local import ensure_local_nvdiffrast
from pose_fit_blender import resolve_pose_fit_blender


def ensure_huggingface_auth() -> bool:
    """Load the user-scoped Hugging Face token into this process if needed.

    The original single-joint notebook performs this bridge before loading the
    gated DINOv3 checkpoint.  V2 is also expected to work after a fresh kernel
    start, where a Windows user environment variable is not automatically
    present in ``os.environ`` for an already-running Jupyter process.  The
    token value is never returned, logged, serialized, or included in a
    report.
    """

    if os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"):
        return True
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "HF_TOKEN")
    except (FileNotFoundError, OSError):
        return False
    if not value:
        return False
    os.environ["HF_TOKEN"] = str(value)
    return True


def _model_requires_auth(model_id: str) -> bool:
    """Return whether the configured remote checkpoint is normally gated."""

    value = str(model_id).strip().lower()
    return value.startswith("facebook/") and "dino" in value


def _model_cache_report(model_ids: tuple[str, ...]) -> dict[str, Any]:
    roots: list[Path] = []
    for key in ("HF_HUB_CACHE", "TRANSFORMERS_CACHE"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value).expanduser())
    home = os.environ.get("HF_HOME")
    if home:
        roots.append(Path(home).expanduser() / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    unique_roots = tuple(dict.fromkeys(path.resolve() for path in roots))
    models = []
    for model_id in model_ids:
        local = Path(model_id).expanduser()
        cached_locations = [str(local.resolve())] if local.is_dir() else [
            str(root / ("models--" + str(model_id).replace("/", "--")))
            for root in unique_roots
            if (root / ("models--" + str(model_id).replace("/", "--"))).is_dir()
        ]
        models.append({"id": str(model_id), "cached": bool(cached_locations), "locations": cached_locations})
    return {
        "roots": [str(root) for root in unique_roots],
        "models": models,
        "allRequestedCached": all(value["cached"] for value in models) if models else None,
    }


def preflight(
    *,
    require_renderer: bool = True,
    require_semantics: bool = False,
    model_ids: tuple[str, ...] = (),
    local_files_only_model_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    import torch

    hf_token_present = ensure_huggingface_auth()
    ensure_local_nvdiffrast(required=False)
    nvdiffrast_version = None
    if importlib.util.find_spec("nvdiffrast"):
        try:
            import nvdiffrast

            nvdiffrast_version = getattr(nvdiffrast, "__version__", "installed")
        except Exception as exc:
            nvdiffrast_version = f"import-error:{type(exc).__name__}"
    report: dict[str, Any] = {
        "python": os.sys.version.split()[0],
        "torch": getattr(torch, "__version__", "unknown"),
        "torchCuda": getattr(torch.version, "cuda", None),
        "cudaAvailable": bool(torch.cuda.is_available()),
        "nvdiffrast": bool(importlib.util.find_spec("nvdiffrast")),
        "nvdiffrastVersion": nvdiffrast_version,
        "transformers": bool(importlib.util.find_spec("transformers")),
        "blender": True,
        "blenderPath": str(resolve_pose_fit_blender()),
        "huggingfaceTokenPresent": hf_token_present,
        "modelCache": _model_cache_report(tuple(str(value) for value in model_ids)),
    }
    if report["cudaAvailable"]:
        report["gpu"] = torch.cuda.get_device_name(0)
        report["vramGiB"] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
    if not report["cudaAvailable"]:
        raise RuntimeError({"ok": False, "error": "V2 requires CUDA", "report": report})
    if require_renderer and not report["nvdiffrast"]:
        raise RuntimeError({"ok": False, "error": "nvdiffrast is not installed; V2 has no soft-renderer fallback", "report": report})
    if require_semantics and not report["transformers"]:
        raise RuntimeError({"ok": False, "error": "transformers is required for semantic finalist scoring", "report": report})
    if require_semantics and model_ids and not report["modelCache"]["allRequestedCached"]:
        raise RuntimeError({"ok": False, "error": "one or more configured vision models are not cached", "report": report})
    local_only_ids = {str(value) for value in local_files_only_model_ids}
    gated_remote_models = [
        str(model_id)
        for model_id in model_ids
        if (
            _model_requires_auth(str(model_id))
            and str(model_id) not in local_only_ids
            and not Path(str(model_id)).expanduser().is_dir()
        )
    ]
    if require_semantics and gated_remote_models and not hf_token_present:
        raise RuntimeError(
            {
                "ok": False,
                "error": (
                    "a configured gated vision model has no HF_TOKEN in this kernel; "
                    "restart the kernel after setting the Windows user environment variable"
                ),
                "models": gated_remote_models,
                "report": report,
            }
        )
    report["ok"] = True
    return report
