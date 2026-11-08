import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("unity_editor") / "ProbeMocapDeliveryBundles.cs"


class ProbeMotionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_curve_key_and_midpoint_sampling_is_present(self):
        self.assertIn("source-pinned sample times", self.source)
        self.assertIn("sampleTimes", self.source)
        self.assertIn("sourceMotionAnalyzed", self.source)
        self.assertIn("expectedMotion", self.source)

    def test_varying_curve_without_mesh_motion_fails(self):
        self.assertIn("expectedMotion && !changed", self.source)
        self.assertIn("source-varying motion but no observed mesh motion", self.source)

    def test_failure_report_is_written_before_process_failure(self):
        write = self.source.index("File.WriteAllText(output")
        failure = self.source.index("if (failed) throw")
        self.assertLess(write, failure)

    def test_static_clips_are_not_unconditionally_rejected(self):
        self.assertIn("expectedMotion", self.source)
        self.assertNotIn("if (!changed) throw", self.source)


if __name__ == "__main__":
    unittest.main()
