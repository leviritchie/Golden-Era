"""Necropolis: turn a long-bodied unit (a mounted knight's horse) toward the DEF's profile view.

The shared sprite camera looks at the model from its front-left, which matches the DEF for a
humanoid (drawn three-quarter front). The DEF draws a horse almost in profile, head to screen
right, so a Meshy horse built facing -Y renders head-on.

after_pose (list it AFTER every extension with an after_pose hook, e.g. necropolis_horse): every
posed bone except Root is turned about +Z through the origin by `yawDeg`, in every frame. The rest
mesh and bind pose stay as built, so the turn is a rigid transform of the whole animated body that
the Hips key carries; the sprite camera, silhouette refine and prop aim all run afterwards on the
turned poses. (A first version rotated the rest mesh in after_skin, but the capture mapping it had
to wrap, map_capture, is defined after that hook runs: KeyError.)

Config: "yawDeg": 40 (positive turns a -Y-facing head toward screen right).
"""
import math
from mathutils import Matrix


def after_pose(g):
    yaw = g["cfg"].get("yawDeg")
    if not yaw:
        return
    Rz = Matrix.Rotation(math.radians(yaw), 4, 'Z')
    for A in g["posed_world"]:
        for n in list(A):
            if n != "Root":
                A[n] = Rz @ A[n]
    print("YAW", yaw, "applied to", len(g["posed_world"]), "frames")
