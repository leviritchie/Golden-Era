"""Compare reference-conditioned captures in one native donor coordinate frame."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from donor_eagle import (load_donor_package, bind_world_matrices,
    inverse_bind_matrices, quat_wxyz_to_matrix)
from eagle_preview import _mesh
from mesh_preview import fk_world_matrices
from native_donor_coordinates import fit_normalized_pose_to_native, apply_pose_to_native
from native_donor_position_replay import replay_native_donor
from pin import sha256_file
from run_eagle_reference_capture_comparison import CLIPS, REFS, verify_source_identity
from run_native_donor_capture_comparison import (validate_capture, frozen_camera,
    labeled, grid, write_preview, SIZE)
from vendor_reference import load_complete_package


def reference_conversion(package):
    stored=np.asarray(package['posePosition'],dtype=np.float64)
    normalized=(stored-stored[:,:1])/package['globalScale']
    animation=package['anim']
    native_positions=np.array([fk_world_matrices(local_rotation=r,
        local_translation=package['offsets'],parents=package['parents'],root_world=p[0])[:,:3,3]
        for r,p in zip(quat_wxyz_to_matrix(np.asarray(animation.rotations)),animation.positions)])
    # Reference yaw is an actor pose, not a coordinate-system correction.
    # Pair each stored sequence with its OWN BVH; never rotate y90 predictions
    # merely to align that reference performance with the y15 performance.
    return fit_normalized_pose_to_native(normalized,native_positions)


def run(capture_root, output):
    started=time.perf_counter()
    if output.exists(): raise ValueError('output must be absent')
    capture_report=json.loads((capture_root/'report.json').read_text())
    donor=load_donor_package()
    native=donor['package']
    parents,offsets=native['parents'],native['offsets']
    bind=bind_world_matrices(offsets,parents)
    inverse=inverse_bind_matrices(bind)
    packages={ref:load_complete_package('zoo',ref) for ref in REFS}
    conversions={ref:reference_conversion(package) for ref,package in packages.items()}
    cases={}
    source_checks={}
    inputs={str((capture_root/'report.json').resolve()):sha256_file(capture_root/'report.json')}
    for corpus_path in map(Path,capture_report['outputs']):
        inputs[str(corpus_path.resolve())]=sha256_file(corpus_path)
        corpus=json.loads(corpus_path.read_text())
        old_path=Path(corpus['provenance']['oldCorpus'])
        if sha256_file(old_path)!=corpus['provenance']['oldCorpusSha256']:
            raise ValueError('original corpus hash drift')
        old_corpus=json.loads(old_path.read_text())
        old_rows={row['key']:row for row in old_corpus['captures']}
        ref=corpus['package']['refSeq']; package=packages[ref]
        if package['jointNames']!=native['jointNames'] or not np.array_equal(package['parents'],parents):
            raise ValueError('source reference and donor hierarchy differ')
        if not np.array_equal(package['offsets'][1:],offsets[1:]):
            raise ValueError('source reference and donor native bind edges differ')
        for row in corpus['captures']:
            old_row=old_rows[row['key']]
            if row['frames']!=old_row['frames'] or row['sourceIndices']!=old_row['sourceIndices']:
                raise ValueError('fresh capture differs from original authored source order')
            source_checks[corpus['unit']+':'+row['key']]=verify_source_identity(old_corpus,old_row)
            path=Path(row['capture'])
            inputs[str(path.resolve())]=sha256_file(path)
            if inputs[str(path.resolve())]!=row['captureSha256']: raise ValueError('capture hash drift')
            with np.load(path,allow_pickle=False) as raw:
                with np.load(old_row['capture'],allow_pickle=False) as original:
                    if not np.array_equal(raw['image_embed'],original['image_embed']):
                        raise ValueError('fresh and original source embeddings differ')
                    if ref==REFS[0] and not np.array_equal(raw['pred_position'],original['pred_position']):
                        raise ValueError('baseline prediction parity failed')
                values=validate_capture(raw,row,package)
                positions=apply_pose_to_native(values,conversions[ref],bind[0,:3,3])
            replay=replay_native_donor(captured_positions=positions,donor_offsets=offsets,
                parents=parents,names=native['jointNames'],vertices=donor['obj']['vertices'],
                weights=donor['weights'],inverse_bind=inverse)
            key=(corpus['unit'],row['key'])
            group=cases.setdefault(key,{})
            if ref in group: raise ValueError('duplicate reference case')
            group[ref]=(row,positions,replay)
    if len(cases)!=6 or any(set(group)!=set(REFS) for group in cases.values()):
        raise ValueError('requires both units, three clips, and all three reference packages')
    for group in cases.values():
        baseline=group[REFS[0]][0]
        for row,_,_ in group.values():
            if row['frames']!=baseline['frames'] or row['sourceIndices']!=baseline['sourceIndices']:
                raise ValueError('reference cases compare different authored frames')
    camera=frozen_camera([a for group in cases.values() for _,positions,replay in group.values()
        for a in (positions,replay['meshes'])])
    obj=donor['obj']; corners=obj['faces'].reshape(-1)
    triangles=np.arange(len(corners)).reshape(-1,3)
    uvs=obj['uvs'][obj['faceUvs'].reshape(-1)]
    with Image.open(donor['texturePath']) as image: texture=np.asarray(image.convert('RGB'))
    output.mkdir(parents=True)
    result=dict(accepted=False,proof='generated native donor comparison only',camera=camera,
        sourceIdentityChecks=source_checks,
        cameraNote='DEF camera is independent; no pixel-alignment claim',
        conversions=conversions,donorFileHashes=donor['fileSha256'],
        sourcePackageHashes={ref:p['fileSha256'] for ref,p in packages.items()},inputHashes=inputs,
        implementationHashes={name:sha256_file(Path(__file__).parent/name) for name in
            ('preview_eagle_reference_comparison.py','run_eagle_reference_capture_comparison.py','native_donor_coordinates.py',
             'native_donor_position_replay.py','run_native_donor_capture_comparison.py',
             'direction_retarget.py','donor_eagle.py','eagle_preview.py','mesh_preview.py','shared_camera.py')},cases={})
    for (unit,key),group in cases.items():
        directory=output/unit; directory.mkdir(exist_ok=True)
        source_paths=group[REFS[0]][0]['frames']
        sprites=[]
        for path in map(Path,source_paths):
            inputs[str(path.resolve())]=sha256_file(path)
            with Image.open(path) as image: sprites.append(image.convert('RGBA'))
        scale=.9*min(SIZE/max(s.width for s in sprites),SIZE/max(s.height for s in sprites))
        frames=[]
        for i,sprite in enumerate(sprites):
            source=Image.new('RGB',(SIZE,SIZE),(245,245,247))
            resized=sprite.resize((round(sprite.width*scale),round(sprite.height*scale)),Image.Resampling.NEAREST)
            source.paste(resized,((SIZE-resized.width)//2,(SIZE-resized.height)//2),resized)
            panels=[]
            for view in ('front','side'):
                panels.append(labeled(source,'DEF / independent camera'))
                for ref in REFS:
                    mesh=group[ref][2]['meshes'][i]
                    panel=_mesh(camera,view,mesh[corners],triangles,uvs,texture)
                    panels.append(labeled(panel,ref.rsplit('/',1)[1]+' reference / '+view))
            frames.append(grid(panels,4))
        write_preview(directory/key,frames)
        metrics={}
        arrays={}
        for ref,(_,positions,replay) in group.items():
            yaw=ref.rsplit('/',1)[1]
            metrics[yaw]=dict(endpointMax=max(replay['endpointResidualMax']),
                lengthMax=max(replay['rawLengthErrorMax']),directionMaxDeg=max(replay['directionErrorMaxDeg']),
                meanJointDifferenceFromY15=float(np.linalg.norm(positions-group[REFS[0]][1],axis=-1).mean()))
            arrays[yaw+'_positions']=positions
            arrays[yaw+'_joint_world']=replay['jointWorld']
        np.savez_compressed(directory/(key+'.npz'),**arrays)
        result['cases'][unit+':'+key]=dict(frameCount=len(frames),referenceMetrics=metrics)
    result['elapsedSeconds']=time.perf_counter()-started
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--capture-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run(args.capture_root,args.output)
    print(json.dumps({'elapsedSeconds':report['elapsedSeconds'],'cases':len(report['cases'])}))
