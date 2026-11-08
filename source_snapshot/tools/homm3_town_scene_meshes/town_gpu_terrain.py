"""CUDA path of the town terrain synthesis: the periphery ring bake (stronghold_full3d_periphery.bake_piece) and the
height-field raymarch (stronghold_full3d_terrain.raymarch). Both reference functions stay the rule; this file re-runs
their arithmetic on the GPU in the reference's own dtypes and order, so the output is byte-identical to the CPU path
given the same inputs (tools/homm3_town_scene_meshes/test_town_gpu_terrain.py proves it).

How the bits match (measured, numpy 2.x / OpenCV 4.x / torch 2.11, docs/town_gpu_kernels.md "Terrain bake"):
  - elementwise IEEE ops (add, sub, mul, div, sqrt) in the reference's order and dtypes, including numpy's mixed-dtype
    promotion (float32 array op float64 array -> float64; float32 - int64 -> float64; float32 += float64 computes in
    float64 and rounds once to float32). Eager torch never fuses them into an FMA;
  - an array divided by a Python scalar: torch on CUDA multiplies by the scalar's reciprocal (two roundings), so every
    such division divides by a 0-d device tensor (sdiv);
  - cv2.remap INTER_LINEAR / BORDER_REPLICATE on float32: the map is quantised to 1/32 px (cvRound), the four weights are
    exact float32 products, the taps are summed left to right (remap);
  - np.interp: numpy's slopes, the j from its binary search and slope * (x - xp[j]) + fp[j] (interp);
  - (N, 3) float64 @ (3,) (OpenBLAS dgemv): fma(fma(x1 * v1, x0, v0), x2, v2) (gemv3, torch.addcmul fuses);
  - float32 sum / mean of 3 along the last axis: sequential.
Kept on the CPU (numpy, the reference's own calls, on the GPU's bit-identical inputs) because CUDA does not reproduce
their bits: transcendental functions (np.power, np.exp, np.log, np.arccos, np.hypot, np.cos / np.sin of the per-column
azimuths), np.interp of the per-row radius, the float32 (.., 3) @ (3,) light dots (OpenBLAS sgemv's order depends on N).
The one input that is NOT byte-identical: the vanilla detail layers' large-sigma blur (stronghold_full3d_ground.
detail_layer, cv2.GaussianBlur sigma = tile / 6) runs on the GPU as a separable float64 convolution with cv2's own
float32 kernel and BORDER_REFLECT_101; its difference to cv2 is measured and bounded by the parity test.
GROUNDSRC (baker.gs) is not ported: device cuda refuses it (SystemExit), --device cpu runs it. No silent fallback.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

W, H = SC.W, SC.H
torch = None
DEV = None


def require_cuda():
    global torch, DEV
    if DEV is None:
        import town_gpu_kernels as GK
        torch = GK.require_cuda()
        DEV = torch.device("cuda", torch.cuda.current_device())
    return torch


def up(a, dtype=None):
    t = torch.from_numpy(np.ascontiguousarray(a)).to(DEV)
    return t if dtype is None else t.to(dtype)


def dn(t) -> np.ndarray:
    return t.detach().cpu().numpy()


_SCALARS: dict = {}


def sdiv(t, s):
    """numpy's `array / python scalar` (one correctly rounded division, the array's dtype). The 0-d device tensor is
    cached by the scalar's exact bits (float.hex keeps -0.0 apart): building one per call is a host-to-device copy."""
    key = (float(s).hex(), t.dtype, t.device)
    d = _SCALARS.get(key)
    if d is None:
        d = _SCALARS[key] = torch.tensor(s, dtype=t.dtype, device=t.device)
    return t / d


def norm3(v):
    """np.linalg.norm(v, axis=-1) of 3-vectors: the squares summed in order."""
    return torch.sqrt((v[..., 0] * v[..., 0] + v[..., 1] * v[..., 1]) + v[..., 2] * v[..., 2])


def gemv3(x, v):
    """(.., 3) float64 @ (3,) float64 as OpenBLAS dgemv sums it: fma(fma(x1 v1, x0, v0), x2, v2)."""
    v = up(np.asarray(v, np.float64))
    acc = x[..., 1] * v[1]
    acc = torch.addcmul(acc, x[..., 0], v[0].expand_as(acc))
    return torch.addcmul(acc, x[..., 2], v[2].expand_as(acc))


