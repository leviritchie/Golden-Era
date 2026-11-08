from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

from experiments.campaign_port_poc.procedural_scenarios import installer as installer_module
from experiments.campaign_port_poc.procedural_scenarios.bundle import create_bundle
from experiments.campaign_port_poc.procedural_scenarios.emitter import (
    NativeMapContainer,
    emit_scenario,
    parse_container_bytes,
    write_container,
)
from experiments.campaign_port_poc.procedural_scenarios.installer import (
    InstallationError,
    apply_core_delta_document,
    install_bundle,
    uninstall_scenario,
)
from experiments.campaign_port_poc.procedural_scenarios.preflight import (
    ProceduralPreflightError,
    validate_procedural_references,
)
from experiments.campaign_port_poc.procedural_scenarios.validator import (
    _validate_objects,
    _validate_spawn_metadata,
    validate_bundle,
)


def _donor() -> NativeMapContainer:
    return NativeMapContainer(
        version="1.0",
        prefix_suffix=b"\0\0",
        chunks=(
            {"title": "Donor", "startSettings": {"DefeatAllEnemiesEnabled": False}},
            {
                "sizeX_": 32,
                "sizeZ_": 32,
                "cliffRandomSeed": 1,
                "generatorChecksum": "test",
                "settings": {},
            },
            {"dialogs": {"lines": []}, "quests": {"quests": []}},
            {"counters": [], "quests": []},
        ),
    )


def _scenario(*, dialog: bool = False, victory_count: int = 1) -> dict:
    size = 32
    triggers = [
        {
            "comment": f"victory {index}",
            "repeat": False,
            "conditions": [
                {
                    "comment": "",
                    "c": "ObjectCaptureEntity",
                    "p": ["proc_test_objective"],
                    "counter": 1,
                }
            ],
            "actions": (
                ([{"comment": "", "a": "Dialog", "p": ["forbidden"]}] if dialog else [])
                + [{"comment": "", "a": "GameVictory", "p": []}]
            ),
            "conditionsLogic": "And",
        }
        for index in range(victory_count)
    ]
    if victory_count == 0:
        triggers = [
            {
                "comment": "no victory",
                "repeat": False,
                "conditions": [
                    {"comment": "", "c": "StartTurn", "p": ["1", "1"], "counter": 1}
                ],
                "actions": [{"comment": "", "a": "GiveRes", "p": ["gold", "1"]}],
                "conditionsLogic": "And",
            }
        ]
    zeroes = [0] * (size * size)
    return {
        "schema": "homm3.procedural_scenario_ir.v1",
        "generator_version": "test",
        "scenario_id": "test",
        "map_sid": "proc_test_scenario",
        "seed": 7,
        "profile": {
            "map_size": size,
            "archetype": "conquest",
            "title": "Test Scenario",
            "description": "",
            "text_provider": {"mode": "none"},
        },
        "topology": {
            "start_zone_id": "start",
            "objective_zone_ids": ["victory"],
            "nodes": [
                {"id": "start", "role": "start"},
                {"id": "victory", "role": "victory"},
            ],
            "edges": [{"source": "start", "target": "victory"}],
        },
        "layout": {},
        "terrain": {
            "tiles_map": [1] * (size * size),
            "water_map": zeroes,
            "roads_map": zeroes,
            "levels_map": zeroes,
            "climbs_map": zeroes,
            "custom_areas_painting": zeroes,
            "blocked": [False] * (size * size),
        },
        "placements": [
            {
                "placement_id": "proc_test_start",
                "kind": "player_start",
                "content_sid": "city-spawner",
                "node": 33,
                "origin": [1, 1],
                "zone_id": "start",
                "footprint": [[0, 0]],
                "interactive": True,
                "risk_tier": 0,
                "metadata": {
                    "owner": 1,
                    "faction_sid": "test_faction",
                    "hero_sid": "test_hero",
                },
            },
            {
                "placement_id": "proc_test_objective",
                "kind": "objective",
                "content_sid": "fx_quest_mark_gold_01",
                "node": 990,
                "origin": [30, 30],
                "zone_id": "victory",
                "footprint": [[0, 0]],
                "interactive": True,
                "risk_tier": 2,
                "metadata": {},
            },
        ],
        "events": triggers,
        "metrics": {
            "gameplay_density": 0.2,
            "visual_density": 0.4,
            "decision_spacing_mean": 8,
        },
        "provenance": {
            "generator_version": "test",
            "source_hashes": {"core": "0" * 64},
        },
    }


