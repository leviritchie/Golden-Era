"""Foot-sole ownership (hook module for build_unit.py; list "foot_sole" in a unit's "extensions").

Why: bone heat splits a heel that reaches behind (or a block foot that reaches below) the ankle between the shin and
the foot, because both bones share the ankle as an endpoint. A shin-owned sole then follows the shin, not the foot:
when the stride plant re-solves the leg by IK and keeps the foot's source rotation, that heel swings under the Idle
floor while the foot's own sole stands on it, and ground_glb refuses the Move (P2, "grounding would float the stride
plant ... the lowest other point there is <side>Leg-owned geometry"; 2026-09-30 h3_magma_elemental: three heel
vertices at 0.55 LeftLeg / 0.45 LeftFoot dipped 0.004 H, and any positive loop offset lifts a swinging sole across
the gate's band edge).

Rule: nothing below the ankle hinge belongs to the shin. For each side, a vertex below its Foot joint's height hands a
share of its <side>Leg and <side>UpLeg weight to <side>Foot, ramping from none at the ankle to all of it at
`fullBelow` x the ankle height (default 0.5), so the shin/foot boundary stays a smooth blend and never a cut. Only
vertices that already carry that side's leg weight are touched (rigid regions and the other leg keep theirs).

Config (optional): "footSole": {"fullBelow": f}  with 0 <= f < 1.
Proof tier: build-time weight edit; judged by the unit's own stride / ground gates, nothing here is a gate.
"""


def after_skin(g):
    cfg = g["cfg"].get("footSole", {})
    if set(cfg) - {"fullBelow"}:
        raise SystemExit(f"footSole: unknown keys {sorted(set(cfg) - {'fullBelow'})}")
    full = float(cfg.get("fullBelow", 0.5))
    if not 0.0 <= full < 1.0:
        raise SystemExit(f"footSole.fullBelow must be in [0, 1), got {full}")
    body, J = g["body"], g["J"]
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    for side in ("Left", "Right"):
        need = [side + "Leg", side + "Foot"]
        if not all(n in J and n in gi for n in need):
            raise SystemExit(f"footSole: the rig has no {side}Leg/{side}Foot bone groups to move the sole between")
        z_ank = float(J[side + "Foot"][2])
        z_full = z_ank * full
        shin = {gi[n] for n in (side + "Leg", side + "UpLeg") if n in gi}
        foot = body.vertex_groups[side + "Foot"]
        moved, total = 0, 0.0
        for v in body.data.vertices:
            z = v.co.z
            if z >= z_ank:
                continue
            a = 1.0 if z <= z_full else (z_ank - z) / max(z_ank - z_full, 1e-9)
            take = 0.0
            for e in v.groups:
                if e.group in shin and e.weight > 0:
                    take += e.weight * a
                    e.weight *= (1.0 - a)
            if take > 1e-6:
                old = next((e.weight for e in v.groups if e.group == foot.index), 0.0)
                foot.add([v.index], old + take, 'REPLACE')
                moved += 1
                total += take
        print("FOOTSOLE", side, "ankle z", round(z_ank, 4), "full below", round(z_full, 4),
              "vertices", moved, "weight moved", round(total, 3))
    # A vertex carrying both legs' weight (a hem or tail hanging between them) gains both Foot groups, which can take
    # it past the build's 4-influence limit; the GLB export then drops an influence and verify_glb's mesh round trip
    # fails (2026-09-30 h3_kobold_upg_alt: 63 tail vertices at 6 influences, MESHERR 0.034). Keep the 4 largest,
    # renormalised, as build_unit's own limit_total + normalize_all would.
    capped = 0
    for v in body.data.vertices:
        live = sorted(((e.group, e.weight) for e in v.groups if e.weight > 1e-6), key=lambda t: t[1], reverse=True)
        if len(live) <= 4:
            continue
        s = sum(w for _, w in live[:4])
        for gidx, _ in live[4:]:
            body.vertex_groups[gidx].remove([v.index])
        for gidx, w in live[:4]:
            body.vertex_groups[gidx].add([v.index], w / s, 'REPLACE')
        capped += 1
    print("FOOTSOLE influence cap: vertices over 4 influences", capped)
