#!/usr/bin/env python3
"""Neutral HoMM3 adventure-object family registry for scenario translation."""

from __future__ import annotations

from typing import Any


VCMI_ENTITY_IDENTIFIERS_URL = (
    "https://github.com/vcmi/vcmi/blob/develop/lib/constants/EntityIdentifiers.h"
)
VCMI_MAP_FORMAT_H3M_URL = (
    "https://github.com/vcmi/vcmi/blob/develop/lib/mapping/MapFormatH3M.cpp"
)

# Core object ids (VCMI MapObjectBaseID)
OBJECT_ARTIFACT = 5
OBJECT_PANDORAS_BOX = 6
OBJECT_BLACK_MARKET = 7
OBJECT_CREATURE_BANK = 16
OBJECT_CREATURE_GENERATOR_1 = 17
OBJECT_CREATURE_GENERATOR_2 = 18
OBJECT_CREATURE_GENERATOR_3 = 19
OBJECT_CREATURE_GENERATOR_4 = 20
OBJECT_EVENT = 26
OBJECT_GARRISON = 33
OBJECT_HERO = 34
OBJECT_GRAIL = 36
OBJECT_LIGHTHOUSE = 42
OBJECT_TWO_WAY_MONOLITH = 45
OBJECT_MINE = 53
OBJECT_MONSTER = 54
OBJECT_OCEAN_BOTTLE = 59
OBJECT_CORPSE = 22
OBJECT_PRISON = 62
OBJECT_PYRAMID = 63
OBJECT_RANDOM_ARTIFACT = 65
OBJECT_RANDOM_ARTIFACT_TREASURE = 66
OBJECT_RANDOM_ARTIFACT_MINOR = 67
OBJECT_RANDOM_ARTIFACT_MAJOR = 68
OBJECT_RANDOM_ARTIFACT_RELIC = 69
OBJECT_RANDOM_HERO = 70
OBJECT_RANDOM_RESOURCE = 76
OBJECT_RANDOM_TOWN = 77
OBJECT_RESOURCE = 79
OBJECT_SCHOLAR = 81
OBJECT_SEA_CHEST = 82
OBJECT_SEER_HUT = 83
OBJECT_CRYPT = 84
OBJECT_SHIPWRECK = 85
OBJECT_SHIPWRECK_SURVIVOR = 86
OBJECT_SHIPYARD = 87
OBJECT_SHRINE_INCANTATION = 88
OBJECT_SHRINE_GESTURE = 89
OBJECT_SHRINE_THOUGHT = 90
OBJECT_SIGN = 91
OBJECT_SPELL_SCROLL = 93
OBJECT_TOWN = 98
OBJECT_TREASURE_CHEST = 101
OBJECT_TREE_OF_KNOWLEDGE = 102
OBJECT_SUBTERRANEAN_GATE = 103
OBJECT_UNIVERSITY = 104
OBJECT_WAGON = 105
OBJECT_WARRIORS_TOMB = 108
OBJECT_WHIRLPOOL = 111
OBJECT_WITCH_HUT = 113
OBJECT_VOLCANO = 158
OBJECT_BORDER_GATE = 212
OBJECT_HERO_PLACEHOLDER = 214
OBJECT_QUEST_GUARD = 215
OBJECT_RANDOM_DWELLING = 216
OBJECT_RANDOM_DWELLING_LVL = 217
OBJECT_RANDOM_DWELLING_FACTION = 218
OBJECT_GARRISON2 = 219
OBJECT_ABANDONED_MINE = 220
OBJECT_CAMPFIRE = 12
OBJECT_LEAN_TO = 39
OBJECT_FLOTSAM = 29
OBJECT_HOTA_CUSTOM_1 = 145
OBJECT_HOTA_CUSTOM_2 = 146
OBJECT_HOTA_CUSTOM_3 = 144

# RoE campaign embedded maps can emit headerless briefing tails after the normal
# object header stream ends with a deadline-first seer-hut quest shape.
OBJECT_ROE_CAMPAIGN_BRIEFING = 232

# Scenery ids observed in shipped maps but absent from the public VCMI enum snapshot.
OBJECT_DESERT_HILLS = 206
OBJECT_UNKNOWN_SCENERY_207 = 207

