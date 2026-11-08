"""Rig a Meshy unit mesh with an owned skeleton and drive it from its DEF-frame capture.

Usage (headless Blender):
  blender -b --factory-startup -P build_unit.py -- <unit.json> <mesh.glb> <raw_capture.npz>
          <master_sequence.json> <sprite_track.json> <out.blend>

First run exports <out>.heat.npz and stops; run surface_weights.py to write
<out>.weights.npz, then run this again to build the rig and the animation.
See README.md for the method and the unit-config keys.
"""
import bpy, bmesh, sys, os, json, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, kdtree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ext"))
import importlib

def run_hooks(stage):
    """Faction extensions (tools/homm3_def_retarget/ext/<module>.py, listed in the unit config's
    "extensions") may define functions named after a stage; each receives this module's globals()
    and may read or modify anything (weights, posed_world, rest, keyed ...). Stages:
    after_skin (weights and rigid regions assigned, before motion), after_pose (posed_world
    built, before sprite camera), before_keys (all world poses final, before actions are written)."""
    for name in cfg.get("extensions", []):
        fn = getattr(importlib.import_module(name), stage, None)
        if fn:
            fn(globals())
            print("HOOK", name, stage)

argv = sys.argv[sys.argv.index("--") + 1:]
CFG, MESH, CAPTURE, MASTER, SPRITE, OUT = argv[:6]
cfg = json.load(open(CFG))
J = {k: tuple(v) for k, v in cfg["joints"].items()}
F = cfg.get("flail")
LOOPS = cfg.get("loops", ["Idle", "Move"])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=MESH)
# source-mesh provenance (source_mesh.py): saved with the .blend, written into every GLB export_glb.py makes from it
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import source_mesh  # noqa: E402
bpy.context.scene[source_mesh.SCENE_PROP] = json.dumps(source_mesh.stamp_for(MESH))
body = max((o for o in bpy.data.objects if o.type == 'MESH' and o.name != 'Icosphere'), key=lambda o: len(o.data.vertices))
mw = body.matrix_world.copy(); body.parent = None; body.matrix_world = mw
for o in list(bpy.data.objects):
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
for m in list(body.modifiers):
    body.modifiers.remove(m)
body.vertex_groups.clear()
bpy.context.view_layer.objects.active = body; body.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
body.name = cfg["unit"]

# ---------------------------------------------------------------- skeleton
# (bone, head joint, tail joint, parent, capture side-arm it copies or None)
BONES = [("Hips", "Hips", "Spine", "Root"), ("Spine", "Spine", "Spine1", "Hips"),
         ("Spine1", "Spine1", "Spine2", "Spine"), ("Spine2", "Spine2", "Neck", "Spine1"),
         ("Neck", "Neck", "Head", "Spine2"), ("Head", "Head", "HeadTop_End", "Neck")]
ARM_PARTS = [("Shoulder", "Arm", "Spine2"), ("Arm", "ForeArm", "Shoulder"),
             ("ForeArm", "Hand", "Arm"), ("Hand", "Hand_End", "ForeArm")]
LEG_PARTS = [("UpLeg", "Leg", "Hips"), ("Leg", "Foot", "UpLeg"),
             ("Foot", "ToeBase", "Leg"), ("ToeBase", "Toe_End", "Foot")]
DRIVE_SRC = {}   # bone -> the capture bone whose motion it copies
for s in ("Left", "Right"):
    for part, tail, par in ARM_PARTS:
        if f"{s}{part}" in J:
            BONES.append((f"{s}{part}", f"{s}{part}", f"{s}{tail}", par if par == "Spine2" else f"{s}{par}"))
    for part, tail, par in LEG_PARTS:
        if f"{s}{part}" in J:
            BONES.append((f"{s}{part}", f"{s}{part}", f"{s}{tail}", par if par == "Hips" else f"{s}{par}"))
# extra arm pairs (naga): prefixed joints, each copying one capture arm
for ex in cfg.get("extraArms", []):
    pre, side = ex["prefix"], ex["side"]
    for k, v in ex["joints"].items():
        J[pre + k] = tuple(v)
    for part, tail, par in ARM_PARTS:
        BONES.append((pre + part, pre + part, pre + tail, par if par == "Spine2" else pre + par))
        DRIVE_SRC[pre + part] = side + part
# static chains (a naga's coil): parented to Root, never driven, but deforming, so heat blends
# the body between the moving hips and the planted coil
STATIC = set()
for ch in cfg.get("staticChains", []):
    pts = ch["points"]
    for i in range(len(pts) - 1):
        n = f"{ch['prefix']}{i}"
        J[n], J[n + "_t"] = tuple(pts[i]), tuple(pts[i + 1])
        BONES.append((n, n, n + "_t", "Root" if i == 0 else f"{ch['prefix']}{i - 1}"))
        STATIC.add(n)
bone_names = [b[0] for b in BONES]
parent_of = {b[0]: b[3] for b in BONES}

FLAIL = []
if F:
    TOP, GRIP = Vector(F["chainTop"]), Vector(F["grip"])
    C1, C2 = Vector(F["chain"][0]), Vector(F["chain"][1])
    BALL_C, BALL_R = Vector(F["ball"]), F["ballR"]
    FLAIL = [("Flail1", GRIP, C1, "RightHand"), ("Flail2", C1, C2, "Flail1"), ("FlailBall", C2, BALL_C, "Flail2")]

arm_data = bpy.data.armatures.new(cfg["unit"] + "_Rig")
rig = bpy.data.objects.new(cfg["unit"] + "_Rig", arm_data)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_data.edit_bones
root = eb.new("Root"); root.head, root.tail = Vector((0, 0, 0)), Vector((0, 0, 0.1))
for name, h, t, p in BONES:
    b = eb.new(name); b.head, b.tail = Vector(J[h]), Vector(J[t]); b.roll = 0
for name, h, t, p in BONES:
    eb[name].parent = eb[p]
bpy.ops.object.mode_set(mode='OBJECT')
arm_data.bones["Root"].use_deform = False   # Root only owns explicit static regions

# ---------------------------------------------------------------- body weights: bone heat on a welded copy
wcopy = body.copy(); wcopy.data = body.data.copy(); bpy.context.scene.collection.objects.link(wcopy)
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = wcopy; wcopy.select_set(True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=1e-5); bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.select_all(action='DESELECT')
wcopy.select_set(True); rig.select_set(True); bpy.context.view_layer.objects.active = rig
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
bpy.context.view_layer.objects.active = wcopy
bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5, repeat=3)
bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
bpy.ops.object.vertex_group_normalize_all(lock_active=False)
bpy.ops.object.mode_set(mode='OBJECT')

_kd = kdtree.KDTree(len(wcopy.data.vertices))
for v in wcopy.data.vertices:
    _kd.insert(v.co, v.index)
_kd.balance()

def widx(co):
    """Welded-copy vertex index for a body position (merging can move a vertex by up to 1e-5)."""
    return _kd.find(co)[1]

wnames = {g.index: g.name for g in wcopy.vertex_groups}
H = np.zeros((len(wcopy.data.vertices), len(bone_names)), dtype=np.float32)
for v in wcopy.data.vertices:
    for g in v.groups:
        if wnames[g.group] in bone_names:
            H[v.index, bone_names.index(wnames[g.group])] = g.weight
WFILE = OUT + ".weights.npz"
if not os.path.exists(WFILE):
    # base colour per welded vertex (used to keep light metal blades out of a snake tail)
    _img = next(nd.image for nd in body.data.materials[0].node_tree.nodes if nd.type == 'TEX_IMAGE' and nd.image)
    _w, _h = _img.size; _px = np.array(_img.pixels[:]).reshape(_h, _w, 4)
    _uvl = body.data.uv_layers[0].data; _BC = np.zeros((len(body.data.vertices), 3))
    for l in body.data.loops:
        uu, vv = _uvl[l.index].uv
        _BC[l.vertex_index] = _px[min(int(vv * _h), _h - 1), min(int(uu * _w), _w - 1), :3]
    _kdb = kdtree.KDTree(len(body.data.vertices))
    for v in body.data.vertices:
        _kdb.insert(v.co, v.index)
    _kdb.balance()
    WCOL = np.array([_BC[_kdb.find(v.co)[1]] for v in wcopy.data.vertices])
    np.savez(OUT + ".heat.npz", C=WCOL, P=np.array([v.co[:] for v in wcopy.data.vertices]),
             E=np.array([e.vertices[:] for e in wcopy.data.edges]), H=H,
             SEG=np.array([[J[h], J[t]] for _, h, t, _ in BONES]), names=np.array(bone_names))
    print("EXPORTED heat graph; run surface_weights.py then rebuild")
    sys.exit(0)
bpy.data.objects.remove(wcopy, do_unlink=True)
wf = np.load(WFILE); Wt, WS, SL = wf["W"], wf["WS"], wf["SL"]
if not (np.isfinite(Wt).all() and np.isfinite(WS).all()):
    # a NaN row passes no `row > 1e-4` test: the vertex would export unweighted (neutral_bone) and stand still
    raise RuntimeError(f"{WFILE}: {int((~np.isfinite(Wt)).any(1).sum())} non-finite weight rows (surface_weights.py)")
for n in bone_names + ["Root"] + [f[0] for f in FLAIL]:
    body.vertex_groups.new(name=n)
