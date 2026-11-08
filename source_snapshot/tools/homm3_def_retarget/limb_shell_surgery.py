"""limb_shell_surgery.py <unit> src.glb out.glb --classes FILE [--inset 0.97] [--nudge 0.002] [--expect SHA] [--reason ..]

Mesh surgery for a limb modelled as part of the body's outer shell (2026-10-12 lane A, h3_hurricane_elemental: Meshy
fused the crossed forearms and fists into the front wall of the whirlwind torso and the upper-arm puffs into its
sides; there is no torso surface behind them, so cutting the arms off alone (limb_cut_surgery) would open a hole and
any weight split tears a sheet between fist and belly).

--classes is a JSON {"parts": {"<name>": [src vertex ids], ...}} (disjoint sets, e.g. one per arm). A face goes to a
part when at least two of its corners are in it (so the crossing of two limbs and a stray unlisted corner do not leave
slivers behind). For each part, the part's faces are DUPLICATED:
  * the copy (new vertices appended after the source's, same UVs/normals/skin attributes) is the free limb: it shares
    no vertex with anything else, so it can be lifted off the body without stretching a face;
  * the original faces stay as the body wall behind the limb. Their vertices that no other face uses are pulled
    radially in toward the torso axis, to --inset x the torso's radius at that height (the median distance of the
    non-part vertices in a 6 cm slab around the slab's own centroid), so the wall closes the body under the limb
    instead of leaving a second limb behind; vertices the part shares with the rest of the body stay put.
The limb copies' border vertices (those coinciding with a kept body vertex) are nudged --nudge out from the torso axis
so no consumer welds limb and body back together by position. The skin attributes are copied unchanged; the DEF
retarget build re-skins anyway, and the body wall's weights are set afterwards (a glbPatch setWeights table).
--min-island N leaves a part's face islands of fewer than N faces (welded by position) in the body instead of copying
them: a stray sliver of the outer wall would otherwise ride along with the limb as a floating shard.
--backface also gives each limb copy a reversed-winding twin (same positions, normals and tangents negated): the
copy is a single sheet cut from the outer wall (no inner surface), so without it the limb vanishes under back-face
culling from every angle that looks at its inside (2026-10-12 hurricane: only the fists showed once the arms rose).
--relocate FILE ({"islands": [{"part": name, "near": [x, y, z], "translate": [dx, dy, dz], "why": ".."}]}, glTF
metres) moves one welded face island of a part's limb copy (the island holding the copy vertex nearest "near") rigidly
by "translate": a fist modelled as its own lump on the belly, away from its upper arm, is put back on the end of that
arm so a raised arm carries it instead of leaving it floating (2026-10-12 hurricane left fist).
No source vertex index changes; vertices only move where listed above. Writes <out stem>.surgery.json.
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
ap.add_argument("--classes", required=True)
ap.add_argument("--inset", type=float, default=0.97)
ap.add_argument("--nudge", type=float, default=0.002)
ap.add_argument("--slab", type=float, default=0.03)
ap.add_argument("--expect", default=None)
ap.add_argument("--reason", default="")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--min-island", type=int, default=0)
ap.add_argument("--backface", action="store_true")
ap.add_argument("--relocate", default=None)
a = ap.parse_args()

src_sha = hashlib.sha256(open(a.src, "rb").read()).hexdigest()
if a.expect and src_sha != a.expect:
    raise SystemExit(f"{a.src}: sha {src_sha[:12]} is not the reviewed source {a.expect[:12]}")
js, b = load(a.src)
assert len(js["meshes"]) == 1 and len(js["meshes"][0]["primitives"]) == 1, "single-primitive meshes only"
p = js["meshes"][0]["primitives"][0]
attrs = {k: acc(js, b, i) for k, i in p["attributes"].items()}
F = acc(js, b, p["indices"]).reshape(-1, 3).astype(np.int64)
G = attrs["POSITION"].astype(np.float64); n0 = len(G)
Bl = np.c_[G[:, 0], -G[:, 2], G[:, 1]]   # Blender axes, z up
parts = json.load(open(a.classes))["parts"]
cls = np.full(n0, -1)
for k, (name, ids) in enumerate(parts.items()):
    ids = np.asarray(ids, np.int64)
    if (cls[ids] >= 0).any():
        raise SystemExit(f"--classes: part {name} overlaps another part")
    cls[ids] = k
anyp = cls >= 0
cf = cls[F]                                                                   # a face goes to the part holding
cnt = np.stack([(cf == k).sum(1) for k in range(len(parts))], 1)             # >= 2 of its corners (most corners;
fpart = np.where(cnt.max(1) >= 2, cnt.argmax(1), -1)                         # ties to the lower part id), else body
_, pid0 = np.unique(np.round(G, 6), axis=0, return_inverse=True); pid0 = pid0.ravel()
dropped = 0
if a.min_island:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    for k in range(len(parts)):
        fk = np.flatnonzero(fpart == k)
        if not len(fk): continue
        Fw = pid0[F[fk]]; nn = pid0.max() + 1
        A = coo_matrix((np.ones(Fw.size), (Fw.ravel(), np.roll(Fw, 1, 1).ravel())), shape=(nn, nn))
        _, lab = connected_components(A, directed=False); fl = lab[Fw[:, 0]]
        cnt_i = np.bincount(fl)
        small = cnt_i[fl] < a.min_island
        fpart[fk[small]] = -1; dropped += int(small.sum())
pf = [np.flatnonzero(fpart == k) for k in range(len(parts))]
inpart = np.zeros(len(F), bool)
for f in pf: inpart[f] = True
used_out = np.zeros(n0, bool); used_out[F[~inpart].ravel()] = True     # used by a face that stays body only
# by position: a UV-seam twin of a body vertex counts as used by the body too (else its limb copy would sit exactly
# on the kept body vertex and weld back to it)
_, pid = np.unique(np.round(G, 6), axis=0, return_inverse=True); pid = pid.ravel()
used_out = np.bincount(pid, weights=used_out, minlength=pid.max() + 1)[pid] > 0
body = ~anyp


def axis_at(z):
    m = body & (np.abs(Bl[:, 2] - z) < a.slab)
    if m.sum() < 12:
        return None, None
    c = Bl[m, :2].mean(0); r = np.median(np.linalg.norm(Bl[m, :2] - c, axis=1))
    return c, r


pos = G.copy(); moved = 0; skipped = 0
inpv = np.zeros(n0, bool); inpv[F[inpart].ravel()] = True
inner = np.flatnonzero(inpv & ~used_out)
for v in inner:
    c, r = axis_at(Bl[v, 2])
    if c is None:
        skipped += 1; continue
    d = Bl[v, :2] - c; rv = np.linalg.norm(d); rt = a.inset * r
    if rv > rt and rv > 1e-9:
        nb = Bl[v].copy(); nb[:2] = c + d / rv * rt
        pos[v] = [nb[0], nb[2], -nb[1]]; moved += 1
newF = []; ext = {k: [v] for k, v in attrs.items()}; base = n0; nudged = 0; stats = {}
for k, (name, fids) in enumerate(zip(parts, pf)):
    vs = np.unique(F[fids].ravel())
    remap = {int(v): base + i for i, v in enumerate(vs)}
    for kk, arr in attrs.items():
        ext[kk].append(arr[vs])
    cp = attrs["POSITION"][vs].astype(np.float64).copy()
    border = used_out[vs]
    for i in np.flatnonzero(border):
        c, _ = axis_at(Bl[vs[i], 2])
        if c is None: continue
        d = Bl[vs[i], :2] - c; d /= np.linalg.norm(d) + 1e-12
        cp[i] += [d[0] * a.nudge, 0.0, -d[1] * a.nudge]; nudged += 1
    # where two parts' faces meet (the crossing of the forearms), each part's copy would sit on the other's: nudge
    # it toward its own part's centre so the two limbs do not weld back together by position
    other = np.zeros(pid.max() + 1, bool)
    for kk, ff in enumerate(pf):
        if kk != k: other[pid[F[ff].ravel()]] = True
    cen = Bl[vs].mean(0)
    for i in np.flatnonzero(other[pid[vs]]):
        d = cen - Bl[vs[i]]; d /= np.linalg.norm(d) + 1e-12
        cp[i] += [d[0] * a.nudge, d[2] * a.nudge, -d[1] * a.nudge]; nudged += 1
    for isl in (json.load(open(a.relocate))["islands"] if a.relocate else []):
        if isl["part"] != name: continue
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        loc = {int(v): i for i, v in enumerate(vs)}; Fl = np.vectorize(loc.get)(F[fids])
        _, wl = np.unique(np.round(cp, 5), axis=0, return_inverse=True); wl = wl.ravel(); Fw = wl[Fl]
        A = coo_matrix((np.ones(Fw.size), (Fw.ravel(), np.roll(Fw, 1, 1).ravel())), shape=(wl.max() + 1,) * 2)
        _, lab = connected_components(A, directed=False); lv = lab[wl]
        seed = int(np.argmin(np.linalg.norm(cp - np.asarray(isl["near"]), axis=1)))
        m = lv == lv[seed]; cp[m] += np.asarray(isl["translate"], float)
        stats[name] = {**stats.get(name, {}), "relocated": {"vertices": int(m.sum()), "translate": isl["translate"]}}
    ext["POSITION"][-1] = cp.astype(attrs["POSITION"].dtype)
    newF.append(np.vectorize(remap.get)(F[fids]))
    stats[name] = {**stats.get(name, {}), "faces": int(len(fids)), "vertices": int(len(vs)), "border": int(border.sum())}
    base += len(vs)
    if a.backface:   # the sheet's inside: same positions, reversed winding, flipped normals/tangents
        for kk, arr in attrs.items():
            x = ext[kk][-1].copy() if kk == "POSITION" else arr[vs].copy()
            if kk == "NORMAL": x = -x
            if kk == "TANGENT": x[:, :3] = -x[:, :3]
            ext[kk].append(x)
        remap2 = {int(v): base + i for i, v in enumerate(vs)}
        newF.append(np.vectorize(remap2.get)(F[fids])[:, ::-1])
        stats[name]["backfaceVertices"] = int(len(vs))
        base += len(vs)
print("small islands left in the body (faces)", dropped)
print("parts", stats, "wall vertices pulled in", moved, "skipped", skipped, "border copies nudged", nudged)
if a.dry_run:
    raise SystemExit(0)
ext = {k: np.concatenate(v) for k, v in ext.items()}
ext["POSITION"][:n0] = pos.astype(attrs["POSITION"].dtype)
F2 = np.concatenate([F] + newF)


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


rec = {"schema": "homm3_mesh_surgery.limb_shell.v1", "input": rel(a.src), "inputSha256": src_sha, "output": rel(a.out),
       "outputSha256": sha, "tool": "tools/homm3_def_retarget/limb_shell_surgery.py " + " ".join(sys.argv[1:2] + sys.argv[4:]),
       "classes": rel(a.classes), "classesSha256": hashlib.sha256(open(a.classes, "rb").read()).hexdigest(),
       "result": {"parts": stats, "wallPulledIn": moved, "borderNudged": nudged, "inset": a.inset, "nudge": a.nudge,
                  "minIsland": a.min_island, "relocate": rel(a.relocate) if a.relocate else None, "smallIslandFacesKept": dropped, "backface": a.backface,
                  "verts": [n0, len(ext["POSITION"])], "faces": [len(F), len(F2)]},
       "reason": a.reason}
json.dump(rec, open(str(Path(a.out).with_suffix("")) + ".surgery.json", "w"), indent=1)
print("wrote", a.out, sha[:12], "verts", n0, "->", len(ext["POSITION"]), "faces", len(F), "->", len(F2))
