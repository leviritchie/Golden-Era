"""maul_surgery.py src.glb out.glb [--haft-end 0.72] [--head-scale 1.7] [--haft-r 0.026] [--mirror-t 0.04]

Mesh surgery for h3_dwarf_battlerager (authenticity pass 2026-10-09, coordinator option B): the DEF battlerager swings
a two-handed maul whose head is about torso size; the Meshy mesh holds a fist-sized mallet (an inline octagonal block
behind the fist, a short wrapped grip and a cap in front of it).

Frame: the old head's centroid Hc and the axis d from it to the grip cap's centroid (the hammer's own line, through the
fist). t is the distance along d from Hc.
- The old block behind the fist stays as the maul's butt / pommel (the DEF idle shows a small block in the hand).
- New haft: a 12-sided cylinder of radius haft-r on the axis from t=0.20 (inside the fist) to t=haft-end, coloured
  from one texel of the existing wrapped grip.
- New head: a copy of the old block (islands 295, 296, the 117 faces behind the fist), its open fist-side rim flattened
  onto the plane t=mirror-t and mirrored across it (two octagonal striking faces, closed), turned so its long axis lies
  perpendicular to the haft in the vertical plane through it, scaled by head-scale and centred on the haft end.
- Every original vertex, face, UV and weight is byte-identical; the new vertices copy the skin of the grip vertex
  nearest the fist centre (the build re-weights anyway; the config's prop regions make the maul rigid on RightHand).
Writes <out>.surgery.json next to the output.
"""
import sys, json, hashlib, argparse
import numpy as np
import struct
from pathlib import Path
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


class glbio:   # minimal GLB reader/writer (single BIN chunk)
    CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
    NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    @staticmethod
    def load(path):
        data = Path(path).read_bytes(); jl = struct.unpack_from("<I", data, 12)[0]
        js = json.loads(data[20:20 + jl]); bo = 20 + jl; bl = struct.unpack_from("<I", data, bo)[0]
        return js, bytearray(data[bo + 8:bo + 8 + bl])

    @staticmethod
    def acc(js, binb, i):
        a = js["accessors"][i]; bv = js["bufferViews"][a["bufferView"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0); n = a["count"] * glbio.NC[a["type"]]
        assert not bv.get("byteStride"), "interleaved buffers are not supported"
        return np.frombuffer(binb, glbio.CT[a["componentType"]], n, off).reshape(a["count"], -1).copy(), off, None

    @staticmethod
    def save(js, binb, out):
        jb = json.dumps(js, separators=(",", ":")).encode()
        while len(jb) % 4: jb += b" "
        o = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(binb)) + struct.pack("<II", len(jb), 0x4E4F534A)
             + jb + struct.pack("<II", len(binb), 0x004E4942) + bytes(binb))
        Path(out).write_bytes(o)

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--haft-end", type=float, default=0.72)
ap.add_argument("--head-scale", type=float, default=1.7)
ap.add_argument("--haft-r", type=float, default=0.026)
ap.add_argument("--mirror-t", type=float, default=0.04)
a = ap.parse_args()

js, b = glbio.load(a.src)
p = js["meshes"][0]["primitives"][0]
attrs = {k: glbio.acc(js, b, i)[0] for k, i in p["attributes"].items()}
F = glbio.acc(js, b, p["indices"])[0].reshape(-1, 3).astype(np.int64)
V = attrs["POSITION"].astype(np.float64); NRM = attrs["NORMAL"].astype(np.float64); UV = attrs["TEXCOORD_0"].astype(np.float64)
n0, f0 = len(V), len(F)
# index islands (faces sharing vertex indices; Meshy UV charts): the island numbers below were read off the smartrigged
# mesh h3_dwarf_battlerager_smartrigged.glb (sha below) and are refused on any other input
_e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]]])
_, lab = connected_components(coo_matrix((np.ones(len(_e)), (_e[:, 0], _e[:, 1])), shape=(n0, n0)), directed=False)
SRC_SHA = "b2bcf0f263ecdca53af2c9221a5211a76cbd8a7978012a462728a635bbf75d8e"
if hashlib.sha256(open(a.src, "rb").read()).hexdigest() != SRC_SHA:
    raise SystemExit(f"{a.src}: not the reviewed smartrigged mesh {SRC_SHA[:12]}; re-derive the island ids first")
