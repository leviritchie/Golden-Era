"""Rest-length scales keep mocap bone directions and refuse leftover-outside binds."""
from __future__ import annotations

import unittest

import numpy as np

from inside_mesh_bind import (
    InsideMeshBindError,
    apply_bone_length_scales,
    body_vertex_mask,
    bone_directions_match,
    fit_bone_lengths_inside_mesh,
    fit_rest_inside_mesh,
    joints_entirely_inside,
    joints_inside_registered_source_view,
)
from static_bind_registration import accepted_bone_length_scales, invert_similarity, rotation_matrix


class InsideMeshBindTest(unittest.TestCase):
    def test_apply_scales_preserves_directions_and_shortens(self):
        joints = np.array([[0.0, 0.0, 0.0], [0.0, 2.0, 0.0], [2.0, 2.0, 0.0]])
        parents = np.array([-1, 0, 1])
        scales = np.array([1.0, 0.5, 0.25])
        placed = apply_bone_length_scales(joints, parents, scales)
        np.testing.assert_allclose(placed[0], joints[0])
        np.testing.assert_allclose(placed[1], [0.0, 1.0, 0.0])
        np.testing.assert_allclose(placed[2], [0.5, 1.0, 0.0])
        self.assertTrue(bone_directions_match(joints, placed, parents))

    def test_missing_length_scales_mean_identity_not_a_guessed_fit(self):
        payload = {
            "acceptance": {"selectedCandidateId": "selected"},
            "views": {"candidates": [{"id": "selected", "skeletonSimilarity": {"scale": 1.0}}]},
        }
        np.testing.assert_allclose(accepted_bone_length_scales(payload, 3), [1.0, 1.0, 1.0])

    def test_wrong_length_scale_count_is_rejected(self):
        payload = {
            "acceptance": {"selectedCandidateId": "selected"},
            "views": {
                "candidates": [{
                    "id": "selected",
                    "skeletonSimilarity": {"boneLengthScales": [1.0, 0.5]},
                }]
            },
        }
        with self.assertRaisesRegex(ValueError, "boneLengthScales"):
            accepted_bone_length_scales(payload, 3)

    def test_fit_shortens_into_pyramid_slab(self):
        rings = []
        for y in np.linspace(0.0, 2.0, 11):
            half = 0.7 * (1.0 - y / 2.0) + 0.08
            for x in (-half, 0.0, half):
                for z in (-half, 0.0, half):
                    rings.append((x, y, z))
        vertices = np.asarray(rings, dtype=np.float64)
        joints = np.array([[0.0, 0.0, 0.0], [0.0, 1.4, 0.0], [1.2, 1.4, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0, 1], dtype=np.int64)
        fitted = fit_bone_lengths_inside_mesh(joints, parents, vertices)
        self.assertLess(float(fitted["scales"][2]), 1.0)
        self.assertTrue(bone_directions_match(joints, fitted["joints"], parents))
        inside, _ = joints_entirely_inside(vertices, fitted["joints"])
        self.assertTrue(inside)

    def test_bind_first_may_change_rest_angles_to_enter_the_mesh(self):
        rings = []
        for y in np.linspace(0.0, 2.0, 11):
            for x in (-0.12, 0.0, 0.12):
                for z in (-0.12, 0.0, 0.12):
                    rings.append((x, y, z))
        vertices = np.asarray(rings, dtype=np.float64)
        joints = np.array([[0.0, 0.0, 0.0], [0.0, 1.2, 0.0], [1.1, 1.2, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0, 1], dtype=np.int64)
        with self.assertRaises(InsideMeshBindError):
            fit_bone_lengths_inside_mesh(joints, parents, vertices)
        fitted = fit_rest_inside_mesh(joints, parents, vertices)
        self.assertGreater(float(fitted["meanRestAngleDeg"]), 1.0)
        inside, _ = joints_entirely_inside(vertices, fitted["joints"])
        self.assertTrue(inside)
        self.assertGreater(float(fitted["bodySaturation"]), 0.0)
        self.assertEqual(fitted["policy"], "bind_first_inside_mesh_saturate_non_weapon_body")

    def _box_with_face_triangles(self, lo, hi):
        corners = np.array(
            [
                [lo[0], lo[1], lo[2]],
                [hi[0], lo[1], lo[2]],
                [hi[0], hi[1], lo[2]],
                [lo[0], hi[1], lo[2]],
                [lo[0], lo[1], hi[2]],
                [hi[0], lo[1], hi[2]],
                [hi[0], hi[1], hi[2]],
                [lo[0], hi[1], hi[2]],
            ],
            dtype=np.float64,
        )
        tris = np.array(
            [
                [0, 1, 2], [0, 2, 3],
                [4, 6, 5], [4, 7, 6],
                [0, 4, 5], [0, 5, 1],
                [3, 2, 6], [3, 6, 7],
                [0, 3, 7], [0, 7, 4],
                [1, 5, 6], [1, 6, 2],
            ],
            dtype=np.int64,
        )
        return corners, tris

    def test_body_bones_lengthen_to_saturate_unused_flesh(self):
        xs, ys, zs = np.meshgrid(
            np.linspace(-0.6, 0.6, 5),
            np.linspace(0.0, 2.0, 9),
            np.linspace(-0.4, 0.4, 4),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        joints = np.array([[0.0, 0.2, 0.0], [0.0, 0.55, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0], dtype=np.int64)
        fitted = fit_rest_inside_mesh(joints, parents, vertices)
        self.assertGreater(float(fitted["joints"][1, 1]), 1.2)
        self.assertGreater(float(fitted["bodySaturation"]), 0.30)
        inside, _ = joints_entirely_inside(vertices, fitted["joints"])
        self.assertTrue(inside)

    def test_saturation_ignores_thin_weapon_spike(self):
        body, body_tris = self._box_with_face_triangles((-1.0, 0.0, -0.45), (1.0, 2.0, 0.45))
        stick, stick_tris = self._box_with_face_triangles((1.85, 0.97, -0.025), (3.4, 1.03, 0.025))
        xs, ys, zs = np.meshgrid(
            np.linspace(-0.8, 0.8, 4),
            np.linspace(0.2, 1.8, 5),
            np.linspace(-0.3, 0.3, 3),
        )
        interior = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        vertices = np.concatenate([body, interior, stick], axis=0)
        triangles = np.concatenate([body_tris, stick_tris + len(body) + len(interior)], axis=0)
        mask = body_vertex_mask(vertices, triangles)
        self.assertTrue(bool(mask[: len(body) + len(interior)].mean() > 0.9))
        self.assertFalse(bool(mask[len(body) + len(interior) + 4 :].any()))
        joints = np.array([[0.0, 0.4, 0.0], [0.25, 1.0, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0], dtype=np.int64)
        names = ["mixamorig:Hips", "mixamorig:LeftHand"]
        fitted = fit_rest_inside_mesh(joints, parents, vertices, triangles, names=names)
        self.assertLess(float(fitted["joints"][1, 0]), 1.25)
        self.assertGreater(float(fitted["joints"][1, 0]), 0.4)
        self.assertEqual(int(fitted["weaponVertexCount"]), int((~mask).sum()))

    def test_foot_cannot_sit_in_the_knee(self):
        torso, torso_t = self._box_with_face_triangles((-0.45, 1.05, -0.28), (0.45, 2.05, 0.28))
        shin, shin_t = self._box_with_face_triangles((0.08, 0.34, -0.09), (0.24, 1.08, 0.09))
        foot, foot_t = self._box_with_face_triangles((-0.02, 0.0, -0.14), (0.38, 0.36, 0.16))
        interiors = []
        for lo, hi, counts in (
            ((-0.35, 1.15, -0.18), (0.35, 1.95, 0.18), (4, 5, 3)),
            ((0.10, 0.40, -0.05), (0.22, 1.00, 0.05), (2, 5, 2)),
            ((0.02, 0.04, -0.08), (0.32, 0.30, 0.10), (4, 3, 3)),
        ):
            xs, ys, zs = np.meshgrid(
                np.linspace(lo[0], hi[0], counts[0]),
                np.linspace(lo[1], hi[1], counts[1]),
                np.linspace(lo[2], hi[2], counts[2]),
            )
            interiors.append(np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1))
        interior = np.concatenate(interiors, axis=0)
        vertices = np.concatenate([torso, shin, foot, interior], axis=0)
        triangles = np.concatenate(
            [
                torso_t,
                shin_t + len(torso),
                foot_t + len(torso) + len(shin),
            ],
            axis=0,
        )
        names = ["mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot"]
        joints = np.array(
            [
                [0.0, 1.55, 0.0],
                [0.12, 1.38, 0.0],
                [0.14, 1.20, 0.0],
                [0.15, 1.10, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 1, 2], dtype=np.int64)
        self.assertLess(float(joints[3, 1] - joints[2, 1]), 0.15)
        fitted = fit_rest_inside_mesh(joints, parents, vertices, triangles, names=names)
        knee = fitted["joints"][2]
        ankle = fitted["joints"][3]
        self.assertGreater(float(knee[1] - ankle[1]), 0.35)
        self.assertLess(float(ankle[1]), 0.45)
        self.assertEqual(fitted["policy"], "bind_first_inside_mesh_anatomical_slots")

    def test_raster_hull_point_check_does_not_scan_every_vertex(self):
        from inside_mesh_bind import MeshContainment

        box, tris = self._box_with_face_triangles((-1.0, 0.0, -1.0), (1.0, 2.0, 1.0))
        hull = MeshContainment(box, tris)
        inside = np.array([0.0, 1.0, 0.0])
        outside = np.array([2.0, 1.0, 0.0])
        self.assertTrue(hull.point_inside(inside))
        self.assertFalse(hull.point_inside(outside))
        self.assertTrue(hull.segment_inside(inside, np.array([0.2, 1.2, 0.0])))
        self.assertFalse(hull.segment_inside(inside, outside))

    def test_raster_hull_accepts_boundary_rounding_within_inside_slack(self):
        from inside_mesh_bind import MeshContainment

        box, tris = self._box_with_face_triangles((-1.0, 0.0, -1.0), (1.0, 2.0, 1.0))
        hull = MeshContainment(box, tris)
        self.assertTrue(hull.point_inside(np.array([1.0 + 0.5e-9, 1.0, 1.0 + 0.5e-9])))
        self.assertFalse(hull.point_inside(np.array([1.0 + 2.0e-9, 1.0, 1.0])))

    def test_source_view_containment_survives_capture_yaw(self):
        xs, ys, zs = np.meshgrid(
            np.linspace(-1.2, 1.2, 5),
            np.linspace(0.0, 2.0, 5),
            np.linspace(-0.35, 0.35, 4),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        mesh_joints = np.array([[0.0, 0.2, 0.0], [1.05, 1.0, 0.0]], dtype=np.float64)
        self.assertTrue(joints_entirely_inside(vertices, mesh_joints)[0])
        yaw = rotation_matrix(-45.0, 0.0, 0.0)
        scale = 1.75
        translation = np.array([0.1, 0.2, -0.3], dtype=np.float64)
        rest = invert_similarity(mesh_joints, rotation=yaw, scale=scale, translation=translation)
        capture_mesh = invert_similarity(vertices, rotation=yaw, scale=scale, translation=translation)
        self.assertFalse(joints_entirely_inside(capture_mesh, rest)[0])
        inside, _ = joints_inside_registered_source_view(
            vertices,
            rest,
            mesh_rotation=np.eye(3),
            skeleton_rotation=yaw,
            scale=scale,
            translation=translation,
        )
        self.assertTrue(inside)


if __name__ == "__main__":
    unittest.main()
