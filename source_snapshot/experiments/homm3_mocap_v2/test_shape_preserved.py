"""Shape-preserving preparation: original mesh invariant, fitted bind, no exact-joint B."""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from barycentric_transfer import UnmatchedCorrespondenceError
from fit_deformation_bind import fit_deformation_bind
from hidden_proxy import allowed_regions_for, assign_rigid_weights, transfer_through_proxy
from pin import SHAPE_PRESERVED_SETTINGS
from reconstruct_adapted import reconstruct_adapted
from run_shape_preserved import RESERVED_RUN_NAMES, _refuse_forbidden_roots, _refuse_reserved_run
from shape_gates import PRESERVE_FACTOR, preservation_limit
from shared_camera import freeze_shared_camera, project_view
from test_native_rotation import axis_rotation


def _demo_ready() -> bool:
    from paths import VENDOR_DEMO

    return (VENDOR_DEMO / "zoo1030" / "bvh").is_dir()


class SpaceAndPolicyTests(unittest.TestCase):
    def test_shared_camera_records_target_bind_space(self) -> None:
        points = np.array(((0.0, 0.0, 0.0), (1.0, 0.2, 0.4)), dtype=np.float64)
        cameras = freeze_shared_camera(points, width=100, height=100, space="targetBindSpace")
        self.assertEqual(cameras["space"], "targetBindSpace")
        self.assertFalse(cameras["perPanelAutofit"])
        xy = project_view(points, cameras, "front")
        self.assertEqual(xy.shape, (2, 2))

    def test_settings_require_shared_idle_reference_and_forbid_exact_joint_replay(self) -> None:
        self.assertTrue(SHAPE_PRESERVED_SETTINGS["notExactJointReplay"])
        self.assertTrue(SHAPE_PRESERVED_SETTINGS["sharedIdleReferenceRequired"])
        self.assertNotIn("clipFrame0IsNotBind", SHAPE_PRESERVED_SETTINGS)
        self.assertEqual(SHAPE_PRESERVED_SETTINGS["maxPrepRevisions"], 3)

    def test_preservation_gate_is_bbox_relative(self) -> None:
        verts = np.array(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), dtype=np.float64)
        self.assertAlmostEqual(preservation_limit(verts), PRESERVE_FACTOR * 10.0)

    def test_historical_eagle_skin_names_are_refused(self) -> None:
        for name in RESERVED_RUN_NAMES:
            with self.assertRaisesRegex(ValueError, "historical"):
                _refuse_reserved_run(name)
        with self.assertRaisesRegex(ValueError, "historical"):
            _refuse_reserved_run("eagle_skin_v3")

    def test_refuses_writes_under_eagle_skinned_tree(self) -> None:
        from paths import MOCAP_EAGLE_SKINNED

        with self.assertRaisesRegex(ValueError, "historical eagle-skinned"):
            _refuse_forbidden_roots(MOCAP_EAGLE_SKINNED / "preparation" / "shape_preserved_v1")


