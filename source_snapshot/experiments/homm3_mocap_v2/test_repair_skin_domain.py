import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repair_skin_domain import condition_body_welds, make_repair_domain, restore_source_owner_support


class RepairSkinDomainTests(unittest.TestCase):
    def mesh(self):
        v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [1, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0]], float)
        t = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.int64)
        w = np.zeros((8, 4), float)
        w[:, 0] = 1
        return v, t, w

    def test_uv_seam_union_and_initial_support(self):
        v, t, w = self.mesh()
        v = np.vstack([v, v[3]])
        w = np.vstack([w, w[3]])
        t = t.copy(); t[1, 2] = 8
        result = make_repair_domain(v, t, w, [2, 3])
        self.assertEqual(result["report"]["trainWeldCount"], 4)
        self.assertTrue(result["allowedSupport"][result["trainMask"], 0].all())

    def test_intentional_split_does_not_couple_ownership(self):
        v, t, w = self.mesh()
        w[2] = [0, 1, 0, 0]
        result = make_repair_domain(v, t, w, [2, 3])
        self.assertEqual(result["ownershipIds"].tolist(), [0, 0, 0, 0, 1, 1, 1, 1])
        self.assertTrue(np.all(result["trainMask"] == (result["ownershipIds"] == 0)))

    def test_still_shared_vertex_refuses(self):
        v, t, w = self.mesh()
        with self.assertRaises(ValueError): make_repair_domain(v, t, w, [0])

    def test_neighbor_adds_absent_body_joint(self):
        v, t, w = self.mesh(); w[3] = [0, 1, 0, 0]; w[4:] = [0, 0, 0, 1]
        result = make_repair_domain(v, t, w, [2, 3], neighbor_rings=1)
        self.assertTrue(result["allowedSupport"][0, 1])

    def test_prop_owner_is_not_added_to_body_support(self):
        v, t, w = self.mesh(); w[4:] = [0, 1, 0, 0]
        result = make_repair_domain(v, t, w, [2, 3])
        self.assertFalse(result["allowedSupport"][0, 1])
        self.assertTrue(result["allowedSupport"][4:, 1].all())

    def test_tiny_positive_initial_support_is_retained(self):
        v, t, w = self.mesh(); w[0] = [1.0 - 1e-12, 1e-12, 0, 0]
        result = make_repair_domain(v, t, w, [2, 3], max_influences=2)
        self.assertTrue(result["allowedSupport"][0, 1])

    def test_limit_and_provenance(self):
        v, t, w = self.mesh(); w[0] = [0.5, 0.5, 0, 0]; w[3] = [0, 0, 1, 0]; w[4:] = [0, 0, 0, 1]
        result = make_repair_domain(v, t, w, [2, 3], max_influences=2)
        self.assertEqual(result["allowedSupport"][0].sum(), 2)
        self.assertTrue(result["report"]["initialSupportNeverRemoved"])
        self.assertGreater(result["report"]["droppedNeighborCandidateCount"], 0)

    def test_malformed_inputs_fail_closed(self):
        v, t, w = self.mesh()
        with self.assertRaises(ValueError): make_repair_domain(v, t, w, [99])
        with self.assertRaises(ValueError): make_repair_domain(v, t, w, [2], neighbor_rings=0)
        with self.assertRaises(ValueError): make_repair_domain(v, t, w, [2], max_influences=9)
        with self.assertRaises(ValueError): make_repair_domain(v, t, w.astype(int), [2])

    def test_conditioning_averages_body_weld_and_is_idempotent(self):
        v, t, w = self.mesh()
        v = np.vstack([v, v[3]])
        w = np.vstack([w, [0, 1, 0, 0]])
        t = t.copy(); t[1, 2] = 8
        result = condition_body_welds(v, t, w, [2, 3])
        self.assertTrue(np.allclose(result["conditionedWeights"][3], [0.5, 0.5, 0, 0]))
        self.assertEqual(result["affectedGroupCount"], 1)
        again = condition_body_welds(v, t, result["conditionedWeights"], [2, 3])
        np.testing.assert_array_equal(again["conditionedWeights"], result["conditionedWeights"])
        self.assertTrue(np.array_equal(result["conditionedWeights"][4:8], w[4:8]))

    def test_conditioning_rejects_more_than_eight_union_support(self):
        v, t, w = self.mesh()
        w = np.pad(w, ((0, 0), (0, 5)))
        w[0] = np.full(9, 1 / 9)
        with self.assertRaises(ValueError): condition_body_welds(v, t, w, [2, 3])

    def test_conditioning_retains_tiny_positive_support(self):
        v, t, w = self.mesh()
        w[0] = [1.0 - 1e-12, 1e-12, 0, 0]
        result = condition_body_welds(v, t, w, [2, 3])
        self.assertGreater(result["conditionedWeights"][0, 1], 0)

    def test_restore_source_owner_support_propagates_body_weld_only(self):
        v, t, w = self.mesh()
        domain = {"ownershipIds": np.array([0, 0, 0, 0, 1, 1, 1, 1], np.int8),
                  "trainMask": np.array([True, True, True, True, False, False, False, False]),
                  "allowedSupport": np.eye(4, dtype=bool)[np.zeros(8, dtype=int)]}
        domain["allowedSupport"][4:, 0] = True
        v = np.vstack([v, v[3]])
        domain["ownershipIds"] = np.append(domain["ownershipIds"], 0)
        domain["trainMask"] = np.append(domain["trainMask"], True)
        domain["allowedSupport"] = np.vstack([domain["allowedSupport"], domain["allowedSupport"][3]])
        source = w.copy(); source[3, 2] = 1e-12; source[3, 0] -= 1e-12; source = np.vstack([source, source[3]])
        source[4:, 0] = 0; source[4:, 1] = 1
        result = restore_source_owner_support(domain, v, source, 2)
        self.assertTrue(result["allowedSupport"][3, 2])
        self.assertTrue(result["allowedSupport"][8, 2])
        self.assertTrue(np.array_equal(result["allowedSupport"][4:8], domain["allowedSupport"][4:8]))
        self.assertTrue(np.array_equal(result["trainMask"], domain["trainMask"]))

    def test_restore_source_owner_support_rejects_overflow_and_bad_inputs(self):
        v, t, w = self.mesh()
        domain = {"ownershipIds": np.zeros(8, np.int8), "trainMask": np.ones(8, bool),
                  "allowedSupport": np.ones((8, 4), bool)}
        with self.assertRaises(ValueError): restore_source_owner_support(domain, v, w, 4)
        domain["allowedSupport"] = np.zeros((8, 9), bool)
        domain["allowedSupport"][:, :8] = True
        source = np.pad(w, ((0, 0), (0, 5)))
        source[:, 8] = 1e-12; source[:, 0] -= 1e-12
        with self.assertRaises(ValueError): restore_source_owner_support(domain, v, source, 8)

    def test_source_owner_is_reserved_before_optional_neighbor_candidates(self):
        v, t, w = self.mesh()
        # Eight existing body supports leave no room for optional neighbors;
        # the mapped owner must be admitted and the optional candidate dropped.
        w = np.pad(w, ((0, 0), (0, 5)))
        w[0] = np.zeros(9); w[0, :7] = 1 / 7
        w[3] = np.zeros(9); w[3, 7] = 1
        source = w.copy(); source[0, 8] = 1e-12; source[0, 0] -= 1e-12
        source[3, 7] = 1
        result = make_repair_domain(v, t, w, [2, 3], source_weights_mapped=source, owner_id=8)
        self.assertTrue(result["allowedSupport"][0, 8])
        self.assertEqual(result["allowedSupport"][0].sum(), 8)
        self.assertGreater(result["report"]["droppedNeighborCandidateCount"], 0)


if __name__ == "__main__": unittest.main()
