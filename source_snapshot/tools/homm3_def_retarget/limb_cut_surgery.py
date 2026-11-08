"""limb_cut_surgery.py <unit> src.glb out.glb --cut LeftForeArm,LeftHand --from LeftUpLeg,LeftLeg [--box x0,x1,y0,y1,z0,z1] [--nudge 0.0015]

Mesh surgery for hota_factory_juggernaut (authenticity pass 2026-10-11; mesh surgery standing-approved): the Meshy
mesh welds the resting left fist onto the left thigh plate (92 faces join fist vertices to thigh vertices), so any
attack that takes the fist off the hip (the DEF g12 forward punch) drags a long shard of thigh plate out with it.

Generic: vertices are classed by the source skin, `cut` (share of the --cut bones > 0.5) and `from` (share of the --from
bones > 0.5). Bridge faces are those with both classes (optionally only inside --box, Blender axes); a bridge face goes
to the side that holds the majority of its corners (ties to `from`). The cut side is every pure-`cut` face plus its
bridge faces; the vertices it shares with the `from` side (pure-`from` faces plus theirs) are duplicated, the cut side
taking the copies, nudged --nudge away from the from-side centroid so the two islands stay apart by position. Skin:
the copies drop the --from bones and the originals drop the --cut bones (renormalised; empty -> the side's first bone).
Every other vertex, face, UV and the texture are unchanged; at rest it is the same mesh.
--mixed-from (2026-10-11 lane B, hota_bulwark_great_shaman sleeve): inside --box, a vertex that is not `cut` counts as
`from` even when no bone side holds over 0.5 of it. A sleeve can hang onto the torso/robe through a strip of mixed
vertices (no face there has a pure-`from` corner, so the plain rule finds no bridge); keep the box below the shoulder
so the limb stays attached where it should. Needs --box.
--classes FILE (2026-10-12 lane B, hota_bulwark_war_mammoth tusk/cheek off the foreleg): a JSON {"cut": [...], "from": [...]}
of src vertex indices replaces the bone classes (for a Meshy auto-rig whose bone shares do not separate the parts, e.g. a
tusk root skinned to the foreleg it rests against). --cut/--from are then not needed and the skin is left as it is on both
sides (fix it afterwards with a glbPatch setWeights table); list only vertices near the contact, since every face holding
a class vertex of each side is split.
--weld-split (2026-10-12 lane B): also nudge the cut side's UV-seam copies that are not duplicated (used only by cut-side
faces) but sit at the position of a from-side vertex; otherwise the two islands still share a weld group by position and
the glbPatch gate (and any weld-by-position consumer) keeps them skinned alike, i.e. still joined.
--dry-run: print the counts (and the bridge-face centroid range) without writing.
Writes <out stem>.surgery.json next to the output.
"""
import sys, json, hashlib, argparse, struct
import numpy as np
from pathlib import Path

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
ap.add_argument("--cut"); ap.add_argument("--from", dest="frm")
ap.add_argument("--classes", default=None, help="JSON {cut: [src vertex ids], from: [...]} replacing the bone classes; skin unchanged")
ap.add_argument("--box", default=None, help="x0,x1,y0,y1,z0,z1 (Blender axes) bounding the bridge faces")
ap.add_argument("--nudge", type=float, default=0.0015)
ap.add_argument("--expect", default=None, help="sha256 the source must have")
ap.add_argument("--reason", default="")
ap.add_argument("--mixed-from", action="store_true", help="inside --box, every non-cut vertex counts as from")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--weld-split", action="store_true", help="also nudge cut-only seam copies at a from-side position")
a = ap.parse_args()

src_sha = hashlib.sha256(open(a.src, "rb").read()).hexdigest()
if a.expect and src_sha != a.expect:
    raise SystemExit(f"{a.src}: sha {src_sha[:12]} is not the reviewed source {a.expect[:12]}; re-check the cut first")
