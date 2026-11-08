"""Build CampaignEventIR census from live H3C object walks.

Every decoded global, map, and town event becomes one IR row. This module does
not emit Olden maps; it only inventories source fields and delivery blockers.
"""

from __future__ import annotations

from typing import Any

import h3m_format as h3m

from .model import (
    Audience,
    BackendStatus,
    BatchEventCensus,
    CampaignEventIR,
    Effects,
    EventScope,
    GuardStack,
    HostKind,
    HostRef,
    MissionEventCensus,
    Schedule,
)
from .readiness import players_mask_zero_based_indices, with_readiness


def _resources_tuple(raw: Any, *, context: str) -> tuple[int, ...]:
    values = list(raw or [])
    if len(values) > 7:
        raise ValueError(f"{context}: resources length {len(values)} exceeds 7")
    while len(values) < 7:
        values.append(0)
    return tuple(int(value or 0) for value in values)


def _audience_from_mask(
    players_mask: Any,
    *,
    human_eligible: bool | None,
    computer_eligible: bool,
    human_eligible_layout: str,
    context: str,
) -> Audience:
    if players_mask is None:
        raise ValueError(f"{context}: players mask is required")
    mask = int(players_mask)
    return Audience(
        players_mask=mask,
        human_eligible=human_eligible,
        computer_eligible=bool(computer_eligible),
        zero_based_player_indices=players_mask_zero_based_indices(mask, context=context),
        human_eligible_layout=human_eligible_layout,
    )


def _schedule_from_occurrence(
    *,
    first_occurrence: Any,
    next_occurrence: Any,
    trigger_day: Any | None = None,
    context: str,
) -> Schedule:
    first = int(first_occurrence or 0)
    nxt = int(next_occurrence or 0)
    if first < 0:
        raise ValueError(f"{context}: firstOccurrence must be >= 0; got {first}")
    if nxt < 0:
        raise ValueError(f"{context}: nextOccurrence must be >= 0; got {nxt}")
    day = int(trigger_day) if trigger_day is not None else first + 1
    if day < 1:
        raise ValueError(f"{context}: triggerDay must be >= 1; got {day}")
    return Schedule(
        first_occurrence=first,
        next_occurrence=nxt,
        trigger_day=day,
        is_repeating=nxt > 0,
    )


