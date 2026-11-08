import hashlib
import unittest
from asset_profile_ancient_behemoth import ANCIENT_BEHEMOTH_MIXAMO as PROFILE
from fit_deformation_bind import fit_deformation_bind
from shape_donor import donor_rest_joints, load_shape_donor
from shape_gates import rig_gate
from skin_weight_field import WeightField
from source_skin_initialization import initialize_source_weights
from target_asset import load_target_asset

class AncientBehemothProfileTest(unittest.TestCase):
    def test_real_cpu_consumers_and_anatomical_subtrees(self):
        target = load_target_asset(PROFILE)
        with open(PROFILE["mesh"], "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), PROFILE["expectedMeshSha256"])
        donor = load_shape_donor(PROFILE)
        self.assertEqual(set(PROFILE["sourceJointMap"]), set(target["names"]))
        initialized = initialize_source_weights(target["sourceDenseWeights"], target["names"], donor["jointNames"], target["vertexRegions"], PROFILE)
        self.assertEqual(initialized["weights"].shape, (len(target["vertices"]), len(donor["jointNames"])))
        self.assertLessEqual(max(map(len, PROFILE["regionJoints"].values())), 8)
        WeightField(target["vertices"], target["triangles"], initialized["weights"], target["vertexRegions"], donor["jointNames"], PROFILE["regionJoints"], device="cpu")
        fitted = fit_deformation_bind(donor_names=donor["jointNames"], donor_parents=donor["bindParents"], donor_rest=donor_rest_joints(donor), target_names=target["names"], target_rest=target["restWorld"], target_vertices=target["vertices"], target_regions=target["vertexRegions"], profile=PROFILE)
        self.assertTrue(fitted["ok"])
        self.assertTrue(rig_gate(names=fitted["names"], parents=fitted["parents"], fitted=fitted["fittedPositions"], offsets=fitted["offsets"], profile=PROFILE, helpers=fitted["helpers"])["ok"])
        by_name = {name: target["restWorld"][i] for i, name in enumerate(target["names"])}
        self.assertLess(by_name["Bone_032"][0], 0.0)
        self.assertGreater(by_name["Bone_036"][0], 0.0)
        self.assertLess(by_name["Bone_005"][0], 0.0)
        self.assertGreater(by_name["Bone_009"][0], 0.0)
        parents = dict(zip(target["names"], target["parents"]))
        for anchor, region in (("Bone_036", "arm_left"), ("Bone_032", "arm_right"), ("Bone_009", "leg_left"), ("Bone_005", "leg_right")):
            for bone in PROFILE["regionBones"][region]:
                current = bone
                reached = False
                while current in parents and parents[current] >= 0:
                    current = target["names"][parents[current]]
                    if current == anchor:
                        reached = True
                        break
                self.assertTrue(reached or bone == anchor, (region, anchor, bone))
        self.assertEqual(PROFILE["sourceJointMap"]["Bone_011"], "mixamorig:Spine2")
        self.assertEqual(PROFILE["sourceJointMap"]["Bone_010"], "mixamorig:Spine2")
        self.assertEqual(PROFILE["sourceJointMap"]["Bone_035"], "mixamorig:LeftForeArm")
        self.assertEqual(PROFILE["sourceJointMap"]["Bone_034"], "mixamorig:LeftHand")
        self.assertEqual(PROFILE["chains"][2]["evidence"][-1], "Bone_034")
        self.assertEqual(PROFILE["chains"][3]["evidence"][-1], "Bone_030")
        self.assertEqual(PROFILE["rigidAttachments"], ())
        self.assertEqual(PROFILE["headBone"], "Bone_027")
        self.assertEqual(PROFILE["neckBone"], "Bone_028")

if __name__ == "__main__":
    unittest.main()
