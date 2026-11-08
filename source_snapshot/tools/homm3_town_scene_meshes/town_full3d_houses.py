#!/usr/bin/env python3
"""Repeated painted props (the Stronghold background cabins) as one modelled mesh, instanced over the painting.

The painting's repeated props were relief on Mesh_Terrain: under the vanilla sweeps their monocular-depth bumps smear
the painted pixels (town_full3d_stretch.py ranks them). This lane replaces them by ONE model (a Meshy image-to-3D
cabin, geometry only), placed once per painted instance:

  fit     per instance: yaw (about world up), uniform scale and base (a pixel of the instance's foot, cast onto the
          local ground plane fitted to the painted terrain around the foot) chosen so the model's rest-camera
          silhouette matches the instance's painted mask (IoU over the pixels no nearer house / sky covers;
          building sprites overlay the painting only when built, so they are not excluded) plus a small term that puts the model's gable end on the painted dark gable. Instances listed as
          split in the houses manifest are two models fitted jointly to one mask. Writes placement.json + viz.
  stage   Mesh_Houses (one environment bin: every instance's copy of the model, one atlas): each triangle the rest
          camera sees takes the painting's own pixels by rest-camera projection, de-lit by the Hex/Lit irradiance of
          its interpolated normal, so the rest pose reproduces the painting; a triangle it does not see (facing
          away, occluded, or grazing) takes the mirrored (180 deg about the instance's vertical axis) projection into
          the instance's back-fill texture (stronghold_full3d_solids.back_fill + its contrast / luminance caps).
  carve   (hooks, TOWN_FULL3D_HOUSES=<dir>) stronghold_full3d_common.albedo_background() returns the painting with
          the instances' pixels refilled with nearby ground, and stronghold_full3d_ground.frame_depth() replaces
          the terrain depth under them by the surrounding ground's (push-pull), so no painted house stays in the
          terrain behind the modelled one.

Inputs: the houses dir's manifest.json (schema town_full3d_houses.v1: faction, model glb, labels npy = int32 1080x1920
frame labels, 0 = none; split ids; meshy provenance). Nothing here reads a faction name.

Groups: one model per houses dir. TOWN_FULL3D_HOUSES may list several dirs (os.pathsep, ';' on Windows), one per
model group (e.g. cottages and longhouses): the carve is the union of every group's, and stage writes every group's
instances into the one Mesh_Houses bin (one atlas; the instances of all groups occlude each other in the rest
buffers). fit --peers <dir;dir> treats the other groups' labels as occluders / non-ground, as a group's own are.
A single dir with the default carve runs the original code path (Stronghold's output is byte-identical).

Open edges (manifest "openRectEdges", default false): fit ignores the frame pixels past the painting's right / bottom
edge, where a frame-cut house has no painted pixels, so its model may continue past the cut instead of shrinking to it.

Carve (manifest "carve"): "label" (default) carves every labelled pixel grown CARVE_DILATE px. "silhouette" carves
only the pixels the placed model covers at the rest pose (fit writes silhouettes.npz), grown CARVE_DILATE px but only
into pixels some placed model covers, and
never a pixel of manifest "propMask" (npy, frame bool: the painting's props) that no group labels: an unmodelled
neighbour keeps its painted pixels at rest, and a labelled pixel the model does not cover stays painted too. Labels
should be cluster-complete (every member of a fused cluster of painted props labelled), since the model of one member
carries the painting's pixels of whatever it covers. The silhouette carve's depth is the ring's push-pull depth, but
never nearer than CARVE_BACK_M behind the placed model's farthest rest depth at that pixel (silhouettes.npz Z<label>):
a hole whose ring is a nearer house would otherwise refill in front of its own model (measured: a cottage behind
another was hidden whole at rest). Nor farther than the model's own ground (silhouettes.npz B<label>, N<label>: per covered px,
the depth where its ray meets the horizontal plane through the base of the instance drawn there; grown CARVE_DILATE
px): the ring's push-pull is dominated by the far terrain around a silhouette and left a pit under every footprint
(Castle zs_v5, user 2026-10-01 "some floating in the air": cottage 2 at 38 m over terrain at 66-77 m, a 5.6 m gap).
The carved terrain behind a model now continues its own ground; the ground-contact gate
(town_full3d_ground_contact.py) is the guard that measures it.

    python town_full3d_houses.py silhouettes --faction <key> --houses <dir>   (rewrite silhouettes.npz from placement)
    python town_full3d_houses.py foot --faction <key> --houses <dir> [--peers <dir;dir>] [--dry-run]
          (the foot check, foot_contact: fit runs it and fails closed; stage needs a passing foot_contact.json for
          its group set. It catches a label that cuts the painted house, which leaves the model floating over the
          painted ground in front of it.)

    python town_full3d_houses.py fit   --faction stronghold --houses <dir> [--peers <dir;dir>]
    TOWN_FULL3D_HOUSES=<dir[;dir]> TOWN_FULL3D_CANDIDATE=<c> python town_full3d_houses.py stage --faction stronghold

Proof tier: generated artifact (offline previews); bundle / editor render / in-game unproven until exercised.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if "--faction" in sys.argv:
    os.environ["TOWN_FULL3D_FACTION"] = sys.argv[sys.argv.index("--faction") + 1]

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SCHEMA = "town_full3d_houses.v1"
TEX_K = 3                  # atlas texels per 1080p frame px
FACING_MIN = 0.22          # a triangle whose normal . view is below this at the rest pose is grazing (not projected)
VISIBLE_MIN = 0.6          # share of a triangle's rest-pose pixels that must be its own to take the projection
CARVE_DILATE = 3           # frame px the painted instance masks are grown before the terrain carve
CARVE_BACK_M = 0.5         # silhouette carve: the carved terrain sits at least this far behind the model (painting m)
CARVE_NEAR_TOL = 0.01      # silhouette carve: ground under a model stays this ratio behind the model's front surface
LIGHT_FLOOR = 0.35          # stage: de-light gain floor, as a share of the instance's median irradiance
TILE_PAD = 64               # stage: frame px the texture buffers extend past the painted rect
RING_MIN = 120              # ground px the local plane is fitted to (the ring dilates until it has them)
GABLE_W = 0.25             # fit: weight of the dark-gable term
DARK_LUM = 70.0            # fit: painted luminance under which a pixel counts as the shaded gable
FOOT_ROW_PX = 4            # foot check: the painted px sampled this far below a silhouette's bottom edge (past the carve)
FOOT_TOL = 0.08            # foot check: painted ground farther than the base plane's depth x (1 + this) is behind the base
FOOT_FLOAT_MAX = 0.25      # foot check: an instance floats when more than this share of its edge px have ground behind it
FOOT_MIN_PX = 8            # foot check: fewer measurable edge px than this: the foot is hidden (recorded, not judged)
FOOT_SLIDE_MAX = 1.5       # fit's foot slide: an instance floating by more than this ratio is a label problem, not a slide


# ------------------------------------------------------------------------------------------------ manifest
def houses_dir(d: str | None = None) -> Path | None:
    d = d or os.environ.get("TOWN_FULL3D_HOUSES", "").strip()
    return Path(d) if d else None


def houses_dirs(d: str | None = None) -> list:
    """Every group dir of TOWN_FULL3D_HOUSES (or d), os.pathsep separated; [] if unset."""
    d = d or os.environ.get("TOWN_FULL3D_HOUSES", "").strip()
    out = [Path(x.strip()) for x in d.split(os.pathsep) if x.strip()] if d else []
    if len({str(x.resolve()).lower() for x in out}) != len(out):
        raise SystemExit(f"TOWN_FULL3D_HOUSES lists a dir twice: {d}")
    return out


def _single_label_dir(dirs: list) -> bool:
    """One group carved by label: the original code path (byte-identical)."""
    return len(dirs) == 1 and manifest(dirs[0]).get("carve", "label") == "label"


def silhouettes(d: Path, man: dict) -> dict:
    """{label: frame bool} rest-pose silhouettes of the placed models (fit writes them), checked against placement."""
    z = np.load(d / "silhouettes.npz")
    sha = hashlib.sha256((d / "placement.json").read_bytes()).hexdigest()
    if str(z["placementSha256"]) != sha:
        raise SystemExit(f"{d}: silhouettes.npz is not of this placement.json; run fit again")
    return {int(k[1:]): z[k] for k in z.files if k.startswith("L")}


def rest_far(d: Path, man: dict) -> dict:
    """{label: frame float32} the placed model's farthest rest-pose camera depth per covered px (inf elsewhere)."""
    z = np.load(d / "silhouettes.npz")
    sha = hashlib.sha256((d / "placement.json").read_bytes()).hexdigest()
    if str(z["placementSha256"]) != sha:
        raise SystemExit(f"{d}: silhouettes.npz is not of this placement.json; run fit again")
    out = {int(k[1:]): z[k] for k in z.files if k.startswith("Z")}
    if not out:
        raise SystemExit(f"{d}: silhouettes.npz has no rest depths (Z<label>); run town_full3d_houses.py silhouettes")
    return out


