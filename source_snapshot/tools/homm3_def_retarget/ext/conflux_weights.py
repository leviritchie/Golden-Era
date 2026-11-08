"""Conflux weight fixes (hook module for build_unit.py; list it in a unit's "extensions").

Config keys, all under the unit's "conflux" object:
  legTop: [z0, z1]      heat spreads the thigh bones far up a short, heavy torso (earth/magma
                        elementals), so the belly stays with the legs when the torso bends. Leg
                        weight is kept in full below z0 and faded out to nothing at z1; the share
                        removed goes to Hips.
  armFalloff: {"width": w, "bias": b, "chain": [...], "torso": [...]}
                        arm-chain weight fades out smoothly where a vertex is nearer the torso
                        chain than the arm chain (see after_skin); optional "maxDist": [r0, r1]
                        also fades it out between r0 and r1 from the arm bones.
  handStrip: {"parts": [...]}
                        with armCut: forearm/hand weight is removed from every vertex that is not
                        owned by the arm chain alone (belly under a resting fist).
  fillUnweighted: true  vertices with no bone weight copy the nearest weighted vertex's weights.
  deleteRegions: [box]  Meshy geometry that is not part of the creature (a display plinth under a
                        robe) is removed: every vertex inside any box [[x0,y0,z0],[x1,y1,z1]].
                        Vertices left with no face are removed too (glTF drops them, so they would
                        make the GLB differ from the .blend: psychic MESHERR 0.057).
  deleteLoose: true     remove face-less vertices without deleting any region.
  uniformIslands: {"maxVerts": n}
                        every surface piece (connected by edges after welding coincident
                        vertices) other than the largest, with at most n vertices, gets one weight
                        set for all its vertices (the piece's mean, top 4) so it moves as one
                        piece: thin lightning strands running from wrist to hip otherwise stretch
                        into long bands when the arms lift (energy/plasma elementals).
"""
import bmesh

LEGS = ("LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg")


