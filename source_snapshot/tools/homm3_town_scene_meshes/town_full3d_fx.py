"""Full-3D town lane: animated HoMM3 buildings as vanilla-style effects, for any faction (profile-classified).

A faction selects this module with `FX_MODULE = "town_full3d_fx"` and classifies EVERY reachable animated layer (HoMM3
DEF with more than one frame in layers/anims/metadata.json) in its profile:

    FX_LAYERS = {
        "<layerId>": {
            "moves": "what the DEF animates, in words (lands in catalog.animationAudit)",
            "effects": [
                {"kind": "flame" | "glints" | "glow" | "lightning" | "smoke" | "spin" | "swing" | "track" | "water" |
                         "wheel",
                 "rects": [[x0, y0, x1, y1], ...],     # optional: native DEF px; default = the whole DEF
                 "exclude": [[x0, y0, x1, y1], ...],   # optional
                 "minPx": 6,                           # optional: smallest changed component kept (flame / glints)
                 "flowDir": [dx, dy],                  # optional, water only: screen flow direction (y down)
                 "colour": {"hue": [lo, hi], "minS": s, "minV": v},  # optional: keep moving px whose brightest
                                                       # frame colour is in this HSV range (hue deg; lo > hi wraps)
                 "colourNot": {...},                   # optional: drop moving px in this HSV range (same form)
                 "floatZm": 160.0,                     # optional: forward depth (painting m) of a float piece
                 "why": "optional note"},
                ...
            ],
        },
        ...
    }

DEF registration: a DEF can be larger than the layer sprite it animates (a crosswalked DEF whose frames carry sky above
the building, or a wider box). The profile then states where the sprite's origin sits inside the DEF,

    ANIM_OFFSETS = {"<defId>": [dx, dy]}     # sprite px = DEF px - (dx, dy)

and ANIM_CROSSWALK stays str -> str (the map validate_town_scene3d_contract.resolve_anim_crosswalk reads). An animated
layer whose DEF box differs from its sprite box without an ANIM_OFFSETS row FAILS the stage, as does an offset row for a
DEF that animates no layer. All masks and profile rects are DEF px; placement converts to sprite px.

Placement: a piece whose DEF pixels all lie at or below the sprite's top row is placed on the layer's own relief (the
depth under its centre). A piece with any pixel above the sprite's top row (a storm cloud or a bolt over the roof: no
relief under it) is a FLOAT piece instead: camera-facing, at the depth of the building directly below it (the median
relief depth of the top opaque sprite px in each of the piece's columns), or at the effect's "floatZm" when the profile
sets one (as Castle's RELIEF_TUNE floatZm hangs the Portal of Glory's cloud). Water cannot float and fails closed there.
catalog.animationAudit[lid].placements and the stage report record which placement each piece got.

An animated reachable layer the profile does not classify, an unknown kind, or a kind whose measured mask is empty
FAILS the stage (SystemExit); there is no default effect. The same holds for a classified layer that is not animated.

The DEF is read only to MEASURE (never played as a flipbook, docs/homm3_stronghold_full_3d_town.md section 7):
the changed mask is the union over frames 1.. of the pixels whose colour differs from frame 0 by more than CHANGE_THR
(frames 1.. are patches over frame 0). Every kind takes its place, extent and colour from that mask, and its timing
from the DEF's own frame count and rate:

  * flame   one emitter per connected component of the mask (a torch, a candle, a window fire): a camera-facing
            VfxUber particle masked by the component's own pixels, noise scrolling upward, tinted with the measured
            bright colour, plus a soft glow flicker in that colour (the Stronghold lightning recipe, warm and upward).
  * glints  sparkle points (vanilla Paragon glow) spawned inside each component's box at the measured sparkle colour;
            size = the median extent of the per-frame sparkles (2+ px), life = the mean frames a pixel stays changed,
            rate = sparkles visible per frame / life, shared over the components by pixel count.
  * glow    the region breathes: a VfxUber particle masked by the time-averaged change, slowly scrolling noise in the
            measured colour, cross-faded over the DEF's own loop period.
  * smoke   puffs rising from the lowest rows of the mask to its top over the DEF's loop period (rise speed = measured
            plume height / period), start width = the plume's base width, end width = its top width, measured colour.
  * water   a FlowWater surface (vanilla WaterNormal, the Stronghold basin recipe) over each component of the mask,
            closed over 3 px (holes such as lily pads kept), on the layer's own relief pulled toward the camera; tint = the measured median
            water colour, flow and ripple scale from the component's size in metres; optional "flowDir" [dx, dy]
            (screen, y down) turns the flow (a waterfall is [0, 1]).
  * lightning  one flash per component of the mask (a bolt, an arc): the Stronghold lightning recipe (VfxUber bolt
            masked by the fraction of frames each px is lit, a glow flicker, a spray of sparks) in the measured bright
            colour; flash life = the mean frames a bolt px stays lit x the DEF frame time.
  * spin    a rotating disc (sails, wheels): fit_spin measures it on the DEF's own frames (frames 1.. composited over
            frame 0): hub = the change-weighted centroid of the moving px, radius = their p99 distance, per-frame step =
            the rotation about the hub that best correlates frame k with frame k+1 (|step| < SPIN_MAX_DEG). Those
            short steps are biased toward 0 (a few degrees on thin blades), so the speed is then tracked on the long
            baseline: frame 0 rotated onto every frame k, searched round the previous angle + the median step, slope
            through the origin (unbiased on synthetic rotors to 0.03 deg / frame, test_town_full3d_fx_spin.py); it
            gives sense and speed with the DEF's own frame time (read by DEF id, so a crosswalked DEF is timed by its
            own row). Fails closed when fewer than SPIN_AGREE_MIN of the steps agree with the median
            (the part does not rotate rigidly about one hub: a crank, a swing, a disc seen edge-on). The disc itself
            is stronghold_full3d_fx.windmill with that measurement; the static texture gets the composited frames'
            median in the rect.
  * swing   a pendulum (a bob swinging to and fro about a pivot above it; needs one explicit rect): fit_swing measures
            it on the composited DEF frames. The bob = px inside the effect's "colour" range (required: the frames'
            median is no background where a slow bob dwells) that change over the frames; per frame it is tracked by translating a bob template built from every frame, scored
            so that template px over never-changing px cost nothing (a beam in front hides the bob there). The
            horizontal track is fitted by a sinusoid with a whole number of swings per DEF loop (amplitude, phase,
            period = loop time / swings); the pivot sits on the vertical through the swing's centre, at the length L
            whose circular arc best fits the vertical track (the bob rises at both ends). Fails closed when the
            horizontal track is no sinusoid (SWING_X_RMS_MAX_PX), when the arc's rise is below SWING_RISE_MIN_PX or L
            reaches its search bound (a translation, not a swing), or when a px shows the bob in every frame (no plate
            under it). The bob is an unlit card at the pivot turning A sin(2 pi t / period + phase) about the view axis
            (catalog row swingPeriod / swingAmpDeg / swingPhaseDeg, and swingZeroDeg = the texture's own pose);
            the never-changing px its path crosses are a static card just in front (Fx_SwingFront_*), so a beam the
            DEF draws across the bob stays in front. The static texture gets, inside the rect, each px's median over
            the frames that do not show the bob there. The fit report carries the length band (L values whose arc rms
            is within 0.1 px of the best): a small rise measures the pivot height loosely, and the band says how
            loosely.
  * wheel, track  measured mechanical parts (a disc turning about a hub that may be hidden and may be seen at a
            slant; a rigid part riding a path and back with keyed poses): town_full3d_mech.py measures and emits them, and each fails closed unless its model
            redraws the DEF frames clearly better than the static plate (town_full3d_mech.MECH_GAIN_MAX).

Materials, noise and glow textures are the ones the Stronghold effects use (stronghold_full3d_fx.Mats: VfxUber /
FlowWater replicas, vanilla Olden Era noise/glow from the faction's vanilla/vfx extract, provenance in the catalog).
Stronghold keeps its own module (stronghold_full3d_fx); nothing here is on its path.
Proof tier: generated artifact; motion is only seen in editor renders / in game.
"""
from __future__ import annotations

import json
import math

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

import stronghold_full3d_common as SC
import stronghold_full3d_fx as SF
import town_full3d_mech as MECH