def rest_ground(d: Path, man: dict) -> dict:
    """{label: (B, N, Z)} frame float32: the base height (world y) of the instance drawn at each covered px (nan
    uncovered), the model's nearest depth there and its farthest (both inf uncovered)."""
    z = np.load(d / "silhouettes.npz")
    sha = hashlib.sha256((d / "placement.json").read_bytes()).hexdigest()
    if str(z["placementSha256"]) != sha:
        raise SystemExit(f"{d}: silhouettes.npz is not of this placement.json; run fit again")
    out = {int(k[1:]): (z[k], z["N" + k[1:]], z["Z" + k[1:]]) for k in z.files if k.startswith("B")}
    if not out:
        raise SystemExit(f"{d}: silhouettes.npz has no base heights (B<label>, the carve's pit guard); run "
                         "town_full3d_houses.py silhouettes")
    return out


def group_ground():
    """(cap, near) frame float: cap, the farthest depth the silhouette carve's terrain may take: where the px's rest
    ray meets the horizontal plane through the base of the model covering it (where models overlap, the farthest one's:
    the ground behind both lies under it; the highest base made a nearer, higher longhouse bury the one behind it by
    1.5 m, Castle restage 2026-10-01); grown CARVE_DILATE px into the uncovered px only, by the highest neighbouring
    base; inf where unconstrained or the ray does not descend to it);
    near, the nearest model depth per covered px (inf elsewhere). None on the single label dir path."""
    dirs = houses_dirs()
    if not dirs or _single_label_dir(dirs):
        return None
    NONE = -1e9
    by = np.full((H, W), NONE, np.float32)
    far = np.full((H, W), -np.inf, np.float32)
    near = np.full((H, W), np.inf, np.float32)
    for d in dirs:
        man = manifest(d)
        if man.get("carve", "label") != "silhouette":
            continue
        for b, zn, zf in rest_ground(d, man).values():
            ok = np.isfinite(b) & (zf > far)
            by[ok] = b[ok]
            far[ok] = zf[ok]
            near = np.minimum(near, zn)
    k = 2 * CARVE_DILATE + 1
    grown = cv2.dilate(by, np.ones((k, k), np.uint8))
    by = np.where(by > NONE / 2, by, grown).astype(np.float64)
    cam = T.camera()
    ys, xs = np.mgrid[0:H, 0:W]
    ry = T.rays(cam, xs + 0.5, ys + 0.5)[..., 1]          # forward component 1: the ray parameter is camera depth
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (by - cam["pos"][1]) / ry
    cap = np.where((by > NONE / 2) & (ry < 0) & np.isfinite(t) & (t > 0), t, np.inf)
    return cap, near.astype(np.float64)


def group_behind() -> np.ndarray | None:
    """Frame float: the nearest depth the silhouette carve's terrain may take (model far depth + CARVE_BACK_M; 0 where
    unconstrained), or None on the single label dir path."""
    dirs = houses_dirs()
    if not dirs or _single_label_dir(dirs):
        return None
    lim = np.zeros((H, W), np.float64)
    for d in dirs:
        man = manifest(d)
        if man.get("carve", "label") != "silhouette":
            continue
        for zf in rest_far(d, man).values():
            ok = np.isfinite(zf)
            lim[ok] = np.maximum(lim[ok], zf[ok] + CARVE_BACK_M)
    return lim


def group_holes(dirs: list) -> list:
    """[(foot row, frame bool hole, unclaimed props or None)] per labelled instance over every group: label mode = the
    label grown CARVE_DILATE px; silhouette mode = (label & rest silhouette) grown CARVE_DILATE px inside the union of
    every silhouette group's rest coverage (a px no model covers keeps its painting), minus the propMask px no group
    labels."""
    k = 2 * CARVE_DILATE + 1
    ker = np.ones((k, k), np.uint8)
    mans = [manifest(d) for d in dirs]
    labs = [labels(d, m) for d, m in zip(dirs, mans)]
    claimed = np.zeros((H, W), bool)
    for lab in labs:
        claimed |= lab > 0
    cover = np.zeros((H, W), bool)
    for d, man in zip(dirs, mans):
        if man.get("carve", "label") == "silhouette":
            for sm in silhouettes(d, man).values():
                cover |= sm
    out = []
    for d, man, lab in zip(dirs, mans, labs):
        mode = man.get("carve", "label")
        if mode not in ("label", "silhouette"):
            raise SystemExit(f"{d}: carve {mode!r} is not label / silhouette")
        foreign = None
        if mode == "silhouette":
            if not man.get("propMask"):
                raise SystemExit(f"{d}: carve silhouette needs a propMask (the painting's props) to protect neighbours")
            pm = np.load(d / man["propMask"])
            if pm.shape != (H, W):
                raise SystemExit(f"{d}: propMask {pm.shape} is not the {H}x{W} frame")
            foreign = (pm > 0) & ~claimed
            sil = silhouettes(d, man)
        for i in sorted(int(x) for x in np.unique(lab) if x > 0):
            m = lab == i
            if mode == "silhouette":
                if i not in sil:
                    raise SystemExit(f"{d}: label {i} has no silhouette; run fit again")
                h = (cv2.dilate((m & sil[i]).astype(np.uint8), ker) > 0) & cover & ~foreign
            else:
                h = cv2.dilate(m.astype(np.uint8), ker) > 0
            out.append((int(np.nonzero(m)[0].max()), h, foreign))
    return out


def manifest(d: Path) -> dict:
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man.get("schema") != SCHEMA or man.get("faction") != SC.FACTION:
        raise SystemExit(f"TOWN_FULL3D_HOUSES {d}: schema {man.get('schema')!r} / faction {man.get('faction')!r} "
                         f"is not {SCHEMA} / {SC.FACTION!r}")
    return man


def labels(d: Path, man: dict) -> np.ndarray:
    lab = np.load(d / man["labels"])
    if lab.shape != (H, W):
        raise SystemExit(f"houses labels {lab.shape} are not the {H}x{W} frame")
    return lab.astype(np.int32)


def carve_mask(d: Path | None = None) -> np.ndarray | None:
    """Frame px carved out of the terrain (every labelled instance, grown CARVE_DILATE px), or None if unset."""
    dirs = houses_dirs(str(d) if d else None)
    if not dirs:
        return None
    if not _single_label_dir(dirs):
        m = np.zeros((H, W), bool)
        for _, h, _ in group_holes(dirs):
            m |= h
        return m
    d = dirs[0]
    lab = labels(d, manifest(d))
    k = 2 * CARVE_DILATE + 1
    return cv2.dilate((lab > 0).astype(np.uint8), np.ones((k, k), np.uint8)) > 0


