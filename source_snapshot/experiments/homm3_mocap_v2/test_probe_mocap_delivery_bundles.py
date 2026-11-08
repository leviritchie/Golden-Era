import unittest
from pathlib import Path


class ProbeMocapDeliveryBundlesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[2] / "tools" / "homm3_import" / "unity_editor" / "ProbeMocapDeliveryBundles.cs"
        cls.source = cls.path.read_text(encoding="utf-8")

    def test_bounded_generic_probe_shape(self):
        self.assertLess(len(self.source.splitlines()), 200)
        self.assertIn("-mocapProbeSpec", self.source)
        self.assertIn("-mocapProbeOut", self.source)
        self.assertIn("AssetBundle.LoadFromFile", self.source)
        self.assertIn("GetAllAssetNames", self.source)
        self.assertIn("AnimationClip", self.source)
        self.assertIn("SampleAnimation", self.source)
        self.assertIn("BakeMesh", self.source)
        self.assertIn("sourceMotionAnalyzed", self.source)
        self.assertIn("sampleTimes", self.source)
        self.assertIn("expectedMotion", self.source)
        self.assertNotIn("AnimationUtility.GetCurveBindings", self.source)

    def test_no_unit_specific_or_acceptance_claims(self):
        for forbidden in ("h3_", "Ogre", "Hobgoblin", "Stronghold", "accepted = true", "runtime-proven"):
            self.assertNotIn(forbidden, self.source)
        self.assertIn("generated-asset-only", self.source)
        self.assertIn("motionObserved", self.source)

    def test_structural_gates_and_cleanup_are_present(self):
        self.assertIn("__homm3_skin_weights_unlimited__", self.source)
        self.assertIn("GetBonesPerVertex", self.source)
        self.assertIn("Finite(mesh.bindposes)", self.source)
        self.assertIn("QualitySettings.skinWeights = (SkinWeights)original", self.source)
        self.assertIn("bundle.Unload(false)", self.source)
        self.assertIn("DestroyImmediate(instance)", self.source)


if __name__ == "__main__":
    unittest.main()
