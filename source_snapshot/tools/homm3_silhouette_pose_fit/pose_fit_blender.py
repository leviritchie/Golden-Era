"""Resolve the Blender 3.5.1 executable used by pose-fit previews.

The GPU cascade still needs Blender for the final lit preview. Candidate
search is discovery of the installed binary, not a skip. A set-but-missing
``HOMM3_POSE_FIT_BLENDER`` path fails closed instead of walking the list.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_NAME = "HOMM3_POSE_FIT_BLENDER"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_DIR = Path(__file__).resolve().parent

DEFAULT_BLENDER_CANDIDATES: tuple[Path, ...] = (
    Path(r"V:/Tools/blender-3.5.1/blender.exe"),
    _TOOL_DIR / "blender-3.5.1" / "blender.exe",
    Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe"),
    Path(r"C:/Program Files/Blender Foundation/Blender 3.5/blender.exe"),
    Path(r"C:/Program Files/Blender Foundation/Blender 3.5.1/blender.exe"),
)


def resolve_pose_fit_blender(explicit: str | Path | None = None) -> Path:
    """Return the Blender 3.5.1 executable, or raise FileNotFoundError."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Blender executable is missing: {path}")
        return path.resolve()
    env = str(os.environ.get(ENV_NAME, "") or "").strip()
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"{ENV_NAME} is set but the Blender executable is missing: {path}"
            )
        return path.resolve()
    looked = []
    for candidate in DEFAULT_BLENDER_CANDIDATES:
        looked.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Blender 3.5.1 executable is missing. Install it or set "
        f"{ENV_NAME}. looked in: {', '.join(looked)}"
    )
