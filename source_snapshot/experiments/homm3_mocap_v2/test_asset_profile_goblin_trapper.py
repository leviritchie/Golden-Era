import hashlib
import unittest

from asset_profile_goblin_trapper import GOBLIN_TRAPPER_MIXAMO as PROFILE
from fit_deformation_bind import fit_deformation_bind
from glb_skeleton import load_bind_skeleton
from shape_donor import donor_rest_joints, load_shape_donor
from shape_gates import rig_gate
from source_skin_initialization import initialize_source_weights
from target_asset import load_target_asset


class GoblinTrapperProfileTest(unittest.TestCase):
    def test_real_consumer_contract(self):
        target = load_target_asset(PROFILE)
        with open(PROFILE["mesh"], "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), PROFILE["expectedMeshSha256"])
        skeleton = load_bind_skeleton(PROFILE["mesh"])
        self.assertEqual(len(skeleton.names), 79)
        donor = load_shape_donor(PROFILE)
        self.assertEqual(set(PROFILE["sourceJointMap"]), set(target["names"]))
        initialized = initialize_source_weights(
            target["sourceDenseWeights"], target["names"], donor["jointNames"], target["vertexRegions"], PROFILE
        )
        self.assertEqual(initialized["weights"].shape, (len(target["vertices"]), len(donor["jointNames"])))
        fitted = fit_deformation_bind(
            donor_names=donor["jointNames"], donor_parents=donor["bindParents"], donor_rest=donor_rest_joints(donor),
            target_names=target["names"], target_rest=target["restWorld"], target_vertices=target["vertices"],
            target_regions=target["vertexRegions"], profile=PROFILE,
        )
        self.assertTrue(fitted["ok"])
        self.assertTrue(rig_gate(names=fitted["names"], parents=fitted["parents"], fitted=fitted["fittedPositions"], offsets=fitted["offsets"], profile=PROFILE, helpers=fitted["helpers"])["ok"])

    def test_side_and_terminal_evidence(self):
        target = load_target_asset(PROFILE)
        names = target["names"]
        coords = target["restWorld"]
        by_name = {name: coords[index] for index, name in enumerate(names)}
        self.assertGreater(by_name["Bone_027"][0], 0.0)
        self.assertGreater(by_name["Bone_019"][0], 0.0)
        self.assertLess(by_name["Bone_032"][0], 0.0)
        self.assertLess(by_name["Bone_014"][0], 0.0)
        self.assertEqual(PROFILE["headBone"], "Bone_021")
        self.assertEqual(PROFILE["chains"][0]["evidence"], ("Bone_022", "Bone_021"))
        self.assertEqual(PROFILE["rigidAttachments"], ())


if __name__ == "__main__":
    unittest.main()
