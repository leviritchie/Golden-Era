"""CUDA path of cs_numpy's batched Corrective Smooth offsets and patch_glb's edge stretch, bit-identical to the numpy
reference (tools/homm3_glb_patch/cs_numpy.py stays the rule; this file only re-runs its arithmetic on the GPU).

Bit identity: every float64 op here is an elementwise IEEE op (add, sub, mul, div, sqrt: correctly rounded on CUDA,
eager torch never fuses them into an FMA) done in the reference's own order:
  - np.bincount (cs_numpy._scatter) sums a bin's values sequentially in index order, from +0.0: here a per-bin table of
    its entries in that order (padded with an index of a zero row), summed column by column from a +0.0 tensor;
  - np.einsum over a contiguous inner axis of 3 sums (p0 + p2) + p1, of 4 (p0 + p2) + (p1 + p3) (measured, numpy 2.x
    X86_V3, alignment-independent); over a strided inner axis (the transposed corner frames) it sums in order;
  - np.linalg.norm(axis=1) sums the squares in order, then sqrt;
  - np.cross is the multiply-then-subtract per component.
What does not run here, because CUDA cannot reproduce its bits: np.arccos of the corner cosines (CPU, on the GPU's
bit-identical inputs), the per-joint det / cbrt of the skin scale (CPU, a few dozen 3x3s), the harmonic fill
(Weld._fill, CPU, only at poses with undefined groups) and the rest-space solve (cs_numpy.solve: LAPACK, CPU).
test_cs_device_parity.py proves the result byte for byte on h3_griffin and h3_mummy.
No CPU fallback: a missing torch or CUDA device raises SystemExit (cs_numpy.resolve_device names the switch).
"""
from __future__ import annotations

import os

import numpy as np

try:
    import torch
except ImportError:  # the error is raised by require_cuda, where the device is asked for
    torch = None

VRAM_CAP_GB = float(os.environ.get("HOMM3_CS_GPU_VRAM_CAP_GB", "4"))
_DEV = None


def require_cuda():
    global _DEV
    if _DEV is not None:
        return _DEV
    if torch is None:
        raise SystemExit("cs_numpy device cuda: torch is not importable; pass device='cpu' (or HOMM3_CS_DEVICE=cpu) "
                         "to run the numpy reference")
    if not torch.cuda.is_available():
        raise SystemExit("cs_numpy device cuda: no CUDA device; pass device='cpu' (or HOMM3_CS_DEVICE=cpu) to run the "
                         "numpy reference")
    _DEV = torch.device("cuda", torch.cuda.current_device())
    total = torch.cuda.get_device_properties(_DEV).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1.0, VRAM_CAP_GB * 2 ** 30 / total), _DEV)
    return _DEV


def _t(a, dtype=None):
    a = np.ascontiguousarray(a)
    t = torch.from_numpy(a).to(_DEV)
    return t if dtype is None else t.to(dtype)


def _table(idx: np.ndarray, n: int, pad: int):
    """(n, deg) entry indices per bin in ascending order (np.bincount's summation order), padded with `pad`."""
    idx = np.asarray(idx, np.int64)
    order = np.argsort(idx, kind="stable")
    cnt = np.bincount(idx, minlength=n)
    deg = int(cnt.max()) if len(cnt) and cnt.size else 0
    tab = np.full((n, max(deg, 1)), pad, np.int64)
    start = np.zeros(n + 1, np.int64)
    np.cumsum(cnt, out=start[1:])
    pos = np.arange(len(idx)) - start[idx[order]]
    tab[idx[order], pos] = order
    return _t(tab)


def _scatter(tab, vals):
    """cs_numpy._scatter / np.bincount: vals (m, ...) summed into tab's bins, sequentially from +0.0."""
    z = torch.zeros((1,) + tuple(vals.shape[1:]), dtype=vals.dtype, device=vals.device)
    v = torch.cat([vals, z], 0)
    acc = torch.zeros((tab.shape[0],) + tuple(vals.shape[1:]), dtype=vals.dtype, device=vals.device)
    for k in range(tab.shape[1]):
        acc = acc + v[tab[:, k]]
    return acc


