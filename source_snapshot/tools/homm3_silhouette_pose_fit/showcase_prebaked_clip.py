#!/usr/bin/env python3
"""Bake a solved lighting rig into a unit's base-colour texture and show a solved clip with it.

Pipeline
--------
1. Blender (Cycles CUDA) imports the unit GLB at rest, applies the key/flood lights from
   ``solve_unit_light_palette.py``'s ``light_solution.json``, and bakes COMBINED
   (direct + indirect, diffuse + glossy) into a new texture on the mesh's own UVs.
   The glossy lobe is view-dependent; it is baked from a front camera and that is a
   known approximation of a pre-baked (view-independent) texture.
2. The baked PNG replaces the GLB's baseColorTexture bytes; nothing else in the GLB
   (nodes, skin, accessors) is touched, so the solved clip poses still apply.
   The reverse view turns the profile *camera* 180 deg about the world up axis (a
   rotated root node would fail the skin-vs-mesh bind validation).
3. The solved ``gpu_clip_result.json`` is rendered through the same nvdiffrast unlit
   base-colour raster the tracker previews use, so the showcase is the baked texture
   and nothing else. Panels: sprite | pre-baked front | pre-baked reverse.

Proof tier: generated artifact preview. Not an OE build; the baked GLB is not a ship
master (Unity would need the metallic/normal maps neutralised to match).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
BLENDER = os.environ.get("HOMM3_POSE_FIT_BLENDER", "V:/Tools/blender-3.5.1/blender.exe")

BAKE_SIZE = 2048
BAKE_SAMPLES = 48
BAKE_MARGIN_PX = 8
# Same rig geometry as solve_unit_light_palette; the solution JSON carries the values
# too and the two are cross-checked below so a drift cannot go unnoticed.
KEY_ELEVATION_DEG = 65.0
KEY_AZIMUTH_DEG = 0.0


def configure_cycles_cuda(prefs: Any, scene: Any) -> list[str]:
    """Turn Cycles onto CUDA GPUs. CPU Cycles is forbidden."""
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    enabled: list[str] = []
    for device in prefs.devices:
        use = str(getattr(device, "type", "")) == "CUDA"
        device.use = use
        if use:
            enabled.append(str(getattr(device, "name", "CUDA")))
    if not enabled:
        raise RuntimeError("Cycles CUDA is required; no CUDA device is present")
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    return enabled


# --------------------------------------------------------------------------- Blender
def _blender_bake(argv: list[str]) -> None:
    import bpy  # type: ignore
    from mathutils import Euler, Vector  # type: ignore

    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--solution", required=True)
    parser.add_argument("--out-png", required=True)
    parser.add_argument("--size", type=int, default=BAKE_SIZE)
    parser.add_argument("--samples", type=int, default=BAKE_SAMPLES)
    args = parser.parse_args(argv)

    solution = json.loads(Path(args.solution).read_text(encoding="utf-8"))
    rig = solution["rig"]
    if abs(float(rig["keyElevationDeg"]) - KEY_ELEVATION_DEG) > 1e-6 or abs(float(rig["keyAzimuthFromCameraDeg"]) - KEY_AZIMUTH_DEG) > 1e-6:
        raise RuntimeError("light_solution rig geometry differs from the bake rig; refusing to bake a different light")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh objects imported from {args.glb}")
    materials = {slot.material.name: slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    if len(materials) != 1:
        raise RuntimeError(f"expected exactly one material to bake into one texture, found {sorted(materials)}")
    material = next(iter(materials.values()))

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        for vertex in evaluated.data.vertices:
            world = evaluated.matrix_world @ vertex.co
            lo = Vector(min(a, b) for a, b in zip(lo, world))
            hi = Vector(max(a, b) for a, b in zip(hi, world))
    center = (lo + hi) * 0.5
    height = hi.z - lo.z

    scene = bpy.context.scene
    configure_cycles_cuda(bpy.context.preferences.addons["cycles"].preferences, scene)
    scene.cycles.samples = int(args.samples)
    scene.view_settings.view_transform = "Standard"

    # Glossy is view-dependent; bake it as seen from the front camera.
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.25
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = center + Vector((0.0, -height * 4.0, 0.0))
    cam.rotation_euler = Euler((math.radians(90.0), 0.0, 0.0), "XYZ")

    sun_data = bpy.data.lights.new("key", "SUN")
    sun_data.angle = math.radians(8.0)
    sun_data.color = tuple(solution["keyLight"]["colorLinear"])
    sun_data.energy = float(solution["keyLight"]["strength"])
    sun = bpy.data.objects.new("key", sun_data)
    scene.collection.objects.link(sun)
    az = math.radians(KEY_AZIMUTH_DEG)
    el = math.radians(KEY_ELEVATION_DEG)
    from_dir = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    sun.rotation_euler = (-from_dir).to_track_quat("-Z", "Y").to_euler()

    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*solution["floodLight"]["colorLinear"], 1.0)
    bg.inputs[1].default_value = float(solution["floodLight"]["strength"])

    image = bpy.data.images.new("baked_lit", int(args.size), int(args.size), alpha=False)
    material.use_nodes = True
    tree = material.node_tree
    bake_node = tree.nodes.new("ShaderNodeTexImage")
    bake_node.image = image
    tree.nodes.active = bake_node

    for index, obj in enumerate(meshes):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake(
            type="COMBINED",
            pass_filter={"DIRECT", "INDIRECT", "COLOR", "DIFFUSE", "GLOSSY"},
            margin=BAKE_MARGIN_PX,
            use_clear=(index == 0),
        )

    image.filepath_raw = str(Path(args.out_png).resolve())
    image.file_format = "PNG"
    image.save()


# --------------------------------------------------------------------------- host
def bake_lit_texture(
    src_glb: Path,
    solution_path: Path,
    out_png: Path,
    *,
    size: int = BAKE_SIZE,
    samples: int = BAKE_SAMPLES,
    timeout_s: int = 3600,
) -> Path:
    """Run the Blender COMBINED bake for ``src_glb`` under ``solution_path``'s rig into ``out_png``."""
    blender = Path(BLENDER)
    if not blender.is_file():
        raise FileNotFoundError(blender)
    solution = json.loads(Path(solution_path).read_text(encoding="utf-8"))
    if Path(solution["glb"]).resolve() != Path(src_glb).resolve():
        raise ValueError(f"light solution was solved on {solution['glb']} but the bake mesh is {src_glb}")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(blender), "-b", "--python", str(Path(__file__).resolve()), "--",
            "--glb", str(Path(src_glb).resolve()), "--solution", str(Path(solution_path).resolve()),
            "--out-png", str(out_png.resolve()), "--size", str(int(size)), "--samples", str(int(samples)),
        ],
        text=True, capture_output=True, timeout=timeout_s,
    )
    if completed.returncode != 0 or not out_png.is_file():
        raise RuntimeError(
            f"blender bake failed with exit {completed.returncode}\n"
            + completed.stdout[-4000:] + completed.stderr[-4000:]
        )
    return out_png


