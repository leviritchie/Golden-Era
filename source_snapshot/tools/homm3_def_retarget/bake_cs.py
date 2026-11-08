"""Bake Corrective Smooth into per-frame shape keys (glTF morph targets) for every action.

Usage: blender -b <unit_def_retarget.blend> -P bake_cs.py -- [iterations=30] [factor=0.7]
(build_unit.py runs this automatically unless the unit config sets "correctiveSmooth": false; emphasis
bl_deliver.py runs it on its work copy.)

Skinning alone shreds fused Meshy cloth in large poses. Corrective Smooth removes that, but modifiers do not
export. For each key of each action, the skinned mesh S and its corrective-smoothed mesh C are evaluated; the
rest-space offset d with Mblend @ d = C - S (Mblend = the vertex's weight-blended bone rotation) is exact for linear
blend skinning, so a morph target d, applied before skinning, reproduces C. Each key becomes one shape key, keyed at
weight 1 on its own frame and 0 on the frames either side, in a KEY slot of the same action, so the glTF exporter
writes it as that clip's morph-weight channel. Saves the .blend in place.

S, C and d are computed in float64 by tools/homm3_glb_patch/cs_numpy.py (the port of Blender 5.2's
MOD_correctivesmooth.cc on the same welded proxy, with its degenerate-corner rule and the harmonic fill of
undefined groups); Blender supplies only the rest
mesh, the weights and the pose bone matrices. Blender's own CORRECTIVE_SMOOTH modifier is not used: its float32
corner frames are rounding noise on the thin parts thirty iterations collapse (docs/homm3_cs_bake_float64.md).
The bake record (cs_numpy.BAKE_STAMP, schema cs_numpy.BAKE_SCHEMA) is kept on the scene; export_glb.py writes it into
the GLB's asset.extras, and tools/validate_homm3_cs_bake_contract.py checks it.
"""
import bpy, sys, os, json
import numpy as np

EXCLUDE = []
if "CS_ITER" in globals():          # exec'd from build_unit.py / bl_deliver.py
    ITER, FACT = CS_ITER, CS_FACT
    EXCLUDE = sorted(globals().get("CS_EXCLUDE") or [])
else:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ITER = int(argv[0]) if len(argv) > 0 else 30
    FACT = float(argv[1]) if len(argv) > 1 else 0.7
    # third CLI arg: correctiveSmooth.excludeBones, comma-separated (fleet_rebuild direct_rebake; before 2026-10-08
    # that route dropped the list and re-baked an excluding unit without it)
    EXCLUDE = sorted(b for b in (argv[2].split(",") if len(argv) > 2 else []) if b)