for v in body.data.vertices:
    row = Wt[widx(v.co)]
    for bi in np.nonzero(row > 1e-4)[0]:
        body.vertex_groups[bone_names[bi]].add([v.index], float(row[bi]), 'REPLACE')

# articulated snake tail (nagas): bones along the surface-distance centreline, weights by
# distance along the body (from surface_weights.py)
TAILB = []
TAILCFG_BUILD = cfg.get("tail", {})
if "TP" in wf.files and len(wf["TP"]):
    TPts = [Vector(tuple(x)) for x in wf["TP"]]; TWt, TMk = wf["TW"], wf["TM"]
    TAILB = [f"Tail_{k:02d}" for k in range(len(TPts) - 1)]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for k, n in enumerate(TAILB):
        b = eb.new(n); b.head, b.tail = TPts[k], TPts[k + 1]; b.roll = 0
        b.parent = eb["Hips"] if k == 0 else eb[TAILB[k - 1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for n in TAILB:
        body.vertex_groups.new(name=n)
    # blend the waist: from the top of the tail down `waistBlend` segments, keep a falling share of
    # the heat weights (Hips/arms) so the seam between the torso and Tail_00 is not a hard cut
    WB = cfg.get("tail", {}).get("waistBlend", 0.6)
    TUb = wf["TU"]
    nt = 0
    for v in body.data.vertices:
        wi = widx(v.co)
        if TMk[wi]:
            keep = max(0.0, 1.0 - TUb[wi] / WB) if WB > 0 else 0.0
            old_w = [(g.group, g.weight * keep) for g in v.groups]
            for g in list(v.groups):
                body.vertex_groups[g.group].remove([v.index])
            for gi_, w_ in old_w:
                if w_ > 1e-4:
                    body.vertex_groups[gi_].add([v.index], w_, 'REPLACE')
            for k in np.nonzero(TWt[wi] > 1e-4)[0]:
                body.vertex_groups[TAILB[k]].add([v.index], float(TWt[wi][k]) * (1 - keep), 'REPLACE')
            nt += 1
    print("TAIL bones", len(TAILB), "verts", nt)

# ground anchor (a naga's coil): below z0 the mesh belongs to the static Root, easing into the
# heat weights up to z1 -- no cut, so the snake body bends continuously into the planted coil
if "anchorBelowZ" in cfg:
    z0, z1 = cfg["anchorBelowZ"]
    far = cfg.get("anchorFar")   # {"axis": [x, y], "radius": [r0, r1], "zMax": z}: coil parts away from the torso
    for v in body.data.vertices:
        a = min(1.0, max(0.0, (z1 - v.co.z) / max(z1 - z0, 1e-6)))
        if far and v.co.z < far["zMax"]:
            d = math.hypot(v.co.x - far["axis"][0], v.co.y - far["axis"][1])
            r0, r1 = far["radius"]
            a = max(a, min(1.0, max(0.0, (d - r0) / (r1 - r0))))
        if a <= 0:
            continue
        for g in v.groups:
            g.weight *= (1 - a)
        body.vertex_groups["Root"].add([v.index], a, 'REPLACE')

# ---------------------------------------------------------------- rigid regions cut free: flail, props, static parts
WINGS = cfg.get("wings", [])
if WINGS:
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for w in WINGS:
        b = eb.new(w["bone"]); b.head, b.tail = Vector(w["head"]), Vector(w["tail"]); b.roll = 0
        b.parent = eb[w.get("parent", "Spine2")]
    bpy.ops.object.mode_set(mode='OBJECT')
    for w in WINGS:
        body.vertex_groups.new(name=w["bone"])
if FLAIL:
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for name, h, t, p in FLAIL:
        b = eb.new(name); b.head, b.tail = h, t; b.roll = 0; b.parent = eb[p]
    bpy.ops.object.mode_set(mode='OBJECT')

def seg_dist(p, a, b):
    ab = b - a; t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.dot(ab), 1e-12)))
    return (p - (a + ab * t)).length