class FitTests(unittest.TestCase):
    def test_polyline_keeps_identities_and_does_not_collapse_the_tip_fork(self) -> None:
        names = ["Hips", "Spine", "W1", "W2", "W3", "W4", "W5"]
        parents = np.asarray((-1, 0, 1, 2, 3, 4, 4), dtype=np.int64)
        donor = np.zeros((7, 3), dtype=np.float64)
        donor[1] = (0.0, 1.0, 0.0)
        donor[2] = (0.2, 1.0, 0.0)
        donor[3] = (0.5, 1.0, 0.0)
        donor[4] = (0.8, 1.0, 0.0)
        donor[5] = (1.2, 1.0, 0.0)
        donor[6] = (0.8, 1.0, 0.2)
        target_names = ["Bone_000", "Bone_hub", "Bone_a", "Bone_b", "Bone_c"]
        target = np.zeros((5, 3), dtype=np.float64)
        target[0] = (0.0, 0.0, 0.0)
        target[1] = (0.0, 2.0, 0.0)
        target[2] = (0.4, 2.0, 0.0)
        target[3] = (1.0, 2.0, 0.0)
        target[4] = (2.0, 2.0, 0.0)
        verts = np.array(
            [
                (0.0, 2.0, 0.0),
                (2.0, 2.0, 0.0),
                (2.0, 2.0, 0.3),
                (0.0, 0.0, 0.0),
                (-0.4, 2.0, 0.0),
            ],
            dtype=np.float64,
        )
        regions = np.array(["torso", "wing_left", "wing_left", "torso", "wing_right"], dtype=object)
        profile = {
            "hubs": {"Hips": "Bone_000", "Spine": "Bone_hub"},
            "chains": (
                {"name": "wing_left", "kind": "polyline", "donor": ("W1", "W2", "W3", "W4"), "evidence": ("Bone_a", "Bone_b", "Bone_c")},
                {
                    "name": "wing_left_trail",
                    "kind": "fork",
                    "donor": ("W5",),
                    "parent": "W3",
                    "primary": "W4",
                    "region": "wing_left",
                },
            ),
            "leftRightPairs": (),
            "regionJoints": {"torso": ("Hips", "Spine"), "wing_left": ("W1", "W2", "W3", "W4", "W5")},
        }
        result = fit_deformation_bind(
            donor_names=names,
            donor_parents=parents,
            donor_rest=donor,
            target_names=target_names,
            target_rest=target,
            target_vertices=verts,
            target_regions=regions,
            profile=profile,
        )
        fitted = result["fittedPositions"]
        self.assertGreater(float(np.linalg.norm(fitted[5] - fitted[4])), 1e-4)
        self.assertAlmostEqual(float(fitted[0, 1]), 0.0)
        self.assertAlmostEqual(float(fitted[1, 1]), 2.0)


class TransferFailClosedTests(unittest.TestCase):
    def test_unmatched_vertices_are_not_silently_assigned(self) -> None:
        donor_v = np.array(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64)
        donor_faces = np.array(((0, 1, 2),), dtype=np.int64)
        donor_w = np.zeros((3, 2), dtype=np.float64)
        donor_w[:, 0] = 1.0
        names = ["Hips", "Wing"]
        region_joints = {"torso": ("Hips",), "wing_left": ("Wing",)}
        roc_v = np.array(((10.0, 10.0, 10.0),), dtype=np.float64)
        roc_regions = np.array(["wing_left"], dtype=object)
        normals = np.array(((0.0, 0.0, 1.0),), dtype=np.float64)
        skip = np.zeros(1, dtype=bool)
        with self.assertRaises(UnmatchedCorrespondenceError):
            transfer_through_proxy(
                target_vertices=roc_v,
                target_regions=roc_regions,
                target_normals=normals,
                target_triangles=np.array(((0, 0, 0),), dtype=np.int64),
                donor_vertices=donor_v,
                donor_faces=donor_faces,
                donor_weights=donor_w,
                donor_names=names,
                region_joints=region_joints,
                skip=skip,
            )

    def test_orientation_reject_is_not_a_nearest_bone_assignment(self) -> None:
        donor_v = np.array(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64)
        donor_faces = np.array(((0, 1, 2),), dtype=np.int64)
        donor_w = np.zeros((3, 2), dtype=np.float64)
        donor_w[:, 1] = 1.0
        names = ["Hips", "Wing"]
        region_joints = {"torso": ("Hips",), "wing_left": ("Wing",)}
        roc_v = np.array(((0.1, 0.1, 0.05),), dtype=np.float64)
        roc_regions = np.array(["wing_left"], dtype=object)
        normals = np.array(((0.0, 0.0, -1.0),), dtype=np.float64)
        skip = np.zeros(1, dtype=bool)
        with self.assertRaises(UnmatchedCorrespondenceError) as ctx:
            transfer_through_proxy(
                target_vertices=roc_v,
                target_regions=roc_regions,
                target_normals=normals,
                target_triangles=np.array(((0, 0, 0),), dtype=np.int64),
                donor_vertices=donor_v,
                donor_faces=donor_faces,
                donor_weights=donor_w,
                donor_names=names,
                region_joints=region_joints,
                skip=skip,
            )
        self.assertEqual(ctx.exception.unmatched[0]["reason"], "orientation_rejected")

    def test_hidden_proxy_source_has_no_nearest_bone_fallback(self) -> None:
        import hidden_proxy

        source = inspect.getsource(hidden_proxy)
        self.assertNotIn("nearest_bone", source)
        self.assertNotIn("nearest-bone", source)
        self.assertNotIn("argmax(distance", source)
        register = inspect.getsource(hidden_proxy.register_hidden_proxy)
        self.assertLess(register.find("transfer_through_proxy"), register.find("arap_deform"))
        self.assertIn("shrinkWrapAllVertices", register)

    def test_torso_cannot_take_head_or_beak_weights(self) -> None:
        self.assertNotIn("neck_head", allowed_regions_for("torso"))
        self.assertNotIn("beak", allowed_regions_for("neck_head"))
        self.assertEqual(allowed_regions_for("wing_left"), {"wing_left"})

    def test_rigid_attachment_is_explicit_not_a_surface_guess(self) -> None:
        regions = np.array(["beak", "torso"], dtype=object)
        profile = {"rigidAttachments": ({"region": "beak", "donorJoints": ("Jaw", "Head")},)}
        weights, assigned = assign_rigid_weights(
            vertex_count=2,
            joint_count=3,
            names=["Hips", "Head", "Jaw"],
            regions=regions,
            profile=profile,
        )
        self.assertTrue(assigned[0])
        self.assertFalse(assigned[1])
        self.assertAlmostEqual(float(weights[0].sum()), 1.0)


