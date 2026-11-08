#!/usr/bin/env python3
"""VCMI BuildingID (campaign START_BONUS) → Olden UnlockBuildingCity params.

Campaign travel bonuses store VCMI BuildingID ordinals (mages_guild_1=0…),
not H3M town-mask bit indices. See h3m_town_construction.py for the distinct
on-disk mask layout.
"""

from __future__ import annotations

from typing import Any

# VCMI BuildingIDBase::Type → (Build_* sid, constructed level).
# Unlisted IDs fail closed (horde/special/ship/grail have no stock unlock verb).
VCMI_BUILDING_TO_OLDEN: dict[int, tuple[str, int]] = {
    0: ("Build_Magic_Guild", 1),  # MAGES_GUILD_1
    1: ("Build_Magic_Guild", 2),
    2: ("Build_Magic_Guild", 3),
    3: ("Build_Magic_Guild", 4),
    4: ("Build_Magic_Guild", 5),
    5: ("Build_Tavern", 1),  # TAVERN
    7: ("Build_Wall", 1),  # FORT
    8: ("Build_Wall", 2),  # CITADEL
    9: ("Build_Wall", 3),  # CASTLE
    10: ("Build_Main", 1),  # VILLAGE_HALL
    11: ("Build_Main", 2),  # TOWN_HALL
    12: ("Build_Main", 3),  # CITY_HALL
    13: ("Build_Main", 4),  # CAPITOL
    14: ("Build_Market", 1),  # MARKETPLACE
    15: ("Build_Resource_Depot", 1),  # RESOURCE_SILO
    # EXTRA_* hall aliases used by some campaign bonuses
    27: ("Build_Main", 2),  # EXTRA_TOWN_HALL
    28: ("Build_Main", 3),  # EXTRA_CITY_HALL
    29: ("Build_Main", 4),  # EXTRA_CAPITOL
    30: ("Build_Tier_1", 1),
    31: ("Build_Tier_2", 1),
    32: ("Build_Tier_3", 1),
    33: ("Build_Tier_4", 1),
    34: ("Build_Tier_5", 1),
    35: ("Build_Tier_6", 1),
    36: ("Build_Tier_7", 1),
    37: ("Build_Tier_1", 2),
    38: ("Build_Tier_2", 2),
    39: ("Build_Tier_3", 2),
    40: ("Build_Tier_4", 2),
    41: ("Build_Tier_5", 2),
    42: ("Build_Tier_6", 2),
    43: ("Build_Tier_7", 2),
}

VCMI_BUILDING_NAMES: dict[int, str] = {
    0: "mages_guild_1",
    1: "mages_guild_2",
    2: "mages_guild_3",
    3: "mages_guild_4",
    4: "mages_guild_5",
    5: "tavern",
    6: "shipyard",
    7: "fort",
    8: "citadel",
    9: "castle",
    10: "village_hall",
    11: "town_hall",
    12: "city_hall",
    13: "capitol",
    14: "marketplace",
    15: "resource_silo",
    16: "blacksmith",
    17: "special_1",
    18: "horde_1",
    19: "horde_1_upgr",
    20: "ship",
    21: "special_2",
    22: "special_3",
    23: "special_4",
    24: "horde_2",
    25: "horde_2_upgr",
    26: "grail",
    27: "extra_town_hall",
    28: "extra_city_hall",
    29: "extra_capitol",
    30: "dwell_1",
    31: "dwell_2",
    32: "dwell_3",
    33: "dwell_4",
    34: "dwell_5",
    35: "dwell_6",
    36: "dwell_7",
    37: "dwell_1_up",
    38: "dwell_2_up",
    39: "dwell_3_up",
    40: "dwell_4_up",
    41: "dwell_5_up",
    42: "dwell_6_up",
    43: "dwell_7_up",
}


def player_facing_building_label(vcmi_name: str) -> str:
    """Dialog answer text for a START_BONUS building unlock.

    Prefer classic HoMM3 names (City Hall, Town Hall) over Olden ``Build_Main
    level N`` tokens — players read those as hero levels.
    """
    token = str(vcmi_name or "").strip()
    if token.startswith("extra_"):
        token = token[len("extra_") :]
    parts: list[str] = []
    for part in token.split("_"):
        if not part:
            continue
        if part.isdigit():
            parts.append(part)
        else:
            parts.append(part[:1].upper() + part[1:])
    return " ".join(parts) or token


def olden_unlock_for_vcmi_building(building_id: int) -> dict[str, Any]:
    mapped = VCMI_BUILDING_TO_OLDEN.get(int(building_id))
    name = VCMI_BUILDING_NAMES.get(int(building_id), f"building_{building_id}")
    if mapped is None:
        raise KeyError(
            f"no Olden UnlockBuildingCity mapping for VCMI BuildingID {building_id} "
            f"({name}); horde/special/ship/grail stay fail-closed"
        )
    build_sid, level = mapped
    return {
        "vcmiBuildingId": int(building_id),
        "vcmiBuildingName": name,
        "buildingSid": build_sid,
        "level": int(level),
        "label": player_facing_building_label(name),
    }