def after_skin(g):
    cfg = g["cfg"].get("conflux", {})
    body = g["body"]
    if "legTop" in cfg:
        z0, z1 = cfg["legTop"]
        gi = {vg.name: vg.index for vg in body.vertex_groups}
        legs = {gi[n] for n in LEGS if n in gi}
        hips = body.vertex_groups["Hips"]
        moved = 0
        for v in body.data.vertices:
            a = min(1.0, max(0.0, (v.co.z - z0) / max(z1 - z0, 1e-6)))
            if a <= 0:
                continue
            take = 0.0
            for e in v.groups:
                if e.group in legs and e.weight > 0:
                    take += e.weight * a
                    e.weight *= (1 - a)
            if take > 1e-4:
                old = next((e.weight for e in v.groups if e.group == hips.index), 0.0)
                hips.add([v.index], old + take, 'REPLACE')
                moved += 1
        print("CONFLUX legTop", z0, z1, "vertices moved", moved)
    if "armFalloff" in cfg:
        # arms hanging against a heavy torso: heat gives the flank and belly to the upper arm and
        # forearm, and a raised arm then lifts a sheet of torso with it. Arm-chain weight is scaled
        # by a smooth function of (distance to the torso chain - distance to the arm chain), so it is
        # continuous over the surface (no tear at a cut) and the removed share goes to the nearest
        # torso bone.
        import numpy as np
        st = cfg["armFalloff"]; J = g["J"]; width = st.get("width", 0.06); bias = st.get("bias", 0.0)
        seg = {b[0]: (np.array(J[b[1]]), np.array(J[b[2]])) for b in g["BONES"]}
        def dist(P, n):
            a_, b_ = seg[n]; ab = b_ - a_
            t = np.clip(((P - a_) @ ab) / max(ab @ ab, 1e-12), 0, 1)
            return np.linalg.norm(P - (a_ + t[:, None] * ab), axis=1)
        P = np.array([v.co[:] for v in body.data.vertices])
        torso = [n for n in st.get("torso", ["Hips", "Spine", "Spine1", "Spine2"]) if n in seg]
        Dt = np.stack([dist(P, n) for n in torso], 1); dt = Dt.min(1); nt = Dt.argmin(1)
        gi = {vg.name: vg.index for vg in body.vertex_groups}
        moved = 0
        for side in ("Left", "Right"):
            chain = [side + k for k in st.get("chain", ["Arm", "ForeArm", "Hand"]) if side + k in seg]
            if not chain:
                continue
            da = np.stack([dist(P, n) for n in chain], 1).min(1)
            f = np.clip(0.5 + (dt - da - bias) / width, 0, 1)
            if "maxDist" in st:
                # flame/cloak mantles fused behind the arms: also fade arm weight out with the
                # distance from the arm bones themselves (full at r0, none at r1)
                r0, r1 = st["maxDist"]
                f = f * np.clip((r1 - da) / max(r1 - r0, 1e-6), 0, 1)
            ids = {gi[n] for n in chain}
            for v in body.data.vertices:
                if f[v.index] >= 1:
                    continue
                take = 0.0
                for e in v.groups:
                    if e.group in ids and e.weight > 0:
                        take += e.weight * (1 - f[v.index]); e.weight *= f[v.index]
                if take > 1e-5:
                    tg = body.vertex_groups[torso[nt[v.index]]]
                    old = next((e.weight for e in v.groups if e.group == tg.index), 0.0)
                    tg.add([v.index], old + take, 'REPLACE'); moved += 1
        print("CONFLUX armFalloff vertices", moved)
    if "handStrip" in cfg:
        # fists resting on the belly: armCut frees the forearm and fist (their vertices end up
        # owned by the arm chain alone, cut along their border), but the belly around them still
        # carries forearm/hand heat and stretches into a sheet when the fist lifts. Every vertex
        # that also has non-arm weight loses its forearm/hand share (renormalised); vertices owned
        # by the arm chain alone are untouched.
        parts = tuple(cfg["handStrip"].get("parts", ["ForeArm", "Hand"]))
        gname = {vg.index: vg.name for vg in body.vertex_groups}
        chain = lambda n: n.startswith(("Left", "Right")) and n.endswith(("Arm", "ForeArm", "Hand", "Shoulder"))
        strip = lambda n: n.startswith(("Left", "Right")) and n.endswith(parts)
        n_ = 0
        for v in body.data.vertices:
            ws = [(e.group, e.weight) for e in v.groups if e.weight > 1e-5]
            if not ws or all(chain(gname[gi_]) for gi_, _ in ws) or not any(strip(gname[gi_]) for gi_, _ in ws):
                continue
            keep = [(gi_, w) for gi_, w in ws if not strip(gname[gi_])]
            tot = sum(w for _, w in keep)
            if tot < 1e-4:
                continue
            for gi_, _ in ws:
                body.vertex_groups[gi_].remove([v.index])
            for gi_, w in keep:
                body.vertex_groups[gi_].add([v.index], w / tot, 'REPLACE')
            n_ += 1
        print("CONFLUX handStrip vertices", n_)
    if cfg.get("fillUnweighted"):
        # loose Meshy shards (wisps floating off a whirlwind) get no bone heat at all and would
        # stay at their rest position forever: copy the weights of the nearest weighted vertex
        from mathutils import kdtree
        vs = body.data.vertices
        wt = [v.index for v in vs if any(e.weight > 1e-4 for e in v.groups)]
        kd = kdtree.KDTree(len(wt))
        for i in wt:
            kd.insert(vs[i].co, i)
        kd.balance()
        miss = [v.index for v in vs if not any(e.weight > 1e-4 for e in v.groups)]
        for i in miss:
            src = vs[kd.find(vs[i].co)[1]]
            for e in list(vs[i].groups):
                body.vertex_groups[e.group].remove([i])
            for e in src.groups:
                body.vertex_groups[e.group].add([i], e.weight, 'REPLACE')
        print("CONFLUX fillUnweighted vertices", len(miss))
    if cfg.get("uniformIslands"):
        import numpy as np
        vs = body.data.vertices; n = len(vs)
        par = list(range(n))
        def find(a):
            while par[a] != a:
                par[a] = par[par[a]]; a = par[a]
            return a
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                par[ra] = rb
        key = {}
        for v in vs:
            k = tuple(round(c, 5) for c in v.co)
            if k in key:
                union(v.index, key[k])
            else:
                key[k] = v.index
        for e in body.data.edges:
            union(e.vertices[0], e.vertices[1])
        comp = {}
        for i in range(n):
            comp.setdefault(find(i), []).append(i)
        big = max(comp.values(), key=len)
        lim = cfg["uniformIslands"].get("maxVerts", 2000)
        nis = nv = 0
        for c in comp.values():
            if c is big or len(c) > lim:
                continue
            acc = {}
            for i in c:
                for e in vs[i].groups:
                    acc[e.group] = acc.get(e.group, 0.0) + e.weight
            keep = sorted(acc.items(), key=lambda x: -x[1])[:4]
            tot = sum(w for _, w in keep)
            if tot <= 0:
                continue
            for i in c:
                for e in list(vs[i].groups):
                    body.vertex_groups[e.group].remove([i])
                for gi_, w in keep:
                    body.vertex_groups[gi_].add([i], w / tot, 'REPLACE')
            nis += 1; nv += len(c)
        print("CONFLUX uniformIslands pieces", nis, "vertices", nv, "of", n, "pieces total", len(comp))
    if "legTop" in cfg or "armFalloff" in cfg or "handStrip" in cfg or cfg.get("fillUnweighted") or cfg.get("uniformIslands"):
        # glTF carries 4 influences per vertex: keep the 4 largest and renormalise, so the exported
        # skin (and the corrective-smooth morphs baked against it) match Blender exactly
        n4 = 0
        for v in body.data.vertices:
            ws = sorted(((e.group, e.weight) for e in v.groups), key=lambda x: -x[1])
            keep = [x for x in ws[:4] if x[1] > 1e-4]; tot = sum(w for _, w in keep)
            if len(ws) > len(keep) or abs(tot - 1) > 1e-4:
                for gi_, _ in ws:
                    body.vertex_groups[gi_].remove([v.index])
                for gi_, w in keep:
                    body.vertex_groups[gi_].add([v.index], w / tot, 'REPLACE')
                n4 += 1
        print("CONFLUX limit4 vertices", n4)
    if cfg.get("deleteRegions"):
        bm = bmesh.new(); bm.from_mesh(body.data)
        boxes = cfg["deleteRegions"]
        dead = [v for v in bm.verts if any(all(b[0][i] <= v.co[i] <= b[1][i] for i in range(3)) for b in boxes)]
        bmesh.ops.delete(bm, geom=dead, context='VERTS')
        bm.to_mesh(body.data); bm.free()
        print("CONFLUX deleted vertices", len(dead))
    if cfg.get("deleteRegions") or cfg.get("deleteLoose"):
        bm = bmesh.new(); bm.from_mesh(body.data)
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.to_mesh(body.data); bm.free()
        print("CONFLUX deleted loose vertices", len(loose))
