#!/usr/bin/env python3
"""Build the original single-player scenario *The Brine Bell*.

A Tower mage rides salt flats to recover three stolen pieces of the harbor
warning bell, fights a pirate landing party, confronts Captain Rime, and
captures Brinehold from Cove raiders.

Map patterns follow the Event Runtime Probe lab (Thirst 4-chunk donor,
type-1 Zone 1x1 markers, random-squad guards, BeforeIamVsHero taunts).
Victory uses ObjectCaptureEntity → GameVictory on the enemy city entity.

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

MAP_SID = "h3_brine_bell"
TITLE = "The Brine Bell"
MISSION_ID = "brine_bell"
SCHEMA = "homm3.olden_brine_bell.v1"
POLICY_ID = "salt_flats_32_capture_brinehold"

DEFAULT_OUT_ROOT = Path(poc.ROOT) / "artifacts" / "campaign_port_poc" / "brine_bell"

# Sector size is 16 tiles. Views use size//16 — non-multiples (e.g. 40) claim a
# larger view than the tilesMap and fail Map.Init / Loader.
VIEW_SECTOR_SIZE = 16
MAP_SIZE = 32
VIEW_SEC_SIZE = MAP_SIZE // VIEW_SECTOR_SIZE
SAND_TILE = 2  # Core tiles.json: id 2 = Sand (id 3 is Deathland)
DIRT_TILE = 7

PLAYER_FACTION = "homm3_tower"
PLAYER_HERO = "homm3_tower_hero_1"
ENEMY_FACTION = "homm3_cove"
# City garrison and field captain must be distinct — duplicate heroSid in
# propHeroes / takenHeroes breaks SpawnsCreator on load.
ENEMY_CITY_HERO = "homm3_cove_hero_1"
ENEMY_HERO = "homm3_cove_hero_3"
ENEMY_KEEP_ENTITY = f"{MISSION_ID}_capture_brinehold"
ENEMY_KEEP_NAME = "Brinehold"

# Olden +Y = north. Player south; keep north; bell pieces on salt-flat trails.
PLAYER_CITY_XY = (16, 4)
ENEMY_CITY_XY = (16, 28)
CLAPPER_XY = (6, 12)
ROPE_XY = (26, 12)
CROWN_XY = (16, 18)
PIRATE_LANDING_XY = (16, 10)
CAPTAIN_XY = (22, 22)

BASE_OBJECT_ID = 100
PLAYER_CITY_ID = BASE_OBJECT_ID
ENEMY_CITY_ID = BASE_OBJECT_ID + 1

# Core.zip h3_pirate squadValue = 299; budget by headcount × squadValue.
PIRATE_UNIT_SID = "h3_pirate"
PIRATE_COUNT = 3
PIRATE_SQUAD_VALUE = 299
PIRATE_VALUE_BUDGET = PIRATE_COUNT * PIRATE_SQUAD_VALUE
PIRATE_SQUAD_SID = f"{MISSION_ID}_h3_pirate_x{PIRATE_COUNT}"

START_GOLD = 3000
START_WOOD = 8
CLAPPER_GOLD = 800
ROPE_WOOD = 10
ROPE_ORE = 4
PIRATE_GEM_REWARD = 3
HARBOR_SUBSIDY_GOLD = 1000
HARBOR_SUBSIDY_INTERVAL = 5


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


def build_dialog_entries() -> list[dict[str, Any]]:
    return [
        {
            "id": f"{MISSION_ID}_briefing",
            "title": TITLE,
            "text": (
                "Archmage Piquedram,\n\n"
                "Last night someone cut the Brine Bell from its tower. Without that "
                "warning chime, fog ships can slip into the harbor unseen. The "
                "thieves smashed the bell into three pieces and scattered them "
                "across the salt flats as bait.\n\n"
                "Recover the clapper, the rope, and the bronze crown. Watch for a "
                "pirate landing on the north road. Captain Rime of the Cove holds "
                "Brinehold — take the keep, and the bell can ring again.\n\n"
                "Objectives:\n"
                "• Recover the three bell fragments\n"
                "• Clear the pirate landing (optional bounty)\n"
                "• Defeat Captain Rime and capture Brinehold\n\n"
                "The harbor council will send gold every five days while you march."
            ),
        },
        {
            "id": f"{MISSION_ID}_clapper",
            "title": "The Clapper",
            "text": (
                "Buried under salt crust: the iron clapper, still warm from the "
                "forge. A Cove sailor's knife marks the pit. You pocket a "
                "hidden purse (+800 gold)."
            ),
        },
        {
            "id": f"{MISSION_ID}_rope",
            "title": "The Rope",
            "text": (
                "The bell-rope lies coiled in a crab trap. Salt-stained charts "
                "nearby sketch a path toward Brinehold. You claim the work "
                "crew's stash (+10 wood, +4 ore)."
            ),
        },
        {
            "id": f"{MISSION_ID}_crown",
            "title": "The Bronze Crown",
            "text": (
                "The bronze lip of the bell sits upright like a basin, catching "
                "rain. Scratched inside: \"RIME RINGS LAST.\" No loot — only the "
                "last piece you need, and a clear warning."
            ),
        },
        {
            "id": f"{MISSION_ID}_pirate_landing",
            "title": "Pirate Landing",
            "text": (
                "Three pirates guard a beached skiff. They laugh when they see "
                "a Tower robe — then draw cutlasses. Win the fight for the "
                "gem tribute meant for Rime (+3 gemstones)."
            ),
        },
        {
            "id": f"{MISSION_ID}_captain_taunt",
            "title": "Captain Rime",
            "titlePosition": 1,
            "text": (
                "\"Wizard. You followed my breadcrumbs across the flats. "
                "The Brine Bell stays silent, and Brinehold stays mine. "
                "Come take it — if your bones float.\""
            ),
            "avatars": [
                {
                    "position": 1,
                    "icon": "icons/dialogue/dialogue_hero_homm3_cove_3",
                    "isForeground": "true",
                    "animations": ["zoomIn"],
                    "height": 384,
                    "width": 384,
                }
            ],
        },
        {
            "id": f"{MISSION_ID}_victory",
            "title": "Brinehold Secured",
            "text": (
                "Cove banners fall from the harbor tower. With clapper, rope, "
                "and crown reunited, the Brine Bell can be remounted. Fog ships "
                "will find no quiet entry tonight.\n\n"
                "Victory!"
            ),
        },
        {
            "id": f"{MISSION_ID}_harbor_subsidy",
            "title": "Harbor Council",
            "text": (
                "A courier from the harbor council arrives with emergency "
                f"funds (+{HARBOR_SUBSIDY_GOLD} gold). \"Keep marching,\" he says. "
                "\"The fog does not wait.\""
            ),
        },
    ]


def _subquest_done(
    comment: str,
    condition: dict[str, Any],
    extra_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        {
            "comment": "",
            "sid": f"{MISSION_ID}_started",
            "sharing": "Clone",
            "value": 0,
            "minValue": -2147483648,
            "maxValue": 2147483647,
        },
        {
            "comment": "",
            "sid": f"{MISSION_ID}_clapper_done",
            "sharing": "Clone",
            "value": 0,
            "minValue": -2147483648,
            "maxValue": 2147483647,
        },
        {
            "comment": "",
            "sid": f"{MISSION_ID}_rope_done",
            "sharing": "Clone",
            "value": 0,
            "minValue": -2147483648,
            "maxValue": 2147483647,
        },
        {
            "comment": "",
            "sid": f"{MISSION_ID}_crown_done",
            "sharing": "Clone",
            "value": 0,
            "minValue": -2147483648,
            "maxValue": 2147483647,
        },
        {
            "comment": "",
            "sid": f"{MISSION_ID}_pirate_landing_done",
            "sharing": "Clone",
            "value": 0,
            "minValue": -2147483648,
            "maxValue": 2147483647,
        },
        timer_counter_row(f"{MISSION_ID}_harbor_subsidy_armed"),
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
                            "comment": "day-1 briefing and march funds",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(1)],
                            "actions": [
                                _print(f"{MISSION_ID} day1 briefing"),
                                _give_res("gold", START_GOLD),
                                _give_res("wood", START_WOOD),
                                _dialog(f"{MISSION_ID}_briefing"),
                                _counter_set(f"{MISSION_ID}_started", 1),
                                _counter_set(f"{MISSION_ID}_harbor_subsidy_armed", 0),
                            ],
                            "conditionsLogic": "And",
                        }
                    ],
                }
            ],
            "subQuestGroups": [],
        },
        {
            "sid": f"{MISSION_ID}_harbor_subsidy",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": "timed harbor council gold",
            "sharing": "Clone",
            "name": "",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_harbor_subsidy_fire",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "first subsidy day 5",
                            "repeat": False,
                            "conditions": [_start_turn_absolute(HARBOR_SUBSIDY_INTERVAL)],
                            "actions": [
                                _give_res("gold", HARBOR_SUBSIDY_GOLD),
                                _dialog(f"{MISSION_ID}_harbor_subsidy"),
                                _print(f"{MISSION_ID} harbor subsidy day {HARBOR_SUBSIDY_INTERVAL}"),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": f"recurring subsidy every {HARBOR_SUBSIDY_INTERVAL} days",
                            "repeat": True,
                            "conditions": [
                                _ced(f"{MISSION_ID}_harbor_subsidy_armed", HARBOR_SUBSIDY_INTERVAL)
                            ],
                            "actions": [
                                _give_res("gold", HARBOR_SUBSIDY_GOLD),
                                _dialog(f"{MISSION_ID}_harbor_subsidy"),
                                _counter_set(f"{MISSION_ID}_harbor_subsidy_armed", 0),
                                _print(f"{MISSION_ID} harbor subsidy recurring"),
                            ],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "daily harbor subsidy timer tick",
                            "repeat": True,
                            "conditions": [_any_start_turn()],
                            "actions": [_counter_plus(f"{MISSION_ID}_harbor_subsidy_armed", 1)],
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
            "comment": "pirate landing combat reward",
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
                            "comment": "pirate landing pre-battle dialog",
                            "repeat": True,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadInteraction",
                                    "p": [f"{MISSION_ID}_pirate_landing"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [_dialog(f"{MISSION_ID}_pirate_landing")],
                            "conditionsLogic": "And",
                        },
                        {
                            "comment": "pirate landing kill reward",
                            "repeat": False,
                            "conditions": [
                                {
                                    "comment": "",
                                    "c": "SquadKill",
                                    "p": [f"{MISSION_ID}_pirate_landing"],
                                    "counter": 1,
                                }
                            ],
                            "actions": [
                                _give_res("gemstones", PIRATE_GEM_REWARD),
                                _counter_set(f"{MISSION_ID}_pirate_landing_done", 1),
                                {
                                    "comment": "",
                                    "a": "DeleteEntity",
                                    "p": [f"{MISSION_ID}_pirate_landing"],
                                },
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
            "comment": "salt flats objectives",
            "sharing": "Clone",
            "name": TITLE,
            "desc": (
                "Recover the three Brine Bell fragments, clear the pirate landing, "
                "defeat Captain Rime, and capture Brinehold."
            ),
            "subQuests": [
                {
                    "sid": f"{MISSION_ID}_obj_clapper",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Recover the clapper",
                    "desc": "Find the iron clapper on the western salt flats.",
                    "comment": "",
                    "triggers": [
                        _subquest_done(
                            "clapper recovered",
                            _object_interaction_after(f"{MISSION_ID}_clapper"),
                            [
                                _give_res("gold", CLAPPER_GOLD),
                                _counter_set(f"{MISSION_ID}_clapper_done", 1),
                            ],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_rope",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Recover the rope",
                    "desc": "Find the bell-rope on the eastern flats.",
                    "comment": "",
                    "triggers": [
                        _subquest_done(
                            "rope recovered",
                            _object_interaction_after(f"{MISSION_ID}_rope"),
                            [
                                _give_res("wood", ROPE_WOOD),
                                _give_res("ore", ROPE_ORE),
                                _counter_set(f"{MISSION_ID}_rope_done", 1),
                            ],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_crown",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Recover the bronze crown",
                    "desc": "Find the bronze lip of the bell on the north road.",
                    "comment": "",
                    "triggers": [
                        _subquest_done(
                            "crown recovered",
                            _object_interaction_after(f"{MISSION_ID}_crown"),
                            [_counter_set(f"{MISSION_ID}_crown_done", 1)],
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_pirate_landing",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Clear the pirate landing (optional)",
                    "desc": "Defeat the Cove landing party on the trail.",
                    "comment": "",
                    "triggers": [
                        _subquest_done(
                            "pirate landing cleared",
                            {
                                "comment": "",
                                "c": "SquadKill",
                                "p": [f"{MISSION_ID}_pirate_landing"],
                                "counter": 1,
                            },
                        )
                    ],
                },
                {
                    "sid": f"{MISSION_ID}_obj_capture_keep",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "Capture Brinehold",
                    "desc": "Take the Cove harbor keep from Captain Rime.",
                    "comment": "",
                    "triggers": [
                        {
                            "comment": "capture Brinehold",
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
        "comment": f"{MISSION_ID} salt flats scenario",
        "aiRolesId": f"{MISSION_ID}_ai",
        "interruptions": [
            {
                "sid": f"{MISSION_ID}_captain_before",
                "comment": "Captain Rime taunt before hero engagement",
                "p": [ENEMY_HERO],
                "activeOnStart": True,
                "interruption": "BeforeIamVsHero",
                "actions": [
                    _dialog(f"{MISSION_ID}_captain_taunt"),
                    {
                        "comment": "",
                        "a": "DisableInterruption",
                        "p": [f"{MISSION_ID}_captain_before"],
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


def _build_terrain() -> dict[str, list[int]]:
    """Flat sand flats with dirt trails — all levels/climbs 0 so the hero is never stranded."""

    if MAP_SIZE % VIEW_SECTOR_SIZE != 0:
        raise ValueError(
            f"MAP_SIZE {MAP_SIZE} must be a multiple of view sector size {VIEW_SECTOR_SIZE}"
        )

    total = MAP_SIZE * MAP_SIZE
    tiles = [SAND_TILE] * total
    trail_nodes: set[int] = set()

    # North-south spine from player town to Brinehold.
    for y in range(PLAYER_CITY_XY[1], ENEMY_CITY_XY[1] + 1):
        for dx in (-1, 0, 1):
            x = PLAYER_CITY_XY[0] + dx
            if 0 <= x < MAP_SIZE:
                trail_nodes.add(node_at(x, y))

    # East-west spur to clapper and rope.
    for x in range(CLAPPER_XY[0], ROPE_XY[0] + 1):
        for dy in (-1, 0):
            y = CLAPPER_XY[1] + dy
            if 0 <= y < MAP_SIZE:
                trail_nodes.add(node_at(x, y))

    # Spur toward Captain Rime.
    for x in range(min(PLAYER_CITY_XY[0], CAPTAIN_XY[0]), max(PLAYER_CITY_XY[0], CAPTAIN_XY[0]) + 1):
        trail_nodes.add(node_at(x, CAPTAIN_XY[1]))
    for y in range(min(CROWN_XY[1], CAPTAIN_XY[1]), max(CROWN_XY[1], CAPTAIN_XY[1]) + 1):
        trail_nodes.add(node_at(CAPTAIN_XY[0], y))

    for node in trail_nodes:
        if 0 <= node < total:
            tiles[node] = DIRT_TILE

    return {
        "tilesMap": tiles,
        "waterMap": [0] * total,
        "roadsMap": [0] * total,
        "levelsMap": [0] * total,
        "climbsMap": [0] * total,
        "customAreasPainting": [0] * total,
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
    city_name: str,
    spawn_type: int,
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
            "spawnHero": True,
            "buildingsConstructionSid": poc.HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID,
            "buildingsBanSid": "default_buildings_ban",
            "buildingsSettingsSid": "default_buildings_settings",
            "customCityName": city_name,
        }
    )
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
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": city_id, "isActive": True}
    )
    if entity_sid:
        _ensure_prop_list(properties, "propEntities").append(
            {"type": 0, "id": city_id, "sid": entity_sid}
        )


def _inject_zone_cache(
    *,
    objects: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    properties: dict[str, Any],
    xy: tuple[int, int],
    entity_sid: str,
    dialog_sid: str,
    next_object_id: int,
    next_marker_id: int,
) -> tuple[int, int]:
    """Campaign-proven type-1 Zone 1x1 + gold FX decor one tile south."""

    marker_id = next_marker_id
    next_marker_id += 1
    x, y = xy
    node = node_at(x, y)
    markers.append({"node": node, "v": "", "sid": "Zone 1x1", "id": marker_id})
    _ensure_prop_list(properties, "propMarkers").append(
        {"type": 1, "id": marker_id, "isDelete": True, "isActivate": True}
    )
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 1, "id": marker_id, "sid": entity_sid}
    )
    _ensure_prop_list(properties, "propActionsBefore").append(
        {
            "type": 1,
            "id": marker_id,
            "repeat": False,
            "sides": "",
            "actions": [_dialog(dialog_sid)],
        }
    )
    deco_id = next_object_id
    next_object_id += 1
    # Decor south of zone so the walkable event cell stays clear (probe pattern).
    deco_y = max(0, y - 1)
    _append_object_group(
        objects, sid="fx_quest_mark_gold_01", object_id=deco_id, node=node_at(x, deco_y)
    )
    return next_object_id, next_marker_id


def _inject_pirate_landing(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    next_object_id: int,
) -> int:
    guarded_id = next_object_id
    next_object_id += 1
    x, y = PIRATE_LANDING_XY
    gnode = node_at(x, y)
    entity_sid = f"{MISSION_ID}_pirate_landing"
    _append_object_group(objects, sid="random-squad", object_id=guarded_id, node=gnode)
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 0, "id": guarded_id, "sid": entity_sid}
    )
    # SpawnsCreator requires propRandomSquads (probe: "Can not find property random squad").
    _ensure_prop_list(properties, "propRandomSquads").append(
        {
            "type": 0,
            "id": guarded_id,
            "sids": [PIRATE_SQUAD_SID],
            "requestedValue": float(PIRATE_VALUE_BUDGET),
            "fraction": "",
            "tier": 0,
            "isMainGuard": False,
            "reactionType": 2,
            "customTopUnit": PIRATE_UNIT_SID,
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
            "unitProps": [{"sid": PIRATE_UNIT_SID, "count": PIRATE_COUNT}],
        }
    )
    _ensure_prop_list(properties, "propAiIntetations").append(
        {"type": 0, "id": guarded_id, "aiIgnore": True}
    )
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": guarded_id, "isActive": True}
    )
    deco_id = next_object_id
    next_object_id += 1
    _append_object_group(
        objects,
        sid="fx_quest_mark_gold_01",
        object_id=deco_id,
        node=node_at(x, max(0, y - 1)),
    )
    return next_object_id


def _inject_captain_hero(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    next_object_id: int,
) -> int:
    hero_id = next_object_id
    next_object_id += 1
    x, y = CAPTAIN_XY
    node = node_at(x, y)
    entity_sid = f"{MISSION_ID}_captain_rime"
    _append_object_group(objects, sid="hero-spawner", object_id=hero_id, node=node)
    _ensure_prop_list(properties, "propEntities").append(
        {"type": 0, "id": hero_id, "sid": entity_sid}
    )
    # Dialog is NOT on propActionsBefore — hero-spawner combat skips it.
    # BeforeIamVsHero interruption in the quest script owns the taunt.
    _ensure_prop_list(properties, "propActivations").append(
        {"type": 0, "id": hero_id, "isActive": True}
    )
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
                "Recover three stolen pieces of the Brine Bell across the salt flats, "
                "break a Cove pirate landing, defeat Captain Rime, and capture Brinehold."
            ),
            "displayWinCondition": "Capture Brinehold from Captain Rime's Cove raiders.",
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
                "takenHeroes": [PLAYER_HERO, ENEMY_CITY_HERO, ENEMY_HERO],
            },
            # Empty campaign shell (not null) — matches shipped custom scenarios.
            "campaignInfo": {
                "missionNameSid": "",
                "missionDescSid": "",
                "campaignSid": "",
                "campaignDescSid": "",
                "hubIconSid": "",
            },
        }
    )
    start = meta.setdefault("startSettings", {})
    if isinstance(start, dict):
        # Capture-keep is the authored win path; DefeatAll remains available as fallback.
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
            "takenHeroes": [PLAYER_HERO, ENEMY_CITY_HERO, ENEMY_HERO],
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
            "rivers": [{"sid": "test", "randomSeed": 1, "nodes": []}],
            "views": [
                {
                    "name": "",
                    "minSecX": 0,
                    "minSecZ": 0,
                    "secSizeX": VIEW_SEC_SIZE,
                    "secSizeZ": VIEW_SEC_SIZE,
                    "isUnderground": False,
                    "stack": -1,
                }
            ],
            # Explicit scenario settings (empty win-condition list; QuestScript owns victory).
            "settings": {
                "heroCountMin": 1,
                "heroCountMax": 1,
                "heroCountIncrement": 1,
                "enableHeroHireBan": False,
                "enableCustomHeroMaxLevel": False,
                "customHeroMaxLevel": 0,
                "disableAutoBattleAgainstEnemyHeroes": False,
                "disableWeekEffect": False,
                "disableFactionLaws": False,
                "disableMagicGuild": False,
                "disableMagicCustomLearning": False,
                "cantRewriteTurnMode": False,
                "idSidesWithoutTimer": [0, 1],
                "idSidesWithoutNotification": [],
                "idSidesWithoutCameraFollowing": [],
                "isTournamentRules": False,
                "bonuses": [],
                "mapWinConditions": [],
                "gameMode": 0,
                "endController": 0,
                "isScenario": True,
                "economicDifficulties": [True, True, True, True, True, True],
                "aiDifficulties": [False, True, True, True, True, False],
                "neutralDifficulties": [True, True, True, True, True, True],
                "quickStartDifficulties": [True, True, True, True, True, True],
                "enableCustomAI": False,
                "customAISid": "",
                "factionLawsExpModifier": 1.0,
                "astrologyExpModifier": 1.0,
            },
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
        city_name="Saltspire",
        spawn_type=0,
    )
    _append_city(
        objects=objects,
        properties=properties,
        city_id=ENEMY_CITY_ID,
        node=enemy_node,
        owner=2,
        faction=ENEMY_FACTION,
        hero_sid=ENEMY_CITY_HERO,
        entity_sid=ENEMY_KEEP_ENTITY,
        city_name=ENEMY_KEEP_NAME,
        spawn_type=1,
    )


def inject_world_content(map_data: dict[str, Any]) -> dict[str, Any]:
    objects = map_data.setdefault("objects", [])
    markers = map_data.setdefault("markers", [])
    properties = map_data.setdefault("objectsProperties", {})
    next_object_id = int(map_data.get("objectsFreeId") or (BASE_OBJECT_ID + 20))
    next_marker_id = max(int(map_data.get("markersFreeId") or 1), 1)

    caches = [
        ("clapper", CLAPPER_XY, f"{MISSION_ID}_clapper", f"{MISSION_ID}_clapper"),
        ("rope", ROPE_XY, f"{MISSION_ID}_rope", f"{MISSION_ID}_rope"),
        ("crown", CROWN_XY, f"{MISSION_ID}_crown", f"{MISSION_ID}_crown"),
    ]
    report_caches: dict[str, Any] = {}
    for key, xy, entity_sid, dialog_sid in caches:
        next_object_id, next_marker_id = _inject_zone_cache(
            objects=objects,
            markers=markers,
            properties=properties,
            xy=xy,
            entity_sid=entity_sid,
            dialog_sid=dialog_sid,
            next_object_id=next_object_id,
            next_marker_id=next_marker_id,
        )
        report_caches[key] = {"xy": list(xy), "entitySid": entity_sid, "oneShot": True}

    next_object_id = _inject_pirate_landing(objects, properties, next_object_id)
    next_object_id = _inject_captain_hero(objects, properties, next_object_id)

    map_data["objectsFreeId"] = next_object_id
    map_data["markersFreeId"] = next_marker_id
    return {
        "caches": report_caches,
        "pirateLanding": {
            "xy": list(PIRATE_LANDING_XY),
            "unit": PIRATE_UNIT_SID,
            "count": PIRATE_COUNT,
            "squadOverlaySid": PIRATE_SQUAD_SID,
            "valueBudget": PIRATE_VALUE_BUDGET,
        },
        "captain": {"xy": list(CAPTAIN_XY), "heroSid": ENEMY_HERO},
        "enemyKeep": {
            "xy": list(ENEMY_CITY_XY),
            "entitySid": ENEMY_KEEP_ENTITY,
            "name": ENEMY_KEEP_NAME,
        },
        "playerCity": {"xy": list(PLAYER_CITY_XY), "name": "Saltspire"},
        "coordinateConvention": "node=y*width+x; Olden +Y = north",
        "mapSize": MAP_SIZE,
    }


def write_core_overlay(out_root: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    overlay = out_root / "core_overlay"
    squad_dir = overlay / "DB" / "squads" / "squads_custom_maps" / "BrineBell"
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
        member = f"DB/dialogs/dialogs/custom_maps/BrineBell/{dialog_sid}.json"
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

    squad_member = f"DB/squads/squads_custom_maps/BrineBell/{PIRATE_SQUAD_SID}.json"
    write_json(
        overlay / squad_member,
        {
            "array": [
                {
                    "id": PIRATE_SQUAD_SID,
                    "squad": [],
                    "useOldSquads": False,
                    "rollChance": 0,
                    "canBeMainGuard": True,
                    "baseSquad": {
                        "units": [{"s": PIRATE_UNIT_SID, "v": PIRATE_VALUE_BUDGET}]
                    },
                    "dynamicSquad": {
                        "requiredValue": PIRATE_VALUE_BUDGET,
                        "units": [PIRATE_UNIT_SID],
                    },
                    "randomSquad": {
                        "maxValue": PIRATE_VALUE_BUDGET,
                        "units": [{"s": PIRATE_UNIT_SID, "v": PIRATE_VALUE_BUDGET}],
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
        "missionId": MISSION_ID,
        "schemaDonorMap": str(poc.PLAYABLE_TEMPLATE_MAP),
        "schemaDonorRole": "4-chunk playable container only; terrain/objects/quests discarded",
        "output": str(out_map),
        "sidecar": str(out_json),
        "installDestinationPolicy": "maps_root_custom_only",
        "coreOverlayRequired": True,
        "world": world_report,
        "coreOverlay": overlay_report,
        "objectives": {
            "main": "Capture Brinehold",
            "subQuests": [
                "Recover the clapper",
                "Recover the rope",
                "Recover the bronze crown",
                "Clear the pirate landing (optional)",
            ],
            "events": [
                "Day-1 briefing with starter gold/wood",
                "Three one-shot bell-fragment Zone dialogs with rewards",
                "Harbor council gold every 5 days (CED timer)",
                "Pirate landing SquadInteraction dialog + SquadKill gem bounty",
                "Captain Rime BeforeIamVsHero taunt",
                "Victory dialog on Brinehold ObjectCaptureEntity",
            ],
        },
        "proofBoundary": (
            "generated artifact + Core overlay members; installed/startup/runtime "
            "behavior remains user-unvalidated"
        ),
        "howToRun": [
            "python experiments/campaign_port_poc/build_brine_bell_scenario.py",
            "python tools/validate_brine_bell_scenario_contract.py --repo-root .",
            "python tools/install_brine_bell_scenario.py --repo-root .",
            "Launch Golden Era → QuickStart → The Brine Bell",
            "Walk the dirt trails (+Y north) to gold marks, pirates, Captain Rime, then Brinehold",
        ],
    }
    write_json(out_root / "install_manifest.json", manifest)
    write_json(out_root / "brine_bell_report.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()
    manifest = build(out_root=args.out_root.resolve())
    print(
        json.dumps(
            {"ok": True, "mapSid": manifest["mapSid"], "output": manifest["output"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
