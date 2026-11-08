import sys
import unittest
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from joint_anchor_objective import FixedJointAnchorObjective


class FixedJointAnchorObjectiveTests(unittest.TestCase):
    def model(self, supported=True, two=True):
        joints = {"0": {"vertexIds": [0], "coefficients": [1.],
                         "adjacentSegmentLength": 1., "supported": supported}}
        if two:
            joints["1"] = {"vertexIds": [1], "coefficients": [1.],
                            "adjacentSegmentLength": 2., "supported": supported}
        return {"schema": "skin-joint-anchor-model-v1", "jointNames": ["root", "tip"],
                "chains": {"limb": {"joints": joints}}}

    def world(self):
        world = np.tile(np.eye(4)[None, None], (2, 2, 1, 1))
        world[:, 0, 0, 3] = [3., 4.]
        world[:, 1, 0, 3] = [5., 6.]
        return world

    def test_nonzero_origins_and_rigid_translation_zero(self):
        objective = FixedJointAnchorObjective(self.model(), self.world(), 2, "cpu")
        animated = torch.tensor([[[3., 0., 0.], [5., 0., 0.]],
                                 [[4., 0., 0.], [6., 0., 0.]]])
        self.assertLess(float(objective.loss(animated)), 1e-12)

    def test_wrong_mesh_positive_and_differentiable(self):
        objective = FixedJointAnchorObjective(self.model(), self.world(), 2, "cpu")
        animated = torch.zeros((2, 2, 3), requires_grad=True)
        loss = objective(animated)
        self.assertGreater(float(loss.detach()), 0.)
        loss.backward()
        self.assertTrue(torch.isfinite(animated.grad).all())
        self.assertGreater(float(animated.grad.abs().sum()), 0.)

    def test_unsupported_is_skipped_explicitly(self):
        objective = FixedJointAnchorObjective(self.model(supported=True, two=False), self.world(), 2, "cpu")
        self.assertEqual(objective.report()["supportedAnchorCount"], 1)
        self.assertEqual(objective.report()["unsupportedJoints"], [])
        model = self.model(supported=False)
        model["chains"]["limb"]["joints"]["0"]["supported"] = True
        model["chains"]["limb"]["joints"]["1"]["supported"] = False
        objective = FixedJointAnchorObjective(model, self.world(), 2, "cpu")
        self.assertEqual(objective.report()["unsupportedJoints"], [{"region": "limb", "joint": "tip"}])

    def test_no_supported_anchor_fails(self):
        with self.assertRaises(ValueError):
            FixedJointAnchorObjective(self.model(supported=False), self.world(), 2, "cpu")

    def test_fixed_inputs_are_immutable_and_bad_support_refuses(self):
        world = self.world()
        objective = FixedJointAnchorObjective(self.model(), world, 2, "cpu")
        world[:, :, :, :] = 99.
        animated = torch.tensor([[[3., 0., 0.], [5., 0., 0.]],
                                 [[4., 0., 0.], [6., 0., 0.]]])
        self.assertLess(float(objective.loss(animated)), 1e-12)
        bad = self.model()
        bad["chains"]["limb"]["joints"]["0"]["vertexIds"] = [0.5]
        with self.assertRaises(ValueError):
            FixedJointAnchorObjective(bad, self.world(), 2, "cpu")
        bad = self.model()
        bad["chains"]["limb"]["joints"]["0"]["adjacentSegmentLength"] = float("inf")
        with self.assertRaises(ValueError):
            FixedJointAnchorObjective(bad, self.world(), 2, "cpu")

    def test_integer_animated_mesh_refuses(self):
        objective = FixedJointAnchorObjective(self.model(), self.world(), 2, "cpu")
        with self.assertRaises(ValueError):
            objective(torch.zeros((2, 2, 3), dtype=torch.int64))


if __name__ == "__main__":
    unittest.main()
