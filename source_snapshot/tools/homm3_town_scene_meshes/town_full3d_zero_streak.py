#!/usr/bin/env python3
"""Full-3D towns: the zero-visible-streak certificate over the reachable camera set (measurement, no Unity).

    TOWN_FULL3D_FACTION=<t> TOWN_FULL3D_CANDIDATE=<c> python town_full3d_zero_streak.py [--loop 36] [--out DIR]

Acceptance bar (user, 2026-10-01): "the goal for any working method is 0 visible streaking behind objects". A lower
streak-pixel count is progress, not success. This tool turns the bar into a measurement (docs/
homm3_town_scene_methodology_v2.md, "The certificate"):

  poses     every pose that can show parallax. Cursor poses are pure rotations about the rest centre (they reveal
            nothing). The free sweep is a closed spline of camera centres; parallax depends only on the centre, and the
            opening of a depth edge and the texel stretch of a surface are linear / convex in the centre offset, so
            their worst case lies on the extreme centres. Sampled: the proof poses (conflux_town_camera_pan.
            proof_poses), the most forward centre of the sweep (`sweep_fwd`: 4.04 m forward against the proof poses'
            2.31 m), and --loop evenly spaced samples of the Catmull-Rom sweep with the look-at-pivot orientation.
  streak    a drawn px whose triangle's texel footprint is stretched (town_t2_streak_map: s1 >= S1_MIN px per texel
            and s1/s2 >= ANISO_MIN), the lane's existing definition.
  revealed  a drawn px whose surface point the rest camera does not see: reprojected into the rest frame it lies more
            than REVEAL_TOL behind the rest surface at that pixel. A curtain (a triangle along the rest rays) is
            revealed by this test everywhere behind its near lip. A point outside the rest frame is `extension`,
            reported apart (periphery, not "behind an object").
  behind    streak AND revealed inside the rest frame: a stretched surface the camera sees only because it moved past
            an occluder. This is the bar's "streaking behind objects".
  visible   a 4-connected component of `behind` px of at least --min-area px (default 16 at 1920x1080).
  hole      an undrawn px not connected to the frame's top / left / right border (no lit geometry: sky or the clear
            colour seen through the scene); the rest frame's own count (sky through arches, unlit Fx water) is the baseline.

The certificate passes when no pose has a visible `behind` component (the user's bar, 2026-10-01: zero visible
streaking behind objects). Enclosed holes are reported, not gated: windows and arches of the building bodies legitimately
open onto more sky as the camera moves (castle props_v1, a candidate without any cut, goes 707 -> 7909 px), so a hole
regression is read as the growth against the seed candidate's own report (`holeGrowthPx`). `groundHolePx` is the
sky-aware split: an undrawn px whose pose ray meets the painted floor plane inside the far cap must have hit ground, so
it is a ground hole (overlay yellow), a defect wherever it is; any other undrawn px is the dome's (sky windows magenta). A recipe must keep it at the rest frame's own count.
restSky refinement (coordinator 2026-10-02, Inferno zs_v1: 99 % of its ground holes): a ground-hole px whose floor hit
point projects onto an undrawn rest px is the painting's own sky in that direction (the floor plane runs on past the
painted horizon), not missing ground. It is excluded from groundHolePx only where the pose raster of the static Sky_
bins (load_sky: Sky_Dome / Sky_Pano, unposed) covers the px: the explicit check that the pose render shows the skybox
there, not the clear colour. Uncovered, or without `sky`, it still counts (fail closed). groundHiddenPx (a rest surface
stands in front of the hit point: unknown ground behind an occluder) always counts, so growth = 0 still holds for it.
Each pose row reports groundRestSkyPx (excluded), groundHiddenPx and groundRestSkyUncoveredPx (counted).
Background frame (coordinator 2026-10-02, a correctness fix of the term, general: Inferno zs_v3, 97 % of its hidden px):
the rest px q is judged against the environment-only rest frame too (env_frame_faces: every environment/ bin except the
backstop class, i.e. Mesh_Backstop and its floor fill, which are hidden fill and no part of the painting; no building
layer; the same rest camera). A building is a HoMM3 sprite over the background painting: where the background frame
shows sky at q, the painting has sky there (the state without that building shows it at rest), so a pose ray past the
building that reveals the dome is faithful. Such px are excluded too, still only where the pose's Sky_ raster covers
them (fail closed), and reported apart as groundRestSkyEnvPx. Hidden means a rest surface in front of the hit point
and the background frame drawn at q: ground behind an environment occluder, or behind a building where the
environment has a surface; it always counts. It is an offline
raster (moderngl, lit Mesh_ bins only, no alpha cut-out, no lighting; posed bins and Fx are not drawn):
generated-artifact proof; a pass does not replace the by-eye check in Unity editor renders.

Device (--device / TOWN_FULL3D_DEVICE, default cuda): the per-pose analysis runs on the GPU (town_gpu_kernels:
one moderngl context for every pose, torch CUDA for the reprojection / stretch / masks; ~18x per pose). The CPU code
below (device cpu) is the reference the GPU path must reproduce exactly (test_town_gpu_kernels.py, gated by
tools/validate_town_zero_streak_contract.py). A missing CUDA device fails; there is no silent fallback.
docs/town_gpu_kernels.md.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import label

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402
import town_t2_streak_map as SM  # noqa: E402
import conflux_town_camera_pan as PAN  # noqa: E402

REVEAL_TOL = 0.03      # a surface point this much (relative forward depth) behind the rest surface is hidden at rest
MIN_AREA = 16          # px: smallest behind-streak component counted as visible (1920x1080)
W, H = SC.W, SC.H
DEVICES = ("cpu", "cuda")
DEVICE = os.environ.get("TOWN_FULL3D_DEVICE", "cuda").strip() or "cuda"   # cuda: parity-proven against cpu


def bin_class(name: str) -> str:
    """Failure-class attribution of a staged bin name '<prefab>/<bin>' (methodology v2 taxonomy)."""
    k, b = name.split("/", 1)
    if k == "environment":
        if "Backstop" in b:
            return "backstop"
        if "Back_Terrain" in b:
            return "terrain_back"
        if b.startswith("Mesh_Terrain"):
            return "terrain_sheet"
        if "Outer" in b:
            return "periphery"
        if "Near" in b:
            return "nearfield"
        if b.startswith("Mesh_Prop"):
            return "prop"
        return "env_other"
    if b.startswith("Mesh_Decal_"):
        return "bldg_decal"
    if "_rest" in b or "BodyRest" in b or "resid" in b:
        return "bldg_residual"
    if b.endswith("_hull") or "_hull_" in b:
        return "bldg_hull"
    return "bldg_front"


def cam_from_root_pose(sc, pos_local, R_local) -> dict:
    """A pose in the scene root's local frame (as proof_poses gives it) -> a painting-world camera (S.pan_cams)."""
    pos = sc.cpos + (np.asarray(pos_local) / sc.scale) @ sc.C.T
    f = np.asarray(R_local[:, 2]) @ sc.C.T
    u = np.asarray(R_local[:, 1]) @ sc.C.T
    f /= np.linalg.norm(f)
    u /= np.linalg.norm(u)
    r = np.cross(u, f)
    return {**sc.cam, "pos": pos, "fwd": f, "up": u, "right": r / np.linalg.norm(r)}


