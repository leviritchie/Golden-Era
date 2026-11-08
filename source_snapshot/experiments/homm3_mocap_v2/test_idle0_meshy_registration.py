"""Idle-0 Meshy registration: identity camera, identity bind, fail-closed overlap."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from idle0_meshy_registration import (
    MIN_BBOX_IOU,
    Idle0RegistrationError,
    capture_yaw_undo_deg,
    identity_height_match_camera,
    idle0_skeleton_similarity,
    mixamo_forward_yaw_deg,
    sprite_alpha_bbox,
    write_idle0_meshy_registration,
)
from inside_mesh_bind import (
    InsideMeshBindError,
    apply_bone_length_scales,
    bone_directions_match,
    fit_bone_lengths_inside_mesh,
    joints_entirely_inside,
)
from static_bind_registration import accepted_mesh_alignment, apply_similarity, rotation_matrix


class Idle0RegistrationTest(unittest.TestCase):
    def test_identity_height_match_accepts_overlapping_front_view(self):
        vertices = np.array([[x, y, 0.0] for x in (-0.4, 0.4) for y in (0.0, 1.6)])
        sprite = np.zeros((32, 32, 4), dtype=np.uint8)
        sprite[4:28, 8:24] = (255, 255, 255, 255)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "02_00.png"
            Image.fromarray(sprite, "RGBA").save(path)
            view = identity_height_match_camera(vertices, sprite_alpha_bbox(path))
        self.assertGreaterEqual(view["bboxIou"], MIN_BBOX_IOU)
        np.testing.assert_allclose(view["rotation"], np.eye(3))

    def test_thin_side_view_fails_closed(self):
        vertices = np.array([[x, y, 0.0] for x in (-0.03, 0.03) for y in (0.0, 1.6)])
        sprite = np.zeros((32, 32, 4), dtype=np.uint8)
        sprite[4:28, 4:28] = (255, 255, 255, 255)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "02_00.png"
            Image.fromarray(sprite, "RGBA").save(path)
            with self.assertRaisesRegex(Idle0RegistrationError, "bbox IoU"):
                identity_height_match_camera(vertices, sprite_alpha_bbox(path))

    def test_anaconda_tail_pair_reads_capture_yaw(self):
        names = ["Hips", "BN_Tail_04", "BN_Tail_10"]
        facing_z = np.array([[0.0, 0.0, 0.0], [1.0, 0.4, 0.0], [-1.0, 0.4, 0.0]], dtype=np.float64)
        self.assertAlmostEqual(mixamo_forward_yaw_deg(facing_z, names), 0.0, places=6)
        yawed = facing_z @ rotation_matrix(45.0, 0.0, 0.0).T
        self.assertAlmostEqual(mixamo_forward_yaw_deg(yawed, names), 45.0, places=5)

    def test_eagle_wing_pair_reads_capture_yaw(self):
        names = ["Hips", "BN_Wing_L_01", "BN_Wing_R_01"]
        facing_z = np.array([[0.0, 0.0, 0.0], [1.0, 1.2, 0.0], [-1.0, 1.2, 0.0]], dtype=np.float64)
        self.assertAlmostEqual(mixamo_forward_yaw_deg(facing_z, names), 0.0, places=6)
        yawed = facing_z @ rotation_matrix(45.0, 0.0, 0.0).T
        self.assertAlmostEqual(mixamo_forward_yaw_deg(yawed, names), 45.0, places=5)

    def test_mounted_prefixed_horse_pair_reads_capture_yaw(self):
        names = ["mount:Bip01_L_Thigh", "mount:Bip01_R_Thigh"]
        facing_z = np.array([[1.0, 0.8, 0.0], [-1.0, 0.8, 0.0]], dtype=np.float64)
        self.assertAlmostEqual(mixamo_forward_yaw_deg(facing_z, names), 0.0, places=6)
        yawed = facing_z @ rotation_matrix(45.0, 0.0, 0.0).T
        self.assertAlmostEqual(mixamo_forward_yaw_deg(yawed, names), 45.0, places=5)

    def test_mixamo_capture_yaw_undo_snaps_45_and_leaves_cardinal_alone(self):
        names = ["mixamorig:Hips", "mixamorig:LeftShoulder", "mixamorig:RightShoulder"]
        facing_z = np.array([[0.0, 0.0, 0.0], [1.0, 1.2, 0.0], [-1.0, 1.2, 0.0]], dtype=np.float64)
        self.assertAlmostEqual(mixamo_forward_yaw_deg(facing_z, names), 0.0, places=6)
        self.assertEqual(capture_yaw_undo_deg(0.2), 0.0)
        yawed = facing_z @ rotation_matrix(45.0, 0.0, 0.0).T
        self.assertAlmostEqual(mixamo_forward_yaw_deg(yawed, names), 45.0, places=5)
        self.assertEqual(capture_yaw_undo_deg(43.1), -45.0)
        self.assertEqual(capture_yaw_undo_deg(46.7), -45.0)

    def test_capture_45_yaw_is_undone_onto_camera_plus_z(self):
        names = ["mixamorig:Hips", "mixamorig:LeftShoulder", "mixamorig:RightShoulder"]
        rest = np.array([[0.0, 0.0, 0.0], [0.5, 1.2, 0.0], [-0.5, 1.2, 0.0]], dtype=np.float64)
        capture = rest @ rotation_matrix(45.0, 0.0, 0.0).T
        xs, ys, zs = np.meshgrid(
            np.linspace(-1.0, 1.0, 5),
            np.linspace(0.0, 1.6, 5),
            np.linspace(-0.4, 0.4, 4),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        undo = capture_yaw_undo_deg(mixamo_forward_yaw_deg(capture, names))
        skeleton = idle0_skeleton_similarity(capture, vertices, seed_yaw_deg=undo)
        self.assertAlmostEqual(skeleton["yawDeg"], -45.0, places=5)
        placed = apply_similarity(
            capture,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        placed_yaw = mixamo_forward_yaw_deg(placed, names)
        self.assertLess(abs(placed_yaw), 2.0)

    def test_skeleton_similarity_is_identity_rotation_and_inverts_into_capture(self):
        joints = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.5, 1.0, 0.2]])
        vertices = joints * 4.0 + np.array([1.0, 2.0, 3.0])
        skeleton = idle0_skeleton_similarity(joints, vertices)
        np.testing.assert_allclose(skeleton["rotation"], np.eye(3))
        placed = apply_similarity(
            joints,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        np.testing.assert_allclose(placed, vertices, atol=1e-9)

    def test_tall_skeleton_is_contained_not_diagonal_matched(self):
        joints = np.array([[0.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.4, 2.0, 0.0]])
        xs, ys, zs = np.meshgrid(np.linspace(-1.0, 1.0, 4), np.linspace(0.0, 2.0, 5), np.linspace(-1.0, 1.0, 4))
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        skeleton = idle0_skeleton_similarity(joints, vertices)
        placed = apply_similarity(
            joints,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        self.assertLess(skeleton["scale"], 1.0)
        np.testing.assert_array_less(placed.max(axis=0), vertices.max(axis=0) + 1e-9)
        np.testing.assert_array_less(vertices.min(axis=0) - 1e-9, placed.min(axis=0))

    def test_parentless_bind_retries_aabb_center_when_vertex_mean_is_outside(self):
        xs, ys, zs = np.meshgrid(
            np.linspace(-1.0, 1.0, 5),
            np.linspace(0.0, 2.0, 5),
            np.linspace(-1.0, 1.0, 5),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        # The mesh is still bounded by a centered box, but its tessellation is
        # heavily concentrated at the front-right corner. A mean-centered
        # parentless fit therefore ejects the left-side joint even though the
        # AABB-centered fit is valid.
        cluster = np.repeat(np.array([[0.9, 1.0, 0.9]], dtype=np.float64), 300, axis=0)
        vertices = np.concatenate([vertices, cluster], axis=0)
        joints = np.array(
            [
                [0.0, 0.5, 0.0],
                [0.0, 1.5, 0.0],
                [-0.5, 1.0, 0.0],
                [0.5, 1.0, 0.0],
            ],
            dtype=np.float64,
        )
        skeleton = idle0_skeleton_similarity(
            joints,
            vertices,
            fit="idle0_bind_first_inside_mesh",
        )
        self.assertEqual(skeleton["fit"], "idle0_bind_first_inside_mesh")
        self.assertEqual(skeleton["translationCenterPolicy"], "aabb_center_fallback")
        np.testing.assert_allclose(
            np.asarray(skeleton["translation"], dtype=np.float64),
            np.array([0.0, -1.0, 0.0]),
            atol=1e-9,
        )

    def _pyramid_mesh(self) -> np.ndarray:
        rings = []
        for y in np.linspace(0.0, 2.0, 11):
            half = 0.7 * (1.0 - y / 2.0) + 0.08
            for x in (-half, 0.0, half):
                for z in (-half, 0.0, half):
                    rings.append((x, y, z))
        return np.asarray(rings, dtype=np.float64)

    def test_tpose_arms_are_sucked_into_the_mesh(self):
        xs, ys, zs = np.meshgrid(
            np.linspace(-1.0, 1.0, 6),
            np.linspace(0.0, 2.0, 7),
            np.linspace(-1.0, 1.0, 6),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        joints = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 1.8, 0.0],
                [-0.25, 1.4, 0.0],
                [-0.85, 1.4, 0.0],
                [-1.15, 1.4, 0.0],
                [0.25, 1.4, 0.0],
                [0.85, 1.4, 0.0],
                [1.15, 1.4, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 1, 1, 3, 4, 1, 6, 7], dtype=np.int64)
        skeleton = idle0_skeleton_similarity(joints, vertices, parents)
        rest = np.asarray(skeleton["bindRestJoints"], dtype=np.float64)
        placed = apply_similarity(
            rest,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        self.assertEqual(skeleton["fit"], "idle0_floor_column_xz")
        self.assertEqual(skeleton["scalePolicy"], "floor_to_mesh_height")
        self.assertEqual(skeleton["containmentPolicy"], "floor_column_xz")
        self.assertGreaterEqual(len(skeleton["footIndices"]), 1)
        self.assertAlmostEqual(float(placed[skeleton["footIndices"], 1].min()), float(vertices[:, 1].min()), places=5)
        self.assertAlmostEqual(float(placed[:, 1].max()), float(vertices[:, 1].max()), places=5)
        np.testing.assert_allclose(rest[0], joints[0], atol=1e-9)
        self.assertEqual(skeleton["candidatesEvaluated"], 1)

    def test_bind_first_fit_is_opt_in_and_keeps_bind_rest(self):
        vertices = np.array(
            [
                [-1.0, 0.0, -1.0],
                [1.0, 0.0, -1.0],
                [1.0, 0.0, 1.0],
                [-1.0, 0.0, 1.0],
                [-1.0, 2.0, -1.0],
                [1.0, 2.0, -1.0],
                [1.0, 2.0, 1.0],
                [-1.0, 2.0, 1.0],
            ],
            dtype=np.float64,
        )
        joints = np.array(
            [
                [0.0, 0.8, 0.0],
                [-0.2, 0.1, 0.0],
                [0.2, 0.1, 0.0],
                [0.0, 1.5, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 0, 0], dtype=np.int64)
        skeleton = idle0_skeleton_similarity(
            joints, vertices, parents, fit="idle0_bind_first_inside_mesh"
        )
        self.assertEqual(skeleton["fit"], "idle0_bind_first_inside_mesh")
        self.assertEqual(skeleton["containmentPolicy"], "bind_first_inside_mesh")
        self.assertEqual(skeleton["scalePolicy"], "seed_first_uniform_shrink_last")
        rest = np.asarray(skeleton["bindRestJoints"], dtype=np.float64)
        np.testing.assert_allclose(rest[0], joints[0], atol=1e-9)
        np.testing.assert_allclose(skeleton["boneLengthScales"], 1.0)

    def test_bind_first_containment_mask_ignores_outside_graft(self):
        vertices = np.array(
            [
                [-1.0, 0.0, -1.0],
                [1.0, 0.0, -1.0],
                [1.0, 0.0, 1.0],
                [-1.0, 0.0, 1.0],
                [-1.0, 2.0, -1.0],
                [1.0, 2.0, -1.0],
                [1.0, 2.0, 1.0],
                [-1.0, 2.0, 1.0],
            ],
            dtype=np.float64,
        )
        joints = np.array(
            [
                [0.0, 0.8, 0.0],
                [-0.2, 0.1, 0.0],
                [0.2, 0.1, 0.0],
                [0.0, 1.5, 0.0],
                [4.0, 1.2, 4.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 0, 0, 0], dtype=np.int64)
        names = ["Hips", "LeftUpLeg", "RightUpLeg", "Head", "BN_Wing_L_01"]
        unmasked = idle0_skeleton_similarity(
            joints, vertices, parents, names=names, fit="idle0_bind_first_inside_mesh"
        )
        masked = idle0_skeleton_similarity(
            joints,
            vertices,
            parents,
            names=names,
            fit="idle0_bind_first_inside_mesh",
            containment_joint_names=names[:-1],
        )
        self.assertEqual(float(masked["yawDeg"]), 0.0)
        self.assertEqual(float(masked["pitchDeg"]), 0.0)
        self.assertEqual(float(masked["rollDeg"]), 0.0)
        self.assertEqual(masked["containmentJointNames"], names[:-1])
        self.assertGreater(float(masked["scale"]), float(unmasked["scale"]))

    def test_ground_height_fit_is_opt_in_and_does_not_edit_bones(self):
        vertices = np.array(
            [
                [-1.0, 0.0, -1.0],
                [1.0, 0.0, -1.0],
                [1.0, 0.0, 1.0],
                [-1.0, 0.0, 1.0],
                [-1.0, 2.0, -1.0],
                [1.0, 2.0, -1.0],
                [1.0, 2.0, 1.0],
                [-1.0, 2.0, 1.0],
            ],
            dtype=np.float64,
        )
        joints = np.array(
            [
                [0.0, 0.8, 0.0],
                [-0.3, 0.0, 0.0],
                [0.3, 0.0, 0.0],
                [0.0, 1.2, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 0, 0], dtype=np.int64)
        skeleton = idle0_skeleton_similarity(joints, vertices, parents, fit="idle0_ground_height")
        self.assertEqual(skeleton["fit"], "idle0_ground_height")
        self.assertEqual(skeleton["scalePolicy"], "floor_to_mesh_height_uniform")
        self.assertEqual(skeleton["containmentPolicy"], "ground_height_only")
        self.assertEqual(float(skeleton["extraYawDeg"]), 0.0)
        np.testing.assert_allclose(skeleton["boneLengthScales"], 1.0)
        self.assertLess(abs(float(skeleton["meanRestAngleDeg"])), 1e-5)
        rest = np.asarray(skeleton["bindRestJoints"], dtype=np.float64)
        np.testing.assert_allclose(rest[0], joints[0], atol=1e-9)
        placed = apply_similarity(
            rest,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        self.assertAlmostEqual(float(placed[skeleton["footIndices"], 1].min()), 0.0, places=5)
        self.assertAlmostEqual(float(placed[:, 1].max()), 2.0, places=5)
        with self.assertRaisesRegex(Idle0RegistrationError, "unknown idle-0 fit"):
            idle0_skeleton_similarity(joints, vertices, parents, fit="not_a_real_fit")

    def test_scale_to_ground_fit_does_not_drop_or_edit_bones(self):
        vertices = np.array(
            [
                [-1.0, 0.0, -1.0],
                [1.0, 0.0, -1.0],
                [1.0, 0.0, 1.0],
                [-1.0, 0.0, 1.0],
                [-1.0, 4.0, -1.0],
                [1.0, 4.0, -1.0],
                [1.0, 4.0, 1.0],
                [-1.0, 4.0, 1.0],
            ],
            dtype=np.float64,
        )
        joints = np.array(
            [
                [0.0, 0.0, 0.0],
                [-0.3, -0.5, 0.0],
                [0.3, -0.4, 0.0],
                [0.0, 0.6, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 0, 0], dtype=np.int64)
        base = {
            "rotation": np.eye(3).tolist(),
            "scale": 1.1,
            "translation": [0.0, 1.5, 0.0],
            "yawDeg": -45.0,
            "pitchDeg": 15.0,
            "rollDeg": 0.0,
        }
        skeleton = idle0_skeleton_similarity(
            joints, vertices, parents, fit="idle0_scale_to_ground", base_similarity=base
        )
        self.assertEqual(skeleton["fit"], "idle0_scale_to_ground")
        self.assertEqual(skeleton["scalePolicy"], "yawfix_origin_until_feet_on_floor")
        self.assertEqual(skeleton["containmentPolicy"], "scale_to_ground")
        self.assertEqual(float(skeleton["yawDeg"]), -45.0)
        self.assertEqual(float(skeleton["pitchDeg"]), 15.0)
        np.testing.assert_allclose(skeleton["boneLengthScales"], 1.0)
        self.assertLess(abs(float(skeleton["meanRestAngleDeg"])), 1e-5)
        rest = np.asarray(skeleton["bindRestJoints"], dtype=np.float64)
        np.testing.assert_allclose(rest[0], joints[0], atol=1e-9)
        placed = apply_similarity(
            rest,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        self.assertAlmostEqual(float(placed[skeleton["footIndices"], 1].min()), 0.0, places=5)
        np.testing.assert_allclose(placed[0], [0.0, 1.5, 0.0], atol=1e-6)
        with self.assertRaisesRegex(Idle0RegistrationError, "yaw-fix bind"):
            idle0_skeleton_similarity(joints, vertices, parents, fit="idle0_scale_to_ground")

    def test_length_fit_fails_closed_when_min_scale_still_outside(self):
        xs, ys, zs = np.meshgrid(
            np.linspace(-0.2, 0.2, 4),
            np.linspace(0.0, 2.0, 5),
            np.linspace(-0.2, 0.2, 4),
        )
        box = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        joints = np.array([[0.0, 1.0, 0.0], [3.0, 1.0, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0], dtype=np.int64)
        with self.assertRaises(InsideMeshBindError):
            fit_bone_lengths_inside_mesh(joints, parents, box)
        needle = []
        for y in np.linspace(0.0, 0.35, 4):
            for x in (-0.8, 0.8):
                for z in (-0.8, 0.8):
                    needle.append((x, y, z))
        for y in np.linspace(0.5, 2.0, 8):
            for x in (-0.02, 0.02):
                for z in (-0.02, 0.02):
                    needle.append((x, y, z))
        box = []
        for y in np.linspace(0.0, 2.0, 8):
            for x in (-0.8, 0.0, 0.8):
                for z in (-0.8, 0.0, 0.8):
                    box.append((x, y, z))
        tpose = np.array(
            [
                [0.0, 0.1, 0.0],
                [0.0, 1.0, 0.0],
                [-1.2, 1.4, 0.0],
                [1.2, 1.4, 0.0],
            ],
            dtype=np.float64,
        )
        tpose_parents = np.array([-1, 0, 1, 1], dtype=np.int64)
        skeleton = idle0_skeleton_similarity(tpose, np.asarray(box, dtype=np.float64), tpose_parents)
        rest = np.asarray(skeleton["bindRestJoints"], dtype=np.float64)
        placed = apply_similarity(
            rest,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        self.assertEqual(skeleton["fit"], "idle0_floor_column_xz")
        self.assertAlmostEqual(float(placed[skeleton["footIndices"], 1].min()), 0.0, places=5)
        self.assertAlmostEqual(float(placed[:, 1].max()), 2.0, places=5)
        self.assertLess(float(np.max(np.abs(placed[:, 0]))), 0.85)

    def test_uniform_scale_shrinks_only_after_seed_size_cannot_contain(self):
        joints = np.array(
            [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.4]],
            dtype=np.float64,
        )
        xs, ys, zs = np.meshgrid(
            np.linspace(-1.0, 1.0, 5),
            np.linspace(0.0, 2.0, 5),
            np.linspace(-0.5, 0.5, 4),
        )
        vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
        skeleton = idle0_skeleton_similarity(joints, vertices)
        self.assertLess(skeleton["scaleFactor"], 1.0)
        self.assertAlmostEqual(skeleton["scale"], skeleton["seed"]["scale"] * skeleton["scaleFactor"], places=9)
        placed = apply_similarity(
            joints,
            rotation=np.array(skeleton["rotation"]),
            scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        inside, _ = joints_entirely_inside(vertices, placed)
        self.assertTrue(inside)

    def test_shortened_rest_keeps_reconstructed_local_rotations(self):
        from reconstruct_ab import reconstruct_ab

        joints = np.array(
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.8, 1.0, 0.0]],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 1], dtype=np.int64)
        scales = np.array([1.0, 1.0, 0.55], dtype=np.float64)
        adjusted = apply_bone_length_scales(joints, parents, scales)
        self.assertTrue(bone_directions_match(joints, adjusted, parents))
        swung = joints.copy()
        delta = joints[2] - joints[1]
        angle = np.deg2rad(35.0)
        rotation = np.array(
            [[np.cos(angle), 0.0, np.sin(angle)], [0.0, 1.0, 0.0], [-np.sin(angle), 0.0, np.cos(angle)]],
            dtype=np.float64,
        )
        swung[2] = joints[1] + rotation @ delta
        capture = np.stack([joints, swung], axis=0)

        def offsets(points: np.ndarray) -> np.ndarray:
            values = points - points[np.clip(parents, 0, None)]
            values[0] = points[0]
            return values

        long_ab = reconstruct_ab(capture_positions=capture, offsets=offsets(joints), parents=parents)
        short_ab = reconstruct_ab(
            capture_positions=capture,
            offsets=offsets(adjusted),
            parents=parents,
            aim_offsets=offsets(joints),
        )
        np.testing.assert_allclose(long_ab["localRotation"], short_ab["localRotation"], atol=1e-8)
        np.testing.assert_allclose(short_ab["localRotation"][0], np.eye(3)[None].repeat(3, axis=0), atol=1e-8)

    def test_reaimed_rest_keeps_capture_relative_locals(self):
        from reconstruct_ab import reconstruct_ab

        capture_rest = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.8, 1.0, 0.0]], dtype=np.float64)
        bind_rest = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.6, 0.0]], dtype=np.float64)
        parents = np.array([-1, 0, 1], dtype=np.int64)
        swung = capture_rest.copy()
        angle = np.deg2rad(35.0)
        rotation = np.array(
            [[np.cos(angle), 0.0, np.sin(angle)], [0.0, 1.0, 0.0], [-np.sin(angle), 0.0, np.cos(angle)]],
            dtype=np.float64,
        )
        swung[2] = capture_rest[1] + rotation @ (capture_rest[2] - capture_rest[1])
        capture = np.stack([capture_rest, swung], axis=0)

        def offsets(points: np.ndarray) -> np.ndarray:
            values = points - points[np.clip(parents, 0, None)]
            values[0] = points[0]
            return values

        authentic = reconstruct_ab(
            capture_positions=capture, offsets=offsets(capture_rest), parents=parents
        )
        bind_first = reconstruct_ab(
            capture_positions=capture,
            offsets=offsets(bind_rest),
            parents=parents,
            aim_offsets=offsets(capture_rest),
        )
        np.testing.assert_allclose(authentic["localRotation"], bind_first["localRotation"], atol=1e-8)
        np.testing.assert_allclose(bind_first["positionsA"][0], bind_rest, atol=1e-8)

    def test_written_artifact_is_consumable_at_bind_frame_zero(self):
        vertices = np.array(
            [[x, y, z] for x in (-0.4, 0.4) for y in (0.0, 1.6) for z in (-0.2, 0.2)],
            dtype=np.float64,
        )
        joints = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.3, 1.2, 0.0],
                [0.0, 1.4, 0.0],
                [-0.3, 1.2, 0.0],
            ],
            dtype=np.float64,
        )
        parents = np.array([-1, 0, 1, 0], dtype=np.int64)
        names = [
            "mixamorig:Hips",
            "mixamorig:LeftShoulder",
            "mixamorig:Head",
            "mixamorig:RightShoulder",
        ]
        sprite = np.zeros((32, 32, 4), dtype=np.uint8)
        sprite[4:28, 8:24] = (255, 255, 255, 255)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            idle = root / "02_00.png"
            Image.fromarray(sprite, "RGBA").save(idle)
            mesh = root / "mesh.glb"
            capture = root / "capture.npz"
            mesh.write_bytes(b"mesh-bytes")
            np.savez(
                capture,
                joint_names=np.asarray(names),
                pred_position=joints[None],
                parents=parents,
            )
            path = root / "registration.json"
            payload = write_idle0_meshy_registration(
                output_path=path,
                unit="h3_example",
                mesh_path=mesh,
                mesh_vertices=vertices,
                capture_path=capture,
                capture_joints=joints,
                capture_parents=parents,
                idle_frame0=idle,
                bind_frame=0,
            )
            self.assertTrue(payload["acceptance"]["visualConfirmation"])
            self.assertEqual(payload["acceptance"]["confirmationKind"], "idle_frame0_meshy_source_identity")
            skeleton = payload["views"]["candidates"][0]["skeletonSimilarity"]
            self.assertEqual(len(skeleton["boneLengthScales"]), 4)
            self.assertEqual(len(skeleton["bindRestJoints"]), 4)
            self.assertEqual(skeleton["scalePolicy"], "floor_to_mesh_height")
            self.assertEqual(skeleton["containmentPolicy"], "floor_column_xz")
            self.assertIn("footIndices", skeleton)
            self.assertIn("feet_pinned_to_mesh_floor_then_scaled_to_mesh_top", payload["acceptance"]["reasons"])
            alignment = accepted_mesh_alignment(payload)
            self.assertEqual(alignment["selectedCandidateId"], "idle0_identity")
            with self.assertRaisesRegex(Idle0RegistrationError, "bind frame 0"):
                write_idle0_meshy_registration(
                    output_path=root / "bad.json",
                    unit="h3_example",
                    mesh_path=mesh,
                    mesh_vertices=vertices,
                    capture_path=capture,
                    capture_joints=joints,
                    capture_parents=parents,
                    idle_frame0=idle,
                    bind_frame=8,
                )

    def test_explicit_route_yaw_does_not_require_bilateral_names(self):
        vertices = np.array(
            [[x, y, z] for x in (-0.5, 0.5) for y in (0.0, 1.5) for z in (-0.3, 0.3)],
            dtype=np.float64,
        )
        joints = np.array(
            [[0.0, 0.0, 0.0], [0.0, 0.8, 0.0], [0.25, 1.2, 0.0]], dtype=np.float64
        )
        parents = np.array([-1, 0, 1], dtype=np.int64)
        names = ["Bone_000", "Bone_001", "Bone_002"]
        sprite = np.zeros((32, 32, 4), dtype=np.uint8)
        sprite[4:28, 8:24] = (255, 255, 255, 255)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            idle = root / "02_00.png"
            Image.fromarray(sprite, "RGBA").save(idle)
            mesh = root / "mesh.glb"
            capture = root / "capture.npz"
            mesh.write_bytes(b"mesh-bytes")
            np.savez(capture, joint_names=np.asarray(names), pred_position=joints[None], parents=parents)
            payload = write_idle0_meshy_registration(
                output_path=root / "registration.json",
                unit="h3_smartrig_example",
                mesh_path=mesh,
                mesh_vertices=vertices,
                capture_path=capture,
                capture_joints=joints,
                capture_parents=parents,
                idle_frame0=idle,
                bind_frame=0,
                explicit_capture_yaw_undo_deg=0.0,
                capture_yaw_policy="smartrig_orientation_node_inverse_yaw_90_mesh_frame",
            )
            skeleton = payload["views"]["candidates"][0]["skeletonSimilarity"]
            self.assertIsNone(skeleton["captureForwardYawDeg"])
            self.assertEqual(skeleton["captureYawUndoDeg"], 0.0)
            self.assertEqual(
                skeleton["captureYawPolicy"],
                "smartrig_orientation_node_inverse_yaw_90_mesh_frame",
            )
            self.assertIn("explicit_route_capture_orientation_applied", payload["acceptance"]["reasons"])


if __name__ == "__main__":
    unittest.main()
