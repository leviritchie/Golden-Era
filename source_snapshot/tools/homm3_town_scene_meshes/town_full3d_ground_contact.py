#!/usr/bin/env python3
"""Town full-3D: ground contact of the environment's free-standing pieces (houses, props, near rocks, boulders).

    python town_full3d_ground_contact.py audit --out <json>      (TOWN_FULL3D_FACTION / TOWN_FULL3D_CANDIDATE)

Why (Castle zs_v5, user in-game 2026-10-01: "some floating in the air"): the environment relief places each painted
piece at the depth its rest px was given, independent of the terrain under it. At rest nothing shows it, but at any
pose that looks across the piece the gap under it opens: Castle zs_v5 had 4 of its 11 cottage pieces 2.5-6.9 m above
the ground and 641 of 934 shrub pieces more than 5 cm up. The zero-streak certificate counts stretch on revealed px
only, so it never saw this.

Pieces (pieces()): a prop bin's model copies (a copy is many components: a part above its own model's base is not
floating), a houses bin's welded models, any other piece bin's welded components. Ground: the environment's terrain bins (GROUND below). A piece's gap is the smallest height of its lowest
points above the highest ground surface straight under them (world up); the Backstop is not ground (it is ground's
far stand-in, behind everything).

anchor(), in this order (coordinator 2026-10-01: piece slide, then ground, then fail closed; rest identity 0 px in
every build state):
  piece slide  the piece scaled about the rest camera (prefab-local: the camera is the origin, so v * s keeps every
          one of its rest px) by the smallest s >= 1 at which its gap is within ANCHOR_TOL_M; kept only when no
          state's rest frame changes (rest_identity());
  ground fill  else the ground hidden behind the piece at rest slides along its own rest rays onto the piece's base
          plane (ground_slide()): the cause of the big gaps is the houses lane's silhouette carve, which pushed the
          terrain behind each cottage back to the ring's far depth, leaving a pit under its footprint;
  fail closed  else (strict), or the piece is reported (audit); a piece whose gap is already within CONTACT_GATE_M
          is left as it is and recorded "withinGate" (ANCHOR_TOL_M is the target, the gate is the acceptance).

contact_gate(): pass when no piece is more than CONTACT_GATE_M above the ground and every piece has ground under it.

Device (TOWN_FULL3D_DEVICE / --device; town_gpu_kernels.resolve_device, default cuda). cpu is the reference; cuda
must reproduce it exactly (test_town_ground_contact_gpu.py compares the two on a staged candidate). There is no
fallback: a missing CUDA device raises.
  ground lookup  Ground buckets the ground triangles per 1 m cell once (vectorized, shared), after bisecting every
                 triangle wider than SPLIT_CELLS cells (Ground.split_oversized, on the device: same bits). cpu: a loop per query
                 point; cuda: every query point's candidate triangles at once in torch float64 (the same elementwise
                 formulas, no matmul, so the same bits), then a segment max. Callers batch: records() takes every
                 piece's lowest points in one query and piece_scale() its whole 1 % scan in one.
  rasters        Rasters: the rest-camera z-buffers the fill and the rest-identity check read. cpu: TP.zbuffer per
                 call (a context and a full upload each); cuda: one town_gpu_kernels.Raster context, the whole stage's
                 vertices in one buffer rewritten only for bins whose vertex array changed, an index buffer per build
                 state (built once: anchoring moves vertices, never faces), the same shader and the same triangle
                 order, so the same z and primitive ids.

Proof tier: generated artifact (offline geometry); the in-game look is the user's check.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SCHEMA = "town_ground_contact.v1"
WELD_M = 0.0005           # vertex weld (m) before the components are taken
GROUP_M = 0.25            # Mesh_Houses: a small component this close to a house model's box belongs to it
LOW_POINTS = 24           # a piece's gap is taken over its LOW_POINTS lowest vertices
ANCHOR_TOL_M = 0.05       # anchored: within this of the ground
CONTACT_GATE_M = 0.15     # the gate: a piece base more than this above the ground fails
S_MAX = 4.0               # anchoring scale limit (a piece needing more meets no ground along its rays)
FILL_HIDDEN_TOL = 1e-3     # ground fill: a vertex this far (ratio) behind the piece's rest front at its px is hidden
FILL_SPIKE_DEG = 45.0      # fail closed: a filled ground triangle (all three vertices moved) steeper than this
FILL_ROUNDS = 6            # ground fill: rounds that freeze a face it brought into the rest frame
FILL_LIFT_M = 0.25         # ground fill: the filled ground may stand this far over the piece's base (it meets the
                           # nearer ground sheet's edge under a base that stands over the seam between two sheets)
FILL_BACK = 0.002          # ground fill: a sheet behind the front one goes this ratio behind the plane
UP = np.array([0.0, 1.0, 0.0])
GROUND = re.compile(r"^Mesh_(\w*Terrain\w*|Outer[CLR]\d+)$")   # every terrain sheet (front, back, near, far, upright, mirror)
PIECE = re.compile(r"^Mesh_(Houses|Prop_[A-Za-z0-9]+|Near_[A-Za-z]+(_\d+)?|Outer_[a-z]+_\d+)$")
NEITHER = {"Mesh_Backstop"}
EXT_DROP = re.compile(r"^Mesh_Near_[A-Za-z]+(_\d+)?$")   # extensionDrop: the nearfield dressing of the frame extension


def fail(msg: str):
    raise SystemExit(f"ground contact: {msg}")


def classify(name: str) -> str | None:
    """'ground', 'piece' or None (the backstop); any other lit environment Mesh_ bin fails closed."""
    if name in NEITHER:
        return None
    if GROUND.match(name):
        return "ground"
    if PIECE.match(name):
        return "piece"
    fail(f"environment bin {name!r} is neither ground nor a piece (classify it in town_full3d_ground_contact)")


class Ground:
    """The highest ground surface straight under a world point, on a 1 m horizontal bucket grid (CSR: cell keys
    sorted, each cell's triangles). device cpu (the reference) or cuda (the same answer, every point at once)."""
    CELL = 1.0
    # every triangle is bucketed over the cells of its bounding box. A per-axis span cap (64) used to drop the large
    # triangles silently, so a coarse terrain sheet had no ground under the props on it (Cove ssr_dfix 2026-10-01:
    # 2141 Mesh_Terrain triangles up to 254 cells wide skipped; agave / reeds read unsupported). Fail closed on a grid
    # larger than CELL_BUDGET entries instead.
    CELL_BUDGET = 60_000_000
    # A long sliver's bounding box covers far more cells than the sliver (Fortress ssr_v1 2026-10-02: Mesh_Terrain's
    # 280261 triangles, 215817 m2 horizontal, filled 90968220 bbox cells; 3238 slivers up to 38958 cells each). The
    # lookup therefore buckets a split copy of the ground (split_oversized): every triangle whose bbox spans more than
    # SPLIT_CELLS cells is bisected on its longest horizontal edge until none does. The halves of a planar triangle
    # are that plane, so the highest surface under any point is the same (up to the midpoints' float rounding); the
    # staged mesh is never touched. CELL_BUDGET still fails closed on the split grid.
    SPLIT_CELLS = 16
    SPLIT_ROUNDS = 48

    def __init__(self, P: np.ndarray, F: np.ndarray, device: str = "cpu"):
        e1 = np.cross(UP, [0.0, 0.0, 1.0]); e1 /= np.linalg.norm(e1)
        e2 = np.cross(UP, e1)
        self.E = np.stack([e1, e2], 1)
        self.P = P
        self.device = device
        H2, HT = P @ self.E, P @ UP
        self.split = {"faces": int(len(F))}
        self.H2, self.HT, F = self.split_oversized(H2, HT, np.asarray(F, np.int64), device)
        self.F = F
        self.split.update(splitFaces=int(len(F)), verts=int(len(self.H2)))
        tb = self.H2[F]
        lo = np.floor(tb.min(1) / self.CELL).astype(np.int64)
        hi = np.floor(tb.max(1) / self.CELL).astype(np.int64)
        t = np.arange(len(F))
        n0, n1 = hi[t, 0] - lo[t, 0] + 1, hi[t, 1] - lo[t, 1] + 1
        cnt = n0 * n1
        self.split["cellEntries"] = int(cnt.sum())
        if int(cnt.sum()) > self.CELL_BUDGET:
            raise SystemExit(f"ground grid: {int(cnt.sum())} cell entries > {self.CELL_BUDGET} after splitting "
                             f"{self.split['faces']} -> {len(F)} triangles to <= {self.SPLIT_CELLS} cells each "
                             f"(largest {int(n0.max())} x {int(n1.max())} cells): the ground is too large for the "
                             f"1 m grid")
        k = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        n1r = np.repeat(n1, cnt)
        key = self._key(np.repeat(lo[t, 0], cnt) + k // n1r, np.repeat(lo[t, 1], cnt) + k % n1r)
        tt = np.repeat(t, cnt)
        o = np.lexsort((tt, key))
        self.keys, start = np.unique(key[o], return_index=True)
        self.tris = tt[o]
        self.start = start.astype(np.int64)
        self.end = np.r_[self.start[1:], len(self.tris)].astype(np.int64)
        if device == "cuda":
            import town_gpu_kernels as GK
            torch = self.torch = GK.require_cuda()
            d = dict(device="cuda")
            self.t = {"H2": torch.as_tensor(self.H2, dtype=torch.float64, **d),
                      "HT": torch.as_tensor(self.HT, dtype=torch.float64, **d),
                      "F": torch.as_tensor(np.asarray(F, np.int64), **d),
                      "keys": torch.as_tensor(self.keys, **d), "tris": torch.as_tensor(self.tris, **d),
                      "start": torch.as_tensor(self.start, **d), "end": torch.as_tensor(self.end, **d)}

    @classmethod
    def split_oversized(cls, H2: np.ndarray, HT: np.ndarray, F: np.ndarray, device: str):
        """(H2, HT, F) with every triangle whose horizontal bbox spans more than SPLIT_CELLS cells bisected on its
        longest horizontal edge, repeatedly (see SPLIT_CELLS). The midpoints are appended (not shared between
        neighbours: the lookup needs no welded mesh). Per-face elementwise math on the device's array namespace (_xp:
        the same bits on cpu and cuda); fails closed when SPLIT_ROUNDS do not bound every triangle."""
        X = _xp(device)
        h2, ht, f = X.arr(H2), X.arr(HT), X.arr(F)
        if not len(F):
            return H2, HT, F
        for _ in range(cls.SPLIT_ROUNDS):
            tb = h2[f]                                             # (m, 3, 2)
            if X.cuda:
                mn, mx = tb.min(1).values, tb.max(1).values
                n = (X.t.floor(mx / cls.CELL) - X.t.floor(mn / cls.CELL) + 1).prod(1)
            else:
                n = (np.floor(tb.max(1) / cls.CELL) - np.floor(tb.min(1) / cls.CELL) + 1).prod(1)
            sel = n > cls.SPLIT_CELLS
            if not bool(sel.any()):
                return X.np(h2), X.np(ht), X.np(f)
            fs, keep = f[sel], f[~sel]
            a0, a1, a2 = h2[fs[:, 0]], h2[fs[:, 1]], h2[fs[:, 2]]

            def l2(p, q):
                d = q - p
                return d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]
            e0, e1, e2 = l2(a0, a1), l2(a1, a2), l2(a2, a0)
            k = X.where((e0 >= e1) & (e0 >= e2), 0, X.where(e1 >= e2, 1, 2))
            if X.cuda:
                k = k.to(X.t.int64)
                r = X.t.arange(len(fs), device="cuda")
            else:
                k = k.astype(np.int64)
                r = np.arange(len(fs))
            ia, ib, io = fs[r, k], fs[r, (k + 1) % 3], fs[r, (k + 2) % 3]
            mid2 = (h2[ia] + h2[ib]) * 0.5
            midt = (ht[ia] + ht[ib]) * 0.5
            if X.cuda:
                im = X.t.arange(len(h2), len(h2) + len(fs), device="cuda")
                h2, ht = X.t.cat([h2, mid2]), X.t.cat([ht, midt])
                f = X.t.cat([keep, X.t.stack([ia, im, io], 1), X.t.stack([im, ib, io], 1)])
            else:
                im = np.arange(len(h2), len(h2) + len(fs))
                h2, ht = np.concatenate([h2, mid2]), np.concatenate([ht, midt])
                f = np.concatenate([keep, np.stack([ia, im, io], 1), np.stack([im, ib, io], 1)])
        raise SystemExit(f"ground grid: {cls.SPLIT_ROUNDS} bisection rounds left triangles over {cls.SPLIT_CELLS} "
                         f"cells (a triangle longer than {2 ** (cls.SPLIT_ROUNDS // 2)} m?)")

    @staticmethod
    def _key(i, j):
        return (i + 2**30) * 2**31 + (j + 2**30)

    def gap(self, Q: np.ndarray) -> np.ndarray:
        """Per point: its height above the highest ground surface under it (a surface up to 0.5 m above the point
        counts: a negative gap is buried); inf where no ground is under it."""
        q2, hq = Q @ self.E, Q @ UP
        if self.device == "cuda":
            return self._gap_cuda(q2, hq)
        g = np.full(len(Q), np.inf)
        ci = np.floor(q2 / self.CELL).astype(np.int64)
        key = self._key(ci[:, 0], ci[:, 1])
        pos = np.searchsorted(self.keys, key)
        for n in range(len(Q)):
            if pos[n] >= len(self.keys) or self.keys[pos[n]] != key[n]:
                continue
            x, y = q2[n]
            f = self.F[self.tris[self.start[pos[n]]:self.end[pos[n]]]]
            a, b, c = self.H2[f[:, 0]], self.H2[f[:, 1]], self.H2[f[:, 2]]
            v0, v1 = b - a, c - a
            v2 = np.array([x, y])[None] - a
            den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
            with np.errstate(divide="ignore", invalid="ignore"):
                u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
                w = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
            ins = (u >= -1e-9) & (w >= -1e-9) & (u + w <= 1 + 1e-9) & (np.abs(den) > 1e-12)
            if not ins.any():
                continue
            fi = f[ins]
            hh = (1 - u[ins] - w[ins]) * self.HT[fi[:, 0]] + u[ins] * self.HT[fi[:, 1]] + w[ins] * self.HT[fi[:, 2]]
            hh = hh[hh <= hq[n] + 0.5]
            if len(hh):
                g[n] = hq[n] - hh.max()
        return g

    def _gap_cuda(self, q2: np.ndarray, hq: np.ndarray) -> np.ndarray:
        """gap() for every point at once: the same elementwise float64 formulas as the loop (same bits), a segment max."""
        torch, t = self.torch, self.t
        if not len(q2):
            return np.zeros(0)
        tq = torch.as_tensor(q2, dtype=torch.float64, device="cuda")
        th = torch.as_tensor(hq, dtype=torch.float64, device="cuda")
        ci = torch.floor(tq / self.CELL).to(torch.int64)
        key = self._key(ci[:, 0], ci[:, 1])
        pos = torch.searchsorted(t["keys"], key)
        posc = pos.clamp(max=len(self.keys) - 1)
        hit = (pos < len(self.keys)) & (t["keys"][posc] == key)
        s0 = torch.where(hit, t["start"][posc], torch.zeros_like(pos))
        cnt = torch.where(hit, t["end"][posc] - t["start"][posc], torch.zeros_like(pos))
        pt = torch.repeat_interleave(torch.arange(len(q2), device="cuda"), cnt)
        out = torch.full((len(q2),), float("-inf"), dtype=torch.float64, device="cuda")
        if len(pt):
            k = torch.arange(len(pt), device="cuda") - torch.repeat_interleave(torch.cumsum(cnt, 0) - cnt, cnt)
            f = t["F"][t["tris"][torch.repeat_interleave(s0, cnt) + k]]
            H2, HT = t["H2"], t["HT"]
            a, b, c = H2[f[:, 0]], H2[f[:, 1]], H2[f[:, 2]]
            v0, v1 = b - a, c - a
            v2 = tq[pt] - a
            den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
            u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
            w = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
            ins = (u >= -1e-9) & (w >= -1e-9) & (u + w <= 1 + 1e-9) & (den.abs() > 1e-12)
            hh = (1 - u - w) * HT[f[:, 0]] + u * HT[f[:, 1]] + w * HT[f[:, 2]]
            ok = ins & (hh <= th[pt] + 0.5)
            out.scatter_reduce_(0, pt[ok], hh[ok], reduce="amax")
        g = torch.where(torch.isfinite(out), th - out, torch.full_like(out, float("inf")))
        return g.cpu().numpy()


class Rasters:
    """Rest-camera z-buffers of the stage (sup=1): every build state (rest_identity) and the fill's subsets
    (ground_slide). cpu: TP.zbuffer per call, the reference; cuda: one context, see the module doc."""

    def __init__(self, sc, stage, state_keys: dict | None, device: str):
        import town_full3d_t2_paint as TP
        self.TP, self.sc, self.stage, self.state_keys, self.device = TP, sc, stage, state_keys or {}, device
        self.to_world = lambda v: sc.cpos + (v / sc.scale) @ sc.C.T
        if device != "cuda":
            return
        import town_gpu_kernels as GK
        GK.require_cuda()
        self.nv = [len(b["v"]) for b in stage.bins]
        self.nf = [len(b["f"]) for b in stage.bins]
        self.off = np.r_[0, np.cumsum(self.nv)].astype(np.int64)
        self.r = GK.Raster()
        ctx = self.r.ctx
        with ctx:
            self.vbo = ctx.buffer(reserve=max(int(self.off[-1]), 1) * 12)
        self.vref = [None] * len(stage.bins)
        self.vaos, self.fmaps = {}, {}
        for s, ks in self.state_keys.items():
            self.vaos[s] = self._vao(self._state_faces(ks))
            self.fmaps[s] = np.concatenate([np.stack([np.full(len(b["f"]), bi), np.arange(len(b["f"]))], 1)
                                            for bi, b in enumerate(stage.bins) if b["key"] in ks])

    def _state_faces(self, ks) -> np.ndarray:
        """The global triangles of a state in Stage.arrays' order (its primitive ids are the reference's face ids)."""
        return np.concatenate([b["f"] + self.off[bi] for bi, b in enumerate(self.stage.bins) if b["key"] in ks])

    def _vao(self, Fg: np.ndarray):
        ctx = self.r.ctx
        with ctx:
            ibo = ctx.buffer(np.asarray(Fg, np.int32).tobytes())
            return ctx.vertex_array(self.r.prog, [(self.vbo, "3f", "in_pos")], ibo), ibo

    def _sync(self) -> None:
        """Rewrite the vertices of every bin whose vertex array is not the one last uploaded (anchoring replaces a bin's
        array, never edits an uploaded one in place); the topology must be the one the index buffers were built on."""
        for bi, b in enumerate(self.stage.bins):
            if len(b["v"]) != self.nv[bi] or len(b["f"]) != self.nf[bi]:
                fail(f"rasters: bin {b['name']} changed its topology after the index buffers were built")
            if self.vref[bi] is b["v"]:
                continue
            with self.r.ctx:
                self.vbo.write(np.asarray(self.to_world(b["v"]), np.float32).tobytes(), offset=int(self.off[bi]) * 12)
            self.vref[bi] = b["v"]

    def _render(self, vao, cam):
        self._sync()
        self.r.vao = vao
        try:
            return self.r.render(cam)
        finally:
            self.r.vao = None

    def state(self, s: str):
        """(z, fid) of build state s at rest, as TP.zbuffer(sc.cam, *stage.arrays(ks)) returns them; and fmap."""
        if self.device != "cuda":
            P, UV, F, owner, names, texs, fmap = self.stage.arrays(self.state_keys[s])
            return (*self.TP.zbuffer(self.sc.cam, P, F, sup=1), fmap)
        return (*self._render(self.vaos[s][0], self.sc.cam), self.fmaps[s])     # fmap as Stage.arrays builds it

    def subset(self, sel: list):
        """(z, fid) at rest of the triangles sel = [(bin, local faces)], concatenated in that order."""
        if self.device != "cuda":
            Ps, Fs, o = [], [], 0
            for bi, f in sel:
                b = self.stage.bins[bi]
                Ps.append(self.to_world(b["v"])); Fs.append(f + o); o += len(b["v"])
            return self.TP.zbuffer(self.sc.cam, np.concatenate(Ps), np.concatenate(Fs), sup=1)
        vao, ibo = self._vao(np.concatenate([f + self.off[bi] for bi, f in sel]))
        try:
            return self._render(vao, self.sc.cam)
        finally:
            with self.r.ctx:
                vao.release(); ibo.release()

    def release(self) -> None:
        if self.device == "cuda":
            with self.r.ctx:
                for vao, ibo in self.vaos.values():
                    vao.release(); ibo.release()
                self.vbo.release()
            self.r.release()


def components(v: np.ndarray, f: np.ndarray, scale: float) -> np.ndarray:
    """Per vertex: its welded (WELD_M) connected component; -1 for a vertex no face uses."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    q = WELD_M * scale
    _, weld = np.unique(np.round(v / q).astype(np.int64), axis=0, return_inverse=True)
    weld = weld.ravel()
    Fw = weld[f]
    n = int(weld.max()) + 1
    g = coo_matrix((np.ones(Fw.size), (Fw.ravel(), np.roll(Fw, 1, 1).ravel())), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    used = np.zeros(len(v), bool)
    used[f.ravel()] = True
    return np.where(used, lab[weld], -1)


def _split(lv: np.ndarray) -> list:
    order = np.argsort(lv, kind="stable")
    order = order[lv[order] >= 0]
    return np.split(order, np.flatnonzero(np.diff(lv[order])) + 1) if len(order) else []


def instance_blocks(uv: np.ndarray, k: int) -> np.ndarray:
    """Per vertex: its instance, for a bin of k copies of one model written one after another (town_t2_props stage:
    the copies share the model's uv); vertices past the k blocks (repair copies) get -2. Fails closed when the uv
    does not split into k equal blocks."""
    n = len(uv)
    if k == 1:
        return np.zeros(n, np.int64)
    for m in range(3, n // k + 1):
        if np.array_equal(uv[m:2 * m], uv[:m]) and all(np.array_equal(uv[i * m:(i + 1) * m], uv[:m]) for i in range(2, k)):
            lab = np.full(n, -2, np.int64)
            lab[:k * m] = np.repeat(np.arange(k), m)
            return lab
    fail(f"the bin's uv does not split into {k} equal instance blocks")


def pieces(name: str, v: np.ndarray, f: np.ndarray, uv: np.ndarray, scale: float, instances: int | None) -> list:
    """The vertex index sets of the bin's free-standing pieces. Mesh_Prop_<type> (town_t2_props: k copies of one
    Meshy model, k from the catalog's props block): one piece per copy (a copy is many components: leaf clusters,
    crowns). Mesh_Houses (town_full3d_houses: one welded model per instance): every component of at least a quarter
    of the largest, with each smaller component it overlaps (grown by GROUP_M; a chimney cap) joined to it. Any
    other piece bin (near rocks, boulders): one piece per component."""
    if not len(f):
        return []
    if name.startswith("Mesh_Prop_"):
        if instances is None:
            fail(f"{name}: the catalog's props block gives no instance count")
        lab = instance_blocks(uv, int(instances))
        used = np.zeros(len(v), bool)
        used[f.ravel()] = True
        lab = np.where(used | (lab >= 0), lab, -1)
        return _split(np.where(lab == -2, -1, lab))
    lv = components(v, f, scale)
    if name != "Mesh_Houses":
        return _split(lv)
    comps, size = np.unique(lv[lv >= 0], return_counts=True)
    big = comps[size >= 0.25 * size.max()]
    lo = {c: v[lv == c].min(0) - GROUP_M * scale for c in comps}
    hi = {c: v[lv == c].max(0) + GROUP_M * scale for c in comps}
    remap = {c: c for c in comps}
    for c in comps:
        if c in big:
            continue
        hit = [g for g in big if (lo[c] <= hi[g]).all() and (hi[c] >= lo[g]).all()]
        if hit:
            ctr = v[lv == c].mean(0)
            remap[c] = min(hit, key=lambda g: float(np.linalg.norm(v[lv == g].mean(0) - ctr)))
    out = lv.copy()
    for c, g in remap.items():
        out[lv == c] = g
    return _split(out)


def staged_world(sc, v: np.ndarray) -> np.ndarray:
    """World positions of prefab-local vertices as the staged float32 bins (write_bin) hold them."""
    return sc.cpos + (np.asarray(v, np.float32).astype(np.float64) / sc.scale) @ sc.C.T


class Scene:
    """The environment's ground and pieces from a recipe Stage (bins with key, name, v, f; prefab-local units)."""

    def __init__(self, sc, stage, env_key: str, catalog: dict, device: str | None = None, state_keys: dict | None = None):
        import town_gpu_kernels as GK
        self.device = GK.resolve_device(device)
        self.sc, self.stage = sc, stage
        inst = {t["bin"]: int(t["instances"]) for t in (catalog.get("props") or {}).get("types", {}).values()}
        # Measured on the vertices as they ship: the staged bins store float32 (write_bin), the recipe's Stage holds
        # float64 between writes. A contact that only holds at float64 is not the staged one (Cove zs_v1 2026-10-02:
        # a near pebble anchored at -0.24 m in memory, its one supporting low point on the lip of a Mesh_Back_Terrain
        # step; read back from the float32 bins that point fell past the lip and the gate read 1.03 m). Quantizing
        # here gives the anchor, the in-loop re-anchor and the gate on the staged files the same answer.
        self.to_world = lambda v: staged_world(sc, v)
        self.piece_bins, self.ground_bins = [], []
        for bi, b in enumerate(stage.bins):
            if b["key"] != env_key:
                continue
            k = classify(b["name"])
            if k == "ground":
                self.ground_bins.append(bi)
            elif k == "piece":
                self.piece_bins.append(bi)
        if not self.ground_bins:
            fail("the environment stages no ground bin")
        self.pieces = {bi: pieces(stage.bins[bi]["name"], stage.bins[bi]["v"], stage.bins[bi]["f"],
                                  stage.bins[bi]["uv"], sc.scale, inst.get(stage.bins[bi]["name"]))
                       for bi in self.piece_bins}
        self.rebuild_ground()
        self.rasters = Rasters(sc, stage, state_keys, self.device)

    def rebuild_ground(self) -> None:
        Pg, Fg, o = [], [], 0
        for bi in self.ground_bins:
            b = self.stage.bins[bi]
            Pg.append(self.to_world(b["v"])); Fg.append(b["f"] + o); o += len(b["v"])
        self.ground = Ground(np.concatenate(Pg), np.concatenate(Fg), self.device)

    def _low(self, v: np.ndarray, idx: np.ndarray, s: float) -> np.ndarray:
        """World positions of the piece's LOW_POINTS lowest vertices at scale s."""
        Q = self.to_world(v[idx] * s)
        low = idx[np.argsort(Q @ UP)[:LOW_POINTS]]
        return self.to_world(v[low] * s)

    def gaps_of(self, items: list) -> np.ndarray:
        """[gap] for items [(v, idx, s)], one ground query for all of them."""
        Ls = [self._low(v, idx, s) for v, idx, s in items]
        g = self.ground.gap(np.concatenate(Ls)) if Ls else np.zeros(0)
        o = np.r_[0, np.cumsum([len(L) for L in Ls])]
        return np.array([g[o[i]:o[i + 1]].min() for i in range(len(Ls))])

    def gap_of(self, v: np.ndarray, idx: np.ndarray, s: float = 1.0) -> float:
        return float(self.gaps_of([(v, idx, s)])[0])

    def records(self) -> list:
        rows = [(bi, n, idx) for bi in self.piece_bins for n, idx in enumerate(self.pieces[bi])]
        g = self.gaps_of([(self.stage.bins[bi]["v"], idx, 1.0) for bi, _, idx in rows])
        return [{"bin": bi, "name": self.stage.bins[bi]["name"], "piece": n, "verts": int(len(idx)), "idx": idx,
                 "gapM": float(gg)} for (bi, n, idx), gg in zip(rows, g)]


def piece_scale(gs: Scene, b: dict, idx: np.ndarray) -> float | None:
    """The smallest s in (1, S_MAX] at which the piece scaled about the rest camera is within ANCHOR_TOL_M of the
    ground under it; None when there is none."""
    f = lambda s: gs.gap_of(b["v"], idx, s)
    ss, s = [], 1.0                          # the 1 % scan, evaluated in one ground query
    while s < S_MAX:
        s = min(s * 1.01, S_MAX)
        ss.append(s)
    g = gs.gaps_of([(b["v"], idx, s) for s in ss])
    hit = np.flatnonzero(g <= ANCHOR_TOL_M)
    if not len(hit):
        return None
    hi = ss[hit[0]]
    lo = ss[hit[0] - 1] if hit[0] else 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if f(mid) <= ANCHOR_TOL_M:
            hi = mid
        else:
            lo = mid
    return hi


def ground_slide(gs: Scene, b: dict, idx: np.ndarray, T, frozen: dict | None = None, erode: bool = False) -> dict | None:
    """Fill the ground under the piece: the ground hidden at rest behind the piece (its rest silhouette) slides along
    its own rest rays (each vertex keeps its rest px) forward to the point FILL_LIFT_M over the piece's base plane
    (horizontal, at the height of its lowest point); a vertex whose point would lie in front of the piece's rest
    front (or of another surface between the piece and it) stays where it is. Why: a painted piece's terrain was carved back behind
    its silhouette (the houses lane's push-pull carve), so the ground under its footprint is the carved far depth,
    metres below the base (Castle zs_v5 cottage 2: the terrain under its foot at 66-77 m, the cottage at 38 m). The
    fill is that carve's ground continued under the piece instead. Only hidden vertices move, so the rest frame is
    unchanged by construction (rest_identity checks it); ground visible at rest is never moved. Per px the frontmost
    ground sheet takes the plane; a sheet behind it (Mesh_Back_Terrain behind Mesh_Terrain) goes FILL_BACK behind
    it, so the two never coincide. Returns the edit (the old vertex arrays per ground bin), or None when nothing
    moves; the caller checks the gap, the rest frame and the slope. frozen: {ground bin: vertex mask} that must not move (anchor() freezes the vertices of a
    face the fill brought into the rest frame). erode: only a vertex whose whole one-ring is hidden moves (a face across
    the silhouette edge keeps its visible part where it was)."""
    sc = gs.sc
    cpos = np.asarray(sc.cpos, float)
    Pp = gs.to_world(b["v"][idx])
    hb = float((Pp @ UP).min())
    hc = float(cpos @ UP)
    keep = np.zeros(len(b["v"]), bool)
    keep[idx] = True
    bi_p = next(i for i, x in enumerate(gs.stage.bins) if x is b)
    inp = keep[b["f"]].all(1)
    zp, fidp = gs.rasters.subset([(bi_p, b["f"][inp])])
    zp = np.where(fidp >= 0, zp, np.inf)                 # the piece's rest front per px
    Pg = [gs.to_world(gs.stage.bins[gi]["v"]) for gi in gs.ground_bins]
    zg, fidg = gs.rasters.subset([(gi, gs.stage.bins[gi]["f"]) for gi in gs.ground_bins])
    zg = np.where(fidg >= 0, zg, np.inf)                 # the frontmost ground per px
    sel = [(bi, ob["f"][~inp] if bi == bi_p else ob["f"])   # every other surface of every state's prefabs
           for bi, ob in enumerate(gs.stage.bins) if bi not in gs.ground_bins and len(ob["f"])]
    zo, fido = gs.rasters.subset(sel)
    zo = np.where(fido >= 0, zo, np.inf)
    X = _xp(gs.device)
    zp_, zg_, zo_ = X.arr(zp), X.arr(zg), X.arr(zo)
    old, moved_front, moved_back = {}, 0, 0
    for gi, Q in zip(gs.ground_bins, Pg):
        g = gs.stage.bins[gi]
        fz = frozen.get(gi) if frozen else None
        mv, front, vnew = _fill_bin(X, sc.cam, cpos, X.arr(Q), zp_, zg_, zo_, hb, hc,
                                    X.arr(g["f"]) if erode else None, None if fz is None else X.arr(fz),
                                    X.arr(g["v"]))
        n_mv = int(mv.sum())
        if not n_mv:
            continue
        moved_front += int((mv & front).sum())
        moved_back += n_mv - int((mv & front).sum())
        old[gi] = (g["v"].copy(), g["dirty"])
        g["v"] = X.np(vnew)
        g["dirty"] = True
    if not old:
        return None
    gs.rebuild_ground()
    return {"old": old, "frontVertsMoved": moved_front, "backVertsMoved": moved_back,
            "vertsMoved": moved_front + moved_back}


class _xp:
    """The array namespace of a device for the per-vertex / per-face formulas (numpy for cpu, the reference; torch
    CUDA for cuda). Every formula is elementwise (no matmul / BLAS reduction), so both devices compute the same bits:
    float64 + - * / and sqrt are correctly rounded on both, and torch eager runs each op as its own kernel (no FMA
    contraction). Divide through div() only (torch's tensor / scalar is a reciprocal multiply)."""

    def __init__(self, device: str):
        self.cuda = device == "cuda"
        if self.cuda:
            import town_gpu_kernels as GK
            self.t = GK.require_cuda()

    def arr(self, a):
        return self.t.as_tensor(np.asarray(a), device="cuda") if self.cuda else np.asarray(a)

    def np(self, a):
        return a.cpu().numpy() if self.cuda else a

    def where(self, c, a, b):
        if self.cuda:
            T_ = self.t
            ref = a if T_.is_tensor(a) else b if T_.is_tensor(b) else c.to(T_.float64)   # two scalars: float64
            a = a if T_.is_tensor(a) else T_.full_like(ref, a)
            b = b if T_.is_tensor(b) else T_.full_like(ref, b)
            return T_.where(c, a, b)
        return np.where(c, a, b)

    def isfinite(self, a):
        return self.t.isfinite(a) if self.cuda else np.isfinite(a)

    def maximum(self, a, b):
        if self.cuda:
            return self.t.maximum(a, b) if self.t.is_tensor(b) else self.t.clamp(a, min=b)
        return np.maximum(a, b)

    def div(self, a, b):
        """a / b, correctly rounded on both devices: torch divides a tensor by a python scalar (and a scalar by a
        tensor) through a reciprocal multiply, so a scalar operand becomes a full tensor first."""
        if self.cuda:
            T_ = self.t
            ref = a if T_.is_tensor(a) else b
            a = a if T_.is_tensor(a) else T_.full_like(ref, a)
            b = b if T_.is_tensor(b) else T_.full_like(ref, b)
        return a / b

    def sqrt(self, a):
        return self.t.sqrt(a) if self.cuda else np.sqrt(a)

    def zeros_bool(self, n):
        return self.t.zeros(n, dtype=self.t.bool, device="cuda") if self.cuda else np.zeros(n, bool)

    def trunc_index(self, x, hi):
        """int(x) toward zero (nan -> 0), clipped to [0, hi]."""
        if self.cuda:
            return self.t.clamp(self.t.nan_to_num(x).to(self.t.int64), 0, hi)
        return np.clip(np.nan_to_num(x).astype(np.int64), 0, hi)


def _dot(d, v):
    """d (n, 3) . v (3,) elementwise (the same bits on both devices; numpy's @ goes through BLAS)."""
    return d[:, 0] * float(v[0]) + d[:, 1] * float(v[1]) + d[:, 2] * float(v[2])


def _fill_bin(X, cam, cpos, Q, zp, zg, zo, hb: float, hc: float, f, frozen, v):
    """ground_slide's per-vertex step for one ground bin (Q: world vertices, v: the bin's local vertices): (move mask,
    front-sheet mask, the new local vertices). Elementwise only; see _xp."""
    import math
    Hh, Ww = zp.shape
    d = Q - X.arr(np.asarray(cam["pos"], np.float64))
    zc = _dot(d, cam["fwd"])
    tn = math.tan(math.radians(cam["fov"]) / 2)
    px = (X.div(_dot(d, cam["right"]), X.div(zc * tn * Ww, Hh)) + 1) * 0.5 * Ww
    py = (1 - X.div(_dot(d, cam["up"]), zc * tn)) * 0.5 * Hh
    ok = X.isfinite(px) & X.isfinite(py) & (zc > 0)
    xi, yi = X.trunc_index(px, Ww - 1), X.trunc_index(py, Hh - 1)
    zpp, zgg, zoo = zp[yi, xi], zg[yi, xi], zo[yi, xi]
    hidden = ok & X.isfinite(zpp) & (zc > zpp * (1 + FILL_HIDDEN_TOL))
    a = _dot(Q - X.arr(np.asarray(cpos, np.float64)), UP)
    neg = a < -1e-9
    # the nearest point of the ray, behind the piece, no higher than FILL_LIFT_M over the base (t = 1: rest)
    tp = X.where(neg, X.div(hb + FILL_LIFT_M - hc, X.where(neg, a, -1.0)), float("inf"))
    front = zc <= zgg * (1 + FILL_HIDDEN_TOL)
    t = X.where(front, tp, tp * (1 + FILL_BACK))
    zcm = X.maximum(zc, 1e-9)
    # a vertex whose new point would lie in front of a surface that is in front of it at its rest px (the piece, or
    # any other surface of any state) does not move at all (clamping it onto that surface instead stands the filled
    # sheet up as a wall along it: Castle zs_v5 cottages, 89.9 deg)
    bind = X.isfinite(zpp) & (zpp < zc) & (t < X.div(zpp * (1 + FILL_HIDDEN_TOL), zcm))
    bind = bind | (X.isfinite(zoo) & (zoo < zc) & (t < X.div(zoo * (1 + FILL_HIDDEN_TOL), zcm)))
    mv = hidden & ~bind & X.isfinite(t) & (t < 1.0 - 1e-9)
    if f is not None:
        # only a vertex whose whole one-ring is hidden moves: a face across the silhouette edge keeps its visible
        # part where it was
        bad = X.zeros_bool(len(Q))
        cut = ~hidden[f].all(1)
        bad[f[cut].reshape(-1)] = True
        mv = mv & ~bad
    if frozen is not None:
        mv = mv & ~frozen
    vnew = v * X.where(mv, t, 1.0)[:, None]
    vnew = X.where(mv[:, None], vnew, v)                                # unmoved vertices keep their exact bits
    return mv, front, vnew


def undo_ground(gs: Scene, edit: dict) -> None:
    for gi, (o, dirty) in edit["old"].items():
        gs.stage.bins[gi]["v"], gs.stage.bins[gi]["dirty"] = o, dirty
    gs.rebuild_ground()


def max_slope_deg(gs: Scene, edit: dict) -> float:
    """The steepest ground triangle the fill made (all three vertices moved; degrees from horizontal), and only where
    it got steeper. A face with only some vertices moved is the hidden step from the fill down to the carved ground
    behind it: hidden at rest by the piece, and the zero-streak certificate measures it at every reachable pose."""
    import math
    X = _xp(gs.device)
    cmin = 1.0
    for gi, (o, _) in edit["old"].items():
        g = gs.stage.bins[gi]
        mv = (g["v"] != o).any(1)
        f = g["f"][mv[g["f"]].all(1)]
        if not len(f):
            continue

        def cos_up(V):
            """per face |n . up| / |n| (1: flat; elementwise, see _xp)."""
            Q = X.arr(gs.to_world(V)[f])
            e1, e2 = Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0]
            nx = e1[:, 1] * e2[:, 2] - e1[:, 2] * e2[:, 1]
            ny = e1[:, 2] * e2[:, 0] - e1[:, 0] * e2[:, 2]
            nz = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
            ln = X.maximum(X.sqrt(nx * nx + ny * ny + nz * nz), 1e-12)
            return X.div(abs(ny), ln)

        c1, c0 = cos_up(g["v"]), cos_up(o)
        st = c1[c1 < c0 * (1 - 1e-9)]                     # only where the fill made it steeper
        if len(st):
            cmin = min(cmin, float(st.min()))
    return math.degrees(math.acos(min(max(cmin, 0.0), 1.0)))


