#!/usr/bin/env python3
"""Persistent Blender 3.5 JSONL worker for silhouette pose scoring.

Parent sends one JSON object per line on stdin; worker replies with one JSON
result per line on stdout. GLB import, materials, camera, and compositor stay
warm across candidates.

Default scoreMode is depth: soft IoU of monocular-predicted sprite depth vs
mesh Z (near=1). Preview shows tgtDepth | predDepth.
Optional scoreMode chroma keeps soft RGB L2. Search uses Workbench
FLAT+TEXTURE; proof stills use Eevee. No species-specific bone names.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

STATE = {}

ANATOMICAL_BONES = {
    "head": ["Bone_017", "Bone_027", "Bone_026", "Bone_029", "Bone_028"],
    "beak": ["Bone_027", "Bone_026", "Bone_029", "Bone_028"],
    "neck": ["Bone_019", "Bone_018", "Bone_017"],
    "torso": ["Bone_000", "Bone_001", "Bone_003"],
    "shoulder": ["Bone_002", "Bone_022", "Bone_025"],
    "upper wing": ["Bone_021", "Bone_024"],
    "lower wing": ["Bone_020", "Bone_023"],
    "wing tip": ["Bone_030", "Bone_032", "Bone_035", "Bone_038", "Bone_040", "Bone_043"],
    "tail": ["Bone_006", "Bone_005", "Bone_004"],
    "upper leg": ["Bone_011", "Bone_016"],
    "knee": ["Bone_010", "Bone_015"],
    "lower leg": ["Bone_009", "Bone_014"],
    "ankle": ["Bone_008", "Bone_013"],
    "foot": ["Bone_007", "Bone_012"],
    "talon": ["Bone_007", "Bone_012"],
}


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def project_world(point: Vector, width: int, height: int) -> tuple[float, float]:
    from bpy_extras.object_utils import world_to_camera_view

    ndc = world_to_camera_view(bpy.context.scene, STATE["camera"], point)
    return float(ndc.x * width), float((1.0 - ndc.y) * height)


def current_part_boxes(width: int, height: int) -> dict[str, tuple[float, float, float, float]]:
    arm = STATE["arm"]
    boxes = {}
    for part, names in ANATOMICAL_BONES.items():
        points = []
        for name in names:
            if name not in arm.pose.bones:
                continue
            pb = arm.pose.bones[name]
            points.extend((project_world(arm.matrix_world @ pb.head, width, height), project_world(arm.matrix_world @ pb.tail, width, height)))
        if not points:
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        # The detector boxes describe visible parts, so give bone projections
        # a role-independent padding rather than claiming exact skin ownership.
        pad = max(3.0, min(width, height) * 0.018)
        boxes[part] = (max(0.0, min(xs) - pad), max(0.0, min(ys) - pad), min(float(width), max(xs) + pad), min(float(height), max(ys) + pad))
    return boxes


def anatomical_alignment(target_boxes, width: int, height: int) -> dict:
    if not target_boxes:
        return {"score": 0.0, "parts": [], "used": False}
    predicted = current_part_boxes(width, height)
    target_map = {}
    for item in target_boxes:
        part = str(item.get("part", ""))
        box = item.get("box")
        if part in ANATOMICAL_BONES and box and len(box) == 4:
            # Notebook boxes are normalized to [0,1] for the search resolution.
            target_map[part] = tuple(float(box[i]) * (width if i % 2 == 0 else height) for i in range(4))
    rows = []
    for part, target in target_map.items():
        candidate = predicted.get(part)
        if candidate is None:
            rows.append({"part": part, "iou": 0.0, "present": False})
            continue
        ax0, ay0, ax1, ay1 = target
        bx0, by0, bx1, by1 = candidate
        ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
        area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
        union = area_a + area_b - inter
        rows.append({"part": part, "iou": float(inter / max(union, 1e-6)), "present": True})
    return {"score": float(sum(row["iou"] for row in rows) / max(len(rows), 1)), "parts": rows, "used": bool(rows)}


def set_unlit_texture_materials():
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        output = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not output or not principled:
            continue
        color = principled.inputs.get("Base Color")
        texture = None
        if color:
            texture = next(
                (
                    link.from_node
                    for link in color.links
                    if link.from_node.type == "TEX_IMAGE" and link.from_node.image
                ),
                None,
            )
        if texture is None:
            texture = next((n for n in nodes if n.type == "TEX_IMAGE" and n.image), None)
        if texture is None:
            continue
        texture.image.colorspace_settings.name = "Non-Color"
        alpha = principled.inputs.get("Alpha")
        emission = principled.inputs.get("Emission")
        if color:
            links.new(texture.outputs["Color"], color)
        if alpha and "Alpha" in texture.outputs:
            links.new(texture.outputs["Alpha"], alpha)
        if emission:
            links.new(texture.outputs["Color"], emission)
        if principled.inputs.get("Roughness"):
            principled.inputs["Roughness"].default_value = 1.0
        if principled.inputs.get("Specular"):
            principled.inputs["Specular"].default_value = 0.0
        emit_node = nodes.new(type="ShaderNodeEmission")
        emit_node.location = (principled.location.x + 220.0, principled.location.y)
        emit_node.inputs["Strength"].default_value = 1.0
        links.new(texture.outputs["Color"], emit_node.inputs["Color"])
        for link in list(output.inputs["Surface"].links):
            links.remove(link)
        links.new(emit_node.outputs["Emission"], output.inputs["Surface"])


def setup_camera(fit, arm):
    rows = fit["basisScreenRows"]
    right = Vector(rows[0]).normalized()
    # Fitted second row is image-down; Blender camera +Y is image-up.
    up = (-Vector(rows[1])).normalized()
    forward = right.cross(up).normalized()
    rotation = Matrix((right, up, -forward)).transposed().to_4x4()
    data = bpy.data.cameras.new("PoseFitCamera")
    data.type = "ORTHO"
    src_w, src_h = float(fit["sourceResolution"][0]), float(fit["sourceResolution"][1])
    data.ortho_scale = max(src_w, src_h) / float(fit["pxPerWorld"])
    camera = bpy.data.objects.new("PoseFitCamera", data)
    bpy.context.collection.objects.link(camera)
    heads = [arm.matrix_world @ pb.bone.head_local for pb in arm.pose.bones]
    center = sum(heads[1:], heads[0]) / float(len(heads))
    camera.location = center - forward * 6.0
    camera.matrix_world = Matrix.Translation(camera.location) @ rotation
    depths = [(h - camera.location).dot(forward) for h in heads]
    near = float(min(depths))
    far = float(max(depths))
    pad = max(0.25, 0.05 * (far - near + 1e-6))
    data.clip_start = max(0.01, near - pad)
    data.clip_end = max(data.clip_start + 0.05, far + pad)
    bpy.context.scene.camera = camera
    return camera, right, up, forward


def _socket(sockets, *names):
    for name in names:
        if name in sockets:
            return sockets[name]
    return None


def setup_depth_compositor(scene, camera, depth_dir: Path, *, pack_depth_in_rgba: bool = True):
    """Z → MapRange. Under blender -b, pack depth into Composite RGB + Alpha silhouette
    (Viewer Node does not update in background mode).
    """
    depth_dir = Path(depth_dir)
    depth_dir.mkdir(parents=True, exist_ok=True)

    view_layer = bpy.context.view_layer
    view_layer.use_pass_z = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)
    composite = tree.nodes.new("CompositorNodeComposite")
    composite.location = (920, 40)

    map_range = tree.nodes.new("CompositorNodeMapRange")
    map_range.location = (320, -80)
    clip_start = float(camera.data.clip_start)
    clip_end = float(camera.data.clip_end)
    for key, value in (
        ("From Min", clip_start),
        ("From Max", clip_end),
        ("To Min", 0.0),
        ("To Max", 1.0),
    ):
        if key in map_range.inputs:
            map_range.inputs[key].default_value = value
    if hasattr(map_range, "use_clamp"):
        map_range.use_clamp = True

    depth_out = _socket(rl.outputs, "Depth", "Z", "Depth.001")
    if depth_out is None:
        for sock in rl.outputs:
            if sock.name not in ("Image", "Alpha"):
                depth_out = sock
                break
    if depth_out is None:
        raise RuntimeError("Render Layers has no Depth/Z socket (enable use_pass_z)")

    value_in = _socket(map_range.inputs, "Value", "value")
    value_out = _socket(map_range.outputs, "Value", "Result", "value")
    if value_in is None or value_out is None:
        raise RuntimeError(
            "CompositorNodeMapRange missing Value socket "
            f"(inputs={list(map_range.inputs.keys())}, outputs={list(map_range.outputs.keys())})"
        )
    tree.links.new(depth_out, value_in)

    img = _socket(rl.outputs, "Image")
    alpha = _socket(rl.outputs, "Alpha")

    if pack_depth_in_rgba:
        comb = tree.nodes.new("CompositorNodeCombRGBA")
        comb.location = (560, -80)
        for ch in ("R", "G", "B"):
            if ch in comb.inputs:
                tree.links.new(value_out, comb.inputs[ch])
        set_alpha = tree.nodes.new("CompositorNodeSetAlpha")
        set_alpha.location = (740, -40)
        tree.links.new(comb.outputs["Image"], set_alpha.inputs["Image"])
        if alpha is not None and "Alpha" in set_alpha.inputs:
            tree.links.new(alpha, set_alpha.inputs["Alpha"])
        tree.links.new(set_alpha.outputs["Image"], composite.inputs["Image"])
    elif img is not None:
        tree.links.new(img, composite.inputs["Image"])
    return depth_dir


def _blender_image_rgba(name: str) -> np.ndarray:
    """Read a Blender image buffer as float RGBA HxWx4 (top-left origin)."""
    img = bpy.data.images.get(name)
    if img is None:
        raise RuntimeError(f"Blender image missing: {name!r}")
    w, h = int(img.size[0]), int(img.size[1])
    if w <= 0 or h <= 0:
        raise RuntimeError(f"Blender image {name!r} has empty size {img.size}")
    _ = len(img.pixels)
    pix = np.array(img.pixels[:], dtype=np.float32)
    if pix.size != w * h * 4:
        raise RuntimeError(
            f"Blender image {name!r} pixel size mismatch: got {pix.size}, expected {w*h*4}"
        )
    return np.flipud(pix.reshape(h, w, 4))


def render_search() -> tuple[np.ndarray, np.ndarray | None]:
    """Search render. blender -b leaves Render Result empty, so write one reused still.
    Depth is packed into RGB when pack_depth_in_rgba is set (no separate depth PNG).
    """
    ensure_search_mode()
    path = Path(STATE["render_path"])
    # Background mode: Render Result size stays 0 unless write_still=True.
    use_still = bool(getattr(bpy.app, "background", True))
    bpy.ops.render.render(write_still=use_still)
    if use_still:
        rgba = load_rgba(path)
    else:
        try:
            rgba = _blender_image_rgba("Render Result")
        except RuntimeError:
            bpy.ops.render.render(write_still=True)
            rgba = load_rgba(path)
    depth = None
    if STATE.get("pack_depth_in_rgba", True):
        depth = np.ascontiguousarray(rgba[:, :, 0], dtype=np.float32)
    return rgba, depth


def render_rgb_search() -> tuple[np.ndarray, None]:
    """Render the actual textured candidate, bypassing the depth packer.

    The search compositor normally replaces RGB with normalized Z so the depth
    scorer can avoid a second render.  That buffer is not suitable for the
    semantic encoder or an RGB live preview, so those paths explicitly render
    through the same camera/pose with the compositor connected to the real
    render image instead.
    """
    ensure_search_mode()
    scene = bpy.context.scene
    previous_path = scene.render.filepath
    rgb_path = Path(STATE["rgb_render_path"])
    rgb_path.parent.mkdir(parents=True, exist_ok=True)
    setup_depth_compositor(
        scene,
        STATE["camera"],
        Path(STATE["depth_dir"]),
        pack_depth_in_rgba=False,
    )
    scene.render.filepath = str(rgb_path)
    try:
        use_still = bool(getattr(bpy.app, "background", True))
        bpy.ops.render.render(write_still=use_still)
        if use_still:
            rgba = load_rgba(rgb_path)
        else:
            try:
                rgba = _blender_image_rgba("Render Result")
            except RuntimeError:
                bpy.ops.render.render(write_still=True)
                rgba = load_rgba(rgb_path)
        return rgba, None
    finally:
        # Restore the depth search compositor for the next candidate unless
        # this worker was initialized in RGB/chroma mode.
        setup_depth_compositor(
            scene,
            STATE["camera"],
            Path(STATE["depth_dir"]),
            pack_depth_in_rgba=bool(STATE.get("pack_depth_in_rgba", False)),
        )
        scene.render.filepath = previous_path


def _configure_engine(engine: str, *, width: int, height: int, taa_samples: int = 1):
    scene = bpy.context.scene
    scene.render.engine = engine
    if engine == "BLENDER_EEVEE":
        scene.eevee.taa_render_samples = max(1, int(taa_samples))
    elif engine == "BLENDER_WORKBENCH":
        shading = scene.display.shading
        shading.light = "FLAT"
        shading.color_type = "TEXTURE"
        shading.show_specular_highlight = False
        shading.show_backface_culling = False
    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True


def init(command):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(command["src"]).resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE":
            modifier.use_deform_preserve_volume = True

    full_w = int(command.get("width", 768))
    full_h = int(command.get("height", 683))
    search_scale = float(command.get("searchScale", 0.35))
    search_scale = min(1.0, max(0.15, search_scale))
    search_w = max(32, int(round(full_w * search_scale)))
    search_h = max(32, int(round(full_h * search_scale)))
    search_engine = str(command.get("searchEngine", "BLENDER_WORKBENCH"))
    search_taa = int(command.get("searchTaaSamples", 1))
    proof_engine = str(command.get("proofEngine", "BLENDER_EEVEE"))
    proof_taa = int(command.get("proofTaaSamples", 8))
    score_mode = str(command.get("scoreMode", "depth")).lower()
    if score_mode not in ("depth", "chroma"):
        raise ValueError(f"unsupported scoreMode: {score_mode!r}")

    scene = bpy.context.scene
    scene.render.fps = 6
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
    except Exception:
        pass
    if scene.world is None:
        scene.world = bpy.data.worlds.new("PoseFitWorld")
    scene.world.color = (0.0, 0.0, 0.0)
    set_unlit_texture_materials()
    camera, right, up, forward = setup_camera(json.loads(Path(command["fit"]).read_text()), arm)

    light_data = bpy.data.lights.new("PoseFitFill", type="AREA")
    light_data.energy = 50.0
    light_data.size = 5.0
    light = bpy.data.objects.new("PoseFitFill", light_data)
    bpy.context.collection.objects.link(light)
    light.location = arm.matrix_world.translation + Vector((2.0, -2.0, 4.0))

    base = {}
    parents = {}
    bone_heads = {}
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        base[pb.name] = pb.rotation_quaternion.copy()
        parents[pb.name] = pb.parent.name if pb.parent else None
        head = arm.matrix_world @ pb.bone.head_local
        bone_heads[pb.name] = [float(head.x), float(head.y), float(head.z)]

    work = Path(tempfile.mkdtemp(prefix="pose_fit_worker_"))
    render_path = work / "capture.png"
    rgb_render_path = work / "capture_rgb.png"
    depth_dir = work / "depth"
    pack_depth = score_mode == "depth"
    setup_depth_compositor(scene, camera, depth_dir, pack_depth_in_rgba=pack_depth)

    _configure_engine(search_engine, width=search_w, height=search_h, taa_samples=search_taa)
    scene.render.filepath = str(render_path)

    STATE.clear()
    STATE.update(
        {
            "arm": arm,
            "camera": camera,
            "base": base,
            "right": right,
            "up": up,
            "forward": forward,
            "full_w": full_w,
            "full_h": full_h,
            "search_w": search_w,
            "search_h": search_h,
            "search_scale": search_scale,
            "search_engine": search_engine,
            "search_taa": search_taa,
            "proof_engine": proof_engine,
            "proof_taa": proof_taa,
            "render_path": render_path,
            "rgb_render_path": rgb_render_path,
            "depth_dir": depth_dir,
            "score_mode": score_mode,
            "color_max_dist": float(command.get("colorMaxDist", 0.30)),
            "depth_max_dist": float(command.get("depthMaxDist", 0.35)),
            "pred_only_penalty": float(command.get("predOnlyPenalty", 2.0)),
            "target_edge_sigma_px": float(command.get("targetEdgeSigmaPx", 4.0)),
            "target_edge_floor": float(command.get("targetEdgeFloor", 0.25)),
            "targets": {},
            "mode": "search",
            "pack_depth_in_rgba": pack_depth,
            "strip_bone_roll": bool(command.get("stripBoneRoll", True)),
        }
    )

    bpy.ops.render.render(write_still=False)

    emit(
        {
            "ok": True,
            "bones": [pb.name for pb in arm.pose.bones],
            "parents": parents,
            "boneHeads": bone_heads,
            "view": [float(forward.x), float(forward.y), float(forward.z)],
            "right": [float(right.x), float(right.y), float(right.z)],
            "up": [float(up.x), float(up.y), float(up.z)],
            "width": full_w,
            "height": full_h,
            "searchWidth": search_w,
            "searchHeight": search_h,
            "searchScale": search_scale,
            "searchEngine": search_engine,
            "proofEngine": proof_engine,
            "scoreMode": score_mode,
            "clipStart": float(camera.data.clip_start),
            "clipEnd": float(camera.data.clip_end),
        }
    )


def set_palette(command):
    """Legacy stub — soft depth/chroma scoring does not use a shared palette."""
    emit(
        {
            "ok": True,
            "legacy": True,
            "paletteSize": int(len(command.get("palette") or [])),
            "texturesQuantized": 0,
            "textureQuantizeMode": "stub",
        }
    )


def ensure_search_mode():
    if STATE.get("mode") == "search":
        return
    _configure_engine(
        STATE["search_engine"],
        width=STATE["search_w"],
        height=STATE["search_h"],
        taa_samples=STATE["search_taa"],
    )
    bpy.context.scene.render.filepath = str(STATE["render_path"])
    STATE["mode"] = "search"


def ensure_proof_mode():
    if STATE.get("mode") == "proof":
        return
    _configure_engine(
        STATE["proof_engine"],
        width=STATE["full_w"],
        height=STATE["full_h"],
        taa_samples=STATE["proof_taa"],
    )
    STATE["mode"] = "proof"


def set_pose(command):
    apply_pose(command)
    emit({"ok": True})


def _axis_angle_quat(axis: str, angle: float) -> Quaternion:
    axis = str(axis).lower()
    if axis == "x":
        return Quaternion((1.0, 0.0, 0.0), float(angle))
    if axis == "y":
        return Quaternion((0.0, 1.0, 0.0), float(angle))
    if axis == "z":
        return Quaternion((0.0, 0.0, 1.0), float(angle))
    raise ValueError(f"unsupported rotation axis: {axis!r}")


def _strip_twist(q: Quaternion, twist_axis: Vector) -> Quaternion:
    """Remove rotation about twist_axis (bone roll). Returns swing-only quaternion.

    Decomposes q = swing * twist and drops twist. Skipping Euler Y alone is not
    enough: X+Z composition still induces roll about the bone shaft.
    """
    q = q.copy()
    q.normalize()
    axis = Vector(twist_axis)
    if axis.length_squared < 1e-16:
        return q
    axis.normalize()
    # Project quaternion vector part onto the twist axis.
    dot = float(q.x * axis.x + q.y * axis.y + q.z * axis.z)
    twist = Quaternion((float(q.w), axis.x * dot, axis.y * dot, axis.z * dot))
    if twist.magnitude < 1e-12:
        return q
    twist.normalize()
    # Keep twist in the same hemisphere as q so swing stays continuous.
    if float(q.w * twist.w + q.x * twist.x + q.y * twist.y + q.z * twist.z) < 0.0:
        twist = Quaternion((-twist.w, -twist.x, -twist.y, -twist.z))
    swing = q @ twist.inverted()
    swing.normalize()
    return swing


def _bone_delta_quat(value) -> Quaternion:
    """float → local +Z; {axis,angle}; or {x,y,z} local Euler radians."""
    if isinstance(value, (int, float)):
        return _axis_angle_quat("z", float(value))
    if isinstance(value, dict):
        if "axis" in value:
            return _axis_angle_quat(
                value["axis"],
                float(value.get("angle", value.get("rad", 0.0))),
            )
        euler = Euler(
            (
                float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("z", 0.0)),
            ),
            "XYZ",
        )
        return euler.to_quaternion()
    raise TypeError(f"bone angle must be float or dict, got {type(value)!r}")


def apply_pose(command):
    arm = STATE["arm"]
    strip_roll = bool(command.get("stripBoneRoll", STATE.get("strip_bone_roll", True)))
    for pb in arm.pose.bones:
        pb.rotation_quaternion = STATE["base"][pb.name]
    for name, value in command.get("angles", {}).items():
        if name not in arm.pose.bones:
            continue
        delta = _bone_delta_quat(value)
        if strip_roll:
            # Twist axis = bone shaft (head→tip) in bone-local space.
            twist_axis = pb.bone.vector.copy()
            if twist_axis.length_squared < 1e-16:
                twist_axis = Vector((0.0, 1.0, 0.0))
            delta = _strip_twist(delta, twist_axis)
        arm.pose.bones[name].rotation_quaternion = STATE["base"][name] @ delta
    bpy.context.view_layer.update()


def load_rgba(path: Path) -> np.ndarray:
    path = Path(path)
    if Image is not None:
        return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    image = bpy.data.images.load(str(path.resolve()), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        values = np.array(image.pixels[:], dtype=np.float32).reshape(
            (image.size[1], image.size[0], 4)
        )
        return np.flipud(values)
    finally:
        bpy.data.images.remove(image)


def load_gray(path: Path) -> np.ndarray:
    path = Path(path)
    if Image is not None:
        return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0
    image = bpy.data.images.load(str(path.resolve()), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        values = np.array(image.pixels[:], dtype=np.float32).reshape(
            (image.size[1], image.size[0], 4)
        )
        gray = values[:, :, 0]
        return np.flipud(gray)
    finally:
        bpy.data.images.remove(image)


def resize_rgba(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    if rgba.shape[0] == height and rgba.shape[1] == width:
        return rgba
    if Image is None:
        ys = np.linspace(0, rgba.shape[0] - 1, height).astype(np.int32)
        xs = np.linspace(0, rgba.shape[1] - 1, width).astype(np.int32)
        return rgba[ys][:, xs]
    img = Image.fromarray(np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8), "RGBA")
    img = img.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def resize_gray(gray: np.ndarray, width: int, height: int) -> np.ndarray:
    if gray.shape[0] == height and gray.shape[1] == width:
        return gray
    if Image is None:
        ys = np.linspace(0, gray.shape[0] - 1, height).astype(np.int32)
        xs = np.linspace(0, gray.shape[1] - 1, width).astype(np.int32)
        return gray[ys][:, xs]
    img = Image.fromarray(np.clip(np.rint(gray * 255.0), 0, 255).astype(np.uint8), "L")
    img = img.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def soft_silhouette_weight(
    target_occ: np.ndarray,
    predicted_occ: np.ndarray,
) -> np.ndarray:
    """Per-pixel soft intersection mass: min(target, pred) occupancy in [0,1]."""
    return np.minimum(target_occ, predicted_occ).astype(np.float32)


def soft_color_weight(
    target_rgb: np.ndarray,
    predicted_rgb: np.ndarray,
    both: np.ndarray,
    color_max_dist: float,
) -> np.ndarray:
    weight = np.zeros(both.shape, dtype=np.float32)
    if not both.any():
        return weight
    diff = target_rgb[both] - predicted_rgb[both]
    dist = np.sqrt((diff * diff).sum(axis=-1))
    max_d = float(color_max_dist)
    if max_d <= 1e-8:
        weight[both] = (dist <= 1e-8).astype(np.float32)
    else:
        weight[both] = np.clip(1.0 - dist / max_d, 0.0, 1.0).astype(np.float32)
    return weight


def soft_depth_weight(
    target_depth: np.ndarray,
    predicted_depth: np.ndarray,
    both: np.ndarray,
    depth_max_dist: float,
) -> np.ndarray:
    weight = np.zeros(both.shape, dtype=np.float32)
    if not both.any():
        return weight
    dist = np.abs(target_depth[both] - predicted_depth[both])
    max_d = float(depth_max_dist)
    if max_d <= 1e-8:
        weight[both] = (dist <= 1e-8).astype(np.float32)
    else:
        weight[both] = np.clip(1.0 - dist / max_d, 0.0, 1.0).astype(np.float32)
    return weight


def target_edge_weights(
    mask: np.ndarray,
    *,
    sigma_px: float = 4.0,
    floor: float = 0.25,
) -> np.ndarray:
    """Per-pixel weights on the target: peak at the silhouette edge, floor in the core.

    Interior distance-to-boundary decays with sigma_px. floor keeps center matches
    from going to zero (1.0 at the rim when floor=0).
    """
    m = np.asarray(mask, dtype=bool)
    out = np.zeros(m.shape, dtype=np.float32)
    if not m.any():
        return out
    sigma = max(float(sigma_px), 1e-3)
    floor = float(np.clip(floor, 0.0, 1.0))
    try:
        import cv2

        dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
    except Exception:
        # Coarse EDT: iterative erosion count (Chebyshev-ish).
        dist = np.zeros(m.shape, dtype=np.float32)
        remain = m.copy()
        layer = 0.0
        while remain.any() and layer < 4096:
            # 4-connected erosion
            pad = np.pad(remain, 1, constant_values=False)
            eroded = (
                pad[1:-1, 1:-1]
                & pad[:-2, 1:-1]
                & pad[2:, 1:-1]
                & pad[1:-1, :-2]
                & pad[1:-1, 2:]
            )
            ring = remain & ~eroded
            dist[ring] = layer
            remain = eroded
            layer += 1.0
            if not ring.any():
                break
    edge = np.exp(-dist.astype(np.float32) / sigma)
    out[m] = floor + (1.0 - floor) * edge[m]
    return out


def normalize_depth_range(
    depth: np.ndarray,
    mask: np.ndarray,
    *,
    lo_pct: float = 5.0,
    hi_pct: float = 95.0,
) -> np.ndarray:
    """Percentile-stretch depth inside mask to [0,1] (near/bright stays high if already near=1)."""
    out = np.zeros(mask.shape, dtype=np.float32)
    if not np.any(mask):
        return out
    vals = np.asarray(depth, dtype=np.float32)[mask]
    lo = float(np.percentile(vals, lo_pct))
    hi = float(np.percentile(vals, hi_pct))
    if hi - lo < 1e-6:
        out[mask] = 1.0
    else:
        out[mask] = np.clip((vals - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    return out


def histogram_match_values(
    source: np.ndarray,
    template: np.ndarray,
) -> np.ndarray:
    """Map source values onto template's CDF (monotone; preserves source order)."""
    src = np.asarray(source, dtype=np.float32).ravel()
    tmpl = np.asarray(template, dtype=np.float32).ravel()
    if src.size == 0 or tmpl.size == 0:
        return np.asarray(source, dtype=np.float32)
    s_values, s_inverse, s_counts = np.unique(src, return_inverse=True, return_counts=True)
    t_values, t_counts = np.unique(tmpl, return_counts=True)
    s_quant = np.cumsum(s_counts).astype(np.float64)
    s_quant /= float(s_quant[-1])
    t_quant = np.cumsum(t_counts).astype(np.float64)
    t_quant /= float(t_quant[-1])
    matched = np.interp(s_quant, t_quant, t_values).astype(np.float32)
    return matched[s_inverse].reshape(np.asarray(source).shape)


