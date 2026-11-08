"""Focused test of town_full3d_fx DEF registration (ANIM_OFFSETS) on Tower's crosswalked dwelling DEFs.

1. With the profile's ANIM_OFFSETS each crosswalked DEF registers at its measured offset: dwellingUp2Lvl1_1 (6, 0),
   dwellingUp2Lvl3_1 (0, 0) (same box), dwellingUp2Lvl7_1 (0, 84) (the storm cloud rows above the temple).
2. Without the offset row, a DEF whose box differs from its sprite fails closed (check_registration).
3. A stray ANIM_OFFSETS key (a DEF that animates no layer) and a malformed row fail closed (layer_meta).
4. The lightning piece of dwellingUp2Lvl7_1 lies above the sprite's top row (a float piece).

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fx_offsets.py   (sets TOWN_FULL3D_FACTION=tower itself)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["TOWN_FULL3D_FACTION"] = "tower"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_common as SC  # noqa: E402
import town_full3d_fx as FX            # noqa: E402


def refuses(fn, needle: str) -> None:
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), f"refusal text {e!s} lacks {needle!r}"
        return
    raise AssertionError(f"expected a refusal containing {needle!r}")


def main() -> int:
    lays = SC.layers()
    lm = FX.layer_meta(SC.anim_frames())
    want = {"tbtwdw_0_2": (6, 0), "tbtwdw_2_2": (0, 0), "tbtwdw_6_2": (0, 84)}
    for lid, off in want.items():
        got = FX.check_registration(lm, lid, lays[lid], FX.def_frames(lm, lid))
        assert got == off, f"{lid}: registered at {got}, want {off}"

    saved = dict(SC.FP.ANIM_OFFSETS)
    try:
        SC.FP.ANIM_OFFSETS = {k: v for k, v in saved.items() if k != "dwellingUp2Lvl7_1"}
        lm2 = FX.layer_meta(SC.anim_frames())
        refuses(lambda: FX.check_registration(lm2, "tbtwdw_6_2", lays["tbtwdw_6_2"], FX.def_frames(lm2, "tbtwdw_6_2")),
                "needs ANIM_OFFSETS")
        SC.FP.ANIM_OFFSETS = {**saved, "tbtwholy": [0, 0]}
        refuses(lambda: FX.layer_meta(SC.anim_frames()), "is not a DEF id that animates a layer")
        SC.FP.ANIM_OFFSETS = {**saved, "dwellingUp2Lvl1_1": [6.0, 0]}
        refuses(lambda: FX.layer_meta(SC.anim_frames()), "must be [dx, dy] integer px")
    finally:
        SC.FP.ANIM_OFFSETS = saved

    ch = FX.changed_count(FX.def_frames(lm, "tbtwdw_6_2"))
    comps = FX.components(ch > 0, 40, dilate=3)
    assert len(comps) == 1, comps
    rect = comps[0][1]
    assert rect[1] - want["tbtwdw_6_2"][1] < 0, f"the bolt {rect} does not rise above the temple sprite"
    print(f"test_town_full3d_fx_offsets: OK (offsets {want}; fail-closed x3; bolt DEF rect {list(rect)} floats)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
