"""Map HoMM3 town builtBuildingsMask / fort flags onto Olden construction presets.

Olden PropCity has no builtBuildingsMask field (native maps never carry it). The only
runtime sink for starting constructed buildings is buildingsConstructionSid → a Core
buildings_constructions preset. Difficulty tables scale start resources / neutrals /
AI buildTag cooldown — they do not multiply starting constructed buildings.

CRITICAL: H3M on-disk building bit indices are NOT VCMI BuildingID enum ordinals.
VCMI reads the 6-byte mask with readBitmaskBuildings, then remaps each H3M bit index
through MapIdentifiersH3M::remapBuilding into BuildingID. Treating raw H3M bits as
BuildingID (mages_guild_1=0 … fort=7) is wrong: H3M bit 3 is Fort, so mask
``080000000000`` is Fort-only, not Mage Guild 4.

Authoritative H3M bit order: HeroWO h3m-The-Corpus town buildings section (and the
same layout VCMI remaps from). Village Hall is never stored; it is always assumed.
Dwelling bits are interleaved with horde slots (not contiguous 30..43).
"""

from __future__ import annotations

import copy
import json
from typing import Any

# H3M on-disk building bit indices (6-byte mask, LSB of byte 0 = bit 0).
# NOT VCMI BuildingID enum values.
H3M_TOWN_HALL = 0
H3M_CITY_HALL = 1
H3M_CAPITOL = 2
H3M_FORT = 3
H3M_CITADEL = 4
H3M_CASTLE = 5
H3M_TAVERN = 6
H3M_BLACKSMITH = 7
H3M_MARKETPLACE = 8
H3M_RESOURCE_SILO = 9
H3M_ARTIFACT_MERCHANTS = 10
H3M_MAGES_GUILD_1 = 11
H3M_MAGES_GUILD_5 = 15
H3M_SHIPYARD = 16
H3M_GRAIL = 17
H3M_SPECIAL_1 = 18
H3M_SPECIAL_2 = 19
H3M_SPECIAL_3 = 20
H3M_SPECIAL_4 = 21
H3M_DWELL_1 = 22
H3M_DWELL_1_UP = 23
H3M_HORDE_1 = 24
H3M_DWELL_2 = 25
H3M_DWELL_2_UP = 26
H3M_HORDE_2 = 27
H3M_DWELL_3 = 28
H3M_DWELL_3_UP = 29
H3M_HORDE_3 = 30
H3M_DWELL_4 = 31
H3M_DWELL_4_UP = 32
H3M_HORDE_4 = 33
H3M_DWELL_5 = 34
H3M_DWELL_5_UP = 35
H3M_HORDE_5 = 36
H3M_DWELL_6 = 37
H3M_DWELL_6_UP = 38
H3M_DWELL_7 = 39
H3M_DWELL_7_UP = 40

# Homecoming regression anchors (must stay Fort / Fort+Tavern+…, never Mage Guild 4).
H3M_MASK_FORT_ONLY = "080000000000"
H3M_MASK_CARYATID = "480840120000"
H3M_MASK_TERRANEUS = "480000000000"

H3M_BUILDING_NAMES: dict[int, str] = {
    H3M_TOWN_HALL: "town_hall",
    H3M_CITY_HALL: "city_hall",
    H3M_CAPITOL: "capitol",
    H3M_FORT: "fort",
    H3M_CITADEL: "citadel",
    H3M_CASTLE: "castle",
    H3M_TAVERN: "tavern",
    H3M_BLACKSMITH: "blacksmith",
    H3M_MARKETPLACE: "marketplace",
    H3M_RESOURCE_SILO: "resource_silo",
    H3M_ARTIFACT_MERCHANTS: "artifact_merchants",
    11: "mages_guild_1",
    12: "mages_guild_2",
    13: "mages_guild_3",
    14: "mages_guild_4",
    15: "mages_guild_5",
    H3M_SHIPYARD: "shipyard",
    H3M_GRAIL: "grail",
    H3M_SPECIAL_1: "special_1",
    H3M_SPECIAL_2: "special_2",
    H3M_SPECIAL_3: "special_3",
    H3M_SPECIAL_4: "special_4",
    H3M_DWELL_1: "dwell_1",
    H3M_DWELL_1_UP: "dwell_1_up",
    H3M_HORDE_1: "horde_1",
    H3M_DWELL_2: "dwell_2",
    H3M_DWELL_2_UP: "dwell_2_up",
    H3M_HORDE_2: "horde_2",
    H3M_DWELL_3: "dwell_3",
    H3M_DWELL_3_UP: "dwell_3_up",
    H3M_HORDE_3: "horde_3",
    H3M_DWELL_4: "dwell_4",
    H3M_DWELL_4_UP: "dwell_4_up",
    H3M_HORDE_4: "horde_4",
    H3M_DWELL_5: "dwell_5",
    H3M_DWELL_5_UP: "dwell_5_up",
    H3M_HORDE_5: "horde_5",
    H3M_DWELL_6: "dwell_6",
    H3M_DWELL_6_UP: "dwell_6_up",
    H3M_DWELL_7: "dwell_7",
    H3M_DWELL_7_UP: "dwell_7_up",
}

