"""Focused source-selection, attribution and diagnostic-boundary checks."""
from pathlib import Path
import unittest

import numpy as np
import torch

from run_sprite_exception_pilot import face_error, topology_support, require_pose_parity
from tools.validate_homm3_attachment_pipeline_contract import validate_sprite_exception_source


class SpriteExceptionPilotTests(unittest.TestCase):
    def test_pose_parity_rejects_nonfinite_reconstruction(self):
        expected = torch.zeros(1, 2, 3)
        self.assertEqual(require_pose_parity(expected, expected), 0.)
        for value in (float("nan"), float("inf"), .01):
            with self.assertRaises(ValueError):
                require_pose_parity(torch.full_like(expected, value), expected)

    def test_support_expands_topologically_not_by_nearby_positions(self):
        triangles = np.array([[0, 1, 2], [2, 3, 4], [4, 5, 6], [7, 8, 9]])
        self.assertEqual(topology_support(triangles, [0], 0), [0, 1, 2])
        self.assertEqual(topology_support(triangles, [0], 1), [0, 1, 2, 3, 4])
        self.assertEqual(topology_support(triangles, [0], 2), list(range(7)))
        self.assertEqual(topology_support(triangles, [], 4), [])

    def test_visible_residual_is_mean_and_unowned_source_stays_unassigned(self):
        buffers = {"rgb": torch.zeros(1, 1, 4, 3),
                   "alpha": torch.tensor([[[[1.], [1.], [1.], [0.]]]]),
                   "triangleId": torch.tensor([[[0, 0, 1, -1]]])}
        error, coverage = face_error(buffers, torch.zeros(1, 1, 4, 3),
                                     torch.tensor([[[[0.], [0.], [0.], [1.]]]]), 3)
        np.testing.assert_array_equal(error, [[1., 1., 0.]])
        np.testing.assert_array_equal(coverage, [[2., 1., 0.]])

    def test_build_guard_rejects_lost_visibility_or_delivery_claim(self):
        source = Path(__file__).with_name("run_sprite_exception_pilot.py").read_text(encoding="utf-8")
        self.assertTrue(validate_sprite_exception_source(source)["explicitSpriteExceptionDiagnostic"])
        for old, new in (("candidate_visible_face_coverage=np.array(trial_coverage)", "removed_coverage=np.array(trial_coverage)"),
                         ('"accepted": False', '"accepted": True'),
                         ('"runtimeExportAvailable": False', '"runtimeExportAvailable": True'),
                         ("detect_conflicts(", "removed_detection(")):
            with self.assertRaises(ValueError):
                validate_sprite_exception_source(source.replace(old, new))


if __name__ == "__main__":
    unittest.main()
