import hashlib
import unittest
from pathlib import Path

from audit_homm3_mesh_coverage import build_inventory


class MeshCoverageAuditTests(unittest.TestCase):
    def test_union_inventory_exposes_current_gaps(self):
        inventory = build_inventory()
        self.assertEqual(inventory["unitCount"], 275)
        self.assertEqual(inventory["counts"]["smartrigPresent"], 243)
        self.assertEqual(inventory["counts"]["meshPresentSmartrigMissing"], 32)
        self.assertEqual(inventory["counts"]["customRigPresent"], 29)
        self.assertEqual(inventory["counts"]["meshMissing"], 0)

    def test_meshy7_outputs_are_meshes_pending_rigging(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "h3_water_elemental")
        self.assertEqual(row["status"], "mesh_present_smartrig_missing")
        self.assertEqual(row["meshKind"], "meshy7_generated_mesh")
        self.assertIsNone(row["smartrig"])

    def test_named_upscale_wins_over_retry_still(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "h3_satyr")
        self.assertEqual(row["imageInputKind"], "aaa_upscale")
        self.assertTrue(row["imageInput"].endswith("artifacts/creature_aaa_3d_upscale/h3_satyr.png"))

    def test_boar_rider_uses_pinned_mesh_without_fabricating_a_smartrig(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "toa_boar_rider")
        self.assertEqual(row["status"], "mesh_present_smartrig_missing")
        self.assertTrue(row["mesh"].endswith("boar_rider_t2/generated.glb"))
        self.assertIsNone(row["smartrig"])

    def test_wolf_rider_and_raider_use_their_own_swapped_basenames(self):
        # 2026-09-27: the files were renamed so the basename is the semantic unit; pin by hash so a
        # reverted swap fails here (rider = grey wolf 2fb1bb07..., raider = black wolf b15de4cf...).
        inventory = build_inventory()
        for sid, sha_prefix in (("h3_wolf_rider", "2fb1bb070082"), ("h3_wolf_raider", "b15de4cfcd0a")):
            row = next(item for item in inventory["records"] if item["unitSid"] == sid)
            self.assertEqual(row["status"], "smartrig_present")
            self.assertTrue(row["smartrig"].endswith(f"{sid}_smartrigged.glb"))
            self.assertIsNone(row.get("smartrigIdentity"))
            self.assertTrue(hashlib.sha256(Path(row["smartrig"]).read_bytes()).hexdigest().startswith(sha_prefix))

    def test_explicit_luna_retry_candidate_is_visible_without_promotion(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "hota_cove_nix_praetorian")
        self.assertEqual(row["customRigKind"], "luna_blender_envelope_retry")
        self.assertTrue(row["customRig"].endswith("retry_nix/hota_cove_nix_praetorian/hota_cove_nix_praetorian_smartrigged.glb"))
        self.assertIsNone(row["smartrig"])

    def test_sharpshooter_luna_retry_candidate_is_visible_without_promotion(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "h3_sharpshooter")
        self.assertEqual(row["customRigKind"], "luna_blender_envelope_quantization_retry")
        self.assertTrue(row["customRig"].endswith("meshy7_luna_batch/h3_sharpshooter/h3_sharpshooter/h3_sharpshooter_smartrigged.glb"))
        self.assertIsNone(row["smartrig"])

    def test_pegasus_replacement_is_selected_and_demo_is_quarantined(self):
        inventory = build_inventory()
        row = next(item for item in inventory["records"] if item["unitSid"] == "h3_pegasus")
        self.assertEqual(row["status"], "mesh_present_smartrig_missing")
        self.assertEqual(row["meshKind"], "meshy7_generated_mesh_replacement")
        self.assertEqual(row["smartrigIdentity"], "verified_source_candidate")
        self.assertIsNone(row["smartrig"])
        self.assertTrue(any("h3_pegasus" in name for name in row["quarantineEvidence"]))

    def test_verified_replacements_are_selected_and_old_meshes_are_quarantined(self):
        inventory = build_inventory()
        for sid in ("h3_mechanic_upg_alt", "h3_paokai"):
            row = next(item for item in inventory["records"] if item["unitSid"] == sid)
            self.assertEqual(row["status"], "mesh_present_smartrig_missing")
            self.assertEqual(row["meshKind"], "meshy7_generated_mesh_replacement")
            self.assertEqual(row["smartrigIdentity"], "verified_source_candidate")
            self.assertIsNone(row["smartrig"])
            self.assertTrue(row["mesh"].endswith(f"meshy71_repair_candidates/{sid}/source/mesh.glb"))
            self.assertTrue(any(sid in name for name in row["quarantineEvidence"]))


if __name__ == "__main__":
    unittest.main()
