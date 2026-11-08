"""Stronghold faction registry for genai prop IK rollout.

Proof tier: source/static. Runtime gameplay not claimed here.
"""
from __future__ import annotations

from typing import Any

from faction_rollout import faction_tier_lab_sids, normalize_faction_key

SOURCE_LANE = "fused_push_v24_pipeline"
PROP_LANE_SUFFIX = "prop_ik_polish_genai_perframe_sites"

# Core Stronghold roster (excludes ToA variants in stronghold_skinned_units.txt).
STRONGHOLD_CORE_UNITS: tuple[str, ...] = tuple(
    sid
    for sid in faction_tier_lab_sids("homm3_stronghold")
    if sid.startswith("h3_")
)

SPECIES_BY_UNIT: dict[str, str] = {
    "h3_goblin": "humanoid_weapon",
    "h3_hobgoblin": "humanoid_weapon",
    "h3_orc": "humanoid_weapon",
    "h3_orc_chieftain": "humanoid_weapon",
    "h3_ogre": "humanoid_weapon",
    "h3_ogre_mage": "humanoid_weapon",
    "h3_cyclops": "humanoid_weapon",
    "h3_cyclops_king": "humanoid_weapon",
    "h3_wolf_rider": "quadruped",
    "h3_wolf_raider": "quadruped",
    "h3_behemoth": "quadruped",
    "h3_ancient_behemoth": "quadruped",
    "h3_roc": "flyer",
    "h3_thunderbird": "flyer",
}

# OE skinned-mesh delivery contract: seven picker clips per unit.
OE_PICKER_CLIPS: tuple[str, ...] = (
    "idle",
    "idle_mouseover",
    "idle_hitted",
    "idle_defence",
    "idle_death",
    "idle_start_move_end",
    "idle_attack_front",
)

DEFAULT_CLIPS: tuple[str, ...] = OE_PICKER_CLIPS


def species_for_unit(unit: str) -> str:
    sid = str(unit)
    species = SPECIES_BY_UNIT.get(sid)
    if species is None:
        raise ValueError(f"no stronghold species mapping for unit {sid!r}")
    return species


def clips_for_unit(unit: str) -> tuple[str, ...]:
    return DEFAULT_CLIPS


def walk_frame_token(clip: str) -> str:
    """Frame range for prop marker authorship / IK temporal blend."""
    if str(clip) in {"move", "idle_start_move_end"}:
        return "10-17"
    return "all"


def parse_frame_token(token: str, available: list[int]) -> list[int]:
    text = str(token).strip().lower()
    if text == "all":
        return [int(frame) for frame in available]
    frames: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            frames.extend(range(int(start), int(end) + 1))
        else:
            frames.append(int(part))
    allowed = set(int(frame) for frame in available)
    picked = [int(frame) for frame in frames if int(frame) in allowed]
    if not picked:
        raise ValueError(f"frame token {token!r} matched no frames in {available}")
    return picked


def prop_lane_name(source_lane: str = SOURCE_LANE) -> str:
    return f"{source_lane}_{PROP_LANE_SUFFIX}"


def rollout_units(*, faction: str = "homm3_stronghold") -> list[str]:
    key = normalize_faction_key(faction)
    if key != "homm3_stronghold":
        raise ValueError(f"this registry only covers homm3_stronghold, not {key!r}")
    return [sid for sid in STRONGHOLD_CORE_UNITS if sid in SPECIES_BY_UNIT]


def unit_rollout_row(unit: str) -> dict[str, Any]:
    sid = str(unit)
    return {
        "unit": sid,
        "species": species_for_unit(sid),
        "clips": list(clips_for_unit(sid)),
        "sourceLane": SOURCE_LANE,
        "propLane": prop_lane_name(),
    }
