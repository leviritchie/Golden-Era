import unittest
import numpy as np

from source_wrist_orientation import solve_projected_direction


class SourceWristOrientationTests(unittest.TestCase):
    def test_neutral_and_nonaxis_basis_preserve_depth_and_magnitude(self):
        right = np.array([1., 1., 0.]); right /= np.linalg.norm(right)
        down = np.array([-1., 1., 2.]); down -= right * (right @ down); down /= np.linalg.norm(down)
        current = np.array([.3, .4, .85]); target = np.array([current @ right, current @ down])
        out = solve_projected_direction(current, target, right, down, 1.)
        np.testing.assert_allclose(out["desiredDirection"], current, atol=1e-8)
        self.assertAlmostEqual(out["angleRad"], 0., places=8)
        np.testing.assert_allclose(np.linalg.det(out["rotation"]), 1., atol=1e-8)

    def test_screen_azimuth_changes_only_and_rotation_is_proper(self):
        right = np.array([1., 0., 1.]); right /= np.linalg.norm(right)
        down = np.array([0., 1., 0.])
        current = np.array([1., 0., 1.]); target = np.array([0., 1.])
        out = solve_projected_direction(current, target, right, down, 90.)
        got = out["rotation"] @ current
        self.assertAlmostEqual(float(got @ right), 0., places=7)
        self.assertGreater(float(got @ down), 0.)
        self.assertAlmostEqual(float(got @ np.cross(right, down)), float(current @ np.cross(right, down)), places=7)
        np.testing.assert_allclose(out["rotation"].T @ out["rotation"], np.eye(3), atol=1e-8)
        self.assertAlmostEqual(np.linalg.det(out["rotation"]), 1., places=8)

    def test_antiparallel_and_bound_fail_closed(self):
        for target in ([-1., 0.], [-1., 1e-7], [-1., -1e-7]):
            out = solve_projected_direction([1., 0., 0.], target, [1., 0., 0.], [0., 1., 0.], 180.)
            np.testing.assert_allclose(out["rotation"] @ [1., 0., 0.], out["desiredDirection"], atol=1e-10)
            np.testing.assert_allclose(out["rotation"].T @ out["rotation"], np.eye(3), atol=1e-10)
            self.assertAlmostEqual(np.linalg.det(out["rotation"]), 1., places=10)
        with self.assertRaises(ValueError):
            solve_projected_direction([1., 0., 0.], [-1., 0.], [1., 0., 0.], [0., 1., 0.], 10.)
        with self.assertRaises(ValueError):
            solve_projected_direction([1., 0., 0.], [0., 1.], [1., 0., 0.], [0., 1., 0.], 1.)

    def test_invalid_basis_and_zero_projection_rejected(self):
        with self.assertRaises(ValueError):
            solve_projected_direction([0., 0., 1.], [1., 0.], [1., 0., 0.], [1., 0., 0.], 90.)
        with self.assertRaises(ValueError):
            solve_projected_direction([0., 0., 1.], [1., 0.], [1., 0., 0.], [0., 1., 0.], 90.)

    def test_inputs_are_not_mutated_and_nearparallel_is_exact(self):
        current = np.array([1., .001, .2]); target = np.array([2., .001])
        right = np.array([2., 0., 0.]); down = np.array([0., 3., 0.])
        originals = [x.copy() for x in (current, target, right, down)]
        out = solve_projected_direction(current, target, right, down, 10.)
        for value, original in zip((current, target, right, down), originals):
            np.testing.assert_array_equal(value, original)
        np.testing.assert_allclose(out["rotation"] @ current, out["desiredDirection"], atol=1e-6)


if __name__ == "__main__": unittest.main()
