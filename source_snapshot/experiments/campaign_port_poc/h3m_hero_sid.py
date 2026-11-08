#!/usr/bin/env python3
"""Map classic HoMM3 heroType ids to Olden Homm3 hero SIDs.

RoE / SoD / AB use 16 heroes per faction for the eight classic factions
(Castle…Fortress), then Conflux at 128–143. HotA-expanded id spaces are
fail-closed until an explicit mapping is added.

Evidence: Homecoming Good-1a heroType 57 is Xyron the Heretic (wiki + RoE
table), not Ignatius. The previous 18-per-faction stride mis-mapped 57 →
homm3_inferno_hero_4.

heroType 255 is HoMM3 random / campaign placeholder (object 214 / random hero).
Those must use allocate_placeholder_hero_sid, not the classic table.
"""

from __future__ import annotations

import re

_HERO_SID_RE = re.compile(r"^(homm3_[a-z]+)_hero_(\d+)$")

H3_HERO_FACTION_SIDS: tuple[str, ...] = (
    "homm3_castle",
    "homm3_rampart",
    "homm3_tower",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_dungeon",
    "homm3_stronghold",
    "homm3_fortress",
    "homm3_conflux",
)

HEROES_PER_FACTION_CLASSIC = 16
CONFLUX_START = 128
CONFLUX_COUNT = 16
CLASSIC_FACTION_COUNT = 8
CLASSIC_HERO_ID_MAX = CLASSIC_FACTION_COUNT * HEROES_PER_FACTION_CLASSIC  # 128
H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE = 255
# Lossy unique pool for heroType 255 until a native random-hero sink exists.
# Neutral1c and other dense maps can exceed 16 placeholders; cover all classic
# Homm3 faction hero slots (8×16) before failing closed.
PLACEHOLDER_HERO_SID_POOL: tuple[str, ...] = tuple(
    f"{faction}_hero_{slot}"
    for faction in H3_HERO_FACTION_SIDS[:CLASSIC_FACTION_COUNT]
    for slot in range(1, HEROES_PER_FACTION_CLASSIC + 1)
)

# SoD / AB campaign-unique heroes (ids after Conflux 128–143).
# Mapped onto dedicated OE roster slots (17/18 or campaign replacements).
SOD_CAMPAIGN_HERO_TYPE_TO_SID: dict[int, str] = {
    144: "homm3_castle_hero_17",  # Catherine
    145: "homm3_castle_hero_18",  # Roland
    146: "homm3_rampart_hero_17",  # Gelu
    147: "homm3_tower_hero_17",  # Dracon
    148: "homm3_inferno_hero_17",  # Xeron
    149: "homm3_dungeon_hero_17",  # Mutare
    150: "homm3_dungeon_hero_18",  # Mutare Drake
    151: "homm3_stronghold_hero_6",  # Boragus (roster; campaign portrait variant unused)
    152: "homm3_necropolis_hero_18",  # Haart Lich
    153: "homm3_fortress_hero_17",  # Adrienne
    154: "homm3_rampart_hero_18",  # Ordwald
    155: "homm3_necropolis_hero_17",  # Finneas
    156: "homm3_dungeon_hero_16",  # Darkstorn
}

# SoD campaign maps often store protagonists under a classic type id that is
# not their roster identity. Apply as type→display-name aliases for that H3C
# entry (and/or mission id); ``resolve_h3_hero_sid`` then wins via name_over_type.
#
# Evidence (wiki player starts + object-walk type ids on Complete LOD maps):
# - Final/Crag: 96→Yog, 102→Crag Hack (classic Crag/Oris slots)
# - Gelu / Final Gelu track: 148→Gelu (classic Xeron slot)
# - Blood: 151→Mutare (classic Boragus slot)
# - Fire: 145→Adrienne (classic Roland slot)
# - AB Catherine's Charge: 5→Catherine (classic Sorsha slot)
# AB must NOT alias 148→Gelu campaign-wide: on later AB maps 148 is Xeron.
H3C_CAMPAIGN_HERO_TYPE_NAME_ALIASES: dict[str, dict[int, str]] = {
    "final.h3c": {
        96: "Yog",
        102: "Crag Hack",
        148: "Gelu",
    },
    "crag.h3c": {
        102: "Crag Hack",
    },
    "gelu.h3c": {
        148: "Gelu",
    },
    "blood.h3c": {
        151: "Mutare",
    },
    "fire.h3c": {
        145: "Adrienne",
    },
    "ab.h3c": {
        5: "Catherine",
    },
}