def reachable_cams(sc, loop: int, extra=()) -> dict:
    """The proof poses, the forward-most sweep pose, `loop` evenly spaced sweep samples, and the named extra poses
    (loop_NNN, the same names the loop uses, or any other name reachable_cams_full gives: a recipe adds the poses an
    earlier certificate or `final` failed at)."""
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    c = PAN.load()
    p0, R0 = PAN.root_frame(c)
    sw = [p for p in PAN.poses(c, 48) if p["mode"] == "free/catmullRom/lookAt"]
    loc = [(R0.T @ (p["p"] - p0), R0.T @ p["R"]) for p in sw]
    i_fwd = int(np.argmax([q[2] for q, _ in loc]))
    cams["sweep_fwd"] = cam_from_root_pose(sc, *loc[i_fwd])
    if loop > 0:
        for j in np.linspace(0, len(loc), loop, endpoint=False).astype(int):
            cams[f"loop_{j:03d}"] = cam_from_root_pose(sc, *loc[j])
    full = None
    for name in extra:
        if not name.startswith("loop_"):
            # any other pose `final` (reachable_cams_full) measures: cursor_cN, free_<hyp>_<ori>_<tag>, transition_NNN
            # (Tower zs_v1 2026-10-02: final failed at transition_ / free_ poses a recipe could not name)
            if full is None:
                full = reachable_cams_full(sc)
            if name not in full:
                raise SystemExit(f"zero-streak: extra pose {name!r} is neither a sweep sample loop_NNN nor a pose of "
                                 f"reachable_cams_full")
            cams[name] = full[name]
            continue
        j = int(name[5:]) if name[5:].isdigit() else -1
        if not 0 <= j < len(loc):
            raise SystemExit(f"zero-streak: extra pose {name!r} is not a sweep sample loop_000..loop_{len(loc) - 1:03d}")
        cams[f"loop_{j:03d}"] = cam_from_root_pose(sc, *loc[j])
    return cams


