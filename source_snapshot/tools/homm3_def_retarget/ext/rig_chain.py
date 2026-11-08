"""Rig surgery: add a bone chain cut from existing geometry (trunks, tails, tentacles, ears; any faction).

Some meshes model a long soft limb that the rig never got: the mammoth trunk rides the Head bone rigidly, so the
DEF trunk lift and reach (h3_mammoth AttackFront, Mouseover) can only be faked by tipping the whole head. This
hook adds a chain of bones along the limb's traced centreline and hands the limb's existing vertices to it with
smooth hat weights (no edge split, no new geometry), the way inferno_whipchain does for a held whip. Unlike the
whip chain it needs no `props` cut: the vertices are picked by distance to the centreline, optional exclude
regions (tusks, horns), and their current share of the parent bone, and the old weights fade into the chain
over a root blend, so the join to the head stays smooth.

  "extensions": [..., "rig_chain"],
  "rigChains": [{"prefix": "Trunk", "parent": "Head", "bones": 6,
                 "points": [[x, y, z], ...],      # centreline, root first (Blender body axes, unit config space)
                 "radius": 0.12,                  # or one radius per point (linearly interpolated along arc length)
                 "root": 0.04,                    # arc length at the root that keeps its current weights
                 "rootBlend": 0.12,               # then the chain fades in over this arc length
                 "minParent": 0.5,                # only vertices whose parent-bone share is at least this
                 "exclude": [<region>, ...],      # stronghold_props regions (segments | sphere | box) left alone
                 "cut": {"belowZ": 0.8, "web": "parent"},   # optional mesh surgery, see below
                 "smoothArc": 6,                  # optional: Laplacian passes on the arc coordinate (wide limbs)
                 "reason": "..."}]

cut (optional): a limb modelled fused to its neighbours (the mammoth trunk's lower curl is webbed to the tusk tips and
the cheeks by long triangles) tears those web faces as soon as the chain moves. In after_skin the faces whose vertices
are all chain vertices are split from the rest along every edge between the two below `belowZ` (config z; the attached
root stays welded). "web": "parent" (the only mode) splits the shared edges (bmesh split_edges): the web faces keep
their old weights and stay with the head, the limb's copies go to the chain. No vertex moves and no face is added or
removed (deleting the web faces instead broke verify_glb's Unit_Death mesh round trip, lane C 2026-10-11).

Pair it with "correctiveSmooth": {"excludeBones": [<prefix>_00, ...]}: Corrective Smooth on a thin bent ribbon (the
trunk shell) folds its local frames and throws neighbouring vertices apart (lane C h3_mammoth_upg_alt: 19x edge stretch
between two vertices with equal weights); the chain bones then take skin only.

"names": [...] (optional, one per bone) names the bones explicitly instead of <prefix>_NN: a one-bone LeftShoulder /
RightShoulder pair cut from a robed, armless body's shoulder caps gives the facing contract its lateralPair
(lane C 2026-10-12 h3_psychic_elemental / h3_magic_elemental: a spine-only rig with an upright Head was unmeasurable).

Bones are <prefix>_00 .. <prefix>_NN (or the given names), equal arc-length pieces of the centreline after `root`; <prefix>_00 is
parented to `parent`, each next one to the one before. Every vertex gets at most two neighbouring chain bones
(linear hat functions centred on the bone mid-points) plus its old influences scaled by (1 - fade); influences are
pruned to the 4 largest and renormalised.

Motion: after_pose makes the chain follow its parent rigidly in every frame, so the build output is unchanged until
something keys it; before_keys re-derives the chain from the final parent pose (after silhouetteRefine), moves the
weights, and registers the bones on the free-bone list (keyed rotation + location + scale). Clip motion (trunk lift,
reach, curl) comes from the GLB patch lane (keyRotations on <prefix>_* bones), so one rig build serves every clip.

Hooks: after_skin (bones + vertex groups + optional cut), after_pose (chain follows the parent), before_keys (weights + keying).
Lane C 2026-10-11 (h3_mammoth_upg_alt trunk; reused by lane B for hota_bulwark_mammoth / hota_bulwark_war_mammoth).
"""
import numpy as np
from mathutils import Vector
from stronghold_props import _region_test


def _specs(g):
    return g["cfg"].get("rigChains", [])


def _names(s):
    if s.get("names"):
        if len(s["names"]) != int(s["bones"]):
            raise SystemExit(f"rigChains {s['prefix']}: names must list exactly {s['bones']} bone names")
        return list(s["names"])
    return [f"{s['prefix']}_{k:02d}" for k in range(int(s["bones"]))]


def _poly(s):
    P = np.array(s["points"], float)
    L = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    return P, L


