"""Hand-keyed motion layered over a captured pose, for a clip the capture has no motion for (shared extension).

Use with tools/homm3_def_retarget/extend_master_clip.py: a DEF group the mocap corpus skipped (h3_leprechaun's
g18 hat-and-coins throw) is added as a clip whose capture rows all repeat idle frame 0, so every frame of the clip
starts from the unit's own captured idle pose. This hook moves chosen bones away from that pose; everything not
keyed keeps the captured pose, so the clip joins its idle bookends without a pop. (ext/hand_keys.py keys from the
REST pose and is for units with no capture at all.)

  "poseOverlay": {
    "ShootFront": [
      {"f": 0, "bones": {"LeftArm": "base", "LeftForeArm": "base"}},
      {"f": 3, "bones": {"LeftArm": {"aim": [0.3, -0.6, 0.75]}, "LeftHand": {"aim": [0, -1, 0.2], "twist": 90},
                         "Spine1": {"rot": [8, 0, 0]}}},
      {"f": 11, "bones": {"LeftArm": "base"}}]
  },
  "propCarry": [{"bone": "Hat", "hand": "LeftHand", "clip": "ShootFront", "grab": 1, "release": 9}]

- "f" is the frame within the clip (one per DEF frame). World frame: the mesh faces -Y, +X is its left, +Z up.
- A bone key is "base" (the captured pose), {"aim": [x, y, z]} (the bone's head->tail direction in world, reached
  by the shortest arc from the captured direction), {"rot": [x, y, z]} (world-axis degrees applied to the captured
  orientation about the bone head, X then Y then Z; +x tips an up-pointing bone forward), plus optional "twist"
  (degrees about the resulting bone axis). Between two keys of a bone the two corrections, each measured against
  that frame's orientation after the parent moved, are slerped;
  before its first / after its last key it is held. A bone with no key in the clip is not touched.
- Bones are applied parent first; an unkeyed child keeps its captured pose RELATIVE to its parent (a hand follows
  a raised arm).
- propCarry: for grab < i < release the prop bone rides the hand with the offset it had to the hand at frame
  `grab` (key the hand onto the prop at grab and back to the same place at release, so the prop leaves and returns
  without a jump). Outside that window the prop keeps its own parent (stronghold_propbone after_pose). List this
  extension AFTER stronghold_propbone.
Proof tier: generated artifact; the keyed motion is authored against the DEF frames, not captured.
"""
import json
import math


def _clips(g):
    return g["cfg"].get("poseOverlay", {}), g["cfg"].get("propCarry", [])


def after_pose(g):
    overlay, carry = _clips(g)
    if not overlay and not carry:
        return
    from mathutils import Euler, Matrix, Quaternion, Vector
    rest, parent_of, posed = g["rest"], g["parent_of"], g["posed_world"]
    order = list(g["bone_names"]) + [b for b in posed[0] if b not in g["bone_names"] and b in parent_of]
    segs = [s for s in json.load(open(g["MASTER"]))["segments"] if s["role"] == "cycle"]
    for clip in list(overlay) + [c["clip"] for c in carry]:
        if not any(s["contractSuffix"] == clip for s in segs):
            raise SystemExit(f"clip_overlay: clip {clip} is not a segment of the master sequence")
    known = set(order)

    def correction(spec, A_b):  # A_b: the bone's current world matrix
        """World rotation (about the bone head) that takes the captured orientation to the keyed one."""
        if spec == "base":
            return Quaternion()
        if not isinstance(spec, dict) or not set(spec) <= {"aim", "rot", "twist"} or not (set(spec) & {"aim", "rot"}):
            raise SystemExit(f"clip_overlay: bad bone key {spec!r}")
        R0 = A_b.to_3x3().normalized()
        if "aim" in spec:
            q = (R0.col[1]).rotation_difference(Vector(spec["aim"]).normalized())
        else:
            q = Euler([math.radians(x) for x in spec["rot"]], 'XYZ').to_quaternion()
        if spec.get("twist"):
            axis = (q.to_matrix() @ R0).col[1].normalized()
            q = Quaternion(axis, math.radians(spec["twist"])) @ q
        return q

    n = 0
    for s in segs:
        keys = overlay.get(s["contractSuffix"])
        if not keys:
            continue
        for k in keys:
            bad = set(k.get("bones", {})) - known
            if bad or not isinstance(k.get("f"), int) or not 0 <= k["f"] < s["frameCount"]:
                raise SystemExit(f"clip_overlay: {s['contractSuffix']} key {k.get('f')!r}: frame out of range or "
                                 f"unknown bones {sorted(bad)}")
        bones = {b for k in keys for b in k["bones"]}
        base = [dict(posed[t]) for t in range(s["globalStart"], s["globalEnd"])]
        kb = {b: sorted((k["f"], k["bones"][b]) for k in keys if b in k["bones"]) for b in bones}
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            A = posed[t]
            for b in order:
                par = parent_of.get(b)
                if par is None or par not in A or b not in A:
                    continue
                M = A[par] @ base[i][par].inverted() @ base[i][b]      # captured pose relative to the (new) parent
                if b in bones:
                    # both bracketing keys are measured against this frame's orientation (after the parent's
                    # correction), so an aim is reached exactly at its key whatever the parent did
                    ks = kb[b]
                    if i <= ks[0][0]:
                        q = correction(ks[0][1], M)
                    elif i >= ks[-1][0]:
                        q = correction(ks[-1][1], M)
                    else:
                        (f0, s0), (f1, s1) = next(p for p in zip(ks, ks[1:]) if p[0][0] <= i <= p[1][0])
                        q = correction(s0, M).slerp(correction(s1, M), (i - f0) / max(f1 - f0, 1))
                    head = M.translation.copy()
                    M = Matrix.Translation(head) @ (q.to_matrix() @ M.to_3x3()).to_4x4()
                A[b] = M
            n += 1
    for c in carry:
        s = next(x for x in segs if x["contractSuffix"] == c["clip"])
        p, h = c["bone"], c["hand"]
        if p not in posed[0] or h not in posed[0] or not 0 <= c["grab"] < c["release"] <= s["frameCount"]:
            raise SystemExit(f"clip_overlay: bad propCarry {c!r}")
        tg = s["globalStart"] + c["grab"]
        rel = posed[tg][h].inverted() @ posed[tg][p]
        for t in range(tg + 1, s["globalStart"] + c["release"]):
            posed[t][p] = posed[t][h] @ rel
        print("OVERLAY carry", p, "on", h, c["clip"], "frames", c["grab"] + 1, "to", c["release"] - 1)
    print("OVERLAY keyed frames", n)
