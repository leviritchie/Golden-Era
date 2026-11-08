"""Cove: a raised tail trails straight out behind the body while flying (stormbird).

The DEF stormbird carries its tail curled up behind it when standing and streams it straight back
in MoveStart / Move / MoveEnd. The tail chain (rampart_quadruped "tail", bones QTail_00..) follows
the hips at its rest curl, so in flight it would still point up. after_pose (list this AFTER
rampart_quadruped): in each listed clip every tail bone, root to tip, turns its world direction
toward "behind" (with "frame": "hips" the hips' rest +Y, i.e. away from the -Y facing, dipped by `dipDeg`)
by the clip's weight ("frame": "world", the default, uses world +Y instead: a flying capture's
hips can be pitched anywhere), then a travelling wave of `waveDeg` about the hips' up axis is added.

Config "coveTailTrail": {"prefix": "QTail", "clips": {"Move": 1.0, "MoveStart": [0.3, 0.9],
  "MoveEnd": [0.9, 0.3]}, "dipDeg": 8, "waveDeg": 6, "rootShare": 0.5}
A number is a constant weight, a pair ramps linearly over the clip; the root bone (on the body)
turns only rootShare of the way. Only bone world matrices change.
"""
import json
import math
from mathutils import Matrix, Vector, Quaternion


def after_pose(g):
    C = g["cfg"].get("coveTailTrail")
    if not C:
        return
    pre = C.get("prefix", "QTail")
    rest, parent_of, pw = g["rest"], g["parent_of"], g["posed_world"]
    tail = sorted(b for b in parent_of if b.startswith(pre + "_"))
    ch = {}
    for b, p in parent_of.items():
        ch.setdefault(p, []).append(b)

    def subtree(b):
        out = [b]; i = 0
        while i < len(out):
            out += ch.get(out[i], []); i += 1
        return out
    dip = math.radians(C.get("dipDeg", 8)); wave = C.get("waveDeg", 6)
    back0 = Vector((0, math.cos(dip), -math.sin(dip)))
    n_ = 0
    for s in json.load(open(g["MASTER"]))["segments"]:
        v = C.get("clips", {}).get(s["contractSuffix"])
        if v is None:
            continue
        w0, w1 = (v, v) if isinstance(v, (int, float)) else v
        nf = s["frameCount"]
        for i in range(nf):
            w = w0 + (w1 - w0) * (i / max(nf - 1, 1))
            A = pw[s["globalStart"] + i]
            Rh = A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted() if C.get("frame") == "hips" else Matrix.Identity(3)
            back = (Rh @ back0).normalized(); up = Rh @ Vector((0, 0, 1))
            ph = 2 * math.pi * i / max(nf, 1)
            for k, b in enumerate(tail):
                if b not in A:
                    continue
                d = (A[b].to_3x3() @ Vector((0, 1, 0))).normalized()
                q = Quaternion().slerp(d.rotation_difference(back), w * (C.get("rootShare", 0.5) if k == 0 else 1.0))
                q = Quaternion(up, math.radians(wave * w * math.sin(ph - 0.8 * k))) @ q
                piv = A[b].translation.copy()
                M = Matrix.Translation(piv) @ q.to_matrix().to_4x4() @ Matrix.Translation(-piv)
                for c in subtree(b):
                    A[c] = M @ A[c]
            n_ += 1
    print("COVE tailtrail frames", n_, "bones", len(tail))
