import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anatomical_chain_skin import initialize_chain_weights


class AnatomicalChainSkinTests(unittest.TestCase):
    def setUp(self):
        self.joints = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.], [0., 2., 0.]])
        self.parents = np.array([-1, 0, 1, -1], np.int64)
        self.chain = np.array([0, 1, 2], np.int64)

    def run_case(self, vertices, mask=None, joints=None):
        vertices = np.asarray(vertices, float)
        if mask is None:
            mask = np.ones(len(vertices), bool)
        weights = np.zeros((len(vertices), 4), float)
        weights[:, 3] = 1.0
        return initialize_chain_weights(
            vertices, self.joints if joints is None else joints, self.chain,
            self.parents, mask, weights)

    def test_segment_uses_start_owner_not_child(self):
        result = self.run_case([[0.2, 0.4, 0.]])
        self.assertGreater(result["weights"][0, 0], result["weights"][0, 1])
        self.assertAlmostEqual(result["weights"][0].sum(), 1.0)

    def test_terminal_feature_owns_terminal_neighborhood(self):
        result = self.run_case([[2., 0., 0.]])
        self.assertGreater(result["weights"][0, 2], 0.0)

    def test_duplicate_positions_match_and_unmasked_rows_freeze(self):
        vertices = np.array([[.5, .4, 0.], [.5, .4, 0.], [9., 9., 9.]])
        mask = np.array([True, True, False])
        result = self.run_case(vertices, mask)
        self.assertTrue(np.array_equal(result["weights"][0], result["weights"][1]))
        self.assertTrue(np.array_equal(result["weights"][2], [0., 0., 0., 1.]))

    def test_rigid_rotation_and_scale_equivariance(self):
        vertices = np.array([[.3, .7, .2], [1.8, -.2, .1]])
        base = self.run_case(vertices)["weights"]
        theta = .7
        rotation = np.array([[np.cos(theta), -np.sin(theta), 0.],
                             [np.sin(theta), np.cos(theta), 0.], [0., 0., 1.]])
        scale = 3.5
        transformed_joints = self.joints @ rotation.T * scale
        transformed_vertices = vertices @ rotation.T * scale
        transformed = self.run_case(transformed_vertices, joints=transformed_joints)["weights"]
        self.assertTrue(np.allclose(base, transformed, atol=1e-12, rtol=0))

    def test_invalid_chain_and_zero_segment_refuse(self):
        with self.assertRaises(ValueError):
            initialize_chain_weights(
                np.array([[.2, 0., 0.]]), self.joints, np.array([0, 2]),
                self.parents, np.ones(1, bool), np.array([[1., 0., 0., 0.]]))
        zero = self.joints.copy(); zero[1] = zero[0]
        with self.assertRaises(ValueError):
            self.run_case([[.2, 0., 0.]], joints=zero)


