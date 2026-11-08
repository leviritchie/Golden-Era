"""Real-asset regression for the wood elf's preserved bow and hand attachment."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.glb_io import load_render_surface, load_mesh, read_glb
from owned_rerig.prop_attachment import repair_prop_attachments
from fit_mesh_rest_pipeline import skin

ROOT = Path(__file__).resolve().parents[2]
ELF = ROOT / "artifacts/meshy_downloads/meshy71_repair_candidates/h3_wood_elf"


@unittest.skipUnless((ELF / "mesh-fitted-v1/fitted_bind.glb").is_file(), "Wood elf pilot inputs absent")
class WoodElfRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_render_surface(ELF / "t-pose/mesh.glb")
        mesh = load_mesh(ELF / "mesh-fitted-v1/fitted_bind.glb")
        doc = read_glb(ELF / "mesh-fitted-v1/fitted_bind.glb")["json"]
        cls.names = [doc["nodes"][i]["name"] for i in doc["skins"][0]["joints"]]
        cls.heads = np.array(json.loads((ELF / "mesh-fitted-v1/report.json").read_text())["fit"]["heads"])
        config = json.loads((Path(__file__).parent / "wood_elf_prop_attachment.json").read_text())
        cls.result = repair_prop_attachments(surface=cls.source, joints=mesh.joints, weights=mesh.weights,
                                            heads=cls.heads, names=cls.names, config=config)

    def test_source_faces_uvs_and_body_are_preserved(self):
        r = self.result
        ids = r["sourceVertices"]
        np.testing.assert_array_equal(ids[r["surface"]["indices"]], self.source["indices"])
        np.testing.assert_array_equal(r["surface"]["uvs"], self.source["uvs"][ids])
        body = r["propOwners"] == -1
        np.testing.assert_array_equal(r["surface"]["positions"][body], self.source["positions"][ids[body]])
        owners = r["propOwners"][r["surface"]["indices"].reshape(-1, 3)]
        self.assertTrue(np.all(owners == owners[:, :1]))
        selected_source = self.source["positions"][ids[r["propOwners"] == 0]]
        self.assertLess(selected_source[:, 0].min(), -.70)
        self.assertGreater(selected_source[:, 0].max(), .70)
        self.assertEqual(r["report"]["sourceFaces"], 8203)

    def test_all_saved_frames_keep_bow_rigid_and_grip_hand_relative(self):
        r = self.result
        exported = load_mesh(ELF / "mesh-fitted-v2/fitted_bind.glb")
        selected = r["propOwners"] == 0
        points = exported.positions[selected]
        joints, weights = exported.joints[selected], exported.weights[selected]
        lengths = np.linalg.norm(points[1:] - points[0], axis=1)
        bone = self.names.index("LeftHand")
        grip = np.array(r["report"]["props"][0]["targetGrip"])
        relative = grip - self.heads[bone]
        with np.load(ELF / "mesh-fitted-v2/retargeted_motion.npz") as motion:
            self.assertEqual(len(motion["rotations"]), 79)
            for rotations, offsets in zip(motion["rotations"], motion["offsets"]):
                rot, offset = rotations[bone], offsets[bone]
                moved = skin(points, joints, weights, rotations, offsets)
                np.testing.assert_allclose(moved, points @ rot.T + offset, atol=1e-6)
                np.testing.assert_allclose(np.linalg.norm(moved[1:] - moved[0], axis=1), lengths, atol=1e-12)
                np.testing.assert_allclose(rot @ grip + offset - (rot @ self.heads[bone] + offset), rot @ relative, atol=1e-12)

    def test_saved_export_matches_recipe_geometry_normals_and_texture(self):
        loaded = load_render_surface(ELF / "mesh-fitted-v2/fitted_bind.glb")
        for key in ("positions", "normals", "uvs"):
            np.testing.assert_allclose(loaded[key], self.result["surface"][key], atol=1e-7)
        np.testing.assert_array_equal(loaded["baseColor"], self.source["baseColor"])
        np.testing.assert_array_equal(loaded["indices"], self.result["surface"]["indices"])
        skin = load_mesh(ELF / "mesh-fitted-v2/fitted_bind.glb")
        np.testing.assert_array_equal(skin.joints, self.result["joints"])
        np.testing.assert_allclose(skin.weights, self.result["weights"], atol=1e-7)


if __name__ == "__main__":
    unittest.main()
