import unittest
from pathlib import Path

import run_all_mocap_pipeline as pipeline
from tools.validate_homm3_mocap_pipeline_contract import validate_inventory


class SelectionTests(unittest.TestCase):
    def test_duplicate_corpus_requires_explicit_preference(self):
        paths = [Path("x/a/corpus.json"), Path("x/b/corpus.json")]
        selected, reason = pipeline._select_corpus("unlisted", paths)
        self.assertIsNone(selected)
        self.assertEqual(reason, "ambiguous")

    def test_single_registration_is_usable(self):
        path = Path("x/registration_v1")
        selected, reason = pipeline._select_registration("unlisted", [path])
        self.assertEqual(selected, path)
        self.assertEqual(reason, "single")


class InventoryTests(unittest.TestCase):
    def test_current_inventory_is_complete_and_commands_are_gated(self):
        inventory = pipeline.build_inventory()
        self.assertEqual(inventory["unitCount"], len(inventory["units"]))
        for row in inventory["units"]:
            if row["readiness"] == "ready_for_weights_only":
                self.assertTrue(row["plannedCommand"])
                self.assertEqual(row["rig"]["kind"], "canonical_smartrig")
            else:
                self.assertFalse(row["plannedCommand"])

    def test_inventory_passes_static_contract_validator(self):
        path = pipeline.ARTIFACTS / "homm3_mocap_unit_inventory.json"
        pipeline.build_inventory()
        self.assertTrue(validate_inventory(path)["ok"])

    def test_lighting_selection_pins_current_fit_reports(self):
        selection = pipeline.build_lighting_selection(pipeline.build_inventory())
        self.assertEqual(selection["schema"], "homm3.mocap-lighting-selection.v1")
        self.assertEqual(len(selection["units"]), 20)
        row = next(item for item in selection["units"] if item["labSid"] == "h3_roc")
        self.assertTrue(row["sourceReport"].endswith("h3_roc/weights_only_v1/report.json"))
        self.assertEqual(len(row["sourceReportSha256"]), 64)
        self.assertEqual(row["fitOutputName"], "weights_only_v1")
        self.assertEqual(row["fitOutputSelection"], "default")

    def test_wolf_rider_pins_matching_corrected_mounted_branch(self):
        inventory = pipeline.build_inventory()
        row = next(item for item in inventory["units"] if item["unit"] == "h3_wolf_rider")
        self.assertTrue(row["source"]["corpus"].endswith("wolf_rider_corrected/composed_v2/corpus.json"))
        self.assertTrue(row["registration"]["root"].endswith("wolf_rider_corrected/registration_v2"))
        self.assertTrue(row["rig"]["path"].endswith("h3_wolf_rider_smartrigged.glb"))
        self.assertEqual(row["readiness"], "ready_for_weights_only")

    def test_pikeman_pins_explicit_front_orientation_wrapper(self):
        inventory = pipeline.build_inventory()
        row = next(item for item in inventory["units"] if item["unit"] == "h3_pikeman")
        self.assertTrue(row["registration"]["root"].endswith("pikeman/registration_v3_flip180"))
        report = Path(row["registration"]["root"]) / "camera_registration.json"
        self.assertEqual(
            pipeline._load(report).get("orientationOverride"),
            "deterministic_front_correction_yaw_plus_180",
        )
        self.assertEqual(row["readiness"], "ready_for_weights_only")

    def test_pikeman_pins_corrected_fit_output(self):
        inventory = pipeline.build_inventory()
        row = next(item for item in inventory["units"] if item["unit"] == "h3_pikeman")
        self.assertEqual(row["fitOutput"]["name"], "weights_only_flip180")
        self.assertEqual(row["fitOutput"]["selection"], "preferred")
        self.assertTrue(row["fitOutput"]["root"].endswith("h3_pikeman/weights_only_flip180"))
        self.assertTrue(any(str(arg).endswith("h3_pikeman\\weights_only_flip180") or str(arg).endswith("h3_pikeman/weights_only_flip180") for arg in row["plannedCommand"]))

        selection = pipeline.build_lighting_selection(inventory)
        lighting = next(item for item in selection["units"] if item["labSid"] == "h3_pikeman")
        self.assertTrue(lighting["sourceReport"].endswith("h3_pikeman/weights_only_flip180/report.json"))
        self.assertEqual(lighting["fitOutputName"], "weights_only_flip180")
        self.assertEqual(lighting["fitOutputSelection"], "preferred")

    def test_missing_preferred_fit_output_does_not_fallback(self):
        inventory = pipeline.build_inventory()
        row = next(item for item in inventory["units"] if item["unit"] == "h3_pikeman")
        preferred = Path(row["fitOutput"]["root"])
        report = preferred / "report.json"
        self.assertTrue(report.is_file())
        original = pipeline.FIT_OUTPUT_PREFERENCES["h3_pikeman"]
        pipeline.FIT_OUTPUT_PREFERENCES["h3_pikeman"] = "weights_only_missing"
        try:
            with self.assertRaises(ValueError):
                pipeline.build_lighting_selection(pipeline.build_inventory())
        finally:
            pipeline.FIT_OUTPUT_PREFERENCES["h3_pikeman"] = original

    def test_invalid_fit_output_name_rejected(self):
        original = pipeline.FIT_OUTPUT_PREFERENCES.get("h3_archer")
        pipeline.FIT_OUTPUT_PREFERENCES["h3_archer"] = "../escape"
        try:
            with self.assertRaises(ValueError):
                pipeline._fit_output_name("h3_archer")
        finally:
            if original is None:
                pipeline.FIT_OUTPUT_PREFERENCES.pop("h3_archer", None)
            else:
                pipeline.FIT_OUTPUT_PREFERENCES["h3_archer"] = original


if __name__ == "__main__":
    unittest.main()
