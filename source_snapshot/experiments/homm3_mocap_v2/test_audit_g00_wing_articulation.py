import unittest
import numpy as np

from audit_g00_wing_articulation import angle, proper_alignment


class WingArticulationMathTests(unittest.TestCase):
    def test_proper_alignment_removes_rigid_rotation(self):
        rest = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
        q = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        current = rest @ q
        fitted, singular = proper_alignment(rest, current)
        self.assertTrue(np.allclose(fitted, q))
        self.assertGreater(singular[1], 1e-9)

    def test_rank_one_hubs_fail_closed(self):
        rest = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]])
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            proper_alignment(rest, rest)

    def test_zero_angle_vector_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "zero"):
            angle(np.zeros(3), np.ones(3))


if __name__ == "__main__":
    unittest.main()
