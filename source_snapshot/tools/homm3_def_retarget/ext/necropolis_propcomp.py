"""Necropolis: bind whole loose mesh pieces to a prop bone when most of the piece is already rigid.

Meshy meshes are often many loose pieces (h3_skeleton_archer: 981 welded components). A prop
region (segments / sphere) catches most of a bow limb or string piece but not its rim; the rim
keeps heat weights (half hand, half thigh) and stretches into a long ribbon when the arm lifts.

after_skin: vertices are welded by position (1e-5) into connected pieces; a piece with at most
`maxVerts` vertices in which at least `minFrac` of the vertices are already bound 100% to one of
the listed bones is bound 100% to that bone. Every vertex keeps exactly one influence (<= 4).

Config: "propComponents": {"bones": ["LeftHand"], "minFrac": 0.4, "maxVerts": 400}
"""
import numpy as np


def _components(m, a, b):
    """Connected-component labels of m nodes joined by edges (a[i], b[i]) (union-find, no scipy in Blender)."""
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
    pc = g["cfg"].get("propComponents")
    if not pc:
        return
    body = g["body"]; me = body.data
    names = {vg.index: vg.name for vg in body.vertex_groups}
    gid = {vg.name: vg.index for vg in body.vertex_groups}
    n = len(me.vertices)
    co = np.array([v.co[:] for v in me.vertices])
    key = np.round(co / 1e-5).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True); weld = weld.ravel()
    E = np.array([e.vertices[:] for e in me.edges])
    m = weld.max() + 1
    lab = _components(m, weld[E[:, 0]], weld[E[:, 1]])
    vlab = lab[weld]
    rigid = np.full(n, -1)
    bones = set(pc.get("bones", []))
    for v in me.vertices:
        gs = [gr for gr in v.groups if gr.weight > 1e-6]
        if len(gs) == 1 and gs[0].weight > 0.999 and names[gs[0].group] in bones:
            rigid[v.index] = gs[0].group
    total = 0
    for c in np.unique(vlab[rigid >= 0]):
        idx = np.nonzero(vlab == c)[0]
        if len(idx) > pc.get("maxVerts", 400):
            continue
        r = rigid[idx]; hit = r[r >= 0]
        if len(hit) / len(idx) < pc.get("minFrac", 0.4):
            continue
        bone = np.bincount(hit).argmax()
        for i in idx[rigid[idx] != bone]:
            v = me.vertices[int(i)]
            for gr in list(v.groups):
                body.vertex_groups[gr.group].remove([int(i)])
            body.vertex_groups[int(bone)].add([int(i)], 1.0, 'REPLACE')
            total += 1
    print("PROPCOMP bound", total, "extra vertices to", sorted(bones))
