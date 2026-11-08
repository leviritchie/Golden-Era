"""town_full3d_cull: the see-through count and the no-worse-than-baseline gate on synthetic input."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_cull as CULL  # noqa: E402

CAM = {"fov": 40.0, "pos": np.array([0.0, 0.0, 0.0]), "fwd": np.array([0.0, 0.0, 1.0]),
       "up": np.array([0.0, 1.0, 0.0]), "right": np.array([1.0, 0.0, 0.0])}


def quad(x0, tris):
    P = np.array([[x0, -1, 10], [x0 + 2, -1, 10], [x0 + 2, 1, 10], [x0, 1, 10]], np.float32)
    return P, np.tile([[0, 0, -1]], (4, 1)).astype(np.float32), np.zeros((4, 2), np.float32), np.array(tris, np.int32)


def test_opposite_windings_one_culled():
    a, b = [[0, 1, 2], [0, 2, 3]], [[0, 2, 1], [0, 3, 2]]
    out = CULL.see_through([("p/Mesh_Body_a", *quad(-2.5, a)), ("p/Mesh_Body_b", *quad(0.5, b))],
                           {"c": CAM}, 160, 90, 1.0, 100.0)["c"]
    lost = dict(map(tuple, out["top"]))
    assert out["seeThroughPx"] > 0 and len(lost) == 1, out     # exactly one winding is Unity's back face


def test_non_body_not_counted():
    b = [[0, 2, 1], [0, 3, 2]]
    both = [[0, 1, 2], [0, 2, 3], [0, 2, 1], [0, 3, 2]]
    one = CULL.see_through([("p/Mesh_Body_a", *quad(-1, both))], {"c": CAM}, 160, 90, 1.0, 100.0)["c"]
    assert one["seeThroughPx"] == 0, one                        # closed from both sides: nothing to see through
    env = CULL.see_through([("p/Mesh_Terrain", *quad(-1, b)), ("p/Mesh_Body_x", *quad(-1, [[0, 1, 2], [0, 2, 3]]))],
                           {"c": CAM}, 160, 90, 1.0, 100.0)["c"]
    assert all(name != "Terrain" for name, _ in env["top"])


def test_gate_no_worse():
    CULL.baseline_row = lambda f: {"candidate": "base", "poses": {"rest": 5, "pan": 10}}
    ok = CULL.gate("x", {"rest": {"seeThroughPx": 5}, "pan": {"seeThroughPx": 3}})
    assert ok["worse"] == {} and ok["mode"] == "no-worse-than-baseline"
    bad = CULL.gate("x", {"rest": {"seeThroughPx": 6}, "pan": {"seeThroughPx": 3}})
    assert bad["worse"] == {"rest": [5, 6]}
    try:
        CULL.gate("x", {"rest": {"seeThroughPx": 0}})
    except SystemExit:
        pass
    else:
        raise AssertionError("a missing pose must fail, not skip")


def test_no_baseline_report_only():
    CULL.baseline_row = lambda f: None
    assert CULL.gate("x", {"rest": {"seeThroughPx": 99}})["worse"] == {}


def test_baseline_file_rows():
    import json
    rows = json.loads(CULL.BASELINE.read_text(encoding="utf-8"))["factions"]
    for f, r in rows.items():
        assert r["totalPx"] == sum(r["poses"].values()), f


def main():
    test_opposite_windings_one_culled()
    test_non_body_not_counted()
    test_baseline_file_rows()
    real = CULL.baseline_row
    try:
        test_gate_no_worse()
        test_no_baseline_report_only()
    finally:
        CULL.baseline_row = real
    print("OK town_full3d_cull: one winding culled, closed step not counted, gate no-worse per pose, baseline rows")


if __name__ == "__main__":
    main()
