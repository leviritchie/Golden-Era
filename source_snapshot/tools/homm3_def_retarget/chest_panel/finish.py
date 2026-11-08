"""finish.py <src_smartrigged.glb> <p1.npz> <p3.npz> <out.glb> [--reason "..."]

Stage 4 of the chest-panel surgery: write the source GLB with the freed arm block, the rebuilt torso front and the
arm caps. Original vertices keep every attribute; split copies copy their source vertex; every vertex of a new face is
a new vertex (boundary positions duplicated so the panel's UV never interpolates into the old texture) that copies
skin data from the nearest vertex of its own part and takes one robe/sleeve texel per connected fill (nearest visible
original vertex to the fill's centroid). Normals of new vertices are area-weighted from the new faces, oriented
outward (panel: toward +Z; caps: away from the arm block centroid).
Writes <out.glb> + <out>.surgery.json."""
import sys, json, hashlib, collections
import numpy as np
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "homm3_def_retarget_delivery"))
from stride_match_glb import Glb as G2
from scipy.spatial import cKDTree
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

a = sys.argv[1:]
src, p1, p3, out = Path(a[0]), np.load(a[1]), np.load(a[2]), Path(a[3])
reason = a[a.index("--reason") + 1] if "--reason" in a else ""
raw = src.read_bytes(); g = G2(raw); js = g.json
pr = js["meshes"][0]["primitives"][0]; at = pr["attributes"]


def rd(ai):
    acc = js["accessors"][ai]; bv = js["bufferViews"][acc["bufferView"]]
    w = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    dt = np.dtype({5126: "<f4", 5123: "<u2", 5121: "u1", 5125: "<u4"}[acc["componentType"]])
    st = bv.get("byteStride", dt.itemsize * w); off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if st == dt.itemsize * w:
        return np.frombuffer(g.bin, dtype=dt, count=acc["count"] * w, offset=off).reshape(acc["count"], w).copy()
    return np.stack([np.frombuffer(g.bin, dtype=dt, count=w, offset=off + i * st) for i in range(acc["count"])])


A = {k: rd(v) for k, v in at.items()}
N0 = int(p1["N0"]); V = p1["V"]; src_of = p1["src_of"]
base = {k: A[k][src_of].copy() for k in A}
# fair.py relaxes original rim vertices (arm side); carry those moves onto every source vertex of the same weld id in
# that part, so the caps stay welded to the rim they were filled against
Wid = p3["W"]; relaxed = 0
for tag, partF in (("body", p1["bodyF"]), ("arm", p1["armF"])):
    wid = p3[tag + "_wid"]; Pp = p3[tag + "_pos"]
    pos_of = {int(w): Pp[i] for i, w in enumerate(wid) if w >= 0}
    for v in np.unique(partF.ravel()):
        q = pos_of.get(int(Wid[v]))
        if q is not None and np.linalg.norm(q - V[v]) > 1e-5:
            V[v] = q; relaxed += 1
print("rim vertices carried from fair.py", relaxed)
base["POSITION"] = V.astype(A["POSITION"].dtype)
bodyF, armF = p1["bodyF"], p1["armF"]
add = collections.defaultdict(list)
nbase = len(V)


def push(si, pos, uv, nrm):
    for k in A:
        v = A[k][si].copy()
        if k == "POSITION": v = np.asarray(pos, A[k].dtype)
        elif k == "TEXCOORD_0": v = np.asarray(uv, A[k].dtype)
        elif k == "NORMAL": v = np.asarray(nrm, A[k].dtype)
        add[k].append(v)
    return nbase + len(add["POSITION"]) - 1


import io
from PIL import Image
_mat = js["materials"][pr.get("material", 0)]
_img = js["images"][js["textures"][_mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]]
_bv = js["bufferViews"][_img["bufferView"]]
TEX = np.asarray(Image.open(io.BytesIO(bytes(g.bin[_bv.get("byteOffset", 0):_bv.get("byteOffset", 0) + _bv["byteLength"]]))).convert("RGB"), float)


def colour(uv):
    uv = np.asarray(uv, float) % 1.0
    h, w = TEX.shape[:2]
    return TEX[np.minimum((uv[:, 1] * h).astype(int), h - 1), np.minimum((uv[:, 0] * w).astype(int), w - 1)]