ARTIFACT_OBJECT_IDS = {
    OBJECT_ARTIFACT,
    OBJECT_RANDOM_ARTIFACT,
    OBJECT_RANDOM_ARTIFACT_TREASURE,
    OBJECT_RANDOM_ARTIFACT_MINOR,
    OBJECT_RANDOM_ARTIFACT_MAJOR,
    OBJECT_RANDOM_ARTIFACT_RELIC,
}
RANDOM_ARTIFACT_OBJECT_IDS = {
    OBJECT_RANDOM_ARTIFACT,
    OBJECT_RANDOM_ARTIFACT_TREASURE,
    OBJECT_RANDOM_ARTIFACT_MINOR,
    OBJECT_RANDOM_ARTIFACT_MAJOR,
    OBJECT_RANDOM_ARTIFACT_RELIC,
}
MONSTER_OBJECT_IDS = {
    OBJECT_MONSTER,
    71,
    72,
    73,
    74,
    75,
    162,
    163,
    164,
}
HERO_OBJECT_IDS = {OBJECT_HERO, OBJECT_PRISON, OBJECT_RANDOM_HERO}
FIXED_CREATURE_GENERATOR_IDS = {
    OBJECT_CREATURE_GENERATOR_1,
    OBJECT_CREATURE_GENERATOR_2,
    OBJECT_CREATURE_GENERATOR_3,
    OBJECT_CREATURE_GENERATOR_4,
}
RANDOM_DWELLING_IDS = {
    OBJECT_RANDOM_DWELLING,
    OBJECT_RANDOM_DWELLING_LVL,
    OBJECT_RANDOM_DWELLING_FACTION,
}
GARRISON_OBJECT_IDS = {OBJECT_GARRISON, OBJECT_GARRISON2}
SHRINE_OBJECT_IDS = {
    OBJECT_SHRINE_INCANTATION,
    OBJECT_SHRINE_GESTURE,
    OBJECT_SHRINE_THOUGHT,
}
CREATURE_BANK_OBJECT_IDS = {
    OBJECT_CREATURE_BANK,
    24,  # DERELICT_SHIP
    25,  # DRAGON_UTOPIA
    OBJECT_CRYPT,
    OBJECT_SHIPWRECK,
}
REWARD_WITH_ARTIFACT_OBJECT_IDS = {
    OBJECT_TREASURE_CHEST,
    OBJECT_CORPSE,
    OBJECT_WARRIORS_TOMB,
    OBJECT_SHIPWRECK_SURVIVOR,
    OBJECT_SEA_CHEST,
}
REWARD_WITH_GARBAGE_OBJECT_IDS = {OBJECT_FLOTSAM, OBJECT_TREE_OF_KNOWLEDGE}
HOTA_REWARD_OBJECT_IDS = {
    OBJECT_CAMPFIRE,
    OBJECT_LEAN_TO,
    OBJECT_WAGON,
    OBJECT_BLACK_MARKET,
    OBJECT_UNIVERSITY,
    OBJECT_PYRAMID,
    OBJECT_HOTA_CUSTOM_1,
    OBJECT_HOTA_CUSTOM_2,
    OBJECT_HOTA_CUSTOM_3,
}
EXTERNAL_DWELLING_OBJECT_IDS = FIXED_CREATURE_GENERATOR_IDS | RANDOM_DWELLING_IDS
TRAVEL_LINK_OBJECT_IDS = {OBJECT_SUBTERRANEAN_GATE, OBJECT_WHIRLPOOL}
OWNER_U32_OBJECT_IDS = {
    OBJECT_MINE,
    OBJECT_LIGHTHOUSE,
    OBJECT_SHIPYARD,
    *FIXED_CREATURE_GENERATOR_IDS,
}

CREATURE_GENERATOR_FAMILY_BY_ID = {
    OBJECT_CREATURE_GENERATOR_1: "creature_generator_1",
    OBJECT_CREATURE_GENERATOR_2: "creature_generator_2",
    OBJECT_CREATURE_GENERATOR_3: "creature_generator_3",
    OBJECT_CREATURE_GENERATOR_4: "creature_generator_4",
}
RANDOM_DWELLING_FAMILY_BY_ID = {
    OBJECT_RANDOM_DWELLING: "random_dwelling",
    OBJECT_RANDOM_DWELLING_LVL: "random_dwelling_level",
    OBJECT_RANDOM_DWELLING_FACTION: "random_dwelling_faction",
}