def extension_drop(gs: Scene, b: dict, idx: np.ndarray, g: float, T, drop: dict) -> tuple[dict | None, str]:
    """extensionDrop (opt-in, recipe groundContact.extensionDrop): a nearfield dressing piece (EXT_DROP) that neither
    the piece slide nor the ground fill can ground, lying wholly outside the painted rect (every vertex, before and
    after), dropped straight down by its gap. Kept only when no build state's rest frame changes inside the painted
    rect (drop["rect"] = (TH, TW)); the px it changes outside the rect (the synthesized extension: no painting there)
    are recorded, and drop["before"] (the frames the rest checks compare with) is rebased onto the new frames.
    Returns (record, "") or (None, why)."""
    sc = gs.sc
    th, tw = drop["rect"]

    def outside(v):
        px, py, zc = T.project(sc.cam, gs.to_world(v))
        return bool(((zc > 0) & ((px > tw) | (py > th))).all())
    v0 = b["v"]
    if not outside(v0[idx]):
        return None, "lies partly inside the painted rect"
    v1 = v0.copy()
    v1[idx] = v0[idx] - g * sc.scale * (UP @ np.asarray(sc.C, float))
    if not outside(v1[idx]):
        return None, "would drop into the painted rect"
    b["v"] = v1
    ga = gs.gap_of(v1, idx)
    if ga > ANCHOR_TOL_M:
        b["v"] = v0
        return None, f"stays {ga:.2f} m up after the drop"
    now = rest_identity(gs, None)
    before = drop["before"]
    inside = {s: int((now[s][:th, :tw] != before[s][:th, :tw]).sum()) for s in now}
    if any(inside.values()):
        b["v"] = v0
        return None, f"changes the painted rect's rest frame {({k: v for k, v in inside.items() if v})}"
    out = {s: int((now[s] != before[s]).sum()) for s in now}
    before.update(now)
    b["dirty"] = True
    return {"how": "extensionDrop", "dropM": round(g, 3), "gapAfterM": round(ga, 3),
            "restPxOutsideRect": {k: v for k, v in out.items() if v}}, ""


