"""Data profile contract checks, with no mesh generation or GPU work."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import structured_profiles as registry
from asset_profile_hobgoblin import HOBGOBLIN_MIXAMO


class StructuredProfilesTests(unittest.TestCase):
    def document(self):
        anatomy = json.loads(json.dumps({k: HOBGOBLIN_MIXAMO[k] for k in registry.ANATOMY_FIELDS}))
        return {"schema": registry.SCHEMA, "assetId": "test", "displayName": "Test",
                "status": "authored", "mesh": "test.glb", "meshSha256": "a" * 64,
                "donorRecipe": "mixamo-25-v1", "sourceSelectionReason": "test fixture",
                "anatomy": anatomy, "anatomySha256": registry.anatomy_hash(anatomy)}

    def test_existing_recipe_can_be_expressed_as_data(self):
        data = self.document()
        names = list(data["anatomy"]["sourceJointMap"])
        profile = registry.validate_document(data, "test", names)
        self.assertEqual(profile["sourceJointMap"], HOBGOBLIN_MIXAMO["sourceJointMap"])
        self.assertTrue(profile["requireCompleteRegionCoverage"])
        self.assertEqual(profile["visualAcceptance"], "unreviewed_candidate")

    def test_explicit_draft_is_never_a_usable_profile(self):
        with patch.object(Path, "read_bytes", return_value=b'{"status": "anatomy-unreviewed"}'):
            with self.assertRaisesRegex(ValueError, "draft cannot prepare"):
                registry.load_registered_profile("draft_fixture", Path("draft.json"))

    def test_every_registered_profile_loads(self):
        registered = registry.registered_profiles()
        self.assertIn("h3_pikeman", registered)
        self.assertIn("h3_archer", registered)
        self.assertIn("h3_marksman", registered)
        self.assertIn("h3_monk", registered)
        self.assertIn("h3_swordsman", registered)
        expected_joints = {"h3_pikeman": 65, "h3_archer": 69, "h3_marksman": 73, "h3_monk": 14, "h3_swordsman": 68}
        for asset, path in registered.items():
            with self.subTest(asset=asset):
                profile = registry.load_registered_profile(asset, path)
                self.assertEqual(profile["assetId"], asset)
                self.assertEqual(profile["visualAcceptance"], "unreviewed_candidate")
                if asset in expected_joints:
                    self.assertEqual(len(profile["sourceJointMap"]), expected_joints[asset])

    def test_duplicate_keys_do_not_silently_replace_mapping(self):
        with patch.object(Path, "read_text", return_value='{"profiles":{"a":"one","a":"two"}}'):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                registry.read_document(Path("test.json"))

    def test_changed_anatomy_and_unknown_recipe_rejected(self):
        data = self.document()
        names = list(data["anatomy"]["sourceJointMap"])
        data["anatomy"]["sourceJointMap"][names[0]] = "invented"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            registry.validate_document(data, "test", names)
        data["anatomySha256"] = registry.anatomy_hash(data["anatomy"])
        with self.assertRaisesRegex(ValueError, "unknown donor"):
            registry.validate_document(data, "test", names)
        data = self.document()
        data["donorRecipe"] = "unknown"
        with self.assertRaisesRegex(ValueError, "donor recipe"):
            registry.validate_document(data, "test", names)

    def test_missing_region_or_mapping_cannot_default_to_torso(self):
        for field in ("regionBones", "sourceJointMap"):
            data = self.document()
            names = list(data["anatomy"]["sourceJointMap"])
            if field == "regionBones":
                data["anatomy"][field]["torso"].remove("Bone_000")
            else:
                del data["anatomy"][field]["Bone_000"]
            data["anatomySha256"] = registry.anatomy_hash(data["anatomy"])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "missing region|cover every"):
                registry.validate_document(data, "test", names)

    def test_wrong_identity_and_incomplete_document_rejected(self):
        data = self.document()
        names = list(data["anatomy"]["sourceJointMap"])
        with self.assertRaisesRegex(ValueError, "identity"):
            registry.validate_document(data, "other", names)
        del data["anatomy"]["hubs"]
        with self.assertRaisesRegex(ValueError, "complete field set"):
            registry.validate_document(data, "test", names)

    def test_shipping_gate_checks_only_registered_selections(self):
        with patch.object(registry, "load_registered_profile", side_effect=ValueError("mesh hash mismatch")) as load:
            errors = registry.validate_selected_profiles([{"assetId": "h3_pikeman"}, {"assetId": "h3_goblin"}])
        load.assert_called_once()
        self.assertEqual(len(errors), 1)
        self.assertIn("mesh hash mismatch", errors[0])

    def test_delivery_validator_invokes_registered_gate_before_payload(self):
        from tools import validate_homm3_mocap_delivery_contract as delivery
        selection = {"schema": "stronghold-current-mocap-ingame-test-selection-v1",
                     "units": [{"assetId": "h3_pikeman", "labSid": "h3_pikeman"}]}
        from experiments.homm3_mocap_v2 import structured_profiles as shipping_registry
        with patch.object(delivery, "_load", return_value=selection), patch.object(
                shipping_registry, "load_registered_profile", side_effect=ValueError("fixture draft cannot prepare")):
            errors = delivery.validate(rollout_dir=Path("missing"), selection_path=Path("selection.json"))
        self.assertTrue(any("draft cannot prepare" in error for error in errors))

    def test_selected_artifact_must_pin_current_authored_profile(self):
        current = {"structuredProfileSha256": "b" * 64}
        with patch.object(registry, "load_registered_profile", return_value=current), \
                patch.object(registry, "registered_profiles", return_value={"h3_pikeman": Path("profile.json")}), \
                patch.object(Path, "read_bytes", return_value=b"report"), \
                patch.object(registry, "read_document", return_value=current):
            for old_hash in (None, "a" * 64):
                row = {"assetId": "h3_pikeman", "structuredProfileSha256": old_hash}
                with self.subTest(old_hash=old_hash):
                    errors = registry.validate_selected_profiles([row])
                    self.assertTrue(any("selected structured profile hash" in error for error in errors))
            self.assertEqual(registry.validate_selected_profiles([
                {"assetId": "h3_pikeman", "structuredProfileSha256": "b" * 64,
                 "sourceReport": "report.json",
                 "sourceReportSha256": registry.hashlib.sha256(b"report").hexdigest()}]), [])


    def test_ownership_selection_requires_pinned_passing_fit(self):
        current = {"structuredProfileSha256": "b" * 64, "geometryOwnership": {"sha256": "mask"}}
        row = {"assetId": "test", "structuredProfileSha256": "b" * 64, "sourceReport": "report.json",
               "sourceReportSha256": registry.hashlib.sha256(b"report").hexdigest()}
        with patch.object(registry, "load_registered_profile", return_value=current), \
                patch.object(registry, "registered_profiles", return_value={"test": Path("profile.json")}), \
                patch.object(Path, "read_bytes", return_value=b"report"):
            for gate, export in ((None, True), ({"passed": False}, True), ({"passed": True}, False)):
                report = {**current, "ownershipBoundaryGate": gate or {}, "candidateValidForExport": export}
                with patch.object(registry, "read_document", return_value=report):
                    self.assertTrue(any("boundary/export gate" in error for error in registry.validate_selected_profiles([row])))
            with patch.object(registry, "read_document", return_value={**current,
                    "ownershipBoundaryGate": {"passed": True}, "candidateValidForExport": True}):
                self.assertEqual(registry.validate_selected_profiles([row]), [])


if __name__ == "__main__":
    unittest.main()
