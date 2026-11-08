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
import hashlib
import math
import os
import shutil
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


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        # This is albedo data, not a scalar/depth map. Treating it as Non-Color
        # makes Standard view transform lift midtones and wash out the RGB
        # image that the semantic encoder sees.
        texture.image.colorspace_settings.name = "sRGB"
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


def set_lit_texture_materials():
    """Keep textured Principled materials for the optional Sun-light ablation."""
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if principled is None:
            continue
        color = principled.inputs.get("Base Color")
        texture = next(
            (
                link.from_node
                for link in (color.links if color else [])
                if link.from_node.type == "TEX_IMAGE" and link.from_node.image
            ),
            None,
        )
        if texture is None:
            texture = next((n for n in nodes if n.type == "TEX_IMAGE" and n.image), None)
        if texture is None:
            continue
        texture.image.colorspace_settings.name = "sRGB"
        if color:
            for link in list(color.links):
                links.remove(link)
            links.new(texture.outputs["Color"], color)
        alpha = principled.inputs.get("Alpha")
        if alpha and "Alpha" in texture.outputs:
            for link in list(alpha.links):
                links.remove(link)
            links.new(texture.outputs["Alpha"], alpha)
        emission = principled.inputs.get("Emission")
        if emission:
            for link in list(emission.links):
                links.remove(link)
            emission.default_value = (0.0, 0.0, 0.0, 1.0)
        if principled.inputs.get("Roughness"):
            principled.inputs["Roughness"].default_value = 1.0
        if principled.inputs.get("Specular"):
            principled.inputs["Specular"].default_value = 0.0


def configure_sun_above(scene, target, *, energy, azimuth_deg, elevation_deg, angle_deg):
    """Add one H3-like directional Sun aimed from an above-facing direction."""
    light_data = bpy.data.lights.new("PoseFitSunAbove", type="SUN")
    light_data.energy = float(energy)
    light_data.angle = math.radians(float(angle_deg))
    light = bpy.data.objects.new("PoseFitSunAbove", light_data)
    bpy.context.collection.objects.link(light)
    azimuth = math.radians(float(azimuth_deg))
    elevation = math.radians(float(elevation_deg))
    direction = Vector((
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        -math.sin(elevation),
    )).normalized()
    light.location = Vector(target) - direction * 10.0
    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return light


def detect_profile_basis(mesh_objects, fit, *, sample_count: int = 72):
    """Find the mesh's broad/thin profile axis from its own geometry.

    The fitted camera supplies the vertical reference and the sign convention.
    We sample azimuths around that vertical axis and choose the camera direction
    with the widest, thinnest projected mesh. This is a geometry-derived profile
    candidate, not a hard-coded 180-degree assumption.
    """
    rows = fit["basisScreenRows"]
    fit_right = Vector(rows[0]).normalized()
    fit_up = (-Vector(rows[1])).normalized()
    # The fit stores screen-right and screen-up for a camera whose forward
    # ray points from the camera toward the subject.  With that convention,
    # forward = up x right; right x up is the reverse ray and puts the
    # camera behind the mesh.
    fit_forward = fit_up.cross(fit_right).normalized()
    points = []
    for obj in mesh_objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            points.append((float(world.x), float(world.y), float(world.z)))
    if len(points) < 8:
        raise RuntimeError("mesh profile detection requires at least 8 mesh vertices")
    vertices = np.asarray(points, dtype=np.float32)
    if len(vertices) > 50000:
        stride = max(1, len(vertices) // 50000)
        vertices = vertices[::stride]
    center = vertices.mean(axis=0)
    relative = vertices - center
    # The torso/head chain identifies the body longitudinal direction more
    # reliably than mesh PCA, which is dominated by the wings. Use the root
    # to upper-body displacement, remove vertical tilt, and make it screen
    # right. The camera ray is then its perpendicular side-profile direction.
    root = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if root is None:
        raise RuntimeError("mesh profile detection requires the armature")
    armature_heads = [root.matrix_world @ bone.head_local for bone in root.data.bones]
    body_axis = None
    if len(armature_heads) >= 4:
        body_axis = armature_heads[3] - armature_heads[0]
    if body_axis is None or body_axis.length < 1e-6:
        body_axis = Vector(fit_right)
    view_right = (body_axis - fit_up * body_axis.dot(fit_up)).normalized()
    if view_right.length < 1e-6:
        raise RuntimeError("mesh profile detection could not construct a screen-right axis")
    # The sprite fit says the beak/body direction is screen-right. Keep that
    # convention even if the armature's root chain is authored backwards.
    if view_right.dot(fit_right) < 0.0:
        view_right = -view_right
    view_forward = fit_up.cross(view_right).normalized()
    if view_forward.length < 1e-6:
        raise RuntimeError("mesh profile detection could not construct a side-profile camera ray")
    width = float(np.ptp(relative @ np.asarray(view_right, dtype=np.float32)))
    height = float(np.ptp(relative @ np.asarray(fit_up, dtype=np.float32)))
    thickness = float(np.ptp(relative @ np.asarray(view_forward, dtype=np.float32)))
    best = {
        "score": width / max(thickness + 0.12 * height, 1e-6),
        "angleDeg": 0.0,
        "right": view_right,
        "up": fit_up,
        "forward": view_forward,
        "width": width,
        "height": height,
        "thickness": thickness,
        "profileAlignment": abs(float(view_forward.dot(view_right))),
        "sourceAxis": "armature_root_to_upper_body_projected_to_screen",
    }
    best["fitAngleDeg"] = 0.0
    best["candidateAnglesDeg"] = [0.0, 180.0]
    best["profileConstraint"] = "fitted_side_profile_pair"
    best["vertexCount"] = int(len(vertices))
    best["right"] = [float(v) for v in best["right"]]
    best["up"] = [float(v) for v in best["up"]]
    best["forward"] = [float(v) for v in best["forward"]]
    return best


def normalize_mesh_orientation(arm, mesh_objects, fit, *, mode: str = "none"):
    """Optionally normalize a mesh into the pipeline's canonical world basis.

    This is opt-in. A provisional picker camera is expressed in the selected
    asset's source frame, so changing the mesh basis here can change a correct
    authored hand assignment even when the GLB is not mirrored. The paired
    child-bone heuristic remains available for an explicitly canonicalized
    experiment, but it must not silently reinterpret source-camera assets.
    """
    mode = str(mode or "auto").strip().lower()
    policy = str(fit.get("cameraPolicy", "")).strip().lower()
    result = {
        "mode": mode,
        "cameraPolicy": policy,
        "applied": False,
        "yawDeg": 0.0,
        "source": None,
    }
    if mode == "none":
        result["skipped"] = "disabled"
        return result
    if policy != "provisional_job_camera":
        result["skipped"] = "authoritative_camera_fit"
        return result

    bones = list(arm.data.bones)
    children: dict[str | None, list] = {}
    for bone in bones:
        children.setdefault(bone.parent.name if bone.parent else None, []).append(bone)

    candidates = []
    for parent_name, siblings in children.items():
        if len(siblings) < 2:
            continue
        for index, first in enumerate(siblings[:-1]):
            for second in siblings[index + 1:]:
                first_name = first.name.lower()
                second_name = second.name.lower()
                if "right" in first_name and "left" in second_name:
                    first, second = second, first
                first_head = arm.matrix_world @ first.head_local
                second_head = arm.matrix_world @ second.head_local
                delta = first_head - second_head
                horizontal = Vector((delta.x, delta.y, 0.0))
                length = horizontal.length
                if length < 1e-4:
                    continue
                vertical_gap = abs(float(delta.z))
                same_height = 1.0 / (1.0 + vertical_gap / max(length, 1e-6))
                parent = arm.data.bones.get(parent_name) if parent_name else None
                parent_z = 0.0 if parent is None else float((arm.matrix_world @ parent.head_local).z)
                # Prefer broad, same-height limb pairs near the lower body;
                # this avoids selecting decorative tips or wing fingers.
                lower_body_bias = 1.0 / (1.0 + max(parent_z, 0.0))
                score = float(length * same_height * (0.75 + 0.25 * lower_body_bias))
                candidates.append((score, horizontal.normalized(), parent_name, first.name, second.name))

    if not candidates:
        result["skipped"] = "no_paired_child_axis"
        return result
    _score, lateral, parent_name, first_name, second_name = max(candidates, key=lambda item: item[0])
    yaw = -math.degrees(math.atan2(float(lateral.y), float(lateral.x)))
    yaw = (yaw + 180.0) % 360.0 - 180.0
    result.update({
        "source": "paired_child_bones",
        "parent": parent_name,
        "first": first_name,
        "second": second_name,
        "lateralAxis": [float(lateral.x), float(lateral.y), float(lateral.z)],
        "yawDeg": float(yaw),
    })
    if abs(yaw) < 1e-3:
        result["skipped"] = "already_canonical"
        return result
    rotation = Matrix.Rotation(math.radians(yaw), 4, "Z")
    for obj in [arm, *mesh_objects]:
        obj.matrix_world = rotation @ obj.matrix_world
    result["applied"] = True
    return result


def setup_camera(
    fit,
    arm,
    mesh_objects,
    *,
    detect_profile: bool = True,
    profile_samples: int = 72,
    honor_fit_screen_offset: bool = False,
    fit_coordinate_basis: str = "native",
):
    rows = fit["basisScreenRows"]
    basis_mode = str(fit_coordinate_basis or "native").strip().lower()
    if basis_mode in {"gltf_to_blender", "gltf_yup_to_blender_zup"}:
        # Mesh imported from glTF is expressed in Blender's Z-up basis while
        # the GPU proxy consumes the raw glTF Y-up node coordinates.
        rows = [
            [float(row[0]), -float(row[2]), float(row[1])]
            for row in rows
        ]
    elif basis_mode != "native":
        raise ValueError(
            "fitCoordinateBasis must be native or gltf_yup_to_blender_zup"
        )
    right = Vector(rows[0]).normalized()
    # Fitted second row is image-down; Blender camera +Y is image-up.
    down = Vector(rows[1]).normalized()
    up = -down
    # basisScreenRows is [screen-right, image-down].  After converting the
    # second row to screen-up, reconstruct the camera-to-subject ray with
    # up x right.  Using right x up produces the exact opposite view.
    forward = up.cross(right).normalized()
    profile_detection = None
    camera_policy = str(fit.get("cameraPolicy", "")).strip().lower()
    # Generic picker assets use a provisional job camera whose orientation is
    # already tied to the source sprite. The Roc detector assumes a bird-like
    # root-to-body hierarchy and can turn humanoid/custom Meshy rigs backward
    # or swap their handedness, so never override a provisional source camera.
    if detect_profile and camera_policy == "provisional_job_camera":
        profile_detection = {
            "enabled": False,
            "skipped": "provisional_job_camera",
            "cameraPolicy": camera_policy,
            "sourceAxis": "fit_basis",
        }
    elif detect_profile:
        profile_detection = detect_profile_basis(
            mesh_objects,
            fit,
            sample_count=profile_samples,
        )
        right = Vector(profile_detection["right"])
        up = Vector(profile_detection["up"])
        forward = Vector(profile_detection["forward"])
    rotation = Matrix((right, up, -forward)).transposed().to_4x4()
    data = bpy.data.cameras.new("PoseFitCamera")
    data.type = "ORTHO"
    src_w, src_h = float(fit["sourceResolution"][0]), float(fit["sourceResolution"][1])
    data.ortho_scale = max(src_w, src_h) / float(fit["pxPerWorld"])
    camera = bpy.data.objects.new("PoseFitCamera", data)
    bpy.context.collection.objects.link(camera)
    heads = [arm.matrix_world @ pb.bone.head_local for pb in arm.pose.bones]
    center = sum(heads[1:], heads[0]) / float(len(heads))
    if honor_fit_screen_offset and "screenOffsetPx" in fit:
        source_width, source_height = (
            float(value) for value in fit["sourceResolution"]
        )
        offset_x, offset_y = (
            float(value) for value in fit["screenOffsetPx"]
        )
        px_per_world = float(fit["pxPerWorld"])
        # The GPU projection is p*pxPerWorld + screenOffsetPx. Move the
        # Blender camera target so its centered orthographic projection has
        # that same affine offset in source-pixel coordinates.
        center = center + right * (
            (source_width * 0.5 - offset_x) / px_per_world
            - center.dot(right)
        ) + down * (
            (source_height * 0.5 - offset_y) / px_per_world
            - center.dot(down)
        )
    camera.location = center - forward * 6.0
    camera.matrix_world = Matrix.Translation(camera.location) @ rotation
    depths = [(h - camera.location).dot(forward) for h in heads]
    near = float(min(depths))
    far = float(max(depths))
    pad = max(0.25, 0.05 * (far - near + 1e-6))
    data.clip_start = max(0.01, near - pad)
    data.clip_end = max(data.clip_start + 0.05, far + pad)
    bpy.context.scene.camera = camera
    return camera, right, up, forward, profile_detection


def _target_alpha_bounds(path: str | Path, *, threshold: int = 8):
    """Return the visible frame-00 subject bounds in source pixels."""
    if Image is None:
        raise RuntimeError("Pillow is required for automatic frame-00 camera fitting")
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha >= int(threshold))
    if xs.size == 0:
        raise ValueError(f"frame-00 target has no visible alpha: {path}")
    return {
        "width": int(rgba.shape[1]),
        "height": int(rgba.shape[0]),
        "x0": int(xs.min()),
        "y0": int(ys.min()),
        "x1": int(xs.max() + 1),
        "y1": int(ys.max() + 1),
    }


