"""Corrective Smooth morph targets in float64 numpy: the one Corrective Smooth implementation of the def_retarget lane.

tools/homm3_def_retarget/bake_cs.py (inside Blender) and tools/homm3_glb_patch/patch_glb.py (on a GLB) both call this.
Blender provides only the rest mesh, the weights and the pose bone matrices; the skinning, the smoothing, the corner
frames and the solve are all here, in float64 (docs/homm3_cs_bake_float64.md).

Per key of each action, the skinned mesh S (linear blend, float64) and its Corrective Smooth C (on a welded proxy: one
vertex per (rest position, weights) group, LENGTH_WEIGHTED, rest source = the rest mesh, no pinned boundary, no vertex
group) give the rest-space offset d = (Mb^T Mb + lam^2 I)^-1 Mb^T (C - S) stored as that key's morph target, where Mb is
the vertex's weight-blended bone 3x3 and vertices whose weighted bone scale is <= 0.9 keep d = 0.

The arithmetic is a line-by-line port of Blender 5.2's MOD_correctivesmooth.cc:
  weld      vertices grouped by (position rounded 1e-5, weights rounded 1e-3), bake_cs's GID key; faces with a repeated
            group dropped; edges = the unique edges of those faces (Blender's calc_edges);
  smooth    smooth_iter__length_weight: per iteration, per edge e=(a,b), dir = x_b - x_a scaled by |dir|, a += dir,
            b -= dir, len sums; x += (2*factor / (lensum * edgecount)) * delta;
  tangents  calc_tangent_spaces per face corner (prev/next edge directions, the cross, the half-way axis) with the
            corner-angle weight, deltas cached from the smoothed rest and re-applied weight-averaged per vertex.
The cyclic start and the winding of a face do not change the result (the corner frame flips by a proper rotation that
the cached delta undoes).

Why float64 and not Blender's modifier (the measured defect, 2026-09-30): thirty length-weighted iterations collapse thin
parts of a Meshy body (fur, hems, fingers): on h3_jotunn_upg_alt 587 of 2483 weld groups end with an incident smoothed
edge below 1e-6. There Blender's float32 corner frames (the cross of two ~1e-7 vectors) are rounding noise: its
Corrective Smooth does not return the rest pose at rest (0.30 max error) and its stored targets doubled the jotunn's
torn edges against no CS at all (2138 vs 979 edges past 2x). In float64 the same frames are exact to ~1e-10 there.

The degenerate-corner rule (DEGEN_CORNER_HEIGHT, the one explicit rule; no silent fallback): a corner frame is built
from the corner's two edge directions; its error is about eps64 * |x| / (shortest edge * sin(angle)). A corner whose
height (shortest incident edge x sin of its angle, the distance of a vertex from the opposite edge's line) is below
DEGEN_CORNER_HEIGHT x the body scale -- in the smoothed rest or in the smoothed pose -- defines no frame and gets
weight 0 (Blender itself weights exactly parallel corners 0). A weld group left with no valid corner at a pose has no
frame there (counted, skinOnlyGroupSamples) and takes the harmonic interpolation of its weld neighbours' corrective
displacement C - S (uniform graph Laplacian, solved exactly per connected undefined component with the defined groups
around it as the boundary); a component that touches no defined group is skinning-only (C = S). v2 (2026-09-30, first
rollout) left every undefined group at S, which tears where it borders a strongly corrected group (h3_champion Death:
one 4.6 mm edge to 24.5x against 7.3x filled); the fill is better than or equal to v2 on all 12 measured units. CS at
the rest pose still returns the rest mesh exactly (every displacement is 0 there, so is its interpolation).

COND_EDGE is the patch lane's parity split against Blender's legacy float32 bytes (patch_glb.py), not a bake rule.
Proof tier: generated artifact (per unit, the bake record; parity against Blender on conditioned groups).
"""
from __future__ import annotations

import os

import numpy as np