js, b = load(a.src)
p = js["meshes"][0]["primitives"][0]
attrs = {k: acc(js, b, i) for k, i in p["attributes"].items()}
F = acc(js, b, p["indices"]).reshape(-1, 3).astype(np.int64)
G = attrs["POSITION"].astype(np.float64); Bl = np.c_[G[:, 0], -G[:, 2], G[:, 1]]
nm = [js["nodes"][j]["name"] for j in js["skins"][0]["joints"]]
if a.classes:
    cls = json.load(open(a.classes)); isC = np.zeros(len(G), bool); isF = np.zeros(len(G), bool)
    isC[cls["cut"]] = True; isF[cls["from"]] = True
    if (isC & isF).any():
        raise SystemExit(f"--classes: {int((isC & isF).sum())} vertices are in both classes")
    cutb = frmb = None
else:
    if not (a.cut and a.frm):
        raise SystemExit("--cut and --from are required without --classes")
    cutb = [nm.index(x) for x in a.cut.split(",")]; frmb = [nm.index(x) for x in a.frm.split(",")]
    J = attrs["JOINTS_0"].astype(np.int64); W = attrs["WEIGHTS_0"].astype(np.float64)
    sC = (np.isin(J, cutb) * W).sum(1); sF = (np.isin(J, frmb) * W).sum(1)
    isC, isF = sC > 0.5, sF > 0.5
n0, f0 = len(G), len(F)
if a.mixed_from:
    if not a.box:
        raise SystemExit("--mixed-from needs --box")
    x0, x1, y0, y1, z0, z1 = [float(v) for v in a.box.split(",")]
    inbox = (Bl[:, 0] >= x0) & (Bl[:, 0] <= x1) & (Bl[:, 1] >= y0) & (Bl[:, 1] <= y1) & (Bl[:, 2] >= z0) & (Bl[:, 2] <= z1)
    isF = isF | (inbox & ~isC)

nC, nF = isC[F].sum(1), isF[F].sum(1)
bridge = (nC > 0) & (nF > 0)
if a.box:
    x0, x1, y0, y1, z0, z1 = [float(v) for v in a.box.split(",")]
    c = Bl[F].mean(1)
    bridge &= (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1) & (c[:, 2] >= z0) & (c[:, 2] <= z1)
if a.dry_run:
    cb = Bl[F[bridge]].mean(1)
    print(f"dry run: bridge faces {int(bridge.sum())} (to cut side {int((bridge & (nC > nF)).sum())})",
          "centroid range", np.round(cb.min(0), 3).tolist() if len(cb) else None, np.round(cb.max(0), 3).tolist() if len(cb) else None)
    raise SystemExit(0)
cut_face = ((nC == 3) | (bridge & (nC > nF)))
frm_face = ((nF > 0) & ~cut_face) | (bridge & ~cut_face)
uC = np.zeros(n0, bool); uC[F[cut_face].ravel()] = True
uF = np.zeros(n0, bool); uF[F[frm_face].ravel()] = True
dup = np.flatnonzero(uC & uF)
remap = np.arange(n0); remap[dup] = n0 + np.arange(len(dup))
F2 = F.copy(); F2[cut_face] = remap[F[cut_face]]
ext = {k: np.concatenate([v, v[dup]]) for k, v in attrs.items()}
# nudge the copies away from the from-side centroid
fc = Bl[np.unique(F[frm_face & bridge])].mean(0) if (frm_face & bridge).any() else Bl[dup].mean(0)
d = Bl[dup] - fc; d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-12
mv = d * a.nudge   # Blender -> glTF: (x, y, z)_bl = (x, -z, y)_gl
pos = ext["POSITION"].astype(np.float64); pos[n0:] += np.c_[mv[:, 0], mv[:, 2], -mv[:, 1]]
welded = np.zeros(0, np.int64)
if a.weld_split:
    kq = lambda X: [tuple(r) for r in np.round(X, 5)]
    fpos = set(kq(G[uF]))
    only = np.flatnonzero(uC & ~uF)
    welded = only[np.array([k in fpos for k in kq(G[only])], bool)] if len(only) else only
    if len(welded):
        dw = Bl[welded] - fc; dw /= np.linalg.norm(dw, axis=1, keepdims=True) + 1e-12; mw = dw * a.nudge
        pos[welded] += np.c_[mw[:, 0], mw[:, 2], -mw[:, 1]]
