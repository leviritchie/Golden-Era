"""sword_draw_surgery.py <unit> src.glb out.glb [--grip-t -0.58] [--dir 0,-0.7,-0.7] [--grip-at 0.6]

Prop surgery for the Cove sea witch line (authenticity pass 2026-10-11, user-approved): the Meshy mesh wears the
cutlass sheathed on the left hip (config prop sheathedSword, rigid on Hips), but the DEF AttackFront draws it overhead
and slashes. This cuts the sword out of the welded mesh and re-seats it in the right hand so the patch lane can
animate the draw-and-slash; the config then makes it rigid on RightHand.

All geometry is in Blender coordinates (x, -z, y of glTF).
- Sword axis: PCA of the sparse blade vertices within 0.04 of the config's sheathedSword segment (t 0.15..0.62 along
  it); t is measured along that fitted axis from the blade vertices' mean, tip side positive.
- Cut set: vertices with t in [t-lo, t-hi] within r-core of the axis (grip, guard, blade) plus the blade's wide edge
  vertices (t in [edge-lo, t-hi], within r-edge). Faces with all three vertices in the set move; vertices of the set
  that kept faces still use are duplicated, so the body keeps a copy where it touched the sword (no holes, no
  stretched faces).
- Re-seat: a rigid transform takes the grip point (axis at grip-t) to RightHand + grip-at * (RightHand_End -
  RightHand) and the axis to --dir (blade lowered forward along the side), the blade's flat facing sideways (+-x).
- Positions and normals of the moved faces are transformed; UVs and every other attribute are copied unchanged.
Writes <out stem>.surgery.json next to the output and prints the new prop segment for the unit config.
"""
import sys, json, hashlib, argparse, struct
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
SRC_SHA = {"hota_cove_sea_witch": "319a4b3d1f834456f339ecd76215482a1e331683ead9b8033a8f4fab166411b3",
           "hota_cove_sorceress": "efa600932028a1648641012b932cfcd979b966a84df556486def7bc30b738b80"}


def load(path):
    data = Path(path).read_bytes(); jl = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + jl]); bo = 20 + jl; bl = struct.unpack_from("<I", data, bo)[0]
    return js, bytearray(data[bo + 8:bo + 8 + bl])


def acc(js, b, i):
    a = js["accessors"][i]; bv = js["bufferViews"][a["bufferView"]]
    assert not bv.get("byteStride"), "interleaved buffers are not supported"
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(b, CT[a["componentType"]], a["count"] * NC[a["type"]], off).reshape(a["count"], -1).copy()


def save(js, b, out):
    jb = json.dumps(js, separators=(",", ":")).encode()
    while len(jb) % 4: jb += b" "
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(b)) + struct.pack("<II", len(jb), 0x4E4F534A)
                          + jb + struct.pack("<II", len(b), 0x004E4942) + bytes(b))


ap = argparse.ArgumentParser()
ap.add_argument("unit"); ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--grip-t", type=float, default=-0.58)
ap.add_argument("--t-lo", type=float, default=-0.68); ap.add_argument("--t-hi", type=float, default=0.07)
ap.add_argument("--r-core", type=float, default=0.045)
ap.add_argument("--edge-lo", type=float, default=-0.5); ap.add_argument("--r-edge", type=float, default=0.07)
ap.add_argument("--hilt", default="", help="extra capsule x0,y0,z0,x1,y1,z1,r for a hilt that bends off the blade axis")
ap.add_argument("--grip-src", default="", help="source grip point x,y,z (overrides --grip-t; for a hilt off the blade axis)")
ap.add_argument("--orphan-max", type=int, default=40)
ap.add_argument("--dir", default="0,-0.7,-0.7")
ap.add_argument("--grip-at", type=float, default=0.6)
ap.add_argument("--reason", default="")
a = ap.parse_args()

if a.unit in SRC_SHA and hashlib.sha256(open(a.src, "rb").read()).hexdigest() != SRC_SHA[a.unit]:
    raise SystemExit(f"{a.src}: not the reviewed source mesh {SRC_SHA[a.unit][:12]}; re-check the cut first")