_col = None
def vert_color(p):
    """Base-colour texture sample at the rest vertex nearest p (built lazily)."""
    global _col
    if _col is None:
        img = next(n.image for n in body.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE' and n.image)
        w, h = img.size; px = np.array(img.pixels[:]).reshape(h, w, 4)
        uvl = body.data.uv_layers[0].data
        C = np.zeros((len(body.data.vertices), 3))
        for l in body.data.loops:
            u, v = uvl[l.index].uv
            C[l.vertex_index] = px[min(int(v * h), h - 1), min(int(u * w), w - 1), :3]
        kd = kdtree.KDTree(len(body.data.vertices))
        for v in body.data.vertices:
            kd.insert(v.co, v.index)
        kd.balance(); _col = (C, kd)
    C, kd = _col
    return C[kd.find(p)[1]]

def make_owner(region):
    """Return f(p) -> bone name or None for one region spec from the config."""
    bone = region["bone"]
    if "segments" in region:
        segs = [(Vector(a), Vector(b)) for a, b in region["segments"]]; r = region["radius"]
        test = lambda p: min(seg_dist(p, a, b) for a, b in segs) < r
    elif "sphere" in region:
        c, r = Vector(region["sphere"][0]), region["sphere"][1]
        test = lambda p: (p - c).length < r
    else:
        lo, hi = Vector(region["box"][0]), Vector(region["box"][1])
        test = lambda p: all(lo[i] <= p[i] <= hi[i] for i in range(3))
    if "minBlueOverRed" in region and "segments" in region:
        # colour-gated: bluish texels anywhere in the radius, or anything close to the axis
        geo, core, mbr = test, region.get("coreRadius", 0.035), region["minBlueOverRed"]
        def test(p, geo=geo):
            if not geo(p):
                return False
            if min(seg_dist(p, a, b) for a, b in segs) < core:
                return True
            c = vert_color(p); return c[2] - c[0] > mbr
    if region.get("wholeIslands"):
        # opt-in (sea witch cutlass, 2026-10-11): only whole connected mesh islands that lie mostly inside the region
        # (a prop cut free by mesh surgery), never the body surface the region also reaches (the fist around a grip)
        geo2, frac = test, float(region["wholeIslands"])
        me = body.data; nv = len(me.vertices); par = list(range(nv))
        def fnd(a):
            while par[a] != a:
                par[a] = par[par[a]]; a = par[a]
            return a
        for e in me.edges:
            par[fnd(e.vertices[0])] = fnd(e.vertices[1])
        first = {}
        for v in me.vertices:                     # weld UV seams: islands by position, not by index
            k_ = tuple(round(c, 5) for c in v.co)
            if k_ in first:
                par[fnd(v.index)] = fnd(first[k_])
            else:
                first[k_] = v.index
        tot, ins = {}, {}
        for v in me.vertices:
            r_ = fnd(v.index); tot[r_] = tot.get(r_, 0) + 1; ins[r_] = ins.get(r_, 0) + bool(geo2(v.co))
        keep = {tuple(round(c, 5) for c in v.co) for v in me.vertices if ins[fnd(v.index)] >= frac * tot[fnd(v.index)]}
        test = lambda p, keep=keep: tuple(round(c, 5) for c in p) in keep
    excl = [make_owner(dict(e, bone="x")) for e in region.get("exclude", [])]
    return lambda p: bone if test(p) and not any(e(p) for e in excl) else None

owners = []
if FLAIL:
    CHAIN_SEGS = [("RightHand", TOP, GRIP, F["radius"]), ("Flail1", GRIP, C1, F["radiusBelowGrip"]),
                  ("Flail2", C1, C2, F["radiusBelowGrip"])]
    def flail_owner(p):
        if (p - BALL_C).length < BALL_R:
            return "FlailBall"
        best = None
        for name, a, b, r in CHAIN_SEGS:
            d = seg_dist(p, a, b)
            if d < r and (best is None or d < best[1]):
                best = (name, d)
        return best[0] if best else None
    owners.append(("flail", flail_owner))
for w in WINGS:
    owners.append((w["bone"], make_owner(dict(w["region"], bone=w["bone"]))))
for i, reg in enumerate(cfg.get("props", [])):
    owners.append((reg.get("name", f"prop{i}"), make_owner(reg)))

bm = bmesh.new(); bm.from_mesh(body.data)
dl = bm.verts.layers.deform.verify()
if TAILB:
    # coil loops that Meshy fused where they touch: an edge whose ends lie far apart *along the
    # body* bridges two loops, and would tear when the tail uncoils -- cut it
    TUw = wf["TU"]
    tu = {v.index: float(TUw[widx(v.co)]) for v in bm.verts}
    fused = [e for e in bm.edges if min(tu[e.verts[0].index], tu[e.verts[1].index]) >= 0
             and abs(tu[e.verts[0].index] - tu[e.verts[1].index]) > TAILCFG_BUILD.get("fuseCut", 1.2)]
    # tail against a non-tail part (a blade resting on the coil), away from the waist
    fused += [e for e in bm.edges if (tu[e.verts[0].index] < 0) != (tu[e.verts[1].index] < 0)
              and max(tu[e.verts[0].index], tu[e.verts[1].index]) > TAILCFG_BUILD.get("waistBlend", 0.6) * 2]
    bmesh.ops.split_edges(bm, edges=fused)
    print("TAIL fused-loop edges cut", len(fused))
    # triangles straddling tail and a non-tail part (a blade on the coil) belong to the part:
    # split them off the tail and give their tail-weighted corners the part's weights
    WBc = TAILCFG_BUILD.get("waistBlend", 0.6) * 2
    tu = {v.index: float(TUw[widx(v.co)]) for v in bm.verts}
    mixed = {f.index for f in bm.faces if any(tu[v.index] < 0 for v in f.verts) and any(tu[v.index] > WBc for v in f.verts)}
    bmesh.ops.split_edges(bm, edges=[e for e in bm.edges if len({f.index in mixed for f in e.link_faces}) > 1])
    bm.faces.ensure_lookup_table()
    mixed = {f.index for f in bm.faces if any(tu.get(v.index, float(TUw[widx(v.co)])) < 0 for v in f.verts)
             and any(float(TUw[widx(v.co)]) > WBc for v in f.verts)}
    nfix = 0
    for v in bm.verts:
        if v.link_faces and all(f.index in mixed for f in v.link_faces) and float(TUw[widx(v.co)]) >= 0:
            donor = next((u for f in v.link_faces for u in f.verts if float(TUw[widx(u.co)]) < 0), None)
            if donor is not None:
                d = v[dl]; d.clear()
                for k_, w_ in donor[dl].items():
                    d[k_] = w_
                nfix += 1
    print("TAIL straddling faces", len(mixed), "corners reassigned", nfix)
gidx = {g.name: g.index for g in body.vertex_groups}
taken = set()

def split_region(inside):
    fin = {f.index: all(inside(v) for v in f.verts) for f in bm.faces}
    edges = [e for e in bm.edges if len({fin[f.index] for f in e.link_faces}) > 1]
    bmesh.ops.split_edges(bm, edges=edges)
    bm.faces.ensure_lookup_table()
    return {f.index for f in bm.faces if all(inside(v) for v in f.verts)}, len(edges)

# metal blades (naga swords resting on the coil): connected light, unsaturated parts longer than
# minExtent are bound whole to the nearest hand -- a blade spanning two coil loops would otherwise
# be stretched along the tail when it uncoils
MB = cfg.get("metalBlades")
if MB:
    def is_metal(co):
        c = vert_color(co); mx = max(c); return mx > MB.get("minValue", 0.35) and (mx - min(c)) / max(mx, 1e-6) < MB.get("maxSat", 0.25)
    metal = {v.index: is_metal(v.co) for v in bm.verts}
    par_ = {i: i for i in metal}
    def fnd(a):
        while par_[a] != a:
            par_[a] = par_[par_[a]]; a = par_[a]
        return a
    for f in bm.faces:
        vs = [v.index for v in f.verts]
        if all(metal[i] for i in vs):
            for i in vs[1:]:
                par_[fnd(i)] = fnd(vs[0])
    comps = {}
    for f in bm.faces:
        vs = [v.index for v in f.verts]
        if all(metal[i] for i in vs):
            comps.setdefault(fnd(vs[0]), set()).update(vs)
    hands = [n for n in bone_names if n.endswith("Hand")]
    vmap = {}
    bm.verts.ensure_lookup_table()
    for vs in comps.values():
        pts = np.array([bm.verts[i].co[:] for i in vs])
        if np.linalg.norm(pts.max(0) - pts.min(0)) < MB.get("minExtent", 0.25):
            continue
        hb = min(hands, key=lambda h: min(np.linalg.norm(pts - np.array(J[h]), axis=1)))
        for i in vs:
            vmap[tuple(round(c, 6) for c in bm.verts[i].co)] = hb
    owners.insert(0, ("metalBlades", lambda p, vm=vmap: vm.get(tuple(round(c, 6) for c in p))))
    print("BLADES", len([1 for vs in comps.values()]), "metal parts,", len(vmap), "verts bound rigid")

for rname, own in owners:
    faces, ne = split_region(lambda v: own(v.co) is not None and v.index not in taken)
    counts = {}
    for v in bm.verts:
        if v.link_faces and all(f.index in faces for f in v.link_faces):
            o = own(v.co); d = v[dl]; d.clear(); d[gidx[o]] = 1.0; counts[o] = counts.get(o, 0) + 1
            taken.add(v.index)
    print("REGION", rname, "split edges", ne, "ownership", counts)
if SL.any():
    sl_faces, n_sl = split_region(lambda v: bool(SL[widx(v.co)]) and v.index not in taken)
    ns = 0
    for v in bm.verts:
        if v.link_faces and all(f.index in sl_faces for f in v.link_faces):
            row = WS[widx(v.co)]; d = v[dl]; d.clear()
            for bi in np.nonzero(row > 1e-4)[0]:
                d[gidx[bone_names[bi]]] = float(row[bi])
            ns += 1
    print("SLEEVE split edges", n_sl, "sleeve verts", ns)
bm.to_mesh(body.data); bm.free()
arm_data.bones["Root"].use_deform = True
mod = body.modifiers.new("Armature", 'ARMATURE'); mod.object = rig
body.parent = rig
run_hooks("after_skin")

# ---------------------------------------------------------------- capture retarget (joint directions, delta from idle frame 0)
cap = np.load(CAPTURE)
P = cap['pred_position'].astype(float)
ix = {str(n).split(":")[-1]: i for i, n in enumerate(cap['joint_names'])}
T = P.shape[0]

def V(a):
    return Vector((float(a[0]), float(a[1]), float(a[2])))

def frame_of(a, b):
    a = a.normalized(); b = (b - a * a.dot(b)).normalized()
    return Matrix((a, b, a.cross(b))).transposed()

def map_capture(P):
    """Capture joints -> Blender world, fixed by idle frame 0 (left -> +X, up -> +Z)."""
    p0 = P[0]
    Fcap = frame_of(V(p0[ix['Spine2']] - p0[ix['Hips']]),
                    V(p0[ix['LeftUpLeg']] - p0[ix['RightUpLeg']]) + V(p0[ix['LeftArm']] - p0[ix['RightArm']]))
    Mcap = frame_of(Vector((0, 0, 1)), Vector((1, 0, 0))) @ Fcap.transposed()
    return [[Mcap @ V(P[t, j]) for j in range(P.shape[1])] for t in range(P.shape[0])]
W = map_capture(P)
jw = lambda t, n: W[t][ix[n]]
hipline = lambda t: jw(t, 'LeftUpLeg') - jw(t, 'RightUpLeg')
shoulderline = lambda t: jw(t, 'LeftArm') - jw(t, 'RightArm')
DRIVE = {"Hips": ("Hips", "Spine1", hipline), "Spine": ("Spine", "Spine1", hipline),
         "Spine1": ("Spine1", "Spine2", lambda t: hipline(t) + shoulderline(t)),
         "Spine2": ("Spine2", "Neck", shoulderline), "Neck": ("Neck", "Head", shoulderline),
         "Head": ("Head", "HeadTop_End", shoulderline)}
for s in ("Left", "Right"):
    DRIVE.update({f"{s}Shoulder": (f"{s}Shoulder", f"{s}Arm", None), f"{s}Arm": (f"{s}Arm", f"{s}ForeArm", None),
                  f"{s}ForeArm": (f"{s}ForeArm", f"{s}Hand", None), f"{s}Hand": (f"{s}ForeArm", f"{s}Hand", None),
                  f"{s}UpLeg": (f"{s}UpLeg", f"{s}Leg", None), f"{s}Leg": (f"{s}Leg", f"{s}Foot", None),
                  f"{s}Foot": (f"{s}Foot", f"{s}ToeBase", None), f"{s}ToeBase": (f"{s}ToeBase", f"{s}Toe_End", None)})
for b, src in DRIVE_SRC.items():
    DRIVE[b] = DRIVE[src]

# "absolute" limbs point along the capture's own direction instead of adding its change since
# idle frame 0 to the mesh's rest direction; large arm moves (a staff raised overhead) then land
# where the DEF puts them even when the mesh's rest arm differs from the capture's idle arm
ABS_SUFFIX = tuple(cfg.get("absoluteLimbs", []))
ABS_MAX_DEG = cfg.get("absoluteMaxRestAngle", 35.0)
def delta(t, a, b, lat, bone=None):
    d0 = jw(0, b) - jw(0, a); d1 = jw(t, b) - jw(t, a)
    if lat is None and bone is not None and ABS_SUFFIX and bone.endswith(ABS_SUFFIX):
        m0 = rest[bone].to_3x3().col[1]
        # only where the mesh's rest limb already agrees with the capture's idle limb; a
        # large disagreement (crossed arms, a misplaced seed) would deform the rest pose
        if m0.angle(d0) < math.radians(ABS_MAX_DEG):
            return m0.normalized().rotation_difference(d1.normalized()).to_matrix()
    if lat is None:
        return d0.normalized().rotation_difference(d1.normalized()).to_matrix()
    return frame_of(d1, lat(t)) @ frame_of(d0, lat(0)).transposed()

bones = rig.data.bones
rest = {b.name: b.matrix_local.copy() for b in bones}
cap_leg = (jw(0, 'LeftUpLeg') - jw(0, 'LeftLeg')).length + (jw(0, 'LeftLeg') - jw(0, 'LeftFoot')).length
if "LeftUpLeg" in J:
    mesh_leg = (Vector(J['LeftUpLeg']) - Vector(J['LeftLeg'])).length + (Vector(J['LeftLeg']) - Vector(J['LeftFoot'])).length
else:
    mesh_leg = Vector(J["Hips"]).z * 0.9
scale = mesh_leg / cap_leg
GROUND = cfg.get("grounding", True)
LEG_DAMP = cfg.get("legDamp", 1.0)
print("capture forward (expect ~ -Y):", tuple(round(x, 2) for x in (jw(0, 'LeftToe_End') + jw(0, 'RightToe_End') - jw(0, 'LeftFoot') - jw(0, 'RightFoot')).normalized()))

def pose_frame(t):
    A = {"Root": rest["Root"].copy()}
    for name in bone_names:
        Rb = rest[name]; par = parent_of[name]
        head = A[par] @ (rest[par].inverted() @ Rb.translation)
        if name in STATIC:
            A[name] = A[par] @ rest[par].inverted() @ Rb
            continue
        a, b, lat = DRIVE[name]
        Dm = delta(t, a, b, lat, name)
        if LEG_DAMP < 1.0 and name.endswith(("UpLeg", "Leg", "Foot", "ToeBase")):
            # legs hidden under a robe: a human capture's wide stances shred the cloth
            Dm = Quaternion().slerp(Dm.to_quaternion(), LEG_DAMP).to_matrix()
        A[name] = Matrix.Translation(head) @ (Dm @ Rb.to_3x3()).to_4x4()
    if GROUND:
        low_t = min(p.z for p in W[t]); low_0 = min(p.z for p in W[0])
        dz = ((jw(t, 'Hips').z - low_t) - (jw(0, 'Hips').z - low_0)) * scale
        A = {n: (m if n == "Root" or n in STATIC else Matrix.Translation(Vector((0, 0, dz))) @ m) for n, m in A.items()}
    return A
posed_world = [pose_frame(t) for t in range(T)]
run_hooks("after_pose")

# clips borrowed from a related unit's capture (the Colossus DEF has a single idle frame; the
# Titan, its base form, has an 8-frame idle). Delta retarget makes the donor's idle frame 0 the
# mesh's rest pose, so the donor motion lands on this mesh's own proportions.
borrowed = {}
for clip, donor in cfg.get("borrowClips", {}).items():
    dl_ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(CAPTURE))))
    droot = os.path.join(os.path.dirname(dl_), donor, "linked_master")
    Pd = np.load(os.path.join(droot, "capture", "capture", "raw_capture.npz"))['pred_position'].astype(float)
    dms = json.load(open(os.path.join(droot, "master_sequence", "master_sequence.json")))
    seg = max((x for x in dms["segments"] if x["contractSuffix"] == clip), key=lambda x: x["frameCount"])
    W_own = W; W = map_capture(Pd)
    borrowed["Unit_" + clip] = [pose_frame(t) for t in range(seg["globalStart"], seg["globalEnd"])]
    W = W_own
    print("BORROWED", clip, "from", donor, len(borrowed["Unit_" + clip]), "frames")

