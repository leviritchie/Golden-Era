"""Cove: turn a rest-straight tail chain sideways in every clip (nix, nix warrior).

The regenerated nix meshes carry their tail straight back (+Y), which the sprite camera (in front
of the unit, looking +Y) hides behind the legs. The DEF draws the tail swept out to screen-left,
i.e. behind and to the unit's right (world -X). after_pose (list this AFTER rampart_quadruped, so its
sway rides on top, and BEFORE cove_tailtrail / idle_cycle): in every frame the first `bones` tail
bones each turn deg/bones about the hips' current up axis, pivoting at their own heads, and every
bone below follows. Only bone world matrices change.

Config "coveTailYaw": {"prefix": "QTail", "deg": 25, "bones": 3}
deg > 0 turns the tail toward world -X (the unit's right; the unit faces -Y). Both nix units use 25:
50 read too flat and long against the DEF. Prints "HOOK COVE tailyaw ...".
Status 2026-09-26: generated artifact only (hota_cove_nix, hota_cove_nix_warrior); nothing in game.
"""
import math
from mathutils import Matrix, Vector


def after_pose(g):
    C = g["cfg"].get("coveTailYaw")
    if not C:
        return
    pre = C.get("prefix", "QTail")
    rest, parent_of, pw = g["rest"], g["parent_of"], g["posed_world"]
    tail = sorted(b for b in parent_of if b.startswith(pre + "_"))
    nb = max(1, min(int(C.get("bones", 3)), len(tail)))
    step = math.radians(C.get("deg", 0.0)) / nb
    ch = {}
    for b, p in parent_of.items():
        ch.setdefault(p, []).append(b)

    def subtree(b):
        out = [b]; i = 0
        while i < len(out):
            out += ch.get(out[i], []); i += 1
        return out
    subs = {b: subtree(b) for b in tail[:nb]}
    n_ = 0
    for A in pw:
        if "Hips" not in A:
            continue
        up = (A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted() @ Vector((0, 0, 1))).normalized()
        R = Matrix.Rotation(step, 4, up)
        for b in tail[:nb]:
            if b not in A:
                continue
            piv = A[b].translation.copy()
            M = Matrix.Translation(piv) @ R @ Matrix.Translation(-piv)
            for c in subs[b]:
                if c in A:
                    A[c] = M @ A[c]
        n_ += 1
    print("HOOK COVE tailyaw frames", n_, "deg", C.get("deg"), "over", nb, "bones", flush=True)
