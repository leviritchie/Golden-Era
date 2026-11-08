"""Hand-keyed joint animation for units with no usable mocap (shared extension, any faction).

Use with a stand-in capture from tools/homm3_def_retarget/hand_stub.py (motionless), so every
bone starts at rest and all motion comes from here. Unit config:

  "extensions": ["hand_keys"],
  "handKeys": {
    "Idle":        [{"f": 0, "bones": {"Spine1": [0, 0, 0]}},
                    {"f": 4, "bones": {"Spine1": [6, 0, 0]}, "root": [0, 0, 0.02]}],
    "AttackFront": [{"f": 0, "bones": {"RightArm": [0, 0, 0]}},
                    {"f": 3, "bones": {"RightArm": [-80, 0, 20], "RightForeArm": [-30, 0, 0]}}]
  }

- Clip names are the contract suffixes (Idle, Move, MoveStart, MoveEnd, Mouseover, Hitted,
  Defence, AttackFront, ShootFront, Death). "f" is the frame index within that clip (0-based, one
  per DEF frame); look at the DEF frames of the clip to choose the poses.
- "bones": XYZ Euler degrees, in the bone's own rest frame (Y runs along the bone), applied on top
  of the rest pose. Each bone interpolates (slerp) between the keys that mention it and holds
  before its first / after its last key; bones never mentioned in a clip stay at rest.
- "root": world-space offset (Blender units, Z up) applied to the whole body, interpolated.
- Any bone in the rig can be keyed, including hook-added chains, as long as it exists by the
  after_pose stage. Clips with no entry stay at the rest pose. Idle/Move loops still get the
  pipeline's closing key, so key the last frame near the first for a clean loop.
- silhouetteRefine still runs afterwards and can absorb small offsets/lean versus the DEF.
"""
import json


def after_pose(g):
    cfg = g["cfg"]; keys = cfg.get("handKeys")
    if not keys:
        return
    Matrix, Vector, Quaternion, Euler = g["Matrix"], g["Vector"], g["Quaternion"], __import__("mathutils").Euler
    rest, parent_of, posed_world = g["rest"], g["parent_of"], g["posed_world"]
    order = [b for b in g["bone_names"]]
    order += [b for b in posed_world[0] if b not in order and b != "Root" and b in parent_of]
    segs = json.load(open(g["MASTER"]))["segments"]

    def sample(clip_keys, i):
        rot, root = {}, Vector((0, 0, 0))
        bones = {b for k in clip_keys for b in k.get("bones", {})}
        for b in bones:
            ks = sorted((k["f"], k["bones"][b]) for k in clip_keys if b in k.get("bones", {}))
            q = lambda e: Euler([x * 3.14159265 / 180 for x in e], 'XYZ').to_quaternion()
            if i <= ks[0][0]:
                rot[b] = q(ks[0][1])
            elif i >= ks[-1][0]:
                rot[b] = q(ks[-1][1])
            else:
                for (f0, e0), (f1, e1) in zip(ks, ks[1:]):
                    if f0 <= i <= f1:
                        rot[b] = q(e0).slerp(q(e1), (i - f0) / max(f1 - f0, 1)); break
        rk = sorted((k["f"], k["root"]) for k in clip_keys if "root" in k)
        if rk:
            if i <= rk[0][0]:
                root = Vector(rk[0][1])
            elif i >= rk[-1][0]:
                root = Vector(rk[-1][1])
            else:
                for (f0, v0), (f1, v1) in zip(rk, rk[1:]):
                    if f0 <= i <= f1:
                        root = Vector(v0).lerp(Vector(v1), (i - f0) / max(f1 - f0, 1)); break
        return rot, root

    n_keyed = 0
    for s in segs:
        clip_keys = keys.get(s["contractSuffix"])
        if not clip_keys:
            continue
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            rot, root = sample(clip_keys, i)
            A = posed_world[t]
            for b in order:
                par = parent_of.get(b)
                if par is None or par not in A:
                    continue
                local = rest[par].inverted() @ rest[b]
                R = rot.get(b)
                A[b] = A[par] @ local @ (R.to_matrix().to_4x4() if R else Matrix.Identity(4))
            if root.length > 0:
                off = Matrix.Translation(root)
                for b in order:
                    if b in A:
                        A[b] = off @ A[b]
            n_keyed += 1
    print("HANDKEYS frames posed", n_keyed, "clips", sorted(keys))
