#!/usr/bin/env python3
"""Tests for orphan random-hero takenHeroes native parity."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc" / "approach_cell"))

import surface_emit as single  # noqa: E402


class TakenHeroesSyncTests(unittest.TestCase):
    def test_orphan_defined_prop_hero_added_to_taken_heroes(self) -> None:
        player_spawns = {
            "takenHeroes": ["homm3_stronghold_hero_7", "homm3_castle_hero_7"],
        }
        properties = {
            "propHeroes": [
                {
                    "type": 0,
                    "id": 0,
                    "isDefined": True,
                    "heroSid": "homm3_stronghold_hero_7",
                },
                {
                    "type": 0,
                    "id": 631,
                    "isDefined": True,
                    "heroSid": "homm3_castle_hero_7",
                },
                {
                    "type": 0,
                    "id": 1570,
                    "isDefined": True,
                    "heroSid": "homm3_castle_hero_8",
                },
                {"type": 0, "id": 99, "isDefined": False, "heroSid": "random"},
            ]
        }
        report = single.sync_taken_heroes_from_defined_prop_heroes(
            player_spawns, properties
        )
        self.assertEqual(report["added"], ["homm3_castle_hero_8"])
        self.assertEqual(
            player_spawns["takenHeroes"],
            [
                "homm3_stronghold_hero_7",
                "homm3_castle_hero_7",
                "homm3_castle_hero_8",
            ],
        )

    def test_random_placeholder_sid_not_added(self) -> None:
        player_spawns = {"takenHeroes": ["hero_a"]}
        properties = {
            "propHeroes": [
                {"type": 0, "id": 1, "isDefined": True, "heroSid": "random"},
            ]
        }
        report = single.sync_taken_heroes_from_defined_prop_heroes(
            player_spawns, properties
        )
        self.assertEqual(report["added"], [])
        self.assertEqual(player_spawns["takenHeroes"], ["hero_a"])


if __name__ == "__main__":
    unittest.main()
