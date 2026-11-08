#!/usr/bin/env python3
"""
Blender: visualize nearest-bone map from two cameras.

  blender -b --python visualize_bone_map.py -- \\
    --master master.glb --donor donor_rigged.glb --map-json bone_map.json \\
    --output bone_map_2cam.png [--fit-report fit_report.json]
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {
        "master": None,
        "donor": None,
        "mapJson": None,
        "output": None,
        "fitReport": None,
        "maxDist": 0.35,
    }
    i = 0
    while i < len(args):
        key = {
            "--master": "master",
            "--donor": "donor",
            "--map-json": "mapJson",
            "--output": "output",
            "--fit-report": "fitReport",
            "--max-dist": "maxDist",
        }.get(args[i])
        if key and i + 1 < len(args):
            if key == "maxDist":
                out[key] = float(args[i + 1])
            else:
                out[key] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["master"] or not out["donor"] or not out["mapJson"] or not out["output"]:
        raise SystemExit("need --master --donor --map-json --output")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_arm(path: Path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in objs if o.type == "ARMATURE")
    for o in objs:
        if o.type == "MESH":
            o.hide_render = True
            o.hide_viewport = True
    return arm


def _bone_heads(arm) -> dict[str, Vector]:
    out = {}
    for pb in arm.pose.bones:
        out[pb.name] = arm.matrix_world @ pb.head
    return out


def _pick_anchor(heads: dict[str, Vector]) -> str:
    for cand in ("Bone_002", "Bone_000", "Hips", "mixamorig:Hips", "pelvis"):
        if cand in heads:
            return cand
    return min(heads.keys(), key=lambda n: heads[n].z)


def _extremity_pts(heads: dict[str, Vector]) -> np.ndarray:
    names = list(heads.keys())
    pts = np.array([[heads[n].x, heads[n].y, heads[n].z] for n in names], dtype=np.float64)
    idxs = []
    for axis in range(3):
        idxs.append(int(np.argmin(pts[:, axis])))
        idxs.append(int(np.argmax(pts[:, axis])))
    uniq = []
    for i in idxs:
        if i not in uniq:
            uniq.append(i)
    return pts[uniq]


def _rigid_align(src: np.ndarray, dst: np.ndarray):
    src_mu = src.mean(axis=0)
    dst_mu = dst.mean(axis=0)
    X = src - src_mu
    Y = dst - dst_mu
    src_scale = np.linalg.norm(X) / math.sqrt(max(1, X.shape[0]))
    dst_scale = np.linalg.norm(Y) / math.sqrt(max(1, Y.shape[0]))
    scale = float(dst_scale / max(src_scale, 1e-8))
    Xn = X / max(src_scale, 1e-8)
    Yn = Y / max(dst_scale, 1e-8)
    H = Xn.T @ Yn
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = dst_mu - scale * (src_mu @ R.T)
    return R, scale, t


def _apply_align(arm, R, scale, t) -> None:
    M = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            M[i][j] = float(R[i, j]) * scale
        M[i][3] = float(t[i])
    arm.matrix_world = Matrix(M) @ arm.matrix_world
    bpy.context.view_layer.update()


def _align_donor(master, donor, fit: dict | None) -> None:
    m_heads = _bone_heads(master)
    d_heads = _bone_heads(donor)
    m_anchor = _pick_anchor(m_heads)
    d_anchor = _pick_anchor(d_heads)
    delta = m_heads[m_anchor] - d_heads[d_anchor]
    donor.location = donor.location + delta
    bpy.context.view_layer.update()
    d_heads = _bone_heads(donor)
    if fit and "align" in fit:
        R = np.array(fit.get("align", {}).get("R") or np.eye(3), dtype=np.float64)
        # fit_report may only have scale/t — recompute if no R
        if "R" not in (fit.get("align") or {}):
            src = _extremity_pts(d_heads)
            dst = _extremity_pts(m_heads)
            n = min(len(src), len(dst))
            R, scale, t = _rigid_align(src[:n], dst[:n])
        else:
            scale = float(fit["align"]["scale"])
            t = np.array(fit["align"]["t"], dtype=np.float64)
            R = np.array(fit["align"]["R"], dtype=np.float64)
        _apply_align(donor, R, scale, t)
    else:
        src = _extremity_pts(d_heads)
        dst = _extremity_pts(m_heads)
        n = min(len(src), len(dst))
        R, scale, t = _rigid_align(src[:n], dst[:n])
        _apply_align(donor, R, scale, t)


def _make_sphere(name: str, loc: Vector, radius: float, color: tuple[float, float, float]):
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    # Icosphere via ops is slow; use UV sphere primitive once
    bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=8, radius=radius, location=loc)
    sph = bpy.context.active_object
    sph.name = name
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emis = nodes.new("ShaderNodeEmission")
    emis.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    emis.inputs["Strength"].default_value = 3.0
    mat.node_tree.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    sph.data.materials.append(mat)
    # remove unused empty mesh obj if created
    if obj.name in bpy.data.objects and obj != sph:
        bpy.data.objects.remove(obj, do_unlink=True)
    return sph


def _make_line(name: str, a: Vector, b: Vector, color: tuple[float, float, float], radius: float = 0.008):
    mid = (a + b) * 0.5
    direction = b - a
    length = direction.length
    if length < 1e-8:
        return None
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=length, location=mid)
    cyl = bpy.context.active_object
    cyl.name = name
    cyl.rotation_mode = "QUATERNION"
    cyl.rotation_quaternion = direction.to_track_quat("Z", "Y")
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree.nodes
    nt.clear()
    out = nt.new("ShaderNodeOutputMaterial")
    emis = nt.new("ShaderNodeEmission")
    emis.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    emis.inputs["Strength"].default_value = 2.5
    mat.node_tree.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    cyl.data.materials.append(mat)
    return cyl


def _draw_armature_bones(arm, color: tuple[float, float, float], prefix: str, radius: float):
    heads = _bone_heads(arm)
    for pb in arm.pose.bones:
        h = heads[pb.name]
        t = arm.matrix_world @ pb.tail
        _make_sphere(f"{prefix}_j_{pb.name}", h, radius, color)
        _make_line(f"{prefix}_b_{pb.name}", h, t, color, radius * 0.45)


def _setup_camera(name: str, loc: Vector, look_at: Vector, ortho_scale: float):
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = loc
    direction = look_at - loc
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam


def _render_cam(cam, path: Path, res: int = 768) -> None:
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    # dark bg
    world = bpy.data.worlds.new("VizWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.05, 0.07, 1.0)
    bg.inputs[1].default_value = 1.0
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)


def run(opts: dict) -> dict:
    _clear()
    master = _import_arm(Path(opts["master"]))
    donor = _import_arm(Path(opts["donor"]))
    mapping = json.loads(Path(opts["mapJson"]).read_text(encoding="utf-8"))
    pairs = mapping.get("mapping") or {}
    fit = None
    if opts.get("fitReport") and Path(opts["fitReport"]).is_file():
        fit = json.loads(Path(opts["fitReport"]).read_text(encoding="utf-8"))

    # Hide original armature render clutter; draw overlays
    master.hide_render = True
    donor.hide_render = True
    _align_donor(master, donor, fit)
    bpy.context.view_layer.update()

    _draw_armature_bones(master, (0.25, 0.75, 1.0), "M", 0.018)  # cyan = master
    _draw_armature_bones(donor, (1.0, 0.55, 0.15), "D", 0.016)  # orange = donor

    m_heads = _bone_heads(master)
    d_heads = _bone_heads(donor)
    for mi, (mb, db) in enumerate(pairs.items()):
        if mb not in m_heads or db not in d_heads:
            continue
        # green = mapped link
        _make_line(f"link_{mi}_{mb}", m_heads[mb], d_heads[db], (0.2, 1.0, 0.35), 0.006)

    # Scene bounds for framing
    pts = list(m_heads.values()) + list(d_heads.values())
    arr = np.array([[p.x, p.y, p.z] for p in pts], dtype=np.float64)
    center = Vector(arr.mean(axis=0).tolist())
    span = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))
    dist = max(2.2, span * 1.35)
    ortho = max(2.0, span * 1.25)

    cam_side = _setup_camera(
        "CamSide",
        Vector((center.x - dist, center.y, center.z + span * 0.05)),
        center,
        ortho,
    )
    cam_front = _setup_camera(
        "CamFront",
        Vector((center.x, center.y - dist, center.z + span * 0.08)),
        center,
        ortho,
    )

    # Key light
    light_data = bpy.data.lights.new(name="Key", type="SUN")
    light_data.energy = 1.2
    light = bpy.data.objects.new("Key", light_data)
    bpy.context.collection.objects.link(light)
    light.rotation_euler = Euler((math.radians(40), math.radians(20), math.radians(10)), "XYZ")

    out = Path(opts["output"])
    tmp = out.parent / "_bone_map_views"
    tmp.mkdir(parents=True, exist_ok=True)
    side_png = tmp / "side.png"
    front_png = tmp / "front.png"
    _render_cam(cam_side, side_png)
    _render_cam(cam_front, front_png)

    # Composite with labels via numpy/PIL if available; else bpy images
    try:
        from PIL import Image, ImageDraw

        a = Image.open(side_png).convert("RGB")
        b = Image.open(front_png).convert("RGB")
        w, h = a.size
        pad = 48
        canvas = Image.new("RGB", (w * 2 + 24, h + pad), (12, 12, 16))
        canvas.paste(a, (8, pad))
        canvas.paste(b, (w + 16, pad))
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 12), "Bone map — side (-X)  |  cyan=master  orange=donor  green=link", fill=(220, 220, 220))
        draw.text((w + 20, 12), "Bone map — front (-Y)", fill=(220, 220, 220))
        canvas.save(out)
    except Exception:
        # Fallback: just copy side if PIL missing
        bpy.data.images.load(str(side_png)).save_render(str(out))

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out).replace("\\", "/"),
                "mappedLinks": len(pairs),
                "side": str(side_png).replace("\\", "/"),
                "front": str(front_png).replace("\\", "/"),
            },
            indent=2,
        ),
        flush=True,
    )
    return {"ok": True, "output": str(out)}


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
