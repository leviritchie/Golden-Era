"""Paired sites must not inherit the donor's segment-length fractions."""
import copy
import unittest

import numpy as np

from fit_deformation_bind import BindFitError, fit_deformation_bind


class PairedLandmarkTests(unittest.TestCase):
    def fixture(self, kind="paired_landmarks"):
        return dict(donor_names=["root", "elbow", "wrist"],
                    donor_parents=np.array([-1, 0, 1]),
                    donor_rest=np.array([[0., 0., 0.], [0., 1., 0.], [0., 2., 0.]]),
                    target_names=["a", "b", "c"],
                    target_rest=np.array([[0., 0., 0.], [0., .2, 0.], [1., .2, 0.]]),
                    target_vertices=np.array([[0., 0., 0.], [1., .2, 0.]]),
                    target_regions=np.array(["arm", "arm"]),
                    profile={"hubs": {}, "chains": [dict(name="arm", kind=kind,
                        donor=("root", "elbow", "wrist"), evidence=("a", "b", "c"))],
                        "leftRightPairs": []})

    def test_exact_sites_not_arclength_samples_and_inputs_unchanged(self):
        data = self.fixture()
        before = copy.deepcopy(data)
        fit = fit_deformation_bind(**data)
        np.testing.assert_allclose(fit["fittedPositions"], data["target_rest"], atol=1e-12)
        np.testing.assert_array_equal(data["target_rest"], before["target_rest"])
        self.assertEqual(data["profile"], before["profile"])
        old = fit_deformation_bind(**self.fixture("polyline"))
        self.assertGreater(np.linalg.norm(old["fittedPositions"][1] - data["target_rest"][1]), .3)

    def test_missing_duplicate_and_unknown_correspondences_are_rejected(self):
        for evidence in (("a", "b"), ("a", "b", "b"), ("a", "b", "unknown")):
            with self.subTest(evidence=evidence):
                data = self.fixture()
                data["profile"]["chains"][0]["evidence"] = evidence
                with self.assertRaises(BindFitError):
                    fit_deformation_bind(**data)


if __name__ == "__main__":
    unittest.main()
