import unittest
import numpy as np
from coincident_bind_candidate import build_candidate
from donor_eagle import compute_rest_joints, skin_dense
from local_rotation_capture_motion import reconstruct_local_rotation


def fixture():
    offsets = np.array([[.1, .2, .3], [.4, .2, 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    parents = np.array([-1, 0, 1, 1, 1])
    rest = compute_rest_joints(offsets, parents)
    inverse = np.repeat(np.eye(4)[None], 5, axis=0)
    inverse[:, :3, 3] = -rest
    capture_offsets = offsets.copy()
    capture_offsets[:2] = 0.
    return dict(vertices=np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
        triangles=np.array([[0, 1, 2]]), uvs=np.zeros((3, 2)), albedo=np.zeros((2, 2, 3), dtype=np.uint8),
        names=np.array(['root', 'hub', 'a', 'b', 'c']), parents=parents, offsets=offsets,
        captureOffsets=capture_offsets, inverseBind=inverse, restAnchors=rest, restWorld=rest,
        weights=np.array([[1., 0., 0., 0., 0.], [.5, .2, .3, 0., 0.], [0., .5, 0., .5, 0.]]),
        regions=np.array(['body', 'body', 'body']))


class CoincidentBindTests(unittest.TestCase):
    def test_joint_positions_and_skin_owner_share_terminal(self):
        original = fixture()
        snapshots = {k: v.copy() for k, v in original.items()}
        candidate = build_candidate(original)['skin']
        np.testing.assert_array_equal(candidate['offsets'][1], [0., 0., 0.])
        np.testing.assert_allclose(candidate['restWorld'][0], original['restWorld'][1])
        np.testing.assert_array_equal(candidate['restWorld'][1:], original['restWorld'][1:])
        np.testing.assert_array_equal(candidate['weights'][:, 0], 0.)
        np.testing.assert_allclose(candidate['weights'][:, 1], original['weights'][:, :2].sum(1))
        for key in original:
            np.testing.assert_array_equal(original[key], snapshots[key])
        for key in ('vertices', 'triangles', 'uvs', 'albedo', 'captureOffsets', 'parents', 'names', 'regions'):
            np.testing.assert_array_equal(candidate[key], original[key])

    def test_rigid_turn_preserves_weighted_mesh_not_only_joints(self):
        original = fixture()
        candidate = build_candidate(original)['skin']
        ref = compute_rest_joints(original['captureOffsets'], original['parents'])
        rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        motion = reconstruct_local_rotation(capture_positions=np.stack([ref, ref @ rotation.T]),
            capture_reference_positions=ref, capture_offsets=original['captureOffsets'],
            fitted_offsets=candidate['offsets'], parents=original['parents'], names=list(original['names']),
            hub_names=tuple(original['names']))
        q = motion['staticBindRotation']
        root = candidate['restWorld'][0]
        expected = (original['vertices']-root) @ (q @ rotation @ q.T).T + root
        posed = skin_dense(candidate['vertices'], candidate['weights'], motion['jointWorld'][1], candidate['inverseBind'])
        np.testing.assert_allclose(posed, expected, atol=1e-10)
        position_only = skin_dense(candidate['vertices'], original['weights'], motion['jointWorld'][1], candidate['inverseBind'])
        self.assertGreater(np.max(np.abs(position_only-expected)), .1)

    def test_no_zero_edges_is_exact_noop(self):
        original = fixture()
        original['captureOffsets'] = original['offsets'].copy()
        candidate = build_candidate(original)['skin']
        for key in original:
            np.testing.assert_array_equal(candidate[key], original[key])

    def test_observable_sibling_prevents_blind_merging(self):
        original = fixture()
        original['parents'][2] = 0
        rest = compute_rest_joints(original['offsets'], original['parents'])
        original['restWorld'] = rest.copy()
        original['restAnchors'] = rest.copy()
        original['inverseBind'][:, :3, 3] = -rest
        with self.assertRaisesRegex(ValueError, 'child|ambiguous|serial|branch'):
            build_candidate(original)

    def test_zero_fork_rejected(self):
        original = fixture()
        original['captureOffsets'][2:4] = 0.
        with self.assertRaisesRegex(ValueError, 'fork|ambiguous|serial|branch'):
            build_candidate(original)

    def test_serial_chain_merges_once(self):
        original = fixture()
        original['parents'] = np.array([-1, 0, 1, 2, 2])
        original['captureOffsets'][2] = 0.
        rest = compute_rest_joints(original['offsets'], original['parents'])
        original['restWorld'] = rest.copy()
        original['restAnchors'] = rest.copy()
        original['inverseBind'][:, :3, 3] = -rest
        result = build_candidate(original)
        candidate = result['skin']
        self.assertEqual(result['report']['groups'][0]['members'], ['root', 'hub', 'a'])
        np.testing.assert_array_equal(candidate['weights'][:, :2], 0.)
        np.testing.assert_allclose(candidate['weights'][:, 2], original['weights'][:, :3].sum(1))
        np.testing.assert_array_equal(candidate['restWorld'][2:], rest[2:])

    def test_invalid_inverse_bind_rejected_even_without_components(self):
        original = fixture()
        original['captureOffsets'] = original['offsets'].copy()
        original['inverseBind'][2, 0, 3] += .1
        with self.assertRaises(ValueError):
            build_candidate(original)

    def test_unnormalized_weight_rejected(self):
        original = fixture()
        original['weights'][0, 0] = .5
        with self.assertRaises(ValueError):
            build_candidate(original)

    def test_nonfinite_weight_rejected(self):
        original = fixture()
        original['weights'][0, 0] = np.nan
        with self.assertRaises(ValueError):
            build_candidate(original)


if __name__ == '__main__':
    unittest.main()
