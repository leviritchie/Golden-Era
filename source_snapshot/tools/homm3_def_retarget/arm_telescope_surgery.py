"""arm_telescope_surgery.py <unit> src.glb out.glb [--axis-c 0.04,0.95] [--face-y -0.765] [--step 0.40] [--sleeves 3]

Mesh surgery for hota_factory_automaton (authenticity pass 2026-10-11, user-approved): the DEF attack telescopes a
segmented arm with the gripper on its end about one body length out of the front drum; the Meshy mesh has the gripper
welded onto the drum's front plate and nothing to extend.
Also hota_factory_sentinel_automaton (its upgrade, same DEF g12 arm; 2026-10-11 coordinator-relayed approval):
--face-y -0.76 --axis-c 0.04,0.92 --claw-zmin 0.6 --uv 0.153622,0.502351.

All geometry is in Blender coordinates (x, -z, y of glTF); the unit faces -Y. The arm axis runs along -Y through
(axis-c x, z).
- Gripper: every vertex in front of the plate (y < face-y) within --claw-r of the axis is cut free: faces with all
  three corners in the set form the gripper island, small kept fragments it orphans go with it, and seam vertices the
  plate still uses are duplicated. The gripper copy is nudged 2 mm forward so the island stays separate by position
  (the build's wholeIslands regions weld UV seams by position).
- Sleeves: n nested open tubes (16 sides; radii r0 - k*dr, outermost first), each `length` long, parked inside the
  drum behind the plate (front ends inside the plate's thickness, so nothing shows at rest). Each tube gets an
  annular front cap down to the next tube's radius (the innermost a full disc), so an extended joint shows a collar,
  not the inside of a pipe. Fully extended (sleeve k out by (k+1)*step, the gripper by n*step) consecutive tubes
  overlap by length - step. Colour: one texel of the gripper's dark grey metal.
- Every original vertex, face and UV outside the gripper is byte-identical.
Writes <out stem>.surgery.json next to the output and prints the rigidParts block for the unit config.
"""
import sys, json, hashlib, argparse, struct
import numpy as np
from pathlib import Path
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
SRC_SHA = {"hota_factory_automaton": "74057616834946572d9eb9588f05b30839c77717af42f187bba74bbf28ab9944",
           "hota_factory_sentinel_automaton": "3f35409acf73ad0221b747ba268f93492838ee075267580b3d6c292f0bdb2a87"}


def load(path):
    data = Path(path).read_bytes(); jl = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + jl]); bo = 20 + jl; bl = struct.unpack_from("<I", data, bo)[0]
    return js, bytearray(data[bo + 8:bo + 8 + bl])


def acc(js, b, i):
    x = js["accessors"][i]; bv = js["bufferViews"][x["bufferView"]]
    assert not bv.get("byteStride"), "interleaved buffers are not supported"
    off = bv.get("byteOffset", 0) + x.get("byteOffset", 0)
    return np.frombuffer(b, CT[x["componentType"]], x["count"] * NC[x["type"]], off).reshape(x["count"], -1).copy()


def save(js, b, out):
    jb = json.dumps(js, separators=(",", ":")).encode()
    while len(jb) % 4: jb += b" "
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(b)) + struct.pack("<II", len(jb), 0x4E4F534A)
                          + jb + struct.pack("<II", len(b), 0x004E4942) + bytes(b))

ap = argparse.ArgumentParser()
ap.add_argument("unit"); ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--axis-c", default="0.04,0.95")
ap.add_argument("--face-y", type=float, default=-0.765)
ap.add_argument("--claw-r", type=float, default=0.4)
ap.add_argument("--claw-zmin", type=float, default=0.65)
ap.add_argument("--sleeves", type=int, default=3)
ap.add_argument("--r0", type=float, default=0.13); ap.add_argument("--dr", type=float, default=0.015)
ap.add_argument("--length", type=float, default=0.46); ap.add_argument("--step", type=float, default=0.40)
ap.add_argument("--front-in", type=float, default=0.012, help="outermost tube front sits this far behind face-y")
ap.add_argument("--uv", default="0.643697,0.736693", help="texel for the tubes (gripper dark grey metal)")
ap.add_argument("--reason", default="")
a = ap.parse_args()

if a.unit in SRC_SHA and hashlib.sha256(open(a.src, "rb").read()).hexdigest() != SRC_SHA[a.unit]:
    raise SystemExit(f"{a.src}: not the reviewed source mesh {SRC_SHA[a.unit][:12]}; re-check the cut first")
