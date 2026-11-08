"""Dungeon yaw clamp (hook module for build_unit.py; list it in "extensions").

The capture is a human pose estimator run on the DEF frames. On the medusa queen/warrior sprites it
reads the hitted and death frames as the body turning 90-180 degrees away from the camera, which
the DEF does not show (she keeps facing screen right); on a snake body with a planted coil that
twist wrings the snake neck. With "yawClamp": deg, each frame's whole posed body is turned about
+Z through the hips so the torso's facing (the Hips bone's rest forward, projected on the ground
plane) stays within deg degrees of its rest facing; lean and pitch are kept. With "tiltClamp": deg
(floating bodies the estimator reads upside down), the whole pose is then turned about the hips so
the Hips bone's up axis leans at most deg degrees from its rest direction. Runs in after_pose,
before the tail is solved, so the tail follows the corrected hips. Only bone world matrices change.
"""
import math
from mathutils import Matrix, Vector


def after_pose(g):
    lim = g["cfg"].get("yawClamp")
    tl = g["cfg"].get("tiltClamp")
    if lim is None and tl is None:
        return
    lim = 360 if lim is None else lim
    rest, pw = g["rest"], g["posed_world"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    local = rest["Hips"].to_3x3().inverted() @ Vector((0, -1, 0))
    yaws, n_ = [], 0
    for A in pw:
        f = A["Hips"].to_3x3() @ local
        yaw = math.degrees(math.atan2(f.x, -f.y))   # signed angle about +Z from (0,-1,0) to f's ground projection
        yaws.append(yaw)
        if abs(yaw) <= lim:
            continue
        corr = -(yaw - math.copysign(lim, yaw))
        piv = A["Hips"].translation.copy()
        M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(corr), 4, 'Z') @ Matrix.Translation(-piv)
        for n in list(A.keys()):
            if n not in skip:
                A[n] = M @ A[n]
        n_ += 1
    tilts, nt = [], 0
    upl = rest["Hips"].to_3x3().inverted() @ Vector((0, 0, 1))
    for A in pw:
        up = A["Hips"].to_3x3() @ upl
        ang = math.degrees(up.angle(Vector((0, 0, 1))))
        tilts.append(ang)
        if tl is None or ang <= tl:
            continue
        axis = up.cross(Vector((0, 0, 1)))
        if axis.length < 1e-6:
            axis = Vector((1, 0, 0))
        piv = A["Hips"].translation.copy()
        M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(ang - tl), 4, axis.normalized()) @ Matrix.Translation(-piv)
        for n in list(A.keys()):
            if n not in skip:
                A[n] = M @ A[n]
        nt += 1
    print("TILTCLAMP", tl, "frames clamped", nt, "tilt per frame", [round(x) for x in tilts])
    print("YAWCLAMP", lim, "frames clamped", n_, "yaw per frame", [round(y) for y in yaws])
