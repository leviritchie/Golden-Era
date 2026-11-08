"""Locate the commit-pinned nvdiffrast CUDA extension.

``setup_gpu_pose_v2.ps1`` installs NVLabs nvdiffrast into
``third_party/gpu_pose_v2`` rather than into the interpreter's site-packages.
Callers that only add this tool directory to ``sys.path`` will not see that
install until this helper prepends the vendor directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

LOCAL_NVDIFFRAST_DIR = Path(__file__).resolve().parent / "third_party" / "gpu_pose_v2"


def ensure_local_nvdiffrast(*, required: bool = False) -> Path | None:
    """Put the vendored CUDA extension on ``sys.path``.

    When ``required`` is true, a missing directory fails closed instead of
    letting a later ``import nvdiffrast`` look like a generic package error.
    """
    path = LOCAL_NVDIFFRAST_DIR
    if not path.is_dir():
        if required:
            raise FileNotFoundError(
                f"Local nvdiffrast directory is missing: {path}. "
                "Run setup_gpu_pose_v2.ps1, then restart the kernel."
            )
        return None
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    return path
