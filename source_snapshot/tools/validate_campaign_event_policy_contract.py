#!/usr/bin/env python3
"""Fail-closed contract for shared RoE Castle campaign event policy.

Validates that every batch mission:
- fully walks objects without absorbing the H3M global timed-event table as
  synthetic ROE campaign briefing tails
- decodes global timed events at walkEnd
- builds alignment story payloads with player briefings (triggerDay), hidden
  map-event quests + entity/dialog SIDs, and computer/resource timed grants
- emits QuestScript StartTurn+GiveRes for those grants (recurrence-expanded)
- emits unguarded map-event Dialog + ObjectInteractionAfter GiveRes, and guarded
  exact propSquads with propActionsBefore Dialog + SquadKill GiveRes
  (no SquadInteraction Dialog / no propRewardParams)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Expected player-briefing / deferred counts from live H3C decode (source/static).
EXPECTED_TIMED_EVENT_SHAPES: dict[str, dict[str, int]] = {
    "homecoming": {"events": 7, "playerBriefings": 7, "deferred": 0, "mapEvents": 1},
    "guardian_angels": {"events": 2, "playerBriefings": 2, "deferred": 0, "mapEvents": 0},
    "griffin_cliff": {"events": 4, "playerBriefings": 3, "deferred": 1, "mapEvents": 3},
    "steadwick_liberation": {"events": 4, "playerBriefings": 4, "deferred": 0, "mapEvents": 0},
    "deal_with_the_devil": {"events": 4, "playerBriefings": 4, "deferred": 0, "mapEvents": 2},
    "neutral_affairs": {"events": 4, "playerBriefings": 4, "deferred": 0, "mapEvents": 0},
    "tunnels_and_troglodytes": {"events": 4, "playerBriefings": 4, "deferred": 0, "mapEvents": 0},
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _story_from_alignment(alignment: dict[str, Any]) -> dict[str, Any]:
    chunks = (alignment.get("container") or {}).get("chunks") or alignment.get("chunks") or []
    if len(chunks) < 4 or not isinstance(chunks[3], dict):
        raise ValueError("alignment missing story chunk[3]")
    return chunks[3]


def validate_mission_live(
    *,
    mission_id: str,
    campaign_entry: str,
    block_index: int,
    walk_engine: Any,
    runtime_script: Any,
    load_h3c_block: Any,
    errors: list[str],
    expected_pin: dict[str, int] | None = None,
) -> dict[str, Any]:
    source = load_h3c_block(campaign_entry, block_index)
    walk = walk_engine.walk_objects(
        source.h3m_data,
        source.summary,
        source.templates,
        walk_engine.make_source_metadata(
            extra={
                "campaignEntry": campaign_entry,
                "blockIndex": block_index,
                "missionId": mission_id,
                "h3mSha256": source.h3m_sha256,
            }
        ),
    )
    table = walk["objectTable"]
    gte = walk.get("globalTimedEvents") or {}
    synth = [row for row in (walk.get("records") or []) if row.get("syntheticHeader")]

    require(bool(table.get("complete")), f"{mission_id}: object walk incomplete", errors)
    require(gte.get("status") == "decoded", f"{mission_id}: globalTimedEvents status must be decoded; got {gte.get('status')!r}", errors)
    require(
        len(synth) == 0,
        f"{mission_id}: synthetic ROE campaign briefing records must be zero when global timed events decode; got {len(synth)}",
        errors,
    )

    partitioned = runtime_script.partition_global_timed_events(gte)
    map_event_count = sum(
        1
        for record in (walk.get("records") or [])
        if isinstance(record, dict) and record.get("payloadKind") == "event"
    )
    derived = {
        "events": int(gte.get("eventCount") or 0),
        "playerBriefings": len(partitioned["playerBriefings"]),
        "deferred": len(partitioned["deferredComputerOrResourceEvents"]),
        "mapEvents": map_event_count,
    }
    expected = dict(expected_pin) if expected_pin is not None else derived
    if expected_pin is not None:
        require(
            int(gte.get("eventCount") or 0) == expected["events"],
            f"{mission_id}: expected {expected['events']} global timed events; got {gte.get('eventCount')}",
            errors,
        )
        require(
            len(partitioned["playerBriefings"]) == expected["playerBriefings"],
            f"{mission_id}: expected {expected['playerBriefings']} player briefings; got {len(partitioned['playerBriefings'])}",
            errors,
        )
        require(
            len(partitioned["deferredComputerOrResourceEvents"]) == expected["deferred"],
            f"{mission_id}: expected {expected['deferred']} deferred computer/resource events; "
            f"got {len(partitioned['deferredComputerOrResourceEvents'])}",
            errors,
        )
    return {
        "missionId": mission_id,
        "declaredCount": table.get("declaredCount"),
        "decodedCount": table.get("decodedCount"),
        "stoppedAtPostObjectGlobalTimedEvents": table.get("stoppedAtPostObjectGlobalTimedEvents"),
        "globalTimedEventCount": gte.get("eventCount"),
        "playerBriefings": len(partitioned["playerBriefings"]),
        "deferred": len(partitioned["deferredComputerOrResourceEvents"]),
        "syntheticBriefingRecords": len(synth),
        "missionTitle": source.summary.title,
        "expected": expected,
        "expectedPinned": expected_pin is not None,
        "walk": walk,
        "partitioned": partitioned,
    }


def validate_alignment_artifact(
    *,
    mission_id: str,
    alignment_path: Path,
    expected: dict[str, int],
    runtime_script: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    if not alignment_path.is_file():
        errors.append(f"{mission_id}: missing alignment artifact {alignment_path}")
        return None
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    story = _story_from_alignment(alignment)
    briefings = story.get("briefingSegments") or []
    deferred = story.get("deferredComputerOrResourceEvents") or []
    map_align = story.get("mapEventAlignment") or []
    quests = story.get("quests") or []
    map_quests = [row for row in quests if "_map_event_" in str(row.get("sid") or "")]

    require(
        story.get("briefingSource") == "h3m_global_timed_event",
        f"{mission_id}: alignment briefingSource must be h3m_global_timed_event; got {story.get('briefingSource')!r}",
        errors,
    )
    require(
        len(briefings) == expected["playerBriefings"],
        f"{mission_id}: alignment briefingSegments expected {expected['playerBriefings']}; got {len(briefings)}",
        errors,
    )
    require(
        int(story.get("globalTimedEventCount") or -1) == expected["events"],
        f"{mission_id}: alignment globalTimedEventCount expected {expected['events']}; got {story.get('globalTimedEventCount')}",
        errors,
    )
    require(
        len(deferred) == expected["deferred"],
        f"{mission_id}: alignment deferred events expected {expected['deferred']}; got {len(deferred)}",
        errors,
    )
    require(
        len(map_align) == expected["mapEvents"],
        f"{mission_id}: mapEventAlignment expected {expected['mapEvents']}; got {len(map_align)}",
        errors,
    )
    require(
        len(map_quests) == expected["mapEvents"],
        f"{mission_id}: map-event quests expected {expected['mapEvents']}; got {len(map_quests)}",
        errors,
    )
    for segment in briefings:
        require(
            int(segment.get("triggerDay") or 0) >= 1,
            f"{mission_id}: briefing segment missing triggerDay: {segment.get('sourceIndex')}",
            errors,
        )
        require(
            segment.get("source") == "h3m_global_timed_event",
            f"{mission_id}: briefing segment source must be h3m_global_timed_event",
            errors,
        )
    for quest in map_quests:
        require(quest.get("hidden") is True, f"{mission_id}: map-event quest must be hidden: {quest.get('sid')}", errors)
        require(bool(quest.get("entitySid")), f"{mission_id}: map-event quest missing entitySid: {quest.get('sid')}", errors)
        require(bool(quest.get("dialogSid")), f"{mission_id}: map-event quest missing dialogSid: {quest.get('sid')}", errors)
    for row in map_align:
        require(bool(row.get("entitySid")), f"{mission_id}: mapEventAlignment missing entitySid: {row.get('sourceKey')}", errors)
        require(bool(row.get("dialogSid")), f"{mission_id}: mapEventAlignment missing dialogSid: {row.get('sourceKey')}", errors)

    dialogs = runtime_script.core_dialog_entries_from_alignment(mission_id, story)
    # Dialog generation skips empty briefing bodies and empty map-event messages
    # (see core_dialog_entries_from_alignment). Expect that nonempty count, not
    # raw briefing/map-event row counts. Seer hut quests always emit a 3-dialog triad
    # (empty H3 text becomes the default "Seer's Hut" body).
    seer_dialog_count = 0
    for quest_row in story.get("quests") or []:
        if not isinstance(quest_row, dict) or quest_row.get("kind") != "seer_hut_quest":
            continue
        plan = quest_row.get("questPlan") or {}
        for sid_key in ("dialogFirstSid", "dialogNextSid", "dialogCompletedSid"):
            if str(plan.get(sid_key) or "").strip():
                seer_dialog_count += 1
    expected_dialog_count = (
        sum(1 for segment in briefings if str(segment.get("body") or "").strip())
        + sum(1 for quest in map_quests if str(quest.get("message") or "").strip())
        + seer_dialog_count
    )
    require(
        len(dialogs) == expected_dialog_count,
        f"{mission_id}: dialog entries expected {expected_dialog_count} "
        f"(nonempty briefings+mapEvents+seerTriads; raw briefings={expected['playerBriefings']} "
        f"mapEvents={expected['mapEvents']} seerDialogs={seer_dialog_count}); got {len(dialogs)}",
        errors,
    )
    for entry in dialogs:
        require(
            "Homecoming" not in entry.get("title", "") or mission_id == "homecoming",
            f"{mission_id}: dialog title must not hardcode Homecoming: {entry.get('id')} title={entry.get('title')!r}",
            errors,
        )
        if mission_id != "homecoming":
            require(
                entry.get("title") != "Homecoming",
                f"{mission_id}: dialog title incorrectly hardcoded to Homecoming for {entry.get('id')}",
                errors,
            )

    policy = story.get("eventPolicy") or {}
    require(
        policy.get("schema") == "homm3.olden_campaign_event_policy.v1",
        f"{mission_id}: missing eventPolicy schema on alignment story",
        errors,
    )
    require(
        policy.get("eventRecurrenceDayCap") is None,
        f"{mission_id}: eventPolicy.eventRecurrenceDayCap must be null (no day-cap expansion); "
        f"got {policy.get('eventRecurrenceDayCap')!r}",
        errors,
    )
    computer_policy = str(policy.get("computerOrResourceTimedEvents") or "")
    require(
        "counter_equality_in_days" in computer_policy.lower()
        and "no_day_cap_expansion" in computer_policy.lower()
        and "any_start_turn" in computer_policy.lower(),
        f"{mission_id}: eventPolicy.computerOrResourceTimedEvents must describe CounterEqualityInDays "
        f"+ AnyStartTurn ticks without day-cap expansion; got {computer_policy!r}",
        errors,
    )
    map_policy = str(policy.get("mapEvents") or "")
    require(
        "no_squadinteraction" in map_policy.lower()
        and "squadkill" in map_policy.lower()
        and "exact_propsquads" in map_policy.lower()
        and "proprandomsquads" in map_policy.lower()
        and "prop_actions_before_dialog" in map_policy.lower()
        and "colocated_hero_rebind" in map_policy.lower(),
        f"{mission_id}: eventPolicy.mapEvents must describe exact propSquads + "
        f"propRandomSquads + propActionsBefore Dialog + SquadKill (no SquadInteraction) "
        f"+ colocated hero rebind; got {map_policy!r}",
        errors,
    )
    town_policy = str(policy.get("townEvents") or "")
    require(
        "not_in_scope" not in town_policy.lower(),
        f"{mission_id}: eventPolicy.townEvents must no longer be out of scope; got {town_policy!r}",
        errors,
    )
    for quest in map_quests:
        has_guards = bool(quest.get("hasGuards"))
        if has_guards:
            require(
                bool(quest.get("guardStacks")),
                f"{mission_id}: guarded map-event quest missing guardStacks: {quest.get('sid')}",
                errors,
            )
            require(
                bool(quest.get("squadEntitySid")),
                f"{mission_id}: guarded map-event quest missing squadEntitySid: {quest.get('sid')}",
                errors,
            )
        else:
            require(
                not quest.get("guardStacks"),
                f"{mission_id}: unguarded map-event quest must not carry guardStacks: {quest.get('sid')}",
                errors,
            )
    return {
        "missionId": mission_id,
        "briefingSegments": len(briefings),
        "deferred": len(deferred),
        "mapEvents": len(map_quests),
        "dialogEntries": len(dialogs),
        "missionTitle": story.get("missionTitle"),
    }




def _actions_for_object(properties: dict[str, Any], family: str, object_id: int) -> list[dict[str, Any]]:
    return [
        row
        for row in (properties.get(family) or [])
        if isinstance(row, dict) and row.get("id") == object_id
    ]


def _has_event_rewards(rewards: Any) -> bool:
    if not isinstance(rewards, dict):
        return False
    if any(rewards.get(key) for key in ("skills", "artifacts", "spells", "creatures")):
        return True
    resources = rewards.get("resources") or []
    return isinstance(resources, list) and any(int(value or 0) for value in resources)


def _iter_quest_triggers(quest: dict[str, Any]) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for sub_quest in quest.get("subQuests") or []:
        if isinstance(sub_quest, dict):
            triggers.extend(
                trigger for trigger in (sub_quest.get("triggers") or []) if isinstance(trigger, dict)
            )
    return triggers


def _map_event_prop_entity_rows(properties: dict[str, Any], mission_id: str) -> list[dict[str, Any]]:
    prefix_visit = f"{mission_id}_h3m_map_event_"
    prefix_guard = f"{mission_id}_map_event_"
    rows: list[dict[str, Any]] = []
    for row in properties.get("propEntities") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("sid") or "")
        if sid.startswith(prefix_visit) or (
            sid.startswith(prefix_guard) and sid.endswith("_guard")
        ):
            rows.append(row)
    return rows


def validate_raw_translation_artifact(
    *,
    mission: Any,
    alignment_path: Path,
    expected: dict[str, int],
    live_partitioned: dict[str, list[dict[str, Any]]],
    map_reader: Any,
    runtime_script: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    """Verify that the generated map and runtime script carry the event contract."""
    raw_map_dir = mission.artifact_root / "raw_translation_map" / "maps"
    # Ignore intermediate *.pre_visual_scenery_postpass.map snapshots; only the final
    # *_raw_translation.map is the installable contract artifact.
    raw_map_candidates = (
        sorted(
            path
            for path in raw_map_dir.glob("*.map")
            if path.name.endswith("_raw_translation.map")
        )
        if raw_map_dir.is_dir()
        else []
    )
    if len(raw_map_candidates) != 1:
        errors.append(
            f"{mission.mission_id}: expected exactly one raw translation map in {raw_map_dir}; "
            f"got {len(raw_map_candidates)}"
        )
        return None
    raw_map_path = raw_map_candidates[0]
    try:
        container = map_reader(raw_map_path)
    except Exception as exc:  # pragma: no cover - diagnostic is the contract output
        errors.append(f"{mission.mission_id}: failed to read raw translation map {raw_map_path}: {exc}")
        return None

    chunks = getattr(container, "chunks", None)
    if not isinstance(chunks, list) or len(chunks) < 4:
        errors.append(f"{mission.mission_id}: raw translation map must contain map and runtime-script chunks")
        return None
    map_chunk = chunks[1]
    runtime_chunk = chunks[3]
    if not isinstance(map_chunk, dict) or not isinstance(runtime_chunk, dict):
        errors.append(f"{mission.mission_id}: raw translation map chunks[1] and chunks[3] must be objects")
        return None
    properties = map_chunk.get("objectsProperties")
    objects = map_chunk.get("objects")
    if not isinstance(properties, dict) or not isinstance(objects, list):
        errors.append(f"{mission.mission_id}: raw translation map is missing objects or objectsProperties")
        return None

    if mission.mission_id == "griffin_cliff":
        from scenario_profile import load_scenario_profile  # noqa: WPS433

        profile = load_scenario_profile(
            Path("scenarios/griffin_cliff_roe_castle/raw_translation.profile.json")
        )
        contract = profile.victory_contract
        require(contract is not None, "griffin_cliff: profile must declare victoryContract", errors)
        if contract is not None:
            require(contract.victory_type == "TAKEDWELLINGS", "griffin_cliff: victory type must be TAKEDWELLINGS", errors)
            require(contract.allow_normal_victory is False, "griffin_cliff: allowNormalVictory must be false", errors)
            source_entities = (
                ((json.loads(alignment_path.read_text(encoding="utf-8")).get("alignment") or {})
                 .get("globalObjectProperties") or {}).get("propEntities") or []
            )
            decoded_targets = [
                row
                for row in source_entities
                if isinstance(row, dict)
                and row.get("category") == "external_dwelling"
                and row.get("payloadKind") == "creature_generator"
                and str(row.get("templateAnimation") or "").lower() == "avggrff0.def"
            ]
            decoded_keys = {row.get("sourceKey") for row in decoded_targets}
            require(
                len(decoded_targets) == 7 and set(contract.source_keys) == decoded_keys,
                "griffin_cliff: profile victory source keys must exactly match the seven decoded Griffin Towers",
                errors,
            )
            source_ids: list[int] = []
            for key in contract.source_keys:
                matches = [
                    row
                    for row in source_entities
                    if isinstance(row, dict)
                    and row.get("sourceKey") == key
                    and row.get("category") == "external_dwelling"
                    and row.get("payloadKind") == "creature_generator"
                ]
                require(len(matches) == 1, f"griffin_cliff: victory source {key} must occur exactly once", errors)
                if len(matches) == 1 and isinstance(matches[0].get("sourceIndex"), int):
                    source_ids.append(matches[0]["sourceIndex"])
            entity_rows = [
                row for row in (properties.get("propEntities") or [])
                if isinstance(row, dict) and row.get("id") in source_ids
            ]
            require(len(entity_rows) == 7 and {row.get("id") for row in entity_rows} == set(source_ids),
                    "griffin_cliff: all seven TAKEDWELLINGS targets need one propEntities binding", errors)
            entity_sids = {row.get("sid") for row in entity_rows}
            triggers = [
                trigger
                for quest in (runtime_chunk.get("quests") or [])
                if isinstance(quest, dict)
                for trigger in _iter_quest_triggers(quest)
            ]
            capture_sids = [
                condition.get("p", [None])[0]
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "ObjectCaptureEntity"
                and condition.get("p")
            ]
            lose_sids = [
                condition.get("p", [None])[0]
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "ObjectLose"
                and condition.get("p")
            ]
            game_victories = sum(
                1 for trigger in triggers for action in (trigger.get("actions") or [])
                if isinstance(action, dict) and action.get("a") == "GameVictory"
            )
            counter_sevens = sum(
                1 for trigger in triggers for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "Counter"
                and len(condition.get("p") or []) >= 3 and condition["p"][2] == "7"
            )
            require(len(capture_sids) == 7 and set(capture_sids) == entity_sids,
                    "griffin_cliff: runtime must have one ObjectCaptureEntity per dwelling", errors)
            require(len(lose_sids) == 7 and set(lose_sids) == entity_sids,
                    "griffin_cliff: runtime must have one ObjectLose per dwelling", errors)
            require(game_victories == 1 and counter_sevens == 1,
                    "griffin_cliff: runtime must have exactly one count-7 GameVictory path", errors)
            start_settings = (chunks[0].get("startSettings") or {}) if isinstance(chunks[0], dict) else {}
            require(start_settings.get("DefeatAllEnemiesEnabled") is False,
                    "griffin_cliff: DefeatAllEnemiesEnabled must be false", errors)

    try:
        alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
        story = _story_from_alignment(alignment)
    except Exception as exc:  # pragma: no cover - alignment validation reports the primary error
        errors.append(f"{mission.mission_id}: failed to read alignment for raw event validation: {exc}")
        return None
    map_align = [row for row in (story.get("mapEventAlignment") or []) if isinstance(row, dict)]
    expected_ids = {
        int(row["sourceIndex"])
        for row in map_align
        if isinstance(row.get("sourceIndex"), int)
    }
    event_entity_rows = _map_event_prop_entity_rows(properties, mission.mission_id)
    actual_entity_ids = {row.get("id") for row in event_entity_rows}
    expected_entity_sids = {
        str(row.get("squadEntitySid") if row.get("hasGuards") else row.get("entitySid"))
        for row in map_align
    }
    require(
        len(event_entity_rows) == len(expected_ids)
        and {str(row.get("sid")) for row in event_entity_rows} == expected_entity_sids,
        f"{mission.mission_id}: each map event must have exactly one semantic entity binding",
        errors,
    )
    visible_marker_ids = {
        object_id
        for group in objects
        if isinstance(group, dict)
        and group.get("sid") in {"homm3_landon_map_event_marker", "fx_quest_mark_gold_01"}
        for object_id in (group.get("ids") or [])
        if isinstance(object_id, int) and object_id in expected_ids
    }
    entity_row_by_sid = {
        str(row.get("sid")): row
        for row in event_entity_rows
        if isinstance(row.get("sid"), str)
    }
    unguarded = [row for row in map_align if not row.get("hasGuards")]
    colocated_hero_unguarded = [
        row
        for row in unguarded
        if str(row.get("hostLifetime") or "") == "colocated_hero_host"
    ]
    invisible_unguarded = [
        row
        for row in unguarded
        if (entity_row_by_sid.get(str(row.get("entitySid"))) or {}).get("type") == 1
    ]
    guarded_ids = {
        int(row["sourceIndex"])
        for row in map_align
        if row.get("hasGuards") and isinstance(row.get("sourceIndex"), int)
    }
    # Keymaster's Tent zone markers (raw_translation/border_guard_gates.py) are not map events;
    # validate_border_key_gate_contract.py owns them.
    tent_marker_ids = {
        row.get("id")
        for row in (properties.get("propEntities") or [])
        if isinstance(row, dict)
        and row.get("type") == 1
        and str(row.get("sid") or "").startswith(f"{mission.mission_id}_keymaster_tent_")
    }
    markers = [
        marker for marker in (map_chunk.get("markers") or [])
        if not (isinstance(marker, dict) and marker.get("id") in tent_marker_ids)
    ]
    marker_rows = [
        row for row in (properties.get("propMarkers") or [])
        if not (isinstance(row, dict) and row.get("id") in tent_marker_ids)
    ]
    random_squad_ids = {
        object_id
        for group in objects
        if isinstance(group, dict) and group.get("sid") == "random-squad"
        for object_id in (group.get("ids") or [])
    }
    require(
        len(markers) == len(invisible_unguarded),
        f"{mission.mission_id}: unguarded Zone events must use invisible Zone markers "
        f"(colocated hero hosts excluded)",
        errors,
    )
    require(
        len(marker_rows) == len(invisible_unguarded)
        and all(row.get("type") == 1 and row.get("isActivate") is True for row in marker_rows),
        f"{mission.mission_id}: every invisible event must have one active type-1 propMarker",
        errors,
    )
    # Colocated hero hosts: Dialog on hero-spawner, never Zone, never random-squad.
    hero_spawner_ids = {
        object_id
        for group in objects
        if isinstance(group, dict) and group.get("sid") == "hero-spawner"
        for object_id in (group.get("ids") or [])
        if isinstance(object_id, int)
    }
    hero_nodes = {
        int(node)
        for group in objects
        if isinstance(group, dict) and group.get("sid") == "hero-spawner"
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or [])
        if isinstance(object_id, int) and isinstance(node, int)
    }
    marker_nodes = {
        int(marker["node"])
        for marker in markers
        if isinstance(marker, dict) and isinstance(marker.get("node"), int)
    }
    require(
        not (marker_nodes & hero_nodes),
        f"{mission.mission_id}: Zone event markers must not share a node with hero-spawner "
        f"(colocated EVENT+hero must rebind Dialog onto the hero)",
        errors,
    )
    for event in colocated_hero_unguarded:
        entity_sid = str(event.get("entitySid") or "")
        semantic = entity_row_by_sid.get(entity_sid) or {}
        host_id = semantic.get("id")
        colocated_index = event.get("colocatedHeroHostSourceIndex")
        require(
            semantic.get("type") == 0
            and isinstance(host_id, int)
            and host_id in hero_spawner_ids
            and isinstance(colocated_index, int)
            and host_id == colocated_index,
            f"{mission.mission_id}: colocated hero event {event.get('sourceKey')} must bind "
            f"entity onto hero-spawner id {colocated_index!r}; got type={semantic.get('type')} "
            f"id={host_id!r}",
            errors,
        )
        require(
            isinstance(host_id, int)
            and host_id not in random_squad_ids,
            f"{mission.mission_id}: colocated hero event must not convert host to random-squad "
            f"(adjacent ZoC); host={host_id}",
            errors,
        )
        avatar_icon = event.get("dialogAvatarIcon")
        avatars = event.get("dialogAvatars") or []
        require(
            isinstance(avatar_icon, str)
            and avatar_icon.startswith("icons/dialogue/dialogue_hero_homm3_")
            and isinstance(avatars, list)
            and len(avatars) >= 1
            and avatars[0].get("icon") == avatar_icon,
            f"{mission.mission_id}: colocated hero event {event.get('sourceKey')} must carry "
            f"dialog avatar icon (icons/dialogue/dialogue_hero_homm3_*); got {avatar_icon!r}",
            errors,
        )
        dialog_sid = str(event.get("dialogSid") or "")
        hero_sid = str(event.get("dialogHeroSid") or "")
        source_key = str(event.get("sourceKey") or "")
        interruption_hits = [
            row
            for row in (runtime_chunk.get("interruptions") or [])
            if isinstance(row, dict)
            and row.get("interruption") == "BeforeIamVsHero"
            and hero_sid
            and hero_sid in (row.get("p") or [])
            and any(
                isinstance(action, dict)
                and action.get("a") == "Dialog"
                and action.get("p") == [dialog_sid]
                for action in (row.get("actions") or [])
            )
        ]
        require(
            bool(hero_sid),
            f"{mission.mission_id}: colocated hero event {source_key} missing dialogHeroSid",
            errors,
        )
        require(
            len(interruption_hits) == 1,
            f"{mission.mission_id}: colocated hero event {source_key} requires one "
            f"BeforeIamVsHero interruption Dialog for {dialog_sid!r} targeting "
            f"heroSid {hero_sid!r}; got {len(interruption_hits)}",
            errors,
        )
        # Native BeforeIamVsHero matches propHeroes.heroSid on the fought hero.
        # dialogHeroSid must be that same identity (stub or roster), not a type-only
        # catalog SID that diverges from the emitted propHero row.
        prop_heroes = [
            row
            for row in (properties.get("propHeroes") or [])
            if isinstance(row, dict)
        ]
        prop_hero_sids = {
            str(row.get("heroSid") or "")
            for row in prop_heroes
            if isinstance(row.get("heroSid"), str) and str(row.get("heroSid") or "").strip()
        }
        require(
            bool(hero_sid) and hero_sid in prop_hero_sids,
            f"{mission.mission_id}: colocated hero event {source_key} dialogHeroSid "
            f"{hero_sid!r} must equal some propHeroes.heroSid on the map",
            errors,
        )
        host_index = event.get("colocatedHeroHostSourceIndex")
        if isinstance(host_index, int):
            host_rows = [row for row in prop_heroes if row.get("id") == host_index]
            require(
                len(host_rows) == 1 and str(host_rows[0].get("heroSid") or "") == hero_sid,
                f"{mission.mission_id}: colocated hero event {source_key} dialogHeroSid "
                f"{hero_sid!r} must equal propHeroes row id={host_index} "
                f"(got {[row.get('heroSid') for row in host_rows]!r})",
                errors,
            )
    # Every BeforeIamVsHero.p[0] must be present in propHeroes (catch non-colocated
    # interrupts that target a missing fought-hero identity).
    prop_hero_sids_all = {
        str(row.get("heroSid") or "")
        for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict)
        and isinstance(row.get("heroSid"), str)
        and str(row.get("heroSid") or "").strip()
    }
    for row in runtime_chunk.get("interruptions") or []:
        if not isinstance(row, dict) or row.get("interruption") != "BeforeIamVsHero":
            continue
        target = (row.get("p") or [None])[0]
        interrupt_sid = str(row.get("sid") or "")
        require(
            isinstance(target, str)
            and target.strip()
            and target in prop_hero_sids_all,
            f"{mission.mission_id}: BeforeIamVsHero {interrupt_sid!r} p[0]={target!r} "
            f"must equal some propHeroes.heroSid",
            errors,
        )
    require(
        guarded_ids <= random_squad_ids,
        f"{mission.mission_id}: guarded events must be physical random-squad objects",
        errors,
    )
    prop_squads = properties.get("propSquads") or []
    for event in map_align:
        if not event.get("hasGuards"):
            continue
        source_index = event.get("sourceIndex")
        if not isinstance(source_index, int):
            continue
        exact_rows = [
            row
            for row in prop_squads
            if isinstance(row, dict)
            and row.get("id") == source_index
            and isinstance(row.get("unitProps"), list)
            and row.get("unitProps")
        ]
        require(
            len(exact_rows) == 1,
            f"{mission.mission_id}: guarded event {source_index} must have exact propSquads.unitProps",
            errors,
        )
        if exact_rows:
            expected_stacks = [
                (stack["creatureType"], stack["count"])
                for stack in (event.get("guardStacks") or [])
                if isinstance(stack, dict)
            ]
            # Count-level equality only; SID mapping is validated separately via creatureType coverage.
            require(
                len(exact_rows[0]["unitProps"]) == len([s for s in expected_stacks if s[1] > 0]),
                f"{mission.mission_id}: guarded event {source_index} unitProps length mismatch",
                errors,
            )
    require(
        not {
            int(row["sourceIndex"])
            for row in invisible_unguarded
            if isinstance(row.get("sourceIndex"), int)
        }.intersection(visible_marker_ids),
        f"{mission.mission_id}: visible question-mark event objects are forbidden",
        errors,
    )

    entity_by_id = {
        row.get("id"): row
        for row in event_entity_rows
        if isinstance(row.get("id"), int)
    }
    for event in map_align:
        source_index = event.get("sourceIndex")
        entity_sid = event.get("entitySid")
        dialog_sid = event.get("dialogSid")
        has_guards = bool(event.get("hasGuards"))
        if not isinstance(source_index, int) or not isinstance(entity_sid, str) or not isinstance(dialog_sid, str):
            continue
        expected_prop_sid = (
            str(event.get("squadEntitySid") or "")
            if has_guards
            else entity_sid
        )
        semantic_entity = entity_row_by_sid.get(expected_prop_sid) or {}
        host_id = semantic_entity.get("id")
        entity = next(
            (
                row
                for row in event_entity_rows
                if row.get("id") == host_id and row.get("sid") == expected_prop_sid
            ),
            None,
        )
        require(
            isinstance(entity, dict) and entity.get("sid") == expected_prop_sid,
            f"{mission.mission_id}: raw event {source_index} entity SID must be {expected_prop_sid!r}; "
            f"got {(entity or {}).get('sid')!r}",
            errors,
        )
        before_rows = _actions_for_object(properties, "propActionsBefore", host_id)
        dialog_actions = [
            action
            for row in before_rows
            for action in (row.get("actions") or [])
            if isinstance(action, dict) and action.get("a") == "Dialog" and action.get("p") == [dialog_sid]
        ]
        host_lifetime = str(event.get("hostLifetime") or "")
        has_message = bool(str(event.get("message") or "").strip())
        if has_guards:
            if has_message:
                require(
                    len(dialog_actions) == 1,
                    f"{mission.mission_id}: guarded raw event {source_index} must have one "
                    f"propActionsBefore Dialog for {dialog_sid!r}; got {len(dialog_actions)}",
                    errors,
                )
                for row in before_rows:
                    if not isinstance(row, dict):
                        continue
                    if any(
                        isinstance(action, dict) and action.get("a") == "Dialog"
                        for action in (row.get("actions") or [])
                    ):
                        require(
                            row.get("repeat") is True,
                            f"{mission.mission_id}: guarded event {source_index} Dialog Before "
                            f"must repeat=true (flee-and-retry)",
                            errors,
                        )
                        require(
                            "computerActivate" not in row,
                            f"{mission.mission_id}: propActionsBefore must not contain computerActivate",
                            errors,
                        )
            else:
                require(
                    len(dialog_actions) == 0,
                    f"{mission.mission_id}: guarded event {source_index} without message must not "
                    f"emit propActionsBefore Dialog; got {len(dialog_actions)}",
                    errors,
                )
            squad_rows = _actions_for_object(properties, "propSquads", source_index)
            require(
                len(squad_rows) == 1
                and isinstance(squad_rows[0].get("unitProps"), list)
                and len(squad_rows[0].get("unitProps") or []) > 0,
                f"{mission.mission_id}: guarded raw event {source_index} must bind exact "
                f"propSquads.unitProps",
                errors,
            )
            random_rows = _actions_for_object(properties, "propRandomSquads", source_index)
            require(
                len(random_rows) == 1,
                f"{mission.mission_id}: guarded raw event {source_index} must bind propRandomSquads "
                f"(SpawnsCreator requires it on random-squad hosts)",
                errors,
            )
            if random_rows:
                overlay_sid = str(event.get("squadOverlaySid") or "")
                require(
                    overlay_sid
                    and overlay_sid in (random_rows[0].get("sids") or []),
                    f"{mission.mission_id}: guarded event {source_index} propRandomSquads.sids "
                    f"must include squadOverlaySid {overlay_sid!r}",
                    errors,
                )
                require(
                    float(random_rows[0].get("requestedValue") or 0) > 0,
                    f"{mission.mission_id}: guarded event {source_index} requestedValue must be "
                    f"positive squadValue budget",
                    errors,
                )
            if event.get("computerActivate") is False:
                ai_rows = _actions_for_object(properties, "propAiIntetations", source_index)
                require(
                    any(row.get("aiIgnore") is True for row in ai_rows),
                    f"{mission.mission_id}: guarded event {source_index} with computerActivate=false "
                    f"must emit propAiIntetations.aiIgnore",
                    errors,
                )
        elif host_lifetime == "colocated_hero_host":
            require(
                len(dialog_actions) == 0,
                f"{mission.mission_id}: colocated hero event {source_index} must not use "
                f"propActionsBefore Dialog (hero-spawner skips it); got {len(dialog_actions)}",
                errors,
            )
            after_rows = _actions_for_object(properties, "propActionsAfter", host_id)
            delete_actions = [
                action
                for row in after_rows
                for action in (row.get("actions") or [])
                if isinstance(action, dict) and action.get("a") == "DeleteEntity" and action.get("p") == [entity_sid]
            ]
            require(
                len(delete_actions) == 0,
                f"{mission.mission_id}: colocated hero event must not DeleteEntity the hero-spawner",
                errors,
            )
        else:
            require(
                len(dialog_actions) == 1,
                f"{mission.mission_id}: raw event {source_index} must have one Dialog action for {dialog_sid!r}; got {len(dialog_actions)}",
                errors,
            )
            if event.get("computerActivate") is False:
                # Unguarded Zone hosts may use marker id (host_id), not H3M sourceIndex.
                ai_rows = _actions_for_object(properties, "propAiIntetations", host_id)
                require(
                    any(row.get("aiIgnore") is True for row in ai_rows),
                    f"{mission.mission_id}: unguarded event {source_index} host {host_id} with "
                    f"computerActivate=false must emit propAiIntetations.aiIgnore",
                    errors,
                )
            for row in before_rows:
                require(
                    "computerActivate" not in row,
                    f"{mission.mission_id}: propActionsBefore must not contain computerActivate",
                    errors,
                )
                sides = str(row.get("sides") or "")
                if sides:
                    for token in sides.split(","):
                        require(
                            token.isdigit() and 0 <= int(token) <= 7,
                            f"{mission.mission_id}: propActions sides must be zero-based; got {sides!r}",
                            errors,
                        )
            after_rows = _actions_for_object(properties, "propActionsAfter", host_id)
            delete_actions = [
                action
                for row in after_rows
                for action in (row.get("actions") or [])
                if isinstance(action, dict) and action.get("a") == "DeleteEntity" and action.get("p") == [entity_sid]
            ]
            expect_delete = (
                1
                if event.get("removeAfterVisit")
                and event.get("hostLifetime")
                not in {"persistent_object", "colocated_hero_host"}
                else 0
            )
            require(
                len(delete_actions) == expect_delete,
                f"{mission.mission_id}: raw event {source_index} removeAfterVisit/hostLifetime wiring mismatch; "
                f"got {len(delete_actions)} DeleteEntity actions",
                errors,
            )
            prop_repeat = any(row.get("repeat") is True for row in before_rows)
            require(
                bool(event.get("actionRepeat")) == prop_repeat,
                f"{mission.mission_id}: unguarded event {source_index} actionRepeat mismatch "
                f"(alignment={event.get('actionRepeat')} prop={prop_repeat})",
                errors,
            )
        activation_family = (
            "propMarkers"
            if semantic_entity.get("type") == 1
            else "propActivations"
        )
        activation_rows = _actions_for_object(properties, activation_family, host_id)
        require(
            any(
                row.get("isActivate") is True
                if activation_family == "propMarkers"
                else row.get("isActive") is True
                for row in activation_rows
            ),
            f"{mission.mission_id}: raw event {source_index} must be active",
            errors,
        )
        reward_rows = _actions_for_object(properties, "propRewardParams", source_index)
        require(
            len(reward_rows) == 0,
            f"{mission.mission_id}: raw event {source_index} must not use propRewardParams "
            f"(GiveRes is QuestScript-only); got {len(reward_rows)}",
            errors,
        )

    raw_map_event_quests = [
        row
        for row in (runtime_chunk.get("quests") or [])
        if isinstance(row, dict) and str(row.get("sid") or "").startswith(f"{mission.mission_id}_map_event_")
    ]
    actual_quest_sids = {row.get("sid") for row in raw_map_event_quests}
    expected_quest_sids = {f"{mission.mission_id}_map_event_{index}" for index in range(expected["mapEvents"])}
    require(
        actual_quest_sids == expected_quest_sids,
        f"{mission.mission_id}: raw runtime map-event quests expected {sorted(expected_quest_sids)}; got {sorted(actual_quest_sids, key=str)}",
        errors,
    )

    # Batch-derived: deferred timed grants + town events emit StartTurn + GiveRes.
    deferred_grants = list(live_partitioned.get("deferredComputerOrResourceEvents") or [])
    town_events = [row for row in (story.get("townEvents") or []) if isinstance(row, dict)]
    grant_quest = next(
        (
            row
            for row in (runtime_chunk.get("quests") or [])
            if isinstance(row, dict) and row.get("sid") == f"{mission.mission_id}_timed_resource_grants"
        ),
        None,
    )
    if deferred_grants or town_events:
        require(
            isinstance(grant_quest, dict),
            f"{mission.mission_id}: missing timed_resource_grants quest for "
            f"{len(deferred_grants)} deferred + {len(town_events)} town grants",
            errors,
        )
        grant_triggers = _iter_quest_triggers(grant_quest) if isinstance(grant_quest, dict) else []
        resource_delta_count = sum(
            1
            for trigger in grant_triggers
            for action in (trigger.get("actions") or [])
            if isinstance(action, dict) and action.get("a") in {"GiveRes", "RemoveRes"}
        )
        start_turn_count = sum(
            1
            for trigger in grant_triggers
            for condition in (trigger.get("conditions") or [])
            if isinstance(condition, dict) and condition.get("c") == "StartTurn"
        )
        require(
            resource_delta_count > 0 and start_turn_count > 0,
            f"{mission.mission_id}: timed grants must emit StartTurn+GiveRes/RemoveRes; "
            f"got startTurn={start_turn_count} resourceDelta={resource_delta_count}",
            errors,
        )
        # One calendar StartTurn first-fire per grant/town event (side audience is
        # Clone/forSides). Repeating grants also emit CED + AnyStartTurn CounterPlus.
        expected_start_turn_count = 0
        expected_ced_count = 0
        for grant in deferred_grants:
            expected_start_turn_count += 1
            if int(grant.get("nextOccurrence") or 0) > 0:
                expected_ced_count += 1
        for town_event in town_events:
            expected_start_turn_count += 1
            if int(town_event.get("nextOccurrence") or 0) > 0:
                expected_ced_count += 1
        ced_count = sum(
            1
            for trigger in grant_triggers
            for condition in (trigger.get("conditions") or [])
            if isinstance(condition, dict) and condition.get("c") == "CounterEqualityInDays"
        )
        any_start_turn_count = sum(
            1
            for trigger in grant_triggers
            for condition in (trigger.get("conditions") or [])
            if isinstance(condition, dict) and condition.get("c") == "AnyStartTurn"
        )
        counter_plus_count = sum(
            1
            for trigger in grant_triggers
            for action in (trigger.get("actions") or [])
            if isinstance(action, dict) and action.get("a") == "CounterPlus"
        )
        require(
            start_turn_count == expected_start_turn_count,
            f"{mission.mission_id}: timed grant StartTurn count expected {expected_start_turn_count}; "
            f"got {start_turn_count}",
            errors,
        )
        require(
            ced_count == expected_ced_count,
            f"{mission.mission_id}: timed grant CounterEqualityInDays count expected {expected_ced_count}; "
            f"got {ced_count}",
            errors,
        )
        require(
            any_start_turn_count == expected_ced_count,
            f"{mission.mission_id}: timed grant AnyStartTurn tick count expected {expected_ced_count}; "
            f"got {any_start_turn_count}",
            errors,
        )
        require(
            counter_plus_count == expected_ced_count,
            f"{mission.mission_id}: timed grant CounterPlus tick count expected {expected_ced_count}; "
            f"got {counter_plus_count}",
            errors,
        )
    else:
        require(
            grant_quest is None,
            f"{mission.mission_id}: timed_resource_grants quest must be absent when deferred=0 and townEvents=0",
            errors,
        )

    # Guarded map events: propActionsBefore Dialog; SquadKill → GiveRes.
    # Unguarded: ObjectInteractionAfter (+ GiveRes).
    for index, event in enumerate(map_align):
        quest_sid = f"{mission.mission_id}_map_event_{index}"
        quest = next((row for row in raw_map_event_quests if row.get("sid") == quest_sid), None)
        require(isinstance(quest, dict), f"{mission.mission_id}: missing runtime quest {quest_sid}", errors)
        if not isinstance(quest, dict):
            continue
        triggers = _iter_quest_triggers(quest)
        has_guards = bool(event.get("hasGuards"))
        dialog_sid = event.get("dialogSid")
        host_lifetime = str(event.get("hostLifetime") or "")
        if host_lifetime == "colocated_hero_host":
            require(
                len(triggers) == 0,
                f"{mission.mission_id}: colocated {quest_sid} must have empty quest triggers "
                f"(BeforeIamVsHero interruption owns Dialog); got {len(triggers)}",
                errors,
            )
            continue
        if has_guards:
            squad_kill = [
                condition
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "SquadKill"
            ]
            squad_interaction = [
                condition
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "SquadInteraction"
            ]
            dialog_on_interaction = [
                action
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "SquadInteraction"
                for action in (trigger.get("actions") or [])
                if isinstance(action, dict) and action.get("a") == "Dialog" and action.get("p") == [dialog_sid]
            ]
            require(
                len(squad_kill) == 1 and len(squad_interaction) == 0 and len(dialog_on_interaction) == 0,
                f"{mission.mission_id}: guarded {quest_sid} must SquadKill only "
                f"(Dialog is propActionsBefore; no SquadInteraction); "
                f"interaction={len(squad_interaction)} dialog={len(dialog_on_interaction)} "
                f"squadKill={len(squad_kill)}",
                errors,
            )
            require(
                squad_kill[0].get("p") == [event.get("squadEntitySid")],
                f"{mission.mission_id}: guarded {quest_sid} SquadKill must target {event.get('squadEntitySid')!r}",
                errors,
            )
            if _has_event_rewards(event.get("rewards")):
                resource_deltas = [
                    action
                    for trigger in triggers
                    for condition in (trigger.get("conditions") or [])
                    if isinstance(condition, dict) and condition.get("c") == "SquadKill"
                    for action in (trigger.get("actions") or [])
                    if isinstance(action, dict) and action.get("a") in {"GiveRes", "RemoveRes"}
                ]
                require(
                    len(resource_deltas) > 0,
                    f"{mission.mission_id}: guarded {quest_sid} with resources must "
                    f"GiveRes/RemoveRes on SquadKill",
                    errors,
                )
        else:
            visit = [
                condition
                for trigger in triggers
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "ObjectInteractionAfter"
            ]
            require(
                len(visit) == 1,
                f"{mission.mission_id}: unguarded {quest_sid} must use ObjectInteractionAfter; got {len(visit)}",
                errors,
            )
            if _has_event_rewards(event.get("rewards")):
                resource_deltas = [
                    action
                    for trigger in triggers
                    for action in (trigger.get("actions") or [])
                    if isinstance(action, dict) and action.get("a") in {"GiveRes", "RemoveRes"}
                ]
                require(
                    len(resource_deltas) > 0,
                    f"{mission.mission_id}: unguarded {quest_sid} with resources must "
                    f"GiveRes/RemoveRes on visit",
                    errors,
                )

    expected_briefings_by_day: dict[int, list[str]] = {}
    for index, segment in enumerate(live_partitioned.get("playerBriefings") or []):
        day = int(segment.get("triggerDay") or 0)
        expected_briefings_by_day.setdefault(day, []).append(f"{mission.mission_id}_briefing_{index}")
    actual_briefings_by_day: dict[int, list[str]] = {}
    intro = next(
        (
            row
            for row in (runtime_chunk.get("quests") or [])
            if isinstance(row, dict) and row.get("sid") == f"{mission.mission_id}_intro"
        ),
        None,
    )
    intro_triggers = _iter_quest_triggers(intro) if isinstance(intro, dict) else []
    for trigger in intro_triggers:
        start_turn = [
            condition
            for condition in (trigger.get("conditions") or [])
            if isinstance(condition, dict) and condition.get("c") == "StartTurn"
        ]
        dialog_ids = [
            str(action.get("p")[0])
            for action in (trigger.get("actions") or [])
            if isinstance(action, dict)
            and action.get("a") == "Dialog"
            and isinstance(action.get("p"), list)
            and action.get("p")
        ]
        if len(start_turn) == 1 and dialog_ids:
            params = start_turn[0].get("p") or []
            if len(params) >= 2:
                # StartTurn p = [week, day-of-week]; compare on absolute day in month 1.
                absolute_day = (int(params[0]) - 1) * 7 + int(params[1])
                actual_briefings_by_day.setdefault(absolute_day, []).extend(dialog_ids)
    # Starting-bonus Dialog is co-emitted on day-1 StartTurn by campaign_starting_bonus;
    # strip it so this check stays briefing-only.
    bonus_sid = f"{mission.mission_id}_starting_bonus"
    actual_briefings_compare: dict[int, list[str]] = {}
    for day, ids in actual_briefings_by_day.items():
        filtered = [dialog_id for dialog_id in ids if dialog_id != bonus_sid]
        if filtered:
            actual_briefings_compare[day] = filtered
    require(
        actual_briefings_compare == expected_briefings_by_day,
        f"{mission.mission_id}: raw StartTurn briefing wiring expected {expected_briefings_by_day}; got {actual_briefings_by_day}",
        errors,
    )

    # Creature SID table must cover every live guarded creatureType in this mission.
    guarded_types: set[int] = set()
    for event in map_align:
        if not event.get("hasGuards"):
            continue
        for stack in event.get("guardStacks") or []:
            if isinstance(stack, dict) and isinstance(stack.get("creatureType"), int):
                guarded_types.add(int(stack["creatureType"]))
    approach_cell_dir = Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc" / "approach_cell"
    poc_dir = Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"
    if str(poc_dir) not in sys.path:
        sys.path.insert(0, str(poc_dir))
    if str(approach_cell_dir) not in sys.path:
        sys.path.insert(0, str(approach_cell_dir))
    import campaign_runtime_script as campaign_script  # noqa: WPS433
    import surface_emit as emit_mod  # noqa: WPS433 — validator-local import after path pin

    for creature_type in sorted(guarded_types):
        if creature_type in emit_mod.H3_CREATURE_EMPTY_TYPES:
            continue
        require(
            creature_type in emit_mod.H3_CREATURE_TYPE_TO_UNIT_SID,
            f"{mission.mission_id}: guarded creatureType {creature_type} missing from "
            f"H3_CREATURE_TYPE_TO_UNIT_SID / MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE",
            errors,
        )
        if creature_type in emit_mod.MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE:
            unit_sid = emit_mod.MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE[creature_type]
            logic = emit_mod.h3_unit_logic_rows().get(unit_sid)
            require(
                isinstance(logic, dict),
                f"{mission.mission_id}: Core unit logic missing for map-event guard SID {unit_sid}",
                errors,
            )

    # HoMM3 character==0 (Compliant) stacks always join — never hostile random-squad.
    alignment_doc = json.loads(alignment_path.read_text(encoding="utf-8"))
    joinable_monsters = [
        row
        for row in (alignment_doc.get("globalEntities") or [])
        if isinstance(row, dict)
        and row.get("category") == "monster_stack"
        and row.get("character") == 0
    ]
    random_by_id = {
        row.get("id"): row
        for row in (properties.get("propRandomSquads") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    for monster in joinable_monsters:
        source_key = monster.get("sourceKey")
        source_index = monster.get("sourceIndex")
        subtype = monster.get("templateSubtype")
        require(
            isinstance(source_index, int),
            f"{mission.mission_id}: joinable monster {source_key} missing integer sourceIndex",
            errors,
        )
        require(
            isinstance(subtype, int) and subtype in emit_mod.CONCRETE_MONSTER_UNIT_BY_SUBTYPE,
            f"{mission.mission_id}: joinable monster {source_key} subtype={subtype} "
            f"missing from CONCRETE_MONSTER_UNIT_BY_SUBTYPE",
            errors,
        )
        if not isinstance(source_index, int):
            continue
        row = random_by_id.get(source_index)
        require(
            isinstance(row, dict),
            f"{mission.mission_id}: joinable monster {source_key} (object {source_index}) "
            f"missing propRandomSquads row",
            errors,
        )
        if not isinstance(row, dict):
            continue
        expected_unit = emit_mod.CONCRETE_MONSTER_UNIT_BY_SUBTYPE.get(subtype)
        require(
            row.get("reactionType") == 4
            and row.get("isFreeDiplomacy") is True
            and row.get("isCampaignFreeDiplomacy") is True
            and row.get("isEscape") is True
            and row.get("customTopUnit") == expected_unit,
            f"{mission.mission_id}: joinable monster {source_key} must emit free-join "
            f"propRandomSquads (reactionType=4, isFreeDiplomacy, customTopUnit={expected_unit!r}); "
            f"got reactionType={row.get('reactionType')} isFreeDiplomacy={row.get('isFreeDiplomacy')} "
            f"customTopUnit={row.get('customTopUnit')!r}",
            errors,
        )

    # H3 monster custom visit messages → propActionsBefore Dialog (OE interact model).
    # Native donor: Story_maps/c_M1.map free-join packs (sides="", Dialog Before).
    # Covers free-join (character==0) join flavor and hostile pre-fight lines alike —
    # both need Dialog wiring whenever non-empty message text is present.
    before_by_id = {
        row.get("id"): row
        for row in (properties.get("propActionsBefore") or [])
        if isinstance(row, dict) and row.get("type") == 0 and isinstance(row.get("id"), int)
    }
    message_monsters: list[dict[str, Any]] = []
    for row in alignment_doc.get("globalEntities") or []:
        if not isinstance(row, dict) or row.get("category") != "monster_stack":
            continue
        try:
            text = campaign_script.monster_interact_message(row)
        except ValueError as exc:
            require(False, f"{mission.mission_id}: {exc}", errors)
            continue
        if text is not None:
            message_monsters.append(row)
    free_join_message_count = sum(
        1 for row in message_monsters if row.get("character") == 0
    )
    overlay_root = mission.artifact_root / "raw_translation_map" / "core_overlay"
    for monster in message_monsters:
        source_key = monster.get("sourceKey")
        source_index = monster.get("sourceIndex")
        is_free_join = monster.get("character") == 0
        join_label = "free-join message" if is_free_join else "message"
        require(
            isinstance(source_index, int),
            f"{mission.mission_id}: {join_label} monster {source_key} missing integer sourceIndex",
            errors,
        )
        if not isinstance(source_index, int):
            continue
        expected_text = campaign_script.monster_interact_message(monster)
        require(
            expected_text is not None,
            f"{mission.mission_id}: {join_label} monster {source_key} resolved empty interact text",
            errors,
        )
        dialog_sid = campaign_script.monster_message_dialog_sid(mission.mission_id, source_index)
        before = before_by_id.get(source_index)
        require(
            isinstance(before, dict),
            f"{mission.mission_id}: {join_label} monster {source_key} (object {source_index}) "
            f"missing propActionsBefore Dialog host row",
            errors,
        )
        if not isinstance(before, dict):
            continue
        actions = before.get("actions") or []
        dialog_hits = [
            action
            for action in actions
            if isinstance(action, dict)
            and action.get("a") == "Dialog"
            and action.get("p") == [dialog_sid]
        ]
        require(
            before.get("sides") == ""
            and before.get("repeat") is False
            and len(dialog_hits) == 1
            and not any(
                isinstance(action, dict) and action.get("c") == "SquadInteraction"
                for action in actions
            ),
            f"{mission.mission_id}: {join_label} monster {source_key} must use propActionsBefore "
            f"Dialog {dialog_sid!r} with sides='' repeat=false (no SquadInteraction); "
            f"got {before}",
            errors,
        )
        # Core overlay must carry the Dialog row (install merges this into Core.zip).
        dialog_hits_fs = list(overlay_root.glob(f"**/DB/dialogs/dialogs/**/{dialog_sid}.json"))
        if not dialog_hits_fs:
            # Some overlays nest under custom_maps/<Mission>/
            dialog_hits_fs = list(overlay_root.rglob(f"{dialog_sid}.json"))
        require(
            len(dialog_hits_fs) >= 1,
            f"{mission.mission_id}: {join_label} monster {source_key} missing core_overlay "
            f"dialog file for {dialog_sid!r}",
            errors,
        )
    if free_join_message_count:
        # Explicit pin so free-join join-flavor regressions cannot hide behind
        # "no message monsters" when character==0 packs lose their text wiring.
        require(
            free_join_message_count
            == sum(
                1
                for row in message_monsters
                if row.get("character") == 0
                and isinstance(row.get("sourceIndex"), int)
                and isinstance(before_by_id.get(row["sourceIndex"]), dict)
                and any(
                    isinstance(a, dict)
                    and a.get("a") == "Dialog"
                    and a.get("p")
                    == [
                        campaign_script.monster_message_dialog_sid(
                            mission.mission_id, row["sourceIndex"]
                        )
                    ]
                    for a in (before_by_id[row["sourceIndex"]].get("actions") or [])
                )
            ),
            f"{mission.mission_id}: {free_join_message_count} free-join custom join "
            f"message pack(s) must each have propActionsBefore Dialog wiring",
            errors,
        )

    return {
        "missionId": mission.mission_id,
        "rawMap": str(raw_map_path),
        "briefingStartTurnDays": sorted(actual_briefings_by_day),
        "mapEvents": len(event_entity_rows),
        "deferredGrantStartTurns": (
            sum(
                1
                for trigger in _iter_quest_triggers(grant_quest)
                for condition in (trigger.get("conditions") or [])
                if isinstance(condition, dict) and condition.get("c") == "StartTurn"
            )
            if isinstance(grant_quest, dict)
            else 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--manifest",
        default="scenarios/roe_castle_campaign/batch_manifest.json",
        help="Campaign batch manifest",
    )
    parser.add_argument(
        "--mission",
        action="append",
        dest="missions",
        help="Optional missionId filter (default: all missions in manifest).",
    )
    parser.add_argument(
        "--skip-alignment-artifacts",
        action="store_true",
        help="Only validate live H3C walks/event partition (skip committed alignment JSON)",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import campaign_runtime_script as runtime_script
    import h3m_object_walk as walk_engine
    import port_homecoming_poc
    from campaign_mission import load_batch_manifest
    from h3c_mission_source import load_h3c_block

    errors: list[str] = []
    live_results: list[dict[str, Any]] = []
    alignment_results: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    manifest = load_batch_manifest((repo_root / args.manifest).resolve())
    selected = set(args.missions) if args.missions else None

    for mission in manifest.missions:
        mission_id = mission.mission_id
        if selected is not None and mission_id not in selected:
            continue
        live = validate_mission_live(
            mission_id=mission_id,
            campaign_entry=mission.campaign_entry,
            block_index=mission.block_index,
            walk_engine=walk_engine,
            runtime_script=runtime_script,
            load_h3c_block=load_h3c_block,
            errors=errors,
            expected_pin=EXPECTED_TIMED_EVENT_SHAPES.get(mission_id),
        )
        live_results.append({k: v for k, v in live.items() if k not in {"walk", "partitioned"}})
        expected = live["expected"]
        if args.skip_alignment_artifacts:
            continue
        # Homecoming alignment may live under layered_ir for legacy layouts.
        alignment_path = mission.alignment_path
        if not alignment_path.is_file():
            alt = mission.layered_ir_dir / f"{mission.mission_id}.olden_storage_alignment.json"
            if alt.is_file():
                alignment_path = alt
        result = validate_alignment_artifact(
            mission_id=mission_id,
            alignment_path=alignment_path,
            expected=expected,
            runtime_script=runtime_script,
            errors=errors,
        )
        if result is not None:
            alignment_results.append(result)
            raw_result = validate_raw_translation_artifact(
                mission=mission,
                alignment_path=alignment_path,
                expected=expected,
                live_partitioned=live["partitioned"],
                map_reader=port_homecoming_poc.read_olden_map_container,
                runtime_script=runtime_script,
                errors=errors,
            )
            if raw_result is not None:
                raw_results.append(raw_result)

    if errors:
        print("Campaign event policy contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Campaign event policy contract PASS")
    print(
        json.dumps(
            {
                "manifest": args.manifest,
                "live": live_results,
                "alignments": alignment_results,
                "rawMaps": raw_results,
                "proofBoundary": (
                    "source/static H3C decode + generated alignment/QuestScript/raw map; "
                    "StartTurn GiveRes, SquadKill, and map-event dialog wiring are "
                    "generated-artifact validated; runtime gameplay remains user-unvalidated"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
