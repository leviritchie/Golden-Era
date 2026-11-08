"""limb_skin_split.py <base.glb> <out_table.json> --cut LeftForeArm,LeftHand --from LeftUpLeg,LeftLeg
    --zone x0,x1,y0,y1 --from-seed y<0.55 [--cut-seed y>0.9 --mode geodesic] [--unit NAME]

Companion to limb_cut_surgery.py (2026-10-11 lane A, hota_factory_juggernaut). The cut opens the mesh between a
limb part and the body part it was welded to, but the delivery build re-skins with heat weights, so vertices next to
the old contact still carry the other side's bones and the pair tears as soon as the patch separates them.

On the build's base GLB (glTF axes, all coordinates glTF), candidates are the vertices inside --zone (x and y ranges)
that carry --from weight, or only part --cut weight (pure --cut vertices, the limb part itself, are never touched).
Seeds are geometric, not by weight, because the heat skin mislabels exactly the vertices in question: --cut-seed /
--from-seed are "axis>value" or "axis<value" filters (axis x, y or z) on vertices whose share of that side's bones is
over 0.95; distances are geodesic over the mesh (positions welded at 0.01 mm, so the surgery's cut stays open).
  --mode contact (default; juggernaut fist, 2026-10-11): a candidate within --limit of a from-seed goes to the from
    side (the heat skin's partial limb weight on the body part next to the contact is what tears); one out of reach
    keeps the larger share. Measured on the juggernaut punch: tears 1484 -> 1068, worst 14.8 -> 12.9.
  --mode geodesic: the nearer seed set wins (needs --cut-seed). On the juggernaut it kept fist weight on thigh-plate
    corners still sharing faces with pure-leg vertices after the cut and tore more (1484 -> 1617); check the gate.
Cut-side vertices drop the --from bones, from-side vertices drop the --cut bones; the rest renormalised (empty ->
the side's first bone).
  --mode source (2026-10-11 lane B, hota_bulwark_great_shaman sleeve): the heat skin moved whole parts across the
    contact (the staff-arm sleeve rode Hips, robe beside it rode LeftHand), so geometric seeds cannot say which side a
    vertex is on. --src is the surgery output the build was made from (same vertices, matched by position after bbox
    normalisation; refuses if any match is further than 1e-4); --src-map "Bone_029=LeftForeArm,..." maps the source's
    limb bones to the unit's. Only zone vertices where the two skins disagree change: limb in the source (share of
    the mapped bones over 0.5) but body in the build (--cut share at most 0.5) takes the source's limb weights
    (mapped, renormalised); body in the source (mapped share under 0.05) but carrying --cut weight in the build drops
    the --cut bones. Wholesale transfer tore more (the source smears arm weight over the chest). --from-seed unused.
    UV-seam copies of one position get one shared result (cut side wins), since the patch gate refuses a split weld
    group. On the great_shaman arm raise this still tore more than the aims alone (2269 -> 5491); the gate-driven
    weight re-solve (lane B wsolve, --newonly then --keepsw) is what passed there.

Writes a weight table {"unit", "vertices": {v: {bone: w}}} for wt_install.py / the glbPatch setWeights op, and prints
how many vertices went to each side.
"""
import sys, json, argparse
import numpy as np
from pathlib import Path
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "homm3_glb_patch"))
import patch_glb as P  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("glb"); ap.add_argument("out")
ap.add_argument("--cut", required=True); ap.add_argument("--from", dest="frm", required=True)
ap.add_argument("--zone", required=True, help="x0,x1,y0,y1 (glTF) around the old contact")
ap.add_argument("--cut-seed", default=None); ap.add_argument("--from-seed", default=None)
ap.add_argument("--mode", choices=("contact", "geodesic", "source"), default="contact")
ap.add_argument("--src", default=None, help="source mode: the surgery GLB the build was made from")
ap.add_argument("--src-map", default=None, help='source mode: "SrcBone=UnitBone,..." for the limb bones')
ap.add_argument("--zmin", type=float, default=-1e9, help="zone lower bound on glTF z (source mode too)")
ap.add_argument("--zmax", type=float, default=1e9)
ap.add_argument("--limit", type=float, default=1.0, help="geodesic search radius (glTF units)")
ap.add_argument("--unit", default=None)
a = ap.parse_args()

