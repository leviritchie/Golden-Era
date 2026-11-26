"""Render Hex/Lit Full-PBR QA tile previews matching Olden Era's pure-diffuse shader via gpu_gate.

Usage:
  python V:/scratch_claude/unit_rebuild/_fortress_coord/gpu_gate.py --slots 2 --min-vram 3200 -- ^
    V:/Tools/blender-mcp/blender-5.2.2/blender.exe -b --python-exit-code 1 --python ^
    tools/homm3_retexture_pbr/render_batch_qa.py -- --work-dir <dir> --units u1,u2 [--shipped-root <dir>]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

DEFAULT_REBUILD_ROOT = Path("V:/scratch_claude/unit_rebuild")
TILE_RES = 448


def setup_scene(samples: int = 20) -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 3
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 1
    sc.render.resolution_x = TILE_RES
    sc.render.resolution_y = TILE_RES
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0

    world = bpy.data.worlds.new("qa_world")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputWorld")
    lpath = nt.nodes.new("ShaderNodeLightPath")
    mix_bg = nt.nodes.new("ShaderNodeMixShader")
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_cam.inputs["Color"].default_value = (0.028, 0.030, 0.028, 1.0)
    bg_cam.inputs["Strength"].default_value = 1.0
    bg_env = nt.nodes.new("ShaderNodeBackground")
    bg_env.inputs["Color"].default_value = (0.78, 0.87, 1.0, 1.0)
    bg_env.inputs["Strength"].default_value = 0.55
    nt.links.new(lpath.outputs["Is Camera Ray"], mix_bg.inputs["Fac"])
    nt.links.new(bg_env.outputs[0], mix_bg.inputs[1])
    nt.links.new(bg_cam.outputs[0], mix_bg.inputs[2])
    nt.links.new(mix_bg.outputs[0], out_n.inputs[0])

    for name, loc, energy, col, ang in [
        ("key_sun", (3.5, -4.5, 5.0), 2.4, (1.0, 0.96, 0.88), 8.0),
        ("fill_sun", (-4.0, -1.5, 2.5), 0.75, (0.76, 0.88, 1.0), 25.0),
        ("rim_sun", (-1.5, 4.5, 3.2), 0.70, (0.85, 0.92, 1.0), 15.0),
    ]:
        ld = bpy.data.lights.new(name, "SUN")
        ld.energy = energy
        ld.color = col
        ld.angle = math.radians(ang)
        lo = bpy.data.objects.new(name, ld)
        sc.collection.objects.link(lo)
        lo.location = Vector(loc)
        lo.rotation_euler = (-Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return sc


def _select_body_mesh(unit: str) -> bpy.types.Object:
    large = [
        o for o in bpy.data.objects
        if o.type == "MESH" and len(o.data.vertices) > 500 and not o.name.lower().endswith("_rubble")
    ]
    if len(large) == 1:
        return large[0]
    named = [o for o in large if o.name in ("body", unit)]
    if len(named) == 1:
        return named[0]
    raise RuntimeError(f"{unit}: ambiguous body meshes {[o.name for o in large]}")


def build_diffuse_hexlit_mat(name: str, basecolor_path: Path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.0
    bsdf.inputs["Metallic"].default_value = 0.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(basecolor_path.resolve()), check_existing=True)
    tex.image.colorspace_settings.name = "sRGB"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs[0], out_n.inputs[0])
    return mat


def build_full_pbr_mat(name: str, out_dir: Path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out_n.inputs[0])

    tex_c = nt.nodes.new("ShaderNodeTexImage")
    tex_c.image = bpy.data.images.load(str(out_dir / "basecolor_albedo.png"), check_existing=True)
    tex_c.image.colorspace_settings.name = "sRGB"
    nt.links.new(tex_c.outputs["Color"], bsdf.inputs["Base Color"])

    tex_mg = nt.nodes.new("ShaderNodeTexImage")
    tex_mg.image = bpy.data.images.load(str(out_dir / "metallicgloss.png"), check_existing=True)
    tex_mg.image.colorspace_settings.name = "Non-Color"
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(tex_mg.outputs["Alpha"], inv.inputs[1])
    nt.links.new(inv.outputs[0], bsdf.inputs["Roughness"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tex_mg.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])

    tex_n = nt.nodes.new("ShaderNodeTexImage")
    tex_n.image = bpy.data.images.load(str(out_dir / "normal.png"), check_existing=True)
    tex_n.image.colorspace_settings.name = "Non-Color"
    nrm = nt.nodes.new("ShaderNodeNormalMap")
    nrm.inputs["Strength"].default_value = 0.85
    nt.links.new(tex_n.outputs["Color"], nrm.inputs["Color"])
    nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def render_unit_tiles(
    sc: bpy.types.Scene,
    unit: str,
    work_dir: Path,
    rebuild_root: Path,
    shipped_root: Path | None,
    compare_pbr: bool = False,
    source_slice_root: Path | None = None,
) -> list[Path]:
    for o in list(bpy.data.objects):
        if o.type in ("MESH", "ARMATURE", "EMPTY"):
            bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)

    if source_slice_root is not None:
        glb = source_slice_root / unit / "inputs/look_delivered.glb"
        if not glb.is_file():
            raise FileNotFoundError(f"{unit}: source slice GLB missing: {glb}")
    else:
        glb = rebuild_root / unit / "out" / f"{unit}.glb"
        if not glb.is_file():
            raise FileNotFoundError(f"{unit}: rebuild GLB missing: {glb}")
    bpy.ops.import_scene.gltf(filepath=str(glb))
    body = _select_body_mesh(unit)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    for o in bpy.data.objects:
        if (o.type == "MESH" and o != body) or o.type == "ARMATURE":
            o.hide_render = True
    if arms:
        arm = arms[0]
        ac = bpy.data.actions["Unit_Idle"]
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = ac
        if hasattr(arm.animation_data, "action_slot") and ac.slots:
            arm.animation_data.action_slot = ac.slots[0]
    sc.frame_set(0)
    bpy.context.view_layer.update()

    deps = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(deps)
    pts = np.array([(body.matrix_world @ v.co)[:] for v in ev.data.vertices], dtype=np.float32)
    bmin, bmax = pts.min(axis=0), pts.max(axis=0)
    c = 0.5 * (bmin + bmax)
    ext = bmax - bmin
    oscale = float(max(ext) * 1.15)
    meta = json.loads((work_dir / unit / "views/meta.json").read_text(encoding="utf-8"))
    hc = Vector(meta["headCenter"])
    hscale = float(meta["headScale"])

    cam = sc.camera
    cam.data.type = "ORTHO"
    views = [
        ("front_34", Vector(c.tolist()), Vector(c.tolist()) + Vector((3.8, -4.4, 2.1)), oscale),
        ("rear_34",  Vector(c.tolist()), Vector(c.tolist()) + Vector((-3.8, 4.4, 2.3)), oscale),
        ("head",     hc,                 hc + Vector((2.6, -3.2, 0.9)),                 hscale),
    ]

    ship_tex = (shipped_root / unit / "inputs/basecolor.png") if shipped_root else Path("__nonexistent__")
    if not ship_tex.is_file() and source_slice_root is not None:
        ship_tex = source_slice_root / unit / "inputs/basecolor.png"
    if not ship_tex.is_file():
        ship_tex = rebuild_root / unit / "tex/basecolor.png"
    u_out = work_dir / unit / "out"
    mats = [
        ("shipped", build_diffuse_hexlit_mat(f"{unit}_ship", ship_tex)),
        ("hexlit_pbr", build_diffuse_hexlit_mat(f"{unit}_hexpbr", u_out / "basecolor_hexlit_pbr.png")),
    ]
    if compare_pbr:
        mats.append(("cycles_pbr", build_full_pbr_mat(f"{unit}_cycpbr", u_out)))

    tdir = work_dir / unit / "renders/qa_tiles"
    tdir.mkdir(parents=True, exist_ok=True)
    out_paths = []
    for vname, tgt, loc, sc_val in views:
        cam.location = loc
        cam.data.ortho_scale = sc_val
        cam.rotation_euler = (tgt - loc).normalized().to_track_quat("-Z", "Y").to_euler()
        for mname, mat in mats:
            body.data.materials[0] = mat
            p = tdir / f"{vname}_{mname}.png"
            sc.render.filepath = str(p)
            bpy.ops.render.render(write_still=True)
            out_paths.append(p)
    return out_paths


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--units", required=True)
    ap.add_argument("--rebuild-root", type=Path, default=DEFAULT_REBUILD_ROOT)
    ap.add_argument("--source-slice-root", type=Path, default=None)
    ap.add_argument("--shipped-root", type=Path, default=None)
    ap.add_argument("--compare-pbr", action="store_true")
    args = ap.parse_args(argv)
    work_dir = args.work_dir.resolve()
    rebuild_root = args.rebuild_root.resolve()
    source_slice_root = args.source_slice_root.resolve() if args.source_slice_root else None
    shipped_root = args.shipped_root.resolve() if args.shipped_root else None

    t0 = time.perf_counter()
    sc = setup_scene(samples=20)
    cam_d = bpy.data.cameras.new("qa_cam")
    cam = bpy.data.objects.new("qa_cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam

    for u in [x.strip() for x in args.units.split(",") if x.strip()]:
        render_unit_tiles(
            sc,
            u,
            work_dir,
            rebuild_root,
            shipped_root,
            compare_pbr=args.compare_pbr,
            source_slice_root=source_slice_root,
        )
        print(f"Rendered QA tiles for {u}")
    print(f"render_batch_qa DONE in {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