CS_SIGMA_MIN = 0.25      # Tikhonov floor of the rest-space solve (bake_cs.py history: h3_storm_elemental 2026-09-26)
ITERATIONS, FACTOR = 30, 0.7
SCALE_MIN = 0.9          # vertices whose weighted bone scale is at or below this keep d = 0 (shrink / hide clips)
# a corner whose height (shortest incident edge x sin(angle)) is below this x body scale defines no frame (weight 0)
DEGEN_CORNER_HEIGHT = 1e-9
BAKE_SCHEMA = "homm3_def_retarget.cs_bake.v3"
SUPERSEDED_SCHEMAS = ("homm3_def_retarget.cs_bake.v2",)   # float64, undefined groups at S (no fill)
FILL_COMPONENT_MAX = 6000  # more undefined groups to fill than this at one pose is refused (dense solve), never truncated
BAKE_ENGINE = "tools/homm3_glb_patch/cs_numpy.py float64"
BAKE_STAMP = "homm3DefRetargetCsBake"      # scene property on the .blend and asset.extras key on the GLB
# Conditioning against Blender's legacy float32 bytes (the patch lane's parity split, patch_glb.py): measured against
# Blender 5.2 (the modifier dumped on the same proxy), smoothing agrees to 3e-7 everywhere and the corrected result to
# <= 6e-5 H on groups whose incident smoothed edges (rest and posed) are >= COND_EDGE H; below it the error reaches
# 0.18 H. A GLB baked by this module (BAKE_STAMP, BAKE_SCHEMA) is numpy's own output and needs no split.
COND_EDGE = 1e-3
_EPS32 = float(np.finfo(np.float32).eps) * 10.0
# offsets_batch device (docs/town_gpu_kernels.md, "CS re-bake"): "cuda" runs the same arithmetic bit for bit in
# cs_torch.py (patch lane and cs_rekey); "cpu" is this file's reference. bake_cs.py (inside Blender, no torch) never
# calls offsets_batch. No fallback: cuda without torch or a CUDA device raises SystemExit.
DEVICES = ("cpu", "cuda")


def resolve_device(device: str | None = None) -> str:
    d = device or os.environ.get("HOMM3_CS_DEVICE", "").strip() or "cuda"
    if d not in DEVICES:
        raise SystemExit(f"cs_numpy: device {d!r} is not one of {DEVICES} (HOMM3_CS_DEVICE)")
    return d


def rule() -> dict:
    """The bake rule a stamp records (and the validator compares against this module)."""
    return {"engine": BAKE_ENGINE, "precision": "float64", "smooth": "LENGTH_WEIGHTED", "restSource": "rest mesh",
            "degenerateCornerHeight": DEGEN_CORNER_HEIGHT, "degenerateGroup": "harmonic fill of the weld neighbours' C - S (exact per component); no defined neighbour: skinning only",
            "sigmaMin": CS_SIGMA_MIN, "scaleMin": SCALE_MIN}


def bake_smoothing(record: dict | None) -> tuple[int, float]:
    """(iterations, factor) a re-bake must smooth with to reproduce a stored bake: the bake record's own values.
    A float64 bake (BAKE_SCHEMA) records them (bake_cs.py: unit configs may set correctiveSmooth iterations/factor,
    h3_pegasus 60 / 0.8); re-baking it with the module defaults (30 / 0.7) failed parity at p99 0.08 H (2026-10-09).
    A BAKE_SCHEMA record without them refuses. A legacy float32 bake (no record) keeps the module defaults."""
    if not isinstance(record, dict) or record.get("schema") != BAKE_SCHEMA:
        return ITERATIONS, FACTOR
    it, fa = record.get("iterations"), record.get("factor")
    if not isinstance(it, int) or isinstance(it, bool) or it < 1 or not isinstance(fa, (int, float)) or not fa > 0:
        raise SystemExit(f"cs_numpy: the {BAKE_SCHEMA} bake record has no valid iterations/factor ({it!r}, {fa!r}); "
                         "a re-bake cannot reproduce it")
    return it, float(fa)


def _scatter(idx: np.ndarray, vals: np.ndarray, n: int) -> np.ndarray:
    """sum of vals (m, K) into n rows by idx (m,): a bincount per flattened column (no scipy: runs inside Blender)."""
    K = vals.shape[1]
    flat = (idx[:, None] * K + np.arange(K)[None]).ravel()
    return np.bincount(flat, vals.ravel(), n * K).reshape(n, K)


