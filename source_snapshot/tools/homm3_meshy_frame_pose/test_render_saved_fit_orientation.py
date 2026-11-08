"""Focused tests for the saved fitted-motion orientation diagnostic."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_saved_fit_orientation as diagnostic


class SavedFitOrientationTests(unittest.TestCase):
    def test_keyframes_select_middle_frame_per_review_clip(self):
        labels = [
            "unit | g02_idle",
            "unit | g02_idle",
            "unit | g00_move",
            "unit | g00_move",
            "unit | g00_move",
            "unit | g05_death",
        ]
        self.assertEqual(diagnostic.keyframe_indices(labels), [1, 3, 5])


if __name__ == "__main__":
    unittest.main()
