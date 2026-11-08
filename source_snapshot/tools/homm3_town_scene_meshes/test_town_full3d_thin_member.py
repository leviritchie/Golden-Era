"""Regression test for thin-member straightening (stronghold_full3d_solids.straighten_thin).

A thin member (pole, spire, blade) is refit as a straight member. The old fit was a plane z = a + b y + c x, so a
background-deep edge column (the depth model's bleed at a 1-3 px member's outline) tilted the member about its own
axis; at a side pose (Stronghold lyceum spire, pan_sweep_left) the front turned edge-on and the back behind it
rendered from inside as a black half-spire. The fit must be a line along the member's own axis: constant depth
across its width, the along-axis trend kept, for a vertical and for a diagonal member.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_thin_member.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_solids as SO  # noqa: E402

CAM = {"fov": 30.0}


def check(mask: np.ndarray, z: np.ndarray, across: list[np.ndarray], label: str) -> None:
    ld, rep = SO.straighten_thin({"mask": mask, "z": z}, CAM)
    assert rep["thinSegments"] >= 1, f"{label}: the member was not fitted ({rep})"
    zn = ld["z"]
    for idx in across:
        spread = float(np.ptp(zn[idx]))
        assert spread < 1e-6, f"{label}: depth varies {spread:.3f} m across the member's width (tilted about its axis)"


def main() -> None:
    # vertical spire: 3 px wide, 60 rows, depth 80 m at the top to 83 m at the foot; the left column bleeds 25 m of
    # background depth (the edge column drop_fringe keeps)
    mask = np.zeros((80, 40), bool)
    mask[10:70, 20:23] = True
    rows = np.arange(80)[:, None] * np.ones((1, 40))
    z = np.where(mask, 80.0 + (rows - 10) * 0.05, 0.0)
    z[10:70, 20] += 25.0
    check(mask, z, [(np.full(3, r), np.arange(20, 23)) for r in range(10, 70, 7)], "vertical")
    ld, _ = SO.straighten_thin({"mask": mask, "z": z}, CAM)
    top, foot = ld["z"][12, 21], ld["z"][67, 21]
    assert top < foot, "the along-axis depth trend was lost"
    # diagonal blade: 3 px wide along a 45 degree axis, constant true depth 90 m, one outline side bleeding +20 m
    m2 = np.zeros((80, 80), bool)
    for k in range(10, 70):
        m2[k, k:k + 3] = True
    z2 = np.where(m2, 90.0, 0.0)
    for k in range(10, 70):
        z2[k, k] += 20.0 if k % 2 == 0 else 0.0
    ld2, rep2 = SO.straighten_thin({"mask": m2, "z": z2}, CAM)
    assert rep2["thinSegments"] >= 1
    # px at the same position along the axis (x + y constant) sit across the width: same depth
    ys, xs = np.nonzero(m2)
    t = xs + ys
    for tv in (60, 80, 100):
        sel = t == tv
        if sel.sum() >= 2:
            spread = float(np.ptp(ld2["z"][ys[sel], xs[sel]]))
            assert spread < 0.5, f"diagonal: depth varies {spread:.3f} m across the blade"
    print("OK straighten_thin: vertical and diagonal members straight along their axis, flat across their width")


if __name__ == "__main__":
    main()