def fit_provisional_camera_to_frame0(
    camera,
    right: Vector,
    up: Vector,
    target_path: str | Path,
    *,
    alpha_threshold: int = 8,
    margin: float = 1.04,
    max_passes: int = 2,
):
    """Calibrate provisional camera scale and framing against sprite frame 00.

    Generic picker cameras are job-camera seeds, not fitted camera proof. The
    calibration therefore measures the *actual rendered alpha*, rather than
    projected object bounds. That distinction matters for rigged meshes with
    invisible helper geometry, loose bind-pose bounds, or geometry that does
    not contribute to the visible silhouette. Authoritative camera fits are
    not routed through this function.

    The worker must already have its search render state initialized. At most
    two low-resolution RGB renders are used: one measurement and one bounded
    correction pass. This is intentionally a one-time per-worker cost, not a
    per-candidate cost.
    """
    target = _target_alpha_bounds(target_path, threshold=alpha_threshold)
    target_width_frac = max((target["x1"] - target["x0"]) / target["width"], 1e-6)
    target_height_frac = max((target["y1"] - target["y0"]) / target["height"], 1e-6)
    target_center = (
        ((target["x0"] + target["x1"]) * 0.5) / target["width"],
        ((target["y0"] + target["y1"]) * 0.5) / target["height"],
    )
    before = float(camera.data.ortho_scale)
    initial = None
    final = None
    passes = []
    for pass_index in range(max(1, int(max_passes))):
        rgba, _ = render_rgb_search()
        alpha = np.asarray(rgba)[:, :, 3]
        ys, xs = np.where(alpha >= (int(alpha_threshold) / 255.0))
        if xs.size == 0:
            raise ValueError("frame-00 calibration render has no visible alpha")
        candidate = {
            "width": int(rgba.shape[1]),
            "height": int(rgba.shape[0]),
            "x0": int(xs.min()),
            "y0": int(ys.min()),
            "x1": int(xs.max() + 1),
            "y1": int(ys.max() + 1),
        }
        if initial is None:
            initial = dict(candidate)
        final = dict(candidate)
        candidate_width_frac = max((candidate["x1"] - candidate["x0"]) / candidate["width"], 1e-6)
        candidate_height_frac = max((candidate["y1"] - candidate["y0"]) / candidate["height"], 1e-6)
        width_ratio = candidate_width_frac / target_width_frac
        height_ratio = candidate_height_frac / target_height_frac
        scale_factor = math.sqrt(max(width_ratio * height_ratio, 1e-8))
        # margin is padding around the subject, so it increases ortho scale.
        scale_factor *= max(float(margin), 1.0)
        if not math.isfinite(scale_factor) or scale_factor <= 0.0:
            raise ValueError(f"invalid rendered frame-00 scale factor: {scale_factor!r}")
        view_height = float(camera.data.ortho_scale)
        view_width = view_height * candidate["width"] / max(candidate["height"], 1)
        dx_px = (
            (candidate["x0"] + candidate["x1"]) * 0.5
            - target_center[0] * candidate["width"]
        )
        dy_px = (
            (candidate["y0"] + candidate["y1"]) * 0.5
            - target_center[1] * candidate["height"]
        )
        camera.data.ortho_scale = view_height * scale_factor
        camera.location += (
            right * (dx_px * view_width / max(candidate["width"], 1))
            - up * (dy_px * view_height / max(candidate["height"], 1))
        )
        passes.append(
            {
                "pass": pass_index + 1,
                "candidateAlphaBoundsPx": [
                    candidate["x0"], candidate["y0"], candidate["x1"], candidate["y1"]
                ],
                "candidateWidthFraction": float(candidate_width_frac),
                "candidateHeightFraction": float(candidate_height_frac),
                "scaleFactor": float(scale_factor),
            }
        )
        # A second pass verifies and tightens the first correction. There is
        # no benefit in repeatedly fitting a provisional camera indefinitely.
        if pass_index + 1 >= max(1, int(max_passes)):
            break

    return {
        "enabled": True,
        "source": "rendered_frame0_alpha_bounds",
        "targetAlphaBoundsPx": [target["x0"], target["y0"], target["x1"], target["y1"]],
        "targetResolution": [target["width"], target["height"]],
        "initialCandidateAlphaBoundsPx": [
            initial["x0"], initial["y0"], initial["x1"], initial["y1"]
        ],
        "finalCandidateAlphaBoundsPx": [
            final["x0"], final["y0"], final["x1"], final["y1"]
        ],
        "orthoScaleBefore": before,
        "orthoScaleAfter": float(camera.data.ortho_scale),
        "scaleFactor": float(camera.data.ortho_scale / max(before, 1e-8)),
        "targetCenterFraction": [float(target_center[0]), float(target_center[1])],
        "passes": passes,
    }


def _socket(sockets, *names):
    for name in names:
        if name in sockets:
            return sockets[name]
    return None


def setup_depth_compositor(scene, camera, depth_dir: Path, *, pack_depth_in_rgba: bool = True):
    """Z → MapRange. Under blender -b, pack depth into Composite RGB + Alpha silhouette
    Viewer Node can expose this packed output in background mode.
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


def setup_rgb_compositor(scene):
    """Route the real render image to Composite without rebuilding depth nodes."""
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)
    composite = tree.nodes.new("CompositorNodeComposite")
    composite.location = (420, 0)
    image = _socket(rl.outputs, "Image")
    if image is None:
        raise RuntimeError("Render Layers has no Image socket")
    tree.links.new(image, composite.inputs["Image"])


def setup_rgb_depth_compositor(scene, camera, depth_dir: Path):
    """Route one render to the RGB Composite and a mapped-Z File Output.

    The search scorer needs both buffers from the same Blender render.  Keeping
    the MapRange contract identical to ``setup_depth_compositor`` avoids a
    scoring change while removing the old depth->RGB compositor flip and the
    second render it forced for semantic candidates.
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
    image = _socket(rl.outputs, "Image")
    if image is None:
        raise RuntimeError("Render Layers has no Image socket")
    tree.links.new(image, composite.inputs["Image"])

    map_range = tree.nodes.new("CompositorNodeMapRange")
    map_range.location = (300, -180)
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
        raise RuntimeError("CompositorNodeMapRange missing Value socket")
    tree.links.new(depth_out, value_in)

    alpha = _socket(rl.outputs, "Alpha")
    comb = tree.nodes.new("CompositorNodeCombRGBA")
    comb.location = (520, -180)
    for channel in ("R", "G", "B"):
        if channel in comb.inputs:
            tree.links.new(value_out, comb.inputs[channel])
    set_alpha = tree.nodes.new("CompositorNodeSetAlpha")
    set_alpha.location = (700, -180)
    tree.links.new(comb.outputs["Image"], set_alpha.inputs["Image"])
    if alpha is not None and "Alpha" in set_alpha.inputs:
        tree.links.new(alpha, set_alpha.inputs["Alpha"])

    depth_file = tree.nodes.new("CompositorNodeOutputFile")
    depth_file.location = (920, -180)
    depth_file.base_path = str(depth_dir)
    depth_file.file_slots[0].path = "depth"
    depth_file.format.file_format = "PNG"
    depth_file.format.color_mode = "RGBA"
    depth_file.format.color_depth = "8"
    tree.links.new(set_alpha.outputs["Image"], depth_file.inputs["Image"])
    return depth_dir


def _configure_png_compression(scene, compression: int) -> int:
    """Apply lossless PNG compression to both the render and depth outputs."""
    value = int(compression)
    if not 0 <= value <= 100:
        raise ValueError(f"renderPngCompression must be between 0 and 100, got {value}")
    image_settings = scene.render.image_settings
    if image_settings.file_format == "PNG" and hasattr(image_settings, "compression"):
        image_settings.compression = value
    for node in scene.node_tree.nodes:
        if node.bl_idname == "CompositorNodeOutputFile":
            output_format = node.format
            if output_format.file_format == "PNG" and hasattr(output_format, "compression"):
                output_format.compression = value
    return value


def ensure_compositor_mode(mode: str):
    """Change compositor graphs only when a candidate changes buffer type."""
    mode = str(mode).lower()
    if mode not in {"depth", "rgb", "rgb_depth"}:
        raise ValueError(f"unsupported compositor mode: {mode!r}")
    if STATE.get("compositor_mode") == mode:
        return
    scene = bpy.context.scene
    if mode == "depth":
        setup_depth_compositor(
            scene,
            STATE["camera"],
            Path(STATE["depth_dir"]),
            pack_depth_in_rgba=True,
        )
    elif mode == "rgb_depth":
        setup_rgb_depth_compositor(
            scene,
            STATE["camera"],
            Path(STATE["depth_dir"]),
        )
    else:
        setup_rgb_compositor(scene)
    _configure_png_compression(scene, int(STATE.get("render_png_compression", 0)))
    STATE["compositor_mode"] = mode


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
    """Search render with depth packed into RGB when requested."""
    ensure_search_mode()
    ensure_compositor_mode("depth")
    path = Path(STATE["render_path"])
    rgba = _render_rgba(path, mode="depth")
    depth = None
    # The depth compositor is only selected for this function, so its RGB
    # channels are always the normalized Z buffer.
    depth = np.ascontiguousarray(rgba[:, :, 0], dtype=np.float32)
    return rgba, depth


def render_rgb_search(output_path: Path | None = None) -> tuple[np.ndarray, None]:
    """Render the actual textured candidate, bypassing the depth packer.

    The dual RGB/depth path handles the primary camera in one render. This
    helper is for alternate semantic cameras and explicit RGB-only requests.
    """
    ensure_search_mode()
    ensure_compositor_mode("rgb")
    scene = bpy.context.scene
    rgb_path = Path(output_path or STATE["rgb_render_path"])
    rgb_path.parent.mkdir(parents=True, exist_ok=True)
    rgba = _render_rgba(rgb_path, mode="rgb")
    STATE["last_rgb_render_path"] = rgb_path
    return rgba, None


def render_rgb_depth_search() -> tuple[np.ndarray, np.ndarray]:
    """Render RGB and mapped depth in one Blender invocation."""
    ensure_search_mode()
    ensure_compositor_mode("rgb_depth")
    rgb_path = Path(STATE["rgb_render_path"])
    rgb_path.parent.mkdir(parents=True, exist_ok=True)
    depth_dir = Path(STATE["depth_dir"])
    depth_dir.mkdir(parents=True, exist_ok=True)
    # The depth output is a sidecar of this exact render. Remove prior sidecars
    # so a compositor failure cannot pair current RGB with an older pose.
    for stale_path in depth_dir.glob("depth*.png"):
        stale_path.unlink(missing_ok=True)
    render_started = time.time()
    rgba = _render_rgba(rgb_path, mode="rgb_depth")
    depth_path = find_latest_depth_png(
        depth_dir,
        newer_than=render_started - 0.01,
    )
    if depth_path is None:
        raise RuntimeError(
            "dual RGB/depth render did not produce a depth PNG in "
            f"{STATE['depth_dir']}"
        )
    depth_read_started = time.perf_counter()
    depth_rgba = load_rgba(depth_path)
    depth_read_seconds = time.perf_counter() - depth_read_started
    depth = np.ascontiguousarray(depth_rgba[:, :, 0], dtype=np.float32)
    timing = dict(STATE.get("last_render_timing", {}))
    timing["depthPath"] = str(depth_path)
    timing["depthReadSeconds"] = float(depth_read_seconds)
    timing["readSeconds"] = float(timing.get("readSeconds", 0.0)) + float(depth_read_seconds)
    timing["mode"] = "rgb_depth"
    STATE["last_render_timing"] = timing
    STATE["last_rgb_render_path"] = rgb_path
    return rgba, depth


def render_depth_search() -> tuple[np.ndarray, np.ndarray | None]:
    """Render a depth-packed search image even when the score mode is RGB."""
    return render_search()


def render_rgb_semantic_views(output_paths=None, *, primary_rgba=None, primary_path=None):
    """Render semantic views, reusing the primary profile when it is view zero."""
    camera = STATE["camera"]
    original_matrix = camera.matrix_world.copy()
    target = Vector(STATE.get("camera_target", camera.location + STATE["forward"] * 6.0))
    forward = Vector(STATE["forward"]).normalized()
    up = Vector(STATE["up"]).normalized()
    right = Vector(STATE["right"]).normalized()
    angles = STATE.get("semantic_view_angles_deg", (0.0, 180.0, 90.0))
    elevations = STATE.get("semantic_view_elevations_deg", (0.0, 0.0, 12.0))
    views = []
    direct_paths = []
    view_timings = []
    output_paths = list(output_paths or [])
    try:
        for angle, elevation in zip(angles, elevations):
            output_path = output_paths[len(views)] if len(output_paths) > len(views) else None
            if (
                len(views) == 0
                and primary_rgba is not None
                and abs(float(angle)) <= 1e-6
                and abs(float(elevation)) <= 1e-6
                and primary_path is not None
                and Path(primary_path).is_file()
            ):
                if output_path is not None:
                    output_path = Path(output_path).resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(primary_path, output_path)
                    direct_paths.append(output_path)
                views.append(primary_rgba)
                view_timings.append(
                    {
                        "mode": "rgb_reuse",
                        "renderSeconds": 0.0,
                        "readSeconds": 0.0,
                        "source": str(Path(primary_path).resolve()),
                    }
                )
                continue
            heading = Quaternion(up, math.radians(float(angle))) @ forward
            view_right = heading.cross(up).normalized()
            if view_right.length < 1e-6:
                view_right = right
            view_up = Quaternion(view_right, math.radians(float(elevation))) @ up
            view_forward = view_up.cross(view_right).normalized()
            rotation = Matrix((view_right, view_up, -view_forward)).transposed().to_4x4()
            camera.matrix_world = Matrix.Translation(target - view_forward * 6.0) @ rotation
            views.append(render_rgb_search(output_path)[0])
            view_timings.append(dict(STATE.get("last_render_timing", {})))
            if output_path is not None:
                direct_paths.append(Path(output_path).resolve())
    finally:
        camera.matrix_world = original_matrix
    STATE["semantic_view_direct_paths"] = direct_paths
    STATE["semantic_view_render_timings"] = view_timings
    return views


def render_search_profile(angle_deg: float):
    """Render RGB and depth from an explicit camera heading, then restore the fit camera."""
    camera = STATE["camera"]
    original_matrix = camera.matrix_world.copy()
    target = Vector(STATE.get("camera_target", camera.location + STATE["forward"] * 6.0))
    forward = Vector(STATE["forward"]).normalized()
    up = Vector(STATE["up"]).normalized()
    try:
        # The camera looks along local -Z. Build the basis from the desired
        # camera-to-subject direction instead of deriving it from a cross
        # product with the wrong sign. At 180 degrees this moves to the
        # opposite side of the mesh and reverses the visible profile.
        view_forward = (Quaternion(up, math.radians(float(angle_deg))) @ forward).normalized()
        view_right = view_forward.cross(up).normalized()
        if view_right.length < 1e-6:
            view_right = Vector(STATE["right"]).normalized()
        rotation = Matrix((view_right, up, -view_forward)).transposed().to_4x4()
        camera.matrix_world = Matrix.Translation(target - view_forward * 6.0) @ rotation
        # Profile previews use the same single-pass RGB+mapped-depth contract
        # as the primary search camera.
        rgb, depth = render_rgb_depth_search()
        profile_timing = dict(STATE.get("last_render_timing", {}))
        profile_timing["profileAngleDeg"] = float(angle_deg)
        STATE["last_profile_render_timing"] = profile_timing
        return rgb, depth
    finally:
        camera.matrix_world = original_matrix


