"""Image-score one asset-wide motion frame; no skin, mesh or camera fitting."""
from __future__ import annotations

import argparse
import json
import time
import itertools
from pathlib import Path

import numpy as np
import torch
from scipy.spatial.transform import Rotation

from asset_profiles import get_profile
from compare_aligned_capture_motion import read_skin
from corpus_motion import load_motion
from global_motion_alignment import GlobalMotionAlignment
from local_rotation_capture_motion import reconstruct_local_rotation
from pin import sha256_file
from run_skin_mesh_pilot import comparison, deform, expand_camera_to_full_canvas, validate_capture_indices
from run_skin_weight_pilot import ROOT, cascade_batch_lock, source_images, digest
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics
from skin_surface_constraints import SurfaceConstraints
from source_reference_bind_candidate import build_source_reference_candidate


def alignment_seeds(mode):
    """Cover the 24 proper axis orientations; no reflection or unit-specific seed."""
    rotations = [np.eye(3)]
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1., 1.), repeat=3):
            matrix = np.eye(3)[:, permutation] * np.asarray(signs)[None]
            if np.linalg.det(matrix) > 0. and not any(np.array_equal(matrix, old) for old in rotations):
                rotations.append(matrix)
    seeds = []
    for matrix in rotations:
        for scale in ((1.,) if mode == 'rotation' else (1., .625, 1.6)):
            raw = np.zeros(3 if mode == 'rotation' else 7)
            raw[:3] = Rotation.from_matrix(matrix).as_rotvec()
            if mode == 'similarity':
                raw[3] = np.arctanh(np.log(scale)/np.log(2.))
            seeds.append(raw)
    return seeds


