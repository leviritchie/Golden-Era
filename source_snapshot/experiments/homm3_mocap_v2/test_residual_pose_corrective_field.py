import sys
import unittest
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pose_corrective_field import PoseCorrectiveField
from residual_pose_corrective_field import ResidualPoseCorrectiveField


class ResidualPoseCorrectiveFieldTests(unittest.TestCase):
    def _rotation(self, axis, angle):
        axis = np.asarray(axis, dtype=np.float64)
        axis /= np.linalg.norm(axis)
        x, y, z = axis
        c, s, v = np.cos(angle), np.sin(angle), 1.0 - np.cos(angle)
        return np.array([
            [c + x * x * v, x * y * v - z * s, x * z * v + y * s],
            [y * x * v + z * s, c + y * y * v, y * z * v - x * s],
            [z * x * v - y * s, z * y * v + x * s, c + z * z * v],
        ])

    def _fixture(self):
        vertices = np.array([
            [0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
            [0., 0., 0.], [1., 1., 1.],
        ], dtype=np.float32)
        regions = np.array(["frozen", "body", "wing", "body", "frozen", "wing"])
        neutral = np.repeat(np.eye(3)[None], 3, axis=0)
        poses = []
        for index in range(16):
            pose = neutral.copy()
            pose[0] = self._rotation((1., 2. + index, 3.), .08 + .035 * index)
            pose[1] = self._rotation((2. + index, 1., 3.), -.12 + .027 * index)
            pose[2] = self._rotation((3., 2., 1. + index), .10 - .021 * index)
            poses.append(pose)
        return vertices, regions, np.stack(poses), neutral

    def _field_pair(self):
        vertices, regions, train, neutral = self._fixture()
        base = PoseCorrectiveField(
            vertices, regions, train, neutral, frozen_regions=["frozen"],
            max_displacement_fraction=.10, grid_resolution=4,
        )
        expanded = ResidualPoseCorrectiveField(
            vertices, regions, train, neutral, frozen_regions=["frozen"],
            max_displacement_fraction=.10, grid_resolution=4, target_energy=.99999999,
        )
        expanded.load_four_mode_state(base.state_dict())
        return base, expanded, vertices, regions, train, neutral

    def test_legacy_warmstart_matches_four_mode_displacement(self):
        base, expanded, _, _, train, _ = self._field_pair()
        with torch.no_grad():
            for mode in base.modes:
                mode.control.normal_(0., .2)
            expanded.load_four_mode_state(base.state_dict())
        np.testing.assert_allclose(
            base.displacement(train).detach().numpy(),
            expanded.displacement(train).detach().numpy(),
            atol=0., rtol=0.,
        )

    def test_neutral_is_zero_and_coefficients_are_bounded(self):
        _, field, _, _, _, neutral = self._field_pair()
        with torch.no_grad():
            for mode in field.modes:
                mode.control.normal_(0., .2)
        coefficients = field.coefficients(neutral[None])
        self.assertEqual(float(field.displacement(neutral[None]).detach().abs().max()), 0.0)
        self.assertLessEqual(float(coefficients.abs().sum(dim=-1).max()), 1.0 + 1e-6)

    def test_residual_modes_have_gradient_and_preserve_field_invariants(self):
        _, field, vertices, _, train, _ = self._field_pair()
        with torch.no_grad():
            for mode in field.modes[4:]:
                mode.control.normal_(0., .3)
        displacement = field.displacement(train[:4])
        displacement.square().sum().backward()
        residual_gradient = sum(
            float(mode.control.grad.abs().sum()) for mode in field.modes[4:]
        )
        self.assertGreater(residual_gradient, 0.0)
        values = displacement.detach().numpy()
        np.testing.assert_array_equal(values[:, [0, 4]], 0.0)
        np.testing.assert_allclose(values[:, 0], values[:, 4], atol=0., rtol=0.)
        diag = np.linalg.norm(vertices.max(0) - vertices.min(0))
        self.assertLessEqual(np.linalg.norm(values, axis=-1).max(), .10 * diag + 1e-6)

    def test_rank_selection_is_deterministic_under_training_duplication(self):
        vertices, regions, train, neutral = self._fixture()
        first = ResidualPoseCorrectiveField(
            vertices, regions, train, neutral, grid_resolution=4, target_energy=.99999999,
        )
        duplicate = ResidualPoseCorrectiveField(
            vertices, regions, np.concatenate((train, train), axis=0), neutral,
            grid_resolution=4, target_energy=.99999999,
        )
        self.assertEqual(first.residual_rank, duplicate.residual_rank)
        # SVD vectors have an arbitrary independent sign under duplicated
        # input; rank and singular-value magnitudes remain deterministic.
        np.testing.assert_allclose(
            np.abs(first.feature_basis.detach().numpy()),
            np.abs(duplicate.feature_basis.detach().numpy()),
            atol=2e-5, rtol=2e-5,
        )
        np.testing.assert_allclose(
            np.abs(first.residual_basis.detach().numpy()),
            np.abs(duplicate.residual_basis.detach().numpy()),
            atol=2e-5, rtol=2e-5,
        )

    def test_legacy_state_inventory_and_buffers_are_fail_closed(self):
        base, expanded, _, _, _, _ = self._field_pair()
        state = dict(base.state_dict())
        with torch.no_grad():
            expanded.modes[4].control[0, 0] = .1
        with self.assertRaisesRegex(ValueError, "residual controls"):
            expanded.load_four_mode_state(state)
        with torch.no_grad():
            expanded.modes[4].control.zero_()
        altered = dict(state)
        altered["neutral_local_rotations"] = altered["neutral_local_rotations"].clone()
        altered["neutral_local_rotations"][0, 0, 0] += 1e-3
        with self.assertRaisesRegex(ValueError, "non-control buffer"):
            expanded.load_four_mode_state(altered)
        extra = dict(state)
        extra["unexpected"] = torch.zeros(1)
        with self.assertRaisesRegex(ValueError, "inventory"):
            expanded.load_four_mode_state(extra)


if __name__ == "__main__":
    unittest.main()
