"""Devil teleport (hook for build_unit.py).

HoMM3 devils do not walk: MoveStart vanishes in a fire burst and MoveEnd reappears out of one
(the burst itself is a sprite effect). The capture under the burst is noise, so from the frame the
burst starts covering the body the pose is frozen and the body shrinks to a point on the ground,
stays hidden, and in MoveEnd grows back from that point into the pose of the first frame the
DEF shows it whole again.

Unit config:
  "teleport": {"out": [clip, first_local_frame, hidden_local_frame],
               "in":  [clip, first_visible_local_frame, whole_local_frame]}
e.g. {"out": ["MoveStart", 4, 7], "in": ["MoveEnd", 5, 8]}
"""
import json
from mathutils import Matrix, Vector


def _segment(g, clip):
    segs = [s for s in json.load(open(g["MASTER"]))["segments"] if s["contractSuffix"] == clip]
    return max(segs, key=lambda s: s["frameCount"])


def before_keys(g):
    tp = g["cfg"].get("teleport")
    if not tp:
        return
    pw = g["posed_world"]; J = g["J"]; about = g["about"]; body_bones = g["body_bones"]
    tgt = Vector((J["Hips"][0], J["Hips"][1], 0.0))

    def place(t, src, k):
        A = {n: m.copy() for n, m in pw[src].items()}
        M = about(tgt, Matrix.Diagonal((k, k, k, 1.0)))
        for n in body_bones(A):
            A[n] = M @ A[n]
        pw[t] = A

    clip, a, b = tp["out"]
    s = _segment(g, clip); t0 = s["globalStart"] + a
    for t in range(t0, s["globalEnd"]):
        f = min(1.0, (t - t0) / max(b - a, 1))
        place(t, t0, max(1e-3, (1 - f) ** 1.5))
    clip, a, b = tp["in"]
    s = _segment(g, clip); t1 = s["globalStart"] + b
    for t in range(s["globalStart"], min(t1, s["globalEnd"])):
        f = max(0.0, (t - (s["globalStart"] + a) + 1) / max(b - a + 1, 1))
        place(t, t1, max(1e-3, f ** 1.5))
    print("TELEPORT out", tp["out"], "in", tp["in"])
