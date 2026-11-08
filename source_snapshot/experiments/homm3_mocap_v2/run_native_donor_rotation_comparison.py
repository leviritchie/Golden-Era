"""Diagnostic learned local rotations versus position-derived native Eagle replay."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from donor_eagle import (load_donor_package, bind_world_matrices,
    inverse_bind_matrices, quat_wxyz_to_matrix, skin_dense)
from eagle_preview import _mesh
from mesh_preview import fk_world_matrices
from native_donor_coordinates import apply_pose_to_native
from native_donor_position_replay import replay_native_donor
from native_donor_rotation_replay import replay_native_rotations
from pin import sha256_file
from preview_eagle_reference_comparison import reference_conversion
from run_eagle_reference_capture_comparison import verify_source_identity, CLIPS
from run_native_donor_capture_comparison import (validate_capture, frozen_camera,
    labeled, grid, write_preview, SIZE)


def run(corpus_paths, output):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError('output must be absent')
    donor = load_donor_package()
    package = donor['package']
    parents, offsets = package['parents'], package['offsets']
    vertices, weights = donor['obj']['vertices'], donor['weights']
    bind = bind_world_matrices(offsets, parents)
    inverse = inverse_bind_matrices(bind)
    skin = dict(vertices=vertices, weights=weights, inverse_bind=inverse)
    conversion = reference_conversion(package)

    # Ground truth must reproduce full orientations and skinned vertices, not
    # merely joint sites. No position-based correction is permitted in this path.
    animation = package['anim']
    known_local = quat_wxyz_to_matrix(np.asarray(animation.rotations))
    roots = np.asarray(animation.positions)[:, 0]
    known_world = np.array([fk_world_matrices(local_rotation=r,
        local_translation=offsets, parents=parents, root_world=p)
        for r, p in zip(known_local, roots)])
    known_mesh = np.array([skin_dense(vertices, weights, w, inverse) for w in known_world])
    control = replay_native_rotations(package['poseRot6d'], offsets, parents, roots, **skin)
    errors = dict(localMatrixMax=float(np.max(np.abs(control['localRotation']-known_local))),
        worldMatrixMax=float(np.max(np.abs(control['jointWorld']-known_world))),
        vertexMax=float(np.linalg.norm(control['meshes']-known_mesh, axis=-1).max()),
        frameCount=len(known_world))
    if max(errors[k] for k in ('localMatrixMax','worldMatrixMax','vertexMax')) > 1e-5:
        raise ValueError(f'known native rotation/skin control failed: {errors}')

    cases = {}
    inputs = {}
    source_checks = {}
    for corpus_path in corpus_paths:
        inputs[str(corpus_path.resolve())] = sha256_file(corpus_path)
        corpus = json.loads(corpus_path.read_text())
        if corpus['package']['refSeq'] != package['refSeq']:
            raise ValueError('reference package differs from donor')
        rows = {r['key']: r for r in corpus['captures']}
        if len(rows) != len(corpus['captures']) or not set(CLIPS).issubset(rows):
            raise ValueError('missing or duplicate comparison clips')
        for key in CLIPS:
            row = rows[key]
            source_checks[corpus['unit']+':'+key] = verify_source_identity(corpus,row)
            path = Path(row['capture'])
            inputs[str(path.resolve())] = sha256_file(path)
            if inputs[str(path.resolve())] != row['captureSha256']:
                raise ValueError('raw capture hash drift')
            with np.load(path, allow_pickle=False) as raw:
                captured = validate_capture(raw, row, package)
                if not np.array_equal(raw['ref_image_embed'], package['refImageEmbed']):
                    raise ValueError('capture reference embedding differs from donor')
                if raw['pred_rot6d'].shape[:2] != raw['pred_position'].shape[:2]:
                    raise ValueError('position and rotation frame/joint counts differ')
                rotation = replay_native_rotations(raw['pred_rot6d'][row['sourceIndices']],
                    offsets, parents, bind[0,:3,3], **skin)
                positions = apply_pose_to_native(captured, conversion, bind[0,:3,3])
            position = replay_native_donor(captured_positions=positions,
                donor_offsets=offsets, parents=parents, names=package['jointNames'], **skin)
            case_key = (corpus['unit'],key)
            if case_key in cases:
                raise ValueError('duplicate unit/clip case')
            cases[case_key] = (row, positions, position, rotation)
    if {k[0] for k in cases} != {'h3_thunderbird','h3_shahrokh'} or len(cases) != 6:
        raise ValueError('requires both birds and three clips each')

    camera = frozen_camera([a for _,raw,pos,rot in cases.values()
        for a in (raw,pos['meshes'],rot['meshes'])])
    control_camera = frozen_camera([known_mesh,control['meshes']])
    obj = donor['obj']; corners = obj['faces'].reshape(-1)
    triangles = np.arange(len(corners)).reshape(-1,3)
    uvs = obj['uvs'][obj['faceUvs'].reshape(-1)]
    with Image.open(donor['texturePath']) as image:
        texture = np.asarray(image.convert('RGB'))
    def render(mesh, view, selected_camera):
        return _mesh(selected_camera,view,mesh[corners],triangles,uvs,texture)

    output.mkdir(parents=True)
    control_frames = []
    for i in range(len(known_world)):
        control_frames.append(grid([labeled(render(mesh[i],view,control_camera),label+' / '+view)
            for view in ('front','side')
            for mesh,label in ((known_mesh,'BVH ground truth'),(control['meshes'],'stored 6D control'))],2))
    write_preview(output/'known_landing',control_frames)
    result = dict(accepted=False, proof='diagnostic native donor replay only',
        decoder='model_runner.rotations_from_6d; vendor transforms3d first-two-rows; native local FK',
        conventionNote='Do not substitute vendor rot6d_to_fk_positions: its column convention differs from stored training targets.',
        knownControl=errors, inputHashes=inputs, sourceIdentityChecks=source_checks,
        packageHashes=package['fileSha256'], donorHashes=donor['fileSha256'],
        camera=camera, controlCamera=control_camera, positionConversion=conversion,
        cameraNote='DEF camera independent; no pixel alignment claim',
        implementationHashes={name:sha256_file(Path(__file__).parent/name) for name in
            ('run_native_donor_rotation_comparison.py','native_donor_rotation_replay.py',
             'model_runner.py','native_donor_position_replay.py','native_donor_coordinates.py',
             'preview_eagle_reference_comparison.py','run_eagle_reference_capture_comparison.py',
             'run_native_donor_capture_comparison.py','direction_retarget.py','donor_eagle.py',
             'mesh_preview.py','eagle_preview.py','shared_camera.py')},cases={})
    for (unit,key),(row,raw,position,rotation) in cases.items():
        directory = output/unit; directory.mkdir(exist_ok=True)
        sprites = []
        for path in map(Path,row['frames']):
            inputs[str(path.resolve())] = sha256_file(path)
            with Image.open(path) as image:
                sprites.append(image.convert('RGBA'))
        scale = .9*min(SIZE/max(s.width for s in sprites),SIZE/max(s.height for s in sprites))
        frames = []
        for i,sprite in enumerate(sprites):
            source = Image.new('RGB',(SIZE,SIZE),(245,245,247))
            resized = sprite.resize((round(sprite.width*scale),round(sprite.height*scale)),Image.Resampling.NEAREST)
            source.paste(resized,((SIZE-resized.width)//2,(SIZE-resized.height)//2),resized)
            panels = []
            for view in ('front','side'):
                panels.append(labeled(source,'DEF / independent camera'))
                for candidate,label in ((position,'Position-derived'),(rotation,'Learned rotations')):
                    panels.append(labeled(render(candidate['meshes'][i],view,camera),label+' / '+view))
            frames.append(grid(panels,3))
        write_preview(directory/key,frames)
        np.savez_compressed(directory/(key+'.npz'),raw_positions=raw,
            position_world=position['jointWorld'],rotation_world=rotation['jointWorld'])
        result['cases'][unit+':'+key] = dict(frameCount=len(frames),
            rotationJointDifferenceFromRawMean=float(np.linalg.norm(rotation['positions']-raw,axis=-1).mean()),
            rotationJointDifferenceFromRawMax=float(np.linalg.norm(rotation['positions']-raw,axis=-1).max()),
            positionEndpointMax=max(position['endpointResidualMax']))
    result['elapsedSeconds'] = time.perf_counter()-started
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.corpus,args.output.resolve())
    print(json.dumps(dict(control=result['knownControl'],cases=result['cases'],elapsedSeconds=result['elapsedSeconds']),indent=2))
