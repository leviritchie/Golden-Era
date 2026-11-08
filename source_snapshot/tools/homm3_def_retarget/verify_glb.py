"""Round-trip check: every Unit_* action in the .blend vs the exported GLB, plus loop closure.

Usage: blender -b --factory-startup -P verify_glb.py -- <unit_def_retarget.blend> <unit_def_retarget.glb> <out.json>
Compares world bone-head positions per key frame, and for loop clips checks that the last key
equals the first (so the wrap interpolates instead of snapping).
"""
import bpy, sys, json

argv = sys.argv[sys.argv.index("--") + 1:]
BLEND, GLB, OUT = argv

import numpy as np
from mathutils import kdtree

def mesh_pts(rig):
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.parent is rig and not o.name.endswith("_Rubble") and "Rubble" not in o.name:
            em = o.evaluated_get(dg).to_mesh(); pts += [tuple(o.matrix_world @ v.co) for v in em.vertices]; o.evaluated_get(dg).to_mesh_clear()
    return np.array(pts)

def set_act(ob_id, act, kind):
    ad = ob_id.animation_data
    if ad is None:
        return
    ad.action = act
    sl = [s for s in act.slots if s.target_id_type == kind]
    if sl:
        ad.action_slot = sl[0]

def sample(rig, act):
    set_act(rig, act, 'OBJECT')
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0          # morphs not animated by this clip rest at weight 0 (glTF default)
            if o.data.shape_keys.animation_data is None:
                o.data.shape_keys.animation_data_create()
            set_act(o.data.shape_keys, act, 'KEY')
    f0, f1 = int(round(act.frame_range[0])), int(round(act.frame_range[1]))
    out = []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        out.append({pb.name: tuple(rig.matrix_world @ pb.head) for pb in rig.pose.bones})
        if f in (f0, (f0 + f1) // 2, f1):
            out[-1]["__mesh__"] = mesh_pts(rig)
    return out

bpy.ops.wm.open_mainfile(filepath=BLEND)
bpy.context.scene.render.fps = 12
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skip_def_groups  # noqa: E402
# unit config "skipDefGroups": export_glb.py does not ship these clips, so the GLB must not have them
SKIPPED = skip_def_groups.skipped_clips(skip_def_groups.unit_of_blend_actions(a.name for a in bpy.data.actions))
src = {a.name: sample(rig, a) for a in bpy.data.actions if a.name.startswith("Unit_") and a.name not in SKIPPED}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = 12
bpy.ops.import_scene.gltf(filepath=GLB)
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
res = {}
for name, frames in src.items():
    act = next((a for a in bpy.data.actions if a.name.startswith(name)), None)
    if act is None:
        res[name] = {"missing": True}; continue
    g = sample(rig, act)
    n = min(len(g), len(frames))
    err = max(max(sum((a - b) ** 2 for a, b in zip(frames[i][k], g[i][k])) ** 0.5 for k in frames[i] if k in g[i] and k != "__mesh__") for i in range(n))
    merr = 0.0
    for i in range(n):
        if "__mesh__" in frames[i] and "__mesh__" in g[i]:
            A_, B_ = frames[i]["__mesh__"], g[i]["__mesh__"]
            kd = kdtree.KDTree(len(B_))
            for j, p in enumerate(B_):
                kd.insert(p, j)
            kd.balance()
            merr = max(merr, max(kd.find(p)[2] for p in A_[::7]))
    close = max(sum((a - b) ** 2 for a, b in zip(g[0][k], g[-1][k])) ** 0.5 for k in g[0] if k != "__mesh__")
    res[name] = {"keys": len(g), "srcKeys": len(frames), "maxBoneErr": err, "maxMeshErr": merr, "lastMinusFirst": close}
json.dump(res, open(OUT, "w"), indent=1)
bad = [k for k, v in res.items() if v.get("missing") or (v["keys"] != v["srcKeys"] and not (v["srcKeys"] == 1 and v["keys"] == 2)) or v["maxBoneErr"] > 1e-4 or v["maxMeshErr"] > 2e-3]
# a skipDefGroups clip must be absent from the GLB (it has no row in OUT: every consumer reads rows as round trips)
bad += [f"{n} shipped despite skipDefGroups" for n in SKIPPED
        if any(a.name == n or a.name.startswith(n + "_") for a in bpy.data.actions)]
print("MESHERR", round(max(v.get("maxMeshErr", 0) for v in res.values()), 5))
print("VERIFY", "OK" if not bad else f"BAD {bad}", {k: (v.get("keys"), round(v.get("lastMinusFirst", -1), 5)) for k, v in res.items() if k in ("Unit_Idle", "Unit_Move")})
