"""Unit config "skipDefGroups" (skip_def_groups.py): parsing fails closed, and the clip map matches the OE contract."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "homm3_silhouette_pose_fit"))
import skip_def_groups as S  # noqa: E402


class SkipDefGroupsTest(unittest.TestCase):
    def test_absent_is_empty(self):
        self.assertEqual(S.parse({"unit": "u"}), {})

    def test_shoot_group_with_reason(self):
        self.assertEqual(S.parse({"unit": "u", "skipDefGroups": {"15": " never shoots "}}), {15: "never shoots"})

    def test_fails_closed(self):
        for bad in ({}, [], {"12": "melee"}, {"15": ""}, {"15": None}, {"x": "r"}, {15: "int key"}):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                S.parse({"unit": "u", "skipDefGroups": bad})

    def test_clip_map_matches_the_contract(self):
        from gpu_cascade_delivery import CONTRACT_SUFFIX_BY_GROUP, SKIPPED_DEF_GROUPS
        for g, clip in S.SHOOT_CLIP_BY_GROUP.items():
            if clip is None:
                self.assertIn(g, SKIPPED_DEF_GROUPS)
            else:
                self.assertEqual(clip, "Unit_" + CONTRACT_SUFFIX_BY_GROUP[g])

    def test_unit_of_blend_actions(self):
        self.assertEqual(S.unit_of_blend_actions(["Unit_Idle", "h3_x_DEF_Master"]), "h3_x")
        for names in (["Unit_Idle"], ["a_DEF_Master", "b_DEF_Master"]):
            with self.assertRaises(SystemExit):
                S.unit_of_blend_actions(names)

    def test_every_unit_config_parses(self):
        for p in sorted(S.UNITS.glob("*.json")):
            S.for_unit(p.stem)


if __name__ == "__main__":
    unittest.main()
