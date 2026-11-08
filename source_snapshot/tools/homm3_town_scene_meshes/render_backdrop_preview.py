#!/usr/bin/env python3
"""Blender: render Factory town backdrop Meshy GLB for human preview (not OE deploy)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# blender -b --python this.py -- --glb ... --out-dir ...
argv = sys.argv
args = argv[argv.index("--") + 1 :] if "--" in argv else []
glb = None
out_dir = None
i = 0
while i < len(args):
    if args[i] == "--glb" and i + 1 < len(args):
        glb = Path(args[i + 1])
        i += 2
    elif args[i] == "--out-dir" and i + 1 < len(args):
        out_dir = Path(args[i + 1])
        i += 2
    else:
        i += 1
if glb is None or out_dir is None:
    raise SystemExit("need --glb and --out-dir")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(glb))

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh in GLB")

# World bounds
mins = Vector((1e9, 1e9, 1e9))
maxs = Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for corner in o.bound_box:
        w = o.matrix_world @ Vector(corner)
        mins = Vector((min(mins.x, w.x), min(mins.y, w.y), min(mins.z, w.z)))
        maxs = Vector((max(maxs.x, w.x), max(maxs.y, w.y), max(maxs.z, w.z)))
center = (mins + maxs) * 0.5
size = maxs - mins
radius = max(size.x, size.y, size.z) * 0.55
if radius < 0.01:
    radius = 1.0

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

# Simple lit world
world = bpy.data.worlds.new("PreviewWorld")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.08, 0.09, 0.11, 1.0)
bg.inputs[1].default_value = 1.0

# Key + fill lights
def add_light(name, energy, loc, size=4.0):
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    return obj

add_light("Key", 800.0, center + Vector((radius * 1.2, -radius * 1.4, radius * 1.6)))
add_light("Fill", 250.0, center + Vector((-radius * 1.5, -radius * 0.6, radius * 0.8)), size=6.0)
add_light("Rim", 180.0, center + Vector((0.0, radius * 1.6, radius * 0.9)), size=5.0)

cam_data = bpy.data.cameras.new("PreviewCam")
cam_data.lens = 35
cam = bpy.data.objects.new("PreviewCam", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam

out_dir.mkdir(parents=True, exist_ok=True)
views = [
    ("front", Vector((0.0, -radius * 2.2, radius * 0.35))),
    ("three_quarter", Vector((radius * 1.6, -radius * 1.8, radius * 0.55))),
    ("high", Vector((radius * 0.4, -radius * 1.6, radius * 1.8))),
]

for name, offset in views:
    cam.location = center + offset
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    out = out_dir / f"backdrop_preview_{name}.png"
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print(f"wrote {out}", flush=True)

# Side-by-side style: also copy nothing; report done
print(
    {
        "ok": True,
        "center": [center.x, center.y, center.z],
        "size": [size.x, size.y, size.z],
        "meshCount": len(meshes),
        "outDir": str(out_dir),
    },
    flush=True,
)
