"""Cove extension: take arm/hand weight off cloth that merely hangs near a hand.

Heat weighting hands a sash or coat tail hanging beside a lowered fist part of that fist, so the
cloth flies up with the arm. Config (unit json):
  "coveReweight": [{"box": [[x0,y0,z0],[x1,y1,z1]], "dropBones": ["RightHand", ...],
                    "fallback": "RightUpLeg", "minRedOverGreen": 1.8 (optional colour gate),
                    "cut": true (optional: split the selection free of its neighbours),
                    "fadeTop": 0.15 (optional: the removal ramps from full at z1 - fadeTop to
                                     none at z1, so the cloth above keeps a smooth blend),
                    "keepSkin": [1.2, 2.2, 0.08] (optional: skip skin-coloured texels, R/G in
                                     [lo, hi] and R > min -- the hand itself inside the box),
                    "skipRigid": true (optional: skip vertices already bound rigidly, e.g. a
                                     sword guard the box overlaps),
                    "cutAgainstDrop": 0.5 (optional, with "cut": split only along faces whose
                                     outside corners carry more than this much of the dropped
                                     bones, so the selection tears free of the hand but stays
                                     welded to the cloth around the box),
                    "rigidSphere": {"center": [x,y,z], "radius": r, "maxRedOverGreen": 1.2,
                                    "bone": "RightHand", "maxX": -0.24} (optional: dark, unsaturated texels in
                                     the sphere -- a sword's basket guard fused to the cloth it
                                     rests on -- are left out of the selection and bound 100% to
                                     `bone` first, so the cut separates them from the cloth; a
                                     list of such spheres is allowed),
                    "smallIslandsTo": {"bone": "RightHand", "maxVerts": 40, "maxRedShare": 0.2} (optional,
                                     with "cut": selected islands of at most maxVerts vertices
                                     left by the cut, not mostly red (R > 2 G: sash, stays with the
                                     body), are bound whole to `bone`)}]
Selected = vertices in the box (and passing the colour gate). With "cut", faces made only of
selected vertices are split off along their boundary first, so the cloth does not drag a strip of
stretched triangles behind the fist. The listed bones' weights are then removed on the selected
vertices and the rest renormalised; a vertex left with no weight goes to `fallback`.
Keep boxes clear of held props (they were cut earlier and are bound rigidly). Runs at after_skin.
"""
import bmesh
import numpy as np


