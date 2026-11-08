"""Very slow sky drift of the full-3D town lane (profile SKY_ANIM).

Vanilla cityHuman2 does not animate its sky (a static panoramic skybox, _Rotation fixed, no time parameter; its cloud
materials are building VFX), so the lane owns the drift. Modes, one per profile, each with its reason:
  drift     Sky_Drift: a full 360 deg band on the sky dome's own elevation range, radius DRIFT_R (just inside the
            dome), turning about world up through the rest camera with period SKY_ANIM["periodS"] (the Unity builder's
            Animator spin on the holder's local Y; holder at the camera, local Y = world up). Its texture is the
            painting's own sky wherever a band direction sees painted sky (the profile's SKY_MASK, eroded 2 px with
            the rect edges kept), and a periodic 360 deg sky panorama everywhere else: SDXL inpainting of the
            equirectangular band (town_full3d_sdfill.py --step sky) conditioned on the painted sky, generated outward
            in overlapping windows and closed by one window across the wrap, so it has no join, no mirror and no
            stretch. Its colour is the SD step's own CIELAB mean / std transfer to the painted sky. The painted sky is
            feathered into it over PANO_FEATHER_DEG inside its mask. Tried and dropped: a per-channel CIELAB quantile
            match (it paired cloud shadows with the painted sky's warmest a*/b* and browned them) and a local
            colour-offset carry-out (it washed the panorama grey). In drift mode the static dome is built from the
            same composite at its own azimuths, so the rest frame at t=0 is the painting's sky and the band matches
            the dome. Opaque, depth-tested: the relief and the buildings occlude
            it; the dome stays behind as the backstop. Pan extremes: the band covers every azimuth, so no pose meets
            its edge. Superseded 2026-09-28: the dome mirrored and stretched over the unpainted 196 deg (vertical
            streaks where the dome's below-skyline column fill turned into view, and a bright line at the rect's
            right edge, where the 2 px mask erosion dropped the edge columns and their fill took the painting's row 0).
            Build: python town_full3d_sky.py --faction <key> kit; the SD step; then stage --parts sky.
  The panorama is its own profile field, SKY_PANO (key / prompt / negative / seed), because the static dome needs it
  whatever the drift mode: every faction that declares SKY_PANO gets the composite dome (painted sky feathered into the
  periodic panorama) in place of the mirror fill, whose streaks right of the painted rect (frame x1440 under the
  sweeps), mirrored duplicates (a second moon) and bright rect-edge line showed on every faction. A drift needs
  SKY_PANO; a profile without it (Stronghold: finished in its own lane; Dungeon: no sky) keeps the mirror dome.
  Tried and dropped for the SKY_PANO rollout (Cove): a CIELAB transfer per elevation band (the painted sky is a thin
  band, so the rows beyond it took its edge stats and banded the panorama) and a 4 deg feather (no visible change:
  the remaining vertical step at the painted rect's edge is painted sky outside the profile's SKY_MASK, carried by the
  relief, not the dome).
  none      no sky to animate (an underground town, or a canopy / fog that hides the sky): nothing is staged.
  deferred  the faction's scene is finished in another lane; the drift is its own later change.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T

DRIFT_R = T.DOME_R - 5.0      # painting m: in front of the dome, behind every relief point (FAR_CAP_M <= 400)
BAND_W, BAND_H = 8192, 2048   # the dome's elevation rows, 360 deg at ~22.8 px / deg (the dome: 25 px / deg)
GA, GE = 256, 64
PANO_H = 1024                 # SD panorama rows over the dome's elevation range (13.1 px / deg; HoMM3 native ~13.9)
PANO_FEATHER_DEG = 1.5        # the painted sky's feather into the panorama, inside the painted mask


def spec() -> dict:
    s = SC.FP.SKY_ANIM
    if not isinstance(s, dict) or s.get("mode") not in ("drift", "none", "deferred") or not s.get("reason"):
        raise SystemExit(f"town_full3d_sky: profile SKY_ANIM {s!r} needs mode drift / none / deferred and a reason")
    if s["mode"] == "drift" and not (isinstance(s.get("periodS"), (int, float)) and s["periodS"] >= 300):
        raise SystemExit("town_full3d_sky: a drift needs periodS >= 300 (a period of minutes)")
    return s


def has_pano() -> bool:
    """The profile declares SKY_PANO: the dome (and a drift) take the panorama composite."""
    return getattr(SC.FP, "SKY_PANO", None) is not None


def pano_spec() -> dict:
    """Profile SKY_PANO: the SD panorama run the dome and the drift use (key, prompt, negative, seed)."""
    p = getattr(SC.FP, "SKY_PANO", None)
    if "pano" in spec():
        raise SystemExit("town_full3d_sky: the panorama moved from SKY_ANIM['pano'] to the profile's SKY_PANO")
    if not isinstance(p, dict) or not all(p.get(k) for k in ("key", "prompt", "negative")) \
            or not isinstance(p.get("seed"), int):
        raise SystemExit("town_full3d_sky: SKY_PANO needs key / prompt / negative / seed (a drift needs SKY_PANO)")
    return p


def pano_dir() -> Path:
    return SC.ROOT / "artifacts" / SC.FP.DATA_DIR / "tex" / "skypano" / pano_spec()["key"]


def pano_size(sky_el) -> tuple[int, int]:
    return int(round(PANO_H * 360.0 / (sky_el[1] - sky_el[0]) / 8.0)) * 8, PANO_H


def painted_sky(sc, az_deg, el_deg) -> tuple[np.ndarray, np.ndarray]:
    """The painting's sky along the (el row, az column) directions (dome orientation): float RGB 0..255 sampled as the
    dome samples it (2x LANCZOS painting, bilinear), and the genuine mask: the direction lands in the painted rect on
    the profile's sky mask, eroded 2 px with the rect edges kept (border_value 1)."""
    from scipy.ndimage import binary_erosion
    up = np.array([0.0, 1.0, 0.0])
    f, r = T.heading(sc.cam)
    sky_e = binary_erosion(T.sky_mask(T.painting()), np.ones((3, 3), bool), iterations=2, border_value=1)
    pl = np.asarray(SC.albedo_background().resize((SC.TW * 2, SC.TH * 2), Image.LANCZOS)).astype(np.float32)
    az, el = np.radians(np.asarray(az_deg, np.float64)), np.radians(np.asarray(el_deg, np.float64))
    img = np.zeros((len(el), len(az), 3), np.float32)
    gen = np.zeros((len(el), len(az)), bool)
    for r0 in range(0, len(el), 256):
        E_, A = np.meshgrid(el[r0:r0 + 256], az, indexing="ij")
        d = np.cos(E_)[..., None] * (np.cos(A)[..., None] * f + np.sin(A)[..., None] * r) + np.sin(E_)[..., None] * up
        px, py, zc = T.project(sc.cam, sc.cam["pos"] + d)
        px, py = np.nan_to_num(px, posinf=-1, neginf=-1), np.nan_to_num(py, posinf=-1, neginf=-1)
        inside = (zc > 0) & (px >= 0) & (px <= SC.TW - 1) & (py >= 0) & (py <= SC.TH - 1)
        xi = np.clip(px.round(), 0, SC.TW - 1).astype(int)
        yi = np.clip(py.round(), 0, SC.TH - 1).astype(int)
        gen[r0:r0 + 256] = inside & sky_e[yi, xi]
        u = np.clip(px * 2 + 0.5, 0, SC.TW * 2 - 1.001).astype(np.float32)
        v = np.clip(py * 2 + 0.5, 0, SC.TH * 2 - 1.001).astype(np.float32)
        img[r0:r0 + 256] = cv2.remap(pl, u, v, cv2.INTER_LINEAR)
    return img, gen


