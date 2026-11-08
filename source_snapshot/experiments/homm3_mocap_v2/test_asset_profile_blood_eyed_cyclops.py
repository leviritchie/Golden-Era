import unittest
import numpy as np

from asset_profile_blood_eyed_cyclops import get_profile
from glb_skeleton import load_bind_skeleton
import run_shape_preserved as shared
from source_skin_initialization import initialize_source_weights


class BloodEyedCyclopsProfileTests(unittest.TestCase):
    def test_live_mesh_is_fully_mapped_and_wrist_endpoints_precede_claws(self):
        profile = get_profile()
        skeleton = load_bind_skeleton(profile["mesh"])
        bones = [bone for region in profile["regionBones"].values() for bone in region]
        self.assertEqual(set(skeleton.names), set(bones))
        self.assertEqual(len(bones), len(set(bones)))
        self.assertEqual(set(skeleton.names), set(profile["sourceJointMap"]))
        index = {name: i for i, name in enumerate(skeleton.names)}
        self.assertEqual(skeleton.names[skeleton.parents[index["Bone_017"]]], "Bone_018")
        self.assertEqual(skeleton.names[skeleton.parents[index["Bone_022"]]], "Bone_023")
        self.assertGreater(float(skeleton.rest_world[index["Bone_017"], 0]), 0.15)
        self.assertLess(float(skeleton.rest_world[index["Bone_022"], 0]), -0.20)
        self.assertEqual(profile["leftRightPairs"][0]["evidence"], ("Bone_017", "Bone_022"))

    def test_source_and_hash_are_pinned(self):
        profile = get_profile()
        self.assertTrue(profile["sourceIdleDir"].is_dir())
        self.assertRegex(profile["expectedMeshSha256"], r"^[0-9a-f]{64}$")

    def test_actual_cpu_preparation_consumers_pass(self):
        profile = get_profile()
        target = shared.load_target_asset(profile)
        donor = shared.load_shape_donor(profile)
        fit = shared.fit_deformation_bind(
            donor_names=donor["jointNames"], donor_parents=donor["bindParents"],
            donor_rest=shared.donor_rest_joints(donor),
            target_names=target["names"], target_rest=target["restWorld"],
            target_vertices=target["vertices"], target_regions=target["vertexRegions"],
            profile=profile)
        rig = shared.rig_gate(names=donor["jointNames"], parents=donor["bindParents"],
                              fitted=fit["fittedPositions"], offsets=fit["offsets"],
                              profile=profile, helpers=fit["helpers"])
        self.assertTrue(rig["ok"])
        weights = initialize_source_weights(target["sourceDenseWeights"], target["names"],
            donor["jointNames"], target["vertexRegions"], profile)["weights"]
        shared.weight_gate(weights, len(target["vertices"]), len(donor["jointNames"]))
        bind = shared.bind_world_matrices(fit["offsets"], donor["bindParents"])
        rest = shared.skin_dense(target["vertices"], weights, bind,
                                 shared.inverse_bind_matrices(bind))
        np.testing.assert_allclose(rest, target["vertices"], atol=1e-12, rtol=0)


if __name__ == "__main__":
    unittest.main()
