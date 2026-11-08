"""Per-faction masks of the full-3D town lane: the painted sky, the outpaint's own sky, and the painted (non-layer)
props such as background huts. Each rule is named in the faction profile (SKY_MASK, TEX["propMask"]); an unknown or
missing rule stops the stage. There is no default rule and no fallback to another faction's rule.

Sky rules (profile SKY_MASK["rule"], frame-rect painting uint8 RGB, rows < horizon + 4 only):
  blue       blue and bright (b > r + 12, b > 140), connected to the top edge: the lane's original Stronghold rule.
  lab        CIELAB box from the profile (lMin/lMax, aMin/aMax, bMin/bMax), connected to the top edge, optional
             maxHoMM3Y cap on the rows: for skies that are not blue (sunset, aurora, red haze, overcast). Optional
             daMax: also the lane's DA V2 Large disparity (depth/da_large.npy) < daMax, for snow peaks against cloud.
             Optional belowHorizon {capHoMM3Y, lMin}: rows past the horizon cap down to capHoMM3Y count too where
             L* >= lMin (a sky painted below the horizon down to a dark ridge).
  none       no sky (an underground town): an empty mask.
Extension sky (the SD fill's continuation of the painted sky, graded never): profile SKY_MASK["extension"] as a CIELAB
box connected to the canvas top; {"rule": "none"} for a scene without sky. Optional stdMax (with stdWin, default 11):
also a local L* standard deviation below stdMax (a smooth sky against rock of the same colour).
Prop rules (profile TEX["propMask"]):
  lowchroma_white   low-chroma components with enough white pixels (whitewashed walls, pale roofs), dilated.
  hue_white         a CIELAB hue-angle band (warm roof tiles and timber: hueMin..hueMax deg, chroma > chromaMin,
                    L* < lMax) or white (L* > whiteL, chroma < whiteChromaMax), closed, components > minArea, dilated,
                    frame rows >= minRow only: roofed cottages on a green meadow. Optional darkL: dark pixels
                    (L* < darkL) touching a kept component join it and enclosed holes are filled (shadow sides).
  none              no painted props (every house in the painting is a building layer): an empty mask. The profile
                    says why ({"rule": "none", "reason": ...}).
  da_bump           props that share the ground's colours (dark roofs on a dark lava floor): the lane's DA V2 Large
                    disparity (depth/da_large.npy) standing above its own grey opening (openPx square, blurred
                    openPx/4) by more than relMin of it, frame rows >= minRow; rows where more than rowFracMax of
                    the row passes are dropped (the opening's reflect border lifts the bottom rows); components with
                    area >= minArea, width <= maxWidth (wider bumps are hills) and height >= minHeight are kept,
                    each carried down by extendDown x its height (a roof pops out of the floor's disparity, the walls
                    below it do not), then dilated.
  boxes             hand-traced boxes (HoMM3 px x0, y0, x1, y1; profile "boxes"), dilated: props that share the
                    ground's colours AND whose disparity bump fails (Bulwark's snow-dusted yurts on blue snow, cut by
                    the bottom edge). The profile says why no colour or disparity rule holds.
"""
from __future__ import annotations

import cv2
import numpy as np


def _top_connected(m: np.ndarray, conn: int = 4) -> np.ndarray:
    n, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=conn)
    top = set(np.unique(lab[0][m[0]]).tolist()) - {0}
    return np.isin(lab, list(top))


