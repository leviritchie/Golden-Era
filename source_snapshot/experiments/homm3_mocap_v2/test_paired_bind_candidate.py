import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paired_bind_candidate as candidate
from asset_profile_ogre import OGRE_MIXAMO


class PairedBindCandidateTests(unittest.TestCase):
    def test_builder_is_opt_in_copy_and_converts_only_polyline_chains(self):
        profile = copy.deepcopy(OGRE_MIXAMO)
        before = copy.deepcopy(profile)
        names = ["j0", "j1"]
        parents = np.asarray([-1, 0])
        offsets = np.zeros((2, 3), dtype=np.float64)
        target = {"names": names, "restWorld": offsets, "vertices": np.zeros((1, 3)),
                  "vertexRegions": np.asarray(["body"]), "sourceSha256": "mesh"}
        donor = {"jointNames": names, "bindParents": parents, "bindOffsets": offsets}
        fit = {"fittedPositions": offsets.copy(), "offsets": offsets.copy(), "helpers": {}}
        identity = np.repeat(np.eye(4)[None], 2, axis=0)
        with mock.patch.object(candidate.shared, "load_target_asset", return_value=target), \
             mock.patch.object(candidate.shared, "load_shape_donor", return_value=donor), \
             mock.patch.object(candidate.shared, "fit_deformation_bind", return_value=fit) as fit_call, \
             mock.patch.object(candidate.shared, "rig_gate"), \
             mock.patch.object(candidate.shared, "bind_world_matrices", return_value=identity), \
             mock.patch.object(candidate.shared, "inverse_bind_matrices", return_value=identity):
            result = candidate.build_paired_bind(profile)
        self.assertEqual(profile, before)
        self.assertEqual([chain["kind"] for chain in profile["chains"]],
                         [chain["kind"] for chain in before["chains"]])
        self.assertEqual(result["names"], names)
        np.testing.assert_array_equal(result["parents"], parents)
        self.assertEqual(result["meshSha256"], "mesh")
        fitted_profile = fit_call.call_args.kwargs["profile"]
        self.assertTrue(all(chain["kind"] == "paired_landmarks" for chain in fitted_profile["chains"] if chain["kind"] != "relative_to_parent"))
        self.assertTrue(all(chain["kind"] == "relative_to_parent" for chain in fitted_profile["chains"] if chain["name"].startswith("head") or chain["name"].startswith("toe")))
        self.assertNotEqual(result["inputProfileHash"], result["candidateProfileHash"])

    def test_builder_does_not_mutate_nested_profile_structures(self):
        profile = copy.deepcopy(OGRE_MIXAMO)
        original_kinds = {chain["name"]: chain["kind"] for chain in profile["chains"]}
        with mock.patch.object(candidate.shared, "load_target_asset", side_effect=ValueError("stop before fit")):
            with self.assertRaisesRegex(ValueError, "stop before fit"):
                candidate.build_paired_bind(profile)
        self.assertEqual({chain["name"]: chain["kind"] for chain in profile["chains"]}, original_kinds)


if __name__ == "__main__":
    unittest.main()