def _at(P, L, x):
    k = int(np.clip(np.searchsorted(L, x) - 1, 0, len(L) - 2))
    t = (x - L[k]) / max(L[k + 1] - L[k], 1e-12)
    return P[k] + t * (P[k + 1] - P[k])


def _cuts(s, L):
    return np.linspace(float(s.get("root", 0.04)), L[-1], int(s["bones"]) + 1)


def after_skin(g):
    specs = _specs(g)
    if not specs:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for s in specs:
        P, L = _poly(s); cuts = _cuts(s, L); names = _names(s)
        for k, nm in enumerate(names):
            b = eb.new(nm); b.head = Vector(_at(P, L, cuts[k])); b.tail = Vector(_at(P, L, cuts[k + 1])); b.roll = 0
            b.parent = eb[s["parent"]] if k == 0 else eb[names[k - 1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for s in specs:
        for nm in _names(s):
            if nm not in body.vertex_groups:
                body.vertex_groups.new(name=nm)
        print("RIGCHAIN", s["prefix"], "bones", s["bones"], "length", round(float(_poly(s)[1][-1]), 3))
        if s.get("cut"):
            _cut(g, s)


CUT_OUT = {}   # prefix -> vertex indices left on the web side of a cut (kept off the chain)


def _picker(g, s):
    """(co, weights {group: w}) -> arc length on the centreline, or None when the vertex is not a chain vertex."""
    P, L = _poly(s)
    root = float(s.get("root", 0.04)); minp = float(s.get("minParent", 0.5))
    rad = s.get("radius", 0.12)
    radf = (lambda x: float(rad)) if np.isscalar(rad) else (lambda x: float(np.interp(x, L, np.asarray(rad, float))))
    excl = [_region_test(g, r) for r in s.get("exclude", [])]
    par = g["body"].vertex_groups[s["parent"]].index
    A, B = P[:-1], P[1:]; AB = B - A; ab2 = np.maximum((AB * AB).sum(1), 1e-12)

    def pick(co, w):
        tot = sum(w.values())
        if tot <= 0 or w.get(par, 0.0) / tot < minp:
            return None
        p = np.array(co[:])
        t = np.clip(((p - A) * AB).sum(1) / ab2, 0, 1)
        d = np.linalg.norm(A + AB * t[:, None] - p, axis=1)
        k = int(np.argmin(d)); sv = L[k] + t[k] * (L[k + 1] - L[k])
        if d[k] > radf(sv) or sv <= root or any(e(co) for e in excl):
            return None
        return float(sv)
    return pick


def _cut(g, s):
    import bmesh
    body = g["body"]; zc = float(s["cut"]["belowZ"]); pick = _picker(g, s)
    bm = bmesh.new(); bm.from_mesh(body.data); dl = bm.verts.layers.deform.verify()
    ins = {v.index: pick(v.co, {k: x for k, x in v[dl].items() if x > 1e-6}) is not None for v in bm.verts}
    fin = {f.index: all(ins[v.index] for v in f.verts) for f in bm.faces}
    # BMFace objects survive split_edges; new vertex copies have no `ins` entry, so classify the faces now
    infaces = {f for f in bm.faces if fin[f.index]}
    mode = s["cut"].get("web", "parent")
    if mode == "parent":
        edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1
                 and max(v.co.z for v in e.verts) < zc]
        bmesh.ops.split_edges(bm, edges=edges)
    else:
        raise SystemExit(f"rigChains {s['prefix']}: cut.web must be parent (delete failed verify_glb: Death round trip), not {mode!r}")
    bm.verts.index_update(); bm.faces.ensure_lookup_table()
    # web-side copies: chain-picked by position but every face they keep is a web face (not all-chain); below the cut
    out = []
    for v in bm.verts:
        if v.co.z < zc and v.link_faces and not any(f in infaces for f in v.link_faces):
            if pick(v.co, {k: x for k, x in v[dl].items() if x > 1e-6}) is not None:
                out.append(v.index)
    bm.to_mesh(body.data); bm.free()
    CUT_OUT[s["prefix"]] = set(out)
    print("RIGCHAIN", s["prefix"], "cut below z", zc, mode, "split edges", len(edges), "web-side copies kept off", len(out))


def _smooth_arc(body, picked, iters):
    """Laplacian-smooth the chain coordinate (arc length) over the picked vertices' welded mesh neighbourhood: a wide
    limb's far side projects onto the centreline unevenly (neighbours land on different segments) and the hat weights
    then jump across one edge (h3_mammoth_upg_alt trunk sides: 0.5/0.5 next to 0.98/0.02). Coincident vertices (UV
    seams, cut copies) share one value; groups with no picked member are left out."""
    co = np.array([v.co[:] for v in body.data.vertices])
    _, wid = np.unique(np.round(co, 5), axis=0, return_inverse=True); wid = wid.ravel(); ng = int(wid.max()) + 1
    idx = np.fromiter(picked.keys(), int); val = np.fromiter(picked.values(), float)
    on = np.zeros(ng, bool); on[wid[idx]] = True
    sg = np.zeros(ng); cnt = np.zeros(ng); np.add.at(sg, wid[idx], val); np.add.at(cnt, wid[idx], 1); sg /= np.maximum(cnt, 1)
    E = np.array([e.vertices[:] for e in body.data.edges], int).reshape(-1, 2); E = wid[E]
    E = np.unique(np.sort(E[E[:, 0] != E[:, 1]], 1), axis=0); E = E[on[E[:, 0]] & on[E[:, 1]]]
    for _ in range(iters):
        acc = np.zeros(ng); n = np.zeros(ng)
        np.add.at(acc, E[:, 0], sg[E[:, 1]]); np.add.at(acc, E[:, 1], sg[E[:, 0]]); np.add.at(n, E[:, 0], 1); np.add.at(n, E[:, 1], 1)
        sg = np.where(n > 0, 0.5 * sg + 0.5 * acc / np.maximum(n, 1), sg)
    return {int(i): float(sg[wid[i]]) for i in idx}


def _weights(g, s):
    body = g["body"]
    P, L = _poly(s); cuts = _cuts(s, L); names = _names(s); n = len(names)
    root = float(s.get("root", 0.04)); rb = float(s.get("rootBlend", 0.12))
    pick = _picker(g, s); off = CUT_OUT.get(s["prefix"], set())
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    cid = [gi[nm] for nm in names]
    centres = (cuts[:-1] + cuts[1:]) / 2
    moved = 0
    picked = {}
    for v in body.data.vertices:
        w = {gg.group: gg.weight for gg in v.groups if gg.weight > 1e-6}
        sv = None if v.index in off else pick(v.co, w)
        if sv is not None:
            picked[v.index] = sv
    if s.get("smoothArc"):
        picked = _smooth_arc(body, picked, int(s["smoothArc"]))
    for v in body.data.vertices:
        if v.index not in picked:
            continue
        w = {gg.group: gg.weight for gg in v.groups if gg.weight > 1e-6}
        tot = sum(w.values())
        sv = picked[v.index]
        on = min(1.0, (sv - root) / rb) if rb > 0 else 1.0
        cw = np.zeros(n)
        if sv <= centres[0]:
            cw[0] = 1.0
        elif sv >= centres[-1]:
            cw[-1] = 1.0
        else:
            j = int(np.searchsorted(centres, sv) - 1)
            f = (sv - centres[j]) / (centres[j + 1] - centres[j])
            cw[j], cw[j + 1] = 1 - f, f
        new = {gid: (1.0 - on) * x / tot for gid, x in w.items()}
        for j in np.nonzero(cw > 1e-6)[0]:
            new[cid[j]] = new.get(cid[j], 0.0) + float(cw[j] * on)
        top = sorted(new.items(), key=lambda kv: -kv[1])[:4]
        st = sum(x for _, x in top)
        for gid in list(w):
            body.vertex_groups[gid].remove([v.index])
        for gid, x in top:
            if x > 1e-6:
                body.vertex_groups[gid].add([v.index], x / st, 'REPLACE')
        moved += 1
    print("RIGCHAIN", s["prefix"], "verts", moved)
    return moved


def after_pose(g):
    specs = _specs(g)
    if not specs:
        return
    rest = g["rest"]; parent_of = g["parent_of"]
    for s in specs:
        names = _names(s)
        for k, nm in enumerate(names):
            rest[nm] = g["rig"].data.bones[nm].matrix_local.copy()
            parent_of[nm] = s["parent"] if k == 0 else names[k - 1]
        for A in g["posed_world"]:
            for nm in names:
                p = parent_of[nm]
                A[nm] = A[p] @ rest[p].inverted() @ rest[nm]


def before_keys(g):
    specs = _specs(g)
    if not specs:
        return
    rest = g["rest"]; parent_of = g["parent_of"]
    for s in specs:
        for A in g["posed_world"]:
            for nm in _names(s):
                p = parent_of[nm]
                A[nm] = A[p] @ rest[p].inverted() @ rest[nm]
        if not _weights(g, s):
            raise SystemExit(f"rigChains {s['prefix']}: no vertex moved onto the chain (check points / radius / minParent)")
        g["RUBBLE_BONES"].extend(_names(s))   # keyed with rotation + location + scale (free-bone list)
        print("RIGCHAIN keyed", s["prefix"], len(_names(s)))