CHANGE_THR = 30          # max |RGB| step from frame 0 that counts as a moving pixel (8-bit)
KINDS = ("flame", "glints", "glow", "lightning", "smoke", "spin", "swing", "track", "water", "wheel")
SPIN_MAX_DEG = 45.0      # |rotation step| searched per frame (screen deg)
SPIN_RES_DEG = 0.25      # search resolution
SPIN_AGREE_DEG = 1.0     # a frame step agrees when within this of the median step
SPIN_AGREE_MIN = 0.6     # share of frame steps that must agree, else the part is not a rigid rotor (fail closed)
SPIN_MOVE_STD = 12.0     # grey std over frames that counts as a moving rotor px
SWING_MIN_PX = 8          # bob px a frame must show (after the colour selection)
SWING_SHIFT_MAX_PX = 24   # |bob translation| searched from the reference frame
SWING_X_RMS_MAX_PX = 0.75  # the horizontal track about its whole-swings-per-loop sinusoid
SWING_Y_RMS_MAX_PX = 0.75  # the vertical track about the arc
SWING_MIN_AMP_PX = 1.5    # half the horizontal travel
SWING_RISE_MIN_PX = 0.5   # the arc's rise at the ends of the swing; below it the pivot height is not measured
SWING_FRONT_PULL_M = 0.15  # the occluder card sits this much further in front than the bob card


# ------------------------------------------------------------------------------------------------ profile
def fx_layers() -> dict:
    spec = getattr(SC.FP, "FX_LAYERS", None)
    if not isinstance(spec, dict):
        raise SystemExit(f"town_full3d_fx: profile {SC.FACTION} sets FX_MODULE town_full3d_fx but no FX_LAYERS dict")
    return spec


def layer_meta(meta: dict) -> dict:
    """layers/anims/metadata.json keyed by catalog layer id: the profile's ANIM_CROSSWALK (DEF id -> layer id, the
    same map validate_town_scene3d_contract.resolve_anim_crosswalk applies) moves a DEF onto the layer it animates;
    each row keeps its DEF folder as "defId". Fails closed on a key that is no DEF id or is itself a layer id, and on a
    layer that two DEFs claim with different frame counts."""
    cw = getattr(SC.FP, "ANIM_CROSSWALK", {}) or {}
    lays = set(SC.layers())
    out = {k: {**v, "defId": k} for k, v in meta.items()}
    for d, lid in cw.items():
        if d not in meta:
            raise SystemExit(f"town_full3d_fx: ANIM_CROSSWALK key {d} is not a DEF id of layers/anims/metadata.json")
        if d in lays:
            raise SystemExit(f"town_full3d_fx: ANIM_CROSSWALK key {d} is itself a layer id")
        if lid in out and out[lid]["defId"] != d and len(out[lid].get("frames") or []) != len(meta[d].get("frames") or []):
            raise SystemExit(f"town_full3d_fx: {lid} is claimed by DEFs {out[lid]['defId']} and {d} with different "
                             f"frame counts")
        out[lid] = {**meta[d], "defId": d}
    offs = getattr(SC.FP, "ANIM_OFFSETS", {}) or {}
    if not isinstance(offs, dict):
        raise SystemExit(f"town_full3d_fx: profile {SC.FACTION} ANIM_OFFSETS is not a dict")
    used = {r["defId"] for lid, r in out.items() if lid in lays}
    for d, o in offs.items():
        if d not in used:
            raise SystemExit(f"town_full3d_fx: ANIM_OFFSETS key {d} is not a DEF id that animates a layer")
        if not (isinstance(o, (list, tuple)) and len(o) == 2 and all(isinstance(v, int) for v in o)):
            raise SystemExit(f"town_full3d_fx: ANIM_OFFSETS[{d}] must be [dx, dy] integer px, got {o!r}")
    for r in out.values():
        r["defOffset"] = [int(v) for v in offs.get(r["defId"], (0, 0))]
        r["defOffsetStated"] = r["defId"] in offs
    return out


def check_registration(lmeta: dict, lid: str, L: dict, F: list[np.ndarray]) -> tuple[int, int]:
    """(dx, dy): the sprite origin in DEF px. Fails closed when the DEF box differs from the sprite box and the profile
    states no ANIM_OFFSETS row for the DEF."""
    row = lmeta[lid]
    dh, dw = F[0].shape[:2]
    sw, sh = SC.sprite(L).size
    if (dw, dh) != (sw, sh) and not row["defOffsetStated"]:
        raise SystemExit(f"town_full3d_fx: {lid}: DEF {row['defId']} is {dw}x{dh} px but the sprite is {sw}x{sh}: the "
                         f"profile needs ANIM_OFFSETS[{row['defId']!r}] = [dx, dy] (the sprite origin in DEF px)")
    return int(row["defOffset"][0]), int(row["defOffset"][1])


def def_frames(lmeta: dict, lid: str) -> list[np.ndarray]:
    """The DEF frames that animate layer lid (its own DEF, or the crosswalked one)."""
    row = lmeta[lid]
    return [np.asarray(Image.open(SF.ANIMS / row["defId"] / f).convert("RGBA")) for f in row["frames"]]


def classify(reachable: list[str], meta: dict, spec: dict) -> dict:
    """{lid: (nframes, row)} for every reachable animated layer. Fails closed on any unclassified / stray / bad row."""
    animated = {lid: len(meta.get(lid, {}).get("frames") or []) for lid in reachable}
    animated = {k: v for k, v in animated.items() if v > 1}
    missing = sorted(set(animated) - set(spec))
    if missing:
        raise SystemExit(f"town_full3d_fx: animated layers without an FX_LAYERS classification: {missing}")
    stray = sorted(set(spec) - set(animated))
    if stray:
        raise SystemExit(f"town_full3d_fx: FX_LAYERS rows for layers that are not reachable animated layers: {stray}")
    out = {}
    for lid in sorted(animated):
        row = spec[lid]
        if not str(row.get("moves") or "").strip():
            raise SystemExit(f"town_full3d_fx: {lid}: FX_LAYERS row lacks 'moves'")
        eff = row.get("effects")
        if not isinstance(eff, list) or not eff:
            raise SystemExit(f"town_full3d_fx: {lid}: FX_LAYERS row names no effects")
        for e in eff:
            if e.get("kind") not in KINDS:
                raise SystemExit(f"town_full3d_fx: {lid}: unknown effect kind {e.get('kind')!r} (known {KINDS})")
        out[lid] = (animated[lid], row)
    return out


# ------------------------------------------------------------------------------------------------ measurement
def changed_count(F: list[np.ndarray]) -> np.ndarray:
    """Per native px: in how many of frames 1.. the pixel differs from frame 0 (patch alpha > 0, step > CHANGE_THR)."""
    f0 = F[0].astype(np.int32)
    ch = np.zeros(f0.shape[:2], np.float32)
    for f in F[1:]:
        f = f.astype(np.int32)
        ch += (f[..., 3] > 0) & (np.abs(f[..., :3] - f0[..., :3]).max(-1) > CHANGE_THR)
    return ch


def composite(F: list[np.ndarray]) -> list[np.ndarray]:
    """Frames 1.. over frame 0 (a DEF frame's transparent px keep frame 0)."""
    return [F[0]] + [np.where(f[..., 3:4] > 0, f, F[0]) for f in F[1:]]