js, b = load(a.src)
p = js["meshes"][0]["primitives"][0]
attrs = {k: acc(js, b, i) for k, i in p["attributes"].items()}
F = acc(js, b, p["indices"]).reshape(-1, 3).astype(np.int64)
G = attrs["POSITION"].astype(np.float64)
Bl = np.c_[G[:, 0], -G[:, 2], G[:, 1]]
n0, f0 = len(Bl), len(F)
cx, cz = [float(x) for x in a.axis_c.split(",")]
lat = np.hypot(Bl[:, 0] - cx, Bl[:, 2] - cz)

# ---- gripper cut
cut = (Bl[:, 1] < a.face_y) & (lat < a.claw_r) & (Bl[:, 2] > a.claw_zmin)
mf = cut[F].all(1)
_, inv = np.unique(np.round(Bl, 4), axis=0, return_inverse=True); inv = inv.ravel(); nw = inv.max() + 1
W = inv[F[~mf]]
_, wl = connected_components(coo_matrix((np.ones(W.size), (W.ravel(), np.roll(W, 1, 1).ravel())), (nw, nw)), directed=False)
fl = wl[W[:, 0]]; cnt = np.bincount(fl); kept_idx = np.flatnonzero(~mf); orphan = []
tree = cKDTree(Bl[cut])
for c in np.flatnonzero((cnt > 0) & (cnt < 40)):
    fs = kept_idx[fl == c]
    if tree.query(Bl[F[fs]].reshape(-1, 3))[0].min() < 0.03:
        orphan += fs.tolist()
mf[orphan] = True
kept_use = np.zeros(n0, bool); kept_use[F[~mf].ravel()] = True
gv = np.unique(F[mf]); dup = gv[kept_use[gv]]
remap = np.arange(n0); remap[dup] = n0 + np.arange(len(dup))
Fg = remap[F[mf]]
newBl = np.concatenate([Bl, Bl[dup]])
moved = np.unique(Fg)
newBl[moved] += np.array([0.0, -0.002, 0.0])
ext = {k: np.concatenate([v, v[dup]]) for k, v in attrs.items()}
grip_lo = float(newBl[moved][:, 1].min())

# ---- sleeves
S = 16; ang = np.linspace(0, 2 * np.pi, S, endpoint=False)
rad = np.c_[np.cos(ang), np.zeros(S), np.sin(ang)]
uv = np.array([float(x) for x in a.uv.split(",")])
P_, N_, Fn = [], [], []


def add(P, N, Fc):
    base = len(newBl) + sum(len(x) for x in P_)
    P_.append(np.asarray(P, float)); N_.append(np.asarray(N, float)); Fn.append(np.asarray(Fc) + base)


def ring(y, rr):
    return np.c_[cx + rr * np.cos(ang), np.full(S, y), cz + rr * np.sin(ang)]


def band(n):
    out = []
    for j in range(n):
        a0, a1 = j, (j + 1) % n
        out += [[a0, a1, a0 + n], [a1, a1 + n, a0 + n]]
    return np.array(out)


def orient(P, Fc, want):
    nrm = np.cross(P[Fc[:, 1]] - P[Fc[:, 0]], P[Fc[:, 2]] - P[Fc[:, 0]])
    flip = (nrm * want).sum(1) < 0; Fc[flip] = Fc[flip][:, ::-1]
    return Fc


parts = []
for k in range(a.sleeves):
    r = a.r0 - k * a.dr
    rn = a.r0 - (k + 1) * a.dr if k + 1 < a.sleeves else 0.0
    y0 = a.face_y + a.front_in - k * 0.006          # inner tubes sit a little further forward
    y1 = y0 + a.length
    Pt = np.concatenate([ring(y0, r), ring(y1, r)]); Nt = np.concatenate([rad, rad]); Ft = band(S)
    add(Pt, Nt, orient(Pt, Ft, Nt[Ft[:, 0]]))
    fwd = np.tile([0.0, -1.0, 0.0], (S + 1, 1))
    if rn > 0:
        Pc = np.concatenate([ring(y0, r), ring(y0, rn)]); Fc = band(S); Nc = np.tile([0.0, -1.0, 0.0], (2 * S, 1))
    else:
        Pc = np.concatenate([ring(y0, r), [[cx, y0, cz]]]); Fc = np.array([[j, (j + 1) % S, S] for j in range(S)]); Nc = fwd
    add(Pc, Nc, orient(Pc, Fc, np.array([0.0, -1.0, 0.0])))
    parts.append({"name": f"ArmSleeve{k + 1}", "radius": r, "y": [y0, y1]})

