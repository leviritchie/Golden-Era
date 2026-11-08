"""Static bind: registration math, anatomy gates, and unverified-consumption refusal."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from donor_eagle import bind_world_matrices
from prepare_move_bind_capture_bind import prepare_move_bind_capture_bind
from static_bind_registration import (
    SCHEMA,
    StaticRegistrationError,
    apply_similarity,
    branch_placement_report,
    canonical_source_view_basis,
    decide_static_outcome,
    distinct_view_candidates,
    evaluate_rigid_compatibility,
    invert_similarity,
    joint_groups,
    misplaced_skeleton_inside_bbox_rejected,
    nearest_bone_weights,
    project_direction,
    project_points,
    require_accepted_static_registration,
    rest_lbs_identity_error,
    rotation_geodesic_deg,
    rotation_matrix,
    source_matches_render_canvas,
)


REGION = {
    "torso": ("Hips", "Spine"),
    "neck_head": ("Neck", "Head"),
    "wing_left": ("Wing_L_01", "Wing_L_02"),
    "wing_right": ("Wing_R_01", "Wing_R_02"),
    "leg_left": ("Thigh_L",),
    "leg_right": ("Thigh_R",),
}
NAMES = [
    "Hips",
    "Spine",
    "Neck",
    "Head",
    "Wing_L_01",
    "Wing_L_02",
    "Wing_R_01",
    "Wing_R_02",
    "Thigh_L",
    "Thigh_R",
]


def _standing_mesh() -> np.ndarray:
    """Tall folded-wing hull: long in Y, short in X/Z."""
    xs, ys, zs = np.meshgrid(
        np.linspace(-0.25, 0.25, 5),
        np.linspace(0.0, 2.0, 9),
        np.linspace(-0.2, 0.2, 4),
    )
    return np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)


def _clustered_joints() -> np.ndarray:
    """All bones sit near the torso core. BBox-inside, anatomically wrong for wings."""
    return np.asarray(
        [
            [0.00, 0.40, 0.00],
            [0.00, 0.70, 0.00],
            [0.00, 0.95, 0.00],
            [0.00, 1.15, 0.00],
            [0.04, 0.80, 0.00],
            [0.08, 0.82, 0.00],
            [-0.04, 0.80, 0.00],
            [-0.08, 0.82, 0.00],
            [0.06, 0.20, 0.00],
            [-0.06, 0.20, 0.00],
        ],
        dtype=np.float64,
    )


def _spread_wing_joints() -> np.ndarray:
    """Flyer rest: body along Y, wings far along X."""
    return np.asarray(
        [
            [0.00, 0.40, 0.00],
            [0.00, 0.80, 0.00],
            [0.00, 1.10, 0.00],
            [0.00, 1.35, 0.00],
            [0.60, 0.90, 0.00],
            [1.40, 0.95, 0.00],
            [-0.60, 0.90, 0.00],
            [-1.40, 0.95, 0.00],
            [0.10, 0.10, 0.00],
            [-0.10, 0.10, 0.00],
        ],
        dtype=np.float64,
    )


def _accepted_payload(*, mesh: str, capture: str, bind_frame: int) -> dict:
    return {
        "schema": SCHEMA,
        "bindFrame": bind_frame,
        "inputHashes": {"mesh": mesh, "capture": capture},
        "views": {"candidates": [{
            "id": "fixture",
            "meshToSourceView": {"rotation": np.eye(3).tolist()},
            "skeletonSimilarity": {"rotation": np.eye(3).tolist(), "scale": 1.0, "translation": [0, 0, 0]},
        }]},
        "acceptance": {
            "selectedCandidateId": "fixture",
            "status": "accepted",
            "accepted": True,
            "visualConfirmation": True,
            "consumable": True,
        },
    }


class SimilarityAndProjectionTest(unittest.TestCase):
    def test_similarity_round_trip(self) -> None:
        points = np.asarray([[0.0, 0.0, 0.0], [1.0, 2.0, -0.5], [0.3, -1.1, 0.8]])
        rotation = rotation_matrix(37.0, -12.0, 8.0)
        scale = 2.4
        translation = np.asarray([0.5, -0.25, 1.1])
        placed = apply_similarity(points, rotation=rotation, scale=scale, translation=translation)
        recovered = invert_similarity(placed, rotation=rotation, scale=scale, translation=translation)
        self.assertTrue(np.allclose(recovered, points, atol=1e-12))

    def test_canonical_basis_projects_lateral_and_up(self) -> None:
        basis = canonical_source_view_basis()
        self.assertTrue(np.allclose(project_direction(np.array([1.0, 0.0, 0.0]), basis=basis), [1.0, 0.0]))
        self.assertTrue(np.allclose(project_direction(np.array([0.0, 1.0, 0.0]), basis=basis), [0.0, -1.0]))
        with self.assertRaisesRegex(ValueError, "parallel"):
            project_direction(np.array([0.0, 0.0, 1.0]), basis=basis)

    def test_rotated_facing_projects_to_expected_screen_axis(self) -> None:
        basis = canonical_source_view_basis()
        yaw90 = rotation_matrix(90.0, 0.0, 0.0)
        facing = yaw90 @ np.array([0.0, 0.0, 1.0])
        self.assertTrue(np.allclose(project_direction(facing, basis=basis), [1.0, 0.0], atol=1e-12))

    def test_source_and_render_must_share_one_canvas(self) -> None:
        source = np.zeros((8, 8, 3))
        source_matches_render_canvas(source, source.copy())
        with self.assertRaisesRegex(ValueError, "share one canvas"):
            source_matches_render_canvas(source, np.zeros((16, 16, 3)))

    def test_projected_points_follow_scale_and_translation(self) -> None:
        basis = canonical_source_view_basis()
        points = np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        pixels = project_points(points, basis=basis, scale=10.0, offset=np.array([3.0, 4.0]))
        self.assertTrue(np.allclose(pixels[0], [3.0, 4.0]))
        self.assertTrue(np.allclose(pixels[1], [23.0, 4.0]))


class AnatomyGateTest(unittest.TestCase):
    def test_bbox_inside_clustered_wings_are_rejected(self) -> None:
        vertices = _standing_mesh()
        joints = _clustered_joints()
        groups = joint_groups(NAMES, REGION)
        result = misplaced_skeleton_inside_bbox_rejected(
            vertices=vertices, joints=joints, names=NAMES, groups=groups
        )
        self.assertTrue(result["bboxInside"])
        self.assertFalse(result["compatibility"]["compatibleUnderRigidAlignment"])
        self.assertEqual(
            result["compatibility"]["reason"],
            "capture_mesh_bind_pose_incompatible_under_rigid_alignment",
        )

    def test_spread_wings_are_incompatible_with_folded_hull(self) -> None:
        vertices = _standing_mesh()
        joints = _spread_wing_joints()
        groups = joint_groups(NAMES, REGION)
        placement = branch_placement_report(joints=joints, names=NAMES, vertices=vertices, groups=groups)
        compatibility = evaluate_rigid_compatibility(
            joints=joints, names=NAMES, vertices=vertices, groups=groups, placement=placement
        )
        self.assertFalse(compatibility["compatibleUnderRigidAlignment"])
        self.assertGreater(compatibility["wingSpanOverMeshWidth"], 1.35)
        self.assertTrue(compatibility["bboxContainmentIsNotAcceptance"])

    def test_zero_lbs_rest_error_is_not_anatomical_alignment(self) -> None:
        vertices = _standing_mesh()
        joints = _clustered_joints()
        parents = np.asarray([-1, 0, 1, 2, 1, 4, 1, 6, 0, 0], dtype=np.int64)
        weights = nearest_bone_weights(vertices, joints)
        error = rest_lbs_identity_error(vertices, weights, joints, parents)
        self.assertLess(error, 1e-9)
        groups = joint_groups(NAMES, REGION)
        placement = branch_placement_report(joints=joints, names=NAMES, vertices=vertices, groups=groups)
        compatibility = evaluate_rigid_compatibility(
            joints=joints, names=NAMES, vertices=vertices, groups=groups, placement=placement
        )
        self.assertFalse(compatibility["compatibleUnderRigidAlignment"])
        self.assertTrue(placement["bbox"]["jointsInside"])
        world = bind_world_matrices(joints - joints[parents.clip(0)], parents)
        self.assertTrue(np.isfinite(world).all())


class ViewAndOutcomeTest(unittest.TestCase):
    def test_keeps_distinct_views_and_flags_near_tie(self) -> None:
        scored = [
            {"rotation": rotation_matrix(0, 0, 0), "iou": 0.71, "total": 0.40},
            {"rotation": rotation_matrix(8, 0, 0), "iou": 0.70, "total": 0.41},
            {"rotation": rotation_matrix(180, 0, 0), "iou": 0.69, "total": 0.42},
            {"rotation": rotation_matrix(90, 0, 0), "iou": 0.40, "total": 0.90},
        ]
        views = distinct_view_candidates(scored)
        self.assertGreaterEqual(len(views["candidates"]), 2)
        self.assertTrue(views["ambiguousOrientation"])
        self.assertFalse(views["selectedAutomatically"])
        self.assertGreater(
            rotation_geodesic_deg(views["candidates"][0]["rotation"], views["candidates"][1]["rotation"]),
            25.0,
        )

    def test_single_mode_stays_pending_visual(self) -> None:
        views = {
            "ambiguousOrientation": False,
            "candidates": [{"rotation": rotation_matrix(0, 0, 0), "iou": 0.8}],
        }
        compatible = {
            "compatibleUnderRigidAlignment": True,
            "reason": "rigid_alignment_not_visually_confirmed",
        }
        outcome = decide_static_outcome(views=views, compatibility_by_view=[compatible])
        self.assertEqual(outcome["status"], "pending_visual_confirmation")
        self.assertFalse(outcome["accepted"])
        self.assertFalse(outcome["visualConfirmation"])
        self.assertFalse(outcome["consumable"])

    def test_all_incompatible_views_report_bind_pose_incompatibility(self) -> None:
        views = {"ambiguousOrientation": False, "candidates": [{"iou": 0.6}]}
        outcome = decide_static_outcome(
            views=views,
            compatibility_by_view=[
                {"compatibleUnderRigidAlignment": False, "reason": "capture_mesh_bind_pose_incompatible_under_rigid_alignment"}
            ],
        )
        self.assertEqual(outcome["status"], "incompatible_bind_pose")
        self.assertTrue(outcome["doesNotProveMeshUnusable"])
        self.assertIn("rest_skeleton_or_capture_retarget", outcome["nextTaskIfIncompatible"])

    def test_ambiguity_wins_over_incompatibility(self) -> None:
        views = {"ambiguousOrientation": True, "candidates": [{}, {}]}
        outcome = decide_static_outcome(
            views=views,
            compatibility_by_view=[{"compatibleUnderRigidAlignment": False}],
        )
        self.assertEqual(outcome["status"], "ambiguous_orientation")


class ConsumptionGateTest(unittest.TestCase):
    def test_missing_artifact_is_refused(self) -> None:
        with self.assertRaisesRegex(StaticRegistrationError, "accepted static registration"):
            require_accepted_static_registration(
                None, mesh_sha256="a", capture_sha256="b", bind_frame=0
            )

    def test_pending_and_incompatible_are_not_consumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            for status in ("pending_visual_confirmation", "incompatible_bind_pose", "ambiguous_orientation"):
                path.write_text(
                    json.dumps(
                        {
                            "schema": SCHEMA,
                            "bindFrame": 0,
                            "inputHashes": {"mesh": "m", "capture": "c"},
                            "acceptance": {
                                "status": status,
                                "accepted": False,
                                "visualConfirmation": False,
                                "consumable": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(StaticRegistrationError, "not accepted"):
                    require_accepted_static_registration(path, mesh_sha256="m", capture_sha256="c", bind_frame=0)

    def test_accepted_without_visual_confirmation_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "bindFrame": 0,
                        "inputHashes": {"mesh": "m", "capture": "c"},
                        "acceptance": {
                            "status": "accepted",
                            "accepted": True,
                            "visualConfirmation": False,
                            "consumable": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(StaticRegistrationError, "not accepted"):
                require_accepted_static_registration(path, mesh_sha256="m", capture_sha256="c", bind_frame=0)

    def test_hash_and_frame_mismatch_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            path.write_text(json.dumps(_accepted_payload(mesh="m", capture="c", bind_frame=0)), encoding="utf-8")
            with self.assertRaisesRegex(StaticRegistrationError, "mesh hash"):
                require_accepted_static_registration(path, mesh_sha256="other", capture_sha256="c", bind_frame=0)
            with self.assertRaisesRegex(StaticRegistrationError, "capture hash"):
                require_accepted_static_registration(path, mesh_sha256="m", capture_sha256="other", bind_frame=0)
            with self.assertRaisesRegex(StaticRegistrationError, "bind frame"):
                require_accepted_static_registration(path, mesh_sha256="m", capture_sha256="c", bind_frame=3)

    def test_matching_accepted_artifact_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            payload = _accepted_payload(mesh="m", capture="c", bind_frame=0)
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = require_accepted_static_registration(path, mesh_sha256="m", capture_sha256="c", bind_frame=0)
            self.assertEqual(loaded["schema"], SCHEMA)

    def test_prepare_refuses_before_writing_bind_glb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = root / "mesh.glb"
            mesh.write_bytes(b"not-a-glb")
            capture = root / "cap.npz"
            np.savez(
                capture,
                joint_names=np.array(["Hips"], dtype="U"),
                parents=np.array([-1], dtype=np.int64),
                pred_position=np.zeros((1, 1, 3)),
            )
            out = root / "bind.glb"
            with self.assertRaises(StaticRegistrationError):
                prepare_move_bind_capture_bind(
                    mesh_glb=mesh, capture_path=capture, out_glb=out, bind_frame=0, unit="h3_roc"
                )
            self.assertFalse(out.exists())
            self.assertFalse(out.with_suffix(".report.json").exists())


class DeclaredBranchCompatibilityTests(unittest.TestCase):
    def fixture(self):
        vertices = np.array([[x, y, z] for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)])
        groups = {"torso": [0], "arm_left": [1], "arm_right": [2], "mount_front_leg": [3]}
        placement = {"branches": {name: {"meanSurfaceDistance": .1, "maxSurfaceDistance": .2}
                                  for name in groups}}
        return dict(joints=np.zeros((4, 3)), names=list(groups), vertices=vertices,
                    groups=groups, placement=placement)

    def test_nonwing_branches_do_not_require_fake_wings(self):
        result = evaluate_rigid_compatibility(**self.fixture())
        self.assertTrue(result["compatibleUnderRigidAlignment"])
        self.assertFalse(result["wingChecksApplied"])
        self.assertEqual(set(result["declaredBranchScreen"]["branches"]),
                         {"torso", "arm_left", "arm_right", "mount_front_leg"})
        self.assertEqual(result["reason"], "rigid_alignment_not_visually_confirmed")
        outcome = decide_static_outcome(views={"ambiguousOrientation": False}, compatibility_by_view=[result])
        self.assertFalse(outcome["accepted"])
        self.assertFalse(outcome["consumable"])

    def test_every_declared_branch_is_checked_scale_independently(self):
        for name in self.fixture()["groups"]:
            data = self.fixture()
            data["placement"]["branches"][name]["maxSurfaceDistance"] = 2.
            result = evaluate_rigid_compatibility(**data)
            self.assertFalse(result["compatibleUnderRigidAlignment"])
            self.assertEqual(result["declaredBranchScreen"]["failedBranches"], [name])
            data["vertices"] *= 10
            for row in data["placement"]["branches"].values():
                row["meanSurfaceDistance"] *= 10
                row["maxSurfaceDistance"] *= 10
            self.assertFalse(evaluate_rigid_compatibility(**data)["compatibleUnderRigidAlignment"])

    def test_missing_or_nonfinite_evidence_and_partial_wing_pair_refuse(self):
        for kind in ("missing", "nonfinite", "partial_wing"):
            data = self.fixture()
            if kind == "missing":
                del data["placement"]["branches"]["arm_left"]
            elif kind == "nonfinite":
                data["placement"]["branches"]["arm_left"]["maxSurfaceDistance"] = float("nan")
            else:
                data["groups"]["wing_left"] = [1]
                data["placement"]["branches"]["wing_left"] = {"meanSurfaceDistance": .1, "maxSurfaceDistance": .2}
            with self.assertRaises(ValueError):
                evaluate_rigid_compatibility(**data)


if __name__ == "__main__":
    unittest.main()
