"""Local prop extraction and rigid ownership, including the current Archer asset."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
import uuid

import numpy as np

from owned_rerig.glb_io import load_mesh, load_render_surface, read_glb, write_skinned_mesh
from owned_rerig.prop_attachment import extract_prop_face_ids, extract_prop_faces, extract_prop_vertex_range, repair_prop_attachments

ROOT = Path(__file__).resolve().parents[2]
ARCHER = ROOT / "artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer"


def grid_fixture():
    positions = np.array([[x, y, 0.] for x in range(5) for y in range(3)])
    faces = []
    for x in range(4):
        for y in range(2):
            a = x * 3 + y
            faces += [[a, a + 3, a + 1], [a + 3, a + 4, a + 1]]
    surface = {"positions": positions, "indices": np.array(faces).reshape(-1),
               "sourceSha256": "0" * 64,
               "normals": np.tile([0., 0., 1.], (len(positions), 1)),
               "uvs": positions[:, :2] / 4, "baseColor": np.zeros((2, 2, 3), dtype=np.uint8)}
    config = {"schema": "prop_attachment.v1", "sourceMeshSha256": "0" * 64, "props": [{
        "name": "rod", "bone": "LeftHand",
        "region": {"bounds": [[1.5, -1., -1.], [5., 3., 1.]],
                   "seeds": [{"a": [4., 0., 0.], "b": [4., 2., 0.], "radius": .1}]},
        "sourceGrip": [4., 1., 0.], "sourceForward": [1., 0., 0.],
        "sourceUp": [0., 1., 0.], "targetOffset": [.2, .1, 0.],
        "targetForward": [0., 1., 0.], "targetUp": [0., 0., 1.]}]}
    args = {"surface": surface, "joints": np.zeros((len(positions), 4), int),
            "weights": np.tile([1., 0., 0., 0.], (len(positions), 1)),
            "heads": np.array([[0., 0., 0.], [5., 2., 1.]]),
            "names": ["Hips", "LeftHand"], "config": config}
    return args


class PropAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.args = grid_fixture()
        self.result = repair_prop_attachments(**self.args)

    def test_every_triangle_and_texture_coordinate_is_preserved(self):
        result, source = self.result, self.args["surface"]
        ids = result["sourceVertices"]
        np.testing.assert_array_equal(ids[result["surface"]["indices"]], source["indices"])
        np.testing.assert_array_equal(result["surface"]["uvs"], source["uvs"][ids])
        self.assertIs(result["surface"]["baseColor"], source["baseColor"])
        self.assertEqual(result["report"]["sourceFaces"], result["report"]["outputFaces"])

    def test_contact_vertices_are_duplicated_and_no_triangle_bridges_owners(self):
        result = self.result
        owners = result["propOwners"][result["surface"]["indices"].reshape(-1, 3)]
        self.assertTrue(np.all(owners == owners[:, :1]))
        self.assertGreater(result["report"]["duplicatedContactVertices"], 0)

    def test_body_positions_normals_and_weights_are_unchanged(self):
        result = self.result
        body = result["propOwners"] == -1
        ids = result["sourceVertices"][body]
        for key in ("positions", "normals"):
            np.testing.assert_array_equal(result["surface"][key][body], self.args["surface"][key][ids])
        for key in ("joints", "weights"):
            np.testing.assert_array_equal(result[key][body], self.args[key][ids])

    def test_prop_is_rigid_and_has_one_hand_owner(self):
        result = self.result
        selected = result["propOwners"] == 0
        source = self.args["surface"]["positions"][result["sourceVertices"][selected]]
        moved = result["surface"]["positions"][selected]
        np.testing.assert_allclose(np.linalg.norm(source[1:] - source[0], axis=1),
                                   np.linalg.norm(moved[1:] - moved[0], axis=1), atol=1e-12)
        np.testing.assert_array_equal(result["joints"][selected, 0], 1)
        np.testing.assert_array_equal(result["weights"][selected, 0], 1)
        np.testing.assert_array_equal(result["weights"][selected, 1:], 0)

    def test_explicit_source_faces_are_exact_and_require_one_selector(self):
        args = grid_fixture()
        prop = args["config"]["props"][0]
        prop.pop("region")
        prop["sourceFaceIds"] = [0, 1]
        result = repair_prop_attachments(**args)
        self.assertEqual(result["report"]["props"][0]["extraction"]["selectedFaces"], 2)
        with self.assertRaisesRegex(ValueError, "sorted, unique"):
            extract_prop_face_ids(args["surface"]["positions"], args["surface"]["indices"], [1, 0])
        prop["region"] = grid_fixture()["config"]["props"][0]["region"]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            repair_prop_attachments(**args)

    def test_grip_and_normals_rotate_with_the_rigid_attachment(self):
        result = self.result
        prop = self.args["config"]["props"][0]
        rotation = np.array(result["report"]["props"][0]["rotation"])
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(rotation), 1.)
        target = self.args["heads"][1] + prop["targetOffset"]
        source = self.args["surface"]["positions"]
        grip_source = np.flatnonzero(np.all(source == prop["sourceGrip"], axis=1))[0]
        grip_result = np.flatnonzero((result["sourceVertices"] == grip_source) &
                                     (result["propOwners"] == 0))[0]
        np.testing.assert_allclose(result["surface"]["positions"][grip_result], target)
        np.testing.assert_allclose(result["surface"]["normals"][grip_result], [1., 0., 0.])

    def test_uv_seam_duplication_does_not_change_region(self):
        args = copy.deepcopy(self.args)
        s = args["surface"]
        source_id = 13
        n = len(s["positions"])
        for key in ("positions", "normals", "uvs"):
            s[key] = np.concatenate((s[key], s[key][source_id:source_id + 1]))
        s["uvs"][-1] = [.12, .89]
        occurrence = np.flatnonzero(s["indices"] == source_id)[0]
        s["indices"][occurrence] = n
        for key in ("joints", "weights"):
            args[key] = np.concatenate((args[key], args[key][source_id:source_id + 1]))
        result = repair_prop_attachments(**args)
        self.assertEqual(self.result["report"]["props"][0]["extraction"],
                         result["report"]["props"][0]["extraction"])
        np.testing.assert_array_equal(result["surface"]["uvs"], s["uvs"][result["sourceVertices"]])

    def test_overlapping_props_are_not_silently_resolved(self):
        args = copy.deepcopy(self.args)
        args["config"]["props"] *= 2
        with self.assertRaisesRegex(ValueError, "same faces"):
            repair_prop_attachments(**args)

    def test_coordinates_are_pinned_to_the_exact_source_asset(self):
        args = copy.deepcopy(self.args)
        args["surface"]["sourceSha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "does not match"):
            repair_prop_attachments(**args)
        del args["config"]["sourceMeshSha256"]
        with self.assertRaisesRegex(ValueError, "require"):
            repair_prop_attachments(**args)

    def test_invalid_seed_envelope_and_parallel_frame_are_explicit(self):
        args = copy.deepcopy(self.args)
        args["config"]["props"][0]["region"]["bounds"][1][0] = 3.5
        with self.assertRaisesRegex(ValueError, "overlap"):
            repair_prop_attachments(**args)
        args = copy.deepcopy(self.args)
        args["config"]["props"][0]["targetUp"] = [0., 2., 0.]
        with self.assertRaisesRegex(ValueError, "parallel"):
            repair_prop_attachments(**args)

    def test_standalone_vertex_range_keeps_every_prop_face(self):
        args = copy.deepcopy(self.args)
        s = args["surface"]
        offset = len(s["positions"])
        s["positions"] = np.vstack((s["positions"], s["positions"] + [10., 0., 0.]))
        s["normals"] = np.vstack((s["normals"], s["normals"]))
        s["uvs"] = np.vstack((s["uvs"], s["uvs"]))
        s["indices"] = np.r_[s["indices"], (s["indices"].reshape(-1, 3) + offset).reshape(-1)]
        args["joints"] = np.vstack((args["joints"], args["joints"]))
        args["weights"] = np.vstack((args["weights"], args["weights"]))
        prop = args["config"]["props"][0]
        prop.pop("region")
        prop["sourceVertexRange"] = [offset, len(s["positions"])]
        ids, report = extract_prop_vertex_range(s["positions"], s["indices"], prop["sourceVertexRange"])
        self.assertEqual(report["mode"], "source_vertex_range")
        self.assertEqual(report["selectedFaces"], len(s["indices"]) // 3 // 2)
        result = repair_prop_attachments(**args)
        self.assertEqual(result["report"]["props"][0]["extraction"]["selectedFaces"], report["selectedFaces"])


@unittest.skipUnless((ARCHER / "mesh-fitted-v1/fitted_bind.glb").is_file(), "Archer pilot asset absent")
class ArcherAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ARCHER / "t-pose/mesh.glb"
        base = ARCHER / "mesh-fitted-v1"
        cls.surface = load_render_surface(source)
        mesh = load_mesh(base / "fitted_bind.glb")
        doc = read_glb(base / "fitted_bind.glb")["json"]
        cls.names = [doc["nodes"][i]["name"] for i in doc["skins"][0]["joints"]]
        cls.parents = [None] * len(cls.names)
        for i, node in enumerate(doc["nodes"][:len(cls.names)]):
            for child in node.get("children", []):
                cls.parents[child] = i
        cls.heads = np.array(json.loads((base / "report.json").read_text())["fit"]["heads"])
        config = json.loads((Path(__file__).parent / "archer_prop_attachment.json").read_text())
        cls.result = repair_prop_attachments(surface=cls.surface, joints=mesh.joints,
            weights=mesh.weights, heads=cls.heads, names=cls.names, config=config)

    def test_real_crossbow_is_one_connected_region_and_rigid_across_capture(self):
        result = self.result
        report = result["report"]["props"][0]
        self.assertEqual(report["extraction"]["connectedComponents"], 1)
        self.assertGreater(report["extraction"]["selectedFaces"], 700)
        self.assertLess(report["extraction"]["selectedFaces"], 1000)
        self.assertLess(result["report"]["duplicatedContactVertices"], 100)
        motion = np.load(ARCHER / "mesh-fitted-v1/retargeted_motion.npz")
        points = result["surface"]["positions"][result["propOwners"] == 0]
        distances = np.linalg.norm(points[1:] - points[0], axis=1)
        bone = self.names.index("LeftHand")
        grip = np.array(report["targetGrip"])
        relative = grip - self.heads[bone]
        for rotation, offset in zip(motion["rotations"], motion["offsets"]):
            moved = points @ rotation[bone].T + offset[bone]
            np.testing.assert_allclose(np.linalg.norm(moved[1:] - moved[0], axis=1), distances, atol=1e-12)
            hand = rotation[bone] @ self.heads[bone] + offset[bone]
            np.testing.assert_allclose(rotation[bone] @ grip + offset[bone] - hand,
                                       rotation[bone] @ relative, atol=1e-12)

    def test_export_preserves_textured_geometry_and_rotated_normals(self):
        result = self.result
        surface = result["surface"]
        tmp_root = ROOT / "artifacts/tmp_prop_attachment_tests"
        tmp_root.mkdir(exist_ok=True)
        temporary = tmp_root / uuid.uuid4().hex
        temporary.mkdir()
        path = temporary / "repaired.glb"
        try:
            write_skinned_mesh(path, positions=surface["positions"], indices=surface["indices"],
                bone_names=self.names, parents=self.parents, heads=self.heads,
                joints=result["joints"], weights=result["weights"],
                source_glb=ARCHER / "t-pose/mesh.glb", uvs=surface["uvs"], normals=surface["normals"])
            loaded = load_render_surface(path)
            for key in ("positions", "uvs", "normals"):
                np.testing.assert_allclose(loaded[key], surface[key], atol=1e-7)
            np.testing.assert_array_equal(loaded["indices"], surface["indices"])
            np.testing.assert_array_equal(loaded["baseColor"], self.surface["baseColor"])
        finally:
            path.unlink(missing_ok=True)
            temporary.rmdir()


if __name__ == "__main__":
    unittest.main()