def fit_spin(F: list[np.ndarray], rect, lid: str) -> dict:
    """Rotor measurement on rect (DEF px) of the composited frames: {"cx", "cy", "rad" (rect-local px), "sail" (the
    rotor px of frame 0), "steps" (deg per frame, + = counter-clockwise on screen), "fit" (report)}. Fails closed when
    the steps do not agree (see the module doc) or the median step is 0 or at the search bound."""
    x0, y0, x1, y1 = rect
    C = composite(F)
    G = np.stack([cv2.cvtColor(np.ascontiguousarray(f[y0:y1, x0:x1, :3]), cv2.COLOR_RGB2GRAY) for f in C]).astype(np.float32)
    sd = G.std(0)
    mv = sd > SPIN_MOVE_STD
    if int(mv.sum()) < 20:
        raise SystemExit(f"town_full3d_fx: {lid}: spin rect {list(rect)} has {int(mv.sum())} moving px")
    ys, xs = np.nonzero(mv)
    w = sd[mv]
    cx, cy = float(np.average(xs, weights=w)), float(np.average(ys, weights=w))
    rad = float(np.percentile(np.hypot(xs - cx, ys - cy), 99)) + 1.0
    yy, xx = np.mgrid[0:G.shape[1], 0:G.shape[2]]
    disc = np.hypot(xx - cx, yy - cy) <= rad
    D = (G - np.median(G, 0)) * disc          # the rotor's pattern; the static structure cancels
    angs = np.arange(-SPIN_MAX_DEG, SPIN_MAX_DEG + SPIN_RES_DEG / 2, SPIN_RES_DEG)
    steps, peaks = [], []
    for k in range(len(C) - 1):
        b = D[k + 1].ravel() - D[k + 1].mean()
        best = (-2.0, 0.0)
        for a in angs:
            r = cv2.warpAffine(D[k], cv2.getRotationMatrix2D((cx, cy), float(a), 1), D[k].shape[::-1]).ravel()
            r = r - r.mean()
            best = max(best, (float(r @ b / (np.linalg.norm(r) * np.linalg.norm(b) + 1e-9)), float(a)))
        peaks.append(best[0])
        steps.append(best[1])
    st = np.asarray(steps)
    med = float(np.median(st))
    agree = float((np.abs(st - med) <= SPIN_AGREE_DEG).mean())
    if agree < SPIN_AGREE_MIN or med == 0.0 or abs(med) >= SPIN_MAX_DEG - SPIN_RES_DEG:
        raise SystemExit(f"town_full3d_fx: {lid}: spin rect {list(rect)} is not a rigid rotor: median step {med} deg, "
                         f"{agree:.2f} of {len(steps)} steps within {SPIN_AGREE_DEG} deg (need {SPIN_AGREE_MIN}); "
                         f"steps {steps}")
    # long baseline: frame 0 rotated onto frame k, tracked round the previous angle + the median step
    win = max(2 * abs(med), 2.0)
    th = [0.0]
    for k in range(1, len(C)):
        b = D[k].ravel() - D[k].mean()
        best = (-2.0, 0.0)
        for a in np.arange(th[-1] + med - win, th[-1] + med + win + SPIN_RES_DEG / 2, SPIN_RES_DEG):
            r = cv2.warpAffine(D[0], cv2.getRotationMatrix2D((cx, cy), float(a), 1), D[0].shape[::-1]).ravel()
            r = r - r.mean()
            best = max(best, (float(r @ b / (np.linalg.norm(r) * np.linalg.norm(b) + 1e-9)), float(a)))
        th.append(best[1])
    kk = np.arange(len(th), dtype=np.float64)
    slope = float((kk * np.asarray(th)).sum() / (kk * kk).sum())
    fit = {"method": "composited-frame NCC rotation about the change-weighted hub; speed = long-baseline track slope",
           "stepMedianDeg": med, "trackSlopeDeg": round(slope, 4), "trackEndDeg": th[-1],
           "agreeShare": round(agree, 3), "agreeDeg": SPIN_AGREE_DEG, "nccP50": round(float(np.median(peaks)), 3),
           "frameSteps": steps, "movingPx": int(mv.sum())}
    sail = mv & disc & (C[0][y0:y1, x0:x1, 3] > 0)
    sail = cv2.morphologyEx(sail.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8)).astype(bool)
    return {"cx": cx, "cy": cy, "rad": rad, "sail": sail, "steps": [round(slope, 4)], "fit": fit}


def _shift(a: np.ndarray, dx: float, dy: float) -> np.ndarray:
    return cv2.warpAffine(a, np.float32([[1, 0, dx], [0, 1, dy]]), a.shape[::-1], flags=cv2.INTER_LINEAR)


def _track(B: list[np.ndarray], T: np.ndarray) -> list[tuple[float, float]]:
    """Per frame, the translation of template T that best explains the bob mask. Score = bob px the shifted template
    covers - bob px it leaves unexplained - template px that land on the bob's path where this frame shows background
    (px that are bob in some other frame). Template px on px that are never bob cost nothing: that is where a static
    occluder (a beam in front) hides the bob. Integer search over |shift| <= SWING_SHIFT_MAX_PX, then the sub-pixel
    vertex of the parabola through the best score and its two neighbours on each axis (integer kept on a flat top)."""
    R = SWING_SHIFT_MAX_PX
    ever = np.stack(B).max(0)
    out = []
    for b in B:
        tot = float(b.sum())
        bg = ever * (1 - b)
        sc = np.full((2 * R + 1, 2 * R + 1), -np.inf)
        for dy in range(-R, R + 1):
            if abs(dy) >= T.shape[0]:
                continue
            Ty = np.roll(T, dy, 0)
            for dx in range(-R, R + 1):
                if abs(dx) >= T.shape[1]:
                    continue
                Ts = np.roll(Ty, dx, 1)
                sc[dy + R, dx + R] = 2 * float((Ts * b).sum()) - tot - float((Ts * bg).sum())
        iy, ix = np.unravel_index(int(np.argmax(sc)), sc.shape)

        def vertex(lo, mid, hi):
            den = lo - 2 * mid + hi
            return 0.0 if not np.isfinite(den) or den >= 0 else float(np.clip(0.5 * (lo - hi) / den, -0.5, 0.5))
        fx = vertex(sc[iy, ix - 1], sc[iy, ix], sc[iy, ix + 1]) if 0 < ix < 2 * R else 0.0
        fy = vertex(sc[iy - 1, ix], sc[iy, ix], sc[iy + 1, ix]) if 0 < iy < 2 * R else 0.0
        out.append((ix - R + fx, iy - R + fy))
    return out


