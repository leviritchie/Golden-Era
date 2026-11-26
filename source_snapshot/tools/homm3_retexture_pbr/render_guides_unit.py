"""Generalized 8-view calibrated guide & AOV renderer for any unit rebuild GLB.

Usage (under gpu_gate):
  python V:/scratch_claude/unit_rebuild/_fortress_coord/gpu_gate.py --slots 2 --min-vram 3200 -- ^
    V:/Tools/blender-mcp/blender-5.2.2/blender.exe -b --python-exit-code 1 --python ^
    tools/homm3_retexture_pbr/render_guides_unit.py -- --unit <unit> --work-dir <work_dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import bpy
import bmesh
import mathutils
import numpy as np
from mathutils import Vector

DEFAULT_REBUILD_ROOT = Path("V:/scratch_claude/unit_rebuild")
VIEW_RES = 1024
AO_BAKE_RES = 1024
UV_RES = 2048
BG_SRGB_U8 = 127


def setup_scene(samples: int = 24) -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type != "CPU"  # the CPU device in a hybrid OptiX render only adds contention (bench 2026-11-25)
    sc.cycles.use_denoising = True
    sc.cycles.denoising_use_gpu = True
    sc.render.use_persistent_data = True  # keep the Cycles session between the per-view renders
    sc.cycles.max_bounces = 4
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 1
    sc.cycles.transparent_max_bounces = 4
    sc.render.resolution_x = VIEW_RES
    sc.render.resolution_y = VIEW_RES
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0

    world = bpy.data.worlds.new("guide_world")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputWorld")
    bg_n = nt.nodes.new("ShaderNodeBackground")
    bg_n.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bg_n.inputs["Strength"].default_value = 0.85
    nt.links.new(bg_n.outputs[0], out_n.inputs[0])
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
    raise RuntimeError(
        f"{unit}: expected 1 body mesh, found {[(o.name, len(o.data.vertices)) for o in bpy.data.objects if o.type == 'MESH']}"
    )


def load_idle0_unit(
    unit: str,
    rebuild_root: Path,
    source_slice_root: Path | None = None,
) -> tuple[bpy.types.Object, list[np.ndarray]]:
    if source_slice_root is not None:
        glb = source_slice_root / unit / "inputs/look_delivered.glb"
        if not glb.is_file():
            raise FileNotFoundError(f"{unit}: source slice GLB missing: {glb}")
    else:
        glb = rebuild_root / unit / "out" / f"{unit}.glb"
        if not glb.is_file():
            raise FileNotFoundError(f"{unit}: rebuild GLB missing: {glb}")
    bpy.ops.import_scene.gltf(filepath=str(glb))
    src_obj = _select_body_mesh(unit)

    head_pts: list[np.ndarray] = []
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if arms:
        arm = arms[0]
        ac = bpy.data.actions.get("Unit_Idle")
        if ac is None:
            raise RuntimeError(f"{unit}: Unit_Idle missing in {glb}")
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = ac
        if hasattr(arm.animation_data, "action_slot") and ac.slots:
            arm.animation_data.action_slot = ac.slots[0]
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()

    if arms:
        arm = arms[0]
        for pb in arm.pose.bones:
            if "head" in pb.name.lower() and "jaw" not in pb.name.lower():
                wp = arm.matrix_world @ pb.center
                head_pts.append(np.array([wp.x, wp.y, wp.z], dtype=np.float32))

    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = src_obj.evaluated_get(deps)
    mesh_data = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=deps)
    static_obj = bpy.data.objects.new(f"{unit}_eval", mesh_data)
    bpy.context.collection.objects.link(static_obj)
    static_obj.matrix_world = src_obj.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    static_obj.select_set(True)
    bpy.context.view_layer.objects.active = static_obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    for o in list(bpy.data.objects):
        if o != static_obj:
            bpy.data.objects.remove(o, do_unlink=True)
    return static_obj, head_pts


def fix_inward_normals_if_needed(obj: bpy.types.Object, unit: str) -> tuple[bool, float]:
    """Check signed volume before AO bake and reverse faces outward if inside-out."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    verts = np.array([v.co[:] for v in bm.verts], dtype=np.float64)
    tris = np.array([[v.index for v in f.verts] for f in bm.faces], dtype=np.int64)
    if len(tris) == 0:
        bm.free()
        return False, 0.0
    vpos = verts[tris]
    svol = float((vpos[:, 0] * np.cross(vpos[:, 1], vpos[:, 2])).sum() / 6.0)
    bm.free()
    if svol >= 0.0:
        return False, svol

    print(f"  NOTE {unit}: negative signed mesh volume ({svol:.4f}); reversing faces outward BEFORE AO bake")
    bm_fix = bmesh.new()
    bm_fix.from_mesh(obj.data)
    bmesh.ops.reverse_faces(bm_fix, faces=bm_fix.faces)
    bm_fix.normal_update()
    bm_fix.to_mesh(obj.data)
    bm_fix.free()
    obj.data.update()
    return True, svol


