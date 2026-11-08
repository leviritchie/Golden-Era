"""Explicit stock ObjectConfig remaps / omit / block policy for vanilla_stock emit."""

from __future__ import annotations

from typing import Any

import h3m_object_registry as h3obj

from . import STOCK_SUBTERRANEAN_GATE_SID
# H3 town subtype → stock city + faction.
H3_TOWN_SUBTYPE_TO_STOCK: dict[int, tuple[str, str]] = {
    0: ("human_city", "human"),  # Castle / Temple
    1: ("nature_city", "nature"),  # Rampart
    3: ("demon_city", "demon"),  # Inferno
    4: ("undead_city", "undead"),  # Necropolis
    5: ("dungeon_city", "dungeon"),  # Dungeon
}

# H3 town subtypes with no stock faction counterpart become lobby free-choice
# (random-city + unlocked faction/hero) instead of failing the whole map.
H3_TOWN_SUBTYPE_UNMAPPED_FREE_CHOICE: dict[int, str] = {
    2: "tower_has_no_stock_faction_counterpart",
    6: "stronghold_has_no_stock_faction_counterpart",
    7: "fortress_has_no_stock_faction_counterpart",
    8: "conflux_has_no_stock_faction_counterpart",
    9: "cove_has_no_stock_faction_counterpart",
    10: "factory_has_no_stock_faction_counterpart",
    11: "bulwark_has_no_stock_faction_counterpart",
}

# Backward-compatible alias used by older call sites / docs.
H3_TOWN_SUBTYPE_BLOCKED = H3_TOWN_SUBTYPE_UNMAPPED_FREE_CHOICE


DEFAULT_STOCK_HERO_BY_FACTION: dict[str, str] = {
    "human": "human_hero_1",
    "nature": "nature_hero_1",
    "demon": "demon_hero_1",
    "undead": "necro_hero_1",
    "dungeon": "dungeon_hero_1",
    "unfrozen": "unfrozen_hero_1",
}

# Water-travel / boat family: omit (no stock boat ObjectConfig).
OMIT_OBJECT_IDS: dict[int, str] = {
    8: "boat_no_stock_objectconfig",
    h3obj.OBJECT_FLOTSAM: "flotsam_water_travel_omit_mvp",
    h3obj.OBJECT_SHIPYARD: "shipyard_requires_boat_omit_mvp",
    h3obj.OBJECT_SEA_CHEST: "sea_chest_water_travel_omit_mvp",
    h3obj.OBJECT_SHIPWRECK: "shipwreck_water_bank_omit_mvp",
    h3obj.OBJECT_SHIPWRECK_SURVIVOR: "shipwreck_survivor_omit_mvp",
    h3obj.OBJECT_OCEAN_BOTTLE: "ocean_bottle_omit_mvp",
    # Complex payloads deferred fail-closed-as-omit for MVP playability slice.
    # OBJECT_EVENT hosts: unguarded → Zone 1x1 markers; guarded → random-squad (victory_events).
    # OBJECT_SEER_HUT → omit (no stock interactable; GE/campaign custom only).
    h3obj.OBJECT_QUEST_GUARD: "quest_guard_payload_deferred_omit_mvp",
    h3obj.OBJECT_PRISON: "prison_payload_deferred_omit_mvp",
    h3obj.OBJECT_HERO_PLACEHOLDER: "hero_placeholder_deferred_omit_mvp",
    h3obj.OBJECT_RANDOM_DWELLING: "random_dwelling_decoder_unsupported_omit_mvp",
    h3obj.OBJECT_RANDOM_DWELLING_LVL: "random_dwelling_lvl_unsupported_omit_mvp",
    h3obj.OBJECT_RANDOM_DWELLING_FACTION: "random_dwelling_faction_unsupported_omit_mvp",
    h3obj.OBJECT_PANDORAS_BOX: "pandoras_box_deferred_omit_mvp",
    h3obj.OBJECT_GRAIL: "grail_deferred_omit_mvp",
    h3obj.OBJECT_SIGN: "sign_message_deferred_omit_mvp",
    h3obj.OBJECT_SCHOLAR: "scholar_deferred_omit_mvp",
    h3obj.OBJECT_WITCH_HUT: "witch_hut_deferred_omit_mvp",
    h3obj.OBJECT_GARRISON: "garrison_army_payload_deferred_omit_mvp",
    h3obj.OBJECT_GARRISON2: "garrison_army_payload_deferred_omit_mvp",
    h3obj.OBJECT_HERO: "placed_hero_identity_lossy_omit_mvp_use_city_spawns",
    h3obj.OBJECT_RANDOM_HERO: "random_hero_omit_mvp_use_city_spawns",
    h3obj.OBJECT_SPELL_SCROLL: "spell_scroll_deferred_omit_mvp",
    h3obj.OBJECT_CORPSE: "corpse_deferred_omit_mvp",
    h3obj.OBJECT_LEAN_TO: "lean_to_deferred_omit_mvp",
    h3obj.OBJECT_WAGON: "wagon_deferred_omit_mvp",
    h3obj.OBJECT_WARRIORS_TOMB: "warriors_tomb_deferred_omit_mvp",
    h3obj.OBJECT_CRYPT: "crypt_bank_deferred_omit_mvp",
    h3obj.OBJECT_CREATURE_BANK: "creature_bank_deferred_omit_mvp",
    h3obj.OBJECT_BLACK_MARKET: "black_market_deferred_omit_mvp",
    h3obj.OBJECT_UNIVERSITY: "university_deferred_omit_mvp",
    h3obj.OBJECT_TREE_OF_KNOWLEDGE: "tree_of_knowledge_deferred_omit_mvp",
    h3obj.OBJECT_BORDER_GATE: "border_gate_deferred_omit_mvp",
}

