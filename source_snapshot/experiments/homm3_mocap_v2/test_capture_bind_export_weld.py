"""The bind producer and repair consumer share exact exported-position welds."""
import unittest

import numpy as np

from experiments.homm3_mocap_v2.prepare_move_bind_capture_bind import (
    _coincident_pairs, candidate_support, geodesic_bone_distances,
    nearest_bone_segment_weights,
)
from experiments.homm3_mocap_v2.topology_weight_field import RepairWeightField


class ExportWeldTests(unittest.TestCase):
    def test_opposed_seams_share_distance_weights_and_support(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                             [0, 0, 0], [-1, 0, 0], [0, 1, 0]], dtype=float)
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        distances = np.array([[10, 11], [.1, 3], [2, 3],
                              [10, 11], [3, .1], [2, 3]], dtype=float)

        def field(policy):
            geo = geodesic_bone_distances(vertices, triangles, distances,
                                         weld_policy=policy)["distances"]
            weights = nearest_bone_segment_weights(geo, k=1)
            support, train = candidate_support(geo, weights, ["a", "b"],
                                              trainable_regions=("a", "b"), ratio=1, cap=2)
            return geo, weights, support, train

        _, weights, support, train = field("coincident_agreeing_normals")
        with self.assertRaisesRegex(ValueError, "allowed_support must agree"):
            RepairWeightField(vertices, triangles, weights, np.zeros(6, dtype=int), train, support)
        geo, weights, support, train = field("export_position")
        for first, other in [(0, 3), (2, 5)]:
            np.testing.assert_array_equal(geo[first], geo[other])
            np.testing.assert_array_equal(weights[first], weights[other])
            np.testing.assert_array_equal(support[first], support[other])
        repaired = RepairWeightField(vertices, triangles, weights, np.zeros(6, dtype=int), train, support)
        self.assertTrue(repaired.validate())

    def test_weld_identity_matches_float32_not_decimal_rounding(self):
        vertices = np.array([[1, 0, 0], [1 + 1e-9, 0, 0], [1 + 2e-7, 0, 0]])
        self.assertEqual(_coincident_pairs(vertices, export_position=True), [(0, 1)])


if __name__ == "__main__":
    unittest.main()
