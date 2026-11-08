"""Cheap unit tests of the GLB patch lane (no GLB, no Blender): python -m unittest tools/homm3_glb_patch/test_patch_glb.py"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_numpy as CS  # noqa: E402
import patch_glb as P  # noqa: E402

MW = {"op": "moveWeights", "from": ["Left*"], "to": "Hips",
      "region": [{"axis": "y", "above": 0.0, "ramp": 0.5}]}


class Spec(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [MW]}), [])
        rt = {"op": "rotateTrack", "bone": "Tail", "clips": ["Unit_Move"], "axis": [1, 0, 0], "deg": 20}
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [rt]}), [])

    def test_refusals(self):
        bad = [{"reason": "", "ops": [MW]}, {"reason": "r", "ops": []}, {"reason": "r", "ops": [MW], "x": 1},
               {"reason": "r", "ops": [dict(MW, op="scale")]}, {"reason": "r", "ops": [dict(MW, keep=1.0)]},
               {"reason": "r", "ops": [dict(MW, region=[{"axis": "y", "above": 0, "below": 1, "ramp": 1}])]},
               {"reason": "r", "ops": [dict(MW, region=[{"axis": "w", "above": 0, "ramp": 1}])]},
               {"reason": "r", "ops": [{"op": "rotateTrack", "bone": "T", "clips": ["c"], "axis": [0, 0, 0], "deg": 5}]},
               {"reason": "r", "ops": [{"op": "rotateTrack", "bone": "T", "clips": ["c"], "axis": [1, 0, 0], "deg": 120}]}]
        for s in bad:
            self.assertTrue(P.spec_errors(s), s)


class MoveWeights(unittest.TestCase):
    def body(self):
        # glTF y-up; the region ramps are in Blender axes (y_blender = -z_gltf, z_blender = y_gltf)
        V = np.array([[0, 0, -1.0], [0, 0, -0.25], [0, 0, 1.0]])   # blender y = 1, 0.25, -1
        return SimpleNamespace(jnames=["Hips", "LeftLeg", "LeftFoot", "Spine"], V=V)

    def test_ramp_and_normalised(self):
        b = self.body()
        J = np.array([[1, 2, 3, 0], [1, 0, 0, 0], [1, 0, 0, 0]])
        W = np.array([[0.5, 0.3, 0.2, 0.0], [1.0, 0, 0, 0], [1.0, 0, 0, 0]])
        J2, W2, rec = P.op_move_weights(b, MW, J, W)
        self.assertEqual(rec["vertices"], 2)                     # the third vertex is below the ramp
        np.testing.assert_allclose(W2.sum(1), 1.0)
        d0 = {j: x for j, x in zip(J2[0], W2[0]) if x > 0}
        self.assertAlmostEqual(d0[0], 0.8)                        # both Left* bones moved fully (alpha 1)
        d1 = {j: x for j, x in zip(J2[1], W2[1]) if x > 0}
        self.assertAlmostEqual(d1[0], 0.5)                        # half-way up the ramp
        self.assertAlmostEqual(d1[1], 0.5)
        np.testing.assert_array_equal(J2[2], J[2])

    def test_noop_and_unknown_refuse(self):
        b = self.body()
        J = np.array([[3, 0, 0, 0]] * 3)
        W = np.array([[1.0, 0, 0, 0]] * 3)
        with self.assertRaises(SystemExit):
            P.op_move_weights(b, MW, J, W)
        with self.assertRaises(SystemExit):
            P.op_move_weights(b, dict(MW, to="Nope"), J, W)


    def test_only_with(self):
        b = self.body()
        J = np.array([[1, 3, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]])
        W = np.array([[0.6, 0.4, 0, 0], [1.0, 0, 0, 0], [1.0, 0, 0, 0]])
        op = dict(MW, onlyWith={"bones": ["Spine"], "atLeast": 0.3})
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        J2, W2, rec = P.op_move_weights(b, op, J, W)
        self.assertEqual(rec["vertices"], 1)                     # the pure-LeftLeg vertex in the region is left alone
        np.testing.assert_array_equal(J2[1], J[1])
        self.assertNotEqual(P.spec_errors({"reason": "r", "ops": [dict(MW, onlyWith={"bones": [], "atLeast": 2})]}), [])

class DiffuseWeights(unittest.TestCase):
    def test_spreads_boundary_keeps_welds_and_untouched(self):
        # strip of 4 vertices 0-1-2-3 plus 1b, a seam copy of vertex 1; hard Arm|Spine boundary between 1 and 2
        V = np.array([[0, 0, 0.0], [1, 0, 0], [2, 0, 0], [3, 0, 0], [1, 0, 0]])
        F = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 1]])
        b = SimpleNamespace(jnames=["Spine", "LeftArm", "Hips"], V=V, F=F)
        J = np.array([[1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0], [1, 0, 0, 0]])
        W = np.array([[1.0, 0, 0, 0]] * 5)
        J2, W2, rec = P.op_diffuse_weights(b, {"op": "diffuseWeights", "bones": ["LeftArm"], "iterations": 2,
                                                "alpha": 0.5}, J, W)
        self.assertEqual(rec["vertices"], 3)                     # only vertices weighted to LeftArm move
        np.testing.assert_allclose(W2.sum(1), 1.0)
        d = [{j: x for j, x in zip(J2[i], W2[i]) if x > 0} for i in range(5)]
        self.assertGreater(d[1].get(0, 0), 0.0)                  # Spine weight crossed the boundary
        self.assertEqual(d[1], d[4])                             # weld copies stay identical
        np.testing.assert_array_equal(J2[2], J[2]); np.testing.assert_array_equal(W2[2], W[2])
        with self.assertRaises(SystemExit):
            P.op_diffuse_weights(b, {"op": "diffuseWeights", "bones": ["Nope"], "iterations": 1, "alpha": 0.5}, J, W)

    def test_region_limits_and_skips_other_bones(self):
        # strip 0-1-2-3-4 along x; Spine | LeftArm boundary between 1 and 2; vertex 4 carries Hips (left out of bones)
        V = np.array([[0, 0, 0.0], [1, 0, 0], [2, 0, 0], [3, 0, 0], [4, 0, 0]])
        F = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4]])
        b = SimpleNamespace(jnames=["Spine", "LeftArm", "Hips"], V=V, F=F)
        J = np.array([[0, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0], [2, 0, 0, 0]])
        W = np.array([[1.0, 0, 0, 0]] * 5)
        op = {"op": "diffuseWeights", "bones": ["Spine", "LeftArm"], "iterations": 2, "alpha": 0.5,
              "region": [{"axis": "x", "below": 2.5, "ramp": 0.01}]}
        J2, W2, rec = P.op_diffuse_weights(b, op, J, W)
        d = [{j: x for j, x in zip(J2[i], W2[i]) if x > 0} for i in range(5)]
        self.assertGreater(d[1].get(1, 0), 0.0)                  # inside the region the boundary spreads
        np.testing.assert_array_equal(W2[3], W[3]); np.testing.assert_array_equal(J2[3], J[3])  # outside: untouched
        self.assertNotIn(2, d[2])                                # Hips (not in bones) never diffuses in
        np.testing.assert_array_equal(J2[4], J[4])


class Quat(unittest.TestCase):
    def test_identity_and_compose(self):
        r = np.array([[0.1, 0.2, 0.3, 0.9]])
        r /= np.linalg.norm(r)
        np.testing.assert_allclose(P.qmul(r, np.array([0, 0, 0, 1.0])), r)
        h = np.radians(45) / 2
        q = np.array([np.sin(h), 0, 0, np.cos(h)])
        np.testing.assert_allclose(P.qmul(P.qmul(np.array([[0, 0, 0, 1.0]]), q), q)[0],
                                   [np.sin(2 * h), 0, 0, np.cos(2 * h)], atol=1e-12)


class CorrectiveSmooth(unittest.TestCase):
    def grid(self, n=6):
        xs, ys = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
        V = np.c_[xs.ravel(), ys.ravel(), 0.1 * np.sin(3 * xs.ravel()) * ys.ravel()]
        F = []
        for i in range(n - 1):
            for j in range(n - 1):
                a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1
                F += [[a, b, d], [a, d, c]]
        return V, np.array(F)

    def run_cs(self, V, F, S):
        J = np.zeros((len(V), 4), np.int64)
        W = np.zeros((len(V), 4))
        W[:, 0] = 1
        w = CS.Weld(V, J, W, F)
        cache = w.rest_deltas(V[w.rep])
        return w.corrective(S[w.rep], cache)[w.gid]

    def test_rest_is_fixed_point(self):
        V, F = self.grid()
        np.testing.assert_allclose(self.run_cs(V, F, V), V, atol=1e-9)

    def test_collapsed_island_is_ill_conditioned(self):
        V, F = self.grid()
        tri = np.array([[5.0, 5, 5], [5.001, 5, 5], [5, 5.001, 5]])   # a lone tiny triangle smooths to a point
        V2 = np.r_[V, tri]
        F2 = np.r_[F, [[len(V), len(V) + 1, len(V) + 2]]]
        J = np.zeros((len(V2), 4), np.int64)
        W = np.zeros((len(V2), 4))
        W[:, 0] = 1
        w = CS.Weld(V2, J, W, F2)
        w.rest_deltas(V2[w.rep])
        Sk = np.eye(4)[None]
        _, cond = CS.offsets(w, V2, J, W, Sk, w.rest_deltas(V2[w.rep]), CS.COND_EDGE)
        self.assertFalse(cond[-3:].any())
        self.assertTrue(cond[:len(V)].all())

    def test_winding_and_corner_start_invariant(self):
        V, F = self.grid()
        S = V + np.c_[0.2 * V[:, 1] ** 2, np.zeros(len(V)), 0.1 * V[:, 0]]
        a = self.run_cs(V, F, S)
        b = self.run_cs(V, F[:, ::-1], S)
        c = self.run_cs(V, np.roll(F, 1, axis=1), S)
        np.testing.assert_allclose(a, b, atol=1e-9)
        np.testing.assert_allclose(a, c, atol=1e-9)


SR = {"op": "sitRepose", "clips": {"Unit_Idle": "full", "Unit_MoveStart": "easeOut"}, "pitch": 20, "drop": 0.06,
      "turns": [{"bone": "Neck", "deg": 20}]}


class SitRepose(unittest.TestCase):
    def test_spec(self):
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [SR]}), [])
        bad = [dict(SR, clips={"Unit_Idle": "half"}), dict(SR, clips={}), dict(SR, pitch=90), dict(SR, drop=0.5),
               dict(SR, turns=[{"bone": "Neck"}]), dict(SR, turns=[{"bone": "Neck", "deg": 0}]),
               dict(SR, legs=[["A", "B"]]), {"op": "sitRepose", "clips": {"Unit_Idle": "full"}}, dict(SR, axis=[1, 0, 0])]
        for op in bad:
            self.assertTrue(P.spec_errors({"reason": "r", "ops": [op]}), op)

    def test_weights_match_the_build_ease(self):
        x = np.array([0.0, 0.5, 1.0])
        np.testing.assert_allclose(P.sit_weight("full", x), [1, 1, 1])
        np.testing.assert_allclose(P.sit_weight("easeOut", x), [1, 0.5, 0], atol=1e-12)
        np.testing.assert_allclose(P.sit_weight("easeIn", x), [0, 0.5, 1], atol=1e-12)
        np.testing.assert_allclose(P.sit_weight("bracket", x), [1, 0, 1], atol=1e-12)

    def test_positive_turn_leans_toward_the_front(self):
        np.testing.assert_allclose(P.axis_rot(90) @ [0, 1, 0], [0, 0, 1], atol=1e-12)

    def test_two_bone_keeps_lengths_ankle_and_knee_side(self):
        H0, K0, A0 = np.array([0, 1.0, 0]), np.array([0, 0.5, 0.2]), np.array([0, 0.0, 0])
        H1 = np.array([0, 0.8, -0.1])   # the hip lowered and moved back
        K1, A1 = P.two_bone(H1, H0, K0, A0)
        np.testing.assert_allclose(A1, A0, atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(K1 - H1), np.linalg.norm(K0 - H0))
        self.assertAlmostEqual(np.linalg.norm(A1 - K1), np.linalg.norm(A0 - K0))
        self.assertGreater(K1[2], 0.0)  # the knee bends forward as before



class SetWeights(unittest.TestCase):
    """setWeights: a sha-pinned per-vertex weight table replaces the listed vertices' skin, nothing else."""
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.root, P.ROOT = P.ROOT, self.tmp
        (self.tmp / P.KEY_ROT_DIR).mkdir(parents=True)

    def tearDown(self):
        import shutil
        P.ROOT = self.root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def table(self, verts, count=3, schema=None):
        import json
        raw = json.dumps({"schema": schema or P.WEIGHT_TABLE_SCHEMA, "vertexCount": count, "vertices": verts}).encode()
        rel = f"{P.KEY_ROT_DIR}/w.json"
        (self.tmp / rel).write_bytes(raw)
        return {"op": "setWeights", "table": rel, "sha256": P.sha(raw)}

    def body(self):
        import types
        return types.SimpleNamespace(V=np.zeros((3, 3)), jnames=["A", "B", "C"])

    def test_replaces_listed_vertices_only(self):
        J = np.array([[0, 0, 0, 0]] * 3); W = np.array([[1.0, 0, 0, 0]] * 3)
        J2, W2, rep = P.op_set_weights(self.body(), self.table({"1": {"B": 0.25, "C": 0.75}}), J, W)
        self.assertEqual(J2[1, :2].tolist(), [2, 1]); self.assertEqual(W2[1, :2].tolist(), [0.75, 0.25])
        self.assertTrue((J2[[0, 2]] == J[[0, 2]]).all() and (W2[[0, 2]] == W[[0, 2]]).all())
        self.assertEqual(rep["vertices"], 1)

    def test_refuses_bad_tables(self):
        J = np.zeros((3, 4), int); W = np.zeros((3, 4))
        op = self.table({"1": {"B": 0.5}})
        self.assertTrue(P.weight_table(op)[1])                               # weights must sum to 1
        op = self.table({"1": {"B": 1.0}}); op["sha256"] = "0" * 64
        self.assertTrue(P.weight_table(op)[1])                               # sha pin
        with self.assertRaises(SystemExit):
            P.op_set_weights(self.body(), self.table({"1": {"B": 1.0}}, count=4), J, W)   # other body
        with self.assertRaises(SystemExit):
            P.op_set_weights(self.body(), self.table({"1": {"Z": 1.0}}), J, W)            # unknown bone

