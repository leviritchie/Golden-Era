import unittest

from run_region_clipping_diagnostic import assert_weight_only, validate_corpus_structure


class RegionClippingPreflightTests(unittest.TestCase):
    def base(self):
        return {"motionRepresentation": "capture_positions_v1", "captures": [{"key": "g00_move"}]}

    def test_accepts_unique_safe_capture_keys(self):
        validate_corpus_structure(self.base())

    def test_rejects_composed_motion(self):
        corpus = self.base()
        corpus["motionRepresentation"] = "composed_fk_v1"
        with self.assertRaisesRegex(ValueError, "capture_positions_v1"):
            validate_corpus_structure(corpus)

    def test_rejects_empty_capture_inventory(self):
        corpus = self.base()
        corpus["captures"] = []
        with self.assertRaisesRegex(ValueError, "no captures"):
            validate_corpus_structure(corpus)

    def test_rejects_duplicate_and_unsafe_keys(self):
        corpus = self.base()
        corpus["captures"].append({"key": "g00_move"})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_corpus_structure(corpus)
        corpus["captures"] = [{"key": "../g00_move"}]
        with self.assertRaisesRegex(ValueError, "unsafe"):
            validate_corpus_structure(corpus)

    def test_rejects_non_weight_changes(self):
        original = {"weights": [[1.0]], "vertices": [[0.0, 0.0, 0.0]], "parents": [0]}
        candidate = {"weights": [[0.5, 0.5]], "vertices": [[1.0, 0.0, 0.0]], "parents": [0]}
        with self.assertRaisesRegex(ValueError, "vertices"):
            assert_weight_only(original, candidate)
if __name__ == "__main__":
    unittest.main()
