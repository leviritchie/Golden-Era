"""Typed procedural-scenario mechanics compiled to native QuestScript rows.

Presentation is deliberately absent from this module. Mechanical events may
carry stable UI labels, but compiling them never emits Dialog, Print, database,
or localization rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence, TypeAlias

MECHANICAL_EVENT_SCHEMA = "olden.procedural.mechanical_event.v1"
_SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COUNTER_OPERATORS = frozenset({"=", "!=", "<", "<=", ">", ">="})


def _require_sid(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _SID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a non-empty stable SID; got {value!r}")
    return value


def _require_label(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    if len(value) > 160:
        raise ValueError(f"{field} exceeds 160 characters")
    return value


@dataclass(frozen=True)
class TurnTrigger:
    """Fire on a 1-based absolute adventure-map day."""

    day: int

    def __post_init__(self) -> None:
        if isinstance(self.day, bool) or not isinstance(self.day, int) or self.day < 1:
            raise ValueError(f"turn day must be an integer >= 1; got {self.day!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "turn", "day": self.day}


@dataclass(frozen=True)
class VisitTrigger:
    entity_sid: str

    def __post_init__(self) -> None:
        _require_sid(self.entity_sid, field="visit entity_sid")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "visit", "entitySid": self.entity_sid}


@dataclass(frozen=True)
class SquadDefeatTrigger:
    squad_sid: str

    def __post_init__(self) -> None:
        _require_sid(self.squad_sid, field="squad defeat squad_sid")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "squad_defeat", "squadSid": self.squad_sid}


@dataclass(frozen=True)
class CaptureTrigger:
    entity_sid: str

    def __post_init__(self) -> None:
        _require_sid(self.entity_sid, field="capture entity_sid")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "capture", "entitySid": self.entity_sid}


@dataclass(frozen=True)
class CounterTrigger:
    counter_sid: str
    value: int
    operator: str = "="

    def __post_init__(self) -> None:
        _require_sid(self.counter_sid, field="counter trigger counter_sid")
        if self.operator != "=":
            raise ValueError(
                "counter trigger operator must be '=' for the proven native backend"
            )
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError(f"counter trigger value must be an integer; got {self.value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "counter",
            "counterSid": self.counter_sid,
            "operator": self.operator,
            "value": self.value,
        }


class CounterOperation(str, Enum):
    SET = "set"
    PLUS = "plus"


@dataclass(frozen=True)
class CounterAction:
    counter_sid: str
    value: int
    operation: CounterOperation = CounterOperation.SET

    def __post_init__(self) -> None:
        _require_sid(self.counter_sid, field="counter action counter_sid")
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError(f"counter action value must be an integer; got {self.value!r}")
        if not isinstance(self.operation, CounterOperation):
            raise ValueError(f"counter action operation is invalid: {self.operation!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "counter",
            "counterSid": self.counter_sid,
            "operation": self.operation.value,
            "value": self.value,
        }


@dataclass(frozen=True)
class ResourceAction:
    resource: str
    amount: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource, str) or not _RESOURCE_RE.fullmatch(self.resource):
            raise ValueError(f"resource must be a canonical lowercase SID; got {self.resource!r}")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int) or self.amount == 0:
            raise ValueError(f"resource amount must be a non-zero integer; got {self.amount!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "resource", "resource": self.resource, "amount": self.amount}


@dataclass(frozen=True)
class ObjectiveProgressAction:
    """Complete the subquest that owns the compiled trigger."""

    objective_sid: str

    def __post_init__(self) -> None:
        _require_sid(self.objective_sid, field="objective progress objective_sid")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "objective_progress", "objectiveSid": self.objective_sid}


@dataclass(frozen=True)
class VictoryAction:
    """The only supported scenario-completion action."""

    victory_sid: str

    def __post_init__(self) -> None:
        _require_sid(self.victory_sid, field="victory victory_sid")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "victory", "victorySid": self.victory_sid}


TriggerSpec: TypeAlias = (
    TurnTrigger | VisitTrigger | SquadDefeatTrigger | CaptureTrigger | CounterTrigger
)
ActionSpec: TypeAlias = (
    CounterAction | ResourceAction | ObjectiveProgressAction | VictoryAction
)


@dataclass(frozen=True)
class MechanicalEventSpec:
    """Immutable mechanics for one native QuestScript trigger."""

    event_id: str
    triggers: tuple[TriggerSpec, ...]
    actions: tuple[ActionSpec, ...]
    repeat: bool = False
    title: str = ""
    objective_label: str | None = None
    schema: str = MECHANICAL_EVENT_SCHEMA

    def __post_init__(self) -> None:
        _require_sid(self.event_id, field="event_id")
        if not self.triggers:
            raise ValueError(f"{self.event_id}: at least one trigger is required")
        if not self.actions:
            raise ValueError(f"{self.event_id}: at least one action is required")
        if self.title:
            _require_label(self.title, field=f"{self.event_id} title")
        if self.objective_label is not None:
            _require_label(
                self.objective_label,
                field=f"{self.event_id} objective_label",
            )
        if self.schema != MECHANICAL_EVENT_SCHEMA:
            raise ValueError(
                f"{self.event_id}: unsupported mechanical event schema {self.schema!r}"
            )
        for trigger in self.triggers:
            if not isinstance(
                trigger,
                (TurnTrigger, VisitTrigger, SquadDefeatTrigger, CaptureTrigger, CounterTrigger),
            ):
                raise TypeError(f"{self.event_id}: unsupported trigger {type(trigger).__name__}")
        for action in self.actions:
            if not isinstance(
                action,
                (CounterAction, ResourceAction, ObjectiveProgressAction, VictoryAction),
            ):
                raise TypeError(f"{self.event_id}: unsupported action {type(action).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "eventId": self.event_id,
            "repeat": self.repeat,
            "title": self.title,
            "objectiveLabel": self.objective_label,
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "actions": [action.to_dict() for action in self.actions],
        }


def _native_condition(trigger: TriggerSpec, *, event_id: str) -> dict[str, Any]:
    if isinstance(trigger, TurnTrigger):
        week, day = divmod(trigger.day - 1, 7)
        return {
            "comment": event_id,
            "c": "StartTurn",
            "p": [str(week + 1), str(day + 1)],
            "counter": 1,
        }
    if isinstance(trigger, VisitTrigger):
        condition_name = "ObjectInteractionAfter"
        sid = trigger.entity_sid
    elif isinstance(trigger, SquadDefeatTrigger):
        condition_name = "SquadKill"
        sid = trigger.squad_sid
    elif isinstance(trigger, CaptureTrigger):
        condition_name = "ObjectCaptureEntity"
        sid = trigger.entity_sid
    elif isinstance(trigger, CounterTrigger):
        return {
            "comment": "",
            "c": "CounterEqualityInDays",
            "p": [trigger.counter_sid, str(trigger.value)],
            "counter": 1,
        }
    else:
        raise TypeError(f"{event_id}: unsupported trigger {type(trigger).__name__}")
    return {"comment": "", "c": condition_name, "p": [sid], "counter": 1}


def _native_action(action: ActionSpec, *, event_id: str) -> dict[str, Any]:
    if isinstance(action, CounterAction):
        action_name = (
            "CounterSet"
            if action.operation is CounterOperation.SET
            else "CounterPlus"
        )
        return {
            "comment": "",
            "a": action_name,
            "p": [action.counter_sid, str(action.value)],
        }
    if isinstance(action, ResourceAction):
        opcode = "GiveRes" if action.amount > 0 else "RemoveRes"
        amount = action.amount if action.amount > 0 else abs(action.amount)
        return {
            "comment": "",
            "a": opcode,
            "p": [action.resource, str(amount)],
        }
    if isinstance(action, ObjectiveProgressAction):
        return {"comment": "", "a": "CurrentSubQuestDone", "p": []}
    if isinstance(action, VictoryAction):
        return {"comment": "", "a": "GameVictory", "p": []}
    raise TypeError(f"{event_id}: unsupported action {type(action).__name__}")


def _validate_counter_references(
    spec: MechanicalEventSpec,
    declared_counter_sids: frozenset[str],
) -> None:
    for trigger in spec.triggers:
        if isinstance(trigger, CounterTrigger) and trigger.counter_sid not in declared_counter_sids:
            raise ValueError(
                f"{spec.event_id}: trigger references undeclared counter "
                f"{trigger.counter_sid!r}"
            )
    for action in spec.actions:
        if isinstance(action, CounterAction) and action.counter_sid not in declared_counter_sids:
            raise ValueError(
                f"{spec.event_id}: action references undeclared counter "
                f"{action.counter_sid!r}"
            )


def compile_event(
    spec: MechanicalEventSpec,
    *,
    declared_counter_sids: Iterable[str] = (),
) -> dict[str, Any]:
    """Compile one event without applying the scenario-wide victory count check."""

    counters = frozenset(
        _require_sid(sid, field="declared counter SID")
        for sid in declared_counter_sids
    )
    _validate_counter_references(spec, counters)
    return {
        "comment": spec.event_id,
        "repeat": spec.repeat,
        "conditions": [
            _native_condition(trigger, event_id=spec.event_id)
            for trigger in spec.triggers
        ],
        "actions": [
            _native_action(action, event_id=spec.event_id)
            for action in spec.actions
        ],
        "conditionsLogic": "And",
    }


def compile_mechanical_events(
    events: Sequence[MechanicalEventSpec],
    *,
    declared_counter_sids: Iterable[str] = (),
    require_explicit_victory: bool = True,
) -> tuple[dict[str, Any], ...]:
    """Compile a scenario event set and enforce its single-victory contract.

    ``require_explicit_victory=False`` is useful for validating or previewing an
    incomplete objective fragment. It never adds an alternate victory path.
    """

    event_ids = [event.event_id for event in events]
    duplicates = sorted({event_id for event_id in event_ids if event_ids.count(event_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate mechanical event IDs: {duplicates}")

    victory_actions = [
        (event.event_id, action.victory_sid)
        for event in events
        for action in event.actions
        if isinstance(action, VictoryAction)
    ]
    if len(victory_actions) > 1:
        raise ValueError(
            "scenario must contain at most one explicit victory action; "
            f"found {victory_actions}"
        )
    if require_explicit_victory and len(victory_actions) != 1:
        raise ValueError(
            "scenario must contain exactly one explicit VictoryAction; "
            f"found {len(victory_actions)}"
        )

    counters = tuple(declared_counter_sids)
    return tuple(
        compile_event(event, declared_counter_sids=counters)
        for event in events
    )


def mechanical_fingerprint(events: Sequence[MechanicalEventSpec]) -> str:
    """Stable fingerprint used for deterministic flavor-text isolation."""

    payload = {
        "schema": MECHANICAL_EVENT_SCHEMA,
        "events": [event.to_dict() for event in events],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

