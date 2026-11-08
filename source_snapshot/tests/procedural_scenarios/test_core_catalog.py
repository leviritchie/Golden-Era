from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from procedural_scenarios.catalog import (
    CatalogBuildError,
    ContentCatalogSnapshot,
    ContentKind,
)
from procedural_scenarios.model import Point


def _write_json(archive: zipfile.ZipFile, name: str, payload: object) -> None:
    archive.writestr(name, json.dumps(payload, sort_keys=True))


def _build_core(path: Path, *, generator_reward_sid: str = "resource_gold") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        _write_json(
            archive,
            "DB/map/tiles/tiles.json",
            {"array": [{"id": 1, "biome": "Grass"}, {"id": 7, "biome": "Dirt"}]},
        )
        _write_json(
            archive,
            "DB/fractions/custom.json",
            {"array": [{"id": "homm3_castle"}, {"id": "homm3_inferno"}]},
        )
        _write_json(
            archive,
            "DB/heroes/custom.json",
            {
                "array": [
                    {"id": "castle_hero", "fraction": "homm3_castle"},
                    {"id": "inferno_hero", "fraction": "homm3_inferno"},
                ]
            },
        )
        _write_json(
            archive,
            "DB/units/custom.json",
            {
                "array": [
                    {
                        "id": "inferno_unit",
                        "fraction": "homm3_inferno",
                        "tier": 2,
                        "squadValue": 200,
                    }
                ]
            },
        )
        _write_json(
            archive,
            "DB/map/objects/objects.json",
            {
                "array": [
                    {
                        "id": "homm3_castle_city",
                        "tag": "Interact",
                        "sizeX": 3,
                        "sizeZ": 3,
                        "pivotX": 1,
                        "pivotZ": 1,
                        "nodes": [1, 1, 1, 1, 1, 1, 2, 1, 1],
                    },
                    {
                        "id": "random-squad",
                        "tag": "meta",
                        "prefs": ["test/random_squad"],
                        "sizeX": 3,
                        "sizeZ": 3,
                        "pivotX": 1,
                        "pivotZ": 1,
                        "nodes": [2, 2, 2, 2, 0, 2, 2, 2, 2],
                    },
                    {
                        "id": "resource_gold",
                        "tag": "Resource",
                        "sizeX": 3,
                        "sizeZ": 3,
                        "pivotX": 1,
                        "pivotZ": 1,
                        "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
                    },
                ]
            },
        )
        _write_json(
            archive,
            "generator/content_lists/basic_content_lists.json",
            [{"name": "basic_rewards", "content": [{"sid": "resource_gold", "weight": 1}]}],
        )
        _write_json(
            archive,
            "generator/content_lists/basic_content_lists_variants_table.json",
            [],
        )
        _write_json(
            archive,
            "generator/content_lists/generator_content_lists.json",
            [{"name": "rewards", "content": [{"sid": generator_reward_sid, "weight": 10}]}],
        )
        _write_json(archive, "generator/content_pools/basic_pools_default.json", [])
        _write_json(archive, "generator/content_pools/basic_pools_resources.json", [])
        _write_json(
            archive,
            "generator/content_pools/default_content_pools.json",
            [
                {
                    "name": "content_pool_default_resources",
                    "groups": [{"weight": 2, "includeLists": ["rewards"]}],
                    "bans": [],
                }
            ],
        )
        _write_json(
            archive,
            "generator/encounter_templates/guarded.json",
            {
                "name": "guarded",
                "encounterType": 0,
                "relativeFrequency": 1.0,
                "allowMirrorX": False,
                "allowMirrorY": False,
                "width": 3,
                "height": 3,
                "roadTargetType": 1,
                "roadTarget": {"x": 1, "y": 1},
                "guards": [{"position": {"x": 1, "y": 1}}],
                "buildings": [
                    {
                        "width": 1,
                        "height": 1,
                        "interaction": 2,
                        "position": {"x": 2, "y": 1},
                    }
                ],
                "pickups": [
                    {
                        "position": {"x": 1, "y": 2},
                        "isOptional": False,
                        "canBeHole": False,
                    }
                ],
                "entrances": [{"x": 1, "y": -1}],
                "holeTiles": [],
                "tileContents": [0, 0, 0, 0, 4, 3, 0, 5, 0],
            },
        )


