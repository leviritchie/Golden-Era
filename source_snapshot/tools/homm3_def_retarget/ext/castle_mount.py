"""Castle: mounted units (cavalier, champion, justiciar) -- a horse under a captured rider.

The capture is a human skeleton; for a mounted DEF only its upper body (the rider) means
anything. This extension turns the build into horse + rider:
  * the human legs are left out of the unit config; "Hips" is the rider's pelvis on the saddle
    and carries the whole horse torso (bone heat gives it the barrel, rump and chest);
  * horse legs, neck and tail are "staticChains" in the config (so bone heat weights them), and
    this hook poses them: rigid with the horse body, plus a procedural trot in Move / MoveStart /
    MoveEnd (diagonal pairs, one cycle per Move clip so the loop closes; half amplitude in the
    start/end clips), a neck nod and a body bob at twice the step rate;
  * the rider's spine, head and arms keep the capture's rotations (optionally damped by
    "riderDamp") but ride on the horse: their heads are re-chained from the fixed Hips;
  * after_skin moves rider-bone weight (spine, head, arms) off vertices outside "riderBox" onto
    Hips, so a leaning rider cannot drag the horse's neck or rump; rigid props are left alone.
Whole-body rearing, lunging and the death fall come from castle_refine (dx, dy, roll).

Config:  "extensions": ["castle_mount", "castle_refine"], "grounding": false,
  "mount": {"riderBox": [[x0,y0,z0],[x1,y1,z1]], "riderDamp": 1.0, "bob": 0.02, "nod": 6,
            "deathFall": {"deg": 85, "side": -1, "pivotX": 0.25, "start": 0.15, "end": 1.0} (optional;
            the fall eases in over clip fractions start..end and holds after end),
            "riderTwist": {"clip": "Hitted", "deg": 90, "bones": ["Spine", "Spine1", "Spine2"], "hold": 0.72,
                           "end": 0.86, "keep": ["LeftShoulder", "RightShoulder"]} (optional; rider torso turn about the vertical, see after_pose),
            "chains": {"HFL": {"phase": 0.0, "swing": 22, "flex": [0, 35, 20]}, ...,
                       "HNeck": {"nod": true}}}
"""
import math, json
import numpy as np

RIDER = ("Spine", "Spine1", "Spine2", "Neck", "Head")


def _rider_bone(n):
    return n in RIDER or n.startswith(("Left", "Right"))


def _parent_chains_to_hips(g):
    """staticChains start at Root, which is never keyed, and only Hips gets location keys, so a
    chain root can only rotate about its rest head: a whole-body move (castle_refine dx/dy/roll,
    castle_yaw) would leave the legs, neck and tail behind. Parent each chain root to Hips."""
    bpy, rig, parent_of = g["bpy"], g["rig"], g["parent_of"]
    roots = [f"{ch['prefix']}0" for ch in g["cfg"].get("staticChains", [])]
    roots = [n for n in roots if n in parent_of and parent_of[n] == "Root"]
    if not roots:
        return
    prev = bpy.context.view_layer.objects.active; mode = prev.mode if prev else 'OBJECT'
    if prev and mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for n in roots:
        eb[n].parent = eb["Hips"]; parent_of[n] = "Hips"
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = prev
    print("MOUNT chains parented to Hips:", roots)


