import unittest
from pathlib import Path


def _vector_metrics(expected, actual):
    expected_by_joint = {joint: weight for joint, weight in expected}
    actual_by_joint = {joint: weight for joint, weight in actual}
    joints = set(expected_by_joint) | set(actual_by_joint)
    l1 = sum(abs(expected_by_joint.get(joint, 0.0) - actual_by_joint.get(joint, 0.0)) for joint in joints)
    q = 1.0 / 65535.0
    delta = len(expected) * q + abs(sum(weight for _, weight in expected) - 1.0)
    return l1, 2.0 * delta / (1.0 - delta)


class OwnedSkinnedBuilderSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[2] / "tools" / "homm3_import" / "unity_editor" / "Homm3OwnedSkinnedLabBuild.cs").read_text(encoding="utf-8")

    def test_smartrig_cascade_stamps_authored_twelve_fps(self):
        self.assertIn('spec.motionAuthority == "idle0_bind_first"', self.source)
        self.assertIn('spec.motionAuthority == "smartrig_gpu_cascade"', self.source)
        self.assertIn("FindNestedBindingPath", self.source)
        self.assertIn("clip binding matches more than one nested transform", self.source)

    def test_copies_pbr_and_master_with_exact_size_check(self):
        self.assertIn("CopyExactFile(spec.albedo, ToAbsolute(albedoPath))", self.source)
        self.assertIn("CopyExactFile(spec.masterGlb, ToAbsolute(masterAssetPath))", self.source)
        self.assertIn("copied file size mismatch", self.source)

    def test_stock_map_binds_missing_mouseover_to_idle(self):
        self.assertIn('if (suffix == "Mouseover" && present.Contains(idle))', self.source)
        self.assertIn("return idle;", self.source)
        self.assertIn('throw new InvalidOperationException("missing required clip " + name);', self.source)

    def test_rebuilds_incompatible_import_mesh_without_dropping_channels(self):
        self.assertIn("RebuildMeshWithCompatibleSkinLayout", self.source)
        self.assertIn("copy.vertices = source.vertices", self.source)
        self.assertIn("copy.bindposes = source.bindposes", self.source)
        self.assertIn("copy.subMeshCount = source.subMeshCount", self.source)
        self.assertIn("copy.SetUVs(channel, values)", self.source)
        self.assertIn("copy.AddBlendShapeFrame", self.source)
        self.assertIn("using UnityEngine.Rendering", self.source)
        self.assertIn("GetIndices(submesh, false)", self.source)
        self.assertIn("GetVertexAttributeFormat(VertexAttribute.Color)", self.source)
        self.assertNotIn("Mesh owned = UnityEngine.Object.Instantiate(source);", self.source)

    def test_skin_readback_remains_fail_closed(self):
        self.assertIn("owned.GetBonesPerVertex()", self.source)
        self.assertIn("owned.GetAllBoneWeights()", self.source)
        self.assertIn("materially changed source skin influences", self.source)
        self.assertIn("maxL1Error", self.source)
        self.assertIn("const float quantizationStep = 1f / 65535f", self.source)
        self.assertIn("float allowedL1Error = 2f * delta / denominator", self.source)

    def test_eight_slot_quantization_bound_accepts_tiny_loss(self):
        expected = [(joint, 0.125) for joint in range(8)]
        actual = [(joint, 0.125) for joint in range(8)]
        actual[0] = (0, 0.1249844678)
        actual[1] = (1, 0.1250155322)
        l1, bound = _vector_metrics(expected, actual)
        self.assertLess(l1, bound)

    def test_observed_goblin_rounding_pair_passes_whole_vector_budget(self):
        expected = [(0, 0.0000765682416), (1, 0.9999234317584)]
        actual = [(0, 0.0000610360876), (1, 0.9999389639124)]
        l1, bound = _vector_metrics(expected, actual)
        self.assertAlmostEqual(l1, 3.1064308e-5, places=10)
        self.assertLess(l1, bound)

    def test_meaningful_truncation_and_wrong_joint_are_not_quantization(self):
        expected = [(joint, 0.125) for joint in range(8)]
        top_four = [(joint, 0.25) for joint in range(4)]
        l1, bound = _vector_metrics(expected, top_four)
        self.assertGreater(l1, bound)
        wrong_joint = [(joint, 0.125) for joint in range(7)] + [(99, 0.125)]
        wrong_l1, wrong_bound = _vector_metrics(expected, wrong_joint)
        self.assertGreater(wrong_l1, wrong_bound)
        self.assertIn("unexpectedJointCount != 0", self.source)


if __name__ == "__main__":
    unittest.main()