def fit_swing(F: list[np.ndarray], rect, lid: str, sel: dict | None) -> dict:
    """Pendulum measurement on rect (DEF px) of the composited frames (see the module doc). Returns rect-local px:
    {"pivot": (x, y), "L", "ampDeg", "phaseDeg", "periodFrames", "zeroDeg", "bob" (RGBA of the bob at the reference
    frame's pose), "front" (RGBA of the static px that hide the bob somewhere on its path, or None), "plate" (RGB of
    the rect with the bob removed), "fit" (report)}."""
    if not sel:
        raise SystemExit(f"town_full3d_fx: {lid}: a swing effect needs the bob's \"colour\" (HSV range): the frames' "
                         f"median is no background where a slow bob dwells at the ends of its swing")
    x0, y0, x1, y1 = rect
    C = composite(F)
    S = np.stack([f[y0:y1, x0:x1, :3] for f in C]).astype(np.float32)
    op = C[0][y0:y1, x0:x1, 3] > 0
    med = np.median(S, 0)
    ever = np.ptp(S, 0).max(-1) > CHANGE_THR               # px that change in some frame
    sel_k = [hsv_in(s, sel) for s in S]
    B = [(sk & ever & op).astype(np.float32) for sk in sel_k]  # bob: in the bob's colour where the px changes
    n = len(B)
    px = [int(b.sum()) for b in B]
    if min(px) < SWING_MIN_PX:
        raise SystemExit(f"town_full3d_fx: {lid}: swing rect {list(rect)}: bob px per frame {px} (need "
                         f"{SWING_MIN_PX} in every frame)")
    ref = int(np.argmax(px))
    T = B[ref].copy()
    for _ in range(2):                       # template = the bob as every frame shows it, aligned to the reference
        sh = _track(B, T)
        acc = sum(_shift(b, -dx, -dy) for b, (dx, dy) in zip(B, sh))
        T = (acc >= max(2.0, 0.2 * n)).astype(np.float32)
    sh = _track(B, T)
    sx = np.array([d[0] for d in sh])        # the template's own frame: shift 0 = the bob texture's pose
    sy = np.array([d[1] for d in sh])
    if np.abs(sx).max() >= SWING_SHIFT_MAX_PX - 1 or np.abs(sy).max() >= SWING_SHIFT_MAX_PX - 1:
        raise SystemExit(f"town_full3d_fx: {lid}: swing track reaches the search bound: x {sx.tolist()} y {sy.tolist()}")
    k = np.arange(n, dtype=np.float64)
    best = None
    for m in range(1, n // 2):               # the DEF loops: a whole number of swings per loop
        w = 2 * np.pi * m / n
        A = np.stack([np.cos(w * k), np.sin(w * k), np.ones(n)], 1)
        c = np.linalg.lstsq(A, sx, rcond=None)[0]
        rms = float(np.sqrt(np.mean((A @ c - sx) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, m, c)
    xrms, m, (a, b, xc) = best
    amp = float(np.hypot(a, b))
    phase = float(np.degrees(np.arctan2(a, b)))          # u(k) = amp sin(w k + phase)
    if xrms > SWING_X_RMS_MAX_PX or amp < SWING_MIN_AMP_PX:
        raise SystemExit(f"town_full3d_fx: {lid}: swing rect {list(rect)} is not a swing: horizontal track "
                         f"{sx.round(2).tolist()} about {m} cycles / loop has rms {xrms:.2f} px (max "
                         f"{SWING_X_RMS_MAX_PX}), amplitude {amp:.2f} px (min {SWING_MIN_AMP_PX})")
    u = sx - xc
    # arc: y(k) = yb - L (1 - cos asin(u / L)); L by a 1-D search, bounded by the travel and by 40 x the travel
    Ls = np.arange(amp + 0.05, 40.0 * amp, 0.05)
    g = Ls[:, None] * (1 - np.sqrt(1 - np.clip(u[None, :] / Ls[:, None], -1, 1) ** 2))
    yb = (sy[None, :] + g).mean(1)
    yr = np.sqrt(((yb[:, None] - g - sy[None, :]) ** 2).mean(1))
    i = int(yr.argmin())
    L, yrms = float(Ls[i]), float(yr[i])
    rise = L * (1 - math.sqrt(1 - (amp / L) ** 2))
    band = Ls[yr <= yrms + 0.1]
    if i == len(Ls) - 1 or rise < SWING_RISE_MIN_PX or yrms > SWING_Y_RMS_MAX_PX:
        raise SystemExit(f"town_full3d_fx: {lid}: swing rect {list(rect)} has no measurable arc: rise {rise:.2f} px "
                         f"(min {SWING_RISE_MIN_PX}), arc rms {yrms:.2f} px (max {SWING_Y_RMS_MAX_PX}), L {L:.2f} px "
                         f"(search bound {Ls[-1]:.2f}); vertical track {sy.round(2).tolist()}: a translation is not a "
                         f"swing about a pivot")
    ys_, xs_ = np.nonzero(T)
    cT = (float(xs_.mean()), float(ys_.mean()))           # bob centre at the reference pose
    pivot = (cT[0] + xc, cT[1] + float(yb[i]) - L)
    zero = float(np.degrees(math.asin(float(np.clip(-xc / L, -1, 1)))))   # reference pose's angle (+ = ccw on screen)
    th = np.degrees(np.arcsin(np.clip(u / L, -1, 1)))
    ampd = float(np.degrees(math.asin(min(amp / L, 1.0))))
    model = ampd * np.sin(2 * np.pi * m * k / n + math.radians(phase))
    # the bob's colour at the reference pose: per px, the median of the frames that show it there
    cnt = np.zeros(T.shape, np.float32)
    stack = []
    for s, bb, (dx, dy) in zip(S, B, sh):
        vis = _shift(bb, -dx, -dy) > 0.5
        stack.append(np.where(vis[..., None], cv2.warpAffine(s, np.float32([[1, 0, -dx], [0, 1, -dy]]), s.shape[1::-1],
                                                             flags=cv2.INTER_NEAREST), np.nan))
        cnt += vis
    bobm = (T > 0) & (cnt > 0)
    bob = np.zeros(T.shape + (4,), np.uint8)
    bob[bobm, :3] = np.nanmedian(np.stack(stack)[:, bobm], 0).round().clip(0, 255).astype(np.uint8)
    bob[..., 3] = bobm * 255
    # where the bob is not: the plate. A px the bob covers in every frame has no plate colour (fail closed).
    on = [cv2.dilate(bb, np.ones((3, 3), np.uint8)) > 0 for bb in B]
    covered = np.stack(on)
    if (covered.all(0) & op).any():
        raise SystemExit(f"town_full3d_fx: {lid}: swing: {int((covered.all(0) & op).sum())} px show the bob in every "
                         f"frame (no plate colour under it)")
    free = ~covered.all(0)
    plate = med.copy()                       # transparent px the dilation reaches: any colour, alpha 0 in the sprite
    plate[free] = np.nanmedian(np.stack([np.where(c[..., None], np.nan, s) for s, c in zip(S, covered)])[:, free], 0)
    plate = plate.round().clip(0, 255).astype(np.uint8)
    # static px in front of the bob: px its silhouette passes over (template at each frame's track, grown by 1 px for
    # the rotation-vs-translation difference) that never change in any frame (so no frame shows the bob there, whatever
    # its colour). Drawn in front of the bob card they restore what the DEF shows there (a beam across the bob); they
    # never cover a px that changes in any frame.
    swept = np.zeros(T.shape, np.float32)
    for dx, dy in sh:
        swept = np.maximum(swept, _shift(T, dx, dy))
    hid = (cv2.dilate((swept > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~ever & op
    front = None
    if hid.any():
        front = np.zeros(T.shape + (4,), np.uint8)
        front[..., :3] = S[0].round().clip(0, 255).astype(np.uint8)   # never-changing px: any frame
        front[..., 3] = hid * 255
    # the model redrawn at each DEF frame (plate, bob card turned about the pivot, front card) against the DEF, and the
    # static plate alone against the DEF (what a non-moving stand-in shows): mean max-channel |RGB| over the px the DEF
    # changes (ever)
    ba = bob.astype(np.float32)
    err, err0 = [], []
    for kk in range(n):
        ang = ampd * math.sin(2 * math.pi * m * kk / n + math.radians(phase)) - zero
        r = cv2.warpAffine(ba, cv2.getRotationMatrix2D(pivot, ang, 1), ba.shape[1::-1], flags=cv2.INTER_LINEAR)
        a = r[..., 3:4] / 255.0
        img = plate * (1 - a) + r[..., :3] * a
        img[hid] = front[hid, :3] if front is not None else img[hid]
        err.append(float(np.abs(img - S[kk]).max(-1)[ever & op].mean()))
        err0.append(float(np.abs(plate.astype(np.float32) - S[kk]).max(-1)[ever & op].mean()))
    fit = {"method": "bob = px in the bob's colour where the px changes over the frames, tracked by occlusion-tolerant template "
                     "translation; horizontal track = whole swings per loop sinusoid; pivot height from the arc's rise",
           "referenceFrame": ref, "bobPxPerFrame": px, "trackX": sx.round(2).tolist(), "trackY": sy.round(2).tolist(),
           "cyclesPerLoop": m, "xRmsPx": round(xrms, 3), "ampPx": round(amp, 2), "phaseDeg": round(phase, 2),
           "lengthPx": round(L, 2), "lengthBandPx": [round(float(band.min()), 2), round(float(band.max()), 2)],
           "risePx": round(rise, 2), "arcRmsPx": round(yrms, 3), "ampDeg": round(ampd, 2), "zeroDeg": round(zero, 2),
           "angleModelRmsDeg": round(float(np.sqrt(np.mean((model - th) ** 2))), 2),
           "pivotPx": [round(float(pivot[0]) + x0, 2), round(float(pivot[1]) + y0, 2)], "frontPx": int(hid.sum()),
           "redrawMaeRgb": round(float(np.mean(err)), 2), "staticPlateMaeRgb": round(float(np.mean(err0)), 2)}
    return {"pivot": pivot, "L": L, "ampDeg": ampd, "phaseDeg": phase, "periodFrames": n / m, "zeroDeg": zero,
            "bob": bob, "front": front, "plate": plate, "fit": fit}


def rect_mask(shape, rects, exclude) -> np.ndarray:
    m = np.zeros(shape, bool)
    if not rects:
        m[:] = True
    for x0, y0, x1, y1 in rects or []:
        m[max(y0, 0):y1, max(x0, 0):x1] = True
    for x0, y0, x1, y1 in exclude or []:
        m[max(y0, 0):y1, max(x0, 0):x1] = False
    return m


def colour_mask(F: list[np.ndarray], sel: dict | None) -> np.ndarray:
    """Pixels whose brightest colour over frames 1.. lies in sel's HSV range (all True when sel is None)."""
    if not sel:
        return np.ones(F[0].shape[:2], bool)
    St = np.stack([np.where(f[..., 3:4] > 0, f[..., :3], F[0][..., :3]) for f in F[1:]]).astype(np.float32)
    iy, ix = np.indices(St.shape[1:3])
    best = St[St.sum(-1).argmax(0), iy, ix]
    return hsv_in(best, sel)


def hsv_in(rgb: np.ndarray, sel: dict | None) -> np.ndarray:
    """Pixels of rgb (uint8-valued, any dtype) inside sel's HSV range (all True when sel is None)."""
    if not sel:
        return np.ones(rgb.shape[:2], bool)
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb.astype(np.uint8)), cv2.COLOR_RGB2HSV_FULL).astype(np.float32)
    h, s, v = hsv[..., 0] * 360 / 256, hsv[..., 1] / 255, hsv[..., 2] / 255
    m = (s >= float(sel.get("minS", 0))) & (v >= float(sel.get("minV", 0)))
    if "hue" in sel:
        lo, hi = sel["hue"]
        m &= ((h >= lo) & (h <= hi)) if lo <= hi else ((h >= lo) | (h <= hi))
    return m


def bright_colour(F: list[np.ndarray], m: np.ndarray) -> np.ndarray:
    """sRGB 0..1: median of the brightest quartile of the moving pixels over frames 1.. (the lit colour of the effect)."""
    px = np.concatenate([f[..., :3][m & (f[..., 3] > 0)] for f in F[1:]]).astype(np.float32)
    if not len(px):
        px = F[0][..., :3][m].astype(np.float32)
    lum = px.mean(-1)
    return np.median(px[lum >= np.percentile(lum, 75)], 0) / 255.0


def mean_colour(F: list[np.ndarray], m: np.ndarray) -> np.ndarray:
    px = np.concatenate([f[..., :3][m & (f[..., 3] > 0)] for f in F[1:]]).astype(np.float32)
    return np.median(px, 0) / 255.0


def components(m: np.ndarray, min_px: int, dilate: int = 1) -> list[tuple[np.ndarray, tuple]]:
    """Connected components of m (joined across `dilate` px); each (own-pixel mask, (x0, y0, x1, y1))."""
    lab, _ = ndimage.label(ndimage.binary_dilation(m, iterations=dilate) if dilate else m)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        cm = (lab == i) & m
        if cm.sum() >= min_px:
            out.append((cm, (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)))
    return out


def mask_png(prefab_dir, name: str, w: np.ndarray, rect, up: int = 4) -> tuple[str, int]:
    """Square soft mask texture of weights w (native px) centred on rect; returns (file name, side in native px)."""
    x0, y0, x1, y1 = rect
    n = max(x1 - x0, y1 - y0) + 2
    m = np.zeros((n * up, n * up), np.float32)
    ox, oy = (n - (x1 - x0)) / 2, (n - (y1 - y0)) / 2
    crop = w[y0:y1, x0:x1].astype(np.float32)
    big = cv2.resize(crop, ((x1 - x0) * up, (y1 - y0) * up), interpolation=cv2.INTER_LINEAR)
    m[int(oy * up):int(oy * up) + big.shape[0], int(ox * up):int(ox * up) + big.shape[1]] = big
    m = cv2.GaussianBlur(m, (0, 0), up * 0.5)
    prefab_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(m / max(float(m.max()), 1e-6), 0, 1) * 255).astype(np.uint8)).save(prefab_dir / name)
    return name, n


def rgba(c, a=1.0, gain=1.0) -> list[float]:
    return [float(x) * gain for x in c[:3]] + [float(a)]


# ------------------------------------------------------------------------------------------------ kinds
class Ctx:
    def __init__(self, sc, M, A, P, lid, F, nf, meta):
        import stronghold_full3d_scene as S
        self.sc, self.M, self.A, self.P, self.lid, self.F, self.nf = sc, M, A, P, lid, F, nf
        self.S = S
        self.prefab = S.PREFIX + lid
        self.dir = S.STAGE / self.prefab
        self.period = nf * meta[lid]["frameRateMs"] / 1000.0
        self.frame_s = meta[lid]["frameRateMs"] / 1000.0
        self.frame_ms = float(meta[lid]["frameRateMs"])   # the DEF's own row (layer_meta keys it by layer)
        self.off = (0, 0)          # sprite px = DEF px - off (check_registration)
        self.e: dict = {}          # the effect being built (its floatZm)
        self.places: list = []     # per piece: relief / float and the depth used

    def spr(self, x, y):
        """DEF px -> sprite px."""
        return np.asarray(x, np.float64) - self.off[0], np.asarray(y, np.float64) - self.off[1]

    def floats(self, rect) -> bool:
        """A piece with any DEF px above the sprite's top row has no relief under it."""
        return rect[1] - self.off[1] < 0

    def float_depth(self, rect) -> float:
        """Depth of the building directly below a float piece: median over the piece's columns of the relief depth at
        the top opaque sprite px (the effect's floatZm when the profile sets one)."""
        if "floatZm" in self.e:
            return float(self.e["floatZm"])
        a = np.asarray(SC.sprite(self.P.L))[..., 3] > 0
        x0, _, x1, _ = rect
        cols = [c for c in range(max(0, x0 - self.off[0]), min(a.shape[1], x1 - self.off[0])) if a[:, c].any()]
        if not cols:
            raise SystemExit(f"town_full3d_fx: {self.lid}: a piece at DEF {list(rect)} floats over no sprite column; "
                             f"set the effect's floatZm")
        return float(np.median([self.P.z[int(np.argmax(a[:, c])), c] for c in cols]))

    def at(self, x, y, rect, pull=SF.FRONT_PULL_M):
        """World point of DEF px (x, y) of the piece `rect`: on the relief, or on the piece's float card."""
        sx, sy = self.spr([x], [y])
        if not self.floats(rect):
            self.places.append({"rect": list(rect), "placement": "relief"})
            return self.P.world(sx, sy, pull=pull)[0]
        z = self.float_depth(rect)
        self.places.append({"rect": list(rect), "placement": "float", "zM": round(z, 2),
                            "floatZmSet": "floatZm" in self.e})
        return self.P.cam["pos"] + self.P.ray(sx + 0.5, sy + 0.5)[0] * (z - pull)

    def centre(self, rect, pull=SF.FRONT_PULL_M):
        x0, y0, x1, y1 = rect
        c = self.at((x0 + x1) / 2, (y0 + y1) / 2, rect, pull=pull)
        zc = float((c - self.P.cam["pos"]) @ self.P.cam["fwd"])
        return c, zc, self.P.m_per_px(zc)

    def group(self, name, c, systems):
        return {"name": name, "pos": [float(x) for x in self.sc.local(c[None, :])[0]], "rot": [0.0, 0.0, 0.0, 1.0],
                "scale": float(self.sc.scale), "systems": systems}


def k_flame(X: Ctx, e: dict, m: np.ndarray, k: int):
    groups, rep = [], []
    for j, (cm, rect) in enumerate(components(m, int(e.get("minPx", 6)))):
        col = bright_colour(X.F, cm)
        c, zc, mpp = X.centre(rect)
        fname, n = mask_png(X.dir, f"flame_{k}_{j}_mask.png", cm.astype(np.float32), rect)
        size = n * mpp
        mat = X.M.uber("TileNoise_19_vfx", "TileNoise_23_vfx", mask_path=f"{X.S.ASSET_ROOT}/{X.prefab}/{fname}",
                       st1=(1, 1), st2=(1, 2), mn=0.05, mx=0.45, lerp=1.0, blend=0.3,
                       color=tuple(rgba(col, 1.0, 1.8)), speeds=(0.1, -1.4, -0.1, -0.9))
        nm = f"Fx_Flame_{k}_{j}_{X.lid}"
        groups.append(X.group(nm, c, [
            SF.psys("flame", mat, lifetime=[0.18, 0.35], speed=[0], size=[size, size * 1.05], rate=9, maxParticles=4,
                    radius=0.001, color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.15, 1, 0.7, 1, 1, 0]),
            SF.psys("glow", X.A["glow"], lifetime=[0.25, 0.5], speed=[0], size=[size * 1.6, size * 2.2], rate=5,
                    maxParticles=4, radius=size * 0.05, color=rgba(col, 0.3), alphaKeys=[0, 0, 0.3, 1, 0.7, 0.8, 1, 0],
                    customUV=False),
        ]))
        rep.append({"name": nm, "rect": list(rect), "px": int(cm.sum()), "colourSrgb": [round(float(x), 3) for x in col],
                    "sizeM": round(size, 3), "depthM": round(zc, 2)})
    return [], groups, rep


def k_glints(X: Ctx, e: dict, m: np.ndarray, k: int):
    ch = X.ch
    comps = components(m, int(e.get("minPx", 6)), dilate=3)
    # sparkle size: median extent of the per-frame changed blobs; rate: changed blobs per frame / frame time
    f0 = X.F[0].astype(np.int32)
    ext, per_frame = [], []
    for f in X.F[1:]:
        f = f.astype(np.int32)
        fm = (f[..., 3] > 0) & (np.abs(f[..., :3] - f0[..., :3]).max(-1) > CHANGE_THR) & m
        lab, _ = ndimage.label(fm)
        sizes = [max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) for sl in ndimage.find_objects(lab)]
        sizes = [z for z in sizes if z >= 2]           # single changed px are dither, not a sparkle
        per_frame.append(len(sizes))
        ext += sizes
    if not ext:
        raise SystemExit(f"town_full3d_fx: {X.lid}: glints: no sparkle of 2+ px in any frame")
    spark_px = float(np.median(ext))
    groups, rep = [], []
    tot = float(sum(cm.sum() for cm, _ in comps)) or 1.0
    life = max(2, round(float(ch[m].mean()))) * X.frame_s if m.any() else 0.2
    for j, (cm, rect) in enumerate(comps[:12]):
        col = bright_colour(X.F, cm)
        c, zc, mpp = X.centre(rect)
        x0, y0, x1, y1 = rect
        share = float(cm.sum()) / tot
        rate = max(1.0, float(np.mean(per_frame)) * share / life)   # sparkles alive at once = rate * life
        sz = spark_px * mpp
        nm = f"Fx_Glints_{k}_{j}_{X.lid}"
        groups.append(X.group(nm, c, [
            SF.psys("glints", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0], size=[sz * 0.6, sz * 1.2],
                    rate=round(rate, 2), maxParticles=max(4, int(rate * life * 2)), shape="box",
                    shapeScale=[(x1 - x0) * mpp, (y1 - y0) * mpp, 0.1], color=rgba(col, 1.0),
                    alphaKeys=[0, 0, 0.3, 1, 1, 0], sizeKeys=[0, 0, 0.35, 1, 1, 0], customUV=False),
        ]))
        rep.append({"name": nm, "rect": list(rect), "px": int(cm.sum()), "colourSrgb": [round(float(x), 3) for x in col],
                    "sparkPx": spark_px, "ratePerS": round(rate, 2), "lifeS": round(life, 3)})
    return [], groups, rep


