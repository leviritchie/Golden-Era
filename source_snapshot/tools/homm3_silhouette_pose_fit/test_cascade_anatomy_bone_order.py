#!/usr/bin/env python3
"""Fail-closed checks for LLM anatomy → cascade bone order expansion."""
from __future__ import annotations

import unittest
from pathlib import Path

from cascade_anatomy_bone_order import (
    cascade_kwargs_from_anatomy_order,
    expand_anatomy_order,
)


TOOL = Path(__file__).resolve().parent


class AnatomyBoneOrderTests(unittest.TestCase):
    def test_roc_start_move_end_expands_dependency_within_groups(self) -> None:
        groups = {
            "groups": {
                "wing_a": {"bonesDependencyOrder": ["Bone_019", "Bone_018"]},
                "trunk": {"bonesDependencyOrder": ["Bone_000", "Bone_001"]},
            }
        }
        authored = {
            "groupVisitOrder": ["wing_a", "trunk"],
            "rotationScaleByGroup": {"wing_a": 1.0, "trunk": 0.5},
            "rationale": "test",
            "method": "llm_anatomy_priority_for_clip",
        }
        expanded = expand_anatomy_order(groups_catalog=groups, authored=authored)
        self.assertEqual(
            expanded["search_bones"],
            ("Bone_019", "Bone_018", "Bone_000", "Bone_001"),
        )
        self.assertEqual(
            expanded["bone_limit_scale_overrides"],
            (
                ("Bone_019", 1.0),
                ("Bone_018", 1.0),
                ("Bone_000", 0.5),
                ("Bone_001", 0.5),
            ),
        )
        kwargs = cascade_kwargs_from_anatomy_order(expanded)
        self.assertFalse(kwargs["include_unlisted_search_bones"])
        self.assertEqual(kwargs["search_bones"], expanded["search_bones"])

    def test_missing_group_fails_closed(self) -> None:
        groups = {"groups": {"wing_a": {"bonesDependencyOrder": ["Bone_019"]}}}
        authored = {
            "groupVisitOrder": ["wing_a", "trunk"],
            "rotationScaleByGroup": {"wing_a": 1.0, "trunk": 0.5},
        }
        with self.assertRaisesRegex(ValueError, "groupVisitOrder names missing from catalog"):
            expand_anatomy_order(groups_catalog=groups, authored=authored)

    def test_repo_roc_authored_files_round_trip(self) -> None:
        from cascade_anatomy_bone_order import expand_anatomy_order_paths

        expanded = expand_anatomy_order_paths(
            groups_path=TOOL / "roc_smartrig_anatomy_groups.json",
            authored_path=TOOL / "llm_authored/roc_start_move_end_anatomy_order.json",
        )
        self.assertEqual(len(expanded["search_bones"]), 23)
        self.assertEqual(expanded["groupVisitOrder"][0], "wing_a")
        self.assertEqual(expanded["groupVisitOrder"][1], "wing_b")


if __name__ == "__main__":
    unittest.main()