cfg = json.load(open(ROOT / "tools/homm3_def_retarget/units" / f"{a.unit}.json"))
J = {k: np.array(v, float) for k, v in cfg["joints"].items()}
seg = next(p for p in cfg["props"] if p["name"] == "sheathedSword")["segments"][0]

js, b = load(a.src)
p = js["meshes"][0]["primitives"][0]
attrs = {k: acc(js, b, i) for k, i in p["attributes"].items()}
F = acc(js, b, p["indices"]).reshape(-1, 3).astype(np.int64)
G = attrs["POSITION"].astype(np.float64)
Bl = np.c_[G[:, 0], -G[:, 2], G[:, 1]]
n0, f0 = len(Bl), len(F)


def tdist(P, o, d):
    r = P - o; t = r @ d; return t, np.linalg.norm(r - np.outer(t, d), axis=1)


a0, a1 = np.array(seg[0], float), np.array(seg[1], float); d0 = (a1 - a0) / np.linalg.norm(a1 - a0)
t, dd = tdist(Bl, a0, d0)
blade = (t > 0.15) & (t < 0.62) & (dd < 0.04)
o = Bl[blade].mean(0); _, s, vt = np.linalg.svd(Bl[blade] - o)
d = vt[0] * np.sign(vt[0] @ d0); w = vt[1] - (vt[1] @ d) * d; w /= np.linalg.norm(w)
t, dd = tdist(Bl, o, d)
cut = ((t > a.t_lo) & (t < a.t_hi) & (dd < a.r_core)) | ((t > a.edge_lo) & (t < a.t_hi) & (dd < a.r_edge))
if a.hilt:
    h = np.array([float(x) for x in a.hilt.split(",")]); h0, h1, hr = h[:3], h[3:6], h[6]
    hd = h1 - h0; hl = np.linalg.norm(hd); hd /= hl; th, dh = tdist(Bl, h0, hd)
    cut |= (th > -hr) & (th < hl + hr) & (dh < hr)
mf = cut[F].all(1)                                   # faces that move
# fragments the cut orphans (small position-welded islands of the kept faces next to the cut) go with the sword
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
_, inv = np.unique(np.round(Bl, 4), axis=0, return_inverse=True); inv = inv.ravel(); nw = inv.max() + 1
W = inv[F[~mf]]
_, wl = connected_components(coo_matrix((np.ones(W.size), (W.ravel(), np.roll(W, 1, 1).ravel())), (nw, nw)), directed=False)
fl = wl[W[:, 0]]; cnt = np.bincount(fl); cutc = Bl[cut]
from scipy.spatial import cKDTree as _T
kept_idx = np.flatnonzero(~mf); orphan = []
for c in np.flatnonzero((cnt > 0) & (cnt < a.orphan_max)):
    fs = kept_idx[fl == c]
    if _T(cutc).query(Bl[F[fs]].reshape(-1, 3))[0].min() < 0.03: orphan += fs.tolist()
mf[orphan] = True
kept_use = np.zeros(n0, bool); kept_use[F[~mf].ravel()] = True
sv = np.unique(F[mf])                                # sword vertices
dup = sv[kept_use[sv]]                               # shared with the body: duplicate
remap = np.arange(n0)
remap[dup] = n0 + np.arange(len(dup))                # moved faces use the new copies of shared vertices
Fs = remap[F[mf]]

# rigid transform: source frame (d, w, n) at grip point -> target frame
D = np.array([float(x) for x in a.dir.split(",")]); D /= np.linalg.norm(D)
Wt = np.array([0.0, -D[2], D[1]]); Wt -= (Wt @ D) * D; Wt /= np.linalg.norm(Wt)  # edge forward/up in the sagittal plane
Rs = np.c_[d, w, np.cross(d, w)]; Rt = np.c_[D, Wt, np.cross(D, Wt)]
R = Rt @ Rs.T
gs = np.array([float(x) for x in a.grip_src.split(",")]) if a.grip_src else o + a.grip_t * d
gt = J["RightHand"] + a.grip_at * (J["RightHand_End"] - J["RightHand"])

