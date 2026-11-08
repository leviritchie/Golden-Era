#!/usr/bin/env python3
"""Compile HoMM3 map victory/loss headers into Olden QuestScript contracts.

Source of truth is the decoded H3M/H3C header (``h3m_format.decode_h3m_scenario_header``).
Profile ``victoryContract`` remains an optional validation overlay for explicit
TAKEDWELLINGS key lists (Griffin Cliff); it does not invent win paths.

Native QuestScript verbs used here are proven on shipped Story/custom maps:
ItemOwnSide, ObjectCaptureEntity/ObjectLose, HeroKill, SquadKill, ResCounter,
UnitOwnSide, BuildingOwn, PlayerDefeated, StartTurn, GameVictory, GameLose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from campaign_event_ir.schedule_encode import start_turn_condition
from campaign_runtime_script import H3_RESOURCE_GIVE_RES_IDS
from h3m_hero_sid import resolve_h3_hero_sid
from vanilla_stock.h3_artifact_stock_map import require_item_sid_for_h3_artifact_id

# SoD campaign maps occasionally encode combination / relocated artifact ids that
# are absent from ARTraits ordinals in our catalog. Map them explicitly.
CAMPAIGN_VICTORY_ARTIFACT_ALIASES: dict[int, int] = {
    # a_thief_in_the_night: Complete H3C stores 131; catalog Vial of Lifeblood is 96.
    131: 96,
}

# gathering_the_legion TRANSPORTITEM 133: require the five Statue of Legion pieces.
CAMPAIGN_VICTORY_ARTIFACT_SETS: dict[int, tuple[int, ...]] = {
    133: (118, 119, 120, 121, 122),
}

# H3M BUILDCITY hallLevel: 0=Town, 1=City, 2=Capitol → Build_Main levels.
HALL_LEVEL_TO_BUILD_MAIN: dict[int, int] = {0: 2, 1: 3, 2: 4}
# H3M castleLevel: 0=Fort, 1=Citadel, 2=Castle → Build_Wall levels.
CASTLE_LEVEL_TO_BUILD_WALL: dict[int, int] = {0: 1, 1: 2, 2: 3}

TOWN_PAYLOADS = frozenset({"town"})
HERO_PAYLOADS = frozenset({"hero", "hero_or_prison", "hero_placeholder"})
MONSTER_PAYLOADS = frozenset({"monster", "random_monster", "pandora", "quest_guard"})
MINE_CATEGORIES = frozenset({"mine", "abandoned_mine"})
DWELLING_PAYLOADS = frozenset({"creature_generator"})

POSITION_SEARCH_RADIUS = 3


class CampaignVictoryError(ValueError):
    """Fail-closed victory/loss binding or emit error."""


@dataclass(frozen=True)
class PropEntityBinding:
    object_id: int
    entity_sid: str
    role: str
    source_key: str


@dataclass
class VictoryPlan:
    mission_id: str
    victory_name: str
    allow_normal_victory: bool
    defeat_all_enemies_enabled: bool
    loss_name: str
    prop_entity_bindings: list[PropEntityBinding] = field(default_factory=list)
    counters: list[dict[str, Any]] = field(default_factory=list)
    win_triggers: list[dict[str, Any]] = field(default_factory=list)
    loss_triggers: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def source_key_from_position(position: dict[str, Any]) -> str:
    return f"{int(position['z'])}:{int(position['x'])}:{int(position['y'])}"


def _chebyshev(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _parse_source_key(source_key: str) -> tuple[int, int, int] | None:
    parts = str(source_key).split(":")
    if len(parts) != 3:
        return None
    try:
        z, x, y = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    return z, x, y


def _entities_matching(
    entities: list[dict[str, Any]],
    *,
    position: dict[str, Any] | None = None,
    source_key: str | None = None,
    payload_kinds: frozenset[str] | None = None,
    categories: frozenset[str] | None = None,
    radius: int = POSITION_SEARCH_RADIUS,
) -> list[dict[str, Any]]:
    if source_key is None and position is not None:
        source_key = source_key_from_position(position)
    exact = [
        row
        for row in entities
        if isinstance(row, dict) and str(row.get("sourceKey") or "") == source_key
    ]
    filtered_exact = _filter_entities(exact, payload_kinds=payload_kinds, categories=categories)
    if filtered_exact:
        return filtered_exact
    if position is None:
        return []
    target = (int(position["z"]), int(position["x"]), int(position["y"]))
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in entities:
        if not isinstance(row, dict):
            continue
        if not _entity_matches(row, payload_kinds=payload_kinds, categories=categories):
            continue
        parsed = _parse_source_key(str(row.get("sourceKey") or ""))
        if parsed is None or parsed[0] != target[0]:
            continue
        dist = _chebyshev(parsed, target)
        if dist <= radius:
            scored.append((dist, row))
    scored.sort(key=lambda item: (item[0], int(item[1].get("sourceIndex") or 0)))
    return [row for _dist, row in scored]


def _filter_entities(
    rows: list[dict[str, Any]],
    *,
    payload_kinds: frozenset[str] | None,
    categories: frozenset[str] | None,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if _entity_matches(row, payload_kinds=payload_kinds, categories=categories)
    ]


def _entity_matches(
    row: dict[str, Any],
    *,
    payload_kinds: frozenset[str] | None,
    categories: frozenset[str] | None,
) -> bool:
    if payload_kinds is not None and str(row.get("payloadKind") or "") not in payload_kinds:
        return False
    if categories is not None and str(row.get("category") or "") not in categories:
        return False
    return True


def _pick_nearest_all(
    rows: list[dict[str, Any]],
    *,
    position: dict[str, Any],
    context: str,
) -> list[dict[str, Any]]:
    """Return every match tied for nearest Chebyshev distance (fail if none)."""

    if not rows:
        raise CampaignVictoryError(f"{context}: expected at least one match; found 0")
    target = (int(position["z"]), int(position["x"]), int(position["y"]))
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        parsed = _parse_source_key(str(row.get("sourceKey") or ""))
        if parsed is None:
            continue
        scored.append((_chebyshev(parsed, target), row))
    if not scored:
        raise CampaignVictoryError(f"{context}: matches lacked parseable sourceKey")
    best = min(dist for dist, _row in scored)
    return [row for dist, row in scored if dist == best]


def _pick_nearest(
    rows: list[dict[str, Any]],
    *,
    position: dict[str, Any],
    context: str,
) -> dict[str, Any]:
    tied = _pick_nearest_all(rows, position=position, context=context)
    if len(tied) != 1:
        keys = [row.get("sourceKey") for row in tied]
        raise CampaignVictoryError(
            f"{context}: ambiguous nearest match; found {len(tied)} {keys}"
        )
    return tied[0]


def _require_position_entity(
    entities: list[dict[str, Any]],
    *,
    position: dict[str, Any],
    context: str,
    payload_kinds: frozenset[str] | None = None,
    categories: frozenset[str] | None = None,
) -> dict[str, Any]:
    rows = _entities_matching(
        entities,
        position=position,
        payload_kinds=payload_kinds,
        categories=categories,
    )
    return _pick_nearest(rows, position=position, context=context)


def _require_unique(
    rows: list[dict[str, Any]],
    *,
    context: str,
) -> dict[str, Any]:
    if len(rows) != 1:
        keys = [row.get("sourceKey") for row in rows]
        raise CampaignVictoryError(f"{context}: expected exactly one match; found {len(rows)} {keys}")
    return rows[0]


def _object_id(row: dict[str, Any], *, context: str) -> int:
    object_id = row.get("sourceIndex")
    if not isinstance(object_id, int):
        raise CampaignVictoryError(f"{context}: missing integer sourceIndex on {row.get('sourceKey')}")
    return object_id


def _artifact_item_sids(artifact_id: int) -> list[str]:
    artifact_id = int(artifact_id)
    if artifact_id in CAMPAIGN_VICTORY_ARTIFACT_SETS:
        return [
            require_item_sid_for_h3_artifact_id(member)
            for member in CAMPAIGN_VICTORY_ARTIFACT_SETS[artifact_id]
        ]
    mapped = CAMPAIGN_VICTORY_ARTIFACT_ALIASES.get(artifact_id, artifact_id)
    return [require_item_sid_for_h3_artifact_id(mapped)]


def _item_own_side_conditions(item_sids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "comment": "",
            "c": "ItemOwnSide",
            "p": [sid, ">", "0"],
            "counter": 1,
        }
        for sid in item_sids
    ]


def _counter_row(sid: str, *, value: int = 0) -> dict[str, Any]:
    return {
        "comment": "",
        "sid": sid,
        "sharing": "Clone",
        "value": value,
        "minValue": -2147483648,
        "maxValue": 2147483647,
    }


def _counter_condition(sid: str, operator: str, value: int) -> dict[str, Any]:
    return {"comment": "", "c": "Counter", "p": [sid, operator, str(value)], "counter": 1}


def _game_victory_actions(mission_id: str) -> list[dict[str, Any]]:
    return [
        {"comment": "", "a": "CounterSet", "p": [f"{mission_id}_main_goal_complete", "1"]},
        {"comment": "", "a": "GameVictory", "p": []},
    ]


def _game_lose_actions() -> list[dict[str, Any]]:
    return [{"comment": "", "a": "GameLose", "p": []}]


def _capture_counter_triggers(
    *,
    mission_id: str,
    entity_sids: list[str],
    counter_sid: str,
    comment_prefix: str,
) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for entity_sid in entity_sids:
        triggers.extend(
            [
                {
                    "comment": f"{comment_prefix} capture {entity_sid}",
                    "repeat": True,
                    "conditions": [
                        {"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1}
                    ],
                    "actions": [{"comment": "", "a": "CounterPlus", "p": [counter_sid, "1"]}],
                    "conditionsLogic": "And",
                },
                {
                    "comment": f"{comment_prefix} lose {entity_sid}",
                    "repeat": True,
                    "conditions": [
                        {"comment": "", "c": "ObjectLose", "p": [entity_sid], "counter": 1}
                    ],
                    "actions": [{"comment": "", "a": "CounterMinus", "p": [counter_sid, "1"]}],
                    "conditionsLogic": "And",
                },
            ]
        )
    triggers.append(
        {
            "comment": f"{comment_prefix} win at {len(entity_sids)}",
            "repeat": False,
            "conditions": [_counter_condition(counter_sid, "=", len(entity_sids))],
            "actions": _game_victory_actions(mission_id),
            "conditionsLogic": "And",
        }
    )
    return triggers


def _resolve_hero_sid(row: dict[str, Any], *, context: str) -> str:
    hero_type = row.get("heroType")
    if not isinstance(hero_type, int):
        raise CampaignVictoryError(f"{context}: hero row missing heroType at {row.get('sourceKey')}")
    name = row.get("heroName") or row.get("name")
    hero_sid, _evidence = resolve_h3_hero_sid(
        hero_type,
        name=str(name) if isinstance(name, str) and name.strip() else None,
    )
    if not hero_sid:
        raise CampaignVictoryError(
            f"{context}: no Olden heroSid for heroType={hero_type} at {row.get('sourceKey')}"
        )
    return hero_sid


def _unit_sid_for_creature(
    creature_id: int,
    *,
    creature_to_unit: Callable[[int], str | None],
    context: str,
) -> str:
    unit_sid = creature_to_unit(int(creature_id))
    if not unit_sid:
        raise CampaignVictoryError(f"{context}: no Olden unit SID for creatureId={creature_id}")
    return unit_sid


def plan_campaign_victory(
    *,
    mission_id: str,
    header: dict[str, Any],
    entities: list[dict[str, Any]],
    creature_to_unit: Callable[[int], str | None],
    profile_victory: dict[str, Any] | None = None,
) -> VictoryPlan:
    victory = header.get("victory") or {}
    loss = header.get("loss") or {}
    victory_name = str(victory.get("name") or "")
    loss_name = str(loss.get("name") or "")
    special = victory.get("special") if isinstance(victory.get("special"), dict) else {}
    loss_special = loss.get("special") if isinstance(loss.get("special"), dict) else {}
    allow_normal = victory.get("allowNormalVictory")
    if victory_name == "WINSTANDARD" or allow_normal is None and victory_name == "WINSTANDARD":
        allow_normal_victory = True
    elif isinstance(allow_normal, bool):
        allow_normal_victory = allow_normal
    else:
        allow_normal_victory = False

    plan = VictoryPlan(
        mission_id=mission_id,
        victory_name=victory_name,
        allow_normal_victory=allow_normal_victory,
        defeat_all_enemies_enabled=bool(allow_normal_victory or victory_name == "WINSTANDARD"),
        loss_name=loss_name,
    )
    plan.evidence.append(f"header victory={victory_name} allow_normal={allow_normal_victory}")
    plan.evidence.append(f"header loss={loss_name}")

    if victory_name == "WINSTANDARD":
        _plan_winstandard(plan, header=header, entities=entities)
    elif victory_name == "ARTIFACT":
        _plan_artifact(plan, artifact_id=int(special["artifactId"]))
    elif victory_name == "TRANSPORTITEM":
        _plan_transport(
            plan,
            entities=entities,
            artifact_id=int(special["artifactId"]),
            position=special["position"],
        )
    elif victory_name == "CAPTURECITY":
        _plan_capture_city(plan, entities=entities, position=special["position"])
    elif victory_name == "BEATHERO":
        _plan_beat_hero(plan, entities=entities, position=special["position"])
    elif victory_name == "BEATMONSTER":
        _plan_beat_monster(plan, entities=entities, position=special["position"])
    elif victory_name == "TAKEDWELLINGS":
        _plan_take_dwellings(plan, entities=entities, profile_victory=profile_victory)
    elif victory_name == "TAKEMINES":
        _plan_take_mines(plan, entities=entities)
    elif victory_name == "GATHERRESOURCE":
        _plan_gather_resource(
            plan,
            resource_id=int(special["resourceId"]),
            count=int(special["count"]),
        )
    elif victory_name == "GATHERTROOP":
        _plan_gather_troop(
            plan,
            creature_id=int(special["creatureId"]),
            count=int(special["count"]),
            creature_to_unit=creature_to_unit,
        )
    elif victory_name == "BUILDCITY":
        _plan_build_city(
            plan,
            entities=entities,
            position=special["position"],
            hall_level=int(special["hallLevel"]),
            castle_level=int(special["castleLevel"]),
        )
    elif victory_name == "BUILDGRAIL":
        _plan_build_grail(plan, entities=entities, position=special["position"])
    elif victory_name == "SURVIVE_TIME":
        _plan_survive_time(plan, days=int(special["days"]))
    elif victory_name == "DEFEAT_ALL_MONSTERS":
        _plan_defeat_all_monsters(plan, entities=entities)
    else:
        raise CampaignVictoryError(f"{mission_id}: unsupported victory type {victory_name!r}")

    if loss_name == "LOSSHERO":
        _plan_loss_hero(plan, entities=entities, position=loss_special["position"])
    elif loss_name == "LOSSCASTLE":
        _plan_loss_castle(plan, entities=entities, position=loss_special["position"])
    elif loss_name == "TIMEEXPIRES":
        _plan_loss_time(plan, days=int(loss_special["days"]))
    elif loss_name != "LOSSSTANDARD":
        raise CampaignVictoryError(f"{mission_id}: unsupported loss type {loss_name!r}")

    if not plan.win_triggers and not plan.defeat_all_enemies_enabled:
        raise CampaignVictoryError(
            f"{mission_id}: victory plan produced no GameVictory path and DefeatAll is disabled"
        )
    return plan


def _plan_winstandard(
    plan: VictoryPlan,
    *,
    header: dict[str, Any],
    entities: list[dict[str, Any]],
) -> None:
    players = header.get("players") or []
    playable = [
        int(row["index"])
        for row in players
        if isinstance(row, dict) and row.get("playable") and isinstance(row.get("index"), int)
    ]
    humans = [
        int(row["index"])
        for row in players
        if isinstance(row, dict)
        and row.get("playable")
        and row.get("canHuman")
        and isinstance(row.get("index"), int)
    ]
    if len(playable) >= 2 and humans:
        for human in humans:
            others = [index for index in playable if index != human]
            if not others:
                continue
            plan.win_triggers.append(
                {
                    "comment": f"WINSTANDARD player {human} when others defeated",
                    "repeat": False,
                    "conditions": [
                        {
                            "comment": "",
                            "c": "PlayerDefeated",
                            "p": [str(index + 1)],
                            "counter": 1,
                        }
                        for index in others
                    ],
                    "actions": _game_victory_actions(plan.mission_id),
                    "conditionsLogic": "And",
                }
            )
        plan.defeat_all_enemies_enabled = True
        plan.evidence.append("WINSTANDARD → DefeatAll + PlayerDefeated")
        return
    # Single playable color: H3 still labels WINSTANDARD while briefings demand
    # clearing neutrals (Festival taming_of_the_wild). Bind every monster squad.
    _plan_defeat_all_monsters(plan, entities=entities)
    plan.defeat_all_enemies_enabled = False
    plan.allow_normal_victory = False
    plan.evidence.append("WINSTANDARD single-player → defeat all map monster squads")


def _plan_artifact(plan: VictoryPlan, *, artifact_id: int) -> None:
    item_sids = _artifact_item_sids(artifact_id)
    plan.win_triggers.append(
        {
            "comment": f"ARTIFACT own {item_sids}",
            "repeat": False,
            "conditions": _item_own_side_conditions(item_sids),
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"ARTIFACT → ItemOwnSide {item_sids}")


def _plan_transport(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    artifact_id: int,
    position: dict[str, Any],
) -> None:
    town = _require_position_entity(
        entities,
        position=position,
        payload_kinds=TOWN_PAYLOADS,
        context=f"{plan.mission_id} TRANSPORTITEM town",
    )
    object_id = _object_id(town, context=f"{plan.mission_id} TRANSPORTITEM")
    entity_sid = f"{plan.mission_id}_transport_town"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="transport_town",
            source_key=str(town.get("sourceKey") or ""),
        )
    )
    conditions = _item_own_side_conditions(_artifact_item_sids(artifact_id))
    conditions.append(
        {"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1}
    )
    plan.win_triggers.append(
        {
            "comment": f"TRANSPORTITEM artifact to {entity_sid}",
            "repeat": False,
            "conditions": conditions,
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"TRANSPORTITEM → ItemOwnSide + ObjectCaptureEntity {entity_sid}")


def _plan_capture_city(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    town = _require_position_entity(
        entities,
        position=position,
        payload_kinds=TOWN_PAYLOADS,
        context=f"{plan.mission_id} CAPTURECITY",
    )
    object_id = _object_id(town, context=f"{plan.mission_id} CAPTURECITY")
    entity_sid = f"{plan.mission_id}_capture_city"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="capture_city",
            source_key=str(town.get("sourceKey") or ""),
        )
    )
    plan.win_triggers.append(
        {
            "comment": f"CAPTURECITY {entity_sid}",
            "repeat": False,
            "conditions": [
                {"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1}
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"CAPTURECITY → ObjectCaptureEntity {entity_sid}")


def _plan_beat_hero(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    hero = _require_position_entity(
        entities,
        position=position,
        payload_kinds=HERO_PAYLOADS,
        context=f"{plan.mission_id} BEATHERO",
    )
    hero_sid = _resolve_hero_sid(hero, context=f"{plan.mission_id} BEATHERO")
    plan.win_triggers.append(
        {
            "comment": f"BEATHERO {hero_sid}",
            "repeat": False,
            "conditions": [{"comment": "", "c": "HeroKill", "p": [hero_sid], "counter": 1}],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"BEATHERO → HeroKill {hero_sid}")


def _plan_beat_monster(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    rows = _entities_matching(entities, position=position, payload_kinds=MONSTER_PAYLOADS)
    if not rows:
        # Concrete monsters often decode as payload monster under category creature.
        rows = _entities_matching(
            entities,
            position=position,
            categories=frozenset({"creature", "monster", "wandering_monster"}),
        )
    monster = _pick_nearest(rows, position=position, context=f"{plan.mission_id} BEATMONSTER")
    object_id = _object_id(monster, context=f"{plan.mission_id} BEATMONSTER")
    entity_sid = f"{plan.mission_id}_beat_monster"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="beat_monster",
            source_key=str(monster.get("sourceKey") or ""),
        )
    )
    plan.win_triggers.append(
        {
            "comment": f"BEATMONSTER {entity_sid}",
            "repeat": False,
            "conditions": [{"comment": "", "c": "SquadKill", "p": [entity_sid], "counter": 1}],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"BEATMONSTER → SquadKill {entity_sid}")


def _plan_take_dwellings(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    profile_victory: dict[str, Any] | None,
) -> None:
    dwellings = [
        row
        for row in entities
        if isinstance(row, dict)
        and row.get("category") == "external_dwelling"
        and str(row.get("payloadKind") or "") in DWELLING_PAYLOADS
    ]
    if profile_victory and profile_victory.get("type") == "TAKEDWELLINGS":
        keys = list(profile_victory.get("sourceKeys") or [])
        if not keys:
            raise CampaignVictoryError(f"{plan.mission_id}: profile TAKEDWELLINGS sourceKeys empty")
        by_key = {str(row.get("sourceKey") or ""): row for row in dwellings}
        selected: list[dict[str, Any]] = []
        for key in keys:
            row = by_key.get(key)
            if row is None:
                raise CampaignVictoryError(
                    f"{plan.mission_id}: profile dwelling sourceKey {key!r} not in alignment"
                )
            selected.append(row)
        dwellings = selected
        plan.evidence.append("TAKEDWELLINGS filtered by profile sourceKeys")
    else:
        dwellings = sorted(dwellings, key=lambda r: str(r.get("sourceKey") or ""))
    if not dwellings:
        raise CampaignVictoryError(f"{plan.mission_id}: TAKEDWELLINGS found no creature generators")
    entity_sids: list[str] = []
    for ordinal, row in enumerate(dwellings, start=1):
        object_id = _object_id(row, context=f"{plan.mission_id} TAKEDWELLINGS")
        entity_sid = f"{plan.mission_id}_dwelling_{ordinal}"
        entity_sids.append(entity_sid)
        plan.prop_entity_bindings.append(
            PropEntityBinding(
                object_id=object_id,
                entity_sid=entity_sid,
                role="dwelling",
                source_key=str(row.get("sourceKey") or ""),
            )
        )
    counter_sid = f"{plan.mission_id}_dwellings_owned"
    plan.counters.append(_counter_row(counter_sid))
    plan.win_triggers.extend(
        _capture_counter_triggers(
            mission_id=plan.mission_id,
            entity_sids=entity_sids,
            counter_sid=counter_sid,
            comment_prefix="TAKEDWELLINGS",
        )
    )
    plan.evidence.append(f"TAKEDWELLINGS → {len(entity_sids)} dwellings")


def _plan_take_mines(plan: VictoryPlan, *, entities: list[dict[str, Any]]) -> None:
    mines = [
        row
        for row in entities
        if isinstance(row, dict)
        and (
            str(row.get("category") or "") in MINE_CATEGORIES
            or str(row.get("payloadKind") or "") in {"mine", "abandoned_mine"}
            or str(row.get("templateAnimation") or "").lower().startswith("avm")
        )
    ]
    if not mines:
        raise CampaignVictoryError(f"{plan.mission_id}: TAKEMINES found no mines")
    entity_sids: list[str] = []
    for ordinal, row in enumerate(sorted(mines, key=lambda r: str(r.get("sourceKey") or "")), start=1):
        object_id = _object_id(row, context=f"{plan.mission_id} TAKEMINES")
        entity_sid = f"{plan.mission_id}_mine_{ordinal}"
        entity_sids.append(entity_sid)
        plan.prop_entity_bindings.append(
            PropEntityBinding(
                object_id=object_id,
                entity_sid=entity_sid,
                role="mine",
                source_key=str(row.get("sourceKey") or ""),
            )
        )
    counter_sid = f"{plan.mission_id}_mines_owned"
    plan.counters.append(_counter_row(counter_sid))
    plan.win_triggers.extend(
        _capture_counter_triggers(
            mission_id=plan.mission_id,
            entity_sids=entity_sids,
            counter_sid=counter_sid,
            comment_prefix="TAKEMINES",
        )
    )
    plan.evidence.append(f"TAKEMINES → {len(entity_sids)} mines")


def _plan_gather_resource(plan: VictoryPlan, *, resource_id: int, count: int) -> None:
    if resource_id < 0 or resource_id >= len(H3_RESOURCE_GIVE_RES_IDS):
        raise CampaignVictoryError(f"{plan.mission_id}: bad resourceId {resource_id}")
    if count <= 0:
        raise CampaignVictoryError(f"{plan.mission_id}: GATHERRESOURCE count must be > 0")
    resource_sid = H3_RESOURCE_GIVE_RES_IDS[resource_id]
    plan.win_triggers.append(
        {
            "comment": f"GATHERRESOURCE {resource_sid}>={count}",
            "repeat": False,
            "conditions": [
                {
                    "comment": "",
                    "c": "ResCounter",
                    "p": [resource_sid, ">=", str(count)],
                    "counter": 1,
                }
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"GATHERRESOURCE → ResCounter {resource_sid}>={count}")


def _plan_gather_troop(
    plan: VictoryPlan,
    *,
    creature_id: int,
    count: int,
    creature_to_unit: Callable[[int], str | None],
) -> None:
    if count <= 0:
        raise CampaignVictoryError(f"{plan.mission_id}: GATHERTROOP count must be > 0")
    unit_sid = _unit_sid_for_creature(
        creature_id,
        creature_to_unit=creature_to_unit,
        context=f"{plan.mission_id} GATHERTROOP",
    )
    plan.win_triggers.append(
        {
            "comment": f"GATHERTROOP {unit_sid}>{count - 1}",
            "repeat": False,
            "conditions": [
                {
                    "comment": "",
                    "c": "UnitOwnSide",
                    "p": [unit_sid, ">", str(count - 1)],
                    "counter": 1,
                }
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"GATHERTROOP → UnitOwnSide {unit_sid}>{count - 1}")


def _plan_build_city(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
    hall_level: int,
    castle_level: int,
) -> None:
    town = _require_position_entity(
        entities,
        position=position,
        payload_kinds=TOWN_PAYLOADS,
        context=f"{plan.mission_id} BUILDCITY",
    )
    object_id = _object_id(town, context=f"{plan.mission_id} BUILDCITY")
    entity_sid = f"{plan.mission_id}_build_city"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="build_city",
            source_key=str(town.get("sourceKey") or ""),
        )
    )
    if hall_level not in HALL_LEVEL_TO_BUILD_MAIN:
        raise CampaignVictoryError(f"{plan.mission_id}: unsupported hallLevel {hall_level}")
    if castle_level not in CASTLE_LEVEL_TO_BUILD_WALL:
        raise CampaignVictoryError(f"{plan.mission_id}: unsupported castleLevel {castle_level}")
    hall_oe = HALL_LEVEL_TO_BUILD_MAIN[hall_level]
    wall_oe = CASTLE_LEVEL_TO_BUILD_WALL[castle_level]
    plan.win_triggers.append(
        {
            "comment": f"BUILDCITY hall={hall_oe} wall={wall_oe} at {entity_sid}",
            "repeat": False,
            "conditions": [
                {
                    "comment": "",
                    "c": "BuildingOwn",
                    "p": ["Build_Main", str(hall_oe), entity_sid],
                    "counter": 1,
                },
                {
                    "comment": "",
                    "c": "BuildingOwn",
                    "p": ["Build_Wall", str(wall_oe), entity_sid],
                    "counter": 1,
                },
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"BUILDCITY → BuildingOwn Main/{hall_oe} Wall/{wall_oe}")


def _plan_build_grail(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    """Approximate H3 BUILDGRAIL: own target town while carrying the Grail artifact.

    Olden has no stock ``Build_Grail`` BuildingOwn verb; native maps do not expose
    a grail-structure ownership condition. Holding the Grail in a captured town is
    the fail-closed playable substitute until a grail building SID exists.
    """

    town = _require_position_entity(
        entities,
        position=position,
        payload_kinds=TOWN_PAYLOADS,
        context=f"{plan.mission_id} BUILDGRAIL",
    )
    object_id = _object_id(town, context=f"{plan.mission_id} BUILDGRAIL")
    entity_sid = f"{plan.mission_id}_grail_town"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="grail_town",
            source_key=str(town.get("sourceKey") or ""),
        )
    )
    grail_sid = require_item_sid_for_h3_artifact_id(2)
    plan.win_triggers.append(
        {
            "comment": f"BUILDGRAIL approx ItemOwnSide({grail_sid}) + capture {entity_sid}",
            "repeat": False,
            "conditions": [
                {"comment": "", "c": "ItemOwnSide", "p": [grail_sid, ">", "0"], "counter": 1},
                {"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1},
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(
        "BUILDGRAIL → ItemOwnSide(grail)+ObjectCaptureEntity (no native Build_Grail)"
    )


def _plan_survive_time(plan: VictoryPlan, *, days: int) -> None:
    if days <= 0:
        raise CampaignVictoryError(f"{plan.mission_id}: SURVIVE_TIME days must be > 0")
    # Win at the start of the day after surviving ``days`` full days.
    plan.win_triggers.append(
        {
            "comment": f"SURVIVE_TIME {days} days",
            "repeat": False,
            "conditions": [
                start_turn_condition(days + 1, context=f"{plan.mission_id} SURVIVE_TIME")
            ],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.defeat_all_enemies_enabled = False
    plan.evidence.append(f"SURVIVE_TIME → StartTurn day {days + 1}")


def _plan_defeat_all_monsters(plan: VictoryPlan, *, entities: list[dict[str, Any]]) -> None:
    monsters = [
        row
        for row in entities
        if isinstance(row, dict)
        and (
            str(row.get("payloadKind") or "") in MONSTER_PAYLOADS
            or str(row.get("category") or "") in {"creature", "monster", "wandering_monster"}
        )
    ]
    if not monsters:
        raise CampaignVictoryError(
            f"{plan.mission_id}: DEFEAT_ALL_MONSTERS / single-player WINSTANDARD found no monsters"
        )
    counter_sid = f"{plan.mission_id}_monsters_killed"
    plan.counters.append(_counter_row(counter_sid))
    entity_sids: list[str] = []
    for ordinal, row in enumerate(sorted(monsters, key=lambda r: str(r.get("sourceKey") or "")), start=1):
        object_id = _object_id(row, context=f"{plan.mission_id} DEFEAT_ALL_MONSTERS")
        entity_sid = f"{plan.mission_id}_monster_{ordinal}"
        entity_sids.append(entity_sid)
        plan.prop_entity_bindings.append(
            PropEntityBinding(
                object_id=object_id,
                entity_sid=entity_sid,
                role="monster",
                source_key=str(row.get("sourceKey") or ""),
            )
        )
        plan.win_triggers.append(
            {
                "comment": f"monster kill {entity_sid}",
                "repeat": False,
                "conditions": [{"comment": "", "c": "SquadKill", "p": [entity_sid], "counter": 1}],
                "actions": [{"comment": "", "a": "CounterPlus", "p": [counter_sid, "1"]}],
                "conditionsLogic": "And",
            }
        )
    plan.win_triggers.append(
        {
            "comment": f"all {len(entity_sids)} monsters killed",
            "repeat": False,
            "conditions": [_counter_condition(counter_sid, "=", len(entity_sids))],
            "actions": _game_victory_actions(plan.mission_id),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"DEFEAT_ALL_MONSTERS → {len(entity_sids)} SquadKill counters")


def _plan_loss_hero(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    rows = _entities_matching(entities, position=position, payload_kinds=HERO_PAYLOADS)
    heroes = _pick_nearest_all(rows, position=position, context=f"{plan.mission_id} LOSSHERO")
    # Tied nearest heroes are intentional on multi-hero loss missions (e.g. Gem+Clancy):
    # losing any of them fails the scenario.
    for hero in heroes:
        hero_sid = _resolve_hero_sid(hero, context=f"{plan.mission_id} LOSSHERO")
        plan.loss_triggers.append(
            {
                "comment": f"LOSSHERO {hero_sid}",
                "repeat": False,
                "conditions": [{"comment": "", "c": "HeroKill", "p": [hero_sid], "counter": 1}],
                "actions": _game_lose_actions(),
                "conditionsLogic": "And",
            }
        )
        plan.evidence.append(f"LOSSHERO → HeroKill {hero_sid}")


def _plan_loss_castle(
    plan: VictoryPlan,
    *,
    entities: list[dict[str, Any]],
    position: dict[str, Any],
) -> None:
    town = _require_position_entity(
        entities,
        position=position,
        payload_kinds=TOWN_PAYLOADS,
        context=f"{plan.mission_id} LOSSCASTLE",
    )
    object_id = _object_id(town, context=f"{plan.mission_id} LOSSCASTLE")
    entity_sid = f"{plan.mission_id}_loss_castle"
    plan.prop_entity_bindings.append(
        PropEntityBinding(
            object_id=object_id,
            entity_sid=entity_sid,
            role="loss_castle",
            source_key=str(town.get("sourceKey") or ""),
        )
    )
    plan.loss_triggers.append(
        {
            "comment": f"LOSSCASTLE {entity_sid}",
            "repeat": False,
            "conditions": [{"comment": "", "c": "ObjectLose", "p": [entity_sid], "counter": 1}],
            "actions": _game_lose_actions(),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"LOSSCASTLE → ObjectLose {entity_sid}")


def _plan_loss_time(plan: VictoryPlan, *, days: int) -> None:
    if days <= 0:
        raise CampaignVictoryError(f"{plan.mission_id}: TIMEEXPIRES days must be > 0")
    plan.loss_triggers.append(
        {
            "comment": f"TIMEEXPIRES after {days} days",
            "repeat": False,
            "conditions": [
                start_turn_condition(days + 1, context=f"{plan.mission_id} TIMEEXPIRES")
            ],
            "actions": _game_lose_actions(),
            "conditionsLogic": "And",
        }
    )
    plan.evidence.append(f"TIMEEXPIRES → StartTurn day {days + 1}")


def apply_victory_prop_entities(
    properties: dict[str, Any],
    plan: VictoryPlan,
) -> dict[str, Any]:
    """Stamp plan propEntities bindings; fail closed on conflicting SIDs for same id."""

    prop_entities = properties.setdefault("propEntities", [])
    if not isinstance(prop_entities, list):
        raise CampaignVictoryError("objectsProperties.propEntities must be a list")
    by_id: dict[int, dict[str, Any]] = {}
    for row in prop_entities:
        if isinstance(row, dict) and isinstance(row.get("id"), int):
            by_id[int(row["id"])] = row
    applied: list[dict[str, Any]] = []
    for binding in plan.prop_entity_bindings:
        existing = by_id.get(binding.object_id)
        if existing is not None:
            existing_sid = existing.get("sid")
            if existing_sid and existing_sid != binding.entity_sid:
                # Featured-city capture SIDs may already own the town id; reuse them
                # by rewriting win triggers that target our provisional sid.
                _rewrite_entity_sid(plan, old=binding.entity_sid, new=str(existing_sid))
                applied.append(
                    {
                        "objectId": binding.object_id,
                        "entitySid": existing_sid,
                        "role": binding.role,
                        "reusedExisting": True,
                    }
                )
                continue
            existing["sid"] = binding.entity_sid
            existing["type"] = existing.get("type", 0)
        else:
            row = {"type": 0, "id": binding.object_id, "sid": binding.entity_sid}
            prop_entities.append(row)
            by_id[binding.object_id] = row
        applied.append(
            {
                "objectId": binding.object_id,
                "entitySid": binding.entity_sid,
                "role": binding.role,
                "sourceKey": binding.source_key,
            }
        )
    return {
        "type": plan.victory_name,
        "allowNormalVictory": plan.allow_normal_victory,
        "bindings": applied,
        "evidence": list(plan.evidence),
    }


def _rewrite_entity_sid(plan: VictoryPlan, *, old: str, new: str) -> None:
    blob_triggers = plan.win_triggers + plan.loss_triggers
    for trigger in blob_triggers:
        for condition in trigger.get("conditions") or []:
            params = condition.get("p")
            if isinstance(params, list):
                condition["p"] = [new if item == old else item for item in params]


def ownership_victory_from_plan(plan: VictoryPlan) -> dict[str, Any] | None:
    """Legacy adapter for TAKEDWELLINGS-shaped ownership_victory consumers."""

    dwelling_sids = [
        binding.entity_sid
        for binding in plan.prop_entity_bindings
        if binding.role == "dwelling"
    ]
    if plan.victory_name == "TAKEDWELLINGS" and dwelling_sids:
        return {"type": "TAKEDWELLINGS", "entitySids": dwelling_sids}
    return None
