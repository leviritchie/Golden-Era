"""Blender side: export the unit's posed mesh (one frame, deformation + corrective morphs applied) as OBJ
for the Unity lighting preview. Never saves the .blend.

    blender -b <unit>_def_retarget.blend --factory-startup -P tools/homm3_prebake/export_posed_obj.py -- \
        --out artifacts/homm3_prebaked_lighting/behemoth/unity/behemoth_f001.obj --frame 1
"""
import argparse
import sys
from pathlib import Path

import bpy  # type: ignore

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--frame", type=int, default=1)
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
sc = bpy.context.scene
sc.frame_set(args.frame)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
obj = max(meshes, key=lambda o: 0 if "Rubble" in o.name else len(o.data.vertices))
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
Path(args.out).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.obj_export(filepath=str(Path(args.out).resolve()), export_selected_objects=True,
                      apply_modifiers=True, export_materials=False, export_uv=True, export_normals=True,
                      forward_axis="NEGATIVE_Z", up_axis="Y")
print("OBJ", args.out)