newF, rep_fills = {}, []
# original non-arm surface, densely sampled, for the panel's texture transfer (faces within --transfer of it)
TR = float(a[a.index("--transfer") + 1]) if "--transfer" in a else 0.015
oF = p1["oldF"]; aidx = set(map(int, p1["armIdx"])) | set(map(int, p1["droppedArm"]))
keepo = np.array([i not in aidx for i in range(len(oF))])
# armIdx indexes F (same face order as oldF)
OT = A["POSITION"][oF].astype(float); OUV = A["TEXCOORD_0"][oF].astype(float)
bc = np.array([(i / 4, j / 4) for i in range(5) for j in range(5 - i)])
smp = (OT[keepo][:, None, 0] * (1 - bc.sum(1))[None, :, None] + OT[keepo][:, None, 1] * bc[None, :, 0, None]
       + OT[keepo][:, None, 2] * bc[None, :, 1, None]).reshape(-1, 3)
s_face = np.repeat(np.nonzero(keepo)[0], len(bc)); s_tree = cKDTree(smp)
armc = V[np.unique(armF.ravel())].mean(0)
for tag, partF in (("body", bodyF), ("arm", armF)):
    P = p3[tag + "_pos"]; F = p3[tag + "_faces"]; isnew = p3[tag + "_new"]
    Fn = F[isnew]
    pv = np.unique(partF.ravel()); tree = cKDTree(V[pv])
    # connected fills
    n = len(P)
    E = np.concatenate([Fn[:, [0, 1]], Fn[:, [1, 2]], Fn[:, [2, 0]]])
    G = sp.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    nc, lab = connected_components(G, directed=False)
    flab = lab[Fn[:, 0]]
    out_faces = []
    for c in np.unique(flab):
        Fc = Fn[flab == c]
        vs = np.unique(Fc.ravel())
        cen = P[vs].mean(0)
        # texel: among the part's 200 vertices nearest the fill centroid (off the cut rim), the one whose base colour is
        # nearest the part's median colour (the robe/sleeve cloth, never a trim or cuff band)
        rim = set(map(tuple, np.round(P[vs], 6)))
        _, cand = tree.query(cen, k=min(200, len(pv)))
        cand = [int(pv[i]) for i in np.atleast_1d(cand) if tuple(np.round(V[pv[i]], 6)) not in rim] or [int(pv[np.atleast_1d(cand)[0]])]
        med = np.median(colour(base["TEXCOORD_0"][pv]), 0)
        cc = colour(base["TEXCOORD_0"][cand])
        texv = cand[int(np.argmin(np.linalg.norm(cc - med, axis=1)))]
        uv = base["TEXCOORD_0"][texv]
        # orientation
        T = P[Fc]; fn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        # orientation: the fill must traverse each rim edge it shares with the part opposite to the adjacent original
        # face (a consistently wound closed surface); vote over the rim. The old centroid rules are only a fallback:
        # a cap's centroid nearly coincides with its arm block's, so "away from the arm centroid" turned caps
        # inside-out (seen through once the sleeve moved)
        kq = lambda X: [tuple(r) for r in np.round(X, 5)]
        pk = kq(V); ok_ = kq(P)
        dE = collections.Counter()
        for f in partF:
            for i in range(3):
                dE[(pk[f[i]], pk[f[(i + 1) % 3]])] += 1
        same = opp = 0
        for f in Fc:
            for i in range(3):
                a_, b_ = ok_[f[i]], ok_[f[(i + 1) % 3]]
                same += dE.get((a_, b_), 0); opp += dE.get((b_, a_), 0)
        if same + opp >= 3:
            flip = same > opp
        elif tag == "body":
            flip = fn[:, 2].sum() < 0
        else:
            flip = (fn * (T.mean(1) - armc)).sum() < 0
        if flip: Fc = Fc[:, ::-1]; fn = -fn
        vn = np.zeros((n, 3)); np.add.at(vn, Fc.ravel(), np.repeat(fn, 3, axis=0))
        vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
        _, near = tree.query(P[vs])
        srcv = {int(v): (int(pv[ni]) if int(pv[ni]) < N0 else int(src_of[pv[ni]])) for v, ni in zip(vs, near)}
        m = {}
        Fout = []
        ntr = 0
        for f in Fc:
            if tag == "body":
                cen_f = P[f].mean(0)
                dd, si = s_tree.query(cen_f)
                if dd < TR:
                    # texture transfer: affine UVs from the nearest original (non-arm) triangle, own corners per face
                    t = OT[s_face[si]]; tu = OUV[s_face[si]]
                    e1, e2 = t[1] - t[0], t[2] - t[0]; G_ = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
                    if abs(np.linalg.det(G_)) > 1e-14:
                        rows = []
                        for v in f:
                            q = P[v] - t[0]; l1, l2 = np.linalg.solve(G_, [q @ e1, q @ e2])
                            uvv = tu[0] + l1 * (tu[1] - tu[0]) + l2 * (tu[2] - tu[0])
                            rows.append(push(srcv[int(v)], P[v], uvv, vn[v]))
                        Fout.append(rows); ntr += 1
                        continue
            Fout.append([m.setdefault(int(v), push(srcv[int(v)], P[v], uv, vn[v])) if int(v) not in m else m[int(v)] for v in f])
        out_faces.append(np.array(Fout, np.int64).reshape(-1, 3))
        rep_fills.append({"part": tag, "rimVote": [int(same), int(opp)], "faces": int(len(Fc)), "vertices": int(len(vs)), "texel": texv, "texelRGB": colour(uv[None])[0].round().tolist(),
                          "center": np.round(cen, 3).tolist(), "flipped": bool(flip), "textureTransferFaces": ntr})
    newF[tag] = np.concatenate(out_faces) if out_faces else np.zeros((0, 3), int)