def matched_depth_pair(
    target_depth: np.ndarray,
    predicted_depth: np.ndarray,
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Stretch both, then histogram-match mesh→sprite so metric Z does not invent darker range."""
    t = normalize_depth_range(target_depth, target_mask)
    p = normalize_depth_range(predicted_depth, predicted_mask)
    # Mesh Z has real far surfaces; monocular sprite depth is flatter. Match pred onto the
    # sprite CDF so scoring/preview share the same value distribution while mesh order stays.
    both = target_mask & predicted_mask
    tmpl = t[both] if int(both.sum()) >= 32 else t[target_mask]
    if predicted_mask.any() and tmpl.size >= 32:
        p_out = np.zeros_like(p)
        p_out[predicted_mask] = histogram_match_values(p[predicted_mask], tmpl)
        p = p_out
    return t, p


def load_depth01(path: Path, width: int, height: int) -> np.ndarray:
    """Load predicted target depth PNG (8 or 16-bit), near=1, resize to search res."""
    path = Path(path)
    if Image is not None:
        img = Image.open(path)
        arr = np.asarray(img, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        if arr.max() > 1.5:
            arr = arr / (65535.0 if arr.max() > 255.5 else 255.0)
    else:
        image = bpy.data.images.load(str(path.resolve()), check_existing=False)
        try:
            values = np.array(image.pixels[:], dtype=np.float32).reshape((image.size[1], image.size[0], 4))
            arr = np.flipud(values[:, :, 0])
        finally:
            bpy.data.images.remove(image)
    arr = np.clip(arr, 0.0, 1.0).astype(np.float32)
    if arr.shape[0] != height or arr.shape[1] != width:
        arr = resize_gray(arr, width, height)
    return np.ascontiguousarray(arr, dtype=np.float32)


def resolve_target_depth_path(target_path: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    sibling = target_path.parent.parent / "frames_depth_predicted" / target_path.name
    if sibling.is_file():
        return sibling
    alt = target_path.parent / "depth" / target_path.name
    if alt.is_file():
        return alt
    return None


def _file_stamp(path: Path | None) -> str:
    """mtime+size so rewritten targets (e.g. scale tweaks) miss the cache."""
    if path is None:
        return ""
    path = Path(path)
    if not path.is_file():
        return ""
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return ""


def get_or_cache_target(
    path: str,
    threshold: float,
    depth_path: str | None = None,
    *,
    edge_sigma_px: float = 4.0,
    edge_floor: float = 0.25,
):
    target_path = Path(path)
    depth_file = resolve_target_depth_path(target_path, depth_path)
    key = (
        str(target_path.resolve()),
        float(threshold),
        STATE["search_w"],
        STATE["search_h"],
        str(depth_file.resolve()) if depth_file else "",
        _file_stamp(target_path),
        _file_stamp(depth_file),
        float(edge_sigma_px),
        float(edge_floor),
        "depth_v5_edge",
    )
    cached = STATE["targets"].get(key)
    if cached is not None:
        return cached
    rgba = resize_rgba(load_rgba(target_path), STATE["search_w"], STATE["search_h"])
    alpha = np.ascontiguousarray(rgba[:, :, 3], dtype=np.float32)
    mask = alpha >= threshold
    target_depth = None
    if depth_file is not None:
        target_depth = load_depth01(depth_file, STATE["search_w"], STATE["search_h"])
        target_depth = target_depth * (alpha > 0).astype(np.float32)
    edge_w = target_edge_weights(mask, sigma_px=edge_sigma_px, floor=edge_floor)
    cached = {
        "mask": mask,
        "silhouette": alpha,
        "depth": target_depth,
        "depthPath": str(depth_file) if depth_file else None,
        "rgb": np.ascontiguousarray(rgba[:, :, :3], dtype=np.float32),
        "rgba": rgba,
        "targetPixels": int(mask.sum()),
        "edgeWeight": edge_w,
        "edgeSigmaPx": float(edge_sigma_px),
        "edgeFloor": float(edge_floor),
    }
    STATE["targets"][key] = cached
    return cached


def find_latest_depth_png(depth_dir: Path, *, newer_than: float | None = None) -> Path | None:
    depth_dir = Path(depth_dir)
    if not depth_dir.is_dir():
        return None
    candidates = list(depth_dir.glob("depth*.png")) + list(depth_dir.glob("**/depth*.png"))
    # Unique by resolve.
    uniq = {}
    for path in candidates:
        try:
            uniq[str(path.resolve())] = path
        except OSError:
            uniq[str(path)] = path
    files = list(uniq.values())
    if not files:
        return None
    if newer_than is not None:
        fresh = []
        for path in files:
            try:
                if path.stat().st_mtime + 1e-3 >= newer_than:
                    fresh.append(path)
            except OSError:
                continue
        if fresh:
            files = fresh
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return files[0]


def write_live_preview(
    *,
    out_path: Path,
    target_rgba: np.ndarray | None,
    target_mask: np.ndarray,
    mid_panel: np.ndarray,
    mid_label: str,
    predicted_mask: np.ndarray,
    soft_weight: np.ndarray,
    iou: float,
    caption: str,
    left_panel: np.ndarray | None = None,
    left_label: str = "target",
    target_part_boxes: list[dict] | None = None,
    predicted_part_boxes: dict[str, tuple[float, float, float, float]] | None = None,
):
    """3-panel PNG with target/render/IoU plus anatomical box overlays."""
    if Image is None:
        return
    h, w = predicted_mask.shape

    def _as_rgb_panel(panel: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if panel.ndim == 2:
            g = np.clip(np.rint(panel * 255.0), 0, 255).astype(np.uint8)
            rgb = np.stack([g, g, g], axis=-1).copy()
        else:
            rgb = np.clip(np.rint(panel[:, :, :3] * 255.0), 0, 255).astype(np.uint8).copy()
        rgb[~mask] = 0
        return rgb

    if left_panel is not None:
        if left_panel.ndim == 2:
            # Soft silhouette / depth: keep AA; do not hard-punch with threshold mask.
            g = np.clip(np.rint(left_panel * 255.0), 0, 255).astype(np.uint8)
            target_panel = np.stack([g, g, g], axis=-1)
        else:
            target_panel = _as_rgb_panel(left_panel, target_mask)
    elif target_rgba is not None and target_rgba.shape[0] == h and target_rgba.shape[1] == w:
        target_panel = np.clip(np.rint(target_rgba[:, :, :3] * 255.0), 0, 255).astype(np.uint8)
        target_panel = target_panel.copy()
        target_panel[~target_mask] = 0
    else:
        target_panel = np.zeros((h, w, 3), dtype=np.uint8)
        target_panel[target_mask] = (220, 220, 220)

    render_panel = _as_rgb_panel(mid_panel, predicted_mask)

    only_target = target_mask & ~predicted_mask
    only_pred = predicted_mask & ~target_mask
    iou_panel = np.zeros((h, w, 3), dtype=np.uint8)
    iou_panel[only_target] = (220, 64, 64)
    iou_panel[only_pred] = (64, 120, 255)
    both = target_mask & predicted_mask
    if both.any():
        g = np.clip(np.rint(64.0 + soft_weight[both] * 176.0), 0, 255).astype(np.uint8)
        iou_panel[both, 0] = 32
        iou_panel[both, 1] = g
        iou_panel[both, 2] = 48

    def draw_boxes(panel: np.ndarray, boxes, color):
        from PIL import ImageDraw, ImageFont

        image = Image.fromarray(panel, "RGB")
        draw = ImageDraw.Draw(image)
        for item in boxes or []:
            if isinstance(item, dict):
                box = item.get("box")
                if not box:
                    continue
                # Target boxes arrive normalized; predicted boxes are pixels.
                if max(abs(float(v)) for v in box) <= 1.5:
                    x0, y0, x1, y1 = (float(box[0]) * w, float(box[1]) * h, float(box[2]) * w, float(box[3]) * h)
                else:
                    x0, y0, x1, y1 = map(float, box)
                label = str(item.get("part", "part"))
            else:
                x0, y0, x1, y1 = map(float, item[1])
                label = str(item[0])
            draw.rectangle((x0, y0, x1, y1), outline=color, width=max(1, w // 160))
            draw.text((max(0, x0 + 2), max(0, y0 + 2)), label, fill=color, font=ImageFont.load_default())
        return np.asarray(image, dtype=np.uint8)

    target_part_boxes = target_part_boxes or []
    predicted_part_boxes = predicted_part_boxes or {}
    target_panel = draw_boxes(target_panel, target_part_boxes, (40, 230, 255))
    render_panel = draw_boxes(render_panel, [(part, box) for part, box in predicted_part_boxes.items()], (255, 220, 40))
    iou_panel = draw_boxes(iou_panel, target_part_boxes, (255, 80, 220))

    gap = 4
    canvas = np.zeros((h, w * 3 + gap * 2, 3), dtype=np.uint8)
    canvas[:, 0:w] = target_panel
    canvas[:, w + gap : 2 * w + gap] = render_panel
    canvas[:, 2 * (w + gap) : 2 * (w + gap) + w] = iou_panel

    bar_h = max(18, h // 12)
    bar = np.zeros((bar_h, canvas.shape[1], 3), dtype=np.uint8)
    bar[:] = (24, 24, 28)
    stacked = np.concatenate([bar, canvas], axis=0)
    image = Image.fromarray(stacked, "RGB")
    try:
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.text((6, 2), f"{caption}   softIoU={iou:.4f}", fill=(235, 235, 240), font=font)
        draw.text((6, bar_h + 2), left_label, fill=(200, 200, 200), font=font)
        draw.text((w + gap + 6, bar_h + 2), mid_label, fill=(200, 200, 200), font=font)
        draw.text(
            (2 * (w + gap) + 6, bar_h + 2),
            "softIoU  G~match R=tgt B=pred",
            fill=(200, 200, 200),
            font=font,
        )
    except Exception:
        pass
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The notebook updates a persistent display handle after the worker reply.
    # Replace atomically so it never reads a partially written PNG.
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp.png")
    image.save(temp_path, format="PNG")
    os.replace(temp_path, out_path)


def score(command):
    if "angles" in command:
        apply_pose(command)

    threshold = float(command.get("alphaThreshold", 0.08))
    score_mode = str(command.get("scoreMode", STATE.get("score_mode", "depth"))).lower()
    color_max_dist = float(command.get("colorMaxDist", STATE.get("color_max_dist", 0.30)))
    depth_max_dist = float(command.get("depthMaxDist", STATE.get("depth_max_dist", 0.35)))
    # Blue panel = pred-only. Weight >1 penalizes mesh spilling outside the sprite.
    pred_only_penalty = float(
        command.get("predOnlyPenalty", STATE.get("pred_only_penalty", 2.0))
    )
    pred_only_penalty = max(1.0, pred_only_penalty)
    edge_sigma = float(
        command.get("targetEdgeSigmaPx", STATE.get("target_edge_sigma_px", 4.0))
    )
    edge_floor = float(
        command.get("targetEdgeFloor", STATE.get("target_edge_floor", 0.25))
    )

    missing_target_depth = False
    left_depth = None
    left_label = "target"

    target = get_or_cache_target(
        command["target"],
        threshold,
        depth_path=command.get("targetDepth"),
        edge_sigma_px=edge_sigma,
        edge_floor=edge_floor,
    )
    # Depth-packed RGB is intentionally used for the depth scorer, but it is
    # not a valid input image for semantic embeddings or an RGB preview.
    wants_rgb = bool(
        score_mode == "chroma"
        or command.get("previewRgb", False)
        or command.get("semanticCandidateOut")
    )
    if score_mode == "depth" and wants_rgb:
        _, depth_mapped = render_search()
        predicted, _ = render_rgb_search()
    elif wants_rgb:
        predicted, depth_mapped = render_rgb_search()
    else:
        predicted, depth_mapped = render_search()
    if predicted.shape[0] != STATE["search_h"] or predicted.shape[1] != STATE["search_w"]:
        predicted = resize_rgba(predicted, STATE["search_w"], STATE["search_h"])
        if depth_mapped is not None:
            depth_mapped = resize_gray(depth_mapped, STATE["search_w"], STATE["search_h"])

    semantic_out = command.get("semanticCandidateOut")
    if semantic_out and Image is not None:
        semantic_path = Path(semantic_out).resolve()
        semantic_path.parent.mkdir(parents=True, exist_ok=True)
        semantic_tmp = semantic_path.with_suffix(semantic_path.suffix + ".tmp.png")
        semantic_rgba = np.clip(np.rint(predicted * 255.0), 0, 255).astype(np.uint8)
        Image.fromarray(semantic_rgba, "RGBA").save(semantic_tmp, format="PNG")
        os.replace(semantic_tmp, semantic_path)

    predicted_mask = predicted[:, :, 3] >= threshold
    target_mask = target["mask"]
    edge_w = target.get("edgeWeight")
    if edge_w is None or edge_w.shape != target_mask.shape:
        edge_w = target_edge_weights(target_mask, sigma_px=edge_sigma, floor=edge_floor)
    both = target_mask & predicted_mask
    only_target = target_mask & ~predicted_mask
    only_pred = predicted_mask & ~target_mask
    depth_used = False
    fallback_binary = False

    def _weighted_intersection(soft: np.ndarray) -> float:
        if not both.any():
            return 0.0
        return float((soft[both] * edge_w[both]).sum())

    def _asymmetric_union(intersection_mass: float) -> float:
        # Red (target miss) uses edge weights; blue (pred spill) uses pred_only_penalty.
        return float(
            intersection_mass
            + float(edge_w[only_target].sum())
            + pred_only_penalty * float(only_pred.sum())
        )

    if score_mode == "chroma":
        soft_weight = soft_color_weight(
            target["rgb"],
            predicted[:, :, :3],
            both,
            color_max_dist,
        )
        mid_panel = predicted
        mid_label = "render"
        intersection = _weighted_intersection(soft_weight)
        union = _asymmetric_union(intersection)
    else:
        # Soft depth IoU: monocular-predicted sprite depth vs mesh Z (near=1).
        if depth_mapped is not None:
            geom = predicted_mask & (depth_mapped < 0.999)
            predicted_mask = geom
            both = target_mask & predicted_mask
            only_target = target_mask & ~predicted_mask
            only_pred = predicted_mask & ~target_mask
            pred_depth = np.zeros(predicted_mask.shape, dtype=np.float32)
            pred_depth[geom] = (1.0 - depth_mapped[geom]).astype(np.float32)
            depth_used = True
            mid_panel = pred_depth
            mid_label = "predDepth(near=1)"
        else:
            pred_depth = predicted[:, :, 3].astype(np.float32)
            fallback_binary = True
            mid_panel = pred_depth
            mid_label = "predSil(no-depth)"

        tgt_depth = target.get("depth")
        if tgt_depth is None:
            missing_target_depth = True
            soft_weight = soft_silhouette_weight(
                target["silhouette"],
                predicted_mask.astype(np.float32),
            )
            intersection = _weighted_intersection(soft_weight)
            union = _asymmetric_union(intersection)
            left_depth = target["silhouette"]
            left_label = "tgtSil(NO pred depth)"
        else:
            tgt_n, pred_n = matched_depth_pair(
                tgt_depth, pred_depth, target_mask, predicted_mask
            )
            soft_weight = soft_depth_weight(tgt_n, pred_n, both, depth_max_dist)
            intersection = _weighted_intersection(soft_weight)
            union = _asymmetric_union(intersection)
            left_depth = tgt_n
            left_label = "tgtDepth(norm)"
            mid_panel = pred_n
            mid_label = "predDepth(→tgt hist)"

    silhouette_iou = float(intersection / max(union, 1e-6))
    part_weight = float(command.get("anatomicalPartWeight", STATE.get("anatomical_part_weight", 0.20)))
    part_weight = min(max(part_weight, 0.0), 1.0)
    part_result = anatomical_alignment(command.get("targetPartBoxes", []), STATE["search_w"], STATE["search_h"])
    # The detector supplies target boxes; current bone projections supply a
    # cheap per-candidate mesh box estimate. This keeps the local vision model
    # out of the inner render loop while still making anatomical alignment part
    # of the candidate score.
    iou = float((1.0 - part_weight) * silhouette_iou + part_weight * part_result["score"]) if part_result["used"] else silhouette_iou

    preview_out = command.get("previewOut")
    if preview_out:
        if command.get("previewRgb", False):
            left_panel, left_label_out = None, "target RGB"
            mid_panel, mid_label = predicted, "candidate RGB"
        elif score_mode == "chroma":
            left_panel, left_label_out = None, "target"
        else:
            left_panel, left_label_out = left_depth, left_label
        write_live_preview(
            out_path=Path(preview_out),
            target_rgba=target.get("rgba"),
            target_mask=target_mask,
            mid_panel=mid_panel,
            mid_label=mid_label,
            predicted_mask=predicted_mask,
            soft_weight=soft_weight,
            iou=iou,
            caption=str(command.get("previewCaption", f"score:{score_mode}")),
            left_panel=left_panel,
            left_label=left_label_out,
            target_part_boxes=command.get("targetPartBoxes") if command.get("showAnatomicalBoxes", True) else [],
            predicted_part_boxes=current_part_boxes(STATE["search_w"], STATE["search_h"])
            if command.get("showAnatomicalBoxes", True) and command.get("targetPartBoxes")
            else {},
        )

    emit(
        {
            "ok": True,
            "iou": iou,
            "intersection": intersection,
            "union": union,
            "silhouetteIoU": silhouette_iou,
            "anatomicalPartIoU": part_result["score"],
            "anatomicalPartWeight": part_weight,
            "anatomicalParts": part_result["parts"],
            "scoreMode": score_mode,
            "colorMaxDist": color_max_dist,
            "depthMaxDist": depth_max_dist,
            "predOnlyPenalty": pred_only_penalty,
            "targetEdgeSigmaPx": edge_sigma,
            "targetEdgeFloor": edge_floor,
            "depthUsed": depth_used,
            "fallbackBinary": fallback_binary,
            "missingTargetDepth": bool(missing_target_depth) if score_mode != "chroma" else False,
            "targetDepthPath": target.get("depthPath"),
            "targetPixels": int(target["targetPixels"]),
            "predictedPixels": int(predicted_mask.sum()),
            "searchWidth": STATE["search_w"],
            "searchHeight": STATE["search_h"],
            "searchEngine": STATE["search_engine"],
            "previewOut": preview_out,
        }
    )


def save_render(command):
    if "angles" in command:
        apply_pose(command)
    ensure_proof_mode()
    out = Path(command["out"]).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    ensure_search_mode()
    emit({"ok": True, "out": str(out)})


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        command = json.loads(line)
        try:
            cmd = command["cmd"]
            if cmd == "init":
                init(command)
            elif cmd == "set_palette":
                set_palette(command)
            elif cmd == "set_pose":
                set_pose(command)
            elif cmd == "score":
                score(command)
            elif cmd == "save_render":
                save_render(command)
            elif cmd == "clear_target_cache":
                STATE.setdefault("targets", {}).clear()
                emit({"ok": True, "cleared": True})
            elif cmd == "quit":
                emit({"ok": True})
                return
            else:
                emit({"ok": False, "error": "unknown command"})
        except Exception as exc:
            emit({"ok": False, "error": repr(exc)})


if __name__ == "__main__":
    main()
