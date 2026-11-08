"""Telescoping / extending rigid parts keyed from the DEF's own reach curve (config "propExtend").

A DEF can shoot a part out of the body (the upgraded automaton's drill arm telescopes forward by ~0.45
body lengths on its attack). A capture has no joint for that, rotations cannot lengthen anything, and
sliding the one rigid piece forward leaves a gap (a detached prop). This ext keeps every piece rigid:

  - the part (a region of vertices currently owned by `parent`, split free by the props cut) moves to
    its own child bone `<name>_0` (the tip);
  - `segments` rigid copies of that part are added as nested telescope sections `<name>_1..k`, each
    radially thinner (`copyScale`), hidden (scaled ~0 about their grip) while the part is retracted;
  - per clip, the tip slides along `axis` by the DEF-derived curve and section i by (k-i)/k of it (the
    innermost section stays seated where the part was), so neighbouring sections overlap and the arm
    reads as one telescope, never as a gap or a stretch. A curve whose step d/k exceeds 0.9 of the
    part's own length would open a gap and is refused.

  "propExtend": [{
    "name": "Drill", "parent": "Head",
    "axis": [-1, 0, 0],                       # direction the part extends along
    "region": {"box": [[x0,y0,z0],[x1,y1,z1]], "exclude": [...]},  # stronghold_props region forms
                                              # axis and region are in the mesh's own frame, like "props";
                                              # a quadruped "restYawDeg" turn is applied here the same way
    "segments": 2, "copyScale": 0.07,         # sections k >= 1; section i radial scale 1 - copyScale * i
    "showAbove": 0.02,                        # sections appear once the tip is out this far (body lengths)
    "clips": {"AttackFront": [0, 0, 0, 0.1, 0.29, 0.37, 0.39, 0.33, 0.2, 0.06]},   # tip offset per DEF
                                              # frame, in rest body lengths along `axis`; one value per frame
    "reason": "..."}]

Fail closed: a clip whose value count differs from its DEF segment's frame count, an empty region, or a
part not owned by `parent` raises. Everything happens at before_keys (after the shatter/rubble copy, so
debris never duplicates the sections). Measured by artifacts/claude_takeover_20260927/worker_b/tools/reach.py
(peak forward extent against Idle key 0 in body lengths). Proof tier of a unit using it: generated artifact.
"""
import json
import math
import bmesh
from mathutils import Vector, Matrix
from stronghold_props import _region_test


