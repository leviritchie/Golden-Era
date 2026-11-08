"""Analytic checks for explicit, unsmoothed two-bone hand clearance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.retarget_clearance import apply_hand_clearance
from owned_rerig.rest_retarget import _swing
from test_rest_retarget import rotation


NAMES = ["Arm", "Elbow", "RightHand", "RightUpLeg", "RightLeg"]
PARENTS = [None, 0, 1, 0, 3]
HASH = "a" * 64


def fixture():
    heads = np.array([[0, 0, 0], [.5, .6, 0], [1, 0, 0], [.9, -.5, 0], [.9, .5, 0]])
    rotations = np.tile(np.eye(3), (2, 5, 1, 1))
    # Incoming roll around each link is real state that a position-only rebuild would lose.
    for joint in (1, 2):
        rotations[:, joint] = rotation(heads[joint] - heads[PARENTS[joint]], .47)
    points = np.repeat(heads[None], 2, axis=0)
    motion = {"frame_joints": points, "rotations": rotations,
              "offsets": points - np.einsum("fjab,jb->fja", rotations, heads),
              "metadata": {"source": "pred_position"}}
    config = {"schema": "retarget_clearance.v1", "sourceMeshSha256": HASH,
              "maxCorrection": .3,
              "constraints": [{"hand": "RightHand", "colliderStart": "RightUpLeg",
                               "colliderEnd": "RightLeg", "radius": .2}]}
    return motion, heads, config


class HandClearanceTests(unittest.TestCase):
    def run_case(self, motion, heads, config, **kwargs):
        return apply_hand_clearance(motion, heads, kwargs.get("parents", PARENTS),
                                    kwargs.get("names", NAMES), config, kwargs.get("hash", HASH))

    def test_reachable_lengths_pole_roll_and_proper_rotations(self):
        motion, heads, config = fixture()
        original, original_heads, original_config = deepcopy(motion), heads.copy(), deepcopy(config)
        result = self.run_case(motion, heads, config)
        np.testing.assert_allclose(result["frame_joints"][:, 2], [[1.1, 0, 0]] * 2, atol=1e-12)
        expected_elbow = [.55, np.sqrt(.61 - .55**2), 0]
        np.testing.assert_allclose(result["frame_joints"][:, 1], [expected_elbow] * 2, atol=1e-12)
        for j in (1, 2):
            parent = PARENTS[j]
            old_vec = heads[j] - heads[parent]
            new_vec = result["frame_joints"][0, j] - result["frame_joints"][0, parent]
            self.assertAlmostEqual(np.linalg.norm(new_vec), np.linalg.norm(old_vec))
            delta = _swing(old_vec[None], new_vec[None], motion["rotations"][0, j, :, 0][None])[0]
            np.testing.assert_allclose(delta.T @ result["rotations"][0, j],
                                       motion["rotations"][0, j], atol=1e-12)
        r = result["rotations"]
        np.testing.assert_allclose(r @ r.swapaxes(-1, -2), np.broadcast_to(np.eye(3), r.shape), atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(r), 1, atol=1e-12)
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", r, heads) + result["offsets"],
                                   result["frame_joints"], atol=1e-12)
        for key in ("frame_joints", "rotations", "offsets"):
            np.testing.assert_array_equal(motion[key], original[key])
            np.testing.assert_array_equal(result[key][:, [0, 3, 4]], original[key][:, [0, 3, 4]])
        np.testing.assert_array_equal(heads, original_heads)
        self.assertEqual(config, original_config)
        result["metadata"]["source"] = "changed"
        self.assertEqual(motion["metadata"]["source"], "pred_position")
        self.assertEqual(result["clearanceReport"]["changedFrames"], 2)
        self.assertAlmostEqual(result["clearanceReport"]["maxCorrection"], .1)
        self.assertLessEqual(result["clearanceReport"]["maxResidual"], 1e-12)
        self.assertFalse(result["clearanceReport"]["accepted"])

    def test_contact_free_is_exact_noop(self):
        motion, heads, config = fixture()
        config["constraints"][0]["radius"] = .05
        result = self.run_case(motion, heads, config)
        for key in ("frame_joints", "rotations", "offsets"):
            np.testing.assert_array_equal(result[key], motion[key])
            self.assertFalse(np.shares_memory(result[key], motion[key]))
        self.assertEqual(result["clearanceReport"]["changedFrames"], 0)
        self.assertEqual(result["clearanceReport"]["maxCorrection"], 0)

    def test_unreachable_and_maximum_reject_without_mutation(self):
        for radius, maximum, message in ((2, 4, "unreachable"), (.2, .05, "maxCorrection")):
            motion, heads, config = fixture()
            config["constraints"][0]["radius"] = radius
            config["maxCorrection"] = maximum
            original = deepcopy(motion)
            with self.assertRaisesRegex(ValueError, message):
                self.run_case(motion, heads, config)
            for key in ("frame_joints", "rotations", "offsets"):
                np.testing.assert_array_equal(motion[key], original[key])

    def test_singular_radial_pole_and_segment_rejected(self):
        for kind, message in (("radial", "radial"), ("pole", "pole"), ("segment", "segment")):
            motion, heads, config = fixture()
            if kind == "radial": heads[3:, 0] = 1
            elif kind == "pole": heads[1] = [.5, 0, 0]; heads[2] = [1.5, 0, 0]; heads[3:, 0] = 1.6
            else: heads[4] = heads[3]
            motion["frame_joints"][:] = heads
            motion["rotations"][:] = np.eye(3)
            motion["offsets"][:] = 0
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, message):
                self.run_case(motion, heads, config)

    def test_invalid_config_names_source_and_outgoing_rejected(self):
        motion, heads, config = fixture()
        with self.assertRaisesRegex(ValueError, "sourceMeshSha256"):
            self.run_case(motion, heads, config, hash="b" * 64)
        for key, value in (("schema", "wrong"), ("maxCorrection", 0), ("maxCorrection", np.inf),
                           ("constraints", [])):
            bad = deepcopy(config); bad[key] = value
            with self.assertRaises(ValueError): self.run_case(motion, heads, bad)
        for key, value in (("hand", "Missing"), ("radius", -1), ("colliderEnd", "Elbow")):
            bad = deepcopy(config); bad["constraints"][0][key] = value
            with self.assertRaises(ValueError): self.run_case(motion, heads, bad)
        with self.assertRaisesRegex(ValueError, "unique"):
            self.run_case(motion, heads, config, names=["same"] * 5)
        with self.assertRaisesRegex(ValueError, "outgoing"):
            self.run_case({**motion, "skin_rotation_sources": np.arange(5)}, heads, config)
        with self.assertRaisesRegex(ValueError, "already"):
            self.run_case(self.run_case(motion, heads, config), heads, config)

    def test_invalid_motion_rejected(self):
        for kind, message in (("shape", "shapes"), ("finite", "finite"), ("rotation", "proper")):
            motion, heads, config = fixture()
            if kind == "shape": motion["offsets"] = np.zeros((1, 3))
            elif kind == "finite": motion["frame_joints"][0, 0, 0] = np.nan
            else: motion["rotations"][0, 1, 0, 0] = 2
            with self.assertRaisesRegex(ValueError, message): self.run_case(motion, heads, config)


if __name__ == "__main__":
    unittest.main()