class KeyRotations(unittest.TestCase):
    """keyRotations: a sha-pinned per-key offset table, post-multiplied on the channel's own key grid."""
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.root, P.ROOT = P.ROOT, self.tmp
        (self.tmp / P.KEY_ROT_DIR).mkdir(parents=True)

    def tearDown(self):
        import shutil
        P.ROOT = self.root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def table(self, times, quat, name="t.json", **extra):
        import json
        tab = {"schema": P.KEY_ROT_SCHEMA, "clips": {"Unit_Idle": {"Arm": {"times": times, "quat": quat}}}, **extra}
        rel = f"{P.KEY_ROT_DIR}/{name}"
        raw = json.dumps(tab).encode()
        (self.tmp / rel).write_bytes(raw)
        return {"op": "keyRotations", "table": rel, "sha256": P.sha(raw)}

    def glb(self, times):
        from stride_match_glb import Glb
        g = Glb.__new__(Glb)
        g.json = {"nodes": [{"name": "Arm"}], "accessors": [], "bufferViews": [], "buffers": [{"byteLength": 0}]}
        g.bin = bytearray(); g.nodes = g.json["nodes"]; g.names = ["Arm"]; g.parent = {}
        tin = g.append_accessor(np.asarray(times, float)[:, None], "SCALAR")
        out = g.append_accessor(np.tile([0, 0, 0, 1.0], (len(times), 1)), "VEC4")
        g.json["animations"] = [{"name": "Unit_Idle", "samplers": [{"input": tin, "output": out, "interpolation": "LINEAR"}],
                                 "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}]}]
        return g

    def test_applies_per_key(self):
        h = np.radians(30) / 2
        q = [[0, 0, 0, 1.0], [np.sin(h), 0, 0, np.cos(h)]]
        op = self.table([1 / 12, 2 / 12], q)
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        g = self.glb([1 / 12, 2 / 12])
        rec = P.op_key_rotations(g, op)
        a = g.anim("Unit_Idle")
        r = g.read(a["samplers"][a["channels"][0]["sampler"]]["output"])
        np.testing.assert_allclose(r, q, atol=1e-6)
        self.assertAlmostEqual(rec["maxOffsetDeg"], 30.0, places=3)

    def test_refusals(self):
        ok = self.table([1 / 12], [[0, 0, 0, 1.0]])
        bad = [dict(ok, sha256="0" * 64), dict(ok, table="elsewhere/t.json"), dict(ok, table=ok["table"] + "x"),
               self.table([1 / 12], [[0, 0, 0, 2.0]], "n.json"),
               self.table([1 / 12], [[1.0, 0, 0, 0]], "big.json"),          # 180 deg > the cap
               self.table([2 / 12, 1 / 12], [[0, 0, 0, 1.0]] * 2, "order.json"),
               self.table([1 / 12], [[0, 0, 0, 1.0]], "schema.json", schema="other")]
        for op in bad:
            self.assertTrue(P.spec_errors({"reason": "r", "ops": [op]}), op)
        with self.assertRaises(SystemExit):     # the table's times must be the channel's own key grid
            P.op_key_rotations(self.glb([1 / 12, 3 / 12]), ok)

    def test_regrid(self):
        """regrid: true resamples a sparse channel spanning the same first/last key onto the table's grid."""
        h = np.radians(20) / 2
        q = [[0, 0, 0, 1.0], [np.sin(h), 0, 0, np.cos(h)], [0, 0, 0, 1.0]]
        op = self.table([1 / 12, 2 / 12, 3 / 12], q)
        with self.assertRaises(SystemExit):
            P.op_key_rotations(self.glb([1 / 12, 3 / 12]), op)
        op = dict(op, regrid=True)
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        self.assertTrue(P.spec_errors({"reason": "r", "ops": [dict(op, regrid="yes")]}))
        g = self.glb([1 / 12, 3 / 12])
        rec = P.op_key_rotations(g, op)
        a = g.anim("Unit_Idle")
        s0 = a["samplers"][a["channels"][0]["sampler"]]
        np.testing.assert_allclose(g.read(s0["input"]).ravel(), [1 / 12, 2 / 12, 3 / 12], atol=1e-6)
        np.testing.assert_allclose(g.read(s0["output"]), q, atol=1e-6)
        self.assertEqual(rec["regridded"], {"Unit_Idle": ["Arm"]})
        with self.assertRaises(SystemExit):     # a different span is still refused
            P.op_key_rotations(self.glb([1 / 12, 4 / 12]), op)


class KeyTranslations(KeyRotations):
    """keyTranslations: sha-pinned per-time translation deltas, interpolated onto the channel's own key grid."""
    def table(self, times, delta, name="tr.json", **extra):
        import json
        tab = {"schema": P.KEY_TR_SCHEMA, "clips": {"Unit_Idle": {"Arm": {"times": times, "delta": delta}}}, **extra}
        rel = f"{P.KEY_ROT_DIR}/{name}"
        raw = json.dumps(tab).encode()
        (self.tmp / rel).write_bytes(raw)
        return {"op": "keyTranslations", "table": rel, "sha256": P.sha(raw)}

    def glb(self, times):
        g = super().glb(times)
        tr = g.append_accessor(np.tile([0, 1.0, 0], (len(times), 1)), "VEC3")
        a = g.json["animations"][0]
        a["samplers"].append({"input": a["samplers"][0]["input"], "output": tr, "interpolation": "LINEAR"})
        a["channels"].append({"sampler": 1, "target": {"node": 0, "path": "translation"}})
        return g

    def test_applies_per_key(self):
        op = self.table([1 / 12, 3 / 12], [[0, 0, 0.0], [0.2, 0, 0.0]])
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        g = self.glb([1 / 12, 2 / 12, 3 / 12])
        rec = P.op_key_translations(g, op, 1.0)
        a = g.anim("Unit_Idle")
        ch = [c for c in a["channels"] if c["target"]["path"] == "translation"][0]
        np.testing.assert_allclose(g.read(a["samplers"][ch["sampler"]]["output"]),
                                   [[0, 1, 0], [0.1, 1, 0], [0.2, 1, 0]], atol=1e-6)   # interpolated mid key
        self.assertAlmostEqual(rec["maxDeltaOverHeight"], 0.2, places=4)
        with self.assertRaises(SystemExit):     # past KEY_TR_MAX_OVER_H of the body height
            P.op_key_translations(self.glb([1 / 12, 3 / 12]), op, 0.5)

    def test_refusals(self):
        ok = self.table([1 / 12], [[0, 0, 0.0]])
        bad = [dict(ok, sha256="0" * 64), dict(ok, table="elsewhere/t.json"),
               self.table([1 / 12], [[0, 0]], "shape.json"),
               self.table([2 / 12, 1 / 12], [[0, 0, 0.0]] * 2, "order.json"),
               self.table([1 / 12], [[0, 0, 0.0]], "schema.json", schema="other")]
        for op in bad:
            self.assertTrue(P.spec_errors({"reason": "r", "ops": [op]}), op)

    def test_regrid(self):
        """regrid: true resamples a sparse (2-key hold) translation channel onto the table's grid, so a mid-clip
        delta is kept instead of interpolating away."""
        op = self.table([1 / 12, 2 / 12, 3 / 12], [[0, 0, 0.0], [0, 0.2, 0], [0, 0, 0.0]])
        g = self.glb([1 / 12, 3 / 12])
        P.op_key_translations(g, op, 1.0)          # without regrid the mid delta is lost on the 2-key grid
        a = g.anim("Unit_Idle")
        ch = [c for c in a["channels"] if c["target"]["path"] == "translation"][0]
        np.testing.assert_allclose(g.read(a["samplers"][ch["sampler"]]["output"]), [[0, 1, 0], [0, 1, 0]], atol=1e-6)
        op = dict(op, regrid=True)
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        self.assertTrue(P.spec_errors({"reason": "r", "ops": [dict(op, regrid="yes")]}))
        g = self.glb([1 / 12, 3 / 12])
        rec = P.op_key_translations(g, op, 1.0)
        a = g.anim("Unit_Idle")
        s1 = a["samplers"][[c for c in a["channels"] if c["target"]["path"] == "translation"][0]["sampler"]]
        np.testing.assert_allclose(g.read(s1["input"]).ravel(), [1 / 12, 2 / 12, 3 / 12], atol=1e-6)
        np.testing.assert_allclose(g.read(s1["output"]), [[0, 1, 0], [0, 1.2, 0], [0, 1, 0]], atol=1e-6)
        self.assertEqual(rec["regridded"], {"Unit_Idle": ["Arm"]})
        with self.assertRaises(SystemExit):     # a different span is still refused
            P.op_key_translations(self.glb([1 / 12, 4 / 12]), op, 1.0)


class KeyScales(KeyRotations):
    """keyScales: sha-pinned per-time scale factors, multiplied into the scale keys (regridded onto the table's grid)."""
    def table(self, times, factor, name="sc.json", **extra):
        import json
        tab = {"schema": P.KEY_SC_SCHEMA, "clips": {"Unit_Idle": {"Arm": {"times": times, "factor": factor}}}, **extra}
        rel = f"{P.KEY_ROT_DIR}/{name}"
        raw = json.dumps(tab).encode()
        (self.tmp / rel).write_bytes(raw)
        return {"op": "keyScales", "table": rel, "sha256": P.sha(raw)}

    def glb(self, times):
        g = super().glb(times)
        sc = g.append_accessor(np.tile([1.0, 2.0, 1.0], (len(times), 1)), "VEC3")
        a = g.json["animations"][0]
        a["samplers"].append({"input": a["samplers"][0]["input"], "output": sc, "interpolation": "LINEAR"})
        a["channels"].append({"sampler": 1, "target": {"node": 0, "path": "scale"}})
        return g

    def out(self, g):
        a = g.anim("Unit_Idle")
        s = a["samplers"][[c for c in a["channels"] if c["target"]["path"] == "scale"][0]["sampler"]]
        return g.read(s["input"]).ravel(), g.read(s["output"])

    def test_applies_per_key(self):
        op = self.table([1 / 12, 2 / 12, 3 / 12], [[1, 1, 1.0], [1, 1.5, 1], [1, 1, 1.0]])
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [op]}), [])
        rec = P.op_key_scales(self.glb([1 / 12, 2 / 12, 3 / 12]), op)
        self.assertEqual(rec["factorRange"], [1.0, 1.5])
        g = self.glb([1 / 12, 3 / 12])            # a 2-key hold is resampled onto the table's grid
        rec = P.op_key_scales(g, op)
        t, v = self.out(g)
        np.testing.assert_allclose(t, [1 / 12, 2 / 12, 3 / 12], atol=1e-6)
        np.testing.assert_allclose(v, [[1, 2, 1], [1, 3, 1], [1, 2, 1]], atol=1e-6)
        self.assertEqual(rec["regridded"], {"Unit_Idle": ["Arm"]})
        with self.assertRaises(SystemExit):     # a different span is refused
            P.op_key_scales(self.glb([1 / 12, 4 / 12]), op)

    def test_refusals(self):
        ok = self.table([1 / 12], [[1, 1, 1.0]])
        bad = [dict(ok, sha256="0" * 64), dict(ok, table="elsewhere/t.json"),
               self.table([1 / 12], [[1, 1]], "shape.json"),
               self.table([2 / 12, 1 / 12], [[1, 1, 1.0]] * 2, "order.json"),
               self.table([1 / 12], [[1, 2.5, 1.0]], "range.json"),
               self.table([1 / 12], [[1, 1, 1.0]], "schema.json", schema="other")]
        for op in bad:
            self.assertTrue(P.spec_errors({"reason": "r", "ops": [op]}), op)

    def test_regrid(self):
        pass                                     # covered by test_applies_per_key (keyScales always regrids)