def _sq3(d):
    """np.einsum('...k,...k->...', d, d) over a contiguous k of 3: (p0 + p2) + p1."""
    return (d[..., 0] * d[..., 0] + d[..., 2] * d[..., 2]) + d[..., 1] * d[..., 1]


def _dot3(a, b):
    return (a[..., 0] * b[..., 0] + a[..., 2] * b[..., 2]) + a[..., 1] * b[..., 1]


def _norm(v):
    """np.linalg.norm(v, axis=-1) of 3-vectors: squares summed in order, then sqrt."""
    return torch.sqrt((v[..., 0] * v[..., 0] + v[..., 1] * v[..., 1]) + v[..., 2] * v[..., 2])


def _cross(a, b):
    return torch.stack([a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1],
                        a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2],
                        a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]], -1)


def _mv4(m, x):
    """np.einsum('nij,nj->ni', m, x) for contiguous 4x4 m: (p0 + p2) + (p1 + p3) per row."""
    p = [m[..., :, j] * x[..., j:j + 1] for j in range(4)]
    return (p[0] + p[2]) + (p[1] + p[3])


class _Dev:
    """A Weld's index tables and rest state, uploaded once."""

    def __init__(self, weld):
        E = len(weld.edges)
        a, b = weld.edges[:, 0], weld.edges[:, 1]
        self.a, self.b = _t(a), _t(b)
        self.tab_a, self.tab_b = _table(a, weld.ng, E), _table(b, weld.ng, E)
        self.edge_count = _t(weld.edge_count)
        C = len(weld.c_curr)
        self.cp, self.cc, self.cn = _t(weld.c_prev), _t(weld.c_curr), _t(weld.c_next)
        self.tab_c = _table(weld.c_curr, weld.ng, C)
        self.rest_valid = _t(weld.rest_valid)
        self.rest_min_edge = _t(weld.rest_min_edge)
        self.rep = _t(weld.rep)


def _dev(weld) -> _Dev:
    d = weld.__dict__.get("_cuda")
    if d is None:
        d = weld._cuda = _Dev(weld)
    return d


def smooth(weld, D: _Dev, X, iterations, factor):
    """cs_numpy.Weld.smooth on (ng, B, 3)."""
    ng, B = X.shape[0], X.shape[1]
    lam = factor * 2.0
    eps = float(np.finfo(np.float32).eps) * 10.0
    ec = D.edge_count[:, None]
    for _ in range(iterations):
        d = X[D.b] - X[D.a]
        ln = torch.sqrt(_sq3(d))
        wd = (d * ln[..., None]).reshape(len(D.a), B * 3)
        delta = _scatter(D.tab_a, wd) - _scatter(D.tab_b, wd)
        div = (_scatter(D.tab_a, ln) + _scatter(D.tab_b, ln)) * ec
        ok = div > eps
        # a Python scalar over a tensor is reciprocal() * scalar in torch (two roundings): divide a full tensor
        coef = torch.where(ok, torch.full_like(div, lam) / torch.where(ok, div, torch.ones_like(div)), torch.zeros_like(div))
        X = X + delta.reshape(ng, B, 3) * coef[..., None]
    return X


def _nrm(v):
    ln = _norm(v)[..., None]
    pos = ln > 0
    return torch.where(pos, v / torch.where(pos, ln, torch.ones_like(ln)), torch.zeros_like(v))


