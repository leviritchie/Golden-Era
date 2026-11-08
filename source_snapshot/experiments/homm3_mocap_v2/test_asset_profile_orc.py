import unittest
from pathlib import Path

from experiments.homm3_mocap_v2.asset_profile_orc import get_profile
from experiments.homm3_mocap_v2.capture_candidates import candidate_record


class OrcProfileTests(unittest.TestCase):
    def test_complete_source_ownership_and_identity(self):
        profile = get_profile()
        bones = [bone for region in profile["regionBones"].values() for bone in region]
        self.assertEqual(len(bones), 66)
        self.assertEqual(len(set(bones)), 66)
        self.assertEqual(set(profile["sourceJointMap"]), set(bones))
        self.assertEqual(profile["expectedMeshSha256"], "b31ea821f9e48ee03d209d177c06d408bb896c90d84c9418caaf0baf23fb3325")
        self.assertTrue(Path(profile["mesh"]).is_file())

    def test_inspected_proximal_chains_and_terminal_ownership(self):
        profile = get_profile()
        mapping = profile["sourceJointMap"]
        self.assertEqual(profile["hubs"], {
            "mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_008",
            "mixamorig:Spine1": "Bone_007", "mixamorig:Spine2": "Bone_006",
        })
        expected = {
            "Bone_021": "mixamorig:Neck", "Bone_020": "mixamorig:Head",
            "Bone_026": "mixamorig:LeftShoulder", "Bone_025": "mixamorig:LeftArm",
            "Bone_024": "mixamorig:LeftForeArm", "Bone_023": "mixamorig:LeftHand",
            "Bone_031": "mixamorig:RightShoulder", "Bone_030": "mixamorig:RightArm",
            "Bone_029": "mixamorig:RightForeArm", "Bone_028": "mixamorig:RightHand",
            "Bone_013": "mixamorig:RightUpLeg", "Bone_012": "mixamorig:RightLeg",
            "Bone_011": "mixamorig:RightFoot", "Bone_018": "mixamorig:LeftUpLeg",
            "Bone_017": "mixamorig:LeftLeg", "Bone_016": "mixamorig:LeftFoot",
        }
        for bone, donor in expected.items():
            self.assertEqual(mapping[bone], donor, bone)
        self.assertEqual(mapping["Bone_019"], "mixamorig:HeadTop_End")
        self.assertEqual(mapping["Bone_032"], "mixamorig:LeftHand")
        self.assertEqual(mapping["Bone_035"], "mixamorig:LeftHand")

    def test_source_idle_contract_and_capture_donor(self):
        profile = get_profile()
        self.assertEqual(profile["sourceIdleGroup"], 2)
        self.assertEqual(profile["sourceIdleFrameCount"], 8)
        self.assertTrue(str(profile["sourceIdleDir"]).replace("\\", "/").endswith("h3_orc/extracted_battle_source_12fps/CORC.dir"))
        record = candidate_record("h3_orc")
        self.assertEqual(record["kind"], profile["donorKind"])
        self.assertEqual(record["refSeq"], profile["donorRefSeq"])


if __name__ == "__main__":
    unittest.main()
