"""CPU contract tests for corrective-objective gradient attribution."""
import math
import sys
import unittest
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from audit_corrective_gradient import _stats, _feature_energy
import numpy as np


class CorrectiveGradientTests(unittest.TestCase):
    def test_stats_reports_weighted_norms_and_descent_sign(self) -> None:
        first = torch.tensor([1.0, 2.0], requires_grad=True)
        second = torch.tensor([3.0, 4.0], requires_grad=True)
        controls = (first, second)

        image = 2.0 * first[0] + 3.0 * first[1] + second[0] - 2.0 * second[1]
        geometry = -first[0] + 4.0 * first[1] + 2.0 * second[0] + second[1]
        stats = _stats({"image": image, "geometry": geometry}, controls)

        image_gradient = (2.0, 3.0, 1.0, -2.0)
        geometry_gradient = (-1.0, 4.0, 2.0, 1.0)
        total_gradient = (1.0, 7.0, 3.0, -1.0)
        image_norm = math.sqrt(sum(value * value for value in image_gradient))
        geometry_norm = math.sqrt(sum(value * value for value in geometry_gradient))
        total_norm = math.sqrt(sum(value * value for value in total_gradient))
        cosine = sum(a * b for a, b in zip(image_gradient, geometry_gradient)) / (image_norm * geometry_norm)
        image_total_dot = sum(a * b for a, b in zip(image_gradient, total_gradient))

        self.assertAlmostEqual(stats["norms"]["image"], image_norm, delta=1e-6)
        self.assertAlmostEqual(stats["norms"]["geometry"], geometry_norm, delta=1e-6)
        self.assertAlmostEqual(stats["totalNorm"], total_norm, delta=1e-6)
        self.assertAlmostEqual(stats["pairwiseCosine"]["image:geometry"], cosine, delta=1e-6)
        self.assertAlmostEqual(stats["imageTotalDot"], image_total_dot, delta=1e-6)
        self.assertAlmostEqual(stats["imageDescentAlignment"], -image_total_dot / (image_norm * total_norm), delta=1e-6)


    def test_zero_gradient_pairwise_cosine_is_undefined(self) -> None:
        first = torch.tensor([1.0, 2.0], requires_grad=True)
        second = torch.tensor([3.0, 4.0], requires_grad=True)
        controls = (first, second)
        zero = (first * 0.0).sum() + (second * 0.0).sum()
        geometry = first[0] + (second * 0.0).sum()

        stats = _stats({"image": zero, "geometry": geometry}, controls)

        self.assertAlmostEqual(stats["norms"]["image"], 0.0)
        self.assertIsNone(stats["pairwiseCosine"]["image:geometry"])


    def test_disconnected_term_control_fails_closed(self) -> None:
        first = torch.tensor([1.0, 2.0], requires_grad=True)
        second = torch.tensor([3.0, 4.0], requires_grad=True)

        with self.assertRaisesRegex((RuntimeError, ValueError), "(?i)(disconnect|gradient|control|depend|not.*used)"):
            _stats({"image": first.sum(), "geometry": second.sum()}, (first, second))

    def test_feature_energy_uses_projection_and_joint_residual(self):
        neutral = np.zeros((2, 3, 3))
        local = np.zeros((2, 2, 3, 3))
        local[:, 0, 0, 0] = 3
        local[:, 1, 0, 0] = 4
        basis = np.zeros((18, 1))
        basis[0, 0] = 1
        result = _feature_energy(local, neutral, basis, ['first', 'second'],
                                 {'all': slice(None), 'one': [0]})
        self.assertEqual(result['all']['fullEnergy'], 50)
        self.assertEqual(result['all']['retainedEnergy'], 18)
        self.assertAlmostEqual(result['all']['retainedFraction'], .36)
        self.assertEqual(result['all']['largestResidualJoints'][0],
                         {'name': 'second', 'energy': 32})
        self.assertEqual(result['one']['fullEnergy'], 25)
