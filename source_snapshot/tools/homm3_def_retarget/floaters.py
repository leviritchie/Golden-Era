"""Floater audit: geometry that hangs in the air when it should not (not holes, not stretch).

Usage: python tools/homm3_def_retarget/floaters.py [unit ...] [--json out.json] [--images]
       (default: every artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb)
       Per-unit results go to artifacts/homm3_def_retarget/_floaters/<unit>.json, evidence crops
       (with --images) to artifacts/homm3_def_retarget/_floaters/img/.

Pure numpy/scipy/PIL, no Blender. Reads the exported GLB with articulation.load and skins the main
mesh itself at every key time of each Unit_* clip, INCLUDING the corrective-smooth morph weights
(articulation.audit skips them; the CS offsets pull torn connected regions back, so leaving them
out would overstate motion gaps). Two kinds of floater:

1. rest (source mesh): vertices are welded by position (1e-5, UV seams split them), connected
   pieces found from the triangles, and pieces closer than `linkTol` (1% of the unit's size) to
   each other are chained into clusters. Every cluster that does not chain to the main body is a
   rest floater: `gap` = its nearest-vertex distance to the rest of the mesh. Separate pieces that
   touch the body (armour plates, hair, eyes, props held in the hand) chain to it and are not flagged.
2. motion (rig/weights): vertices are welded by position AND identical skin weights, so a region
   the build cut free (rigid props, wings, split hands) or a Meshy piece weighted on its own is its
   own "skin piece". Per frame, pieces within linkTol of each other are chained into groups; every
   group not chained to the largest piece is detached, and its gap is its nearest approach to any
   geometry outside the group (so a crest of many shards that leaves together is one group, and a
   toe chip beside a foot that is itself detached measures to the foot). `open` = gap minus the
   bind-pose gap. Each finding names the clip, frame, the group's dominant bone, the bone of the
   surface it sat on at bind (`sitsOn`), whether it is a separate Meshy piece or a cut region,
   `fixPoint` (a vertex of it in Blender Z-up coordinates, for ext/floater_fix.py) and a proposed
   `fix` class (weightfill / reweightToSurface / structural; rest: deleteIsland / reportProp).
   `score` = open scaled down for slivers under 5% of the unit's size (ranking only).
Also recorded: `unweighted` (vertices the glTF exporter bound to "neutral_bone" because they had no
deform weight in Blender: they stay frozen at rest while the body moves; a large frozen region that
stays near the body is a tear, not a floater, so it is counted here directly), `rubble` (a *_Rubble
mesh must be ~zero size in every clip but Death) and `sinks`
(pieces dipping below the unit's own Idle ground by > 3% of its size; grounded units only).

Severity uses the gap as a fraction of the unit's size (max bbox extent at bind): high >= 6%,
medium >= 3%, low >= 1.5% (and, for debris, any detached piece of <= 12 welded vertices); a motion
group under 2% of the unit's size drops one level.
Whitelist (WHITELIST below plus rules): Death clips of units that shatter/shrink/pile/mist (the
death is meant to come apart), pieces bound to a hook-added prop bone (propBones, flail), and named
per-unit cases with the reason recorded. Whitelisted items are kept in the JSON with `whitelist`.
Proof: generated-artifact only (the GLB as exported); nothing here is imported into Unity.
"""
import json, os, sys
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import articulation as A