def _solid_png(rgb: tuple[int, int, int]) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def _append_image(doc: dict[str, Any], bin_blob: bytearray, png: bytes, name: str) -> int:
    pad = (4 - len(bin_blob) % 4) % 4
    bin_blob += b"\x00" * pad
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(bin_blob), "byteLength": len(png)})
    bin_blob += png
    doc["images"].append({"bufferView": len(doc["bufferViews"]) - 1, "mimeType": "image/png", "name": name})
    return len(doc["images"]) - 1


def write_glb_with_basecolor(
    src_glb: Path, dest_glb: Path, png_path: Path, *, neutralize_pbr: bool = False
) -> dict[str, Any]:
    """Copy the GLB with baseColorTexture bytes swapped for ``png_path``.

    Nodes, skin and accessors are untouched, so solved clip poses still apply.
    ``neutralize_pbr`` additionally points material 0's metallicRoughnessTexture at a
    solid (metallic 0, roughness 1) image and its normalTexture at a flat normal, and
    zeroes metallicFactor, so a downstream lit renderer (the OE Hex/Lit material) adds
    only plain diffuse over the already-baked albedo instead of re-lighting specular.
    A lit engine still shades the baked texture a second time; that is not removable
    without an unlit material and is recorded in the returned report.
    """
    sys.path.insert(0, str(TOOL))
    from gpu_cascade_delivery import _read_glb, _write_glb

    doc, bin_blob = _read_glb(src_glb)
    material = doc["materials"][0]
    pbr = material["pbrMetallicRoughness"]
    base_ref = pbr["baseColorTexture"]
    texture = doc["textures"][int(base_ref["index"])]
    image = doc["images"][int(texture["source"])]
    png = png_path.read_bytes()
    pad = (4 - len(bin_blob) % 4) % 4
    bin_blob += b"\x00" * pad
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(bin_blob), "byteLength": len(png)})
    bin_blob += png
    image["bufferView"] = len(doc["bufferViews"]) - 1
    image["mimeType"] = "image/png"
    image["name"] = "baked_lit_basecolor"

    report: dict[str, Any] = {"output": str(dest_glb), "basecolorBytes": len(png), "pbrNeutralized": bool(neutralize_pbr)}
    if neutralize_pbr:
        _strip_non_engine_material_inputs(doc, material)
        _set_neutral_pbr_maps(doc, bin_blob, material, replace_existing=True)
        report["engineNote"] = "lit engine still applies diffuse shading over the baked albedo"
    doc["buffers"] = [{"byteLength": len(bin_blob)}]
    _write_glb(dest_glb, doc, bin_blob)
    return report


