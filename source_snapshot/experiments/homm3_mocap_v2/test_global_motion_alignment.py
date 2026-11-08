import unittest
import torch

from global_motion_alignment import transform_motion_palettes, GlobalMotionAlignment


def palettes():
    d = torch.eye(4, dtype=torch.float64).repeat(2, 3, 1, 1)
    d[0, 1, :3, 3] = torch.tensor([1., 0., 0.])
    d[1, 2, :3, :3] = torch.tensor([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    return d


class GlobalMotionAlignmentTests(unittest.TestCase):
    def test_trainable_module_has_only_shared_parameters(self):
        d = palettes().requires_grad_()
        field = GlobalMotionAlignment(d, pivot=torch.zeros(3), span=2., mode='similarity')
        self.assertEqual(sum(p.numel() for p in field.parameters()), 7)
        field()[..., :3, 3].square().sum().backward()
        self.assertIsNone(d.grad)
        self.assertTrue(torch.isfinite(field.raw.grad).all())
        self.assertTrue(torch.equal(field.source, d))
        self.assertEqual(GlobalMotionAlignment(d, pivot=torch.zeros(3), span=2., mode='rotation').raw.numel(), 3)

    def test_nonidentity_similarity_retains_rigid_bone_transforms(self):
        field = GlobalMotionAlignment(palettes(), pivot=torch.tensor([1., 2., 3.]), span=2., mode='similarity')
        with torch.no_grad():
            field.raw.copy_(torch.tensor([.2, -.4, .8, .9, -.3, .6, .8]))
        rotations = field()[..., :3, :3]
        torch.testing.assert_close(rotations.transpose(-1, -2) @ rotations,
            torch.eye(3, dtype=rotations.dtype).expand_as(rotations), atol=1e-12, rtol=1e-12)
        self.assertGreater(field.stats()['scale'], 1.)
        self.assertLess(field.stats()['scale'], 2.)

    def test_source_translation_rotates_and_scales_analytically(self):
        d = torch.eye(4, dtype=torch.float64).repeat(1, 1, 1, 1)
        d[0, 0, 0, 3] = 1.
        field = GlobalMotionAlignment(d, pivot=torch.ones(3), span=2., mode='similarity')
        with torch.no_grad():
            field.raw[2] = torch.pi/2
            field.raw[3] = .7
        expected = torch.tensor([0., field.stats()['scale'], 0.], dtype=torch.float64)
        torch.testing.assert_close(field()[0, 0, :3, 3], expected, atol=1e-12, rtol=1e-12)

    def test_identity_and_neutral(self):
        d = palettes()
        out = transform_motion_palettes(d, mesh_span=2., pivot=torch.zeros(3, dtype=torch.float64))
        self.assertTrue(torch.allclose(out["palettes"], d))
        self.assertTrue(torch.allclose(out["matrix"], torch.eye(4, dtype=torch.float64)))
        self.assertTrue(out["report"]["sharedTransform"])

    def test_exact_shared_similarity_conjugation(self):
        d = palettes()
        raw = torch.tensor([0., 0., 0.2, 0.0, 0.1, -0.1, 0.2], dtype=torch.float64)
        out = transform_motion_palettes(d, raw_params=raw, mesh_span=2., pivot=torch.zeros(3, dtype=torch.float64))
        expected = out["matrix"] @ d @ torch.linalg.inv(out["matrix"])
        self.assertTrue(torch.allclose(out["palettes"], expected))
        self.assertGreater(out["report"]["scale"], 0.)
        self.assertGreater(out["report"]["rotationDeterminant"], 0.999)

    def test_gradients_finite_at_zero(self):
        raw = torch.zeros(7, dtype=torch.float64, requires_grad=True)
        out = transform_motion_palettes(palettes(), raw_params=raw, mesh_span=2., pivot=torch.zeros(3, dtype=torch.float64))
        loss = out["palettes"].square().sum()
        loss.backward()
        self.assertTrue(torch.isfinite(raw.grad).all())

    def test_source_unchanged_and_affine(self):
        d = palettes(); before = d.clone()
        out = transform_motion_palettes(d, mode="rotation", raw_params=torch.tensor([.1, .2, .3]), mesh_span=2., pivot=torch.zeros(3))
        self.assertTrue(torch.equal(d, before))
        self.assertTrue(torch.allclose(out["palettes"][..., 3, :], torch.tensor([0., 0., 0., 1.], dtype=out["palettes"].dtype)))


if __name__ == "__main__":
    unittest.main()
