"""Compile CampaignEventIR backends into QuestScript / map-property shapes.

Static/generated shapes only. Delivery readiness stays fail-closed until runtime
proof clears blockers in readiness.py.
"""

from __future__ import annotations

from typing import Any

from .audience_encode import encode_prop_actions_sides, should_emit_ai_ignore
from .model import BackendId, CampaignEventIR, EventScope, HostKind
from .schedule_encode import (
    any_start_turn_every_day_condition,
    counter_equality_in_days_condition,
    counter_plus_action,
    counter_set_action,
    start_turn_condition,
)


def _give_res_actions(resources: tuple[int, ...] | list[int], *, context: str) -> list[dict[str, Any]]:
    import campaign_runtime_script as runtime_script

    return runtime_script.resource_delta_actions_from_h3_resources(list(resources), context=context)


def timed_resource_arm_counter_sid(mission_id: str, source_index: int | None) -> str:
    return f"{mission_id}_timed_grant_{source_index}_armed"


def timed_town_resource_arm_counter_sid(mission_id: str, event_index: int | None) -> str:
    return f"{mission_id}_timed_grant_town_{event_index}_armed"


def compile_repeating_resource_triggers(
    event: CampaignEventIR,
    *,
    arm_counter_sid: str | None = None,
) -> list[dict[str, Any]]:
    """Emit first-fire StartTurn grant + CounterPlus/CED interval recurrence.

    ``StartTurn`` is week/day (Clone sharing owns side audience).
    ``CounterEqualityInDays`` matches counter **value**, so recurrence uses a
    daily ``AnyStartTurn`` → ``CounterPlus`` tick and CED on the interval value.
    The timer counter must start at ``TIMER_PREARM_VALUE`` (see schedule_encode).

    ``arm_counter_sid`` overrides the default global timed-grant arm counter when
    compiling town-hosted grants (``*_timed_grant_town_*_armed``).
    """

    if event.selected_backend not in {
        BackendId.REPEATING_RESOURCE,
        BackendId.ONE_SHOT_TIMED_RESOURCE,
        BackendId.TOWN_OWNERSHIP_AWARE,
    }:
        raise ValueError(f"{event.source_identity}: not a timed-resource backend")
    if event.schedule is None:
        raise ValueError(f"{event.source_identity}: timed resource requires schedule")
    context = event.source_identity
    give = _give_res_actions(event.effects.resources, context=context)
    first_day = int(event.schedule.trigger_day)
    triggers: list[dict[str, Any]] = [
        {
            "comment": f"{context} first grant day {first_day}",
            "repeat": False,
            "conditions": [start_turn_condition(first_day, context=context)],
            "actions": list(give),
            "conditionsLogic": "And",
        }
    ]
    if not event.schedule.is_repeating:
        return triggers

    arm_sid = arm_counter_sid or timed_resource_arm_counter_sid(event.mission_id, event.source_index)
    interval = int(event.schedule.next_occurrence)
    if interval < 1:
        raise ValueError(f"{context}: repeating grant requires nextOccurrence >= 1")

    # Reset timer after first grant so CED cannot use pre-arm Plus ticks.
    triggers[0]["actions"] = list(triggers[0]["actions"]) + [counter_set_action(arm_sid, 0)]
    # CED grant trigger must be listed before the daily Plus trigger so that on
    # the fire day CounterSet(0) runs before CounterPlus(1).
    triggers.append(
        {
            "comment": f"{context} repeating every {interval} days (CED value == {interval})",
            "repeat": True,
            "conditions": [counter_equality_in_days_condition(arm_sid, interval)],
            "actions": list(give) + [counter_set_action(arm_sid, 0)],
            "conditionsLogic": "And",
        }
    )
    triggers.append(
        {
            "comment": f"{context} daily timer tick",
            "repeat": True,
            "conditions": [any_start_turn_every_day_condition()],
            "actions": [counter_plus_action(arm_sid, 1)],
            "conditionsLogic": "And",
        }
    )
    return triggers


def compile_guarded_map_event_triggers(event: CampaignEventIR, *, quest_row: dict[str, Any]) -> list[dict[str, Any]]:
    """SquadKill → rewards / one-shot cleanup.

    Pre-battle Dialog is owned by ``propActionsBefore`` on the random-squad host
    (interrupting Actions Before). QuestScript ``SquadInteraction`` must not call
    Dialog — it cannot pause combat init (Unfrozen mapmaking guide).
    """

    import campaign_runtime_script as runtime_script

    squad_entity_sid = str(quest_row.get("squadEntitySid") or "")
    if not squad_entity_sid:
        raise ValueError(f"{event.source_identity}: guarded event missing squad entity SID")
    if event.effects.has_message and not str(quest_row.get("dialogSid") or "").strip():
        raise ValueError(
            f"{event.source_identity}: guarded event with message requires dialogSid "
            f"for propActionsBefore Dialog emit"
        )
    event_index = str(quest_row.get("eventIndex") or event.source_index)
    visited = f"{event.mission_id}_map_event_{event_index}_visited"
    kill_actions: list[dict[str, Any]] = []
    if event.effects.has_resources:
        kill_actions.extend(_give_res_actions(event.effects.resources, context=event.source_identity))
    kill_actions.append(runtime_script._counter_set(visited, 1))
    if event.remove_after_visit:
        kill_actions.append({"comment": "", "a": "DeleteEntity", "p": [squad_entity_sid]})
    return [
        {
            "comment": f"SquadKill rewards for {squad_entity_sid}",
            "repeat": False,
            "conditions": [{"comment": "", "c": "SquadKill", "p": [squad_entity_sid], "counter": 1}],
            "actions": kill_actions,
            "conditionsLogic": "And",
        }
    ]


def map_event_action_repeat(event: CampaignEventIR) -> bool:
    """Callback recurrence is independent of physical host deletion."""

    if event.has_guards:
        return False
    if event.host.kind == HostKind.PERSISTENT_OBJECT and event.remove_after_visit is False:
        return True
    return False


def map_event_prop_actions_sides(event: CampaignEventIR) -> str:
    return encode_prop_actions_sides(event.audience, context=event.source_identity)


def map_event_emit_ai_ignore(event: CampaignEventIR) -> bool:
    return should_emit_ai_ignore(computer_eligible=event.audience.computer_eligible)


def town_event_host_entity_sid(event: CampaignEventIR) -> str | None:
    """Featured-city capture SID when the town is a named featured city."""

    import campaign_runtime_script as runtime_script

    town_name = event.host.town_name
    if not town_name:
        return None
    return runtime_script.featured_capture_entity_sid(event.mission_id, city_name=town_name)
