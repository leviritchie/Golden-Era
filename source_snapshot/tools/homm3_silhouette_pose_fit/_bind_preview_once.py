
import json, sys
from pathlib import Path
import bpy
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera

OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_meshy46_bind_diag"
MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3.glb"
SPRITE = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames_painted_g11/frame_00.png"
OUT.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(MASTER))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
if arm.animation_data:
    arm.animation_data_clear()
for mat in mesh.data.materials:
    if mat is None or not mat.use_nodes: continue
    nt=mat.node_tree; nodes=nt.nodes; links=nt.links
    outn=next((n for n in nodes if n.type=="OUTPUT_MATERIAL"), None)
    bsdf=next((n for n in nodes if n.type=="BSDF_PRINCIPLED"), None)
    if not outn or not bsdf: continue
    base=bsdf.inputs.get("Base Color")
    emit=nodes.new("ShaderNodeEmission"); emit.inputs["Strength"].default_value=1.0
    if base is not None and base.is_linked: links.new(base.links[0].from_socket, emit.inputs["Color"])
    elif base is not None: emit.inputs["Color"].default_value=tuple(base.default_value)
    for link in list(outn.inputs["Surface"].links): links.remove(link)
    links.new(emit.outputs["Emission"], outn.inputs["Surface"])

world=bpy.data.worlds.new("W"); bpy.context.scene.world=world; world.use_nodes=True
bg=world.node_tree.nodes["Background"]; bg.inputs["Color"].default_value=(0.05,0.05,0.07,1); bg.inputs["Strength"].default_value=0.0
scene=bpy.context.scene; scene.render.engine="BLENDER_EEVEE"; scene.eevee.taa_render_samples=8
scene.render.resolution_x=512; scene.render.resolution_y=512; scene.render.image_settings.file_format="PNG"
job={"camera":{"axis":"iso","isoAzimuthDeg":40.0,"isoElevationDeg":30.0,"distance":3.0,"orthoScale":2.6,"rootYawDeg":0.0}}
setup_pose_camera(job, arm, bpy_module=bpy)
path=OUT/"bind_iso40_el30.png"
scene.render.filepath=str(path)
bpy.ops.render.render(write_still=True)
sprite=Image.open(SPRITE).convert("RGBA")
mesh_im=Image.open(path).convert("RGBA")
# side by side
w=max(sprite.width, mesh_im.width); h=max(sprite.height, mesh_im.height)
canvas=Image.new("RGB",(w*2+16,h+40),(12,12,16))
canvas.paste(sprite.convert("RGB"), ((w-sprite.width)//2, 40), sprite if sprite.mode=="RGBA" else None)
canvas.paste(mesh_im.convert("RGB"), (w+16+(w-mesh_im.width)//2, 40))
d=ImageDraw.Draw(canvas); d.text((8,8),"painted f0",fill=(220,220,220)); d.text((w+24,8),"meshy46 bind iso",fill=(220,220,220))
out=OUT/"bind_vs_painted_f0.png"; canvas.save(out)
print(json.dumps({"ok":True,"out":str(out).replace("\\\\","/")}))
