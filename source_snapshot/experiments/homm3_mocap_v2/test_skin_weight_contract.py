"""Candidate publication cannot bypass support or held-out quality gates."""
import unittest
import numpy as np
from skin_weight_contract import holdout_gate, validate_candidate_weights


class SkinWeightContractTests(unittest.TestCase):
    def test_frozen_support_and_normalization(self):
        original = np.array([[1., 0., 0.], [0., 1., 0.]], dtype=np.float32)
        kwargs = dict(original=original, regions=["wing", "leg"], names=["a", "b", "c"],
                      region_joints={"wing": ["a", "b"]}, train_regions=["wing"])
        valid = np.array([[.5, .5, 0.], [0., 1., 0.]], dtype=np.float32)
        self.assertTrue(validate_candidate_weights(valid, **kwargs)["ok"])
        for invalid in (np.array([[.5, 0., .5], [0., 1., 0.]]),
                        np.array([[.5, .5, 0.], [1., 0., 0.]]),
                        np.array([[.5, .2, 0.], [0., 1., 0.]])):
            with self.assertRaises(ValueError):
                validate_candidate_weights(invalid, **kwargs)

    def test_training_improvement_cannot_override_flight_regression(self):
        good = dict(holdoutMeanIouImprovement=.02, beforeEdgeRatioP95=2., afterEdgeRatioP95=2.)
        bad = dict(good, holdoutMeanIouImprovement=-.01)
        self.assertFalse(holdout_gate({"attack": good, "flight": bad}))
        self.assertFalse(holdout_gate({"attack": dict(good, afterEdgeRatioP95=3.)}))
        self.assertFalse(holdout_gate({}))
        self.assertTrue(holdout_gate({"attack": good, "flight": good}))


if __name__ == "__main__":
    unittest.main()
