"""Regression test for the building mask's speck / fringe removal (stronghold_full3d_buildings.drop_fringe).

769a896baf intersected the mask with an off-centre-anchored 2x2 MORPH_OPEN: that removed the transparent rim (the
Stronghold bars) but shaved the top / left px off every shape and deleted every sub-2px opaque feature (Inferno
tbinext2 rays). drop_fringe must keep a shape's full extent, keep a thin opaque line that differs from the painting,
drop a background-matching speck, and never return a px outside the input mask.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_mask_fringe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_buildings as BL  # noqa: E402


def main() -> None:
    painting = np.full((16, 16, 3), (120, 30, 20), np.int32)       # dark red sky
    rgb = painting.copy()
    m = np.zeros((16, 16), bool)
    m[3:9, 3:9] = True                                              # 6x6 opaque block, stone grey
    rgb[3:9, 3:9] = (90, 90, 90)
    m[1:15, 12] = True                                              # 1 px opaque ray, yellow
    rgb[1:15, 12] = (230, 200, 40)
    m[12, 5] = True                                                 # 1 px speck matching the painting
    rgb[12, 5] = (124, 32, 22)
    out = BL.drop_fringe(m, rgb, painting)
    assert not (out & ~m).any(), "drop_fringe added px outside the input mask"
    assert out[3:9, 3:9].all() and out[3:9, 3:9].sum() == 36, "the 6x6 block lost px (edge shave)"
    assert out[1:15, 12].all(), "the 1 px opaque ray that differs from the painting was removed"
    assert not out[12, 5], "the background-matching 1 px speck was kept"
    print("OK drop_fringe: 6x6 kept 6x6, opaque 1 px ray kept, background speck dropped, result within mask")


if __name__ == "__main__":
    main()
