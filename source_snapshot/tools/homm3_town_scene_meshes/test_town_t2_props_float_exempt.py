"""Unit tests: town_t2_props FLOAT_EXEMPT_APPROVED (scoped floating-rule exemption; finish lane 2026-10-02,
Stronghold's ridge-top butte). Only the named (town, prop) at the pinned base, only the elevation term, only at the
pinned minElevationDeg."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_t2_props as PR  # noqa: E402

BUTTE = {"prop": "butte", "base": [154.4405019561339, 31.353055312627824, 152.96523090446505], "yaw": 305.89,
         "height": 31.72}


class FloatExempt(unittest.TestCase):
    def test_table_is_exactly_the_approved_butte(self):
        self.assertEqual(set(PR.FLOAT_EXEMPT_APPROVED), {("stronghold", "butte")})

    def test_match_needs_town_prop_and_pinned_base(self):
        self.assertIsNotNone(PR.float_exempt("stronghold", BUTTE))
        self.assertIsNone(PR.float_exempt("cove", BUTTE))
        self.assertIsNone(PR.float_exempt("stronghold", {**BUTTE, "prop": "cones"}))
        moved = {**BUTTE, "base": [BUTTE["base"][0] + 0.5, BUTTE["base"][1], BUTTE["base"][2]]}
        self.assertIsNone(PR.float_exempt("stronghold", moved))

    def test_only_the_elevation_term_at_the_pinned_value(self):
        inst = [BUTTE, {**BUTTE, "prop": "cones"}]
        fl = {0: {"minElevationDeg": -8.39}, 1: {"minElevationDeg": -8.39}}
        got = PR.apply_float_exempt("stronghold", fl, inst)
        self.assertEqual(list(got), [0])
        self.assertEqual(list(fl), [1])               # the cones stays floating
        for f in ({"minElevationDeg": -9.5}, {"minElevationDeg": -8.39, "sweep_right": 0.8}, {"sweep_left": 0.7}):
            fl = {0: dict(f)}
            self.assertEqual(PR.apply_float_exempt("stronghold", fl, [BUTTE]), {})
            self.assertEqual(list(fl), [0])


if __name__ == "__main__":
    unittest.main()
