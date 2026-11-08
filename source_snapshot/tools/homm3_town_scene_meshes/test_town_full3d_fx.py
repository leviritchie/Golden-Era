"""Focused test of town_full3d_fx (the shared profile-classified town effects module).

1. classify() refuses an animated reachable layer the profile does not classify (fail closed), a stray row, and an
   unknown kind.
2. One classified layer (Dungeon tbdndw_6, candle flames + hoard glints) is measured from its own DEF: the flame
   filter finds the isolated candles and the glint mask excludes them.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fx.py   (sets TOWN_FULL3D_FACTION=dungeon itself)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["TOWN_FULL3D_FACTION"] = "dungeon"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import town_full3d_fx as FX            # noqa: E402
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_fx as SF      # noqa: E402


def refuses(fn, needle: str) -> None:
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), f"refusal text {e!s} lacks {needle!r}"
        return
    raise AssertionError(f"expected a refusal containing {needle!r}")


def main() -> int:
    meta = SC.anim_frames()
    reach = SC.reachable_layers()
    spec = dict(SC.FP.FX_LAYERS)
    todo = FX.classify(reach, meta, spec)
    assert "tbdndw_6" in todo and todo["tbdndw_6"][0] == len(meta["tbdndw_6"]["frames"])
    # fail closed: drop one classified layer
    short = {k: v for k, v in spec.items() if k != "tbdnext0"}
    refuses(lambda: FX.classify(reach, meta, short), "without an FX_LAYERS classification: ['tbdnext0']")
    # a static layer classified is a stray row
    refuses(lambda: FX.classify(reach, meta, {**spec, "tbdnhall": spec["tbdnext0"]}), "not reachable animated")
    # unknown kind
    bad = {**spec, "tbdnext0": {"moves": "x", "effects": [{"kind": "flipbook"}]}}
    refuses(lambda: FX.classify(reach, meta, bad), "unknown effect kind 'flipbook'")
    # a missing FX_LAYERS dict
    saved = SC.FP.FX_LAYERS
    try:
        del SC.FP.FX_LAYERS
        refuses(FX.fx_layers, "no FX_LAYERS dict")
    finally:
        SC.FP.FX_LAYERS = saved

    # one classified layer, measured from its DEF
    row = spec["tbdndw_6"]
    F = SF.frames("tbdndw_6")
    ch = FX.changed_count(F)
    flame_sel = row["effects"][0]["colour"]
    fm = (ch > 0) & FX.colour_mask(F, flame_sel)
    comps = FX.components(fm, row["effects"][0]["minPx"])
    rects = [r for _, r in comps]
    # the two isolated wall candles (DEF patches (66,18,72,30) and (205,10,241,46)) are flame components
    assert any(66 <= r[0] and r[2] <= 72 and 18 <= r[1] and r[3] <= 30 for r in rects), rects
    assert any(205 <= r[0] and r[2] <= 241 and 10 <= r[1] and r[3] <= 46 for r in rects), rects
    gm = (ch > 0) & ~FX.colour_mask(F, flame_sel)
    assert not (gm & fm).any() and gm.sum() > fm.sum() > 0
    col = FX.bright_colour(F, comps[0][0])
    assert col[0] > 0.8 and col[2] < 0.3, col          # a flame is warm
    print(f"test_town_full3d_fx: OK (fail-closed x4; tbdndw_6 flames {len(comps)} comps {int(fm.sum())} px, "
          f"glint px {int(gm.sum())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
