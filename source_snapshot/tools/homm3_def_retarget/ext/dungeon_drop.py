"""Dungeon death drop for floating units (hook module for build_unit.py; list it in "extensions").

The DEF evil eye / beholder falls out of the air onto a heap of tentacles in its last Death frames;
the capture keeps it hovering. With "deathDrop": {"frames": n, "hipsZ": z, "splay": deg}, the last n
Death frames ease the whole pose down until the Hips sit at height z, and turn each leg chain
(the hanging tentacles) about its UpLeg head so it points outward and down by `splay` degrees below
horizontal, so the tentacles spread on the ground instead of passing through it. Only bone world
matrices change (weights untouched).
"""
import json
import math
from mathutils import Matrix, Quaternion, Vector


def before_keys(g):
    sp = g["cfg"].get("deathDrop")
    if not sp:
        return
    pw, rest = g["posed_world"], g["rest"]
    skip = set(g.get("STATIC", ())) | set(g.get("RUBBLE_BONES", ())) | {"Root"}
    chains = {s: [n for n in (f"{s}UpLeg", f"{s}Leg", f"{s}Foot", f"{s}ToeBase") if n in pw[0]] for s in ("Left", "Right")}
    n_ = 0
    for s in json.load(open(g["MASTER"]))["segments"]:
        if s["contractSuffix"] != sp.get("clip", "Death"):
            continue
        nf = min(int(sp.get("frames", 2)), s["frameCount"])
        for i in range(nf):
            t = s["globalEnd"] - nf + i
            e = (i + 1) / nf; e = e * e * (3 - 2 * e)
            A = pw[t]
            dz = (A["Hips"].translation.z - sp.get("hipsZ", 0.3)) * e
            T = Matrix.Translation(Vector((0, 0, -dz)))
            for n in list(A.keys()):
                if n not in skip:
                    A[n] = T @ A[n]
            for side, ch in chains.items():
                if not ch:
                    continue
                piv = A[ch[0]].translation.copy()
                tip = A[ch[-1]].translation
                cur = (tip - piv).normalized()
                hip_x = A["Hips"].to_3x3().col[0].normalized()
                out = hip_x if side == "Left" else -hip_x
                out.z = 0
                out = out.normalized() * math.cos(math.radians(sp.get("splay", 15))) + Vector((0, 0, -math.sin(math.radians(sp.get("splay", 15)))))
                q = cur.rotation_difference(out.normalized())
                q = Quaternion().slerp(q, e)
                M = Matrix.Translation(piv) @ q.to_matrix().to_4x4() @ Matrix.Translation(-piv)
                for n in ch:
                    A[n] = M @ A[n]
            n_ += 1
    print("DEATHDROP frames", n_)
