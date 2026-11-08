"""Render one loop of a GLB clip at 30 fps (1x real time) with the Workbench engine.

    blender -b --factory-startup -P tools/homm3_idle_cadence/render_idle_blender.py -- \
        <in.glb> <clip> <out_dir> [--size 360]

Writes <out_dir>/f_%04d.png for t = 0, 1/30, ... < loop length, so the frames tile seamlessly when
looped (ffmpeg -stream_loop). The scene runs at 30 fps before import, so glTF seconds map to
frames exactly; the clip's action is assigned to the armature and, when present, to the mesh's
shape keys (the corrective-smooth morph weights). Camera: fixed orthographic front-left view
fitted to the rest-pose bounding box, the same for before and after of one unit.
Run `python tools/homm3_def_retarget/memgate.py` first.
"""
import bpy, sys, os, math
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, clip, out = argv[0], argv[1], argv[2]
size = int(argv[argv.index("--size") + 1]) if "--size" in argv else 360
FPS = 30

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = FPS; sc.render.fps_base = 1.0
bpy.ops.import_scene.gltf(filepath=src)
act = bpy.data.actions.get(clip)
if act is None:
    sys.exit(f"FAIL: no action {clip!r}; have {[a.name for a in bpy.data.actions]}")
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
meshes = [o for o in bpy.data.objects if o.type == 'MESH']


def assign(idblock, action):
    ad = idblock.animation_data or idblock.animation_data_create()
    for tr in list(ad.nla_tracks):
        ad.nla_tracks.remove(tr)
    ad.action = action
    slots = getattr(action, "slots", None)
    if slots is not None and len(slots):
        want = 'OBJECT' if isinstance(idblock, bpy.types.Object) else 'KEY'
        cand = [s for s in slots if s.target_id_type == want]
        if cand:
            ad.action_slot = cand[0]
    return ad


assign(arm, act)
shape_action = bpy.data.actions.get(clip + "_ShapeKeys") or bpy.data.actions.get(clip)
for m in meshes:
    if m.data.shape_keys is not None:
        assign(m.data.shape_keys, shape_action)
f0, f1 = act.frame_range
loop_frames = f1 - f0
print("CLIP", clip, "frames", f0, f1, "seconds", loop_frames / FPS)

# camera fitted to the rest bounding box (evaluate at the first frame)
sc.frame_set(int(math.floor(f0)), subframe=f0 - math.floor(f0))
dg = bpy.context.evaluated_depsgraph_get()
pts = []
body = max(meshes, key=lambda o: len(o.data.vertices))   # rubble / helper meshes are not framed
for m in [body]:
    ev = m.evaluated_get(dg)
    pts += [ev.matrix_world @ v.co for i, v in enumerate(ev.data.vertices) if i % 7 == 0]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (lo + hi) / 2
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam")); sc.collection.objects.link(cam)
cam.data.type = 'ORTHO'; cam.data.ortho_scale = max(hi - lo) * 1.15
d = Vector((-0.9, 0.1, -0.35)).normalized()
cam.location = ctr - d * 20; cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
cam.data.clip_end = 100
sc.camera = cam
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'TEXTURE'
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("W"); sc.world.color = (0.82, 0.82, 0.8)
os.makedirs(out, exist_ok=True)
n = int(math.ceil(round(loop_frames, 3) - 1e-6))   # t in [0, loop); a non-integer loop tiles within 1/30 s
for k in range(n):
    f = f0 + k
    sc.frame_set(int(math.floor(f)), subframe=f - math.floor(f))
    sc.render.filepath = os.path.join(out, f"f_{k:04d}.png")
    bpy.ops.render.render(write_still=True)
print("RENDERED", n, "frames to", out)