def pano_kit(sc, sky_az, sky_el) -> Path:
    """kit/known.png (the painted sky on grey 128 at the panorama's own size), kit/known_mask.png (255 = painted
    sky), kit/kit.json for town_full3d_sdfill.py --step sky. Columns start at sky_az[0] and cover 360 deg."""
    import hashlib
    import json
    pw, ph = pano_size(sky_el)
    az = sky_az[0] + (np.arange(pw) + 0.5) * 360.0 / pw
    el = sky_el[1] - (np.arange(ph) + 0.5) * (sky_el[1] - sky_el[0]) / ph
    img, gen = painted_sky(sc, az, el)
    kit = pano_dir() / "kit"
    kit.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.where(gen[..., None], img, 128.0).clip(0, 255).astype(np.uint8)).save(kit / "known.png")
    Image.fromarray((gen * 255).astype(np.uint8)).save(kit / "known_mask.png")
    man = {"schema": "town_full3d_skypano_kit.v1", "faction": SC.FACTION, "size": [pw, ph],
           "azDeg": [sky_az[0], sky_az[0] + 360.0], "elDeg": [sky_el[1], sky_el[0]], "knownPx": int(gen.sum()),
           "knownSha256": hashlib.sha256((kit / "known.png").read_bytes()).hexdigest(), "pano": pano_spec()}
    (kit / "kit.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return kit


def composite(sc, az_deg, el_deg) -> np.ndarray:
    """The drift's sky along (el row, az column): the painted sky feathered over PANO_FEATHER_DEG inside its mask into
    the SD panorama (<pano_dir>/pano.png; missing -> stop). uint8 RGB."""
    import json
    from scipy.ndimage import distance_transform_edt
    d = pano_dir()
    if not (d / "pano.png").is_file():
        raise SystemExit(f"town_full3d_sky: {d / 'pano.png'} missing (town_full3d_sky.py kit, then "
                         f"town_full3d_sdfill.py --step sky)")
    kit = json.loads((d / "kit" / "kit.json").read_text(encoding="utf-8"))
    pano = np.asarray(Image.open(d / "pano.png").convert("RGB")).astype(np.float32)
    ph, pw = pano.shape[:2]
    if [pw, ph] != kit["size"]:
        raise SystemExit(f"town_full3d_sky: pano.png is {pw}x{ph}, its kit says {kit['size']}")
    a0, (e1, e0) = kit["azDeg"][0], kit["elDeg"]
    az, el = np.asarray(az_deg, np.float64), np.asarray(el_deg, np.float64)
    U, V = np.meshgrid(np.mod(az - a0, 360.0) / 360.0 * pw - 0.5, (e1 - el) / (e1 - e0) * ph - 0.5)
    pad = np.concatenate([pano[:, -1:], pano, pano[:, :1]], 1)          # wrap in azimuth, clamp in elevation
    back = cv2.remap(pad, (U + 1).astype(np.float32), np.clip(V, 0, ph - 1).astype(np.float32), cv2.INTER_LINEAR)
    img, gen = painted_sky(sc, az, el)
    px_per_deg = (len(az) - 1) / max(float(np.ptp(az)), 1e-6)
    em = getattr(SC.FP, "SKY_EDGE_MATCH", None)
    if em:
        # profile SKY_EDGE_MATCH (sky only, never terrain or buildings): the panorama's low-pass tone is moved onto the
        # painted sky's at the nearest painted direction, fully inside the painted mask and fading out over radiusDeg
        # outside it, so the painted sky's glow and the panorama meet without a line at the rect's edge (Bulwark: the
        # painted night sky is lighter than the panorama beside it; seam-line ratio 6.7-7.2 over rows 0-40 at x = TW)
        sig = float(em["sigmaDeg"]) * px_per_deg
        g = gen.astype(np.float32)
        ng = cv2.GaussianBlur(g, (0, 0), sig)
        lp_img = cv2.GaussianBlur(img * g[..., None], (0, 0), sig) / np.maximum(ng, 1e-4)[..., None]
        lp_back = cv2.GaussianBlur(back, (0, 0), sig)
        dist, (iy, ix) = distance_transform_edt(~gen, return_indices=True)
        # the painted low-pass is taken where the painted share is at least half (its border average is diluted)
        core = ng >= 0.5
        if not core.any():
            raise SystemExit("town_full3d_sky: SKY_EDGE_MATCH: no painted sky direction in this band")
        _, (cy, cx) = distance_transform_edt(~core, return_indices=True)
        ref = lp_img[cy[iy, ix], cx[iy, ix]]
        wo = np.exp(-(dist / (float(em["radiusDeg"]) * px_per_deg)) ** 2)[..., None]
        back = back + (ref - lp_back) * wo
    join = getattr(SC.FP, "SKY_EDGE_JOIN", None)
    if join is not None:
        return _edge_join(sc, az, el, img, gen, back, px_per_deg, join)
    w = np.clip(distance_transform_edt(gen) / (PANO_FEATHER_DEG * px_per_deg), 0, 1)[..., None]
    return np.clip(img * w + back * (1 - w) + 0.5, 0, 255).astype(np.uint8)


# Profile SKY_EDGE_JOIN (opt-in; absent = the composite above, byte-identical): the painted sky continued across the
# painted rect's side edges onto the panorama. Without it the dome is pure panorama right of x = TW (the feather sits
# inside the painted mask), and the panorama there does not continue the painted clouds: a vertical step at the frame
# edge on SKY_PANO factions (seam-line gate rows 0..~200 at x = TW, 2026-09-29: castle ratio ~5-6, necropolis ~4-5).
# A wider mask feather does not reach it (4 deg on Cove: no change). Method "mirror": a dome direction that projects
# beyond a listed edge by d <= fadePx frame px samples the painting at the edge's reflection (x -> 2(TW-1) - x on the
# right, -x on the left) when the reflected pixel lies in the painting's sky region (at or above its column's lowest
# painted-sky row: painted clouds the profile's SKY_MASK leaves out are carried by the relief inside the rect, so their
# reflection is what continues them) and not under a building layer. The mirrored sky's weight falls to 0 over fadePx (smoothstep), and the
# PANO_FEATHER_DEG feather is taken over the union of the painted and mirrored masks, so the rect's side edge is no
# longer a feather boundary. Continuous at the edge by construction (the edge column maps to itself); a mirrored cloud
# shows only inside the fade. Sky pixels only: the dome sits behind every relief point and building.
def _edge_join(sc, az, el, img, gen, back, px_per_deg, join: dict) -> np.ndarray:
    from scipy.ndimage import binary_erosion, distance_transform_edt
    edges = set(join.get("edges") or ())
    method = join.get("method")
    if method not in ("mirror", "canvas") or not edges or not edges <= {"left", "right"} \
            or not float(join.get("fadePx", 0)) > 0 or not join.get("reason"):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN {join!r} needs method 'mirror' or 'canvas', edges within "
                         f"{{left, right}}, fadePx > 0 and a reason")
    fade = float(join["fadePx"])
    # method "canvas": a dome direction beyond a listed edge by d <= fadePx samples the TOWN_FULL3D_EXTSRC canvas's own
    # sky at that direction (the extension sky rule of the profile's SKY_MASK), fading to the panorama over fadePx. A
    # bridge with writeSky continues the painted sky into the canvas, so where the painting's sky beside the edge sits
    # under building layers (Cove: the Grail's moon statue and the lighthouse cover rows ~60-230 at x 1380-1439, so the
    # mirror has no source) the canvas still carries the painted sky across the edge. Needs the canvas (fail closed).
    cv_img = cv_sky = None
    # profile canvasBelowMirror (opt-in, method 'mirror' only): a mirror direction the painting has no source for (below
    # the reflected column's lowest sky row, or under a building) samples the TOWN_FULL3D_EXTSRC canvas at the direction
    # itself instead of falling back to the panorama. Castle: with the far wall fitted down to the canvas skyline
    # (EXT_SKYLINE), the directions between the painted sky's bottom and that skyline showed the flat panorama as a
    # grey-blue block beside the mage tower; the pure canvas join instead raised the sky rows' seam line (x1440 p90 2.50
    # -> 3.46: the bridged sky beside the edge is not the painted sky's reflection)
    below = join.get("canvasBelowMirror", False)
    if not isinstance(below, bool) or (below and method != "mirror"):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN canvasBelowMirror must be a bool and True only with method "
                         f"'mirror', got {below!r}")
    if method == "canvas" or below:
        ext = SC.extension_canvas()
        if ext is None:
            raise SystemExit("town_full3d_sky: SKY_EDGE_JOIN method 'canvas' needs TOWN_FULL3D_EXTSRC")
        cimg, cx0, ck = ext
        if ck != 1:
            raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN method 'canvas' needs a scale-1 canvas, got {ck}")
        import town_full3d_masks as M
        clab = cv2.cvtColor(cimg.astype(np.float32), cv2.COLOR_RGB2LAB)
        crect = np.zeros(cimg.shape[:2], bool)
        crect[:SC.TH, -cx0:-cx0 + SC.TW] = True
        cv_sky = M.extension_sky(clab, crect, SC.FP.SKY_MASK)
        cv_img = (cimg * 255.0).astype(np.float32)
    TW_, TH_ = SC.TW, SC.TH
    up = np.array([0.0, 1.0, 0.0])
    f, r = T.heading(sc.cam)
    sky_e = binary_erosion(T.sky_mask(T.painting()), np.ones((3, 3), bool), iterations=2, border_value=1)
    lowest = np.where(sky_e.any(0), TH_ - 1 - np.argmax(sky_e[::-1], axis=0), -1)   # per column: lowest sky row
    # the painting under a building layer is never seen (HoMM3 leaves it unfinished: Necropolis's flat white patches
    # behind the cliff mansion tbncdw_6 showed as blocks on the dome), so it is never a mirror source
    import town_full3d_tex as TX
    under = TX.building_mask_frame()[:TH_, :TW_]
    # profile mirrorUnderBuildings (opt-in): a painting whose sky is finished under its building layers (Castle: the
    # clouds run on behind the mage tower and the wall towers at x 1140-1440) takes those pixels as mirror sources too;
    # excluded, the reflection of the edge's tower columns left a flat panorama block beside it (seam-line rows 157-240)
    under_ok = join.get("mirrorUnderBuildings", False)
    if not isinstance(under_ok, bool):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN mirrorUnderBuildings must be a bool, got {under_ok!r}")
    if under_ok:
        under = np.zeros_like(under)
    pl = np.asarray(SC.albedo_background().resize((TW_ * 2, TH_ * 2), Image.LANCZOS)).astype(np.float32)
    mir = np.zeros_like(img)
    mw = np.zeros(gen.shape, np.float32)
    inr = np.zeros(gen.shape, bool)                  # directions inside the painted rect or within fadePx beside it
    rin = np.zeros(gen.shape, bool)                  # directions inside the painted rect
    abv = np.zeros(gen.shape, bool)                  # directions above the rect's top, over the rect or its fade band
    rect_feather = join.get("rectFeather", True)
    if not isinstance(rect_feather, bool):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN rectFeather must be a bool, got {rect_feather!r}")
    canvas_sky_only = join.get("canvasSkyOnly", True)
    if not isinstance(canvas_sky_only, bool) or (not canvas_sky_only and method != "canvas"):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN canvasSkyOnly must be a bool and False only with method "
                         f"'canvas', got {canvas_sky_only!r}")
    top_feather = join.get("topFeather", True)
    if not isinstance(top_feather, bool) or (not top_feather and rect_feather):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN topFeather must be a bool and False only with rectFeather "
                         f"False, got {top_feather!r}")
    # topFadePx (opt-in, only with topFeather False and canvasSkyOnly False): the directions above the rect's top take
    # the low-passed weight only as it fades to 0 over this many frame px above row 0, and right/left of the rect they
    # sample the canvas's own column (its row 0) instead of the painting clamped to its corner pixel. Without it those
    # directions carried the full weight onto the painting clamped at its top row: Fortress cursor_left/right showed
    # the painting's top-row trunks as vertical streaks over the rect and its dark top-right corner pixel as a
    # near-black bar beside it (rows 0-30 at frame x 1500-1700, min RGB 2/4/12 against canopy_v1's 28/40/34)
    top_fade = join.get("topFadePx")
    if top_fade is not None and (isinstance(top_fade, bool) or not isinstance(top_fade, (int, float))
                                 or not float(top_fade) > 0 or top_feather or canvas_sky_only):
        raise SystemExit(f"town_full3d_sky: SKY_EDGE_JOIN topFadePx must be a number > 0 and set only with topFeather "
                         f"False and canvasSkyOnly False, got {top_fade!r}")
    above = np.zeros(gen.shape, np.float32)          # frame px above the rect's top row (topFadePx only)
    besd = np.zeros(gen.shape, bool)                 # beside the rect in x (topFadePx only)
    sm = lambda t: t * t * (3 - 2 * t)  # noqa: E731
    for r0 in range(0, len(el), 256):
        E_, A = np.meshgrid(np.radians(el[r0:r0 + 256]), np.radians(az), indexing="ij")
        d = np.cos(E_)[..., None] * (np.cos(A)[..., None] * f + np.sin(A)[..., None] * r) + np.sin(E_)[..., None] * up
        px, py, zc = T.project(sc.cam, sc.cam["pos"] + d)
        px = np.nan_to_num(px, nan=-1e9, posinf=-1e9, neginf=-1e9)
        py = np.nan_to_num(py, nan=-1e9, posinf=-1e9, neginf=-1e9)
        ok = (zc > 0) & (py >= 0) & (py <= TH_ - 1)
        dist = np.full(px.shape, np.inf)
        mx = np.zeros(px.shape)
        if "right" in edges:
            dr = px - (TW_ - 1)
            sel = ok & (dr > 0) & (dr <= fade)
            dist, mx = np.where(sel, dr, dist), np.where(sel, (TW_ - 1) - dr, mx)
        if "left" in edges:
            dl = -px
            sel = ok & (dl > 0) & (dl <= fade) & ~np.isfinite(dist)
            dist, mx = np.where(sel, dl, dist), np.where(sel, dl, mx)
        hit = np.isfinite(dist)
        rin[r0:r0 + 256] = ok & (px >= 0) & (px <= TW_ - 1)
        abv[r0:r0 + 256] = (zc > 0) & (py < 0) & (px >= -fade) & (px <= TW_ - 1 + fade)
        above[r0:r0 + 256] = np.clip(-py, 0, None)
        besd[r0:r0 + 256] = (px < 0) | (px > TW_ - 1)
        inr[r0:r0 + 256] = rin[r0:r0 + 256] | hit
        xi = np.clip(mx.round(), 0, TW_ - 1).astype(int)
        yi = np.clip(py.round(), 0, TH_ - 1).astype(int)
        if method == "canvas":
            cxf = px - cx0                                  # canvas column of the direction itself
            cxi = np.clip(cxf.round(), 0, cv_sky.shape[1] - 1).astype(int)
            hit &= (cxf >= 0) & (cxf <= cv_sky.shape[1] - 1)
            if canvas_sky_only:
                hit &= cv_sky[yi, cxi]
            # canvasSkyOnly False: the canvas is sampled below its own sky too. The far wall there is fitted to that
            # skyline (EXT_SKYLINE) and textured from the same canvas, so it covers those directions; what the option
            # removes is the weight's low-pass at the canvas's sky bottom, which dimmed the painted glow just above the
            # skyline to the panorama (Cove rows 234-258 at x 1441: L* ~50 on the dome against ~62 in the canvas)
            mir[r0:r0 + 256] = cv2.remap(cv_img, np.clip(cxf, 0, cv_sky.shape[1] - 1).astype(np.float32),
                                         np.clip(py, 0, TH_ - 1).astype(np.float32), cv2.INTER_LINEAR)
        else:
            hm = hit & (yi <= lowest[xi]) & ~under[yi, xi]
            u = np.clip(mx * 2 + 0.5, 0, TW_ * 2 - 1.001).astype(np.float32)
            v = np.clip(py * 2 + 0.5, 0, TH_ * 2 - 1.001).astype(np.float32)
            mm = cv2.remap(pl, u, v, cv2.INTER_LINEAR)
            if below:
                cxf = px - cx0
                hc = hit & ~hm & (cxf >= 0) & (cxf <= cv_img.shape[1] - 1)
                mc = cv2.remap(cv_img, np.clip(cxf, 0, cv_img.shape[1] - 1).astype(np.float32),
                               np.clip(py, 0, TH_ - 1).astype(np.float32), cv2.INTER_LINEAR)
                # canvasBlendPx: over this many rows above the reflected column's sky bottom the mirror fades into
                # the canvas, so the switch is not a horizontal cut (the painting's low cloud against the canvas's sky)
                bpx = float(join.get("canvasBlendPx", 0.0))
                t = np.clip((yi - (lowest[xi] - bpx)) / max(bpx, 1e-6), 0, 1)[..., None] if bpx > 0 else 0.0
                okc = ((cxf >= 0) & (cxf <= cv_img.shape[1] - 1))[..., None]
                mm = np.where(hm[..., None], np.where(okc, mm * (1 - t) + mc * t, mm), mc)
                hm = hm | hc
            hit = hm
            mir[r0:r0 + 256] = mm
        mw[r0:r0 + 256] = np.where(hit, 1 - sm(np.clip(np.where(hit, dist, 0) / fade, 0, 1)), 0)
    hit = (mw > 0) & ~gen
    src = np.where(hit[..., None], mir, img)
    if rect_feather:
        fw = np.clip(distance_transform_edt(gen | hit) / (PANO_FEATHER_DEG * px_per_deg), 0, 1)
        w = (fw * np.where(hit, mw, 1.0))[..., None]
    else:
        # rectFeather False: the painted sky is feathered only toward panorama directions that are neither in the
        # painted rect nor within fadePx beside it. A rect direction the painting does not call sky is its relief or a
        # building at rest, and a direction beside the edge whose reflection is not sky continues that relief, so
        # feathering the sky toward either only tints the painted sky just above the silhouette with the panorama
        # (Inferno, belowHorizon rows: the smoky panorama darkened the painted glow above the right-edge ridge,
        # L* 18 -> 13, seam-line rows 243-294). Those directions take the panorama (weight 0), as before.
        nf = inr & ~gen & ~hit
        if not top_feather:
            # topFeather False: directions above the rect's top edge are not feather boundaries either (weight 0 like
            # nf), so the joined sky beside the edge keeps its full weight up to the frame's top row instead of fading
            # to the panorama over PANO_FEATHER_DEG below it (Cove: the canvas sky right of x = TW fell back to the
            # darker panorama over rows 0-40, seam-line bin 0 ratio 9.6 while rows 40-160 sat at ~2)
            nf = nf | (abv & ~gen & ~hit)
        fw = np.clip(distance_transform_edt(gen | hit | nf) / (PANO_FEATHER_DEG * px_per_deg), 0, 1)
        w = np.where(nf, 0.0, fw * np.where(hit, mw, 1.0)).astype(np.float32)
        # beside the edge the mirror's misses follow the painting's per-column sky bottom, a stair-stepped line on the
        # visible dome: outside the rect the weight is low-passed over half the feather (inside it stays as is)
        sig = 0.5 * PANO_FEATHER_DEG * px_per_deg
        if canvas_sky_only:
            w = np.where(rin, w, cv2.GaussianBlur(w, (0, 0), sig))[..., None]
        else:
            # canvasSkyOnly False: no stair-stepped miss line to hide, and the low-pass is normalised over the
            # directions outside the rect only: rect directions the painting does not call sky (the glow above the
            # painted ridge, a building at rest) carry weight 0 and dimmed the joined sky within ~sig of x = TW
            # (Cove rows 234-252, x 1441-1460: RGB ~167/110/93 on the dome against the canvas's ~200/132/109)
            # (topFeather False: the directions above the rect's top are left out of it too, else their weight 0
            # dims rows 0-20 beside the edge again)
            o = (~rin & ~(abv if not top_feather else np.zeros_like(abv))).astype(np.float32)
            lw = cv2.GaussianBlur(w * o, (0, 0), sig) / np.maximum(cv2.GaussianBlur(o, (0, 0), sig), 1e-4)
            if top_fade is not None:
                ab = abv & ~hit & ~gen
                lw = np.where(ab, lw * (1 - sm(np.clip(above / float(top_fade), 0, 1))), lw)
                if method == "canvas":
                    src = np.where((ab & besd)[..., None], mir, src)
                # the clamped top row still smears upward as vertical streaks: it is low-passed toward the fade's end
                ta = sm(np.clip(above / float(top_fade), 0, 1))[..., None]
                src = np.where(ab[..., None], src * (1 - ta) + cv2.GaussianBlur(src, (0, 0), sig) * ta, src)
            w = np.where(rin, w, lw)[..., None]
    return np.clip(src * w + back * (1 - w) + 0.5, 0, 255).astype(np.uint8)


