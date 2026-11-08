import sys
import unittest
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_eagle_cyclic_context_comparison import context_mapping
from preview_eagle_cyclic_context_comparison import _policy


class CyclicContextMappingTests(unittest.TestCase):
    def setUp(self):
        self.source = np.arange(30, dtype=np.int64)
        self.authored = np.arange(12, 18, dtype=np.int64)

    def test_original_identity_preserves_every_source_index(self):
        mapping = context_mapping(30, self.authored, "original")
        np.testing.assert_array_equal(mapping, self.source)

    def test_cyclic_30_repeats_authored_context_and_keeps_authored_slice(self):
        mapping = context_mapping(30, self.authored, "cyclic")
        np.testing.assert_array_equal(mapping, np.resize(self.authored, 30))
        np.testing.assert_array_equal(mapping[12:18], self.authored)

    def test_cyclic_29_repeats_without_interpolation_and_keeps_authored_slice(self):
        mapping = context_mapping(29, self.authored, "cyclic")
        np.testing.assert_array_equal(mapping, np.resize(self.authored, 29))
        np.testing.assert_array_equal(mapping[12:18], self.authored)

    def test_rejects_invalid_policy(self):
        with self.assertRaises(ValueError):
            context_mapping(30, self.authored, "blend")

    def test_phase_lock_is_not_accidental_multiple_of_cycle_length(self):
        mapping = context_mapping(13, [4, 5, 6], 'cyclic')
        np.testing.assert_array_equal(mapping, [6,4,5,6,4,5,6,4,5,6,4,5,6])

    def test_preview_policy_has_no_missing_or_substring_fallback(self):
        for value in (None, '', 'original_context', 'not_cyclic', 'cyclic_context_from_authored_move'):
            with self.assertRaises(ValueError):
                _policy({}, {'provenance': {'policy': value}})
        for value in ('original','cyclic'):
            self.assertEqual(_policy({}, {'provenance': {'policy': value}}), value)

    def test_rejects_empty_noncontiguous_noninteger_and_out_of_range_indices(self):
        for length, indices in (
            (30, []), (30, [12, 14, 15, 16, 17, 18]),
            (30, [12.0, 13, 14, 15, 16, 17]),
            (30, [-1, 0, 1, 2, 3, 4]),
            (30, [12, 13, 14, 15, 16, 30]), (0, self.authored),
        ):
            with self.assertRaises(ValueError):
                context_mapping(length, indices, "cyclic")


if __name__ == "__main__":
    unittest.main()
