"""Blender side of showcase.py: render a unit's clips under the Hex/Lit relight, raw vs prebaked look.

  blender -b <build.blend> --factory-startup -P showcase_render.py -- --out DIR --look LOOK.png
          [--scale 4] [--turn-frames 240] [--idle 1,2,3,...] [--cond sand] [--cells CELLS.json]

--cells swaps the look's base colour per frame for a uvAtlas effect (the oceanid's water flow):
{"sprite": {"<timeline frame>": png}, "turn": [png per --idle entry, or null]}; a frame not listed keeps --look.
Its optional "lights" list ({rgb sRGB, range, frames: {"<timeline frame>": [positionWorld, intensity]}}) adds the
unit's dynamic effectLights to the look's sprite frames with Hex/Lit's point term, as review.py / vfx.point_term:
albedo * rgb * intensity * s^2/d^2 * N.L, s = clamp(1 - (d^2/range^2)^2). Unlit on the turntable (idle).
DIR/anchors.json records every bone's head/tail pixel in the SpriteCam at 100% (DEF resolution) per timeline
frame, for showcase.py to pin the sprite-ripped flipbooks.

Per variant (raw = the build's own Meshy base colour, look = the prebaked base colour) it writes
  DIR/<variant>/sprite_NNN.png   the build's SpriteCam at every timeline frame (NNN = frame, 1-based)
  DIR/<variant>/turn_NNN.png     an orthographic camera orbiting the unit 360 degrees, the sun turning
                                 with it (= the unit turning in place under a fixed arena sun), the
                                 idle frames looping underneath
Shading is Hex/Lit's: albedo * (sun * N.L * shadow + ambient [+ effect point lights]), no specular, no emission,
opaque.
Proof tier: generated artifact (Blender Eevee render), not an in-game capture.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import bpy  # type: ignore
from bpy_extras.object_utils import world_to_camera_view  # type: ignore
from mathutils import Vector  # type: ignore

SUN_SRGB = (1.0, 0.9569, 0.8392)          # prebake_lab.SUN_SRGB
AMBIENT_SRGB = (0.6235, 0.6784, 0.7922)   # prebake_lab.AMBIENT_SRGB
ARENA_SUNS = {"sand": (0.624, -0.4035, 0.6692), "grass": (-0.0215, -0.1804, 0.9834), "snow": (0.4011, -0.4035, 0.8224)}


def lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def point_light_nodes(nt, geo, rng, rgb_lin):
    """Hex/Lit point irradiance at the shading point, as an RGB vector. Returns (position node, intensity node, term)."""
    def m(op, a, b, clamp=False):
        n = nt.nodes.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, x in enumerate((a, b)):
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                nt.links.new(x, n.inputs[i])
        return n.outputs[0]

    def vm(op, a, b):
        n = nt.nodes.new("ShaderNodeVectorMath"); n.operation = op
        nt.links.new(a, n.inputs[0]); nt.links.new(b, n.inputs[1])
        return n.outputs["Value" if op == "DOT_PRODUCT" else "Vector"]

    pos = nt.nodes.new("ShaderNodeCombineXYZ")
    inten = nt.nodes.new("ShaderNodeValue"); inten.outputs[0].default_value = 0.0
    col = nt.nodes.new("ShaderNodeCombineXYZ")
    for i, c in enumerate(rgb_lin):
        col.inputs[i].default_value = c
    d = vm("SUBTRACT", pos.outputs[0], geo.outputs["Position"])
    d2 = m("MAXIMUM", vm("DOT_PRODUCT", d, d), 1e-5)
    s = m("SUBTRACT", 1.0, m("POWER", m("DIVIDE", d2, rng * rng), 2.0), clamp=True)
    att = m("DIVIDE", m("MULTIPLY", s, s), d2)
    ndl = m("DIVIDE", vm("DOT_PRODUCT", geo.outputs["Normal"], d), m("SQRT", d2, 0.0), clamp=True)
    k = m("MULTIPLY", m("MULTIPLY", att, ndl), inten.outputs[0])
    sc = nt.nodes.new("ShaderNodeVectorMath"); sc.operation = "SCALE"
    nt.links.new(col.outputs[0], sc.inputs[0]); nt.links.new(k, sc.inputs["Scale"])
    return pos, inten, sc.outputs["Vector"]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--look", required=True)
    ap.add_argument("--scale", type=float, default=4.0)
    ap.add_argument("--turn-frames", type=int, default=240)
    ap.add_argument("--turn-size", type=int, default=1080)
    ap.add_argument("--idle", default="1")
    ap.add_argument("--cond", default="sand")
    ap.add_argument("--elev", type=float, default=30.0)
    ap.add_argument("--cells")
    a = ap.parse_args(argv)

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    try:
        sc.eevee.taa_render_samples = 32
    except AttributeError:
        pass
    world = sc.world or bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[1].default_value = 0.0   # ambient comes from the material (unoccluded SH, as Hex/Lit)

    for o in list(sc.objects):
        if o.type == "LIGHT":
            o.hide_render = True
    sun_data = bpy.data.lights.new("showcase_sun", "SUN")
    sun_data.energy = 1.0  # Blender sun strength 1 -> a white diffuse facing the sun reads 1.0 (Hex/Lit: sun * N.L)
    sun_data.color = lin(SUN_SRGB)
    sun_data.angle = math.radians(1.0)
    sun = bpy.data.objects.new("showcase_sun", sun_data)
    sc.collection.objects.link(sun)

    meshes = [o for o in sc.objects if o.type == "MESH" and not o.hide_render and o.data.materials]
    cells = json.load(open(a.cells)) if a.cells else {"sprite": {}, "turn": []}
    lights = cells.get("lights", [])
    light_nodes = [[] for _ in lights]  # per light: (position node, intensity node) in every material
    amb = lin(AMBIENT_SRGB)
    slots = []  # (image node, raw image)
    for m in {m for o in meshes for m in o.data.materials if m and m.use_nodes}:
        nt = m.node_tree
        imgs = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image]
        if not imgs:
            continue
        tex = max(imgs, key=lambda n: n.image.size[0] * n.image.size[1])
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
        mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        mul.inputs[7].default_value = (*amb, 1.0)
        emi = nt.nodes.new("ShaderNodeEmission")
        add = nt.nodes.new("ShaderNodeAddShader")
        nt.links.new(tex.outputs["Color"], diff.inputs["Color"])
        nt.links.new(tex.outputs["Color"], mul.inputs[6])
        if lights:
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            total = None
            for li, lt in enumerate(lights):
                pos, inten, term = point_light_nodes(nt, geo, float(lt["range"]), lin(lt["rgb"]))
                light_nodes[li].append((pos, inten))
                if total is None:
                    total = term
                else:
                    add_v = nt.nodes.new("ShaderNodeVectorMath"); add_v.operation = "ADD"
                    nt.links.new(total, add_v.inputs[0]); nt.links.new(term, add_v.inputs[1])
                    total = add_v.outputs["Vector"]
            lit = nt.nodes.new("ShaderNodeVectorMath"); lit.operation = "MULTIPLY"
            nt.links.new(tex.outputs["Color"], lit.inputs[0]); nt.links.new(total, lit.inputs[1])
            emit = nt.nodes.new("ShaderNodeVectorMath"); emit.operation = "ADD"
            nt.links.new(mul.outputs[2], emit.inputs[0]); nt.links.new(lit.outputs["Vector"], emit.inputs[1])
            nt.links.new(emit.outputs["Vector"], emi.inputs["Color"])
        else:
            nt.links.new(mul.outputs[2], emi.inputs["Color"])
        nt.links.new(diff.outputs[0], add.inputs[0])
        nt.links.new(emi.outputs[0], add.inputs[1])
        nt.links.new(add.outputs[0], out.inputs["Surface"])
        try:
            m.blend_method = "OPAQUE"  # the plugin restamp forces opaque
        except (AttributeError, TypeError):
            pass
        slots.append((tex, tex.image))
    if not slots:
        raise SystemExit("no textured material found")
    look = bpy.data.images.load(a.look)
    look.colorspace_settings.name = "sRGB"

    spr = bpy.data.objects["SpriteCam"]

    def set_lights(t):
        """Light the effect lights of timeline frame t (None = all off)."""
        for lt, nodes in zip(lights, light_nodes):
            row = lt["frames"].get(str(t)) if t is not None else None
            for pos, inten in nodes:
                inten.outputs[0].default_value = float(row[1]) if row else 0.0
                if row:
                    for i in range(3):
                        pos.inputs[i].default_value = row[0][i]
    loaded = {}

    def image_for(path):
        if not path:
            return look
        if path not in loaded:
            loaded[path] = bpy.data.images.load(path)
            loaded[path].colorspace_settings.name = "sRGB"
        return loaded[path]

    def set_tex(img):
        for tex, _ in slots:
            tex.image = img

    def sun_for(cam):
        ux, uy, uz = ARENA_SUNS[a.cond]
        m = cam.matrix_world.to_3x3()
        right, fwd = (m @ Vector((1, 0, 0))).normalized(), (m @ Vector((0, 0, -1))).normalized()
        rh = Vector((right.x, right.y, 0)).normalized(); fh = Vector((fwd.x, fwd.y, 0)).normalized()
        travel = (rh * ux + fh * uz + Vector((0, 0, 1)) * uy).normalized()
        sun.rotation_euler = travel.to_track_quat("-Z", "Y").to_euler()

    # turntable camera around the idle frame-1 body
    sc.frame_set(int(a.idle.split(",")[0]))
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in meshes:
        ev = o.evaluated_get(deps)
        pts += [o.matrix_world @ v.co for v in ev.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) * 0.5
    extent = max((hi - lo).x, (hi - lo).y, (hi - lo).z)
    cd = bpy.data.cameras.new("turn"); cd.type = "ORTHO"; cd.ortho_scale = extent * 1.35
    turn = bpy.data.objects.new("turn", cd); sc.collection.objects.link(turn)
    idle = [int(x) for x in a.idle.split(",") if x]
    fwd0 = Vector(spr.matrix_world.to_3x3() @ Vector((0, 0, -1)))
    az0 = math.atan2(-fwd0.y, -fwd0.x)  # start where the sprite camera looks from

    res0 = (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage)
    rigs = [o for o in sc.objects if o.type == "ARMATURE"]
    anchors = {}
    for t in range(sc.frame_start, sc.frame_end + 1):
        sc.frame_set(t)
        fr = anchors[t] = {}
        for rig in rigs:
            for pb in rig.pose.bones:
                fr[pb.name] = {}
                for k, loc in (("headPx", pb.head), ("tailPx", pb.tail)):
                    v = world_to_camera_view(sc, spr, rig.matrix_world @ loc)
                    fr[pb.name][k] = [v.x * res0[0], (1 - v.y) * res0[1]]
    os.makedirs(a.out, exist_ok=True)
    json.dump({"resolution": [res0[0], res0[1]], "frames": anchors}, open(os.path.join(a.out, "anchors.json"), "w"))
    for variant in ("raw", "look"):
        for tex, raw in slots:
            tex.image = raw if variant == "raw" else look
        swap = variant == "look"
        d = os.path.join(a.out, variant); os.makedirs(d, exist_ok=True)
        sc.camera = spr
        sc.render.resolution_x, sc.render.resolution_y = res0[0], res0[1]
        sc.render.resolution_percentage = int(round(100 * a.scale))
        sun_for(spr)
        for t in range(sc.frame_start, sc.frame_end + 1):
            sc.frame_set(t)
            set_lights(t if swap else None)
            if swap:
                set_tex(image_for(cells["sprite"].get(str(t))))
            sc.render.filepath = os.path.join(d, f"sprite_{t:03d}.png")
            bpy.ops.render.render(write_still=True)
        sc.camera = turn
        set_lights(None)
        sc.render.resolution_x = sc.render.resolution_y = a.turn_size
        sc.render.resolution_percentage = 100
        e = math.radians(a.elev)
        for i in range(a.turn_frames):
            az = az0 + 2 * math.pi * i / a.turn_frames
            to_cam = Vector((math.cos(az) * math.cos(e), math.sin(az) * math.cos(e), math.sin(e)))
            turn.location = centre + to_cam * extent * 4
            turn.rotation_euler = (-to_cam).to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()
            sun_for(turn)
            ii = (i // 3) % len(idle)
            sc.frame_set(idle[ii])  # idle at 10 fps under a 30 fps orbit
            if swap:
                set_tex(image_for(cells["turn"][ii] if ii < len(cells["turn"]) else None))
            sc.render.filepath = os.path.join(d, f"turn_{i:03d}.png")
            bpy.ops.render.render(write_still=True)
    print("SHOWCASE_RENDER_OK")


main(sys.argv[sys.argv.index("--") + 1:])
