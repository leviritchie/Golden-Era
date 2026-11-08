"""Necropolis: hold a floor-length robe hem on the hips instead of the feet.

surface_weights.py's `skirtLegShare` only moves UpLeg/Leg weight to the hips; the robe hem that
lies on the floor around the feet keeps full Foot/ToeBase weight, so every step drags the hem
into long cyan sheets (h3_lich_master). This hook takes Foot/ToeBase/Toe_End weight from vertices
farther than `keepDist` from those bones (the shoe itself stays on the foot) and gives all but
`share` of it to Hips, ramping in over `ramp`.

Config: "hemHold": {"keepDist": 0.06, "ramp": 0.03, "share": 0.2}
"""
import numpy as np


def _seg_dist(P, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float); ab = b - a
    t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def after_skin(g):
    cfg, J, body = g["cfg"], g["J"], g["body"]
    hc = cfg.get("hemHold", {})
    keep, ramp, share = hc.get("keepDist", 0.06), hc.get("ramp", 0.03), hc.get("share", 0.2)
    P = np.array([v.co[:] for v in body.data.vertices])
    vg = {v.name: v for v in body.vertex_groups}
    hips = vg["Hips"]
    moved_n = 0
    for side in ("Left", "Right"):
        chain = [c for c in ("Foot", "ToeBase", "Toe_End") if side + c in J]
        segs = [(J[side + a], J[side + b]) for a, b in zip(chain, chain[1:])]
        if not segs:
            continue
        d = np.min([_seg_dist(P, a, b) for a, b in segs], 0)
        alpha = np.clip((d - keep) / ramp, 0, 1) * (1 - share)
        idx = {vg[side + c].index: vg[side + c] for c in chain if side + c in vg}
        for v in body.data.vertices:
            a = alpha[v.index]
            if a <= 0:
                continue
            take = 0.0
            for gr in v.groups:
                if gr.group in idx and gr.weight > 0:
                    m = gr.weight * a; take += m
                    idx[gr.group].add([v.index], gr.weight - m, 'REPLACE')
            if take > 0:
                hw = next((gr.weight for gr in v.groups if gr.group == hips.index), 0.0)
                hips.add([v.index], hw + take, 'REPLACE'); moved_n += 1
    print("HEMHOLD moved foot weight to hips on", moved_n, "vertices")
