import unittest

import torch

from sprite_surface_residual import SpriteSurfaceResidual


class SpriteSurfaceResidualTests(unittest.TestCase):
    def make(self):
        vertices = torch.tensor([[0., 0., 0.], [0., 0., 0.], [0., 0., 0.],
                                 [1., 1., 1.], [1e-12, 0., 0.]], dtype=torch.float64)
        weights = torch.tensor([[1., 0.], [1., 0.], [.5, .5], [1., 0.], [1., 0.]])
        return SpriteSurfaceResidual(vertices, weights, [0], 2)

    def test_zero_support_and_exact_duplicate_groups(self):
        field = self.make()
        self.assertEqual(tuple(field.displacement().shape), (2, 5, 3))
        self.assertTrue(torch.equal(field.displacement(), torch.zeros((2, 5, 3))))
        self.assertEqual(field.support_mask.tolist(), [True, True, False, False, False])
        with torch.no_grad():
            field.controls[0, 0] = torch.tensor([.2, .3, -.1])
        result = field.displacement()
        self.assertTrue(torch.equal(result[:, 0], result[:, 1]))
        self.assertTrue(torch.equal(result[:, 2:], torch.zeros((2, 3, 3))))
        self.assertTrue(torch.equal(result[1], torch.zeros((5, 3))))

    def test_vector_bound_and_gradients(self):
        field = self.make()
        field.displacement().sum().backward()
        self.assertTrue(torch.isfinite(field.controls.grad).all())
        self.assertGreater(float(field.controls.grad.abs().sum()), 0)
        for value in (1., 10000.):
            field.zero_grad()
            with torch.no_grad():
                field.controls.fill_(value)
            result = field.displacement()
            self.assertLessEqual(float(torch.linalg.vector_norm(result.detach(), dim=-1).max()),
                                 field.max_displacement + 1e-7)
            result[..., 0].sum().backward()
            self.assertTrue(torch.isfinite(field.controls.grad).all())

    def test_invalid_inputs_and_controls(self):
        for kwargs in ({"frame_count": 0}, {"vertex_ids": [-1]}, {"vertex_ids": [0.]},
                       {"max_displacement_fraction": float("nan")},
                       {"vertices": [[float("inf"), 0, 0], [1, 1, 1]]},
                       {"weights": [[float("nan")], [1.]]}):
            inputs = dict(vertices=[[0., 0., 0.], [1., 1., 1.]], weights=[[1.], [1.]],
                          vertex_ids=[0], frame_count=2)
            inputs.update(kwargs)
            with self.assertRaises(ValueError):
                SpriteSurfaceResidual(**inputs)
        field = self.make()
        with torch.no_grad():
            field.controls.fill_(float("nan"))
        with self.assertRaises(ValueError):
            field.displacement()


if __name__ == "__main__":
    unittest.main()
