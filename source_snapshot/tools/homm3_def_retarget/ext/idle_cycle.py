"""Authored idle breathing cycle on the Unit_Idle loop (shared extension, any faction).

Why: for bodies the human capture cannot drive (hydra necks, tails, quadruped heads, wings) the
per-frame silhouette fits turn the DEF's small idle motion into whole-body screen jitter
(dx / dy / roll of the rigid body), while the articulated parts that carry the DEF's motion swing
only 1-3 deg. The idle then reads frozen once the cadence retime slows it (docs/homm3_idle_cadence.md,
nearStatic). This hook replaces the idle loop with ONE held pose plus a periodic articulated cycle.

What it touches: only the frames of the longest segment whose contract suffix is `clip` (the
Unit_Idle loop build_unit keys). Every other clip, and the single-frame idle segments between
actions, keep their fitted poses; the fits still run over them, so the fit's frame-to-frame state
(and with it every other clip's IoU) is unchanged.

Per idle frame i of n:
  1. base pose = the segment's first frame (the fitted pose closest to DEF idle frame 0): every
     bone's parent-relative transform is copied from it, so the rigid fit jitter is gone;
  2. on top, per bone, a rotation about a world rest axis (converted into the bone's rest frame,
     like fortress_rig's rot params), summed from the specs below; bones are re-chained root-first,
     so a child follows its parent;
  3. optional whole-body lift (world vector x shape).
Shapes are periodic in i/n with integer `cycles`, so the loop closes on build_unit's closing key.

Config (unit JSON, list "idle_cycle" LAST in "extensions" so it sees the final poses):
  "idleCycle": {
    "clip": "Idle", "cycles": 1,
    "rot":  [{"bones": [["Neck", 0.6], ["Head", 0.4]], "axis": [1, 0, 0], "peak": -6,
              "shape": "breath"|"sin", "phase": 0}],
    "wave": [{"bones": ["Tail_00", "Tail_01", ...] | "prefix": "Tail_", "axis": [0, 0, 1],
              "amp": 5, "wavelength": 6, "phase": 0, "grow": 1}],
    "lift": {"vec": [0, 0, 0.01], "shape": "breath", "phase": 0},
    "rigidParts": [{"name": "Rotor", "center": [x, y, z], "axis": [x, y, z], "radius": 0.21,
                    "hMin": -0.05, "hMax": 0.12, "parent": optional}],
    "spin": [{"bone": "Rotor", "turns": 1}]
  }
  breath: peak * (1 - cos(2 pi cycles i/n + phase)) / 2   (0 at frame 0, peak mid-loop)
  sin:    peak * (sin(2 pi cycles i/n + phase) - sin(phase))
  ramp:   peak * cycles i/n
  wave:   bone k of the chain turns amp * min(1, (k+1)/grow) * (sin(2 pi cycles i/n + p_k) - sin(p_k)),
          p_k = phase - 2 pi k/wavelength
  Every shape is 0 at frame 0, so the loop starts on the fitted DEF frame 0 pose that the
  other clips blend from. spin turns a bone about its own rest axis by 360 * turns * i/n
  (integer turns, or the closing key snaps back).
  rigidParts (after_skin): a part the rig has no bone for (an automaton's rotor) gets one; the
  disk region is cut from the skin and bound 100% to it (world coordinates after the other
  extensions' after_skin, e.g. rampart_quadruped's rest yaw); parent defaults to the bone that
  held most of the region's weight.
  Degrees; axes are world rest axes (the unit faces -Y, +Z up; +X about a -Y-facing body pitches the
  front down).
Prints "HOOK IDLECYCLE ...".
"""
import json
import math


def _shape(kind, peak, u, phase):
    a = 2 * math.pi * u + math.radians(phase)
    if kind == "sin":
        return peak * (math.sin(a) - math.sin(math.radians(phase)))
    if kind == "ramp":
        return peak * u
    return peak * (1 - math.cos(a)) / 2



