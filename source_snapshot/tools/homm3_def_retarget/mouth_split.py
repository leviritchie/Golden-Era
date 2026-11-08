"""mouth_split.py (authenticity pass 2026-10-07, h3_royal_griffin attempt 8) src.glb out.glb : cut the fused beak along the mouth plane (config frame: point C, normal N, inside
BOX) so no triangle straddles upper (Head) and lower (QJaw) beak; each cut point is duplicated at +-EPS across the plane
(upper/lower lip copies, coincident when closed), and a double-sided roof/floor cap fans each lip loop so the open mouth
is not see-through. No existing vertex moves more than SNAP; UV/normals interpolated."""
import sys, json, struct, hashlib, types, numpy as np
glbio = types.ModuleType('glbio'); exec('''import json, struct, numpy as np
CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}; NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}
def load(src):
    data = open(src,"rb").read()
    jl = struct.unpack_from("<I", data, 12)[0]; js = json.loads(data[20:20 + jl]); bo = 20 + jl
    bl = struct.unpack_from("<I", data, bo)[0]; binb = bytearray(data[bo + 8:bo + 8 + bl])
    return js, binb
def acc(js, binb, i):
    a = js["accessors"][i]; bv = js["bufferViews"][a["bufferView"]]; off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    n = a["count"] * NC[a["type"]]
    return np.frombuffer(binb, CT[a["componentType"]], n, off).reshape(a["count"], -1).copy()
''', glbio.__dict__)
src, out = sys.argv[1:3]
# optional (2026-10-08, h3_battle_griffin): --point x,y,z --dir dx,dy,dz --box x0,y0,z0,x1,y1,z1 (config frame);
# the defaults are the royal griffin's mouth plane
_o = {sys.argv[i]: [float(v) for v in sys.argv[i + 1].split(",")] for i in range(3, len(sys.argv) - 1, 2)}
C = np.array(_o.get("--point", [0, -0.468, 0.664])); D = np.array(_o.get("--dir", [0, 0.108, 0.024])); N = np.cross(D, [1, 0, 0]); N = N / np.linalg.norm(N)
if N[2] < 0: N = -N
_b = _o.get("--box", [-0.1, -0.5, 0.6, 0.1, -0.33, 0.70])
BOX = (np.array(_b[:3]), np.array(_b[3:])); EPS = 0.0003; SNAP = 0.0005
js, binb = glbio.load(src); prim = js["meshes"][0]["primitives"][0]
V = glbio.acc(js, binb, prim["attributes"]["POSITION"]); NO = glbio.acc(js, binb, prim["attributes"]["NORMAL"])
UV = glbio.acc(js, binb, prim["attributes"]["TEXCOORD_0"]); T = glbio.acc(js, binb, prim["indices"]).reshape(-1, 3).astype(np.int64)
cfg = lambda X: np.stack([X[..., 0], -X[..., 2], X[..., 1]], -1); gl = lambda P: np.stack([P[..., 0], P[..., 2], -P[..., 1]], -1)
P = cfg(V); inb = ((P >= BOX[0] - 0.01) & (P <= BOX[1] + 0.01)).all(1)
d = (P - C) @ N
sn = inb & (np.abs(d) < SNAP); P[sn] += np.outer(np.where(d[sn] >= 0, SNAP, -SNAP) - d[sn], N); d = (P - C) @ N
fin = inb[T].all(1) & ((P[T][..., 1] <= BOX[1][1]).all(1)); sg = d[T] > 0
cut = fin & sg.any(1) & ~sg.all(1)
print("snapped", int(sn.sum()), "faces cut", int(cut.sum()))
Vl, NOl, UVl = list(P), list(NO), list(UV); newT = [T[~cut]]; ecache = {}; segs = []
def add(p, n, uv):
    Vl.append(p); NOl.append(n); UVl.append(uv); return len(Vl) - 1
def edge_pt(a, b):
    k = (min(a, b), max(a, b))
    if k not in ecache:
        t = d[a] / (d[a] - d[b]); p = P[a] + t * (P[b] - P[a]); n = NO[a] + t * (NO[b] - NO[a]); n /= np.linalg.norm(n) + 1e-12
        uv = UV[a] + t * (UV[b] - UV[a]); p0 = p - ((p - C) @ N) * N
        ecache[k] = (add(p0 + EPS * N, n, uv), add(p0 - EPS * N, n, uv), p0, uv)
    return ecache[k]
for f in T[cut]:
    s = d[f] > 0
    lone = int(np.nonzero(s != (s.sum() == 2))[0][0]) if s.sum() in (1, 2) else None
    a, b, c = f[lone], f[(lone + 1) % 3], f[(lone + 2) % 3]
    eab, eac = edge_pt(a, b), edge_pt(a, c); up_lone = d[a] > 0
    ia = 0 if up_lone else 1; ib = 1 - ia       # lone side copy index, other side copy index
    newT.append(np.array([[a, eab[ia], eac[ia]], [eab[ib], b, c], [eab[ib], c, eac[ib]]]))
    segs.append((eab, eac))
capn = 0
for side, sgn in ((0, 1), (1, -1)):
    pts = [e[2] for s_ in segs for e in s_]; cen = np.mean(pts, 0); uvc = np.mean([e[3] for s_ in segs for e in s_], 0)
    ci = add(cen + sgn * EPS * N, -sgn * N, uvc); cache = {}
    for e1, e2 in segs:
        ids = []
        for e in (e1, e2):
            k = id(e)
            if k not in cache: cache[k] = add(e[2] + sgn * EPS * N, -sgn * N, e[3])
            ids.append(cache[k])
        newT.append(np.array([[ci, ids[0], ids[1]]])); capn += 1   # material is doubleSided
T2 = np.concatenate(newT); V2 = gl(np.array(Vl, np.float32)).astype(np.float32); NO2 = np.array(NOl, np.float32); UV2 = np.array(UVl, np.float32)
print("verts", len(V), "->", len(V2), "faces", len(T), "->", len(T2), "cap faces", capn, "lip segments", len(segs), "max move", float(SNAP if sn.any() else 0))
def put(arr, key, target):
    while len(binb) % 4: binb.append(0)
    js["bufferViews"].append({"buffer": 0, "byteOffset": len(binb), "byteLength": arr.nbytes, "target": target}); binb.extend(arr.tobytes())
    a = js["accessors"][key]; a["bufferView"] = len(js["bufferViews"]) - 1; a["byteOffset"] = 0; a["count"] = int(arr.size // ({"VEC3": 3, "VEC2": 2, "SCALAR": 1}[a["type"]]))
for arr, k in ((V2, "POSITION"), (NO2, "NORMAL"), (UV2, "TEXCOORD_0")): put(arr, prim["attributes"][k], 34962)
js["accessors"][prim["attributes"]["POSITION"]].update(min=V2.min(0).tolist(), max=V2.max(0).tolist())
ia = js["accessors"][prim["indices"]]; ia["componentType"] = 5125; put(T2.astype(np.uint32).ravel(), prim["indices"], 34963)
while len(binb) % 4: binb.append(0)
js["buffers"][0]["byteLength"] = len(binb)
jb = json.dumps(js, separators=(",", ":")).encode()
while len(jb) % 4: jb += b" "
while len(binb) % 4: binb.append(0)
o = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(binb)) + struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(binb), 0x004E4942) + bytes(binb)
open(out, "wb").write(o); print("wrote", out, hashlib.sha256(o).hexdigest())
