"""Regression test for the building front-surface winding (stronghold_full3d_buildings.wind_to_camera).

A camera-facing relief grid on a steep depth face, with shading normals smoothed and bent toward a low key light the
way front_surface bends them: the normals disagree with the triangles' own side. The old rule (orient by the shading
normals) wound part of the face away from the camera, which the lab HexLit (Cull Off, back faces flip the normal)
shaded black as 1 px vertical bars. wind_to_camera must wind every triangle toward the camera, for either sgn.

Run: python tools/homm3_town_scene_meshes/test_town_full3d_winding.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_buildings as BL  # noqa: E402


def steep_face():
    cam = np.zeros(3)
    nx, ny = 24, 16
    u, w = np.meshgrid(np.linspace(-0.2, 0.2, nx), np.linspace(-0.15, 0.15, ny))
    rays = np.stack([u, w, np.ones_like(u)], -1)
    # a steep face: depth climbs 40 m across 0.4 rad of view (nearly edge-on), with a ripple
    z = 60.0 + 100.0 * (u + 0.2) + 1.5 * np.sin(w * 40.0)
    P = cam + rays * z[..., None]
    a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]).ravel()
    f = np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])
    # shading normals: toward the viewer, then bent most of the way toward a key light low on the far side
    to_cam = -P / np.linalg.norm(P, axis=-1, keepdims=True)
    to_sun = np.array([-0.9, 0.3, 0.3])
    to_sun /= np.linalg.norm(to_sun)
    n = 0.2 * to_cam + 0.8 * to_sun
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return cam, P.reshape(-1, 3), n.reshape(-1, 3), f


def facing(v, f, cam, sgn):
    g = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    return (g * (cam - v[f].mean(1))).sum(1) * sgn


def main() -> int:
    cam, v, n, f = steep_face()
    for sgn in (1.0, -1.0):
        old = BL.orient(v, f, n[f].mean(1), sgn)
        away_old = int((facing(v, old, cam, sgn) < 0).sum())
        assert away_old > 0, "premise: the shading-normal rule must mis-wind part of this face"
        new = BL.wind_to_camera(v, f, cam, sgn)
        away_new = int((facing(v, new, cam, sgn) < 0).sum())
        assert away_new == 0, f"sgn {sgn}: {away_new} of {len(f)} triangles wound away from the camera"
        assert np.array_equal(np.sort(new, 1), np.sort(f, 1)), "winding only: the vertex sets must not change"
        print(f"sgn {sgn:+.0f}: shading-normal rule {away_old}/{len(f)} away, wind_to_camera 0/{len(f)}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
