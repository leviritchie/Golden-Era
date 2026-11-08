import sys
import unittest
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pose_corrective_field import PoseCorrectiveField


class PoseCorrectiveFieldTests(unittest.TestCase):
    def _rot(self, axis, angle):
        axis = np.asarray(axis, dtype=float)
        axis /= np.linalg.norm(axis)
        x, y, z = axis
        c, s, v = np.cos(angle), np.sin(angle), 1.0 - np.cos(angle)
        return np.array([[c + x*x*v, x*y*v-z*s, x*z*v+y*s],
                         [y*x*v+z*s, c+y*y*v, y*z*v-x*s],
                         [z*x*v-y*s, z*y*v+x*s, c+z*z*v]])

    def _fixture(self):
        vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                             [0., 0., 1.], [0., 0., 0.], [1., 1., 1.]], dtype=np.float32)
        regions = np.array(["frozen", "body", "wing", "body", "frozen", "wing"])
        neutral = np.repeat(np.eye(3)[None], 2, axis=0)
        poses = []
        specs = [((1, 0, 0), .3, ((0, 1, 0), .1)),
                 ((0, 1, 0), .4, ((0, 0, 1), -.2)),
                 ((0, 0, 1), .5, ((1, 1, 0), .25)),
                 ((1, 1, 1), .35, ((1, 0, 1), -.3)),
                 ((1, 0, 1), .6, ((0, 1, 1), .45))]
        for a1, t1, (a2, t2) in specs:
            pose = neutral.copy()
            pose[0] = self._rot(a1, t1)
            pose[1] = self._rot(a2, t2)
            poses.append(pose)
        return vertices, regions, np.stack(poses), neutral

    def _field(self):
        vertices, regions, train, neutral = self._fixture()
        return PoseCorrectiveField(vertices, regions, train, neutral,
                                   frozen_regions=["frozen"], max_displacement_fraction=.10,
                                   grid_resolution=4), vertices, regions, train, neutral

    def test_neutral_is_exact_zero_even_after_modes_are_controlled(self):
        field, _, _, _, neutral = self._field()
        with torch.no_grad():
            for mode in field.modes:
                mode.control.copy_(torch.randn_like(mode.control) * 3.)
        delta = field.displacement(neutral[None])
        self.assertEqual(float(delta.detach().abs().max()), 0.0)

    def test_frozen_regions_and_duplicate_positions_are_preserved(self):
        field, vertices, _, train, neutral = self._field()
        with torch.no_grad():
            for mode in field.modes:
                mode.control.copy_(torch.ones_like(mode.control) * .8)
        delta = field.displacement(train[1:2])[0].detach().numpy()
        np.testing.assert_array_equal(delta[[0, 4]], 0.0)
        np.testing.assert_allclose(delta[0], delta[4], atol=0, rtol=0)
        self.assertGreater(float(np.linalg.norm(delta[1])), 0.0)

    def test_combined_displacement_respects_overall_bound(self):
        field, vertices, _, train, _ = self._field()
        with torch.no_grad():
            for index, mode in enumerate(field.modes):
                mode.control.copy_(torch.full_like(mode.control, 20.0 * (-1 if index % 2 else 1)))
        delta = field.displacement(train).detach().numpy()
        diag = np.linalg.norm(vertices.max(0) - vertices.min(0))
        self.assertLessEqual(np.linalg.norm(delta, axis=-1).max(), .10 * diag + 1e-6)

    def test_nonzero_control_has_finite_pose_gradient_and_equal_pose_is_deterministic(self):
        field, _, _, _, neutral = self._field()
        with torch.no_grad():
            for mode in field.modes:
                mode.control.normal_(0., .2)
        pose = torch.tensor(self._fixture()[2][1], dtype=torch.float32, requires_grad=True)
        batch = torch.stack((pose, pose), dim=0)
        delta = field.displacement(batch)
        np.testing.assert_allclose(delta[0].detach().numpy(), delta[1].detach().numpy(), atol=0, rtol=0)
        delta.square().sum().backward()
        self.assertTrue(torch.isfinite(pose.grad).all())
        self.assertGreater(float(pose.grad.abs().sum()), 0.0)
        control_grad = sum(float(mode.control.grad.abs().sum()) for mode in field.modes)
        self.assertGreater(control_grad, 0.0)

    def test_repeating_training_set_preserves_coefficient_magnitudes(self):
        vertices, regions, train, neutral = self._fixture()
        original = PoseCorrectiveField(vertices, regions, train, neutral, grid_resolution=4)
        repeated = PoseCorrectiveField(vertices, regions, np.concatenate((train, train), axis=0), neutral,
                                       grid_resolution=4)
        query = train[[1, 3, 4]]
        first = original.coefficients(query).detach().numpy()
        second = repeated.coefficients(query).detach().numpy()
        np.testing.assert_allclose(np.abs(first), np.abs(second), atol=2e-5, rtol=2e-5)

    def test_rank_four_and_so3_validation_fail_closed(self):
        vertices, regions, train, neutral = self._fixture()
        with self.assertRaisesRegex(ValueError, "rank 4"):
            PoseCorrectiveField(vertices, regions, np.repeat(neutral[None], 3, axis=0), neutral)
        bad = train.copy(); bad[0, 0, 0, 0] = 2.
        with self.assertRaisesRegex(ValueError, "orthonormal"):
            PoseCorrectiveField(vertices, regions, bad, neutral)

    def test_training_inputs_are_not_mutated(self):
        vertices, regions, train, neutral = self._fixture()
        original = train.copy()
        PoseCorrectiveField(vertices, regions, train, neutral)
        np.testing.assert_array_equal(train, original)


if __name__ == "__main__":
    unittest.main()
