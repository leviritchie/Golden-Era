import unittest
import numpy as np

from experiments.homm3_mocap_v2.mounted_ownership_diagnostic import probe


class MountedOwnershipDiagnosticTests(unittest.TestCase):
    def test_probe_changes_only_owned_joint_in_simple_rig(self):
        names = np.array(["root", "arm"]); parents = np.array([-1, 0]); rest = np.array([[0., 0, 0], [0, 1, 0]])
        vertices = np.array([[1., 1, 0], [1., 2, 0]]); triangles = np.array([[0, 1, 1]])
        weights = np.array([[0., 1.], [0., 1.]])
        inverse = np.repeat(np.eye(4)[None], 2, axis=0); inverse[1, :3, 3] = [0, -1, 0]
        result = probe(vertices, triangles, weights, names, parents, rest, inverse, "arm", ["rider", "rider"])
        self.assertGreater(result["vertexMovement"]["max"], 0.1)
        self.assertEqual(len(result["topTriangleStretch"]), 1)

    def test_unknown_joint_fails_closed(self):
        with self.assertRaises(ValueError):
            probe(np.zeros((1, 3)), np.zeros((0, 3), dtype=int), np.ones((1, 1)), ["root"], [-1],
                  np.zeros((1, 3)), np.eye(4)[None], "missing")


if __name__ == "__main__":
    unittest.main()
