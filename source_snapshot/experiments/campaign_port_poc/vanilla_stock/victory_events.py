"""Stock-legal victory quests and map-event emit helpers for vanilla_stock."""

from __future__ import annotations

from typing import Any

import campaign_runtime_script as runtime_script
import h3m_format as h3m
import h3m_object_registry as h3obj

from .h3_artifact_stock_map import stock_item_sid_for_h3_artifact_id
from .stock_neutral_strength import (
    StockNeutralStrengthError,
    stock_guard_requested_value as calibrated_guard_requested_value,
    stock_random_squad_requested_value as calibrated_random_squad_requested_value,
)

STOCK_MAP_EVENT_MARKER_SID = "Zone 1x1"
STOCK_MAP_EVENT_GUARD_SID = "random-squad"
STOCK_MAP_EVENT_DECO_SID = "fx_quest_mark_gold_01"
STOCK_EVENT_RELOCATE_MAX_CHEBYSHEV = 12
MINES_OWNED_COUNTER_SID = "mines_owned"
MAIN_QUEST_SID = "MainQuest"


class VanillaStockVictoryError(ValueError):
    """Fail-closed victory / event contract error."""


def playable_player_indices(header: dict[str, Any]) -> list[int]:
    players = header.get("players") or []
    out: list[int] = []
    for row in players:
        if isinstance(row, dict) and row.get("playable"):
            out.append(int(row["index"]))
    return out


def human_capable_player_indices(header: dict[str, Any]) -> list[int]:
    players = header.get("players") or []
    out: list[int] = []
    for row in players:
        if isinstance(row, dict) and row.get("playable") and row.get("canHuman"):
            out.append(int(row["index"]))
    return out


def clear_template_win_and_quest_leftovers(
    *,
    meta: dict[str, Any],
    map_data: dict[str, Any],
    props: dict[str, Any],
) -> None:
    """Strip Thirst/template quest + win leftovers before intentional emit."""

    settings = map_data.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise VanillaStockVictoryError("map settings must be an object")
    settings["mapWinConditions"] = []
    settings["endController"] = 0
    settings["isScenario"] = True
    settings["gameMode"] = 0
    # Allow auto-battle vs neutrals/guards; block auto vs enemy heroes.
    settings["disableAutoBattleAgainstEnemyHeroes"] = True

    start_settings = meta.setdefault("startSettings", {})
    if not isinstance(start_settings, dict):
        raise VanillaStockVictoryError("meta startSettings must be an object")
    # DefeatAll is set intentionally by apply_victory_contract.
    start_settings["DefeatAllEnemiesEnabled"] = False

    meta["endController"] = 0
    meta["isScenario"] = True
    meta["gameMode"] = 0
    meta["displayWinCondition"] = ""
    if not isinstance(meta.get("campaignInfo"), dict):
        raise VanillaStockVictoryError("meta campaignInfo must preserve the stock scenario object")

    for key in (
        "propEntities",
        "propActionsBefore",
        "propActionsAfter",
        "propActivations",
        "propMarkers",
        "propRewardParams",
        "propQuestMarkers",
        "propQuestNames",
        "propDialogWindows",
    ):
        props[key] = []


def _counter_row(sid: str, *, comment: str, value: int = 0) -> dict[str, Any]:
    return {
        "comment": comment,
        "sid": sid,
        "sharing": "Clone",
        "value": value,
        "minValue": -2147483648,
        "maxValue": 2147483647,
    }


def _player_defeated_condition(olden_owner: int) -> dict[str, Any]:
    # Olden QuestScript uses 1-based side indices in Thirst (owner 1 → "1").
    if not isinstance(olden_owner, int) or olden_owner < 1:
        raise VanillaStockVictoryError(
            f"PlayerDefeated requires final native owner >= 1; got {olden_owner!r}"
        )
    return {
        "comment": "",
        "p": [str(olden_owner)],
        "counter": 1,
        "c": "PlayerDefeated",
    }


def build_winstandard_quest_script(
    *,
    map_title: str,
    header: dict[str, Any],
    h3_color_to_final_owners: dict[int, list[int]] | None = None,
) -> dict[str, Any]:
    """Thirst-style: when every other playable side is defeated → GameVictory."""

    playable = playable_player_indices(header)
    humans = human_capable_player_indices(header)
    if not humans:
        raise VanillaStockVictoryError("WINSTANDARD requires at least one human-capable H3 player")
    if len(playable) < 2:
        raise VanillaStockVictoryError(
            "WINSTANDARD quest requires at least two playable H3 players to defeat"
        )
    mapping = h3_color_to_final_owners or {}
    if not mapping:
        # Legacy color+1 fallback is intentionally refused: compact ownership is required.
        raise VanillaStockVictoryError(
            "WINSTANDARD requires h3_color_to_final_owners from ownership contract"
        )

    def finals_for(h3_colors: list[int]) -> list[int]:
        out: list[int] = []
        for color in h3_colors:
            mapped = mapping.get(int(color))
            if not mapped:
                raise VanillaStockVictoryError(
                    f"WINSTANDARD H3 color {color} missing from ownership mapping"
                )
            for owner in mapped:
                if owner not in out:
                    out.append(owner)
        return sorted(out)

    human_finals = finals_for(humans)
    if 1 not in human_finals:
        raise VanillaStockVictoryError(
            f"WINSTANDARD human finals {human_finals} must include compact owner 1"
        )
    all_finals = finals_for(playable)

    subquests: list[dict[str, Any]] = []
    for human_owner in human_finals:
        others = [owner for owner in all_finals if owner != human_owner]
        if not others:
            continue
        conditions = [_player_defeated_condition(owner) for owner in others]
        subquests.append(
            {
                "sid": f"MainQuest_defeat_as_p{human_owner}",
                "activeOnStart": True,
                "hidden": False,
                "name": "Defeat all enemies",
                "desc": "",
                "comment": (
                    f"WINSTANDARD: native owner {human_owner} wins when other "
                    f"playable sides are defeated"
                ),
                "triggers": [
                    {
                        "comment": "",
                        "repeat": False,
                        "conditions": conditions,
                        "actions": [
                            {"comment": "", "p": [], "a": "CurrentSubQuestDone"},
                            {"comment": "", "p": [], "a": "GameVictory"},
                        ],
                        "conditionsLogic": "And",
                    }
                ],
            }
        )
    if not subquests:
        raise VanillaStockVictoryError("WINSTANDARD produced no PlayerDefeated subquests")

    quest = {
        "sid": MAIN_QUEST_SID,
        "activeOnStart": True,
        "comment": "vanilla_stock WINSTANDARD → DefeatAll + PlayerDefeated → GameVictory",
        "main": True,
        "hidden": False,
        "name": "Defeat all enemies",
        "desc": f"Capture all enemy towns and defeat all enemy heroes on {map_title}.",
        "sharing": "Clone",
        "subQuests": subquests,
    }
    return {
        "counters": [],
        "quests": [quest],
        "objectiveText": quest["desc"],
        "defeatAllEnemiesEnabled": True,
        "humanFinalOwners": human_finals,
        "playableFinalOwners": all_finals,
    }