def after_skin(g):
    after_skin_reach(g)
    cfg, body = g["cfg"], g["body"]
    specs = cfg.get("coveReweight", [])
    if not specs:
        return
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    for sp in specs:
        lo, hi = np.array(sp["box"][0]), np.array(sp["box"][1])
        drop = {gi[b] for b in sp["dropBones"] if b in gi}
        fb = gi[sp["fallback"]]
        gate = sp.get("minRedOverGreen")

        def sel(co):
            p = np.array(co[:])
            if not ((p >= lo).all() and (p <= hi).all()):
                return False
            if gate is None:
                return True
            c = g["vert_color"](co)
            return c[0] > gate * c[1] and c[0] > 0.06

        skin = sp.get("keepSkin")
        rigid = g["taken"] if sp.get("skipRigid") else set()
        sel0 = sel

        def sel(co, idx=None):
            if idx is not None and idx in rigid:
                return False
            if not sel0(co):
                return False
            if skin:
                c = g["vert_color"](co)
                if skin[0] * c[1] < c[0] < skin[1] * c[1] and c[0] > skin[2]:
                    return False
            return True

        rss = sp.get("rigidSphere") or []
        rss = [rss] if isinstance(rss, dict) else rss

        def in_one(rs, co):
            if np.linalg.norm(np.array(co[:]) - np.array(rs["center"])) > rs["radius"]:
                return False
            if co.x > rs.get("maxX", 1e9):      # keep the thigh the guard rests against
                return False
            c = g["vert_color"](co)
            return c[0] < rs.get("maxRedOverGreen", 1.2) * c[1]

        def in_rigid_sphere(co):
            return any(in_one(rs, co) for rs in rss)

        bm = bmesh.new(); bm.from_mesh(body.data)
        dl = bm.verts.layers.deform.verify()
        nrig = 0
        for rs in rss:
            rb = gi[rs["bone"]]
            for v in bm.verts:
                if v.index not in rigid and in_one(rs, v.co):
                    d = v[dl]; d.clear(); d[rb] = 1.0; nrig += 1
        s = {v.index: sel(v.co, v.index) and not in_rigid_sphere(v.co) for v in bm.verts}
        ncut = 0
        if sp.get("cut"):
            fin = {f.index: all(s[v.index] for v in f.verts) for f in bm.faces}
            ca = sp.get("cutAgainstDrop")
            dropw = {v.index: sum(w for k, w in v[dl].items() if k in drop) for v in bm.verts}
            fhand = {f.index: ca is None or (not fin[f.index] and any(dropw[v.index] > ca for v in f.verts)) for f in bm.faces}
            edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1
                     and any(fhand[f.index] for f in e.link_faces if not fin[f.index])]
            bmesh.ops.split_edges(bm, edges=edges); ncut = len(edges)
            bm.faces.ensure_lookup_table()
            # split_edges adds vertices but keeps the faces, so the face selection still holds;
            # a vertex is chosen when it touches the selection and no hand-side face outside it
            chosen = [v for v in bm.verts if any(fin[f.index] for f in v.link_faces)
                      and not any(fhand[f.index] for f in v.link_faces if not fin[f.index])]
        else:
            chosen = [v for v in bm.verts if s.get(v.index, False)]
        # the cut can leave slivers of the guard (a few faces each) as islands of the selection:
        # they float beside the thigh, so bind them whole to the hand they were fused to
        si = sp.get("smallIslandsTo")
        nisl = 0
        if si and sp.get("cut"):
            chosen_set = {v.index for v in chosen}
            seen = set(); sb = gi[si["bone"]]
            for v0 in chosen:
                if v0.index in seen:
                    continue
                comp, stack = [], [v0]; seen.add(v0.index)
                while stack:
                    v = stack.pop(); comp.append(v)
                    for e in v.link_edges:
                        u = e.other_vert(v)
                        if u.index not in seen:
                            seen.add(u.index); stack.append(u)
                red = sum(1 for v in comp if (lambda c: c[0] > si.get("redOverGreen", 2.0) * c[1])(g["vert_color"](v.co)))
                if (len(comp) <= si.get("maxVerts", 40) and all(v.index in chosen_set for v in comp)
                        and red <= si.get("maxRedShare", 0.2) * len(comp)):
                    for v in comp:
                        d = v[dl]; d.clear(); d[sb] = 1.0
                        chosen_set.discard(v.index)
                    nisl += 1
            chosen = [v for v in chosen if v.index in chosen_set]
        n = 0
        for v in chosen:
            d = v[dl]
            if not any(k in drop for k in d.keys()):
                continue
            ft = sp.get("fadeTop", 0.0)
            f = 1.0 if ft <= 0 else min(1.0, max(0.0, (hi[2] - v.co.z) / ft))
            keep = {k: (w if k not in drop else w * (1 - f)) for k, w in d.items() if w > 1e-4}
            if sum(w for k, w in keep.items() if k not in drop) <= 1e-4 and f >= 1.0:
                keep = {}
            d.clear(); tot = sum(keep.values())
            if tot <= 1e-4:
                d[fb] = 1.0
            else:
                for k, w in keep.items():
                    d[k] = w / tot
            n += 1
        bm.to_mesh(body.data); bm.free()
        print("HOOK COVE reweight", sp["box"], "cut edges", ncut, "verts", n, "rigid sphere verts", nrig, "islands to hand", nisl)


def _seg_dist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def after_skin_reach(g):
    """"coveArmReach": {"inner": 0.08, "outer": 0.16, "bones": ["Arm", "ForeArm", "Hand"]}
    Heat spreads arm weight over a coat front or chest the arm only hangs beside; when the arm
    lifts, the whole panel stretches up with it. Each arm bone's weight is scaled by a falloff of
    the vertex's distance to that side's arm chain (1 inside `inner`, 0 beyond `outer`), then the
    row is renormalised (an emptied row goes to Hips). Rigid regions (props, wings) are skipped."""
    cfg, body = g["cfg"], g["body"]
    R = cfg.get("coveArmReach")
    if not R:
        return
    J, taken = g["J"], g["taken"]
    inner, outer = R.get("inner", 0.08), R.get("outer", 0.16)
    P = np.array([v.co[:] for v in body.data.vertices])
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    hips = gi["Hips"]
    scale = {}
    for side in ("Left", "Right"):
        chain = [(side + a, side + b) for a, b in (("Arm", "ForeArm"), ("ForeArm", "Hand"), ("Hand", "Hand_End"))
                 if side + a in J and side + b in J]
        if not chain:
            continue
        d = np.min(np.stack([_seg_dist(P, np.array(J[a]), np.array(J[b])) for a, b in chain], 1), 1)
        f = np.clip((outer - d) / max(outer - inner, 1e-6), 0, 1)
        for b in R.get("bones", ["Arm", "ForeArm", "Hand"]):
            if side + b in gi:
                scale[gi[side + b]] = f
    n = 0
    for v in body.data.vertices:
        if v.index in taken:
            continue
        ws = {x.group: x.weight for x in v.groups}
        if not any(k in scale and scale[k][v.index] < 1 for k in ws):
            continue
        new = {k: (w * scale[k][v.index] if k in scale else w) for k, w in ws.items()}
        tot = sum(new.values())
        for k in ws:
            body.vertex_groups[k].remove([v.index])
        if tot <= 1e-4:
            body.vertex_groups[hips].add([v.index], 1.0, 'REPLACE')
        else:
            for k, w in new.items():
                if w > 1e-5:
                    body.vertex_groups[k].add([v.index], w / tot, 'REPLACE')
        n += 1
    print("HOOK COVE armReach", inner, outer, "verts changed", n)