NON_ENGINE_MATERIAL_EXTENSIONS = ("KHR_materials_specular", "KHR_materials_ior")


def _strip_non_engine_material_inputs(doc: dict[str, Any], material: dict[str, Any]) -> list[str]:
    """Remove material inputs the OE Hex/Lit rebind never reads (emission, specular/ior extensions)."""
    removed: list[str] = []
    for key in ("emissiveTexture", "emissiveFactor"):
        if key in material:
            material.pop(key)
            removed.append(key)
    extensions = material.get("extensions") or {}
    for name in NON_ENGINE_MATERIAL_EXTENSIONS:
        if name in extensions:
            extensions.pop(name)
            removed.append(name)
    if not extensions:
        material.pop("extensions", None)
    still_used = {name for mat in doc.get("materials", []) for name in (mat.get("extensions") or {})}
    if "extensionsUsed" in doc:
        doc["extensionsUsed"] = [name for name in doc["extensionsUsed"] if name not in NON_ENGINE_MATERIAL_EXTENSIONS or name in still_used]
        if not doc["extensionsUsed"]:
            doc.pop("extensionsUsed")
    return removed


def _set_neutral_pbr_maps(
    doc: dict[str, Any], bin_blob: bytearray, material: dict[str, Any], *, replace_existing: bool
) -> list[str]:
    """Point metallicRoughness at metallic 0 / roughness 1 and normal at flat, adding maps when absent."""
    pbr = material["pbrMetallicRoughness"]
    changed: list[str] = []
    if replace_existing or "metallicRoughnessTexture" not in pbr:
        # glTF metallicRoughness: G = roughness, B = metallic.
        mr_image = _append_image(doc, bin_blob, _solid_png((255, 255, 0)), "neutral_metallic_roughness")
        doc["textures"].append({"source": mr_image})
        pbr["metallicRoughnessTexture"] = {"index": len(doc["textures"]) - 1}
        changed.append("metallicRoughnessTexture")
    if replace_existing or "normalTexture" not in material:
        normal_image = _append_image(doc, bin_blob, _solid_png((128, 128, 255)), "flat_normal")
        doc["textures"].append({"source": normal_image})
        material["normalTexture"] = {"index": len(doc["textures"]) - 1}
        changed.append("normalTexture")
    if replace_existing:
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 1.0
    return changed


