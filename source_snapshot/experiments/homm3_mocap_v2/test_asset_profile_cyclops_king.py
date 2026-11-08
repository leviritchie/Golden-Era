import unittest

from asset_profile_cyclops_king import get_profile
from glb_skeleton import load_bind_skeleton


class CyclopsKingProfileTests(unittest.TestCase):
    def test_live_mesh_is_fully_owned_and_wrist_endpoints_are_not_claws(self):
        profile = get_profile()
        skeleton = load_bind_skeleton(profile["mesh"])
        region_bones = [bone for bones in profile["regionBones"].values() for bone in bones]
        self.assertEqual(set(skeleton.names), set(region_bones))
        self.assertEqual(len(region_bones), len(set(region_bones)))
        self.assertEqual(set(skeleton.names), set(profile["sourceJointMap"]))
        self.assertEqual(profile["chains"][2]["evidence"][-1], "Bone_021")
        self.assertEqual(profile["chains"][3]["evidence"][-1], "Bone_026")
        self.assertEqual(profile["leftRightPairs"][0]["evidence"], ("Bone_021", "Bone_026"))
        index = {name: i for i, name in enumerate(skeleton.names)}
        self.assertEqual(skeleton.names[skeleton.parents[index["Bone_021"]]], "Bone_022")
        self.assertEqual(skeleton.names[skeleton.parents[index["Bone_026"]]], "Bone_027")
        self.assertTrue(skeleton.rest_world[index["Bone_021"], 0] > 0.20)
        self.assertTrue(skeleton.rest_world[index["Bone_026"], 0] < -0.20)
        self.assertTrue(skeleton.rest_world[index["Bone_020"], 0] > 0.18)
        self.assertTrue(skeleton.rest_world[index["Bone_025"], 0] > -0.02)

    def test_source_and_hash_are_pinned(self):
        profile = get_profile()
        self.assertTrue(profile["sourceIdleDir"].is_dir())
        self.assertRegex(profile["expectedMeshSha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
