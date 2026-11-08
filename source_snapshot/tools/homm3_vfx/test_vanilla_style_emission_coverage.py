"""Focused test: a glowing emissionMap row whose compiled mask covers nothing is refused; the black no-glow placeholder
is not (vanilla_style_fx.emission_glow_error, enforced by ``compile`` and ``check``).

    python tools/homm3_vfx/test_vanilla_style_emission_coverage.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vanilla_style_fx as vs  # noqa: E402

BLACK = {"color": [0.0, 0.0, 0.0], "minPower": 0.0, "blinkPower": 0.0, "blinkSpeed": 0.0}
GLOW = {"color": [1.6, 0.8, 0.35], "minPower": 0.4, "blinkPower": 0.25, "blinkSpeed": 1.0}


class EmissionGlowCoverage(unittest.TestCase):
    def test_black_placeholder_with_empty_mask_passes(self):
        self.assertIsNone(vs.emission_glow_error("u", "body_emission", BLACK, {"coverage": 0.0, "meanMask": 0.0}))

    def test_glow_with_covered_mask_passes(self):
        self.assertIsNone(vs.emission_glow_error("u", "body_emission", GLOW, {"coverage": 0.14, "meanMask": 0.02}))

    def test_glow_with_empty_mask_fails(self):
        err = vs.emission_glow_error("u", "body_emission", GLOW, {"coverage": 0.0, "meanMask": 0.0})
        self.assertIsNotNone(err)
        self.assertIn("lights nothing", err)

    def test_any_single_glow_term_counts(self):
        for layer in ({**BLACK, "color": [0.0, 0.0, 0.5]}, {**BLACK, "minPower": 0.1}, {**BLACK, "blinkPower": 0.1}):
            self.assertIsNotNone(vs.emission_glow_error("u", "e", layer, {"coverage": 0.0}), layer)

    def test_missing_coverage_is_empty(self):
        self.assertIsNotNone(vs.emission_glow_error("u", "e", GLOW, {}))


if __name__ == "__main__":
    unittest.main()
