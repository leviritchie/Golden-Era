#!/usr/bin/env python3
"""Authentic HoMM3 default town name pools for unnamed H3M town objects.

Root cause of coordinate placeholder names (``Town 0:29:6``): H3M town objects
carry an optional custom name (``hasName`` flag). When absent, HoMM3 assigns a
random unused name at map start from the per-faction pool in
``Data/H3bitmap.lod`` -> ``TownName.txt`` (16 names per faction, SoD; the
``HotA_lng.lod`` copy is identical). The raw_translation port previously
invented ``f"Town {sourceKey}"``, surfacing as coordinate-like placeholders
in-game (452 of 612 installed campaign towns).

An Olden ``.map`` bakes ``customCityName`` at build time, so HoMM3's per-run
random pick cannot be replicated. This module deterministically assigns pool
names at build time instead:

- per-(mission, faction) SHA-256 seed picks the pool start offset, so each
  mission gets variety but rebuilds are byte-stable;
- towns are processed in source position order (``sourceKey`` ``layer:x:y``);
- names already used anywhere on the map (explicit H3M names or earlier
  assignments) are skipped, matching HoMM3's global used-name avoidance —
  required because ``Strongglen`` exists in both the Rampart and Stronghold
  pools;
- pool exhaustion (more than 16 towns of one faction on one map) cycles with
  duplicates, matching HoMM3's tolerance, and is reported per assignment.

Name provenance: extracted from the local HoMM 3 Complete install
(``H3bitmap.lod`` -> ``TownName.txt``, verified equal to
``HotA_lng.lod`` -> ``TownName.txt``); faction order verified against
``TownType.txt`` (Castle, Rampart, Tower, Inferno, Necropolis, Dungeon,
Stronghold, Fortress, Conflux). Cove (HotA) has no pool in the local
archives; unnamed towns of unknown faction fail closed.
"""

from __future__ import annotations

import hashlib
from typing import Any

NAME_POOL_POLICY = "h3_default_town_name_pool_v1"

# Faction sid -> TownName.txt rows, in source order (16 per faction).
H3_DEFAULT_TOWN_NAMES: dict[str, tuple[str, ...]] = {
    "homm3_castle": (
        "Castellatus", "Cornerstone", "Kanan", "Highcastle",
        "Whitemoon", "Transom", "Middleheim", "Brettonia",
        "Alexandretta", "Whitestone", "Claxton", "Armitage",
        "Whistledale", "Gateway", "Dunwall", "Kildare",
    ),
    "homm3_rampart": (
        "Wise Oak", "Forest", "Fortune Keep", "Still Water",
        "Elfwind", "Serenity", "Ceiliedgh", "Gladeroot",
        "Forest Glen", "Rainhaven", "Strongglen", "Marishen",
        "Bath'iere", "Green Falls", "Emerald Moor", "Wild Willow",
    ),
    "homm3_tower": (
        "Machina", "Stronggale", "Corona", "Silverwing",
        "Facture", "Cloudfire", "Cloudspire", "Equinox",
        "Athenaeum", "Valtara", "Tirith", "Fallen Star",
        "Mystos", "Ayer", "Silverspire", "Manufactury",
    ),
    "homm3_inferno": (
        "Abaddon", "Acheron", "Ashden", "Brimstone",
        "Candent", "Cinderspire", "Daemon Gate", "Enkindle",
        "Gehenna", "Firebrand", "Ashcombe", "Hellwind",
        "Stygius", "Styx", "Tartaros", "Blackburn",
    ),
    "homm3_necropolis": (
        "Haunt's Wind", "Cessacioun", "Agony", "Sanctum",
        "Terminus", "Blackquarter", "Death's Gate", "Grave Raven",
        "Dark Cloud", "Coldsoul", "Coldreign", "Dark Eternal",
        "Ghostwind", "Blight", "Shadow Keep", "Worm Warren",
    ),
    "homm3_dungeon": (
        "Veks", "Sorrow Crown", "Chillwater", "Deepshadow",
        "Darkhold", "Blindroot", "Shadowden", "Scar",
        "Malev", "Castigare", "Dragonnade", "Shade",
        "Evernight", "Darkburrow", "Lost Hold", "Coldshadow",
    ),
    "homm3_stronghold": (
        "Kragg", "Drago Breach", "Hartgrim", "Sandflash",
        "Morganheim", "Cragmoor", "Dragonspire", "Battlement",
        "Bocc", "Slau", "Tormina", "Dolere",
        "Rockwarren", "Strongglen", "Kruber", "Rovener",
    ),
    "homm3_fortress": (
        "Marshank", "Deadfall", "Coolmire", "Backwater",
        "Marshchoke", "Lostmoor", "Silt", "Deadwood",
        "Edgewater", "Stillbog", "Drakenmoor", "Hermit Cove",
        "Mosswood", "Marshwall", "Mossden", "Mudshire",
    ),
    "homm3_conflux": (
        "Elementon", "Styriam", "Fenderen", "Lagumoor",
        "Wazzar", "Lanting", "Vluchton", "Solium",
        "Massein", "Magmetin", "Ventu", "Fleogan Mills",
        "Electrising", "Ceald", "Igne", "Froisan",
    ),
}

TOWN_NAMES_PER_FACTION = 16


