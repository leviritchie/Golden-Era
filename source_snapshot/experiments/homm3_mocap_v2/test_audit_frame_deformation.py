import unittest

import numpy as np

from audit_frame_deformation import _semantic_region, audit_deformation_arrays


class FrameDeformationAuditTests(unittest.TestCase):
    def test_joint_labels_map_to_conservative_regions(self):
        self.assertEqual(_semantic_region("mixamorig:LeftForeArm"), "upper_limb")
        self.assertEqual(_semantic_region("RightFoot"), "lower_limb")
        self.assertEqual(_semantic_region("Spine2"), "torso")
        self.assertEqual(_semantic_region("WingRoot"), "wing")

    def test_flags_low_motion_high_strain_region(self):
        rest = np.array([
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0],
        ], dtype=np.float64)
        triangles = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
        joints = np.zeros((6, 1), dtype=np.int64)
        joints[3:, 0] = 1
        weights = np.ones((6, 1), dtype=np.float64)
        posed = np.stack([rest, rest.copy(), rest.copy()])
        # Establish a high-motion torso baseline so a compact, strained limb
        # is correctly identified as low-motion/high-strain.
        posed[1:, :3] += [5.0, 0.0, 0.0]
        posed[1:, 4] = [1.8, 0.0, 1.0]
        result = audit_deformation_arrays(
            names=["Spine", "LeftFoot"],
            vertex_joints=joints,
            vertex_weights=weights,
            triangles=triangles,
            rest_vertices=rest,
            posed_vertices=posed,
        )
        self.assertIn("lower_limb", result["regions"])
        self.assertTrue(result["regions"]["lower_limb"]["surfaceStrainP95"] > 1.5)
        self.assertIn("lower_limb", result["flaggedRegions"])


if __name__ == "__main__":
    unittest.main()
