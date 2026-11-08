#!/usr/bin/env python3
"""Build the original single-player scenario *The Emberwatch Signal*.

A Castle scout investigates rogue signal fires along a ridge trail, lights
beacon caches, fights through a wolf pass, confronts Marshal Venn, and captures
Emberwatch Keep from the Stronghold renegades.

Proof boundary: generated/installed artifact only until runtime exercised.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

MAP_SID = "h3_emberwatch_signal"
TITLE = "The Emberwatch Signal"
MISSION_ID = "emberwatch_signal"
SCHEMA = "homm3.olden_emberwatch_signal.v1"
POLICY_ID = "ridge_trail_48_capture_keep"

DEFAULT_OUT_ROOT = Path(poc.ROOT) / "artifacts" / "campaign_port_poc" / "emberwatch_signal"

MAP_SIZE = 48
GRASS_TILE = 1
DIRT_TILE = 7

PLAYER_FACTION = "homm3_castle"
PLAYER_HERO = "homm3_castle_hero_1"
ENEMY_FACTION = "homm3_stronghold"
ENEMY_HERO = "homm3_stronghold_hero_2"
ENEMY_KEEP_ENTITY = f"{MISSION_ID}_emberwatch_keep"

PLAYER_CITY_XY = (24, 6)
ENEMY_CITY_XY = (24, 40)
BEACON_WEST_XY = (10, 22)
BEACON_CROSS_XY = (24, 24)
BEACON_EAST_XY = (38, 20)
WOLF_PASS_XY = (24, 16)
MARSHAL_XY = (32, 30)

BASE_OBJECT_ID = 100
PLAYER_CITY_ID = BASE_OBJECT_ID
ENEMY_CITY_ID = BASE_OBJECT_ID + 1

# Core.zip has h3_wolf_rider (squadValue 130), not a standalone h3_wolf logic row.
WOLF_UNIT_SID = "h3_wolf_rider"
WOLF_COUNT = 3
WOLF_SQUAD_VALUE = 130
WOLF_VALUE_BUDGET = WOLF_COUNT * WOLF_SQUAD_VALUE
WOLF_SQUAD_SID = f"{MISSION_ID}_h3_wolf_rider_x{WOLF_COUNT}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def node_at(x: int, y: int) -> int:
    return y * MAP_SIZE + x


def _dialog(dialog_sid: str) -> dict[str, Any]:
    return {"comment": "", "a": "Dialog", "p": [dialog_sid]}


def _give_res(resource: str, amount: int) -> dict[str, Any]:
    return {"comment": "", "a": "GiveRes", "p": [resource, str(amount)]}


def _print(*parts: str) -> dict[str, Any]:
    return {"comment": "", "a": "Print", "p": [str(p) for p in parts]}


def _counter_set(sid: str, value: int | str) -> dict[str, Any]:
    return {"comment": "", "a": "CounterSet", "p": [sid, str(value)]}


def _counter_plus(sid: str, value: int | str = 1) -> dict[str, Any]:
    return {"comment": "", "a": "CounterPlus", "p": [sid, str(value)]}


def _object_interaction_after(entity_sid: str) -> dict[str, Any]:
    return {"comment": "", "c": "ObjectInteractionAfter", "p": [entity_sid], "counter": 1}


def _start_turn_absolute(absolute_day: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import start_turn_condition

    return start_turn_condition(absolute_day, context=MISSION_ID)


def _any_start_turn() -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import any_start_turn_every_day_condition

    return any_start_turn_every_day_condition()


def _ced(sid: str, value: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import counter_equality_in_days_condition

    return counter_equality_in_days_condition(sid, value)


def build_dialog_entries() -> list[dict[str, str]]:
    return [
        {
            "id": f"{MISSION_ID}_briefing",
            "title": TITLE,
            "text": (
                "Scout-Captain Lysa,\n\n"
                "Three signal fires burned last night along the Emberwatch ridge — "
                "the old warning chain the border lords swore was dead. Our riders "
                "found wolf tracks and Stronghold banners near the crossroads.\n\n"
                "Ride north along the dirt trail. Investigate each beacon cache. "
                "Break through the wolf pass if you must. Marshal Venn holds "
                "Emberwatch Keep with renegade ogres; he will not parley.\n\n"
                "Objectives:\n"
                "• Investigate the western, central, and eastern beacons\n"
                "• Clear the wolf pass (optional bounty)\n"
                "• Defeat Marshal Venn and capture Emberwatch Keep\n\n"
                "Allied scouts will drop supplies every seventh day once you march."
            ),
        },
        {
            "id": f"{MISSION_ID}_beacon_west",
            "title": "Western Beacon",
            "text": (
                "A cold fire-pit and a torn Stronghold pennant. Whoever lit this "
                "beacon wanted the ridge watched — not defended. You pocket a "
                "hidden supply cache (+500 gold)."
            ),
        },
        {
            "id": f"{MISSION_ID}_beacon_cross",
            "title": "Ridge Crossroads",
            "text": (
                "The middle beacon overlooks both trails. Chalk marks show wolf "
                "packs driven north toward the pass — deliberate herding. "
                "You claim the scout stash (+8 wood, +3 ore)."
            ),
        },
        {
            "id": f"{MISSION_ID}_beacon_east",
            "title": "Eastern Beacon",
            "text": (
                "A warning scorched into the signal post: \"VENN TAKES KEEP AT DAWN.\" "
                "No supplies here — only urgency. The keep is close."
            ),
        },
        {
            "id": f"{MISSION_ID}_wolf_pass",
            "title": "Wolf Pass",
            "text": (
                "Starved wolf riders block the choke point. Their handler fled "
                "toward the keep. Fight through — the patrol carries a gem "
                "tribute meant for Venn (+2 gemstones on victory)."
            ),
        },
        {
            "id": f"{MISSION_ID}_marshal_taunt",
            "title": "Marshal Venn",
            "titlePosition": 1,
            "text": (
                "\"Castle lapdog. You followed my lanterns straight to your grave. "
                "Emberwatch is mine — and your bones will grease the gate.\""
            ),
            "avatars": [
                {
                    "position": 1,
                    "icon": "icons/dialogue/dialogue_hero_homm3_stronghold_2",
                    "isForeground": "true",
                    "animations": ["zoomIn"],
                    "height": 384,
                    "width": 384,
                }
            ],
        },
        {
            "id": f"{MISSION_ID}_victory",
            "title": "Emberwatch Secured",
            "text": (
                "The keep's banners fall. Marshal Venn's renegades scatter into "
                "the hills. The signal chain is yours — and the ridge sleeps "
                "safely again.\n\n"
                "Victory!"
            ),
        },
    ]


def _subquest_done_trigger(comment: str, condition: dict[str, Any], extra_actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    actions: list[dict[str, Any]] = list(extra_actions or [])
    actions.append({"comment": "", "a": "CurrentSubQuestDone", "p": []})
    return {
        "comment": comment,
        "repeat": False,
        "conditions": [condition],
        "actions": actions,
        "conditionsLogic": "And",
    }


def build_quest_script() -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import timer_counter_row

    counters = [
        {"comment": "", "sid": f"{MISSION_ID}_started", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_beacon_west_done", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_beacon_cross_done", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_beacon_east_done", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_wolf_pass_done", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        timer_counter_row(f"{MISSION_ID}_scout_supply_armed"),
    ]

    quests: list[dict[str, Any]] = [
        {
            "sid": f"{MISSION_ID}_intro",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "opening briefing",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_intro_start",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "day-1 briefing and march gold",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 briefing"),
                                _give_res("gold", 2500),
                                _give_res("wood", 5),
                                _dialog(f"{MISSION_ID}_briefing"),
                                _counter_set(f"{MISSION_ID}_started", 1),
                                _counter_set(f"{MISSION_ID}_scout_supply_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        }
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_scout_supply",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "weekly allied supply drop",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_scout_supply_fire",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "first scout drop day 7",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(7)],
                            "actions": [
                                _give_res("wood", 10),
                                _give_res("ore", 5),
                                _print(f"{MISSION_ID} scout supply day 7"),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "recurring scout drop every 7 days",
                            "repeat": True,
                            "conditions": [_ced(f"{MISSION_ID}_scout_supply_armed", 7)],
                            "actions": [
                                _give_res("wood", 10),
                                _give_res("ore", 5),
                                _counter_set(f"{MISSION_ID}_scout_supply_armed", 0),
                                _print(f"{MISSION_ID} scout supply recurring"),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "daily scout supply timer tick",
                            "repeat": True,
                            "conditions": [_any_start_turn()],
                            "actions": [_counter_plus(f"{MISSION_ID}_scout_supply_armed", 1)],
                            "conditionsLogic": "And",
                        },
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_map_events",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "guarded pass reward",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_map_events_body",
                    "activeOnStart": True,
                    "hidden": True,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "wolf pass pre-battle",
                            "repeat": True,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadInteraction",
                                    "p": [f"{MISSION_ID}_wolf_pass"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [_dialog(f"{MISSION_ID}_wolf_pass")],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "wolf pass victory reward",
                            "repeat": False,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadKill",
                                    "p": [f"{MISSION_ID}_wolf_pass"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [
                                _give_res("gemstones", 2),
                                _counter_set(f"{MISSION_ID}_wolf_pass_done", 1),
                                {"comment": "", "a": "DeleteEntity", "p": [f"{MISSION_ID}_wolf_pass"]},
                            ],
                            "conditionsLogic": "And",
                        },
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_main",
            "hidden": False,
            "main": True,
            "activeOnStart": True,
            "comment": "ridge trail objectives",
            "sharing": "Clone",
            "name": "The Emberwatch Signal",
            "desc": (
                "Investigate the three beacon caches along the ridge, break the wolf pass, "
                "defeat Marshal Venn, and capture Emberwatch Keep."
            ),
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_obj_beacon_west",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Investigate the western beacon",
                    "desc": "Ride to the western signal fire and search the cache.",
                    "comment": "",
                    "triggers": [
                        _subquest_done_trigger(
                            "western beacon visited",
                            _object_interaction_after(f"{MISSION_ID}_beacon_west"),
                            [_give_res("gold", 500), _counter_set(f"{MISSION_ID}_beacon_west_done", 1)],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_beacon_cross",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Recover the crossroads cache",
                    "desc": "Reach the ridge crossroads beacon.",
                    "comment": "",
                    "triggers": [
                        _subquest_done_trigger(
                            "crossroads beacon visited",
                            _object_interaction_after(f"{MISSION_ID}_beacon_cross"),
                            [
                                _give_res("wood", 8),
                                _give_res("ore", 3),
                                _counter_set(f"{MISSION_ID}_beacon_cross_done", 1),
                            ],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_beacon_east",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Read the eastern warning",
                    "desc": "Learn what the eastern beacon reveals about Venn's timetable.",
                    "comment": "",
                    "triggers": [
                        _subquest_done_trigger(
                            "eastern beacon visited",
                            _object_interaction_after(f"{MISSION_ID}_beacon_east"),
                            [_counter_set(f"{MISSION_ID}_beacon_east_done", 1)],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_wolf_pass",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Clear the wolf pass (optional)",
                    "desc": "Defeat the starved wolf pack blocking the choke point.",
                    "comment": "",
                    "triggers": [
                        _subquest_done_trigger(
                            "wolf pass cleared",
                            {
                                "comment": "",
                                "c": "SquadKill",
                                "p": [f"{MISSION_ID}_wolf_pass"],
                                "counter": 1,
                            },
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_capture_keep",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Capture Emberwatch Keep",
                    "desc": "Take the Stronghold outpost from Marshal Venn's renegades.",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "capture enemy keep",
                            "repeat": False,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "ObjectCaptureEntity",
                                    "p": [ENEMY_KEEP_ENTITY],
                                    "counter": 1,
                                }
                            ],
                            "actions": [
                                _dialog(f"{MISSION_ID}_victory"),
                                {"comment": "", "a": "CurrentSubQuestDone", "p": []},
                                {"comment": "", "a": "GameVictory", "p": []},
                            ],
                            "conditionsLogic": "And",
                        }
                    ],
                },
            ],
            "subQuestGroups": [],
        },
    ]

    return {
        "comment": f"{MISSION_ID} ridge trail scenario",
        "aiRolesId": f"{MISSION_ID}_ai",
        "interruptions": [
            {
                "sid": f"{MISSION_ID}_marshal_before",
                "comment": "Marshal Venn taunt before hero engagement",
                "p": [ENEMY_HERO],
                "activeOnStart": True,
                "interruption": "BeforeIamVsHero",
                "actions": [
                    _dialog(f"{MISSION_ID}_marshal_taunt"),
                    {
                        "comment": "",
                        "a": "DisableInterruption",
                        "p": [f"{MISSION_ID}_marshal_before"],
                    },
                ],
            }
        ],
        "counters": counters,
        "quests": quests,
    }


def _build_terrain() -> dict[str, list[int]]:
    total = MAP_SIZE * MAP_SIZE
    tiles = [GRASS_TILE] * total
    for y in range(MAP_SIZE):
        for x in range(MAP_SIZE):
            node = node_at(x, y)
            on_trail = False
            if x == PLAYER_CITY_XY[0] and PLAYER_CITY_XY[1] <= y <= ENEMY_CITY_XY[1]:
                on_trail = True
            if y == BEACON_CROSS_XY[1] and 10 <= x <= 38:
                on_trail = True
            if (x, y) == BEACON_WEST_XY and 10 <= x <= PLAYER_CITY_XY[0]:
                on_trail = True
            if (x, y) == BEACON_EAST_XY and PLAYER_CITY_XY[0] <= x <= 38:
                on_trail = True
            west_branch_x = list(range(10, PLAYER_CITY_XY[0] + 1))
            if y == BEACON_WEST_XY[1] and x in west_branch_x:
                on_trail = True
            east_branch_x = list(range(PLAYER_CITY_XY[0], BEACON_EAST_XY[0] + 1))
            if y == BEACON_EAST_XY[1] and x in east_branch_x:
                on_trail = True
            if on_trail:
                tiles[node] = DIRT_TILE
    return {
        "tilesMap": tiles,
        "waterMap": [0] * total,
        "roadsMap": [0] * total,
        "levelsMap": [0] * total,
        "climbsMap": [0] * total,
        "customAreasPainting": [0] * total,
    }


def _ensure_prop_list(properties: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = properties.get(key)
    if not isinstance(rows, list):
        rows = []
        properties[key] = rows
    return rows


def _append_object_group(
    objects: list[dict[str, Any]],
    *,
    sid: str,
    object_id: int,
    node: int,
    rotation: int = 0,
    level: float = 0.0,
) -> None:
    for group in objects:
        if group.get("sid") != sid or not isinstance(group.get("ids"), list):
            continue
        group["ids"].append(object_id)
        group.setdefault("nodes", []).append(node)
        group.setdefault("rotations", []).append(rotation)
        group.setdefault("levels", []).append(level)
        target_len = len(group["ids"])
        for key, values in list(group.items()):
            if key == "sid" or not isinstance(values, list):
                continue
            while len(values) < target_len:
                if not values:
                    values.append(0.0 if key == "levels" else ("" if key == "v" else 0))
                else:
                    values.append(values[-1])
        return
    objects.append(
        {
            "sid": sid,
            "ids": [object_id],
            "nodes": [node],
            "rotations": [rotation],
            "levels": [level],
        }
    )


def _city_random_squad_row(city_id: int) -> dict[str, Any]:
    return {
        "type": 0,
        "id": city_id,
        "sids": [],
        "requestedValue": 0.0,
        "fraction": "",
        "tier": 0,
        "isMainGuard": False,
        "reactionType": 2,
        "customTopUnit": "",
        "weeklyIncrementBonus": 0.0,
        "diplomacyUnitsCountBonus": 0.0,
        "isEscape": True,
        "isAutobatle": True,
        "isFreeDiplomacy": False,
        "isCampaignFreeDiplomacy": False,
        "isCampaignDiplomacy": False,
        "isIgnoreMultiply": False,
        "obstruction": "",
        "customStacks": 0,
    }


def _append_city(
    *,
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    city_id: int,
    node: int,
    owner: int,
    faction: str,
    hero_sid: str,
    entity_sid: str | None,
    spawn_type: int,
    spawn_hero: bool = True,
) -> None:
    _append_object_group(objects, sid="city-spawner", object_id=city_id, node=node)
    _ensure_prop_list(properties, "propSpawns").append(
        {
            "type": 0,
            "id": city_id,
            "owner": owner,
            "spawnType": spawn_type,
            "spawnPointType": 0 if owner == 1 else 1,
            "isLocked": False,
        }
    )
    _ensure_prop_list(properties, "propCities").append(
        {
            "type": 0,
            "id": city_id,
            "isDefined": True,
            "factionSid": faction,
            "spawnHero": spawn_hero,
            "buildingsConstructionSid": poc.HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID,
            "buildingsBanSid": "default_buildings_ban",
            "buildingsSettingsSid": "default_buildings_settings",
            "customCityName": "Emberwatch Keep" if entity_sid else "",
        }
    )
    if spawn_hero and hero_sid:
        _ensure_prop_list(properties, "propHeroes").append(
            {
                "type": 0,
                "id": city_id,
                "isDefined": True,
                "heroSid": hero_sid,
            }
        )
    _ensure_prop_list(properties, "propGrowthUnits").append(
        {
            "type": 0,
            "id": city_id,
            "isConstantGrowth": True,
            "countGrowth": 1,
        }
    )
    _ensure_prop_list(properties, "propRandomSquads").append(_city_random_squad_row(city_id))
    _ensure_prop_list(properties, "propActivations").append({"type": 0, "id": city_id, "isActive": True})
    if entity_sid:
        _ensure_prop_list(properties, "propEntities").append(
            {"type": 0, "id": city_id, "sid": entity_sid}
        )


def _inject_zone_beacon(
    *,
    objects: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    properties: dict[str, Any],
    key: str,
    xy: tuple[int, int],
    entity_sid: str,
    dialog_sid: str,
    next_object_id: int,
    next_marker_id: int,
    one_shot: bool,
) -> tuple[int, int]:
    marker_id = next_marker_id
    next_marker_id += 1
    x, y = xy
    node = node_at(x, y)
    markers.append({"node": node, "v": "", "sid": "Zone 1x1", "id": marker_id})
    _ensure_prop_list(properties, "propMarkers").append(
        {"type": 1, "id": marker_id, "isDelete": one_shot, "isActivate": True}
    )
    _ensure_prop_list(properties, "propEntities").append({"type": 1, "id": marker_id, "sid": entity_sid})
    _ensure_prop_list(properties, "propActionsBefore").append(
        {
            "type": 1,
            "id": marker_id,
            "repeat": not one_shot,
            "sides": "",
            "actions": [_dialog(dialog_sid)],
        }
    )
    if one_shot:
        _ensure_prop_list(properties, "propActionsAfter").append(
            {
                "type": 1,
                "id": marker_id,
                "repeat": False,
                "sides": "",
                "actions": [{"comment": "", "a": "DeleteEntity", "p": [entity_sid]}],
            }
        )
    deco_id = next_object_id
    next_object_id += 1
    deco_node = node_at(x, y - 1)
    _append_object_group(objects, sid="fx_quest_mark_gold_01", object_id=deco_id, node=deco_node)
    return next_object_id, next_marker_id


def _inject_wolf_pass(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    next_object_id: int,
) -> int:
    guarded_id = next_object_id
    next_object_id += 1
    x, y = WOLF_PASS_XY
    gnode = node_at(x, y)
    entity_sid = f"{MISSION_ID}_wolf_pass"
    _append_object_group(objects, sid="random-squad", object_id=guarded_id, node=gnode)
    _ensure_prop_list(properties, "propEntities").append({"type": 0, "id": guarded_id, "sid": entity_sid})
    _ensure_prop_list(properties, "propRandomSquads").append(
        {
            "type": 0,
            "id": guarded_id,
            "sids": [WOLF_SQUAD_SID],
            "requestedValue": float(WOLF_VALUE_BUDGET),
            "fraction": "",
            "tier": 0,
            "isMainGuard": False,
            "reactionType": 2,
            "customTopUnit": WOLF_UNIT_SID,
            "weeklyIncrementBonus": 0.0,
            "diplomacyUnitsCountBonus": 0.0,
            "isEscape": False,
            "isAutobatle": False,
            "isFreeDiplomacy": False,
            "isCampaignFreeDiplomacy": False,
            "isCampaignDiplomacy": False,
            "isIgnoreMultiply": False,
            "obstruction": "",
            "customStacks": 0,
        }
    )
    _ensure_prop_list(properties, "propSquads").append(
        {
            "type": 0,
            "id": guarded_id,
            "isMainGuard": False,
            "isStartBattleImmediately": False,
            "reactionType": 2,
            "weeklyIncrementBonus": 0.0,
            "unitProps": [{"sid": WOLF_UNIT_SID, "count": WOLF_COUNT}],
        }
    )
    _ensure_prop_list(properties, "propAiIntetations").append({"type": 0, "id": guarded_id, "aiIgnore": True})
    _ensure_prop_list(properties, "propActivations").append({"type": 0, "id": guarded_id, "isActive": True})
    deco_id = next_object_id
    next_object_id += 1
    _append_object_group(objects, sid="fx_quest_mark_gold_01", object_id=deco_id, node=node_at(x, y - 1))
    return next_object_id


def _inject_marshal_hero(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    next_object_id: int,
) -> int:
    hero_id = next_object_id
    next_object_id += 1
    x, y = MARSHAL_XY
    node = node_at(x, y)
    entity_sid = f"{MISSION_ID}_marshal_venn"
    _append_object_group(objects, sid="hero-spawner", object_id=hero_id, node=node)
    _ensure_prop_list(properties, "propEntities").append({"type": 0, "id": hero_id, "sid": entity_sid})
    _ensure_prop_list(properties, "propActivations").append({"type": 0, "id": hero_id, "isActive": True})
    _ensure_prop_list(properties, "propHeroes").append(
        {"type": 0, "id": hero_id, "isDefined": True, "heroSid": ENEMY_HERO}
    )
    _ensure_prop_list(properties, "propSpawns").append(
        {
            "type": 0,
            "id": hero_id,
            "owner": 2,
            "spawnType": 1,
            "spawnPointType": 1,
            "isLocked": False,
        }
    )
    return next_object_id


def _reset_scenario_map(meta: dict[str, Any], map_data: dict[str, Any], map_hash: str) -> None:
    terrain = _build_terrain()
    meta.pop("takenHeroes", None)
    meta.update(
        {
            "title": TITLE,
            "template": "",
            "desc": (
                "A Castle scout rides the Emberwatch ridge to investigate rogue signal fires, "
                "break a wolf pass, defeat Marshal Venn, and capture the Stronghold keep."
            ),
            "displayWinCondition": "Capture Emberwatch Keep from Marshal Venn's renegades.",
            "hashSum": map_hash,
            "nameFromLocalization": False,
            "descFromLocalization": False,
            "isScenario": True,
            "sizeX": MAP_SIZE,
            "sizeZ": MAP_SIZE,
            "spawns": {
                "playersCount": 2,
                "spawns": [
                    {
                        "owner": 1,
                        "spawnType": 0,
                        "playerId": "",
                        "spawnPointType": 0,
                        "isCityDefined": True,
                        "factionSid": PLAYER_FACTION,
                        "isHeroDefined": True,
                        "heroSid": PLAYER_HERO,
                        "colorId": -1,
                        "isAlive": True,
                        "isLocked": False,
                    },
                    {
                        "owner": 2,
                        "spawnType": 1,
                        "playerId": "",
                        "spawnPointType": 1,
                        "isCityDefined": True,
                        "factionSid": ENEMY_FACTION,
                        "isHeroDefined": False,
                        "heroSid": "",
                        "colorId": -1,
                        "isAlive": True,
                        "isLocked": False,
                    },
                ],
                "takenHeroes": [PLAYER_HERO, ENEMY_HERO],
            },
            "campaignInfo": None,
        }
    )
    start = meta.setdefault("startSettings", {})
    if isinstance(start, dict):
        start["DefeatAllEnemiesEnabled"] = True

    player_node = node_at(*PLAYER_CITY_XY)
    enemy_node = node_at(*ENEMY_CITY_XY)

    map_data.clear()
    map_data.update(
        {
            "fileMapName": MAP_SID,
            "mapName": TITLE,
            "mapNameFromLoc": False,
            "mapDesc": meta["desc"],
            "mapDescFromLoc": False,
            "sizeX_": MAP_SIZE,
            "sizeZ_": MAP_SIZE,
            **terrain,
            "haveCustomAreas": True,
            "areasVersion": 1,
            "objects": [],
            "objectsFreeId": BASE_OBJECT_ID + 20,
            "squads": [],
            "squadsFreeId": 0,
            "markers": [],
            "markersFreeId": 1,
            "takenHeroes": [PLAYER_HERO, ENEMY_HERO],
            "keyObjects": [],
            "objectValuesOverrides": [],
            "areas": [
                {
                    "id": 0,
                    "keyObjectId": PLAYER_CITY_ID,
                    "rootNode": player_node,
                    "nodes": list(range(MAP_SIZE * MAP_SIZE)),
                }
            ],
            "rivers": [],
            "views": [
                {
                    "name": "",
                    "minSecX": 0,
                    "minSecZ": 0,
                    "secSizeX": 3,
                    "secSizeZ": 3,
                    "isUnderground": False,
                    "stack": -1,
                }
            ],
            "banInfoData": {
                "bannedMagics": [],
                "bannedItems": [],
                "bannedSkills": [],
                "bannedHeroes": [],
                "bannedUnits": [],
            },
            "objectsProperties": {
                "propSpawns": [],
                "propCities": [],
                "propHeroes": [],
                "propGrowthUnits": [],
                "propRandomSquads": [],
                "propEntities": [],
                "propActionsBefore": [],
                "propActionsAfter": [],
                "propActivations": [],
                "propMarkers": [],
                "propSquads": [],
                "propAiIntetations": [],
            },
        }
    )

    objects = map_data["objects"]
    properties = map_data["objectsProperties"]
    _append_city(
        objects=objects,
        properties=properties,
        city_id=PLAYER_CITY_ID,
        node=player_node,
        owner=1,
        faction=PLAYER_FACTION,
        hero_sid=PLAYER_HERO,
        entity_sid=None,
        spawn_type=0,
    )
    _append_city(
        objects=objects,
        properties=properties,
        city_id=ENEMY_CITY_ID,
        node=enemy_node,
        owner=2,
        faction=ENEMY_FACTION,
        hero_sid="",
        entity_sid=ENEMY_KEEP_ENTITY,
        spawn_type=1,
        spawn_hero=False,
    )


def inject_world_content(map_data: dict[str, Any]) -> dict[str, Any]:
    objects = map_data.setdefault("objects", [])
    markers = map_data.setdefault("markers", [])
    properties = map_data.setdefault("objectsProperties", {})
    next_object_id = int(map_data.get("objectsFreeId") or (BASE_OBJECT_ID + 20))
    next_marker_id = max(int(map_data.get("markersFreeId") or 1), 1)

    beacons = [
        ("beacon_west", BEACON_WEST_XY, f"{MISSION_ID}_beacon_west", f"{MISSION_ID}_beacon_west", True),
        ("beacon_cross", BEACON_CROSS_XY, f"{MISSION_ID}_beacon_cross", f"{MISSION_ID}_beacon_cross", True),
        ("beacon_east", BEACON_EAST_XY, f"{MISSION_ID}_beacon_east", f"{MISSION_ID}_beacon_east", True),
    ]
    report_beacons: dict[str, Any] = {}
    for key, xy, entity_sid, dialog_sid, one_shot in beacons:
        next_object_id, next_marker_id = _inject_zone_beacon(
            objects=objects,
            markers=markers,
            properties=properties,
            key=key,
            xy=xy,
            entity_sid=entity_sid,
            dialog_sid=dialog_sid,
            next_object_id=next_object_id,
            next_marker_id=next_marker_id,
            one_shot=one_shot,
        )
        report_beacons[key] = {"xy": list(xy), "entitySid": entity_sid, "oneShot": one_shot}

    next_object_id = _inject_wolf_pass(objects, properties, next_object_id)
    next_object_id = _inject_marshal_hero(objects, properties, next_object_id)

    map_data["objectsFreeId"] = next_object_id
    map_data["markersFreeId"] = next_marker_id
    return {
        "beacons": report_beacons,
        "wolfPass": {"xy": list(WOLF_PASS_XY), "unit": WOLF_UNIT_SID, "count": WOLF_COUNT},
        "marshal": {"xy": list(MARSHAL_XY), "heroSid": ENEMY_HERO},
        "enemyKeep": {"xy": list(ENEMY_CITY_XY), "entitySid": ENEMY_KEEP_ENTITY},
        "coordinateConvention": "node=y*width+x; Olden +Y = north",
    }


def write_core_overlay(out_root: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    overlay = out_root / "core_overlay"
    squad_dir = overlay / "DB" / "squads" / "squads_custom_maps" / "EmberwatchSignal"
    if squad_dir.is_dir():
        for stale in squad_dir.glob("*.json"):
            stale.unlink()
    english_member = "Lang/english/texts/dialogues.json"
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        english_doc = json.loads(core.read(english_member).decode("utf-8-sig"))
        quickstart = json.loads(core.read("DB/quickStart.json").decode("utf-8-sig"))
    tokens = english_doc.setdefault("tokens", [])
    array_rows = english_doc.setdefault("array", [])
    if not isinstance(tokens, list) or not isinstance(array_rows, list):
        raise ValueError("dialogues.json must use list tokens/array")
    for section in (tokens, array_rows):
        existing = {
            row.get("sid"): row
            for row in section
            if isinstance(row, dict) and isinstance(row.get("sid"), str)
        }
        for entry in entries:
            dialog_sid = entry["id"]
            title_token = f"dialogue_title_{dialog_sid}"
            text_token = f"dialogue_text_{dialog_sid}_0"
            for sid, text in ((title_token, entry["title"]), (text_token, entry["text"])):
                if sid in existing:
                    existing[sid]["text"] = text
                else:
                    section.append({"sid": sid, "text": text})
                    existing[sid] = section[-1]
    dialog_members: list[str] = []
    for entry in entries:
        dialog_sid = entry["id"]
        title_token = f"dialogue_title_{dialog_sid}"
        text_token = f"dialogue_text_{dialog_sid}_0"
        member = f"DB/dialogs/dialogs/custom_maps/EmberwatchSignal/{dialog_sid}.json"
        dialog_members.append(member)
        avatars = entry.get("avatars") if isinstance(entry.get("avatars"), list) else []
        title_position = entry.get("titlePosition")
        if not isinstance(title_position, int):
            title_position = 1 if avatars else 3
        write_json(
            overlay / member,
            {
                "array": [
                    {
                        "id": dialog_sid,
                        "localization": True,
                        "slides": [
                            {
                                "id": "start",
                                "fon": "",
                                "avatars": avatars,
                                "title": {"sid": title_token, "position": title_position},
                                "text": text_token,
                                "next": "ending",
                            },
                            {
                                "id": "ending",
                                "fon": "",
                                "text": "",
                                "invokeOnlyActions": True,
                                "end": True,
                            },
                        ],
                    }
                ]
            },
        )
    write_json(overlay / english_member, english_doc)

    squad_member = f"DB/squads/squads_custom_maps/EmberwatchSignal/{WOLF_SQUAD_SID}.json"
    write_json(
        overlay / squad_member,
        {
            "array": [
                {
                    "id": WOLF_SQUAD_SID,
                    "squad": [],
                    "useOldSquads": False,
                    "rollChance": 0,
                    "canBeMainGuard": True,
                    "baseSquad": {"units": [{"s": WOLF_UNIT_SID, "v": WOLF_VALUE_BUDGET}]},
                    "dynamicSquad": {
                        "requiredValue": WOLF_VALUE_BUDGET,
                        "units": [WOLF_UNIT_SID],
                    },
                    "randomSquad": {
                        "maxValue": WOLF_VALUE_BUDGET,
                        "units": [{"s": WOLF_UNIT_SID, "v": WOLF_VALUE_BUDGET}],
                    },
                    "tier": 0,
                    "fraction": "",
                }
            ]
        },
    )

    scenarios = quickstart.setdefault("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("quickStart.json scenarios must be a list")
    if MAP_SID not in scenarios:
        scenarios.append(MAP_SID)
    write_json(overlay / "DB/quickStart.json", quickstart)

    return {
        "dialogMembers": dialog_members,
        "squadMember": squad_member,
        "langMember": english_member,
        "quickStartMember": "DB/quickStart.json",
        "dialogCount": len(entries),
    }


def build(*, out_root: Path) -> dict[str, Any]:
    if not poc.PLAYABLE_TEMPLATE_MAP.exists():
        raise FileNotFoundError(f"missing schema donor map: {poc.PLAYABLE_TEMPLATE_MAP}")
    container = poc.read_olden_map_container(poc.PLAYABLE_TEMPLATE_MAP)
    chunks = copy.deepcopy(list(container.chunks))
    if len(chunks) < 4:
        raise ValueError(f"schema donor must have 4 chunks; got {len(chunks)}")

    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()
    meta = chunks[0]
    map_data = chunks[1]
    _reset_scenario_map(meta, map_data, map_hash)
    world_report = inject_world_content(map_data)
    dialog_entries = build_dialog_entries()
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    chunks[3] = build_quest_script()

    out_maps = out_root / "maps"
    out_maps.mkdir(parents=True, exist_ok=True)
    out_map = out_maps / f"{MAP_SID}.map"
    out_json = out_maps / f"{MAP_SID}.json"
    poc.write_olden_map_container(
        out_map,
        poc.OldenMapContainer(container.version, container.prefix_suffix, chunks),
        map_hash,
    )
    write_json(
        out_json,
        {"counters": list(chunks[3].get("counters") or []), "quests": []},
    )
    overlay_report = write_core_overlay(out_root, dialog_entries)

    manifest = {
        "schema": SCHEMA,
        "status": "generated_artifact_runtime_unproven",
        "mapSid": MAP_SID,
        "title": TITLE,
        "policyId": POLICY_ID,
        "schemaDonorMap": str(poc.PLAYABLE_TEMPLATE_MAP),
        "output": str(out_map),
        "sidecar": str(out_json),
        "installDestinationPolicy": "maps_root_custom_only",
        "coreOverlayRequired": True,
        "world": world_report,
        "coreOverlay": overlay_report,
        "objectives": {
            "main": "Capture Emberwatch Keep",
            "subQuests": [
                "Investigate the western beacon",
                "Recover the crossroads cache",
                "Read the eastern warning",
                "Clear the wolf pass (optional)",
            ],
            "events": [
                "Day-1 briefing with starter resources",
                "Three beacon visit dialogs with rewards",
                "Weekly allied scout supply (every 7 days from day 7)",
                "Wolf pass guarded encounter with gem bounty",
                "Marshal Venn BeforeIamVsHero taunt",
                "Victory dialog on keep capture",
            ],
        },
        "proofBoundary": "generated artifact + Core overlay; runtime remains user-unvalidated",
        "howToRun": [
            "python experiments/campaign_port_poc/build_emberwatch_signal_scenario.py",
            "python tools/install_emberwatch_signal_scenario.py --repo-root .",
            "Launch Golden Era → QuickStart → The Emberwatch Signal",
        ],
    }
    write_json(out_root / "install_manifest.json", manifest)
    write_json(out_root / "emberwatch_signal_report.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()
    manifest = build(out_root=args.out_root.resolve())
    print(json.dumps({"ok": True, "mapSid": manifest["mapSid"], "output": manifest["output"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
