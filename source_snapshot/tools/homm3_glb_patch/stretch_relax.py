"""Per-pose strain-limiting corrective for the glb patch lane's `stretchRelax` op (docs/homm3_glb_patch_lane.md,
"Deep hip and knee flexion").

Why: a deep hip/knee flexion (a seated or kneeling collapse into a heap, as the HoMM3 DEF Death clips do) bends linear
blend skinning around a hard weight band. The skin over the buttock, the back of the knee, the waist side and the
crotch then stretches past the tear gate's 2x on a few rows of edges, while the edges a little further along the thigh
and the back stay near rest. No weight op spreads that (h3_giant_upg heap D3: hip / waist / shoulder diffusion,
moveWeights of arm and thigh bleed and a wider spine fold all refused, 980 -> 1512).

What: for each CS_ target of the named clips, after the lane's differential Corrective Smooth re-bake and before the
tear gate measures it, the skinned pose is relaxed in posed space and the change is written back into that target:
  - every weld group's posed position starts at the skinned pose (stored target included);
  - each iteration, every edge longer than `ratio` x its rest length pulls its two ends toward that length (half each,
    averaged over a group's over-long edges), the pull is projected onto the posed surface's tangent plane (the skin
    slides; the silhouette and volume stay), and the displacement field is Laplacian-smoothed by `smooth` so the
    slack is drawn from the neighbouring near-rest edges (the material a real fold would pull in);
  - only `bones`-weighted groups move (default all), and at each pose only groups whose blended skin matrix is well
    conditioned (smallest singular value >= SIGMA_MIN: the candy-wrapper core of a deep fold stays put); the posed
    change is mapped back to rest space through each vertex's blended skin matrix (CPU LAPACK) and added to the
    target, so a rest offset is at most 1 / SIGMA_MIN x the posed slide.
It is a strain limiter, not a reshape: the op refuses any group moving more than `maxMove` x the body height, and the
lane's tear gate, morph-extent gate and every delivery gate after it measure the result unchanged.

Device: the iteration loop runs on CUDA by default (cs_numpy.resolve_device, HOMM3_CS_DEVICE), bit-identical to the
numpy reference here: elementwise float64 IEEE ops in the reference's order and np.bincount scatters replayed as ordered
per-bin tables (cs_torch._table / _scatter). Skinning and the rest-space solve run on the CPU for both devices (einsum
and LAPACK orders). test_stretch_relax.py proves the bytes equal; no CPU fallback when CUDA is asked for.
"""
from __future__ import annotations

import numpy as np

import cs_numpy as CS

TIKHONOV = 1e-9     # rest-space solve regulariser (x the blended skin matrix's own scale); pinned below SIGMA_MIN
SIGMA_MIN = 0.5     # a group whose blended skin matrix has a singular value under this stays pinned at that pose: the
                    # rest-space solve would amplify its slide by 1/sigma (h3_giant_upg heap f4: 0.06 posed -> 1.33 rest,
                    # morph extent 0.08 -> 0.79 H); pinned, |rest change| <= |posed slide| / SIGMA_MIN


def _sqrt_norm(v):
    """|v| of 3-vectors, squares summed in order (cs_torch._norm's order)."""
    return np.sqrt((v[..., 0] * v[..., 0] + v[..., 1] * v[..., 1]) + v[..., 2] * v[..., 2])


def _dot(a, b):
    return (a[..., 0] * b[..., 0] + a[..., 1] * b[..., 1]) + a[..., 2] * b[..., 2]


def _cross(a, b):
    return np.stack([a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1],
                     a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2],
                     a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]], -1)


def _scat(idx, vals, n):
    """vals (m, B, 3) summed into n bins by idx (np.bincount order)."""
    m = vals.shape[0]
    return CS._scatter(idx, vals.reshape(m, -1), n).reshape((n,) + vals.shape[1:])


class Mesh:
    """Weld-group edges, rest lengths and triangles of the body (seam copies are one group, as in the gate's Weld)."""

    def __init__(self, weld: CS.Weld, V: np.ndarray):
        E = weld.edges
        R = np.asarray(V, np.float64)[weld.rep]
        L = _sqrt_norm(R[E[:, 1]] - R[E[:, 0]])
        keep = L > 1e-6                      # the gate's edge measure skips degenerate rest edges
        self.a, self.b, self.L = E[keep, 0].copy(), E[keep, 1].copy(), L[keep]
        tri = [f for f in weld.faces if len(f) == 3]
        self.F = np.asarray(tri, np.int64).reshape(-1, 3)
        self.ng = weld.ng
        self.deg = np.bincount(np.concatenate([self.a, self.b]), minlength=self.ng).astype(np.float64)
        self.fidx = np.concatenate([self.F[:, 0], self.F[:, 1], self.F[:, 2]])


def _loop_numpy(mesh: Mesh, Y0, mv, ratio, iterations, smooth):
    a, b, ng = mesh.a, mesh.b, mesh.ng
    tL = ratio * mesh.L[:, None]
    degd = np.maximum(mesh.deg, 1.0)[:, None, None]
    mvb = mv[..., None]
    Y = Y0.copy()
    for _ in range(iterations):
        d = Y[b] - Y[a]
        ln = _sqrt_norm(d)
        over = ln > tL
        k = np.where(over, (1.0 - tL / np.maximum(ln, 1e-12)) * 0.5, 0.0)
        f = k[..., None] * d
        disp = _scat(a, f, ng) - _scat(b, f, ng)
        ov = over.astype(np.float64)[..., None]
        cnt = _scat(a, ov, ng) + _scat(b, ov, ng)
        disp = disp / np.maximum(cnt, 1.0)
        fn = _cross(Y[mesh.F[:, 1]] - Y[mesh.F[:, 0]], Y[mesh.F[:, 2]] - Y[mesh.F[:, 0]])
        n = _scat(mesh.fidx, np.concatenate([fn, fn, fn]), ng)
        n = n / np.maximum(_sqrt_norm(n), 1e-12)[..., None]
        disp = disp - _dot(disp, n)[..., None] * n
        Y = Y + disp * mvb
        Dl = Y - Y0
        nb = (_scat(a, Dl[b], ng) + _scat(b, Dl[a], ng)) / degd
        Y = Y0 + (Dl + (smooth * (nb - Dl)) * mvb)
    return Y


