#!/usr/bin/env python3
"""Host-side world-space retarget of our clip onto Meshy's rig.

Pure GLB math (no Blender): builds both rigs' hierarchies + world rest
rotations from node TRS, computes our world pose per key from the clip's
local quats, solves Meshy's pose-local quats to reproduce those worlds, and
VERIFIES the result (W_B == W_A) before writing pose_locals to JSON.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

MESHY_ANIM = Path(
    r"C:/Users/<user>/Downloads/Meshy_AI_Azure_Knight_of_the_E_biped"
    r"/Meshy_AI_Azure_Knight_of_the_E_biped"
    r"/Meshy_AI_Azure_Knight_of_the_E_biped_Meshy_AI_Meshy_Merged_Animations.glb"
)
OUR_CLIP = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/crusader_pose_pipeline"
    r"/out_fit_strong/g00_move_pilot/move_g0_strong_fixed_length_ik.glb"
)
OUT_JSON = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/crusader_pose_pipeline/out_meshyrig_ourwalk/retarget_pose_locals.json"
)


def _glb(path: Path):
    d = path.read_bytes()
    off = 12
    chunks = []
    while off < len(d):
        clen, ctype = struct.unpack("<I4s", d[off : off + 8])
        chunks.append((ctype, d[off + 8 : off + 8 + clen]))
        off += 8 + clen
    j = json.loads(chunks[0][1].decode("utf-8"))
    return j, next(b for c, b in chunks if c == b"BIN\x00")


def _acc(doc, binbuf, i):
    a = doc["accessors"][i]
    if "bufferView" not in a:
        return None
    bv = doc["bufferViews"][a["bufferView"]]
    buf = binbuf[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}[a["componentType"]]
    return np.frombuffer(buf, dtype=np.dtype(dt), count=a["count"] * ncomp).reshape(-1, ncomp)


def _q(v):
    """glTF (x,y,z,w) -> (w,x,y,z)."""
    return np.array([v[3], v[0], v[1], v[2]], dtype=float)


def _qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def _qinv(q):
    """Quaternion inverse: conjugate / |q|^2."""
    return np.array([q[0], -q[1], -q[2], -q[3]]) / np.dot(q, q)


def _ang(a, b):
    d = abs(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))))
    return 2 * math.degrees(math.acos(min(1.0, d)))


def build_rig(doc, binbuf):
    """parent map, local rest quats, world rest quats, per-node children, bone names."""
    nodes = doc["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    local_rot = {}
    names = {}
    for i, n in enumerate(nodes):
        names[i] = n.get("name")
        if "rotation" in n:
            local_rot[i] = _q(n["rotation"])
        else:
            local_rot[i] = np.array([1.0, 0.0, 0.0, 0.0])
    world_rot = {}
    order = sorted(range(len(nodes)), key=lambda i: _depth(parent, i))
    for i in order:
        p = parent.get(i)
        if p is None:
            world_rot[i] = local_rot[i]
        else:
            world_rot[i] = _qmul(world_rot[p], local_rot[i])
    skin_joints = []
    for s in doc.get("skins", []):
        ref = s["joints"]
        if isinstance(ref, int):
            idxs = _acc(doc, binbuf, ref)
        else:
            idxs = np.asarray(ref, dtype=np.int64).reshape(-1, 1)
        skin_joints = [int(j[0]) for j in idxs]
    return {
        "parent": parent,
        "names": names,
        "local_rot": local_rot,
        "world_rot": world_rot,
        "skin_joints": skin_joints,
    }


def _depth(parent, i):
    d = 0
    while i in parent:
        d += 1
        i = parent[i]
    return d


def clip_channels(doc, binbuf):
    names = {i: n.get("name") for i, n in enumerate(doc["nodes"])}
    anim = doc["animations"][0]
    times = None
    quats = {}
    for ch in anim["channels"]:
        nm = names[ch["target"]["node"]]
        if ch["target"]["path"] != "rotation":
            continue
        samp = anim["samplers"][ch["sampler"]]
        t = _acc(doc, binbuf, samp["input"])[:, 0]
        if times is None:
            times = t
        qs = _acc(doc, binbuf, samp["output"])
        quats[nm] = [_q(q) for q in qs]
    return times, quats


def main() -> int:
    mdoc, mbin = _glb(MESHY_ANIM)
    cdoc, cbin = _glb(OUR_CLIP)
    meshy = build_rig(mdoc, mbin)
    clip = build_rig(cdoc, cbin)
    times, quats = clip_channels(cdoc, cbin)

    # map bone name -> node index per rig
    def name_to_node(rig):
        m = {}
        for i, nm in rig["names"].items():
            if nm:
                m[nm] = i
        return m

    meshy_node = name_to_node(meshy)
    clip_node = name_to_node(clip)

    shared = sorted(set(quats) & set(meshy_node) - {"RightWeaponTip", "headfront"})

    # topology order for both rigs (depth asc, then name)
    def topo(rig, nodes):
        return sorted(nodes, key=lambda n: (_depth(rig["parent"], n), rig["names"][n] or ""))

    clip_order = topo(clip, [clip_node[n] for n in shared])
    meshy_order = topo(meshy, [meshy_node[n] for n in shared])
    order_names = [clip["names"][n] for n in clip_order]  # parents before children

    # W_A per key per bone; W_B per key per bone; pose_locals for B.
    n_keys = len(times)
    WA = {nm: [] for nm in shared}
    WB = {nm: [] for nm in shared}
    pose = {nm: [] for nm in shared}
    worst = []
    for k in range(n_keys):
        row_worst = []
        for nm in order_names:
            ca = clip_node[nm]
            cb = meshy_node[nm]
            # world rest rotation of the bone's parent (or identity if none)
            pa = clip["parent"].get(ca)
            pb = meshy["parent"].get(cb)
            qa_parent = clip["world_rot"][pa] if pa is not None else np.array([1.0, 0.0, 0.0, 0.0])
            qb_parent_world = meshy["world_rot"][pb] if pb is not None else np.array([1.0, 0.0, 0.0, 0.0])
            rest_local_a = _qmul(_qinv(qa_parent), clip["world_rot"][ca])
            rest_local_b = _qmul(_qinv(qb_parent_world), meshy["world_rot"][cb])
            # W_A(b,k) = W_A(parent,k) @ clip_q(b,k)
            # (glTF node rotation channels ARE the local rotation — no separate rest
            #  factor; unlike Blender's rest-baked pose channels.)
            if pa is not None and clip["names"][pa] in WA:
                w_a_parent = WA[clip["names"][pa]][k]
            else:
                w_a_parent = qa_parent  # unposed parent -> rest world
            w_a = _qmul(w_a_parent, quats[nm][k])
            WA[nm].append(w_a)
            # solve B pose_local: rest_local_b^-1 @ W_B(parent)^-1 @ W_A(b)
            if pb is not None and meshy["names"][pb] in WB:
                w_b_parent = WB[meshy["names"][pb]][k]
            else:
                w_b_parent = qb_parent_world
            pose_local = _qmul(_qmul(_qinv(rest_local_b), _qinv(w_b_parent)), w_a)
            pose[nm].append(pose_local)
            w_b = _qmul(_qmul(w_b_parent, rest_local_b), pose_local)
            WB[nm].append(w_b)
            assert _ang(w_a, w_b) < 1e-3, (nm, k, _ang(w_a, w_b))
            row_worst.append((_ang(w_a, w_b), nm))
            if k == 0:
                print(f"  k0 {nm:<14} angA2B={_ang(w_a, w_b):7.3f}", flush=True)
        row_worst.sort(reverse=True)
        worst.append({"frame": k, "worst3": [(nm, round(a, 2)) for a, nm in row_worst[:3]]})

    for w in worst:
        print(w)
    ok = all(w["worst3"][0][1] < 0.01 for w in worst)
    print("HOST-SIDE VERIFY:", "PASS" if ok else "FAIL")

    data = {
        "ok": ok,
        "times": [float(t) for t in times],
        "shared": shared,
        "pose_locals": {nm: [[float(v) for v in q] for q in qs] for nm, qs in pose.items()},
        "expected_worlds": {nm: [[float(v) for v in q] for q in qs] for nm, qs in WA.items()},
        "worst_per_frame": worst,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
