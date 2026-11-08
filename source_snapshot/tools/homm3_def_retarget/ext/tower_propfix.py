"""Tower: finish cutting a thin held prop that Meshy fused to the robe (h3_mage staff).

The build binds a prop rigidly only where a face lies wholly inside the prop's radius. A staff
whose low-poly shaft shares long triangles with the robe behind it keeps those triangles (and
the shaft vertices on them) on the body, so a sliver of staff stands in the robe when the hand
lifts the staff away. after_skin, config "propFix": [{"bone": "LeftHand", "segments": [[a, b], ...],
"radius": r, "minCorners": 2}]:
  * every face with at least one non-rigid corner and at least minCorners corners within
    `radius` of the segments joins the prop;
  * edges between those faces and the rest are split;
  * a vertex now used only by prop faces is bound 100% to `bone`.
"""
import bmesh
import numpy as np


def _segdist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def after_skin(g):
    body, cfg = g["body"], g["cfg"]
    specs = cfg.get("propFix", [])
    if not specs:
        return
    me = body.data
    vg = body.vertex_groups
    for sp in specs:
        bi = vg[sp["bone"]].index
        bm = bmesh.new(); bm.from_mesh(me)
        dl = bm.verts.layers.deform.verify()
        bm.verts.ensure_lookup_table()
        P = np.array([v.co[:] for v in bm.verts])
        d = np.min(np.stack([_segdist(P, np.array(a), np.array(b)) for a, b in sp["segments"]], 1), 1)
        near = d < sp["radius"]
        rig = np.array([bool(v[dl]) and max(v[dl].values()) >= 0.999 and v[dl].get(bi, 0) >= 0.999 for v in bm.verts])
        k = sp.get("minCorners", 2)
        prop = {f.index for f in bm.faces
                if not all(rig[v.index] for v in f.verts) and sum(near[v.index] for v in f.verts) >= k}
        cut = [e for e in bm.edges if len({f.index in prop for f in e.link_faces}) > 1]
        bmesh.ops.split_edges(bm, edges=cut)
        n = 0
        for v in bm.verts:
            if v.link_faces and all(f.index in prop for f in v.link_faces):
                dv = v[dl]; dv.clear(); dv[bi] = 1.0; n += 1
        bm.to_mesh(me); bm.free()
        print("HOOK tower propfix", sp["bone"], "faces", len(prop), "split edges", len(cut), "verts bound", n)
