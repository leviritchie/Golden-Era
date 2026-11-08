import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import numpy as np

from geometry_ownership import apply_ownership, animated_boundary_gate, validate_prepared_ownership, load_ownership, validate_boundary_pairs, SCHEMA
from source_skin_initialization import initialize_source_weights


class GeometryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.target = {"vertices": np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]),
                       "triangles": np.array([[0, 1, 2], [1, 3, 2]]),
                       "uvs": np.array([[0., 0], [1, 0], [0, 1], [1, 1]]),
                       "sourceDenseWeights": np.ones((4, 1)), "names": ["source"],
                       "albedo": np.ones((2, 2, 4), dtype=np.uint8)}
        self.profile = {"geometryOwnership": {"sha256": "mask"},
                        "rigidAttachments": [{"region": "weapon", "donorJoints": ["hand"]}],
                        "regionJoints": {"body": ["body"], "weapon": ["hand"]},
                        "sourceJointMap": {"source": "body"}}
        self.data = {"sourceVertexCount": 4, "sourceFaceCount": 2, "maxBoundaryGap": 0,
                     "rigidParts": [{"region": "weapon", "owner": "hand", "faceIds": [1], "interfaceMode": "split_shared"}],
                     "bodyVertexRegions": {"body": [0, 1, 2]}}

    def apply(self):
        with patch("geometry_ownership.load_ownership", return_value=self.data):
            return apply_ownership(self.target, self.profile)

    def test_exact_corners_and_complete_boundary(self):
        out = self.apply()
        np.testing.assert_array_equal(out["sourceVertexIds"], [0, 1, 2, 3, 1, 2])
        np.testing.assert_array_equal(out["ownershipBoundaryPairs"], [[1, 4], [2, 5]])
        np.testing.assert_array_equal(out["vertices"][out["triangles"]], self.target["vertices"][self.target["triangles"]])
        np.testing.assert_array_equal(out["uvs"][out["triangles"]], self.target["uvs"][self.target["triangles"]])
        self.assertEqual(out["vertexRegions"].tolist(), ["body", "body", "body", "weapon", "weapon", "weapon"])

    def test_mask_overlap_rejected(self):
        self.data["rigidParts"].append(copy.deepcopy(self.data["rigidParts"][0]))
        with self.assertRaises(ValueError): self.apply()

    def test_missing_body_vertex_rejected(self):
        self.data["bodyVertexRegions"]["body"].remove(1)
        with self.assertRaisesRegex(ValueError, "exactly cover"): self.apply()

    def test_out_of_range_or_duplicate_face_rejected(self):
        for values in ([2], [1, 1]):
            self.data["rigidParts"][0]["faceIds"] = values
            with self.assertRaises(ValueError): self.apply()

    def test_physical_prop_zero_support_allowed_body_stays_strict(self):
        out = self.apply()
        with patch("geometry_ownership.load_ownership", return_value=self.data):
            weights = initialize_source_weights(out["sourceDenseWeights"], ["source"], ["body", "hand"], out["vertexRegions"], self.profile)["weights"]
            np.testing.assert_array_equal(weights[:3], [[1, 0]] * 3)
            np.testing.assert_array_equal(weights[3:], [[0, 1]] * 3)
            self.profile["sourceJointMap"]["source"] = "hand"
            with self.assertRaisesRegex(ValueError, "zero support in region body"):
                initialize_source_weights(out["sourceDenseWeights"], ["source"], ["body", "hand"], out["vertexRegions"], self.profile)

    def test_full_replay_rejects_missing_pair_or_vertex_mapping(self):
        target = self.apply()
        skin = {**target, "regions": target["vertexRegions"], "names": ["body", "hand"]}
        with patch("geometry_ownership.load_ownership", return_value=self.data), patch("target_asset.load_target_asset", return_value=target):
            skin["weights"] = initialize_source_weights(target["sourceDenseWeights"], ["source"], skin["names"], skin["regions"], self.profile)["weights"]
            validate_prepared_ownership(self.profile, skin)
            for key in ("ownershipBoundaryPairs", "sourceVertexIds"):
                broken = {**skin, key: skin[key][:-1]}
                with self.assertRaisesRegex(ValueError, "replay mismatch"):
                    validate_prepared_ownership(self.profile, broken)

    def test_gap_gate_no_subset_and_no_disconnected_prop(self):
        target = self.apply()
        with patch("geometry_ownership.load_ownership", return_value=self.data), patch("target_asset.load_target_asset", return_value=target):
            posed = target["vertices"][None]
            self.assertTrue(animated_boundary_gate(self.profile, target, posed, expected_frame_count=1)["passed"])
            moved = posed.copy()
            moved[0, 4, 0] += .01
            self.assertFalse(animated_boundary_gate(self.profile, target, moved, expected_frame_count=1)["passed"])
            with self.assertRaisesRegex(ValueError, "complete source replay"):
                animated_boundary_gate(self.profile, {**target, "ownershipBoundaryPairs": target["ownershipBoundaryPairs"][:1]}, moved, expected_frame_count=1)
            for wrong in (posed[:0], posed[0], np.full_like(posed, np.nan), posed[:, :-1]):
                with self.assertRaisesRegex(ValueError, "every expected"):
                    animated_boundary_gate(self.profile, target, wrong, expected_frame_count=1)
            with self.assertRaisesRegex(ValueError, "every expected"):
                animated_boundary_gate(self.profile, target, posed, expected_frame_count=2)

    def test_sequential_parts_compose_shared_source_mapping(self):
        self.target["triangles"] = np.array([[0, 1, 2], [1, 3, 2], [0, 3, 1]])
        self.data["sourceFaceCount"] = 3
        self.data["rigidParts"].append({"region": "shield", "owner": "other", "faceIds": [2], "interfaceMode": "split_shared"})
        self.profile["rigidAttachments"].append({"region": "shield", "donorJoints": ["other"]})
        out = self.apply()
        np.testing.assert_array_equal(out["sourceVertexIds"], [0, 1, 2, 3, 1, 2, 3, 0, 1])
        np.testing.assert_array_equal(out["ownershipBoundaryPairs"], [[1, 4], [2, 5], [3, 6], [0, 7], [1, 8]])
        np.testing.assert_array_equal(out["sourceVertexIds"][out["triangles"]], self.target["triangles"])
        np.testing.assert_array_equal(out["vertices"][out["triangles"]], self.target["vertices"][self.target["triangles"]])
        np.testing.assert_array_equal(out["uvs"][out["triangles"]], self.target["uvs"][self.target["triangles"]])

    def test_interface_mode_must_match_original_topology(self):
        self.data["rigidParts"][0]["interfaceMode"] = "source_detached"
        with self.assertRaisesRegex(ValueError, "original source shared"): self.apply()
        self.target["vertices"] = np.concatenate([self.target["vertices"], [[2, 0, 0], [2, 1, 0]]])
        self.target["uvs"] = np.concatenate([self.target["uvs"], [[.5, 0], [.5, 1]]])
        self.target["sourceDenseWeights"] = np.ones((6, 1))
        self.target["triangles"][1] = [3, 4, 5]
        self.data["sourceVertexCount"] = 6
        target = self.apply()
        self.assertEqual(target["ownershipBoundaryPairs"].shape, (0, 2))
        with patch("geometry_ownership.load_ownership", return_value=self.data), patch("target_asset.load_target_asset", return_value=target):
            gate = animated_boundary_gate(self.profile, target, target["vertices"][None], expected_frame_count=1)
        self.assertFalse(gate["boundaryApplicable"])
        self.assertFalse(gate["contactProven"])
        self.assertEqual(gate["acceptance"], "not_applicable_source_detached")
        self.data["rigidParts"][0]["interfaceMode"] = "split_shared"
        with self.assertRaisesRegex(ValueError, "original source shared"): self.apply()

    def test_pair_shape_uniqueness_range_and_source_correspondence(self):
        target = self.apply()
        source = target["sourceVertexIds"]
        for pairs in ([], [[1, 4], [1, 4]], [[1, 4], [2, 9]], [[0, 4], [2, 5]], [[1., 4.], [2., 5.]]):
            with self.assertRaisesRegex(ValueError, "boundary pairs"):
                validate_boundary_pairs(source, pairs, 4)

    def test_authored_body_override_does_not_change_shared_prop_copy(self):
        self.target["sourceDenseWeights"] = np.array([[1., 0], [0, 1], [1, 0], [0, 1]])
        self.profile["sourceJointMap"] = {"body_source": "body", "hand_source": "hand"}
        self.data["bodyWeightOverrides"] = [{"sourceVertexId": 1, "weights": {"body": 1.},
                                              "rationale": "reviewed body-side contact vertex"}]
        target = self.apply()
        def initialize(ids):
            return initialize_source_weights(target["sourceDenseWeights"], ["body_source", "hand_source"],
                ["body", "hand"], target["vertexRegions"], self.profile, source_vertex_ids=ids)
        with patch("geometry_ownership.load_ownership", return_value=self.data):
            result = initialize(target["sourceVertexIds"])
            self.assertEqual(result["bodyWeightOverrideCount"], 1)
            np.testing.assert_array_equal(result["weights"][1], [1, 0])
            np.testing.assert_array_equal(result["weights"][4], [0, 1])
            with self.assertRaisesRegex(ValueError, "source_vertex_ids"):
                initialize(None)
            self.data["bodyWeightOverrides"] = []
            with self.assertRaisesRegex(ValueError, "zero support in region body"):
                initialize(target["sourceVertexIds"])

    def test_invalid_body_override_weights_region_or_source_rejected(self):
        from geometry_ownership import body_weight_overrides
        valid = {"sourceVertexId": 1, "weights": {"body": 1.}, "rationale": "reviewed body"}
        for change in ({"sourceVertexId": 3}, {"sourceVertexId": True}, {"weights": {"hand": 1.}},
                       {"weights": {"body": -.5}}, {"weights": {"body": .5}},
                       {"weights": {"body": float("nan")}}, {"rationale": ""}):
            self.data["bodyWeightOverrides"] = [{**valid, **change}]
            with self.assertRaises(ValueError): body_weight_overrides(self.data, self.profile)
        self.data["bodyWeightOverrides"] = [valid, valid]
        with self.assertRaisesRegex(ValueError, "repeat"):
            body_weight_overrides(self.data, self.profile)

    def test_sidecar_camera_hash_conversion_and_draft_rejection(self):
        camera = json.dumps({"pxPerWorld": 100}).encode()
        data = {**self.data, "schema": SCHEMA, "sourceMeshSha256": "mesh", "maxBoundaryGap": 0,
                "boundaryGapUnits": "source_mesh_units", "authorship": {"status": "reviewed_source_geometry"},
                "boundaryGapEvidence": {"cameraPath": "camera.json", "cameraSha256": hashlib.sha256(camera).hexdigest(),
                    "worldUnitsPerPixel": .01, "pixelLimit": 0, "acceptance": "provisional_unaccepted"}}
        def check(value):
            payload = json.dumps(value).encode()
            profile = {"expectedMeshSha256": "mesh", "geometryOwnership": {"path": "ownership.json", "sha256": hashlib.sha256(payload).hexdigest()}}
            with patch("pathlib.Path.read_bytes", side_effect=[payload, camera]):
                return load_ownership(profile)
        check(data)
        for mutate in (lambda value: value["authorship"].update(status="draft"),
                       lambda value: value["boundaryGapEvidence"].update(cameraSha256="wrong"),
                       lambda value: value["boundaryGapEvidence"].update(worldUnitsPerPixel=.02),
                       lambda value: value.update(maxBoundaryGap=.01),
                       lambda value: value["boundaryGapEvidence"].pop("cameraPath"),
                       lambda value: value["boundaryGapEvidence"].update(cameraPath=[]),
                       lambda value: value["boundaryGapEvidence"].update(worldUnitsPerPixel=[]),
                       lambda value: value.update(authorship=[]),
                       lambda value: value.update(rigidParts=[None]),
                       lambda value: value.update(sourceVertexCount="4")):
            broken = copy.deepcopy(data)
            mutate(broken)
            with self.assertRaises(ValueError): check(broken)


if __name__ == "__main__":
    unittest.main()