def _leg_weights(g, LW):
    """mount.legWeights {"chains": ["HFL", ...], "blend": 0.03} (authenticity rubric 3a, 2026-10-07): bone heat
    smears a horse leg's weight -- the cannon (k=1) owned ~150 partial vertices, the forearm bone half the chest,
    and the near cannon shared vertices with the far forearm -- so a knee fold barely bends the leg and stretches
    the skin. Per vertex below the chain tops: its total weight on all leg bones is re-split by the nearest leg
    segment (all chains compete, so a vertex belongs to one leg), linear blend to the neighbouring bone within
    `blend` of a joint; its non-leg weight (Hips) is kept."""
    body, taken = g["body"], g["taken"]
    chains = {ch["prefix"]: [np.array(q, float) for q in ch["points"]] for ch in g["cfg"].get("staticChains", [])
              if ch["prefix"] in LW["chains"]}
    blend = float(LW.get("blend", 0.03))
    segs = [(pre, k, P[k], P[k + 1]) for pre, P in chains.items() for k in range(len(P) - 1)]
    leg_bone = {f"{pre}{k}" for pre, k, _, _ in segs}
    gi = {vg.index: vg.name for vg in body.vertex_groups}
    vg = body.vertex_groups
    changed = 0
    for v in body.data.vertices:
        if v.index in taken:
            continue
        row = {gi[gr.group]: gr.weight for gr in v.groups if gr.weight > 0}
        s_leg = sum(w for k, w in row.items() if k in leg_bone)
        if s_leg < 0.05:
            continue
        p = np.array(v.co[:], float)
        best = None
        for pre, k, a, b in segs:
            ab = b - a; L = float(np.linalg.norm(ab)); t = float(np.clip((p - a) @ ab / (L * L), 0.0, 1.0))
            d = float(np.linalg.norm(a + t * ab - p))
            if best is None or d < best[0]:
                best = (d, pre, k, t * L, L)
        _, pre, k, x, L = best
        if k == 0 and x <= 1e-6:                           # above the chain top: the body's, keep bone heat
            continue
        n = len(chains[pre]) - 1
        dist = {f"{pre}{k}": 1.0}
        if k > 0 and x < blend:
            f = 0.5 * (1.0 - x / blend); dist = {f"{pre}{k}": 1.0 - f, f"{pre}{k - 1}": f}
        elif k < n - 1 and L - x < blend:
            f = 0.5 * (1.0 - (L - x) / blend); dist = {f"{pre}{k}": 1.0 - f, f"{pre}{k + 1}": f}
        new = {kk: w for kk, w in row.items() if kk not in leg_bone}
        for kk, f in dist.items():
            new[kk] = new.get(kk, 0.0) + f * s_leg
        top = sorted(new.items(), key=lambda kv: -kv[1])[:4]; tt = sum(w for _, w in top)
        for gr in list(v.groups):
            vg[gr.group].remove([v.index])
        for kk, w in top:
            vg[kk].add([v.index], w / tt, 'REPLACE')
        changed += 1
    print("MOUNT legWeights re-split", changed, "leg vertices over", sorted(chains))


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _chain_split(V, P, blend):
    """Per vertex: weights over the chain's bones (len(P)-1) by nearest segment, rigid inside a segment, a linear
    50/50 blend within `blend` of each inner joint. Returns (n, len(P)-1) rows summing to 1, and the distance."""
    nb = len(P) - 1
    best_d = np.full(len(V), np.inf); best_k = np.zeros(len(V), int); best_x = np.zeros(len(V)); Ls = []
    for k in range(nb):
        a, b = P[k], P[k + 1]; ab = b - a; L = float(np.linalg.norm(ab)); Ls.append(L)
        t = np.clip((V - a) @ ab / (L * L), 0.0, 1.0)
        d = np.linalg.norm(a + t[:, None] * ab - V, axis=1)
        m = d < best_d
        best_d[m], best_k[m], best_x[m] = d[m], k, t[m] * L
    R = np.zeros((len(V), nb))
    R[np.arange(len(V)), best_k] = 1.0
    if blend > 0:
        for k in range(nb):
            sel = best_k == k
            L = Ls[k]
            if k > 0:                                          # near this segment's head: share with the parent
                m = sel & (best_x < blend)
                f = 0.5 * (1.0 - best_x[m] / blend)
                R[m, k] -= f; R[m, k - 1] += f
            if k < nb - 1:                                     # near its tail: share with the child
                m = sel & (L - best_x < blend)
                f = 0.5 * (1.0 - (L - best_x[m]) / blend)
                R[m, k] -= f; R[m, k + 1] += f
    return R, best_d


def _smooth_rows(V, W, edges, zone, iters):
    """Average weight rows over mesh neighbours for `zone` vertices (others are fixed boundary); coincident vertices
    (UV-seam / split copies) are welded first so they keep skinning identically."""
    key = np.round(V / 1e-5).astype(np.int64)
    _, gid = np.unique(key, axis=0, return_inverse=True); gid = gid.ravel(); ng = int(gid.max()) + 1
    E = np.unique(np.sort(gid[np.asarray(edges)], 1), axis=0); E = E[E[:, 0] != E[:, 1]]
    cnt = np.bincount(gid, minlength=ng).astype(float)
    G = np.zeros((ng, W.shape[1])); np.add.at(G, gid, W); G /= cnt[:, None]
    zg = np.zeros(ng, bool); zg[gid[zone]] = True
    deg = np.bincount(E.ravel(), minlength=ng).astype(float)
    for _ in range(iters):
        acc = np.zeros_like(G); np.add.at(acc, E[:, 0], G[E[:, 1]]); np.add.at(acc, E[:, 1], G[E[:, 0]])
        nb = acc / np.maximum(deg, 1)[:, None]
        G[zg & (deg > 0)] = 0.5 * G[zg & (deg > 0)] + 0.5 * nb[zg & (deg > 0)]
    W = W.copy(); W[zone] = G[gid[zone]]
    return W