class Weld:
    """bake_cs's welded proxy. Weld(V, J, W, F) builds it from GLB vertices (rest V, joints J, weights W normalised,
    triangles F); Weld.from_groups(gid, polys, V) from a group id per vertex and polygons (Blender's own loops)."""

    def __init__(self, V: np.ndarray, J: np.ndarray, W: np.ndarray, F: np.ndarray):
        keys = {}
        gid = np.empty(len(V), np.int64)
        # the GID key is (rounded rest position, rounded dense weight row); a dense row per vertex over its own joints
        for i in range(len(V)):
            w = {}
            for j, x in zip(J[i], W[i]):
                if x > 0:
                    w[int(j)] = w.get(int(j), 0.0) + float(x)
            k = (tuple(np.round(V[i], 5)), tuple(sorted((j, round(x, 3)) for j, x in w.items() if round(x, 3) != 0)))
            gid[i] = keys.setdefault(k, len(keys))
        self._build(gid, [np.asarray(f, np.int64) for f in np.asarray(F, np.int64)], np.asarray(V, np.float64))

    @classmethod
    def from_groups(cls, gid: np.ndarray, polys, V: np.ndarray) -> "Weld":
        w = cls.__new__(cls)
        w._build(np.asarray(gid, np.int64), [np.asarray(p, np.int64) for p in polys], np.asarray(V, np.float64))
        return w

    def _build(self, gid, polys, V):
        self.n = len(gid)
        self.gid = gid
        self.keep = None      # per-group share of the corrective displacement kept (set_exclusion); None = all of it
        self.ng = int(gid.max()) + 1 if len(gid) else 0
        rep = np.zeros(self.ng, np.int64)
        rep[gid] = np.arange(self.n)
        self.rep = rep
        # the body scale the degenerate rule is relative to (rotation-free: the largest rest extent)
        self.scale = float(np.ptp(V, axis=0).max()) if len(V) else 1.0
        cp, cc, cn, ea, eb, faces = [], [], [], [], [], []
        for p in polys:
            f = gid[p]
            if len(set(f.tolist())) != len(f):
                continue                      # bake_cs: a face with a repeated group is not in the proxy
            faces.append(f)
            cp.append(np.roll(f, 1))
            cc.append(f)
            cn.append(np.roll(f, -1))
            ea.append(f)
            eb.append(np.roll(f, -1))
        self.faces = faces
        self.c_prev = np.concatenate(cp) if cp else np.zeros(0, np.int64)
        self.c_curr = np.concatenate(cc) if cc else np.zeros(0, np.int64)
        self.c_next = np.concatenate(cn) if cn else np.zeros(0, np.int64)
        e = np.sort(np.stack([np.concatenate(ea), np.concatenate(eb)], 1), 1) if ea else np.zeros((0, 2), np.int64)
        self.edges = np.unique(e, axis=0)
        self.edge_count = np.bincount(self.edges.ravel(), minlength=self.ng).astype(np.float64)

    def set_exclusion(self, m: np.ndarray | None) -> None:
        """m: per weld group, the summed normalised weight on the unit's CS-excluded bones (correctiveSmooth.excludeBones).
        The corrective displacement C - S is scaled by 1 - m (Blender's Corrective Smooth vertex-group influence, as a
        weight ramp): a group skinned only to excluded bones moves rigidly with them, one half on them keeps half.
        For rigid distal segments whose thin tips thirty iterations collapse (h3_royal_griffin wingtips: a 0.22 m rest
        delta on a 1.39 m body, 6 mm edges stretched 10x by the frame rotation alone). None or all zero: no-op."""
        if m is None or not np.any(np.asarray(m) > 0):
            self.keep = None
            return
        m = np.asarray(m, np.float64)
        if m.shape != (self.ng,):
            raise ValueError(f"set_exclusion: {m.shape} for {self.ng} weld groups")
        self.keep = np.clip(1.0 - m, 0.0, 1.0)

    # ------------------------------------------------------------------ Blender's Corrective Smooth, float64
    def smooth(self, X: np.ndarray, iterations: int = ITERATIONS, factor: float = FACTOR) -> np.ndarray:
        """X: (ng, 3), or (ng, B, 3) for B independent poses smoothed at once."""
        one = X.ndim == 2
        X = np.array(X[:, None, :] if one else X, dtype=np.float64)
        a, b = self.edges[:, 0], self.edges[:, 1]
        lam = factor * 2.0
        B = X.shape[1]
        for _ in range(iterations):
            d = X[b] - X[a]                                        # x_b - x_a per edge
            ln = np.sqrt(np.einsum("ebk,ebk->eb", d, d))
            wd = (d * ln[..., None]).reshape(len(a), B * 3)
            delta = _scatter(a, wd, self.ng) - _scatter(b, wd, self.ng)
            div = (_scatter(a, ln, self.ng) + _scatter(b, ln, self.ng)) * self.edge_count[:, None]
            coef = np.where(div > _EPS32, lam / np.where(div > _EPS32, div, 1.0), 0.0)
            X += delta.reshape(self.ng, B, 3) * coef[..., None]
        return X[:, 0] if one else X

    def tangents(self, X: np.ndarray):
        """Per corner 3x3 frame (rows = axes), angle weight, and validity (the degenerate-corner rule)."""
        ep = X[self.c_prev] - X[self.c_curr]
        en = X[self.c_curr] - X[self.c_next]
        lp = np.linalg.norm(ep, axis=1)
        lq = np.linalg.norm(en, axis=1)

        def nrm(v):
            ln = np.linalg.norm(v, axis=1, keepdims=True)
            return np.where(ln > 0, v / np.where(ln > 0, ln, 1), 0.0)
        dp, dn = nrm(ep), nrm(en)
        same = np.all(np.abs(dp - dn) <= _EPS32, axis=1)       # Blender: parallel edges, identity frame, weight 0
        cr = np.cross(dp, dn)
        s = np.linalg.norm(cr, axis=1)
        t2 = nrm(cr)
        t0 = nrm(dp + dn)
        t1 = np.cross(t2, t0)
        T = np.stack([t0, t1, t2], 1)
        wt = np.abs(np.arccos(np.clip(np.einsum("ij,ij->i", dn, dp), -1.0, 1.0)))
        valid = ~same & (np.minimum(lp, lq) * s >= DEGEN_CORNER_HEIGHT * self.scale)
        T[~valid] = np.eye(3)
        wt[~valid] = 0.0
        return T, wt, valid

    def min_edge(self, X: np.ndarray) -> np.ndarray:
        """Per group, the shortest incident edge of X (the conditioning of its corner frames)."""
        ln = np.linalg.norm(X[self.edges[:, 1]] - X[self.edges[:, 0]], axis=1)
        m = np.full(self.ng, np.inf)
        np.minimum.at(m, self.edges[:, 0], ln)
        np.minimum.at(m, self.edges[:, 1], ln)
        return m

    def rest_deltas(self, R: np.ndarray, iterations: int = ITERATIONS, factor: float = FACTOR) -> np.ndarray:
        """delta_cache: per corner, the rest-minus-smoothed-rest offset in the smoothed rest's corner frame."""
        R = np.asarray(R, np.float64)
        self.iterations, self.factor = iterations, factor
        Rs = self.smooth(R, iterations, factor)
        self.rest_min_edge = self.min_edge(Rs)
        T, _, self.rest_valid = self.tangents(Rs)
        delta = R[self.c_curr] - Rs[self.c_curr]
        # Blender: imat = inverse(ts), falling back to the transpose when singular; a valid frame is orthonormal
        # (inverse = transpose) and an invalid one is the identity here: cache_i = axis_i . delta
        return np.einsum("cij,cj->ci", T, delta)

    def corrective(self, S: np.ndarray, cache: np.ndarray, X: np.ndarray | None = None) -> np.ndarray:
        """Corrective Smooth of the deformed group positions S (ng x 3); X = smooth(S) when precomputed.
        Sets last_min_edge, last_skin_only (groups with no valid corner, which return S) and last_invalid_corners."""
        S = np.asarray(S, np.float64)
        X = self.smooth(S, self.iterations, self.factor) if X is None else X
        self.last_min_edge = np.minimum(self.min_edge(X), self.rest_min_edge)
        T, wt, valid = self.tangents(X)
        valid &= self.rest_valid
        wt = np.where(valid, wt, 0.0)
        wsum = np.bincount(self.c_curr, wt, self.ng)
        w = np.where(wsum[self.c_curr] > 0, wt / np.where(wsum[self.c_curr] > 0, wsum[self.c_curr], 1), 0.0)
        M = np.transpose(T, (0, 2, 1))
        add = np.einsum("cij,cj->ci", M, cache) * w[:, None]
        out = X + _scatter(self.c_curr, add, self.ng)
        skin_only = wsum <= 0
        D = out - S
        D[skin_only] = 0.0
        self.last_skin_only = skin_only
        self.last_invalid_corners = int((~valid).sum())
        self.last_unfilled = 0
        if skin_only.any():
            D, self.last_unfilled = self._fill(D, skin_only)
        if self.keep is not None:
            D = D * self.keep[:, None]
        return S + D

    def _fill(self, D: np.ndarray, free: np.ndarray) -> tuple[np.ndarray, int]:
        """Harmonic interpolation of D on the undefined groups `free` with the defined groups as the boundary
        (uniform weld-graph Laplacian, one exact dense solve; the system is block diagonal over the connected undefined
        components). A component with no defined neighbour keeps D = 0 (skinning only). Returns (D, groups unfilled)."""
        a, b = self.edges[:, 0], self.edges[:, 1]
        inc = free[a] | free[b]
        a, b = a[inc], b[inc]
        ff = free[a] & free[b]
        # connected components of the undefined subgraph (min-label propagation + pointer jumping; no scipy in Blender)
        lab = np.where(free, np.arange(self.ng), -1)
        fa, fb = a[ff], b[ff]
        while len(fa):
            m = np.minimum(lab[fa], lab[fb])
            new = lab.copy()
            np.minimum.at(new, fa, m); np.minimum.at(new, fb, m)
            new[free] = new[new[free]]
            if np.array_equal(new, lab):
                break
            lab = new
        # components touching a defined group (an edge free -> defined)
        cross = free[a] != free[b]
        fside = np.where(free[a[cross]], a[cross], b[cross])
        touched = np.zeros(self.ng, bool); touched[np.unique(lab[fside])] = True
        solve = free & touched[np.maximum(lab, 0)]
        unfilled = int(free.sum() - solve.sum())
        n = int(solve.sum())
        if n == 0:
            return D, unfilled
        if n > FILL_COMPONENT_MAX:
            raise RuntimeError(f"cs_numpy: {n} undefined weld groups to fill exceeds FILL_COMPONENT_MAX "
                               f"{FILL_COMPONENT_MAX}; refusing rather than truncating the fill")
        idx = -np.ones(self.ng, np.int64); nodes = np.flatnonzero(solve); idx[nodes] = np.arange(n)
        L = np.zeros((n, n)); rhs = np.zeros((n, 3))
        for p, q in ((a, b), (b, a)):
            sel = idx[p] >= 0
            pi, qq = idx[p[sel]], q[sel]
            np.add.at(L, (pi, pi), 1.0)
            inner = idx[qq] >= 0
            np.add.at(L, (pi[inner], idx[qq[inner]]), -1.0)
            np.add.at(rhs, pi[~inner], D[qq[~inner]])
        D = D.copy()
        D[nodes] = np.linalg.solve(L, rhs)
        return D, unfilled


