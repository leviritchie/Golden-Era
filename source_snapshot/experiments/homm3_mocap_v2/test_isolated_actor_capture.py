"""CPU tests for fixed-canvas isolated capture preflight."""
import sys, unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_actor_capture import _timeline
from dino_embed import extract_subject_from_rgba


class IsolatedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_tmp") / "isolated_capture_tests"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for p in self.root.glob("*.png"):
            p.unlink()

    def _manifest(self, names):
        paths = []
        for name in names:
            path = self.root / name
            Image.new("RGBA", (8, 8), (20, 30, 40, 255)).save(path)
            paths.append(str(path))
        return {"clips": [{"key": "g02_idle", "contextBefore": [paths[0]], "frames": [paths[1]], "contextAfter": [paths[2]]}]}

    def test_timeline_rejects_swapped_frames(self):
        a, b = self._manifest(["a.png", "b.png", "c.png"]), self._manifest(["a.png", "c.png", "b.png"])
        self.assertNotEqual(_timeline(a), _timeline(b))

    def test_transparent_hidden_rgb_does_not_change_encoder_pixels(self):
        window = {"canvas": [4, 4], "bboxXyxy": [0, 0, 4, 4], "paddingRatio": 0.0, "bg": [1.0, 1.0, 1.0]}
        one = np.zeros((4, 4, 4), dtype=np.uint8); two = one.copy()
        one[1, 1] = [255, 0, 0, 255]; two[1, 1] = [255, 0, 0, 255]
        one[2, 2] = [1, 2, 3, 0]; two[2, 2] = [250, 240, 230, 0]
        self.assertTrue(np.array_equal(extract_subject_from_rgba(one, window), extract_subject_from_rgba(two, window)))


if __name__ == "__main__":
    unittest.main()