def segment_weights(V, names, W, cfg, RS, edges=None):
    """mount.rigSegments (authenticity rubric 3a, 2026-10-07; pure numpy so it can be checked on a GLB): bone heat
    smeared the horse -- no leg, neck or rider-arm bone owned one rigid vertex (HFL0 reached 2499 vertices up into
    the barrel, HNeck0 3777, a neck vertex carried HFL0), so a knee/fetlock fold dragged the chest and the CS re-bake
    tore the stretched skin. Rebuild those weights by segment:
      legs  {"chains": [...], "blend": b, "radius": r, "band": [z1, z0]}: a vertex belongs to its nearest leg when
            within `radius` of it; membership is 1 below z1 and fades to 0 at z0 (the belly line, so the elbow /
            stifle fold blends into the body); inside the leg each segment is rigid with a `blend` at each joint;
      neck  {"chain": "HNeck", "blend": b, "t": [t0, t1], "radius": r, "maxX": x}: membership fades in along the
            neck base axis (t0 -> t1 past the first chain point), within `radius` of the chain and |x| < maxX;
            "smooth": n (with `edges`): n rounds of weight averaging over mesh neighbours inside the neck zone, so the
            throat skin between the tucked jaw and the breast blends instead of tearing;
      arms  {"chains": [[joint names...]], "blend": b}: the vertex's share on those bones is re-split by nearest
            segment of the capture joints (its spine/prop share is kept).
    Leg/neck weight on non-member vertices goes to Hips. Tail-owned vertices (tail weight > 0.3) stay out of legs/neck. Rider-owned vertices (rider weight > 0.5) are not horse.
    W: (n, len(names)) weights per vertex; returns the new matrix (rows sum as before)."""
    W = W.copy(); col = {n: i for i, n in enumerate(names)}
    chains = {ch["prefix"]: np.array(ch["points"], float) for ch in cfg.get("staticChains", [])}
    s0 = W.sum(1)
    rider = W[:, [col[n] for n in names if _rider_bone(n)]].sum(1) > 0.5 * np.maximum(s0, 1e-9)
    hips = col["Hips"]
    tail = W[:, [col[n] for n in names if n.startswith("HTail")]].sum(1) > 0.3 * np.maximum(s0, 1e-9)   # tail hangs by the hocks
    groups = []
    if "legs" in RS:
        groups += [(pre, "leg") for pre in RS["legs"]["chains"]]
    if "neck" in RS:
        groups.append((RS["neck"]["chain"], "neck"))
    managed = [col[f"{pre}{k}"] for pre, _ in groups for k in range(len(chains[pre]) - 1)]
    pool = W[:, managed].sum(1)
    W[:, managed] = 0.0; W[:, hips] += pool                   # strip, then hand back by membership
    body = W.copy()
    if "legs" in RS:
        L = RS["legs"]; legs = L["chains"]
        splits = {pre: _chain_split(V, chains[pre], L.get("blend", 0.035)) for pre in legs}
        D = np.stack([splits[pre][1] for pre in legs], 1); near = D.argmin(1); dmin = D.min(1)
        z1, z0 = L["band"]
        m = (1.0 - _smooth(z1, z0, V[:, 2])) * (dmin < L["radius"]) * (~rider) * (~tail)
        for li, pre in enumerate(legs):
            sel = (near == li) & (m > 0)
            R = splits[pre][0]
            idx = [col[f"{pre}{k}"] for k in range(R.shape[1])]
            mm = m[sel] * s0[sel]
            W[sel] = body[sel] * (1.0 - m[sel])[:, None]
            W[np.ix_(sel, idx)] += mm[:, None] * R[sel]
    if "neck" in RS:
        N = RS["neck"]; P = chains[N["chain"]]
        R, d = _chain_split(V, P, N.get("blend", 0.06))
        u = (P[1] - P[0]) / np.linalg.norm(P[1] - P[0]); t = (V - P[0]) @ u
        m = _smooth(N["t"][0], N["t"][1], t) * (d < N["radius"]) * (np.abs(V[:, 0]) < N["maxX"]) * (~rider) * (~tail)
        legged = W[:, [c for c in managed if names[c][:3] in ("HFL", "HFR", "HHL", "HHR")]].sum(1) > 1e-6
        sel = (m > 0) & ~legged
        idx = [col[f"{N['chain']}{k}"] for k in range(R.shape[1])]
        W[sel] = W[sel] * (1.0 - m[sel])[:, None]
        W[np.ix_(sel, idx)] += (m[sel] * s0[sel])[:, None] * R[sel]
        if N.get("smooth") and edges is not None:
            zone = (t > N["t"][0] - 0.1) & (d < N["radius"] + 0.05) & ~rider & ~legged
            W = _smooth_rows(V, W, edges, zone, int(N["smooth"]))
    if "throat" in RS:
        W = _throat_weights(V, names, W, chains, RS["throat"], edges, rider)
    for jn in RS.get("arms", {}).get("chains", []):
        P = np.array([cfg["joints"][n] for n in jn], float)
        bones = jn[:-1]; idx = [col[n] for n in bones if n in col]
        if len(idx) != len(bones):
            continue
        R, _ = _chain_split(V, P, RS["arms"].get("blend", 0.03))
        share = W[:, idx].sum(1); sel = share > 0.05 * np.maximum(s0, 1e-9)
        W[np.ix_(sel, idx)] = share[sel, None] * R[sel]
    return W