REMOVE_HIDDEN_KEYS = {"bin", "piece", "verts", "why"}


def remove_hidden(stage, sc, env_key: str, catalog: dict, cams: dict, entries: list) -> list:
    """groundContact.removeHidden (coordinator 2026-10-02, Stronghold zs_v1 houses_v36 piece 0: a house placed 9-14 m
    under the left hill, no terrain under it to anchor to): drop an environment piece the recipe names by bin, piece
    number and vertex count (the identity pin: a restage that renumbers or reshapes the pieces fails here instead of
    removing another piece), only after proving it draws 0 px at the rest camera and at every given pose. The proof
    rasters the environment alone: a build state is the environment plus building layers, and adding geometry to a
    depth-tested raster can only hide a px, never reveal one, so 0 px over the environment alone is 0 px in every
    state. Fails closed on any visible px. -> [{bin, piece, verts, faces, why}] (the stage bins are edited in place)."""
    import town_gpu_kernels as GK
    inst = {t["bin"]: int(t["instances"]) for t in (catalog.get("props") or {}).get("types", {}).values()}
    todo = []
    for e in entries:
        if not isinstance(e, dict) or set(e) != REMOVE_HIDDEN_KEYS or not str(e.get("why", "")).strip():
            fail(f"removeHidden: each entry is {sorted(REMOVE_HIDDEN_KEYS)} with a reason, got {e!r}")
        bis = [bi for bi, b in enumerate(stage.bins) if b["key"] == env_key and b["name"] == e["bin"]]
        if len(bis) != 1 or classify(e["bin"]) != "piece":
            fail(f"removeHidden: {e['bin']} is not one environment piece bin ({len(bis)} staged)")
        b = stage.bins[bis[0]]
        ps = pieces(b["name"], b["v"], b["f"], b["uv"], sc.scale, inst.get(b["name"]))
        if not 0 <= int(e["piece"]) < len(ps) or len(ps[int(e["piece"])]) != int(e["verts"]):
            fail(f"removeHidden: {e['bin']} piece {e['piece']} is not the named {e['verts']}-vertex piece "
                 f"({len(ps)} pieces; that piece has {len(ps[int(e['piece'])]) if 0 <= int(e['piece']) < len(ps) else '-'} "
                 f"vertices): the staged houses changed, re-measure before removing anything")
        inp = np.zeros(len(b["v"]), bool)
        inp[ps[int(e["piece"])]] = True
        todo.append((bis[0], np.flatnonzero(inp[b["f"]].any(1)), e))
    if not todo:
        return []
    P, _, F, _, _, _, fmap = stage.arrays([env_key])
    gidx = {bi: np.flatnonzero(fmap[:, 0] == bi) for bi, _, _ in todo}
    mark = np.zeros(len(F) + 1, np.int64)                         # 1 + entry index per face, 0 elsewhere
    for i, (bi, lf, _) in enumerate(todo):
        mark[gidx[bi][lf]] = i + 1
    rast = GK.Raster(P, F)
    seen = np.zeros(len(todo), np.int64)
    try:
        for pose, cam in {"rest": sc.cam, **cams}.items():
            _, fid = rast.render(cam)
            hit = mark[fid[fid >= 0]]
            seen += np.bincount(hit, minlength=len(todo) + 1)[1:]
    finally:
        rast.release()
    if seen.any():
        fail("removeHidden: named pieces draw px at the rest camera or a reachable pose (environment alone): "
             + json.dumps({f"{e['bin']}/{e['piece']}": int(n) for (_, _, e), n in zip(todo, seen) if n}))
    out = []
    for bi, lf, e in todo:
        stage.drop(bi, lf)
        out.append({"bin": e["bin"], "piece": int(e["piece"]), "verts": int(e["verts"]), "faces": int(len(lf)),
                    "posesChecked": 1 + len(cams), "why": e["why"]})
    return out


