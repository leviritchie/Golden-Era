"""Stronghold full-3D: the world outside the default frame for the vanilla town camera's pan / sweep (no Meshy).

The vanilla cityHuman2 camera (conflux_town_camera_pan) looks up to ~52 deg either side of the rest heading and
~37 deg down, from positions up to ~19 painting metres off the rest pose; the default frame covers +-40 deg. Outside
the frame the painting says nothing, so the outer world is built from the same measured field the frame's extension
uses (stronghold_full3d_terrain.world_field: the calibrated floor plane plus the canyon walls continued from the
painted edge profiles, closing in only outside the frame):

  * mesh     a polar grid about the rest camera (THETA_STEP deg x a distance step growing with rho) to RHO_MAX m.
             Triangles wholly EDGE_PX inside the default frame are dropped; kept vertices inside the frame move back
             along their own rest ray behind the frame surface (or down to the skyline where the frame shows sky), so
             the default frame is unchanged at the vertex level (frameIntrusions, checked, must be 0).
  * albedo   the frame extension's own synthesis (stronghold_full3d_ground: vanilla desert textures in world space,
             strata palette measured from the painting, the rect's low-frequency colour toned out with world distance
             from the rect), so the outer ground continues the in-frame extension with the same formula.
  * scatter  vanilla Olden Era desert rocks (Rock_desert_new_0x, Des_Rock_0x, their own textures) and a scrub kind
             from the vanilla Dead_thorns_01 bush with its vanilla texture re-tinted (luminance mapped onto the
             painting's measured scrub colours), placed only where the whole instance box projects outside the
             default frame. Bins: Mesh_Outer_boulders_<mesh>, Mesh_Outer_scrub_<k>.
  * water    none: the Stronghold painting has no river leaving the frame (declared, not omitted silently).
  * coverage the retained outer triangles sampled on the field's XZ grid (pan_coverage.npz) for
             tools/validate_town_scene3d_contract.py; a geometry proxy, not pixel proof.
Proof tier: generated artifact. Editor renders are the review evidence; nothing here is runtime proof.
"""
from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import stronghold_full3d_ground as G

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SEED = 1707
THETA_MAX = 70.0           # deg either side of the rest heading (pan reaches ~53 deg from moved cameras)
THETA_STEP = 0.5
RHO_MIN, RHO_MAX = 6.0, 398.0
EDGE_PX = 12.0
PUSH_REL, PUSH_ABS = 0.004, 0.04
THETA_SPLIT = 36.0
RHO_BANDS = ((0.0, 70.0, 0.035), (70.0, 170.0, 0.035), (170.0, RHO_MAX + 1, 0.045))  # (rho0, rho1, deg per texel)
FACE = 0.7
MAX_TEX = 4096
NORMAL_LEAN = 0.35
EXT_FEATHER_PX = 60.0      # TOWN_FULL3D_EXTSRC: the outpaint fades in over this many canvas px from its border
# scatter
ROCK_MESHES = SC.FP.ROCK_MESHES
SCRUB_MESH, SCRUB_TEX = SC.FP.SCRUB_MESH, SC.FP.SCRUB_TEX
SCATTER_POLICY = SC.FP.PERIPHERY_SCATTER   # validate_town_scene3d_contract.py enforces the catalog against it
if bool(SCATTER_POLICY["scrub"]["required"]) != (SCRUB_MESH is not None):
    raise SystemExit(f"periphery: PERIPHERY_SCATTER scrub.required {SCATTER_POLICY['scrub']['required']} disagrees "
                     f"with SCRUB_MESH {SCRUB_MESH!r}")
ROCK_SIZE_M, SCRUB_SIZE_M = SC.FP.ROCK_SIZE_M, SC.FP.SCRUB_SIZE_M   # painting m
SCATTER_RHO = (14.0, 260.0)
SCRUB_ROW0 = SC.FP.SCRUB_ROW0   # rect rows (1440x673) below which olive pixels are floor scrub


def cam_height(floor, cam) -> float:
    return float(floor.rel(cam["pos"][None])[0])