OUTDIR = os.path.join(A.ART, "_floaters")
UNITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "units")
STD = {"Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "Root"} | {
    s + p for s in ("Left", "Right") for p in ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase")}
SEV = (("high", 0.06), ("medium", 0.03), ("low", 0.015))
# per-unit intentional floaters: match on the piece's dominant bone and/or clip, reason recorded
WHITELIST = {
    "hota_cove_sorceress": [{"props": ["orb"], "reason": "crystal ball floats above the hand by design (DEF shows it hovering)"}],
    "hota_cove_tidecaller": [{"props": ["orb"], "reason": "same crystal ball as the sorceress (tidecaller is its upgrade, same mesh)"}],
}
FREE_DEATH = ("shatter", "shrinkOut", "bonePile", "mistForm", "deathDrop", "teleport")


def _components(n, a, b):
    m = coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    return connected_components(m, directed=False)[1]


def _clusters(ids, n):
    return _components(n, *(np.array(x, int) for x in zip(*ids))) if ids else np.arange(n)


def load_unit(path):
    """Main skinned mesh (largest non-rubble), its morph targets, rubble meshes, and a frame evaluator."""
    g, acc0 = A.load(path)

    def acc(i):
        a = g["accessors"][i]
        if "bufferView" in a and "sparse" not in a:
            return acc0(i)
        n = A.NC[a["type"]]
        out = acc0(i).copy() if "bufferView" in a else np.zeros((a["count"], n), np.float32)
        sp = a.get("sparse")
        if sp:                                         # sparse accessor (Blender writes morphs this way)
            gi = dict(g); gi["accessors"] = list(g["accessors"])
            k = len(gi["accessors"])
            gi["accessors"] = gi["accessors"] + [
                {"bufferView": sp["indices"]["bufferView"], "byteOffset": sp["indices"].get("byteOffset", 0),
                 "componentType": sp["indices"]["componentType"], "count": sp["count"], "type": "SCALAR"},
                {"bufferView": sp["values"]["bufferView"], "byteOffset": sp["values"].get("byteOffset", 0),
                 "componentType": a["componentType"], "count": sp["count"], "type": a["type"]}]
            g["accessors"].extend(gi["accessors"][k:])
            ii = acc0(k)[:, 0].astype(int); vv = acc0(k + 1)
            del g["accessors"][k:]
            out[ii] = vv
        return out
    nodes = g["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    rest = {i: (np.array(n.get("translation", [0, 0, 0]), float), np.array(n.get("rotation", [0, 0, 0, 1]), float),
                np.array(n.get("scale", [1, 1, 1]), float)) for i, n in enumerate(nodes)}
    order, stack = [], [i for i in range(len(nodes)) if i not in parent][::-1]
    while stack:
        i = stack.pop(); order.append(i); stack += nodes[i].get("children", [])[::-1]

    def mesh(mi):
        n = nodes[mi]; sk = g["skins"][n["skin"]]
        P, J, W, T, tris, off = [], [], [], [], [], 0
        for p in g["meshes"][n["mesh"]]["primitives"]:
            a = p["attributes"]; pp = acc(a["POSITION"]).astype(float)
            P.append(pp); J.append(acc(a["JOINTS_0"]).astype(int)); W.append(acc(a["WEIGHTS_0"]).astype(float))
            idx = acc(p["indices"]).reshape(-1).astype(int) if "indices" in p else np.arange(len(pp))
            tris.append(idx.reshape(-1, 3) + off); off += len(pp)
            T.append([acc(t["POSITION"]).astype(np.float32) for t in p.get("targets", [])])
        W = np.concatenate(W); W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
        tg = np.stack([np.concatenate([T[k][j] for k in range(len(T))]) for j in range(len(T[0]))]) if T[0] else None
        ibm = acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(float)
        return dict(node=mi, name=n.get("name", ""), P=np.concatenate(P), J=np.concatenate(J), W=W, tris=np.concatenate(tris),
                    targets=tg, joints=sk["joints"], ibm=ibm, jnames=[nodes[j].get("name", str(j)) for j in sk["joints"]])
    sk_nodes = [i for i, n in enumerate(nodes) if "skin" in n and "mesh" in n]
    rub = [i for i in sk_nodes if "rubble" in nodes[i].get("name", "").lower()]
    main = max((i for i in sk_nodes if i not in rub),
               key=lambda i: sum(g["accessors"][p["attributes"]["POSITION"]]["count"] for p in g["meshes"][nodes[i]["mesh"]]["primitives"]))
    M = mesh(main); R = [mesh(i) for i in rub]

    def sample(an, t):
        cur = {i: list(v) for i, v in rest.items()}; mw = {}
        for ch in an["channels"]:
            tgt = ch["target"]; s = an["samplers"][ch["sampler"]]
            ti = acc(s["input"])[:, 0].astype(float); vo = acc(s["output"]).astype(float)
            if tgt["path"] == "weights":
                vo = vo.reshape(len(ti), -1)
            k = int(np.searchsorted(ti, t + 1e-6, side="right")) - 1
            if k < 0:
                v = vo[0]
            elif k >= len(ti) - 1 or s.get("interpolation") == "STEP":
                v = vo[min(k, len(vo) - 1)]
            else:
                u = (t - ti[k]) / max(ti[k + 1] - ti[k], 1e-9); a0, a1 = vo[k], vo[k + 1]
                if tgt["path"] == "rotation" and np.dot(a0, a1) < 0:
                    a1 = -a1
                v = a0 * (1 - u) + a1 * u
                if tgt["path"] == "rotation":
                    v = v / np.linalg.norm(v)
            if tgt["path"] == "weights":
                mw[tgt["node"]] = v
            else:
                cur[tgt["node"]][{"translation": 0, "rotation": 1, "scale": 2}[tgt["path"]]] = v
        G = {}
        for i in order:
            L = A.trs(*cur[i]); G[i] = G[parent[i]] @ L if i in parent else L
        return G, mw

    def skin(m, G, mw):
        P = m["P"]
        w = mw.get(m["node"])
        if w is not None and m["targets"] is not None:
            nz = np.nonzero(np.abs(w) > 1e-6)[0]
            if len(nz):
                P = P + np.tensordot(w[nz], m["targets"][nz], axes=1)
        Ph = np.c_[P, np.ones(len(P))]
        Mx = np.stack([G[j] @ m["ibm"][k] for k, j in enumerate(m["joints"])])
        V = np.zeros((len(P), 3))
        for c in range(m["J"].shape[1]):
            V += m["W"][:, c:c + 1] * np.einsum("nij,nj->ni", Mx[m["J"][:, c]], Ph)[:, :3]
        return V

    clips = {}
    for an in g["animations"]:
        if not an["name"].startswith("Unit_"):
            continue
        times = sorted({round(float(x), 5) for ch in an["channels"] for x in acc(an["samplers"][ch["sampler"]]["input"])[:, 0]})
        clips[an["name"][5:]] = (an, times)
    # bind pose = the mesh's own POSITION data (the inverse bind matrices define it)
    return dict(g=g, main=M, rubble=R, clips=clips, sample=sample, skin=skin)


