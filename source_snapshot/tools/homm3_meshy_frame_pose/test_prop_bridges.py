"""Explicit attached-rest bridges: generated ownership and source preservation."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.prop_attachment import repair_prop_attachments  # noqa: E402
from test_prop_attachment import grid_fixture  # noqa: E402


class PropBridgeTests(unittest.TestCase):
    def setUp(self):
        self.args = grid_fixture()
        self.bridge = {"a": [5., 2., 1.], "b": [5., 2., 3.],
                       "radius": .1, "sections": 8, "uvSourceFace": 0}
        self.args["config"]["props"][0]["shaftBridges"] = [self.bridge]

    def test_original_faces_and_attributes_preserved_and_counts_exclude_generated(self):
        baseline_args = copy.deepcopy(self.args)
        del baseline_args["config"]["props"][0]["shaftBridges"]
        baseline = repair_prop_attachments(**baseline_args)
        result = repair_prop_attachments(**self.args)
        n, f = len(baseline["sourceVertices"]), len(baseline["surface"]["indices"])
        for key in ("positions", "normals", "uvs"):
            np.testing.assert_array_equal(result["surface"][key][:n], baseline["surface"][key])
        for key in ("joints", "weights", "sourceVertices", "propOwners"):
            np.testing.assert_array_equal(result[key][:n], baseline[key])
        np.testing.assert_array_equal(result["surface"]["indices"][:f], baseline["surface"]["indices"])
        np.testing.assert_array_equal(result["sourceVertices"][result["surface"]["indices"][:f]],
                                      self.args["surface"]["indices"])
        self.assertIs(result["surface"]["baseColor"], self.args["surface"]["baseColor"])
        r = result["report"]
        self.assertEqual(r["preservedTexturedFaces"], f // 3)
        self.assertEqual(r["generatedFaces"], 32)
        self.assertEqual(r["generatedVertices"], 18)
        self.assertEqual(r["outputFaces"], r["sourceFaces"] + r["generatedFaces"])
        self.assertEqual(r["outputVertices"], n + r["generatedVertices"])
        self.assertEqual(r["duplicatedContactVertices"], baseline["report"]["duplicatedContactVertices"])
        for key in ("generatedVertices", "generatedFaces"):
            self.assertEqual(r[key], r["props"][0][key])
            self.assertEqual(baseline["report"][key], 0)
        self.assertEqual(r["props"][0]["renderVertices"], int((result["propOwners"] == 0).sum()))

    def test_attached_rest_endpoints_uv_normals_and_rigid_ownership(self):
        result = repair_prop_attachments(**self.args)
        generated = result["sourceVertices"] == -1
        points = result["surface"]["positions"][generated]
        # The fixture rotates and translates its original prop. Bridge endpoints must
        # already be in attached rest space, never transformed a second time.
        np.testing.assert_allclose(points.min(axis=0), [4.9, 1.9, 1.])
        np.testing.assert_allclose(points.max(axis=0), [5.1, 2.1, 3.])
        np.testing.assert_allclose(np.linalg.norm(result["surface"]["normals"][generated], axis=1), 1.)
        source = self.args["surface"]
        uv = source["uvs"][source["indices"].reshape(-1, 3)[0]].mean(axis=0)
        np.testing.assert_allclose(result["surface"]["uvs"][generated], np.tile(uv, (generated.sum(), 1)))
        np.testing.assert_array_equal(result["propOwners"][generated], 0)
        np.testing.assert_array_equal(result["joints"][generated], np.tile([1, 0, 0, 0], (generated.sum(), 1)))
        np.testing.assert_array_equal(result["weights"][generated], np.tile([1., 0, 0, 0], (generated.sum(), 1)))
        triangle_owners = result["propOwners"][result["surface"]["indices"].reshape(-1, 3)]
        self.assertTrue(np.all(triangle_owners == triangle_owners[:, :1]))

    def test_multiple_bridges_and_props_keep_their_owner_and_bone(self):
        self.args["config"]["props"][0]["shaftBridges"].append(copy.deepcopy(self.bridge))
        second = copy.deepcopy(self.args["config"]["props"][0])
        second.update(name="second", bone="Hips", shaftBridges=[copy.deepcopy(self.bridge)])
        self.args["config"]["props"].append(second)
        with patch("owned_rerig.prop_attachment.extract_prop_faces",
                   side_effect=[(np.array([0]), {}), (np.array([1]), {})]):
            result = repair_prop_attachments(**self.args)
        for owner, count, bone in ((0, 36, 1), (1, 18, 0)):
            selected = (result["sourceVertices"] == -1) & (result["propOwners"] == owner)
            self.assertEqual(selected.sum(), count)
            np.testing.assert_array_equal(result["joints"][selected, 0], bone)
        self.assertEqual(result["report"]["generatedFaces"], 96)

    def test_invalid_recipe_values_fail_closed(self):
        cases = [("radius", value) for value in (0, -1, 1e-12, float("nan"), float("inf"), True, [1])]
        cases += [("sections", value) for value in (0, 2, 8.5, True, float("inf"))]
        cases += [("uvSourceFace", value) for value in (-1, 16, 0.5, True)]
        cases += [("a", [float("nan"), 0, 0]), ("b", [0, float("inf"), 0]),
                  ("a", [0, 0]), ("b", self.bridge["a"])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                args = copy.deepcopy(self.args)
                args["config"]["props"][0]["shaftBridges"][0][field] = value
                with self.assertRaises(ValueError):
                    repair_prop_attachments(**args)

    def test_missing_or_nonfinite_uvs_and_missing_normals_fail_closed(self):
        for key in ("uvs", "normals"):
            args = copy.deepcopy(self.args)
            args["surface"][key] = None
            with self.subTest(attribute=key), self.assertRaisesRegex(ValueError, "requires"):
                repair_prop_attachments(**args)
        self.args["surface"]["uvs"][0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite triangle UVs"):
            repair_prop_attachments(**self.args)

    def test_bridge_recipe_remains_source_hash_pinned(self):
        self.args["config"]["sourceMeshSha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "does not match"):
            repair_prop_attachments(**self.args)


if __name__ == "__main__":
    unittest.main()
