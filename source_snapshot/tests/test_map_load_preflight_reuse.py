#!/usr/bin/env python3
"""Focused tests for invocation-scoped map/Core reuse in map preflight."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
POC = ROOT / "experiments" / "campaign_port_poc"
for import_path in (str(TOOLS), str(POC)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

import map_load_preflight as preflight  # noqa: E402
import port_homecoming_poc  # noqa: E402
import validate_map_load_preflight_contract as validator  # noqa: E402


MISSION = {
    "array": [
        {
            "variants": [
                {
                    "sides": [],
                    "difficulties": [],
                }
            ]
        }
    ]
}


class MemoryArchive:
    def __init__(self, members: dict[str, bytes], name_reads: list[str]) -> None:
        self.members = members
        self.name_reads = name_reads
        self.closed = False

    def namelist(self) -> list[str]:
        self.name_reads.append("namelist")
        return list(self.members)

    def read(self, member: str) -> bytes:
        return self.members[member]

    def close(self) -> None:
        self.closed = True


class MapLoadPreflightReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "__map_load_preflight_synthetic_fixture__"
        self.game_root = self.root / "game"
        self.core_zip = self.game_root / preflight.CORE_ZIP_REL
        self.map_path = self.game_root / preflight.STORY_MAPS_REL / "fixture.map"
        self.core_members = self._core_members()

    def _core_members(self) -> dict[str, bytes]:
        resource_ids = list(preflight.NATIVE_RESOURCE_LOGIC_IDS)
        camp_ids = list(preflight.CAMP_FIRE_META_ALIAS_IDS)
        documents: dict[str, object] = {
            preflight.NATIVE_CAMP_FIRE_OBJECT_MEMBER: {
                "array": [{"id": sid} for sid in resource_ids + camp_ids]
            },
            "DB/map/objects/fixture.json": {"array": [{"id": "fixture_object"}]},
            preflight.RESOURCES_LOGIC_MEMBER: {
                "array": [{"id": sid} for sid in resource_ids]
            },
            preflight.RESOURCES_CAMPS_LOGIC_MEMBER: {
                "array": [{"id": sid} for sid in camp_ids]
            },
            "DB/map/tiles/tiles.json": {"array": [{"id": 2, "biome": "Sand"}]},
            "DB/map/waters/waters.json": {
                "array": [{"id": 2, "name": "water sand"}]
            },
            "DB/buildings_constructions/fixture.json": {"array": []},
            "campaigns/fixture/missions/fixture.json": MISSION,
            "DB/map/objects/replace.json": {"array": [{"id": "base_object"}]},
            "DB/objects_logic/fixture/replace.json": {
                "array": [{"id": "base_logic"}]
            },
            "DB/buildings_constructions/replace.json": {
                "array": [
                    {"id": "construction_keep", "value": "base"},
                    {"id": "construction_replace", "value": "base"},
                ]
            },
        }
        for member in preflight.META_MAP_OBJECT_LOGIC_MEMBERS:
            documents.setdefault(member, {"array": []})
        return {
            member: json.dumps(document, ensure_ascii=True).encode("utf-8")
            for member, document in documents.items()
        }

    @contextlib.contextmanager
    def _virtual_files(self, *paths: Path) -> Iterator[None]:
        real_is_file = Path.is_file
        available = {Path(path) for path in paths}

        def is_file(path: Path) -> bool:
            return Path(path) in available or real_is_file(path)

        with patch.object(Path, "is_file", new=is_file):
            yield

    @contextlib.contextmanager
    def _core_archive(self) -> Iterator[tuple[list[Path], list[str]]]:
        opens: list[Path] = []
        name_reads: list[str] = []

        def open_archive(path: Path, *args: object, **kwargs: object) -> MemoryArchive:
            opens.append(Path(path))
            return MemoryArchive(self.core_members, name_reads)

        with patch.object(preflight.zipfile, "ZipFile", new=open_archive):
            yield opens, name_reads

    @staticmethod
    def _valid_map_data() -> dict[str, object]:
        return {
            "objects": [],
            "objectsProperties": {},
            "tilesMap": [],
            "waterMap": [],
            "levelsMap": [],
        }

    def _container(
        self, *, map_data: object | None = None, chunks: list[object] | None = None
    ) -> SimpleNamespace:
        if chunks is None:
            chunks = [
                {},
                self._valid_map_data() if map_data is None else map_data,
                {},
                {"counters": [], "quests": []},
            ]
        return SimpleNamespace(chunks=chunks)

    def _run(
        self,
        container: object,
        *,
        map_rows: list[dict[str, object]] | None = None,
    ) -> tuple[list[preflight.PreflightIssue], object, tuple[list[Path], list[str]]]:
        if map_rows is None:
            map_rows = [
                {
                    "mapSid": "fixture-map",
                    "mapPath": self.map_path,
                    "mission": MISSION,
                    "missionLabel": "fixture-mission",
                    "missionId": "fixture-mission",
                }
            ]
        with (
            self._virtual_files(self.core_zip, self.map_path),
            self._core_archive() as core_metrics,
            patch.object(
                port_homecoming_poc,
                "read_olden_map_container",
                return_value=container,
            ) as map_reader,
        ):
            issues = preflight.run_installed_campaign_preflight(
                game_root=self.game_root,
                core_zip=self.core_zip,
                map_checks=map_rows,
                require_story_maps=False,
            )
        return issues, map_reader, core_metrics

    @staticmethod
    def _issue_rows(issues: list[preflight.PreflightIssue]):
        return [(issue.signature, issue.message, issue.context) for issue in issues]

    def test_cli_uses_one_core_archive_index_and_one_map_parse(self) -> None:
        opens: list[Path] = []
        name_reads: list[str] = []
        map_container = self._container()
        install_row = {
            "mapSid": "fixture",
            "missionMember": "campaigns/fixture/missions/fixture.json",
            "coreOverlay": Path("unused-overlay"),
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "validate_map_load_preflight_contract.py",
            "--repo-root",
            str(self.root),
            "--game-root",
            str(self.game_root),
            "--hub",
            "fixture",
        ]
        with (
            self._virtual_files(self.core_zip, self.map_path),
            self._core_archive() as core_metrics,
            patch.object(validator, "HUB_MAP_INSTALLS", {"fixture": [install_row]}),
            patch.object(validator, "ALL_HUB_CHOICES", ("fixture",)),
            patch.object(sys, "argv", argv),
            patch.object(
                port_homecoming_poc,
                "read_olden_map_container",
                return_value=map_container,
            ) as map_reader,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = validator.main()
            opens, name_reads = core_metrics

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("mapChecks=1", stdout.getvalue())
        self.assertEqual(opens, [self.core_zip])
        self.assertEqual(name_reads, ["namelist"])
        map_reader.assert_called_once_with(self.map_path)

    def test_repeated_separated_map_rows_share_snapshot_without_deduplicating_checks(self) -> None:
        container = self._container()
        other_map = self.game_root / preflight.STORY_MAPS_REL / "other.map"
        rows = [
            {"mapSid": "fixture-a", "mapPath": self.map_path},
            {"mapSid": "fixture-other", "mapPath": other_map},
            {"mapSid": "fixture-b", "mapPath": self.map_path},
        ]
        with (
            self._virtual_files(self.core_zip, self.map_path, other_map),
            self._core_archive(),
            patch.object(
                port_homecoming_poc,
                "read_olden_map_container",
                return_value=container,
            ) as map_reader,
        ):
            issues = preflight.run_installed_campaign_preflight(
                game_root=self.game_root,
                core_zip=self.core_zip,
                map_checks=rows,
                require_story_maps=False,
            )
        self.assertEqual(self._issue_rows(issues), [])
        self.assertEqual(
            [call.args[0] for call in map_reader.call_args_list],
            [self.map_path, other_map],
        )

    def test_map_read_failure_replays_each_signature_diagnostic(self) -> None:
        sentinel = OSError("synthetic map read failure")
        with (
            self._virtual_files(self.core_zip, self.map_path),
            self._core_archive(),
            patch.object(
                port_homecoming_poc,
                "read_olden_map_container",
                side_effect=sentinel,
            ) as map_reader,
        ):
            issues = preflight.run_installed_campaign_preflight(
                game_root=self.game_root,
                core_zip=self.core_zip,
                map_checks=[
                    {
                        "mapSid": "fixture-map",
                        "mapPath": self.map_path,
                        "mission": MISSION,
                        "missionLabel": "fixture-mission",
                        "missionId": "fixture-mission",
                    }
                ],
                require_story_maps=False,
            )

        path = str(self.map_path)
        failure = "synthetic map read failure"
        self.assertEqual(
            self._issue_rows(issues),
            [
                (
                    "map_sid_missing_objectconfig",
                    f"failed to read map object SIDs for fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_emits_meta_random_res",
                    f"failed to read map object SIDs for fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_random_item_rarity_out_of_range",
                    f"failed to read map for random-item rarity check fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_ocean_retired_or_unresolved",
                    f"failed to read map for ocean check fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_city_construction_sid_missing",
                    f"failed to read map for construction SID check fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_city_garrison_squad_sid_missing",
                    f"failed to read map for town garrison SID check fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_human_city_missing_city_prop_spawn",
                    f"failed to read map for human city spawn bind check fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "map_quest_counter_sid_missing",
                    f"failed to read map quest chunk for fixture-map: {failure}",
                    {"mapPath": path},
                ),
                (
                    "storyhub_owner_missing_side",
                    f"failed to read map owners for fixture-mission: {failure}",
                    {},
                ),
            ],
        )
        map_reader.assert_called_once_with(self.map_path)

    def test_non_object_mapdata_keeps_construction_and_quest_diagnostics_distinct(self) -> None:
        chunks = [{}, "not-mapdata", {}, {"counters": [], "quests": []}]
        issues, map_reader, _core_metrics = self._run(self._container(chunks=chunks))
        path = str(self.map_path)
        data_error = f"mapData chunk is not an object: {path}"
        self.assertEqual(
            self._issue_rows(issues),
            [
                (
                    "map_sid_missing_objectconfig",
                    f"failed to read map object SIDs for fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "map_emits_meta_random_res",
                    f"failed to read map object SIDs for fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "map_random_item_rarity_out_of_range",
                    f"failed to read map for random-item rarity check fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "map_ocean_retired_or_unresolved",
                    f"failed to read map for ocean check fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "map_city_construction_sid_missing",
                    "mapData chunk is not an object: fixture-map",
                    {},
                ),
                (
                    "map_city_garrison_squad_sid_missing",
                    f"failed to read map for town garrison SID check fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "map_human_city_missing_city_prop_spawn",
                    f"failed to read map for human city spawn bind check fixture-map: {data_error}",
                    {"mapPath": path},
                ),
                (
                    "storyhub_owner_missing_side",
                    f"failed to read map owners for fixture-mission: {data_error}",
                    {},
                ),
            ],
        )
        map_reader.assert_called_once_with(self.map_path)

    def test_missing_chunk3_keeps_quest_counter_diagnostic_only(self) -> None:
        chunks = [{}, self._valid_map_data()]
        issues, map_reader, _core_metrics = self._run(self._container(chunks=chunks))
        self.assertEqual(
            self._issue_rows(issues),
            [
                (
                    "map_quest_counter_sid_missing",
                    "fixture-map: map chunk3 missing or not an object",
                    {"mapPath": str(self.map_path)},
                )
            ],
        )
        map_reader.assert_called_once_with(self.map_path)

    def test_standalone_path_apis_parse_independently(self) -> None:
        container = self._container()
        with (
            self._virtual_files(self.core_zip, self.map_path),
            self._core_archive(),
            patch.object(
                port_homecoming_poc,
                "read_olden_map_container",
                return_value=container,
            ) as map_reader,
        ):
            self.assertEqual(preflight.read_map_object_sids(self.map_path), set())
            index = preflight.build_effective_core_index(self.core_zip)
            issues: list[preflight.PreflightIssue] = []
            preflight.check_map_sids_resolve(
                self.map_path, index, issues=issues, map_sid="fixture-map"
            )

        self.assertEqual(self._issue_rows(issues), [])
        self.assertEqual(map_reader.call_count, 2)

    def test_core_reader_and_mission_loader_reject_closed_or_unentered_index(self) -> None:
        mission_member = "campaigns/fixture/missions/fixture.json"
        unopened = preflight.CoreZipIndex(self.core_zip)
        with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
            _ = mission_member in unopened
        with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
            unopened.read(mission_member)
        with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
            validator.load_mission_from_core(unopened, mission_member)

        with self._virtual_files(self.core_zip), self._core_archive():
            with preflight.CoreZipIndex(self.core_zip) as opened:
                self.assertEqual(
                    validator.load_mission_from_core(opened, mission_member),
                    MISSION,
                )
            with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
                _ = mission_member in opened
            with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
                opened.read(mission_member)
            with self.assertRaisesRegex(RuntimeError, "CoreZipIndex is not open"):
                validator.load_mission_from_core(opened, mission_member)

    def test_core_overlay_replacement_and_construction_id_merge_are_unchanged(self) -> None:
        construction_member = "DB/buildings_constructions/replace.json"
        overlay = {
            "DB/map/objects/replace.json": b'{"array":[{"id":"overlay_object"}]}',
            "DB/objects_logic/fixture/replace.json": b'{"array":[{"id":"overlay_logic"}]}',
            construction_member: (
                b'{"array":[{"id":"construction_replace","value":"overlay"},'
                b'{"id":"construction_added","value":"overlay"}]}'
            ),
        }
        with self._virtual_files(self.core_zip), self._core_archive():
            index = preflight.build_effective_core_index(
                self.core_zip, overlay_members=overlay
            )

        self.assertIn("overlay_object", index.object_config_ids)
        self.assertNotIn("base_object", index.object_config_ids)
        self.assertEqual(
            [row["id"] for row in index.logic_by_member["DB/objects_logic/fixture/replace.json"]],
            ["overlay_logic"],
        )
        self.assertTrue(
            {
                "construction_keep",
                "construction_replace",
                "construction_added",
            }.issubset(index.buildings_construction_ids)
        )
        merged_rows = json.loads(
            preflight.merge_id_array_catalog_bytes(
                b'{"array":[{"id":"construction_replace","value":"base"}]}',
                overlay[construction_member],
            )
        )["array"]
        self.assertEqual(
            next(row["value"] for row in merged_rows if row["id"] == "construction_replace"),
            "overlay",
        )


if __name__ == "__main__":
    unittest.main()