def smoothstep(a, b, x):
    t = torch.clamp(sdiv(x.double() - a, b - a), 0, 1)
    return t * t * (3 - 2 * t)


def interp(x, xp: np.ndarray, fp: np.ndarray):
    """np.interp(x, xp, fp) for x (float64 tensor) with len(xp) <= x.numel() (numpy's precomputed slopes)."""
    xp = np.asarray(xp, np.float64)
    fp = np.asarray(fp, np.float64)
    if len(xp) < 2:
        raise SystemExit("town_gpu_terrain.interp: needs len(xp) >= 2")
    slopes = (fp[1:] - fp[:-1]) / (xp[1:] - xp[:-1])
    xpt, fpt, st = up(xp), up(fp), up(slopes)
    j = torch.searchsorted(xpt, x.contiguous(), right=True) - 1
    jc = j.clamp(0, len(xp) - 2)
    val = st[jc] * (x - xpt[jc]) + fpt[jc]
    val = torch.where(xpt[jc] == x, fpt[jc], val)
    out = torch.where(j < 0, fpt[0], torch.where(j >= len(xp) - 1, fpt[-1], val))
    return torch.where(torch.isnan(x), x, out)


def remap(tex, x, y):
    """cv2.remap(tex, x, y, INTER_LINEAR, borderMode=BORDER_REPLICATE) for a float32 (h, w, C) tex, float32 maps."""
    Xi = torch.round(x * 32).to(torch.int64)
    Yi = torch.round(y * 32).to(torch.int64)
    ix, iy = Xi >> 5, Yi >> 5
    ax = (Xi & 31).to(torch.float32) * (1.0 / 32)
    ay = (Yi & 31).to(torch.float32) * (1.0 / 32)
    h, w = tex.shape[:2]
    x0, x1 = ix.clamp(0, w - 1), (ix + 1).clamp(0, w - 1)
    y0, y1 = iy.clamp(0, h - 1), (iy + 1).clamp(0, h - 1)
    w0, w1, w2, w3 = (1 - ay) * (1 - ax), (1 - ay) * ax, ay * (1 - ax), ay * ax
    return ((tex[y0, x0] * w0[..., None] + tex[y0, x1] * w1[..., None]) + tex[y1, x0] * w2[..., None]) \
        + tex[y1, x1] * w3[..., None]


# ------------------------------------------------------------------------------------------------ field and noise
class GField:
    """T.Field on the device (float64 X, Z only, as every caller here passes)."""

    def __init__(self, field):
        self.f = field
        self.h = up(field.h)

    def sample(self, arr, X, Z):
        if X.dtype != torch.float64 or Z.dtype != torch.float64:
            raise SystemExit("town_gpu_terrain.GField: float64 coordinates only (the reference's promotion differs)")
        f = self.f
        cx = torch.clamp(sdiv(X - f.x0, f.res), 0, arr.shape[1] - 1.001)
        cz = torch.clamp(sdiv(Z - f.z0, f.res), 0, arr.shape[0] - 1.001)
        ix, iz = cx.to(torch.int64), cz.to(torch.int64)
        fx, fz = cx - ix.double(), cz - iz.double()
        return ((arr[iz, ix] * (1 - fx) + arr[iz, ix + 1] * fx) * (1 - fz)
                + (arr[iz + 1, ix] * (1 - fx) + arr[iz + 1, ix + 1] * fx) * fz)

    def height(self, X, Z):
        return self.sample(self.h, X, Z)

    def normal(self, X, Z, eps=1.0):
        hx = sdiv(self.height(X + eps, Z) - self.height(X - eps, Z), 2 * eps)
        hz = sdiv(self.height(X, Z + eps) - self.height(X, Z - eps), 2 * eps)
        n = torch.stack([-hx, torch.ones_like(hx), -hz], -1)
        return n / norm3(n)[..., None]


_LAT: dict = {}


