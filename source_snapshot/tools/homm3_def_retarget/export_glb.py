"""Export a built unit to GLB: textured skinned mesh, rig, and one animation per DEF clip.

Usage: blender -b <unit_def_retarget.blend> -P export_glb.py -- <out.glb>

build_unit.py writes one action per clip (Unit_Idle, Unit_AttackFront, Unit_ShootFront, ...)
plus <unit>_DEF_Master (the whole reel). A clip the unit config's "skipDefGroups" names is not exported
(skip_def_groups.py). Keys are one per DEF frame at 12 fps. Loop clips
(Idle, Move) end with a closing key equal to their first pose, preceded by transition keys
where the capture's seam was large, so looping at clip length wraps smoothly.

If bake_cs.py has run, each action also has a KEY slot animating corrective-smooth morph
targets. Every action is laid out as a same-named NLA track on the rig (OBJECT slot) and on the
shape keys (KEY slot); the exporter merges same-named tracks into one glTF animation, so each
clip carries its own bone and morph-weight channels.
"""
import bpy, sys

OUT = sys.argv[sys.argv.index("--") + 1]
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.parent is rig]   # body (+ rubble)
key = next((m.data.shape_keys for m in meshes if m.data.shape_keys), None)
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skip_def_groups  # noqa: E402

actions = [a for a in bpy.data.actions if a.name.startswith("Unit_") or a.name.endswith("_DEF_Master")]
# unit config "skipDefGroups": a shoot clip the unit never plays is not shipped (skip_def_groups.py)
SKIPPED = skip_def_groups.skipped_clips(skip_def_groups.unit_of_blend_actions(a.name for a in bpy.data.actions))
actions = [a for a in actions if a.name not in SKIPPED]

def lay_out(idb, kind):
    ad = idb.animation_data or idb.animation_data_create()
    for t in list(ad.nla_tracks):
        ad.nla_tracks.remove(t)
    for act in actions:
        slot = next((s for s in act.slots if s.target_id_type == kind), None)
        if slot is None:
            continue
        tr = ad.nla_tracks.new(); tr.name = act.name
        st = tr.strips.new(act.name, int(round(act.frame_range[0])), act)
        st.action_slot = slot
        st.name = act.name
    ad.action = None

lay_out(rig, 'OBJECT')
if key:
    lay_out(key, 'KEY')
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.context.scene.render.fps = 12
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True,
                          export_animations=True, export_animation_mode='NLA_TRACKS',
                          export_force_sampling=True, export_skins=True, export_def_bones=False,
                          export_apply=False, export_yup=True, export_materials='EXPORT',
                          export_morph=True, export_morph_normal=False, export_morph_tangent=False,
                          export_try_sparse_sk=False, export_morph_animation=True)
# dense morph targets (export_try_sparse_sk=False, 2026-09-30): the float64 CS bake (bake_cs.py) leaves exact zeros on
# rigid parts, where Blender's float32 modifier left noise, so the exporter would switch most targets to sparse
# accessors; the numpy delivery stages and the patch lane read and rewrite dense targets in place
# a skin must have one top joint: the glTF exporter adds a second, neutral_bone, for vertices with no weight, and
# those vertices then stand still while the body moves (2026-09-28 h3_leprechaun: 243 chest vertices)
import json as _json, struct as _struct  # noqa: E401
with open(OUT, "rb") as _fh:
    _fh.read(12)
    _jl = _struct.unpack("<I", _fh.read(4))[0]
    _fh.read(4)
    _js = _json.loads(_fh.read(_jl))
_par = {c: i for i, n in enumerate(_js["nodes"]) for c in n.get("children", [])}
for _sk in _js.get("skins", []):
    _jt = set(_sk["joints"])
    _tops = sorted(_js["nodes"][j].get("name", str(j)) for j in _jt if _par.get(j) not in _jt)
    if len(_tops) != 1:
        raise RuntimeError(f"exported skin has top joints {_tops}, expected one (neutral_bone = unweighted "
                           f"vertices: fix the weights, surface_weights.py); {OUT}")
# source-mesh provenance (source_mesh.py): build_unit.py saved it on the scene. A .blend built before it has none and
# exports unstamped; freeze_slice admits such a GLB only through source_mesh_legacy.json.
import source_mesh  # noqa: E402
_src = bpy.context.scene.get(source_mesh.SCENE_PROP)
if _src:
    source_mesh.write_glb_stamp(OUT, _json.loads(_src))
print("SOURCE_MESH", _json.loads(_src)["sha256"] if _src else "unstamped (built before the source-mesh stamp)")
# Corrective Smooth bake record (bake_cs.py, cs_numpy.BAKE_STAMP): the float64 bake keeps it on the scene; a .blend whose
# shape keys were baked before it (Blender's float32 modifier) exports unstamped, and
# tools/validate_homm3_cs_bake_contract.py admits such a GLB only through tools/homm3_def_retarget/cs_bake_legacy.json
_CS_STAMP = "homm3DefRetargetCsBake"
_cs = bpy.context.scene.get(_CS_STAMP)
if _cs:
    source_mesh.write_glb_extras(OUT, _CS_STAMP, _json.loads(_cs))
print("CS_BAKE", _json.loads(_cs)["schema"] if _cs else ("unstamped legacy bake" if key else "no corrective shape keys"))
print("EXPORTED", OUT, sorted(a.name for a in actions), *(["skipDefGroups:", sorted(SKIPPED)] if SKIPPED else []))
