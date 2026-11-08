"""Atlas and prop-axis regression tests for composed Meshy sources."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_textured_mesh import _atlas_uv, _rotation_from_y_axis


class ComposeTexturedMeshTests(unittest.TestCase):
    def test_unequal_texture_heights_map_into_top_left_atlas_regions(self):
        uv = np.array([[0.0, 0.0], [1.0, 1.0], [0.25, 0.75]])
        body = _atlas_uv(uv, 0, 0, 2048, 2048, 6144, 4096)
        prop = _atlas_uv(uv, 2048, 0, 4096, 4096, 6144, 4096)
        np.testing.assert_allclose(body[2], [0.25 / 3, 0.375])
        np.testing.assert_allclose(prop[2], [0.5, 0.75])
        np.testing.assert_allclose(body[1], [1 / 3, 0.5])

    def test_same_source_and_target_axis_give_identity_rotation(self):
        axis = np.array([0.0, 1.0, 0.0])
        transform = _rotation_from_y_axis(axis) @ _rotation_from_y_axis(axis).T
        np.testing.assert_allclose(transform, np.eye(3))


if __name__ == "__main__":
    unittest.main()
