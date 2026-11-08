import unittest
from types import SimpleNamespace

import numpy as np

from audit_target_skin import summarize


class TargetSkinAuditTests(unittest.TestCase):
    def skeleton(self):
        return SimpleNamespace(names=["root", "arm", "hand", "leg", "foot"],
            parents=[-1, 0, 1, 0, 3], vertices=np.array([[0., 0, 0], [2., 0, 0]]),
            rest_world=np.zeros((5, 3)), triangles=np.empty((0, 3), dtype=int),
            vertex_joints=np.array([[2, 4], [1, 3]]),
            vertex_weights=np.array([[.75, .25], [.6, .4]]))

    def test_slots_are_not_joint_columns(self):
        report = summarize(self.skeleton())
        self.assertEqual(report["influenceSlotsPerVertex"], 2)
        self.assertEqual(report["weightedJointCount"], 4)
        rows = {row["name"]: row for row in report["joints"]}
        self.assertEqual(rows["root"]["weightMass"], 0)
        self.assertEqual(rows["hand"]["weightMass"], .75)
        self.assertEqual(rows["foot"]["weightMass"], .25)
        self.assertEqual(rows["hand"]["parent"], "arm")
        self.assertEqual(rows["arm"]["weightedCentroidMeshLocal"], [2., 0, 0])

    def test_invalid_raw_indices_and_geometry_rejected(self):
        for index in (-1, 5):
            skeleton = self.skeleton()
            skeleton.vertex_joints[0, 0] = index
            with self.assertRaisesRegex(ValueError, "influence joint index"):
                summarize(skeleton)
        for vertices in (np.zeros((2, 2)), np.zeros((3, 3)), np.full((2, 3), np.nan)):
            skeleton = self.skeleton()
            skeleton.vertices = vertices
            with self.assertRaises(ValueError):
                summarize(skeleton)

    def test_zero_support_and_duplicate_names_rejected(self):
        skeleton = self.skeleton()
        skeleton.vertex_weights[0] = 0
        with self.assertRaises(ValueError):
            summarize(skeleton)

    def test_invalid_parent_and_triangle_arrays_rejected(self):
        for key, value in (("parents", [-1, 0.5, 1, 0, 3]),
                           ("parents", [-1, np.nan, 1, 0, 3]),
                           ("triangles", None), ("triangles", [[0, 1, 2]])):
            skeleton = self.skeleton()
            setattr(skeleton, key, value)
            with self.assertRaises(ValueError):
                summarize(skeleton)
        skeleton = self.skeleton()
        skeleton.names[-1] = "root"
        with self.assertRaises(ValueError):
            summarize(skeleton)


if __name__ == "__main__":
    unittest.main()
