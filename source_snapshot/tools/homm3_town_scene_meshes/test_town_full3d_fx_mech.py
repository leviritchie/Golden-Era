"""Focused test of town_full3d_mech (the measured mechanical kinds `wheel` and `track` behind town_full3d_fx).

1. A synthetic 16-tooth cog turning -5 deg / frame (clockwise on screen) over a 9-frame loop, its hub hidden behind a
   static wall drawn in front of it (frame 0 whole, frames 1.. patches over the cog), is measured back: hub within 1 px,
   step snapped exactly to -5 deg (8-fold: the loop turns one eighth), the wall in the front card, and the model
   redraws the frames within MECH_GAIN_MAX of the static plate's error.
2. A synthetic cage (a dark box outline) riding down a shaft from under a housing drawn in front of it, pausing, and
   riding back up, a thin bar in front of the shaft, is measured back: the visible frames' vertical poses within
   0.5 px of the truth, the hidden frames (inside the housing) interpolated between their visible neighbours, the bar and the housing in the
   front card, the plate under the cage's path the background.
3. Refusals: the cage measured as a wheel, a part that one frame shows only, and a track without room to reach its
   poses fail closed.
4. Factory: tbfacas3's right-hand cog measures as a wheel with its hub behind the wall near (151.5, 45) DEF px, -5
   deg / frame, 8-fold; its left-hand cog is refused (not a wheel); tbfaholy's elevator cage passes as a track.
5. town_full3d_fx dispatches both kinds (KINDS, KIND_FN).

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fx_mech.py   (sets TOWN_FULL3D_FACTION=factory itself)
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ["TOWN_FULL3D_FACTION"] = "factory"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_common as SC  # noqa: E402
import town_full3d_fx as FX            # noqa: E402
import town_full3d_mech as MECH        # noqa: E402

BG = (70, 110, 150)
WALL = (190, 160, 120)


def refuses(fn, needle: str) -> None:
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), f"refusal text {e!s} lacks {needle!r}"
        return
    raise AssertionError(f"expected a refusal containing {needle!r}")


def background(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.zeros((h, w, 4), np.uint8)
    base[..., :3] = BG
    base[(xx // 3 + yy // 3) % 2 == 0, :3] = (80, 120, 160)
    base[..., 3] = 255
    return base, yy, xx


def cog(n=9, step=-5.0, hub=(40.0, 30.0)):
    base, yy, xx = background(60, 60)
    dx, dy = xx + 0.5 - hub[0], -(yy + 0.5 - hub[1])          # screen up = + (angles read counter-clockwise)
    r = np.hypot(dx, dy)
    wall = xx >= 44                                            # the hub (x 40) and the cog's right side are hidden
    frames = []
    for k in range(n):
        a = np.degrees(np.arctan2(dy, dx)) - step * k          # the pattern turned by step * k
        teeth = (np.sin(np.radians(a) * 16) > 0) & (r >= 11) & (r <= 15)
        body = (r < 11) & (r >= 4)
        holes = body & (np.cos(np.radians(a) * 8) > 0.8) & (r > 6) & (r < 9)
        f = base.copy()
        f[teeth | body, :3] = (120, 70, 40)
        f[holes, :3] = (30, 20, 15)
        f[teeth & (np.sin(np.radians(a) * 16) > 0.7), :3] = (200, 150, 90)
        f[wall, :3] = WALL
        if k:
            f[..., 3] = np.where(r <= 17, 255, 0)
        frames.append(f)
    return frames, wall


def cage(n=24):
    base, yy, xx = background(100, 40)
    housing = yy < 16
    bar = (yy >= 44) & (yy <= 45)
    top, bottom = 2.0, 70.0
    ys = []
    for k in range(n):                                  # 0-3 hidden at the top, down 4-11, wait 12-15, up 16-23
        if k < 4:
            y = top
        elif k < 12:
            y = top + (bottom - top) * (k - 3) / 8
        elif k < 16:
            y = bottom
        else:
            y = bottom - (bottom - top) * (k - 15) / 8
        ys.append(y)
    frames = []
    for k, y in enumerate(ys):
        f = base.copy()
        box = (xx >= 14) & (xx < 26) & (yy >= round(y)) & (yy < round(y) + 10)
        inner = (xx >= 16) & (xx < 24) & (yy >= round(y) + 2) & (yy < round(y) + 8)
        f[box & ~inner, :3] = (35, 25, 20)
        f[housing, :3] = WALL
        f[bar, :3] = (60, 40, 30)
        if k:
            f[..., 3] = np.where((xx >= 10) & (xx < 30), 255, 0)
        frames.append(f)
    return frames, [float(round(y)) for y in ys], housing, bar


def main() -> int:
    F, wall = cog()
    w = MECH.fit_wheel(F, (0, 0, 60, 60), "synthetic_cog", {})
    f = w["fit"]
    assert abs(w["hub"][0] - 40.0) <= 1.0 and abs(w["hub"][1] - 30.0) <= 1.0, f
    assert f["stepDeg"] == -5.0 and f["symmetryN"] == 8 and f["screenSense"] == "cw", f
    assert f["redrawMaeRgb"] <= MECH.MECH_GAIN_MAX * f["staticPlateMaeRgb"], f
    assert w["front"] is not None and (w["front"][..., 3] > 0)[wall & (np.hypot(*np.mgrid[0:60, 0:60][::-1] -
                                                                      np.array([40.0, 30.0])[:, None, None]) < 14)].all(), \
        "the wall over the cog is not in the front card"

    F, ys, housing, bar = cage()
    t = MECH.fit_track(F, (0, 0, 40, 100), "synthetic_cage", {"reachPx": 90})
    tf = t["fit"]
    vis = t["visible"]
    hidden = [k for k in range(len(ys)) if not vis[k]]
    assert hidden == [0, 1, 2, 3, 23], (hidden, tf)          # the cage is inside the housing (y 2)
    dyk = [p[1] for p in t["poses"]]
    off = np.median([dyk[k] - ys[k] for k in range(len(ys)) if vis[k]])
    for k in range(len(ys)):
        if vis[k]:
            assert abs(dyk[k] - off - ys[k]) <= 0.5, (k, dyk[k] - off, ys[k], tf)
            assert abs(t["poses"][k][0]) <= 0.5, (k, t["poses"][k])
    # the hidden frames sit between their visible neighbours round the loop (22 and 4)
    for k in hidden:
        assert min(dyk[22], dyk[4]) - 1e-6 <= dyk[k] <= max(dyk[22], dyk[4]) + 1e-6, (k, dyk)
    fr = t["front"][..., 3] > 0
    assert fr[bar[:, :] & (np.mgrid[0:100, 0:40][1] >= 14) & (np.mgrid[0:100, 0:40][1] < 26)].all(), \
        "the bar across the shaft is not in the front card"
    assert fr[housing & (np.mgrid[0:100, 0:40][1] >= 15) & (np.mgrid[0:100, 0:40][1] < 25)].any(), \
        "the housing over the cage's top is not in the front card"
    assert tuple(t["plate"][40, 15]) != (35, 25, 20), "the plate keeps the cage on its path"
    assert tf["redrawMaeRgb"] <= MECH.MECH_GAIN_MAX * tf["staticPlateMaeRgb"], tf

    refuses(lambda: MECH.fit_wheel(F, (0, 0, 40, 100), "cage_as_wheel", {}), "cage_as_wheel")
    one = [F[0]] + [F[0].copy() for _ in range(5)]
    one[3] = F[8]
    refuses(lambda: MECH.fit_track(one, (0, 0, 40, 100), "once", {"reachPx": 90}), "fewer than two frames")
    refuses(lambda: MECH.fit_track(F, (0, 0, 40, 100), "short_reach", {"reachPx": 20}), "search bound")
    refuses(lambda: MECH.fit_track(F, (0, 0, 40, 101), "past_frame", {"reachPx": 90}), "leaves the DEF frame")

    lm = FX.layer_meta(SC.anim_frames())
    Fc = FX.def_frames(lm, "tbfacas3")
    w = MECH.fit_wheel(Fc, (140, 24, 176, 66), "tbfacas3", {})
    f = w["fit"]
    assert abs(f["hubPx"][0] - 151.5) <= 1.0 and abs(f["hubPx"][1] - 45.1) <= 1.0, f
    assert f["stepDeg"] == -5.0 and f["symmetryN"] == 8, f
    refuses(lambda: MECH.fit_wheel(Fc, (38, 24, 66, 64), "tbfacas3", {}), "this part is not a wheel")
    t = MECH.fit_track(FX.def_frames(lm, "tbfaholy"), (44, 80, 84, 217), "tbfaholy", {"reachPx": 110})
    hf = t["fit"]
    assert hf["visibleFrames"] >= 30 and hf["redrawMaeRgb"] <= MECH.MECH_GAIN_MAX * hf["staticPlateMaeRgb"], hf

    assert {"wheel", "track"} <= set(FX.KINDS) and FX.KIND_FN["wheel"] is MECH.k_wheel \
        and FX.KIND_FN["track"] is MECH.k_track
    print(f"test_town_full3d_fx_mech: OK (synthetic cog hub, -5 deg 8-fold, wall in front; synthetic cage poses "
          f"within 0.5 px, hidden frames interpolated; refusals x4; tbfacas3 hub {f['hubPx']} redraw "
          f"{f['redrawMaeRgb']} vs {f['staticPlateMaeRgb']}, left cog refused; tbfaholy cage redraw "
          f"{hf['redrawMaeRgb']} vs {hf['staticPlateMaeRgb']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
