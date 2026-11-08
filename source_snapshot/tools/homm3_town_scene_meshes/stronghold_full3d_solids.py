"""Depth-relief buildings closed as solids (no Meshy, no paid generation): the 'solid' building method.

The 'relief' method (stronghold_full3d_buildings.build_mesh) closes each sprite's depth relief by extruding every
silhouette edge along its camera ray to a flat back at one per-layer thickness. Under the vanilla sweep that shows
three defects: side walls that carry one texel column along their whole depth (streaks), ground painted into the
sprite (plazas, yards, hill paths) extruded into thick slabs, and thin parts (poles, spires, banners) extruded into
sheets as deep as the building. This closure keeps the same camera-facing front (every vertex on its own pixel's ray,
so the rest pose is unchanged by construction) and replaces the back:

  ground / upright  a front vertex whose height above the painted terrain at its own pixel is under H_UP_M is ground:
                    it keeps its relief depth (already clamped in front of the terrain) and gets no volume. Anything
                    higher (or with sky behind it) is upright.
  thin members      row runs narrower than THIN_M (poles, spires, blades, posts): each connected thin segment gets a
                    robust planar depth fit (z = a + b y + c x), so it stays a straight member under the sweep instead
                    of a ribbon wobbling with the depth model's noise.
  depth steps       a front triangle across a depth step is sunk to its far depth (front_surface sink_cuts) rather
                    than cut, so the rest pose keeps its texels, and the step's near edge gets a closing wall along
                    its own rays down to that depth (BL.closing_walls: edge-on at rest, wound toward the far side).
  thickness         per grid row, each run of upright vertices is a cross-section as deep as DEPTH_K x its own width
                    (capped per layer), with a superellipse profile (exponent PROFILE_N; 2 = round, larger = boxier)
                    that is zero at the run's ends, capped by DEPTH_K x the vertex's own column run (no deeper than
                    tall: wing tips and eaves over open ground stay thin), then smoothed vertically. A pole is as thin
                    as it is wide; a hut is about as deep as it is wide; ground has none.
  back surface      the smoothed front depth plus the thickness, along each vertex's own camera ray (edge-on at the rest
                    pose, like the relief), welded to the front on the upright region's outline (thickness 0 there).
                    It is continuous across the front's depth-step cuts, so a step opens onto the volume's own inside,
                    not onto a see-through gap.
  back texture      the front art re-parametrised per row by 3D arc length, so a side wall shows the texels at the
                    building's own edge spread evenly around the profile (the mirrored hidden side), instead of one
                    texel column smeared over the whole depth.
  atlas             de-lit front | back half (the front with highlights capped at its own luminance quantile and
                    slightly darkened, so a back face turned to the key light does not blow out a painted highlight).

  parts (optional)  build_solid(parts=True) for the layers in PARTS_LAYERS: the upright region is split at depth
                    steps (PART_RATIO) into parts (specks and silhouette halo merged back) and each part gets its own
                    runs, smoothing and arc-length back, with no back triangle bridging two parts, so a wing in front of
                    its crag is as thin as the wing. The silhouette outline keeps the plain closure.

Generic: nothing here reads a faction name. Per-layer inputs are the sprite mask/depth/terrain from layer_depth and
an optional TUNE row (cap / profile) for parts that the width rule cannot know (a cloth banner is wide but flat).
Proof tier: generated artifact (offline meshes; editor renders are the review evidence).
"""
from __future__ import annotations

import cv2
import numpy as np

import stronghold_full3d_buildings as BL
import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import town_full3d_wall_rest as WR

H_UP_M = 0.6          # m above the painted terrain (along the floor normal) that makes a vertex upright
MIN_UP_CELLS = 12     # smaller upright specks are ground
DEPTH_K = 0.8         # a cross-section is this deep per metre of its own width
T_MAX_M = 16.0        # default cap on a cross-section's depth (m)
PROFILE_N = 3.0       # superellipse exponent of a cross-section
SMOOTH_Y_CELLS = 2.0  # vertical smoothing of the thickness (grid cells)
BACK_Z_SIGMA = 3.0    # smoothing of the front depth under the back surface (grid cells)
TEX_ALIGN = 16        # albedo padded to a multiple of this many texels (mip registration)
THIN_M = 1.5          # an upright row run narrower than this (m) is a thin member (pole, spire, blade, post)
SINK_BACK_MARGIN = 0.003  # a back vertex of a sunk step triangle sits this fraction of its depth behind it
THIN_MIN_ROWS = 6     # a thin segment this tall (native px) or more is fitted as one straight member
BACK_LUM_Q = 0.85     # back-half luminance cap: this quantile of the building's own de-lit front
BACK_DARKEN = 0.9     # back half darkened by this factor (hand-set)
PART_RATIO = 1.03     # parts: grid neighbours whose depth ratio exceeds this are in different parts (a wing over its crag)
EDGE_BAND = 1        # parts: cells in from the silhouette outline where no part boundary is cut
PART_WELD = False     # parts: weld the back to the front on both sides of a part boundary (thickness 0 there)
PART_BRIDGE = False   # parts: keep the back triangles that bridge two parts (a skirt behind the front's sunk step)
COLOR_MEDIAN_PX = 5   # parts (appearance cue): median filter of the sprite before its chroma is compared (native px)
HALO_SHARE = 0.6      # parts: a part with this share of its cells in the silhouette band is edge halo (merged)
MIN_PART_CELLS = 24   # parts smaller than this are merged into the part they touch most (no specks with their own back)
# Layers closed with part separation under --building-method solid_parts (None = every layer: evaluation),
# chosen per faction by its review (faction profile PARTS_LAYERS).
PARTS_LAYERS = SC.FP.PARTS_LAYERS
BACK_ERODE_TX = 2     # back fill: texels of the sprite's own edge band (halo, outline pixels) replaced by the interior
BACK_FILL_CONTRAST = 0.5  # back fill: contrast of the back half about the building's median colour
BACK_FILL_LUM_Q = 0.6  # back fill: luminance cap (quantile of the building's own de-lit front) after the compression
BACK_FILL_DARKEN = 1.0  # back fill: overall factor of the back half (as BACK_DARKEN)
BACK_BLUR_TX = 0    # back fill: light blur of the filled back half (texels)
# Layers whose back half uses the edge-filled texture under --back-fill (None = every layer: evaluation), chosen
# per faction by its review (faction profile BACK_FILL_LAYERS); hand-set rows where the width rule is wrong
# (crag: the relief lane's hand-set cliff thickness is the cap) are the profile's SOLID_TUNE.
BACK_FILL_LAYERS = SC.FP.BACK_FILL_LAYERS
TUNE = SC.FP.SOLID_TUNE
# Per-faction opt-in (profile SINK_RIM_GRAZE_DROP = {"maxCos": c}; absent = off): a back triangle on a sunk front
# triangle whose shallow rim vertex tops a closing wall is kept (it closes the side past the wall), except, under the
# opt-in, one whose plane grazes the rest ray (|cos(normal, ray)| < maxCos). Off by default: on Cove it drops 85
# tbcvnmp2 triangles and opens orbit y-18 (24593 -> 30023 px, cv_v12 scratch 2026-09-29).
SINK_RIM_GRAZE_DROP = getattr(SC.FP, "SINK_RIM_GRAZE_DROP", None)