def pieces(M, weld=1e-5):
    """geometric components (weld by position) and skin pieces (weld by position + identical weights)."""
    P, tris = M["P"], M["tris"]
    q = np.round(P / weld).astype(np.int64)
    _, wid = np.unique(q, axis=0, return_inverse=True); wid = wid.reshape(-1)
    nb = len(M["jnames"])
    dense = np.zeros((len(P), nb)); np.add.at(dense, (np.repeat(np.arange(len(P)), M["J"].shape[1]), M["J"].reshape(-1)), M["W"].reshape(-1))
    key = np.c_[q, np.round(dense * 50).astype(np.int64)]
    _, sid = np.unique(key, axis=0, return_inverse=True); sid = sid.reshape(-1)
    e = np.r_[tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]
    geo = _components(wid.max() + 1, wid[e[:, 0]], wid[e[:, 1]])[wid]
    skn = _components(sid.max() + 1, sid[e[:, 0]], sid[e[:, 1]])[sid]
    return geo, skn, dense, wid


def other_gap(V, lab, only=None, k=16):
    """per label: min distance from its vertices to any vertex with a different label; also the index
    pair (vertex in piece, nearest outside vertex) that realises it. `only`: labels to measure."""
    tree = cKDTree(V)
    kk = min(k, len(V))
    d, j = tree.query(V, k=kk)
    diff = lab[j] != lab[:, None]
    dd = np.where(diff, d, np.inf)
    col = dd.argmin(1); best = dd[np.arange(len(V)), col]; nbr = j[np.arange(len(V)), col]
    labs = np.unique(lab) if only is None else only
    out = {}
    order = np.argsort(lab, kind="stable"); sl = lab[order]
    for L in labs:
        a, b = np.searchsorted(sl, L), np.searchsorted(sl, L, side="right")
        idx = order[a:b]
        if not len(idx):
            continue
        m = int(np.argmin(best[idx]))
        if np.isfinite(best[idx][m]):
            out[L] = (float(best[idx][m]), int(idx[m]), int(nbr[idx][m]))
        else:                                        # every neighbour was its own: exact complement query
            rest_idx = np.nonzero(lab != L)[0]
            if not len(rest_idx):
                continue
            t2 = cKDTree(V[rest_idx]); d2, j2 = t2.query(V[idx])
            m = int(np.argmin(d2)); out[L] = (float(d2[m]), int(idx[m]), int(rest_idx[j2[m]]))
    return out


