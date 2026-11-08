import sys
import unittest
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_mesh_field import MeshField, validate_rest_field


class MeshFieldTests(unittest.TestCase):
    def setUp(self):
        self.v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], [.05, .05, 0]], float)
        self.r = np.array(["beak", "body", "body", "body_uv", "body"])

    def test_bound_duplicate_and_frozen_exact(self):
        field = MeshField(self.v, self.r, frozen_regions={"beak"}, grid_resolution=3)
        with torch.no_grad(): field.control.fill_(100)
        out = field.vertices()
        self.assertTrue(torch.equal(out[0], torch.as_tensor(self.v[0], dtype=torch.float32)))
        self.assertTrue(torch.allclose(out[1], out[3]))
        self.assertLessEqual(float(torch.linalg.vector_norm(out - field.rest_vertices, dim=1).max()), field.max_displacement + 1e-6)
        self.assertTrue(validate_rest_field(field))

    def test_rounded_duplicate_group_is_identical(self):
        vertices = self.v.copy()
        vertices[3] = [1.0 + 2e-7, 2e-7, 0]
        field = MeshField(vertices, self.r, grid_resolution=3)
        with torch.no_grad(): field.control.normal_(std=2)
        self.assertTrue(torch.allclose(field.vertices()[1], field.vertices()[3], atol=1e-6))
        self.assertTrue(validate_rest_field(field))

    def test_taper_near_frozen_and_gradient(self):
        field = MeshField(self.v, self.r, frozen_regions={"beak"}, grid_resolution=3)
        self.assertEqual(float(field.taper[0]), 0.0)
        self.assertLess(float(field.taper[4]), 1.0)
        loss = field.penalty()
        loss.backward()
        self.assertIsNotNone(field.control.grad)
        self.assertTrue(torch.isfinite(field.control.grad).all())

    def test_invalid_and_zero_bound(self):
        with self.assertRaises(ValueError): MeshField(self.v, self.r, frozen_regions={"leg"})
        with self.assertRaises(ValueError): MeshField(self.v, self.r, grid_resolution=7)
        field = MeshField(self.v, self.r, max_displacement_fraction=0)
        self.assertTrue(torch.equal(field.vertices(), field.rest_vertices))


if __name__ == "__main__":
    unittest.main()
