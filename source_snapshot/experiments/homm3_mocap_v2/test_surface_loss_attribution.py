import sys
import unittest
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from surface_loss_attribution import attribute_surface


class SurfaceLossAttributionTests(unittest.TestCase):
    def test_concentrated_boundary_loss_reports_original_top_triangle(self):
        stretches = torch.ones((2, 100, 2), dtype=torch.float64)
        stretches[:, 37] = torch.tensor([2.0, 0.5], dtype=torch.float64)
        valid = torch.ones(100, dtype=torch.bool)
        areas = torch.arange(1, 101, dtype=torch.float64)
        result = attribute_surface(stretches, valid, areas)
        self.assertEqual(result["topTriangleIndices"], [37])
        self.assertAlmostEqual(result["topBoundaryContributionShare"], 1.0)
        self.assertAlmostEqual(result["perFrameBoundaryContributionFractions"][0], 1.0)
        self.assertGreater(result["countViolationFraction"], 0.0)
        self.assertGreater(result["areaWeightedViolationFraction"], 0.0)
        self.assertAlmostEqual(result["topRestAreaShare"], 38.0 / sum(range(1, 101)))

    def test_zero_boundary_violation_is_explicit_and_deterministic(self):
        result = attribute_surface(torch.ones((3, 101, 2)), torch.ones(101, dtype=torch.bool),
                                    torch.ones(101))
        self.assertEqual(result["topTriangleIndices"], [0, 1])
        self.assertEqual(result["topBoundaryContributionShare"], 0.0)
        self.assertEqual(result["perFrameBoundaryContributionFractions"], [0.0, 0.0, 0.0])
        self.assertEqual(result["countViolationFraction"], 0.0)
        self.assertEqual(result["areaWeightedViolationFraction"], 0.0)

    def test_invalid_shapes_values_and_valid_area_fail_closed(self):
        base = torch.ones((2, 3, 2))
        with self.assertRaises(ValueError):
            attribute_surface(base[..., :1], torch.ones(3, dtype=torch.bool), torch.ones(3))
        with self.assertRaises(ValueError):
            attribute_surface(base, torch.ones(3), torch.ones(3))
        with self.assertRaises(ValueError):
            attribute_surface(base, torch.ones(3, dtype=torch.bool), torch.tensor([1., 0., 1.]))
        bad = base.clone(); bad[0, 0, 0] = 0.
        with self.assertRaises(ValueError):
            attribute_surface(bad, torch.ones(3, dtype=torch.bool), torch.ones(3))
        with self.assertRaises(ValueError):
            attribute_surface(base, torch.tensor([True, False, False]), torch.tensor([0., 1., 1.]))

    def test_invalid_faces_may_be_nan_and_original_ids_are_preserved(self):
        values = torch.ones((1, 100, 2), dtype=torch.float64)
        values[:, 0, :] = float("nan")
        values[:, 1, :] = 0.0
        values[:, 10, :] = torch.tensor([2.0, 2.0])
        valid = torch.ones(100, dtype=torch.bool)
        valid[:2] = False
        areas = torch.ones(100, dtype=torch.float64)
        areas[:2] = 0.0
        result = attribute_surface(values, valid, areas)
        self.assertEqual(result["topTriangleIndices"], [10])
        self.assertEqual(result["validTriangleCount"], 98)

    def test_integer_stretches_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "floating"):
            attribute_surface(torch.ones((1, 2, 2), dtype=torch.int64),
                              torch.ones(2, dtype=torch.bool), torch.ones(2))

    def test_boundary_share_matches_independent_multiframe_formula(self):
        values = torch.tensor([
            [[1.6, 1.0], [2.0, .5], [1.0, 1.0]],
            [[1.7, 1.0], [1.8, .6], [1.0, 1.0]],
        ], dtype=torch.float64)
        valid = torch.ones(3, dtype=torch.bool)
        result = attribute_surface(values, valid, torch.tensor([1., 2., 3.], dtype=torch.float64))
        boundary = (torch.relu(values - 1.5).square() + torch.relu(.67 - values).square()).mean(-1)
        expected = float(boundary[:, 1].sum() / boundary.sum())
        self.assertEqual(result["topTriangleIndices"], [1])
        self.assertAlmostEqual(result["topBoundaryContributionShare"], expected)


if __name__ == "__main__":
    unittest.main()