# Bits with no Olden construction SID equivalent (fail-closed residual gaps).
UNMAPPED_H3M_BITS = frozenset(
    {
        H3M_BLACKSMITH,
        H3M_ARTIFACT_MERCHANTS,
        H3M_SHIPYARD,
        H3M_GRAIL,
        H3M_SPECIAL_1,
        H3M_SPECIAL_2,
        H3M_SPECIAL_3,
        H3M_SPECIAL_4,
        H3M_HORDE_1,
        H3M_HORDE_2,
        H3M_HORDE_3,
        H3M_HORDE_4,
        H3M_HORDE_5,
    }
)

# Dwelling base/upgrade bit pairs by creature tier (H3M interleaved layout).
H3M_DWELLING_BITS: dict[int, tuple[int, int]] = {
    1: (H3M_DWELL_1, H3M_DWELL_1_UP),
    2: (H3M_DWELL_2, H3M_DWELL_2_UP),
    3: (H3M_DWELL_3, H3M_DWELL_3_UP),
    4: (H3M_DWELL_4, H3M_DWELL_4_UP),
    5: (H3M_DWELL_5, H3M_DWELL_5_UP),
    6: (H3M_DWELL_6, H3M_DWELL_6_UP),
    7: (H3M_DWELL_7, H3M_DWELL_7_UP),
}

CONSTRUCTION_SID_PREFIX = "homecoming_h3_town_construction_"


def decode_buildings_mask(mask_hex: str | None) -> set[int]:
    if not isinstance(mask_hex, str) or not mask_hex:
        return set()
    raw = bytes.fromhex(mask_hex)
    bits: set[int] = set()
    for byte_index, value in enumerate(raw):
        for bit in range(8):
            if value & (1 << bit):
                bits.add(byte_index * 8 + bit)
    return bits


def named_buildings(bits: set[int]) -> list[str]:
    return [H3M_BUILDING_NAMES.get(bit, f"bit_{bit}") for bit in sorted(bits)]


def _hall_level(bits: set[int]) -> int:
    if H3M_CAPITOL in bits:
        return 4
    if H3M_CITY_HALL in bits:
        return 3
    if H3M_TOWN_HALL in bits:
        return 2
    # Village hall is never stored in the H3M mask; always keep a town center.
    return 1


def _wall_level(bits: set[int]) -> int:
    if H3M_CASTLE in bits:
        return 3
    if H3M_CITADEL in bits:
        return 2
    if H3M_FORT in bits:
        return 1
    return 0


def _mage_guild_level(bits: set[int]) -> int:
    level = 0
    for index in range(H3M_MAGES_GUILD_1, H3M_MAGES_GUILD_5 + 1):
        if index in bits:
            level = max(level, index - H3M_MAGES_GUILD_1 + 1)
    return level


def _dwelling_levels(bits: set[int]) -> dict[int, int]:
    levels: dict[int, int] = {}
    for tier, (base, upgrade) in H3M_DWELLING_BITS.items():
        if upgrade in bits:
            levels[tier] = 2
        elif base in bits:
            levels[tier] = 1
    return levels


def olden_constructed_from_h3_bits(bits: set[int]) -> dict[str, int]:
    """Return Olden Build_* SID → constructed level for bits present in the H3M mask."""
    constructed: dict[str, int] = {"Build_Main": _hall_level(bits)}
    wall = _wall_level(bits)
    if wall > 0:
        constructed["Build_Wall"] = wall
    if H3M_TAVERN in bits:
        constructed["Build_Tavern"] = 1
    if H3M_MARKETPLACE in bits:
        constructed["Build_Market"] = 1
    if H3M_RESOURCE_SILO in bits:
        constructed["Build_Resource_Depot"] = 1
    mage = _mage_guild_level(bits)
    if mage > 0:
        constructed["Build_Magic_Guild"] = mage
    for tier, level in _dwelling_levels(bits).items():
        constructed[f"Build_Tier_{tier}"] = level
    return constructed


