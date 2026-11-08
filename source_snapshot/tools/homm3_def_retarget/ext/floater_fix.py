"""Floaters: a small piece bound to a different bone than the surface it sits on (see floaters.py).

A rigid region (wing, prop) is cut free by a volume test, so stray body faces inside that volume
become small islands bound 100% to the wing, and fly off with it (dragon/gargoyle wing slivers at
the feet); a limbLeash handSplit can leave a few hand faces bound to the thigh; a Meshy shard can be
weighted on its own and drift off the surface it rests on. floaters.py finds these in the exported
GLB and prints each one's `fixPoint`.

after_skin (list it LAST in "extensions", after every hook that cuts or reweights): pieces are
connected faces plus coincident vertices (1e-5) whose weights also match, so a UV seam joins but a
cut boundary does not (castle_loosebits welds by position only, which would merge a cut sliver back
into the body it was cut from). For each listed point, the piece holding the vertex at that point
takes, on all its vertices, the mean weights of the `k` nearest vertices of other pieces (the
surface it sat on at rest), limited to 4 bones and normalised; or 100% `bone` when given.

Fail-closed: a point with no vertex within 1e-3, or whose piece has more than `maxVerts` vertices
(the point hit the body, not a sliver), raises.

Config: "floaterFix": {"k": 8, "maxVerts": 400,
                       "pieces": [{"point": [x, y, z], "note": "wing sliver at left foot"},
                                  {"point": [x, y, z], "bone": "Hips"},
                                  {"point": [x, y, z], "delete": true, "note": "broken-off whip segment"}]}
Points are Blender coordinates (Z up), as floaters.py writes them.

"from": "<bone>" picks, among the vertices at the point, the one whose dominant weight is that bone (a cut
sliver shares every position with the surface it was cut from, so the point alone is ambiguous).

"delete": true removes the piece (floaters.py `fix: deleteIsland`: a rest island that is debris, not a part
of the unit, e.g. a Meshy segment broken off a whip). Deletions run after every reweight, in one bmesh pass,
so the other points still resolve against the unchanged mesh; same fail-closed point / maxVerts checks.

"stage": "before_keys" (opt-in, per piece or for the whole floaterFix; default "after_skin") resolves that piece in the
before_keys hook instead, i.e. after every other extension's weights are final. List floater_fix LAST in "extensions" so its
before_keys runs after theirs. Needed where the owner of the sliver, or the surface it sits on, is assigned after
after_skin: inferno_whipchain moves the tail/whip onto its chain only in before_keys (at after_skin a tail-root seam
sliver still shares Hips with the whole 600-vert tail, h3_gore_demon), and a sliver of back faces that a wing region
cut onto a wing_chain bone sits on a body whose seam copies only separate once the chain owns the wing (h3_vermin).
"delete" is refused at this stage (deletions belong to the source mesh, before the motion is built).

"weights": "vertex" (per piece, opt-in; default "mean"): each vertex of the piece copies the skin weights of its
nearest host vertex instead of the piece taking one k-nearest mean. Hosts are the vertices outside the piece whose
dominant bone is none of the piece's own dominant bones (so a wing sliver never copies the wing membrane beside it,
and a Hips seam sliver on the tail copies the tail, not the Hips body). A seam sliver's vertices are coincident with
the surface's copies, so each copies its own twin and the seam is welded in every pose (a mean over a blended chain,
e.g. Tail_00 0.55 / Tail_01 0.45 at one copy and 0.61 / 0.39 at the next, would leave the sliver rigid against it).
Fail-closed: a vertex with no host within `maxHostDist` (default 0.03) raises.

Status 2026-09-26: exercised in a build (generated artifact only) on hota_cove_nix_warrior, whose
regenerated mesh has three unweighted head islands (crest 232, fins 90/77 verts). Each printed
"REGION floater_fix piece ... -> Head 1.00", verify_glb stays ~1e-6, and floaters.py on the rebuilt
GLB reports unweighted 0, rest floaters 0, motion 0 high / 1 medium / 2 low (the medium is a
13-vert shield-rim cut region in Death, not one of the fixed pieces).
"""
import numpy as np
from castle_loosebits import _components


def _stage(cfg, e):
    return e.get("stage", cfg.get("stage", "after_skin"))


