"""Immutable CampaignEventIR model for HoMM3 → Olden event translation.

Source events are inventoried field-for-field before any emit/compile step.
Delivery readiness is separate: an event may be present in IR while its backend
remains unresolved or unproven.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


EVENT_IR_SCHEMA = "homm3.campaign_event_ir.v1"
EVENT_CENSUS_SCHEMA = "homm3.campaign_event_ir_census.v1"


class EventScope(str, Enum):
    GLOBAL = "global"
    MAP = "map"
    TOWN = "town"


class HostKind(str, Enum):
    NONE = "none"
    DISPOSABLE_MARKER = "disposable_marker"
    EXACT_SQUAD = "exact_squad"
    PERSISTENT_OBJECT = "persistent_object"
    COLOCATED_HERO = "colocated_hero"
    TOWN = "town"


class BackendId(str, Enum):
    BRIEFING_START_TURN_DIALOG = "briefing_start_turn_dialog"
    REPEATING_RESOURCE = "repeating_resource_native_or_direct_state"
    ONE_SHOT_TIMED_RESOURCE = "one_shot_timed_resource"
    UNGUARDED_MAP_EVENT = "unguarded_map_event"
    GUARDED_MAP_EVENT_EXACT_SQUAD = "guarded_map_event_exact_squad"
    TOWN_OWNERSHIP_AWARE = "town_ownership_aware_recurrence"


class BackendStatus(str, Enum):
    UNRESOLVED = "unresolved"
    SELECTED_UNPROVEN = "selected_unproven"
    PROVEN = "proven"


@dataclass(frozen=True)
class Audience:
    """H3 audience: bit0 of players_mask is player 1 (identity 0)."""

    players_mask: int
    human_eligible: bool | None
    computer_eligible: bool
    zero_based_player_indices: tuple[int, ...]
    human_eligible_layout: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Schedule:
    first_occurrence: int
    next_occurrence: int
    trigger_day: int
    is_repeating: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardStack:
    creature_type: int
    count: int
    slot: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Effects:
    message: str
    resources: tuple[int, ...]
    experience: int = 0
    mana: int = 0
    morale: int = 0
    luck: int = 0
    primary_skill: int = 0
    skills: tuple[Any, ...] = ()
    artifacts: tuple[Any, ...] = ()
    spells: tuple[Any, ...] = ()
    creatures: tuple[Any, ...] = ()
    event_buildings_mask: Any | None = None
    creature_growth: tuple[int, ...] | None = None

    @property
    def has_message(self) -> bool:
        return bool(self.message.strip())

    @property
    def has_resources(self) -> bool:
        return any(int(value or 0) != 0 for value in self.resources)

    def non_resource_nonzero(self) -> tuple[str, ...]:
        keys: list[str] = []
        if int(self.experience or 0) != 0:
            keys.append("experience")
        if int(self.mana or 0) != 0:
            keys.append("mana")
        if int(self.morale or 0) != 0:
            keys.append("morale")
        if int(self.luck or 0) != 0:
            keys.append("luck")
        if int(self.primary_skill or 0) != 0:
            keys.append("primarySkill")
        if self.skills:
            keys.append("skills")
        if self.artifacts:
            keys.append("artifacts")
        if self.spells:
            keys.append("spells")
        if self.creatures:
            keys.append("creatures")
        return tuple(keys)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HostRef:
    kind: HostKind
    source_key: str | None = None
    town_name: str | None = None
    town_event_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sourceKey": self.source_key,
            "townName": self.town_name,
            "townEventIndex": self.town_event_index,
        }


@dataclass(frozen=True)
class CampaignEventIR:
    """One decoded H3 source event with delivery backend selection state."""

    mission_id: str
    scope: EventScope
    source_identity: str
    source_index: int | None
    source_key: str
    name: str
    schedule: Schedule | None
    audience: Audience
    host: HostRef
    remove_after_visit: bool | None
    has_guards: bool
    guard_stacks: tuple[GuardStack, ...]
    effects: Effects
    is_player_briefing: bool
    is_timed_resource_grant: bool
    selected_backend: BackendId | None
    backend_status: BackendStatus
    readiness_blockers: tuple[str, ...]
    schema: str = EVENT_IR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "missionId": self.mission_id,
            "scope": self.scope.value,
            "sourceIdentity": self.source_identity,
            "sourceIndex": self.source_index,
            "sourceKey": self.source_key,
            "name": self.name,
            "schedule": None if self.schedule is None else self.schedule.to_dict(),
            "audience": self.audience.to_dict(),
            "host": self.host.to_dict(),
            "removeAfterVisit": self.remove_after_visit,
            "hasGuards": self.has_guards,
            "guardStacks": [stack.to_dict() for stack in self.guard_stacks],
            "effects": self.effects.to_dict(),
            "isPlayerBriefing": self.is_player_briefing,
            "isTimedResourceGrant": self.is_timed_resource_grant,
            "selectedBackend": None if self.selected_backend is None else self.selected_backend.value,
            "backendStatus": self.backend_status.value,
            "readinessBlockers": list(self.readiness_blockers),
        }


@dataclass(frozen=True)
class MissionEventCensus:
    mission_id: str
    campaign_entry: str
    block_index: int
    h3m_sha256: str
    events: tuple[CampaignEventIR, ...]
    schema: str = EVENT_CENSUS_SCHEMA

    @property
    def global_count(self) -> int:
        return sum(1 for event in self.events if event.scope == EventScope.GLOBAL)

    @property
    def map_count(self) -> int:
        return sum(1 for event in self.events if event.scope == EventScope.MAP)

    @property
    def town_count(self) -> int:
        return sum(1 for event in self.events if event.scope == EventScope.TOWN)

    @property
    def player_briefing_count(self) -> int:
        return sum(1 for event in self.events if event.is_player_briefing)

    @property
    def timed_resource_grant_count(self) -> int:
        """Global deferred/resource timed events only (excludes town events)."""
        return sum(
            1
            for event in self.events
            if event.scope == EventScope.GLOBAL and event.is_timed_resource_grant
        )

    @property
    def readiness_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for event in self.events:
            for blocker in event.readiness_blockers:
                blockers.append(f"{event.source_identity}: {blocker}")
        return tuple(blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "missionId": self.mission_id,
            "campaignEntry": self.campaign_entry,
            "blockIndex": self.block_index,
            "h3mSha256": self.h3m_sha256,
            "counts": {
                "total": len(self.events),
                "global": self.global_count,
                "map": self.map_count,
                "town": self.town_count,
                "playerBriefings": self.player_briefing_count,
                "timedResourceGrants": self.timed_resource_grant_count,
            },
            "events": [event.to_dict() for event in self.events],
            "readinessBlockers": list(self.readiness_blockers),
        }


@dataclass(frozen=True)
class BatchEventCensus:
    missions: tuple[MissionEventCensus, ...]
    schema: str = EVENT_CENSUS_SCHEMA

    @property
    def events(self) -> tuple[CampaignEventIR, ...]:
        return tuple(event for mission in self.missions for event in mission.events)

    @property
    def readiness_blockers(self) -> tuple[str, ...]:
        return tuple(
            blocker for mission in self.missions for blocker in mission.readiness_blockers
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "missionCount": len(self.missions),
            "eventCount": len(self.events),
            "missions": [mission.to_dict() for mission in self.missions],
            "readinessBlockers": list(self.readiness_blockers),
        }


# Expected live H3C census pins for the RoE Castle batch (source/static).
EXPECTED_EVENT_CENSUS: dict[str, dict[str, int]] = {
    "homecoming": {
        "global": 7,
        "map": 1,
        "town": 1,
        "playerBriefings": 7,
        "timedResourceGrants": 0,
    },
    "guardian_angels": {
        "global": 2,
        "map": 0,
        "town": 0,
        "playerBriefings": 2,
        "timedResourceGrants": 0,
    },
    "griffin_cliff": {
        "global": 4,
        "map": 3,
        "town": 0,
        "playerBriefings": 3,
        "timedResourceGrants": 1,
    },
    "steadwick_liberation": {
        "global": 4,
        "map": 0,
        "town": 0,
        "playerBriefings": 4,
        "timedResourceGrants": 0,
    },
    "deal_with_the_devil": {
        "global": 4,
        "map": 2,
        "town": 0,
        "playerBriefings": 4,
        "timedResourceGrants": 0,
    },
    "neutral_affairs": {
        "global": 4,
        "map": 0,
        "town": 0,
        "playerBriefings": 4,
        "timedResourceGrants": 0,
    },
    "tunnels_and_troglodytes": {
        "global": 4,
        "map": 0,
        "town": 0,
        "playerBriefings": 4,
        "timedResourceGrants": 0,
    },
}
