"""Stronghold full-3D buildings: one closed relief mesh per reachable HoMM3 building level (no Meshy).

Per layer (every level is its own prefab, swapped by the runtime's native BhBuilding interaction):
  * mask     the sprite's alpha, minus the HoMM3 shadow/transparency palette leftovers (magenta-hued pixels) and minus
             pixels identical to the town background under them (sprites carry sky or ground cut from the painting);
             small specks dropped, holes filled.
  * depth    Depth Anything V2 Large on the sprite composited over the background (a context crop,
             stronghold_full3d_depth), calibrated PER CROP: a robust affine fit of its disparity to the calibrated
             terrain inverse depth on the crop's own background pixels (so the building is measured against the
             ground it stands on). Then clamped never to sit behind the painted ground at the same pixel, relief
             limited to RELIEF_M (hand-tuned per layer) about the footing depth, smoothed.
  * footing  the lowest mask pixels of each column are pulled onto the terrain surface (FOOT_BAND px ramp): no
             floating or sunken buildings (checked in the report: footing error in metres).
  * mesh     a screen-space grid over the sprite (GRID px), silhouette vertices snapped to the frame-res mask edge;
             closed by hand: every silhouette edge is extruded away from the camera by THICK_M (per layer; default
             from the building's width) to a flat back face.
  * texture  front = the sprite upscaled to BUILD_SCALE texels per 1080p px (LANCZOS) and de-lit by the Hex/Lit
             irradiance of its normals; sides and back use a second half of the atlas: the same art darkened and
             blurred (a back is unseen at the rest pose; under pan it reads as the building's shaded far side).
Proof tier: generated artifact (offline previews); editor renders are the review evidence.
"""
from __future__ import annotations

import math
import os

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import stronghold_full3d_ground as G

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
GRID = 2                    # frame px per grid cell
BUILD_SCALE = 2             # bake texels per 1080p px
FOOT_BAND = 10.0            # frame px above the footing over which the base is pulled onto the terrain
NORMAL_SIGMA_CELLS = 3.0    # grid cells of depth smoothing behind the shading normals
NORMAL_VIEW_LEAN = 0.35     # shading normals lean this far toward the viewer
ALBEDO_MAX = 0.97           # de-lit albedo ceiling the normal bend must make reachable
SIDE_DARKEN = 0.8           # sides / back are this much darker than the front's row colour
CUT_RATIO = 1.08            # a grid triangle whose depth spread exceeds this ratio is cut (a depth step, not a surface)
BG_EQUAL = 10               # max RGB difference to the background under the sprite that counts as "the painting"
# Hand-tuned per layer: relief half-range and thickness (m); None = derived from the width (faction profile).
# RELIEF_TUNE[lid]["hung"]: a sprite hung in the painted relief (a treehouse on a trunk, nests in a canopy) whose
# lowest pixel sits over far ground: its footing is the HUNG_RING_Q quantile of the painted depth in a HUNG_RING_PX
# ring around its mask (the trunk / canopy it hangs in) instead of the terrain below it (Fortress: 173-323 m fog
# footings for bodies whose surroundings sit at 63-110 m, so the body spanned 97-273 m and sheared under the sweeps).
TUNE = SC.FP.RELIEF_TUNE
HUNG_RING_PX = 15           # native px ring around a hung sprite's mask
HUNG_RING_Q = 0.25          # quantile of the ring's painted depth taken as the hung sprite's footing

FRINGE_DE = 20.0             # dE76 to the painting under it at or below which an opening-nominated px is fringe / speck


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.clip(rgb / 255, 0, 1).astype(np.float32), cv2.COLOR_RGB2LAB)


def drop_fringe(m: np.ndarray, rgb: np.ndarray, under: np.ndarray) -> np.ndarray:
    """Speck / fringe removal, a subset of m. A true 2x2 opening (erode anchored top-left, dilate with the reflected
    anchor) nominates the sub-kernel px; a nominated px is dropped only when it matches the painting under it
    (dE76 <= FRINGE_DE), so thin opaque detail stays and background-coloured specks and fringe go.
    MORPH_OPEN with one off-centre anchor for both passes shifted the mask 1 px (a transparent right / bottom rim:
    the Stronghold x311 / x637 bars); m & MORPH_OPEN(m) (769a896baf) removed that rim but shaved the top / left px
    off every shape and deleted every sub-2px feature (Inferno tbinext2 rays and spike tips)."""
    m = np.asarray(m, bool)
    k2 = np.ones((2, 2), np.uint8)
    opened = cv2.dilate(cv2.erode(m.astype(np.uint8), k2, anchor=(0, 0)), k2, anchor=(1, 1)).astype(bool)
    de = np.linalg.norm(_lab(np.asarray(rgb, np.float32)) - _lab(np.asarray(under, np.float32)), axis=-1)
    return m & ~(~opened & (de <= FRINGE_DE))


MASK_DARK = 20              # max RGB channel at or below which a px's background match is ambiguous (dark on dark)
MASK_DENSITY_SIGMA = 2.0   # native px: neighbourhood over which a bright px's background-match share is taken
MASK_DENSITY = 0.35        # share of matching bright px at or above which a neighbourhood is the carried painting
MASK_EDGE_PX = 4            # native px band along the sprite edge where any background match is painting
MASK_BRIDGE_PX = 3          # opening width that cuts the thin dark bridges from a facade's dark arch to the cave


