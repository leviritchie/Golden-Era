import unittest
import numpy as np
from camera_chroma_registration import chromaticity, rank_candidates


class CameraChromaTests(unittest.TestCase):
    def test_chroma_breaks_alpha_iou_tie(self):
        rgb = np.zeros((2, 2, 3)); rgb[..., 0] = 1
        alpha = np.ones((2, 2, 1))
        wrong = np.zeros_like(rgb); wrong[..., 1] = 1
        ranked = rank_candidates([{"id": "wrong", "rgb": wrong, "alpha": alpha},
                                  {"id": "right", "rgb": rgb, "alpha": alpha}], rgb, alpha)
        self.assertEqual(ranked[0]["id"], "right")
        self.assertEqual(ranked[0]["alphaIoU"], 1.0)

    def test_rejects_nonfinite_and_empty_candidates(self):
        with self.assertRaises(ValueError):
            chromaticity([[[np.nan, 0, 0]]], [[[1]]])
        with self.assertRaises(ValueError):
            rank_candidates([], np.zeros((1, 1, 3)), np.ones((1, 1, 1)))


if __name__ == "__main__":
    unittest.main()
