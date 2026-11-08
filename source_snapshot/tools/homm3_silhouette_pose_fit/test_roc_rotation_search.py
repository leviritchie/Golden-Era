import math
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from roc_rotation_search import (  # noqa: E402
    continuation_proposal,
    quaternion_angle_deg,
    quaternion_from_euler_xyz,
    quaternion_to_euler_xyz,
    rotation_vector_proposals,
    virtual_search_frame,
)


class RotationSearchTests(unittest.TestCase):
    def test_virtual_frame_is_orthonormal_for_nonstandard_shaft(self):
        frame = virtual_search_frame((1.0, 2.0, 3.0))
        vectors = (frame["shaft"], frame["swingA"], frame["swingB"])
        for vector in vectors:
            self.assertAlmostEqual(sum(value * value for value in vector), 1.0, places=6)
        for left_index, left in enumerate(vectors):
            for right in vectors[left_index + 1 :]:
                self.assertAlmostEqual(sum(a * b for a, b in zip(left, right)), 0.0, places=6)

    def test_adaptive_shell_adds_explicit_twist_candidates(self):
        proposals = rotation_vector_proposals(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.2),
            16.0,
            8,
            150.0,
            include_twist=True,
            twist_policy="adaptive",
        )
        self.assertEqual(len(proposals), 10)
        self.assertEqual(sum(proposal["kind"] == "twist" for proposal in proposals), 2)
        self.assertTrue(all(proposal["twistPolicy"] in {"include", "exclude"} for proposal in proposals))

    def test_continuation_is_bounded(self):
        proposal = rotation_vector_proposals(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            32.0,
            8,
            150.0,
            include_twist=False,
            twist_policy="exclude",
        )[0]
        self.assertIsNotNone(
            continuation_proposal(
                (1.0, 0.0, 0.0, 0.0),
                proposal["axis"],
                64.0,
                150.0,
                kind="swing",
                direction=0,
                twist_policy="exclude",
            )
        )
        self.assertIsNone(
            continuation_proposal(
                (1.0, 0.0, 0.0, 0.0),
                proposal["axis"],
                160.0,
                150.0,
                kind="swing",
                direction=0,
                twist_policy="exclude",
            )
        )

    def test_euler_round_trip(self):
        original = (0.2, -0.3, 0.4)
        recovered = quaternion_to_euler_xyz(quaternion_from_euler_xyz(*original))
        for expected, actual in zip(original, recovered):
            self.assertTrue(math.isclose(expected, actual, abs_tol=1e-6))
        self.assertGreater(quaternion_angle_deg(quaternion_from_euler_xyz(*original)), 0.0)


if __name__ == "__main__":
    unittest.main()
