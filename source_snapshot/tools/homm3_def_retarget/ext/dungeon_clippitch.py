"""Dungeon per-clip body pitch (hook module for build_unit.py; list it in "extensions").

The DEF dragons take off and glide with the body near horizontal in Move; the human capture stays
upright. With "clipPitch": {"Move": deg, "MoveStart": [deg0, deg1], "MoveEnd": [deg0, deg1]}, every
frame of a listed clip turns the whole pose forward about the hips by deg (a number: constant; a
pair: linear from the clip's first to its last frame, so MoveStart can lift into the glide and
MoveEnd can land out of it). Forward = the rest facing (-Y): the axis is +X, so a positive angle
tips the head toward -Y. Runs in after_pose, before wings, tail and silhouette refine.
"""
import json
import math
from mathutils import Matrix


def after_pose(g):
    spec = g["cfg"].get("clipPitch")
    if not spec:
        return
    pw = g["posed_world"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    n_ = 0
    for s in json.load(open(g["MASTER"]))["segments"]:
        v = spec.get(s["contractSuffix"])
        if v is None:
            continue
        a0, a1 = (v, v) if isinstance(v, (int, float)) else v
        nf = s["frameCount"]
        for i in range(nf):
            ang = a0 + (a1 - a0) * (i / max(nf - 1, 1))
            A = pw[s["globalStart"] + i]
            piv = A["Hips"].translation.copy()
            M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(ang), 4, 'X') @ Matrix.Translation(-piv)
            for n in list(A.keys()):
                if n not in skip:
                    A[n] = M @ A[n]
            n_ += 1
    print("CLIPPITCH frames", n_)