def after_skin(g):
    """rigidParts: a part the rig has no bone for (an automaton's rotor) gets its own bone. Its
    region (a disk about `center` along `axis`: lateral distance < radius, axial offset in
    [hMin, hMax]) is cut from the surrounding skin (edges split, like build_unit's prop regions)
    and bound 100% to the new bone, parented to the bone that owned most of the region's weight
    (or `parent`, required when the region is unskinned: loose parts the heat weights miss).
    The bone runs along `axis`, so a "spin" entry turns the part about its own axis."""
    parts = (g["cfg"].get("idleCycle") or {}).get("rigidParts", [])
    if not parts:
        return
    import bpy
    import bmesh
    Vector = g["Vector"]
    body, rig = g["body"], g["rig"]
    created = []
    for rp in parts:
        c, ax = Vector(rp["center"]), Vector(rp["axis"]).normalized()
        r, h0, h1 = rp["radius"], rp.get("hMin", -0.05), rp.get("hMax", 0.12)

        def inside(co, c=c, ax=ax, r=r, h0=h0, h1=h1):
            d = co - c; h = d.dot(ax)
            return h0 <= h <= h1 and (d - ax * h).length < r
        if rp.get("wholeIslands"):
            # opt-in (automaton telescoping arm, 2026-10-11): only whole mesh islands (edges + UV-seam copies welded
            # by position) lying at least this fraction inside the disk, i.e. parts mesh surgery cut free or added;
            # nested sleeves share one axis, so a plain disk would also take the inner tubes and the drum plate
            frac = float(rp["wholeIslands"]); me = body.data; par_ = list(range(len(me.vertices)))

            def fnd(x):
                while par_[x] != x:
                    par_[x] = par_[par_[x]]; x = par_[x]
                return x
            for e in me.edges:
                par_[fnd(e.vertices[0])] = fnd(e.vertices[1])
            first = {}
            for v in me.vertices:
                k_ = tuple(round(q, 5) for q in v.co)
                if k_ in first:
                    par_[fnd(v.index)] = fnd(first[k_])
                else:
                    first[k_] = v.index
            tot_, in_ = {}, {}
            for v in me.vertices:
                r_ = fnd(v.index); tot_[r_] = tot_.get(r_, 0) + 1; in_[r_] = in_.get(r_, 0) + bool(inside(v.co))
            keep = {tuple(round(q, 5) for q in v.co) for v in me.vertices
                    if in_[fnd(v.index)] >= frac * tot_[fnd(v.index)]}

            def inside(co, keep=keep):
                return tuple(round(q, 5) for q in co) in keep
        names = [vg.name for vg in body.vertex_groups]
        tot = {}
        for v in body.data.vertices:
            if inside(v.co):
                for x in v.groups:
                    tot[names[x.group]] = tot.get(names[x.group], 0.0) + x.weight
        if not tot and not rp.get("parent"):
            nin = sum(1 for v in body.data.vertices if inside(v.co))
            lo = [min(v.co[i] for v in body.data.vertices) for i in range(3)]
            hi = [max(v.co[i] for v in body.data.vertices) for i in range(3)]
            raise RuntimeError("idleCycle.rigidParts %s: region holds no skinned vertex (%d vertices inside; mesh "
                               "bounds %s..%s)" % (rp["name"], nin, [round(x, 2) for x in lo], [round(x, 2) for x in hi]))
        par = rp.get("parent") or max(tot, key=tot.get)
        if par not in g["parent_of"] and par != "Root":
            raise RuntimeError("idleCycle.rigidParts %s: parent %s is not a rig bone" % (rp["name"], par))
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        eb = rig.data.edit_bones
        b = eb.new(rp["name"]); b.head, b.tail = c + ax * h0, c + ax * h1; b.roll = 0
        b.parent = eb[par]
        bpy.ops.object.mode_set(mode='OBJECT')
        gi = body.vertex_groups.new(name=rp["name"]).index
        bm = bmesh.new(); bm.from_mesh(body.data)
        dl = bm.verts.layers.deform.verify()
        fin = {f.index: all(inside(v.co) for v in f.verts) for f in bm.faces}
        cut = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1]
        bmesh.ops.split_edges(bm, edges=cut)
        n = 0
        for v in bm.verts:
            if v.link_faces and all(fin.get(f.index, False) and all(inside(u.co) for u in f.verts) for f in v.link_faces):
                d = v[dl]; d.clear(); d[gi] = 1.0; n += 1
        bm.to_mesh(body.data); bm.free(); body.data.update()
        g["bone_names"].append(rp["name"]); g["parent_of"][rp["name"]] = par
        g["STATIC"].add(rp["name"])          # rigid with its parent through the capture pose; see after_pose
        created.append(rp["name"])
        print("HOOK IDLECYCLE rigid part", rp["name"], "parent", par, "verts", n, "split edges", len(cut))
    g["IDLECYCLE_PARTS"] = created


def after_pose(g):
    # from here on the part is an ordinary bone: silhouette corrections and death shatter move it
    for n in g.get("IDLECYCLE_PARTS", []):
        g["STATIC"].discard(n)


