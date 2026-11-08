"""Explicit authored branch correction on a copy of fixed captured FK motion."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from pin import sha256_file
from screen_landmark_ik import solve


def project(points, camera):
    return points @ np.array([camera['right'], camera['down']]).T * camera['scale'] + camera['offset']


def run(skin_path, corpus_path, camera_path, recipe_path, output):
    if output.exists():
        raise FileExistsError(output)
    recipe = json.loads(recipe_path.read_text())
    corpus = json.loads(corpus_path.read_text())
    camera = json.loads(camera_path.read_text())
    if sha256_file(skin_path) != recipe['sourceSkinSha256']:
        raise ValueError('landmark attachment skin changed')
    row = next(r for r in corpus['captures'] if r['key'] == recipe['clip'])
    hashes = [sha256_file(Path(p)) for p in row['frames']]
    if hashes != recipe['sourceFrameSha256'] or len(hashes) != len(recipe['frames']):
        raise ValueError('authored source frame content or ordering changed')
    for path in row['frames']:
        with Image.open(path) as im:
            if list(im.size) != recipe['coordinateCanvas']:
                raise ValueError('authored source canvas changed')
    if sha256_file(Path(row['capture'])) != recipe['captureSha256'] or row['captureSha256'] != recipe['captureSha256']:
        raise ValueError('authored capture changed')
    with np.load(skin_path, allow_pickle=False) as z:
        skin = {k:z[k].copy() for k in z.files}
    with np.load(row['capture'], allow_pickle=False) as z:
        raw = {k:z[k].copy() for k in z.files}
    names = list(skin['names'].astype(str))
    if list(raw['joint_names'].astype(str)) != names or not np.array_equal(raw['parents'], skin['parents']):
        raise ValueError('capture and skin graph differ')
    indices = np.asarray(row['sourceIndices'], dtype=int)
    if len(indices) != len(recipe['frames']) or np.any(np.diff(indices) != 1):
        raise ValueError('authored frame inventory must match contiguous capture selection')
    sites = {}
    for key, spec in recipe['sites'].items():
        joint = names.index(spec['joint'])
        if 'meshVertex' in spec:
            vertex = int(spec['meshVertex'])
            if skin['weights'][vertex,joint] != 1 or np.count_nonzero(skin['weights'][vertex]) != 1:
                raise ValueError('attachment site is not rigid to its declared joint')
            point = (skin['inverseBind'][joint] @ np.r_[skin['vertices'][vertex],1])[:3]
        else:
            point = np.asarray(spec['localPoint'],dtype=float)
        sites[key] = {'joint':joint, 'localPoint':point.tolist()}
    world = raw['joint_world'][indices]
    baseline_points = np.stack([(world[:,s['joint']] @ np.r_[s['localPoint'],1])[:,:3] for s in sites.values()],axis=1)
    pixels = project(baseline_points,camera)
    anchor_pixels = project(world[:,names.index(recipe['anchorJoint']),:3,3],camera)
    authored = np.array([[f[k] for k in sites] for f in recipe['frames']],dtype=float)
    hip = np.array([f['hip'] for f in recipe['frames']],dtype=float)
    # One actor-relative calibration preserves the existing mesh proportions.
    # Absolute source agreement remains a separate downstream gate.
    head = list(sites).index('head'); grip = list(sites).index('grip'); tip = list(sites).index('tip')
    scale = np.linalg.norm(pixels[0,head]-anchor_pixels[0]) / np.linalg.norm(authored[0,head]-hip[0])
    relative = authored-hip[:,None]
    targets = anchor_pixels[:,None] + (pixels[0]-anchor_pixels[0])[None] + scale*(relative-relative[0])
    direction = authored[:,tip]-authored[:,grip]
    direction /= np.linalg.norm(direction,axis=1,keepdims=True)
    blade_length = np.linalg.norm(pixels[0,tip]-pixels[0,grip])
    targets[:,tip] = targets[:,grip] + direction*blade_length
    active = [names.index(n) for n in recipe['activeJoints']]
    confidence = np.tile([.7,1.,1.],(len(indices),1))
    # Source frame zero and all idle context remain bitwise unchanged.
    local, solved_world, report = solve(raw['local_rotation'][indices[1:]],raw['offsets'],raw['parents'],
        raw['joint_world'][indices[1:],0,:3,3],camera,active,sites,targets[1:],confidence[1:],
        prior_weight=.02,temporal_weight=.015,max_nfev=100)
    candidate = {k:v.copy() for k,v in raw.items()}
    candidate['local_rotation'][indices[1:]] = local
    candidate['joint_world'][indices[1:]] = solved_world
    candidate['pred_position'] = candidate['joint_world'][:,:,:3,3].copy()
    inactive = [i for i in range(len(names)) if i not in active]
    report['inactiveLocalMatrixMax'] = float(np.abs(candidate['local_rotation'][:,inactive]-raw['local_rotation'][:,inactive]).max())
    mount = [i for i,n in enumerate(names) if n.startswith('mount:')]
    report['mountWorldMatrixMax'] = float(np.abs(candidate['joint_world'][:,mount]-raw['joint_world'][:,mount]).max())
    untouched = np.setdiff1d(np.arange(len(raw['local_rotation'])),indices[1:])
    report['contextAndFirstFrameWorldMax'] = float(np.abs(candidate['joint_world'][untouched]-raw['joint_world'][untouched]).max())
    report['sourcePixelsToPreviewPixels'] = float(scale)
    report['proof'] = 'generated_candidate_not_absolute_source_fit'
    report['sourceSkinSha256'] = sha256_file(skin_path)
    report['sourceCorpusSha256'] = sha256_file(corpus_path)
    report['recipeSha256'] = sha256_file(recipe_path)
    if report['mountWorldMatrixMax'] or report['inactiveLocalMatrixMax'] or report['contextAndFirstFrameWorldMax'] or not report['fixedOffsetParity']:
        raise ValueError('correction violated fixed motion ownership or fixed lengths')
    output.mkdir(parents=True)
    dest = output/'corrected_capture.npz'
    np.savez(dest,**candidate)
    # Preserve all other clips and the explicit source-frame correspondence.
    new_rows = [dict(r) for r in corpus['captures']]
    corrected_row = next(r for r in new_rows if r['key']==recipe['clip'])
    corrected_row.update(capture=str(dest.resolve()),captureSha256=sha256_file(dest))
    corpus.update(captures=new_rows,correctionRecipe=str(recipe_path.resolve()),correctionRecipeSha256=sha256_file(recipe_path),
        compositePolicy='original composed FK with explicit authored upper-body rotation correction')
    (output/'corpus.json').write_text(json.dumps(corpus,indent=2))
    (output/'report.json').write_text(json.dumps(report,indent=2))
    (output/'targets.json').write_text(json.dumps({'sites':sites,'targets':targets.tolist(),'sourceFrames':row['frames'],
        'sourceFrameSha256':[sha256_file(Path(p)) for p in row['frames']]},indent=2))
    overlay_frames=[]
    for i,path in enumerate(row['frames']):
        with Image.open(path) as im:
            if list(im.size) != recipe['coordinateCanvas']:
                raise ValueError('authored source canvas changed')
            im=im.convert('RGB').resize((350,290))
        draw=ImageDraw.Draw(im)
        for key,color in [('hip','cyan'),('head','lime'),('grip','yellow'),('tip','red')]:
            x,y=np.array(recipe['frames'][i][key])/3
            draw.ellipse((x-3,y-3,x+3,y+3),fill=color)
        draw.line([tuple(np.array(recipe['frames'][i][k])/3) for k in ('hip','head')],fill='lime',width=2)
        draw.line([tuple(np.array(recipe['frames'][i][k])/3) for k in ('grip','tip')],fill='yellow',width=2)
        overlay_frames.append(im)
    overlay_frames[0].save(output/'authored_source.gif',save_all=True,append_images=overlay_frames[1:],duration=180,loop=0)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('skin','corpus','camera','recipe','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args()
    run(a.skin,a.corpus,a.camera,a.recipe,a.output)