# ------------------------------------------------------------------------------------------------ carve hooks
def _fill_ground(img: np.ndarray, holes: list, avoid: np.ndarray) -> np.ndarray:
    """img with each hole (one per instance, in the given order) refilled from nearby ground: the shift (dx over +-6
    hole widths, dy from -1/3 to +1 hole height) whose source is clear of every still-unfilled hole and of avoid, and
    whose ring best matches the hole's own ring (SSD over the clear ring px), copied in feathered with the ring's mean
    offset. A filled hole becomes source for the next. A hole with no clear shift falls back to cv2.inpaint (counted in fallbackPx)."""
    out = img.astype(np.float32).copy()
    h, w = img.shape[:2]
    left = np.zeros((h, w), bool)
    for m in holes:
        left |= m
    fallback = np.zeros((h, w), bool)
    pad = 3
    for m in holes:
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        bw, bh = x1 - x0, y1 - y0
        mg = pad + 4                                   # crop margin: room for the dilation and the ring around it
        oy, ox = max(y0 - mg, 0), max(x0 - mg, 0)
        ey, ex = min(y1 + mg, h), min(x1 + mg, w)
        mm = cv2.dilate(m[oy:ey, ox:ex].astype(np.uint8), np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) > 0
        ring = (cv2.dilate(mm.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~mm
        dst = out[oy:ey, ox:ex]
        blocked = left | avoid                         # never copy from a hole (its own included)
        best, best_e = None, np.inf
        for dy in range(-(bh // 3), bh + 1, 2):
            for dx in range(-6 * bw, 6 * bw + 1, max(bw // 4, 1)):
                if abs(dx) < bw * 0.8:
                    continue
                sy0, sx0 = oy + dy, ox + dx
                if sy0 < 0 or sx0 < 0 or sy0 + mm.shape[0] > h or sx0 + mm.shape[1] > w:
                    continue
                blk = blocked[sy0:sy0 + mm.shape[0], sx0:sx0 + mm.shape[1]]
                if (blk & mm).any() or blk[mm].size == 0:
                    continue
                src = out[sy0:sy0 + mm.shape[0], sx0:sx0 + mm.shape[1]]
                rk = ring & ~blk
                if rk.sum() < 8:
                    continue
                e = float(((src[rk] - dst[rk]) ** 2).mean()) + 0.5 * abs(dy) + 0.02 * abs(dx)
                if e < best_e:
                    best, best_e = (dy, dx), e
        if best is None:
            fallback |= m
            continue
        dy, dx = best
        src = out[oy + dy:oy + dy + mm.shape[0], ox + dx:ox + dx + mm.shape[1]].copy()
        rk = ring & ~blocked[oy + dy:oy + dy + mm.shape[0], ox + dx:ox + dx + mm.shape[1]]
        src = src + (dst[rk].mean(0) - src[rk].mean(0))
        a = cv2.GaussianBlur(mm.astype(np.float32), (0, 0), 1.0)
        a = np.maximum(a, m[oy:ey, ox:ex].astype(np.float32))[..., None]
        out[oy:ey, ox:ex] = dst * (1 - a) + src * a
        left &= ~m
    if fallback.any():
        out = cv2.inpaint(np.clip(out + 0.5, 0, 255).astype(np.uint8), fallback.astype(np.uint8), 5,
                          cv2.INPAINT_TELEA).astype(np.float32)
    _fill_ground.fallbackPx = int(fallback.sum())
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def carved_background(d: Path | None = None) -> Image.Image | None:
    """The native painting (RGB, 800 x 374) with the instances refilled (cached next to the manifest), or None."""
    dirs = houses_dirs(str(d) if d else None)
    if not dirs:
        return None
    if not _single_label_dir(dirs):
        return _carved_background_groups(dirs)
    d = dirs[0]
    man = manifest(d)
    lab = labels(d, man)
    bg = SC.background_rgb()
    key = hashlib.sha256(np.asarray(bg).tobytes() + lab.tobytes() + f"{CARVE_DILATE}/fill5".encode()).hexdigest()[:16]
    cache = d / f"carved_background_{key}.png"
    if cache.is_file():
        return Image.open(cache).convert("RGB")
    nat = np.asarray(bg)
    k = 2 * CARVE_DILATE + 1
    holes = []
    ids = [int(i) for i in np.unique(lab) if i > 0]
    for i in sorted(ids, key=lambda i: -np.nonzero(lab == i)[0].max()):     # front (lowest foot) first: open ground
                                                                              # below it; filled, it feeds the next
        mf = cv2.dilate((lab == i).astype(np.uint8), np.ones((k, k), np.uint8))[:TH, :TW]
        hn = cv2.resize(mf, (nat.shape[1], nat.shape[0]), interpolation=cv2.INTER_AREA) > 0
        holes.append(cv2.dilate(hn.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    sky = cv2.resize(T.sky_mask(np.asarray(bg.resize((TW, TH), Image.LANCZOS))).astype(np.uint8),
                     (nat.shape[1], nat.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    # building sprites overlay the painting only when built: the terrain under them is carved like any other
    out = _fill_ground(nat, holes, sky)
    print(f"carve: {len(holes)} instances refilled, inpaint fallback {_fill_ground.fallbackPx} native px", flush=True)
    Image.fromarray(out).save(cache)
    return Image.fromarray(out)


def _carved_background_groups(dirs: list) -> Image.Image:
    """carved_background for several groups or a silhouette carve: every group's instance holes, front (lowest foot)
    first, refilled from ground clear of every hole, the sky and the unclaimed props; cached in the first dir."""
    bg = SC.background_rgb()
    hs = group_holes(dirs)
    h = hashlib.sha256(np.asarray(bg).tobytes() + f"{CARVE_DILATE}/fill5/groups".encode())
    for _, m, _ in hs:
        h.update(np.packbits(m).tobytes())
    cache = dirs[0] / f"carved_background_{h.hexdigest()[:16]}.png"
    if cache.is_file():
        return Image.open(cache).convert("RGB")
    nat = np.asarray(bg)
    nsz = (nat.shape[1], nat.shape[0])
    holes = []
    avoid_f = np.zeros((H, W), bool)
    for _, m, foreign in sorted(hs, key=lambda t: -t[0]):
        hn = cv2.resize(m[:TH, :TW].astype(np.uint8), nsz, interpolation=cv2.INTER_AREA) > 0
        hn = cv2.dilate(hn.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        if foreign is not None:
            fn = cv2.resize(foreign[:TH, :TW].astype(np.uint8), nsz, interpolation=cv2.INTER_AREA) > 0
            hn &= ~fn                   # a native px holding any unclaimed prop px stays painted
            avoid_f |= foreign
        holes.append(hn)
    sky = cv2.resize(T.sky_mask(np.asarray(bg.resize((TW, TH), Image.LANCZOS))).astype(np.uint8), nsz,
                     interpolation=cv2.INTER_NEAREST) > 0
    if avoid_f.any():                   # never refill from a painted prop either
        sky |= cv2.resize(avoid_f[:TH, :TW].astype(np.uint8), nsz, interpolation=cv2.INTER_AREA) > 0
    out = _fill_ground(nat, [x for x in holes if x.any()], sky)
    print(f"carve: {len(holes)} instances ({len(dirs)} groups) refilled, inpaint fallback {_fill_ground.fallbackPx} "
          f"native px", flush=True)
    Image.fromarray(out).save(cache)
    return Image.fromarray(out)


def carve_depth(zs: np.ndarray) -> np.ndarray:
    """Frame depth with the instances' relief replaced by the surrounding ground (inverse depth, push-pull)."""
    m = carve_mask()
    if m is None:
        return zs
    inv = np.where(np.isfinite(zs), 1.0 / zs, np.nan)
    known = np.isfinite(inv) & ~m
    filled = T.push_pull(np.where(known, inv, 0.0).astype(np.float32), known)
    out = zs.copy()
    sel = m & np.isfinite(zs)
    out[sel] = 1.0 / np.maximum(filled[sel], 1e-6)
    gg = group_ground()
    lim = group_behind()
    if gg is not None:                  # never past the placed model's own ground (no pit under its footprint)
        cap, near = gg
        out[sel] = np.minimum(out[sel], cap[sel])
        if lim is not None:
            # where the model's ground lies in front of CARVE_BACK_M behind its far side at this px (the ground under
            # the house), the ground is the floor, not the far side; never nearer than CARVE_NEAR_TOL behind the
            # model's front surface there. At the base rows the floor meets the model's own front: refusing the cap
            # there instead pushed the ground behind the whole model and left the front base over the frame
            # extension 4.4 m lower (Castle longhouse 3, zs_v6 restage)
            under = np.isfinite(cap) & (cap < lim)
            lim = np.where(under, np.maximum(cap, near * (1 + CARVE_NEAR_TOL)), lim)
    if lim is not None:                 # never in front of the placed model it was carved for
        out[sel] = np.maximum(out[sel], lim[sel])
    return out


# ------------------------------------------------------------------------------------------------ model
def load_model(path: Path) -> dict:
    """The glb as a canonical cabin: local X = ridge (PCA of the top 5 % of vertices), Y up, base at y = 0, footprint
    centred, scaled so the ridge-axis extent is 1. Gable faces: |n . X| > 0.7 above the eaves."""
    import trimesh
    m = trimesh.load(str(path), force="mesh")
    V = np.asarray(m.vertices, np.float64)
    F = np.asarray(m.faces, np.int64)
    top = V[V[:, 1] > np.quantile(V[:, 1], 0.95)]
    xz = top[:, [0, 2]] - top[:, [0, 2]].mean(0)
    _, U = np.linalg.eigh(xz.T @ xz)
    r = U[:, -1]
    ang = math.atan2(r[1], r[0])            # ridge angle in the glb's XZ plane
    c, s = math.cos(-ang), math.sin(-ang)
    X = V[:, 0] * c - V[:, 2] * s
    Z = V[:, 0] * s + V[:, 2] * c
    L = np.stack([X, V[:, 1], Z], 1)
    L[:, 0] -= (L[:, 0].max() + L[:, 0].min()) / 2
    L[:, 2] -= (L[:, 2].max() + L[:, 2].min()) / 2
    L[:, 1] -= L[:, 1].min()
    k = 1.0 / (L[:, 0].max() - L[:, 0].min())
    L *= k
    tm = trimesh.Trimesh(L, F, process=False)
    fn = np.asarray(tm.face_normals)
    vn = np.asarray(tm.vertex_normals)
    cy = L[F][:, :, 1].mean(1)
    eave = np.quantile(L[:, 1], 0.55)
    gable = (np.abs(fn[:, 0]) > 0.7) & (cy > eave)
    rng = np.random.default_rng(0)
    hull_idx = rng.choice(len(L), min(900, len(L)), replace=False)
    return {"V": L, "F": F, "fn": fn, "vn": vn, "gable": gable, "hull": hull_idx,
            "extent": (L.max(0) - L.min(0)).round(3).tolist(), "tris": int(len(F)), "verts": int(len(L)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def rot_y(theta_deg: float) -> np.ndarray:
    t = math.radians(theta_deg)
    return np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])


def place(model: dict, inst: dict) -> np.ndarray:
    return np.asarray(inst["base"]) + inst["scale"] * (model["V"] @ rot_y(inst["yaw"]).T)


# ------------------------------------------------------------------------------------------------ fit
class Ground:
    """Local ground plane y = a x + b z + c fitted (robust LS) to the painted terrain around one instance's foot."""

    def __init__(self, P: np.ndarray, ring: np.ndarray):
        pts = P[ring].astype(np.float64)
        A = np.c_[pts[:, 0], pts[:, 2], np.ones(len(pts))]
        w = np.ones(len(pts))
        for _ in range(4):
            coef, *_ = np.linalg.lstsq(A * w[:, None], pts[:, 1] * w, rcond=None)
            r = pts[:, 1] - A @ coef
            s = 1.4826 * np.median(np.abs(r)) + 1e-3
            w = 1 / (1 + (r / (2 * s)) ** 2)
        self.coef = coef
        self.n = len(pts)

    def y(self, x, z):
        a, b, c = self.coef
        return a * x + b * z + c

    def cast(self, cam, u, v):
        r = T.rays(cam, np.array([u]), np.array([v]))[0]
        p = cam["pos"]
        a, b, c = self.coef
        # p + t r on y = a x + b z + c
        den = r[1] - a * r[0] - b * r[2]
        t = (a * p[0] + b * p[2] + c - p[1]) / den
        return p + t * r


class Fitter:
    def __init__(self, sc, model, lab, P, sky, paint_lum):
        self.cam, self.model, self.lab, self.P = sc.cam, model, lab, P
        self.sky, self.lum = sky, paint_lum
        self.prop = np.zeros(lab.shape, bool)   # fit() sets the manifest propMask
        self.F = model["F"]

    def setup(self, ids, occluders):
        """Crop, care region and ground for the instance(s) of label ids; occluders: labels in front of them."""
        m = np.isin(self.lab, ids)
        ys, xs = np.nonzero(m)
        pad = 30
        self.box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad + 1, W), min(ys.max() + pad + 1, H))
        x0, y0, x1, y1 = self.box
        self.M = m[y0:y1, x0:x1]
        dont = (np.isin(self.lab, occluders) | self.sky)[y0:y1, x0:x1] & ~self.M
        self.care = ~dont
        if getattr(self, "open_edges", False):
            # manifest openRectEdges: the painting has no pixels past its right / bottom frame edge, so a house the
            # frame cuts is not penalised for continuing there (it is fitted to its painted part only)
            yy, xx = np.mgrid[y0:y1, x0:x1]
            self.care &= (xx < TW) & (yy < TH)
        self.dark = np.clip((DARK_LUM - self.lum[y0:y1, x0:x1]) / DARK_LUM, 0, 1)
        k0 = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        cy = ys.mean()
        rows = np.arange(H)[:, None]
        # the ring grows until it holds RING_MIN ground px (a small ring squeezed between houses fits a plane that
        # can run parallel to the foot ray: #17 cast its base next to the camera)
        for kr in (13, 21, 31, 45, 61):
            k1 = cv2.dilate(m.astype(np.uint8), np.ones((kr, kr), np.uint8)) > 0
            ring = k1 & ~k0 & (rows > cy) & (self.lab == 0) & ~self.sky & ~self.prop
            if ring.sum() < RING_MIN:
                ring = k1 & ~k0 & (self.lab == 0) & ~self.sky & ~self.prop
            if ring.sum() >= RING_MIN:
                break
        self.ground = Ground(self.P, ring)
        self.foot = (float(xs.mean()), float(ys.max()))
        # fail closed: the foot pixel cast onto the plane must sit at the ring's own depth
        zr = np.median(T.project(self.cam, self.P[ring].astype(np.float64))[2])
        zf = T.project(self.cam, self.ground.cast(self.cam, *self.foot)[None])[2][0]
        if not (0.8 * zr <= zf <= 1.25 * zr):
            raise SystemExit(f"ground plane for labels {ids}: foot cast depth {zf:.1f} vs ring depth {zr:.1f} "
                             f"({int(ring.sum())} ring px)")
        self.fixed = None          # a fitted partner's silhouette (split pairs)

    def inst(self, yaw, s, u, v):
        base = self.ground.cast(self.cam, u, v)
        # sink the base to the lowest ground under the footprint corners (slopes: no floating corner)
        half = np.array([[.5, .5], [.5, -.5], [-.5, .5], [-.5, -.5]]) * s
        ez = self.model["extent"][2] / self.model["extent"][0]
        R = rot_y(yaw)
        cs = np.c_[half[:, 0], np.zeros(4), half[:, 1] * ez] @ R.T + base
        base = base.copy()
        base[1] = min(self.ground.y(cs[:, 0], cs[:, 2]).min(), base[1])
        return {"yaw": float(yaw % 360), "scale": float(s), "base": base.tolist(), "footPx": [float(u), float(v)]}

    def proj(self, Pw):
        px, py, zc = T.project(self.cam, Pw)
        return np.stack([px - self.box[0], py - self.box[1]], 1), zc

    def sil(self, inst, full):
        x0, y0, x1, y1 = self.box
        S = np.zeros((y1 - y0, x1 - x0), np.uint8)
        V = place(self.model, inst)
        if full:
            q, _ = self.proj(V)
            tri = np.round(q[self.F] * 4).astype(np.int32)
            cv2.fillPoly(S, list(tri), 1, lineType=cv2.LINE_8, shift=2)
        else:
            q, _ = self.proj(V[self.model["hull"]])
            hull = cv2.convexHull(np.round(q * 4).astype(np.int32))
            cv2.fillConvexPoly(S, hull, 1, lineType=cv2.LINE_8, shift=2)
        return S.astype(bool)

    def gable_dark(self, inst):
        V = place(self.model, inst)
        g = self.model["gable"]
        R = rot_y(inst["yaw"])
        n = self.model["fn"][g] @ R.T
        ctr = V[self.F[g]].mean(1)
        vis = ((self.cam["pos"] - ctr) * n).sum(-1) > 0
        if not vis.any():
            return 0.0
        q, _ = self.proj(V)
        x0, y0, x1, y1 = self.box
        G = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(G, list(np.round(q[self.F[g][vis]] * 4).astype(np.int32)), 1, shift=2)
        G = G.astype(bool) & self.care
        if G.sum() < 4:
            return 0.0
        return float(self.dark[G].mean() - self.dark[self.M].mean())

    def score(self, inst, full):
        S = self.sil(inst, full)
        if self.fixed is not None:
            S = S | self.fixed
        c = self.care
        inter = (S & self.M & c).sum()
        uni = ((S | self.M) & c).sum()
        iou = inter / max(uni, 1)
        return iou + (GABLE_W * self.gable_dark(inst) if full else 0.0)

    def fit(self, s_range, uv_box=None):
        x0, y0 = self.box[:2]
        if uv_box is None:
            ys, xs = np.nonzero(self.M)
            uv_box = (xs.min() + x0, ys.min() + y0, xs.max() + x0, ys.max() + y0)
        ux0, uy0, ux1, uy1 = uv_box
        us = np.linspace(ux0 + 0.2 * (ux1 - ux0), ux1 - 0.2 * (ux1 - ux0), 5)
        vs = np.linspace(uy0 + 0.55 * (uy1 - uy0), uy1, 4)
        ss = np.geomspace(s_range[0], s_range[1], 12)
        cand = []
        for yaw in np.arange(0, 180, 7.5):
            for s in ss:
                for u in us:
                    for v in vs:
                        cand.append((self.score(self.inst(yaw, s, u, v), False), yaw, s, u, v))
        cand.sort(key=lambda r: -r[0])
        seeds, seen = [], []
        for r in cand:
            if all(abs(((r[1] - y + 90) % 180) - 90) > 10 for y in seen):
                seeds.append(r)
                seen.append(r[1])
            if len(seeds) == 4:
                break
        from scipy.optimize import minimize
        best = None
        for _, yaw, s, u, v in seeds:
            for flip in (0.0, 180.0):
                x0v = np.array([yaw + flip, math.log(s), u, v])

                def f(x):
                    sc_ = math.exp(min(max(x[1], math.log(s_range[0])), math.log(s_range[1])))
                    return -self.score(self.inst(x[0], sc_, x[2], x[3]), True)
                simplex = np.vstack([x0v, x0v + np.diag([6.0, 0.08, 3.0, 2.0])])
                r = minimize(f, x0v, method="Nelder-Mead",
                             options={"initial_simplex": simplex, "xatol": 0.3, "fatol": 1e-4, "maxiter": 120})
                sc_ = math.exp(min(max(r.x[1], math.log(s_range[0])), math.log(s_range[1])))
                ins = self.inst(r.x[0], sc_, r.x[2], r.x[3])
                val = -r.fun
                if best is None or val > best[0]:
                    best = (val, ins)
        ins = best[1]
        S = self.sil(ins, True)
        c = self.care
        ins["iou"] = round(float(((S & self.M & c).sum()) / max(((S | self.M) & c).sum(), 1)), 3)
        ins["coverOfMask"] = round(float((S & self.M).sum() / max(self.M.sum(), 1)), 3)
        ins["gableDark"] = round(self.gable_dark(ins), 3)
        return ins


def fit(hd: Path, only: list | None = None, peers: list | None = None) -> dict:
    """only: refit just these labels and keep the other instances of the existing placement.json. peers: the other
    groups' dirs; their labels (offset past this group's) occlude like this group's own and are not ground."""
    import stronghold_full3d_scene as S
    t0 = time.time()
    man = manifest(hd)
    model = load_model(hd / man["model"])
    lab = labels(hd, man)
    own_ids = sorted(int(i) for i in np.unique(lab) if i > 0)
    for k, pd in enumerate(peers or []):
        pl_ = labels(pd, manifest(pd))
        lab = np.where((pl_ > 0) & (lab == 0), pl_ + 1000 * (k + 1), lab)
    sc = S.Scene()
    st = S.terrain_state(sc)
    P = st["baker"].P
    sky = st["fd"]["sky"]
    paint = np.zeros((H, W, 3), np.float32)
    paint[:TH, :TW] = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS)).astype(np.float32)
    lum = paint @ np.array([0.299, 0.587, 0.114], np.float32)
    lum[TH:, :] = 255
    lum[:, TW:] = 255
    fz = Fitter(sc, model, lab, P, sky, lum)
    fz.open_edges = bool(man.get("openRectEdges", False))
    # the ground ring takes no painted prop px either (manifest propMask): an unlabelled wall or chimney next to the
    # foot fitted the plane to its relief (Castle longhouse 4: base 7 m over the painted grass, depth 45 vs 74 m)
    fz.prop = np.load(hd / man["propMask"]).astype(bool) if man.get("propMask") else np.zeros((H, W), bool)
    ids = sorted(int(i) for i in np.unique(lab) if i > 0)
    foot_row = {i: np.nonzero(lab == i)[0].max() for i in ids}
    all_ids, ids = ids, own_ids
    split = set(man.get("split", []))
    s_lo, s_hi = man.get("scaleRangeM", [3.0, 18.0])
    s_split = man.get("splitScaleMaxM", 9.0)
    out = []
    keep = []
    if only:
        old = json.loads((hd / "placement.json").read_text(encoding="utf-8"))
        if old["modelSha256"] != model["sha256"]:
            raise SystemExit("placement.json was fitted to another model; refit all labels")
        keep = [x for x in old["instances"] if x["label"] not in only]
    for i in ids:
        if only and i not in only:
            continue
        occ = [j for j in all_ids if j != i and foot_row[j] > foot_row[i]]
        fz.setup([i], occ)
        if i not in split:
            ins = fz.fit((s_lo, s_hi))
            ins.update({"label": i, "part": 0})
            out.append(ins)
            print(i, {k: ins[k] for k in ("yaw", "scale", "iou", "coverOfMask", "gableDark")}, flush=True)
            continue
        # split: A alone under the cap, then B on the joint mask with A fixed, then A again with B fixed
        a = fz.fit((s_lo, s_split))
        fz.fixed = fz.sil(a, True)
        resid = fz.M & ~fz.fixed
        x0, y0 = fz.box[:2]
        ys, xs = np.nonzero(resid if resid.sum() > 30 else fz.M)
        b = fz.fit((s_lo, s_split), (xs.min() + x0, ys.min() + y0, xs.max() + x0, ys.max() + y0))
        fz.fixed = fz.sil(b, True)
        a = fz.fit((s_lo, s_split))
        fz.fixed = None
        both = fz.sil(a, True) | fz.sil(b, True)
        c = fz.care
        iou = float(((both & fz.M & c).sum()) / max(((both | fz.M) & c).sum(), 1))
        for part, ins in ((0, a), (1, b)):
            ins.update({"label": i, "part": part, "pairIou": round(iou, 3)})
            out.append(ins)
        print(i, "split", round(iou, 3), [(round(x["yaw"], 1), round(x["scale"], 2)) for x in (a, b)], flush=True)
    out = sorted(keep + out, key=lambda x: (x["label"], x["part"]))
    rep = {"schema": "town_full3d_houses_placement.v1", "model": man["model"], "modelSha256": model["sha256"],
           "modelLocalExtent": model["extent"], "modelTris": model["tris"], "labels": man["labels"],
           "instances": out, "seconds": round(time.time() - t0, 1),
           "iouMedian": round(float(np.median([x["iou"] for x in out])), 3)}
    (hd / "placement.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    write_silhouettes(hd, sc, model, out)
    foot = foot_check(hd, peers, sc, st)
    # foot slide: a fitted instance that floats with a consistent ratio (its whole edge over painted ground farther
    # than its base: the ground plane fitted around the foot runs above a hillside falling toward the camera; Stronghold
    # houses_v33 label 14, ratio 1.18 on 92 % of 49 edge px, the label box holding the whole painted hut) is scaled
    # about the rest camera by its median ratio: every rest px is kept (base and scale both x k) and its base meets
    # the painted ground under its edge. Only labels this fit refitted; a ratio over FOOT_SLIDE_MAX, or a scale out of
    # the manifest's range, is left failing (a label that cuts the painted house needs a new label, not a slide)
    slid = {}
    for k_ in foot["failing"]:
        r_ = foot["instances"][k_]
        k = float(r_.get("ratioP10P50P90", [0, 0, 0])[1])
        parts = [x for x in out if str(x["label"]) == k_ and (not only or x["label"] in only)]
        if not parts or not (1 + FOOT_TOL < k <= FOOT_SLIDE_MAX) or r_.get("buriedShare", 1) > 0.25 \
                or any(not (s_lo <= x["scale"] * k <= s_hi) for x in parts):
            continue
        c = np.asarray(sc.cam["pos"], np.float64)
        for x in parts:
            x["base"] = (c + (np.asarray(x["base"]) - c) * k).tolist()
            x["scale"] = float(x["scale"] * k)
            x["footSlide"] = round(k, 4)
        slid[k_] = round(k, 4)
    if slid:
        print("FOOT SLIDE", json.dumps(slid), flush=True)
        rep["footSlide"] = slid
        (hd / "placement.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        write_silhouettes(hd, sc, model, out)
        foot = foot_check(hd, peers, sc, st)
    viz(hd, sc, model, lab, out)
    rep["foot"] = {"ok": foot["ok"], "failing": foot["failing"]}
    if not foot["ok"]:
        bad = {k: foot["instances"][k] for k in foot["failing"]}
        raise SystemExit(f"fit: foot check fails for labels {foot['failing']} ({bad}); see {hd / 'foot_contact.json'}")
    return rep


def foot_contact(cam, P: np.ndarray, sky: np.ndarray, sils: list, occl: np.ndarray) -> dict:
    """The foot check: does each placed model stand on the painted ground it is drawn over?

    For every bottom-edge px of a placed silhouette (a covered px whose FOOT_ROW_PX px below are covered by no
    silhouette and no label of any group, in the painted rect, not sky), the painted terrain's camera depth there
    (P: frame world points of the fit's terrain) is compared with the depth where that px's rest ray meets the
    instance's base plane. Ratio > 1 + FOOT_TOL: the painted ground under the base edge lies behind it, so the model
    floats in front of what the painting shows it standing on. Measured on Castle carve_v1 (2026-10-01): longhouse 3
    and 4 at ratio 1.60 / 1.97, their hand label boxes cut through the painted lower wall, which stayed on the terrain
    while the model's base sat at the box bottom (user on zs_v5: houses float, meshes not lined up with their
    textures). Every other instance had ratio <= 1 + FOOT_TOL on >= 85 % of its edge px. A ratio < 1 (something
    nearer under the edge: another house, a wall in front) is recorded as buriedShare, not judged.
    sils: [(key, frame bool L, frame base y B)] (B: the base of the instance drawn at each covered px, so a split
    pair is judged per part); occl: frame bool, every group's silhouettes and labels.
    Vectorised numpy over the edge px only (a few hundred per instance; no raster or per-frame-px filter to port)."""
    clear = ~occl
    run = np.zeros((H, W), bool)
    run[:H - FOOT_ROW_PX] = True
    for k in range(1, FOOT_ROW_PX + 1):
        run[:H - FOOT_ROW_PX] &= clear[k:H - FOOT_ROW_PX + k]
    out = {}
    for key, L, B in sils:
        yy, xx = np.nonzero(L & run)
        y2 = yy + FOOT_ROW_PX
        keep = (y2 < TH) & (xx < TW) & ~sky[y2, xx] & np.isfinite(B[yy, xx])
        by = B[yy[keep], xx[keep]].astype(np.float64)
        xx, y2 = xx[keep], y2[keep]
        rec = {"edgePx": 0, "ok": True, "judged": False}
        if len(xx):
            Q = P[y2, xx].astype(np.float64)
            fin = np.isfinite(Q).all(1)
            zg = np.full(len(Q), np.nan)
            if fin.any():
                zg[fin] = T.project(cam, Q[fin])[2]
            r = T.rays(cam, xx + 0.5, y2 + 0.5)
            with np.errstate(divide="ignore", invalid="ignore"):
                tb = (by - cam["pos"][1]) / r[:, 1]
            ok = fin & np.isfinite(tb) & (tb > 0) & (r[:, 1] < 0)
            ratio = zg[ok] / tb[ok]
            n = int(ok.sum())
            rec["edgePx"] = n
            if n:
                rec.update({"floatShare": round(float((ratio > 1 + FOOT_TOL).mean()), 3),
                            "buriedShare": round(float((ratio < 1 - FOOT_TOL).mean()), 3),
                            "contactShare": round(float((np.abs(ratio - 1) <= FOOT_TOL).mean()), 3),
                            "ratioP10P50P90": [round(float(x), 3) for x in np.quantile(ratio, [.1, .5, .9])]})
            if n >= FOOT_MIN_PX:
                rec["judged"] = True
                rec["ok"] = rec["floatShare"] <= FOOT_FLOAT_MAX
        out[key] = rec
    return out


def foot_check(hd: Path, peers: list | None = None, sc=None, st=None, write: bool = True) -> dict:
    """Run foot_contact on hd's placement (its peer groups occlude) and record foot_contact.json, pinned to the
    placement.json of hd and of every peer. stage refuses a houses dir without a passing record for its group set."""
    import stronghold_full3d_scene as S
    sc = sc or S.Scene()
    st = st or S.terrain_state(sc)
    dirs = [hd] + [d for d in (peers or []) if d != hd]
    occl = np.zeros((H, W), bool)
    sils = []
    for d in dirs:
        man = manifest(d)
        occl |= labels(d, man) > 0
        L = silhouettes(d, man)
        for m in L.values():
            occl |= m
        if d == hd:
            for lab, (B, _, _) in rest_ground(d, man).items():
                sils.append((str(lab), L[lab], B))
    res = foot_contact(sc.cam, st["baker"].P, st["fd"]["sky"], sils, occl)

    def sha(d):
        return hashlib.sha256((d / "placement.json").read_bytes()).hexdigest()
    rep = {"schema": "town_full3d_houses_foot.v1", "placementSha256": sha(hd),
           "peers": {d.name: sha(d) for d in dirs[1:]},
           "spec": {"rowPx": FOOT_ROW_PX, "tol": FOOT_TOL, "floatMax": FOOT_FLOAT_MAX, "minPx": FOOT_MIN_PX},
           "instances": res, "ok": all(r["ok"] for r in res.values()),
           "failing": sorted(k for k, r in res.items() if not r["ok"])}
    if write:
        (hd / "foot_contact.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def require_foot(dirs: list) -> None:
    """stage: every group dir needs a passing foot_contact.json pinned to its own and its peers' current placement."""
    sha = {d.name: hashlib.sha256((d / "placement.json").read_bytes()).hexdigest() for d in dirs}
    for d in dirs:
        f = d / "foot_contact.json"
        if not f.exists():
            raise SystemExit(f"{d}: no foot_contact.json; run town_full3d_houses.py foot --houses {d} --peers <others>")
        r = json.loads(f.read_text(encoding="utf-8"))
        want = {k: v for k, v in sha.items() if k != d.name}
        if r.get("placementSha256") != sha[d.name] or r.get("peers") != want:
            raise SystemExit(f"{d}: foot_contact.json is not of the current placements of this group set; run foot")
        if not r.get("ok"):
            raise SystemExit(f"{d}: foot check fails for labels {r.get('failing')} (the painted ground under the "
                             f"base lies behind it: the label cuts the painted house, or the fit floats it)")


def write_silhouettes(hd: Path, sc, model, insts):
    """silhouettes.npz: per label, the frame px its placed model(s) cover at the rest pose (L<label>, the silhouette
    carve) and their farthest camera depth there (Z<label>, float32, inf uncovered: the carve's depth floor), and the depth where each covered px's rest ray meets the base plane of the
    instance drawn there: its base height (B<label>, float32 world y, nan uncovered: the carve's depth cap, rest_ground)
    and the nearest covering depth (N<label>, float32, inf uncovered)."""
    sil = {}
    base_y, near = {}, {}
    for ins in insts:
        px, py, zc = T.project(sc.cam, place(model, ins))
        q = np.stack([px, py], 1)
        qi = np.round(q[model["F"]] * 4).astype(np.int32)
        zk = f"Z{ins['label']}"
        Z = sil.get(zk, np.full((H, W), -np.inf, np.float32))
        Yb = base_y.setdefault(zk, np.full((H, W), np.nan, np.float64))
        N = near.setdefault(zk, np.full((H, W), np.inf, np.float32))
        tz = zc[model["F"]].max(1)
        tn = zc[model["F"]].min(1)
        for t in np.argsort(tz):        # near to far: the farthest covering triangle wins
            b0 = qi[t].min(0) >> 2
            b1 = (qi[t].max(0) >> 2) + 2
            x0, y0 = max(int(b0[0]), 0), max(int(b0[1]), 0)
            x1, y1 = min(int(b1[0]), W), min(int(b1[1]), H)
            if x1 <= x0 or y1 <= y0:
                continue
            bb = np.zeros((y1 - y0, x1 - x0), np.uint8)
            cv2.fillPoly(bb, [qi[t] - np.array([x0 * 4, y0 * 4], np.int32)], 1, shift=2)
            sub = Z[y0:y1, x0:x1]
            sub[bb > 0] = tz[t]
            Yb[y0:y1, x0:x1][bb > 0] = float(ins["base"][1])     # the base of the instance whose triangle won
            sn = N[y0:y1, x0:x1]
            sn[bb > 0] = np.minimum(sn[bb > 0], tn[t])
        sil[zk] = Z
    for zk in [k for k in sil if k.startswith("Z")]:
        # coverage from the per-triangle fill (one fillPoly over the overlapping triangle list fills even-odd)
        sil["L" + zk[1:]] = np.isfinite(sil[zk])
        sil[zk] = np.where(np.isfinite(sil[zk]), sil[zk], np.inf).astype(np.float32)
        sil["B" + zk[1:]] = base_y[zk].astype(np.float32)
        sil["N" + zk[1:]] = near[zk]
    sha = hashlib.sha256((hd / "placement.json").read_bytes()).hexdigest()
    np.savez_compressed(hd / "silhouettes.npz", placementSha256=np.array(sha), **sil)


def viz(hd: Path, sc, model, lab, insts):
    """placement_viz.png: the rest rect with each instance's fitted silhouette outline (colour per instance), its
    ridge line and label; placement_viz_zoom.png: the village band at x2."""
    paint = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS)).copy()
    img = (paint.astype(np.float32) * 0.6).astype(np.uint8)
    rng = np.random.default_rng(4)
    for ins in insts:
        col = tuple(int(c) for c in rng.integers(90, 255, 3))
        V = place(model, ins)
        px, py, _ = T.project(sc.cam, V)
        q = np.stack([px, py], 1)
        S = np.zeros((H, W), np.uint8)
        cv2.fillPoly(S, list(np.round(q[model["F"]] * 4).astype(np.int32)), 1, shift=2)
        cnt, _ = cv2.findContours(S[:TH, :TW], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(img, cnt, -1, col, 1)
        top = V[:, 1] > np.quantile(V[:, 1], 0.97)
        ridge = V[top]
        ax = rot_y(ins["yaw"]) @ np.array([1.0, 0, 0])
        t = ridge @ ax
        e = [ridge[np.argmin(t)], ridge[np.argmax(t)]]
        a, b = (T.project(sc.cam, p[None])[:2] for p in e)
        cv2.line(img, (int(a[0][0]), int(a[1][0])), (int(b[0][0]), int(b[1][0])), (255, 255, 0), 1)
        fx, fy = ins["footPx"]
        cv2.putText(img, f"{ins['label']}{'ab'[ins['part']] if ins['part'] or any(j['label'] == ins['label'] and j['part'] for j in insts) else ''}",
                    (int(fx) - 6, int(fy) + 12), cv2.FONT_HERSHEY_PLAIN, 0.8, col, 1)
    Image.fromarray(img).save(hd / "placement_viz.png")
    band = img[330:673]
    Image.fromarray(band).resize((band.shape[1] * 2, band.shape[0] * 2), Image.LANCZOS).save(hd / "placement_viz_zoom.png")


# ------------------------------------------------------------------------------------------------ stage
ID_VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos; in vec3 in_nrm; in float in_id;
flat out float v_id; out vec3 v_n;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); v_id = in_id; v_n = in_nrm; }
"""
ID_FS = """
#version 330
flat in float v_id; in vec3 v_n;
layout(location=0) out vec4 o_id; layout(location=1) out vec4 o_n;
void main(){ o_id = vec4(v_id, 0.0, 0.0, 1.0); o_n = vec4(normalize(v_n), 1.0); }
"""


def rest_buffers(sc, pieces, w, h):
    """Rest-camera triangle-id (float, -1 = none / occluder) and normal buffers at w x h. pieces: (P, n, tris, id0 or
    None for an occluder); triangle ids are id0 + index."""
    import moderngl
    import stronghold_full3d_preview as PV
    ctx = moderngl.create_standalone_context()
    prog = ctx.program(vertex_shader=ID_VS, fragment_shader=ID_FS)
    cid = ctx.texture((w, h), 4, dtype="f4")
    cn = ctx.texture((w, h), 4, dtype="f4")
    dep = ctx.depth_texture((w, h))
    fbo = ctx.framebuffer([cid, cn], dep)
    fbo.use()
    fbo.clear(-1.0, 0.0, 0.0, 0.0, depth=1.0)
    ctx.enable(moderngl.DEPTH_TEST)
    cam = sc.cam
    mvp = PV.perspective(cam["fov"], w / h, 2.0, T.DOME_R * 1.2) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
    prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
    for P, n, tris, id0 in pieces:
        tri = np.asarray(tris, np.int64)
        v = np.asarray(P, np.float32)[tri.ravel()]
        nn = np.asarray(n, np.float32)[tri.ravel()]
        ids = np.repeat(np.arange(len(tri)) + (id0 if id0 is not None else 0), 3).astype(np.float32)
        if id0 is None:
            ids[:] = -1.0
        vb = np.concatenate([v, nn, ids[:, None]], 1).astype(np.float32)
        vbo = ctx.buffer(vb.tobytes())
        vao = ctx.vertex_array(prog, [(vbo, "3f 3f 1f", "in_pos", "in_nrm", "in_id")])
        vao.render()
    a = np.frombuffer(cid.read(), np.float32).reshape(h, w, 4)[::-1, :, 0].copy()
    nb = np.frombuffer(cn.read(), np.float32).reshape(h, w, 4)[::-1, :, :3].copy()
    ctx.release()
    return a, nb


def pack(sizes, width=4096):
    """Shelf packing: [(w, h)] -> [(x, y)], atlas (W, H) (H a multiple of 16)."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    pos = [None] * len(sizes)
    x = y = shelf = 0
    for i in order:
        w, h = sizes[i]
        if x + w > width:
            x, y, shelf = 0, y + shelf, 0
        pos[i] = (x, y)
        x += w
        shelf = max(shelf, h)
    return pos, (width, -(-(y + shelf) // 16) * 16)


def stage(hd) -> dict:
    """hd: one houses dir, or a list of group dirs (one model each) staged together into Mesh_Houses."""
    import conflux_full3d_env as E
    import stronghold_full3d_ground as G
    import stronghold_full3d_scene as S
    import stronghold_full3d_solids as SL
    t0 = time.time()
    dirs = list(hd) if isinstance(hd, (list, tuple)) else [hd]
    require_foot(dirs)
    groups = []
    for d in dirs:
        man_ = manifest(d)
        pl_ = json.loads((d / "placement.json").read_text(encoding="utf-8"))
        model_ = load_model(d / man_["model"])
        if model_["sha256"] != pl_["modelSha256"]:
            raise SystemExit(f"{d}: placement.json was fitted to another model; run fit again")
        groups.append((d, man_, pl_, model_))
    man, model = groups[0][1], groups[0][3]
    sc = S.Scene()
    insts = [ins for g in groups for ins in g[2]["instances"]]
    Mi = [g[3] for g in groups for _ in g[2]["instances"]]          # each instance's model
    gi = [k for k, g in enumerate(groups) for _ in g[2]["instances"]]
    nTi = [len(m["F"]) for m in Mi]
    off = np.concatenate([[0], np.cumsum(nTi)]).astype(np.int64)    # triangle id offset per instance
    # world geometry per instance
    Pw = [place(Mi[i], ins) for i, ins in enumerate(insts)]
    Nw = [Mi[i]["vn"] @ rot_y(ins["yaw"]).T for i, ins in enumerate(insts)]
    Fn = [Mi[i]["fn"] @ rot_y(ins["yaw"]).T for i, ins in enumerate(insts)]
    # rest buffers at TEX_K x: which triangle owns each texel, and its interpolated normal
    k = TEX_K
    # only the instances occlude each other: the building solids cover the painted houses only when built, and the
    # painting under them still shows the houses, so they must not decide which triangles take the projection
    pieces = [(Pw[i], Nw[i], Mi[i]["F"], int(off[i])) for i in range(len(insts))]
    idb, nb = rest_buffers(sc, pieces, W * k, H * k)
    own = np.round(idb).astype(np.int64)
    # per triangle: rest-pose pixel count (own) vs projected area; facing
    counts = np.bincount(own[own >= 0].ravel(), minlength=int(off[-1]))
    paint_big = np.asarray(SC.background_rgb().resize((TW * k, TH * k), Image.LANCZOS)).astype(np.float32) / 255
    # buffers padded by TILE_PAD frame px on every side, so a tile covers an instance whose projection (or mirrored
    # projection) leaves the painted rect; outside the rect nothing is "front" and the back fill supplies the texels
    pk = TILE_PAD * k
    paint_lin = np.pad(G.SC_srgb_to_lin(paint_big), ((pk, pk), (pk, pk), (0, 0)), mode="edge")
    in_rect = np.pad(np.ones((TH * k, TW * k), bool), pk)
    own = np.pad(own[:TH * k, :TW * k], pk, constant_values=-1)
    nb = np.pad(nb[:TH * k, :TW * k], ((pk, pk), (pk, pk), (0, 0)))
    rig, sun = sc.rig, sc.sun
    tiles, UVs, tri_all, P_all, N_all = [], [], [], [], []
    rep_inst = []
    for i, ins in enumerate(insts):
        V, Nv, F = Pw[i], Nw[i], Mi[i]["F"]
        o0, nT = int(off[i]), nTi[i]
        px, py, zc = T.project(sc.cam, V)
        q = np.stack([px, py], 1)
        tri_q = q[F]
        area = 0.5 * np.abs((tri_q[:, 1, 0] - tri_q[:, 0, 0]) * (tri_q[:, 2, 1] - tri_q[:, 0, 1])
                            - (tri_q[:, 1, 1] - tri_q[:, 0, 1]) * (tri_q[:, 2, 0] - tri_q[:, 0, 0])) * k * k
        ctr = V[F].mean(1)
        view = sc.cam["pos"] - ctr
        view /= np.linalg.norm(view, axis=-1, keepdims=True)
        facing = (Fn[i] * view).sum(-1)
        vis = counts[o0:o0 + nT] / np.maximum(area, 1e-6)
        inside = (tri_q[:, :, 0].max(1) < TW) & (tri_q[:, :, 1].max(1) < TH) & (tri_q.min((1, 2)) >= 0)
        front = (facing >= FACING_MIN) & (vis >= VISIBLE_MIN) & inside
        # mirrored positions: 180 deg about the instance's vertical axis through its base
        base = np.asarray(ins["base"])
        Vm = (V - base) @ rot_y(180).T + base
        mx, my, _ = T.project(sc.cam, Vm)
        # tile box: the instance's projection (front) with a margin, in frame px, clipped to the rect
        allx = np.r_[px, mx]
        ally = np.r_[py, my]
        bx0, by0 = int(math.floor(allx.min())) - 3, int(math.floor(ally.min())) - 3
        bx1, by1 = int(math.ceil(allx.max())) + 4, int(math.ceil(ally.max())) + 4
        if bx0 < -TILE_PAD or by0 < -TILE_PAD or bx1 > TW + TILE_PAD or by1 > TH + TILE_PAD:
            raise SystemExit(f"instance {ins['label']}/{ins['part']}: tile box {(bx0, by0, bx1, by1)} leaves the "
                             f"rect + TILE_PAD {TILE_PAD}")
        tw_, th_ = (bx1 - bx0) * k, (by1 - by0) * k
        sl = (slice((by0 + TILE_PAD) * k, (by1 + TILE_PAD) * k), slice((bx0 + TILE_PAD) * k, (bx1 + TILE_PAD) * k))
        crop = paint_lin[sl]
        idc = own[sl]
        nc = nb[sl]
        mine = (idc >= o0) & (idc < o0 + nT) & in_rect[sl]
        mine_front = mine & front[np.clip(idc - o0, 0, nT - 1)]
        Lr = E.light(nc / (np.linalg.norm(nc, axis=-1, keepdims=True) + 1e-9), rig, sun)
        # de-light with a bounded gain: where the rig leaves a painted-lit wall in shadow, painting / irradiance would
        # blow out (P10 irradiance 0.01 on some walls); the floor is LIGHT_FLOOR x the instance's median irradiance
        lm = Lr.mean(-1)
        ref = lm[mine_front] if mine_front.any() else lm[mine] if mine.any() else lm.ravel()
        floor = LIGHT_FLOOR * float(np.median(ref))
        alb = np.clip(crop / np.maximum(Lr, floor), 0, 1).astype(np.float32)
        # front tile: de-lit painting where this instance's front triangles own the texel, pushed out elsewhere
        ftile = SL.back_fill(alb, mine_front, erode_tx=0) if mine_front.any() else alb
        ftile[mine_front] = alb[mine_front]
        # back tile: the solid lane's back fill of the same (contrast / luminance capped, edge band replaced)
        src_mask = mine_front if mine_front.sum() > 16 else mine
        bsrc = SL.back_fill(alb, src_mask)
        med = np.median(alb[src_mask], 0) if src_mask.any() else np.full(3, 0.3, np.float32)
        bc = med + (bsrc - med) * SL.BACK_FILL_CONTRAST
        lum = alb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        blum = bc @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        cap = float(np.quantile(lum[src_mask], SL.BACK_FILL_LUM_Q)) if src_mask.any() else 1.0
        btile = (bc * (np.minimum(blum, cap) / np.maximum(blum, 1e-6))[..., None] * SL.BACK_FILL_DARKEN).astype(np.float32)
        tiles.append((ftile, btile, (bx0, by0)))
        # per-triangle-corner uv (unwelded where a vertex is shared by front and back triangles)
        fu = (px - bx0) * k / tw_, (py - by0) * k / th_
        bu = (mx - bx0) * k / tw_, (my - by0) * k / th_
        UVs.append((np.stack(fu, 1), np.stack(bu, 1), front))
        rep_inst.append({**({"group": groups[gi[i]][0].name} if len(groups) > 1 else {}),
                         "label": ins["label"], "part": ins["part"], "frontTris": int(front.sum()),
                         "backTris": int((~front).sum()), "tilePx": [tw_, th_],
                         "irradianceP10P50": [round(float(x), 3) for x in np.quantile(Lr[mine_front].mean(-1), [.1, .5])]
                         if mine_front.any() else None,
                         "clippedShare": round(float((alb[mine_front] >= 0.999).any(-1).mean()), 4)
                         if mine_front.any() else None})
    sizes = []
    for ftile, btile, _ in tiles:
        sizes += [(ftile.shape[1] + 4, ftile.shape[0] + 4), (btile.shape[1] + 4, btile.shape[0] + 4)]
    pos, (AW, AH) = pack(sizes)
    atlas = np.zeros((AH, AW, 3), np.float32)
    for j, (ftile, btile, _) in enumerate(tiles):
        for t, img in enumerate((ftile, btile)):
            x, y = pos[2 * j + t]
            atlas[y:y + img.shape[0] + 4, x:x + img.shape[1] + 4] = np.pad(img, ((2, 2), (2, 2), (0, 0)), mode="edge")
    off = 0
    uv_all = []
    for j, (ftile, btile, _) in enumerate(tiles):
        V, Nv, F = Pw[j], Nw[j], Mi[j]["F"]
        fuv, buv, front = UVs[j]
        # unweld: front triangles use the front corner set, back triangles the back one
        for t, (sel, uvs, img) in enumerate(((front, fuv, ftile), (~front, buv, btile))):
            if not sel.any():
                continue
            x, y = pos[2 * j + t]
            used = np.unique(F[sel])
            remap = np.full(len(V), -1)
            remap[used] = np.arange(len(used))
            u = (x + 2 + uvs[used, 0] * img.shape[1]) / AW
            v = 1 - (y + 2 + uvs[used, 1] * img.shape[0]) / AH
            P_all.append(V[used])
            N_all.append(Nv[used])
            uv_all.append(np.stack([u, v], 1))
            tri_all.append(remap[F[sel]] + off)
            off += len(used)
    P = np.concatenate(P_all)
    uv = np.concatenate(uv_all)
    n = np.concatenate(N_all)
    tris = np.concatenate(tri_all)
    env = S.PREFIX + "environment"
    row = sc.add_bin(env, "Mesh_Houses", P, n, uv, tris, atlas, extra={"mipBias": S.TERRAIN_MIP_BIAS,
                                                                        "aniso": S.TERRAIN_ANISO})
    S.save_rows(sc)
    S.write_catalog(sc, carry="previous", drop=("houses",))
    cat_p = S.OUT / "catalog.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    if len(groups) == 1:
        gcat = {"model": man["model"], "modelSha256": model["sha256"], "modelTris": model["tris"],
                "meshy": man.get("meshy", {}), "meshyCredits": int(man.get("meshy", {}).get("credits", 0))}
    else:
        gcat = {"groups": [{"dir": g[0].name, "model": g[1]["model"], "modelSha256": g[3]["sha256"],
                            "modelTris": g[3]["tris"], "instances": len(g[2]["instances"]),
                            "carve": g[1].get("carve", "label"), "meshy": g[1].get("meshy", {})} for g in groups],
                "meshyCredits": sum(int(g[1].get("meshy", {}).get("credits", 0)) for g in groups)}
    cat["houses"] = {"piece": "Mesh_Houses", "instances": len(insts),
                     "labels": len({(gi[i], x["label"]) for i, x in enumerate(insts)}),
                     **gcat,
                     "texelsPerPx": TEX_K, "atlas": [AW, AH],
                     "texture": "rest-camera projection of the painting (de-lit) on the triangles the rest pose sees; "
                                "mirrored back fill elsewhere",
                     "terrainCarve": {"dilatePx": CARVE_DILATE, "albedo": "ground refill", "depth": "push-pull"},
                     "proofTier": "generated artifact (offline previews; bundle / in-game unproven)"}
    cat_p.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    rep = {"instances": rep_inst, "atlas": [AW, AH], "tris": int(len(tris)), "verts": int(len(P)),
           "seconds": round(time.time() - t0, 1), "row": row}
    (S.WORK / "houses_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    # props re-check: the props were placed against the previous houses (hidden behind them at rest); a moved house
    # can expose one (Castle zs_v6 2026-10-01: refitted longhouse 3 left shrub 0 in front of its wall, 2555 px at
    # rest). town_t2_props.check measures every build state; fail closed until the prop is re-placed or dropped.
    import town_t2_props as PR
    if (PR.PROPS_DIR / "placement.json").is_file():
        if PR.check():
            raise SystemExit(f"houses stage: the props check fails on the restaged houses ({PR.PROPS_DIR / 'check.json'}"
                             "): re-place the flagged props (town_t2_props.py replace --ids ...) or drop them, then "
                             "re-run the check")
        rep["propsCheck"] = "pass"
        (S.WORK / "houses_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "carve", "silhouettes", "foot"])
    ap.add_argument("--dry-run", action="store_true", help="foot: report only, write no foot_contact.json")
    ap.add_argument("--faction", default=SC.FACTION)
    ap.add_argument("--houses", default="")
    ap.add_argument("--labels", default="", help="fit: refit only these labels (comma list), keep the rest")
    ap.add_argument("--peers", default="", help="fit: the other groups' dirs (os.pathsep list)")
    a = ap.parse_args()
    if a.cmd == "stage":
        dirs = houses_dirs(os.environ.get("TOWN_FULL3D_HOUSES", ""))
        if not dirs:
            raise SystemExit("stage: set TOWN_FULL3D_HOUSES (the terrain must be carved by the same houses dirs)")
        if a.houses and [str(x) for x in houses_dirs(a.houses)] != [str(x) for x in dirs]:
            raise SystemExit("stage: --houses differs from TOWN_FULL3D_HOUSES (the terrain is carved by the latter)")
        print(json.dumps({k: v for k, v in stage(dirs if len(dirs) > 1 else dirs[0]).items() if k != "instances"},
                         indent=1))
        return 0
    hd = houses_dir(a.houses)
    if hd is None:
        raise SystemExit("--houses <dir> or TOWN_FULL3D_HOUSES")
    if a.cmd == "fit":
        rep = fit(hd, [int(x) for x in a.labels.split(",") if x.strip()] or None, houses_dirs(a.peers) or None)
        print(json.dumps({k: v for k, v in rep.items() if k != "instances"}, indent=1))
    elif a.cmd == "foot":
        rep = foot_check(hd, houses_dirs(a.peers) or None, write=not a.dry_run)
        print(json.dumps(rep, indent=1))
        return 0 if rep["ok"] else 1
    elif a.cmd == "carve":
        img = carved_background(hd)
        print(img.size)
    elif a.cmd == "silhouettes":
        import stronghold_full3d_scene as S
        man = manifest(hd)
        rep = json.loads((hd / "placement.json").read_text(encoding="utf-8"))
        write_silhouettes(hd, S.Scene(), load_model(hd / man["model"]), rep["instances"])
        print(json.dumps({"silhouettes": str(hd / "silhouettes.npz"), "instances": len(rep["instances"])}))
    else:
        if not os.environ.get("TOWN_FULL3D_HOUSES"):
            raise SystemExit("stage: set TOWN_FULL3D_HOUSES (the terrain must be carved by the same houses dir)")
        print(json.dumps({k: v for k, v in stage(hd).items() if k != "instances"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
