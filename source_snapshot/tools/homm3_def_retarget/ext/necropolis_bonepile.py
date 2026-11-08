"""Necropolis: skeleton deaths collapse into a heap of bones on the ground.

The shared `shatter` death throws its rubble chunks outward under gravity, which over a
3-4 frame DEF death leaves the bones hanging in the air where the body stood. The DEF
skeletons fold straight down into a pile. This hook (before_keys) re-keys every rubble
chunk from the break frame on: each chunk drops from its break pose to a heap spot below
the hips (its horizontal offset shrunk by `spread`, stacked up to `heapHeight` near the
centre) and tumbles by up to `tumble` degrees, with an ease-in fall over the death frames.

Config (unit json): "bonePile": {"spread": 0.8, "heapHeight": 0.22, "tumble": 80, "seed": 3,
"power": 1.6}. Needs "shatter" (which builds the rubble mesh and chunk bones).

Optional "standProp": {"segment": [[guard xyz], [tip xyz]], "radius": 0.07, "at": [dx, dy], "lean": 12}
(rest coordinates, like the unit's props): the chunks that are mostly that blade fall as one rigid piece
and end standing upright in the heap, tip down at hips + `at`, leaning `lean` degrees (DEF swordsmen:
the sword stays standing in the bone pile).
"""
import math
import numpy as np
from mathutils import Matrix, Vector


def before_keys(g):
    cfg, death = g["cfg"], g["death"]
    bp = cfg.get("bonePile")
    if not bp or not death or not g.get("RUBBLE_BONES"):
        return
    posed_world, rest, CH = g["posed_world"], g["rest"], g["RUBBLE_BONES"][1:]
    d0, d1 = death["globalStart"], death["globalEnd"]
    ts = d0 + cfg["shatter"]["start"]
    n = max(d1 - ts, 1)
    rs = np.random.default_rng(bp.get("seed", 3))
    spread, hh = bp.get("spread", 0.8), bp.get("heapHeight", 0.22)
    tumble, power = math.radians(bp.get("tumble", 80)), bp.get("power", 1.6)
    # hips at the break frame: the body is hidden (scaled to ~0 about it) from ts on, so take
    # the last frame before the break
    hips = posed_world[max(ts - 1, 0)]["Hips"].translation.copy()
    A0 = posed_world[ts]
    body = g["body"]
    BP = np.array([v.co[:] for v in body.data.vertices])
    plan = []
    for k, nme in enumerate(CH):
        M0 = A0[nme] @ rest[nme].inverted()             # break-frame rigid transform of chunk k
        c_rest = rest[nme].translation
        p0 = M0 @ c_rest
        off = Vector((p0.x - hips.x, p0.y - hips.y, 0.0)) * spread
        rad = off.length
        z = 0.04 + hh * max(0.0, 1.0 - rad / 0.45) * rs.random()
        q = Vector((hips.x, hips.y, 0.0)) + off + Vector((rs.normal() * 0.03, rs.normal() * 0.03, z))
        ax = Vector(tuple(rs.normal(size=3))).normalized()
        ang = tumble * (0.3 + 0.7 * rs.random())
        plan.append((M0, c_rest, p0, q, ax, ang))
    stand = _stand_plan(g, bp.get("standProp"), CH, A0, rest, hips)
    B0 = {nme: A0[nme].copy() for nme in CH}         # break-frame chunk poses (A0 is re-keyed below)
    for t in range(ts, d1):
        f = min(1.0, ((t - ts + 1) / n) ** power)
        A = posed_world[t]
        if stand:
            Mg, tip0, axr, angr, qt, sel = stand
            Mt = Matrix.Translation(tip0.lerp(qt, f)) @ Matrix.Rotation(angr * f, 4, axr) @ Matrix.Translation(-tip0)
        for k, nme in enumerate(CH):
            if stand and k in stand[5]:
                A[nme] = Mt @ B0[nme]
                continue
            M0, c, p0, q, ax, ang = plan[k]
            R = Matrix.Rotation(ang * f, 4, ax)
            pos = p0.lerp(q, f)
            # chunk centre moves p0 -> q while turning about itself
            A[nme] = Matrix.Translation(pos) @ R @ Matrix.Translation(-p0) @ M0 @ rest[nme]
    print("BONEPILE chunks", len(CH), "frames", n, "standing prop chunks", sorted(stand[5]) if stand else None)


def _stand_plan(g, sp, CH, A0, rest, hips):
    if not sp:
        return None
    a, b = np.array(sp["segment"][0], float), np.array(sp["segment"][1], float)
    BP, lab = g["BP"], g["lab"]
    ab = b - a
    tpar = np.clip(((BP - a) @ ab) / (ab @ ab), 0, 1)
    near = np.linalg.norm(BP - (a + tpar[:, None] * ab), axis=1) < sp.get("radius", 0.07)
    sel = {k for k in range(len(CH)) if (lab == k).any() and near[lab == k].mean() >= 0.5}
    if not sel:
        print("BONEPILE standProp: no blade chunks"); return None
    kb = max(sel, key=lambda k: int(near[lab == k].sum()))
    Mg = A0[CH[kb]] @ rest[CH[kb]].inverted()        # break-frame rigid transform of the blade
    tip0, guard0 = Mg @ Vector(b.tolist()), Mg @ Vector(a.tolist())
    d0 = (tip0 - guard0).normalized()                # guard -> tip at the break
    at = sp.get("at", [0.0, 0.0]); lean = math.radians(sp.get("lean", 12))
    want = Vector((math.sin(lean) * (1 if at[0] >= 0 else -1), 0.0, -math.cos(lean))).normalized()
    axr = d0.cross(want)
    angr = math.asin(min(1.0, axr.length)) if d0.dot(want) >= 0 else math.pi - math.asin(min(1.0, axr.length))
    axr = axr.normalized() if axr.length > 1e-6 else Vector((1, 0, 0))
    qt = Vector((hips.x + at[0], hips.y + at[1], sp.get("tipZ", 0.02)))
    return Mg, tip0, axr, angr, qt, sel
