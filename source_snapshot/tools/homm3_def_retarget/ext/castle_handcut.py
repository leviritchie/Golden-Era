"""Castle: cut hands (and forearms) that Meshy fused to the body free of it.

A Meshy hand resting on the hip (archer) or hanging against a tunic/thigh is fused to it, so bone
heat lets the hand own a patch of tunic/belt and the body own part of the hand; when the arm lifts
the patch tears off in long shards. after_skin, per configured side:
  1. ARM vertices = near the Hand segment and skin-like in colour, or near the ForeArm segment and
     not cloth-coloured (config radii / colour rules below). Rigid regions (props) are left alone.
  2. Every other vertex loses its Hand/ForeArm weight on that side; the removed share is replaced by
     the weights of the nearest vertex that carries no such weight (torso/skirt around the patch).
  3. ARM vertices lose any non-arm-chain weight (the hand moves only with the arm).
  4. Edges between all-ARM faces and faces touching a vertex that is not arm-driven after step 2
     (arm-chain weight < 0.5) are split, so the hand leaves the hip cleanly instead of tearing it.
Weights are limited to 4 per vertex and normalised.

Config "castleHandCut": {"sides": ["Right", "Left"], "handRadius": 0.1, "foreRadius": 0.07,
  "skin": {"minRedOverBlue": 0.12, "minLum": 0.3}, "cloth": {"blueOverRed": 0.05, "whiteLum": 0.6},
  "foreMinLum": 0.15, "perSide": {"Right": {"handRadius": ...}} (optional overrides),
  "adopt": {"pairs": [[dst_xyz, src_xyz], ...]} (optional; fused vertices that take a neighbour's arm weights),
  "adopt": {"fused": [xyz, ...], "radius": m} (optional; heat-order-robust form, see adopt_fused),
  "upperRadius": m, "upperMinArm": 0.35 (optional; upper-arm band vertices that join the arm cut),
  "farStrip": {"dist": m, "maxHeight": m} (optional; arm weight leaked onto body vertices far from the arm is removed)}
"""
import numpy as np


def adopt_fused(P, aw, spots, radius=0.03, tol=0.002, min_arm=0.7):
    """"adopt": {"fused": [xyz, ...], "radius": r} (authenticity h3_champion 2026-10-07). The armoured gauntlet
    fails the skin/colour arm test, and bone heat fuses one glove vertex to Hips; but WHICH of the listed glove
    vertices carries the fused row changes with any mesh edit elsewhere (the heat solve is global). The fixed
    dst <- src "pairs" form then copied a fused Hips .91 row (after neck surgery the fused one was src) and tore the
    Hitted twist 8.8x. Rule by position and arm share, not vertex identity: each spot vertex (and its coincident
    UV-seam copies) joins the arm; one whose arm share is < 0.5 takes the row of the nearest arm-dominant vertex
    (share >= min_arm) within `radius`. Returns (members, {vertex: donor}). Only spot vertices join: a whole
    glove ball in the arm tore the lunges 15x more (2026-10-07 authB 567 vs 37 reel edges).
    P (n,3) positions, aw (n,) arm-chain share."""
    P = np.asarray(P, float); aw = np.asarray(aw, float)
    mem = np.zeros(len(P), bool)
    for s_ in spots:
        d = np.linalg.norm(P - np.asarray(s_, float), axis=1)
        if d.min() > tol:
            raise SystemExit(f"castleHandCut.adopt.fused: spot {s_} matches no vertex within {tol} m")
        mem |= d < 1e-5 + d.min()
    members = np.nonzero(mem)[0]; ok = aw >= min_arm; out = {}
    for v in members[aw[members] < 0.5]:
        d = np.linalg.norm(P - P[v], axis=1); c = ok & (d < radius)
        if c.any():
            out[int(v)] = int(np.nonzero(c)[0][np.argmin(d[c])])
    return members.tolist(), out