def build_takemines_quest_script(
    *,
    map_title: str,
    mine_entity_sids: list[str],
    allow_normal_victory: bool,
) -> dict[str, Any]:
    """Glittering-style mine capture counter → GameVictory; DefeatAll from allow_normal_win."""

    if not mine_entity_sids:
        raise VanillaStockVictoryError("TAKEMINES requires at least one emitted mine entity")
    needed = len(mine_entity_sids)
    capture_triggers: list[dict[str, Any]] = []
    lose_triggers: list[dict[str, Any]] = []
    for entity_sid in mine_entity_sids:
        capture_triggers.append(
            {
                "comment": "",
                "repeat": True,
                "conditions": [
                    {
                        "comment": "",
                        "p": [entity_sid],
                        "counter": 1,
                        "c": "ObjectCaptureEntity",
                    }
                ],
                "actions": [
                    {
                        "comment": "",
                        "p": [MINES_OWNED_COUNTER_SID, "1"],
                        "a": "CounterPlus",
                    }
                ],
                "conditionsLogic": "And",
            }
        )
        lose_triggers.append(
            {
                "comment": "",
                "repeat": True,
                "conditions": [
                    {
                        "comment": "",
                        "p": [entity_sid],
                        "counter": 1,
                        "c": "ObjectLose",
                    }
                ],
                "actions": [
                    {
                        "comment": "",
                        "p": [MINES_OWNED_COUNTER_SID, "1"],
                        "a": "CounterMinus",
                    }
                ],
                "conditionsLogic": "And",
            }
        )

    victory_trigger = {
        "comment": "",
        "repeat": False,
        "conditions": [
            {
                "comment": "",
                "p": [MINES_OWNED_COUNTER_SID, "=", str(needed)],
                "counter": 1,
                "c": "Counter",
            }
        ],
        "actions": [
            {"comment": "", "p": [], "a": "CurrentSubQuestDone"},
            {"comment": "", "p": [], "a": "GameVictory"},
        ],
        "conditionsLogic": "And",
    }

    quest = {
        "sid": MAIN_QUEST_SID,
        "activeOnStart": True,
        "comment": "vanilla_stock TAKEMINES → ObjectCaptureEntity/ObjectLose counter → GameVictory",
        "main": True,
        "hidden": False,
        "name": "Flag all mines",
        "desc": f"Control all {needed} mines on {map_title}.",
        "sharing": "Clone",
        "subQuests": [
            {
                "sid": "MainQuest_mines_track",
                "activeOnStart": True,
                "hidden": False,
                "name": "Capture mines",
                "desc": "",
                "comment": "",
                "triggers": capture_triggers + lose_triggers,
            },
            {
                "sid": "MainQuest_mines_victory",
                "activeOnStart": True,
                "hidden": False,
                "name": "Hold every mine",
                "desc": "",
                "comment": "",
                "triggers": [victory_trigger],
            },
        ],
    }
    return {
        "counters": [
            _counter_row(
                MINES_OWNED_COUNTER_SID,
                comment="counting mines under the local player's control",
            )
        ],
        "quests": [quest],
        "objectiveText": quest["desc"],
        "defeatAllEnemiesEnabled": bool(allow_normal_victory),
        "mineEntityCount": needed,
        "mineEntitySids": list(mine_entity_sids),
    }


def apply_victory_contract(
    *,
    header: dict[str, Any],
    map_title: str,
    meta: dict[str, Any],
    map_data: dict[str, Any],
    props: dict[str, Any],
    emitted_mine_object_ids: list[int],
    source_mine_record_count: int,
    h3_color_to_final_owners: dict[int, list[int]] | None = None,
) -> dict[str, Any]:
    """Clear leftovers and emit intentional victory for supported H3 conditions."""

    clear_template_win_and_quest_leftovers(meta=meta, map_data=map_data, props=props)
    victory = header.get("victory") or {}
    victory_type = int(victory.get("type"))
    victory_name = str(victory.get("name") or "")

    if victory_type == h3m.VICTORY_WINSTANDARD:
        built = build_winstandard_quest_script(
            map_title=map_title,
            header=header,
            h3_color_to_final_owners=h3_color_to_final_owners,
        )
        mode = "WINSTANDARD"
    elif victory_type == h3m.VICTORY_TAKEMINES:
        if source_mine_record_count <= 0:
            raise VanillaStockVictoryError("TAKEMINES map has no mine/abandoned-mine object records")
        if len(emitted_mine_object_ids) != source_mine_record_count:
            raise VanillaStockVictoryError(
                "TAKEMINES mine entity coverage incomplete: "
                f"emitted {len(emitted_mine_object_ids)} of {source_mine_record_count} source mine records"
            )
        entity_sids = [f"mine{i + 1}" for i in range(len(emitted_mine_object_ids))]
        for object_id, entity_sid in zip(emitted_mine_object_ids, entity_sids):
            props.setdefault("propEntities", []).append(
                {"type": 0, "id": int(object_id), "sid": entity_sid}
            )
        allow_normal = bool(victory.get("allowNormalVictory"))
        built = build_takemines_quest_script(
            map_title=map_title,
            mine_entity_sids=entity_sids,
            allow_normal_victory=allow_normal,
        )
        mode = "TAKEMINES"
    else:
        raise VanillaStockVictoryError(
            f"vanilla_stock pilot does not yet emit victory condition {victory_name} ({victory_type}); "
            "extend after WINSTANDARD/TAKEMINES pilot is solid"
        )

    start_settings = meta.setdefault("startSettings", {})
    start_settings["DefeatAllEnemiesEnabled"] = bool(built["defeatAllEnemiesEnabled"])
    meta["displayWinCondition"] = str(built.get("objectiveText") or "")
    map_data["mapDesc"] = meta.get("desc") or map_data.get("mapDesc") or ""

    return {
        "mode": mode,
        "victoryName": victory_name,
        "allowNormalVictory": victory.get("allowNormalVictory"),
        "lossName": (header.get("loss") or {}).get("name"),
        "defeatAllEnemiesEnabled": built["defeatAllEnemiesEnabled"],
        "objectiveText": built.get("objectiveText"),
        "counters": built.get("counters") or [],
        "quests": built.get("quests") or [],
        "mineEntityCount": built.get("mineEntityCount"),
        "mineEntitySids": built.get("mineEntitySids"),
        "humanFinalOwners": built.get("humanFinalOwners"),
        "playableFinalOwners": built.get("playableFinalOwners"),
    }


