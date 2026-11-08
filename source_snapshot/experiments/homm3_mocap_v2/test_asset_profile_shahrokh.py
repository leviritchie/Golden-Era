"""Real Eagle consumer and independently pinned Shahrokh anatomy checks."""
import unittest
import numpy as np
import run_shape_preserved as shared
from asset_profile_shahrokh import get_profile
from source_skin_initialization import initialize_source_weights
from skin_weight_field import WeightField


class ShahrokhTests(unittest.TestCase):
    def test_real_consumer_and_anatomical_ownership(self):
        profile = get_profile()
        target = shared.load_target_asset(profile)
        donor = shared.load_shape_donor(profile)
        self.assertEqual(len(donor["jointNames"]), 50)
        self.assertEqual(set(profile["sourceJointMap"]), set(target["names"]))
        names, parents = target["names"], target["parents"]
        for region, root in (("wing_left", "Bone_023"), ("wing_right", "Bone_026"),
                             ("leg_left", "Bone_013"), ("leg_right", "Bone_009"), ("jaw", "Bone_030")):
            descendants = {names.index(root)}
            for index, parent in enumerate(parents):
                if parent in descendants:
                    descendants.add(index)
            self.assertEqual(set(profile["regionBones"][region]), {names[i] for i in descendants})
            owned = np.isin(np.argmax(target["sourceDenseWeights"], axis=1), list(descendants))
            self.assertTrue(owned.any())
            self.assertTrue(np.all(target["vertexRegions"][owned] == region))
        self.assertEqual(profile["hubs"]["Bip01_Spine1"], "Bone_014")
        fitted = shared.fit_deformation_bind(donor_names=donor["jointNames"], donor_parents=donor["bindParents"],
            donor_rest=shared.donor_rest_joints(donor), target_names=names, target_rest=target["restWorld"],
            target_vertices=target["vertices"], target_regions=target["vertexRegions"], profile=profile)
        self.assertTrue(shared.rig_gate(names=fitted["names"], parents=fitted["parents"], fitted=fitted["fittedPositions"],
            offsets=fitted["offsets"], profile=profile, helpers=fitted["helpers"])["ok"])
        weights = initialize_source_weights(target["sourceDenseWeights"], names, donor["jointNames"], target["vertexRegions"], profile)["weights"]
        field = WeightField(target["vertices"], target["triangles"], weights, target["vertexRegions"],
            donor["jointNames"], profile["regionJoints"], device="cpu")
        self.assertLessEqual(field.support_stats()["maxInfluences"], 8)


if __name__ == "__main__":
    unittest.main()