def reachable_cams_full(sc, loop: int = 36) -> dict:
    """The one-time gate before install (v2 recipes): reachable_cams(loop) plus the rest of the controller's range that
    conflux_town_camera_pan.poses samples, at its extremes: the four cursor corners (yaw +-deltaHorizontalAngle x pitch
    +-deltaVerticalAngle at the rest position), each spline hypothesis (catmullRom / polygon) x orientation hypothesis
    (lookAt / restRotation) at its leftmost / rightmost heading and highest point, and every sampled mode transition
    at its midpoint (a = 0.5). Still 16:9 only: the other aspects are the runtime root scale's claim (not measured)."""
    cams = reachable_cams(sc, loop)
    c = PAN.load()
    p0, R0 = PAN.root_frame(c)
    ps = PAN.poses(c, 48)

    def loc(p):
        return R0.T @ (p["p"] - p0), R0.T @ p["R"]

    def azim(p):
        f = (R0.T @ p["R"])[:, 2]
        return math.degrees(math.atan2(f[0], f[2]))
    cur = [p for p in ps if p["mode"] == "cursor"]
    for i, p in enumerate(cur):
        if i in (0, 2, 6, 8):                     # the four (yaw, pitch) corners
            cams[f"cursor_c{i}"] = cam_from_root_pose(sc, *loc(p))
    for hyp in ("catmullRom", "polygon"):
        for ori in ("lookAt", "restRotation"):
            sw = [p for p in ps if p["mode"] == f"free/{hyp}/{ori}"]
            az = [azim(p) for p in sw]
            for tag, j in (("left", int(np.argmin(az))), ("right", int(np.argmax(az))),
                           ("high", int(np.argmax([p["p"][1] for p in sw])))):
                cams[f"free_{hyp}_{ori}_{tag}"] = cam_from_root_pose(sc, *loc(sw[j]))
    tr = [p for p in ps if p["mode"].startswith("transition/")]
    for k in range(1, len(tr), 3):               # the a = 0.5 sample of each (0.25, 0.5, 0.75) triple
        cams[f"transition_{k // 3:03d}"] = cam_from_root_pose(sc, *loc(tr[k]))
    return cams


def world_points(cam, z) -> np.ndarray:
    h, w = z.shape
    ys, xs = np.mgrid[0:h, 0:w]
    t = math.tan(math.radians(cam["fov"]) / 2)
    xn = ((xs + 0.5) / w * 2 - 1) * t * W / H
    yn = (1 - (ys + 0.5) / h * 2) * t
    d = (cam["fwd"][None, None] + xn[..., None] * cam["right"][None, None] + yn[..., None] * cam["up"][None, None])
    return cam["pos"][None, None] + d * np.where(np.isfinite(z), z, 0)[..., None]


