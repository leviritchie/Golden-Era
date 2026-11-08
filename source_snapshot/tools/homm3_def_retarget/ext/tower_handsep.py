"""Tower: free a hand that Meshy fused to the robe (h3_mage: right fist clasped on a belt pouch;
robe tied to the staff hand by heat through the staff).

Bone heat blends the fist and the pouch/robe it rests on (about half hand, half Hips), so when
the arm lifts the robe front is dragged up into a sheet and the fist is held back by the robe.
after_skin, config "handSep": [{"hand": "RightHand", "center": [x, y, z], "radius": r,
                                "seedRadius": 0.035, "armKeep": 0.8, "gate": {...}}]
  * the hand = flood fill over mesh edges from the vertices within seedRadius of `center`,
    through vertices within `radius` whose texture colour passes the skin gate (R > minR,
    minGR < G/R < maxGR, minBR < B/R < maxBR) -- or, with "bodyBones": [...], whose nearest
    bone segment is in the hand's chain rather than one of those body bones; flooded vertices take the arm chain only
    (Arm/ForeArm/Hand, inverse-distance^4 to the bone segments, as the armCut rule does);
  * every other non-rigid vertex within `radius` that mixes arm and body goes wholly to one side:
    arm-chain share >= armKeep (cuff, an unflooded knuckle) keeps only the arm, otherwise
    (pouch, robe under the fist) only the body;
config "chainSep": [{"chains": [[...], [...]], "center": c, "radius": r}]: inside the sphere a vertex blended
between two arm chains keeps only the larger one (two arms laid side by side), and the faces split between them
("split": false: reweight only, e.g. an upper arm heat-bound into the low shoulder under it);
"gateAll": true takes every gated vertex in the radius as the hand (rigid ones too, no flood over edges);
"rigid": true binds the entry's hand vertices wholly to the hand bone (a held prop such as a sword hilt);
"splitAll": true also opens pure-hand / pure-body welds inside the radius: every vertex there joins the face split;
config "handSepChains": true: every arm chain an entry names is an arm side of its own (low arms included), so faces
split between different arm chains as well as between arm and body;
config "armStrip": [{"chain": [...], "belowZ": z, "armKeep": 0.8}]: non-rigid vertices below
belowZ whose share of `chain` is under armKeep lose it (robe tied to a hand through a fused prop);
an entry with "center" + "radius" strips inside that sphere instead of below belowZ (armKeep > 1 strips every share);
then each face at a reweighted vertex goes to the arm or the body side (majority of its corners),
edges between faces of different sides are split, and a corner left on the other side's faces
takes a same-face donor's weights, so the contact opens instead of stretching (and the
corrective-smooth bake cannot drag the robe after the hand).
Each vertex keeps at most 4 bone weights, renormalised.
"""
import bmesh
import numpy as np


def _segdist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


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
    i = int(i)
    """Replace vertex i's weights with ws (dict bone->w), top 4, renormalised."""
    top = sorted(((w, k) for k, w in ws.items() if w > 1e-5), reverse=True)[:4]
    s = sum(w for w, _ in top)
    for g in vg:
        g.remove([i])
    for w, k in top:
        vg[k].add([i], w / s, 'REPLACE')