def _quat_y_to(u: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Rotation matrix and Unity quaternion (x, y, z, w) taking +Y to u."""
    y = np.array([0.0, 1.0, 0.0])
    ax = np.cross(y, u)
    s, c = float(np.linalg.norm(ax)), float(y @ u)
    if s < 1e-9:
        return np.eye(3), [0.0, 0.0, 0.0, 1.0]
    ax /= s
    ang = math.atan2(s, c)
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    R = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K
    h = math.sin(ang / 2)
    return R, [float(ax[0] * h), float(ax[1] * h), float(ax[2] * h), float(math.cos(ang / 2))]


def _ry(theta_deg: float) -> np.ndarray:
    """Unity Quaternion.Euler(0, theta, 0) as a matrix (acts on column vectors)."""
    t = math.radians(theta_deg)
    return np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])


def geometry(sc, sky_az, sky_el):
    """World grid of the band (az from sky_az[0] over 360 deg, el sky_el[1] -> sky_el[0], dome's orientation)."""
    up = np.array([0.0, 1.0, 0.0])
    f, r = T.heading(sc.cam)
    ga = np.radians(np.linspace(sky_az[0], sky_az[0] + 360.0, GA + 1))
    ge = np.radians(np.linspace(sky_el[1], sky_el[0], GE + 1))
    AA, EE = np.meshgrid(ga, ge)
    dd = np.cos(EE)[..., None] * (np.cos(AA)[..., None] * f + np.sin(AA)[..., None] * r) + np.sin(EE)[..., None] * up
    Pw = sc.cam["pos"] + dd * DRIFT_R
    uv = np.stack([(AA - ga[0]) / (ga[-1] - ga[0]), (EE - ge[-1]) / (ge[0] - ge[-1])], -1).reshape(-1, 2)
    nx_ = GA + 1
    j, i = np.meshgrid(np.arange(GE), np.arange(GA), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    return Pw.reshape(-1, 3), (-dd).reshape(-1, 3), uv.astype(np.float32), tris


def stage_drift(sc, prefab: str, sky_az, sky_el) -> dict:
    """Stage Sky_Drift (holder-local mesh, pos = the camera, rot = world up; spinPeriod) and its t=0 preview row."""
    import stronghold_full3d_scene as S
    s = spec()
    band = composite(sc, sky_az[0] + (np.arange(BAND_W) + 0.5) * 360.0 / BAND_W,
                     np.linspace(sky_el[1], sky_el[0], BAND_H))
    Pw, nw, uv, tris = geometry(sc, sky_az, sky_el)
    v_true = sc.local(Pw)                                  # prefab frame (camera at the origin)
    n_true = sc.local_dir(nw)
    u_p = sc.local_dir(np.array([0.0, 1.0, 0.0]))
    u_p = u_p / np.linalg.norm(u_p)
    R, q = _quat_y_to(u_p)
    v_h, n_h = v_true @ R, n_true @ R                       # R^T v per row: holder-local
    name = "Sky_Drift"
    S.write_bin(S.STAGE / prefab / f"{name}.bytes", v_h, n_h, uv, [tris])
    tp = S.STAGE / prefab / f"{name}_albedo.png"
    tp.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(band).save(tp)
    row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{prefab}/{name}.bytes",
           "texture": f"{S.ASSET_ROOT}/{prefab}/{name}_albedo.png", "kind": "sky", "maxSize": BAND_W,
           "pos": [0.0, 0.0, 0.0], "rot": q, "spinPeriod": float(s["periodS"])}
    sc.pieces.setdefault(prefab, []).append(row)
    sc.preview.append((f"{prefab}/{name}", Pw.astype(np.float32), nw.astype(np.float32), uv, tris.astype(np.int32),
                       band, True))
    deg_s = 360.0 / s["periodS"]
    px_per_deg = SC.W / (2 * math.degrees(math.atan(math.tan(math.radians(sc.cam["fov"]) / 2) * SC.W / SC.H)))
    rep = {"mode": "drift", "reason": s["reason"], "periodS": s["periodS"], "degPerS": round(deg_s, 4),
           "screenPxPerS": round(deg_s * px_per_deg, 2), "radiusM": DRIFT_R, "band": [BAND_W, BAND_H],
           "azDeg": [sky_az[0], sky_az[0] + 360.0], "elDeg": list(sky_el), "rot": q,
           "join": "painted sky feathered into a periodic SDXL panorama (no mirror, no stretch, no wrap join)",
           "pano": {"dir": str(pano_dir()), **pano_spec()}}
    sc.report["skyDrift"] = rep
    return rep


def holder_to_prefab(v, n, prefab: str):
    """Sky_Drift's holder-local bin -> prefab frame by its staged row's rot (t = 0)."""
    import json
    import stronghold_full3d_scene as S
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    row = next(b for b in rows[prefab]["bins"] if b["name"] == "Sky_Drift")
    x, y, z, w = row["rot"]
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    return np.asarray(v, np.float64) @ R.T + np.asarray(row["pos"]), np.asarray(n, np.float64) @ R.T


def posed_preview_row(row_preview, theta_deg: float, sc):
    """The Sky_Drift preview row turned by theta about world up through the camera (Unity's spin sense)."""
    name, P, n, uv, tris, img, unlit = row_preview
    u_p = sc.local_dir(np.array([0.0, 1.0, 0.0]))
    R, _ = _quat_y_to(u_p / np.linalg.norm(u_p))
    M = R @ _ry(theta_deg) @ R.T                           # prefab frame, column vectors
    v = sc.local(P.astype(np.float64)) @ M.T
    nn = sc.local_dir(n.astype(np.float64)) @ M.T
    Pw = sc.cpos + (v / sc.scale) @ sc.C.T
    nw = nn @ sc.C.T
    return (name, Pw.astype(np.float32), nw.astype(np.float32), uv, tris, img, unlit)


def main() -> int:
    import argparse
    import json
    import stronghold_full3d_scene as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=SC.FACTION)
    ap.add_argument("cmd", choices=["kit"])
    ap.parse_args()
    if not has_pano():
        raise SystemExit(f"town_full3d_sky: {SC.FACTION} declares no SKY_PANO")
    print(json.dumps({"kit": str(pano_kit(S.Scene(), S.SKY_AZ, S.SKY_EL))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
