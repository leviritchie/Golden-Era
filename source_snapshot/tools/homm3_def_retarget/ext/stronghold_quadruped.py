"""Procedural wolf under a captured rider (Stronghold wolf riders / wolf raiders).

The DEF capture is a human skeleton: it drives the goblin rider (spine, arms, sword) but has no
wolf. This extension adds a wolf rig (body, neck, head, tail, four 3-segment legs) under the
rider, binds the wolf part of the mesh to it, and animates it per DEF clip with a parametric
gait: a galloping leg cycle in Move (one cycle per clip, so the loop closes), breathing in Idle,
a lunge in AttackFront, a recoil in Hitted, a crouch in Defence and a roll onto its side in Death.
The rider's bones ride on the wolf body. silhouetteRefine (dx, dy, roll) then fits the whole
unit to each DEF frame.

Config key "quadruped":
  "bones": {name: [head, tail, parent]}            wolf body chain, parent "Root" or a wolf bone;
                                                   must contain "WolfBody" (the rider rides it)
  "legs": {prefix: {"points": [top, knee, ankle, paw], "front": bool, "side": +1|-1}}
  "rider": {"box": [lo, hi], "minZ": z, "minSat": s, "saddle": [z0, z1]}
      optional "color": {"expr": "g-r", "min"|"max": v} replaces the saturation test (r,g,b,mx,mn),
      optional "boxes": [[lo, hi], ...] are rider regardless of height/colour (boar rider)
      vertices in box with z > minZ, or with colour saturation > minSat (the wolf is grey), are
      rider; the rest is wolf. Rider vertices below saddle z1 blend into WolfBody (all of it
      below z0), so the saddle and hanging legs stay on the wolf.
  "protect": ["RightHand"]   vertices bound 100% to these bones (props) always stay rider
      "rider" may also carry "free": [{"box": [lo, hi]}, ...]: vertices inside are rider and skip
      the saddle blend (hands and sword hilts that hang below the saddle line)
  "bodyRadius": r      distance allowance of the body segment (torso vertices prefer the body)
  "gait": {"stride": deg, "knee": deg, "pitch": deg, "bob": m}   Move cycle amplitudes
Hooks: after_skin, after_pose, before_keys.
"""
import math, json
import numpy as np
from mathutils import Vector, Matrix, kdtree


def _q(g):
    return g["cfg"].get("quadruped")


def _all_bones(q):
    out = [(n, v[0], v[1], v[2]) for n, v in q["bones"].items()]
    for pre, lg in q["legs"].items():
        p = lg["points"]
        for k in range(3):
            out.append((f"{pre}{k + 1}", p[k], p[k + 1], "WolfBody" if k == 0 else f"{pre}{k}"))
    return out


