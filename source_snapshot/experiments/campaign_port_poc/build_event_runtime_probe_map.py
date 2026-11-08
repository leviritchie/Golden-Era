#!/usr/bin/env python3
"""Build a compact Event Runtime Probe map for fast campaign-event iteration.

Emits a fresh 32x32 flat-grass lab (Thirst is used only as a 4-chunk playable
schema donor — objects/terrain/quests are discarded). Stations sit on open tiles
north of the starting city (Olden +Y = north).

Stations (visible):
1. INFO HUB — gold FX, repeating checklist dialog
2. ONE-SHOT — gold FX, dialog once then DeleteEntity
3. AVALANCHE — gold FX, dialog every visit, host stays
4. GUARDED — random-squad with exact h3_pikeman unitProps (campaign SID shape;
   Golden Era already carries Core.zip h3 logics + homm3_bundles art)
5. PERSISTENT — stock prison dwelling, one-shot dialog, no DeleteEntity (Guardhouse stand-in)
6. COLOCATED HERO — enemy hero-spawner with Dialog on the hero (same-cell EVENT+hero);
   adjacent approach must not auto-fight; step onto hero for taunt then fight/leave

Timed (no tiles): day-1 wood/gold, Griffin-like wood, fast crystal, town-shaped weekly wood.
Recurrence uses CounterEqualityInDays (value match) + AnyStartTurn CounterPlus ticks
(decomp: CED is not an N-day interval opcode).

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

MAP_SID = "h3_event_runtime_probe"
TITLE = "Event Runtime Probe"
MISSION_ID = "event_runtime_probe"
SCHEMA = "homm3.olden_event_runtime_probe.v1"
POLICY_ID = "compact_grass_lab_32_north_stations"

DEFAULT_OUT_ROOT = Path(poc.ROOT) / "artifacts" / "campaign_port_poc" / "event_runtime_probe"

MAP_SIZE = 32
# Thirst P1 cities sit on dirt tile 7 with levelsMap=1 at the city node.
CITY_TILE = 7
GROUND_TILE = 7
# Olden +Y = north. City toward the south edge; stations on open grass to the north.
CITY_XY = (16, 8)
STATIONS = {
    "info": {"xy": (14, 16), "label": "INFO HUB"},
    "oneshot": {"xy": (16, 16), "label": "ONE-SHOT"},
    "avalanche": {"xy": (18, 16), "label": "AVALANCHE"},
    "guarded": {"xy": (15, 18), "label": "GUARDED EXACT"},
    "guardhouse": {"xy": (17, 18), "label": "PERSISTENT HOST"},
    # Same-cell EVENT+hero stand-in: dialog on hero-spawner (not Zone). Adjacent tiles
    # must remain safe (heroes ≠ monster ZoC); step onto hero for taunt then fight/leave.
    "colocated_hero": {"xy": (19, 18), "label": "COLOCATED HERO"},
}

# Campaign-exact SID; GE install already has Core.zip h3 logics + pikeman bundles.
# Olden random-squad overlays budget by squadValue (not headcount): 1× pikeman = 80.
GUARD_UNIT_SID = "h3_pikeman"
GUARD_UNIT_SQUAD_VALUE = 80
GUARD_COUNT = 1
GUARD_VALUE_BUDGET = GUARD_COUNT * GUARD_UNIT_SQUAD_VALUE
GUARD_SQUAD_SID = f"{MISSION_ID}_h3_pikeman_x{GUARD_COUNT}"
# Use Thirst-proven faction/hero pair (synthetic "human" city spawn still NullRef'd in czr.vgq).
PLAYER_FACTION = "dungeon"
PLAYER_HERO = "dungeon_hero_6"
CITY_FACTION = "dungeon"
# Avoid reserved/low object ids; city starts here, stations continue after.
BASE_OBJECT_ID = 100
CITY_OBJECT_ID = BASE_OBJECT_ID

GOLD_REWARD = 1500
WOOD_REPEATING = 10
WOOD_TOWN = 14
WOOD_ONESHOT = 5


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


def _start_turn_absolute(absolute_day: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import start_turn_condition

    return start_turn_condition(absolute_day, context=MISSION_ID)


def _any_start_turn() -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import any_start_turn_every_day_condition

    return any_start_turn_every_day_condition()


def _counter_set(sid: str, value: int | str) -> dict[str, Any]:
    return {"comment": "", "a": "CounterSet", "p": [sid, str(value)]}


def _counter_plus(sid: str, value: int | str = 1) -> dict[str, Any]:
    return {"comment": "", "a": "CounterPlus", "p": [sid, str(value)]}


def _ced(sid: str, value: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import counter_equality_in_days_condition

    return counter_equality_in_days_condition(sid, value)


def _object_interaction_after(entity_sid: str) -> dict[str, Any]:
    return {"comment": "", "c": "ObjectInteractionAfter", "p": [entity_sid], "counter": 1}


def build_dialog_entries() -> list[dict[str, str]]:
    return [
        {
            "id": f"{MISSION_ID}_briefing",
            "title": TITLE,
            "text": (
                "EVENT RUNTIME PROBE (32x32 grass lab)\n\n"
                "Olden +Y is north. Gold ? marks are DECORS only — walk ONE TILE "
                "NORTH of each ? onto the invisible Zone to fire the event "
                "(campaign-style type-1 markers).\n\n"
                "1) INFO — zone north of gold ?\n"
                "2) ONE-SHOT — zone north of gold ?; deletes after one visit\n"
                "3) AVALANCHE — zone north of gold ?; re-enter to repeat\n"
                "4) GUARDED — h3_pikeman stack; dialog before fight; 1500 gold on win\n"
                "5) PERSISTENT — visible prison dwelling (east of the pikeman); "
                "one-shot dialog; prison stays (Guardhouse stand-in)\n"
                "6) COLOCATED HERO — enemy hero east of the prison; stand adjacent safely "
                "(no ZoC), then step onto the hero for taunt dialog before fight/leave\n\n"
                "Timed (watch the resource bar / gold):\n"
                "- Day 1 briefing also grants +2500 gold (t_C5-shaped GiveRes smoke).\n"
                "- Day 1: +5 wood and +14 wood (town-shaped).\n"
                "- Day 2: +10 wood (Griffin-like), then every 5 days.\n"
                "- +1 crystal every 2 days after day 1 arm.\n"
                "- Town-shaped +14 wood every 7 days after day 1.\n\n"
                "Late-day (125) proof: live bridge / save edit — do not play 125 turns."
            ),
        },
        {
            "id": f"{MISSION_ID}_oneshot_dialog",
            "title": "One-shot",
            "text": "ONE-SHOT: fires once, then this gold mark should disappear.",
        },
        {
            "id": f"{MISSION_ID}_avalanche_dialog",
            "title": "Avalanche Repeat",
            "text": "AVALANCHE: mark stays. Leave and re-enter to hear this again.",
        },
        {
            "id": f"{MISSION_ID}_guarded_dialog",
            "title": "Guarded Exact",
            "text": "GUARDED: pre-battle dialog. Win once for 1500 gold. Loss/retreat must not grant gold.",
        },
        {
            "id": f"{MISSION_ID}_guardhouse_dialog",
            "title": "Persistent Host",
            "text": (
                "PERSISTENT HOST (prison): one-shot dialog. After this, the prison "
                "must still be here (same rule as Homecoming Guardhouse: do not delete the dwelling)."
            ),
        },
        {
            "id": f"{MISSION_ID}_colocated_hero_dialog",
            "title": "Gurnisson",
            "titlePosition": 1,
            "text": (
                "COLOCATED HERO: Gurnisson taunt on the hero-spawner (portrait test). "
                "Stand adjacent without fighting, then step on for this dialog. After OK you may fight or leave."
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
    ]


def build_quest_script() -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import timer_counter_row

    counters = [
        {"comment": "", "sid": f"{MISSION_ID}_started", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_oneshot_visited", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_avalanche_visits", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_guarded_visited", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_guardhouse_visited", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        {"comment": "", "sid": f"{MISSION_ID}_colocated_hero_visited", "sharing": "Clone", "value": 0, "minValue": -2147483648, "maxValue": 2147483647},
        timer_counter_row(f"{MISSION_ID}_griffin_wood_armed"),
        timer_counter_row(f"{MISSION_ID}_fast_recurrence_armed"),
        timer_counter_row(f"{MISSION_ID}_town_wood_armed"),
    ]

    quests: list[dict[str, Any]] = [
        {
            "sid": f"{MISSION_ID}_intro",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "probe briefing",
            "sharing": "Clone",
            "name": f"{MISSION_ID}_intro",
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
                            "comment": "day-1 briefing + GiveRes smoke (t_C5-shaped)",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 GiveRes gold 2500"),
                                _give_res("gold", 2500),
                                _dialog(f"{MISSION_ID}_briefing"),
                                _counter_set(f"{MISSION_ID}_started", 1),
                            ],
                            "conditionsLogic": "And",
                        }
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_timed_grants",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "timed resource probes",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_timed_grants_fire",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "one-shot +5 wood day 1",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 GiveRes wood {WOOD_ONESHOT}"),
                                _give_res("wood", WOOD_ONESHOT),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "Griffin-like first fire day 2 + arm timer",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(2)],
                            "actions": [
                                _print(f"{MISSION_ID} day2 GiveRes wood {WOOD_REPEATING}"),
                                _give_res("wood", WOOD_REPEATING),
                                _counter_set(f"{MISSION_ID}_griffin_wood_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "Griffin-like every 5 days (CED value==5)",
                            "repeat": True,
                            "conditions": [_ced(f"{MISSION_ID}_griffin_wood_armed", 5)],
                            "actions": [
                                _print(f"{MISSION_ID} CED GiveRes wood {WOOD_REPEATING}"),
                                _give_res("wood", WOOD_REPEATING),
                                _counter_set(f"{MISSION_ID}_griffin_wood_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "Griffin-like daily timer tick",
                            "repeat": True,
                            "conditions": [_any_start_turn()],
                            "actions": [_counter_plus(f"{MISSION_ID}_griffin_wood_armed", 1)],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "fast recurrence first fire day 1 + arm",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 GiveRes crystals 1"),
                                _give_res("crystals", 1),
                                _counter_set(f"{MISSION_ID}_fast_recurrence_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "fast recurrence every 2 days (CED value==2)",
                            "repeat": True,
                            "conditions": [_ced(f"{MISSION_ID}_fast_recurrence_armed", 2)],
                            "actions": [
                                _print(f"{MISSION_ID} CED GiveRes crystals 1"),
                                _give_res("crystals", 1),
                                _counter_set(f"{MISSION_ID}_fast_recurrence_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "fast recurrence daily timer tick",
                            "repeat": True,
                            "conditions": [_any_start_turn()],
                            "actions": [_counter_plus(f"{MISSION_ID}_fast_recurrence_armed", 1)],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "town-shaped weekly wood first fire day 1",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 GiveRes wood {WOOD_TOWN}"),
                                _give_res("wood", WOOD_TOWN),
                                _counter_set(f"{MISSION_ID}_town_wood_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "town-shaped weekly wood every 7 days (CED value==7)",
                            "repeat": True,
                            "conditions": [_ced(f"{MISSION_ID}_town_wood_armed", 7)],
                            "actions": [
                                _print(f"{MISSION_ID} CED GiveRes wood {WOOD_TOWN}"),
                                _give_res("wood", WOOD_TOWN),
                                _counter_set(f"{MISSION_ID}_town_wood_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "town-shaped daily timer tick",
                            "repeat": True,
                            "conditions": [_any_start_turn()],
                            "actions": [_counter_plus(f"{MISSION_ID}_town_wood_armed", 1)],
                            "conditionsLogic": "And",
                        },
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_map_stations",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "map interaction stations",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_map_stations_body",
                    "activeOnStart": True,
                    "hidden": True,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "info hub visit",
                            "repeat": True,
                            "conditions": [_object_interaction_after(f"{MISSION_ID}_info")],
                            "actions": [],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "one-shot visit record",
                            "repeat": False,
                            "conditions": [_object_interaction_after(f"{MISSION_ID}_oneshot")],
                            "actions": [_counter_set(f"{MISSION_ID}_oneshot_visited", 1)],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "avalanche visit count",
                            "repeat": True,
                            "conditions": [_object_interaction_after(f"{MISSION_ID}_avalanche")],
                            "actions": [
                                {
                                    "comment": "",
                                    "a": "CounterPlus",
                                    "p": [f"{MISSION_ID}_avalanche_visits", "1"],
                                }
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "guarded pre-battle dialog",
                            "repeat": True,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadInteraction",
                                    "p": [f"{MISSION_ID}_guarded"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [_dialog(f"{MISSION_ID}_guarded_dialog")],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "guarded win reward",
                            "repeat": False,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadKill",
                                    "p": [f"{MISSION_ID}_guarded"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [
                                _give_res("gold", GOLD_REWARD),
                                _counter_set(f"{MISSION_ID}_guarded_visited", 1),
                                {
                                    "comment": "",
                                    "a": "DeleteEntity",
                                    "p": [f"{MISSION_ID}_guarded"],
                                },
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "persistent host visit",
                            "repeat": False,
                            "conditions": [_object_interaction_after(f"{MISSION_ID}_guardhouse")],
                            "actions": [_counter_set(f"{MISSION_ID}_guardhouse_visited", 1)],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "colocated hero visit (dialog is propActionsBefore on hero)",
                            "repeat": False,
                            "conditions": [_object_interaction_after(f"{MISSION_ID}_colocated_hero")],
                            "actions": [_counter_set(f"{MISSION_ID}_colocated_hero_visited", 1)],
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
            "comment": "probe main checklist",
            "sharing": "Clone",
            "name": "Event Probe Checklist",
            "desc": "Walk the gold marks, the prison, the colocated hero, and the creature north of town; check timed grants.",
            "subQuests": [],
            "subQuestGroups": [],
        },
    ]

    return {
        "comment": f"{MISSION_ID} event runtime probe",
        "aiRolesId": f"{MISSION_ID}_ai",
        "interruptions": [
            {
                "sid": f"{MISSION_ID}_colocated_hero_before",
                "comment": "Gurnisson-style taunt before fighting colocated hero-spawner",
                # Vanilla targets propHeroes.heroSid (not propEntities.sid).
                "p": ["homm3_stronghold_hero_2"],
                "activeOnStart": True,
                "interruption": "BeforeIamVsHero",
                "actions": [
                    {"comment": "", "a": "Dialog", "p": [f"{MISSION_ID}_colocated_hero_dialog"]},
                    {"comment": "", "a": "CounterSet", "p": [f"{MISSION_ID}_colocated_hero_visited", "1"]},
                    {
                        "comment": "",
                        "a": "DisableInterruption",
                        "p": [f"{MISSION_ID}_colocated_hero_before"],
                    },
                ],
            }
        ],
        "counters": counters,
        "quests": quests,
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


def _empty_terrain() -> dict[str, list[int]]:
    total = MAP_SIZE * MAP_SIZE
    # Keep the whole lab flat. An elevated city tile with no climbs stranded the hero
    # (Player.log: map stations never interacted; only intro Dialog fired).
    return {
        "tilesMap": [GROUND_TILE] * total,
        "waterMap": [0] * total,
        "roadsMap": [0] * total,
        "levelsMap": [0] * total,
        "climbsMap": [0] * total,
        "customAreasPainting": [0] * total,
    }


def _city_random_squad_row(city_id: int) -> dict[str, Any]:
    """Empty garrison row matching Thirst city-spawner shape."""
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


def _reset_playable_lab(meta: dict[str, Any], map_data: dict[str, Any], map_hash: str) -> None:
    terrain = _empty_terrain()
    # Drop donor multi-player spawn leftovers; keep startSettings timers/etc.
    meta.pop("takenHeroes", None)
    meta.update(
        {
            "title": TITLE,
            "template": "",
            "desc": (
                "Compact 32x32 event lab. Stations north of town (+Y=north). "
                "Generated artifact only until runtime exercised."
            ),
            "displayWinCondition": "Exercise each station and timed grant.",
            "hashSum": map_hash,
            "nameFromLocalization": False,
            "descFromLocalization": False,
            "isScenario": True,
            "sizeX": MAP_SIZE,
            "sizeZ": MAP_SIZE,
            "spawns": {
                "playersCount": 1,
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
                    }
                ],
                "takenHeroes": [PLAYER_HERO],
            },
            "campaignInfo": None,
        }
    )
    start = meta.setdefault("startSettings", {})
    if isinstance(start, dict):
        # Single-player lab: no enemy sides to defeat.
        start["DefeatAllEnemiesEnabled"] = False

    city_id = CITY_OBJECT_ID
    city_node = node_at(*CITY_XY)

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
            # Hero comes from city spawnHero + propHeroes (Thirst pattern). No separate hero-spawner.
            "objects": [
                {
                    "sid": "city-spawner",
                    "ids": [city_id],
                    "nodes": [city_node],
                    "rotations": [0],
                    "levels": [0.0],
                },
            ],
            "objectsFreeId": BASE_OBJECT_ID + 10,
            "squads": [],
            "squadsFreeId": 0,
            "markers": [],
            "markersFreeId": 1,
            "takenHeroes": [PLAYER_HERO],
            "keyObjects": [],
            "objectValuesOverrides": [],
            "areas": [
                {
                    "id": 0,
                    "keyObjectId": city_id,
                    "rootNode": city_node,
                    "nodes": list(range(MAP_SIZE * MAP_SIZE)),
                }
            ],
            "rivers": [{"sid": "test", "randomSeed": 1, "nodes": []}],
            "views": [
                {
                    "name": "",
                    "minSecX": 0,
                    "minSecZ": 0,
                    "secSizeX": 2,
                    "secSizeZ": 2,
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
                "propSpawns": [
                    {
                        "type": 0,
                        "id": city_id,
                        "owner": 1,
                        "spawnType": 0,
                        "spawnPointType": 0,
                        "isLocked": False,
                    },
                ],
                "propCities": [
                    {
                        "type": 0,
                        "id": city_id,
                        "isDefined": True,
                        "factionSid": CITY_FACTION,
                        "spawnHero": True,
                        "buildingsConstructionSid": "rich_buildings_construction",
                        "buildingsBanSid": "default_buildings_ban",
                        "buildingsSettingsSid": "default_buildings_settings",
                        "customCityName": "",
                    }
                ],
                "propHeroes": [
                    {
                        "type": 0,
                        "id": city_id,
                        "isDefined": True,
                        "heroSid": PLAYER_HERO,
                    },
                ],
                "propGrowthUnits": [
                    {
                        "type": 0,
                        "id": city_id,
                        "isConstantGrowth": True,
                        "countGrowth": 1,
                    }
                ],
                "propRandomSquads": [_city_random_squad_row(city_id)],
                "propEntities": [],
                "propActionsBefore": [],
                "propActionsAfter": [],
                "propActivations": [
                    {"type": 0, "id": city_id, "isActive": True},
                ],
                "propMarkers": [],
                "propSquads": [],
                "propAiIntetations": [],
            },
        }
    )


def inject_stations(map_data: dict[str, Any]) -> dict[str, Any]:
    objects = map_data.setdefault("objects", [])
    markers = map_data.setdefault("markers", [])
    properties = map_data.setdefault("objectsProperties", {})
    next_object_id = int(map_data.get("objectsFreeId") or (BASE_OBJECT_ID + 10))
    # Native Story maps allocate marker ids after area ids (area 0 → markers from 1).
    next_marker_id = max(int(map_data.get("markersFreeId") or 1), 1)
    report: dict[str, Any] = {
        "stations": {},
        "objectIds": {},
        "markerIds": {},
        "coordinateConvention": "node=y*width+x; Olden +Y = north",
        "mapSize": MAP_SIZE,
        "cityXy": list(CITY_XY),
    }

    # Dialog stations: type-1 Zone 1x1 (campaign-proven). Story maps use sides "" for Dialog.
    # Gold FX objects are decors only (Player: ? marks, no Dialog). Guardhouse is a real prison.
    zone_defs = [
        ("info", f"{MISSION_ID}_info", f"{MISSION_ID}_briefing", True, False, "fx_quest_mark_gold_01"),
        ("oneshot", f"{MISSION_ID}_oneshot", f"{MISSION_ID}_oneshot_dialog", False, True, "fx_quest_mark_gold_01"),
        ("avalanche", f"{MISSION_ID}_avalanche", f"{MISSION_ID}_avalanche_dialog", True, False, "fx_quest_mark_gold_01"),
    ]
    for key, entity_sid, dialog_sid, action_repeat, is_delete, deco_sid in zone_defs:
        marker_id = next_marker_id
        next_marker_id += 1
        x, y = STATIONS[key]["xy"]
        node = node_at(x, y)
        markers.append({"node": node, "v": "", "sid": "Zone 1x1", "id": marker_id})
        _ensure_prop_list(properties, "propMarkers").append(
            {"type": 1, "id": marker_id, "isDelete": is_delete, "isActivate": True}
        )
        _ensure_prop_list(properties, "propEntities").append(
            {"type": 1, "id": marker_id, "sid": entity_sid}
        )
        _ensure_prop_list(properties, "propActionsBefore").append(
            {
                "type": 1,
                "id": marker_id,
                "repeat": action_repeat,
                "sides": "",
                "actions": [_dialog(dialog_sid)],
            }
        )
        if is_delete:
            _ensure_prop_list(properties, "propActionsAfter").append(
                {
                    "type": 1,
                    "id": marker_id,
                    "repeat": False,
                    "sides": "",
                    "actions": [{"comment": "", "a": "DeleteEntity", "p": [entity_sid]}],
                }
            )
        # Decorative FX one tile south of the zone so the walkable event cell stays clear.
        deco_id = next_object_id
        next_object_id += 1
        deco_node = node_at(x, y - 1)
        _append_object_group(objects, sid=deco_sid, object_id=deco_id, node=deco_node)
        report["markerIds"][key] = marker_id
        report["objectIds"][f"{key}_deco"] = deco_id
        report["stations"][key] = {
            "kind": "type1_zone_marker",
            "xy": [x, y],
            "node": node,
            "decoXy": [x, y - 1],
            "decoSid": deco_sid,
            "entitySid": entity_sid,
            "dialogSid": dialog_sid,
            "actionRepeat": action_repeat,
            "isDelete": is_delete,
            "sides": "",
            "eventLifetime": "one_shot" if (is_delete or not action_repeat) else "repeating",
            "hostLifetime": "deleted_with_event" if is_delete else "persistent_object",
            "eventLifetimeDetail": "one_shot_no_host_delete" if (key == "guardhouse") else None,
            "plainLanguage": (
                "Walk onto the zone tile (north of the ? deco). "
                + (
                    "Mark/zone deletes after one visit."
                    if is_delete
                    else (
                        "Re-enter to fire again."
                        if action_repeat
                        else "One-shot dialog; zone stays."
                    )
                )
            ),
        }

    # Guardhouse stand-in: stock prison (c_M9 Dialog host). Visible dwelling, one-shot
    # Dialog, no DeleteEntity — same lifetime rule as Homecoming Guardhouse.
    guardhouse_id = next_object_id
    next_object_id += 1
    hx, hy = STATIONS["guardhouse"]["xy"]
    hnode = node_at(hx, hy)
    guardhouse_entity = f"{MISSION_ID}_guardhouse"
    _append_object_group(objects, sid="prison", object_id=guardhouse_id, node=hnode)
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 0, "id": guardhouse_id, "sid": guardhouse_entity}
    )
    _ensure_prop_list(properties, "propActionsBefore").append(
        {
            "type": 0,
            "id": guardhouse_id,
            "repeat": False,
            "sides": "",
            "actions": [_dialog(f"{MISSION_ID}_guardhouse_dialog")],
        }
    )
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": guardhouse_id, "isActive": True}
    )
    report["objectIds"]["guardhouse"] = guardhouse_id
    report["stations"]["guardhouse"] = {
        "kind": "persistent_prison",
        "xy": [hx, hy],
        "node": hnode,
        "objectSid": "prison",
        "entitySid": guardhouse_entity,
        "dialogSid": f"{MISSION_ID}_guardhouse_dialog",
        "actionRepeat": False,
        "isDelete": False,
        "sides": "",
        "eventLifetime": "one_shot",
        "hostLifetime": "persistent_object",
        "eventLifetimeDetail": "one_shot_no_host_delete",
        "plainLanguage": (
            "Walk onto / interact with the prison. One-shot dialog; prison must remain."
        ),
    }

    # Colocated EVENT+hero: Dialog on hero-spawner (not Zone). Never random-squad —
    # heroes must not adjacent-ZoC like wandering monsters.
    colocated_id = next_object_id
    next_object_id += 1
    cx, cy = STATIONS["colocated_hero"]["xy"]
    cnode = node_at(cx, cy)
    colocated_entity = f"{MISSION_ID}_colocated_hero"
    _append_object_group(objects, sid="hero-spawner", object_id=colocated_id, node=cnode)
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 0, "id": colocated_id, "sid": colocated_entity}
    )
    # Dialog is NOT on propActionsBefore — hero-spawner combat skips it.
    # BeforeIamVsHero interruption in the quest script owns the taunt.
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": colocated_id, "isActive": True}
    )
    _ensure_prop_list(properties, "propHeroes").append(
        {
            "type": 0,
            "id": colocated_id,
            "isDefined": True,
            "heroSid": "homm3_stronghold_hero_2",
        }
    )
    _ensure_prop_list(properties, "propSpawns").append(
        {
            "type": 0,
            "id": colocated_id,
            "owner": 2,
            "spawnType": 1,
            "spawnPointType": 1,
            "isLocked": False,
        }
    )
    report["objectIds"]["colocated_hero"] = colocated_id
    report["stations"]["colocated_hero"] = {
        "kind": "colocated_hero_spawner",
        "xy": [cx, cy],
        "node": cnode,
        "objectSid": "hero-spawner",
        "entitySid": colocated_entity,
        "dialogSid": f"{MISSION_ID}_colocated_hero_dialog",
        "actionRepeat": False,
        "isDelete": False,
        "sides": "",
        "eventLifetime": "one_shot",
        "hostLifetime": "colocated_hero_host",
        "eventLifetimeDetail": "one_shot_no_host_delete",
        "engagementContract": "hero_tile_engage_not_adjacent_zoc",
        "dialogDelivery": "BeforeIamVsHero",
        "dialogAvatarIcon": "icons/dialogue/dialogue_hero_homm3_stronghold_2",
        "dialogHeroSid": "homm3_stronghold_hero_2",
        "plainLanguage": (
            "Stand adjacent safely (no auto-fight). Step onto Gurnisson to engage: "
            "BeforeIamVsHero interruption shows taunt with portrait, then fight or leave."
        ),
    }

    # Guard: SpawnsCreator requires propRandomSquads on random-squad objects
    # (Player.log: "Can not find property random squad; objectId: 113"). Keep
    # propSquads.unitProps too for the campaign exact-roster shape under test.
    guarded_id = next_object_id
    next_object_id += 1
    gx, gy = STATIONS["guarded"]["xy"]
    gnode = node_at(gx, gy)
    _append_object_group(objects, sid="random-squad", object_id=guarded_id, node=gnode)
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 0, "id": guarded_id, "sid": f"{MISSION_ID}_guarded"}
    )
    _ensure_prop_list(properties, "propRandomSquads").append(
        {
            "type": 0,
            "id": guarded_id,
            "sids": [GUARD_SQUAD_SID],
            "requestedValue": float(GUARD_VALUE_BUDGET),
            "fraction": "",
            "tier": 0,
            "isMainGuard": False,
            "reactionType": 2,
            "customTopUnit": GUARD_UNIT_SID,
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
            "unitProps": [{"sid": GUARD_UNIT_SID, "count": GUARD_COUNT}],
        }
    )
    _ensure_prop_list(properties, "propAiIntetations").append(
        {"type": 0, "id": guarded_id, "aiIgnore": True}
    )
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": guarded_id, "isActive": True}
    )
    report["objectIds"]["guarded"] = guarded_id
    report["stations"]["guarded"] = {
        "kind": "exact_squad",
        "xy": [gx, gy],
        "node": gnode,
        "entitySid": f"{MISSION_ID}_guarded",
        "squadOverlaySid": GUARD_SQUAD_SID,
        "unitProps": [{"sid": GUARD_UNIT_SID, "count": GUARD_COUNT}],
        "unitNote": (
            "propRandomSquads.sids required by SpawnsCreator; propSquads.unitProps kept "
            "for campaign exact-roster shape"
        ),
        "goldOnKill": GOLD_REWARD,
        "aiIgnore": True,
    }

    map_data["objectsFreeId"] = next_object_id
    map_data["markersFreeId"] = next_marker_id
    return report


def write_core_overlay(out_root: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    overlay = out_root / "core_overlay"
    squad_dir = overlay / "DB" / "squads" / "squads_custom_maps" / "EventRuntimeProbe"
    if squad_dir.is_dir():
        for stale in squad_dir.glob("*.json"):
            stale.unlink()
    english_member = "Lang/english/texts/dialogues.json"
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        english_doc = json.loads(core.read(english_member).decode("utf-8-sig"))
        quickstart = json.loads(core.read("DB/quickStart.json").decode("utf-8-sig"))
    tokens = english_doc.setdefault("tokens", [])
    if not isinstance(tokens, list):
        raise ValueError("dialogues.json tokens must be a list")
    array_rows = english_doc.setdefault("array", [])
    if not isinstance(array_rows, list):
        raise ValueError("dialogues.json array must be a list")
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
        member = f"DB/dialogs/dialogs/custom_maps/EventRuntimeProbe/{dialog_sid}.json"
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

    # Shape matches shipped homecoming_* squad overlays (fraction "", tier 0, v = value budget).
    # Core.zip configs load once at game startup — reinstall requires a full relaunch.
    squad_member = f"DB/squads/squads_custom_maps/EventRuntimeProbe/{GUARD_SQUAD_SID}.json"
    write_json(
        overlay / squad_member,
        {
            "array": [
                {
                    "id": GUARD_SQUAD_SID,
                    "squad": [],
                    "useOldSquads": False,
                    "rollChance": 0,
                    "canBeMainGuard": True,
                    "baseSquad": {
                        "units": [{"s": GUARD_UNIT_SID, "v": GUARD_VALUE_BUDGET}]
                    },
                    "dynamicSquad": {
                        "requiredValue": GUARD_VALUE_BUDGET,
                        "units": [GUARD_UNIT_SID],
                    },
                    "randomSquad": {
                        "maxValue": GUARD_VALUE_BUDGET,
                        "units": [{"s": GUARD_UNIT_SID, "v": GUARD_VALUE_BUDGET}],
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
        raise FileNotFoundError(
            f"missing schema donor map (Thirst playable container): {poc.PLAYABLE_TEMPLATE_MAP}"
        )
    container = poc.read_olden_map_container(poc.PLAYABLE_TEMPLATE_MAP)
    chunks = copy.deepcopy(list(container.chunks))
    if len(chunks) < 4:
        raise ValueError(f"schema donor must have 4 chunks; got {len(chunks)}")

    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()
    meta = chunks[0]
    map_data = chunks[1]
    _reset_playable_lab(meta, map_data, map_hash)
    station_report = inject_stations(map_data)
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
        "schemaDonorRole": "4-chunk playable container only; terrain/objects/quests discarded",
        "output": str(out_map),
        "sidecar": str(out_json),
        "installDestinationPolicy": "maps_root_custom_only",
        "coreOverlayRequired": True,
        "stations": station_report,
        "coreOverlay": overlay_report,
        "acceptanceMatrix": {
            "briefingDay1": f"{MISSION_ID}_briefing",
            "oneShotGiveResWood": WOOD_ONESHOT,
            "griffinLikeWood": {"firstDay": 2, "intervalDays": 5, "amount": WOOD_REPEATING},
            "fastRecurrenceCrystal": {"intervalDays": 2, "amount": 1},
            "townShapedWeeklyWood": {"firstDay": 1, "intervalDays": 7, "amount": WOOD_TOWN},
            "avalancheRepeat": True,
            "guardedExact": {
                "unit": GUARD_UNIT_SID,
                "count": GUARD_COUNT,
                "gold": GOLD_REWARD,
                "note": (
                    "campaign-exact h3_pikeman; random-squad overlay uses squadValue budget "
                    f"{GUARD_VALUE_BUDGET}; Core.zip squad config requires full game relaunch"
                ),
            },
            "persistentHostOneShot": True,
            "lateDayNote": "Use live bridge / save edit for day-125 style checks; do not play 125 turns.",
        },
        "proofBoundary": (
            "generated artifact + Core overlay members; installed/startup/runtime event "
            "behavior remains user-unvalidated"
        ),
        "howToRun": [
            "python experiments/campaign_port_poc/build_event_runtime_probe_map.py",
            "python tools/install_event_runtime_probe_map.py --repo-root .",
            "Launch Golden Era → QuickStart → Event Runtime Probe",
            "Walk north (+Y) from town to the gold marks, the prison, and the creature stack",
        ],
    }
    write_json(out_root / "install_manifest.json", manifest)
    write_json(out_root / "event_runtime_probe_report.json", manifest)
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
