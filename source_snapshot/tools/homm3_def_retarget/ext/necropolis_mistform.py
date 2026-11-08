"""Necropolis: vampires dissolve into mist for Move (the DEF flies as a bat inside a cloud).

The vampire DEF's MoveStart turns the body into a mist cloud that releases a bat, Move is the
bat alone, and MoveEnd reverses it. A humanoid mesh cannot become a bat, so this hook
(before_keys) shrinks the whole body into a point at the chest across MoveStart, keeps it hidden
through Move, and grows it back across MoveEnd. The mist and the bat are effects for the game
side. Config: "mistForm": {"power": 1.2, "pivot": "Spine1"}.
"""
import json
from mathutils import Matrix


def before_keys(g):
    mf = g["cfg"].get("mistForm")
    if mf is None:
        return
    posed_world, STATIC = g["posed_world"], g["STATIC"]
    rub = set(g.get("RUBBLE_BONES") or [])
    pw, piv_bone = mf.get("power", 1.2), mf.get("pivot", "Spine1")
    tiny = 1e-3
    segs = json.load(open(g["MASTER"]))["segments"]
    sched = {}
    for s in segs:
        n = s["frameCount"]; ts = list(range(s["globalStart"], s["globalEnd"]))
        if s["contractSuffix"] == "MoveStart":
            for i, t in enumerate(ts):
                sched[t] = max(tiny, (1 - (i + 1) / n) ** pw)
        elif s["contractSuffix"] == "Move":
            for t in ts:
                sched[t] = tiny
        elif s["contractSuffix"] == "MoveEnd":
            for i, t in enumerate(ts):
                sched[t] = max(tiny, (i / max(n - 1, 1)) ** pw)
    for t, k in sched.items():
        if k >= 0.999:
            continue
        A = posed_world[t]
        p = A[piv_bone].translation.copy()
        M = Matrix.Translation(p) @ Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation(-p)
        for n in A:
            if n != "Root" and n not in STATIC and n not in rub:
                A[n] = M @ A[n]
    print("MISTFORM frames", len(sched))
