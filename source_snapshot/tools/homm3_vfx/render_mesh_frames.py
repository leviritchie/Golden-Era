"""Blender (headless) renderer for the VFX experiments.

Opens a *copy* of a def_retarget .blend and, for each timeline frame (= DEF master
frame), renders through the calibrated SpriteCam:
  base_XXX.png  textured Workbench render, transparent background
  mask_XXX.png  flat render of a vertex attribute = normalised rest height (0 bottom .. 1 top),
                used to emulate a per-vertex emissive band in 2D compositing
and writes bones.json: every bone's head/tail projected to sprite pixels (1x, y down).

Usage: blender -b COPY.blend --python render_mesh_frames.py -- OUTDIR SCALE
"""
import bpy, sys, json, os
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index("--") + 1:]
out, scale = argv[0], int(argv[1])
os.makedirs(out, exist_ok=True)
sc = bpy.context.scene
cam = bpy.data.objects["SpriteCam"]
sc.camera = cam
W, H = sc.render.resolution_x, sc.render.resolution_y
sc.render.resolution_percentage = 100 * scale
sc.render.engine = 'BLENDER_WORKBENCH'
sc.render.film_transparent = True
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'TEXTURE'
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'

arm = next(o for o in sc.objects if o.type == 'ARMATURE')
meshes = [o for o in sc.objects if o.type == 'MESH' and not o.hide_render]
for o in meshes:
    zs = [v.co.z for v in o.data.vertices]
    z0, z1 = min(zs), max(zs)
    a = o.data.color_attributes.new("vfx_height", 'FLOAT_COLOR', 'POINT')
    for i, v in enumerate(o.data.vertices):
        h = (v.co.z - z0) / max(1e-6, z1 - z0)
        a.data[i].color = (h, h, h, 1.0)
    o.data.color_attributes.active_color = a

bones = {}
for t in range(sc.frame_start, sc.frame_end + 1):
    sc.frame_set(t)
    rec = {}
    for pb in arm.pose.bones:
        for key, p in (("head", pb.head), ("tail", pb.tail)):
            c = world_to_camera_view(sc, cam, arm.matrix_world @ p)
            rec.setdefault(pb.name, {})[key] = [c.x * W, (1 - c.y) * H, c.z]
    bones[t] = rec
    sc.display.shading.color_type = 'TEXTURE'
    sc.display.shading.light = 'STUDIO'
    sc.render.filepath = f"{out}/base_{t:03d}.png"
    bpy.ops.render.render(write_still=True)
    sc.display.shading.color_type = 'VERTEX'
    sc.display.shading.light = 'FLAT'
    sc.render.filepath = f"{out}/mask_{t:03d}.png"
    bpy.ops.render.render(write_still=True)
json.dump({"size": [W, H], "scale": scale, "frames": bones}, open(f"{out}/bones.json", "w"))
print("DONE", sc.frame_start, sc.frame_end)