b = P.Body(P.Glb(Path(a.glb).read_bytes())); J, W, F, V = b.J, b.W, b.F, b.V
nm = b.jnames
CUT = [nm.index(x) for x in a.cut.split(",")]; FRM = [nm.index(x) for x in a.frm.split(",")]
sC = (np.isin(J, CUT) * W).sum(1); sF = (np.isin(J, FRM) * W).sum(1)


def seed(spec, share):
    ax = "xyz".index(spec[0]); op, val = spec[1], float(spec[2:])
    m = V[:, ax] > val if op == ">" else V[:, ax] < val
    return m & (share > 0.95)


_, inv = np.unique(np.round(V, 5), axis=0, return_inverse=True); inv = inv.ravel(); n = inv.max() + 1
E = np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]; e = inv[E]
ln = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1) + 1e-9
G = coo_matrix((np.r_[ln, ln], (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), (n, n)).tocsr()
x0, x1, y0, y1 = [float(v) for v in a.zone.split(",")]
zone = (V[:, 0] > x0) & (V[:, 0] < x1) & (V[:, 1] > y0) & (V[:, 1] < y1) & (V[:, 2] > a.zmin) & (V[:, 2] < a.zmax)
if a.mode == "source":
    import struct
    from scipy.spatial import cKDTree
    if not (a.src and a.src_map):
        raise SystemExit("--mode source needs --src and --src-map")
    CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}; NC = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}
    data = Path(a.src).read_bytes(); jl = struct.unpack_from("<I", data, 12)[0]; js = json.loads(data[20:20 + jl])
    buf = data[20 + jl + 8:]; prim = js["meshes"][0]["primitives"][0]

    def sacc(i):
        x = js["accessors"][i]; bv = js["bufferViews"][x["bufferView"]]
        return np.frombuffer(buf, CT[x["componentType"]], x["count"] * NC[x["type"]],
                             bv.get("byteOffset", 0) + x.get("byteOffset", 0)).reshape(x["count"], -1).astype(np.float64)
    S = sacc(prim["attributes"]["POSITION"]); SJ = sacc(prim["attributes"]["JOINTS_0"]).astype(np.int64)
    SW = sacc(prim["attributes"]["WEIGHTS_0"]); snm = [js["nodes"][j]["name"] for j in js["skins"][0]["joints"]]
    smap = dict(kv.split("=") for kv in a.src_map.split(","))
    tgt = np.array([nm.index(smap[x]) if x in smap else -1 for x in snm])

    def unitbox(X):
        lo = X.min(0); return (X - lo) / (X.max(0) - lo).max()
    tree = cKDTree(unitbox(S)); dist, idx = tree.query(unitbox(V))
    if dist.max() > 1e-4:
        raise SystemExit(f"--src does not match the base by position (max {dist.max():.2e}); wrong source?")
    # UV-seam vertices coincide in the source but carry different skins, so the nearest one is a coin toss: match
    # faces instead (a base face's corners are one source face's corners) and take the vertex of that face.
    SF = sacc(prim["indices"]).astype(np.int64).reshape(-1, 3)
    sface = {tuple(sorted(f)): f for f in SF.tolist()}
    near = tree.query_ball_point(unitbox(V), 1e-6)
    fixed = np.zeros(len(V), bool); amb = np.array([len(c) > 1 for c in near])
    for f in F:
        if not amb[f].any():
            continue
        cands = [near[v] for v in f]
        hit = None
        for c0 in cands[0]:
            for c1 in cands[1]:
                for c2 in cands[2]:
                    if tuple(sorted((c0, c1, c2))) in sface:
                        hit = (c0, c1, c2); break
                if hit: break
            if hit: break
        if hit:
            for v, sv in zip(f, hit):
                if not fixed[v]:
                    idx[v] = sv; fixed[v] = True
    print(f"source match: {int(amb.sum())} base vertices sit on coincident source vertices, {int((fixed & amb).sum())} settled by face")
    tab, cnt = {}, {"cut": 0, "from": 0, "unchanged": 0}
    for v in np.flatnonzero(zone):
        sj, sw = SJ[idx[v]], SW[idx[v]]; lim = tgt[sj] >= 0; ss = (sw * lim).sum()
        if ss > 0.5 and sC[v] <= 0.5:
            d = {}
            for j, w in zip(tgt[sj][lim], sw[lim]):
                d[nm[j]] = d.get(nm[j], 0) + float(w)
            t = sum(d.values()); new = {k: round(w / t, 6) for k, w in d.items()}; side = "cut"
        else:
            if ss >= 0.05 or not np.isin(J[v][W[v] > 1e-6], CUT).any():
                cnt["unchanged"] += 1; continue
            d = {}
            for j, w in zip(J[v], W[v]):
                if w > 1e-6 and j not in CUT:
                    d[nm[j]] = d.get(nm[j], 0) + float(w)
            t = sum(d.values()); new = {k: round(w / t, 6) for k, w in d.items()} if t > 1e-6 else {nm[FRM[0]]: 1.0}
            side = "from"
        top = sorted(((k, w) for k, w in new.items() if w >= 1e-4), key=lambda kw: -kw[1])[:4]   # setWeights: 1-4 bones, (0, 1], sum 1
        t = sum(w for _, w in top); new = {k: round(w / t, 6) for k, w in top}
        new[top[0][0]] = round(new[top[0][0]] + 1.0 - sum(new.values()), 6)
        cnt[side] += 1; tab[str(int(v))] = (side, new)
    # UV-seam copies (one weld group: same position at 0.01 mm) must skin alike or the patch opens a crack, and the
    # source's own seams can disagree there: the whole group follows one result, cut side winning over from side.
    grp = {}
    for k in tab:
        grp.setdefault(int(inv[int(k)]), []).append(k)
    members = {}
    for v in range(len(V)):
        if int(inv[v]) in grp:
            members.setdefault(int(inv[v]), []).append(str(v))
    unified = 0
    for g, ks in grp.items():
        pick = next((tab[k] for k in ks if tab[k][0] == "cut"), tab[ks[0]])
        for k in members[g]:
            if k not in tab or tab[k][1] != pick[1]:
                unified += 1
            tab[k] = pick
    tab = {k: new for k, (_, new) in tab.items()}
    print(f"weld groups unified: {unified} copies brought in line")
    json.dump({"unit": a.unit or Path(a.glb).parent.name, "vertices": tab}, open(a.out, "w"))
    print(f"zone {int(zone.sum())}: source-limb to cut side {cnt['cut']}, limb bones dropped {cnt['from']}, unchanged {cnt['unchanged']}")
    raise SystemExit(0)