# ---------------------------------------------------------------- sprite camera calibrated on idle frame 0
sj = json.load(open(SPRITE))
SW, SH = sj["size"]
scene = bpy.context.scene
fwd_cam = Vector((0.416, 0.893, -0.174)).normalized()   # front-left of the model: it faces screen-right like the DEF
right = fwd_cam.cross(Vector((0, 0, 1))).normalized(); up = right.cross(fwd_cam).normalized()
rv = [v.co for v in body.data.vertices]
xs = [p.dot(right) for p in rv]; ys = [p.dot(up) for p in rv]
bx0, by0, bx1, by1 = sj["bbox0"]
s_px = (by1 - by0) / (max(ys) - min(ys))
oy = by1 + s_px * min(ys)
ox = (bx0 + bx1) / 2 - s_px * (max(xs) + min(xs)) / 2
cam = bpy.data.objects.new("SpriteCam", bpy.data.cameras.new("SpriteCam"))
scene.collection.objects.link(cam); scene.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = max(SW, SH) / s_px
cam.location = right * ((SW / 2 - ox) / s_px) + up * ((oy - SH / 2) / s_px) - fwd_cam * 8
cam.rotation_euler = fwd_cam.to_track_quat('-Z', 'Y').to_euler()
scene.render.resolution_x, scene.render.resolution_y = SW, SH
json.dump({"right": list(right), "up": list(up), "forward": list(fwd_cam), "pxPerUnit": s_px,
           "offset": [ox, oy], "size": [SW, SH]}, open(OUT + ".spritecam.json", "w"))

# ---------------------------------------------------------------- flail: ball on the DEF ball's view ray, chain taut from the fist
if FLAIL:
    grip_local = rest["RightHand"].inverted() @ GRIP
    L = (BALL_C - GRIP).length
    seg_f = [min((C1 - GRIP).length / L, 0.95), min(((C1 - GRIP).length + (C2 - C1).length) / L, 0.95)]
    prevB = BALL_C.copy()
    slack_t = {}     # global frame -> "ground" | "near"
    for sg in json.load(open(MASTER))["segments"]:
        v = F.get("slack", {}).get(sg["contractSuffix"])
        if v is not None:
            a_, b_, m_ = (v, sg["frameCount"], "ground") if isinstance(v, int) else (v[0], v[1], v[2] if len(v) > 2 else "ground")
            for i_ in range(a_, min(b_, sg["frameCount"])):
                slack_t[sg["globalStart"] + i_] = m_
    for t in range(T):
        A = posed_world[t]
        G = A["RightHand"] @ grip_local
        px, py = sj["balls"][t][:2]
        Q = right * ((px - ox) / s_px) + up * ((oy - py) / s_px)
        w = Q - G; bq = w.dot(fwd_cam); disc = bq * bq - (w.dot(w) - L * L)
        if disc >= 0:
            B = min((Q + fwd_cam * (-bq + r) for r in (math.sqrt(disc), -math.sqrt(disc))), key=lambda c: (c - prevB).length)
        else:
            B = G + (Q + fwd_cam * (-bq) - G).normalized() * L
        if B.z < BALL_R * 0.95:
            B.z = BALL_R * 0.95
            h = Vector((B.x - G.x, B.y - G.y, 0)); vz = B.z - G.z
            B = Vector((G.x, G.y, B.z)) + h.normalized() * math.sqrt(max(L * L - vz * vz, 1e-6))
        prevB = B
        C = [G, G.lerp(B, seg_f[0]), G.lerp(B, seg_f[1]), B]
        if t in slack_t and fwd_cam.z < -1e-6:
            # opt-in "slack": {clip: first local frame | [first, end, "ground" | "near"]}: the chain goes slack
            # (fixed link lengths, 2-link IK bent toward the ground). "ground": the ball rests where the DEF ball's view
            # ray meets the ground, not held up in the air on a taut chain off a fallen body (h3_gremlin_upg Death);
            # "near": the ball sits on the ray at its point nearest the fist (at least ballR + 0.1 off it), held up
            # close like the DEF instead of out at the end of a stiff horizontal chain (h3_gremlin_upg Defence)
            if slack_t[t] == "near":
                Bg = Q + fwd_cam * (-(Q - G).dot(fwd_cam))
                if (Bg - G).length < BALL_R + 0.1:
                    Bg = G + ((Bg - G).normalized() if (Bg - G).length > 1e-6 else Vector((0, 0, 1))) * (BALL_R + 0.1)
            else:
                zg = BALL_R * 0.95
                Bg = Q + fwd_cam * ((zg - Q.z) / fwd_cam.z)
            s0, s1, s2 = (C1 - GRIP).length, (C2 - C1).length, (BALL_C - C2).length
            if slack_t[t] == "ground" and (Bg - G).length > L * 0.97 and G.z - zg < L * 0.97:
                # the ray's ground point is out of the chain's reach (h3_gremlin_upg Death f5+: it lands behind the
                # heap): the ball rests on the ground toward it, at 0.97 of the chain's reach, instead of the taut
                # chain holding it up in the air
                hd = Vector((Bg.x - G.x, Bg.y - G.y, 0.0))
                hd = hd.normalized() if hd.length > 1e-6 else Vector((1.0, 0.0, 0.0))
                Bg = Vector((G.x, G.y, zg)) + hd * math.sqrt(max((L * 0.97) ** 2 - (G.z - zg) ** 2, 0.0))
            if (Bg - G).length <= L:
                T1 = (G + Bg) * 0.5; T1.z = F.get("radius", 0.06)
                P1 = G + (T1 - G).normalized() * s0
                d = max((Bg - P1).length, 1e-6); u = (Bg - P1) / d
                if d >= s1 + s2:
                    P1 = G + (Bg - G).normalized() * s0; d = max((Bg - P1).length, 1e-6); u = (Bg - P1) / d
                a = (s1 * s1 - s2 * s2 + d * d) / (2 * d); h = math.sqrt(max(s1 * s1 - a * a, 0.0))
                n = Vector((0, 0, -1)) - u * u.z
                n = n.normalized() if n.length > 1e-6 else Vector((0, 0, -1))
                P2 = P1 + u * a + n * h
                C = [G, P1, P2, P2 + (Bg - P2).normalized() * s2]
                prevB = C[3]
        hand_rot = A["RightHand"].to_3x3() @ rest["RightHand"].to_3x3().inverted()
        for k, (name, h, tl, par) in enumerate(FLAIL):
            Rb = rest[name]
            head = A[par] @ (rest[par].inverted() @ Rb.translation)
            d0h = hand_rot @ (tl - h).normalized(); d1 = (C[k + 1] - C[k]).normalized()
            A[name] = Matrix.Translation(head) @ (d0h.rotation_difference(d1).to_matrix() @ hand_rot @ Rb.to_3x3()).to_4x4()
            parent_of[name] = par