def after_skin(g):
    q = _q(g)
    if not q:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]; vert_color = g["vert_color"]
    B = _all_bones(q)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for n, h, t, p in B:
        b = eb.new(n); b.head, b.tail = Vector(h), Vector(t); b.roll = 0
    for n, h, t, p in B:
        eb[n].parent = eb[p]
    bpy.ops.object.mode_set(mode='OBJECT')
    for n, *_ in B:
        body.vertex_groups.new(name=n)
    gidx = {vg.name: vg.index for vg in body.vertex_groups}

    V = body.data.vertices
    P = np.array([v.co[:] for v in V])
    # vertices the skin pass left with no weight (boar rider: 310 at the saddle front) would stay
    # at rest while the body moves: copy the weights of the nearest weighted vertex
    empty = [i for i, v in enumerate(V) if sum(gg.weight for gg in v.groups) < 1e-6]
    if empty:
        full = [i for i, v in enumerate(V) if sum(gg.weight for gg in v.groups) >= 1e-6]
        kdf = kdtree.KDTree(len(full))
        for k, i in enumerate(full):
            kdf.insert(P[i], k)
        kdf.balance()
        for i in empty:
            src = V[full[kdf.find(P[i])[1]]]
            for gg in src.groups:
                body.vertex_groups[gg.group].add([i], gg.weight, 'REPLACE')
        print("QUADRUPED filled", len(empty), "weightless vertices from their nearest neighbour")
    C = np.array([vert_color(v.co) for v in V])
    rd = q["rider"]; lo, hi = np.array(rd["box"][0]), np.array(rd["box"][1])
    inbox = np.all((P >= lo) & (P <= hi), 1)
    sat = C.max(1) - C.min(1)
    if "color" in rd:   # colour test instead of saturation (a saturated brown boar under a green rider)
        cc = rd["color"]
        cv = eval(cc["expr"], {}, {"r": C[:, 0], "g": C[:, 1], "b": C[:, 2], "mx": C.max(1), "mn": C.min(1)})
        colour = (cv >= cc["min"]) if "min" in cc else (cv <= cc["max"])
    else:
        colour = sat > rd["minSat"]
    rider = inbox & ((P[:, 2] > rd["minZ"]) | colour)
    for bx in rd.get("boxes", []):   # always rider (legs hanging beside the body)
        rider |= np.all((P >= np.array(bx[0])) & (P <= np.array(bx[1])), 1)
    # vote over a small 3D ball: texture noise and dark rider cloth follow their neighbours
    kd = kdtree.KDTree(len(P))
    for i, p in enumerate(P):
        kd.insert(p, i)
    kd.balance()
    for _ in range(rd.get("votePasses", 2)):
        nr = rider.copy()
        for i in np.nonzero(inbox)[0]:
            nb = [j for _, j, _ in kd.find_range(P[i], rd.get("voteRadius", 0.035))]
            nr[i] = np.mean(rider[nb]) > 0.5
        rider = nr
    # prop-bound vertices (the sword, bound 100% to a hand by "props") stay rider
    prot = {gidx[n] for n in q.get("protect", []) if n in gidx}
    for i, v in enumerate(V):
        if any(gg.group in prot and gg.weight >= 0.999 for gg in v.groups):
            rider[i] = True
    free = np.zeros(len(P), bool)
    for fr in rd.get("free", []):
        flo, fhi = np.array(fr["box"][0]), np.array(fr["box"][1])
        free |= np.all((P >= flo) & (P <= fhi), 1)
    rider |= free
    # wolf weights: inverse distance to the wolf bone segments
    segs = [(n, np.array(h), np.array(t)) for n, h, t, _ in B]
    def segd(a, b):
        ab = b - a; tt = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        return np.linalg.norm(P - (a + tt[:, None] * ab), axis=1)
    D = np.stack([segd(a, b) for _, a, b in segs], 1)
    br = q.get("bodyRadius", 0.18)
    for k, (n, a, b) in enumerate(segs):
        if n == "WolfBody":
            D[:, k] = np.maximum(D[:, k] - br, 0.0)
        elif n in ("WolfNeck",):
            D[:, k] = np.maximum(D[:, k] - br * 0.5, 0.0)
    D = np.maximum(D, 0.01)
    Wd = 1.0 / D ** q.get("power", 4)
    # upper leg bones only below the body's underside at their top joint (flank stays body)
    for pre, lg in q["legs"].items():
        k = [s[0] for s in segs].index(f"{pre}1"); top = lg["points"][0][2]
        Wd[:, k] *= np.clip((top - P[:, 2]) / 0.15, 0, 1) ** 2 + 1e-6
    idx = np.argsort(-Wd, 1)[:, 3:]
    np.put_along_axis(Wd, idx, 0, 1)
    Wd /= Wd.sum(1, keepdims=True)
    z0, z1 = rd["saddle"]
    wb = gidx["WolfBody"]; nw = nr_ = 0
    for i, v in enumerate(V):
        if rider[i]:
            a = 1.0 if free[i] else float(np.clip((P[i, 2] - z0) / max(z1 - z0, 1e-6), 0, 1))
            if a >= 1:
                continue
            old = [(gg.group, gg.weight * a) for gg in v.groups]
            for gg in list(v.groups):
                body.vertex_groups[gg.group].remove([i])
            for gi, w in old:
                if w > 1e-4:
                    body.vertex_groups[gi].add([i], w, 'REPLACE')
            body.vertex_groups[wb].add([i], 1 - a, 'ADD')
            nr_ += 1
            continue
        for gg in list(v.groups):
            body.vertex_groups[gg.group].remove([i])
        for k in np.nonzero(Wd[i] > 1e-4)[0]:
            body.vertex_groups[gidx[segs[k][0]]].add([i], float(Wd[i, k]), 'REPLACE')
        nw += 1
    # glTF skins carry 4 influences: keep each vertex's 4 largest weights, renormalised
    n4 = 0
    for i, v in enumerate(V):
        gs = sorted(((gg.group, gg.weight) for gg in v.groups if gg.weight > 0), key=lambda t: -t[1])
        if len(gs) > 4 or (gs and abs(sum(w for _, w in gs) - 1.0) > 1e-4):
            keep = gs[:4]; tot = sum(w for _, w in keep)
            for gg in list(v.groups):
                body.vertex_groups[gg.group].remove([i])
            for gi, w in keep:
                body.vertex_groups[gi].add([i], w / tot, 'REPLACE')
            n4 += 1
    print("REGION quadruped wolf verts", nw, "rider verts", int(rider.sum()), "saddle-blended", nr_, "limit4/renorm", n4)


def _about(pt, M):
    return Matrix.Translation(pt) @ M @ Matrix.Translation(-pt)


