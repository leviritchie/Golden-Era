#!/usr/bin/env python3
"""Pose editor may only write under artifacts/sprite_feasibility/**/manual_edit/."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
EDITOR = FIT / "pose_editor"

REQUIRED_NEEDLES = (
    "assert_write_path",
    "manual_edit",
    "neverMasterGlb",
    "poseUnits",
    "h3_roc",
    "idle_start_move_end",
    "fused_push_v24_pipeline",
    "meshy_downloads",
    "enforceSymmetry",
    "resetIdlePose",
    "idleReferenceFrame",
    "copyAnatomicalDelta",
    "restWorldQuat",
)


def main() -> None:
    server = (EDITOR / "server.py").read_text(encoding="utf-8")
    paths = (EDITOR / "pose_editor_paths.py").read_text(encoding="utf-8")
    ui = (EDITOR / "static" / "app.js").read_text(encoding="utf-8")
    html = (EDITOR / "static" / "index.html").read_text(encoding="utf-8")
    blob = "\n".join((server, paths, ui, html))
    for needle in REQUIRED_NEEDLES:
        if needle not in blob:
            raise SystemExit(f"FAIL validate_sprite_pose_editor_contract: missing {needle}")
    tree = ast.parse(server)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in {"write_text", "write_bytes"}:
            continue
        # Writes must go through _json_dump / assert_write_path in this file.
        if "assert_write_path" not in server:
            raise SystemExit("FAIL validate_sprite_pose_editor_contract: writes without assert_write_path")
    print("PASS validate_sprite_pose_editor_contract")


if __name__ == "__main__":
    main()
