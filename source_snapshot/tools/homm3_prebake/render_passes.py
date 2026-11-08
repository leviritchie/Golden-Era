"""Blender side: render per-view UV / normal / sun-shadow passes for numpy relighting.

    blender -b <unit>_def_retarget.blend --factory-startup -P tools/homm3_prebake/render_passes.py -- \
        --out artifacts/homm3_prebaked_lighting/behemoth/views --frames 1,13,50

Every view writes ``<view>.npz`` with float arrays at ``--supersample`` x resolution:

- ``uv``      (H,W,2) texture coordinate per pixel (1 sample, box filter: no UV blending)
- ``alpha``   (H,W)
- ``normal``  (H,W,3) world-space geometric normal (the runtime shader has no normal map)
- ``sun_<c>`` (H,W) shadowed Lambert for arena sun condition ``c`` (white diffuse, sun only)
- ``ndl_<c>`` (H,W) the same without shadows, from ``normal`` (for calibration)

Views: ``sprite_fNNN`` use the build's SpriteCam at frame NNN (1-based, DEF source NNN-1).
``battle_<facing>`` use an orthographic camera elevated ``--elev`` degrees whose azimuth is set
relative to the unit's front, so the unit faces screen-right / screen-left / the camera / away.

Options added for the unit-look pipeline: ``--position`` (``position`` (H,W,3) world position per pixel, for the
point-light relight), ``--bones all|A,B`` (per view, bone head/tail world positions and output-pixel projections
in ``views_meta.json``), ``--conds`` (subset of sun conditions) and ``--no-battle``.

Sun conditions are the installed arenas' serialized MainLight directions, applied relative
to the camera on the *hypothesis* that the battle camera looks along Unity +Z:
``sand`` (sand/dirt/autumn arenas), ``grass`` (grass arenas), ``snow`` (snow/necro arenas).

Proof tier: generated artifact (Blender Cycles render). Never saves the .blend.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore
import numpy as np
from mathutils import Vector  # type: ignore

# Unity MainLight forward (x, y, z) from game_lighting_probe.json; y is up.
ARENA_SUNS = {
    "sand": (0.624, -0.4035, 0.6692),
    "grass": (-0.0215, -0.1804, 0.9834),
    "snow": (0.4011, -0.4035, 0.8224),
}
FACINGS = {
    # camera azimuth, measured from the unit's front towards its left, in degrees
    "faces_right": -60.0,   # camera on the unit's right-front quarter, like the DEF sprite
    "faces_left": 60.0,
    "faces_camera": 0.0,
    "faces_away": 180.0,
}


def configure_gpu(scene) -> None:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = dev.type == "CUDA"
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"


AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}


def resolve_front(arm, spec: str):
    """Unit front (horizontal, world). ``spec`` is ``auto`` or an axis (+x/-x/+y/-y).

    ``auto`` uses the Head bone's horizontal offset from Hips. That works for a hunched or
    quadruped body (the Behemoth resolves to -Y) but not for an upright biped, whose head sits
    almost straight above the hips, so ``auto`` refuses when the offset is under 10% of the
    Head-Hips distance instead of guessing; pass ``--front`` then."""
    if spec != "auto":
        return Vector(AXES[spec]), spec
    if arm is None or "Head" not in arm.data.bones or "Hips" not in arm.data.bones:
        raise SystemExit("--front auto needs an armature with Head and Hips bones; pass --front +x/-x/+y/-y")
    d = arm.data.bones["Head"].head_local - arm.data.bones["Hips"].head_local
    full = d.length
    d.z = 0.0
    if d.length < 0.1 * max(full, 1e-6):
        raise SystemExit(f"--front auto: Head is nearly above Hips (horizontal {d.length:.4f} of {full:.4f}); "
                         "facing is ambiguous, pass --front +x/-x/+y/-y")
    return d.normalized(), "auto:Head-Hips"


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", default="1")
    ap.add_argument("--supersample", type=int, default=4)
    ap.add_argument("--battle-size", type=int, default=160)
    ap.add_argument("--elev", type=float, default=40.0)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--views", default="")
    ap.add_argument("--front", default="auto", choices=["auto", *AXES],
                    help="unit's facing axis in Blender world (auto = Head-Hips offset)")
    ap.add_argument("--position", action="store_true",
                    help="also store ``position`` (H,W,3) world-space position per pixel (point-light relight)")
    ap.add_argument("--bones", default="",
                    help="comma list of bones (or 'all'): per view, record each bone head/tail in world space "
                         "and projected to output pixels (x right, y down) in views_meta.json")
    ap.add_argument("--conds", default=",".join(ARENA_SUNS), help="arena sun conditions to render")
    ap.add_argument("--no-battle", action="store_true", help="sprite views only (skip the four battle facings)")
    args = ap.parse_args(argv)
    conds = [c for c in args.conds.split(",") if c]
    for c in conds:
        if c not in ARENA_SUNS:
            raise SystemExit(f"unknown --conds entry {c!r}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)

    scene = bpy.context.scene
    configure_gpu(scene)
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"
    scene.cycles.use_denoising = False
    scene.cycles.pixel_filter_type = "BOX"
    scene.cycles.filter_width = 0.01

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    obj = max(meshes, key=lambda o: 0 if "Rubble" in o.name else len(o.data.vertices))
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            o.hide_render = True
    arm = next((m.object for m in obj.modifiers if m.type == "ARMATURE"), None)
    front, front_source = resolve_front(arm, args.front)
    print("FRONT", tuple(round(c, 3) for c in front), front_source, flush=True)
    left = Vector((0, 0, 1)).cross(front).normalized()

    mat = bpy.data.materials.new("prebake_white")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (1, 1, 1, 1)
    nt.links.new(diff.outputs["BSDF"], outn.inputs["Surface"])
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)

    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = world

    sun_data = bpy.data.lights.new("arena_sun", "SUN")
    sun_data.energy = 1.0
    sun_data.angle = math.radians(1.0)
    sun = bpy.data.objects.new("arena_sun", sun_data)
    scene.collection.objects.link(sun)

    vl = scene.view_layers[0]
    vl.use_pass_uv = True
    vl.use_pass_normal = True
    vl.use_pass_diffuse_direct = True
    if args.position:
        vl.use_pass_position = True
    try:
        scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
    except TypeError:  # Blender 5.x splits media type from format
        scene.render.image_settings.media_type = "MULTI_LAYER_IMAGE"
        scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
    scene.render.image_settings.color_depth = "32"
    scene.render.use_compositing = False

    def render_pass(cam, w: int, h: int, samples: int) -> dict:
        """Render one multilayer EXR and read its passes with OpenImageIO (bundled with Blender)."""
        import OpenImageIO as oiio  # type: ignore

        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = w, h
        scene.render.resolution_percentage = 100
        scene.cycles.samples = samples
        path = tmp / "passes.exr"
        if path.exists():
            path.unlink()
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=False)
        bpy.data.images["Render Result"].save_render(filepath=str(path), scene=scene)
        if not path.exists():
            raise RuntimeError(f"render not written to {path}")
        # Blender 5 writes a multipart EXR: one part per pass.
        chan = {}
        inp = oiio.ImageInput.open(str(path))
        part = 0
        while inp.seek_subimage(part, 0):
            spec = inp.spec()
            px = inp.read_image(part, 0, 0, spec.nchannels, oiio.FLOAT)
            px = px.reshape(spec.height, spec.width, spec.nchannels)
            for ci, cname in enumerate(spec.channelnames):
                chan[cname] = px[..., ci]
            part += 1
        inp.close()

        def chans(prefix_opts, comps):
            for prefix in prefix_opts:
                keys = [f"{prefix}.{c}" for c in comps]
                if all(k in chan for k in keys):
                    return np.stack([chan[k] for k in keys], axis=-1)
            raise RuntimeError(f"missing pass {prefix_opts}; channels {sorted(chan)[:40]}")

        return {
            "uv": chans(["ViewLayer.UV"], ["U", "V"]),
            "normal": chans(["ViewLayer.Normal"], ["X", "Y", "Z"]),
            "diffdir": chans(["ViewLayer.DiffDir", "ViewLayer.Diffuse Direct"], ["R", "G", "B"]),
            "alpha": chans(["ViewLayer.Combined"], ["A"]),
            **({"position": chans(["ViewLayer.Position"], ["X", "Y", "Z"])} if args.position else {}),
        }

    def cam_basis(cam):
        m = cam.matrix_world.to_3x3()
        right = (m @ Vector((1, 0, 0))).normalized()
        fwd = (m @ Vector((0, 0, -1))).normalized()
        return right, fwd

    def set_sun(cam, cond: str):
        ux, uy, uz = ARENA_SUNS[cond]
        right, fwd = cam_basis(cam)
        rh = Vector((right.x, right.y, 0)).normalized()
        fh = Vector((fwd.x, fwd.y, 0)).normalized()
        travel = (rh * ux + fh * uz + Vector((0, 0, 1)) * uy).normalized()
        sun.rotation_euler = travel.to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        return -travel

    views = []
    spr = bpy.data.objects.get("SpriteCam")
    for f in [int(v) for v in args.frames.split(",") if v]:
        views.append((f"sprite_f{f:03d}", spr, f, scene.render.resolution_x, scene.render.resolution_y))
    # Battle camera, built once per facing around the frame-1 body centre.
    scene.frame_set(1)
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    pts = [obj.matrix_world @ v.co for v in ev.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) * 0.5
    extent = max((hi - lo).x, (hi - lo).y, (hi - lo).z)
    for facing, az in ({} if args.no_battle else FACINGS).items():
        cd = bpy.data.cameras.new(f"battle_{facing}")
        cd.type = "ORTHO"
        cd.ortho_scale = extent * 1.15
        cam = bpy.data.objects.new(f"battle_{facing}", cd)
        scene.collection.objects.link(cam)
        a, e = math.radians(az), math.radians(args.elev)
        to_cam = (front * math.cos(a) + left * math.sin(a)) * math.cos(e) + Vector((0, 0, math.sin(e)))
        cam.location = centre + to_cam * extent * 4
        cam.rotation_euler = (-to_cam).to_track_quat("-Z", "Y").to_euler()
        views.append((f"battle_{facing}", cam, 1, args.battle_size, args.battle_size))

    only = set(filter(None, args.views.split(",")))
    meta = {"proof": "generated artifact (Blender Cycles passes)", "front": list(front), "frontSource": front_source, "left": list(left),
            "arenaSuns": {c: ARENA_SUNS[c] for c in conds}, "facings": FACINGS, "elev": args.elev, "views": {}}
    ss = args.supersample
    for name, cam, frame, w, h in views:
        if only and name not in only:
            continue
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        sun.hide_render = True
        base = render_pass(cam, w * ss, h * ss, 1)
        data = {"uv": base["uv"][..., :2].astype(np.float32), "alpha": base["alpha"][..., 0].astype(np.float32),
                "normal": base["normal"][..., :3].astype(np.float32)}
        if args.position:
            data["position"] = base["position"][..., :3].astype(np.float32)
        sun.hide_render = False
        suns = {}
        for cond in conds:
            from_dir = set_sun(cam, cond)
            r = render_pass(cam, w * ss, h * ss, args.samples)
            data[f"sun_{cond}"] = r["diffdir"][..., 0].astype(np.float32)
            n = data["normal"]
            data[f"ndl_{cond}"] = np.clip(n @ np.array(from_dir, dtype=np.float32), 0, None).astype(np.float32)
            suns[cond] = list(from_dir)
        right, fwd = cam_basis(cam)
        np.savez_compressed(out / f"{name}.npz", **data)
        meta["views"][name] = {"frame": frame, "size": [w, h], "supersample": ss,
                               "camRight": list(right), "camForward": list(fwd), "sunFrom": suns}
        if args.bones and arm is not None:
            from bpy_extras.object_utils import world_to_camera_view  # type: ignore
            want = list(arm.pose.bones.keys()) if args.bones == "all" else [b for b in args.bones.split(",") if b]
            rec = {}
            for bn in want:
                pb = arm.pose.bones.get(bn)
                if pb is None:
                    continue
                ent = {}
                for end in ("head", "tail"):
                    wpos = arm.matrix_world @ getattr(pb, end)
                    c = world_to_camera_view(scene, cam, wpos)
                    ent[end] = list(wpos)
                    ent[end + "Px"] = [c.x * w, (1.0 - c.y) * h]
                rec[bn] = ent
            meta["views"][name]["bones"] = rec
        print(f"VIEW {name} done", flush=True)
    (out / "views_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("VIEWS DONE")


main(sys.argv[sys.argv.index("--") + 1:])