# Template id → stock SID (no MiniLM; fail if SID missing from stock Core).
DIRECT_TEMPLATE_SID: dict[int, str] = {
    h3obj.OBJECT_TREASURE_CHEST: "chest",
    h3obj.OBJECT_CAMPFIRE: "camp_fire",
    h3obj.OBJECT_RANDOM_RESOURCE: "random-res",
    h3obj.OBJECT_SUBTERRANEAN_GATE: STOCK_SUBTERRANEAN_GATE_SID,
    h3obj.OBJECT_WHIRLPOOL: "portal_magic",
    h3obj.OBJECT_RANDOM_TOWN: "random-city",
    # Specific artifacts (OBJECT_ARTIFACT=5) resolve via h3_artifact_stock_map catalog.
    h3obj.OBJECT_RANDOM_ARTIFACT: "random-item",
    h3obj.OBJECT_RANDOM_ARTIFACT_TREASURE: "random-item",
    h3obj.OBJECT_RANDOM_ARTIFACT_MINOR: "random-item",
    h3obj.OBJECT_RANDOM_ARTIFACT_MAJOR: "random-item",
    h3obj.OBJECT_RANDOM_ARTIFACT_RELIC: "random-item",
    h3obj.OBJECT_EVENT: "fx_quest_mark_gold_01",  # table remap only; emit overrides to Zone/random-squad
    h3obj.OBJECT_MONSTER: "random-squad",
    # Random monster tiers / expansions → random-squad.
    71: "random-squad",
    72: "random-squad",
    73: "random-squad",
    74: "random-squad",
    75: "random-squad",
    162: "random-squad",
    163: "random-squad",
    164: "random-squad",
    # Direct adventure buildings already stock in GE substitution tables.
    11: "quixs_path",
    28: "fairy_ring",
    31: "fountain",
    37: "watchtower",
    38: "fountain",
    42: "watchtower",
    60: "watchtower",
    61: "altar_of_magic_1",
    64: "quixs_path",
    80: "altar_of_magic_1",
    h3obj.OBJECT_SHRINE_INCANTATION: "scroll_box",
    h3obj.OBJECT_SHRINE_GESTURE: "enchanted_scroll_box",
    h3obj.OBJECT_SHRINE_THOUGHT: "mythic_scroll_box",
}