def value_noise(x, z, seed, scale):
    lat = _LAT.get(seed)
    if lat is None:
        lat = _LAT[seed] = up(np.random.default_rng(seed).random((257, 257)).astype(np.float32))
    u, v = sdiv(x, scale), sdiv(z, scale)
    iu, iv = torch.floor(u).to(torch.int64), torch.floor(v).to(torch.int64)
    fu, fv = u.double() - iu.double(), v.double() - iv.double()       # float32 - int64 -> float64 (numpy)
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    iu, iv = torch.remainder(iu, 256), torch.remainder(iv, 256)
    a, b = lat[iv, iu], lat[iv, iu + 1]
    c, d = lat[iv + 1, iu], lat[iv + 1, iu + 1]
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


def fbm(x, z, seed, scale, octaves=5):
    s, amp, tot, nrm = scale, 1.0, 0.0, 0.0
    for o in range(octaves):
        tot = tot + amp * value_noise(x, z, seed + o, s)
        nrm += amp
        amp *= 0.5
        s *= 0.5
    return sdiv(tot, nrm)


# ------------------------------------------------------------------------------------------------ detail layers
_LAYERS: dict = {}


def detail_layer(name: str, source: str = "gpu"):
    """stronghold_full3d_ground.detail_layer on the device. source "gpu": the blur on the GPU (float64 separable
    convolution, cv2's kernel and border; not bit-identical to cv2, bounded by the parity test); "cpu": the reference's
    own cv2 layer uploaded (the parity test's byte-exact mode)."""
    import stronghold_full3d_ground as G
    key = (name, source)
    t = _LAYERS.get(key)
    if t is not None:
        return t
    if source == "cpu":
        t = up(G.detail_layer(name))
    elif source == "gpu":
        import cv2
        import torch.nn.functional as F
        img = G.V.tex(name).astype(np.float32) / 255
        lin = G.SC_srgb_to_lin(img)
        h, w = lin.shape[:2]
        sigma = h / 6
        ks = int(round(sigma * 4 * 2 + 1)) | 1                           # cv2 createGaussianKernels, float depth
        k = up(cv2.getGaussianKernel(ks, sigma, cv2.CV_32F).astype(np.float64).ravel())
        r = ks // 2
        x = up(np.tile(lin, (3, 3, 1)), torch.float64).permute(2, 0, 1)[None]     # (1, C, 3h, 3w)
        # BORDER_REFLECT_101 (cv2's default) is torch's "reflect"; only rows / cols that reach the centre tile are kept
        if r >= min(h, w):
            raise SystemExit(f"town_gpu_terrain.detail_layer {name}: blur radius {r} >= tile {h}x{w} (the tiled image "
                             "would need cv2's border rule); run TOWN_FULL3D_DEVICE=cpu")
        # the 3x3 tiling keeps cv2's BORDER_REFLECT_101 out of reach of the centre tile: a valid convolution suffices
        rows = x[:, :, h - r:2 * h + r, w - r:2 * w + r]
        C = rows.shape[1]
        a = F.conv2d(rows.reshape(1, C, rows.shape[2], -1).transpose(0, 1), k.view(1, 1, 1, -1))   # along x
        b = F.conv2d(a, k.view(1, 1, -1, 1))                                                       # along y
        low = b[:, 0].permute(1, 2, 0).contiguous().to(torch.float32)
        if low.shape[:2] != (h, w):
            raise SystemExit(f"town_gpu_terrain.detail_layer {name}: blur window {tuple(low.shape)} != {(h, w)}")
        linT = up(lin)
        t = linT / torch.clamp(low, min=1e-3)
        t = torch.cat([t[-2:], t, t[:2]], 0)
        t = torch.cat([t[:, -2:], t, t[:, :2]], 1).contiguous()
    else:
        raise SystemExit(f"town_gpu_terrain.detail_layer: source {source!r} is not 'gpu' or 'cpu'")
    _LAYERS[key] = t
    return t


def sample_wrap(tex, u, v):
    h, w = tex.shape[0] - 4, tex.shape[1] - 4
    x = (torch.remainder(u, 1.0) * w + 2).to(torch.float32)
    y = (torch.remainder(v, 1.0) * h + 2).to(torch.float32)
    return remap(tex, x, y)


def tiled(tex, scale, a, b, rot=0.0, off=(0.0, 0.0)):
    c, s = math.cos(rot), math.sin(rot)
    u = sdiv(a * c - b * s, scale) + off[0]
    v = sdiv(a * s + b * c, scale) + off[1]
    return sample_wrap(tex, u, v)


