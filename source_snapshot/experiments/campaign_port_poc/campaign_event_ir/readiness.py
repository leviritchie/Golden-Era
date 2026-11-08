"""Fail-closed delivery readiness for CampaignEventIR.

An event may be fully inventoried in IR while remaining undeliverable. Build and
install readiness must fail until every readiness blocker is cleared by a named,
proven backend — never by silent truncation, fallback, or omission.
"""

from __future__ import annotations

from .model import (
    BackendId,
    BackendStatus,
    CampaignEventIR,
    EventScope,
    HostKind,
)


def _mask_player_indices(players_mask: int) -> tuple[int, ...]:
    return tuple(index for index in range(8) if players_mask & (1 << index))


def select_backend(event: CampaignEventIR) -> BackendId | None:
    """Choose exactly one named backend class for a source event."""

    if event.scope == EventScope.TOWN:
        return BackendId.TOWN_OWNERSHIP_AWARE
    if event.scope == EventScope.MAP:
        if event.has_guards and event.guard_stacks:
            return BackendId.GUARDED_MAP_EVENT_EXACT_SQUAD
        return BackendId.UNGUARDED_MAP_EVENT
    if event.is_player_briefing and not event.is_timed_resource_grant:
        return BackendId.BRIEFING_START_TURN_DIALOG
    if event.is_timed_resource_grant:
        if event.schedule is not None and event.schedule.is_repeating:
            return BackendId.REPEATING_RESOURCE
        return BackendId.ONE_SHOT_TIMED_RESOURCE
    if event.is_player_briefing:
        return BackendId.BRIEFING_START_TURN_DIALOG
    return None


def collect_readiness_blockers(event: CampaignEventIR) -> tuple[str, ...]:
    """Return delivery blockers for one IR event. Empty means delivery-ready."""

    blockers: list[str] = []
    backend = event.selected_backend
    if backend is None:
        blockers.append("selected_backend_missing")

    # Audience encoders are opcode-specific and currently unproven for delivery.
    blockers.append("audience_encoder_unproven")

    if event.scope == EventScope.TOWN:
        blockers.append("town_event_backend_unproven")

    if event.schedule is not None and event.schedule.is_repeating:
        blockers.append("repeating_schedule_requires_native_or_direct_state_backend")

    for key in event.effects.non_resource_nonzero():
        blockers.append(f"unsupported_reward_{key}")

    if event.scope == EventScope.MAP:
        if event.has_guards and not event.guard_stacks:
            blockers.append("hasGuards_true_but_empty_guardStacks")
        if event.has_guards and event.guard_stacks:
            blockers.append("guarded_exact_squad_host_contract_unproven")
            blockers.append("guarded_pre_battle_dialog_phase_unproven")
        else:
            if event.remove_after_visit is False:
                blockers.append("non_removing_event_lifetime_unproven")
            if event.host.kind == HostKind.PERSISTENT_OBJECT:
                blockers.append("persistent_host_rebinding_unproven")
            if event.host.kind == HostKind.COLOCATED_HERO:
                blockers.append("colocated_hero_host_event_unproven")
                blockers.append("colocated_hero_adjacent_engagement_unproven")

    if not event.effects.has_message and (
        event.effects.has_resources or event.effects.non_resource_nonzero() or event.has_guards
    ):
        blockers.append("empty_message_must_not_drop_effects")

    if event.backend_status != BackendStatus.PROVEN:
        if "backend_not_runtime_proven" not in blockers:
            blockers.append("backend_not_runtime_proven")

    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for blocker in blockers:
        if blocker in seen:
            continue
        seen.add(blocker)
        ordered.append(blocker)
    return tuple(ordered)


def with_readiness(event: CampaignEventIR) -> CampaignEventIR:
    """Attach selected backend + blockers without mutating the input."""

    backend = select_backend(event)
    draft = CampaignEventIR(
        mission_id=event.mission_id,
        scope=event.scope,
        source_identity=event.source_identity,
        source_index=event.source_index,
        source_key=event.source_key,
        name=event.name,
        schedule=event.schedule,
        audience=event.audience,
        host=event.host,
        remove_after_visit=event.remove_after_visit,
        has_guards=event.has_guards,
        guard_stacks=event.guard_stacks,
        effects=event.effects,
        is_player_briefing=event.is_player_briefing,
        is_timed_resource_grant=event.is_timed_resource_grant,
        selected_backend=backend,
        backend_status=BackendStatus.SELECTED_UNPROVEN if backend is not None else BackendStatus.UNRESOLVED,
        readiness_blockers=(),
    )
    blockers = collect_readiness_blockers(draft)
    status = (
        BackendStatus.PROVEN
        if not blockers and backend is not None
        else BackendStatus.SELECTED_UNPROVEN
        if backend is not None
        else BackendStatus.UNRESOLVED
    )
    return CampaignEventIR(
        mission_id=draft.mission_id,
        scope=draft.scope,
        source_identity=draft.source_identity,
        source_index=draft.source_index,
        source_key=draft.source_key,
        name=draft.name,
        schedule=draft.schedule,
        audience=draft.audience,
        host=draft.host,
        remove_after_visit=draft.remove_after_visit,
        has_guards=draft.has_guards,
        guard_stacks=draft.guard_stacks,
        effects=draft.effects,
        is_player_briefing=draft.is_player_briefing,
        is_timed_resource_grant=draft.is_timed_resource_grant,
        selected_backend=backend,
        backend_status=status,
        readiness_blockers=blockers,
    )


def assert_delivery_ready(events: list[CampaignEventIR] | tuple[CampaignEventIR, ...], *, context: str) -> None:
    """Fail closed when any inventoried event remains undeliverable."""

    blockers: list[str] = []
    for event in events:
        ready = with_readiness(event) if not event.readiness_blockers else event
        for blocker in ready.readiness_blockers:
            blockers.append(f"{ready.source_identity}: {blocker}")
    if blockers:
        preview = "; ".join(blockers[:12])
        more = "" if len(blockers) <= 12 else f" (+{len(blockers) - 12} more)"
        raise ValueError(f"{context}: delivery not ready; {len(blockers)} blocker(s): {preview}{more}")


def players_mask_zero_based_indices(players_mask: int, *, context: str) -> tuple[int, ...]:
    if players_mask < 0 or players_mask > 0xFF:
        raise ValueError(f"{context}: players_mask must be u8; got {players_mask}")
    indices = _mask_player_indices(int(players_mask))
    if not indices and players_mask != 0:
        raise ValueError(f"{context}: players_mask {players_mask} selected no sides")
    return indices
