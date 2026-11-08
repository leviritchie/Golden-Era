"""Ground measurements must evaluate mixed glTF sampler grids at one clip time."""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ground_check as G  # noqa: E402
from stride_match_glb import Glb  # noqa: E402


def fixture(head_times=(0.0, 1.0), head_heights=(1.0, 2.0), head_interp="LINEAR", rubble=False) -> Glb:
    blobs, views, accessors = [], [], []

    def add(values, kind):
        arr = np.asarray(values, dtype="<f4")
        offset = sum(len(b) for b in blobs)
        raw = arr.tobytes()
        blobs.append(raw + b"\0" * ((-len(raw)) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126,
                          "count": len(arr), "type": kind})
        return len(accessors) - 1

    idle_t = add([[0.0], [1.0]], "SCALAR")
    idle_hips = add([[0, 0, 0], [0, 0, 0]], "VEC3")
    hips_t = add([[0.0], [0.5], [1.0]], "SCALAR")
    hips_v = add([[0, 0, 0], [0, 0.1, 0], [0, 0, 0]], "VEC3")
    head_t = add(np.asarray(head_times)[:, None], "SCALAR")
    head_v = add([[0, y, 0] for y in head_heights], "VEC3")
    js = {
        "nodes": [{"name": "Root", "children": [1, 3] if rubble else [1]},
                  {"name": "Hips", "children": [2]},
                  {"name": "Head", "translation": [0, 1, 0]}]
        + ([{"name": "RubbleRoot", "children": [4]}, {"name": "Chunk_00"}] if rubble else []),
        "animations": [
            {"name": "Unit_Idle", "samplers": [{"input": idle_t, "output": idle_hips}],
             "channels": [{"sampler": 0, "target": {"node": 1, "path": "translation"}}]},
            {"name": "Unit_Move", "samplers": [
                {"input": hips_t, "output": hips_v, "interpolation": "LINEAR"},
                {"input": head_t, "output": head_v, "interpolation": head_interp}],
             "channels": [
                 {"sampler": 0, "target": {"node": 1, "path": "translation"}},
                 {"sampler": 1, "target": {"node": 2, "path": "translation"}}]}],
        "buffers": [{"byteLength": sum(len(b) for b in blobs)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    json_bytes = json.dumps(js).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    binary = b"".join(blobs)
    data = (struct.pack("<III", 0x46546C67, 2, 28 + len(json_bytes) + len(binary))
            + struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
    return Glb(data)


class FakeRig:
    source: Glb

    def __init__(self, _path, _clip):
        self.js = self.source.json
        self.joints = [1, 2]
        self.names = ["Hips", "Head"]
        self.J = np.array([[0], [1]])
        self.W = np.ones((2, 1))

    def world(self, _frame):
        raise AssertionError("ground_check must not mix sampler key indices")

    def skin(self, jm):
        return np.array([[0, jm[0, 1, 3] + 2, 0], [0, jm[1, 1, 3] - 1, 0]])


class FakeRubbleRig(FakeRig):
    """FakeRig plus a death-shatter chunk (Chunk_00 under RubbleRoot, build_unit.py's naming) collapsed far below."""

    def __init__(self, _path, _clip):
        super().__init__(_path, _clip)
        self.joints = [1, 2, 4]
        self.names = ["Hips", "Head", "Chunk_00"]
        self.J = np.array([[0], [1], [2]])
        self.W = np.ones((3, 1))

    def skin(self, jm):
        return np.r_[super().skin(jm[:2]), [[0, -10.0, 0]]]


class GroundSamplerTime(unittest.TestCase):
    def measure(self, glb, rig=FakeRig):
        rig.source = glb
        with patch.object(G.Glb, "load", return_value=glb), patch.object(G, "Rig", rig):
            return G.glb_ground(Path("synthetic.glb"))

    def test_rubble_chunks_under_rubble_root_are_not_the_floor(self):
        # 2026-09-27 h3_skeleton_warrior / h3_banshee: the collapsed Chunk_NN vertices (named without "rubble") held
        # every clip's lowest vertex at the Root origin, so the ground stage could not bring a lifted body down
        got = self.measure(fixture(rubble=True), FakeRubbleRig)
        self.assertEqual(got["H"], 2.0)
        self.assertEqual(got["clips"]["Move"]["lows"], [0.0, 0.3, 0.5])
        g = fixture(rubble=True)
        self.assertEqual(G.rubble_nodes(g.names, g.parent), {3, 4})

    def test_sparse_head_track_interpolates_at_dense_hips_times(self):
        got = self.measure(fixture())
        self.assertEqual(got["H"], 2.0)
        self.assertEqual(got["clips"]["Move"]["lows"], [0.0, 0.3, 0.5])
        self.assertEqual(got["clips"]["Move"]["hips0"], 0.0)

    def test_step_track_contributes_its_own_timestamp(self):
        got = self.measure(fixture(head_times=(0.0, 0.25, 1.0),
                                   head_heights=(1.0, 1.5, 2.0), head_interp="STEP"))
        self.assertEqual(got["clips"]["Move"]["lows"], [0.0, 0.275, 0.3, 0.5])

    def test_unknown_sampler_interpolation_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "unsupported sampler interpolation 'FUTURE'"):
            self.measure(fixture(head_interp="FUTURE"))


if __name__ == "__main__":
    unittest.main()
