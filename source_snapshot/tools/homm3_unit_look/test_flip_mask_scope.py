"""Regression: a defFlipbook layer's effectMask carves the fit/review targets only on the DEF
(group, frame) keys the layer lists, and a file mask is read only there.

Needs a complete bake of HOMM3_TEST_UNIT (default h3_pikeman; applied units are pruned, so pick an unapplied baked unit) under artifacts/homm3_unit_look/<unit>/work (read only; nothing is
written there). Masks go to a temp dir.

    python tools/homm3_unit_look/test_flip_mask_scope.py
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
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import look as L  # noqa: E402
import spec as S  # noqa: E402

UNIT = os.environ.get("HOMM3_TEST_UNIT", "h3_pikeman")  # any unit with a complete bake (applied units are pruned)


def main() -> int:
    base = json.loads((HERE / "units" / f"{UNIT}.json").read_text())
    clips = S.clip_segments(UNIT)
    atk = clips["Unit_AttackFront"]
    fit, review = L.choose_frames(base, clips)
    shown = set(fit) | set(review)
    keys = [(g, f, t) for (g, f), t in zip(atk["defFrames"], atk["masterFrames"]) if t in shown]
    assert keys, "no AttackFront key among the fit/review frames"
    g0, f0, t0 = keys[0]
    tmp = Path(tempfile.mkdtemp(prefix="flipscope_", dir="V:/games/unit_look_scratch"))
    try:
        # the full-canvas mask exists ONLY for the listed attack frame; no idle PNGs
        canvas = Image.open(S.frames_meta(UNIT)["sources"][t0]).size
        Image.fromarray(np.full(canvas[::-1], 255, np.uint8)).save(tmp / f"{g0:02d}_{f0:02d}.png")
        ly = {"id": "t_attack", "type": "defFlipbook", "anchor": {"bone": "Head"},
              "clips": {"Unit_AttackFront": {"defGroup": g0, "frames": [f0]}},
              "effectMask": {"method": "file", "path": str(tmp)}}
        spec = copy.deepcopy(base)
        spec["vfx"]["layers"] = [*spec["vfx"]["layers"], ly]
        L.choose_frames = lambda _s, _c: (fit, review)  # same baked frames for both specs (the layer adds review keys)
        ref = L.build_ctx(UNIT, base)["def"]
        got = L.build_ctx(UNIT, spec)["def"]  # used to raise FileNotFoundError on the idle frames
        for vn, rec in got.items():
            if rec["t"] == t0:
                assert rec["fx"].any() and np.array_equal(rec["fx"], rec["body"]), f"{vn}: listed frame not carved"
            else:
                for k in ("fx", "bodyNoFx"):
                    assert np.array_equal(rec[k], ref[vn][k]), f"{vn}: unlisted frame's {k} changed"
        print(f"OK scope: layer lists only {g0:02d}_{f0:02d} (t={t0}); {len(got) - 1} other fit/review frames unchanged")

        # validator: a listed frame without its PNG is an error; an absent directory is pending (warning)
        ly2 = copy.deepcopy(ly)
        ly2["clips"]["Unit_AttackFront"]["frames"] = [f0, next(f for g, f in atk["defFrames"] if f != f0)]
        s2 = copy.deepcopy(base)
        s2["vfx"]["layers"] = [*s2["vfx"]["layers"], ly2]
        w: list[str] = []
        errs = S.validate(s2, UNIT, clips, w, S.build_info(UNIT))
        assert any("effectMask file masks missing for listed frames" in x for x in errs), errs
        ly2["effectMask"]["path"] = str(tmp / "absent")
        w = []
        errs = S.validate(s2, UNIT, clips, w, S.build_info(UNIT))
        assert not any("missing for listed frames" in x for x in errs), errs
        assert any("does not exist yet (pending)" in x for x in w), w
        print("OK validator: missing listed PNG is an error; absent mask directory is pending")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