def detached(V, lab, main, link):
    """per label: gap from its proximity group to all other geometry (0 when chained to the main body).
    Labels whose vertices come within `link` of each other are chained into one group, so a crest
    made of many shards that leaves the body together is one detached group, not many touching shards."""
    n = int(lab.max()) + 1
    pr = cKDTree(V).query_pairs(link, output_type="ndarray")
    a, b = lab[pr[:, 0]], lab[pr[:, 1]]; m = a != b
    comp = _components(n, a[m], b[m])
    vc = comp[lab]; inm = vc == comp[main]
    gap = np.zeros(n); near = np.full(n, -1)
    # a detached group's gap is its nearest approach to ANY geometry outside it (a toe chip next to
    # a foot that is itself detached measures to the foot, not to the far-away body)
    for c in np.unique(vc[~inm]):
        gi = np.nonzero(vc == c)[0]; oi = np.nonzero(vc != c)[0]
        d, j = cKDTree(V[oi]).query(V[gi])
        m = int(np.argmin(d)); pl = np.unique(lab[gi])
        gap[pl] = float(d[m]); near[pl] = int(oi[j[m]])
    return gap, near, comp


def dominant(dense, jn, idx):
    s = dense[idx].sum(0)
    return jn[int(s.argmax())]


def severity(frac):
    for name, t in SEV:
        if frac >= t:
            return name
    return None


def fix_point(P, idx):
    """a vertex of the piece (nearest its centroid) in Blender coordinates (Z up), for ext/floater_fix.py."""
    c = P[idx].mean(0); v = P[idx[np.argmin(np.linalg.norm(P[idx] - c, axis=1))]]
    return [round(float(v[0]), 5), round(float(-v[2]), 5), round(float(v[1]), 5)]


def fix_class(rec, kind):
    """proposed fix class for one finding (the handoff groups by these)."""
    if kind == "rest":
        if rec["bone"] == "neutral_bone":
            return "weightfill"
        return "deleteIsland" if rec["diagFrac"] < 0.25 else "reportProp"
    if rec["bone"] == "neutral_bone":
        return "weightfill"
    if rec["sitsOn"] == "neutral_bone":
        return "afterWeightfill"
    if rec["weldedVerts"] <= 60 and rec["diag"] / rec["_size"] < 0.25:
        return "reweightToSurface"
    return "structural"


def unit_cfg(unit):
    p = os.path.join(UNITS, unit + ".json")
    return json.load(open(p)) if os.path.exists(p) else {}


def prop_bones(cfg):
    """bones that hooks add for free-moving props (propBones, flail)."""
    b = {p.get("name") for p in cfg.get("propBones", [])}
    if "flail" in cfg:
        b |= {"Flail", "FlailBall", "Ball", "Chain"}
    return {x for x in b if x}


