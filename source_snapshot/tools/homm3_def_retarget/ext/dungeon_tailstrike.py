"""Dungeon scorpion-tail strike (hook module for build_unit.py; list it AFTER the extension that
builds the tail chain, e.g. rampart_quadruped, in "extensions").

The DEF manticore / scorpicore attack by whipping the scorpion tail up and forward over the back;
a procedural quadruped only sways its tail. With "tailStrike": {"prefix": "QTail", "clip":
"AttackFront", "lift": deg, "uncurl": deg, "peak": 0.4}, each frame of that clip first uncurls
the tail (the joints after the first turn back by uncurl/(n-1) each) and then swings the whole
tail forward about its root by `lift`, both scaled by an envelope that rises to 1 at `peak` of the
clip and returns to 0 at its end (the clip starts and ends on the rest tail). The swing axis is
up x (Hips -> Spine), so a positive lift swings the tail up and toward the head. Only bone world matrices change.
"""
import json
import math
from mathutils import Matrix, Vector


def _env(u, peak):
    if u <= peak:
        x = u / max(peak, 1e-6)
    else:
        x = (1 - u) / max(1 - peak, 1e-6)
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def before_keys(g):
    sp = g["cfg"].get("tailStrike")
    if not sp:
        return
    pw = g["posed_world"]
    pre = sp.get("prefix", "QTail")
    chain = sorted(n for n in pw[0] if n.startswith(pre + "_"))
    if len(chain) < 2:
        print("TAILSTRIKE no chain", pre); return
    n_ = 0
    for s in json.load(open(g["MASTER"]))["segments"]:
        if s["contractSuffix"] != sp.get("clip", "AttackFront"):
            continue
        nf = s["frameCount"]
        for i in range(nf):
            e = _env(i / max(nf - 1, 1), sp.get("peak", 0.4))
            if e <= 0:
                continue
            A = pw[s["globalStart"] + i]
            fwd = A["Spine"].translation - A["Hips"].translation
            ax = Vector((0, 0, 1)).cross(fwd)
            ax.normalize()   # up x forward: a positive angle swings up toward forward
            un = math.radians(sp.get("uncurl", 60)) * e / (len(chain) - 1)
            for k in range(1, len(chain)):
                piv = A[chain[k]].translation.copy()
                M = Matrix.Translation(piv) @ Matrix.Rotation(-un, 4, ax) @ Matrix.Translation(-piv)
                for n in chain[k:]:
                    A[n] = M @ A[n]
            piv = A[chain[0]].translation.copy()
            M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(sp.get("lift", 40)) * e, 4, ax) @ Matrix.Translation(-piv)
            for n in chain:
                A[n] = M @ A[n]
            n_ += 1
    print("TAILSTRIKE", pre, "bones", len(chain), "frames", n_)