def anchor(gs: Scene, rest_check, T, strict: bool = True, drop: dict | None = None) -> list:
    """Ground every floating piece, in place on the stage bins, keeping every state's rest frame identical:
    first the piece itself scaled about the rest camera onto the ground (piece_scale); when that changes the rest
    frame (something nearer at rest lies on its rays), the ground under it filled to its base along the ground's own
    rest rays (ground_slide). rest_check(faces=None) -> {state: px changed against the frames before anchoring}
    (faces: filled with {bin: local faces drawn at a changed px}); a fill that changes the rest frame is undone, the
    vertices of the ground faces it brought into view are frozen and it is tried again (FILL_ROUNDS). Fails closed
    when neither keeps the rest frame, or the fill is steeper than FILL_SPIKE_DEG. A piece with no ground under
    it is left as it is (contact_gate fails on it). strict False (audit): a failure is recorded and the next piece
    tried, so one run reports every piece. drop (opt-in): {"before": the frames rest_check compares with (rebased
    in place), "rect": (TH, TW)} enables extension_drop() for EXT_DROP pieces both moves fail on."""
    moved = []

    def fail_piece(rec, msg, g):
        # ANCHOR_TOL_M is the anchoring target, CONTACT_GATE_M the acceptance: a piece neither move can ground but
        # already within the gate is left as it is and recorded (Dungeon props_v1 / Inferno zs_v1 / Factory gc_v1,
        # 2026-10-01: near-field pebbles at 0.09-0.14 m stopped builds that contact_gate passes). Over the gate: fail
        if g <= CONTACT_GATE_M:
            rec.update({"how": "withinGate", "why": msg})
            moved.append(rec)
            return
        if strict:
            fail(msg)
        rec.update({"how": "failed", "why": msg})
        moved.append(rec)
    for r in gs.records():
        g = r["gapM"]
        if not np.isfinite(g) or g <= ANCHOR_TOL_M:
            continue
        b = gs.stage.bins[r["bin"]]
        idx = r["idx"]
        rec = {"name": r["name"], "piece": r["piece"], "verts": r["verts"], "gapBeforeM": round(g, 3)}
        s = piece_scale(gs, b, idx)
        if s is not None:
            v0 = b["v"]
            b["v"] = v0.copy()
            b["v"][idx] *= s
            ch = rest_check()
            if not any(ch.values()):
                b["dirty"] = True
                rec.update({"how": "piece", "scale": round(s, 6), "gapAfterM": round(gs.gap_of(b["v"], idx), 3)})
                moved.append(rec)
                continue
            rec["pieceSlideRestPx"] = {k: v for k, v in ch.items() if v}
            b["v"] = v0
        s2, why = None, "cannot reach its base"
        for erode in (False, True):         # the plain fill first; then only fully hidden one-rings
            frozen, edit, ch = {}, None, {}
            for _ in range(FILL_ROUNDS):
                edit = ground_slide(gs, b, idx, T, frozen, erode)
                if edit is None:
                    break
                faces: dict = {}
                ch = rest_check(faces)
                if not any(ch.values()):
                    break
                why = f"changes the rest frame {({k: v for k, v in ch.items() if v})}"
                grew = False
                for gi in edit["old"]:
                    lf = sorted(faces.get(gi, ()))
                    if not lf:
                        continue
                    m = frozen.setdefault(gi, np.zeros(len(gs.stage.bins[gi]["v"]), bool))
                    n0 = int(m.sum())
                    m[gs.stage.bins[gi]["f"][lf].ravel()] = True
                    grew |= int(m.sum()) > n0
                undo_ground(gs, edit)
                edit = None
                if not grew:
                    break
            if edit is not None and gs.gap_of(b["v"], idx) > ANCHOR_TOL_M:
                # the fill keeps the rest frame but leaves the base short of it (the base stands over the seam
                # between two ground sheets): the piece slide again, now onto the filled ground
                s2 = piece_scale(gs, b, idx)
                ok = False
                if s2 is not None:
                    v0 = b["v"]
                    b["v"] = v0.copy()
                    b["v"][idx] *= s2
                    ok = not any(rest_check().values())
                    if not ok:
                        b["v"] = v0
                if ok:
                    b["dirty"] = True
                else:
                    why = ("reaches its base only by a piece slide that changes the rest frame" if s2 is not None
                           else "leaves its base short of the ground")
                    s2 = None
                    undo_ground(gs, edit)
                    edit = None
            if edit is not None:
                break
        if edit is None and drop is not None and EXT_DROP.match(r["name"]):
            res, dwhy = extension_drop(gs, b, idx, g, T, drop)
            if res is not None:
                rec.update(res)
                moved.append(rec)
                continue
            why += f"; extensionDrop: {dwhy}"
        if edit is None:
            fail_piece(rec, f"{r['name']} piece {r['piece']} ({r['verts']} verts, gap {g:.2f} m): the piece slide "
                            f"{'changes the rest frame' if s is not None else 'meets no ground'} and the ground "
                            f"fill {why}", g)
            continue
        slope = max_slope_deg(gs, edit)
        if slope > FILL_SPIKE_DEG:
            undo_ground(gs, edit)
            fail_piece(rec, f"{r['name']} piece {r['piece']} ({r['verts']} verts, gap {g:.2f} m): the ground fill "
                            f"rises at {slope:.1f} deg (> {FILL_SPIKE_DEG})", g)
            continue
        rec.update({"how": "ground" if s2 is None else "ground+piece",
                    "scale": None if s2 is None else round(s2, 6), "eroded": erode, "groundVertsMoved": edit["vertsMoved"], "frozenVerts":
                    int(sum(m.sum() for m in frozen.values())), "maxSlopeDeg": round(slope, 1),
                    "gapAfterM": round(gs.gap_of(b["v"], idx), 3)})
        moved.append(rec)
    return moved