def in_prop(cfg, name, Pb):
    """vertices (bind positions, glTF Y-up) inside a named config prop region (sphere/box only)."""
    for p in cfg.get("props", []):
        if p.get("name") != name:
            continue
        Z = np.c_[Pb[:, 0], -Pb[:, 2], Pb[:, 1]]      # to Blender Z-up
        if "sphere" in p:
            c, r = p["sphere"]; return np.linalg.norm(Z - np.array(c), axis=1) <= r * 1.2
        if "box" in p:
            lo, hi = np.array(p["box"]); return np.all((Z >= lo) & (Z <= hi), axis=1)
    return np.zeros(len(Pb), bool)


def scan(unit, keep=None):
    path = os.path.join(A.ART, unit, f"{unit}_def_retarget.glb")
    U = load_unit(path)
    M = U["main"]; P = M["P"]; jn = M["jnames"]
    cfg = unit_cfg(unit)
    size = float(np.ptp(P, axis=0).max())
    geo, skn, dense, wid = pieces(M)
    link = 0.01 * size
    res = {"unit": unit, "size": round(size, 4), "verts": int(len(P)), "geoPieces": int(geo.max() + 1),
           "skinPieces": int(skn.max() + 1), "rest": [], "motion": [], "rubble": [], "sinks": []}
    # vertices the exporter parked on "neutral_bone" (no deform weight in Blender): frozen at rest
    nb_ = [k for k, nm in enumerate(jn) if nm == "neutral_bone"]
    res["unweighted"] = int((dense[:, nb_].sum(1) > 0.5).sum()) if nb_ else 0

    # ---- 1. rest floaters (source mesh) ----
    tree = cKDTree(P)
    pr = tree.query_pairs(link, output_type="ndarray")
    pr = pr[geo[pr[:, 0]] != geo[pr[:, 1]]]
    ng = geo.max() + 1
    cl = _components(ng, geo[pr[:, 0]], geo[pr[:, 1]]) if len(pr) else np.arange(ng)
    vcl = cl[geo]
    body = np.bincount(vcl).argmax()
    gaps = other_gap(P, vcl, only=[c for c in np.unique(vcl) if c != body])
    for c, (gap, vi, vj) in gaps.items():
        idx = np.nonzero(vcl == c)[0]
        diag = float(np.linalg.norm(np.ptp(P[idx], axis=0)))
        nw = len(np.unique(wid[idx]))
        frac = gap / size
        sev = severity(frac)
        if sev is None and nw <= 12 and frac >= 0.004:
            sev = "low"                                   # tiny debris just off the surface
        if sev is None:
            continue
        res["rest"].append({"cluster": int(c), "verts": int(len(idx)), "weldedVerts": int(nw), "diag": round(diag, 4),
                            "diagFrac": round(diag / size, 4), "gap": round(gap, 4), "gapFrac": round(frac, 4),
                            "gapOverDiag": round(gap / max(diag, 1e-9), 2), "severity": sev,
                            "bone": dominant(dense, jn, idx), "nearBone": jn[int(dense[vj].argmax())],
                            "center": np.round(P[idx].mean(0), 3).tolist(), "fixPoint": fix_point(P, idx),
                            "vertIdx": idx.tolist() if keep is not None else None})
        res["rest"][-1]["fix"] = fix_class(res["rest"][-1], "rest")

    # ---- 2. motion floaters (rig/weights) ----
    main_piece = int(np.bincount(skn).argmax())
    g0, n0, _ = detached(P, skn, main_piece, link)
    pidx = {L: np.nonzero(skn == L)[0] for L in np.unique(skn)}
    best = {}                                            # piece -> worst (open, clip, frame, gap, near, members)
    ground = None; grounded = cfg.get("grounding", True) is not False
    frames_keep = {}
    clip_order = sorted(U["clips"], key=lambda c: (c != "Idle", c))
    for clip in clip_order:
        an, times = U["clips"][clip]
        Vs = []
        for fi, t in enumerate(times):
            G, mw = U["sample"](an, t)
            V = U["skin"](M, G, mw)
            Vs.append(V)
            if clip == "Idle" and fi == 0:
                ground = float(V[:, 1].min())
            gf, nf, cf = detached(V, skn, main_piece, link)
            op = gf - g0
            for L in np.nonzero(op > 0.004 * size)[0]:
                if L not in best or op[L] > best[L][0]:
                    best[L] = (float(op[L]), clip, fi, float(gf[L]), int(nf[L]), np.nonzero(cf == cf[L])[0])
            if grounded and ground is not None and clip != "Death":
                low = V[:, 1] < ground - 0.03 * size
                if low.any():
                    sl = np.unique(skn[low])
                    for L in sl:
                        dep = float(ground - V[skn == L, 1].min())
                        res["sinks"].append((int(L), clip, fi, round(dep / size, 3)))
            for R in U["rubble"]:
                if clip != "Death":
                    VR = U["skin"](R, G, mw)
                    ext = float(np.ptp(VR, axis=0).max())
                    if ext > 0.01 * size:
                        res["rubble"].append({"clip": clip, "frame": fi, "extentFrac": round(ext / size, 3)})
        if keep is not None:
            frames_keep[clip] = Vs
    # collapse sinks to the worst per piece
    sk = {}
    for L, clip, fi, dep in res["sinks"]:
        if L not in sk or dep > sk[L][2]:
            sk[L] = (clip, fi, dep)
    res["sinks"] = [{"piece": L, "clip": c, "frame": f, "depthFrac": d, "verts": int(len(pidx.get(L, np.nonzero(skn == L)[0]))),
                     "bone": dominant(dense, jn, np.nonzero(skn == L)[0])} for L, (c, f, d) in sorted(sk.items(), key=lambda x: -x[1][2])]
    # collapse rubble to worst per clip
    rb = {}
    for r in res["rubble"]:
        if r["clip"] not in rb or r["extentFrac"] > rb[r["clip"]]["extentFrac"]:
            rb[r["clip"]] = r
    res["rubble"] = list(rb.values())

    pbones = prop_bones(cfg)
    free_death = [k for k in FREE_DEATH if k in cfg]
    wl = WHITELIST.get(unit, [])
    wl_mask = np.zeros(len(P), bool)
    for w in wl:
        for pn in w.get("props", []):
            wl_mask |= in_prop(cfg, pn, P)
    covered = set()
    for L, (op, clip, fi, gap, vj, members) in sorted(best.items(), key=lambda x: -x[1][0]):
        if L in covered:
            continue
        members = [int(x) for x in members if x != main_piece] or [int(L)]   # the whole detached group
        covered.update(members)
        idx = np.concatenate([pidx[x] for x in members])
        frac = op / size
        sev = severity(frac)
        nw = len(np.unique(wid[idx]))
        if sev is None and nw <= 12 and frac >= 0.008:
            sev = "low"
        if sev is None:
            continue
        diagf = float(np.linalg.norm(np.ptp(P[idx], axis=0))) / size
        if diagf < 0.02 and sev in ("high", "medium"):     # a sliver: visible, but a speck
            sev = {"high": "medium", "medium": "low"}[sev]
        bone = dominant(dense, jn, idx)
        gpiece = np.unique(geo[idx])
        own_geo = np.all(np.isin(np.nonzero(np.isin(geo, gpiece))[0], idx))
        oth = np.nonzero(~np.isin(skn, members))[0]            # the surface it sat on at bind
        dd, jj = cKDTree(P[oth]).query(P[idx]); vj = int(oth[jj[dd.argmin()]])
        rec = {"piece": int(L), "pieces": len(members), "verts": int(len(idx)), "weldedVerts": int(nw),
               "diag": round(float(np.linalg.norm(np.ptp(P[idx], axis=0))), 4), "clip": clip, "frame": fi,
               "restGap": round(float(g0[L]), 4), "gap": round(gap, 4), "open": round(op, 4), "openFrac": round(frac, 4), "score": round(frac * min(1.0, max(0.3, diagf / 0.05)), 4),
               "severity": sev, "bone": bone, "sitsOn": jn[int(dense[vj].argmax())],
               "kind": "meshPiece" if own_geo else "cutRegion",
               "rigid": bool(np.all(dense[idx].max(1) > 0.999)),
               "center": np.round(P[idx].mean(0), 3).tolist(), "fixPoint": fix_point(P, idx),
               "vertIdx": idx.tolist() if keep is not None else None, "_size": size}
        rec["fix"] = fix_class(rec, "motion"); del rec["_size"]
        why = None
        if clip == "Death" and free_death:
            why = f"Death comes apart by config ({', '.join(free_death)})"
        elif bone in pbones:
            why = f"bone {bone} is a hook-added free prop bone (propBones/flail)"
        elif wl_mask[idx].mean() > 0.5:
            why = next(w["reason"] for w in wl)
        if why:
            rec["whitelist"] = why
        res["motion"].append(rec)
    for r in res["rest"]:
        idx = np.nonzero(vcl == r["cluster"])[0]
        if wl_mask[idx].mean() > 0.5:
            r["whitelist"] = next(w["reason"] for w in wl)
    res["motion"].sort(key=lambda r: -r["score"]); res["rest"].sort(key=lambda r: -r["gapFrac"])
    if keep is not None:
        keep.update(frames=frames_keep, P=P, skn=skn, vcl=vcl, size=size)
    return res


