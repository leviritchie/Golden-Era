"""Conflux wing fold (hook module for build_unit.py; list it in "extensions").

The shared `wings` option swings rigid wing bones OPEN from their rest pose by the DEF sprite's
width, so it needs a mesh whose wings rest folded. The phoenix meshes rest with the wings spread
(near horizontal), while the DEF phoenix folds them in Idle/Defence and opens them in Move/Attack.
With "conflux": {"wingFold": {"deg": 60, "power": 1.0}} and the unit's wings configured with
wingMaxDeg 0 (no opening), each wing bone is swung DOWN about the body's front-back axis through
its own head by deg * (1 - spread)^power, where spread is the same width measure the shared wing
code uses (0 = idle frame 0's width, 1 = the widest DEF frame). Runs in before_keys, after
silhouetteRefine, so refine must not include the "wing" parameter.
"upDeg": u raises the wings by u * spread^power above rest in wide frames (the DEF shows open wings
raised in the image plane; a horizontal wing is edge-on to the sprite camera once the bird is yawed).
"axis": "side" swings about the body's left-right axis instead (wings that rest folded and point
backward, sacred phoenix: raising them lifts the tips up behind the back).
"clipAngles": {"<contractSuffix>": [deg per DEF frame, ...]} adds a per-frame swing (positive =
down, negative = up) for a flapping clip (phoenix Move), read off that clip's DEF frames.
"""
import math
import numpy as np
from mathutils import Matrix, Vector


def before_keys(g):
    wf = g["cfg"].get("conflux", {}).get("wingFold")
    if not wf:
        return
    deg, pw, up = wf.get("deg", 60.0), wf.get("power", 1.0), wf.get("upDeg", 0.0)
    wd = np.array(g["sj"]["widths"], float); w0 = wd[0]; wmax = max(wd.max(), w0 + 1)
    spread = np.clip((wd - w0) / (wmax - w0), 0, 1)
    wings = g["cfg"].get("wings", [])
    fwd = Vector((1, 0, 0)) if wf.get("axis") == "side" else Vector((0, 1, 0))
    extra = {}
    import json
    for sg in json.load(open(g["MASTER"]))["segments"]:
        ang = wf.get("clipAngles", {}).get(sg["contractSuffix"])
        if ang:
            for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
                extra[t] = ang[min(i, len(ang) - 1)]
    for t, A in enumerate(g["posed_world"]):
        k = (1 - spread[t]) ** pw
        for w in wings:
            n = w["bone"]
            if n not in A:
                continue
            # body's front-back axis in this frame: parent's rest Y (world) carried by its pose
            par = w.get("parent", "Spine2")
            ax = (A[par].to_3x3() @ (g["rest"][par].to_3x3().inverted() @ fwd)).normalized()
            piv = A[n].translation.copy()
            # "down" sign from the wing itself: the rotation sense that lowers its tip
            tip = (A[n] @ Vector((0, 0.3, 0, 1))).to_3d() - piv
            side = 1 if (Matrix.Rotation(0.2, 3, ax) @ tip).z < tip.z else -1
            R = Matrix.Rotation(math.radians(deg * k - up * spread[t] ** pw + extra.get(t, 0.0)) * side, 4, ax)
            A[n] = Matrix.Translation(piv) @ R @ Matrix.Translation(-piv) @ A[n]
    print("CONFLUX wingFold", deg, "spread per frame", [round(float(x), 2) for x in spread])