class ProfileChainTests(unittest.TestCase):
    def setUp(self):
        from anatomical_chain_skin import initialize_profile_chains
        self.initialize = initialize_profile_chains
        inverse = np.repeat(np.eye(4)[None], 3, axis=0)
        inverse[:, 0, 3] = -np.arange(3)
        self.skin = {"vertices": np.array([[.2, 0., 0.], [.4, .1, 0.], [.6, 0., 0.],
                                            [.2, 0., 0.], [.4, .1, 0.], [.6, 0., 0.]]),
                     "triangles": np.array([[0, 1, 2], [3, 4, 5]]),
                     "weights": np.tile([0., 0., 1.], (6, 1)),
                     "regions": np.array(["limb"] * 6), "names": np.array(["a", "b", "c"]),
                     "parents": np.array([-1, 0, 1]), "inverseBind": inverse}
        self.profile = {"chains": [{"name": "limb", "kind": "polyline", "donor": ("a", "b", "c")}]}

    def test_profile_freezes_prop_even_same_region_and_position(self):
        result = self.initialize(self.skin, np.array([1]), self.profile, ["limb"])
        self.assertTrue(np.array_equal(result["weights"][3:], self.skin["weights"][3:]))
        self.assertFalse(np.array_equal(result["weights"][:3], self.skin["weights"][:3]))
        self.assertEqual(result["report"]["chains"][0]["jointNames"], ["a", "b", "c"])

    def test_empty_selection_is_explicit_identity(self):
        result = self.initialize(self.skin, np.array([1]), self.profile, [])
        self.assertTrue(np.array_equal(result["weights"], self.skin["weights"]))
        self.assertEqual(result["report"]["chains"], [])

    def test_unknown_duplicate_and_empty_body_regions_refuse(self):
        for regions in (["missing"], ["limb", "limb"]):
            with self.assertRaises(ValueError):
                self.initialize(self.skin, np.array([1]), self.profile, regions)
        with self.assertRaises(ValueError):
            self.initialize(self.skin, np.array([0, 1]), self.profile, ["limb"])

    def test_v2_routes_mixed_rigid_label_body_rows_but_freezes_prop(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "weapon", "donorJoints": ["c"]},)}
        skin = self._routed_island_skin(weld_to_target=True)
        original = skin["weights"].copy()
        original[:3] = [1., 0., 0.]
        skin["weights"] = original
        result = self.initialize(skin, np.array([1]), profile, ["limb"],
                                 schema="profile-chain-initialization-v2")
        self.assertTrue(np.array_equal(result["weights"][3:6], original[3:6]))
        self.assertFalse(np.array_equal(result["weights"][:3], original[:3]))
        self.assertEqual(result["report"]["bodyRegionRouting"],
                         {"weapon": {"chain": "limb", "owner": "c", "vertexCount": 3}})

    def test_v2_unrelated_rigid_label_not_present_on_selected_part_is_ignored(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "shield", "donorJoints": ["c"]},)}
        result = self.initialize(self.skin, np.array([1]), profile, ["limb"],
                                 schema="profile-chain-initialization-v2")
        baseline = self.initialize(self.skin, np.array([1]), self.profile, ["limb"])
        self.assertTrue(np.array_equal(result["weights"], baseline["weights"]))
        self.assertEqual(result["report"]["bodyRegionRouting"], {})

    def test_v2_ambiguous_relevant_owner_chain_refuses(self):
        profile = {"chains": [self.profile["chains"][0],
                               {"name": "alternate", "kind": "polyline", "donor": ("a", "c")}],
                   "rigidAttachments": ({"region": "limb", "donorJoints": ["c"]},)}
        with self.assertRaises(ValueError):
            self.initialize(self.skin, np.array([1]), profile, ["limb"],
                            schema="profile-chain-initialization-v2")

    def test_v2_mixed_selected_prop_owner_rows_refuse(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "limb", "donorJoints": ["c"]},)}
        weights = self.skin["weights"].copy()
        weights[3] = [.5, 0., .5]
        with self.assertRaises(ValueError):
            self.initialize(dict(self.skin, weights=weights), np.array([1]), profile, ["limb"],
                            schema="profile-chain-initialization-v2")

    def test_v2_empty_regions_is_identity_with_empty_routing(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "limb", "donorJoints": ["c"]},)}
        result = self.initialize(self.skin, np.array([1]), profile, [],
                                 schema="profile-chain-initialization-v2")
        self.assertTrue(np.array_equal(result["weights"], self.skin["weights"]))
        self.assertEqual(result["report"]["bodyRegionRouting"], {})

    def _routed_island_skin(self, weld_to_target=False):
        vertices = np.vstack([self.skin["vertices"],
                              [[10., 10., 0.], [10.5, 10., 0.], [10., 10.5, 0.]]])
        if weld_to_target:
            vertices[6] = vertices[0]
        triangles = np.vstack([self.skin["triangles"], [[6, 7, 8]]])
        regions = np.array(["limb", "limb", "limb", "weapon", "weapon", "weapon",
                            "weapon", "weapon", "weapon"])
        weights = np.tile([0., 0., 1.], (9, 1))
        return {"vertices": vertices, "triangles": triangles, "weights": weights,
                "regions": regions, "names": self.skin["names"],
                "parents": self.skin["parents"], "inverseBind": self.skin["inverseBind"]}

    def test_v2_disconnected_routed_label_island_refuses(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "weapon", "donorJoints": ["c"]},)}
        with self.assertRaisesRegex(ValueError, "disconnected topology island"):
            self.initialize(self._routed_island_skin(), np.array([1]), profile, ["limb"],
                            schema="profile-chain-initialization-v2")

    def test_v2_exact_position_weld_provides_routing_adjacency(self):
        profile = {"chains": self.profile["chains"],
                   "rigidAttachments": ({"region": "weapon", "donorJoints": ["c"]},)}
        result = self.initialize(self._routed_island_skin(weld_to_target=True), np.array([1]),
                                 profile, ["limb"], schema="profile-chain-initialization-v2")
        self.assertTrue(np.array_equal(result["weights"][0], result["weights"][6]))


if __name__ == "__main__":
    unittest.main()