F2 = np.concatenate([bodyF, armF, newF["body"], newF["arm"]]).astype(np.int64)
kind = np.repeat([0, 1, 2, 3], [len(bodyF), len(armF), len(newF["body"]), len(newF["arm"])])
# --recolor LUM (default 8): the look stage rasterises UV triangles, so a fill whose vertices all share one texel has no
# UV area and comes out black; and Meshy painted the fused, occluded sleeve/chest surfaces black, which the freed
# arms now show. Give each such face (every fill face without a texture transfer, and every arm-block or chest-band
# body face whose texel is darker than LUM) its own corners on one robe-cloth UV triangle (an original face whose three
# corner texels are nearest the part's median cloth colour)
RL = float(a[a.index("--recolor") + 1]) if "--recolor" in a else 8.0
nrec = collections.Counter()
if RL > 0:
    UVall = np.concatenate([base["TEXCOORD_0"], np.array(add["TEXCOORD_0"], dtype=A["TEXCOORD_0"].dtype).reshape(-1, 2)]).astype(float)
    Pall0 = np.concatenate([base["POSITION"], np.array(add["POSITION"], dtype=A["POSITION"].dtype).reshape(-1, 3)]).astype(float)
    def attr(v):
        return {k: (base[k][v] if v < nbase else np.asarray(add[k][v - nbase])) for k in A}
    def cloth_tri(partF):
        med = np.median(colour(base["TEXCOORD_0"][np.unique(partF.ravel())]), 0)
        U = base["TEXCOORD_0"][partF].astype(float)
        cd = np.linalg.norm(colour(U.reshape(-1, 2)).reshape(-1, 3, 3) - med, axis=2).max(1)
        e1, e2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]; ar = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
        ok = (cd < 8) & (ar > np.percentile(ar, 40))
        return U[np.nonzero(ok)[0][np.argmin(cd[ok])]] if ok.any() else U[np.argmin(cd)]
    tri = {0: cloth_tri(bodyF), 1: cloth_tri(armF)}
    lumf = colour(UVall[F2].mean(1)).mean(1)
    e1, e2 = UVall[F2[:, 1]] - UVall[F2[:, 0]], UVall[F2[:, 2]] - UVall[F2[:, 0]]; uva = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
    cy = Pall0[F2].mean(1)[:, 1]; band = (cy > 0.95) & (cy < 1.40)
    sel = ((kind >= 2) & (uva < 1e-12)) | ((kind == 1) & (lumf < RL)) | ((kind == 0) & band & (lumf < RL))
    for fi in np.nonzero(sel)[0]:
        t = tri[1 if kind[fi] in (1, 3) else 0]
        row = []
        for j, v in enumerate(F2[fi]):
            at_ = attr(int(v))
            for k in A:
                add[k].append(np.asarray(t[j], A[k].dtype) if k == "TEXCOORD_0" else at_[k].copy())
            row.append(nbase + len(add["POSITION"]) - 1)
        F2[fi] = row; nrec[int(kind[fi])] += 1
