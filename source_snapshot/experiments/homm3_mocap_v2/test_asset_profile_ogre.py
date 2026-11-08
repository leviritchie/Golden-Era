from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asset_profile_ogre import OGRE_MIXAMO
from capture_candidates import candidate_record
from glb_skeleton import load_bind_skeleton


class OgreProfileTests(unittest.TestCase):
    def test_profile_covers_actual_skeleton_and_identity(self):
        mesh = Path(OGRE_MIXAMO["mesh"])
        self.assertTrue(mesh.is_file())
        skeleton = load_bind_skeleton(mesh)
        names = set(skeleton.names)
        mapped = set(OGRE_MIXAMO["sourceJointMap"])
        covered = {bone for group in OGRE_MIXAMO["regionBones"].values() for bone in group}
        self.assertEqual(names, mapped)
        self.assertEqual(names, covered)
        self.assertEqual(len(names), 29)
        self.assertEqual(OGRE_MIXAMO["expectedMeshSha256"], "ce5ccf1fa0e76fc561924840f16c363e2fb567484ada545f4257b2f6f8fce76a")

    def test_parent_evidence_and_source_idle_are_real(self):
        skeleton = load_bind_skeleton(Path(OGRE_MIXAMO["mesh"]))
        by_name = dict(zip(skeleton.names, skeleton.parents))
        self.assertEqual(by_name["Bone_001"], 0)
        self.assertEqual(by_name["Bone_005"], 1)
        self.assertEqual(by_name["Bone_023"], 11)
        self.assertEqual(by_name["Bone_028"], 11)
        self.assertTrue(Path(OGRE_MIXAMO["sourceIdleDir"]).is_dir())
        self.assertEqual(OGRE_MIXAMO["sourceIdleGroup"], 2)
        self.assertEqual(OGRE_MIXAMO["sourceIdleFrameCount"], 8)

    def test_no_unverified_prop_ownership(self):
        self.assertEqual(OGRE_MIXAMO["rigidAttachments"][0]["region"], "weapon")
        self.assertEqual(OGRE_MIXAMO["rigidAttachments"][0]["donorJoints"], ("mixamorig:RightHand",))
        self.assertEqual(OGRE_MIXAMO["skinInitialization"], "source_joint_map")
        self.assertTrue(OGRE_MIXAMO["requireCompleteRegionCoverage"])

    def test_arm_pivots_and_side_assignments_are_anatomical(self):
        regions = OGRE_MIXAMO["regionBones"]
        self.assertEqual(regions["arm_left"], ("Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_024"))
        self.assertEqual(regions["arm_right"], ("Bone_023", "Bone_022", "Bone_021", "Bone_020"))
        self.assertEqual(regions["weapon"], ("Bone_019",))
        mapping = OGRE_MIXAMO["sourceJointMap"]
        self.assertEqual(mapping["Bone_020"], "mixamorig:RightHand")
        self.assertEqual(mapping["Bone_019"], "mixamorig:RightHand")
        self.assertEqual(mapping["Bone_028"], "mixamorig:LeftShoulder")
        self.assertEqual(mapping["Bone_010"], "mixamorig:LeftUpLeg")
        self.assertEqual(mapping["Bone_015"], "mixamorig:RightUpLeg")
        self.assertEqual(OGRE_MIXAMO["hubs"]["mixamorig:Spine2"], "Bone_002")
        self.assertEqual(mapping["Bone_002"], "mixamorig:Spine2")

    def test_capture_candidate_matches_profile_donor(self):
        record = candidate_record("h3_ogre")
        self.assertEqual(record["kind"], OGRE_MIXAMO["donorKind"])
        self.assertEqual(record["refSeq"], OGRE_MIXAMO["donorRefSeq"])


if __name__ == "__main__":
    unittest.main()
