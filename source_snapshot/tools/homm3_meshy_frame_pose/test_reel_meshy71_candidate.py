"""Focused tests for consuming the paired registration as a source report."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reel_meshy71_candidate as reel


class SimilarityTests(unittest.TestCase):
    def test_candidate_motion_mode_must_be_explicit(self):
        action = next(
            action
            for action in reel.build_parser()._actions
            if action.dest == "candidate_motion"
        )
        self.assertTrue(action.required)
        self.assertIsNone(action.default)

    def test_reel_unit_uses_master_identity(self):
        self.assertEqual(reel.reel_unit({"unit": "toa_ogre_brute"}, Path("wrong-pilot")), "toa_ogre_brute")
        self.assertEqual(reel.reel_unit({}, Path("h3_wraith")), "h3_wraith")

    def test_load_similarity_accepts_direct_registration(self):
        payload = {
            "schema": "homm3.static-bind-registration.v1",
            "views": {
                "candidates": [{
                    "id": "idle0_identity",
                    "skeletonSimilarity": {
                        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "scale": 0.934625825,
                        "translation": [-0.04, 0.80, -0.05],
                        "policy": "idle_frame0_meshy_source_identity",
                    },
                }]
            },
            "acceptance": {"selectedCandidateId": "idle0_identity"},
        }
        path = Path("test_direct_registration.json")
        with patch.object(Path, "read_text", return_value=json.dumps(payload)):
            similarity = reel.load_similarity(path)
        self.assertAlmostEqual(similarity.scale, 0.934625825)
        self.assertEqual(similarity.policy, "idle_frame0_meshy_source_identity")
        self.assertEqual(similarity.source, str(path.resolve()).replace("\\", "/"))

    def test_explicit_selection_cannot_fall_back_to_only_candidate(self):
        for selected in (None, "missing"):
            payload = {"schema": "homm3.static-bind-registration.v1",
                       "views": {"candidates": [{"id": "only"}]},
                       "acceptance": {"selectedCandidateId": selected}}
            with self.subTest(selected=selected), patch.object(Path, "read_text", return_value=json.dumps(payload)):
                with self.assertRaisesRegex(ValueError, "selected registration candidate"):
                    reel.load_similarity(Path("registration.json"))

    def test_ambiguous_selection_is_not_silently_chosen(self):
        payload = {"schema": "homm3.static-bind-registration.v1",
                   "views": {"candidates": [{"id": "same"}, {"id": "same"}]},
                   "acceptance": {"selectedCandidateId": "same"}}
        with patch.object(Path, "read_text", return_value=json.dumps(payload)):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                reel.load_similarity(Path("registration.json"))

    def test_static_schema_cannot_bypass_selection_with_legacy_field(self):
        payload = {"schema": "homm3.static-bind-registration.v1",
                   "similarity": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                  "scale": 1, "translation": [0, 0, 0],
                                  "policy": "legacy", "source": "legacy.json"},
                   "views": {"candidates": [{"id": "only"}]}}
        with patch.object(Path, "read_text", return_value=json.dumps(payload)):
                with self.assertRaisesRegex(ValueError, "selected registration candidate"):
                    reel.load_similarity(Path("registration.json"))

    def test_saved_retargeted_motion_does_not_require_candidate_similarity(self):
        with patch.object(reel, "load_similarity", side_effect=AssertionError("must not load")):
            self.assertIsNone(
                reel.load_candidate_similarity(Path("fitter_report.json"), "saved-retargeted")
            )

    def test_saved_motion_is_sliced_by_non_bookend_clip_span(self):
        master = {
            "frames": [{"globalIndex": index} for index in range(4)],
            "segments": [
                {"clipKey": "g02_idle", "role": "cycle", "globalStart": 0, "globalEnd": 2},
                {"clipKey": "g02_idle", "role": "bookend", "globalStart": 2, "globalEnd": 3},
                {"clipKey": "g00_move", "role": "cycle", "globalStart": 3, "globalEnd": 4},
            ],
        }
        motion = {key: np.arange(4 * 1 * 3, dtype=float).reshape(4, 1, 3) for key in ("frame_joints", "offsets")}
        motion["rotations"] = np.zeros((4, 1, 3, 3), dtype=float)
        sliced = reel.saved_motion_for_clip(motion, master, "g00_move")
        self.assertEqual(sliced["frame_joints"].shape, (1, 1, 3))
        np.testing.assert_array_equal(sliced["frame_joints"][0], motion["frame_joints"][3])

    def test_saved_motion_loader_rejects_wrong_frame_contract(self):
        class Archive:
            def __enter__(self):
                return {
                    "frame_joints": np.zeros((3, 1, 3)),
                    "rotations": np.zeros((3, 1, 3, 3)),
                    "offsets": np.zeros((3, 1, 3)),
                }

            def __exit__(self, *_args):
                return False

        master = {"frames": [{"globalIndex": index} for index in range(4)]}
        with patch.object(Path, "is_file", return_value=True), patch.object(reel.np, "load", return_value=Archive()):
            with self.assertRaisesRegex(SystemExit, "does not match"):
                reel.load_saved_motion(Path("motion.npz"), master, 1)


if __name__ == "__main__":
    unittest.main()