def tangents(weld, D: _Dev, X):
    """cs_numpy.Weld.tangents on (ng, B, 3): frames (C, B, 3, 3), weight (C, B), valid (C, B)."""
    eps = float(np.finfo(np.float32).eps) * 10.0
    ep = X[D.cp] - X[D.cc]
    en = X[D.cc] - X[D.cn]
    lp, lq = _norm(ep), _norm(en)
    dp, dn = _nrm(ep), _nrm(en)
    same = torch.all(torch.abs(dp - dn) <= eps, -1)
    cr = _cross(dp, dn)
    s = _norm(cr)
    t2 = _nrm(cr)
    t0 = _nrm(dp + dn)
    t1 = _cross(t2, t0)
    T = torch.stack([t0, t1, t2], -2)
    # np.arccos is not reproducible on CUDA: the clipped cosine (bit-identical) goes to the CPU and back
    cosv = torch.clamp(_dot3(dn, dp), -1.0, 1.0).cpu().numpy()
    wt = _t(np.abs(np.arccos(cosv)))
    valid = ~same & (torch.minimum(lp, lq) * s >= weld_degen(weld))
    eye = torch.eye(3, dtype=T.dtype, device=T.device)
    T = torch.where(valid[..., None, None], T, eye)
    wt = torch.where(valid, wt, torch.zeros_like(wt))
    return T, wt, valid


def weld_degen(weld) -> float:
    import cs_numpy as CS
    return CS.DEGEN_CORNER_HEIGHT * weld.scale


def min_edge(D: _Dev, X, ng):
    ln = _norm(X[D.b] - X[D.a])
    m = torch.full((ng,) + tuple(ln.shape[1:]), float("inf"), dtype=ln.dtype, device=ln.device)
    idx_a = D.a.view(-1, *([1] * (ln.dim() - 1))).expand_as(ln)
    idx_b = D.b.view(-1, *([1] * (ln.dim() - 1))).expand_as(ln)
    m = m.scatter_reduce(0, idx_a, ln, "amin")
    return m.scatter_reduce(0, idx_b, ln, "amin")


def corrective(weld, D: _Dev, Sg, cache_t, X):
    """cs_numpy.Weld.corrective for B poses at once: (C (ng, B, 3) on the device, last_min_edge (ng, B))."""
    last_min = torch.minimum(min_edge(D, X, weld.ng), D.rest_min_edge[:, None])
    T, wt, valid = tangents(weld, D, X)
    valid = valid & D.rest_valid[:, None]
    wt = torch.where(valid, wt, torch.zeros_like(wt))
    wsum = _scatter(D.tab_c, wt)
    wc = wsum[D.cc]
    pos = wc > 0
    w = torch.where(pos, wt / torch.where(pos, wc, torch.ones_like(wc)), torch.zeros_like(wt))
    # np.einsum('cij,cj->ci', T^T, cache): a strided inner axis, summed in order
    c = cache_t[:, None, :]
    add = (T[..., 0, :] * c[..., 0:1] + T[..., 1, :] * c[..., 1:2]) + T[..., 2, :] * c[..., 2:3]
    add = add * w[..., None]
    out = X + _scatter(D.tab_c, add)
    skin_only = wsum <= 0
    Dd = out - Sg
    Dd = torch.where(skin_only[..., None], torch.zeros_like(Dd), Dd)
    return Dd, skin_only, last_min


def skin(Vh, Jt, Wt, Sk_t, sc_t):
    """cs_numpy._skin for B poses: S (B, n, 3), Mb (B, n, 3, 3), scale (B, n)."""
    B, n = Sk_t.shape[0], Vh.shape[0]
    S = torch.zeros((B, n, 3), dtype=torch.float64, device=_DEV)
    Mb = torch.zeros((B, n, 3, 3), dtype=torch.float64, device=_DEV)
    scale = torch.zeros((B, n), dtype=torch.float64, device=_DEV)
    for k in range(Jt.shape[1]):
        m = Sk_t[:, Jt[:, k]]
        S = S + Wt[None, :, k:k + 1] * _mv4(m, Vh[None])[..., :3]
        Mb = Mb + Wt[None, :, k, None, None] * m[..., :3, :3]
        scale = scale + Wt[None, :, k] * sc_t[:, Jt[:, k]]
    return S, Mb, scale