def before_keys(g):
    sp = g["cfg"].get("idleCycle")
    if not sp:
        return
    if not any(sp.get(k) for k in ("rot", "spin", "wave", "lift")):
        # rigidParts only (e.g. hota_factory_sentinel_automaton's arm bones): no cycle to author, so the capture's
        # own Idle stays as it is instead of being re-chained from its first frame
        return
    Matrix, Vector = g["Matrix"], g["Vector"]
    rest, parent_of, posed = g["rest"], g["parent_of"], g["posed_world"]
    segs = [s for s in json.load(open(g["MASTER"]))["segments"] if s["contractSuffix"] == sp.get("clip", "Idle")]
    if not segs:
        raise RuntimeError("idleCycle: no segment with contract suffix %r" % sp.get("clip", "Idle"))
    seg = max(segs, key=lambda s: s["frameCount"])
    t0, n = seg["globalStart"], seg["frameCount"]
    A0 = posed[t0]
    # rig bones are re-chained from frame 0; bones outside the rig tree (conflux rubble chunks,
    # parked until the death clip) keep each frame's own pose
    names = [b for b in A0 if b != "Root" and b in parent_of]
    depth = {}

    def dep(b):
        if b == "Root":
            return 0
        if b not in depth:
            depth[b] = dep(parent_of[b]) + 1
        return depth[b]
    order = sorted(names, key=dep)
    local0 = {b: A0[parent_of[b]].inverted() @ A0[b] for b in order}
    cyc = sp.get("cycles", 1)
    unknown = set()

    def chain_bones(w):
        if "bones" in w:
            return list(w["bones"])
        return sorted(b for b in order if b.startswith(w["prefix"]))
    waves = [(w, chain_bones(w)) for w in sp.get("wave", [])]
    for w, bs in waves:
        if not bs:
            raise RuntimeError("idleCycle: wave matches no bone (%s)" % w.get("prefix", w.get("bones")))
    peaks = {}
    for i in range(n):
        u = cyc * i / n
        D = {}

        def add(b, deg, axis):
            if b not in A0:
                unknown.add(b); return
            if abs(deg) < 1e-9:
                return
            R = Matrix.Rotation(math.radians(deg), 3, Vector(axis).normalized())
            D[b] = R @ D.get(b, Matrix.Identity(3))
            peaks[b] = max(peaks.get(b, 0.0), abs(deg))
        for r in sp.get("rot", []):
            v = _shape(r.get("shape", "breath"), r["peak"], u, r.get("phase", 0.0))
            for b, share in r["bones"]:
                add(b, v * share, r["axis"])
        for sp_ in sp.get("spin", []):
            # a turn about the bone's own rest axis (its head-to-tail line), `turns` per loop
            add(sp_["bone"], 360.0 * sp_.get("turns", 1) * u, tuple(rest[sp_["bone"]].to_3x3().col[1]) if sp_["bone"] in rest else (0, 0, 1))
        for w, bs in waves:
            lam = w.get("wavelength", len(bs)); grow = max(w.get("grow", 1), 1)
            for k, b in enumerate(bs):
                env = min(1.0, (k + 1) / grow)
                ph0 = -2 * math.pi * k / lam + math.radians(w.get("phase", 0.0))
                ang = w["amp"] * env * (math.sin(2 * math.pi * u + ph0) - math.sin(ph0))
                add(b, ang, w["axis"])
        A = {"Root": posed[t0 + i]["Root"]}
        extra = {b: M for b, M in posed[t0 + i].items() if b != "Root" and b not in parent_of}
        for b in order:
            M = A[parent_of[b]] @ local0[b]
            if b in D:
                Rr = rest[b].to_3x3()
                M = M @ (Rr.inverted() @ D[b] @ Rr).to_4x4()
            A[b] = M
        lf = sp.get("lift")
        if lf:
            off = Vector(lf["vec"]) * _shape(lf.get("shape", "breath"), 1.0, u, lf.get("phase", 0.0))
            T = Matrix.Translation(off)
            for b in order:
                A[b] = T @ A[b]
        A.update(extra)
        posed[t0 + i].clear(); posed[t0 + i].update(A)
    if unknown:
        raise RuntimeError("idleCycle: unknown bones %s" % sorted(unknown))
    print("HOOK IDLECYCLE frames", n, "from", t0, "peak deg", {b: round(v, 1) for b, v in sorted(peaks.items())})
