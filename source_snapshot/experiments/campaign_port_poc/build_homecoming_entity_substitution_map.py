#!/usr/bin/env python3
"""Generate programmatic Olden-valid substitutions for Homecoming map entities."""

from __future__ import annotations

import atexit
import json
import os
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import h3m_object_registry as h3obj
import numpy as np
from homm3_external_dwelling_map import (
    CREATURE_GENERATOR_ANIMATION_EXACT_MAP,
    HOMM3_LANDON_BARRACKS_SIDS,
    landon_barracks_clone_sid,
    lookup_creature_generator_replacement,
)
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

SCHEMA = "homm3.homecoming_olden_entity_substitution_map.v0"
STATUS = "query_shape_substitutions_not_playable"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = REPO_ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc"
DEFAULT_OUT_ROOT = DEFAULT_INPUT_ROOT
OUT_ROOT = Path(os.environ.get("HOMECOMING_POC_OUT_ROOT", DEFAULT_OUT_ROOT))
ALIGNMENT_PATH = Path(os.environ.get("HOMECOMING_POC_ALIGNMENT_PATH", DEFAULT_INPUT_ROOT / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"))
CORE_CATALOG_PATH = REPO_ROOT / "artifacts" / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"
OUT_DIR = OUT_ROOT / "entity_substitutions"
_SUBSTITUTION_BASENAME = os.environ.get("HOMECOMING_POC_SUBSTITUTION_BASENAME", "homecoming.olden_entity_substitution_map")
OUT_PATH = OUT_DIR / f"{_SUBSTITUTION_BASENAME}.json"
_REPORT_BASENAME = _SUBSTITUTION_BASENAME.replace(".olden_entity_substitution_map", "")
REPORT_PATH = OUT_DIR / f"{_REPORT_BASENAME.upper()}_OLDEN_ENTITY_SUBSTITUTION_MAP_REPORT.md"
ENGLISH_MAP_OBJECT_TEXT = "Lang/english/texts/mapObjects.json"
ENGLISH_ARTIFACT_TEXT = "Lang/english/texts/artifacts.json"
MINILM_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_EMBEDDING_DIMENSION = 384
MINILM_CACHE_ROOT = REPO_ROOT / ".cache" / "sentence_transformers"
MINILM_ACCEPTANCE_THRESHOLD = 0.52
MINILM_REJECT_THRESHOLD = 0.54
MINILM_MIN_ACCEPTANCE_MARGIN = 0.03
# Process-lifetime Core.zip handles: open thrash (~65MB ZipFile ctor per SID) dominated
# MiniLM substitution timing. One open archive per resolved path; closed on process exit.
_CORE_ZIP_BY_PATH: dict[str, zipfile.ZipFile] = {}
# Reuse across missions inside one worker process (catalog/tokens are mission-invariant).
_CACHED_SEMANTIC_MAPPER = None
_CACHED_ARTIFACT_MAPPER = None
CUSTOM_VALID_ENTITY_IDS = {
    "homm3_boat",
    "homm3_seer_hut",
    "homm3_flotsam_pickup",
    "homm3_landon_castle_city",
    "homm3_landon_dungeon_city",
    "homm3_landon_map_event_marker",
    *HOMM3_LANDON_BARRACKS_SIDS,
}

RESOURCE_ANIMATION_MAP = {
    "gold": "resource_gold",
    "wood": "resource_wood",
    "ore": "resource_ore",
    "crys": "resource_crystals",
    "merc": "resource_mercury",
    "gems": "resource_gemstones",
    "sulf": "resource_dust",
}

MINE_ANIMATION_MAP = {
    "gog": "mine_gold",
    "gos": "mine_gold",
    "ore": "mine_ore",
    "saw": "mine_wood",
    "sw": "mine_wood",
    "cr": "mine_crystals",
    "ge": "mine_gemstones",
    "gem": "mine_gemstones",
    "sulf": "alchemy_lab",
    "alc": "alchemy_lab",
}

DECORATION_RULES = [
    ("snow_tree_decoration", ["sntr", "sptr", "pnt", "pntr"], "pinetree_snow_1"),
    # Use avlms* (AVL snow-mountain stems), never bare ms0/ms1 — those match AVMgems0/AVTgems0.
    ("snow_mountain_decoration", ["mtsn", "mtsb", "avlms"], "mountain_snow_small_1"),
    ("dirt_mountain_decoration", ["mtdr", "mtgn", "mtgr"], "mountain_dirt_small_1"),
    ("green_mountain_decoration", ["mtg", "mtgr"], "mountain_green_small_1"),
    ("dead_tree_decoration", ["ddsn", "dead"], "tree_dead_1"),
    ("grass_tree_decoration", ["tree", "tr1", "tr2"], "tree_dirt_1"),
    ("rock_decoration", ["rg", "rock", "r04", "r03", "skul"], "dirt_rock_1"),
    ("desert_decoration", ["ca", "dune", "cact"], "desert_dune_1"),
    ("water_pool_decoration", ["lk", "llk", "lv", "lake", "pool"], "pool_dirt_small_1"),
    ("underground_pool_decoration", ["llk", "lk1", "lk2", "lk3", "lv1", "lv2", "lv3"], "pool_dirt_small_1"),
    ("mushroom_decoration", ["moss", "mush"], "mushrooms_1"),
    ("fire_or_light_decoration", ["fire", "lght", "ref"], "fx_map_light"),
    ("ruin_or_building_decoration", ["dun", "hol", "hld", "man", "tmpl", "hut", "post", "pllr", "ring"], "ruins_desert_1"),
]



# Honest direct/family translators for formerly scenery-mapped template ids.
# SIDs must exist in Core.zip map-object catalog (validated at choose time).
# Creature-bank animation overrides applied before the object-16 shady_den default.
# Dragon Fly Hive is a unit bank with a tiny H3 footprint; prefer a small OE bank.
CREATURE_BANK_ANIMATION_EXACT_MAP: dict[str, tuple[str, str]] = {
    "AVXbnk70.def": ("black_tower", "dragon_fly_hive_to_black_tower_small_bank"),
    "avxbnk70.def": ("black_tower", "dragon_fly_hive_to_black_tower_small_bank"),
}

DIRECT_BLOCKED_TEMPLATE_MAP: dict[int, tuple[str, str]] = {
    11: ("quixs_path", "buoy_to_quixs_path_morale"),
    # Campfire (classic 12 + HotA-style 222 AVXcf*) → native camp_fire pickup.
    12: ("camp_fire", "campfire_to_camp_fire"),
    16: ("shady_den", "creature_bank_to_shady_den"),
    # Dragon Utopia (25): Core guarded_res_banks/dragon_utopia is the same named guarded bank.
    25: ("dragon_utopia", "dragon_utopia_to_dragon_utopia"),
    28: ("fairy_ring", "faerie_ring_to_fairy_ring"),
    31: ("fountain", "faith_to_fountain"),
    37: ("watchtower", "hut_of_magi_to_watchtower_reveal"),
    38: ("fountain", "idol_to_fountain"),
    42: ("watchtower", "lighthouse_to_watchtower_reveal"),
    60: ("watchtower", "pillar_of_fire_to_watchtower_reveal"),
    61: ("altar_of_magic_1", "axis_to_altar_of_magic"),
    64: ("quixs_path", "rally_flag_to_quixs_path_morale"),
    # Sanctuary maps to altar_of_magic_1 as the native protection/sanctuary family.
    80: ("altar_of_magic_1", "sanctuary_to_altar_of_magic"),
    95: ("tavern", "tavern_to_tavern"),
    # Trading Post (99) and its HotA snow variant (221) exchange resources; Core objects_logic/markets
    # `market` is the native resource-exchange object.
    99: ("market", "trading_post_to_market"),
    221: ("market", "trading_post_snow_to_market"),
    # Formerly dropped (payloadless) objects mapped to the Olden Era object of the same role; the
    # user accepted the Olden Era numbers (docs/homm3_map_object_animation_audit.md, Objects that
    # draw nothing). Evidence: Core objects_logic.
    7: ("forge", "black_market_to_forge"),  # item_markets/forge: buy/sell items
    13: ("watchtower", "cartographer_to_watchtower_reveal"),  # vision_banks/watchtower: reveal r15
    22: ("abandoned_corpse", "corpse_to_abandoned_corpse"),  # resource_banks/abandoned_corpse
    48: ("mana_well", "magic_spring_to_mana_well"),  # hero_res_banks/mana_well: mana to 100%
    56: ("fountain", "oasis_to_fountain"),  # hero_res_banks/fountain: +movement
    84: ("overgrown_grave", "crypt_to_overgrown_grave"),  # guarded_res_banks: guarded gold + rare item
    105: ("peasant_cart", "wagon_to_peasant_cart"),  # resource_banks/peasant_cart
    108: ("heros_crypt", "warriors_tomb_to_heros_crypt"),  # item + debuff, the same bargain
    110: ("fountain", "watering_hole_to_fountain"),
    # Border Guard (9): Core map/objects/9_blocks campaign_FX_block (visible fx_map_smoke, one
    # blocked node) is the native key-gated passage: native story maps delete it with a quest
    # DeleteEntity. raw_translation/border_guard_gates.py binds each guard to its Keymaster's Tent.
    9: ("campaign_FX_block", "border_guard_to_campaign_fx_block_key_gate"),
    111: ("portal_magic", "whirlpool_to_magic_portal_same_layer"),
    222: ("camp_fire", "hota_campfire_to_camp_fire"),
    # Freelancer's Guild (213) -> Core objects_logic/unit_res_trade_labs/unit_trade_lab_kitten_horn,
    # the nearest native unit-for-resources trader. Behaviour differs and the user accepted it
    # (2026-09-26): HoMM3 buys any of the hero's creatures for resources; this hires kitten_horn
    # for 1 crystal. docs/homm3_map_object_animation_audit.md, "Objects that draw nothing".
    213: ("unit_trade_lab_kitten_horn", "freelancers_guild_to_unit_trade_lab_kitten_horn"),
}

MONOLITH_TWO_WAY_ANIMATION_EXACT_MAP: dict[str, tuple[str, str]] = {
    "AVXmn2g0.def": ("portal_1", "monolith_two_way_green_to_portal_1"),
    "AVXmn2o0.def": ("portal_2", "monolith_two_way_orange_to_portal_2"),
    "AVXmn2p0.def": ("portal_3", "monolith_two_way_purple_to_portal_3"),
    # SoD/AB two-way color packs (live H3M templates; portal_* family already in Core).
    "AVXmn5b0.def": ("portal_4", "monolith_two_way_blue_to_portal_4"),
    "AVXmn5.def": ("portal_4", "monolith_two_way_blue_to_portal_4"),
    "AVXmn6b0.def": ("portal_3", "monolith_two_way_teal_to_portal_3"),
    "AVXmn6.def": ("portal_3", "monolith_two_way_teal_to_portal_3"),
    "AVXmn7b0.def": ("portal_5", "monolith_two_way_yellow_to_portal_5"),
    "AVXmn7.def": ("portal_5", "monolith_two_way_yellow_to_portal_5"),
    "AVXmn8b0.def": ("portal_1_2", "monolith_two_way_violet_to_portal_1_2"),
    "AVXmn8.def": ("portal_1_2", "monolith_two_way_violet_to_portal_1_2"),
    # avxmn4b0 (Fall of Sandro) had no entry and was dropped; portal_2_2 is unused by the table.
    "AVXmn4b0.def": ("portal_2_2", "monolith_two_way_mn4b_to_portal_2_2"),
}

SHRINE_TEMPLATE_SID_MAP: dict[int, tuple[str, str]] = {
    h3obj.OBJECT_SHRINE_INCANTATION: ("scroll_box", "shrine_incantation_to_scroll_box"),
    h3obj.OBJECT_SHRINE_GESTURE: ("enchanted_scroll_box", "shrine_gesture_to_enchanted_scroll_box"),
    h3obj.OBJECT_SHRINE_THOUGHT: ("mythic_scroll_box", "shrine_thought_to_mythic_scroll_box"),
}

BLOCKED_ANIMATION_RULES: dict[str, str] = {}

MINE_ANIMATION_EXACT_MAP = {
    "AVMalch0.def": "mine_mercury",
    "AVMalcs0.def": "mine_mercury",
    "AVMsulf0.def": "mine_mercury",
    "AVMorsb0.def": "mine_ore",
    "AVMorsn0.def": "mine_ore",
    # Common dirt/grass/snow ore & gold variants (fuzzy tokens miss these spellings).
    "AVMordr0.def": "mine_ore",
    "AVMorlv0.def": "mine_ore",
    "AVMorro0.def": "mine_ore",
    "AVMgold0.def": "mine_gold",
    "AVMgodr0.def": "mine_gold",
    "AVMgorf0.def": "mine_gold",
    "AVMgods0.def": "mine_gold",
    "AVMsawm0.def": "mine_wood",
    "AVMswmp0.def": "mine_wood",
    "AVMcrys0.def": "mine_crystals",
    "AVMgems0.def": "mine_gemstones",
    # Additional ore / abandoned-mine adventure DEF stems (SoD/AB + abandoned).
    # Abandoned Mine is a capturable mine in HoMM3; emit as gold mine (not OE outpost→town).
    "AVMgovo0.def": "mine_gold",
    "AVMords0.def": "mine_ore",
    "AVXamGr.def": "mine_gold",
    "AVXamgr0.def": "mine_gold",
    "AVXabnd0.def": "mine_gold",
    "AVXabnd.def": "mine_gold",
    "AvMAbMG.def": "mine_gold",
    "AVMABMG.def": "mine_gold",
    "avmabmg.def": "mine_gold",
}

# CREATURE_GENERATOR_ANIMATION_EXACT_MAP imported from homm3_external_dwelling_map.

# Empty: every former placeholder now has a direct translator rule name.
LOSSY_PLACEHOLDER_RULES: set[str] = set()

RANDOM_ARTIFACT_RARITY_RULE = {
    h3obj.OBJECT_RANDOM_ARTIFACT: ("random-item", "random_artifact_any_to_random_item"),
    h3obj.OBJECT_RANDOM_ARTIFACT_TREASURE: ("random-item", "random_artifact_treasure_to_random_item"),
    h3obj.OBJECT_RANDOM_ARTIFACT_MINOR: ("random-item", "random_artifact_minor_to_random_item"),
    h3obj.OBJECT_RANDOM_ARTIFACT_MAJOR: ("random-item", "random_artifact_major_to_random_item"),
    h3obj.OBJECT_RANDOM_ARTIFACT_RELIC: ("random-item", "random_artifact_relic_to_random_item"),
}

H3_TERRAIN_BIOME = {
    0: "dirt",
    1: "desert",
    2: "grass",
    3: "snow",
    4: "dead",
    5: "grass",
    6: "dirt",
    7: "lava",
    8: "water",
    9: "grass",
}

TERRAIN_OBJECT_ROLES = {
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
    136: "rock",  # HoMM3 Outcropping (AVLoc* / AVLo*sn*); not a lake
    137: "tree",
    147: "rock",
    148: "ruin",
    149: "pool_big",
    150: "shrub",
    151: "rock",
    153: "rock",
    155: "terrain_animation_classification_required",
    # HotA decoration families (DEF first frames reviewed 2026-09-26): 199 is trees (avlswt*/avlswtr*
    # palms and jungle, avltro*/avltrro* rough trees); 206 desert / 209 rough / 210 subterranean are
    # rock clumps; 207 dirt / 208 grass / 211 swamp are bush-and-flower clumps; 117 is a gully.
    # Every one has only blocked cells, which the gap fill already seals.
    117: "ground",
    199: "tree",
    206: "rock",
    207: "shrub",
    208: "shrub",
    209: "rock",
    210: "rock",
    211: "shrub",
}

# HotA magic-terrain overlays (223-231) are fully passable in HoMM3 (block mask all 255), so they
# can only be drawn with a non-blocking native object: a pathable 1-cell Environment decoration or
# a sizeless Core FX. The FX are Olden Era's own effects; the Environment picks are static.
# Favorable Winds (225, on open sea) has no fitting native object and stays ledgered.
HOTA_MAGIC_TERRAIN_OVERLAY_MAP: dict[int, tuple[tuple[str, ...], str]] = {
    223: (("dead_stones_1", "dead_stones_2"), "cursed_ground_to_dead_stones"),
    224: (("fx_fog",), "evil_fog_to_fx_fog"),
    226: (("fx_map_fire",), "fire_fields_to_fx_map_fire"),
    227: (("flowers_1", "flowers_2"), "holy_ground_to_flowers"),
    228: (("fx_fireflies_blue",), "lucid_pools_to_fx_fireflies_blue"),
    229: (("fx_fog",), "magic_clouds_to_fx_fog"),
    230: (("fx_fireflies_yellow",), "magic_plains_to_fx_fireflies_yellow"),
    231: (("dirt_stones_1", "dirt_stones_2"), "rocklands_to_dirt_stones"),
}


def choose_hota_magic_terrain_overlay(row: dict[str, Any], valid_ids: set[str]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    import hashlib

    template_id = int(row.get("templateObjectId") or 0)
    mapping = HOTA_MAGIC_TERRAIN_OVERLAY_MAP.get(template_id)
    if mapping is None:
        return None, None, None, None
    pool, rule_name = mapping
    live = [sid for sid in pool if sid in valid_ids]
    if not live:
        return None, f"{rule_name}_missing_valid_target", "blocked", {
            "method": "hota_magic_terrain_overlay_pathable",
            "blockedReason": "no overlay stand-in SID is in the valid entity catalog",
            "pool": list(pool),
        }
    seed = str(row.get("sourceKey") or row.get("sourceIndex") or row.get("templateAnimation") or "overlay")
    digest = hashlib.sha256(f"hota-overlay:{template_id}:{seed}".encode("utf-8")).hexdigest()
    replacement = live[int(digest[:12], 16) % len(live)]
    return replacement, rule_name, "visual_context_only", {
        "method": "hota_magic_terrain_overlay_pathable",
        "templateObjectId": template_id,
        "templateAnimation": row.get("templateAnimation"),
        "pool": live,
        "replacementSid": replacement,
    }

# Canonical single SID per role/biome (used when no variant seed is provided).
BIOME_ROLE_REPLACEMENTS = {
    "mountain": {
        "grass": "mountain_green_small_1",
        "snow": "mountain_snow_small_1",
        "dirt": "mountain_dirt_small_1",
        "desert": "mountain_dirt_small_1",
        "dead": "mountain_dead_small_1",
        "lava": "mountain_lava_small_1",
        "water": "mountain_water_small_1",
    },
    "pool": {
        "grass": "pool_small",
        "snow": "pool_snow_small_1",
        "dirt": "pool_dirt_small_1",
        "desert": "pool_desert_small_1",
        "dead": "pool_dead_small_1",
        "lava": "pool_lava_small_1",
        "water": "water_reed_1",
    },
    "pool_big": {
        "grass": "pool_big",
        "snow": "pool_snow_big_1",
        "dirt": "pool_dirt_big_1",
        "desert": "pool_desert_big_1",
        "dead": "pool_dead_big_1",
        "lava": "pool_lava_big_1",
        "water": "water_reed_1",
    },
    "tree": {
        "grass": "pinetree_1",
        "snow": "pinetree_snow_1",
        "dirt": "tree_dirt_1",
        "desert": "grass_desert_1",
        "dead": "tree_dead_1",
        "lava": "tree_lava_1",
        "water": "water_reed_1",
    },
    "shrub": {
        "grass": "grass_1",
        "snow": "grass_snow_1",
        "dirt": "dirt_strange_flower",
        "desert": "grass_desert_1",
        "dead": "grass_death_1",
        "lava": "lava_ground_1",
        "water": "water_reed_1",
    },
    "rock": {
        "grass": "grass_stones_1",
        "snow": "snow_stones_1",
        "dirt": "dirt_rock_1",
        "desert": "desert_stones_1",
        "dead": "dead_stones_1",
        "lava": "lava_stones_1",
        "water": "water_reed_1",
    },
    "ground": {
        "grass": "grass_stones_1",
        "snow": "snow_stones_1",
        "dirt": "dirt_stones_1",
        "desert": "desert_dune_1",
        "dead": "dead_meadow",
        "lava": "lava_ground_1",
        "water": "water_reed_1",
    },
    "ruin": {
        "grass": "rocks_1",
        "snow": "snow_rock_hill_1",
        "dirt": "dirt_rock_1",
        "desert": "ruins_desert_1",
        "dead": "dead_sculls_bones_hill",
        "lava": "dirt_volcanic_rock",
        "water": "water_reed_1",
    },
    "water_decoration": {
        "grass": "water_reed_1",
        "snow": "water_reed_1",
        "dirt": "water_reed_1",
        "desert": "water_reed_1",
        "dead": "water_reed_1",
        "lava": "water_reed_1",
        "water": "water_reed_1",
    },
}

# Equivalent scenery variants keyed by (role, biome, occupied_cell_count).
# Deterministic selection uses stable_node_score at map generation time.
SCENERY_VARIANT_GROUPS: dict[tuple[str, str, int], list[str]] = {
    ("mountain", "grass", 1): ["mountain_green_small_1", "mountain_green_small_2"],
    ("mountain", "grass", 4): ["mountain_green_big_1", "mountain_green_big_2"],
    ("mountain", "grass", 9): ["mountain_green_big_3", "mountain_green_big_4"],
    ("mountain", "snow", 1): ["mountain_snow_small_1", "mountain_snow_small_2"],
    ("mountain", "snow", 4): ["mountain_snow_big_1", "mountain_snow_big_2"],
    ("mountain", "snow", 9): ["mountain_snow_big_3", "mountain_snow_big_4"],
    ("mountain", "dirt", 1): ["mountain_dirt_small_1", "mountain_dirt_small_2"],
    ("mountain", "dirt", 4): ["mountain_dirt_big_1", "mountain_dirt_big_2"],
    ("mountain", "dirt", 9): ["mountain_dirt_big_3", "mountain_dirt_big_4"],
    ("mountain", "desert", 1): ["mountain_desert_1", "mountain_desert_2"],
    ("mountain", "desert", 4): ["mountain_desert_3", "mountain_desert_4"],
    ("mountain", "desert", 9): ["mountain_desert_5", "mountain_desert_6"],
    ("mountain", "dead", 1): ["mountain_dead_small_1", "mountain_dead_small_2"],
    ("mountain", "dead", 4): ["mountain_dead_big_1", "mountain_dead_big_2"],
    ("mountain", "dead", 9): ["mountain_dead_big_3", "mountain_dead_big_4"],
    ("mountain", "lava", 1): ["mountain_lava_small_1", "mountain_lava_small_2", "mountain_lava_small_3", "mountain_lava_small_4"],
    ("mountain", "lava", 4): ["mountain_lava_big_1", "mountain_lava_big_2"],
    ("mountain", "lava", 9): ["mountain_lava_big_3", "mountain_lava_big_4"],
    ("mountain", "water", 1): ["mountain_water_small_1", "mountain_water_small_2", "mountain_water_small_3"],
    ("mountain", "water", 4): ["mountain_water_big_1", "mountain_water_big_2", "mountain_water_big_3"],
    ("pool", "grass", 4): ["pool_small"],
    ("pool", "snow", 4): ["pool_snow_small_1", "pool_snow_small_2"],
    ("pool", "dirt", 4): ["pool_dirt_small_1"],
    ("pool", "desert", 4): ["pool_desert_small_1"],
    ("pool", "dead", 4): ["pool_dead_small_1"],
    ("pool", "lava", 4): ["pool_lava_small_1"],
    ("pool_big", "grass", 9): ["pool_big"],
    ("pool_big", "snow", 9): ["pool_snow_big_1"],
    ("pool_big", "dirt", 9): ["pool_dirt_big_1"],
    ("pool_big", "desert", 9): ["pool_desert_big_1"],
    ("pool_big", "dead", 9): ["pool_dead_big_1"],
    ("pool_big", "lava", 9): ["pool_lava_big_1", "pool_lava_big_2"],
    ("tree", "grass", 1): ["pinetree_1", "pinetree_2", "pinetree_3", "pinetree_4"],
    ("tree", "snow", 1): ["pinetree_snow_1", "pinetree_snow_2", "pinetree_snow_3", "pinetree_snow_4"],
    ("tree", "dirt", 1): ["tree_dirt_1", "tree_dirt_2", "tree_dirt_3", "tree_dirt_4"],
    ("tree", "dead", 1): ["tree_dead_1", "tree_dead_2", "tree_dead_3", "tree_dead_4"],
    ("tree", "lava", 1): ["tree_lava_1", "tree_lava_2", "tree_lava_3"],
}

HOMM3_SOURCE_BUILDING_DESCRIPTIONS = {
    4: {
        "sourceName": "Arena",
        "sourceDescription": "Permanently trains the visiting hero to increase Attack or Defense.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["defence", "offence"],
        "expectedReplacementSid": "fort",
        "ruleName": "arena_to_pauper_knight_order_stats_bank",
        "badControls": ["arena"],
    },
    23: {
        "sourceName": "Marletto Tower",
        "sourceDescription": "Permanently increases the visiting hero Defense.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["defence"],
        "expectedReplacementSid": "armory_automaton",
        "ruleName": "marletto_tower_to_summit_automaton_defense_bank",
        "badControls": ["market"],
    },
    41: {
        "sourceName": "Library of Enlightenment",
        "sourceDescription": "Permanently increases Attack, Defense, Spell Power, and Knowledge for an experienced visiting hero.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["defence", "intelligence", "offence", "spellPower"],
        "expectedReplacementSid": "college_of_wonder",
        "ruleName": "library_to_mountain_monastery_all_stats_bank",
        "badControls": ["lost_library"],
    },
    47: {
        "sourceName": "School of Magic",
        "sourceDescription": "Lets the visiting hero choose a permanent increase to Spell Power or Knowledge.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["intelligence", "spellPower"],
        "expectedReplacementSid": "orb_observatory",
        "ruleName": "school_of_magic_to_four_scholars_observatory_magic_stats_bank",
        "badControls": ["learning_stone"],
    },
    51: {
        "sourceName": "Mercenary Camp",
        "sourceDescription": "Permanently increases the visiting hero Attack.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["offence"],
        "expectedReplacementSid": "stinging_sword",
        "ruleName": "mercenary_camp_to_stinging_sword_attack_bank",
        "badControls": ["mercenary_guild"],
    },
    96: {
        "sourceName": "Temple",
        "sourceDescription": "Blesses the visiting hero with extra Morale for a limited time.",
        "requiredTargetLogicSourceTokens": ["buff_banks"],
        "requiredRewardTypes": ["HeroBuffReward"],
        "requiredBuffParameters": ["quixs_path_buff"],
        "expectedReplacementSid": "quixs_path",
        "ruleName": "temple_to_quixs_altar_morale_bank",
        "badControls": ["fickle_shrine"],
    },
    107: {
        "sourceName": "School of War",
        "sourceDescription": "Permanently increases the visiting hero Attack or Defense after the hero chooses one of those two primary stats.",
        "requiredTargetLogicSourceTokens": ["stats_banks"],
        "requiredRewardTypes": ["HeroStatsReward"],
        "requiredTargetStats": ["defence", "offence"],
        "expectedReplacementSid": "fort",
        "ruleName": "school_of_war_to_pauper_knight_order_stats_bank",
        "badControls": ["arena"],
    },
    113: {
        "sourceName": "Witch Hut",
        "sourceDescription": "Teaches the visiting hero a random secondary skill.",
        "requiredTargetLogicSourceTokens": ["skill_banks"],
        "requiredRewardTypes": ["HeroSkillAdditionReward"],
        "requiredSkillParameterPrefix": "skill_",
        "minimumSkillParameterCount": 3,
        "expectedReplacementSid": "wise_owl",
        "ruleName": "witch_hut_to_wise_owl_skill_bank",
        "badControls": ["university"],
    },
}

PAYLOAD_BUILDING_TEMPLATE_IDS = {
    "witch_hut": 113,
}

HOMM3_ARTIFACT_EFFECT_PROFILES: dict[int, dict[str, Any]] = {
    25: {
        "sourceName": "Breastplate of Petrified Wood",
        "sourceDescription": "Grants +1 Spell Power to the visiting hero when equipped.",
        "sourceSlotHint": "armor",
        "effects": [{"family": "hero_primary_stat", "stat": "spellPower", "value": 1.0}],
    },
    35: {
        "sourceName": "Sword of Judgement",
        "sourceDescription": "Grants +5 Attack, +5 Defense, +5 Spell Power, and +5 Knowledge to the visiting hero when equipped.",
        "sourceSlotHint": "hand",
        "effects": [
            {"family": "hero_primary_stat", "stat": "offence", "value": 5.0},
            {"family": "hero_primary_stat", "stat": "defence", "value": 5.0},
            {"family": "hero_primary_stat", "stat": "spellPower", "value": 5.0},
            {"family": "hero_primary_stat", "stat": "intelligence", "value": 5.0},
        ],
    },
    56: {
        "sourceName": "Dead Man's Boots",
        "sourceDescription": "Increases the hero's necromancy raise percentage by 15 when equipped.",
        "sourceSlotHint": "boots",
        "effects": [{"family": "necromancy_raise_percent", "value": 15.0}],
        "unrepresentedRuleName": "artifact_effect_shape_unrepresented_necromancy_raise_percent",
    },
    57: {
        "sourceName": "Garniture of Interference",
        "sourceDescription": "Grants 5% magic resistance to the visiting hero when equipped.",
        "sourceSlotHint": "misc",
        "effects": [{"family": "magic_defense_percent", "value": 5.0}],
    },
    58: {
        "sourceName": "Surcoat of Counterpoise",
        "sourceDescription": "Grants 10% magic resistance to the visiting hero when equipped.",
        "sourceSlotHint": "back",
        "effects": [{"family": "magic_defense_percent", "value": 10.0}],
    },
}

ARTIFACT_RANDOM_TEMPLATE_IDS = h3obj.RANDOM_ARTIFACT_OBJECT_IDS
ARTIFACT_EFFECT_MATCH_CONFIDENCE = "artifact_effect_shape"
ARTIFACT_STAT_ORDER = {"offence": 0, "defence": 1, "spellPower": 2, "intelligence": 3}

EXACT_TEMPLATE_RULES = {
    2: ("altar_of_magic_1", "template_altar"),
    # HoMM3 Crystal restores/doubles mana; OE Well fully restores mana.
    21: ("mana_well", "template_crystal_to_mana_well"),
    27: ("insaras_eye", "template_eye"),
    30: ("fountain", "template_fountain"),
    32: ("knowledge_garden", "template_garden"),
    35: ("snow_grassy_hill_1", "template_hill"),
    39: ("learning_stone", "template_learning_object"),
    46: ("altar_of_magic_1", "template_plains_shrine"),
    49: ("mana_well", "template_well"),
    55: ("mysterious_stone", "template_mystic_object"),
    58: ("watchtower", "redwood_observatory_to_watchtower_reveal"),
    82: ("chest", "template_sea_chest"),
    86: ("watchtower", "template_surveyor"),
    94: ("stables", "template_stables"),
    97: ("shady_den", "template_den"),
    # HoMM3 Gazebo grants XP; Learning Stone is the native XP visit object.
    100: ("learning_stone", "template_gazebo_to_learning_stone"),
    101: ("chest", "template_chest"),
    102: ("tree_of_knowledge", "template_tree"),
    104: ("university", "template_university"),
    109: ("windmill", "template_windmill"),
    # Wind-themed adventure art (AVMwndd*) is weekly windmill resources, not Wind Rose map reveal.
    112: ("windmill", "template_windmill"),
    118: ("mountain_lava_small_1", "template_lava_lake"),
    119: ("dead_meadow", "template_dead_swamp"),
    120: ("flowers_1", "template_flowers"),
    124: ("pool_snow_small_1", "template_hole"),
    125: ("pool_dirt_small_1", "template_lake"),
    126: ("pool_lava_small_1", "template_lava_lake"),
    127: ("pool_dirt_big_1", "template_large_lake"),
    128: ("pool_dirt_small_1", "template_lake"),
    129: ("mountain_snow_small_1", "template_mountain_snow"),
    130: ("log_1", "template_log"),
    131: ("mountain_dirt_small_1", "template_mountain"),
    132: ("mushrooms_1", "template_moss"),
    133: ("mountain_green_small_1", "template_mountain_green"),
    134: ("mountain_snow_small_1", "template_mountain_snow"),
    135: ("pinetree_snow_1", "template_snow_pine"),
    136: ("rocks_1", "template_outcropping"),
    137: ("pinetree_snow_1", "template_snow_tree"),
    147: ("dirt_rock_1", "template_rough_ground"),
    148: ("ruins_desert_1", "template_dungeon_entrance"),
    149: ("pool_lava_big_1", "template_spit_pool"),
    150: ("grass_1", "template_shrub"),
    151: ("dead_skulls_hill", "template_skull"),
    153: ("snow_stones_1", "template_snow_stone"),
    155: ("tree_dirt_1", "template_tree"),
    161: ("fx_map_light", "template_reflection"),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def open_core_zip(source_core: str | Path) -> zipfile.ZipFile:
    """Return a process-lifetime open ZipFile for Core.zip (fail-closed on open errors)."""
    key = str(Path(source_core).resolve())
    cached = _CORE_ZIP_BY_PATH.get(key)
    if cached is not None:
        return cached
    archive = zipfile.ZipFile(key, "r")
    _CORE_ZIP_BY_PATH[key] = archive
    return archive


def close_core_zips() -> None:
    """Close all cached Core.zip handles. Safe to call multiple times."""
    for key, archive in list(_CORE_ZIP_BY_PATH.items()):
        try:
            archive.close()
        finally:
            _CORE_ZIP_BY_PATH.pop(key, None)


atexit.register(close_core_zips)


def load_english_artifact_tokens(source_core: str) -> dict[str, str]:
    archive = open_core_zip(source_core)
    payload = json.loads(archive.read(ENGLISH_ARTIFACT_TEXT).decode("utf-8-sig"))
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError(f"{ENGLISH_ARTIFACT_TEXT} must contain a tokens array")
    return {row["sid"]: row["text"] for row in tokens if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str)}


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def canonical_artifact_effects_from_bonuses(bonuses: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effects: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for bonus in bonuses:
        if not isinstance(bonus, dict):
            unsupported.append({"reason": "bonus_not_object", "bonus": bonus})
            continue
        parameters = bonus.get("parameters")
        bonus_type = bonus.get("type")
        parsed = False
        if bonus_type == "heroStat" and isinstance(parameters, list) and len(parameters) >= 2 and isinstance(parameters[0], str):
            value = parse_float(parameters[1])
            stat = parameters[0]
            if value is not None and stat in ARTIFACT_STAT_ORDER:
                effects.append({"family": "hero_primary_stat", "stat": stat, "value": value, "activationLevel": bonus.get("activationLevel")})
                parsed = True
            elif value is not None and stat == "spellPowerPer":
                effects.append({"family": "spell_power_percent", "value": value * 100.0, "activationLevel": bonus.get("activationLevel")})
                parsed = True
        elif bonus_type == "unitStat" and isinstance(parameters, list) and len(parameters) >= 4 and parameters[:3] == ["modifierSet", "inDmgMods", "magic_damage"]:
            value = parse_float(parameters[3])
            if value is not None and value < 0:
                effects.append({"family": "magic_defense_percent", "value": abs(value) * 100.0, "activationLevel": bonus.get("activationLevel")})
                parsed = True
        if not parsed:
            unsupported.append({"reason": "unsupported_artifact_bonus_shape", "type": bonus_type, "parameters": parameters, "activationLevel": bonus.get("activationLevel")})
    sorted_effects = sorted(effects, key=lambda effect: (str(effect.get("family")), ARTIFACT_STAT_ORDER.get(str(effect.get("stat")), 99), effect.get("activationLevel") is not None, float(effect.get("value") or 0.0)))
    return sorted_effects, unsupported


def base_artifact_effects(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [effect for effect in effects if effect.get("activationLevel") is None]


def artifact_effect_key(effect: dict[str, Any]) -> tuple[str, str]:
    return str(effect.get("family")), str(effect.get("stat") or "")


def artifact_effect_shape_key(effects: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return sorted(artifact_effect_key(effect) for effect in effects)


def artifact_effect_value_distance(source_effects: list[dict[str, Any]], target_effects: list[dict[str, Any]]) -> float:
    target_by_key = {artifact_effect_key(effect): effect for effect in target_effects}
    distance = 0.0
    for source in source_effects:
        target = target_by_key[artifact_effect_key(source)]
        distance += abs(float(target.get("value") or 0.0) - float(source.get("value") or 0.0))
    return distance


def normalized_artifact_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def load_english_text_tokens(core_catalog: dict[str, Any]) -> dict[str, str]:
    source_core = core_catalog.get("sourceCoreZip")
    if not isinstance(source_core, str):
        raise ValueError("core catalog must record sourceCoreZip for localized substitution evidence")
    archive = open_core_zip(source_core)
    payload = json.loads(archive.read(ENGLISH_MAP_OBJECT_TEXT).decode("utf-8-sig"))
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError(f"{ENGLISH_MAP_OBJECT_TEXT} must contain a tokens array")
    result: dict[str, str] = {}
    for row in tokens:
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
            result[row["sid"]] = row["text"]
    return result


def localized_map_object_details(candidate_sid: str, core_catalog: dict[str, Any], english_tokens: dict[str, str]) -> dict[str, Any]:
    source_core = core_catalog.get("sourceCoreZip")
    if not isinstance(source_core, str):
        raise ValueError("core catalog must record sourceCoreZip for localized substitution evidence")
    details: dict[str, Any] = {"sid": candidate_sid, "name": None, "description": None, "narrativeDescription": None, "logicSources": []}
    for logic_row in core_catalog.get("objectLogicRows", []):
        if isinstance(logic_row, dict) and logic_row.get("id") == candidate_sid and isinstance(logic_row.get("source"), str):
            details["logicSources"].append(logic_row["source"])
    for row in core_catalog.get("mapObjects", []):
        if not isinstance(row, dict) or row.get("id") != candidate_sid:
            continue
        source = row.get("source")
        if not isinstance(source, str):
            return details
        archive = open_core_zip(source_core)
        data = json.loads(archive.read(source).decode("utf-8-sig"))
        for object_row in data.get("array", []):
            if not isinstance(object_row, dict) or object_row.get("id") != candidate_sid:
                continue
            for field in ["name", "description", "narrativeDescription"]:
                token_sid = object_row.get(field)
                token_resolution = "explicit"
                if not isinstance(token_sid, str):
                    token_sid = f"{candidate_sid}_{field}"
                    token_resolution = "implicit_sid_suffix"
                details[f"{field}TokenSid"] = token_sid
                details[f"{field}TokenResolution"] = token_resolution
                details[field] = english_tokens.get(token_sid)
            return details
    return details


def source_embedding_text(rule: dict[str, Any]) -> str:
    return f"{rule['sourceName']}. {rule['sourceDescription']}"


def target_embedding_text(details: dict[str, Any]) -> str:
    parts = [details.get("name"), details.get("description")]
    return ". ".join(part for part in parts if isinstance(part, str) and part)


def logic_sources_match(logic_sources: list[Any], required_tokens: list[str]) -> bool:
    joined_logic_sources = " ".join(str(source).lower() for source in logic_sources)
    return all(token.lower() in joined_logic_sources for token in required_tokens)


def load_minilm_model() -> SentenceTransformer:
    # Imported here: torch + transformers cost ~20 s per process, and the raw_translation
    # emit imports this module for its tables without ever loading the model.
    import torch
    from sentence_transformers import SentenceTransformer

    os.environ.setdefault("HF_HOME", str(REPO_ROOT / ".cache" / "huggingface"))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MINILM_CACHE_ROOT))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if not torch.cuda.is_available():
        raise RuntimeError(
            "MiniLM substitution mapping requires CUDA; "
            f"torch={torch.__version__} cuda.is_available=False. "
            "Install a CUDA torch build (e.g. cu128) — CPU fallback is forbidden."
        )
    model = SentenceTransformer(MINILM_MODEL_NAME, device="cuda")
    dimension = model.get_embedding_dimension() if hasattr(model, "get_embedding_dimension") else model.get_sentence_embedding_dimension()
    if dimension != MINILM_EMBEDDING_DIMENSION:
        raise ValueError(f"MiniLM embedding dimension drift: {dimension} != {MINILM_EMBEDDING_DIMENSION}")
    return model


class ArtifactEffectMapper:
    def __init__(self, valid_ids: set[str], core_catalog: dict[str, Any]) -> None:
        self.valid_ids = valid_ids
        self.core_catalog = core_catalog
        source_core = core_catalog.get("sourceCoreZip")
        if not isinstance(source_core, str):
            raise ValueError("core catalog must record sourceCoreZip for artifact effect matching")
        self.source_core = source_core
        self.artifact_map_ids = {row["id"] for row in core_catalog.get("mapObjects", []) if isinstance(row, dict) and row.get("tag") == "Artifact" and isinstance(row.get("id"), str)}
        self.artifact_tokens = load_english_artifact_tokens(source_core)
        self.candidates_cache: list[dict[str, Any]] | None = None

    def localized_item_text(self, item: dict[str, Any], field: str) -> str:
        token_sid = item.get(field)
        if not isinstance(token_sid, str):
            token_sid = f"{item.get('id')}_{field}"
        return self.artifact_tokens.get(token_sid, "")

    def load_item_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        archive = open_core_zip(self.source_core)
        for member in archive.namelist():
            if not member.startswith("DB/items/items/") or not member.endswith(".json"):
                continue
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            for item in payload.get("array", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    rows.append({**item, "source": member})
        return rows

    def candidates(self) -> list[dict[str, Any]]:
        if self.candidates_cache is not None:
            return self.candidates_cache
        candidates: list[dict[str, Any]] = []
        for item in self.load_item_rows():
            sid = item["id"]
            if sid not in self.valid_ids or sid not in self.artifact_map_ids:
                continue
            effects, unsupported = canonical_artifact_effects_from_bonuses(item.get("bonuses") or [])
            base_effects = base_artifact_effects(effects)
            if unsupported or not base_effects:
                continue
            candidates.append({
                "sid": sid,
                "source": item.get("source"),
                "name": self.localized_item_text(item, "name"),
                "description": self.localized_item_text(item, "description"),
                "rarity": item.get("rarity"),
                "slot": item.get("slot_"),
                "goodsValue": item.get("goodsValue"),
                "effects": effects,
                "baseEffects": base_effects,
            })
        self.candidates_cache = sorted(candidates, key=lambda row: row["sid"])
        return self.candidates_cache

    def score_candidate(self, source_profile: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
        source_effects = source_profile["effects"]
        target_effects = candidate["baseEffects"]
        if artifact_effect_shape_key(source_effects) != artifact_effect_shape_key(target_effects):
            return None
        distance = artifact_effect_value_distance(source_effects, target_effects)
        source_total = max(1.0, sum(abs(float(effect.get("value") or 0.0)) for effect in source_effects))
        value_similarity = 1.0 / (1.0 + (distance / source_total))
        name_match = normalized_artifact_name(source_profile["sourceName"]) == normalized_artifact_name(candidate.get("name"))
        slot_hint = source_profile.get("sourceSlotHint")
        target_slot = candidate.get("slot")
        slot_match = slot_hint == target_slot or (slot_hint == "hand" and target_slot in {"left_hand", "right_hand"})
        score = 100.0 + (10.0 * value_similarity) + (5.0 if name_match else 0.0) + (3.0 if slot_match else 0.0)
        return {
            "sid": candidate["sid"],
            "targetEnglishName": candidate.get("name"),
            "targetEnglishDescription": candidate.get("description"),
            "targetEffects": target_effects,
            "targetAllEffects": candidate.get("effects"),
            "targetRarity": candidate.get("rarity"),
            "targetSlot": candidate.get("slot"),
            "targetGoodsValue": candidate.get("goodsValue"),
            "effectValueDistance": round(distance, 6),
            "effectValueSimilarity": round(value_similarity, 6),
            "nameMatch": name_match,
            "sourceSlotHint": slot_hint,
            "slotMatch": slot_match,
            "score": round(score, 6),
        }

    def choose(self, row: dict[str, Any]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
        template_id = row.get("templateObjectId")
        if template_id in ARTIFACT_RANDOM_TEMPLATE_IDS:
            mapping = RANDOM_ARTIFACT_RARITY_RULE.get(int(template_id))
            if mapping is None:
                evidence = {
                    "method": "random_artifact_rarity_table",
                    "blockedReason": "random HoMM3 artifact template missing rarity mapping",
                    "templateObjectId": template_id,
                    "templateAnimation": row.get("templateAnimation"),
                }
                return None, "artifact_random_requires_random_artifact_contract", "blocked", evidence
            replacement, rule_name = mapping
            evidence = {
                "method": "random_artifact_rarity_table",
                "templateObjectId": template_id,
                "templateAnimation": row.get("templateAnimation"),
                "replacementSid": replacement,
                "ruleName": rule_name,
            }
            if replacement not in self.valid_ids:
                evidence["blockedReason"] = "random-item SID missing from valid entity catalog"
                return None, f"{rule_name}_missing_valid_target", "blocked", evidence
            return replacement, rule_name, "role", evidence
        subtype = row.get("templateSubtype")
        # Prefer installed HoMM3 artifact catalog SID (map object id == item id).
        try:
            from vanilla_stock.h3_artifact_stock_map import catalog_item_sid_for_h3_artifact_id
        except ImportError:
            from h3_artifact_stock_map import catalog_item_sid_for_h3_artifact_id  # type: ignore

        if isinstance(subtype, int):
            catalog_sid = catalog_item_sid_for_h3_artifact_id(subtype)
            if catalog_sid:
                evidence = {
                    "method": "homm3_artifact_catalog_h3id",
                    "templateObjectId": template_id,
                    "templateSubtype": subtype,
                    "templateAnimation": row.get("templateAnimation"),
                    "replacementSid": catalog_sid,
                    "ruleName": "artifact_h3id_to_homm3_catalog_sid",
                }
                if catalog_sid not in self.valid_ids:
                    evidence["blockedReason"] = "catalog artifact SID missing from valid entity catalog"
                    return None, "artifact_catalog_sid_missing_valid_target", "blocked", evidence
                return catalog_sid, "artifact_h3id_to_homm3_catalog_sid", "direct_or_family_substitution", evidence
        source_profile = HOMM3_ARTIFACT_EFFECT_PROFILES.get(subtype)
        if source_profile is None:
            evidence = {
                "method": "artifact_effect_shape_similarity",
                "blockedReason": "HoMM3 artifact subtype is not in the effect-profile table or catalog",
                "templateObjectId": template_id,
                "templateSubtype": subtype,
                "templateAnimation": row.get("templateAnimation"),
            }
            return None, "artifact_effect_shape_unknown_subtype", "blocked", evidence
        source_effects = source_profile["effects"]
        top_candidates = [scored for candidate in self.candidates() if (scored := self.score_candidate(source_profile, candidate)) is not None]
        top_candidates.sort(key=lambda candidate: (-candidate["score"], candidate["effectValueDistance"], not candidate["nameMatch"], str(candidate["sid"])))
        if not top_candidates:
            rule_name = source_profile.get("unrepresentedRuleName") or f"artifact_effect_shape_unrepresented_{source_effects[0]['family']}"
            evidence = {
                "method": "artifact_effect_shape_similarity",
                "sourceSubtype": subtype,
                "sourceName": source_profile["sourceName"],
                "sourceDescription": source_profile["sourceDescription"],
                "sourceEffects": source_effects,
                "sourceSlotHint": source_profile.get("sourceSlotHint"),
                "blockedReason": "no Olden artifact exposes the same base effect shape",
                "candidateCount": len(self.candidates()),
            }
            return None, rule_name, "blocked", evidence
        best = top_candidates[0]
        evidence = {
            "method": "artifact_effect_shape_similarity",
            "sourceSubtype": subtype,
            "sourceName": source_profile["sourceName"],
            "sourceDescription": source_profile["sourceDescription"],
            "sourceEffects": source_effects,
            "sourceSlotHint": source_profile.get("sourceSlotHint"),
            "sourceTemplateAnimation": row.get("templateAnimation"),
            "targetEnglishName": best.get("targetEnglishName"),
            "targetEnglishDescription": best.get("targetEnglishDescription"),
            "targetEffects": best.get("targetEffects"),
            "targetAllEffects": best.get("targetAllEffects"),
            "score": best["score"],
            "effectValueDistance": best["effectValueDistance"],
            "effectValueSimilarity": best["effectValueSimilarity"],
            "nameMatch": best["nameMatch"],
            "candidateCountAfterEffectShapeFilter": len(top_candidates),
            "topCandidates": top_candidates[:5],
        }
        return best["sid"], f"artifact_effect_shape_{best['sid']}", ARTIFACT_EFFECT_MATCH_CONFIDENCE, evidence


class MiniLmBuildingMapper:
    def __init__(self, model: SentenceTransformer, valid_ids: set[str], core_catalog: dict[str, Any], english_tokens: dict[str, str]) -> None:
        self.model = model
        self.valid_ids = valid_ids
        self.core_catalog = core_catalog
        self.english_tokens = english_tokens
        source_core = core_catalog.get("sourceCoreZip")
        if not isinstance(source_core, str):
            raise ValueError("core catalog must record sourceCoreZip for MiniLM logic evidence")
        self.source_core = source_core
        self.details_cache: dict[str, dict[str, Any]] = {}
        self.embedding_cache: dict[str, np.ndarray] = {}
        self.logic_profile_cache: dict[str, dict[str, Any]] = {}
        self.candidates_by_rule_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}

    def details(self, sid: str) -> dict[str, Any]:
        if sid not in self.details_cache:
            self.details_cache[sid] = localized_map_object_details(sid, self.core_catalog, self.english_tokens)
        return self.details_cache[sid]

    def logic_profile(self, sid: str) -> dict[str, Any]:
        cached = self.logic_profile_cache.get(sid)
        if cached is not None:
            return cached
        reward_types: set[str] = set()
        stat_parameters: set[str] = set()
        buff_parameters: set[str] = set()
        skill_parameters: set[str] = set()
        details = self.details(sid)
        archive = open_core_zip(self.source_core)
        for source in details.get("logicSources") or []:
            if not isinstance(source, str):
                continue
            payload = json.loads(archive.read(source).decode("utf-8-sig"))
            for object_row in payload.get("array", []):
                for variant in object_row.get("variants", []) if isinstance(object_row, dict) else []:
                    reward_set = variant.get("rewardSet") if isinstance(variant, dict) else None
                    rewards = reward_set.get("rewards", []) if isinstance(reward_set, dict) else []
                    for reward in rewards:
                        if not isinstance(reward, dict):
                            continue
                        reward_type = reward.get("rewardType")
                        if isinstance(reward_type, str):
                            reward_types.add(reward_type)
                        params = reward.get("parameters") or []
                        if reward_type == "HeroStatsReward":
                            for index in range(0, len(params), 2):
                                if isinstance(params[index], str):
                                    stat_parameters.add(params[index])
                        elif reward_type == "HeroBuffReward":
                            if params and isinstance(params[0], str):
                                buff_parameters.add(params[0])
                        elif reward_type == "HeroSkillAdditionReward":
                            if params and isinstance(params[0], str):
                                skill_parameters.add(params[0])
        profile = {
            "rewardTypes": sorted(reward_types),
            "statParameters": sorted(stat_parameters),
            "buffParameters": sorted(buff_parameters),
            "skillParameters": sorted(skill_parameters),
        }
        self.logic_profile_cache[sid] = profile
        return profile

    def passes_structured_logic_filter(self, sid: str, rule: dict[str, Any]) -> bool:
        profile = self.logic_profile(sid)
        required_reward_types = set(rule.get("requiredRewardTypes", []))
        if required_reward_types and not required_reward_types.issubset(set(profile["rewardTypes"])):
            return False
        required_stats = rule.get("requiredTargetStats")
        if required_stats is not None and set(required_stats) != set(profile["statParameters"]):
            return False
        required_buffs = rule.get("requiredBuffParameters")
        if required_buffs is not None and not set(required_buffs).issubset(set(profile["buffParameters"])):
            return False
        required_skill_prefix = rule.get("requiredSkillParameterPrefix")
        if isinstance(required_skill_prefix, str):
            skill_parameters = profile["skillParameters"]
            if any(not str(skill).startswith(required_skill_prefix) for skill in skill_parameters):
                return False
            if len(skill_parameters) < int(rule.get("minimumSkillParameterCount", 1)):
                return False
        return True

    def embedding(self, text: str) -> np.ndarray:
        cached = self.embedding_cache.get(text)
        if cached is not None:
            return cached
        vector = self.model.encode([text], normalize_embeddings=True)[0]
        self.embedding_cache[text] = vector
        return vector

    def similarity(self, source_text: str, target_text: str) -> float:
        return float(np.dot(self.embedding(source_text), self.embedding(target_text)))

    def candidates(self, rule: dict[str, Any]) -> list[dict[str, Any]]:
        required_logic_tokens = rule["requiredTargetLogicSourceTokens"]
        key = (
            tuple(required_logic_tokens),
            tuple(rule.get("requiredRewardTypes", [])),
            tuple(rule.get("requiredTargetStats", [])),
            tuple(rule.get("requiredBuffParameters", [])),
            rule.get("requiredSkillParameterPrefix"),
            rule.get("minimumSkillParameterCount"),
        )
        cached = self.candidates_by_rule_key.get(key)
        if cached is not None:
            return cached
        result: list[dict[str, Any]] = []
        for sid in sorted(self.valid_ids):
            details = self.details(sid)
            target_text = target_embedding_text(details)
            logic_sources = details.get("logicSources") or []
            if target_text and logic_sources_match(logic_sources, required_logic_tokens) and self.passes_structured_logic_filter(sid, rule):
                result.append({"sid": sid, "details": details, "targetText": target_text, "logicProfile": self.logic_profile(sid)})
        self.candidates_by_rule_key[key] = result
        return result

    def score_control(self, source_text: str, sid: str, rule: dict[str, Any]) -> dict[str, Any]:
        required_logic_tokens = rule["requiredTargetLogicSourceTokens"]
        details = self.details(sid)
        target_text = target_embedding_text(details)
        if not target_text:
            raise ValueError(f"MiniLM bad-control target {sid!r} has no localized English target text")
        score = self.similarity(source_text, target_text)
        logic_sources = details.get("logicSources") or []
        return {
            "sid": sid,
            "targetEnglishName": details.get("name"),
            "targetEnglishDescription": details.get("description"),
            "targetLogicSources": sorted(logic_sources),
            "targetLogicProfile": self.logic_profile(sid),
            "score": round(score, 6) if isinstance(score, float) else None,
            "passesLogicSourceFilter": logic_sources_match(logic_sources, required_logic_tokens),
            "passesStructuredLogicFilter": self.passes_structured_logic_filter(sid, rule),
        }

    def choose(self, template_id: int) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
        rule = HOMM3_SOURCE_BUILDING_DESCRIPTIONS.get(template_id)
        if rule is None:
            return None, None, None, None
        required_logic_tokens = rule["requiredTargetLogicSourceTokens"]
        source_text = source_embedding_text(rule)
        scored: list[tuple[float, dict[str, Any]]] = []
        for candidate in self.candidates(rule):
            score = self.similarity(source_text, candidate["targetText"])
            scored.append((score, candidate))
        scored.sort(key=lambda row: row[0], reverse=True)
        if not scored:
            raise ValueError(f"no MiniLM target candidates for Homecoming template {template_id} with logic filters {required_logic_tokens}")
        best_score, best_candidate = scored[0]
        next_score = scored[1][0] if len(scored) > 1 else None
        margin = best_score - next_score if next_score is not None else None
        if best_score < MINILM_ACCEPTANCE_THRESHOLD:
            raise ValueError(f"MiniLM score too low for template {template_id}: {best_score:.6f} < {MINILM_ACCEPTANCE_THRESHOLD}")
        if margin is not None and margin < MINILM_MIN_ACCEPTANCE_MARGIN:
            raise ValueError(f"MiniLM margin too small for template {template_id}: {margin:.6f} < {MINILM_MIN_ACCEPTANCE_MARGIN}")
        replacement = best_candidate["sid"]
        expected = rule.get("expectedReplacementSid")
        if replacement != expected:
            raise ValueError(f"MiniLM selected {replacement!r} for template {template_id}, expected calibrated replacement {expected!r}")
        details = best_candidate["details"]
        bad_controls = [self.score_control(source_text, sid, rule) for sid in rule.get("badControls", [])]
        for control in bad_controls:
            score = control.get("score")
            if control.get("passesLogicSourceFilter") and control.get("passesStructuredLogicFilter") and isinstance(score, float) and score > MINILM_REJECT_THRESHOLD:
                raise ValueError(f"MiniLM bad control passed for template {template_id}: {control}")
        evidence = {
            "method": "minilm_semantic_description_similarity",
            "model": MINILM_MODEL_NAME,
            "embeddingDimension": MINILM_EMBEDDING_DIMENSION,
            "acceptanceThreshold": MINILM_ACCEPTANCE_THRESHOLD,
            "rejectThreshold": MINILM_REJECT_THRESHOLD,
            "minimumAcceptanceMargin": MINILM_MIN_ACCEPTANCE_MARGIN,
            "sourceName": rule["sourceName"],
            "sourceDescription": rule["sourceDescription"],
            "sourceEmbeddingText": source_text,
            "targetEnglishName": details.get("name"),
            "targetEnglishNameTokenSid": details.get("nameTokenSid"),
            "targetEnglishNameTokenResolution": details.get("nameTokenResolution"),
            "targetEnglishDescription": details.get("description"),
            "targetEnglishDescriptionTokenSid": details.get("descriptionTokenSid"),
            "targetEnglishDescriptionTokenResolution": details.get("descriptionTokenResolution"),
            "targetEmbeddingText": best_candidate["targetText"],
            "targetLogicSources": sorted(details.get("logicSources") or []),
            "targetLogicProfile": self.logic_profile(replacement),
            "requiredTargetLogicSourceTokens": required_logic_tokens,
            "requiredRewardTypes": rule.get("requiredRewardTypes", []),
            "requiredTargetStats": rule.get("requiredTargetStats", []),
            "requiredBuffParameters": rule.get("requiredBuffParameters", []),
            "requiredSkillParameterPrefix": rule.get("requiredSkillParameterPrefix"),
            "minimumSkillParameterCount": rule.get("minimumSkillParameterCount"),
            "score": round(best_score, 6),
            "nextBestScore": round(next_score, 6) if next_score is not None else None,
            "acceptanceMargin": round(margin, 6) if margin is not None else None,
            "candidateCountAfterLogicFilter": len(scored),
            "topCandidates": [
                {
                    "sid": candidate["sid"],
                    "targetEnglishName": candidate["details"].get("name"),
                    "targetEnglishDescription": candidate["details"].get("description"),
                    "score": round(score, 6),
                }
                for score, candidate in scored[:5]
            ],
            "badControls": bad_controls,
        }
        return replacement, rule["ruleName"], "minilm_semantic_family", evidence


def signature_for(entity: dict[str, Any]) -> str:
    return "|".join(
        str(entity.get(key, ""))
        for key in ["sid", "templateObjectId", "templateAnimation", "category", "payloadKind"]
    )


def choose_existing(candidate: str, valid_ids: set[str]) -> str | None:
    return candidate if candidate in valid_ids else None


def choose_by_animation(animation: str, table: dict[str, str], valid_ids: set[str]) -> tuple[str | None, str | None]:
    lower = animation.lower()
    for token, replacement in table.items():
        if token in lower and replacement in valid_ids:
            return replacement, f"animation_token_{token}"
    return None, None


def source_terrain_for_row(row: dict[str, Any], layer_tiles: dict[int, list[int]]) -> int | None:
    layer = row.get("sourceLayer")
    node = row.get("sourceNode")
    if not isinstance(layer, int) or not isinstance(node, int):
        return None
    tiles = layer_tiles.get(layer)
    if not isinstance(tiles, list) or node < 0 or node >= len(tiles):
        return None
    terrain = tiles[node]
    return terrain if isinstance(terrain, int) else None


def source_terrain_context(rows: list[dict[str, Any]], layer_tiles: dict[int, list[int]]) -> dict[str, Any]:
    terrain_values = [source_terrain_for_row(row, layer_tiles) for row in rows]
    terrain_values = [terrain for terrain in terrain_values if terrain is not None]
    terrain_histogram = Counter(terrain_values)
    biome_histogram = Counter(H3_TERRAIN_BIOME.get(terrain, "unknown") for terrain in terrain_values)
    dominant_biome = biome_histogram.most_common(1)[0][0] if biome_histogram else None
    return {
        "terrainHistogram": dict(sorted((str(k), v) for k, v in terrain_histogram.items())),
        "biomeHistogram": dict(sorted(biome_histogram.items())),
        "dominantBiome": dominant_biome,
    }


def load_layer_tiles(alignment: dict[str, Any]) -> dict[int, list[int]]:
    layers: dict[int, list[int]] = {}
    for layer in alignment.get("layeredMapData") or []:
        if not isinstance(layer, dict):
            continue
        layer_index = layer.get("layer")
        tiles = ((layer.get("mapData") or {}).get("tilesMap"))
        if isinstance(layer_index, int) and isinstance(tiles, list):
            layers[layer_index] = tiles
    return layers


def terrain_role_for_row(row: dict[str, Any]) -> str | None:
    template_id = row.get("templateObjectId")
    animation = str(row.get("templateAnimation") or "").lower()
    if template_id == 155:
        if "r04" in animation:
            return "rock"
        if "yuc" in animation:
            return "shrub"
        # Palms (avlplm*), rough trees (avlroug*), swamp trees (avlswmp*) and willows (avlwlw*).
        if "tr" in animation or any(token in animation for token in ("avlplm", "avlroug", "avlswmp", "avlwlw")):
            return "tree"
        return "terrain_animation_classification_required"
    return TERRAIN_OBJECT_ROLES.get(template_id)


def resolve_terrain_biome(terrain_context: dict[str, Any] | None) -> str | None:
    if not isinstance(terrain_context, dict):
        return None
    biome = terrain_context.get("dominantBiome")
    if isinstance(biome, str):
        return biome
    biome = terrain_context.get("biome")
    return biome if isinstance(biome, str) else None


def scenery_variant_candidates(role: str, biome: str, footprint_cells: int, valid_ids: set[str]) -> list[str]:
    candidates = SCENERY_VARIANT_GROUPS.get((role, biome, int(footprint_cells))) or []
    return [sid for sid in candidates if sid in valid_ids]


# Olden mountain/tree/pool variant buckets are solid 1x1 / 2x2 / 3x3 only.
# Mountains/trees plant **1x1 only** (multi-tile meshes overhang OCC onto H3-open
# neighbors); residual H3 blocks go to gap-fill. Pools may still use 2x2/3x3.
SCENERY_SOLID_SQUARE_SIDES = (3, 2, 1)
HOMM3_SCENERY_FOOTPRINT_POLICY = (
    "homm3_block_mask_1x1_only_for_mountain_tree_plus_gap_fill_residual_pool_keeps_solid_square"
)


def homm3_block_solid_squares(
    block_offsets: set[tuple[int, int]],
    side: int,
) -> list[tuple[int, int]]:
    """Return (min_dx, min_dy) origins of every solid side×side subset of BR-relative blocks."""
    if side < 1 or not block_offsets:
        return []
    xs = [dx for dx, _dy in block_offsets]
    ys = [dy for _dx, dy in block_offsets]
    origins: list[tuple[int, int]] = []
    for min_dy in range(min(ys), max(ys) + 1):
        for min_dx in range(min(xs), max(xs) + 1):
            cells = {
                (min_dx + dx, min_dy + dy)
                for dy in range(side)
                for dx in range(side)
            }
            if cells <= block_offsets:
                origins.append((min_dx, min_dy))
    return origins


def prefer_homm3_block_solid_square(
    block_offsets: set[tuple[int, int]],
    side: int,
) -> tuple[int, int] | None:
    """Pick one solid square origin; prefer BR cell (0,0), else BR-most."""
    origins = homm3_block_solid_squares(block_offsets, side)
    if not origins:
        return None

    def score(origin: tuple[int, int]) -> tuple[int, int, int, int, int]:
        min_dx, min_dy = origin
        br = (min_dx + side - 1, min_dy + side - 1)
        at_entity_br = 1 if br == (0, 0) else 0
        return (at_entity_br, br[0], br[1], -min_dx, -min_dy)

    return max(origins, key=score)


def largest_homm3_block_solid_square(
    block_offsets: set[tuple[int, int]],
    *,
    max_side: int = 3,
) -> dict[str, int] | None:
    """Largest solid square subset of HoMM3 BR-relative block offsets."""
    if not block_offsets:
        return None
    for side in SCENERY_SOLID_SQUARE_SIDES:
        if side > max_side:
            continue
        origin = prefer_homm3_block_solid_square(block_offsets, side)
        if origin is None:
            continue
        min_dx, min_dy = origin
        return {
            "side": side,
            "minDx": min_dx,
            "minDy": min_dy,
            "footprintCells": side * side,
            "brDx": min_dx + side - 1,
            "brDy": min_dy + side - 1,
        }
    return None


def scenery_footprint_cells_from_homm3_blocks(
    role: str,
    biome: str,
    block_offsets: set[tuple[int, int]],
    valid_ids: set[str],
) -> tuple[int | None, dict[str, Any]]:
    """Map HoMM3 block-mask solid squares to an Olden scenery variant bucket.

    Mountains/trees: **1x1 only**. Multi-tile Olden mountain/tree SIDs (especially
    ``*_big_*``) have meshes/collision that overhang their ObjectConfig OCC onto
    HoMM3-open neighbors. Residual H3 block cells are sealed by 1x1 gap-fill.

    Pools keep explicit 2x2/3x3 role buckets only when that solid square fits;
    otherwise skip so the caller can keep the canonical substitution.
    """
    evidence: dict[str, Any] = {
        "policy": HOMM3_SCENERY_FOOTPRINT_POLICY,
        "role": role,
        "biome": biome,
        "sourceBlockCellCount": len(block_offsets),
    }
    if role in {"pool", "pool_big"}:
        side = 3 if role == "pool_big" else 2
        origin = prefer_homm3_block_solid_square(block_offsets, side)
        cells = side * side
        evidence["requestedSide"] = side
        if origin is None:
            evidence["decision"] = "skip_variant_no_solid_square_for_pool_bucket"
            return None, evidence
        if not scenery_variant_candidates(role, biome, cells, valid_ids):
            evidence["decision"] = "skip_variant_no_candidates_for_pool_bucket"
            return None, evidence
        evidence.update({
            "decision": "use_pool_solid_square_bucket",
            "side": side,
            "minDx": origin[0],
            "minDy": origin[1],
            "footprintCells": cells,
        })
        return cells, evidence

    if role not in {"mountain", "tree"}:
        evidence["decision"] = "skip_variant_role_not_solid_square_sized"
        return None, evidence

    # Mountains/trees: never plant multi-tile solid-square variants. Big meshes
    # invent blocks on H3-open tiles adjacent to the OCC square.
    square = largest_homm3_block_solid_square(block_offsets, max_side=1)
    if square is None:
        evidence["decision"] = "skip_variant_empty_block_mask"
        return None, evidence
    evidence["largestSolidSquare"] = dict(square)
    footprint_cells = 1
    if scenery_variant_candidates(role, biome, footprint_cells, valid_ids):
        evidence.update({
            "decision": "use_1x1_solid_square_only_mountain_tree",
            "footprintCells": footprint_cells,
            "reason": "multi_tile_olden_scenery_meshes_overhang_h3_open_cells",
        })
        return footprint_cells, evidence
    evidence["decision"] = "skip_variant_no_candidates_for_1x1_mountain_tree"
    return None, evidence


def scenery_sid_solid_side(sid: str) -> int | None:
    """Return solid square side length for a known scenery variant SID, else None."""
    for (_role, _biome, cells), candidates in SCENERY_VARIANT_GROUPS.items():
        if sid in candidates:
            if cells == 1:
                return 1
            if cells == 4:
                return 2
            if cells == 9:
                return 3
            raise ValueError(f"unsupported scenery variant footprintCells={cells} for {sid}")
    return None


def ensure_mountain_tree_sid_fits_homm3_block_mask(
    replacement_sid: str,
    role: str,
    biome: str,
    block_offsets: set[tuple[int, int]],
    valid_ids: set[str],
    *,
    seed_key: str,
    node: int,
) -> str:
    """Force mountain/tree SIDs to 1x1 solid-square variants.

    Multi-tile Olden mountain/tree meshes overhang ObjectConfig OCC onto H3-open
    neighbors even when a solid 2x2/3x3 subset exists inside the H3 block mask.
    Residual H3 blocks are sealed by 1x1 gap-fill, not by planting ``*_big_*``.
    """
    if role not in {"mountain", "tree"}:
        return replacement_sid
    side = scenery_sid_solid_side(replacement_sid)
    if side is None or side == 1:
        return replacement_sid
    footprint_cells, evidence = scenery_footprint_cells_from_homm3_blocks(
        role, biome, block_offsets, valid_ids
    )
    if footprint_cells is None:
        raise ValueError(
            f"scenery SID {replacement_sid} is multi-tile mountain/tree and no 1x1 "
            f"variant exists (role={role} biome={biome} blocks={len(block_offsets)} "
            f"decision={evidence.get('decision')})"
        )
    variant = choose_scenery_variant(
        role,
        biome,
        footprint_cells,
        valid_ids,
        seed_key=seed_key,
        node=node,
    )
    if not variant:
        raise ValueError(
            f"scenery SID {replacement_sid} is multi-tile mountain/tree and "
            f"choose_scenery_variant returned no 1x1 sid "
            f"(role={role} biome={biome} blocks={len(block_offsets)})"
        )
    return variant


def ensure_rock_sid_fits_homm3_block_mask(
    replacement_sid: str,
    block_offsets: set[tuple[int, int]],
    valid_ids: set[str],
) -> str:
    """Force multi-tile rock meshes to rocks_1/rocks_2.

    ``dirt_rock_*`` / volcanic / snow rock hills are solid 2x2 meshes. Same-size
    clones that zero half the OCC still render the full mesh over H3-open cells
    (Hack and Slash scn1: 2-tile H3 rock → 4-tile OE dirt_rock look). Residual
    H3 blocks are sealed by gap-fill, matching mountain/tree policy.
    """
    if not isinstance(replacement_sid, str) or not replacement_sid:
        return replacement_sid
    lower = replacement_sid.lower()
    multi_tile_rock_mesh = (
        lower.startswith(("dirt_rock", "dirt_volcanic_rock", "snow_rock_hill"))
        or replacement_sid.startswith("homm3_xfp_")
    )
    if not multi_tile_rock_mesh:
        return replacement_sid
    for sid in ("rocks_1", "rocks_2"):
        if sid in valid_ids:
            return sid
    raise ValueError(
        f"rock role cannot plant multi-tile mesh {replacement_sid!r}: "
        f"rocks_1/rocks_2 missing from valid_ids (h3_blocks={len(block_offsets)})"
    )


def choose_scenery_variant(
    role: str | None,
    biome: str | None,
    footprint_cells: int,
    valid_ids: set[str],
    *,
    seed_key: str,
    node: int,
) -> str | None:
    if not role or not biome:
        return None
    candidates = scenery_variant_candidates(role, biome, footprint_cells, valid_ids)
    if not candidates:
        return None
    import hashlib

    digest = hashlib.sha256(f"scenery:{role}:{biome}:{footprint_cells}:{seed_key}:{node}".encode("utf-8")).hexdigest()
    return candidates[int(digest[:12], 16) % len(candidates)]


def choose_terrain_biome_replacement(
    role: str | None,
    valid_ids: set[str],
    terrain_context: dict[str, Any] | None,
    *,
    footprint_cells: int | None = None,
    seed_key: str | None = None,
    node: int | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    if role is None or terrain_context is None:
        return None, None, None
    biome = resolve_terrain_biome(terrain_context)
    if not isinstance(biome, str):
        # Border-overhang anchors sit outside the source tile grid; use grass as the
        # explicit scenery-family default rather than blocking substitution.
        if role in {"mountain", "rock", "tree", "shrub", "lake", "crater"}:
            biome = "grass"
            terrain_context = {
                **(terrain_context or {}),
                "biome": biome,
                "borderOverhangDefaultBiome": True,
            }
        else:
            return None, "terrain_biome_missing_source_tile_context", {
                "method": "source_tile_biome_role_mapping",
                "role": role,
                **(terrain_context or {}),
                "blockedReason": "no source terrain tile exists for this object anchor",
            }
    if role == "terrain_animation_classification_required":
        return None, "terrain_biome_template_155_requires_animation_role", {
            "method": "source_tile_biome_role_mapping",
            "role": role,
            **terrain_context,
            "blockedReason": "template 155 is terrain-like but this animation is not classified as rock, shrub, or tree",
        }
    if footprint_cells is not None and seed_key is not None and node is not None:
        variant = choose_scenery_variant(
            role,
            biome,
            footprint_cells,
            valid_ids,
            seed_key=seed_key,
            node=node,
        )
        if variant:
            return variant, f"terrain_biome_variant_{role}_{biome}_{footprint_cells}", {
                "method": "source_tile_biome_role_variant",
                "role": role,
                "biome": biome,
                "footprintCells": footprint_cells,
                "seedKey": seed_key,
                "node": node,
                **terrain_context,
            }
    replacement = (BIOME_ROLE_REPLACEMENTS.get(role) or {}).get(biome)
    if replacement is None:
        return None, f"terrain_biome_missing_role_mapping_{role}_{biome}", {
            "method": "source_tile_biome_role_mapping",
            "role": role,
            **terrain_context,
            "blockedReason": "no replacement is defined for this terrain role and source biome",
        }
    if replacement not in valid_ids:
        return None, f"terrain_biome_missing_valid_replacement_{role}_{biome}_{replacement}", {
            "method": "source_tile_biome_role_mapping",
            "role": role,
            **terrain_context,
            "candidateReplacementSid": replacement,
            "candidateWhitelisted": False,
        }
    return replacement, f"terrain_biome_{role}_{biome}", {
        "method": "source_tile_biome_role_mapping",
        "role": role,
        "biome": biome,
        **terrain_context,
        "candidateReplacementSid": replacement,
        "candidateWhitelisted": True,
    }


def choose_decoration(animation: str, valid_ids: set[str]) -> tuple[str | None, str | None]:
    lower = animation.lower()
    for rule_name, tokens, replacement in DECORATION_RULES:
        if replacement not in valid_ids:
            continue
        if any(token in lower for token in tokens):
            return replacement, rule_name
    return None, None



def choose_block(template_id: Any) -> tuple[None, str | None, str | None]:
    return None, None, None


def choose_clearing(template_id: Any, animation: str, category: str | None, payload: Any, valid_ids: set[str]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    if int(template_id or 0) != 14:
        return None, None, None, None
    replacement = "knowledge_garden"
    if replacement not in valid_ids:
        return None, "clearing_to_knowledge_garden_missing_valid_target", "blocked", {
            "method": "clearing_garden_family",
            "templateAnimation": animation,
            "blockedReason": "knowledge_garden is missing from the valid entity catalog",
        }
    return replacement, "clearing_to_knowledge_garden", "role_and_visual", {
        "method": "clearing_garden_family",
        "templateAnimation": animation,
        "replacementSid": replacement,
    }


def choose_flotsam(template_id: Any, valid_ids: set[str]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    if int(template_id or 0) != h3obj.OBJECT_FLOTSAM:
        return None, None, None, None
    replacement = "homm3_flotsam_pickup"
    if replacement not in valid_ids:
        return None, "flotsam_pickup_sid_not_in_valid_catalog", "blocked", {
            "method": "flotsam_one_shot_water_reward",
            "blockedReason": "homm3_flotsam_pickup must be injected into valid_ids before substitution",
            "templateObjectId": template_id,
        }
    return replacement, "flotsam_to_one_shot_pickup", "role", {
        "method": "flotsam_one_shot_water_reward",
        "templateObjectId": template_id,
    }


# Pathable 1-cell env decorations (no occupied ObjectConfig nodes). Used when HoMM3
# signs/signposts have no readable-text Olden analogue.
PATHABLE_SCENERY_SIDS_BY_BIOME: dict[str, tuple[str, ...]] = {
    "grass": (
        "flowers_1", "flowers_2", "grass_1", "grass_2",
        "grass_stones_1", "grass_stones_2",
        "mushrooms_1", "mushrooms_2", "mushrooms_3", "mushrooms_4",
    ),
    "dirt": ("flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"),
    "desert": ("flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"),
    "snow": ("grass_snow_1", "grass_snow_2", "snow_stones_1", "snow_stones_2", "snow_stones_3", "snow_stones_4"),
    "dead": ("flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"),
    "lava": ("flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"),
    "water": ("flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"),
}
# HoMM3 object 99 is the Trading Post (221 its HotA snow variant), not a signpost: it used to be
# listed here, which turned every trading post into walkable flowers/grass. Trading posts map to the
# native market in DIRECT_BLOCKED_TEMPLATE_MAP (docs/homm3_map_object_animation_audit.md, Not presented).
SIGN_OR_SIGNPOST_TEMPLATE_IDS = frozenset({h3obj.OBJECT_SIGN})


def is_sign_or_signpost_row(row: dict[str, Any]) -> bool:
    if row.get("category") == "readable_sign_or_bottle":
        return True
    return int(row.get("templateObjectId") or 0) in SIGN_OR_SIGNPOST_TEMPLATE_IDS


def choose_sign_pathable_scenery(
    row: dict[str, Any],
    valid_ids: set[str],
    terrain_context: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    """Replace unreadably-lossy sign FX with biome pathable scenery."""
    import hashlib

    biome = resolve_terrain_biome(terrain_context) if terrain_context else None
    if not isinstance(biome, str):
        biome = "grass"
    pool = [sid for sid in PATHABLE_SCENERY_SIDS_BY_BIOME.get(biome, PATHABLE_SCENERY_SIDS_BY_BIOME["grass"]) if sid in valid_ids]
    if not pool:
        pool = [sid for sid in PATHABLE_SCENERY_SIDS_BY_BIOME["grass"] if sid in valid_ids]
    if not pool:
        return None, "sign_pathable_scenery_missing_valid_targets", "blocked", {
            "method": "sign_to_pathable_scenery",
            "blockedReason": "no pathable scenery SIDs remain in the valid entity catalog",
            "biome": biome,
            "templateObjectId": row.get("templateObjectId"),
        }
    seed = str(row.get("sourceKey") or row.get("sourceIndex") or row.get("templateAnimation") or "sign")
    digest = hashlib.sha256(f"sign-pathable-scenery:{biome}:{seed}".encode("utf-8")).hexdigest()
    replacement = pool[int(digest[:12], 16) % len(pool)]
    template_id = int(row.get("templateObjectId") or 0)
    rule_name = (
        "readable_sign_to_pathable_scenery"
        if template_id == h3obj.OBJECT_SIGN or row.get("category") == "readable_sign_or_bottle"
        else "signpost_to_pathable_scenery"
    )
    return replacement, rule_name, "visual_context_only", {
        "method": "sign_to_pathable_scenery",
        "biome": biome,
        "pool": list(pool),
        "seedKey": seed,
        "templateObjectId": template_id,
        "templateAnimation": row.get("templateAnimation"),
        "replacementSid": replacement,
        "ruleName": rule_name,
    }


def choose_direct_blocked_template(template_id: Any, valid_ids: set[str]) -> tuple[str | None, str | None, str | None]:
    mapping = DIRECT_BLOCKED_TEMPLATE_MAP.get(int(template_id)) if isinstance(template_id, int) else None
    if mapping is None:
        return None, None, None
    replacement, rule_name = mapping
    if replacement not in valid_ids:
        return None, f"{rule_name}_missing_valid_target", "blocked"
    return replacement, rule_name, "role_and_visual"


def choose_monolith_two_way(animation: str, valid_ids: set[str]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    mapping = MONOLITH_TWO_WAY_ANIMATION_EXACT_MAP.get(animation)
    if mapping is None:
        return None, "monolith_two_way_requires_exact_animation", "blocked", {
            "method": "monolith_two_way_exact_animation",
            "blockedReason": "two-way monolith animation has no portal SID mapping",
            "templateAnimation": animation,
        }
    replacement, rule_name = mapping
    if replacement not in valid_ids:
        return None, f"{rule_name}_missing_valid_target", "blocked", {
            "method": "monolith_two_way_exact_animation",
            "blockedReason": "mapped portal SID is missing from the valid entity catalog",
            "templateAnimation": animation,
            "replacementSid": replacement,
        }
    return replacement, rule_name, "role_and_visual", {
        "method": "monolith_two_way_exact_animation",
        "templateAnimation": animation,
        "replacementSid": replacement,
        "ruleName": rule_name,
    }


def choose_shrine_by_template(template_id: Any, valid_ids: set[str]) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    mapping = SHRINE_TEMPLATE_SID_MAP.get(int(template_id)) if isinstance(template_id, int) else None
    if mapping is None:
        return None, "shrine_requires_level_mapping", "blocked", {
            "method": "shrine_template_level_mapping",
            "blockedReason": "HoMM3 shrine template id has no scroll_box level mapping",
            "templateObjectId": template_id,
        }
    replacement, rule_name = mapping
    if replacement not in valid_ids:
        return None, f"{rule_name}_missing_valid_target", "blocked", {
            "method": "shrine_template_level_mapping",
            "blockedReason": "mapped scroll_box SID is missing from the valid entity catalog",
            "templateObjectId": template_id,
            "replacementSid": replacement,
        }
    return replacement, rule_name, "role", {
        "method": "shrine_template_level_mapping",
        "templateObjectId": template_id,
        "replacementSid": replacement,
        "ruleName": rule_name,
    }


def lossiness_for(rule_name: str | None, confidence: str | None) -> str:
    if confidence == "blocked":
        return "blocked"
    if rule_name in LOSSY_PLACEHOLDER_RULES:
        return "lossy_placeholder"
    return "direct_or_family_substitution"


def choose_by_exact_animation(animation: str, table: dict[str, str], valid_ids: set[str]) -> tuple[str | None, str | None]:
    replacement = table.get(animation)
    if replacement and replacement in valid_ids:
        return replacement, f"exact_animation_{animation}"
    return None, None


def choose_biome_decoration(template_id: Any, animation: str, valid_ids: set[str]) -> tuple[str | None, str | None]:
    lower = animation.lower()
    candidates: list[tuple[str, str]] = []
    if template_id == 118 and "lk" in lower:
        candidates.append(("pool_lava_big_1", "biome_lava_pool"))
    elif template_id == 119:
        # Dead/snow-dead vegetation is encoded in the DEF, not the anchor tile biome.
        if any(token in lower for token in ("ddsn", "dead", "d6sn", "d9sn", "d3sn", "dd")):
            if "tree_dead_1" in valid_ids:
                candidates.append(("tree_dead_1", "biome_dead_tree"))
            elif "tree_dead_2" in valid_ids:
                candidates.append(("tree_dead_2", "biome_dead_tree"))
        elif "swp" in lower:
            candidates.append(("pool_dead_small_1", "biome_dead_swamp_pool"))
    elif template_id in {129, 134}:
        if "mtsn" in lower or "mtsb" in lower or "avlms" in lower:
            candidates.append(("mountain_snow_small_1", "biome_snow_mountain"))
        elif "mtdr" in lower:
            candidates.append(("mountain_dirt_small_1", "biome_dirt_mountain"))
        elif "mtgr" in lower or "mtgn" in lower or "mtg" in lower:
            candidates.append(("mountain_green_small_1", "biome_green_mountain"))
    elif template_id == 131:
        if "mtdr" in lower:
            candidates.append(("mountain_dirt_small_1", "biome_dirt_mountain"))
        elif "mtgr" in lower or "mtgn" in lower:
            candidates.append(("mountain_green_small_1", "biome_green_mountain"))
    elif template_id == 133:
        if "mtgr" in lower or "mtgn" in lower or "mtg" in lower:
            candidates.append(("mountain_green_small_1", "biome_green_mountain"))
    elif template_id == 135:
        if "autr" in lower:
            candidates.append(("tree_autumn_1", "biome_autumn_tree"))
        elif "sptr" in lower:
            candidates.append(("pinetree_snow_1", "biome_snow_pine"))
    elif template_id == 137:
        if "sntr" in lower:
            candidates.append(("pinetree_snow_1", "biome_snow_tree"))
        elif "pntr" in lower:
            candidates.append(("pinetree_1", "biome_pine_tree"))
    elif template_id == 147:
        if "sn" in lower or lower.endswith("s0.def"):
            candidates.append(("snow_stones_1", "biome_snow_rock"))
        elif "w0" in lower:
            candidates.append(("water_reed_1", "biome_water_rock"))
        else:
            candidates.append(("dirt_rock_1", "biome_dirt_rock"))
    elif template_id == 150:
        if "sn" in lower:
            candidates.append(("grass_snow_1", "biome_snow_shrub"))
        elif lower.endswith("d0.def"):
            candidates.append(("grass_desert_1", "biome_desert_shrub"))
        elif lower.endswith("g0.def"):
            candidates.append(("grass_1", "biome_grass_shrub"))
    elif template_id == 155:
        if "r04" in lower:
            candidates.append(("dirt_rock_1", "biome_rock_not_tree"))
        elif "yuc" in lower:
            candidates.append(("grass_desert_1", "biome_desert_yucca"))
        elif "tr" in lower:
            candidates.append(("tree_dirt_1", "biome_dirt_tree"))
    elif template_id == 136 and "sn" in lower:
        candidates.append(("pool_snow_small_1", "biome_snow_pool"))
    elif template_id == 125 and "klp" in lower:
        candidates.append(("water_reed_1", "biome_water_kelp"))
    # Animation-token fallbacks for any template (DEF family beats silent miss).
    if not candidates:
        if any(token in lower for token in ("mtsn", "mtsb", "avlms")):
            candidates.append(("mountain_snow_small_1", "anim_snow_mountain"))
        elif any(token in lower for token in ("ddsn", "dead")):
            candidates.append(("tree_dead_1", "anim_dead_tree"))
        elif any(token in lower for token in ("sntr", "sptr")):
            candidates.append(("pinetree_snow_1", "anim_snow_tree"))
        elif "mtdr" in lower:
            candidates.append(("mountain_dirt_small_1", "anim_dirt_mountain"))
        elif any(token in lower for token in ("mtgr", "mtgn")):
            candidates.append(("mountain_green_small_1", "anim_green_mountain"))
    for replacement, rule in candidates:
        if replacement in valid_ids:
            return replacement, rule
    return None, None


def scenery_biome_from_sid(sid: str | None) -> str | None:
    if not isinstance(sid, str) or not sid:
        return None
    lower = sid.lower()
    mapping = (
        ("mountain_snow", "snow"),
        ("mountain_dead", "dead"),
        ("mountain_dirt", "dirt"),
        ("mountain_desert", "desert"),
        ("mountain_lava", "lava"),
        ("mountain_water", "water"),
        ("mountain_green", "grass"),
        ("pinetree_snow", "snow"),
        ("tree_dead", "dead"),
        ("tree_dirt", "dirt"),
        ("tree_lava", "lava"),
        ("tree_autumn", "grass"),
        ("pinetree", "grass"),
        ("pool_snow", "snow"),
        ("pool_dead", "dead"),
        ("pool_dirt", "dirt"),
        ("pool_desert", "desert"),
        ("pool_lava", "lava"),
        ("pool", "grass"),
        ("grass_death", "dead"),
    )
    for prefix, biome in mapping:
        if lower.startswith(prefix):
            return biome
    return None


def scenery_family_prefix(sid: str | None) -> str | None:
    """Coarse family used to keep catalog remaps inside the same blocking scenery line."""
    if not isinstance(sid, str) or not sid:
        return None
    lower = sid.lower()
    for prefix in (
        "mountain_snow",
        "mountain_dead",
        "mountain_dirt",
        "mountain_desert",
        "mountain_lava",
        "mountain_water",
        "mountain_green",
        "pinetree_snow",
        "tree_dead",
        "tree_dirt",
        "tree_lava",
        "tree_autumn",
        "pinetree",
        "pool_snow",
        "pool_dead",
        "pool_dirt",
        "pool_desert",
        "pool_lava",
        "pool",
    ):
        if lower.startswith(prefix):
            return prefix
    return lower.split("_", 1)[0] if "_" in lower else lower


def gap_fill_blocker_sid_for_animation(animation: str | None, valid_ids: set[str]) -> str | None:
    """1x1 blocking scenery for residual H3 block cells, keyed by source DEF family."""
    lower = str(animation or "").lower()
    ordered: list[str] = []
    if any(token in lower for token in ("mtsn", "mtsb", "avlms")):
        ordered.extend(["mountain_snow_small_1", "mountain_snow_small_2"])
    elif any(token in lower for token in ("ddsn", "dead")):
        ordered.extend(["tree_dead_1", "tree_dead_2", "mountain_dead_small_1"])
    elif any(token in lower for token in ("sntr", "sptr")):
        ordered.extend(["pinetree_snow_1", "mountain_snow_small_1"])
    elif "mtdr" in lower:
        ordered.extend(["mountain_dirt_small_1", "mountain_dirt_small_2"])
    elif any(token in lower for token in ("mtgr", "mtgn", "mtg")):
        ordered.extend(["mountain_green_small_1", "mountain_green_small_2"])
    elif any(token in lower for token in ("pntr", "autr", "tree")):
        ordered.extend(["pinetree_1", "tree_dirt_1", "mountain_green_small_1"])
    for sid in ordered:
        if sid in valid_ids:
            return sid
    return None


def choose_localized_interactive_equivalent(payload: Any, semantic_mapper: MiniLmBuildingMapper) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    template_id = PAYLOAD_BUILDING_TEMPLATE_IDS.get(str(payload))
    if template_id is None:
        return None, None, None, None
    return semantic_mapper.choose(template_id)


def choose_replacement(row: dict[str, Any], valid_ids: set[str], semantic_mapper: MiniLmBuildingMapper, artifact_mapper: ArtifactEffectMapper, terrain_context: dict[str, Any] | None = None) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    sid = row.get("sid")
    category = row.get("category")
    payload = row.get("payloadKind")
    animation = str(row.get("templateAnimation") or "")
    template_id = row.get("templateObjectId")

    blocked_animation_rule = BLOCKED_ANIMATION_RULES.get(animation)
    if blocked_animation_rule is not None:
        return None, blocked_animation_rule, "blocked", None

    if payload == "spell_scroll" or int(template_id or 0) == h3obj.OBJECT_SPELL_SCROLL:
        # Adventure spell scrolls are not H3 artifact subtypes; map to the catalog scroll object.
        replacement = choose_existing("homm3_artifact_001_spell_scroll", valid_ids) or choose_existing(
            "scroll_box", valid_ids
        )
        if replacement is None:
            return None, "spell_scroll_missing_valid_target", "blocked", {
                "method": "spell_scroll_exact_catalog",
                "blockedReason": "homm3_artifact_001_spell_scroll/scroll_box missing from valid entity catalog",
                "templateAnimation": animation,
            }
        return replacement, "spell_scroll_to_homm3_catalog_scroll", "role", {
            "method": "spell_scroll_exact_catalog",
            "templateAnimation": animation,
            "replacementSid": replacement,
        }

    if (
        int(template_id or 0) == h3obj.OBJECT_PANDORAS_BOX
        or payload in {"pandoras_box", "pandora"}
        or animation.upper().startswith("AVA0128")
    ):
        replacement = choose_existing("pandora_box", valid_ids)
        if replacement is None:
            return None, "pandoras_box_missing_valid_target", "blocked", {
                "method": "pandoras_box_exact_sid",
                "blockedReason": "pandora_box missing from valid entity catalog",
                "templateAnimation": animation,
            }
        return replacement, "pandoras_box_to_pandora_box", "role", {
            "method": "pandoras_box_exact_sid",
            "templateAnimation": animation,
            "replacementSid": replacement,
        }

    if int(template_id or 0) == h3obj.OBJECT_SHIPYARD or payload == "shipyard" or animation.upper().startswith(
        "AVXSHYD"
    ):
        # No dedicated shipyard ObjectConfig; water-travel family uses installed boat SID.
        replacement = choose_existing("homm3_boat", valid_ids)
        if replacement is None:
            return None, "shipyard_missing_valid_target", "blocked", {
                "method": "shipyard_water_travel_family",
                "blockedReason": "homm3_boat missing from valid entity catalog",
                "templateAnimation": animation,
            }
        return replacement, "shipyard_to_homm3_boat_water_travel_family", "role", {
            "method": "shipyard_water_travel_family",
            "templateAnimation": animation,
            "replacementSid": replacement,
        }

    if (
        int(template_id or 0) == h3obj.OBJECT_GRAIL
        or payload == "grail"
        or animation.upper().startswith("AVZGRAIL")
    ):
        # Geometry/interact marker only; victory-condition wiring stays QuestScript-owned.
        replacement = choose_existing("fx_quest_mark_gold_01", valid_ids) or choose_existing(
            "homm3_landon_map_event_marker", valid_ids
        )
        if replacement is None:
            return None, "grail_missing_valid_marker_target", "blocked", {
                "method": "grail_to_quest_mark_marker",
                "blockedReason": "fx_quest_mark_gold_01 / map_event_marker missing from valid entity catalog",
                "templateAnimation": animation,
            }
        return replacement, "grail_to_quest_mark_marker", "role", {
            "method": "grail_to_quest_mark_marker",
            "templateAnimation": animation,
            "replacementSid": replacement,
            "note": "placement marker only; grail victory remains QuestScript/win-condition owned",
        }

    if int(template_id or 0) == h3obj.OBJECT_ABANDONED_MINE or payload == "abandoned_mine":
        # HoMM3 Abandoned Mine becomes a resource mine after capture; OE has no
        # abandoned-mine SID, so emit mine_gold (not abandoned_outpost→town).
        replacement = choose_existing("mine_gold", valid_ids)
        if replacement is None:
            return None, "abandoned_mine_missing_valid_target", "blocked", {
                "method": "abandoned_mine_to_mine_gold",
                "blockedReason": "mine_gold missing from valid entity catalog",
                "templateAnimation": animation,
            }
        return replacement, "abandoned_mine_to_mine_gold", "role", {
            "method": "abandoned_mine_to_mine_gold",
            "templateAnimation": animation,
            "replacementSid": replacement,
        }

    if category == "artifact_pickup" or payload == "artifact":
        return artifact_mapper.choose(row)

    if payload == "random_dwelling" or str(animation or "").lower().startswith("avrcg"):
        # HotA/SoD random dwelling hosts (avrcgen*/avrcgn*). Until faction/level
        # decoding is wired into emit, place a Castle land-on barracks at the
        # declared level subtype (fail-closed if subtype missing/out of range).
        subtype = row.get("templateSubtype")
        if not isinstance(subtype, int) or subtype < 1 or subtype > 7:
            return None, "random_dwelling_requires_level_subtype_1_to_7", "blocked", {
                "method": "random_dwelling_castle_tier_from_subtype",
                "blockedReason": f"templateSubtype must be dwelling level 1..7; got {subtype!r}",
                "templateObjectId": template_id,
                "templateAnimation": animation,
                "templateSubtype": subtype,
            }
        replacement = landon_barracks_clone_sid("castle", subtype)
        evidence = {
            "method": "random_dwelling_castle_tier_from_subtype",
            "templateObjectId": template_id,
            "templateAnimation": animation,
            "templateSubtype": subtype,
            "replacementSid": replacement,
            "ruleName": "random_dwelling_to_castle_landon_barracks_by_level",
        }
        if replacement not in valid_ids:
            evidence["blockedReason"] = "castle land-on barracks SID missing from valid entity catalog"
            return None, "random_dwelling_castle_barracks_missing_valid_target", "blocked", evidence
        return replacement, "random_dwelling_to_castle_landon_barracks_by_level", "role", evidence

    if category == "external_dwelling" or payload == "creature_generator":
        replacement_rule = lookup_creature_generator_replacement(animation)
        evidence = {
            "method": "creature_generator_exact_animation",
            "templateObjectId": template_id,
            "templateAnimation": animation,
            "category": category,
            "payloadKind": payload,
            "generatorFamily": row.get("generatorFamily"),
            "owner": row.get("owner"),
            "ownerEncoding": row.get("ownerEncoding"),
            "payloadDecoderEvidence": row.get("payloadDecoderEvidence"),
        }
        if replacement_rule is None:
            evidence["blockedReason"] = "HoMM3 creature generator has no exact native dwelling policy"
            return None, "creature_generator_requires_exact_dwelling_policy", "blocked", evidence
        replacement, rule_name = replacement_rule
        evidence.update({"replacementSid": replacement, "ruleName": rule_name})
        if replacement not in valid_ids:
            evidence["blockedReason"] = "exact native HoMM3 barracks SID is missing from the valid entity catalog"
            return None, f"{rule_name}_missing_valid_target", "blocked", evidence
        return replacement, rule_name, "role_and_visual", evidence

    blocked_replacement, blocked_rule, blocked_confidence = choose_block(template_id)
    if blocked_rule is not None:
        return blocked_replacement, blocked_rule, blocked_confidence, None

    flotsam_replacement, flotsam_rule, flotsam_confidence, flotsam_evidence = choose_flotsam(template_id, valid_ids)
    if flotsam_rule is not None:
        return flotsam_replacement, flotsam_rule, flotsam_confidence, flotsam_evidence

    if is_sign_or_signpost_row(row):
        return choose_sign_pathable_scenery(row, valid_ids, terrain_context)

    clearing_replacement, clearing_rule, clearing_confidence, clearing_evidence = choose_clearing(
        template_id,
        animation,
        category,
        payload,
        valid_ids,
    )
    if clearing_rule is not None:
        return clearing_replacement, clearing_rule, clearing_confidence, clearing_evidence

    if int(template_id or 0) == h3obj.OBJECT_TWO_WAY_MONOLITH:
        monolith_replacement, monolith_rule, monolith_confidence, monolith_evidence = choose_monolith_two_way(animation, valid_ids)
        if monolith_rule is not None:
            return monolith_replacement, monolith_rule, monolith_confidence, monolith_evidence

    shrine_replacement, shrine_rule, shrine_confidence, shrine_evidence = choose_shrine_by_template(template_id, valid_ids)
    if int(template_id or 0) in SHRINE_TEMPLATE_SID_MAP:
        return shrine_replacement, shrine_rule, shrine_confidence, shrine_evidence

    bank_anim = CREATURE_BANK_ANIMATION_EXACT_MAP.get(animation) or CREATURE_BANK_ANIMATION_EXACT_MAP.get(
        animation.lower()
    )
    if bank_anim is not None:
        bank_sid, bank_rule = bank_anim
        if bank_sid in valid_ids:
            return bank_sid, bank_rule, "role_and_visual", {
                "method": "creature_bank_animation_exact",
                "templateObjectId": template_id,
                "templateAnimation": animation,
                "replacementSid": bank_sid,
                "ruleName": bank_rule,
            }
        return None, f"{bank_rule}_missing_valid_target", "blocked", {
            "method": "creature_bank_animation_exact",
            "blockedReason": f"{bank_sid} missing from valid entity catalog",
            "templateAnimation": animation,
        }

    direct_replacement, direct_rule, direct_confidence = choose_direct_blocked_template(template_id, valid_ids)
    if direct_rule is not None:
        return direct_replacement, direct_rule, direct_confidence, {
            "method": "direct_blocked_template_map",
            "templateObjectId": template_id,
            "replacementSid": direct_replacement,
            "ruleName": direct_rule,
        }

    if sid in valid_ids:
        return sid, "already_valid", "exact", None

    if category == "town":
        lower = animation.lower()
        # Land-on GATE clones where the raw/Homecoming pipeline already ships them.
        # AB/SoD Dungeon variant AVCdunx* has no contiguous "dung" token.
        if "dung" in lower or "dunx" in lower or "cdun" in lower:
            return choose_existing("homm3_landon_dungeon_city", valid_ids), "town_animation_dungeon", "role_and_visual", None
        # RoE uses AVCcast*; SoD often emits AVCcasx* for the same Castle faction.
        if "cast" in lower or "casx" in lower:
            return choose_existing("homm3_landon_castle_city", valid_ids), "town_animation_castle", "role_and_visual", None
        # Remaining RoE factions: native faction city SIDs (no land-on GATE clone yet).
        # Prefer playable towns over omitting AI capitals (Deal/Neutral would otherwise
        # emit hero-only AI sides and fail StoryHub Bot binding).
        faction_town_sids = (
            ("inft", "homm3_inferno_city", "town_animation_inferno"),
            # SoD Inferno variant stem.
            ("infx", "homm3_inferno_city", "town_animation_inferno"),
            ("ramp", "homm3_rampart_city", "town_animation_rampart"),
            # SoD Rampart variant (AVCramx*) — "ramp" token is absent (no trailing p).
            ("ramx", "homm3_rampart_city", "town_animation_rampart"),
            ("towr", "homm3_tower_city", "town_animation_tower"),
            ("towx", "homm3_tower_city", "town_animation_tower"),
            ("fort", "homm3_fortress_city", "town_animation_fortress"),
            ("ftrt", "homm3_fortress_city", "town_animation_fortress"),
            ("ftrx", "homm3_fortress_city", "town_animation_fortress"),
            # AB/SoD Fortress variant stem (AVChforx*) — no contiguous "fort" token.
            ("hfor", "homm3_fortress_city", "town_animation_fortress"),
            ("forx", "homm3_fortress_city", "town_animation_fortress"),
            ("stro", "homm3_stronghold_city", "town_animation_stronghold"),
            ("strx", "homm3_stronghold_city", "town_animation_stronghold"),
            ("necr", "homm3_necropolis_city", "town_animation_necropolis"),
            # SoD Necropolis variant (AVCnecx*) — must not require the RoE "necr" token.
            ("necx", "homm3_necropolis_city", "town_animation_necropolis"),
            ("elem", "homm3_conflux_city", "town_animation_conflux"),
            ("elex", "homm3_conflux_city", "town_animation_conflux"),
        )
        for token, sid, rule in faction_town_sids:
            if token in lower:
                return choose_existing(sid, valid_ids), rule, "role_and_visual", None
        return None, "town_requires_faction_animation_contract", "blocked", {
            "method": "town_faction_animation",
            "blockedReason": "town animation does not encode a known faction",
            "templateAnimation": animation,
        }

    if category == "map_event" or payload in {"map_event", "event"}:
        # Decoder may emit payloadKind "event" while category remains map_event.
        return (
            choose_existing("homm3_landon_map_event_marker", valid_ids),
            "event_map_marker_direct_exact_homm3_footprint_keep_donor",
            "role",
            None,
        )

    if category == "resource_pickup" or payload == "resource":
        if int(template_id or 0) == h3obj.OBJECT_RANDOM_RESOURCE:
            # HoMM3 random resource is a spawn randomizer (like random squads), not a
            # mystery one-shot pickup. Native Olden analogue is meta random-res.
            replacement = "resource_gold"
            if replacement not in valid_ids:
                return None, "concrete_resource_sid_not_in_valid_catalog", "blocked", {
                    "method": "random_resource_concrete_emit",
                    "blockedReason": "resource_gold missing from Core catalog",
                    "templateObjectId": template_id,
                }
            # Meta random-res resolves resources.json ∪ resources_camps.json and has
            # caused Loader MapObjects.opn(null) retry hangs on Steadwick-scale maps.
            # HoMM3 random resource is a one-shot pile; emit a concrete resource_*.
            return replacement, "random_resource_to_concrete_resource_gold", "role", {
                "method": "random_resource_concrete_emit",
                "templateObjectId": template_id,
                "amount": row.get("amount"),
                "note": "emit/install may diversify across resource_* by object id",
            }
        replacement, rule = choose_by_animation(animation, RESOURCE_ANIMATION_MAP, valid_ids)
        if replacement:
            return replacement, f"resource_{rule}", "role_and_visual", None
        return None, "resource_requires_exact_resource_animation", "blocked", {
            "method": "resource_animation",
            "blockedReason": "fixed resource animation has no resource SID mapping",
            "templateAnimation": animation,
        }

    if category == "mine" or payload == "mine":
        replacement, rule = choose_by_exact_animation(animation, MINE_ANIMATION_EXACT_MAP, valid_ids)
        if replacement:
            return replacement, f"mine_{rule}", "role_and_visual", None
        replacement, rule = choose_by_animation(animation, MINE_ANIMATION_MAP, valid_ids)
        if replacement:
            return replacement, f"mine_{rule}", "role_and_visual", None
        return None, "mine_requires_exact_mine_animation", "blocked", {
            "method": "mine_animation",
            "blockedReason": "mine animation has no exact mine SID mapping",
            "templateAnimation": animation,
        }

    if category == "monster_stack" or payload == "monster":
        if int(template_id or 0) == h3obj.OBJECT_MONSTER:
            return choose_existing("random-squad", valid_ids), "monster_concrete_to_random_squad", "role", None
        return choose_existing("random-squad", valid_ids), "monster_random_level_to_random_squad", "role", None

    if category == "interactive_reward_object":
        replacement, rule_name, confidence, evidence = choose_localized_interactive_equivalent(payload, semantic_mapper)
        if replacement:
            return replacement, rule_name, confidence, evidence
        if payload == "shrine":
            return choose_shrine_by_template(template_id, valid_ids)
        if payload == "scholar":
            return choose_existing("wise_owl", valid_ids), "scholar_to_wise_owl", "role", None

    if category == "garrison" or payload == "garrison":
        # HoMM3 garrisons are roadblock armies; Olden uses mixed-unit random-squad hosts.
        # Empty garrisons still occupy the map as visitables — emit random-squad with
        # empty army (no invented stacks) rather than omitting the roadblock.
        stacks = row.get("garrisonStacks")
        if not isinstance(stacks, list):
            stacks = []
        nonempty = [
            stack
            for stack in stacks
            if isinstance(stack, dict)
            and isinstance(stack.get("creatureType"), int)
            and isinstance(stack.get("count"), int)
            and int(stack["count"]) > 0
            and int(stack["creatureType"]) not in {0xFF, 0xFFFF}
        ]
        evidence = {
            "method": "garrison_exact_army_to_random_squad",
            "templateObjectId": template_id,
            "templateAnimation": animation,
            "stackCount": len(nonempty),
        }
        replacement = choose_existing("random-squad", valid_ids)
        if replacement is None:
            evidence["blockedReason"] = "random-squad SID missing from valid entity catalog"
            return None, "garrison_to_exact_neutral_stack_missing_valid_target", "blocked", evidence
        if not nonempty:
            evidence["emptyArmy"] = True
            return replacement, "garrison_empty_army_to_random_squad", "role", evidence
        return replacement, "garrison_to_exact_neutral_stack", "role", evidence

    if category == "interactive_quest_object":
        if payload == "seer_hut" or template_id == 83:
            replacement = choose_existing("homm3_seer_hut", valid_ids)
            if replacement is None:
                return None, "seer_hut_missing_homm3_seer_hut", "role", {
                    "blockedReason": "homm3_seer_hut missing from valid entity catalog",
                }
            return replacement, "seer_hut_to_homm3_seer_hut", "role_and_visual", None
        return choose_existing("fx_quest_mark_gold_01", valid_ids), f"quest_object_{payload or 'marker'}", "role", None

    if template_id in HOMM3_SOURCE_BUILDING_DESCRIPTIONS:
        return semantic_mapper.choose(template_id)

    if category == "travel_link_candidate":
        lower = animation.lower()
        if "cave" in lower:
            return choose_existing("portal_1", valid_ids), "cave_to_portal", "role", None
        if "whrl" in lower:
            return choose_existing("portal_magic", valid_ids), "whirlpool_to_magic_portal", "role", None

    if category == "hero_or_prison":
        if "prsn" in animation.lower():
            return choose_existing("prison", valid_ids), "prison_visual", "role_and_visual", None
        hero_type = row.get("heroType")
        owner = row.get("owner")
        if hero_type == 6 and owner == 0:
            return choose_existing("hero-spawner", valid_ids), "start_hero_to_hero_spawner", "role", None
        return choose_existing("hero-spawner", valid_ids), "placed_hero_to_hero_spawner", "role", None

    if category == "boat_or_water_travel_object":
        return choose_existing("homm3_boat", valid_ids), "boat_to_homm3_boat", "role_and_visual", None

    replacement, rule, evidence = choose_terrain_biome_replacement(terrain_role_for_row(row), valid_ids, terrain_context)
    if replacement:
        return replacement, rule, "source_tile_biome", evidence
    if rule:
        return None, rule, "blocked", evidence

    replacement, rule = choose_biome_decoration(template_id, animation, valid_ids)
    if replacement:
        return replacement, rule, "visual_family", None

    if template_id in EXACT_TEMPLATE_RULES and template_id not in TERRAIN_OBJECT_ROLES:
        replacement, rule = EXACT_TEMPLATE_RULES[template_id]
        if replacement in valid_ids:
            return replacement, rule, "template_family", None

    if category == "payloadless_object_unclassified_for_current_scope" and payload == "explicit_no_payload":
        overlay = choose_hota_magic_terrain_overlay(row, valid_ids)
        if overlay[1] is not None:
            return overlay
        replacement, rule = choose_decoration(animation, valid_ids)
        if replacement:
            return replacement, rule, "visual_family", None
        replacement, rule = choose_biome_decoration(template_id, animation, valid_ids)
        if replacement:
            return replacement, rule, "visual_family", None
        role = terrain_role_for_row(row)
        if role is not None:
            replacement, rule, evidence = choose_terrain_biome_replacement(role, valid_ids, terrain_context or {"biome": "grass"})
            if replacement:
                return replacement, rule, "source_tile_biome", evidence
        return None, "payloadless_scenery_requires_explicit_mapping", "blocked", None

    return None, "unclassified_object_requires_explicit_mapping", "blocked", None


def valid_entity_ids(core_catalog: dict[str, Any]) -> set[str]:
    """Core map-object ids plus the custom HoMM3 SIDs the overlays add (the substitution whitelist).

    Single source for the generator and tools/validate_homecoming_entity_substitution_map_contract.py.
    """
    valid_ids = {
        row["id"]
        for row in core_catalog.get("mapObjects", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    valid_ids.add("homm3_subterranean_gate_portal")
    valid_ids.update(CUSTOM_VALID_ENTITY_IDS)
    return valid_ids


def main() -> int:
    global _CACHED_SEMANTIC_MAPPER, _CACHED_ARTIFACT_MAPPER
    alignment = read_json(ALIGNMENT_PATH)
    core_catalog = read_json(CORE_CATALOG_PATH)
    valid_ids = valid_entity_ids(core_catalog)
    if _CACHED_SEMANTIC_MAPPER is None:
        english_tokens = load_english_text_tokens(core_catalog)
        _CACHED_SEMANTIC_MAPPER = MiniLmBuildingMapper(load_minilm_model(), valid_ids, core_catalog, english_tokens)
    else:
        cached_core = _CACHED_SEMANTIC_MAPPER.core_catalog.get("sourceCoreZip")
        live_core = core_catalog.get("sourceCoreZip")
        if cached_core != live_core:
            raise RuntimeError(
                f"cached MiniLmBuildingMapper sourceCoreZip drift: {cached_core!r} != {live_core!r}"
            )
    semantic_mapper = _CACHED_SEMANTIC_MAPPER
    if _CACHED_ARTIFACT_MAPPER is None:
        _CACHED_ARTIFACT_MAPPER = ArtifactEffectMapper(valid_ids, core_catalog)
    else:
        if _CACHED_ARTIFACT_MAPPER.source_core != core_catalog.get("sourceCoreZip"):
            raise RuntimeError(
                "cached ArtifactEffectMapper sourceCoreZip drift vs live catalog"
            )
    artifact_mapper = _CACHED_ARTIFACT_MAPPER
    entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    layer_tiles = load_layer_tiles(alignment)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        groups[signature_for(entity)].append(entity)

    invalid_entries = []
    unresolved = []
    for signature, rows in sorted(groups.items()):
        sample = rows[0]
        source_sid = sample.get("sid")
        if source_sid in valid_ids:
            continue
        placement_overrides: list[dict[str, Any]] = []
        terrain_roles = {terrain_role_for_row(row) for row in rows}
        is_terrain_signature = any(role is not None for role in terrain_roles)
        is_sign_signature = any(is_sign_or_signpost_row(row) for row in rows)
        if is_terrain_signature:
            if None in terrain_roles:
                replacement, rule_name, confidence, lossiness, semantic_evidence = None, "terrain_biome_mixed_or_unknown_role", "blocked", "direct_or_family_substitution", {
                    "method": "source_tile_biome_role_mapping",
                    "blockedReason": "terrain signature contains rows without a classified terrain role",
                    "roles": sorted(str(role) for role in terrain_roles),
                }
            else:
                row_results = []
                for row in rows:
                    row_context = source_terrain_context([row], layer_tiles)
                    row_replacement, row_rule, row_confidence, row_evidence = choose_replacement(row, valid_ids, semantic_mapper, artifact_mapper, row_context)
                    row_lossiness = lossiness_for(row_rule, row_confidence)
                    override = {
                        "sourceIndex": row.get("sourceIndex"),
                        "sourceKey": row.get("sourceKey"),
                        "replacementSid": row_replacement,
                        "ruleName": row_rule,
                        "confidence": row_confidence,
                        "lossiness": row_lossiness,
                        "semanticEvidence": row_evidence,
                    }
                    placement_overrides.append(override)
                    row_results.append((row_replacement, row_rule, row_confidence, row_lossiness, row_evidence))
                replacement, rule_name, confidence, lossiness, semantic_evidence = row_results[0]
                if len(set((result[0], result[1], result[2]) for result in row_results)) != 1:
                    semantic_evidence = {
                        "method": "placement_source_tile_biome_role_mapping",
                        "placementOverrideCount": len(placement_overrides),
                        "replacementHistogram": dict(Counter(str(result[0]) for result in row_results)),
                        "ruleHistogram": dict(Counter(str(result[1]) for result in row_results)),
                    }
        elif is_sign_signature:
            # Per-placement hash so co-signed signatures still vary scenery SIDs.
            row_results = []
            for row in rows:
                row_context = source_terrain_context([row], layer_tiles)
                row_replacement, row_rule, row_confidence, row_evidence = choose_replacement(
                    row, valid_ids, semantic_mapper, artifact_mapper, row_context
                )
                row_lossiness = lossiness_for(row_rule, row_confidence)
                override = {
                    "sourceIndex": row.get("sourceIndex"),
                    "sourceKey": row.get("sourceKey"),
                    "replacementSid": row_replacement,
                    "ruleName": row_rule,
                    "confidence": row_confidence,
                    "lossiness": row_lossiness,
                    "semanticEvidence": row_evidence,
                }
                placement_overrides.append(override)
                row_results.append((row_replacement, row_rule, row_confidence, row_lossiness, row_evidence))
            replacement, rule_name, confidence, lossiness, semantic_evidence = row_results[0]
            if len(set((result[0], result[1], result[2]) for result in row_results)) != 1:
                semantic_evidence = {
                    "method": "placement_sign_to_pathable_scenery",
                    "placementOverrideCount": len(placement_overrides),
                    "replacementHistogram": dict(Counter(str(result[0]) for result in row_results)),
                    "ruleHistogram": dict(Counter(str(result[1]) for result in row_results)),
                }
        else:
            terrain_context = source_terrain_context(rows, layer_tiles)
            replacement, rule_name, confidence, semantic_evidence = choose_replacement(sample, valid_ids, semantic_mapper, artifact_mapper, terrain_context)
            lossiness = lossiness_for(rule_name, confidence)
        animations = Counter(row.get("templateAnimation") for row in rows)
        layers = Counter(str(row.get("sourceLayer")) for row in rows)
        entry = {
            "sourceSignature": signature,
            "sourceSid": source_sid,
            "templateObjectId": sample.get("templateObjectId"),
            "templateAnimation": sample.get("templateAnimation"),
            "category": sample.get("category"),
            "payloadKind": sample.get("payloadKind"),
            "replacementSid": replacement,
            "ruleName": rule_name,
            "confidence": confidence,
            "lossiness": lossiness,
            "count": len(rows),
            "sourceLayers": dict(sorted(layers.items())),
            "sampleSourceKeys": [row.get("sourceKey") for row in rows[:8]],
            "animationHistogram": dict(animations.most_common(8)),
        }
        for source_payload_key in ["generatorFamily", "owner", "ownerEncoding", "payloadDecoderEvidence"]:
            if source_payload_key in sample:
                entry[source_payload_key] = sample[source_payload_key]
        if placement_overrides:
            entry["placementOverridesRequired"] = True
            entry["placementOverrides"] = placement_overrides
        if semantic_evidence is not None:
            entry["semanticEvidence"] = semantic_evidence
        invalid_entries.append(entry)
        if rule_name is None:
            unresolved.append(entry)

    if unresolved:
        unresolved_labels = ", ".join(entry["sourceSignature"] for entry in unresolved[:10])
        raise SystemExit(f"unresolved Homecoming entity substitution signatures: {unresolved_labels}")

    by_replacement = Counter(entry["replacementSid"] for entry in invalid_entries if entry["replacementSid"] is not None)
    by_rule = Counter(entry["ruleName"] for entry in invalid_entries)
    by_lossiness = Counter(entry["lossiness"] for entry in invalid_entries)
    blocked_count = sum(1 for entry in invalid_entries if entry["replacementSid"] is None)
    fallback_rule_count = sum(
        count for rule, count in by_rule.items()
        if isinstance(rule, str) and ("fallback" in rule or "placeholder" in rule)
    )
    output = {
        "schema": SCHEMA,
        "status": STATUS,
        "sourceAlignment": str(ALIGNMENT_PATH.relative_to(REPO_ROOT)),
        "sourceWhitelist": str(CORE_CATALOG_PATH.relative_to(REPO_ROOT)),
        "whitelistKind": "olden_core_map_valid_entity_catalog.mapObjects.id+homecoming_generated",
        "programmaticGeneration": True,
        "silentFallbacksUsed": fallback_rule_count > 0,
        "fallbackRuleInstanceCount": fallback_rule_count,
        "validEntityCount": len(valid_ids),
        "sourceEntityCount": len(entities),
        "distinctSourceSignatureCount": len(groups),
        "invalidSignatureCount": len(invalid_entries),
        "blockedSubstitutionCount": blocked_count,
        "replacementSidHistogram": dict(by_replacement.most_common()),
        "ruleHistogram": dict(by_rule.most_common()),
        "lossinessHistogram": dict(by_lossiness.most_common()),
        "lossyPlaceholderRules": sorted(LOSSY_PLACEHOLDER_RULES),
        "invalidEntitySubstitutions": invalid_entries,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = [
        "# Homecoming Olden Entity Substitution Map",
        "",
        "Status: generated, query-shape substitution map only; not runtime-playable proof.",
        "",
        f"- Source entities: {len(entities)}",
        f"- Distinct source signatures: {len(groups)}",
        f"- Invalid signatures needing substitution: {len(invalid_entries)}",
        f"- Valid Olden whitelist entries: {len(valid_ids)}",
        "",
        "## Top Replacement IDs",
    ]
    report.append(f"- `BLOCKED`: {blocked_count}")
    for replacement, count in by_replacement.most_common(20):
        report.append(f"- `{replacement}`: {count}")
    report.extend(["", "## Top Rules"])
    for rule, count in by_rule.most_common(20):
        report.append(f"- `{rule}`: {count}")
    report.extend(["", "## Lossiness"])
    for lossiness, count in by_lossiness.most_common():
        report.append(f"- `{lossiness}`: {count}")
    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
