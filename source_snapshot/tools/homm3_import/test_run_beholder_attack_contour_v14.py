"""Source-pixel provenance tests for the Beholder 3D contour preview."""

import os
from pathlib import Path
import shutil
import sys
import unittest

import numpy as np
from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import run_beholder_attack_contour_v14 as contour


class BeholderAttackContourV14Tests(unittest.TestCase):
    def setUp(self):
        contour.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        self.output = contour.OUTPUT_ROOT / f"test_contour_v14_{os.getpid()}_{self._testMethodName}"
        if self.output.exists() or self.output.parent.resolve() != contour.OUTPUT_ROOT.resolve():
            raise RuntimeError("test output collision or path escape")
        self.output.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.output))

    def test_recovered_electricity_pixels_are_exact_source_rgba(self):
        runtime = contour.validate_and_prepare(self.output)
        self.assertEqual([frame["name"] for frame in runtime["frames"]],
                         [f"12_{index:02d}" for index in range(7)])
        self.assertEqual([frame["name"] for frame in runtime["frames"] if frame["forwardEffectPixels"]],
                         ["12_02", "12_03", "12_04", "12_05"])
        for frame in runtime["frames"]:
            with Image.open(frame["allRecoveredSourcePath"]) as recovered, Image.open(frame["sourcePath"]) as source:
                actual = np.asarray(recovered.convert("RGBA"))
                original = np.asarray(source.convert("RGBA"))
                visible = actual[:, :, 3] > 0
                self.assertEqual(int(visible.sum()), frame["recoverableSourcePixels"], frame["name"])
                np.testing.assert_array_equal(actual[visible], original[visible])
            with Image.open(frame["effectSourcePath"]) as forward, Image.open(frame["sourcePath"]) as source:
                actual = np.asarray(forward.convert("RGBA"))
                original = np.asarray(source.convert("RGBA"))
                visible = actual[:, :, 3] > 0
                self.assertEqual(int(visible.sum()), frame["forwardEffectPixels"], frame["name"])
                np.testing.assert_array_equal(actual[visible], original[visible])
                yy, xx = np.indices(visible.shape)
                self.assertFalse(np.any(visible & ((xx < 215) | (yy >= 246))), frame["name"])
                with Image.open(frame["cropPath"]) as crop:
                    cropped = np.asarray(crop.convert("RGBA"))
                    expected_crop = actual[frame["y0"]:frame["y1"], frame["x0"]:frame["x1"]]
                    np.testing.assert_array_equal(cropped, expected_crop)
            self.assertEqual(frame["effectPixels"], frame["forwardEffectPixels"])
            self.assertGreaterEqual(frame["ambiguousNearCoreAnatomyPixels"], 0)
            self.assertEqual(frame["hasLightOrigin"], bool(frame["forwardEffectPixels"]))
            if not frame["forwardEffectPixels"]:
                self.assertEqual(frame["lightScale"], 0)


if __name__ == "__main__":
    unittest.main()
