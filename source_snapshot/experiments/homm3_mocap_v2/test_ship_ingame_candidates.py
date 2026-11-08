import copy
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from experiments.homm3_mocap_v2 import ship_ingame_candidates as ship


class ShipIngameCandidatesTests(unittest.TestCase):
    def setUp(self):
        version = ship.payload_abi.source_versions()[ship.PAYLOAD_SURFACE]
        self.runtime = {"pluginPayloadAbi": {"surface": ship.PAYLOAD_SURFACE, "version": version},
                        "proof": "compile-only; runtime behavior unproven"}

    def test_lab_preparation_receives_exact_non_stronghold_selection(self):
        selection = Path("artifacts/castle_selection.json")
        command = ship.lab_prepare_command(Path("artifacts/castle_output"), selection,
                                           [{"labSid": "h3_pikeman"}, {"labSid": "h3_crusader"}])
        self.assertEqual(command[command.index("--selection") + 1], str(selection.resolve()))
        self.assertEqual(command[command.index("--lab-sids") + 1], "h3_pikeman,h3_crusader")
        self.assertIn("--require-chosen-set", command)

    def test_scope_uses_existing_prefab_naming_and_explicit_game_sid(self):
        for lab, game, prefab in (
            ("h3_pikeman", "h3_pikeman", "owned_skinned.prefab"),
            ("h3_crusader", "h3_swordsman_upg", "crusader_owned_skinned.prefab"),
        ):
            with self.subTest(lab=lab):
                path = f"Assets/CustomUnits/homm3_lab/{lab}/OwnedSkinned/{prefab}"
                rows = [{"labSid": lab, "gameSid": game, "bundleName": "selected_bundle"}]
                inventory = {"units": [{"unitSid": lab, "bundleName": "selected_bundle",
                                        "battlePrefabAsset": path, "mapPrefabAsset": path}]}
                entry = {"battlePrefabAssetPath": path, "mapPrefabAssetPath": path,
                         "bundleName": "selected_bundle", "gameUnitSids": [game]}
                with mock.patch.object(ship, "load", side_effect=[inventory, {"entries": [entry]}]):
                    ship.require_scope(rows)
                wrong = {**entry, "gameUnitSids": ["unrelated_unit"]}
                with mock.patch.object(ship, "load", side_effect=[inventory, {"entries": [wrong]}]):
                    with self.assertRaisesRegex(ValueError, "missing current skinned import binding"):
                        ship.require_scope(rows)
                legacy = copy.deepcopy(inventory)
                legacy["units"][0]["battlePrefabAsset"] = f"Assets/CustomUnits/homm3_lab/{lab}/battle.prefab"
                with mock.patch.object(ship, "load", side_effect=[legacy, {"entries": [entry]}]):
                    with self.assertRaisesRegex(ValueError, "not already on the owned skinned lane"):
                        ship.require_scope(rows)

    def test_runtime_capability_pins_the_payload_version_not_the_dll(self):
        ship.validate_runtime_capability(self.runtime)

        changed = copy.deepcopy(self.runtime)
        changed["pluginPayloadAbi"]["version"] += 1
        with self.assertRaisesRegex(ValueError, "source PluginPayloadAbi.cs"):
            ship.validate_runtime_capability(changed)

        changed = copy.deepcopy(self.runtime)
        changed["dllSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "retired plugin pin"):
            ship.validate_runtime_capability(changed)

        changed = copy.deepcopy(self.runtime)
        changed["proof"] = "runtime proven"
        with self.assertRaisesRegex(ValueError, "compile-only"):
            ship.validate_runtime_capability(changed)

    @mock.patch.object(Path, "is_file", return_value=True)
    @mock.patch.object(ship, "sha", return_value="a" * 64)
    def test_probe_authority_selects_derived_time_domain(self, digest, exists):
        clip = {"rawSourceGlb": "raw.glb", "rawSourceGlbSha256": "a" * 64}
        self.assertEqual(ship.clip_motion_authority(clip), Path("raw.glb"))
        clip["motionStyle"] = {"profile": ship.STYLE_PROFILE,
                               "derivedSourceGlb": "slow_idle.glb",
                               "derivedSourceGlbSha256": "a" * 64}
        self.assertEqual(ship.clip_motion_authority(clip), Path("slow_idle.glb"))
        clip["motionStyle"]["derivedSourceGlbSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            ship.clip_motion_authority(clip)
        clip["motionStyle"] = {}
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            ship.clip_motion_authority(clip)

    @mock.patch.object(ship.sys, "platform", "win32")
    @mock.patch.object(ship.subprocess, "run")
    def test_deploy_guard_accepts_exactly_stopped_process(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="INFO: No tasks are running which match the specified criteria.\r\n"
        )
        ship.require_game_stopped()
        run.assert_called_once()

    @mock.patch.object(ship.sys, "platform", "win32")
    @mock.patch.object(ship.subprocess, "run")
    def test_deploy_guard_rejects_running_game_before_writes(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='"HeroesOldenEra.exe","1234","Console","1","42 K"\r\n'
        )
        with self.assertRaisesRegex(RuntimeError, "HeroesOldenEra.exe is running"):
            ship.require_game_stopped()

    @mock.patch.object(ship.sys, "platform", "win32")
    @mock.patch.object(ship.subprocess, "run")
    def test_deploy_guard_fails_closed_on_tasklist_error(self, run):
        run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with self.assertRaisesRegex(RuntimeError, "unable to prove"):
            ship.require_game_stopped()


if __name__ == "__main__":
    unittest.main()