# ---------------- evidence images ----------------
def _panel(V, flag, box, cell, axes, depth_axis, flip_depth):
    from PIL import Image
    lo, hi = box
    sc = (cell - 12) / max(float((hi - lo).max()), 1e-9)
    c = (lo + hi) / 2
    p = (V[:, axes] - c) * sc + cell / 2
    x = p[:, 0].astype(int); y = (cell - 1 - p[:, 1]).astype(int)
    dep = V[:, depth_axis] * (-1 if flip_depth else 1)
    im = np.full((cell, cell, 3), 28, np.uint8)
    dn = (dep - dep.min()) / max(np.ptp(dep), 1e-9)
    col = np.stack([90 + 120 * dn] * 3, 1).astype(np.uint8)
    col[flag] = (255, 0, 220)
    order = np.argsort(dep + flag * 1e6)             # flagged drawn last so it is never hidden
    ok = (x >= 0) & (x < cell) & (y >= 0) & (y < cell)
    o = order[ok[order]]
    for dx in (0, 1):
        for dy in (0, 1):
            xx, yy = np.clip(x[o] + dx, 0, cell - 1), np.clip(y[o] + dy, 0, cell - 1)
            im[yy, xx] = col[o]
    f = np.nonzero(flag & ok)[0]
    for dx in range(-2, 3):                            # flagged points drawn 5x5 on top
        for dy in range(-2, 3):
            im[np.clip(y[f] + dy, 0, cell - 1), np.clip(x[f] + dx, 0, cell - 1)] = (255, 0, 220)
    out = Image.fromarray(im)
    if len(f):
        from PIL import ImageDraw
        cx, cy = float(x[f].mean()), float(y[f].mean()); r = max(10.0, float(np.ptp(x[f]) + np.ptp(y[f])) / 2 + 8)
        ImageDraw.Draw(out).ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 230, 0))
    return out


