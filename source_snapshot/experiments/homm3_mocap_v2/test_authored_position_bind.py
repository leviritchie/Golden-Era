"""Physical landmarks are source-pinned positions, not mislabeled source bones."""
import copy
import unittest

import numpy as np

from fit_deformation_bind import BindFitError, fit_deformation_bind


class AuthoredPositionTests(unittest.TestCase):
    def fixture(self):
        points = [[0., 0., 0.], [0., .6, 0.], [.8, .6, .1]]
        return dict(donor_names=["root", "ankle", "toe"],
                    donor_parents=np.array([-1, 0, 1]),
                    donor_rest=np.array([[0., 0., 0.], [0., 1., 0.], [0., 2., 0.]]),
                    target_names=["a", "b", "c"],
                    target_rest=np.array([[0., 0., 0.], [0., .2, 0.], [1., .2, 0.]]),
                    target_vertices=np.array([[-1., -1., -1.], [1., 1., 1.]]),
                    target_regions=np.array(["leg", "leg"]),
                    profile={"expectedMeshSha256": "a" * 64, "hubs": {}, "leftRightPairs": [],
                             "chains": [{"name": "physical_foot", "kind": "authored_positions",
                                         "donor": ["root", "ankle", "toe"], "positions": points,
                                         "sourceMeshSha256": "a" * 64,
                                         "coordinateSpace": "target_mesh_space",
                                         "evidence": "Physical landmarks reviewed in original front/side mesh views"}]})

    def test_positions_are_exact_and_recorded_without_mutating_inputs(self):
        data = self.fixture()
        before = copy.deepcopy(data)
        fit = fit_deformation_bind(**data)
        np.testing.assert_array_equal(fit["fittedPositions"], data["profile"]["chains"][0]["positions"])
        np.testing.assert_array_equal(data["target_rest"], before["target_rest"])
        self.assertEqual(data["profile"], before["profile"])
        self.assertEqual(fit["notes"][0]["sourceMeshSha256"], "a" * 64)
        self.assertEqual(fit["notes"][0]["coordinateSpace"], "target_mesh_space")

    def test_bad_provenance_coordinates_or_identity_are_rejected(self):
        invalid = (
            ("sourceMeshSha256", "b" * 64), ("sourceMeshSha256", ""),
            ("coordinateSpace", "blender_world"), ("evidence", ""),
            ("donor", ["root", "ankle", "unknown"]), ("donor", ["root", "ankle", "ankle"]),
            ("positions", [[0, 0, 0]]),
            ("positions", [[0, 0, 0], [0, 1], [1, 1, 0]]),
            ("positions", [[0, 0, 0], [0, float("nan"), 0], [1, 1, 0]]),
            ("positions", [[0, 0, 0], [0, float("inf"), 0], [1, 1, 0]]),
            ("positions", [[0, 0, 0], [0, 2, 0], [1, 1, 0]]),
            ("positions", [["0", "0", "0"]] * 3),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                data = self.fixture()
                data["profile"]["chains"][0][key] = value
                with self.assertRaises(BindFitError):
                    fit_deformation_bind(**data)

    def test_no_earlier_or_later_placement_can_replace_authored_positions(self):
        data = self.fixture()
        data["profile"]["hubs"] = {"root": "a"}
        with self.assertRaisesRegex(BindFitError, "overwrite placed"):
            fit_deformation_bind(**data)
        data = self.fixture()
        data["profile"]["chains"].append({"name": "bad_override", "kind": "paired_landmarks",
                                           "donor": ["ankle"], "evidence": ["b"]})
        with self.assertRaisesRegex(BindFitError, "overwrote authored"):
            fit_deformation_bind(**data)

    def test_degenerate_authored_bones_still_fail_existing_gate(self):
        data = self.fixture()
        data["profile"]["chains"][0]["positions"][2] = [0., .6, 0.]
        with self.assertRaisesRegex(BindFitError, "degenerate articulated"):
            fit_deformation_bind(**data)


if __name__ == "__main__":
    unittest.main()
