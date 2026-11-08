"""Blender side of facing_proof.py: the four battle facings at chosen animation frames (Workbench, textured).

    blender -b <unit>_def_retarget.blend --factory-startup -P facing_proof_blender.py -- \
        --out DIR --frames 13,14 --front -y [--size 320] [--elev 40]

Cameras are built exactly as render_passes.py builds its battle views (orthographic, elevated ``--elev``,
azimuth from the unit's front towards its left, framed on the frame-1 body), but rendered at every listed
frame, so an attack pose can be seen from each facing. Writes ``f<NNN>_<facing>.png`` (RGBA) and
``facing_meta.json`` (per image: camRight, camForward, bone head/tail world + px). Proof tier: generated
artifact. Never saves the .blend.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # type: ignore
from bpy_extras.object_utils import world_to_camera_view  # type: ignore
from mathutils import Vector  # type: ignore

FACINGS = {"faces_right": -60.0, "faces_left": 60.0, "faces_camera": 0.0, "faces_away": 180.0}  # = render_passes.FACINGS
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--front", required=True, choices=list(AXES))
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--elev", type=float, default=40.0)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = scene.render.resolution_y = a.size
    scene.render.resolution_percentage = 100
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    obj = max(meshes, key=lambda o: 0 if "Rubble" in o.name else len(o.data.vertices))
    arm = next((m.object for m in obj.modifiers if m.type == "ARMATURE"), None)
    front = Vector(AXES[a.front])
    left = Vector((0, 0, 1)).cross(front).normalized()
    scene.frame_set(1)
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    pts = [obj.matrix_world @ v.co for v in ev.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre, extent = (lo + hi) * 0.5, max((hi - lo).x, (hi - lo).y, (hi - lo).z)
    cams = {}
    for facing, az in FACINGS.items():
        cd = bpy.data.cameras.new(f"proof_{facing}")
        cd.type = "ORTHO"
        cd.ortho_scale = extent * 1.6          # wider than the review views: room for effects beyond the body
        cam = bpy.data.objects.new(f"proof_{facing}", cd)
        scene.collection.objects.link(cam)
        r, e = math.radians(az), math.radians(a.elev)
        to_cam = (front * math.cos(r) + left * math.sin(r)) * math.cos(e) + Vector((0, 0, math.sin(e)))
        cam.location = centre + to_cam * extent * 4
        cam.rotation_euler = (-to_cam).to_track_quat("-Z", "Y").to_euler()
        cams[facing] = cam
    meta = {"proof": "generated artifact (Blender Workbench)", "front": list(front), "left": list(left), "elev": a.elev,
            "facings": FACINGS, "images": {}}
    for f in [int(x) for x in a.frames.split(",") if x]:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        for facing, cam in cams.items():
            scene.camera = cam
            name = f"f{f:03d}_{facing}.png"
            scene.render.filepath = str(out / name)
            bpy.ops.render.render(write_still=True)
            m = cam.matrix_world.to_3x3()
            rec = {}
            if arm is not None:
                for bn, pb in arm.pose.bones.items():
                    ent = {}
                    for end in ("head", "tail"):
                        w = arm.matrix_world @ getattr(pb, end)
                        c = world_to_camera_view(scene, cam, w)
                        ent[end] = list(w)
                        ent[end + "Px"] = [c.x * a.size, (1.0 - c.y) * a.size]
                    rec[bn] = ent
            meta["images"][name] = {"frame": f, "facing": facing, "camRight": list(m.col[0]),
                                    "camForward": list(-m.col[2]), "bones": rec}
            print(f"PROOF {name}", flush=True)
    (out / "facing_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("PROOF DONE")


main(sys.argv[sys.argv.index("--") + 1:])