def coherent_painting(a: np.ndarray, same: np.ndarray, lum: np.ndarray) -> np.ndarray:
    """Profile MASK_PAINT_COHERENT: which background-equal px are the painting the sprite carries. The carried painting
    (cave wall, ground ledge cut with the sprite) is a coherent region on the sprite's rim; a px of the building that
    merely matches the background within BG_EQUAL (Dungeon 2026-10-18: dark arches, shadowed tower sides and the mage
    tower door against the dark cave behind; speckle across lit facades) is not. Bright matches count where at least
    MASK_DENSITY of the bright px around them match, and only in a component that reaches the alpha rim; a dark match
    (max channel <= MASK_DARK) is painting only when it connects to that painting or the rim through other dark matches
    once thin bridges are opened away; an enclosed dark match stays building."""
    a = np.asarray(a, bool)
    dark = lum <= MASK_DARK
    bn = a & ~dark
    # the match is speckly even on a true painting copy (palette / resampling noise): judge the local share of bright
    # px that match, not single px
    num = cv2.GaussianBlur((same & bn).astype(np.float32), (0, 0), MASK_DENSITY_SIGMA)
    den = cv2.GaussianBlur(bn.astype(np.float32), (0, 0), MASK_DENSITY_SIGMA)
    dense = bn & (num > MASK_DENSITY * np.maximum(den, 1e-6))
    # the image edge counts as rim (a fully opaque rectangular sprite carries painting out to its frame)
    rim = a & ~cv2.erode(a.astype(np.uint8), np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT,
                         borderValue=0).astype(bool)
    n, lab = cv2.connectedComponents(dense.astype(np.uint8), connectivity=8)
    hit = np.unique(lab[rim & (lab > 0)])
    region = np.isin(lab, hit) & (lab > 0)
    paint = region & same
    # dark matches: painting only where they connect to the carried painting (or the rim) through other matches, after
    # an opening cuts the 1-2 px bridges by which a dark arch inside a facade would leak out to the cave
    cand = (same & a & dark).astype(np.uint8)
    k = np.ones((MASK_BRIDGE_PX, MASK_BRIDGE_PX), np.uint8)
    core = cv2.morphologyEx(cand, cv2.MORPH_OPEN, k).astype(bool)
    seed = cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) | rim
    n2, lab2 = cv2.connectedComponents((core | region).astype(np.uint8), connectivity=4)
    hit2 = np.unique(lab2[seed & (lab2 > 0)])
    reach = np.isin(lab2, hit2) & (lab2 > 0) & core
    # give back the opening's trim next to a reached core (geodesic, MASK_BRIDGE_PX steps inside the dark matches)
    for _ in range(MASK_BRIDGE_PX):
        reach = cv2.dilate(reach.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & cand.astype(bool)
    # within MASK_EDGE_PX of the sprite's edge every background match is the carried painting (as before): thin strips
    # of cave there are too narrow for the density / opening tests and would stand as bright side walls under pans
    band = a & ~cv2.erode(a.astype(np.uint8), np.ones((2 * MASK_EDGE_PX + 1,) * 2, np.uint8),
                          borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
    return paint | reach | (same & band)


def native_mask(L: dict) -> np.ndarray:
    spr = np.asarray(SC.sprite(L)).astype(np.int32)
    bg = np.asarray(SC.background_rgb()).astype(np.int32)
    x, y = L["x"], L["y"]
    h, w = spr.shape[:2]
    sy, sx = max(0, -y), max(0, -x)   # a sprite may start above / left of the screen (Fortress tbfrdw_2_3, y -12)
    under = bg[y + sy:y + h, x + sx:x + w]
    hh, ww = under.shape[:2]
    a = spr[..., 3] > 128
    r, g, b = spr[..., 0], spr[..., 1], spr[..., 2]
    magenta = (r > 120) & (b > 120) & (g < 0.62 * np.minimum(r, b))
    same = np.zeros_like(a)
    same[sy:sy + hh, sx:sx + ww] = np.abs(spr[sy:sy + hh, sx:sx + ww, :3] - under).max(-1) <= BG_EQUAL
    # TOWN_MASK_PAINT_COHERENT=1 turns it on for a trial build of a faction whose profile does not set it yet
    if getattr(SC.FP, "MASK_PAINT_COHERENT", False) or os.environ.get("TOWN_MASK_PAINT_COHERENT") == "1":
        same = coherent_painting(a, same, spr[..., :3].max(-1))
    if L["id"] in getattr(SC.FP, "PAINTED_LAYERS", ()):
        # profile PAINTED_LAYERS: the painting itself carries this building (HotA Factory's village hall is painted
        # into the background, its DEF repeats it within BG_EQUAL): the sprite's own alpha is the mask
        same[:] = False
    m = a & ~magenta & ~same
    und = np.zeros(spr.shape[:2] + (3,), np.int32)
    und[sy:sy + hh, sx:sx + ww] = under
    m = drop_fringe(m, spr[..., :3], und).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 25
    m = keep[lab]
    # fill holes
    inv = (~m).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    border = set(np.unique(np.r_[lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]]).tolist())
    holes = np.isin(lab2, [i for i in range(1, n2) if i not in border and st2[i, cv2.CC_STAT_AREA] < 400])
    return m | holes


def crop_calibration(lid: str, L: dict, mask: np.ndarray, rd: dict) -> dict:
    """Per-crop affine map of the layer's DA disparity to the terrain's inverse depth on its own background."""
    import json
    idx = json.loads((SC.DATA / "depth" / "layers" / "index.json").read_text(encoding="utf-8"))[lid]
    x0, y0, x1, y1 = idx["box"]
    k = idx["k"]
    d4 = np.load(SC.DATA / "depth" / "layers" / f"{lid}_da_large.npy")
    d = cv2.resize(d4, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    # terrain inverse depth at the crop's native pixels
    zc = rd["zc"]
    ys, xs = np.mgrid[y0:y1, x0:x1]
    fx = np.clip(((xs + 0.5) * SC.SCALE).astype(int), 0, TW - 1)
    fy = np.clip(((ys + 0.5) * SC.SCALE).astype(int), 0, TH - 1)
    zt = zc[fy, fx]
    m_full = np.zeros_like(d, bool)
    mx0, my0 = L["x"] - x0, L["y"] - y0
    mh, mw = mask.shape
    sy, sx, ty, tx = max(0, -my0), max(0, -mx0), max(0, my0), max(0, mx0)   # sprite rows above the screen: none
    m_full[ty:ty + mh - sy, tx:tx + mw - sx] = mask[sy:sy + max(0, min(mh - sy, (y1 - y0) - ty)),
                                                     sx:sx + max(0, min(mw - sx, (x1 - x0) - tx))]
    near = cv2.dilate(m_full.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    sel = ~near & np.isfinite(zt)
    if sel.sum() < 200:
        raise SystemExit(f"{lid}: only {int(sel.sum())} background pixels to calibrate its crop depth")
    dv, iv = d[sel].astype(np.float64), 1.0 / zt[sel]
    A = np.stack([np.ones_like(dv), dv], 1)
    w = np.ones(len(dv))
    for _ in range(15):
        sol, *_ = np.linalg.lstsq(A * w[:, None], iv * w, rcond=None)
        res = A @ sol - iv
        s = 1.4826 * np.median(np.abs(res[w > 0])) + 1e-12
        u = res / (4.685 * s)
        w = np.where(np.abs(u) < 1, (1 - u * u) ** 2, 0.0)
    inv = sol[0] + sol[1] * d
    return {"inv": inv, "zt": zt, "box": (x0, y0, x1, y1), "offset": (mx0, my0), "sol": sol.tolist(),
            "residRel": float(np.median(np.abs(res[w > 0]) / iv[w > 0])), "inliers": float((w > 0).mean()),
            "bgPx": int(sel.sum())}


# RELIEF_TUNE[lid]["flat"]: a sprite that carries a painted plume or cloud (Necropolis tbncspec's storm cloud over
# the tower) gets that region as a flat card: the depth model reads the billowing cloud as rough relief, and the solid
# closure then gives it depth-step cracks and lit side walls that float as fragments under the pan poses. The region
# is the DEF's own changed-pixel mask (town_full3d_fx.changed_count: the cloud is what moves), closed by closePx and
# grown by growPx native px, inside the sprite's alpha, plus the sprite's alpha pixels that native_mask dropped as
# "the painting" (within BG_EQUAL of the background) where they touch that region above its lowest changed row: the
# painting has no cloud there (town_all/necropolis/tbncspec_bg_vs_sprite.png), the dark smoke is merely within 10 RGB
# of the dark sky, and dropping it cut the cloud into ragged islands. The region joins the layer mask. Geometry only:
# every texel is the sprite's own, none is recoloured.
def flat_region(lid: str, L: dict, mask: np.ndarray, tune: dict):
    spec = tune.get("flat")
    if spec is None:
        return None, None
    if not isinstance(spec, dict) or spec.get("source") != "defChanged":
        raise SystemExit(f"RELIEF_TUNE {lid}: flat needs {{'source': 'defChanged', 'closePx', 'growPx'}}, got {spec!r}")
    cp, gp = spec.get("closePx"), spec.get("growPx")
    if not (isinstance(cp, int) and cp >= 1 and isinstance(gp, int) and gp >= 0):
        raise SystemExit(f"RELIEF_TUNE {lid}: flat closePx must be an int >= 1 and growPx an int >= 0, got {spec!r}")
    import town_full3d_fx as FX
    meta = FX.layer_meta(SC.anim_frames())
    if lid not in meta or len(meta[lid].get("frames") or []) < 2:
        raise SystemExit(f"RELIEF_TUNE {lid}: flat source defChanged, but the layer has no animated DEF")
    ch = FX.changed_count(FX.def_frames(meta, lid)) > 0
    if ch.shape != mask.shape:
        raise SystemExit(f"RELIEF_TUNE {lid}: DEF frame {ch.shape} and sprite mask {mask.shape} differ")
    k = 2 * cp + 1
    m = cv2.morphologyEx(ch.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    if gp:
        m = cv2.dilate(m, np.ones((2 * gp + 1, 2 * gp + 1), np.uint8))
    alpha = np.asarray(SC.sprite(L).convert("RGBA"))[..., 3] > 128
    core = m.astype(bool) & alpha
    dropped = alpha & ~mask
    dropped[int(np.nonzero(ch.any(1))[0].max()) + 1:] = False
    n, lab = cv2.connectedComponents(dropped.astype(np.uint8), connectivity=8)
    touch = np.unique(lab[cv2.dilate(core.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & dropped])
    joined = np.isin(lab, touch[touch > 0])
    flat = core | joined
    if flat.sum() < 200:
        raise SystemExit(f"RELIEF_TUNE {lid}: flat region has only {int(flat.sum())} px")
    return flat, {"source": "defChanged", "closePx": cp, "growPx": gp, "px": int(flat.sum()),
                  "joinedPaintingPx": int((joined & ~core).sum()),
                  "share": round(float(flat.sum() / max((mask | flat).sum(), 1)), 3)}


# ------------------------------------------------------------------------------------------------ contact_v1
# Opt-in per candidate (<candidate>/work/building_depth.json {"mode": "contact_v1"}; no pin = the legacy per-column
# footing + relief window below, unchanged). docs/homm3_town_building_contact_depth.md.
# Legacy: every column is footed on the terrain right under its own lowest mask px and the depth is clamped to a
# relief window about that footing. A sprite that carries its own reflection or a floor decal (Cove's waterfall,
# the stilt houses) is footed at the reflection's bottom, so 76-99.6% of its px were set by the window, not by the
# depth map, and the upright part was dragged up to ~150 m toward the camera along its rays.
# contact_v1: (1) split the mask into a GROUND part (floor-polygon px whose calibrated depth follows the painted floor
# plane, in value and in its vertical gradient, connected to the sprite's bottom: reflection, decal, reeds) and an
# UPRIGHT part (the rest); (2) one robust contact for the upright part (its lowest rows); (3) the upright depth is an
# affine map of the crop's calibrated inverse depth anchored at the contact, 1/z = 1/z_c + sigma (inv - inv_c), with
# sigma in [0, 1] shrunk until its p2-p98 extent is at most CONTACT_THICK_K x its width (thickness prior; sigma = 0,
# a flat card at the contact, when the crop calibration is inverted); (4) the ground part lies on the floor plane.
# Every px stays on its own ray (rest pose pixel-exact). Rest-occlusion clamp min(z, 0.997 zt) kept and counted.
CONTACT_THICK_K = 0.8        # upright front-surface depth extent (p2-p98) <= this x its width at the contact
GROUND_LOG_TOL = 0.25        # |log(z / z_floor)| at or below which a floor-polygon px is floor-consistent in value
GROUND_SLOPE_MIN = 0.5       # and its vertical d log z / d row is at least this share of the floor plane's
GROUND_BOTTOM_PX = 2         # a ground component must reach within this many native px of its column's lowest px
GROUND_GAP_PX = 3            # non-ground px a column's ground run may cross on its way up from the sprite's bottom
CONTACT_Q = 0.75             # the contact row: this quantile of the upright part's per-column lowest rows
CONTACT_BAND_PX = 3          # native px above each contact column's lowest upright px that set inv_c
CONTACT_UNDER_PX = 6         # native rows under each contact column whose calibrated terrain sets z_c
CONTACT_UNDER_Q = 0.5        # the quantile (median) of those terrain depths
CONTACT_LEDGE_RATIO = 1.3    # terrain under the contact deeper than this x the sprite's own base depth: rawLedge


def building_depth_pin() -> dict | None:
    """The candidate's building depth pin (<candidate>/work/building_depth.json), None without one (legacy)."""
    import json
    import os
    cand = (os.environ.get("TOWN_FULL3D_CANDIDATE", "") or os.environ.get("STRONGHOLD_FULL3D_CANDIDATE", "")).strip()
    if not cand:
        return None
    p = SC.DATA / "candidates" / cand / "work" / "building_depth.json"
    if not p.is_file():
        return None
    pin = json.loads(p.read_text(encoding="utf-8"))
    if pin.get("mode") != "contact_v1":
        raise SystemExit(f"buildings: {p} mode {pin.get('mode')!r} is not contact_v1")
    return pin


def contact_depth(inv: np.ndarray, up: np.ndarray, inv_c: float, z_c: float, sigma: float) -> np.ndarray:
    """contact_v1 upright depth: affine in disparity anchored at the contact, z = 1 / (1/z_c + sigma (inv - inv_c)),
    with inv clipped to the upright part's own p2-p98 window (the window contact_sigma bounds). Tested by
    test_town_building_contact_depth.py."""
    inv = np.asarray(inv, np.float64)
    sel = np.asarray(up, bool) & np.isfinite(inv)
    lo, hi = np.percentile(inv[sel], [2, 98]) if sel.any() else (inv_c, inv_c)
    return 1.0 / np.maximum(1.0 / z_c + sigma * (np.clip(inv, lo, hi) - inv_c), 1e-6)


def contact_sigma(inv_up: np.ndarray, inv_c: float, z_c: float, width_m: float, k: float = CONTACT_THICK_K,
                  far_m: float = 4000.0) -> tuple[float, float, float]:
    """The thickness prior: the largest sigma in [0, 1] for which z = 1 / (1/z_c + sigma (inv - inv_c)) over the
    upright px has a p2-p98 extent <= k * width_m and stays in front of far_m. Returns (sigma, extent at sigma 1,
    extent at sigma). Tested by test_town_building_contact_depth.py."""
    inv_up = np.asarray(inv_up, np.float64)
    inv_up = inv_up[np.isfinite(inv_up)]
    if not len(inv_up):
        return 0.0, 0.0, 0.0
    q2, q98 = np.percentile(inv_up, [2, 98])
    cap = k * max(width_m, 1e-3)

    def extent(sg):
        a, b = 1.0 / z_c + sg * (q2 - inv_c), 1.0 / z_c + sg * (q98 - inv_c)
        if min(a, b) <= 1.0 / far_m:
            return math.inf
        return abs(1.0 / a - 1.0 / b)

    e1 = extent(1.0)
    if e1 <= cap:
        return 1.0, e1, e1
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if extent(mid) <= cap:
            lo = mid
        else:
            hi = mid
    return lo, e1, extent(lo)


def ground_split(mask: np.ndarray, raw: np.ndarray, plane: np.ndarray, in_floor: np.ndarray, dlog_plane: np.ndarray,
                 low: np.ndarray) -> np.ndarray:
    """GROUND px of a sprite mask: inside the floor polygon, calibrated depth within GROUND_LOG_TOL of the floor plane,
    its vertical log-depth gradient at least GROUND_SLOPE_MIN of the plane's (a wall standing on the floor has the
    floor's depth at its base but no gradient), in 8-connected components that reach the sprite's bottom.
    Tested by test_town_building_contact_depth.py."""
    ok = mask & in_floor & np.isfinite(raw) & np.isfinite(plane)
    lr = np.full(mask.shape, np.inf)
    lr[ok] = np.log(np.maximum(raw[ok], 1e-6) / np.maximum(plane[ok], 1e-6))
    kv = (mask & np.isfinite(raw)).astype(np.float32)
    lz = np.zeros(mask.shape, np.float32)
    lz[kv > 0] = np.log(np.maximum(raw[kv > 0], 1e-6))
    lzs = cv2.GaussianBlur(lz, (0, 0), 2.0) / np.maximum(cv2.GaussianBlur(kv, (0, 0), 2.0), 1e-6)
    g = np.zeros_like(lzs)
    g[1:-1] = 0.5 * (lzs[2:] - lzs[:-2])
    dp = np.where(np.abs(dlog_plane) > 1e-9, dlog_plane, np.nan)
    ratio = np.nan_to_num(g / dp, nan=0.0)
    cand = ok & (np.abs(lr) <= GROUND_LOG_TOL) & (ratio >= GROUND_SLOPE_MIN)
    if not cand.any():
        return cand
    mh = mask.shape[0]
    rows = np.arange(mh)[:, None]
    bottom = (low[None, :] >= 0) & (rows >= low[None, :] - GROUND_BOTTOM_PX)
    n, lab = cv2.connectedComponents(cand.astype(np.uint8), connectivity=8)
    keep = np.unique(lab[cand & bottom])
    g = np.isin(lab, keep[keep > 0])
    # per column, the ground is one run up from the sprite's bottom: from the lowest mask px upward across gaps of at
    # most GROUND_GAP_PX non-ground px (depth-model speckle inside a reflection), so no upright island is left under
    # the waterline to drag the contact down
    out = np.zeros_like(g)
    for c in np.nonzero(low >= 0)[0]:
        col, top, gap = g[:, c], None, 0
        for r in range(low[c], -1, -1):
            if not mask[r, c]:
                break
            if col[r]:
                top, gap = r, 0
            else:
                gap += 1
                if gap > GROUND_GAP_PX:
                    break
        if top is not None:
            out[top:low[c] + 1, c] = mask[top:low[c] + 1, c] & in_floor[top:low[c] + 1, c]
    return out


def _contact_v1(lid: str, L: dict, rd: dict, mask: np.ndarray, inv: np.ndarray, zt: np.ndarray, low: np.ndarray,
                tune: dict, flat, contact_px=None) -> dict:
    """contact_v1 depth of the layer's mask px (block comment above)."""
    mh, mw = mask.shape
    floor = rd["floor"]
    raw = 1.0 / np.maximum(inv, 1e-5)
    ys, xs = np.mgrid[0:mh, 0:mw]
    fy = (L["y"] + ys + 0.5) * SC.SCALE
    fx = (L["x"] + xs + 0.5) * SC.SCALE
    fm = T.floor_mask()
    inside = (fy >= 0) & (fy < TH) & (fx >= 0) & (fx < TW)
    in_floor = inside & fm[np.clip(fy.astype(int), 0, TH - 1), np.clip(fx.astype(int), 0, TW - 1)]
    pinv = floor.inv_depth(fy)
    plane = np.where(pinv > 0, 1.0 / np.maximum(pinv, 1e-9), np.nan)
    dlog_plane = np.where(pinv > 0, -SC.SCALE / np.maximum(fy - T.HORIZON_PY, 1e-6), 0.0)   # d log z_floor / d row
    if tune.get("hung") or tune.get("noGround"):
        ground = np.zeros_like(mask)
    else:
        ground = ground_split(mask, raw, plane, in_floor, dlog_plane, low)
    if flat is not None:
        ground &= ~flat
    up = mask & ~ground
    if up.any() and not (tune.get("hung") or tune.get("noGround")):
        # an upright island wholly inside the floor polygon and wholly below the main upright part's base is a
        # reflection the depth model did not read as floor (Cove's stilt houses: the ladders mirrored in the lake)
        n, lab, st, _ = cv2.connectedComponentsWithStats(up.astype(np.uint8), connectivity=8)
        main = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        mm = lab == main
        lowm = np.where(mm.any(0), mh - 1 - np.argmax(mm[::-1], 0), -1)
        base = float(np.quantile(lowm[lowm >= 0], CONTACT_Q))
        demote = [k for k in range(1, n) if k != main and st[k, cv2.CC_STAT_TOP] > base
                  and in_floor[lab == k].all()]
        if demote:
            dm = np.isin(lab, demote)
            ground, up = ground | dm, up & ~dm
    if up.sum() < 20:           # all ground (a decal, a pond): the floor plane carries it
        ground, up = mask & np.isfinite(plane), mask & ~np.isfinite(plane)
    # the upright part's contact: per column lowest upright px, the CONTACT_Q quantile row, the columns near it
    lowu = np.where(up.any(0), mh - 1 - np.argmax(up[::-1], 0), -1)
    cols = np.nonzero(lowu >= 0)[0]
    rep = {"mode": "contact_v1", "groundShare": round(float(ground.sum() / max(mask.sum(), 1)), 4),
           "uprightPx": int(up.sum()), "groundPx": int(ground.sum())}
    if len(cols):
        r_c = float(np.quantile(lowu[cols], CONTACT_Q))
        tol = max(4.0, 0.05 * mh)
        ccols = cols[np.abs(lowu[cols] - r_c) <= tol]
        if contact_px is not None:
            # an explicit contact (a Meshy body's base): its row, the upright columns within tol of its column; the
            # columns' own lowest upright px are moved to that row for the terrain lookup below
            r_c, c0 = float(contact_px[0]), float(contact_px[1])
            near = cols[np.abs(cols - c0) <= max(tol, 0.1 * mw)]
            ccols = near if len(near) else cols[[int(np.argmin(np.abs(cols - c0)))]]
            lowu = lowu.copy()
            lowu[ccols] = int(np.clip(round(r_c), 0, mh - 1))
        band = np.zeros_like(up)
        for c in ccols:
            band[max(0, lowu[c] - CONTACT_BAND_PX):lowu[c] + 1, c] = True
        band &= up & np.isfinite(inv)
        inv_c = float(np.median(inv[band])) if band.any() else float(np.nanmedian(inv[up]))
        c_c = int(np.median(ccols))
        row_below = int(min(round(r_c) + 1, mh - 1))
        fy_c, fx_c = (L["y"] + row_below + 0.5) * SC.SCALE, (L["x"] + c_c + 0.5) * SC.SCALE
        if tune.get("hung"):
            k = 2 * HUNG_RING_PX + 1
            ring = (cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & ~mask & np.isfinite(zt)
            if ring.sum() < 200:
                raise SystemExit(f"{lid}: hung sprite has only {int(ring.sum())} ring px of painted depth")
            z_c, src = float(np.quantile(zt[ring], HUNG_RING_Q)), "hungRing"
        else:
            # the calibrated terrain right under the contact columns (the mesh the building visibly stands on; the
            # floor plane's depth there is reported beside it)
            # (CONTACT_UNDER_PX rows under each contact column, their median: one row alone flips across a shore
            # line or a cliff lip; a near quantile instead split Cove's two gate levels, 202 m vs 370 m)
            zz = []
            for c in ccols:
                for k in range(1, CONTACT_UNDER_PX + 1):
                    yb = lowu[c] + k
                    v = zt[yb, c] if yb < mh else np.nan
                    if not np.isfinite(v):
                        fy_k = int((L["y"] + yb + 0.5) * SC.SCALE)
                        fx_k = min(int((L["x"] + c + 0.5) * SC.SCALE), TW - 1)
                        v = rd["zc"][fy_k, fx_k] if 0 <= fy_k < TH else np.nan
                    zz.append(v)
            zz = np.asarray(zz, np.float64)
            if not np.isfinite(zz).any():
                if "floatZm" not in tune:
                    raise SystemExit(f"{lid}: contact_v1 found no terrain under the contact "
                                     f"(a floating sprite needs RELIEF_TUNE[{lid!r}]['floatZm'])")
                z_c, src = float(tune["floatZm"]), "floatZm"
            else:
                z_c, src = float(np.nanquantile(zz, CONTACT_UNDER_Q)), "terrain"
                z_raw = 1.0 / inv_c if inv_c > 0 else math.inf
                if z_c > CONTACT_LEDGE_RATIO * z_raw:
                    # the terrain under the contact reads far deeper than the sprite's own base: a ledge / cliff top
                    # the background calibration pushed back (cause 3, docs/homm3_town_building_contact_depth.md).
                    # Standing on it would put the body behind the backdrop; the sprite's own base depth is used
                    # and the source says so (Cove tbcvnix2: terrain 381 m, own base 233 m)
                    z_c, src = float(z_raw), "rawLedge"
        behind = zt[up & np.isfinite(zt)]
        rep["zRawContactM"] = round(1.0 / inv_c, 2) if inv_c > 0 else None
        rep["zBehindP10M"] = round(float(np.quantile(behind, 0.1)), 2) if len(behind) else None
        if 0 <= fy_c < TH and 0 <= fx_c < TW and fm[int(fy_c), int(fx_c)] and floor.inv_depth(fy_c) > 0:
            rep["zFloorPlaneM"] = round(float(1.0 / floor.inv_depth(fy_c)), 2)
        # the upright part's width: p2-p98 of its px columns (px-weighted), the validator's own width measure
        # (validate_town_scene3d_contract building_upright_stats: p2-p98 azimuth). The min-max column extent let a
        # flagpole or an eave double it (rampart tbrmdw_1_2: 11.8 m vs 6.5 m, its solid then measured 3.49x deep)
        upc = np.nonzero(up)[1]
        c2, c98 = np.percentile(upc, [2, 98])
        width_m = (c98 - c2 + 1) * SC.SCALE * 2 * z_c * math.tan(math.radians(47.6) / 2) / H
        sol1 = float(rd.get("_sol1", 1.0))
        sig, e1, es = (contact_sigma(inv[up], inv_c, z_c, width_m) if sol1 > 0 else (0.0, float("nan"), 0.0))
        # the prior bounds the upright p2-p98 extent; the tails beyond it are clipped to that window, not left free
        # (rampart tbrmdw_1_2: 4% of its front, a low side wall at the sprite's edge, ran back to 126 m from a
        # 90 m contact and measured 3.5x its width)
        zu = contact_depth(inv, up, inv_c, z_c, sig)
        rep.update({"contactRow": round(r_c, 1), "contactCol": c_c, "contactSource": src, "zContactM": round(z_c, 2),
                    "invContact": inv_c, "sigma": round(sig, 4),
                    "extentRawM": round(e1, 2) if np.isfinite(e1) else None,
                    "extentM": round(es, 2), "uprightWidthM": round(width_m, 2)})
    else:
        z_c = float(np.nanmedian(plane[ground])) if ground.any() else float("nan")
        width_m = 0.0
        zu = np.full(mask.shape, z_c)
        rep.update({"contactSource": "allGround", "zContactM": round(z_c, 2)})
    zg = np.where(np.isfinite(plane), plane, raw)
    z = np.where(ground, zg, zu)
    if flat is not None:
        fl_ = flat & mask
        z = np.where(fl_, float(np.nanmedian(z[fl_])), z)
    # rest occlusion: never past the far cap (the dome). Ground px are also kept in front of the painted terrain at the
    # same px; upright px are NOT clamped to it per px - a px-wise clamp tore the terrain-covered px (4.7%) of castle
    # tbcsdw_0 40+ m off its body (upright span 49.6 m against a 12.9 m prior). The upright part stays one rigid
    # affine piece and town_full3d_building_redepth.order_pass pulls the whole layer in front of the terrain instead.
    # restClampShare reports the upright share the terrain would cover at the contact depth (what the pass resolves).
    rl = np.linalg.norm(T.rays(T.camera(), fx, fy), axis=-1)
    far = T.FAR_CAP_M / rl
    lim_t = np.where(np.isfinite(zt), zt * 0.997, np.inf)
    rep["restClampShare"] = round(float((mask & (z > lim_t))[up].mean()) if up.any() else 0.0, 4)
    z = np.minimum(z, far)
    z = np.where(ground, np.minimum(z, lim_t), z)
    # masked smoothing within each part (a reflection does not bleed into its building)
    out = np.full(mask.shape, np.nan)
    for part in (up, ground):
        if not part.any():
            continue
        zz = np.where(part, z, 0).astype(np.float32)
        kk = part.astype(np.float32)
        sm = cv2.GaussianBlur(zz, (0, 0), 0.8) / np.maximum(cv2.GaussianBlur(kk, (0, 0), 0.8), 1e-6)
        out = np.where(part, sm, out)
    return {"z": out, "zContact": z_c, "ground": ground, "upright": up, "widthM": width_m, "audit": rep}


def depth_audit(ld: dict) -> dict:
    """The stage-report depth audit of one layer: reliefWindowShare (legacy: share of mask px whose depth the relief
    window set instead of the depth map; contact_v1: 0, there is no window), footSpreadRatio (p95 / p5 of the
    per-column footing), and the upright front's depth span over its width (validate_town_scene3d_contract)."""
    a = dict(ld.get("audit") or {})
    m = ld["mask"]
    up = ld.get("upright")
    up = m if up is None else up
    z = ld["z"][up & np.isfinite(ld["z"])]
    fz = ld["foot_z"][ld["low"] >= 0]
    a["reliefWindowShare"] = round(float(ld.get("windowShare", 0.0)), 4)
    a["footSpreadRatio"] = round(float(np.percentile(fz, 95) / max(np.percentile(fz, 5), 1e-6)), 3) if len(fz) else None
    if len(z):
        span = float(np.percentile(z, 98) - np.percentile(z, 2))
        a["uprightSpanM"] = round(span, 2)
        a["spanOverWidth"] = round(span / max(ld["widthM"], 0.5), 3)
    a.setdefault("mode", "legacy")
    return a


def layer_depth(lid: str, L: dict, rd: dict, mode: str | None = None, contact_px=None) -> dict:
    """Native-resolution depth (painting m) of the sprite's mask pixels, footed and clamped (legacy), or contact_v1
    when the candidate pins it (building_depth_pin). mode forces "legacy" / "contact_v1" (the redepth pass reads both).
    contact_px (native row, col) sets the contact_v1 contact (a Meshy body's base, town_full3d_building_redepth)."""
    if mode is None:
        mode = "contact_v1" if building_depth_pin() is not None else "legacy"
    if mode not in ("legacy", "contact_v1"):
        raise SystemExit(f"layer_depth: unknown mode {mode!r}")
    mask = native_mask(L)
    flat, flat_rep = flat_region(lid, L, mask, TUNE.get(lid, {}))
    if flat is not None:
        mask = mask | flat
    cal = crop_calibration(lid, L, mask, rd)
    mx0, my0 = cal["offset"]
    mh, mw = mask.shape
    x0, y0, x1, y1 = cal["box"]
    inv = np.full(mask.shape, np.nan)
    zt = np.full(mask.shape, np.nan)
    ch, cw = y1 - y0, x1 - x0
    sy, sx, ty, tx = max(0, -my0), max(0, -mx0), max(0, my0), max(0, mx0)   # sprite rows above the screen stay NaN
    hh, ww = min(mh - sy, ch - ty), min(mw - sx, cw - tx)
    inv[sy:sy + hh, sx:sx + ww] = cal["inv"][ty:ty + hh, tx:tx + ww]
    zt[sy:sy + hh, sx:sx + ww] = cal["zt"][ty:ty + hh, tx:tx + ww]
    mask = mask & np.isfinite(inv)
    z = 1.0 / np.maximum(inv, 1e-5)
    # footing: the lowest mask pixel of each column and the terrain right below it
    ys = np.arange(mh)[:, None]
    low = np.where(mask.any(0), mh - 1 - np.argmax(mask[::-1], 0), -1)
    foot_z = np.full(mw, np.nan)
    for c in np.nonzero(low >= 0)[0]:
        yb = min(low[c] + 1, mh - 1)
        zz = zt[yb, c] if np.isfinite(zt[yb, c]) else np.nan
        if not np.isfinite(zz):     # the sprite reaches the screen bottom: the terrain in the frame below it
            fx = min(int((L["x"] + c + 0.5) * SC.SCALE), TW - 1)
            fy = min(int((L["y"] + low[c] + 1.5) * SC.SCALE), TH - 1)
            zz = rd["zc"][fy, fx]
        foot_z[c] = zz
    good = np.isfinite(foot_z)
    tune = TUNE.get(lid, {})
    if mode == "contact_v1":
        r = _contact_v1(lid, L, {**rd, "_sol1": cal["sol"][1]}, mask, inv, zt, low, tune, flat, contact_px)
        z_c = r["zContact"]
        thick = tune.get("thick", float(np.clip(0.55 * r["widthM"], 2.0, 18.0)))
        upm = r["upright"]
        lowu = np.where(upm.any(0), mh - 1 - np.argmax(upm[::-1], 0), -1)
        cols = np.arange(mw)
        ok = lowu >= 0
        zb = r["z"][lowu[ok], cols[ok]] if ok.any() else np.zeros(0)
        ld = {"mask": mask, "z": r["z"], "zt": zt, "foot_z": np.full(mw, z_c), "low": low,
              "relief": 0.0, "thick": thick, "flat": (flat & mask) if flat is not None else None, "flatRep": flat_rep,
              "widthM": r["widthM"], "calib": {k: cal[k] for k in ("sol", "residRel", "inliers", "bgPx")},
              "footErrM": float(np.nanmedian(np.abs(zb - z_c))) if len(zb) else 0.0,
              "kind": tune.get("kind", "building"), "ground": r["ground"], "upright": r["upright"],
              "windowShare": 0.0, "audit": r["audit"]}
        if flat is not None:
            flat_rep["zM"] = round(float(np.nanmedian(r["z"][flat & mask])), 2)
        return ld
    if tune.get("hung"):
        k = 2 * HUNG_RING_PX + 1
        m8 = mask.astype(np.uint8)
        ring = (cv2.dilate(m8, np.ones((k, k), np.uint8)) > 0) & ~mask & np.isfinite(zt)
        if ring.sum() < 200:
            raise SystemExit(f"{lid}: hung sprite has only {int(ring.sum())} ring px of painted depth")
        foot_z = np.where(low >= 0, float(np.quantile(zt[ring], HUNG_RING_Q)), np.nan)
        good = np.isfinite(foot_z)
    if not good.any() and "floatZm" in tune:
        # a sprite that stands on nothing (a cloud-borne portal): the profile names its depth explicitly
        foot_z[low >= 0] = float(tune["floatZm"])
        good = np.isfinite(foot_z)
    if not good.any():
        raise SystemExit(f"{lid}: no footing found (a floating sprite needs RELIEF_TUNE[{lid!r}]['floatZm'])")
    cols = np.arange(mw)
    foot_z = np.interp(cols, cols[good], foot_z[good])
    width_m = mw * SC.SCALE * 2 * float(np.median(foot_z)) * math.tan(math.radians(47.6) / 2) / H
    relief = tune.get("relief", float(np.clip(0.35 * width_m, 2.0, 12.0)))
    zf = foot_z[None, :].repeat(mh, 0)
    window_share = float((((z < zf - relief) | (z > zf + relief * 0.5)) & mask).sum() / max(mask.sum(), 1))
    z = np.clip(z, zf - relief, zf + relief * 0.5)
    # never behind the painted ground at the same pixel
    z = np.where(np.isfinite(zt), np.minimum(z, zt * 0.997), z)
    # pull the base onto the footing over FOOT_BAND frame px
    dist_up = (low[None, :] - ys) * SC.SCALE
    wf = np.clip(1 - dist_up / FOOT_BAND, 0, 1) * (low[None, :] >= 0)
    z = z * (1 - wf) + zf * wf
    if flat is not None:
        flat = flat & mask
        # a painted plume / cloud carried by the sprite is a flat card at its own median depth (no relief, no cuts)
        zflat = float(np.nanmedian(z[flat]))
        z = np.where(flat, zflat, z)
        flat_rep["zM"] = round(zflat, 2)
    # masked smoothing
    zz = np.where(mask, z, 0).astype(np.float32)
    kk = mask.astype(np.float32)
    z = cv2.GaussianBlur(zz, (0, 0), 0.8) / np.maximum(cv2.GaussianBlur(kk, (0, 0), 0.8), 1e-6)
    z = np.where(mask, z, np.nan)
    thick = tune.get("thick", float(np.clip(0.55 * width_m, 2.0, 18.0)))
    foot_err = float(np.nanmedian(np.abs(z[low[low >= 0], cols[low >= 0]] - foot_z[low >= 0])))
    return {"mask": mask, "z": z, "zt": zt, "foot_z": foot_z, "low": low, "relief": relief, "thick": thick,
            "flat": flat, "flatRep": flat_rep,
            "widthM": width_m, "calib": {k: cal[k] for k in ("sol", "residRel", "inliers", "bgPx")},
            "footErrM": foot_err, "kind": tune.get("kind", "building"), "windowShare": window_share,
            "audit": {"mode": "legacy"}}


# ------------------------------------------------------------------------------------------------ mesh
def _fill_nearest(img: np.ndarray, ok: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt
    _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
    return img[iy, ix]


def orient(v, f, want_n, sgn):
    gn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    flip = (gn * want_n).sum(-1) * sgn < 0
    f = f.copy()
    f[flip] = f[flip][:, [0, 2, 1]]
    return f


def wind_to_camera(v, f, cam_pos, sgn):
    """Wind each triangle toward the camera (its geometric side as seen from cam_pos), whatever its shading normals
    say. For a camera-facing relief every vertex is on its own pixel's ray, so this is the grid's own screen winding.
    Tested by test_town_full3d_winding.py."""
    return orient(v, f, np.asarray(cam_pos, np.float64) - v[f].mean(1), sgn)


def closing_walls(P: np.ndarray, zz: np.ndarray, cut_tris: np.ndarray, cam_pos, sgn: float, u: np.ndarray,
                  v: np.ndarray):
    """Walls that close a sunk depth step from the side (front_surface sink_cuts).

    A cut triangle is split at its largest depth-ratio gap. When two of its vertices are near (the step's near edge),
    a quad is added on those two vertices' own camera rays, from their depth back to the triangle's sunk depth: the
    near part's side wall. It lies in the plane of the two rays, so it projects to zero area at the rest camera (the
    rest pose is unchanged), and it shares its top edge with the near sheet and its bottom edge with the sunk triangle
    (watertight). It is wound toward the step's far side, so a camera that pans or orbits toward that side sees its
    front. Without it the only surface there was the solid's back sheet, wound away from the camera: from the side a
    culling shader (the game's Hex/Lit, _CullMode Back) shows its back as a see-through slit.
    P: (ny, nx, 3) grid positions, zz: (ny, nx) depth along each vertex's ray (P = cam + ray * zz), u / v: (ny, nx)
    texture coordinates (a wall repeats its near edge's texels along its depth; front_surface passes each vertex's
    nearest in-mask pixel centre, so no wall samples across the mask edge). Returns (P, n, u, v, z, tris, edges) of
    the walls: tris index the returned vertices, edges (k, 3) are each wall's near edge and its cut triangle's far vertex
    as grid vertex indices (a, b, far). Tested by test_town_full3d_closing_walls.py."""
    cam_pos = np.asarray(cam_pos, np.float64)
    Pr = P.reshape(-1, 3).astype(np.float64)
    z = zz.ravel().astype(np.float64)
    t = np.asarray(cut_tris).reshape(-1, 3)
    order = np.argsort(z[t], 1)
    ts = np.take_along_axis(t, order, 1)
    zs = z[ts]
    two_near = zs[:, 2] / zs[:, 1] >= zs[:, 1] / zs[:, 0]
    ts, zs = ts[two_near], zs[two_near]
    k = len(ts)
    if k == 0:
        e = np.zeros((0, 3))
        return e, e, np.zeros(0), np.zeros(0), np.zeros(0), np.zeros((0, 3), np.int64), np.zeros((0, 3), np.int64)
    a, b, f = ts[:, 0], ts[:, 1], ts[:, 2]
    zfar = zs[:, 2]
    ta, tb = Pr[a], Pr[b]
    ba = cam_pos + (ta - cam_pos) * (zfar / z[a])[:, None]
    bb = cam_pos + (tb - cam_pos) * (zfar / z[b])[:, None]
    # corners per wall: 0 top a, 1 top b, 2 bottom b, 3 bottom a
    Pw = np.stack([ta, tb, bb, ba], 1).reshape(-1, 3)
    base = (np.arange(k) * 4)[:, None]
    tri = np.concatenate([base + np.array([0, 1, 2]), base + np.array([0, 2, 3])])
    # toward the far side: the far vertex brought to the near edge's depth, minus the edge's midpoint (lateral only)
    zm = 0.5 * (z[a] + z[b])
    far_at = cam_pos + (Pr[f] - cam_pos) * (zm / z[f])[:, None]
    want = far_at - 0.5 * (ta + tb)
    tri = orient(Pw, tri, np.concatenate([want, want]), sgn)
    g = np.cross(Pw[tri[:, 1]] - Pw[tri[:, 0]], Pw[tri[:, 2]] - Pw[tri[:, 0]])
    g /= np.linalg.norm(g, axis=1, keepdims=True) + 1e-12
    g = np.where(((g * np.concatenate([want, want])).sum(1) < 0)[:, None], -g, g)
    nw = np.zeros((k, 3))
    nw += g[:k] + g[k:]
    nw /= np.linalg.norm(nw, axis=1, keepdims=True) + 1e-12
    Nw = np.repeat(nw, 4, 0)
    uf, vf_ = u.ravel(), v.ravel()
    Uw = np.stack([uf[a], uf[b], uf[b], uf[a]], 1).ravel()
    Vw = np.stack([vf_[a], vf_[b], vf_[b], vf_[a]], 1).ravel()
    Zw = np.stack([z[a], z[b], zfar, zfar], 1).ravel()
    return Pw, Nw, Uw, Vw, Zw, tri, np.stack([a, b, f], 1)


def front_surface(L: dict, ld: dict, cam: dict, rig: dict, sun, sgn: float, u_scale: float,
                  sink_cuts: bool = False) -> dict:
    """The camera-facing relief grid shared by both closures: every vertex on its own pixel's ray (registration by
    construction), shading normals bent for the de-lit bake, depth-step triangles cut. u = frame x / width * u_scale.
    sink_cuts: a cut triangle is kept on its own vertices moved to its farthest depth (same rays, uv and normals), so
    the rest pose still shows its texels and the far layer continues under the near one instead of leaving a gap."""
    import conflux_full3d_env as E
    from scipy.ndimage import distance_transform_edt
    mask_n, z_n = ld["mask"], ld["z"]
    mh, mw = mask_n.shape
    fx0, fy0 = L["x"] * SC.SCALE, L["y"] * SC.SCALE
    fw, fh = mw * SC.SCALE, mh * SC.SCALE
    Wi, Hi = int(math.ceil(fw)), int(math.ceil(fh))
    # frame-resolution mask / depth over the sprite box (pixel (i, j) centre = fx0 + i + 0.5)
    mf = cv2.resize(mask_n.astype(np.float32), (Wi, Hi), interpolation=cv2.INTER_LINEAR) > 0.5
    zfill = _fill_nearest(np.where(mask_n, z_n, 0.0), mask_n).astype(np.float32)
    zf = cv2.resize(zfill, (Wi, Hi), interpolation=cv2.INTER_LINEAR)
    xs, ys = grid_axis(fw), grid_axis(fh)
    gx, gy = np.meshgrid(xs, ys)
    valid = mf[gy, gx]
    ring = cv2.dilate(valid.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~valid
    _, (iy, ix) = distance_transform_edt(~mf, return_indices=True)
    px = gx.astype(np.float64) + 0.5
    py = gy.astype(np.float64) + 0.5
    ty, tx = iy[gy, gx], ix[gy, gx]
    vx, vy = px - (tx + 0.5), py - (ty + 0.5)
    nr = np.hypot(vx, vy) + 1e-9
    px = np.where(ring, tx + 0.5 + 0.5 * vx / nr, px)
    py = np.where(ring, ty + 0.5 + 0.5 * vy / nr, py)
    keep = valid | ring
    zz = np.where(valid, zf[gy, gx], zf[ty, tx])
    FX, FY = fx0 + px, fy0 + py
    P = cam["pos"] + T.rays(cam, FX, FY) * zz[..., None]
    # shading normals from a heavily smoothed depth (the relief's shape, not its pixel noise: a sharp per-pixel
    # normal would drive the de-lit albedo past 1 in stripes), leaned toward the viewer
    kv = keep.astype(np.float32)
    zs_ = cv2.GaussianBlur(np.where(keep, zz, 0).astype(np.float32), (0, 0), NORMAL_SIGMA_CELLS)
    zs_ = zs_ / np.maximum(cv2.GaussianBlur(kv, (0, 0), NORMAL_SIGMA_CELLS), 1e-6)
    zs_ = np.where(keep, zs_, zz)
    Ps = cam["pos"] + T.rays(cam, FX, FY) * zs_[..., None]
    dx = np.zeros_like(Ps)
    dy = np.zeros_like(Ps)
    dx[:, 1:-1] = Ps[:, 2:] - Ps[:, :-2]
    dx[:, 0] = Ps[:, 1] - Ps[:, 0]
    dx[:, -1] = Ps[:, -1] - Ps[:, -2]
    dy[1:-1] = Ps[2:] - Ps[:-2]
    dy[0] = Ps[1] - Ps[0]
    dy[-1] = Ps[-1] - Ps[-2]
    n = np.cross(dx, dy)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    to_cam = cam["pos"] - P
    to_cam /= np.linalg.norm(to_cam, axis=-1, keepdims=True) + 1e-12
    n = np.where(((n * to_cam).sum(-1) < 0)[..., None], -n, n)
    n = n * (1 - NORMAL_VIEW_LEAN) + to_cam * NORMAL_VIEW_LEAN
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    # reachability: where the painted colour is brighter than the Hex/Lit irradiance at that normal can return
    # (albedo would clip above 1), bend the normal toward the key light just enough (bisection)
    spr_small = np.asarray(SC.sprite(L).resize((Wi, Hi), Image.BILINEAR)).astype(np.float32)[..., :3] / 255
    need = G.SC_srgb_to_lin(spr_small)[gy, gx] / ALBEDO_MAX
    to_sun = -np.asarray(sun, np.float64)
    lo = np.zeros(n.shape[:2])
    hi = np.ones(n.shape[:2])

    def bend(t):
        m_ = n * (1 - t[..., None]) + to_sun * t[..., None]
        return m_ / (np.linalg.norm(m_, axis=-1, keepdims=True) + 1e-12)

    ok0 = (E.light(n.astype(np.float32), rig, sun) >= need).all(-1)
    for _ in range(10):
        mid = 0.5 * (lo + hi)
        okm = (E.light(bend(mid).astype(np.float32), rig, sun) >= need).all(-1)
        hi = np.where(okm, mid, hi)
        lo = np.where(okm, lo, mid)
    t_b = np.where(ok0, 0.0, hi)
    n = bend(t_b)
    bent_share = float((t_b > 0)[valid].mean())
    nx_ = len(xs)
    j, i = np.meshgrid(np.arange(len(ys) - 1), np.arange(nx_ - 1), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    tris = tris[keep.ravel()[tris].all(1)]
    zr = zz.ravel()[tris]
    cut = zr.max(1) / zr.min(1) > CUT_RATIO
    cut_tris = tris[cut]
    tris = tris[~cut]
    used = np.unique(tris)
    remap = np.full(P.shape[0] * P.shape[1], -1)
    remap[used] = np.arange(len(used))
    Pf = P.reshape(-1, 3)[used]
    Nf = n.reshape(-1, 3)[used]
    Zf = zz.ravel()[used]
    U = (px.ravel()[used] / fw) * u_scale
    Vv = 1 - py.ravel()[used] / fh
    tf = remap[tris]
    if sink_cuts and len(cut_tris):
        ct = cut_tris.ravel()
        zmax = np.repeat(zz.ravel()[cut_tris].max(1), 3)
        Pr = P.reshape(-1, 3)[ct]
        Ps_ = cam["pos"] + (Pr - cam["pos"]) * (zmax / zz.ravel()[ct])[:, None]
        base = len(Pf)
        Pf = np.concatenate([Pf, Ps_])
        Nf = np.concatenate([Nf, n.reshape(-1, 3)[ct]])
        Zf = np.concatenate([Zf, zmax])
        U = np.concatenate([U, (px.ravel()[ct] / fw) * u_scale])
        Vv = np.concatenate([Vv, 1 - py.ravel()[ct] / fh])
        tf = np.concatenate([tf, base + np.arange(len(ct)).reshape(-1, 3)])
    # wind every front triangle toward the camera (its geometric facing: every vertex is on its own pixel's ray), not
    # toward its shading normal. The shading normals are smoothed and bent toward the key light, so on steep depth
    # faces they disagree with the triangle's own side; orienting by them wound ~8% of a keep's front triangles
    # away from the camera, which a back-face-flipping shader (the lab HexLit: Cull Off, normal * (front ? 1 : -1))
    # shades black (1 px vertical bars) and a back-face-culling one drops. Winding only: P, n, uv are unchanged.
    tf = wind_to_camera(Pf, tf, cam["pos"], sgn)
    n_walls = 0
    wall_grid = np.zeros(0, np.int64)
    wall_edge_grid = np.zeros((0, 3), np.int64)
    if sink_cuts and len(cut_tris):
        # closing walls on the sunk steps' near edges: wound by closing_walls (toward the far side), not by the camera
        # (they are edge-on at the rest camera, where the camera side is undefined)
        # texels: each wall corner samples its near vertex's nearest in-mask pixel centre (a silhouette ring vertex
        # would otherwise sample across the mask edge), repeated along the wall's depth; build_solid then puts each
        # wall on one existing texel of the building (stronghold_full3d_solids.wall_texels)
        Pw, Nw, Uw, Vw, Zw, tw, we = closing_walls(P, zz, cut_tris, cam["pos"], sgn, (tx + 0.5) / fw * u_scale,
                                                   1 - (ty + 0.5) / fh)
        n_walls = len(tw) // 2
        wall_grid = np.unique(we[:, :2])
        wall_edge_grid = we
        base = len(Pf)
        Pf = np.concatenate([Pf, Pw.astype(Pf.dtype)])
        Nf = np.concatenate([Nf, Nw.astype(Nf.dtype)])
        Zf = np.concatenate([Zf, Zw.astype(Zf.dtype)])
        U = np.concatenate([U, Uw])
        Vv = np.concatenate([Vv, Vw])
        tf = np.concatenate([tf, base + tw])
    return {"P": P, "n": n, "zz": zz, "keep": keep, "valid": valid, "px": px, "py": py, "FX": FX, "FY": FY,
            "nx": nx_, "used": used, "remap": remap, "Pf": Pf, "Nf": Nf, "Zf": Zf, "U": U, "Vv": Vv, "tf": tf,
            "cut": cut, "cutTris": cut_tris, "closingWalls": n_walls, "wallGrid": wall_grid, "wallEdgeGrid": wall_edge_grid, "bentShare": bent_share, "fw": fw, "fh": fh, "Wi": Wi, "Hi": Hi}


def grid_axis(extent: float) -> np.ndarray:
    """The relief grid's vertex columns (or rows) in box px: 0, GRID, 2 GRID, ..., ceil(extent) - 1."""
    Wi = int(math.ceil(extent))
    return np.unique(np.r_[np.arange(0, Wi, GRID), Wi - 1])


def grid_to_texels(g: np.ndarray, fw: float, fh: float, tw_: int, th_: int) -> np.ndarray:
    """Resample a per-vertex relief-grid field to texels (bilinear), registered on the vertices' frame positions."""
    xs, ys = grid_axis(fw), grid_axis(fh)
    if g.shape[:2] != (len(ys), len(xs)):
        raise SystemExit(f"grid_to_texels: field {g.shape[:2]} is not the relief grid {(len(ys), len(xs))}")
    cx = np.interp((np.arange(tw_) + 0.5) * fw / tw_, xs + 0.5, np.arange(len(xs))).astype(np.float32)
    cy = np.interp((np.arange(th_) + 0.5) * fh / th_, ys + 0.5, np.arange(len(ys))).astype(np.float32)
    mx, my = np.meshgrid(cx, cy)
    return cv2.remap(g, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def front_albedo(L: dict, mask_n: np.ndarray, n: np.ndarray, fw: float, fh: float, rig: dict, sun):
    """The sprite (static plate) de-lit by the Hex/Lit irradiance of the front's shading normals (linear albedo)."""
    import conflux_full3d_env as E
    spr = SC.albedo_sprite(L)
    tw_, th_ = int(round(fw * BUILD_SCALE)), int(round(fh * BUILD_SCALE))
    big = np.asarray(spr.resize((tw_, th_), Image.LANCZOS)).astype(np.float32) / 255
    mbig = cv2.resize(mask_n.astype(np.float32), (tw_, th_), interpolation=cv2.INTER_LINEAR) > 0.5
    rgb = _fill_nearest(big[..., :3], mbig)
    lin = G.SC_srgb_to_lin(rgb)
    # normals at texel resolution, each texel sampling the grid at its own frame position: vertex k sits at box px
    # xs[k] + 0.5 (xs = 0, GRID, 2 GRID, ..., Wi - 1, as in front_surface) and texel j's centre at (j + 0.5) fw / tw_.
    # (A plain resize spread the grid evenly over the box and drifted up to ~1.3 px from the rendered normals, so a
    # normal crease de-lit one texel column with the neighbouring facet's light: 1-2 px overbright / dark lines.)
    ngrid = grid_to_texels(n.astype(np.float32), fw, fh, tw_, th_)
    ngrid /= np.linalg.norm(ngrid, axis=-1, keepdims=True) + 1e-9
    Lr = E.light(ngrid, rig, sun)
    front = np.clip(lin / np.maximum(Lr, 0.03), 0, 1)
    clipped = float(((lin / np.maximum(Lr, 0.03)) > 1).any(-1)[mbig].mean())
    return front, mbig, clipped


def build_mesh(lid: str, L: dict, ld: dict, cam: dict, rig: dict, sun, sgn: float) -> dict:
    """Closed relief mesh (painting world) + atlas texture (linear albedo) for one layer (the 'relief' closure)."""
    fs = front_surface(L, ld, cam, rig, sun, sgn, 0.5)
    Pf, Nf, Zf, U, Vv, tf, n = fs["Pf"], fs["Nf"], fs["Zf"], fs["U"], fs["Vv"], fs["tf"], fs["n"]
    fw, fh, cut, bent_share = fs["fw"], fs["fh"], fs["cut"], fs["bentShare"]
    mask_n = ld["mask"]
    # closing by hand: extrude along each vertex's camera ray (edge-on at the rest pose) by the layer thickness
    thick = ld["thick"]
    Pb = cam["pos"] + (Pf - cam["pos"]) * ((Zf + thick) / Zf)[:, None]
    fwd_h = T.heading(cam)[0]
    Nb = np.tile(fwd_h, (len(Pb), 1))
    nv = len(Pf)
    # boundary edges of the front
    e = np.concatenate([tf[:, [0, 1]], tf[:, [1, 2]], tf[:, [2, 0]]])
    es = np.sort(e, 1)
    key = es[:, 0].astype(np.int64) * (nv + 1) + es[:, 1]
    uniq, cnt = np.unique(key, return_counts=True)
    bset = set(uniq[cnt == 1].tolist())
    be = e[[k in bset for k in key]]
    # side quads: new vertices so their normals are the side's own
    ctr = Pf.mean(0)
    sP, sN, sUV, sT = [], [], [], []
    for k, (va, vb) in enumerate(be):
        q = [Pf[va], Pf[vb], Pb[vb], Pb[va]]
        nn = np.cross(q[1] - q[0], q[3] - q[0])
        nn /= np.linalg.norm(nn) + 1e-12
        mid = 0.25 * (q[0] + q[1] + q[2] + q[3])
        if nn @ (mid - ctr) < 0:
            nn = -nn
        base = nv * 2 + 4 * k
        sP += q
        sN += [nn] * 4
        ua = (U[va] + 0.5, Vv[va])
        ub = (U[vb] + 0.5, Vv[vb])
        sUV += [ua, ub, ub, ua]
        sT.append((base, base + 1, base + 2, nn))
    V = np.concatenate([Pf, Pb] + ([np.array(sP)] if sP else []))
    N = np.concatenate([Nf, Nb] + ([np.array(sN)] if sN else []))
    UV = np.concatenate([np.stack([U, Vv], 1), np.stack([U + 0.5, Vv], 1)] + ([np.array(sUV)] if sUV else []))
    back = orient(V, tf + nv, np.tile(fwd_h, (len(tf), 1)), sgn)
    side = []
    for base, b1, b2, nn in sT:
        side += [orient(V, np.array([[base, b1, b2], [base, b2, base + 3]]), np.array([nn, nn]), sgn)]
    F = np.concatenate([tf, back] + side)
    # texture atlas: front (de-lit sprite) | back (darkened, blurred). A part that moves as an Fx_ piece (the
    # windmill's sails) is replaced by its DEF frames' median, so it is not painted twice.
    front, mbig, clipped = front_albedo(L, mask_n, n, fw, fh, rig, sun)
    th_ = front.shape[0]
    # sides / back: extruded quads carry one texel column along their whole depth, so per-pixel art would streak;
    # they get the building's own per-row median colour (a plain wall in its own strata), darkened, with a little
    # of the front's grain
    rowmed = np.zeros((th_, 3), np.float32)
    for r in range(th_):
        m_ = mbig[r]
        rowmed[r] = np.median(front[r][m_], 0) if m_.sum() >= 3 else np.nan
    ok_r = np.isfinite(rowmed[:, 0])
    if not ok_r.any():
        raise SystemExit(f"{lid}: empty mask rows")
    rr_ = np.arange(th_)
    rowmed = np.stack([np.interp(rr_, rr_[ok_r], rowmed[ok_r, c]) for c in range(3)], 1)
    rowmed = cv2.GaussianBlur(rowmed[:, None, :], (0, 0), sigmaX=0.1, sigmaY=3.0)[:, 0, :]
    grain = front.mean(-1, keepdims=True) / np.maximum(cv2.GaussianBlur(front.mean(-1), (0, 0), 6)[..., None], 1e-3)
    backt = np.clip(rowmed[:, None, :] * (0.75 + 0.25 * np.clip(grain, 0.5, 1.5)) * SIDE_DARKEN, 0, 1)
    atlas = np.concatenate([front, backt], 1).astype(np.float32)
    return {"P": V, "n": N, "uv": UV.astype(np.float32), "tris": F.astype(np.int32), "albedo": atlas,
            "texelsPerPx": float(BUILD_SCALE), "frontTris": int(len(tf)), "sideQuads": int(len(be)),
            "clippedShare": clipped, "bentShare": bent_share, "cutTris": int(cut.sum()), "texSize": [atlas.shape[1], atlas.shape[0]]}


# ------------------------------------------------------------------------------------------------ edge fray
def _apply_fray_drop(lid: str, m: dict, F: np.ndarray, drop: np.ndarray, cam: dict) -> dict:
    """Remove the fray's triangles. A solid (build_solid) is closed along the cut by edge-on cap walls
    (stronghold_full3d_solids.cap_cut); a relief shell keeps the plain removal."""
    if "solid" in m:
        import stronghold_full3d_solids as SO
        return SO.cap_cut(lid, m, F, drop, cam)
    m["tris"] = F[~drop].astype(np.int32)
    nf = int(m["frontTris"])
    m["frontTris"] = int((~drop[:nf]).sum()) if nf <= len(F) else nf
    return {}


# A layer whose HoMM3 sprite is cut by the painting's right frame edge (x = TW) ends in a straight vertical line that
# the frame extension then shows at rest (the seam-line gate, town_full3d_tex seam_line). Opt-in per faction profile
# (EDGE_FRAY = {layer id: {"minPx", "maxPx", "sigmaPx"}}, frame px; absent = no layer is touched): the mesh's triangles
# (front, back, ground) whose rest-camera centroid lies right of a ragged line TW - d(y) are removed, d(y) a smooth
# per-row noise in [minPx, maxPx] (seeded by the layer id), so the painted background under the sprite (which the
# extension bridge continues) shows through a ragged boundary. Geometry only: no texel is recoloured.
def edge_fray(lid: str, m: dict, cam: dict, fray: dict) -> dict:
    import zlib
    from scipy.ndimage import gaussian_filter1d
    lo, hi, sig = float(fray["minPx"]), float(fray["maxPx"]), float(fray["sigmaPx"])
    if not 0 <= lo < hi:
        raise SystemExit(f"EDGE_FRAY {lid}: need 0 <= minPx < maxPx, got {fray}")
    P, F = np.asarray(m["P"], np.float64), np.asarray(m["tris"])
    px, py, _ = T.project(cam, P)
    cx, cy = px[F].mean(1), py[F].mean(1)
    if cx.max() < SC.TW - hi:
        raise SystemExit(f"EDGE_FRAY {lid}: the layer does not reach the fray band (max x {cx.max():.1f} < "
                         f"{SC.TW - hi:.1f}); remove it from the profile")
    rng = np.random.default_rng(zlib.crc32(lid.encode()))
    n = gaussian_filter1d(rng.standard_normal(SC.H + 64), sig)[32:32 + SC.H]
    n = n / max(float(n.std()), 1e-9)
    d = lo + (hi - lo) * np.clip((n + 1.5) / 3.0, 0, 1)
    cut = SC.TW - d[np.clip(np.round(cy).astype(int), 0, SC.H - 1)]
    drop = cx > cut
    rows = fray.get("rows")
    if rows is not None:
        # optional frame-row band: only the part of the layer between these rows is frayed (the rest keeps its edge)
        drop &= (cy >= float(rows[0])) & (cy < float(rows[1]))
    if drop.all():
        raise SystemExit(f"EDGE_FRAY {lid}: every triangle is right of the fray line")
    cap = _apply_fray_drop(lid, m, F, drop, cam)
    return {"minPx": lo, "maxPx": hi, "sigmaPx": sig, "rows": rows, "droppedTris": int(drop.sum()),
            "keptTris": int((~drop).sum()), **cap,
            "method": "triangles right of TW - d(y) removed (geometry only)"}


# The same at the painting's BOTTOM frame edge (y = TH): opt-in per faction profile (EDGE_FRAY_BOTTOM = {layer id:
# {"minPx", "maxPx", "sigmaPx"}}, frame px; absent = no layer is touched). A sprite cut by the bottom edge (Castle's
# market row, Rampart's fountain) ends in a straight horizontal line on the extension's ground (seam-line gate, y =
# TH); the triangles whose rest-camera centroid lies below TH - d(x) are removed, d(x) a smooth per-column noise in
# [minPx, maxPx] seeded by the layer id (a different stream from the right edge's). Geometry only.
def edge_fray_bottom(lid: str, m: dict, cam: dict, fray: dict) -> dict:
    import zlib
    from scipy.ndimage import gaussian_filter1d
    lo, hi, sig = float(fray["minPx"]), float(fray["maxPx"]), float(fray["sigmaPx"])
    if not 0 <= lo < hi:
        raise SystemExit(f"EDGE_FRAY_BOTTOM {lid}: need 0 <= minPx < maxPx, got {fray}")
    P, F = np.asarray(m["P"], np.float64), np.asarray(m["tris"])
    px, py, _ = T.project(cam, P)
    cx, cy = px[F].mean(1), py[F].mean(1)
    if cy.max() < SC.TH - hi:
        raise SystemExit(f"EDGE_FRAY_BOTTOM {lid}: the layer does not reach the fray band (max y {cy.max():.1f} < "
                         f"{SC.TH - hi:.1f}); remove it from the profile")
    rng = np.random.default_rng(zlib.crc32((lid + ":bottom").encode()))
    n = gaussian_filter1d(rng.standard_normal(SC.W + 64), sig)[32:32 + SC.W]
    n = n / max(float(n.std()), 1e-9)
    d = lo + (hi - lo) * np.clip((n + 1.5) / 3.0, 0, 1)
    cut = SC.TH - d[np.clip(np.round(cx).astype(int), 0, SC.W - 1)]
    drop = cy > cut
    if drop.all():
        raise SystemExit(f"EDGE_FRAY_BOTTOM {lid}: every triangle is below the fray line")
    cap = _apply_fray_drop(lid, m, F, drop, cam)
    return {"minPx": lo, "maxPx": hi, "sigmaPx": sig, "droppedTris": int(drop.sum()), "keptTris": int((~drop).sum()), **cap,
            "method": "triangles below TH - d(x) removed (geometry only)"}


# The same at the painting's TOP frame edge (y = 0): opt-in per faction profile (EDGE_FRAY_TOP = {layer id: {"minPx",
# "maxPx", "sigmaPx"}}, frame px; absent = no layer is touched). A sprite cut by the top edge (Necropolis tbncspec's
# storm cloud) ends in a straight horizontal line against the dome sky once a pan pose looks above the painting; the
# triangles whose rest-camera centroid lies above d(x) are removed, d(x) a smooth per-column noise in [minPx, maxPx]
# seeded by the layer id (its own stream). Geometry only.
def edge_fray_top(lid: str, m: dict, cam: dict, fray: dict) -> dict:
    import zlib
    from scipy.ndimage import gaussian_filter1d
    lo, hi, sig = float(fray["minPx"]), float(fray["maxPx"]), float(fray["sigmaPx"])
    if not 0 <= lo < hi:
        raise SystemExit(f"EDGE_FRAY_TOP {lid}: need 0 <= minPx < maxPx, got {fray}")
    P, F = np.asarray(m["P"], np.float64), np.asarray(m["tris"])
    px, py, _ = T.project(cam, P)
    cx, cy = px[F].mean(1), py[F].mean(1)
    if cy.min() > hi:
        raise SystemExit(f"EDGE_FRAY_TOP {lid}: the layer does not reach the fray band (min y {cy.min():.1f} > "
                         f"{hi:.1f}); remove it from the profile")
    rng = np.random.default_rng(zlib.crc32((lid + ":top").encode()))
    n = gaussian_filter1d(rng.standard_normal(SC.W + 64), sig)[32:32 + SC.W]
    n = n / max(float(n.std()), 1e-9)
    d = lo + (hi - lo) * np.clip((n + 1.5) / 3.0, 0, 1)
    drop = cy < d[np.clip(np.round(cx).astype(int), 0, SC.W - 1)]
    if drop.all():
        raise SystemExit(f"EDGE_FRAY_TOP {lid}: every triangle is above the fray line")
    cap = _apply_fray_drop(lid, m, F, drop, cam)
    return {"minPx": lo, "maxPx": hi, "sigmaPx": sig, "droppedTris": int(drop.sum()), "keptTris": int((~drop).sum()), **cap,
            "method": "triangles above d(x) removed (geometry only)"}


# ------------------------------------------------------------------------------------------------ stage
def stage_buildings(sc, rd: dict, prefix: str, only=None, method: str = "relief", back_fill: bool = False) -> dict:
    """One prefab per reachable layer with a single Mesh_Body piece. Fails closed on a layer without a mesh.
    method: 'relief' (the installed extrude-to-flat-back shell), 'solid' (stronghold_full3d_solids) or 'solid_parts'
    (solid with part separation on the layers in stronghold_full3d_solids.PARTS_LAYERS; the rest close as 'solid').
    back_fill (solid methods only): the back half uses the edge-filled texture on the layers in
    stronghold_full3d_solids.BACK_FILL_LAYERS."""
    lays = SC.layers()
    rep = {}
    if method not in ("relief", "solid", "solid_parts"):
        raise SystemExit(f"buildings: unknown method {method}")
    for lid in SC.reachable_layers():
        if only and lid not in only:
            continue
        L = lays[lid]
        ld = layer_depth(lid, L, rd)
        lmethod = method
        if method in ("solid", "solid_parts"):
            import stronghold_full3d_solids as SO
            use_parts = method == "solid_parts" and (SO.PARTS_LAYERS is None or lid in SO.PARTS_LAYERS)
            lmethod = "solid_parts" if use_parts else "solid"
            use_fill = back_fill and (SO.BACK_FILL_LAYERS is None or lid in SO.BACK_FILL_LAYERS)
            m = SO.build_solid(lid, L, ld, sc.cam, sc.rig, sc.sun, 1.0, rd["floor"], parts=use_parts,
                               fill_back=use_fill)
        else:
            m = build_mesh(lid, L, ld, sc.cam, sc.rig, sc.sun, 1.0)
        if m["frontTris"] == 0:
            raise SystemExit(f"{lid}: empty mesh")
        fray = (getattr(SC.FP, "EDGE_FRAY", None) or {}).get(lid)
        fray_rep = edge_fray(lid, m, sc.cam, fray) if fray else None
        frayb = (getattr(SC.FP, "EDGE_FRAY_BOTTOM", None) or {}).get(lid)
        frayb_rep = edge_fray_bottom(lid, m, sc.cam, frayb) if frayb else None
        frayt = (getattr(SC.FP, "EDGE_FRAY_TOP", None) or {}).get(lid)
        frayt_rep = edge_fray_top(lid, m, sc.cam, frayt) if frayt else None
        sc.add_bin(prefix + lid, f"Mesh_Body_{lid}", m["P"], m["n"], m["uv"], m["tris"], m["albedo"])
        if "wallEdges" in m:
            # closing-wall near edges in the prefab frame, for the Unity rest check (town_full3d_wall_rest)
            sc.wall_edges[lid] = sc.local(m["wallEdges"].reshape(-1, 3)).reshape(-1, 2, 3)
        rep[lid] = {"kind": ld["kind"], "footZm": round(float(np.median(ld["foot_z"])), 1),
                    "footErrM": round(ld["footErrM"], 3), "reliefM": ld["relief"], "thickM": ld["thick"],
                    "widthM": round(ld["widthM"], 1), "calib": {k: (round(v, 4) if isinstance(v, float) else v)
                                                              for k, v in ld["calib"].items() if k != "sol"},
                    "tris": int(len(m["tris"])), "frontTris": m["frontTris"], "sideQuads": m["sideQuads"],
                    "texSize": m["texSize"], "texelsPerPx": m["texelsPerPx"],
                    "delitClippedShare": round(m["clippedShare"], 4), "method": lmethod,
                    "depthAudit": depth_audit(ld),
                    **({"solid": m["solid"]} if "solid" in m else {}),
                    **({"edgeFray": fray_rep} if fray_rep else {}),
                    **({"edgeFrayBottom": frayb_rep} if frayb_rep else {}),
                    **({"edgeFrayTop": frayt_rep} if frayt_rep else {})}
        print(lid, rep[lid], flush=True)
    sc.report["buildings"] = rep
    return rep
