"""CPU-safe objective checks; CUDA renderer smoke is intentionally opt-in."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import torch

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from skin_image_objective import SkinImageRenderer, image_loss, image_metrics


class SkinImageObjectiveTests(unittest.TestCase):
    def test_perfect_images_are_zero_and_finite(self) -> None:
        rgb = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
        rgb[..., 0] = 0.8
        alpha = torch.zeros((1, 8, 8, 1), dtype=torch.float32)
        alpha[:, 2:6, 2:6] = 1.0
        distance = torch.ones((1, 8, 8), dtype=torch.float32)
        result = image_loss(rgb, alpha, rgb.clone(), alpha.clone(), distance)
        self.assertTrue(torch.isfinite(result["total"]))
        self.assertLess(float(result["total"]), 1e-7)
        metrics = image_metrics(rgb, alpha, rgb, alpha)
        self.assertAlmostEqual(metrics[0]["iou"], 1.0, places=6)

    def test_loss_provides_gradient(self) -> None:
        rgb = torch.zeros((1, 8, 8, 3), dtype=torch.float32, requires_grad=True)
        alpha = torch.zeros((1, 8, 8, 1), dtype=torch.float32, requires_grad=True)
        target_rgb = torch.ones_like(rgb) * 0.5
        target_alpha = torch.zeros_like(alpha)
        target_alpha[:, 2:6, 2:6] = 1.0
        result = image_loss(rgb, alpha, target_rgb, target_alpha, torch.ones((1, 8, 8)))
        result["total"].backward()
        self.assertIsNotNone(alpha.grad)
        self.assertTrue(torch.isfinite(alpha.grad).all())

    @unittest.skipUnless(os.environ.get("RUN_SKIN_IMAGE_CUDA_SMOKE") == "1", "CUDA smoke is opt-in")
    def test_cuda_renderer_smoke(self) -> None:
        self.assertTrue(torch.cuda.is_available())

    @unittest.skipUnless(os.environ.get("RUN_SKIN_IMAGE_CUDA_SMOKE") == "1", "CUDA smoke is opt-in")
    def test_cuda_batch_texture_orientation_and_gradient(self) -> None:
        triangles = torch.tensor([[0, 1, 2], [0, 2, 3]], dtype=torch.int32).cpu().numpy()
        # World y increases downwards in this camera. UV v=0 is the first
        # image row, so the rendered top half must be the red texture half.
        uvs = torch.tensor([[0., 0.], [1., 0.], [1., 1.], [0., 1.]]).numpy()
        albedo = torch.zeros((4, 4, 3), dtype=torch.uint8).numpy()
        albedo[:2, :, 0] = 255
        albedo[2:, :, 2] = 255
        camera = {
            "right": (1., 0., 0.), "down": (0., 1., 0.), "forward": (0., 0., 1.),
            "scale": 1., "offset": (3.5, 3.5), "depth_center": 0., "depth_span": 2.,
        }
        renderer = SkinImageRenderer(triangles, uvs, albedo, camera, resolution=8)
        vertices = torch.tensor(
            [[[-3., -3., 0.], [3., -3., 0.], [3., 3., 0.], [-3., 3., 0.]],
             [[-2.8, -3., 0.], [3.2, -3., 0.], [3.2, 3., 0.], [-2.8, 3., 0.]]],
            device="cuda", dtype=torch.float32, requires_grad=True,
        )
        rgb, alpha = renderer.render(vertices)
        self.assertEqual(tuple(rgb.shape), (2, 8, 8, 3))
        self.assertEqual(tuple(alpha.shape), (2, 8, 8, 1))
        for frame in range(2):
            self.assertGreater(float(rgb[frame, 2, 4, 0].detach()), .8)
            self.assertLess(float(rgb[frame, 2, 4, 2].detach()), .2)
            self.assertGreater(float(rgb[frame, 5, 4, 2].detach()), .8)
            self.assertLess(float(rgb[frame, 5, 4, 0].detach()), .2)
        loss = (rgb.mean() + alpha.mean())
        loss.backward()
        self.assertIsNotNone(vertices.grad)
        self.assertTrue(torch.isfinite(vertices.grad).all())
        self.assertGreater(float(vertices.grad.abs().sum()), 0.0)


if __name__ == "__main__":
    unittest.main()
