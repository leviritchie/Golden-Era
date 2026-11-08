import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preview_saved_linked_master import _rotate_candidate_y


class PreviewSavedLinkedMasterTests(unittest.TestCase):
    def test_zero_yaw_preserves_candidate(self):
        vertices = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        rotated = _rotate_candidate_y(vertices, 0.0)
        self.assertIs(rotated, vertices)

    def test_half_turn_rotates_only_candidate_coordinates(self):
        vertices = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        rotated = _rotate_candidate_y(vertices, 180.0)
        np.testing.assert_allclose(rotated, [[-1.0, 2.0, -3.0]], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
