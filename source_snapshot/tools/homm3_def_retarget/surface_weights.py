"""Restrict bone-heat weights to bones that are close along the mesh surface.

Heat weighting is volumetric, so a sleeve hanging over the robe inherits thigh weight and
the robe inherits forearm weight. Along the surface those layers only meet at the shoulder,
so a bone may keep weight on a vertex only if its geodesic distance is within MARGIN of the
closest bone's.
"""
import sys, numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
import json
# usage: surface_weights.py <heat.npz> <weights.npz> <unit.json> [geodesic margin; default off]
src, dst = sys.argv[1], sys.argv[2]
cfg = json.load(open(sys.argv[3]))
MARGIN = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
d = np.load(src); P, E, H, SEG, names = d["P"], d["E"], d["H"], d["SEG"], list(d["names"])
n, B = H.shape
L = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1) + 1e-9
G = coo_matrix((np.r_[L, L], (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(n, n)).tocsr()

def seg_dist(P, a, b):
    ab = b - a; t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
D = np.stack([seg_dist(P, s[0], s[1]) for s in SEG], 1)
near = D.argmin(1)
geo = np.full((n, B), np.inf)
for b in range(B):
    mine = np.nonzero(near == b)[0]
    if len(mine) == 0:
        mine = np.array([D[:, b].argmin()])
    seeds = mine[D[mine, b] <= D[mine, b].min() + 0.02]
    geo[:, b] = dijkstra(G, indices=seeds, min_only=True)
# A welded component that holds none of the global seeds is unreachable along the surface (every geo inf), and the
# heat-lost fallback below then computes inf - inf = NaN for it: build_unit's `row > 1e-4` is False for NaN, so those
# vertices export unweighted, to glTF's neutral_bone, and stand still (h3_leprechaun: 131 of 2231 rows, 243 exported
# chest vertices; h3_automaton_upg_alt: 1378 of 2251). Rule (2026-09-28): the unreached vertices that also have no
# heat (the ones that would go NaN) take surface distances seeded inside their own component, by the same
# nearest-bone-segment rule restricted to its vertices: each bone that is the Euclidean-nearest segment of some of
# them seeds at those within 0.02 of their closest. An unreached vertex that has heat keeps its heat row as before.
from scipy.sparse.csgraph import connected_components
ncomp, comp = connected_components(G, directed=False)
unreached = ~np.isfinite(geo).any(1)
nan_rows = unreached & (H.sum(1) <= 1e-6)
for c in np.unique(comp[nan_rows]):
    cv = np.nonzero(comp == c)[0]
    fix = cv[nan_rows[cv]]
    seeded = []
    for b in np.unique(near[cv]):
        mine = cv[near[cv] == b]
        seeds = mine[D[mine, b] <= D[mine, b].min() + 0.02]
        geo[fix, b] = dijkstra(G, indices=seeds, min_only=True)[fix]
        seeded.append(str(names[b]))
    print(f"surface-unreached heatless vertices: component {c} ({len(cv)} vertices), {len(fix)} seeded by nearest "
          f"bone segment: {seeded}")
bad = nan_rows & ~np.isfinite(geo).any(1)
if bad.any():
    raise SystemExit(f"surface_weights: {int(bad.sum())} vertices in components {sorted(set(comp[bad].tolist()))} "
                     "have no finite surface distance to any bone after component seeding")
gmin = geo.min(1, keepdims=True)
allowed = geo <= gmin + MARGIN
W = H * allowed
lost = W.sum(1) <= 1e-6
W[lost] = (np.exp(-((geo[lost] - gmin[lost]) / 0.05) ** 2) * allowed[lost])
A = G.copy(); A.data[:] = 1.0
deg = np.asarray(A.sum(1)).ravel() + 1
for _ in range(3):
    W = ((A @ W) + W) / deg[:, None]
    W *= allowed
# robe skirt: the legs are hidden inside a bell of cloth, so above the boots the robe keeps only
# a share of the thigh/shin motion and hands the rest to the hips
SKIRT_K = cfg.get("skirtLegShare", 1.0); BOOT = cfg.get("bootTop", 0.0)
z = P[:, 2]
k = np.clip((z - BOOT) / 0.10, 0, 1) * (1 - SKIRT_K)   # 0 at boots, 1-SKIRT_K on the robe
hips = names.index("Hips")
for nm in [m for m in ("LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg") if m in names]:
    b = names.index(nm); moved = W[:, b] * k; W[:, b] -= moved; W[:, hips] += moved
# sleeves: the wide sleeves hang from the elbows to thigh height and are fused to the robe, so
# heat splits them between arm, spine and thigh. Outside the torso profile they belong to the arm.
x = P[:, 0]
CUT = True
WS = np.zeros_like(W); SL = np.zeros(n, bool)
SLEEVE = cfg.get("sleeve")
if SLEEVE:
    SX, SZ0, SZ1 = SLEEVE["x"], SLEEVE["zMin"], SLEEVE["zMax"]
for side, sgn in ((("Left", 1), ("Right", -1)) if SLEEVE else ()):
    ids = [names.index(side + b) for b in ("Arm", "ForeArm", "Hand")]
    dd = np.stack([seg_dist(P, SEG[i][0], SEG[i][1]) for i in ids], 1)
    aw = 1.0 / np.maximum(dd, 0.02) ** 4; aw /= aw.sum(1, keepdims=True)
    alpha = np.clip((sgn * x - SX) / 0.04, 0, 1) * np.clip((SZ1 - z) / 0.06, 0, 1) * np.clip((z - SZ0) / 0.04, 0, 1)
    if CUT:
        WS[:, ids] = np.where((alpha > 0.5)[:, None], aw, WS[:, ids]); SL |= alpha > 0.5
    else:
        arm_row = np.zeros_like(W); arm_row[:, ids] = aw
        W = W * (1 - alpha[:, None]) + arm_row * alpha[:, None]
# spatial smoothing: Meshy stacks cloth layers millimetres apart (inner/outer robe) and heat gives
# them different weights, so the inner layer pokes through the outer as shards. Averaging weights
# over a small 3D ball (not along the surface) makes nearby layers move together.
SS = cfg.get("spatialSmooth")
if SS:
    from scipy.spatial import cKDTree
    from scipy.sparse import csr_matrix
    pairs = cKDTree(P).query_pairs(SS.get("radius", 0.035), output_type="ndarray")
    M = csr_matrix((np.ones(len(pairs) * 2), (np.r_[pairs[:, 0], pairs[:, 1]], np.r_[pairs[:, 1], pairs[:, 0]])), shape=(n, n))
    dg_ = np.asarray(M.sum(1)).ravel() + 1
    for _ in range(SS.get("passes", 2)):
        W = ((M @ W) + W) / dg_[:, None]
    print("spatial smooth pairs", len(pairs))
# final surface smoothing of the whole field: heat on these fused Meshy surfaces is noisy from one
# vertex to the next, which tears triangles into shards when limbs move apart
for _ in range(cfg.get("smoothPasses", 0)):
    W = ((A @ W) + W) / deg[:, None]
# chest-panel surgery (tools/homm3_def_retarget/chest_panel): the forearm+hand block was cut free of the torso and the
# torso front rebuilt 1 cm behind it, so heat hands that panel to the forearms. Only the arm block's own vertices
# (the record's armFaceIdx, matched by position) and the elbow (within elbowRadius of the ForeArm head) may carry
# ForeArm/Hand weight; elsewhere it goes back to the nearest non-arm bone segments.
AP = cfg.get("armPart")
if AP:
    from scipy.spatial import cKDTree
    import os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _rec = json.load(open(os.path.join(_root, AP["record"])))
    sys.path.insert(0, os.path.join(_root, "tools", "homm3_def_retarget_delivery"))
    from stride_match_glb import Glb as _G
    _g = _G.load(os.path.join(_root, AP["mesh"])); _pr = _g.json["meshes"][0]["primitives"][0]
    _V = _g.read(_pr["attributes"]["POSITION"]).astype(float); _F = _g.read(_pr["indices"]).astype(int).reshape(-1, 3)
    _av = _V[np.unique(_F[_rec["armFaceIdx"]].ravel())]
    _av = np.c_[_av[:, 0], -_av[:, 2], _av[:, 1]]          # glTF Y-up -> Blender Z-up
    _d, _ = cKDTree(_av).query(P)
    armv = _d < 1e-5
    er = AP.get("elbowRadius", 0.07)
    ab = AP.get("bones", ["ForeArm", "Hand"]); kj = AP.get("keepJoint", "ForeArm")   # Arm/Arm: whole sleeve freed
    for side in ("Left", "Right"):
        fa = names.index(side + kj)
        elbow = np.linalg.norm(P - SEG[fa][0], axis=1) < er
        cols = [names.index(side + b) for b in ab if side + b in names]
        strip = ~armv & ~elbow & (W[:, cols].sum(1) > 0)
        W[np.ix_(strip, cols)] = 0
        print("arm part", side, "stripped", int(strip.sum()))
    # each separately capped arm block (connected over position-welded arm faces) follows ONE side's ForeArm/Hand:
    # heat leaks the other forearm's weight into a hand tucked in the opposite sleeve, which tears once the arms part
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    _AF = _F[_rec["armFaceIdx"]]
    _k = np.unique(np.round(_V, 6), axis=0, return_inverse=True)[1].ravel()[_AF]
    _E = np.concatenate([_k[:, [0, 1]], _k[:, [1, 2]]]); _nk = _k.max() + 1
    _nc, _lab = connected_components(coo_matrix((np.ones(len(_E)), (_E[:, 0], _E[:, 1])), shape=(_nk, _nk)), directed=False)
    _kv = np.unique(_k.ravel()); _pv = np.zeros((_nk, 3)); _pv[_k.ravel()] = _V[_AF.ravel()]
    _pv = np.c_[_pv[:, 0], -_pv[:, 2], _pv[:, 1]]
    _dd, _ni = cKDTree(_pv[_kv]).query(P)
    comp = np.where(_dd < 1e-5, _lab[_kv][_ni], -1)
    sc = {s: [names.index(s + b) for b in ab if s + b in names] for s in ("Left", "Right")}
    for c in np.unique(comp[comp >= 0]):
        m = comp == c
        l, r_ = W[np.ix_(m, sc["Left"])].sum(), W[np.ix_(m, sc["Right"])].sum()
        lose = sc["Right"] if l >= r_ else sc["Left"]
        W[np.ix_(m, lose)] = 0
        keep = sc["Left"] if l >= r_ else sc["Right"]
        e = m & (W.sum(1) <= 1e-6)
        if e.any():
            ww = 1.0 / np.maximum(D[np.ix_(e, keep)], 0.02) ** 4; W[np.ix_(e, keep)] = ww / ww.sum(1, keepdims=True)
        print("arm part block", int(c), "vertices", int(m.sum()), "side", "Left" if l >= r_ else "Right", "share", round(max(l, r_) / max(l + r_, 1e-9), 3))
    # the rebuilt chest panel sits right behind the arm blocks, where heat comes out patchy (Spine1/Arm dominance
    # alternating triangle by triangle), which tears once the upper arms lift: Laplacian-smooth its weights over the
    # position-welded surface, the surrounding original robe held
    ps = int(AP.get("panelSmooth", 0))
    if ps and "panelFaceIdx" in _rec:
        _pp = _V[np.unique(_F[_rec["panelFaceIdx"]].ravel())]; _pp = np.c_[_pp[:, 0], -_pp[:, 2], _pp[:, 1]]
        pan = cKDTree(_pp).query(P)[0] < 1e-5
        kk = np.unique(np.round(P, 5), axis=0, return_inverse=True)[1].ravel(); ng = kk.max() + 1
        Wg = np.zeros((ng, W.shape[1])); np.add.at(Wg, kk, W); Wg /= np.bincount(kk, minlength=ng)[:, None]
        pg = np.zeros(ng, bool); pg[kk[pan]] = True
        strip_b = [names.index(x) for x in AP.get("panelStrip", []) if x in names]
        if strip_b:      # the chest front follows the spine; arm weight only blends in from the original sleeve border
            Wg[np.ix_(pg, strip_b)] = 0
            z = pg & (Wg.sum(1) <= 1e-6)
            sp_ = [i for i, nm in enumerate(names) if nm.startswith("Spine")]
            Wg[np.ix_(z, sp_)] = 1.0 / len(sp_)
            Wg[pg] /= Wg[pg].sum(1, keepdims=True)
        Ek = kk[E]; Ek = Ek[Ek[:, 0] != Ek[:, 1]]; Ek = np.concatenate([Ek, Ek[:, ::-1]])
        A_ = coo_matrix((np.ones(len(Ek)), (Ek[:, 0], Ek[:, 1])), shape=(ng, ng)).tocsr(); A_.data[:] = 1
        dg = np.maximum(np.asarray(A_.sum(1)).ravel(), 1)
        for _ in range(ps):
            Wg[pg] = 0.5 * Wg[pg] + 0.5 * (A_ @ Wg)[pg] / dg[pg, None]
        W = Wg[kk]
        print("arm part panel smoothed", int(pan.sum()), "vertices,", ps, "iterations")
    # a whole freed sleeve bends far from its folded rest at the elbow: heat's sharp, patchy Arm/ForeArm/Hand
    # transition inside the block tears there, so smooth the block's weights the same way (the shoulder weld held)
    asm = int(AP.get("armSmooth", 0))
    if asm:
        kk = np.unique(np.round(P, 5), axis=0, return_inverse=True)[1].ravel(); ng = kk.max() + 1
        Wg = np.zeros((ng, W.shape[1])); np.add.at(Wg, kk, W); Wg /= np.bincount(kk, minlength=ng)[:, None]
        ag = np.zeros(ng, bool); ag[kk[armv]] = True
        sh = np.zeros(ng, bool)
        for side in ("Left", "Right"):
            sh[kk[np.linalg.norm(P - SEG[names.index(side + kj)][0], axis=1) < er]] = True
        if AP.get("smoothShoulder"):     # blend the shoulder weld too (sharp Shoulder->Arm step tears on big lifts)
            ag |= sh
        else:
            ag &= ~sh
        Ek = kk[E]; Ek = Ek[Ek[:, 0] != Ek[:, 1]]; Ek = np.concatenate([Ek, Ek[:, ::-1]])
        A_ = coo_matrix((np.ones(len(Ek)), (Ek[:, 0], Ek[:, 1])), shape=(ng, ng)).tocsr(); A_.data[:] = 1
        dg = np.maximum(np.asarray(A_.sum(1)).ravel(), 1)
        for _ in range(asm):
            Wg[ag] = 0.5 * Wg[ag] + 0.5 * (A_ @ Wg)[ag] / dg[ag, None]
        W = Wg[kk]
        print("arm part blocks smoothed", int(ag.sum()), "welded vertices,", asm, "iterations")
    # diffuse: {"bones": [globs], "iterations": n}. Heat on the fused robe leaves a noisy Shoulder/Spine/Arm field
    # around the shoulder weld and the rebuilt chest that tears when both arms swing wide; Laplacian-diffuse every
    # vertex carrying > 0.01 of those bones over the position-welded surface (the patch lane's diffuseWeights rule)
    DF = AP.get("diffuse")
    if DF:
        import fnmatch
        sel = [i for i, nm in enumerate(names) if any(fnmatch.fnmatchcase(nm, g_) for g_ in DF["bones"])]
        kk = np.unique(np.round(P, 5), axis=0, return_inverse=True)[1].ravel(); ng = kk.max() + 1
        Wg = np.zeros((ng, W.shape[1])); np.add.at(Wg, kk, W); Wg /= np.bincount(kk, minlength=ng)[:, None]
        fg = Wg[:, sel].max(1) > 0.01
        Ek = kk[E]; Ek = Ek[Ek[:, 0] != Ek[:, 1]]; Ek = np.concatenate([Ek, Ek[:, ::-1]])
        A_ = coo_matrix((np.ones(len(Ek)), (Ek[:, 0], Ek[:, 1])), shape=(ng, ng)).tocsr(); A_.data[:] = 1
        dg = np.maximum(np.asarray(A_.sum(1)).ravel(), 1)
        for _ in range(int(DF.get("iterations", 50))):
            Wg[fg] = (A_ @ Wg)[fg] / dg[fg, None]
        W = Wg[kk]
        print("arm part diffused", int(fg.sum()), "welded vertices,", DF.get("iterations", 50), "iterations")
    # shortEdgeTie: one weight row per cluster of mesh edges shorter than this. The surgery fills leave a few
    # millimetre edges beside the shoulder weld; any weight step across one (0.05 of Arm) is a 5x+ stretch once the
    # arm swings up, the gate's worst edge. Tied rows move rigidly together, so those edges keep their length
    tie = float(AP.get("shortEdgeTie", 0))
    if tie:
        L_ = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
        Es = E[L_ < tie]
        nc_, lb_ = connected_components(coo_matrix((np.ones(len(Es)), (Es[:, 0], Es[:, 1])), shape=(n, n)), directed=False)
        cnt_ = np.bincount(lb_, minlength=nc_)
        Wm = np.zeros((nc_, W.shape[1])); np.add.at(Wm, lb_, W); Wm /= cnt_[:, None]
        tied = cnt_[lb_] > 1
        W[tied] = Wm[lb_[tied]]
        print("arm part short-edge tie <", tie, ":", len(Es), "edges,", int(tied.sum()), "vertices")
    other = [i for i, nm in enumerate(names) if not any(nm == sd + b for sd in ("Left", "Right") for b in ab)]
    empty = W.sum(1) <= 1e-6
    if empty.any():
        dd = D[np.ix_(empty, other)]; ww = 1.0 / np.maximum(dd, 0.02) ** 4
        W[np.ix_(empty, other)] = ww / ww.sum(1, keepdims=True)
    print("arm part vertices", int(armv.sum()), "refilled", int(empty.sum()))
idx = np.argsort(-W, 1)[:, 4:]
np.put_along_axis(W, idx, 0, 1)
W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
changed = (np.abs(W - H / np.maximum(H.sum(1, keepdims=True), 1e-9)).sum(1) > 0.2).sum()
print("vertices", n, "heat-lost", int(lost.sum()), "changed>0.2", int(changed))
for nm in [m for m in ["LeftForeArm", "RightForeArm", "LeftUpLeg", "RightUpLeg"] if m in names]:
    b = names.index(nm); print(nm, "heat verts", int((H[:, b] > 0.05).sum()), "->", int((W[:, b] > 0.05).sum()))
# snake tail (nagas): the body below the waist is ordered by distance *along the surface* from
# the waist, so loops of the coil that Meshy fused together still get separate bones. The
# centreline is the centroid of each distance band, resampled to equal arc length; each vertex
# blends the two tail bones nearest its own distance.
TAIL = cfg.get("tail")
TP = np.zeros((0, 3)); TW = np.zeros((n, 0), np.float32); TM = np.zeros(n, bool); TU = -np.ones(n)
if TAIL:
    hx, hy, hz = cfg["joints"]["Hips"]
    r = np.hypot(P[:, 0] - hx, P[:, 1] - hy)
    snake = (P[:, 2] < hz - TAIL.get("belowHips", 0.12)) | ((P[:, 2] < hz) & (r < TAIL.get("neckRadius", 0.2)))
    snake &= ~((P[:, 2] > TAIL.get("handsAboveZ", 0.45)) & (r > TAIL.get("handsRadius", 0.3)))
    # held swords that hang to the ground belong to the hands, not the tail
    armcols = [i for i, nm in enumerate(names) if any(k in nm for k in ("Shoulder", "Arm", "Hand"))]
    Hn = H / np.maximum(H.sum(1, keepdims=True), 1e-9)
    if TAIL.get("excludeNearHands"):
        # blades held low: anything within reach of a hand segment is not tail
        hand_ids = [i for i, nm in enumerate(names) if nm.endswith("Hand") or nm.endswith("ForeArm")]
        dh = np.min(np.stack([seg_dist(P, SEG[i][0], SEG[i][1]) for i in hand_ids], 1), 1)
        snake &= dh > TAIL["excludeNearHands"]
    if TAIL.get("excludeMetal") and "C" in d.files:
        # light, unsaturated texels (blades lying beside the coil) stay with the hands
        Cv = d["C"]; mx = Cv.max(1); sat = (mx - Cv.min(1)) / np.maximum(mx, 1e-6)
        snake &= ~((mx > TAIL.get("metalMinValue", 0.35)) & (sat < TAIL.get("metalMaxSat", 0.25)))
    if "maxArmHeat" in TAIL:
        snake &= Hn[:, armcols].sum(1) < TAIL["maxArmHeat"]
    sidx = np.nonzero(snake)[0]; smap = -np.ones(n, int); smap[sidx] = np.arange(len(sidx))
    keep = snake[E[:, 0]] & snake[E[:, 1]]
    se = smap[E[keep]]; sl = np.linalg.norm(P[E[keep, 0]] - P[E[keep, 1]], axis=1) + 1e-9
    SG = coo_matrix((np.r_[sl, sl], (np.r_[se[:, 0], se[:, 1]], np.r_[se[:, 1], se[:, 0]])), shape=(len(sidx),) * 2).tocsr()
    Q = P[sidx]
    # Meshy sometimes builds the coil as a separate shell from the snake's neck: bridge separate
    # pieces where their surfaces come within bridgeDist, so distance along the body carries on
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    nc, lab = connected_components(SG)
    if nc > 1:
        bd = TAIL.get("bridgeDist", 0.06); add = []
        for c in range(nc):
            mine = np.nonzero(lab == c)[0]; other = np.nonzero(lab != c)[0]
            if len(mine) == 0 or len(other) == 0:
                continue
            dd, nn = cKDTree(Q[other]).query(Q[mine])
            close = dd < bd
            add += [(a, other[b], d_) for a, b, d_ in zip(mine[close], nn[close], dd[close])]
        if add:
            a_, b_, d_ = map(np.array, zip(*add)); d_ = d_ + 1e-6
            SG = (SG + coo_matrix((np.r_[d_, d_], (np.r_[a_, b_], np.r_[b_, a_])), shape=SG.shape).tocsr()).tocsr()
        print("tail shells", nc, "bridges", len(add))
    # start at the top of the snake's neck, near the body axis (a coil can rise above hips - 0.2)
    rq = np.hypot(Q[:, 0] - hx, Q[:, 1] - hy); axial = rq < TAIL.get("neckRadius", 0.2)
    ztop = Q[axial, 2].max()
    src = np.nonzero(axial & (Q[:, 2] > ztop - 0.08))[0]
    dist = dijkstra(SG, indices=src, min_only=True)
    ok = np.isfinite(dist); dm = dist[ok].max()
    NT = TAIL.get("segments", 12)
    nb = 4 * NT; bins = np.minimum((np.where(ok, dist, 0) / dm * nb).astype(int), nb - 1)
    cen = np.array([Q[ok & (bins == k)].mean(0) for k in range(nb) if (ok & (bins == k)).any()])
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(cen, axis=0), axis=1))]
    TP = np.stack([np.interp(np.linspace(0, arc[-1], NT + 1), arc, cen[:, i]) for i in range(3)], 1)
    u = np.where(ok, dist, 0) / dm * NT
    # separate shells inside the snake body (belly plates) are not reached along the surface:
    # they take the position along the body of the nearest reached vertex
    if (~ok).any():
        from scipy.spatial import cKDTree
        _, nn = cKDTree(Q[ok]).query(Q[~ok])
        u[~ok] = u[ok][nn]; ok = np.ones_like(ok)
    # a thick tube's opposite sides sit up to a segment apart in surface distance, which shears
    # its cross-section when the tail unrolls: take each vertex's position along the body from its
    # projection onto the centreline, choosing only segments within 2 of its surface distance
    # (so loops of the coil that touch stay apart)
    up = u.copy(); rad = np.zeros(len(Q))
    for i in range(len(Q)):
        best = (1e9, u[i])
        for k in range(max(0, int(u[i]) - 2), min(NT, int(u[i]) + 3)):
            a, b = TP[k], TP[k + 1]; ab = b - a
            t_ = float(np.clip((Q[i] - a) @ ab / max(ab @ ab, 1e-12), 0, 1))
            dd = float(np.linalg.norm(Q[i] - (a + t_ * ab)))
            if dd < best[0]:
                best = (dd, k + t_)
        up[i] = best[1]; rad[i] = best[0]
    u = up
    # only the tube belongs to the tail: blades and hands resting on the coil sit far outside
    # the tube radius of their stretch of body and are handed back to the heat weights
    tube = np.array([np.median(rad[(u >= k) & (u < k + 1)]) if ((u >= k) & (u < k + 1)).any() else np.median(rad) for k in range(NT)])
    inside = rad <= TAIL.get("tubeFactor", 1.8) * tube[np.clip(u.astype(int), 0, NT - 1)] + 0.02
    ok &= inside
    print("tail tube outliers", int((~inside).sum()))
    TW = np.zeros((n, NT), np.float32)
    for k in range(NT):
        TW[sidx[ok], k] = np.maximum(0, 1 - np.abs(u[ok] - (k + 0.5)))
    TW[sidx] /= np.maximum(TW[sidx].sum(1, keepdims=True), 1e-9)
    TM[sidx[ok]] = True
    nonarm = [i for i, nm in enumerate(names) if not any(k in nm for k in ("Shoulder", "Arm", "Hand"))]
    ts_ = sidx[ok]
    Wn = np.zeros_like(W[ts_]); Wn[:, nonarm] = W[ts_][:, nonarm]
    Wn[Wn.sum(1) <= 1e-6, names.index("Hips")] = 1.0
    W[ts_] = Wn / Wn.sum(1, keepdims=True)
    TU[sidx[ok]] = u[ok]
    # low body vertices the mask missed (belly plates, fins, fused bits) follow the nearest tail
    # vertex unless they belong to a hand; anything left at the coil would stay behind as a sheet
    Hn2 = H / np.maximum(H.sum(1, keepdims=True), 1e-9)
    armc = [i for i, nm in enumerate(names) if any(k in nm for k in ("ForeArm", "Hand"))]
    armdom = Hn2[:, armc].sum(1) > 0.5
    # grow outward by proximity (a raised tail tip, fins, parts fused onto the coil), never into
    # the torso (near the body axis above the waist) or a hand
    from scipy.spatial import cKDTree
    rr_ = np.hypot(P[:, 0] - hx, P[:, 1] - hy)
    torso = (P[:, 2] > hz - 0.05) & (rr_ < TAIL.get("torsoRadius", 0.28))
    fill = np.zeros(n, bool)
    for _ in range(TAIL.get("growSteps", 12)):
        cand = ~TM & ~armdom & ~torso
        if not cand.any():
            break
        ti = np.nonzero(TM)[0]; dd, nn = cKDTree(P[ti]).query(P[cand])
        near = dd < TAIL.get("growDist", 0.05)
        if not near.any():
            break
        ci = np.nonzero(cand)[0][near]; src_ = ti[nn[near]]
        TW[ci] = TW[src_]; TU[ci] = TU[src_]; TM[ci] = True; fill[ci] = True
    if fill.any():
        fi = np.nonzero(fill)[0]
        Wf = np.zeros((len(fi), W.shape[1])); Wf[:, names.index("Hips")] = 1.0; W[fi] = Wf
    print("tail filled", int(fill.sum()))
    print("tail verts", int(TM.sum()), "reach", round(float(dm), 2), "segments", NT)
