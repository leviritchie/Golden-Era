
import bpy, json, sys, pathlib, numpy as np, math
from mathutils import Vector, Euler
job_path = pathlib.Path(sys.argv[sys.argv.index("--")+1])
job=json.loads(job_path.read_text())
out_dir=pathlib.Path(job.get("outputDir_abs") or job.get("outputDir"))
export_dir=pathlib.Path(job.get("exportDir_abs") or job.get("exportDir") or (out_dir.parent/"export"))
frames_meta=job["frames"]
import sys as _sys
_sys.path.insert(0, str(pathlib.Path(r"V:\Games\Olden Era Playtest Tweak\tools\homm3_silhouette_pose_fit")))
from homm3_pose_camera import setup_pose_camera
# load buffers for cam but not needed for bake
bpy.ops.wm.read_factory_settings(use_empty=True)
import os
master_path = job.get("masterGlb_abs") or job.get("masterGlb")
bpy.ops.import_scene.gltf(filepath=master_path)
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]
mesh=[o for o in bpy.data.objects if o.type=='MESH'][0]
names=[str(b) for b in job.get("optimizeBones")]
# compute basis
cam=setup_pose_camera(job, arm, bpy_module=bpy)
mw=cam.matrix_world
right_w=(mw.to_quaternion() @ Vector((1.0,0.0,0.0))).normalized()
up_w=(mw.to_quaternion() @ Vector((0.0,1.0,0.0))).normalized()
forward_w=(mw.to_quaternion() @ Vector((0.0,0.0,-1.0))).normalized()
arm_inv=arm.matrix_world.inverted().to_3x3()
right=(arm_inv @ right_w).normalized()
up=(arm_inv @ up_w).normalized()
forward=(arm_inv @ forward_w).normalized()
basis=(right,up,forward)
def apply_vec(vec):
    for i,name in enumerate(names):
        pb=arm.pose.bones[name]
        pb.rotation_mode='XYZ'
        o=i*6
        u,v,d=float(vec[o]),float(vec[o+1]),float(vec[o+2])
        rx,ry,rz=float(vec[o+3]),float(vec[o+4]),float(vec[o+5])
        loc=right*u + up*v + forward*d
        pb.location=loc
        pb.rotation_euler=Euler((rx,ry,rz),'XYZ')
# clear anim
if arm.animation_data is not None:
    arm.animation_data_clear()
arm.animation_data_create()
# group by clip
from collections import defaultdict
groups={}
for i, fr in enumerate(frames_meta):
    cid=str(fr.get("clipId") or fr.get("actionName") or "clip")
    groups.setdefault(cid, []).append(i)
import pathlib
fps=float(job.get("fps",12))
bpy.context.scene.render.fps=int(round(fps))
clip_map={"schema":"homm3_pseudo_rig_clip_map.v1","clips":[]}
for clip_id, indices in groups.items():
    # only those with pose files present? We'll check
    # filter to those where pose file exists
    present=[idx for idx in indices if (out_dir/"poses_gpu"/f"pose_{idx:03d}.npy").is_file()]
    if not present:
        continue
    action_name=str(next((fr.get("actionName") for fr in [frames_meta[i] for i in present] if fr.get("actionName")), clip_id))
    action=bpy.data.actions.new(name=action_name)
    arm.animation_data.action=action
    for local_i, global_i in enumerate(present):
        vec=np.load(out_dir/"poses_gpu"/f"pose_{global_i:03d}.npy")
        frame=local_i+1
        bpy.context.scene.frame_set(frame)
        apply_vec(vec)
        for name in names:
            pb=arm.pose.bones[name]
            pb.keyframe_insert(data_path="location", frame=frame)
            pb.keyframe_insert(data_path="rotation_euler", frame=frame)
    track=arm.animation_data.nla_tracks.new()
    track.name=action_name
    track.strips.new(action_name, 1, action)
    arm.animation_data.action=None
    clip_map["clips"].append({"clipId":clip_id,"actionName":action_name,"frameCount":len(present),"cyclic": bool(frames_meta[present[0]].get("cyclic",False)),"globalFrameIndices": present})
export_dir.mkdir(parents=True, exist_ok=True)
out_glb=export_dir/"crusader_pseudo_rig.glb"
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
mesh.select_set(True)
bpy.context.view_layer.objects.active=arm
bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format="GLB", export_skins=True, export_animations=True, export_nla_strips=True, export_force_sampling=True, export_apply=False, export_texcoords=True, export_normals=True, export_materials="EXPORT")
clip_map["outputGlb"]=str(out_glb)
clip_map["proof"]="generated-artifact validated — host pseudo-rig bake; not OE runtime"
clip_path=export_dir/"clip_map.json"
clip_path.write_text(json.dumps(clip_map,indent=2),encoding="utf-8")
print(f"bake done {out_glb}")
