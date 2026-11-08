import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_pose_corrective_pilot import split_frames, checkpoint_improves


class PoseCorrectivePilotSplitTests(unittest.TestCase):
    def test_checkpoint_rejects_image_or_safety_tradeoff(self):
        initial = dict(image=1.,surface=2.,idle=.01)
        self.assertTrue(checkpoint_improves(dict(image=.9,surface=1.9,idle=.009),1.,initial))
        for metrics in (dict(image=1.1,surface=1.,idle=0.),
                        dict(image=.9,surface=2.1,idle=0.),
                        dict(image=.9,surface=1.,idle=.02)):
            self.assertFalse(checkpoint_improves(metrics,1.,initial))
        self.assertFalse(checkpoint_improves(initial,1.,initial))
        with self.assertRaises(ValueError):
            checkpoint_improves(dict(image=float('nan'),surface=1.,idle=0.),1.,initial)

    def setUp(self):
        self.lengths = {"g00_move": 5, "g02_idle": 4, "g11_attack_up": 6}

    def test_attack_is_entirely_held_out(self):
        train, held, slices = split_frames(self.lengths)
        attack = set(range(slices["g11_attack_up"].start, slices["g11_attack_up"].stop))
        self.assertTrue(attack.issubset(set(held)))
        self.assertFalse(attack & set(train))

    def test_split_has_complete_nonoverlapping_coverage(self):
        train, held, slices = split_frames(self.lengths)
        total = sum(self.lengths.values())
        self.assertEqual(set(train) & set(held), set())
        self.assertEqual(set(train) | set(held), set(range(total)))
        self.assertEqual([s.start for s in slices.values()], [0, 5, 9])

    def test_training_uses_deterministic_every_third_holdout(self):
        train, held, slices = split_frames(self.lengths)
        for key, start in (("g00_move", 0), ("g02_idle", 5)):
            expected = {start + index for index in range(self.lengths[key]) if index % 3 == 1}
            self.assertTrue(expected.issubset(set(held)))
            self.assertFalse(expected & set(train))
        self.assertEqual(split_frames(self.lengths), split_frames(dict(self.lengths)))

    def test_missing_idle_or_attack_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "idle"):
            split_frames({"g11_attack_up": 4})
        with self.assertRaisesRegex(ValueError, "upward attack"):
            split_frames({"g02_idle": 4})


if __name__ == "__main__":
    unittest.main()
