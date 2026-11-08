#!/usr/bin/env python3
"""Solve a per-unit lighting rig whose lit mesh matches the DEF sprite colour palette.

Why a solver
------------
HoMM3 sprites were rendered with a warm studio key light that is baked into every
pixel; Meshy albedo is painted flat and cool. A single hand-picked tint will not hold
across units (green ogre skin, grey stone gargoyle, gold-trimmed angel), so the light
colours are solved per unit against that unit's own sprite frames.

Rig (fixed shape, solved colours)
---------------------------------
Olden Era shows units from every angle, so the rig is direction-agnostic: one key
light from above (``KEY_ELEVATION_DEG`` with a small front bias) plus a uniform
flood/bounce world. Only their colours and strengths are unknowns (6 numbers).

Method
------
1. Blender (Cycles CUDA) renders the bind mesh at
   several yaws and writes linear passes: diffuse and glossy albedo, plus diffuse and
   glossy shading from a white unit key alone and from a white unit world alone.
   Rendered colour is then ``sum_lobe albedo_lobe * (K * key_lobe + A * world_lobe)``,
   exactly linear in the unknowns, so the optimiser never re-renders. Glossy is not
   optional: Meshy materials are largely metallic, so most visible colour arrives via
   the glossy lobe (h3_hobgoblin diffuse albedo median 0.05).
2. The host converts both the lit-mesh pixels and the sprite pixels to CIELAB and
   minimises the sliced-Wasserstein distance between the two colour clouds. This
   compares palettes, not pixel positions, so bind pose versus idle pose is
   irrelevant and every yaw contributes equally.
3. Blender re-renders with the solved lights (full shading, including glossy that
   the diffuse-only model ignores). The tool fails closed if that real render is not
   closer to the sprite than the white-light baseline.

Outputs under ``--out``: ``passes/``, ``light_solution.json``, ``preview_sheet.png``.

Proof tier: generated artifact. Nothing here feeds a solve or a build yet.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

BLENDER = os.environ.get("HOMM3_POSE_FIT_BLENDER", "V:/Tools/blender-3.5.1/blender.exe")
ROOT = Path(__file__).resolve().parents[2]

KEY_ELEVATION_DEG = 65.0
KEY_AZIMUTH_DEG = 0.0  # from the camera side; kept small so faces are not all in shadow
DEFAULT_YAWS = (0.0, 90.0, 180.0, 270.0)
# 2048 x 48 keeps one cost evaluation near 1 ms; 6000 x 96 measured 18 ms and made the
# solve run for minutes with no visible change in the solved colours.
SWD_PROJECTIONS = 48
SWD_SAMPLES = 2048
RESTARTS = 3
MAX_ITER = 1500
SEED = 7
# Blackbody light model: each light is a colour temperature plus strength. It can be
# warm or cool but never chartreuse/magenta, which the free RGB model will happily
# choose when a sprite has gold highlights (h3_hobgoblin: key #ebff5b).
CCT_MIN_K = 1500.0
CCT_MAX_K = 12000.0
PARAM_COUNT = {"rgb": 6, "blackbody": 4}


# --------------------------------------------------------------------------- Blender
def _blender_side(argv: list[str]) -> None:
    import bpy  # type: ignore
    from mathutils import Euler, Vector  # type: ignore

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("passes", "preview"), required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--yaws", required=True)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--solution", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    yaws = [float(v) for v in args.yaws.split(",")]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh objects imported from {args.glb}")

    pivot = bpy.data.objects.new("turntable_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    roots = [obj for obj in bpy.context.scene.objects if obj.parent is None and obj is not pivot]
    for obj in roots:
        obj.parent = pivot
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for vertex in evaluated.data.vertices:
            world = matrix @ vertex.co
            lo = Vector(min(a, b) for a, b in zip(lo, world))
            hi = Vector(max(a, b) for a, b in zip(hi, world))
    center = (lo + hi) * 0.5
    height = hi.z - lo.z
    if not math.isfinite(height) or height <= 0.0:
        raise RuntimeError("degenerate mesh bounds")
    pivot.location = center
    bpy.context.view_layer.update()
    for obj in roots:
        obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    bpy.context.view_layer.update()

    scene = bpy.context.scene
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from showcase_prebaked_clip import configure_cycles_cuda

    configure_cycles_cuda(bpy.context.preferences.addons["cycles"].preferences, scene)
    scene.cycles.samples = int(args.samples)
    scene.cycles.use_denoising = False
    scene.render.resolution_x = int(args.size)
    scene.render.resolution_y = int(args.size)
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"

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

    def set_lights(key_rgb, key_strength, world_rgb, world_strength) -> None:
        sun_data.color = tuple(key_rgb)
        sun_data.energy = float(key_strength)
        bg.inputs[0].default_value = (*world_rgb, 1.0)
        bg.inputs[1].default_value = float(world_strength)

    if args.mode == "passes":
        view_layer = scene.view_layers[0]
        view_layer.use_pass_diffuse_color = True
        view_layer.use_pass_diffuse_direct = True
        view_layer.use_pass_diffuse_indirect = True
        # Meshy materials are often mostly metallic (h3_hobgoblin diffuse albedo median
        # 0.05); without the glossy lobe the model misses most of the visible colour.
        view_layer.use_pass_glossy_color = True
        view_layer.use_pass_glossy_direct = True
        view_layer.use_pass_glossy_indirect = True
        scene.use_nodes = True
        tree = scene.node_tree
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        render_layers = tree.nodes.new("CompositorNodeRLayers")
        file_out = tree.nodes.new("CompositorNodeOutputFile")
        file_out.format.file_format = "OPEN_EXR"
        file_out.format.color_depth = "32"
        file_out.format.color_mode = "RGBA"
        file_out.file_slots.clear()
        for slot_name, socket in (
            ("albedo", "DiffCol"),
            ("direct", "DiffDir"),
            ("indirect", "DiffInd"),
            ("galbedo", "GlossCol"),
            ("gdirect", "GlossDir"),
            ("gindirect", "GlossInd"),
            ("alpha", "Alpha"),
        ):
            file_out.file_slots.new(slot_name)
            tree.links.new(render_layers.outputs[socket], file_out.inputs[slot_name])

        def read_exr(path: Path):
            image = bpy.data.images.load(str(path), check_existing=False)
            width, height_px = image.size
            import numpy as np  # Blender ships numpy

            buffer = np.empty(width * height_px * 4, dtype=np.float32)
            image.pixels.foreach_get(buffer)
            bpy.data.images.remove(image)
            return buffer.reshape(height_px, width, 4)[::-1]

        import numpy as np

        for yaw in yaws:
            pivot.rotation_euler = Euler((0.0, 0.0, math.radians(yaw)), "XYZ")
            tag = f"yaw{int(round(yaw)):+04d}"
            arrays: dict[str, np.ndarray] = {}
            for light_name, key_s, world_s in (("key", 1.0, 0.0), ("world", 0.0, 1.0)):
                set_lights((1.0, 1.0, 1.0), key_s, (1.0, 1.0, 1.0), world_s)
                pass_dir = out / "passes" / f"{tag}_{light_name}"
                pass_dir.mkdir(parents=True, exist_ok=True)
                file_out.base_path = str(pass_dir)
                scene.frame_set(1)
                bpy.ops.render.render(write_still=False)
                rgb = lambda name: read_exr(pass_dir / f"{name}0001.exr")[..., :3]  # noqa: E731
                arrays[f"{light_name}_shade"] = rgb("direct") + rgb("indirect")
                arrays[f"{light_name}_gloss_shade"] = rgb("gdirect") + rgb("gindirect")
                arrays["albedo"] = rgb("albedo")
                arrays["gloss_albedo"] = rgb("galbedo")
                arrays["alpha"] = read_exr(pass_dir / "alpha0001.exr")[..., 0]
            np.savez_compressed(out / "passes" / f"{tag}.npz", **arrays)
        return

    solution = json.loads(Path(args.solution).read_text(encoding="utf-8"))
    rigs = {
        "white": ((1.0, 1.0, 1.0), 1.0, (1.0, 1.0, 1.0), 1.0),
        "solved": (
            tuple(solution["keyLight"]["colorLinear"]),
            float(solution["keyLight"]["strength"]),
            tuple(solution["floodLight"]["colorLinear"]),
            float(solution["floodLight"]["strength"]),
        ),
    }
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    for rig_name, (key_rgb, key_s, world_rgb, world_s) in rigs.items():
        set_lights(key_rgb, key_s, world_rgb, world_s)
        for yaw in yaws:
            pivot.rotation_euler = Euler((0.0, 0.0, math.radians(yaw)), "XYZ")
            scene.render.filepath = str(out / "preview" / f"{rig_name}_yaw{int(round(yaw)):+04d}.png")
            bpy.ops.render.render(write_still=True)


# --------------------------------------------------------------------------- colour
def srgb_to_linear(x):
    import numpy as np

    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    import numpy as np

    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def linear_rgb_to_lab(rgb):
    """Linear sRGB (D65) -> CIELAB. Input clipped to [0,1]; the display cannot show more."""
    import numpy as np

    rgb = np.clip(rgb, 0.0, 1.0)
    m = np.array(
        [[0.4124564, 0.3575761, 0.1804375],
         [0.2126729, 0.7151522, 0.0721750],
         [0.0193339, 0.1191920, 0.9503041]]
    )
    xyz = rgb @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    lab = np.stack(
        [116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )
    return lab


def sorted_projections(cloud, projections):
    """Project a colour cloud onto the fixed directions and sort each column once."""
    import numpy as np

    return np.sort(cloud @ projections.T, axis=0)


def sliced_wasserstein(a, sorted_b, projections):
    """Mean over fixed unit directions of the 1-D Wasserstein-1 between projected clouds.

    ``sorted_b`` is the target from ``sorted_projections`` (sorted once, reused per call).
    Both clouds must hold the same number of samples; callers sample to ``SWD_SAMPLES``.
    """
    import numpy as np

    pa = np.sort(a @ projections.T, axis=0)
    if pa.shape != sorted_b.shape:
        raise ValueError(f"cloud sample counts differ: {pa.shape} vs {sorted_b.shape}")
    return float(np.mean(np.abs(pa - sorted_b)))


def load_sprite_cloud(frame_dir: Path, stride: int, rng):
    import numpy as np
    from PIL import Image

    frames = sorted(frame_dir.glob("*.png"))
    if not frames:
        raise FileNotFoundError(f"no sprite frames in {frame_dir}")
    pixels = []
    for path in frames[::stride]:
        arr = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
        mask = arr[..., 3] > 0.5
        pixels.append(arr[mask][:, :3])
    cloud = np.concatenate(pixels, axis=0)
    return linear_rgb_to_lab(srgb_to_linear(_sample_rows(cloud, rng, f"sprite pixels in {frame_dir}"))), len(frames[::stride])


def _sample_rows(cloud, rng, what: str):
    if cloud.shape[0] < SWD_SAMPLES:
        raise RuntimeError(f"only {cloud.shape[0]} {what}; need at least {SWD_SAMPLES}")
    return cloud[rng.choice(cloud.shape[0], size=SWD_SAMPLES, replace=False)]


def load_pass_clouds(pass_dir: Path, rng):
    import numpy as np

    keys = ("albedo", "key_shade", "world_shade", "gloss_albedo", "key_gloss_shade", "world_gloss_shade")
    stacks: dict[str, list] = {key: [] for key in keys}
    files = sorted(pass_dir.glob("yaw*.npz"))
    if not files:
        raise FileNotFoundError(f"no pass files in {pass_dir}")
    for path in files:
        data = np.load(path)
        mask = data["alpha"] > 0.5
        for key in keys:
            stacks[key].append(data[key][mask])
    passes = {key: np.concatenate(value) for key, value in stacks.items()}
    count = passes["albedo"].shape[0]
    if count < SWD_SAMPLES:
        raise RuntimeError(f"only {count} covered mesh pixels in {pass_dir}; need at least {SWD_SAMPLES}")
    idx = rng.choice(count, size=SWD_SAMPLES, replace=False)
    return {key: value[idx] for key, value in passes.items()}, len(files)


def cct_to_linear_rgb(kelvin: float):
    """Planckian-locus colour (Kim et al. CIE 1931 fit) as linear sRGB, normalised to max 1."""
    import numpy as np

    t = float(np.clip(kelvin, CCT_MIN_K, CCT_MAX_K))
    if t <= 4000.0:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222.0:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000.0:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    xyz = np.array([x / y, 1.0, (1.0 - x - y) / y])
    m = np.array(
        [[3.2404542, -1.5371385, -0.4985314],
         [-0.9692660, 1.8760108, 0.0415560],
         [0.0556434, -0.2040259, 1.0572252]]
    )
    rgb = np.clip(m @ xyz, 0.0, None)
    return rgb / rgb.max()


def _kelvin_from_unit(u: float) -> float:
    """Map an unbounded optimiser variable onto [CCT_MIN_K, CCT_MAX_K] smoothly."""
    return CCT_MIN_K + (CCT_MAX_K - CCT_MIN_K) / (1.0 + math.exp(-u))


def lights_from_params(model: str, params):
    """Return (key_rgb, flood_rgb) linear colours*strength for either light model."""
    import numpy as np

    if model == "rgb":
        return np.exp(params[:3]), np.exp(params[3:6])
    if model == "blackbody":
        key = math.exp(params[0]) * cct_to_linear_rgb(_kelvin_from_unit(params[1]))
        flood = math.exp(params[2]) * cct_to_linear_rgb(_kelvin_from_unit(params[3]))
        return key, flood
    raise ValueError(f"unknown light model {model!r}")


def predict_linear_rgb(passes, key, flood):
    """Rendered linear colour for key/flood light colours: exact for diffuse + glossy lobes."""
    key_term = passes["albedo"] * passes["key_shade"] + passes["gloss_albedo"] * passes["key_gloss_shade"]
    flood_term = passes["albedo"] * passes["world_shade"] + passes["gloss_albedo"] * passes["world_gloss_shade"]
    return key * key_term + flood * flood_term


def solve_lights(passes, sprite_sorted, projections, rng, light_model: str):
    import numpy as np
    from scipy.optimize import minimize

    def cost(params):
        key, flood = lights_from_params(light_model, params)
        return sliced_wasserstein(linear_rgb_to_lab(predict_linear_rgb(passes, key, flood)), sprite_sorted, projections)

    n_params = PARAM_COUNT[light_model]
    # White unit lights: log-strength 0 for rgb; for blackbody, unit 0 maps to the
    # middle of the Kelvin range (~6750 K, near daylight white).
    baseline_params = np.zeros(n_params)
    baseline_cost = cost(baseline_params)
    best_params, best_cost = None, math.inf
    for restart in range(RESTARTS):
        init = baseline_params if restart == 0 else rng.normal(0.0, 0.7, size=n_params)
        result = minimize(
            cost, init, method="Nelder-Mead",
            options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": MAX_ITER},
        )
        if result.fun < best_cost:
            best_params, best_cost = result.x, float(result.fun)
    if best_params is None or not math.isfinite(best_cost):
        raise RuntimeError("light solve did not produce a finite optimum")
    return best_params, best_cost, baseline_cost


def _split_color(rgb):
    import numpy as np

    rgb = np.asarray(rgb, dtype=np.float64)
    strength = float(rgb.max())
    if strength <= 0.0:
        raise RuntimeError("solved light has zero strength")
    color = rgb / strength
    hex_srgb = "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in linear_to_srgb(color))
    return {"colorLinear": [float(v) for v in color], "colorSrgbHex": hex_srgb, "strength": strength}


def _compose_sheet(out: Path, sprite_frame: Path, yaws, size: int) -> Path:
    from PIL import Image, ImageDraw

    label_h = 18
    cols = 1 + len(yaws)
    rows = 2
    sheet = Image.new("RGB", (cols * size, rows * (size + label_h)), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)

    def fit(img):
        img = img.convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        scale = min((size - 8) / max(1, img.width), (size - 8) / max(1, img.height))
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        tile = Image.new("RGBA", (size, size), (40, 40, 40, 255))
        tile.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
        return tile.convert("RGB")

    for row, rig in enumerate(("white", "solved")):
        y0 = row * (size + label_h)
        sheet.paste(fit(Image.open(sprite_frame)), (0, y0 + label_h))
        draw.text((4, y0 + 2), "sprite f0", fill=(255, 255, 255))
        for col, yaw in enumerate(yaws, start=1):
            path = out / "preview" / f"{rig}_yaw{int(round(yaw)):+04d}.png"
            sheet.paste(fit(Image.open(path)), (col * size, y0 + label_h))
            draw.text((col * size + 4, y0 + 2), f"{rig} light | yaw {yaw:+.0f}", fill=(255, 255, 255))
    sheet_path = out / "preview_sheet.png"
    sheet.save(sheet_path)
    return sheet_path


def _rendered_cloud(out: Path, rig: str, yaws, rng):
    import numpy as np
    from PIL import Image

    pixels = []
    for yaw in yaws:
        arr = np.asarray(Image.open(out / "preview" / f"{rig}_yaw{int(round(yaw)):+04d}.png").convert("RGBA"), dtype=np.float32) / 255.0
        pixels.append(arr[arr[..., 3] > 0.5][:, :3])
    cloud = np.concatenate(pixels)
    return linear_rgb_to_lab(srgb_to_linear(_sample_rows(cloud, rng, f"covered pixels in {rig} preview renders")))


def run_blender(mode: str, glb: Path, out: Path, yaws, size: int, samples: int, solution: Path | None) -> None:
    blender = Path(BLENDER)
    if not blender.is_file():
        raise FileNotFoundError(blender)
    command = [
        str(blender), "-b", "--python", str(Path(__file__).resolve()), "--",
        "--mode", mode, "--glb", str(glb.resolve()), "--out", str(out.resolve()),
        f"--yaws={','.join(str(v) for v in yaws)}", "--size", str(size), "--samples", str(samples),
    ]
    if solution is not None:
        command += ["--solution", str(solution.resolve())]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=3600,
        env={**os.environ, "BLENDER_USER_CONFIG": str(ROOT / ".blender_oe_style_config")},
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout[-4000:] + completed.stderr[-4000:])
        raise SystemExit(f"blender {mode} failed with exit {completed.returncode}")


def main() -> int:
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--sprite-dir", required=True, help="Shadow-culled DEF frame directory.")
    parser.add_argument("--sprite-stride", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--yaws", default=",".join(str(v) for v in DEFAULT_YAWS))
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument(
        "--light-model", choices=tuple(PARAM_COUNT), default="blackbody",
        help="blackbody: colour temperature + strength per light (default); rgb: free colour per light.",
    )
    parser.add_argument(
        "--skip-passes", action="store_true",
        help="Reuse passes/ already rendered under --out (same GLB and yaws) and only re-solve.",
    )
    args = parser.parse_args()

    import time

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    glb = Path(args.glb)
    sprite_dir = Path(args.sprite_dir)
    yaws = [float(v) for v in args.yaws.split(",")]
    rng = np.random.default_rng(SEED)
    projections = rng.normal(size=(SWD_PROJECTIONS, 3))
    projections /= np.linalg.norm(projections, axis=1, keepdims=True)
    timings: dict[str, float] = {}

    if args.skip_passes:
        if not (out / "passes").is_dir():
            raise FileNotFoundError(f"--skip-passes given but {out / 'passes'} does not exist")
    else:
        print("rendering linear light passes...", flush=True)
        started = time.perf_counter()
        run_blender("passes", glb, out, yaws, args.size, args.samples, None)
        timings["passesSec"] = round(time.perf_counter() - started, 1)
    passes, n_yaws = load_pass_clouds(out / "passes", rng)
    sprite_lab, n_frames = load_sprite_cloud(sprite_dir, int(args.sprite_stride), rng)
    sprite_sorted = sorted_projections(sprite_lab, projections)

    print("solving key/flood colours...", flush=True)
    started = time.perf_counter()
    params, cost_after, cost_before = solve_lights(passes, sprite_sorted, projections, rng, args.light_model)
    timings["solveSec"] = round(time.perf_counter() - started, 1)
    key_rgb, flood_rgb = lights_from_params(args.light_model, params)
    key_entry = _split_color(key_rgb)
    flood_entry = _split_color(flood_rgb)
    if args.light_model == "blackbody":
        key_entry["kelvin"] = round(_kelvin_from_unit(params[1]))
        flood_entry["kelvin"] = round(_kelvin_from_unit(params[3]))

    solution = {
        "proof": "generated-artifact",
        "unit": args.unit,
        "glb": str(glb.resolve()),
        "spriteDir": str(sprite_dir.resolve()),
        "spriteFramesUsed": n_frames,
        "meshYawsUsed": yaws,
        "rig": {
            "keyType": "sun",
            "keyElevationDeg": KEY_ELEVATION_DEG,
            "keyAzimuthFromCameraDeg": KEY_AZIMUTH_DEG,
            "floodType": "uniform_world_background",
            "note": "Direction is fixed for all-angle viewing; only colours and strengths are solved.",
        },
        "lightModel": args.light_model,
        "keyLight": key_entry,
        "floodLight": flood_entry,
        "objective": "sliced_wasserstein_cielab",
        "modelDistance": {"whiteLight": cost_before, "solved": cost_after},
        "modelNote": "diffuse + glossy linear light model from Cycles passes; emission/transmission not modelled",
    }
    solution_path = out / "light_solution.json"
    solution_path.write_text(json.dumps(solution, indent=2) + "\n", encoding="utf-8")

    print("rendering proof previews...", flush=True)
    started = time.perf_counter()
    run_blender("preview", glb, out, yaws, args.size, args.samples, solution_path)
    timings["previewSec"] = round(time.perf_counter() - started, 1)
    rendered_white = sliced_wasserstein(_rendered_cloud(out, "white", yaws, rng), sprite_sorted, projections)
    rendered_solved = sliced_wasserstein(_rendered_cloud(out, "solved", yaws, rng), sprite_sorted, projections)
    solution["renderedDistance"] = {"whiteLight": rendered_white, "solved": rendered_solved}
    solution["timings"] = timings
    solution_path.write_text(json.dumps(solution, indent=2) + "\n", encoding="utf-8")
    if not rendered_solved < rendered_white:
        raise SystemExit(
            f"solved lights did not bring the real render closer to the sprite "
            f"(white {rendered_white:.3f} vs solved {rendered_solved:.3f}); see {solution_path}"
        )

    sprite_frame = sorted(sprite_dir.glob("*.png"))[0]
    sheet = _compose_sheet(out, sprite_frame, yaws, int(args.size))
    print(
        json.dumps(
            {
                "solution": str(solution_path),
                "sheet": str(sheet),
                "keyLight": solution["keyLight"],
                "floodLight": solution["floodLight"],
                "modelDistance": solution["modelDistance"],
                "renderedDistance": solution["renderedDistance"],
                "timings": timings,
            },
            indent=2,
        )
    )
    return 0


def _inside_blender() -> bool:
    try:
        import bpy  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


if __name__ == "__main__":
    if _inside_blender():
        _blender_side(sys.argv[sys.argv.index("--") + 1 :])
    else:
        raise SystemExit(main())
