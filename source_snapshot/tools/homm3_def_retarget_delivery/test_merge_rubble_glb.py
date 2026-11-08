"""merge_rubble_glb appends a shatter's rubble to the body primitive losslessly and refuses anything else; the ship,
freeze and validator wiring around it.

    python -m unittest tools/homm3_def_retarget_delivery/test_merge_rubble_glb.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import merge_rubble_glb as M  # noqa: E402
from glbpatch import Glb  # noqa: E402

TINY, ONE = [1e-4] * 3, [1.0] * 3


class Builder:
    def __init__(self):
        self.js = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [],
                   "nodes": [], "meshes": [], "skins": [], "materials": [{"name": "body"}, {"name": "other"}],
                   "animations": []}
        self.bin = bytearray()

    def acc(self, arr, ctype, typ, minmax=False):
        arr = np.ascontiguousarray(arr)
        self.bin += b"\0" * (-len(self.bin) % 4)
        self.js["bufferViews"].append({"buffer": 0, "byteOffset": len(self.bin), "byteLength": arr.nbytes})
        self.bin += arr.tobytes()
        a = {"bufferView": len(self.js["bufferViews"]) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        self.js["accessors"].append(a)
        return len(self.js["accessors"]) - 1

    def sparse(self, count, idx, vals):
        i = self.acc(np.array(idx, np.uint16), 5123, "SCALAR")
        v = self.acc(np.array(vals, np.float32), 5126, "VEC3")
        for k in (i, v):
            self.js["accessors"][k]["_drop"] = True
        a = {"componentType": 5126, "count": count, "type": "VEC3", "min": [-1, -1, -1], "max": [1, 1, 1],
             "sparse": {"count": len(idx), "indices": {"bufferView": self.js["accessors"][i]["bufferView"], "componentType": 5123},
                        "values": {"bufferView": self.js["accessors"][v]["bufferView"]}}}
        self.js["accessors"].append(a)
        return len(self.js["accessors"]) - 1

    def prim(self, pos, tris, joint, material=0, targets=None):
        n = len(pos)
        attrs = {"POSITION": self.acc(np.array(pos, np.float32), 5126, "VEC3", True),
                 "NORMAL": self.acc(np.tile(np.float32([0, 1, 0]), (n, 1)), 5126, "VEC3"),
                 "TEXCOORD_0": self.acc(np.zeros((n, 2), np.float32) + 0.25, 5126, "VEC2"),
                 "JOINTS_0": self.acc(np.tile(np.uint8([joint, 0, 0, 0]), (n, 1)), 5121, "VEC4"),
                 "WEIGHTS_0": self.acc(np.tile(np.float32([1, 0, 0, 0]), (n, 1)), 5126, "VEC4")}
        p = {"attributes": attrs, "indices": self.acc(np.array(tris, np.uint16).reshape(-1, 1), 5123, "SCALAR"),
             "material": material}
        if targets:
            p["targets"] = targets
        return p

    def anim(self, name, channels):
        a = {"name": name, "channels": [], "samplers": []}
        for node, path, times, vals in channels:
            vals = np.array(vals, np.float32)
            a["samplers"].append({"input": self.acc(np.array(times, np.float32).reshape(-1, 1), 5126, "SCALAR", True),
                                  "output": self.acc(vals.reshape(len(times), -1) if path != "weights" else vals.reshape(-1, 1),
                                                     5126, {1: "SCALAR", 3: "VEC3", 4: "VEC4"}[vals.reshape(len(times), -1).shape[1]]
                                                     if path != "weights" else "SCALAR"),
                                  "interpolation": "LINEAR"})
            a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": node, "path": path}})
        self.js["animations"].append(a)

    def write(self, path):
        for a in self.js["accessors"]:
            a.pop("_drop", None)
        self.js["buffers"][0]["byteLength"] = len(self.bin)
        g = Glb.__new__(Glb)
        g.json, g.bin = self.js, self.bin
        Path(path).write_bytes(g.to_bytes())


def fixture(path, *, rubble_material=0, rubble_targets=False, rubble_name="u_Rubble", rubble_skin=0):
    b = Builder()
    # nodes: 0 Root, 1 RubbleRoot, 2 Chunk_00, 3 body, 4 rubble
    b.js["nodes"] = [{"name": "Root", "children": [1]}, {"name": "RubbleRoot", "children": [2], "scale": TINY},
                     {"name": "Chunk_00"}, {"name": "u", "mesh": 0, "skin": 0}, {"name": rubble_name, "mesh": 1, "skin": rubble_skin}]
    dense = b.acc(np.array([[0, .1, 0], [0, 0, 0], [0, 0, 0], [.2, 0, 0]], np.float32), 5126, "VEC3", True)
    sparse = b.sparse(4, [1, 2], [[0, 0, .3], [0, .4, 0]])
    body = b.prim([[0, 0, 0], [1, 0, 0], [1, 2, 0], [0, 2, 0]], [0, 1, 2, 0, 2, 3], 0,
                  targets=[{"POSITION": dense}, {"POSITION": sparse}])
    rub_t = [{"POSITION": b.acc(np.zeros((3, 3), np.float32), 5126, "VEC3", True)}] if rubble_targets else None
    rubble = b.prim([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [0, 1, 2], 1, rubble_material, rub_t)
    b.js["meshes"] = [{"primitives": [body], "weights": [0, 0]}, {"primitives": [rubble]}]
    ibm = b.acc(np.tile(np.eye(4, dtype=np.float32).reshape(1, 16), (2, 1)), 5126, "MAT4")
    b.js["skins"] = [{"joints": [0, 2], "inverseBindMatrices": ibm}, {"joints": [0, 2]}]
    b.anim("Unit_Death", [(1, "scale", [1 / 12, 2 / 12, 3 / 12, 4 / 12], [TINY, TINY, ONE, ONE]),
                          (3, "weights", [1 / 12, 2 / 12, 3 / 12, 4 / 12], [1, 0, 0, 1, 0, 0, 0, 0])])
    b.anim("Unit_Idle", [(1, "scale", [1 / 12, 3.0], [TINY, TINY]),
                         (3, "weights", [1 / 12, 3.0], [0, 0, 0, 0])])
    b.write(path)


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rubble_rides_the_body_primitive_losslessly(self):
        fixture(self.d / "a.glb")
        rec = M.merge(self.d / "a.glb", self.d / "m.glb", ["u_Rubble"])   # check_equivalent runs inside
        self.assertEqual((rec["bodyVertices"], rec["totalVertices"]), (4, 7))
        self.assertEqual(rec["merged"], [{"node": "u_Rubble", "sourceMesh": 1, "firstVertex": 4, "vertices": 3, "triangles": 1}])
        g = Glb.load(self.d / "m.glb")
        self.assertEqual(len(g.json["meshes"]), 1)
        skinned = [n["name"] for n in g.json["nodes"] if "mesh" in n]
        self.assertEqual(skinned, ["u"])
        p = g.json["meshes"][0]["primitives"][0]
        dense, sparse = (M.read_accessor(g, t["POSITION"]) for t in p["targets"])
        self.assertTrue(np.allclose(dense[3], [.2, 0, 0]) and not dense[4:].any())
        self.assertTrue(np.allclose(sparse[2], [0, .4, 0]) and not sparse[4:].any())
        self.assertIn("sparse", g.json["accessors"][p["targets"][1]["POSITION"]])      # stays sparse, count grew
        idx = M.read_accessor(g, p["indices"]).reshape(-1)
        self.assertEqual(idx[-3:].tolist(), [4, 5, 6])
        self.assertEqual(M.read_accessor(g, p["attributes"]["JOINTS_0"])[4:, 0].tolist(), [1, 1, 1])
        self.assertEqual(M.verify(self.d / "m.glb")["totalVertices"], 7)
        # nothing unreferenced is kept
        used = {v for v in p["attributes"].values()} | {p["indices"]} | {t["POSITION"] for t in p["targets"]}
        used |= {g.json["skins"][0]["inverseBindMatrices"]}
        used |= {k for a in g.json["animations"] for s in a["samplers"] for k in (s["input"], s["output"])}
        self.assertEqual(used, set(range(len(g.json["accessors"]))))

    def test_refusals(self):
        cases = {"material": dict(rubble_material=1), "targets": dict(rubble_targets=True),
                 "skin": dict(rubble_skin=1)}
        for what, kw in cases.items():
            with self.subTest(what):
                fixture(self.d / "a.glb", **kw)
                with self.assertRaises(M.MergeError):
                    M.merge(self.d / "a.glb", self.d / "m.glb", ["u_Rubble"])
        fixture(self.d / "a.glb", rubble_name="u_Cape")
        with self.assertRaises(M.MergeError):
            M.merge(self.d / "a.glb", self.d / "m.glb", ["u_Cape"])
        fixture(self.d / "a.glb")
        with self.assertRaises(M.MergeError):
            M.merge(self.d / "a.glb", self.d / "m.glb", ["v_Rubble"])
        M.merge(self.d / "a.glb", self.d / "m.glb", ["u_Rubble"])
        with self.assertRaises(M.MergeError):                                   # already merged
            M.merge(self.d / "m.glb", self.d / "m2.glb", ["u_Rubble"])

    def test_verify_refuses_a_tampered_stamp(self):
        fixture(self.d / "a.glb")
        M.merge(self.d / "a.glb", self.d / "m.glb", ["u_Rubble"])
        g = Glb.load(self.d / "m.glb")
        g.json["asset"]["extras"][M.STAMP]["totalVertices"] = 8
        (self.d / "t.glb").write_bytes(g.to_bytes())
        with self.assertRaises(M.MergeError):
            M.verify(self.d / "t.glb")


class Rows(unittest.TestCase):
    def doc(self):
        return {"units": [{"labSid": "u", "albedo": "basecolor", "deferMeshes": {"u_Rubble": "old"}, "frozen": {}},
                          {"labSid": "v", "frozen": {}}]}

    def test_rows_move_rubble_in_place_and_are_idempotent(self):
        doc = self.doc()
        self.assertEqual(M.migrate_rows(doc, ["u"]), ["u: u_Rubble"])
        row = doc["units"][0]
        self.assertEqual(list(row), ["labSid", "albedo", "mergeMeshes", "frozen"])
        self.assertEqual(row["mergeMeshes"], {"u_Rubble": M.MERGE_REASON})
        self.assertEqual(M.migrate_rows(doc, ["u"]), [])
        with self.assertRaises(M.MergeError):
            M.migrate_rows(doc, ["v"])

    def test_a_refreeze_keeps_the_opt_in(self):
        import freeze_slice
        new = {"labSid": "u", "deferMeshes": {"u_Rubble": freeze_slice.RUBBLE_REASON}, "frozen": {}}
        old = self.doc()
        M.migrate_rows(old, ["u"])
        self.assertEqual(freeze_slice.keep_merge_opt_in(dict(new), old["units"])["mergeMeshes"], {"u_Rubble": M.MERGE_REASON})
        kept = freeze_slice.keep_merge_opt_in(dict(new), self.doc()["units"])
        self.assertNotIn("mergeMeshes", kept)


class ShipWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        import ship_def_retarget_slice as S
        self.S = S

    def tearDown(self):
        self.tmp.cleanup()

    def test_probe_checks_sample_the_break_and_the_heap(self):
        fixture(self.d / "a.glb")
        plan = {"unit": "u", "mergedMeshes": [{"node": "u_Rubble", "firstVertex": 4, "vertices": 3}]}
        checks = self.S.rubble_probe_checks(plan, self.d / "a.glb")
        self.assertEqual([(c["clip"], round(c["t"], 4), c["values"][2:]) for c in checks],
                         [("Unit_Death", round(2 / 12, 4), [0.0, self.S.RUBBLE_COLLAPSED_MAX]),
                          ("Unit_Death", round(4 / 12, 4), [self.S.RUBBLE_SPREAD_MIN, 1e6]),
                          ("Unit_Idle", round(1 / 12, 4), [0.0, self.S.RUBBLE_COLLAPSED_MAX])])
        self.assertEqual(self.S.rubble_probe_checks({"unit": "u", "mergedMeshes": []}, self.d / "a.glb"), [])

    def test_merge_master_records_ranges_and_later_stages_reverify(self):
        fixture(self.d / "a.glb")
        plan = {"unit": "u", "mergedMeshes": [{"node": "u_Rubble", "reason": "r"}]}
        out = self.S.merge_master(plan, self.d / "a.glb", self.d / "m.glb")
        self.assertEqual(out, self.d / "m.glb")
        self.assertEqual(plan["mergedMeshes"][0]["firstVertex"], 4)
        mm = self.S.verify_merged_master(plan, self.S.sha(self.d / "a.glb"))
        self.assertEqual(mm["totalVertices"], 7)
        with self.assertRaises(self.S.ShipError):
            self.S.verify_merged_master(plan, "0" * 64)
        with self.assertRaises(self.S.ShipError):                               # prepare never recorded the merge
            self.S.verify_merged_master({"unit": "u", "mergedMeshes": [{"node": "u_Rubble", "reason": "r"}]}, "x")

    def test_validator_accepts_only_the_plan_merge(self):
        import validate_homm3_def_retarget_delivery_contract as V
        fixture(self.d / "a.glb")
        plan = {"unit": "u", "mergedMeshes": [{"node": "u_Rubble", "reason": "r"}]}
        self.S.merge_master(plan, self.d / "a.glb", self.d / "m.glb")
        row = {"labSid": "u", "mergeMeshes": {"u_Rubble": "r"}}
        lab = {"masterGlbSha256": self.S.sha(self.d / "m.glb"), "mesh": {"vertexCount": 7},
               "mergedMeshes": [{"node": "u_Rubble"}]}
        errors = []
        self.assertEqual(V.merged_master_checks("t", "u", row, plan, lab, errors), self.S.sha(self.d / "a.glb"))
        self.assertEqual(errors, [])
        V.merged_master_checks("t", "u", row, plan, {**lab, "mesh": {"vertexCount": 4}}, errors)
        V.merged_master_checks("t", "u", {"labSid": "u"}, plan, lab, errors)
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