def compute_head_framing(
    pts: np.ndarray,
    center: np.ndarray,
    ext: np.ndarray,
    bmin: np.ndarray,
    bmax: np.ndarray,
    head_pts: list[np.ndarray],
) -> tuple[np.ndarray, float]:
    """Frame single head bone tightly or union of multiple head bones for multi-headed units."""
    if len(head_pts) >= 2:
        pts_arr = np.stack(head_pts, axis=0)
        h_lo = pts_arr.min(axis=0) - max(0.18 * max(ext), 0.25)
        h_hi = pts_arr.max(axis=0) + max(0.18 * max(ext), 0.25)
        hm = np.all((pts >= h_lo[None, :]) & (pts <= h_hi[None, :]), axis=1)
        h_pts = pts[hm] if hm.sum() > 200 else pts_arr
        head_center = 0.5 * (h_pts.min(axis=0) + h_pts.max(axis=0))
        head_ext = h_pts.max(axis=0) - h_pts.min(axis=0)
        head_scale = float(max(head_ext[0], head_ext[2], 0.85) * 1.25)
        return head_center, head_scale

    hc_anchor = (
        head_pts[0]
        if len(head_pts) == 1
        else np.array([center[0], bmin[1] + 0.25 * ext[1], bmax[2] - 0.25 * ext[2]], dtype=np.float32)
    )
    hm = np.linalg.norm(pts - hc_anchor[None, :], axis=-1) < max(0.32 * max(ext), 0.55)
    h_pts = pts[hm] if hm.sum() > 100 else pts
    head_center = 0.5 * (h_pts.min(axis=0) + h_pts.max(axis=0))
    head_ext = h_pts.max(axis=0) - h_pts.min(axis=0)
    head_scale = float(max(max(head_ext) * 1.32, 0.42 * max(ext)))
    return head_center, head_scale


