"""Castle: turn a mounted unit's horse toward the DEF's profile view (Castle copy of necropolis_yaw).

The shared sprite camera looks at the model from its front-left, which suits a humanoid drawn
three-quarter front; the DEF draws a horse nearly in profile, head to screen right, so a Meshy horse
built facing -Y renders head-on. after_pose (list it after castle_mount, before castle_refine):
every posed bone except Root is turned about +Z through the origin by `yawDeg` in every frame, a
rigid turn of the whole animated body; the rest mesh and bind pose are untouched. Only Hips
carries location keys, so every turned bone must descend from Hips (castle_mount re-parents the
horse chains from Root to Hips for this reason).

Config: "yawDeg": 40 (positive turns a -Y-facing head toward screen right).
"""
import math


def after_pose(g):
    yaw = g["cfg"].get("yawDeg")
    if not yaw:
        return
    Rz = g["Matrix"].Rotation(math.radians(yaw), 4, 'Z')
    for A in g["posed_world"]:
        for n in list(A):
            if n != "Root":
                A[n] = Rz @ A[n]
    _heading(g, 0, "after_yaw")
    print("HOOK castle_yaw", yaw, "applied to", len(g["posed_world"]), "frames")


def _heading(g, t, tag):
    A = g["posed_world"][t]
    if "HNeck2" in A and "HTail1" in A:
        n = A["HNeck2"].translation; tl = A["HTail1"].translation
        print("YAWCHECK", tag, t, "neck2 head", tuple(round(c, 2) for c in n), "tail1 head", tuple(round(c, 2) for c in tl))


def before_keys(g):
    if g["cfg"].get("yawDeg"):
        _heading(g, 0, "before_keys")
