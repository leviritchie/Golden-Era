"""Fail-closed write/read gates for the sprite pose editor."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"

import sys

sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "pose_editor"))

from pose_editor_paths import (  # noqa: E402
    FORBIDDEN_WRITE_PARTS,
    MANUAL_EDIT_DIRNAME,
    WORK_TREE,
    assert_read_path,
    assert_write_path,
    manual_edit_dir,
)


class PoseEditorPathTests(unittest.TestCase):
    def test_write_only_under_manual_edit(self) -> None:
        dest = WORK_TREE / "h3_roc" / "idle_start_move_end" / MANUAL_EDIT_DIRNAME / "current" / "after_poses.json"
        self.assertEqual(assert_write_path(dest), dest.resolve())
        with self.assertRaises(ValueError):
            assert_write_path(WORK_TREE / "h3_roc" / "idle_start_move_end" / "round_12" / "after_poses.json")

    def test_forbids_meshy_and_fused_push(self) -> None:
        self.assertIn("meshy_downloads", FORBIDDEN_WRITE_PARTS)
        self.assertIn("fused_push_v24_pipeline", FORBIDDEN_WRITE_PARTS)
        with self.assertRaises(ValueError):
            assert_write_path(
                ROOT / "artifacts" / "meshy_downloads" / MANUAL_EDIT_DIRNAME / "x.json"
            )

    def test_manual_edit_dir_is_under_work_tree(self) -> None:
        path = manual_edit_dir("h3_roc", "idle_start_move_end")
        self.assertEqual(path.name, "current")
        self.assertIn(MANUAL_EDIT_DIRNAME, path.parts)

    def test_rejects_path_injection(self) -> None:
        with self.assertRaises(ValueError):
            manual_edit_dir("h3_roc/../x", "idle_start_move_end")


class PoseEditorServerSourceTests(unittest.TestCase):
    def test_server_does_not_write_forbidden_trees(self) -> None:
        text = (FIT / "pose_editor" / "server.py").read_text(encoding="utf-8")
        self.assertIn("assert_write_path", text)
        self.assertIn("neverMasterGlb", text)
        self.assertIn("poseUnits", text)
        tree = ast.parse(text)
        writes: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in {"write_text", "write_bytes", "copy2"}:
                    writes.append(name)
                self.generic_visit(node)

        Visitor().visit(tree)
        self.assertTrue(writes)


class PoseEditorUiSourceTests(unittest.TestCase):
    def test_click_drag_and_original_sprite_plate(self) -> None:
        html = (FIT / "pose_editor" / "static" / "index.html").read_text(encoding="utf-8")
        js = (FIT / "pose_editor" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="spritePlate"', html)
        self.assertIn('class="plate"', html)
        self.assertIn("Raycaster", js)
        self.assertIn("armPick", js)
        self.assertIn("syncSliderReadouts", js)
        self.assertIn("pointerdown", js)
        self.assertIn('id="hits"', html)
        self.assertIn('id="meshPreviewBtn"', html)
        self.assertIn("zoomAtEvent", js)
        self.assertIn("meshPreviewOn", js)
        self.assertIn("copyAnatomicalDelta", js)
        self.assertIn("anatomicalAxes", js)
        self.assertIn("restWorldQuat", js)
        self.assertIn("modelFrameOrNull", js)
        self.assertIn("enforceSymmetry", js)
        self.assertIn("resetFrameToIdle", js)
        self.assertIn("idleReferenceFrame", js)
        self.assertIn('id="enforceSymmetry"', html)
        self.assertIn('id="resetIdlePose"', html)
        self.assertIn('id="symmetryMode"', html)


if __name__ == "__main__":
    unittest.main()
