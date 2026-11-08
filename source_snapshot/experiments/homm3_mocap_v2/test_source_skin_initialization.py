import unittest

import numpy as np

from source_skin_initialization import initialize_source_weights


class SourceSkinInitializationTests(unittest.TestCase):
    def profile(self):
        return {"sourceJointMap": {"src_body": "body", "src_hand": "hand"},
                "regionJoints": {"body": ("body",), "arm": ("hand",)},
                "rigidAttachments": ()}

    def test_remap_restricts_and_renormalizes_mass(self):
        result = initialize_source_weights([[.7, .3], [.2, .8]], ["src_body", "src_hand"],
            ["body", "hand"], ["body", "arm"], self.profile())
        np.testing.assert_allclose(result["weights"], [[1, 0], [0, 1]])
        self.assertEqual(result["rigidCount"], 0)
        self.assertGreater(result["restrictedMassReport"]["min"], 0)

    def test_missing_mapping_fails(self):
        profile = self.profile()
        del profile["sourceJointMap"]["src_hand"]
        with self.assertRaises(ValueError):
            initialize_source_weights([[.5, .5]], ["src_body", "src_hand"], ["body", "hand"], ["body"], profile)

    def test_rigid_attachment_requires_exact_single_donor(self):
        profile = self.profile()
        profile["rigidAttachments"] = ({"region": "weapon", "donorJoints": ("hand",)},)
        result = initialize_source_weights([[0, 1]], ["src_body", "src_hand"], ["body", "hand"], ["weapon"], profile)
        np.testing.assert_allclose(result["weights"], [[0, 1]])
        self.assertEqual(result["rigidCount"], 1)

    def test_zero_support_and_duplicate_source_names_fail(self):
        with self.assertRaises(ValueError):
            initialize_source_weights([[1, 0]], ["src_body", "src_hand"], ["body", "hand"], ["arm"], self.profile())
        with self.assertRaises(ValueError):
            initialize_source_weights([[1, 0]], ["same", "same"], ["body", "hand"], ["body"], self.profile())


if __name__ == "__main__":
    unittest.main()
