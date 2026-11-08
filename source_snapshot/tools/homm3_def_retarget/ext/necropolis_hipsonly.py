"""Necropolis: hand the weights of listed bones to Hips (bones that must own no flesh).

A centaur (h3_dreadtaur) has no human legs, but the build needs the Mixamo leg joints; parked
inside the horse's chest, heat still gives them chest and flank vertices, which then move with
the capture's leg motion (stretch at the withers and at the rear flank). after_skin: every
listed bone's weight is added to Hips and removed from the bone. List this hook after any hook
that assigns weights (e.g. necropolis_horse).

Config: "hipsOnly": ["LeftUpLeg", "LeftLeg", ...]
"""


def after_skin(g):
    body = g["body"]
    names = g["cfg"].get("hipsOnly", [])
    vg = {v.name: v for v in body.vertex_groups}
    hips = vg["Hips"]
    idx = {vg[n].index: vg[n] for n in names if n in vg}
    moved = 0
    for v in body.data.vertices:
        take = 0.0
        for gr in v.groups:
            if gr.group in idx and gr.weight > 0:
                take += gr.weight
        if take <= 0:
            continue
        for gi, grp in idx.items():
            grp.remove([v.index])
        hw = next((gr.weight for gr in v.groups if gr.group == hips.index), 0.0)
        hips.add([v.index], hw + take, 'REPLACE'); moved += 1
    print("HIPSONLY moved", moved, "vertices from", sorted(idx and [g.name for g in idx.values()]))