def k_glow(X: Ctx, e: dict, m: np.ndarray, k: int):
    ys, xs = np.nonzero(m)
    rect = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    w = np.where(m, X.ch, 0.0)
    w = cv2.GaussianBlur(w.astype(np.float32), (0, 0), 1.5)
    col = bright_colour(X.F, m)
    c, zc, mpp = X.centre(rect)
    fname, n = mask_png(X.dir, f"glow_{k}_mask.png", w, rect)
    size = n * mpp
    mat = X.M.uber("TileNoise_23_vfx", "TileNoise_07_vfx", mask_path=f"{X.S.ASSET_ROOT}/{X.prefab}/{fname}",
                   st1=(1, 1), st2=(2, 2), mn=0.1, mx=0.7, lerp=1.0, blend=0.3,
                   color=tuple(rgba(col, 1.0, 1.2)), speeds=(0.05, 0.08, -0.06, 0.04))
    life = max(X.period, 0.6)
    nm = f"Fx_Glow_{k}_{X.lid}"
    g = X.group(nm, c, [
        SF.psys("pulse", mat, lifetime=[life, life], speed=[0], size=[size, size], rate=round(2.0 / life, 3),
                maxParticles=3, radius=0.001, color=[1, 1, 1, 0.55], alphaKeys=[0, 0, 0.5, 1, 1, 0]),
    ])
    rep = {"name": nm, "rect": list(rect), "px": int(m.sum()), "colourSrgb": [round(float(x), 3) for x in col],
           "sizeM": round(size, 3), "loopS": round(life, 3)}
    return [], [g], [rep]