# Mission-scoped aliases when the same classic type id means different heroes
# across one H3C (AB 148 = Gelu only on Shadows; Seeking/Maker use other ids
# as Xeron stand-ins).
H3C_MISSION_HERO_TYPE_NAME_ALIASES: dict[str, dict[int, str]] = {
    "shadows_of_the_forest": {148: "Gelu"},
    "seeking_armageddon": {155: "Xeron"},
    "maker_of_sorrows": {49: "Xeron"},
}

# When a mission places the campaign protagonist beside named companions
# (Sandro+Vidomina, Gem+Melodia-slot), prefer these H3M type ids for spawn
# selection so companion name_over_type / mainCustomHeroId cannot win.
# Include heroesNames-only protagonists (Sandro 74 on Master; Gem 27 on
# After the Amulet; Kilgor 149 on Taming of the Wild).
# AB omits 148: that id is Xeron on most AB maps (enemy/option), not the start.
H3C_CAMPAIGN_PROTAGONIST_HERO_TYPES: dict[str, frozenset[int]] = {
    "sandro.h3c": frozenset({74}),
    "secret.h3c": frozenset({74}),
    "gem.h3c": frozenset({27}),
    "gelu.h3c": frozenset({148, 146}),
    "yog.h3c": frozenset({45}),
    "crag.h3c": frozenset({102}),
    "blood.h3c": frozenset({151, 149, 150}),
    "fire.h3c": frozenset({145, 153}),
    "festival.h3c": frozenset({149}),  # Kilgor (type 149; name_over_type from chain)
    "slayer.h3c": frozenset({147}),
    "ab.h3c": frozenset({5, 144, 146, 152, 49, 155}),
    "final.h3c": frozenset({96, 102, 148, 74, 27, 146}),
}


def campaign_hero_type_name_aliases(
    campaign_entry: str,
    *,
    mission_id: str | None = None,
) -> dict[int, str]:
    """Return type→display-name aliases for an H3C entry and optional mission id."""
    key = str(campaign_entry or "").strip().lower()
    out = dict(H3C_CAMPAIGN_HERO_TYPE_NAME_ALIASES.get(key) or {})
    mid = str(mission_id or "").strip().lower()
    if mid:
        out.update(H3C_MISSION_HERO_TYPE_NAME_ALIASES.get(mid) or {})
    return out


def campaign_protagonist_hero_types(campaign_entry: str) -> frozenset[int]:
    """H3M heroType ids that are campaign protagonists for spawn preference."""
    key = str(campaign_entry or "").strip().lower()
    return H3C_CAMPAIGN_PROTAGONIST_HERO_TYPES.get(key, frozenset())

# H3M ``heroesNames`` / ``customHero.name`` can rename a type id (Festival Razor Claw
# places type 149 with name "Kilgor"). When the name maps to a known OE SID, that
# name is authoritative over SOD_CAMPAIGN_HERO_TYPE_TO_SID / classic type math.
H3M_CAMPAIGN_HERO_NAME_TO_SID: dict[str, str] = {
    "catherine": "homm3_castle_hero_17",
    "roland": "homm3_castle_hero_18",
    "gelu": "homm3_rampart_hero_17",
    "ordwald": "homm3_rampart_hero_18",
    "dracon": "homm3_tower_hero_17",
    "xeron": "homm3_inferno_hero_17",
    "mutare": "homm3_dungeon_hero_17",
    "mutare drake": "homm3_dungeon_hero_18",
    "boragus": "homm3_stronghold_hero_6",
    "haart lich": "homm3_necropolis_hero_18",
    "adrienne": "homm3_fortress_hero_17",
    "finneas": "homm3_necropolis_hero_17",
    "darkstorn": "homm3_dungeon_hero_16",
    "kilgor": "homm3_stronghold_hero_17",
}

_NAME_TITLE_PREFIXES: tuple[str, ...] = (
    "queen ",
    "king ",
    "lord ",
    "general ",
    "sir ",
)

_roster_name_to_sid_cache: dict[str, str] | None = None