def grazing(P: np.ndarray, tris: np.ndarray, cam_pos, max_cos: float) -> np.ndarray:
    """Triangles whose plane is within max_cos of containing the ray from cam_pos to their centroid."""
    t = np.asarray(P, np.float64)[np.asarray(tris)]
    g = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    d = t.mean(1) - np.asarray(cam_pos, np.float64)
    c = np.abs((g * d).sum(1)) / (np.linalg.norm(g, axis=1) * np.linalg.norm(d, axis=1) + 1e-30)
    return c < max_cos
WALL_INNER_TX = 3     # closing-wall texel: band starts this many texels in from the wall's near edge (edge / outline px)
WALL_BAND_K = 24      # closing-wall texel: the band is this many near-side in-mask texels nearest the near edge
WALL_BAND_RADIUS_TX = 16.0  # closing-wall texel: the band lies within this many texels of the edge's midpoint


def _grid_zt(ld: dict, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """Terrain depth under each grid vertex (native sprite px lookup; NaN where the painting has sky)."""
    import stronghold_full3d_common as SC
    zt = ld["zt"]
    mh, mw = zt.shape
    sx = np.clip((px / SC.SCALE).astype(int), 0, mw - 1)
    sy = np.clip((py / SC.SCALE).astype(int), 0, mh - 1)
    return zt[sy, sx]


def _clean(up: np.ndarray, valid: np.ndarray) -> np.ndarray:
    n, lab, st, _ = cv2.connectedComponentsWithStats(up.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= MIN_UP_CELLS
    up = keep[lab]
    # ground holes fully inside an upright part (a window, a doorway's sill) are upright
    hole = (valid & ~up).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(hole, connectivity=4)
    for k in range(1, n2):
        if st2[k, cv2.CC_STAT_AREA] > 3 * MIN_UP_CELLS:
            continue
        m = lab2 == k
        ring = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~m
        if up[ring].all():
            up = up | m
    return up


def _runs(mask_1d: np.ndarray, brk_1d: np.ndarray | None = None):
    """[a, b) runs of True, also split where brk_1d[k] (a break between k and k+1) is set."""
    d = np.diff(np.r_[0, mask_1d.astype(np.int8), 0])
    starts, ends = list(np.nonzero(d == 1)[0]), list(np.nonzero(d == -1)[0])
    if brk_1d is None:
        return list(zip(starts, ends))
    out = []
    for a, b in zip(starts, ends):
        cuts = [int(k) + 1 for k in np.nonzero(brk_1d[a:b - 1])[0] + a]
        edges = [a] + cuts + [b]
        out += list(zip(edges[:-1], edges[1:]))
    return out


def _grid_chroma(L: dict, px: np.ndarray, py: np.ndarray, fw: float, fh: float) -> np.ndarray:
    """CIELAB (a*, b*) of the sprite at each grid vertex, from the static plate median-filtered (COLOR_MEDIAN_PX) so a
    part's own texture grain does not read as a boundary. L* is left out: in a painted sprite it is mostly lighting."""
    spr = np.asarray(SC.static_plate(L).convert("RGB"))
    spr = cv2.medianBlur(spr, COLOR_MEDIAN_PX)
    lab = cv2.cvtColor(spr, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    xi = np.clip((px / fw * w).astype(int), 0, w - 1)
    yi = np.clip((py / fh * h).astype(int), 0, h - 1)
    return lab[yi, xi, 1:] - 128.0


def _parts(up: np.ndarray, zz: np.ndarray, ratio: float, chroma: np.ndarray | None = None,
           color_step: float = 0.0) -> tuple:
    """Part labels of the upright grid: 4-neighbours join unless their depth ratio exceeds `ratio` (a depth step).
    Parts under MIN_PART_CELLS are merged into the neighbour part they share most edges with. Returns
    (labels (-1 off up), horizontal breaks (ny, nx-1), vertical breaks (ny-1, nx), silhouette band) where a break is an
    edge between two upright vertices of different parts, both outside the silhouette band."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    ny, nx = up.shape
    z = np.where(up, zz, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        rh = np.maximum(z[:, 1:], z[:, :-1]) / np.minimum(z[:, 1:], z[:, :-1])
        rv = np.maximum(z[1:], z[:-1]) / np.minimum(z[1:], z[:-1])
    jh = up[:, 1:] & up[:, :-1] & (rh <= ratio)
    jv = up[1:] & up[:-1] & (rv <= ratio)
    if chroma is not None and color_step > 0:
        # appearance cue (prototype, per-layer TUNE partColor only): neighbours at a similar depth are still split
        # where the sprite's chroma steps by more than color_step (a*b* distance)
        jh &= np.linalg.norm(chroma[:, 1:] - chroma[:, :-1], axis=-1) <= color_step
        jv &= np.linalg.norm(chroma[1:] - chroma[:-1], axis=-1) <= color_step
    # the silhouette band (EDGE_BAND cells in from the outline): the depth model blends into what is behind at the
    # edge, so a part lying mostly in the band is the model's halo, not a part (keeping it apart strips the edge's back
    # cover and the rest pose loses the edge texels behind the terrain): it is merged like a speck
    edge = _outline(up)
    if EDGE_BAND > 1:
        edge = cv2.dilate(edge.astype(np.uint8), np.ones((2 * EDGE_BAND - 1,) * 2, np.uint8)).astype(bool) & up
    idx = np.arange(ny * nx).reshape(ny, nx)
    r = np.r_[idx[:, :-1][jh], idx[:-1][jv]]
    c = np.r_[idx[:, 1:][jh], idx[1:][jv]]
    g = coo_matrix((np.ones(len(r)), (r, c)), shape=(ny * nx, ny * nx))
    _, lab = connected_components(g, directed=False)
    lab = np.where(up.ravel(), lab, -1).reshape(ny, nx)
    # merge small parts into their most-shared upright neighbour part (repeat: a merged speck may still be small)
    for _ in range(6):
        ids, cnt = np.unique(lab[lab >= 0], return_counts=True)
        in_band = np.bincount(lab[edge & (lab >= 0)], minlength=lab.max() + 1)[ids]
        small = set(ids[(cnt < MIN_PART_CELLS) | (in_band >= HALO_SHARE * cnt)].tolist())
        if not small:
            break
        pairs = np.r_[np.stack([lab[:, :-1].ravel(), lab[:, 1:].ravel()], 1),
                      np.stack([lab[:-1].ravel(), lab[1:].ravel()], 1)]
        pairs = pairs[(pairs >= 0).all(1) & (pairs[:, 0] != pairs[:, 1])]
        pairs = np.r_[pairs, pairs[:, ::-1]]
        lut = np.arange(lab.max() + 1)
        changed = False
        for sid in small:
            nb = pairs[pairs[:, 0] == sid, 1]
            if len(nb):
                v, n = np.unique(nb, return_counts=True)
                lut[sid] = int(v[np.argmax(n)])
                changed = True
        if not changed:
            break
        for _ in range(8):          # resolve chains (a -> b -> c)
            lut = lut[lut]
        lab = np.where(lab >= 0, lut[np.maximum(lab, 0)], -1)
    # boundaries inside the silhouette band stay as the plain solid closure (joined, bridged): the edge's back surface
    # covers the front's sunk halo triangles at the rest pose, so cutting there costs rest-pose texels
    bh = up[:, 1:] & up[:, :-1] & (lab[:, 1:] != lab[:, :-1]) & ~edge[:, 1:] & ~edge[:, :-1]
    bv = up[1:] & up[:-1] & (lab[1:] != lab[:-1]) & ~edge[1:] & ~edge[:-1]
    return lab, bh, bv, edge


def _masked_blur(val: np.ndarray, lab: np.ndarray | None, up: np.ndarray, sx: float, sy: float) -> np.ndarray:
    """Normalised Gaussian blur of val over `up`, never mixing two parts (per-part bounding-box crops)."""
    def one(v, w):
        num = cv2.GaussianBlur((v * w).astype(np.float32), (0, 0), sigmaX=sx, sigmaY=sy)
        den = cv2.GaussianBlur(w.astype(np.float32), (0, 0), sigmaX=sx, sigmaY=sy)
        return num / np.maximum(den, 1e-6)
    out = val.astype(np.float64).copy()
    pad = int(3 * max(sx, sy)) + 2
    for k in np.unique(lab[lab >= 0]):
        ys, xs = np.nonzero(lab == k)
        y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, lab.shape[0])
        x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, lab.shape[1])
        m = lab[y0:y1, x0:x1] == k
        b = one(np.nan_to_num(val[y0:y1, x0:x1]), m)
        sub = out[y0:y1, x0:x1]
        sub[m] = b[m]
    return out


def _thickness(up: np.ndarray, P: np.ndarray, right: np.ndarray, upv: np.ndarray, tmax: float,
               n_exp: float, lab: np.ndarray | None = None, bh: np.ndarray | None = None,
               bv: np.ndarray | None = None) -> np.ndarray:
    """Per-row superellipse cross-sections over the runs of upright vertices, capped by DEPTH_K x the vertex's own
    column run (a part is no deeper than its vertical extent: wing tips, eaves and banners over open ground stay thin),
    smoothed vertically, 0 on the outline."""
    ny, nx = up.shape
    Tt = np.zeros((ny, nx))
    lat = P @ right                      # lateral position (m) of each front vertex
    ver = P @ upv                        # vertical (camera up) position (m)
    cap = np.zeros((ny, nx))
    for i in range(nx):
        col = up[:, i]
        if not col.any():
            continue
        for a, b in _runs(col, None if bv is None else bv[:, i]):
            m = b - a
            cap[a:b, i] = DEPTH_K * abs(ver[a, i] - ver[b - 1, i]) * (m + 1) / max(m - 1, 1)
    for j in range(ny):
        row = up[j]
        if not row.any():
            continue
        for a, b in _runs(row, None if bh is None else bh[j]):           # run [a, b)
            m = b - a
            width = abs(lat[j, b - 1] - lat[j, a]) * (m + 1) / max(m - 1, 1)
            D = min(DEPTH_K * width, tmax)
            s = (np.arange(m) + 1.0) / (m + 1.0)
            Tt[j, a:b] = D * np.clip(1 - np.abs(2 * s - 1) ** n_exp, 0, 1) ** (1 / n_exp)
    Tt = np.minimum(Tt, cap)
    if lab is not None:
        return np.where(up, _masked_blur(Tt, lab, up, 0.6, SMOOTH_Y_CELLS), 0.0)
    w = up.astype(np.float32)
    num = cv2.GaussianBlur((Tt * w).astype(np.float32), (0, 0), sigmaX=0.6, sigmaY=SMOOTH_Y_CELLS)
    den = cv2.GaussianBlur(w, (0, 0), sigmaX=0.6, sigmaY=SMOOTH_Y_CELLS)
    Tt = np.where(up, num / np.maximum(den, 1e-6), 0.0)
    return Tt


def _outline(up: np.ndarray) -> np.ndarray:
    """Upright vertices with a 4-neighbour that is not upright (or on the grid border): thickness 0, welded."""
    p = np.pad(up, 1, constant_values=False)
    inner = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return up & ~inner


def member_axis(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Position of each px along a thin segment's principal axis (px units, centred)."""
    q = np.stack([xs, ys], 1).astype(np.float64)
    q -= q.mean(0)
    w, v = np.linalg.eigh(q.T @ q)
    return q @ v[:, np.argmax(w)]


def straighten_thin(ld: dict, cam: dict) -> tuple[dict, dict]:
    """Thin members (native row runs narrower than THIN_M: poles, spires, blades, posts) are straightened: each
    connected thin segment's monocular depth is replaced by a robust planar fit, so a pole is one straight member
    instead of a ribbon that wobbles with the depth model's noise. Moves along the rays only (rest pose unchanged)."""
    import math
    import stronghold_full3d_common as SC
    mask, z = ld["mask"], ld["z"]
    mh, mw = mask.shape
    run = np.zeros(mask.shape, np.float64)
    for j in range(mh):
        d = np.diff(np.r_[0, mask[j].astype(np.int8), 0])
        for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            run[j, a:b] = b - a
    mpp = np.where(mask, z, 0) * 2 * math.tan(math.radians(cam["fov"]) / 2) / SC.H * SC.SCALE
    thin = mask & (run * mpp < THIN_M)
    if not thin.any():
        return ld, {"thinPx": 0}
    # each connected thin segment (a pole between its banners, one blade, one post) is a straight member: a robust
    # (Tukey IRLS) line z = a + b t along its own principal axis t, so its depth is constant across its width; tiny
    # specks keep their depth. (A plane z = a + b y + c x let the depth model's edge bleed on a 1-3 px member - a
    # background-deep edge column - tilt it about its own axis: with the mask's thin-feature px kept (drop_fringe),
    # the Stronghold lyceum spire turned edge-on at pan_sweep_left, its front covered 1 px and the 4 px of back
    # behind it rendered from inside as a black half-spire.)
    zn = z.copy()
    n, lab, st, _ = cv2.connectedComponentsWithStats(thin.astype(np.uint8), connectivity=8)
    fitted = 0
    for k in range(1, n):
        if st[k, cv2.CC_STAT_HEIGHT] < THIN_MIN_ROWS:
            continue
        ys, xs = np.nonzero(lab == k)
        zv = z[ys, xs]
        ok = np.isfinite(zv)
        if ok.sum() < THIN_MIN_ROWS:
            continue
        t = member_axis(xs, ys)
        A = np.stack([np.ones(ok.sum()), t[ok]], 1)
        wv = np.ones(len(A))
        for _ in range(10):
            sol, *_ = np.linalg.lstsq(A * wv[:, None], zv[ok] * wv, rcond=None)
            res = A @ sol - zv[ok]
            sc = 1.4826 * np.median(np.abs(res)) + 1e-6
            u = res / (4.685 * sc)
            wv = np.where(np.abs(u) < 1, (1 - u * u) ** 2, 0.0)
        zn[ys, xs] = np.stack([np.ones(len(ys)), t], 1) @ sol
        fitted += 1
    moved = np.abs(zn - z)[thin]
    return dict(ld, z=zn), {"thinPx": int(thin.sum()), "thinSegments": fitted,
                            "thinMovedP95M": round(float(np.nanpercentile(moved, 95)), 2)}


def back_fill(front: np.ndarray, mbig: np.ndarray, erode_tx: int = BACK_ERODE_TX,
              blur_tx: float = BACK_BLUR_TX) -> np.ndarray:
    """Back-half source texture without the sprite's edge band: the texels within erode_tx of the mask outline (the
    anti-aliased halo, where the painting's sky / ground colour is mixed in) and everything outside are replaced by
    the interior's colour pushed outwards (normalised blur at growing scales), then lightly blurred. The arc-length
    back UVs start at the row's own edge texel, so without this a side wall opens on that halo colour (a pale patch)."""
    k = 2 * erode_tx + 1
    inner = cv2.erode(mbig.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    if inner.sum() < 16:
        inner = mbig.copy()
    out = front.astype(np.float32).copy()
    done = inner.copy()
    w = inner.astype(np.float32)
    src = front.astype(np.float32) * w[..., None]
    for sg in (2, 4, 8, 16, 32, 64):
        den = cv2.GaussianBlur(w, (0, 0), sg)
        num = cv2.GaussianBlur(src, (0, 0), sg)
        ok = ~done & (den > 1e-3)
        out[ok] = num[ok] / den[ok][:, None]
        done |= ok
        if done.all():
            break
    out[~done] = front[inner].mean(0) if inner.any() else out[~done]
    if blur_tx > 0:
        out = cv2.GaussianBlur(out, (0, 0), blur_tx)
        out[inner] = 0.5 * out[inner] + 0.5 * front[inner]      # keep interior detail, soften only its texture noise
    return out


def wall_texels(front: np.ndarray, mbig: np.ndarray, edge_xy: np.ndarray, far_xy: np.ndarray,
                inner: float = WALL_INNER_TX, k: int = WALL_BAND_K, radius: float = WALL_BAND_RADIUS_TX):
    """One existing texel per closing wall, chosen spatially with no tonal change.

    A wall is edge-on at rest and repeats its near edge along its depth; sampling the edge itself smeared an edge
    highlight (a lit window) along the wall as a bright streak. Instead each wall takes a single texel of the
    building's own de-lit front: of the in-mask texels within `radius` of the edge's midpoint and at least `inner`
    texels from its edge line, on the near side of that line (away from the cut triangle's far vertex), the `k`
    nearest the midpoint; of those, the one of median luminance rank. The colour is that texel, unmodified.
    A step on the silhouette (the near vertices are the outline ring, whose in-mask part is the 1-2 texel outline
    itself: Cove tbcvdock) has no near-side texel that far in; its band is then taken the same way on the far side,
    i.e. inward into the building. Such walls are counted (`silhouette`), not hidden.
    front (th, tw, 3), mbig (th, tw); edge_xy (m, 2, 2) the near edge's two ends and far_xy (m, 2) the far vertex, in
    texel coordinates (x, y). Returns ((m, 2) integer texel (x, y), silhouette count). Raises when a wall has no
    in-mask texel `inner`+ texels from its edge within `radius` on either side (fail closed: no wall without a
    texel of its own building)."""
    from scipy.spatial import cKDTree
    m = len(edge_xy)
    if m == 0:
        return np.zeros((0, 2), np.int64), 0
    iy, ix = np.nonzero(mbig)
    if len(ix) == 0:
        raise SystemExit("wall_texels: the building has no in-mask texel")
    pts = np.stack([ix + 0.5, iy + 0.5], 1)
    tree = cKDTree(pts)
    lum = front[iy, ix] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    out = np.zeros((m, 2), np.int64)
    sil = 0
    for w in range(m):
        a, b = edge_xy[w]
        mid = 0.5 * (a + b)
        e = b - a
        el = float(np.hypot(*e))
        rf = far_xy[w] - a
        sf = (e[0] * rf[1] - e[1] * rf[0]) / max(el, 1e-12)
        if el < 1e-9 or abs(sf) < 1e-9:
            raise SystemExit(f"wall_texels: wall {w} at texel {mid.round(1).tolist()} has a degenerate cut triangle (edge {edge_xy[w].round(2).tolist()}, far {np.round(far_xy[w], 2).tolist()})")
        side = -np.sign(sf)                                       # the near side: away from the far vertex
        j = np.asarray(tree.query_ball_point(mid, radius), np.int64)
        d = np.hypot(*(pts[j] - mid).T)
        rel = pts[j] - a
        sd = (e[0] * rel[:, 1] - e[1] * rel[:, 0]) / el          # signed distance from the edge line
        o = np.argsort(d, kind="stable")
        j, sd = j[o], sd[o]
        band = j[sd * side >= inner][:k]
        if len(band) == 0:
            band = j[-sd * side >= inner][:k]
            sil += 1
        if len(band) == 0:
            raise SystemExit(f"wall_texels: wall {w} at texel {mid.round(1).tolist()} has no in-mask texel {inner}+ "
                             f"texels from its edge within {radius} texels")
        pick = band[np.argsort(lum[band], kind="stable")[len(band) // 2]]
        out[w] = ix[pick], iy[pick]
    return out, sil


def _edge_table(tris: np.ndarray, n: int):
    """(key, a, b, third) per triangle edge, a < b, key = a * n + b."""
    t = np.asarray(tris, np.int64)
    a = np.concatenate([t[:, 0], t[:, 1], t[:, 2]])
    b = np.concatenate([t[:, 1], t[:, 2], t[:, 0]])
    c = np.concatenate([t[:, 2], t[:, 0], t[:, 1]])
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return lo * n + hi, lo, hi, c


def cap_cut(lid: str, m: dict, F: np.ndarray, drop: np.ndarray, cam: dict, sgn: float = 1.0) -> dict:
    """Close a solid (build_solid) that a frame-edge fray (BL.edge_fray*) cuts open.

    The fray removes front and back triangles by their rest-camera centroid, so the solid ends in an open cross-section
    along the fray line: from a camera moved toward the cut side the back sheet's inside shows through it (the game's
    Cull Back drops it: Necropolis tbncdock orbit -18, ~8k see-through px). Front and back vertices of one grid vertex
    lie on the same camera ray and every grid cell's front and back triangles share their centroid ray, so the kept
    front's cut edge (u, v) and the kept back's cut edge (u', v') lie on the same two rays. A cap quad u, v, v', u'
    therefore lies in the plane of those rays: edge-on at the rest camera (the rest pose is unchanged; checked by
    WR.rest_area_or_exit), watertight with both sheets, and wound toward the removed side. Each cap carries one
    existing in-mask front texel of the building (wall_texels, the closing-wall rule), unmodified.
    Three counted variants: a front cut edge with back vertices on both rays but no back triangle on that pair (a back
    cell left out by the all-upright rule beside a rim vertex) is capped on those vertices (capsWithoutBackEdge); one
    whose other end is ground (no back vertex on that ray: thickness 0, as on the welded outline) gets a cap triangle
    to that front vertex (capsToGround); a back cut edge whose front cut is on sunk step triangles (own vertices, no
    shared index) is capped against the deepest kept front edge on its rays (capsOnUnsharedFrontEdge). A back cut edge
    under a front the fray did not cut on those rays is a hole and fails closed. A welded rim edge needs no cap.
    m: the build_solid mesh (frontTris, P, n, uv, tris, albedo, frontMask; optional capTris / wallEdges from an
    earlier fray); F: its triangles before this fray, drop: the triangles this fray removes. Mutates m."""
    P = np.asarray(m["P"], np.float64)
    F = np.asarray(F, np.int64)
    nv = len(P)
    nf = int(m["frontTris"])
    ncap0 = int(m.get("capTris", 0))
    nb1 = len(F) - ncap0
    keep = ~drop
    px, py, _ = T.project(cam, P)
    ray = np.round(px * 256).astype(np.int64) * (1 << 31) + np.round(py * 256).astype(np.int64)

    def cut_edges(sel_all: np.ndarray, sel_keep: np.ndarray):
        kk, ka, kb, _ = _edge_table(F[sel_all & sel_keep], nv)
        dk, da, db, dc = _edge_table(F[sel_all & ~sel_keep], nv)
        uk, cnt = np.unique(kk, return_counts=True)
        once = uk[cnt == 1]
        hit = np.isin(dk, once)
        _, first = np.unique(dk[hit], return_index=True)
        return da[hit][first], db[hit][first], dc[hit][first]

    idx = np.arange(len(F))
    # closing walls are zero-thickness sheets inside the front: a fray through one leaves a sheet edge, not an opening
    wv0, wv1 = m.get("wallVerts", (0, 0))
    is_wall = (np.arange(nv) >= wv0) & (np.arange(nv) < wv1)
    fu, fv, fw = cut_edges(idx < nf, keep)
    nwe = ~(is_wall[fu] & is_wall[fv])
    fu, fv, fw = fu[nwe], fv[nwe], fw[nwe]
    bu, bv, bw = cut_edges((idx >= nf) & (idx < nb1), keep)
    back_pair = {}
    back_far = {}
    for a, b, c in zip(bu, bv, bw):
        ka, kb = ray[a], ray[b]
        back_pair[(min(ka, kb), max(ka, kb))] = (a, b)
        back_far[(min(ka, kb), max(ka, kb))] = c
    bt_all = F[nf:nb1]
    back_on_ray = {}
    for q in np.unique(bt_all):
        back_on_ray.setdefault(ray[q], q)
    quads, far, used, open_at, no_back_edge, to_ground = [], [], set(), [], 0, 0
    for u, v, w in zip(fu, fv, fw):
        k = (min(ray[u], ray[v]), max(ray[u], ray[v]))
        hit = back_pair.get(k)
        if hit is None:
            qa, qb = back_on_ray.get(ray[u]), back_on_ray.get(ray[v])
            deep = [q for q, f in ((qa, u), (qb, v)) if q is not None and np.linalg.norm(P[q] - P[f]) > 1e-6]
            if not deep:
                continue                                    # ground / welded: no volume behind this edge
            if qa is None or qb is None:
                # one end is ground (no back on its ray: thickness 0 there, as on the welded outline; a diagonal
                # neighbour of a non-rim upright vertex, Factory tbfamark): a cap triangle to that front vertex
                quads.append((u, v, v if qb is None else qb, u if qa is None else qa))
                far.append(w)
                to_ground += 1
                continue
            # the back's vertices on both rays exist but no back triangle had this edge (a back cell dropped by the
            # all-upright rule next to a rim vertex, Bulwark tbbha201 at the fray's row limit): cap on them
            quads.append((u, v, qb, qa))
            far.append(w)
            no_back_edge += 1
            continue
        used.add(k)
        a, b = hit if ray[hit[0]] == ray[u] else hit[::-1]
        if np.linalg.norm(P[a] - P[u]) < 1e-6 and np.linalg.norm(P[b] - P[v]) < 1e-6:
            continue                                        # welded rim edge: already closed
        quads.append((u, v, b, a))
        far.append(w)
    open_back, back_only = 0, 0
    front_on_pair = None
    for k, (a, b) in back_pair.items():
        if k in used:
            continue
        if front_on_pair is None:
            # kept front edges by ray pair: a sunk step triangle has its own vertices, so its cut edge shares no index
            # with the dropped neighbour and is not found above (Cove tbcvnix1: 1 edge)
            _, ea, eb, _ = _edge_table(F[(idx < nf) & keep], nv)
            front_on_pair = {}
            for x, y in zip(ea, eb):
                kx, ky = ray[x], ray[y]
                if kx != ky and not (is_wall[x] and is_wall[y]):
                    front_on_pair.setdefault((min(kx, ky), max(kx, ky)), []).append((x, y))
            _, da, db, _ = _edge_table(F[(idx < nf) & ~keep], nv)
            front_dropped = {(min(ray[x], ray[y]), max(ray[x], ray[y])) for x, y in zip(da, db)}
        # only where the fray cut the front on the same rays too (a back cut under a whole front is a hole: refused)
        cand = front_on_pair.get(k) if k in front_dropped else None
        if cand:
            # the deepest kept front edge on the pair: the front surface the back closes against there
            x, y = max(cand, key=lambda e: float(np.linalg.norm(P[e[0]] - cam["pos"]) + np.linalg.norm(P[e[1]] - cam["pos"])))
            if ray[x] != ray[a]:
                x, y = y, x
            quads.append((x, y, b, a))
            far.append(back_far[k])
            back_only += 1
            continue
        open_back += 1
        on = lambda q: [round(float(np.linalg.norm(P[x] - cam["pos"])), 3) for x in np.nonzero(ray == ray[q])[0]]
        open_at.append(["back", round(float(px[a]), 1), round(float(py[a]), 1), round(float(px[b]), 1),
                        round(float(py[b]), 1), on(a), on(b)])
    if open_back:
        raise SystemExit(f"{lid}: the fray cut leaves the solid open: {open_back} back cut edges with no cut front on "
                         f"their rays (a hole in the back under a whole front); rest px, depths on each ray: {open_at[:5]}")
    keptF = F[keep]
    rep = {"capWalls": len(quads), "capTexelsSilhouette": 0, "capRestAreaMaxPx2": 0.0, "capsWithoutBackEdge": no_back_edge,
           "capsOnUnsharedFrontEdge": back_only, "capsToGround": to_ground}
    m_nf = int(keep[:nf].sum())
    m_ncap = int(keep[nb1:].sum())
    if not quads:
        m["tris"] = keptF.astype(np.int32)
        m["frontTris"] = m_nf
        m["capTris"] = m_ncap
        return rep
    Q = np.asarray(quads, np.int64)
    Pq = P[Q]                                                   # (k, 4, 3): u, v, v', u'
    tl = np.array([[0, 1, 2], [0, 2, 3]], np.int64)
    k = len(Q)
    loc = (np.arange(k)[:, None, None] * 4 + tl[None]).reshape(-1, 3)
    Pc = Pq.reshape(-1, 3)
    want = np.repeat(P[np.asarray(far)] - 0.5 * (Pq[:, 0] + Pq[:, 1]), 2, 0)
    loc = BL.orient(Pc, loc, want, sgn)
    g = np.cross(Pc[loc[:, 1]] - Pc[loc[:, 0]], Pc[loc[:, 2]] - Pc[loc[:, 0]])
    area = np.linalg.norm(g, axis=1)
    loc, g, area = loc[area > 1e-12], g[area > 1e-12], area[area > 1e-12]
    Nc = np.zeros((len(Pc), 3))
    for c in range(3):
        np.add.at(Nc, loc[:, c], g * sgn)
    Nc /= np.maximum(np.linalg.norm(Nc, axis=1, keepdims=True), 1e-12)
    cap_area = WR.rest_area_or_exit(lid, Pc, loc, lambda q: T.project(cam, q))
    # one existing in-mask front texel per cap (the closing-wall rule), in texel coordinates of the front half
    uv = np.asarray(m["uv"], np.float64)
    mbig = m["frontMask"]
    atlas = np.asarray(m["albedo"])
    th0, tw0 = mbig.shape
    thp, twp = atlas.shape[0], atlas.shape[1] // 2
    # texel coordinates from each vertex's own rest-camera frame position (every front vertex is on its pixel's ray;
    # a uv can be in-mask snapped or a closing wall's single texel, which put two edge ends on one texel)
    fx0, fy0, ffw, ffh = m["frontFrame"]
    tx = np.stack([(px - fx0) * tw0 / ffw, (py - fy0) * th0 / ffh], 1)
    front = atlas[:th0, :tw0]
    tex, sil = wall_texels(front, mbig, tx[Q[:, :2]], tx[np.asarray(far)])
    uvc = np.stack([(tex[:, 0] + 0.5) / (2 * twp), 1 - (tex[:, 1] + 0.5) / thp], 1)
    uvc = np.repeat(uvc, 4, 0)
    ax = np.round(uvc[:, 0] * 2 * twp - 0.5).astype(int)
    ay = np.round((1 - uvc[:, 1]) * thp - 0.5).astype(int)
    if (ax >= tw0).any() or not mbig[ay, ax].all():
        raise SystemExit(f"{lid}: a fray cap texel is not an in-mask front texel of the building")
    m["P"] = np.concatenate([P, Pc]).astype(np.asarray(m["P"]).dtype)
    m["n"] = np.concatenate([np.asarray(m["n"], np.float64), Nc]).astype(np.asarray(m["n"]).dtype)
    m["uv"] = np.concatenate([uv, uvc]).astype(np.float32)
    m["tris"] = np.concatenate([keptF, nv + loc]).astype(np.int32)
    m["frontTris"] = m_nf
    m["capTris"] = m_ncap + len(loc)
    edges = Pq[:, :2]
    m["wallEdges"] = np.concatenate([np.asarray(m.get("wallEdges", np.zeros((0, 2, 3))), np.float64).reshape(-1, 2, 3),
                                     edges])
    rep.update(capWalls=int(k), capTexelsSilhouette=int(sil), capRestAreaMaxPx2=float(f"{cap_area:.3g}"))
    return rep


def build_solid(lid: str, L: dict, ld: dict, cam: dict, rig: dict, sun, sgn: float, floor, parts: bool = False,
                fill_back: bool = False) -> dict:
    """Front relief (shared with the relief method, thin members straightened) + width-driven closed back.
    parts: the upright region is first split into parts at depth steps (PART_RATIO); each part is closed on its own
    (its own row / column runs, its own smoothing, its own outline welded), so a wing in front of a crag is as thin as
    the wing and no back surface bridges two parts."""
    ld, thin_rep = straighten_thin(ld, cam)
    fs = BL.front_surface(L, ld, cam, rig, sun, sgn, 1.0, sink_cuts=True)
    P, zz, valid, keep = fs["P"], fs["zz"].astype(np.float64), fs["valid"], fs["keep"]
    ny, nx = zz.shape
    R = T.rays(cam, fs["FX"], fs["FY"])
    zt = _grid_zt(ld, fs["px"], fs["py"])
    fin = np.isfinite(zt)
    h = np.where(fin, (np.where(fin, zt, 0) - zz) * np.abs(R @ floor.n), np.inf)
    up = _clean(valid & (h > H_UP_M), valid)
    flat_g = None
    if ld.get("flat") is not None:
        # RELIEF_TUNE flat (a painted plume / cloud card): no volume, the front card only
        fm = ld["flat"]
        mh, mw = fm.shape
        sx = np.clip((fs["px"] / SC.SCALE).astype(int), 0, mw - 1)
        sy = np.clip((fs["py"] / SC.SCALE).astype(int), 0, mh - 1)
        flat_g = fm[sy, sx] & valid
        up = _clean(up & ~flat_g, valid)
    ground = valid & ~up & fin
    z_new = zz
    tune = TUNE.get(lid, {})
    tmax = float(tune.get("tmax", ld["thick"] if ld["kind"] == "crag" else T_MAX_M))
    n_exp = float(tune.get("n", PROFILE_N))
    lab = bh = bv = None
    if parts:
        cstep = float(tune.get("partColor", 0.0))
        chroma = _grid_chroma(L, fs["px"], fs["py"], fs["fw"], fs["fh"]) if cstep > 0 else None
        lab, bh, bv, pedge = _parts(up, zz, float(tune.get("partRatio", PART_RATIO)), chroma, cstep)
    Tt = _thickness(up, P, np.asarray(cam["right"], np.float64), np.asarray(cam["up"], np.float64), tmax, n_exp,
                    lab, bh, bv)
    w = up.astype(np.float32)
    zs = cv2.GaussianBlur((z_new * w).astype(np.float32), (0, 0), BACK_Z_SIGMA)
    zs = zs / np.maximum(cv2.GaussianBlur(w, (0, 0), BACK_Z_SIGMA), 1e-6)
    if parts:
        # inside the silhouette band the back is the plain solid closure's (it covers the sunk halo at the rest pose);
        # the part closure takes over from the band inwards
        Tt0 = _thickness(up, P, np.asarray(cam["right"], np.float64), np.asarray(cam["up"], np.float64), tmax, n_exp)
        zsp = _masked_blur(z_new, lab, up, BACK_Z_SIGMA, BACK_Z_SIGMA)
        Tt = np.where(pedge, Tt0, Tt)
        zs = np.where(pedge, zs, zsp)
    rim = _outline(up)
    if parts and PART_WELD:
        # both sides of a part boundary are welded (thickness 0): each part closes on its own outline
        rim = rim.copy()
        rim[:, 1:] |= bh
        rim[:, :-1] |= bh
        rim[1:] |= bv
        rim[:-1] |= bv
    Tt[rim] = 0.0
    # back depth: the smoothed front depth (so the back does not repeat the front's steps) plus the thickness
    zb = np.where(rim, z_new, np.maximum(z_new, zs) + Tt)
    # a sunk depth-step triangle (front_surface sink_cuts) lies at its farthest vertex's depth; the smoothed back can
    # pass in front of it there and show through the front as a 1-3 px line of back texels (Bulwark tbbucas3, Unity
    # full3d_full x 317-319 rows 195-326: a pale line the runtime lights, dark in the offline preview; the same rule
    # removes dark back slivers at two other Bulwark buildings). Every upright, non-rim back vertex of a sunk triangle is kept
    # behind that triangle's depth. A rim vertex keeps its weld (raising it let the closing walls on the outline show
    # their backs past the silhouette: Cove tbcvnmp2 orbit -18 see-through ~17k px).
    ct = fs["cutTris"]
    sink_raised = 0
    zsink = np.zeros((ny, nx))
    if len(ct):
        zsink = np.zeros(ny * nx)
        np.maximum.at(zsink, ct.ravel(), np.repeat(zz.ravel()[ct].max(1), 3))
        zsink = zsink.reshape(ny, nx)
        need = up & ~rim & (zb < zsink * (1 + SINK_BACK_MARGIN))
        zb = np.where(need, zsink * (1 + SINK_BACK_MARGIN), zb)
        sink_raised = int(need.sum())
    Pb = cam["pos"] + R * zb[..., None]

    Pf, Nf, U, Vv, tf = fs["Pf"], fs["Nf"], fs["U"], fs["Vv"], fs["tf"]
    nv = len(Pf)
    # back vertices: every upright grid vertex (rim ones coincide with the front, but keep their own uv / normal)
    upf = up.ravel()
    bidx = np.full(ny * nx, -1)
    bsel = np.nonzero(upf)[0]
    bidx[bsel] = nv + np.arange(len(bsel))
    Pbk = Pb.reshape(-1, 3)[bsel]
    # arc-length u per row run of the back (v as the front)
    u_grid = (fs["px"] / fs["fw"]).astype(np.float64)
    v_grid = (1 - fs["py"] / fs["fh"]).astype(np.float64)
    ub = np.zeros((ny, nx))
    for j in range(ny):
        row = up[j]
        if not row.any():
            continue
        for a, b in _runs(row, None if bh is None else bh[j]):
            seg = np.linalg.norm(np.diff(Pb[j, a:b], axis=0), axis=-1)
            A = np.r_[0.0, np.cumsum(seg)]
            if A[-1] < 1e-6:
                ub[j, a:b] = u_grid[j, a:b]
            else:
                ub[j, a:b] = u_grid[j, a] + A / A[-1] * (u_grid[j, b - 1] - u_grid[j, a])
    UVb = np.stack([ub.ravel()[bsel], v_grid.ravel()[bsel]], 1)
    # back triangles: every grid cell triangle over three upright vertices (not cut: the back is smooth)
    j_, i_ = np.meshgrid(np.arange(ny - 1), np.arange(nx - 1), indexing="ij")
    a_ = (j_ * nx + i_).ravel()
    gt = np.concatenate([np.stack([a_, a_ + 1, a_ + nx], 1), np.stack([a_ + 1, a_ + nx + 1, a_ + nx], 1)])
    gt = gt[upf[gt].all(1)]
    # a back triangle on a sunk front triangle's own three vertices, with a welded rim vertex still in front of the sunk
    # depth and no closing wall on that vertex, sits in front of the sunk front at the rest pose and faces away: the
    # game (Cull Back) drops it and shows what is behind the sunk front. It is dropped here, so the sunk front's texels
    # are what the rest pose shows. Where the rim vertex tops a closing wall the triangle is kept: it closes the side
    # past the wall (dropping those too opened Cove tbcvnmp2's rigging: orbit -18 see-through 8.4k -> 23.8k px).
    rim_over, rim_graze = 0, 0
    if len(ct):
        shallow = (rim & (zb < zsink * (1 + SINK_BACK_MARGIN))).ravel()
        walled = np.zeros(ny * nx, bool)
        walled[fs["wallGrid"]] = True
        shallow &= ~walled
        key = lambda t: np.sort(t, 1) @ np.array([1, ny * nx, (ny * nx) ** 2], np.int64)
        on_sunk = np.isin(key(gt), key(ct)) & shallow[gt].any(1)
        if SINK_RIM_GRAZE_DROP:
            shw = (rim & (zb < zsink * (1 + SINK_BACK_MARGIN))).ravel() & walled
            cand = np.nonzero(np.isin(key(gt), key(ct)) & shw[gt].any(1) & ~on_sunk)[0]
            hit = cand[grazing(Pb.reshape(-1, 3), gt[cand], cam["pos"], float(SINK_RIM_GRAZE_DROP["maxCos"]))]
            on_sunk[hit] = True
            rim_graze = int(len(hit))
        rim_over = int(on_sunk.sum())
        gt = gt[~on_sunk]
    if parts and not PART_BRIDGE:           # no back triangle bridges two parts
        lf = lab.ravel()
        ef = pedge.ravel()
        same = (lf[gt[:, 0]] == lf[gt[:, 1]]) & (lf[gt[:, 0]] == lf[gt[:, 2]])
        gt = gt[same | ef[gt].any(1)]
    bt = bidx[gt]
    V = np.concatenate([Pf, Pbk])
    ray_b = R.reshape(-1, 3)[bsel]
    ray_b = ray_b / np.linalg.norm(ray_b, axis=-1, keepdims=True)
    bt = BL.orient(V, bt, ray_b[bt - nv].mean(1), sgn)
    # back normals: area-weighted from the back triangles, pointing away from the camera
    fn = np.cross(V[bt[:, 1]] - V[bt[:, 0]], V[bt[:, 2]] - V[bt[:, 0]]) * sgn
    Nb = np.zeros((len(Pbk), 3))
    for k in range(3):
        np.add.at(Nb, bt[:, k] - nv, fn)
    bad = np.linalg.norm(Nb, axis=-1) < 1e-12
    Nb[bad] = ray_b[bad]
    Nb /= np.linalg.norm(Nb, axis=-1, keepdims=True)
    flip = (Nb * ray_b).sum(-1) < 0
    Nb[flip] = -Nb[flip]
    N = np.concatenate([Nf, Nb])
    UV = np.concatenate([np.stack([U, Vv], 1), UVb])
    F = np.concatenate([tf, bt])
    front, mbig, clipped = BL.front_albedo(L, ld["mask"], fs["n"], fs["fw"], fs["fh"], rig, sun)
    # atlas = front | back, each padded to a multiple of TEX_ALIGN texels (edge colour) so every mip level keeps the
    # same texel registration. The back half is the front art with its painted highlights capped at the building's
    # own BACK_LUM_Q luminance quantile and darkened by BACK_DARKEN: a highlight is baked light, not albedo, and a
    # back face turned to the key light would otherwise blow it out.
    th0, tw0 = front.shape[:2]
    thp, twp = -(-th0 // TEX_ALIGN) * TEX_ALIGN, -(-tw0 // TEX_ALIGN) * TEX_ALIGN
    lum = front @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    if fill_back:
        # edge-filled source, contrast compressed toward the building's own median colour (both the painted highlights
        # and the painted shadows: a back / side is lit by the runtime, not by the painting)
        bsrc = back_fill(front, mbig)
        med = np.median(front[mbig], 0) if mbig.any() else np.full(3, 0.5, np.float32)
        bc = med + (bsrc - med) * BACK_FILL_CONTRAST
        blum = bc @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        cap = float(np.quantile(lum[mbig], BACK_FILL_LUM_Q)) if mbig.any() else 1.0
        backt = bc * (np.minimum(blum, cap) / np.maximum(blum, 1e-6))[..., None] * BACK_FILL_DARKEN
    else:
        cap = float(np.quantile(lum[mbig], BACK_LUM_Q)) if mbig.any() else 1.0
        backt = front * (np.minimum(lum, cap) / np.maximum(lum, 1e-6))[..., None] * BACK_DARKEN
    pad = ((0, thp - th0), (0, twp - tw0), (0, 0))
    atlas = np.concatenate([np.pad(front, pad, mode="edge"), np.pad(backt, pad, mode="edge")], 1)
    nf = len(Pf)
    # closing walls (the last 4 vertices per wall of the front, BL.closing_walls: top a, top b, bottom b, bottom a):
    # all four corners on one existing front texel of this building (wall_texels), at its centre
    nwall = int(fs["closingWalls"])
    wall_tx = np.zeros((0, 2), np.int64)
    wall_area, wall_edges, wall_sil = 0.0, np.zeros((0, 2, 3)), 0
    if nwall:
        w0 = nf - 4 * nwall
        # the near edge at its grid vertices' own frame positions (not the in-mask-snapped uv, where two silhouette
        # ring vertices can share one texel), in texel coordinates
        gxs, gys = BL.grid_axis(fs["fw"]), BL.grid_axis(fs["fh"])
        eg = np.asarray(fs["wallEdgeGrid"]).reshape(nwall, 3)
        exy = np.stack([(gxs[eg % nx] + 0.5) * tw0 / fs["fw"], (gys[eg // nx] + 0.5) * th0 / fs["fh"]], -1)
        edge_xy, far_xy = exy[:, :2], exy[:, 2]
        wall_tx, wall_sil = wall_texels(front, mbig, edge_xy, far_xy)
        UV[w0:nf, 0] = np.repeat((wall_tx[:, 0] + 0.5) / tw0, 4)
        UV[w0:nf, 1] = np.repeat(1 - (wall_tx[:, 1] + 0.5) / th0, 4)
        # fail closed: walls are edge-on at the rest camera (town_full3d_wall_rest)
        wall_area = WR.rest_area_or_exit(lid, Pf[w0:nf], fs["tf"][-2 * nwall:] - w0, lambda q: T.project(cam, q))
        wall_edges = Pf[w0:nf].reshape(nwall, 4, 3)[:, :2]
    uu = UV[:, 0] * (tw0 / twp) * 0.5
    uu[nf:] += 0.5
    UV = np.stack([uu, 1 - (1 - UV[:, 1]) * (th0 / thp)], 1)
    if nwall:
        # fail closed: every wall corner lands on a texel centre of the atlas front half that is one of this
        # building's in-mask front texels (no tonal change, no back-half art)
        ax = UV[w0:nf, 0] * atlas.shape[1] - 0.5
        ay = (1 - UV[w0:nf, 1]) * atlas.shape[0] - 0.5
        if not (np.allclose(ax, np.round(ax), atol=1e-3) and np.allclose(ay, np.round(ay), atol=1e-3)):
            raise SystemExit(f"{lid}: a closing-wall uv is not on a texel centre")
        ax, ay = np.round(ax).astype(int), np.round(ay).astype(int)
        if (ax >= tw0).any() or not mbig[ay, ax].all() or not np.array_equal(atlas[ay, ax], front[ay, ax]):
            raise SystemExit(f"{lid}: a closing-wall texel is not an in-mask front texel of the building")
    front = atlas
    tv = Tt[up & ~rim]
    rep = {"upShare": round(float(up[valid].mean()), 3), "groundShare": round(float(ground[valid].mean()), 3),
           "hUpM": H_UP_M, "depthK": DEPTH_K, "tmaxM": tmax, "profileN": n_exp,
           "thickP50M": round(float(np.median(tv)), 2) if tv.size else 0.0,
           "thickP95M": round(float(np.percentile(tv, 95)), 2) if tv.size else 0.0,
           "sunkTris": int(fs["cut"].sum()), "closingWalls": int(fs["closingWalls"]), "wallTexels": {"innerTx": WALL_INNER_TX, "bandK": WALL_BAND_K, "distinct": int(len(np.unique(wall_tx, axis=0))), "silhouette": int(wall_sil), "radiusTx": WALL_BAND_RADIUS_TX}, "wallRestAreaMaxPx2": float(f"{wall_area:.3g}"), "sinkBackRaised": sink_raised, "backDroppedOnSunkRim": rim_over, "backDroppedGrazingWalled": rim_graze, **thin_rep,
           "backTris": int(len(bt)), "tune": tune,
           **({"flat": {**ld["flatRep"], "gridCells": int(flat_g.sum())}} if flat_g is not None else {}),
           **({"backFill": {"erodeTx": BACK_ERODE_TX, "blurTx": BACK_BLUR_TX, "contrast": BACK_FILL_CONTRAST, "lumQ": BACK_FILL_LUM_Q, "darken": BACK_FILL_DARKEN}} if fill_back else {}),
           **({"parts": {"partRatio": float(tune.get("partRatio", PART_RATIO)), "minPartCells": MIN_PART_CELLS,
                         "count": int(len(np.unique(lab[lab >= 0]))),
                         "boundaryEdges": int(bh.sum() + bv.sum())}} if parts else {})}
    return {"P": V, "n": N, "uv": UV.astype(np.float32), "tris": F.astype(np.int32), "albedo": front.astype(np.float32),
            "texelsPerPx": float(BL.BUILD_SCALE), "frontTris": int(len(tf)), "sideQuads": 0,
            "clippedShare": clipped, "bentShare": fs["bentShare"], "cutTris": int(fs["cut"].sum()),
            "texSize": [front.shape[1], front.shape[0]], "solid": rep, "wallEdges": wall_edges,
            "frontMask": mbig, "frontFrame": [float(L["x"] * SC.SCALE), float(L["y"] * SC.SCALE), float(fs["fw"]),
                                              float(fs["fh"])],
            "wallVerts": [int(nf - 4 * nwall), int(nf)]}