def _acc32(acc, add64):
    """numpy `float32_array += float64_array`: the sum in float64, rounded once to float32."""
    return (acc.double() + add64).to(torch.float32)


# ------------------------------------------------------------------------------------------------ ground synthesis
def synth_detail_parts(P, nrm, rel, layers: str):
    """stronghold_full3d_ground.synth_detail_parts (float32 P, nrm, rel)."""
    import stronghold_full3d_ground as G
    X, Y, Z = P[..., 0], P[..., 1], P[..., 2]
    fl = torch.zeros(X.shape + (3,), dtype=torch.float32, device=DEV)
    wsum = torch.zeros(X.shape, dtype=torch.float32, device=DEV)
    for i, (nm, sc) in enumerate(G.FLOOR_TEX):
        m = fbm(X, Z, 300 + i, 25.0, 3)
        w = torch.clamp((m - 0.35) * 3.0, 0, 1)
        w = w * w + 0.05
        tex = detail_layer(nm, layers)
        d = 0.65 * tiled(tex, sc, X, Z, 0.3 * i, (0.13 * i, 0.71 * i)) \
            + 0.35 * tiled(tex, sc * 2.37, X, Z, 1.1 + i, (0.4, 0.2))
        fl = _acc32(fl, d * w[..., None])
        wsum = _acc32(wsum, w)
    fl = fl / wsum[..., None]
    rk = torch.zeros_like(fl)
    rs = torch.zeros_like(wsum)
    n_np = dn(nrm)
    tw = np.abs(n_np) ** 4
    tw /= tw.sum(-1, keepdims=True) + 1e-9
    slope = np.degrees(np.arccos(np.clip(n_np[..., 1], -1, 1)))
    tw = up(tw)
    for i, (nm, sc) in enumerate(G.ROCK_TEX):
        m = fbm(X, Z, 400 + i, 40.0, 3)
        w = torch.clamp((m - 0.3) * 2.5, 0, 1)
        w = w * w + 0.05
        ro = G.ROCK_ROT.get(nm, 0.0)
        tex = detail_layer(nm, layers)
        d = (tiled(tex, sc, Z, -Y, ro, (0.3 * i, 0.1)) * tw[..., 0:1]
             + tiled(tex, sc, X, Z, 0.4, (0.1 * i, 0.6)) * tw[..., 1:2]
             + tiled(tex, sc, X, -Y, ro, (0.7 * i, 0.3)) * tw[..., 2:3])
        rk = _acc32(rk, d * w[..., None])
        rs = _acc32(rs, w)
    rk = rk / rs[..., None]
    st = torch.ones_like(fl)
    for i, (nm, sc) in enumerate(G.FLOOR_STONES):
        m = fbm(X, Z, 500 + i, 12.0, 3)
        w = torch.clamp((m - 0.4) * 3.0, 0, 1)[..., None]
        st = (st.double() * (1 + w * (tiled(detail_layer(nm, layers), sc, X, Z, 0.7 + i, (0.21 * i, 0.5)) - 1))
              ).to(torch.float32)
    fl = fl * st
    wall = torch.maximum(smoothstep(G.WALL_REL_M[0], G.WALL_REL_M[1], rel), smoothstep(30.0, 50.0, up(slope)))
    fl = up(np.power(dn(torch.clamp(fl, min=1e-3)), G.DETAIL_CONTRAST))
    rk = up(np.power(dn(torch.clamp(rk, min=1e-3)), G.ROCK_CONTRAST))
    return fl, rk, wall


def palette_at(pal: dict, Y, theta_sign):
    def one(p):
        return torch.stack([interp(Y, p["bins"], p["pal"][:, c]) for c in range(3)], -1)
    return torch.where(theta_sign[..., None] < 0, one(pal["left"]), one(pal["right"]))


def floor_patches(pal: dict, X, Z):
    import stronghold_full3d_ground as G
    cen, share = pal["floorK"], pal["floorShare"]
    out = torch.zeros(X.shape + (3,), dtype=torch.float32, device=DEV)
    wsum = torch.zeros(X.shape, dtype=torch.float32, device=DEV)
    for k in range(len(cen)):
        m = fbm(X, Z, 600 + k, G.PATCH_M * (1.0 if k == 0 else 0.6), 4)
        w = up(np.exp(dn(8.0 * (m - 0.5)))) * float(share[k])
        out = _acc32(out, up(np.asarray(cen[k])) * w[..., None])
        wsum = _acc32(wsum, w)
    return out / wsum[..., None]


