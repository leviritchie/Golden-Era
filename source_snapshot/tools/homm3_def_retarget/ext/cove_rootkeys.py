"""Cove: re-apply hand_keys "root" offsets after rampart_quadruped (nix praetorian: hand keys + tail chain).

hand_keys moves every posed bone except Root by the keyed root offset. rampart_quadruped's
after_pose, which must run after it so the tail chain can sway, re-chains every bone's head onto its
parent's frame starting from the unmoved Root, so the offset is lost (a hand-keyed Death that drops
the body to the ground left it hanging in the air). List this module AFTER rampart_quadruped: in
each clip with root keys it translates every posed bone except Root by the same interpolated offset
hand_keys used (linear between keys, held before the first / after the last). Config: none (reads
"handKeys").
"""
import json
from mathutils import Matrix, Vector


def _root_at(clip_keys, i):
    rk = sorted((k["f"], k["root"]) for k in clip_keys if "root" in k)
    if not rk:
        return None
    if i <= rk[0][0]:
        return Vector(rk[0][1])
    if i >= rk[-1][0]:
        return Vector(rk[-1][1])
    for (f0, v0), (f1, v1) in zip(rk, rk[1:]):
        if f0 <= i <= f1:
            return Vector(v0).lerp(Vector(v1), (i - f0) / max(f1 - f0, 1))


def after_pose(g):
    keys = g["cfg"].get("handKeys")
    if not keys:
        return
    pw = g["posed_world"]; n_ = 0
    for s in json.load(open(g["MASTER"]))["segments"]:
        ck = keys.get(s["contractSuffix"])
        if not ck:
            continue
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            r = _root_at(ck, i)
            if r is None or r.length == 0:
                continue
            off = Matrix.Translation(r); A = pw[t]
            for b in list(A):
                if b != "Root":
                    A[b] = off @ A[b]
            n_ += 1
    print("COVE rootkeys frames", n_)