def render_action_camera(angle_deg: float, elevation_deg: float):
    """Render the posed mesh from a front/upper action-camera view in RGB."""
    camera = STATE["camera"]
    original_matrix = camera.matrix_world.copy()
    target = Vector(STATE.get("camera_target", camera.location + STATE["forward"] * 6.0))
    forward = Vector(STATE["forward"]).normalized()
    up = Vector(STATE["up"]).normalized()
    try:
        view_forward = (Quaternion(up, math.radians(float(angle_deg))) @ forward).normalized()
        view_right = view_forward.cross(up).normalized()
        if view_right.length < 1e-6:
            view_right = Vector(STATE["right"]).normalized()
        view_up = (Quaternion(view_right, math.radians(float(elevation_deg))) @ up).normalized()
        rotation = Matrix((view_right, view_up, -view_forward)).transposed().to_4x4()
        camera.matrix_world = Matrix.Translation(target - view_forward * 6.0) @ rotation
        rgb, _ = render_rgb_search()
        return rgb
    finally:
        camera.matrix_world = original_matrix


def _asset_root_objects(arm, mesh_objects):
    """Return imported asset roots without parenting the camera or lights."""
    owned = set()
    for obj in (arm, *mesh_objects):
        current = obj
        while current is not None:
            owned.add(current)
            current = current.parent
    return sorted(
        (obj for obj in owned if obj.parent not in owned),
        key=lambda obj: obj.name,
    )


def _create_motion_root(arm, mesh_objects):
    """Create a stable parent above the imported armature/mesh hierarchy."""
    root = bpy.data.objects.new("PoseFitMotionRoot", None)
    bpy.context.collection.objects.link(root)
    root.matrix_world = Matrix.Identity(4)
    for child in _asset_root_objects(arm, mesh_objects):
        world = child.matrix_world.copy()
        child.parent = root
        child.matrix_world = world
    return root


def _motion_root_basis(right):
    """Build a model/world basis, independent of camera pixel dimensions."""
    world_up = Vector((0.0, 0.0, 1.0))
    forward = Vector(right)
    forward -= world_up * forward.dot(world_up)
    if forward.length < 1e-8:
        forward = Vector((1.0, 0.0, 0.0))
    else:
        forward.normalize()
    lateral = world_up.cross(forward)
    if lateral.length < 1e-8:
        lateral = Vector((0.0, 1.0, 0.0))
    else:
        lateral.normalize()
    return {
        "forward": forward,
        "lateral": lateral,
        "vertical": world_up,
    }