def contact_gate(gs: Scene) -> dict:
    """Per piece bin: pieces, floating (> CONTACT_GATE_M), unsupported (no ground under it at any height), buried
    (wholly under a ground surface: no surface within 0.5 m above its lowest points, one higher above its highest
    point; a buried piece is under the terrain at every pose, so it does not fail the gate), embedded (ground over its
    24 lowest points stands between its lowest and highest point: planted in the ground, not failing); pass when
    floating and unsupported are zero."""
    by: dict = {}
    for r in gs.records():
        e = by.setdefault(r["name"], {"pieces": 0, "floating": 0, "unsupported": 0, "buried": 0, "worst": []})
        e["pieces"] += 1
        if not np.isfinite(r["gapM"]):
            b = gs.stage.bins[r["bin"]]
            Q = gs.to_world(b["v"][r["idx"]])
            top = Q[np.argmax(Q @ UP)][None]
            lift = top + 1e4 * np.asarray(UP)[None]
            g_top = gs.ground.gap(lift)[0]                    # height of the highest ground over the piece's top
            if np.isfinite(g_top) and (1e4 - g_top) > 0:      # that ground is above the piece's highest point
                e["buried"] += 1
                continue
            # embedded: gap() only counts a surface up to 0.5 m above a point, so a piece planted deeper than that in
            # the ground read as inf. Ground over its low points that stands between its lowest and its highest point
            # holds it: it stands in the ground, it does not float (Cove ssr_dfix 2026-10-01: agave / reeds /
            # Near_rocks_0 planted 0.05-2.5 m deep counted unsupported)
            hs = Q @ UP
            low = Q[np.argsort(hs)[:24]]
            g_low = gs.ground.gap(low + 1e4 * np.asarray(UP)[None])
            surf = (low @ UP + 1e4) - g_low                   # height of the highest ground over each low point
            fin = np.isfinite(surf)
            if fin.any() and (surf[fin] > hs.min()).any() and (surf[fin] < hs.max()).all():
                e["embedded"] = e.get("embedded", 0) + 1
            else:
                e["unsupported"] += 1
        elif r["gapM"] > CONTACT_GATE_M:
            e["floating"] += 1
            e["worst"].append((round(r["gapM"], 3), r["piece"], r["verts"]))
    for e in by.values():
        e["worst"] = sorted(e["worst"], reverse=True)[:8]
    ok = all(e["floating"] == 0 and e["unsupported"] == 0 for e in by.values())
    return {"schema": SCHEMA, "gateM": CONTACT_GATE_M, "pass": ok, "byBin": by}


