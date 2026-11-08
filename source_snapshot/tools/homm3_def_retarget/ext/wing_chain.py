"""Articulated wing chains driven from the DEF (hook module for build_unit.py; list "wing_chain" in
"extensions", config key "wingChain").

Why: the `wings` block binds each wing rigidly to one bone that hinges at the shoulder and is
swung by the sprite's width. It never folds, and silhouetteRefine then fakes the wing beat by
rolling and bouncing the whole body (the "toy" motion, handoffs/articulation.md). This hook keeps
the `wings` block only for its region cut (set "wingMaxDeg": 0 and drop "wing"/"roll" from any
silhouetteRefine), and replaces the rigid bone with a chain of bones along the wing:

after_skin
  Every wing vertex the `wings` block bound to its bone is re-weighted onto a straight chain of
  `bones` bones (default 4: arm, forearm, hand, tip) from the shoulder (the wing bone's head) to
  the far end of the wing along the region's principal axis. A vertex is weighted by its projected
  position along the chain (two neighbouring bones, triangular blend, as fortress_rig chains), so
  the membrane bends smoothly across each joint. The rest chain is straight, so opening the wing
  is a rigid rotation of the whole panel and deformation comes only from real folds.

before_keys (all body poses final; the chain is recomputed from its parent bone every frame)
  Per wing, in the body's rest frame (X left, Y back, Z up), symmetric for both wings:
    open   0..1   slerp from the rest orientation to the spread orientation: the chain along
                  `spreadDir` (left wing; mirrored for the right) with the wing's dorsal face up;
    flap   deg    elevation about the body's long axis at the shoulder (+ = up);
    sweep  deg    about the vertical at the shoulder (+ = tip back);
    fold   deg    in-plane bend at the joints (+ = tip swept back toward the body), shared over
                  the joints by `foldShares` (the wrist takes most of it);
    droop  deg    out-of-plane bend at the joints (+ = tip down behind the inner wing), shares
                  `droopShares`;
    twist  deg    opt-in: rotation of the whole wing about its own rest arm axis (the first chain
                  segment; shoulder -> wrist for a finger fan) at the shoulder, applied before `open`,
                  right-handed about the outward axis for the left wing and mirrored for the right.
                  Turns a lowered membrane broadside to a profile camera. Only configs that key it in
                  "anim" or list it in fit.params get the channel; without it the pose and the
                  .wingchain.json are exactly as before;
    dx/dy  px     screen offset of the whole unit.
  Base values per clip come from "anim" ({clip|"*": {param: spec}}, specs as fortress_rig:
  {"sin": a, "cycles": c, "phase": deg, "offset": o} | {"keys": [[u, v], ...]} | number), read off
  the DEF frames. With "fit", each frame then searches offsets from those values that maximise
  silhouette IoU against the DEF frame under the sprite camera, penalised toward the base value
  and the previous frame. dx/dy are fitted in a first pass, then fixed per clip to the median
  plus at most `bounce` px per frame (a steady framing, not a rocking toy), and the wing is refitted.
  Params whose fitted value should never go below/above a bound are clamped by "limits".

Config (all optional except wings):
  "wingChain": {
    "wings": [{"bone": "LeftWing", "side": 1}, {"bone": "RightWing", "side": -1}],
        # bone: the `wings` block bone whose vertices become the chain; side +1 = +X (left)
        # optional per wing: "points": explicit chain points (else automatic), "dorsal": [x,y,z]
        # hint for the upper face (else away from the hips)
    "bones": 4, "ratios": [0, 0.3, 0.55, 0.78, 1.0],
    "spreadDir": [1, 0.25, 0.05], "spreadUp": [0, 0, 1],   # [lateral, tailward, dorsal] body axes
    "bodyAxis": [x, y, z],        # rest headward spine direction (default Hips -> Spine2)
    "foldShares": [0, 0.3, 0.7], "droopShares": [0, 0.4, 0.6],   # per joint 1..bones-1
    "fanDroopShares": [0.4, 0.6], "fanFold": 1.0,             # finger-fan wings only (below)
    "adoptWeights": "mean",       # "nearest": adopted loose pieces copy their nearest wing vertex's
                                  # weights per vertex (seam slivers stay welded to a folding wing)
    "anim": {...}, "limits": {"flap": [-70, 80], ...},
    "fit": {"params": ["flap", "open", "fold", "droop", "sweep"], "offsets": ["dx", "dy"],
            "clips": ["MoveStart", "Move", ...], "range": {"flap": 40, ...}, "bounce": 4,
            "penalty": 0.0008, "smooth": 0.0008}
  }
  Landing (opt-in; configs without these keys build exactly as before):
    "bodyTurn": {..., "keep": ["QTail_00"]}
        subtrees that ride the body turn's translation and yaw but not its pitch / roll. A flying
        dragon's DEF tail streams level behind it while the body flares nose-up; turned rigidly with
        the body, the tail hung 0.2-0.3 of the height below the feet, and at MoveEnd entry the Hips
        stood too far above the lowest point for the ground gate's joint entry (2026-09-28
        h3_green_dragon / h3_gold_dragon). Used by the turn fit and by the turn applied.
    "land": ["MoveEnd"]
        clips that settle into the Idle clip's first pose: after the body turn, every body bone's
        parent-relative pose is blended toward Unit_Idle frame 0's with weight 0 -> 1 over the clip
        (0.5 - 0.5 cos(pi i/(n-1)), the quadrupedSit easeIn curve), and the per-frame fit offsets'
        range shrinks by (1 - weight). The first frame keeps its DEF fit; the last frame is Idle
        frame 0 (body and wings), so the landing hands off to Idle without a step. Before it, the
        silhouette fits' free vertical offset left the dragons' last MoveEnd frame 0.11-0.19 of the
        height above the floor.
Writes <out>.wingchain.json (per frame values and IoU).

Primaries (per wing "primaries": [{...}]; opt-in, wings without it build exactly as before; not with "fan")
  A straight chain cannot spread the trailing primaries away from the leading edge, so a spread wing reads
  narrower than a DEF wing whose feathers fan out (2026-10-07 royal griffin, route 1a). Each entry adds one
  bone <pre>_P<i> from chain joint `from` (default 2, the wrist) to `tip` (rest mesh frame, left wing; mirrored
  in x for side -1), parented to chain bone `from`. Wing vertices on the tip's side of the chain (in-plane
  distance s along the tip's perpendicular offset) hand a share f of their chain weight to it:
  f = smoothstep((s - s0) / blend) * ramp(u: from - uIn .. from), u = chain coordinate (bones),
  {"tip": [x,y,z], "from": 2, "s0": 0.05, "blend": 0.15, "uIn": 0.5}. The bones ride their parent rigidly
  in every chain pose (fit included); the patch lane keys them (glbPatch keyRotations) to spread the fan.

Finger fan (per wing "fan": {...}; opt-in, wings without it build exactly as before)
  For bat wings that Meshy modelled FOLDED (wrist at the top, fingers hanging down the flank): a
  straight chain can swing and bend that sail but never widen it. With a fan block the wing gets an
  arm (<pre>_Arm shoulder->elbow, <pre>_00 elbow->wrist) and `fingers` finger chains out of the wrist
  (<pre>_{1+2f} wrist->knuckle, <pre>_{2+2f} knuckle->tip, inner/trailing finger first, leading last).
    "fan": {"wrist": [x,y,z],      # required: the wrist (base of the thumb hook), eye-picked per unit
            "fingers": 3, "tips": [[x,y,z], ...],   # tips default: distance-from-wrist maxima on the wing
            "fanDeg": 140, "spread": [deg, ...],    # finger turn at full open; default fanDeg split by
                                                    # the rest arc shoulder -> tip0 -> tip1 -> ...
            "knuckle": 0.55, "elbow": 0.5, "seedEps": 0.05, "rootR": 0.15, "hookBlend": 0.05,
            "anchorR": 0.25, "anchorBlend": 0.1,   # seam: wing verts sewn to the body within anchorR of the
                                                    # shoulder ride the chain parent, fading over anchorBlend
            "clawR": 0.08}                          # small loose pieces this close to a tip copy its weights
  Every fan vertex keeps at most 4 influences (glTF limit; more made the GLB disagree with the .blend).
  Weights: a harmonic "fan coordinate" s on the welded wing surface (s = 0 on the arm line and within
  rootR of the shoulder, s = j on finger j's line, Laplace in between, edge weights 1/length); a vertex
  blends the two lines around s, and along each line its two bones by projection. s is continuous
  over the surface, so the membrane stretches evenly between the fingers instead of tearing where a
  nearest-line rule flips. Vertices past the wrist along the arm (the thumb hook) ride <pre>_00.
  Pose: `open` slerps the whole wing to the spread attitude (arm along spreadDir, the membrane's
  in-plane tailward side kept tailward; spreadUp is not used) and turns finger i about the membrane
  normal at the wrist by spread_i * (open + fan) - fold * fanFold * spread_i / max(spread). The extra
  fit param "fan" (add it to fit.params) lets the fit narrow or widen the fan per frame.
"""
import json
import math
import numpy as np
from mathutils import Vector, Matrix, Quaternion