def _motion_root_length(mesh_objects, forward):
    """Measure the rest-pose mesh span used to normalize root displacement."""
    projections = []
    for obj in mesh_objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        for vertex in obj.data.vertices:
            projections.append(float((obj.matrix_world @ vertex.co).dot(forward)))
    if len(projections) >= 2:
        span = max(projections) - min(projections)
        if span > 1e-6:
            return float(span)
    corners = []
    for obj in mesh_objects:
        if obj.type != "MESH":
            continue
        corners.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if len(corners) >= 2:
        span = max(float(point.dot(forward)) for point in corners) - min(
            float(point.dot(forward)) for point in corners
        )
        if span > 1e-6:
            return float(span)
    return 1.0


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
    reuse_requested = bool(command.get("reuseAsset", False))
    if reuse_requested and not STATE.get("initialized"):
        raise RuntimeError("reuseAsset requested before the worker initialized a resident mesh")
    reuse_asset = reuse_requested
    source_path = Path(command["src"]).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"selected mesh does not exist: {source_path}")
    source_mesh_sha256 = _sha256_file(source_path)

    previous_mesh_orientation = None
    if reuse_asset:
        previous_source = Path(str(STATE.get("source_mesh", ""))).expanduser().resolve()
        previous_hash = str(STATE.get("source_mesh_sha256", ""))
        if previous_source != source_path or previous_hash != source_mesh_sha256:
            raise ValueError(
                "reuseAsset requires the same mesh path and content hash: "
                f"resident={previous_source} ({previous_hash}) "
                f"requested={source_path} ({source_mesh_sha256})"
            )
        arm = STATE.get("arm")
        mesh = STATE.get("mesh")
        if arm is None or mesh is None:
            raise RuntimeError("reuseAsset requested before a complete mesh initialization")
        resident_scale = float(STATE.get("mesh_object_scale", 1.0))
        requested_scale = float(command.get("meshScale", resident_scale))
        if abs(requested_scale - resident_scale) > 1e-9:
            raise ValueError(
                "reuseAsset cannot change meshScale without reloading the mesh: "
                f"resident={resident_scale} requested={requested_scale}"
            )
        requested_orientation_mode = str(command.get("meshOrientationMode", "none"))
        resident_orientation_mode = str(
            STATE.get("mesh_orientation_mode", requested_orientation_mode)
        )
        if requested_orientation_mode != resident_orientation_mode:
            raise ValueError(
                "reuseAsset cannot change meshOrientationMode without reloading the mesh: "
                f"resident={resident_orientation_mode!r} requested={requested_orientation_mode!r}"
            )
        previous_mesh_orientation = STATE.get("mesh_orientation")

        # Return the resident asset to its imported bind state and remove only
        # clip-owned scene objects. This keeps GLB import, armature creation,
        # texture loading, and skin setup out of every subsequent animation.
        previous_root = STATE.get("motion_root")
        if previous_root is not None:
            previous_root.matrix_world = STATE.get(
                "motion_root_rest_matrix", Matrix.Identity(4)
            ).copy()
        for pose_bone in arm.pose.bones:
            base_rotation = (STATE.get("base") or {}).get(pose_bone.name)
            if base_rotation is not None:
                pose_bone.rotation_mode = "QUATERNION"
                pose_bone.rotation_quaternion = base_rotation.copy()
        if previous_root is not None:
            for child in list(previous_root.children):
                world = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = world
            bpy.data.objects.remove(previous_root, do_unlink=True)
        for key in ("camera", "light"):
            old_object = STATE.get(key)
            if old_object is not None:
                old_data = old_object.data
                old_type = old_object.type
                bpy.data.objects.remove(old_object, do_unlink=True)
                if old_data is not None and old_data.users == 0:
                    if old_type == "CAMERA":
                        bpy.data.cameras.remove(old_data)
                    elif old_type == "LIGHT":
                        bpy.data.lights.remove(old_data)
        bpy.context.scene.camera = None
        mesh_object_scale = resident_scale
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source_path))
        arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
        mesh = next(o for o in bpy.data.objects if o.type == "MESH")
        mesh_object_scale = float(command.get("meshScale", 1.0))
    if mesh_object_scale <= 0.0:
        raise ValueError(f"meshScale must be positive, got {mesh_object_scale}")
    # Scale the imported armature and all mesh objects in world space. The
    # previous `searchScale` setting only reduced the search render buffer and
    # was therefore invisible after the preview was enlarged for display.
    if not reuse_asset and abs(mesh_object_scale - 1.0) > 1e-9:
        imported_world = {
            obj.name: obj.matrix_world.copy()
            for obj in bpy.context.scene.objects
            if obj.type in {"ARMATURE", "MESH"}
        }
        scale_matrix = Matrix.Scale(mesh_object_scale, 4)
        for name, world in imported_world.items():
            bpy.data.objects[name].matrix_world = scale_matrix @ world
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE":
            # V2's CUDA renderer implements linear blend skinning.  Keep the
            # legacy preview default, but let an exact-parity caller disable
            # Blender's dual-quaternion preserve-volume deformation.
            modifier.use_deform_preserve_volume = bool(
                command.get("useDeformPreserveVolume", True)
            )

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
    lighting_mode = str(command.get("lightingMode", "flat_emission")).lower()
    if lighting_mode not in {"flat_emission", "sun_above"}:
        raise ValueError(f"unsupported lightingMode: {lighting_mode!r}")

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
    if lighting_mode == "sun_above":
        set_lit_texture_materials()
    else:
        set_unlit_texture_materials()
    fit = json.loads(Path(command["fit"]).read_text())
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    mesh_orientation = (
        previous_mesh_orientation
        if reuse_asset
        else normalize_mesh_orientation(
            arm,
            mesh_objects,
            fit,
            mode=str(command.get("meshOrientationMode", "none")),
        )
    )
    if bool(command.get("disableArmatureDeform", False)):
        # GPU vertex overrides already contain skinned positions. Leave the
        # imported armature in bind pose and shade those triangles; a second
        # Armature modifier pass stretches the mesh into ribbons.
        for mesh_object in mesh_objects:
            _disable_armature_deform_modifiers(mesh_object)
    camera, right, up, forward, profile_detection = setup_camera(
        fit,
        arm,
        mesh_objects,
        detect_profile=bool(command.get("detectProfile", True)),
        profile_samples=int(command.get("profileSamples", 72)),
        honor_fit_screen_offset=bool(command.get("honorFitScreenOffset", False)),
        fit_coordinate_basis=str(command.get("fitCoordinateBasis", "native")),
    )
    frame0_fit = None
    frame0_fit_pending = (
        bool(command.get("autoFrame0Fit", False))
        and str(fit.get("cameraPolicy", "")).strip().lower() == "provisional_job_camera"
    )
    frame0_target = command.get("frame0Target")
    if frame0_fit_pending and not frame0_target:
        raise ValueError("autoFrame0Fit requires frame0Target")

    if lighting_mode == "sun_above":
        light = configure_sun_above(
            scene,
            arm.matrix_world.translation,
            energy=float(command.get("sunEnergy", 2.0)),
            azimuth_deg=float(command.get("sunAzimuthDeg", -35.0)),
            elevation_deg=float(command.get("sunElevationDeg", 55.0)),
            angle_deg=float(command.get("sunAngleDeg", 5.0)),
        )
    else:
        light_data = bpy.data.lights.new("PoseFitFill", type="AREA")
        light_data.energy = 50.0
        light_data.size = 5.0
        light = bpy.data.objects.new("PoseFitFill", light_data)
        bpy.context.collection.objects.link(light)
        light.location = arm.matrix_world.translation + Vector((2.0, -2.0, 4.0))

    # Keep camera fitting and delivered body motion separate. The root is
    # created after import scaling/orientation/camera fitting, so moving it
    # later translates the complete asset without changing the camera or
    # deforming the skeleton's local pose.
    motion_root = _create_motion_root(arm, mesh_objects)
    motion_root_rest_matrix = motion_root.matrix_world.copy()
    motion_root_basis_mode = str(
        command.get("motionRootBasis", "model")
    ).strip().lower()
    if motion_root_basis_mode == "camera":
        # The GPU cascade names its translation channels by camera space:
        # forward is the camera ray, lateral is screen-right, and vertical is
        # screen-up. Keep the historical model/world basis as the default for
        # the semantic-hybrid worker, but let the GPU exporter request an exact
        # coordinate contract instead of silently reinterpreting its values.
        motion_root_basis = {
            "forward": Vector(forward).normalized(),
            "lateral": Vector(right).normalized(),
            "vertical": Vector(up).normalized(),
        }
    elif motion_root_basis_mode == "model":
        motion_root_basis = _motion_root_basis(right)
    else:
        raise ValueError(
            "motionRootBasis must be model or camera, "
            f"got {motion_root_basis_mode!r}"
        )
    computed_motion_root_length_world = _motion_root_length(
        mesh_objects,
        motion_root_basis["forward"],
    )
    motion_root_length_world = float(
        command.get("motionRootLengthWorld", computed_motion_root_length_world)
    )
    if not math.isfinite(motion_root_length_world) or motion_root_length_world <= 0.0:
        raise ValueError(
            "motionRootLengthWorld must be finite and positive, "
            f"got {motion_root_length_world!r}"
        )
    motion_root_enabled = bool(command.get("motionRootEnabled", False))
    motion_root_axes = tuple(
        str(axis).strip().lower()
        for axis in command.get("motionRootAxes", ("forward",))
        if str(axis).strip().lower() in {"forward", "lateral", "vertical"}
    )
    motion_root_limits = {
        "forward": float(command.get("motionRootForwardRadiusBodyLengths", 0.20)),
        "lateral": float(command.get("motionRootLateralRadiusBodyLengths", 0.05)),
        "vertical": float(command.get("motionRootVerticalRadiusBodyLengths", 0.0)),
    }
    if motion_root_enabled and not motion_root_axes:
        raise ValueError("motionRootEnabled requires at least one motionRootAxes entry")
    for axis in motion_root_axes:
        if motion_root_limits[axis] <= 0.0:
            raise ValueError(
                f"motionRoot{axis.title()}RadiusBodyLengths must be positive when {axis!r} is enabled"
            )
    motion_root_rotation_enabled = bool(
        command.get("motionRootRotationEnabled", False)
    )
    motion_root_rotation_axes = tuple(
        str(axis).strip().lower()
        for axis in command.get(
            "motionRootRotationAxes",
            ("camera_forward",),
        )
        if str(axis).strip().lower()
        in {"camera_forward", "camera_right", "camera_up"}
    )
    motion_root_rotation_limit_deg = float(
        command.get("motionRootRotationLimitDeg", 180.0)
    )
    if motion_root_rotation_enabled and not motion_root_rotation_axes:
        raise ValueError(
            "motionRootRotationEnabled requires at least one motionRootRotationAxes entry"
        )
    if motion_root_rotation_limit_deg <= 0.0:
        raise ValueError("motionRootRotationLimitDeg must be positive")
    motion_root_rotation_basis = {
        "camera_forward": Vector(forward).normalized(),
        "camera_right": Vector(right).normalized(),
        "camera_up": Vector(up).normalized(),
    }
    motion_root_pivot_value = command.get("motionRootPivotWorld")
    if motion_root_pivot_value is None:
        motion_root_pivot = Vector(arm.matrix_world.translation)
    else:
        if not isinstance(motion_root_pivot_value, (list, tuple)) or len(motion_root_pivot_value) != 3:
            raise ValueError("motionRootPivotWorld must be a three-element world-space vector")
        motion_root_pivot = Vector(float(value) for value in motion_root_pivot_value)

    base = {}
    base_pose_matrices = {}
    parents = {}
    bone_heads = {}
    bone_vectors = {}
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        base[pb.name] = pb.rotation_quaternion.copy()
        base_pose_matrices[pb.name] = pb.matrix.copy()
        parents[pb.name] = pb.parent.name if pb.parent else None
        head = arm.matrix_world @ pb.bone.head_local
        bone_heads[pb.name] = [float(head.x), float(head.y), float(head.z)]
        bone_vectors[pb.name] = [
            float(pb.bone.vector.x),
            float(pb.bone.vector.y),
            float(pb.bone.vector.z),
        ]
    semantic_camera_target = sum(
        (arm.matrix_world @ pb.bone.head_local for pb in arm.pose.bones),
        Vector(),
    ) / max(len(arm.pose.bones), 1)
    # Keep Blender math types inside the worker.  STATE is also used to build
    # command/diagnostic payloads, so values crossing that boundary must stay
    # JSON-compatible.
    semantic_camera_target_json = [
        float(semantic_camera_target.x),
        float(semantic_camera_target.y),
        float(semantic_camera_target.z),
    ]

    work = Path(tempfile.mkdtemp(prefix="pose_fit_worker_"))
    render_path = work / "capture.png"
    rgb_render_path = work / "capture_rgb.png"
    primary_rgb_snapshot_path = work / "capture_primary_rgb.png"
    depth_dir = work / "depth"
    render_png_compression = int(command.get("renderPngCompression", 0))
    if not 0 <= render_png_compression <= 100:
        raise ValueError(
            f"renderPngCompression must be between 0 and 100, got {render_png_compression}"
        )
    render_depth_default = bool(command.get("renderDepth", score_mode == "depth"))
    render_result_in_memory = bool(command.get("renderResultInMemory", False))
    if render_depth_default:
        setup_rgb_depth_compositor(
            scene,
            camera,
            depth_dir,
        )
    else:
        setup_rgb_compositor(scene)

    _configure_engine(search_engine, width=search_w, height=search_h, taa_samples=search_taa)
    _configure_png_compression(scene, render_png_compression)
    scene.render.filepath = str(render_path)

    STATE.clear()
    STATE.update(
        {
            "arm": arm,
            "mesh": mesh,
            "initialized": True,
            "motion_root": motion_root,
            "motion_root_rest_matrix": motion_root_rest_matrix,
            "motion_root_basis": motion_root_basis,
            "motion_root_basis_mode": motion_root_basis_mode,
            "motion_root_length_world": float(motion_root_length_world),
            "motion_root_enabled": motion_root_enabled,
            "motion_root_axes": motion_root_axes,
            "motion_root_limits": motion_root_limits,
            "motion_root_values": {axis: 0.0 for axis in ("forward", "lateral", "vertical")},
            "motion_root_rotation_enabled": motion_root_rotation_enabled,
            "motion_root_rotation_axes": motion_root_rotation_axes,
            "motion_root_rotation_limit_deg": motion_root_rotation_limit_deg,
            "motion_root_rotation_basis": motion_root_rotation_basis,
            "motion_root_rotation_values": {
                axis: 0.0
                for axis in ("camera_forward", "camera_right", "camera_up")
            },
            "motion_root_pivot": motion_root_pivot,
            "camera": camera,
            "base": base,
            "base_pose_matrices": base_pose_matrices,
            "right": right,
            "up": up,
            "forward": forward,
            "full_w": full_w,
            "full_h": full_h,
            "search_w": search_w,
            "search_h": search_h,
            "search_scale": search_scale,
            "mesh_object_scale": mesh_object_scale,
            "mesh_orientation_mode": str(command.get("meshOrientationMode", "none")),
            "search_engine": search_engine,
            "search_taa": search_taa,
            "proof_engine": proof_engine,
            "proof_taa": proof_taa,
            "render_path": render_path,
            "rgb_render_path": rgb_render_path,
            "primary_rgb_snapshot_path": primary_rgb_snapshot_path,
            "depth_dir": depth_dir,
            "score_mode": score_mode,
            "color_max_dist": float(command.get("colorMaxDist", 0.30)),
            "depth_max_dist": float(command.get("depthMaxDist", 0.35)),
            "pred_only_penalty": float(command.get("predOnlyPenalty", 2.0)),
            "target_only_penalty": float(command.get("targetOnlyPenalty", 1.0)),
            "target_edge_sigma_px": float(command.get("targetEdgeSigmaPx", 4.0)),
            "target_edge_floor": float(command.get("targetEdgeFloor", 0.25)),
            "target_edge_bonus": float(command.get("targetEdgeBonus", 0.0)),
            "profile_half_bias": float(command.get("profileHalfBias", 0.5)),
            "targets": {},
            "mode": "search",
            "pack_depth_in_rgba": render_depth_default,
            "render_depth_default": render_depth_default,
            "render_result_in_memory": render_result_in_memory,
            "render_png_compression": render_png_compression,
            "incremental_pose_application": bool(command.get("incrementalPoseApplication", True)),
            "pose_cache_valid": False,
            "last_strip_roll": None,
            "compositor_mode": "rgb_depth" if render_depth_default else "rgb",
            "strip_bone_roll": bool(command.get("stripBoneRoll", True)),
            "strip_bone_roll_by_bone": {
                str(name): str(policy).lower()
                for name, policy in dict(command.get("stripBoneRollByBone", {}) or {}).items()
            },
            "camera_target": semantic_camera_target_json,
            "arm_rest_location": [
                float(arm.matrix_world.translation.x),
                float(arm.matrix_world.translation.y),
                float(arm.matrix_world.translation.z),
            ],
            "body_translation_px": (0.0, 0.0),
            "semantic_view_angles_deg": tuple(command.get("semanticViewAnglesDeg", (0.0, 180.0, 90.0))),
            "semantic_view_elevations_deg": tuple(command.get("semanticViewElevationsDeg", (0.0, 0.0, 12.0))),
            "ik_enabled": bool(command.get("ikEnabled", False)),
            "ik_mode": str(command.get("ikMode", "off")).lower(),
            "ik_bones": tuple(command.get("ikBones", ())),
            "ik_targets": dict(command.get("ikTargets", {}) or {}),
            "ik_chain_length": int(command.get("ikChainLength", 1)),
            "ik_iterations": int(command.get("ikIterations", 8)),
            "ik_strength": float(command.get("ikStrength", 1.0)),
            "ik_depth": float(command.get("ikDepth", 6.0)),
            "profile_detection": profile_detection,
            "mesh_orientation": mesh_orientation,
            "frame0_fit": frame0_fit,
            "light": light,
            "source_mesh": str(source_path),
            "source_mesh_sha256": source_mesh_sha256,
        }
    )

    if frame0_fit_pending:
        # The camera is calibrated from the actual RGB alpha after the worker
        # state and compositor are ready. Projected object bounds are not a
        # reliable proxy for a visible skinned silhouette.
        frame0_fit = fit_provisional_camera_to_frame0(
            camera,
            right,
            up,
            frame0_target,
            alpha_threshold=int(command.get("frame0AlphaThreshold", 8)),
            margin=float(command.get("frame0FitMargin", 1.04)),
            max_passes=int(command.get("frame0FitPasses", 2)),
        )
        STATE["frame0_fit"] = frame0_fit
        # Camera translation changes the visible depth interval. Refresh the
        # clip planes so the calibrated camera and depth compositor agree.
        depths = [
            float((arm.matrix_world @ pb.bone.head_local - camera.location).dot(forward))
            for pb in arm.pose.bones
        ]
        near, far = min(depths), max(depths)
        pad = max(0.25, 0.05 * (far - near + 1e-6))
        camera.data.clip_start = max(0.01, near - pad)
        camera.data.clip_end = max(camera.data.clip_start + 0.05, far + pad)
        ensure_compositor_mode("rgb_depth" if render_depth_default else "rgb")

    bpy.ops.render.render(write_still=False)

    emit(
        {
            "ok": True,
            "bones": [pb.name for pb in arm.pose.bones],
            "parents": parents,
            "boneHeads": bone_heads,
            "boneVectors": bone_vectors,
            "view": [float(forward.x), float(forward.y), float(forward.z)],
            "right": [float(right.x), float(right.y), float(right.z)],
            "up": [float(up.x), float(up.y), float(up.z)],
            "cameraLocation": [
                float(camera.location.x),
                float(camera.location.y),
                float(camera.location.z),
            ],
            "cameraOrthoScale": float(camera.data.ortho_scale),
            "width": full_w,
            "height": full_h,
            "searchWidth": search_w,
            "searchHeight": search_h,
            "searchScale": search_scale,
            "meshScale": mesh_object_scale,
            "sourceMesh": str(source_path),
            "sourceMeshSha256": source_mesh_sha256,
            "assetReused": bool(reuse_asset),
            "camera_target": semantic_camera_target_json,
            "profileDetection": profile_detection,
            "meshOrientation": mesh_orientation,
            "frame0Fit": frame0_fit,
            "motionRoot": {
                "enabled": motion_root_enabled,
                "axes": list(motion_root_axes),
                "limitsBodyLengths": dict(motion_root_limits),
                "object": motion_root.name,
                "referenceLengthWorld": float(motion_root_length_world),
                "basis": {
                    axis: [float(value) for value in vector]
                    for axis, vector in motion_root_basis.items()
                },
                "restTranslation": [
                    float(value) for value in motion_root_rest_matrix.translation
                ],
                "rotation": {
                    "enabled": motion_root_rotation_enabled,
                    "basis": "camera",
                    "axes": list(motion_root_rotation_axes),
                    "limitDeg": float(motion_root_rotation_limit_deg),
                    "pivot": [float(value) for value in motion_root_pivot],
                    "basisVectors": {
                        axis: [float(value) for value in vector]
                        for axis, vector in motion_root_rotation_basis.items()
                    },
                },
            },
            "semantic_view_angles_deg": list(command.get("semanticViewAnglesDeg", (0.0, 180.0, 90.0))),
            "semantic_view_elevations_deg": list(command.get("semanticViewElevationsDeg", (0.0, 0.0, 12.0))),
            "searchEngine": search_engine,
            "proofEngine": proof_engine,
            "lightingMode": lighting_mode,
            "sunEnergy": float(command.get("sunEnergy", 2.0)),
            "sunAzimuthDeg": float(command.get("sunAzimuthDeg", -35.0)),
            "sunElevationDeg": float(command.get("sunElevationDeg", 55.0)),
            "sunAngleDeg": float(command.get("sunAngleDeg", 5.0)),
            "scoreMode": score_mode,
            "renderDepthDefault": render_depth_default,
            "compositorMode": STATE.get("compositor_mode"),
            "renderResultInMemory": bool(STATE.get("render_result_in_memory", False)),
            "renderPngCompression": int(STATE.get("render_png_compression", 0)),
            "incrementalPoseApplication": bool(STATE.get("incremental_pose_application", True)),
            "predOnlyPenalty": float(STATE["pred_only_penalty"]),
            "targetOnlyPenalty": float(STATE["target_only_penalty"]),
            "targetEdgeBonus": float(STATE["target_edge_bonus"]),
            "profileHalfBias": float(STATE["profile_half_bias"]),
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
    if command.get("meshVerticesWorld"):
        # Disable skinning before any pose application. apply_pose must not
        # re-deform vertices that the GPU already skinned.
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                _disable_armature_deform_modifiers(obj)
    apply_pose(command)
    result = {"ok": True}
    if "meshVerticesWorld" in command:
        result["meshVerticesChanged"] = int(_apply_mesh_vertex_override(command))
    if bool(command.get("returnPoseDebug", False)):
        arm = STATE["arm"]
        result["poseDebug"] = {
            pb.name: {
                "matrixWorld": [
                    [float(value) for value in row]
                    for row in (arm.matrix_world @ pb.matrix)
                ],
                "headWorld": [
                    float(value)
                    for value in (arm.matrix_world @ Vector(pb.head))
                ],
                "tailWorld": [
                    float(value)
                    for value in (arm.matrix_world @ Vector(pb.tail))
                ],
            }
            for pb in arm.pose.bones
        }
    emit(result)


def _axis_angle_quat(axis, angle: float) -> Quaternion:
    """Build an axis-angle quaternion from a named or arbitrary unit axis."""
    if isinstance(axis, str):
        axis = axis.lower()
        if axis == "x":
            axis = (1.0, 0.0, 0.0)
        elif axis == "y":
            axis = (0.0, 1.0, 0.0)
        elif axis == "z":
            axis = (0.0, 0.0, 1.0)
        else:
            raise ValueError(f"unsupported rotation axis: {axis!r}")
    axis_vector = Vector(tuple(float(part) for part in axis))
    if axis_vector.length_squared < 1e-16:
        raise ValueError("rotation axis cannot have zero length")
    axis_vector.normalize()
    return Quaternion(axis_vector, float(angle))


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
        if "quaternion" in value:
            raw = value["quaternion"]
            if not isinstance(raw, (list, tuple)) or len(raw) != 4:
                raise ValueError("quaternion pose entries must contain four values")
            order = str(value.get("quaternionOrder", "wxyz")).lower()
            if order == "wxyz":
                components = [float(part) for part in raw]
            elif order == "xyzw":
                components = [float(raw[3]), float(raw[0]), float(raw[1]), float(raw[2])]
            else:
                raise ValueError("quaternionOrder must be wxyz or xyzw")
            if not all(math.isfinite(part) for part in components):
                raise ValueError("quaternion pose entries must be finite")
            quaternion = Quaternion(tuple(components))
            if quaternion.magnitude < 1e-12:
                raise ValueError("quaternion pose entry cannot have zero magnitude")
            quaternion.normalize()
            return quaternion
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


def _ik_target_world(target, depth: float) -> Vector:
    """Convert a normalized image point into a point on the orthographic camera plane."""
    if isinstance(target, dict):
        x = float(target["x"])
        y = float(target["y"])
        depth = float(target.get("depth", depth))
    else:
        if len(target) < 2:
            raise ValueError("IK target must contain normalized x and y")
        x, y = float(target[0]), float(target[1])
        if len(target) > 2:
            depth = float(target[2])
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"IK target must be normalized to [0,1], got {(x, y)}")
    camera = STATE["camera"]
    right = Vector(STATE["right"]).normalized()
    up = Vector(STATE["up"]).normalized()
    forward = Vector(STATE["forward"]).normalized()
    height = float(camera.data.ortho_scale)
    width = height * float(STATE["full_w"]) / max(float(STATE["full_h"]), 1.0)
    center = camera.location + forward * float(depth)
    return center + right * ((x - 0.5) * width) + up * ((0.5 - y) * height)


def _apply_ik(command):
    mode = str(command.get("ikMode", STATE.get("ik_mode", "off"))).lower()
    enabled = bool(command.get("ikEnabled", STATE.get("ik_enabled", False)))
    if not enabled or mode == "off":
        return
    if mode not in {"replace", "replace_all", "add", "add_all"}:
        raise ValueError("ikMode must be off, replace, replace_all, add, or add_all")
    targets = command.get("ikTargets", STATE.get("ik_targets", {})) or {}
    requested_bones = list(command.get("ikBones", STATE.get("ik_bones", ())) or ())
    arm = STATE["arm"]
    # All modes accept target keys as the selected set when ikBones is empty.
    # For replace_all/add_all this is the intended contract: the caller says
    # whether rotation is replaced/retained globally, while the target map
    # supplies the image-space endpoints that actually have IK destinations.
    names = requested_bones or list(targets.keys())
    if not names:
        raise ValueError(
            f"ikMode={mode} requires ikTargets; ikBones is optional, but IK "
            "cannot solve without image-space destinations"
        )
    missing_targets = [name for name in names if name not in targets]
    if missing_targets:
        preview = ", ".join(missing_targets[:8])
        suffix = "..." if len(missing_targets) > 8 else ""
        raise ValueError(
            f"ikMode={mode} requires an ikTargets entry for every selected pose bone; "
            f"missing {preview}{suffix}"
        )
    arm_inv = arm.matrix_world.inverted()
    iterations = max(1, int(command.get("ikIterations", STATE.get("ik_iterations", 8))))
    chain_length = max(1, int(command.get("ikChainLength", STATE.get("ik_chain_length", 1))))
    strength = min(1.0, max(0.0, float(command.get("ikStrength", STATE.get("ik_strength", 1.0)))))
    depth = float(command.get("ikDepth", STATE.get("ik_depth", 6.0)))
    for name in names:
        if name not in arm.pose.bones:
            raise ValueError(f"IK bone is not present in armature: {name}")
        end = arm.pose.bones[name]
        chain = []
        joint = end
        for _ in range(chain_length):
            if joint is None:
                break
            chain.append(joint)
            joint = joint.parent
        target_world = _ik_target_world(targets[name], depth)
        for _ in range(iterations):
            end_world = arm.matrix_world @ Vector(end.tail)
            if (target_world - end_world).length < 1e-4:
                break
            for joint in reversed(chain):
                joint_world = arm.matrix_world @ Vector(joint.head)
                current = end_world - joint_world
                desired = target_world - joint_world
                if current.length < 1e-8 or desired.length < 1e-8:
                    continue
                delta = current.normalized().rotation_difference(desired.normalized())
                if strength < 1.0:
                    delta = Quaternion().slerp(delta, strength)
                world_matrix = arm.matrix_world @ joint.matrix
                pivot = Matrix.Translation(joint_world)
                unpivot = Matrix.Translation(-joint_world)
                joint.matrix = arm_inv @ pivot @ delta.to_matrix().to_4x4() @ unpivot @ world_matrix
                bpy.context.view_layer.update()
                end_world = arm.matrix_world @ Vector(end.tail)


def _quaternion_close(left: Quaternion, right: Quaternion, tolerance: float = 1e-10) -> bool:
    """Compare rotations by orientation, ignoring quaternion sign."""
    left_n = left.normalized()
    right_n = right.normalized()
    return 1.0 - abs(float(left_n.dot(right_n))) <= tolerance


def _desired_direct_pose(command):
    """Build the absolute local pose requested by a score command."""
    arm = STATE["arm"]
    strip_roll = bool(command.get("stripBoneRoll", STATE.get("strip_bone_roll", True)))
    strip_roll_by_bone = {
        str(name): str(policy).lower()
        for name, policy in dict(
            command.get(
                "stripBoneRollByBone",
                STATE.get("strip_bone_roll_by_bone", {}),
            )
            or {}
        ).items()
    }
    ik_mode = str(command.get("ikMode", STATE.get("ik_mode", "off"))).lower()
    ik_enabled = bool(command.get("ikEnabled", STATE.get("ik_enabled", False)))
    ik_bones = set(command.get("ikBones", STATE.get("ik_bones", ())) or ())
    if not ik_bones and ik_mode in {"replace", "add"}:
        ik_bones = set((command.get("ikTargets", STATE.get("ik_targets", {})) or {}).keys())
    all_ik = ik_enabled and ik_mode in {"replace_all", "add_all"}
    desired = {pb.name: STATE["base"][pb.name].copy() for pb in arm.pose.bones}
    for name, value in command.get("angles", {}).items():
        if name not in arm.pose.bones:
            continue
        if all_ik and ik_mode == "replace_all":
            continue
        if ik_mode == "replace" and name in ik_bones:
            continue
        delta = _bone_delta_quat(value)
        twist_policy = None
        if isinstance(value, dict):
            twist_policy = str(value.get("twistPolicy", "")).lower().strip() or None
        twist_policy = twist_policy or strip_roll_by_bone.get(name)
        should_strip_roll = strip_roll
        if twist_policy == "include":
            should_strip_roll = False
        elif twist_policy == "exclude":
            should_strip_roll = True
        elif twist_policy not in {None, "adaptive"}:
            raise ValueError(
                f"unsupported twistPolicy for bone {name!r}: {twist_policy!r}"
            )
        if should_strip_roll:
            twist_axis = arm.pose.bones[name].bone.vector.copy()
            if twist_axis.length_squared < 1e-16:
                twist_axis = Vector((0.0, 1.0, 0.0))
            delta = _strip_twist(delta, twist_axis)
        desired[name] = STATE["base"][name] @ delta
    return desired, ik_enabled, ik_mode, strip_roll


def _desired_direct_pose_matrices(command):
    """Build absolute Blender pose matrices from GPU deformation matrices.

    A glTF node's local axes are not generally the same as a Blender pose
    bone's rolled local axes. Applying a rotation-vector axis by axis is
    therefore not an exact retarget. The GPU exporter can instead send the
    relative skinning deformation for each bone. Applying that deformation to
    the imported bind pose preserves Meshy's authored bone rolls while
    reproducing the proxy's joint transform.
    """
    raw = command.get("boneDeformationMatrices")
    if not isinstance(raw, dict):
        return None
    arm = STATE["arm"]
    base_matrices = STATE.get("base_pose_matrices") or {}
    if not base_matrices:
        raise RuntimeError("bone deformation mode requires imported bind pose matrices")
    desired = {}
    for pb in arm.pose.bones:
        value = raw.get(pb.name)
        if value is None:
            deformation = Matrix.Identity(4)
        else:
            try:
                deformation = Matrix(value)
            except Exception as exc:
                raise ValueError(
                    f"boneDeformationMatrices[{pb.name!r}] must be a 4x4 matrix"
                ) from exc
            if len(deformation) != 4 or any(len(row) != 4 for row in deformation):
                raise ValueError(
                    f"boneDeformationMatrices[{pb.name!r}] must be a 4x4 matrix"
                )
        base_world = arm.matrix_world @ base_matrices[pb.name]
        desired[pb.name] = arm.matrix_world.inverted() @ deformation @ base_world
    return desired


def _apply_motion_root(command):
    """Apply translation and camera-relative rigid-body rotation above the rig."""
    root = STATE["motion_root"]
    rest = STATE["motion_root_rest_matrix"]
    translation_enabled = bool(STATE.get("motion_root_enabled", False))
    rotation_enabled = bool(STATE.get("motion_root_rotation_enabled", False))
    if not translation_enabled and not rotation_enabled:
        root.matrix_world = rest.copy()
        STATE["motion_root_values"] = {
            axis: 0.0 for axis in ("forward", "lateral", "vertical")
        }
        STATE["motion_root_rotation_values"] = {
            axis: 0.0
            for axis in ("camera_forward", "camera_right", "camera_up")
        }
        STATE["body_translation_px"] = (0.0, 0.0)
        return
    angles = command.get("angles", {})
    motion_root = command.get("motionRoot")
    if motion_root is None and isinstance(angles, dict):
        motion_root = angles.get("__motion_root__")

    values = {axis: 0.0 for axis in ("forward", "lateral", "vertical")}
    displacement = Vector()
    if isinstance(motion_root, dict) and any(
        axis in motion_root for axis in ("forward", "lateral", "vertical")
    ):
        for axis in values:
            raw_value = float(motion_root.get(axis, 0.0))
            if not translation_enabled:
                if abs(raw_value) > 1e-8:
                    raise ValueError(
                        f"motion root translation is disabled but received {axis}={raw_value:g}"
                    )
                continue
            if axis not in STATE["motion_root_axes"]:
                if abs(raw_value) > 1e-8:
                    raise ValueError(
                        f"motion root axis {axis!r} is disabled but received {raw_value:g}"
                    )
                continue
            limit = float(STATE["motion_root_limits"][axis])
            if abs(raw_value) > limit + 1e-8:
                raise ValueError(
                    f"motion root {axis!r}={raw_value:g} exceeds configured limit +/-{limit:g}"
                )
            values[axis] = raw_value
        basis = STATE["motion_root_basis"]
        displacement = sum(
            (
                basis[axis]
                * values[axis]
                * float(STATE["motion_root_length_world"])
                for axis in ("forward", "lateral", "vertical")
            ),
            Vector(),
        )
    elif translation_enabled and "bodyTranslationPx" in command:
        # Old callers supplied image-space [right, up] pixels. Keep that
        # compatibility path explicit and separate from normalized root units.
        translation = command.get("bodyTranslationPx", (0.0, 0.0))
        if isinstance(translation, dict):
            translation = (translation.get("x", 0.0), translation.get("y", 0.0))
        if not isinstance(translation, (list, tuple)) or len(translation) != 2:
            raise ValueError("bodyTranslationPx must be a two-element [right, up] pair")
        tx_px, ty_px = (float(translation[0]), float(translation[1]))
        camera = STATE["camera"]
        px_world_x = float(camera.data.ortho_scale) / max(float(STATE["full_w"]), 1.0)
        px_world_y = float(camera.data.ortho_scale) / max(float(STATE["full_h"]), 1.0)
        displacement = STATE["right"] * (tx_px * px_world_x) + STATE["up"] * (ty_px * px_world_y)
        STATE["body_translation_px"] = (tx_px, ty_px)
    else:
        STATE["body_translation_px"] = (0.0, 0.0)

    rotation_request = command.get("motionRootRotation")
    if rotation_request is None and isinstance(angles, dict):
        rotation_request = angles.get("__motion_root_rotation__")
    rotation_values = {
        axis: 0.0
        for axis in ("camera_forward", "camera_right", "camera_up")
    }
    world_rotation = Quaternion()
    if isinstance(rotation_request, dict) and any(
        axis in rotation_request
        for axis in ("camera_forward", "camera_right", "camera_up")
    ):
        for axis in rotation_values:
            raw_value = float(rotation_request.get(axis, 0.0))
            if not rotation_enabled:
                if abs(raw_value) > 1e-8:
                    raise ValueError(
                        f"motion root rotation is disabled but received {axis}={raw_value:g}"
                    )
                continue
            if axis not in STATE["motion_root_rotation_axes"]:
                if abs(raw_value) > 1e-8:
                    raise ValueError(
                        f"motion root rotation axis {axis!r} is disabled but received {raw_value:g}"
                    )
                continue
            limit = float(STATE["motion_root_rotation_limit_deg"])
            if abs(raw_value) > limit + 1e-8:
                raise ValueError(
                    f"motion root rotation {axis!r}={raw_value:g} exceeds configured limit +/-{limit:g}"
                )
            rotation_values[axis] = raw_value
            world_rotation = (
                Quaternion(
                    STATE["motion_root_rotation_basis"][axis],
                    math.radians(raw_value),
                )
                @ world_rotation
            )
    elif not rotation_enabled:
        rotation_values = {
            axis: 0.0
            for axis in ("camera_forward", "camera_right", "camera_up")
        }

    # Rotate around the armature origin rather than the identity Empty's
    # world origin. The parent remains above the imported hierarchy, so this
    # cannot change local Meshy bone dependencies or skinning behavior.
    pivot = Vector(STATE["motion_root_pivot"])
    rotation_about_pivot = (
        Matrix.Translation(pivot)
        @ world_rotation.to_matrix().to_4x4()
        @ Matrix.Translation(-pivot)
    )
    root.matrix_world = Matrix.Translation(displacement) @ rotation_about_pivot @ rest
    STATE["motion_root_values"] = values
    STATE["motion_root_rotation_values"] = rotation_values
    length = max(float(STATE["motion_root_length_world"]), 1e-8)
    if isinstance(motion_root, dict) and any(
        axis in motion_root for axis in ("forward", "lateral", "vertical")
    ):
        STATE["motion_root_values"] = {
            axis: float(
                displacement.dot(STATE["motion_root_basis"][axis]) / length
            )
            for axis in ("forward", "lateral", "vertical")
        }


def apply_pose(command):
    arm = STATE["arm"]
    ik_mode = str(command.get("ikMode", STATE.get("ik_mode", "off"))).lower()
    ik_enabled = bool(command.get("ikEnabled", STATE.get("ik_enabled", False)))
    if ik_mode in {"replace_all", "add_all"} and not ik_enabled:
        raise ValueError(f"ikMode={ik_mode} requires ikEnabled=True")
    started = time.perf_counter()
    _apply_motion_root(command)
    desired_matrices = _desired_direct_pose_matrices(command)
    if desired_matrices is None:
        desired, desired_ik_enabled, desired_ik_mode, strip_roll = _desired_direct_pose(command)
    else:
        desired = None
        desired_ik_enabled, desired_ik_mode, strip_roll = False, "off", False
    incremental_allowed = bool(
        command.get(
            "incrementalPoseApplication",
            STATE.get("incremental_pose_application", True),
        )
        and STATE.get("pose_cache_valid", False)
        and not ik_enabled
        and ik_mode == "off"
        and not desired_ik_enabled
        and desired_ik_mode == "off"
        and desired_matrices is None
        and STATE.get("last_strip_roll") == strip_roll
        and isinstance(STATE.get("last_direct_pose"), dict)
    )
    changed = 0
    if desired_matrices is not None:
        def pose_depth(pose_bone):
            depth = 0
            parent = pose_bone.parent
            while parent is not None:
                depth += 1
                parent = parent.parent
            return depth

        # Imported glTF node order is not guaranteed to be parent-first.
        # Absolute pose matrices must be assigned from the roots outward so a
        # child is converted against its final parent transform.
        for pb in sorted(arm.pose.bones, key=pose_depth):
            pb.matrix = desired_matrices[pb.name]
            bpy.context.view_layer.update()
        changed = len(desired_matrices)
    elif incremental_allowed:
        previous = STATE["last_direct_pose"]
        for pb in arm.pose.bones:
            target = desired[pb.name]
            if not _quaternion_close(previous[pb.name], target):
                pb.rotation_quaternion = target
                changed += 1
    else:
        for pb in arm.pose.bones:
            pb.rotation_quaternion = desired[pb.name]
        changed = len(desired)
    bpy.context.view_layer.update()
    if ik_enabled or ik_mode != "off":
        _apply_ik(command)
        STATE["pose_cache_valid"] = False
    else:
        STATE["pose_cache_valid"] = True
    STATE["last_strip_roll"] = strip_roll
    STATE["last_direct_pose"] = desired or {}
    STATE["last_pose_timing"] = {
        "seconds": time.perf_counter() - started,
        "incremental": bool(incremental_allowed),
        "changedBones": int(changed),
    }


def _disable_armature_deform_modifiers(obj) -> int:
    """Stop Blender from skinning vertices the GPU already deformed."""
    disabled = 0
    for modifier in obj.modifiers:
        if modifier.type != "ARMATURE":
            continue
        modifier.show_viewport = False
        modifier.show_render = False
        disabled += 1
    return disabled


def _refresh_camera_clip_from_mesh_vertices() -> None:
    """Keep the orthographic camera from clipping GPU-posed mesh parts.

    The init camera clip is measured from bind-pose bone heads. After the GPU
    vertex override, the visible mesh can sit in a different depth interval,
    and a leftover bind-bone clip range shears the proof into fragments.
    """
    camera = STATE.get("camera")
    forward = STATE.get("forward")
    if camera is None or forward is None:
        return
    forward = Vector(forward).normalized()
    depths = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            depths.append(float((world - camera.location).dot(forward)))
    if not depths:
        return
    near, far = min(depths), max(depths)
    pad = max(0.25, 0.05 * (far - near + 1e-6))
    camera.data.clip_start = max(0.01, near - pad)
    camera.data.clip_end = max(camera.data.clip_start + 0.05, far + pad)


def _apply_mesh_vertex_override(command):
    """Write an exact GPU-deformed vertex buffer into the imported mesh.

    This is an export/preview bridge, not an optimizer path.  It deliberately
    bypasses Blender's armature solver after the GPU has already evaluated the
    same LBS triangles.  That gives the final lit render the identical
    geometry used by the CUDA silhouette preview instead of asking Blender to
    reinterpret a rolled, connected Meshy hierarchy a second time.
    """
    raw = command.get("meshVerticesWorld")
    if not isinstance(raw, dict) or not raw:
        return 0
    changed = 0
    for object_name, values in raw.items():
        obj = bpy.data.objects.get(str(object_name))
        if obj is None or obj.type != "MESH":
            raise ValueError(
                f"meshVerticesWorld target is not an imported mesh object: {object_name!r}"
            )
        _disable_armature_deform_modifiers(obj)
        if not isinstance(values, (list, tuple)) or len(values) != len(obj.data.vertices):
            raise ValueError(
                f"meshVerticesWorld[{object_name!r}] must contain "
                f"{len(obj.data.vertices)} vertices, got "
                f"{len(values) if isinstance(values, (list, tuple)) else 'invalid'}"
            )
        inverse_world = obj.matrix_world.inverted()
        for vertex, value in zip(obj.data.vertices, values):
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise ValueError(
                    f"meshVerticesWorld[{object_name!r}] entries must be [x, y, z]"
                )
            vertex.co = inverse_world @ Vector(
                (float(value[0]), float(value[1]), float(value[2]))
            )
        obj.data.update()
        try:
            obj.data.calc_normals()
        except AttributeError:
            # Blender 3.5 updates mesh normals during the depsgraph update;
            # newer builds may expose an explicit calculation method.
            pass
        changed += len(values)
    bpy.context.view_layer.update()
    _refresh_camera_clip_from_mesh_vertices()
    return changed


def _render_rgba(path: Path, *, mode: str) -> np.ndarray:
    """Render one search buffer, preferring Render Result over PNG I/O."""
    path = Path(path)
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    prefer_memory = bool(STATE.get("render_result_in_memory", False))
    started = time.perf_counter()
    use_still = bool(getattr(bpy.app, "background", True)) and not prefer_memory
    bpy.ops.render.render(write_still=use_still)
    render_seconds = time.perf_counter() - started
    source = "render_result"
    fallback_render_seconds = 0.0
    read_started = time.perf_counter()
    if use_still:
        rgba = load_rgba(path)
        source = "png"
    else:
        try:
            rgba = _blender_image_rgba("Render Result")
        except RuntimeError:
            # Blender 3.5 background mode can leave Render Result empty for a
            # compositor output. Preserve correctness, but expose the fallback.
            fallback_started = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            fallback_render_seconds = time.perf_counter() - fallback_started
            render_seconds += fallback_render_seconds
            rgba = load_rgba(path)
            source = "png_fallback"
            # Probe once. Blender 3.5.1 background mode does not expose this
            # compositor output in Render Result, so retrying it per candidate
            # would add a second render to every evaluation.
            STATE["render_result_in_memory"] = False
            STATE["render_result_fallback_reason"] = "background_render_result_empty"
    STATE["last_render_timing"] = {
        "mode": str(mode),
        "renderSeconds": float(render_seconds),
        "renderCount": 2 if fallback_render_seconds > 0.0 else 1,
        "fallbackRenderSeconds": float(fallback_render_seconds),
        "readSeconds": float(time.perf_counter() - read_started),
        "source": source,
    }
    return rgba


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
    *,
    normalized_target: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Stretch both, then histogram-match mesh→sprite so metric Z does not invent darker range."""
    t = (
        np.asarray(normalized_target, dtype=np.float32)
        if normalized_target is not None
        else normalize_depth_range(target_depth, target_mask)
    )
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
    normalized_target_depth = None
    if depth_file is not None:
        target_depth = load_depth01(depth_file, STATE["search_w"], STATE["search_h"])
        target_depth = target_depth * (alpha > 0).astype(np.float32)
        normalized_target_depth = normalize_depth_range(target_depth, mask)
    edge_w = target_edge_weights(mask, sigma_px=edge_sigma_px, floor=edge_floor)
    cached = {
        "mask": mask,
        "silhouette": alpha,
        "depth": target_depth,
        "normalizedDepth": normalized_target_depth,
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
        if not fresh:
            return None
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
    reverse_target_rgba: np.ndarray | None = None,
    reverse_predicted_rgba: np.ndarray | None = None,
    reverse_target_mask: np.ndarray | None = None,
    reverse_predicted_mask: np.ndarray | None = None,
    reverse_soft_weight: np.ndarray | None = None,
    reverse_iou: float | None = None,
    primary_iou: float | None = None,
    action_panel: np.ndarray | None = None,
    preview_profile_depth: bool = False,
    primary_target_depth: np.ndarray | None = None,
    primary_predicted_depth: np.ndarray | None = None,
    reverse_target_depth: np.ndarray | None = None,
    reverse_predicted_depth: np.ndarray | None = None,
):
    """Write a 3x2 preview: primary target/render/IoU above reverse target/render/IoU."""
    if Image is None:
        return
    h, w = predicted_mask.shape

    def _as_depth_panel(panel: np.ndarray | None, mask: np.ndarray) -> np.ndarray:
        """Render a depth array with foreground contrast for human inspection."""
        if panel is None:
            return np.zeros((h, w, 3), dtype=np.uint8)
        values = np.asarray(panel, dtype=np.float32)
        if values.shape != (h, w):
            values = resize_gray(values, w, h)
        foreground = values[np.asarray(mask, dtype=bool)]
        foreground = foreground[np.isfinite(foreground)]
        if foreground.size:
            lo = float(np.percentile(foreground, 2.0))
            hi = float(np.percentile(foreground, 98.0))
            if hi > lo + 1e-6:
                values = np.clip((values - lo) / (hi - lo), 0.0, 1.0)
        g = np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8)
        rgb = np.stack([g, g, g], axis=-1).copy()
        rgb[~np.asarray(mask, dtype=bool)] = 0
        return rgb

    def _as_rgb_panel(panel: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if panel.ndim == 2:
            return _as_depth_panel(panel, mask)
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

    def make_iou_panel(target_mask_in, predicted_mask_in, soft_weight_in):
        """Render the same target-only/pred-only/soft-match overlay used by the score."""
        target_mask_in = np.asarray(target_mask_in, dtype=bool)
        predicted_mask_in = np.asarray(predicted_mask_in, dtype=bool)
        if target_mask_in.shape != (h, w):
            target_mask_in = resize_gray(target_mask_in.astype(np.float32), w, h) >= 0.5
        if predicted_mask_in.shape != (h, w):
            predicted_mask_in = resize_gray(predicted_mask_in.astype(np.float32), w, h) >= 0.5
        only_target_in = target_mask_in & ~predicted_mask_in
        only_pred_in = predicted_mask_in & ~target_mask_in
        panel = np.zeros((h, w, 3), dtype=np.uint8)
        panel[only_target_in] = (220, 64, 64)
        panel[only_pred_in] = (64, 120, 255)
        both_in = target_mask_in & predicted_mask_in
        if both_in.any():
            if soft_weight_in is None:
                match = np.ones((h, w), dtype=np.float32)
            else:
                match = np.asarray(soft_weight_in, dtype=np.float32)
                if match.shape != (h, w):
                    match = resize_gray(match, w, h)
            g = np.clip(np.rint(64.0 + match[both_in] * 176.0), 0, 255).astype(np.uint8)
            panel[both_in, 0] = 32
            panel[both_in, 1] = g
            panel[both_in, 2] = 48
        return panel

    iou_panel = make_iou_panel(target_mask, predicted_mask, soft_weight)

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
    if preview_profile_depth and primary_predicted_depth is not None:
        if primary_target_depth is not None:
            target_panel = _as_depth_panel(primary_target_depth, target_mask)
        render_panel = _as_depth_panel(primary_predicted_depth, predicted_mask)
        labels = ["target depth", "profile mesh depth"]
    else:
        labels = [left_label, mid_label]
    panels = [target_panel, render_panel, iou_panel]
    primary_overlay_iou = iou if primary_iou is None else primary_iou
    labels.append(f"IoU overlay {primary_overlay_iou:.4f}")
    if reverse_target_rgba is not None and reverse_predicted_rgba is not None:
        reverse_target = resize_rgba(reverse_target_rgba, w, h)
        reverse_predicted = resize_rgba(reverse_predicted_rgba, w, h)
        reverse_target_mask = (
            resize_gray(reverse_target_mask.astype(np.float32), w, h) >= 0.5
            if reverse_target_mask is not None and reverse_target_mask.shape != (h, w)
            else reverse_target_mask
        )
        if reverse_target_mask is None:
            reverse_target_mask = reverse_target[:, :, 3] >= 0.08
        reverse_mask = (
            reverse_predicted_mask
            if reverse_predicted_mask is not None
            else reverse_predicted[:, :, 3] >= 0.08
        )
        reverse_iou_panel = make_iou_panel(
            reverse_target_mask,
            reverse_mask,
            reverse_soft_weight,
        )
        if preview_profile_depth and reverse_predicted_depth is not None:
            reverse_target_panel = reverse_target_depth if reverse_target_depth is not None else reverse_target[:, :, 3]
            reverse_mesh_panel = reverse_predicted_depth
            panels.extend([
                _as_depth_panel(reverse_target_panel, reverse_target_mask),
                _as_depth_panel(reverse_mesh_panel, reverse_mask),
                reverse_iou_panel,
            ])
        else:
            panels.extend([
                _as_rgb_panel(reverse_target, reverse_target_mask),
                _as_rgb_panel(reverse_predicted, reverse_mask),
                reverse_iou_panel,
            ])
        reverse_label = "reverse IoU overlay"
        if reverse_iou is not None:
            reverse_label += f" {float(reverse_iou):.4f}"
        if preview_profile_depth and reverse_predicted_depth is not None:
            labels.extend(["reverse target depth", "reverse mesh depth", reverse_label])
        else:
            labels.extend(["reverse target RGB", "reverse mesh RGB", reverse_label])
    action_display = None
    action_height = 0
    if action_panel is not None:
        # Keep the action view as a genuinely larger third row. It is not part
        # of the six profile/depth cells and must remain visually distinct.
        action_rgba = resize_rgba(action_panel, w * 3 + gap * 2, h * 2 + gap)
        action_rgb = action_rgba[:, :, :3]
        action_alpha = action_rgba[:, :, 3:4]
        action_display = np.clip(np.rint(action_rgb * action_alpha * 255.0), 0, 255).astype(np.uint8)
    columns = 3
    if action_panel is not None:
        # The action panel is intentionally a larger third row spanning the
        # complete preview width; do not treat it as a fourth small cell.
        panels = panels[:6]
        rows = 2
        action_height = action_display.shape[0] + gap
    else:
        rows = (len(panels) + columns - 1) // columns
    canvas_height = h * rows + gap * (rows - 1) + action_height
    canvas = np.zeros(
        (canvas_height, w * columns + gap * (columns - 1), 3),
        dtype=np.uint8,
    )
    for index, panel in enumerate(panels):
        row, column = divmod(index, columns)
        x0 = column * (w + gap)
        y0 = row * (h + gap)
        canvas[y0 : y0 + h, x0 : x0 + w] = panel
    if action_display is not None:
        y0 = 2 * (h + gap)
        canvas[y0 : y0 + action_display.shape[0], : action_display.shape[1]] = action_display

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
        for index, label in enumerate(labels):
            row, column = divmod(index, columns)
            draw.text(
                (column * (w + gap) + 6, bar_h + row * (h + gap) + 2),
                label,
                fill=(200, 200, 200),
                font=font,
            )
        if action_display is not None:
            draw.text((6, bar_h + 2 * (h + gap) + 2), "front-upper-diagonal action camera", fill=(200, 200, 200), font=font)
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
    silhouette_depth_weight = float(command.get("silhouetteDepthWeight", 1.0))
    if not math.isfinite(silhouette_depth_weight) or not 0.0 <= silhouette_depth_weight <= 1.0:
        raise ValueError(
            f"silhouetteDepthWeight must be between 0 and 1, got {silhouette_depth_weight!r}"
        )
    # Blue panel = pred-only. Weight >1 penalizes mesh spilling outside the sprite.
    pred_only_penalty = float(
        command.get("predOnlyPenalty", STATE.get("pred_only_penalty", 2.0))
    )
    if not math.isfinite(pred_only_penalty) or pred_only_penalty < 0.0:
        raise ValueError(f"predOnlyPenalty must be finite and non-negative, got {pred_only_penalty!r}")
    # Red panel = target-only. The old scorer implicitly used 1.0 here.
    target_only_penalty = float(
        command.get("targetOnlyPenalty", STATE.get("target_only_penalty", 1.0))
    )
    if not math.isfinite(target_only_penalty) or target_only_penalty < 0.0:
        raise ValueError(f"targetOnlyPenalty must be finite and non-negative, got {target_only_penalty!r}")
    edge_sigma = float(
        command.get("targetEdgeSigmaPx", STATE.get("target_edge_sigma_px", 4.0))
    )
    edge_floor = float(
        command.get("targetEdgeFloor", STATE.get("target_edge_floor", 0.25))
    )
    target_edge_bonus = float(
        command.get("targetEdgeBonus", STATE.get("target_edge_bonus", 0.0))
    )
    if not math.isfinite(target_edge_bonus) or target_edge_bonus < 0.0:
        raise ValueError(f"targetEdgeBonus must be finite and non-negative, got {target_edge_bonus!r}")
    profile_half_bias = float(
        command.get("profileHalfBias", STATE.get("profile_half_bias", 0.5))
    )
    if not math.isfinite(profile_half_bias) or not 0.0 <= profile_half_bias <= 1.0:
        raise ValueError(f"profileHalfBias must be between 0 and 1, got {profile_half_bias!r}")
    reverse_profile_weight = float(command.get("reverseProfileWeight", 0.5))
    if not math.isfinite(reverse_profile_weight) or not 0.0 <= reverse_profile_weight <= 1.0:
        raise ValueError(
            f"reverseProfileWeight must be between 0 and 1, got {reverse_profile_weight!r}"
        )

    missing_target_depth = False
    left_depth = None
    left_label = "target"
    reverse_target_rgba = None
    reverse_predicted_rgba = None
    reverse_target_mask = None
    reverse_predicted_mask = None
    reverse_soft_weight = None
    reverse_iou = None
    action_panel = None
    primary_target_depth_preview = None
    primary_predicted_depth_preview = None
    reverse_target_depth_preview = None
    reverse_predicted_depth_preview = None

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
        or command.get("anatomicalCandidateOut")
    )
    # The request, not the scoreMode string alone, controls the expensive
    # depth pass. Semantic-only runs can use RGB alpha for the worker fallback
    # without paying for a depth compositor render that the hybrid ledger will
    # ignore. Explicit profile-depth previews and reverse-profile geometry
    # still force the depth path.
    render_depth = bool(
        command.get("renderDepth", STATE.get("render_depth_default", score_mode == "depth"))
        or command.get("previewProfileDepth", False)
        or command.get("reverseProfileEnabled", False)
    )
    render_records = []
    rgb_render_source = None
    if render_depth:
        if wants_rgb:
            # RGB and mapped Z come from the same Blender render.  This avoids
            # both the old compositor flip and a second pose/render pass for
            # semantic+depth candidates.
            predicted, depth_mapped = render_rgb_depth_search()
            render_records.append(dict(STATE.get("last_render_timing", {})))
            rgb_render_source = Path(STATE["rgb_render_path"])
        else:
            predicted, depth_mapped = render_search()
            render_records.append(dict(STATE.get("last_render_timing", {})))
    else:
        predicted, depth_mapped = render_rgb_search()
        render_records.append(dict(STATE.get("last_render_timing", {})))
        rgb_render_source = Path(STATE["rgb_render_path"])
    # Reverse-profile, action-camera, and alternate semantic renders reuse the
    # worker's RGB path. Preserve the primary profile before any of them can
    # overwrite it, otherwise the semantic candidate could silently become a
    # reverse/action view.
    primary_snapshot_required = bool(
        command.get("reverseProfileEnabled", False)
        or command.get("semanticMultiview", False)
        or command.get("previewActionCamera", False)
    )
    if (
        primary_snapshot_required
        and rgb_render_source is not None
        and rgb_render_source.is_file()
    ):
        primary_snapshot = Path(STATE["primary_rgb_snapshot_path"])
        shutil.copyfile(rgb_render_source, primary_snapshot)
        rgb_render_source = primary_snapshot
    semantic_view_outs = list(command.get("semanticViewOuts", []) or [])
    semantic_views = []
    if command.get("semanticMultiview", False) and wants_rgb:
        expected_view_count = len(STATE.get("semantic_view_angles_deg", ()))
        if len(semantic_view_outs) != expected_view_count:
            raise ValueError(
                "semanticViewOuts must contain one output path per configured semantic view"
            )
    if predicted.shape[0] != STATE["search_h"] or predicted.shape[1] != STATE["search_w"]:
        predicted = resize_rgba(predicted, STATE["search_w"], STATE["search_h"])
        if depth_mapped is not None:
            depth_mapped = resize_gray(depth_mapped, STATE["search_w"], STATE["search_h"])

    semantic_out = command.get("semanticCandidateOut")
    semantic_encode_seconds = 0.0
    semantic_copy_seconds = 0.0
    anatomical_out = command.get("anatomicalCandidateOut")
    if anatomical_out:
        anatomical_path = Path(anatomical_out).resolve()
        anatomical_path.parent.mkdir(parents=True, exist_ok=True)
        anatomical_tmp = anatomical_path.with_suffix(anatomical_path.suffix + ".tmp.png")
        if rgb_render_source is not None and rgb_render_source.is_file():
            shutil.copyfile(rgb_render_source, anatomical_tmp)
        elif Image is not None:
            Image.fromarray(
                np.clip(np.rint(predicted * 255.0), 0, 255).astype(np.uint8),
                "RGBA",
            ).save(anatomical_tmp, format="PNG")
        else:
            raise RuntimeError("anatomicalCandidateOut requires a readable RGB render")
        os.replace(anatomical_tmp, anatomical_path)
    anatomical_depth_out = command.get("anatomicalCandidateDepthOut")
    if anatomical_depth_out and Image is not None:
        if depth_mapped is None:
            raise RuntimeError(
                "anatomicalCandidateDepthOut was requested but the render did not produce depth"
            )
        anatomical_depth_path = Path(anatomical_depth_out).resolve()
        anatomical_depth_path.parent.mkdir(parents=True, exist_ok=True)
        anatomical_depth_tmp = anatomical_depth_path.with_suffix(
            anatomical_depth_path.suffix + ".tmp.png"
        )
        # Target depth caches use near=bright. Blender's mapped depth uses the
        # opposite convention, so invert it before the detector reads it.
        anatomical_depth = np.clip(
            np.rint((1.0 - np.asarray(depth_mapped, dtype=np.float32)) * 65535.0),
            0,
            65535,
        ).astype(np.uint16)
        Image.fromarray(anatomical_depth, "I;16").save(
            anatomical_depth_tmp,
            format="PNG",
        )
        os.replace(anatomical_depth_tmp, anatomical_depth_path)

    predicted_mask = predicted[:, :, 3] >= threshold
    target_mask = target["mask"]
    pred_depth = None
    preview_predicted_mask = predicted_mask.copy()
    if command.get("previewProfileDepth", False) and depth_mapped is not None:
        profile_geom = predicted_mask & (depth_mapped < 0.999)
        preview_predicted_mask = profile_geom
        pred_depth = np.zeros(predicted_mask.shape, dtype=np.float32)
        pred_depth[profile_geom] = (1.0 - depth_mapped[profile_geom]).astype(np.float32)
    edge_w = target.get("edgeWeight")
    if edge_w is None or edge_w.shape != target_mask.shape:
        edge_w = target_edge_weights(target_mask, sigma_px=edge_sigma, floor=edge_floor)
    both = target_mask & predicted_mask
    only_target = target_mask & ~predicted_mask
    only_pred = predicted_mask & ~target_mask
    depth_used = False
    fallback_binary = False

    def _edge_score_weights(weights: np.ndarray) -> np.ndarray:
        """Add an optional extra multiplier to target pixels near the silhouette rim."""
        base = np.asarray(weights, dtype=np.float32)
        if target_edge_bonus <= 0.0:
            return base
        denom = max(1.0 - min(1.0, max(0.0, edge_floor)), 1e-6)
        proximity = np.clip((base - edge_floor) / denom, 0.0, 1.0)
        return base * (1.0 + target_edge_bonus * proximity)

    def _profile_half_weights(mask: np.ndarray, *, own_right: bool) -> np.ndarray:
        """Weight the owning profile more on its image-side half.

        The primary camera is the current/right-view profile; the reverse camera
        owns the image-left half. A bias of 0.5 is symmetric and 1.0 is exclusive.
        """
        height, width = mask.shape
        ys, xs = np.where(mask)
        split = (float(xs.min()) + float(xs.max()) + 1.0) * 0.5 if xs.size else width * 0.5
        columns = np.arange(width, dtype=np.float32)[None, :]
        own_side = columns >= split if own_right else columns < split
        row = np.where(own_side, profile_half_bias, 1.0 - profile_half_bias).astype(np.float32)
        return np.broadcast_to(row, (height, width)).copy()

    def _score_components(
        target_mask_value: np.ndarray,
        predicted_mask_value: np.ndarray,
        soft_value: np.ndarray,
        edge_weights_value: np.ndarray,
        influence: np.ndarray | None = None,
    ) -> tuple[float, float, float]:
        """Return weighted intersection, asymmetric union, and IoU for one view."""
        if influence is None:
            influence = np.ones(target_mask_value.shape, dtype=np.float32)
        both_value = target_mask_value & predicted_mask_value
        only_target_value = target_mask_value & ~predicted_mask_value
        only_pred_value = predicted_mask_value & ~target_mask_value
        target_mass = np.asarray(edge_weights_value, dtype=np.float32) * influence
        intersection_value = float(
            (np.asarray(soft_value, dtype=np.float32)[both_value] * target_mass[both_value]).sum()
        ) if both_value.any() else 0.0
        union_value = float(
            intersection_value
            # These are soft asymmetric-union weights. A positive score is
            # still returned when every candidate has some pred-only spill;
            # a hard exclusion needs an explicit pixel limit, not a huge weight.
            + target_only_penalty * float(target_mass[only_target_value].sum())
            + pred_only_penalty * float(influence[only_pred_value].sum())
        )
        return intersection_value, union_value, float(intersection_value / max(union_value, 1e-6))

    def _zone_diagnostics(
        target_mask_value: np.ndarray,
        predicted_mask_value: np.ndarray,
        edge_weights_value: np.ndarray,
        influence: np.ndarray | None = None,
    ) -> dict[str, float | int]:
        """Expose the exact asymmetric-union terms used by _score_components."""
        if influence is None:
            influence = np.ones(target_mask_value.shape, dtype=np.float32)
        only_target_value = target_mask_value & ~predicted_mask_value
        only_pred_value = predicted_mask_value & ~target_mask_value
        target_mass = np.asarray(edge_weights_value, dtype=np.float32) * influence
        pred_only_mass = float(influence[only_pred_value].sum())
        target_only_mass = float(target_mass[only_target_value].sum())
        return {
            "predOnlyPixels": int(only_pred_value.sum()),
            "targetOnlyPixels": int(only_target_value.sum()),
            "predOnlyMass": pred_only_mass,
            "targetOnlyMass": target_only_mass,
            "predOnlyPenaltyApplied": float(pred_only_penalty * pred_only_mass),
            "targetOnlyPenaltyApplied": float(target_only_penalty * target_only_mass),
        }

    edge_w = _edge_score_weights(edge_w)

    if score_mode == "chroma":
        soft_weight = soft_color_weight(
            target["rgb"],
            predicted[:, :, :3],
            both,
            color_max_dist,
        )
        mid_panel = predicted
        mid_label = "render"
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
            left_depth = target["silhouette"]
            left_label = "tgtSil(NO pred depth)"
        else:
            tgt_n, pred_n = matched_depth_pair(
                tgt_depth,
                pred_depth,
                target_mask,
                predicted_mask,
                normalized_target=target.get("normalizedDepth"),
            )
            depth_weight = soft_depth_weight(tgt_n, pred_n, both, depth_max_dist)
            silhouette_weight = soft_silhouette_weight(
                target["silhouette"], predicted_mask.astype(np.float32)
            )
            soft_weight = (
                (1.0 - silhouette_depth_weight) * silhouette_weight
                + silhouette_depth_weight * depth_weight
            )
            left_depth = tgt_n
            left_label = "tgtDepth(norm)"
            mid_panel = pred_n
            mid_label = "predDepth(→tgt hist)"

    primary_intersection, primary_union, primary_full_silhouette_iou = _score_components(
        target_mask,
        predicted_mask,
        soft_weight,
        edge_w,
    )
    intersection = primary_intersection
    union = primary_union
    silhouette_iou = primary_full_silhouette_iou
    primary_silhouette_iou = primary_full_silhouette_iou
    reverse_result = None
    reverse_intersection = None
    reverse_union = None
    primary_profile_intersection = primary_intersection
    primary_profile_union = primary_union
    primary_profile_influence = None
    reverse_profile_influence = None
    primary_zone_diagnostics = _zone_diagnostics(target_mask, predicted_mask, edge_w)
    reverse_zone_diagnostics = None
    reverse_only_target = None
    reverse_only_pred = None
    if bool(command.get("reverseProfileEnabled", False)):
        reverse_target_path = command.get("reverseProfileTarget")
        reverse_depth_path = command.get("reverseProfileDepth")
        if not reverse_target_path or not reverse_depth_path:
            raise ValueError(
                "reverseProfileEnabled requires reverseProfileTarget and reverseProfileDepth"
            )
        if not Path(reverse_target_path).is_file():
            raise FileNotFoundError(f"reverse profile target does not exist: {reverse_target_path}")
        if not Path(reverse_depth_path).is_file():
            raise FileNotFoundError(f"reverse profile depth does not exist: {reverse_depth_path}")
        reverse_target = get_or_cache_target(
            reverse_target_path,
            threshold,
            depth_path=reverse_depth_path,
            edge_sigma_px=edge_sigma,
            edge_floor=edge_floor,
        )
        reverse_predicted, reverse_depth = render_search_profile(180.0)
        render_records.append(dict(STATE.get("last_profile_render_timing", {})))
        reverse_target_rgba = reverse_target.get("rgba")
        reverse_target_mask = reverse_target["mask"]
        reverse_predicted_rgba = reverse_predicted
        reverse_predicted = resize_rgba(
            reverse_predicted, STATE["search_w"], STATE["search_h"]
        )
        if reverse_depth is not None:
            reverse_depth = resize_gray(
                reverse_depth, STATE["search_w"], STATE["search_h"]
            )
        reverse_alpha_mask = reverse_predicted[:, :, 3] >= threshold
        reverse_mask = reverse_alpha_mask
        reverse_preview_mask = reverse_alpha_mask.copy()
        if reverse_depth is not None:
            reverse_geom = reverse_mask & (reverse_depth < 0.999)
            reverse_pred_depth = np.zeros(reverse_mask.shape, dtype=np.float32)
            reverse_pred_depth[reverse_geom] = (1.0 - reverse_depth[reverse_geom]).astype(np.float32)
            if score_mode != "chroma":
                reverse_mask = reverse_geom
            if command.get("previewProfileDepth", False):
                reverse_preview_mask = reverse_geom
        else:
            reverse_pred_depth = reverse_predicted[:, :, 3].astype(np.float32)
        reverse_predicted_mask = reverse_preview_mask
        if command.get("previewProfileDepth", False):
            reverse_target_depth_preview = reverse_target["depth"]
            reverse_predicted_depth_preview = reverse_pred_depth
        reverse_both = reverse_target["mask"] & reverse_mask
        reverse_only_target = reverse_target["mask"] & ~reverse_mask
        reverse_only_pred = reverse_mask & ~reverse_target["mask"]
        reverse_edge_w = _edge_score_weights(reverse_target["edgeWeight"])
        if score_mode == "chroma":
            reverse_soft = soft_color_weight(
                reverse_target["rgb"],
                reverse_predicted[:, :, :3],
                reverse_both,
                color_max_dist,
            )
        elif reverse_target.get("depth") is None:
            reverse_soft = soft_silhouette_weight(
                reverse_target["silhouette"], reverse_mask.astype(np.float32)
            )
        else:
            reverse_tgt_n, reverse_pred_n = matched_depth_pair(
                reverse_target["depth"],
                reverse_pred_depth,
                reverse_target["mask"],
                reverse_mask,
                normalized_target=reverse_target.get("normalizedDepth"),
            )
            reverse_depth_soft = soft_depth_weight(
                reverse_tgt_n, reverse_pred_n, reverse_both, depth_max_dist
            )
            reverse_silhouette_soft = soft_silhouette_weight(
                reverse_target["silhouette"], reverse_mask.astype(np.float32)
            )
            reverse_soft = (
                (1.0 - silhouette_depth_weight) * reverse_silhouette_soft
                + silhouette_depth_weight * reverse_depth_soft
            )
        reverse_soft_weight = reverse_soft
        primary_profile_influence = _profile_half_weights(target_mask, own_right=True)
        reverse_profile_influence = _profile_half_weights(reverse_target["mask"], own_right=False)
        primary_profile_intersection, primary_profile_union, primary_profile_iou = _score_components(
            target_mask,
            predicted_mask,
            soft_weight,
            edge_w,
            primary_profile_influence,
        )
        reverse_intersection, reverse_union, reverse_result = _score_components(
            reverse_target["mask"],
            reverse_mask,
            reverse_soft,
            reverse_edge_w,
            reverse_profile_influence,
        )
        reverse_iou = reverse_result
        primary_zone_diagnostics = _zone_diagnostics(
            target_mask,
            predicted_mask,
            edge_w,
            primary_profile_influence,
        )
        reverse_zone_diagnostics = _zone_diagnostics(
            reverse_target["mask"],
            reverse_mask,
            reverse_edge_w,
            reverse_profile_influence,
        )
        reverse_weight = reverse_profile_weight
        weighted_profile_scores = []
        if primary_profile_union > 1e-6 and (1.0 - reverse_weight) > 0.0:
            weighted_profile_scores.append(((1.0 - reverse_weight), primary_profile_iou))
        if reverse_union > 1e-6 and reverse_weight > 0.0:
            weighted_profile_scores.append((reverse_weight, reverse_result))
        if weighted_profile_scores:
            weight_sum = sum(weight for weight, _ in weighted_profile_scores)
            silhouette_iou = sum(weight * value for weight, value in weighted_profile_scores) / weight_sum
        else:
            silhouette_iou = 0.0
    if command.get("previewProfileDepth", False):
            primary_target_depth_preview = target.get("depth")
            primary_predicted_depth_preview = pred_depth
    if command.get("previewActionCamera", False):
        action_panel = render_action_camera(
            float(command.get("actionCameraAngleDeg", -45.0)),
            float(command.get("actionCameraElevationDeg", 18.0)),
        )
        action_out = command.get("actionPanelOut")
        if action_out and Image is not None:
            action_path = Path(action_out).resolve()
            action_path.parent.mkdir(parents=True, exist_ok=True)
            action_rgba = np.clip(np.rint(action_panel * 255.0), 0, 255).astype(np.uint8)
            Image.fromarray(action_rgba, "RGBA").save(action_path, format="PNG")
    anatomical_enabled = bool(command.get("anatomicalBoxesEnabled", False))
    show_anatomical_boxes = bool(command.get("showAnatomicalBoxes", False))
    configured_part_weight = float(command.get("anatomicalPartWeight", STATE.get("anatomical_part_weight", 0.20)))
    part_weight = configured_part_weight if anatomical_enabled else 0.0
    if not math.isfinite(part_weight) or not 0.0 <= part_weight <= 1.0:
        raise ValueError(f"anatomicalPartWeight must be between 0 and 1, got {part_weight!r}")
    # Candidate anatomy is detected by the notebook-side local vision model
    # from the RGB render written above. Do not substitute bone projections:
    # they are not evidence of the visible feature location.
    part_result = {
        "score": 0.0,
        "distance": 1.0,
        "parts": [],
        "used": False,
    }
    iou = silhouette_iou
    triage_enabled = bool(
        command.get("triageEnabled", False)
        and command.get("triageSilhouetteEnabled", False)
        and command.get("triageSilhouetteHeuristicEnabled", False)
        and semantic_out
    )
    triage_floor = float(command.get("triageSilhouetteFloor", 0.0))
    triage_rejected = bool(triage_enabled and primary_silhouette_iou < triage_floor)
    if command.get("semanticMultiview", False) and wants_rgb:
        if triage_rejected:
            for view_out in semantic_view_outs:
                Path(view_out).unlink(missing_ok=True)
        else:
            # Multiview rendering is only needed after the cheap primary
            # silhouette gate. Preserve the primary RGB before alternate views
            # reuse the worker's RGB output path.
            if (
                rgb_render_source is not None
                and rgb_render_source.is_file()
                and Path(rgb_render_source).resolve()
                != Path(STATE["primary_rgb_snapshot_path"]).resolve()
            ):
                primary_snapshot = Path(STATE["primary_rgb_snapshot_path"])
                shutil.copyfile(rgb_render_source, primary_snapshot)
                rgb_render_source = primary_snapshot
            semantic_views = render_rgb_semantic_views(
                semantic_view_outs,
                primary_rgba=predicted,
                primary_path=rgb_render_source,
            )
            render_records.extend(STATE.get("semantic_view_render_timings", ()))
    if semantic_out and not triage_rejected:
        semantic_path = Path(semantic_out).resolve()
        semantic_path.parent.mkdir(parents=True, exist_ok=True)
        semantic_tmp = semantic_path.with_suffix(semantic_path.suffix + ".tmp.png")
        copy_started = time.perf_counter()
        if rgb_render_source is not None and rgb_render_source.is_file():
            shutil.copyfile(rgb_render_source, semantic_tmp)
        elif Image is not None:
            Image.fromarray(
                np.clip(np.rint(predicted * 255.0), 0, 255).astype(np.uint8),
                "RGBA",
            ).save(semantic_tmp, format="PNG")
            semantic_encode_seconds = time.perf_counter() - copy_started
        else:
            raise RuntimeError("semanticCandidateOut requires a readable RGB render")
        semantic_copy_seconds = time.perf_counter() - copy_started
        os.replace(semantic_tmp, semantic_path)
    for view, view_out in zip(semantic_views, semantic_view_outs):
        view_path = Path(view_out).resolve()
        if triage_rejected:
            view_path.unlink(missing_ok=True)
            continue
        if view_path in set(STATE.get("semantic_view_direct_paths", ())):
            # The compositor wrote this exact RGB render directly to the
            # requested path; avoid decoding and re-encoding it here.
            continue
        view_path.parent.mkdir(parents=True, exist_ok=True)
        view_tmp = view_path.with_suffix(view_path.suffix + ".tmp.png")
        Image.fromarray(np.clip(np.rint(view * 255.0), 0, 255).astype(np.uint8), "RGBA").save(view_tmp, format="PNG")
        os.replace(view_tmp, view_path)

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
            predicted_mask=preview_predicted_mask,
            soft_weight=soft_weight,
            iou=iou,
            caption=str(command.get("previewCaption", f"score:{score_mode}")),
            left_panel=left_panel,
            left_label=left_label_out,
            target_part_boxes=[],
            predicted_part_boxes={},
            reverse_target_rgba=reverse_target_rgba,
            reverse_predicted_rgba=reverse_predicted_rgba,
            reverse_target_mask=reverse_target_mask,
            reverse_predicted_mask=reverse_predicted_mask,
            reverse_soft_weight=reverse_soft_weight,
            reverse_iou=reverse_iou,
            primary_iou=primary_silhouette_iou,
            action_panel=action_panel,
            preview_profile_depth=bool(command.get("previewProfileDepth", False)),
            primary_target_depth=primary_target_depth_preview,
            primary_predicted_depth=primary_predicted_depth_preview,
            reverse_target_depth=reverse_target_depth_preview,
            reverse_predicted_depth=reverse_predicted_depth_preview,
        )

    emit(
        {
            "ok": True,
            "iou": iou,
            "intersection": intersection,
            "union": union,
            "silhouetteIoU": silhouette_iou,
            "primarySilhouetteIoU": primary_silhouette_iou,
            "anatomicalPartIoU": part_result["score"],
            "anatomicalBoxesEnabled": anatomical_enabled,
            "anatomicalPartWeight": part_weight,
            "anatomicalFeatureDistance": part_result.get("distance"),
            "anatomicalParts": part_result["parts"],
            "scoreMode": score_mode,
            "colorMaxDist": color_max_dist,
            "depthMaxDist": depth_max_dist,
            "silhouetteDepthWeight": silhouette_depth_weight,
            "motionRoot": dict(STATE.get("motion_root_values", {})),
            "motionRootRotation": dict(
                STATE.get("motion_root_rotation_values", {})
            ),
            "motionRootReferenceLengthWorld": float(STATE.get("motion_root_length_world", 1.0)),
            "reverseProfileEnabled": bool(command.get("reverseProfileEnabled", False)),
            "reverseProfileIoU": reverse_result,
            "reverseProfileWeight": reverse_profile_weight,
            "profileHalfBias": profile_half_bias,
            "profileHalfPrimaryIoU": primary_profile_iou if reverse_result is not None else None,
            "profileHalfReverseIoU": reverse_result,
            "profileHalfPrimaryIntersection": primary_profile_intersection,
            "profileHalfPrimaryUnion": primary_profile_union,
            "profileHalfReverseIntersection": reverse_intersection,
            "profileHalfReverseUnion": reverse_union,
            "predOnlyPenalty": pred_only_penalty,
            "targetOnlyPenalty": target_only_penalty,
            "targetEdgeSigmaPx": edge_sigma,
            "targetEdgeFloor": edge_floor,
            "targetEdgeBonus": target_edge_bonus,
            "zoneDiagnostics": {
                "primary": primary_zone_diagnostics,
                "reverse": reverse_zone_diagnostics,
            },
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
            "triageEnabled": triage_enabled,
            "triageSilhouetteFloor": triage_floor,
            "triageSilhouette": float(primary_silhouette_iou),
            "triageRejected": triage_rejected,
            "triageReason": "silhouette_floor" if triage_rejected else None,
            "semanticCandidateWritten": bool(semantic_out and not triage_rejected),
            "timings": {
                "pose": dict(STATE.get("last_pose_timing", {})),
                "renders": render_records,
                "semanticCandidateEncodeSeconds": float(semantic_encode_seconds),
                "semanticCandidateCopySeconds": float(semantic_copy_seconds),
                "renderSeconds": float(sum(float(item.get("renderSeconds", 0.0)) for item in render_records)),
                "renderReadSeconds": float(sum(float(item.get("readSeconds", 0.0)) for item in render_records)),
            },
        }
    )


def save_render(command):
    if "angles" in command:
        apply_pose(command)
    ensure_proof_mode()
    # Proof outputs are actual mesh renders, never the depth-search buffer.
    ensure_compositor_mode("rgb")
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
