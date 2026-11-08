#!/usr/bin/env python3
"""
Blender: pack a crude albedo onto an untextured GLB so Meshy auto-rig will accept it.

  blender -b --python texture_for_rig.py -- --mode sprite|master|solid \\
    --input in.glb --output out.glb [--sprite frame.png] [--master master.glb]
"""
from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {
        "mode": None,
        "input": None,
        "output": None,
        "sprite": None,
        "master": None,
        "textureSize": 512,
    }
    i = 0
    while i < len(args):
        if args[i] in {"--mode", "--input", "--output", "--sprite", "--master"} and i + 1 < len(args):
            key = args[i][2:]
            out[key] = Path(args[i + 1]) if key != "mode" else args[i + 1]
            i += 2
        elif args[i] == "--textureSize" and i + 1 < len(args):
            out["textureSize"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["mode"] or not out["input"] or not out["output"]:
        raise SystemExit("need --mode --input --output")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_glb(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh in {path}")
    return meshes


def _ensure_uv(mesh_obj) -> None:
    me = mesh_obj.data
    if me.uv_layers:
        return
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


def _new_image(name: str, size: int):
    img = bpy.data.images.new(name, width=size, height=size, alpha=True)
    img.pixels = [0.2, 0.2, 0.2, 1.0] * (size * size)
    return img


def _assign_image_material(mesh_obj, img) -> None:
    mat = bpy.data.materials.new(name="RigAlbedo")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mesh_obj.data.materials.clear()
    mesh_obj.data.materials.append(mat)
    # Active image for bake target
    for n in nodes:
        if n.type == "TEX_IMAGE":
            nodes.active = n
            break


def _bbox(objs):
    pts = []
    for o in objs:
        for corner in o.bound_box:
            pts.append(o.matrix_world @ Vector(corner))
    arr = np.array([[p.x, p.y, p.z] for p in pts], dtype=np.float64)
    return arr.min(axis=0), arr.max(axis=0)


def _paint_solid(mesh_obj, img) -> None:
    """Height / lateral bands: head / torso / legs / left-right limbs — rig-readable only."""
    size = img.size[0]
    pixels = np.zeros((size, size, 4), dtype=np.float32)
    pixels[..., 3] = 1.0
    me = mesh_obj.data
    uv = me.uv_layers.active.data
    mn, mx = _bbox([mesh_obj])
    span = np.maximum(mx - mn, 1e-6)

    # Per-loop color from vertex world pos
    for poly in me.polygons:
        cols = []
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            co = mesh_obj.matrix_world @ me.vertices[vi].co
            t = (np.array([co.x, co.y, co.z]) - mn) / span
            z, x = float(t[2]), float(t[0])
            if z > 0.72:
                c = (0.95, 0.2, 0.2)  # head
            elif z < 0.35:
                c = (0.2, 0.85, 0.25)  # legs
            elif x < 0.28:
                c = (0.2, 0.35, 0.95)  # leftish
            elif x > 0.72:
                c = (0.95, 0.85, 0.15)  # rightish
            else:
                c = (0.85, 0.55, 0.25)  # torso
            cols.append(c)
        # paint UV pixels for this poly (sample loop uvs)
        for li in poly.loop_indices:
            u, v = uv[li].uv
            px = int(np.clip(u * (size - 1), 0, size - 1))
            py = int(np.clip(v * (size - 1), 0, size - 1))
            # average poly color
            r = sum(c[0] for c in cols) / len(cols)
            g = sum(c[1] for c in cols) / len(cols)
            b = sum(c[2] for c in cols) / len(cols)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    xx = int(np.clip(px + dx, 0, size - 1))
                    yy = int(np.clip(py + dy, 0, size - 1))
                    pixels[yy, xx, :3] = (r, g, b)
    # fill empty with torso tone
    empty = pixels[..., 0] + pixels[..., 1] + pixels[..., 2] < 1e-4
    pixels[empty, 0] = 0.5
    pixels[empty, 1] = 0.4
    pixels[empty, 2] = 0.3
    flat = pixels.reshape(-1)
    img.pixels = flat.tolist()
    img.update()


def _paint_sprite(mesh_obj, img, sprite_path: Path) -> None:
    """Orthographic side projection of mesh onto sprite bbox (crude)."""
    loaded = bpy.data.images.load(str(sprite_path))
    sw, sh = int(loaded.size[0]), int(loaded.size[1])
    flat = np.array(loaded.pixels[:], dtype=np.float32).reshape(sh, sw, 4)
    # Blender image pixels are bottom-up; flip to top-left sampling space.
    sprite = flat[::-1, :, :]
    size = img.size[0]
    pixels = np.zeros((size, size, 4), dtype=np.float32)
    pixels[..., 3] = 1.0
    me = mesh_obj.data
    uv = me.uv_layers.active.data
    mn, mx = _bbox([mesh_obj])
    # Side view: Y horizontal, Z vertical (glTF Y-up after import)
    y0, y1 = float(mn[1]), float(mx[1])
    z0, z1 = float(mn[2]), float(mx[2])
    ys = max(1e-6, y1 - y0)
    zs = max(1e-6, z1 - z0)

    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            co = mesh_obj.matrix_world @ me.vertices[vi].co
            u_sp = (co.y - y0) / ys
            v_sp = (co.z - z0) / zs
            sx = int(np.clip(u_sp * (sw - 1), 0, sw - 1))
            sy = int(np.clip((1.0 - v_sp) * (sh - 1), 0, sh - 1))
            col = sprite[sy, sx]
            if col[3] < 0.05:
                col = np.array([0.45, 0.45, 0.45, 1.0], dtype=np.float32)
            uu, vv = uv[li].uv
            px = int(np.clip(uu * (size - 1), 0, size - 1))
            py = int(np.clip(vv * (size - 1), 0, size - 1))
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    xx = int(np.clip(px + dx, 0, size - 1))
                    yy = int(np.clip(py + dy, 0, size - 1))
                    pixels[yy, xx, :3] = col[:3]
                    pixels[yy, xx, 3] = 1.0
    empty = pixels[..., 0] + pixels[..., 1] + pixels[..., 2] < 1e-4
    pixels[empty, :3] = 0.4
    img.pixels = pixels.reshape(-1).tolist()
    img.update()


def _bake_from_master(target_meshes, master_path: Path, img, size: int) -> None:
    """Selected-to-active diffuse bake from master mesh onto first target."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(master_path))
    master_meshes = [o for o in bpy.data.objects if o.type == "MESH" and o not in before]
    if not master_meshes:
        raise RuntimeError("master has no mesh")
    source = master_meshes[0]
    target = target_meshes[0]
    # Hide extras
    for o in master_meshes[1:]:
        o.hide_render = True

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.cycles.bake_type = "DIFFUSE"
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.use_pass_color = True
    scene.render.bake.margin = 4

    _ensure_uv(target)
    _assign_image_material(target, img)

    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    try:
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, cage_extrusion=0.08)
    except Exception as e:
        print(f"[texture_for_rig] bake failed ({e}); falling back to solid bands", flush=True)
        _paint_solid(target, img)
    img.filepath_raw = ""
    img.file_format = "PNG"


def _export(path: Path, mesh_objs) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs:
        o.select_set(True)
        # also select parents / armatures if any
        if o.parent:
            o.parent.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_apply=False,
    )


def run(opts: dict) -> None:
    _clear()
    meshes = _import_glb(Path(opts["input"]))
    for m in meshes:
        _ensure_uv(m)
    target = meshes[0]
    size = int(opts["textureSize"])
    img = _new_image("rig_albedo", size)
    mode = str(opts["mode"])

    if mode == "solid":
        _assign_image_material(target, img)
        _paint_solid(target, img)
    elif mode == "sprite":
        if not opts["sprite"]:
            raise RuntimeError("--sprite required for sprite mode")
        _assign_image_material(target, img)
        _paint_sprite(target, img, Path(opts["sprite"]))
    elif mode == "master":
        if not opts["master"]:
            raise RuntimeError("--master required for master mode")
        _bake_from_master(meshes, Path(opts["master"]), img, size)
    else:
        raise RuntimeError(f"unknown mode {mode}")

    # Pack image into material (already assigned)
    _export(Path(opts["output"]), meshes)
    print(json_dumps_ok(Path(opts["output"])), flush=True)


def json_dumps_ok(path: Path) -> str:
    import json

    return json.dumps({"ok": True, "output": str(path).replace("\\", "/")})


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
