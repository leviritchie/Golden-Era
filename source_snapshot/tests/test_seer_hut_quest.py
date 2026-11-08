"""Unit tests for shared Seer's Hut QuestScript compile."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "experiments" / "campaign_port_poc"
if str(CAMPAIGN) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN))

from seer_hut_quest import (  # noqa: E402
    SeerHutQuestError,
    SeerMissionBringArtifacts,
    SeerMissionBringResources,
    SeerMissionDefeatSquad,
    SeerQuestPlan,
    SeerQuestTexts,
    SeerRewardExperience,
    SeerRewardResource,
    assert_supported_mission_type,
    compile_seer_quest_subquests,
    compile_seer_quest_triggers,
    declared_counters_for_plan,
    homm3_seer_hut_event_bank_doc,
    homm3_seer_hut_object_row,
)
import exact_homm3_footprint as exact_fp  # noqa: E402


class SeerHutQuestCompileTests(unittest.TestCase):
    def test_object_row_matches_wise_owl_donor_footprint(self) -> None:
        row = homm3_seer_hut_object_row()
        self.assertEqual(row["id"], "homm3_seer_hut")
        self.assertTrue(row["isInteractable"])
        self.assertEqual(row["sizeX"], 2)
        self.assertEqual(row["sizeZ"], 2)
        self.assertEqual(row["nodes"], [1, 2, 2, 2])
        self.assertEqual(row["prefs"], ["interactive/wise_owl"])
        self.assertIn(2, row["nodes"])

    def test_event_bank_is_nonempty_noop_shell(self) -> None:
        doc = homm3_seer_hut_event_bank_doc()
        row = doc["array"][0]
        self.assertEqual(row["id"], "homm3_seer_hut")
        self.assertEqual(row["tooltipVisitType"], "NoRewardAndScouting")
        rewards = row["variants"][0]["rewardSet"]["rewards"]
        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0]["rewardType"], "MovePointsAdditionReward")
        self.assertEqual(rewards[0]["parameters"], ["0"])

    def test_seer_hut_classifies_as_single_gate_for_visit_align(self) -> None:
        row = homm3_seer_hut_object_row()
        self.assertEqual(
            exact_fp.classify_object_config_shape(row, "homm3_seer_hut"),
            "single_gate",
        )
        footprint = exact_fp.footprint_from_donor_config(row)
        self.assertIsNotNone(footprint.gate_config_x)
        self.assertIsNotNone(footprint.gate_config_z)
        # wise_owl donor alone stays "other" (3 GATE markers) — seer SID is the pin.
        wise = dict(row)
        wise["id"] = "wise_owl"
        self.assertEqual(exact_fp.classify_object_config_shape(wise, "wise_owl"), "other")

    def test_defeat_squad_fsm_emits_offer_incomplete_complete(self) -> None:
        plan = SeerQuestPlan(
            quest_id="test_seer",
            hut_entity_sid="hut_1",
            state_counter_sid="test_seer_state",
            task_counter_sid="test_seer_task",
            mission=SeerMissionDefeatSquad(squad_sid="squad_1"),
            reward=SeerRewardExperience(amount=1000),
            texts=SeerQuestTexts("first", "next", "done"),
        )
        triggers = compile_seer_quest_triggers(plan)
        comments = [row["comment"] for row in triggers]
        self.assertIn("test_seer_offer", comments)
        self.assertIn("test_seer_incomplete", comments)
        self.assertIn("test_seer_ready", comments)
        self.assertIn("test_seer_complete", comments)
        self.assertEqual(
            declared_counters_for_plan(plan),
            ("test_seer_state", "test_seer_task"),
        )
        complete = next(row for row in triggers if row["comment"] == "test_seer_complete")
        self.assertEqual(
            [(condition["c"], condition["p"]) for condition in complete["conditions"]],
            [("ObjectInteractionBefore", ["hut_1"])],
        )
        self.assertNotIn(
            "ObjectInteractionAfter",
            [condition["c"] for condition in complete["conditions"]],
        )
        actions = [row["a"] for row in complete["actions"]]
        self.assertIn("GiveExpHero", actions)
        self.assertIn("Dialog", actions)
        self.assertNotIn("EntityActionsOff", actions)
        self.assertNotIn("DeleteEntity", actions)
        offer = next(row for row in triggers if row["comment"] == "test_seer_offer")
        self.assertNotIn(
            "EntityActionsOff",
            [row["a"] for row in offer["actions"]],
            "EntityActionsOff on offer blocks incomplete/complete visits",
        )
        ready = next(row for row in triggers if row["comment"] == "test_seer_ready")
        self.assertEqual(
            [(condition["c"], condition["p"]) for condition in ready["conditions"]],
            [("SquadKill", ["squad_1"])],
        )

    def test_seer_visit_checks_use_repeatable_incomplete_stage(self) -> None:
        plan = SeerQuestPlan(
            quest_id="rotating_seer",
            hut_entity_sid="hut_1",
            state_counter_sid="rotating_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("ladybird",)),
            reward=SeerRewardExperience(amount=1000),
            texts=SeerQuestTexts("first", "next", "done"),
        )

        subquests = compile_seer_quest_subquests(plan)
        self.assertEqual(
            [row["sid"] for row in subquests],
            [
                "rotating_seer_offer",
                "rotating_seer_incomplete",
                "rotating_seer_ready",
                "rotating_seer_complete",
            ],
        )
        self.assertTrue(subquests[0]["activeOnStart"])
        self.assertFalse(subquests[1]["activeOnStart"])
        self.assertFalse(subquests[2]["activeOnStart"])
        self.assertFalse(subquests[3]["activeOnStart"])

        offer = subquests[0]["triggers"][0]
        incomplete = subquests[1]["triggers"][0]
        ready = subquests[2]["triggers"][0]
        complete = subquests[3]["triggers"][0]
        for trigger in (offer, incomplete, complete):
            self.assertEqual(
                [(condition["c"], condition["p"]) for condition in trigger["conditions"]],
                [("ObjectInteractionBefore", ["hut_1"])],
            )
        self.assertEqual(
            [(condition["c"], condition["p"]) for condition in ready["conditions"]],
            [("ItemOwnSide", ["ladybird", ">", "0"])],
        )
        self.assertIn(
            ("SubQuestActivate", ["rotating_seer", "rotating_seer_incomplete"]),
            [(action["a"], action["p"]) for action in offer["actions"]],
        )
        self.assertIn(
            ("SubQuestDeactivate", ["rotating_seer", "rotating_seer_offer"]),
            [(action["a"], action["p"]) for action in offer["actions"]],
        )
        self.assertTrue(incomplete["repeat"])
        self.assertFalse(complete["repeat"])
        self.assertEqual(
            incomplete["actions"],
            [{"comment": "", "a": "Dialog", "p": ["rotating_seer_next"]}],
        )
        self.assertIn(
            ("SubQuestActivate", ["rotating_seer", "rotating_seer_complete"]),
            [(action["a"], action["p"]) for action in ready["actions"]],
        )
        self.assertEqual(
            complete["actions"][-1],
            {
                "comment": "",
                "a": "SubQuestDone",
                "p": ["rotating_seer", "rotating_seer_complete"],
            },
        )

    def test_bring_resources_uses_res_counter_and_remove(self) -> None:
        plan = SeerQuestPlan(
            quest_id="res_seer",
            hut_entity_sid="hut_2",
            state_counter_sid="res_seer_state",
            mission=SeerMissionBringResources(resources=(("gold", 2500),)),
            reward=SeerRewardResource(resource="wood", amount=10),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        triggers = compile_seer_quest_triggers(plan)
        complete = next(row for row in triggers if row["comment"] == "res_seer_complete")
        self.assertEqual([row["c"] for row in complete["conditions"]], ["ObjectInteractionBefore"])
        ready = next(row for row in triggers if row["comment"] == "res_seer_ready")
        self.assertIn("ResCounter", [row["c"] for row in ready["conditions"]])
        actions = [row["a"] for row in complete["actions"]]
        self.assertIn("RemoveRes", actions)
        self.assertIn("GiveRes", actions)

    def test_bring_artifacts_uses_item_own_side(self) -> None:
        plan = SeerQuestPlan(
            quest_id="art_seer",
            hut_entity_sid="hut_3",
            state_counter_sid="art_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("some_artifact",)),
            reward=SeerRewardExperience(amount=500),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        triggers = compile_seer_quest_triggers(plan)
        complete = next(row for row in triggers if row["comment"] == "art_seer_complete")
        self.assertEqual(
            [row.get("c") for row in complete["conditions"]],
            ["ObjectInteractionBefore"],
        )
        ready = next(row for row in triggers if row["comment"] == "art_seer_ready")
        self.assertTrue(
            any(row.get("c") == "ItemOwnSide" for row in ready["conditions"])
        )
        self.assertTrue(any(row.get("a") == "RemoveItem" for row in complete["actions"]))

    def test_empty_map_texts_get_genrltxt_artifact_defaults(self) -> None:
        from seer_hut_quest import (
            SeerRewardArtifact,
            coalesce_seer_quest_texts,
            default_seer_quest_texts,
        )

        mission = SeerMissionBringArtifacts(
            item_sids=("homm3_artifact_048_ladybird_of_luck",)
        )
        reward = SeerRewardArtifact(item_sid="homm3_artifact_049_badge_of_courage")
        texts = coalesce_seer_quest_texts(SeerQuestTexts("", "", ""), mission, reward)
        self.assertIn("Ladybird of Luck", texts.first_visit)
        self.assertIn("Ladybird of Luck", texts.next_visit)
        self.assertIn("Ladybird of Luck", texts.completed)
        self.assertNotEqual(texts.first_visit, "Seer's Hut")
        # Custom map text wins per-slot.
        custom = coalesce_seer_quest_texts(
            SeerQuestTexts("Custom offer.", "", "Custom done."),
            mission,
            reward,
        )
        self.assertEqual(custom.first_visit, "Custom offer.")
        self.assertEqual(custom.completed, "Custom done.")
        self.assertEqual(
            custom.next_visit,
            default_seer_quest_texts(mission, reward).next_visit,
        )

    def test_none_reward_consumes_without_grants(self) -> None:
        from seer_hut_quest import SeerRewardNone

        plan = SeerQuestPlan(
            quest_id="none_seer",
            hut_entity_sid="hut_none",
            state_counter_sid="none_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("art",)),
            reward=SeerRewardNone(),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        complete = next(
            row
            for row in compile_seer_quest_triggers(plan)
            if row["comment"] == "none_seer_complete"
        )
        actions = [row.get("a") for row in complete["actions"]]
        self.assertIn("RemoveItem", actions)
        self.assertNotIn("GiveExpHero", actions)
        self.assertNotIn("GiveRes", actions)
        self.assertNotIn("GiveItemHero", actions)
        self.assertNotIn("GiveUnitHero", actions)
        self.assertNotIn("GiveStatsHero", actions)
        self.assertNotIn("AddSpellHero", actions)

    def test_unsupported_mission_fail_closed(self) -> None:
        with self.assertRaises(SeerHutQuestError):
            assert_supported_mission_type(1, context="test")

    def test_primary_skill_reward_emits_give_stats_hero(self) -> None:
        from seer_hut_quest import SeerRewardPrimarySkill

        plan = SeerQuestPlan(
            quest_id="stat_seer",
            hut_entity_sid="hut_stat",
            state_counter_sid="stat_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("art",)),
            reward=SeerRewardPrimarySkill(stat="offence", amount=3),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        complete = next(
            row
            for row in compile_seer_quest_triggers(plan)
            if row["comment"] == "stat_seer_complete"
        )
        self.assertIn(
            {"comment": "seer primary skill offence +3", "a": "GiveStatsHero", "p": ["offence", "", "3"]},
            complete["actions"],
        )

    def test_spell_reward_emits_add_spell_hero(self) -> None:
        from seer_hut_quest import SeerRewardSpell

        plan = SeerQuestPlan(
            quest_id="spell_seer",
            hut_entity_sid="hut_spell",
            state_counter_sid="spell_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("art",)),
            reward=SeerRewardSpell(magic_sid="space_6_magic_blink"),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        complete = next(
            row
            for row in compile_seer_quest_triggers(plan)
            if row["comment"] == "spell_seer_complete"
        )
        self.assertIn(
            {
                "comment": "seer spell space_6_magic_blink",
                "a": "AddSpellHero",
                "p": ["space_6_magic_blink", ""],
            },
            complete["actions"],
        )

    def test_hero_buff_days_reward_emits_add_buff_hero_days(self) -> None:
        from seer_hut_quest import SeerRewardHeroBuffDays

        plan = SeerQuestPlan(
            quest_id="buff_seer",
            hut_entity_sid="hut_buff",
            state_counter_sid="buff_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("art",)),
            reward=SeerRewardHeroBuffDays(buff_sid="campaign_morale_buff", days=999),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        complete = next(
            row
            for row in compile_seer_quest_triggers(plan)
            if row["comment"] == "buff_seer_complete"
        )
        self.assertIn(
            {
                "comment": "seer hero buff campaign_morale_buff for 999 days",
                "a": "AddBuffHeroDays",
                "p": ["campaign_morale_buff", "", "999"],
            },
            complete["actions"],
        )

    def test_mana_restore_reward_emits_change_mana_hero_full(self) -> None:
        from seer_hut_quest import SeerRewardManaRestore

        plan = SeerQuestPlan(
            quest_id="mana_seer",
            hut_entity_sid="hut_mana",
            state_counter_sid="mana_seer_state",
            mission=SeerMissionBringArtifacts(item_sids=("art",)),
            reward=SeerRewardManaRestore(),
            texts=SeerQuestTexts("a", "b", "c"),
        )
        complete = next(
            row
            for row in compile_seer_quest_triggers(plan)
            if row["comment"] == "mana_seer_complete"
        )
        self.assertIn(
            {
                "comment": "seer mana substitute: refill visiting hero to 100%",
                "a": "ChangeManaHero",
                "p": ["", "100"],
            },
            complete["actions"],
        )


class SeerHutSubstituteTests(unittest.TestCase):
    """Hand-crafted substitutes for H3 quests OE cannot port natively."""

    def _entity(self, quest: dict, *, source_key: str = "0:0:0") -> dict:
        return {"sourceKey": source_key, "quest": quest}

    def test_substitute_applies_when_native_path_fails(self) -> None:
        from seer_hut_campaign_bind import plan_from_seer_entity
        from seer_hut_substitutes import SEER_HUT_SUBSTITUTES

        entry = {
            "original": "mission type 1: reach experience level 99",
            "rationale": "unit test entry",
            "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 1000]},
            "texts": {
                "first_visit": "offer",
                "next_visit": "interim",
                "completed": "done",
            },
        }
        SEER_HUT_SUBSTITUTES[("unit_test_map", "0:0:0")] = entry
        try:
            plan = plan_from_seer_entity(
                self._entity({"missionType": 1, "experienceLevel": 99, "rewardType": 1,
                              "reward": {"rewardType": 1, "experience": 10}}),
                hut_entity_sid="hut_1",
                mission_id="unit_test_map",
            )
        finally:
            SEER_HUT_SUBSTITUTES.pop(("unit_test_map", "0:0:0"), None)
        self.assertIsInstance(plan.mission, SeerMissionBringResources)
        self.assertEqual(plan.mission.resources, (("gold", 1000),))
        self.assertEqual(plan.texts.first_visit, "offer")
        self.assertIsNotNone(plan.substitution_note)
        self.assertIn("unit test entry", plan.substitution_note)

    def test_stale_substitute_fails_closed_when_native_path_works(self) -> None:
        from seer_hut_campaign_bind import plan_from_seer_entity
        from seer_hut_substitutes import SEER_HUT_SUBSTITUTES

        entry = {
            "original": "pretend unsupported",
            "rationale": "unit test stale entry",
            "reward": {"rewardType": "mana_restore"},
        }
        SEER_HUT_SUBSTITUTES[("unit_test_map", "0:0:0")] = entry
        try:
            with self.assertRaises(SeerHutQuestError) as ctx:
                plan_from_seer_entity(
                    self._entity(
                        {
                            "missionType": 7,
                            "requiredResources": [0, 0, 0, 0, 0, 0, 100],
                            "rewardType": 1,
                            "reward": {"rewardType": 1, "experience": 10},
                        }
                    ),
                    hut_entity_sid="hut_1",
                    mission_id="unit_test_map",
                )
        finally:
            SEER_HUT_SUBSTITUTES.pop(("unit_test_map", "0:0:0"), None)
        self.assertIn("stale seer substitute", str(ctx.exception))

    def test_substitute_without_mission_id_keeps_fail_closed(self) -> None:
        from seer_hut_campaign_bind import plan_from_seer_entity

        with self.assertRaises(SeerHutQuestError):
            plan_from_seer_entity(
                self._entity({"missionType": 1, "experienceLevel": 99,
                              "rewardType": 1, "reward": {"rewardType": 1, "experience": 10}}),
                hut_entity_sid="hut_1",
            )

    def test_substitute_reward_kinds_decode(self) -> None:
        from seer_hut_campaign_bind import _reward_from_quest
        from seer_hut_quest import SeerRewardHeroBuffDays, SeerRewardManaRestore

        reward = _reward_from_quest(
            {"reward": {"rewardType": "hero_buff_days", "buffSid": "campaign_morale_buff", "days": 999}},
            context="test",
        )
        self.assertIsInstance(reward, SeerRewardHeroBuffDays)
        self.assertEqual(reward.days, 999)
        reward = _reward_from_quest({"reward": {"rewardType": "mana_restore"}}, context="test")
        self.assertIsInstance(reward, SeerRewardManaRestore)
        with self.assertRaises(SeerHutQuestError):
            _reward_from_quest({"reward": {"rewardType": "bogus_kind"}}, context="test")

    def test_registry_entries_match_decode_contract(self) -> None:
        """Every registry entry decodes against its real port-manifest record."""

        import json

        from campaign_mission import load_batch_manifest
        from seer_hut_campaign_bind import plan_from_seer_entity
        from seer_hut_substitutes import SEER_HUT_SUBSTITUTES

        records: dict[tuple[str, str], dict] = {}
        for manifest in (
            ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json",
            ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json",
            ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
        ):
            batch = load_batch_manifest(manifest)
            for mission in batch.missions:
                for path in mission.artifact_root.rglob("*object_port_manifest.json"):
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    rows = doc.get("records") or doc.get("objects") or []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        if row.get("payloadKind") != "seer_hut" and row.get("templateObjectId") != 83:
                            continue
                        key = row.get("sourceKey")
                        if key:
                            records[(mission.mission_id, key)] = row
                    break

        self.assertTrue(records, "no port-manifest seer records found")
        for mission_id, source_key in sorted(SEER_HUT_SUBSTITUTES):
            record = records.get((mission_id, source_key))
            self.assertIsNotNone(
                record,
                f"substitute ({mission_id}, {source_key}) has no port-manifest record",
            )
            plan = plan_from_seer_entity(
                record,
                hut_entity_sid=f"{mission_id}_hut",
                mission_id=mission_id,
            )
            self.assertIsNotNone(
                plan.substitution_note,
                f"substitute ({mission_id}, {source_key}) did not apply",
            )


if __name__ == "__main__":
    unittest.main()
