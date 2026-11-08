#!/usr/bin/env python3
"""Full-3D T2 towns: where does the scene streak / warp at the reachable pan poses? (measurement, no Unity).

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<cand> python town_t2_streak_map.py [--poses a,b] [--out DIR]

A streak is a surface whose texture is magnified much more along one screen direction than the other: a painting-
projected triangle seen at a grazing angle at rest (a depth curtain, a hill's hidden back, a relief side) is drawn
from a handful of texels stretched over many screen px once the camera pans. Measured per drawn triangle from its
own UVs and the albedo size, so it is source-agnostic (painting projection, outpaint, Meshy, vanilla tiles):

    J = d(screen px) / d(texel) of the triangle under the pose camera; s1 >= s2 its singular values
    streak px  <=>  s1 >= S1_MIN px per texel  and  s1 / s2 >= ANISO_MIN

Every lit Mesh_* bin of the build state "full" (environment + STATES["full"] prefabs) is rasterised with face ids
(town_full3d_t2_paint.zbuffer) at the pose. Per pose it writes <out>/streak_<pose>.png (the mask in red over a flat
shade of the drawn bins), streak_<pose>.npz (mask, camera depth, face bin index) and streak_report.json: streak px per
pose and per bin, and inside / outside the painted rect's rest footprint. Poses: conflux_town_camera_pan.proof_poses
(the vanilla camera's extremes, never limited). Proof tier: generated artifact (offline raster, not the Unity render).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402

S1_MIN = 6.0        # screen px per texel along the stretched direction
ANISO_MIN = 3.0     # stretched / across
SUP = 1
POSES = ("sweep_left", "sweep_right", "sweep_high", "cursor_left", "cursor_right")


def png_size(p: Path) -> tuple[int, int]:
    with open(p, "rb") as f:
        h = f.read(24)
    return struct.unpack(">II", h[16:24])


def load_bins(sc, rows: dict, keys: list[str]):
    to_world = lambda v: sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T
    Ps, UVs, Fs, owner, names, texs = [], [], [], [], [], []
    off = 0
    for k in keys:
        for b in rows.get(k, {}).get("bins", []):
            if not b["name"].startswith("Mesh_") or b.get("kind", "lit") != "lit" or b.get("pos") or b.get("rot"):
                continue
            v, _, uv, subs = S.read_bin(S.STAGE / k / f"{b['name']}.bytes")
            f = np.concatenate(subs).reshape(-1, 3)
            Fs.append(f + off)
            Ps.append(to_world(v))
            UVs.append(np.asarray(uv, np.float64))
            owner.append(np.full(len(f), len(names), np.int32))
            names.append(f"{k[len(S.PREFIX):]}/{b['name']}")
            texs.append(png_size(S.STAGE / k / f"{b['name']}_albedo.png"))
            off += len(v)
    return (np.concatenate(Ps), np.concatenate(UVs), np.concatenate(Fs), np.concatenate(owner), names,
            np.asarray(texs, np.float64))


def face_stretch(cam, P, UV, F, owner, texs, faces: np.ndarray):
    """(s1, s2) screen px per texel of the given faces under cam."""
    f = F[faces]
    px, py, z = T.project(cam, P[f.ravel()])
    sp = np.stack([px, py], 1).reshape(-1, 3, 2)
    wh = texs[owner[faces]]                                    # (n, 2) texture w, h
    tp = UV[f.ravel()].reshape(-1, 3, 2) * wh[:, None, :]      # texel coords
    dS = np.stack([sp[:, 1] - sp[:, 0], sp[:, 2] - sp[:, 0]], 2)   # (n, 2, 2) columns = edges in screen
    dT = np.stack([tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0]], 2)   # columns = edges in texels
    det = dT[:, 0, 0] * dT[:, 1, 1] - dT[:, 0, 1] * dT[:, 1, 0]
    ok = np.abs(det) > 1e-9
    inv = np.zeros_like(dT)
    inv[ok, 0, 0], inv[ok, 1, 1] = dT[ok, 1, 1] / det[ok], dT[ok, 0, 0] / det[ok]
    inv[ok, 0, 1], inv[ok, 1, 0] = -dT[ok, 0, 1] / det[ok], -dT[ok, 1, 0] / det[ok]
    J = dS @ inv
    s = np.linalg.svd(J, compute_uv=False)
    s[~ok] = [1e3, 1.0]                                         # degenerate UVs: one texel smeared over the face
    return s[:, 0], np.maximum(s[:, 1], 1e-6)


def rest_rect_mask(cam_pose, zpose, sc) -> np.ndarray:
    """Pose px whose surface projects inside the painted rect (0..TW, 0..TH) under the rest camera."""
    h, w = zpose.shape
    ys, xs = np.mgrid[0:h, 0:w]
    fin = np.isfinite(zpose)
    t = np.tan(np.radians(cam_pose["fov"]) / 2)
    xn = ((xs + 0.5) / w * 2 - 1) * t * W / H
    yn = (1 - (ys + 0.5) / h * 2) * t
    d = (cam_pose["fwd"][None, None] + xn[..., None] * cam_pose["right"][None, None]
         + yn[..., None] * cam_pose["up"][None, None])
    wp = cam_pose["pos"][None, None] + d * np.where(fin, zpose, 0)[..., None]
    px, py, _ = T.project(sc.cam, wp.reshape(-1, 3))
    inside = (px >= 0) & (px < SC.TW) & (py >= 0) & (py < SC.TH)
    return inside.reshape(h, w) & fin, wp


W, H = SC.W, SC.H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poses", default=",".join(POSES))
    ap.add_argument("--out", default="")
    ap.add_argument("--state", default="full")
    ap.add_argument("--orbits", action="store_true",
                    help="also the review orbits (S.ORBITS via S.orbit_cam: not runtime poses, review only) as "
                         "orbit_y<yaw>_p<pitch>, matching the Unity render names pan_orbit_*")
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    out = Path(a.out) if a.out else S.WORK / "streak"
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES[a.state]]
    P, UV, F, owner, names, texs = load_bins(sc, rows, keys)
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    poses = [p for p in a.poses.split(",") if p]
    if a.orbits:
        orb = {f"orbit_y{y:+d}_p{p:+d}": S.orbit_cam(sc, y, p) for y, p in S.ORBITS}
        cams.update(orb)
        poses += [p for p in orb if p not in poses]
    rep = {"faction": SC.FP.FRACTION, "candidate": S.CANDIDATE, "s1Min": S1_MIN, "anisoMin": ANISO_MIN, "poses": {}}
    from scipy.ndimage import label as _label
    for pose in poses + ["default"]:
        cam = cams[pose]
        z, fid = TP.zbuffer(cam, P, F, sup=SUP)
        vis = fid >= 0
        faces = np.unique(fid[vis])
        s1, s2 = face_stretch(cam, P, UV, F, owner, texs, faces)
        streak_f = (s1 >= S1_MIN) & (s1 / s2 >= ANISO_MIN)
        lut = np.zeros(len(F), bool)
        lut[faces[streak_f]] = True
        m = vis & lut[np.where(vis, fid, 0)]
        inside, wp = rest_rect_mask(cam, z, sc)
        ob = np.where(vis, owner[np.where(vis, fid, 0)], -1)
        per_bin = {}
        for i in np.unique(ob[m]):
            per_bin[names[i]] = int((m & (ob == i)).sum())
        per_bin = dict(sorted(per_bin.items(), key=lambda kv: -kv[1]))
        # enclosed gap: undrawn px (no lit geometry) not connected to the frame's top/left/right border (sky reaches
        # the frame through those); a hole inside the drawn scene, which Unity shows as the clear colour or sky
        el, _ = _label(~vis)
        top = np.unique(np.r_[el[0], el[:, 0], el[:, -1]])
        enclosed = (~vis) & ~np.isin(el, top)
        rep["poses"][pose] = {"streakPx": int(m.sum()), "drawnPx": int(vis.sum()),
                              "terrainStreakPx": int(sum(v for k, v in per_bin.items() if "Mesh_Terrain" in k
                                                         or "Mesh_Back_Terrain" in k)),
                              "enclosedEmptyPx": int(enclosed.sum()),
                              "streakShare": round(float(m.sum() / max(vis.sum(), 1)), 4),
                              "insidePaintedRect": int((m & inside).sum()), "outsidePaintedRect": int((m & ~inside).sum()),
                              "perBin": per_bin}
        shade = np.where(vis, 70 + (ob * 37) % 120, 20).astype(np.uint8)
        img = np.stack([shade, shade, shade], -1)
        img[m] = [230, 30, 30]
        img[m & inside] = [255, 200, 0]
        img[enclosed] = [255, 0, 255]
        Image.fromarray(img).save(out / f"streak_{pose}.png")
        np.savez_compressed(out / f"streak_{pose}.npz", mask=m, inside=inside, z=z.astype(np.float32),
                            owner=ob.astype(np.int16), world=wp.astype(np.float32))
        print(pose, json.dumps({k: v for k, v in rep["poses"][pose].items() if k != "perBin"}),
              list(per_bin.items())[:6], flush=True)
    rep["bins"] = names
    (out / "streak_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
