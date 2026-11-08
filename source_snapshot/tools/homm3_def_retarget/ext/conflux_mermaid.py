"""Conflux mermaids: yaw toward the DEF's profile view + fish-tail motion (hook module for
build_unit.py; list it in a unit's "extensions" AFTER hand_keys).

Weights. On the decimated Meshy mermaid meshes (hundreds of loose pieces) Blender's bone heat
fails on every vertex and surface_weights' geodesic fallback leaves NaN on pieces no bone seed
reaches (they then stay at rest: a ghost torso). "conflux": {"mermaidWeights": {...}} replaces
every non-tail weight at after_skin with a thickness-normalised proximity rule: a vertex's
distance to each torso/arm bone segment is divided by that bone's radius (`radius`, keyed by bone
name or by suffix: Hips, Spine, Neck, Head, Shoulder, Arm, ForeArm, Hand), weights are
1/(d/r) ** `power` over the best 3, then smoothed `smooth` times over mesh edges. The radius keeps
belly skin under a resting fist with the spine (a thin hand bone loses to a thick torso bone) while
the fist itself stays with the hand. The mesh is cut where lower-arm faces meet body faces
(`splitArms`, default true; loose fragments of at most `islandVoteMaxVerts` (200) vertices go
whole to their majority class; with `handColor` {"minRedRatio", "reach"} skin of the hand colour
(red over green and blue) within reach of a Hand segment is that hand's, first; with `cutUpperBelowZ` also the upper arm below that height, where
Meshy fused it to the flank) and around each `armFins` box ({"bone": "RightArm", "box": [lo, hi]}:
the membranes Meshy fused along the upper arm), whose vertices ride that bone rigidly; tail vertices inside `finBox` [lo, hi] ride the last tail
bone rigidly. Optionally (`islandMaxVerts`, off by default: on these meshes the arms themselves
are made of such fragments) loose pieces up to that size copy the weights of the nearest vertex
outside them. Tail vertices keep their Tail_* weights and fill any missing
share (the waist blend, lost to NaN) from the torso bones only; vertices below `lowZ` that are not
tail copy the weights of the nearest tail vertex (fins and spines on the coil).

Yaw. The shared sprite camera looks at the model from its front-left; the DEF draws the mermaid
nearly in profile with the tail running to screen left, so the Meshy mesh (facing -Y, tail behind
it along +Y) renders head-on with the tail hidden. "conflux": {"yawDeg": d} turns every posed bone
(except Root) about +Z through the origin by d in every frame -- like castle_yaw, but at
before_keys, after the naga tail solve: the solver plants the coil on its rest targets and rides
the waist with the hips, so turning earlier would twist the coil against itself. The sprite camera
is re-centred horizontally on the turned rest mesh (build_unit fitted it on the unturned one; the
vertical fit is unchanged by a turn about Z). The naga tail's Move `behind` direction is in the
unturned frame, so give it turned back by -d.

The water / ice / frost elementals are mermaids: a torso on a long coiled fish tail with a fin.
The shared naga `tail` builds the articulated chain (Tail_00..) and, in Move, uncoils it into a
flat trailing wave on the ground. Everywhere else the chain beyond the ground contact lies still,
but the DEF mermaid's fin sways in Idle, flicks up and down while she slides (Move) and the tail
whips when she is hit. This hook bends the chain on top of that, per clip:

"conflux": {"tailSway": {"<contractSuffix>": {
    "from": k0,                    # first bent bone (default: the ground-contact index gidx_)
    "side": deg, "up": deg,        # travelling wave amplitude per bone, about world up / about
                                   #   the bone's horizontal normal (positive up lifts the tip)
    "cycles": n, "lag": rad,       # whole waves over the clip (integer keeps loops closed) and
                                   #   phase delay per bone (the wave runs toward the tip)
    "power": p,                    # amplitude grows as ((k-k0+1)/(N-k0)) ** p toward the tip
    "curl": [{"f": i, "side": deg, "up": deg}, ...]   # keyed extra bend per bone (lerped)
}}}

Every segment with that suffix gets the motion (1-frame Idle bookends take frame 0's pose, as the
clip's own first frame does). Bends are applied root-to-tip, each about its bone's current head,
so the chain stays connected and bone lengths are kept. Runs at before_keys, after the naga tail
solve and the silhouette fit; only Tail_* world matrices change.
"""
import json
import math
from mathutils import Matrix, Vector