# ---------------------------------------------------------------- wings: spread from the DEF sprite's width
# The capture has no wings. A gargoyle's sprite widens almost only when its wings open, so the
# opaque width relative to idle frame 0 (normalised to the widest frame) sets how far each wing
# swings out about the body's front-back axis at its root.
if WINGS:
    wd = np.array(sj["widths"], float); w0 = wd[0]; wmax = max(wd.max(), w0 + 1)
    spread = np.clip((wd - w0) / (wmax - w0), 0, 1)
    for t in range(T):
        A = posed_world[t]
        for w in WINGS:
            n, par = w["bone"], w.get("parent", "Spine2")
            ang = math.radians(cfg.get("wingMaxDeg", 75.0)) * spread[t] * w["sign"]
            axis_l = rest[n].to_3x3().inverted() @ Vector((0, 1, 0))
            A[n] = A[par] @ rest[par].inverted() @ rest[n] @ Matrix.Rotation(ang, 4, axis_l)
            parent_of[n] = par
    print("WINGS spread per frame", [round(float(x), 2) for x in spread])

# ---------------------------------------------------------------- snake tail motion
# The capture has no tail. Each frame the chain follows a target curve: its first segments ride
# with the hips, the grounded coil stays where it lies, and in Move (half-way in MoveStart /
# MoveEnd) the coil beyond the ground contact uncoils into a trailing wave behind the body --
# the DEF naga stretches its tail out behind while it moves. The wave's phase makes exactly one
# cycle over the Move clip, so the loop closes. Bone lengths are fixed (follow-the-target FK).
TAILCFG = cfg.get("tail", {})
tail_alpha = [0.0] * T; tail_phase = [0.0] * T
if TAILB:
    for sg in json.load(open(MASTER))["segments"]:
        a_ = {"Move": 1.0, "MoveStart": 0.5, "MoveEnd": 0.5}.get(sg["contractSuffix"], 0.0)
        for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
            tail_alpha[t] = a_
            tail_phase[t] = 2 * math.pi * i / max(sg["frameCount"], 1)
    seglen = [(TPts[k + 1] - TPts[k]).length for k in range(len(TAILB))]
    gidx_ = next((k for k, p_ in enumerate(TPts) if p_.z < TAILCFG.get("groundZ", 0.18)), len(TPts) // 3)
    # "behind" is the model-space trail axis (the opposite of the body's facing, +Y for a -Y front), never the
    # sprite camera's screen-left: that is a 2D projection and trails the tail diagonally in game (naga, 2026-09-30).
    back = Vector(TAILCFG.get("behind", (0, 1, 0))).normalized(); side = back.cross(Vector((0, 0, 1))).normalized()

def solve_tail(t):
    A = posed_world[t]
    Hm = A["Hips"] @ rest["Hips"].inverted()
    tg = []
    for k, p_ in enumerate(TPts):
        w = min(1.0, k / max(gidx_, 1))
        tg.append((Hm @ p_).lerp(p_, w))
    al = tail_alpha[t]
    if al > 0:
        g0 = tg[gidx_]; sacc = 0.0
        amp, lam = TAILCFG.get("amplitude", 0.12), TAILCFG.get("wavelength", 0.9)
        for k in range(gidx_ + 1, len(TPts)):
            sacc += seglen[k - 1]
            env = min(1.0, sacc / 0.3)                       # the wave grows away from the body
            ext = g0 + back * sacc * 0.92 + side * (amp * env * math.sin(2 * math.pi * sacc / lam - tail_phase[t]))
            ext.z = g0.z
            tg[k] = tg[k].lerp(ext, al)
    head = Hm @ TPts[0]
    carry = Hm.to_3x3().normalized()          # twist is carried down the chain (parallel transport)
    for k, n in enumerate(TAILB):
        d = (tg[k + 1] - head).normalized()
        carry = (carry @ rest[n].to_3x3().col[1]).normalized().rotation_difference(d).to_matrix() @ carry
        R = carry @ rest[n].to_3x3()
        # opt-in tail.snapGrounded (radians): a grounded coil bone (target unmoved, no Move uncoil) whose solve lands
        # within this angle of its rest rotation is set exactly to rest, and the carried twist below it is reset.
        # The hips ride the first segments in Idle, which leaves ~1e-5 rad jitter down the resting coil; the glTF
        # exporter flattens such a channel to a constant and the round trip (verify_glb) then misses the jitter
        # summed over the bones below it (h3_naga_upg at 24 segments: 1.2e-4 at the tip, gate 1e-4).
        snap = TAILCFG.get("snapGrounded", 0)
        if snap and al == 0 and k >= gidx_ and (R @ rest[n].to_3x3().inverted()).to_quaternion().angle < snap:
            R = rest[n].to_3x3().copy(); carry = Matrix.Identity(3)
            d = rest[n].to_3x3().col[1].normalized()
        A[n] = Matrix.Translation(head) @ R.to_4x4()
        head = head + d * seglen[k]
        parent_of[n] = "Hips" if k == 0 else TAILB[k - 1]

if TAILB:
    for t in range(T):
        solve_tail(t)

# ---------------------------------------------------------------- silhouette fit against the DEF (non-humanoid units)
# The capture is a human skeleton; for a flying gargoyle, a floating genie or a lunging naga its
# hips and legs are guesses. Per frame, a small whole-body correction -- screen-plane offset
# (dx, dy), lean about the camera axis through the hips (roll) and extra wing spread -- is chosen
# to maximise silhouette IoU between the skinned mesh under the sprite camera and the DEF frame's
# opaque pixels, starting from the previous frame's answer and penalised toward zero.
REFINE = cfg.get("silhouetteRefine")
refine_log = []
if REFINE:
    PARAMS = REFINE.get("params", ["dx", "dy", "roll"])
    names_all = list(posed_world[0].keys())
    V0 = np.array([v.co[:] for v in body.data.vertices])
    Vh = np.c_[V0, np.ones(len(V0))]
    gname = {g.index: g.name for g in body.vertex_groups}
    Wm = np.zeros((len(V0), len(names_all)))
    col = {n: i for i, n in enumerate(names_all)}
    for v in body.data.vertices:
        for g in v.groups:
            n = gname[g.group]
            if n in col:
                Wm[v.index, col[n]] += g.weight
    Wm /= np.maximum(Wm.sum(1, keepdims=True), 1e-9)
    wing_rows = {w["bone"]: Wm[:, col[w["bone"]]] > 0.5 for w in WINGS}
    restinv = {n: np.array(rest[n].inverted()) for n in names_all}
    R_ = np.array(right); U_ = np.array(up); Fw = np.array(fwd_cam)

    def def_mask(path):
        img = bpy.data.images.load(path, check_existing=True)
        a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 0.99
        bpy.data.images.remove(img); return a

    def skin(A):
        out = np.zeros((len(V0), 3))
        for n, i in col.items():
            w = Wm[:, i]
            if w.max() <= 0:
                continue
            M = np.array(A[n]) @ restinv[n]
            out += w[:, None] * (Vh @ M.T)[:, :3]
        return out

    def splat(P):
        x = np.round(ox + s_px * (P @ R_)).astype(int); y = np.round(oy - s_px * (P @ U_)).astype(int)
        ok = (x >= 1) & (x < SW - 1) & (y >= 1) & (y < SH - 1)
        m = np.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
        g = m.copy()
        for dy_, dx_ in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            g |= np.roll(np.roll(m, dy_, 0), dx_, 1)
        return g

    def rot_about(axis, ang, pivot):
        Rm = np.array(Matrix.Rotation(ang, 3, Vector(axis)))
        return lambda P: (P - pivot) @ Rm.T + pivot

    ms_frames = json.load(open(MASTER))["frames"]
    # the refine's vertical is bounded where the ground gate judges the Hips (grounding.judged_hips_frames: each clip's
    # first frame, the gate's own allowance and exemptions): an IoU gain is no evidence the body left the floor there.
    # Unjudged frames stay free. A bound that moves dy by more than BOUND_REPORT_PX is reported (the unit then needs a
    # DEF | old | new strip before it freezes).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import grounding as GRD
    BOUND_REPORT_PX = 3.0

    def def_opaque(path):
        img = bpy.data.images.load(path, check_existing=True)
        a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 254.5 / 255
        bpy.data.images.remove(img); return a
    JUDGED, IDLE0 = {}, 0
    if "dy" in PARAMS:
        _curve = GRD.def_curve(json.load(open(MASTER)), def_opaque)
        JUDGED = GRD.judged_hips_frames(_curve, cfg)
        IDLE0 = GRD.canonical(_curve)["Idle"]["globalStart"]
        if JUDGED and min(JUDGED) < IDLE0:
            raise SystemExit(f"silhouetteRefine: judged frame {min(JUDGED)} precedes the Idle floor frame {IDLE0}; "
                             "the dy band needs Idle refined first")
        _v_idle = skin(posed_world[IDLE0])
        H_IDLE = float(_v_idle[:, 2].max() - _v_idle[:, 2].min())
    idle_hips_z = None
    bound_moves = []
    wing_pivots = {w["bone"]: None for w in WINGS}
    prev = {k: 0.0 for k in PARAMS}
    prev_aim = {}
    lam = REFINE.get("penalty", 0.0015)
    for t in range(T):
        A = posed_world[t]
        base = skin(A)
        target = def_mask(ms_frames[t]["sourcePng"])
        hips = np.array(A["Hips"].translation)
        wp = {w["bone"]: (np.array(A[w["bone"]].translation), np.array(A[w["bone"]].to_3x3() @ (rest[w["bone"]].to_3x3().inverted() @ Vector((0, 1, 0))))) for w in WINGS}
        def apply(p):
            P = base.copy()
            for w in WINGS:
                if "wing" in p and p["wing"]:
                    piv, ax = wp[w["bone"]]
                    rows = wing_rows[w["bone"]]
                    P[rows] = rot_about(ax, math.radians(p["wing"]) * w["sign"], piv)(P[rows])
            if p.get("roll"):
                P = rot_about(fwd_cam, math.radians(p["roll"]), hips)(P)
            return P + R_ * p.get("dx", 0.0) / s_px + U_ * p.get("dy", 0.0) / s_px
        def score(p):
            m = splat(apply(p)); inter = (m & target).sum(); uni = (m | target).sum()
            return inter / max(uni, 1) - lam * sum(abs(v) for v in p.values())
        steps = {"dx": [8, 4, 2, 1], "dy": [8, 4, 2, 1], "roll": [8, 4, 2, 1], "wing": [32, 12, 6, 2], "aim1": [24, 10, 4, 2], "aim2": [24, 10, 4, 2]}
        lim = REFINE.get("limits", {"dx": 40, "dy": 60, "roll": 45, "wing": 60})

        def search(band):
            clampb = lambda k, v: max(band[k][0], min(band[k][1], v))
            cur = {k: clampb(k, v) for k, v in prev.items()}; best = score(cur)
            for level in range(4):
                improved = True
                while improved:
                    improved = False
                    for k in PARAMS:
                        for sgn in (1, -1):
                            c = dict(cur); c[k] = clampb(k, c[k] + sgn * steps[k][level])
                            sc_ = score(c)
                            if sc_ > best + 1e-6:
                                best, cur, improved = sc_, c, True
            return cur, best
        free = {k: (-lim[k], lim[k]) for k in PARAMS}
        base_iou = score({k: 0.0 for k in PARAMS}) + 0
        cur, best = search(free)
        dy_band = None
        if t in JUDGED:
            lo_, hi_ = GRD.refine_dy_band(float(hips[2]), idle_hips_z, H_IDLE, JUDGED[t], float(U_[2]), s_px)
            dy_band = (max(-lim["dy"], lo_), min(lim["dy"], hi_))
            if dy_band[0] > dy_band[1]:
                raise SystemExit(f"silhouetteRefine frame {t}: the DEF-evidenced dy band [{lo_:.1f}, {hi_:.1f}] px lies "
                                 f"outside the dy limit {lim['dy']} (the pose's own Hips step exceeds the DEF's rows)")
            if not dy_band[0] - 1e-9 <= cur["dy"] <= dy_band[1] + 1e-9:
                dy_free = cur["dy"]
                cur, best = search({**free, "dy": dy_band})
                bound_moves.append({"frame": t, "dyFree": round(dy_free, 2), "dy": round(cur["dy"], 2),
                                    "movedPx": round(abs(cur["dy"] - dy_free), 2)})
        prev = cur
        refine_log.append({"frame": t, **{k: round(v, 2) for k, v in cur.items()}, "iouGain": round(best - base_iou, 3)})
        if dy_band is not None:
            refine_log[-1]["dyBand"] = [round(dy_band[0], 2), round(dy_band[1], 2)]
        if t == IDLE0 and "dy" in PARAMS:
            idle_hips_z = float(hips[2] + U_[2] * cur.get("dy", 0.0) / s_px)
        # bake the correction into the world poses
        Tm = Matrix.Translation(Vector(tuple(R_ * cur.get("dx", 0.0) / s_px + U_ * cur.get("dy", 0.0) / s_px)))
        if cur.get("roll"):
            hv = Vector(tuple(hips))
            Tm = Tm @ Matrix.Translation(hv) @ Matrix.Rotation(math.radians(cur["roll"]), 4, fwd_cam) @ Matrix.Translation(-hv)
        for n in names_all:
            if n != "Root" and n not in STATIC and n not in TAILB:
                A[n] = Tm @ A[n]
        for w in WINGS:
            if cur.get("wing"):
                n = w["bone"]
                axis_l = rest[n].to_3x3().inverted() @ Vector((0, 1, 0))
                A[n] = A[n] @ Matrix.Rotation(math.radians(cur["wing"]) * w["sign"], 4, axis_l)
        # held props: the capture has no wrist twist, so a staff or bolt keeps its hand-relative
        # angle. Search a swing about the camera axis and a tilt toward/away from it, about the
        # hand, for the prop bone's rigid vertices, maximising the same silhouette IoU.
        # propAimDepth "imagePlane" (opt-in): the tilt toward/away from the camera is not searched. A
        # silhouette cannot tell a prop tilted toward the camera from one tilted away, and a thin prop
        # hidden against the body by foreshortening scores about as well as a visible one that is a
        # few pixels off, so the free tilt picked +-40..75 deg with a sign that flipped frame to frame
        # (2026-09-30 troglodyte line: idle 53/51/53/-41, a 94 deg depth swing on the loop seam, read
        # in game as the spear flailing back and forth). Instead the prop's own axis is laid into the
        # sprite image plane (the DEF draws it at full length) and only the swing about the camera
        # axis is fitted. Evidence: the DEF shows only the projected direction; depth is assumed.
        DEPTH = REFINE.get("propAimDepth", "search")
        if DEPTH not in ("search", "imagePlane"):
            raise SystemExit(f"silhouetteRefine.propAimDepth {DEPTH!r}: expected 'search' or 'imagePlane'")
        for ab in REFINE.get("propAim", []):
            rows = Wm[:, col[ab]] > 0.99
            if not rows.any():
                continue
            A = posed_world[t]
            base2 = skin(A); piv = np.array(A[ab].translation)
            pdir = base2[rows].mean(0) - piv
            ax2 = np.cross(np.array(fwd_cam), pdir); ax2 /= max(np.linalg.norm(ax2), 1e-9)
            if DEPTH == "imagePlane":
                fw = np.array(fwd_cam) / np.linalg.norm(fwd_cam)
                Pr = base2[rows]
                paxis = np.linalg.svd(Pr - Pr.mean(0), full_matrices=False)[2][0]
                if paxis @ pdir < 0:
                    paxis = -paxis
                ax2 = np.cross(fw, paxis); ax2 /= max(np.linalg.norm(ax2), 1e-9)
                e = math.asin(max(-1.0, min(1.0, float(paxis @ fw))))
                lock = min((e, -e), key=lambda a: abs(float(rot_about(tuple(ax2), a, np.zeros(3))(paxis[None])[0] @ fw)))
                lock_deg = math.degrees(lock)
                if abs(float(rot_about(tuple(ax2), lock, np.zeros(3))(paxis[None])[0] @ fw)) > 1e-6:
                    raise SystemExit(f"propAimDepth imagePlane frame {t} {ab}: the lock left the prop out of the image plane")
                # propAimTilt (deg, opt-in, default 0 = the plain image-plane lock): tip the locked prop that far toward
                # the camera (camera at -fwd_cam). A blade held at the hip and laid into the image plane through the
                # hand runs inside the torso (2026-10-01 hota_cove_seaman idle: only the tip showed past the shoulder);
                # the DEF draws it across the front of the body.
                TILT = math.radians(float(REFINE.get("propAimTilt", 0.0)))
                if TILT:
                    lock = min((lock + TILT, lock - TILT),
                               key=lambda a: float(rot_about(tuple(ax2), a, np.zeros(3))(paxis[None])[0] @ fw))
                    lock_deg = math.degrees(lock)
                def rot_prop(q):
                    P2 = base2.copy()
                    P2[rows] = rot_about(fwd_cam, math.radians(q["aim1"]), piv)(rot_about(tuple(ax2), lock, piv)(P2[rows]))
                    return P2
                # The swing is bounded to propAimRange deg (default 100, as "search") about the capture's own
                # hand pose and pulled toward it: whole-body IoU of a thin prop is nearly flat, so a wide swing
                # chases the tip/butt mirror line and unexplained body pixels. (A +-30 deg/frame window against
                # the previous frame was tried and let the spear ratchet backwards through Hitted and stay
                # there: h3_troglodyte idle +172 on screen against the DEF's +100, 2026-09-30.)
                RANGE = float(REFINE.get("propAimRange", 100))
                vlock = rot_about(tuple(ax2), lock, np.zeros(3))(paxis[None])[0]
                def phi_of(a1):
                    w = rot_about(fwd_cam, math.radians(a1), np.zeros(3))(vlock[None])[0]
                    return math.degrees(math.atan2(float(w @ U_), float(w @ R_)))
                def allowed(a1):
                    return -RANGE - 1e-9 <= a1 <= RANGE + 1e-9
                def pscore(q):
                    m = splat(rot_prop(q)); inter = (m & target).sum(); uni = (m | target).sum()
                    return inter / max(uni, 1) - 0.0001 * abs(q["aim1"])
                grid = sorted({float(a1) for a1 in range(-180, 181, 2)} | {-RANGE, RANGE})
                cands = [{"aim1": a1} for a1 in grid if allowed(a1)]
                q = max(cands, key=pscore); qb = pscore(q)
                improved = True
                while improved:
                    improved = False
                    for sgn in (1, -1):
                        c = {"aim1": q["aim1"] + sgn * 1.0}
                        if allowed(c["aim1"]):
                            sc_ = pscore(c)
                            if sc_ > qb + 1e-6:
                                qb, q, improved = sc_, c, True
                prev_aim[ab] = {**q, "phi": phi_of(q["aim1"])}
                Rw = (Matrix.Translation(Vector(tuple(piv))) @ Matrix.Rotation(math.radians(q["aim1"]), 4, fwd_cam)
                      @ Matrix.Rotation(lock, 4, Vector(tuple(ax2))) @ Matrix.Translation(-Vector(tuple(piv))))
                A[ab] = Rw @ A[ab]
                refine_log[-1][ab] = {"aim1": round(q["aim1"], 1), "depthLock": round(lock_deg, 1),
                                      "screenDeg": round(prev_aim[ab]["phi"], 1)}
                continue
            def rot_prop(q):
                P2 = base2.copy()
                P2[rows] = rot_about(tuple(ax2), math.radians(q["aim2"]), piv)(rot_about(fwd_cam, math.radians(q["aim1"]), piv)(P2[rows]))
                return P2
            def pscore(q):
                m = splat(rot_prop(q)); inter = (m & target).sum(); uni = (m | target).sum()
                return inter / max(uni, 1) - 0.0001 * (abs(q["aim1"]) + abs(q["aim2"]))
            # a thin prop changes IoU only a little, and a swing to level can need 90 degrees:
            # scan the swing coarsely (plus the previous frame's answer), then refine
            cands = [dict(prev_aim.get(ab, {"aim1": 0.0, "aim2": 0.0}))]
            cands += [{"aim1": float(a1), "aim2": float(a2)} for a1 in range(-100, 101, 10) for a2 in (-45, 0, 45)]
            q = max(cands, key=pscore); qb = pscore(q)
            for level in range(4):
                improved = True
                while improved:
                    improved = False
                    for k in ("aim1", "aim2"):
                        for sgn in (1, -1):
                            c = dict(q); c[k] = max(-100, min(100, c[k] + sgn * steps[k][level])); sc_ = pscore(c)
                            if sc_ > qb + 1e-6:
                                qb, q, improved = sc_, c, True
            prev_aim[ab] = q
            Rw = (Matrix.Translation(Vector(tuple(piv))) @ Matrix.Rotation(math.radians(q["aim2"]), 4, Vector(tuple(ax2)))
                  @ Matrix.Rotation(math.radians(q["aim1"]), 4, fwd_cam) @ Matrix.Translation(-Vector(tuple(piv))))
            A[ab] = Rw @ A[ab]
            refine_log[-1][ab] = {k: round(v, 1) for k, v in q.items()}
    json.dump(refine_log, open(OUT + ".refine.json", "w"), indent=0)
    big = [m for m in bound_moves if m["movedPx"] > BOUND_REPORT_PX]
    json.dump({"judgedFrames": sorted(JUDGED), "moves": bound_moves, "reportPx": BOUND_REPORT_PX,
               "movedOverReport": [m["frame"] for m in big]}, open(OUT + ".refine_bound.json", "w"), indent=1)
    print("REFINE DY BOUND", len(bound_moves), "judged frame(s) bounded" + (
          f"; MOVED > {BOUND_REPORT_PX:g} px at frames {[m['frame'] for m in big]}: needs a DEF | old | new strip "
          "before it freezes" if big else ""))
    for t in range(T):
        if TAILB:
            solve_tail(t)
    print("REFINE mean IoU gain", round(float(np.mean([r["iouGain"] for r in refine_log])), 3))

# ---------------------------------------------------------------- death transformations the DEF shows
# Skinning cannot turn a body into rubble or a lamp, so two explicit stages follow the DEF:
#   shrinkOut (genies): from a local death frame the whole body scales down into a point on the
#     ground where the DEF's genie vanishes into its lamp (the lamp/sparkle itself is an effect);
#   shatter (golems, gargoyles): a hidden duplicate of the mesh is cut into k-means chunks, each
#     on its own bone. At the break frame every chunk takes the rigid pose that best fits its part
#     of the deformed body (Kabsch), the body collapses to nothing, and the chunks fall under
#     gravity with a burst, spin and ground bounce. Every other frame keys the rubble at ~0 scale.
#     "solid": true (opt-in) caps each chunk's open rim so the pieces read as solid stone, not skin shells.
#     "keepWhole": [{"segment": [[x,y,z], [x,y,z]], "radius": r}] (opt-in, Blender rest axes) gives every
#     vertex / face within r of each segment its own extra chunk, so a long thin prop (a staff whose shaft
#     is a few full-length quads) breaks as one rigid piece instead of full-length slivers spread over
#     the k-means cells (bonePile standProp then stands that piece in the heap).
RUBBLE_BONES = []
death = max((x for x in json.load(open(MASTER))["segments"] if x["contractSuffix"] == "Death"),
            key=lambda x: x["frameCount"], default=None)
SHR, SHT = cfg.get("shrinkOut"), cfg.get("shatter")
TINY = Matrix.Diagonal((1e-4, 1e-4, 1e-4, 1.0))

def about(pt, M4):
    return Matrix.Translation(pt) @ M4 @ Matrix.Translation(-pt)

def body_bones(A):
    return [n for n in A if n != "Root" and n not in STATIC and n not in RUBBLE_BONES]

if death and SHR:
    d0, d1 = death["globalStart"], death["globalEnd"]
    a = d0 + SHR["start"]
    tgt = Vector(SHR.get("target", (J["Hips"][0], J["Hips"][1], 0.0)))
    for t in range(a, d1):
        f = (t - a + 1) / (d1 - a)
        k_ = max(1e-3, (1 - f) ** SHR.get("power", 1.5))
        M = about(tgt, Matrix.Diagonal((k_, k_, k_, 1.0)))
        for n in body_bones(posed_world[t]):
            posed_world[t][n] = M @ posed_world[t][n]
    print("SHRINK from death frame", SHR["start"])

if death and SHT:
    d0, d1 = death["globalStart"], death["globalEnd"]; ts = d0 + SHT["start"]
    K = SHT.get("chunks", 40)
    BP = np.array([v.co[:] for v in body.data.vertices])
    rs = np.random.default_rng(SHT.get("seed", 7))
    Cc = BP[rs.choice(len(BP), K, replace=False)]
    for _ in range(15):
        lab = np.argmin(((BP[:, None, :] - Cc[None]) ** 2).sum(-1), 1)
        Cc = np.array([BP[lab == k].mean(0) if (lab == k).any() else Cc[k] for k in range(K)])
    keep = []
    for kw in SHT.get("keepWhole", []):
        sa, sb = np.array(kw["segment"][0], float), np.array(kw["segment"][1], float)
        near = lambda P, sa=sa, sb=sb, r=kw.get("radius", 0.07): np.linalg.norm(
            P - (sa + np.clip(((P - sa) @ (sb - sa)) / ((sb - sa) @ (sb - sa)), 0, 1)[:, None] * (sb - sa)), axis=1) < r
        m = near(BP)
        if m.any():
            lab[m] = K; Cc = np.vstack([Cc, BP[m].mean(0)]); keep.append((near, K)); K += 1
            print("SHATTER keepWhole", int(m.sum()), "verts -> chunk", K - 1)
    if keep:
        # a k-means cell whose every vertex went to a keepWhole piece would get a NaN pose (no verts to fit):
        # drop it, so its faces fall to the next-nearest cell
        nk0 = K - len(keep)
        used = [k for k in range(nk0) if (lab == k).any()]
        if len(used) < nk0:
            order = used + [kk for _, kk in keep]
            remap = np.full(K, -1); remap[order] = np.arange(len(order))
            lab = remap[lab]; Cc = Cc[order]; keep = [(near, int(remap[kk])) for near, kk in keep]
            print("SHATTER keepWhole dropped", nk0 - len(used), "emptied chunks")
            K = len(order)
    # rubble mesh: a copy of the body cut along chunk boundaries, one bone per chunk
    rub = body.copy(); rub.data = body.data.copy(); rub.name = cfg["unit"] + "_Rubble"
    bpy.context.scene.collection.objects.link(rub)
    for m in list(rub.modifiers):
        rub.modifiers.remove(m)
    rub.vertex_groups.clear()
    CH = [f"Chunk_{k:02d}" for k in range(K)]
    for n in CH:
        rub.vertex_groups.new(name=n)
    bm2 = bmesh.new(); bm2.from_mesh(rub.data)
    def fch(f):
        c = np.array(f.calc_center_median()[:])
        for near, kk in keep:
            if near(c[None])[0]:
                return kk
        return int(np.argmin(((Cc[:K - len(keep)] - c) ** 2).sum(1)))
    fc = {f.index: fch(f) for f in bm2.faces}
    bmesh.ops.split_edges(bm2, edges=[e for e in bm2.edges if len({fc[f.index] for f in e.link_faces}) > 1])
    bm2.faces.ensure_lookup_table()
    caps = set()
    if SHT.get("solid"):
        # opt-in: close every chunk's open rim with a cap so the pieces read as solid stone, not hollow skin
        # shells; cap UVs take the mean UV of the rim vertex's own faces (a smear of the chunk's surface colour)
        caps = set(bmesh.ops.holes_fill(bm2, edges=[e for e in bm2.edges if e.is_boundary], sides=0)["faces"])
        for lay in bm2.loops.layers.uv.values():
            for f in caps:
                for lp in f.loops:
                    us = [ll[lay].uv.copy() for ll in lp.vert.link_loops if ll.face not in caps]
                    if us:
                        lp[lay].uv = sum(us, Vector((0.0, 0.0))) / len(us)
        bm2.faces.ensure_lookup_table()
    dl2 = bm2.verts.layers.deform.verify()
    for f in bm2.faces:
        if f in caps:
            continue   # rim verts are already weighted by their chunk's own faces
        k = fch(f)
        for v in f.verts:
            d = v[dl2]; d.clear(); d[k] = 1.0
    bm2.to_mesh(rub.data); bm2.free()
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    rr = eb.new("RubbleRoot"); rr.head, rr.tail = Vector((0, 0, 0)), Vector((0, 0, 0.05)); rr.parent = eb["Root"]
    for k, n in enumerate(CH):
        b = eb.new(n); b.head = Vector(Cc[k]); b.tail = Vector(Cc[k]) + Vector((0, 0, 0.05)); b.parent = rr
    bpy.ops.object.mode_set(mode='OBJECT')
    RUBBLE_BONES = ["RubbleRoot"] + CH
    for n in RUBBLE_BONES:
        rest[n] = rig.data.bones[n].matrix_local.copy()
        parent_of[n] = "Root" if n == "RubbleRoot" else "RubbleRoot"
    rub.parent = rig
    rmod = rub.modifiers.new("Armature", 'ARMATURE'); rmod.object = rig

    # skin the body at the break frame to start each chunk where its flesh is
    gname = {g.index: g.name for g in body.vertex_groups}
    A0 = posed_world[ts]
    Ysk = np.zeros_like(BP); wsum = np.zeros(len(BP))
    mats = {n: np.array(A0[n] @ rest[n].inverted()) for n in A0}
    for v in body.data.vertices:
        for g in v.groups:
            n = gname[g.group]
            if n in mats and g.weight > 0:
                Ysk[v.index] += g.weight * (mats[n] @ np.r_[BP[v.index], 1.0])[:3]; wsum[v.index] += g.weight
    Ysk /= np.maximum(wsum, 1e-9)[:, None]
    centre = Ysk.mean(0)
    burst, up_, spin = SHT.get("burst", 1.0), SHT.get("up", 1.0), SHT.get("spin", 6.0)
    chunks = []
    for k in range(K):
        X = BP[lab == k]; Y = Ysk[lab == k]
        cx, cy = X.mean(0), Y.mean(0)
        U_, _, Vt = np.linalg.svd((X - cx).T @ (Y - cy))
        Rk = Vt.T @ U_.T
        if np.linalg.det(Rk) < 0:
            Vt[-1] *= -1; Rk = Vt.T @ U_.T
        out = cy - centre; out[2] = 0; out /= max(np.linalg.norm(out), 1e-6)
        vel = out * burst * (0.4 + 0.8 * rs.random()) + np.array([0, 0, up_ * rs.random()])
        chunks.append({"c": cx, "p": cy.copy(), "R": Matrix(Rk.tolist()), "v": vel,
                       "w": (rs.random(3) - 0.5) * 2 * spin, "r": float(np.linalg.norm(X - cx, axis=1).mean())})
    hips_ts = A0["Hips"].translation.copy()
    for t in range(T):
        A = posed_world[t]
        live = ts <= t < d1
        A["RubbleRoot"] = rest["RubbleRoot"].copy() if live else rest["RubbleRoot"] @ TINY
        if not live:
            for n in CH:
                A[n] = A["RubbleRoot"] @ rest["RubbleRoot"].inverted() @ rest[n]
            continue
        if t > ts:
            h = 1.0 / (12 * 8)
            for _ in range(8):
                for c in chunks:
                    c["v"][2] -= 9.8 * h; c["p"] += c["v"] * h
                    wn = float(np.linalg.norm(c["w"]))
                    if wn > 1e-6:
                        c["R"] = Matrix.Rotation(wn * h, 3, Vector(tuple(c["w"] / wn))) @ c["R"]
                    floor = c["r"] * 0.6
                    if c["p"][2] < floor:
                        c["p"][2] = floor; c["v"][2] = -c["v"][2] * 0.25; c["v"][:2] *= 0.6; c["w"] *= 0.6
        for k, c in enumerate(chunks):
            M = Matrix.Translation(Vector(tuple(c["p"]))) @ c["R"].to_4x4() @ Matrix.Translation(-Vector(tuple(c["c"])))
            A[CH[k]] = M @ rest[CH[k]]
        hide = about(hips_ts, TINY)
        for n in body_bones(A):
            A[n] = hide @ A[n]
    print("SHATTER", K, "chunks from death frame", SHT["start"])

run_hooks("before_keys")

# ---------------------------------------------------------------- local pose per frame, then actions
keyed = bone_names + [f[0] for f in FLAIL] + [w["bone"] for w in WINGS] + TAILB + RUBBLE_BONES
FREE = {"Hips"} | set(RUBBLE_BONES)
def local_pose(A, name):
    Rb = rest[name]; par = parent_of[name]
    basis = (rest[par].inverted() @ Rb).inverted() @ A[par].inverted() @ A[name]
    return basis.decompose()
POSE = [{n: local_pose(posed_world[t], n) for n in keyed} for t in range(T)]

def write_action(name, frames):
    """frames: list of {bone: (loc, quat)}; keys at scene frames 1..len(frames)."""
    act = bpy.data.actions.new(name)
    rig.animation_data.action = act
    prev = {}
    for i, fr in enumerate(frames):
        for n in keyed:
            loc, q, sc = fr[n]
            if n in prev and prev[n].dot(q) < 0:
                q = -q                                  # keep quaternion keys on one hemisphere
            prev[n] = q
            pb = rig.pose.bones[n]
            pb.rotation_quaternion = q; pb.keyframe_insert("rotation_quaternion", frame=i + 1)
            if n in FREE:
                pb.location = loc; pb.keyframe_insert("location", frame=i + 1)
                pb.scale = sc; pb.keyframe_insert("scale", frame=i + 1)
    act.use_fake_user = True
    return act

def pose_dist(a, b):
    """Largest bone-head displacement between two frames' world poses (scene units)."""
    return max((a[n].translation - b[n].translation).length for n in bone_names)

rig.animation_data_create()
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='POSE')
for pb in rig.pose.bones:
    pb.rotation_mode = 'QUATERNION'

