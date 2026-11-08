"""Cove extension: a hand-placed centreline for a coiled snake tail (sea serpents).

surface_weights.py orders the snake body by distance *along the surface* from the waist and takes
the centreline as the centroid of each distance band. The Cove serpents' coil is a helix whose
laps touch and are fused by Meshy, so the surface distance leaks across the contact, both laps
share distance bands, and the centroid cuts through the middle of the loop (the back half of the
loop then stretches in Move / Attack / Death).

Config: "coveTailPath": {"points": [[x, y, z], ...], "fuseCut": 1.5, "dropStraddling": false}
`points` runs from the waist (the Hips joint) along the middle of the body to the tail tip. At
after_skin (bones not yet read for rest poses):
  1. the path is resampled to the existing tail bone count and the Tail_* bones are moved onto it
     (TPts, which the tail solver reads later, is updated in place);
  2. every vertex that carries tail weight takes its position along the body by projection onto
     the nearest point of the path (touching laps sit a lap apart along the path, so they stay
     apart), and edges whose ends lie more than `fuseCut` segments apart along the body -- the
     fused contact between laps, or a lap against the neck -- are cut;
  3. each such vertex is re-weighted from its new position: the two nearest tail bones, and near
     the waist (u < waistBlend) a falling share of its torso weights, limited to 4 influences.
With "dropStraddling": true the triangles spanning two laps are also collapsed onto their waist-side corner
(zero area; the vertex count is kept so later stages' indices hold): on a tightly fused coil (h3_naga_upg) the
detached triangles stuck out of the lap as fins once the tail uncoiled. They sat in the contact between the laps.
With "capCuts": true the openings the cut leaves in each lap (where the laps were merged) are filled with new faces
on the existing boundary vertices (loops of at most "capMaxSides" edges, default 64; tail-weighted edges only).
"""
import numpy as np
try:                                  # Blender only; the pure helpers below are unit-tested outside it
    import bmesh
    import bpy
    from mathutils import Vector
except ImportError:
    bmesh = bpy = Vector = None


def _resample(pts, n):
    L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    s = np.linspace(0, L[-1], n + 1)
    return np.stack([np.interp(s, L, pts[:, i]) for i in range(3)], 1)


