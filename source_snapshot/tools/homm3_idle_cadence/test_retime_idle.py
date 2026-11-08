"""Unit tests for retime_idle (synthetic GLB, no Blender).

    python -m unittest tools/homm3_idle_cadence/test_retime_idle.py
"""
import os
import sys

import numpy as np
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def approx(a, b, abs_=1e-6, rel=0.0):
    return abs(a - b) <= max(abs_, rel * abs(b))
from glb_anim import accessor, animation, read_glb, write_glb  # noqa: E402
from idle_metrics import cadence  # noqa: E402
import retime_idle as R  # noqa: E402


def _qz(deg):
    a = np.radians(deg) / 2
    return [0.0, 0.0, np.sin(a), np.cos(a)]


def _make(tmp_path: Path, closed=True, step_nonconstant=False):
    bn = bytearray(); views = []; accs = []

    def add(arr, typ):
        arr = np.ascontiguousarray(arr, dtype="<f4")
        off = len(bn); bn.extend(arr.tobytes())
        views.append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        accs.append({"bufferView": len(views) - 1, "componentType": 5126, "count": int(arr.shape[0]),
                     "type": {1: "SCALAR", 3: "VEC3", 4: "VEC4"}[arr.shape[1]]})
        return len(accs) - 1

    t = np.arange(1, 10)[:, None] / 12.0                       # 9 keys at 12 fps, 1/12 .. 9/12
    ang = [0, 5, 10, 5, 0, -5, -10, -5, 0 if closed else 7]
    idle_in = add(t, 1); idle_rot = add(np.array([_qz(a) for a in ang]), 4)
    const_in = add(np.array([[1 / 12], [9 / 12]]), 1); const_t = add(np.array([[0, 1, 0], [0, 1, 0]]), 3)
    w = np.eye(9).reshape(-1, 1)                               # one-hot corrective weights
    w_out = add(w, 1)
    atk_rot = add(np.array([_qz(a) for a in [0, 30, 0]]), 4); atk_in = add(np.array([[0], [0.5], [1.0]]), 1)
    js = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bn)}], "bufferViews": views,
          "accessors": accs, "nodes": [{"name": "Hips"}, {"name": "Body", "mesh": 0}],
          "meshes": [{"primitives": [], "weights": [0] * 9}],
          "animations": [
              {"name": "Unit_Idle", "channels": [
                  {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                  {"sampler": 1, "target": {"node": 0, "path": "translation"}},
                  {"sampler": 2, "target": {"node": 1, "path": "weights"}}],
               "samplers": [{"input": idle_in, "output": idle_rot},
                            {"input": const_in, "output": const_t,
                             "interpolation": "STEP"},
                            {"input": idle_in, "output": w_out}]},
              {"name": "Unit_AttackFront", "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
               "samplers": [{"input": atk_in, "output": atk_rot}]}]}
    if step_nonconstant:
        js["animations"][0]["samplers"][0]["interpolation"] = "STEP"
    p = tmp_path / "in.glb"
    write_glb(str(p), js, bytes(bn))
    return str(p)


