"""Conflux full-3D, phase 2: whole-scene integration of the building layers (ground contact and footing).

Every building layer's HoMM3 sprite paints more than the building: the ledge, stairs, plinth, rubble and path the
building stands on. Where the registered mesh does not cover those painted ground pixels, the building reads as
floating or cut off (the 2026-09-27 review: "the fort just sits there"). A skirt restores them as geometry:

  * coverage  the layer's meshes are z-buffered in the reference camera (per-triangle depth, painter's order);
  * region    sprite pixels outside the (dilated) mesh silhouette, in the lower part of the building (below the
              70th-percentile row of its silhouette, or the whole sprite for a mesh-less layer), on terrain (not sky),
              off the flowing water, in components of at least SKIRT_MIN_PX;
  * depth     a harmonic membrane in inverse depth: the mesh's own depth where the skirt touches the building, the
              terrain's depth everywhere else on its border, so it runs from the building's foot down to the
              ground with no step on either side; drawn 0.3 % toward the camera so it covers the terrain it drapes;
  * albedo    the sprite's painted colour divided by the Hex/Lit irradiance of the membrane's own normals (the rig
              the whole scene is baked against), cross-faded into the terrain albedo over the last FEATHER_PX of
              its outer border, so the join to the terrain carries no colour edge.

The skirt is a lit Mesh_Skirt_<layer> piece of the layer prefab (the runtime rebinds it to Hex/Lit like the building).
Proof tier: generated artifact / editor render. Not in-game.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

import conflux_full3d_env as E

W, H = E.W, E.H
SKIRT_MIN_PX = 200
FEATHER_PX = 8
SKIRT_GRID = 2
TOWARD_CAMERA = 0.997


def raster_depth(cam, verts_world: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Camera depth (along fwd) of the nearest triangle per frame pixel; inf where uncovered."""
    px, py, zc = E.project(cam, verts_world)
    zb = np.full((H, W), np.inf, np.float32)
    ok = (zc[faces] > 0.1).all(1)
    f = faces[ok]
    tz = zc[f].mean(1)
    pts = np.stack([px, py], 1)
    tri = pts[f]
    inside = ((tri[..., 0].max(1) >= 0) & (tri[..., 0].min(1) < W) & (tri[..., 1].max(1) >= 0) & (tri[..., 1].min(1) < H))
    f, tz, tri = f[inside], tz[inside], tri[inside]
    order = np.argsort(-tz)
    layer = np.full((H, W), np.inf, np.float32)
    for i in order:
        cv2.fillConvexPoly(layer, np.round(tri[i] * 4).astype(np.int32), float(tz[i]), lineType=cv2.LINE_8, shift=2)
    np.minimum(zb, layer, out=zb)
    return zb


