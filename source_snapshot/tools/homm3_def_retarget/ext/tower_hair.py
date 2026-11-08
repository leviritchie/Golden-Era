"""Tower: long hair on the back skinned to the spine and head, not to the arms (h3_naga, 2026-10-10).

Bone heat binds a Meshy hair sheet that lies on the upper back to whatever bone is nearest: on the naga the
hair between the shoulder blades carried LeftArm / LeftShoulder / LowLeftShoulder weight, so every arm fling
(Hitted, Death) dragged strips of hair across the shoulders and chest.
after_skin, config "hairWeights": {"box": [[x0, y0, z0], [x1, y1, z1]], "maxV": 0.2, "chain": ["Spine1", "Spine2", "Neck", "Head"],
                                   "falloff": 0.03}
  * hair = vertices inside the Blender-space box whose texture colour is dark (max channel < maxV);
  * each takes the chain only, interpolated by height between consecutive chain joints (J[bone] heads):
    below the first joint wholly the first bone, above the last wholly the last;
  * non-hair vertices within `falloff` of a hair vertex (the skin it is welded to) take half that blend,
    so the hair edge does not stretch against the back.
Each vertex keeps at most 4 bone weights, renormalised. Opt-in per unit; no config, no change.
"""
import numpy as np
from mathutils import kdtree


def _colors(me):
    img = next(n.image for n in me.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    w, h = img.size
    px = np.array(img.pixels[:]).reshape(h, w, 4)
    C = np.zeros((len(me.vertices), 3)); cnt = np.zeros(len(me.vertices))
    uvl = me.uv_layers[0].data
    for l in me.loops:
        u, v = uvl[l.index].uv
        C[l.vertex_index] += px[min(int(v * h), h - 1) % h, min(int(u * w), w - 1) % w, :3]
        cnt[l.vertex_index] += 1
    return C / np.maximum(cnt, 1)[:, None]


def _set(vg, i, ws):
    top = sorted(((w, k) for k, w in ws.items() if w > 1e-5), reverse=True)[:4]
    s = sum(w for w, _ in top)
    for g in vg:
        g.remove([i])
    for w, k in top:
        vg[k].add([i], w / s, 'REPLACE')


def after_skin(g):
    body, cfg, J = g["body"], g["cfg"], g["J"]
    hw = cfg.get("hairWeights")
    if not hw:
        return
    me = body.data; vg = body.vertex_groups
    gname = {x.index: x.name for x in vg}
    P = np.array([v.co[:] for v in me.vertices])
    C = _colors(me)
    lo, hi = np.array(hw["box"][0]), np.array(hw["box"][1])
    hair = np.all((P >= lo) & (P <= hi), 1) & (C.max(1) < hw.get("maxV", 0.2))
    chain = hw.get("chain", ["Spine1", "Spine2", "Neck", "Head"])
    zs = np.array([J[b][2] for b in chain])

    def blend(z):
        if z <= zs[0]:
            return {chain[0]: 1.0}
        if z >= zs[-1]:
            return {chain[-1]: 1.0}
        k = int(np.searchsorted(zs, z)) - 1
        t = (z - zs[k]) / max(zs[k + 1] - zs[k], 1e-6)
        return {chain[k]: 1 - t, chain[k + 1]: t}

    idx = np.nonzero(hair)[0]
    for i in idx:
        _set(vg, int(i), blend(P[i, 2]))
    kd = kdtree.KDTree(len(idx))
    for n, i in enumerate(idx):
        kd.insert(P[i], int(i))
    kd.balance()
    fo = hw.get("falloff", 0.03); n_edge = 0
    for i in np.nonzero(~hair)[0]:
        co, j, d = kd.find(P[i])
        if j is None or d > fo:
            continue
        old = {gname[x.group]: x.weight for x in me.vertices[int(i)].groups}
        s = sum(old.values())
        if s <= 1e-6:
            continue
        new = {k: 0.5 * w / s for k, w in old.items()}
        for k, w in blend(P[i, 2]).items():
            new[k] = new.get(k, 0.0) + 0.5 * w
        _set(vg, int(i), new); n_edge += 1
    print("HOOK tower hair verts", len(idx), "edge blend", n_edge)
