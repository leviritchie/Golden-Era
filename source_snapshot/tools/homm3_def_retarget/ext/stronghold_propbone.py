"""Held props on their own bone, so a thrown weapon can vanish and come back (Stronghold).

Orcs throw their axe and cyclopes their rock in the DEF shoot clip; the prop must leave the hand at
release and a new one appear when the unit picks the next one up. A prop bound to the hand bone
cannot do that, so this puts the prop on a child bone of the hand:

  "propBones": [{"name": "Axe", "parent": "RightHand", "head": grip, "tail": tip,
                 "region": {<segments|sphere|box>, "radius", "exclude", "color", "coreRadius"},
                 "regions": [...more regions, same bone...],
                 "hide": [{"clip": "ShootFront", "from": 3, "to": 13}]}]   # local frames, to exclusive
                                                                           # (null = clip end)
  "onlyWeight": {"bone": "LeftHand", "min": 0.99}   # optional: only vertices already bound to that bone
                           # (min share) can join -- separates a rigid staff from blended fingers and from
                           # foot/robe vertices that sit inside the prop's radius (h3_mage_upg, 2026-10-11)
  "bindAt": "before_keys"  # optional: cut in after_skin but bind in before_keys, after silhouetteRefine, so a
                           # propAim on the parent hand still fits the prop (needs a prop already cut free)
  "faceTest": "centroid"   # optional: a face is prop when its centroid is inside (default: all verts)
  "relocate": {"from": [at, axis, up], "to": [at, axis, up]}   # optional
Some meshes (T-pose re-meshes) model the weapon floating free of the hand. relocate moves the cut
prop rigidly at rest: point `from.at` goes to `to.at`, direction `from.axis` to `to.axis`, and
`from.up` (orthogonalised) to `to.up`. "head"/"tail" are then given in the relocated frame.
The bone follows the hand rigidly (head at the grip, so silhouetteRefine.propAim can name it and
swing it about the grip). Hidden frames scale it to ~0 about the grip. Region tests are those of
stronghold_props (colour-gated where "color" is given).

Hooks: after_skin (bone + vertex cut), after_pose (bone follows its parent), before_keys (hide,
and registers the bone for keying through the free-bone list).
"""
import json
import bmesh
from mathutils import Vector, Matrix
from stronghold_props import _region_test


DEFER = {}   # bindAt before_keys: bone -> vertex indices found in after_skin


def _specs(g):
    return g["cfg"].get("propBones", [])


