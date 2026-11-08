"""Haiku anim bench: mesh-repair and rig ops, replayed over a pristine snapshot of the unit (no Blender, numpy only).

The bench keeps these ops ("mops") in its stack next to the pose edits. Every change to the mop list rebuilds the rig
state from the pristine scene by replaying the list in order (a few ms on a 10k-vertex unit), writes it into the
Unit's Scene in place (P, N, J, W, morphs, nodes, parent, order, joints, ibm, rest, channels), and the GL side
re-uploads its buffers. Pose edits reference bones by name, so they survive a replay.

Weight repairs (expressible as patch-lane ops, see EXPRESSIBLE):
  smooth  {"fix": "smooth", "bones": [A, B], "ring": n, "center": xyz, "radius": r}   LOCAL diffusion of the A/B
          split around the spot over weld groups (UV-seam copies keep identical weights); every other bone's weight
          and the A+B share stay. Without "center": patch_glb.op_diffuse_weights (whole-bone, the lane's own op).
          The local form needs a region parameter on diffuseWeights to be a lane op.
  blend   {"fix": "blend", "from": A, "to": B, "amount": a, "center": xyz, "radius": r}   patch_glb.op_move_weights:
          move `amount` of A's weight onto B inside a box of half size r around `center` (bind space), ramped
Rest-shape / Corrective Smooth repairs (not expressible by a glbPatch op today):
  relax   {"fix": "relax", "center": xyz, "radius": r, "strength": s}   Taubin (lambda/mu) relax of the rest shape
          over weld groups, falloff to 0 at r; normals recomputed in the region
  nocs    {"fix": "nocs", "bones": [A]}   correctiveSmooth.excludeBones rule (bake_cs): the baked CS morph offsets
          are scaled by 1 - the vertex's weight on those bones
Rig ops (new joints get constant 2-key STEP translation/rotation/scale channels in every clip, like every other
bone of a def_retarget GLB, so later pose edits and the lane's `regrid` work on them):
  split    {"do": "split", "bone": B, "at": f, "toward": C?, "name": N}  new joint N at fraction f along B (toward
           its child C, or toward the tip of B's skin for a leaf bone); C is re-parented under N; B's weights are
           split along the segment with a smoothstep band, so the rest pose is unchanged exactly
  add      {"do": "add", "parent": B, "toward": dir, "size": s, "name": N}  new child joint N at the base of the
           `size` fraction of B's skin furthest along dir (back/front/up/down/left/right, body frame), weights grown
           from those vertices with a smoothstep band (tail fan, primary feathers, a talon...)
  pivot    {"do": "pivot", "bone": B, "move": [dx, dy, dz]}  move B's rest pivot (mesh space); B's IBM, its rest/keyed
           translation and its children's are re-bound so the rest pose is unchanged; only the pivot moves
  reparent {"do": "reparent", "bone": B, "parent": Q}  keeps B's rest global; its local channels are re-baked on each
           clip's key grid from the old globals (LINEAR)
"""
from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import numpy as np

import patch_glb as PG  # noqa: E402  (anim_core puts tools/homm3_glb_patch on sys.path)
from gltf_scene import _quat_to_mat, sample_channel  # noqa: E402

FIXES = ("smooth", "blend", "relax", "nocs", "sculpt", "rebind", "paint", "corrective")
SCULPT_MODES = ("move", "scale", "inflate", "deflate", "smooth", "flatten")
MAX_CORRECTIVES = 12
RIG_DOS = ("split", "add", "pivot", "reparent")
DIRS = {"back": (0, 0, -1.0), "front": (0, 0, 1.0), "up": (0, 1.0, 0), "down": (0, -1.0, 0),
        "left": (1.0, 0, 0), "right": (-1.0, 0, 0)}
