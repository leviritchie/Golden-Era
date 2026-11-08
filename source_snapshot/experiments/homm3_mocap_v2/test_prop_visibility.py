import unittest
from pathlib import Path

import numpy as np

import prop_visibility


class PropVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.paths = {"g15_shoot_front": [Path("a.png"), Path("b.png")], "g14_shoot_up": [Path("c.png")]}
        self.hashes = {str(path): ("%064x" % (index + 1)) for index, path in enumerate([*self.paths["g15_shoot_front"], *self.paths["g14_shoot_up"]])}
        prop_visibility.Path.is_file = lambda path: True
        prop_visibility._sha256 = lambda path: self.hashes[str(path)]

    def tearDown(self):
        import importlib
        importlib.reload(prop_visibility)

    def row(self, *, asset="h3_cyclops", corpus="corpus", clips=None):
        clips = clips or {"g15_shoot_front": {"sourceFrameSha256": [self.hashes["a.png"], self.hashes["b.png"]], "visible": [True, False]}}
        return {"schema": 1, "asset": asset, "corpusSha256": corpus, "clips": clips}

    def test_declared_subset_and_strict_bool(self):
        result = prop_visibility.validate_visibility(self.row(), "h3_cyclops", "corpus", self.paths)
        np.testing.assert_array_equal(result["g15_shoot_front"], [True, False])

    def test_missing_extra_and_length_fail_closed(self):
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(self.row(clips={"missing": {"sourceFrameSha256": [], "visible": []}}), "h3_cyclops", "corpus", self.paths)
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(self.row(clips={"g15_shoot_front": {"sourceFrameSha256": [self.hashes["a.png"]], "visible": [True]}}), "h3_cyclops", "corpus", self.paths)
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(self.row(clips={"g15_shoot_front": {"sourceFrameSha256": [self.hashes["a.png"], self.hashes["b.png"]], "visible": [1, False]}}), "h3_cyclops", "corpus", self.paths)

    def test_identity_and_source_hash_fail(self):
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(self.row(asset="other"), "h3_cyclops", "corpus", self.paths)
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(self.row(corpus="other"), "h3_cyclops", "corpus", self.paths)
        bad = self.row(); bad["clips"]["g15_shoot_front"]["sourceFrameSha256"][0] = "%064x" % 999
        with self.assertRaises(ValueError):
            prop_visibility.validate_visibility(bad, "h3_cyclops", "corpus", self.paths)


if __name__ == "__main__":
    unittest.main()
