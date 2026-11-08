"""Blender side: bake yaw-invariant and directional lighting *terms* in UV space.

Run headless (never saves the .blend):

    blender -b <unit>_def_retarget.blend --factory-startup -P tools/homm3_prebake/bake_terms.py -- \
        --out artifacts/homm3_prebaked_lighting/behemoth/terms --size 2048 --samples 64

The unit's skinned mesh is baked in its bind (rest) pose with shape keys removed in memory,
so every term lives on the source mesh's UVs and can be recombined in numpy without
re-baking. Terms (float16 .npy, top-down UV rows, linear, white diffuse, Meshy normal map applied):

- ``ao``          Cycles AO, distance ``--ao-dist`` x mesh height.
- ``sky``         irradiance from a world that is 1 above the horizon and ``--ground`` below,
                  with occlusion and one bounce (a hemisphere / bent-normal term).
- ``sun_<name>``  shadowed Lambert from one sun (world black). Directions are in the unit's
                  own frame (front = the head side), so mirrored pairs are symmetric about
                  the sagittal plane.
- ``pos``         object-space position (for height gradients).
- ``nrm``         object-space shading normal.

Optional extra terms (``--extras ao_short,thickness,pointiness,nrm_geo``; baked instead of the
standard set, meta written to ``terms_meta_extras.json``):

- ``ao_short``    AO at ``--ao-short-dist`` x height: fine cavity / crevice term.
- ``thickness``   inside-AO at ``--thick-dist`` x height (low = thin extremity).
- ``pointiness``  Cycles pointiness (mesh convexity; ``--weld`` merges UV-split duplicates in
                  memory first, otherwise seams read as creases).
- ``nrm_geo``     object-space geometric normal without the normal map (pairs with ``nrm``
                  for a normal-map bump term).

``--input-hash <file.json>`` bakes nothing: it writes a sha256 over everything a term reads from the .blend
(the chosen mesh's evaluated rest geometry, corner normals, UV maps and topology, its unevaluated data (the
``--weld`` input), modifier stack, world matrix, armature rest matrices, the normal-map image bytes and the
Blender version) so a caller can key its terms cache on content instead of the .blend's bytes, which change on
every save (tools/homm3_unit_look/look.py, terms_key.json). It never initialises the GPU.

Proof tier: generated artifact (Blender-rendered).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

SUNS = {
    # name: (azimuth deg from the unit's front, positive = unit's left, elevation deg)
    "top": (0.0, 89.0),
    "fl": (45.0, 45.0), "fr": (-45.0, 45.0),
    "bl": (135.0, 45.0), "br": (-135.0, 45.0),
    "l": (90.0, 30.0), "r": (-90.0, 30.0),
}


def configure_gpu(scene) -> None:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    used = False
    for dev in prefs.devices:
        dev.use = dev.type == "CUDA"
        used |= dev.use
    if not used:
        raise RuntimeError("CUDA device required")
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


def find_normal_image(obj):
    """The material's normal map (the last image node whose image name starts with "normal"), or None."""
    normal_img = None
    for n in obj.data.materials[0].node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.name.lower().startswith("normal"):
            normal_img = n.image
    return normal_img