def _throat_weights(V, names, W, chains, T, edges, rider):
    """mount.rigSegments.throat (authenticity 2026-10-07, h3_champion): bone heat gave the horse's throatlatch skin
    half to the head (HNeck2) and a third to the neck base (HNeck0) while skipping the upper neck (HNeck1), so any head
    turn sheared its sub-cm edges against the neighbouring jaw/neck skin and the CS re-bake tore them. Graded weights:
    for the skip-set vertices (head share >= min2 and neck-base share >= min0) grown by `grow` edge rings, the neck
    share (sum over the chain's bones) is re-split over the chain bones by inverse distance to each segment
    (weight ~ d^-power, so it grades head -> upper neck -> neck base with no rigid seam), then `smooth` rounds of
    neighbour averaging inside the zone (zone edge fixed). Non-neck weight (Hips, rider) is untouched.
    T: {"chain": "HNeck", "min2": a, "min0": b, "grow": n, "power": p, "smooth": n, "headR": [r1, r0],
        "headOwn": [r1, r0], "hipsT": [t0, t1], "hipsSeg": [[a], [b]], "minHips": h}.
    Status 2026-10-07 21:40 (opt-in, no unit uses it): on h3_champion the best variant (headR [0.17, 0.27], power 2,
    smooth 6) cut the HNeck2 +12 deg probe's tears 116 -> 88 but raised the fitted base pose 64 -> 67, so the patch-lane
    gate still refuses; hipsT / hipsSeg / headOwn made it worse (the tucked rest head put head heat on the under-neck
    and jaw skin that also carries Hips)."""
    P = chains[T.get("chain", "HNeck")]; nb = len(P) - 1
    col = {n: i for i, n in enumerate(names)}
    idx = [col[f"{T.get('chain', 'HNeck')}{k}"] for k in range(nb)]
    s0 = np.maximum(W.sum(1), 1e-9)
    N = W[:, idx] / s0[:, None]
    hips = col["Hips"]
    seed = (N[:, nb - 1] >= T.get("min2", 0.3)) & ((N[:, 0] >= T.get("min0", 0.2))
                                                   | (W[:, hips] / s0 >= T.get("minHips", 2.0))) & ~rider
    if edges is None or not seed.any():
        return W
    key = np.round(V / 1e-5).astype(np.int64)
    _, gid = np.unique(key, axis=0, return_inverse=True); gid = gid.ravel()
    E = np.asarray(edges)
    zg = np.zeros(int(gid.max()) + 1, bool); zg[gid[seed]] = True
    for _ in range(int(T.get("grow", 2))):
        ge = gid[E]; hit = zg[ge[:, 0]] | zg[ge[:, 1]]
        zg[ge[hit].ravel()] = True
    zone = zg[gid] & ~rider & (N.sum(1) > 0.05)
    D = np.stack([np.linalg.norm(P[k] + np.clip((V - P[k]) @ (P[k + 1] - P[k]) / float((P[k + 1] - P[k]) @ (P[k + 1] - P[k])), 0, 1)[:, None]
                                 * (P[k + 1] - P[k]) - V, axis=1) for k in range(nb)], 1)
    G = np.maximum(D, 1e-3) ** -float(T.get("power", 2.0))
    if T.get("headR"):                                   # the head bone only owns skin near the head: the rest-pose
        r1, r0 = T["headR"]                              # tucked nose put head heat on the breast, so a head turn
        G[:, nb - 1] *= 1.0 - _smooth(r1, r0, D[:, nb - 1])   # dragged the chest (tears at the breast, not the throat)
    W = W.copy()
    if T.get("headOwn"):                                 # muzzle/jaw skin resting against the breast took a Hips
        o1, o0 = T["headOwn"]                            # share: inside the head radius it rides with the head
        f = (1.0 - _smooth(o1, o0, D[:, nb - 1])) * zone
        moved = W[:, hips] * f; W[:, hips] -= moved; W[:, idx[-1]] += moved
    if T.get("hipsT"):                                   # under-neck skin between the tucked head and the breast took
        a0, a1 = T["hipsT"]                              # a Hips share; past the neck base it belongs to the neck
        u = (P[1] - P[0]) / np.linalg.norm(P[1] - P[0])
        f = _smooth(a0, a1, (V - P[0]) @ u) * zone
        moved = W[:, hips] * f; W[:, hips] -= moved; W[:, idx[0]] += moved
    cols = list(idx)
    if T.get("hipsSeg"):                                 # the breast as one more graded member (Hips): zone skin grades
        a, b = (np.array(x, float) for x in T["hipsSeg"])  # breast -> neck base -> upper neck -> head
        ab = b - a; dh = np.linalg.norm(a + np.clip((V - a) @ ab / float(ab @ ab), 0, 1)[:, None] * ab - V, axis=1)
        G = np.c_[G, np.maximum(dh, 1e-3) ** -float(T.get("power", 2.0))]; cols.append(hips)
    G /= G.sum(1, keepdims=True)
    share = W[:, cols].sum(1)
    W[np.ix_(zone, cols)] = share[zone, None] * G[zone]
    if T.get("smooth"):
        W = _smooth_rows(V, W, edges, zone, int(T["smooth"]))
    print("MOUNT throat graded", int(zone.sum()), "vertices (seed", int(seed.sum()), ")")
    return W