MONOLITH_TWO_WAY_ANIMATION_SID: dict[str, str] = {
    "AVXmn2g0.def": "portal_1",
    "AVXmn2o0.def": "portal_2",
    "AVXmn2p0.def": "portal_3",
    "avxmn2g0.def": "portal_1",
    "avxmn2o0.def": "portal_2",
    "avxmn2p0.def": "portal_3",
    "avxmn4b0.def": "portal_1",
    "avxmn5b0.def": "portal_2",
    "avxmn6b0.def": "portal_3",
    "avxmn7b0.def": "portal_1",
    "avxmn8b0.def": "portal_2",
    "avxmn9bw.def": "portal_3",
    "avxmn2pink0.def": "portal_1",
    "avxmn2t0.def": "portal_2",
    "avxmn2y0.def": "portal_3",
    "avxmn2b0.def": "portal_1",
    "avxmn9b0.def": "portal_2",
    "avxmn10b.def": "portal_3",
    "avxmn11b.def": "portal_1",
    "avxmn12b.def": "portal_2",
    "avxmn2bl.def": "portal_3",
    "avxmn2rd.def": "portal_1",
    "avxmn19p.def": "portal_2",
    "avxmn20b.def": "portal_3",
    "avxptw_0.def": "portal_1",
    "avxptw_1.def": "portal_2",
    "avxptw_2.def": "portal_3",
    "avxptw_3.def": "portal_1",
}

RESOURCE_ANIMATION_TOKEN_SID: dict[str, str] = {
    "gold": "resource_gold",
    "wood": "resource_wood",
    "ore": "resource_ore",
    "crys": "resource_crystals",
    "merc": "resource_mercury",
    "gems": "resource_gemstones",
    "sulf": "resource_dust",
}

MINE_SUBTYPE_SID: dict[int, str] = {
    0: "mine_wood",
    1: "mine_mercury",
    2: "mine_ore",
    3: "alchemy_lab",  # H3 sulfur — stock has no mine_sulfur; alchemy_lab is the existing stock stand-in
    4: "mine_crystals",
    5: "mine_gemstones",
    6: "mine_gold",
}

# Abandoned-mine template subtype is often 7; always use stock empty mine for TAKEMINES coverage.
ABANDONED_MINE_SID = "campaign_M2_empty_mine"

MINE_ANIMATION_EXACT_SID: dict[str, str] = {
    "AVMalch0.def": "alchemy_lab",
    "AVMalcs0.def": "alchemy_lab",
    "AVMsulf0.def": "alchemy_lab",
    "AVMorsb0.def": "mine_ore",
    "AVMorsn0.def": "mine_ore",
    "AVMore0.def": "mine_ore",
    "AVMsawg0.def": "mine_wood",
    "AVMsaws0.def": "mine_wood",
    "AVMwwhl0.def": "mine_wood",
    "AVMgold0.def": "mine_gold",
    "AVMgos0.def": "mine_gold",
    "AVMgems0.def": "mine_gemstones",
    "AVMcrys0.def": "mine_crystals",
    "AVMcrgr0.def": "mine_crystals",
}

MINE_ANIMATION_TOKEN_SID: dict[str, str] = {
    "gog": "mine_gold",
    "gos": "mine_gold",
    "god": "mine_gold",
    "gold": "mine_gold",
    "ors": "mine_ore",
    "ord": "mine_ore",
    "ore": "mine_ore",
    "saw": "mine_wood",
    "wwh": "mine_wood",
    "crys": "mine_crystals",
    "crgr": "mine_crystals",
    "crdr": "mine_crystals",
    "crsu": "mine_crystals",
    "gem": "mine_gemstones",
    "ger": "mine_gemstones",
    "ged": "mine_gemstones",
    "sulf": "alchemy_lab",
    "alc": "alchemy_lab",
}

