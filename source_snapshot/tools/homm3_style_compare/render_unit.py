"""Blender side of the style comparison: render one unit (ours or vanilla) under the Hex/Lit relight.

    blender -b [<build.blend>] --factory-startup -P render_unit.py -- --job JOB.json

JOB.json:
  {"kind": "ours" | "native",
   "out": DIR,
   "frame": 1,                      # ours: the timeline frame (first idle frame) the unit is posed at
   "native": DIR,                   # native: extract_native.py output (mesh.npz, mat_*.png, emi_*.png, meta.json)
   "looks": {"lit": PNG, ...},      # ours: base colour per variant (swapped into the build's largest texture slot)
   "targetHeight": h,               # battle world height to fit to (ours: battleHeightHexes * perHex); omit = as-is
   "ortho": W,                      # orthographic width in battle world units (same for both units of a pair)
   "res": 1600, "cond": "sand"}
Writes DIR/<variant>_<view>.png (RGBA, transparent background) and DIR/render_meta.json (triangle count,
battle-space bounds, camera). Views: battle (elev 40 deg, the unit facing screen-right, camera looking along the
arena's forward axis), front34 (elev 15, 45 deg off the unit's front), turn_0..7 (elev 30, 45 deg steps from the
battle view; the sun turns with the camera = the unit turning in place under a fixed arena sun).
Variants: every ours look (lit), "albedo" (flat base colour, unlit) and, for vanilla materials with
HEX_EMISSION_MAP_ENABLED, "emi" (lit + the emission map added at weight 1: assumed, see the page).
Shading = showcase_render.py's Hex/Lit relight: albedo * (sun * N.L * shadow + ambient), no specular.
Proof tier: generated artifact (Blender Eevee render), not an in-game capture. Never saves a .blend.
"""
from __future__ import annotations

import json
import math
import os
import sys

import bpy  # type: ignore
import numpy as np
from mathutils import Vector  # type: ignore

SUN_SRGB = (1.0, 0.9569, 0.8392)          # prebake_lab.SUN_SRGB (as showcase_render.py)
AMBIENT_SRGB = (0.6235, 0.6784, 0.7922)   # prebake_lab.AMBIENT_SRGB
ARENA_SUNS = {"sand": (0.624, -0.4035, 0.6692), "grass": (-0.0215, -0.1804, 0.9834), "snow": (0.4011, -0.4035, 0.8224)}


def lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def setup_scene(res):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    try:
        sc.eevee.taa_render_samples = 32
    except AttributeError:
        pass
    world = sc.world or bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[1].default_value = 0.0
    for o in list(sc.objects):
        if o.type == "LIGHT":
            o.hide_render = True
    sd = bpy.data.lights.new("cmp_sun", "SUN")
    sd.energy = 1.0
    sd.color = lin(SUN_SRGB)
    sd.angle = math.radians(1.0)
    sun = bpy.data.objects.new("cmp_sun", sd)
    sc.collection.objects.link(sun)
    return sc, sun


def hexlit_material(nt, tex, emi_tex=None, alpha_clip=None):
    """Rewire a node tree to Hex/Lit: diffuse(sun) + albedo*ambient emission. Returns switch nodes per variant."""
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    mul.inputs[7].default_value = (*lin(AMBIENT_SRGB), 1.0)
    amb = nt.nodes.new("ShaderNodeEmission")
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tex.outputs["Color"], diff.inputs["Color"])
    nt.links.new(tex.outputs["Color"], mul.inputs[6])
    nt.links.new(mul.outputs[2], amb.inputs["Color"])
    nt.links.new(diff.outputs[0], add.inputs[0])
    nt.links.new(amb.outputs[0], add.inputs[1])
    lit = add
    flat = nt.nodes.new("ShaderNodeEmission")          # unlit albedo
    nt.links.new(tex.outputs["Color"], flat.inputs["Color"])
    emi_node = None
    if emi_tex is not None:
        e = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(emi_tex.outputs["Color"], e.inputs["Color"])
        emi_node = nt.nodes.new("ShaderNodeAddShader")
        nt.links.new(add.outputs[0], emi_node.inputs[0]); nt.links.new(e.outputs[0], emi_node.inputs[1])
    final = {"lit": lit, "albedo": flat, "emi": emi_node or lit}
    clip = None
    if alpha_clip is not None:
        gt = nt.nodes.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = alpha_clip
        nt.links.new(tex.outputs["Alpha"], gt.inputs[0])
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        clip = (gt, tr)

    def use(variant):
        src = final[variant]
        if clip:
            mix = nt.nodes.get("cmp_clipmix") or nt.nodes.new("ShaderNodeMixShader")
            mix.name = "cmp_clipmix"
            nt.links.new(clip[0].outputs[0], mix.inputs[0])
            nt.links.new(clip[1].outputs[0], mix.inputs[1])
            nt.links.new(src.outputs[0], mix.inputs[2])
            nt.links.new(mix.outputs[0], out.inputs["Surface"])
        else:
            nt.links.new(src.outputs[0], out.inputs["Surface"])
    return use