def _loop_cuda(mesh: Mesh, Y0, mv, ratio, iterations, smooth):
    import cs_torch as T
    torch = T.torch
    T.require_cuda()
    a, b, ng = mesh.a, mesh.b, mesh.ng
    m = len(a)
    tab_a, tab_b = T._table(a, ng, m), T._table(b, ng, m)
    tab_f = T._table(mesh.fidx, ng, len(mesh.fidx))
    at, bt = T._t(a), T._t(b)
    F0, F1, F2 = (T._t(mesh.F[:, k]) for k in range(3))
    tL = T._t(ratio * mesh.L[:, None])
    degd = T._t(np.maximum(mesh.deg, 1.0)[:, None, None])
    mvb = T._t(np.asarray(mv, np.float64)[..., None])
    Y0t = T._t(np.asarray(Y0, np.float64))
    Y = Y0t.clone()
    one, eps, half = (torch.tensor(x, dtype=torch.float64, device=Y.device) for x in (1.0, 1e-12, 0.5))
    zero = torch.zeros((), dtype=torch.float64, device=Y.device)
    sm = torch.tensor(float(smooth), dtype=torch.float64, device=Y.device)

    def nrm(v):
        return torch.sqrt((v[..., 0] * v[..., 0] + v[..., 1] * v[..., 1]) + v[..., 2] * v[..., 2])

    def dot(u, v):
        return (u[..., 0] * v[..., 0] + u[..., 1] * v[..., 1]) + u[..., 2] * v[..., 2]

    for _ in range(iterations):
        d = Y[bt] - Y[at]
        ln = nrm(d)
        over = ln > tL
        k = torch.where(over, (one - tL / torch.maximum(ln, eps)) * half, zero)
        f = k[..., None] * d
        disp = T._scatter(tab_a, f) - T._scatter(tab_b, f)
        ov = over.to(torch.float64)[..., None]
        cnt = T._scatter(tab_a, ov) + T._scatter(tab_b, ov)
        disp = disp / torch.maximum(cnt, one)
        fn = T._cross(Y[F1] - Y[F0], Y[F2] - Y[F0])
        n = T._scatter(tab_f, torch.cat([fn, fn, fn], 0))
        n = n / torch.maximum(nrm(n), eps)[..., None]
        disp = disp - dot(disp, n)[..., None] * n
        Y = Y + disp * mvb
        Dl = Y - Y0t
        nb = (T._scatter(tab_a, Dl[bt]) + T._scatter(tab_b, Dl[at])) / degd
        Y = Y0t + (Dl + (sm * (nb - Dl)) * mvb)
    return Y.cpu().numpy()


def relax_batch(weld: CS.Weld, V, J, Wn, Sks, Ds, movable, ratio: float, iterations: int, smooth: float,
                device: str | None = None) -> tuple[list, np.ndarray]:
    """Ds (rest-space target offsets, one (n, 3) per pose) relaxed under skin matrices Sks; movable: per vertex bool.
    Returns (new offsets per pose, per pose the largest group move in posed space, per pose the movable groups pinned
    for an ill-conditioned skin matrix)."""
    mesh = weld.__dict__.get("_relax_mesh")
    if mesh is None:
        mesh = weld._relax_mesh = Mesh(weld, V)
    rep = weld.rep
    Ss, Mbs = [], []
    for Sk, D in zip(Sks, Ds):
        S, Mb, _ = CS._skin(np.asarray(V, np.float64) + D, J, Wn, Sk)
        Ss.append(S)
        Mbs.append(Mb)
    Y0 = np.stack([S[rep] for S in Ss], 1)                       # (ng, B, 3)
    mvg = np.zeros(weld.ng, bool)
    np.logical_or.at(mvg, weld.gid, np.asarray(movable, bool))   # a group moves if any copy is movable (all are alike)
    sig = np.stack([np.linalg.svd(Mb[rep], compute_uv=False)[:, -1] for Mb in Mbs], 1)   # (ng, B)
    mv = (mvg[:, None] & (sig >= SIGMA_MIN)).astype(np.float64)
    loop = _loop_cuda if CS.resolve_device(device) == "cuda" else _loop_numpy
    Y = loop(mesh, Y0, mv, float(ratio), int(iterations), float(smooth))
    dY = Y - Y0
    moved = _sqrt_norm(dY).max(0)
    pinned = ((sig < SIGMA_MIN) & mvg[:, None]).sum(0)
    out = []
    for k, (D, Mb) in enumerate(zip(Ds, Mbs)):
        dy = dY[weld.gid, k]                                       # seam copies take their group's change
        lam = TIKHONOV * np.einsum("nij,nij->n", Mb, Mb)[:, None, None]
        A = np.einsum("nji,njk->nik", Mb, Mb) + lam * np.eye(3)[None]
        rhs = np.einsum("nji,nj->ni", Mb, dy)
        out.append(D + np.linalg.solve(A, rhs[..., None])[..., 0])
    return out, moved, pinned
