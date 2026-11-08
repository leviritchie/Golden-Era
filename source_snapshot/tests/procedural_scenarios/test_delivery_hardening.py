from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from experiments.campaign_port_poc.procedural_scenarios.emitter import (
    NATIVE_OBJECT_PROPERTY_KEYS,
    NativeMapContainer,
    build_native_container,
    serialize_container,
)
from experiments.campaign_port_poc.procedural_scenarios.validator import (
    _validate_source_hashes,
    validate_generated_ir,
)
from experiments.campaign_port_poc.procedural_scenarios.service import generate_bundle
from tests.procedural_scenarios.test_delivery_framework import _scenario
from tests.procedural_scenarios.test_delivery_model_integration import (
    _donor as _typed_donor,
    _typed_scenario,
)


class DeliveryHardeningTests(unittest.TestCase):
    def test_emitter_owns_settings_and_removes_donor_victory_paths(self) -> None:
        donor = NativeMapContainer(
            "1.0",
            b"\0\0",
            (
                {
                    "title": "donor",
                    "startSettings": {"DefeatAllEnemiesEnabled": True},
                },
                {
                    "cliffRandomSeed": 1,
                    "generatorChecksum": "donor",
                    "settings": {
                        "isScenario": True,
                        "mapWinConditions": [{"typeWinCondition": 0}],
                    },
                },
                {},
                {},
            ),
        )
        container = build_native_container(_scenario(), donor)
        settings = container.chunks[1]["settings"]
        self.assertFalse(container.chunks[0]["startSettings"]["DefeatAllEnemiesEnabled"])
        self.assertEqual([], settings["mapWinConditions"])
        self.assertTrue(settings["isScenario"])
        self.assertNotEqual(donor.chunks[1]["settings"], settings)

    def test_native_schema_lists_and_wrappers_are_non_null(self) -> None:
        donor = NativeMapContainer(
            "1.0",
            b"\0\0",
            (
                {"startSettings": {"DefeatAllEnemiesEnabled": False}},
                {},
                {},
                {},
            ),
        )
        container = build_native_container(_scenario(), donor)
        header = container.chunks[0]
        data = container.chunks[1]
        self.assertEqual(
            {
                "missionNameSid": "",
                "missionDescSid": "",
                "campaignSid": "",
                "campaignDescSid": "",
                "hubIconSid": "",
            },
            header["campaignInfo"],
        )
        self.assertEqual({"list": []}, data["objectValuesOverrides"])
        self.assertEqual(
            set(NATIVE_OBJECT_PROPERTY_KEYS),
            set(data["objectsProperties"]),
        )
        self.assertTrue(
            all(isinstance(rows, list) for rows in data["objectsProperties"].values())
        )
    def test_encounter_uses_exact_squad_mode_only(self) -> None:
        scenario = copy.deepcopy(_scenario())
        scenario["placements"].append(
            {
                "placement_id": "proc_test_encounter",
                "kind": "encounter",
                "content_sid": "random-squad",
                "node": 266,
                "origin": [10, 8],
                "zone_id": "victory",
                "footprint": [[0, 0]],
                "interactive": True,
                "risk_tier": 1,
                "metadata": {
                    "squadMode": "exact",
                    "exactSquad": {
                        "sid": "proc_test_encounter_squad",
                        "unitProps": [{"sid": "test_unit", "count": 7}],
                        "actualValue": 700.0,
                    },
                    "encounterTemplateInstance": {
                        "guards": [{
                            "position": {"x": 2, "y": 1},
                            "entitySid": "proc_test_encounter",
                            "squadSid": "proc_test_encounter_squad",
                        }],
                        "buildings": [{
                            "position": {"x": 0, "y": 0},
                            "contentSid": "test_building",
                            "entitySid": "proc_test_encounter_building_00",
                        }],
                        "pickups": [{
                            "position": {"x": 1, "y": 0},
                            "contentSid": "test_pickup",
                            "entitySid": "proc_test_encounter_pickup_00",
                        }],
                    },
                },
            }
        )
        donor = NativeMapContainer(
            "1.0",
            b"\0\0",
            ({"startSettings": {"DefeatAllEnemiesEnabled": False}}, {}, {}, {}),
        )
        map_data = build_native_container(scenario, donor).chunks[1]
        properties = map_data["objectsProperties"]
        encounter_id = next(
            row["id"]
            for row in properties["propEntities"]
            if row.get("sid") == "proc_test_encounter"
        )
        self.assertNotIn(encounter_id, {row["id"] for row in properties["propSquads"]})
        random_row = next(row for row in properties["propRandomSquads"] if row["id"] == encounter_id)
        self.assertEqual(700.0, random_row["requestedValue"])
        self.assertEqual("test_unit", random_row["customTopUnit"])
        self.assertEqual(1, random_row["tier"])
        emitted_sids = {row["sid"] for row in map_data["objects"]}
        self.assertIn("test_building", emitted_sids)
        self.assertIn("test_pickup", emitted_sids)

    def test_service_validates_before_atomic_library_publish(self) -> None:
        scenario = _typed_scenario()
        scenario = replace(
            scenario,
            provenance=replace(
                scenario.provenance,
                source_hashes=(("core", "d" * 64),),
            ),
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "unused-core.zip").write_bytes(b"unused")
            donor = root / "donor.map"
            donor.write_bytes(
                serialize_container(_typed_donor(), hashlib.md5(b"donor").hexdigest())
            )
            library = root / "library"
            with (
                patch(
                    "experiments.campaign_port_poc.procedural_scenarios.service.build_catalog",
                    return_value=SimpleNamespace(source_artifacts=()),
                ),
                patch(
                    "experiments.campaign_port_poc.procedural_scenarios.service.generate_scenario",
                    return_value=scenario,
                ),
            ):
                result = generate_bundle(
                    scenario.profile,
                    core_zip=root / "unused-core.zip",
                    donor_map=donor,
                    output_root=library,
                    publish_by_sid=True,
                )
                self.assertEqual(library / scenario.map_sid, result.bundle.root)
                sentinel = result.bundle.root / "sentinel.txt"
                sentinel.write_text("preserve", encoding="utf-8")
                with patch(
                    "experiments.campaign_port_poc.procedural_scenarios.service.create_bundle",
                    side_effect=RuntimeError("synthetic staging failure"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "synthetic staging failure"):
                        generate_bundle(
                            scenario.profile,
                            core_zip=root / "unused-core.zip",
                            donor_map=donor,
                            output_root=library,
                            publish_by_sid=True,
                        )
                self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))

    def test_service_emits_from_the_snapshotted_donor_bytes(self) -> None:
        scenario = _typed_scenario()
        scenario = replace(
            scenario,
            provenance=replace(
                scenario.provenance,
                source_hashes=(("core", "d" * 64),),
            ),
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "unused-core.zip").write_bytes(b"unused")
            donor = root / "donor.map"
            donor_payload = serialize_container(
                _typed_donor(),
                hashlib.md5(b"immutable-donor").hexdigest(),
            )
            donor.write_bytes(donor_payload)
            observed: dict[str, str] = {}

            def mutate_donor(_profile, _catalog, *, donor_hash: str):
                observed["donorHash"] = donor_hash
                donor.write_bytes(b"changed after generation began")
                return scenario

            with (
                patch(
                    "experiments.campaign_port_poc.procedural_scenarios.service.build_catalog",
                    return_value=SimpleNamespace(source_artifacts=()),
                ),
                patch(
                    "experiments.campaign_port_poc.procedural_scenarios.service.generate_scenario",
                    side_effect=mutate_donor,
                ),
                patch(
                    "experiments.campaign_port_poc.procedural_scenarios.emitter.read_container",
                    side_effect=AssertionError("donor path was reread"),
                ),
            ):
                result = generate_bundle(
                    scenario.profile,
                    core_zip=root / "unused-core.zip",
                    donor_map=donor,
                    output_root=root / "bundle",
                )

            self.assertTrue(result.bundle.emission.map_path.is_file())
            self.assertEqual(
                hashlib.sha256(donor_payload).hexdigest(),
                observed["donorHash"],
            )


    def test_bundle_source_hashes_are_canonical_and_match_provenance(self) -> None:
        digest = "a" * 64
        issues = []
        _validate_source_hashes(
            {
                "sourceHashes": {"fixture/Core.zip": digest},
                "provenance": {"sourceHashes": {"core": digest}},
            },
            issues,
        )
        codes = {issue.code for issue in issues}
        self.assertIn("core_source_hash_missing", codes)
        self.assertIn("core_source_hash_legacy_key", codes)
        self.assertIn("source_hash_provenance_mismatch", codes)

        valid_issues = []
        canonical = {"core": digest, "custom:test": "b" * 64}
        _validate_source_hashes(
            {
                "sourceHashes": canonical,
                "provenance": {"sourceHashes": canonical},
            },
            valid_issues,
        )
        self.assertEqual([], valid_issues)
    def test_generated_ir_fails_closed_when_required_structures_are_missing(self) -> None:
        scenario = _scenario()
        del scenario["topology"]
        del scenario["events"]
        report = validate_generated_ir(scenario)
        codes = {issue.code for issue in report.issues}
        self.assertIn("topology_missing", codes)
        self.assertIn("events_missing", codes)


if __name__ == "__main__":
    unittest.main()