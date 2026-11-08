"""Freeze gate DEF evidence: source-pinned teleport clouds, measured DEF holds and measured body-absent frames.

Only a collapsed weighted body may hold under exact DEF effects or where the DEF body is gone; a DEF hold is its
silhouette, not its colours. DefShapeTest reads the real enchanter / oceanid / devil source frames.

    python -m unittest tools/homm3_def_retarget_delivery/test_flyer_articulation_freeze.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flyer_articulation as F  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TeleportFreezeTest(unittest.TestCase):
    def setUp(self):
        scratch = F.ROOT / "artifacts/homm3_def_retarget_delivery/_articulation"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / f"test_freeze_{uuid.uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.unit = "h3_synthetic_teleporter"
        self.cfg = self.root / "tools/homm3_def_retarget/units" / f"{self.unit}.json"
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text(json.dumps({"teleport": {"out": ["MoveStart", 0, 1],
                                                      "in": ["MoveEnd", 2, 3]}}))
        self.flier = self.root / "fliers.json"
        self.flier.write_text(json.dumps({"units": {self.unit: {"flyingSubtypes": ["movementTeleporting"]}}}))
        self.runs = self.root / "runs"
        ms_dir = self.runs / self.unit / "linked_master/master_sequence"
        ms_dir.mkdir(parents=True)
        mask_dir = self.root / "masks"
        mask_dir.mkdir()
        frames = []
        segments = []
        pins = {}
        for clip, group, count, window in (("MoveStart", 20, 3, (1, 2)), ("Move", 0, 1, None),
                                           ("MoveEnd", 21, 4, (0, 1))):
            start = len(frames)
            source_shas, mask_shas = [], []
            for i in range(count):
                src = self.root / f"{group:02}_{i:02}.png"
                Image.new("RGBA", (2, 2), (i + group, 10, 20, 255)).save(src)
                frames.append({"sourcePng": str(src), "sourceSha256": sha(src)})
                if window is not None and window[0] <= i <= window[1]:
                    mask = mask_dir / src.name
                    Image.new("L", (2, 2), 255).save(mask)
                    source_shas.append(sha(src))
                    mask_shas.append(sha(mask))
            segments.append({"contractSuffix": clip, "defGroup": group, "frameCount": count,
                             "globalStart": start, "globalEnd": len(frames)})
            if window is not None:
                pins[clip] = {"defGroup": group, "frames": list(window),
                              "sourceSetSha256": hashlib.sha256("".join(source_shas).encode()).hexdigest(),
                              "effectMaskSetSha256": hashlib.sha256("".join(mask_shas).encode()).hexdigest()}
        (ms_dir / "master_sequence.json").write_text(json.dumps({"segments": segments, "frames": frames,
                                                                  "sourceFrameMs": 1000.0}))
        self.ref = self.root / "teleport_effect_windows.json"
        self.ref.write_text(json.dumps({"schema": "homm3_def_teleport_effect_windows.v1",
                                        "sourceFrameMs": 1000.0,
                                        "units": {self.unit: {"effectMaskDir": "masks", **pins}}}))
        for name, value in (("ROOT", self.root), ("MASTER_RUNS", self.runs), ("FLIERS_TABLE", self.flier),
                            ("TELEPORT_EFFECT_WINDOWS", self.ref)):
            patcher = mock.patch.object(F, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_exact_source_and_mask_windows(self):
        self.assertEqual(F.teleport_effect_windows(self.unit),
                         {"Unit_MoveStart": {"frames": [1, 2], "frameCount": 3, "frameDurationS": 1.0},
                          "Unit_MoveEnd": {"frames": [0, 1], "frameCount": 4, "frameDurationS": 1.0}})
        self.assertEqual(F.teleport_reference_errors(), [])

    def test_missing_stale_or_widened_evidence_refuses(self):
        ref = json.loads(self.ref.read_text())
        ref["units"][self.unit]["MoveStart"]["sourceSetSha256"] = "0" * 64
        self.ref.write_text(json.dumps(ref))
        with self.assertRaisesRegex(SystemExit, "source/effect-mask pins changed"):
            F.teleport_effect_windows(self.unit)
        ref["units"][self.unit]["MoveStart"]["sourceSetSha256"] = hashlib.sha256(
            "".join(sha(self.root / f"20_{i:02}.png") for i in (1, 2)).encode()).hexdigest()
        self.ref.write_text(json.dumps(ref))
        Image.new("L", (2, 2), 0).save(self.root / "masks/20_01.png")
        with self.assertRaisesRegex(SystemExit, "not the source's opaque fire-cloud"):
            F.teleport_effect_windows(self.unit)
        Image.new("L", (2, 2), 255).save(self.root / "masks/20_01.png")
        cfg = json.loads(self.cfg.read_text())
        cfg["teleport"]["out"][2] = 0
        self.cfg.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(SystemExit, "bounds are invalid"):
            F.teleport_effect_windows(self.unit)

    def test_nonteleport_or_unconfigured_refuses(self):
        self.flier.write_text(json.dumps({"units": {self.unit: {"flyingSubtypes": []}}}))
        with self.assertRaisesRegex(SystemExit, "movementTeleporting"):
            F.teleport_effect_windows(self.unit)
        self.cfg.write_text("{}")
        with self.assertRaisesRegex(SystemExit, "must both exist"):
            F.teleport_effect_windows(self.unit)

    def test_visible_body_or_missing_scale_is_not_excused(self):
        times = np.arange(1, 6, dtype=float)
        vals = {0: times[:, None], 1: np.tile([0, 0, 0, 1], (5, 1)),
                2: np.array([[0.001, 0.001, 0.001]] * 3 + [[1, 1, 1]] * 2)}
        acc = lambda i: vals[i]  # noqa: E731
        anim = {"name": "Unit_MoveEnd", "samplers": [{"input": 0, "output": 1}, {"input": 0, "output": 2}],
                "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                             {"sampler": 1, "target": {"node": 1, "path": "scale"}}]}
        window = {"frames": [0, 2], "frameCount": 5, "frameDurationS": 1.0}
        js = {"nodes": [{}, {"scale": [1, 1, 1]}]}
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertEqual(m["collapsedCloudStepsExcused"], 2)
        self.assertEqual(m["freezeRun"], 2)  # visible held flesh at frames 3-4 is still counted
        vals[3] = np.array([[1.0], [5.0]])
        vals[4] = np.array([[0.001, 0.001, 0.001], [1.0, 1.0, 1.0]])
        anim["samplers"][1] = {"input": 3, "output": 4, "interpolation": "STEP"}
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertEqual(m["collapsedCloudStepsExcused"], 2)  # sparse STEP stays collapsed until its next key
        anim["samplers"][1]["interpolation"] = "CUBICSPLINE"
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertIn("needs LINEAR or STEP interpolation", m["freezeEvidence"])
        anim["samplers"][1] = {"input": 0, "output": 2, "interpolation": "LINEAR"}
        vals[2][0, 0] = np.nan
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertIn("invalid keys", m["freezeEvidence"])
        vals[2][0, 0] = 0.001
        vals[2][:3] = 1
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertIn("visible weighted body scale", m["freezeEvidence"])
        anim["channels"].pop()
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {1})
        self.assertIn("animated Hips scale", m["freezeEvidence"])
        js["nodes"][0]["scale"] = [2, 2, 2]
        anim["channels"].append({"sampler": 1, "target": {"node": 1, "path": "scale"}})
        vals[2][:3] = 0.001
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {0, 1})
        self.assertIn("expanding scale", m["freezeEvidence"])
        js["nodes"][0]["scale"] = [1, 1, 1]
        vals[0][:, 0] += 0.5
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]], window, 1, {0, 1})
        self.assertIn("pinned DEF time grid", m["freezeEvidence"])

    def test_weighted_joint_outside_hips_refuses(self):
        def glb(weighted_joint, weight=1.0):
            joints = np.array([[weighted_joint, 0, 0, 0]], dtype=np.uint8).tobytes()
            weights = np.array([[weight, 0, 0, 0]], dtype="<f4").tobytes()
            js = {"nodes": [{"name": "Root", "children": [1]}, {"name": "Hips"},
                            {"name": "Body", "mesh": 0, "skin": 0}],
                  "skins": [{"joints": [0, 1]}],
                  "meshes": [{"primitives": [{"attributes": {"JOINTS_0": 0, "WEIGHTS_0": 1, "POSITION": 2}}]}],
                  "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 4},
                                  {"buffer": 0, "byteOffset": 4, "byteLength": 16}],
                  "accessors": [{"bufferView": 0, "componentType": 5121, "count": 1, "type": "VEC4"},
                                {"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC4"},
                                {"count": 1, "type": "VEC3"}]}
            raw = json.dumps(js).encode()
            raw += b" " * (-len(raw) % 4)
            binary = joints + weights
            out = self.root / "skin.glb"
            out.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(raw) + len(binary)) +
                            struct.pack("<I4s", len(raw), b"JSON") + raw +
                            struct.pack("<I4s", len(binary), b"BIN\0") + binary)
            return out, js

        path, js = glb(1)
        self.assertEqual(F.hidden_body_root(path, js), (1, {0, 1, 2}))
        path, js = glb(0)
        with self.assertRaisesRegex(SystemExit, "outside the Hips subtree"):
            F.hidden_body_root(path, js)
        path, js = glb(1, 0.5)
        with self.assertRaisesRegex(SystemExit, "incomplete skin weights"):
            F.hidden_body_root(path, js)
        path, js = glb(1)
        js["nodes"][0]["matrix"] = list(np.eye(4).reshape(-1))
        with self.assertRaisesRegex(SystemExit, "matrix transform"):
            F.hidden_body_root(path, js)
        path, js = glb(1)
        js["accessors"][0]["count"] = 0
        with self.assertRaisesRegex(SystemExit, "invalid skin weights"):
            F.hidden_body_root(path, js)
        path, js = glb(1)
        js["meshes"][0]["primitives"] = []
        with self.assertRaisesRegex(SystemExit, "no auditable primitives"):
            F.hidden_body_root(path, js)


def sil(shift=0, h=20, w=12, top=4):
    """A 40x30 silhouette: a w x h block whose top edge is at row top, shifted right by shift px."""
    m = np.zeros((40, 30), bool)
    m[top:top + h, 5 + shift:5 + shift + w] = True
    return m


def held_clip(n, hips_scale):
    """n keys, one never-moving rotation (every step held) and a Hips scale track."""
    times = np.arange(1, n + 1, dtype=float)
    vals = {0: times[:, None], 1: np.tile([0, 0, 0, 1], (n, 1)), 2: np.array(hips_scale, float)}
    anim = {"name": "Unit_MoveStart", "samplers": [{"input": 0, "output": 1}, {"input": 0, "output": 2}],
            "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                         {"sampler": 1, "target": {"node": 1, "path": "scale"}}]}
    return {"nodes": [{}, {"scale": [1, 1, 1]}]}, (lambda i: vals[i]), anim


class DefShapeFreezeTest(unittest.TestCase):
    """The DEF's shape, not its pixels' colours, decides whether it moved; a missing body is measured too."""

    def test_def_hold_is_the_silhouette_not_the_colours(self):
        js, acc, anim = held_clip(5, [[1, 1, 1]] * 5)
        dither = [F.DefFrame(f"c{i}", sil(0) ^ (np.eye(40, 30, k=i % 2, dtype=bool) & sil(0))) for i in range(5)]
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [dither])
        self.assertEqual((m["freezeRun"], m["rawFreezeRun"], m["defHoldStepsExcused"]), (1, 5, 4))
        moving = [F.DefFrame(f"c{i}", sil(i)) for i in range(5)]      # the body slides 1 px per frame: 4 px spread
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [moving])
        self.assertEqual(m["freezeRun"], 5)
        self.assertNotIn("defHoldStepsExcused", m)
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [[str(i) for i in range(5)]])   # no silhouette: no excuse
        self.assertEqual(m["freezeRun"], 5)

    def test_body_absent_hold_needs_the_collapsed_body(self):
        frames = [F.DefFrame(f"r{i}", sil(0, h=3, top=30), absent=True) for i in range(5)]
        js, acc, anim = held_clip(5, [[0.001] * 3] * 5)
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [frames], None, 1, {1})
        self.assertEqual((m["freezeRun"], m["bodyAbsentStepsExcused"]), (1, 4))
        js, acc, anim = held_clip(5, [[1, 1, 1]] * 5)   # full-scale mesh while the DEF body is gone (a still ripple)
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [frames], None, 1, {1})
        self.assertEqual((m["freezeRun"], m["bodyAbsentStepsExcused"]), (5, 0))
        self.assertEqual(F.freeze_gate({"Unit_MoveStart": m})[0][:44], "Unit_MoveStart holds one pose for 5 frames f")
        js, acc, anim = held_clip(5, [[0.001] * 3] * 5)               # collapsed, but the skin audit failed
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [frames], None, None, None, "teleport cloud needs one skin")
        self.assertEqual(m["freezeRun"], 5)
        self.assertIn("needs one skin", F.freeze_gate({"Unit_MoveStart": m})[0])
        js["nodes"][0]["scale"] = [2, 2, 2]                            # an expanding ancestor undoes the collapse
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1, [frames], None, 1, {0, 1})
        self.assertEqual(m["freezeRun"], 5)

    def test_real_enchanter_mouseover_holds_and_shootfront_moves(self):
        d = F.def_frames("h3_enchanter")
        mo = max(d["Mouseover"], key=len)[2:9]
        self.assertGreater(len({f.hash for f in mo}), 1)               # the old whole-frame hash called this motion
        self.assertLessEqual(F.silhouette_spread(mo), F.DEF_HOLD_PX)
        shoot = max(d["ShootFront"], key=len)[4:7]
        self.assertGreater(F.silhouette_spread(shoot), 10 * F.DEF_HOLD_PX)
        self.assertFalse(any(f.absent for seg in d.values() for s_ in seg for f in s_))

    def test_real_oceanid_sink_is_body_absent_and_devil_clouds_are_not(self):
        d = F.def_frames("hota_cove_oceanid")
        self.assertEqual([f.absent for f in max(d["MoveStart"], key=len)], [False] * 6 + [True] * 7)
        self.assertEqual([f.absent for f in max(d["MoveEnd"], key=len)], [True] * 7 + [False] * 6)
        self.assertFalse(any(f.absent for f in max(d["Death"], key=len)))   # a corpse on the floor is a body
        for unit in ("h3_devil", "h3_arch_devil", "h3_arch_demon"):
            d = F.def_frames(unit)
            for clip, (a, b) in (("MoveStart", (7, 13)), ("MoveEnd", (0, 4))):
                seg = max(d[clip], key=len)
                self.assertFalse(any(f.absent for f in seg[a:b + 1]), (unit, clip))
                for i in range(a, b - 1):                              # the cloud still counts as DEF motion
                    self.assertGreater(F.silhouette_spread(seg[i:i + 3]), 10 * F.DEF_HOLD_PX, (unit, clip, i))


if __name__ == "__main__":
    unittest.main()
