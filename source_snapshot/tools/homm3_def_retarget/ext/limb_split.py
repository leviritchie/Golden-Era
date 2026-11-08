"""Cut a limb free of the body it is fused into (mesh surgery along the weight seam).

Some meshes model a hand (often with its prop) sunk into the robe or coat at the hip: the faces between
them are shared, so the limb's weight jumps from 1 to 0 across one ring of faces. Any raise of the limb
stretches that ring into a sheet (tear gate). `limbStrip` (bulwark_limbcut) only cleans weights; this hook
splits the mesh along the seam so limb and body separate cleanly:

  "limbSplit": [{"bones": ["LeftHand", "LeftForeArm", "LeftArm"],   # the limb's share = sum of these weights
                 "box": [[x0, y0, z0], [x1, y1, z1]],                # only seam edges whose midpoint is inside
                 "harden": true,       # optional: snap blended limb/body vertices in the box to one side first
                 "fallback": "Hips",   # body bone for a hardened vertex left with no body weight
                 "islandMax": 300,     # a loose piece of <= this many faces, wholly in the box, whose 8 nearest
                                       # outside vertices are mostly on the other side joins that side (nearest weights)
                 "reason": "..."}]

Each face goes to the limb when the mean limb share of its vertices is >= 0.5 (a face straddling a hard
1/0 seam goes with the majority of its corners). Edges inside the box whose two faces differ are split
(bmesh split_edges; new vertices are appended, existing indices keep their order). A vertex then used
only by limb faces but carrying body weight (or the reverse) takes the mean weights of its same-side
face neighbours, so every face moves wholly with one side and nothing is stretched across the cut.
Rest positions are unchanged (split copies coincide); the seam opens only when the limb moves.

List it after "bulwark_limbcut" in "extensions" so it sees the stripped weights. Pairs with any
setWeights table on the unit only after re-pinning its vertexCount (the split appends vertices).

Hook: after_skin.
"""
import bmesh
import mathutils.kdtree


def after_skin(g):
    specs = g["cfg"].get("limbSplit", [])
    if not specs:
        return
    body = g["body"]
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify()
    for s in specs:
        bones = {gidx[b] for b in s["bones"] if b in gidx}
        lo, hi = s["box"]

        def share(v):
            d = v[dl]; t = sum(d.values())
            return sum(w for k, w in d.items() if k in bones) / t if t > 0 else 0.0

        def inbox(p):
            return all(lo[i] <= p[i] <= hi[i] for i in range(3))

        if s.get("harden"):
            # blended limb/body vertices inside the box are snapped to one side first (share >= 0.5 keeps only the
            # limb bones, else only the body bones), so the whole fused zone becomes a hard seam the split can open
            fb = gidx[s.get("fallback", "Hips")]; nh = 0
            for v in bm.verts:
                if not inbox(v.co):
                    continue
                d = v[dl]; t = sum(d.values()); x = share(v)
                if t <= 0 or x in (0.0, 1.0):
                    continue
                keep = {k: w for k, w in d.items() if (k in bones) == (x >= 0.5) and w > 0}
                d.clear()
                if not keep:
                    keep = {fb: 1.0}
                tk = sum(keep.values())
                for k, w in keep.items():
                    d[k] = w / tk
                nh += 1
            print("LIMBSPLIT harden verts", nh)
        sh = {v: share(v) for v in bm.verts}
        side = {f: sum(sh[v] for v in f.verts) / len(f.verts) >= 0.5 for f in bm.faces}
        edges = [e for e in bm.edges if len(e.link_faces) >= 2 and len({side[f] for f in e.link_faces}) > 1
                 and inbox((e.verts[0].co + e.verts[1].co) / 2)]
        seamfaces = {f for e in edges for f in e.link_faces}
        bmesh.ops.split_edges(bm, edges=edges)
        side = {f: side[f] for f in bm.faces}   # faces survive split_edges (same BMFace objects)
        sh = {v: share(v) for v in bm.verts}   # after the split (copies carry their source weights)
        fixed = 0
        for v in bm.verts:
            if not v.link_faces or not inbox(v.co):
                continue
            sides = {side[f] for f in v.link_faces}
            if len(sides) != 1:
                continue
            limb = sides.pop()
            if (sh[v] >= 0.5) == limb:
                continue
            acc = {}; n = 0
            for f in v.link_faces:
                for u in f.verts:
                    if u is v or (sh[u] >= 0.5) != limb:
                        continue
                    for k, w in u[dl].items():
                        acc[k] = acc.get(k, 0.0) + w
                    n += 1
            if not n:
                continue
            d = v[dl]; d.clear()
            for k, w in sorted(acc.items(), key=lambda kv: -kv[1])[:4]:
                d[k] = w
            t4 = sum(d.values())
            for k in list(d.keys()):
                d[k] = d[k] / t4
            fixed += 1
        # islands: a small piece wholly inside the box (a gem set in a staff head, a cuff or trim modelled against the
        # limb) whose surroundings are on the other side would hang in the air when the limb moves: it joins the side
        # of its nearest outside vertices, copying the weights of that side's nearest vertex
        imax = int(s.get("islandMax", 300)); moved = 0
        sh = {v: share(v) for v in bm.verts}   # after the reweight above
        live = [v for v in bm.verts if v.link_faces]
        kd = mathutils.kdtree.KDTree(len(live))
        for i, v in enumerate(live):
            kd.insert(v.co, i)
        kd.balance()
        seen = set()
        for f0 in bm.faces:
            if f0 in seen:
                continue
            comp, stack = [], [f0]; seen.add(f0)
            while stack:
                f = stack.pop(); comp.append(f)
                for v in f.verts:          # vertex connectivity: a piece touching the rest at one corner is not loose
                    for f2 in v.link_faces:
                        if f2 not in seen:
                            seen.add(f2); stack.append(f2)
            if len(comp) > imax:
                continue
            vs = {v for f in comp for v in f.verts}
            if not all(inbox(v.co) for v in vs):
                continue
            near = {}
            for v in vs:
                for co, i, dist in kd.find_n(v.co, len(vs) + 16):
                    u = live[i]
                    if u not in vs and (u not in near or dist < near[u]):
                        near[u] = dist
            ring = sorted(near, key=near.get)[:8]
            if not ring:
                continue
            limb_now = sum(sh[v] for v in vs) / len(vs) >= 0.5
            if (sum(sh[u] >= 0.5 for u in ring) * 2 > len(ring)) == limb_now:
                continue          # its surroundings are on its own side
            others = [u for u in live if u not in vs and (sh[u] >= 0.5) != limb_now]
            for v in vs:
                _, i, _ = min((x for x in kd.find_n(v.co, 64) if live[x[1]] not in vs and (sh[live[x[1]]] >= 0.5) != limb_now),
                              key=lambda x: x[2], default=(None, None, None))
                u = live[i] if i is not None else min(others, key=lambda u: (u.co - v.co).length_squared)
                d = v[dl]; d.clear()
                for k, w in u[dl].items():
                    d[k] = w
            for v in vs:
                sh[v] = share(v)   # a moved piece is never picked as the other side of a later one
            moved += 1
            print("LIMBSPLIT island", len(comp), "faces ->", "body" if limb_now else "limb")
        print("LIMBSPLIT", s["bones"], "split edges", len(edges), "reweighted verts", fixed, "islands moved", moved,
              "verts now", len(bm.verts))
    bm.to_mesh(body.data); bm.free()
