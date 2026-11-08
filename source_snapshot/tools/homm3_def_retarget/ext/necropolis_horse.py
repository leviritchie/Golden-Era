"""Necropolis: mounted knights (Black/Dread Knight) -- a horse rig under the captured rider.

The capture is a single human. On a mounted Meshy mesh the human skeleton is placed on the
rider (hips on the saddle); this module adds the horse:
  after_skin  -- horse bones (HorseNeck, HorseTail, and per leg <name>Up / <name>Low / <name>Hoof, all
                 under Hips; <name>Hoof is an unweighted leaf at the hoof, the leg's end effector for the
                 stride and articulation gates, since glTF keeps no bone tails) and their weights: horse legs below the belly (|x| < legMaxX, z < legTop)
                 go to the nearest leg's upper/lower bone, split at the knee and blended into the
                 body over `blend`; the neck/head (y < neckY) and tail (y > tailY) go to their bones.
                 Everything else keeps the heat weights, so the horse body rides the Hips bone.
  after_pose  -- the rider's hips no longer move the horse: Hips is held at rest (plus a small trot
                 bob in Move), the rider's spine/arms keep the capture's rotations and are
                 re-attached, and the rider's legs stay rigid on the saddle. The horse legs trot
                 procedurally in Move (one gait cycle per Move clip, so the loop closes; half
                 amplitude in MoveStart / MoveEnd); the neck bobs with the gait. In Death the whole
                 unit topples onto its side from `fallStart` (the DEF horse collapses); the
                 silhouette refine then corrects the rest.
  before_keys -- the horse bones are appended to bone_names so they are keyed and exported.

Config "horse": {"legs": [{"name": "HorseLF", "top": [..], "knee": [..], "hoof": [..],
  "phase": 0.0, "kneeSign": 1}, ...], "legTop": 0.62, "legMaxX": 0.2, "blend": 0.08,
  "neck": {"root": [..], "tip": [..]}, "neckY": -0.3, "tail": {"root": [..], "tip": [..]},
  "tailY": 0.64, "swing": 28, "knee": 45, "bob": 0.025, "fallStart": 4, "fallSide": 1,
  "fallAngle": 80}.
"""
import json
import math
import numpy as np
import bpy
from mathutils import Matrix, Vector

HORSE = []   # bone names added here, in parent-before-child order


def _clip(x):
    return max(0.0, min(1.0, x))


def _seg_dist(p, a, b):
    ab = b - a
    t = _clip((p - a).dot(ab) / max(ab.dot(ab), 1e-12))
    return (p - (a + ab * t)).length, t


def after_skin(g):
    hc = g["cfg"].get("horse")
    if not hc:
        return
    rig, body = g["rig"], g["body"]
    V = Vector
    bones = []   # (name, head, tail, parent)
    for L in hc["legs"]:
        bones.append((L["name"] + "Up", V(L["top"]), V(L["knee"]), "Hips"))
        bones.append((L["name"] + "Low", V(L["knee"]), V(L["hoof"]), L["name"] + "Up"))
        d = (V(L["hoof"]) - V(L["knee"])).normalized() * 0.05
        bones.append((L["name"] + "Hoof", V(L["hoof"]), V(L["hoof"]) + d, L["name"] + "Low"))
    if "neck" in hc:
        bones.append(("HorseNeck", V(hc["neck"]["root"]), V(hc["neck"]["tip"]), "Hips"))
    if "tail" in hc:
        bones.append(("HorseTail", V(hc["tail"]["root"]), V(hc["tail"]["tip"]), "Hips"))
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for n, h, t, p in bones:
        b = eb.new(n); b.head, b.tail = h, t; b.roll = 0
    for n, h, t, p in bones:
        eb[n].parent = eb[p]
    bpy.ops.object.mode_set(mode='OBJECT')
    HORSE[:] = [b[0] for b in bones]
    for n in HORSE:
        if not n.endswith("Hoof"):             # the hoof leaf carries no weights
            body.vertex_groups.new(name=n)
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    legTop, maxX, bl = hc.get("legTop", 0.62), hc.get("legMaxX", 0.2), hc.get("blend", 0.08)
    neckY, tailY = hc.get("neckY", -0.3), hc.get("tailY", 0.64)
    legs = [(L["name"], V(L["top"]), V(L["knee"]), V(L["hoof"])) for L in hc["legs"]]
    counts = {}
    for v in body.data.vertices:
        # vertices bound 100% to one bone by a prop region stay as they are
        if any(gr.weight > 0.999 for gr in v.groups) and len(v.groups) == 1 and \
                body.vertex_groups[v.groups[0].group].name.endswith("Hand"):
            continue
        p = v.co
        target = None
        if abs(p.x) < maxX and p.z < legTop + bl and p.y < tailY:
            best = None
            for name, top, knee, hoof in legs:
                d1, _ = _seg_dist(p, top, knee); d2, _ = _seg_dist(p, knee, hoof)
                d = min(d1, d2)
                if best is None or d < best[0]:
                    best = (d, name, top, knee, hoof, d1, d2)
            _, name, top, knee, hoof, d1, d2 = best
            kb = _clip((knee.z - p.z) / 0.1 + 0.5)            # 0 above the knee .. 1 below
            a = _clip((legTop + bl - p.z) / (2 * bl))
            target = [(name + "Up", a * (1 - kb)), (name + "Low", a * kb)]
        elif "neck" in hc and p.y < neckY + bl and abs(p.x) < maxX and p.z > legTop - bl:
            a = _clip((neckY + bl - p.y) / (2 * bl))
            target = [("HorseNeck", a)]
        elif "tail" in hc and p.y > tailY - bl and abs(p.x) < maxX:
            a = _clip((p.y - (tailY - bl)) / (2 * bl))
            target = [("HorseTail", a)]
        if not target:
            continue
        tot = sum(w for _, w in target)
        if tot <= 1e-4:
            continue
        for gr in v.groups:
            gr.weight *= (1 - tot)
        for n, w in target:
            if w > 1e-4:
                body.vertex_groups[gi[n]].add([v.index], w, 'REPLACE')
                counts[n] = counts.get(n, 0) + 1
    # glTF carries 4 influences per vertex: keep the strongest 4 and renormalise
    for v in body.data.vertices:
        gs = sorted(((gr.group, gr.weight) for gr in v.groups), key=lambda x: -x[1])
        if len(gs) > 4 or abs(sum(w for _, w in gs) - 1.0) > 1e-4:
            keep = gs[:4]; tot = max(sum(w for _, w in keep), 1e-9)
            for gidx_, _ in gs[4:]:
                body.vertex_groups[gidx_].remove([v.index])
            for gidx_, w in keep:
                body.vertex_groups[gidx_].add([v.index], w / tot, 'REPLACE')
    print("HORSE bones", HORSE, "weighted", counts)