EXPRESSIBLE = {"smooth": "local form: none (diffuseWeights has no region; whole-bone form = diffuseWeights)",
               "blend": "glbPatch moveWeights {from, to, region (axis ramps), keep}",
               "relax": "none (needs a new rest-shape op, e.g. restShape {table of vertex deltas} + CS re-bake)",
               "nocs": "none in glbPatch (build-time correctiveSmooth.excludeBones; cs_rekey_glb reads the list)",
               "split": "none (needs addBones)", "add": "none (needs addBones)", "pivot": "none (needs rebind/pivot op)",
               "reparent": "none (needs reparent op)",
               "sculpt": "none (needs a new rest-shape op, e.g. restShape {table of vertex deltas} + CS re-bake)",
               "rebind": "none (needs a region weight op, e.g. setWeights {vertex table})",
               "paint": "none (needs a region weight op, e.g. setWeights {vertex table})",
               "corrective": "none (bench-only joint-keyed shape; not exported)"}


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, np.float64) - a) / max(b - a, 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def mat_to_quat(R):
    """(..., 3, 3) rotation -> (..., 4) xyzw (Shepperd)."""
    R = np.asarray(R, np.float64)
    sh = R.shape[:-2]
    R = R.reshape(-1, 3, 3)
    out = np.zeros((len(R), 4))
    for i, m in enumerate(R):
        tr = m[0, 0] + m[1, 1] + m[2, 2]
        if tr > 0:
            s = np.sqrt(tr + 1.0) * 2
            q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
            q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
        elif m[1, 1] > m[2, 2]:
            s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
            q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
        else:
            s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
            q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
        q = np.asarray(q)
        out[i] = q / np.linalg.norm(q)
    return out.reshape(*sh, 4)


def trs(t, r, s):
    M = np.eye(4)
    M[:3, :3] = _quat_to_mat(np.asarray(r, np.float64)) * np.asarray(s, np.float64)[None, :]
    M[:3, 3] = t
    return M


def clean_name(name: str, fallback: str, taken) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "", str(name or ""))[:32] or fallback
    if not n[0].isalpha():
        n = "J" + n
    base, k = n, 2
    while n in taken:
        n, k = f"{base}{k}", k + 1
    return n