ext["POSITION"] = pos.astype(attrs["POSITION"].dtype)


def strip(idx, drop, fallback):
    Jx, Wx = ext["JOINTS_0"], ext["WEIGHTS_0"].astype(np.float64)
    for v in idx:
        w = Wx[v].copy(); w[np.isin(Jx[v], drop)] = 0
        if w.sum() < 1e-6:
            Jx[v] = [fallback, 0, 0, 0]; w = np.array([1.0, 0, 0, 0])
        Wx[v] = w / w.sum()
    ext["WEIGHTS_0"] = Wx.astype(attrs["WEIGHTS_0"].dtype)


if not a.classes:
    strip(n0 + np.arange(len(dup)), frmb, cutb[0])
    strip(dup, cutb, frmb[0])


def append(arr, target=None):
    global b
    while len(b) % 4:
        b += b"\0"
    off = len(b); raw = np.ascontiguousarray(arr).tobytes(); b += raw
    bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
    if target:
        bv["target"] = target
    js["bufferViews"].append(bv); return len(js["bufferViews"]) - 1


for k, arr in ext.items():
    x = js["accessors"][p["attributes"][k]]
    x["bufferView"] = append(arr, 34962); x["byteOffset"] = 0; x["count"] = len(arr)
    if "min" in x or k == "POSITION":
        x["min"] = arr.min(0).tolist(); x["max"] = arr.max(0).tolist()
ia = js["accessors"][p["indices"]]
it = np.uint16 if len(ext["POSITION"]) < 65536 else np.uint32
ia["bufferView"] = append(F2.reshape(-1).astype(it), 34963); ia["byteOffset"] = 0; ia["count"] = F2.size
ia["componentType"] = 5123 if it is np.uint16 else 5125; ia.pop("min", None); ia.pop("max", None)
js["buffers"][0]["byteLength"] = len(b)
save(js, b, a.out)
sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()


def rel(q):
    q = Path(q).resolve()
    return q.relative_to(ROOT).as_posix() if q.is_relative_to(ROOT) else str(q)


rec = {"schema": "homm3_mesh_surgery.limb_cut.v1", "input": rel(a.src), "inputSha256": src_sha, "output": rel(a.out),
       "outputSha256": sha, "tool": "tools/homm3_def_retarget/limb_cut_surgery.py " + " ".join(sys.argv[1:2] + sys.argv[4:]),
       "result": {"bridgeFaces": int(bridge.sum()), "bridgeToCut": int((bridge & cut_face).sum()), "cutFaces": int(cut_face.sum()),
                  "seamDuplicates": int(len(dup)), "weldSplitNudged": int(len(welded)), "nudge": a.nudge, **({"classes": rel(a.classes), "classesSha256": hashlib.sha256(open(a.classes, "rb").read()).hexdigest(), "skin": "unchanged"} if a.classes else {}), "verts": [n0, len(ext["POSITION"])], "faces": [f0, len(F2)]},
       "reason": a.reason}
json.dump(rec, open(str(Path(a.out).with_suffix("")) + ".surgery.json", "w"), indent=1)
print(f"bridge faces {bridge.sum()} (to cut side {(bridge & cut_face).sum()}), cut-side faces {cut_face.sum()}, seam dups {len(dup)}, weld-split nudged {len(welded)}")
print("wrote", a.out, sha[:12], "verts", n0, "->", len(ext["POSITION"]), "faces", f0, "->", len(F2))
