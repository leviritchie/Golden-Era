"""Rest-pose sliver surgery: collapse the tiny edges the tear gate keeps tearing (numpy, no Blender).

Why (authenticity pass, 2026-10-07, royal griffin): 84% of the delivered tears sit on edges shorter than 0.01
(the mesh median is 0.021), Meshy slivers in the neck and chest, the shoulders and the wing roots. The corrective
smooth's offsets blow such an edge to many times its rest length, so every new pose there spends gate budget.
Re-weighting does not help (their tears are not skinning tears); collapsing the slivers removes them.

Method: vertices are grouped by rest position (UV-seam copies are one weld group). Candidate edges are group edges
shorter than `maxLen` whose midpoint lies within `near` of one of the listed `targets` (midpoints of torn edges, in
glTF coordinates, e.g. from the gate's output tear list). Shortest first, each collapse merges group b into group a
at the edge midpoint (each b copy is remapped to the a copy nearest in UV) unless a group was already touched this
pass or an adjacent face would flip or collapse (normal dot < `minDot`). Faces left degenerate are dropped and
unused vertices are compacted. Passes repeat until nothing collapses.

Usage: python sliver_collapse.py <in.glb> <out.glb> <targets.json> [--max-len 0.01] [--near 0.006] [--min-dot 0.3]
targets.json: [[x, y, z], ...] or [{"mid": [x, y, z]}, ...]
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from wing_lengthen import read_glb, write_glb


def face_normals(P, F):
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out"); ap.add_argument("targets")
    ap.add_argument("--max-len", type=float, default=0.01)
    ap.add_argument("--near", type=float, default=0.006)
    ap.add_argument("--min-dot", type=float, default=0.3)
    a = ap.parse_args()
    T = json.load(open(a.targets))
    T = np.array([t["mid"] if isinstance(t, dict) else t for t in T], float)
    js, binb = read_glb(a.inp)
    pr = js["meshes"][0]["primitives"][0]; at = pr["attributes"]

    def get(i, n, dt=np.float32):
        acc = js["accessors"][i]; bv = js["bufferViews"][acc["bufferView"]]
        return np.frombuffer(binb, dt, acc["count"] * n, bv.get("byteOffset", 0) + acc.get("byteOffset", 0)).reshape(-1, n).copy()

    P = get(at["POSITION"], 3).astype(float); N = get(at["NORMAL"], 3); UV = get(at["TEXCOORD_0"], 2)
    ia = js["accessors"][pr["indices"]]
    F = get(pr["indices"], 1, {5123: np.uint16, 5125: np.uint32}[ia["componentType"]]).reshape(-1, 3).astype(np.int64)
    nv0, nf0 = len(P), len(F)
    collapsed = []
    for _pass in range(6):
        _, grp = np.unique(np.round(P, 6), axis=0, return_inverse=True); grp = grp.ravel()
        members = {}
        for v, gi in enumerate(grp):
            members.setdefault(gi, []).append(v)
        E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        GE = np.unique(np.sort(grp[E], 1), axis=0); GE = GE[GE[:, 0] != GE[:, 1]]
        rep = {gi: m[0] for gi, m in members.items()}
        A = np.array([P[rep[g]] for g in GE[:, 0]]); B = np.array([P[rep[g]] for g in GE[:, 1]])
        L = np.linalg.norm(A - B, axis=1); mid = (A + B) / 2
        dT = np.min(np.linalg.norm(mid[:, None, :] - T[None, :, :], axis=2), axis=1) if len(T) else np.full(len(GE), 9.0)
        cand = np.where((L < a.max_len) & (dT < a.near))[0]
        cand = cand[np.argsort(L[cand])]
        vf = {}
        for fi, f in enumerate(F):
            for v in f:
                vf.setdefault(grp[v], set()).add(fi)
        touched = set(); done = 0; Fn0 = face_normals(P, F)
        for c in cand:
            ga, gb = GE[c]
            if ga in touched or gb in touched:
                continue
            m = (P[rep[ga]] + P[rep[gb]]) / 2
            faces = sorted(vf.get(ga, set()) | vf.get(gb, set()))
            P2 = P.copy()
            for v in members[ga] + members[gb]:
                P2[v] = m
            Ff = F[faces]; keep = np.array([len({grp[x] for x in f}) == 3 and not ({grp[x] for x in f} >= {ga, gb}) for f in Ff])
            if keep.any():
                n2 = face_normals(P2, Ff[keep]); dots = (n2 * Fn0[np.array(faces)[keep]]).sum(1)
                if dots.min() < a.min_dot:
                    continue
            # remap each b copy to the a copy nearest in UV
            amap = {}
            for vb in members[gb]:
                amap[vb] = min(members[ga], key=lambda va: float(np.sum((UV[va] - UV[vb]) ** 2)))
            P = P2
            for fi in faces:
                F[fi] = [amap.get(int(x), int(x)) for x in F[fi]]
            touched |= {ga, gb}; done += 1
            collapsed.append({"mid": m.round(4).tolist(), "len": round(float(L[c]), 5)})
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
        ar = np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
        F = F[ar > 1e-12]                                  # seam copies merged onto one point: zero-area faces
        if not done:
            break
    used = np.unique(F); remap = -np.ones(len(P), np.int64); remap[used] = np.arange(len(used))
    P, N, UV, F = P[used].astype(np.float32), N[used], UV[used], remap[F].astype(np.uint32)
    for key, arr in ((at["POSITION"], P), (at["NORMAL"], N), (at["TEXCOORD_0"], UV), (pr["indices"], F.ravel())):
        off = len(binb) + (-len(binb) % 4)
        binb.extend(b"\0" * (off - len(binb))); binb.extend(np.ascontiguousarray(arr).tobytes())
        js["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        acc = js["accessors"][key]; acc["bufferView"] = len(js["bufferViews"]) - 1; acc.pop("byteOffset", None)
        acc["count"] = int(arr.size if arr.ndim == 1 else arr.shape[0])
        if key == pr["indices"]:
            acc["componentType"] = 5125; acc.pop("min", None); acc.pop("max", None)
        elif key == at["POSITION"] or "min" in acc:
            acc["min"] = arr.min(0).tolist(); acc["max"] = arr.max(0).tolist()
    js["buffers"][0]["byteLength"] = len(binb)
    write_glb(a.out, js, binb)
    rep = {"schema": "homm3_def_retarget.sliver_collapse.v1", "input": a.inp,
           "inputSha256": hashlib.sha256(Path(a.inp).read_bytes()).hexdigest(), "targets": a.targets,
           "maxLen": a.max_len, "near": a.near, "minDot": a.min_dot, "collapsed": len(collapsed),
           "vertices": [nv0, int(len(P))], "faces": [nf0, int(len(F))],
           "maxMove": round(max((c["len"] / 2 for c in collapsed), default=0.0), 5), "edges": collapsed,
           "outputSha256": hashlib.sha256(Path(a.out).read_bytes()).hexdigest()}
    Path(a.out).with_suffix(".surgery.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps({k: v for k, v in rep.items() if k != "edges"}))


if __name__ == "__main__":
    main()
