"""Fortress extension for build_unit.py (config key "fortress"; list "fortress_rig" in "extensions").

The capture is a human skeleton. For Fortress's non-humanoids (flies, basilisks, gorgons, wyverns,
hydras) it is unusable, so this module can replace the capture motion with a small procedural rig
fitted to the DEF silhouette frame by frame. Pieces (all optional):

  reweight: [{box|sphere|segments(+radius), margin, strip:[bone suffixes], set:{bone:w},
              zBlend:[[z, bone], ...]}]
      after skinning, inside the region (soft falloff over `margin`): drop weight on bones whose
      name ends with a `strip` suffix, or blend toward fixed weights (`set`) / a height ramp
      between bones (`zBlend`). Rigid prop/wing vertices are never touched. Used for capes that
      bone heat hands to the arms, hydra chests, etc.
  chains: [{name, parent, points:[[x,y,z],...], radius, rootBlend, ratio, box}]
      articulated bone chains (tails, serpent bodies, hydra necks) along a hand/seeded centreline.
      A vertex belongs to the closest chain if it is within `radius` of it and no farther than
      `ratio` x its distance to any non-chain bone (the chain's parent excluded); with
      `geodesic: G` ownership is decided along the mesh surface instead: every group (the other
      bones, each chain) is seeded with the vertices clearly nearest to it and a vertex goes to the
      group nearest over the surface (G = the largest distance a chain may claim); it is weighted by
      its position along the chain (two nearest bones), blending into its heat weights over the
      first `rootBlend` of chain length.
      `maxBlueMinusRed: t` gates a region to texels with blue - red <= t (brown wood/leather on a
      blue body).
      `absorb: [bone, ...]` hands the named capture bones' flesh to the chain: they no longer compete
      for ownership (euclidean `od` and the geodesic "other bones" seeds), so a chain laid over them
      (a wyvern neck chain from the shoulders over the capture's two-bone Neck/Head column) owns
      that flesh. The absorbed bones stay in the rig and follow their parent; only vertices outside
      every chain keep their heat weight on them.
  postReweight: [...] -- reweight specs applied after the chains (chains otherwise win).
  fillUnweighted: true -- after reweight/chains, a vertex with no weight at all copies the weights of
      the nearest weighted vertex (fly fangs / claw islands that bone heat never reached).
  armSplit: {sides, foreRadius, handRadius, armKeep} -- cut an arm Meshy fused to the flank/robe
      free (castle hand cut / inferno straddle cut adapted; see _arm_split).
  chainCut: [{a: [bone prefixes], b: [...]}] -- split the mesh between faces owned by a and by b
      (wyvern wing tip lying on the tail).
  procedural: true   -- discard the capture pose; every frame starts from the rest pose.
  params: {name: {type: rot|chain|screen, ...}}
      rot:    bones:[[bone, share], ...], axis:[x,y,z] (world rest axis) -- degrees
      chain:  chain:<name or [names]>, mode: curl|wave|straight|phase, axis / dir, wavelength (bones)
              curl: total bend (deg) spread over the chain; wave: travelling-wave amplitude (deg),
              its phase from the param named in `phaseParam`; straight: 0..1 blend of every bone
              toward direction `dir` (world rest, in the chain parent's frame)
      screen: dx / dy (sprite pixels) / roll (deg about the camera axis through the hips)
  anim: {clipSuffix | "*": {param: spec}}   base value per frame; spec is
      {"sin": amp, "cycles": 1, "phase": deg, "offset": c}  (loops close: phase runs i/n)
      {"keys": [[u, v], ...]}                             (u = i/(n-1) over the clip)
      {"alt": amp}                                         (+amp / -amp on alternate frames)
      {"ramp": total}                                      (total * i/n, e.g. a wave phase)
  fit: {params:[...], clips:{suffix:[extra params]}, limits:{p:[lo,hi]}, penalty, smooth,
        scan:{p:[values]} (coarse grid tried each frame before the descent), camYawSearch:[deg]}
      per frame, a coordinate search of offsets on top of the base values that maximises
      silhouette IoU against the DEF frame under the sprite camera (like build_unit's
      silhouetteRefine, but over the procedural rig's own parameters).
      `tip: {clips: [suffix, ...], side: "right"|"left", weight: w}` adds a leading-tip term in the
      listed clips: the silhouette's frontmost point (the extreme column on `side`, and the mean row
      of the pixels within 2 px of it), found the same way on the DEF mask and on the fitted
      splat, costs `w` per pixel of |dx| + |dy| between them. IoU alone is blind to a small head:
      the wyvern's flight fit (2026-09-30) rolled the body +-13 deg for the wings and carried a
      rigid neck with it, so its head bobbed 20 px where the DEF head holds within 2 px.
      The per-frame error lands in the .fortfit.json log as `tipErr`.
  flap: {bones:{wingBone: sign}, amp: deg, "clips": {suffix: amp}}   (before_keys) fast wing beat
      alternating each DEF frame, on top of whatever the wings block produced.
"""
import bpy, math, json
import numpy as np
from mathutils import Vector, Matrix


def _fc(g):
    return g["cfg"].get("fortress", {})


# ---------------------------------------------------------------- geometry helpers
def _seg_dist(P, a, b):
    a = np.asarray(a, float); b = np.asarray(b, float); ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1), t


def _region_dist(P, reg):
    """Distance outside a region (0 inside)."""
    if "box" in reg:
        lo, hi = np.array(reg["box"][0], float), np.array(reg["box"][1], float)
        return np.linalg.norm(np.maximum(0, np.maximum(lo - P, P - hi)), axis=1)
    if "sphere" in reg:
        c, r = np.array(reg["sphere"][0], float), reg["sphere"][1]
        return np.maximum(0, np.linalg.norm(P - c, axis=1) - r)
    d = np.min(np.stack([_seg_dist(P, a, b)[0] for a, b in reg["segments"]], 1), 1)
    return np.maximum(0, d - reg["radius"])