def sky_mask(paint: np.ndarray, horizon_py: float, spec: dict) -> np.ndarray:
    rule = spec.get("rule") if isinstance(spec, dict) else None
    if rule == "blue":
        f = cv2.GaussianBlur(paint.astype(np.float32), (0, 0), 1.2)
        r, g, b = f[..., 0], f[..., 1], f[..., 2]
        blue = (b > r + 12) & (b > 140)
        rows = np.arange(paint.shape[0])[:, None]
        blue &= rows < horizon_py + 4
        m = _top_connected(blue)
        return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
    if rule == "lab":
        f = cv2.GaussianBlur(paint.astype(np.float32), (0, 0), 1.2) / 255
        L = cv2.cvtColor(f, cv2.COLOR_RGB2LAB)
        m = np.ones(paint.shape[:2], bool)
        for c, k in enumerate("lab"):
            m &= (L[..., c] >= spec.get(f"{k}Min", -1e9)) & (L[..., c] <= spec.get(f"{k}Max", 1e9))
        rows = np.arange(paint.shape[0])[:, None]
        cap = horizon_py + 4 if "maxHoMM3Y" not in spec else min(horizon_py + 4, spec["maxHoMM3Y"] * 1.8)
        if "belowHorizon" in spec:
            # opt-in: painted sky that continues below the horizon row to a dark far ridge (Inferno: crimson sky to
            # frame row ~297 at the right edge, carried by the relief as a slab that stopped at x = TW). Rows from
            # the horizon cap down to capHoMM3Y are sky only where L* >= lMin (the ridge is L* ~0, the sky 13-21)
            bh = spec["belowHorizon"]
            low = (rows >= cap) & (rows < bh["capHoMM3Y"] * 1.8) & (L[..., 0] >= bh["lMin"])
            m &= (rows < cap) | low
        else:
            m &= rows < cap
        if "daMax" in spec:
            # snow peaks share the clouds' colour: the lane's own Depth Anything V2 Large disparity of the painting
            # (stronghold_full3d_depth, frame rect) separates them (sky reads 0, the nearest peak > 100)
            import stronghold_full3d_common as SC
            da = np.load(SC.DATA / "depth" / "da_large.npy")
            if da.shape != m.shape:
                raise SystemExit(f"town_full3d_masks: da_large {da.shape} is not the painting rect {m.shape}")
            m &= da < spec["daMax"]
        m = _top_connected(m)
        return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
    if rule == "none":
        return np.zeros(paint.shape[:2], bool)
    raise SystemExit(f"town_full3d_masks: sky rule {rule!r} is not blue / lab / none (profile SKY_MASK)")


