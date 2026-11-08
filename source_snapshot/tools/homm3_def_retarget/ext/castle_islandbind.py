"""Castle: bind whole Meshy index-islands, fused by position to the wrong body part, rigidly to one bone.

Meshy welds a prop piece to the skin it rests on (h3_marksman: crossbow stock and back limb on the left thigh;
h3_halberdier: the left fist's fingers wrapped round the shaft). Bone heat then weights the piece like the skin
under it, so the piece stays on the thigh (or the halberd) when the hand moves. The pieces are separate index-islands
in the mesh, only position-coincident with the skin, so no cut is needed: binding the islands 100% to the right bone
makes their weights differ from the coincident skin copies, and bake_cs (which welds by rest position AND weights)
then treats them as their own surface -- the rip happens at the existing island boundary.

Config: "islandBinds": [{"table": "tools/homm3_def_retarget/island_binds/<unit>_<part>.json",
                         "bone": "LeftHand" (default: the table's bone), "minMatch": 0.95,
                         "adoptFrom": ["LeftHand", "LeftForeArm"] (optional)}]
Table (written from the patch base GLB): {"bone", "positions": [[x, y, z] Blender build space], ...}.
A mesh island (edge-connected vertices) is bound when at least minMatch of its vertices sit on table positions.
Bound islands go 100% to `bone`, or with adoptFrom each bound vertex copies the weights of the nearest vertex (its
weld-coincident copy, when there is one) whose dominant bone is in adoptFrom: the piece then skins exactly like the
hand surface it sits on, so it stays welded there and parts from the thigh/belt/shaft copies. Every table position must be matched by a bound vertex, or the build stops (the source mesh changed). Hook: after_skin;
list it after the unit's other weight extensions. A bind with "stage": "before_keys" is applied in before_keys instead,
after castle_refine's silhouette/propAim fit (adopting chips onto a prop hand at after_skin moved the swordsman's
AttackFront windup aim); nothing between the fit and the export reads the weights except silhouetteRefine and shatter,
so do not use it on units that have those.
"""
import json
import os

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _components(n, E):
    par = np.arange(n)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a, b in E.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb
    return np.array([find(i) for i in range(n)])


def after_skin(g):
    _apply(g, [b for b in g["cfg"].get("islandBinds", []) if b.get("stage", "after_skin") == "after_skin"])


def before_keys(g):
    # "stage": "before_keys" binds land after castle_refine's fit (list castle_islandbind after castle_refine), so a
    # few chips re-bound at a held prop's hand cannot move the prop's aim; the exported skin still gets them
    _apply(g, [b for b in g["cfg"].get("islandBinds", []) if b.get("stage") == "before_keys"])


def _apply(g, binds):
    if not binds:
        return
    body = g["body"]; me = body.data; vg = body.vertex_groups
    n = len(me.vertices)
    co = np.array([v.co[:] for v in me.vertices])
    E = np.array([e.vertices[:] for e in me.edges]).reshape(-1, 2)
    lab = _components(n, E)
    q = 1e-5
    vkey = {}
    for i, k in enumerate(map(tuple, np.round(co / q).astype(np.int64))):
        vkey.setdefault(k, []).append(i)
    offs = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    for bd in binds:
        tab = json.load(open(os.path.join(ROOT, bd["table"])))
        bone = bd.get("bone", tab["bone"]); mm = bd.get("minMatch", 0.95)
        if bone not in vg:
            raise SystemExit(f"castle_islandbind: bone {bone} has no vertex group")
        P = np.array(tab["positions"], float)
        hit = np.zeros(n, bool); unmatched = 0
        for k in map(tuple, np.round(P / q).astype(np.int64)):
            idx = [i for o in offs for i in vkey.get((k[0] + o[0], k[1] + o[1], k[2] + o[2]), [])]
            if not idx:
                unmatched += 1
            hit[idx] = True
        bound = []
        for c in np.unique(lab[hit]):
            m = lab == c
            if hit[m].mean() >= mm:
                bound.append(np.nonzero(m)[0])
        bound = np.concatenate(bound) if bound else np.zeros(0, np.int64)
        # every table position must land on a bound vertex
        bset = set(map(tuple, np.round(co[bound] / q).astype(np.int64)))
        miss = sum(1 for k in map(tuple, np.round(P / q).astype(np.int64))
                   if not any((k[0] + o[0], k[1] + o[1], k[2] + o[2]) in bset for o in offs))
        if unmatched or miss:
            raise SystemExit(f"castle_islandbind {bd['table']}: {unmatched} table positions match no vertex, "
                             f"{miss} not on a bound island (source mesh or build changed; regenerate the table)")
        b = vg[bone].index
        hosts = bd.get("adoptFrom")
        if hosts:
            # each bound vertex takes the weights of the nearest vertex (a weld-coincident copy when there is one) on
            # the surface it sits on: unbound vertices whose dominant bone is one of adoptFrom
            hb = {vg[h].index for h in hosts if h in vg}
            dom = np.full(n, -1)
            for v in me.vertices:
                if v.groups:
                    dom[v.index] = max(v.groups, key=lambda gr: gr.weight).group
            host = np.nonzero(np.isin(dom, list(hb)) & ~np.isin(np.arange(n), bound))[0]
            if not len(host):
                raise SystemExit(f"castle_islandbind {bd['table']}: no host vertices on {hosts}")
            src = [int(host[np.argmin(np.linalg.norm(co[host] - co[i], axis=1))]) for i in bound.tolist()]
            copy = {i: [(gr.group, gr.weight) for gr in me.vertices[j].groups] for i, j in zip(bound.tolist(), src)}
            far = max(float(np.linalg.norm(co[i] - co[j])) for i, j in zip(bound.tolist(), src))
        for i in bound.tolist():
            for gr in list(me.vertices[i].groups):
                vg[gr.group].remove([i])
            if hosts:
                for k, w in copy[i]:
                    vg[k].add([i], w, 'REPLACE')
            else:
                vg[b].add([i], 1.0, 'REPLACE')
        print("REGION castle_islandbind", os.path.basename(bd["table"]), "adopt " + "/".join(hosts) + f" (max host distance {far:.4f})"
              if hosts else bone + " rigid", "islands", len(np.unique(lab[bound])), "vertices", len(bound), "table", len(P))