def _alpha(P, reg):
    d = _region_dist(P, reg); m = reg.get("margin", 0.0)
    a = (d <= 0).astype(float) if m <= 0 else np.clip(1 - d / m, 0, 1)
    for ex in reg.get("exclude", []):
        a = a * (_region_dist(P, ex) > 0)
    return a


def _geodesic(body, P, seeds):
    """Distance along the mesh surface (vertices welded by position) from the seed vertices."""
    import heapq
    key = np.round(P, 5)
    _, inv = np.unique(key, axis=0, return_inverse=True); inv = inv.ravel(); n = inv.max() + 1
    Q = np.zeros((n, 3)); Q[inv] = P
    adj = [[] for _ in range(n)]
    for e in body.data.edges:
        a, b = inv[e.vertices[0]], inv[e.vertices[1]]
        if a != b:
            w = float(np.linalg.norm(Q[a] - Q[b])); adj[a].append((b, w)); adj[b].append((a, w))
    dist = np.full(n, np.inf); h = []
    for i in np.unique(inv[np.nonzero(seeds)[0]]):
        dist[i] = 0.0; h.append((0.0, int(i)))
    heapq.heapify(h)
    while h:
        dd, a = heapq.heappop(h)
        if dd > dist[a]:
            continue
        for b, w in adj[a]:
            nd = dd + w
            if nd < dist[b]:
                dist[b] = nd; heapq.heappush(h, (nd, b))
    return dist[inv]


