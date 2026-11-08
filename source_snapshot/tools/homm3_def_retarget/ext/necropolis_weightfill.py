"""Necropolis: give unweighted vertices the weights of their nearest weighted neighbour.

surface_weights.py computes geodesic heat on the welded surface graph; a loose Meshy piece that no
bone seed can reach gets geo = inf and a NaN weight row (the "RuntimeWarning: invalid value" line,
"heat-lost N"). build_unit.py skips NaN rows, so those vertices carry no weight, stay at the rest
position while the body moves, and render as long spikes (h3_bone_dragon: 25 welded vertices, Move
max stretch 50x).

after_skin: every body vertex whose deform weights sum to ~0 copies the groups of the nearest
vertex (by 3D distance) that has weights; the result is limited to 4 influences and renormalised.
Rigid prop/wing vertices are untouched (they already carry weight 1).
"""
import bpy
from mathutils import kdtree


def after_skin(g):
    body = g["body"]
    names = {vg.index: vg.name for vg in body.vertex_groups}
    def total(v):
        return sum(gr.weight for gr in v.groups if names[gr.group] != "Root" and gr.weight == gr.weight)
    empty = [v.index for v in body.data.vertices if total(v) < 1e-6]
    if not empty:
        print("WEIGHTFILL none"); return
    es = set(empty)
    kd = kdtree.KDTree(len(body.data.vertices) - len(es))
    for v in body.data.vertices:
        if v.index not in es:
            kd.insert(v.co, v.index)
    kd.balance()
    vs = body.data.vertices
    for i in empty:
        _, j, _ = kd.find(vs[i].co)
        gs = sorted(((gr.group, gr.weight) for gr in vs[j].groups if gr.weight > 1e-6), key=lambda x: -x[1])[:4]
        tot = max(sum(w for _, w in gs), 1e-9)
        for gr in list(vs[i].groups):
            body.vertex_groups[gr.group].remove([i])
        for gi, w in gs:
            body.vertex_groups[gi].add([i], w / tot, 'REPLACE')
    print("WEIGHTFILL filled", len(empty), "unweighted vertices")