# Castle creature generators → stock human barracks (lossy faction collapse).
CREATURE_GENERATOR_ANIMATION_SID: dict[str, str] = {
    "AVGpike0.def": "barracks_human_1",
    "AVGcros0.def": "barracks_human_2",
    "AVGgrff0.def": "barracks_human_3",
    "AVGswor0.def": "barracks_human_4",
    "AVGmonk0.def": "barracks_human_5",
    "AVGcavl0.def": "barracks_human_6",
    "AVGangl0.def": "barracks_human_7",
    "avgpike0.def": "barracks_human_1",
    "avgcros0.def": "barracks_human_2",
    "avggrff0.def": "barracks_human_3",
    "avgswor0.def": "barracks_human_4",
    "avgmonk0.def": "barracks_human_5",
    "avgcavl0.def": "barracks_human_6",
    "avgangl0.def": "barracks_human_7",
}

# Scenery template roles reused from the GE scenery role table (stock SIDs only).
TERRAIN_OBJECT_ROLES: dict[int, str] = {
    116: "ground",
    118: "pool",
    119: "tree",
    120: "shrub",
    124: "pool",
    125: "water_decoration",
    126: "pool",
    127: "pool_big",
    128: "pool",
    129: "mountain",
    131: "mountain",
    133: "mountain",
    134: "mountain",
    135: "tree",
    136: "rock",  # HoMM3 Outcropping (AVLoc*); not a lake
    137: "tree",
    147: "rock",
    148: "ruin",
    149: "pool_big",
    150: "shrub",
    151: "rock",
    153: "rock",
    h3obj.OBJECT_DESERT_HILLS: "mountain",
    h3obj.OBJECT_UNKNOWN_SCENERY_207: "rock",
    208: "rock",
    209: "rock",
    210: "mountain",
    211: "rock",
}

BIOME_ROLE_REPLACEMENTS: dict[str, dict[str, str]] = {
    "mountain": {
        "grass": "mountain_green_small_1",
        "snow": "mountain_snow_small_1",
        "dirt": "mountain_dirt_small_1",
        "desert": "mountain_dirt_small_1",
        "dead": "mountain_dead_small_1",
        "lava": "mountain_lava_small_1",
        "water": "mountain_water_small_1",
        "sand": "mountain_dirt_small_1",
    },
    "pool": {
        "grass": "pool_small",
        "snow": "pool_snow_small_1",
        "dirt": "pool_dirt_small_1",
        "desert": "pool_desert_small_1",
        "dead": "pool_dead_small_1",
        "lava": "pool_lava_small_1",
        "water": "water_reed_1",
        "sand": "pool_desert_small_1",
    },
    "pool_big": {
        "grass": "pool_big",
        "snow": "pool_snow_big_1",
        "dirt": "pool_dirt_big_1",
        "desert": "pool_desert_big_1",
        "dead": "pool_dead_big_1",
        "lava": "pool_lava_big_1",
        "water": "water_reed_1",
        "sand": "pool_desert_big_1",
    },
    "tree": {
        "grass": "pinetree_1",
        "snow": "pinetree_snow_1",
        "dirt": "tree_dirt_1",
        "desert": "grass_desert_1",
        "dead": "tree_dead_1",
        "lava": "tree_lava_1",
        "water": "water_reed_1",
        "sand": "grass_desert_1",
    },
    "shrub": {
        "grass": "grass_1",
        "snow": "grass_snow_1",
        "dirt": "dirt_strange_flower",
        "desert": "grass_desert_1",
        "dead": "grass_death_1",
        "lava": "lava_stones_1",
        "water": "water_reed_1",
        "sand": "grass_desert_1",
    },
    "rock": {
        "grass": "grass_stones_1",
        "snow": "snow_stones_1",
        "dirt": "dirt_rock_1",
        "desert": "desert_stones_1",
        "dead": "dead_stones_1",
        "lava": "lava_stones_1",
        "water": "water_reed_1",
        "sand": "desert_stones_1",
    },
    "ground": {
        "grass": "grass_stones_1",
        "snow": "snow_stones_1",
        "dirt": "dirt_stones_1",
        "desert": "desert_dune_1",
        "dead": "dead_meadow",
        "lava": "lava_stones_1",
        "water": "water_reed_1",
        "sand": "desert_dune_1",
    },
    "ruin": {
        "grass": "rocks_1",
        "snow": "snow_rock_hill_1",
        "dirt": "dirt_rock_1",
        "desert": "ruins_desert_1",
        "dead": "dead_sculls_bones_hill",
        "lava": "dirt_volcanic_rock",
        "water": "water_reed_1",
        "sand": "ruins_desert_1",
    },
    "water_decoration": {
        "grass": "water_reed_1",
        "snow": "water_reed_1",
        "dirt": "water_reed_1",
        "desert": "water_reed_1",
        "dead": "water_reed_1",
        "lava": "water_reed_1",
        "water": "water_reed_1",
        "sand": "water_reed_1",
    },
}

