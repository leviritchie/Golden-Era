"""Rider unseated and lance dropped in Death (Castle mounts, opt-in per unit).

The DEF champion rises out of the saddle, falls clear of the horse and drops the lance (Death f2-f7).
The base rig skins the rider's seat and legs to the horse's Hips and the lance rigidly to LeftHand, so
the rider stays fused to the saddle and the lance stays in the fist. Listed last in a unit's
"extensions", with:

  "riderThrow": {
    "riderHips": {"head": [x,y,z], "tail": [x,y,z],          # Spine head; rest axes copied from Hips
                  "boxes": [[lo, hi], ...], "exclude": [[lo, hi], ...]},   # Hips-dominant seat/leg verts
    "lance": {"parent": "LeftHand", "head": grip, "tail": tip,
              "segments": [[a, b]], "radius": r},               # parent-dominant verts near the shaft
    "keys": {"RiderHips": [[u, [tx,ty,tz], [rx,ry,rz]], ...],   # Death clip fraction u, metres / deg,
             "Lance":     [[u, [tx,ty,tz], [rx,ry,rz]], ...]}}  # rest frame, about the bone head
                                                                # (smoothstep between keys)

after_skin: RiderHips (child of Hips, Hips' rest axes so Spine's local rest is unchanged) and Lance
(child of the hand) are added; the seat/leg region and every rider-bone vertex's Hips weight move to
RiderHips, the shaft verts go to Lance at weight 1, and the mesh is split along the rider/horse and
lance/hand boundaries so separating them tears nothing.
after_pose: both follow their parents (no motion outside Death).
before_keys (listed last, so after castle_refine's world corrections): both re-follow their
parents, Spine is re-parented under RiderHips, and the Death keys are applied in the parent's rest
frame. Both are keyed with location (free-bone list), so the patch lane's rotation tables for Hips,
Spine and LeftHand keep composing with them. Units without "riderThrow" are untouched.
"""
import json
import math
import bmesh
from mathutils import Vector, Matrix, Euler

RIDER = ("Spine", "Spine1", "Spine2", "Neck", "Head")


def _rider_bone(n):
    return n in RIDER or n.startswith(("Left", "Right"))


def _cfg(g):
    return g["cfg"].get("riderThrow")


def _inbox(p, b):
    return all(b[0][i] <= p[i] <= b[1][i] for i in range(3))


def _segd(p, a, b):
    a, b = Vector(a), Vector(b)
    t = max(0.0, min(1.0, (p - a).dot(b - a) / max((b - a).length_squared, 1e-12)))
    return (p - (a + (b - a) * t)).length


