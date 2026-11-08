import unittest
import numpy as np
import torch
from run_global_motion_alignment import alignment_seeds
from global_motion_alignment import build_alignment_matrix


class AlignmentSeedTests(unittest.TestCase):
    def test_rotation_seeds_cover_proper_cube_group(self):
        seeds = alignment_seeds('rotation')
        self.assertEqual(len(seeds), 24)
        matrices = [build_alignment_matrix(torch.tensor(seed), mode='rotation',
                    mesh_span=2., pivot=[0., 0., 0.])[0][:3, :3].numpy() for seed in seeds]
        np.testing.assert_array_equal(seeds[0], 0.)
        self.assertEqual(len({tuple(np.round(matrix, 8).flatten()) for matrix in matrices}), 24)
        for matrix in matrices:
            self.assertAlmostEqual(np.linalg.det(matrix), 1.)
            np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=1e-12)

    def test_similarity_scale_seeds_are_positive_and_distinct(self):
        seeds = alignment_seeds('similarity')
        self.assertEqual(len(seeds), 72)
        scales = [float(build_alignment_matrix(torch.tensor(seed), mode='similarity',
                  mesh_span=2., pivot=[0., 0., 0.])[1]['scale']) for seed in seeds[:3]]
        np.testing.assert_allclose(scales, [1., .625, 1.6], atol=1e-12)


if __name__ == '__main__':
    unittest.main()
