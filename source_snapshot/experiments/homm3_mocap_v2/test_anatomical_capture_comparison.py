import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np

from coincident_bind_candidate import build_candidate
from run_anatomical_capture_comparison import validate_inputs, rigid_weighted_controls
from test_anatomical_capture_motion import fixture
from anatomical_capture_motion import reconstruct_anatomical_capture


class AnatomicalComparisonPreflightTests(unittest.TestCase):
    def test_rigid_control_exercises_motion_and_detects_bad_reconstruction(self):
        parents, offsets, rest, names = fixture()
        inverse = np.broadcast_to(np.eye(4), (len(names), 4, 4)).copy()
        inverse[:, :3, 3] = -rest
        skin = dict(vertices=rest + [.1, .2, .3], weights=np.eye(len(names)),
                    offsets=offsets, captureOffsets=offsets, parents=parents,
                    inverseBind=inverse, names=names)
        hubs = ('J1', 'J2', 'J5')
        good = rigid_weighted_controls(skin, rest, hubs)
        self.assertTrue(good['passed'])
        self.assertTrue(good['motionReconstructorExercised'])
        self.assertEqual(good['capturePoseCount'], 13)

        def corrupt(**kwargs):
            motion = reconstruct_anatomical_capture(**kwargs)
            motion['jointWorld'][1, 1, 0, 3] += .5
            return motion

        with patch('anatomical_capture_motion.reconstruct_anatomical_capture', side_effect=corrupt) as solver:
            with self.assertRaisesRegex(ValueError, 'rigid weighted control failed'):
                rigid_weighted_controls(skin, rest, hubs)
        solver.assert_called_once()

    def test_corpus_identity_mismatch_fails_before_registration_reads(self):
        with self.assertRaisesRegex(ValueError, "corpus unit"):
            validate_inputs({}, {"unit": "other"}, "h3_thunderbird", Path("missing"), Path("missing"), Path("missing"))

    def test_canonical_builder_does_not_mutate_original(self):
        skin = {
            "vertices": np.array([[0., 0., 0.]]), "triangles": np.array([[0, 0, 0]], dtype=np.int64),
            "uvs": np.zeros((1, 2)), "albedo": np.zeros((1, 3), dtype=np.uint8),
            "names": np.array(["Hips"]), "parents": np.array([-1], dtype=np.int64),
            "offsets": np.zeros((1, 3)), "captureOffsets": np.zeros((1, 3)),
            "inverseBind": np.eye(4)[None], "weights": np.ones((1, 1)), "regions": np.array(["body"]),
        }
        before = {key: value.copy() if hasattr(value, "copy") else value for key, value in skin.items()}
        candidate = build_candidate(skin)["skin"]
        self.assertTrue(np.array_equal(skin["weights"], before["weights"]))
        self.assertTrue(np.array_equal(skin["parents"], before["parents"]))
        self.assertIsNot(candidate, skin)


if __name__ == "__main__":
    unittest.main()
