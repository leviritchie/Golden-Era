import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from prepare_skin_corpus import ROOT, normalized_rgba, movement_context


class PrepareIdleNormalizationTests(unittest.TestCase):
    def test_native_movement_presence_is_explicit(self):
        for groups, expected, absent in (({20, 0, 21}, [20, 0, 21], []),
                                         ({0}, [0], [20, 21]),
                                         ({20, 0}, [20, 0], [21]),
                                         ({0, 21}, [0, 21], [20])):
            with self.subTest(groups=groups):
                chain, report = movement_context({g: [str(g)] for g in groups})
                self.assertEqual(chain, expected)
                self.assertEqual(report["absentTransitionGroups"], absent)
                self.assertIn("no frames", report["absenceReason"])
        with self.assertRaisesRegex(ValueError, "authored movement cycle"):
            movement_context({20: ["start"], 21: ["end"]})

    def test_shadow_alpha_difference_normalizes_but_body_pixel_does_not(self):
        # Keep fixtures on V:, since the managed Windows TEMP can deny cleanup.
        root = ROOT / "artifacts" / "test_tmp"
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / ("skin-normalization-" + uuid4().hex)
        temporary.mkdir()
        paths = []
        try:
            known = np.zeros((4, 4, 4), dtype=np.uint8)
            known[1:3, 1:3] = [40, 80, 120, 255]
            known[0, 0] = [0, 0, 0, 64]
            changed_shadow = known.copy()
            changed_shadow[0, 0, 3] = 128
            changed_body = known.copy()
            changed_body[1, 1, 0] = 41
            paths = [Path(temporary) / name for name in ("known.png", "shadow.png", "body.png")]
            for path, values in zip(paths, (known, changed_shadow, changed_body)):
                Image.fromarray(values, "RGBA").save(path)

            np.testing.assert_array_equal(normalized_rgba(paths[0]), normalized_rgba(paths[1]))
            self.assertFalse(np.array_equal(normalized_rgba(paths[0]), normalized_rgba(paths[2])))
        finally:
            for path in paths:
                path.unlink(missing_ok=True)
            temporary.rmdir()


if __name__ == "__main__":
    unittest.main()
