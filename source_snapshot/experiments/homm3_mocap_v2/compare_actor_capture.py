"""Fixed-scale, fixed-view raw skeleton controls; no mesh or pose optimization."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from pin import sha256_file

def panel(points,parents,names,plane,bounds,label):
    p=points[:,plane]; low,high=bounds;scale=240/max(high-low);xy=(p-(low+high)/2)*scale+140;xy[:,1]=280-xy[:,1]
    image=Image.new('RGB',(280,304),(238,238,238));d=ImageDraw.Draw(image)
    for j,parent in enumerate(parents):
        if parent<0:continue
        color=(190,65,45) if 'Right' in names[j] or '_R_' in names[j] else (35,135,85)
        d.line([tuple(xy[parent]),tuple(xy[j])],fill=color,width=3)
    for j,(x,y) in enumerate(xy):
        d.ellipse((x-2,y-2,x+2,y+2),fill=(20,40,40))
        if names[j].endswith('RightHand'):d.text((x+3,y),'hand',fill=(175,30,30))
    d.rectangle((0,280,280,304),fill=(238,238,238));d.text((4,286),label,fill=(10,10,10));return image

def compare(root,output):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    report={}
    for actor in ('mount','rider'):
        corpora={c:json.loads((root/c/actor/'corpus.json').read_text()) for c in ('control','isolated')}
        rows={c:{r['key']:r for r in corpus['captures']} for c,corpus in corpora.items()}
        captures={}
        for condition in rows:
            for key,entry in rows[condition].items():
                path=Path(entry['capture'])
                if sha256_file(path)!=entry['captureSha256']:raise ValueError('capture changed')
                with np.load(path) as raw:captures[condition,key]={k:raw[k].copy() for k in ('pred_position','joint_names','parents')}
        allpoints=np.concatenate([r['pred_position'].reshape(-1,3) for r in captures.values()])
        bounds={tuple(plane):(allpoints[:,plane].min(axis=0),allpoints[:,plane].max(axis=0)) for plane in ([0,1],[0,2])}
        for key in rows['control']:
            images=[];entry=rows['control'][key]
            for frame,source in enumerate(entry['frames']):
                row=Image.new('RGB',(1400,326),(35,35,38));d=ImageDraw.Draw(row);d.text((4,4),f'{actor} {key} frame {frame:02d}; fixed views/scales; red = right limbs',fill='white')
                im=Image.open(source).convert('RGBA');im.thumbnail((280,280));bg=Image.new('RGB',(280,304),(238,238,238));bg.paste(im,((280-im.width)//2,(280-im.height)//2),im);ImageDraw.Draw(bg).text((4,286),'Source',fill=(10,10,10));row.paste(bg,(0,22))
                for col,(condition,plane) in enumerate((('control',[0,1]),('isolated',[0,1]),('control',[0,2]),('isolated',[0,2])),1):
                    raw=captures[condition,key];index=rows[condition][key]['sourceIndices'][frame]
                    row.paste(panel(raw['pred_position'][index],raw['parents'],raw['joint_names'],plane,bounds[tuple(plane)],condition+' '+('XY' if plane==[0,1] else 'XZ')),(col*280,22))
                images.append(row)
            path=output/f'{actor}_{key}.gif';images[0].save(path,save_all=True,append_images=images[1:],duration=83,loop=0)
            sheet=Image.new('RGB',(1400,326*len(images)),(35,35,38))
            for i,im in enumerate(images):sheet.paste(im,(0,326*i))
            sheet.save(output/f'{actor}_{key}.png')
            report[actor+'/'+key]={'gif':str(path.resolve()),'frames':len(images)}
    (output/'comparison.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();compare(a.root,a.output)
