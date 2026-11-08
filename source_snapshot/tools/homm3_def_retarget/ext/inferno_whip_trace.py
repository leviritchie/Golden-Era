"""Trace a held whip's centreline from the mesh (Inferno helper, not a build hook).

Usage: blender -b --factory-startup -P tools/homm3_def_retarget/ext/inferno_whip_trace.py -- \
         <mesh_smartrigged.glb> <unit.json or seed.json> RightHand <out.json> [far=0.16]
Vertices farther than `far` from every body bone segment (foot/shin segments count at 0.06) are
the whip; 4 cm voxel centroids are linked within 7.5 cm, the largest linked set is walked by a
shortest path from the hand, and each path node is replaced by the mean of the centroids within 6 cm
(a cross-section), resampled every 10 cm. Output: list of points (hand first) for a `props` entry
{"segments": [[p0,p1],[p1,p2],...], "radius": 0.06}. Checked against the hand-traced h3_pit_lord
whip: within 0.03 along its whole length. Used for h3_pit_spawn.
"""
# blender -b -P whip.py -- glb joints.json hand out.json [far]
import bpy,sys,json,numpy as np
a=sys.argv[sys.argv.index("--")+1:]; glb,jf,hand,out=a[:4]; far=float(a[4]) if len(a)>4 else 0.16
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=glb)
ob=max((o for o in bpy.data.objects if o.type=='MESH'),key=lambda o:len(o.data.vertices))
M=ob.matrix_world;P=np.array([(<email>)[:] for v in ob.data.vertices])
J=json.load(open(jf));J=J.get('joints',J);J={k:np.array(v) for k,v in J.items() if isinstance(v,list) and len(v)==3}
chain=['Hips','Spine','Spine1','Spine2','Neck','Head','HeadTop_End']
segs=[(chain[i],chain[i+1]) for i in range(6)]
for s in ('Left','Right'):
    segs+=[('Spine2',s+'Shoulder'),(s+'Shoulder',s+'Arm'),(s+'Arm',s+'ForeArm'),(s+'ForeArm',s+'Hand'),(s+'Hand',s+'Hand_End'),('Hips',s+'UpLeg'),(s+'UpLeg',s+'Leg'),(s+'Leg',s+'Foot'),(s+'Foot',s+'ToeBase'),(s+'ToeBase',s+'Toe_End')]
def sd(a,b):
    ab=b-a;t=np.clip((P-a)@ab/(ab@ab),0,1);return np.linalg.norm(P-(a+t[:,None]*ab),axis=1)
D=np.min(np.stack([sd(J[x],J[y])*(far/0.06 if ('Foot' in x+y or 'Toe' in x+y) else 1.0) for x,y in segs]),0)
W=P[D>far]
# voxel centroids
v=np.floor(W/0.04).astype(int);keys,inv=np.unique(v,axis=0,return_inverse=True)
C=np.array([W[inv.ravel()==i].mean(0) for i in range(len(keys))])
# connected components of centroids (adjacency 0.07)
from collections import deque
n=len(C);dd=np.linalg.norm(C[:,None]-C[None],axis=2);adj=dd<0.075
comp=-np.ones(n,int);k=0
for i in range(n):
    if comp[i]>=0: continue
    q=deque([i]);comp[i]=k
    while q:
        u=q.popleft()
        for w in np.nonzero(adj[u]&(comp<0))[0]: comp[w]=k;q.append(w)
    k+=1
sizes=np.bincount(comp);big=np.argmax(sizes)
print("WHIP far",far,"verts",len(W),"centroids",n,"components",sorted(sizes)[::-1][:6])
I=np.nonzero(comp==big)[0]
# geodesic order: BFS distances from centroid nearest hand
h=J[hand];s=I[np.argmin(np.linalg.norm(C[I]-h,axis=1))]
import heapq
dist={s:0.0};pq=[(0.0,s)];prev={}
while pq:
    d,u=heapq.heappop(pq)
    if d>dist[u]: continue
    for w in I[adj[u,I]]:
        nd=d+dd[u,w]
        if nd<dist.get(w,1e9): dist[w]=nd;prev[w]=u;heapq.heappush(pq,(nd,w))
end=max(dist,key=dist.get)
path=[end]
while path[-1]!=s: path.append(prev[path[-1]])
path=path[::-1]
# smooth: average centroids within 0.06 of each path node? use geodesic bins of 0.1
Q=C[path];L=np.array([dist[p] for p in path])
# local centre: mean of all component centroids within 0.06 of each path node (a cross-section),
# then resample every 0.1 along the path
X=np.array([C[I][np.linalg.norm(C[I]-q,axis=1)<0.06].mean(0) for q in Q])
pts=[]
for b_ in np.arange(0,L.max()+1e-6,0.1):
    j=int(np.argmin(abs(L-b_)));pts.append(X[j])
pts.append(X[-1])
pts=[h]+pts
print("WHIP length %.2f points %d start %s end %s"%(L.max(),len(pts),np.round(pts[1],3),np.round(pts[-1],3)))
json.dump([[round(float(x),3) for x in p] for p in pts],open(out,'w'))
