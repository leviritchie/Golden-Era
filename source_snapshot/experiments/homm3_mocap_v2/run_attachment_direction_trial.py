"""Source-authored leaf orientation diagnostic on calibrated, fixed skin motion."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from asset_profiles import get_profile
from corpus_motion import load_motion
from glb_skeleton import load_bind_skeleton
from pin import sha256_file
from run_skin_mesh_pilot import comparison, deform, expand_camera_to_full_canvas
from run_skin_weight_pilot import (_load_frozen_prep, cascade_batch_lock, ROOT,
    source_images, write_skinned_glb, matrices_to_xyzw, verify_calibrated_export,
    SOURCE_FRAME_MS)
from screen_attachment_direction import correct
from skin_image_objective import SkinImageRenderer
from skin_surface_constraints import SurfaceConstraints
from ownership_candidate_validation import validate_invariants


def run(recipe_path, corpus_path, registration, output, candidate_skin=None, candidate_sha256=None):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    recipe = json.loads(recipe_path.read_text())
    if recipe['schema'] != 1 or recipe['method'] != 'agent_eye_authored_attachment_axis':
        raise ValueError('unsupported authored attachment recipe')
    corpus = json.loads(corpus_path.read_text())
    if sha256_file(corpus_path) != recipe['corpusSha256'] or corpus['unit'] != recipe['asset']:
        raise ValueError('recipe corpus identity changed')
    profile = get_profile(recipe['asset'])
    freeze, skin = _load_frozen_prep(recipe['asset'])
    candidate_weights = skin['weights']
    if (candidate_skin is None) != (candidate_sha256 is None):
        raise ValueError('candidate skin and expected hash must be supplied together')
    if candidate_skin is not None:
        if sha256_file(candidate_skin) != candidate_sha256:
            raise ValueError('candidate skin hash changed')
        with np.load(candidate_skin,allow_pickle=False) as z:
            candidate={k:z[k].copy() for k in z.files}
        validate_invariants(skin,candidate,weapon_regions=(recipe['region'],))
        candidate_weights=candidate['weights']
    previous = json.loads((registration/'pilot_report.json').read_text())
    if previous['asset'] != recipe['asset'] or previous['kind'] != 'idle_registration_only':
        raise ValueError('wrong registration identity or kind')
    skin_hash = sha256_file(Path(freeze['researchSkin']))
    if skin_hash != recipe['skinSha256'] or skin_hash != previous['inputs']['researchSkin']:
        raise ValueError('recipe or registration skin changed')
    calibration_path = Path(previous['inputs']['calibrationPath'])
    if sha256_file(calibration_path) != previous['inputs']['calibration'] or sha256_file(calibration_path) != recipe['calibrationSha256']:
        raise ValueError('registration calibration changed')
    reference = np.asarray(json.loads(calibration_path.read_text())['referencePositions'])
    camera_path = registration/'camera.json'
    if sha256_file(camera_path) != recipe['cameraSha256']:
        raise ValueError('authored registration camera changed')
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    matches = [r for r in corpus['captures'] if r['key'] == recipe['clip']]
    if len(matches) != 1:
        raise ValueError('recipe requires exactly one matching clip')
    row = matches[0]
    if len(row['frames']) != len(recipe['frames']):
        raise ValueError('authored frame inventory changed')
    for path, authored in zip(row['frames'], recipe['frames']):
        if sha256_file(Path(path)) != authored['sha256']:
            raise ValueError('authored source frame changed')
        with Image.open(path) as image:
            if list(image.size) != recipe['coordinateCanvas']:
                raise ValueError('authored coordinate canvas changed')
    if sha256_file(Path(row['capture'])) != row['captureSha256']:
        raise ValueError('capture hash changed')
    with np.load(row['capture'], allow_pickle=False) as raw:
        motion = load_motion(raw, row, corpus, skin, reference, profile['wholeBodyHubs'])
    joint = list(skin['names']).index(recipe['joint'])
    region_mask = np.asarray(skin['regions']) == recipe['region']
    if not region_mask.any() or not np.all(skin['weights'][region_mask, joint] == 1):
        raise ValueError('attachment region is not rigidly owned by the declared joint')
    source_mesh = Path(profile['mesh'])
    if sha256_file(source_mesh) != recipe['sourceMeshSha256']:
        raise ValueError('source anatomical axis mesh changed')
    skeleton = load_bind_skeleton(source_mesh)
    axis_sites = np.asarray([skeleton.rest_world[list(skeleton.names).index(n)] for n in recipe['sourceAxisBones']])
    axis = skin['inverseBind'][joint,:3,:3] @ (axis_sites[1] - axis_sites[0])
    directions = np.asarray([np.subtract(f['tip'], f['grip']) for f in recipe['frames']])
    local, world, report = correct(motion['localRotation'], motion['jointWorld'], skin['parents'], joint,
        axis, camera, directions, anchor_frame=recipe['anchorFrame'],
        max_correction_degrees=recipe['maxCorrectionDegrees'])
    report['baselineLeafLocalIdentityMax'] = float(np.abs(motion['localRotation'][:,joint]-np.eye(3)).max())
    report.update(proof='generated_attachment_direction_candidate', visualAcceptance='unreviewed',
        asset=recipe['asset'], clip=recipe['clip'], sourceRecipeSha256=sha256_file(recipe_path),
        corpusSha256=sha256_file(corpus_path), skinSha256=skin_hash,
        cameraSha256=sha256_file(camera_path), calibrationSha256=sha256_file(calibration_path),
        scope='Leaf orientation only; fixed body, skin, mesh, and wrist positions. Not absolute source fit.')
    if candidate_skin is not None:
        report.update(candidateSkinSha256=candidate_sha256,
            scope='Explicit topology-weight candidate plus leaf orientation; original geometry and body motion fixed.')
    if not np.allclose(world[:,0,:3,3], skin['offsets'][0], atol=1e-8):
        raise ValueError('rotation-only diagnostic export requires fixed root at bind')
    output.mkdir(parents=True)
    np.savez_compressed(output/'corrected_motion.npz', localRotation=local, jointWorld=world,
        baselineLocal=motion['localRotation'], baselineWorld=motion['jointWorld'],
        names=np.asarray(skin['names']), parents=skin['parents'], offsets=skin['offsets'])
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(skin['triangles'],skin['uvs'],skin['albedo'],camera,224)
        vertices = torch.as_tensor(skin['vertices'],device='cuda',dtype=torch.float32)
        weights = torch.as_tensor(candidate_weights,device='cuda',dtype=torch.float32)
        surface = SurfaceConstraints(skin['vertices'],skin['triangles'],device='cuda')
        report['surface'] = []
        columns = [source_images([Path(p) for p in row['frames']],camera['sourceCrop'],224)[0]]
        variants=[(motion['jointWorld'],weights),(world,weights)]
        titles=['Source','Captured body + inherited hand','Source-guided hand direction']
        if candidate_skin is not None:
            variants.insert(0,(motion['jointWorld'],torch.as_tensor(skin['weights'],device='cuda',dtype=torch.float32)))
            titles=['Source','Original skin','Topology skin','Topology + hand direction']
        for transforms, variant_weights in variants:
            matrices = torch.as_tensor((transforms @ skin['inverseBind'][None])[:,:,:3],device='cuda',dtype=torch.float32)
            meshes = deform(matrices,variant_weights,vertices)
            report['surface'].append(surface.metrics(meshes))
            columns.append(renderer.render(meshes)[0])
        comparison(output/'comparison.gif',columns,titles,recipe['clip'])
        times = np.arange(len(local),dtype=np.float32)*SOURCE_FRAME_MS/1000
        glb = output/'candidate.glb'
        write_skinned_glb(glb,names=skin['names'],parents=skin['parents'],
            rest_local_rotation=np.repeat(np.eye(3)[None],len(skin['names']),axis=0),
            rest_local_translation=skin['offsets'],inverse_bind=skin['inverseBind'],
            vertices=skin['vertices'],triangles=skin['triangles'],uvs=skin['uvs'],
            albedo=skin['albedo'],weights=candidate_weights,
            animation={'name':'source_guided_attachment','times':times,'rotations':matrices_to_xyzw(local)})
        report['exportParity'] = verify_calibrated_export(glb,expected_meshes=meshes.cpu().numpy(),expected_times=times,idle_frame=None)
    overlays=[]
    for path, authored in zip(row['frames'], recipe['frames']):
        with Image.open(path) as image:
            image=image.convert('RGB'); image.thumbnail((350,360))
        scale=np.asarray(image.size)/recipe['coordinateCanvas']
        draw=ImageDraw.Draw(image)
        points=[tuple(np.asarray(authored[k])*scale) for k in ('grip','tip')]
        draw.line(points,fill='yellow',width=2)
        for point,color in zip(points,('cyan','red')):
            x,y=point; draw.ellipse((x-3,y-3,x+3,y+3),fill=color)
        overlays.append(image)
    overlays[0].save(output/'authored_source.gif',save_all=True,append_images=overlays[1:],duration=180,loop=0)
    report['elapsedSecondsIncludingPreviewExport'] = time.perf_counter()-started
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('recipe','corpus','registration','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--candidate-skin',type=Path)
    parser.add_argument('--candidate-sha256')
    args=parser.parse_args()
    run(args.recipe,args.corpus,args.registration,args.output,args.candidate_skin,args.candidate_sha256)