def normalize_h3m_hero_name(name: str | None) -> str:
    """Normalize H3M hero display names for SID lookup."""
    text = " ".join(str(name or "").strip().lower().split())
    if not text:
        return ""
    changed = True
    while changed:
        changed = False
        for prefix in _NAME_TITLE_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
    return text


def _roster_name_to_sid() -> dict[str, str]:
    """Load OE roster display names → SIDs (extract map) once."""
    global _roster_name_to_sid_cache
    if _roster_name_to_sid_cache is not None:
        return _roster_name_to_sid_cache
    out: dict[str, str] = {}
    try:
        import sys
        from pathlib import Path

        tools = Path(__file__).resolve().parents[2] / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from extract_homm3_hero_portraits import HERO_MAP  # type: ignore
    except Exception:
        _roster_name_to_sid_cache = out
        return out
    for row in HERO_MAP:
        if not isinstance(row, dict):
            continue
        sid = row.get("sid")
        name = row.get("name")
        if not isinstance(sid, str) or not sid.startswith("homm3_"):
            continue
        key = normalize_h3m_hero_name(str(name or ""))
        if key and key not in out:
            out[key] = sid
    _roster_name_to_sid_cache = out
    return out


def h3_hero_name_to_hero_sid(name: str | None) -> str | None:
    """Return OE SID for a known H3M hero display name, or None if unknown."""
    key = normalize_h3m_hero_name(name)
    if not key:
        return None
    if key in H3M_CAMPAIGN_HERO_NAME_TO_SID:
        return H3M_CAMPAIGN_HERO_NAME_TO_SID[key]
    return _roster_name_to_sid().get(key)


def collect_h3m_hero_names_by_type(header: dict) -> dict[int, str]:
    """Map heroType id → display name from player heroesNames + customHero."""
    names: dict[int, str] = {}
    for player in header.get("players") or []:
        if not isinstance(player, dict):
            continue
        custom = player.get("customHero")
        main_id = player.get("mainCustomHeroId")
        if (
            isinstance(main_id, int)
            and main_id != H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE
            and isinstance(custom, dict)
        ):
            custom_name = str(custom.get("name") or "").strip()
            if custom_name:
                names[main_id] = custom_name
        for row in player.get("heroesNames") or []:
            if not isinstance(row, dict):
                continue
            hero_id = row.get("id")
            hero_name = str(row.get("name") or "").strip()
            if (
                isinstance(hero_id, int)
                and hero_id != H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE
                and hero_name
            ):
                names[hero_id] = hero_name
    return names


def merge_h3m_hero_names_by_type(
    *name_maps: dict[int, str],
    context: str = "campaign chain",
) -> dict[int, str]:
    """Merge heroType→name maps; fail closed when the same type gets conflicting names."""
    merged: dict[int, str] = {}
    for name_map in name_maps:
        for hero_type, raw_name in name_map.items():
            name = str(raw_name or "").strip()
            if not isinstance(hero_type, int) or not name:
                continue
            prior = merged.get(hero_type)
            if prior is None:
                merged[hero_type] = name
                continue
            if normalize_h3m_hero_name(prior) != normalize_h3m_hero_name(name):
                raise ValueError(
                    f"{context}: heroType {hero_type} has conflicting display names "
                    f"{prior!r} vs {name!r}"
                )
    return merged


def resolve_h3_hero_sid(hero_type: int, *, name: str | None = None) -> tuple[str, str]:
    """Resolve OE hero SID from type id, with known H3M display names winning.

    Returns ``(heroSid, evidenceTag)``. Evidence tags:
    - ``h3m_hero_name_over_type`` — known name disagrees with type-id mapping
    - ``h3m_hero_name`` — known name agrees with type-id mapping
    - ``h3_hero_type`` — no known name; type-id mapping only
    """
    typed = h3_hero_type_to_hero_sid(hero_type)
    named = h3_hero_name_to_hero_sid(name)
    if named is None:
        return typed, "h3_hero_type"
    if named != typed:
        return named, "h3m_hero_name_over_type"
    return named, "h3m_hero_name"