def _guard_stacks(raw: Any, *, context: str) -> tuple[GuardStack, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{context}: guardStacks must be a list")
    empty_types = {0xFF, 0xFFFF}
    out: list[GuardStack] = []
    for stack in raw:
        if not isinstance(stack, dict):
            raise ValueError(f"{context}: malformed guard stack {stack!r}")
        creature_type = stack.get("creatureType")
        count = stack.get("count")
        if not isinstance(creature_type, int) or not isinstance(count, int):
            raise ValueError(f"{context}: guard stack missing creatureType/count: {stack!r}")
        if count <= 0 or creature_type in empty_types:
            continue
        slot = stack.get("slot")
        out.append(
            GuardStack(
                creature_type=creature_type,
                count=count,
                slot=int(slot) if isinstance(slot, int) else None,
            )
        )
    return tuple(out)


def _classify_global(message: str, computer_affected: bool, has_resources: bool) -> tuple[bool, bool]:
    is_player_briefing = bool(message.strip()) and not computer_affected
    is_timed_grant = computer_affected or has_resources
    if not is_player_briefing and not is_timed_grant:
        raise ValueError(
            "global timed event has neither player briefing message nor computer/resource effects"
        )
    return is_player_briefing, is_timed_grant


def _unresolved_draft(**kwargs: Any) -> CampaignEventIR:
    return CampaignEventIR(
        selected_backend=None,
        backend_status=BackendStatus.UNRESOLVED,
        readiness_blockers=(),
        **kwargs,
    )


def _global_event_ir(*, mission_id: str, event: dict[str, Any]) -> CampaignEventIR:
    index = int(event["index"])
    context = f"{mission_id}/global/{index}"
    message = str(event.get("message") or "")
    resources = _resources_tuple(event.get("resources"), context=context)
    computer_affected = bool(event.get("computerAffected"))
    is_briefing, is_grant = _classify_global(message, computer_affected, any(resources))
    human_raw = event.get("humanAffected")
    human_eligible = None if human_raw is None else bool(human_raw)
    layout = (
        "hota_explicit_byte"
        if human_raw is not None
        else "roe_ab_sod_no_human_affected_byte"
    )
    source_key = f"global:{index}"
    draft = _unresolved_draft(
        mission_id=mission_id,
        scope=EventScope.GLOBAL,
        source_identity=f"{mission_id}:{source_key}",
        source_index=index,
        source_key=source_key,
        name=str(event.get("name") or "").strip(),
        schedule=_schedule_from_occurrence(
            first_occurrence=event.get("firstOccurrence"),
            next_occurrence=event.get("nextOccurrence"),
            trigger_day=event.get("triggerDay"),
            context=context,
        ),
        audience=_audience_from_mask(
            event.get("playersMask"),
            human_eligible=human_eligible,
            computer_eligible=computer_affected,
            human_eligible_layout=layout,
            context=context,
        ),
        host=HostRef(kind=HostKind.NONE),
        remove_after_visit=None,
        has_guards=False,
        guard_stacks=(),
        effects=Effects(message=message, resources=resources),
        is_player_briefing=is_briefing,
        is_timed_resource_grant=is_grant,
    )
    return with_readiness(draft)


def _map_event_ir(
    *,
    mission_id: str,
    record: dict[str, Any],
    colocated_hero_keys: frozenset[str] = frozenset(),
) -> CampaignEventIR:
    source_key = str(record.get("key") or "")
    if not source_key:
        raise ValueError(f"{mission_id}: map event missing key")
    context = f"{mission_id}/map/{source_key}"
    box = record.get("boxContent") or {}
    message_and_guards = box.get("messageAndGuards") or {}
    rewards = box.get("rewards") or {}
    has_guards = bool(message_and_guards.get("hasGuards"))
    guard_stacks = _guard_stacks(message_and_guards.get("guardStacks"), context=context)
    remove_after_visit = bool(record.get("removeAfterVisit"))
    # Some AB/SoD maps set hasGuards with only empty 0xFFFF slots. Keep the source
    # flag for inventory, but do not claim an exact-squad host without stacks.
    if has_guards and guard_stacks:
        host_kind = HostKind.EXACT_SQUAD
    elif source_key in colocated_hero_keys and not guard_stacks:
        # Same-cell placed hero owns combat; EVENT text rebinds onto hero-spawner.
        host_kind = HostKind.COLOCATED_HERO
    elif remove_after_visit:
        host_kind = HostKind.DISPOSABLE_MARKER
    else:
        host_kind = HostKind.PERSISTENT_OBJECT
    message = str(message_and_guards.get("message") or "")
    draft = _unresolved_draft(
        mission_id=mission_id,
        scope=EventScope.MAP,
        source_identity=f"{mission_id}:map:{source_key}",
        source_index=int(record["index"]) if record.get("index") is not None else None,
        source_key=source_key,
        name=f"map_event:{source_key}",
        schedule=None,
        audience=_audience_from_mask(
            record.get("playersMask"),
            human_eligible=bool(record.get("humanActivate", True)),
            computer_eligible=bool(record.get("computerActivate")),
            human_eligible_layout="map_event_humanActivate",
            context=context,
        ),
        host=HostRef(kind=host_kind, source_key=source_key),
        remove_after_visit=remove_after_visit,
        has_guards=has_guards,
        guard_stacks=guard_stacks,
        effects=Effects(
            message=message,
            resources=_resources_tuple(rewards.get("resources"), context=context),
            experience=int(rewards.get("experience") or 0),
            mana=int(rewards.get("mana") or 0),
            morale=int(rewards.get("morale") or 0),
            luck=int(rewards.get("luck") or 0),
            primary_skill=int(rewards.get("primarySkill") or 0),
            skills=tuple(rewards.get("skills") or ()),
            artifacts=tuple(rewards.get("artifacts") or ()),
            spells=tuple(rewards.get("spells") or ()),
            creatures=tuple(
                dict(item) if isinstance(item, dict) else item
                for item in (rewards.get("creatures") or ())
            ),
        ),
        is_player_briefing=False,
        is_timed_resource_grant=False,
    )
    return with_readiness(draft)


def _town_event_ir(
    *,
    mission_id: str,
    town_record: dict[str, Any],
    event_index: int,
    event: dict[str, Any],
) -> CampaignEventIR:
    town_key = str(town_record.get("key") or "")
    if not town_key:
        raise ValueError(f"{mission_id}: town event host missing key")
    source_key = f"town:{town_key}:event:{event_index}"
    context = f"{mission_id}/{source_key}"
    growth_raw = event.get("creatureGrowth")
    growth = None if growth_raw is None else tuple(int(value or 0) for value in growth_raw)
    h3m_version = int(town_record.get("h3mVersion") or 0)
    layout = (
        "town_event_hota_explicit"
        if h3m_version == h3m.H3M_VERSION_HOTA
        else "town_event_roe_human_affected_hardcoded_true"
    )
    draft = _unresolved_draft(
        mission_id=mission_id,
        scope=EventScope.TOWN,
        source_identity=f"{mission_id}:{source_key}",
        source_index=event_index,
        source_key=source_key,
        name=str(event.get("name") or "").strip(),
        schedule=_schedule_from_occurrence(
            first_occurrence=event.get("firstOccurrence"),
            next_occurrence=event.get("nextOccurrence"),
            context=context,
        ),
        audience=_audience_from_mask(
            event.get("players"),
            human_eligible=bool(event.get("humanAffected")),
            computer_eligible=bool(event.get("computerAffected")),
            human_eligible_layout=layout,
            context=context,
        ),
        host=HostRef(
            kind=HostKind.TOWN,
            source_key=town_key,
            town_name=str(town_record.get("name") or "") or None,
            town_event_index=event_index,
        ),
        remove_after_visit=None,
        has_guards=False,
        guard_stacks=(),
        effects=Effects(
            message=str(event.get("message") or ""),
            resources=_resources_tuple(event.get("resources"), context=context),
            event_buildings_mask=event.get("eventBuildingsMask"),
            creature_growth=growth,
        ),
        is_player_briefing=False,
        is_timed_resource_grant=True,
    )
    return with_readiness(draft)


def build_mission_event_census_from_walk(
    *,
    mission_id: str,
    campaign_entry: str,
    block_index: int,
    h3m_sha256: str,
    walk: dict[str, Any],
) -> MissionEventCensus:
    """Inventory every decoded event from one object walk into IR."""

    events: list[CampaignEventIR] = []
    gte = walk.get("globalTimedEvents") or {}
    if gte.get("status") != "decoded":
        raise ValueError(
            f"{mission_id}: globalTimedEvents status must be decoded; got {gte.get('status')!r}"
        )
    for event in gte.get("events") or []:
        events.append(_global_event_ir(mission_id=mission_id, event=event))

    records = walk.get("records") or []
    heroes_by_key: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("key") or "")
        if not key:
            layer = record.get("layer", 0)
            x, y = record.get("x"), record.get("y")
            if x is None or y is None:
                continue
            key = f"{int(layer)}:{int(x)}:{int(y)}"
        if record.get("payloadKind") == "hero_or_prison":
            heroes_by_key.add(key)

    colocated_hero_keys: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("payloadKind") != "event":
            continue
        key = str(record.get("key") or "")
        if not key or key not in heroes_by_key:
            continue
        box = (record.get("boxContent") or {}).get("messageAndGuards") or {}
        guard_stacks = box.get("guardStacks") or []
        nonempty = [
            stack
            for stack in guard_stacks
            if isinstance(stack, dict)
            and int(stack.get("creatureType") or 0xFFFF) != 0xFFFF
            and int(stack.get("count") or 0) > 0
        ]
        if not nonempty:
            colocated_hero_keys.add(key)

    for record in records:
        if record.get("payloadKind") == "event":
            events.append(
                _map_event_ir(
                    mission_id=mission_id,
                    record=record,
                    colocated_hero_keys=frozenset(colocated_hero_keys),
                )
            )
        town_events = record.get("townEvents") or []
        if town_events:
            for event_index, town_event in enumerate(town_events):
                events.append(
                    _town_event_ir(
                        mission_id=mission_id,
                        town_record=record,
                        event_index=event_index,
                        event=town_event,
                    )
                )

    identities = [event.source_identity for event in events]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{mission_id}: duplicate CampaignEventIR sourceIdentity values")

    return MissionEventCensus(
        mission_id=mission_id,
        campaign_entry=campaign_entry,
        block_index=block_index,
        h3m_sha256=h3m_sha256,
        events=tuple(events),
    )


def build_mission_event_census(
    *,
    mission_id: str,
    campaign_entry: str,
    block_index: int,
    load_h3c_block: Any,
    walk_engine: Any,
) -> MissionEventCensus:
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
    return build_mission_event_census_from_walk(
        mission_id=mission_id,
        campaign_entry=campaign_entry,
        block_index=block_index,
        h3m_sha256=source.h3m_sha256,
        walk=walk,
    )


def build_batch_event_census(
    *,
    missions: Any,
    load_h3c_block: Any,
    walk_engine: Any,
) -> BatchEventCensus:
    rows: list[MissionEventCensus] = []
    for mission in missions:
        rows.append(
            build_mission_event_census(
                mission_id=mission.mission_id,
                campaign_entry=mission.campaign_entry,
                block_index=mission.block_index,
                load_h3c_block=load_h3c_block,
                walk_engine=walk_engine,
            )
        )
    return BatchEventCensus(missions=tuple(rows))
