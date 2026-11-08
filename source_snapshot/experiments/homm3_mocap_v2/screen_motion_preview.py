"""Render old and explicitly corrected motion on the same fixed skin."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from corpus_motion import load_motion
from pin import sha256_file
from run_skin_mesh_pilot import comparison, deform
from run_skin_weight_pilot import cascade_batch_lock, ROOT, source_images
from skin_image_objective import SkinImageRenderer


def run(skin_path, original_path, corrected_path, camera_path, clip, output):
    if output.exists():
        raise FileExistsError(output)
    with np.load(skin_path,allow_pickle=False) as z:
        skin={k:z[k].copy() for k in z.files}
    skin['names']=list(skin['names'].astype(str))
    camera=json.loads(camera_path.read_text())
    motions=[]; rows=[]
    for path in (original_path,corrected_path):
        corpus=json.loads(path.read_text())
        row=next(r for r in corpus['captures'] if r['key']==clip)
        if sha256_file(Path(row['capture'])) != row['captureSha256']:
            raise ValueError('capture pin changed')
        with np.load(row['capture']) as raw:
            motions.append(load_motion(raw,row,corpus,skin,raw['pred_position'][0],()))
        rows.append(row)
    if rows[0]['frames'] != rows[1]['frames'] or rows[0]['sourceIndices'] != rows[1]['sourceIndices']:
        raise ValueError('source timelines differ')
    with cascade_batch_lock(ROOT):
        renderer=SkinImageRenderer(skin['triangles'],skin['uvs'],skin['albedo'],camera,224)
        vertices=torch.as_tensor(skin['vertices'],device='cuda',dtype=torch.float32)
        weights=torch.as_tensor(skin['weights'],device='cuda',dtype=torch.float32)
        columns=[source_images([Path(p) for p in rows[0]['frames']],camera['sourceCrop'],224)[0]]
        for motion in motions:
            transforms=torch.as_tensor((motion['jointWorld']@skin['inverseBind'][None])[:,:,:3],device='cuda',dtype=torch.float32)
            columns.append(renderer.render(deform(transforms,weights,vertices))[0])
        comparison(output,columns,['Source','Previous motion','Authored strike correction'],clip+'; same skin, fixed mount')
    output.with_suffix('.json').write_text(json.dumps({'skinSha256':sha256_file(skin_path),
        'originalCorpusSha256':sha256_file(original_path),'correctedCorpusSha256':sha256_file(corrected_path),
        'cameraSha256':sha256_file(camera_path),'clip':clip},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('skin','original','corrected','camera','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--clip',required=True)
    a=p.parse_args();run(a.skin,a.original,a.corrected,a.camera,a.clip,a.output)
