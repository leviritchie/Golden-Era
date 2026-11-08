"""Bulwark/Factory hook: keep fused limbs from dragging the body they rest against.

Meshy fuses arms hanging beside a coat (kobolds, yetis, shamans) or legs into a belly; heat
weighting then spreads forearm/hand weight onto the coat, which tears into a sheet when the arm
lifts. Pair this with the config's `armCut` (surface_weights.py cuts the forearm/hand free along
its boundary); this hook then strips the listed limb bones' weights from every vertex whose
nearest bone segment is not in that limb, so the coat no longer follows the arm.

Config:
  "limbStrip": [{"chain": ["LeftForeArm", "LeftHand"], "keep": ["LeftArm", "LeftForeArm", "LeftHand"],
                 "fallback": "Spine1"}, ...]
    chain    bones whose weight is removed from vertices outside the limb
    keep     a vertex whose nearest bone segment is one of these keeps its weights
    fallback bone that receives the weight if nothing is left
    keepDist optional: a vertex nearest a `keep` bone is kept only within this distance of it
    belowZ   optional: only vertices below this height are cleaned (keeps the shoulder blend)
"""
import numpy as np


def after_skin(g):
    cfg, body, BONES, J = g["cfg"], g["body"], g["BONES"], g["J"]
    specs = cfg.get("limbStrip", [])
    if not specs:
        return
    P = np.array([v.co[:] for v in body.data.vertices])
    names = [b[0] for b in BONES]
    segs = [(np.array(J[h]), np.array(J[t])) for _, h, t, _ in BONES]

    def sd(a, b):
        ab = b - a; t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
    D = np.stack([sd(a, b) for a, b in segs], 1)
    nearest = [names[i] for i in D.argmin(1)]
    dmin = D.min(1)
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    gname = {vg.index: vg.name for vg in body.vertex_groups}
    for sp in specs:
        chain = set(sp["chain"]); keep = set(sp["keep"]); fb = sp.get("fallback", "Spine1")
        n = 0
        taken = g.get("taken", set())
        for v in body.data.vertices:
            if "belowZ" in sp and v.co.z >= sp["belowZ"]:
                continue
            if (nearest[v.index] in keep and dmin[v.index] < sp.get("keepDist", 1e9)) or v.index in taken:   # rigid props stay whole
                continue
            ws = {gname[x.group]: x.weight for x in v.groups}
            if ws and set(ws) <= (chain | keep):              # the cut limb itself (armCut region)
                continue
            if not any(k in chain and w > 1e-4 for k, w in ws.items()):
                continue
            rest = {k: w for k, w in ws.items() if k not in chain and w > 1e-4}
            for k in chain:
                if k in ws:
                    body.vertex_groups[k].remove([v.index])
            tot = sum(rest.values())
            if tot <= 1e-6:
                body.vertex_groups[fb].add([v.index], 1.0, 'REPLACE')
            else:
                for k, w in rest.items():
                    body.vertex_groups[k].add([v.index], w / tot, 'REPLACE')
            n += 1
        print("LIMBSTRIP", sorted(chain), "vertices cleaned", n)