addP = np.concatenate(P_); addN = np.concatenate(N_); addF = np.concatenate(Fn)
na = len(addP)
Pall = np.concatenate([newBl, addP])
out_attr = {}
for k, arr in ext.items():
    if k == "POSITION":
        v = np.c_[Pall[:, 0], Pall[:, 2], -Pall[:, 1]]
    elif k == "NORMAL":
        v = np.concatenate([arr, np.c_[addN[:, 0], addN[:, 2], -addN[:, 1]]])
    elif k.startswith("TEXCOORD"):
        v = np.concatenate([arr, np.tile(uv, (na, 1))])
    else:
        v = np.concatenate([arr, np.tile(arr[gv[0]], (na, 1))])
    out_attr[k] = v.astype(arr.dtype)
allF = np.concatenate([F[~mf], Fg, addF])


def append(arr, target=None):
    global b
    while len(b) % 4:
        b += b"\0"
    off = len(b); raw = np.ascontiguousarray(arr).tobytes(); b += raw
    bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
    if target:
        bv["target"] = target
    js["bufferViews"].append(bv); return len(js["bufferViews"]) - 1


for k, arr in out_attr.items():
    x = js["accessors"][p["attributes"][k]]
    x["bufferView"] = append(arr, 34962); x["byteOffset"] = 0; x["count"] = len(arr)
    if "min" in x or k == "POSITION":
        x["min"] = arr.min(0).tolist(); x["max"] = arr.max(0).tolist()
ia = js["accessors"][p["indices"]]
it = np.uint16 if len(out_attr["POSITION"]) < 65536 else np.uint32
ia["bufferView"] = append(allF.reshape(-1).astype(it), 34963); ia["byteOffset"] = 0; ia["count"] = allF.size
ia["componentType"] = 5123 if it is np.uint16 else 5125; ia.pop("min", None); ia.pop("max", None)
js["buffers"][0]["byteLength"] = len(b)
save(js, b, a.out)
sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()

# rigidParts for idle_cycle (wholeIslands): outermost first, each parented to the one before; the gripper last
rp, par = [], "Head"
for q in parts:
    rp.append({"name": q["name"], "center": [cx, round(q["y"][0], 4), cz], "axis": [0, -1, 0],
               "radius": round(q["radius"] + 0.004, 4), "hMin": round(-a.length - 0.01, 3), "hMax": 0.01,
               "parent": par, "wholeIslands": 0.9})
    par = q["name"]
gc = a.face_y - 0.002
rp.append({"name": "ArmGripper", "center": [cx, round(gc, 4), cz], "axis": [0, -1, 0], "radius": a.claw_r,
           "hMin": -0.001, "hMax": round(gc - grip_lo + 0.05, 3), "parent": par, "wholeIslands": 0.9})


def rel(q):
    q = Path(q).resolve()
    return q.relative_to(ROOT).as_posix() if q.is_relative_to(ROOT) else str(q)


rec = {"schema": "homm3_mesh_surgery.arm_telescope.v1", "input": rel(a.src),
       "inputSha256": hashlib.sha256(open(a.src, "rb").read()).hexdigest(), "output": rel(a.out), "outputSha256": sha,
       "tool": "tools/homm3_def_retarget/arm_telescope_surgery.py " + " ".join(sys.argv[1:2] + sys.argv[4:]),
       "result": {"gripperFaces": int(mf.sum()), "gripperVerts": int(len(moved)), "orphanFaces": len(orphan),
                  "seamDuplicates": int(len(dup)), "gripperFrontY": grip_lo, "sleeves": parts,
                  "sleeveVerts": int(na), "sleeveFaces": int(len(addF)), "step": a.step,
                  "verts": [n0, len(out_attr["POSITION"])], "faces": [f0, len(allF)], "rigidParts": rp},
       "reason": a.reason}
json.dump(rec, open(str(Path(a.out).with_suffix("")) + ".surgery.json", "w"), indent=1)
print(f"gripper faces {mf.sum()} (orphans {len(orphan)}), verts {len(moved)}, seam dups {len(dup)}, front y {grip_lo:.3f}; "
      f"sleeves {[(q['name'], round(q['radius'], 3), [round(y, 3) for y in q['y']]) for q in parts]}")
print("wrote", a.out, sha[:12], "verts", n0, "->", len(out_attr["POSITION"]), "faces", f0, "->", len(allF))
print(json.dumps(rp))
