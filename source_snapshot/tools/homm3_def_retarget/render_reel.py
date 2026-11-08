import bpy,sys,math
from mathutils import Vector
argv=sys.argv[sys.argv.index("--")+1:];out=argv[0]
sc=bpy.context.scene;sc.render.engine='BLENDER_WORKBENCH'
sc.display.shading.light='STUDIO';sc.display.shading.color_type='TEXTURE'
sc.render.film_transparent=True
spr=bpy.data.objects["SpriteCam"]
side=bpy.data.objects.new("SideCam",bpy.data.cameras.new("SideCam"));sc.collection.objects.link(side)
side.data.type='ORTHO';side.data.ortho_scale=3.4
f=Vector((-0.9,0.1,-0.35)).normalized();tgt=Vector((0,0,0.8));side.location=tgt-f*8;side.rotation_euler=f.to_track_quat('-Z','Y').to_euler()
for vn,cam,res in [("sprite",spr,None),("side",side,(400,400))]:
    sc.camera=cam
    if res: sc.render.resolution_x,sc.render.resolution_y=res
    for t in range(sc.frame_start,sc.frame_end+1):
        sc.frame_set(t);sc.render.filepath=f"{out}/{vn}_{t:03d}.png";bpy.ops.render.render(write_still=True)
