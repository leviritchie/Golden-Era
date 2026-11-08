"""Dungeon: separate hands/forearms from the legs and torso they rest on.

Meshy fuses hands to thighs, knees and bellies (fury's hands in her lap, chthonian's claws on
its knees). Bone heat then blends arm and leg weights across the contact, and when the arm lifts
the contact stretches into a sheet. after_skin (config "limbSep": {"bodyBones": [...]}):
  * every non-rigid vertex whose nearest bone (rest segment distance) is a leg or body bone
    loses its ForeArm/Hand weights; one whose nearest bone is a ForeArm/Hand loses its leg and
    body-bone weights (both renormalised, never emptied);
  * edges whose two ends then share no bone are split, so the contact opens instead of
    stretching.
Rigid regions (props, wings: one bone at weight 1) are left alone.
"""
import bmesh
import numpy as np


def _segdist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def after_skin(g):
    body, cfg, BONES, J = g["body"], g["cfg"], g["BONES"], g["J"]
    opt = cfg.get("limbSep", {})
    arm = [b for b, *_ in BONES if b.endswith(("ForeArm", "Hand"))]
    body_default = [b for b, *_ in BONES if b.endswith(("UpLeg", "Leg"))]
    other = opt.get("bodyBones", body_default)
    segs = {b: (np.array(J[h]), np.array(J[t])) for b, h, t, _ in BONES if b in arm or b in other}
    names = list(segs)
    me = body.data
    n = len(me.vertices)
    P = np.array([v.co[:] for v in me.vertices])
    D = np.stack([_segdist(P, *segs[b]) for b in names], 1)
    near = [names[i] for i in D.argmin(1)]
    vg = body.vertex_groups
    gname = {x.index: x.name for x in vg}
    armset, otherset = set(arm), set(other)
    changed = 0
    for v in me.vertices:
        ws = {gname[x.group]: x.weight for x in v.groups}
        if not ws or max(ws.values()) >= 0.999:
            continue
        drop = armset if near[v.index] in otherset else otherset if near[v.index] in armset else set()
        keep = {k: w for k, w in ws.items() if k not in drop}
        if not drop or len(keep) == len(ws) or sum(keep.values()) < 1e-4:
            continue
        s = sum(keep.values())
        for k in ws:
            if k in keep:
                vg[k].add([v.index], keep[k] / s, 'REPLACE')
            else:
                vg[k].remove([v.index])
        changed += 1
    bm = bmesh.new(); bm.from_mesh(me)
    dl = bm.verts.layers.deform.verify()
    sup = lambda v: {k for k, w in v[dl].items() if w > 1e-3}
    cut = [e for e in bm.edges if not (sup(e.verts[0]) & sup(e.verts[1]))
           and (sup(e.verts[0]) | sup(e.verts[1])) & {vg[b].index for b in arm}]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(me); bm.free()
    print("DUNGEON limbsep: reweighted", changed, "split edges", len(cut))