def after_pose(g):
    hc = g["cfg"].get("horse")
    if not hc or not HORSE:
        return
    posed_world, rest, parent_of = g["posed_world"], g["rest"], g["parent_of"]
    bone_names = g["bone_names"]
    for n in HORSE:
        parent_of[n] = rig_parent(g["rig"], n)
    segs = json.load(open(g["MASTER"]))["segments"]
    amp_t, ph_t = {}, {}
    death = None
    for s in segs:
        a = {"Move": 1.0, "MoveStart": 0.5, "MoveEnd": 0.5}.get(s["contractSuffix"], 0.0)
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            amp_t[t] = a; ph_t[t] = i / max(s["frameCount"], 1)
        if s["contractSuffix"] == "Death" and (death is None or s["frameCount"] > death["frameCount"]):
            death = s
    sw, kn, bob = math.radians(hc.get("swing", 28)), math.radians(hc.get("knee", 45)), hc.get("bob", 0.025)
    rider_legs = [n for n in bone_names if any(k in n for k in ("UpLeg", "Leg", "Foot", "Toe"))]
    Rz = Matrix.Identity(3)   # necropolis_yaw turns the finished poses afterwards (its after_pose runs later)
    X = Rz @ Vector((1, 0, 0))
    for t, A in enumerate(posed_world):
        am, ph = amp_t.get(t, 0.0), ph_t.get(t, 0.0)
        dz = bob * am * abs(math.sin(2 * math.pi * 2 * ph))
        A["Hips"] = Matrix.Translation(Vector((0, 0, dz))) @ rest["Hips"]
        for n in bone_names:
            if n == "Hips":
                continue
            par = parent_of[n]
            if n in rider_legs:
                A[n] = A[par] @ rest[par].inverted() @ rest[n]
            else:
                head = A[par] @ (rest[par].inverted() @ rest[n].translation)
                A[n] = Matrix.Translation(head) @ A[n].to_3x3().to_4x4()
        for L in hc["legs"]:
            phi = 2 * math.pi * (ph + L.get("phase", 0.0))
            up = -sw * am * math.sin(phi)                       # negative = hoof forward
            flex = kn * am * max(0.0, math.cos(phi)) * L.get("kneeSign", 1)
            u, lo = L["name"] + "Up", L["name"] + "Low"
            A[u] = A["Hips"] @ rest["Hips"].inverted() @ rest[u] @ _local_rot(rest[u], X, up)
            A[lo] = A[u] @ rest[u].inverted() @ rest[lo] @ _local_rot(rest[lo], X, flex)
            hf = L["name"] + "Hoof"
            A[hf] = A[lo] @ rest[lo].inverted() @ rest[hf]
        for n, k in (("HorseNeck", 0.25), ("HorseTail", -0.4)):
            if n in HORSE:
                ang = sw * k * am * math.sin(2 * math.pi * 2 * ph)
                A[n] = A["Hips"] @ rest["Hips"].inverted() @ rest[n] @ _local_rot(rest[n], X, ang)
    # death: topple onto the side, about the ground line under the hooves on that side
    if death and "fallStart" in hc:
        d0, d1 = death["globalStart"], death["globalEnd"]
        a0 = d0 + hc["fallStart"]; side = hc.get("fallSide", 1); maxang = math.radians(hc.get("fallAngle", 80))
        xs = max(abs(L["hoof"][0]) for L in hc["legs"]) + 0.08
        pivot = Rz @ Vector((side * xs, 0, 0))
        for t in range(a0, d1):
            f = _clip((t - a0 + 1) / max(d1 - a0, 1)) ** 1.5
            M = Matrix.Translation(pivot) @ Matrix.Rotation(-side * maxang * f, 4, Rz @ Vector((0, 1, 0))) @ Matrix.Translation(-pivot)
            A = posed_world[t]
            for n in A:
                if n != "Root" and n not in g["STATIC"]:
                    A[n] = M @ A[n]
    print("HORSE posed", len(posed_world), "frames")


def _local_rot(Rb, axis_world, ang):
    """Rotation by ang about a world axis, expressed in the bone's rest frame."""
    ax = Rb.to_3x3().inverted() @ axis_world
    return Matrix.Rotation(ang, 4, ax)


def rig_parent(rig, n):
    return rig.data.bones[n].parent.name


def before_keys(g):
    if HORSE:
        for n in HORSE:
            if n not in g["bone_names"]:
                g["bone_names"].append(n)
