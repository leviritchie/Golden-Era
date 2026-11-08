import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from body_relative_capture_motion import reconstruct_body_relative
from reconstruct_adapted import reconstruct_adapted
from mesh_preview import fk_world_matrices


class BodyRelativeTests(unittest.TestCase):
    def inputs(self):
        parents = np.array([-1, 0, 0, 1, 2])
        reference = np.array([[0., 0, 0], [1, .2, 0], [-1, .3, 0], [1.2, 1, .5], [-1.2, 1, -.3]])
        fitted = np.array([[.2, .1, .3], [.5, .8, .2], [-.5, .7, .1], [.9, 1.1, .8], [-.8, 1.2, -.7]])
        offsets = lambda p: np.vstack([p[0], p[1:] - p[parents[1:]]])
        names = ['root', 'left', 'right', 'tip_left', 'tip_right']
        return dict(capture_positions=reference[None].copy(), capture_reference_positions=reference,
            capture_offsets=offsets(reference), fitted_offsets=offsets(fitted), parents=parents,
            names=names, hub_names=tuple(names))

    def test_rigid_motion_preserves_all_pair_distances_and_translation(self):
        args = self.inputs()
        ref = args['capture_reference_positions']
        rotations = Rotation.from_rotvec([[0, 0, 0], [0, 0, 1.5], [.8, .4, -.2]]).as_matrix()
        travel = np.array([[0., 0, 0], [.2, -.4, .3], [-.1, .2, .4]])
        args['capture_positions'] = np.einsum('tij,kj->tki', rotations, ref) + travel[:, None]
        before = {key: value.copy() for key, value in args.items() if isinstance(value, np.ndarray)}
        result = reconstruct_body_relative(**args)
        rest = result['fittedRest']
        q = result['wholeBodyRotation']
        expected = np.einsum('tij,kj->tki', q[None] @ rotations @ q.T[None], rest-rest[0]) + rest[0] + (travel @ q.T)[:, None]
        np.testing.assert_allclose(result['positions'], expected, atol=1e-10)
        self.assertLess(result['fixedLengthErrorMax'], 1e-10)
        self.assertTrue(result['clipFrame0IsBind'])
        for key, value in before.items():
            np.testing.assert_array_equal(args[key], value)
        for index in range(len(rotations)):
            rebuilt = fk_world_matrices(local_rotation=result['localRotation'][index],
                local_translation=result['localTranslation'][index], parents=args['parents'],
                root_world=result['positions'][index, 0])
            np.testing.assert_allclose(rebuilt, result['jointWorld'][index], atol=1e-10)

    def test_articulation_is_not_replaced_by_body_rotation_only(self):
        args = self.inputs()
        args['hub_names'] = ('root', 'left', 'right')
        args['capture_positions'] = np.repeat(args['capture_positions'], 2, axis=0)
        args['capture_positions'][1, 3] += [0, 0, .6]
        result = reconstruct_body_relative(**args)
        self.assertGreater(np.linalg.norm(result['positions'][1, 3]-result['positions'][0, 3]), .01)
        np.testing.assert_allclose(result['targetBodyRotation'], np.eye(3)[None].repeat(2, axis=0), atol=1e-10)

    def test_rejects_degenerate_body_hubs(self):
        args = self.inputs()
        args['hub_names'] = ('root', 'left')
        with self.assertRaises(ValueError):
            reconstruct_body_relative(**args)

    def test_translation_is_not_bind_and_missing_hubs_reject(self):
        args = self.inputs()
        args['capture_positions'] += [.3, .4, -.2]
        self.assertFalse(reconstruct_body_relative(**args)['clipFrame0IsBind'])
        args['hub_names'] = ('root', 'left', 'missing')
        with self.assertRaisesRegex(ValueError, 'known hub'):
            reconstruct_body_relative(**args)

    def test_combined_body_turn_preserves_the_same_residual_articulation(self):
        args = self.inputs()
        args['hub_names'] = ('root', 'left', 'right')
        args['capture_positions'][0, 3] += [0, .2, .6]
        articulated = reconstruct_body_relative(**args)
        rotation = Rotation.from_rotvec([.5, -.8, .3]).as_matrix()
        args['capture_positions'] = args['capture_positions'] @ rotation.T
        combined = reconstruct_body_relative(**args)
        q = combined['wholeBodyRotation']
        root = combined['fittedRest'][0]
        expected = (articulated['positions']-root) @ (q @ rotation @ q.T).T + root
        np.testing.assert_allclose(combined['positions'], expected, atol=1e-10)

    def test_near_collinear_hubs_reject_and_nonrigidity_is_reported(self):
        args = self.inputs()
        args['capture_positions'][0, 3] += [0, 0, .8]
        report = reconstruct_body_relative(**args)['bodyDiagnostics']
        self.assertGreater(report['relativeRigidFitRms'][0], .01)
        self.assertFalse(report['rigidHubAssumptionValidated'])
        args = self.inputs()
        args['hub_names'] = ('root', 'left', 'right')
        args['capture_positions'][0, :3] = [[0, 0, 0], [1, 0, 0], [-1, 1e-9, 0]]
        with self.assertRaisesRegex(ValueError, 'ill-conditioned'):
            reconstruct_body_relative(**args)


if __name__ == '__main__':
    unittest.main()
