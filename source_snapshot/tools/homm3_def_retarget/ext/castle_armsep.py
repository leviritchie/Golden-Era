"""Castle: cut a hanging arm free of the torso/hip skin Meshy fused it to.

h3_crossbowman: the left upper arm and forearm hang against the waist and hip, and Meshy welds the two surfaces
along the contact. Bone heat then bleeds LeftArm/LeftForeArm weight 0.3-0.9 into the waist/back skin and hip weight
into the inner sleeve, so any arm raise (ShootFront shouldering the crossbow) stretches the contact into a sheet.
Weight-only fixes cannot help -- the surfaces share edges, so moving weight just moves the stretch (patch-lane
moveWeights trials 1549 -> 1615-1749 tears).

after_skin (config "armSep"): within the height band low < z < top (Blender build space, z up) every face is classed
ARM when its centroid lies within radius(z) + margin of the arm axis polyline (fitted to the sleeve's cross-sections),
else BODY when its centroid x < bodyMaxX (the torso side) or y > bodyBehindY (behind the arm: hip and coat skirt);
the crossbow and anything outboard in front stay as they are. "neutralDominant": faces whose three corners are all
dominated by one of these bones (the crossbow on LeftHand) are never BODY, so bodyMaxX/bodyBehindY can be opened up. The
mesh is ripped along every edge between an ARM and a BODY face (bmesh split_edges), so each side owns its own
corner vertices; then a vertex only on ARM faces drops every non-arm bone and one only on BODY faces drops the arm
bones (renormalised; rigid vertices and vertices that would be emptied keep their weights). A per-vertex test cannot
do this: a face spanning the contact keeps an arm-to-torso edge whatever is split around it.

Config: "armSep": {"armBones": ["LeftArm", "LeftForeArm", "LeftHand"],
                   "axis": [[x, y, z], ...] Blender build space, "radius": [r per axis point], "margin": 0.012,
                   "low": 0.45, "top": 1.0, "ramp": 0.06, "bodyMaxX": 0.19, "bodyBehindY": 0.08,
                   "side": "left"}
"side": "left" (default) = an arm on the +x side, torso where x < bodyMaxX; "right" = an arm on the -x side, torso where
x > -bodyMaxX (bodyMaxX is given as the same positive distance either way). armBones / axis must name that side.
"elbowHandoff": {"z": 0.79, "ramp": 0.06} (optional, off by default) moves upper-arm weight on arm-only vertices below the
elbow height z to the forearm (ramped), so a sleeve underside bound to the upper arm does not fan out when the elbow opens;
its optional "smooth": {"band": [zlo, zhi], "iterations": 20, "alpha": 0.5} then Laplacian-smooths the upper/forearm
split of arm-only vertices in that band, so short edges across the ramp do not tear at the bent elbow.
"armSep" may also be a list of such dicts (both arms): the cuts run in order, each on the mesh the previous one left.
The cut is full between low + ramp and top - ramp and fades out linearly to both band ends (no split there: the two
sides still share bones), so the sleeve top / armpit and the hand / thigh contact keep a smooth blend.
A whole mesh piece rigid (weight 1) to a bone of the wrong side (hip/coat pieces bone heat made rigid to the upper
arm) copies, vertex by vertex, the weights of the nearest non-rigid vertex on its own side.
A vertex on one side only that carries no bone of that side at all (hip-weighted corners of ARM faces, where Meshy's
6-9 cm triangles straddle the contact) copies the weights of the nearest vertex of its own piece that does, within
"orphanReach" (default 0.12), blended by the band fade; it touches no face of the other side, so nothing tears.
List it after castle_islandbind (rigid island binds are skipped as rigid).
"""
import bmesh
import numpy as np


def _components(n, E):
    par = np.arange(n)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a, b in E.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb
    return np.array([find(i) for i in range(n)])


def _polyd(P, A, R):
    best = np.full(len(P), np.inf); rr = np.zeros(len(P))
    for k in range(len(A) - 1):
        a, b = A[k], A[k + 1]; ab = b - a
        t = np.clip(((P - a) @ ab) / float(ab @ ab), 0, 1)
        d = np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
        m = d < best; best[m] = d[m]; rr[m] = (R[k] + t * (R[k + 1] - R[k]))[m]
    return best, rr