def h3_players_mask_to_sides(
    players_mask: Any,
    *,
    h3_color_to_final_owners: dict[int, list[int]] | None = None,
) -> str:
    """Encode H3 playersMask for propActions*.sides using final native owners.

    Native Story/custom maps use ``sides: \"\"`` for all-players Dialog hosts.
    Partial masks use zero-based CSV of final owners (owner 1 → \"0\").
    """

    if not isinstance(players_mask, int) or players_mask <= 0:
        return ""
    if players_mask == 255:
        return ""
    if not h3_color_to_final_owners:
        raise VanillaStockVictoryError(
            "map event sides require h3_color_to_final_owners from ownership contract"
        )
    from .ownership_contract import (
        VanillaStockOwnershipError,
        translate_h3_players_mask_to_final_sides,
    )

    try:
        return translate_h3_players_mask_to_final_sides(
            players_mask,
            h3_color_to_final_owners=h3_color_to_final_owners,
        )
    except VanillaStockOwnershipError as ex:
        raise VanillaStockVictoryError(str(ex)) from ex


def stock_random_squad_property_row(
    object_id: int,
    *,
    requested_value: float,
    reaction_type: int = 2,
    never_flees: bool = False,
    not_growing: bool = False,
) -> dict[str, Any]:
    """Stock-native propRandomSquads row (fraction must be string, not float)."""

    if float(requested_value) <= 0:
        raise VanillaStockVictoryError(
            f"propRandomSquads id={object_id} requestedValue must be > 0, got {requested_value}"
        )
    return {
        "type": 0,
        "id": int(object_id),
        "sids": [],
        "requestedValue": float(requested_value),
        "fraction": "",
        "tier": 0,
        "isMainGuard": False,
        "reactionType": int(reaction_type),
        "customTopUnit": "",
        "weeklyIncrementBonus": 0.0,
        "diplomacyUnitsCountBonus": 0.0,
        "isEscape": False,
        # Neutrals/guards: allow adventure-map auto-battle. Enemy-hero auto is
        # gated separately via settings.disableAutoBattleAgainstEnemyHeroes.
        "isAutobatle": True,
        "isFreeDiplomacy": False,
        "isCampaignFreeDiplomacy": False,
        "isCampaignDiplomacy": False,
        "isIgnoreMultiply": bool(not_growing),
        "obstruction": "",
        "customStacks": 0,
        "neverFlees": bool(never_flees),
        "notGrowingTeam": bool(not_growing),
    }


def map_event_entity_sid(map_sid: str, object_id: int) -> str:
    return f"{map_sid}_map_event_{object_id}"


def map_event_dialog_sid(map_sid: str, object_id: int) -> str:
    return f"{map_sid}_map_event_{object_id}_dialog"


def map_event_visited_counter_sid(map_sid: str, object_id: int) -> str:
    return f"{map_sid}_map_event_{object_id}_visited"


def map_event_quest_sid(map_sid: str, object_id: int) -> str:
    return f"{map_sid}_map_event_{object_id}"


def classify_map_event_guards(record: dict[str, Any]) -> dict[str, Any]:
    """Return nonempty guard stacks when H3 hasGuards is true with real creatures.

    Empty 0xFFFF-only slots demote to unguarded (same as campaign EventIR).
    HotA-only creatureTypes absent from the baked stock strength model force a
    named omit — stock cannot invent a SpawnsCreator budget for unknown units.
    """

    source_key = str(record.get("key") or record.get("sourceKey") or record.get("index"))
    box = record.get("boxContent") if isinstance(record.get("boxContent"), dict) else {}
    message_block = box.get("messageAndGuards") if isinstance(box, dict) else {}
    if not isinstance(message_block, dict):
        message_block = {}
    has_guards_flag = bool(message_block.get("hasGuards"))
    if not has_guards_flag:
        return {
            "hasGuards": False,
            "guardStacks": [],
            "hostSid": STOCK_MAP_EVENT_MARKER_SID,
            "sourceKey": source_key,
        }
    stacks = runtime_script.nonempty_guard_stacks(
        message_block.get("guardStacks") or [],
        context=f"vanilla_stock map event {source_key}",
        allow_empty=True,
    )
    if not stacks:
        return {
            "hasGuards": False,
            "guardStacks": [],
            "hostSid": STOCK_MAP_EVENT_MARKER_SID,
            "sourceKey": source_key,
            "demotedEmptyGuards": True,
        }
    try:
        from .stock_neutral_strength import load_strength_model

        known = {
            int(k)
            for k in (load_strength_model().get("creatureTypeSquadValuesFromGe") or {})
        }
    except Exception as ex:  # noqa: BLE001
        raise VanillaStockVictoryError(
            f"strength model unreadable while classifying guards for {source_key}: {ex}"
        ) from ex
    unknown = sorted(
        {
            int(stack["creatureType"])
            for stack in stacks
            if isinstance(stack, dict)
            and isinstance(stack.get("creatureType"), int)
            and int(stack["creatureType"]) not in known
        }
    )
    if unknown:
        return {
            "hasGuards": False,
            "guardStacks": [],
            "hostSid": STOCK_MAP_EVENT_MARKER_SID,
            "sourceKey": source_key,
            "omit": True,
            "omitReason": f"hota_or_unmapped_guard_creature_types_{unknown}",
            "unknownCreatureTypes": unknown,
        }
    return {
        "hasGuards": True,
        "guardStacks": stacks,
        "hostSid": STOCK_MAP_EVENT_GUARD_SID,
        "sourceKey": source_key,
    }


