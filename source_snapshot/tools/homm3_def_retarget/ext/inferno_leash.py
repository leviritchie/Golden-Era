"""Limb leash (hook for build_unit.py).

Bone heat is computed on the welded mesh while the held prop is still fused to the body: a
devil's scythe shaft or a pit fiend's whip runs from the hand down the robe / leg, so heat from the
hand and forearm bones flows along the prop into the cloth it touches (and heat from a leg can flow
up the prop to the shoulder). The prop is then cut free and bound rigidly, but the cloth keeps a
share of the far bones and is dragged into a long sheet whenever the limb lifts. after_skin, on
every non-rigid vertex:
  1. drops a listed bone's weight where the vertex is farther than maxDist (or boneMaxDist[bone])
     from that bone's rest segment;
  2. nearestOnly: also drops it where the vertex's nearest bone is not in that bone's arm chain;
  3. maxDistAll: drops ANY bone's weight farther than this from its segment (cross-body leaks);
  4. armOnly: a vertex whose nearest bone is a listed ForeArm/Hand keeps only that arm chain
     (wrong where a thigh lies under the hand and its own leg bone runs behind it: the devil);
  5. partition (list of body bones, e.g. thighs + Hips): a vertex carrying both a listed
     ForeArm/Hand and one of these keeps only the side with the larger share, so the contact
     between a hand and the thigh it rests on becomes a clean cut for handSplit;
  6. handSplit: a face holding both an arm-dominant and a partition-dominant vertex gets its own
     copies of its arm-dominant corners, weighted like that face's nearest partition-dominant vertex, so a
     hand Meshy fused to a thigh lifts away instead of stretching the face into a sheet.
A vertex left with no weight takes its nearest bone. Only removes weights and renormalises, so each
vertex stays within 4 influences.

Unit config: "limbLeash": {"bones": ["LeftArm", "LeftForeArm", "LeftHand"], "maxDist": 0.15,
  "boneMaxDist": {"LeftHand": 0.07}, "nearestOnly": true, "maxDistAll": 0.35, "armOnly": false,
  "partition": ["RightUpLeg", "Hips"], "handSplit": true}
"""
import bmesh
import numpy as np


def _seg_dist(P, a, b):
    ab = b - a
    t = np.clip((P - a) @ ab / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def _chain(n):
    side = "Left" if n.startswith("Left") else "Right" if n.startswith("Right") else ""
    if side and n[len(side):] in ("Arm", "ForeArm", "Hand"):
        return [side + b for b in ("Shoulder", "Arm", "ForeArm", "Hand", "Hand_End")]
    return [n]


def after_skin(g):
    lc = g["cfg"].get("limbLeash")
    if not lc:
        return
    body, rig, taken = g["body"], g["rig"], g["taken"]
    md = lc.get("maxDist", 0.15)
    bmd = lc.get("boneMaxDist", {})
    mda = lc.get("maxDistAll")
    seg = {b.name: (np.array(b.head_local[:]), np.array(b.tail_local[:])) for b in rig.data.bones if b.use_deform}
    P = np.array([v.co[:] for v in body.data.vertices])
    vg = body.vertex_groups
    gname = {x.index: x.name for x in vg}
    allb = [n for n in seg if n in vg and n != "Root"]
    D = {n: _seg_dist(P, *seg[n]) for n in allb}
    Dm = np.stack([D[n] for n in allb], 1)
    near = np.array(allb)[Dm.argmin(1)]
    leashed = [n for n in lc["bones"] if n in D]
    drop = {n: D[n] > bmd.get(n, md) for n in leashed}
    if lc.get("nearestOnly"):
        for n in leashed:
            drop[n] |= ~np.isin(near, _chain(n))
    if mda:
        for n in allb:
            drop[n] = drop.get(n, np.zeros(len(P), bool)) | (D[n] > mda)
    handsplit = lc.get("handSplit")
    ends = [n for n in leashed if n.endswith(("ForeArm", "Hand"))]
    released = pure = 0
    for v in body.data.vertices:
        i = v.index
        if i in taken:
            continue
        ws = {gname[x.group]: x.weight for x in v.groups if x.weight > 0}
        keep = {k: w for k, w in ws.items() if not (k in drop and drop[k][i])}
        if lc.get("armOnly") and near[i] in ends:
            ch = set(_chain(near[i]))
            arm = {k: w for k, w in keep.items() if k in ch}
            if arm and len(arm) < len(keep):
                keep = arm; pure += 1
        part = set(lc.get("partition", []))
        if part and any(k in part for k in keep) and any(k in ends for k in keep):
            # hand resting on a thigh: one side of a clean cut, by the dominant share
            armb = {k for k in keep if k.endswith(("Shoulder", "Arm", "ForeArm", "Hand"))}
            if sum(w for k, w in keep.items() if k in armb) >= 0.5 * sum(keep.values()):
                keep = {k: w for k, w in keep.items() if k not in part}
            else:
                keep = {k: w for k, w in keep.items() if k not in armb}
            pure += 1
        if len(keep) == len(ws):
            continue
        if not keep:
            ok = [j for j, n in enumerate(allb) if not (n in drop and drop[n][i])]
            keep = {allb[min(ok or range(len(allb)), key=lambda j: Dm[i, j])]: 1.0}
        s = sum(keep.values())
        for k in ws:
            if k not in keep:
                vg[k].remove([i])
        for k, w in keep.items():
            vg[k].add([i], w / s, 'REPLACE')
        released += 1
    nsplit = 0
    if handsplit:
        # straddle cut: a face holding both an arm-dominant vertex and a partition-dominant vertex
        # (a hand fused to the thigh / hip it rests on) is detached from the arm: each of its
        # arm-dominant corners gets its own vertex weighted like the nearest partition-dominant
        # vertex of the same face, so the face stays on the body and the hand lifts away.
        part = set(lc.get("partition", []))
        sides = {("Left" if n.startswith("Left") else "Right") for n in leashed}
        armb = {s_ + b for s_ in sides for b in ("ForeArm", "Hand")}   # the parts that rest on things
        me = body.data
        bm = bmesh.new(); bm.from_mesh(me)
        dl = bm.verts.layers.deform.verify()
        aid = {vg[n].index for n in armb if n in vg}; pid = {vg[n].index for n in part if n in vg}
        share = lambda u, ids: sum(w for k, w in u[dl].items() if k in ids)
        isArm = lambda u: share(u, aid) >= 0.5
        isBody = lambda u: share(u, pid) >= 0.5 and share(u, pid) > share(u, aid)
        strad = [f for f in bm.faces if any(isArm(u) for u in f.verts) and any(isBody(u) for u in f.verts)]
        for f in strad:
            fb = [u for u in f.verts if isBody(u)]
            fw = [dict(u[dl].items()) for u in fb]
            for u in [u for u in f.verts if isArm(u)]:
                j = int(np.argmin([(u.co - b.co).length for b in fb]))
                nv = bmesh.utils.face_vert_separate(f, u) if len(u.link_faces) > 1 else u
                d = nv[dl]; d.clear()
                for k, w in fw[j].items():
                    d[k] = w
                nsplit += 1
        bm.to_mesh(me); bm.free()
        print("HOOK LEASH straddle faces", len(strad), "corners detached", nsplit)
    print("HOOK LEASH", leashed, "maxDist", md, bmd, "maxDistAll", mda, "vertices released", released,
          "arm-only/partitioned", pure, "split edges", nsplit)
