"""Write the bench's rig state (new joints, re-bound pivots, re-parented bones, edited skin weights, relaxed rest shape,
CS-excluded morphs) into a GLB: the work GLB with those parts replaced. Pose edits are NOT baked here (export.py runs
the patch lane's keyRotations/keyTranslations on top). Experiment folder only.

New accessors are appended (the old ones stay as unreferenced bytes; the file grows by the rewritten attributes).
"""
from __future__ import annotations

import copy

import numpy as np

from stride_match_glb import Glb, write_channels  # noqa: E402  (anim_core puts the delivery tools on sys.path)


def append_typed(g: Glb, arr: np.ndarray, typ: str, ctype: int, minmax: bool = False) -> int:
    dt = {5126: "<f4", 5123: "<u2", 5121: "u1"}[ctype]
    arr = np.ascontiguousarray(arr, dtype=dt)
    while len(g.bin) % 4:
        g.bin.append(0)
    off = len(g.bin)
    g.bin += arr.tobytes()
    g.json["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
    acc = {"bufferView": len(g.json["bufferViews"]) - 1, "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
    if minmax:
        acc["min"] = [float(x) for x in arr.min(0)]
        acc["max"] = [float(x) for x in arr.max(0)]
    g.json["accessors"].append(acc)
    return len(g.json["accessors"]) - 1


def build_rig_glb(work_bytes: bytes, u, rig) -> Glb:
    s, p = u.scene, rig.p
    g = Glb(work_bytes)
    js = g.json
    js["nodes"] = copy.deepcopy(s.nodes)
    node = js["nodes"][s.body_node]
    skin = js["skins"][node["skin"]]
    skin["joints"] = [int(j) for j in s.joints]
    skin["inverseBindMatrices"] = append_typed(g, s.ibm.transpose(0, 2, 1).reshape(-1, 16), "MAT4", 5126)
    p_changed = not np.array_equal(p.P, s.P)
    m_changed = s.morphs is not p.morphs
    off = 0
    for prim in js["meshes"][node["mesh"]]["primitives"]:
        at = prim["attributes"]
        n = js["accessors"][at["POSITION"]]["count"]
        sl = slice(off, off + n)
        at["JOINTS_0"] = append_typed(g, s.J[sl], "VEC4", 5123)
        at["WEIGHTS_0"] = append_typed(g, s.W[sl], "VEC4", 5126)
        if p_changed:
            at["POSITION"] = append_typed(g, s.P[sl], "VEC3", 5126, minmax=True)
            if "NORMAL" in at:
                at["NORMAL"] = append_typed(g, s.N[sl], "VEC3", 5126)
        if m_changed:
            for k, t in enumerate(prim.get("targets", [])):
                t["POSITION"] = append_typed(g, s.morphs[k, sl], "VEC3", 5126, minmax=True)
        off += n
    anims = {a.get("name"): a for a in js.get("animations", [])}
    for clip, chans in s.channels.items():
        old = p.channels.get(clip, [])
        changed = [ch for ch in chans if not any(ch is o for o in old)]
        groups = {}
        for path, nd, ti, vo, it in changed:
            groups.setdefault((ti.tobytes(), it), (ti, {}))[1][(nd, path)] = np.asarray(vo, np.float64).reshape(len(ti), -1)
        for (_, it), (ti, targets) in groups.items():
            write_channels(g, anims[clip], np.asarray(ti, np.float64), targets, it)
    ex = js.setdefault("asset", {}).setdefault("extras", {})
    ex["haikuAnimBenchRig"] = {"ops": rig.ops, "newJoints": rig.new_joints,
                               "note": "experiment only; CS morphs not re-baked for the new weights"}
    return Glb(g.to_bytes())