def write_engine_material_glb(src_glb: Path, dest_glb: Path) -> dict[str, Any]:
    """Copy ``src_glb`` with material 0 reduced to what the OE Hex/Lit rebind actually renders.

    Some Meshy exports (h3_ogre_mage) wire the base colour into ``emissiveTexture`` with
    ``emissiveFactor`` 1, add ``KHR_materials_specular`` 2.0, and ship no metallicRoughness
    or normal map (so glTF's default ``metallicFactor`` 1 makes Blender treat the whole
    surface as metal). The engine reads only albedo / normal / metallic-gloss, so a light
    solve or bake on the raw file is fitting a material the game never shows. This writes
    the engine-equivalent material: emission and the specular/ior extensions removed,
    neutral metallicRoughness and flat normal added only where the source has none, and
    metallicFactor forced to 0 when the source relied on the glTF default. Existing PBR
    maps are kept. Nodes, skin and accessors are untouched. The report says exactly what
    changed; ``changed`` empty means the source already was engine-shaped.
    """
    sys.path.insert(0, str(TOOL))
    from gpu_cascade_delivery import _read_glb, _write_glb

    doc, bin_blob = _read_glb(src_glb)
    material = doc["materials"][0]
    removed = _strip_non_engine_material_inputs(doc, material)
    pbr = material["pbrMetallicRoughness"]
    added = _set_neutral_pbr_maps(doc, bin_blob, material, replace_existing=False)
    if "metallicRoughnessTexture" in added and pbr.get("metallicFactor", 1.0) != 0.0:
        # glTF metallic = metallicFactor x map.B; also zero the factor so a reader that
        # ignores the map (the engine extract reads factor-less maps) sees a dielectric.
        pbr["metallicFactor"] = 0.0
        added.append("metallicFactor")
    doc["buffers"] = [{"byteLength": len(bin_blob)}]
    _write_glb(dest_glb, doc, bin_blob)
    return {"source": str(src_glb), "output": str(dest_glb), "removed": removed, "added": added, "changed": removed + added}


def write_reverse_camera_fit(src_fit: Path, dest_fit: Path) -> Path:
    """Turn the profile camera 180 deg about the world up axis.

    Rotating the skinned mesh's root node is not an option: glTF skinned vertices live in
    skeleton space, so the experiment's bind validation (skin at rest == mesh positions)
    fails. Turning the camera keeps mesh, skin, poses and pixel scale identical.
    The screen offset is left as-is, so the view spins about the world origin; Meshy
    meshes are centred, and the shared crop window absorbs any residual shift.
    """
    import numpy as np

    data = json.loads(src_fit.read_text(encoding="utf-8"))
    up = np.asarray((data.get("profileMetrics") or {}).get("worldUpAxis") or [0.0, 1.0, 0.0], dtype=np.float64)
    up /= np.linalg.norm(up)
    rows = np.asarray(data["basisScreenRows"], dtype=np.float64)
    # 180 deg about `up`: v -> 2 (v.up) up - v
    turned = 2.0 * (rows @ up)[:, None] * up[None, :] - rows
    data["basisScreenRows"] = turned.tolist()
    data["cameraPolicy"] = f"{data.get('cameraPolicy', 'unknown')}+reverse_180_about_world_up"
    dest_fit.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dest_fit


def render_clip(glb: Path, clip_payload: dict[str, Any], camera_fit: Path | None = None):
    sys.path.insert(0, str(TOOL))
    from cascade_clip_pose_tweak import clip_frame_indices, gpu_config_for_preview, target_frame_dir_from_clip
    from nvdiffrast_local import ensure_local_nvdiffrast
    from render_nonbone_deform_gif import _render_rgb
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    ensure_local_nvdiffrast(required=True)
    frames = clip_frame_indices(clip_payload)
    experiment = GpuCascadeExperiment(
        src_glb=glb.resolve(),
        camera_fit=(camera_fit or Path(str(clip_payload["cameraFitPath"]))).resolve(),
        target_frame_dir=target_frame_dir_from_clip(clip_payload),
        frame_indices=frames,
        config=gpu_config_for_preview(clip_payload["config"]),
    )
    poses = {int(key): value for key, value in clip_payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)
    return _render_rgb(experiment, bones, root_t, root_r, vertex_offsets=None), frames, target_frame_dir_from_clip(clip_payload)


