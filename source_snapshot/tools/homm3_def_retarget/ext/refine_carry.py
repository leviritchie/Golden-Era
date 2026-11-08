"""Carry free prop bones with castle_refine's whole-body correction.

castle_refine shifts and rolls every posed body bone per frame, but leaves the free-bone list (RUBBLE_BONES) alone,
and stronghold_propbone registers a held prop (the orc berserker's Axe) there so it can be hidden and keyed with
location. In pose-follow trial A (2026-09-27) the berserker's body therefore moved off while its axe stayed on the
ground. This hook re-applies the same per-frame transform to the named bones.

Config (unit json): "refineCarry": ["Axe", ...], listed in "extensions" right after "castle_refine".
The transform is rebuilt from <out>.castle_refine.json (dx, dy in sprite px, roll in degrees about the camera axis
through the pre-shift hips): the hips' shifted world position minus the shift gives that pivot. A named bone that is
not a free bone, or a castle_refine log that is missing, is refused (fail closed).
Proof tier: generated artifact.
"""
import json
import math
import os
import numpy as np


def before_keys(g):
    names = g["cfg"].get("refineCarry")
    if not names:
        return
    Matrix, Vector = g["Matrix"], g["Vector"]
    rub = set(g.get("RUBBLE_BONES", []))
    bad = [n for n in names if n not in rub]
    if bad:
        raise SystemExit(f"refineCarry: {bad} are not free bones (castle_refine already moves posed body bones)")
    path = g["OUT"] + ".castle_refine.json"
    if not os.path.exists(path):
        raise SystemExit("refineCarry: no castle_refine log; list refine_carry after castle_refine")
    R_ = np.array(g["right"]); U_ = np.array(g["up"]); s_px = g["s_px"]; fwd = g["fwd_cam"]
    n_moved = 0
    for e in json.load(open(path)):
        dx, dy, roll = e.get("dx", 0.0), e.get("dy", 0.0), e.get("roll", 0.0)
        if not (dx or dy or roll):
            continue
        A = g["posed_world"][e["frame"]]
        d = Vector(tuple(R_ * dx / s_px + U_ * dy / s_px))
        Tm = Matrix.Translation(d)
        if roll:
            hv = A["Hips"].translation - d
            Tm = Tm @ Matrix.Translation(hv) @ Matrix.Rotation(math.radians(roll), 4, fwd) @ Matrix.Translation(-hv)
        for n in names:
            A[n] = Tm @ A[n]
        n_moved += 1
    print("REFINE_CARRY", names, "frames", n_moved)