# VCMI readObject() routes these ids through dedicated payload readers.
PAYLOAD_ROUTED_OBJECT_IDS = {
    OBJECT_EVENT,
    *HERO_OBJECT_IDS,
    *MONSTER_OBJECT_IDS,
    OBJECT_OCEAN_BOTTLE,
    OBJECT_SIGN,
    OBJECT_SEER_HUT,
    OBJECT_WITCH_HUT,
    OBJECT_SCHOLAR,
    *GARRISON_OBJECT_IDS,
    *ARTIFACT_OBJECT_IDS,
    OBJECT_SPELL_SCROLL,
    OBJECT_RANDOM_RESOURCE,
    OBJECT_RESOURCE,
    OBJECT_RANDOM_TOWN,
    OBJECT_TOWN,
    OBJECT_MINE,
    OBJECT_ABANDONED_MINE,
    *FIXED_CREATURE_GENERATOR_IDS,
    *SHRINE_OBJECT_IDS,
    OBJECT_PANDORAS_BOX,
    OBJECT_GRAIL,
    *RANDOM_DWELLING_IDS,
    OBJECT_QUEST_GUARD,
    OBJECT_SHIPYARD,
    OBJECT_HERO_PLACEHOLDER,
    OBJECT_LIGHTHOUSE,
    OBJECT_BORDER_GATE,
    OBJECT_ROE_CAMPAIGN_BRIEFING,
}

# Positive classic-H3M allowlist for VCMI readObject's default static branch.
# Keep this explicit: changing a routed decoder must never cause a previously
# unknown object family to become zero-byte by set subtraction.
VCMI_CLASSIC_STATIC_NO_PAYLOAD_OBJECT_IDS = frozenset({
    0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 35, 37, 38, 39, 40, 41, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 55, 56, 57, 58, 60, 61, 63, 64, 78, 80, 82, 84, 85, 86, 92, 94, 95, 96, 97, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 213, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231,
})

# Creature banks and several reward objects only add bytes on HotA feature levels.
PAYLOAD_ROUTED_OBJECT_IDS -= CREATURE_BANK_OBJECT_IDS
PAYLOAD_ROUTED_OBJECT_IDS -= REWARD_WITH_ARTIFACT_OBJECT_IDS
PAYLOAD_ROUTED_OBJECT_IDS -= REWARD_WITH_GARBAGE_OBJECT_IDS
PAYLOAD_ROUTED_OBJECT_IDS -= HOTA_REWARD_OBJECT_IDS
PAYLOAD_ROUTED_OBJECT_IDS.discard(OBJECT_PYRAMID)

