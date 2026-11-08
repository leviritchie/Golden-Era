"""High-resolution review sheet: textured renders with stretched faces tinted red.

Usage: blender -b <unit_def_retarget.blend> -P review.py -- <out_prefix> [res=768]
Frames: one mid frame per clip plus the four worst-stretch frames (from stretch.json next to the
.blend). Each frame is rendered from the sprite-side front-left and from behind-right, with
vertices on edges stretched >2x tinted cyan and >1.5x yellow, so small tears that vanish at
sprite size stand out. Writes <out_prefix>_NNN.png per frame and <out_prefix>.json (frame list).
"""
import bpy, sys, json, os
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]; res = int(argv[1]) if len(argv) > 1 else 768
blend = bpy.data.filepath
fj = json.load(open(blend + ".frames.json"))
st = json.load(open(os.path.join(os.path.dirname(blend), "stretch.json")))
seg = {}
for k, a, b in fj["segments"]:
    if k not in seg or b - a > seg[k][1] - seg[k][0]:
        seg[k] = (a, b)
frames = sorted({(a + b) // 2 for a, b in seg.values()} | set(int(i) for i in np.argsort([-s[2] for s in st])[:4]))

sc = bpy.context.scene
ob = next(o for o in bpy.data.objects if o.type == "MESH" and "Armature" in o.modifiers and not o.name.endswith("_Rubble"))
dg = bpy.context.evaluated_depsgraph_get()
me = ob.data
R = np.array([v.co[:] for v in me.vertices])
E = np.array([e.vertices[:] for e in me.edges]); L0 = np.linalg.norm(R[E[:, 0]] - R[E[:, 1]], axis=1)

# material: mix the base texture with a per-vertex tint attribute
tint = me.color_attributes.get("review_tint") or me.color_attributes.new("review_tint", 'FLOAT_COLOR', 'POINT')
for mat in me.materials:
    nt = mat.node_tree; bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    link = next((l for l in nt.links if l.to_socket == bsdf.inputs["Base Color"]), None)
    if link is None or "ReviewMix" in nt.nodes:
        continue
    src = link.from_socket
    attr = nt.nodes.new("ShaderNodeAttribute"); attr.attribute_name = "review_tint"
    mix = nt.nodes.new("ShaderNodeMix"); mix.name = "ReviewMix"; mix.data_type = 'RGBA'
    nt.links.new(attr.outputs["Alpha"], mix.inputs[0]); nt.links.new(src, mix.inputs[6]); nt.links.new(attr.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])

sc.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE'
sc.render.resolution_x = sc.render.resolution_y = res
sc.render.film_transparent = False
if sc.world is None:
    sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.25, 0.25, 0.27)
if not any(o.type == 'LIGHT' for o in bpy.data.objects):
    for rot, en in (((0.8, 0.2, 0.6), 4.0), ((1.2, 0.0, 3.6), 2.0)):
        L = bpy.data.objects.new("L", bpy.data.lights.new("L", 'SUN')); L.data.energy = en; L.rotation_euler = rot
        sc.collection.objects.link(L)
cam = bpy.data.objects.new("ReviewCam", bpy.data.cameras.new("ReviewCam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'
views = [Vector((0.42, 0.89, -0.25)), Vector((-0.6, -0.75, -0.3))]
for t in frames:
    sc.frame_set(t + 1)
    em = ob.evaluated_get(dg).to_mesh(); P = np.array([v.co[:] for v in em.vertices]); ob.evaluated_get(dg).to_mesh_clear()
    r = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1) / np.maximum(L0, 1e-6)
    vr = np.zeros(len(R))
    np.maximum.at(vr, E[:, 0], r); np.maximum.at(vr, E[:, 1], r)
    for i, x in enumerate(vr):
        tint.data[i].color = (0.0, 1.0, 1.0, 0.9) if x > 2 else (1.0, 1.0, 0.0, 0.6) if x > 1.5 else (0, 0, 0, 0)
    lo, hi = P.min(0), P.max(0); ctr = Vector(((lo + hi) / 2).tolist()); ext = float(np.max(hi - lo))
    cam.data.ortho_scale = ext * 1.15
    for vi, f in enumerate(views):
        f = f.normalized(); cam.location = ctr - f * 10; cam.rotation_euler = f.to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = f"{out}_{t:03d}_{vi}.png"; bpy.ops.render.render(write_still=True)
json.dump({"frames": frames, "segments": fj["segments"], "stretch": [st[t] for t in frames]}, open(out + ".json", "w"))