def membrane(inner: np.ndarray, fixed: np.ndarray, value: np.ndarray) -> np.ndarray:
    """Harmonic interpolation of `value` (given where `fixed`) over the pixels of `inner` (5-point Laplacian)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve

    ys, xs = np.nonzero(inner)
    n = len(ys)
    out = value.copy()
    if n == 0:
        return out
    idx = -np.ones(inner.shape, np.int64)
    idx[ys, xs] = np.arange(n)
    rows, cols, vals = [np.arange(n)], [np.arange(n)], [np.zeros(n)]
    rhs = np.zeros(n)
    deg = np.zeros(n)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        yy, xx = ys + dy, xs + dx
        ok = (yy >= 0) & (yy < inner.shape[0]) & (xx >= 0) & (xx < inner.shape[1])
        yy_, xx_ = np.clip(yy, 0, inner.shape[0] - 1), np.clip(xx, 0, inner.shape[1] - 1)
        nb_in = ok & inner[yy_, xx_]
        nb_fix = ok & ~inner[yy_, xx_] & fixed[yy_, xx_]
        deg += nb_in + nb_fix
        rows.append(np.nonzero(nb_in)[0]); cols.append(idx[yy_[nb_in], xx_[nb_in]]); vals.append(-np.ones(int(nb_in.sum())))
        rhs[nb_fix] += value[yy_[nb_fix], xx_[nb_fix]]
    deg = np.maximum(deg, 1)
    vals[0] = deg
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    out[ys, xs] = spsolve(A, rhs)
    return out


def skirt(ctx, layer: str, rgba: np.ndarray, mesh_depth: np.ndarray, fd: dict, terrain_albedo_lin: np.ndarray,
          whole_sprite: bool = False) -> dict | None:
    """One layer's skirt (see module doc): mesh arrays in world space + an albedo texture over its bbox."""
    alpha = rgba[..., 3] > 127
    zs = fd["zs"]
    terr = ~np.isnan(zs)
    covered = np.isfinite(mesh_depth)
    cov_d = cv2.dilate(covered.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    cand = alpha & ~cov_d & terr & ~fd["water"]
    if not whole_sprite:
        if not covered.any():
            return None
        ys_m = np.nonzero(covered & alpha)[0] if (covered & alpha).any() else np.nonzero(covered)[0]
        cand &= np.arange(H)[:, None] >= np.percentile(ys_m, 70)
    ncomp, lab, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    keep = np.zeros(ncomp, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= SKIRT_MIN_PX
    region = keep[lab]
    if region.sum() < SKIRT_MIN_PX:
        return None
    # Inverse depth: mesh depth on the building side, terrain depth elsewhere on the border.
    zf = E.filled_depth(zs)
    inv_val = np.where(covered, 1.0 / np.maximum(mesh_depth, 1e-3), 1.0 / zf).astype(np.float64)
    near_mesh = cv2.dilate(covered.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    # Pixels between the silhouette and the skirt (the dilation ring) take the nearest mesh depth.
    if covered.any():
        from scipy.ndimage import distance_transform_edt

        _, (iy, ix) = distance_transform_edt(~covered, return_indices=True)
        ring = near_mesh & ~covered
        inv_val[ring] = 1.0 / np.maximum(mesh_depth[iy[ring], ix[ring]], 1e-3)
    fixed = ~region
    inv = membrane(region, fixed, inv_val)
    zsk = 1.0 / np.maximum(inv, 1e-4)
    ys, xs = np.nonzero(region)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    # Grid over the bbox, cells kept where all four corners are skirt (dilated by one cell so edges are covered).
    gx_ = np.unique(np.r_[np.arange(x0, x1, SKIRT_GRID), x1 - 1])
    gy_ = np.unique(np.r_[np.arange(y0, y1, SKIRT_GRID), y1 - 1])
    gx, gy = np.meshgrid(gx_, gy_)
    reg_d = cv2.dilate(region.astype(np.uint8), np.ones((2 * SKIRT_GRID + 1,) * 2, np.uint8)).astype(bool)
    vk = reg_d[gy, gx]
    zz = zsk[gy, gx]
    P = ctx.cpos + E.rays(ctx.cam, gx.astype(np.float64), gy.astype(np.float64)) * (zz * TOWARD_CAMERA)[..., None]
    dx = np.gradient(P, axis=1); dy = np.gradient(P, axis=0)
    nrm = np.cross(dx, dy)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-12
    nrm[(nrm * (ctx.cpos - P)).sum(-1) < 0] *= -1
    nx_ = len(gx_)
    j, i = np.meshgrid(np.arange(len(gy_) - 1), np.arange(nx_ - 1), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    tris = tris[vk.ravel()[tris].all(1)]
    uv = np.stack([(gx - x0 + 0.5) / (x1 - x0), 1 - (gy - y0 + 0.5) / (y1 - y0)], -1).reshape(-1, 2)
    # Albedo over the bbox: sprite / L(n), feathered into the terrain albedo at the outer border.
    nf = cv2.resize(nrm.astype(np.float32), (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    nf /= np.linalg.norm(nf, axis=-1, keepdims=True) + 1e-9
    L = E.light(nf, ctx.rig, ctx.sun)
    Lm = float(np.median(E.lum(L)))
    spr = E.srgb_to_lin(rgba[y0:y1, x0:x1, :3].astype(np.float32) / 255)
    alb = spr / np.maximum(L, 0.18 * Lm)
    ter = terrain_albedo_lin[y0:y1, x0:x1]
    from scipy.ndimage import distance_transform_edt

    reg_c = region[y0:y1, x0:x1]
    outer = ~(reg_c | covered[y0:y1, x0:x1] | cov_d[y0:y1, x0:x1])
    d_out = distance_transform_edt(~outer)
    w = np.clip(d_out / FEATHER_PX, 0, 1)[..., None]
    alb = alb * w + ter * (1 - w)
    alb = np.where(reg_c[..., None] | (d_out[..., None] < 3), alb, ter)
    mx = alb.max(-1, keepdims=True)
    alb = np.where(mx > 0.95, alb * 0.95 / np.maximum(mx, 1e-6), alb)
    img = (E.lin_to_srgb(alb) * 255 + 0.5).astype(np.uint8)
    lift = float(np.median((zf[ys, xs] - zsk[ys, xs]) / zf[ys, xs]))
    return {"P": P.reshape(-1, 3), "n": nrm.reshape(-1, 3), "uv": uv, "tris": tris, "img": img, "z": zsk, "region": region,
            "stats": {"px": int(region.sum()), "tris": int(len(tris)), "bbox": [int(x0), int(y0), int(x1), int(y1)],
                      "medianRelLiftOverTerrain": round(lift, 4)}}


LEDGE_BAND_PX = 16      # the slab's side/underside: covered pixels this close above the silhouette's bottom edge
LEDGE_REACH = (41, 25)  # px ellipse (w, h) the ledge spreads from the slab toward the ground it stands on
LEDGE_SNOW_PX = 5       # px of snow at the band's top (the slab's lit rim) before the ledge turns to crag rock
LEDGE_ROCK_PX = 60      # px from the band's top over which the rock fades (the outer feather does the rest)
LEDGE_FACE = (0.6, 0.8)  # (up, toward camera) weights of the ledge's shading normal
LEDGE_STREAK = 0.6      # share of snow in the crag face's streaks
LEDGE_JITTER_PX = 5.0   # noise amplitude that breaks the snow line, the rock line and the ledge's lower edge


def ledge(ctx, mesh_depth: np.ndarray, fd: dict, terrain_albedo_lin: np.ndarray, snow_lin: np.ndarray,
          rock_lin: np.ndarray) -> dict | None:
    """A crag building whose mesh ends in a slab (the Altar of Air on its snow ledge) has no painted ground outside its
    silhouette for skirt(): the slab edge and its dark underside hang in front of a far mountain slope. The ledge is a
    lit membrane that covers the slab's side/underside band (drawn just in front of the mesh there) and runs from it
    down to the terrain behind: a thin broken snow rim, then the mountain's own crag rock, then the painted slope,
    with noise-broken transitions and lower edge so no straight slab line or oval halo remains."""
    covered = np.isfinite(mesh_depth)
    if not covered.any():
        return None
    zs = fd["zs"]
    zf = E.filled_depth(zs)
    ys_c, xs_c = np.nonzero(covered)
    bottom = np.full(W, -1)
    np.maximum.at(bottom, xs_c, ys_c)
    yy = np.arange(H)[:, None]
    band = covered & (bottom[None, :] >= 0) & (bottom[None, :] - yy < LEDGE_BAND_PX)
    rng = np.random.default_rng(1729)
    noise = cv2.GaussianBlur(rng.standard_normal((H, W)).astype(np.float32), (0, 0), 3.0)
    noise /= noise.std() + 1e-6
    col_n = cv2.GaussianBlur(rng.standard_normal((1, W)).astype(np.float32), (0, 0), 6.0)[0]
    col_n /= col_n.std() + 1e-6
    below = np.zeros((H, W), bool)
    for x in np.nonzero(bottom >= 0)[0]:
        reach = int(round(LEDGE_REACH[1] * float(np.clip(0.7 + 0.3 * col_n[x], 0.3, 1.0))))
        below[bottom[x] + 1:min(H, bottom[x] + 1 + reach), x] = True
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, LEDGE_REACH)
    spread = cv2.dilate(band.astype(np.uint8), k).astype(bool) & ~covered
    spread &= noise > -0.6  # ragged outer edge
    region = (band | ((below | spread) & ~covered)) & ~np.isnan(zs) & ~fd["water"]
    region = cv2.morphologyEx(region.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool) | band
    if region.sum() < SKIRT_MIN_PX:
        return None
    # Inverse depth: in front of the mesh on the band's upper border, the terrain on the outer border.
    inv_val = np.where(covered, 1.0 / np.maximum(mesh_depth * 0.995, 1e-3), 1.0 / zf).astype(np.float64)
    inv = membrane(region, ~region, inv_val)
    zsk = 1.0 / np.maximum(inv, 1e-4)
    zsk = np.where(band, np.minimum(zsk, mesh_depth * 0.995), zsk)
    # v: px below the band's top edge in each column, jittered so the snow and rock lines are broken.
    top = np.where(bottom >= 0, bottom - LEDGE_BAND_PX + 1, H)[None, :]
    v = (yy - top).astype(np.float32) + LEDGE_JITTER_PX * noise
    snow_w = np.clip(1 - (v - LEDGE_SNOW_PX) / 3.0, 0, 1)[..., None]
    rock_w = np.clip(1 - (v - LEDGE_SNOW_PX) / (LEDGE_ROCK_PX - LEDGE_SNOW_PX), 0, 1)[..., None]
    rock = rock_lin[None, None, :] * (0.85 + 0.15 * np.clip(noise, -2, 2)[..., None])
    # Snow streaks down the crag face (vertical noise), so the ledge reads as the mountain's own snowy rock.
    streak = cv2.GaussianBlur(rng.standard_normal((H, W)).astype(np.float32), (0, 0), sigmaX=1.5, sigmaY=6.0)
    streak /= streak.std() + 1e-6
    sw = (E.smoothstep(0.0, 0.8, streak) * np.clip(1 - v / (LEDGE_ROCK_PX + 6), 0, 1))[..., None] * LEDGE_STREAK
    rock = rock * (1 - sw) + snow_lin[None, None, :] * 0.85 * sw
    colour = terrain_albedo_lin * (1 - rock_w) + rock * rock_w
    colour = colour * (1 - snow_w) + snow_lin[None, None, :] * snow_w
    # The membrane recedes from the slab to the far slope, i.e. it is an overhang whose geometric normal faces down
    # and away from the sun: it rendered as a black block under the slab. It stands for the crag the slab rests on,
    # so it is shaded as a camera-facing mountain face (normal between world up and toward the camera).
    face = np.asarray(ctx.cam["fwd"], np.float64) * -LEDGE_FACE[1] + np.array([0.0, LEDGE_FACE[0], 0.0])
    face /= np.linalg.norm(face)
    return _membrane_mesh(ctx, region, zsk, colour, covered, band, terrain_albedo_lin, lit_source=False,
                          normal_override=face)


def _membrane_mesh(ctx, region, zsk, colour_lin, covered, cov_d, terrain_albedo_lin, lit_source: bool,
                   normal_override: np.ndarray | None = None) -> dict:
    """Grid mesh over `region` at depth `zsk` (TOWARD_CAMERA) with an albedo over its bbox: `colour_lin` (divided by
    the membrane's own Hex/Lit irradiance when it is a lit painting), feathered into the terrain albedo."""
    ys, xs = np.nonzero(region)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    gx_ = np.unique(np.r_[np.arange(x0, x1, SKIRT_GRID), x1 - 1])
    gy_ = np.unique(np.r_[np.arange(y0, y1, SKIRT_GRID), y1 - 1])
    gx, gy = np.meshgrid(gx_, gy_)
    reg_d = cv2.dilate(region.astype(np.uint8), np.ones((2 * SKIRT_GRID + 1,) * 2, np.uint8)).astype(bool)
    vk = reg_d[gy, gx]
    zz = zsk[gy, gx]
    P = ctx.cpos + E.rays(ctx.cam, gx.astype(np.float64), gy.astype(np.float64)) * (zz * TOWARD_CAMERA)[..., None]
    dx = np.gradient(P, axis=1); dy = np.gradient(P, axis=0)
    nrm = np.cross(dx, dy)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-12
    nrm[(nrm * (ctx.cpos - P)).sum(-1) < 0] *= -1
    if normal_override is not None:
        nrm = np.broadcast_to(np.asarray(normal_override, np.float64), nrm.shape).copy()
    nx_ = len(gx_)
    j, i = np.meshgrid(np.arange(len(gy_) - 1), np.arange(nx_ - 1), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    tris = tris[vk.ravel()[tris].all(1)]
    uv = np.stack([(gx - x0 + 0.5) / (x1 - x0), 1 - (gy - y0 + 0.5) / (y1 - y0)], -1).reshape(-1, 2)
    src = colour_lin[y0:y1, x0:x1]
    if lit_source:
        nf = cv2.resize(nrm.astype(np.float32), (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
        nf /= np.linalg.norm(nf, axis=-1, keepdims=True) + 1e-9
        L = E.light(nf, ctx.rig, ctx.sun)
        Lm = float(np.median(E.lum(L)))
        alb = src / np.maximum(L, 0.18 * Lm)
    else:
        alb = src.copy()
    ter = terrain_albedo_lin[y0:y1, x0:x1]
    from scipy.ndimage import distance_transform_edt

    reg_c = region[y0:y1, x0:x1]
    outer = ~(reg_c | covered[y0:y1, x0:x1] | cov_d[y0:y1, x0:x1])
    d_out = distance_transform_edt(~outer)
    w = np.clip(d_out / FEATHER_PX, 0, 1)[..., None]
    alb = alb * w + ter * (1 - w)
    alb = np.where(reg_c[..., None] | (d_out[..., None] < 3), alb, ter)
    mx = alb.max(-1, keepdims=True)
    alb = np.where(mx > 0.95, alb * 0.95 / np.maximum(mx, 1e-6), alb)
    img = (E.lin_to_srgb(alb) * 255 + 0.5).astype(np.uint8)
    return {"P": P.reshape(-1, 3), "n": nrm.reshape(-1, 3), "uv": uv, "tris": tris, "img": img, "z": zsk, "region": region,
            "stats": {"px": int(region.sum()), "tris": int(len(tris)), "bbox": [int(x0), int(y0), int(x1), int(y1)],
                      "kind": "ledge"}}


def patch_mesh(ctx, mask: np.ndarray, zmap: np.ndarray, toward: float, grid: int = 2) -> dict | None:
    """Camera-registered grid over `mask` at depth `zmap` * `toward` (an overlay drawn just in front of the surface it
    lies on, e.g. the lava over its painted crater). uv spans the mask's bbox (texture space of the overlay)."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    gx_ = np.unique(np.r_[np.arange(x0, x1, grid), x1 - 1])
    gy_ = np.unique(np.r_[np.arange(y0, y1, grid), y1 - 1])
    gx, gy = np.meshgrid(gx_, gy_)
    md = cv2.dilate(mask.astype(np.uint8), np.ones((2 * grid + 1,) * 2, np.uint8)).astype(bool)
    vk = md[gy, gx]
    zz = zmap[gy, gx]
    P = ctx.cpos + E.rays(ctx.cam, gx.astype(np.float64), gy.astype(np.float64)) * (zz * toward)[..., None]
    nx_ = len(gx_)
    j, i = np.meshgrid(np.arange(len(gy_) - 1), np.arange(nx_ - 1), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    tris = tris[vk.ravel()[tris].all(1)]
    uv = np.stack([(gx - x0 + 0.5) / (x1 - x0), 1 - (gy - y0 + 0.5) / (y1 - y0)], -1).reshape(-1, 2)
    n = np.tile(-ctx.cam["fwd"], (P.shape[0] * P.shape[1], 1))
    return {"P": P.reshape(-1, 3), "n": n, "uv": uv, "tris": tris, "bbox": [int(x0), int(y0), int(x1), int(y1)]}


def compact(P, n, uv, tris, *extra):
    """Drop vertices no triangle uses (grid meshes keep the whole lattice otherwise)."""
    used = np.unique(tris)
    remap = -np.ones(len(P), np.int64)
    remap[used] = np.arange(len(used))
    return (P[used], n[used], uv[used], remap[tris]) + tuple(e[used] for e in extra)
