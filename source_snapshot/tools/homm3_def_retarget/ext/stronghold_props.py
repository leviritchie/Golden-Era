"""Colour-gated rigid props for Stronghold units (clubs, maces, axes, rocks held against the body).

Config key (unit json), list of regions like core "props" plus a colour test:
  "colorProps": [{"name": "club", "bone": "RightHand",
                  "segments": [[a, b], ...] | "sphere": [c, r] | "box": [lo, hi], "radius": r,
                  "exclude": [region, ...],
                  "color": {"expr": "r-g", "min": 0.05} (or "max"),   # texture base colour test
                  "coreRadius": 0.03}]                                # always prop near the axis
A vertex is prop when it lies inside the region and (its base colour passes the test or it is within
coreRadius of a segment). Meshy fuses a club against the shoulder it rests on; geometry alone takes
the deltoid with the club head, colour alone takes the brown tunic, both together take the club.
Faces wholly inside are split off and bound 100% to the bone, like core props.

Hook: after_skin.
"""
import numpy as np
import bmesh
from mathutils import Vector


def _region_test(g, reg):
    seg_dist = g["seg_dist"]
    if "segments" in reg:
        segs = [(Vector(a), Vector(b)) for a, b in reg["segments"]]; r = reg["radius"]
        geo = lambda p: min(seg_dist(p, a, b) for a, b in segs) < r
    elif "sphere" in reg:
        c, r = Vector(reg["sphere"][0]), reg["sphere"][1]
        geo = lambda p: (p - c).length < r
    else:
        lo, hi = Vector(reg["box"][0]), Vector(reg["box"][1])
        geo = lambda p: all(lo[i] <= p[i] <= hi[i] for i in range(3))
    excl = [_region_test(g, e) for e in reg.get("exclude", [])]
    return lambda p: geo(p) and not any(e(p) for e in excl)


def after_skin(g):
    cfg = g["cfg"]; specs = cfg.get("colorProps", [])
    if not specs:
        return
    body = g["body"]; vert_color = g["vert_color"]; seg_dist = g["seg_dist"]
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    for reg in specs:
        test = _region_test(g, reg)
        col = reg.get("color")
        segs = [(Vector(a), Vector(b)) for a, b in reg.get("segments", [])]
        core = reg.get("coreRadius", 0.0)

        def inside(p, test=test, col=col, segs=segs, core=core):
            if not test(p):
                return False
            if core > 0 and segs and min(seg_dist(p, a, b) for a, b in segs) < core:
                return True
            if not col:
                return True
            r, gg, b = (float(x) for x in vert_color(p))
            v = eval(col["expr"], {}, {"r": r, "g": gg, "b": b, "mx": max(r, gg, b), "mn": min(r, gg, b)})
            return v >= col.get("min", -1e9) and v <= col.get("max", 1e9)

        ins = {v.index: inside(v.co) for v in bm.verts}
        # drop isolated prop vertices (texture noise): need at least `minNeighbours` prop neighbours
        for _ in range(reg.get("cleanPasses", 1)):
            ins = {v.index: ins[v.index] and sum(ins[e.other_vert(v).index] for e in v.link_edges) >= reg.get("minNeighbours", 2)
                   for v in bm.verts}
        fin = {f.index: all(ins[v.index] for v in f.verts) for f in bm.faces}
        edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1]
        bmesh.ops.split_edges(bm, edges=edges)
        bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
        faces = {i for i, f in fin.items() if f}
        n = 0
        bi = gidx[reg["bone"]]
        for v in bm.verts:
            if v.link_faces and all(f.index in faces for f in v.link_faces):
                d = v[dl]; d.clear(); d[bi] = 1.0; n += 1
        print("REGION colorProp", reg.get("name", "prop"), "split edges", len(edges), "verts", n)
    bm.to_mesh(body.data); bm.free()