def light(n, rig, sun_dir):
    """conflux_full3d_env.light for float32 n; the two (.., 3) @ (3,) dots run in numpy (sgemv's order)."""
    ny = n[..., 1:2]
    u_ = torch.sqrt(torch.clamp(ny, 0, 1))
    d_ = torch.sqrt(torch.clamp(-ny, 0, 1))
    sky, eq, gr = (up(np.array(rig[k], np.float32)) for k in ("ambSky", "ambEq", "ambGround"))
    amb = torch.where(ny >= 0, eq + (sky - eq) * u_, eq + (gr - eq) * d_)
    n_np = dn(n)
    s = up(np.clip(n_np @ -np.asarray(sun_dir, np.float32), 0, None))
    out = amb + up(np.array(rig["sunColor"], np.float32)) * s[..., None]
    if rig.get("fillColor"):
        f = up(np.clip(n_np @ -np.asarray(rig["fillDir"], np.float32), 0, None))
        out = out + up(np.array(rig["fillColor"], np.float32)) * f[..., None]
    return out


def mean3(x):
    return sdiv((x[..., 0] + x[..., 1]) + x[..., 2], 3)


def baked_shade(gf: GField, X, Z, rig, sun, wall):
    import stronghold_full3d_ground as G
    nf = gf.normal(X, Z, eps=G.SHADE_EPS_M[0]).to(torch.float32)
    nb = gf.normal(X, Z, eps=G.SHADE_EPS_M[1]).to(torch.float32)
    lf = mean3(light(nf, rig, sun))
    lb = mean3(light(nb, rig, sun))
    g = G.SHADE_GAIN[1] + (G.SHADE_GAIN[0] - G.SHADE_GAIN[1]) * wall
    lr = up(np.log(dn(torch.clamp(lf, min=1e-3) / torch.clamp(lb, min=1e-3))))
    return up(np.exp(dn(torch.clamp(g * lr, -1.2, 0.6)))).to(torch.float32)


def cavity(gf: GField, X, Z, wall):
    import stronghold_full3d_ground as G
    h0 = gf.height(X, Z)
    cav = torch.zeros_like(h0)
    for r in G.CAV_R_M:
        ring = 0
        for a in np.linspace(0, 2 * math.pi, 6, endpoint=False):
            ring = ring + gf.height(X + r * math.cos(a), Z + r * math.sin(a))
        cav = cav + sdiv(sdiv(ring, 6) - h0, len(G.CAV_R_M))
    f = torch.clamp(1 - G.CAV_K * cav, *G.CAV_CLIP)
    return (1 + (f - 1) * wall).to(torch.float32)


def soft_normal(gf: GField, cam, X, Z, Y):
    import stronghold_full3d_periphery as PP
    n = gf.normal(X, Z, eps=1.5)
    P = torch.stack([X, Y, Z], -1)
    v = up(np.asarray(cam["pos"], np.float64)) - P
    v = v / (norm3(v)[..., None] + 1e-9)
    lean = up(np.array([0.0, 1.0, 0.0])) + v
    lean = lean / (norm3(lean)[..., None] + 1e-9)
    n = n * (1 - PP.NORMAL_LEAN) + lean * PP.NORMAL_LEAN
    return n / (norm3(n)[..., None] + 1e-9)


def floor_rel(floor, P):
    p = floor.cam["pos"]
    dx, dz = P[..., 0] - p[0], P[..., 2] - p[2]
    y = p[1] + sdiv(floor.d - floor.n[0] * dx - floor.n[2] * dz, float(floor.n[1]))
    return P[..., 1] - y


def project(cam, p):
    d = p - up(np.asarray(cam["pos"], np.float64))
    zc = gemv3(d, cam["fwd"])
    t = math.tan(math.radians(cam["fov"]) / 2)
    px = (gemv3(d, cam["right"]) / sdiv(zc * t * W, H) + 1) * 0.5 * W
    py = (1 - gemv3(d, cam["up"]) / (zc * t)) * 0.5 * H
    return px, py, zc