def load_sky(sc, rows: dict, keys: list):
    """World (P, F) of the static Sky_ bins (kind sky, unposed) of the given prefabs, or None when none is staged. The
    restSky refinement of the ground-hole term rasters them per pose: a posed / drifting sky bin is left out (its
    coverage at a pose is not fixed), which can only count more px, never fewer."""
    Ps, Fs, off = [], [], 0
    for k in keys:
        for b in rows.get(k, {}).get("bins", []):
            if not b["name"].startswith("Sky_") or b.get("kind") != "sky" or b.get("pos") or b.get("rot"):
                continue
            v, _, _, subs = S.read_bin(S.STAGE / k / f"{b['name']}.bytes")
            Ps.append(sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T)
            Fs.append(np.concatenate(subs).reshape(-1, 3) + off)
            off += len(v)
    return (np.concatenate(Ps), np.concatenate(Fs)) if Ps else None


def _proj_fixed(cam, q):
    """T.project with the dot products written out in a fixed order (no BLAS): the GPU path reproduces it to ulps."""
    d = q - cam["pos"][None]
    dot = lambda u: d[:, 0] * float(u[0]) + d[:, 1] * float(u[1]) + d[:, 2] * float(u[2])
    zc = dot(cam["fwd"])
    t = math.tan(math.radians(cam["fov"]) / 2)
    return (dot(cam["right"]) / (zc * t * W / H) + 1) * 0.5 * W, (1 - dot(cam["up"]) / (zc * t)) * 0.5 * H, zc


def env_frame_faces(names, owner, F) -> np.ndarray:
    """Face mask of the background (environment-only) rest frame: the faces of every environment/ bin except the
    backstop class (Mesh_Backstop and its floor fill: hidden fill, not painting). No building layer is in it."""
    env_bins = np.array([n.startswith("environment/") and bin_class(n) != "backstop" for n in names], bool)
    return env_bins[np.asarray(owner, np.int64)] if len(F) else np.zeros(0, bool)


def ground_split(sc, cam, floor, ys, xs, fid_rest, z0, sky_cov, fid_env=None):
    """For ground-hole px (ys, xs) of a pose: (restSky, restSkyAny, hidden, restSkyEnv), bool per px. The floor hit
    point of the px's ray is projected into the rest frame: restSkyAny when it lands on a px the background frame
    (fid_env: the environment-only rest raster, env_frame_faces) leaves undrawn; restSky when the state's own rest
    frame is undrawn there and sky_cov (the pose's Sky_ raster coverage; None = no sky checked, nothing covered)
    covers the px; restSkyEnv when only the background frame is undrawn there (a building in front) and sky_cov covers
    the px; hidden when the background frame is drawn there and a rest surface lies in front of the hit point.
    fid_env None: the state's frame stands in for it (no restSkyEnv). The reference the GPU path
    (town_gpu_kernels.CertifyEngine) re-decides its borderline px with."""
    yi0, xi0 = np.asarray(ys, np.int64), np.asarray(xs, np.int64)
    ys, xs = yi0.astype(np.float64), xi0.astype(np.float64)
    t = math.tan(math.radians(cam["fov"]) / 2)
    xn = ((xs + 0.5) / W * 2 - 1) * t * W / H
    yn = (1 - (ys + 0.5) / H * 2) * t
    d = cam["fwd"][None] + xn[:, None] * cam["right"][None] + yn[:, None] * cam["up"][None]
    d = d / np.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2])[:, None]
    n = floor.n
    nd = d[:, 0] * float(n[0]) + d[:, 1] * float(n[1]) + d[:, 2] * float(n[2])
    th = (floor.d - float(n @ (cam["pos"] - sc.cam["pos"]))) / np.where(np.abs(nd) > 1e-12, nd, 1e-12)
    px, py, zc = _proj_fixed(sc.cam, cam["pos"][None] + d * th[:, None])
    ins = (zc > 0) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
    xi = np.clip(np.nan_to_num(px, nan=0).astype(np.int64), 0, W - 1)
    yi = np.clip(np.nan_to_num(py, nan=0).astype(np.int64), 0, H - 1)
    fr = fid_rest[yi, xi]
    sky_state = ins & (fr < 0)
    sky_any = sky_state if fid_env is None else ins & (fid_env[yi, xi] < 0)
    cov = np.zeros(len(xs), bool) if sky_cov is None else sky_cov[yi0, xi0]
    return (sky_state & cov, sky_any, ins & ~sky_any & (fr >= 0) & (z0[yi, xi] < zc),
            sky_any & ~sky_state & cov)


