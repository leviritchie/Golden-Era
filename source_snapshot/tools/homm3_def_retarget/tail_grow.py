"""Rest-pose tail surgery: grow a lion tail out of a stub (numpy, no Blender).

Why (authenticity pass, 2026-10-07, royal griffin): the Meshy royal griffin has only a 0.13-long tail stub hanging
from the rump, while the DEF's lion tail hangs to the ground, curls out behind and ends in a tuft; the rig's
4-bone tail chain spans air below the stub, so every tail key moves almost nothing. Scaling the stub
(tail_lengthen-style) cannot make a tail, so a tube is added.

Method: a tube of `sides`-vertex rings follows a Catmull-Rom curve through `path` (Blender coordinates x, -z, y of
the glTF; the first point sits inside the stub so the joint is hidden), radius tapering `r0` -> `r1`, with a tuft
bulge (`tuft` radius over the last `tuftLen` fraction) closed by a cone to a tip vertex. Its UVs are borrowed from
the stub (each ring vertex takes the UV of the stub vertex nearest in angle around the stub axis, in the stub's
lower half), so the tail carries the stub's own tawny texture. Normals are the tube's outward normals. The tube is
appended to the single primitive (new buffer views for positions, normals, UVs and indices); the original
vertices, UVs and faces are untouched.

Usage: python tail_grow.py <spec.json> <in.glb> <out.glb>
spec: {"path": [[x,y,z],...], "r0": .02, "r1": .013, "tuft": .026, "tuftLen": .14, "sides": 10, "step": .01,
       "stubBox": [[lo],[hi]]}
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from wing_lengthen import read_glb, write_glb, in_box


def catmull(P, step):
    P = np.asarray(P, float)
    Q = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        n = max(2, int(np.ceil(np.linalg.norm(p2 - p1) / step)))
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(Q[-2])
    return np.array(out)


def main():
    spec, inp, outp = sys.argv[1:4]
    S = json.load(open(spec))
    js, binb = read_glb(inp)
    pr = js["meshes"][0]["primitives"][0]
    at = pr["attributes"]

    def get(i, n, dt=np.float32):
        a = js["accessors"][i]; bv = js["bufferViews"][a["bufferView"]]
        return np.frombuffer(binb, dt, a["count"] * n, bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(-1, n).copy()

    P, N, UV = get(at["POSITION"], 3), get(at["NORMAL"], 3), get(at["TEXCOORD_0"], 2)
    ia = js["accessors"][pr["indices"]]
    I = get(pr["indices"], 1, {5123: np.uint16, 5125: np.uint32}[ia["componentType"]]).ravel().astype(np.uint32)
    B = np.stack([P[:, 0], -P[:, 2], P[:, 1]], 1).astype(float)

    C = catmull(S["path"], S.get("step", 0.01))
    T = np.gradient(C, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]; f = arc / arc[-1]
    r = S["r0"] + (S["r1"] - S["r0"]) * f
    tl = S.get("tuftLen", 0.14)
    u = np.clip((f - (1 - tl)) / tl, 0, 1)
    r = np.maximum(r, S["tuft"] * np.sin(np.pi * u * 0.9))                              # swell into the tuft
    r[-1] = S["tuft"] * 0.55
    k = S.get("sides", 10)
    # parallel-transport frames, seeded with the body lateral axis
    nrm = np.zeros_like(C); ref = np.array([1.0, 0, 0])
    for i in range(len(C)):
        v = ref - (ref @ T[i]) * T[i]; v /= np.linalg.norm(v); nrm[i] = v; ref = v
    bin_ = np.cross(T, nrm)
    th = np.linspace(0, 2 * np.pi, k, endpoint=False)
    ring_dir = np.cos(th)[None, :, None] * nrm[:, None, :] + np.sin(th)[None, :, None] * bin_[:, None, :]
    V = C[:, None, :] + r[:, None, None] * ring_dir
    Vn = ring_dir.copy()
    tip = C[-1] + T[-1] * S["tuft"] * 0.9
    newB = np.vstack([V.reshape(-1, 3), tip]); newN = np.vstack([Vn.reshape(-1, 3), T[-1]])

    # UVs from the stub's lower half, nearest in angle about the stub axis
    sb = in_box(B, S["stubBox"]); stub = np.nonzero(sb)[0]
    if len(stub) < 8:
        raise SystemExit(f"stubBox holds {len(stub)} vertices")
    sc = B[stub].mean(0)
    low = stub[B[stub, 2] <= np.median(B[stub, 2])]
    d = B[low] - sc
    ang_s = np.arctan2(d @ bin_[0], d @ nrm[0])
    uv_ring = UV[low[np.argmin(np.abs(np.angle(np.exp(1j * (th[:, None] - ang_s[None, :])))), 1)]]
    newUV = np.vstack([np.tile(uv_ring, (len(C), 1)), uv_ring.mean(0)])

    n0 = len(P); F = []
    for i in range(len(C) - 1):
        for j in range(k):
            a, b2 = n0 + i * k + j, n0 + i * k + (j + 1) % k
            c, d2 = a + k, b2 + k
            F += [[a, c, b2], [b2, c, d2]]
    tipi = n0 + len(C) * k
    for j in range(k):
        F.append([n0 + (len(C) - 1) * k + j, tipi, n0 + (len(C) - 1) * k + (j + 1) % k])
    F = np.array(F, np.uint32)
    # orient outward
    Ball = np.vstack([B, newB])
    e = np.cross(Ball[F[:, 1]] - Ball[F[:, 0]], Ball[F[:, 2]] - Ball[F[:, 0]])
    cen = Ball[F].mean(1); out_dir = cen - np.vstack([C, tip])[np.clip((F[:, 0] - n0) // k, 0, len(C))]
    flip = (e * out_dir).sum(1) < 0
    F[flip] = F[flip][:, [0, 2, 1]]

    toG = lambda X: np.stack([X[:, 0], X[:, 2], -X[:, 1]], 1).astype(np.float32)
    P2 = np.vstack([P, toG(newB)]); N2 = np.vstack([N, toG(newN)]); UV2 = np.vstack([UV, newUV]).astype(np.float32)
    I2 = np.r_[I, F.ravel()].astype(np.uint32)
    for key, arr in ((at["POSITION"], P2), (at["NORMAL"], N2), (at["TEXCOORD_0"], UV2), (pr["indices"], I2)):
        off = len(binb) + (-len(binb) % 4)
        binb.extend(b"\0" * (off - len(binb))); binb.extend(arr.tobytes())
        js["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        a = js["accessors"][key]; a["bufferView"] = len(js["bufferViews"]) - 1; a.pop("byteOffset", None)
        a["count"] = int(arr.size if arr.ndim == 1 else arr.shape[0])
        if key == pr["indices"]:
            a["componentType"] = 5125; a.pop("min", None); a.pop("max", None)
        elif "min" in a or key == at["POSITION"]:
            a["min"] = arr.min(0).tolist(); a["max"] = arr.max(0).tolist()
    js["buffers"][0]["byteLength"] = len(binb)
    write_glb(outp, js, binb)
    rep = {"schema": "homm3_def_retarget.tail_grow.v1", "input": inp,
           "inputSha256": hashlib.sha256(Path(inp).read_bytes()).hexdigest(), "spec": S,
           "addedVertices": int(len(newB)), "addedFaces": int(len(F)), "tubeLength": round(float(arc[-1]), 4),
           "stubVertices": int(len(stub)), "boxNeeded": [newB.min(0).round(3).tolist(), newB.max(0).round(3).tolist()],
           "outputSha256": hashlib.sha256(Path(outp).read_bytes()).hexdigest()}
    Path(outp).with_suffix(".surgery.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps({k: v for k, v in rep.items() if k != "spec"}))


if __name__ == "__main__":
    main()