def assert_h3m_bit_layout_contract() -> None:
    """Fail closed if H3M on-disk bits are again confused with VCMI BuildingID."""
    fort_only = decode_buildings_mask(H3M_MASK_FORT_ONLY)
    if fort_only != {H3M_FORT}:
        raise ValueError(
            f"H3M fort-only mask {H3M_MASK_FORT_ONLY} must decode to fort bit {H3M_FORT}; "
            f"got {sorted(fort_only)} ({named_buildings(fort_only)}). "
            "Likely regressing to VCMI BuildingID ordinals (where bit 3 is mages_guild_4)."
        )
    caryatid = decode_buildings_mask(H3M_MASK_CARYATID)
    expected_caryatid = {
        H3M_FORT,
        H3M_TAVERN,
        H3M_MAGES_GUILD_1,
        H3M_DWELL_1,
        H3M_DWELL_2,
        H3M_DWELL_3,
    }
    if caryatid != expected_caryatid:
        raise ValueError(
            f"Homecoming Caryatid mask {H3M_MASK_CARYATID} must decode to "
            f"{sorted(expected_caryatid)} ({named_buildings(expected_caryatid)}); "
            f"got {sorted(caryatid)} ({named_buildings(caryatid)})"
        )
    terraneus = decode_buildings_mask(H3M_MASK_TERRANEUS)
    if terraneus != {H3M_FORT, H3M_TAVERN}:
        raise ValueError(
            f"Homecoming Terraneus mask {H3M_MASK_TERRANEUS} must decode to fort+tavern; "
            f"got {sorted(terraneus)} ({named_buildings(terraneus)})"
        )


def olden_constructed_from_town_state(town_state: dict[str, Any]) -> tuple[dict[str, int], dict[str, Any]]:
    """Derive Olden constructed buildings from H3 town payload fields."""
    assert_h3m_bit_layout_contract()

    if town_state.get("hasCustomBuildings"):
        bits = decode_buildings_mask(town_state.get("builtBuildingsMask"))
        constructed = olden_constructed_from_h3_bits(bits)
        evidence = {
            "source": "h3_builtBuildingsMask",
            "bitLayout": "h3m_on_disk_not_vcmi_BuildingID",
            "builtBuildingsMask": town_state.get("builtBuildingsMask"),
            "forbiddenBuildingsMask": town_state.get("forbiddenBuildingsMask"),
            "h3BuiltBits": sorted(bits),
            "h3BuiltNames": named_buildings(bits),
            "unmappedH3Bits": sorted(bits & UNMAPPED_H3M_BITS),
            "unmappedH3Names": named_buildings(bits & UNMAPPED_H3M_BITS),
        }
        return constructed, evidence

    # Standard (non-custom) H3 towns: Village Hall + tier-1 dwelling; Fort when flagged.
    bits = {H3M_DWELL_1}
    if town_state.get("hasFort"):
        bits.add(H3M_FORT)
    constructed = olden_constructed_from_h3_bits(bits)
    evidence = {
        "source": "h3_standard_fort_flag",
        "bitLayout": "h3m_on_disk_not_vcmi_BuildingID",
        "hasFort": bool(town_state.get("hasFort")),
        "h3BuiltBits": sorted(bits),
        "h3BuiltNames": named_buildings(bits),
        "unmappedH3Bits": [],
        "unmappedH3Names": [],
    }
    return constructed, evidence


def construction_sid_for_object(object_id: int) -> str:
    return f"{CONSTRUCTION_SID_PREFIX}{int(object_id)}"


