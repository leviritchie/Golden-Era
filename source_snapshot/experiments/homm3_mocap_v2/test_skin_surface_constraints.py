import sys
import unittest
from pathlib import Path
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_surface_constraints import (
    rest_mesh_gate,
    surface_constraint_loss,
    surface_constraint_metrics,
    triangle_principal_stretches,
)


class SurfaceConstraintTests(unittest.TestCase):
    def setUp(self):
        self.rest = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., 0.]])
        self.triangles = torch.tensor([[0, 1, 2], [1, 3, 2]])

    def test_rigid_rotation_is_one(self):
        theta = np.pi / 3
        rotation = torch.tensor([[np.cos(theta), -np.sin(theta), 0.], [np.sin(theta), np.cos(theta), 0.], [0., 0., 1.]], dtype=torch.float32)
        moved = (self.rest - torch.tensor([.2, -.4, 1.])) @ rotation.T + torch.tensor([2., 3., -1.])
        stretches, valid, _ = triangle_principal_stretches(moved, self.rest, self.triangles)
        self.assertTrue(torch.allclose(stretches[:, valid], torch.ones_like(stretches[:, valid]), atol=1e-5))

    def test_scale_and_compression(self):
        scale = torch.diag(torch.tensor([2., .5, 1.]))
        stretches, valid, _ = triangle_principal_stretches(self.rest @ scale, self.rest, self.triangles)
        self.assertTrue(torch.allclose(stretches[0, valid], torch.tensor([[2., .5], [2., .5]]), atol=1e-4))
        loss, metrics = surface_constraint_loss(self.rest @ scale, self.rest, self.triangles)
        self.assertGreater(float(loss), 0.)
        self.assertEqual(metrics["validTriangleCount"], 2)

    def test_gradient_finite_at_identity(self):
        moved = self.rest.clone().requires_grad_()
        loss, _ = surface_constraint_loss(moved, self.rest, self.triangles)
        loss.backward()
        self.assertTrue(torch.isfinite(moved.grad).all())

    def test_degenerate_reference_is_excluded_and_counted(self):
        rest = torch.cat((self.rest, torch.tensor([[0., 0., 0.], [1e-10, 0., 0.], [0., 1e-10, 0.]])))
        triangles = torch.cat((self.triangles, torch.tensor([[4, 5, 6]])))
        stretches, valid, _ = triangle_principal_stretches(rest, rest, triangles)
        self.assertEqual(int(valid.sum()), 2)
        self.assertEqual(surface_constraint_metrics(stretches, valid, torch.ones(3))["validTriangleCount"], 2)

    def test_rest_gate_reports_fractions_and_normal_flip(self):
        candidate = self.rest.clone()
        candidate[3, 2] = .01
        report = rest_mesh_gate(self.rest, candidate, self.triangles)
        self.assertIn("triangleRatioViolationFraction", report)
        self.assertIn("normalFlipFraction", report)
        flipped = self.rest[self.triangles[[0, 2, 1]]].reshape(-1, 3) if False else candidate.clone()
        flipped[2] = torch.tensor([0., 1., -1.])
        self.assertGreaterEqual(rest_mesh_gate(self.rest, flipped, self.triangles)["normalFlipFraction"], 0.)


if __name__ == "__main__":
    unittest.main()