class _BakerDev:
    def __init__(self, baker):
        self.edge_col, self.d_rect_m, self.P = up(baker.edge_col), up(baker.d_rect_m), up(baker.P)
        self.ext = None if baker.ext is None else up(baker.ext["lin"])


def bake_piece(baker, field, floor, cam, pc: dict, layers: str = "gpu") -> np.ndarray:
    """stronghold_full3d_periphery.bake_piece on the device (float32 (h, w, 3) linear albedo)."""
    import stronghold_full3d_ground as G
    import stronghold_full3d_periphery as PP
    require_cuda()
    if baker.gs is not None:
        raise SystemExit("town_gpu_terrain.bake_piece: TOWN_FULL3D_GROUNDSRC (baker.gs) is not ported to cuda; run the "
                         "periphery with TOWN_FULL3D_DEVICE=cpu")
    gf = baker.__dict__.get("_gpu_field")
    if gf is None or gf.f is not field:
        gf = baker._gpu_field = GField(field)
    bd = baker.__dict__.get("_gpu")
    if bd is None:
        bd = baker._gpu = _BakerDev(baker)
    w, h = pc["size"]
    th = pc["th"][0] + (np.arange(w) + 0.5) / w * (pc["th"][1] - pc["th"][0])
    g = (h - 1 - np.arange(h) + 0.5) / h * pc["g"][-1]
    f_, r_ = T.heading(cam)
    tr = np.radians(th)
    colx = np.cos(tr) * f_[0] + np.sin(tr) * r_[0]
    colz = np.cos(tr) * f_[2] + np.sin(tr) * r_[2]
    colx_t, colz_t, th_t = up(colx), up(colz), up(th)
    pos = cam["pos"]
    out = np.zeros((h, w, 3), np.float32)
    for r0 in range(0, h, 256):
        r1 = min(h, r0 + 256)
        rho = up(np.interp(g[r0:r1], pc["g"], pc["rr"]))[:, None]
        X = pos[0] + rho * colx_t[None, :]
        Z = pos[2] + rho * colz_t[None, :]
        Th = th_t[None, :].expand(r1 - r0, w)
        Y = gf.height(X, Z)
        P = torch.stack([X, Y, Z], -1).to(torch.float32)
        n = soft_normal(gf, cam, X, Z, Y).to(torch.float32)
        rel = floor_rel(floor, P.double()).to(torch.float32)
        fl, rk, wall = synth_detail_parts(P, n, rel, layers)
        det = fl * (1 - wall[..., None]) + rk * wall[..., None]
        base_wall = palette_at(baker.pal, Y, Th)
        base_floor = floor_patches(baker.pal, X, Z)
        base = base_floor * (1 - wall[..., None]) + base_wall * wall[..., None]
        P3 = P.reshape(-1, 3).double()
        px, py, zc = project(cam, P3)
        ok = zc > 0.5
        side = gemv3(P3 - up(np.asarray(pos, np.float64)), cam["right"])
        qx = torch.clamp(torch.where(ok, px, torch.where(side < 0, 0.0, float(W - 1)).double()), 0, W - 1)
        qy = torch.clamp(torch.where(ok, py, torch.full_like(py, H - 1)), 0, H - 1)
        xi, yi = qx.to(torch.int64), qy.to(torch.int64)
        edge = bd.edge_col[yi, xi].reshape(P.shape)
        d_edge = bd.d_rect_m[yi, xi].reshape(P.shape[:2])
        Pe = bd.P[yi, xi].reshape(P.shape)
        hyp = np.hypot(dn(P[..., 0] - Pe[..., 0]), dn(P[..., 2] - Pe[..., 2]))
        d_out = d_edge + up(hyp)
        tone = up(np.exp(dn(sdiv(-d_out, G.EDGE_TONE_M))))[..., None] * (1 - 0.6 * wall[..., None])
        cav = (cavity(gf, X, Z, wall) * baked_shade(gf, X, Z, baker.rig, baker.sun, wall))[..., None]
        res = torch.clamp((edge * tone + base * (1 - tone)) * det * cav, 0, 1).to(torch.float32)
        if baker.ext is not None:
            ex = baker.ext
            k = ex.get("k", 1)
            wc = ex["lin"].shape[1] // k
            cx = (torch.where(ok, px, torch.full_like(px, -1e6)) - ex["x0"]).reshape(P.shape[:2]).to(torch.float32)
            cy = torch.where(ok, py, torch.full_like(py, -1e6)).reshape(P.shape[:2]).to(torch.float32)
            d = torch.minimum(torch.minimum(torch.minimum(cx, wc - 1 - cx), cy), H - 1 - cy)
            pxr = torch.where(ok, px, torch.full_like(px, W / 2)).reshape(P.shape[:2])
            left = ((pxr < 0) | (pxr >= W)) & (d >= 0)
            if bool(left.any()):
                sx, sy = (cx, cy) if k == 1 else ((cx + 0.5) * k - 0.5, (cy + 0.5) * k - 0.5)
                samp = remap(bd.ext, sx.to(torch.float32), sy.to(torch.float32))
                alb = torch.clamp(samp / torch.clamp(light(n, baker.rig, baker.sun), min=0.02), 0, 1)
                wgt = (torch.clamp(sdiv(d, PP.EXT_FEATHER_PX), 0, 1) * left)[..., None]
                res = res * (1 - wgt) + alb * wgt
        out[r0:r1] = dn(res)
    return out