def resolve(cfg, co, W, edges, names, stage="after_skin"):
    """Pure numpy core (also used offline by the dry check): the pieces of `stage`; returns
    ([(idx, w2 or None, piece, label)], drop).
    co (n,3) Blender coordinates, W (n, nb) weights, edges (m,2) vertex pairs, names: bone of each W column."""
    n, nb = W.shape
    gid = {nm: i for i, nm in enumerate(names)}
    key = np.c_[np.round(co / 1e-5).astype(np.int64), np.round(W * 50).astype(np.int64)]
    _, weld = np.unique(key, axis=0, return_inverse=True); weld = weld.ravel()
    E = np.asarray(edges)
    vlab = _components(weld.max() + 1, weld[E[:, 0]], weld[E[:, 1]])[weld]
    k, maxv = cfg.get("k", 8), cfg.get("maxVerts", 400)
    dom = W.argmax(1)
    out, drop = [], []
    for e in [x for x in cfg["pieces"] if _stage(cfg, x) == stage]:
        late = stage == "before_keys"
        d0 = np.linalg.norm(co - np.array(e["point"]), axis=1); i0 = int(np.argmin(d0))
        if d0[i0] > 1e-3:
            raise RuntimeError(f"floaterFix: no vertex at {e['point']} (nearest {d0[i0]:.4f})")
        if "from" in e:                      # a cut sliver shares its positions with the body: pick the copy on that bone
            at = np.nonzero(d0 <= d0[i0] + 1e-5)[0]
            on = [i for i in at.tolist() if dom[i] == gid[e["from"]]]
            if not on:
                raise RuntimeError(f"floaterFix: no vertex at {e['point']} is dominated by {e['from']}")
            i0 = on[0]
        idx = np.nonzero(vlab == vlab[i0])[0]
        if len(idx) > maxv:
            raise RuntimeError(f"floaterFix: piece at {e['point']} has {len(idx)} verts > maxVerts {maxv}")
        if e.get("delete"):
            if late:
                raise RuntimeError("floaterFix: delete is an after_skin (source mesh) fix, not allowed at stage before_keys")
            drop.extend(idx.tolist()); out.append((idx, None, e, "delete")); continue
        if "bone" in e:
            w2 = np.zeros(nb); w2[gid[e["bone"]]] = 1.0
        elif e.get("weights", "mean") == "vertex":
            own = set(dom[idx].tolist())
            host = np.nonzero((vlab != vlab[i0]) & ~np.isin(dom, list(own)))[0]
            dd = np.linalg.norm(co[host][None, :, :] - co[idx][:, None, :], axis=2)
            j = dd.argmin(1); far = dd[np.arange(len(idx)), j]
            lim = float(e.get("maxHostDist", 0.03))
            if far.max() > lim:
                raise RuntimeError(f"floaterFix: piece at {e['point']}: a vertex is {far.max():.4f} from any host > maxHostDist {lim}")
            w2 = W[host[j]].copy()
            out.append((idx, w2, e, f"per-vertex hosts (max dist {far.max():.4f})"))
            W[idx] = w2
            continue
        else:
            host = np.nonzero(vlab != vlab[i0])[0]
            dd = np.linalg.norm(co[host][None, :, :] - co[idx][:, None, :], axis=2).min(0)
            near = host[np.argsort(dd)[:k]]
            w = W[near].mean(0)
            top = np.argsort(-w)[:4]; w2 = np.zeros(nb); w2[top] = w[top]
            w2 /= max(w2.sum(), 1e-12)
        out.append((idx, np.broadcast_to(w2, (len(idx), nb)).copy(), e, "mean"))
        W[idx] = w2
    return out, drop


def _run(g, stage):
    cfg = g["cfg"].get("floaterFix")
    if not cfg or not any(_stage(cfg, e) == stage for e in cfg["pieces"]):
        return
    body = g["body"]; me = body.data; vg = body.vertex_groups
    n = len(me.vertices); nb = len(vg)
    co = np.array([v.co[:] for v in me.vertices])
    W = np.zeros((n, nb))
    for v in me.vertices:
        for gr in v.groups:
            W[v.index, gr.group] = gr.weight
    E = np.array([e.vertices[:] for e in me.edges])
    out, drop = resolve(cfg, co, W, E, [x.name for x in vg], stage)
    for idx, w2, e, how in out:
        if w2 is None:
            print("REGION floater_fix delete piece", len(idx), "verts", e.get("note", ""))
            continue
        for r, i in enumerate(idx.tolist()):
            for gr in list(me.vertices[i].groups):
                vg[gr.group].remove([i])
            for b in np.nonzero(w2[r] > 0)[0]:
                vg[int(b)].add([i], float(w2[r][b]), 'REPLACE')
        m = w2.mean(0)
        top = sorted(((float(m[b]), vg[int(b)].name) for b in np.nonzero(m > 0)[0]), reverse=True)[:4]
        print("REGION floater_fix piece", len(idx), "verts ->", ", ".join(f"{nm} {w:.2f}" for w, nm in top), how, e.get("note", ""))
    if drop:
        import bmesh
        bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.verts[i] for i in sorted(set(drop))], context='VERTS')
        bm.to_mesh(me); bm.free(); me.update()


def after_skin(g):
    _run(g, "after_skin")


def before_keys(g):
    _run(g, "before_keys")