def offsets_batch(weld, V, J, W, Sks, cache, cond_edge: float, chunk: int = 32):
    """cs_numpy.offsets_batch on the GPU (same return value, bit for bit)."""
    import cs_numpy as CS
    require_cuda()
    D = _dev(weld)
    V = np.asarray(V, np.float64)
    Vh = _t(np.c_[V, np.ones(len(V))])
    Jt, Wt = _t(np.asarray(J, np.int64)), _t(np.asarray(W, np.float64))
    cache_t = _t(np.asarray(cache, np.float64))
    out = []
    for i in range(0, len(Sks), chunk):
        sk = np.stack([np.asarray(x, np.float64) for x in Sks[i:i + chunk]])
        sc = np.stack([np.cbrt(np.abs(np.linalg.det(x[:, :3, :3]))) for x in sk])
        S, Mb, scale = skin(Vh, Jt, Wt, _t(sk), _t(sc))
        Sg = S[:, D.rep].transpose(0, 1)                     # (ng, B, 3)
        X = smooth(weld, D, Sg.contiguous(), weld.iterations, weld.factor)
        Dd, skin_only, last_min = corrective(weld, D, Sg, cache_t, X)
        Dd, skin_only = Dd.cpu().numpy(), skin_only.cpu().numpy()
        cond = (last_min >= cond_edge).cpu().numpy()
        S_np, Mb_np, sc_np, Sg_np = S.cpu().numpy(), Mb.cpu().numpy(), scale.cpu().numpy(), Sg.cpu().numpy()
        def finish(k):
            Dk = Dd[:, k]
            free = skin_only[:, k]
            if free.any():
                Dk, _ = weld._fill(Dk, free)
            if weld.keep is not None:                     # cs_numpy.Weld.set_exclusion, same numpy multiply
                Dk = Dk * weld.keep[:, None]
            C = Sg_np[:, k] + Dk
            return CS.solve(weld.gid, weld.rep, S_np[k], Mb_np[k], sc_np[k], C), cond[:, k][weld.gid]
        # the per-pose fill and LAPACK solve stay numpy (bit for bit); numpy releases the GIL in them, so the chunk's
        # poses run on a thread pool, each one exactly the reference call
        out += list(_pool().map(finish, range(sk.shape[0])))
    return out


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max_workers=int(os.environ.get("HOMM3_CS_SOLVE_THREADS", "6")))
    return _POOL


def edge_stretch(body, J, Wn, Sk, D) -> np.ndarray:
    """patch_glb.edge_stretch on the GPU (same values, bit for bit)."""
    require_cuda()
    c = body.__dict__.get("_cuda_es")
    if c is None:
        c = body._cuda_es = {"E0": _t(body._edges[:, 0]), "E1": _t(body._edges[:, 1]), "L": _t(body._rest_len),
                             "jw": {}}
    key = (id(J), id(Wn))
    jw = c["jw"].get(key)
    if jw is None or jw[0] is not J or jw[1] is not Wn:
        jw = c["jw"][key] = (J, Wn, _t(np.asarray(J, np.int64)), _t(np.asarray(Wn, np.float64)))
    _, _, Jt, Wt = jw
    X = np.c_[body.V + D, np.ones(len(body.V))]
    Xt, Skt = _t(np.asarray(X, np.float64)), _t(np.asarray(Sk, np.float64))
    Y = torch.zeros((len(X), 3), dtype=torch.float64, device=_DEV)
    for k in range(Jt.shape[1]):
        Y = Y + Wt[:, k:k + 1] * _mv4(Skt[Jt[:, k]], Xt)[:, :3]
    return (_norm(Y[c["E0"]] - Y[c["E1"]]) / c["L"]).cpu().numpy()
