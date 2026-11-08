"""Conflux body-tilt clamp (hook module for build_unit.py; list it in "extensions").

The capture is a human pose estimator run on the DEF frames. On a legless whirlwind or robe it
sometimes reads a frame upside down (storm/hurricane ShootFront: arms raised over a body it takes
for legs), and a floating unit then flips head-down. With "conflux": {"maxBodyTilt": deg} the whole
body of each frame is rotated about the hips so the Hips bone's up axis leans at most deg degrees
from its rest direction (the lean itself, when within the limit, is kept).
"""
import math
from mathutils import Matrix


def _clamp(g, frames, lim):
    rest, pw = g["rest"], g["posed_world"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    head = g["cfg"].get("conflux", {}).get("tiltAxis") == "head"
    def upv(A):
        if head:
            return (A["Head"].translation - A["Hips"].translation).normalized()
        return A["Hips"].to_3x3().col[1].normalized()
    up0 = upv(rest)
    n_ = 0
    for t in frames:
        A = pw[t]
        up = upv(A)
        ang = up0.angle(up)
        if ang <= math.radians(lim):
            continue
        axis = up.cross(up0)
        if axis.length < 1e-6:
            axis = A["Hips"].to_3x3().col[0]
        R = Matrix.Rotation(ang - math.radians(lim), 4, axis.normalized())
        piv = A["Hips"].translation.copy()
        M = Matrix.Translation(piv) @ R @ Matrix.Translation(-piv)
        for n in list(A.keys()):
            if n not in skip:
                A[n] = M @ A[n]
        n_ += 1
    return n_


def after_pose(g):
    lim = g["cfg"].get("conflux", {}).get("maxBodyTilt")
    if lim is None:
        return
    print("CONFLUX maxBodyTilt", lim, "frames clamped", _clamp(g, range(len(g["posed_world"])), lim))


def before_keys(g):
    spec = g["cfg"].get("conflux", {}).get("maxBodyTiltClips")
    if not spec:
        return
    import json
    segs = json.load(open(g["MASTER"]))["segments"]
    for suffix, lim in spec.items():
        fr = [t for s in segs if s["contractSuffix"] == suffix for t in range(s["globalStart"], s["globalEnd"])]
        print("CONFLUX maxBodyTiltClips", suffix, lim, "frames clamped", _clamp(g, fr, lim))