def k_smoke(X: Ctx, e: dict, m: np.ndarray, k: int):
    groups, rep = [], []
    for j, (cm, rect) in enumerate(components(m, int(e.get("minPx", 40)), dilate=2)):
        x0, y0, x1, y1 = rect
        ys, xs = np.nonzero(cm)
        base_rows = ys >= np.percentile(ys, 90)
        top_rows = ys <= np.percentile(ys, 15)
        bx, by = float(np.median(xs[base_rows])), float(ys.max())
        w0 = float(np.ptp(xs[base_rows]) + 1)
        w1 = float(np.ptp(xs[top_rows]) + 1)
        col = mean_colour(X.F, cm)
        base = X.at(bx, by, rect)
        zc = float((base - X.P.cam["pos"]) @ X.P.cam["fwd"])
        mpp = X.P.m_per_px(zc)
        h = (y1 - y0) * mpp
        life = max(X.period, 1.0)
        v = h / life
        nm = f"Fx_Smoke_{k}_{j}_{X.lid}"
        groups.append(X.group(nm, base, [
            SF.psys("smoke", X.A["spray"], lifetime=[life * 0.85, life * 1.1], speed=[0], velY=[v * 0.85, v * 1.1],
                    size=[w0 * mpp * 0.9, w0 * mpp * 1.2], rate=round(6.0 / life + 2.0, 2), maxParticles=40,
                    radius=w0 * mpp * 0.25, color=rgba(col, 0.7), alphaKeys=[0, 0, 0.15, 1, 0.7, 0.6, 1, 0],
                    sizeKeys=[0, 1.0, 1, max(w1 / max(w0, 1.0), 1.0)], rotation=[0, 360], rotSpeed=[-20, 20]),
        ]))
        rep.append({"name": nm, "rect": list(rect), "basePx": [round(bx, 1), round(by, 1)], "heightM": round(h, 3),
                    "riseMperS": round(v, 3), "baseWidthPx": w0, "topWidthPx": w1,
                    "colourSrgb": [round(float(x), 3) for x in col]})
    return [], groups, rep


def k_lightning(X: Ctx, e: dict, m: np.ndarray, k: int):
    groups, rep = [], []
    lit = X.ch / max(len(X.F) - 1, 1)                  # fraction of frames 1.. each px is lit
    for j, (cm, rect) in enumerate(components(m, int(e.get("minPx", 40)), dilate=3)):
        col = bright_colour(X.F, cm)
        c, zc, mpp = X.centre(rect)
        fname, n = mask_png(X.dir, f"bolt_{k}_{j}_mask.png", np.clip(np.where(cm, lit, 0) * 1.6, 0, 1), rect)
        size = n * mpp
        life = max(1.0, float(X.ch[cm].mean())) * X.frame_s     # a flash lasts the mean frames a bolt px is lit
        mat = X.M.uber("TileNoise_19_vfx", "TileNoise_23_vfx", mask_path=f"{X.S.ASSET_ROOT}/{X.prefab}/{fname}",
                       st1=(2, 1), st2=(1, 2), mn=0.05, mx=0.35, lerp=1.0, blend=0.3,
                       color=tuple(rgba(col, 1.0, 1.6)), speeds=(1.7, 0.3, -1.3, 0.9))
        nm = f"Fx_Lightning_{k}_{j}_{X.lid}"
        groups.append(X.group(nm, c, [
            SF.psys("bolt", mat, lifetime=[life * 0.6, life * 1.2], speed=[0], size=[size, size],
                    rate=round(1.5 / life, 3), maxParticles=3, radius=0.001, color=[1, 1, 1, 1],
                    alphaKeys=[0, 0, 0.1, 1, 0.7, 1, 1, 0]),
            SF.psys("glow", X.A["glow"], lifetime=[life * 0.8, life * 1.4], speed=[0], size=[size * 0.9, size * 1.2],
                    rate=round(1.5 / life, 3), maxParticles=5, radius=size * 0.05, color=rgba(col, 0.35),
                    alphaKeys=[0, 0, 0.2, 1, 0.6, 0.7, 1, 0], customUV=False),
            SF.psys("sparks", X.A["glint"], lifetime=[0.1, 0.25], speed=[0], size=[size * 0.03, size * 0.07], rate=18,
                    maxParticles=12, shape="box", shapeScale=[size * 0.7, size * 0.5, 0.2], color=rgba(col, 1.0),
                    alphaKeys=[0, 0, 0.3, 1, 1, 0], sizeKeys=[0, 0, 0.35, 1, 1, 0], customUV=False),
        ]))
        rep.append({"name": nm, "rect": list(rect), "boltPx": int(cm.sum()),
                    "colourSrgb": [round(float(x), 3) for x in col], "sizeM": round(size, 3), "flashS": round(life, 3),
                    "depthM": round(zc, 2)})
    return [], groups, rep


def k_spin(X: Ctx, e: dict, m: np.ndarray, k: int):
    ys, xs = np.nonzero(m)
    rect = tuple(e["rects"][0]) if e.get("rects") else (int(xs.min()), int(ys.min()), int(xs.max()) + 1,
                                                         int(ys.max()) + 1)
    if X.floats(rect):
        raise SystemExit(f"town_full3d_fx: {X.lid}: spin at DEF {list(rect)} lies above the sprite (no relief)")
    meas = fit_spin(X.F, rect, X.lid)
    row, r = SF.windmill(X.sc, X.P, X.lid, rect, X.F, meas=meas, frame_ms=X.frame_ms, off=X.off)
    X.places.append({"rect": list(rect), "placement": "relief"})
    return [row], [], [r]


