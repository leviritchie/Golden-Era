#!/usr/bin/env python3
"""Shared HoMM3 → Olden ``propRandomItems.rarity`` binning.

Policy ``homm3_rarity_bin_to_olden_erarity_v1`` (emit-path only; not an installer hack):

| HoMM3 rarity | Olden ``ERarity`` |
|---|---|
| 0, 1, or 2 | 1 |
| 3 | 2 |
| 4 | 3 |

Fail-closed on any other HoMM rarity. Olden ``Common=0`` is intentionally unused
by this policy. Engine ``Hex.Configs.ERarity`` is still ``0..3``; value ``4`` is
invalid and hangs ``RandomItemsPool.bfou`` → ``MapObjects.opn(null)``.

Random-artifact object ids ``65..69`` map to HoMM classes any/treasure/minor/major/relic
as rarities ``0..4``, then through this bin.
"""

from __future__ import annotations

from typing import Any

# Documented emit policy name — keep stable for validators / install reports.
HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY = "homm3_rarity_bin_to_olden_erarity_v1"

# HoMM3 random-artifact template object id → HoMM rarity class (0..4).
H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY: dict[int, int] = {
    65: 0,  # RANDOM_ART (any)
    66: 1,  # RANDOM_TREASURE_ART
    67: 2,  # RANDOM_MINOR_ART
    68: 3,  # RANDOM_MAJOR_ART
    69: 4,  # RANDOM_RELIC_ART
}

# Policy output set (OE Common=0 unused).
POLICY_OLDEN_ERARITY_VALUES: frozenset[int] = frozenset({1, 2, 3})

# Full engine ERarity domain (preflight may still allow 0).
ENGINE_ERARITY_VALUES: frozenset[int] = frozenset({0, 1, 2, 3})


def bin_homm3_rarity_to_olden_erarity(homm_rarity: int) -> int:
    """Bin a HoMM3 artifact rarity into Olden ``propRandomItems.rarity``.

    Uses policy ``homm3_rarity_bin_to_olden_erarity_v1``. Fail-closed on unexpected
    inputs (including non-ints after coercion failure by the caller).
    """
    if not isinstance(homm_rarity, int) or isinstance(homm_rarity, bool):
        raise ValueError(
            f"{HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY}: HoMM rarity must be int, "
            f"got {type(homm_rarity).__name__}: {homm_rarity!r}"
        )
    if homm_rarity in (0, 1, 2):
        return 1
    if homm_rarity == 3:
        return 2
    if homm_rarity == 4:
        return 3
    raise ValueError(
        f"{HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY}: unexpected HoMM rarity "
        f"{homm_rarity} (accepted 0..4 only)"
    )


def olden_rarity_for_random_artifact_template_id(
    template_id: int,
    *,
    source_key: Any = None,
) -> int:
    """Map HoMM3 random-artifact template object id (65..69) → binned Olden rarity."""
    if template_id not in H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY:
        where = f" for {source_key}" if source_key is not None else ""
        raise ValueError(
            f"{HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY}: random artifact template "
            f"has no HoMM rarity mapping{where}: {template_id}"
        )
    return bin_homm3_rarity_to_olden_erarity(
        H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY[template_id]
    )


def random_artifact_rarity(entity: dict[str, Any]) -> int:
    """Emit helper: entity ``templateObjectId`` → binned Olden ``propRandomItems.rarity``."""
    template_id = int(entity.get("templateObjectId") or 0)
    return olden_rarity_for_random_artifact_template_id(
        template_id,
        source_key=entity.get("sourceKey"),
    )
