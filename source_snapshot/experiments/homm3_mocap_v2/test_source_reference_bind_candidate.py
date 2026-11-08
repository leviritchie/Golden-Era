import unittest

import numpy as np

from source_reference_bind_candidate import build_source_reference_candidate, _similarity
from local_rotation_capture_motion import reconstruct_local_rotation
from donor_eagle import skin_dense


def fixture():
    parents = np.array([-1, 0, 1, 1], dtype=np.int64)
    offsets = np.array([[1., 2., 3.], [0., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
    rest = np.array([[1., 2., 3.], [1., 2., 3.], [2., 2., 3.], [1., 4., 3.]])
    inverse = np.repeat(np.eye(4)[None], 4, axis=0)
    inverse[:, :3, 3] = -rest
    return {
        "vertices": np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
        "triangles": np.array([[0, 1, 2]], dtype=np.int64), "uvs": np.zeros((3, 2)),
        "albedo": np.zeros((2, 2, 3), dtype=np.uint8),
        "names": np.array(["root", "hub", "a", "b"]), "parents": parents,
        "offsets": offsets, "restWorld": rest, "restAnchors": rest.copy(),
        "captureOffsets": offsets.copy(), "inverseBind": inverse,
        "weights": np.array([[1., 0., 0., 0.], [.5, .5, 0., 0.], [0., 0., 1., 0.]]),
        "regions": np.array(["body", "body", "body"]),
    }


class SourceReferenceBindCandidateTests(unittest.TestCase):
    def test_similarity_fit_and_surface_invariants(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        reference = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
        result = build_source_reference_candidate(original, reference, ("root", "a", "b"))
        skin = result["skin"]
        self.assertAlmostEqual(result["report"]["transform"]["scale"], 1.0)
        np.testing.assert_allclose(skin["restWorld"][0], original["restWorld"][0])
        np.testing.assert_allclose(skin["restWorld"][2], original["restWorld"][2])
        np.testing.assert_array_equal(skin["vertices"], original["vertices"])
        np.testing.assert_array_equal(skin["triangles"], original["triangles"])
        np.testing.assert_array_equal(skin["captureOffsets"], original["captureOffsets"])
        self.assertLess(result["report"]["similarityResidualMax"], 1e-12)

    def test_rotated_scaled_reference_registration(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        q = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        source = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
        source = 2.0 * (source @ q.T) + np.array([4., -1., 2.])
        result = build_source_reference_candidate(original, source, ("root", "a", "b"))
        self.assertAlmostEqual(result["report"]["transform"]["scale"], .5, places=10)
        self.assertLess(result["report"]["similarityResidualMax"], 1e-12)

    def test_collapsed_or_negative_inputs_rejected(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        collapsed = np.zeros((4, 3))
        with self.assertRaisesRegex(ValueError, "collapsed|observable dimensions"):
            build_source_reference_candidate(original, collapsed, ("root", "a", "b"))
        separated = np.array([[0., 0., 0.], [1., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
        with self.assertRaisesRegex(ValueError, "source-zero"):
            build_source_reference_candidate(original, separated, ("root", "a", "b"))

    def test_collinear_source_hubs_are_rejected(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        collinear = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [2., 0., 0.]])
        with self.assertRaisesRegex(ValueError, "observable dimensions"):
            build_source_reference_candidate(original, collinear, ("root", "a", "b"))

    def test_mirrored_target_keeps_positive_signed_scale(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        source = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
        # An anisotropic source cannot fit exactly with one positive scale.
        mirrored = source.copy()
        mirrored[:, 0] *= -2.0
        result = build_source_reference_candidate(original, mirrored, ("root", "a", "b"))
        self.assertGreater(result["report"]["transform"]["scale"], 0.0)
        self.assertFalse(result["report"]["invariants"]["reflection"])
        self.assertGreater(result["report"]["similarityResidualMax"], 1e-6)

    def test_full_rank_mirror_uses_signed_optimal_scale(self):
        source = np.array([[0., 0., 0.], [1., 0., 0.], [0., 2., 0.], [0., 0., 3.]])
        target = source * [-1., 1., 1.]
        scale, q, translation, residual = _similarity(source, target)
        x, y = source-source.mean(0), target-target.mean(0)
        self.assertAlmostEqual(np.linalg.det(q), 1.)
        self.assertAlmostEqual(scale, np.sum(x * (y @ q)) / np.sum(x*x))
        self.assertLess(scale, 1.)
        self.assertGreater(residual, .1)

    def test_rigid_capture_drives_canonical_weighted_mesh(self):
        original = fixture()
        source = (original['restWorld'] - original['restWorld'][0]) / 2.
        result = build_source_reference_candidate(original, source, ('root', 'a', 'b'))
        skin = result['skin']
        r = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        motion = reconstruct_local_rotation(capture_positions=np.stack([source, source @ r.T]),
            capture_reference_positions=source, capture_offsets=skin['captureOffsets'],
            fitted_offsets=skin['offsets'], parents=skin['parents'], names=list(skin['names']),
            hub_names=('root', 'a', 'b'))
        q = motion['staticBindRotation']
        root = skin['restWorld'][0]
        posed = skin_dense(skin['vertices'], skin['weights'], motion['jointWorld'][1], skin['inverseBind'])
        expected = (skin['vertices'] - root) @ (q @ r @ q.T).T + root
        np.testing.assert_allclose(posed, expected, atol=1e-10)

    def test_input_is_immutable(self):
        original = fixture()
        original["captureOffsets"][1] = 0.0
        snapshot = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in original.items()}
        reference = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [0., 2., 0.]])
        build_source_reference_candidate(original, reference, ("root", "a", "b"))
        for key, value in snapshot.items():
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(original[key], value)


if __name__ == "__main__":
    unittest.main()
