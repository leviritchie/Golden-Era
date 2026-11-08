import unittest
import numpy as np
from capture_stage_metrics import analyze


class CaptureStageTests(unittest.TestCase):
    def run_stages(self, capture, reference, parents):
        offsets = reference.copy()
        offsets[1:] -= reference[np.asarray(parents)[1:]]
        return analyze(capture, reference, offsets, np.asarray(parents), ['root', 'a', 'b'], ('root', 'a', 'b'))

    def test_rigid_turn_and_translation_preserve_unsmoothed_source(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.]])
        rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        capture = np.stack([reference, reference @ rotation.T + [2., 3., 1.]])
        before = capture.copy()
        result = self.run_stages(capture, reference, [-1, 0, 1])
        np.testing.assert_allclose(result['stages']['unsmoothed_same_rest_fk'], capture, atol=1e-12)
        np.testing.assert_array_equal(capture, before)

    def test_variable_lengths_are_separate_from_direction_loss(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.]])
        capture = np.stack([reference, reference * 2])
        result = self.run_stages(capture, reference, [-1, 0, 1])
        for key in ('fixed_lengths_independent_edges', 'unsmoothed_same_rest_fk', 'current_same_rest_fk'):
            np.testing.assert_allclose(result['stages'][key], np.stack([reference, reference]), atol=1e-12)
        self.assertGreater(np.max(np.abs(result['stages']['raw'] - result['stages']['fixed_lengths_independent_edges'])), .9)

    def test_branch_angle_change_cannot_fit_rigid_parent(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        pose = reference.copy()
        pose[2] = [2 ** -.5, 2 ** -.5, 0.]
        result = self.run_stages(np.stack([reference, pose]), reference, [-1, 0, 0])
        np.testing.assert_allclose(result['stages']['fixed_lengths_independent_edges'][1], pose, atol=1e-12)
        rigid = result['stages']['unsmoothed_same_rest_fk'][1]
        self.assertGreater(np.max(np.abs(rigid - pose)), .2)
        self.assertAlmostEqual(float(np.dot(rigid[1] - rigid[0], rigid[2] - rigid[0])), 0., places=12)

    def test_nonfinite_capture_rejected(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.]])
        capture = reference[None].copy()
        capture[0, 1, 0] = np.nan
        with self.assertRaises(ValueError):
            self.run_stages(capture, reference, [-1, 0, 1])

    def test_nonzero_reference_origin_is_not_lost(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.]]) + [3., -2., 4.]
        offsets = reference.copy()
        offsets[0] = 0.
        offsets[1:] -= reference[[0, 1]]
        result = analyze(reference[None], reference, offsets, np.array([-1, 0, 1]), ['root', 'a', 'b'], ('root', 'a', 'b'))
        for stage in result['stages'].values():
            np.testing.assert_allclose(stage[0], reference, atol=1e-12)


if __name__ == '__main__':
    unittest.main()
