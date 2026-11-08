import unittest
from pathlib import Path

from experiments.homm3_mocap_v2.asset_profile_cyclops import get_profile
from experiments.homm3_mocap_v2.capture_candidates import candidate_record
from experiments.homm3_mocap_v2.target_asset import load_target_asset


class CyclopsProfileTests(unittest.TestCase):
    def test_complete_source_coverage_and_pinned_mesh(self):
        p = get_profile()
        bones = [b for region in p["regionBones"].values() for b in region]
        self.assertEqual(len(bones), 44)
        self.assertEqual(len(set(bones)), 44)
        self.assertEqual(set(p["sourceJointMap"]), set(bones))
        self.assertEqual(p["expectedMeshSha256"], "b1d7b588c78833e4f6d1687d93075d5aa69d81feb7c25e9c6ba669ed06544248")
        self.assertTrue(Path(p["mesh"]).is_file())

    def test_coordinate_backed_left_right_pivots(self):
        p = get_profile()
        m = p["sourceJointMap"]
        self.assertEqual(m["Bone_028"], "mixamorig:LeftShoulder")
        self.assertEqual(m["Bone_027"], "mixamorig:LeftArm")
        self.assertEqual(m["Bone_026"], "mixamorig:LeftForeArm")
        self.assertEqual(m["Bone_025"], "mixamorig:LeftHand")
        self.assertEqual(m["Bone_023"], "mixamorig:RightShoulder")
        self.assertEqual(m["Bone_022"], "mixamorig:RightArm")
        self.assertEqual(m["Bone_021"], "mixamorig:RightForeArm")
        self.assertEqual(m["Bone_020"], "mixamorig:RightHand")
        # Bone_003 is the short final chest segment; Bone_002 is its terminal
        # detail and is intentionally retained in the Spine2 region.
        self.assertEqual(p["hubs"]["mixamorig:Spine2"], "Bone_003")
        # The anatomical wrist is the proximal Bone_025/Bone_020 pivot;
        # terminal detail may be hand-owned but must not replace that pivot.
        self.assertEqual(m["Bone_025"], "mixamorig:LeftHand")
        self.assertEqual(m["Bone_020"], "mixamorig:RightHand")

    def test_load_coverage_source_idle_and_capture_donor(self):
        p = get_profile()
        loaded = load_target_asset(p)
        self.assertEqual(len(loaded["names"]), 44)
        self.assertEqual(len(loaded["vertices"]), 11890)
        self.assertEqual(p["sourceIdleGroup"], 2)
        self.assertEqual(p["sourceIdleFrameCount"], 6)
        self.assertTrue(str(p["sourceIdleDir"]).replace("\\", "/").endswith("h3_cyclops/extracted_battle_source_12fps/CCYCLR.dir"))
        record = candidate_record("h3_cyclops")
        self.assertEqual(record["kind"], p["donorKind"])
        self.assertEqual(record["refSeq"], p["donorRefSeq"])


if __name__ == "__main__":
    unittest.main()