ms = json.load(open(MASTER))
clips = {}
for s in ms["segments"]:
    n = "Unit_" + s["contractSuffix"]
    if n not in clips or s["frameCount"] > clips[n]["frameCount"]:
        clips[n] = s
loop_report = {}
for n, s in sorted(clips.items(), key=lambda kv: kv[1]["globalStart"]):
    rng = list(range(s["globalStart"], s["globalEnd"]))
    frames = [POSE[t] for t in rng]
    world = [posed_world[t] for t in rng]
    if n in borrowed:
        world = borrowed[n]
        frames = [{b: local_pose(A, b) for b in keyed if b in A} for A in world]
        for fr in frames:           # bones the donor does not drive (props, rubble) keep frame 0
            for b in keyed:
                fr.setdefault(b, POSE[rng[0]][b])
    if s["contractSuffix"] in LOOPS and len(frames) > 1:
        steps = [pose_dist(a, b) for a, b in zip(world, world[1:])]
        typical = max(float(np.median(steps)), 1e-4)
        seam = pose_dist(world[-1], world[0])
        extra = int(min(3, max(0, round(seam / typical) - 1)))
        last, first = frames[-1], frames[0]
        for k in range(1, extra + 1):     # transition keys easing the seam back to frame 0
            f = k / (extra + 1)
            frames.append({b: (last[b][0].lerp(first[b][0], f), last[b][1].slerp(first[b][1], f), last[b][2].lerp(first[b][2], f)) for b in keyed})
        frames.append(first)                # closing key == first pose: the wrap interpolates
        loop_report[n] = {"frames": len(world), "seamOverTypicalStep": round(seam / typical, 2), "transitionKeys": extra}
    write_action(n, frames)
