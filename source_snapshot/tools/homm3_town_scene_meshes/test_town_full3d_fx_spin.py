"""Focused test of town_full3d_fx.fit_spin (the rotor measurement behind the `spin` kind).

1. A synthetic 6-blade rotor turned by a known step per frame, drawn as a DEF would be (frame 0 whole, frames 1.. with
   transparent px outside the rotor), is measured back: hub within 1 px, speed (long-baseline track slope) within
   0.1 deg / frame, sense kept.
2. Factory's windmill DEF (tbfahrd2, 54 frames) measures as a rigid rotor: counter-clockwise, every frame step
   agreeing, track slope 1.97 deg / frame (104.75 deg over 53 frames), hub near (47, 18.5) DEF px.
3. Factory's flywheel and crank (tbfaup_3 [4, 100, 121, 156]) is refused: its steps do not agree (a crank and a wheel
   seen at a slant are not one rigid screen-plane rotor), so a profile cannot classify it as spin.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_fx_spin.py   (sets TOWN_FULL3D_FACTION=factory itself)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np

os.environ["TOWN_FULL3D_FACTION"] = "factory"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_common as SC  # noqa: E402
import town_full3d_fx as FX            # noqa: E402


def synthetic(step: float, n: int = 12, size: int = 64, hub=(30.0, 33.0)) -> list[np.ndarray]:
    blades = np.zeros((size, size), np.float32)
    for b in range(6):
        a = np.radians(b * 60.0)
        cv2.line(blades, (int(hub[0]), int(hub[1])),
                 (int(hub[0] + 22 * np.cos(a)), int(hub[1] - 22 * np.sin(a))), 1.0, 3)
    tower = np.zeros((size, size, 4), np.uint8)
    tower[..., :3] = (90, 120, 150)
    tower[..., 3] = 255
    tower[:, 26:34, :3] = (60, 50, 40)                 # a static post behind the rotor
    frames = []
    for k in range(n):
        r = cv2.warpAffine(blades, cv2.getRotationMatrix2D(hub, step * k, 1), (size, size))
        f = tower.copy()
        f[..., :3] = np.where(r[..., None] > 0.5, np.array([220, 200, 170], np.uint8), f[..., :3])
        if k:
            f[..., 3] = np.where(np.hypot(*np.mgrid[0:size, 0:size][::-1] - np.array(hub)[:, None, None]) <= 25, 255, 0)
        frames.append(f)
    return frames


def main() -> int:
    for step in (-3.0, 1.5, 5.5):
        m = FX.fit_spin(synthetic(step, n=30), (0, 0, 64, 64), "synthetic")
        got = m["steps"][0]
        assert abs(got - step) <= 0.1, f"synthetic step {step}: measured {got} ({m['fit']})"
        assert abs(m["cx"] - 30.0) <= 1.0 and abs(m["cy"] - 33.0) <= 1.0, f"synthetic hub {m['cx']}, {m['cy']}"
        assert m["fit"]["agreeShare"] >= 0.9, m["fit"]

    lm = FX.layer_meta(SC.anim_frames())
    m = FX.fit_spin(FX.def_frames(lm, "tbfahrd2"), (20, 0, 72, 48), "tbfahrd2")
    assert abs(m["steps"][0] - 1.967) <= 0.05, m["fit"]
    assert m["fit"]["agreeShare"] >= 0.95, m["fit"]
    hub = (m["cx"] + 20, m["cy"])
    assert abs(hub[0] - 47.1) <= 1.0 and abs(hub[1] - 18.5) <= 1.0, hub
    assert 18 <= m["rad"] <= 25, m["rad"]

    try:
        FX.fit_spin(FX.def_frames(lm, "tbfaup_3"), (4, 100, 121, 156), "tbfaup_3")
    except SystemExit as e:
        assert "not a rigid rotor" in str(e), str(e)
    else:
        raise AssertionError("tbfaup_3 flywheel + crank was accepted as a rigid rotor")

    print(f"test_town_full3d_fx_spin: OK (synthetic -3/+1.5/+5.5 deg; tbfahrd2 {m['steps'][0]} deg/frame "
          f"hub {hub[0]:.1f},{hub[1]:.1f} r {m['rad']:.1f}; tbfaup_3 refused)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