print("recoloured faces (body, arm, panel, cap):", [nrec[k] for k in range(4)])
# --merge: collapse mesh edges shorter than this (default 2 mm, a tenth of the median edge) and drop the faces that
# degenerate. The fills and the relaxed rim leave near-coincident vertices whose corrective-shape offsets differ: a 1 mm
# edge then "stretches" 25x in the tear gate.
# --collapse "x,y,z;x,y,z": also collapse the edge whose midpoint lies within 3 mm of each point (rest position, glTF
# axes): an edge above the merge threshold whose ends carry the same weights yet still tear under the corrective-shape
# offsets (pose.py --diag --where names it), where a larger global merge would decimate the mesh.
# Both work on WELDED vertices (rest position to 5 decimals, bake_cs's key): UV/normal seam copies of a vertex are
# separate indices, so collapsing by index picks a different end on each side of a seam and cracks the surface open.
# Each cluster snaps to the position of its lowest-index vertex (originals are lower: they stay put); every copy keeps
# its own UV, and a face is dropped when two corners land in one cluster.
MERGE = float(a[a.index("--merge") + 1]) if "--merge" in a else 0.002
COLL = [[float(c) for c in q.split(",")] for q in a[a.index("--collapse") + 1].split(";")] if "--collapse" in a else []
Pall = np.concatenate([base["POSITION"], np.array(add["POSITION"], dtype=A["POSITION"].dtype).reshape(-1, 3)]).astype(float)
_, wid = np.unique(np.round(Pall, 5), axis=0, return_inverse=True); wid = wid.ravel()
Ee = np.unique(np.sort(np.concatenate([F2[:, [0, 1]], F2[:, [1, 2]], F2[:, [2, 0]]]), 1), axis=0)
Es = Ee[np.linalg.norm(Pall[Ee[:, 0]] - Pall[Ee[:, 1]], axis=1) < MERGE]
par = np.arange(wid.max() + 1)
def root(x):
    while par[x] != x: par[x] = par[par[x]]; x = par[x]
    return x
def union(x, y):
    rx, ry = root(x), root(y)
    if rx != ry: par[max(rx, ry)] = min(rx, ry)
for u, v in Es: union(wid[u], wid[v])
collapsed = []
if COLL:
    from scipy.spatial import cKDTree
    dq, iq = cKDTree(Pall[Ee].mean(1)).query(np.array(COLL), 1)
    for q, dd, ii in zip(COLL, dq, iq):
        if dd > 0.003: raise SystemExit(f"finish.py --collapse: no edge midpoint within 3 mm of {q} (nearest {dd:.4f})")
        u, v = Ee[ii].tolist(); union(wid[u], wid[v])
        collapsed.append({"at": q, "length": round(float(np.linalg.norm(Pall[u] - Pall[v])), 4)})
# snapping a cluster to its lowest-index vertex can shorten a neighbouring edge below the threshold: repeat until none is left
passes = 0
while True:
    cl = np.array([root(x) for x in range(len(par))])[wid]          # cluster per vertex
    first = np.full(cl.max() + 1, len(Pall)); np.minimum.at(first, cl, np.arange(len(Pall)))
    Pnew = Pall[first[cl]]
    Ec = Ee[cl[Ee[:, 0]] != cl[Ee[:, 1]]]
    Eh = Ec[np.linalg.norm(Pnew[Ec[:, 0]] - Pnew[Ec[:, 1]], axis=1) < MERGE]
    if not len(Eh) or passes >= 20: break
    for u, v in Eh: union(wid[u], wid[v])
    passes += 1
