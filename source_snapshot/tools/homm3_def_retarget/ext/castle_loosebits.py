"""Castle: loose Meshy pieces (studs, bracers, straps) move with the surface they sit on.

Some Meshy meshes are many separate pieces (h3_archangel: 28, h3_seraph: 14): shield studs, bracer
rings, belt plates. Bone heat weights each small piece on its own, so a stud can follow a different
bone than the shield under it and float away when the arm moves.

after_skin: vertices are welded by position (1e-5) into connected pieces. Every piece with at most
`maxVerts` vertices takes, for all its vertices, the mean weights of the `k` nearest vertices that
belong to any other piece (the surface it sits on; weights as they were before this hook). A piece already bound 100% to one bone in
all its vertices (a prop region) is left alone. Weights are limited to 4 per vertex and normalised.

Config: "looseBits": {"maxVerts": 120, "k": 8, "skipBones": []}

Before that, "pieceBones": [{"point": [x, y, z], "bone": "LeftWing"}, ...] binds the whole piece that
contains the vertex nearest each point 100% to that bone (wings, a shield, a sword that Meshy made as
separate pieces: no cut needed, and no box has to separate them from the body).
"""
import numpy as np


def _components(m, a, b):
    par = np.arange(m)
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for x, y in zip(a.tolist(), b.tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            par[rx] = ry
    return np.array([find(i) for i in range(m)])


def after_skin(g):
    cfg = g["cfg"].get("looseBits"); pb = g["cfg"].get("pieceBones", [])
    if cfg is None and not pb:
        return
    cfg = cfg or {}
    body = g["body"]; me = body.data; vg = body.vertex_groups
    n = len(me.vertices); nb = len(vg)
    co = np.array([v.co[:] for v in me.vertices])
    W = np.zeros((n, nb))
    for v in me.vertices:
        for gr in v.groups:
            W[v.index, gr.group] = gr.weight
    key = np.round(co / 1e-5).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True); weld = weld.ravel()
    E = np.array([e.vertices[:] for e in me.edges])
    lab = _components(weld.max() + 1, weld[E[:, 0]], weld[E[:, 1]])
    vlab = lab[weld]
    ids, cnt = np.unique(vlab, return_counts=True); size = dict(zip(ids.tolist(), cnt.tolist()))
    for e in pb:
        i0 = int(np.argmin(np.linalg.norm(co - np.array(e["point"]), axis=1)))
        idx = np.nonzero(vlab == vlab[i0])[0]; b = vg[e["bone"]].index
        for i in idx.tolist():
            for gr in list(me.vertices[i].groups):
                vg[gr.group].remove([i])
            vg[b].add([i], 1.0, 'REPLACE')
        W[idx] = 0; W[idx, b] = 1
        print("REGION castle_loosebits piece", e["bone"], len(idx))
    if "maxVerts" not in cfg:
        return
    maxv, k = cfg.get("maxVerts", 120), cfg.get("k", 8)
    skip = {vg[b].index for b in cfg.get("skipBones", []) if b in vg}
    done = 0; pieces = 0
    for c in ids[cnt <= maxv]:
        idx = np.nonzero(vlab == c)[0]
        if (W[idx].max(1) > 0.999).all() and len(set(W[idx].argmax(1).tolist())) == 1:
            continue
        host = np.nonzero(vlab != c)[0]
        if len(host) == 0:
            continue
        cen = co[idx].mean(0)
        d = np.linalg.norm(co[host] - cen, axis=1)
        near = host[np.argsort(d)[:k]]
        w = W[near].mean(0)
        for s in skip:
            w[s] = 0
        top = np.argsort(-w)[:4]; w2 = np.zeros(nb); w2[top] = w[top]
        if w2.sum() <= 0:
            continue
        w2 /= w2.sum()
        for i in idx.tolist():
            for gr in list(me.vertices[i].groups):
                vg[gr.group].remove([i])
            for b in top:
                if w2[b] > 0:
                    vg[int(b)].add([i], float(w2[b]), 'REPLACE')
        done += len(idx); pieces += 1
    print("REGION castle_loosebits pieces", pieces, "verts", done)