def exclusion_share(J: np.ndarray, W: np.ndarray, joint_names, exclude) -> np.ndarray:
    """Per vertex, the summed normalised weight (J, W 4-influence) on joints named in exclude."""
    ex = np.array([nm in set(exclude or ()) for nm in joint_names] + [False])
    return (np.asarray(W, np.float64) * ex[np.asarray(J, np.int64)]).sum(1)


def skin_mats(world_joint: np.ndarray, ibm: np.ndarray) -> np.ndarray:
    return world_joint @ ibm


def _skin(V, J, W, Sk):
    """Linear blend skinning of V by 4-influence (J, W) with per-joint 4x4 skin matrices Sk (float64)."""
    Vh = np.c_[V, np.ones(len(V))]
    S = np.zeros((len(V), 3))
    Mb = np.zeros((len(V), 3, 3))
    sc = np.cbrt(np.abs(np.linalg.det(Sk[:, :3, :3])))
    scale = np.zeros(len(V))
    for k in range(J.shape[1]):
        m = Sk[J[:, k]]
        S += W[:, k:k + 1] * np.einsum("nij,nj->ni", m, Vh)[:, :3]
        Mb += W[:, k, None, None] * m[:, :3, :3]
        scale += W[:, k] * sc[J[:, k]]
    return S, Mb, scale


