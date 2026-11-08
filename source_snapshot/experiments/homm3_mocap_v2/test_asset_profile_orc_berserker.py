import hashlib
import unittest

from asset_profile_orc_berserker import ORC_BERSERKER_MIXAMO as PROFILE
from fit_deformation_bind import fit_deformation_bind
from shape_donor import donor_rest_joints, load_shape_donor
from shape_gates import rig_gate
from source_skin_initialization import initialize_source_weights
from target_asset import load_target_asset


class OrcBerserkerProfileTest(unittest.TestCase):
    def test_real_consumer_contract(self):
        target = load_target_asset(PROFILE)
        with open(PROFILE["mesh"], "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), PROFILE["expectedMeshSha256"])
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


if __name__ == "__main__":
    unittest.main()
