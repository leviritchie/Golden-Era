"""Opcode-specific audience encoders for CampaignEventIR.

propActions*.sides is zero-based (vanilla Glittering_Strait / Thirst_for_Power).
StartTurn calendar parameters are week/day (see schedule_encode); side audience for
timed grants comes from quest sharing Clone / forSides, not StartTurn p[].

Never write computerActivate onto PropActionsBase — it is not a native field.
"""

from __future__ import annotations

from typing import Any

from .model import Audience


def encode_prop_actions_sides(audience: Audience | int | None, *, context: str) -> str:
    """H3 playersMask bit0 = player 1 → zero-based CSV for propActions*.sides."""

    mask = _players_mask(audience, context=context)
    if mask == 0:
        raise ValueError(f"{context}: players mask selects no sides")
    # Full mask 255 is a valid all-sides selection; do not collapse to "".
    sides = [str(index) for index in range(8) if mask & (1 << index)]
    if not sides:
        raise ValueError(f"{context}: players mask {mask} selected no zero-based sides")
    return ",".join(sides)


def encode_start_turn_sides(audience: Audience | int | None, *, context: str) -> list[str]:
    """Legacy helper: one-based player indices from playersMask.

    Not StartTurn opcode parameters (those are week/day). Kept for validators and
    callers that still reason about per-player Clone audience size.
    """

    mask = _players_mask(audience, context=context)
    if mask <= 0:
        raise ValueError(f"{context}: playersMask must be positive; got {mask}")
    sides = [str(index + 1) for index in range(8) if mask & (1 << index)]
    if not sides:
        raise ValueError(f"{context}: playersMask {mask} selects no StartTurn sides")
    return sides


def should_emit_ai_ignore(*, computer_eligible: bool) -> bool:
    """Candidate AI exclusion for narrative hosts (runtime semantics unproven)."""

    return not bool(computer_eligible)


def _players_mask(audience: Audience | int | None, *, context: str) -> int:
    if audience is None:
        raise ValueError(f"{context}: audience/players mask is required")
    if isinstance(audience, Audience):
        return int(audience.players_mask)
    if isinstance(audience, int):
        return int(audience)
    raise ValueError(f"{context}: unsupported audience type {type(audience).__name__}")


def audience_from_players_mask(
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
    if mask < 0 or mask > 0xFF:
        raise ValueError(f"{context}: players mask must be u8; got {mask}")
    indices = tuple(index for index in range(8) if mask & (1 << index))
    if not indices and mask != 0:
        raise ValueError(f"{context}: players mask {mask} selected no sides")
    return Audience(
        players_mask=mask,
        human_eligible=human_eligible,
        computer_eligible=bool(computer_eligible),
        zero_based_player_indices=indices,
        human_eligible_layout=human_eligible_layout,
    )