def skin_dense(V, Wt, M):
    """Linear blend skinning with a dense normalised weight matrix Wt (n x bones) and per-bone 4x4 M (float64), as
    Blender's Armature modifier deforms (vertex groups, no envelopes, no preserve volume): a vertex with no weight
    keeps its rest position. Returns S, the blended 3x3 Mb and the weighted bone scale."""
    V = np.asarray(V, np.float64)
    M = np.asarray(M, np.float64)
    S = np.einsum("vb,bij,vj->vi", Wt, M[:, :3, :3], V) + Wt @ M[:, :3, 3]
    none = Wt.sum(1) <= 0
    S[none] = V[none]
    Mb = np.einsum("vb,bij->vij", Wt, M[:, :3, :3])
    scale = Wt @ np.cbrt(np.abs(np.linalg.det(M[:, :3, :3])))
    return S, Mb, scale


def solve(gid, rep, S, Mb, scale, C):
    """Rest-space offset per vertex: (Mb^T Mb + lam^2 I)^-1 Mb^T (C - S) over the vertex's group, 0 where scale <= 0.9.
    A blend of opposing bone rotations is near-singular long before its det reaches 1e-6, and an exact solve through it
    multiplies the smoothing offset by 1/sigma_min (h3_storm_elemental shipped 320-unit offsets on a 1.7-unit body,
    2026-09-26); the Tikhonov floor bounds |d| <= |diff| / (2 lam). Scaled-down bodies (shrinkOut deaths, teleports)
    would be re-inflated by CS, hence the scale mask."""
    diff = (C - S[rep])[gid]
    d = np.zeros_like(diff)
    ok = scale > SCALE_MIN
    MT = np.transpose(Mb[ok], (0, 2, 1))
    d[ok] = np.linalg.solve(MT @ Mb[ok] + CS_SIGMA_MIN ** 2 * np.eye(3), (MT @ diff[ok][..., None]))[..., 0]
    return d


