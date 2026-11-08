import json
import tempfile
import unittest
from pathlib import Path

from .oe_lighting_style import redistribute_energy, soften_solution


class SoftLightingTests(unittest.TestCase):
    def test_preserves_colour_and_rebalances_strengths(self):
        src = {"keyLight": {"colorLinear": [1, .8, .6], "strength": 2},
               "floodLight": {"colorLinear": [.5, .6, 1], "strength": 1}}
        out = soften_solution(src)
        self.assertEqual(out["keyLight"]["colorLinear"], src["keyLight"]["colorLinear"])
        self.assertAlmostEqual(out["keyLight"]["strength"], 1.3)
        self.assertAlmostEqual(out["floodLight"]["strength"], 1.35)
        self.assertNotIn("oeStyle", src)

    def test_bad_scales_fail_closed(self):
        src = {"keyLight": {"strength": 1}, "floodLight": {"strength": 1}}
        with self.assertRaises(ValueError):
            soften_solution(src, key_scale=0)
        with self.assertRaises(ValueError):
            soften_solution(src, flood_scale=.9)

    def test_nonfinite_source_strength_fails_closed(self):
        src = {"keyLight": {"strength": float("nan")}, "floodLight": {"strength": 1}}
        with self.assertRaises(ValueError):
            soften_solution(src)

    def test_energy_redistribution_conserves_requested_scalar(self):
        src = {"keyLight": {"colorLinear": [1, 0.5, 0.25], "strength": 10},
               "floodLight": {"colorLinear": [1, 1, 1], "strength": 1}}
        out = redistribute_energy(src, key_scale=.6, fill_fraction=.25)
        self.assertAlmostEqual(out["keyLight"]["strength"], 6.0)
        self.assertAlmostEqual(max(out["floodLight"]["colorLinear"]) * out["floodLight"]["strength"], 2.0)
        self.assertEqual(out["oeStyle"]["profile"], "energy-redistributed")


if __name__ == "__main__":
    unittest.main()
