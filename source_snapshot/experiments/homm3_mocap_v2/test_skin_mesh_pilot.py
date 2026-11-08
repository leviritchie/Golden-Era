"""Shared rest geometry remains compatible with immutable bone transforms."""
import unittest
import torch

from run_skin_mesh_pilot import deform, validate_capture_indices, project_mesh_step, rest_barrier, _training_regions, expand_camera_to_full_canvas
from skin_mesh_field import MeshField
from skin_surface_constraints import SurfaceConstraints, rest_mesh_gate


class SharedMeshTests(unittest.TestCase):
    def test_explicit_region_support_reaches_training_field(self):
        from unittest.mock import patch
        from run_skin_mesh_pilot import make_asset_field
        skin = dict(vertices=[], triangles=[], weights=[], regions=[], names=['root', 'hub'])
        original = {'body': ('root', 'hub')}
        canonical = {'body': ('hub',)}
        with patch('run_skin_mesh_pilot.get_profile', return_value={'regionJoints': original}), \
             patch('run_skin_mesh_pilot.WeightField') as factory:
            make_asset_field('test', skin, ('body',), region_joints=canonical)
            self.assertEqual(factory.call_args.args[5], canonical)
            make_asset_field('test', skin, ('body',))
            self.assertEqual(factory.call_args.args[5], original)

    def test_ownership_seam_vertices_are_frozen_for_weight_training(self):
        from unittest.mock import patch
        from run_skin_mesh_pilot import make_asset_field
        skin = dict(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], triangles=[[0, 1, 2]],
                    weights=[], regions=[], names=['root'],
                    ownershipBoundaryPairs=[[0, 3], [0, 3]])
        with patch('run_skin_mesh_pilot.get_profile', return_value={'regionJoints': {'body': ('root',)}}), \
             patch('run_skin_mesh_pilot.WeightField') as factory:
            make_asset_field('test', skin, ('body',))
            frozen = factory.call_args.kwargs['frozen_vertices']
            self.assertEqual(sorted(int(v) for v in frozen), [0, 1, 2, 3])

    def test_unknown_bind_mode_rejected_before_work(self):
        from pathlib import Path
        from run_skin_mesh_pilot import run
        with self.assertRaisesRegex(ValueError, 'bind mode'):
            run(Path('unused'), Path('unused'), Path('unused'), bind_mode='automatic')

    def test_camera_expansion_uses_full_landscape_canvas(self):
        camera = {"sourceSize": [120, 80], "sourceCrop": {"left": 10, "top": 0, "size": 80},
                  "resolution": 112, "scale": 2., "offset": [30., 40.]}
        expanded = expand_camera_to_full_canvas(camera)
        self.assertEqual(expanded["sourceCrop"], {"left": 0, "top": -20, "size": 120})
        self.assertEqual(expanded["resolution"], 224)
        self.assertAlmostEqual(expanded["offset"][0], 30 * (80 / 120) * (223 / 111) + 10 * 223 / 120)

    def test_camera_expansion_uses_full_portrait_canvas(self):
        camera = {"sourceSize": [1064, 1085], "sourceCrop": {"left": 0, "top": 10, "size": 1064},
                  "resolution": 112, "scale": 2., "offset": [30., 40.]}
        expanded = expand_camera_to_full_canvas(camera)
        self.assertEqual(expanded["sourceCrop"], {"left": -10, "top": 0, "size": 1085})
        self.assertEqual(expanded["resolution"], 224)
        self.assertAlmostEqual(expanded["offset"][0], 30 * (1064 / 1085) * (223 / 111) + 10 * 223 / 1085)

    def test_non_roc_training_regions_exclude_rigid_attachments(self):
        skin = {"regions": ["torso", "weapon", "arm_left"]}
        profile = {"regionJoints": {"torso": (), "weapon": (), "arm_left": ()},
                   "rigidAttachments": ({"region": "weapon"},)}
        from unittest.mock import patch
        with patch("run_skin_mesh_pilot.get_profile", return_value=profile):
            self.assertEqual(_training_regions("h3_behemoth", skin), ("torso", "arm_left"))

    def test_rest_barrier_identity_gradient_and_boundary_cost(self):
        original = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        surface = SurfaceConstraints(original, [[0, 1, 2]])
        vertices = original.clone().requires_grad_()
        loss = rest_barrier(vertices, surface)
        loss.backward()
        self.assertTrue(torch.isfinite(vertices.grad).all())
        self.assertLess(float(loss.detach()), 1e-5)
        self.assertGreater(float(rest_barrier(original * 1.24, surface)), .5)

    def test_context_mapping_keeps_authored_boundaries(self):
        entry = {"contextBeforeCount": 8, "contextAfterCount": 8, "frames": ["a", "b", "c"], "sourceIndices": [8, 9, 10], "referenceIndex": 0}
        validate_capture_indices(entry, 19)
        for bad in ([-3, -2, -1], [0, 1, 2], [8, 10]):
            with self.assertRaises(ValueError):
                validate_capture_indices(dict(entry, sourceIndices=bad), 19)

    def test_mesh_projection_keeps_rest_surface_feasible(self):
        vertices = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]
        field = MeshField(vertices, ["body"] * 3, (), max_displacement_fraction=.5)
        surface = SurfaceConstraints(vertices, [[0, 1, 2]])
        previous = field.control.detach().clone()
        with torch.no_grad():
            field.control[:, 0] = torch.linspace(-4, 4, len(field.control))
        fraction = project_mesh_step(field, surface, previous)
        self.assertLess(fraction, 1)
        self.assertTrue(rest_mesh_gate(vertices, field.vertices(), [[0, 1, 2]], max_displacement_fraction=.5)["ok"])

    def test_identity_and_translation_with_mesh_gradients(self):
        vertices = torch.tensor([[1., 2., 3.], [-1., 0., 2.]], requires_grad=True)
        weights = torch.tensor([[.2, .8], [.7, .3]], requires_grad=True)
        transforms = torch.eye(4)[None, None, :3].repeat(2, 2, 1, 1)
        transforms[1, :, 0, 3] = 2
        result = deform(transforms, weights, vertices)
        torch.testing.assert_close(result[0], vertices)
        torch.testing.assert_close(result[1], vertices + torch.tensor([2., 0., 0.]))
        result.square().sum().backward()
        self.assertTrue(torch.isfinite(vertices.grad).all())
        self.assertTrue(torch.isfinite(weights.grad).all())
        self.assertFalse(transforms.requires_grad)


if __name__ == "__main__":
    unittest.main()