CAP = [254, 255, 256, 257, 258, 266, 267, 277, 278, 288]
HEAD = [295, 296]
cap = np.isin(lab, CAP); head = np.isin(lab, HEAD)
C = V[cap].mean(0); Hc = V[head].mean(0)
d = (C - Hc) / np.linalg.norm(C - Hc)
t_all = (V - Hc) @ d
r_all = np.linalg.norm((V - Hc) - np.outer(t_all, d), axis=1)

# ---- new head: mirrored copy of the old block
hf = F[head[F].all(1)]
hv = np.unique(hf)
remap = {int(v): i for i, v in enumerate(hv)}
Hp = V[hv].copy(); Hn = NRM[hv].copy(); Huv = UV[hv].copy(); tH = (Hp - Hc) @ d
tm = a.mirror_t
over = tH > tm
Hp[over] -= np.outer(tH[over] - tm, d)                     # flatten the open rim side onto the plane
tH = (Hp - Hc) @ d
Hf = np.vectorize(remap.get)(hf)
# mirror across the plane t = tm
Mp = Hp - 2 * np.outer(tH - tm, d)
Mn = Hn - 2 * np.outer(Hn @ d, d)
Mf = Hf[:, ::-1] + len(Hp)                                  # flipped winding
on_plane = np.abs(tH - tm) < 1e-9
# weld the mirror's plane rim onto the original's (same positions) so the head is closed
Mf_w = Mf.copy()
for i in np.nonzero(on_plane)[0]:
    Mf_w[Mf == i + len(Hp)] = i
headP = np.concatenate([Hp, Mp]); headN = np.concatenate([Hn, Mn]); headUV = np.concatenate([Huv, Huv])
headF = np.concatenate([Hf, Mf_w])
used = np.unique(headF); keep = np.zeros(len(headP), bool); keep[used] = True
idx = -np.ones(len(headP), np.int64); idx[keep] = np.arange(keep.sum())
headP, headN, headUV, headF = headP[keep], headN[keep], headUV[keep], idx[headF]
# head frame: centre on the axis at tm; long axis d -> a_h (vertical, orthogonal to the haft)
c0 = Hc + tm * d
y = np.array([0.0, 1.0, 0.0]); ah = y - (y @ d) * d; ah /= np.linalg.norm(ah)
e3 = np.cross(d, ah)                                        # third axis
# rotation R with R @ d = ah, R @ ah = -d, R @ e3 = e3 (90 deg about e3)
Rm = np.outer(ah, d) + np.outer(-d, ah) + np.outer(e3, e3)
k = a.head_scale
hc_new = Hc + a.haft_end * d
headP = hc_new + k * ((headP - c0) @ Rm.T)
headN = headN @ Rm.T

# ---- new haft cylinder
S, t0, t1, rr = 12, 0.20, a.haft_end, a.haft_r
rings = np.linspace(t0, t1, max(2, int(round((t1 - t0) / 0.05)) + 1))
ang = np.linspace(0, 2 * np.pi, S, endpoint=False)
u1 = np.cross(d, [0, 1.0, 0]); u1 /= np.linalg.norm(u1); u2 = np.cross(d, u1)
radial = np.outer(np.cos(ang), u1) + np.outer(np.sin(ang), u2)
haftP = np.concatenate([Hc + t * d + rr * radial for t in rings])
haftN = np.tile(radial, (len(rings), 1))
haftF = []
for i in range(len(rings) - 1):
    for j in range(S):
        a0, a1 = i * S + j, i * S + (j + 1) % S
        b0, b1 = a0 + S, a1 + S
        haftF += [[a0, b0, a1], [a1, b0, b1]]
haftF = np.array(haftF)
# texel: the grip wrap vertices (between fist and cap) -> their median UV
wrap = (t_all > 0.215) & (t_all < 0.25) & (r_all < 0.035) & ~cap
wuv = np.median(UV[wrap], 0)
haftUV = np.tile(wuv, (len(haftP), 1))

