#!/usr/bin/env python3
"""Build campaign mission runtime quest/counter scripts from decoded H3M manifest rows.

Shared Olden event policy (all RoE Castle batch missions):
- H3M global timed events own day-scheduled player briefings (Dialog + StartTurn).
- Computer/resource timed events emit calendar StartTurn first-fire + daily
  AnyStartTurn CounterPlus ticks + CounterEqualityInDays value-match recurrence
  (no finite day-cap expansion; see campaign_event_ir.schedule_encode).
- Unguarded map events: propActionsBefore Dialog + ObjectInteractionAfter GiveRes.
- Guarded map events: exact propSquads + propActionsBefore Dialog + SquadKill GiveRes.
- Town events emit ownership-targeted recurring GiveRes against featured city SIDs.
- Missing global timed briefings fail closed (no synthetic/H3C text fallback).
"""

from __future__ import annotations

import re
from typing import Any

from campaign_objective_text import objective_obj_sid, split_objective_bullets

# Legacy constant retained only so outdated callers fail loudly instead of truncating.
EVENT_RECURRENCE_DAY_CAP = 120
EVENT_RECURRENCE_EXPANSION_REMOVED = (
    "timed-grant day-list expansion was removed; use CounterEqualityInDays recurrence"
)

COUNTER_ACTION_KINDS: frozenset[str] = frozenset(
    {"CounterSet", "CounterPlus", "CounterMinus"}
)
COUNTER_CONDITION_KINDS: frozenset[str] = frozenset(
    {"Counter", "CounterEqualityInDays"}
)

# H3M resource slot order → native Story-map GiveRes resource ids.
H3_RESOURCE_GIVE_RES_IDS: tuple[str, ...] = (
    "wood",
    "mercury",
    "ore",
    "dust",
    "crystals",
    "gemstones",
    "gold",
)

NON_RESOURCE_REWARD_KEYS: tuple[str, ...] = (
    "experience",
    "mana",
    "morale",
    "luck",
    "primarySkill",
    "skills",
    "artifacts",
    "spells",
    "creatures",
)


def map_event_entity_sid(mission_id: str, index: int | str) -> str:
    return f"{mission_id}_h3m_map_event_{index}"


def map_event_dialog_sid(mission_id: str, index: int | str) -> str:
    return f"{mission_id}_map_event_{index}_dialog"


def monster_message_dialog_sid(mission_id: str, source_index: int | str) -> str:
    """Core dialog SID for an H3 monster stack custom interact message."""
    return f"{mission_id}_monster_{source_index}_dialog"


def map_event_guard_squad_entity_sid(mission_id: str, index: int | str) -> str:
    return f"{mission_id}_map_event_{index}_guard"


def map_event_guard_squad_overlay_sid(mission_id: str, index: int | str) -> str:
    return f"{mission_id}_map_event_{index}_guard_squad"


def seer_hut_entity_sid(mission_id: str, source_index: int | str) -> str:
    """Match approach_cell.deterministic_entity_sid for homm3_seer_hut placements."""
    return f"{mission_id}_homm3_seer_hut_{source_index}".replace("-", "_")


def _seer_hut_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("payloadKind") == "seer_hut" or record.get("templateObjectId") == 83:
            rows.append(record)
    return rows


