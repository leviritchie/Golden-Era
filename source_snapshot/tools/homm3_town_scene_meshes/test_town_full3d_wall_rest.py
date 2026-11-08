"""town_full3d_wall_rest: walls are edge-on at rest (offline area gate) and the Unity-render line mask.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_wall_rest.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_buildings as BL  # noqa: E402
import town_full3d_wall_rest as WR  # noqa: E402
import test_town_full3d_closing_walls as CW  # noqa: E402

W, H = 1920, 1080
FOV = 40.0


def project(P, pos=np.zeros(3)):
    d = np.asarray(P, np.float64) - pos
    t = np.tan(np.radians(FOV) / 2)
    return ((d[:, 0] / (d[:, 2] * t * W / H) + 1) * 0.5 * W, (1 - d[:, 1] / (d[:, 2] * t)) * 0.5 * H, d[:, 2])


def main() -> int:
    cam, rays, zz, P, kept, cut_tris, u, w = CW.scene()
    Pw, _, _, _, _, tw, _ = BL.closing_walls(P, zz, cut_tris, cam, CW.SGN, u, w)
    # (1) edge-on at the camera they were built from: passes, with room to spare
    amax = WR.rest_area_or_exit("synthetic", Pw, tw, project)
    assert amax < 1e-9, amax
    # (2) a camera 5 cm off the build camera sees the walls' area: the gate fails closed
    try:
        WR.rest_area_or_exit("synthetic", Pw, tw, lambda q: project(q, np.array([0.05, 0.0, 0.0])))
    except SystemExit:
        pass
    else:
        raise AssertionError("walls seen off their build camera must fail the rest-area gate")
    # (3) line mask: the near edges' projected lines (1 px pad) cover every wall pixel of a filled-wall raster, and a
    # pixel far from any wall is off the mask
    edges = Pw.reshape(-1, 4, 3)[:, :2]
    cam_u = {"fwd": np.array([0, 0, 1.0]), "up": np.array([0, 1.0, 0]), "right": np.array([1.0, 0, 0]), "fov": FOV}
    m = WR.line_mask(edges, cam_u, W, H)
    px, py, _ = project(edges.reshape(-1, 3))
    assert m[np.clip(np.round(py - 0.5).astype(int), 0, H - 1), np.clip(np.round(px - 0.5).astype(int), 0, W - 1)].all()
    assert not m[0, 0] and m.mean() < 0.05, m.mean()
    print(f"OK wall_rest: {len(tw) // 2} walls, rest area max {amax:.2g} px^2, off-camera walls refused, "
          f"line mask {int(m.sum())} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
