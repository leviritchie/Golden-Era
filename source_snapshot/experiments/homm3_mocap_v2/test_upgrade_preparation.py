"""Exercise actual preparation consumers, not just profile label coverage."""
import unittest

import numpy as np
import run_shape_preserved as shared
from source_skin_initialization import initialize_source_weights


class UpgradePreparationTests(unittest.TestCase):
    def test_live_assets_have_complete_placeable_rigs_and_owned_weights(self):
        for asset in ("h3_orc_chieftain", "h3_ogre_mage", "h3_cyclops_king", "h3_ogre_brute", "h3_goblin_trapper", "h3_ghost_behemoth"):
            with self.subTest(asset=asset):
                profile = shared.get_profile(asset)
                self.assertEqual(profile["skinInitialization"], "source_joint_map")
                target = shared.load_target_asset(profile)
                donor = shared.load_shape_donor(profile)
                self.assertEqual(set(profile["sourceJointMap"]), set(target["names"]))
                names, parents = donor["jointNames"], donor["bindParents"]
                fit = shared.fit_deformation_bind(
                    donor_names=names, donor_parents=parents,
                    donor_rest=shared.donor_rest_joints(donor),
                    target_names=target["names"], target_rest=target["restWorld"],
                    target_vertices=target["vertices"],
                    target_regions=target["vertexRegions"], profile=profile)
                rig = shared.rig_gate(names=names, parents=parents,
                    fitted=fit["fittedPositions"], offsets=fit["offsets"],
                    profile=profile, helpers=fit["helpers"])
                self.assertTrue(rig["ok"])
                weights = initialize_source_weights(target["sourceDenseWeights"],
                    target["names"], names, target["vertexRegions"], profile)["weights"]
                shared.weight_gate(weights, len(target["vertices"]), len(names))
                bind = shared.bind_world_matrices(fit["offsets"], parents)
                rest = shared.skin_dense(target["vertices"], weights, bind,
                    shared.inverse_bind_matrices(bind))
                np.testing.assert_allclose(rest, target["vertices"], atol=1e-12, rtol=0)

    def test_new_limb_regions_follow_actual_target_subtrees(self):
        for asset, roots in (("h3_goblin_trapper", ("Bone_027", "Bone_032", "Bone_019", "Bone_014")),
                             ("h3_ghost_behemoth", ("Bone_020", "Bone_024", "Bone_012", "Bone_008"))):
            profile = shared.get_profile(asset)
            target = shared.load_target_asset(profile)
            names, parents = target["names"], target["parents"]
            for region, root in zip(("arm_left", "arm_right", "leg_left", "leg_right"), roots):
                with self.subTest(asset=asset, region=region):
                    descendants = {names.index(root)}
                    for index, parent in enumerate(parents):
                        if parent in descendants:
                            descendants.add(index)
                    self.assertEqual(set(profile["regionBones"][region]), {names[i] for i in descendants})
                    self.assertEqual(target["restWorld"][names.index(root), 0] > 0, region.endswith("left"))

    def test_ogre_brute_anatomical_sites_and_owned_subtrees(self):
        profile = shared.get_profile("h3_ogre_brute")
        target = shared.load_target_asset(profile)
        names, parents = target["names"], target["parents"]
        for region, root in (("arm_left", "Bone_027"), ("arm_right", "Bone_022"),
                             ("leg_left", "Bone_009"), ("leg_right", "Bone_014")):
            descendants = {names.index(root)}
            for index, parent in enumerate(parents):
                if parent in descendants:
                    descendants.add(index)
            self.assertEqual(set(profile["regionBones"][region]), {names[i] for i in descendants})
        chains = {chain["name"]: chain for chain in profile["chains"]}
        self.assertEqual(chains["arm_right"]["evidence"][-1], "Bone_019")
        self.assertEqual(chains["arm_left"]["evidence"][-1], "Bone_024")
        self.assertGreater(target["restWorld"][names.index("Bone_018"), 1] -
                           target["restWorld"][names.index("Bone_019"), 1], .4)


if __name__ == "__main__":
    unittest.main()
