"""Cove extension: a water spirit (nereid) sinks into a puddle and rises out of one.

The DEF nereid does not walk: MoveStart sinks her into a puddle, MoveEnd raises her out of one
(the puddle itself is a sprite effect). From `out[1]` the pose of that frame is held and the body
squashes toward the ground point under the hips (uniform scale: a non-uniform one on rotated bones becomes shear,
which glTF bone TRS cannot carry) until it is hidden (k ~ 0) at `out[2]` and stays hidden to the end
of the clip. MoveEnd mirrors it: hidden until `in[1]`, then grows back into the pose of frame
`in[2]`, after which the clip's own poses play.

Config: "coveSink": {"out": ["MoveStart", 3, 7], "in": ["MoveEnd", 6, 10], "power": 1.3}
Runs at before_keys (after every other pose change, so the tail/column follows the held pose).
"""
import json
from mathutils import Matrix, Vector


def _segment(g, clip):
    segs = [s for s in json.load(open(g["MASTER"]))["segments"] if s["contractSuffix"] == clip]
    return max(segs, key=lambda s: s["frameCount"])


def before_keys(g):
    sp = g["cfg"].get("coveSink")
    if not sp:
        return
    pw, J, about, body_bones = g["posed_world"], g["J"], g["about"], g["body_bones"]
    tgt = Vector((J["Hips"][0], J["Hips"][1], 0.0))
    pwr = sp.get("power", 1.3)

    def place(t, src, k):
        k = max(1e-3, k)
        A = {n: m.copy() for n, m in pw[src].items()}
        M = about(tgt, Matrix.Diagonal((k, k, k, 1.0)))
        for n in body_bones(A):
            A[n] = M @ A[n]
        pw[t] = A

    if "out" in sp:
        clip, a, b = sp["out"]
        s = _segment(g, clip); t0 = s["globalStart"] + a
        for t in range(t0, s["globalEnd"]):
            f = min(1.0, (t - t0) / max(b - a, 1))
            place(t, t0, (1 - f) ** pwr)
    if "in" in sp:
        clip, a, b = sp["in"]
        s = _segment(g, clip); t1 = s["globalStart"] + b
        for t in range(s["globalStart"], min(t1, s["globalEnd"])):
            f = max(0.0, (t - (s["globalStart"] + a)) / max(b - a, 1))
            place(t, t1, f ** pwr)
    print("HOOK COVE sink out", sp.get("out"), "in", sp.get("in"))
