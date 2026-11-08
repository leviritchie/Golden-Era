"""Focused test of town_full3d_fx.fit_swing (the pendulum measurement behind the `swing` kind).

1. A synthetic pendulum (a disc bob on an invisible rod, drawn as a DEF would be: frame 0 whole, frames 1.. with
   transparent px away from the bob's path, a static dark brace across the path in front of the bob) is measured back:
   swings per loop exact, phase within 3 deg, horizontal travel within 0.4 px, pivot x within 1 px, amplitude within
   3 deg, and the true rod length inside the reported length band (the pivot HEIGHT rests on a rise of about one px,
   so it is measured loosely and the band says how loosely); the brace is in the front card, and the plate under the
   bob's rest position is the background. A bob wider than its travel (a px it covers in every frame) is refused.
2. The same bob sliding sideways on a straight line (no rise) is refused: a translation is not a swing. A swing
   without a colour range is refused.
3. Tower's pendulum DEF (tbtwdw_0_2 via dwellingUp2Lvl1_1, 20 frames) measures as one swing per loop with the pivot
   under the clock face, near (36, 28) DEF px, and the model redraws the DEF closer than the static plate does.
4. colour_mask (now through hsv_in) gives the same mask as its previous inline form on Tower's DEF.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fx_swing.py   (sets TOWN_FULL3D_FACTION=tower itself)
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

os.environ["TOWN_FULL3D_FACTION"] = "tower"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_common as SC  # noqa: E402
import town_full3d_fx as FX            # noqa: E402

BG = (70, 110, 90)
BOB = (215, 175, 70)
BRACE = (40, 30, 25)


def pendulum(n=24, cycles=1, amp_deg=15.0, phase_deg=40.0, L=25.0, pivot=(40.0, 12.0), r=5, slide=False):
    size = (64, 80)                                   # h, w
    yy, xx = np.mgrid[0:size[0], 0:size[1]]
    base = np.zeros(size + (4,), np.uint8)
    base[..., :3] = BG
    base[(xx // 3 + yy // 3) % 2 == 0, :3] = (80, 120, 100)          # a textured background
    base[..., 3] = 255
    brace = np.abs((xx - 44) - (yy - 37) * 0.4) < 1.0                  # a thin static brace across the path
    frames = []
    for k in range(n):
        th = math.radians(amp_deg) * math.sin(2 * math.pi * cycles * k / n + math.radians(phase_deg))
        if slide:
            bx, by = pivot[0] + L * math.sin(th), pivot[1] + L
        else:
            bx, by = pivot[0] + L * math.sin(th), pivot[1] + L * math.cos(th)
        f = base.copy()
        f[np.hypot(xx - bx, yy - by) <= r, :3] = BOB
        f[brace, :3] = BRACE
        if k:
            f[..., 3] = np.where((yy > pivot[1] + L - 12) & (yy < pivot[1] + L + 10), 255, 0)
        frames.append(f)
    return frames, brace


def refuses(fn, needle: str) -> None:
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), f"refusal text {e!s} lacks {needle!r}"
        return
    raise AssertionError(f"expected a refusal containing {needle!r}")


def old_colour_mask(F, sel):
    St = np.stack([np.where(f[..., 3:4] > 0, f[..., :3], F[0][..., :3]) for f in F[1:]]).astype(np.float32)
    iy, ix = np.indices(St.shape[1:3])
    best = St[St.sum(-1).argmax(0), iy, ix]
    hsv = cv2.cvtColor(np.ascontiguousarray(best.astype(np.uint8)), cv2.COLOR_RGB2HSV_FULL).astype(np.float32)
    h, s, v = hsv[..., 0] * 360 / 256, hsv[..., 1] / 255, hsv[..., 2] / 255
    m = (s >= float(sel.get("minS", 0))) & (v >= float(sel.get("minV", 0)))
    if "hue" in sel:
        lo, hi = sel["hue"]
        m &= ((h >= lo) & (h <= hi)) if lo <= hi else ((h >= lo) | (h <= hi))
    return m


def main() -> int:
    sel = {"hue": [30, 70], "minS": 0.35, "minV": 0.4}
    for cycles, amp, phase, L in ((1, 15.0, 40.0, 25.0), (2, 20.0, -70.0, 25.0), (1, 12.0, 40.0, 40.0)):
        F, brace = pendulum(cycles=cycles, amp_deg=amp, phase_deg=phase, L=L)
        m = FX.fit_swing(F, (0, 0, 80, 64), "synthetic", sel)
        f = m["fit"]
        assert f["cyclesPerLoop"] == cycles, f
        dphi = (m["phaseDeg"] - phase + 180) % 360 - 180
        assert abs(dphi) <= 3.0, f
        assert abs(f["ampPx"] - L * math.sin(math.radians(amp))) <= 0.4, f
        assert abs(m["pivot"][0] - 40.0) <= 1.0, (m["pivot"], f)
        assert abs(m["ampDeg"] - amp) <= 3.0, f
        assert f["lengthBandPx"][0] <= L <= f["lengthBandPx"][1], f
        assert m["front"] is not None and (m["front"][..., 3] > 0)[brace & (np.abs(np.mgrid[0:64, 0:80][0] - (12 + L)) <= 3)].all(), \
            "the brace across the bob's path is not in the front card"
        assert tuple(m["plate"][int(12 + L), 40]) != BOB, "the plate keeps the bob at its rest position"
        assert f["redrawMaeRgb"] < f["staticPlateMaeRgb"], f

    F, _ = pendulum(slide=True)
    refuses(lambda: FX.fit_swing(F, (0, 0, 80, 64), "slide", sel), "no measurable arc")
    F, _ = pendulum(r=8)
    refuses(lambda: FX.fit_swing(F, (0, 0, 80, 64), "wide", sel), "show the bob in every frame")
    refuses(lambda: FX.fit_swing(pendulum()[0], (0, 0, 80, 64), "nocolour", None), "needs the bob's")

    lm = FX.layer_meta(SC.anim_frames())
    F = FX.def_frames(lm, "tbtwdw_0_2")
    m = FX.fit_swing(F, (15, 30, 55, 66), "tbtwdw_0_2", sel)
    f = m["fit"]
    assert f["cyclesPerLoop"] == 1 and m["periodFrames"] == 20, f
    assert abs(f["pivotPx"][0] - 36.2) <= 1.0 and 20.0 <= f["pivotPx"][1] <= 32.0, f     # under the clock face
    assert abs(f["ampPx"] - 7.2) <= 0.5 and 10.0 <= f["ampDeg"] <= 19.0, f
    assert f["redrawMaeRgb"] < f["staticPlateMaeRgb"], f

    for s in (sel, {"hue": [330, 30], "minS": 0.2}, {"minV": 0.8}, None):
        if s:
            assert (FX.colour_mask(F, s) == old_colour_mask(F, s)).all(), s
    print(f"test_town_full3d_fx_swing: OK (synthetic 1 and 2 swings / loop, brace in front; slide refused; "
          f"tbtwdw_0_2 pivot {f['pivotPx']} amp {f['ampDeg']} deg L {f['lengthPx']} px band {f['lengthBandPx']}; "
          f"redraw {f['redrawMaeRgb']} vs static {f['staticPlateMaeRgb']}; colour_mask unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
