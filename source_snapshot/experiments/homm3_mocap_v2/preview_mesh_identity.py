"""Read-only textured identity sheet for explicitly selected mesh files."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from PIL import Image, ImageDraw
from glb_skeleton import load_bind_skeleton
from pin import sha256_file
from run_skin_weight_pilot import cascade_batch_lock, ROOT
from skin_image_objective import SkinImageRenderer


def run(paths,output):
    if output.exists():
        raise FileExistsError(output)
    sheet=Image.new('RGB',(448*len(paths),480),(35,35,35))
    draw=ImageDraw.Draw(sheet); reports=[]
    right=np.array([-.42261826174069933,0,.90630778703665]);down=np.array([0,-1,0]);forward=np.cross(right,down)
    with cascade_batch_lock(ROOT):
        for i,path in enumerate(paths):
            bind=load_bind_skeleton(path);v=bind.vertices
            xy=<email>([right,down]).T;depth=v@forward
            scale=390/np.ptp(xy,axis=0).max();offset=np.array([224,224])-(xy.min(0)+xy.max(0))*.5*scale
            camera=dict(right=right.tolist(),down=down.tolist(),forward=forward.tolist(),scale=float(scale),offset=offset.tolist(),depth_center=float((depth.min()+depth.max())*.5),depth_span=float(np.ptp(depth)*.6))
            renderer=SkinImageRenderer(bind.triangles,bind.uvs,bind.albedo,camera,448)
            rgb,alpha=renderer.render(torch.as_tensor(v[None],device='cuda',dtype=torch.float32))
            pixels=((rgb[0]+(1-alpha[0])*.137).clamp(0,1).detach().cpu().numpy()*255).astype('uint8')
            sheet.paste(Image.fromarray(pixels),(i*448,32));draw.text((i*448+8,8),path.name,fill='white')
            reports.append(dict(path=str(path.resolve()),sha256=sha256_file(path),jointCount=len(bind.names),vertices=len(v)))
    output.parent.mkdir(parents=True,exist_ok=True);sheet.save(output)
    output.with_suffix('.json').write_text(json.dumps(reports,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--meshes',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.meshes,a.output)
