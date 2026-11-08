#!/usr/bin/env python3
"""Resolve HoMM3 campaign mission hero level caps from H3M headers.

Complete campaign map payloads (RoE/AB/SoD) store ``levelLimit`` after the
difficulty byte when the map version is AB or newer (Complete RoE campaign
maps are version 21). ``0`` means unlimited.

Olden map settings mirror that field:

- levelLimit > 0 → ``enableCustomHeroMaxLevel=true``, ``customHeroMaxLevel=N``
- levelLimit == 0 → ``enableCustomHeroMaxLevel=false``, ``customHeroMaxLevel=0``

Carry-policy handoff ``levelCap`` must equal the **fromMission** H3M
``levelLimit`` (the restriction that applied during the scenario being left).

Proof boundary: source/static decode from Complete LOD H3C → H3M header.
Runtime enforcement of Olden ``customHeroMaxLevel`` remains separately unproven.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import h3m_format as h3m
import port_homecoming_poc as poc
from campaign_mission import CampaignMission, load_batch_manifest
from h3c_mission_source import load_h3c_block

_BATCH_MANIFEST_CANDIDATES = (
    Path("scenarios/roe_castle_campaign/batch_manifest.json"),
    Path("scenarios/roe_remaining_campaigns/batch_manifest.json"),
    Path("scenarios/ab_sod_campaigns/batch_manifest.json"),
)


@lru_cache(maxsize=256)
def h3m_hero_level_limit(*, campaign_entry: str, block_index: int) -> int:
    """Return H3M ``levelLimit`` for a campaign map block (0 = unlimited)."""

    if block_index <= 0:
        raise ValueError(f"H3C block index must be positive, got {block_index}")
    source = load_h3c_block(campaign_entry, block_index)
    header = h3m.decode_h3m_scenario_header(source.h3m_data)
    limit = int(header.get("levelLimit") or 0)
    if limit < 0:
        raise ValueError(
            f"{campaign_entry} block {block_index}: negative levelLimit {limit}"
        )
    return limit


def mission_hero_level_limit(mission: CampaignMission) -> int:
    return h3m_hero_level_limit(
        campaign_entry=mission.campaign_entry,
        block_index=mission.block_index,
    )


def olden_custom_hero_max_level_settings(level_limit: int) -> dict[str, Any]:
    """Map H3M levelLimit onto Olden MapData.settings hero-max-level fields."""

    limit = int(level_limit)
    if limit < 0:
        raise ValueError(f"level_limit must be >= 0, got {limit}")
    if limit == 0:
        return {
            "enableCustomHeroMaxLevel": False,
            "customHeroMaxLevel": 0,
        }
    return {
        "enableCustomHeroMaxLevel": True,
        "customHeroMaxLevel": limit,
    }


def resolve_mission_by_id(
    mission_id: str,
    *,
    repo_root: Path | None = None,
) -> CampaignMission:
    """Find a campaign mission across the known campaign batch manifests."""

    root = repo_root or poc.ROOT
    known: list[str] = []
    for rel in _BATCH_MANIFEST_CANDIDATES:
        path = root / rel
        if not path.is_file():
            continue
        batch = load_batch_manifest(path)
        for mission in batch.missions:
            known.append(mission.mission_id)
            if mission.mission_id == mission_id:
                return mission
    raise KeyError(
        f"unknown missionId {mission_id!r}; known missions: {', '.join(known)}"
    )


def handoff_level_cap_for_from_mission(
    from_mission_id: str,
    *,
    repo_root: Path | None = None,
) -> int:
    """Carry-policy handoff levelCap for the scenario being left."""

    mission = resolve_mission_by_id(from_mission_id, repo_root=repo_root)
    return mission_hero_level_limit(mission)


def source_text_for_level_cap(level_cap: int, *, from_mission_id: str) -> str:
    """Stable provenance string for carry-policy handoff.levelCap."""

    if level_cap == 0:
        return (
            f"H3M levelLimit=0 for {from_mission_id} (unlimited); "
            "no scenario hero level restriction."
        )
    return (
        f"H3M levelLimit={level_cap} for {from_mission_id} "
        f"(Complete LOD campaign map header)."
    )


def validate_handoff_level_cap(
    handoff: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """Return error strings when handoff.levelCap drifts from H3M."""

    errors: list[str] = []
    from_id = handoff.get("fromMissionId")
    if not isinstance(from_id, str) or not from_id:
        errors.append("handoff missing fromMissionId")
        return errors
    try:
        expected = handoff_level_cap_for_from_mission(from_id, repo_root=repo_root)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"handoff {from_id}: cannot resolve H3M levelLimit ({exc})")
        return errors
    got = handoff.get("levelCap")
    if got != expected:
        errors.append(
            f"handoff {from_id}->{handoff.get('toMissionId')}: "
            f"levelCap={got!r} must equal H3M levelLimit={expected}"
        )
    return errors
