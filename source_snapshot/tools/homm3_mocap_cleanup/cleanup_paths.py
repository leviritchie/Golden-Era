"""Allowlisted read/write paths for the mocap bind lab."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MOCAP_V2 = REPO / "experiments" / "homm3_mocap_v2"
LEDGER = REPO / "artifacts" / "homm3_mocap_v2" / "full_set_mocap_idle0_v1"
RUNS = LEDGER / "runs"
EDITS = REPO / "artifacts" / "homm3_mocap_v2" / "cleanup_edits"
STATIC = Path(__file__).resolve().parent / "static"


def assert_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"{resolved} is outside {root_resolved}")
    return resolved


def assert_read_path(path: Path) -> Path:
    resolved = path.resolve()
    for root in (RUNS, EDITS, STATIC):
        try:
            return assert_under(resolved, root)
        except ValueError:
            continue
    raise ValueError(f"refusing to read {resolved}")


def assert_write_path(path: Path) -> Path:
    return assert_under(path, EDITS)
