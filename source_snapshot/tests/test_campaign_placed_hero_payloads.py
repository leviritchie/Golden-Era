#!/usr/bin/env python3
"""Unit tests for placed-hero QuestScript payload grants."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_POC = Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import campaign_placed_hero_payloads as php
import campaign_runtime_script as crs


class PlacedHeroPayloadGrantTests(unittest.TestCase):
    def test_tyranell_shaped_head_of_legion_defeat_loot(self) -> None:
        entity = {
            "sourceKey": "0:11:58",
            "sourceIndex": 1570,
            "hasArtifactSet": True,
            "hasGarrison": True,
            "secondarySkillCount": 0,
            "secondarySkills": [],
            "equippedArtifacts": [
                65535,
                65535,
                65535,
                65535,
                65535,
                65535,
                65535,
                65535,
                65535,
                122,
                125,
                65535,
                65535,
                65535,
                65535,
                65535,
                65535,
                0,
                65535,
            ],
            "backpackArtifacts": [],
            "garrisonStacks": [
                {"slot": 0, "creatureType": 1, "count": 200},
                {"slot": 1, "creatureType": 3, "count": 150},
                {"slot": 4, "creatureType": 65535, "count": 0},
            ],
        }
        placed = [
            {
                "objectId": 1570,
                "sourceKey": "0:11:58",
                "heroSid": "h3_campaign_placed_tyranell",
            }
        ]
        unit_map = {1: "h3_pikeman", 3: "h3_archer"}
        plan = php.plan_placed_hero_payload_grants(
            mission_id="gathering_the_legion",
            placed_heroes=placed,
            entities_by_id={1570: entity},
            creature_to_unit=lambda cid: unit_map.get(int(cid)),
        )
        loot_sids = {row["itemSid"] for row in plan.defeat_loot}
        self.assertIn("homm3_artifact_122_head_of_legion", loot_sids)
        self.assertIn("homm3_artifact_125_shackles_of_war", loot_sids)
        self.assertNotIn("homm3_artifact_000_spell_book", loot_sids)
        self.assertTrue(
            all(row["killedHeroSid"] == "h3_campaign_placed_tyranell" for row in plan.defeat_loot)
        )
        unit_actions = [row for row in plan.actions if row["a"] == "GiveUnitHero"]
        self.assertEqual(len(unit_actions), 2)
        self.assertEqual(
            unit_actions[0]["p"], ["h3_pikeman", "200", "h3_campaign_placed_tyranell"]
        )
        self.assertFalse(any(row["a"] == "GiveItemHero" for row in plan.actions))

        quests = php.build_placed_hero_payload_quests(
            "gathering_the_legion",
            plan,
            start_turn_condition=crs._briefing_start_turn,
            human_hero_sid="homm3_stronghold_hero_1",
        )
        self.assertEqual(len(quests), 2)
        self.assertEqual(quests[0]["sharing"], "Ai")
        loot_quest = quests[1]
        self.assertEqual(loot_quest["sharing"], "Clone")
        trigger = loot_quest["subQuests"][0]["triggers"][0]
        self.assertEqual(trigger["conditions"][0]["c"], "HeroKill")
        self.assertEqual(trigger["conditions"][0]["p"], ["h3_campaign_placed_tyranell"])
        item_actions = [row for row in trigger["actions"] if row["a"] == "GiveItemHero"]
        self.assertTrue(
            all(row["p"][1] == "homm3_stronghold_hero_1" for row in item_actions)
        )
        chunk = {"quests": quests}
        php.assert_script_covers_placed_hero_payloads(
            chunk, plan, human_hero_sid="homm3_stronghold_hero_1"
        )

    def test_empty_slots_ignored_without_payload_flags(self) -> None:
        entity = {
            "sourceKey": "0:1:1",
            "hasArtifactSet": False,
            "hasGarrison": False,
            "secondarySkillCount": 0,
            "equippedArtifacts": [65535, 65535],
            "backpackArtifacts": [],
            "garrisonStacks": [],
        }
        plan = php.plan_placed_hero_payload_grants(
            mission_id="probe",
            placed_heroes=[{"objectId": 1, "heroSid": "homm3_castle_hero_1"}],
            entities_by_id={1: entity},
            creature_to_unit=lambda _cid: None,
        )
        self.assertEqual(plan.actions, [])
        self.assertEqual(plan.defeat_loot, [])

    def test_spell_book_only_has_artifact_set_is_not_custom_payload(self) -> None:
        """OE heroes already have a spell book; H3 book-only rows need no grant."""
        # Mot-shaped RoE row: hasArtifactSet + slot 17 Spell Book only.
        entity = {
            "sourceKey": "0:63:66",
            "hasArtifactSet": True,
            "hasGarrison": False,
            "secondarySkillCount": 0,
            "secondarySkills": [],
            "equippedArtifacts": [65535] * 17 + [0],
            "backpackArtifacts": [],
            "garrisonStacks": [],
        }
        self.assertFalse(php.entity_has_custom_payload(entity))
        plan = php.plan_placed_hero_payload_grants(
            mission_id="corporeal_punishment",
            placed_heroes=[{"objectId": 66, "heroSid": "homm3_inferno_hero_1", "sourceKey": "0:63:66"}],
            entities_by_id={66: entity},
            creature_to_unit=lambda _cid: None,
        )
        self.assertEqual(plan.actions, [])
        self.assertEqual(plan.defeat_loot, [])
        self.assertEqual(plan.heroes, [])

        # Empty decode with the flag still fails closed (decode regression).
        empty_flag = {
            "sourceKey": "0:0:0",
            "hasArtifactSet": True,
            "hasGarrison": False,
            "secondarySkillCount": 0,
            "secondarySkills": [],
            "equippedArtifacts": [65535] * 18,
            "backpackArtifacts": [],
            "garrisonStacks": [],
        }
        self.assertTrue(php.entity_has_custom_payload(empty_flag))
        with self.assertRaises(php.PlacedHeroPayloadError):
            php.plan_placed_hero_payload_grants(
                mission_id="probe",
                placed_heroes=[{"objectId": 1, "heroSid": "homm3_castle_hero_1"}],
                entities_by_id={1: empty_flag},
                creature_to_unit=lambda _cid: None,
            )

    def test_secondary_skills_add_skill_hero(self) -> None:
        entity = {
            "sourceKey": "0:2:2",
            "hasArtifactSet": False,
            "hasGarrison": False,
            "secondarySkillCount": 1,
            "secondarySkills": [{"skillId": 6, "level": 1}],
            "equippedArtifacts": [],
            "garrisonStacks": [],
        }
        plan = php.plan_placed_hero_payload_grants(
            mission_id="probe",
            placed_heroes=[{"objectId": 2, "heroSid": "homm3_castle_hero_1"}],
            entities_by_id={2: entity},
            creature_to_unit=lambda _cid: None,
        )
        skill_actions = [row for row in plan.actions if row["a"] == "AddSkillHero"]
        self.assertEqual(len(skill_actions), 2)  # advanced = two grants
        self.assertEqual(skill_actions[0]["p"], ["skill_leadership", "homm3_castle_hero_1"])

    def test_armor_of_the_damned_expands_components(self) -> None:
        entity = {
            "sourceKey": "0:67:6",
            "hasArtifactSet": True,
            "equippedArtifacts": [132, 65535],
            "backpackArtifacts": [],
            "garrisonStacks": [],
            "secondarySkillCount": 0,
            "secondarySkills": [],
        }
        plan = php.plan_placed_hero_payload_grants(
            mission_id="fall_of_sandro",
            placed_heroes=[{"objectId": 9, "heroSid": "homm3_necropolis_hero_1"}],
            entities_by_id={9: entity},
            creature_to_unit=lambda _cid: None,
        )
        item_sids = {row["itemSid"] for row in plan.defeat_loot}
        self.assertIn("homm3_artifact_020_skull_helmet", item_sids)
        self.assertIn("homm3_artifact_008_blackshard_of_the_dead_knight", item_sids)
        self.assertIn("homm3_artifact_026_rib_cage", item_sids)
        self.assertIn("homm3_artifact_014_shield_of_the_yawning_dead", item_sids)

    def test_prison_payload_is_scoped_to_that_prison_interaction(self) -> None:
        entity = {
            "sourceKey": "0:3:5",
            "hasArtifactSet": True,
            "equippedArtifacts": [],
            "backpackArtifacts": [48],
            "garrisonStacks": [],
            "secondarySkillCount": 0,
            "secondarySkills": [],
        }
        placed = [
            {
                "objectId": 902,
                "sourceKey": "0:3:5",
                "heroSid": "h3_campaign_placed_gen_kendal",
                "hostKind": "prison",
                "entitySid": "steadwick_liberation_prison_902",
            }
        ]
        plan = php.plan_placed_hero_payload_grants(
            mission_id="steadwick_liberation",
            placed_heroes=placed,
            entities_by_id={902: entity},
            creature_to_unit=lambda _cid: None,
        )

        quests = php.build_placed_hero_payload_quests(
            "steadwick_liberation",
            plan,
            start_turn_condition=crs._briefing_start_turn,
            human_hero_sid="homm3_castle_hero_7",
        )
        self.assertEqual(len(quests), 1)
        triggers = quests[0]["subQuests"][0]["triggers"]
        arm_trigger = triggers[0]
        grant_trigger = triggers[1]
        self.assertEqual(
            arm_trigger["conditions"],
            [
                {
                    "comment": "",
                    "c": "ObjectInteractionAfter",
                    "p": ["steadwick_liberation_prison_902"],
                    "counter": 1,
                }
            ],
        )
        self.assertEqual(
            arm_trigger["actions"],
            [
                {
                    "comment": (
                        "defer prison payload until next side start "
                        "for h3_campaign_placed_gen_kendal"
                    ),
                    "a": "CounterSet",
                    "p": [
                        "steadwick_liberation_prison_rescue_payload_0_pending",
                        "1",
                    ],
                }
            ],
        )
        self.assertEqual(
            grant_trigger["conditions"],
            [
                {
                    "comment": "",
                    "c": "CounterEqualityInDays",
                    "p": [
                        "steadwick_liberation_prison_rescue_payload_0_pending",
                        "1",
                    ],
                    "counter": 1,
                }
            ],
        )
        self.assertEqual(
            grant_trigger["actions"][0],
            {
                "comment": "prison rescue 0:3:5 artifact 48",
                "a": "GiveItemHero",
                "p": ["homm3_artifact_048_ladybird_of_luck", "h3_campaign_placed_gen_kendal"],
            },
        )
        self.assertEqual(
            grant_trigger["actions"][-1],
            {
                "comment": "",
                "a": "CounterSet",
                "p": ["steadwick_liberation_prison_rescue_payload_0_pending", "0"],
            },
        )
        self.assertFalse(any(row["a"] == "GiveItemHero" for row in plan.defeat_loot))


if __name__ == "__main__":
    unittest.main()
