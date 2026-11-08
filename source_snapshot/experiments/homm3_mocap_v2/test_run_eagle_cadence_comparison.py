import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_eagle_cadence_comparison import context_mapping
from preview_eagle_cadence_comparison import _verify_mapping


class EagleCadenceMappingTests(unittest.TestCase):
    def test_original_preserves_full_context_and_authored_positions(self):
        mapping = context_mapping(30, "original")
        np.testing.assert_array_equal(mapping, np.arange(30))
        authored = np.array([12, 13, 14, 15, 16, 17])
        np.testing.assert_array_equal(mapping[authored], authored)

    def test_hold2_repeats_each_source_and_authored_frames_use_first_duplicate(self):
        mapping = context_mapping(29, "hold2")
        np.testing.assert_array_equal(mapping, np.repeat(np.arange(29), 2))
        authored = np.arange(12, 18)
        authored_positions = authored * 2
        np.testing.assert_array_equal(mapping[authored_positions], authored)
        self.assertEqual(len(mapping) - authored_positions[-1] - 1, 23)

    def test_lengths_have_explicit_after_count_with_last_held_duplicate(self):
        for length, expected_after in ((30, 25), (29, 23)):
            mapping = context_mapping(length, "hold2")
            authored_positions = np.arange(12, 18) * 2
            self.assertEqual(int(mapping[authored_positions[-1]]), 17)
            self.assertEqual(len(mapping) - int(authored_positions[-1]) - 1, expected_after)

    def test_invalid_lengths_and_policy_fail_closed(self):
        for bad in (0, -1, 1.5, True, "30"):
            with self.assertRaises(ValueError):
                context_mapping(bad, "original")
        with self.assertRaisesRegex(ValueError, "unknown"):
            context_mapping(30, "cyclic")

    def _verify_with_memory_files(self, mapping, new_source_indices, *, bad_target=None):
        length = 30
        old_frames = [Path("old") / "frames" / f"{i:06d}.png" for i in range(length)]
        new_frames = [Path("new") / "frames" / f"{i:06d}.png" for i in range(len(mapping))]
        old_raw = Path("old") / "capture" / "raw_capture.npz"
        new_raw = Path("new") / "capture" / "raw_capture.npz"
        old_row = {"sourceIndices": list(range(12, 18)), "frames": ["authored-%d.png" % i for i in range(6)]}
        new_row = {"sourceIndices": list(new_source_indices), "frames": list(old_row["frames"])}
        context_hashes = [f"source-{i}" for i in range(length)]

        def glob(self, _pattern):
            text = str(self).replace("\\", "/")
            return old_frames if text.startswith("old/") else new_frames

        def digest(path):
            path = Path(path)
            text = str(path).replace("\\", "/")
            if text.startswith("old/"):
                return context_hashes[int(path.stem)]
            target = int(path.stem)
            if bad_target is not None and target == bad_target:
                return "wrong-hash"
            return context_hashes[int(mapping[target])]

        with patch("preview_eagle_cadence_comparison.Path.glob", new=glob), \
             patch("preview_eagle_cadence_comparison.sha256_file", side_effect=digest):
            _verify_mapping("hold2", list(mapping), new_row, old_row, old_raw, new_raw, context_hashes)

    def test_preview_accepts_hold2_doubled_mapping_and_first_authored_duplicates(self):
        mapping = context_mapping(30, "hold2")
        self._verify_with_memory_files(mapping, np.arange(12, 18) * 2)

    def test_preview_rejects_two_full_passes_instead_of_hold2(self):
        mapping = np.tile(np.arange(30), 2)
        with self.assertRaisesRegex(ValueError, "mapping does not implement"):
            self._verify_with_memory_files(mapping, np.arange(12, 18) * 2)

    def test_preview_rejects_unchanged_authored_selection(self):
        mapping = context_mapping(30, "hold2")
        with self.assertRaisesRegex(ValueError, "authored source indices"):
            self._verify_with_memory_files(mapping, np.arange(12, 18))

    def test_preview_rejects_wrong_mapped_png_hash(self):
        mapping = context_mapping(30, "hold2")
        with self.assertRaisesRegex(ValueError, "PNG hash"):
            self._verify_with_memory_files(mapping, np.arange(12, 18) * 2, bad_target=7)


if __name__ == "__main__":
    unittest.main()