def _vert_colors(body):
    """Base-colour texture sample per vertex (last loop wins at UV seams)."""
    img = next(n.image for n in body.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
    w, h = img.size; px = np.array(img.pixels[:]).reshape(h, w, 4)
    uvl = body.data.uv_layers[0].data; C = np.zeros((len(body.data.vertices), 3))
    for l in body.data.loops:
        u, v = uvl[l.index].uv
        C[l.vertex_index] = px[min(int(v * h), h - 1), min(int(u * w), w - 1), :3]
    return C


def _read_weights(body):
    names = [vg.name for vg in body.vertex_groups]
    W = np.zeros((len(body.data.vertices), len(names)))
    for v in body.data.vertices:
        for gr in v.groups:
            W[v.index, gr.group] = gr.weight
    return names, W


def _write_weights(body, W, rows):
    for i in rows:
        v = body.data.vertices[int(i)]
        for gr in list(v.groups):
            body.vertex_groups[gr.group].remove([v.index])
        for k in np.nonzero(W[i] > 1e-4)[0]:
            body.vertex_groups[int(k)].add([v.index], float(W[i, k]), 'REPLACE')


# ---------------------------------------------------------------- after_skin: chain bones and weights
def after_skin(g):
    fc = _fc(g)
    if not fc:
        return
    body, rig = g["body"], g["rig"]
    chains = fc.get("chains", [])
    g["FORT_CHAINS"] = {}
    if chains:
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        eb = rig.data.edit_bones
        for ch in chains:
            pts = ch["points"]; names = []
            for k in range(len(pts) - 1):
                n = f"{ch['name']}_{k:02d}"
                b = eb.new(n); b.head, b.tail = Vector(pts[k]), Vector(pts[k + 1]); b.roll = 0
                b.parent = eb[ch["parent"]] if k == 0 else eb[names[-1]]
                names.append(n)
            g["FORT_CHAINS"][ch["name"]] = names
        bpy.ops.object.mode_set(mode='OBJECT')
        for ch in chains:
            for k, n in enumerate(g["FORT_CHAINS"][ch["name"]]):
                body.vertex_groups.new(name=n)
                g["bone_names"].append(n)
                g["parent_of"][n] = ch["parent"] if k == 0 else g["FORT_CHAINS"][ch["name"]][k - 1]
                g["STATIC"].add(n)          # posed by after_pose; static until then
    P = np.array([v.co[:] for v in body.data.vertices])
    names, W = _read_weights(body)
    col = {n: i for i, n in enumerate(names)}
    rigid = np.zeros(len(P), bool)
    rigid[list(g.get("taken", set()))] = True
    touched = np.zeros(len(P), bool)

    def _apply_reweight(regs, W, touched):
        for reg in regs:
            a = _alpha(P, reg) * ~rigid
            if "maxBlueMinusRed" in reg:     # colour gate: keep only brownish/reddish texels (wood, leather)
                if "_C" not in g:
                    g["_C"] = _vert_colors(body)
                a = a * ((g["_C"][:, 2] - g["_C"][:, 0]) <= reg["maxBlueMinusRed"])
            if not a.any():
                continue
            new = W.copy()
            if "strip" in reg:
                cols = [i for n, i in col.items() if n.endswith(tuple(reg["strip"])) and not n.startswith("Root")]
                new[:, cols] = 0
            if "set" in reg or "zBlend" in reg:
                tgt = np.zeros_like(W)
                if "set" in reg:
                    for n, w in reg["set"].items():
                        tgt[:, col[n]] = w
                else:
                    zs = [z for z, _ in reg["zBlend"]]
                    for j, (z, n) in enumerate(reg["zBlend"]):
                        e = np.zeros(len(zs)); e[j] = 1
                        tgt[:, col[n]] += np.interp(P[:, 2], zs, e)
                new = tgt if "strip" not in reg else new
            lost = new.sum(1) <= 1e-6
            if lost.any():                       # stripped everything: fall back to the listed target
                fb = reg.get("fallback", "Hips")
                new[lost, col[fb]] = 1.0
            new /= np.maximum(new.sum(1, keepdims=True), 1e-9)
            W = W * (1 - a[:, None]) + new * a[:, None]
            touched |= a > 0
            print("FORT reweight", reg.get("name", "?"), int((a > 0).sum()), "verts")
        return W, touched

    W, touched = _apply_reweight(fc.get("reweight", []), W, touched)
    if chains:
        # distance to every non-chain bone segment (rest)
        bones = rig.data.bones
        chain_bones = {n for v in g["FORT_CHAINS"].values() for n in v}
        absorbed = {n for ch in chains for n in ch.get("absorb", [])}
        missing = sorted(n for n in absorbed if n not in bones)
        if missing:
            raise SystemExit(f"fortress chains absorb unknown bones {missing}")
        others = [b for b in bones if b.name != "Root" and b.name not in chain_bones and b.name not in absorbed
                  and b.use_deform]
        best = np.full(len(P), np.inf); owner = -np.ones(len(P), int); upos = np.zeros(len(P)); sdist = np.zeros(len(P))
        GEO = None
        if any(ch.get("geodesic") for ch in chains):
            # geodesic ownership: seed each group (the non-chain skeleton, every chain) with the
            # vertices that are clearly nearest to it in space, then give every vertex to the group
            # nearest along the surface
            od_all = np.min(np.stack([_seg_dist(P, np.array(b.head_local), np.array(b.tail_local))[0] for b in others], 1), 1)
            dcs = [np.min(np.stack([_seg_dist(P, np.array(c["points"][k]), np.array(c["points"][k + 1]))[0]
                                    for k in range(len(c["points"]) - 1)], 1), 1) for c in chains]
            DD = np.stack([od_all] + dcs, 1)
            srt = np.sort(DD, 1); lab = DD.argmin(1)
            clear = (srt[:, 0] < 0.7 * srt[:, 1]) & (srt[:, 0] < 0.15)
            GEO = np.stack([_geodesic(body, P, clear & (lab == j)) for j in range(DD.shape[1])], 1)
            GOWN = GEO.argmin(1)
        for ci, ch in enumerate(chains):
            pts = np.array(ch["points"], float)
            seglen = np.linalg.norm(np.diff(pts, axis=0), axis=1); cum = np.r_[0, np.cumsum(seglen)]
            D = np.stack([_seg_dist(P, pts[k], pts[k + 1])[0] for k in range(len(pts) - 1)], 1)
            T = np.stack([_seg_dist(P, pts[k], pts[k + 1])[1] for k in range(len(pts) - 1)], 1)
            k = D.argmin(1); d = D[np.arange(len(P)), k]; t = T[np.arange(len(P)), k]
            s = cum[k] + t * seglen[k]
            od = np.min(np.stack([_seg_dist(P, np.array(b.head_local), np.array(b.tail_local))[0]
                                  for b in others if b.name != ch["parent"]], 1), 1)
            if ch.get("geodesic"):
                # ownership along the surface: a folded wing lying against the tail or a leg is
                # nearer to them in space but far from them over the mesh
                gc = GEO[:, ci + 1]
                ok = (GOWN == ci + 1) & (gc < ch["geodesic"]) & ~rigid
                d = gc
            else:
                ok = (d < ch.get("radius", 0.2)) & (d <= ch.get("ratio", 1.0) * od) & ~rigid
            if "box" in ch:
                ok &= _region_dist(P, {"box": ch["box"]}) <= 0
            # the chain starts at its first point: nothing "before" it (t=0 on segment 0 with the
            # point behind the root) unless it is within the root blend anyway
            better = ok & (d < best)
            best[better] = d[better]; owner[better] = ci; upos[better] = k[better] + t[better]; sdist[better] = s[better]
        for ci, ch in enumerate(chains):
            names_c = g["FORT_CHAINS"][ch["name"]]; nb = len(names_c)
            rows = np.nonzero(owner == ci)[0]
            if not len(rows):
                continue
            u = upos[rows]
            cw = np.zeros((len(rows), nb))
            for k in range(nb):
                cw[:, k] = np.maximum(0, 1 - np.abs(u - (k + 0.5)))
            cw[u < 0.5, 0] = 1.0; cw[u > nb - 0.5, nb - 1] = 1.0
            cw /= np.maximum(cw.sum(1, keepdims=True), 1e-9)
            a = np.clip(sdist[rows] / max(ch.get("rootBlend", 0.1), 1e-6), 0, 1)
            new = W[rows] * (1 - a[:, None])
            for k, n in enumerate(names_c):
                new[:, col[n]] += cw[:, k] * a
            W[rows] = new / np.maximum(new.sum(1, keepdims=True), 1e-9)
            touched[rows] = True
            print("FORT chain", ch["name"], "bones", nb, "verts", len(rows))
        # flesh outside every chain that heat still ties to an absorbed bone would stay with that bone's
        # parent while its neighbours ride the chain: move that weight onto the nearest chain bone
        for ci, ch in enumerate(chains):
            ab = [col[n] for n in ch.get("absorb", []) if n in col]
            if not ab:
                continue
            names_c = g["FORT_CHAINS"][ch["name"]]; pts = np.array(ch["points"], float)
            rows = np.nonzero((owner < 0) & (W[:, ab].sum(1) > 1e-6) & ~rigid)[0]
            if len(rows):
                D = np.stack([_seg_dist(P[rows], pts[k], pts[k + 1])[0] for k in range(len(pts) - 1)], 1)
                kk = D.argmin(1); moved = W[rows][:, ab].sum(1)
                W[np.ix_(rows, ab)] = 0.0
                for j, k in enumerate(kk):
                    W[rows[j], col[names_c[k]]] += moved[j]
                touched[rows] = True
            print("FORT chain", ch["name"], "absorbed", ch["absorb"], "outside-chain verts moved", len(rows))
    if fc.get("fillUnweighted"):
        # vertices left with no weight at all (small islands bone heat never reached, e.g. a fly's
        # fangs or a claw tip beyond the chain radius) stay at the origin pose and draw long slivers:
        # give each the weights of the nearest weighted vertex (rest space)
        from mathutils.kdtree import KDTree
        zero = W.sum(1) <= 1e-6
        if zero.any() and (~zero).any():
            src = np.nonzero(~zero)[0]; kd = KDTree(len(src))
            for j, i in enumerate(src):
                kd.insert(Vector(P[i]), j)
            kd.balance()
            for i in np.nonzero(zero)[0]:
                W[i] = W[src[kd.find(Vector(P[i]))[1]]]
            touched |= zero
        print("FORT fillUnweighted", int(zero.sum()), "verts")
    # postReweight: same specs as reweight, applied after the chains (e.g. hand a fly's mandibles
    # back to the Head where the body chain passes close under them)
    W, touched = _apply_reweight(fc.get("postReweight", []), W, touched)
    # keep 4 influences
    idx = np.argsort(-W, 1)[:, 4:]
    W2 = W.copy(); np.put_along_axis(W2, idx, 0, 1); W2 /= np.maximum(W2.sum(1, keepdims=True), 1e-9)
    _write_weights(body, W2, np.nonzero(touched)[0])
    if fc.get("armSplit"):
        _arm_split(g, fc["armSplit"])
    if fc.get("chainCut"):
        _chain_cut(g, fc["chainCut"])


# ---------------------------------------------------------------- fused-part cuts (after all weights)
def _rows(body):
    gname = {x.index: x.name for x in body.vertex_groups}
    return [{gname[x.group]: x.weight for x in v.groups if x.weight > 0} for v in body.data.vertices]


def _put_rows(body, rows, ids):
    vg = body.vertex_groups
    for i in ids:
        top = sorted(rows[i].items(), key=lambda kv: -kv[1])[:4]; t = sum(w for _, w in top)
        if t <= 0:
            continue
        v = body.data.vertices[int(i)]
        for x in list(v.groups):
            vg[x.group].remove([v.index])
        for k, w in top:
            vg[k].add([v.index], w / t, 'REPLACE')


def _split_by_label(body, rows, lab, pairs):
    """Split the mesh along edges whose two faces carry labels forming one of `pairs` (a face's
    label = the majority label of its corners). Afterwards every corner whose faces all carry one
    label L different from its own takes the weights of the nearest original vertex labelled L,
    so no face is left straddling the cut. Weights stay within 4 influences."""
    import bmesh
    from mathutils.kdtree import KDTree
    me = body.data; n = len(me.vertices); gid = {x.name: x.index for x in body.vertex_groups}
    bm = bmesh.new(); bm.from_mesh(me)
    bm.faces.ensure_lookup_table(); dl = bm.verts.layers.deform.verify()
    flab = {}
    for f in bm.faces:
        ls = [int(lab[v.index]) for v in f.verts]
        c = max(set(ls), key=ls.count)
        flab[f.index] = c if 2 * ls.count(c) > len(ls) else -2
    pairs = {tuple(sorted(p)) for p in pairs}
    cut = [e for e in bm.edges
           if len({flab[f.index] for f in e.link_faces}) == 2
           and tuple(sorted({flab[f.index] for f in e.link_faces})) in pairs]
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    P = np.array([v.co[:] for v in me.vertices])
    trees = {}
    for L in {l for p in pairs for l in p}:
        ids = np.nonzero(lab == L)[0]
        if not len(ids):
            continue
        t = KDTree(len(ids))
        for k, i in enumerate(ids):
            t.insert(Vector(P[i]), k)
        t.balance(); trees[L] = (t, ids)
    fixed = 0
    for v in bm.verts:
        if not v.link_faces:
            continue
        fl = {flab[f.index] for f in v.link_faces}
        if len(fl) != 1:
            continue
        L = fl.pop()
        if L not in trees or (v.index < n and lab[v.index] == L):
            continue
        t, ids = trees[L]; j = int(ids[t.find(v.co)[1]])
        top = sorted(rows[j].items(), key=lambda kv: -kv[1])[:4]; tt = sum(w for _, w in top)
        if tt <= 0:
            continue
        d = v[dl]; d.clear()
        for k, w in top:
            d[gid[k]] = w / tt
        fixed += 1
    bm.to_mesh(me); bm.free()
    return len(cut), fixed


def _arm_split(g, cfg):
    """Arms Meshy fused to the flank or robe (a lizardman bow arm, a shaman forearm on the robe):
    bone heat smears Hand/ForeArm weight into the flank and body weight into the arm, and the band
    between stretches into a sheet when the arm lifts. Adapted from the castle hand cut and the
    inferno straddle cut:
      1. ARM = vertices within foreRadius of the ForeArm or handRadius of the Hand segment whose
         nearest deform bone is in that arm chain (a thigh under the hand is not taken);
      2. every other vertex loses that side's ForeArm/Hand weight, and Arm/Shoulder weight too when
         it lies farther than armKeep from the upper-arm segment; the removed share goes to the
         weights of the nearest vertex that carries no such weight;
      3. ARM vertices keep only their arm-chain weights;
      4. edges between ARM faces and body faces (arm share < 0.5) are split and corners re-weighted
         to their face's side, so the arm lifts off the flank cleanly.
    Rigid prop vertices are left alone. Config: {"sides": ["Left"], "foreRadius": 0.07,
    "handRadius": 0.09, "armKeep": 0.12, "perSide": {"Right": {...}}}"""
    from mathutils.kdtree import KDTree
    body, rig = g["body"], g["rig"]
    rigid = set(int(i) for i in g.get("taken", set()))
    V = body.data.vertices; n = len(V)
    notrig = np.array([i not in rigid for i in range(n)])
    P = np.array([v.co[:] for v in V]); rows = _rows(body)
    seg = {b.name: (np.array(b.head_local[:]), np.array(b.tail_local[:])) for b in rig.data.bones
           if b.use_deform and b.name != "Root" and b.name in body.vertex_groups}
    names = list(seg)
    D = np.stack([_seg_dist(P, *seg[b])[0] for b in names], 1); near = np.array(names)[D.argmin(1)]
    ARM = np.zeros(n, bool); report = []
    for side in cfg.get("sides", ["Left", "Right"]):
        c = dict(cfg); c.update(cfg.get("perSide", {}).get(side, {}))
        chain = [side + b for b in ("Shoulder", "Arm", "ForeArm", "Hand", "Hand_End")]
        low = {side + "ForeArm", side + "Hand"}; up = {side + "Arm", side + "Shoulder"}
        dh = _seg_dist(P, *seg[side + "Hand"])[0]; df = _seg_dist(P, *seg[side + "ForeArm"])[0]
        da = _seg_dist(P, *seg[side + "Arm"])[0]
        arm = ((dh < c.get("handRadius", 0.09)) | (df < c.get("foreRadius", 0.07))) & np.isin(near, chain) & notrig
        ARM |= arm
        moved = np.zeros(n)
        for i in range(n):
            if not notrig[i]:
                continue
            if arm[i]:
                keep = {k: w for k, w in rows[i].items() if k in chain}
                if keep and sum(keep.values()) > 1e-4:
                    rows[i] = keep
                continue
            strip = set(low) | (up if da[i] > c.get("armKeep", 0.12) else set())
            for b in strip:
                moved[i] += rows[i].pop(b, 0.0)
        allarm = low | up
        donor = [i for i in range(n) if notrig[i] and not ARM[i] and moved[i] == 0
                 and sum(rows[i].values()) > 0.5 and not any(b in rows[i] for b in allarm)]
        tree = KDTree(len(donor))
        for k, i in enumerate(donor):
            tree.insert(Vector(P[i]), k)
        tree.balance()
        for i in np.nonzero(moved > 1e-6)[0]:
            dnr = rows[donor[tree.find(Vector(P[i]))[1]]]; s_ = sum(dnr.values())
            for k, w in dnr.items():
                rows[i][k] = rows[i].get(k, 0.0) + moved[i] * w / s_
        report.append((side, int(arm.sum()), int((moved > 1e-6).sum())))
    armb = {s_ + b for s_ in ("Left", "Right") for b in ("Shoulder", "Arm", "ForeArm", "Hand")}
    armw = np.array([sum(w for k, w in r.items() if k in armb) / max(sum(r.values()), 1e-9) for r in rows])
    lab = np.where(ARM, 1, np.where(armw < 0.5, 0, 2))
    lab[~notrig] = -1
    _put_rows(body, rows, np.nonzero(notrig)[0])
    ncut, nfix = _split_by_label(body, rows, lab, [(0, 1)])
    print("FORT armSplit", report, "split edges", ncut, "corners re-weighted", nfix)


def _chain_cut(g, specs):
    """Cut between parts Meshy fused that move apart (a wyvern wing tip lying on its tail):
    vertices are labelled by their top bone (prefix match against each spec's "a" / "b" lists) and
    the edges between an "a" face and a "b" face are split, corners re-weighted to their face's
    side. Config: [{"a": ["WingR_03", "WingR_04"], "b": ["Tail_", "Hips"]}]"""
    body = g["body"]
    rigid = set(int(i) for i in g.get("taken", set()))
    for k, sp in enumerate(specs):
        rows = _rows(body); n = len(rows)
        top = [max(r, key=r.get) if r else "" for r in rows]
        lab = np.full(n, -1)
        for i, t in enumerate(top):
            if i in rigid:
                continue
            if any(t.startswith(p) for p in sp["a"]):
                lab[i] = 1
            elif any(t.startswith(p) for p in sp["b"]):
                lab[i] = 0
        ncut, nfix = _split_by_label(body, rows, lab, [(0, 1)])
        print("FORT chainCut", k, "a", int((lab == 1).sum()), "b", int((lab == 0).sum()), "split edges", ncut, "corners", nfix)


# ---------------------------------------------------------------- procedural pose + silhouette fit
def _clip_table(g):
    ms = json.load(open(g["MASTER"]))
    tab = [None] * len(ms["frames"])
    for s in ms["segments"]:
        n = s["frameCount"]
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            tab[t] = (s["contractSuffix"], i, n)
    return tab, ms


def _spec_value(spec, i, n, loop):
    if isinstance(spec, (int, float)):
        return float(spec)
    v = spec.get("offset", 0.0)
    if "sin" in spec:
        ph = 2 * math.pi * spec.get("cycles", 1) * (i / max(n, 1)) + math.radians(spec.get("phase", 0.0))
        v += spec["sin"] * math.sin(ph)
    if "alt" in spec:                        # alternate sign every DEF frame (insect wing beat)
        v += spec["alt"] * (1.0 if i % 2 == 0 else -1.0)
    if "ramp" in spec:                       # loop-closing linear ramp (a wave's phase)
        v += spec["ramp"] * i / max(n, 1)
    if "keys" in spec:
        u = i / max(n - 1, 1)
        ks = spec["keys"]
        v += float(np.interp(u, [k[0] for k in ks], [k[1] for k in ks]))
    return v


def after_pose(g):
    fc = _fc(g)
    if not fc:
        return
    for names in g.get("FORT_CHAINS", {}).values():
        for n in names:
            g["STATIC"].discard(n)
    if not (fc.get("procedural") or fc.get("params") or g.get("FORT_CHAINS")):
        return
    rest, parent_of, posed = g["rest"], g["parent_of"], g["posed_world"]
    T = len(posed)
    allb = [n for n in posed[0] if n != "Root"]
    depth = {}
    def dep(n):
        if n == "Root":
            return 0
        if n not in depth:
            depth[n] = dep(parent_of[n]) + 1
        return depth[n]
    order = sorted(allb, key=dep)
    restR = {n: rest[n].to_3x3() for n in allb}
    rel = {n: rest[parent_of[n]].inverted() @ rest[n] for n in allb}
    chains = {k: v for k, v in g.get("FORT_CHAINS", {}).items()}
    chain_of = {b: c for c, v in chains.items() for b in v}
    PR = fc.get("params", {})
    tab, ms = _clip_table(g)
    loops = set(g["LOOPS"])
    anim = fc.get("anim", {})
    proc = fc.get("procedural", False)

    def base_values(t):
        clip, i, n = tab[t]
        vals = {}
        for src in ("*", clip):
            for p, spec in anim.get(src, {}).items():
                vals[p] = vals.get(p, 0.0) + _spec_value(spec, i, n, clip in loops)
        return vals

    def locals_of(A):
        Q = {}
        for n in order:
            p = parent_of[n]
            Q[n] = rel[n].inverted() @ A[p].inverted() @ A[n]
        return Q

    Qcap = [None if proc else locals_of(posed[t]) for t in range(T)]
    fwd = Vector((0.416, 0.893, -0.174)).normalized()

    def rot_deltas(vals):
        """rest-world rotation delta per bone (D), from rot and chain params."""
        D = {}
        for p, v in vals.items():
            spec = PR.get(p)
            if not spec or not v or spec["type"] != "rot":
                continue
            ax = Vector(spec["axis"]).normalized()
            for b, share in spec["bones"]:
                D[b] = D.get(b, Matrix.Identity(3)) @ Matrix.Rotation(math.radians(v * share), 3, ax)
        for c, names in chains.items():
            nb = len(names)
            G = [Matrix.Identity(3) for _ in range(nb)]
            specs = [(p, PR[p]) for p in vals if p in PR and PR[p]["type"] == "chain"
                     and c in (PR[p]["chain"] if isinstance(PR[p]["chain"], list) else [PR[p]["chain"]])]
            if not specs:
                continue
            restdir = [(rest[n].to_3x3().col[1]).normalized() for n in names]
            for k in range(nb):
                Gk = Matrix.Identity(3)
                for p, spec in specs:
                    v = vals[p]
                    if spec["mode"] == "straight" and v:
                        tgt = restdir[k].slerp(Vector(spec["dir"]).normalized(), min(1.0, max(0.0, v)))
                        Gk = restdir[k].rotation_difference(tgt).to_matrix() @ Gk
                for p, spec in specs:
                    v = vals[p]
                    if spec["mode"] == "curl" and v:
                        w = spec.get("weights")
                        f = (sum(w[:k + 1]) / sum(w)) if w else (k + 1) / nb
                        Gk = Matrix.Rotation(math.radians(v * f), 3, Vector(spec["axis"]).normalized()) @ Gk
                    elif spec["mode"] == "wave" and v:
                        ph = math.radians(vals.get(spec.get("phaseParam", ""), 0.0))
                        lam = spec.get("wavelength", nb)
                        env = min(1.0, (k + 1) / max(spec.get("grow", 1), 1))
                        ang = v * env * math.sin(2 * math.pi * k / lam - ph)
                        Gk = Matrix.Rotation(math.radians(ang), 3, Vector(spec["axis"]).normalized()) @ Gk
                G[k] = Gk
            for k, n in enumerate(names):
                Dk = (G[k - 1].inverted() if k else Matrix.Identity(3)) @ G[k]
                D[n] = Dk @ D.get(n, Matrix.Identity(3))
        return D

    def compose(t, vals):
        A = {"Root": rest["Root"].copy()}
        D = rot_deltas(vals)
        for n in order:
            if Qcap[t] is not None and n not in chain_of:
                Q = Qcap[t][n].copy()
            else:
                Q = Matrix.Identity(4)
            if n in D:
                Q = Q @ (restR[n].inverted() @ D[n] @ restR[n]).to_4x4()
            A[n] = A[parent_of[n]] @ rel[n] @ Q
        dx, dy, roll = vals.get("dx", 0.0), vals.get("dy", 0.0), vals.get("roll", 0.0)
        lift = vals.get("lift", 0.0)
        if dx or dy or roll or lift:
            hv = A["Hips"].translation.copy()
            Tm = (Matrix.Translation(CAM["right"] * (dx / CAM["s"]) + CAM["up"] * (dy / CAM["s"]) + Vector((0, 0, lift)))
                  @ Matrix.Translation(hv) @ Matrix.Rotation(math.radians(roll), 4, CAM["fwd"]) @ Matrix.Translation(-hv))
            for n in order:
                A[n] = Tm @ A[n]
        return A

    # sprite camera (same construction as build_unit, which builds it after this hook). A unit may
    # turn the camera about the vertical ("camYaw", degrees, or a "camYawSearch" list scored on idle
    # frame 0): a quadruped's DEF shows it in near-profile, a humanoid's in three-quarter view. The
    # model itself is never turned (its forward stays -Y); before_keys moves the render camera.
    body = g["body"]
    sj = json.load(open(g["SPRITE"])); SW, SH = sj["size"]
    V0 = np.array([v.co[:] for v in body.data.vertices])
    fwd0 = fwd.copy()
    CAM = {}
    def set_cam(yaw):
        f = (Matrix.Rotation(math.radians(yaw), 3, 'Z') @ fwd0).normalized()
        r = f.cross(Vector((0, 0, 1))).normalized(); u = r.cross(f).normalized()
        xs = V0 @ np.array(r); ys = V0 @ np.array(u)
        bx0, by0, bx1, by1 = sj["bbox0"]
        s_ = (by1 - by0) / (ys.max() - ys.min())
        CAM.update({"yaw": yaw, "fwd": f, "right": r, "up": u, "s": s_, "oy": by1 + s_ * ys.min(),
                    "ox": (bx0 + bx1) / 2 - s_ * (xs.max() + xs.min()) / 2, "R": np.array(r), "U": np.array(u)})
    set_cam(fc.get("camYaw", 0.0))

    FIT = fc.get("fit")
    fitlog = []
    if FIT:
        # skinning matrix; groups whose bone is not posed yet (wings) follow their parent bone
        names_all = order
        colx = {n: i for i, n in enumerate(names_all)}
        sub = np.arange(len(V0))
        if len(sub) > 7000:
            sub = sub[:: int(math.ceil(len(sub) / 7000))]
        Vh = np.c_[V0[sub], np.ones(len(sub))]
        Wm = np.zeros((len(sub), len(names_all)))
        gname = {gr.index: gr.name for gr in body.vertex_groups}
        bones = g["rig"].data.bones
        def posed_name(n):
            while n not in colx and n in bones and bones[n].parent is not None:
                n = bones[n].parent.name
            return n if n in colx else None
        pos = {i: k for k, i in enumerate(sub)}
        for v in body.data.vertices:
            k = pos.get(v.index)
            if k is None:
                continue
            for gr in v.groups:
                n = posed_name(gname[gr.group])
                if n:
                    Wm[k, colx[n]] += gr.weight
        Wm /= np.maximum(Wm.sum(1, keepdims=True), 1e-9)
        used = [n for n in names_all if Wm[:, colx[n]].max() > 0]
        restinv = {n: np.array(rest[n].inverted()) for n in used}

        def skin(A):
            out = np.zeros((len(sub), 3))
            for n in used:
                M = np.array(A[n]) @ restinv[n]
                out += Wm[:, colx[n]][:, None] * (Vh @ M.T)[:, :3]
            return out

        def splat(Pp):
            x = np.round(CAM["ox"] + CAM["s"] * (Pp @ CAM["R"])).astype(int); y = np.round(CAM["oy"] - CAM["s"] * (Pp @ CAM["U"])).astype(int)
            ok = (x >= 1) & (x < SW - 1) & (y >= 1) & (y < SH - 1)
            m = np.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
            gg = m.copy()
            for dy_, dx_ in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                gg |= np.roll(np.roll(m, dy_, 0), dx_, 1)
            return gg

        def def_mask(path):
            img = bpy.data.images.load(path, check_existing=True)
            a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 0.99
            bpy.data.images.remove(img); return a

        lim_all = {"dx": [-40, 40], "dy": [-80, 80], "roll": [-60, 60], "lift": [-0.5, 0.5]}
        lim_all.update({p: s.get("limit", [-60, 60]) for p, s in PR.items()})
        lim_all.update(FIT.get("limits", {}))
        step0 = {"dx": 8, "dy": 8, "roll": 8, "lift": 0.08}
        step0.update({p: s.get("step", 12 if s["type"] != "chain" or s["mode"] != "straight" else 0.25) for p, s in PR.items()})
        lam, lam2 = FIT.get("penalty", 0.0015), FIT.get("smooth", 0.0015)
        scale = {p: (1.0 / max(step0[p], 1e-6)) * 8 for p in step0}      # penalties per 8-unit step
        prev = {}
        if FIT.get("camYawSearch"):
            tgt0 = def_mask(ms["frames"][0]["sourcePng"]); A0 = compose(0, base_values(0))
            def yaw_score(yaw):
                set_cam(yaw); P0 = skin(A0); best_ = 0.0
                for ddx in range(-24, 25, 4):
                    for ddy in range(-12, 13, 4):
                        m = splat(P0 + CAM["R"] * ddx / CAM["s"] + CAM["U"] * ddy / CAM["s"])
                        best_ = max(best_, (m & tgt0).sum() / max((m | tgt0).sum(), 1))
                return best_
            ys_ = {y: yaw_score(y) for y in FIT["camYawSearch"]}
            set_cam(max(ys_, key=ys_.get))
            print("FORT camYaw", CAM["yaw"], {k: round(float(v), 3) for k, v in ys_.items()})
    g["FORT_CAM"] = dict(CAM)
    TIP = (FIT or {}).get("tip")
    if TIP:
        unknown = set(TIP) - {"clips", "side", "weight"}
        if unknown or TIP.get("side") not in ("right", "left") or not TIP.get("clips") or not TIP.get("weight"):
            raise SystemExit(f"fortress fit.tip needs clips, side right|left and weight (unknown {sorted(unknown)})")

    def lead_tip(m):
        ys_, xs_ = np.nonzero(m)
        if not len(xs_):
            return None
        xe = xs_.max() if TIP["side"] == "right" else xs_.min()
        near = np.abs(xs_ - xe) <= 2
        return float(xe), float(ys_[near].mean())

    for t in range(T):
        vals = base_values(t)
        if FIT:
            clip = tab[t][0]
            fp = list(FIT.get("params", [])) + list(FIT.get("clips", {}).get(clip, []))
            fp = [p for p in fp if p not in FIT.get("skip", {}).get(clip, [])]
            target = def_mask(ms["frames"][t]["sourcePng"])
            tip_t = lead_tip(target) if TIP and clip in TIP["clips"] else None
            off = {p: prev.get(p, 0.0) for p in fp}
            def score(o):
                vv = dict(vals)
                for p, x in o.items():
                    vv[p] = vv.get(p, 0.0) + x
                m = splat(skin(compose(t, vv)))
                iou = (m & target).sum() / max((m | target).sum(), 1)
                pen = sum(lam * abs(x) * scale[p] + lam2 * abs(x - prev.get(p, 0.0)) * scale[p] for p, x in o.items())
                if tip_t is not None:
                    tm = lead_tip(m)
                    err = 1e3 if tm is None else abs(tm[0] - tip_t[0]) + abs(tm[1] - tip_t[1])
                    pen += TIP["weight"] * err
                    score.tip_err = err
                return iou - pen, iou
            zero = {p: 0.0 for p in fp}
            best, _ = score(off); zb, base_iou = score(zero)
            if zb > best:                        # never start worse than the plain base pose
                best, off = zb, zero
            # coarse scan of the big whole-body moves (rearing, lying down, a tail swung straight):
            # coordinate descent from the previous frame cannot jump that far on its own
            scan = {p: v for p, v in FIT.get("scan", {}).items() if p in fp}
            if scan:
                import itertools
                keys = list(scan)
                for combo in itertools.product(*[scan[k] for k in keys]):
                    c = dict(off); c.update({k: float(v) for k, v in zip(keys, combo)})
                    sc_ = score(c)[0]
                    if sc_ > best + 1e-6:
                        best, off = sc_, c
            for level in range(4):
                improved = True
                while improved:
                    improved = False
                    for p in fp:
                        st = step0[p] / (2 ** level)
                        for sg in (1, -1):
                            c = dict(off); c[p] = min(lim_all[p][1], max(lim_all[p][0], c[p] + sg * st))
                            sc_ = score(c)[0]
                            if sc_ > best + 1e-6:
                                best, off, improved = sc_, c, True
            # log the chosen pose's own IoU / tip error. Before 2026-09-30 this ran after `vals` had
            # already absorbed `off`, so the log scored every offset twice (the wyvern's Move read
            # IoU 0.03-0.16 for a pose the finished .blend matches at 0.48-0.56); the pose was right
            fin = score(off)[1]
            prev = off
            for p, x in off.items():
                vals[p] = vals.get(p, 0.0) + x
            fitlog.append({"frame": t, "clip": clip, "iou0": round(float(base_iou), 3), "iou": round(float(fin), 3),
                           **({"tipErr": round(float(score.tip_err), 1)} if tip_t is not None else {}),
                           **{p: round(x, 2) for p, x in off.items()}})
        A = compose(t, vals)
        posed[t].clear(); posed[t].update(A)
    if FIT:
        json.dump(fitlog, open(g["OUT"] + ".fortfit.json", "w"), indent=0)
        print("FORT fit mean IoU", round(float(np.mean([f["iou"] for f in fitlog])), 3),
              "from", round(float(np.mean([f["iou0"] for f in fitlog])), 3))
    print("FORT posed", T, "frames", "procedural" if proc else "capture+chains")


# ---------------------------------------------------------------- before_keys: wing beat
def _move_camera(g):
    """Re-aim build_unit's sprite camera by the unit's chosen yaw (see after_pose)."""
    C = g.get("FORT_CAM")
    if not C or not C.get("yaw"):
        return
    cam = g["cam"]; SW, SH = g["SW"], g["SH"]
    f, r, u, s_px, ox, oy = C["fwd"], C["right"], C["up"], C["s"], C["ox"], C["oy"]
    cam.data.ortho_scale = max(SW, SH) / s_px
    cam.location = r * ((SW / 2 - ox) / s_px) + u * ((oy - SH / 2) / s_px) - f * 8
    cam.rotation_euler = f.to_track_quat('-Z', 'Y').to_euler()
    json.dump({"right": list(r), "up": list(u), "forward": list(f), "pxPerUnit": s_px, "offset": [ox, oy],
               "size": [SW, SH], "yaw": C["yaw"]}, open(g["OUT"] + ".spritecam.json", "w"))
    print("FORT camera yaw", C["yaw"])


def before_keys(g):
    if _fc(g):
        _move_camera(g)
    fc = _fc(g); fl = fc.get("flap")
    if not fl:
        return
    tab, _ = _clip_table(g)
    rest, posed = g["rest"], g["posed_world"]
    for t, A in enumerate(posed):
        clip, i, n = tab[t]
        amp = fl.get("clips", {}).get(clip, fl.get("amp", 30.0))
        if not amp:
            continue
        s = (1.0 if i % 2 == 0 else -1.0) if fl.get("mode", "alternate") == "alternate" else math.sin(2 * math.pi * fl.get("cycles", 3) * i / max(n, 1))
        for b, sign in fl["bones"].items():
            if b not in A:
                continue
            axis_l = rest[b].to_3x3().inverted() @ Vector(fl.get("axis", (0, 1, 0)))
            A[b] = A[b] @ Matrix.Rotation(math.radians(amp * s * sign), 4, axis_l)
    print("FORT flap", fl.get("amp"))