def compose_gif(frame_dir: Path, frames, panels: list[tuple[str, Any]], out: Path, panel_height: int) -> Path:
    import numpy as np
    from PIL import Image, ImageDraw

    sys.path.insert(0, str(TOOL))
    from preview_timing import PREVIEW_GIF_FRAME_MS
    from render_nonbone_deform_gif import _content_bbox, _fit_height, _sprite_panel

    raster_size = (int(panels[0][1].shape[2]), int(panels[0][1].shape[1]))
    sprite_stack = np.stack([_sprite_panel(frame_dir, int(index), raster_size) for index in frames])
    stacks = [sprite_stack] + [stack for _, stack in panels]
    left, top, right, bottom = _content_bbox(stacks, margin=4)
    labels = ["sprite"] + [label for label, _ in panels]
    images: list[Image.Image] = []
    for position, frame_index in enumerate(frames):
        tiles = [_fit_height(stack[position][top:bottom, left:right], panel_height) for stack in stacks]
        width = sum(tile.width for tile in tiles) + 6 * (len(tiles) - 1)
        canvas = Image.new("RGB", (width, panel_height + 18), (30, 30, 30))
        draw = ImageDraw.Draw(canvas)
        x = 0
        for label, tile in zip(labels, tiles):
            canvas.paste(tile, (x, 18))
            draw.text((x + 3, 2), f"{label}  f{int(frame_index):02d}", fill=(235, 235, 235))
            x += tile.width + 6
        images.append(canvas)
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, save_all=True, append_images=images[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0, optimize=False)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane", required=True, help="Solved lane under artifacts/pose_picker_runs/<unit>/<clip>/")
    parser.add_argument("--solution", required=True, help="light_solution.json from solve_unit_light_palette.py")
    parser.add_argument("--out", required=True)
    parser.add_argument("--bake-size", type=int, default=BAKE_SIZE)
    parser.add_argument("--bake-samples", type=int, default=BAKE_SAMPLES)
    parser.add_argument("--panel-height", type=int, default=320)
    parser.add_argument("--skip-bake", action="store_true", help="Reuse baked_lit.png already under --out.")
    args = parser.parse_args()

    sys.path.insert(0, str(TOOL))
    from def_mocap_bootstrap import unit_mesh
    from gpu_cascade_delivery import require_pose_units_degrees

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    src_glb = unit_mesh(args.unit, args.clip).resolve()
    solution_path = Path(args.solution).resolve()
    solution = json.loads(solution_path.read_text(encoding="utf-8"))
    if Path(solution["glb"]).resolve() != src_glb:
        raise SystemExit(f"light solution was solved on {solution['glb']} but the clip mesh is {src_glb}")

    baked_png = out / "baked_lit.png"
    if args.skip_bake:
        if not baked_png.is_file():
            raise FileNotFoundError(baked_png)
    else:
        print("baking lit texture...", flush=True)
        bake_lit_texture(src_glb, solution_path, baked_png, size=args.bake_size, samples=args.bake_samples)

    baked_glb = out / f"{args.unit}_prebaked.glb"
    written = write_glb_with_basecolor(src_glb, baked_glb, baked_png)

    clip_path = ROOT / "artifacts/pose_picker_runs" / args.unit / args.clip / args.lane / "solve" / "gpu_clip_result.json"
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    require_pose_units_degrees(payload, source=str(clip_path))
    reverse_fit = write_reverse_camera_fit(Path(str(payload["cameraFitPath"])), out / "reverse_camera_fit.json")
    print("rendering front...", flush=True)
    front_rgb, frames, frame_dir = render_clip(baked_glb, payload)
    print("rendering reverse...", flush=True)
    reverse_rgb, _, _ = render_clip(baked_glb, payload, camera_fit=reverse_fit)

    gif = compose_gif(frame_dir, frames, [("pre-baked front", front_rgb), ("pre-baked reverse", reverse_rgb)], out / "sprite_vs_prebaked_front_reverse.gif", int(args.panel_height))
    report = {
        "proof": "generated-artifact",
        "unit": args.unit,
        "clip": args.clip,
        "lane": args.lane,
        "clipResult": str(clip_path),
        "lightSolution": str(solution_path),
        "bakedTexture": str(baked_png),
        "bakeSize": int(args.bake_size),
        "bakeSamples": int(args.bake_samples),
        "glossyNote": "glossy baked from the front camera; view-dependent term frozen into the texture",
        "glb": written,
        "reverseCameraFit": str(reverse_fit),
        "reverseNote": "camera turned 180 deg about world up; root lateral motion is not mirrored in this view",
        "gif": str(gif),
        "frames": len(frames),
    }
    (out / "showcase_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gif": str(gif), "bakedTexture": str(baked_png)}, indent=2))
    return 0


def _inside_blender() -> bool:
    try:
        import bpy  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


if __name__ == "__main__":
    if _inside_blender():
        _blender_bake(sys.argv[sys.argv.index("--") + 1 :])
    else:
        raise SystemExit(main())