def _shell_classes(bm, opt, vg, armidx, band, isneu):
    """"shell": {"share": t} (necropolis wight/wraith sleeves, 2026-10-10) replaces the axis/bodyMaxX face test. The arm
    shell is flooded over mesh edges from the hand (vertices dominated by armBones[-1]) through vertices whose bone-heat
    share of armBones exceeds t; a sleeve hanging beside a robe is not a tube about one axis, so a radius test either
    misses it or takes the robe. In the band, a face with a majority of shell corners is ARM, every other face BODY
    (neutralDominant faces excepted), so the rip follows the whole shell boundary."""
    t = float(opt["shell"].get("share", 0.4))
    dl0 = bm.verts.layers.deform.verify(); bm.verts.ensure_lookup_table()
    hand = vg[opt["armBones"][-1]].index
    nv = len(bm.verts); share = np.zeros(nv); dom = np.full(nv, -1)
    for v in bm.verts:
        dw = dict(v[dl0].items()); tot = sum(dw.values())
        if tot > 0:
            share[v.index] = sum(w for k, w in dw.items() if k in armidx) / tot
            dom[v.index] = max(dw.items(), key=lambda kv: kv[1])[0]
    # loose parts (a hand modelled apart from its sleeve) touch only at coincident vertices: flood across those too
    P = np.round(np.array([v.co[:] for v in bm.verts]) / 1e-4).astype(np.int64)
    _, wid = np.unique(P, axis=0, return_inverse=True); wid = wid.ravel()
    twins = {}
    for i, w in enumerate(wid):
        twins.setdefault(int(w), []).append(i)
    inn = np.zeros(nv, bool)
    st = [i for i in range(nv) if dom[i] == hand and share[i] > t]
    inn[st] = True
    while st:
        i = st.pop(); v = bm.verts[i]
        for o in [e.other_vert(v).index for e in v.link_edges] + twins[int(wid[i])]:
            if not inn[o] and share[o] > t:
                inn[o] = True; st.append(o)
    zc = np.array([v.co[2] for v in bm.verts])
    zb = (zc > opt.get("low", 0.45)) & (zc < opt.get("top", 1.0))
    print("REGION castle_armsep: band vertices with arm share >", t, int((zb & (share > t)).sum()), "of", int(zb.sum()),
          "; shell z", (round(float(zc[inn].min()), 3), round(float(zc[inn].max()), 3)) if inn.any() else None)
    frac = np.array([np.mean([inn[v.index] for v in f.verts]) for f in bm.faces])
    if inn.sum() < opt["shell"].get("minVerts", 0):
        raise SystemExit(f"castle_armsep: shell has {int(inn.sum())} vertices, under minVerts {opt['shell']['minVerts']}")
    print("REGION castle_armsep: shell vertices", int(inn.sum()), "share >", t)
    return np.where(band & (frac > 0.5), 1, np.where(band & ~isneu, 2, 0))


def after_skin(g):
    """"armSep" is one cut (dict) or several (list of dicts, e.g. both arms), applied in order; each cut reads the mesh
    and weights the previous one left (its own bmesh round trip, so vertex indices are fresh)."""
    opt = g["cfg"].get("armSep")
    if not opt:
        return
    for o in (opt if isinstance(opt, list) else [opt]):
        _cut(g, o)


