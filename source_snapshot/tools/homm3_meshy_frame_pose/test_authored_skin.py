"""Synthetic, in-memory GLB tests for explicit authored skin transfer."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig import authored_skin


HASH = "a" * 64


def fixture(joints=None, weights=None, *, normalized=False):
    positions = np.array([[0, 0, 0], [1, 2, 3]], dtype=np.float32)
    joints = joints if joints is not None else [np.array([[0, 1, 2, 3]] * 2, dtype=np.uint16)]
    weights = weights if weights is not None else [np.array([[.4, .3, .2, .1]] * 2, dtype=np.float32)]
    doc = {"nodes": [{"name": f"source{i}"} for i in range(6)],
           "skins": [{"joints": list(range(6))}], "meshes": [{"primitives": [{"attributes": {}}]}],
           "accessors": [], "bufferViews": []}
    blob = bytearray()
    attributes = doc["meshes"][0]["primitives"][0]["attributes"]

    def add(name, array, norm=False):
        array = np.ascontiguousarray(array)
        component = {"float32": 5126, "uint16": 5123, "uint8": 5121}[str(array.dtype)]
        attributes[name] = len(doc["accessors"])
        doc["accessors"].append({"bufferView": len(doc["bufferViews"]), "count": len(array),
                                 "type": f"VEC{array.shape[1]}", "componentType": component,
                                 "normalized": norm})
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": array.nbytes})
        blob.extend(array.tobytes())

    add("POSITION", positions)
    for i, (j, w) in enumerate(zip(joints, weights)):
        add(f"JOINTS_{i}", j)
        add(f"WEIGHTS_{i}", w, normalized)
    config = {"schema": "authored_skin_map.v1", "sourceMeshSha256": HASH,
              "boneMap": {f"source{i}": f"target{i}" for i in range(6)},
              "reduction": "top4-renormalize"}
    return {"json": doc, "bin": bytes(blob), "sha256": HASH}, positions, config


class AuthoredSkinTests(unittest.TestCase):
    def transfer(self, packed, positions, config, names=None):
        with patch.object(authored_skin, "read_glb", return_value=packed):
            return authored_skin.transfer_authored_skin(Path("source.glb"), positions,
                names if names is not None else [f"target{i}" for i in range(6)], config)

    def test_all_sets_merge_duplicate_source_and_target_before_reduction(self):
        joints = [np.array([[0, 1, 2, 3]] * 2, dtype=np.uint16),
                  np.array([[0, 4, 5, 1]] * 2, dtype=np.uint16)]
        weights = [np.array([[.15, .1, .1, .1]] * 2, dtype=np.float32),
                   np.array([[.1, .2, .15, .1]] * 2, dtype=np.float32)]
        p, v, c = fixture(joints, weights)
        c["boneMap"]["source4"] = "target1"
        before = copy.deepcopy(c)
        result = self.transfer(p, v, c)
        np.testing.assert_array_equal(result["joints"], [[1, 0, 5, 2]] * 2)
        np.testing.assert_allclose(result["weights"], [[.4/.9, .25/.9, .15/.9, .1/.9]] * 2)
        self.assertAlmostEqual(result["report"]["maxDroppedMass"], .1)
        self.assertEqual(result["report"]["influenceSetCount"], 2)
        self.assertEqual(c, before)
        self.assertEqual(result["report"]["boneMap"], c["boneMap"])
        self.assertFalse(result["report"]["accepted"])

    def test_top4_ties_are_stable_and_report_mean_and_max_loss(self):
        j = [np.array([[0, 1, 2, 3]] * 2, dtype=np.uint16),
             np.array([[4, 5, 0, 0]] * 2, dtype=np.uint16)]
        w = [np.array([[.125, .125, .125, .125], [1, 0, 0, 0]], dtype=np.float32),
             np.array([[.25, .25, 0, 0], [0, 0, 0, 0]], dtype=np.float32)]
        result = self.transfer(*fixture(j, w))
        np.testing.assert_array_equal(result["joints"][0], [4, 5, 0, 1])
        np.testing.assert_allclose(result["weights"][0], [1/3, 1/3, 1/6, 1/6])
        self.assertEqual(result["report"]["maxDroppedMass"], .25)
        self.assertEqual(result["report"]["meanDroppedMass"], .125)
        np.testing.assert_allclose(result["weights"].sum(axis=1), 1)

    def test_normalized_unsigned_weights(self):
        for dtype, maximum in ((np.uint8, 255), (np.uint16, 65535)):
            with self.subTest(dtype=dtype):
                w = [np.array([[maximum-3, 1, 1, 1]] * 2, dtype=dtype)]
                result = self.transfer(*fixture(weights=w, normalized=True))
                np.testing.assert_allclose(result["weights"], w[0] / maximum)
                self.assertAlmostEqual(result["report"]["maxDroppedMass"], 0)

    def test_small_unit_total_error_accepted_and_normalized(self):
        w = [np.array([[1.000005, 0, 0, 0]] * 2, dtype=np.float32)]
        result = self.transfer(*fixture(weights=w))
        np.testing.assert_array_equal(result["weights"], [[1, 0, 0, 0]] * 2)

    def test_zero_weight_unmapped_nodes_need_no_inferred_mapping(self):
        p, v, c = fixture(weights=[np.array([[1, 0, 0, 0]] * 2, dtype=np.float32)])
        c["boneMap"] = {"source0": "only"}
        result = self.transfer(p, v, c, ["only"])
        np.testing.assert_array_equal(result["joints"], np.zeros((2, 4), dtype=np.uint16))
        np.testing.assert_array_equal(result["weights"], [[1, 0, 0, 0]] * 2)

    def test_unknown_and_unmapped_names_fail_without_ancestor_fallback(self):
        for case, message in (("source", "unknown source"), ("target", "unknown target"),
                              ("unmapped", "missing from boneMap")):
            p, v, c = fixture()
            p["json"]["nodes"][0]["children"] = [1]
            if case == "source": c["boneMap"]["not-a-node"] = "target0"
            elif case == "target": c["boneMap"]["source0"] = "not-a-target"
            else: del c["boneMap"]["source1"]
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, message):
                self.transfer(p, v, c)

    def test_duplicate_names_and_skin_nodes_rejected(self):
        p, v, c = fixture()
        with self.assertRaisesRegex(ValueError, "unique"):
            self.transfer(p, v, c, ["target0"] * 6)
        p["json"]["nodes"][1]["name"] = "source0"
        with self.assertRaisesRegex(ValueError, "unique"):
            self.transfer(p, v, c)
        p, v, c = fixture()
        p["json"]["skins"][0]["joints"][1] = 0
        with self.assertRaisesRegex(ValueError, "unique"):
            self.transfer(p, v, c)

    def test_hash_schema_and_reduction_must_be_explicit(self):
        for key, value, message in (("sourceMeshSha256", "b"*64, "Sha256"),
                                    ("schema", "other", "schema"),
                                    ("reduction", None, "explicitly")):
            p, v, c = fixture()
            c[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                self.transfer(p, v, c)

    def test_source_position_change_or_reorder_rejected(self):
        p, v, c = fixture()
        for bad in (v[::-1], v[:1], v + .001, np.full_like(v, np.nan)):
            with self.assertRaisesRegex(ValueError, "vertex order"):
                self.transfer(p, bad, c)

    def test_missing_unpaired_or_noncontiguous_sets_rejected(self):
        for case in ("missing", "unpaired", "gap", "malformed"):
            p, v, c = fixture()
            a = p["json"]["meshes"][0]["primitives"][0]["attributes"]
            if case == "missing":
                del a["JOINTS_0"]; del a["WEIGHTS_0"]
            elif case == "unpaired": del a["WEIGHTS_0"]
            elif case == "gap":
                a["JOINTS_2"] = a.pop("JOINTS_0"); a["WEIGHTS_2"] = a.pop("WEIGHTS_0")
            else: a["JOINTS_bad"] = a.pop("JOINTS_0")
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.transfer(p, v, c)

    def test_bad_weights_and_indices_rejected(self):
        for row in ([np.nan, 0, 0, 0], [np.inf, 0, 0, 0], [1.1, -.1, 0, 0],
                    [.5, 0, 0, 0], [0, 0, 0, 0], [1.00002, 0, 0, 0]):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.transfer(*fixture(weights=[np.array([row]*2, dtype=np.float32)]))
        with self.assertRaisesRegex(ValueError, "out of range"):
            self.transfer(*fixture(joints=[np.array([[0, 1, 2, 6]]*2, dtype=np.uint16)]))
        with self.assertRaisesRegex(ValueError, "vertex count"):
            self.transfer(*fixture(weights=[np.array([[1, 0, 0, 0]], dtype=np.float32)]))

    def test_unsupported_accessor_forms_rejected(self):
        for change in ({"componentType": 5123}, {"sparse": {}}, {"type": "VEC3"}):
            p, v, c = fixture()
            p["json"]["accessors"][2].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.transfer(p, v, c)
        p, v, c = fixture()
        p["json"]["accessors"][1]["normalized"] = True
        with self.assertRaisesRegex(ValueError, "unnormalized"):
            self.transfer(p, v, c)

    def test_multiple_primitives_or_skins_rejected(self):
        for case in ("primitive", "skin"):
            p, v, c = fixture()
            if case == "primitive": p["json"]["meshes"][0]["primitives"] *= 2
            else: p["json"]["skins"] *= 2
            with self.assertRaisesRegex(ValueError, "exactly one"):
                self.transfer(p, v, c)


if __name__ == "__main__":
    unittest.main()
