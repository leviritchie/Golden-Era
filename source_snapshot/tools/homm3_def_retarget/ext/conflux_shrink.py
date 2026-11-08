"""Conflux per-clip body shrink (hook module for build_unit.py; list it in "extensions").

Elementals the DEF turns into something skinning cannot make (the energy elemental collapses into
a ball of light and then a thin spark to travel) are approximated by shrinking the whole body
uniformly about a pivot for those frames; the light effect itself is Unity work.

"conflux": {"clipShrink": {"<contractSuffix>": [s0, s1, ...], ...}, "shrinkPivot": "hips"|"ground"}
gives one uniform scale per DEF frame of that clip (the longest segment with that suffix; missing
entries mean 1). The pivot is the hips of that frame ("hips", default) or the point under them on
the ground ("ground"). Only body bones are scaled (not Root, static chains or rubble).
"""
from mathutils import Matrix, Vector


def before_keys(g):
    cfg = g["cfg"].get("conflux", {})
    spec = cfg.get("clipShrink")
    if not spec:
        return
    import json
    segs = json.load(open(g["MASTER"]))["segments"]
    pw = g["posed_world"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    for suffix, scales in spec.items():
        cand = [s for s in segs if s["contractSuffix"] == suffix]
        if not cand:
            continue
        s = max(cand, key=lambda x: x["frameCount"])
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            k = scales[i] if i < len(scales) else 1.0
            if abs(k - 1.0) < 1e-6:
                continue
            k = max(k, 1e-3)
            piv = pw[t]["Hips"].translation.copy()
            if cfg.get("shrinkPivot") == "ground":
                piv.z = 0.0
            M = Matrix.Translation(piv) @ Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation(-piv)
            for n in list(pw[t].keys()):
                if n not in skip:
                    pw[t][n] = M @ pw[t][n]
        print("CONFLUX clipShrink", suffix, scales)