def _rig_segments(g, RS):
    body, taken = g["body"], g["taken"]
    names = [vg.name for vg in body.vertex_groups]; vg = body.vertex_groups
    keep = [v.index for v in body.data.vertices if v.index not in taken]
    V = np.array([body.data.vertices[i].co[:] for i in keep], float)
    W = np.zeros((len(keep), len(names)))
    for r, i in enumerate(keep):
        for gr in body.data.vertices[i].groups:
            if gr.weight > 0:
                W[r, gr.group] = gr.weight
    pos = {i: r for r, i in enumerate(keep)}
    edges = [(pos[e.vertices[0]], pos[e.vertices[1]]) for e in body.data.edges
             if e.vertices[0] in pos and e.vertices[1] in pos]
    W2 = segment_weights(V, names, W, g["cfg"], RS, np.array(edges, int))
    changed = 0
    for r, i in enumerate(keep):
        if np.allclose(W[r], W2[r], atol=1e-6):
            continue
        row = sorted(((k, w) for k, w in enumerate(W2[r]) if w > 1e-4), key=lambda kv: -kv[1])[:4]
        t = sum(w for _, w in row)
        for gr in list(body.data.vertices[i].groups):
            vg[gr.group].remove([i])
        for k, w in row:
            vg[k].add([i], w / t, 'REPLACE')
        changed += 1
    print("MOUNT rigSegments rewrote", changed, "vertices", sorted(RS))


def after_skin(g):
    M = g["cfg"].get("mount")
    if not M:
        return
    _parent_chains_to_hips(g)
    if M.get("legWeights"):
        _leg_weights(g, M["legWeights"])
    if M.get("rigSegments"):
        _rig_segments(g, M["rigSegments"])
    if "riderBox" not in M:
        return
    body = g["body"]; taken = g["taken"]
    lo, hi = M["riderBox"]
    gi = {vg.index: vg.name for vg in body.vertex_groups}
    vg = body.vertex_groups
    moved = 0
    for v in body.data.vertices:
        if v.index in taken:
            continue
        p = v.co
        if all(lo[i] <= p[i] <= hi[i] for i in range(3)):
            continue
        row = {gi[gr.group]: gr.weight for gr in v.groups if gr.weight > 0}
        acc = sum(w for k, w in row.items() if _rider_bone(k))
        if acc <= 0:
            continue
        row = {k: w for k, w in row.items() if not _rider_bone(k)}
        row["Hips"] = row.get("Hips", 0.0) + acc
        top = sorted(row.items(), key=lambda kv: -kv[1])[:4]; t = sum(w for _, w in top)
        for gr in list(v.groups):
            vg[gr.group].remove([v.index])
        for k, w in top:
            vg[k].add([v.index], w / t, 'REPLACE')
        moved += 1
    print("MOUNT rider weight moved to Hips on", moved, "horse vertices")