def certify(sc, P, UV, F, owner, names, texs, cams: dict, min_area=MIN_AREA, out: Path | None = None,
            save_worst: int = 3, faces_out: dict | None = None, device: str | None = None,
            unseen_out: dict | None = None, sky=None) -> dict:
    """faces_out (optional): filled with {face id: visible-behind px summed over the poses}, so a builder can act on
    the exact faces the certificate fails (methodology v2 pilot 2). unseen_out (optional): the same for the unseen-face
    stretch components (unseen_face()). device: cpu (the reference) or cuda (default
    DEVICE; same report, town_gpu_kernels). sky: load_sky()'s (P, F) for the restSky refinement of the ground-hole
    term (None: no px is excluded)."""
    device = device or DEVICE
    if device not in DEVICES:
        raise SystemExit(f"zero-streak: device {device!r} is not one of {DEVICES}")
    classes = np.array([bin_class(n) for n in names])
    rep = {"revealTol": REVEAL_TOL, "minArea": min_area, "s1Min": SM.S1_MIN, "anisoMin": SM.ANISO_MIN, "poses": {},
           "groundSkyChecked": sky is not None, "skyFaces": 0 if sky is None else int(len(sky[1]))}
    keep_imgs = []
    if device == "cuda":
        import town_gpu_kernels as GK
        eng = GK.CertifyEngine(sc, P, UV, F, owner, names, texs, REVEAL_TOL, sky=sky)
        try:
            for pose, cam in cams.items():
                row, (fv, cv), m = eng.pose(cam, min_area, classes, want_masks=out is not None, unseen_out=unseen_out)
                if faces_out is not None:
                    for a, b in zip(fv.tolist(), cv.tolist()):
                        faces_out[a] = faces_out.get(a, 0) + b
                rep["poses"][pose] = row
                _print_row(pose, row)
                if out is not None:
                    keep_imgs.append((row["visibleBehindPx"], pose, _overlay(**m)))
        finally:
            eng.release()
        return _finish(rep, keep_imgs, out, save_worst)
    z0, fid_rest = TP.zbuffer(sc.cam, P, F, sup=1)
    em = env_frame_faces(names, owner, F)
    if sky is not None and not em.any():
        raise SystemExit("zero-streak: the restSky refinement needs the background frame: no environment/ bin is staged")
    fid_env = TP.zbuffer(sc.cam, P, F[em], sup=1)[1] if em.any() else None
    rest_cnt = np.bincount(fid_rest[fid_rest >= 0], minlength=len(F))
    floor = T.Floor(sc.cam)
    for pose, cam in cams.items():
        z, fid = TP.zbuffer(cam, P, F, sup=1)
        vis = fid >= 0
        faces = np.unique(fid[vis])
        s1, s2 = SM.face_stretch(cam, P, UV, F, owner, texs, faces)
        lut = np.zeros(len(F), bool)
        lut[faces[(s1 >= SM.S1_MIN) & (s1 / s2 >= SM.ANISO_MIN)]] = True
        streak = vis & lut[np.where(vis, fid, 0)]
        wp = world_points(cam, z)
        px, py, zc = T.project(sc.cam, wp.reshape(-1, 3))
        px, py, zc = px.reshape(z.shape), py.reshape(z.shape), zc.reshape(z.shape)
        inside = vis & (zc > 0) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
        xi = np.clip(np.nan_to_num(px, nan=0).astype(np.int64), 0, W - 1)
        yi = np.clip(np.nan_to_num(py, nan=0).astype(np.int64), 0, H - 1)
        revealed = inside & (zc > z0[yi, xi] * (1 + REVEAL_TOL))
        extension = vis & ~inside
        behind = streak & revealed
        lab, nlab = label(behind)
        areas = np.bincount(lab.ravel())[1:] if nlab else np.zeros(0, np.int64)
        big = np.flatnonzero(areas >= min_area) + 1
        visible = np.isin(lab, big)
        if faces_out is not None and visible.any():
            fv, cv = np.unique(fid[visible], return_counts=True)
            for a, b in zip(fv.tolist(), cv.tolist()):
                faces_out[a] = faces_out.get(a, 0) + b
        # enclosed hole: undrawn px (no lit geometry) not connected to the frame's top / left / right border; the rest
        # frame's own enclosed count (sky seen through arches, unlit Fx water) is the baseline it is compared with
        el, _ = label(~vis)
        top = np.unique(np.r_[el[0], el[:, 0], el[:, -1]])
        enclosed = (~vis) & ~np.isin(el, top)
        # ground hole: an undrawn px whose pose ray meets the painted floor plane (T.Floor of the rest camera) nearer
        # than the far cap. Such a ray must hit ground; finding nothing there is a defect whatever encloses it. A ray
        # that misses the floor inside the cap is the dome's (sky windows under crowns, a ridge dropping against
        # infinity as the camera rises).
        ground = np.zeros_like(vis)
        if (~vis).any():
            dw = world_points(cam, np.where(vis, np.nan, 1.0)) - cam["pos"][None, None]
            dw /= np.maximum(np.linalg.norm(dw, axis=-1, keepdims=True), 1e-12)
            nd = dw @ floor.n
            t_hit = (floor.d - float(floor.n @ (cam["pos"] - sc.cam["pos"]))) / np.where(np.abs(nd) > 1e-12, nd, 1e-12)
            ground = (~vis) & (t_hit > 0) & (t_hit < T.FAR_CAP_M)
        # restSky refinement: the painting's own sky is excluded where the pose's Sky_ raster covers the px
        gy, gx = np.nonzero(ground)
        sky_cov = None if sky is None else TP.zbuffer(cam, sky[0], sky[1], sup=1)[1] >= 0
        rs, rs_any, hid, rs_env = ground_split(sc, cam, floor, gy, gx, fid_rest, z0, sky_cov, fid_env)
        g_split = {"groundRestSkyPx": int(rs.sum()), "groundRestSkyEnvPx": int(rs_env.sum()),
                   "groundHiddenPx": int(hid.sum()),
                   "groundRestSkyUncoveredPx": int((rs_any & ~rs & ~rs_env).sum())}
        ground[gy[rs | rs_env], gx[rs | rs_env]] = False
        ob = np.where(vis, owner[np.where(vis, fid, 0)], -1)
        by_cls = {}
        by_bin = {}
        for i in np.unique(ob[visible]):
            npx = int((visible & (ob == i)).sum())
            by_bin[names[i]] = npx
            by_cls[classes[i]] = by_cls.get(classes[i], 0) + npx
        nr = streak & ~revealed & ~extension
        nr_cls = {}
        for i in np.unique(ob[nr]):
            nr_cls[classes[i]] = nr_cls.get(classes[i], 0) + int((nr & (ob == i)).sum())
        uf, uf_cls, uf_bin = unseen_face(nr, fid, vis, rest_cnt, ob, classes, names, min_area, unseen_out)
        row = {"streakPx": int(streak.sum()), "revealedPx": int(revealed.sum()), "extensionPx": int(extension.sum()),
               "behindPx": int(behind.sum()), "visibleBehindPx": int(visible.sum()),
               "visibleBehindComponents": int(len(big)),
               "largestComponentPx": int(areas.max()) if len(areas) else 0,
               "streakNotRevealedPx": int((streak & ~revealed & ~extension).sum()),
               "streakExtensionPx": int((streak & extension).sum()),
               "enclosedHolePx": int(enclosed.sum()), "groundHolePx": int(ground.sum()), **g_split,
               "streakNotRevealedByClass": dict(sorted(nr_cls.items(), key=lambda kv: -kv[1])),
               "visibleBehindByClass": dict(sorted(by_cls.items(), key=lambda kv: -kv[1])),
               "visibleBehindTopBins": dict(sorted(by_bin.items(), key=lambda kv: -kv[1])[:12]),
               "unseenFacePx": uf, "unseenFaceByClass": uf_cls, "unseenFaceTopBins": uf_bin}
        rep["poses"][pose] = row
        _print_row(pose, row)
        if out is not None:
            keep_imgs.append((row["visibleBehindPx"], pose, _overlay(vis, ob, revealed, streak, visible, behind,
                                                                     enclosed, ground)))
    return _finish(rep, keep_imgs, out, save_worst)