def _cut(g, opt):
    print("REGION castle_armsep: cut", opt.get("side", "left"), opt["armBones"])
    body = g["body"]; me = body.data; vg = body.vertex_groups
    arm = [b for b in opt["armBones"] if b in vg]
    if len(arm) != len(opt["armBones"]):
        raise SystemExit(f"castle_armsep: arm bones without a vertex group: {set(opt['armBones']) - set(arm)}")
    armidx = {vg[b].index for b in arm}
    gname = {x.index: x.name for x in vg}
    A = np.array(opt.get("axis", [[0, 0, 0], [0, 0, 1]]), float); R = np.array(opt.get("radius", [0, 0]), float)
    top = opt.get("top", 1.0); low = opt.get("low", 0.45); ramp = opt.get("ramp", 0.06)
    margin = opt.get("margin", 0.012); xmax = opt.get("bodyMaxX", 0.19); yb = opt.get("bodyBehindY", 9.0)
    side = opt.get("side", "left")
    if side not in ("left", "right"):
        raise SystemExit(f"castle_armsep: side must be 'left' or 'right', got {side!r}")
    sx = 1.0 if side == "left" else -1.0   # mirror the torso-side x test for a right arm
    # 1) class every face by its centroid (ARM / BODY / neither), then rip the mesh along the ARM|BODY face boundary:
    #    a face spanning the contact keeps all three corners on its own side, so the cut follows face edges.
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    C = np.array([f.calc_center_median()[:] for f in bm.faces])
    d, r = _polyd(C, A, R)
    band = (C[:, 2] > low) & (C[:, 2] < top)
    neu = {vg[b].index for b in opt.get("neutralDominant", []) if b in vg}
    if neu:   # faces whose corners are all dominated by a neutral bone (the crossbow on LeftHand) stay as they are
        dl0 = bm.verts.layers.deform.verify()
        vdom = {v.index: (max(v[dl0].items(), key=lambda t: t[1])[0] if v[dl0] else -1) for v in bm.verts}
        isneu = np.array([all(vdom[v.index] in neu for v in f.verts) for f in bm.faces])
    else:
        isneu = np.zeros(len(C), bool)
    if opt.get("shell"):
        fc = _shell_classes(bm, opt, vg, armidx, band, isneu)
    else:
        fc = np.where(band & (d < r + margin), 1, np.where(band & ~isneu & ((sx * C[:, 0] < xmax) | (C[:, 1] > yb)), 2, 0))
    cut = [e for e in bm.edges if len(e.link_faces) == 2
           and {int(fc[e.link_faces[0].index]), int(fc[e.link_faces[1].index])} == {1, 2}]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.verts.index_update(); bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()   # ripped copies get real indices
    # crack ends: a vertex still on both ARM and BODY faces (the two fans meet through a neutral face or only at the
    # corner, so no ARM|BODY edge exists there) -- rip every ARM|non-ARM edge around it as well
    ce = [v for v in bm.verts if {1, 2} <= {int(fc[f.index]) for f in v.link_faces}]
    cut2 = list({e for v in ce for e in v.link_edges if len(e.link_faces) == 2
                 and (int(fc[e.link_faces[0].index]) == 1) != (int(fc[e.link_faces[1].index]) == 1)})
    if cut2:
        bmesh.ops.split_edges(bm, edges=cut2)
        bm.verts.index_update(); bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    print("REGION castle_armsep: crack-end vertices", len(ce), "extra cut edges", len(cut2))
    vcls = {}
    for f in bm.faces:
        for v in f.verts:
            vcls.setdefault(v.index, set()).add(int(fc[f.index]))
    bm.to_mesh(me); bm.free()
    # 2) weights: a vertex only on ARM faces drops the non-arm bones, one only on BODY faces drops the arm bones,
    #    faded out toward both band ends (by vertex height) so the armpit and hand/thigh blends stay smooth.
    P = np.array([v.co[:] for v in me.vertices]); z = P[:, 2]
    n_arm = n_body = 0
    for v in me.vertices:
        i = v.index; cl = vcls.get(i, set()) - {0}
        if len(cl) != 1:
            continue
        is_arm = cl == {1}
        ws = {x.group: x.weight for x in v.groups}
        if not ws or max(ws.values()) >= 0.999:
            continue
        keep = {k: w for k, w in ws.items() if (k in armidx) == is_arm}
        if len(keep) == len(ws) or sum(keep.values()) < 1e-4:
            continue
        f = float(np.clip(min(top - z[i], z[i] - low) / ramp, 0, 1))
        new = {k: (w if k in keep else w * (1 - f)) for k, w in ws.items()}
        s = sum(new.values())
        for k, w in new.items():
            if w > 1e-6:
                vg[gname[k]].add([i], w / s, 'REPLACE')
            else:
                vg[gname[k]].remove([i])
        if is_arm:
            n_arm += 1
        else:
            n_body += 1
    # 3) vertices rigid (weight 1) to a bone of the WRONG side -- bone heat made whole hip/coat pieces rigid to the upper
    #    arm, and step 2 cannot drop their only bone -- copy the weights of the nearest non-rigid vertex of their side
    #    (dominant bone on that side), faded like step 2 is not possible for a single bone, so only inside the full band.
    E = np.array([e.vertices[:] for e in me.edges]).reshape(-1, 2)
    dom = {}; rigid = set()
    for v in me.vertices:
        if v.groups:
            gmax = max(v.groups, key=lambda gr: gr.weight); dom[v.index] = gmax.group
            if gmax.weight >= 0.999:
                rigid.add(v.index)
    n_adopt = 0
    for side, want_arm in ((1, True), (2, False)):
        tgt = [i for i in rigid if vcls.get(i, set()) - {0} == {side} and (dom[i] in armidx) != want_arm
               and low + ramp <= z[i] <= top - ramp]
        host = np.array([i for i, gi in dom.items() if i not in rigid and (gi in armidx) == want_arm
                         and vcls.get(i, set()) - {0} == {side}])
        if not tgt or not len(host):
            continue
        # whole pieces only: a piece that also has vertices outside the target set keeps them all (adopting part of
        # it would tear it along the boundary)
        tset = set(tgt); piece = _components(len(P), E)
        whole = {c for c in set(piece[tgt].tolist()) if all(k in tset for k in np.flatnonzero(piece == c).tolist())}
        tgt = [i for i in tgt if piece[i] in whole]
        for i in tgt:
            j = int(host[np.argmin(np.linalg.norm(P[host] - P[i], axis=1))])
            ws = [(gr.group, gr.weight) for gr in me.vertices[j].groups]
            for gr in list(me.vertices[i].groups):
                vg[gname[gr.group]].remove([i])
            for k, w in ws:
                vg[gname[k]].add([i], w, 'REPLACE')
            n_adopt += 1
    # 4) vertices on one side carrying no bone of that side at all (body-only weights inside ARM faces, arm-only weights
    #    inside BODY faces): step 2 cannot drop their bones, so they copy the weights of the nearest vertex of the SAME
    #    piece that does carry a bone of their side (a neighbour, so the piece is not torn along a new boundary),
    #    blended by the band fade.
    #    Passes repeat with the host set refreshed (an orphan adopted in one pass hosts its neighbours in the next), so
    #    a fan of orphans fills in from its nearest real host outward instead of failing on the reach limit.
    piece = _components(len(P), E)
    n_orph = 0; reach = opt.get("orphanReach", 0.12)   # Meshy triangles at the hip contact span 6-9 cm
    for side, want_arm in ((1, True), (2, False)):
        sidev = np.array([vcls.get(i, set()) - {0} == {side} for i in range(len(P))])
        for _pass in range(8):
            ok = np.array([any((gr.group in armidx) == want_arm and gr.weight > 0.05 for gr in v.groups) for v in me.vertices])
            todo = []
            for i in np.flatnonzero(sidev & ~ok).tolist():
                f = float(np.clip(min(top - z[i], z[i] - low) / ramp, 0, 1))
                cand = np.flatnonzero((piece == piece[i]) & ok & sidev)
                if f <= 0 or not len(cand):
                    continue
                j = int(cand[np.argmin(np.linalg.norm(P[cand] - P[i], axis=1))])
                if np.linalg.norm(P[j] - P[i]) <= reach:
                    todo.append((i, j, f))
            if not todo:
                break
            for i, j, f in todo:
                old = {gr.group: gr.weight for gr in me.vertices[i].groups}
                hw = {gr.group: gr.weight for gr in me.vertices[j].groups}
                new = {k: old.get(k, 0) * (1 - f) + hw.get(k, 0) * f for k in set(old) | set(hw)}
                s_ = sum(new.values())
                for k, w in new.items():
                    if w > 1e-6:
                        vg[gname[k]].add([i], w / s_, 'REPLACE')
                    elif k in old:
                        vg[gname[k]].remove([i])
                n_orph += 1
    print("REGION castle_armsep: side-orphan vertices adopted from their piece", n_orph)
    # 5) optional "elbowHandoff": {"z": elbow height, "ramp": m}. Arm-only vertices (all weight on armBones) below the
    #    elbow carry upper-arm weight wherever bone heat or the adoptions above gave them a LeftArm host; when the elbow
    #    straightens (crossbowman ShootFront) they swing about the shoulder instead of the elbow and fan out as dark
    #    spikes under the sleeve. Their armBones[0] weight moves to armBones[1], fully below z - ramp, fading to none at z.
    eh = opt.get("elbowHandoff")
    n_hand = 0
    if eh:
        up, lo = vg[opt["armBones"][0]].index, vg[opt["armBones"][1]].index
        z0, er = float(eh["z"]), float(eh.get("ramp", 0.06))
        for v in me.vertices:
            gw = {gr.group: gr.weight for gr in v.groups}
            if up not in gw or sum(w for k, w in gw.items() if k in armidx) < 0.999 * sum(gw.values()):
                continue
            k_ = float(np.clip((z0 - v.co.z) / er, 0, 1))
            if k_ <= 0:
                continue
            mv = gw[up] * k_
            if gw[up] - mv > 1e-6:
                vg[gname[up]].add([v.index], gw[up] - mv, 'REPLACE')
            else:
                vg[gname[up]].remove([v.index])
            vg[gname[lo]].add([v.index], gw.get(lo, 0.0) + mv, 'REPLACE')
            n_hand += 1
    # 5b) optional "elbowHandoff.smooth": {"band": [zlo, zhi], "iterations": n, "alpha": a}. The ramp above leaves a
    #    hard upper/forearm step next to vertices bone heat had blended already, and short edges across it tear at the
    #    bent elbow (Death, Move). Laplacian-smooth the armBones[0]/[1] split of arm-only vertices in the band over
    #    edges between arm-only vertices (the cut keeps body vertices out); coincident copies share one value.
    sm = (eh or {}).get("smooth")
    n_sm = 0
    if sm:
        zlo, zhi = map(float, sm["band"])
        its, al = int(sm.get("iterations", 20)), float(sm.get("alpha", 0.5))
        nv = len(me.vertices)
        D = np.zeros((nv, 2)); armw = np.zeros(nv); tot = np.zeros(nv); Z = np.zeros(nv)
        CO = np.zeros((nv, 3))
        for v in me.vertices:
            Z[v.index] = v.co.z; CO[v.index] = v.co[:]
            for gr in v.groups:
                tot[v.index] += gr.weight
                if gr.group in armidx:
                    armw[v.index] += gr.weight
                if gr.group == up:
                    D[v.index, 0] = gr.weight
                elif gr.group == lo:
                    D[v.index, 1] = gr.weight
        armonly = (tot > 0) & (armw >= 0.999 * tot)
        ab = D.sum(1)
        free = armonly & (Z > zlo) & (Z < zhi) & (ab > 0.01 * np.maximum(tot, 1e-9))
        E = np.array([e.vertices[:] for e in me.edges]); E = E[armonly[E].all(1)]
        _, grp = np.unique(np.round(CO, 5), axis=0, return_inverse=True); grp = grp.ravel(); ng = grp.max() + 1
        fr = D[:, 1] / np.maximum(ab, 1e-9)
        for _ in range(its):
            s = np.zeros(nv); c = np.zeros(nv)
            for a_, b_ in ((0, 1), (1, 0)):
                np.add.at(s, E[:, a_], fr[E[:, b_]]); np.add.at(c, E[:, a_], 1)
            nf = np.where(free, (1 - al) * fr + al * np.where(c > 0, s / np.maximum(c, 1), fr), fr)
            gm = np.bincount(grp, nf * free, minlength=ng) / np.maximum(np.bincount(grp, free.astype(float), minlength=ng), 1e-9)
            fr = np.where(free, gm[grp], fr)
        for i in np.flatnonzero(free):
            wu, wl = float(ab[i] * (1 - fr[i])), float(ab[i] * fr[i])
            if abs(wu - D[i, 0]) < 1e-6 and abs(wl - D[i, 1]) < 1e-6:
                continue
            for b_, w_ in ((up, wu), (lo, wl)):
                if w_ > 1e-6:
                    vg[gname[b_]].add([int(i)], w_, 'REPLACE')
                else:
                    vg[gname[b_]].remove([int(i)])
            n_sm += 1
    print("REGION castle_armsep: elbow handoff vertices", n_hand, "smoothed", n_sm)
    print("REGION castle_armsep: wrong-side rigid vertices adopted", n_adopt)
    print("REGION castle_armsep: vertices left on both sides (crack ends)", sum(1 for c in vcls.values() if {1, 2} <= c))
    print("REGION castle_armsep: faces arm", int((fc == 1).sum()), "body", int((fc == 2).sum()), "cut edges", len(cut),
          "reweighted arm verts", n_arm, "body verts", n_body)
