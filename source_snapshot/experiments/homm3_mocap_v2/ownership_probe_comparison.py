"""Textured original/candidate comparison under identical diagnostic rotations."""
import argparse
import json
from pathlib import Path
import numpy as np
from mounted_ownership_diagnostic import probe
from run_skin_mesh_pilot import comparison
from run_skin_weight_pilot import cascade_batch_lock, ROOT
from skin_image_objective import SkinImageRenderer


def run(original,candidate,camera_path,output):
    if output.exists():raise FileExistsError(output)
    with np.load(original) as z:base={k:z[k].copy() for k in z.files}
    with np.load(candidate) as z:trial={k:z[k].copy() for k in z.files}
    camera=json.loads(camera_path.read_text());output.mkdir(parents=True)
    from ownership_candidate_validation import validate_invariants
    validate_invariants(base,trial,weapon_regions=('weapon',))
    data={}
    for target in ('rider:mixamorig:RightArm','rider:mixamorig:LeftArm','mount:Bip01_Neck'):
        sequences=[]
        for skin in (base,trial):
            sequences.append(np.array([probe(skin['vertices'],skin['triangles'],skin['weights'],skin['names'],skin['parents'],skin['restAnchors'],skin['inverseBind'],target,skin['regions'],angle,(1,0,0))['moved'] for angle in (0,15,30,15,0,-15,-30,-15,0)]))
        data[target]=sequences
    # Both views share a union framing across all original and candidate probes.
    points=np.concatenate([v.reshape(-1,3) for seq in data.values() for v in seq])
    def framed(right,down,forward):
        result=dict(camera)
        x,y,z=points@right,points@down,points@forward
        scale=224/(max(np.ptp(x),np.ptp(y))*1.12)
        result.update(right=right.tolist(),down=down.tolist(),forward=forward.tolist(),scale=float(scale),
            offset=[float(112-(x.min()+x.max())*.5*scale),float(112-(y.min()+y.max())*.5*scale)],
            depth_center=float((z.min()+z.max())*.5),depth_span=float(np.ptp(z)*.56),resolution=224)
        return result
    right=np.array(camera['right']);down=np.array(camera['down']);forward=np.array(camera['forward'])
    cameras=[framed(right,down,forward),framed(forward,down,-right)]
    with cascade_batch_lock(ROOT):
        renderers=[SkinImageRenderer(base['triangles'],base['uvs'],base['albedo'],c,224) for c in cameras]
        for target,seqs in data.items():
            columns=[renderer.render(vertices)[0] for renderer in renderers for vertices in seqs]
            path=output/(target.split(':')[-1]+'_comparison.gif')
            comparison(path,columns,['Original','Topology weights','Original off-axis','Topology off-axis'],target+' +/-30 X; unchanged rig and surface')
            print(str(path),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--camera',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.original,a.candidate,a.camera,a.output)
