import unittest
import numpy as np
from unittest import mock

from experiments.homm3_mocap_v2.ownership_candidate_validation import compare_probes, probe_report, validate_invariants


class OwnershipCandidateValidationTests(unittest.TestCase):
    def setUp(self):
        vertices = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0]])
        self.base = {"vertices": vertices, "triangles": np.array([[0, 1, 2]]), "uvs": np.zeros((3, 2)),
                     "albedo": np.zeros((3, 4), dtype=np.uint8), "names": np.array(["root", "hand"]),
                     "parents": np.array([-1, 0]), "offsets": np.zeros((2, 3)),
                     "captureOffsets": np.zeros((2, 3)),
                     "inverseBind": np.repeat(np.eye(4)[None], 2, axis=0),
                     "weights": np.array([[1., 0], [0, 1], [1, 0]]), "regions": np.array(["body", "weapon", "body"]),
                     "restAnchors": np.zeros((2, 3))}

    def test_normal_candidate_and_rigid_weapon(self):
        result = validate_invariants(self.base, self.base, ["weapon"])
        self.assertTrue(result["invariants"])
        self.assertEqual(result["maxInfluences"], 1)

    def test_rejects_invariant_and_influence_changes(self):
        changed = dict(self.base); changed["uvs"] = self.base["uvs"].copy(); changed["uvs"][0, 0] = 1
        with self.assertRaises(ValueError): validate_invariants(self.base, changed)
        changed = dict(self.base); changed["weights"] = self.base["weights"].copy(); changed["weights"][1] = [.5, .5]
        with self.assertRaises(ValueError): validate_invariants(self.base, changed, ["weapon"])

    def test_rejects_divergent_coincident_weights(self):
        original = dict(self.base); original["vertices"] = np.array([[0., 0, 0], [0., 0, 0], [0, 1, 0]])
        candidate = dict(original); candidate["weights"] = np.array([[1., 0], [0, 1], [1, 0]])
        with self.assertRaises(ValueError): validate_invariants(original, candidate)

    def test_rest_anchor_evidence_is_optional_but_symmetric(self):
        original = dict(self.base)
        candidate = dict(self.base)
        original.pop("restAnchors")
        candidate.pop("restAnchors")
        self.assertTrue(validate_invariants(original, candidate)["invariants"])
        with self.assertRaisesRegex(ValueError, "present in both"):
            validate_invariants(original, self.base)
        changed = dict(self.base)
        changed["restAnchors"] = self.base["restAnchors"].copy()
        changed["restAnchors"][0, 0] = 1
        with self.assertRaisesRegex(ValueError, "restAnchors"):
            validate_invariants(self.base, changed)

    def test_probe_report_requires_all_three_targets(self):
        with self.assertRaises(ValueError): probe_report(self.base)

    def test_compare_probes_marks_frozen_candidate(self):
        names = np.array(["rider:mixamorig:RightArm", "rider:mixamorig:LeftArm", "mount:Bip01_Neck"])
        original = dict(self.base, names=names, parents=np.array([-1, -1, -1]), weights=np.eye(3),
                        restAnchors=np.zeros((3, 3)), inverseBind=np.repeat(np.eye(4)[None], 3, axis=0),
                        regions=np.array(["rider_arm_right", "rider_arm_left", "mount_head"]))
        candidate = dict(original)
        calls = [0]
        def fake_probe(vertices, *args, **kwargs):
            calls[0] += 1
            return {"moved": vertices + (0.2 if calls[0] % 2 else 0.0)}
        with mock.patch("experiments.homm3_mocap_v2.ownership_candidate_validation.probe", side_effect=fake_probe):
            result = compare_probes(original, candidate)
        self.assertFalse(result["motionRetentionPassed"])
        self.assertGreater(result["retentionFailureCount"], 0)


if __name__ == "__main__": unittest.main()
