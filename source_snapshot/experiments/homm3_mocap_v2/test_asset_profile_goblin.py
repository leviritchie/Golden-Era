import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.homm3_mocap_v2.asset_profile_goblin import get_profile
from experiments.homm3_mocap_v2 import goblin_candidate_anatomy as candidate


class GoblinProfileTests(unittest.TestCase):
    def test_complete_ownership_and_rigid_weapon(self):
        profile = get_profile()
        bones = [bone for group in profile["regionBones"].values() for bone in group]
        self.assertEqual(len(bones), 80)
        self.assertEqual(len(set(bones)), 80)
        self.assertEqual(set(profile["sourceJointMap"]), set(bones))
        self.assertEqual(profile["rigidAttachments"][0]["region"], "weapon")
        self.assertEqual(profile["rigidAttachments"][0]["donorJoints"], ("mixamorig:RightHand",))
        self.assertEqual(profile["regionBones"]["weapon"], ("Bone_079", "Bone_078"))

    def test_proximal_bones_retain_articulated_donor_joints(self):
        mapping = get_profile()["sourceJointMap"]
        expected = {
            "Bone_004": "mixamorig:Spine", "Bone_003": "mixamorig:Spine1", "Bone_002": "mixamorig:Spine2",
            "Bone_021": "mixamorig:LeftArm", "Bone_020": "mixamorig:LeftForeArm",
            "Bone_026": "mixamorig:RightArm", "Bone_025": "mixamorig:RightForeArm",
            "Bone_014": "mixamorig:LeftUpLeg", "Bone_013": "mixamorig:LeftLeg", "Bone_012": "mixamorig:LeftFoot",
            "Bone_009": "mixamorig:RightUpLeg", "Bone_008": "mixamorig:RightLeg", "Bone_007": "mixamorig:RightFoot",
            "Bone_079": "mixamorig:RightHand", "Bone_078": "mixamorig:RightHand",
        }
        for bone, donor in expected.items():
            self.assertEqual(mapping[bone], donor, bone)

    def test_candidate_uses_correct_weapon_anchor(self):
        self.assertEqual(candidate.SOURCE_GROUPS["weapon"], ("Bone_079", "Bone_078"))
        with patch.object(candidate, "load_bind_skeleton") as load:
            skeleton = type("Skeleton", (), {
                "names": [f"Bone_{i:03d}" for i in range(80)],
                "parents": [-1] + list(range(79)),
                "rest_world": [[float(i), 0.0, 0.0] for i in range(80)],
            })()
            load.return_value = skeleton
            with patch.object(candidate, "compute_source_sha256", return_value=candidate.SOURCE_SHA256) as digest:
                relative = Path("absolute-or-relative.glb")
                result = candidate.build_candidate(relative)
                absolute_result = candidate.build_candidate(relative.resolve())
                self.assertEqual(result, absolute_result)
                self.assertEqual(digest.call_args_list[0].args, (relative.resolve(),))
                self.assertEqual(digest.call_args_list[1].args, (relative.resolve(),))
        self.assertEqual(result["weaponCandidate"]["bone"], "Bone_079")
        self.assertEqual(result["weaponCandidate"]["restAnchor"], [79.0, 0.0, 0.0])
        self.assertEqual(result["sourceSha256"], candidate.SOURCE_SHA256)

    def test_candidate_rejects_hash_drift_before_loading_mesh(self):
        with patch.object(candidate, "compute_source_sha256", return_value="drift") as digest, \
             patch.object(candidate, "load_bind_skeleton") as load:
            with self.assertRaisesRegex(ValueError, "hash changed"):
                candidate.build_candidate(Path("changed.glb"))
        digest.assert_called_once()
        load.assert_not_called()


if __name__ == "__main__": unittest.main()