def rho_levels() -> np.ndarray:
    out, r = [RHO_MIN], RHO_MIN
    while r < RHO_MAX:
        r = r + float(np.clip(0.012 * r, 0.25, 4.0))
        out.append(min(r, RHO_MAX))
    return np.array(out)


def frame_depth_grid(grid: dict, cam) -> np.ndarray:
    """Forward depth of the frame terrain mesh per 1080p pixel (max over 3x3 vertices: conservative); NaN on sky."""
    P = grid["P"]
    zc = (P - cam["pos"]) @ cam["fwd"]
    zc = np.where(grid["keep"], zc, np.nan).astype(np.float32)
    zmax = cv2.dilate(np.nan_to_num(zc, nan=0.0), np.ones((3, 3), np.uint8))
    zmax = np.where(grid["keep"], zmax, np.nan)
    xs, ys = grid["xs"], grid["ys"]
    gx = np.clip(np.searchsorted(xs, np.arange(W)), 0, len(xs) - 1)
    gy = np.clip(np.searchsorted(ys, np.arange(H)), 0, len(ys) - 1)
    return zmax[np.ix_(gy, gx)]


def settle(cam, P, tris, zframe, sky):
    P = P.copy()
    px, py, zc = T.project(cam, P)
    infr = (px >= 0) & (px <= W) & (py >= 0) & (py <= H) & (zc > 0.05)
    deep = (px >= EDGE_PX) & (px <= W - EDGE_PX) & (py >= EDGE_PX) & (py <= H - EDGE_PX) & (zc > 0.05)
    tris = tris[~deep[tris].all(1)]
    used = np.zeros(len(P), bool)
    used[tris.ravel()] = True
    moved = used & infr
    qx = np.clip(px[moved], 0, W - 1)
    qy = np.clip(py[moved], 0, H - 1)
    xi, yi = np.round(qx).astype(int), np.round(qy).astype(int)
    zf = zframe[yi, xi]
    is_sky = sky[yi, xi] | ~np.isfinite(zf)
    first = np.where((~sky).any(0), np.argmax(~sky, 0), H - 1)
    ys_ = np.where(is_sky, np.minimum(first[xi] + 2, H - 1), qy)
    zf2 = zframe[np.round(ys_).astype(int), xi]
    zf2 = np.where(np.isfinite(zf2), zf2, np.nanmax(zframe))
    ztgt = np.maximum(zc[moved], zf2 * (1 + PUSH_REL) + PUSH_ABS)
    P[moved] = cam["pos"] + T.rays(cam, qx, ys_) * ztgt[:, None]
    return P, tris, {"moved": int(moved.sum()), "loweredToSkyline": int(is_sky.sum())}


def frame_intrusions(cam, P, zframe, sky) -> int:
    px, py, zc = T.project(cam, P)
    ins = (zc > 0.05) & (px >= 0) & (px <= W - 1) & (py >= 0) & (py <= H - 1)
    if not ins.any():
        return 0
    xi, yi = np.round(px[ins]).astype(int), np.round(py[ins]).astype(int)
    zf = zframe[yi, xi]
    bad = np.where(sky[yi, xi], True, np.isfinite(zf) & (zc[ins] < zf * (1 + 0.5 * PUSH_REL)))
    return int(bad.sum())


def polar_mesh(cam, field, zframe, sky) -> dict:
    ths = np.arange(-THETA_MAX, THETA_MAX + 1e-6, THETA_STEP)
    rhos = rho_levels()
    Th, R = np.meshgrid(ths, rhos)
    X, Z = T.polar_to_xz(cam, Th, R)
    Y = field.height(X, Z)
    P = np.stack([X, Y, Z], -1).reshape(-1, 3)
    nth = len(ths)
    j, i = np.meshgrid(np.arange(len(rhos) - 1), np.arange(nth - 1), indexing="ij")
    a = (j * nth + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nth], 1), np.stack([a + 1, a + nth + 1, a + nth], 1)])
    P0 = P.copy()
    P, tris, st = settle(cam, P, tris, zframe, sky)
    return {"P": P, "P0": P0, "tris": tris, "theta": Th.ravel(), "rho": R.ravel(), **st}