def after_skin(g):
    specs = _specs(g)
    if not specs:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]; seg_dist = g["seg_dist"]; vert_color = g["vert_color"]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for s in specs:
        b = eb.new(s["name"]); b.head, b.tail = Vector(s["head"]), Vector(s["tail"]); b.roll = 0
        b.parent = eb[s["parent"]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for s in specs:
        if s["name"] not in body.vertex_groups:
            body.vertex_groups.new(name=s["name"])
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    for s in specs:
        tests = []
        for reg in ([s["region"]] if "region" in s else []) + s.get("regions", []):
            geo = _region_test(g, reg)
            segs = [(Vector(a), Vector(b)) for a, b in reg.get("segments", [])]
            tests.append((geo, reg.get("color"), segs, reg.get("coreRadius", 0.0)))

        def inside(p):
            for geo, col, segs, core in tests:
                if not geo(p):
                    continue
                if core > 0 and segs and min(seg_dist(p, a, b) for a, b in segs) < core:
                    return True
                if not col:
                    return True
                r, gg, b = (float(x) for x in vert_color(p))
                v = eval(col["expr"], {}, {"r": r, "g": gg, "b": b, "mx": max(r, gg, b), "mn": min(r, gg, b)})
                if col.get("min", -1e9) <= v <= col.get("max", 1e9):
                    return True
            return False

        ow = s.get("onlyWeight")   # {"bone": b, "min": w}: a vertex qualifies only when already bound to b
        if ow:                     # with weight >= min (keeps hand/foot copies that sit inside the prop)
            ob, omin = gidx[ow["bone"]], float(ow.get("min", 0.99))
            def wok(v):
                d = v[dl]; t = sum(d.values())
                return t > 0 and d.get(ob, 0.0) / t >= omin
        else:
            wok = lambda v: True
        ins = {v.index: inside(v.co) and wok(v) for v in bm.verts}
        for _ in range(s.get("cleanPasses", 1)):
            ins = {v.index: ins[v.index] and sum(ins[e.other_vert(v).index] for e in v.link_edges) >= 2 for v in bm.verts}
        if s.get("faceTest") == "centroid":
            # decimated meshes fuse a prop to the body with long triangles: a face is prop when its
            # centroid passes the test (vertex cleaning does not apply)
            fin = {f.index: inside(f.calc_center_median()) for f in bm.faces}
        else:
            fin = {f.index: all(ins[v.index] for v in f.verts) for f in bm.faces}
        edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1]
        if s.get("bindAt") == "before_keys":
            # deferred bind: the prop stays on the parent through silhouetteRefine (propAim on the hand keeps
            # fitting it) and moves onto its bone in before_keys; a reweight only, so the cut must need no split
            if edges:
                raise SystemExit(f"propBones {s['name']}: bindAt before_keys needs a prop already cut free "
                                 f"(propFix / props), {len(edges)} edges would split")
            faces = {i for i, f in fin.items() if f}
            DEFER[s["name"]] = [v.index for v in bm.verts if v.link_faces and all(f.index in faces for f in v.link_faces)]
            print("REGION propBone", s["name"], "deferred verts", len(DEFER[s["name"]]))
            continue
        bmesh.ops.split_edges(bm, edges=edges)
        bm.faces.ensure_lookup_table()
        faces = {i for i, f in fin.items() if f}
        n = 0
        for v in bm.verts:
            if v.link_faces and all(f.index in faces for f in v.link_faces):
                d = v[dl]; d.clear(); d[gidx[s["name"]]] = 1.0; n += 1
        print("REGION propBone", s["name"], "split edges", len(edges), "verts", n)
        rl = s.get("relocate")
        if rl:
            def frame(axis, up):
                a = Vector(axis).normalized(); b = (Vector(up) - a * a.dot(Vector(up))).normalized()
                return Matrix((a, b, a.cross(b))).transposed()
            Rm = frame(*rl["to"][1:]) @ frame(*rl["from"][1:]).transposed()
            src, dst = Vector(rl["from"][0]), Vector(rl["to"][0])
            bi = gidx[s["name"]]; nm = 0
            for v in bm.verts:
                d = v[dl]
                if len(d) == 1 and bi in d:
                    v.co = dst + Rm @ (v.co - src); nm += 1
            print("PROPBONE", s["name"], "relocated", nm, "verts")
    bm.to_mesh(body.data); bm.free()


def after_pose(g):
    specs = _specs(g)
    if not specs:
        return
    rest = g["rest"]; parent_of = g["parent_of"]
    for s in specs:
        n, par = s["name"], s["parent"]
        rest[n] = g["rig"].data.bones[n].matrix_local.copy()
        parent_of[n] = par
        for A in g["posed_world"]:
            A[n] = A[par] @ rest[par].inverted() @ rest[n]


def before_keys(g):
    specs = _specs(g)
    if not specs:
        return
    rest = g["rest"]; posed = g["posed_world"]
    # a prop-aimed bone was swung by silhouetteRefine in world space; its parent (the hand) was
    # moved by the same whole-body correction, so posed_world already holds the final pose
    segs = json.load(open(g["MASTER"]))["segments"]
    tiny = Matrix.Diagonal((1e-4, 1e-4, 1e-4, 1.0))
    for s in specs:
        n = s["name"]
        if n in DEFER:
            # the parent (hand) may have been swung by propAim after after_pose: re-derive the bone from its
            # final pose, then move the prop's vertices onto it (rigid ride: skinned positions unchanged)
            par = s["parent"]
            for A in posed:
                A[n] = A[par] @ rest[par].inverted() @ rest[n]
            body = g["body"]; vg = body.vertex_groups
            for v in DEFER[n]:
                for gg in list(body.data.vertices[v].groups):
                    vg[gg.group].remove([v])
                vg[n].add([v], 1.0, 'REPLACE')
            print("PROPBONE", n, "deferred bind verts", len(DEFER[n]))
        hidden = set()
        for h in s.get("hide", []):
            for sg in segs:
                if sg["contractSuffix"] != h["clip"]:
                    continue
                a = sg["globalStart"] + h.get("from", 0)
                b = sg["globalStart"] + h["to"] if h.get("to") is not None else sg["globalEnd"]
                hidden.update(range(a, min(b, sg["globalEnd"])))
        for t in sorted(hidden):
            M = posed[t][n]
            posed[t][n] = M @ tiny          # scale about the bone head (the grip)
        g["RUBBLE_BONES"].append(n)         # keyed with location + scale (free-bone list)
        print("PROPBONE", n, "hidden frames", sorted(hidden))
