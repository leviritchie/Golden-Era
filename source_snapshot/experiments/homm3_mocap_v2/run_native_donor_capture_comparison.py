"""Compare Cartesian captures to native Eagle replay, without target retargeting."""
from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from donor_eagle import (load_donor_package, bind_world_matrices,
    inverse_bind_matrices, quat_wxyz_to_matrix, skin_dense)
from eagle_preview import _mesh, _stick
from mesh_preview import fk_world_matrices
from native_donor_position_replay import replay_native_donor
from paths import SOURCE_FRAME_MS
from pin import sha256_file
from shared_camera import freeze_shared_camera
from position_anchored_donor import replay_position_anchored
from skin_surface_constraints import triangle_principal_stretches, surface_constraint_metrics
from native_donor_coordinates import fit_normalized_pose_to_native, apply_pose_to_native

SIZE = 240


def validate_capture(raw, row, skeleton):
    if list(raw['joint_names'].astype(str)) != skeleton['jointNames']:
        raise ValueError('capture names differ from native donor')
    if not np.array_equal(raw['parents'], skeleton['parents']):
        raise ValueError('capture hierarchy differs from native donor')
    if not np.array_equal(raw['offsets'], skeleton['offsets']):
        raise ValueError('capture offsets differ from native donor')
    indices = np.asarray(row['sourceIndices'])
    positions = np.asarray(raw['pred_position'], dtype=np.float64)
    if (indices.ndim != 1 or indices.dtype.kind not in 'iu' or not len(indices)
            or len(indices) != len(row['frames']) or np.any(indices < 0)
            or np.any(indices >= len(positions)) or len(set(indices)) != len(indices)):
        raise ValueError('invalid authored source indices')
    return positions[indices]


def frozen_camera(arrays):
    values = np.concatenate([np.asarray(a).reshape(-1, 3) for a in arrays])
    # Bounding-box corners prevent mean-density bias from clipping asymmetric poses.
    corners = np.array(list(itertools.product(*zip(values.min(0), values.max(0)))))
    return freeze_shared_camera(corners, width=SIZE, height=SIZE,
        space='native_eagle_capture_space')


def labeled(panel, title):
    result = Image.new('RGB', (SIZE, SIZE + 22), (245, 245, 247))
    result.paste(panel, (0, 22))
    ImageDraw.Draw(result).text((4, 5), title, fill=(15, 15, 20))
    return result