class RigEditor:
    def __init__(self, unit):
        self.u = unit
        s = unit.scene
        self.p = SimpleNamespace(P=s.P.copy(), N=s.N.copy(), J=s.J.copy(), W=s.W.copy(), morphs=s.morphs,
                                 nodes=copy.deepcopy(s.nodes), joints=list(s.joints), ibm=s.ibm.copy(),
                                 rest=[tuple(x.copy() for x in r) for r in s.rest],
                                 channels={c: list(ch) for c, ch in s.channels.items()},
                                 dw=np.asarray(s.default_weights).copy())
        unit.M0 = s.morphs.shape[0]
        s.correctives = []
        # position welds (every vertex at one rest position moves as one: seams never open) and the surface graph
        # over them (edge lengths at rest) for geodesic regions: a region grows along the surface from its seed, so it
        # never jumps to a part that only touches it (a club resting on a thigh, a wing on the body)
        from scipy.sparse import coo_matrix
        _, pg = np.unique(np.round(s.P, 5), axis=0, return_inverse=True)
        self.pgrp = pg.ravel()
        self.npg = int(self.pgrp.max()) + 1
        Fp = self.pgrp[s.F]
        Ep = np.unique(np.sort(np.concatenate([Fp[:, [0, 1]], Fp[:, [1, 2]], Fp[:, [2, 0]]]), 1), axis=0)
        Ep = Ep[Ep[:, 0] != Ep[:, 1]]
        Pg = np.zeros((self.npg, 3)); Pg[self.pgrp] = s.P
        L = np.maximum(np.linalg.norm(Pg[Ep[:, 0]] - Pg[Ep[:, 1]], axis=1), 1e-9)
        self.pedges = Ep
        self.graph = coo_matrix((np.r_[L, L], (np.r_[Ep[:, 0], Ep[:, 1]], np.r_[Ep[:, 1], Ep[:, 0]])),
                                shape=(self.npg, self.npg)).tocsr()
        self.n_nodes0, self.n_joints0 = len(s.nodes), len(s.joints)
        # weld groups (UV-seam copies: one rest position AND the same weights, as bake_cs groups them; coincident
        # vertices of different parts, e.g. a wing resting on the body, stay apart) and their adjacency
        D0 = np.zeros((len(s.P), len(s.joints)))
        np.add.at(D0, (np.repeat(np.arange(len(s.P)), s.J.shape[1]), s.J.ravel()), s.W.ravel())
        _, grp = np.unique(np.c_[np.round(s.P, 5), np.round(D0, 2)], axis=0, return_inverse=True)
        self.grp = grp.ravel()
        self.ng = int(self.grp.max()) + 1
        F = s.F
        E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        ge = np.unique(np.sort(self.grp[E], 1), axis=0)
        self.gedges = ge[ge[:, 0] != ge[:, 1]]
        self.ops: list[dict] = []
        self.version = 0
        self.reports: list[dict] = []
        self.new_joints: list[str] = []

    # ------------------------------------------------------------ replay
    def apply(self, ops: list[dict]) -> list[dict]:
        """Reset the scene to the pristine snapshot and replay `ops`. Raises ValueError (scene left at the replay of
        the ops before the failing one... callers re-apply the previous list on error)."""
        s, p = self.u.scene, self.p
        s.P, s.N, s.J, s.W, s.morphs = p.P.copy(), p.N.copy(), p.J.copy(), p.W.copy(), p.morphs
        s.default_weights, s.correctives = p.dw.copy(), []
        s.nodes = copy.deepcopy(p.nodes)
        s.joints, s.ibm = list(p.joints), p.ibm.copy()
        s.rest = [tuple(x.copy() for x in r) for r in p.rest]
        s.channels = {c: list(ch) for c, ch in p.channels.items()}
        self._relink()
        reps = []
        for op in ops:
            kind = op.get("fix") or op.get("do")
            fn = getattr(self, f"_op_{kind}", None)
            if fn is None:
                raise ValueError(f"unknown mesh/rig op {kind!r}")
            reps.append(fn(op))
            self._relink()
        self.ops = [dict(o) for o in ops]
        self.reports = reps
        self.new_joints = [s.nodes[j].get("name") for j in s.joints[self.n_joints0:]]
        self.version += 1
        self.u.refresh()
        return reps

    def _relink(self):
        s = self.u.scene
        s.parent = {c: i for i, n in enumerate(s.nodes) for c in n.get("children", [])}
        order, stack = [], [i for i in range(len(s.nodes)) if i not in s.parent][::-1]
        while stack:
            i = stack.pop(); order.append(i); stack += s.nodes[i].get("children", [])[::-1]
        s.order = order

    # ------------------------------------------------------------ helpers
    def names(self):
        return [n.get("name") for n in self.u.scene.nodes]

    def jidx(self, bone: str) -> int:
        s = self.u.scene
        nm = self.names()
        if bone not in nm or nm.index(bone) not in s.joints:
            raise ValueError(f"unknown bone {bone!r}")
        return s.joints.index(nm.index(bone))

    def dense(self) -> np.ndarray:
        s = self.u.scene
        D = np.zeros((len(s.P), len(s.joints)))
        np.add.at(D, (np.repeat(np.arange(len(s.P)), s.J.shape[1]), s.J.ravel()), s.W.ravel())
        return D

    def set_dense(self, D: np.ndarray):
        s = self.u.scene
        k = s.J.shape[1]
        top = np.argsort(-D, 1)[:, :k]
        w = np.take_along_axis(D, top, 1)
        w[w < 1e-6] = 0
        w /= np.maximum(w.sum(1, keepdims=True), 1e-12)
        s.J = np.where(w > 0, top, 0).astype(np.int64)
        s.W = w

    def rest_globals(self) -> np.ndarray:
        s = self.u.scene
        G = np.zeros((len(s.nodes), 4, 4))
        for i in s.order:
            L = trs(*s.rest[i])
            pa = s.parent.get(i)
            G[i] = L if pa is None else G[pa] @ L
        return G

    def bind(self, j: int) -> np.ndarray:
        return np.linalg.inv(self.u.scene.ibm[j])

    def _add_joint(self, parent_node: int, name: str, t_local) -> int:
        """Append a joint node (identity rotation, unit scale) under parent_node, keyed as constants in every clip."""
        s = self.u.scene
        name = clean_name(name, "NewJoint", set(self.names()))
        ni = len(s.nodes)
        s.nodes.append({"name": name, "translation": [float(x) for x in t_local]})
        s.nodes[parent_node].setdefault("children", []).append(ni)
        s.rest.append((np.asarray(t_local, np.float64), np.array([0, 0, 0, 1.0]), np.ones(3)))
        pj = s.joints.index(parent_node)
        s.joints.append(ni)
        Tl = np.eye(4); Tl[:3, 3] = t_local
        s.ibm = np.concatenate([s.ibm, np.linalg.inv(self.bind(pj) @ Tl)[None]])
        for clip, chans in s.channels.items():
            c = self.u.clips.get(clip)
            st, en = (c["start"], c["end"]) if c else (min(ch[2][0] for ch in chans), max(ch[2][-1] for ch in chans))
            ti = np.array([st, en], np.float64)
            chans.append(("translation", ni, ti, np.tile(np.asarray(t_local, np.float64), (2, 1)), "STEP"))
            chans.append(("rotation", ni, ti, np.tile([0, 0, 0, 1.0], (2, 1)), "STEP"))
            chans.append(("scale", ni, ti, np.ones((2, 3)), "STEP"))
        return ni

    def _offset_translation(self, node: int, d_local):
        """Add a constant to the node's rest translation and every translation key."""
        s = self.u.scene
        t, r, sc = s.rest[node]
        s.rest[node] = (t + d_local, r, sc)
        s.nodes[node]["translation"] = [float(x) for x in t + d_local]
        for clip, chans in s.channels.items():
            for k, (path, nd, ti, vo, it) in enumerate(chans):
                if path == "translation" and nd == node:
                    chans[k] = (path, nd, ti, (vo.reshape(-1, 3) + d_local).reshape(vo.shape), it)

    def _split_weights(self, jb: int, jx: int, s_param: np.ndarray, lo: float, hi: float):
        D = self.dense()
        if D.shape[1] <= jx:
            D = np.c_[D, np.zeros((len(D), jx + 1 - D.shape[1]))]
        h = smoothstep(lo, hi, s_param)
        moved = D[:, jb] * h
        D[:, jx] += moved
        D[:, jb] -= moved
        self.set_dense(D)
        return int((moved > 1e-3).sum())

    # ------------------------------------------------------------ weight repairs (the lane's own code)
    def _body(self):
        s = self.u.scene
        return SimpleNamespace(jnames=[s.nodes[j].get("name") for j in s.joints], V=s.P, F=s.F)

    def _op_smooth(self, op):
        """Local weight diffusion across a joint boundary: inside `radius` of `center` (falloff), the vertex's share on
        `bones` is re-split by Laplacian averaging of those bones' columns over weld-group neighbours (`ring` x 3
        iterations, alpha 0.5); the share itself and every other bone's weight stay as they are. Without a centre it
        is the lane's own whole-bone diffuseWeights (patch_glb.op_diffuse_weights)."""
        s = self.u.scene
        bones = [str(b) for b in op["bones"]][:3]
        js = [self.jidx(b) for b in bones]
        it = int(np.clip(int(op.get("ring", 2)), 1, 6)) * 3
        if op.get("center") is None:
            try:
                J2, W2, rep = PG.op_diffuse_weights(self._body(), {"bones": bones, "iterations": it, "alpha": 0.5}, s.J, s.W)
            except SystemExit as e:
                raise ValueError(str(e)) from None
            s.J, s.W = J2.astype(np.int64), W2
            return rep
        D = self.dense()
        cnt = np.bincount(self.grp, minlength=self.ng)[:, None]
        Gd = np.zeros((self.ng, D.shape[1])); np.add.at(Gd, self.grp, D); Gd /= cnt
        Gp = np.zeros((self.ng, 3)); np.add.at(Gp, self.grp, s.P); Gp /= cnt
        r = float(op["radius"])
        fall = 1 - smoothstep(0.5 * r, r, np.linalg.norm(Gp - np.asarray(op["center"], np.float64), axis=1))
        share = Gd[:, js].sum(1)
        act = (fall > 0) & (share > 0.01)
        if act.sum() < 3:
            raise ValueError("smooth: those bones carry no weight near that spot")
        F = Gd[:, js] / np.maximum(share, 1e-12)[:, None]          # fractions of the share
        ge = self.gedges
        deg = np.bincount(ge.ravel(), minlength=self.ng)[:, None]
        w_nb = share[ge]                                            # neighbours without the bones count as no vote
        F0 = F.copy()
        for _ in range(it):
            S = np.zeros_like(F); C = np.zeros((self.ng, 1))
            np.add.at(S, ge[:, 0], F[ge[:, 1]] * (w_nb[:, 1:2] > 0.01)); np.add.at(C, ge[:, 0], (w_nb[:, 1:2] > 0.01) * 1.0)
            np.add.at(S, ge[:, 1], F[ge[:, 0]] * (w_nb[:, 0:1] > 0.01)); np.add.at(C, ge[:, 1], (w_nb[:, 0:1] > 0.01) * 1.0)
            M = np.where(C > 0, S / np.maximum(C, 1), F)
            F = np.where(act[:, None], F + (0.5 * fall)[:, None] * (M - F), F)
        Gd[:, js] = F * share[:, None]
        av = act[self.grp]
        D[av] = Gd[self.grp][av]
        self.set_dense(D)
        moved = float(np.abs(F - F0).sum(1).max()) / 2
        return {"op": "smooth", "bones": bones, "vertices": int(act[self.grp].sum()), "maxShareMoved": round(moved, 4),
                "local": True}

    def blend_region(self, center, radius):
        cb = PG.blender_axes(np.asarray(center, np.float64)[None])[0]
        ramp = 0.6 * radius
        reg = []
        for k, ax in enumerate("xyz"):
            reg.append({"axis": ax, "above": float(cb[k] - radius - ramp), "ramp": float(ramp)})
            reg.append({"axis": ax, "below": float(cb[k] + radius + ramp), "ramp": float(ramp)})
        return reg

    def _op_blend(self, op):
        s = self.u.scene
        self.jidx(op["from"]); self.jidx(op["to"])
        amount = float(np.clip(float(op.get("amount", 0.5)), 0.05, 1.0))
        lane = {"op": "moveWeights", "from": [op["from"]], "to": op["to"],
                "region": self.blend_region(op["center"], float(op["radius"])), "keep": 1.0 - amount}
        try:
            J2, W2, rep = PG.op_move_weights(self._body(), lane, s.J, s.W)
        except SystemExit as e:
            raise ValueError(str(e)) from None
        s.J, s.W = J2.astype(np.int64), W2
        rep["laneOp"] = lane
        return rep

    # ------------------------------------------------------------ rest-shape / CS repairs
    def _op_relax(self, op):
        s = self.u.scene
        c = np.asarray(op["center"], np.float64)
        r = float(op["radius"])
        lam = float(np.clip(float(op.get("strength", 0.5)), 0.1, 1.0)) * 0.5
        G = np.zeros((self.ng, 3)); cnt = np.bincount(self.grp, minlength=self.ng)[:, None]
        np.add.at(G, self.grp, s.P); G /= cnt
        fall = 1 - smoothstep(0.5 * r, r, np.linalg.norm(G - c, axis=1))
        if (fall > 0).sum() < 3:
            raise ValueError("relax: no vertices near that spot")
        ge = self.gedges
        deg = np.bincount(ge.ravel(), minlength=self.ng)[:, None]
        G0 = G.copy()
        for _ in range(4):
            for f in (lam, -lam * 1.06):        # Taubin: shrink-free
                S = np.zeros_like(G); np.add.at(S, ge[:, 0], G[ge[:, 1]]); np.add.at(S, ge[:, 1], G[ge[:, 0]])
                M = np.where(deg > 0, S / np.maximum(deg, 1), G)
                G = G + (f * fall)[:, None] * (M - G)
        d = G - G0
        s.P = s.P + d[self.grp]
        moved = np.flatnonzero(np.linalg.norm(d, axis=1)[self.grp] > 1e-9)
        # normals in the moved region
        F = s.F
        fn = np.cross(s.P[F[:, 1]] - s.P[F[:, 0]], s.P[F[:, 2]] - s.P[F[:, 0]])
        Nn = np.zeros_like(s.P)
        for k in range(3):
            np.add.at(Nn, F[:, k], fn)
        Ng = np.zeros((self.ng, 3)); np.add.at(Ng, self.grp, Nn)
        Nn = Ng[self.grp]
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
        N2 = s.N.copy()
        N2[moved] = Nn[moved]
        s.N = N2
        return {"op": "relax", "vertices": int(len(moved)), "maxMove": round(float(np.linalg.norm(d, axis=1).max()), 5)}

    def _op_nocs(self, op):
        s = self.u.scene
        bones = [str(b) for b in op["bones"]][:4]
        js = [self.jidx(b) for b in bones]
        if not s.morphs.shape[0]:
            raise ValueError("nocs: this unit has no baked Corrective Smooth morphs")
        D = self.dense()
        k = 1.0 - np.clip(D[:, js].sum(1), 0, 1)
        s.morphs = (s.morphs * k[None, :, None].astype(np.float32)).astype(np.float32)
        return {"op": "nocs", "bones": bones, "vertices": int((k < 0.999).sum())}

    # ------------------------------------------------------------ region tools (round 3): sculpt, rebind, paint, corrective
    def region(self, center, radius: float) -> np.ndarray:
        """Per-vertex falloff (1 inside 0.6 r, smooth to 0 at r) of the surface region around the vertex nearest
        `center`: GEODESIC distance along the mesh (position-welded graph), so it follows the part it starts on."""
        from scipy.sparse.csgraph import dijkstra
        s = self.u.scene
        c = np.asarray(center, np.float64)
        seed = int(self.pgrp[int(np.argmin(np.linalg.norm(s.P - c, axis=1)))])
        r = float(radius)
        d = dijkstra(self.graph, directed=False, indices=seed, limit=r)
        fall_g = np.where(np.isfinite(d), 1 - smoothstep(0.6 * r, r, np.where(np.isfinite(d), d, r)), 0.0)
        return fall_g[self.pgrp]

    def _renormal(self, moved: np.ndarray):
        s = self.u.scene
        F = s.F
        fn = np.cross(s.P[F[:, 1]] - s.P[F[:, 0]], s.P[F[:, 2]] - s.P[F[:, 0]])
        Nn = np.zeros_like(s.P)
        for k in range(3):
            np.add.at(Nn, F[:, k], fn)
        Ng = np.zeros((self.npg, 3)); np.add.at(Ng, self.pgrp, Nn)
        Nn = Ng[self.pgrp]
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
        N2 = s.N.copy()
        N2[moved] = Nn[moved]
        s.N = N2

    def sculpt_positions(self, op) -> tuple[np.ndarray, np.ndarray]:
        """The sculpted rest positions (not written): soft selection = self.region; modes move | scale | inflate |
        deflate | smooth | flatten; amounts in body heights (move/inflate) or fractions (scale/smooth/flatten)."""
        s, H = self.u.scene, self.u.H
        mode = str(op.get("mode", "smooth"))
        if mode not in SCULPT_MODES:
            raise ValueError(f"sculpt mode must be one of {list(SCULPT_MODES)}")
        fall = self.region(op["center"], float(op["radius"]))
        if (fall > 0).sum() < 3:
            raise ValueError("sculpt: no surface there")
        a = float(op.get("amount", 0.5))
        Gp = np.zeros((self.npg, 3)); Gp[self.pgrp] = s.P
        fg = np.zeros(self.npg); fg[self.pgrp] = fall
        Ng = np.zeros((self.npg, 3)); np.add.at(Ng, self.pgrp, s.N)
        Ng /= np.maximum(np.linalg.norm(Ng, axis=1, keepdims=True), 1e-12)
        w = fg[:, None]
        if mode == "move":
            d = np.asarray(op.get("dir", [0, 1, 0]), np.float64)[:3]
            d = d / max(np.linalg.norm(d), 1e-9)
            G = Gp + w * np.clip(a, -0.3, 0.3) * H * d
        elif mode == "scale":
            c = (Gp * w).sum(0) / max(w.sum(), 1e-9)
            G = c + (Gp - c) * (1 + np.clip(a, -0.8, 1.5) * w)
        elif mode in ("inflate", "deflate"):
            k = abs(np.clip(a, -0.15, 0.15)) * (1 if mode == "inflate" else -1) * (1 if a >= 0 else -1)
            G = Gp + w * k * H * Ng
        elif mode == "smooth":
            G = Gp.copy()
            ge = self.pedges
            deg = np.bincount(ge.ravel(), minlength=self.npg)[:, None]
            for _ in range(int(np.clip(round(6 * max(a, 0.1)), 1, 12))):
                S = np.zeros_like(G); np.add.at(S, ge[:, 0], G[ge[:, 1]]); np.add.at(S, ge[:, 1], G[ge[:, 0]])
                M = np.where(deg > 0, S / np.maximum(deg, 1), G)
                G = G + 0.5 * w * (M - G)
        else:  # flatten
            c = (Gp * w).sum(0) / max(w.sum(), 1e-9)
            n = (Ng * w).sum(0)
            n /= max(np.linalg.norm(n), 1e-9)
            G = Gp - np.clip(a, 0, 1) * w * (((Gp - c) @ n)[:, None] * n)
        P = G[self.pgrp]
        return P, np.flatnonzero(fall > 0)

    def _op_sculpt(self, op):
        s = self.u.scene
        P, moved = self.sculpt_positions(op)
        mx = float(np.linalg.norm(P - s.P, axis=1).max())
        s.P = P
        self._renormal(moved)
        return {"op": "sculpt", "mode": op.get("mode"), "vertices": int(len(moved)), "maxMoveH": round(mx / self.u.H, 4)}

    def _op_paint(self, op):
        """Weight painting toward one bone over a geodesic soft region: amount > 0 pulls the skin to `bone` (1 = all
        of it at the centre), < 0 pushes it off `bone` onto the vertex's other bones; the rest re-normalise."""
        s = self.u.scene
        jb = self.jidx(op["bone"])
        fall = self.region(op["center"], float(op["radius"]))
        if op.get("hard"):
            fall = (fall > 0.02).astype(np.float64) * np.clip(fall * 4, 0, 1)
        a = float(np.clip(float(op.get("amount", 0.5)), -1, 1))
        D = self.dense()
        old = D[:, jb].copy()
        if a >= 0:
            new = old + a * fall * (1 - old)
        else:
            new = old * (1 + a * fall)
        rest = 1 - old
        k = np.where(rest > 1e-9, (1 - new) / np.maximum(rest, 1e-9), 0.0)
        D *= k[:, None]
        D[:, jb] = np.where(rest > 1e-9, new, old)
        self.set_dense(D)
        n = int((np.abs(D[:, jb] - old) > 1e-3).sum())
        if n == 0:
            raise ValueError("paint: nothing changed there")
        return {"op": "rebind" if op.get("hard") else "paint", "bone": op["bone"], "vertices": n}

    def _op_rebind(self, op):
        """Bind a piece of the surface (geodesic region from the seed) rigidly to one joint."""
        return self._op_paint(dict(op, amount=1.0, hard=True))

    def _op_corrective(self, op):
        """A corrective shape keyed to one joint's angle (pose-space): the sculpt's rest-space delta becomes a morph
        whose weight is 1 when the joint's local rotation is at the reference pose and fades to 0 toward its bind
        rotation (Unit.pose computes it per frame)."""
        s = self.u.scene
        if len(s.correctives) >= MAX_CORRECTIVES:
            raise ValueError(f"at most {MAX_CORRECTIVES} corrective shapes")
        jb = self.jidx(op["bone"])
        node = s.joints[jb]
        P, moved = self.sculpt_positions(op)
        d = (P - s.P).astype(np.float32)
        if not np.abs(d).max() > 1e-7:
            raise ValueError("corrective: that sculpt does not change anything")
        qref = np.asarray(op["qref"], np.float64)
        qrest = np.asarray(s.rest[node][1], np.float64)
        span = float(np.degrees(2 * np.arccos(np.clip(abs(qref @ qrest), 0, 1))))
        s.morphs = np.concatenate([s.morphs, d[None]], 0)
        s.default_weights = np.r_[s.default_weights, 0.0]
        s.correctives.append({"node": node, "qref": qref, "qrest": qrest, "m": s.morphs.shape[0] - 1,
                              "span": max(span, 8.0)})
        return {"op": "corrective", "bone": op["bone"], "vertices": int(len(moved)), "spanDeg": round(span, 1)}

    # ------------------------------------------------------------ rig ops
    def _op_split(self, op):
        s = self.u.scene
        jb = self.jidx(op["bone"])
        nb = s.joints[jb]
        f = float(np.clip(float(op.get("at", 0.5)), 0.15, 0.85))
        kids = [c for c in s.nodes[nb].get("children", []) if c in s.joints]
        nm = self.names()
        child = None
        if op.get("toward"):
            if op["toward"] not in nm or nm.index(op["toward"]) not in kids:
                raise ValueError(f"split: {op['toward']!r} is not a child joint of {op['bone']} "
                                 f"(children: {[nm[c] for c in kids] or 'none'})")
            child = nm.index(op["toward"])
        elif len(kids) == 1:
            child = kids[0]
        elif len(kids) > 1:
            raise ValueError(f"split: {op['bone']} has several children; add \"toward\": one of {[nm[c] for c in kids]}")
        Bg = self.bind(jb)
        a = Bg[:3, 3]
        D = self.dense()
        if child is not None:
            c_local = s.rest[child][0]
            b = (Bg @ np.r_[c_local, 1.0])[:3]
        else:                          # leaf: toward the far end of the bone's own skin
            m = D[:, jb] > 0.3
            if m.sum() < 4:
                raise ValueError(f"split: {op['bone']} has too little skin to split")
            V = s.P[m] - a
            dirn = (V * D[m, jb][:, None]).sum(0)
            dirn /= max(np.linalg.norm(dirn), 1e-12)
            b = a + dirn * float((V @ dirn).max())
            c_local = np.linalg.solve(Bg[:3, :3], b - a)
        seg = b - a
        if np.linalg.norm(seg) < 1e-6:
            raise ValueError("split: zero-length bone")
        x_local = f * np.asarray(c_local, np.float64)
        name = op.get("name") or f"{op['bone']}_mid"
        nx = self._add_joint(nb, name, x_local)
        jx = len(s.joints) - 1
        if child is not None:          # re-parent the child under the new joint, same global placement
            s.nodes[nb]["children"].remove(child)
            s.nodes[nx].setdefault("children", []).append(child)
            self._offset_translation(child, -x_local)
        sp = ((s.P - a) @ seg) / float(seg @ seg)
        n = self._split_weights(jb, jx, sp, f - 0.18, f + 0.18)
        op["name"] = s.nodes[nx]["name"]
        return {"op": "split", "bone": op["bone"], "new": s.nodes[nx]["name"], "child": nm[child] if child is not None else None,
                "vertices": n}

    def _op_add(self, op):
        s = self.u.scene
        jb = self.jidx(op["parent"])
        nb = s.joints[jb]
        toward = str(op.get("toward", "back"))
        if toward not in DIRS:
            raise ValueError(f"add: toward must be one of {sorted(DIRS)}")
        size = float(np.clip(float(op.get("size", 0.3)), 0.1, 0.6))
        D = self.dense()
        m = D[:, jb] > 0.2
        if m.sum() < 8:
            raise ValueError(f"add: {op['parent']} has too little skin there")
        dv = np.asarray(DIRS[toward])
        proj = s.P @ dv
        pm = proj[m]
        q = float(np.quantile(pm, 1 - size))
        L = float(pm.max() - pm.min()) + 1e-9
        ring = m & (np.abs(proj - q) < 0.06 * L)
        if ring.sum() < 3:
            ring = m & (proj >= q)
        pivot = s.P[ring].mean(0)
        Bg = self.bind(jb)
        x_local = np.linalg.solve(Bg[:3, :3], pivot - Bg[:3, 3])
        name = op.get("name") or f"{op['parent']}_{toward}"
        nx = self._add_joint(nb, name, x_local)
        jx = len(s.joints) - 1
        n = self._split_weights(jb, jx, proj, q - 0.08 * L, q + 0.12 * L)
        if n == 0:
            raise ValueError("add: no weight moved to the new joint")
        op["name"] = s.nodes[nx]["name"]
        return {"op": "add", "parent": op["parent"], "new": s.nodes[nx]["name"], "toward": toward, "vertices": n,
                "pivot": [round(float(x), 4) for x in pivot]}

    def _op_pivot(self, op):
        s = self.u.scene
        jx = self.jidx(op["bone"])
        nx = s.joints[jx]
        d = np.asarray(op["move"], np.float64)[:3]          # mesh space (bind), already scaled by the caller
        Gr = self.rest_globals()
        pa = s.parent.get(nx)
        if pa is None:
            raise ValueError("pivot: the root cannot move its pivot")
        self._offset_translation(nx, np.linalg.solve(Gr[pa][:3, :3], d))
        dx = np.linalg.solve(Gr[nx][:3, :3], d)
        for c in s.nodes[nx].get("children", []):
            self._offset_translation(c, -dx)
        T = np.eye(4); T[:3, 3] = -d
        s.ibm = s.ibm.copy()
        s.ibm[jx] = s.ibm[jx] @ T
        return {"op": "pivot", "bone": op["bone"], "move": [round(float(x), 5) for x in d]}

    def _op_reparent(self, op):
        s = self.u.scene
        jx, jq = self.jidx(op["bone"]), self.jidx(op["parent"])
        nx, nq = s.joints[jx], s.joints[jq]
        a = nq
        while a is not None:
            if a == nx:
                raise ValueError("reparent: the new parent is the bone itself or one of its descendants")
            a = s.parent.get(a)
        old = s.parent.get(nx)
        if old == nq:
            raise ValueError("reparent: already the parent")
        Gr = self.rest_globals()
        Lr = np.linalg.inv(Gr[nq]) @ Gr[nx]
        # bake the bone's local channels per clip on the clip grid from the current globals
        baked = {}
        for clip in s.channels:
            c = self.u.clips.get(clip)
            if c is None:
                continue
            grid = np.asarray(c["grid"], np.float64)
            G, _, _ = self.u.pose(clip, grid, [])
            L = np.linalg.inv(G[:, nq]) @ G[:, nx]
            sc = np.linalg.norm(L[:, :3, :3], axis=1)
            R = L[:, :3, :3] / sc[:, None, :]
            q = mat_to_quat(R)
            for i in range(1, len(q)):
                if np.dot(q[i], q[i - 1]) < 0:
                    q[i] = -q[i]
            baked[clip] = (grid, L[:, :3, 3], q, sc)
        s.nodes[old]["children"].remove(nx)
        s.nodes[nq].setdefault("children", []).append(nx)
        sc0 = np.linalg.norm(Lr[:3, :3], axis=0)
        r0 = mat_to_quat(Lr[:3, :3] / sc0[None, :])
        s.rest[nx] = (Lr[:3, 3].copy(), r0, sc0)
        s.nodes[nx].update(translation=[float(x) for x in Lr[:3, 3]], rotation=[float(x) for x in r0],
                           scale=[float(x) for x in sc0])
        for clip, (grid, t, q, sc) in baked.items():
            chans = [ch for ch in s.channels[clip] if ch[1] != nx]
            chans += [("translation", nx, grid, t, "LINEAR"), ("rotation", nx, grid, q, "LINEAR"),
                      ("scale", nx, grid, sc, "LINEAR")]
            s.channels[clip] = chans
        return {"op": "reparent", "bone": op["bone"], "from": s.nodes[old].get("name"), "to": op["parent"]}