def after_skin(g):
    C = _cfg(g)
    if not C:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]
    RH, LN = C["riderHips"], C["lance"]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    hb = eb["Hips"]
    b = eb.new("RiderHips"); b.head, b.tail = Vector(RH["head"]), Vector(RH["tail"]); b.roll = hb.roll
    b.parent = hb
    l = eb.new("Lance"); l.head, l.tail = Vector(LN["head"]), Vector(LN["tail"]); l.roll = 0
    l.parent = eb[LN["parent"]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for n in ("RiderHips", "Lance"):
        if n not in body.vertex_groups:
            body.vertex_groups.new(name=n)
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    gname = {i: n for n, i in gidx.items()}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()

    def dom(v):
        d = v[dl]
        return gname[max(d.keys(), key=lambda k: d[k])] if len(d) else None

    seat = {v.index for v in bm.verts if dom(v) == "Hips" and any(_inbox(v.co, bx) for bx in RH["boxes"])
            and not any(_inbox(v.co, bx) for bx in RH.get("exclude", []))}
    shaft = {v.index for v in bm.verts if dom(v) == LN["parent"]
             and any(_segd(v.co, a, b_) < LN["radius"] for a, b_ in LN["segments"])}

    def share(v):                                    # how much of the vertex is rider
        if v.index in seat:
            return 1.0
        d = v[dl]; tot = sum(d.values()) or 1.0
        return sum(w for k, w in d.items() if _rider_bone(gname[k])) / tot
    sh = {v.index: share(v) for v in bm.verts}

    # one split for both cuts: a face is lance (all verts on the shaft), rider (mean rider share >= 0.5)
    # or horse; edges between classes are split, so the classes can separate without stretching
    def cls(f):
        ix = [v.index for v in f.verts]
        if all(i in shaft for i in ix):
            return 2
        return 1 if sum(sh[i] for i in ix) / len(ix) >= 0.5 else 0
    fc = {f.index: cls(f) for f in bm.faces}
    edges = [e for e in bm.edges if len({fc[f.index] for f in e.link_faces}) > 1]
    bmesh.ops.split_edges(bm, edges=edges)
    bm.faces.ensure_lookup_table()
    # faces of two classes that touch only at a corner still share that vertex: give the other class's
    # faces their own copy
    nsep = 0
    for v in list(bm.verts):
        lf = list(v.link_faces)
        if len({fc[f.index] for f in lf}) > 1:
            c0 = fc[lf[0].index]
            for f in lf:
                if fc[f.index] != c0:
                    bmesh.utils.face_vert_separate(f, v); nsep += 1
    print("RIDERTHROW corner separations", nsep)
    hips, rh, ln = gidx["Hips"], gidx["RiderHips"], gidx["Lance"]
    n_seat = n_mix = n_lance = n_horse = 0
    hstat = {}; moved = set(); lance_verts = []
    bm.verts.index_update(); bm.verts.ensure_lookup_table()
    for v in bm.verts:
        if not v.link_faces:
            continue
        c = fc[v.link_faces[0].index]                # after the split every vertex is in one class
        d = v[dl]
        if c == 2:                                   # rigid on the hand until before_keys (castle_refine's
            d.clear(); d[gidx[LN["parent"]]] = 1.0; n_lance += 1    # propAim finds the lance by its hand weight)
            lance_verts.append(v.index)
        elif c == 1:                                 # rider: every horse-bone share moves to RiderHips
            mv = [k for k in d.keys() if not _rider_bone(gname[k]) and k != rh]
            if mv:
                w = sum(d[k] for k in mv)
                for k in mv:
                    del d[k]
                d[rh] = d.get(rh, 0.0) + w
                if w > 0.5:
                    n_seat += 1
                else:
                    n_mix += 1
        else:                                        # horse: rider-bone shares go to the vertex's own horse
            mv = [k for k in d.keys() if _rider_bone(gname[k])]       # bones in proportion (Hips if none), so
            if mv:                                                    # the horse's own weight gradients stay
                for k in mv:
                    hstat.setdefault(gname[k], []).append((d[k], tuple(round(c, 2) for c in v.co)))
                w = sum(d[k] for k in mv)
                for k in mv:
                    del d[k]
                rest_w = sum(d.values())
                if rest_w > 1e-6:
                    for k in list(d.keys()):
                        d[k] = d[k] * (1.0 + w / rest_w)
                else:
                    d[hips] = w
                n_horse += 1
                moved.add(v.index)
    # seamSmooth: the horse vertices that lost a rider share take the mean horse weights of their horse
    # neighbours (Jacobi, n passes), so dropping e.g. a 0.12 LeftArm share does not sharpen the Hips/HNeck0
    # gradient at the glove rest on the neck (h3_champion Death neck seam 2.3x on a 3.5 cm edge)
    for _ in range(C.get("seamSmooth", 0)):
        new = {}
        for i in moved:
            v = bm.verts[i]
            rows = [v[dl]] + [e.other_vert(v)[dl] for e in v.link_edges if e.link_faces and fc[e.link_faces[0].index] == 0] if v.link_edges else [v[dl]]
            acc = {}
            for d in rows:
                tot = sum(d.values()) or 1.0
                for k, w in d.items():
                    acc[k] = acc.get(k, 0.0) + w / tot / len(rows)
            new[i] = acc
        for i, acc in new.items():
            d = bm.verts[i][dl]; d.clear()
            for k, w in acc.items():
                if w > 1e-4:
                    d[k] = w
    bm.to_mesh(body.data); bm.free()
    g["_riderthrow_lance"] = lance_verts
    print("RIDERTHROW split edges", len(edges), "rider verts mostly horse-weighted", n_seat, "partly", n_mix,
          "horse verts off rider bones", n_horse, "lance verts", n_lance)
    for k, l in sorted(hstat.items(), key=lambda kv: -len(kv[1])):
        ws = [w for w, _ in l]; ps = [p for _, p in l]
        print("RIDERTHROW horse share", k, len(l), "max w %.2f" % max(ws), "lo", tuple(min(p[i] for p in ps) for i in range(3)),
              "hi", tuple(max(p[i] for p in ps) for i in range(3)))


def after_pose(g):
    C = _cfg(g)
    if not C:
        return
    rest = g["rest"]; parent_of = g["parent_of"]
    for n, par in (("RiderHips", "Hips"), ("Lance", C["lance"]["parent"])):
        rest[n] = g["rig"].data.bones[n].matrix_local.copy()
        parent_of[n] = par
        for A in g["posed_world"]:
            A[n] = A[par] @ rest[par].inverted() @ rest[n]


def _ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def _sample(keys, u):
    if not keys:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    ks = [(k[0], Vector(k[1]), Vector(k[2])) for k in keys]
    if u <= ks[0][0]:
        return ks[0][1], ks[0][2]
    for (u0, t0, r0), (u1, t1, r1) in zip(ks, ks[1:]):
        if u <= u1:
            w = _ease((u - u0) / max(u1 - u0, 1e-9))
            return t0.lerp(t1, w), r0.lerp(r1, w)
    return ks[-1][1], ks[-1][2]


def before_keys(g):
    C = _cfg(g)
    if not C:
        return
    bpy = g["bpy"]; rig = g["rig"]; rest = g["rest"]; parent_of = g["parent_of"]; posed = g["posed_world"]
    lpar = C["lance"]["parent"]
    death = {}
    for sg in json.load(open(g["MASTER"]))["segments"]:
        if sg["contractSuffix"] == "Death":
            n_ = max(sg["frameCount"] - 1, 1)
            for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                death[t] = i / n_
    keys = C.get("keys", {})
    for t, A in enumerate(posed):
        u = death.get(t)
        for n, par in (("RiderHips", "Hips"), ("Lance", lpar)):
            D = Matrix.Identity(4)
            if u is not None and keys.get(n):
                tr, rot = _sample(keys[n], u)
                h = rest[n].translation
                Rm = Euler(tuple(math.radians(x) for x in rot), 'XYZ').to_matrix().to_4x4()
                D = Matrix.Translation(tr) @ Matrix.Translation(h) @ Rm @ Matrix.Translation(-h)
            A[n] = A[par] @ rest[par].inverted() @ D @ rest[n]
    # the shaft moves from the hand to Lance now that castle_refine's propAim has run
    body = g["body"]; lg = body.vertex_groups["Lance"]; hg = body.vertex_groups[lpar]
    idx = g.get("_riderthrow_lance", [])
    hg.remove(idx); lg.add(idx, 1.0, 'REPLACE')
    # Spine now hangs from RiderHips (same rest axes as Hips, so its rotation keys mean the same thing)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    rig.data.edit_bones["Spine"].parent = rig.data.edit_bones["RiderHips"]
    bpy.ops.object.mode_set(mode='OBJECT')
    parent_of["Spine"] = "RiderHips"
    for n in ("RiderHips", "Lance"):
        g["RUBBLE_BONES"].append(n)              # keyed with location + scale (free-bone list)
    print("RIDERTHROW keyed", len(death), "death frames; Spine parent -> RiderHips")