def _solve(weld, S, Mb, scale, C):
    return solve(weld.gid, weld.rep, S, Mb, scale, C)


def offsets(weld: Weld, V: np.ndarray, J: np.ndarray, W: np.ndarray, Sk: np.ndarray, cache: np.ndarray,
            cond_edge: float | None = None):
    """The rest-space morph offset d for every GLB vertex at one pose (Sk: per skin joint 4x4 skin matrices).
    With cond_edge (an absolute length), also the per-vertex mask of conditioned groups (see COND_EDGE)."""
    S, Mb, scale = _skin(V, J, W, Sk)
    d = _solve(weld, S, Mb, scale, weld.corrective(S[weld.rep], cache))
    if cond_edge is None:
        return d
    return d, (weld.last_min_edge >= cond_edge)[weld.gid]


def offsets_batch(weld: Weld, V, J, W, Sks, cache, cond_edge: float, chunk: int = 32, device: str | None = None):
    """offsets() for a list of poses, the smoothing run over up to `chunk` poses at once (same arithmetic).
    device (resolve_device): "cuda" runs cs_torch.offsets_batch, bit-identical to this reference."""
    if resolve_device(device) == "cuda":
        import cs_torch
        return cs_torch.offsets_batch(weld, V, J, W, Sks, cache, cond_edge, chunk)
    out = []
    for i in range(0, len(Sks), chunk):
        sk = [_skin(V, J, W, x) for x in Sks[i:i + chunk]]
        X = weld.smooth(np.stack([s[0][weld.rep] for s in sk], 1), weld.iterations, weld.factor)
        for k, (S, Mb, scale) in enumerate(sk):
            C = weld.corrective(S[weld.rep], cache, X[:, k])
            out.append((_solve(weld, S, Mb, scale, C), (weld.last_min_edge >= cond_edge)[weld.gid]))
    return out