def test_retime_scales_idle_keeps_poses_and_leaves_other_clips(tmp_path):
    src = _make(tmp_path)
    js, bn = read_glb(src)
    atk_before = [dict(s) for s in animation(js, "Unit_AttackFront")["samplers"]]
    new_bin, stats = R.retime(js, bn, "Unit_Idle", 3.2, 30.0)
    an = animation(js, "Unit_Idle")
    t = accessor(js, new_bin, an["samplers"][0]["input"])[:, 0]
    q = accessor(js, new_bin, an["samplers"][0]["output"])
    assert approx(t[0], 1 / 12)
    assert approx(t[-1] - t[0], 8 / 12 * 3.2, 1e-5)
    # every original key time (stretched) is in the output and hits its original pose
    for k, a in enumerate([0, 5, 10, 5, 0, -5, -10, -5, 0]):
        tk = 1 / 12 + k / 12 * 3.2
        i = int(np.argmin(np.abs(t - tk)))
        assert abs(t[i] - tk) < 1e-5
        assert abs(abs(np.dot(q[i], _qz(a))) - 1) < 1e-6
    assert np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-5)
    assert np.all(np.diff(t) > 0) and np.max(np.diff(t)) <= 1 / 30 + 1e-6
    # corrective weights stay in [0, 1]
    w = accessor(js, new_bin, an["samplers"][2]["output"])
    assert w.min() >= -1e-6 and w.max() <= 1 + 1e-6
    # constant STEP channel: two keys, stretched, still STEP
    tc = accessor(js, new_bin, an["samplers"][1]["input"])[:, 0]
    assert len(tc) == 2 and approx(tc[-1] - tc[0], 8 / 12 * 3.2, 1e-5)
    # the other clip still points at its original, unchanged accessors
    assert animation(js, "Unit_AttackFront")["samplers"] == atk_before
    assert new_bin[:len(bn)] == bn
    # tempo: the loop is 3.2x longer, amplitude unchanged
    js0, bn0 = read_glb(src)
    from glb_anim import sample_rotations
    r0, l0 = sample_rotations(js0, bn0, "Unit_Idle")
    r1, l1 = sample_rotations(js, new_bin, "Unit_Idle")
    c0, c1 = cadence(r0, l0), cadence(r1, l1)
    assert approx(l1, 3.2 * l0, 0, 1e-4)
    assert approx(c1["amplitudeDeg"]["median"], c0["amplitudeDeg"]["median"], 0, 0.02)
    assert c1["angSpeedDegS"]["median"] < c0["angSpeedDegS"]["median"] / 2.5


def test_open_loop_fails_closed(tmp_path):
    js, bn = read_glb(_make(tmp_path, closed=False))
    try:
        R.retime(js, bn, "Unit_Idle", 3.2, 30.0)
    except R.RetimeError as e:
        assert "does not close" in str(e)
    else:
        raise AssertionError("open idle loop was retimed")


def test_nonconstant_step_fails_closed(tmp_path):
    js, bn = read_glb(_make(tmp_path, step_nonconstant=True))
    try:
        R.retime(js, bn, "Unit_Idle", 3.2, 30.0)
    except R.RetimeError as e:
        assert "STEP" in str(e)
    else:
        raise AssertionError("non-constant STEP channel was retimed")


def test_cli_refuses_in_place(tmp_path):
    src = _make(tmp_path)
    import subprocess
    r = subprocess.run([sys.executable, R.__file__, src, src, "--unit", "x"], capture_output=True, text=True)
    assert r.returncode != 0 and "refusing to overwrite" in (r.stdout + r.stderr)


def test_wing_decouple_tiles_source_loop(tmp_path):
    js2, bn2 = read_glb(_make(tmp_path))
    new_bin, _ = R.retime(js2, bn2, "Unit_Idle", 3.2, 30.0, {0: 3})
    an = animation(js2, "Unit_Idle")
    t = accessor(js2, new_bin, an["samplers"][0]["input"])[:, 0]
    q = accessor(js2, new_bin, an["samplers"][0]["output"])
    # the idle still spans 3.2x; the decoupled channel plays its source loop 3 times over it
    assert approx(t[-1] - t[0], 8 / 12 * 3.2, 1e-5)
    per = 8 / 12 * 3.2 / 3
    for c in range(3):
        for k, a in enumerate([0, 5, 10, 5, 0, -5, -10, -5, 0]):
            tk = 1 / 12 + c * per + k / 12 * 3.2 / 3
            i = int(np.argmin(np.abs(t - tk)))
            assert abs(t[i] - tk) < 1e-5 and abs(abs(np.dot(q[i], _qz(a))) - 1) < 1e-6
    # an undecoupled channel of the same clip keeps the body timing
    w_t = accessor(js2, new_bin, an["samplers"][2]["input"])[:, 0]
    assert approx(w_t[-1] - w_t[0], 8 / 12 * 3.2, 1e-5)


class RetimeIdleTest(unittest.TestCase):
    def _run(self, fn):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))

    def test_retime(self):
        self._run(test_retime_scales_idle_keeps_poses_and_leaves_other_clips)

    def test_open_loop(self):
        self._run(test_open_loop_fails_closed)

    def test_nonconstant_step(self):
        self._run(test_nonconstant_step_fails_closed)

    def test_wing_decouple(self):
        self._run(test_wing_decouple_tiles_source_loop)

    def test_in_place(self):
        self._run(test_cli_refuses_in_place)


if __name__ == "__main__":
    unittest.main()