class CatalogTests(unittest.TestCase):
    def test_core_snapshot_uses_native_generator_semantics(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core)
            catalog = ContentCatalogSnapshot.from_core(
                core, allowlist=("random-squad",)
            )
        self.assertEqual(2, len(catalog.native_generator.content_lists))
        self.assertEqual(1, len(catalog.native_generator.content_pools))
        self.assertEqual(1, len(catalog.native_generator.encounter_templates))
        template = catalog.native_generator.encounter_templates[0]
        self.assertEqual(Point(1, 1), template.road_target)
        self.assertEqual((Point(1, 1),), template.guards)
        self.assertEqual(Point(2, 1), template.buildings[0].position)
        self.assertEqual(Point(1, 2), template.pickups[0].position)
        self.assertEqual((0, 0, 0, 0, 4, 3, 0, 5, 0), template.tile_contents)
        self.assertEqual(
            "homm3_castle_city",
            catalog.entries_for_faction(
                ContentKind.SETTLEMENT, "homm3_castle"
            )[0].sid,
        )
        encounter = catalog.require_sid(
            "random-squad", kinds=(ContentKind.ENCOUNTER,)
        )
        self.assertTrue(encounter.eligible)
        weighted = catalog.pool_entries(
            "content_pool_default_resources",
            kinds=(ContentKind.REWARD,),
            biome="grass",
        )
        self.assertEqual(("resource_gold", 20), (weighted[0][0].sid, weighted[0][1]))

    def test_meta_content_rejected_without_explicit_allowlist(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core)
            catalog = ContentCatalogSnapshot.from_core(core)
        encounter = next(entry for entry in catalog.entries if entry.sid == "random-squad")
        self.assertFalse(encounter.eligible)
        self.assertEqual("meta_content", encounter.exclusion_reason)

    def test_map_specific_helper_members_require_an_allowlist(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core)
            with zipfile.ZipFile(core, "a") as archive:
                _write_json(
                    archive,
                    "DB/map/objects/homecoming_exact_footprint_objects.json",
                    {
                        "array": [
                            {
                                "id": "homm3_xfp_fixture",
                                "tag": "Environment",
                                "sizeX": 1,
                                "sizeZ": 1,
                                "nodes": [1],
                            }
                        ]
                    },
                )
                _write_json(
                    archive,
                    "DB/map/objects/homm3_envelope_padding_blocker.json",
                    {
                        "array": [
                            {
                                "id": "homm3_envelope_padding_blocker",
                                "tag": "Block",
                                "sizeX": 1,
                                "sizeZ": 1,
                                "nodes": [1],
                            }
                        ]
                    },
                )
            catalog = ContentCatalogSnapshot.from_core(core)
        for sid in ("homm3_xfp_fixture", "homm3_envelope_padding_blocker"):
            entry = next(item for item in catalog.entries if item.sid == sid)
            self.assertFalse(entry.eligible)
            self.assertIn(entry.exclusion_reason, {"scenario_specific_content", "procedural_helper_content"})
    def test_native_pivot_normalizes_footprint_offsets(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core)
            catalog = ContentCatalogSnapshot.from_core(core)
        reward = catalog.require_sid("resource_gold", kinds=(ContentKind.REWARD,))
        self.assertEqual((Point(0, 0),), reward.footprint.occupied)
        self.assertIn(Point(-1, -1), reward.footprint.interaction)
        city = catalog.entries_for_faction(
            ContentKind.SETTLEMENT, "homm3_castle"
        )[0]
        self.assertIn(Point(-1, 1), city.footprint.interaction)


    def test_selected_pool_rejects_unresolved_content(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core, generator_reward_sid="missing_reward")
            catalog = ContentCatalogSnapshot.from_core(core)

        with self.assertRaisesRegex(CatalogBuildError, "unresolved content SID"):
            catalog.pool_entries(
                "content_pool_default_resources",
                kinds=(ContentKind.REWARD,),
                biome="grass",
            )

    def test_custom_manifest_cannot_self_approve_meta_content(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            core = root / "Core.zip"
            manifest = root / "custom.json"
            _build_core(core)
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "homm3.procedural_content_manifest.v1",
                        "content": [
                            {
                                "sid": "custom_reward",
                                "kind": "reward",
                                "eligible": True,
                                "tags": ["meta"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            catalog = ContentCatalogSnapshot.from_core(
                core, custom_manifests=(manifest,)
            )

        entry = next(item for item in catalog.entries if item.sid == "custom_reward")
        self.assertFalse(entry.eligible)
        self.assertEqual("meta_content", entry.exclusion_reason)

    def test_core_catalog_hash_and_parse_use_one_immutable_read(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            core = Path(temporary) / "Core.zip"
            _build_core(core)
            expected_hash = hashlib.sha256(core.read_bytes()).hexdigest()
            original_read_bytes = Path.read_bytes
            reads: list[Path] = []

            def tracked_read_bytes(path: Path) -> bytes:
                reads.append(path.resolve())
                return original_read_bytes(path)

            with (
                mock.patch.object(
                    Path,
                    "read_bytes",
                    autospec=True,
                    side_effect=tracked_read_bytes,
                ),
                mock.patch(
                    "procedural_scenarios.catalog.zipfile.ZipFile",
                    wraps=zipfile.ZipFile,
                ) as open_zip,
            ):
                catalog = ContentCatalogSnapshot.from_core(core)

            self.assertEqual([core.resolve()], reads)
            self.assertIsInstance(open_zip.call_args_list[0].args[0], io.BytesIO)
            self.assertEqual(expected_hash, catalog.core_hash)


    def test_catalog_fingerprint_is_independent_of_core_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "Core.zip"
            second = second_dir / "Renamed.zip"
            _build_core(first)
            shutil.copyfile(first, second)

            first_catalog = ContentCatalogSnapshot.from_core(first)
            second_catalog = ContentCatalogSnapshot.from_core(second)

        self.assertEqual(first_catalog.fingerprint, second_catalog.fingerprint)
        self.assertEqual((("core", first_catalog.core_hash),), first_catalog.source_hashes)

if __name__ == "__main__":
    unittest.main()