def swing_card(X: Ctx, name: str, rgba: np.ndarray, rect, pivot, pull: float) -> tuple[dict, dict]:
    """An unlit fx card (the stronghold windmill disc's frame, a square instead of a disc): holder at the pivot on the
    relief (pulled `pull` m toward the camera), local Y along the view ray (away from the camera: a positive turn about
    it reads counter-clockwise on screen), the rect-local RGBA laid out round the pivot in screen right / up."""
    import stronghold_full3d_scene as S
    x0, y0, _, _ = rect
    cx, cy = pivot
    ys, xs = np.nonzero(rgba[..., 3])
    half = float(np.hypot(np.maximum(np.abs(xs + 0.5 - cx), np.abs(xs - 0.5 - cx)) + 1,
                          np.maximum(np.abs(ys + 0.5 - cy), np.abs(ys - 0.5 - cy)) + 1).max())
    nn = 2 * int(math.ceil(half)) + 2
    up = 8
    Mw = np.float32([[1, 0, -(cx - nn / 2)], [0, 1, -(cy - nn / 2)]]) * np.float32([[up], [up]])
    rgb = cv2.warpAffine(np.ascontiguousarray(rgba[..., :3]), Mw, (nn * up, nn * up), flags=cv2.INTER_CUBIC)
    al = cv2.warpAffine((rgba[..., 3] > 0).astype(np.float32), Mw, (nn * up, nn * up), flags=cv2.INTER_LINEAR)
    al = cv2.GaussianBlur(al, (0, 0), up * 0.4)
    tex = np.zeros((nn * up, nn * up, 4), np.uint8)
    tex[..., :3] = rgb
    tex[..., 3] = (np.clip((al - 0.25) / 0.5, 0, 1) * 255).astype(np.uint8)
    X.dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tex).save(X.dir / f"{name}_albedo.png")
    sx, sy = X.spr([cx + x0], [cy + y0])
    hub = X.P.world(sx, sy, pull=pull)[0]
    hub_l = X.sc.local(hub[None, :])[0]
    Y = hub_l / np.linalg.norm(hub_l)            # camera -> pivot, prefab frame (camera at the origin)
    Xa = np.array([1.0, 0, 0]) - Y * Y[0]
    Xa /= np.linalg.norm(Xa)
    Z = np.cross(Xa, Y)
    R = np.stack([Xa, Y, Z], 1)
    zc = float((hub - X.P.cam["pos"]) @ X.P.cam["fwd"])
    h_units = nn / 2 * X.P.m_per_px(zc) * X.sc.scale
    zs_up = np.sign(Z @ np.array([0, 1.0, 0])) or 1.0
    cu = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float64)     # (right, up) corners
    Vl = np.stack([cu[:, 0], np.zeros(4), cu[:, 1] * zs_up], 1) * h_units
    uv = 0.5 + 0.5 * cu
    tris = np.array([[0, 1, 2], [0, 2, 3]])
    toward = R.T @ (-Y)
    cr = np.cross(Vl[tris[:, 1]] - Vl[tris[:, 0]], Vl[tris[:, 2]] - Vl[tris[:, 0]])
    flip = cr @ toward < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    S.write_bin(X.dir / f"{name}.bytes", Vl, np.tile(toward, (4, 1)), uv, [tris])
    row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{X.prefab}/{name}.bytes",
           "texture": f"{S.ASSET_ROOT}/{X.prefab}/{name}_albedo.png", "kind": "fx", "maxSize": 512,
           "pos": [float(v) for v in hub_l], "rot": SF.mat_to_quat(R)}
    return row, {"halfUnits": round(h_units, 4), "texPx": nn * up, "depthM": round(zc, 2)}


def k_swing(X: Ctx, e: dict, m: np.ndarray, k: int):
    if not e.get("rects") or len(e["rects"]) != 1:
        raise SystemExit(f"town_full3d_fx: {X.lid}: a swing effect needs exactly one explicit rect")
    rect = tuple(e["rects"][0])
    if X.floats(rect):
        raise SystemExit(f"town_full3d_fx: {X.lid}: swing at DEF {list(rect)} lies above the sprite (no relief)")
    meas = fit_swing(X.F, rect, X.lid, e.get("colour"))
    period = meas["periodFrames"] * X.frame_s
    nm = f"Fx_Swing_{k}_{X.lid}"
    row, card = swing_card(X, nm, meas["bob"], rect, meas["pivot"], SF.FRONT_PULL_M)
    row.update({"swingPeriod": round(period, 3), "swingAmpDeg": round(meas["ampDeg"], 3),
                "swingPhaseDeg": round(meas["phaseDeg"], 3), "swingZeroDeg": round(meas["zeroDeg"], 3)})
    rows = [row]
    rep = {"name": nm, "rect": list(rect), "periodSec": round(period, 3), "frameMs": X.frame_ms, "card": card,
           "fit": meas["fit"], "defOffset": [int(X.off[0]), int(X.off[1])]}
    if meas["front"] is not None:
        fn = f"Fx_SwingFront_{k}_{X.lid}"
        frow, fcard = swing_card(X, fn, meas["front"], rect, meas["pivot"], SF.FRONT_PULL_M + SWING_FRONT_PULL_M)
        rows.append(frow)
        rep["front"] = {"name": fn, "px": meas["fit"]["frontPx"], "card": fcard}
    X.places.append({"rect": list(rect), "placement": "relief"})
    return rows, [], [rep]


def k_water(X: Ctx, e: dict, m: np.ndarray, k: int, spec_l=None, sky_c=None):
    bins, rep = [], []
    S, P, M = X.S, X.P, X.M
    if sky_c is None or not np.isfinite(np.asarray(sky_c, np.float64)).all():
        raise SystemExit(f"town_full3d_fx: {X.lid}: water needs the painting's sky colour (none measured: {sky_c})")
    for j, (cm0, rect) in enumerate(components(m, int(e.get("minPx", 40)), dilate=3)):
        x0, y0, x1, y1 = rect
        if X.floats(rect):
            raise SystemExit(f"town_full3d_fx: {X.lid}: water at DEF {list(rect)} lies above the sprite (no relief)")
        sub = cm0[y0:y1, x0:x1].astype(np.uint8)
        # closed over 3 px only, holes kept: what the DEF does not move (lily pads, stones) stays the static sprite
        wm = cv2.morphologyEx(sub, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool) & (X.F[0][y0:y1, x0:x1, 3] > 0)
        ys, xs = np.nonzero(wm)
        wc = mean_colour(X.F, cm0)
        st = 0.5
        gx = np.arange(0, wm.shape[1] + st, st)
        gy = np.arange(0, wm.shape[0] + st, st)
        GX, GY = np.meshgrid(gx, gy)
        cx_, cy_ = GX[:-1, :-1] + st / 2, GY[:-1, :-1] + st / 2
        inside = wm[np.clip(cy_.astype(int), 0, wm.shape[0] - 1), np.clip(cx_.astype(int), 0, wm.shape[1] - 1)]
        gxs, gys = X.spr(GX.ravel() + x0, GY.ravel() + y0)   # world_smooth remaps one row: chunk under SHRT_MAX
        V = np.concatenate([P.world_smooth(gxs[i:i + 30000], gys[i:i + 30000], pull=SF.WATER_PULL_M)
                            for i in range(0, len(gxs), 30000)])
        nx = len(gx)
        iy, ix = np.nonzero(inside)
        a = iy * nx + ix
        tris = np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])
        used = np.unique(tris)
        remap = -np.ones(len(V), int)
        remap[used] = np.arange(len(used))
        V, tris = V[used], remap[tris]
        sx_v, sy_v = (GX.ravel() + x0)[used], (GY.ravel() + y0)[used]
        cp = P.cam["pos"]
        cr = np.cross(V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]])
        flip = cr @ (cp - V.mean(0)) < 0
        tris[flip] = tris[flip][:, [0, 2, 1]]
        hx, hy = xs + x0 + 0.5, ys + y0 + 0.5
        ecx, ecy = float((hx.min() + hx.max()) / 2), float((hy.min() + hy.max()) / 2)
        eax, eay = float((hx.max() - hx.min()) / 2 + 0.5), float((hy.max() - hy.min()) / 2 + 0.5)
        c = P.world_smooth(*X.spr([ecx], [ecy]), pull=SF.WATER_PULL_M)[0]
        zc = float((c - cp) @ P.cam["fwd"])
        Rm = float(np.mean([eax, eay]) * P.m_per_px(zc))
        en = np.stack([(sx_v - ecx) / eax, (sy_v - ecy) / eay], 1)
        uv0 = np.stack([0.5 + 0.5 * np.clip(en[:, 0], -1, 1), 0.5 + 0.5 * np.clip(en[:, 1], -1, 1)], 1)
        mpp = P.m_per_px(zc)
        # metres in the screen plane; FlowWater flows along +u, turned to the profile's screen direction "flowDir"
        # ([dx, dy], screen y down; default [1, 0]: a pond drifts sideways, a waterfall is [0, 1])
        fd = np.asarray(e.get("flowDir", [1.0, 0.0]), np.float64)
        fd = fd / (np.linalg.norm(fd) or 1.0)
        du, dv = (sx_v - ecx) * mpp, (sy_v - ecy) * mpp
        uv1 = np.stack([du * fd[0] + dv * fd[1], -du * fd[1] + dv * fd[0]], 1)
        n_ = 128
        tint = np.zeros((n_, n_, 4), np.uint8)
        tint[..., :3] = (np.clip(wc, 0, 1) * 255).astype(np.uint8)
        wsm = cv2.resize(wm.astype(np.float32), (n_, n_), interpolation=cv2.INTER_AREA)
        tint[..., 3] = (np.clip(cv2.GaussianBlur(wsm, (0, 0), 2.0), 0, 1) * 255).astype(np.uint8)
        name = f"Fx_Water_{k}_{j}_{X.lid}"
        X.dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(tint).save(X.dir / f"{name}_tint.png")
        colors = {"_SpecDir": [float(x) for x in spec_l[:3]] + [0.0],
                  "_SkyColor": [float(x) for x in sky_c[:3]] + [1.0]}
        mat = M.material("Homm3ConfluxFlowWater",
                         [M.tex("_MainTex", f"{S.ASSET_ROOT}/{X.prefab}/{name}_tint.png", clamp=True),
                          M.tex("_Noise", M.vtex("TileNoise_23_vfx")), M.tex("_Noise2", M.vtex("TileNoise_07_vfx")),
                          M.tex("_NormalMap", M.vtex("WaterNormal"), srgb=False)],
                         {"_ShoreRange": 22, "_ShoreOut": 2, "_Deep": 0.5, "_DeepPx": 10, "_Foam": 0.2, "_FoamPx": 2.5,
                          "_Feather": 2, "_Speed": Rm * 0.08, "_Scale": 2.2 / Rm, "_Stretch": 0.35, "_Ripple": 0.45,
                          "_NormalScale": 3.0 / Rm, "_Glint": 0.5}, colors)
        up = np.tile([0, 1.0, 0], (len(V), 1))
        mesh = SF.write_mesh(X.sc, X.prefab, name, X.sc.local(V), X.sc.local_dir(up), uv0, tris)
        (S.STAGE / X.prefab / f"{name}_uv2.bytes").write_bytes(np.asarray(uv1, np.float32).tobytes())
        bins.append({"name": name, "mesh": mesh, "kind": "fxmesh", "material": mat, "pos": [0.0, 0.0, 0.0],
                     "rot": [0.0, 0.0, 0.0, 1.0], "uv2": f"{S.ASSET_ROOT}/{X.prefab}/{name}_uv2.bytes"})
        X.places.append({"rect": list(rect), "placement": "relief"})
        rep.append({"name": name, "rect": list(rect), "waterPx": int(wm.sum()), "movingPx": int(cm0.sum()),
                    "colourSrgb": [round(float(x), 3) for x in wc], "radiusM": round(Rm, 3), "tris": int(len(tris))})
    return bins, [], rep