def evidence(unit, rec, keep, kind, out):
    """rest pose | worst frame, each full body + a crop around the flagged piece, side and front views."""
    from PIL import Image, ImageDraw
    P, size = keep["P"], keep["size"]
    if kind == "rest":
        idx = np.array(rec["vertIdx"]); frames = [("bind", P)]
        clip = rec.get("clip") or "Idle"
        if clip in keep["frames"]:
            frames.append((f"{clip} f0", keep["frames"][clip][0]))
    else:
        idx = np.array(rec["vertIdx"]); fr = keep["frames"][rec["clip"]]
        frames = [("bind", P), (f"{rec['clip']} f{rec['frame']}", fr[rec["frame"]])]
    flag = np.zeros(len(P), bool); flag[idx] = True
    cell = 260
    cols = []
    for label, V in frames:
        pc = V[idx].mean(0); r = max(float(np.linalg.norm(np.ptp(V[idx], axis=0))), 0.12 * size)
        near = np.linalg.norm(V - pc, axis=1) < 1.6 * r
        crop = (V[near].min(0), V[near].max(0))
        full = (V.min(0), V.max(0))
        tiles = []
        for axes, da, fl in (((2, 1), 0, False), ((0, 1), 2, True)):
            b = lambda bx: (bx[0][list(axes)], bx[1][list(axes)])
            tiles += [_panel(V, flag, b(full), cell, list(axes), da, fl), _panel(V, flag, b(crop), cell, list(axes), da, fl)]
        cols.append((label, tiles))
    im = Image.new("RGB", (cell * 4, cell * len(cols) + 16 * len(cols)), (20, 20, 20))
    d = ImageDraw.Draw(im)
    for r, (label, tiles) in enumerate(cols):
        y = r * (cell + 16)
        info = (f"gap {rec['gapFrac']:.1%} of size" if kind == "rest" else
                f"opens {rec['openFrac']:.1%} of size, {rec['bone']} on {rec['sitsOn']}")
        d.text((4, y + 2), f"{unit} {kind} {label} [{info}]: side full | side crop | front full | front crop (magenta = flagged)", fill=(255, 255, 0))
        for k, t in enumerate(tiles):
            im.paste(t, (k * cell, y + 16))
    im.save(out)
    return out


