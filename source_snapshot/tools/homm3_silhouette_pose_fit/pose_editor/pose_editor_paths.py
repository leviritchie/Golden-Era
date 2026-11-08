"""Write/read gates for the sprite pose editor.

The editor may read experiment meshes, poses, cameras, and sprite plates.
It may only write under artifacts/sprite_feasibility/**/manual_edit/.
It never writes live fused-push or Meshy downloads.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK_TREE = ROOT / "artifacts" / "sprite_feasibility"
SPRITE_TREE = ROOT / "artifacts" / "pose_picker_runs"
ANATOMY_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})
MANUAL_EDIT_DIRNAME = "manual_edit"


def _resolved(path: str | Path) -> Path:
    return Path(path).resolve()


def assert_under(path: Path, root: Path) -> Path:
    resolved = _resolved(path)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{resolved} is not under {root}") from exc
    return resolved


def assert_read_path(path: str | Path) -> Path:
    resolved = _resolved(path)
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise ValueError(f"pose editor may not read forbidden path {resolved}")
    allowed_roots = (WORK_TREE.resolve(), SPRITE_TREE.resolve(), ANATOMY_DIR.resolve())
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"pose editor may not read {resolved}")


def assert_write_path(path: str | Path) -> Path:
    resolved = _resolved(path)
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise ValueError(f"pose editor may not write forbidden path {resolved}")
    rel = assert_under(resolved, WORK_TREE)
    if MANUAL_EDIT_DIRNAME not in rel.parts:
        raise ValueError(f"pose editor may only write under {MANUAL_EDIT_DIRNAME}/; got {resolved}")
    return resolved


def work_clip_dir(unit: str, clip: str) -> Path:
    sid = str(unit).strip()
    name = str(clip).strip()
    if not sid or not name or "/" in sid or "\\" in sid or "/" in name or "\\" in name:
        raise ValueError("unit and clip must be single path names")
    return assert_under(WORK_TREE / sid / name, WORK_TREE)


def manual_edit_dir(unit: str, clip: str) -> Path:
    return assert_write_path(work_clip_dir(unit, clip) / MANUAL_EDIT_DIRNAME / "current")
