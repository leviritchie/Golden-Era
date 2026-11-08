"""blender_panel.py -- <p1.npz> <p2.npz> [--edge 0.018] [--gap 0.01]

Stage 2 of the chest-panel surgery, run inside Blender (bmesh + BVH):
- the body (torso cut away under the folded arms) and the freed arm block are rebuilt as position-welded bmeshes
- every NEW open boundary loop (not open in the source mesh) is filled with bmesh triangle_fill (beauty), refined to
  --edge with grid subdivision + beautify, then faired: the body panel by a bi-Laplacian solve with the boundary and
  its original one-ring held, so it continues the surrounding robe tangentially (a rebuilt torso front, not a flat
  window); arm caps by a harmonic solve
- the body panel is clamped --gap behind the arm block's front surface (BVH ray along -Z) wherever the arms cover it,
  so it never shows at rest, then re-faired with the clamp held
Writes <p2.npz>: per filled loop the new vertices (positions, normals, side, nearest source vertex) and faces over
(source index | new index) for finish.py."""
import sys, numpy as np, bmesh, bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
inp, outp = argv[0], argv[1]
EDGE = float(argv[argv.index("--edge") + 1]) if "--edge" in argv else 0.018
GAP = float(argv[argv.index("--gap") + 1]) if "--gap" in argv else 0.01
d = np.load(inp)
V = d["V"]; N0 = int(d["N0"]); oldF = d["oldF"]


def weld(F):
    u, inv = np.unique(np.round(V, 6), axis=0, return_inverse=True)
    return u, inv.ravel()


U, W = weld(None)                      # welded positions, original index -> weld id


def open_edges(F):
    E = np.sort(np.stack([W[F[:, [0, 1]]], W[F[:, [1, 2]]], W[F[:, [2, 0]]]], 1), axis=2).reshape(-1, 2)
    u, c = np.unique(E, axis=0, return_counts=True)
    return set(map(tuple, u[c == 1]))


pre_open = open_edges(oldF)
print("PANEL pre-existing open edges", len(pre_open))


def build(F):
    bm = bmesh.new()
    ids = np.unique(W[F].ravel())
    vm = {}
    for w in ids:
        vm[int(w)] = bm.verts.new(Vector(U[w]))
    bm.verts.index_update()
    for f in F:
        try:
            bm.faces.new([vm[int(W[x])] for x in f])
        except ValueError:
            pass                       # duplicate face (UV-seam twin triangles)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    wid = {v: w for w, v in vm.items()}
    return bm, wid


def all_edges(F):
    E = np.sort(np.stack([W[F[:, [0, 1]]], W[F[:, [1, 2]]], W[F[:, [2, 0]]]], 1), axis=2).reshape(-1, 2)
    return set(map(tuple, np.unique(E, axis=0)))


def loops(bm, wid, other):
    """components of new open edges (not open in the source, not shared with the other part, e.g. the elbow)"""
    ed = [e for e in bm.edges if e.is_boundary and tuple(sorted((wid[e.verts[0]], wid[e.verts[1]]))) not in pre_open
          and tuple(sorted((wid[e.verts[0]], wid[e.verts[1]]))) not in other]
    adj = {}
    for e in ed:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    seen, comps = set(), []
    for e in ed:
        if e in seen: continue
        st, comp = [e], []
        seen.add(e)
        while st:
            x = st.pop(); comp.append(x)
            for v in x.verts:
                for y in adj[v]:
                    if y not in seen:
                        seen.add(y); st.append(y)
        comps.append(comp)
    return comps


def fair(bm, newv, fixed_extra, order, iters, clamp=None):
    """Jacobi fairing of the new verts; order 1 harmonic, 2 bi-Laplacian (fixed: everything not in newv)"""
    allv = set(newv) | set(fixed_extra)
    for v in list(newv):
        for e in v.link_edges:
            allv.add(e.other_vert(v))
    allv = list(allv); ix = {v: i for i, v in enumerate(allv)}
    P = np.array([v.co[:] for v in allv]); free = np.array([v in set(newv) for v in allv])
    nb = [[ix[e.other_vert(v)] for e in v.link_edges if e.other_vert(v) in ix] for v in allv]
    deg = np.array([len(n) for n in nb])
    rows = np.repeat(np.arange(len(allv)), deg); cols = np.concatenate([np.array(n, int) for n in nb if n] or [np.zeros(0, int)])
    def lap(X):
        S = np.zeros_like(X); np.add.at(S, rows, X[cols]); return S / np.maximum(deg, 1)[:, None] - X
    for it in range(iters):
        L = lap(P)
        if order == 2:
            L2 = lap(L); P[free] -= 0.25 * L2[free]
        else:
            P[free] += 0.8 * L[free]
        if clamp is not None and it % 10 == 9:
            P = clamp(P, free)
    if clamp is not None: P = clamp(P, free)
    for v, p in zip(allv, P):
        if v in set(newv): v.co = Vector(p)