moved = int((np.linalg.norm(Pnew - Pall, axis=1) > 0).sum())
base["POSITION"] = Pnew[:nbase].astype(base["POSITION"].dtype)
add["POSITION"] = [r.astype(A["POSITION"].dtype) for r in Pnew[nbase:]]
C = cl[F2]
keepf = (C[:, 0] != C[:, 1]) & (C[:, 1] != C[:, 2]) & (C[:, 2] != C[:, 0])
print("merged edges <", MERGE, ":", len(Es), "re-merge passes", passes, "+ collapsed", collapsed, "vertices snapped", moved, "faces dropped", int((~keepf).sum()))
F2, kind = F2[keepf], kind[keepf]
# --cap-loops MIN: cap every open boundary loop of at least MIN welded edges with a double-sided fan from its centroid.
# The rebuilt chest band's top rim is not joined to the mantle above it: a shoulder-height ring hidden under the mantle
# at rest that opens a see-through slit at the armpit once the shoulders protract (h3_monk, h3_zealot). The cap is
# inside the torso; each cap face gets its own corners on the robe-cloth UV triangle (as --recolor does), so it bakes
# as cloth, and it counts as a panel face (the rest-occlusion fill mask covers it).
CAPMIN = int(a[a.index("--cap-loops") + 1]) if "--cap-loops" in a else 0
capped = []
if CAPMIN:
    Pc = np.concatenate([base["POSITION"], np.array(add["POSITION"], dtype=A["POSITION"].dtype).reshape(-1, 3)]).astype(float)
    Cf = cl[F2]
    Eo = np.sort(np.concatenate([Cf[:, [0, 1]], Cf[:, [1, 2]], Cf[:, [2, 0]]]), 1)
    ue, uc = np.unique(Eo, axis=0, return_counts=True); op = ue[uc == 1]
    lpar = {}
    def lroot(x):
        lpar.setdefault(x, x)
        while lpar[x] != x: lpar[x] = lpar[lpar[x]]; x = lpar[x]
        return x
    for u_, v_ in op: lpar[lroot(int(u_))] = lroot(int(v_))
    comps = collections.defaultdict(list)
    for u_, v_ in op: comps[lroot(int(u_))].append((int(u_), int(v_)))
    if RL <= 0: raise SystemExit("finish.py --cap-loops needs --recolor (the robe-cloth UV triangle)")
    for es in comps.values():
        if len(es) < CAPMIN: continue
        cids = np.unique(np.array(es)); rv = first[cids]          # one representative vertex per cluster
        Q = Pc[rv]; c0 = Q.mean(0); _, _, vt = np.linalg.svd(Q - c0)
        ang = np.arctan2((Q - c0) @ vt[1], (Q - c0) @ vt[0]); ring = rv[np.argsort(ang)]
        # walk the boundary edges (Euler circuit; a loop that touches itself has degree-4 vertices) so every boundary
        # edge gets its own fan triangle; the angle order above is the fallback for an odd-degree component
        nb_ = collections.defaultdict(list)
        for ei, (u_, v_) in enumerate(es): nb_[u_].append((v_, ei)); nb_[v_].append((u_, ei))
        if all(len(x) % 2 == 0 for x in nb_.values()):
            usedE = set(); st_ = [es[0][0]]; walk = []
            while st_:
                x = st_[-1]
                while nb_[x] and nb_[x][-1][1] in usedE: nb_[x].pop()
                if nb_[x]:
                    y, ei = nb_[x].pop(); usedE.add(ei); st_.append(y)
                else:
                    walk.append(st_.pop())
            ring = first[np.array(walk[:-1])]
        at_c = {k: (base[k][ring[0]] if ring[0] < nbase else np.asarray(add[k][ring[0] - nbase])) for k in A}
        t = tri[0]
        for j in range(len(ring)):
            for corners in ((ring[j], ring[(j + 1) % len(ring)], -1), (ring[(j + 1) % len(ring)], ring[j], -1)):
                row = []
                for q, v in enumerate(corners):
                    src_ = at_c if v < 0 else {k: (base[k][v] if v < nbase else np.asarray(add[k][v - nbase])) for k in A}
                    for k in A:
                        if k == "TEXCOORD_0": add[k].append(np.asarray(t[q], A[k].dtype))
                        elif k == "POSITION": add[k].append(np.asarray(c0 if v < 0 else Pc[v], A[k].dtype))
                        else: add[k].append(np.asarray(src_[k]).copy())
                    row.append(nbase + len(add["POSITION"]) - 1)
                F2 = np.vstack([F2, np.array(row)[None]]); kind = np.append(kind, 2)
        capped.append({"edges": len(es), "ringVertices": int(len(ring)), "center": np.round(c0, 3).tolist()})
    print("capped loops", capped)