class TargetPoses(unittest.TestCase):
    """A one-frame clip holds its CS target on both keys; the same pose on every key reads as one target pose."""
    def glb(self, arm_quats):
        from stride_match_glb import Glb
        from types import SimpleNamespace
        g = Glb.__new__(Glb)
        g.json = {"nodes": [{"name": "Arm"}, {"name": "Body"}], "accessors": [], "bufferViews": [], "buffers": [{"byteLength": 0}]}
        g.bin = bytearray(); g.nodes = g.json["nodes"]; g.names = ["Arm", "Body"]; g.parent = {}
        tin = g.append_accessor(np.array([[1 / 12], [2 / 12]]), "SCALAR")
        rot = g.append_accessor(np.asarray(arm_quats, float), "VEC4")
        w = g.append_accessor(np.ones((2, 1)), "SCALAR")
        g.json["animations"] = [{"name": "Unit_MoveStart", "samplers": [
            {"input": tin, "output": rot, "interpolation": "LINEAR"}, {"input": tin, "output": w, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                         {"sampler": 1, "target": {"node": 1, "path": "weights"}}]}]
        return g, SimpleNamespace(target_names=["CS_Unit_MoveStart_001"], node=1)

    def test_held_frame_is_one_pose(self):
        g, body = self.glb([[0, 0, 0, 1.0], [0, 0, 0, 1.0]])
        (r,) = P.target_poses(g, body)
        self.assertEqual(r[:2], (0, "Unit_MoveStart")); self.assertAlmostEqual(r[2], 1 / 12, places=6)

    def test_different_poses_refuse(self):
        h = np.radians(20) / 2
        g, body = self.glb([[0, 0, 0, 1.0], [np.sin(h), 0, 0, np.cos(h)]])
        with self.assertRaises(SystemExit):
            P.target_poses(g, body)

    def orphan_glb(self, orphan_w):
        from types import SimpleNamespace
        g, _ = self.glb([[0, 0, 0, 1.0], [0, 0, 0, 1.0]])
        a = g.json["animations"][0]
        a["samplers"][1]["output"] = g.append_accessor(np.array([[1.0], [orphan_w], [1.0], [orphan_w]]), "SCALAR")
        return g, SimpleNamespace(target_names=["CS_Unit_MoveStart_001", "CS_Unit_ShootFront_001"], node=1)

    def test_skipped_clip_target_is_an_orphan(self):
        from unittest import mock
        g, body = self.orphan_glb(0.0)
        with mock.patch.object(P.skip_def_groups, "skipped_clips", return_value={"Unit_ShootFront": "never shoots"}):
            self.assertEqual([r[:2] for r in P.target_poses(g, body, "u")], [(0, "Unit_MoveStart")])
        with self.assertRaises(SystemExit):          # not skipped by the config: still refused
            P.target_poses(g, body)

    def test_played_orphan_refuses(self):
        from unittest import mock
        g, body = self.orphan_glb(0.5)
        with mock.patch.object(P.skip_def_groups, "skipped_clips", return_value={"Unit_ShootFront": "never shoots"}):
            with self.assertRaises(SystemExit):
                P.target_poses(g, body, "u")


class MasterSync(unittest.TestCase):
    SEGS = [{"contractSuffix": "Idle", "globalStart": 0, "globalEnd": 3, "frameCount": 3},
            {"contractSuffix": "Hitted", "globalStart": 3, "globalEnd": 5, "frameCount": 2},
            {"contractSuffix": "Idle", "globalStart": 5, "globalEnd": 6, "frameCount": 1},      # bookend
            {"contractSuffix": "Death", "globalStart": 6, "globalEnd": 7, "frameCount": 1}]
    SRC = ["i0", "i1", "i2", "h0", "h1", "i0", "d0"]

    def test_frame_map_follows_build_unit(self):
        m = P.master_frame_map(self.SEGS, self.SRC)
        self.assertEqual(m, [("Unit_Idle", 0), ("Unit_Idle", 1), ("Unit_Idle", 2), ("Unit_Hitted", 0),
                             ("Unit_Hitted", 1), ("Unit_Idle", 0), ("Unit_Death", 0)])
        self.assertIsNone(P.master_frame_map(self.SEGS, self.SRC[:5] + ["x", "d0"])[5])   # no shipped frame of that PNG

    def glb(self):
        from stride_match_glb import Glb
        g = Glb.__new__(Glb)
        g.json = {"nodes": [{"name": "Arm"}], "accessors": [], "bufferViews": [], "buffers": [{"byteLength": 0}]}
        g.bin = bytearray(); g.nodes = g.json["nodes"]; g.names = ["Arm"]; g.parent = {}

        def anim(name, n, deg):
            tin = g.append_accessor((np.arange(n, dtype=float)[:, None] + 1) / 12, "SCALAR")
            h = np.radians(np.asarray(deg, float)) / 2
            q = np.stack([np.sin(h), 0 * h, 0 * h, np.cos(h)], 1)
            out = g.append_accessor(q, "VEC4")
            return {"name": name, "samplers": [{"input": tin, "output": out, "interpolation": "LINEAR"}],
                    "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}]}
        g.json["animations"] = [anim("u_DEF_Master", 7, [0] * 7), anim("Unit_Idle", 4, [10, 20, 30, 10]),
                                anim("Unit_Hitted", 2, [40, 50])]       # no Unit_Death: a skipped clip
        return g

    def test_sync_rewrites_master_from_clips(self):
        g = self.glb()
        g0 = self.glb()
        rec = P.sync_master(g, g0, P.master_frame_map(self.SEGS, self.SRC))
        a = g.anim("u_DEF_Master")
        q = g.read(a["samplers"][a["channels"][0]["sampler"]]["output"])
        deg = np.degrees(2 * np.arctan2(q[:, 0], q[:, 3]))
        np.testing.assert_allclose(deg, [10, 20, 30, 40, 50, 10, 0], atol=1e-4)   # Death frame kept (no clip)
        self.assertEqual(rec["unmapped"], [6])
        self.assertEqual(rec["synced"], 6)
        with self.assertRaises(SystemExit):                                         # map / key count mismatch
            P.sync_master(self.glb(), self.glb(), P.master_frame_map(self.SEGS, self.SRC)[:6])
        self.assertIn("skipped", P.sync_master(self.glb(), self.glb(), None))

    def test_copy_check_and_gate_dedup(self):
        fmap = P.master_frame_map(self.SEGS, self.SRC)
        g, g0 = self.glb(), self.glb()
        P.sync_master(g, g0, fmap)
        rec = P.verify_master_copy(g, g0, fmap, 1.0)
        self.assertEqual(rec["checked"], 6)
        self.assertLess(rec["maxRotationDeg"], P.MASTER_COPY_TOL_DEG)
        with self.assertRaises(SystemExit):                                         # an unsynced (stale) master fails
            P.verify_master_copy(self.glb(), self.glb(), fmap, 1.0)
        # the tear gate skips exactly the mapped master frames (each shipped pose once); unmapped frame 6 stays gated
        dup = P.master_duplicate_poses(g0, fmap)
        self.assertEqual(dup, {("u_DEF_Master", round((t + 1) / 12, 4)) for t in range(6)})
        self.assertEqual(P.master_duplicate_poses(g0, None), set())


if __name__ == "__main__":
    unittest.main()
