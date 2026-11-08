"""Conflux rubble settle (hook module for build_unit.py; list it in a unit's "extensions").

The shared shatter stage lets chunks fall under real gravity, but an elemental's DEF death goes
from breaking apart to a heap on the ground in 3-4 frames (0.3 s), far quicker than a 1.7-unit
body falls. With "conflux": {"rubbleSettle": {"gather": g, "power": p}} every rubble chunk, from
the break frame to the last death frame, is eased (by ((t - break) / span) ** p) down to lie on the
ground at its own size, and pulled a share g toward the heap centre, so the last frame is a heap.
"""
from mathutils import Matrix, Vector


def before_keys(g):
    st = g["cfg"].get("conflux", {}).get("rubbleSettle")
    if not st or not g.get("RUBBLE_BONES") or not g.get("death"):
        return
    pw, CH = g["posed_world"], [n for n in g["RUBBLE_BONES"] if n.startswith("Chunk_")]
    d0, d1 = g["death"]["globalStart"], g["death"]["globalEnd"]
    ts = d0 + g["cfg"]["shatter"]["start"]
    span = max(d1 - 1 - ts, 1)
    radius = {c: ch["r"] for c, ch in zip(CH, g["chunks"])}
    centre = sum((pw[ts][n].translation for n in CH), Vector()) / len(CH)
    centre.z = 0.0
    for t in range(ts + 1, d1):
        a = min(1.0, ((t - ts) / span) ** st.get("power", 1.0))
        for n in CH:
            p = pw[t][n].translation
            q = p.lerp(Vector((centre.x, centre.y, 0)), st.get("gather", 0.3))
            q.z = radius[n] * 0.6
            pw[t][n] = Matrix.Translation(p.lerp(q, a) - p) @ pw[t][n]
    print("CONFLUX rubbleSettle", len(CH), "chunks over", span, "frames")
