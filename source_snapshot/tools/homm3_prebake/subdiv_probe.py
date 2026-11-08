"""Blender side: baked-subdivision probe on an in-memory copy of the unit (never saves).

    blender -b <unit>_def_retarget.blend --factory-startup -P tools/homm3_prebake/subdiv_probe.py -- \
        --texture artifacts/homm3_prebaked_lighting/behemoth/textures/v6_sprite_match_basecolor.png \
        --out artifacts/homm3_prebaked_lighting/behemoth/subdiv

Renders the posed unit (frame 1, and a large-pose frame) with and without a Catmull-Clark
level-1 subdivision placed *before* the Armature modifier (Blender interpolates vertex-group
weights onto the new vertices, which is what a baked delivery would export), under a
Hex/Lit-like rig: one sun (arena colour, strength pi so a white Lambert surface facing it = 1.0)
plus a flat world of the arena ambient colour. Material is Diffuse BSDF with the given base
colour, no normal map (the installed Hex/Lit has none).

Shape keys (the corrective-smooth morphs) are removed in memory for BOTH renders, because
Blender cannot evaluate subdivision below existing shape keys on export; a delivery would have
to re-run bake_cs.py on the subdivided mesh. Proof tier: generated artifact (Blender-rendered).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--texture", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", default="1,50")
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--uv-smooth", default="PRESERVE_BOUNDARIES")
    ap.add_argument("--weld", type=float, default=0.0, help="merge-by-distance before subdividing (m)")
    ap.add_argument("--front", default="-y", choices=["+x", "-x", "+y", "-y"], help="unit's facing axis")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = bpy.context.scene
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "CUDA"
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU"
    sc.cycles.samples = 64
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x = sc.render.resolution_y = args.size
    sc.render.resolution_percentage = 100
    try:
        sc.render.image_settings.media_type = "IMAGE"
    except (AttributeError, TypeError):
        pass
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    obj = max(meshes, key=lambda o: 0 if "Rubble" in o.name else len(o.data.vertices))
    for o in meshes:
        if o is not obj:
            o.hide_render = True
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            o.hide_render = True
    if obj.data.shape_keys:
        obj.shape_key_clear()

    if args.weld > 0:
        import bmesh  # type: ignore

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=args.weld)
        bm.to_mesh(obj.data)
        print("WELD", before, "->", len(bm.verts), flush=True)
        bm.free()

    img = bpy.data.images.load(str(Path(args.texture).resolve()))
    mat = bpy.data.materials.new("hexlit_like")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    o_ = nt.nodes.new("ShaderNodeOutputMaterial")
    df = nt.nodes.new("ShaderNodeBsdfDiffuse")
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = img
    nt.links.new(tx.outputs["Color"], df.inputs["Color"])
    nt.links.new(df.outputs["BSDF"], o_.inputs["Surface"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    amb = [srgb_to_lin(c) for c in (0.6235, 0.6784, 0.7922)]
    w = bpy.data.worlds.new("amb")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*amb, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    sc.world = w
    sd = bpy.data.lights.new("sun", "SUN")
    sd.color = tuple(srgb_to_lin(c) for c in (1.0, 0.9569, 0.8392))
    sd.energy = math.pi
    sd.angle = math.radians(1)
    sun = bpy.data.objects.new("sun", sd)
    sc.collection.objects.link(sun)

    front = Vector({"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}[args.front])
    left = Vector((0, 0, 1)).cross(front).normalized()
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    sc.collection.objects.link(cam)
    sc.camera = cam

    subsurf = obj.modifiers.new("prebake_subdiv", "SUBSURF")
    subsurf.levels = subsurf.render_levels = 1
    subsurf.uv_smooth = args.uv_smooth
    # Subdivision must run before the Armature modifier so weights are interpolated.
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(object=obj):
        bpy.ops.object.modifier_move_to_index(modifier="prebake_subdiv", index=0)

    report = {"proof": "generated artifact (Blender Cycles render)", "renders": []}
    for level in (0, 1):
        subsurf.show_render = subsurf.show_viewport = level == 1
        for f in [int(x) for x in args.frames.split(",")]:
            sc.frame_set(f)
            deps = bpy.context.evaluated_depsgraph_get()
            ev = obj.evaluated_get(deps)
            me = ev.to_mesh()
            me.calc_loop_triangles()
            nv, nt_ = len(me.vertices), len(me.loop_triangles)
            pts = [obj.matrix_world @ v.co for v in me.vertices]
            ev.to_mesh_clear()
            lo = Vector([min(p[i] for p in pts) for i in range(3)])
            hi = Vector([max(p[i] for p in pts) for i in range(3)])
            c = (lo + hi) / 2
            ext = max(hi - lo)
            for facing, az in (("faces_right", -60.0), ("faces_camera", 0.0)):
                a, e = math.radians(az), math.radians(40)
                to_cam = (front * math.cos(a) + left * math.sin(a)) * math.cos(e) + Vector((0, 0, math.sin(e)))
                cam.location = c + to_cam * ext * 4
                cam.rotation_euler = (-to_cam).to_track_quat("-Z", "Y").to_euler()
                cam.data.ortho_scale = ext * 1.1
                m3 = cam.matrix_world.to_3x3()
                r = (m3 @ Vector((1, 0, 0)));  r.z = 0; r.normalize()
                fw = (m3 @ Vector((0, 0, -1))); fw.z = 0; fw.normalize()
                travel = (r * 0.624 + fw * 0.6692 + Vector((0, 0, -0.4035))).normalized()
                sun.rotation_euler = travel.to_track_quat("-Z", "Y").to_euler()
                path = out / f"subdiv{level}_f{f:03d}_{facing}.png"
                bpy.ops.render.render(write_still=False)
                bpy.data.images["Render Result"].save_render(filepath=str(path), scene=sc)
                report["renders"].append({"subdivLevel": level, "frame": f, "facing": facing,
                                          "vertices": nv, "triangles": nt_, "png": str(path)})
                print("RENDER", path.name, nv, nt_, flush=True)
    (out / "subdiv_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


main(sys.argv[sys.argv.index("--") + 1:])