if "__file__" not in globals():
    raise RuntimeError("bake_cs.py needs __file__ (exec it with {'__file__': <path to bake_cs.py>}) to find cs_numpy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "homm3_glb_patch"))
import importlib  # noqa: E402
import cs_numpy as CSN  # noqa: E402
CSN = importlib.reload(CSN)         # a long-lived Blender session (bl_deliver) must not keep an older module

rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
ob = next(o for o in bpy.data.objects if o.type == 'MESH' and o.parent is rig and not o.name.endswith("_Rubble"))
if ob.data.shape_keys:
    ob.shape_key_clear()
sc = bpy.context.scene
n = len(ob.data.vertices)
REST = np.array([v.co[:] for v in ob.data.vertices], dtype=np.float64)

# the glTF exporter's influence limit first (influence_limit.py): the bake must skin with the weights that ship, not
# the 5+ influences an after_skin hook can leave behind (no-op for vertices with <= 4)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import influence_limit  # noqa: E402
influence_limit = importlib.reload(influence_limit)
influence_limited = influence_limit.apply_to_mesh(ob, [b.name for b in rig.data.bones])

# normalised deform weights (vertex x bone)
bnames = [b.name for b in rig.data.bones if b.use_deform]
col = {nm: i for i, nm in enumerate(bnames)}
gname = {g.index: g.name for g in ob.vertex_groups}
Wt = np.zeros((n, len(bnames)))
for v in ob.data.vertices:
    for g in v.groups:
        nm = gname[g.group]
        if nm in col:
            Wt[v.index, col[nm]] += g.weight
Wt /= np.maximum(Wt.sum(1, keepdims=True), 1e-9)
to_local = ob.matrix_world.inverted() @ rig.matrix_world
to_local_inv = to_local.inverted()

# Meshy splits the surface into many UV islands; Corrective Smooth smooths each island on its own,
# so the duplicate vertices along every UV seam drift apart and open cracks. Vertices sharing a
# rest position and identical weights skin identically, so their offsets are averaged per group,
# and Corrective Smooth runs on the welded proxy (one vertex per group), so smoothing crosses UV
# seams like the continuous surface it is; results map back to every duplicate.
_gk = {}
GID = np.empty(n, dtype=np.int64)
for i in range(n):
    k = (tuple(np.round(REST[i], 5)), tuple(np.round(Wt[i], 3)))
    GID[i] = _gk.setdefault(k, len(_gk))
weld = CSN.Weld.from_groups(GID, [list(p.vertices) for p in ob.data.polygons], REST)
cache = weld.rest_deltas(REST[weld.rep], ITER, FACT)
# correctiveSmooth.excludeBones (opt-in): the corrective displacement is scaled by 1 - the vertex's weight on them
# (cs_numpy.Weld.set_exclusion); patch_glb / cs_rekey_glb read the list back from the bake record
_unknown = [b for b in EXCLUDE if b not in col]
if _unknown:
    raise RuntimeError(f"bake_cs: correctiveSmooth.excludeBones names no deform bone: {_unknown}")
weld.set_exclusion(Wt[:, [col[b] for b in EXCLUDE]].sum(1)[weld.rep] if EXCLUDE else None)
rest_C = weld.corrective(REST[weld.rep], cache)
rest_round_trip = float(np.abs(rest_C - REST[weld.rep]).max()) / weld.scale
rest_skin_only, rest_invalid = int(weld.last_skin_only.sum()), int((~weld.rest_valid).sum())
if rest_round_trip > 1e-9:
    raise RuntimeError(f"bake_cs: Corrective Smooth at the rest pose moved the rest mesh by {rest_round_trip:.3g} x "
                       "body scale; the float64 bake must return rest at rest")


def bone_mats():
    """Per deform bone, the 4x4 deform matrix in the mesh object's local space (float64)."""
    M = np.zeros((len(bnames), 4, 4))
    for nm, i in col.items():
        pb = rig.pose.bones[nm]
        M[i] = np.array(to_local @ pb.matrix @ pb.bone.matrix_local.inverted() @ to_local_inv)
    return M


def use_action(act):
    ad = rig.animation_data; ad.action = act
    if act.slots:
        ad.action_slot = next(s for s in act.slots if s.target_id_type == 'OBJECT')


actions = [a for a in bpy.data.actions if a.name.startswith("Unit_") or a.name.endswith("_DEF_Master")]
plan = []   # (action, frame, delta)
worst = {}
skin_only_samples, unfilled_samples, invalid_corner_samples, frames_evaluated = 0, 0, 0, 0
CHUNK = 32
for act in actions:
    use_action(act)
    f0, f1 = int(round(act.frame_range[0])), int(round(act.frame_range[1]))
    frames = list(range(f0, f1 + 1))
    for c0 in range(0, len(frames), CHUNK):
        block = []
        for f in frames[c0:c0 + CHUNK]:
            sc.frame_set(f)
            block.append((f, CSN.skin_dense(REST, Wt, bone_mats())))
        X = weld.smooth(np.stack([s[0][weld.rep] for _, s in block], 1), ITER, FACT)
        for k, (f, (S, Mb, scale)) in enumerate(block):
            C = weld.corrective(S[weld.rep], cache, X[:, k])
            frames_evaluated += 1
            skin_only_samples += int(weld.last_skin_only.sum())
            unfilled_samples += weld.last_unfilled
            invalid_corner_samples += weld.last_invalid_corners
            mx = float(np.abs((C - S[weld.rep])[GID]).max())
            worst[act.name] = max(worst.get(act.name, 0), mx)
            if mx < 1e-4:
                continue
            # bodies hidden at ~0 scale have singular blended frames and scaled-down bodies (shrinkOut deaths,
            # teleports) would be re-inflated by Corrective Smooth: CSN.solve leaves vertices whose bones are scaled
            # below 0.9 alone, and its Tikhonov floor (CS_SIGMA_MIN) bounds near-singular blends (see cs_numpy.solve)
            plan.append((act, f, CSN.solve(GID, weld.rep, S, Mb, scale, C)))

bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
basis = ob.shape_key_add(name="Basis", from_mix=False)
key = ob.data.shape_keys
key.use_relative = True
key.animation_data_create()
kbs = []
for act, f, d in plan:
    kb = ob.shape_key_add(name=f"CS_{act.name}_{f:03d}", from_mix=False)
    kb.data.foreach_set("co", (REST + d).astype(np.float32).ravel())
    kb.value = 0.0
    kbs.append((act, f, kb))
import cs_weight_keys  # noqa: E402
cs_weight_keys = importlib.reload(cs_weight_keys)
for act in actions:
    mine = [(f, kb) for a, f, kb in kbs if a is act]
    f0, f1 = int(round(act.frame_range[0])), int(round(act.frame_range[1]))
    # a clip with no shape of its own still gets an all-zero weight channel (cs_weight_keys: the bundle probe reads
    # every clip's weight track; 2026-10-12 h3_sacred_phoenix Move had none)
    wk = cs_weight_keys.weight_keys(f0, f1, mine, kbs[0][2] if kbs else None)
    if not wk:
        continue
    slot = next((s for s in act.slots if s.target_id_type == 'KEY'), None) or act.slots.new(id_type='KEY', name=key.name)
    key.animation_data.action = act; key.animation_data.action_slot = slot
    for kb, ff, val in wk:
        kb.value = val; kb.keyframe_insert("value", frame=ff)
    for _, _, kb in kbs:
        kb.value = 0.0
    for fc in act.fcurves if hasattr(act, "fcurves") else []:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
# leave the master reel on both rig and key so renders show the corrected mesh
master = next((a for a in actions if a.name.endswith("_DEF_Master")), None)
if master:
    use_action(master)
    ks = next((s for s in master.slots if s.target_id_type == 'KEY'), None)
    if ks:
        key.animation_data.action = master; key.animation_data.action_slot = ks
record = {"schema": CSN.BAKE_SCHEMA, "rule": CSN.rule(), "iterations": ITER, "factor": FACT,
          **({"excludeBones": EXCLUDE} if EXCLUDE else {}),
          "influenceLimit": {"limit": influence_limit.LIMIT, "verticesLimited": influence_limited},
          "weldGroups": weld.ng, "vertices": n, "framesEvaluated": frames_evaluated, "shapeKeys": len(kbs),
          "restRoundTripOverScale": rest_round_trip, "restInvalidCorners": rest_invalid,
          "restSkinOnlyGroups": rest_skin_only, "skinOnlyGroupSamples": skin_only_samples,
          "unfilledGroupSamples": unfilled_samples,
          "invalidCornerSamples": invalid_corner_samples,
          "worstCorrectiveOffset": {k: round(v, 5) for k, v in worst.items()}}
sc[CSN.BAKE_STAMP] = json.dumps(record, sort_keys=True)
print("BAKE_CS float64 shape keys", len(kbs), "influence-limited vertices", influence_limited, "rest round trip", f"{rest_round_trip:.2e}", "skin-only group samples",
      skin_only_samples, "worst corrective offset per action", {k: round(v, 4) for k, v in worst.items()})
bpy.ops.wm.save_mainfile()