def h3_hero_type_to_hero_sid(hero_type: int) -> str:
    if not isinstance(hero_type, int) or hero_type < 0:
        raise ValueError(f"heroType must be a non-negative int, got {hero_type!r}")
    if hero_type == H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
        raise ValueError(
            f"heroType {hero_type} is HoMM3 random/campaign placeholder; "
            "call allocate_placeholder_hero_sid instead of h3_hero_type_to_hero_sid"
        )
    campaign_sid = SOD_CAMPAIGN_HERO_TYPE_TO_SID.get(hero_type)
    if campaign_sid is not None:
        return campaign_sid
    if hero_type >= CONFLUX_START:
        slot = hero_type - CONFLUX_START + 1
        if slot < 1 or slot > CONFLUX_COUNT:
            raise ValueError(
                f"heroType {hero_type} is outside the SoD Conflux block "
                f"[{CONFLUX_START}, {CONFLUX_START + CONFLUX_COUNT - 1}] "
                f"and has no SOD_CAMPAIGN_HERO_TYPE_TO_SID entry"
            )
        return f"homm3_conflux_hero_{slot}"
    if hero_type >= CLASSIC_HERO_ID_MAX:
        raise ValueError(
            f"heroType {hero_type} is in the HotA-expanded gap "
            f"[{CLASSIC_HERO_ID_MAX}, {CONFLUX_START - 1}]; add an explicit mapping"
        )
    faction_index = hero_type // HEROES_PER_FACTION_CLASSIC
    slot = (hero_type % HEROES_PER_FACTION_CLASSIC) + 1
    faction = H3_HERO_FACTION_SIDS[faction_index]
    return f"{faction}_hero_{slot}"


def h3_hero_sid_to_hero_type(hero_sid: str) -> int:
    """Inverse of ``h3_hero_type_to_hero_sid`` for carry-policy missionSpawns fallbacks.

    Prefer SoD/AB campaign type ids when a SID is listed there (Catherine 144, etc.).
    Classic faction slots 1–16 and Conflux 1–16 reverse to the canonical type-id table.
    Fail closed for unknown shapes / HotA-only SIDs rather than guessing.
    """
    sid = str(hero_sid or "").strip()
    if not sid:
        raise ValueError("heroSid must be a non-empty string")
    sod_hits = [hero_type for hero_type, mapped in SOD_CAMPAIGN_HERO_TYPE_TO_SID.items() if mapped == sid]
    if len(sod_hits) == 1:
        return sod_hits[0]
    if len(sod_hits) > 1:
        raise ValueError(
            f"heroSid {sid!r} maps to multiple SOD_CAMPAIGN_HERO_TYPE_TO_SID entries: {sod_hits}"
        )
    match = _HERO_SID_RE.fullmatch(sid)
    if match is None:
        raise ValueError(f"heroSid has unexpected shape for type reverse-map: {sid!r}")
    faction_sid = match.group(1)
    slot = int(match.group(2))
    if faction_sid == "homm3_conflux":
        if slot < 1 or slot > CONFLUX_COUNT:
            raise ValueError(f"Conflux heroSid slot out of range: {sid!r}")
        return CONFLUX_START + slot - 1
    try:
        faction_index = H3_HERO_FACTION_SIDS.index(faction_sid)
    except ValueError as exc:
        raise ValueError(f"heroSid faction is not in the classic HoMM3 table: {sid!r}") from exc
    if faction_index >= CLASSIC_FACTION_COUNT:
        raise ValueError(f"heroSid faction is not reverse-mappable as classic/Conflux: {sid!r}")
    if slot < 1 or slot > HEROES_PER_FACTION_CLASSIC:
        raise ValueError(
            f"heroSid {sid!r} uses slot {slot} outside classic 1..{HEROES_PER_FACTION_CLASSIC}; "
            "add SOD_CAMPAIGN_HERO_TYPE_TO_SID or an explicit type"
        )
    return faction_index * HEROES_PER_FACTION_CLASSIC + (slot - 1)


def allocate_placeholder_hero_sid(taken: set[str]) -> str:
    """Pick a unique Homm3 hero SID for HoMM3 heroType 255 (random/placeholder)."""
    for sid in PLACEHOLDER_HERO_SID_POOL:
        if sid not in taken:
            return sid
    raise ValueError(
        "exhausted PLACEHOLDER_HERO_SID_POOL for heroType 255; "
        "expand the pool or add a native random-hero sink"
    )


def h3_owner_to_olden_player_index(owner: int) -> int:
    """Map H3M owner byte (0-based player) to Olden propSpawns/propCities owner (1-based)."""

    if not isinstance(owner, int) or owner < 0 or owner > 7:
        raise ValueError(f"H3M owner must be 0..7, got {owner!r}")
    return owner + 1
