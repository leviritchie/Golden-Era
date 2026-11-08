#!/usr/bin/env python3
"""Unit tests for the authentic HoMM3 default town name pool assignment.

Pins the contract that replaced the old ``f"Town {sourceKey}"`` coordinate
placeholder fallback: unnamed H3M towns must receive deterministic, authentic,
map-unique pool names at build time.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

POC = Path(__file__).resolve().parent
for path in (POC / "raw_translation", POC / "approach_cell", POC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import h3_town_name_pool as pool


def _town(source_key: str, animation: str, name: str | None = None, source_index: int = 0) -> dict:
    return {
        "category": "town",
        "payloadKind": "town",
        "sourceKey": source_key,
        "sourceIndex": source_index,
        "templateAnimation": animation,
        "name": name,
    }


class TownNamePoolShapeTests(unittest.TestCase):
    def test_nine_factions_with_sixteen_names_each(self) -> None:
        self.assertEqual(len(pool.H3_DEFAULT_TOWN_NAMES), 9)
        for faction, names in pool.H3_DEFAULT_TOWN_NAMES.items():
            with self.subTest(faction=faction):
                self.assertEqual(len(names), pool.TOWN_NAMES_PER_FACTION)
                self.assertTrue(all(name.strip() for name in names))

    def test_faction_animation_prefixes(self) -> None:
        cases = {
                "AVCcast0.def": "homm3_castle",
                "avccasx0.def": "homm3_castle",
                "AVCramp0.def": "homm3_rampart",
                "AVCramx0.def": "homm3_rampart",
                "AVCtowr0.def": "homm3_tower",
                "AVCtowx0.def": "homm3_tower",
                "AVCinft0.def": "homm3_inferno",
                "AVCinfx0.def": "homm3_inferno",
                "AVCnecr0.def": "homm3_necropolis",
                "AVCnecx0.def": "homm3_necropolis",
                "AVCdung0.def": "homm3_dungeon",
                "AVCdunx0.def": "homm3_dungeon",
                "AVCstro0.def": "homm3_stronghold",
                "AVCstrx0.def": "homm3_stronghold",
                "AVCfort0.def": "homm3_fortress",
                "AVCftrt0.def": "homm3_fortress",
                "AVCftrx0.def": "homm3_fortress",
                "AVCforx0.def": "homm3_fortress",
                "AVChforx.def": "homm3_fortress",
                "avchforx.def": "homm3_fortress",
                "AVCelem0.def": "homm3_conflux",
                "AVCelex0.def": "homm3_conflux",
        }
        for animation, faction in cases.items():
            with self.subTest(animation=animation):
                self.assertEqual(pool.town_faction_sid_from_animation(animation), faction)
        self.assertIsNone(pool.town_faction_sid_from_animation("AVCcove0.def"))
        self.assertIsNone(pool.town_faction_sid_from_animation(None))
        self.assertIsNone(pool.town_faction_sid_from_animation(""))


class AssignDefaultTownNamesTests(unittest.TestCase):
    def test_assigns_pool_names_to_unnamed_towns(self) -> None:
        entities = [
            _town("0:29:6", "AVCftrx0.def", source_index=0),
            _town("0:67:66", "AVCstrx0.def", source_index=1),
        ]
        report = pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        self.assertEqual(report["assignedCount"], 2)
        self.assertEqual(report["explicitNameCount"], 0)
        for entity in entities:
            self.assertTrue(str(entity["name"]).strip())
        fortress_names = set(pool.H3_DEFAULT_TOWN_NAMES["homm3_fortress"])
        stronghold_names = set(pool.H3_DEFAULT_TOWN_NAMES["homm3_stronghold"])
        self.assertIn(entities[0]["name"], fortress_names)
        self.assertIn(entities[1]["name"], stronghold_names)

    def test_deterministic_per_mission(self) -> None:
        def build() -> list[dict]:
            return [_town(f"0:{x}:{y}", "AVCcast0.def", source_index=i) for i, (x, y) in enumerate([(1, 2), (3, 4), (5, 6)])]

        first = build()
        second = build()
        pool.assign_default_town_names(first, mission_id="unit_test_mission")
        pool.assign_default_town_names(second, mission_id="unit_test_mission")
        self.assertEqual([e["name"] for e in first], [e["name"] for e in second])

    def test_explicit_names_are_never_rewritten(self) -> None:
        entities = [
            _town("0:1:1", "AVCcast0.def", name="Terraneus", source_index=0),
            _town("0:2:2", "AVCcast0.def", source_index=1),
        ]
        pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        self.assertEqual(entities[0]["name"], "Terraneus")
        self.assertNotEqual(entities[1]["name"], "Terraneus")

    def test_explicit_name_is_removed_from_pool_choices(self) -> None:
        explicit = pool.H3_DEFAULT_TOWN_NAMES["homm3_castle"][0]
        entities = [
            _town("0:1:1", "AVCcast0.def", name=explicit, source_index=0),
            *[_town(f"0:{i + 2}:2", "AVCcast0.def", source_index=i + 1) for i in range(15)],
        ]
        report = pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        assigned = [e["name"] for e in entities[1:]]
        self.assertNotIn(explicit, assigned)
        self.assertEqual(len(set(assigned)), 15)
        self.assertEqual(report["exhaustedPoolAssignments"], [])

    def test_cross_faction_duplicate_pool_names_are_avoided(self) -> None:
        # "Strongglen" exists in both the Rampart and Stronghold pools; the
        # used-name set must be map-global like HoMM3.
        rampart_index = pool.H3_DEFAULT_TOWN_NAMES["homm3_rampart"].index("Strongglen")
        entities = [
            _town("0:1:1", "AVCramp0.def", name="Strongglen", source_index=0),
            *[_town(f"0:{i + 2}:2", "AVCstro0.def", source_index=i + 1) for i in range(16)],
        ]
        self.assertEqual(rampart_index, 10)
        report = pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        stronghold_assigned = [e["name"] for e in entities[1:]]
        # 16 unnamed Stronghold towns against a 16-name pool with "Strongglen"
        # blocked: 15 unique names plus exactly one exhausted duplicate.
        self.assertEqual(len(set(stronghold_assigned)), 15)
        self.assertEqual(len(report["exhaustedPoolAssignments"]), 1)
        # The forced duplicate is the only way the blocked name may appear.
        if "Strongglen" in stronghold_assigned:
            self.assertEqual(report["exhaustedPoolAssignments"][0]["name"], "Strongglen")

    def test_pool_exhaustion_cycles_with_duplicate_reported(self) -> None:
        entities = [_town(f"0:{i}:1", "AVCcast0.def", source_index=i) for i in range(17)]
        report = pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        names = [e["name"] for e in entities]
        self.assertEqual(len(set(names)), 16)
        self.assertEqual(len(report["exhaustedPoolAssignments"]), 1)
        self.assertTrue(report["exhaustedPoolAssignments"][0]["duplicatePoolName"])

    def test_cross_layer_towns_share_one_used_set(self) -> None:
        entities = [
            _town("0:1:1", "AVCcast0.def", source_index=0),
            _town("1:1:1", "AVCcast0.def", source_index=1),
        ]
        pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        self.assertNotEqual(entities[0]["name"], entities[1]["name"])

    def test_unknown_faction_unnamed_town_fails_closed(self) -> None:
        entities = [_town("0:1:1", "AVCcove0.def", source_index=0)]
        with self.assertRaises(ValueError):
            pool.assign_default_town_names(entities, mission_id="unit_test_mission")

    def test_empty_mission_id_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            pool.assign_default_town_names([], mission_id="")

    def test_non_town_entities_are_ignored(self) -> None:
        entities = [
            {"category": "monster", "sourceKey": "0:1:1", "name": None},
            _town("0:2:2", "AVCcast0.def", source_index=1),
        ]
        report = pool.assign_default_town_names(entities, mission_id="unit_test_mission")
        self.assertEqual(report["townCount"], 1)
        self.assertIsNone(entities[0]["name"])


if __name__ == "__main__":
    unittest.main()
