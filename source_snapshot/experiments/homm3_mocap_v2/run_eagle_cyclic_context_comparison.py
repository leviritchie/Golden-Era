"""Diagnostic only: hold retained movement frames fixed while varying context."""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from capture_candidates import require_frozen_package
from intermediate_capture import run_capture
from model_runner import load_model
from paths import REPO
from pin import sha256_file
from run_eagle_reference_capture_comparison import verify_source_identity
from run_mocap_baseline import _gpu_lock_waiting

CLIP = 'g00_move'
POLICIES = ('original', 'cyclic')


def context_mapping(length, source_indices, policy):
    indices = np.asarray(source_indices)
    if (not isinstance(length, (int, np.integer)) or isinstance(length, bool)
            or length <= 0 or indices.ndim != 1 or indices.size == 0
            or not np.issubdtype(indices.dtype, np.integer)
            or np.any(indices < 0) or np.any(indices >= length)
            or np.any(np.diff(indices) != 1)):
        raise ValueError('requires positive length and contiguous in-range integer authored indices')
    if policy == 'original':
        return np.arange(length)
    if policy != 'cyclic':
        raise ValueError('unknown context policy')
    # Phase-lock every retained frame; only the surrounding context changes.
    return indices[(np.arange(length) - indices[0]) % len(indices)]


def run(corpus_paths, output):
    started = time.perf_counter()
    if len(corpus_paths) != 2:
        raise ValueError('exactly two corpora required')
    if output.exists():
        raise FileExistsError('output must be absent')
    prepared = []
    for path in corpus_paths:
        corpus = json.loads(path.read_text())
        if corpus['package']['refSeq'] != 'Eagle#Eagle-Landing/y15':
            raise ValueError('requires frozen y15 source')
        rows = {r['key']: r for r in corpus['captures']}
        if len(rows) != len(corpus['captures']) or CLIP not in rows:
            raise ValueError('requires unique movement row')
        row = rows[CLIP]
        identity = verify_source_identity(corpus, row)
        raw_path = Path(row['capture'])
        if sha256_file(raw_path) != row['captureSha256']:
            raise ValueError('old capture hash drift')
        numbered = sorted((raw_path.parent.parent / 'frames').glob('*.png'))
        with np.load(raw_path, allow_pickle=False) as raw:
            embed = raw['image_embed'].copy()
            old_pred = raw['pred_position'].copy()
            old_ref = raw['ref_image_embed'].copy()
        expected_length = {'h3_thunderbird': 30, 'h3_shahrokh': 29}.get(corpus['unit'])
        if (len(embed) != expected_length or len(numbered) != len(embed)
                or row['sourceIndices'] != list(range(12, 18))):
            raise ValueError('unexpected unit or movement context inventory')
        prepared.append((path, corpus, row, numbered, embed, old_pred, old_ref, identity))
    if {item[1]['unit'] for item in prepared} != {'h3_thunderbird', 'h3_shahrokh'}:
        raise ValueError('requires both Thunderbird and Shahrokh')

    import torch
    output.mkdir(parents=True)
    outputs = []
    with _gpu_lock_waiting(REPO):
        model = load_model(torch.device('cuda'))[0]
        for path, corpus, row, numbered, embed, old_pred, old_ref, identity in prepared:
            package = require_frozen_package(corpus['unit'], role='primary')
            if (package['refSeq'] != corpus['package']['refSeq']
                    or not np.array_equal(package['refImageEmbed'], old_ref)):
                raise ValueError('frozen package reference differs from original')
            for policy in POLICIES:
                mapping = context_mapping(len(embed), row['sourceIndices'], policy)
                dest = output / corpus['unit'] / policy
                frame_dir = dest / CLIP / 'frames'
                frame_dir.mkdir(parents=True)
                for i, source_index in enumerate(mapping):
                    target = frame_dir / f'{i:06d}.png'
                    shutil.copy2(numbered[source_index], target)
                    if sha256_file(target) != identity['contextSha256'][source_index]:
                        raise ValueError('copied context frame hash mismatch')
                features = embed[mapping].copy()
                indices = row['sourceIndices']
                if not np.array_equal(features[indices], embed[indices]):
                    raise ValueError('retained authored embeddings changed')
                capture_dir = dest / CLIP / 'capture'
                report = run_capture(package=package, frames_dir=frame_dir,
                    out_dir=capture_dir, image_embed=features,
                    preprocess_meta=corpus['preprocess'], model=model,
                    source_kind='authored_source_frame', title=f'{CLIP}:{policy}', compare_gt=False)
                fresh = capture_dir / 'raw_capture.npz'
                with np.load(fresh, allow_pickle=False) as raw:
                    if not np.array_equal(raw['image_embed'], features):
                        raise ValueError('capture context embeddings changed')
                    if not np.array_equal(raw['ref_image_embed'], old_ref):
                        raise ValueError('capture reference embedding changed')
                    if policy == 'original' and not np.array_equal(raw['pred_position'], old_pred):
                        raise ValueError('fresh original baseline is not bit-exact')
                    delta = float(np.max(np.abs(raw['pred_position'][indices] - old_pred[indices])))
                new_row = {k: row[k] for k in ('key', 'frames', 'sourceIndices',
                    'referenceIndex', 'contextBeforeCount', 'contextAfterCount')}
                new_row.update(capture=str(fresh.resolve()), captureSha256=sha256_file(fresh),
                    report=report, retainedPredictionMaxDifference=delta)
                new_corpus = dict(schema='homm3.cyclic-context-diagnostic.v1', unit=corpus['unit'],
                    package=corpus['package'], preprocess=corpus['preprocess'], captures=[new_row],
                    provenance=dict(policy=policy, mapping=mapping.tolist(),
                        oldCorpus=str(path.resolve()), oldCorpusSha256=sha256_file(path),
                        sourceIdentity=identity))
                corpus_out = dest / 'corpus.json'
                corpus_out.write_text(json.dumps(new_corpus, indent=2) + '\n')
                outputs.append(str(corpus_out.resolve()))
                print(f"{corpus['unit']} {policy}: retained prediction max difference {delta}", flush=True)
    result = dict(outputs=outputs, elapsedSeconds=time.perf_counter()-started,
        accepted=False, proof='diagnostic captures only; no production changes',
        implementationHashes={name: sha256_file(Path(__file__).parent / name) for name in
            ('run_eagle_cyclic_context_comparison.py', 'run_eagle_reference_capture_comparison.py',
             'intermediate_capture.py', 'model_runner.py')})
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.corpus, args.output.resolve()), indent=2))
