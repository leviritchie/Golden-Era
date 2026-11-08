import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_skin_joint_anchor_audit import audit_motion, posed


class MotionAuditTests(unittest.TestCase):
    def setUp(self):
        self.bind = np.repeat(np.eye(4)[None], 2, axis=0)
        self.bind[1, 0, 3] = 2
        self.skin = {"vertices": np.array([[2., 1., 0.]]),
                     "inverseBind": np.linalg.inv(self.bind),
                     "parents": np.array([-1, 0]), "names": np.array(["root", "child"])}
        self.worlds = self.bind[None].copy()

    def test_bind_identity_and_common_translation(self):
        weights = np.array([[.3, .7]])
        np.testing.assert_allclose(posed(self.skin, weights, self.worlds)[0], self.skin["vertices"])
        self.worlds[:, :, 1, 3] += 3
        np.testing.assert_allclose(posed(self.skin, weights, self.worlds)[0], self.skin["vertices"] + [0, 3, 0])
        self.assertEqual(audit_motion(self.skin, self.worlds)["joints"][0]["maxSharedJointError"], 0)

    def test_detects_rigid_but_disconnected_child(self):
        self.worlds[0, 1, 1, 3] += 1
        report = audit_motion(self.skin, self.worlds)
        self.assertEqual(report["singularValueDeviationMax"], 0)
        self.assertEqual(report["joints"][0]["maxSharedJointError"], 1)
        self.assertEqual(report["joints"][0]["relativeError"], .5)

    def test_detects_nonrigid_transform(self):
        self.worlds[0, 1, 0, 0] = 1.5
        self.assertEqual(audit_motion(self.skin, self.worlds)["singularValueDeviationMax"], .5)


if __name__ == "__main__":
    unittest.main()