def unseen_face(nr, fid, vis, rest_cnt, ob, classes, names, min_area, faces_out: dict | None = None):
    """Unseen-face stretch (Castle zs_v5, user 2026-10-01: "meshes plainly not lined up with textures"): a streaked
    px that is not revealed and lies inside the rest frame (streakNotRevealed), drawn by a face the rest camera never
    sees (no rest px), in a component of at least min_area. Such a face has no painting of its own: its texture is the
    rest projection smeared across it. -> (px, by class, top bins)."""
    m = nr & (rest_cnt[np.where(vis, fid, 0)] == 0)
    lab, n = label(m)
    if not n:
        return 0, {}, {}
    areas = np.bincount(lab.ravel())[1:]
    keep = np.zeros(n + 1, bool)
    keep[1 + np.flatnonzero(areas >= min_area)] = True
    big = keep[lab]
    if faces_out is not None and big.any():
        fv, cv = np.unique(fid[big], return_counts=True)
        for a, c in zip(fv.tolist(), cv.tolist()):
            faces_out[a] = faces_out.get(a, 0) + c
    cnt = np.bincount(ob[big], minlength=len(names))
    by_cls, by_bin = {}, {}
    for i in np.flatnonzero(cnt):
        by_bin[names[i]] = int(cnt[i])
        by_cls[classes[i]] = by_cls.get(classes[i], 0) + int(cnt[i])
    return (int(big.sum()), dict(sorted(by_cls.items(), key=lambda kv: -kv[1])),
            dict(sorted(by_bin.items(), key=lambda kv: -kv[1])[:12]))