master = write_action(cfg["unit"] + "_DEF_Master", POSE)
rig.animation_data.action = master
bpy.ops.object.mode_set(mode='OBJECT')
print("LOOPS", json.dumps(loop_report))
scene.render.fps = 12
scene.frame_start, scene.frame_end = 1, T
for sgm in ms['segments']:
    scene.timeline_markers.new(sgm['clipKey'], frame=sgm['globalStart'] + 1)
json.dump({"segments": [(s['clipKey'], s['globalStart'], s['globalEnd']) for s in ms['segments']],
           "sources": [f['sourcePng'] for f in ms['frames']], "loops": loop_report},
          open(OUT + ".frames.json", "w"))
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED", OUT)
# corrective smooth baked into per-frame morph targets (removes cloth tearing); the unit config
# "correctiveSmooth": false disables it, or {"iterations": n, "factor": f} tunes it
_csc = cfg.get("correctiveSmooth", {})
if _csc is not False:
    _bcs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bake_cs.py")
    _g = {"__name__": "bake_cs", "__file__": _bcs, "CS_ITER": _csc.get("iterations", 30), "CS_FACT": _csc.get("factor", 0.7),
          "CS_EXCLUDE": _csc.get("excludeBones", [])}
    exec(open(_bcs).read(), _g)