def featured_capture_entity_sid(mission_id: str, *, city_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", city_name.lower()).strip("_")
    if not slug:
        raise ValueError(f"featured city name must produce a non-empty capture entity sid slug: {city_name!r}")
    return f"{mission_id}_capture_{slug}"


def mission_display_title(mission_id: str, mission_title: str | None = None) -> str:
    token = str(mission_title or "").strip()
    if token:
        return token
    return mission_id.replace("_", " ").title()


def _event_has_resources(event: dict[str, Any]) -> bool:
    resources = event.get("resources") or []
    return any(int(value or 0) != 0 for value in resources)


def _event_resource_signs(event: dict[str, Any]) -> tuple[bool, bool]:
    """Return (has_positive, has_negative) resource deltas."""
    resources = event.get("resources") or []
    has_positive = any(int(value or 0) > 0 for value in resources)
    has_negative = any(int(value or 0) < 0 for value in resources)
    return has_positive, has_negative


def partition_timed_resource_grants_for_alignment(
    mission_id: str, deferred: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep resource-delta grants (GiveRes and/or RemoveRes); omit empty computer events."""

    grants: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for grant in deferred:
        context = f"{mission_id} timed grant {grant.get('index')}"
        assert_resource_only_rewards(
            {"resources": grant.get("resources") or []},
            context=context,
        )
        has_positive, has_negative = _event_resource_signs(grant)
        if has_positive or has_negative:
            grants.append(grant)
            continue
        if bool(grant.get("computerAffected")):
            omitted.append(
                {
                    "index": grant.get("index"),
                    "name": grant.get("name"),
                    "resources": list(grant.get("resources") or []),
                    "omitReason": (
                        "computer/resource event has no nonzero resources to GiveRes/RemoveRes"
                    ),
                }
            )
            continue
        # Message-only deferred classification without resources should not reach here.
    return grants, omitted


def players_mask_to_start_turn_sides(players_mask: Any, *, context: str) -> list[str]:
    """H3M playersMask bit0 = player 1 → Olden StartTurn side \"1\" (one-based)."""
    from campaign_event_ir.audience_encode import encode_start_turn_sides

    return encode_start_turn_sides(players_mask, context=context)


def expand_timed_grant_occurrence_days(
    trigger_day: int,
    next_occurrence: int,
    *,
    day_cap: int = EVENT_RECURRENCE_DAY_CAP,
    context: str = "timed grant",
) -> list[int]:
    """Removed. Callers must use native/direct-state recurrence compilers."""

    raise ValueError(f"{context}: {EVENT_RECURRENCE_EXPANSION_REMOVED}")


def assert_resource_only_rewards(rewards: Any, *, context: str) -> None:
    if rewards is None:
        return
    if not isinstance(rewards, dict):
        raise ValueError(f"{context}: rewards must be a dict; got {type(rewards).__name__}")
    for key in NON_RESOURCE_REWARD_KEYS:
        value = rewards.get(key)
        if key in {"skills", "artifacts", "spells", "creatures"}:
            if value:
                raise ValueError(
                    f"{context}: non-resource reward field {key!r} is nonzero; "
                    f"this batch fail-closes non-resource map-event / timed rewards"
                )
        elif value not in (None, 0, 0.0, "", [], {}):
            if isinstance(value, (int, float)) and int(value) == 0:
                continue
            raise ValueError(
                f"{context}: non-resource reward field {key!r}={value!r} is nonzero; "
                f"this batch fail-closes non-resource rewards"
            )


def _signed_h3_reward_int(value: Any) -> Any:
    """Decode uint32-wrapped signed H3 reward deltas (e.g. 4294967246 → -50)."""
    if isinstance(value, int) and value >= 0x80000000:
        return value - 0x100000000
    return value


def take_resource_rewards_for_alignment(
    rewards: Any, *, context: str
) -> tuple[Any, list[str]]:
    """Keep experience + resources; omit unsupported non-resource fields with names.

    Pandora / map-event sheets often carry mana/morale/luck deltas that Olden
    alignment cannot emit yet. Fail-closed assert_resource_only_rewards remains
    for runtime script compile; alignment story payload uses this omit path so
    remaining RoE maps can still generate with an explicit gap list.
    """
    if rewards is None:
        return None, []
    if not isinstance(rewards, dict):
        raise ValueError(f"{context}: rewards must be a dict; got {type(rewards).__name__}")
    omitted: list[str] = []
    cleaned = dict(rewards)
    for key in NON_RESOURCE_REWARD_KEYS:
        value = cleaned.get(key)
        if key in {"skills", "artifacts", "spells", "creatures"}:
            if value:
                omitted.append(f"{key}={value!r}")
                cleaned[key] = []
            continue
        coerced = _signed_h3_reward_int(value)
        if coerced in (None, 0, 0.0, "", [], {}):
            cleaned[key] = 0 if isinstance(value, (int, float)) else value
            continue
        if isinstance(coerced, (int, float)) and int(coerced) == 0:
            cleaned[key] = 0
            continue
        omitted.append(f"{key}={coerced!r}")
        cleaned[key] = 0
    return cleaned, omitted


def give_res_actions_from_h3_resources(resources: Any, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(resources, list):
        raise ValueError(f"{context}: resources must be a list; got {type(resources).__name__}")
    if len(resources) > len(H3_RESOURCE_GIVE_RES_IDS):
        raise ValueError(
            f"{context}: resources length {len(resources)} exceeds "
            f"{len(H3_RESOURCE_GIVE_RES_IDS)}-slot H3 table"
        )
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(resources):
        amount = int(_signed_h3_reward_int(raw) or 0)
        if amount == 0:
            continue
        if amount < 0:
            raise ValueError(f"{context}: negative resource amount at slot {index}: {amount}")
        actions.append(
            {"comment": "", "a": "GiveRes", "p": [H3_RESOURCE_GIVE_RES_IDS[index], str(amount)]}
        )
    if not actions:
        raise ValueError(f"{context}: expected at least one nonzero resource for GiveRes")
    return actions


def remove_res_actions_from_h3_resources(resources: Any, *, context: str) -> list[dict[str, Any]]:
    """Emit stock-proven RemoveRes for negative H3 resource slots (absolute amounts)."""

    if not isinstance(resources, list):
        raise ValueError(f"{context}: resources must be a list; got {type(resources).__name__}")
    if len(resources) > len(H3_RESOURCE_GIVE_RES_IDS):
        raise ValueError(
            f"{context}: resources length {len(resources)} exceeds "
            f"{len(H3_RESOURCE_GIVE_RES_IDS)}-slot H3 table"
        )
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(resources):
        amount = int(_signed_h3_reward_int(raw) or 0)
        if amount >= 0:
            continue
        actions.append(
            {
                "comment": "",
                "a": "RemoveRes",
                "p": [H3_RESOURCE_GIVE_RES_IDS[index], str(abs(amount))],
            }
        )
    if not actions:
        raise ValueError(f"{context}: expected at least one negative resource for RemoveRes")
    return actions


def resource_delta_actions_from_h3_resources(resources: Any, *, context: str) -> list[dict[str, Any]]:
    """GiveRes for positive slots and RemoveRes for negative slots (stock-proven verbs)."""

    if not isinstance(resources, list):
        raise ValueError(f"{context}: resources must be a list; got {type(resources).__name__}")
    signed = [int(_signed_h3_reward_int(raw) or 0) for raw in resources]
    positives = [value if value > 0 else 0 for value in signed]
    negatives = [value if value < 0 else 0 for value in signed]
    actions: list[dict[str, Any]] = []
    if any(value > 0 for value in positives):
        actions.extend(give_res_actions_from_h3_resources(positives, context=context))
    if any(value < 0 for value in negatives):
        actions.extend(remove_res_actions_from_h3_resources(negatives, context=context))
    if not actions:
        raise ValueError(f"{context}: expected at least one nonzero resource delta")
    return actions


def nonempty_guard_stacks(
    stacks: Any,
    *,
    context: str,
    allow_empty: bool = False,
) -> list[dict[str, int]]:
    """Return nonempty guard stacks when hasGuards is true.

    AB/SoD maps sometimes set hasGuards with only empty 0xFFFF slots. Pass
    allow_empty=True for alignment/story emit so those events demote to
    unguarded hosts (matching EventIR readiness blocker behavior) instead of
    failing closed on inventory-only empty flags.
    """
    if not isinstance(stacks, list):
        raise ValueError(f"{context}: guardStacks must be a list when hasGuards is true")
    empty_types = {0xFF, 0xFFFF}
    out: list[dict[str, int]] = []
    for stack in stacks:
        if not isinstance(stack, dict):
            raise ValueError(f"{context}: malformed guard stack {stack!r}")
        creature_type = stack.get("creatureType")
        count = stack.get("count")
        if not isinstance(creature_type, int) or not isinstance(count, int):
            raise ValueError(f"{context}: guard stack missing creatureType/count: {stack!r}")
        if count <= 0 or creature_type in empty_types:
            continue
        out.append({"creatureType": creature_type, "count": count})
    if not out and not allow_empty:
        raise ValueError(f"{context}: hasGuards true but no nonempty guardStacks")
    return out


def classify_global_timed_event(event: dict[str, Any]) -> dict[str, Any]:
    """Classify one H3M global timed event for the Olden campaign script.

    Player briefings: non-empty message and not computerAffected.
    Deferred computer/resource events: computerAffected and/or nonzero resources.
    An event may be both (message briefing + deferred resource grant).
    """
    if not isinstance(event, dict):
        raise ValueError("global timed event must be a dict")
    body = str(event.get("message") or "").strip()
    computer_affected = bool(event.get("computerAffected"))
    has_resources = _event_has_resources(event)
    is_player_briefing = bool(body) and not computer_affected
    is_deferred = computer_affected or has_resources
    if not is_player_briefing and not is_deferred:
        raise ValueError(
            f"global timed event {event.get('index')!r} has neither player briefing message "
            f"nor computer/resource effects"
        )
    return {
        "index": event.get("index"),
        "name": str(event.get("name") or "").strip(),
        "message": body,
        "resources": list(event.get("resources") or []),
        "playersMask": event.get("playersMask"),
        "computerAffected": computer_affected,
        "firstOccurrence": int(event.get("firstOccurrence") or 0),
        "nextOccurrence": int(event.get("nextOccurrence") or 0),
        "triggerDay": int(event.get("triggerDay") or (int(event.get("firstOccurrence") or 0) + 1)),
        "isPlayerBriefing": is_player_briefing,
        "isDeferredComputerOrResource": is_deferred,
        "deferredReason": (
            "computer_affected_and_resources"
            if computer_affected and has_resources
            else "computer_affected"
            if computer_affected
            else "nonzero_resources"
            if has_resources
            else None
        ),
    }


def partition_global_timed_events(global_timed_events: dict[str, Any] | None) -> dict[str, Any]:
    events = (global_timed_events or {}).get("events") or []
    briefings: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for event in events:
        classified = classify_global_timed_event(event)
        if classified["isPlayerBriefing"]:
            briefings.append(classified)
        if classified["isDeferredComputerOrResource"]:
            deferred.append(classified)
    return {
        "playerBriefings": briefings,
        "deferredComputerOrResourceEvents": deferred,
        "sourceEventCount": len(events),
        "sourceStatus": (global_timed_events or {}).get("status"),
    }


def _briefing_dialog_segments(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for record in records:
        if record.get("category") != "campaign_briefing_script":
            continue
        if record.get("payloadKind") != "roe_campaign_briefing":
            continue
        title = str(record.get("firstVisitText") or "").strip()
        body = str(record.get("nextVisitText") or "").strip()
        if not title and not body:
            continue
        segments.append(
            {
                "title": title,
                "body": body,
                "sourceIndex": str(record.get("sourceIndex")),
                "triggerKind": "start_turn",
                "triggerDay": 1,
                "source": "synthetic_roe_campaign_briefing",
            }
        )
    return segments


def _map_event_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("category") == "map_event"]


# Unguarded EVENT sharing a cell with a placed hero: dialog rebinds onto hero-spawner.
# HoMM3 heroes do not adjacent-ZoC (unlike wandering monsters); keep hostLifetime distinct
# so emit never Zone-converts or DeleteEntity-deletes the hero.
COLOCATED_HERO_HOST_LIFETIME = "colocated_hero_host"
PERSISTENT_OBJECT_HOST_LIFETIME = "persistent_object"
DISPOSABLE_MARKER_HOST_LIFETIME = "disposable_marker"


def _record_source_key(record: dict[str, Any]) -> str:
    key = record.get("sourceKey") or record.get("key")
    if isinstance(key, str) and key.strip():
        return key
    layer = record.get("sourceLayer", record.get("layer", 0))
    x = record.get("sourceX", record.get("x"))
    y = record.get("sourceY", record.get("y"))
    if x is None or y is None:
        return ""
    return f"{int(layer)}:{int(x)}:{int(y)}"


def colocated_hero_by_event_source_key(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Same-cell hero_or_prison for unguarded map EVENTs (sourceKey → hero record)."""
    heroes: dict[str, dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source_key = _record_source_key(record)
        if not source_key:
            continue
        category = record.get("category")
        payload_kind = record.get("payloadKind")
        if category == "hero_or_prison":
            heroes[source_key] = record
        if category == "map_event" or payload_kind in {"event", "map_event"}:
            events[source_key] = record
    colocated: dict[str, dict[str, Any]] = {}
    for source_key, event in events.items():
        hero = heroes.get(source_key)
        if hero is None:
            continue
        trigger_fields = event.get("triggerFields") or {}
        box = (event.get("boxContent") or {}).get("messageAndGuards") or {}
        has_guards_flag = bool(
            trigger_fields.get("hasGuards")
            if "hasGuards" in trigger_fields
            else box.get("hasGuards")
        )
        guard_stacks = trigger_fields.get("guardStacks")
        if guard_stacks is None:
            guard_stacks = box.get("guardStacks")
        nonempty = []
        if has_guards_flag and isinstance(guard_stacks, list):
            try:
                nonempty = nonempty_guard_stacks(
                    guard_stacks,
                    context=f"colocated hero detect {source_key}",
                    allow_empty=True,
                )
            except ValueError:
                nonempty = []
        # EVENT-embedded guards stay on the exact-squad backend; do not rebind to hero.
        if nonempty:
            continue
        colocated[source_key] = hero
    return colocated


def resolve_map_event_host_binding(
    *,
    mission_id: str,
    source_key: str,
    remove_after_visit: bool,
    has_guards: bool,
    colocated_heroes: dict[str, dict[str, Any]],
) -> tuple[str, bool, int | None]:
    """Return (hostLifetime, actionRepeat, colocatedHeroHostSourceIndex)."""
    if mission_id == "homecoming" and source_key == "0:18:35":
        # Declarative Guardhouse binding: persistent dwelling host, one-shot dialog.
        return PERSISTENT_OBJECT_HOST_LIFETIME, False, None
    hero = colocated_heroes.get(source_key) if not has_guards else None
    if hero is not None:
        hero_index = hero.get("sourceIndex", hero.get("index"))
        if not isinstance(hero_index, int):
            raise ValueError(
                f"{mission_id} map event {source_key}: colocated hero missing sourceIndex"
            )
        return COLOCATED_HERO_HOST_LIFETIME, False, hero_index
    if remove_after_visit:
        return DISPOSABLE_MARKER_HOST_LIFETIME, False, None
    return PERSISTENT_OBJECT_HOST_LIFETIME, (not has_guards), None


def briefing_segments_from_texts(briefing_texts: list[str] | None) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for index, text in enumerate(briefing_texts or []):
        body = str(text or "").strip()
        if not body:
            continue
        segments.append(
            {
                "title": "",
                "body": body,
                "sourceIndex": str(index),
                "triggerKind": "start_turn",
                "triggerDay": 1,
                "source": "h3c_briefing_texts",
            }
        )
    return segments


def briefing_segments_from_global_timed_events(global_timed_events: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Prefer H3M global timed events when present; they own day-scheduled story/recon dialogs."""
    partitioned = partition_global_timed_events(global_timed_events)
    segments: list[dict[str, Any]] = []
    for event in partitioned["playerBriefings"]:
        segments.append(
            {
                "title": event["name"],
                "body": event["message"],
                "sourceIndex": str(event["index"]),
                "triggerKind": "start_turn",
                "triggerDay": event["triggerDay"],
                "firstOccurrence": event["firstOccurrence"],
                "nextOccurrence": event["nextOccurrence"],
                "source": "h3m_global_timed_event",
            }
        )
    return segments



def _town_event_non_resource_effects(town_event: dict[str, Any]) -> list[str]:
    """Named non-resource town-event fields present in H3M (omitted at alignment)."""
    omitted: list[str] = []
    growth = town_event.get("creatureGrowth") or []
    if isinstance(growth, list) and any(int(value or 0) != 0 for value in growth):
        omitted.append(f"creatureGrowth={growth!r}")
    buildings = str(town_event.get("eventBuildingsMask") or "").strip()
    if buildings and buildings.strip("0"):
        omitted.append(f"eventBuildingsMask={buildings!r}")
    return omitted


def _town_event_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        town_state = record.get("townState") if isinstance(record.get("townState"), dict) else {}
        town_events = town_state.get("townEvents") or record.get("townEvents") or []
        if not town_events:
            continue
        town_key = str(record.get("sourceKey") or record.get("key") or "")
        town_name = str(record.get("name") or town_state.get("name") or "")
        for event_index, town_event in enumerate(town_events):
            if not isinstance(town_event, dict):
                raise ValueError(f"town {town_key} event {event_index} must be a dict")
            rows.append(
                {
                    "townSourceKey": town_key,
                    "townName": town_name,
                    "eventIndex": event_index,
                    "name": str(town_event.get("name") or "").strip(),
                    "message": str(town_event.get("message") or ""),
                    "resources": list(town_event.get("resources") or []),
                    "creatureGrowth": list(town_event.get("creatureGrowth") or []),
                    "eventBuildingsMask": town_event.get("eventBuildingsMask"),
                    "playersMask": town_event.get("players"),
                    "humanAffected": town_event.get("humanAffected"),
                    "computerAffected": town_event.get("computerAffected"),
                    "firstOccurrence": int(town_event.get("firstOccurrence") or 0),
                    "nextOccurrence": int(town_event.get("nextOccurrence") or 0),
                    "triggerDay": int(town_event.get("firstOccurrence") or 0) + 1,
                }
            )
    return rows


def partition_town_events_for_alignment(
    mission_id: str, town_events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep resource GiveRes town events; omit growth/buildings-only with explicit gaps.

    QuestScript town grants only emit resources today. Creature-growth and building
    town events (e.g. Specter Poison Fit ``Troops``) are recorded as omissions rather
    than silently dropped or falsely required to carry resources.
    """
    resource_events: list[dict[str, Any]] = []
    omitted_events: list[dict[str, Any]] = []
    for town_event in town_events:
        context = (
            f"{mission_id} town event {town_event.get('townSourceKey')}"
            f"#{town_event.get('eventIndex')}"
        )
        assert_resource_only_rewards(
            {"resources": town_event.get("resources") or []},
            context=context,
        )
        non_resource = _town_event_non_resource_effects(town_event)
        has_resources = _event_has_resources(town_event)
        if has_resources:
            row = dict(town_event)
            if non_resource:
                row["omittedNonResourceTownFields"] = non_resource
            resource_events.append(row)
            continue
        if non_resource:
            omitted_events.append(
                {
                    "townSourceKey": town_event.get("townSourceKey"),
                    "eventIndex": town_event.get("eventIndex"),
                    "name": town_event.get("name"),
                    "omittedNonResourceTownFields": non_resource,
                    "omitReason": (
                        "town event has no nonzero resources; QuestScript GiveRes path "
                        "cannot encode creatureGrowth/eventBuildingsMask"
                    ),
                }
            )
            continue
        # Empty stubs (named "Gold" with all-zero resources/growth/buildings) appear on
        # AB/SoD maps; omit rather than fail closed on inventory-only placeholders.
        omitted_events.append(
            {
                "townSourceKey": town_event.get("townSourceKey"),
                "eventIndex": town_event.get("eventIndex"),
                "name": town_event.get("name"),
                "omittedNonResourceTownFields": [],
                "omitReason": "empty town event stub (no resources, growth, or buildings)",
            }
        )
    return resource_events, omitted_events


def build_alignment_story_payload(
    mission_id: str,
    records: list[dict[str, Any]],
    *,
    objective_text: str | None = None,
    briefing_texts: list[str] | None = None,
    global_timed_events: dict[str, Any] | None = None,
    mission_title: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    prop_actions_before: list[dict[str, Any]] = []
    prop_actions_after: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    display_title = mission_display_title(mission_id, mission_title)

    partitioned = partition_global_timed_events(global_timed_events)
    briefing_segments = briefing_segments_from_global_timed_events(global_timed_events)
    briefing_source = "h3m_global_timed_event" if briefing_segments else None
    if not briefing_segments:
        raise ValueError(
            f"{mission_id}: missing H3M global timed player briefings; "
            f"synthetic ROE / H3C briefing fallbacks are forbidden "
            f"(globalTimedEvents status={(global_timed_events or {}).get('status')!r}, "
            f"eventCount={(global_timed_events or {}).get('eventCount')})"
        )
    _ = briefing_texts  # call-site compat; never used as fallback
    map_events = _map_event_rows(records)
    town_events = _town_event_rows(records)
    colocated_heroes = colocated_hero_by_event_source_key(records)

    for index, event in enumerate(map_events):
        trigger_fields = event.get("triggerFields") or {}
        entity_sid = map_event_entity_sid(mission_id, index)
        dialog_sid = map_event_dialog_sid(mission_id, index)
        has_guards_flag = bool(trigger_fields.get("hasGuards"))
        rewards, omitted_rewards = take_resource_rewards_for_alignment(
            trigger_fields.get("rewards"),
            context=f"{mission_id} map event {index}",
        )
        guard_stacks = (
            nonempty_guard_stacks(
                trigger_fields.get("guardStacks"),
                context=f"{mission_id} map event {index}",
                allow_empty=True,
            )
            if has_guards_flag
            else []
        )
        # Empty 0xFFFF-only guard slots (common on AB/SoD) demote to unguarded emit.
        has_guards = bool(guard_stacks)
        remove_after_visit = bool(trigger_fields.get("removeAfterVisit"))
        source_key = str(event.get("sourceKey") or "")
        host_lifetime, action_repeat, colocated_hero_index = resolve_map_event_host_binding(
            mission_id=mission_id,
            source_key=source_key,
            remove_after_visit=remove_after_visit,
            has_guards=has_guards,
            colocated_heroes=colocated_heroes,
        )
        dialog_avatar = None
        if host_lifetime == COLOCATED_HERO_HOST_LIFETIME:
            hero = colocated_heroes.get(source_key)
            if not isinstance(hero, dict):
                raise ValueError(
                    f"{mission_id} map event {source_key}: colocated_hero_host missing hero record"
                )
            dialog_avatar = colocated_hero_dialog_avatar(hero)
        alignment_row = {
            "sid": f"h3m.action.map_event_alignment.{index}",
            "entitySid": entity_sid,
            "dialogSid": dialog_sid,
            "sourceKey": event.get("sourceKey"),
            "sourceIndex": event.get("sourceIndex"),
            "sourceObjectTemplate": event.get("templateObjectId"),
            "message": event.get("message"),
            "playersMask": trigger_fields.get("playersMask"),
            "computerActivate": trigger_fields.get("computerActivate"),
            "humanActivate": trigger_fields.get("humanActivate", True),
            "removeAfterVisit": remove_after_visit,
            "actionRepeat": action_repeat,
            "hostLifetime": host_lifetime,
            "colocatedHeroHostSourceIndex": colocated_hero_index,
            "dialogAvatars": (dialog_avatar or {}).get("avatars"),
            "dialogTitle": (dialog_avatar or {}).get("title"),
            "dialogTitlePosition": (dialog_avatar or {}).get("titlePosition"),
            "dialogHeroSid": (dialog_avatar or {}).get("heroSid"),
            "dialogAvatarIcon": (dialog_avatar or {}).get("icon"),
            "rewards": rewards,
            "rewardCounts": trigger_fields.get("rewardCounts"),
            "omittedNonResourceRewardFields": omitted_rewards,
            "hasGuards": has_guards,
            "hasGuardsSource": has_guards_flag,
            "emptyGuardStacksDemoted": bool(has_guards_flag and not has_guards),
            "guardStacks": guard_stacks,
            "squadEntitySid": map_event_guard_squad_entity_sid(mission_id, index) if has_guards else None,
            # SpawnsCreator requires propRandomSquads on random-squad hosts; overlay
            # budgets use count×squadValue (not headcount as v).
            "squadOverlaySid": (
                map_event_guard_squad_overlay_sid(mission_id, index) if has_guards else None
            ),
            "alignmentStatus": "direct_map_event_trigger_contract",
            "alignmentMode": "campaign_runtime_script",
            "queryShapeOnly": False,
        }
        prop_actions_before.append(alignment_row)
        actions.append(alignment_row)

    resource_grants, omitted_negative_grants = partition_timed_resource_grants_for_alignment(
        mission_id, partitioned["deferredComputerOrResourceEvents"]
    )

    resource_town_events, omitted_town_events = partition_town_events_for_alignment(
        mission_id, town_events
    )

    story_counters = [
        {"sid": f"{mission_id}_started", "value": 0},
        {"sid": f"{mission_id}_briefing_index", "value": 0},
    ]
    for index, _event in enumerate(map_events):
        story_counters.append({"sid": f"{mission_id}_map_event_{index}_visited", "value": 0})
    from campaign_event_ir.schedule_encode import TIMER_PREARM_VALUE

    for grant in resource_grants:
        if int(grant.get("nextOccurrence") or 0) > 0:
            story_counters.append(
                {
                    "sid": f"{mission_id}_timed_grant_{grant.get('index')}_armed",
                    "value": TIMER_PREARM_VALUE,
                }
            )
    for town_event in resource_town_events:
        if int(town_event.get("nextOccurrence") or 0) > 0:
            story_counters.append(
                {
                    "sid": f"{mission_id}_timed_grant_town_{town_event.get('eventIndex')}_armed",
                    "value": TIMER_PREARM_VALUE,
                }
            )

    story_quests = [
        {
            "sid": f"{mission_id}_intro",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "briefingSegmentCount": len(briefing_segments),
        },
        {
            "sid": f"{mission_id}_main_goal",
            "main": True,
            "activeOnStart": True,
            "objectiveText": objective_text or "",
        },
    ]
    for index, event in enumerate(map_events):
        trigger_fields = event.get("triggerFields") or {}
        has_guards_flag = bool(trigger_fields.get("hasGuards"))
        rewards, omitted_rewards = take_resource_rewards_for_alignment(
            trigger_fields.get("rewards"),
            context=f"{mission_id} map event quest {index}",
        )
        guard_stacks = (
            nonempty_guard_stacks(
                trigger_fields.get("guardStacks"),
                context=f"{mission_id} map event quest {index}",
                allow_empty=True,
            )
            if has_guards_flag
            else []
        )
        has_guards = bool(guard_stacks)
        remove_after_visit = bool(trigger_fields.get("removeAfterVisit"))
        source_key = str(event.get("sourceKey") or "")
        host_lifetime, action_repeat, colocated_hero_index = resolve_map_event_host_binding(
            mission_id=mission_id,
            source_key=source_key,
            remove_after_visit=remove_after_visit,
            has_guards=has_guards,
            colocated_heroes=colocated_heroes,
        )
        dialog_avatar = None
        if host_lifetime == COLOCATED_HERO_HOST_LIFETIME:
            hero = colocated_heroes.get(source_key)
            if not isinstance(hero, dict):
                raise ValueError(
                    f"{mission_id} map event quest {source_key}: colocated_hero_host missing hero record"
                )
            dialog_avatar = colocated_hero_dialog_avatar(hero)
        story_quests.append(
            {
                "sid": f"{mission_id}_map_event_{index}",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "sourceKey": event.get("sourceKey"),
                "message": event.get("message"),
                "entitySid": map_event_entity_sid(mission_id, index),
                "dialogSid": map_event_dialog_sid(mission_id, index),
                "removeAfterVisit": remove_after_visit,
                "actionRepeat": action_repeat,
                "hostLifetime": host_lifetime,
                "colocatedHeroHostSourceIndex": colocated_hero_index,
                "dialogAvatars": (dialog_avatar or {}).get("avatars"),
                "dialogTitle": (dialog_avatar or {}).get("title"),
                "dialogTitlePosition": (dialog_avatar or {}).get("titlePosition"),
                "dialogHeroSid": (dialog_avatar or {}).get("heroSid"),
                "dialogAvatarIcon": (dialog_avatar or {}).get("icon"),
                "playersMask": trigger_fields.get("playersMask"),
                "computerActivate": trigger_fields.get("computerActivate"),
                "humanActivate": trigger_fields.get("humanActivate", True),
                "rewards": rewards,
                "omittedNonResourceRewardFields": omitted_rewards,
                "hasGuards": has_guards,
                "hasGuardsSource": has_guards_flag,
                "emptyGuardStacksDemoted": bool(has_guards_flag and not has_guards),
                "guardStacks": guard_stacks,
                "squadEntitySid": map_event_guard_squad_entity_sid(mission_id, index) if has_guards else None,
                "squadOverlaySid": (
                    map_event_guard_squad_overlay_sid(mission_id, index) if has_guards else None
                ),
            }
        )

    for seer_record in _seer_hut_records(records):
        source_index = seer_record.get("sourceIndex")
        if not isinstance(source_index, int):
            raise ValueError(f"{mission_id}: seer hut missing integer sourceIndex")
        quest_payload = seer_record.get("quest")
        if quest_payload is None and isinstance(seer_record.get("quests"), list):
            quests = seer_record["quests"]
            quest_payload = quests[0] if len(quests) == 1 else None
        if isinstance(quest_payload, dict) and int(quest_payload.get("missionType") or 0) == 0:
            continue
        hut_sid = seer_hut_entity_sid(mission_id, source_index)
        from seer_hut_campaign_bind import compile_seer_entity_subquests

        subquests, counter_sids, plan = compile_seer_entity_subquests(
            seer_record,
            hut_entity_sid=hut_sid,
            target_entity_sid=None,
            mission_id=mission_id,
        )
        triggers = [
            trigger
            for subquest in subquests
            for trigger in subquest["triggers"]
        ]
        for counter_sid in counter_sids:
            story_counters.append({"sid": counter_sid, "value": 0})
        story_quest_row = {
            "sid": plan.quest_id,
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "kind": "seer_hut_quest",
            "sourceKey": seer_record.get("sourceKey"),
            "sourceIndex": source_index,
            "entitySid": hut_sid,
            # Raw H3 quest retained so map emit can recompile the FSM even when
            # placement entities omit decoder fields.
            "questPayload": dict(quest_payload) if isinstance(quest_payload, dict) else None,
            "questPlan": {
                "dialogFirstSid": plan.dialog_first_sid,
                "dialogNextSid": plan.dialog_next_sid,
                "dialogCompletedSid": plan.dialog_completed_sid,
                "firstVisitText": plan.texts.first_visit,
                "nextVisitText": plan.texts.next_visit,
                "completedText": plan.texts.completed,
            },
            "compiledTriggers": list(triggers),
            "compiledSubQuests": [dict(subquest) for subquest in subquests],
        }
        if plan.substitution_note:
            # Hand-crafted substitute (seer_hut_substitutes.py): keep the original
            # H3 quest plus the reason for divergence visible in the generated map.
            story_quest_row["questSubstitution"] = plan.substitution_note
        story_quests.append(story_quest_row)

    deferred = resource_grants
    story_payload: dict[str, Any] = {
        "comment": f"{mission_id}_campaign_runtime_script_alignment",
        "aiRolesId": f"{mission_id}_campaign_runtime_script",
        "missionTitle": display_title,
        "interruptions": [],
        "counters": story_counters,
        "quests": story_quests,
        "briefingSegments": briefing_segments,
        "briefingSource": briefing_source,
        "mapEventAlignment": actions,
        "globalTimedEventCount": partitioned["sourceEventCount"],
        "deferredComputerOrResourceEvents": deferred,
        "deferredComputerOrResourceEventCount": len(deferred),
        "timedResourceGrants": deferred,
        "timedResourceGrantCount": len(deferred),
        "omittedNegativeResourceTimedEvents": omitted_negative_grants,
        "omittedNegativeResourceTimedEventCount": len(omitted_negative_grants),
        "townEvents": resource_town_events,
        "townEventCount": len(resource_town_events),
        "omittedTownEvents": omitted_town_events,
        "omittedTownEventCount": len(omitted_town_events),
        "eventPolicy": {
            "schema": "homm3.olden_campaign_event_policy.v1",
            "timedEvents": "h3m_global_timed_events_player_briefings_start_turn_dialog",
            "computerOrResourceTimedEvents": (
                "questscript_calendar_start_turn_first_fire;"
                "any_start_turn_counter_plus_ticks;"
                "counter_equality_in_days_value_match_recurrence;"
                "fail_closed_non_resource;no_day_cap_expansion"
            ),
            "mapEvents": (
                "unguarded_prop_actions_before_dialog_object_interaction_after_giveres;"
                "colocated_hero_rebind_dialog_onto_hero_spawner_no_zone;"
                "guarded_exact_propsquads_plus_proprandomsquads_squadvalue_budget;"
                "guarded_prop_actions_before_dialog_squadkill_only;"
                "no_squadinteraction_dialog;"
                "zero_based_prop_actions_sides;no_computerActivate_property;"
                "fail_closed_non_resource_rewards"
            ),
            "townEvents": (
                "questscript_start_turn_first_fire_plus_counter_equality_in_days_recurrence;"
                "featured_city_entity_sid_target;ownership_filter_runtime_unproven"
            ),
            "eventRecurrenceDayCap": None,
            "proofBoundary": (
                "source/static + generated alignment/QuestScript/map properties; "
                "audience, recurrence cadence, aiIgnore, guarded phases, and town "
                "ownership remain runtime-unproven"
            ),
        },
    }
    if objective_text:
        story_counters.append({"sid": f"{mission_id}_main_goal_complete", "value": 0})
    return prop_actions_before, prop_actions_after, actions, story_payload


def _runtime_counter_rows(counters: list[dict[str, Any]], *, sharing: str = "Clone") -> list[dict[str, Any]]:
    return [
        {
            "comment": "",
            "sid": row.get("sid"),
            "sharing": sharing,
            "value": row.get("value", 0),
            "minValue": -2147483648,
            "maxValue": 2147483647,
        }
        for row in counters
        if isinstance(row.get("sid"), str) and row.get("sid")
    ]


def _dialog_action(dialog_sid: str) -> dict[str, Any]:
    return {"comment": "", "a": "Dialog", "p": [dialog_sid]}


def _starting_bonus_dialog_actions(alignment_story: dict[str, Any]) -> list[dict[str, Any]]:
    """Append Day-1 starting-bonus Dialog when alignment_story carries a resolved spec."""
    bonus = alignment_story.get("startingBonus")
    if not isinstance(bonus, dict):
        return []
    dialog_sid = str(bonus.get("dialogSid") or "").strip()
    if not dialog_sid:
        raise ValueError("alignment_story.startingBonus.dialogSid is required")
    options = bonus.get("options")
    if not isinstance(options, list) or len(options) < 1:
        raise ValueError(
            f"startingBonus {dialog_sid!r} must declare >= 1 option before QuestScript emit"
        )
    hero_sid = str(bonus.get("heroSid") or "").strip()
    if not hero_sid:
        raise ValueError(f"startingBonus {dialog_sid!r} missing heroSid")
    return [_dialog_action(dialog_sid)]


def collect_referenced_counter_sids(quests: list[Any] | None) -> set[str]:
    """Collect counter SIDs referenced by quest actions/conditions."""
    referenced: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            kind_a = node.get("a")
            kind_c = node.get("c")
            params = node.get("p")
            if (
                kind_a in COUNTER_ACTION_KINDS
                and isinstance(params, list)
                and params
                and isinstance(params[0], str)
                and params[0]
            ):
                referenced.add(params[0])
            if (
                kind_c in COUNTER_CONDITION_KINDS
                and isinstance(params, list)
                and params
                and isinstance(params[0], str)
                and params[0]
            ):
                referenced.add(params[0])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(quests or [])
    return referenced


def assert_quest_counter_sids_declared(
    *,
    counters: list[Any] | None,
    quests: list[Any] | None,
    mission_id: str,
    interruptions: list[Any] | None = None,
) -> None:
    """Fail closed when quest Counter* SIDs are missing from declared counters."""
    declared = {
        str(row.get("sid"))
        for row in (counters or [])
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and row.get("sid")
    }
    referenced = collect_referenced_counter_sids(quests)
    referenced |= collect_referenced_counter_sids(interruptions)
    missing = sorted(referenced - declared)
    if missing:
        sample = ", ".join(missing[:8])
        more = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        raise ValueError(
            f"{mission_id}: quest Counter* SID(s) missing from declared counters: "
            f"{sample}{more}. Declared started="
            f"{sorted(s for s in declared if s.endswith('_started'))}"
        )


def _counter_set(counter_sid: str, value: str | int) -> dict[str, Any]:
    return {"comment": "", "a": "CounterSet", "p": [counter_sid, str(value)]}


def _counter_condition(counter_sid: str, operator: str, value: str | int, *, counter_slot: int = 1) -> dict[str, Any]:
    return {"comment": "", "c": "Counter", "p": [counter_sid, operator, str(value)], "counter": counter_slot}


def _object_interaction_after(entity_sid: str, *, counter_slot: int = 1) -> dict[str, Any]:
    return {"comment": "", "c": "ObjectInteractionAfter", "p": [entity_sid], "counter": counter_slot}


def _squad_kill(entity_sid: str, *, counter_slot: int = 1) -> dict[str, Any]:
    return {"comment": "", "c": "SquadKill", "p": [entity_sid], "counter": counter_slot}


def _start_turn(week: str | int, day: int, *, counter_slot: int = 1) -> dict[str, Any]:
    """StartTurn parameters are calendar week + day-of-week (decomp ConStartTurn)."""

    return {"comment": "", "c": "StartTurn", "p": [str(week), str(day)], "counter": counter_slot}


def _briefing_start_turn(absolute_day: int) -> dict[str, Any]:
    """Map 1-based absolute day onto StartTurn week/day (not hard-coded week 1)."""
    from campaign_event_ir.schedule_encode import start_turn_condition

    return start_turn_condition(int(absolute_day), context="campaign briefing")


def build_timed_resource_grant_triggers(
    mission_id: str,
    grants: list[dict[str, Any]],
    *,
    day_cap: int | None = None,
) -> list[dict[str, Any]]:
    """Emit StartTurn first-fire + CounterPlus/CED interval recurrence for timed grants."""
    if day_cap is not None:
        raise ValueError(
            f"{mission_id}: day_cap expansion was removed; pass day_cap=None "
            f"({EVENT_RECURRENCE_EXPANSION_REMOVED})"
        )
    from campaign_event_ir.compile_backends import compile_repeating_resource_triggers
    from campaign_event_ir.model import (
        Audience,
        BackendId,
        BackendStatus,
        CampaignEventIR,
        Effects,
        EventScope,
        HostKind,
        HostRef,
        Schedule,
    )

    triggers: list[dict[str, Any]] = []
    for grant in grants:
        if not isinstance(grant, dict):
            raise ValueError(f"{mission_id}: timed resource grant must be a dict")
        context = f"{mission_id} timed grant {grant.get('index')}"
        if not _event_has_resources(grant):
            raise ValueError(f"{context}: missing nonzero resources")
        mask = int(grant["playersMask"])
        indices = tuple(i for i in range(8) if mask & (1 << i))
        schedule = Schedule(
            first_occurrence=int(grant.get("firstOccurrence") or 0),
            next_occurrence=int(grant.get("nextOccurrence") or 0),
            trigger_day=int(grant["triggerDay"]),
            is_repeating=int(grant.get("nextOccurrence") or 0) > 0,
        )
        backend = (
            BackendId.REPEATING_RESOURCE if schedule.is_repeating else BackendId.ONE_SHOT_TIMED_RESOURCE
        )
        event = CampaignEventIR(
            mission_id=mission_id,
            scope=EventScope.GLOBAL,
            source_identity=f"{mission_id}:global:{grant.get('index')}",
            source_index=int(grant["index"]) if grant.get("index") is not None else None,
            source_key=f"global:{grant.get('index')}",
            name=str(grant.get("name") or ""),
            schedule=schedule,
            audience=Audience(
                players_mask=mask,
                human_eligible=None,
                computer_eligible=bool(grant.get("computerAffected")),
                zero_based_player_indices=indices,
                human_eligible_layout="roe_ab_sod_no_human_affected_byte",
            ),
            host=HostRef(kind=HostKind.NONE),
            remove_after_visit=None,
            has_guards=False,
            guard_stacks=(),
            effects=Effects(message=str(grant.get("message") or ""), resources=tuple(grant.get("resources") or [])),
            is_player_briefing=False,
            is_timed_resource_grant=True,
            selected_backend=backend,
            backend_status=BackendStatus.SELECTED_UNPROVEN,
            readiness_blockers=(),
        )
        triggers.extend(compile_repeating_resource_triggers(event))
    return triggers


def build_town_event_grant_triggers(mission_id: str, town_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit recurring town resource grants (ownership filter runtime-unproven)."""
    from campaign_event_ir.compile_backends import compile_repeating_resource_triggers
    from campaign_event_ir.model import (
        Audience,
        BackendId,
        BackendStatus,
        CampaignEventIR,
        Effects,
        EventScope,
        HostKind,
        HostRef,
        Schedule,
    )

    triggers: list[dict[str, Any]] = []
    for town_event in town_events:
        mask = int(town_event["playersMask"])
        indices = tuple(i for i in range(8) if mask & (1 << i))
        schedule = Schedule(
            first_occurrence=int(town_event.get("firstOccurrence") or 0),
            next_occurrence=int(town_event.get("nextOccurrence") or 0),
            trigger_day=int(town_event["triggerDay"]),
            is_repeating=int(town_event.get("nextOccurrence") or 0) > 0,
        )
        event = CampaignEventIR(
            mission_id=mission_id,
            scope=EventScope.TOWN,
            source_identity=(
                f"{mission_id}:town:{town_event.get('townSourceKey')}:event:{town_event.get('eventIndex')}"
            ),
            source_index=int(town_event["eventIndex"]),
            source_key=f"town:{town_event.get('townSourceKey')}:event:{town_event.get('eventIndex')}",
            name=str(town_event.get("name") or ""),
            schedule=schedule,
            audience=Audience(
                players_mask=mask,
                human_eligible=bool(town_event.get("humanAffected")),
                computer_eligible=bool(town_event.get("computerAffected")),
                zero_based_player_indices=indices,
                human_eligible_layout="town_event_roe_human_affected_hardcoded_true",
            ),
            host=HostRef(
                kind=HostKind.TOWN,
                source_key=str(town_event.get("townSourceKey") or ""),
                town_name=str(town_event.get("townName") or "") or None,
                town_event_index=int(town_event["eventIndex"]),
            ),
            remove_after_visit=None,
            has_guards=False,
            guard_stacks=(),
            effects=Effects(
                message=str(town_event.get("message") or ""),
                resources=tuple(town_event.get("resources") or []),
            ),
            is_player_briefing=False,
            is_timed_resource_grant=True,
            selected_backend=BackendId.TOWN_OWNERSHIP_AWARE,
            backend_status=BackendStatus.SELECTED_UNPROVEN,
            readiness_blockers=(),
        )
        # Compile with the town arm-counter SID directly — do not post-rewrite a
        # subset of Counter* ops (CounterPlus was previously left on the global SID).
        from campaign_event_ir.compile_backends import timed_town_resource_arm_counter_sid

        compiled = compile_repeating_resource_triggers(
            event,
            arm_counter_sid=timed_town_resource_arm_counter_sid(
                mission_id, int(town_event["eventIndex"])
            ),
        )
        triggers.extend(compiled)
    return triggers


def _global_entities_by_source_key(
    global_entities: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not global_entities:
        return out
    for row in global_entities:
        if not isinstance(row, dict):
            continue
        source_key = str(row.get("sourceKey") or "").strip()
        if source_key:
            out[source_key] = row
    return out


def _runtime_seer_subquests_for_story_row(
    mission_id: str,
    quest_row: dict[str, Any],
    *,
    global_entities_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recompile Seer FSM from decoded H3 quest + placement entity identity.

    Alignment story already compiled once from the port manifest. Map emit must
    recompile (so FSM shape stays owned by ``seer_hut_quest``), but placement
    ``globalEntities`` sometimes omit decoder fields. Prefer ``questPayload`` on
    the story row when present; never silently reuse stale ``compiledSubQuests``.
    """

    quest_sid = str(quest_row.get("sid") or "").strip()
    source_key = str(quest_row.get("sourceKey") or "").strip()
    hut_sid = str(quest_row.get("entitySid") or "").strip()
    if not quest_sid or not source_key or not hut_sid:
        raise ValueError(
            f"{mission_id}: seer hut quest {quest_sid!r} missing sourceKey/entitySid"
        )
    entity = dict(global_entities_by_key.get(source_key) or {})
    if not entity:
        entity = {"sourceKey": source_key}
    payload = quest_row.get("questPayload")
    if isinstance(payload, dict):
        entity["quest"] = dict(payload)
        # Avoid empty HotA ``quests: []`` / null winning over the story payload.
        entity.pop("quests", None)
        entity.pop("repeatableQuests", None)
    elif "quest" not in entity and "quests" not in entity:
        raise ValueError(
            f"{mission_id}: seer hut quest {quest_sid} missing questPayload and "
            f"global entity quest fields for {source_key!r}; rewalk + rebuild "
            "object_port_manifest, then refresh alignment"
        )
    from seer_hut_campaign_bind import compile_seer_entity_subquests
    from seer_hut_quest import SeerHutQuestError

    try:
        subquests, _, _ = compile_seer_entity_subquests(
            entity,
            hut_entity_sid=hut_sid,
            target_entity_sid=None,
            mission_id=mission_id,
        )
    except SeerHutQuestError as exc:
        raise ValueError(
            f"{mission_id}: seer hut {source_key} QuestScript recompile failed ({exc}); "
            "rewalk + rebuild object_port_manifest, then emit with alignment refresh "
            "so story questPayload / globalEntities carry the decoded quest"
        ) from exc
    return [dict(subquest) for subquest in subquests]


def build_runtime_script_chunk(
    mission_id: str,
    alignment_story: dict[str, Any],
    *,
    dialog_lines: list[dict[str, Any]],
    featured_city_capture_sids: dict[str, str],
    ownership_victory: dict[str, Any] | None = None,
    victory_plan: Any | None = None,
    placed_hero_payload_plan: Any | None = None,
    human_hero_sid: str | None = None,
    global_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # StartTurn briefings use vanilla Story sharing Clone (c_M2/c_M9/c_M10).
    # An earlier "All" experiment did not stop dual Dialog fire; Player.log proved
    # the real cause is QuestSystem.Init running twice after a Map-load NRE reload.
    raw_counters = list(alignment_story.get("counters") or [])
    counters = _runtime_counter_rows(raw_counters, sharing="Clone")
    briefing_segments = alignment_story.get("briefingSegments") or []
    runtime_quests: list[dict[str, Any]] = []

    intro_triggers: list[dict[str, Any]] = []
    bonus_actions = _starting_bonus_dialog_actions(alignment_story)
    if briefing_segments:
        # Same calendar day: fire all Dialog actions in one StartTurn trigger so the
        # engine does not depend on same-pass Counter re-evaluation. Later days use
        # absolute StartTurn day = H3M firstOccurrence + 1.
        day_groups: dict[int, list[tuple[int, dict[str, Any]]]] = {}
        for index, segment in enumerate(briefing_segments):
            trigger_day = int(segment.get("triggerDay") or 1)
            day_groups.setdefault(trigger_day, []).append((index, segment))

        started_set = False
        for trigger_day in sorted(day_groups):
            group = day_groups[trigger_day]
            actions: list[dict[str, Any]] = [
                _dialog_action(f"{mission_id}_briefing_{index}") for index, _segment in group
            ]
            if not started_set:
                actions.append(_counter_set(f"{mission_id}_started", 1))
                started_set = True
            if trigger_day == 1 and bonus_actions:
                actions.extend(bonus_actions)
                bonus_actions = []
            last_index = group[-1][0]
            actions.append(_counter_set(f"{mission_id}_briefing_index", last_index + 1))
            intro_triggers.append(
                {
                    "comment": f"campaign briefing day {trigger_day} ({len(group)} dialogs)",
                    "repeat": False,
                    "conditions": [_briefing_start_turn(trigger_day)],
                    "actions": actions,
                    "conditionsLogic": "And",
                }
            )
        if bonus_actions:
            # Briefings exist but none on absolute day 1 — still offer the bonus once.
            intro_triggers.insert(
                0,
                {
                    "comment": "campaign starting-bonus choice day 1",
                    "repeat": False,
                    "conditions": [_briefing_start_turn(1)],
                    "actions": [_counter_set(f"{mission_id}_started", 1), *bonus_actions],
                    "conditionsLogic": "And",
                },
            )
            started_set = True
    else:
        day1_actions = [_counter_set(f"{mission_id}_started", 1), *bonus_actions]
        intro_triggers.append(
            {
                "comment": "mission start marker",
                "repeat": False,
                "conditions": [_briefing_start_turn(1)],
                "actions": day1_actions,
                "conditionsLogic": "And",
            }
        )

    runtime_quests.append(
        {
            "sid": f"{mission_id}_intro",
            "hidden": True,
            "main": False,
            "activeOnStart": True,
            "comment": f"{mission_id} campaign intro briefing",
            "sharing": "Clone",
            "name": f"{mission_id}_intro",
            "desc": "",
            "subQuests": [
                {
                    "sid": f"{mission_id}_intro_start",
                    "activeOnStart": True,
                    "hidden": False,
                    "name": "",
                    "desc": "",
                    "comment": "",
                    "triggers": intro_triggers,
                }
            ],
            "subQuestGroups": [],
        }
    )

    if placed_hero_payload_plan is not None:
        import campaign_placed_hero_payloads as hero_payloads

        if not isinstance(human_hero_sid, str) or not human_hero_sid.strip():
            raise ValueError(
                f"{mission_id}: human_hero_sid required when placed_hero_payload_plan is set"
            )
        runtime_quests.extend(
            hero_payloads.build_placed_hero_payload_quests(
                mission_id,
                placed_hero_payload_plan,
                start_turn_condition=_briefing_start_turn,
                human_hero_sid=human_hero_sid.strip(),
            )
        )
        rescue_counter_rows = [
            {
                "sid": hero_payloads.prison_rescue_pending_counter_sid(mission_id, index),
                "value": 0,
            }
            for index, _rescue in enumerate(
                getattr(placed_hero_payload_plan, "rescue_grants", []) or []
            )
        ]
        declared_counter_sids = {
            str(row.get("sid"))
            for row in counters
            if isinstance(row, dict) and row.get("sid")
        }
        counters.extend(
            _runtime_counter_rows(
                [
                    row
                    for row in rescue_counter_rows
                    if row["sid"] not in declared_counter_sids
                ],
                sharing="Clone",
            )
        )

    grants = list(alignment_story.get("timedResourceGrants") or alignment_story.get("deferredComputerOrResourceEvents") or [])
    grant_triggers = build_timed_resource_grant_triggers(mission_id, grants)
    town_events = list(alignment_story.get("townEvents") or [])
    grant_triggers.extend(build_town_event_grant_triggers(mission_id, town_events))
    if grant_triggers:
        runtime_quests.append(
            {
                "sid": f"{mission_id}_timed_resource_grants",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": f"{mission_id} H3M computer/resource timed GiveRes grants",
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{mission_id}_timed_resource_grants_fire",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": grant_triggers,
                    }
                ],
                "subQuestGroups": [],
            }
        )

    main_goal = next((row for row in alignment_story.get("quests") or [] if row.get("main")), None)
    objective_text = str((main_goal or {}).get("objectiveText") or "")
    capture_triggers: list[dict[str, Any]] = []
    if victory_plan is not None:
        for row in getattr(victory_plan, "counters", []) or []:
            if isinstance(row, dict) and row.get("sid"):
                counters.extend(_runtime_counter_rows([row], sharing="Clone"))
        capture_triggers.extend(list(getattr(victory_plan, "win_triggers", []) or []))
        loss_triggers = list(getattr(victory_plan, "loss_triggers", []) or [])
    elif ownership_victory is not None:
        loss_triggers = []
        entity_sids = ownership_victory.get("entitySids")
        victory_type = ownership_victory.get("type")
        if victory_type != "TAKEDWELLINGS" or not isinstance(entity_sids, list) or not entity_sids:
            raise ValueError(f"{mission_id}: invalid ownership victory contract: {ownership_victory}")
        if len(set(entity_sids)) != len(entity_sids) or not all(
            isinstance(sid, str) and sid for sid in entity_sids
        ):
            raise ValueError(f"{mission_id}: ownership victory entity SIDs must be unique non-empty strings")
        owned_counter_sid = f"{mission_id}_dwellings_owned"
        counters.extend(_runtime_counter_rows([{"sid": owned_counter_sid, "value": 0}], sharing="Clone"))
        for entity_sid in entity_sids:
            capture_triggers.extend(
                [
                    {
                        "comment": f"capture TAKEDWELLINGS target {entity_sid}",
                        "repeat": True,
                        "conditions": [
                            {"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1}
                        ],
                        "actions": [
                            {"comment": "", "a": "CounterPlus", "p": [owned_counter_sid, "1"]}
                        ],
                        "conditionsLogic": "And",
                    },
                    {
                        "comment": f"lose TAKEDWELLINGS target {entity_sid}",
                        "repeat": True,
                        "conditions": [{"comment": "", "c": "ObjectLose", "p": [entity_sid], "counter": 1}],
                        "actions": [
                            {"comment": "", "a": "CounterMinus", "p": [owned_counter_sid, "1"]}
                        ],
                        "conditionsLogic": "And",
                    },
                ]
            )
        capture_triggers.append(
            {
                "comment": f"win after controlling all {len(entity_sids)} TAKEDWELLINGS targets",
                "repeat": False,
                "conditions": [_counter_condition(owned_counter_sid, "=", len(entity_sids))],
                "actions": [
                    _counter_set(f"{mission_id}_main_goal_complete", 1),
                    {"comment": "", "a": "GameVictory", "p": []},
                ],
                "conditionsLogic": "And",
            }
        )
    else:
        loss_triggers = []
        for source_key in sorted(featured_city_capture_sids):
            entity_sid = featured_city_capture_sids[source_key]
            capture_triggers.append(
                {
                    "comment": f"capture featured city {source_key}",
                    "repeat": False,
                    "conditions": [{"comment": "", "c": "ObjectCaptureEntity", "p": [entity_sid], "counter": 1}],
                    "actions": [
                        _counter_set(f"{mission_id}_main_goal_complete", 1),
                        {"comment": "", "a": "GameVictory", "p": []},
                    ],
                    "conditionsLogic": "And",
                }
            )

    main_subquest_triggers = list(capture_triggers)
    if loss_triggers:
        main_subquest_triggers.extend(loss_triggers)

    # Vanilla quest UI: short parent title + checklist bullets on subquest ``name``
    # LocKit SIDs. Empty subquest name/desc shows as player-visible ``LOC:``.
    objective_bullets = split_objective_bullets(objective_text)
    if not objective_bullets:
        raise ValueError(
            f"{mission_id}: main objective text is empty; cannot build quest-log bullets"
        )

    main_subquests: list[dict[str, Any]] = []
    for index, _bullet in enumerate(objective_bullets, start=1):
        is_primary = index == 1
        main_subquests.append(
            {
                "sid": (
                    f"{mission_id}_main_goal_capture"
                    if is_primary
                    else f"{mission_id}_main_goal_obj_{index}"
                ),
                "activeOnStart": True,
                "hidden": False,
                "name": objective_obj_sid(mission_id, index),
                "desc": None,
                "comment": "",
                "triggers": list(main_subquest_triggers) if is_primary else [],
            }
        )

    runtime_quests.append(
        {
            "sid": f"{mission_id}_main_goal",
            "hidden": False,
            "main": True,
            "activeOnStart": True,
            "comment": objective_text or f"{mission_id} main objective",
            "sharing": "Clone",
            "name": f"{mission_id}_main_goal",
            # Parent desc stays null; attributes live on subquest name bullets
            # (native quest_sub_M* pattern). Avoid cramming the full H3 blurb into
            # one truncated journal paragraph.
            "desc": None,
            "subQuests": main_subquests,
            "subQuestGroups": [],
        }
    )

    for quest_row in alignment_story.get("quests") or []:
        quest_sid = str(quest_row.get("sid") or "")
        if "_map_event_" not in quest_sid:
            continue
        message = str(quest_row.get("message") or "").strip()
        rewards = quest_row.get("rewards") or {}
        has_resources = any(int(value or 0) for value in (rewards.get("resources") or []))
        # Empty HoMM3 EVENT stubs still need 1:1 QuestScript rows (visit counter /
        # ObjectInteractionAfter). Never silently drop alignment map events.
        event_index = quest_sid.rsplit("_", 1)[-1]
        entity_sid = str(quest_row.get("entitySid") or map_event_entity_sid(mission_id, event_index))
        dialog_sid = str(quest_row.get("dialogSid") or map_event_dialog_sid(mission_id, event_index))
        has_guards = bool(quest_row.get("hasGuards"))
        assert_resource_only_rewards(rewards, context=f"{mission_id} map event runtime {event_index}")
        resource_actions: list[dict[str, Any]] = []
        if has_resources:
            resource_actions = resource_delta_actions_from_h3_resources(
                rewards.get("resources"),
                context=f"{mission_id} map event runtime {event_index}",
            )
        visited_counter = f"{mission_id}_map_event_{event_index}_visited"

        if has_guards:
            from campaign_event_ir.compile_backends import compile_guarded_map_event_triggers
            from campaign_event_ir.model import (
                Audience,
                BackendId,
                BackendStatus,
                CampaignEventIR,
                Effects,
                EventScope,
                GuardStack,
                HostKind,
                HostRef,
            )

            squad_entity_sid = str(
                quest_row.get("squadEntitySid") or map_event_guard_squad_entity_sid(mission_id, event_index)
            )
            stacks = nonempty_guard_stacks(
                quest_row.get("guardStacks"),
                context=f"{mission_id} map event runtime {event_index}",
            )
            mask = int(quest_row.get("playersMask") or 0)
            indices = tuple(i for i in range(8) if mask & (1 << i))
            event_ir = CampaignEventIR(
                mission_id=mission_id,
                scope=EventScope.MAP,
                source_identity=f"{mission_id}:map:{quest_row.get('sourceKey')}",
                source_index=int(event_index) if str(event_index).isdigit() else None,
                source_key=str(quest_row.get("sourceKey") or ""),
                name=f"map_event:{quest_row.get('sourceKey')}",
                schedule=None,
                audience=Audience(
                    players_mask=mask,
                    human_eligible=bool(quest_row.get("humanActivate", True)),
                    computer_eligible=bool(quest_row.get("computerActivate")),
                    zero_based_player_indices=indices,
                    human_eligible_layout="map_event_humanActivate",
                ),
                host=HostRef(kind=HostKind.EXACT_SQUAD, source_key=str(quest_row.get("sourceKey") or "")),
                remove_after_visit=bool(quest_row.get("removeAfterVisit")),
                has_guards=True,
                guard_stacks=tuple(
                    GuardStack(creature_type=s["creatureType"], count=s["count"]) for s in stacks
                ),
                effects=Effects(
                    message=message,
                    resources=tuple(rewards.get("resources") or []),
                ),
                is_player_briefing=False,
                is_timed_resource_grant=False,
                selected_backend=BackendId.GUARDED_MAP_EVENT_EXACT_SQUAD,
                backend_status=BackendStatus.SELECTED_UNPROVEN,
                readiness_blockers=(),
            )
            quest_row_for_compile = {
                **quest_row,
                "dialogSid": dialog_sid,
                "squadEntitySid": squad_entity_sid,
                "eventIndex": event_index,
            }
            triggers = compile_guarded_map_event_triggers(event_ir, quest_row=quest_row_for_compile)
            comment = (
                "H3M guarded map event: propActionsBefore Dialog; "
                "SquadKill → GiveRes; exact propSquads host"
            )
        elif str(quest_row.get("hostLifetime") or "") == COLOCATED_HERO_HOST_LIFETIME:
            # hero-spawner does not run propActionsBefore Dialog (runtime-proven).
            # Visit/reward tracking is owned by the BeforeIamVsHero interruption actions.
            triggers = []
            comment = (
                "H3M colocated hero+EVENT: Dialog via BeforeIamVsHero interruption; "
                "no propActionsBefore Dialog on hero-spawner"
            )
        else:
            actions = [_counter_set(visited_counter, 1)]
            actions.extend(resource_actions)
            action_repeat = bool(quest_row.get("actionRepeat"))
            triggers = [
                {
                    "comment": (
                        f"record visit for {entity_sid} without duplicating Dialog"
                        + ("; GiveRes after visit" if resource_actions else "")
                    ),
                    "repeat": action_repeat,
                    "conditions": [_object_interaction_after(entity_sid)],
                    "actions": actions,
                    "conditionsLogic": "And",
                }
            ]
            comment = (
                "H3M map event visit tracked after propActionsBefore Dialog; "
                "resource GiveRes on ObjectInteractionAfter; cleanup lives in propActionsAfter"
            )

        runtime_quests.append(
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

    global_entities_by_key = _global_entities_by_source_key(global_entities)

    for quest_row in alignment_story.get("quests") or []:
        if not isinstance(quest_row, dict) or quest_row.get("kind") != "seer_hut_quest":
            continue
        quest_sid = str(quest_row.get("sid") or "")
        compiled_subquests = _runtime_seer_subquests_for_story_row(
            mission_id,
            quest_row,
            global_entities_by_key=global_entities_by_key,
        )
        if len(compiled_subquests) < 4:
            raise ValueError(
                f"{mission_id}: seer hut quest {quest_sid} missing compiled "
                "offer/incomplete/ready/complete stages"
            )
        subquests: list[dict[str, Any]] = []
        for index, subquest in enumerate(compiled_subquests):
            if not isinstance(subquest, dict):
                raise ValueError(
                    f"{mission_id}: seer hut quest {quest_sid} subquest {index} is not an object"
                )
            subquest_sid = str(subquest.get("sid") or "").strip()
            subquest_triggers = subquest.get("triggers")
            if not subquest_sid or not isinstance(subquest_triggers, list):
                raise ValueError(
                    f"{mission_id}: seer hut quest {quest_sid} subquest {index} "
                    "missing sid/triggers"
                )
            subquests.append(
                {
                    "sid": subquest_sid,
                    "activeOnStart": bool(subquest.get("activeOnStart")),
                    "hidden": bool(subquest.get("hidden", True)),
                    "name": str(subquest.get("name") or ""),
                    "desc": str(subquest.get("desc") or ""),
                    "comment": str(subquest.get("comment") or ""),
                    "triggers": list(subquest_triggers),
                }
            )
        runtime_quests.append(
            {
                "sid": quest_sid,
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": "H3 Seer's Hut → homm3_seer_hut QuestScript FSM (missions 3-7)",
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": subquests,
                "subQuestGroups": [],
            }
        )

    alignment_map_event_sids = {
        str(row.get("sid"))
        for row in (alignment_story.get("quests") or [])
        if isinstance(row, dict) and "_map_event_" in str(row.get("sid") or "")
    }
    runtime_map_event_sids = {
        str(row.get("sid"))
        for row in runtime_quests
        if isinstance(row, dict) and "_map_event_" in str(row.get("sid") or "")
    }
    if alignment_map_event_sids != runtime_map_event_sids:
        missing = sorted(alignment_map_event_sids - runtime_map_event_sids)
        extra = sorted(runtime_map_event_sids - alignment_map_event_sids)
        raise ValueError(
            f"{mission_id}: map-event QuestScript emit must be 1:1 with alignment; "
            f"missing={missing}; extra={extra}"
        )

    interruptions = build_colocated_hero_interruptions(mission_id, alignment_story)

    assert_quest_counter_sids_declared(
        counters=counters,
        quests=runtime_quests,
        mission_id=mission_id,
        interruptions=interruptions,
    )

    return {
        "comment": alignment_story.get("comment") or f"{mission_id} layered-atlas runtime script",
        "aiRolesId": alignment_story.get("aiRolesId") or "",
        "interruptions": interruptions,
        "counters": counters,
        "quests": runtime_quests,
    }


def build_colocated_hero_interruptions(
    mission_id: str,
    alignment_story: dict[str, Any],
) -> list[dict[str, Any]]:
    """Vanilla BeforeIamVsHero interruptions for same-cell EVENT+hero dialogs.

    Player.log proved propActionsBefore Dialog on hero-spawner never loads before
    StartBattleHeroes; native campaign maps use interruptions instead.
    """
    rows: list[dict[str, Any]] = []
    for quest_row in alignment_story.get("quests") or []:
        if not isinstance(quest_row, dict):
            continue
        quest_sid = str(quest_row.get("sid") or "")
        if "_map_event_" not in quest_sid:
            continue
        if str(quest_row.get("hostLifetime") or "") != COLOCATED_HERO_HOST_LIFETIME:
            continue
        event_index = quest_sid.rsplit("_", 1)[-1]
        # Vanilla BeforeIamVsHero.p is the enemy propHeroes.heroSid (c_M2/c_M5),
        # not propEntities.sid — targeting the entity SID never fires.
        hero_sid = str(quest_row.get("dialogHeroSid") or "").strip()
        dialog_sid = str(quest_row.get("dialogSid") or map_event_dialog_sid(mission_id, event_index))
        message = str(quest_row.get("message") or "").strip()
        if not hero_sid:
            raise ValueError(
                f"{mission_id} colocated hero interruption {event_index}: "
                "missing dialogHeroSid (BeforeIamVsHero requires propHeroes.heroSid)"
            )
        if not message and not dialog_sid:
            continue
        interruption_sid = f"{mission_id}_map_event_{event_index}_before_hero"
        visited_counter = f"{mission_id}_map_event_{event_index}_visited"
        actions: list[dict[str, Any]] = [
            {"comment": "", "a": "Dialog", "p": [dialog_sid]},
            _counter_set(visited_counter, 1),
        ]
        rewards = quest_row.get("rewards") or {}
        if any(int(value or 0) for value in (rewards.get("resources") or [])):
            actions.extend(
                resource_delta_actions_from_h3_resources(
                    rewards.get("resources"),
                    context=f"{mission_id} colocated hero interruption {event_index}",
                )
            )
        if quest_row.get("removeAfterVisit"):
            actions.append({"comment": "", "a": "DisableInterruption", "p": [interruption_sid]})
        rows.append(
            {
                "sid": interruption_sid,
                "comment": f"colocated EVENT dialog before fighting {hero_sid}",
                "p": [hero_sid],
                "activeOnStart": True,
                "interruption": "BeforeIamVsHero",
                "actions": actions,
            }
        )
    return rows


def map_quest_sidecar_payload(chunk3: dict[str, Any]) -> dict[str, Any]:
    """Sidecar ``.json`` next to the ``.map`` — counters only; quests stay in chunk 3.

    Fail-closed hygiene for this port: chunk 3 owns runtime QuestScript. (Empty
    sidecar alone does not explain dual Dialog fire — Player.log still doubled
    after quests:[]; the load-NRE → dual QuestSystem.Init path does.)
    """
    if not isinstance(chunk3, dict):
        raise ValueError("map quest sidecar requires chunk 3 dict")
    return {
        "counters": list(chunk3.get("counters") or []),
        "quests": [],
    }


def build_runtime_dialog_lines(mission_id: str, alignment_story: dict[str, Any]) -> list[dict[str, Any]]:
    # Vanilla Story maps keep dialog bodies in Core.zip DB/dialogs, not map chunk 2.
    # Chunk 2 stays empty; Core overlay owns briefing + map-event dialog SIDs.
    return []


def _hero_core_icon_sid(hero_sid: str) -> str:
    """Resolve Core heroes.icon for a Homm3/custom hero SID (dialog avatar base key).

    Returns the short Core icon (e.g. hero_homm3_stronghold_2). Dialog slides use
    ``icons/dialogue/dialogue_<icon>`` so cko dict injection matches vanilla paths.
    """
    import json
    import zipfile

    import port_homecoming_poc as poc

    member = None
    # Prefer faction folder layout: DB/heroes/<faction>/<hero_sid>.json
    if hero_sid.startswith("homm3_"):
        parts = hero_sid.split("_")
        # homm3_<faction>_hero_N
        if len(parts) >= 4 and parts[-2] == "hero":
            faction = "_".join(parts[:-2])  # homm3_stronghold
            member = f"DB/heroes/{faction}/{hero_sid}.json"
    if member is None:
        raise ValueError(f"cannot derive Core hero path for dialog avatar: {hero_sid!r}")
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        if member not in core.namelist():
            raise ValueError(f"missing Core hero row for dialog avatar: {member}")
        doc = json.loads(core.read(member).decode("utf-8-sig"))
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ValueError(f"Core hero row malformed: {member}")
    icon = rows[0].get("icon")
    if not isinstance(icon, str) or not icon.strip():
        raise ValueError(f"Core hero {hero_sid!r} missing icon for dialog avatar")
    return icon.strip()


def dialog_hero_portrait_icon_key(hero_icon_key: str) -> str:
    """Vanilla-shaped dialog avatar icon path for a custom hero Core icon key."""
    icon = str(hero_icon_key or "").strip()
    if not icon.startswith("hero_homm3_"):
        raise ValueError(
            f"dialog hero portrait icon must be hero_homm3_* Core icon key; got {hero_icon_key!r}"
        )
    return f"icons/dialogue/dialogue_{icon}"


def colocated_hero_dialog_avatar(
    hero_record: dict[str, Any],
) -> dict[str, Any]:
    """Vanilla-shaped single-speaker avatar for a same-cell EVENT+hero dialog.

    ``heroSid`` must match emit-time ``propHeroes.heroSid`` (via
    ``resolve_placed_hero_sid``), because ``BeforeIamVsHero.p`` keys on that
    identity. Portrait icon stays on the catalog/donor type — stub SIDs are
    interrupt identity, not Core icon keys.
    """
    import h3_campaign_placed_heroes as placed_campaign_heroes
    import h3m_hero_sid

    hero_type = hero_record.get("heroType")
    if not isinstance(hero_type, int):
        raise ValueError("colocated hero missing heroType for dialog avatar")
    if hero_type == h3m_hero_sid.H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
        raise ValueError("colocated hero dialog avatar cannot use placeholder heroType 255")
    # Match emit SID policy: custom display name → resolve_placed_hero_sid.
    # Object walks set hasName=true; port manifests often omit hasName while still
    # carrying the custom name string (emit recovers it via campaign-chain
    # names_by_type). Use a non-empty name unless hasName is explicitly false.
    entity_name = None
    raw_name = hero_record.get("name")
    if isinstance(raw_name, str) and raw_name.strip() and hero_record.get("hasName") is not False:
        entity_name = raw_name.strip()
    hero_sid, _evidence = placed_campaign_heroes.resolve_placed_hero_sid(
        hero_type, name=entity_name
    )
    catalog_sid = h3m_hero_sid.h3_hero_type_to_hero_sid(hero_type)
    core_icon = _hero_core_icon_sid(catalog_sid)
    icon = dialog_hero_portrait_icon_key(core_icon)
    # Prefer Olden portrait identity when the H3 placed name is a known short form.
    title = str(hero_record.get("name") or "").strip()
    if catalog_sid == "homm3_stronghold_hero_2":
        title = "Gurnisson"
    elif not title:
        title = hero_sid
    return {
        "heroSid": hero_sid,
        "icon": icon,
        "title": title,
        "avatars": [
            {
                "position": 1,
                "icon": icon,
                "isForeground": "true",
                "animations": ["zoomIn"],
            }
        ],
        "titlePosition": 1,
    }


def monster_interact_message(entity: dict[str, Any]) -> str | None:
    """Return custom H3 monster visit text, or None when the stack has no message.

    H3 can set hasMessage=true with an empty string (no box text) — treat that as
    no Dialog. Fail closed when hasMessage=false but non-empty text is present
    (decode / alignment corruption that would silently drop planned flavor).
    """
    if not isinstance(entity, dict):
        raise ValueError("monster_interact_message requires a monster entity dict")
    raw_message = entity.get("message")
    message = str(raw_message or "").strip()
    has_message = entity.get("hasMessage")
    if has_message is False and message:
        raise ValueError(
            f"monster {entity.get('sourceKey')} hasMessage=false but message text is present"
        )
    if message:
        return message
    return None


def core_dialog_entries_from_monster_messages(
    mission_id: str,
    global_entities: list[dict[str, Any]] | None,
    *,
    mission_title: str | None = None,
) -> list[dict[str, Any]]:
    """Core dialog rows for H3 monster-stack custom interact messages.

    OE shows these via propActionsBefore Dialog on the random-squad host
    (native c_M1 free-join shape), not SquadInteraction and not H3's inline
    monster message box.
    """
    import dialog_portrait_plan as portraits
    import surface_emit as emit

    display_title = mission_display_title(mission_id, mission_title)
    entries: list[dict[str, Any]] = []
    for entity in global_entities or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("category") not in {"monster_stack", "monster"} and entity.get(
            "payloadKind"
        ) not in {"monster", "monster_stack"}:
            continue
        message = monster_interact_message(entity)
        if message is None:
            continue
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            raise ValueError(
                f"monster {entity.get('sourceKey')} with interact message missing integer sourceIndex"
            )
        entry: dict[str, Any] = {
            "id": monster_message_dialog_sid(mission_id, source_index),
            "title": display_title,
            "text": message,
            "sourceKey": entity.get("sourceKey"),
            "sourceIndex": source_index,
        }
        subtype = entity.get("templateSubtype")
        if isinstance(subtype, int):
            unit_sid = emit.MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE.get(subtype)
            if unit_sid:
                try:
                    icon = portraits.unit_sid_to_dialog_icon(unit_sid)
                    label = portraits.unit_sid_display_name(unit_sid)
                    entry["title"] = label
                    entry["avatars"] = [
                        {
                            "position": 1,
                            "icon": icon,
                            "isForeground": "true",
                            "animations": ["zoomIn"],
                        }
                    ]
                except ValueError:
                    pass
        entries.append(entry)
    return _apply_dialog_portrait_plans(mission_id, entries)


def core_dialog_entries_from_alignment(
    mission_id: str,
    alignment_story: dict[str, Any],
    *,
    mission_title: str | None = None,
) -> list[dict[str, Any]]:
    display_title = mission_display_title(
        mission_id,
        mission_title or alignment_story.get("missionTitle"),
    )
    entries: list[dict[str, Any]] = []
    for index, segment in enumerate(alignment_story.get("briefingSegments") or []):
        title = str(segment.get("title") or display_title).strip() or display_title
        body = str(segment.get("body") or "").strip()
        if not body:
            continue
        entries.append(
            {
                "id": f"{mission_id}_briefing_{index}",
                "title": title,
                "text": body,
            }
        )
    for quest_row in alignment_story.get("quests") or []:
        if not isinstance(quest_row, dict):
            continue
        quest_sid = str(quest_row.get("sid") or "")
        if "_map_event_" not in quest_sid:
            continue
        message = str(quest_row.get("message") or "").strip()
        if not message:
            continue
        event_index = quest_sid.rsplit("_", 1)[-1]
        entry: dict[str, Any] = {
            "id": str(quest_row.get("dialogSid") or map_event_dialog_sid(mission_id, event_index)),
            "title": display_title,
            "text": message,
        }
        avatars = quest_row.get("dialogAvatars")
        if isinstance(avatars, list) and avatars:
            entry["avatars"] = avatars
            title_override = str(quest_row.get("dialogTitle") or "").strip()
            if title_override:
                entry["title"] = title_override
            title_pos = quest_row.get("dialogTitlePosition")
            if isinstance(title_pos, int):
                entry["titlePosition"] = title_pos
        entries.append(entry)
    for quest_row in alignment_story.get("quests") or []:
        if not isinstance(quest_row, dict) or quest_row.get("kind") != "seer_hut_quest":
            continue
        plan = quest_row.get("questPlan") or {}
        triad = (
            ("dialogFirstSid", "firstVisitText", "Seer's Hut"),
            ("dialogNextSid", "nextVisitText", "Seer's Hut"),
            ("dialogCompletedSid", "completedText", "Seer's Hut"),
        )
        for sid_key, text_key, default_title in triad:
            dialog_sid = str(plan.get(sid_key) or "").strip()
            body = str(plan.get(text_key) or "").strip()
            if not dialog_sid:
                continue
            if not body:
                raise ValueError(
                    f"{mission_id}: seer dialog {dialog_sid!r} has empty {text_key}; "
                    "empty H3 strings must be filled by coalesce_seer_quest_texts before emit"
                )
            entries.append(
                {
                    "id": dialog_sid,
                    "title": default_title,
                    "text": body,
                }
            )
    bonus = alignment_story.get("startingBonus")
    if isinstance(bonus, dict):
        import campaign_starting_bonus as starting_bonus

        entries.append(starting_bonus.build_dialog_entry(bonus))
    return _apply_dialog_portrait_plans(mission_id, entries)


def _apply_dialog_portrait_plans(
    mission_id: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach single/multi-speaker portrait slides without rewriting HoMM3 wording."""
    try:
        import dialog_portrait_plan as portraits
    except ImportError:
        return entries
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Choice/grant dialogs own their slide graph; portrait rewriting would drop answers.
        if entry.get("kind") == "starting_bonus_choice":
            out.append(entry)
            continue
        plan = portraits.plan_dialog_portraits(
            dialog_sid=str(entry.get("id") or ""),
            mission_id=mission_id,
            text=str(entry.get("text") or ""),
            existing_avatars=entry.get("avatars") if isinstance(entry.get("avatars"), list) else None,
            existing_title=str(entry.get("title") or "") or None,
        )
        out.append(portraits.apply_plan_to_dialog_entry(entry, plan))
    return out


def map_event_specs_by_source_key(alignment_story: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for quest_row in alignment_story.get("quests") or []:
        if not isinstance(quest_row, dict):
            continue
        quest_sid = str(quest_row.get("sid") or "")
        if "_map_event_" not in quest_sid:
            continue
        source_key = quest_row.get("sourceKey")
        entity_sid = quest_row.get("entitySid")
        dialog_sid = quest_row.get("dialogSid")
        if source_key is None or not entity_sid or not dialog_sid:
            continue
        has_guards = bool(quest_row.get("hasGuards"))
        event_index = quest_sid.rsplit("_", 1)[-1]
        mission_id = mission_id_from_quest_sid(quest_sid)
        colocated_hero_index = quest_row.get("colocatedHeroHostSourceIndex")
        specs[str(source_key)] = {
            "entitySid": str(entity_sid),
            "dialogSid": str(dialog_sid),
            "hasMessage": bool(str(quest_row.get("message") or "").strip()),
            "removeAfterVisit": bool(quest_row.get("removeAfterVisit")),
            "actionRepeat": bool(quest_row.get("actionRepeat")),
            "hostLifetime": str(quest_row.get("hostLifetime") or "disposable_marker"),
            "colocatedHeroHostSourceIndex": (
                int(colocated_hero_index) if isinstance(colocated_hero_index, int) else None
            ),
            "playersMask": quest_row.get("playersMask"),
            "computerActivate": quest_row.get("computerActivate"),
            "humanActivate": quest_row.get("humanActivate", True),
            "rewards": quest_row.get("rewards"),
            "hasGuards": has_guards,
            "guardStacks": list(quest_row.get("guardStacks") or []),
            "squadEntitySid": (
                str(quest_row.get("squadEntitySid") or map_event_guard_squad_entity_sid(mission_id, event_index))
                if has_guards
                else None
            ),
            "squadOverlaySid": (
                str(
                    quest_row.get("squadOverlaySid")
                    or map_event_guard_squad_overlay_sid(mission_id, event_index)
                )
                if has_guards
                else None
            ),
            "eventIndex": event_index,
            "missionId": mission_id,
        }
    return specs


def mission_id_from_quest_sid(quest_sid: str) -> str:
    marker = "_map_event_"
    if marker not in quest_sid:
        raise ValueError(f"quest sid is not a map-event quest: {quest_sid!r}")
    return quest_sid.split(marker, 1)[0]


def build_briefing_dialog_lines(mission_id: str, alignment_story: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for index, segment in enumerate(alignment_story.get("briefingSegments") or []):
        title = str(segment.get("title") or f"Briefing {index + 1}")
        body = str(segment.get("body") or "")
        text = "\n\n".join(part for part in (title, body) if part)
        lines.append(
            {
                "id": f"{mission_id}_briefing_{index}",
                "text": text,
                "comment": f"briefing_segment_{index}",
            }
        )
    return lines
