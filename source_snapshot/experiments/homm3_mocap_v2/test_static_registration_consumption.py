"""Accepted registration owns the exact mesh placement consumed by the binder."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import prepare_move_bind_capture_bind as binder
import static_bind_registration as registration
from glb_skeleton import _accessor, read_glb


def candidate(identifier: str = "selected") -> dict:
    return {
        "id": identifier,
        "meshToSourceView": {"rotation": registration.rotation_matrix(37, -18, 11).tolist()},
        "skeletonSimilarity": {
            "rotation": registration.rotation_matrix(-23, 16, 7).tolist(),
            "scale": 2.3,
            "translation": [0.7, -1.1, 0.4],
        },
    }


def payload() -> dict:
    return {
        "schema": registration.SCHEMA,
        "bindFrame": 0,
        "inputHashes": {"mesh": "mesh", "capture": "capture"},
        "acceptance": {
            "status": "accepted", "accepted": True, "visualConfirmation": True,
            "consumable": True, "selectedCandidateId": "selected",
        },
        "views": {"candidates": [candidate()]},
    }


class AcceptedAlignmentTest(unittest.TestCase):
    def test_nontrivial_composition_matches_approved_view_and_round_trip(self) -> None:
        document = payload()
        row = document["views"]["candidates"][0]
        mesh = np.array([[0.2, -0.4, 1.0], [1.3, 0.1, -0.2], [-0.8, 2.0, 0.5]])
        alignment = registration.accepted_mesh_alignment(document)
        placed = registration.apply_similarity(
            mesh, rotation=alignment["rotation"], scale=alignment["scale"],
            translation=alignment["translation"],
        )
        skeleton = row["skeletonSimilarity"]
        registered = registration.apply_similarity(
            placed, rotation=np.array(skeleton["rotation"]), scale=skeleton["scale"],
            translation=np.array(skeleton["translation"]),
        )
        np.testing.assert_allclose(registered, mesh @ np.array(row["meshToSourceView"]["rotation"]).T, atol=1e-12)
        recovered = registration.invert_similarity(
            placed, rotation=alignment["rotation"], scale=alignment["scale"],
            translation=alignment["translation"],
        )
        np.testing.assert_allclose(recovered, mesh, atol=1e-12)
        self.assertEqual(alignment["selectedCandidateId"], "selected")
        self.assertTrue(alignment["policy"])

    def test_selection_changes_applied_placement(self) -> None:
        document = payload()
        second = candidate("other")
        second["skeletonSimilarity"]["translation"] = [3.0, 4.0, 5.0]
        document["views"]["candidates"].append(second)
        first_alignment = registration.accepted_mesh_alignment(document)
        document["acceptance"]["selectedCandidateId"] = "other"
        second_alignment = registration.accepted_mesh_alignment(document)
        self.assertFalse(np.allclose(first_alignment["translation"], second_alignment["translation"]))
        self.assertEqual(second_alignment["selectedCandidateId"], "other")

    def test_missing_unknown_empty_and_duplicate_selection_are_rejected(self) -> None:
        mutations = []
        missing = payload()
        del missing["acceptance"]["selectedCandidateId"]
        mutations.append(missing)
        for selected in ("", "unknown", 1):
            document = payload()
            document["acceptance"]["selectedCandidateId"] = selected
            mutations.append(document)
        duplicate = payload()
        duplicate["views"]["candidates"].append(candidate())
        mutations.append(duplicate)
        no_transform = payload()
        del no_transform["views"]["candidates"][0]["skeletonSimilarity"]
        mutations.append(no_transform)
        for index, document in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                registration.accepted_mesh_alignment(document)

    def test_invalid_similarity_inputs_are_rejected(self) -> None:
        bad_rotations = [
            [[1, 0.3, 0], [0, 1, 0], [0, 0, 1]],
            np.diag([-1, 1, 1]).tolist(),
            [[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]],
            [[float("inf"), 0, 0], [0, 1, 0], [0, 0, 1]],
            [[1, 0], [0, 1]],
        ]
        for owner in ("meshToSourceView", "skeletonSimilarity"):
            for index, rotation in enumerate(bad_rotations):
                document = payload()
                document["views"]["candidates"][0][owner]["rotation"] = rotation
                with self.subTest(owner=owner, index=index), self.assertRaises(ValueError):
                    registration.accepted_mesh_alignment(document)
        for scale in (-1, 0, float("nan"), float("inf")):
            document = payload()
            document["views"]["candidates"][0]["skeletonSimilarity"]["scale"] = scale
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                registration.accepted_mesh_alignment(document)
        for translation in ([0, 1], [0, float("nan"), 1], [0, float("inf"), 1]):
            document = payload()
            document["views"]["candidates"][0]["skeletonSimilarity"]["translation"] = translation
            with self.subTest(translation=translation), self.assertRaises(ValueError):
                registration.accepted_mesh_alignment(document)

    def test_consumption_gate_checks_transform_not_only_acceptance_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registration.json"
            document = payload()
            path.write_text(json.dumps(document), encoding="utf-8")
            loaded = registration.require_accepted_static_registration(
                path, mesh_sha256="mesh", capture_sha256="capture", bind_frame=0,
            )
            self.assertEqual(loaded, document)
            invalid = copy.deepcopy(document)
            invalid["views"]["candidates"][0]["skeletonSimilarity"]["scale"] = -1
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ValueError):
                registration.require_accepted_static_registration(
                    path, mesh_sha256="mesh", capture_sha256="capture", bind_frame=0,
                )

    def test_binder_exports_approved_transform_without_legacy_alignment(self) -> None:
        names = ["Root", "Body", "Head", "Tip"]
        vertices = np.array([[x, y, z] for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)])
        triangles = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
        surface = {"vertices": vertices, "triangles": triangles, "uvs": np.zeros((8, 2)), "albedo": np.ones((2, 2, 4), dtype=np.uint8) * 255}
        profile = {
            "assetId": "synthetic_non_roc", "regionJoints": {"torso": names},
            "captureBind": {
                "headJoint": "Head", "leftJoint": "Body", "rightJoint": "Tip",
                "meshBodyAxis": [0, 1, 0], "meshSecondAxis": [0, 0, 1], "skinFrozenRegions": [],
            },
        }
        initial = {"weights": np.full((8, 4), .25), "geodesic": {"distances": np.ones((8, 4))}}
        placement = {
            "jointsOutsideCount": 0,
            "jointCount": 4,
            "maxDistanceOutsideFractionOfDiagonal": 0.0,
            "worstViewOutsideFraction": 0.0,
            "worstViewMaxDistanceOutsideFractionOfDiagonal": 0.0,
            "views": {
                "front": {"outsideFraction": 0.0, "maxDistanceOutsideFractionOfDiagonal": 0.0},
                "side": {"outsideFraction": 0.0, "maxDistanceOutsideFractionOfDiagonal": 0.0},
                "top": {"outsideFraction": 0.0, "maxDistanceOutsideFractionOfDiagonal": 0.0},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh, capture, out = root / "mesh.glb", root / "capture.npz", root / "bind.glb"
            mesh.write_bytes(b"synthetic mesh loader fixture")
            np.savez(capture, joint_names=np.array(names), parents=np.array([-1, 0, 1, 2]),
                     pred_position=np.array([[[0., 0., 0.], [0., .2, 0.], [0., .4, 0.], [.2, .4, 0.]]]))
            document = payload()
            document["inputHashes"] = {"mesh": binder.sha256_file(mesh), "capture": binder.sha256_file(capture)}
            registration_path = root / "registration.json"
            registration_path.write_text(json.dumps(document), encoding="utf-8")
            with patch.object(binder, "get_profile", return_value=profile), \
                 patch.object(binder, "_load_unskinned_triangle_surface", return_value=surface), \
                 patch.object(binder, "semantic_axis_rotation", side_effect=AssertionError("legacy axes used")), \
                 patch.object(binder, "align_surface_to_rest", side_effect=AssertionError("legacy alignment used")), \
                 patch.object(binder, "build_initializer_weights", return_value=initial, create=True), \
                 patch.object(binder, "geodesic_bone_distances", return_value=initial["geodesic"]), \
                 patch.object(binder, "nearest_bone_segment_weights", return_value=initial["weights"]), \
                 patch.object(binder, "joints_inside_registered_source_view", return_value=(True, placement)), \
                 patch.object(binder, "write_skeleton_overlay"):
                report = binder.prepare_move_bind_capture_bind(
                    mesh_glb=mesh, capture_path=capture, out_glb=out,
                    unit="synthetic_non_roc", static_registration=registration_path,
                )
            alignment = registration.accepted_mesh_alignment(document)
            expected = registration.apply_similarity(
                vertices, rotation=alignment["rotation"], scale=alignment["scale"], translation=alignment["translation"],
            )
            glb = read_glb(out)
            primitive = glb["json"]["meshes"][0]["primitives"][0]
            reloaded = _accessor(glb, glb["bin"], primitive["attributes"]["POSITION"]).reshape(-1, 3)
            np.testing.assert_allclose(reloaded, expected, atol=1e-6)
            self.assertEqual(report["staticRegistration"]["selectedCandidateId"], "selected")

    def test_cached_bind_requires_exact_registration_and_placement(self) -> None:
        document = payload()
        matching = {
            "staticRegistration": {"sha256": "registration-hash", "selectedCandidateId": "selected"},
            "surfaceAlignment": registration.accepted_mesh_alignment(document),
        }
        registration.require_bind_registration(matching, document, "registration-hash")
        legacy = {"surfaceAlignment": {"rotationPolicy": "legacy_axes"}}
        wrong_hash = copy.deepcopy(matching)
        wrong_hash["staticRegistration"]["sha256"] = "different-artifact"
        wrong_selection = copy.deepcopy(matching)
        wrong_selection["staticRegistration"]["selectedCandidateId"] = "different-view"
        wrong_placement = copy.deepcopy(matching)
        wrong_placement["surfaceAlignment"]["translation"][0] += .1
        for name, sidecar in (("legacy", legacy), ("hash", wrong_hash),
                              ("selection", wrong_selection), ("placement", wrong_placement)):
            with self.subTest(name=name), self.assertRaises(registration.StaticRegistrationError):
                registration.require_bind_registration(sidecar, document, "registration-hash")


class BindDefectPassthroughTest(unittest.TestCase):
    def test_remaining_idle0_env_allows_inside_mesh_passthrough(self) -> None:
        previous = binder.os.environ.get(binder.BIND_DEFECT_ENV)
        try:
            binder.os.environ.pop(binder.BIND_DEFECT_ENV, None)
            self.assertFalse(binder.accept_bind_defects())
            binder.os.environ[binder.BIND_DEFECT_ENV] = "1"
            self.assertTrue(binder.accept_bind_defects())
        finally:
            if previous is None:
                binder.os.environ.pop(binder.BIND_DEFECT_ENV, None)
            else:
                binder.os.environ[binder.BIND_DEFECT_ENV] = previous


if __name__ == "__main__":
    unittest.main()
