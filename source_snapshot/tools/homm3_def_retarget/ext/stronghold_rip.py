"""Rip the mesh open where two bone sets meet (hand fused to thigh, forearm fused to hip).

Meshy fuses a hanging fist to the thigh it rests on; bone heat then blends hand and leg weights
across the contact and a raised arm pulls a sheet down to the knee. Config (unit json):
  "rips": [{"a": ["LeftHand", "LeftForeArm"], "b": ["LeftUpLeg", "Hips"],
            "box": [lo, hi] | "sphere": [c, r],   # optional: only faces inside (by centroid)
            "minShare": 0.05}]                      # a face belongs to a side only above this
Each face whose vertices carry more set-a than set-b weight (summed) is side a, the reverse side b
(faces with less than minShare of either are neutral). Edges between an a-face and a b-face are
split, then every vertex whose faces are all a/neutral loses its set-b weights and vice versa.
Each vertex is then re-limited to its 4 largest weights and renormalised (glTF skins carry 4).
Rigid vertices (one bone at weight 1) are untouched. Hook: after_skin (after stronghold_props).

  "strips": [{"bones": ["LeftArm", "LeftForeArm"], "box": [lo, hi] | "sphere": [c, r]}]
runs first: every non-rigid vertex inside the region (by rest position) loses the listed bones'
weights (renormalised, never emptied) -- torso flesh that bone heat gave to a hanging arm.
"""
import bmesh
from mathutils import Vector


def _in_region(rip, c):
    if "box" in rip:
        lo, hi = rip["box"]
        return all(lo[i] <= c[i] <= hi[i] for i in range(3))
    if "sphere" in rip:
        return (c - Vector(rip["sphere"][0])).length < rip["sphere"][1]
    return True


def after_skin(g):
    rips = g["cfg"].get("rips", []); strips = g["cfg"].get("strips", [])
    if not rips and not strips:
        return
    body = g["body"]
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    for st in strips:
        S = {gidx[n] for n in st["bones"] if n in gidx}; ns = 0
        for v in bm.verts:
            d = v[dl]
            if len(d) == 1 or not _in_region(st, v.co) or not any(k in S for k in d.keys()):
                continue
            items = [(k, w) for k, w in d.items() if k not in S]
            s_ = sum(w for _, w in items)
            if s_ <= 1e-8:
                continue
            d.clear()
            for k, w in items:
                d[k] = w / s_
            ns += 1
        print("STRIP", st.get("name", "strip"), "vertices", ns)
    for rip in rips:
        A = {gidx[n] for n in rip["a"] if n in gidx}
        B = {gidx[n] for n in rip["b"] if n in gidx}
        ms = rip.get("minShare", 0.05)
        bm.faces.ensure_lookup_table()
        side = {}
        for f in bm.faces:
            if not _in_region(rip, f.calc_center_median()):
                continue
            wa = sum(w for v in f.verts for k, w in v[dl].items() if k in A)
            wb = sum(w for v in f.verts for k, w in v[dl].items() if k in B)
            n = len(f.verts)
            if wa / n < ms and wb / n < ms:
                continue
            side[f.index] = "a" if wa >= wb else "b"
        edges = [e for e in bm.edges
                 if len({side.get(f.index) for f in e.link_faces} - {None}) > 1]
        # remember sides by face identity: split_edges keeps faces but may reorder indices
        fside = {f: side[f.index] for f in bm.faces if f.index in side}
        bmesh.ops.split_edges(bm, edges=edges)
        bm.verts.ensure_lookup_table()
        na = nb = 0
        for v in bm.verts:
            d = v[dl]
            if len(d) == 1 and abs(next(iter(d.values())) - 1.0) < 1e-6:
                continue  # rigid
            ss = {fside.get(f) for f in v.link_faces} - {None}
            if ss == {"a"}:
                drop = B; na += 1
            elif ss == {"b"}:
                drop = A; nb += 1
            else:
                continue
            items = [(k, w) for k, w in d.items() if k not in drop]
            if not items or sum(w for _, w in items) <= 1e-8:
                continue  # never empty a vertex
            items = sorted(items, key=lambda t: -t[1])[:4]
            s = sum(w for _, w in items)
            d.clear()
            for k, w in items:
                d[k] = w / s
        print("RIP", rip.get("name", "rip"), "split edges", len(edges), "side-a verts", na, "side-b verts", nb)
    # re-limit every vertex to 4 influences, renormalised
    n4 = 0
    for v in bm.verts:
        d = v[dl]
        if len(d) > 4:
            items = sorted(d.items(), key=lambda t: -t[1])[:4]; s = sum(w for _, w in items)
            d.clear()
            for k, w in items:
                d[k] = w / s
            n4 += 1
    print("RIP limit4 vertices", n4)
    bm.to_mesh(body.data); bm.free()
