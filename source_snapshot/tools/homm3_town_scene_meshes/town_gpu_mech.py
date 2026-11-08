"""CUDA scoring of town_full3d_mech's wheel hub x step grid search (fit_wheel).

wheel_grid_scores(D, ev, ever, cells, steps, ks) returns, per hub cell, the best _wheel_score over the steps, computed on
the GPU for every (cell, step, k) at once. Exact parts (bit-for-bit what the CPU path computes):
  - the screen map: ell_affine at q = 1, psi = 0 is the rotation R itself (A = I), and its translation is
    c - M @ c, which numpy evaluates as fma(M[i, 0], c0, M[i, 1] * c1) (torch.addcmul on CUDA fuses); cos / sin of
    each distinct angle come from Python's math, as in ell_affine. A spot check against ell_affine fails closed;
  - cv2.warpAffine (OpenCV 4.13, INTER_LINEAR, BORDER_CONSTANT 0) on float32: the map inverted in double as cv2 does,
    the fixed-point source position (AB_BITS 10, INTER_BITS 5, round delta 16), the float32 table weights and the
    four taps summed in order. The warped mask (> 0.5) and its px count are therefore exact.
Approximate part: the NCC sums (numpy reduces float32 pairwise; here float64). The caller re-scores on the CPU every
cell within 2 x WHEEL_GPU_EPS of the third-best GPU cell and picks by the CPU score, so the chosen fit is the CPU
path's; it also fails closed if any re-scored cell's GPU score is more than WHEEL_GPU_EPS from its CPU score.
No CPU fallback: a missing CUDA device raises (town_gpu_kernels.require_cuda).
"""
from __future__ import annotations

import math

import numpy as np

import town_gpu_kernels as GK

CELLS_PER_CHUNK = 12


def _matrices(torch, dev, cells, steps, ks):
    """(C, S, K, 6) float32 forward maps, bit-identical to ell_affine(cx, cy, 1.0, 0.0, s * k)."""
    ang = np.asarray(steps, np.float64)[:, None] * np.asarray(ks, np.int64)[None, :]          # (S, K) as s * k
    ua, inv = np.unique(ang, return_inverse=True)
    cs = np.array([math.cos(math.radians(a)) for a in ua.tolist()])
    sn = np.array([math.sin(math.radians(a)) for a in ua.tolist()])
    c = torch.as_tensor(cs[inv.reshape(ang.shape)], device=dev)[None]
    s = torch.as_tensor(sn[inv.reshape(ang.shape)], device=dev)[None]
    cxy = torch.as_tensor(np.asarray(cells, np.float64), device=dev)
    cx, cy = cxy[:, 0, None, None], cxy[:, 1, None, None]
    m00, m01, m10, m11 = c, s, -s, c
    tx = cx - torch.addcmul(m01 * cy, m00, cx)          # fma(M00, cx, M01 * cy)
    ty = cy - torch.addcmul(m11 * cy, m10, cx)
    sh = tx.shape
    M = torch.stack([m00.expand(sh), m01.expand(sh), tx, m10.expand(sh), m11.expand(sh), ty], -1)
    return M.to(torch.float32)