H3_TERRAIN_BIOME: dict[int, str] = {
    0: "dirt",
    1: "sand",
    2: "grass",
    3: "snow",
    4: "dead",
    5: "grass",
    6: "dirt",
    7: "lava",
    8: "water",
    9: "dirt",
}

# Explicit stock-native 1x1 OCC donors used when no same-family ObjectConfig
# reproduces the full H3 block mask. This is a contract, not a best-effort fallback.
SCENERY_FOOTPRINT_FILL_BY_BIOME: dict[str, str] = {
    "grass": "mountain_green_small_1",
    "snow": "mountain_snow_small_1",
    "dirt": "mountain_dirt_small_1",
    "desert": "mountain_dirt_small_1",
    "dead": "mountain_dead_small_1",
    "lava": "mountain_lava_small_1",
    "water": "mountain_water_small_1",
    "sand": "mountain_dirt_small_1",
}

SCENERY_PATHABLE_BY_BIOME: dict[str, str] = {
    "grass": "grass_stones_1",
    "snow": "snow_stones_1",
    "dirt": "dirt_stones_1",
    "desert": "desert_stones_1",
    "dead": "dead_stones_1",
    # lava_ground_* is a blocking 2x2 plate; lava_stones_1 is the stock pathable donor.
    "lava": "lava_stones_1",
    "water": "water_reed_1",
    "sand": "desert_stones_1",
}


class VanillaStockObjectMapError(ValueError):
    """Raised when an H3 object cannot be mapped to a stock SID without GE leaks."""


def _animation_token_match(animation: str, table: dict[str, str]) -> str | None:
    lowered = animation.lower()
    for token, sid in table.items():
        if token in lowered:
            return sid
    return None