def build_native(nd):
    d = np.load(os.path.join(nd, "mesh.npz"))
    meta = json.load(open(os.path.join(nd, "meta.json")))
    pos = d["pos"].astype(np.float64); nrm = d["nrm"].astype(np.float64); uv = d["uv"]; tri = d["tri"]; mi = d["mat"]
    # Unity (x right, y up, z forward; left-handed) -> Blender (x right, y forward, z up): swap y/z
    P = pos[:, [0, 2, 1]]; N = nrm[:, [0, 2, 1]]
    me = bpy.data.meshes.new("native")
    me.from_pydata(P.tolist(), [], tri.tolist())
    me.update()
    me.polygons.foreach_set("material_index", mi.tolist())
    uvl = me.uv_layers.new(name="UVMap")
    loops = np.zeros(len(me.loops), dtype=np.int64); me.loops.foreach_get("vertex_index", loops)
    uvl.data.foreach_set("uv", uv[loops].astype(np.float32).ravel())
    try:
        me.normals_split_custom_set_from_vertices(N.tolist())
    except Exception:
        pass
    ob = bpy.data.objects.new("native", me)
    bpy.context.scene.collection.objects.link(ob)
    switches, has_emi = [], False
    for i, m in enumerate(meta["materials"]):
        mat = bpy.data.materials.new(m["name"] or f"m{i}")
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            if n.type != "OUTPUT_MATERIAL":
                nt.nodes.remove(n)
        tex = nt.nodes.new("ShaderNodeTexImage")
        if m.get("mainTexture"):
            img = bpy.data.images.load(os.path.join(nd, m["mainTexture"])); img.colorspace_settings.name = "sRGB"
            tex.image = img
        emi = None
        kw = m.get("keywords") or []
        if m.get("emissionTexture") and "HEX_EMISSION_MAP_ENABLED" in kw:
            emi = nt.nodes.new("ShaderNodeTexImage")
            ei = bpy.data.images.load(os.path.join(nd, m["emissionTexture"])); ei.colorspace_settings.name = "sRGB"
            emi.image = ei; has_emi = True
        clip = m["floats"].get("_AlphaCutoff", 0.5) if "HEX_ALPHA_CLIP_ENABLED" in kw else None
        if m.get("shader") != "Hex/Lit":
            mat.name = "SKIP_" + mat.name     # VFX-only material (e.g. magic/Fresnel): not drawn in the relight
            tr = nt.nodes.new("ShaderNodeBsdfTransparent")
            nt.links.new(tr.outputs[0], next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL").inputs["Surface"])
            switches.append(None)
        else:
            switches.append(hexlit_material(nt, tex, emi, clip))
        try:
            mat.surface_render_method = "DITHERED"
        except AttributeError:
            pass
        me.materials.append(mat)
    tris = int(len(tri))
    return [ob], (lambda v: [s(v) for s in switches if s]), has_emi, tris, meta


def build_ours(job):
    sc = bpy.context.scene
    sc.frame_set(int(job["frame"]))
    meshes = [o for o in sc.objects if o.type == "MESH" and not o.hide_render and o.data.materials]
    slots, uses = [], []
    for m in {m for o in meshes for m in o.data.materials if m and m.use_nodes}:
        nt = m.node_tree
        imgs = [n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image]
        if not imgs:
            continue
        tex = max(imgs, key=lambda n: n.image.size[0] * n.image.size[1])
        uses.append(hexlit_material(nt, tex))
        try:
            m.blend_method = "OPAQUE"
        except (AttributeError, TypeError):
            pass
        slots.append(tex)
    if not slots:
        raise SystemExit("no textured material found")
    looks = {k: bpy.data.images.load(v) for k, v in job["looks"].items()}
    for im in looks.values():
        im.colorspace_settings.name = "sRGB"
    deps = bpy.context.evaluated_depsgraph_get()
    tris = sum(sum(len(p.vertices) - 2 for p in o.evaluated_get(deps).data.polygons) for o in meshes)
    front = Vector(job["front"]).normalized()     # unit-look metrics lighting.frontResolved.vector
    return meshes, uses, slots, looks, tris, front


def main(argv):
    job = json.load(open(argv[argv.index("--job") + 1]))
    os.makedirs(job["out"], exist_ok=True)
    if job["kind"] == "native":
        for o in list(bpy.data.objects):      # factory startup: the default cube / camera / light
            bpy.data.objects.remove(o, do_unlink=True)
    sc, sun = setup_scene(int(job.get("res", 1600)))
    if job["kind"] == "native":
        objs, use_all, has_emi, tris, nmeta = build_native(job["native"])
        variants = ["lit", "albedo"] + (["emi"] if has_emi else [])
        front = Vector((0, 1, 0))                      # Unity +Z (the prefab's forward) after the y/z swap
        looks = None
    else:
        objs, uses, slots, looks, tris, front = build_ours(job)
        use_all = lambda v: [u("albedo" if v == "albedo" else "lit") for u in uses]
        variants = list(job["looks"]) + ["albedo"]
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        ev = o.evaluated_get(deps)
        pts += [o.matrix_world @ v.co for v in ev.data.vertices]
    P = np.array([[p.x, p.y, p.z] for p in pts])
    lo, hi = P.min(0), P.max(0)
    centre = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] + (hi[2] - lo[2]) * 0.5))
    ground = float(lo[2])
    # blend units per battle world unit: fitted to the battle height (ours: the runtime hex fit at the idle pose)
    s = float(hi[2] - lo[2]) / float(job["targetHeight"]) if job.get("targetHeight") else 1.0
    cd = bpy.data.cameras.new("cmp"); cd.type = "ORTHO"; cd.ortho_scale = float(job["ortho"]) * s
    cam = bpy.data.objects.new("cmp", cd); sc.collection.objects.link(cam); sc.camera = cam
    up = Vector((0, 0, 1))
    look0 = up.cross(front).normalized()          # camera looks along look0 -> front is screen-right
    # every view is centred on the same point: half the pair's ortho height above the ground
    aim = Vector((centre.x, centre.y, ground + float(job["ortho"]) * s * 0.42))

    def place(look_h, elev):
        e = math.radians(elev)
        d = (look_h * math.cos(e) - up * math.sin(e)).normalized()
        cam.location = aim - d * 50 * s * float(job["ortho"])
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cd.clip_end = 200 * s * float(job["ortho"])
        bpy.context.view_layer.update()
        ux, uy, uz = ARENA_SUNS[job.get("cond", "sand")]
        m = cam.matrix_world.to_3x3()
        right, fwd = (m @ Vector((1, 0, 0))).normalized(), (m @ Vector((0, 0, -1))).normalized()
        rh = Vector((right.x, right.y, 0)).normalized(); fh = Vector((fwd.x, fwd.y, 0)).normalized()
        travel = (rh * ux + fh * uz + up * uy).normalized()
        sun.rotation_euler = travel.to_track_quat("-Z", "Y").to_euler()

    def rot(v, deg):
        a = math.radians(deg)
        return Vector((v.x * math.cos(a) - v.y * math.sin(a), v.x * math.sin(a) + v.y * math.cos(a), 0))

    views = {"battle": (look0, 40.0), "front34": (rot(-front, -45.0), 15.0)}
    for i in range(8):
        views[f"turn_{i}"] = (rot(look0, 45.0 * i), 30.0)
    for var in variants:
        if looks is not None and var in looks:
            for t in slots:
                t.image = looks[var]
        use_all(var)
        vset = views if var == "lit" else {k: views[k] for k in ("battle", "front34")}
        for vn, (lh, el) in vset.items():
            place(lh, el)
            sc.render.filepath = os.path.join(job["out"], f"{var}_{vn}.png")
            bpy.ops.render.render(write_still=True)
    json.dump({"triangles": tris, "boundsBattle": {"min": (lo / s).tolist(), "max": (hi / s).tolist()},
               "heightBattle": float((hi[2] - lo[2]) / s), "widthBattleXY": float(max(hi[0] - lo[0], hi[1] - lo[1]) / s),
               "ortho": job["ortho"], "res": job.get("res", 1600), "variants": variants,
               "front": [front.x, front.y, front.z]},
              open(os.path.join(job["out"], "render_meta.json"), "w"), indent=1)
    print("STYLE_RENDER_OK")


main(sys.argv[sys.argv.index("--") + 1:])