def after_pose(g):
    M = g["cfg"].get("mount")
    if not M:
        return
    Matrix, Vector, Quaternion = g["Matrix"], g["Vector"], g["Quaternion"]
    posed, rest, parent_of, names = g["posed_world"], g["rest"], g["parent_of"], g["bone_names"]
    STATIC = g["STATIC"]; T = g["T"]
    chains_cfg = M.get("chains", {})
    chain_of = {}
    for ch in g["cfg"].get("staticChains", []):
        k = 0
        while f"{ch['prefix']}{k}" in names:
            chain_of[f"{ch['prefix']}{k}"] = (ch["prefix"], k); k += 1
    # gait phase and amplitude per frame
    amp = [0.0] * T; ph = [0.0] * T
    for sg in json.load(open(g["MASTER"]))["segments"]:
        a_ = {"Move": 1.0, "MoveStart": 0.5, "MoveEnd": 0.5}.get(sg["contractSuffix"], 0.0)
        n_ = max(sg["frameCount"], 1)
        for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
            amp[t] = a_; ph[t] = 2 * math.pi * i / n_
    damp = M.get("riderDamp", 1.0)
    X = Vector((1, 0, 0))
    for t in range(T):
        A = posed[t]
        bob = M.get("bob", 0.02) * amp[t] * math.cos(2 * ph[t])
        B = Matrix.Translation(Vector((0, 0, bob)))
        new = {"Root": A["Root"]}
        for n in names:
            par = parent_of[n]
            if n == "Hips":
                new[n] = B @ rest[n]; continue
            if n in chain_of:
                pre, k = chain_of[n]; c = chains_cfg.get(pre, {})
                phase = ph[t] + 2 * math.pi * c.get("phase", 0.0)
                if c.get("nod"):
                    ang = math.radians(M.get("nod", 6.0)) * amp[t] * math.sin(2 * ph[t]) if k == 0 else 0.0
                else:
                    swing = math.radians(c.get("swing", 0.0)) * amp[t] * math.sin(phase)
                    lift = max(0.0, math.cos(phase))
                    fl = c.get("flex", [])
                    ang = (swing if k == 0 else 0.0) + (math.radians(fl[k]) * amp[t] * lift if k < len(fl) else 0.0)
                if k == 0:
                    head = (B @ rest[n]).translation; base = B.to_3x3()
                    acc = ang
                else:
                    head = new[par] @ (rest[par].inverted() @ rest[n].translation)
                    base = B.to_3x3(); acc = new[par + "_acc"] + ang if (par + "_acc") in new else ang
                new[n + "_acc"] = acc
                R = base @ Matrix.Rotation(acc, 3, X) @ rest[n].to_3x3()
                new[n] = Matrix.Translation(head) @ R.to_4x4()
                continue
            head = new[par] @ (rest[par].inverted() @ rest[n].translation)
            Rw = A[n].to_3x3()
            if damp < 1.0 and _rider_bone(n):
                q0 = rest[n].to_3x3().to_quaternion(); q1 = Rw.to_quaternion()
                Rw = q0.slerp(q1, damp).to_matrix()
            new[n] = Matrix.Translation(head) @ Rw.to_4x4()
        for n in list(new):
            if not n.endswith("_acc"):
                A[n] = new[n]
    kids = {}
    for n in names:
        kids.setdefault(parent_of[n], []).append(n)

    def sub(b):
        out, st = [], [b]
        while st:
            x = st.pop(); out.append(x); st += kids.get(x, [])
        return out

    def death_frames():
        for sg in json.load(open(g["MASTER"]))["segments"]:
            if sg["contractSuffix"] == "Death":
                n_ = max(sg["frameCount"] - 1, 1)
                for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                    yield i / n_, t

    def ease(u, s0, s1):
        u = min(1.0, max(0.0, (u - s0) / max(s1 - s0, 1e-6)))
        return u * u * (3 - 2 * u)

    def turn(A, bone, ang, axis, piv=None):
        if bone not in A or abs(ang) < 1e-9:
            return
        p = A[bone].translation.copy() if piv is None else piv
        Rm = Matrix.Translation(p) @ Matrix.Rotation(ang, 4, axis) @ Matrix.Translation(-p)
        for n in sub(bone):
            if n in A:
                A[n] = Rm @ A[n]
    # front sink in Death, before the fall (h3_champion DEF f1-f4: the forelegs fold under the chest, the front of the
    # horse sinks onto its knees while the hind stays up, the head stays raised; a falling human capture cannot give
    # it). Eased in over clip fractions start..end and held: the whole body pitches nose-down `pitch` deg about the
    # hind hoof line (rest x axis at y = pivotY, z = 0; the horse faces -Y), each foreleg bone k turns `fore[k]` deg
    # about its head (positive folds the lower leg back), the neck root `neck` deg (negative lifts the head) and,
    # with riderUpright, the rider's Spine subtree turns back by the pitch so the rider sits up as the horse sinks.
    # The pitch (not the leg/neck fold) eases back out over releaseStart..releaseEnd (default: the deathFall window)
    # so the horse lies level on its side.
    FS = M.get("frontSink")
    if FS:
        nfs = 0
        piv = Vector((0.0, FS.get("pivotY", 0.4), 0.0))
        for u, t in death_frames():
            w = ease(u, FS.get("start", 0.05), FS.get("end", 0.45))
            if w <= 0:
                continue
            DFc = M.get("deathFall") or {}
            wp = w * (1.0 - ease(u, FS.get("releaseStart", DFc.get("start", 1.0)), FS.get("releaseEnd", DFc.get("end", 1.0))))
            A = posed[t]
            for pre in ("HFL", "HFR"):
                for k, deg in enumerate(FS.get("fore", [])):
                    turn(A, f"{pre}{k}", math.radians(deg) * w, 'X')
            turn(A, "HNeck0", math.radians(FS.get("neck", 0.0)) * w, 'X')
            if FS.get("riderUpright"):
                turn(A, "Spine", -math.radians(FS.get("pitch", 0.0)) * wp, 'X')
            Rm = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(FS.get("pitch", 0.0)) * wp, 4, 'X') @ Matrix.Translation(-piv)
            for n in list(A):
                if n != "Root" and not n.endswith("_acc"):
                    A[n] = Rm @ A[n]
            nfs += 1
        print("MOUNT front sink", FS.get("pitch"), "deg over", nfs, "frames")
    # scripted fall in Death: the DEF horse tips onto its side, which a capture of a falling
    # human cannot give and castle_refine's local roll search cannot reach. Every body bone turns
    # about the ground line along the horse (rest +Y axis, at x = side * pivotX, z = 0), eased in
    # from `start` (fraction of the clip) to the last frame. Runs before castle_yaw (rest frame).
    DF = M.get("deathFall")
    if DF:
        side = DF.get("side", -1); deg = DF.get("deg", 85.0); x0 = DF.get("pivotX", 0.25)
        piv = Vector((side * x0, 0.0, 0.0))
        nfall = 0
        for sg in json.load(open(g["MASTER"]))["segments"]:
            if sg["contractSuffix"] != "Death":
                continue
            n_ = max(sg["frameCount"] - 1, 1)
            for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                s0, s1 = DF.get("start", 0.15), DF.get("end", 1.0)
                u = (i / n_ - s0) / max(s1 - s0, 1e-6)
                u = min(1.0, max(0.0, u)); u = u * u * (3 - 2 * u)
                if u <= 0:
                    continue
                Rm = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(side * deg * u), 4, 'Y') @ Matrix.Translation(-piv)
                A = posed[t]
                for n in list(A):
                    if n != "Root" and not n.endswith("_acc"):
                        A[n] = Rm @ A[n]
                nfall += 1
        print("MOUNT death fall", deg, "deg over", nfall, "frames")
        # riderFlat: the rider (Spine subtree, Spine2 carries the shield) rolls on past the horse by this many deg
        # about the horse's long axis through the Spine head, eased over the same window, so he lies flat beyond the
        # fallen horse and the shield stays below its silhouette (h3_champion DEF f6-f7) instead of standing up.
        rf = DF.get("riderFlat", 0.0)
        if rf:
            for u, t in death_frames():
                w = ease(u, DF.get("start", 0.15), DF.get("end", 1.0))
                if w > 0:
                    A = posed[t]
                    axis = Vector((0.0, 1.0, 0.0))       # the long axis the fall turned about
                    p = A["Spine"].translation.copy()
                    Rm = Matrix.Translation(p) @ Matrix.Rotation(math.radians(side * rf) * w, 4, axis) @ Matrix.Translation(-p)
                    for n in sub("Spine"):
                        if n in A:
                            A[n] = Rm @ A[n]
            print("MOUNT rider flat", rf, "deg")
        # riderHold: once the fall has landed (clip fraction >= end) the rider keeps the landed frame's pose relative
        # to Hips; the human death capture keeps flailing (h3_champion f6-f7: lance and shield stood up off the
        # lying horse where the DEF rider lies still).
        if DF.get("riderHold"):
            ref = None; nh = 0
            for u, t in death_frames():
                if u + 1e-6 < DF.get("end", 1.0):
                    continue
                A = posed[t]
                if ref is None:
                    ref = {n: A[n].copy() for n in sub("Spine") if n in A}; refh = A["Hips"].copy(); continue
                C = A["Hips"] @ refh.inverted()
                for n, m in ref.items():
                    A[n] = C @ m
                nh += 1
            print("MOUNT rider hold over", nh, "frames")
        # lanceLie: [bone, [x0,y0,z0], [x1,y1,z1]] (the held prop's rest segment): over the fall window the bone's
        # subtree turns about its head until the prop lies level along the horse, pointing forward (-Y) (h3_champion
        # DEF f5-f7: the lance lies along the fallen horse, never standing up off it). Level, not down: a prop under
        # the floor would make ground_glb lift the whole lying unit.
        LL = DF.get("lanceLie")
        if LL:
            bone, p0, p1 = LL[0], Vector(LL[1]), Vector(LL[2])
            d0 = rest[bone].to_3x3().inverted() @ (p1 - p0).normalized()
            for u, t in death_frames():
                w = ease(u, DF.get("start", 0.15), DF.get("end", 1.0))
                A = posed[t]
                if w <= 0 or bone not in A:
                    continue
                dn = (A[bone].to_3x3().normalized() @ d0).normalized()
                q = dn.rotation_difference(Vector((0.0, -1.0, 0.0)))
                q = Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(q, w)
                p = A[bone].translation.copy()
                Rm = Matrix.Translation(p) @ q.to_matrix().to_4x4() @ Matrix.Translation(-p)
                for n in sub(bone):
                    if n in A:
                        A[n] = Rm @ A[n]
                if w >= 0.999:                   # castle_refine's propAim leaves these frames alone
                    g.setdefault("propHeld", {}).setdefault(bone, set()).add(t)
            print("MOUNT lance lie", bone, "held", len(g.get("propHeld", {}).get(bone, ())), "frames")
    # rider twist in one clip: the DEF turns the rider's torso about the vertical (h3_champion Hitted: ~90 deg, back
    # to the viewer, f0-f5, front again by f6), which the capture does not. Split evenly over `bones` (lowest first),
    # each turning its own subtree about the world vertical through its head; full until `hold`, eased back to 0 at
    # `end` (clip fractions; optional `start` eases it in from 0). `keep` bones (the shoulders) keep their world
    # rotation and only ride along with their head: the arms and lance stay put while the torso and the Spine2 shield
    # turn away, so the hands resting on the saddle do not smear (h3_champion: 46 edges > 2x vs 279 with the arms
    # turning too). Runs before castle_yaw (rest frame, +Z up).
    RT = M.get("riderTwist")
    if RT:
        bones = RT.get("bones", ["Spine", "Spine1", "Spine2"]); per = math.radians(RT["deg"]) / len(bones)
        ntw = 0
        for sg in json.load(open(g["MASTER"]))["segments"]:
            if sg["contractSuffix"] != RT.get("clip", "Hitted"):
                continue
            n_ = max(sg["frameCount"] - 1, 1)
            for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                u = i / n_; s0 = RT.get("start", 0.0); h1, e1 = RT.get("hold", 0.72), RT.get("end", 0.86)
                w = 1.0 if s0 <= 0 else min(1.0, max(0.0, u / s0))
                if u > h1:
                    w = min(w, max(0.0, (e1 - u) / max(e1 - h1, 1e-6)))
                w = w * w * (3 - 2 * w)
                if w <= 0:
                    continue
                A = posed[t]
                keep = RT.get("keep", [])
                old = {n: A[n].copy() for k in keep for n in sub(k) if n in A}
                for b in bones:
                    piv = A[b].translation.copy()
                    Rm = Matrix.Translation(piv) @ Matrix.Rotation(per * w, 4, 'Z') @ Matrix.Translation(-piv)
                    for n in sub(b):
                        if n in A:
                            A[n] = Rm @ A[n]
                for k in keep:              # kept subtrees (shoulders): world pose kept, carried by the head's shift
                    if k in A:
                        sh = Matrix.Translation(A[k].translation - old[k].translation)
                        for n in sub(k):
                            if n in old:
                                A[n] = sh @ old[n]
                ntw += 1
        print("MOUNT rider twist", RT["deg"], "deg over", ntw, "frames")
    # from here on the chains are ordinary body bones (castle_refine moves them with the body)
    for n in chain_of:
        STATIC.discard(n)
    print("MOUNT posed", len(chain_of), "horse chain bones over", T, "frames")
