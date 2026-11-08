import unittest
from unittest.mock import patch
from pathlib import Path
import json
import numpy as np

from compare_aligned_capture_motion import read_skin
from coincident_bind_candidate import build_candidate
from asset_profiles import get_profile
from joint_axis_calibration import JointAxisCalibration
from test_anatomical_capture_motion import fixture
from run_joint_axis_calibration import HELDOUT_CLIPS, partition_clips, source_motion, verify_calibration


class JointAxisRunnerTests(unittest.TestCase):
    def test_rigid_verifier_rejects_corrupted_learner_output(self):
        parents, offsets, rest, names = fixture()
        inverse = np.broadcast_to(np.eye(4), (len(names), 4, 4)).copy()
        inverse[:, :3, 3] = -rest
        skin = dict(vertices=rest + [.1, .2, .3], weights=np.eye(len(names)),
                    offsets=offsets, captureOffsets=offsets, parents=parents,
                    inverseBind=inverse, names=names)
        raw = np.full((len(names) - 1, 3), .3)
        original_forward = JointAxisCalibration.forward

        def corrupt(model):
            world = original_forward(model)
            world[1, 1, 0, 3] += .5
            return world

        with patch.object(JointAxisCalibration, 'forward', corrupt):
            with self.assertRaisesRegex(ValueError, 'rigid mesh control failed'):
                verify_calibration(skin, rest, ('J1', 'J2', 'J5'), raw)

    def rows(self):
        return [
            {"key": "g00_move", "frames": ["a", "b"]},
            {"key": "g11_attack_up", "frames": ["c", "d", "e"]},
            {"key": "g12_attack_front", "frames": ["f"]},
            {"key": "g13_attack_down", "frames": ["g", "h"]},
        ]

    def test_partition_excludes_entire_required_attack_clips(self):
        train, heldout, slices = partition_clips(self.rows())
        self.assertEqual(train, [0, 1, 5])
        self.assertEqual(heldout, [2, 3, 4, 6, 7])
        self.assertEqual(slices["g11_attack_up"], slice(2, 5))
        self.assertEqual(slices["g13_attack_down"], slice(6, 8))
        self.assertTrue(set(train).isdisjoint(heldout))
        self.assertEqual(sorted(train + heldout), list(range(8)))

    def test_partition_rejects_missing_or_duplicate_clip(self):
        with self.assertRaises(ValueError):
            partition_clips([{"key": "g00_move", "frames": ["a"]}, {"key": "g11_attack_up", "frames": ["b"]}])
        rows = self.rows() + [{"key": "g00_move", "frames": ["z"]}]
        with self.assertRaises(ValueError):
            partition_clips(rows)

    def test_actual_thunderbird_source_rigid_control(self):
        root = Path(__file__).resolve().parents[2]
        skin_path = root / "artifacts/homm3_mocap_v2/shape_preserved/h3_thunderbird/preparation/mapped_skin_v2/research_skin.npz"
        registration = root / "artifacts/homm3_mocap_v2/skin_mesh_pilot/thunderbird/registration_v2"
        skin = build_candidate(read_skin(skin_path))['skin']
        reference = np.asarray(json.loads((registration / "idle_reference.json").read_text())["referencePositions"])
        hubs = tuple(get_profile('h3_thunderbird')['wholeBodyHubs'])
        raw = np.random.default_rng(42).normal(size=(skin['weights'].shape[1] - 1, 3))
        result = verify_calibration(skin, reference, hubs, raw)
        self.assertTrue(result["passed"])
        self.assertLess(result["rigidErrorMax"], 1e-6)


if __name__ == "__main__":
    unittest.main()