OBJECT_ID_EVIDENCE: dict[int, dict[str, Any]] = {
    OBJECT_ARTIFACT: {"vcmiName": "ARTIFACT", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_ARTIFACT: {"vcmiName": "RANDOM_ART", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_ARTIFACT_TREASURE: {"vcmiName": "RANDOM_TREASURE_ART", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_ARTIFACT_MINOR: {"vcmiName": "RANDOM_MINOR_ART", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_ARTIFACT_MAJOR: {"vcmiName": "RANDOM_MAJOR_ART", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_ARTIFACT_RELIC: {"vcmiName": "RANDOM_RELIC_ART", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_HERO: {"vcmiName": "RANDOM_HERO", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_GARRISON: {"vcmiName": "GARRISON", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_GARRISON2: {"vcmiName": "GARRISON2", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_SEER_HUT: {"vcmiName": "SEER_HUT", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_VOLCANO: {"vcmiName": "VOLCANO", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_SHIPYARD: {"vcmiName": "SHIPYARD", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_SUBTERRANEAN_GATE: {"vcmiName": "SUBTERRANEAN_GATE", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_WHIRLPOOL: {"vcmiName": "WHIRLPOOL", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_CREATURE_GENERATOR_1: {"vcmiName": "CREATURE_GENERATOR1", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_CREATURE_GENERATOR_2: {"vcmiName": "CREATURE_GENERATOR2", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_CREATURE_GENERATOR_3: {"vcmiName": "CREATURE_GENERATOR3", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_CREATURE_GENERATOR_4: {"vcmiName": "CREATURE_GENERATOR4", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_DWELLING: {"vcmiName": "RANDOM_DWELLING", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_DWELLING_LVL: {"vcmiName": "RANDOM_DWELLING_LVL", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_RANDOM_DWELLING_FACTION: {"vcmiName": "RANDOM_DWELLING_FACTION", "vcmiSource": VCMI_ENTITY_IDENTIFIERS_URL},
    OBJECT_DESERT_HILLS: {
        "vcmiObject": "desertHills",
        "handler": "static",
        "vcmiReader": "readGeneric/default",
        "status": "VCMI-backed no per-instance payload",
    },
    OBJECT_UNKNOWN_SCENERY_207: {
        "vcmiObject": "unknownScenery207",
        "handler": "static",
        "vcmiReader": "readGeneric/default",
        "status": "observed in VCMI sample map; no per-instance payload",
    },
}

NO_PAYLOAD_OBJECT_EVIDENCE = {
    object_id: evidence
    for object_id, evidence in OBJECT_ID_EVIDENCE.items()
    if evidence.get("vcmiReader") == "readGeneric/default"
}
NO_PAYLOAD_OBJECT_EVIDENCE.update({
    object_id: {
        "vcmiReader": "CMapLoaderH3M::readObject default static branch",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
        "h3mVersions": [14, 21, 28],
        "payloadShape": "no per-instance payload",
        "status": "positive_classic_static_allowlist",
    }
    for object_id in VCMI_CLASSIC_STATIC_NO_PAYLOAD_OBJECT_IDS
    if object_id not in NO_PAYLOAD_OBJECT_EVIDENCE
})
for _evidence in NO_PAYLOAD_OBJECT_EVIDENCE.values():
    _evidence.setdefault("h3mVersions", [14, 21, 28])
    _evidence.setdefault("payloadShape", "no per-instance payload")
NO_PAYLOAD_OBJECT_IDS = frozenset(NO_PAYLOAD_OBJECT_EVIDENCE)
if NO_PAYLOAD_OBJECT_IDS != VCMI_CLASSIC_STATIC_NO_PAYLOAD_OBJECT_IDS:
    raise RuntimeError("RoE static object evidence does not match the positive no-payload allowlist")

PAYLOAD_DECODER_EVIDENCE = {
    "fixed_creature_generator": {
        "vcmiReader": "CMapLoaderH3M::readDwelling",
        "payloadShape": "readPlayer32 owner only",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
    },
    "random_dwelling": {
        "vcmiReader": "CMapLoaderH3M::readDwellingRandom",
        "payloadShape": "readPlayer32 owner, optional faction identifier/bitmask, optional min/max level",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
    },
    "garrison": {
        "vcmiReader": "CMapLoaderH3M::readGarrison",
        "payloadShape": "readPlayer32 owner, readCreatureSet, AB removable bool, 8 zero bytes",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
    },
    "seer_hut": {
        "vcmiReader": "CMapLoaderH3M::readSeerHut",
        "payloadShape": "readSeerHutQuest/readQuest reward chain, 2 zero bytes",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
    },
    "hero": {
        "vcmiReader": "CMapLoaderH3M::readHero",
        "payloadShape": "version-gated RoE/AB/SoD hero instance payload",
        "vcmiSource": VCMI_MAP_FORMAT_H3M_URL,
    },
    "roe_campaign_briefing": {
        "vcmiReader": "parse_od_seers_hut.c deadline-first AB briefing tail",
        "payloadShape": "deadline u32, first/next/completed strings, reward u8, reward payload, 2 zero bytes; no mission prefix or object header",
        "status": "observed in RoE campaign embedded H3M tail objects such as Steadwick Liberation Intro briefing",
    },
    "roe_campaign_briefing_gap": {
        "vcmiReader": "synthetic",
        "payloadShape": "00 00 FB / 00 FB 00 / FB 00 00 prefix plus zero padding until next briefing tail",
        "status": "observed between RoE campaign briefing tail pairs in Steadwick Liberation",
    },
    "roe_campaign_briefing_zero_block": {
        "vcmiReader": "synthetic",
        "payloadShape": "24 zero bytes before the next briefing gap or tail",
        "status": "observed between RoE campaign briefing pairs in Steadwick Liberation",
    },
}

UNSUPPORTED_KNOWN_OBJECTS: dict[int, str] = {}


def creature_generator_family(object_id: int) -> str:
    try:
        return CREATURE_GENERATOR_FAMILY_BY_ID[object_id]
    except KeyError as ex:
        raise ValueError(f"object id {object_id} is not a fixed creature generator") from ex


def random_dwelling_family(object_id: int) -> str:
    try:
        return RANDOM_DWELLING_FAMILY_BY_ID[object_id]
    except KeyError as ex:
        raise ValueError(f"object id {object_id} is not a random dwelling") from ex


def unsupported_payload_reason(object_id: int) -> str | None:
    return UNSUPPORTED_KNOWN_OBJECTS.get(object_id)


def is_no_payload_object(object_id: int) -> bool:
    return object_id in NO_PAYLOAD_OBJECT_IDS
