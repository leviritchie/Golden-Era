"""Final serialized skin replay, not a report-only acceptance check."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.spatial.transform import Rotation

import delivery_ownership as subject
from eagle_glb import matrices_to_xyzw, write_skinned_glb
from experiments.homm3_mocap_v2.assemble_ingame_delivery import _wrap_orientation, _read_glb, _write_glb


class DeliveryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=subject.ROOT / 'artifacts/homm3_mocap_v2/tmp')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, angle=0, translation=0.):
        names = ['Root'] + [f'Joint{i}' for i in range(1, 8)]
        parents = np.array([-1] + [0] * 7)
        vertices = np.array([[1., 0, 0], [0, 1., 0], [0, 0, 0], [1., 0, 0]])
        uvs = np.array([[0., 0], [0, 1.], [1., 0], [0., 0]])
        triangles = np.array([[0, 1, 2], [3, 2, 1]])
        weights = np.zeros((4, 8))
        weights[:, 0] = 1
        weights[0] = .125  # Joint7 resides in the second influence set.
        rotations = np.broadcast_to(np.eye(3), (2, 8, 3, 3)).copy()
        rotations[1, 7] = Rotation.from_rotvec([0, 0, angle]).as_matrix()
        offsets = np.zeros((8, 3))
        offsets[1:, 1] = translation
        ibm = np.broadcast_to(np.eye(4), (8, 4, 4)).copy()
        ibm[:, :3, 3] = -offsets
        path = self.root / f'clip_{angle}.glb'
        write_skinned_glb(path, names=names, parents=parents,
                          rest_local_rotation=rotations[0], rest_local_translation=offsets,
                          inverse_bind=ibm,
                          vertices=vertices, triangles=triangles, uvs=uvs,
                          albedo=np.full((2, 2, 4), 255, dtype=np.uint8), weights=weights,
                          animation={'name': 'Unit_AttackFront', 'times': np.array([0., 1.]),
                                     'rotations': matrices_to_xyzw(rotations)})
        prepared = dict(vertices=vertices, names=names, parents=parents, uvs=uvs, triangles=triangles,
                        offsets=offsets, inverseBind=ibm,
                        sourceVertexIds=np.array([0, 1, 2, 0]), ownershipBoundaryPairs=np.array([[0, 3]]))
        return path, {'prepared': prepared, 'maxBoundaryGap': .05}

    def test_raw_passes_but_changed_final_rotation_fails(self):
        raw, context = self.fixture()
        result = subject.replay_boundaries(raw, context)
        self.assertEqual(result['sampleTimes'], [0., .5, 1.])
        final, context = self.fixture(1.)
        with self.assertRaisesRegex(ValueError, 'gap .* exceeds'):
            subject.replay_boundaries(final, context)

    def test_second_influence_set_is_evaluated(self):
        path, context = self.fixture(1.)
        context['maxBoundaryGap'] = 1.
        result = subject.replay_boundaries(path, context)
        self.assertAlmostEqual(result['maxDistance'], .25 * np.sin(.5), places=6)

    def test_rigid_wrapper_preserves_gaps_and_scale_is_refused(self):
        path, context = self.fixture(.2)
        baseline = subject.replay_boundaries(path, context)
        _wrap_orientation(path)
        self.assertEqual(subject.replay_boundaries(path, context)['maxDistance'], baseline['maxDistance'])
        doc, blob = _read_glb(path)
        doc['nodes'][-1]['scale'] = [2, 2, 2]
        _write_glb(path, doc, blob)
        with self.assertRaisesRegex(ValueError, 'unit-scale'):
            subject.replay_boundaries(path, context)

    def test_changed_topology_is_refused(self):
        path, context = self.fixture()
        context['prepared']['triangles'][0] = [1, 0, 2]
        with self.assertRaisesRegex(ValueError, 'topology'):
            subject.replay_boundaries(path, context)

    def test_changed_authored_bind_is_refused(self):
        path, context = self.fixture()
        for key in ('offsets', 'inverseBind'):
            previous = context['prepared'][key].copy()
            context['prepared'][key].flat[0] += .1
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'authored bind'):
                subject.replay_boundaries(path, context)
            context['prepared'][key] = previous

    def test_prepared_joint_order_and_double_json_offsets(self):
        path, context = self.fixture(translation=.123456789123)
        p = context['prepared']
        order = np.array([0, 7, 6, 5, 4, 3, 2, 1])
        p['names'] = [p['names'][i] for i in order]
        for key in ('offsets', 'inverseBind'):
            p[key] = p[key][order]
        # All siblings retain Root as their parent in either enumeration.
        self.assertTrue(subject.replay_boundaries(path, context)['passed'])

    def test_nonjoint_transform_between_joints_is_refused(self):
        path, context = self.fixture()
        doc, blob = _read_glb(path)
        joint = doc['skins'][0]['joints'][7]
        root = doc['skins'][0]['joints'][0]
        doc['nodes'][root]['children'].remove(joint)
        doc['nodes'][root]['children'].append(len(doc['nodes']))
        doc['nodes'].append({'name': 'UnexpectedIntermediate', 'translation': [1, 0, 0], 'children': [joint]})
        _write_glb(path, doc, blob)
        with self.assertRaisesRegex(ValueError, 'between joints'):
            subject.replay_boundaries(path, context)

    def test_animated_ancestor_reaches_descendant_influences(self):
        path, context = self.fixture(1.)
        doc, blob = _read_glb(path)
        joints = doc['skins'][0]['joints']
        doc['nodes'][joints[0]]['children'].remove(joints[7])
        doc['nodes'][joints[6]]['children'] = [joints[7]]
        for channel in doc['animations'][0]['channels']:
            target = channel['target']
            if target['node'] == joints[7]:
                target['node'] = joints[6]
            elif target['node'] == joints[6]:
                target['node'] = joints[7]
        _write_glb(path, doc, blob)
        context['prepared']['parents'][7] = 6
        context['maxBoundaryGap'] = 1.
        self.assertAlmostEqual(subject.replay_boundaries(path, context)['maxDistance'], .5 * np.sin(.5), places=6)

    def test_missing_masked_sidecar_reference_cannot_skip_gate(self):
        from tools.validate_homm3_mocap_delivery_contract import _validate_ownership_replay
        path = self.root / 'skin.json'
        path.write_text('{}')
        errors = []
        with patch('experiments.homm3_mocap_v2.delivery_ownership.ownership_context',
                   return_value={'reference': {'sha256': 'current'}}):
            _validate_ownership_replay({'skinWeights': {'path': str(path)}},
                                       {'labSid': 'test'}, self.root, [], errors)
        self.assertTrue(any('missing or stale' in error for error in errors))

    def test_changed_pair_reference_is_refused(self):
        from tools.validate_homm3_mocap_delivery_contract import _validate_ownership_replay
        path = self.root / 'skin.json'
        path.write_text(json.dumps({'preparedOwnership': {'sha256': 'changed-pairs'}}))
        errors = []
        with patch('experiments.homm3_mocap_v2.delivery_ownership.ownership_context',
                   return_value={'reference': {'sha256': 'source-replayed-pairs'}}):
            _validate_ownership_replay({'skinWeights': {'path': str(path)}},
                                       {'labSid': 'test'}, self.root, [], errors)
        self.assertTrue(any('missing or stale' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
