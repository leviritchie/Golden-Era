#!/usr/bin/env python3
"""Blender: unlit preview of depth-projected Factory backdrop (Option B spike)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv
args = argv[argv.index("--") + 1 :] if "--" in argv else []
obj_path = None
albedo_path = None
out_dir = None
i = 0
while i < len(args):
    if args[i] == "--obj" and i + 1 < len(args):
        obj_path = Path(args[i + 1])
        i += 2
    elif args[i] == "--albedo" and i + 1 < len(args):
        albedo_path = Path(args[i + 1])
        i += 2
    elif args[i] == "--out-dir" and i + 1 < len(args):
        out_dir = Path(args[i + 1])
        i += 2
    else:
        i += 1
if obj_path is None or albedo_path is None or out_dir is None:
    raise SystemExit("need --obj --albedo --out-dir")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.obj(filepath=str(obj_path), use_edges=True, use_smooth_groups=False)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")

# Force unlit emission so we see the exact paint, not lighting wash.
img = bpy.data.images.load(str(albedo_path))
mat = bpy.data.materials.new("FactoryPaintUnlit")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
out = nt.nodes.new("ShaderNodeOutputMaterial")
em = nt.nodes.new("ShaderNodeEmission")
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
tex.interpolation = "Closest"
em.inputs["Strength"].default_value = 1.0
nt.links.new(tex.outputs["Color"], em.inputs["Color"])
nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
for o in meshes:
    o.data.materials.clear()
    o.data.materials.append(mat)

mins = Vector((1e9, 1e9, 1e9))
maxs = Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for corner in o.bound_box:
        w = o.matrix_world @ Vector(corner)
        mins = Vector((min(mins.x, w.x), min(mins.y, w.y), min(mins.z, w.z)))
        maxs = Vector((max(maxs.x, w.x), max(maxs.y, w.y), max(maxs.z, w.z)))
center = (mins + maxs) * 0.5
size = maxs - mins

# OBJ Y-up import rotates into Blender Z-up; depth is the thinnest AABB axis.
extents = [
    (size.x, Vector((1.0, 0.0, 0.0)), mins.x, maxs.x),
    (size.y, Vector((0.0, 1.0, 0.0)), mins.y, maxs.y),
    (size.z, Vector((0.0, 0.0, 1.0)), mins.z, maxs.z),
]
extents_sorted = sorted(extents, key=lambda t: t[0])
# File +Z (near/paint) maps to Blender -Y under default Y-up OBJ import → near at mins.
thin_axis = extents_sorted[0][1]
near_is_min = True  # default Y-up OBJ → Blender: near on the min side of thin axis
depth_axis = (-thin_axis) if near_is_min else thin_axis
face_a = extents_sorted[1][1]
face_b = extents_sorted[2][1]
face_w = max(extents_sorted[1][0], extents_sorted[2][0]) * 0.5
face_h = min(extents_sorted[1][0], extents_sorted[2][0]) * 0.5
up_hint = Vector((0.0, 0.0, 1.0))
if abs(depth_axis.dot(up_hint)) > 0.9:
    up_hint = Vector((0.0, 1.0, 0.0))

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.use_denoising = False
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

world = bpy.data.worlds.new("PreviewWorld")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.05, 0.055, 0.07, 1.0)
bg.inputs[1].default_value = 1.0

cam_data = bpy.data.cameras.new("PreviewCam")
cam_data.lens = 50.0
cam_data.sensor_width = 36.0
cam_obj = bpy.data.objects.new("PreviewCam", cam_data)
bpy.context.collection.objects.link(cam_obj)
scene.camera = cam_obj


def look_at(obj, target: Vector, up: Vector):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    # Re-derive with preferred up if track quat left us rolled sideways.
    q = direction.to_track_quat("-Z", "Y")
    # If resulting local +Y is anti-aligned with up, flip by 180 around view.
    local_y = q @ Vector((0.0, 1.0, 0.0))
    if local_y.dot(up) < 0.0:
        obj.rotation_euler.rotate_axis("Z", math.pi)


def cam_distance_for_frame(fov_y_deg: float = 39.6) -> float:
    fov = math.radians(fov_y_deg)
    dist_h = face_h / math.tan(fov * 0.5)
    fov_x = 2.0 * math.atan(math.tan(fov * 0.5) * (16.0 / 9.0))
    dist_w = face_w / math.tan(fov_x * 0.5)
    return max(dist_h, dist_w) * 1.08


base_dist = cam_distance_for_frame()
look_target = center.copy()

# Basis: depth toward camera, plus face horizontal/vertical for yaw/pitch offsets.
right = face_b if extents_sorted[2][0] >= extents_sorted[1][0] else face_a
up_face = face_a if right == face_b else face_b
# Ensure right x up roughly matches depth direction for a right-handed frame.
if right.cross(up_face).dot(depth_axis) < 0.0:
    up_face = -up_face

views = [
    ("front", depth_axis * base_dist),
    ("yaw_left", (depth_axis * (base_dist * 0.97) + (-right) * (base_dist * 0.22))),
    ("yaw_right", (depth_axis * (base_dist * 0.97) + right * (base_dist * 0.22))),
    ("low_orbit", (depth_axis * (base_dist * 0.95) + right * (base_dist * 0.12) + (-up_face) * (base_dist * 0.10))),
]

out_dir.mkdir(parents=True, exist_ok=True)
print(
    f"bounds size=({size.x:.3f},{size.y:.3f},{size.z:.3f}) "
    f"depth_axis={tuple(depth_axis)} base_dist={base_dist:.3f}"
)
for name, offset in views:
    cam_obj.location = look_target + offset
    look_at(cam_obj, look_target, up_hint)
    scene.render.filepath = str(out_dir / f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"wrote {scene.render.filepath}")