def after_skin(g):
    body, cfg, BONES, J = g["body"], g["cfg"], g["BONES"], g["J"]
    specs, strips = cfg.get("handSep", []), cfg.get("armStrip", [])
    seps = cfg.get("chainSep", [])
    if not specs and not strips and not seps:
        return
    me = body.data
    vg = body.vertex_groups
    gname = {x.index: x.name for x in vg}
    P = np.array([v.co[:] for v in me.vertices])
    seg = {b: (np.array(J[h]), np.array(J[t])) for b, h, t, _ in BONES}
    adj = [[] for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b); adj[b].append(a)
    W = [{gname[x.group]: x.weight for x in v.groups} for v in me.vertices]
    rigid = np.array([bool(w) and max(w.values()) >= 0.999 for w in W])
    done = set()
    split_only = set()
    C = _colors(me) if specs else None
    for sp in specs:
        side = sp["hand"].replace("Hand", "")
        chain = [side + b for b in ("Arm", "ForeArm", "Hand")]
        c = np.array(sp["center"]); R = sp["radius"]; keep = sp.get("armKeep", 0.8)
        gt = sp.get("gate", {})
        r, gg, bb = C[:, 0], C[:, 1], C[:, 2]
        rs = np.maximum(r, 1e-6)
        skin = ((r > gt.get("minR", 0.4)) & (gg / rs > gt.get("minGR", 0.6)) & (gg / rs < gt.get("maxGR", 0.88))
                & (bb / rs > gt.get("minBR", 0.4)) & (bb / rs < gt.get("maxBR", 0.8)))
        dc = np.linalg.norm(P - c, axis=1)
        if "bodyBones" in sp:
            # skin the same colour as the body (naga): the hand is what lies nearer the hand
            # chain than any listed body bone, instead of what passes the colour gate
            cand = chain + [b for b in sp["bodyBones"] if b in seg]
            dn = [_segdist(P, *seg[b]) for b in cand]
            TP = g.get("TPts")
            if "Tail" in sp["bodyBones"] and TP is not None and len(TP) > 1:   # naga coil centreline
                TP = np.asarray(TP, float)
                dn += [_segdist(P, TP[k], TP[k + 1]) for k in range(len(TP) - 1)]
            dn = np.stack(dn, 1)
            skin = dn.argmin(1) < len(chain)
        if sp.get("gateAll"):
            # "gateAll": true -- every vertex in the radius that passes the gate, rigid ones included and without a
            # flood (a sword pommel Meshy split across UV seams and heat bound rigidly to another arm's hand)
            ok = skin & (dc < R)
            front = []; hand = {int(i) for i in np.nonzero(ok)[0]}
        else:
            ok = skin & (dc < R) & ~rigid
            front = [i for i in np.nonzero(ok & (dc < sp.get("seedRadius", 0.035)))[0]]
            hand = set(front)
        while front:
            nxt = []
            for i in front:
                for j in adj[i]:
                    if j not in hand and ok[j]:
                        hand.add(j); nxt.append(j)
            front = nxt
        dd = np.stack([_segdist(P, *seg[b]) for b in chain], 1)
        aw = 1.0 / np.maximum(dd, 0.02) ** 4; aw /= aw.sum(1, keepdims=True)
        for i in hand:
            if sp.get("rigid"):    # "rigid": true -- a held prop (sword hilt) moves wholly with the hand bone
                _set(vg, i, {sp["hand"]: 1.0})
            else:
                _set(vg, i, {b: float(aw[i, k]) for k, b in enumerate(chain)})
        done |= hand
        n_arm = n_body = 0
        for i in np.nonzero((dc < R) & ~rigid)[0]:
            if i in hand:
                continue
            ws = W[i]
            arm = sum(w for k, w in ws.items() if k in chain)
            if arm <= 1e-4 or arm >= 1 - 1e-4:
                continue
            if arm >= keep:            # cuff / unflooded knuckle: arm only
                _set(vg, i, {k: w for k, w in ws.items() if k in chain}); n_arm += 1
            else:                      # pouch / robe under the fist: body only
                rest = {k: w for k, w in ws.items() if k not in chain}
                _set(vg, i, rest if sum(rest.values()) > 1e-4 else {"Hips": 1.0}); n_body += 1
            done.add(int(i))
        print("HOOK tower handsep", sp["hand"], "hand verts", len(hand), "to arm", n_arm, "to body", n_body)
        if sp.get("splitAll"):
            # "splitAll": true -- every vertex within the radius takes part in the face split below, not only the
            # reweighted ones: a hand welded to skin it was never blended with (pure-hand corners meeting pure-body
            # corners) is cut too, so the corrective-smooth bake cannot drag the fingers after the body
            split_only |= {int(i) for i in np.nonzero(dc < R)[0]}
    touched = set(done)
    # armStrip: [{"chain": [...], "belowZ": z, "armKeep": 0.8}] -- robe cloth that heat tied to a
    # hand through a fused prop or fist loses that chain's weight below belowZ
    for st in strips:
        chain = set(st["chain"]); keep = st.get("armKeep", 0.8); n = 0
        # "center" + "radius" (opt-in): a sphere instead of the belowZ slab -- a fist Meshy fused onto the hip
        # that belongs to no rigged arm (naga's stub third arm) goes wholly to the body with armKeep > 1
        if "center" in st:
            region = np.linalg.norm(P - np.array(st["center"]), axis=1) < st["radius"]
        else:
            region = P[:, 2] < st["belowZ"]
        for i in np.nonzero(region & (~rigid | (keep > 1)))[0]:   # armKeep > 1 also takes a rigid fused fist
            if int(i) in done:
                continue
            ws = W[i]
            arm = sum(w for k, w in ws.items() if k in chain)
            if arm <= 1e-4 or arm >= keep:
                continue
            rest = {k: w for k, w in ws.items() if k not in chain}
            _set(vg, i, rest if sum(rest.values()) > 1e-4 else {"Hips": 1.0}); n += 1
            touched.add(int(i))
        print("HOOK tower armstrip", sorted(chain), "stripped", n)
    # chainSep: [{"chains": [[...], [...]], "center": c, "radius": r}] -- two arms Meshy laid side by side (the naga's
    # upper-left forearm along the low-left upper arm) that heat blended into each other: inside the sphere a vertex
    # carrying both chains keeps only the chain with the larger share (plus any body weight), and joins the face split
    for cs in seps:
        ca, cb = (set(x) for x in cs["chains"]); n = 0
        for i in np.nonzero(np.linalg.norm(P - np.array(cs["center"]), axis=1) < cs["radius"])[0]:
            if int(i) in done:
                continue
            ws = {gname[x.group]: x.weight for x in me.vertices[int(i)].groups}
            a = sum(w for k, w in ws.items() if k in ca); b = sum(w for k, w in ws.items() if k in cb)
            if a <= 1e-4 or b <= 1e-4:
                continue
            drop = cb if a >= b else ca
            _set(vg, i, {k: w for k, w in ws.items() if k not in drop}); n += 1
            if cs.get("split", True):      # "split": false -- reweight only (a shoulder root must not open)
                touched.add(int(i))
        print("HOOK tower chainsep", sorted(ca)[0], "|", sorted(cb)[0], "separated", n)
    touched |= split_only
    # open every contact at a reweighted vertex: each face there goes to the arm or the body side
    # (majority of its corners with / without arm weight), edges between faces of different sides
    # are split, and a corner left on the other side's faces takes a same-face donor's weights --
    # so the contact opens instead of stretching and the corrective-smooth bake cannot drag the
    # robe after the hand
    bm = bmesh.new(); bm.from_mesh(me)
    dl = bm.verts.layers.deform.verify()
    # the arm side: the main arms; with "handSepChains" also every chain a handSep / armStrip entry names (a naga's
    # LowLeft / LowRight arms -- without it those count as body, so a low hand's faces never split from the hips)
    armn = {s_ + b for s_ in ("Left", "Right") for b in ("Arm", "ForeArm", "Hand")}
    if cfg.get("handSepChains"):
        armn |= {sp["hand"].replace("Hand", "") + b for sp in specs for b in ("Arm", "ForeArm", "Hand")}
        armn |= {b for st in strips for b in st["chain"]}
        armn |= {b for cs in seps if cs.get("split", True) for ch in cs["chains"] for b in ch if "Shoulder" not in b}
    armg = {vg[n].index for n in armn if n in vg}
    if cfg.get("handSepChains"):
        # "handSepChains": true -- each arm chain is its own side (a hand resting on another arm's hand, as the naga's
        # upper right hand on the low right one, is cut from it too): a vertex's side is the chain carrying most of
        # its arm weight, "" without arm weight
        chain_of = {vg[n].index: n.replace("ForeArm", "").replace("Arm", "").replace("Hand", "") for n in armn if n in vg}

        def hasarm(v):
            sh = {}
            for k, w in v[dl].items():
                if k in chain_of and w > 1e-3:
                    sh[chain_of[k]] = sh.get(chain_of[k], 0.0) + w
            return max(sh, key=sh.get) if sh else ""
    else:
        hasarm = lambda v: any(k in armg and w > 1e-3 for k, w in v[dl].items())
    side = {}
    for f in bm.faces:
        if not any(v.index in touched for v in f.verts):
            continue
        # majority of its corners: the arm (or, per chain, the most common arm chain) when it holds at least half
        arms = [x for x in (hasarm(v) for v in f.verts) if x]
        top = max(set(arms), key=arms.count) if arms else None
        held = top is not None and arms.count(top) * 2 >= len(f.verts)
        side[f.index] = (top if held else "") if cfg.get("handSepChains") else held
    cut = [e for e in bm.edges if len(e.link_faces) == 2
           and all(f.index in side for f in e.link_faces)
           and side[e.link_faces[0].index] != side[e.link_faces[1].index]]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.faces.ensure_lookup_table()
    fixed = 0
    for v in bm.verts:
        fs = [f for f in v.link_faces if f.index in side]
        if not fs or len(fs) != len(v.link_faces):
            continue
        sides = {side[f.index] for f in fs}
        if len(sides) != 1 or sides == {hasarm(v)}:
            continue
        want = sides.pop()
        donors = [u for f in fs for u in f.verts if u is not v and hasarm(u) == want]
        if not donors:
            continue
        d = min(donors, key=lambda u: (u.co - v.co).length)
        src = dict(d[dl].items()); dv = v[dl]; dv.clear()
        for k, w in src.items():
            dv[k] = w
        fixed += 1
    bm.to_mesh(me); bm.free()
    print("HOOK tower handsep split edges", len(cut), "straddling corners reassigned", fixed)
