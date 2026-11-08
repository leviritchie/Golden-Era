"""Render explicit named source regions and joint sites for anatomical review."""
import argparse
import importlib
from pathlib import Path
import numpy as np
import torch
from PIL import Image, ImageDraw
from glb_skeleton import load_bind_skeleton
from target_asset import dense_weights
from run_skin_weight_pilot import cascade_batch_lock, ROOT
from skin_image_objective import SkinImageRenderer

COLORS=np.array([(220,70,70),(240,160,50),(230,210,60),(75,190,90),(40,190,190),(75,125,240),(170,100,230),(240,110,180),(150,210,65),(70,170,210),(210,160,210),(170,120,75),(180,190,210),(230,230,230)],dtype='uint8')


def run(mesh,module,output):
    groups=importlib.import_module(module).SOURCE_GROUPS
    bind=load_bind_skeleton(mesh)
    mapping={n:i for i,(_,names) in enumerate(groups.items()) for n in names}
    if set(mapping)!=set(bind.names) or sum(map(len,groups.values()))!=len(bind.names):
        raise ValueError('source region coverage must be exact and unique')
    label=np.array([mapping[bind.names[i]] for i in dense_weights(bind).argmax(1)])
    uv=np.stack([(label+.5)/len(groups),np.full(len(label),.5)],axis=1)
    texture=COLORS[:len(groups)][None]
    sheet=Image.new('RGB',(1200,1040),(28,28,28));draw=ImageDraw.Draw(sheet)
    with cascade_batch_lock(ROOT):
        for view,yaw in enumerate((115,25,-65,205)):
            a=np.deg2rad(yaw);right=np.array([np.cos(a),0,np.sin(a)]);down=np.array([0,-1,0]);forward=np.cross(right,down)
            xy=<email>([right,down]).T;depth=bind.vertices@forward
            scale=405/np.ptp(xy,axis=0).max();offset=np.array([240,240])-(xy.min(0)+xy.max(0))*.5*scale
            camera=dict(right=right,down=down,forward=forward,scale=scale,offset=offset,depth_center=(depth.min()+depth.max())*.5,depth_span=np.ptp(depth)*.6)
            renderer=SkinImageRenderer(bind.triangles,uv,texture,camera,480)
            rgb,alpha=renderer.render(torch.as_tensor(bind.vertices[None],device='cuda',dtype=torch.float32))
            pixels=((rgb[0]+(1-alpha[0])*.11).clamp(0,1).detach().cpu().numpy()*255).astype('uint8')
            x=(view%2)*600;y=(view//2)*500;sheet.paste(Image.fromarray(pixels),(x,y+20));draw.text((x+10,y+3),f'yaw {yaw}',fill='white')
            sites=<email>([right,down]).T*scale+offset
            for j,(px,py) in enumerate(sites):
                draw.ellipse((x+px-2,y+py+18,x+px+2,y+py+22),fill='white')
                draw.text((x+px+2,y+py+20),bind.names[j].removeprefix('Bone_'),fill='white')
            for k,name in enumerate(groups):
                if view==0:
                    draw.rectangle((485,k*24+30,497,k*24+42),fill=tuple(COLORS[k]));draw.text((499,k*24+30),name,fill='white')
    output.parent.mkdir(parents=True,exist_ok=True);sheet.save(output)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mesh',type=Path,required=True);p.add_argument('--module',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.mesh,a.module,a.output)
