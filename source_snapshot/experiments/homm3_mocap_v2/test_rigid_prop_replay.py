import unittest
from unittest.mock import patch
from pathlib import Path
import json

import torch

from replay_rigid_prop_faces import rigid_corners, run


class RigidPropReplayTests(unittest.TestCase):
    def test_mask_producer_digest_required_before_gpu(self):
        loaded = ({"inputs":{"researchSkin":"skin"}}, None, None, None, None, None, None, None, None)
        for claimed in (None,"wrong"):
            report = {"asset":"unit","researchSkinSha256":"skin","maskSha256":claimed}
            with patch("replay_rigid_prop_faces._load_inputs",return_value=loaded), patch.object(Path,"exists",return_value=False), patch.object(Path,"read_text",return_value=json.dumps(report)), patch("replay_rigid_prop_faces.sha256_file",return_value="actual"), patch("replay_rigid_prop_faces.cascade_batch_lock") as gpu:
                with self.assertRaisesRegex(ValueError,"producer digest"):
                    run("unit",Path("fit"),Path("mask"),"hand",Path("output"))
                gpu.assert_not_called()

    def setUp(self):
        # Face 0 is the proposed prop; face 1 shares vertex 0 but remains body.
        self.rest = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 2.]])
        self.faces = torch.tensor([[0, 1, 2], [0, 2, 3]], dtype=torch.long)
        self.selected = torch.tensor([0], dtype=torch.long)

    def test_neutral_identity_is_exact(self):
        baseline = self.rest.unsqueeze(0).clone()
        transform = torch.eye(4).unsqueeze(0)
        out = rigid_corners(baseline, self.rest, self.faces, self.selected, transform)
        torch.testing.assert_close(out, baseline[:, self.faces], rtol=0, atol=0)

    def test_only_selected_face_corners_change(self):
        baseline = self.rest.unsqueeze(0).repeat(2, 1, 1)
        baseline[1, 3] = torch.tensor([9., 9., 9.])
        transform = torch.eye(4).repeat(2, 1, 1)
        transform[1, :3, :3] = torch.tensor([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        transform[1, :3, 3] = torch.tensor([4., -2., 3.])
        out = rigid_corners(baseline, self.rest, self.faces, self.selected, transform)
        original = baseline[:, self.faces]
        torch.testing.assert_close(out[:, 1], original[:, 1], rtol=0, atol=0)
        expected = torch.einsum("fij,tkj->ftki", transform[:, :3, :3], self.rest[self.faces[self.selected]]) + transform[:, None, None, :3, 3]
        torch.testing.assert_close(out[:, 0], expected[:, 0], rtol=0, atol=0)
        self.assertEqual(float((out[:, 1] - original[:, 1]).abs().max()), 0.0)

    def test_selected_edges_preserve_rigid_lengths(self):
        baseline = self.rest.unsqueeze(0).repeat(3, 1, 1)
        transforms = torch.eye(4).repeat(3, 1, 1)
        transforms[1, :3, 3] = torch.tensor([2., 3., -1.])
        transforms[2, :3, :3] = torch.tensor([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        transforms[2, :3, 3] = torch.tensor([-3., 1., 2.])
        out = rigid_corners(baseline, self.rest, self.faces, self.selected, transforms)
        edges = torch.linalg.vector_norm(out[:, 0, 1:] - out[:, 0, :1], dim=-1)
        rest_edges = torch.linalg.vector_norm(self.rest[self.faces[0, 1:]] - self.rest[self.faces[0, :1]], dim=-1)
        torch.testing.assert_close(edges, rest_edges.expand_as(edges), rtol=0, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