def write_input_hash(obj, arm, path: Path) -> None:
    """sha256 over every .blend input of the terms (see the module doc); CPU only, nothing is baked or saved."""
    import hashlib
    import numpy as np  # Blender ships numpy

    h = hashlib.sha256()
    parts = {}

    def put(tag: str, data) -> None:
        b = data if isinstance(data, bytes) else np.ascontiguousarray(data).tobytes()
        h.update(tag.encode() + b"\0" + len(b).to_bytes(8, "little"))
        h.update(b)
        parts[tag] = hashlib.sha256(b).hexdigest()[:16]

    def arr(coll, attr, n, width, dtype):
        buf = np.empty(n * width, dtype=dtype)
        coll.foreach_get(attr, buf)
        return buf

    def mesh_parts(prefix: str, me) -> None:
        nv, nl, np_ = len(me.vertices), len(me.loops), len(me.polygons)
        put(prefix + ".co", arr(me.vertices, "co", nv, 3, np.float32))
        put(prefix + ".loopVert", arr(me.loops, "vertex_index", nl, 1, np.int32))
        put(prefix + ".polyStart", arr(me.polygons, "loop_start", np_, 1, np.int32))
        put(prefix + ".polyTotal", arr(me.polygons, "loop_total", np_, 1, np.int32))
        put(prefix + ".polySmooth", arr(me.polygons, "use_smooth", np_, 1, bool))
        put(prefix + ".cornerNormals", arr(me.corner_normals, "vector", nl, 3, np.float32))
        for i, uv in enumerate(me.uv_layers):
            put(f"{prefix}.uv{i}:{uv.name}:{int(uv.active)}{int(uv.active_render)}", arr(uv.uv, "vector", nl, 2, np.float32))

    put("blender", bpy.app.version_string.encode())
    put("object", obj.name.encode())
    put("matrixWorld", np.array(obj.matrix_world, dtype=np.float64))
    put("modifiers", json.dumps([[m.name, m.type, bool(m.show_render)] for m in obj.modifiers]).encode())
    mesh_parts("data", obj.data)
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        mesh_parts("evaluated", me)
    finally:
        ev.to_mesh_clear()
    if arm is not None:
        put("armatureMatrixWorld", np.array(arm.matrix_world, dtype=np.float64))
        put("bones", json.dumps([[b.name, [list(r) for r in b.matrix_local]] for b in arm.data.bones]).encode())
    img = find_normal_image(obj)
    if img is None:
        put("normalImage", b"none")
    else:
        src = img.packed_file.data if img.packed_file else Path(bpy.path.abspath(img.filepath)).read_bytes()
        put("normalImage:" + img.name, bytes(src))
    path.write_text(json.dumps({"schema": "homm3_bake_terms_input_hash.v1", "sha256": h.hexdigest(),
                                "blend": bpy.data.filepath, "parts": parts}, indent=1), encoding="utf-8")
    print("INPUT_HASH", h.hexdigest(), flush=True)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--mesh", default="")
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--ao-dist", type=float, default=0.12)
    ap.add_argument("--ground", type=float, default=0.25)
    ap.add_argument("--only", default="")
    ap.add_argument("--front", default="auto", choices=["auto", *AXES],
                    help="unit's facing axis in Blender world (auto = Head-Hips offset)")
    ap.add_argument("--extras", default="", help="bake only these optional terms (see module doc)")
    ap.add_argument("--ao-short-dist", type=float, default=0.015)
    ap.add_argument("--thick-dist", type=float, default=0.05)
    ap.add_argument("--weld", type=float, default=0.0, help="merge-by-distance (m) in memory before baking")
    ap.add_argument("--input-hash", default="", help="write the terms' .blend input hash to this JSON and exit")
    args = ap.parse_args(argv)
    scene = bpy.context.scene
    if not args.input_hash:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        configure_gpu(scene)
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = False
        scene.render.bake.margin = 16
        scene.render.bake.use_clear = True

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    obj = bpy.data.objects[args.mesh] if args.mesh else max(meshes, key=lambda o: 0 if "Rubble" in o.name else len(o.data.vertices))
    for o in bpy.data.objects:
        if o.type == "MESH" and o is not obj:
            o.hide_render = True
    arm = next((m.object for m in obj.modifiers if m.type == "ARMATURE"), None)
    if arm is not None:
        arm.data.pose_position = "REST"
    if obj.data.shape_keys:
        obj.animation_data_clear()
        obj.data.animation_data_clear() if obj.data.animation_data else None
        obj.shape_key_clear()
    if args.input_hash:
        bpy.context.view_layer.update()
        write_input_hash(obj, arm, Path(args.input_hash))
        return
    if args.weld > 0:
        import bmesh  # type: ignore

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        n0 = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=args.weld)
        bm.to_mesh(obj.data)
        print("WELD", n0, "->", len(bm.verts), flush=True)
        bm.free()
    bpy.context.view_layer.update()

    # Unit frame: front is the side the Head bone sits on, relative to Hips (ground plane).
    front, front_source = resolve_front(arm, args.front)
    print("FRONT", tuple(round(c, 3) for c in front), front_source, flush=True)
    left = Vector((0, 0, 1)).cross(front).normalized()

    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    zs = [(obj.matrix_world @ v.co).z for v in ev.data.vertices]
    height = max(zs) - min(zs)

    # Source textures from the existing material.
    normal_img = find_normal_image(obj)

    mat = bpy.data.materials.new("prebake_white")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (1, 1, 1, 1)
    emis = nt.nodes.new("ShaderNodeEmission")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    tco = nt.nodes.new("ShaderNodeTexCoord")
    if normal_img is not None:
        nimg = nt.nodes.new("ShaderNodeTexImage")
        nimg.image = normal_img
        nimg.image.colorspace_settings.name = "Non-Color"
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nimg.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], diff.inputs["Normal"])
    target = nt.nodes.new("ShaderNodeTexImage")
    nt.nodes.active = target
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    world = bpy.data.worlds.new("prebake_world")
    scene.world = world
    world.use_nodes = True
    wt = world.node_tree
    bg = wt.nodes["Background"]
    wtc = wt.nodes.new("ShaderNodeTexCoord")
    sep = wt.nodes.new("ShaderNodeSeparateXYZ")
    mr = wt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -0.15
    mr.inputs["From Max"].default_value = 0.15
    mr.inputs["To Min"].default_value = args.ground
    mr.inputs["To Max"].default_value = 1.0
    wt.links.new(wtc.outputs["Generated"], sep.inputs["Vector"])
    wt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    world.light_settings.distance = args.ao_dist * height

    def set_world(mode: str) -> None:
        for l in list(bg.inputs["Color"].links):
            wt.links.remove(l)
        if mode == "sky":
            wt.links.new(mr.outputs["Result"], bg.inputs["Color"])
            bg.inputs["Strength"].default_value = 1.0
        else:
            bg.inputs["Color"].default_value = (0, 0, 0, 1)
            bg.inputs["Strength"].default_value = 0.0

    def surface(kind: str) -> None:
        for l in list(outn.inputs["Surface"].links):
            nt.links.remove(l)
        for l in list(emis.inputs["Color"].links):
            nt.links.remove(l)
        if kind == "diffuse":
            nt.links.new(diff.outputs["BSDF"], outn.inputs["Surface"])
        elif kind == "pos":
            nt.links.new(tco.outputs["Object"], emis.inputs["Color"])
            nt.links.new(emis.outputs["Emission"], outn.inputs["Surface"])
        elif kind == "nrm":
            nt.links.new(diff.outputs["BSDF"], outn.inputs["Surface"])

    sun_data = bpy.data.lights.new("prebake_sun", "SUN")
    sun_data.angle = math.radians(3.0)
    sun_data.energy = 1.0
    sun = bpy.data.objects.new("prebake_sun", sun_data)
    scene.collection.objects.link(sun)
    for o in bpy.data.objects:
        if o.type == "LIGHT" and o is not sun:
            o.hide_render = True

    def new_target(name: str):
        img = bpy.data.images.new(name, args.size, args.size, alpha=False, float_buffer=True)
        img.colorspace_settings.name = "Non-Color"
        target.image = img
        return img

    def save(img, name: str) -> None:
        import numpy as np  # Blender ships numpy

        buf = np.empty(args.size * args.size * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        # Row 0 of Image.pixels is the bottom (v=0); store top-down like a PNG of the UV map.
        arr = buf.reshape(args.size, args.size, 4)[::-1, :, :3]
        np.save(out / f"{name}.npy", arr.astype(np.float16))

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    only = set(filter(None, args.only.split(",")))
    timings = {}

    def bake(name: str, **kw) -> None:
        if only and name not in only:
            return
        t0 = time.time()
        img = new_target(name)
        bpy.ops.object.bake(**kw)
        save(img, name)
        timings[name] = round(time.time() - t0, 1)
        print(f"BAKED {name} {timings[name]}s", flush=True)

    extras = [e for e in args.extras.split(",") if e]
    if extras:
        sun.hide_render = True
        aon = nt.nodes.new("ShaderNodeAmbientOcclusion")
        aon.only_local = True
        aon.samples = 16
        for e in extras:
            for l in list(outn.inputs["Surface"].links):
                nt.links.remove(l)
            for l in list(emis.inputs["Color"].links):
                nt.links.remove(l)
            if e == "ao_short":
                set_world("sky")
                world.light_settings.distance = args.ao_short_dist * height
                nt.links.new(diff.outputs["BSDF"], outn.inputs["Surface"])
                bake("ao_short", type="AO")
            elif e == "thickness":
                set_world("black")
                aon.inside = True
                aon.inputs["Distance"].default_value = args.thick_dist * height
                nt.links.new(aon.outputs["AO"], emis.inputs["Color"])
                nt.links.new(emis.outputs["Emission"], outn.inputs["Surface"])
                bake("thickness", type="EMIT")
            elif e == "pointiness":
                set_world("black")
                nt.links.new(geo.outputs["Pointiness"], emis.inputs["Color"])
                nt.links.new(emis.outputs["Emission"], outn.inputs["Surface"])
                bake("pointiness", type="EMIT")
            elif e == "nrm_geo":
                set_world("black")
                plain = nt.nodes.new("ShaderNodeBsdfDiffuse")
                nt.links.new(plain.outputs["BSDF"], outn.inputs["Surface"])
                scene.render.bake.normal_space = "OBJECT"
                bake("nrm_geo", type="NORMAL")
            else:
                raise SystemExit(f"unknown extra term {e}")
        meta = {"proof": "generated artifact (Blender Cycles bake)", "blend": bpy.data.filepath,
                "mesh": obj.name, "size": args.size, "samples": args.samples, "height": height,
                "aoShortDistance": args.ao_short_dist * height, "thicknessDistance": args.thick_dist * height,
                "weld": args.weld, "extras": extras, "timings": timings}
        (out / "terms_meta_extras.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print("EXTRAS DONE", json.dumps(timings))
        return

    sun.hide_render = True
    set_world("sky")
    surface("diffuse")
    bake("ao", type="AO")
    bake("sky", type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"})
    set_world("black")
    surface("pos")
    bake("pos", type="EMIT")
    surface("nrm")
    scene.render.bake.normal_space = "OBJECT"
    bake("nrm", type="NORMAL")
    surface("diffuse")
    sun.hide_render = False
    for name, (az, el) in SUNS.items():
        a, e = math.radians(az), math.radians(el)
        horiz = front * math.cos(a) + left * math.sin(a)
        from_dir = (horiz * math.cos(e) + Vector((0, 0, math.sin(e)))).normalized()
        sun.rotation_euler = (-from_dir).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        bake(f"sun_{name}", type="DIFFUSE", pass_filter={"DIRECT"})

    meta = {
        "proof": "generated artifact (Blender Cycles bake)",
        "blend": bpy.data.filepath, "mesh": obj.name, "size": args.size, "samples": args.samples,
        "front": list(front), "frontSource": front_source, "left": list(left), "height": height,
        "aoDistance": world.light_settings.distance, "skyGround": args.ground,
        "normalMap": normal_img.name if normal_img else None,
        "suns": SUNS, "timings": timings,
    }
    (out / "terms_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("TERMS DONE", json.dumps(timings))


main(sys.argv[sys.argv.index("--") + 1:])
