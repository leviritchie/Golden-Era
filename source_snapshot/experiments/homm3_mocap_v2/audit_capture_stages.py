"""CPU-only capture loss decomposition, not a new animation or skin candidate."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from asset_profiles import get_profile
from capture_stage_metrics import analyze
from direction_retarget import desired_target_directions
from reconstruct_adapted import reconstruct_adapted, one_to_one_bone_chains
from pin import sha256_file


def directions(positions, parents):
    edge = positions - positions[..., np.maximum(parents, 0), :]
    length = np.linalg.norm(edge, axis=-1, keepdims=True)
    return np.divide(edge, length, out=np.zeros_like(edge), where=length > 1e-8)


def preview(stages, parents, camera, path):
    labels = ['Raw captured joints', 'Lengths fixed; free branches', 'Rigid FK; no smoothing', 'Current same-rest FK', 'Current fitted-rest FK']
    basis = np.asarray([camera['right'], camera['down']])
    projected = [positions @ basis.T for positions in stages]
    all_points = np.concatenate(projected).reshape(-1, 2)
    center = (all_points.min(0) + all_points.max(0)) / 2
    scale = 220 / np.ptp(all_points, axis=0).max()
    frames = []
    for t in range(len(stages[0])):
        frame = Image.new('RGB', (1300, 310), (22, 24, 27))
        draw = ImageDraw.Draw(frame)
        for column, (points, label) in enumerate(zip(projected, labels)):
            xy = (points[t] - center) * scale + [column * 260 + 130, 165]
            draw.text((column * 260 + 6, 8), label, fill='white')
            for child, parent in enumerate(parents):
                if parent >= 0:
                    draw.line([tuple(xy[parent]), tuple(xy[child])], fill=(95, 220, 135), width=2)
            for x, y in xy:
                draw.ellipse((x-2, y-2, x+2, y+2), fill=(225, 235, 230))
        draw.text((8, 289), f'Authored frame {t}; root-relative, own reference-span normalized; NOT pixel alignment or mesh playback', fill='white')
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=1000/12, loop=0)
    selected = sorted(set(np.linspace(0, len(frames)-1, min(4, len(frames))).astype(int)))
    sheet = Image.new('RGB', (1300, len(selected)*310))
    for row, index in enumerate(selected):
        sheet.paste(frames[index], (0, row*310))
    sheet.save(path.with_suffix('.png'))


def run(skin_path, corpus_path, registration, output):
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    registered_path = registration/'pilot_report.json'
    registered = json.loads(registered_path.read_text())
    corpus = json.loads(corpus_path.read_text())
    if registered['asset'] != corpus['unit'] or registered['kind'] != 'idle_registration_only':
        raise ValueError('registration/corpus identity mismatch')
    if corpus.get('motionRepresentation', 'capture_positions_v1') != 'capture_positions_v1':
        raise ValueError('requires raw ordinary capture, not composed FK')
    inputs = registered['inputs']
    calibration_path = Path(inputs['calibrationPath'])
    for path, expected in ((skin_path, inputs['researchSkin']), (corpus_path, inputs['corpusSha256']),
                           (calibration_path, inputs['calibration'])):
        if sha256_file(path) != expected:
            raise ValueError(f'registered input changed: {path}')
    manifest_path = Path(corpus['manifest'])
    if sha256_file(manifest_path) != corpus['manifestSha256']:
        raise ValueError('source manifest changed')
    with np.load(skin_path, allow_pickle=False) as raw:
        skin = {key: raw[key].copy() for key in raw.files}
    names = list(skin['names'].astype(str))
    parents = skin['parents']
    reference = np.asarray(json.loads(calibration_path.read_text())['referencePositions'])
    hubs = tuple(get_profile(corpus['unit'])['wholeBodyHubs'])
    camera_path = registration/'camera.json'
    camera = json.loads(camera_path.read_text())
    pinned = {str(p.resolve()): sha256_file(p) for p in (skin_path, corpus_path, registered_path, calibration_path, camera_path, manifest_path)}
    clips = corpus['captures']
    if not clips or len({r['key'] for r in clips}) != len(clips):
        raise ValueError('empty/duplicate clips')
    for row in clips:
        if Path(row['key']).name != row['key'] or any(c in row['key'] for c in '/\\:'):
            raise ValueError('unsafe clip key')
        if sha256_file(Path(row['capture'])) != row['captureSha256']:
            raise ValueError('capture changed')
        pinned[str(Path(row['capture']).resolve())] = row['captureSha256']
        for frame in row['frames']:
            if sha256_file(Path(frame)) != corpus['sourceFrames'][frame]['sha256']:
                raise ValueError('source frame changed')
    output.mkdir(parents=True)
    report = dict(asset=corpus['unit'], proof='capture_stage_diagnostic_only', accepted=False,
                  scope='same-reference controls isolate length, rigid-branch, and smoothing loss; no production changes',
                  inputHashes=pinned, cases={})
    for row in clips:
        with np.load(row['capture'], allow_pickle=False) as raw:
            if list(raw['joint_names'].astype(str)) != names or not np.array_equal(raw['parents'], parents):
                raise ValueError('capture skeleton differs from skin')
            indices = np.asarray(row['sourceIndices'])
            if indices.dtype.kind not in 'iu' or indices.ndim != 1 or len(indices) != len(row['frames']) or not len(indices) or np.any(indices < 0) or np.any(indices >= len(raw['pred_position'])):
                raise ValueError('invalid authored frame indices')
            capture = raw['pred_position'][indices].copy()
        result = analyze(capture, reference, skin['captureOffsets'], parents, names, hubs)
        fitted = reconstruct_adapted(capture_positions=capture, capture_reference_positions=reference,
            capture_offsets=skin['captureOffsets'], fitted_offsets=skin['offsets'], parents=parents, names=names, hub_names=hubs)
        observable = (parents >= 0) & (np.linalg.norm(skin['captureOffsets'], axis=1) > 1e-8)
        chains = [c for c in one_to_one_bone_chains(names, parents) if observable[names.index(c['target'][-1])]]
        desired = desired_target_directions(capture_positions=capture, capture_rest=reference, capture_names=names,
            target_rest=fitted['fittedRest'], target_names=names, chains=chains)
        actual = directions(fitted['positions'], parents)
        fitted_observable = observable & (np.linalg.norm(skin['offsets'], axis=1) > 1e-8)
        angle = np.degrees(np.arccos(np.clip(np.sum(actual*desired, axis=-1), -1, 1)))[:, fitted_observable]
        metrics = result['metrics']
        metrics['fittedDesiredDirectionErrorDegrees'] = dict(mean=float(angle.mean()), maximum=float(angle.max()), p95=float(np.percentile(angle, 95)))
        metrics['fittedDesiredErrorByBone'] = {name: float(angle[:, i].mean()) for i, name in enumerate(np.asarray(names)[fitted_observable])}
        metrics['fittedZeroLengthExcluded'] = list(np.asarray(names)[observable & ~fitted_observable])
        report['cases'][row['key']] = dict(frameCount=len(indices), metrics=metrics)
        stages = result['stages']
        np.savez_compressed(output/(row['key']+'.npz'), **stages, fitted=fitted['positions'])
        ref_span = np.linalg.norm(np.ptp(reference, axis=0))
        fit_span = np.linalg.norm(np.ptp(fitted['fittedRest'], axis=0))
        plots = [(stages[k] - stages[k][:, :1]) @ fitted['wholeBodyRotation'].T / ref_span for k in
                 ('raw', 'fixed_lengths_independent_edges', 'unsmoothed_same_rest_fk', 'current_same_rest_fk')]
        plots.append((fitted['positions'] - fitted['positions'][:, :1]) / fit_span)
        preview(plots, parents, camera, output/(row['key']+'.gif'))
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected:
            raise ValueError('input changed during audit')
    report['implementation'] = {name: sha256_file(Path(__file__).parent/name) for name in
        ('audit_capture_stages.py', 'capture_stage_metrics.py', 'reconstruct_adapted.py', 'direction_retarget.py', 'mesh_preview.py', 'donor_eagle.py')}
    report['elapsedSeconds'] = time.perf_counter()-started
    (output/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'report': str(output/'report.json'), 'elapsedSeconds': report['elapsedSeconds']}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('skin', 'corpus', 'registration', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    run(a.skin, a.corpus, a.registration, a.output)