order = np.argsort(kind, kind="stable"); F2, kind = F2[order], kind[order]
nb, na_, nbp = int((kind == 0).sum()), int((kind == 1).sum()), int((kind == 2).sum())
newF = {"body": F2[kind == 2], "arm": F2[kind == 3]}


def append(arr, ctype, typ, normalized=False, target=None):
    while len(g.bin) % 4: g.bin.append(0)
    off = len(g.bin); g.bin += arr.tobytes()
    bvd = {"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes}
    if target: bvd["target"] = target
    js["bufferViews"].append(bvd)
    acc = {"bufferView": len(js["bufferViews"]) - 1, "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
    if normalized: acc["normalized"] = True
    if typ == "VEC3" and ctype == 5126: acc["min"] = arr.min(0).tolist(); acc["max"] = arr.max(0).tolist()
    js["accessors"].append(acc); return len(js["accessors"]) - 1


# compact: drop vertices no face uses (the hidden torso front, eroded slivers)
used = np.zeros(nbase + len(add["POSITION"]), bool); used[F2.ravel()] = True
remap = -np.ones(len(used), np.int64); remap[used] = np.arange(used.sum())
for k, ai in list(at.items()):
    arr = np.concatenate([base[k], np.array(add[k], dtype=A[k].dtype).reshape(-1, A[k].shape[1])])[used]
    o = js["accessors"][ai]
    at[k] = append(np.ascontiguousarray(arr), o["componentType"], o["type"], o.get("normalized", False), 34962)
F3 = remap[F2]
pr["indices"] = append(np.ascontiguousarray(F3.astype("<u4").ravel()), 5125, "SCALAR", target=34963)
data = g.to_bytes()
out.write_bytes(data)
rep = {"schema": "homm3_mesh_surgery.chest_panel.v1",
       "input": str(src).replace("\\", "/").split("olden era playtest tweak/")[-1],
       "inputSha256": hashlib.sha256(raw).hexdigest(),
       "output": str(out).replace("\\", "/").split("olden era playtest tweak/")[-1],
       "outputSha256": hashlib.sha256(data).hexdigest(),
       "tool": "tools/homm3_def_retarget/chest_panel/{prep.py, blender_panel.py (Blender 5.2.2 bmesh), fair.py, finish.py}",
       "prep": json.loads(Path(a[1] + ".json").read_text()) if Path(a[1] + ".json").exists() else {},
       "result": {"faces": [int(len(p1["oldF"])), int(len(F3))], "vertices": [N0, int(used.sum())],
                  "bodyFaces": nb, "armFaces": na_, "panelFaces": nbp, "armCapFaces": int(len(newF["arm"])),
                  "fills": rep_fills, "mergedShortEdges": int(len(Es)), "mergePasses": passes, "mergeThreshold": MERGE,
                  **({"collapsedEdges": collapsed} if collapsed else {}), **({"cappedLoops": capped} if capped else {}),
                  "recolouredFaces": {"body": nrec[0], "arm": nrec[1], "panel": nrec[2], "cap": nrec[3], "lum": RL}},
       "armFaceIdx": list(range(nb, nb + na_)) + list(range(nb + na_ + nbp, len(F3))),
       "panelFaceIdx": list(range(nb + na_, nb + na_ + nbp)),
       "reason": reason}
Path(str(out) + ".surgery.json").write_text(json.dumps(rep, indent=1))
print(json.dumps({k: v for k, v in rep.items() if k not in ("armFaceIdx", "panelFaceIdx", "prep")})[:1500])