def after_skin(g):
    cfg = g["cfg"]["castleHandCut"]
    bmesh, body, J, owners, widx = g["bmesh"], g["body"], g["J"], g["owners"], g["widx"]
    C = np.load(g["OUT"] + ".heat.npz")["C"]
    vg = body.vertex_groups; gname = {x.index: x.name for x in vg}; gid = {x.name: x.index for x in vg}
    V = body.data.vertices; n = len(V)
    P = np.array([v.co[:] for v in V]); Cv = np.array([C[widx(v.co)] for v in V])
    lum = Cv.mean(1); rb = Cv[:, 0] - Cv[:, 2]
    rows = [{gname[x.group]: x.weight for x in v.groups if x.weight > 0} for v in V]
    # rigid = inside a prop region AND bound 100% to one bone (split_region leaves a heat-weighted
    # twin of each boundary vertex at the same position, which must still be processed)
    rigid = np.array([max(rows[v.index].values(), default=0) > 0.999
                      and any(own(v.co) is not None for _, own in owners) for v in V])

    def sd(a, b):
        a, b = np.array(a), np.array(b); ab = b - a
        t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(P - a - t[:, None] * ab, axis=1)

    ARM = np.zeros(n, bool); strip = set(); chains = {}; farstrip = {}
    for side in cfg.get("sides", ["Right", "Left"]):
        c = dict(cfg); c.update(cfg.get("perSide", {}).get(side, {}))
        sk = c.get("skin", {"minRedOverBlue": 0.12, "minLum": 0.3})
        cl = c.get("cloth", {"blueOverRed": 0.05, "whiteLum": 0.6})
        skin = (rb > sk["minRedOverBlue"]) & (lum > sk["minLum"])
        cloth = (-rb > cl.get("blueOverRed", 9)) | (lum > cl.get("whiteLum", 9))
        dh = sd(J[side + "Hand"], J[side + "Hand_End"]); df = sd(J[side + "ForeArm"], J[side + "Hand"])
        arm = (((dh < c.get("handRadius", 0.1)) & skin)
               | ((df < c.get("foreRadius", 0.07)) & ~cloth & (lum > c.get("foreMinLum", 0.15)))) & ~rigid
        for b in ("Hand", "ForeArm"):
            strip.add(side + b)
        chains[side] = {side + b for b in ("Shoulder", "Arm", "ForeArm", "Hand")}
        # "upperRadius"/"upperMinArm" (authenticity h3_champion 2026-10-07): an upper arm hanging against the
        # waist is fused to it and bone heat leaves a band of Arm .5 / Hips .45 vertices next to Arm .87 rows.
        # Any rider lean or fall stretches that band 3-5x on weights alone (the worst-stretch gate and the
        # Death fall's tear budget). Band vertices near the Arm segment that are mostly arm-driven join the arm,
        # so step 4 cuts the upper arm off the waist like the hand.
        if c.get("upperRadius"):
            du = sd(J[side + "Arm"], J[side + "ForeArm"])
            aw = np.array([sum(w for k, w in r.items() if k in chains[side]) / max(sum(r.values()), 1e-9)
                           for r in rows])
            up = (du < c["upperRadius"]) & (aw >= c.get("upperMinArm", 0.35)) & ~rigid & ~arm
            arm = arm | up
            print("REGION castle_handcut", side, "upper-arm band verts", int(up.sum()))
        # "farStrip": {"dist": m, "maxHeight": m} (authenticity h3_champion 2026-10-07): bone heat leaked the upper
        # arm onto the rider's thigh/seat under a hand resting on it (RightArm .5 / Hips .5 rows 12-19 cm from every
        # arm segment, at saddle height). Any arm lift dragged the thigh with it, capping the shield arm and every rider
        # slump at the tear gate. Non-arm vertices farther than dist from the side's Arm/ForeArm/Hand segments and
        # below maxHeight (mesh z) lose that side's Arm/ForeArm/Hand weight; step 2 refills it from the nearest
        # vertex that carries no arm weight.
        fs = c.get("farStrip")
        if fs:
            dmin = np.minimum(np.minimum(sd(J[side + "Arm"], J[side + "ForeArm"]), df), dh)
            far = (dmin > fs["dist"]) & (P[:, 2] < fs.get("maxHeight", 9.0)) & ~rigid & ~arm
            bones = {side + b for b in ("Arm", "ForeArm", "Hand")}
            hit = [i for i in np.nonzero(far)[0] if bones & rows[i].keys()]
            for i in hit:
                farstrip.setdefault(int(i), set()).update(bones)
            print("REGION castle_handcut", side, "farStrip verts", len(hit))
        ARM |= arm
        print("REGION castle_handcut", side, "arm verts", int(arm.sum()))
    armbones = set().union(*chains.values())
    # "adopt": {"pairs": [[dst_xyz, src_xyz], ...], "tol": m} (authenticity h3_champion 2026-10-07): an armoured
    # gauntlet fails the skin test, and bone heat left a Hips .91 vertex inside the champion's right glove, 1 cm
    # from RightHand .78. Every rider lean pulled that edge 12-15x (weights alone) and the corrective-smooth re-bake
    # smeared it over the glove: 25-35 torn edges per lunge, the whole patch-lane tear budget. Each dst vertex
    # (and its coincident UV-seam copies) takes src's weight row and joins the arm (so the cut frees it).
    ad = cfg.get("adopt", {})
    if ad.get("fused"):
        aw_all = np.array([sum(w for k, w in r.items() if k in armbones) / max(sum(r.values()), 1e-9) for r in rows])
        mem, got = adopt_fused(P, aw_all, ad["fused"], ad.get("radius", 0.03), ad.get("tol", 0.002))
        for v, j in got.items():
            rows[v] = dict(rows[j])
        ARM[[v for v in mem if not rigid[v]]] = True
        print("REGION castle_handcut adopt fused", mem, "re-rowed", sorted(got.items()))
    tol = cfg.get("adopt", {}).get("tol", 0.002)
    for d, s_ in cfg.get("adopt", {}).get("pairs", []):
        dd = np.linalg.norm(P - np.array(d), axis=1); ds = np.linalg.norm(P - np.array(s_), axis=1)
        if dd.min() > tol or ds.min() > tol:
            raise SystemExit(f"castleHandCut.adopt: pair {d} <- {s_} matches no vertex within {tol} m")
        src = int(ds.argmin())
        for i in np.nonzero(dd < 1e-5 + dd.min())[0]:
            rows[i] = dict(rows[src]); ARM[i] = True
        print("REGION castle_handcut adopt", np.nonzero(dd < 1e-5 + dd.min())[0].tolist(), "<-", src)
    moved = np.zeros(n)
    for i in range(n):
        if rigid[i]:
            continue
        if ARM[i]:
            keep = {k: w for k, w in rows[i].items() if k in armbones}
            if keep and sum(keep.values()) > 1e-4:
                rows[i] = keep
            continue
        for b in strip | farstrip.get(i, set()):
            w = rows[i].pop(b, 0.0)
            moved[i] += w
    allstrip = strip.union(*farstrip.values()) if farstrip else strip
    donor = [i for i in range(n) if not rigid[i] and not ARM[i] and moved[i] == 0
             and sum(rows[i].values()) > 0.5 and not any(b in rows[i] for b in allstrip)]
    tree = g["kdtree"].KDTree(len(donor))
    for k, i in enumerate(donor):
        tree.insert(V[i].co, k)
    tree.balance()
    for i in np.nonzero(moved > 1e-6)[0]:
        d = rows[donor[tree.find(V[int(i)].co)[1]]]; s = sum(d.values())
        for k, w in d.items():
            rows[i][k] = rows[i].get(k, 0.0) + moved[i] * w / s
    armw = np.array([sum(w for k, w in r.items() if k in armbones) / max(sum(r.values()), 1e-9) for r in rows])
    # write weights
    for i in range(n):
        if rigid[i]:
            continue
        top = sorted(rows[i].items(), key=lambda kv: -kv[1])[:4]; t = sum(w for _, w in top)
        if t <= 0:
            continue
        for x in list(V[i].groups):
            vg[x.group].remove([i])
        for k, w in top:
            vg[k].add([i], w / t, 'REPLACE')
    # split the hand/forearm off body faces. A face belongs to the arm when most of its corners are
    # ARM; corners that end up only in faces of the other side after the split take that side's
    # weights (nearest vertex of that side), so no triangle is left straddling the cut.
    bm = bmesh.new(); bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    armface = {f.index: 2 * sum(ARM[v.index] for v in f.verts) > len(f.verts) for f in bm.faces}
    bodyface = {f.index: any((not ARM[v.index]) and (not rigid[v.index]) and armw[v.index] < 0.5 for v in f.verts)
                for f in bm.faces}
    cut = [e for e in bm.edges if any(armface[f.index] for f in e.link_faces)
           and any(bodyface[f.index] and not armface[f.index] for f in e.link_faces)]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    fside = {}
    for f in bm.faces:   # split_edges keeps face order; new faces are not created
        fside[f.index] = armface.get(f.index, False)
    trees = {}
    for flag in (True, False):
        ids = [i for i in range(n) if ARM[i] == flag and not rigid[i]]
        t_ = g["kdtree"].KDTree(len(ids))
        for k, i in enumerate(ids):
            t_.insert(V[i].co, k)
        t_.balance(); trees[flag] = (t_, ids)
    nfix = 0
    for v in bm.verts:
        if not v.link_faces or v.index < n and rigid[v.index]:
            continue
        sides = {fside[f.index] for f in v.link_faces}
        if len(sides) != 1:
            continue
        side = sides.pop()
        src = v.index if v.index < n else None
        if src is not None and ARM[src] == side:
            continue
        t_, ids = trees[side]; j = ids[t_.find(v.co)[1]]
        d = v[dl]; d.clear()
        top = sorted(rows[j].items(), key=lambda kv: -kv[1])[:4]; tt = sum(w for _, w in top)
        for k, w in top:
            d[gid[k]] = w / tt
        nfix += 1
    bm.to_mesh(body.data); bm.free()
    print("REGION castle_handcut: corners moved to their face side", nfix)
    print("REGION castle_handcut: stripped", int((moved > 1e-6).sum()), "share %.1f" % moved.sum(),
          "split edges", len(cut))