newBl = Bl.copy()
newBl = np.concatenate([newBl, Bl[dup]])
moved = np.unique(Fs)
newBl[moved] = gt + (newBl[moved] - gs) @ R.T
# moved-only vertices of the original index range (not shared) keep their index and move in place (done above)
out_attr = {}
for k, arr in attrs.items():
    ext = np.concatenate([arr, arr[dup]])
    if k == "POSITION":
        ext = np.c_[newBl[:, 0], newBl[:, 2], -newBl[:, 1]].astype(arr.dtype)
    elif k == "NORMAL":
        nb = np.c_[ext[:, 0], -ext[:, 2], ext[:, 1]].astype(np.float64)
        nb[moved] = nb[moved] @ R.T
        ext = np.c_[nb[:, 0], nb[:, 2], -nb[:, 1]].astype(arr.dtype)
    out_attr[k] = ext
allF = np.concatenate([F[~mf], Fs])

tip = gt + (o + a.t_hi * d - gs) @ R.T; pommel = gt + (o + a.t_lo * d - gs) @ R.T
from scipy.spatial import cKDTree
body_v = np.unique(F[~mf]); dist, _ = cKDTree(Bl[body_v]).query(newBl[moved])
print(f"orphan fragments moved: {len(orphan)} faces"); print(f"axis o {o.round(3)} d {d.round(3)} spread {s.round(3)}; cut verts {cut.sum()}, moved faces {mf.sum()}, "
      f"moved verts {len(moved)} ({len(dup)} duplicated at the seam); grip {gs.round(3)} -> {gt.round(3)}; "
      f"new segment pommel {pommel.round(3)} tip {tip.round(3)}; min clearance moved->body {dist.min():.3f} "
      f"(<0.02: {(dist < 0.02).sum()} verts)")


def append(arr, target=None):
    global b
    while len(b) % 4: b += b"\0"
    off = len(b); raw = np.ascontiguousarray(arr).tobytes(); b += raw
    bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
    if target: bv["target"] = target
    js["bufferViews"].append(bv); return len(js["bufferViews"]) - 1


for k, arr in out_attr.items():
    ac = js["accessors"][p["attributes"][k]]
    ac["bufferView"] = append(arr, 34962); ac["byteOffset"] = 0; ac["count"] = len(arr)
    if "min" in ac or k == "POSITION": ac["min"] = arr.min(0).tolist(); ac["max"] = arr.max(0).tolist()
ia = js["accessors"][p["indices"]]
it = np.uint16 if len(out_attr["POSITION"]) < 65536 else np.uint32
ia["bufferView"] = append(allF.reshape(-1).astype(it), 34963); ia["byteOffset"] = 0; ia["count"] = allF.size
ia["componentType"] = 5123 if it is np.uint16 else 5125; ia.pop("min", None); ia.pop("max", None)
js["buffers"][0]["byteLength"] = len(b)
save(js, b, a.out)
sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
rel = lambda q: Path(q).resolve().relative_to(ROOT).as_posix() if Path(q).resolve().is_relative_to(ROOT) else str(q)
rec = {"schema": "homm3_mesh_surgery.sword_draw.v1", "input": rel(a.src),
       "inputSha256": hashlib.sha256(open(a.src, "rb").read()).hexdigest(), "output": rel(a.out), "outputSha256": sha,
       "tool": "tools/homm3_def_retarget/sword_draw_surgery.py " + " ".join(sys.argv[1:2] + sys.argv[4:]),
       "result": {"axisOrigin": o.tolist(), "axisDir": d.tolist(), "movedFaces": int(mf.sum()), "movedVerts": int(len(moved)),
                  "seamDuplicates": int(len(dup)), "gripFrom": gs.tolist(), "gripTo": gt.tolist(),
                  "swordSegment": [pommel.round(3).tolist(), tip.round(3).tolist()],
                  "minClearanceToBody": float(dist.min()), "verts": [n0, len(out_attr["POSITION"])], "faces": [f0, len(allF)]},
       "reason": a.reason}
json.dump(rec, open(str(Path(a.out).with_suffix("")) + ".surgery.json", "w"), indent=1)
print("wrote", a.out, sha[:12], "verts", n0, "->", len(out_attr["POSITION"]), "faces", f0, "->", len(allF))