if not a.from_seed:
    raise SystemExit("--from-seed is required in contact/geodesic mode")
cand = np.flatnonzero(zone & ((sF > 1e-4) | ((sC > 1e-4) & (sC < 0.9999))))
sf = seed(a.from_seed, sF)
if not sf.any():
    raise SystemExit("no from-side seeds")
dF = dijkstra(G, indices=np.unique(inv[sf]), min_only=True, limit=a.limit)
if a.mode == "geodesic":
    if not a.cut_seed:
        raise SystemExit("--mode geodesic needs --cut-seed")
    sc = seed(a.cut_seed, sC)
    if not sc.any():
        raise SystemExit("no cut-side seeds")
    dC = dijkstra(G, indices=np.unique(inv[sc]), min_only=True, limit=a.limit)
else:
    dC = np.full(n, np.inf)
tab, cnt = {}, {"cut": 0, "from": 0, "unchanged": 0}
for v in cand:
    c_, f_ = dC[inv[v]], dF[inv[v]]
    side = ("cut" if c_ < f_ else "from") if np.isfinite(min(c_, f_)) else ("cut" if sC[v] >= sF[v] else "from")
    drop, keep = (FRM, CUT) if side == "cut" else (CUT, FRM)
    if not np.isin(J[v][W[v] > 1e-6], drop).any():
        cnt["unchanged"] += 1; continue
    cnt[side] += 1
    d = {}
    for j, w in zip(J[v], W[v]):
        if w > 1e-6 and j not in drop:
            d[nm[j]] = d.get(nm[j], 0) + float(w)
    t = sum(d.values())
    tab[str(int(v))] = {k: round(w / t, 6) for k, w in d.items()} if t > 1e-6 else {nm[keep[0]]: 1.0}
json.dump({"unit": a.unit or Path(a.glb).parent.name, "vertices": tab}, open(a.out, "w"))
print(f"candidates {len(cand)}: reweighted to cut side {cnt['cut']}, from side {cnt['from']}, already clean {cnt['unchanged']}")
