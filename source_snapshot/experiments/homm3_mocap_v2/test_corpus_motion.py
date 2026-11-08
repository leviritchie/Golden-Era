import unittest

import numpy as np

from corpus_motion import load_motion
from mesh_preview import fk_world_matrices


class FixedMotionTests(unittest.TestCase):
    def fixture(self):
        skin = {"names": ["mount", "seat", "rider"], "parents": np.array([-1, 0, 1]),
                "offsets": np.array([[0., 1., 0.], [1., 0., 0.], [0., .5, 0.]])}
        local = np.tile(np.eye(3), (2, 3, 1, 1))
        local[1, 0] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        offsets = skin["offsets"].copy()
        offsets[0] = 0
        world = np.array([fk_world_matrices(local_rotation=frame, local_translation=offsets,
            parents=skin["parents"], root_world=skin["offsets"][0]) for frame in local])
        raw = {"joint_names": np.array(skin["names"]), "parents": skin["parents"],
               "offsets": skin["offsets"].copy(),
               "local_rotation": local, "joint_world": world, "pred_position": world[:, :, :3, 3].copy()}
        return raw, skin

    def load(self, raw, skin):
        return load_motion(raw, {"sourceIndices": [0, 1]}, {"motionRepresentation": "fixed_composed_fk_v1"},
                           skin, raw["pred_position"][0], [])

    def test_preserves_fk_and_seat_rotation(self):
        raw, skin = self.fixture()
        result = self.load(raw, skin)
        np.testing.assert_array_equal(result["jointWorld"], raw["joint_world"])
        np.testing.assert_allclose(result["jointWorld"][1, 2, :3, 3], [-.5, 2, 0])

    def test_rejects_independently_translated_seat(self):
        raw, skin = self.fixture()
        raw["joint_world"][1, 2, 0, 3] += .1
        with self.assertRaisesRegex(ValueError, "frozen bind FK"):
            self.load(raw, skin)

    def test_rejects_nonrigid_rotations(self):
        raw, skin = self.fixture()
        raw["local_rotation"][1, 0, 0, 0] = 3
        with self.assertRaisesRegex(ValueError, "nonrigid"):
            self.load(raw, skin)

    def test_rejects_unknown_representation(self):
        raw, skin = self.fixture()
        with self.assertRaisesRegex(ValueError, "unsupported"):
            load_motion(raw, {"sourceIndices": [0]}, {"motionRepresentation": "typo"}, skin, raw["pred_position"][0], [])


if __name__ == "__main__":
    unittest.main()
