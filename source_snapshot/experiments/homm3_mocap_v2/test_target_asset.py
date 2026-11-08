import unittest

from target_asset import validate_complete_region_coverage


class CompleteRegionCoverageTests(unittest.TestCase):
    def _profile(self):
        return {
            "requireCompleteRegionCoverage": True,
            "regionJoints": {"body": ("source_body",), "arm": ("source_arm",)},
            "regionBones": {"body": ("Bone_000",), "arm": ("Bone_001",)},
        }

    def test_opt_in_contract_accepts_complete_assignment(self):
        validate_complete_region_coverage(["Bone_000", "Bone_001"], self._profile())

    def test_rejects_missing_and_duplicate_source_bones(self):
        with self.assertRaisesRegex(ValueError, "missing region assignment"):
            validate_complete_region_coverage(["Bone_000", "Bone_001", "Bone_002"], self._profile())
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_complete_region_coverage(["Bone_000"], self._profile())
        profile = self._profile()
        profile["regionBones"]["arm"] = ("Bone_000",)
        with self.assertRaisesRegex(ValueError, "multiple"):
            validate_complete_region_coverage(["Bone_000"], profile)

    def test_rejects_unlisted_region_and_rigid_donor(self):
        profile = self._profile()
        profile["regionBones"]["tail"] = ("Bone_001",)
        with self.assertRaisesRegex(ValueError, "absent"):
            validate_complete_region_coverage(["Bone_000", "Bone_001"], profile)
        profile = self._profile()
        profile["regionBones"]["weapon"] = ("Bone_002",)
        profile["rigidAttachments"] = ({"region": "weapon", "donorJoints": ("missing",)},)
        with self.assertRaisesRegex(ValueError, "donor joints"):
            validate_complete_region_coverage(["Bone_000", "Bone_001", "Bone_002"], profile)

    def test_existing_profiles_are_not_opted_in(self):
        validate_complete_region_coverage([], {"regionBones": {"body": ("not-present",)}})


if __name__ == "__main__":
    unittest.main()