def _warp(torch, img, Mf, H, W):
    """cv2.warpAffine(img, M, (W, H), INTER_LINEAR) for a batch of maps Mf (..., 6) float32 -> (..., H, W) float32."""
    M = Mf.double()
    m0, m1, m2, m3, m4, m5 = M.unbind(-1)
    D = m0 * m4 - m1 * m3
    D = torch.where(D != 0, torch.ones_like(D) / D, torch.zeros_like(D))
    a11, a22 = m4 * D, m0 * D
    m1, m3 = m1 * -D, m3 * -D
    m0, m4 = a11, a22
    b1 = -m0 * m2 - m1 * m5
    b2 = -m3 * m2 - m4 * m5
    dev = img.device
    x = torch.arange(W, dtype=torch.float64, device=dev)
    y = torch.arange(H, dtype=torch.float64, device=dev)
    e = lambda t: t[..., None, None]
    k1024 = torch.tensor(1024.0, dtype=torch.float64, device=dev)
    ad = torch.round(e(m0) * x * k1024).long()                                   # (..., 1, W)
    bd = torch.round(e(m3) * x * k1024).long()
    X0 = torch.round((e(m1) * y[:, None] + e(b1)) * k1024).long() + 16          # (..., H, 1)
    Y0 = torch.round((e(m4) * y[:, None] + e(b2)) * k1024).long() + 16
    X = (X0 + ad) >> 5
    Y = (Y0 + bd) >> 5
    ix, iy = X >> 5, Y >> 5
    one = torch.tensor(1.0, dtype=torch.float32, device=dev)
    k32 = torch.tensor(1.0 / 32, dtype=torch.float32, device=dev)
    ax = (X & 31).float() * k32
    ay = (Y & 31).float() * k32
    flat = img.reshape(-1)

    def tap(xx, yy):
        ok = (xx >= 0) & (yy >= 0) & (xx < W) & (yy < H)
        v = flat[(yy.clamp(0, H - 1) * W + xx.clamp(0, W - 1))]
        return torch.where(ok, v, torch.zeros_like(v))
    w00, w01 = (one - ay) * (one - ax), (one - ay) * ax
    w10, w11 = ay * (one - ax), ay * ax
    return ((tap(ix, iy) * w00 + tap(ix + 1, iy) * w01) + tap(ix, iy + 1) * w10) + tap(ix + 1, iy + 1) * w11


def wheel_grid_scores(D, ev, ever, cells, steps, ks) -> np.ndarray:
    """(C,) float64: per hub cell, max over steps of the (GPU) _wheel_score(D, ev, ever, cx, cy, 1, 0, s, ks)."""
    import town_full3d_mech as MECH
    torch = GK.require_cuda()
    dev = torch.device("cuda", torch.cuda.current_device())
    H, W = ever.shape
    Dt = torch.as_tensor(np.ascontiguousarray(D, np.float32), device=dev)
    evt = torch.as_tensor(np.ascontiguousarray(ev, np.float32), device=dev)
    evr = torch.as_tensor(np.ascontiguousarray(ever), device=dev)
    kst = torch.as_tensor(np.asarray(ks, np.int64), device=dev)
    Dk = Dt[kst].double()                                                         # (K, H, W)
    M = _matrices(torch, dev, cells, steps, ks)                                  # (C, S, K, 6)
    rng = np.random.default_rng(0)                                               # spot check against ell_affine
    for _ in range(64):
        i, j, kk = rng.integers(len(cells)), rng.integers(len(steps)), rng.integers(len(ks))
        ref = MECH.ell_affine(cells[i][0], cells[i][1], 1.0, 0.0, steps[j] * ks[kk]).ravel()
        if ref.tobytes() != M[i, j, kk].cpu().numpy().tobytes():
            raise SystemExit("town_gpu_mech: the GPU screen map differs from ell_affine; run with --device cpu")
    out = np.empty(len(cells))
    for c0 in range(0, len(cells), CELLS_PER_CHUNK):
        Mc = M[c0:c0 + CELLS_PER_CHUNK]
        r = _warp(torch, Dt[0], Mc, H, W).double()                                # (c, S, K, H, W)
        m = (_warp(torch, evt, Mc, H, W) > 0.5) & evr
        mf = m.double()
        n = mf.sum((-2, -1))
        nn = n.clamp(min=1)
        sr, sd = (r * mf).sum((-2, -1)), (Dk * mf).sum((-2, -1))
        mr, md = sr / nn, sd / nn
        a = (r - mr[..., None, None]) * mf
        b = (Dk - md[..., None, None]) * mf
        ncc = (a * b).sum((-2, -1)) / (torch.sqrt((a * a).sum((-2, -1))) * torch.sqrt((b * b).sum((-2, -1))) + 1e-9)
        sc = torch.where((n < 20).any(-1), torch.full_like(ncc[..., 0], -1.0), ncc.mean(-1))   # (c, S)
        out[c0:c0 + CELLS_PER_CHUNK] = sc.max(-1).values.cpu().numpy()
    return out