def grid(panels, columns):
    result = Image.new('RGB', (columns * SIZE, ((len(panels)+columns-1)//columns)*(SIZE+22)))
    for i, panel in enumerate(panels):
        result.paste(panel, ((i % columns)*SIZE, (i//columns)*(SIZE+22)))
    return result


def write_preview(path, frames):
    frames[0].save(path.with_suffix('.gif'), save_all=True, append_images=frames[1:],
        duration=SOURCE_FRAME_MS, loop=0, disposal=2)
    indices = sorted(set((0, len(frames)//3, 2*len(frames)//3, len(frames)-1)))
    sheet = Image.new('RGB', (frames[0].width, frames[0].height*len(indices)))
    for row, index in enumerate(indices):
        sheet.paste(frames[index], (0, row*frames[0].height))
    sheet.save(path.with_suffix('.png'))


def run(corpus_paths, output, *, position_anchored=False):
    started = time.perf_counter()
    if output.exists():
        raise ValueError('output already exists; preserve prior evidence')
    donor = load_donor_package()
    skeleton = donor['captureSkeleton']
    parents, offsets = skeleton['parents'], skeleton['offsets']
    vertices, weights = donor['obj']['vertices'], donor['weights']
    bind = bind_world_matrices(offsets, parents)
    inverse = inverse_bind_matrices(bind)
    kwargs = dict(donor_offsets=offsets, parents=parents, names=skeleton['jointNames'],
        vertices=vertices, weights=weights, inverse_bind=inverse)
    anim = donor['package']['anim']
    rotations = quat_wxyz_to_matrix(np.asarray(anim.rotations))
    known_world = np.array([fk_world_matrices(local_rotation=r, local_translation=offsets,
        parents=parents, root_world=p[0]) for r, p in zip(rotations, anim.positions)])
    known_mesh = np.array([skin_dense(vertices, weights, w, inverse) for w in known_world])
    stored = np.asarray(donor['package']['posePosition'],dtype=np.float64)
    normalized = (stored-stored[:,:1,:])/donor['package']['globalScale']
    conversion = fit_normalized_pose_to_native(normalized,known_world[:,:,:3,3])
    known_replay = replay_native_donor(captured_positions=known_world[:, :, :3, 3], **kwargs)
    known_error = np.linalg.norm(known_replay['meshes']-known_mesh, axis=-1)
    if max(known_replay['endpointResidualMax']) > 1e-5:
        raise ValueError('known native motion position control failed')

    cases = []
    inputs = {}
    for path in corpus_paths:
        inputs[str(path.resolve())] = sha256_file(path)
        corpus = json.loads(path.read_text())
        if corpus['package']['refSeq'] != 'Eagle#Eagle-Landing/y15':
            raise ValueError('unexpected source actor package')
        for row in corpus['captures']:
            capture_path = Path(row['capture'])
            digest = sha256_file(capture_path)
            if digest != row['captureSha256']:
                raise ValueError('capture hash differs from corpus')
            inputs[str(capture_path.resolve())] = digest
            with np.load(capture_path, allow_pickle=False) as raw:
                normalized_positions = validate_capture(raw, row, skeleton)
                positions = apply_pose_to_native(normalized_positions,conversion,bind[0,:3,3])
                # Vendor calls these "rest_pose", but BVHReader supplies local offsets.
                expected_vendor = (offsets-offsets[:1])/donor['package']['globalScale']
                if not np.allclose(raw['vendor_offset_a'],expected_vendor,atol=1e-6,rtol=0):
                    raise ValueError('capture normalization metadata differs from vendor package')
            replay = replay_native_donor(captured_positions=positions, **kwargs)
            if position_anchored:
                anchored = replay_position_anchored(joint_world=replay['jointWorld'],
                    raw_positions=positions, parents=parents, donor_offsets=offsets)
                replay['anchored'] = anchored
                replay['anchoredMeshes'] = np.array([skin_dense(vertices,weights,w,inverse)
                    for w in anchored['jointWorld']])
            sprites = []
            for frame in row['frames']:
                frame_path = Path(frame)
                inputs[str(frame_path.resolve())] = sha256_file(frame_path)
                with Image.open(frame_path) as image:
                    sprites.append(image.convert('RGBA'))
            cases.append((corpus['unit'], row, positions, replay, sprites))

    bounds = [known_mesh, known_replay['meshes'], known_world[:,:,:3,3]]
    for _,_,raw,replay,_ in cases:
        bounds.extend((raw,replay['meshes']))
        if position_anchored:
            bounds.append(replay['anchoredMeshes'])
    camera = frozen_camera(bounds)
    # Expand render-only face corners to preserve the OBJ's UV seams exactly.
    obj = donor['obj']
    corner_vertices = np.asarray(obj['faces']).reshape(-1)
    triangles = np.arange(len(corner_vertices)).reshape(-1,3)
    uvs = obj['uvs'][np.asarray(obj['faceUvs']).reshape(-1)]
    with Image.open(donor['texturePath']) as image:
        albedo = np.asarray(image.convert('RGB'))

    def render(mesh, view):
        return _mesh(camera, view, mesh[corner_vertices], triangles, uvs, albedo)

    output.mkdir(parents=True)
    known_frames = []
    for truth, reconstructed in zip(known_mesh, known_replay['meshes']):
        known_frames.append(grid([labeled(render(mesh, view), title+' / '+view)
            for view in ('front','side') for mesh,title in
            ((truth,'BVH rotations'),(reconstructed,'From positions'))],2))
    write_preview(output/'known_landing', known_frames)
    report = dict(proof='generated diagnostic only', accepted=False,
        positionAnchoredComparison=position_anchored,
        networkToNativeCoordinates=conversion,
        cameraPolicy='Fixed shared native views; DEF camera not calibrated', camera=camera,
        donorFileHashes=donor['fileSha256'], inputHashes=inputs,
        implementationHashes={name:sha256_file(Path(__file__).parent/name) for name in
            ('run_native_donor_capture_comparison.py','native_donor_position_replay.py',
             'donor_eagle.py','direction_retarget.py','eagle_preview.py','mesh_preview.py','shared_camera.py',
             'position_anchored_donor.py','native_donor_coordinates.py','skin_surface_constraints.py')},
        knownControl=dict(frames=len(known_mesh), endpointMax=max(known_replay['endpointResidualMax']),
            meshErrorMean=float(known_error.mean()), meshErrorMax=float(known_error.max()),
            note='Position parity does not establish unobserved axial rotation parity'), cases={})
    for unit, row, positions, replay, sprites in cases:
        directory=output/unit
        directory.mkdir(exist_ok=True)
        scale = min(SIZE/max(s.width for s in sprites), SIZE/max(s.height for s in sprites))*.9
        frames = []
        for frame_index,(raw, joints, mesh, sprite) in enumerate(zip(positions,replay['positions'],replay['meshes'],sprites)):
            source=Image.new('RGB',(SIZE,SIZE),(245,245,247))
            resized=sprite.resize((max(1,round(sprite.width*scale)),max(1,round(sprite.height*scale))),Image.Resampling.NEAREST)
            source.paste(resized,((SIZE-resized.width)//2,(SIZE-resized.height)//2),resized)
            panels=[]
            for view in ('front','side'):
                sticks=_stick(camera,view,raw,parents,(20,145,70))
                sticks=_stick(camera,view,joints,parents,(210,35,130),background=sticks)
                panels.extend((labeled(source,'DEF (independent camera)'),
                    labeled(sticks,'Raw green / FK pink: '+view),
                    labeled(render(mesh,view),'Fixed-length donor: '+view)))
                if position_anchored:
                    panels.append(labeled(render(replay['anchoredMeshes'][frame_index],view),
                        'Raw-position donor: '+view))
            frames.append(grid(panels,4 if position_anchored else 3))
        write_preview(directory/row['key'],frames)
        report['cases'][unit+':'+row['key']] = dict(frameCount=len(frames),
            endpointResidualMax=max(replay['endpointResidualMax']),
            rawLengthErrorMax=max(replay['rawLengthErrorMax']),
            directionErrorMaxDeg=max(replay['directionErrorMaxDeg']),
            perFrameEndpoint=replay['endpointResidualMax'],
            perFrameLength=replay['rawLengthErrorMax'],sourceIndices=row['sourceIndices'])
        if position_anchored:
            case = report['cases'][unit+':'+row['key']]
            case['anchoredEndpointResidualMax'] = float(np.max(np.linalg.norm(
                replay['anchored']['jointWorld'][:,:,:3,3]-positions,axis=-1)))
            case['anchoredFkParityMax'] = replay['anchored']['fkParityMax']
            case['surface'] = {}
            for label,meshes in (('fixed',replay['meshes']),('anchored',replay['anchoredMeshes'])):
                case['surface'][label] = surface_constraint_metrics(*triangle_principal_stretches(
                    meshes,vertices,obj['faces']))
    report['elapsedSeconds']=time.perf_counter()-started
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--corpus',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--position-anchored',action='store_true')
    args=parser.parse_args()
    result=run(args.corpus,args.output.resolve(),position_anchored=args.position_anchored)
    print(json.dumps({'elapsedSeconds':result['elapsedSeconds'],'cases':len(result['cases']),
        'knownControl':result['knownControl']}))