def _project(Q, TP):
    best = np.full(len(Q), 1e9); u = np.zeros(len(Q))
    for k in range(len(TP) - 1):
        a, b = TP[k], TP[k + 1]; ab = b - a
        t = np.clip(((Q - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
        d = np.linalg.norm(Q - (a + t[:, None] * ab), axis=1)
        m = d < best; best[m] = d[m]; u[m] = k + t[m]
    return u


def cap_edges(spec, edges, tail_verts):
    """Boundary edges whose openings capCuts fills: none unless the config opts in ("capCuts": true), else
    every boundary edge with both ends among `tail_verts` (vertex indices carrying > 0.3 tail weight).
    `edges`: objects with .is_boundary and .verts[i].index (bmesh edges)."""
    if not spec.get("capCuts"):
        return []
    return [e for e in edges if e.is_boundary and e.verts[0].index in tail_verts and e.verts[1].index in tail_verts]


def after_skin(g):
    cfg = g["cfg"]; spec = cfg.get("coveTailPath")
    TAILB, TPts = g["TAILB"], g["TPts"] if g["TAILB"] else None
    if not spec or not TAILB:
        return
    body, rig = g["body"], g["rig"]
    NT = len(TAILB)
    TP = _resample(np.array(spec["points"], float), NT)
    # 1. bones onto the path
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for k, n in enumerate(TAILB):
        eb[n].head, eb[n].tail = Vector(TP[k]), Vector(TP[k + 1]); eb[n].roll = 0
    bpy.ops.object.mode_set(mode='OBJECT')
    for k in range(NT + 1):
        TPts[k] = Vector(TP[k])
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    tail_ids = {gi[n]: k for k, n in enumerate(TAILB)}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    bm.verts.ensure_lookup_table()
    share = np.array([sum(w for gk, w in v[dl].items() if gk in tail_ids) for v in bm.verts])
    Q = np.array([v.co[:] for v in bm.verts])
    u = _project(Q, TP)
    # 2. cut fused contacts
    fc = spec.get("fuseCut", 1.5)
    WB = cfg.get("tail", {}).get("waistBlend", 0.6)
    cut = []
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        ta, tb = share[a] > 0.3, share[b] > 0.3
        if ta and tb and abs(u[a] - u[b]) > fc:
            cut.append(e)
        elif ta != tb and max(u[a] if ta else 0, u[b] if tb else 0) > fc:
            cut.append(e)
    # triangles whose corners lie on two laps (Meshy fused them) cannot be separated by cutting
    # edges: detach each one and let it ride on one lap only (the corner nearest the waist)
    straddle = []
    for f in bm.faces:
        us = [u[v.index] for v in f.verts if share[v.index] > 0.3]
        if len(us) >= 2 and max(us) - min(us) > fc:
            straddle.append(f)
    cutset = set(cut)
    for f in straddle:
        cutset.update(f.edges)
    bmesh.ops.split_edges(bm, edges=list(cutset))
    bm.verts.ensure_lookup_table()
    # split vertices keep their deform data; recompute per current vertex
    n = 0
    for v in bm.verts:
        d = v[dl]
        t = sum(w for gk, w in d.items() if gk in tail_ids)
        if t <= 1e-4:
            continue
        uu = _project(np.array([v.co[:]]), TP)[0]
        tw = {k: max(0.0, 1 - abs(uu - (k + 0.5))) for k in range(NT)}
        tw = {k: w for k, w in tw.items() if w > 1e-4}
        if not tw:
            tw = {min(NT - 1, int(uu)): 1.0}
        s = sum(tw.values())
        # the waist blend (keep a falling share of the torso weights over the first `waistBlend`
        # segments) is redone from the new position: with the old one, loops that touched the
        # waist kept most of their weight on Hips
        keep = max(0.0, 1.0 - uu / WB) if WB > 0 else 0.0
        rest = {gk: w for gk, w in d.items() if gk not in tail_ids}
        rs = sum(rest.values())
        rest = {gk: w / rs for gk, w in rest.items()} if rs > 1e-6 else {gi["Hips"]: 1.0}
        new = {gk: w * keep for gk, w in rest.items()}
        for k, w in tw.items():
            new[gi[TAILB[k]]] = (1 - keep) * w / s
        top = sorted(new.items(), key=lambda x: -x[1])[:4]
        tot = sum(w for _, w in top)
        d.clear()
        for gk, w in top:
            if w > 1e-5:
                d[gk] = w / tot
        n += 1
    for f in straddle:
        vs = list(f.verts)
        src = min(vs, key=lambda v: _project(np.array([v.co[:]]), TP)[0])
        w = dict(src[dl].items())
        for v in vs:
            if v is not src:
                d = v[dl]; d.clear()
                for gk, ww in w.items():
                    d[gk] = ww
                if spec.get("dropStraddling"):
                    v.co = src.co.copy()
    ncap = 0
    bm.verts.ensure_lookup_table()
    tset = {v.index for v in bm.verts if sum(w for gk, w in v[dl].items() if gk in tail_ids) > 0.3}
    tset -= {v.index for f in straddle for v in f.verts}      # detached lap-bridging triangles are not openings
    bnd = cap_edges(spec, bm.edges, tset)
    if bnd:
        # cutting the fused contact between two laps leaves each lap with an opening where Meshy had
        # merged its surface into the other lap; close those openings (faces only, no new vertices, so
        # every later stage's vertex indices hold)
        nf = len(bm.faces)
        bmesh.ops.holes_fill(bm, edges=bnd, sides=spec.get("capMaxSides", 64))
        ncap = len(bm.faces) - nf
    bm.to_mesh(body.data); bm.free()
    print("HOOK COVE tailpath caps", ncap)
    print("HOOK COVE tailpath bones", NT, "cut edges", len(cut), "straddling faces", len(straddle), "verts", n)