def _lerp_keys(keys, i, name):
    ks = sorted((k["f"], k.get(name, 0.0)) for k in keys)
    if not ks:
        return 0.0
    if i <= ks[0][0]:
        return ks[0][1]
    if i >= ks[-1][0]:
        return ks[-1][1]
    for (f0, a0), (f1, a1) in zip(ks, ks[1:]):
        if f0 <= i <= f1:
            u = (i - f0) / max(f1 - f0, 1)
            u = u * u * (3 - 2 * u)
            return a0 + (a1 - a0) * u
    return 0.0


def _suffix(name):
    for k in ("ForeArm", "Shoulder", "Hand", "Arm", "Spine", "Hips", "Neck", "Head"):
        if k in name:
            return k
    return name


def _proximity(P, bones, J, R, power):
    import numpy as np
    D = np.zeros((len(P), len(bones)))
    for k, (_, h, t, _) in enumerate(bones):
        a, b = np.array(J[h]), np.array(J[t]); ab = b - a
        u = np.clip((P - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
        D[:, k] = np.linalg.norm(P - (a + u[:, None] * ab), axis=1)
    return np.maximum(D / R, 1e-3) ** -power


def _split_lower_arms(g, P, names, W, tail, fins, cut_up_z=None):
    """Cut the mesh where lower-arm faces meet body faces (fists fused to belly/hips) and around
    boxed arm fins; returns the per-vertex class after the cut (0 none, 1 left / 2 right lower
    arm, 3+i fin box i)."""
    import bmesh
    import numpy as np
    body = g["body"]
    dom = W.argmax(1)
    lowcls = np.zeros(len(P), int)
    for si, side in enumerate(("Left", "Right")):
        ids = [k for k, nm in enumerate(names) if nm.startswith(side) and ("ForeArm" in nm or "Hand" in nm)]
        lowcls[np.isin(dom, ids) & ~tail] = si + 1
        if cut_up_z is not None:
            up = [k for k, nm in enumerate(names) if nm == side + "Arm"]
            lowcls[np.isin(dom, up) & ~tail & (P[:, 2] < cut_up_z)] = si + 1
    # fists pressed on the belly: skin of the hand colour within reach of a hand is that hand's
    hc = g["cfg"].get("conflux", {}).get("mermaidWeights", {}).get("handColor")
    if hc:
        from mathutils import kdtree
        hz = np.load(g["OUT"] + ".heat.npz"); HP, HC = hz["P"], hz["C"]
        kd = kdtree.KDTree(len(HP))
        for i, q in enumerate(HP):
            kd.insert(q, i)
        kd.balance()
        Cv = HC[[kd.find(q)[1] for q in P]]
        rr = hc.get("minRedRatio", 1.25)
        red = (Cv[:, 0] > rr * Cv[:, 1]) & (Cv[:, 0] > rr * Cv[:, 2])
        J = g["J"]
        for si, side in enumerate(("Left", "Right")):
            a, b = np.array(J[side + "Hand"]), np.array(J[side + "Hand_End"]); ab = b - a
            u = np.clip((P - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
            d = np.linalg.norm(P - (a + u[:, None] * ab), axis=1)
            m = red & (d < hc.get("reach", 0.12)) & ~tail
            lowcls[m] = si + 1
        print("CONFLUX mermaid hand-colour verts", int((red & (lowcls > 0)).sum()))
    # the decimated Meshy surface is hundreds of loose fragments: a small fragment goes whole to
    # the lower arm that owns most of it, or whole to the body (fist chips resting on the belly)
    iv = g["cfg"].get("conflux", {}).get("mermaidWeights", {}).get("islandVoteMaxVerts", 200)
    if iv:
        roots = _islands(body)
        ids, inv, cnt = np.unique(roots, return_inverse=True, return_counts=True)
        for k in np.nonzero(cnt <= iv)[0]:
            m = inv == k
            c = np.bincount(lowcls[m], minlength=3)
            lowcls[m] = int(c.argmax())
    for fi, fb in enumerate(fins):
        lo, hi = np.array(fb["box"][0]), np.array(fb["box"][1])
        lowcls[np.all((P >= lo) & (P <= hi), 1) & ~tail] = 3 + fi
    NC = 3 + len(fins)
    bm = bmesh.new(); bm.from_mesh(body.data); bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    fcls = {}
    for f in bm.faces:
        c = np.bincount([lowcls[v.index] for v in f.verts], minlength=NC)
        fcls[f.index] = int(c.argmax()) if c[1:].max() * 2 > len(f.verts) else 0
    # majority filter over face neighbours: stray patches (a few body faces inside a fist, a chip of
    # fist on the belly) would otherwise be cut out as floating shards
    for _ in range(4):
        nxt = {}
        for f in bm.faces:
            nb = [fcls[o.index] for e in f.edges for o in e.link_faces if o is not f]
            if nb:
                c = np.bincount(nb + [fcls[f.index]], minlength=NC)
                nxt[f.index] = int(c.argmax()) if c.max() > c[fcls[f.index]] else fcls[f.index]
            else:
                nxt[f.index] = fcls[f.index]
        fcls = nxt
    cut = [e for e in bm.edges if len({fcls[f.index] for f in e.link_faces}) > 1]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.verts.ensure_lookup_table(); bm.verts.index_update()
    out = np.zeros(len(bm.verts), int)
    for v in bm.verts:
        cs = [fcls[f.index] for f in v.link_faces]
        out[v.index] = max(set(cs), key=cs.count) if cs else 0
    bm.to_mesh(body.data); bm.free(); body.data.update()
    print("CONFLUX mermaid arm cut edges", len(cut), "verts", len(out))
    return out


def _islands(body):
    """Connected surface pieces (edges + coincident UV-seam copies), as a root id per vertex."""
    import numpy as np
    vs = body.data.vertices; n = len(vs)
    par = list(range(n))
    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a
    for e in body.data.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            par[a] = b
    first = {}
    for v in vs:
        k = tuple(round(c, 5) for c in v.co)
        if k in first:
            a, b = find(v.index), find(first[k])
            if a != b:
                par[a] = b
        else:
            first[k] = v.index
    return np.array([find(i) for i in range(n)])


def _stick_islands(body, max_verts):
    """Small loose pieces (elbow fins, chips Meshy left beside a fist) move rigidly with the part
    they touch: every vertex takes the weights of the nearest vertex outside its piece."""
    import numpy as np
    from mathutils import kdtree
    vs = body.data.vertices; n = len(vs)
    roots = _islands(body)
    ids, cnt = np.unique(roots, return_counts=True)
    small = set(ids[cnt <= max_verts].tolist())
    if not small:
        return 0
    big = [i for i in range(n) if roots[i] not in small]
    kd = kdtree.KDTree(len(big))
    for i in big:
        kd.insert(vs[i].co, i)
    kd.balance()
    done = 0
    for r in small:
        mem = np.nonzero(roots == r)[0]
        best = min((kd.find(vs[int(i)].co) for i in mem), key=lambda x: x[2])
        src = vs[best[1]]
        w = [(e.group, e.weight) for e in src.groups]
        for i in mem:
            i = int(i)
            for e in list(vs[i].groups):
                body.vertex_groups[e.group].remove([i])
            for gk, ww in w:
                body.vertex_groups[gk].add([i], ww, 'REPLACE')
        done += 1
    return done


def after_skin(g):
    spec = g["cfg"].get("conflux", {}).get("mermaidWeights")
    if not spec:
        return
    import numpy as np
    from mathutils import kdtree
    body, BONES, J = g["body"], g["BONES"], g["J"]
    STATIC = g.get("STATIC", set())
    bones = [b for b in BONES if b[0] not in STATIC and b[1] in J and b[2] in J]
    names = [b[0] for b in bones]
    rad = spec.get("radius", {})
    R = np.array([rad.get(nm, rad.get(_suffix(nm), 0.1)) for nm in names])
    arm = np.array([any(x in nm for x in ("Shoulder", "Arm", "Hand")) for nm in names])

    def tail_state():
        gname = {vg.index: vg.name for vg in body.vertex_groups}
        n = len(body.data.vertices)
        TS = np.zeros(n); TWrow = [dict() for _ in range(n)]
        for v in body.data.vertices:
            for e in v.groups:
                nm = gname[e.group]
                if nm.startswith("Tail_") and e.weight > 1e-6:
                    TWrow[v.index][nm] = e.weight; TS[v.index] += e.weight
        return TS, TWrow

    P = np.array([v.co[:] for v in body.data.vertices])
    TS, TWrow = tail_state(); tail = TS > 1e-4
    W = _proximity(P, bones, J, R, spec.get("power", 6)); W[np.ix_(tail, arm)] = 0
    fins = spec.get("armFins", [])
    if spec.get("splitArms", True):
        lowcls = _split_lower_arms(g, P, names, W, tail, fins, spec.get("cutUpperBelowZ"))
        P = np.array([v.co[:] for v in body.data.vertices])
        TS, TWrow = tail_state(); tail = TS > 1e-4
        W = _proximity(P, bones, J, R, spec.get("power", 6)); W[np.ix_(tail, arm)] = 0
    else:
        lowcls = np.zeros(len(P), int)
    vs = body.data.vertices; n = len(vs)
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    # the tail fin rides the last tail bone rigidly (a blend across the last two bones shears its
    # wide lobes whenever the tip bends)
    fb = spec.get("finBox")
    TAILB = g.get("TAILB") or []
    if fb and TAILB:
        lo, hi = np.array(fb[0]), np.array(fb[1])
        m = np.all((P >= lo) & (P <= hi), 1) & tail
        for i in np.nonzero(m)[0]:
            TWrow[i] = {TAILB[-1]: 1.0}; TS[i] = 1.0
        print("CONFLUX mermaid fin verts", int(m.sum()))
    # a lower-arm vertex keeps only its own arm chain; an upper-arm vertex no other arm's lower
    # part; every other vertex no forearm/hand weight (a fist resting on the belly or hip must
    # not pull skin with it, and a raised forearm must not drag hip weight along)
    cls = np.zeros(n, int)            # 0 body, 1/3 left/right upper arm, 2/4 left/right lower arm
    all_low = [k for k, nm in enumerate(names) if "ForeArm" in nm or "Hand" in nm]
    dom = W.argmax(1)
    for si, side in enumerate(("Left", "Right")):
        low_ids = [k for k, nm in enumerate(names) if nm.startswith(side) and ("ForeArm" in nm or "Hand" in nm)]
        up_ids = [k for k, nm in enumerate(names) if nm == side + "Arm"]
        chain = [k for k, nm in enumerate(names) if nm.startswith(side) and any(x in nm for x in ("Arm", "Hand"))]
        lower = (lowcls == si + 1) & ~tail
        upper = np.isin(dom, up_ids) & ~tail & (lowcls == 0)
        cls[upper] = 2 * si + 1; cls[lower] = 2 * si + 2
        keep = np.zeros(len(names), bool); keep[chain] = True
        W[lower] *= keep
        other = [k for k in all_low if k not in low_ids]
        Wu = W[upper]; Wu[:, other] = 0; W[upper] = Wu
    Wb = W[cls == 0]; Wb[:, all_low] = 0; W[cls == 0] = Wb
    # boxed arm fins (membranes Meshy fused along the upper arm) ride their bone rigidly
    for fi, fb in enumerate(fins):
        m = (lowcls == 3 + fi) & ~tail
        W[m] = 0; W[m, names.index(fb["bone"])] = 1.0
        cls[m] = 5 + fi
    zero = W.sum(1) < 1e-9
    W[zero, names.index("Hips")] = 1.0
    idx = np.argsort(-W, 1)[:, 3:]; np.put_along_axis(W, idx, 0, 1)
    W /= W.sum(1, keepdims=True)
    # smooth over mesh edges, only between vertices of the same class (body / left / right lower arm)
    E = np.array([e.vertices[:] for e in body.data.edges])
    c0, c1 = cls[E[:, 0]], cls[E[:, 1]]
    side0, side1 = (c0 + 1) // 2, (c1 + 1) // 2          # 0 body, 1 left, 2 right
    lowbody = ((c0 % 2 == 0) & (c0 > 0) & (c1 == 0)) | ((c1 % 2 == 0) & (c1 > 0) & (c0 == 0))
    E = E[~lowbody & ((side0 == side1) | (side0 == 0) | (side1 == 0))]
    E = E[((cls[E[:, 0]] < 5) & (cls[E[:, 1]] < 5)) | (cls[E[:, 0]] == cls[E[:, 1]])]
    deg = np.bincount(E.ravel(), minlength=n) + 1.0
    for _ in range(spec.get("smooth", 2)):
        S = W.copy()
        np.add.at(S, E[:, 0], W[E[:, 1]]); np.add.at(S, E[:, 1], W[E[:, 0]])
        W = S / deg[:, None]
    idx = np.argsort(-W, 1)[:, 3:]; np.put_along_axis(W, idx, 0, 1)
    W /= W.sum(1, keepdims=True)
    lowZ = spec.get("lowZ", J["Hips"][2] - 0.12)
    low = (~tail) & (P[:, 2] < lowZ)
    src = {}
    if low.any() and tail.any():
        ti = np.nonzero(tail)[0]
        kd = kdtree.KDTree(len(ti))
        for j in ti:
            kd.insert(P[j], int(j))
        kd.balance()
        src = {int(i): kd.find(P[i])[1] for i in np.nonzero(low)[0]}
    for nm in names:
        if nm not in gi:
            body.vertex_groups.new(name=nm); gi[nm] = body.vertex_groups[nm].index
    n_low = 0
    for v in vs:
        i = v.index
        for e in list(v.groups):
            body.vertex_groups[e.group].remove([i])
        j = src.get(i, i)
        n_low += i in src
        share = 1.0 - min(TS[j], 1.0)
        rows = list(TWrow[j].items()) + [(names[k], W[j, k] * share) for k in np.nonzero(W[j])[0]]
        # glTF skins carry 4 influences: keep the top 4 so the GLB deforms like the .blend
        rows = sorted((r for r in rows if r[1] > 1e-4), key=lambda r: -r[1])[:4]
        tot = sum(w for _, w in rows)
        for nm, w in rows:
            body.vertex_groups[nm].add([i], float(w / tot), 'REPLACE')
    ni = _stick_islands(body, spec["islandMaxVerts"]) if spec.get("islandMaxVerts") else 0
    print("CONFLUX mermaid small islands re-attached", ni)
    print("CONFLUX mermaidWeights verts", n, "tail", int(tail.sum()), "low->tail", n_low,
          "arm classes", [int((cls == c).sum()) for c in range(5 + len(fins))])


def after_pose(g):
    """worldKeys: like hand_keys, but each rotation is about the REST WORLD axes (X right, Y back,
    Z up of the unturned model) carried by the bone's parent, not about the bone's own roll axes.
    A forearm pointing forward (-Y) sits at Blender's roll singularity, so its roll-0 axes flip
    with a millimetre of joint change; "RightForeArm": [-60, 0, 0] always lifts the tip."""
    spec = g["cfg"].get("conflux", {}).get("worldKeys")
    if not spec:
        return
    from mathutils import Euler
    rest, parent_of, pw = g["rest"], g["parent_of"], g["posed_world"]
    segs = json.load(open(g["MASTER"]))["segments"]
    kids = {}
    for b, p_ in parent_of.items():
        kids.setdefault(p_, []).append(b)

    def desc(b):
        out = []
        for c in kids.get(b, []):
            out += [c] + desc(c)
        return out

    q = lambda e: Euler([math.radians(x) for x in e], 'XYZ').to_quaternion()
    n_ = 0
    for s_ in segs:
        keys = spec.get(s_["contractSuffix"])
        if not keys:
            continue
        bones = sorted({b for k in keys for b in k["bones"]}, key=lambda b: len(desc(b)), reverse=True)
        for i, t in enumerate(range(s_["globalStart"], s_["globalEnd"])):
            A = pw[t]
            for b in bones:
                ks = sorted((k["f"], k["bones"][b]) for k in keys if b in k["bones"])
                if i <= ks[0][0]:
                    Q = q(ks[0][1])
                elif i >= ks[-1][0]:
                    Q = q(ks[-1][1])
                else:
                    for (f0, e0), (f1, e1) in zip(ks, ks[1:]):
                        if f0 <= i <= f1:
                            u = (i - f0) / max(f1 - f0, 1); Q = q(e0).slerp(q(e1), u); break
                if b not in A:
                    continue
                Rb = rest[b].to_3x3()
                Rl = (Rb.inverted() @ Q.to_matrix() @ Rb).to_4x4()
                old = A[b].copy(); new = old @ Rl
                D = new @ old.inverted()
                A[b] = new
                for c in desc(b):
                    if c in A:
                        A[c] = D @ A[c]
            n_ += 1
    print("CONFLUX worldKeys frames", n_)


def _yaw(g):
    yaw = g["cfg"].get("conflux", {}).get("yawDeg")
    if not yaw:
        return
    Rz = Matrix.Rotation(math.radians(yaw), 4, 'Z')
    for A in g["posed_world"]:
        for n in list(A):
            if n != "Root":
                A[n] = Rz @ A[n]
    print("CONFLUX yaw", yaw, "frames", len(g["posed_world"]))


def _recentre_camera(g):
    yaw = g["cfg"].get("conflux", {}).get("yawDeg")
    if not yaw:
        return
    cam = g["cam"]; right, s_px = g["right"], g["s_px"]
    Rz = Matrix.Rotation(math.radians(yaw), 3, 'Z')
    xs0 = [p.dot(right) for p in g["rv"]]
    xs1 = [(Rz @ p).dot(right) for p in g["rv"]]
    shift = ((max(xs1) + min(xs1)) - (max(xs0) + min(xs0))) / 2
    cam.location = cam.location + right * shift
    print("CONFLUX yaw camera recentred by", round(shift, 3))


def before_keys(g):
    _yaw(g)
    _recentre_camera(g)
    spec = g["cfg"].get("conflux", {}).get("tailSway")
    TAILB = g.get("TAILB") or []
    if not spec or not TAILB:
        return
    pw = g["posed_world"]; N = len(TAILB)
    segs = json.load(open(g["MASTER"]))["segments"]
    Z = Vector((0, 0, 1))
    n_frames = 0
    for suffix, c in spec.items():
        cand = [s for s in segs if s["contractSuffix"] == suffix]
        if not cand:
            continue
        n = max(s["frameCount"] for s in cand)
        k0 = int(c.get("from", g.get("gidx_", N // 3)))
        k0 = max(0, min(k0, N - 1))
        side, up = c.get("side", 0.0), c.get("up", 0.0)
        cyc, lag, pw_ = c.get("cycles", 1), c.get("lag", 0.6), c.get("power", 1.0)
        curl = c.get("curl", [])
        for s in cand:
            for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
                A = pw[t]
                ph = 2 * math.pi * cyc * i / max(n, 1)
                cs = _lerp_keys(curl, i, "side") if curl else 0.0
                cu = _lerp_keys(curl, i, "up") if curl else 0.0
                for k in range(k0, N):
                    w = ((k - k0 + 1) / (N - k0)) ** pw_
                    a_side = side * w * math.sin(ph - lag * (k - k0)) + cs
                    a_up = up * w * math.sin(ph - lag * (k - k0) + math.pi / 2) + cu
                    if abs(a_side) < 1e-4 and abs(a_up) < 1e-4:
                        continue
                    M = A[TAILB[k]]
                    p = M.translation.copy()
                    d = M.to_3x3().col[1].normalized()
                    ax = d.cross(Z)
                    R = Matrix.Rotation(math.radians(a_side), 4, Z)
                    if ax.length > 1e-6 and abs(a_up) > 1e-4:
                        R = R @ Matrix.Rotation(math.radians(a_up), 4, ax.normalized())
                    X = Matrix.Translation(p) @ R @ Matrix.Translation(-p)
                    for j in range(k, N):
                        A[TAILB[j]] = X @ A[TAILB[j]]
                n_frames += 1
    print("CONFLUX tailSway frames", n_frames, "clips", sorted(spec))
