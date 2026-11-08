"""prop_cut_surgery.py <unit> src.glb out.glb --seg x0,y0,z0,x1,y1,z1 [--fit-r 0.03] [--t-lo -0.1] [--t-hi 1.1]
    [--r-core 0.03] [--radial-min 0.2] [--box x0,y0,z0,x1,y1,z1 ...] [--nudge 0.0015] [--orphan-max 40] [--expect sha]

In-place prop cut (authenticity pass 2026-10-11, lane A, h3_peasant pitchfork; mesh surgery standing-approved): the
Meshy mesh welds a held prop into the body where it rests against it (the peasant's pitchfork shaft is face-joined to
the right thigh, the right fist and the left grip), so the heat skin bleeds body weights onto the prop and any pose
that moves the prop away from the body tears the shaft apart (the tines float free of the haft in the attack). This
cuts the prop out as its own island, in place; the unit config then makes it rigid with a "wholeIslands" prop region.

All geometry is in Blender coordinates (x, -z, y of glTF), like the unit config's props.
- Axis: PCA of the vertices within --fit-r of --seg (one prop segment from the config, roughly along the shaft); t is
  the distance along the fitted axis from --seg's first point, toward its second.
  --refine-bin s: per slice of t the axis point moves to the median of the vertices within --refine-r of it (a haft
  that bends or sits off the fit), interpolated between slices.
- Cut set: vertices with t in [t-lo, t-hi] within r-core of the axis whose vertex normal points away from the axis
  (radial component > radial-min; a finger wrapped round the shaft faces it and stays on the body), plus every vertex
  inside each --box (a prop head off the axis, e.g. tines). Faces with all three corners in the set go to the prop.
- Small kept fragments (position-welded islands under --orphan-max faces) touching the cut go with the prop.
- Seam: prop vertices whose position (welded, 4 decimals) a body face also uses are duplicated; the prop takes the copies, nudged --nudge along the
  outward axis normal so the build's position weld (5 decimals) keeps the islands apart. Positions only move by the
  nudge; UVs, normals and the texture are copied unchanged; at rest it is the same mesh.
Writes <out stem>.surgery.json next to the output and prints the prop island's faces/verts and its seam size.
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
ap.add_argument("--seg", required=True, help="x0,y0,z0,x1,y1,z1 (Blender) roughly along the prop")
ap.add_argument("--fit-r", type=float, default=0.03)
ap.add_argument("--t-lo", type=float, default=-0.1); ap.add_argument("--t-hi", type=float, default=1.1)
ap.add_argument("--r-core", type=float, default=0.03); ap.add_argument("--radial-min", type=float, default=0.2)
ap.add_argument("--box", action="append", default=[], help="x0,y0,z0,x1,y1,z1 (Blender), repeatable")
ap.add_argument("--nudge", type=float, default=0.0015); ap.add_argument("--orphan-max", type=int, default=40)
ap.add_argument("--refine-bin", type=float, default=0.0); ap.add_argument("--refine-r", type=float, default=0.06)
ap.add_argument("--expect", default=""); ap.add_argument("--reason", default="")
a = ap.parse_args()

src_sha = hashlib.sha256(open(a.src, "rb").read()).hexdigest()
if a.expect and not src_sha.startswith(a.expect):
    raise SystemExit(f"{a.src}: sha {src_sha[:12]} is not the expected source {a.expect}; re-check the cut first")
js, b = load(a.src)
p = js["meshes"][0]["primitives"][0]
attrs = {k: acc(js, b, i) for k, i in p["attributes"].items()}
F = acc(js, b, p["indices"]).reshape(-1, 3).astype(np.int64)
G = attrs["POSITION"].astype(np.float64)
Bl = np.c_[G[:, 0], -G[:, 2], G[:, 1]]
n0, f0 = len(Bl), len(F)
s = np.array([float(x) for x in a.seg.split(",")]); a0, a1 = s[:3], s[3:]; L0 = np.linalg.norm(a1 - a0); d0 = (a1 - a0) / L0


def tdist(P, o, d):
    r = P - o; t = r @ d; return t, np.linalg.norm(r - np.outer(t, d), axis=1), r - np.outer(t, d)


t, dd, _ = tdist(Bl, a0, d0)
fit = (t > 0) & (t < L0) & (dd < a.fit_r)
if fit.sum() < 10:
    raise SystemExit(f"only {fit.sum()} vertices within {a.fit_r} of --seg; check the segment")
o = Bl[fit].mean(0); _, sv, vt = np.linalg.svd(Bl[fit] - o); d = vt[0] * np.sign(vt[0] @ d0)
o = o + ((a0 - o) @ d) * d                                   # t = 0 at --seg's first point, on the fitted axis
t, dd, rad = tdist(Bl, o, d)
if a.refine_bin > 0:
    # a carved haft is not a straight line: per --refine-bin slice of t, the axis point is the median of the vertices
    # within --refine-r of the line (interpolated between slices), so the core test follows the haft's own centre
    edges = np.arange(a.t_lo, a.t_hi + a.refine_bin, a.refine_bin); ctr = []; tc = []
    for lo in edges[:-1]:
        m = (t >= lo) & (t < lo + a.refine_bin) & (dd < a.refine_r)
        if m.sum() >= 6:
            ctr.append(np.median(rad[m], axis=0)); tc.append(lo + a.refine_bin / 2)
    ctr, tc = np.array(ctr), np.array(tc)
    off = np.stack([np.interp(t, tc, ctr[:, i]) for i in range(3)], 1)
    rad = rad - off; dd = np.linalg.norm(rad, axis=1)
    print("refined axis offsets (m):", np.linalg.norm(ctr, axis=1).round(3).tolist())
fn =np.cross(Bl[F[:, 1]] - Bl[F[:, 0]], Bl[F[:, 2]] - Bl[F[:, 0]]); N = np.zeros_like(Bl)
for i in range(3):
    np.add.at(N, F[:, i], fn)
N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
radial = np.einsum("ij,ij->i", N, rad / (dd[:, None] + 1e-9))
cut = (t > a.t_lo) & (t < a.t_hi) & (dd < a.r_core) & (radial > a.radial_min)
for bx in a.box:
    q = np.array([float(x) for x in bx.split(",")]); lo, hi = np.minimum(q[:3], q[3:]), np.maximum(q[:3], q[3:])
    cut |= np.all((Bl >= lo) & (Bl <= hi), axis=1)
mf = cut[F].all(1)
_, inv = np.unique(np.round(Bl, 4), axis=0, return_inverse=True); inv = inv.ravel(); nw = inv.max() + 1
Wk = inv[F[~mf]]
_, wl = connected_components(coo_matrix((np.ones(Wk.size), (Wk.ravel(), np.roll(Wk, 1, 1).ravel())), (nw, nw)), directed=False)
fl = wl[Wk[:, 0]]; cnt = np.bincount(fl); cutc = Bl[cut]
kept_idx = np.flatnonzero(~mf); orphan = []
for c in np.flatnonzero((cnt > 0) & (cnt < a.orphan_max)):
    fs = kept_idx[fl == c]
    if cKDTree(cutc).query(Bl[F[fs]].reshape(-1, 3))[0].min() < 0.03:
        orphan += fs.tolist()
mf[orphan] = True
kept_use = np.zeros(nw, bool); kept_use[inv[F[~mf].ravel()]] = True    # by welded position: UV-seam twins count
pv = np.unique(F[mf]); dup = pv[kept_use[inv[pv]]]
remap = np.arange(n0); remap[dup] = n0 + np.arange(len(dup))
Fp = remap[F[mf]]
# prop islands after the cut (position-welded), for the report
Wp = inv[F[mf]]
_, pl = connected_components(coo_matrix((np.ones(Wp.size), (Wp.ravel(), np.roll(Wp, 1, 1).ravel())), (nw, nw)), directed=False)
isl = np.bincount(pl[Wp[:, 0]]); isl = sorted(isl[isl > 0].tolist(), reverse=True)
newBl = np.concatenate([Bl, Bl[dup]])
r_dup = rad[dup] / (dd[dup][:, None] + 1e-9)
newBl[n0:] += a.nudge * r_dup                                 # prop copies move off the axis-outward normal
out_attr = {}
for k, arr in attrs.items():
    ext = np.concatenate([arr, arr[dup]])
    if k == "POSITION":
        ext = np.c_[newBl[:, 0], newBl[:, 2], -newBl[:, 1]].astype(arr.dtype)
    out_attr[k] = ext
allF = np.concatenate([F[~mf], Fp])
print(f"axis o {o.round(3)} d {d.round(4)} (fit {fit.sum()} verts, spread {sv[:3].round(3)}); cut verts {cut.sum()}, "
      f"prop faces {mf.sum()} (orphans {len(orphan)}), prop verts {len(pv)}, seam duplicates {len(dup)}; "
      f"prop islands (faces) {isl[:6]}")


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
rec = {"schema": "homm3_mesh_surgery.prop_cut.v1", "input": rel(a.src), "inputSha256": src_sha, "output": rel(a.out),
       "outputSha256": sha, "tool": "tools/homm3_def_retarget/prop_cut_surgery.py " + " ".join(sys.argv[1:2] + sys.argv[4:]),
       "result": {"axisOrigin": o.tolist(), "axisDir": d.tolist(), "propFaces": int(mf.sum()), "propVerts": int(len(pv)),
                  "orphanFaces": len(orphan), "seamDuplicates": int(len(dup)), "propIslands": isl[:10],
                  "verts": [n0, len(out_attr["POSITION"])], "faces": [f0, len(allF)]},
       "reason": a.reason}
json.dump(rec, open(str(Path(a.out).with_suffix("")) + ".surgery.json", "w"), indent=1)
print("wrote", a.out, sha[:12], "verts", n0, "->", len(out_attr["POSITION"]), "faces", f0, "->", len(allF))
