"""Source-replayed ownership checks for final, styled mocap delivery clips."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from asset_profiles import get_profile
from attachment_repair import boundary_gaps
from eagle_glb import gltf_world_matrices
from geometry_ownership import load_ownership
from glb_skeleton import load_bind_skeleton, read_glb
from mesh_preview import skin_vertices
from run_shape_preserved import _load_frozen_prep
from structured_profiles import require_profile_pin
from verify_calibrated_export import _serialized_local_rotations

ROOT = Path(__file__).resolve().parents[2]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ownership_context(source):
    """Resolve the existing current frozen preparation, never a guessed NPZ."""
    asset = source['assetId']
    profile = get_profile(asset)
    if 'geometryOwnership' not in profile:
        return None
    report_path = Path(source['sourceReport'])
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path = report_path.resolve()
    if _sha(report_path) != source['sourceReportSha256']:
        raise ValueError('ownership source report differs from selection')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    freeze, prepared = _load_frozen_prep(asset)
    pin = require_profile_pin(asset, profile, report, freeze)
    if report.get('asset') != asset or report['inputs']['researchSkin'] != freeze['inputHashes']['researchSkin']:
        raise ValueError('ownership fit does not use the current frozen preparation')
    if report.get('bindMode') != 'prepared':
        raise ValueError('ownership delivery requires the explicitly prepared bind')
    definition = load_ownership(profile)
    reference = {'sourceReport': str(report_path), 'sourceReportSha256': _sha(report_path),
                 'path': str(Path(freeze['researchSkin']).resolve()),
                 'sha256': freeze['inputHashes']['researchSkin'],
                 'geometryOwnership': profile['geometryOwnership'], **pin}
    return {'reference': reference, 'prepared': prepared,
            'maxBoundaryGap': definition['maxBoundaryGap']}


def replay_boundaries(glb_path, context):
    """Evaluate serialized keys and midpoint samples, not continuous/runtime proof."""
    path = Path(glb_path)
    doc = read_glb(path)['json']
    # FK omits the common rigid presentation wrapper. Distances are invariant
    # only when no node introduces scale or a matrix transform.
    for node in doc.get('nodes', []):
        if 'matrix' in node or not np.array_equal(np.asarray(node.get('scale', [1, 1, 1])), [1, 1, 1]):
            raise ValueError('ownership replay requires unit-scale TRS nodes')
    skeleton = load_bind_skeleton(path)
    node_parents = {child: index for index, node in enumerate(doc['nodes']) for child in node.get('children', [])}
    for joint, parent in enumerate(skeleton.parents):
        if parent >= 0 and node_parents.get(skeleton.node_indices[joint]) != skeleton.node_indices[parent]:
            raise ValueError('ownership replay refuses non-joint transforms between joints')
    prepared = context['prepared']
    if skeleton.vertices is None or len(skeleton.vertices) != len(prepared['vertices']):
        raise ValueError('delivered ownership vertex count differs')
    names = list(prepared['names'])
    if len(set(names)) != len(names) or len(set(skeleton.names)) != len(names) or set(skeleton.names) != set(names):
        raise ValueError('delivered ownership joint identities differ')
    # The exporter canonicalizes donor DFS into loader BFS. Compare identities,
    # not array positions; JSON translations retain double precision.
    source_index = {name: index for index, name in enumerate(names)}
    order = [source_index[name] for name in skeleton.names]
    expected_parent_names = [None if prepared['parents'][i] < 0 else names[prepared['parents'][i]] for i in order]
    actual_parent_names = [None if i < 0 else skeleton.names[i] for i in skeleton.parents]
    if (actual_parent_names != expected_parent_names or
            not np.array_equal(skeleton.rest_local_translation, np.asarray(prepared['offsets'])[order]) or
            not np.array_equal(skeleton.rest_local_rotation, np.broadcast_to(np.eye(3), (len(skeleton.names), 3, 3))) or
            not np.array_equal(skeleton.inverse_bind, np.asarray(prepared['inverseBind'], dtype=np.float32)[order]) or
            not np.array_equal(skeleton.triangles, prepared['triangles']) or
            not np.array_equal(skeleton.uvs, np.asarray(prepared['uvs'], dtype=np.float32))):
        raise ValueError('delivered ownership topology, UVs or authored bind differ')
    times, rotations, translations, _ = _serialized_local_rotations(path, allow_root_motion=True)
    sample_times = np.sort(np.concatenate((times, (times[:-1] + times[1:]) / 2)))
    if len(times) > 1:
        sampled_rotation = np.stack([
            Slerp(times, Rotation.from_matrix(rotations[:, joint]))(sample_times).as_matrix()
            for joint in range(len(skeleton.names))], axis=1)
        sampled_translation = np.stack([
            np.stack([np.interp(sample_times, times, translations[:, joint, axis]) for axis in range(3)], axis=1)
            for joint in range(len(skeleton.names))], axis=1)
    else:
        sampled_rotation, sampled_translation = rotations, translations
    posed = []
    for rotation, translation in zip(sampled_rotation, sampled_translation):
        world = gltf_world_matrices(local_rotation=rotation, local_translation=translation,
                                    parents=np.asarray(skeleton.parents))
        posed.append(skin_vertices(skeleton, world))
    animated = np.stack(posed)
    if not np.isfinite(animated).all():
        raise ValueError('delivered ownership replay is nonfinite')
    pairs = prepared['ownershipBoundaryPairs']
    result = boundary_gaps(animated, pairs)
    tolerance = context['maxBoundaryGap']
    result.update(maxBoundaryGap=tolerance, passed=result['maxDistance'] <= tolerance,
                  acceptance='explicit authored source-unit tolerance' if len(pairs) else 'not_applicable_source_detached',
                  sampleTimes=sample_times.tolist(), keyCount=len(times), sampleCount=len(sample_times),
                  boundaryApplicable=bool(len(pairs)), contactProven=False,
                  proof='final-glb-key-and-midpoint-samples')
    if not result['passed']:
        raise ValueError(f"delivered ownership gap {result['maxDistance']:.9g} exceeds {tolerance:.9g}")
    return result
