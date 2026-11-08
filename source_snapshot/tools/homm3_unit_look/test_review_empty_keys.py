"""Regression: review keys with an empty mesh (rig sink / hideMesh) or an empty DEF body reference
(hideMesh + DEF remains) are recorded and excluded from the body means, never a crash; a unit whose
every key is excluded fails closed. Also pins the empty-input guards in prebake_lab.

Needs a complete bake of HOMM3_TEST_UNIT (default h3_pikeman; applied units are pruned, so pick an unapplied baked unit) under artifacts/homm3_unit_look/<unit>/work (read only). Sheets go to
a temp dir.

    python tools/homm3_unit_look/test_review_empty_keys.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "homm3_prebake"))
import look as L  # noqa: E402
import prebake_lab as pl  # noqa: E402
import review as RV  # noqa: E402

UNIT = os.environ.get("HOMM3_TEST_UNIT", "h3_pikeman")  # any unit with a complete bake (applied units are pruned)


def raises(fn, exc, text):
    try:
        fn()
    except exc as e:
        assert text in str(e), e
        return
    raise AssertionError(f"expected {exc.__name__} ({text})")


def main() -> int:
    raises(lambda: pl.hist_distance(np.array([]), np.array([1.0])), ValueError, "empty L* sample")
    raises(lambda: pl.image_stats(np.zeros((4, 4, 3)), np.zeros((4, 4), bool)), ValueError, "empty mask")

    spec = json.loads((HERE / "units" / f"{UNIT}.json").read_text())
    base = L.build_ctx(UNIT, spec)
    tex = base["maps"]["albedo"]
    vns = base["reviewViews"]
    assert len(vns) >= 4, vns
    sink, lost, body_gone = vns[1], vns[2], vns[3]
    tmp = Path(tempfile.mkdtemp(prefix="reviewempty_", dir="V:/games/unit_look_scratch"))
    try:
        ref = RV.run(spec, base, tmp, tex, None)["summary"]

        ctx = copy.copy(base)
        ctx["views"] = dict(base["views"])
        ctx["vmeta"] = copy.deepcopy(base["vmeta"])
        ctx["def"] = dict(base["def"])
        for vn in (sink, lost):  # the mesh renders empty on these keys
            ctx["views"][vn] = {**base["views"][vn], "alpha": np.zeros_like(base["views"][vn]["alpha"])}
        for b in ctx["vmeta"]["views"][sink]["bones"].values():  # the rig is collapsed to one point (sink)
            b["headPx"] = [100.0, 120.0]
        rec = dict(base["def"][body_gone])  # the whole DEF frame is effect (hideMesh + DEF remains)
        rec["bodyNoFx"] = np.zeros_like(rec["bodyNoFx"])
        ctx["def"][body_gone] = rec
        out = RV.run(spec, ctx, tmp, tex, None)
        per, s = out["views"], out["summary"]
        assert per[sink]["meshEmpty"] and per[sink]["meshEmptyCause"] == "rigCollapsed", per[sink]
        assert per[lost]["meshEmptyCause"] == "unexplained", per[lost]
        assert any(lost in w and "suspicious" in w for w in s["warnings"]), s
        assert not any(sink in w for w in s["warnings"]), s
        assert per[body_gone]["bodyEmpty"] and per[body_gone]["look"] is None, per[body_gone]
        assert per[body_gone]["lookWithEffects"] is not None  # the composite is still measured
        assert set(s["excludedFromBody"]) == {sink, lost, body_gone}, s
        assert s["bodyViews"] == len(vns) - 3 and s["reviewViews"] == len(vns)
        keep = [vn for vn in vns if vn not in (sink, lost, body_gone)]
        want = round(float(np.mean([ref_v["look"]["LhistDistanceToDEF"] for vn, ref_v in
                                    RV.run(spec, base, tmp, tex, None)["views"].items() if vn in keep])), 2)
        assert s["meanLhistBodyLook"] == want, (s["meanLhistBodyLook"], want)
        assert (tmp / "review_sheet.png").is_file()
        print(f"OK empty keys: sink/unexplained/bodyEmpty recorded and excluded; body mean over {keep} = {want} "
              f"(all keys: {ref['meanLhistBodyLook']})")

        for vn in vns:  # every key empty -> fail closed
            ctx["views"][vn] = {**base["views"][vn], "alpha": np.zeros_like(base["views"][vn]["alpha"])}
        raises(lambda: RV.run(spec, ctx, tmp, tex, None), RV.ReviewError, "every review key has an empty mesh")
        print("OK fail closed when every review key is excluded; prebake_lab guards raise ValueError")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