def _print_row(pose: str, row: dict) -> None:
    print(f"{pose:14s} behind {row['visibleBehindPx']:7d} px in {row['visibleBehindComponents']:4d} comps "
          f"(largest {row['largestComponentPx']}) streak {row['streakPx']:7d} holes {row['enclosedHolePx']:6d} "
          f"ground {row['groundHolePx']} (restSky {row['groundRestSkyPx']} + env {row['groundRestSkyEnvPx']} excluded, "
          f"hidden {row['groundHiddenPx']}, "
          f"sky uncovered {row['groundRestSkyUncoveredPx']}) "
          + json.dumps(row["visibleBehindByClass"]), flush=True)


def _overlay(vis, ob, revealed, streak, visible, behind, enclosed, ground) -> np.ndarray:
    shade = np.where(vis, 70 + (ob * 37) % 120, 20).astype(np.uint8)
    img = np.stack([shade] * 3, -1)
    img[revealed] = (img[revealed] * 0.5 + np.array([0, 80, 160]) * 0.5).astype(np.uint8)
    img[streak & ~revealed] = [200, 120, 40]
    img[visible] = [255, 0, 0]
    img[behind & ~visible] = [255, 160, 160]
    img[enclosed & ~ground] = [255, 0, 255]
    img[ground] = [255, 230, 0]
    return img