def before_keys(g):
    specs = g["cfg"].get("propExtend", [])
    if not specs:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]; rest = g["rest"]; parent_of = g["parent_of"]
    posed = g["posed_world"]
    segs = json.load(open(g["MASTER"]))["segments"]
    TINY = Matrix.Diagonal((1e-4, 1e-4, 1e-4, 1.0))
    allv = [v.co.copy() for v in body.data.vertices]
    yaw = g["cfg"].get("quadruped", {}).get("restYawDeg")
    Rz = Matrix.Rotation(math.radians(yaw), 3, 'Z') if yaw else Matrix.Identity(3)
    Rzi = Rz.inverted()
    for s in specs:
        name, par, k = s["name"], s["parent"], int(s.get("segments", 2))
        ax = (Rz @ Vector(s["axis"])).normalized()
        proj = [p.dot(ax) for p in allv]
        L = max(proj) - min(proj)
        test0 = _region_test(g, s["region"])
        test = lambda p, t0=test0: t0(Rzi @ p)
        gidx = {vg.name: vg.index for vg in body.vertex_groups}
        pi = gidx[par]
        bm = bmesh.new(); bm.from_mesh(body.data)
        dl = bm.verts.layers.deform.verify()
        bm.verts.ensure_lookup_table()

        def owned(v):
            d = v[dl]
            return bool(d) and max(d.items(), key=lambda kv: kv[1])[0] == pi
        ins = {v.index: test(v.co) and owned(v) for v in bm.verts}
        fin = {f.index: all(ins[v.index] for v in f.verts) for f in bm.faces}
        if not any(fin.values()):
            raise RuntimeError(f"propExtend {name}: no face of {par} inside the region")
        edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1]
        bmesh.ops.split_edges(bm, edges=edges)            # face indices survive the split
        bm.faces.ensure_lookup_table()
        faces = [f for f in bm.faces if fin.get(f.index)]
        pv = {v for f in faces for v in f.verts}
        if any(not all(fin.get(f.index) for f in v.link_faces) for v in pv):
            raise RuntimeError(f"propExtend {name}: part still welded to the body after the cut")
        P = [v.co.copy() for v in pv]
        rear = min(p.dot(ax) for p in P)
        cen = sum(P, Vector()) / len(P)
        grip = cen + ax * (rear - cen.dot(ax))
        lenp = max(p.dot(ax) for p in P) - rear
        names = [f"{name}_{i}" for i in range(k + 1)]
        for n in names:
            if n not in body.vertex_groups:
                body.vertex_groups.new(name=n)
        gidx = {vg.name: vg.index for vg in body.vertex_groups}
        for v in pv:
            d = v[dl]; d.clear(); d[gidx[names[0]]] = 1.0
        for i in range(1, k + 1):
            dup = bmesh.ops.duplicate(bm, geom=list(pv) + faces + list({e for f in faces for e in f.edges}))
            sc = 1.0 - float(s.get("copyScale", 0.07)) * i
            for v in (x for x in dup["geom"] if isinstance(x, bmesh.types.BMVert)):
                a = grip + ax * (v.co - grip).dot(ax)
                v.co = a + (v.co - a) * sc
                d = v[dl]; d.clear(); d[gidx[names[i]]] = 1.0
        bm.to_mesh(body.data); bm.free(); body.data.update()
        print("PROPEXTEND", name, "part verts", len(pv), "faces", len(faces), "split edges", len(edges),
              "sections", k, "part length", round(lenp, 3), "body length", round(L, 3))

        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        eb = rig.data.edit_bones
        for n in names:
            b = eb.new(n); b.head = grip; b.tail = grip + ax * max(lenp, 0.05); b.roll = 0; b.parent = eb[par]
        bpy.ops.object.mode_set(mode='OBJECT')
        for n in names:
            rest[n] = rig.data.bones[n].matrix_local.copy(); parent_of[n] = par
            for A in posed:
                A[n] = A[par] @ rest[par].inverted() @ rest[n]

        show = float(s.get("showAbove", 0.02))
        if k < 1:
            raise RuntimeError(f"propExtend {name}: segments must be >= 1")
        out = {}
        for clip, curve in s["clips"].items():
            cs = [sg for sg in segs if sg["contractSuffix"] == clip]
            if not cs:
                raise RuntimeError(f"propExtend {name}: no DEF segment {clip}")
            if max(curve) * L / k > 0.9 * lenp:
                raise RuntimeError(f"propExtend {name}: {clip} step {max(curve) * L / k:.3f} > 0.9 x part length {lenp:.3f} (gap); add segments")
            for sg in cs:
                if len(curve) != sg["frameCount"]:
                    raise RuntimeError(f"propExtend {name}: {clip} has {len(curve)} values for {sg['frameCount']} DEF frames")
                for j, dL in enumerate(curve):
                    out[sg["globalStart"] + j] = float(dL) * L
        for t, A in enumerate(posed):
            d = out.get(t, 0.0)
            for i, n in enumerate(names):
                A[n] = A[n] @ Matrix.Translation((0, d * (k - i) / k, 0))
            if d < show * L:
                for n in names[1:]:
                    A[n] = A[n] @ TINY
        for n in names:
            g["RUBBLE_BONES"].append(n)     # keyed with location + scale (free-bone list)
        print("PROPEXTEND", name, "clips", {c: max(v) for c, v in s["clips"].items()})
