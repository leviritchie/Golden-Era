"""Dungeon: repair vertices left without usable skin weights.

surface_weights.py gives NaN weights to vertices on mesh islands that no bone reaches along the
surface and that bone heat also missed (infernal troglodyte: 32 such vertices). NaN or all-zero
rows skin to garbage (flying shards) and make the corrective-smooth bake's solve singular.
after_skin: each such vertex copies the weights of the nearest vertex with valid weights.
"""
import math


def after_skin(g):
    body, kdtree = g["body"], g["kdtree"]
    bad, good = [], []
    for v in body.data.vertices:
        ws = [x.weight for x in v.groups]
        ok = ws and all(math.isfinite(w) for w in ws) and sum(ws) > 1e-4
        (good if ok else bad).append(v.index)
    if not bad:
        print("DUNGEON fixweights: none")
        return
    kd = kdtree.KDTree(len(good))
    for i in good:
        kd.insert(body.data.vertices[i].co, i)
    kd.balance()
    vg = body.vertex_groups
    for i in bad:
        v = body.data.vertices[i]
        src = body.data.vertices[kd.find(v.co)[1]]
        for x in list(v.groups):
            vg[x.group].remove([i])
        for x in src.groups:
            vg[x.group].add([i], x.weight, 'REPLACE')
    print("DUNGEON fixweights: repaired", len(bad))