def _finish(rep: dict, keep_imgs: list, out: Path | None, save_worst: int) -> dict:
    P_ = rep["poses"]
    rep["summary"] = {
        "poses": len(P_),
        "maxVisibleBehindPx": max(r["visibleBehindPx"] for r in P_.values()),
        "worstPose": max(P_, key=lambda k: P_[k]["visibleBehindPx"]),
        "posesWithVisibleBehind": sum(1 for r in P_.values() if r["visibleBehindComponents"]),
        "maxEnclosedHolePx": max(r["enclosedHolePx"] for r in P_.values()), "restEnclosedHolePx": P_["default"]["enclosedHolePx"],
        "sumVisibleBehindByClass": {},
        "holeGrowthPx": max(r["enclosedHolePx"] for r in P_.values()) - P_["default"]["enclosedHolePx"],
        "maxGroundHolePx": max(r["groundHolePx"] for r in P_.values()), "restGroundHolePx": P_["default"]["groundHolePx"],
        "groundHoleGrowthPx": max(r["groundHolePx"] for r in P_.values()) - P_["default"]["groundHolePx"],
        "maxGroundHiddenPx": max(r["groundHiddenPx"] for r in P_.values()),
        "maxGroundRestSkyPx": max(r["groundRestSkyPx"] for r in P_.values()),
        "maxGroundRestSkyEnvPx": max(r["groundRestSkyEnvPx"] for r in P_.values()),
        "maxGroundRestSkyUncoveredPx": max(r["groundRestSkyUncoveredPx"] for r in P_.values()),
        "groundSkyChecked": rep.get("groundSkyChecked", False),
        "pass": all(r["visibleBehindComponents"] == 0 for r in P_.values()),
        "maxUnseenFacePx": max(r["unseenFacePx"] for r in P_.values()),
        "worstUnseenFacePose": max(P_, key=lambda k: P_[k]["unseenFacePx"]),
        "unseenFacePass": all(r["unseenFacePx"] == 0 for r in P_.values()),
    }
    acc = {}
    for r in P_.values():
        for k, v in r["visibleBehindByClass"].items():
            acc[k] = acc.get(k, 0) + v
    rep["summary"]["sumVisibleBehindByClass"] = dict(sorted(acc.items(), key=lambda kv: -kv[1]))
    if out is not None:
        for _, pose, img in sorted(keep_imgs, key=lambda t: -t[0])[:save_worst]:
            Image.fromarray(img).save(out / f"zs_{pose}.png")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=36, help="evenly spaced sweep samples besides the proof poses")
    ap.add_argument("--min-area", type=int, default=MIN_AREA)
    ap.add_argument("--state", default="full")
    ap.add_argument("--out", default="")
    ap.add_argument("--save-worst", type=int, default=3)
    ap.add_argument("--device", choices=DEVICES, default=DEVICE,
                    help="cuda (default, town_gpu_kernels) or cpu (the reference implementation)")
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    out = Path(a.out) if a.out else S.WORK / "zero_streak"
    out.mkdir(parents=True, exist_ok=True)
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES[a.state]]
    P, UV, F, owner, names, texs = SM.load_bins(sc, rows, keys)
    rep = certify(sc, P, UV, F, owner, names, texs, reachable_cams(sc, a.loop), a.min_area, out, a.save_worst,
                 device=a.device, sky=load_sky(sc, rows, keys))
    rep.update({"schema": "town_zero_streak.v1", "faction": SC.FP.FRACTION, "candidate": S.CANDIDATE,
                "state": a.state, "bins": names})
    (out / "zero_streak_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(rep["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
