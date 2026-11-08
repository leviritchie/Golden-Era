import bpy,sys,json,numpy as np
out=sys.argv[sys.argv.index("--")+1]
sc=bpy.context.scene;ob=next(o for o in bpy.data.objects if o.type=="MESH" and "Armature" in o.modifiers and not o.name.endswith("_Rubble"));dg=bpy.context.evaluated_depsgraph_get()
E=np.array([e.vertices[:] for e in ob.data.edges]);R=np.array([v.co[:] for v in ob.data.vertices])
L0=np.linalg.norm(R[E[:,0]]-R[E[:,1]],axis=1);ok=L0>1e-5
res=[]
for t in range(sc.frame_start,sc.frame_end+1):
    sc.frame_set(t);me=ob.evaluated_get(dg).to_mesh()
    P=np.array([v.co[:] for v in me.vertices]);ob.evaluated_get(dg).to_mesh_clear()
    r=np.linalg.norm(P[E[:,0]]-P[E[:,1]],axis=1)[ok]/L0[ok]
    res.append([float(r.max()),float(np.percentile(r,99.9)),int((r>2).sum())])
json.dump(res,open(out,"w"))
