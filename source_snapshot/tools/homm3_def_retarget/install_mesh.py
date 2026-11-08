"""Install a unit's mesh for the DEF retarget from another delivery file.

Usage: blender -b --factory-startup -P tools/homm3_def_retarget/install_mesh.py -- <unit> <source.glb> [--force]

Most units' Meshy meshes are in artifacts/meshy_downloads/<unit>_smartrigged.glb. Some exist only
inside earlier delivery files (e.g. artifacts/homm3_mocap_v2/remaining_idle0_ingame_v1/units/<unit>/
<unit>_master.glb, or the Unity lab's OwnedSkinned/Source/master.glb) as a skinned copy. This takes
the largest textured mesh from <source.glb>, drops its armature so it sits in its rest (bind) pose,
applies transforms, stands it on z=0 centred in x/y, and writes a static textured GLB to
artifacts/meshy_downloads/<unit>_smartrigged.glb. It refuses to overwrite an existing file unless
--force, and writes <unit>_smartrigged.provenance.json next to it.
"""
import bpy, sys, os, json, hashlib
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
unit, src = argv[0], argv[1]; force = "--force" in argv
ROOT = r"V:/games/Olden Era Playtest Tweak"
dst = os.path.join(ROOT, "artifacts/meshy_downloads", f"{unit}_smartrigged.glb")
if os.path.exists(dst) and not force:
    sys.exit(f"{dst} exists; use --force")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.data.materials and len(o.data.vertices) > 100]
body = max(meshes, key=lambda o: len(o.data.vertices))
# evaluate at the skeleton's REST pose with the armature applied: rigid-part deliveries store
# their parts relative to bones, so simply dropping the armature can scatter them
for a in bpy.data.objects:
    if a.type == 'ARMATURE':
        a.data.pose_position = 'REST'
if body.data.shape_keys:
    body.shape_key_clear()
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
baked = bpy.data.meshes.new_from_object(body.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
mw = body.matrix_world.copy()
body.data = baked
for m in list(body.modifiers):
    body.modifiers.remove(m)
body.parent = None; body.matrix_world = mw
for o in list(bpy.data.objects):
    if o is not body:
        bpy.data.objects.remove(o, do_unlink=True)
body.vertex_groups.clear()
bpy.context.view_layer.objects.active = body; body.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
src_verts = len(body.data.vertices)
if "--decimate" in argv:      # raw Meshy output (300k+ verts) -> pipeline density; collapse keeps UVs
    target = int(argv[argv.index("--decimate") + 1])
    mod = body.modifiers.new("dec", 'DECIMATE'); mod.decimate_type = 'COLLAPSE'
    mod.ratio = min(1.0, target / max(len(body.data.polygons), 1)); mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
P = [v.co for v in body.data.vertices]
lo = Vector((min(p.x for p in P), min(p.y for p in P), min(p.z for p in P)))
hi = Vector((max(p.x for p in P), max(p.y for p in P), max(p.z for p in P)))
body.location = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', use_selection=True,
                          export_materials='EXPORT', export_image_format='AUTO')
dims = [round(x, 3) for x in body.dimensions]
json.dump({"unit": unit, "source": src, "sourceSha256": hashlib.sha256(open(src, "rb").read()).hexdigest(),
           "sourceObject": body.name, "vertices": len(body.data.vertices), "sourceVertices": src_verts,
           "decimatedToFaces": int(argv[argv.index("--decimate") + 1]) if "--decimate" in argv else None,
           "dimensions": dims,
           "note": "evaluated at the skeleton rest pose from a skinned delivery file, then armature, weights and shape keys dropped"},
          open(dst.replace(".glb", ".provenance.json"), "w"), indent=1)
print("INSTALLED", unit, "verts", len(body.data.vertices), "dims", dims, "->", dst)
