"""prep.py <src_smartrigged.glb> <weights_ref.glb> <out.npz> [--th 0.6] [--nudge 6e-4]

Stage 1 of the chest-panel surgery (robed casters with forearms fused across the chest: h3_zealot, h3_monk).
- arm faces: mean ForeArm+Hand share of the corners (from <weights_ref>, matched by position) > --th
- the arm block is cut free of the TORSO only: an arm-side corner gets its own vertex copy (index >= N0, nudged toward
  the arm block) only when a torso face (not upper-arm/shoulder dominated) also uses that position; the elbow seam to
  the upper-arm sleeve stays welded
- torso faces of the front that the folded arms hide at rest (a +Z ray from the face centroid hits the arm block) are
  removed: blender_panel.py rebuilds the torso front there instead of patching around fused fragments
Writes <out.npz> (+ .json) for blender_panel.py and finish.py."""
import sys, json
import numpy as np
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "homm3_glb_patch"))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "homm3_def_retarget_delivery"))
import patch_glb as P
from stride_match_glb import Glb as G2
from scipy.spatial import cKDTree
sys.path.insert(0, str(Path(__file__).resolve().parent))
from raylib import ray_z

a = sys.argv[1:]
src, ref, out = Path(a[0]), Path(a[1]), Path(a[2])
th = float(a[a.index("--th") + 1]) if "--th" in a else 0.6
nudge = float(a[a.index("--nudge") + 1]) if "--nudge" in a else 6e-4
g = G2(src.read_bytes()); js = g.json
pr = js["meshes"][0]["primitives"][0]; at = pr["attributes"]


def rd(ai):
    acc = js["accessors"][ai]; bv = js["bufferViews"][acc["bufferView"]]
    w = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    dt = np.dtype({5126: "<f4", 5123: "<u2", 5121: "u1", 5125: "<u4"}[acc["componentType"]])
    st = bv.get("byteStride", dt.itemsize * w); off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if st == dt.itemsize * w:
        return np.frombuffer(g.bin, dtype=dt, count=acc["count"] * w, offset=off).reshape(acc["count"], w).copy()
    return np.stack([np.frombuffer(g.bin, dtype=dt, count=w, offset=off + i * st) for i in range(acc["count"])])


V0 = rd(at["POSITION"]).astype(np.float64)
I = rd(pr["indices"]).reshape(-1, 3).astype(np.int64)
N0 = len(V0)
gr = P.Glb(ref.read_bytes()); b = P.Body(gr); names = list(b.jnames)
D = np.zeros((len(b.V), len(names)))
np.add.at(D, (np.repeat(np.arange(len(b.V)), b.J.shape[1]), b.J.ravel()), b.W.ravel())
D /= D.sum(1, keepdims=True)
d, nn = cKDTree(b.V).query(V0)
assert d.max() < 1e-4, d.max()
Dv = D[nn]
JP = np.array([np.linalg.inv(m)[:3, 3] for m in b.ibm])
er = float(a[a.index("--elbow") + 1]) if "--elbow" in a else 0.07
rep0 = {n: np.round(JP[i], 3).tolist() for i, n in enumerate(names) if 'Arm' in n}

# --upper: the upper-arm sleeve is freed too (fused down the robe's sides): the block is Arm+ForeArm+Hand and the
# weld is kept at the shoulder (Arm joint) instead of the elbow
UPPER = "--upper" in a
ARMB = ("Arm", "ForeArm", "Hand") if UPPER else ("ForeArm", "Hand")
KEEPJ = "Arm" if UPPER else "ForeArm"
rep0["upper"] = UPPER
limb = [names.index(s + n) for s in ("Left", "Right") for n in ("Shoulder", "Arm", "ForeArm", "Hand")]
torsoface = Dv[:, limb].sum(1)[I].mean(1) < 0.5

key = np.unique(np.round(V0, 6), axis=0, return_inverse=True)[1].ravel()
F = I.copy(); armface = np.zeros(len(I), bool); side_of = np.zeros(len(I), np.int8)
rep = {"threshold": th, "nudge": nudge, "sides": {}}
newpos, src_of = [], list(range(N0))
for si, side in enumerate(("Left", "Right")):
    fw = Dv[:, [names.index(side + n) for n in ARMB]].sum(1)
    fa = (fw[I].mean(1) > th) & ~armface
    armface |= fa; side_of[fa] = si + 1
for si, side in enumerate(("Left", "Right")):
    fa = side_of == si + 1
    used_arm = np.zeros(N0, bool); used_arm[I[fa].ravel()] = True
    # body faces that keep the weld: the upper-arm sleeve around the elbow (centroid within --elbow of ForeArm joint)
    ej = JP[names.index(side + KEEPJ)]
    elbow = np.linalg.norm(V0[I].mean(1) - ej, axis=1) < er
    tb = np.zeros(key.max() + 1, bool); tb[key[I[~armface & ~elbow].ravel()]] = True
    armc = V0[I[fa].ravel()].mean(0)
    remap = {}
    for v in np.nonzero(used_arm & tb[key])[0]:
        dn = armc - V0[v]; dn /= np.linalg.norm(dn) + 1e-12
        remap[v] = N0 + len(newpos); newpos.append(V0[v] + nudge * dn); src_of.append(int(v))
    for fi in np.nonzero(fa)[0]:
        F[fi] = [remap.get(int(x), int(x)) for x in F[fi]]
    rep["sides"][side] = {"armFaces": int(fa.sum()), "splitVertices": len(remap)}