class ReconstructAdaptedTests(unittest.TestCase):
    def test_fixed_lengths_and_no_translation_replay(self) -> None:
        parents = np.asarray((-1, 0, 1), dtype=np.int64)
        capture_off = np.zeros((3, 3), dtype=np.float64)
        capture_off[1] = (0.0, 1.0, 0.0)
        capture_off[2] = (1.0, 0.0, 0.0)
        fitted_off = capture_off.copy()
        fitted_off[2] = (0.5, 0.0, 0.0)
        local = np.repeat(np.eye(3)[None], 3, axis=0)
        local[1] = axis_rotation(2, 0.4)
        from mesh_preview import fk_world_matrices

        cap_fk = capture_off.copy()
        cap_fk[0] = 0.0
        posed = fk_world_matrices(
            local_rotation=local,
            local_translation=cap_fk,
            parents=parents,
            root_world=np.zeros(3),
        )[:, :3, 3]
        capture = np.stack([posed, posed])
        result = reconstruct_adapted(
            capture_positions=capture,
            capture_reference_positions=np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))),
            capture_offsets=capture_off,
            fitted_offsets=fitted_off,
            parents=parents,
            names=["Hips", "Spine", "Tip"],
            hub_names=("Hips", "Spine"),
        )
        self.assertTrue(result["notExactJointReplay"])
        self.assertLess(result["fixedLengthErrorMax"], 1e-8)
        self.assertNotIn("localTranslationB", result)
        self.assertGreater(result["residualVsMappedCaptureMax"], 1e-4)

    def test_clip_frame0_is_not_forced_to_bind(self) -> None:
        parents = np.asarray((-1, 0), dtype=np.int64)
        offsets = np.zeros((2, 3), dtype=np.float64)
        offsets[1] = (0.0, 1.0, 0.0)
        local = np.repeat(np.eye(3)[None], 2, axis=0)
        local[0] = axis_rotation(2, 0.5)
        from mesh_preview import fk_world_matrices

        fk_off = offsets.copy()
        fk_off[0] = 0.0
        posed = fk_world_matrices(
            local_rotation=local,
            local_translation=fk_off,
            parents=parents,
            root_world=np.zeros(3),
        )[:, :3, 3]
        capture = np.stack([posed, posed, posed])
        result = reconstruct_adapted(
            capture_positions=capture,
            capture_reference_positions=np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))),
            capture_offsets=offsets,
            fitted_offsets=offsets,
            parents=parents,
            names=["Hips", "Tip"],
            hub_names=("Hips", "Tip"),
        )
        self.assertFalse(result["clipFrame0IsBind"])
        self.assertGreater(result["frame0LocalFromIdentityMaxRad"], 0.1)
        self.assertFalse(result["usedWorldDirectionMatching"])

    def test_capture_rest_stays_the_fitted_bind(self) -> None:
        parents = np.asarray((-1, 0, 1), dtype=np.int64)
        capture_off = np.zeros((3, 3), dtype=np.float64)
        capture_off[1] = (0.0, 1.0, 0.0)
        capture_off[2] = (1.0, 0.0, 0.0)
        fitted_off = capture_off.copy()
        fitted_off[2] = (0.5, 0.0, 0.0)
        rest = np.zeros((3, 3), dtype=np.float64)
        rest[1] = (0.0, 1.0, 0.0)
        rest[2] = (1.0, 1.0, 0.0)
        capture = np.stack([rest, rest])
        result = reconstruct_adapted(
            capture_positions=capture,
            capture_reference_positions=rest,
            capture_offsets=capture_off,
            fitted_offsets=fitted_off,
            parents=parents,
            names=["Hips", "Spine", "Tip"],
            hub_names=("Hips", "Spine"),
        )
        self.assertTrue(result["clipFrame0IsBind"])
        self.assertLess(result["frame0LocalFromIdentityMaxRad"], 1e-5)

    def test_reference_idle_drives_identity_target_when_donor_rest_differs(self) -> None:
        parents = np.asarray((-1, 0, 1), dtype=np.int64)
        donor_rest = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)))
        reference_idle = np.array(((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.8, 2.6, 0.4)))
        target = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.5, 0.2, -0.3)))
        result = reconstruct_adapted(
            capture_positions=np.stack([reference_idle, reference_idle]),
            capture_reference_positions=reference_idle,
            capture_offsets=donor_rest,
            fitted_offsets=target,
            parents=parents,
            names=["Hips", "Spine", "Tip"],
            hub_names=("Hips", "Spine"),
        )
        np.testing.assert_allclose(result["wholeBodyRotation"], np.eye(3), atol=1e-8)
        # The identity target is the captured idle anchor in capture space; the
        # fitted bind is allowed to have different proportions.
        np.testing.assert_allclose(result["mappedCapture"][0], reference_idle, atol=1e-8)
        self.assertLess(result["frame0LocalFromIdentityMaxRad"], 1e-5)

    def test_invalid_idle_reference_is_refused(self) -> None:
        parents = np.asarray((-1, 0), dtype=np.int64)
        offsets = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        capture = np.stack([offsets, offsets])
        common = dict(
            capture_positions=capture,
            capture_offsets=offsets,
            fitted_offsets=offsets,
            parents=parents,
            names=["Hips", "Tip"],
            hub_names=("Hips", "Tip"),
        )
        for reference in (
            np.array(((0.0, 0.0, 0.0), (np.nan, 1.0, 0.0))),
            np.array(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))),
        ):
            with self.assertRaises(ValueError):
                reconstruct_adapted(capture_reference_positions=reference, **common)

    def test_capture_length_change_is_not_a_posture_change(self) -> None:
        offsets = np.array(((0., 0., 0.), (0., 1., 0.)))
        result = reconstruct_adapted(
            capture_positions=(offsets * 2)[None],
            capture_reference_positions=offsets,
            capture_offsets=offsets, fitted_offsets=offsets,
            parents=np.array((-1, 0)), names=["Root", "Tip"],
            hub_names=("Root", "Tip"),
        )
        self.assertTrue(result["clipFrame0IsBind"])
        self.assertGreater(result["captureFrame0FromRestMax"], 0.1)
        self.assertLess(result["captureFrame0DirectionFromReferenceMaxRad"], 1e-7)

    def test_target_bone_lengths_are_preserved(self) -> None:
        parents = np.asarray((-1, 0, 1), dtype=np.int64)
        donor = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)))
        target = np.array(((0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 2.0, 0.5)))
        result = reconstruct_adapted(
            capture_positions=np.stack([donor, donor]),
            capture_reference_positions=donor,
            capture_offsets=donor,
            fitted_offsets=target,
            parents=parents,
            names=["Hips", "Spine", "Tip"],
            hub_names=("Hips", "Spine"),
        )
        positions = result["positions"]
        expected = np.linalg.norm(target[1:], axis=1)
        actual = np.linalg.norm(positions[:, 1:] - positions[:, parents[1:]], axis=2)
        np.testing.assert_allclose(actual, np.repeat(expected[None, :], len(positions), axis=0), atol=1e-8)

    def test_structural_coincident_hub_is_allowed_and_reported(self) -> None:
        parents = np.asarray((-1, 0, 1, 2), dtype=np.int64)
        # The donor has a structural zero-length root-to-hub edge.  The target
        # bind may still give that edge a useful length; its direction is simply
        # unobservable in the captured source.
        donor_offsets = np.array(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)))
        reference = np.array(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 2.0, 0.0)))
        fitted = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)))
        result = reconstruct_adapted(
            capture_positions=np.stack([reference, reference]),
            capture_reference_positions=reference,
            capture_offsets=donor_offsets,
            fitted_offsets=fitted,
            parents=parents,
            names=["Hips", "Hub", "Tip", "End"],
            hub_names=("Hips", "Hub"),
        )
        self.assertIn("Hub", result["unobservableDirectionJoints"])
        self.assertEqual(result["motionPreservation"]["capture"]["boneCount"], 2)
        self.assertNotEqual(result["motionPreservation"]["capture"]["boneCount"], 3)
        self.assertTrue(result["motionPreservation"]["stationaryDisplacedDoesNotPass"])
        self.assertLess(result["motionPreservation"]["capture"]["frameToFrameMaxRad"], 1e-8)

    def test_structural_coincident_hub_is_refused_when_separated(self) -> None:
        parents = np.asarray((-1, 0, 1), dtype=np.int64)
        donor_offsets = np.array(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        reference = np.array(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        separated = reference.copy()
        separated[1] = (0.0, 0.25, 0.0)
        with self.assertRaises(ValueError):
            reconstruct_adapted(
                capture_positions=np.stack([separated, separated]),
                capture_reference_positions=reference,
                capture_offsets=donor_offsets,
                fitted_offsets=donor_offsets,
                parents=parents,
                names=["Hips", "Hub", "Tip"],
                hub_names=("Hips", "Hub"),
            )

    def test_pose_result_does_not_depend_on_clip_boundary(self) -> None:
        parents = np.asarray((-1, 0), dtype=np.int64)
        reference = np.array(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        pose = np.array(((0.0, 0.0, 0.0), (0.6, 0.8, 0.0)))
        common = dict(
            capture_reference_positions=reference,
            capture_offsets=reference,
            fitted_offsets=reference,
            parents=parents,
            names=["Hips", "Tip"],
            hub_names=("Hips", "Tip"),
        )
        short = reconstruct_adapted(capture_positions=np.stack([reference, pose]), **common)
        long = reconstruct_adapted(capture_positions=np.stack([reference, reference, pose]), **common)
        np.testing.assert_allclose(short["localRotation"][1], long["localRotation"][2], atol=1e-8)
        np.testing.assert_allclose(short["positions"][1], long["positions"][2], atol=1e-8)


class ProfileReuseTests(unittest.TestCase):
    def test_roc_and_crusader_share_the_same_prepare_entry(self) -> None:
        import run_shape_preserved as runner

        self.assertTrue(callable(runner.prepare))
        from asset_profiles import CRUSADER_MIXAMO, ROC_EAGLE

        self.assertTrue(CRUSADER_MIXAMO["syntheticMotionOnly"])
        self.assertEqual(ROC_EAGLE["donorRefSeq"], "Eagle#Eagle-Landing/y15")
        self.assertIn("BN_Wing_L_05", [name for chain in ROC_EAGLE["chains"] if chain["name"] == "wing_left_trail" for name in chain["donor"]])
        self.assertEqual(len(ROC_EAGLE["chains"][2]["donor"]), 4)


class OriginalHashTests(unittest.TestCase):
    def test_original_roc_hash_matches_the_profile_pin(self) -> None:
        from asset_profiles import ROC_EAGLE
        from pin import sha256_file

        path = ROC_EAGLE["mesh"]
        if not path.is_file():
            self.skipTest("original Roc GLB is not present")
        self.assertEqual(sha256_file(path), ROC_EAGLE["expectedMeshSha256"])


if __name__ == "__main__":
    unittest.main()