def main():
    args = sys.argv[1:]
    jo = None; images = "--images" in args
    args = [a for a in args if a != "--images"]
    if "--json" in args:
        i = args.index("--json"); jo = args[i + 1]; args = args[:i] + args[i + 2:]
    units = args or sorted(d for d in os.listdir(A.ART) if os.path.exists(os.path.join(A.ART, d, f"{d}_def_retarget.glb"))
                           and os.path.exists(os.path.join(UNITS, d + ".json")))   # skips side-by-side copies
    os.makedirs(os.path.join(OUTDIR, "img"), exist_ok=True)
    allres = {}
    for u in units:
        keep = {} if images else None
        try:
            r = scan(u, keep)
        except Exception as e:
            import traceback; traceback.print_exc()
            allres[u] = {"error": repr(e)}; print(u, "ERROR", repr(e), flush=True); continue
        if images:
            for kind in ("rest", "motion"):
                for n, rec in enumerate(x for x in r[kind] if x["severity"] in ("high", "medium") and not x.get("whitelist")):
                    if n >= 4:
                        break
                    tag = rec.get("clip", "rest") if kind == "motion" else "rest"
                    rec["image"] = evidence(u, rec, keep, kind, os.path.join(OUTDIR, "img", f"{u}_{kind}{n}_{tag}.png"))
        for kind in ("rest", "motion"):
            for rec in r[kind]:
                rec.pop("vertIdx", None)
        json.dump(r, open(os.path.join(OUTDIR, f"{u}.json"), "w"), indent=1)
        allres[u] = r
        cnt = lambda k: {s: sum(1 for x in r[k] if x["severity"] == s and not x.get("whitelist")) for s, _ in SEV}
        print(u, "rest", cnt("rest"), "motion", cnt("motion"), "rubble", len(r["rubble"]), "sinks", len(r["sinks"]), flush=True)
    if jo:
        json.dump(allres, open(jo, "w"), indent=1)


if __name__ == "__main__":
    main()
