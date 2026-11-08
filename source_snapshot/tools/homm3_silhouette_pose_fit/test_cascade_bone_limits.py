"""Per-bone limit scales: named override replaces the depth rule, typos raise."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cascade_bone_limits import (
    resolve_bone_limit_scales,
    validate_bone_limit_scale_overrides,
)

NAMES = ("Armature", "Bone_000", "Bone_001", "Bone_012", "Bone_024")
DEPTHS = (0, 1, 2, 3, 6)


class ValidateOverrideTests(unittest.TestCase):
    def test_accepts_pairs_mapping_and_json_round_trip(self) -> None:
        expected = (("Bone_012", 0.3), ("Bone_024", 1.0))
        self.assertEqual(validate_bone_limit_scale_overrides(expected), expected)
        self.assertEqual(
            validate_bone_limit_scale_overrides({"Bone_012": 0.3, "Bone_024": 1.0}),
            expected,
        )
        self.assertEqual(
            validate_bone_limit_scale_overrides([["Bone_012", 0.3], ["Bone_024", 1.0]]),
            expected,
        )

    def test_empty_and_none_are_no_override(self) -> None:
        self.assertEqual(validate_bone_limit_scale_overrides(None), ())
        self.assertEqual(validate_bone_limit_scale_overrides(()), ())

    def test_rejects_out_of_range_scale(self) -> None:
        for bad in (0.0, -0.5, 1.5, float("nan")):
            with self.assertRaises(ValueError):
                validate_bone_limit_scale_overrides((("Bone_012", bad),))

    def test_rejects_duplicate_bone(self) -> None:
        with self.assertRaises(ValueError):
            validate_bone_limit_scale_overrides((("Bone_012", 0.3), ("Bone_012", 0.5)))

    def test_rejects_malformed_entry(self) -> None:
        for bad in ("Bone_012", ("Bone_012",), ("Bone_012", 0.3, 0.4), ((), 0.3)):
            with self.assertRaises(ValueError):
                validate_bone_limit_scale_overrides((bad,))


class ResolveScaleTests(unittest.TestCase):
    def test_depth_rule_only(self) -> None:
        scales = resolve_bone_limit_scales(
            node_names=NAMES,
            node_depths=DEPTHS,
            proximal_depth=2,
            proximal_scale=0.35,
        )
        # Depth 0 is the armature root and is never shrunk by the depth rule.
        self.assertEqual(scales, (1.0, 0.35, 0.35, 1.0, 1.0))

    def test_override_replaces_depth_rule_without_multiplying(self) -> None:
        scales = resolve_bone_limit_scales(
            node_names=NAMES,
            node_depths=DEPTHS,
            proximal_depth=2,
            proximal_scale=0.35,
            overrides=(("Bone_001", 0.5), ("Bone_012", 0.3)),
        )
        self.assertEqual(scales, (1.0, 0.35, 0.5, 0.3, 1.0))

    def test_unknown_bone_name_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            resolve_bone_limit_scales(
                node_names=NAMES,
                node_depths=DEPTHS,
                proximal_depth=2,
                proximal_scale=1.0,
                overrides=(("Bone_999", 0.3),),
            )
        self.assertIn("Bone_999", str(caught.exception))

    def test_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_bone_limit_scales(
                node_names=NAMES,
                node_depths=DEPTHS[:-1],
                proximal_depth=2,
                proximal_scale=1.0,
            )


if __name__ == "__main__":
    unittest.main()