P_ALL = ("open", "flap", "sweep", "fold", "droop")


_LOG = []


def _say(*a):
    """print, and keep the line for <out>.wingchain.log (run_unit.sh filters build output)."""
    print(*a)
    if _LOG:
        with open(_LOG[0], "a") as f:
            f.write(" ".join(str(x) for x in a) + "\n")


def _wc(g):
    return g["cfg"].get("wingChain")


def _spec_value(spec, i, n):
    if isinstance(spec, (int, float)):
        return float(spec)
    v = spec.get("offset", 0.0)
    if "sin" in spec:
        ph = 2 * math.pi * spec.get("cycles", 1) * (i / max(n, 1)) + math.radians(spec.get("phase", 0.0))
        s = math.sin(ph)
        if spec.get("half") == "pos":
            s = max(s, 0.0)
        elif spec.get("half") == "neg":
            s = min(s, 0.0)
        v += spec["sin"] * s
    if "keys" in spec:
        u = i / max(n - 1, 1)
        ks = spec["keys"]
        v += float(np.interp(u, [k[0] for k in ks], [k[1] for k in ks]))
    return v


# ---------------------------------------------------------------- after_skin: chain bones + weights
def after_skin(g):
    wc = _wc(g)
    if not wc:
        return
    import bpy
    _LOG[:] = [g["OUT"] + ".wingchain.log"]
    open(_LOG[0], "w").close()
    body, rig = g["body"], g["rig"]
    nb = wc.get("bones", 4)
    ratios = wc.get("ratios", [0, 0.3, 0.55, 0.78, 1.0][:nb + 1] if nb == 4 else list(np.linspace(0, 1, nb + 1)))
    wdefs = {w["bone"]: w for w in g["WINGS"]}
    names = {vg.index: vg.name for vg in body.vertex_groups}
    P = np.array([v.co[:] for v in body.data.vertices])
    hips = np.array(g["J"]["Hips"], float)
    g["WCH"] = []
    for w in wc["wings"]:
        wb = w["bone"]
        rows = np.array([v.index for v in body.data.vertices
                         if any(names[x.group] == wb and x.weight > 0.5 for x in v.groups)])
        X = P[rows]
        head = np.array(wdefs[wb]["head"], float)
        c = X.mean(0)
        U, S, Vt = np.linalg.svd(X - c, full_matrices=False)
        ax = Vt[0] if Vt[0] @ (c - head) > 0 else -Vt[0]
        normal = Vt[2]
        if "points" in w:
            pts = np.array(w["points"], float)
        else:
            far = np.percentile((X - head) @ ax, 99)
            end = head + ax * far
            pts = np.array([head + (end - head) * r for r in ratios])
        dorsal = np.array(w.get("dorsal", list(c - hips)), float)
        if normal @ dorsal < 0:
            normal = -normal
        pre = "WingL" if w.get("side", 1) > 0 else "WingR"
        ch = {"bone": wb, "side": w.get("side", 1), "pts": pts, "normal": normal,
              "names": [f"{pre}_{k:02d}" for k in range(len(pts) - 1)], "rows": rows,
              "parent": w.get("parent", wdefs[wb].get("parent", "Spine2"))}
        if "fan" in w:
            ch.update(_fan_build(w["fan"], head, X, rows, body, P, dorsal, pre))
        g["WCH"].append(ch)
    for ch, w in zip(g["WCH"], wc["wings"]):
        ch["prim"] = []
        if w.get("primaries"):
            if "fan" in w:
                raise SystemExit("wingChain: primaries and fan on one wing are not supported")
            pre = ch["names"][0][:-3]
            for q, pc in enumerate(w["primaries"]):
                k0 = int(pc.get("from", 2)); tip = np.array(pc["tip"], float)
                if ch["side"] < 0:
                    tip = tip * np.array([-1.0, 1.0, 1.0])
                ch["prim"].append({"name": f"{pre}_P{q}", "k": k0, "head": ch["pts"][k0].copy(), "tip": tip, "cfg": pc})
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for ch in g["WCH"]:
        for k, n in enumerate(ch["names"]):
            b = eb.new(n); b.roll = 0
            if "fan" in ch:
                b.head, b.tail = Vector(ch["heads"][k]), Vector(ch["tails"][k])
                pk = ch["par"][k]
                b.parent = eb[ch["parent"]] if pk < 0 else eb[ch["names"][pk]]
                continue
            b.head, b.tail = Vector(ch["pts"][k]), Vector(ch["pts"][k + 1])
            b.parent = eb[ch["parent"]] if k == 0 else eb[ch["names"][k - 1]]
        for pr in ch.get("prim", []):
            b = eb.new(pr["name"]); b.roll = 0
            b.head, b.tail = Vector(pr["head"]), Vector(pr["tip"])
            b.parent = eb[ch["names"][pr["k"]]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for ch in g["WCH"]:
        for k, n in enumerate(ch["names"]):
            body.vertex_groups.new(name=n)
            g["bone_names"].append(n)
            if "fan" in ch:
                g["parent_of"][n] = ch["parent"] if ch["par"][k] < 0 else ch["names"][ch["par"][k]]
            else:
                g["parent_of"][n] = ch["parent"] if k == 0 else ch["names"][k - 1]
            g["STATIC"].add(n)        # follows its parent until before_keys poses it
        X = P[ch["rows"]]
        if "fan" in ch:
            cw = ch["cw"]
        else:
            pts = ch["pts"]; nbc = len(pts) - 1
            seg = np.diff(pts, axis=0); L2 = (seg * seg).sum(1)
            T_ = np.stack([np.clip(((X - pts[k]) @ seg[k]) / L2[k], 0, 1) for k in range(nbc)], 1)
            D = np.stack([np.linalg.norm(X - (pts[k] + T_[:, k:k + 1] * seg[k]), axis=1) for k in range(nbc)], 1)
            k = D.argmin(1); u = k + T_[np.arange(len(X)), k]
            cw = np.zeros((len(X), nbc))
            for j in range(nbc):
                cw[:, j] = np.maximum(0, 1 - np.abs(u - (j + 0.5)))
            cw[u < 0.5, 0] = 1.0; cw[u > nbc - 0.5, nbc - 1] = 1.0
            cw /= cw.sum(1, keepdims=True)
        vg = body.vertex_groups; gi = vg[ch["bone"]].index
        for r, i in enumerate(ch["rows"]):
            v = body.data.vertices[int(i)]
            for x in list(v.groups):
                vg[x.group].remove([v.index])
            for j in np.nonzero(cw[r] > 1e-4)[0]:
                vg[ch["names"][j]].add([v.index], float(cw[r, j]), 'REPLACE')
        # small loose pieces (claws, spikes cut free by the region cut) that sit on this wing but are
        # skinned to the body would float off once the wing really moves: bind each rigidly to the
        # chain position it touches
        adopted = _adopt_pieces(body, P, ch["rows"], cw, wc.get("adoptMaxVerts", 80),
                                wc.get("adoptWeights", "mean"))
        for piece, wts in adopted:
            for r_, i in enumerate(piece):
                v = body.data.vertices[int(i)]
                w_ = wts if wts.ndim == 1 else wts[r_]
                for x in list(v.groups):
                    vg[x.group].remove([v.index])
                for j in np.nonzero(w_ > 1e-4)[0]:
                    vg[ch["names"][j]].add([v.index], float(w_[j]), 'REPLACE')
        if adopted:
            _say("WINGCHAIN", ch["bone"], "adopted pieces", [len(pc) for pc, _ in adopted])
        if "fan" in ch:
            _fan_attach(ch, wdefs[ch["bone"]], wc, body, P, cw, g)
        for pr in ch.get("prim", []):
            _prim_weights(ch, pr, body, P, g)
        _say("WINGCHAIN", ch["bone"], "->", ch["names"], "verts", len(ch["rows"]),
              "pts", np.round(ch["pts"], 3).tolist(), "normal", np.round(ch["normal"], 2).tolist(),
              "share per bone", np.round(cw.sum(0) / len(X), 2).tolist())
        if "fan" in ch:
            _say("WINGFAN", ch["bone"], "wrist", np.round(ch["fan"]["wrist"], 3).tolist(),
                 "tips", np.round(ch["fan"]["tips"], 3).tolist(), "spread", np.round(ch["fan"]["spread"], 1).tolist(),
                 "seeds per line", ch["fan"]["seeds"])


def _prim_weights(ch, pr, body, P, g):
    """Primaries bone: hand a share of the chain weight of the wing vertices on the tip's side of the chain."""
    n = pr["name"]; pc = pr["cfg"]; k0 = pr["k"]
    body.vertex_groups.new(name=n); g["bone_names"].append(n)
    g["parent_of"][n] = ch["names"][k0]; g["STATIC"].add(n)
    pts = ch["pts"]; nbc = len(pts) - 1
    d = pts[-1] - pts[k0]; d /= np.linalg.norm(d)
    t = (pr["tip"] - pr["head"]); t = t - d * (t @ d); t /= np.linalg.norm(t)
    vg = body.vertex_groups; cidx = {vg[x].index: x for x in ch["names"]}
    seg = np.diff(pts, axis=0); L2 = (seg * seg).sum(1)
    s0, bl, uin = float(pc.get("s0", 0.05)), float(pc.get("blend", 0.15)), float(pc.get("uIn", 0.5))
    moved = 0; tot = 0.0
    for i in ch["rows"]:
        v = body.data.vertices[int(i)]; x = np.array(v.co[:])
        T_ = [min(1, max(0, ((x - pts[k]) @ seg[k]) / L2[k])) for k in range(nbc)]
        D_ = [np.linalg.norm(x - (pts[k] + T_[k] * seg[k])) for k in range(nbc)]
        kk = int(np.argmin(D_)); u = kk + T_[kk]
        sv = (x - pr["head"]) @ t
        a = min(1.0, max(0.0, (sv - s0) / bl)); a = a * a * (3 - 2 * a)
        r = min(1.0, max(0.0, (u - (k0 - uin)) / uin))
        f = a * r
        if f <= 1e-3:
            continue
        cw = [(x_.group, x_.weight) for x_ in v.groups if x_.group in cidx]
        share = sum(wt for _, wt in cw) * f
        for gi_, wt in cw:
            vg[cidx[gi_]].add([v.index], wt * (1 - f), 'REPLACE')
        vg[n].add([v.index], share, 'REPLACE')
        moved += 1; tot += f
    _say("WINGPRIM", n, "parent", ch["names"][k0], "tip", np.round(pr["tip"], 3).tolist(), "verts", moved,
         "mean share", round(tot / max(moved, 1), 2))


# ---------------------------------------------------------------- finger fan (folded bat wings)
def _topk(cw, k):
    """keep each row's k largest weights, renormalised: glTF skins carry 4 influences per vertex, and a
    fan vertex can blend 2 lines x 2 bones plus the seam anchor; more than 4 in Blender made the exported
    GLB disagree with the .blend (verify_glb MESHERR 0.049)."""
    cw = cw.copy()
    if cw.shape[1] > k:
        drop = np.argsort(cw, 1)[:, :-k]
        np.put_along_axis(cw, drop, 0.0, 1)
    return cw / np.maximum(cw.sum(1, keepdims=True), 1e-12)


def _pieces(body, n):
    """connected-component root per vertex (union-find over edges; no scipy in Blender)."""
    par = np.arange(n)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for e in body.data.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            par[a] = b
    return np.array([find(i) for i in range(n)])


def _fan_attach(ch, wdef, wc, body, P, cw, g):
    """Two fan-only fixes after the weights are written (floaters.py on the first fan build):
    1. seam: the wing is sewn to the back along the region cut (wing vertices coincident with body
       vertices). Near the shoulder the fan's arm turns the membrane ~90 deg about the shoulder, which
       opened the whole wing 0.35 (of unit size) off the body. Wing vertices within `anchorBlend` of
       a seam vertex that lies within `anchorR` of the shoulder blend onto the chain parent bone
       (1 on the seam, smoothstep to 0), so the wing root stays sewn on and the membrane stretches
       from the back to the arm instead.
    2. claws: small loose pieces (<= adoptMaxVerts) whose centre is within `clawR` of a finger tip
       were skinned to the body (the tips hang beside the legs at rest) and stayed behind when the
       fan spread; they copy the weights of their nearest wing vertex, per vertex."""
    fc = wc["wings"][[w["bone"] for w in wc["wings"]].index(ch["bone"])]["fan"]
    vg = body.vertex_groups
    rows = ch["rows"]; X = P[rows]
    wing = np.zeros(len(P), bool); wing[rows] = True
    S = np.array(wdef["head"], float)
    nonw = np.nonzero(~wing)[0]
    from mathutils.kdtree import KDTree

    def tree(idx):
        t = KDTree(len(idx))
        for k, i in enumerate(idx):
            t.insert(Vector(P[i]), k)
        t.balance()
        return t
    tb = tree(nonw)
    seam = np.array([tb.find(Vector(x))[2] < 1e-4 for x in X])
    anc = seam & (np.linalg.norm(X - S, axis=1) < fc.get("anchorR", 0.25))
    parent = ch["parent"]
    if anc.any() and parent in vg:
        A = X[anc]
        d = np.array([np.linalg.norm(A - x, axis=1).min() for x in X])
        t = np.clip(d / fc.get("anchorBlend", 0.1), 0, 1)
        a = 1 - t * t * (3 - 2 * t)
        for r, i in enumerate(rows):
            if a[r] < 1e-3:
                continue
            v = body.data.vertices[int(i)]
            for x in list(v.groups):
                vg[x.group].remove([v.index])
            c3 = _topk(cw[r:r + 1], 3)[0]          # + the parent = 4 influences
            for j in np.nonzero(c3 > 1e-4)[0]:
                if (1 - a[r]) * c3[j] > 1e-4:
                    vg[ch["names"][j]].add([v.index], float((1 - a[r]) * c3[j]), 'REPLACE')
            vg[parent].add([v.index], float(a[r]), 'REPLACE')
        _say("WINGFAN", ch["bone"], "seam anchored to", parent, "seam verts", int(anc.sum()),
             "verts blended", int((a > 1e-3).sum()))
    roots = _pieces(body, len(P))
    tips = ch["fan"]["tips"]; tw = tree(rows)
    ids, counts = np.unique(roots[~wing], return_counts=True)
    done = []
    for r_, c in zip(ids, counts):
        if c > wc.get("adoptMaxVerts", 80) or (roots[rows] == r_).any():
            continue
        piece = np.nonzero(roots == r_)[0]
        if np.linalg.norm(tips - P[piece].mean(0), axis=1).min() > fc.get("clawR", 0.08):
            continue
        for i in piece:
            k = tw.find(Vector(P[i]))[1]
            v = body.data.vertices[int(i)]
            for x in list(v.groups):
                vg[x.group].remove([v.index])
            for j in np.nonzero(cw[k] > 1e-4)[0]:
                vg[ch["names"][j]].add([v.index], float(cw[k, j]), 'REPLACE')
        done.append(len(piece))
    if done:
        _say("WINGFAN", ch["bone"], "tip claws adopted", done)


def _fan_build(fc, shoulder, X, rows, body, P, dorsal, pre):
    """Arm (shoulder -> elbow -> wrist, 2 bones) plus `fingers` finger chains (wrist -> knuckle -> tip,
    2 bones each) fanning out of the wrist, with the membrane weighted between neighbouring fingers by a
    harmonic fan coordinate on the welded wing surface (see the module docstring). Blender's Python
    has no scipy: the Laplace solve is dense numpy (a wing is ~500-1000 welded nodes)."""
    S = np.array(shoulder, float)
    Wr = np.array(fc["wrist"], float)
    a = Wr - S; a /= np.linalg.norm(a); back = -a
    # welded wing surface graph (UV seams split vertices)
    key = np.round(X / 1e-5).astype(np.int64)
    uk, inv = np.unique(key, axis=0, return_inverse=True); inv = inv.ravel(); m = len(uk)
    Xw = np.zeros((m, 3)); Xw[inv] = X
    loc = -np.ones(len(P), int); loc[rows] = inv
    E = []
    for p in body.data.polygons:
        vs = [loc[i] for i in p.vertices]
        for q in range(len(vs)):
            x, y = vs[q], vs[(q + 1) % len(vs)]
            if x >= 0 and y >= 0 and x != y:
                E.append((min(x, y), max(x, y)))
    E = np.unique(np.array(E), axis=0)
    adj = [[] for _ in range(m)]
    for x, y in E:
        adj[x].append(y); adj[y].append(x)
    # finger tips: distance-from-wrist maxima over their 2-ring, the farthest first, well apart
    if "tips" in fc:
        tips = [np.array(t, float) for t in fc["tips"]]
    else:
        dw = np.linalg.norm(Xw - Wr, axis=1)
        cand = []
        for v in range(m):
            ring = set(adj[v])
            for u in adj[v]:
                ring.update(adj[u])
            ring.discard(v)
            if not ring or dw[v] >= max(dw[list(ring)]) - 1e-9:
                cand.append((dw[v], v))
        cand.sort(reverse=True)
        tips = []
        for dv, v in cand:
            if dv < fc.get("minTipFrac", 0.5) * cand[0][0]:
                break
            if all(np.linalg.norm(Xw[v] - t) > fc.get("tipSep", 0.12) for t in tips):
                tips.append(Xw[v].copy())
            if len(tips) == fc.get("fingers", 3):
                break

    def ang(t):
        d = (t - Wr) / np.linalg.norm(t - Wr)
        return math.degrees(math.acos(max(-1.0, min(1.0, float(d @ back)))))
    tips = sorted(tips, key=ang)                    # inner (trailing) finger first, leading last
    nf = len(tips)
    # fan plane: through shoulder, wrist and tips; normal on the dorsal-hint side like the chain's
    pts = np.array([S, Wr] + tips)
    N = np.linalg.svd(pts - pts.mean(0))[2][2]
    if N @ dorsal < 0:
        N = -N
    sg = 1.0 if N @ np.cross(back, tips[-1] - Wr) >= 0 else -1.0     # + rotation opens the fan
    if "spread" in fc:
        spread = np.array(fc["spread"], float)
    else:                                            # by the rest arc from the shoulder along the tips
        arc = np.cumsum([np.linalg.norm(tips[0] - S)] + [np.linalg.norm(tips[k + 1] - tips[k]) for k in range(nf - 1)])
        spread = fc.get("fanDeg", 140.0) * arc / arc[-1]
    kn = fc.get("knuckle", 0.55)
    El = S + (Wr - S) * fc.get("elbow", 0.5)
    lines = [np.array([S, El, Wr])] + [np.array([Wr, Wr + kn * (t - Wr), t]) for t in tips]
    nl = len(lines)

    def polyd(Y, pl):
        best = np.full(len(Y), 1e9); u = np.zeros(len(Y))
        for k in range(2):
            sv = pl[k + 1] - pl[k]; t = np.clip(((Y - pl[k]) @ sv) / (sv @ sv), 0, 1)
            dd = np.linalg.norm(Y - (pl[k] + t[:, None] * sv), axis=1)
            mk = dd < best; best[mk] = dd[mk]; u[mk] = k + t[mk]
        return best, u
    # harmonic fan coordinate s: s = j on the surface nodes nearest to line j, Laplace elsewhere
    # (edge weights 1/length). Continuous on the surface, so neighbouring vertices never jump between
    # finger pairs (the nearest-pair rule tore the membrane at 26x in the numpy prototype)
    eps = fc.get("seedEps", 0.05)
    seed = -np.ones(m)
    for j, pl in enumerate(lines):
        for k in range(2):
            for t in np.linspace(0, 1, 25):
                p = pl[k] + (pl[k + 1] - pl[k]) * t
                d = np.linalg.norm(Xw - p, axis=1); q = int(d.argmin())
                if d[q] < eps and (seed[q] < 0 or j == 0):
                    seed[q] = j
    # the wing root stays on the arm: every node within rootR of the shoulder is an arm seed, otherwise
    # the membrane at the attachment follows a finger about the wrist and the whole wing pulls off the
    # body when the fan opens (floaters.py: right wing gap 0.35 of unit size in Move)
    seed[np.linalg.norm(Xw - S, axis=1) < fc.get("rootR", 0.15)] = 0
    ln = np.linalg.norm(Xw[E[:, 0]] - Xw[E[:, 1]], axis=1)
    wgt = 1.0 / np.maximum(ln, 1e-4)
    Lp = np.zeros((m, m))
    np.add.at(Lp, (E[:, 0], E[:, 1]), -wgt); np.add.at(Lp, (E[:, 1], E[:, 0]), -wgt)
    Lp[np.arange(m), np.arange(m)] = -Lp.sum(1)
    free = seed < 0
    sv = seed.copy()
    if free.any() and (~free).any():
        Lff = Lp[np.ix_(free, free)] + 1e-9 * np.eye(int(free.sum()))
        sv[free] = np.linalg.solve(Lff, -Lp[np.ix_(free, ~free)] @ seed[~free])
    # nodes on pieces no seed reaches keep 0 from the solve's regulariser: give them the fan
    # coordinate of the nearest line instead
    s = np.clip(sv[inv], 0, nl - 1)
    Dl = np.stack([polyd(X, pl)[0] for pl in lines], 1)
    Ul = np.stack([polyd(X, pl)[1] for pl in lines], 1)
    j0 = np.minimum(np.floor(s).astype(int), nl - 2); al = s - j0
    r = np.arange(len(X))

    def segw(u):
        w = np.stack([np.maximum(0, 1 - np.abs(u - 0.5)), np.maximum(0, 1 - np.abs(u - 1.5))], 1)
        w[u < 0.5, 0] = 1; w[u > 1.5, 1] = 1
        return w / w.sum(1, keepdims=True)
    cw = np.zeros((len(X), 2 * nl))
    for jj, wj in ((j0, 1 - al), (j0 + 1, al)):
        sw = segw(Ul[r, jj])
        cw[r, 2 * jj] += wj * sw[:, 0]; cw[r, 2 * jj + 1] += wj * sw[:, 1]
    # past the wrist along the arm (the thumb hook) rides the forearm, not the fingers
    beta = np.clip(((X - Wr) @ a) / fc.get("hookBlend", 0.05), 0, 1); beta = beta * beta * (3 - 2 * beta)
    cw *= (1 - beta)[:, None]; cw[:, 1] += beta
    cw = _topk(cw, 4)
    # bones: <pre>_Arm (shoulder-elbow), _00 (elbow-wrist); finger f: _{1+2f} (wrist-knuckle), _{2+2f}
    # (knuckle-tip). The humerus is unnumbered and the leading finger numbered last, so articulation.py's
    # wingFold (lowest vs highest *_NN region, >= 20 verts each) compares the forearm with the leading
    # finger tip: the humerus alone holds too few membrane vertices to be measured
    heads, tails, par = [S, El], [El, Wr], [-1, 0]
    for f in range(nf):
        heads += [lines[f + 1][0], lines[f + 1][1]]; tails += [lines[f + 1][1], lines[f + 1][2]]
        par += [1, 2 + 2 * f]
    return {"fan": {"wrist": Wr, "tips": np.array(tips), "spread": spread, "N": N, "sg": sg,
                    "seeds": [int((seed == j).sum()) for j in range(nl)]},
            "names": [f"{pre}_Arm"] + [f"{pre}_{k:02d}" for k in range(len(heads) - 1)], "heads": heads, "tails": tails,
            "par": par, "cw": cw, "normal": N}


def _adopt_pieces(body, P, rows, cw, maxv, mode="mean"):
    """small connected pieces (not the wing) most of whose vertices have a wing vertex as their
    nearest foreign neighbour -> [(vertex ids, chain weights)].
    mode "mean": one weight row per piece (rigid on the chain; the exemplars).
    mode "nearest": one row per vertex, copied from its nearest wing vertex. A seam sliver whose
    vertices coincide with wing vertices then skins exactly like them instead of drifting off the
    folded wing (a piece-mean weight differs from the blended weights it sits on)."""
    from mathutils.kdtree import KDTree
    n = len(P)
    par = np.arange(n)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for e in body.data.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            par[a] = b
    roots = np.array([find(i) for i in range(n)])
    wing = np.zeros(n, bool); wing[rows] = True
    wing_roots = set(np.unique(roots[rows]).tolist())

    def tree(idx):
        t = KDTree(len(idx))
        for k, i in enumerate(idx):
            t.insert(Vector(P[i]), k)
        t.balance()
        return t
    tw = tree(rows)
    nonw = np.nonzero(~wing)[0]
    to = tree(nonw)
    out = []
    ids, counts = np.unique(roots, return_counts=True)
    for r, c in zip(ids, counts):
        if c > maxv or r in wing_roots:
            continue
        piece = np.nonzero(roots == r)[0]
        near, iw, kall, dmin = [], [], [], 1e9
        for i in piece:
            _, kw, dw = tw.find(Vector(P[i]))
            do = min((d for _, k, d in to.find_n(Vector(P[i]), c + 8) if roots[nonw[k]] != r), default=1e9)
            dmin = min(dmin, dw)
            kall.append(kw)
            if dw <= do:
                near.append(True); iw.append(kw)
            else:
                near.append(False)
        if np.mean(near) <= 0.5 or dmin > 0.02:
            continue
        if mode == "nearest":
            wts = cw[kall]
            out.append((piece, wts / wts.sum(1, keepdims=True)))
            continue
        wts = cw[iw].mean(0)
        out.append((piece, wts / wts.sum()))
    return out


def after_pose(g):
    for ch in g.get("WCH", []):
        for n in ch["names"]:
            g["STATIC"].discard(n)


# ---------------------------------------------------------------- pose model
def _rot(axis, deg):
    return np.array(Matrix.Rotation(math.radians(deg), 3, Vector(axis)))


def _frame(d, up):
    d = d / np.linalg.norm(d); up = up - d * (up @ d); up /= np.linalg.norm(up)
    return np.stack([d, up, np.cross(d, up)], 1)


def _slerp_R(R, t):
    q = Matrix(R.tolist()).to_quaternion()
    if t < 0:                                   # past the rest pose, away from the spread one
        q, t = q.inverted(), -t
    if t > 1:                                   # past the spread pose
        return np.array((q.to_matrix() @ Quaternion().slerp(q, t - 1).to_matrix()))
    return np.array(Quaternion().slerp(q, t).to_matrix())


def _with_twist(EO, axis, side, v):
    """EO @ (rotation about the rest arm axis by side * twist); EO itself, untouched, when twist is 0/absent
    so wings without the channel pose bit-identically to builds before it existed."""
    tw = v.get("twist", 0.0)
    if not tw:
        return EO
    return EO @ _rot(axis, side * tw)


def _uses_twist(wc):
    """the twist channel is opt-in: keyed in some anim clip, or a fit param."""
    return (any("twist" in (spec or {}) for spec in wc.get("anim", {}).values())
            or "twist" in (wc.get("fit") or {}).get("params", []))


class _Wing:
    def __init__(self, ch, wc, rest, parent_of, axes):
        self.ch = ch; s = ch["side"]
        pts = ch["pts"]; self.pts = pts; self.cn = ch["names"]; self.parent = ch["parent"]
        self.prim = [(pr["name"], pr["k"]) for pr in ch.get("prim", [])]
        self.names = self.cn + [nm for nm, _ in self.prim]          # chain bones, then primaries (ride rigidly)
        self.primRel = [np.linalg.inv(np.array(rest[self.cn[k]])) @ np.array(rest[nm]) for nm, k in self.prim]
        self.segs = np.diff(pts, axis=0)
        self.d = self.segs[0] / np.linalg.norm(self.segs[0])
        N = ch["normal"]; N = N - self.d * (N @ self.d); self.N = N / np.linalg.norm(N)
        self.C = np.cross(self.N, self.d)
        self.A = self.d                                             # twist axis: the rest arm
        # body axes (rest): X lateral (left), H headward along the spine, D dorsal = H x X.
        # spreadDir / spreadUp are [lateral, tailward, dorsal] components in these axes, so an
        # upright-standing flyer spreads in the plane of its spine and flies with it level
        X, H, D = axes
        self.H, self.D = H, D
        a = np.array(wc.get("spreadDir", [1, 0.25, 0.05]), float)
        b = np.array(wc.get("spreadUp", [0, 0, 1]), float)
        sd = a[0] * s * X - a[1] * H + a[2] * D
        su = b[0] * s * X - b[1] * H + b[2] * D
        self.S = _frame(sd, su) @ _frame(self.d, self.N).T         # rest -> spread (rest body frame)
        # fold sign: + sends the spread tip tailward
        self.fsign = 1.0 if (self.S @ self.C) @ (-H) >= 0 else -1.0
        nj = len(self.cn) - 1
        self.fsh = wc.get("foldShares", [0.0, 0.3, 0.7][:nj])
        self.dsh = wc.get("droopShares", [0.0, 0.4, 0.6][:nj])
        self.s = s
        self.restR = [np.array(rest[n].to_3x3()) for n in self.cn]
        self.restP = np.array(rest[self.parent])

    def G(self, v):
        """rest-body-frame rotation per bone."""
        O = _slerp_R(self.S, max(-0.5, min(1.2, v.get("open", 0.0))))
        # flap: about the spine (+ = toward dorsal); sweep: about the dorsal axis (+ = tailward)
        E = _rot(self.H, self.s * v.get("flap", 0.0)) @ _rot(self.D, self.s * v.get("sweep", 0.0))
        EO = _with_twist(E @ O, self.A, self.s, v)
        out = []; L = np.eye(3)
        for k in range(len(self.cn)):
            if k > 0:
                j = k - 1
                L = L @ _rot(self.N, self.fsign * v.get("fold", 0.0) * self.fsh[j]) \
                      @ _rot(self.C, v.get("droop", 0.0) * self.dsh[j])
            out.append(EO @ L)
        return out

    def pose(self, Apar, v):
        """world 4x4 per chain bone, given the parent's posed world matrix (numpy)."""
        B = Apar @ np.linalg.inv(self.restP)
        Br = B[:3, :3]
        head = (B @ np.r_[self.pts[0], 1])[:3]
        out = []
        for k, Gk in enumerate(self.G(v)):
            M = np.eye(4); M[:3, :3] = Br @ Gk @ self.restR[k]; M[:3, 3] = head
            out.append(M)
            head = head + Br @ Gk @ self.segs[k]
        for (nm, k), Rel in zip(self.prim, self.primRel):
            out.append(out[k] @ Rel)
        return out


class _FanWing:
    """Arm + finger fan. `open` slerps the whole wing from rest to the spread attitude (arm along
    spreadDir, the membrane's in-plane tailward side kept tailward) and spreads each finger about the
    membrane normal at the wrist by spread_i * (open + fan); `fold` closes the fan (the leading finger
    by `fanFold` of fold, the others in proportion); `droop` bends the fingers out of plane at the
    wrist and knuckle (`droopShares` [wrist, knuckle]); flap/sweep as the chain."""

    def __init__(self, ch, wc, rest, axes):
        self.ch = ch; s = ch["side"]; fz = ch["fan"]
        self.names, self.parent, self.par = ch["names"], ch["parent"], ch["par"]
        self.heads = [np.array(h, float) for h in ch["heads"]]
        X, H, D = axes
        self.H, self.D, self.s = H, D, s
        self.N = fz["N"]; self.sg = fz["sg"]; self.spread = np.array(fz["spread"], float)
        a = np.array(ch["tails"][1], float) - self.heads[0]; a /= np.linalg.norm(a)      # shoulder -> wrist
        self.A = a                                                                         # twist axis
        sp = np.array(wc.get("spreadDir", [1, 0.25, 0.05]), float)
        sd = sp[0] * s * X - sp[1] * H + sp[2] * D
        self.S = _frame(sd, -H) @ _frame(a, -H).T
        self.C = []
        for k in range(len(self.names)):
            dvec = np.array(ch["tails"][k]) - self.heads[k]; c = np.cross(self.N, dvec)
            self.C.append(c / max(np.linalg.norm(c), 1e-9))
        self.dsh = wc.get("fanDroopShares", [0.4, 0.6])
        self.ffold = wc.get("fanFold", 1.0)
        self.restR = [np.array(rest[n].to_3x3()) for n in self.names]
        self.restP = np.array(rest[self.parent])

    def G(self, v):
        op = v.get("open", 0.0)
        O = _slerp_R(self.S, max(-0.5, min(1.2, op)))
        E = _rot(self.H, self.s * v.get("flap", 0.0)) @ _rot(self.D, self.s * v.get("sweep", 0.0))
        f = max(0.0, min(1.2, op)) + v.get("fan", 0.0)
        smax = max(float(self.spread.max()), 1e-6)
        dr = v.get("droop", 0.0)
        L = [np.eye(3), np.eye(3)]
        for k in range(2, len(self.names)):
            fi = (k - 2) // 2
            if k % 2 == 0:
                ang = self.spread[fi] * f - v.get("fold", 0.0) * self.ffold * self.spread[fi] / smax
                ang = max(-15.0, ang)
                L.append(L[1] @ _rot(self.N, self.sg * ang) @ _rot(self.C[k], dr * self.dsh[0]))
            else:
                L.append(L[k - 1] @ _rot(self.C[k], dr * self.dsh[1]))
        EO = _with_twist(E @ O, self.A, self.s, v)
        return [EO @ Lk for Lk in L]

    def pose(self, Apar, v):
        B = Apar @ np.linalg.inv(self.restP)
        Br = B[:3, :3]
        Gs = self.G(v)
        hp, out = [], []
        for k, Gk in enumerate(Gs):
            p = self.par[k]
            h = (B @ np.r_[self.heads[k], 1])[:3] if p < 0 else hp[p] + Br @ Gs[p] @ (self.heads[k] - self.heads[p])
            hp.append(h)
            M = np.eye(4); M[:3, :3] = Br @ Gk @ self.restR[k]; M[:3, 3] = h
            out.append(M)
        return out


# ---------------------------------------------------------------- before_keys: drive + fit
def before_keys(g):
    wc = _wc(g)
    if not wc or not g.get("WCH"):
        return
    import bpy
    rest, posed, body = g["rest"], g["posed_world"], g["body"]
    T = len(posed)
    Jh = np.array(g["J"]["Hips"], float); Js = np.array(g["J"].get("Spine2", g["J"]["Spine"]), float)
    H = np.array(wc.get("bodyAxis", list(Js - Jh)), float); X = np.array([1.0, 0, 0])
    H = H - X * (H @ X); H /= np.linalg.norm(H); D = np.cross(H, X)
    wings = [_FanWing(ch, wc, rest, (X, H, D)) if "fan" in ch else _Wing(ch, wc, rest, g["parent_of"], (X, H, D))
             for ch in g["WCH"]]
    PP = P_ALL + (("fan",) if any("fan" in ch for ch in g["WCH"]) else ()) + (("twist",) if _uses_twist(wc) else ())
    chain_names = [n for w in wings for n in w.names]
    ms = json.load(open(g["MASTER"]))
    tab = [None] * T
    for sg in ms["segments"]:
        for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
            tab[t] = (sg["contractSuffix"], i, sg["frameCount"])
    anim = wc.get("anim", {})
    lim = {"fan": [-0.6, 0.6], "open": [-0.3, 1.1], "flap": [-80, 90], "sweep": [-50, 50], "fold": [-30, 110], "droop": [-40, 80],
           "twist": [-90, 90],
           "dx": [-40, 40], "dy": [-40, 40]}
    lim.update(wc.get("limits", {}))

    def base(t):
        clip, i, n = tab[t]
        v = {p: 0.0 for p in PP}
        for src in ("*", clip):
            for p, spec in anim.get(src, {}).items():
                v[p] = v.get(p, 0.0) + _spec_value(spec, i, n)
        return v

    skip = set(g.get("RUBBLE_BONES", ())) | {"Root"} | set(g["STATIC"])
    R_, U_ = np.array(g["right"]), np.array(g["up"])
    s_px, ox, oy, SW, SH = g["s_px"], g["ox"], g["oy"], g["SW"], g["SH"]

    FIT = wc.get("fit") or {}
    segs = ms["segments"]
    parent_of = g["parent_of"]
    kids = {}
    for b_, p_ in parent_of.items():
        kids.setdefault(p_, []).append(b_)

    def subtree(b):
        out = [b]; k = 0
        while k < len(out):
            out += kids.get(out[k], []); k += 1
        return out

    LAND = set(wc.get("land", []))
    for c in LAND:
        if not any(x["contractSuffix"] == c and x["frameCount"] >= 2 for x in segs):
            raise SystemExit(f"wingChain.land: no {c} segment of 2+ frames to settle")
    t_idle0 = max((x for x in segs if x["contractSuffix"] == "Idle"), key=lambda x: x["frameCount"])["globalStart"] \
        if LAND else None

    def land_w(t):
        clip, i, n = tab[t]
        if clip not in LAND:
            return 0.0
        return 0.5 - 0.5 * math.cos(math.pi * i / max(n - 1, 1))

    def about_hips(A, M3, dx=0.0, dy=0.0):
        """rotate the whole pose by M3 (world axes) about the hips, then shift on screen."""
        h = A["Hips"].translation.copy()
        Tm = Matrix.Translation(Vector(tuple(R_ * dx / s_px + U_ * dy / s_px)) + h) @ M3.to_4x4() @ Matrix.Translation(-h)
        return {n: (m if n in skip else Tm @ m) for n, m in A.items()}

    # 1. steady torso: blend each frame's hips rotation toward the clip's mean rotation, so the
    #    capture's per-frame body wobble (a flyer's rocking) does not survive into the clip
    for sg in segs:
        sh = wc.get("steady", {}).get(sg["contractSuffix"])
        if not sh or sg["frameCount"] < 2:
            continue
        ts = list(range(sg["globalStart"], sg["globalEnd"]))
        qs = [posed[t]["Hips"].to_quaternion() for t in ts]
        for k in range(1, len(qs)):
            if qs[k].dot(qs[0]) < 0:
                qs[k] = -qs[k]
        qm = Quaternion(tuple(np.mean([tuple(q) for q in qs], 0))).normalized()
        for t, q in zip(ts, qs):
            C = Quaternion().slerp(qm @ q.inverted(), min(1.0, sh))
            A = about_hips(posed[t], C.to_matrix())
            posed[t].clear(); posed[t].update(A)
    def land_blend():
        """"land" clips: blend each body bone's parent-relative pose toward Unit_Idle frame 0's (weight land_w)."""
        if not LAND:
            return
        ref = posed[t_idle0]

        def depth(n):
            d = 0
            while parent_of.get(n) in ref:
                n = parent_of[n]; d += 1
            return d
        order = sorted((n for n in ref if n not in skip and n not in chain_names), key=depth)
        for t in range(T):
            w = land_w(t)
            if w <= 0.0:
                continue
            A = posed[t]; out = {}
            for n in order:
                p = parent_of.get(n)
                rel = p in A and p in ref
                la = A[p].inverted() @ A[n] if rel else A[n]
                lb = ref[p].inverted() @ ref[n] if rel else ref[n]
                q = la.to_quaternion().slerp(lb.to_quaternion(), w)
                L = Matrix.Translation(la.translation.lerp(lb.translation, w)) @ q.to_matrix().to_4x4()
                out[n] = (out.get(p, A[p]) @ L) if rel else L
            A.update(out)
            fitted.setdefault(t, {})["landWeight"] = round(w, 3)

    log = []
    fitted = {}
    if FIT:
        # numpy skinning on a vertex subsample: body part fixed per frame, wing part per trial
        V0 = np.array([v.co[:] for v in body.data.vertices])
        sub = np.arange(len(V0))
        if len(sub) > 9000:
            sub = sub[::int(math.ceil(len(sub) / 9000))]
        names_all = [n for n in posed[0] if n != "Root"]
        colx = {n: i for i, n in enumerate(names_all)}
        gname = {x.index: x.name for x in body.vertex_groups}
        pos = {int(i): k for k, i in enumerate(sub)}
        Wm = np.zeros((len(sub), len(names_all)))
        for v in body.data.vertices:
            k = pos.get(v.index)
            if k is None:
                continue
            for x in v.groups:
                if gname[x.group] in colx:
                    Wm[k, colx[gname[x.group]]] += x.weight
        Wm /= np.maximum(Wm.sum(1, keepdims=True), 1e-9)
        Vh = np.c_[V0[sub], np.ones(len(sub))]
        ccols = [colx[n] for n in chain_names]
        wrows = Wm[:, ccols].sum(1) > 1e-6
        Vw = Vh[wrows]; Ww = Wm[wrows][:, ccols]; Wsum = Ww.sum(1, keepdims=True)
        restinv = {n: np.linalg.inv(np.array(rest[n])) for n in names_all}
        other = [n for n in names_all if n not in chain_names and Wm[:, colx[n]].max() > 0]

        def skin_body(A):
            out = np.zeros((len(sub), 3))
            for n in other:
                M = np.array(A[n]) @ restinv[n]
                out += Wm[:, colx[n]][:, None] * (Vh @ M.T)[:, :3]
            return out

        def with_wings(A, Pb, v):
            Ms = {}
            for w in wings:
                for n, M in zip(w.names, w.pose(np.array(A[w.parent]), v)):
                    Ms[n] = M
            out = np.zeros((len(Vw), 3))
            for j, n in enumerate(chain_names):
                out += Ww[:, j:j + 1] * (Vw @ (Ms[n] @ restinv[n]).T)[:, :3]
            Pp = Pb.copy(); Pp[wrows] = Pp[wrows] * (1 - Wsum) + out
            return Pp

        def splat(Pp):
            x = np.round(ox + s_px * (Pp @ R_)).astype(int); y = np.round(oy - s_px * (Pp @ U_)).astype(int)
            ok = (x >= 1) & (x < SW - 1) & (y >= 1) & (y < SH - 1)
            m = np.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
            gg = m.copy()
            for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                gg |= np.roll(np.roll(m, a, 0), b, 1)
            return gg

        masks = {}

        def mask(t):
            if t not in masks:
                img = bpy.data.images.load(ms["frames"][t]["sourcePng"], check_existing=True)
                a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 0.99
                bpy.data.images.remove(img); masks[t] = a
            return masks[t]

        def iou(m, tgt):
            return (m & tgt).sum() / max((m | tgt).sum(), 1)

        def descend(params, step0, clampv, score, off):
            best = score(off)
            for level in range(4):
                improved = True
                while improved:
                    improved = False
                    for p in params:
                        st = step0[p] / (2 ** level)
                        for sgn in (1, -1):
                            c = dict(off); c[p] = clampv(p, c[p] + sgn * st)
                            sc = score(c)
                            if sc > best + 1e-6:
                                best, off, improved = sc, c, True
            return off

        # 2. one body turn per clip (pitch/roll about the hips + a screen offset), constant over the
        #    clip: fixes a capture held at the wrong attitude (a bird upright in flight) without any
        #    per-frame rocking. rampIn / rampOut clips ease into / out of it.
        BT = wc.get("bodyTurn", {})
        tlim = {"yaw": [-80, 80], "pitch": [-70, 70], "roll": [-45, 45], "dx": [-40, 40], "dy": [-40, 40]}

        def turn3(o, f=1.0):
            return (Matrix.Rotation(math.radians(o.get("yaw", 0.0) * f), 3, 'Z')
                    @ Matrix.Rotation(math.radians(o["pitch"] * f), 3, 'X') @ Matrix.Rotation(math.radians(o["roll"] * f), 3, 'Y'))
        tlim.update(BT.get("limits", {}))
        keep_roots = list(BT.get("keep", []))
        for b_ in keep_roots:
            if b_ not in posed[0]:
                raise SystemExit(f"wingChain.bodyTurn.keep: no bone {b_!r} in the pose")

        def turned(A, o, f=1.0):
            """the body turn o (at fraction f) about the hips; keep subtrees take its shift and yaw only."""
            B = about_hips(A, turn3(o, f), o["dx"] * f, o["dy"] * f)
            if keep_roots:
                Rz = Matrix.Rotation(math.radians(o.get("yaw", 0.0) * f), 4, 'Z')
                for r_ in keep_roots:
                    Mk = Matrix.Translation(B[r_].translation) @ Rz @ Matrix.Translation(-A[r_].translation)
                    for n_ in subtree(r_):
                        if n_ in A and n_ not in skip:
                            B[n_] = Mk @ A[n_]
            return B
        turns = {}
        for clip in BT.get("fit", []):
            sg = max((x for x in segs if x["contractSuffix"] == clip), key=lambda x: x["frameCount"])
            ts = list(range(sg["globalStart"], sg["globalEnd"]))

            def tscore(o, ts=ts):
                tot = 0.0
                for t in ts:
                    A = turned(posed[t], o)
                    tot += iou(splat(with_wings(A, skin_body(A), base(t))), mask(t))
                return tot / len(ts) - 0.0002 * (abs(o["pitch"]) + abs(o["roll"]) + abs(o["yaw"]))
            z4 = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "dx": 0.0, "dy": 0.0}
            tp = [p for p in ("yaw", "pitch", "roll", "dx", "dy") if p in BT.get("params", ["yaw", "pitch", "roll", "dx", "dy"])]
            # coarse scan of the attitude first: descent from zero cannot turn a body 60 degrees
            cands = [dict(z4, yaw=float(y), pitch=float(pt)) for y in BT.get("scanYaw", [-60, -40, -20, 0, 20, 40, 60])
                     for pt in BT.get("scanPitch", [-30, 0, 30])]
            start = max(cands, key=tscore) if "yaw" in tp else dict(z4)
            o = descend(tp, {"yaw": 12, "pitch": 16, "roll": 16, "dx": 8, "dy": 8},
                        lambda p, x: max(tlim[p][0], min(tlim[p][1], x)), tscore, start)
            turns[clip] = o
            _say("WINGCHAIN bodyTurn", clip, {k: round(v, 1) for k, v in o.items()},
                  "IoU", round(tscore(z4), 3), "->", round(tscore(o), 3))
        ramps = [(c, s_, True) for c, s_ in BT.get("rampIn", {}).items()] + \
                [(c, s_, False) for c, s_ in BT.get("rampOut", {}).items()]
        for t in range(T):
            clip, i, n = tab[t]
            o, f = turns.get(clip), 1.0
            for c, src, rin in ramps:
                if clip == c and src in turns:
                    o = turns[src]; u = i / max(n - 1, 1); f = u if rin else 1 - u
            if not o:
                continue
            A = turned(posed[t], o, f)
            posed[t].clear(); posed[t].update(A)
            fitted.setdefault(t, {}).update({k: round(o[k] * f, 1) for k in ("yaw", "pitch", "roll")})
        land_blend()

        # 3. per-frame wing fit (+ a bounded screen bounce) against the DEF frame
        fclips = set(FIT.get("clips", ["MoveStart", "Move", "MoveEnd", "Hitted", "Defence", "AttackFront", "Death"]))
        rng = {"fan": 0.5, "open": 0.5, "flap": 45, "sweep": 30, "fold": 60, "droop": 45, "twist": 30}
        rng.update(FIT.get("range", {}))
        bounce = FIT.get("bounce", 4.0)
        rng["dx"] = rng["dy"] = bounce
        step0 = {"fan": 0.2, "open": 0.2, "flap": 12, "sweep": 10, "fold": 16, "droop": 12, "twist": 10, "dx": 2, "dy": 2}
        lam, lam2 = FIT.get("penalty", 0.0008), FIT.get("smooth", 0.0008)
        unit = {p: 8.0 / step0[p] for p in step0}
        unit["dx"] = unit["dy"] = 1.0
        params = list(FIT.get("params", ["flap", "open", "fold", "droop", "sweep"])) + list(FIT.get("offsets", ["dx", "dy"]))
        prev = {}
        for t in range(T):
            clip, i, n = tab[t]
            if clip not in fclips:
                continue
            if i == 0:
                prev = {}
            b = base(t); tgt = mask(t); A0 = posed[t]; cache = {}

            def evaluate(o, b=b, tgt=tgt, A0=A0, cache=cache):
                key = (o.get("dx", 0.0), o.get("dy", 0.0))
                if key not in cache:
                    A = about_hips(A0, Matrix.Identity(3), *key)
                    cache[key] = (A, skin_body(A))
                A, Pb = cache[key]
                v = dict(b)
                for p in PP:
                    if p in o:
                        v[p] = b[p] + o[p]
                return iou(splat(with_wings(A, Pb, v)), tgt)

            def score(o, prev=prev):
                return evaluate(o) - sum(lam * abs(x) * unit[p] + lam2 * abs(x - prev.get(p, 0.0)) * unit[p]
                                         for p, x in o.items())

            lw = 1.0 - land_w(t)     # a "land" clip's offsets shrink to nothing at its Idle-matched end

            def clampv(p, x, b=b, lw=lw):
                x = max(-rng[p] * lw, min(rng[p] * lw, x))
                if p in b:
                    x = max(lim[p][0] - b[p], min(lim[p][1] - b[p], x))
                return x

            zero = {p: 0.0 for p in params}
            start = {p: clampv(p, prev.get(p, 0.0)) for p in params}
            off = descend(params, step0, clampv, score, start if score(start) > score(zero) else zero)
            prev = off
            fitted.setdefault(t, {}).update({"iouBase": round(float(evaluate(zero)), 3), "iou": round(float(evaluate(off)), 3),
                                             "off": {p: round(x, 2) for p, x in off.items()}})
    if not FIT:
        land_blend()
    # 4. pose the chains (and the fitted bounce) into every frame
    for t in range(T):
        v = base(t); f = fitted.get(t, {}); off = f.get("off", {})
        for p in PP:
            v[p] += off.get(p, 0.0)
        A = dict(about_hips(posed[t], Matrix.Identity(3), off.get("dx", 0.0), off.get("dy", 0.0)))
        for w in wings:
            for nme, M in zip(w.names, w.pose(np.array(A[w.parent]), v)):
                A[nme] = Matrix(M.tolist())
        posed[t].clear(); posed[t].update(A)
        rec = {"frame": t, "clip": tab[t][0], **{p: round(float(x), 2) for p, x in v.items()}}
        rec.update({k: x for k, x in f.items() if k != "off"})
        rec.update({p: off[p] for p in ("dx", "dy") if p in off})
        log.append(rec)
    json.dump(log, open(g["OUT"] + ".wingchain.json", "w"), indent=0)
    fl = [r for r in log if "iou" in r]
    if fl:
        _say("WINGCHAIN fit mean IoU", round(float(np.mean([r["iou"] for r in fl])), 3), "from base",
              round(float(np.mean([r["iouBase"] for r in fl])), 3), "frames", len(fl))
    _say("WINGCHAIN posed", T, "frames")