def add_soft_studio_lights(sc: bpy.types.Scene) -> None:
    for name, loc, energy, angle_deg in [
        ("key_top_front", (4.0, -4.0, 5.5), 1.35, 35.0),
        ("fill_left_back", (-4.5, 4.0, 4.0), 1.15, 40.0),
        ("fill_bottom", (0.5, -1.5, -5.0), 1.10, 45.0),
    ]:
        ldata = bpy.data.lights.new(name, "SUN")
        ldata.energy = energy
        ldata.angle = math.radians(angle_deg)
        lobj = bpy.data.objects.new(name, ldata)
        sc.collection.objects.link(lobj)
        lobj.location = Vector(loc)
        lobj.rotation_euler = (-Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def build_guide_material(
    obj: bpy.types.Object,
    unit: str,
    rebuild_root: Path,
    source_slice_root: Path | None = None,
) -> None:
    if source_slice_root is not None:
        tex_dir = source_slice_root / unit / "inputs"
        basecolor_p = tex_dir / "basecolor.png"
        if not basecolor_p.is_file():
            raise FileNotFoundError(f"{unit}: source slice basecolor.png missing: {basecolor_p}")
    else:
        tex_dir = rebuild_root / unit / "tex"
        basecolor_p = tex_dir / "basecolor.png"
        if not basecolor_p.is_file():
            raise FileNotFoundError(f"{unit}: rebuild basecolor.png missing: {basecolor_p}")
    mat = bpy.data.materials.new("guide_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.62
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.35

    tex_albedo = nt.nodes.new("ShaderNodeTexImage")
    tex_albedo.image = bpy.data.images.load(str(basecolor_p), check_existing=True)

    gamma_n = nt.nodes.new("ShaderNodeGamma")
    gamma_n.inputs["Gamma"].default_value = 0.44
    nt.links.new(tex_albedo.outputs["Color"], gamma_n.inputs["Color"])

    ao_n = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao_n.samples = 12
    ao_n.inputs["Distance"].default_value = 0.25

    mix_clay = nt.nodes.new("ShaderNodeMix")
    mix_clay.data_type = "RGBA"
    mix_clay.inputs["Factor"].default_value = 0.35
    mix_clay.inputs["A"].default_value = (0.48, 0.48, 0.46, 1.0)
    nt.links.new(gamma_n.outputs["Color"], mix_clay.inputs["B"])

    mul_ao = nt.nodes.new("ShaderNodeMix")
    mul_ao.data_type = "RGBA"
    mul_ao.blend_type = "MULTIPLY"
    mul_ao.inputs["Factor"].default_value = 0.42
    nt.links.new(mix_clay.outputs["Result"], mul_ao.inputs["A"])
    nt.links.new(ao_n.outputs["AO"], mul_ao.inputs["B"])
    nt.links.new(mul_ao.outputs["Result"], bsdf.inputs["Base Color"])

    raw_nrm = tex_dir / "normal.png"
    if raw_nrm.is_file():
        tex_nrm = nt.nodes.new("ShaderNodeTexImage")
        tex_nrm.image = bpy.data.images.load(str(raw_nrm), check_existing=True)
        tex_nrm.image.colorspace_settings.name = "Non-Color"
        nrm_map = nt.nodes.new("ShaderNodeNormalMap")
        nrm_map.inputs["Strength"].default_value = 0.85
        nt.links.new(tex_nrm.outputs["Color"], nrm_map.inputs["Color"])
        nt.links.new(nrm_map.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out_n.inputs[0])
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def save_view_passes(
    sc: bpy.types.Scene,
    obj: bpy.types.Object,
    cam_inv: mathutils.Matrix,
    out_prefix: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sc.cycles.samples = 24
    sc.cycles.use_denoising = True
    sc.cycles.filter_width = 1.5
    sc.render.image_settings.color_depth = "8"
    tmp_rgba = str(out_prefix.with_name(out_prefix.name + "_rgba_tmp.png"))
    sc.render.filepath = tmp_rgba
    bpy.ops.render.render(write_still=True)

    im_rgba = bpy.data.images.load(tmp_rgba)
    rw, rh = im_rgba.size
    rgba = np.flipud(np.array(im_rgba.pixels[:], dtype=np.float32).reshape(rh, rw, 4)).copy()
    bpy.data.images.remove(im_rgba)
    alpha = np.clip(rgba[..., 3], 0.0, 1.0)
    rgb = np.clip(rgba[..., :3], 0.0, 1.0)
    comp = np.clip(rgb * alpha[..., None] + (BG_SRGB_U8 / 255.0) * (1.0 - alpha[..., None]), 0.0, 1.0)

    out_im = bpy.data.images.new(out_prefix.name + "_guide", width=rw, height=rh, alpha=False)
    out_rgba = np.ones((rh, rw, 4), dtype=np.float32)
    out_rgba[..., :3] = np.flipud(comp)
    out_im.pixels.foreach_set(out_rgba.ravel())
    out_im.filepath_raw = str(out_prefix.with_name(out_prefix.name + "_guide.png"))
    out_im.file_format = "PNG"
    out_im.save()
    bpy.data.images.remove(out_im)
    os.remove(tmp_rgba)

    orig_mat = obj.data.materials[0]
    tmp_mat = bpy.data.materials.new("aov_mat")
    tmp_mat.use_nodes = True
    nt = tmp_mat.node_tree
    nt.nodes.clear()
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(emit.outputs[0], out_n.inputs[0])

    world_bg = sc.world.node_tree.nodes["Background"]
    old_strength = world_bg.inputs["Strength"].default_value
    world_bg.inputs["Strength"].default_value = 0.0
    sc.cycles.samples = 1
    sc.cycles.use_denoising = False
    sc.cycles.filter_width = 0.01
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    sc.render.image_settings.color_mode = "RGBA"
    obj.data.materials[0] = tmp_mat

    def render_exr(node_output, tag: str) -> np.ndarray:
        nt.links.new(node_output, emit.inputs["Color"])
        exr_path = str(out_prefix.with_name(out_prefix.name + f"_{tag}.exr"))
        sc.render.filepath = exr_path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(exr_path)
        arr = np.array(img.pixels[:], dtype=np.float32).reshape(VIEW_RES, VIEW_RES, 4)
        bpy.data.images.remove(img)
        os.remove(exr_path)
        return np.flipud(arr).copy()

    pos_rgba = render_exr(geom.outputs["Position"], "pos")
    sh_nrm_rgba = render_exr(geom.outputs["Normal"], "snrm")

    world_bg.inputs["Strength"].default_value = old_strength
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    obj.data.materials[0] = orig_mat
    bpy.data.materials.remove(tmp_mat)

    hit = pos_rgba[..., 3] > 0.5
    pos_w = pos_rgba[..., :3]
    m_arr = np.array(cam_inv, dtype=np.float32)
    z_cam = -(m_arr[2, 0] * pos_w[..., 0] + m_arr[2, 1] * pos_w[..., 1] + m_arr[2, 2] * pos_w[..., 2] + m_arr[2, 3])
    depth = np.where(hit, z_cam, -1.0).astype(np.float32)
    nrm = sh_nrm_rgba[..., :3].astype(np.float32)
    n_len = np.linalg.norm(nrm, axis=-1, keepdims=True)
    nrm = np.where(hit[..., None] & (n_len > 1e-6), nrm / np.maximum(n_len, 1e-6), 0.0).astype(np.float32)
    return hit.astype(np.float32), depth, nrm


def bake_uv_ao(sc: bpy.types.Scene, obj: bpy.types.Object, out_path: Path) -> None:
    """Fast 1024x1024 Cycles AO bake (upsampled cleanly during projection)."""
    img = bpy.data.images.new("uv_ao_bake", width=AO_BAKE_RES, height=AO_BAKE_RES, alpha=False, float_buffer=False)
    mat = bpy.data.materials.new("ao_bake_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tex_node = nt.nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    nt.nodes.active = tex_node
    old_mat = obj.data.materials[0] if obj.data.materials else None
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    sc.cycles.samples = 16
    sc.cycles.use_denoising = True
    sc.render.bake.margin = 12
    sc.render.bake.margin_type = "EXTEND"
    bpy.ops.object.bake(type="AO")

    arr = np.array(img.pixels[:], dtype=np.float32).reshape(AO_BAKE_RES, AO_BAKE_RES, 4)[..., 0]
    arr = np.flipud(arr).copy()
    np.save(out_path, arr.astype(np.float32))

    if old_mat is not None:
        obj.data.materials[0] = old_mat
    else:
        obj.data.materials.clear()
    bpy.data.materials.remove(mat)
    bpy.data.images.remove(img)


def export_eval_mesh(obj: bpy.types.Object, out_path: Path) -> None:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    tri_mesh = bpy.data.meshes.new("tri_export")
    bm.to_mesh(tri_mesh)
    bm.free()

    verts = np.array([v.co[:] for v in tri_mesh.vertices], dtype=np.float32)
    tris = np.array([[p.vertices[0], p.vertices[1], p.vertices[2]] for p in tri_mesh.polygons], dtype=np.int32)
    uv_layer = tri_mesh.uv_layers.active.data
    cnorms = tri_mesh.corner_normals
    uvs = np.empty((len(tri_mesh.polygons), 3, 2), dtype=np.float32)
    lnorms = np.empty((len(tri_mesh.polygons), 3, 3), dtype=np.float32)
    for i, poly in enumerate(tri_mesh.polygons):
        for k, li in enumerate(poly.loop_indices):
            uvs[i, k] = uv_layer[li].uv[:]
            lnorms[i, k] = cnorms[li].vector[:]
    np.savez(out_path, verts=verts, tris=tris, uvs=uvs, lnorms=lnorms)
    bpy.data.meshes.remove(tri_mesh)


def compose_sheet(unit_root: Path, view_names: list[str], out_path: Path) -> None:
    arr = np.full((VIEW_RES * 2, VIEW_RES * 2, 4), 1.0, dtype=np.float32)
    arr[..., :3] = BG_SRGB_U8 / 255.0
    for i, vn in enumerate(view_names):
        im = bpy.data.images.load(str(unit_root / "views" / f"{vn}_guide.png"))
        tile = np.flipud(np.array(im.pixels[:], dtype=np.float32).reshape(VIEW_RES, VIEW_RES, 4))
        bpy.data.images.remove(im)
        r0 = (i // 2) * VIEW_RES
        c0 = (i % 2) * VIEW_RES
        arr[r0:r0 + VIEW_RES, c0:c0 + VIEW_RES, :3] = tile[..., :3]
    out_im = bpy.data.images.new(out_path.stem, width=VIEW_RES * 2, height=VIEW_RES * 2, alpha=False)
    out_im.pixels.foreach_set(np.flipud(arr).ravel())
    out_im.filepath_raw = str(out_path)
    out_im.file_format = "PNG"
    out_im.save()
    bpy.data.images.remove(out_im)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit", required=True)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--rebuild-root", type=Path, default=DEFAULT_REBUILD_ROOT)
    ap.add_argument("--source-slice-root", type=Path, default=None)
    ap.add_argument("--tertiary", action="store_true",
                    help="opt-in: also render the 4 low TERTIARY views + guide_sheet_tertiary.png")
    ap.add_argument("--tertiary-only", action="store_true",
                    help="opt-in: render only the TERTIARY views and append them to an existing views/meta.json")
    args = ap.parse_args(argv)
    unit = args.unit
    source_slice_root = args.source_slice_root.resolve() if args.source_slice_root else None

    t0 = time.perf_counter()
    u_root = args.work_dir / unit
    for sub in ("views", "proj", "out", "renders"):
        (u_root / sub).mkdir(parents=True, exist_ok=True)

    sc = setup_scene(samples=24)
    obj, head_pts = load_idle0_unit(unit, args.rebuild_root, source_slice_root=source_slice_root)
    flipped_normals, svol_before = fix_inward_normals_if_needed(obj, unit)

    pts = np.array([v.co[:] for v in obj.data.vertices], dtype=np.float32)
    bmin = pts.min(axis=0)
    bmax = pts.max(axis=0)
    center = 0.5 * (bmin + bmax)
    ext = bmax - bmin
    head_center, head_scale = compute_head_framing(pts, center, ext, bmin, bmax, head_pts)

    if not args.tertiary_only:
        export_eval_mesh(obj, u_root / "proj/eval_mesh.npz")
        bake_uv_ao(sc, obj, u_root / "proj/uv_ao.npy")

    add_soft_studio_lights(sc)
    build_guide_material(obj, unit, args.rebuild_root, source_slice_root=source_slice_root)

    cam_data = bpy.data.cameras.new("ortho_cam")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.1
    cam_data.clip_end = 50.0
    cam = bpy.data.objects.new("ortho_cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    body_scale = float(max(ext) * 1.16)
    c_vec = Vector(center.tolist())
    hc_vec = Vector(head_center.tolist())

    view_defs = [
        ("right",          Vector((1.0, 0.0, 0.06)),   c_vec,  body_scale, "Z"),
        ("left",           Vector((-1.0, 0.0, 0.06)),  c_vec,  body_scale, "Z"),
        ("front",          Vector((0.0, -1.0, 0.22)),  c_vec,  body_scale, "Z"),
        ("top",            Vector((0.0, 0.02, 1.0)),   c_vec,  body_scale, "NEG_Y"),
        ("front_right_34", Vector((0.82, -0.78, 0.42)), c_vec, body_scale, "Z"),
        ("rear_34",        Vector((-0.78, 0.78, 0.46)), c_vec, body_scale, "Z"),
        ("bottom",         Vector((0.0, -0.18, -1.0)), c_vec,  body_scale, "NEG_Y"),
        ("head_closeup",   Vector((0.72, -0.86, 0.24)), hc_vec, head_scale, "Z"),
    ]
    tertiary_defs = [   # opt-in low views (project_unit.TERTIARY_VIEWS)
        ("low_front",          Vector((0.0, -1.0, -0.40)),  c_vec, body_scale, "Z"),
        ("low_back",           Vector((0.0, 1.0, -0.40)),   c_vec, body_scale, "Z"),
        ("low_front_left_34",  Vector((-0.7, -0.7, -0.35)), c_vec, body_scale, "Z"),
        ("low_rear_right_34",  Vector((0.7, 0.7, -0.35)),   c_vec, body_scale, "Z"),
    ]
    if args.tertiary_only:
        meta_p = u_root / "views/meta.json"
        if not meta_p.is_file():
            raise FileNotFoundError(f"{unit}: --tertiary-only needs an existing {meta_p}")
        view_defs = tertiary_defs
    elif args.tertiary:
        view_defs = view_defs + tertiary_defs

    meta = {
        "unit": unit,
        "viewRes": VIEW_RES,
        "uvRes": UV_RES,
        "bgSrgb": BG_SRGB_U8,
        "flippedInwardNormals": flipped_normals,
        "signedVolumeBefore": float(svol_before),
        "headCenter": [float(x) for x in head_center],
        "headScale": head_scale,
        "views": {},
    }
    for vname, dvec, tgt, oscale, up_hint in view_defs:
        dir_n = dvec.normalized()
        loc = tgt + dir_n * 8.0
        cam.location = loc
        cam_data.ortho_scale = oscale
        forward = (tgt - loc).normalized()
        if up_hint == "Z":
            rot_q = forward.to_track_quat("-Z", "Y")
        else:
            z_ax = -forward
            up_v = Vector((0.0, -1.0, 0.0))
            x_ax = up_v.cross(z_ax).normalized()
            y_ax = z_ax.cross(x_ax).normalized()
            rot_q = mathutils.Matrix((x_ax, y_ax, z_ax)).transposed().to_quaternion()
        cam.rotation_euler = rot_q.to_euler()
        bpy.context.view_layer.update()

        cam_inv = cam.matrix_world.inverted()
        prefix = u_root / "views" / vname
        alpha_f, depth, nrm = save_view_passes(sc, obj, cam_inv, prefix)
        np.save(prefix.with_name(f"{vname}_alpha.npy"), alpha_f)
        np.save(prefix.with_name(f"{vname}_depth.npy"), depth)
        np.save(prefix.with_name(f"{vname}_nrm.npy"), nrm)

        meta["views"][vname] = {
            "orthoScale": oscale,
            "camLoc": [float(x) for x in cam.location],
            "camDir": [float(x) for x in forward],
            "worldToCam": [[float(c) for c in row] for row in cam_inv],
            "fgFraction": float((alpha_f > 0.5).mean()),
        }

    if args.tertiary_only:
        old = json.loads((u_root / "views/meta.json").read_text(encoding="utf-8"))
        old["views"].update(meta["views"])
        meta = old
    (u_root / "views/meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if not args.tertiary_only:
        compose_sheet(u_root, ["right", "left", "front", "top"], u_root / "views/guide_sheet_primary.png")
        compose_sheet(u_root, ["front_right_34", "rear_34", "bottom", "head_closeup"], u_root / "views/guide_sheet_secondary.png")
    if args.tertiary or args.tertiary_only:
        compose_sheet(u_root, [d[0] for d in tertiary_defs], u_root / "views/guide_sheet_tertiary.png")
    print(f"{unit}: render_guides_unit DONE in {time.perf_counter() - t0:.1f}s (bodyScale={body_scale:.2f} headScale={head_scale:.2f} flip={flipped_normals})")


if __name__ == "__main__":
    main()