def _write_donor(path: Path) -> None:
    from experiments.campaign_port_poc.procedural_scenarios.emitter import (
        serialize_container,
    )

    path.write_bytes(serialize_container(_donor(), hashlib.md5(b"donor").hexdigest()))


def _pin_bundle_core_source(bundle_root: Path, core_path: Path) -> None:
    manifest_path = bundle_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_hashes = {
        "core": hashlib.sha256(core_path.read_bytes()).hexdigest()
    }
    manifest["sourceHashes"] = source_hashes
    provenance = manifest.setdefault("provenance", {})
    spellings = [
        spelling
        for spelling in ("sourceHashes", "source_hashes")
        if spelling in provenance
    ]
    if not spellings:
        spellings = ["sourceHashes"]
    for spelling in spellings:
        provenance[spelling] = source_hashes
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

class DeliveryFrameworkTests(unittest.TestCase):
    def test_deterministic_emission_and_zero_gzip_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = emit_scenario(
                _scenario(), root / "a", donor_container=_donor()
            )
            second = emit_scenario(
                _scenario(), root / "b", donor_container=_donor()
            )
            first_bytes = first.map_path.read_bytes()
            self.assertEqual(first_bytes, second.map_path.read_bytes())
            self.assertEqual(first_bytes[4:8], b"\0\0\0\0")
            parsed = parse_container_bytes(first_bytes)
            self.assertEqual(parsed.chunks[1]["fileMapName"], "proc_test_scenario")

    def test_bundle_validator_accepts_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            report = validate_bundle(bundle.root)
            self.assertTrue(report.ok, report.to_dict())

    def test_custom_source_bundle_is_self_contained_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            payload = b"custom source evidence"
            digest = hashlib.sha256(payload).hexdigest()
            source_key = "custom-manifest/" + digest
            scenario = _scenario()
            scenario["provenance"]["source_hashes"][source_key] = digest

            bundle = create_bundle(
                scenario,
                root / "bundle",
                donor_map=donor,
                source_artifacts={source_key: payload},
            )
            report = validate_bundle(bundle.root)
            self.assertTrue(report.ok, report.to_dict())
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            evidence_path = manifest["sourceArtifacts"][source_key]
            self.assertEqual(payload, (bundle.root / evidence_path).read_bytes())
            self.assertEqual(digest, manifest["files"][evidence_path])
    def test_validator_rejects_multiple_victories_and_textless_dialog(self) -> None:
        for scenario, code in (
            (_scenario(victory_count=2), "victory_contract_count"),
            (_scenario(dialog=True), "textless_dialog_forbidden"),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                donor = root / "donor.map"
                _write_donor(donor)
                bundle = create_bundle(scenario, root / "bundle", donor_map=donor)
                report = validate_bundle(bundle.root)
                self.assertIn(code, {issue.code for issue in report.issues})

    def test_validator_rejects_unresolved_event_entity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            scenario = _scenario()
            scenario["events"][0]["conditions"][0]["p"] = ["proc_missing_entity"]
            bundle = create_bundle(scenario, root / "bundle", donor_map=donor)
            report = validate_bundle(bundle.root)
            self.assertIn("event_entity_unresolved", {issue.code for issue in report.issues})
    def test_transactional_install_and_uninstall_restore_originals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = (
                game_root
                / "HeroesOldenEra_Data"
                / "StreamingAssets"
                / "maps"
            )
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr(
                    "DB/quickStart.json",
                    json.dumps({"scenarios": ["stock"]}).encode("utf-8"),
                )
            _pin_bundle_core_source(bundle.root, core_path)
            original_core = core_path.read_bytes()
            runner = lambda core, map_path, sid: ("synthetic_preflight",)
            installed = install_bundle(
                bundle.root,
                game_root=game_root.resolve(),
                preflight_runner=runner,
            )
            self.assertTrue(installed.map_path.is_file())
            with zipfile.ZipFile(core_path) as archive:
                quickstart = json.loads(archive.read("DB/quickStart.json"))
            self.assertIn("proc_test_scenario", quickstart["scenarios"])
            result = uninstall_scenario(
                "proc_test_scenario",
                game_root=game_root.resolve(),
                preflight_runner=runner,
            )
            self.assertIn("core", result.restored)
            self.assertEqual(core_path.read_bytes(), original_core)
            self.assertFalse(installed.map_path.exists())

    def test_create_json_member_is_deterministic_and_conflict_checked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "Core.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            delta = {
                "operations": [
                    {
                        "member": "DB/dialogs/dialogs/custom_maps/proc_test/dialog.json",
                        "operation": "create_json_member",
                        "path": [],
                        "value": {"array": [{"id": "proc_dialog"}]},
                    }
                ]
            }
            first = root / "first.zip"
            second = root / "second.zip"
            apply_core_delta_document(source, delta, first)
            apply_core_delta_document(source, delta, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    json.loads(archive.read("DB/dialogs/dialogs/custom_maps/proc_test/dialog.json")),
                    {"array": [{"id": "proc_dialog"}]},
                )
            conflicting = copy.deepcopy(delta)
            conflicting["operations"][0]["value"] = {"array": []}
            with self.assertRaises(InstallationError):
                apply_core_delta_document(first, conflicting, root / "conflict.zip")

    def test_install_uses_validated_snapshot_if_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            source_sidecar = bundle.root / "maps" / "proc_test_scenario.json"
            expected_sidecar = source_sidecar.read_bytes()
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)

            validate = installer_module.validate_bundle
            calls: list[Path] = []

            def mutate_after_snapshot(path: Path):
                report = validate(path)
                calls.append(Path(path))
                if len(calls) == 2:
                    source_sidecar.write_bytes(b"changed after snapshot")
                return report

            with mock.patch.object(
                installer_module,
                "validate_bundle",
                side_effect=mutate_after_snapshot,
            ):
                installed = install_bundle(
                    bundle.root,
                    game_root=game_root.resolve(),
                    preflight_runner=lambda *_: ("synthetic_preflight",),
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(installed.sidecar_path.read_bytes(), expected_sidecar)
            self.assertNotEqual(source_sidecar.read_bytes(), expected_sidecar)
    def test_post_install_preflight_failure_rolls_back_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            original_core = core_path.read_bytes()
            calls = 0

            def runner(*_args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise InstallationError("synthetic post-install preflight failure")
                return ("synthetic_preflight",)

            with self.assertRaises(InstallationError):
                install_bundle(
                    bundle.root,
                    game_root=game_root.resolve(),
                    preflight_runner=runner,
                )
            self.assertEqual(core_path.read_bytes(), original_core)
            self.assertFalse((maps_root / "proc_test_scenario.map").exists())
            self.assertFalse((maps_root / "proc_test_scenario.json").exists())
            state_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / ".procedural_scenarios"
            self.assertFalse((state_root / "installed" / "proc_test_scenario").exists())
    def test_uninstall_rejects_external_payload_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            runner = lambda *_: ("synthetic_preflight",)
            installed = install_bundle(
                bundle.root,
                game_root=game_root.resolve(),
                preflight_runner=runner,
            )
            installed.map_path.write_bytes(installed.map_path.read_bytes() + b"drift")
            with self.assertRaises(InstallationError):
                uninstall_scenario(
                    installed.map_sid,
                    game_root=game_root.resolve(),
                    preflight_runner=runner,
                )
    def test_core_source_identity_rejects_legacy_path(self) -> None:
        digest = "0" * 64
        manifest = {
            "sourceHashes": {"fixture/Core.zip": digest},
            "provenance": {"sourceHashes": {"fixture/Core.zip": digest}},
        }
        with self.assertRaisesRegex(InstallationError, "canonical logical key"):
            installer_module._expected_core_source_hash(manifest)
    def test_core_source_mismatch_fails_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":["drift"]}')
            drifted_core = core_path.read_bytes()

            with self.assertRaisesRegex(InstallationError, "does not match"):
                install_bundle(
                    bundle.root,
                    game_root=game_root.resolve(),
                    preflight_runner=lambda *_: ("synthetic_preflight",),
                )
            self.assertEqual(core_path.read_bytes(), drifted_core)
            self.assertFalse((maps_root / "proc_test_scenario.map").exists())

    def test_installer_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            state_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / ".procedural_scenarios"
            lock_root = state_root / ".installer.lock"
            lock_root.mkdir(parents=True)

            with self.assertRaisesRegex(InstallationError, "holds"):
                install_bundle(
                    bundle.root,
                    game_root=game_root.resolve(),
                    preflight_runner=lambda *_: ("synthetic_preflight",),
                )
            self.assertTrue(lock_root.is_dir())
            self.assertFalse((maps_root / "proc_test_scenario.map").exists())

    def test_partial_directory_removal_is_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "installed" / "proc_partial"
            destination.mkdir(parents=True)
            (destination / "a.txt").write_text("a", encoding="utf-8")
            (destination / "b.txt").write_text("b", encoding="utf-8")
            real_rmtree = installer_module.shutil.rmtree
            attempted = False

            def fail_after_partial_remove(path: Path, *args, **kwargs):
                nonlocal attempted
                if Path(path) == destination and not attempted:
                    attempted = True
                    (destination / "a.txt").unlink()
                    raise OSError("synthetic partial remove failure")
                return real_rmtree(path, *args, **kwargs)

            with mock.patch.object(
                installer_module.shutil,
                "rmtree",
                side_effect=fail_after_partial_remove,
            ):
                with self.assertRaisesRegex(OSError, "partial remove"):
                    with installer_module._FileTransaction(root / "rollback") as transaction:
                        transaction.remove_path(destination)
                        transaction.commit()
            self.assertEqual(
                sorted(path.name for path in destination.iterdir()),
                ["a.txt", "b.txt"],
            )
    def test_uninstall_readback_failure_rolls_back_removals_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "maps"
            maps_root.mkdir(parents=True)
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            runner = lambda *_: ("synthetic_preflight",)
            installed = install_bundle(
                bundle.root,
                game_root=game_root.resolve(),
                preflight_runner=runner,
            )
            state_root = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / ".procedural_scenarios"
            state_path = state_root / "state.json"
            record_root = state_root / "installed" / installed.map_sid
            before = {
                "core": core_path.read_bytes(),
                "map": installed.map_path.read_bytes(),
                "sidecar": installed.sidecar_path.read_bytes(),
                "state": state_path.read_bytes(),
            }
            original_read_json = installer_module._read_json
            state_reads = 0

            def fail_final_state_read(path: Path):
                nonlocal state_reads
                if Path(path).name == "state.json":
                    state_reads += 1
                    if state_reads == 2:
                        raise InstallationError("synthetic uninstall readback failure")
                return original_read_json(path)

            with mock.patch.object(
                installer_module, "_read_json", side_effect=fail_final_state_read
            ):
                with self.assertRaisesRegex(InstallationError, "readback failure"):
                    uninstall_scenario(
                        installed.map_sid,
                        game_root=game_root.resolve(),
                        preflight_runner=runner,
                    )
            self.assertEqual(core_path.read_bytes(), before["core"])
            self.assertEqual(installed.map_path.read_bytes(), before["map"])
            self.assertEqual(installed.sidecar_path.read_bytes(), before["sidecar"])
            self.assertEqual(state_path.read_bytes(), before["state"])
            self.assertTrue((record_root / "record.json").is_file())

    def test_preflight_rejects_missing_typed_core_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scenario = _scenario()
            scenario["placements"].append(
                {
                    "placement_id": "proc_test_guard",
                    "kind": "encounter",
                    "content_sid": "random-squad",
                    "node": 66,
                    "origin": [2, 2],
                    "zone_id": "start",
                    "footprint": [[0, 0]],
                    "interactive": True,
                    "risk_tier": 1,
                    "metadata": {
                        "squadMode": "exact",
                        "exactSquad": {
                            "sid": "proc_test_guard_squad",
                            "unitProps": [{"sid": "missing_unit", "count": 3}],
                            "actualValue": 100.0,
                        },
                        "encounterTemplateInstance": {
                            "guards": [{
                                "position": {"x": 0, "y": 0},
                                "entitySid": "proc_test_guard",
                                "squadSid": "proc_test_guard_squad",
                            }],
                            "buildings": [],
                            "pickups": [],
                        },
                    },
                }
            )
            emitted = emit_scenario(
                scenario, root / "bundle", donor_container=_donor()
            )
            core_path = root / "Core.zip"
            catalogs = {
                "DB/fractions/test.json": {"array": [{"id": "test_faction"}]},
                "DB/heroes/test.json": {"array": [{"id": "test_hero"}]},
                "DB/units/test.json": {"array": []},
                "DB/squads/test.json": {"array": [{"id": "test_squad"}]},
                "DB/buildings_bans/test.json": {
                    "array": [{"id": "default_buildings_ban"}]
                },
                "DB/buildings_settings/test.json": {
                    "array": [{"id": "default_buildings_settings"}]
                },
            }
            with zipfile.ZipFile(core_path, "w") as archive:
                for member, document in catalogs.items():
                    archive.writestr(member, json.dumps(document))
            with self.assertRaisesRegex(ProceduralPreflightError, "missing unit"):
                validate_procedural_references(core_path, emitted.map_path)

    def test_city_spawn_uses_native_host_and_point_type_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scenario = _scenario()
            ai_start = copy.deepcopy(scenario["placements"][0])
            ai_start.update(
                placement_id="proc_test_ai_start",
                kind="ai_settlement",
                node=66,
                origin=[2, 2],
            )
            ai_start["metadata"]["owner"] = 2
            scenario["placements"].append(ai_start)
            emission = emit_scenario(
                scenario, root / "bundle", donor_container=_donor()
            )
            container = parse_container_bytes(emission.map_path.read_bytes())
            map_chunk = copy.deepcopy(container.chunks[1])
            ai_property = next(
                row
                for row in map_chunk["objectsProperties"]["propSpawns"]
                if row["owner"] == 2
            )
            ai_spawn = next(
                row
                for row in container.chunks[0]["spawns"]["spawns"]
                if row["owner"] == 2
            )
            self.assertEqual(0, ai_property["spawnPointType"])
            self.assertEqual(0, ai_spawn["spawnPointType"])
            self.assertEqual(0, ai_property["spawnType"])
            self.assertEqual(0, ai_spawn["spawnType"])
            broken_meta = copy.deepcopy(container.chunks[0])
            broken_meta["spawns"]["spawns"][1]["spawnPointType"] = 1
            metadata_issues = []
            _validate_spawn_metadata(broken_meta, metadata_issues)
            self.assertIn(
                "city_spawn_metadata_type_invalid",
                {issue.code for issue in metadata_issues},
            )

            broken_map = copy.deepcopy(map_chunk)
            broken_map["objectsProperties"]["propSpawns"][0]["spawnType"] = 1
            parity_issues = []
            _validate_spawn_metadata(
                container.chunks[0], parity_issues, map_data=broken_map
            )
            self.assertIn(
                "city_spawn_property_metadata_mismatch",
                {issue.code for issue in parity_issues},
            )
            issues = []
            _validate_objects(map_chunk, issues)
            self.assertNotIn("city_spawn_host_invalid", {issue.code for issue in issues})
            city_id = ai_property["id"]
            city_group = next(row for row in map_chunk["objects"] if city_id in row["ids"])
            city_group["sid"] = "homm3_inferno_city"
            issues = []
            _validate_objects(map_chunk, issues)
            self.assertIn("city_spawn_host_invalid", {issue.code for issue in issues})

            map_chunk["objectsProperties"]["propSpawns"] = []
            city_group["sid"] = "random-city"
            issues = []
            _validate_objects(map_chunk, issues)
            self.assertNotIn("city_spawn_host_invalid", {issue.code for issue in issues})
    def test_preflight_reports_malformed_property_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            emission = emit_scenario(
                _scenario(), root / "bundle", donor_container=_donor()
            )
            container = parse_container_bytes(emission.map_path.read_bytes())
            chunks = [copy.deepcopy(chunk) for chunk in container.chunks]
            chunks[1]["objectsProperties"]["propCities"] = {}
            malformed = root / "malformed.map"
            write_container(
                malformed,
                NativeMapContainer(
                    container.version,
                    container.prefix_suffix,
                    tuple(chunks),
                ),
                "0" * 32,
            )
            core_path = root / "Core.zip"
            with zipfile.ZipFile(core_path, "w"):
                pass
            with self.assertRaisesRegex(
                ProceduralPreflightError,
                "objectsProperties.propCities must be a list",
            ):
                validate_procedural_references(core_path, malformed)
    def test_frozen_spec_declares_preflight_module(self) -> None:
        spec = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "procedural_scenario_gui"
            / "OldenProceduralScenarios.spec"
        ).read_text(encoding="utf-8")
        self.assertIn('"tools.map_load_preflight"', spec)
    def test_installer_rejects_story_maps_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            donor = root / "donor.map"
            _write_donor(donor)
            bundle = create_bundle(_scenario(), root / "bundle", donor_map=donor)
            game_root = root / "Golden Era"
            maps_root = (
                game_root
                / "HeroesOldenEra_Data"
                / "StreamingAssets"
                / "maps"
            )
            story_root = maps_root / "Story_maps"
            story_root.mkdir(parents=True)
            (story_root / "proc_test_scenario.map").write_bytes(b"duplicate")
            core_path = game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
            with zipfile.ZipFile(core_path, "w") as archive:
                archive.writestr("DB/quickStart.json", '{"scenarios":[]}')
            _pin_bundle_core_source(bundle.root, core_path)
            with self.assertRaises(InstallationError):
                install_bundle(
                    bundle.root,
                    game_root=game_root.resolve(),
                    preflight_runner=lambda *_: (),
                )


if __name__ == "__main__":
    unittest.main()