def coverage_raster(field, mesh: dict) -> dict:
    """Final retained triangle heights sampled on the field's XZ grid (-inf where no triangle)."""
    P = mesh["P"]
    t = mesh["tris"]
    nz, nx = field.h.shape
    outer_h = np.full((nz, nx), -np.inf, np.float32)
    xz = np.stack([(P[:, 0] - field.x0) / field.res, (P[:, 2] - field.z0) / field.res], -1)
    for face in t:
        q = xz[face]
        lo = np.maximum(np.ceil(q.min(0)).astype(int), 0)
        hi = np.minimum(np.floor(q.max(0)).astype(int), [nx - 1, nz - 1])
        if np.any(lo > hi):
            continue
        a, b, c = q
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-10:
            continue
        xx, zz = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        wa = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (zz - c[1])) / den
        wb = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (zz - c[1])) / den
        wc = 1 - wa - wb
        inside = (wa >= -1e-8) & (wb >= -1e-8) & (wc >= -1e-8)
        if inside.any():
            y = wa * P[face[0], 1] + wb * P[face[1], 1] + wc * P[face[2], 1]
            patch = outer_h[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            np.maximum(patch, y, out=patch, where=inside)
    return {"outer_h": outer_h, "covered": np.isfinite(outer_h)}


# ------------------------------------------------------------------------------------------------ texture pieces
def row_density(rho, hc) -> np.ndarray:
    rho = np.asarray(rho, np.float64)
    return np.maximum(hc / (rho * rho + hc * hc), FACE / np.maximum(rho, 1e-3))


def row_map(rho0, rho1, rad_per_row, hc):
    rr = np.linspace(rho0, rho1, 20001)
    d = row_density(rr, hc)
    g = np.concatenate([[0.0], np.cumsum(0.5 * (d[1:] + d[:-1]) * np.diff(rr))]) / rad_per_row
    return rr, g


def piece_layout(mesh: dict, hc: float) -> list[dict]:
    th, rho = mesh["theta"], mesh["rho"]
    t = mesh["tris"]
    ct, cr = th[t].mean(1), rho[t].mean(1)
    bucket = np.where(ct < -THETA_SPLIT, 0, np.where(ct > THETA_SPLIT, 2, 1))
    pieces = []
    for b, bname in enumerate(("L", "C", "R")):
        for k, (r0, r1, deg) in enumerate(RHO_BANDS):
            sel = (bucket == b) & (cr >= r0) & (cr < r1)
            if not sel.any():
                continue
            tt = t[sel]
            used = np.unique(tt)
            th0, th1 = float(th[used].min()), float(th[used].max())
            q0, q1 = float(rho[used].min()), float(rho[used].max())
            w = min(MAX_TEX, int(math.ceil((th1 - th0) / deg)))
            rad = math.radians(deg)
            rr, g = row_map(q0, q1, rad, hc)
            h = int(math.ceil(g[-1]))
            if h > MAX_TEX:
                rad *= h / MAX_TEX
                rr, g = row_map(q0, q1, rad, hc)
                h = MAX_TEX
            pieces.append({"name": f"Mesh_Outer{bname}{k}", "tris": tt, "used": used, "th": (th0, th1),
                           "rho": (q0, q1), "size": (max(w, 8), max(h, 8)), "rr": rr, "g": g,
                           "degPerTexel": [(th1 - th0) / max(w, 8), math.degrees(rad)]})
    return pieces


def piece_uv(pc: dict, th, rho) -> np.ndarray:
    w, h = pc["size"]
    u = (np.asarray(th) - pc["th"][0]) / max(pc["th"][1] - pc["th"][0], 1e-9)
    v = np.interp(rho, pc["rr"], pc["g"]) / pc["g"][-1]
    return np.stack([(u * (w - 1) + 0.5) / w, (v * (h - 1) + 0.5) / h], -1).astype(np.float32)


def soft_normal(field, cam, X, Z, Y):
    n = field.normal(X, Z, eps=1.5)
    P = np.stack([X, Y, Z], -1)
    v = cam["pos"] - P
    v /= np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9
    lean = np.array([0.0, 1.0, 0.0]) + v
    lean /= np.linalg.norm(lean, axis=-1, keepdims=True) + 1e-9
    n = n * (1 - NORMAL_LEAN) + lean * NORMAL_LEAN
    return n / (np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9)


def bake_piece(baker, field, floor, cam, pc: dict, device: str | None = None) -> np.ndarray:
    """Linear albedo of one polar piece with the frame extension's own formula (continuous at the frame edge).

    device (else TOWN_FULL3D_DEVICE, else cuda): cuda runs town_gpu_terrain.bake_piece (no fallback); this body is the
    cpu reference. Parity: test_town_gpu_terrain.py, docs/town_gpu_kernels.md "Terrain bake"."""
    import town_gpu_kernels as GK
    if GK.resolve_device(device) == "cuda":
        import town_gpu_terrain as GT
        return GT.bake_piece(baker, field, floor, cam, pc)
    w, h = pc["size"]
    th = pc["th"][0] + (np.arange(w) + 0.5) / w * (pc["th"][1] - pc["th"][0])
    g = (h - 1 - np.arange(h) + 0.5) / h * pc["g"][-1]          # row 0 = far end (v = 1)
    out = np.zeros((h, w, 3), np.float32)
    for r0 in range(0, h, 256):
        r1 = min(h, r0 + 256)
        rho = np.interp(g[r0:r1], pc["g"], pc["rr"])
        Th, R = np.meshgrid(th, rho)
        X, Z = T.polar_to_xz(cam, Th, R)
        Y = field.height(X, Z)
        P = np.stack([X, Y, Z], -1).astype(np.float32)
        n = soft_normal(field, cam, X, Z, Y).astype(np.float32)
        rel = floor.rel(P.astype(np.float64)).astype(np.float32)
        det, wall = G.synth_detail(P, n, rel)
        base_wall = G.palette_at(baker.pal, Y, Th)
        base_floor = G.floor_patches(baker.pal, X, Z)
        base = base_floor * (1 - wall[..., None]) + base_wall * wall[..., None]
        px, py, zc = T.project(cam, P.reshape(-1, 3).astype(np.float64))
        ok = zc > 0.5
        qx = np.clip(np.where(ok, px, np.where((P.reshape(-1, 3) - cam["pos"]) @ cam["right"] < 0, 0, W - 1)), 0, W - 1)
        qy = np.clip(np.where(ok, py, H - 1), 0, H - 1)
        xi, yi = qx.astype(int), qy.astype(int)
        edge = baker.edge_col[yi, xi].reshape(P.shape)
        d_edge = baker.d_rect_m[yi, xi].reshape(P.shape[:2])
        Pe = baker.P[yi, xi].reshape(P.shape)
        d_out = d_edge + np.hypot(P[..., 0] - Pe[..., 0], P[..., 2] - Pe[..., 2])
        tone = np.exp(-d_out / G.EDGE_TONE_M)[..., None] * (1 - 0.6 * wall[..., None])
        cav = (G.cavity(field, X, Z, wall) * G.baked_shade(field, X, Z, baker.rig, baker.sun, wall))[..., None]
        if baker.gs is None:
            out[r0:r1] = np.clip((edge * tone + base * (1 - tone)) * det * cav, 0, 1)
        else:
            # TOWN_FULL3D_GROUNDSRC: the authored floor (footprints from this piece's own texel grid and the rest
            # projection), walls from the synthesis, exactly as the frame extension does it
            _, rk, _ = G.synth_detail_parts(P, n, rel)
            wall_alb = (edge * tone + base_wall * (1 - tone)) * rk
            fp = G.footprint(P, np.where(ok, px, np.nan).reshape(P.shape[:2]),
                             np.where(ok, py, np.nan).reshape(P.shape[:2]))
            flo = baker.gs.floor(P, fp, d_out)
            ramp = T.smoothstep(0.0, baker.gs.shade_ramp_m, d_out).astype(np.float32)
            sh = np.power(np.maximum(cav[..., 0], 1e-3), wall + (1 - wall) * ramp)
            out[r0:r1] = np.clip((flo * (1 - wall[..., None]) + wall_alb * wall[..., None]) * sh[..., None], 0, 1)
        if baker.ext is not None:
            # TOWN_FULL3D_EXTSRC: where the rest ray lands on the canvas OUTSIDE the frame (the frame itself is the
            # terrain mesh's), the outpaint de-lit by this texel's normal, feathered in from the canvas border
            ex = baker.ext
            k = ex.get("k", 1)
            wc = ex["lin"].shape[1] // k
            cx = (np.where(ok, px, -1e6) - ex["x0"]).reshape(P.shape[:2]).astype(np.float32)
            cy = np.where(ok, py, -1e6).reshape(P.shape[:2]).astype(np.float32)
            d = np.minimum.reduce([cx, wc - 1 - cx, cy, H - 1 - cy])
            pxr = np.where(ok, px, W / 2).reshape(P.shape[:2])
            left = ((pxr < 0) | (pxr >= W)) & (d >= 0)
            if left.any():
                sx, sy = (cx, cy) if k == 1 else ((cx + 0.5) * k - 0.5, (cy + 0.5) * k - 0.5)
                samp = cv2.remap(ex["lin"], sx.astype(np.float32), sy.astype(np.float32), cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
                alb = np.clip(samp / np.maximum(baker.E.light(n, baker.rig, baker.sun), 0.02), 0, 1)
                w = (np.clip(d / EXT_FEATHER_PX, 0, 1) * left)[..., None]
                out[r0:r1] = out[r0:r1] * (1 - w) + alb * w
    return out


# ------------------------------------------------------------------------------------------------ scatter
def scrub_palette(baker, cam) -> np.ndarray:
    """The painting's scrub colours: olive pixels (g > r, g > b + 12) on the rect's floor rows (below HoMM3 y ~139),
    10 / 50 / 90th percentiles, de-lit by the rig's irradiance for ground facing up and toward the viewer."""
    import conflux_full3d_env as E
    p = T.painting().astype(np.int32)
    r, g, b = p[..., 0], p[..., 1], p[..., 2]
    m = (g > r + 2) & (g > b + 12) & (np.arange(p.shape[0])[:, None] > SCRUB_ROW0)
    if m.sum() < 200:
        raise SystemExit(f"periphery scrub palette: only {int(m.sum())} scrub-coloured pixels in the painting")
    q = np.percentile(p[m], [10, 50, 90], axis=0).astype(np.float32) / 255
    n = np.array([0.0, 1.0, 0.0]) - np.asarray(cam["fwd"])
    n = (n / np.linalg.norm(n)).astype(np.float32)
    L = E.light(n[None], baker.rig, baker.sun)[0]
    return np.clip(G.SC_srgb_to_lin(q) / L, 0, 1).astype(np.float32)


def retint(img_srgb: np.ndarray, ramp_lin: np.ndarray) -> np.ndarray:
    lin = G.SC_srgb_to_lin(img_srgb.astype(np.float32) / 255)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lo, hi = np.percentile(lum, 5), np.percentile(lum, 95)
    t = np.clip((lum - lo) / max(hi - lo, 1e-4), 0, 1)[..., None]
    col = np.where(t < 0.5, ramp_lin[0] + (ramp_lin[1] - ramp_lin[0]) * (t / 0.5),
                   ramp_lin[1] + (ramp_lin[2] - ramp_lin[1]) * ((t - 0.5) / 0.5))
    return (G.lin_to_srgb(np.clip(col, 0, 1)) * 255 + 0.5).astype(np.uint8)


def tone_to(img_srgb: np.ndarray, target_lin: np.ndarray) -> np.ndarray:
    """A vanilla texture toned to a target albedo: per-channel median match in linear light (detail kept)."""
    lin = G.SC_srgb_to_lin(img_srgb.astype(np.float32) / 255)
    med = np.median(lin.reshape(-1, 3), 0)
    out = np.clip(lin * (target_lin / np.maximum(med, 1e-4)), 0, 1)
    return (G.lin_to_srgb(out) * 255 + 0.5).astype(np.uint8)


def floor_target(baker, floor) -> np.ndarray:
    rel = floor.rel(baker.P[:TH, :TW].astype(np.float64))
    flm = (rel < 2.5) & ~baker.fd["sky"][:TH, :TW]
    return np.median(baker.alb_rect[flm], 0).astype(np.float32)


def load_vanilla(name: str):
    import stronghold_full3d_vanilla as V
    m = V.mesh(name)
    v = np.asarray(m["v"], np.float64)
    n = np.asarray(m["n"], np.float64)
    # model space is Z-up (Blender export): Y-up with X kept
    v = v[:, [0, 2, 1]] * np.array([1, 1, -1])
    n = n[:, [0, 2, 1]] * np.array([1, 1, -1])
    lo, hi = v.min(0), v.max(0)
    v = v - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    f = np.asarray(m["f"], np.int64)
    from stronghold_full3d_buildings import orient
    f = orient(v, f, n[f].mean(1), 1.0)
    return v, n, np.asarray(m["uv"], np.float32), f


def outside_frame(cam, base, hgt, rad, margin=3.0) -> np.ndarray:
    ok = np.ones(len(base), bool)
    for dx in (-1, 1):
        for dz in (-1, 1):
            for dy in (0, 1):
                c = base + np.stack([dx * rad, dy * hgt, dz * rad], 1)
                px, py, zc = T.project(cam, c)
                inside = (zc > 0.05) & (px > -margin) & (px < W + margin) & (py > -margin) & (py < H + margin)
                ok &= ~inside
    return ok


def sites(cam, field, floor, rng, spacing_fn, rel_max, slope_max):
    """Jittered polar sites (density falls with distance), on floor-ish ground, outside the default frame."""
    out = []
    rho = SCATTER_RHO[0]
    while rho < SCATTER_RHO[1]:
        sp = spacing_fn(rho)
        n = int(2 * THETA_MAX * math.pi / 180 * rho / sp)
        th = rng.uniform(-THETA_MAX + 1, THETA_MAX - 1, n)
        rr = rho + rng.uniform(0, sp, n)
        out.append(np.stack([th, rr], 1))
        rho += sp
    s = np.concatenate(out)
    X, Z = T.polar_to_xz(cam, s[:, 0], s[:, 1])
    Y = field.height(X, Z)
    P = np.stack([X, Y, Z], 1)
    rel = floor.rel(P)
    nrm = field.normal(X, Z, eps=1.0)
    slope = np.degrees(np.arccos(np.clip(nrm[:, 1], -1, 1)))
    keep = (rel < rel_max) & (slope < slope_max)
    return P[keep], s[keep, 1]


def merge(proto, base, yaw_deg, s, field):
    v, n, uv, f = proto
    Vs, Ns, UVs, Fs = [], [], [], []
    off = 0
    for b, yw, sc in zip(base, yaw_deg, s):
        a = math.radians(yw)
        c, sn = math.cos(a), math.sin(a)
        R = np.array([[c, 0, sn], [0, 1, 0], [-sn, 0, c]])
        vv = b + (v * sc) @ R.T
        # sit on the ground under the footprint (the lowest ground point under the instance, sunk 8%)
        foot = field.height(vv[:, 0], vv[:, 2])
        vv[:, 1] += float(np.min(foot)) - b[1] - 0.08 * sc * (v[:, 1].max())
        Vs.append(vv)
        Ns.append(n @ R.T)
        UVs.append(uv)
        Fs.append(f + off)
        off += len(v)
    return np.concatenate(Vs), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Fs)


# ------------------------------------------------------------------------------------------------ stage
def build(sc, prefix_env: str, state: dict, out_dir, dome_r: float, sky_az, sky_el) -> dict:
    """Writes the outer terrain / scatter bins into the environment prefab via sc.add_bin and pan_coverage.npz into
    out_dir; returns the catalog's periphery block (minus panCoverage) and the coverage row."""
    import time

    import stronghold_full3d_vanilla as V
    t0 = time.time()
    cam, field, floor, fd, grid, baker = (state[k] for k in ("cam", "field", "floor", "fd", "grid", "baker"))
    hc = cam_height(floor, cam)
    sky = fd["sky"]
    zframe = frame_depth_grid(grid, cam)
    mesh = polar_mesh(cam, field, zframe, sky)
    X0, Z0 = T.polar_to_xz(cam, mesh["theta"], mesh["rho"])
    nrm = soft_normal(field, cam, X0, Z0, field.height(X0, Z0))
    rep_pieces = {}
    for pc in piece_layout(mesh, hc):
        lin = bake_piece(baker, field, floor, cam, pc)
        used = pc["used"]
        remap = np.full(len(mesh["P"]), -1)
        remap[used] = np.arange(len(used))
        v = mesh["P"][used]
        tl = remap[pc["tris"]]
        from stronghold_full3d_buildings import orient
        f = orient(v, tl, nrm[used][tl].mean(1), 1.0)
        uv = piece_uv(pc, mesh["theta"][used], mesh["rho"][used])
        sc.add_bin(prefix_env, pc["name"], v, nrm[used], uv, f, lin, max_size=MAX_TEX,
                   extra={"mipBias": -0.5, "aniso": 8})
        rep_pieces[pc["name"]] = {"size": list(pc["size"]), "thetaDeg": [round(x, 2) for x in pc["th"]],
                                  "rhoM": [round(x, 1) for x in pc["rho"]], "tris": int(len(f)),
                                  "verts": int(len(used)), "degPerTexel": [round(x, 4) for x in pc["degPerTexel"]]}
        del lin
    t_bake = time.time() - t0

    # scatter
    rng = np.random.default_rng(SEED)
    rock_target = floor_target(baker, floor)
    scat = {}
    # boulders: denser near the wall feet (rel 0.5-6 m) and scattered on the floor
    Pr, rr = sites(cam, field, floor, rng, lambda r: 6.0 + 0.05 * r, rel_max=9.0, slope_max=40.0)
    size = rng.uniform(*ROCK_SIZE_M, len(Pr)) * (1 + 0.6 * np.clip(floor.rel(Pr) / 9.0, 0, 1))
    okr = outside_frame(cam, Pr, 0.7 * size, 0.6 * size)
    which = rng.integers(0, len(ROCK_MESHES), len(Pr))
    yaw = rng.uniform(0, 360, len(Pr))
    for k, (mname, tname) in enumerate(ROCK_MESHES.items()):
        sel = okr & (which == k)
        if not sel.any():
            continue
        v, n, uv, f = load_vanilla(mname)
        diam = float(max(np.ptp(v[:, 0]), np.ptp(v[:, 2])))
        Vv, Nn, UV, Fc = merge((v, n, uv, f), Pr[sel], yaw[sel], size[sel] / diam, field)
        img = np.asarray(Image.fromarray(V.tex(tname)).convert("RGB")) if isinstance(V.tex(tname), np.ndarray) \
            else np.asarray(V.tex(tname).convert("RGB"))
        name = f"Mesh_Outer_boulders_{k}"
        sc.add_bin(prefix_env, name, Vv, Nn, UV, Fc, img, srgb=True, max_size=1024)
        scat[name] = {"instances": int(sel.sum()), "tris": int(len(Fc)), "mesh": mname, "texture": tname}
    scat["_rock"] = {"sites": int(len(Pr)), "outsideFrame": int(okr.sum()), "prefixes": ["Mesh_Outer_boulders_"],
                     "source": "vanilla Olden Era desert rocks (resources.assets; see vanilla provenance)"}
    # scrub: the floor's dark bushes (a profile declaring scrub not required places none)
    if not SCATTER_POLICY["scrub"]["required"]:
        scat["_tree"] = {"sites": 0, "outsideFrame": 0, "prefixes": [], "source": SCATTER_POLICY["scrub"]["reason"]}
    else:
        Ps, rs = sites(cam, field, floor, rng, lambda r: 4.0 + 0.04 * r, rel_max=2.5, slope_max=18.0)
        ssz = rng.uniform(*SCRUB_SIZE_M, len(Ps))
        oks = outside_frame(cam, Ps, 0.55 * ssz, 0.55 * ssz)
        ramp = scrub_palette(baker, cam)
        tint = retint(V.tex(SCRUB_TEX), ramp)
        v, n, uv, f = load_vanilla(SCRUB_MESH)
        width = float(max(np.ptp(v[:, 0]), np.ptp(v[:, 2])))
        yaw = rng.uniform(0, 360, len(Ps))
        bands = ((0.0, 60.0), (60.0, 1e9))
        for k, (r0, r1) in enumerate(bands):
            sel = oks & (rs >= r0) & (rs < r1)
            if not sel.any():
                continue
            Vv, Nn, UV, Fc = merge((v, n, uv, f), Ps[sel], yaw[sel], ssz[sel] / width, field)
            name = f"Mesh_Outer_scrub_{k}"
            sc.add_bin(prefix_env, name, Vv, Nn, UV, Fc, tint, srgb=True, max_size=512)
            scat[name] = {"instances": int(sel.sum()), "tris": int(len(Fc)), "mesh": SCRUB_MESH,
                          "texture": f"{SCRUB_TEX} re-tinted to the painting's scrub ramp",
                          "rhoM": [r0, r1 if r1 < 1e8 else None]}
        scat["_tree"] = {"sites": int(len(Ps)), "outsideFrame": int(oks.sum()), "prefixes": ["Mesh_Outer_scrub_"],
                         "source": "vanilla Dead_thorns_01 bush, texture re-tinted (no desert tree exists in the "
                                   "vanilla desert kit; the painting's floor carries low scrub, not trees)",
                         "scrubRampLinear": np.round(ramp, 4).tolist()}

    # coverage + registration
    cov = coverage_raster(field, mesh)
    intr = frame_intrusions(cam, mesh["P"][np.unique(mesh["tris"])], zframe, sky)
    if intr:
        raise SystemExit(f"periphery: {intr} outer vertices draw over the default frame (registration broken)")
    out_dir.mkdir(parents=True, exist_ok=True)
    npz = out_dir / "pan_coverage.npz"
    np.savez_compressed(npz, x0=field.x0, z0=field.z0, res=field.res, h=field.h.astype(np.float32),
                        outer_h=cov["outer_h"], covered=cov["covered"],
                        cam_pos=cam["pos"], cam_fwd=cam["fwd"], cam_up=cam["up"], cam_right=cam["right"],
                        fov=cam["fov"], frame_wh=np.array([W, H]), frame_sky=sky, C=sc.C, cpos=sc.cpos,
                        depth_scale=sc.scale, dome_r=dome_r, sky_az=np.array(sky_az), sky_el=np.array(sky_el))
    per = {
        "panSource": "vanilla_city_camera_pan.json (cityHuman2 BhCityCameraController / SoCityCameraSettings human2)",
        "vanillaReference": {"scene": "cityHuman2", "note": SC.FP.PERIPHERY_VANILLA_NOTE},
        "mesh": {"thetaDeg": [-THETA_MAX, THETA_MAX], "rhoM": [RHO_MIN, RHO_MAX], "verts": int(len(mesh["P"])),
                 "tris": int(len(mesh["tris"])), "movedBehindFrame": mesh["moved"],
                 "loweredToSkyline": mesh["loweredToSkyline"], "frameIntrusions": intr},
        "pieces": rep_pieces,
        "water": dict(SC.FP.PERIPHERY_WATER),
        "scatter": scat,
        "albedo": "the frame extension's synthesis (vanilla desert textures in world space, strata palette measured "
                  f"from the painting, the rect's low-frequency colour toned out over {G.EDGE_TONE_M} m of world "
                  "distance from the rect): the same formula as the in-frame extension, continuous at the frame edge",
        "registration": "outer triangles wholly EDGE_PX inside the frame dropped; kept in-frame vertices moved back "
                        "along their rest ray behind the frame surface; scatter only where the whole instance box "
                        "projects outside the default frame. Vertex check only; editor pixels must verify",
        "meshyCredits": 0,
        "bakeSeconds": round(t_bake, 1), "seconds": round(time.time() - t0, 1),
    }
    cov_row = {"file": npz.name, "sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
               "coveredShare": round(float(cov["covered"].mean()), 4)}
    return {"periphery": per, "coverage": cov_row}