# Prefix -> faction sid, mirroring the stem knowledge already pinned in
# build_homecoming_entity_substitution_map (town_animation_* rules). RoE stems
# plus AB/SoD variant stems: AVCdunx (Dungeon), AVCtowx (Tower), AVCinfx
# (Inferno), AVCforx/AVChforx (Fortress), AVCramx (Rampart), AVCelex (Conflux).
# Unknown prefixes return None so callers fail closed.
_TOWN_ANIMATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("avchforx", "homm3_fortress"),  # AB/SoD Fortress variant stem (no "fort" token)
    ("avcdung", "homm3_dungeon"),
    ("avcdunx", "homm3_dungeon"),
    ("avccast", "homm3_castle"),
    ("avccasx", "homm3_castle"),
    ("avcramp", "homm3_rampart"),
    ("avcramx", "homm3_rampart"),
    ("avctowr", "homm3_tower"),
    ("avctowx", "homm3_tower"),
    ("avcinft", "homm3_inferno"),
    ("avcinfx", "homm3_inferno"),
    ("avcnecr", "homm3_necropolis"),
    ("avcnecx", "homm3_necropolis"),
    ("avcstro", "homm3_stronghold"),
    ("avcstrx", "homm3_stronghold"),
    ("avcfort", "homm3_fortress"),
    ("avcftrt", "homm3_fortress"),
    ("avcftrx", "homm3_fortress"),
    ("avcforx", "homm3_fortress"),
    ("avcelem", "homm3_conflux"),
    ("avcelex", "homm3_conflux"),
)


def town_faction_sid_from_animation(template_animation: Any) -> str | None:
    """Map a HoMM3 town DEF animation (``AVCcasx0.def``) to a homm3 faction sid.

    Returns None for unknown prefixes so callers fail closed instead of
    mis-naming a town.
    """
    anim = str(template_animation or "").lower()
    for prefix, faction in _TOWN_ANIMATION_PREFIXES:
        if anim.startswith(prefix):
            return faction
    return None


def _source_sort_key(index: int, entity: dict[str, Any]) -> tuple[int, int, int, int, int]:
    source_key = str(entity.get("sourceKey") or "")
    parts = source_key.split(":")
    if len(parts) == 3 and all(part.lstrip("-").isdigit() for part in parts):
        layer, x, y = (int(part) for part in parts)
        return (0, layer, x, y, index)
    source_index = entity.get("sourceIndex")
    return (1, int(source_index) if isinstance(source_index, int) else 0, 0, 0, index)


def _pool_start_offset(mission_id: str, faction: str, pool_size: int) -> int:
    digest = hashlib.sha256(f"{mission_id}|{faction}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % pool_size


def assign_default_town_names(
    entities: list[dict[str, Any]],
    *,
    mission_id: str,
) -> dict[str, Any]:
    """Assign authentic pool names to unnamed town entities, in place.

    Runs on the full cross-layer entity list before layer splitting so the
    used-name set is map-global, like HoMM3. Explicit H3M names are never
    rewritten. Unknown-faction or Cove unnamed towns raise (fail closed).
    """
    mission = str(mission_id or "").strip()
    if not mission:
        raise ValueError("assign_default_town_names requires a non-empty mission_id")

    towns = [
        entity
        for entity in entities
        if isinstance(entity, dict)
        and (entity.get("category") == "town" or entity.get("payloadKind") == "town")
    ]
    used_names = {
        str(entity.get("name")).strip().casefold()
        for entity in towns
        if str(entity.get("name") or "").strip()
    }
    unnamed = [
        (index, entity)
        for index, entity in enumerate(entities)
        if isinstance(entity, dict)
        and (entity.get("category") == "town" or entity.get("payloadKind") == "town")
        and not str(entity.get("name") or "").strip()
    ]
    unnamed.sort(key=lambda item: _source_sort_key(item[0], item[1]))

    cursors: dict[str, int] = {}
    assignments: list[dict[str, Any]] = []
    exhausted: list[dict[str, Any]] = []
    for _index, entity in unnamed:
        animation = entity.get("templateAnimation")
        faction = town_faction_sid_from_animation(animation)
        if faction is None:
            raise ValueError(
                f"unnamed town {entity.get('sourceKey')} (sourceIndex "
                f"{entity.get('sourceIndex')}) has unknown templateAnimation "
                f"{animation!r}; cannot pick an authentic HoMM3 town name"
            )
        pool = H3_DEFAULT_TOWN_NAMES.get(faction)
        if pool is None:
            raise ValueError(
                f"unnamed town {entity.get('sourceKey')} faction {faction} has no "
                "HoMM3 default name pool (Cove pools are not present in the local "
                "Complete archives); name the town explicitly or extend the pool"
            )
        if faction not in cursors:
            cursors[faction] = _pool_start_offset(mission, faction, len(pool))
        cursor = cursors[faction]
        chosen_index: int | None = None
        for probe in range(len(pool)):
            candidate = (cursor + probe) % len(pool)
            if pool[candidate].casefold() not in used_names:
                chosen_index = candidate
                break
        duplicate = chosen_index is None
        if duplicate:
            # HoMM3 duplicates pool names once the pool is exhausted on one map.
            chosen_index = cursor % len(pool)
        name = pool[chosen_index]
        entity["name"] = name
        used_names.add(name.casefold())
        cursors[faction] = (chosen_index + 1) % len(pool)
        record = {
            "sourceKey": entity.get("sourceKey"),
            "sourceIndex": entity.get("sourceIndex"),
            "faction": faction,
            "name": name,
            "poolIndex": chosen_index,
            "duplicatePoolName": duplicate,
        }
        assignments.append(record)
        if duplicate:
            exhausted.append(record)

    return {
        "policy": NAME_POOL_POLICY,
        "missionId": mission,
        "townCount": len(towns),
        "explicitNameCount": len(towns) - len(unnamed),
        "assignedCount": len(assignments),
        "assignments": assignments,
        "exhaustedPoolAssignments": exhausted,
        "proofBoundary": (
            "generated_artifact: deterministic build-time stand-in for HoMM3 "
            "per-run random default town names; player-visible names land via "
            "cities.json LocKit rows at lang-overlay emit"
        ),
    }
