"""Castle: arms Meshy modelled folded across the chest (monks, priests) move mostly with the chest.

A monk's forearms and hands lie across the robe front as one fused surface with the chest and the
sleeves; there is no chest behind them. Any rotation of the arm chain relative to the torso opens
long shards across the whole front (h3_monk with the full capture: reel edges>2x 26k). This
after_pose hook blends each configured arm bone's world rotation between "rigid with its parent
as in the rest pose" (0) and the capture rotation (1), per clip, then rebuilds the chain heads,
so the arms keep a damped share of the capture's gesture. Only the arm chains are touched.

Config: "extensions": ["castle_armblock"],
  "armBlock": {"bones": ["LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", ...],
               "follow": 0.2, "clipFollow": {"Death": 0.4},
               "boneFollow": {"Head": 0.3}}   (optional per-bone share, overrides the clip value;
  any bone may be listed, e.g. a capture neck/head that droops where the DEF stays upright)
"""
import json


def after_pose(g):
    AB = g["cfg"].get("armBlock")
    if not AB:
        return
    rest, parent_of, names = g["rest"], g["parent_of"], g["bone_names"]
    Matrix, Quaternion = g["Matrix"], g["Quaternion"]
    bones = [n for n in names if n in set(AB["bones"])]   # bone_names is parent-first
    clip_of = {}
    for sg in json.load(open(g["MASTER"]))["segments"]:
        for t in range(sg["globalStart"], sg["globalEnd"]):
            clip_of[t] = sg["contractSuffix"]
    cf = AB.get("clipFollow", {}); bf = AB.get("boneFollow", {})
    for t, A in enumerate(g["posed_world"]):
        f = cf.get(clip_of.get(t), AB.get("follow", 0.2))
        for n in bones:
            par = parent_of[n]; Rb = rest[n]
            head = A[par] @ (rest[par].inverted() @ Rb.translation)
            rigid = (A[par] @ rest[par].inverted() @ Rb).to_quaternion()
            cap = A[n].to_quaternion()
            if rigid.dot(cap) < 0:
                cap = -cap
            q = rigid.slerp(cap, bf.get(n, f))
            A[n] = Matrix.Translation(head) @ q.to_matrix().to_4x4()
        # descendants of the blended bones (hand ends, fingers) follow their parents rigidly
        for n in names:
            par = parent_of.get(n)
            if n in bones or par is None or par not in bones:
                continue
            A[n] = A[par] @ rest[par].inverted() @ rest[n]
    print("HOOK castle_armblock", len(bones), "bones, follow", AB.get("follow", 0.2), cf)