def stock_guard_requested_value(stacks: list[dict[str, int]]) -> float:
    """Calibrated budget: sum(H3 count × GE ``h3_`` squadValue), rounded like campaign."""

    try:
        return calibrated_guard_requested_value(stacks)
    except StockNeutralStrengthError as ex:
        raise VanillaStockVictoryError(str(ex)) from ex


def stock_random_squad_requested_value(entity: dict[str, Any]) -> float:
    """Calibrated SpawnsCreator budget for H3 monster → stock ``random-squad``.

    Same magnitude model as campaign GE emit: ``count_or_nominal × squadValue``,
    with squadValue from the baked GE ``h3_`` snapshot in ``h3_neutral_strength_model.json``.
    """

    try:
        return calibrated_random_squad_requested_value(entity)
    except StockNeutralStrengthError as ex:
        raise VanillaStockVictoryError(str(ex)) from ex


def stock_monster_reaction_type(entity: dict[str, Any]) -> int:
    character = entity.get("character")
    if character == 0:
        return 4
    if character in (1, 2):
        return 2
    if character in (3, 4):
        return 0
    return 2


def node_xy(node: int, *, atlas_width: int) -> tuple[int, int]:
    return int(node % atlas_width), int(node // atlas_width)


def same_atlas_layer(node_a: int, node_b: int, *, atlas_width: int, layer_width: int) -> bool:
    ax, _ = node_xy(node_a, atlas_width=atlas_width)
    bx, _ = node_xy(node_b, atlas_width=atlas_width)
    return (ax // layer_width) == (bx // layer_width)


def zone_cell_is_landable(
    node: int,
    *,
    levels_map: list[int],
    climbs_map: list[int],
    occupied_nodes: set[int],
    envelope_nodes: set[int],
) -> bool:
    """Zone 1x1 must sit on a walkable in-envelope cell (not elevated cliff padding)."""

    if node not in envelope_nodes:
        return False
    if node in occupied_nodes:
        return False
    if int(levels_map[node]) != 0 and int(climbs_map[node]) == 0:
        return False
    return True


def relocate_unguarded_event_node(
    provisional_node: int,
    *,
    atlas_width: int,
    atlas_height: int,
    layer_width: int,
    levels_map: list[int],
    climbs_map: list[int],
    occupied_nodes: set[int],
    envelope_nodes: set[int],
    source_key: str,
    max_chebyshev: int = STOCK_EVENT_RELOCATE_MAX_CHEBYSHEV,
) -> dict[str, Any]:
    """Keep or move an unguarded Zone onto terrain heroes can step on.

    Fail closed when no same-layer in-envelope landable cell exists within radius.
    """

    total = atlas_width * atlas_height
    if not (0 <= provisional_node < total):
        raise VanillaStockVictoryError(
            f"map event {source_key}: provisional node {provisional_node} outside atlas"
        )

    def try_node(node: int) -> bool:
        if not same_atlas_layer(
            provisional_node, node, atlas_width=atlas_width, layer_width=layer_width
        ):
            return False
        return zone_cell_is_landable(
            node,
            levels_map=levels_map,
            climbs_map=climbs_map,
            occupied_nodes=occupied_nodes,
            envelope_nodes=envelope_nodes,
        )

    if try_node(provisional_node):
        return {
            "node": provisional_node,
            "relocated": False,
            "chebyshev": 0,
            "sourceKey": source_key,
            "policy": "zone_1x1_keep_source_when_landable",
        }

    px, py = node_xy(provisional_node, atlas_width=atlas_width)
    for radius in range(1, max_chebyshev + 1):
        candidates: list[tuple[int, int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                x, y = px + dx, py + dy
                if not (0 <= x < atlas_width and 0 <= y < atlas_height):
                    continue
                node = y * atlas_width + x
                if try_node(node):
                    candidates.append((y, x, node))
        if candidates:
            candidates.sort()
            chosen = candidates[0][2]
            return {
                "node": chosen,
                "relocated": True,
                "chebyshev": radius,
                "fromNode": provisional_node,
                "sourceKey": source_key,
                "policy": "zone_1x1_nearest_landable_same_layer_chebyshev",
            }

    raise VanillaStockVictoryError(
        f"map event {source_key}: no landable Zone 1x1 cell within Chebyshev "
        f"{max_chebyshev} of node {provisional_node} (terrain does not fit unguarded event)"
    )


def choose_event_deco_node(
    zone_node: int,
    *,
    atlas_width: int,
    atlas_height: int,
    layer_width: int,
    levels_map: list[int],
    climbs_map: list[int],
    occupied_nodes: set[int],
    envelope_nodes: set[int],
    source_key: str,
) -> int:
    """Place decorative gold FX near the Zone without covering the walkable host cell.

    Prefer one tile south (Olden +Y = north → y-1), matching the campaign probe map.
    Search expands to Chebyshev-2 on dense HotA maps before failing closed.
    """

    px, py = node_xy(zone_node, atlas_width=atlas_width)
    # South, north, east, west at radius 1, then the rest of Chebyshev-1, then Chebyshev-2.
    preferred = [(0, -1), (0, 1), (1, 0), (-1, 0)]
    offsets: list[tuple[int, int]] = []
    for radius in (1, 2):
        ring: list[tuple[int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                if radius == 1 and (dx, dy) in preferred:
                    continue
                ring.append((dx, dy))
        if radius == 1:
            offsets.extend(preferred)
        offsets.extend(ring)
    for dx, dy in offsets:
        x, y = px + dx, py + dy
        if not (0 <= x < atlas_width and 0 <= y < atlas_height):
            continue
        node = y * atlas_width + x
        if not same_atlas_layer(zone_node, node, atlas_width=atlas_width, layer_width=layer_width):
            continue
        # Deco may sit on non-walkable scenery; only require empty envelope cell.
        if node not in envelope_nodes or node in occupied_nodes:
            continue
        return node
    raise VanillaStockVictoryError(
        f"map event {source_key}: no free Chebyshev-2 cell for {STOCK_MAP_EVENT_DECO_SID} deco "
        f"near Zone node {zone_node}"
    )


def choose_spawn_map_object_node(
    host_node: int,
    *,
    atlas_width: int,
    atlas_height: int,
    layer_width: int,
    levels_map: list[int],
    climbs_map: list[int],
    occupied_nodes: set[int],
    envelope_nodes: set[int],
    source_key: str,
) -> int:
    """Pick a landable adjacent cell for SpawnMapObject artifact delivery."""

    px, py = node_xy(host_node, atlas_width=atlas_width)
    for radius in range(1, 4):
        candidates: list[tuple[int, int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                x, y = px + dx, py + dy
                if not (0 <= x < atlas_width and 0 <= y < atlas_height):
                    continue
                node = y * atlas_width + x
                if not same_atlas_layer(
                    host_node, node, atlas_width=atlas_width, layer_width=layer_width
                ):
                    continue
                if not zone_cell_is_landable(
                    node,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                    occupied_nodes=occupied_nodes,
                    envelope_nodes=envelope_nodes,
                ):
                    continue
                candidates.append((abs(dx) + abs(dy), dx * dx + dy * dy, node))
        if candidates:
            candidates.sort()
            return candidates[0][2]
    raise VanillaStockVictoryError(
        f"map event {source_key}: no landable cell for SpawnMapObject artifact near node {host_node}"
    )


def _spawn_map_object_action(*, item_sid: str, node: int) -> dict[str, Any]:
    return {"comment": "", "a": "SpawnMapObject", "p": [item_sid, str(int(node)), "0"]}


def _artifact_and_mana_reward_actions(
    rewards_raw: Any,
    *,
    host_node: int | None,
    atlas_width: int | None,
    atlas_height: int | None,
    layer_width: int | None,
    levels_map: list[int] | None,
    climbs_map: list[int] | None,
    occupied_nodes: set[int],
    envelope_nodes: set[int],
    source_key: str,
    object_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Port mapped H3 artifacts via SpawnMapObject; mana stays a named gap (no AddMana donor)."""

    actions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    spawned_sids: list[str] = []
    if not isinstance(rewards_raw, dict):
        return actions, gaps, spawned_sids

    mana = runtime_script._signed_h3_reward_int(rewards_raw.get("mana"))
    if mana not in (None, 0, 0.0, "", [], {}):
        if isinstance(mana, (int, float)) and int(mana) != 0:
            gaps.append(
                {
                    "sourceKey": source_key,
                    "objectId": object_id,
                    "omit": f"mana={int(mana)}",
                    "reason": (
                        "stock maps prove ChangeManaHero only with a named hero entity SID; "
                        "no AddMana / interacting-hero mana donor for map-event visits"
                    ),
                }
            )

    artifacts = rewards_raw.get("artifacts") or []
    if not artifacts:
        return actions, gaps, spawned_sids
    if not isinstance(artifacts, list):
        raise VanillaStockVictoryError(f"{source_key}: artifacts reward must be a list")
    if (
        host_node is None
        or atlas_width is None
        or atlas_height is None
        or layer_width is None
        or levels_map is None
        or climbs_map is None
    ):
        raise VanillaStockVictoryError(
            f"{source_key}: artifact SpawnMapObject requires host node and terrain maps"
        )

    for raw_id in artifacts:
        artifact_id = int(raw_id)
        item_sid = stock_item_sid_for_h3_artifact_id(artifact_id)
        if item_sid is None:
            gaps.append(
                {
                    "sourceKey": source_key,
                    "objectId": object_id,
                    "omit": f"artifacts=[{artifact_id}]",
                    "reason": "no_exact_stock_item_sid_for_h3_artifact_id",
                }
            )
            continue
        spawn_node = choose_spawn_map_object_node(
            int(host_node),
            atlas_width=int(atlas_width),
            atlas_height=int(atlas_height),
            layer_width=int(layer_width),
            levels_map=levels_map,
            climbs_map=climbs_map,
            occupied_nodes=occupied_nodes,
            envelope_nodes=envelope_nodes,
            source_key=source_key,
        )
        occupied_nodes.add(spawn_node)
        actions.append(_spawn_map_object_action(item_sid=item_sid, node=spawn_node))
        spawned_sids.append(item_sid)
    return actions, gaps, spawned_sids


def build_inline_dialog_document(*, dialog_sid: str, title: str, body: str) -> dict[str, Any]:
    """Stock Core dialog row with localization:false so text needs no Loc tokens."""

    return {
        "array": [
            {
                "id": dialog_sid,
                "localization": False,
                "slides": [
                    {
                        "id": "start",
                        "fon": "",
                        "avatars": {"icons": []},
                        "title": title or "Event",
                        "text": body or "(empty event message)",
                        "end": True,
                        "resultDialog": "Default",
                    }
                ],
            }
        ]
    }


def _signed_resource_list(resources: Any) -> list[int]:
    if not isinstance(resources, list):
        return [0] * 7
    return [int(runtime_script._signed_h3_reward_int(value) or 0) for value in resources]


def _build_unguarded_visit_triggers(
    *,
    entity_sid: str,
    visited_counter: str,
    reward_actions: list[dict[str, Any]],
    action_repeat: bool,
) -> list[dict[str, Any]]:
    actions = [runtime_script._counter_set(visited_counter, 1)]
    actions.extend(reward_actions)
    return [
        {
            "comment": (
                f"record visit for {entity_sid} without duplicating Dialog"
                + ("; rewards after visit" if reward_actions else "")
            ),
            "repeat": action_repeat,
            "conditions": [runtime_script._object_interaction_after(entity_sid)],
            "actions": actions,
            "conditionsLogic": "And",
        }
    ]


def _build_guarded_quest_triggers(
    *,
    entity_sid: str,
    dialog_sid: str,
    message: str,
    visited_counter: str,
    reward_actions: list[dict[str, Any]],
    remove_after_visit: bool,
) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    if message:
        triggers.append(
            {
                "comment": f"SquadInteraction pre-battle dialog for {entity_sid}",
                "repeat": True,
                "conditions": [
                    {"comment": "", "c": "SquadInteraction", "p": [entity_sid], "counter": 1}
                ],
                "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
                "conditionsLogic": "And",
            }
        )
    kill_actions: list[dict[str, Any]] = list(reward_actions)
    kill_actions.append(runtime_script._counter_set(visited_counter, 1))
    if remove_after_visit:
        kill_actions.append({"comment": "", "a": "DeleteEntity", "p": [entity_sid]})
    triggers.append(
        {
            "comment": f"SquadKill rewards for {entity_sid}",
            "repeat": False,
            "conditions": [{"comment": "", "c": "SquadKill", "p": [entity_sid], "counter": 1}],
            "actions": kill_actions,
            "conditionsLogic": "And",
        }
    )
    return triggers


def apply_map_events(
    *,
    map_sid: str,
    map_title: str,
    event_records: list[dict[str, Any]],
    props: dict[str, Any],
    provisional_nodes: dict[int, int] | None = None,
    host_nodes: dict[int, int] | None = None,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
    occupied_nodes: set[int] | None = None,
    envelope_nodes: set[int] | None = None,
    atlas_width: int | None = None,
    atlas_height: int | None = None,
    layer_width: int | None = None,
    first_marker_id: int = 1,
    h3_color_to_final_owners: dict[int, list[int]] | None = None,
) -> dict[str, Any]:
    """Wire campaign-parity map events on stock hosts (Zone 1x1 / random-squad).

    Unguarded: invisible ``Zone 1x1`` markers + gold FX deco + type-1 Dialog Before +
    QuestScript ``ObjectInteractionAfter`` → GiveRes/RemoveRes/SpawnMapObject.
    Guarded: ``random-squad`` + ``SquadInteraction`` / ``SquadKill``. Dialog JSON
    lives under optional_core_overlay_for_events/ (text only).
    """

    empty = {
        "eventCount": 0,
        "unguardedCount": 0,
        "guardedCount": 0,
        "placedObjectIds": [],
        "unguardedObjectIds": [],
        "unguardedMarkerIds": [],
        "guardedObjectIds": [],
        "markers": [],
        "decoPlacements": [],
        "relocations": [],
        "dialogDocuments": [],
        "counters": [],
        "quests": [],
        "omittedRewardGaps": [],
        "giveResActionCount": 0,
        "removeResActionCount": 0,
        "spawnMapObjectActionCount": 0,
        "coreDialogInstallRequired": False,
        "notes": ["no OBJECT_EVENT tiles in this H3M"],
        "markerSid": STOCK_MAP_EVENT_MARKER_SID,
        "guardSid": STOCK_MAP_EVENT_GUARD_SID,
        "decoSid": STOCK_MAP_EVENT_DECO_SID,
    }
    if not event_records:
        return empty

    provisional_nodes = dict(provisional_nodes or {})
    host_nodes = dict(host_nodes or {})
    occupied_live = set(occupied_nodes or ())
    envelope_nodes = set(envelope_nodes or ())
    dialog_documents: list[dict[str, Any]] = []
    placed_ids: list[int] = []
    unguarded_ids: list[int] = []
    unguarded_marker_ids: list[int] = []
    guarded_ids: list[int] = []
    markers: list[dict[str, Any]] = []
    deco_placements: list[dict[str, Any]] = []
    relocations: list[dict[str, Any]] = []
    counters: list[dict[str, Any]] = []
    quests: list[dict[str, Any]] = []
    omitted_gaps: list[dict[str, Any]] = []
    notes: list[str] = []
    give_res_action_count = 0
    remove_res_action_count = 0
    spawn_map_object_action_count = 0
    next_marker_id = int(first_marker_id)

    for record in event_records:
        object_id = int(record["index"])
        source_key = str(record.get("key") or record.get("sourceKey") or object_id)
        context = f"vanilla_stock map event {source_key}"
        box = record.get("boxContent") if isinstance(record.get("boxContent"), dict) else {}
        message_block = box.get("messageAndGuards") if isinstance(box, dict) else {}
        if not isinstance(message_block, dict):
            message_block = {}
        message = str(message_block.get("message") or "").strip()
        remove_after_visit = bool(record.get("removeAfterVisit"))
        if "removeAfterVisit" not in record and isinstance(box, dict) and "removeAfterVisit" in box:
            remove_after_visit = bool(box.get("removeAfterVisit"))

        guard_info = classify_map_event_guards(record)
        is_guarded = bool(guard_info["hasGuards"])
        guard_stacks = list(guard_info.get("guardStacks") or [])

        rewards_raw = box.get("rewards") if isinstance(box, dict) else None
        cleaned_rewards, omitted_fields = runtime_script.take_resource_rewards_for_alignment(
            rewards_raw if isinstance(rewards_raw, dict) else {},
            context=context,
        )
        for field in omitted_fields:
            if str(field).startswith("artifacts=") or str(field).startswith("mana="):
                continue
            omitted_gaps.append(
                {
                    "sourceKey": source_key,
                    "objectId": object_id,
                    "omit": field,
                    "reason": "non_resource_reward_not_ported_on_stock",
                }
            )

        resources = _signed_resource_list(
            (cleaned_rewards or {}).get("resources") if isinstance(cleaned_rewards, dict) else None
        )
        reward_actions: list[dict[str, Any]] = []
        if any(amount != 0 for amount in resources):
            deltas = runtime_script.resource_delta_actions_from_h3_resources(
                resources,
                context=context,
            )
            reward_actions.extend(deltas)
            give_res_action_count += sum(1 for a in deltas if a.get("a") == "GiveRes")
            remove_res_action_count += sum(1 for a in deltas if a.get("a") == "RemoveRes")

        has_pending_art_or_mana = isinstance(rewards_raw, dict) and bool(
            rewards_raw.get("artifacts") or rewards_raw.get("mana")
        )
        if not message and not reward_actions and not is_guarded and not has_pending_art_or_mana:
            notes.append(f"skipped empty noop map event {source_key}")
            continue
        if not message and not is_guarded:
            # Dialog hosts require non-empty text. HotA maps sometimes ship reward
            # events with blank messages — omit with a named gap rather than invent copy.
            omitted_gaps.append(
                {
                    "sourceKey": source_key,
                    "objectId": object_id,
                    "omit": "unguarded_event_empty_message",
                    "reason": "dialog_host_requires_text_blank_h3m_message",
                    "hadRewardActions": bool(reward_actions) or has_pending_art_or_mana,
                }
            )
            notes.append(f"omitted blank-message unguarded map event {source_key}")
            continue

        entity_sid = map_event_entity_sid(map_sid, object_id)
        dialog_sid = map_event_dialog_sid(map_sid, object_id)
        visited_counter = map_event_visited_counter_sid(map_sid, object_id)
        quest_sid = map_event_quest_sid(map_sid, object_id)
        sides = h3_players_mask_to_sides(
            record.get("playersMask"),
            h3_color_to_final_owners=h3_color_to_final_owners,
        )
        computer_activate = bool(record.get("computerActivate"))
        if computer_activate is False and sides == "" and int(record.get("playersMask") or 0) == 0:
            raise VanillaStockVictoryError(
                f"map event {source_key} has computerActivate=False but empty playersMask"
            )
        # computerActivate is NOT a PropActionsBase field (audience_encode); never emit it.

        counters.append(
            _counter_row(visited_counter, comment=f"visit latch for map event {source_key}")
        )

        if is_guarded:
            guarded_ids.append(object_id)
            host_node = host_nodes.get(object_id)
            if host_node is None:
                raise VanillaStockVictoryError(
                    f"guarded map event {source_key} missing host_nodes atlas node"
                )
            art_actions, art_gaps, _spawned = _artifact_and_mana_reward_actions(
                rewards_raw,
                host_node=int(host_node),
                atlas_width=atlas_width,
                atlas_height=atlas_height,
                layer_width=layer_width,
                levels_map=levels_map,
                climbs_map=climbs_map,
                occupied_nodes=occupied_live,
                envelope_nodes=envelope_nodes,
                source_key=source_key,
                object_id=object_id,
            )
            omitted_gaps.extend(art_gaps)
            reward_actions.extend(art_actions)
            spawn_map_object_action_count += len(art_actions)
            props.setdefault("propEntities", []).append(
                {"type": 0, "id": object_id, "sid": entity_sid}
            )
            props.setdefault("propRandomSquads", []).append(
                stock_random_squad_property_row(
                    object_id,
                    requested_value=stock_guard_requested_value(guard_stacks),
                    reaction_type=2,
                )
            )
            triggers = _build_guarded_quest_triggers(
                entity_sid=entity_sid,
                dialog_sid=dialog_sid,
                message=message,
                visited_counter=visited_counter,
                reward_actions=reward_actions,
                remove_after_visit=remove_after_visit,
            )
            comment = (
                "H3M guarded map event: SquadInteraction → Dialog; "
                "SquadKill → GiveRes/RemoveRes/SpawnMapObject; stock random-squad host"
            )
        else:
            if (
                levels_map is None
                or climbs_map is None
                or atlas_width is None
                or atlas_height is None
                or layer_width is None
            ):
                raise VanillaStockVictoryError(
                    f"unguarded map event {source_key} requires terrain maps and atlas dims "
                    "for Zone 1x1 landability"
                )
            if object_id not in provisional_nodes:
                raise VanillaStockVictoryError(
                    f"unguarded map event {source_key} missing provisional atlas node"
                )
            placement = relocate_unguarded_event_node(
                int(provisional_nodes[object_id]),
                atlas_width=int(atlas_width),
                atlas_height=int(atlas_height),
                layer_width=int(layer_width),
                levels_map=levels_map,
                climbs_map=climbs_map,
                occupied_nodes=occupied_live,
                envelope_nodes=envelope_nodes,
                source_key=source_key,
            )
            relocations.append(placement)
            node = int(placement["node"])
            occupied_live.add(node)
            deco_node = choose_event_deco_node(
                node,
                atlas_width=int(atlas_width),
                atlas_height=int(atlas_height),
                layer_width=int(layer_width),
                levels_map=levels_map,
                climbs_map=climbs_map,
                occupied_nodes=occupied_live,
                envelope_nodes=envelope_nodes,
                source_key=source_key,
            )
            occupied_live.add(deco_node)
            deco_placements.append(
                {
                    "sourceKey": source_key,
                    "objectId": object_id,
                    "zoneNode": node,
                    "decoNode": deco_node,
                    "sid": STOCK_MAP_EVENT_DECO_SID,
                }
            )
            art_actions, art_gaps, _spawned = _artifact_and_mana_reward_actions(
                rewards_raw,
                host_node=node,
                atlas_width=atlas_width,
                atlas_height=atlas_height,
                layer_width=layer_width,
                levels_map=levels_map,
                climbs_map=climbs_map,
                occupied_nodes=occupied_live,
                envelope_nodes=envelope_nodes,
                source_key=source_key,
                object_id=object_id,
            )
            omitted_gaps.extend(art_gaps)
            reward_actions.extend(art_actions)
            spawn_map_object_action_count += len(art_actions)
            marker_id = next_marker_id
            next_marker_id += 1
            unguarded_ids.append(object_id)
            unguarded_marker_ids.append(marker_id)
            action_repeat = not remove_after_visit
            props.setdefault("propEntities", []).append(
                {"type": 1, "id": marker_id, "sid": entity_sid}
            )
            props.setdefault("propActionsBefore", []).append(
                {
                    "type": 1,
                    "id": marker_id,
                    "repeat": action_repeat,
                    "sides": sides,
                    "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
                }
            )
            after_actions: list[dict[str, Any]] = []
            if remove_after_visit:
                after_actions.append({"comment": "", "a": "DeleteEntity", "p": [entity_sid]})
            if after_actions:
                props.setdefault("propActionsAfter", []).append(
                    {
                        "type": 1,
                        "id": marker_id,
                        "repeat": False,
                        "sides": sides,
                        "actions": after_actions,
                    }
                )
            props.setdefault("propMarkers", []).append(
                {
                    "type": 1,
                    "id": marker_id,
                    "isDelete": remove_after_visit,
                    "isActivate": True,
                }
            )
            markers.append(
                {"node": node, "v": "", "sid": STOCK_MAP_EVENT_MARKER_SID, "id": marker_id}
            )
            triggers = _build_unguarded_visit_triggers(
                entity_sid=entity_sid,
                visited_counter=visited_counter,
                reward_actions=reward_actions,
                action_repeat=action_repeat,
            )
            comment = (
                "H3M map event visit tracked after marker Dialog; "
                "GiveRes/RemoveRes/SpawnMapObject on ObjectInteractionAfter; Zone 1x1 + gold deco"
            )

        quests.append(
            {
                "sid": quest_sid,
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": comment,
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{quest_sid}_visited",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": triggers,
                    }
                ],
                "subQuestGroups": [],
            }
        )

        if message:
            dialog_documents.append(
                {
                    "dialogSid": dialog_sid,
                    "relativeMember": f"DB/dialogs/dialogs/custom_maps/{map_sid}/{dialog_sid}.json",
                    "document": build_inline_dialog_document(
                        dialog_sid=dialog_sid,
                        title=map_title,
                        body=message,
                    ),
                    "sourceKey": source_key,
                    "message": message,
                    "hasGuards": is_guarded,
                    "playersMask": record.get("playersMask"),
                    "computerActivate": computer_activate,
                    "removeAfterVisit": remove_after_visit,
                    "giveResActionCount": sum(1 for a in reward_actions if a.get("a") == "GiveRes"),
                }
            )
        elif not is_guarded:
            raise VanillaStockVictoryError(
                f"unguarded map event {source_key} has no message; Dialog host requires text"
            )

        placed_ids.append(object_id)

    notes.append(
        "Unguarded EVENTs use Zone 1x1 markers + adjacent fx_quest_mark_gold_01 deco + "
        "Dialog Before + ObjectInteractionAfter rewards. Guarded EVENTs use random-squad + "
        "SquadInteraction/SquadKill. Mapped artifacts SpawnMapObject on visit; unmapped "
        "artifacts and mana stay named gaps. Negative resources use RemoveRes. "
        "Dialog SIDs need Core overlay merge. Runtime remains unvalidated."
    )
    return {
        "eventCount": len(placed_ids),
        "unguardedCount": len(unguarded_ids),
        "guardedCount": len(guarded_ids),
        "placedObjectIds": placed_ids,
        "unguardedObjectIds": unguarded_ids,
        "unguardedMarkerIds": unguarded_marker_ids,
        "guardedObjectIds": guarded_ids,
        "markers": markers,
        "decoPlacements": deco_placements,
        "relocations": relocations,
        "dialogDocuments": dialog_documents,
        "counters": counters,
        "quests": quests,
        "omittedRewardGaps": omitted_gaps,
        "giveResActionCount": give_res_action_count,
        "removeResActionCount": remove_res_action_count,
        "spawnMapObjectActionCount": spawn_map_object_action_count,
        "coreDialogInstallRequired": bool(dialog_documents),
        "notes": notes,
        "markerSid": STOCK_MAP_EVENT_MARKER_SID,
        "guardSid": STOCK_MAP_EVENT_GUARD_SID,
        "decoSid": STOCK_MAP_EVENT_DECO_SID,
    }


def apply_global_timed_events(
    *,
    map_sid: str,
    map_title: str,
    global_timed_events: dict[str, Any] | None,
) -> dict[str, Any]:
    """Emit StartTurn briefing Dialogs and calendar GiveRes/RemoveRes grants."""

    if not global_timed_events or int(global_timed_events.get("eventCount") or 0) == 0:
        return {
            "briefingCount": 0,
            "timedGrantCount": 0,
            "counters": [],
            "quests": [],
            "dialogDocuments": [],
            "omittedGaps": [],
            "notes": ["no H3M global timed events"],
        }

    partitioned = runtime_script.partition_global_timed_events(global_timed_events)
    briefings = list(partitioned.get("playerBriefings") or [])
    deferred = list(partitioned.get("deferredComputerOrResourceEvents") or [])
    grants, omitted = runtime_script.partition_timed_resource_grants_for_alignment(map_sid, deferred)

    dialog_documents: list[dict[str, Any]] = []
    counters: list[dict[str, Any]] = []
    quests: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []

    for index, briefing in enumerate(briefings):
        dialog_sid = f"{map_sid}_timed_briefing_{index}"
        body = str(briefing.get("message") or "").strip()
        title = str(briefing.get("name") or map_title).strip() or map_title
        if not body:
            raise VanillaStockVictoryError(f"timed briefing {index} missing message body")
        dialog_documents.append(
            {
                "dialogSid": dialog_sid,
                "relativeMember": f"DB/dialogs/dialogs/custom_maps/{map_sid}/{dialog_sid}.json",
                "document": build_inline_dialog_document(
                    dialog_sid=dialog_sid,
                    title=title,
                    body=body,
                ),
                "sourceKey": f"global:{briefing.get('index')}",
                "message": body,
            }
        )
        trigger_day = int(briefing.get("triggerDay") or 1)
        triggers.append(
            {
                "comment": f"H3M global timed briefing day {trigger_day}",
                "repeat": False,
                "conditions": [runtime_script._briefing_start_turn(trigger_day)],
                "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
                "conditionsLogic": "And",
            }
        )

    if grants:
        from campaign_event_ir.compile_backends import timed_resource_arm_counter_sid
        from campaign_event_ir.schedule_encode import timer_counter_row

        grant_triggers = runtime_script.build_timed_resource_grant_triggers(map_sid, grants)
        triggers.extend(grant_triggers)
        for grant in grants:
            if int(grant.get("nextOccurrence") or 0) > 0:
                arm_sid = timed_resource_arm_counter_sid(map_sid, grant.get("index"))
                counters.append(timer_counter_row(arm_sid))

    if triggers:
        quests.append(
            {
                "sid": f"{map_sid}_global_timed_events",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": "H3M global timed briefings + resource grants",
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{map_sid}_global_timed_events_fire",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": triggers,
                    }
                ],
                "subQuestGroups": [],
            }
        )

    return {
        "briefingCount": len(briefings),
        "timedGrantCount": len(grants),
        "counters": counters,
        "quests": quests,
        "dialogDocuments": dialog_documents,
        "omittedGaps": omitted,
        "notes": [
            "Player briefings: StartTurn Dialog. Resource grants: StartTurn + CED recurrence "
            "with GiveRes/RemoveRes. Runtime cadence unvalidated."
        ],
    }


def source_mine_records(walk_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in walk_records
        if int(record.get("templateObjectId") or -1)
        in (h3obj.OBJECT_MINE, h3obj.OBJECT_ABANDONED_MINE)
    ]