def apply_constructed_to_preset_template(
    template_buildings: list[dict[str, Any]],
    constructed: dict[str, int],
) -> list[dict[str, Any]]:
    """Clone a Core preset building list and mark only mapped SIDs constructed."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in template_buildings:
        if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
            raise ValueError(f"malformed construction preset building row: {row!r}")
        sid = row["sid"]
        seen.add(sid)
        out = copy.deepcopy(row)
        if sid in constructed:
            out["isConstructed"] = True
            out["level"] = int(constructed[sid])
        else:
            out["isConstructed"] = False
            # Preserve template level floor of 1 for unbuilt rows.
            out["level"] = int(out.get("level") or 1)
        rows.append(out)
    missing = sorted(set(constructed) - seen)
    if missing:
        raise ValueError(
            "H3→Olden construction mapping produced SIDs absent from the Core preset template: "
            + ", ".join(missing)
        )
    return rows


def build_construction_preset_row(
    *,
    construction_sid: str,
    template_row: dict[str, Any],
    constructed: dict[str, int],
) -> dict[str, Any]:
    if not isinstance(template_row.get("buildings"), list):
        raise ValueError("construction template missing buildings array")
    row = copy.deepcopy(template_row)
    row["id"] = construction_sid
    row["buildings"] = apply_constructed_to_preset_template(template_row["buildings"], constructed)
    return row


def apply_town_construction_from_h3(
    properties: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Set each propCities buildingsConstructionSid from H3 town construction state.

    Does not invent army/rich presets. Garrison defense remains propRandomSquads.
    """
    assert_h3m_bit_layout_contract()
    city_rows = properties.get("propCities") or []
    if not isinstance(city_rows, list):
        raise ValueError("propCities must be a list before H3 town construction apply")

    applied: list[dict[str, Any]] = []
    for city_row in city_rows:
        if not isinstance(city_row, dict) or not isinstance(city_row.get("id"), int):
            raise ValueError(f"malformed propCities row: {city_row!r}")
        object_id = int(city_row["id"])
        entity = entities_by_id.get(object_id)
        if entity is None:
            raise ValueError(f"propCities id {object_id} has no source entity for H3 construction mapping")
        constructed, evidence = olden_constructed_from_town_state(entity)
        construction_sid = construction_sid_for_object(object_id)
        city_row["buildingsConstructionSid"] = construction_sid
        applied.append(
            {
                "objectId": object_id,
                "name": entity.get("name"),
                "buildingsConstructionSid": construction_sid,
                "oldenConstructed": constructed,
                **evidence,
            }
        )
    return {
        "status": "applied_h3_built_mask_to_construction_presets",
        "policy": "h3m_on_disk_builtBuildingsMask_or_standard_fort_to_olden_buildingsConstructionSid",
        "bitLayout": "h3m_on_disk_not_vcmi_BuildingID",
        "difficultyAffectsStartingBuildings": False,
        "difficultyEvidence": (
            "Core DB/difficulties*.json scale start resources, neutralPowerMultiplier, and AI "
            "buildTag/buildingColdown — not PropCity starting constructed buildings"
        ),
        "towns": applied,
    }


def upsert_array_row(doc: dict[str, Any], row: dict[str, Any]) -> None:
    rows = doc.setdefault("array", [])
    if not isinstance(rows, list):
        raise ValueError("buildings construction doc array must be a list")
    row_id = row.get("id")
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == row_id:
            rows[index] = row
            return
    rows.append(row)


def generate_town_construction_preset_rows(
    town_contract: dict[str, Any],
    *,
    template_row: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for town in town_contract.get("towns") or []:
        if not isinstance(town, dict):
            raise ValueError(f"malformed town construction contract row: {town!r}")
        sid = town.get("buildingsConstructionSid")
        constructed = town.get("oldenConstructed")
        if not isinstance(sid, str) or not isinstance(constructed, dict):
            raise ValueError(f"town construction contract missing sid/constructed: {town!r}")
        rows.append(
            build_construction_preset_row(
                construction_sid=sid,
                template_row=template_row,
                constructed={str(key): int(value) for key, value in constructed.items()},
            )
        )
    return rows


def write_town_construction_overlay(
    *,
    overlay_root: Any,
    town_contract: dict[str, Any],
    template_row: dict[str, Any],
    existing_preset_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write/merge per-town construction presets into custom_maps_buildings_presets.json."""
    from pathlib import Path

    assert_h3m_bit_layout_contract()
    member = "DB/buildings_constructions/custom_maps_buildings_presets.json"
    out_path = Path(overlay_root) / member
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = copy.deepcopy(existing_preset_doc) if isinstance(existing_preset_doc, dict) else {"array": []}
    if "array" not in doc or not isinstance(doc["array"], list):
        raise ValueError("custom_maps_buildings_presets.json must contain an array")
    preset_rows = generate_town_construction_preset_rows(town_contract, template_row=template_row)
    for row in preset_rows:
        upsert_array_row(doc, row)
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "generated_h3_town_construction_presets",
        "member": member,
        "output": str(out_path),
        "presetSids": [row["id"] for row in preset_rows],
        "townCount": len(preset_rows),
    }
