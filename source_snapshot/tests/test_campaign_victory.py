#!/usr/bin/env python3
"""Unit tests for header-derived campaign victory compilation."""

from __future__ import annotations

import unittest

import campaign_victory as cv


class CampaignVictoryPlanTests(unittest.TestCase):
    def test_artifact_item_own_side(self) -> None:
        plan = cv.plan_campaign_victory(
            mission_id="seeking_armageddon",
            header={
                "victory": {
                    "name": "ARTIFACT",
                    "allowNormalVictory": True,
                    "special": {"artifactId": 35},
                },
                "loss": {"name": "LOSSSTANDARD", "special": {}},
                "players": [{"index": 0, "playable": True, "canHuman": True}],
            },
            entities=[],
            creature_to_unit=lambda _cid: None,
        )
        self.assertTrue(plan.defeat_all_enemies_enabled)
        self.assertEqual(len(plan.win_triggers), 1)
        cond = plan.win_triggers[0]["conditions"][0]
        self.assertEqual(cond["c"], "ItemOwnSide")
        self.assertEqual(cond["p"][0], "homm3_artifact_035_sword_of_judgement")

    def test_vial_alias_131(self) -> None:
        plan = cv.plan_campaign_victory(
            mission_id="a_thief_in_the_night",
            header={
                "victory": {
                    "name": "ARTIFACT",
                    "allowNormalVictory": True,
                    "special": {"artifactId": 131},
                },
                "loss": {"name": "LOSSSTANDARD", "special": {}},
                "players": [],
            },
            entities=[],
            creature_to_unit=lambda _cid: None,
        )
        self.assertEqual(
            plan.win_triggers[0]["conditions"][0]["p"][0],
            "homm3_artifact_096_vial_of_lifeblood",
        )

    def test_capture_city_nearest_town(self) -> None:
        entities = [
            {
                "sourceKey": "1:35:35",
                "sourceIndex": 1454,
                "payloadKind": "town",
                "category": "town",
            }
        ]
        plan = cv.plan_campaign_victory(
            mission_id="homecoming",
            header={
                "victory": {
                    "name": "CAPTURECITY",
                    "allowNormalVictory": False,
                    "special": {"position": {"x": 33, "y": 35, "z": 1}},
                },
                "loss": {"name": "LOSSSTANDARD", "special": {}},
                "players": [],
            },
            entities=entities,
            creature_to_unit=lambda _cid: None,
        )
        self.assertFalse(plan.defeat_all_enemies_enabled)
        self.assertEqual(plan.prop_entity_bindings[0].object_id, 1454)
        self.assertEqual(plan.win_triggers[0]["conditions"][0]["c"], "ObjectCaptureEntity")

    def test_timeexpires_loss(self) -> None:
        plan = cv.plan_campaign_victory(
            mission_id="crystal_dragons",
            header={
                "victory": {
                    "name": "BEATMONSTER",
                    "allowNormalVictory": False,
                    "special": {"position": {"x": 1, "y": 1, "z": 0}},
                },
                "loss": {"name": "TIMEEXPIRES", "special": {"days": 56}},
                "players": [],
            },
            entities=[
                {
                    "sourceKey": "0:1:1",
                    "sourceIndex": 9,
                    "payloadKind": "monster",
                    "category": "creature",
                }
            ],
            creature_to_unit=lambda _cid: None,
        )
        self.assertEqual(len(plan.loss_triggers), 1)
        self.assertEqual(plan.loss_triggers[0]["conditions"][0]["c"], "StartTurn")
        self.assertEqual(plan.loss_triggers[0]["actions"][0]["a"], "GameLose")

    def test_gather_resource(self) -> None:
        plan = cv.plan_campaign_victory(
            mission_id="to_build_a_tunnel",
            header={
                "victory": {
                    "name": "GATHERRESOURCE",
                    "allowNormalVictory": False,
                    "special": {"resourceId": 6, "count": 100000},
                },
                "loss": {"name": "LOSSSTANDARD", "special": {}},
                "players": [],
            },
            entities=[],
            creature_to_unit=lambda _cid: None,
        )
        cond = plan.win_triggers[0]["conditions"][0]
        self.assertEqual(cond["c"], "ResCounter")
        self.assertEqual(cond["p"], ["gold", ">=", "100000"])


if __name__ == "__main__":
    unittest.main()
