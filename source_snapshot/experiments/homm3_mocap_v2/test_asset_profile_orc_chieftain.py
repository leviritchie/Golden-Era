import hashlib
import unittest
from pathlib import Path

from asset_profile_orc_chieftain import get_profile
from glb_skeleton import load_bind_skeleton


class OrcChieftainProfileTests(unittest.TestCase):
    def test_mesh_identity_and_complete_source_coverage(self):
        profile = get_profile()
        mesh = Path(profile["mesh"])
        self.assertTrue(mesh.is_file())
        digest = hashlib.sha256(mesh.read_bytes()).hexdigest()
        self.assertEqual(digest, profile["expectedMeshSha256"])
        skeleton = load_bind_skeleton(mesh)
        bones = [bone for region in profile["regionBones"].values() for bone in region]
        self.assertEqual(len(skeleton.names), 66)
        self.assertEqual(len(bones), 66)
        self.assertEqual(len(set(bones)), 66)
        self.assertEqual(set(bones), set(skeleton.names))
        self.assertEqual(set(profile["sourceJointMap"]), set(skeleton.names))

    def test_coordinate_backed_laterality_and_anatomical_chains(self):
        profile = get_profile()
        skeleton = load_bind_skeleton(Path(profile["mesh"]))
        index = {name: i for i, name in enumerate(skeleton.names)}
        x = {name: float(skeleton.rest_world[index[name], 0]) for name in index}
        # The audited arm/leg proximal joints establish +X left, -X right.
        self.assertGreater(x["Bone_033"], 0.0)
        self.assertLess(x["Bone_028"], 0.0)
        self.assertGreater(x["Bone_010"], 0.0)
        self.assertLess(x["Bone_007"], 0.0)
        self.assertEqual(profile["chains"][2]["evidence"], ("Bone_033", "Bone_032", "Bone_031", "Bone_030"))
        self.assertEqual(profile["chains"][3]["evidence"], ("Bone_028", "Bone_027", "Bone_026", "Bone_025"))
        self.assertEqual(profile["sourceJointMap"]["Bone_032"], "mixamorig:LeftArm")
        self.assertEqual(profile["sourceJointMap"]["Bone_031"], "mixamorig:LeftForeArm")
        self.assertEqual(profile["sourceJointMap"]["Bone_030"], "mixamorig:LeftHand")
        self.assertEqual(profile["sourceJointMap"]["Bone_029"], "mixamorig:LeftHand")
        self.assertEqual(profile["sourceJointMap"]["Bone_025"], "mixamorig:RightHand")
        self.assertEqual(profile["sourceJointMap"]["Bone_030"], "mixamorig:LeftHand")
        self.assertEqual(profile["sourceJointMap"]["Bone_004"], "mixamorig:Spine")
        self.assertEqual(profile["sourceJointMap"]["Bone_003"], "mixamorig:Spine1")
        self.assertEqual(profile["sourceJointMap"]["Bone_002"], "mixamorig:Spine2")
        self.assertEqual(profile["rigidAttachments"], ())
        for region, root in (("arm_left", "Bone_033"), ("arm_right", "Bone_028")):
            descendants = {root}
            for name, parent in zip(skeleton.names, skeleton.parents):
                if parent >= 0 and skeleton.names[parent] in descendants:
                    descendants.add(name)
            self.assertEqual(set(profile["regionBones"][region]), descendants)

    def test_source_idle_contract(self):
        profile = get_profile()
        self.assertTrue(Path(profile["sourceIdleDir"]).is_dir())
        self.assertEqual(profile["sourceIdleGroup"], 2)
        self.assertEqual(profile["sourceIdleFrameCount"], 8)


if __name__ == "__main__":
    unittest.main()