# ------------------------------------------------------------------------------------------------ raymarch
def raymarch(cam, field, px, py, t0=5.0, t1=None) -> np.ndarray:
    """stronghold_full3d_terrain.raymarch on the device (same float64 hits, NaN where the ray escapes)."""
    require_cuda()
    t1 = t1 or T.FAR_CAP_M
    d = T.rays(cam, px, py)
    dn_np = d / np.linalg.norm(d, axis=-1, keepdims=True)
    fz_np = dn_np @ cam["fwd"]
    gf = GField(field)
    D, fz = up(dn_np), up(fz_np)
    O = up(np.asarray(cam["pos"], np.float64))
    n = len(dn_np)
    t = torch.full((n,), float(t0), dtype=torch.float64, device=DEV)
    prev_t = t.clone()
    lo, hi = t.clone(), t.clone()
    crossed_any = torch.zeros(n, dtype=torch.bool, device=DEV)
    idx = torch.arange(n, device=DEV)
    # the march, per ray exactly the reference's steps; a crossed ray keeps its bracket (prev_t, t) and the
    # bisection runs once at the end (it depends on that ray alone). The live set is compacted every CHECK steps
    # (one host sync each), between them finished rays are masked
    CHECK = 32
    while idx.numel():
        Dl, tl, pl = D[idx], t[idx], prev_t[idx]
        alive = torch.ones(idx.numel(), dtype=torch.bool, device=DEV)
        cr = torch.zeros_like(alive)
        blo, bhi = pl.clone(), tl.clone()
        for _ in range(CHECK):
            P = O + Dl * tl[:, None]
            c = alive & ((P[:, 1] - gf.height(P[:, 0], P[:, 2])) <= 0)
            blo, bhi = torch.where(c, pl, blo), torch.where(c, tl, bhi)
            cr = cr | c
            adv = alive & ~c
            pl = torch.where(adv, tl, pl)
            tl = torch.where(adv, tl + torch.clamp(0.004 * tl, min=0.3), tl)
            alive = adv & ~(tl > t1)
        lo[idx], hi[idx], crossed_any[idx] = blo, bhi, cr
        t[idx], prev_t[idx] = tl, pl
        idx = idx[alive]
    hit = torch.full((n,), float("nan"), dtype=torch.float64, device=DEV)
    ci = torch.nonzero(crossed_any).ravel()
    if ci.numel():
        a_, b_, Dc = lo[ci], hi[ci], D[ci]
        for _ in range(12):
            mid = 0.5 * (a_ + b_)
            Pm = O + Dc * mid[:, None]
            above = Pm[:, 1] - gf.height(Pm[:, 0], Pm[:, 2]) > 0
            a_, b_ = torch.where(above, mid, a_), torch.where(above, b_, mid)
        hit[ci] = b_ * fz[ci]
    out = dn(hit)
    if SC.FP.SKY_MASK.get("rule") == "none":
        out = np.where(np.isnan(out), t1 * fz_np, out)
    return out