def extension_sky(lab: np.ndarray, rect: np.ndarray, spec: dict) -> np.ndarray:
    """The outpaint canvas's own sky (CIELAB float canvas, rect = painted-rect mask): the profile's box, connected to
    the canvas's top 40 rows, closed 5x5. Rows >= maxRow are never sky. Optional stdMax: smooth pixels only."""
    e = spec.get("extension") if isinstance(spec, dict) else None
    if e is None:
        raise SystemExit("town_full3d_masks: profile SKY_MASK has no 'extension' rule")
    if e.get("rule") == "none":
        return np.zeros(lab.shape[:2], bool)
    skyish = np.ones(lab.shape[:2], bool)
    for c, k in enumerate("lab"):
        if f"{k}Min" in e:
            skyish &= lab[..., c] > e[f"{k}Min"]
        if f"{k}Max" in e:
            skyish &= lab[..., c] < e[f"{k}Max"]
    if "stdMax" in e:
        # the fill's peaks share the sky's colour (Bulwark: dark teal night over dark teal rock): the sky is smooth,
        # the rock is not. Local L* standard deviation over a stdWin square (sky p95 0.7, peaks p50 4.7..8.1)
        k = int(e.get("stdWin", 11))
        L = lab[..., 0].astype(np.float32)
        m1, m2 = cv2.blur(L, (k, k)), cv2.blur(L * L, (k, k))
        box = skyish.copy()
        skyish &= np.sqrt(np.maximum(m2 - m1 * m1, 0)) < e["stdMax"]
    skyish = skyish.astype(np.uint8)
    skyish[e["maxRow"]:] = 0
    n, labc, st, _ = cv2.connectedComponentsWithStats(skyish)
    top = set(np.unique(labc[:40]).tolist()) - {0}
    sky_e = np.isin(labc, list(top))
    if "stdMax" in e:
        # the window's own reach: give back the stdWin // 2 halo round the rock (and the stars' holes), in the box only
        grow = cv2.dilate(sky_e.astype(np.uint8), np.ones((k | 1, k | 1), np.uint8)) > 0
        sky_e = grow & box
        sky_e[e["maxRow"]:] = False
    sky_e &= ~rect
    return cv2.morphologyEx(sky_e.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0


def prop_mask(paint: np.ndarray, spec: dict) -> np.ndarray:
    """Painted (non-layer) props at the frame rect (1440x673): background huts and houses."""
    rule = spec.get("rule") if isinstance(spec, dict) else None
    if rule == "none":
        return np.zeros(paint.shape[:2], bool)
    if rule == "hue_white":
        lab = cv2.cvtColor(cv2.GaussianBlur(paint.astype(np.float32), (0, 0), 1.0) / 255, cv2.COLOR_RGB2LAB)
        hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
        chroma = np.hypot(lab[..., 1], lab[..., 2])
        roof = (hue > spec["hueMin"]) & (hue < spec["hueMax"]) & (chroma > spec["chromaMin"]) & (lab[..., 0] < spec["lMax"])
        white = (lab[..., 0] > spec["whiteL"]) & (chroma < spec["whiteChromaMax"])
        m = cv2.morphologyEx((roof | white).astype(np.uint8), cv2.MORPH_CLOSE,
                             np.ones((spec["close"], spec["close"]), np.uint8))
        n, lb, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        keep = np.where(stats[:, cv2.CC_STAT_AREA] > spec["minArea"])[0]
        keep = keep[keep > 0]
        seed = np.isin(lb, keep)
        if "darkL" in spec:
            # the cottages' shadow sides, windows and eaves are dark, not warm: dark pixels join a kept component
            # when they touch it, then each component's enclosed holes are filled
            grow = (seed | (lab[..., 0] < spec["darkL"])).astype(np.uint8)
            n2, lb2 = cv2.connectedComponents(grow, connectivity=8)
            seed = np.isin(lb2, np.unique(lb2[seed]))
            seed &= lb2 > 0
            ff = np.pad(~seed, 1, constant_values=True).astype(np.uint8)
            cv2.floodFill(ff, None, (0, 0), 2)
            seed |= ff[1:-1, 1:-1] == 1
        big = cv2.dilate(seed.astype(np.uint8), np.ones((spec["dilate"], spec["dilate"]), np.uint8)) > 0
        return big & (np.arange(paint.shape[0])[:, None] >= spec["minRow"])
    if rule == "da_bump":
        return _da_bump(paint, spec)
    if rule == "boxes":
        s = paint.shape[1] / 800.0   # HoMM3 px -> this image's px (the frame rect: 1.8)
        m = np.zeros(paint.shape[:2], np.uint8)
        for x0, y0, x1, y1 in spec["boxes"]:
            m[int(round(y0 * s)):int(round(y1 * s)), int(round(x0 * s)):int(round(x1 * s))] = 1
        return cv2.dilate(m, np.ones((spec["dilate"], spec["dilate"]), np.uint8)) > 0
    if rule != "lowchroma_white":
        raise SystemExit(f"town_full3d_masks: prop rule {rule!r} is not lowchroma_white / hue_white / da_bump / boxes / "
                         "none (profile TEX['propMask'])")
    lab = cv2.cvtColor(paint.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    low = ((chroma < spec["chromaMax"]) | ((lab[..., 0] > spec["brightL"]) & (chroma < spec["brightChromaMax"])))
    low = cv2.morphologyEx(low.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((spec["close"], spec["close"]), np.uint8))
    n, lb, stats, _ = cv2.connectedComponentsWithStats(low, 8)
    white = ((lab[..., 0] > spec["whiteL"]) & (chroma < spec["whiteChromaMax"]))
    wc = np.bincount(lb.ravel(), weights=white.ravel(), minlength=n)
    keep = np.where((stats[:, cv2.CC_STAT_AREA] > spec["minArea"]) & (wc >= spec["minWhite"]))[0]
    keep = keep[keep > 0]
    big = np.isin(lb, keep)
    return cv2.dilate(big.astype(np.uint8), np.ones((spec["dilate"], spec["dilate"]), np.uint8)) > 0


def _da_bump(paint: np.ndarray, spec: dict) -> np.ndarray:
    """Prop rule da_bump (module doc): painted props found as disparity bumps, not by colour."""
    from scipy.ndimage import grey_opening
    import stronghold_full3d_common as SC
    da = np.load(SC.DATA / "depth" / "da_large.npy").astype(np.float32)
    if da.shape != paint.shape[:2]:
        raise SystemExit(f"town_full3d_masks: da_large {da.shape} is not the painting rect {paint.shape[:2]}")
    k = int(spec["openPx"])
    base = cv2.GaussianBlur(grey_opening(da, size=(k, k)), (0, 0), k / 4)
    m = (da - base) / np.maximum(base, 1.0) > spec["relMin"]
    m &= np.arange(da.shape[0])[:, None] >= spec["minRow"]
    m[m.mean(1) > spec["rowFracMax"]] = False
    n, lb, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    out = np.zeros(m.shape, bool)
    for i in range(1, n):
        _, _, w, h, a = st[i]
        if a < spec["minArea"] or w > spec["maxWidth"] or h < spec["minHeight"]:
            continue
        c = lb == i
        cc = c.copy()
        for d in range(1, int(round(h * spec["extendDown"])) + 1):
            cc[d:] |= c[:-d]
        out |= cc
    return cv2.dilate(out.astype(np.uint8), np.ones((spec["dilate"], spec["dilate"]), np.uint8)) > 0