def resolve_object_sid(
    record: dict[str, Any],
    *,
    stock_object_ids: set[str],
    terrain_biome: str,
) -> dict[str, Any]:
    """Return {action: keep|omit|emit, sid?, reason, factionSid?}."""
    oid = int(record["templateObjectId"])
    anim = str(record.get("templateAnimation") or "")
    subtype = int(record.get("templateSubtype") or 0)

    if oid in OMIT_OBJECT_IDS:
        return {"action": "omit", "reason": OMIT_OBJECT_IDS[oid], "templateObjectId": oid}

    if oid == h3obj.OBJECT_SEER_HUT:
        # Custom Core ObjectConfig (homecoming_custom_objects) is GE/campaign-only.
        # Vanilla stock has no legal seer-hut interactable — omit fail-closed by name.
        return {
            "action": "omit",
            "reason": "seer_hut_omitted_no_stock_interactable",
            "templateObjectId": oid,
        }

    if oid == h3obj.OBJECT_ARTIFACT:
        # Vanilla stock must stay Core-legal. Exact catalog SIDs are GE/campaign
        # overlay artifacts; remap specific H3 artifacts to stock random-item.
        if "random-item" not in stock_object_ids:
            raise VanillaStockObjectMapError("stock random-item SID missing from Core")
        return {
            "action": "emit",
            "sid": "random-item",
            "reason": "lossy_specific_h3_artifact_to_stock_random_item",
            "kind": "artifact",
            "templateObjectId": oid,
            "h3ArtifactSubtype": subtype,
        }

    if oid in (h3obj.OBJECT_TOWN,):
        if subtype in H3_TOWN_SUBTYPE_UNMAPPED_FREE_CHOICE:
            if "random-city" not in stock_object_ids:
                raise VanillaStockObjectMapError("stock random-city SID missing from Core")
            return {
                "action": "emit",
                "sid": "random-city",
                "factionSid": "",
                "freeChoice": True,
                "reason": (
                    "unmapped_h3_town_subtype_to_random_city_free_choice:"
                    f"{H3_TOWN_SUBTYPE_UNMAPPED_FREE_CHOICE[subtype]}"
                ),
                "kind": "town",
            }
        if subtype not in H3_TOWN_SUBTYPE_TO_STOCK:
            raise VanillaStockObjectMapError(f"unsupported town subtype {subtype} at {record.get('key')}")
        city_sid, faction = H3_TOWN_SUBTYPE_TO_STOCK[subtype]
        if city_sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"stock city SID missing from Core: {city_sid}")
        return {
            "action": "emit",
            "sid": city_sid,
            "factionSid": faction,
            "freeChoice": False,
            "reason": "lossy_h3_town_subtype_to_stock_city",
            "kind": "town",
        }

    if oid == h3obj.OBJECT_TWO_WAY_MONOLITH:
        sid = MONOLITH_TWO_WAY_ANIMATION_SID.get(anim) or MONOLITH_TWO_WAY_ANIMATION_SID.get(anim.lower())
        if sid is None:
            raise VanillaStockObjectMapError(f"unmapped two-way monolith animation {anim!r} at {record.get('key')}")
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"monolith remap SID missing from stock Core: {sid}")
        return {"action": "emit", "sid": sid, "reason": "monolith_animation_exact", "kind": "portal"}

    if oid == h3obj.OBJECT_RESOURCE:
        sid = _animation_token_match(anim, RESOURCE_ANIMATION_TOKEN_SID) or "resource_gold"
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"resource SID missing from stock Core: {sid}")
        return {"action": "emit", "sid": sid, "reason": "resource_animation_token", "kind": "resource"}

    if oid == h3obj.OBJECT_ABANDONED_MINE:
        sid = ABANDONED_MINE_SID
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"abandoned mine SID missing from stock Core: {sid}")
        return {
            "action": "emit",
            "sid": sid,
            "reason": "abandoned_mine_stock_empty_mine",
            "kind": "mine",
        }

    if oid == h3obj.OBJECT_MINE:
        sid = MINE_SUBTYPE_SID.get(subtype)
        if sid is None:
            sid = (
                MINE_ANIMATION_EXACT_SID.get(anim)
                or {k.lower(): v for k, v in MINE_ANIMATION_EXACT_SID.items()}.get(anim.lower())
                or _animation_token_match(anim, MINE_ANIMATION_TOKEN_SID)
            )
        if sid is None:
            return {
                "action": "omit",
                "reason": f"unmapped_mine_subtype_{subtype}_omit_mvp",
                "templateObjectId": oid,
                "templateAnimation": anim,
            }
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"mine SID missing from stock Core: {sid}")
        return {"action": "emit", "sid": sid, "reason": "mine_subtype_or_animation", "kind": "mine"}

    if oid == h3obj.OBJECT_MONSTER:
        # Concrete SoD creature indexes are baked into the stock strength model.
        # HotA-only creatureTypes (e.g. 157 on Mysterious Island) have no stock
        # budget — omit by name rather than inventing a silent strength guess.
        from .stock_neutral_strength import load_strength_model

        try:
            model = load_strength_model()
            known = set(int(k) for k in (model.get("creatureTypeSquadValuesFromGe") or {}))
        except Exception as ex:  # noqa: BLE001 - surface as object-map error
            raise VanillaStockObjectMapError(f"strength model unreadable for monster omit gate: {ex}") from ex
        if subtype not in known:
            return {
                "action": "omit",
                "reason": f"hota_or_unmapped_creature_type_{subtype}_no_stock_squad_value",
                "templateObjectId": oid,
                "templateSubtype": subtype,
            }

    if oid in (
        h3obj.OBJECT_CREATURE_GENERATOR_1,
        h3obj.OBJECT_CREATURE_GENERATOR_2,
        h3obj.OBJECT_CREATURE_GENERATOR_3,
        h3obj.OBJECT_CREATURE_GENERATOR_4,
    ):
        sid = CREATURE_GENERATOR_ANIMATION_SID.get(anim) or CREATURE_GENERATOR_ANIMATION_SID.get(anim.lower())
        if sid is None:
            raise VanillaStockObjectMapError(
                "creature generator animation has no explicit stock mapping: "
                f"objectId={oid}, animation={anim!r}"
            )
        reason = "creature_generator_animation_to_stock_barracks"
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"barracks SID missing from stock Core: {sid}")
        return {"action": "emit", "sid": sid, "reason": reason, "kind": "dwelling"}

    if oid in DIRECT_TEMPLATE_SID:
        sid = DIRECT_TEMPLATE_SID[oid]
        if sid not in stock_object_ids:
            raise VanillaStockObjectMapError(f"direct remap SID missing from stock Core: {sid}")
        kind = "portal" if sid.startswith("portal") else "interactable"
        if oid == h3obj.OBJECT_EVENT:
            kind = "map_event"
        if sid == "random-squad":
            kind = "random_squad"
        if sid in {"random-city", "human_city", "nature_city", "demon_city", "undead_city", "dungeon_city"}:
            kind = "town"
            if sid == "random-city":
                return {
                    "action": "emit",
                    "sid": sid,
                    "factionSid": "",
                    "freeChoice": True,
                    "reason": "direct_template_random_city_free_choice",
                    "kind": kind,
                }
            return {
                "action": "emit",
                "sid": sid,
                "factionSid": None,
                "freeChoice": False,
                "reason": "direct_template_sid",
                "kind": kind,
            }
        return {"action": "emit", "sid": sid, "reason": "direct_template_sid", "kind": kind}

    if oid in TERRAIN_OBJECT_ROLES:
        role = TERRAIN_OBJECT_ROLES[oid]
        if role == "terrain_animation_classification_required":
            raise VanillaStockObjectMapError(f"scenery template {oid} requires animation classification at {record.get('key')}")
        biome_table = BIOME_ROLE_REPLACEMENTS.get(role)
        if not biome_table:
            raise VanillaStockObjectMapError(f"missing biome table for scenery role {role}")
        sid = biome_table.get(terrain_biome) or biome_table.get("grass")
        if sid is None or sid not in stock_object_ids:
            raise VanillaStockObjectMapError(
                f"scenery SID {sid!r} for role={role} biome={terrain_biome} missing from stock Core"
            )
        fill_sid = SCENERY_FOOTPRINT_FILL_BY_BIOME.get(terrain_biome)
        pathable_sid = SCENERY_PATHABLE_BY_BIOME.get(terrain_biome)
        if fill_sid is None or fill_sid not in stock_object_ids:
            raise VanillaStockObjectMapError(
                f"scenery footprint fill SID {fill_sid!r} for biome={terrain_biome} missing from stock Core"
            )
        if pathable_sid is None or pathable_sid not in stock_object_ids:
            raise VanillaStockObjectMapError(
                f"pathable scenery SID {pathable_sid!r} for biome={terrain_biome} missing from stock Core"
            )
        return {
            "action": "emit",
            "sid": sid,
            "reason": f"scenery_role_{role}",
            "kind": "scenery",
            "footprintFillSid": fill_sid,
            "footprintPathableSid": pathable_sid,
        }

    # Remaining payloadless scenery / interactables: omit with explicit reason rather than invent GE SIDs.
    return {
        "action": "omit",
        "reason": f"unmapped_template_object_id_{oid}_omit_mvp",
        "templateObjectId": oid,
        "templateAnimation": anim,
    }