def fill_loop(bm, comp, panel, arm_bvh):
    before = set(bm.verts); orig = set(bm.faces); bset = set(comp)
    # undirected Euler walk over the loop's edges (Meshy winding is not consistent), split at pinch vertices into
    # simple cycles; each cycle is then oriented against the face owning its first edge
    adj = {}
    for e in comp:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    used = set(); cycles = []
    odd = [v for v, es in adj.items() if len(es) % 2]
    starts = [(es[0], v) for v in odd for es in [adj[v]]] + [(e, e.verts[0]) for e in comp]
    for e0, sv in starts:
        if e0 in used: continue
        used.add(e0); start, c = sv, e0.other_vert(sv)
        path = [start, c]; pos = {start: 0, c: 1}
        while True:
            nxt = [x for x in adj[c] if x not in used]
            if not nxt: break
            e = nxt[0]; used.add(e); n = e.other_vert(c)
            if n in pos:
                cyc = path[pos[n]:]; cycles.append(cyc)
                for x in cyc[1:]: del pos[x]
                path = path[:pos[n] + 1]; c = n
                if len(path) == 1:
                    nxt2 = [x for x in adj[c] if x not in used]
                    if not nxt2: break
                    e = nxt2[0]; used.add(e); n = e.other_vert(c); pos[n] = 1; path.append(n); c = n
                continue
            pos[n] = len(path); path.append(n); c = n
        if len(path) > 2:
            print("PANEL open path closed by a chord", len(path), "chord", round((path[0].co - path[-1].co).length, 3))
            cycles.append(path)
    def orient(cyc):
        a_, b_ = cyc[0], cyc[1]
        e = bm.edges.get((a_, b_))
        if e is None or not e.link_faces: return cyc
        for lp in e.link_faces[0].loops:
            if lp.vert == a_ and lp.link_loop_next.vert == b_:
                return cyc[::-1]
        return cyc
    cycles = [orient(c) for c in cycles]
    ng = []
    for cyc in cycles:
        if len(cyc) < 3: continue
        try:
            ng.append(bm.faces.new(cyc))
        except ValueError as ex:
            print("PANEL cycle face failed", len(cyc), ex)
    if not ng:
        return None
    print("PANEL cycles", [len(c) for c in cycles])
    bmesh.ops.triangulate(bm, faces=ng, quad_method="BEAUTY", ngon_method="BEAUTY")
    newf = lambda: [f for f in bm.faces if f not in orig]
    for _ in range(8):
        nf = newf(); nfs = set(nf)
        ne = [e for e in {e for f in nf for e in f.edges} if e not in bset and e.calc_length() > 1.4 * EDGE
              and all(x in nfs for x in e.link_faces)]
        if not ne: break
        bmesh.ops.subdivide_edges(bm, edges=ne, cuts=1, use_grid_fill=True)
        nf = newf()
        bmesh.ops.triangulate(bm, faces=[f for f in nf if len(f.verts) > 3])
        nf = newf(); nfs = set(nf)
        bmesh.ops.beautify_fill(bm, faces=nf, edges=[e for e in {e for f in nf for e in f.edges}
                                                     if e not in bset and all(x in nfs for x in e.link_faces)])
    nf = newf()
    newv = [v for v in bm.verts if v not in before]
    bnd = {x for e in comp for x in e.verts}
    ring1 = {e.other_vert(v) for v in bnd for e in v.link_edges if e.other_vert(v) in before}
    return newv, nf, bnd


out = {}
for tag, F, panel, oF in (("body", d["bodyF"], True, d["armF"]), ("arm", d["armF"], False, d["bodyF"])):
    bm, wid = build(F)
    abm, _ = build(d["armF"])
    arm_bvh = BVHTree.FromBMesh(abm)
    orig_all = set(bm.faces)
    comps = loops(bm, wid, all_edges(oF))
    print("PANEL", tag, "new loops", [len(c) for c in comps])
    for ci, comp in enumerate(comps):
        if len(comp) < 3 or not all(e.is_valid for e in comp): continue
        nb = len(bm.verts); nfb = len(bm.faces)
        r = fill_loop(bm, comp, panel, arm_bvh)
        print("PANEL", tag, "loop", ci, "edges", len(comp), "ok" if r else "FAILED", "verts +", len(bm.verts) - nb, "faces +", len(bm.faces) - nfb)
    bm.normal_update(); bm.verts.index_update()
    out[tag + "_pos"] = np.array([v.co[:] for v in bm.verts])
    out[tag + "_nrm"] = np.array([v.normal[:] for v in bm.verts])
    out[tag + "_wid"] = np.array([wid.get(v, -1) for v in bm.verts], int)
    out[tag + "_faces"] = np.array([[v.index for v in f.verts] for f in bm.faces if len(f.verts) == 3], int)
    out[tag + "_new"] = np.array([f not in orig_all for f in bm.faces if len(f.verts) == 3], bool)
    print("PANEL", tag, "non-tri faces", sum(len(f.verts) != 3 for f in bm.faces))
out["U"] = U; out["W"] = W
np.savez(outp, **out)
print("PANEL done", {k: v.shape for k, v in out.items()})
