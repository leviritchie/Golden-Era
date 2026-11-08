"""Fit shared local-axis gauges with entire attack clips withheld."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

from body_relative_capture_motion import reconstruct_body_relative
from corpus_motion import load_motion
from direction_retarget import _rodrigues
from donor_eagle import compute_rest_joints
from joint_axis_calibration import JointAxisCalibration
from pin import sha256_file
from reconstruct_adapted import whole_body_rotation
from run_anatomical_capture_comparison import prepare
from run_skin_mesh_pilot import comparison, deform, expand_camera_to_full_canvas, validate_capture_indices
from run_skin_weight_pilot import ROOT, cascade_batch_lock, source_images
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics
from skin_surface_constraints import SurfaceConstraints

HELDOUT_CLIPS = frozenset(('g11_attack_up', 'g13_attack_down'))
IMPLEMENTATIONS = ('run_joint_axis_calibration.py', 'joint_axis_calibration.py',
                  'run_anatomical_capture_comparison.py', 'body_relative_capture_motion.py',
                  'reconstruct_adapted.py', 'direction_retarget.py', 'corpus_motion.py',
                  'coincident_bind_candidate.py', 'skin_image_objective.py', 'skin_surface_constraints.py')


def partition_clips(rows):
    keys = [row['key'] for row in rows]
    if len(set(keys)) != len(keys) or not HELDOUT_CLIPS.issubset(keys):
        raise ValueError('requires unique clips including both explicit heldout attacks')
    train, heldout, slices = [], [], {}
    cursor = 0
    for row in rows:
        count = len(row['frames'])
        if count < 1:
            raise ValueError('empty clip')
        slices[row['key']] = slice(cursor, cursor + count)
        (heldout if row['key'] in HELDOUT_CLIPS else train).extend(range(cursor, cursor + count))
        cursor += count
    if not train or not heldout:
        raise ValueError('requires nonempty training and heldout sets')
    return train, heldout, slices


def source_motion(positions, reference, skin, hubs):
    """Reconstruct in source-reference geometry first; never fit source on target."""
    parents = np.asarray(skin['parents'])
    names = list(skin['names'])
    source_offsets = reference - reference[parents.clip(0)]
    source_offsets[0] = reference[0]
    motion = reconstruct_body_relative(
        capture_positions=positions, capture_reference_positions=reference,
        capture_offsets=skin['captureOffsets'], fitted_offsets=source_offsets,
        parents=parents, names=names, hub_names=hubs,
    )
    target_rest = compute_rest_joints(skin['offsets'], parents)
    gauge = whole_body_rotation(reference, target_rest, names, hubs)
    local = gauge @ motion['localRotation'] @ gauge.T
    roots = target_rest[0] + (positions[:, 0] - reference[0]) @ gauge.T
    return local, roots, gauge


def array_hash(value):
    array = np.ascontiguousarray(value)
    return hashlib.sha256(str((array.shape, array.dtype)).encode() + array.tobytes()).hexdigest()


def verify_calibration(skin, reference, hubs, raw):
    """Exercise source reconstruction AND learned axes on rigid weighted meshes."""
    rotations = [np.eye(3)] + [_rodrigues(axis, np.radians(a))
        for axis in np.eye(3) for a in (-90., -45., 45., 90.)]
    travel = [np.zeros(3)] + [np.array([.13, -.07, .11])] * 12
    positions = np.stack([(reference - reference[0]) @ r.T + reference[0] + t
                          for r, t in zip(rotations, travel)])
    local, roots, gauge = source_motion(positions, reference, skin, hubs)
    model = JointAxisCalibration(local, roots, skin['offsets'], skin['parents'])
    with torch.no_grad():
        model.raw.copy_(torch.as_tensor(raw, dtype=model.raw.dtype))
        world = model().numpy()
    vertices = skin['vertices']
    hom = np.column_stack((vertices, np.ones(len(vertices))))
    rest_root = compute_rest_joints(skin['offsets'], skin['parents'])[0]
    errors = []
    for w, r, t in zip(world, rotations, travel):
        q = gauge @ r @ gauge.T
        mesh = np.einsum('vj,jab,vb->va', skin['weights'], w @ skin['inverseBind'], hom)[:, :3]
        expected = (vertices - rest_root) @ q.T + rest_root + gauge @ t
        errors.append(float(np.max(np.abs(mesh - expected))))
    if not np.isfinite(errors).all() or max(errors) >= 1e-6:
        raise ValueError(f'calibrated rigid mesh control failed: {errors}')
    return {'passed': True, 'poseCount': 13, 'neutralError': errors[0],
            'rigidErrorMax': max(errors[1:]), 'learnedParametersExercised': True}


def run(original_path, corpus_path, registration, output, steps=250):
    started = time.perf_counter()
    if output.exists() or steps < 1:
        raise ValueError('requires unique output directory and positive steps')
    corpus = json.loads(corpus_path.read_text())
    prep = prepare(corpus['unit'], original_path, corpus_path, registration)
    original, skin = prep['original'], prep['canonical']['skin']
    reference = np.asarray(json.loads(prep['provenance']['calibration'].read_text())['referencePositions'])
    hubs = tuple(prep['profile']['wholeBodyHubs'])
    train, heldout, slices = partition_clips(corpus['captures'])
    camera_path = registration / 'camera.json'
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    pinned = dict(prep['inputHashes'])
    manifest = Path(corpus['manifest'])
    if sha256_file(manifest) != corpus['manifestSha256']:
        raise ValueError('source manifest changed')
    source_mesh = Path(prep['profile']['mesh'])
    if sha256_file(source_mesh) != prep['profile']['expectedMeshSha256']:
        raise ValueError('source mesh identity changed')
    for path in [camera_path, manifest, source_mesh] + [Path(__file__).parent / name for name in IMPLEMENTATIONS]:
        pinned[str(path.resolve())] = sha256_file(path)
    locals_all, roots_all, prepared_world, frame_paths, frame_ids = [], [], [], [], []
    for row in corpus['captures']:
        cap = Path(row['capture'])
        pinned[str(cap.resolve())] = row['captureSha256']
        for path in row['frames']:
            pinned[str(Path(path).resolve())] = corpus['sourceFrames'][path]['sha256']
        with np.load(cap, allow_pickle=False) as raw:
            validate_capture_indices(row, len(raw['pred_position']))
            if list(raw['joint_names'].astype(str)) != list(skin['names']) or not np.array_equal(raw['parents'], skin['parents']):
                raise ValueError('capture hierarchy differs from prepared skin')
            positions = raw['pred_position'][row['sourceIndices']]
            local, roots, gauge = source_motion(positions, reference, skin, hubs)
            control = load_motion(raw, row, corpus, original, reference, hubs)
        locals_all.append(local)
        roots_all.append(roots)
        prepared_world.append(control['jointWorld'])
        frame_paths.extend(Path(path) for path in row['frames'])
        frame_ids.extend(f'{row["key"]}:{i}' for i in range(len(row['frames'])))
    fixed_local, fixed_roots = np.concatenate(locals_all), np.concatenate(roots_all)
    source_hash = array_hash(fixed_local)
    output.mkdir(parents=True)
    np.savez_compressed(output / 'canonical_skin.npz', **skin)
    np.savez_compressed(output / 'fixed_source.npz', local=fixed_local, roots=fixed_roots, globalGauge=gauge)
    report = {'asset': corpus['unit'], 'accepted': False, 'proof': 'static_joint_axis_diagnostic',
              'inputHashes': pinned, 'canonicalPreparation': prep['canonical']['report'],
              'canonicalSkinSha256': sha256_file(output / 'canonical_skin.npz'),
              'fixedSourceSha256': sha256_file(output / 'fixed_source.npz'),
              'sourceLocalArraySha256': source_hash, 'heldoutClips': sorted(HELDOUT_CLIPS),
              'trainFrames': [frame_ids[i] for i in train], 'heldoutFrames': [frame_ids[i] for i in heldout],
              'objective': 'training image_loss.total + 0.02 * existing dimensionless surface loss; no heldout loss used',
              'scope': 'shared non-root axis conjugations; fixed angular trajectories, roots, bind, weights, mesh, camera',
              'cases': {}, 'iterations': steps, 'learningRate': .03}
    with cascade_batch_lock(ROOT):
        def tensor(value):
            return torch.as_tensor(value, dtype=torch.float32, device='cuda')

        vertices, weights, inverse = tensor(skin['vertices']), tensor(skin['weights']), tensor(skin['inverseBind'])
        field = JointAxisCalibration(tensor(fixed_local), tensor(fixed_roots), tensor(skin['offsets']), skin['parents'])
        renderer = SkinImageRenderer(skin['triangles'], skin['uvs'], skin['albedo'], camera, 224)
        surface = SurfaceConstraints(skin['vertices'], skin['triangles'], device='cuda')
        targets = source_images(frame_paths, camera['sourceCrop'], 224)
        train_targets = tuple(value[train] for value in targets)

        def mesh_from_world(world):
            return deform((world @ inverse[None])[:, :, :3], weights, vertices)

        with torch.no_grad():
            uncalibrated = mesh_from_world(field())
            current = deform((tensor(np.concatenate(prepared_world)) @ tensor(original['inverseBind'])[None])[:, :, :3],
                             tensor(original['weights']), vertices)
        optimizer = torch.optim.Adam(field.parameters(), lr=.03)
        best_value, best_raw, best_step, history = float('inf'), None, None, []
        for step in range(steps + 1):
            optimizer.zero_grad(set_to_none=True)
            mesh = mesh_from_world(field())[train]
            rgb, alpha = renderer.render(mesh)
            image_term = image_loss(rgb, alpha, *train_targets)['total']
            surface_term = surface.loss(mesh)
            loss = image_term + .02 * surface_term
            if not torch.isfinite(loss):
                raise ValueError('nonfinite training objective')
            value = float(loss.detach())
            if value < best_value:
                best_value, best_raw, best_step = value, field.raw.detach().clone(), step
            if step % 25 == 0:
                history.append({'step': step, 'trainingLoss': value, 'image': float(image_term.detach()),
                                'surface': float(surface_term.detach())})
            if step < steps:
                loss.backward()
                if field.raw.grad is None or not torch.isfinite(field.raw.grad).all():
                    raise ValueError('missing or nonfinite axis gradient')
                optimizer.step()
        with torch.no_grad():
            field.raw.copy_(best_raw)
            learned_world = field()
            calibrated = mesh_from_world(learned_world)
            corrected_local = field.locals()
            trace_error = float((corrected_local.diagonal(dim1=-2, dim2=-1).sum(-1)
                               - field.source_local.diagonal(dim1=-2, dim2=-1).sum(-1)).abs().max())
            if trace_error > 1e-4 or not torch.equal(corrected_local[:, 0], field.source_local[:, 0]):
                raise ValueError('angular trajectory or frozen root violated')
            raw_parameters = field.raw.cpu().numpy()
            report['rigidWeightedControls'] = verify_calibration(skin, reference, hubs, raw_parameters)
            report.update(bestStep=best_step, bestTrainingLoss=best_value, history=history,
                          parameters=raw_parameters.tolist(), parameterCount=field.raw.numel(), traceErrorMax=trace_error)
            np.savez_compressed(output / 'calibrated_motion.npz', jointWorld=learned_world.cpu().numpy(),
                                localRotation=corrected_local.cpu().numpy(), raw=raw_parameters)
            meshes = (current, uncalibrated, calibrated)
            images = [renderer.render(mesh) for mesh in meshes]
            for key, indices in slices.items():
                clip_targets = tuple(value[indices] for value in targets)
                clip_images = [tuple(value[indices] for value in item) for item in images]
                forward = tensor(camera['forward'])
                report['cases'][key] = {
                    'frameCount': indices.stop - indices.start, 'heldout': key in HELDOUT_CLIPS,
                    'scores': [image_metrics(*item, *clip_targets[:2]) for item in clip_images],
                    'surface': [surface.metrics(mesh[indices]) for mesh in meshes],
                    'depthClippedVertexSamples': [int((((mesh[indices] @ forward) - camera['depth_center']).abs()
                                                     >= camera['depth_span']).sum()) for mesh in meshes],
                }
                comparison(output / (key + '.gif'), [clip_targets[0]] + [item[0] for item in clip_images],
                           ['Source', 'Current prepared', 'Fixed source axes', 'Learned static axes'],
                           key + ('; HELD OUT' if key in HELDOUT_CLIPS else '; training'))
    if source_hash != array_hash(fixed_local):
        raise ValueError('source locals changed')
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected:
            raise ValueError(f'input changed during trial: {path}')
    report['elapsedSeconds'] = time.perf_counter() - started
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('original', 'corpus', 'registration', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--steps', type=int, default=250)
    args = parser.parse_args()
    result = run(args.original.resolve(), args.corpus.resolve(), args.registration.resolve(), args.output.resolve(), args.steps)
    print(json.dumps({'report': str(args.output.resolve() / 'report.json'), 'elapsedSeconds': result['elapsedSeconds'], 'bestStep': result['bestStep']}))
