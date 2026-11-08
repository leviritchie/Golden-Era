"""Dungeon death slump for snake-bodied units (hook module for build_unit.py; list it in "extensions").

The DEF medusa collapses onto her coil in the last Death frames, but the human capture keeps the
torso upright (a person's death falls to the ground, which a coil standing 1 m tall cannot follow).
With "slump": {"clip": "Death", "frames": n, "angle": deg, "dir": [x, y, z]} the last n frames of
that clip bend the upright part of the snake body forward (toward dir) by up to deg degrees, easing
in. The bend is spread over the tail joints between the waist and the first grounded tail point,
so the snake neck curls instead of creasing; the torso, arms and head ride on the bend unchanged.
Only bone world matrices change, so weights (and the 4-influence limit) are untouched.
"""
import json
import math
from mathutils import Matrix, Vector


def before_keys(g):
    sp = g["cfg"].get("slump")
    TAILB = g.get("TAILB") or []
    if not sp or not TAILB:
        return
    pw, rest = g["posed_world"], g["rest"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    k = max(1, min(int(g.get("gidx_", len(TAILB) // 3)), len(TAILB) - 1))
    tailset = set(TAILB)
    dirv = Vector(sp.get("dir", (0, -1, 0))).normalized()
    axis = Vector((0, 0, 1)).cross(dirv).normalized()   # rotating +Z toward dir
    segs = json.load(open(g["MASTER"]))["segments"]
    n_ = 0
    for s in segs:
        if s["contractSuffix"] != sp.get("clip", "Death"):
            continue
        nf = min(int(sp.get("frames", 3)), s["frameCount"])
        for i in range(nf):
            t = s["globalEnd"] - nf + i
            ease = (i + 1) / nf
            ease = ease * ease * (3 - 2 * ease)
            step = math.radians(sp.get("angle", 70)) * ease / k
            A = pw[t]
            for j in range(k, 0, -1):   # lowest bend first; Tail_j itself stays, everything above it turns
                upper = [n for n in A if n not in skip and (n not in tailset or TAILB.index(n) < j)]
                piv = A[TAILB[j]].translation.copy()
                M = Matrix.Translation(piv) @ Matrix.Rotation(step, 4, axis) @ Matrix.Translation(-piv)
                for n in upper:
                    A[n] = M @ A[n]
            n_ += 1
    print("SLUMP bend joints", k, "frames", n_)