def run(original_path, corpus_path, registration, output, iterations=180):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    if iterations < 1:
        raise ValueError('iterations must be positive')
    original = read_skin(original_path)
    corpus = json.loads(corpus_path.read_text())
    if corpus.get('motionRepresentation', 'capture_positions_v1') != 'capture_positions_v1':
        raise ValueError('global alignment requires ordinary position captures')
    registered_path = registration/'pilot_report.json'
    registered = json.loads(registered_path.read_text())
    inputs = registered['inputs']
    if registered.get('kind') != 'idle_registration_only' or registered.get('asset') != corpus['unit']:
        raise ValueError('registration identity differs from corpus')
    if inputs['researchSkin'] != sha256_file(original_path) or inputs['corpusSha256'] != sha256_file(corpus_path):
        raise ValueError('registration inputs differ')
    calibration_path = Path(inputs['calibrationPath'])
    manifest_path = Path(corpus['manifest'])
    if sha256_file(calibration_path) != inputs['calibration'] or sha256_file(manifest_path) != corpus['manifestSha256']:
        raise ValueError('calibration or source manifest changed')
    reference = np.asarray(json.loads(calibration_path.read_text())['referencePositions'])
    hubs = tuple(get_profile(corpus['unit'])['wholeBodyHubs'])
    candidate = build_source_reference_candidate(original, reference, hubs)
    skin = candidate['skin']
    camera_path = registration/'camera.json'
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    pinned = {str(p.resolve()): sha256_file(p) for p in
              (original_path, corpus_path, registered_path, calibration_path, manifest_path, camera_path)}
    palettes, controls, slices, paths, frame_ids, heldout = [], [], {}, [], [], []
    cursor = 0
    if not corpus['captures']:
        raise ValueError('empty corpus')
    for entry in corpus['captures']:
        key = entry['key']
        if key in slices or Path(key).name != key or any(c in key for c in '/\\:'):
            raise ValueError('duplicate or unsafe clip key')
        capture_path = Path(entry['capture'])
        if sha256_file(capture_path) != entry['captureSha256']:
            raise ValueError('capture changed')
        pinned[str(capture_path)] = entry['captureSha256']
        for frame in entry['frames']:
            expected = corpus['sourceFrames'][frame]['sha256']
            if sha256_file(Path(frame)) != expected:
                raise ValueError('source frame changed')
            pinned[frame] = expected
        with np.load(capture_path, allow_pickle=False) as raw:
            validate_capture_indices(entry, len(raw['pred_position']))
            if list(raw['joint_names'].astype(str)) != list(skin['names']) or not np.array_equal(raw['parents'], skin['parents']):
                raise ValueError('capture skeleton inventory differs')
            positions = raw['pred_position'][entry['sourceIndices']]
            control = load_motion(raw, entry, corpus, original, reference, hubs)
            motion = reconstruct_local_rotation(capture_positions=positions, capture_reference_positions=reference,
                capture_offsets=skin['captureOffsets'], fitted_offsets=skin['offsets'], parents=skin['parents'],
                names=list(skin['names']), hub_names=hubs)
        similarity = candidate['report']['transform']
        expected_root = similarity['scale'] * positions[:, 0] @ np.asarray(similarity['rotation']).T + similarity['translation']
        delta = expected_root-motion['jointWorld'][:, 0, :3, 3]
        motion['jointWorld'][:, :, :3, 3] += delta[:, None]
        palettes.append(motion['jointWorld'] @ skin['inverseBind'][None])
        controls.append(control['jointWorld'] @ original['inverseBind'][None])
        count = len(entry['frames'])
        slices[key] = slice(cursor, cursor+count)
        if count >= 5:
            heldout.append(cursor+count//2)
        paths.extend(Path(p) for p in entry['frames'])
        frame_ids.extend(f'{key}:{i}' for i in range(count))
        cursor += count
    source = np.concatenate(palettes)
    source_hash = digest(source)
    train = [i for i in range(cursor) if i not in heldout]
    if not heldout or not train:
        raise ValueError('trial requires nonempty train and withheld frames')
    report = {'asset': corpus['unit'], 'accepted': False, 'proof': 'shared_alignment_diagnostic',
        'scope': 'one shared correction per mode; fixed camera, mesh, weights and precomputed source-reference palette',
        'inputHashes': pinned, 'sourcePaletteSha256': source_hash, 'sourceReferenceBind': candidate['report'],
        'trainFrames': [frame_ids[i] for i in train], 'heldoutFrames': [frame_ids[i] for i in heldout],
        'iterations': iterations, 'objective': 'image_loss total only; heldout not used for checkpoint selection',
        'modes': {}, 'cases': {}}
    output.mkdir(parents=True)
    np.savez_compressed(output/'source_skin.npz', **skin)
    report['sourceSkinSha256'] = sha256_file(output/'source_skin.npz')
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(skin['triangles'], skin['uvs'], skin['albedo'], camera, 224)
        surface = SurfaceConstraints(skin['vertices'], skin['triangles'], device='cuda')
        vertices = torch.as_tensor(skin['vertices'], device='cuda', dtype=torch.float32)
        weights = torch.as_tensor(skin['weights'], device='cuda', dtype=torch.float32)
        source_tensor = torch.as_tensor(source, device='cuda', dtype=torch.float32)
        span = float(np.linalg.norm(np.ptp(skin['vertices'], axis=0)))
        pivot = (vertices.max(0).values+vertices.min(0).values)*.5
        targets = source_images(paths, camera['sourceCrop'], 224)
        train_targets = tuple(v[train] for v in targets)
        with torch.no_grad():
            base_mesh = deform(source_tensor[:, :, :3], weights, vertices)
            prepared_mesh = deform(torch.as_tensor(np.concatenate(controls)[:, :, :3], device='cuda', dtype=torch.float32),
                torch.as_tensor(original['weights'], device='cuda', dtype=torch.float32), vertices)
        meshes = {'prepared': prepared_mesh, 'source_reference': base_mesh}
        for mode in ('rotation', 'similarity'):
            field = GlobalMotionAlignment(source_tensor, pivot=pivot, span=span, mode=mode)
            best, state, history, best_step = float('inf'), None, [], None
            mode_start = time.perf_counter()
            coarse = []
            with torch.no_grad():
                for seed_index, seed in enumerate(alignment_seeds(mode)):
                    field.raw.copy_(torch.as_tensor(seed, device='cuda', dtype=field.raw.dtype))
                    posed = deform(field()[:, :, :3], weights, vertices)
                    value = float(image_loss(*renderer.render(posed[train]), *train_targets)['total'])
                    if not np.isfinite(value):
                        raise ValueError('nonfinite coarse alignment score')
                    coarse.append({'seed': seed_index, 'parameters': seed.tolist(), 'trainingLoss': value})
            selected = sorted(coarse, key=lambda row: row['trainingLoss'])[:3]
            for seed in selected:
                with torch.no_grad():
                    field.raw.copy_(torch.as_tensor(seed['parameters'], device='cuda', dtype=field.raw.dtype))
                optimizer = torch.optim.Adam(field.parameters(), lr=.025)
                for step in range(iterations):
                    optimizer.zero_grad(set_to_none=True)
                    posed = deform(field()[:, :, :3], weights, vertices)
                    loss = image_loss(*renderer.render(posed[train]), *train_targets)['total']
                    if not torch.isfinite(loss):
                        raise ValueError('nonfinite alignment objective')
                    value = float(loss.detach())
                    if value < best:
                        best = value
                        best_step = {'seed': seed['seed'], 'step': step}
                        state = {name: parameter.detach().clone() for name, parameter in field.named_parameters()}
                    loss.backward()
                    if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in field.parameters()):
                        raise ValueError('nonfinite alignment gradient')
                    optimizer.step()
                    if step % 60 == 0:
                        history.append({'seed': seed['seed'], 'step': step, 'trainingLoss': value})
                        print(json.dumps({'mode': mode, **history[-1]}), flush=True)
            with torch.no_grad():
                for name, parameter in field.named_parameters():
                    parameter.copy_(state[name])
                transformed = field()
                meshes[mode] = deform(transformed[:, :, :3], weights, vertices)
                transform = field.matrix()
                identity = torch.eye(4, device='cuda')
                neutral = transform @ identity @ torch.linalg.inv(transform)
                neutral_error = float((neutral-identity).abs().max())
                if neutral_error > 2e-6:
                    raise ValueError('alignment changed neutral identity')
                report['modes'][mode] = {'alignment': field.stats(), 'trainingLoss': best, 'history': history,
                    'selectedStep': best_step,
                    'coarseSeeds': coarse, 'refinedSeeds': [row['seed'] for row in selected],
                    'neutralPaletteMaxAbsError': neutral_error, 'elapsedSeconds': time.perf_counter()-mode_start}
                np.savez_compressed(output/f'{mode}_motion.npz', palettes=transformed.cpu().numpy(), correction=transform.cpu().numpy())
        with torch.no_grad():
            images = {name: renderer.render(mesh) for name, mesh in meshes.items()}
            for name, mesh in meshes.items():
                scores = image_metrics(*images[name], *targets[:2])
                report.setdefault('scores', {})[name] = scores
                report.setdefault('splitMetrics', {})[name] = {}
                for split, indices in (('train', train), ('heldout', heldout)):
                    losses = image_loss(*[v[indices] for v in images[name]], *[v[indices] for v in targets])
                    report['splitMetrics'][name][split] = {key: float(value) for key, value in losses.items()}
                    report['splitMetrics'][name][split]['frameCount'] = len(indices)
                report.setdefault('surface', {})[name] = surface.metrics(mesh)
                depth = mesh @ torch.as_tensor(camera['forward'], device='cuda', dtype=torch.float32)
                report.setdefault('depthClippedSamples', {})[name] = int(((depth-camera['depth_center']).abs() >= camera['depth_span']).sum())
            for key, selected in slices.items():
                comparison(output/f'{key}.gif', [targets[0][selected]] + [images[name][0][selected] for name in meshes],
                    ['Source', 'Prepared', 'Source-reference', 'Shared rotation', 'Shared similarity'], key)
                report['cases'][key] = {'start': selected.start, 'stop': selected.stop}
                print(str(output/f'{key}.gif'), flush=True)
        if not torch.equal(source_tensor, torch.as_tensor(source, device='cuda', dtype=torch.float32)):
            raise ValueError('immutable source palettes changed')
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected:
            raise ValueError('trial input changed during execution')
    if digest(source) != source_hash:
        raise ValueError('source motion changed')
    report['elapsedSeconds'] = time.perf_counter()-started
    report['implementation'] = {name: sha256_file(Path(__file__).parent/name) for name in (
        'run_global_motion_alignment.py', 'global_motion_alignment.py', 'source_reference_bind_candidate.py',
        'coincident_bind_candidate.py', 'local_rotation_capture_motion.py', 'reconstruct_adapted.py',
        'direction_retarget.py', 'skin_image_objective.py', 'skin_surface_constraints.py')}
    (output/'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'corpus', 'registration', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=180)
    args = parser.parse_args()
    run(args.original.resolve(), args.corpus.resolve(), args.registration.resolve(), args.output.resolve(), args.iterations)
