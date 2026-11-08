import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attachment_repair import boundary_gaps, consolidate_redundant_owner, reassign_cut_boundary_weights, split_attachment, topology_traced_weights


class AttachmentRepairTests(unittest.TestCase):
    def setUp(self):
        self.skin = {
            "vertices": np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]),
            "triangles": np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64),
            "uvs": np.array([[0., 0], [1, 0], [1, 1], [0, 1]]),
            "regions": np.array(["body", "body", "prop", "prop"]),
            "weights": np.array([[1., 0], [.7, .3], [.2, .8], [0., 1.]]),
            "names": np.array(["body", "prop"]),
            "parents": np.array([-1, 0], dtype=np.int64),
            "inverseBind": np.eye(4)[None].repeat(2, axis=0),
            "albedo": np.arange(8).reshape(4, 2),
        }

    def test_split_preserves_rest_uv_faces_and_body_weights(self):
        original = {key: value.copy() for key, value in self.skin.items()}
        result, report = split_attachment(self.skin, [1], "prop")
        self.assertEqual(result["triangles"].shape, self.skin["triangles"].shape)
        self.assertTrue(np.array_equal(result["triangles"][0], self.skin["triangles"][0]))
        self.assertTrue(np.array_equal(result["vertices"][:4], self.skin["vertices"]))
        self.assertTrue(np.array_equal(result["uvs"][:4], self.skin["uvs"]))
        self.assertTrue(np.array_equal(result["albedo"], self.skin["albedo"]))
        self.assertTrue(np.array_equal(result["weights"][:3], self.skin["weights"][:3]))
        self.assertTrue(np.array_equal(result["weights"][3], [0., 1.]))
        self.assertTrue(np.array_equal(result["weights"][4], [0., 1.]))
        self.assertEqual(report["sharedBoundary"], [[0, 4], [2, 5]])
        self.assertEqual(report["sourceVertexIds"], [0, 1, 2, 3, 0, 2])
        self.assertTrue(np.array_equal(self.skin["vertices"], original["vertices"]))

    def test_selected_interior_vertex_is_owned_in_place(self):
        skin = dict(self.skin)
        skin["triangles"] = np.array([[0, 1, 2], [2, 3, 1]], dtype=np.int64)
        result, report = split_attachment(skin, [0, 1], "prop")
        self.assertEqual(report["sharedBoundary"], [])
        self.assertTrue(np.array_equal(result["weights"][1], [0., 1.]))

    def test_rigid_transform_keeps_rest_duplication_exact(self):
        result, report = split_attachment(self.skin, [1], "prop")
        transform = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.]])
        animated = result["vertices"] @ transform.T
        gaps = boundary_gaps(animated, report["sharedBoundary"])
        self.assertEqual(gaps["maxDistance"], 0.0)
        self.assertEqual(gaps["acceptance"], "not evaluated")

    def test_object_string_regions_are_serializable_without_pickle(self):
        skin = dict(self.skin)
        skin["regions"] = np.array(["body", "body", "prop", "prop"], dtype=object)
        repaired, _ = split_attachment(skin, [1], "prop")
        self.assertNotEqual(repaired["regions"].dtype, object)
        path = Path(__file__).resolve().parent / "artifacts" / "attachment_regions_regression.npz"
        path.parent.mkdir(exist_ok=True)
        try:
            np.savez(path, **repaired)
            with np.load(path, allow_pickle=False) as loaded:
                self.assertTrue(np.array_equal(loaded["regions"], repaired["regions"]))
        finally:
            path.unlink(missing_ok=True)

    def test_nonstring_regions_fail_closed(self):
        skin = dict(self.skin)
        skin["regions"] = np.array(["body", 1, "prop", "prop"], dtype=object)
        with self.assertRaises(ValueError): split_attachment(skin, [1], "prop")

    def test_malformed_inputs_fail_closed(self):
        with self.assertRaises(ValueError): split_attachment(self.skin, [0, 0], "prop")
        with self.assertRaises(ValueError): split_attachment(self.skin, [3], "prop")
        bad = dict(self.skin, weights=self.skin["weights"].copy())
        bad["weights"][0, 0] = np.nan
        with self.assertRaises(ValueError): split_attachment(bad, [1], "prop")
        with self.assertRaises(ValueError): split_attachment(self.skin, [1], "missing")
        with self.assertRaises(ValueError): boundary_gaps(np.zeros((2, 3)), [[0, 4]])

    def test_contract_rejects_empty_selection_and_bad_skeleton_dimension(self):
        with self.assertRaises(ValueError): split_attachment(self.skin, [], "prop")
        with self.assertRaises(ValueError): split_attachment(dict(self.skin, triangles=np.empty((0, 3), dtype=np.int64)), [0], "prop")
        bad = dict(self.skin, weights=np.ones((4, 3)) / 3)
        with self.assertRaises(ValueError): split_attachment(bad, [1], "prop")

    def test_contract_rejects_normalization_drift_and_nonfinite_uv(self):
        bad_weights = dict(self.skin, weights=self.skin["weights"].copy())
        bad_weights["weights"][0, 0] += 2e-6
        with self.assertRaises(ValueError): split_attachment(bad_weights, [1], "prop")
        bad_uvs = dict(self.skin, uvs=self.skin["uvs"].copy())
        bad_uvs["uvs"][0, 0] = np.nan
        with self.assertRaises(ValueError): split_attachment(bad_uvs, [1], "prop")

    def test_boundary_gaps_rejects_float_pair_ids(self):
        with self.assertRaises(ValueError): boundary_gaps(np.zeros((2, 3)), [[0.0, 1.0]])

    def test_consolidates_redundant_terminal_owner_with_lbs_parity(self):
        worlds = np.tile(np.eye(4), (2, 2, 1, 1))
        worlds[1, 0, 0, 3] = 2.0
        worlds[1, 1, 0, 3] = 2.0
        result, report = consolidate_redundant_owner(self.skin, worlds, "prop")
        self.assertTrue(np.allclose(result["weights"][:, 0], self.skin["weights"][:, 0] + self.skin["weights"][:, 1]))
        self.assertTrue(np.all(result["weights"][:, 1] == 0))
        self.assertEqual(report["parent"], "body")
        self.assertLessEqual(report["maxMatrixError"], 1e-6)
        self.assertLessEqual(report["maxVertexError"], 1e-6)

    def test_consolidation_rejects_nonredundant_rotation_root_and_nonleaf(self):
        worlds = np.tile(np.eye(4), (2, 2, 1, 1))
        worlds[1, 1, :2, :2] = [[0., -1.], [1., 0.]]
        with self.assertRaises(ValueError): consolidate_redundant_owner(self.skin, worlds, "prop")
        with self.assertRaises(ValueError): consolidate_redundant_owner(self.skin, worlds, "body")
        nonleaf = dict(self.skin, names=np.array(["body", "prop", "child"]), parents=np.array([-1, 0, 1]),
                       weights=np.column_stack([self.skin["weights"], np.zeros(4)]), inverseBind=np.eye(4)[None].repeat(3, axis=0))
        with self.assertRaises(ValueError): consolidate_redundant_owner(nonleaf, np.tile(np.eye(4), (2, 3, 1, 1)), "prop")

    def test_cut_ring_reassignment_drops_body_side_owner_creep(self):
        result, _ = split_attachment(self.skin, [1], "prop")
        original = result["weights"].copy()
        out, report = reassign_cut_boundary_weights(result, [1], "prop", rings=1)
        weights = out["weights"]
        self.assertEqual(report["seamSourceCount"], 2)
        self.assertEqual(report["duplicateCount"], 2)
        self.assertEqual(report["bodyRowsChanged"], 2)
        self.assertEqual(report["bodyRowsFallback"], 0)
        self.assertAlmostEqual(report["ownerMassDropped"], 1.1)
        self.assertEqual(report["maxOwnerMassRemainingInBodyRing"], 0.0)
        self.assertTrue(report["rowsNormalized"])
        self.assertTrue(np.allclose(weights[0], [1., 0.]))
        self.assertTrue(np.allclose(weights[1], [1., 0.]))
        self.assertTrue(np.allclose(weights[2], [1., 0.]))
        self.assertTrue(np.allclose(weights[3], [0., 1.]))
        self.assertTrue(np.allclose(weights[4], [0., 1.]))
        self.assertTrue(np.allclose(weights[5], [0., 1.]))
        self.assertTrue(np.array_equal(result["weights"], original))

    def test_cut_ring_zero_leaves_neighbors_creeping(self):
        result, _ = split_attachment(self.skin, [1], "prop")
        out, report = reassign_cut_boundary_weights(result, [1], "prop", rings=0)
        self.assertEqual(report["rings"], 0)
        self.assertTrue(np.allclose(out["weights"][0], [1., 0.]))
        self.assertTrue(np.allclose(out["weights"][2], [1., 0.]))
        self.assertTrue(np.allclose(out["weights"][1], [.7, .3]))

    def test_cut_ring_fully_owned_body_row_falls_back_instead_of_zero(self):
        skin = dict(self.skin, weights=self.skin["weights"].copy())
        skin["weights"][0] = [0., 1.]
        result, _ = split_attachment(skin, [1], "prop")
        out, report = reassign_cut_boundary_weights(result, [1], "prop", rings=0)
        self.assertEqual(report["bodyRowsFallback"], 1)
        self.assertTrue(np.allclose(out["weights"][0], [0., 1.]))
        self.assertEqual(report["maxOwnerMassRemainingInBodyRing"], 1.0)
        self.assertTrue(report["rowsNormalized"])

    def test_cut_ring_reassignment_rejects_bad_contracts(self):
        result, _ = split_attachment(self.skin, [1], "prop")
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [1], "prop", rings=-1)
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [1], "prop", rings=1.5)
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [1], "prop", rings=True)
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [1], "missing", rings=1)
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [], "prop")
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(result, [5], "prop")
        bare = dict(result)
        del bare["sourceVertexIds"]
        with self.assertRaises(ValueError): reassign_cut_boundary_weights(bare, [1], "prop")
        with self.assertRaises(TypeError): reassign_cut_boundary_weights([1, 2], [1], "prop")

    def _traced_fixture(self):
        # Two disconnected squares: A is the hand flesh, B the hip flesh.
        # The hip bone reaches toward the hand square but stops 0.9 short,
        # so every A vertex is robustly nearer its own bone while a Euclidean
        # field still bleeds hip onto hand.
        vertices = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                             [3, 0, 0], [4, 0, 0], [4, 1, 0], [3, 1, 0]])
        skin = {
            "vertices": vertices,
            "triangles": np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], dtype=np.int64),
            "weights": np.tile([0.5, 0.5], (8, 1)),
            "names": np.array(["hand", "hip"]),
        }
        heads = np.array([[0.5, -2, 0], [3.5, -2, 0]])
        tails = np.array([[0.5, 3, 0], [1.8, 0.5, 0]])
        return skin, heads, tails

    def test_traced_weights_block_spatially_near_disconnected_bone(self):
        skin, heads, tails = self._traced_fixture()
        out, report = topology_traced_weights(skin, heads, tails, marker_tokens=("ZZZ",))
        weights = out["weights"]
        self.assertTrue(np.all(weights[:4, 1] == 0.0))
        self.assertTrue(np.all(weights[4:, 0] == 0.0))
        self.assertGreater(report["excludedMass"], 0.0)
        self.assertEqual(report["unreachableBoneEntries"], 8)
        self.assertEqual(report["rowsFallback"], 0)
        self.assertTrue(report["rowsNormalized"])
        self.assertTrue(np.allclose(weights.sum(axis=1), 1.0))
        self.assertTrue(np.array_equal(skin["weights"], np.tile([0.5, 0.5], (8, 1))))

    def test_traced_weights_exclude_markers_and_pin_bare_rows(self):
        skin, heads, tails = self._traced_fixture()
        skin["names"] = np.array(["hand", "hip", "Toe_End"])
        heads = np.vstack([heads, [[10., 10, 10]]])
        tails = np.vstack([tails, [[10., 10, 10]]])
        out, report = topology_traced_weights(skin, heads, tails)
        self.assertEqual(report["markerBonesExcluded"], ["Toe_End"])
        self.assertTrue(np.all(out["weights"][:, 2] == 0.0))
        far = dict(skin)
        far["triangles"] = np.array([[0, 1, 2]], dtype=np.int64)
        far["vertices"] = np.array([[10., 0, 0], [11, 0, 0], [11, 1, 0]])
        far["weights"] = np.tile([0.5, 0.5, 0.0], (3, 1))
        far_heads = np.array([[0.5, 0, 0], [0.5, 1, 0], [0., 0, 0]])
        far_tails = np.array([[0.5, 0, 0], [0.5, 1, 0], [0., 0, 0]])
        lone, lone_report = topology_traced_weights(
            far, far_heads, far_tails, trim=0.99, max_influences=1)
        self.assertEqual(lone_report["rowsFallback"], 3)
        self.assertTrue(lone_report["rowsNormalized"])

    def test_traced_weights_weld_coincident_unless_split_barred(self):
        # Two triangles sharing exactly one coincident vertex pair: without
        # split provenance the weld carries influence across, with it the cut
        # stays a barrier.
        vertices = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0],
                             [5., 0, 0], [6, 0, 0], [0, 0, 0]])
        base = {
            "vertices": vertices,
            "triangles": np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64),
            "weights": np.tile([0.5, 0.5], (6, 1)),
            "names": np.array(["near", "far"]),
        }
        heads = np.array([[0.33, 0.33, 0], [5.33, 0.33, 0]])
        tails = heads.copy()
        with_bar, barred_report = topology_traced_weights(
            dict(base, sourceVertexIds=np.array([0, 1, 2, 3, 4, 0])),
            heads, tails, marker_tokens=("ZZZ",))
        self.assertEqual(barred_report["splitPairsBarred"], 1)
        self.assertTrue(np.all(with_bar["weights"][:3, 1] == 0.0))
        self.assertFalse(np.allclose(with_bar["weights"][0], with_bar["weights"][5]))
        welded, _ = topology_traced_weights(base, heads, tails, marker_tokens=("ZZZ",))
        self.assertGreater(welded["weights"][:3, 1].sum(), 0.0)
        self.assertTrue(np.allclose(welded["weights"][0], welded["weights"][5]))
        self.assertTrue(np.allclose(with_bar["weights"][5], welded["weights"][5]))

    def test_traced_weights_enforce_articulation_neighbourhoods(self):
        skin = {
            "vertices": np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]),
            "triangles": np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64),
            "weights": np.tile([0.5, 0.5], (4, 1)),
            "names": np.array(["upper", "lower"]),
        }
        heads = np.array([[0.5, -1, 0], [0.6, -1, 0]])
        tails = np.array([[0.5, 2, 0], [0.6, 2, 0]])
        plain, _ = topology_traced_weights(skin, heads, tails, marker_tokens=("ZZZ",))
        self.assertFalse(bool((plain["weights"][:, 0] == 1.0).all()))
        cut, report = topology_traced_weights(
            skin, heads, tails, parents=np.array([-1, -1]), marker_tokens=("ZZZ",))
        self.assertTrue(report["articulationEnforced"])
        self.assertEqual(report["articulationDroppedEntries"], 4)
        self.assertTrue(np.all(cut["weights"].max(axis=1) == 1.0))
        self.assertTrue(np.allclose(cut["weights"][:, 0], [1., 0, 0, 1]))
        kept, kept_report = topology_traced_weights(
            skin, heads, tails, parents=np.array([-1, 0]), marker_tokens=("ZZZ",))
        self.assertEqual(kept_report["articulationDroppedEntries"], 0)
        self.assertTrue(np.allclose(kept["weights"], plain["weights"]))

    def test_traced_weights_single_influence_is_onehot(self):
        skin, heads, tails = self._traced_fixture()
        out, report = topology_traced_weights(
            skin, heads, tails, max_influences=1, marker_tokens=("ZZZ",))
        self.assertTrue(np.all(out["weights"].max(axis=1) == 1.0))
        self.assertTrue(np.allclose(out["weights"].sum(axis=1), 1.0))
        self.assertTrue(np.all(out["weights"][:4, 1] == 0.0))
        self.assertTrue(np.all(out["weights"][4:, 0] == 0.0))

    def test_traced_weights_rejects_bad_contracts(self):
        skin, heads, tails = self._traced_fixture()
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads[:1], tails)
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, power=0.0)
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, trim=1.0)
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, max_influences=0)
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, max_influences=True)
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, marker_tokens=())
        with self.assertRaises(ValueError): topology_traced_weights(skin, heads, tails, marker_tokens="hip")
        all_markers = dict(skin, names=np.array(["Toe_End", "HeadTop_End"]))
        with self.assertRaises(ValueError):
            topology_traced_weights(all_markers, heads, tails)
        bad_ids = dict(skin, sourceVertexIds=np.array([0, 1]))
        with self.assertRaises(ValueError): topology_traced_weights(bad_ids, heads, tails, marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError):
            topology_traced_weights(skin, heads, tails, parents=np.array([-1]), marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError):
            topology_traced_weights(skin, heads, tails, parents=np.array([0, 0]), marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError):
            topology_traced_weights(skin, heads, tails, parents=np.array([-1, 5]), marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError): topology_traced_weights(dict(skin, triangles=np.empty((0, 3), dtype=np.int64)), heads, tails, marker_tokens=("ZZZ",))
        with self.assertRaises(TypeError): topology_traced_weights([1, 2], heads, tails)

    def test_consolidation_rejects_invalid_numeric_contracts(self):
        worlds = np.tile(np.eye(4), (2, 2, 1, 1))
        with self.assertRaises(ValueError): consolidate_redundant_owner(self.skin, np.empty((0, 2, 4, 4)), "prop")
        bad_weights = dict(self.skin, weights=self.skin["weights"].copy())
        bad_weights["weights"][0] = [-.1, 1.1]
        with self.assertRaises(ValueError): consolidate_redundant_owner(bad_weights, worlds, "prop")
        bad_names = dict(self.skin, names=np.array([["body", "prop"]]))
        with self.assertRaises(ValueError): consolidate_redundant_owner(bad_names, worlds, "prop")
        cyclic = dict(self.skin, parents=np.array([-1, 1]))
        with self.assertRaises(ValueError): consolidate_redundant_owner(cyclic, worlds, "prop")


if __name__ == "__main__":
    unittest.main()