def rest_identity(gs: "Scene", before: dict | None, faces: dict | None = None) -> dict:
    """{state: px whose rest face differs from before (state -> fid image)} over gs.rasters' build states; with before
    None, returns the images. faces (optional): filled with {bin: set of local faces now drawn at a changed px}."""
    out = {}
    for s in gs.rasters.state_keys:
        _, fid, fmap = gs.rasters.state(s)
        if before is None:
            out[s] = fid
            continue
        ch = fid != before[s]
        out[s] = int(ch.sum())
        if faces is not None and out[s]:
            for f in np.unique(fid[ch & (fid >= 0)]):
                bi, lf = fmap[f]
                faces.setdefault(int(bi), set()).add(int(lf))
    return out


def _stage(tree_states: bool = True):
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import town_t2_streak_map as SM
    import town_full3d_recipe as R
    import town_full3d_build_states as BS
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    states = BS.enumerate_states(SC.FP, SC.layer_map()) if tree_states else SC.FP.STATES
    state_keys = {s: [S.ENV_KEY] + [S.PREFIX + l for l in ls] for s, ls in states.items()}
    missing = sorted({k for ks in state_keys.values() for k in ks if k not in rows})
    if missing:
        fail(f"build states name prefabs the candidate does not stage: {missing}")
    keys = sorted({k for ks in state_keys.values() for k in ks})
    return S, sc, R.Stage(S, SM, sc, rows, keys), state_keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="read-only: the gate on the staged candidate, and what anchoring would do")
    a.add_argument("--out", required=True)
    a.add_argument("--try-anchor", action="store_true", help="also anchor in memory and check the rest frame")
    a.add_argument("--extension-drop", action="store_true", help="with --try-anchor: enable extensionDrop")
    a.add_argument("--device", choices=["cpu", "cuda"], default=None,
                   help="cpu: the reference; cuda (default, TOWN_FULL3D_DEVICE): the same answer on the GPU")
    args = ap.parse_args()
    import time
    t0 = time.time()
    S, sc, stage, state_keys = _stage()
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    gs = Scene(sc, stage, S.ENV_KEY, cat, args.device, state_keys if args.try_anchor else None)
    rep = {"faction": os.environ.get("TOWN_FULL3D_FACTION"), "candidate": S.CANDIDATE, "gate": contact_gate(gs)}
    if args.try_anchor:
        import stronghold_full3d_terrain as T
        import stronghold_full3d_common as SC
        before = rest_identity(gs, None)
        drop = {"before": before, "rect": (SC.TH, SC.TW)} if args.extension_drop else None
        try:
            moved = anchor(gs, lambda faces=None: rest_identity(gs, before, faces), T, strict=False, drop=drop)
            rep["anchor"] = {"moved": len(moved), "pieces": moved}
        except SystemExit as e:
            rep["anchor"] = {"error": str(e)}
        else:
            rep["anchor"]["restPxChanged"] = rest_identity(gs, before)
            gs.rasters.release()
            rep["gateAfterAnchor"] = contact_gate(Scene(sc, stage, S.ENV_KEY, cat, args.device))
    rep["device"], rep["seconds"] = gs.device, round(time.time() - t0, 1)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    g = rep["gate"]
    print(json.dumps({"candidate": S.CANDIDATE, "pass": g["pass"],
                      "byBin": {k: {x: v[x] for x in ("pieces", "floating", "unsupported")} for k, v in g["byBin"].items()}}))
    if "anchor" in rep:
        print("ANCHOR", json.dumps({k: v for k, v in rep["anchor"].items() if k != "pieces"}))
        if "gateAfterAnchor" in rep:
            print("AFTER", rep["gateAfterAnchor"]["pass"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