KIND_FN = {"flame": k_flame, "glints": k_glints, "glow": k_glow, "lightning": k_lightning, "smoke": k_smoke,
           "spin": k_spin, "swing": k_swing, "water": k_water, **MECH.KIND_FN}


# ------------------------------------------------------------------------------------------------ lane hooks
def static_plate(L: dict):
    """The sprite itself, except inside a `spin` rect, where the frames' median replaces the moving part, and inside a
    `swing` rect, where fit_swing's plate (each px's median over the frames that do not show the bob) replaces it, and
    inside a wheel / track rect, where town_full3d_mech's fit plate replaces it."""
    spr = SC.sprite(L)
    row = (getattr(SC.FP, "FX_LAYERS", None) or {}).get(L["id"])
    if not row:
        return spr
    spins = [e for e in row.get("effects") or [] if e.get("kind") == "spin"]
    swings = [e for e in row.get("effects") or [] if e.get("kind") == "swing"]
    mechs = [e for e in row.get("effects") or [] if e.get("kind") in MECH.FIT_FN]
    if not spins and not swings and not mechs:
        return spr
    lm = layer_meta(SC.anim_frames())
    F = def_frames(lm, L["id"])
    dx, dy = check_registration(lm, L["id"], L, F)
    a = np.asarray(spr).copy()
    for e in spins:
        if not e.get("rects"):
            raise SystemExit(f"town_full3d_fx: {L['id']}: a spin effect needs an explicit rect")
        x0, y0, x1, y1 = e["rects"][0]
        if x0 - dx < 0 or y0 - dy < 0 or x1 - dx > a.shape[1] or y1 - dy > a.shape[0]:
            raise SystemExit(f"town_full3d_fx: {L['id']}: spin rect {e['rects'][0]} (DEF px) leaves the sprite")
        S = np.stack([f[y0:y1, x0:x1, :3] for f in composite(F)]).astype(np.float32)
        a[y0 - dy:y1 - dy, x0 - dx:x1 - dx, :3] = np.median(S, 0).round().astype(np.uint8)
    for e in swings:
        if not e.get("rects") or len(e["rects"]) != 1:
            raise SystemExit(f"town_full3d_fx: {L['id']}: a swing effect needs exactly one explicit rect")
        x0, y0, x1, y1 = e["rects"][0]
        if x0 - dx < 0 or y0 - dy < 0 or x1 - dx > a.shape[1] or y1 - dy > a.shape[0]:
            raise SystemExit(f"town_full3d_fx: {L['id']}: swing rect {e['rects'][0]} (DEF px) leaves the sprite")
        a[y0 - dy:y1 - dy, x0 - dx:x1 - dx, :3] = fit_swing(F, e["rects"][0], L["id"], e.get("colour"))["plate"]
    for e in mechs:
        if not e.get("rects") or len(e["rects"]) != 1:
            raise SystemExit(f"town_full3d_fx: {L['id']}: a {e['kind']} effect needs exactly one explicit rect")
        x0, y0, x1, y1 = e["rects"][0]
        if x0 - dx < 0 or y0 - dy < 0 or x1 - dx > a.shape[1] or y1 - dy > a.shape[0]:
            raise SystemExit(f"town_full3d_fx: {L['id']}: {e['kind']} rect {e['rects'][0]} (DEF px) leaves the sprite")
        a[y0 - dy:y1 - dy, x0 - dx:x1 - dx, :3] = MECH.FIT_FN[e["kind"]](F, tuple(e["rects"][0]), L["id"], e)["plate"]
    return Image.fromarray(a)


def stage(sc, rd: dict, spec_l, sky_c) -> dict:
    """Fx_ rows per classified animated layer; returns {"rows", "audit", "report", "vanillaTextures"}."""
    import stronghold_full3d_buildings as BL
    import stronghold_full3d_scene as S
    M = SF.Mats(S.STAGE, S.ASSET_ROOT, S.SHADER_DIR)
    A = M.standard()
    lays = SC.layers()
    meta = SC.anim_frames()
    meta = layer_meta(meta)
    todo = classify(SC.reachable_layers(), meta, fx_layers())
    rows, audit, rep = {}, {}, {}
    for lid, (nf, spec) in todo.items():
        L = lays[lid]
        P = SF.Place(sc, L, BL.layer_depth(lid, L, rd))
        F = def_frames(meta, lid)
        X = Ctx(sc, M, A, P, lid, F, nf, meta)
        X.def_id = meta[lid]["defId"]
        X.off = check_registration(meta, lid, L, F)
        X.ch = changed_count(F)
        bins, groups, r = [], [], {}
        for k, e in enumerate(spec["effects"]):
            m = (X.ch > 0) & rect_mask(X.ch.shape, e.get("rects"), e.get("exclude")) & colour_mask(F, e.get("colour"))
            if e.get("colourNot"):
                m &= ~colour_mask(F, e["colourNot"])
            if int(m.sum()) < int(e.get("minPx", 6)):
                raise SystemExit(f"town_full3d_fx: {lid}: effect {k} ({e['kind']}) has {int(m.sum())} changed px "
                                 f"in its rects (the DEF does not move there)")
            X.e = e
            if e["kind"] == "water":
                b, g, rr = k_water(X, e, m, k, spec_l, sky_c)
            else:
                b, g, rr = KIND_FN[e["kind"]](X, e, m, k)
            if not b and not g:
                raise SystemExit(f"town_full3d_fx: {lid}: effect {k} ({e['kind']}) produced no piece")
            bins += b
            groups += g
            r[f"{e['kind']}_{k}"] = rr
        names = [b["name"] for b in bins] + [g["name"] for g in groups]
        if len(set(names)) != len(names):
            raise SystemExit(f"town_full3d_fx: {lid}: repeated effect piece names {names}")
        rows[S.PREFIX + lid] = {"bins": bins, "particles": groups}
        audit[lid] = {"defFrames": nf, "defId": meta[lid]["defId"], "moves": spec["moves"], "effects": names,
                      "kinds": [e["kind"] for e in spec["effects"]], "frameRateMs": meta[lid]["frameRateMs"],
                      "changedPx": int((X.ch > 0).sum()), "defOffset": list(X.off),
                      "placements": sorted({pl["placement"] for pl in X.places})}
        r["placements"] = X.places
        rep[lid] = r
        print("fx", lid, json.dumps(r)[:500], flush=True)
    return {"rows": rows, "audit": audit, "report": rep, "vanillaTextures": M.sources}
