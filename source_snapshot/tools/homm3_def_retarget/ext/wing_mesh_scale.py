"""Root-ramped wing enlargement (hook module for build_unit.py; list "wing_mesh_scale" LAST in "extensions", after
"wing_chain" and "flight_life"; config key "wingMeshScale").

Why: the Meshy dragons' wings are about 60% of the DEF span (2026-10-09 authenticity pass; render proofs at
1.4/1.6/1.8 in V:/olden_port_work/authenticity/wingscale/, x1.6 approved). Scaling the Wing?_00 bone would also
scale the root skin against the body and open a seam, and scaling the mesh before the build changes the motion:
the sprite camera, silhouetteRefine, the quadruped fits and the wing_chain fit all match the mesh's silhouette to the
DEF, and on the bigger wings the green dragon's approved Death, Defence and AttackFront came out 0.1-0.5 m and up to
50 deg (wings) off. So the whole build (chain, weights, every fit) runs on the original mesh, and only then:

before_keys (runs after every fit; all world poses are final)
  Per wing chain built by wing_chain (g["WCH"]): its vertices (total weight on the chain's bones > 0.5, so the
  claws/spikes wing_chain adopted come along) move about the chain head (the shoulder) by s(d),
  where d is the vertex's rest distance to the nearest vertex outside the wing (the body):
    s = 1 for d <= bodyGap, ramping linearly to `factor` over the next `ramp` metres, and `factor` beyond.
  The chain bones' heads/tails scale about the same head by `factor`. A uniform scale about one point keeps every
  bone's direction and roll and scales every parent->child offset alike, so this holds for a straight chain and for
  a finger fan (wing_chain "fan": arm, forearm and per-finger knuckle/tip bones, scaled about the fan's shoulder
  heads[0]); only rotations are keyed for these bones, so the keyed motion is unchanged in angle and the enlarged
  wing bends at proportionally placed joints. Fan seam vertices anchored to the parent (chain weight <= 0.5) stay put,
  and the root ramp (bodyGap/ramp) keeps the rest of the shoulder seam closed. Primaries chains are not supported.
  Coincident copies (UV-seam splits) share a position, so they share d and s and stay welded.

"wingMeshScale": {"factor": 1.6, "bodyGap": 0.03, "ramp": 0.06, "bones": ["LeftWing", "RightWing"]}
("bones" defaults to every chain; names are the `wings` block bones the chains were built from)
"""
import numpy as np


def before_keys(g):
    opt = g["cfg"].get("wingMeshScale")
    if not opt:
        return
    import bpy
    from mathutils import Vector, kdtree
    if not g.get("WCH"):
        raise SystemExit("wingMeshScale: no wing chains (list wing_mesh_scale after wing_chain in extensions)")
    body, rig = g["body"], g["rig"]; me = body.data
    fac, gap, ramp = float(opt["factor"]), float(opt.get("bodyGap", 0.03)), float(opt.get("ramp", 0.06))
    want = set(opt.get("bones", [ch["bone"] for ch in g["WCH"]]))
    P = np.array([v.co[:] for v in me.vertices])
    chains = [ch for ch in g["WCH"] if ch["bone"] in want]
    if any(ch.get("prim") for ch in chains):
        raise SystemExit("wingMeshScale: primaries chains are not supported")
    # members: total weight on the chain's bones > 0.5 -- the chain rows plus the claws/spikes wing_chain adopted
    gname = {x.index: x.name for x in body.vertex_groups}
    cw = {ch["bone"]: np.zeros(len(P)) for ch in g["WCH"]}
    own = {n: ch["bone"] for ch in g["WCH"] for n in ch["names"]}
    for v in me.vertices:
        for x in v.groups:
            b = own.get(gname[x.group])
            if b:
                cw[b][v.index] += x.weight
    wing = np.zeros(len(P), bool)
    for ch in g["WCH"]:
        wing |= (cw[ch["bone"]] > 0.5) | np.isin(np.arange(len(P)), np.asarray(ch["rows"], int))
    others = np.flatnonzero(~wing)
    kd = kdtree.KDTree(len(others))
    for i in others:
        kd.insert(P[i], int(i))
    kd.balance()
    heads = {}
    for ch in chains:
        rows = np.flatnonzero(cw[ch["bone"]] > 0.5)
        head = np.array(ch["heads"][0] if "fan" in ch else ch["pts"][0], float)
        d = np.array([kd.find(P[i])[2] for i in rows])
        s = 1.0 + (fac - 1.0) * np.clip((d - gap) / max(ramp, 1e-6), 0.0, 1.0)
        Q = head + (P[rows] - head) * s[:, None]
        for r, i in enumerate(rows):
            me.vertices[int(i)].co = Q[r]
        heads[ch["bone"]] = head
        print("REGION wing_mesh_scale:", ch["bone"], "verts", len(rows), "factor", fac, "at root (s=1)",
              int((s <= 1.0001).sum()), "ramping", int(((s > 1.0001) & (s < fac - 1e-4)).sum()), "full",
              int((s >= fac - 1e-4).sum()))
    me.update()
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for ch in chains:
        h = Vector(heads[ch["bone"]])
        for n in ch["names"]:
            b = eb[n]; roll = b.roll
            b.head, b.tail = h + (b.head - h) * fac, h + (b.tail - h) * fac
            b.roll = roll
    bpy.ops.object.mode_set(mode='OBJECT')
    for ch in chains:
        for n in ch["names"]:
            g["rest"][n] = rig.data.bones[n].matrix_local.copy()
        print("REGION wing_mesh_scale: chain", ch["names"][0][:-3], "bones x", fac, "about", np.round(heads[ch["bone"]], 3).tolist())