def after_pose(g):
    q = _q(g)
    if not q:
        return
    rest = g["rest"]; parent_of = g["parent_of"]; posed = g["posed_world"]
    B = _all_bones(q)
    wolf = [n for n, *_ in B]
    for n, h, t, p in B:
        rest[n] = g["rig"].data.bones[n].matrix_local.copy()
        parent_of[n] = p
    segs = json.load(open(g["MASTER"]))["segments"]
    info = {}
    for sg in segs:
        for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
            info[t] = (sg["contractSuffix"], i, sg["frameCount"])
    ga = q.get("gait", {})
    STR, KNEE, PITCH, BOB = (math.radians(ga.get("stride", 32)), math.radians(ga.get("knee", 35)),
                             math.radians(ga.get("pitch", 6)), ga.get("bob", 0.03))
    bodyh = Vector(q["bones"]["WolfBody"][0]); bodyt = Vector(q["bones"]["WolfBody"][1])
    centre = (bodyh + bodyt) / 2
    X = Vector((1, 0, 0))

    def local_rot(n, ang):
        axis = rest[n].to_3x3().inverted() @ X
        return Matrix.Rotation(ang, 4, axis)

    for t, A in enumerate(posed):
        clip, i, nfr = info.get(t, ("Idle", 0, 1))
        e = math.sin(math.pi * i / max(nfr - 1, 1)) if nfr > 1 else 0.0
        phase = 2 * math.pi * i / max(nfr, 1)
        pitch = 0.0; off = Vector((0, 0, 0)); roll = 0.0
        neck = head = tail = 0.0
        leg = {pre: [0.0, 0.0, 0.0] for pre in q["legs"]}
        if clip in ("Move", "MoveStart", "MoveEnd"):
            amp = 1.0 if clip == "Move" else 0.5
            ph = phase if clip == "Move" else (0.0 if clip == "MoveStart" else math.pi)
            for pre, lg in q["legs"].items():
                o = (0.0 if lg["front"] else math.pi * 0.8) + (0.25 if lg["side"] > 0 else 0.0)
                s = math.sin(ph + o)
                leg[pre] = [amp * STR * s, amp * KNEE * max(0.0, math.cos(ph + o)) * (-1 if lg["front"] else 1),
                            amp * 0.5 * KNEE * max(0.0, math.cos(ph + o))]
            pitch = amp * PITCH * math.sin(ph + math.pi / 2)
            off = Vector((0, 0, amp * BOB * math.sin(2 * ph)))
            neck = -0.5 * pitch; tail = 0.25 * math.sin(ph)
        elif clip in ("Idle", "Mouseover"):
            off = Vector((0, 0, 0.006 * math.sin(phase)))
            head = math.radians(3) * math.sin(phase)
            tail = 0.08 * math.sin(phase)
        elif clip == "AttackFront":
            pitch = math.radians(12) * e; off = Vector((0, -0.12 * e, -0.03 * e))
            neck = math.radians(10) * e; head = math.radians(12) * e
            for pre, lg in q["legs"].items():
                leg[pre] = [(-math.radians(28) if lg["front"] else math.radians(18)) * e, 0.0, 0.0]
        elif clip == "Hitted":
            pitch = -math.radians(10) * e; off = Vector((0, 0.06 * e, 0.0))
            head = -math.radians(10) * e
            for pre, lg in q["legs"].items():
                if lg["front"]:
                    leg[pre] = [-math.radians(15) * e, -math.radians(25) * e, 0.0]
        elif clip == "Defence":
            off = Vector((0, 0.03 * e, -0.06 * e)); pitch = -math.radians(4) * e
            for pre, lg in q["legs"].items():
                leg[pre] = [0.0, (-1 if lg["front"] else 1) * math.radians(20) * e, 0.0]
        elif clip == "Death":
            f = i / max(nfr - 1, 1); f = f * f * (3 - 2 * f)
            roll = math.radians(q.get("deathRoll", 80)) * f
            for pre, lg in q["legs"].items():
                leg[pre] = [0.0, (-1 if lg["front"] else 1) * math.radians(40) * f, 0.0]
            head = math.radians(15) * f
        # body: pitch about the body centre, roll onto its side about a ground pivot, offset
        M = Matrix.Translation(off) @ _about(centre, Matrix.Rotation(pitch, 4, X))
        if roll:
            piv = Vector((q.get("deathSide", 1) * q.get("halfWidth", 0.3), centre.y, 0.0))
            M = _about(piv, Matrix.Rotation(roll * q.get("deathSide", 1), 4, Vector((0, 1, 0)))) @ M
        # rider rides the wolf body
        for n in list(A.keys()):
            if n != "Root" and n not in g["STATIC"]:
                A[n] = M @ A[n]
        A["WolfBody"] = M @ rest["WolfBody"]
        extra = {"WolfNeck": neck, "WolfHead": head, "WolfTail": tail}
        for n, h, tl, p in B:
            if n == "WolfBody":
                continue
            ang = extra.get(n, 0.0)
            if n[:-1] in q["legs"] and n[-1].isdigit():
                ang = leg[n[:-1]][int(n[-1]) - 1]
            A[n] = A[p] @ rest[p].inverted() @ rest[n] @ local_rot(n, ang)
    print("QUADRUPED wolf bones", len(wolf))


def before_keys(g):
    q = _q(g)
    if not q:
        return
    for n, *_ in _all_bones(q):
        g["RUBBLE_BONES"].append(n)
