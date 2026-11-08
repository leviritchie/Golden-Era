"""Cove extension: sea serpents (haspid, sea serpent, abyss serpent) slump to the ground in Death.

The serpents are rigged with the naga `tail` (the coil) and a spine chain for the raised neck; the
human capture only tilts the neck a little when the DEF serpent collapses onto its coil. From a
local death frame the whole raised body (every driven bone; the tail's planted part follows by
itself because it rides the hips only near the waist) rotates forward and down about a horizontal
axis through a pivot on the ground under the hips, easing in, so the head ends on the ground in
front like the DEF.

Config: "coveSlump": {"start": 2, "deg": 75, "pivotZ": 0.15, "forward": [0, -1, 0]}

The DEF serpents also strike by throwing the raised body forward, which the human attack capture
barely does: "coveLunge": {"deg": 40, "peak": 0.55, "width": 0.3, "pivotZ": 0.5} adds the same
forward rotation in AttackFront with a smooth bell profile (0 at the clip ends, `deg` at the
`peak` fraction of the clip, half-width `width`), so the clip still starts and ends on the capture.
Runs at after_pose (before the tail is solved, so the tail follows the lowered hips).
"""
import json
import math
from mathutils import Matrix, Vector


def _rotate(g, t, deg, pivot_z, fwd):
    axis = fwd.cross(Vector((0, 0, -1))).normalized()   # rotating +Z toward fwd
    A = g["posed_world"][t]
    hip = A["Hips"].translation
    piv = Vector((hip.x, hip.y, pivot_z))
    M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-piv)
    for n in list(A.keys()):
        if n != "Root" and n not in g["STATIC"]:
            A[n] = M @ A[n]


def after_pose(g):
    cfg = g["cfg"]
    segs = json.load(open(g["MASTER"]))["segments"]
    L = cfg.get("coveLunge")
    if L:
        fwd = Vector(L.get("forward", (0, -1, 0))).normalized()
        for sg in segs:
            if sg["contractSuffix"] != "AttackFront":
                continue
            n = sg["frameCount"]
            for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                x = (i / max(n - 1, 1) - L.get("peak", 0.55)) / L.get("width", 0.3)
                w = math.cos(min(abs(x), 1.0) * math.pi / 2) ** 2
                if w > 1e-4:
                    _rotate(g, t, L.get("deg", 40) * w, L.get("pivotZ", 0.5), fwd)
        print("HOOK COVE lunge deg", L.get("deg", 40))
    S = cfg.get("coveSlump")
    if not S:
        return
    death = max((x for x in segs if x["contractSuffix"] == "Death"), key=lambda x: x["frameCount"], default=None)
    if death is None:
        return
    d0, d1 = death["globalStart"], death["globalEnd"]
    a = d0 + S.get("start", 2)
    fwd = Vector(S.get("forward", (0, -1, 0))).normalized()
    axis = fwd.cross(Vector((0, 0, -1))).normalized()   # rotating +Z toward fwd
    STATIC = g["STATIC"]
    for t in range(a, d1):
        f = (t - a + 1) / max(d1 - a, 1)
        f = f * f * (3 - 2 * f)
        A = g["posed_world"][t]
        hip = A["Hips"].translation
        piv = Vector((hip.x, hip.y, S.get("pivotZ", 0.15)))
        M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(S.get("deg", 75)) * f, 4, axis) @ Matrix.Translation(-piv)
        for n in list(A.keys()):
            if n != "Root" and n not in STATIC:
                A[n] = M @ A[n]
    print("HOOK COVE slump from death frame", S.get("start", 2), "deg", S.get("deg", 75))