# forearms fused to the chest (genies' crossed arms): vertices whose nearest bone is a forearm or
# hand, within maxDist of it, are cut free and owned by that arm chain
AC = cfg.get("armCut")
if AC:
    nearest = D.argmin(1); dmin = D.min(1)
    for side in ("Left", "Right"):
        ids = [names.index(side + b) for b in ("ForeArm", "Hand") if side + b in names]
        if not ids:
            continue
        sel = np.isin(nearest, ids) & (dmin < AC.get("maxDist", 0.07)) & ~SL
        allids = [names.index(side + b) for b in ("Arm", "ForeArm", "Hand")]
        dd = np.stack([seg_dist(P, SEG[i][0], SEG[i][1]) for i in allids], 1)
        aw = 1.0 / np.maximum(dd, 0.02) ** 4; aw /= aw.sum(1, keepdims=True)
        WS[sel] = 0; WS[np.ix_(sel, allids)] = aw[sel]; SL |= sel
        print("arm cut", side, int(sel.sum()))
WS /= np.maximum(WS.sum(1, keepdims=True), 1e-9)
for nm_, arr in (("W", W), ("WS", WS), ("TW", TW)):
    rows_ = ~np.isfinite(arr).all(1)
    if rows_.any():
        raise SystemExit(f"surface_weights: {int(rows_.sum())} non-finite {nm_} rows (components "
                         f"{sorted(set(comp[rows_].tolist()))[:20]}); refusing to write {dst}")
np.savez(dst, W=W.astype(np.float32), WS=WS.astype(np.float32), SL=SL, TP=TP, TW=TW, TM=TM, TU=TU)
print("sleeve cut vertices", int(SL.sum()))