# the two forearms are also cut free of EACH OTHER (hands tucked into the opposite sleeve): a position used by both
# sides' arm faces gets a Right-side copy, nudged toward the right arm block; each side is capped separately, so
# the arms part without a skin bridge stretching between them
if "--no-lr-split" not in a:
    Vc = np.concatenate([V0, np.array(newpos).reshape(-1, 3)])
    kc = np.unique(np.round(Vc, 6), axis=0, return_inverse=True)[1].ravel()
    usedL = np.zeros(kc.max() + 1, bool); usedL[kc[F[side_of == 1].ravel()]] = True
    armcR = Vc[F[side_of == 2].ravel()].mean(0)
    remap = {}
    for fi in np.nonzero(side_of == 2)[0]:
        row = []
        for x in F[fi]:
            x = int(x)
            if usedL[kc[x]]:
                if x not in remap:
                    dn = armcR - Vc[x]; dn /= np.linalg.norm(dn) + 1e-12
                    remap[x] = N0 + len(newpos); newpos.append(Vc[x] + nudge * dn); src_of.append(int(src_of[x]))
                x = remap[x]
            row.append(x)
        F[fi] = row
    rep["leftRightSplitVertices"] = len(remap)
V = np.concatenate([V0, np.array(newpos).reshape(-1, 3)])
src_of = np.array(src_of)

armF = F[armface]
AV = V[np.unique(armF.ravel())]
ylo, yhi = AV[:, 1].min() - 0.03, AV[:, 1].max() + 0.03
C = V[F].mean(1)
Nz = np.cross(V[F][:, 1] - V[F][:, 0], V[F][:, 2] - V[F][:, 0])[:, 2]
EJ = JP[[names.index('Left' + KEEPJ), names.index('Right' + KEEPJ)]]
notelbow = np.linalg.norm(C[:, None, :] - EJ[None], axis=2).min(1) >= er
cand = ~armface & notelbow & (Nz > 0) & (C[:, 2] > -0.03) & (C[:, 1] > ylo) & (C[:, 1] < yhi) & (np.abs(C[:, 0]) < np.abs(AV[:, 0]).max())
hz = np.full(len(F), np.nan)
ci = np.nonzero(cand)[0]
hz[ci] = ray_z(C[ci] - np.array([0, 0, 1e-3]), V[armF])
hidden = cand & ~np.isnan(hz)
# also any face with a hidden corner (centroid rays miss thin slivers along the arm's silhouette)
cv = np.unique(F[ci].ravel())
hv = np.zeros(len(V), bool); hv[cv] = ~np.isnan(ray_z(V[cv] - np.array([0, 0, 1e-3]), V[armF]))
hidden |= cand & (hv[F].sum(1) >= 2)
# erode spikes the cut leaves (faces with 2+ open edges over the final welded mesh): body faces of the hidden front
# band, and any arm face (slivers that were buried in the chest and would show once the arm moves)
kw = np.unique(np.round(V, 6), axis=0, return_inverse=True)[1].ravel()
dropped_arm = np.zeros(len(F), bool)
rep["eroded"] = []
for _ in range(int(a[a.index("--erode") + 1]) if "--erode" in a else 6):
    kf = np.nonzero(~hidden & ~dropped_arm)[0]
    E = np.sort(np.stack([kw[F[kf][:, [0, 1]]], kw[F[kf][:, [1, 2]]], kw[F[kf][:, [2, 0]]]], 1), axis=2)
    ek = E[..., 0].astype(np.int64) * (kw.max() + 1) + E[..., 1]
    u, cnt = np.unique(ek.ravel(), return_counts=True)
    openE = np.isin(ek, u[cnt == 1]).sum(1)
    spb = kf[(openE >= 2) & cand[kf]]; spa = kf[(openE >= 2) & armface[kf]]
    if not len(spb) and not len(spa): break
    hidden[spb] = True; dropped_arm[spa] = True
    rep["eroded"].append([int(len(spb)), int(len(spa))])
armface_kept = armface & ~dropped_arm
armF = F[armface_kept]
keep = ~armface & ~hidden
rep["hiddenTorsoFaces"] = int(hidden.sum())
np.savez(out, torso=torsoface, hidden=hidden, armface=armface, F=F, V=V, src_of=src_of, N0=N0, bodyF=F[keep], bodyIdx=np.nonzero(keep)[0], armF=armF,
         armIdx=np.nonzero(armface_kept)[0], armSide=side_of[armface_kept], droppedArm=np.nonzero(dropped_arm)[0], oldF=I, band=np.array([ylo, yhi]))
rep["band"] = [float(ylo), float(yhi)]
Path(str(out) + ".json").write_text(json.dumps(rep, indent=1))
print(json.dumps(rep))
