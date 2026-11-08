import copy
from pathlib import Path
import unittest

from experiments.homm3_mocap_v2.faction_rollout_inventory import build_inventory


class FactionInventoryTests(unittest.TestCase):
    def setUp(self):
        self.factions = [("fixture.json", {"identity": {"factionSid": "test"},
                         "unitVariants": ["", "_upg"],
                         "unitLines": [{"tier": 1, "baseSid": "a", "names": ["A", "B"],
                                        "variantSids": {"_upg": "b"}}]})]
        self.entry = {"gameUnitSids": ["a"], "bundleName": "bundle",
                      "battlePrefabAssetPath": "battle", "mapPrefabAssetPath": "map"}
        self.unit = {"unitSid": "lab_a", "bundleName": "bundle",
                     "battlePrefabAsset": "battle", "mapPrefabAsset": "map"}

    def inventory(self, entries=None, units=None, selection=None):
        return build_inventory(self.factions, {"entries": entries if entries is not None else [self.entry]},
                               {"units": units if units is not None else [self.unit]}, selection or {},
                               {"units": []}, root=Path.cwd())

    def test_counts_derive_from_cartesian_roster_and_explicit_sid_overrides(self):
        report = self.inventory()
        self.assertEqual(report["counts"]["rosterSlots"], 2)
        self.assertEqual(report["counts"]["expectedSlotsFromDefinitions"], 2)
        self.assertEqual([r["gameSid"] for r in report["units"]], ["a", "b"])
        self.assertEqual(report["units"][0]["labSid"], "lab_a")

    def test_missing_import_keeps_full_row(self):
        report = self.inventory(entries=[])
        self.assertEqual(len(report["units"]), 2)
        self.assertTrue(all("missing_import_mapping" in row["issues"] for row in report["units"]))
        self.assertTrue(all(row["labSid"] is None for row in report["units"]))

    def test_duplicate_import_is_ambiguous_not_first_match(self):
        report = self.inventory(entries=[self.entry, copy.deepcopy(self.entry)])
        row = report["units"][0]
        self.assertIn("ambiguous_import_mapping", row["issues"])
        self.assertIsNone(row["labSid"])
        self.assertEqual(len(row["importMatches"]), 2)

    def test_missing_and_duplicate_bundle_joins_remain_visible(self):
        for units, issue in (([], "missing_bundle_mapping"), ([self.unit, self.unit], "ambiguous_bundle_mapping")):
            with self.subTest(issue=issue):
                report = self.inventory(units=units)
                self.assertEqual(len(report["units"]), 2)
                self.assertIn(issue, report["units"][0]["issues"])

    def test_selection_does_not_claim_animation_or_install_completion(self):
        selection = {"units": [{"gameSid": "a", "labSid": "lab_a", "bundleName": "bundle"}],
                     "excluded": [{"gameSid": "b", "reason": "unresolved mesh"}]}
        report = self.inventory(selection=selection)
        self.assertEqual(report["counts"]["selectedCandidateSlots"], 1)
        self.assertEqual(report["units"][0]["animationCompletion"], "unproven")
        self.assertEqual(report["units"][0]["installedCompletion"], "unproven")
        self.assertEqual(report["units"][1]["explicitExclusions"][0]["reason"], "unresolved mesh")

    def test_duplicate_roster_sid_is_reported_without_dropping_slot(self):
        self.factions[0][1]["unitLines"][0]["variantSids"]["_upg"] = "a"
        report = self.inventory()
        self.assertEqual(report["counts"]["rosterSlots"], 2)
        self.assertEqual(report["counts"]["uniqueGameSids"], 1)
        self.assertTrue(all("duplicate_roster_game_sid" in row["issues"] for row in report["units"]))


if __name__ == "__main__":
    unittest.main()