# orient haft faces outward: check one face normal against radial
def fix_winding(P, Fc, outward):
    n = np.cross(P[Fc[:, 1]] - P[Fc[:, 0]], P[Fc[:, 2]] - P[Fc[:, 0]])
    flip = (n * outward).sum(1) < 0
    Fc[flip] = Fc[flip][:, ::-1]
    return Fc
haftF = fix_winding(haftP, haftF, haftN[haftF[:, 0]])

# ---- assemble
newP = np.concatenate([headP, haftP]); newN = np.concatenate([headN, haftN]); newUV = np.concatenate([headUV, haftUV])
newF = np.concatenate([headF + n0, haftF + n0 + len(headP)])
grip = (t_all > 0.12) & (t_all < 0.2) & ~head
src_v = np.nonzero(grip)[0][np.argmin(r_all[grip])]
nn = len(newP)
out_attr = {}
for kname, arr in attrs.items():
    if kname == "POSITION": add = newP
    elif kname == "NORMAL": add = newN / np.linalg.norm(newN, axis=1, keepdims=True)
    elif kname == "TEXCOORD_0": add = newUV
    else: add = np.tile(arr[src_v], (nn, 1))
    out_attr[kname] = np.concatenate([arr, add.astype(arr.dtype)])
allF = np.concatenate([F, newF])
assert allF.max() < 65536

# body clearance: new head vs original vertices outside the hammer
body = ~(head | cap) & (r_all > 0.08)
from scipy.spatial import cKDTree
dist, _ = cKDTree(V[body]).query(headP)
print(f"axis d {np.round(d,3)} Hc {np.round(Hc,3)}; head verts {len(headP)} faces {len(headF)}; haft verts {len(haftP)} "
      f"faces {len(haftF)}; head centre {np.round(hc_new,3)} extent {np.round(np.ptp(headP,0),3)}; min clearance to body {dist.min():.3f}; "
      f"skin source vertex {src_v}; wrap uv {np.round(wuv,4)} from {wrap.sum()} verts")

# ---- write: append new buffer views
def append(arr, ctype, target=None):
    global b
    while len(b) % 4: b += b"\0"
    off = len(b); raw = arr.tobytes(); b += raw
    bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
    if target: bv["target"] = target
    js["bufferViews"].append(bv); return len(js["bufferViews"]) - 1
for kname, arr in out_attr.items():
    acc = js["accessors"][p["attributes"][kname]]
    acc["bufferView"] = append(np.ascontiguousarray(arr), acc["componentType"], 34962)
    acc["byteOffset"] = 0; acc["count"] = len(arr)
    if kname == "POSITION": acc["min"] = arr.min(0).tolist(); acc["max"] = arr.max(0).tolist()
    elif "min" in acc: acc["min"] = arr.min(0).tolist(); acc["max"] = arr.max(0).tolist()
ia = js["accessors"][p["indices"]]
ia["bufferView"] = append(allF.reshape(-1).astype(np.uint16), 5123, 34963); ia["byteOffset"] = 0; ia["count"] = allF.size
ia.pop("min", None); ia.pop("max", None)
js["buffers"][0]["byteLength"] = len(b)
glbio.save(js, b, a.out)
sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
print("wrote", a.out, sha, "verts", n0, "->", n0 + nn, "faces", f0, "->", len(allF))
json.dump({"axisOriginHc": Hc.tolist(), "axisD": d.tolist(), "haft": [(Hc + t0 * d).tolist(), (Hc + t1 * d).tolist()],
           "haftRadius": rr, "headCentre": hc_new.tolist(), "headAxis": ah.tolist(), "headHalfLength": float(np.abs((headP - hc_new) @ ah).max()),
           "headRadius": float(np.linalg.norm((headP - hc_new) - np.outer((headP - hc_new) @ ah, ah), axis=1).max()),
           "minBodyClearance": float(dist.min()), "outputSha256": sha, "vertsAdded": int(nn), "facesAdded": int(len(newF))},
          open(a.out + ".geom.json", "w"), indent=1)
