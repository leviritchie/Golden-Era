#!/usr/bin/env python3
"""Emit a programmatic single-layer Olden map from Homecoming alignment data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import zipfile
from collections import Counter, defaultdict
from statistics import median
from pathlib import Path
from typing import Any

import campaign_runtime_script as campaign_script
import footprint_alignment
import functional_emit_reservation
import h3m_hero_sid
import h3m_object_registry as h3obj
import town_gate_align
import h3m_scenario_translation as scenario
import homecoming_localization as homecoming_lang
import homm3_olden_rarity_bin as rarity_bin
from homm3_external_dwelling_map import (
    HOMM3_LANDON_BARRACKS_BY_DONOR,
    HOMM3_LANDON_BARRACKS_SIDS,
)
import port_homecoming_poc as poc
import scenario_menu_shell

SCHEMA = "homm3.homecoming_single_layer_map.v0"
STATUS = "generated_deployed_user_visible_object_placement_validated"
VANILLA_WATER_VISUAL_DONOR_TILE_CODE = 18
VANILLA_OCEAN_WATER_ID = 18
# Ocean uses the vanilla water terrain tile ids 18-22 from Core.zip tiles.json plus waterMap id 18
# so native animated water meshes and boat/water traversal semantics match stock Olden maps.
DISPLAY_WATER_TILE_CODE = 18
DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE = {
    "north": 19,
    "south": 20,
    "west": 21,
    "east": 22,
}
DISPLAY_WATER_TILE_CODES = tuple([DISPLAY_WATER_TILE_CODE, *DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE.values()])
DISPLAY_WATER_TILE_NAMES_BY_CODE = {tile_code: f"tiles_{tile_code}" for tile_code in DISPLAY_WATER_TILE_CODES}
DISPLAY_WATER_TERRAIN_PENALTY = 3.0
DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE = DISPLAY_WATER_TILE_CODE
DISPLAY_WATER_BEHAVIOR_DONOR_BIOME = "Water"
DISPLAY_WATER_STATUS = "generated_static_native_vanilla_water_tiles_runtime_unvalidated"
DISPLAY_WATER_ARCHITECTURE = "native_vanilla_water_tiles_with_watermap_ocean_overlay"
NATIVE_WATER_TILE_CODE = DISPLAY_WATER_TILE_CODE
NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE = DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE
NATIVE_WATER_TILE_CODES = DISPLAY_WATER_TILE_CODES
NATIVE_WATER_TILE_NAMES_BY_CODE = DISPLAY_WATER_TILE_NAMES_BY_CODE
NATIVE_WATER_TERRAIN_PENALTY = DISPLAY_WATER_TERRAIN_PENALTY
NATIVE_WATER_PENALTY_STATUS = DISPLAY_WATER_STATUS
NATIVE_WATER_PENALTY_ARCHITECTURE = DISPLAY_WATER_ARCHITECTURE
ACTIVE_WATER_RUNTIME_HOOK = "Homm3HomecomingWaterTraversalBridge"
WATER_TILE_PENALTY_MEMBER = "DB/map/tiles/tiles.json"
WATER_TILE_OVERLAY_STATUS = "retired_runtime_hook_did_not_apply"
WATER_TILE_OVERLAY_ARCHITECTURE = "retired_pathable_environment_object_visual_overlay"
WATER_TILE_OVERLAY_RUNTIME_VISUAL = "Homm3HomecomingWaterTileOverlayVisual"
WATER_TILE_OVERLAY_OBJECT_MEMBER = "DB/map/objects/homecoming_water_tile_overlays.json"
WATER_TILE_OVERLAY_DONOR_PREFAB = "environment/grass_1"
WATER_TILE_OVERLAY_ID_BASE = 910000
WATER_TILE_OVERLAY_IDENTITY_SCHEMA = "homm3.homecoming_water_tile_overlay_identity.v2"
WATER_TILE_OVERLAY_IDENTITY_RELATIVE_PATH = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_tile_overlay_identity_manifest.json"
WATER_TILE_OVERLAY_IDENTITY_SOURCE_PATH = poc.ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / WATER_TILE_OVERLAY_IDENTITY_RELATIVE_PATH
WATER_TILE_OVERLAY_VISUAL_CONTRACT = {
    "material": "sanitized_native_hex_lit_billboard_material_per_sid",
    "animation": "multi_frame_map_idle_texture_animator",
    "orientation": "flat_against_landscape",
    "mesh": "horizontal_quad",
    "cameraFacing": False,
}
SHORELINE_WATER_TILE_STATUS = "generated_static_shoreline_tile_variants_runtime_unvalidated"
SHORELINE_WATER_TILE_POLICY = "orthogonal_source_ocean_edge_to_display_water_tile_variant"
SHORELINE_RIVER_SID = "test"
SHORELINE_RIVER_RANDOM_SEED = 1803185001
ENV_DECORATION_ID_BASE = 900000
MAP_SID = "h3_roe_castle_homecoming_single_layer"
TITLE = "Homecoming - Single Layer"
DESCRIPTION = "A generated single-layer surface projection of Homecoming using Olden-valid entity substitutions. Underground content is excluded until native layer support exists."
NATIVE_START_TEMPLATE_MAP = poc.OLDEN_MAPS_DIR / "Story_maps" / "c_M1.map"
DEFAULT_INPUT_ROOT = poc.ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc"
BASE_OUT_ROOT = Path(os.environ.get("HOMECOMING_POC_OUT_ROOT", DEFAULT_INPUT_ROOT))
OUT_ROOT = BASE_OUT_ROOT / "single_layer_map"
RETIRED_WATER_LAYER_ARTIFACT_PATH = OUT_ROOT / "mod_overlay" / f"{MAP_SID}.homm3_water_layer.json"
RETIRED_WATER_LAYER_RUNTIME_RELATIVE_PATH = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_layer.json"
RETIRED_WATER_LAYER_RUNTIME_SOURCE_PATH = poc.ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / RETIRED_WATER_LAYER_RUNTIME_RELATIVE_PATH
WATER_TRAVERSAL_PLAN_SCHEMA = "homm3.homecoming_water_traversal_plan.v1"
WATER_TRAVERSAL_PLAN_RELATIVE_PATH = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_traversal_plan.json"
WATER_TRAVERSAL_PLAN_SOURCE_PATH = poc.ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / WATER_TRAVERSAL_PLAN_RELATIVE_PATH
ALIGNMENT_PATH = Path(os.environ.get("HOMECOMING_POC_ALIGNMENT_PATH", DEFAULT_INPUT_ROOT / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"))
SUBSTITUTION_PATH = Path(os.environ.get("HOMECOMING_POC_SUBSTITUTION_PATH", BASE_OUT_ROOT / "entity_substitutions" / "homecoming.olden_entity_substitution_map.json"))
CORE_CATALOG_PATH = poc.ROOT / "artifacts" / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"
RANDOM_MONSTER_STRENGTH_MODEL_PATH = Path(os.environ.get("HOMECOMING_POC_RANDOM_MONSTER_STRENGTH_MODEL_PATH", Path(__file__).with_name("h3_random_monster_strength_model.json")))
LAYERED_IR_PATH = DEFAULT_INPUT_ROOT / "layered_ir" / "homecoming.layered_map_ir.json"
SOURCE_LAYER = 0
SOURCE_WIDTH = 72
SOURCE_HEIGHT = 72
OLDEN_VIEW_SECTION_SIZE = 16
OLDEN_WIDTH = ((SOURCE_WIDTH + OLDEN_VIEW_SECTION_SIZE - 1) // OLDEN_VIEW_SECTION_SIZE) * OLDEN_VIEW_SECTION_SIZE
OLDEN_HEIGHT = ((SOURCE_HEIGHT + OLDEN_VIEW_SECTION_SIZE - 1) // OLDEN_VIEW_SECTION_SIZE) * OLDEN_VIEW_SECTION_SIZE
SOURCE_OFFSET_X = (OLDEN_WIDTH - SOURCE_WIDTH) // 2
SOURCE_OFFSET_Y = (OLDEN_HEIGHT - SOURCE_HEIGHT) // 2
PADDING_TILE_ID = 1
PADDING_WATER_ID = 0
Y_AXIS_TRANSFORM = "h3_raw_y_bottom_origin_to_olden_top_origin"
START_HERO_SOURCE_HERO_TYPE = 6
START_HERO_SOURCE_NAME = "Christian"
START_HERO_SID = "homm3_castle_hero_7"
START_FACTION_SID = "homm3_castle"
HOMM3_RANDOM_RESOURCE_PICKUP_SID = "homm3_random_resource_pickup"
HOMM3_RANDOM_RESOURCE_PICKUP_DONOR_SID = "resource_gold"
HOMM3_FLOTSAM_PICKUP_SID = "homm3_flotsam_pickup"
HOMM3_FLOTSAM_PICKUP_DONOR_SID = "resource_wood"
HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER = "DB/map/objects/homecoming_custom_objects.json"
# Shared HoMM→OE rarity bin (policy homm3_rarity_bin_to_olden_erarity_v1).
HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY = rarity_bin.HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY
H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY = (
    rarity_bin.H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY
)
H3_RANDOM_ARTIFACT_RARITY_BY_OBJECT_ID = {
    object_id: rarity_bin.bin_homm3_rarity_to_olden_erarity(homm_rarity)
    for object_id, homm_rarity in H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY.items()
}
HOMECOMING_BUILDINGS_BAN_SID = "homecoming_campaign_buildings_ban"
HOMECOMING_BUILDINGS_CONSTRUCTION_SID = "homecoming_castle_starting_buildings"
HOMECOMING_BUILDINGS_SETTINGS_SID = "default_buildings_settings"
HOMM3_BOAT_SID = "homm3_boat"
HOMM3_BOAT_INTERACT_DONOR_PREFAB = "interactive/autumn_well"
HOMM3_BOAT_OBJECT_MEMBER = "DB/map/objects/homecoming_custom_objects.json"
HOMM3_SUBTERRANEAN_GATE_PORTAL_SID = "homm3_subterranean_gate_portal"
HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID = "portal_5"
HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB = "interactive/dungeon_entrance"
HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER = "DB/map/objects/4_interactables.json"
HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER = "DB/objects_logic/portals/portals.json"
# Scorched-earth: donor portal_5 [1,0,0,2] → keep OCC, all 0s become GATE.
HOMM3_SUBTERRANEAN_GATE_PORTAL_NODES = [1, 2, 2, 2]
HOMM3_LANDON_MAP_EVENT_MARKER_SID = "homm3_landon_map_event_marker"
HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID = "fx_quest_mark_gold_01"
HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER = "DB/map/objects/5_fxs.json"
HOMM3_LANDON_CASTLE_CITY_SID = "homm3_landon_castle_city"
HOMM3_LANDON_CASTLE_CITY_DONOR_SID = "homm3_castle_city"
HOMM3_LANDON_CASTLE_CITY_LOGIC_MEMBER = "DB/objects_logic/cities/homm3_landon_castle_city.json"
HOMM3_LANDON_CASTLE_CITY_DONOR_LOGIC_MEMBER = "DB/objects_logic/cities/homm3_castle_city.json"
HOMM3_LANDON_DUNGEON_CITY_SID = "homm3_landon_dungeon_city"
HOMM3_LANDON_DUNGEON_CITY_DONOR_SID = "homm3_dungeon_city"
HOMM3_LANDON_DUNGEON_CITY_LOGIC_MEMBER = "DB/objects_logic/cities/homm3_landon_dungeon_city.json"
HOMM3_LANDON_DUNGEON_CITY_DONOR_LOGIC_MEMBER = "DB/objects_logic/cities/homm3_dungeon_city.json"
HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER = "DB/map/objects/4_interactables.json"
HOMM3_LANDON_BARRACKS_LOGIC_MEMBER = "DB/objects_logic/hires/barracks.json"
# 3x3 ObjectConfig nodes, row-major. Olden +Y = north.
# High config_z = building bottom (camera/enter) = map-south after Z→map expand
# (grid_y = anchor_y + (size_z - 1 - config_z)). Land-on towns use bottom-center
# GATE index 7 — not native CornerLeft bottom-left index 6.
HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES = [1, 1, 1, 1, 1, 1, 1, 2, 1]
HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX = 7
HOMM3_LANDON_BOTTOM_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # alias
HOMM3_LANDON_BOTTOM_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_NORTH_EDGE_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # retired alias
HOMM3_LANDON_NORTH_EDGE_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_SOUTH_EDGE_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # retired alias
HOMM3_LANDON_SOUTH_EDGE_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_CENTER_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES
# Land-on external dwellings: donor barracks_homm3_{faction}_{N} → landon clones.
# Guardhouse (castle_1) keeps the layered 3x4 footprint with GATE on the bottom-center (index 10).
# Other tiers/factions use native 1x1 visit GATE via homm3_landon_barracks_object_row.
HOMM3_LANDON_BARRACKS_CASTLE_1_SID = HOMM3_LANDON_BARRACKS_BY_DONOR["barracks_homm3_castle_1"]
HOMM3_LANDON_BARRACKS_CASTLE_1_DONOR_SID = "barracks_homm3_castle_1"
HOMM3_LANDON_BARRACKS_CASTLE_1_NODES = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1]
HOMM3_LANDON_BARRACKS_CASTLE_1_SIZE_Z = 4
HOMM3_LANDON_BARRACKS_BOTTOM_GATE_INDEX = 10
HOMM3_LANDON_BARRACKS_NORTH_EDGE_GATE_INDEX = HOMM3_LANDON_BARRACKS_BOTTOM_GATE_INDEX
HOMM3_LANDON_BARRACKS_SOUTH_EDGE_GATE_INDEX = HOMM3_LANDON_BARRACKS_BOTTOM_GATE_INDEX
HOMM3_LANDON_BARRACKS_BOTTOM_CENTER_GATE_INDEX = HOMM3_LANDON_BARRACKS_BOTTOM_GATE_INDEX
HOMM3_LANDON_OBJECT_OVERLAY_STATUS = "generated_static_landon_visit_gate_clone_overlay_runtime_unvalidated"
HOMM3_LANDON_OBJECT_OVERLAY_ARCHITECTURE = "native_donor_objectconfig_and_logic_clones_with_visit_gate_nodes"
HOMM3_LANDON_OBJECT_SIDS = frozenset({
    HOMM3_LANDON_MAP_EVENT_MARKER_SID,
    HOMM3_LANDON_CASTLE_CITY_SID,
    HOMM3_LANDON_DUNGEON_CITY_SID,
    *HOMM3_LANDON_BARRACKS_SIDS,
})
GUARDHOUSE_DWELLING_SOURCE_KEY = "0:18:34"
HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER = "DB/map/objects/homm3_pathability_alignment.json"
HOMM3_PATHING_BLOCKER_SID = "homm3_pathing_blocker"
HOMM3_PATHING_BLOCKER_DONOR_SID = "campaign_FX_block"
# Static Core env pref for Block occupancy clones that need prefs.Length >= 1
# (native bve.ope). Do not inherit campaign_FX_block's fx/fx_map_smoke.
HOMM3_CHEAP_BLOCK_PREF = "environment/dirt_stones_1"
HOMM3_PATHING_BLOCKER_ID_BASE = 880000
HOMM3_PATHING_VISUAL_SID_PREFIX = "homm3_pathing_visual"
HOMM3_PATHABILITY_ALIGNMENT_STATUS = "generated_static_pathability_aligned_runtime_unvalidated"
HOMM3_PATHABILITY_ALIGNMENT_POLICY = "h3m_nonvisitable_block_mask_as_translator_owned_blocking_layer"
HOMM3_PATHABILITY_ALIGNMENT_HUMAN_DECISION = (
    "Translator-owned visual clones preserve original prefabs/properties while suppressing native ObjectConfig "
    "occupancy; runtime interaction behavior of cloned visual SIDs must be user-validated before promoting this "
    "from static pathability proof to gameplay proof."
)
PATHABILITY_VISUAL_CLONE_EXCLUDED_CATEGORIES = frozenset({
    "hero_or_prison",
    "town",
})
PATHABILITY_VISUAL_CLONE_EXTRA_SIDS = frozenset({
    "college_of_wonder",
    "wind_rose",
})
WATER_TILE_OVERLAY_SID_BY_TILE_CODE = {
    NATIVE_WATER_TILE_CODE: "homm3_homecoming_water_overlay_deep",
    NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE["north"]: "homm3_homecoming_water_overlay_shore_north",
    NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE["south"]: "homm3_homecoming_water_overlay_shore_south",
    NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE["west"]: "homm3_homecoming_water_overlay_shore_west",
    NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE["east"]: "homm3_homecoming_water_overlay_shore_east",
}
HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_STATUS = "generated_static_dungeon_entrance_portal_overlay_runtime_unvalidated"
HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_ARCHITECTURE = "native_prop_portals_logic_with_dungeon_entrance_prefab"
SUPPORTED_LIVE_PROPERTY_SIDS = {
    "altar_of_magic_1", "arena", "armory_automaton", "chest", "college_of_wonder", "fort",
    "fountain", "fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", "grass_1",
    "hero-spawner", "homm3_boat", "homm3_castle_city", "homm3_dungeon_city",
    *HOMM3_LANDON_BARRACKS_SIDS, HOMM3_LANDON_CASTLE_CITY_SID, HOMM3_LANDON_DUNGEON_CITY_SID,
    HOMM3_LANDON_MAP_EVENT_MARKER_SID, "homm3_flotsam_pickup", "random-res", HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, "knowledge_garden", "learning_stone",
    "lost_library", "mana_well", "mereas_shrine", "mine_crystals", "mine_gold", "mine_ore",
    "mine_wood", "mountain_dead_small_1", "mountain_dirt_small_1", "mountain_green_small_1", "mountain_lava_small_1", "mountain_snow_small_1", "mountain_water_small_1", "mysterious_stone",
    "orb_observatory", "pool_dirt_small_1", "portal_1", "portal_1_2", "portal_1_3", "portal_2", "portal_2_2", "portal_2_3", "portal_3", "portal_3_2", "portal_3_3", "portal_4", "portal_4_2", "portal_4_3", "portal_5", "portal_5_2", "portal_5_3", "portal_magic", "prison", "quixs_path",
    "random-item",
    "random-squad", "resource_crystals", "resource_dust", "resource_gemstones", "resource_gold",
    "resource_mercury", "resource_ore", "resource_wood", "shady_den", "snow_grassy_hill_1",
    "stables", "stinging_sword", "tree_dirt_1", "tree_of_knowledge", "university", "watchtower", "windmill",
    "wise_owl",
}
# Keep in sync with approach_cell/surface_emit.py SUPPORTED_LIVE_PROPERTY_FAMILIES.
SUPPORTED_LIVE_PROPERTY_FAMILIES = {
    "propActionsAfter", "propActionsBefore", "propActivations", "propAiIntetactions", "propAiIntetations", "propEntities",
    "propHeroes", "propNoCombineGeometries", "propOwners", "propPortals", "propRandomItems", "propRandomSquads",
    "propCities", "propGrowthUnits", "propQuestMarkers", "propResParams", "propResources", "propRewardParams",
    "propSpawns", "propSquads",
    "propVariants", "propsName",
}
RESOURCE_VALUES = {
    "resource_gold": 500,
    "resource_wood": 5,
    "resource_ore": 5,
    "resource_crystals": 1,
    "resource_dust": 1,
    "resource_gemstones": 1,
    "resource_mercury": 1,
}
REWARD_PARAM_SIDS = {
    "altar_of_magic_1", "armory_automaton", "college_of_wonder", "fort", "fountain",
    "knowledge_garden", "learning_stone", "lost_library", "mana_well", "mereas_shrine",
    "mysterious_stone", "orb_observatory", "quixs_path", "shady_den", "stables",
    "stinging_sword",
    "tree_of_knowledge", "university", "watchtower", "windmill", "wise_owl",
}
VARIANT_SIDS = {"chest", "lost_library", "mereas_shrine", "shady_den", "tree_of_knowledge", "windmill", "wise_owl"}
ENTITY_SIDS = {
    "fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", "homm3_seer_hut",
    "lost_library", "mana_well",
    "mine_crystals", "mine_gold", "mine_ore", "mine_wood", "mountain_dead_small_1", "mountain_dirt_small_1", "mountain_green_small_1", "mountain_lava_small_1", "mountain_snow_small_1", "mountain_water_small_1",
    "pool_dirt_small_1", "portal_1", "prison", "snow_grassy_hill_1", "tree_dirt_1",
    "tree_of_knowledge", "university",
}
NO_COMBINE_GEOMETRY_SIDS = {"mountain_dead_small_1", "mountain_dirt_small_1", "mountain_green_small_1", "mountain_lava_small_1", "mountain_snow_small_1", "mountain_water_small_1", "pool_dirt_small_1", "snow_grassy_hill_1", "tree_dirt_1"}
AI_IGNORE_SIDS = {"grass_1", "portal_1", "random-squad", "resource_mercury"}
ACTION_BEFORE_SIDS = {"arena", "lost_library", "mana_well", "mine_gold", "portal_1", "prison", "tree_of_knowledge", "university"}
ACTION_AFTER_SIDS = {"portal_1", "random-squad", "watchtower"}
ACTIVATION_SIDS = {"fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", HOMM3_LANDON_MAP_EVENT_MARKER_SID}
MAP_EVENT_MARKER_SIDS = {HOMM3_LANDON_MAP_EVENT_MARKER_SID, "fx_quest_mark_gold_01"}
LANDON_CITY_PROPERTY_SIDS = {
    HOMM3_LANDON_CASTLE_CITY_SID: START_FACTION_SID,
    "homm3_castle_city": START_FACTION_SID,
    HOMM3_LANDON_DUNGEON_CITY_SID: "homm3_dungeon",
    "homm3_dungeon_city": "homm3_dungeon",
}
PORTAL_SIDS = {
    HOMM3_SUBTERRANEAN_GATE_PORTAL_SID,
    "portal_1", "portal_1_2", "portal_1_3",
    "portal_2", "portal_2_2", "portal_2_3",
    "portal_3", "portal_3_2", "portal_3_3",
    "portal_4", "portal_4_2", "portal_4_3",
    "portal_5", "portal_5_2", "portal_5_3",
    "portal_magic",
}

H3_SURFACE_TO_OLDEN_TILE = {
    0: {"oldenId": 7, "oldenBiome": "Dirt"},
    1: {"oldenId": 7, "oldenBiome": "Dirt"},
    2: {"oldenId": 1, "oldenBiome": "Grass"},
    3: {"oldenId": 4, "oldenBiome": "Snow"},
    4: {"oldenId": 1, "oldenBiome": "Grass"},
    5: {"oldenId": 1, "oldenBiome": "Grass"},
    6: {"oldenId": 15, "oldenBiome": "Burrow"},
    7: {"oldenId": 7, "oldenBiome": "Dirt"},
    8: {"oldenId": DISPLAY_WATER_TILE_CODE, "oldenBiome": "Water"},
}
ENV_DECORATION_SIDS_BY_TILE = {
    1: ["flowers_1", "flowers_2", "grass_1", "grass_2", "grass_stones_1", "grass_stones_2", "mushrooms_1", "mushrooms_2", "mushrooms_3", "mushrooms_4"],
    4: ["grass_snow_1", "grass_snow_2", "snow_stones_1", "snow_stones_2", "snow_stones_3", "snow_stones_4"],
    7: ["flowers_1", "flowers_2", "grass_1", "grass_2", "dirt_stones_1", "dirt_stones_2"],
}
ENV_DECORATION_TARGET_BY_TILE = {
    1: 96,
    4: 40,
    7: 1,
}
SHORELINE_RIVER_DIRECTION_BITS = {
    (-1, 0): 1,
    (1, 0): 2,
    (0, -1): 4,
    (0, 1): 8,
}
SOURCE_ADJACENCY_TO_OLDEN_SHORE_EDGE = {
    (0, 1): "north",
    (0, -1): "south",
    (-1, 0): "west",
    (1, 0): "east",
}
SHORELINE_WATER_EDGE_PRIORITY = ("north", "south", "west", "east")

H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN = {
    0: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
    },
    1: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
    },
    2: {
        1: {"oldenId": 7, "oldenName": "water grass"},
    },
    3: {
        1: {"oldenId": 4, "oldenName": "water snow"},
        2: {"oldenId": 4, "oldenName": "water snow"},
    },
    4: {
        1: {"oldenId": 1, "oldenName": "water grass (swamp river lossy)"},
    },
    5: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
    },
    7: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
        # H3 river type 4 = lava. Olden has no lava-river mesh; map to dirt water
        # so the channel remains marked in waterMap (lossy visual, fail-closed absent).
        4: {"oldenId": 7, "oldenName": "water dirt (lava river lossy)"},
    },
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def homm3_boat_object_row() -> dict[str, Any]:
    """HoMM3 boat: 1x1 GATE on visit. See approach_cell.surface_emit.homm3_boat_object_row."""
    return {
        "id": HOMM3_BOAT_SID,
        "tag": "Interact",
        "isInteractable": True,
        "prefs": [HOMM3_BOAT_INTERACT_DONOR_PREFAB],
        "canBeMirrored": False,
        "selectionUiPrefabID": "1x1",
        "pivotX": 0,
        "pivotZ": 0,
        "sizeX": 1,
        "sizeZ": 1,
        "offsetX": 0,
        "offsetZ": 0,
        "nodes": [2],
        "gateInsideObject": True,
        "generatorConfig": {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 0,
            "buildingInteractionLayout": 0,
        },
    }


def homm3_subterranean_gate_portal_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    """Clone donor portal_5; SID + Dungeon Entrance prefab + scorched-earth GATE nodes."""
    row = json.loads(json.dumps(donor_row, ensure_ascii=False))
    if row.get("id") != HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID:
        raise ValueError(f"subterranean gate portal donor row mismatch: {row}")
    if row.get("sizeX") != 2 or row.get("sizeZ") != 2:
        raise ValueError(
            f"subterranean gate portal donor must remain 2x2; got "
            f"sizeX={row.get('sizeX')!r} sizeZ={row.get('sizeZ')!r}"
        )
    donor_nodes = row.get("nodes")
    if donor_nodes != [1, 0, 0, 2]:
        raise ValueError(
            f"subterranean gate portal donor nodes must be [1,0,0,2]; got {donor_nodes!r}"
        )
    row["id"] = HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
    row["prefs"] = [HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB]
    row["nodes"] = list(HOMM3_SUBTERRANEAN_GATE_PORTAL_NODES)
    return row


def clone_core_object_row(donor_row: dict[str, Any], *, donor_sid: str, clone_sid: str) -> dict[str, Any]:
    if donor_row.get("id") != donor_sid:
        raise ValueError(f"landon object donor row mismatch for {clone_sid}: expected {donor_sid!r}, found {donor_row.get('id')!r}")
    row = json.loads(json.dumps(donor_row, ensure_ascii=False))
    row["id"] = clone_sid
    return row


def homm3_landon_map_event_marker_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    """1x1 interact marker for map-events (FX body is prefab-only; no occupied cell).

    nodes=[2] here is a deliberate marker-only footprint for floating quest FX —
    not a Resource pickup. Do not copy this pattern onto gold/items/chests.
    """
    row = clone_core_object_row(
        donor_row,
        donor_sid=HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
        clone_sid=HOMM3_LANDON_MAP_EVENT_MARKER_SID,
    )
    row["sizeX"] = 1
    row["sizeZ"] = 1
    row["nodes"] = [2]
    # Marker-only FX: not an inside-object visit on an occupied body.
    row.pop("gateInsideObject", None)
    return row


def homm3_random_resource_pickup_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    """One-shot random basic-resource pickup (not weekly random-res).

    Keeps the donor resource_gold 3x3 footprint: occupied center (body) + GATE
    *markers* around it. Do not set gateInsideObject — native Resource rows leave
    it unset; GATE markers are exterior approach points, not an inside-object visit.
    """

    row = clone_core_object_row(
        donor_row,
        donor_sid=HOMM3_RANDOM_RESOURCE_PICKUP_DONOR_SID,
        clone_sid=HOMM3_RANDOM_RESOURCE_PICKUP_SID,
    )
    if row.get("sizeX") != 3 or row.get("sizeZ") != 3:
        raise ValueError(
            f"{HOMM3_RANDOM_RESOURCE_PICKUP_DONOR_SID} must remain a 3x3 resource footprint for "
            f"{HOMM3_RANDOM_RESOURCE_PICKUP_SID}: sizeX={row.get('sizeX')!r} sizeZ={row.get('sizeZ')!r}"
        )
    nodes = row.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 9 or 1 not in nodes:
        raise ValueError(
            f"{HOMM3_RANDOM_RESOURCE_PICKUP_DONOR_SID} must keep a 3x3 nodes grid with an occupied "
            f"value-1 cell for {HOMM3_RANDOM_RESOURCE_PICKUP_SID}: {nodes!r}"
        )
    # Preserve donor gateInsideObject (unset on native resource_*).
    row.pop("gateInsideObject", None)
    return row


def homm3_flotsam_pickup_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    """One-shot HoMM3 flotsam water reward pickup (not weekly random-res)."""

    row = clone_core_object_row(
        donor_row,
        donor_sid=HOMM3_FLOTSAM_PICKUP_DONOR_SID,
        clone_sid=HOMM3_FLOTSAM_PICKUP_SID,
    )
    if row.get("sizeX") != 3 or row.get("sizeZ") != 3:
        raise ValueError(
            f"{HOMM3_FLOTSAM_PICKUP_DONOR_SID} must remain a 3x3 resource footprint for "
            f"{HOMM3_FLOTSAM_PICKUP_SID}: sizeX={row.get('sizeX')!r} sizeZ={row.get('sizeZ')!r}"
        )
    nodes = row.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 9 or 1 not in nodes:
        raise ValueError(
            f"{HOMM3_FLOTSAM_PICKUP_DONOR_SID} must keep a 3x3 nodes grid with an occupied "
            f"value-1 cell for {HOMM3_FLOTSAM_PICKUP_SID}: {nodes!r}"
        )
    row.pop("gateInsideObject", None)
    return row


def homm3_landon_bottom_center_gate_city_object_row(
    donor_row: dict[str, Any], *, clone_sid: str, donor_sid: str
) -> dict[str, Any]:
    """Land-on town ObjectConfig clone with bottom-center GATE (index 7).

    CornerLeft interact is ON buildingLeftBottom. Native SW is LeftBottom (0,2)
    / GATE index 6; south-center is LeftBottom (1,2) / GATE index 7 with a 1x1
    building. InteractionLayout.Bottom places interact one cell south of the
    building (external) and must not be used here.
    """
    row = clone_core_object_row(donor_row, donor_sid=donor_sid, clone_sid=clone_sid)
    if row.get("sizeX") != 3 or row.get("sizeZ") != 3:
        raise ValueError(f"{donor_sid} must remain a 3x3 city footprint for {clone_sid}: {row}")
    row["nodes"] = list(HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES)
    row["canBeMirrored"] = False
    row["generatorConfig"] = {
        "buildingSizeX": 1,
        "buildingSizeZ": 1,
        "buildingLeftBottomX": 1,
        "buildingLeftBottomZ": 2,
        "buildingInteractionLayout": 1,  # InteractionLayout.CornerLeft on south-center
    }
    return row


def homm3_landon_center_gate_city_object_row(
    donor_row: dict[str, Any], *, clone_sid: str, donor_sid: str
) -> dict[str, Any]:
    """Thin alias for homm3_landon_bottom_center_gate_city_object_row."""
    return homm3_landon_bottom_center_gate_city_object_row(
        donor_row, clone_sid=clone_sid, donor_sid=donor_sid
    )


def homm3_landon_barracks_object_row(
    donor_row: dict[str, Any], *, donor_sid: str, clone_sid: str
) -> dict[str, Any]:
    """Land-on dwelling ObjectConfig clone.

    Castle_1 (Guardhouse) keeps the layered 3x4 bottom-center GATE *marker* contract.
    Tiers 2–5 use town-style bottom-center marker (nodes==2, not occupied).
    gateInsideObject=True matches native land-on cities — not GATE-ring pickups.
    """
    row = clone_core_object_row(donor_row, donor_sid=donor_sid, clone_sid=clone_sid)
    if clone_sid == HOMM3_LANDON_BARRACKS_CASTLE_1_SID:
        if row.get("sizeX") != 3:
            raise ValueError(f"{donor_sid} must keep sizeX=3 for {clone_sid}")
        row["sizeZ"] = HOMM3_LANDON_BARRACKS_CASTLE_1_SIZE_Z
        row["nodes"] = list(HOMM3_LANDON_BARRACKS_CASTLE_1_NODES)
        row["gateInsideObject"] = True
        return row
    if row.get("sizeX") != 3 or row.get("sizeZ") != 3:
        raise ValueError(
            f"{donor_sid} must remain a 3x3 barracks footprint for {clone_sid}: "
            f"sizeX={row.get('sizeX')!r} sizeZ={row.get('sizeZ')!r}"
        )
    row["nodes"] = list(HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES)
    row["gateInsideObject"] = True
    return row


def homm3_landon_barracks_castle_1_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    return homm3_landon_barracks_object_row(
        donor_row,
        donor_sid=HOMM3_LANDON_BARRACKS_CASTLE_1_DONOR_SID,
        clone_sid=HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
    )

def clone_core_objects_logic_row(donor_row: dict[str, Any], *, donor_sid: str, clone_sid: str) -> dict[str, Any]:
    row = clone_core_object_row(donor_row, donor_sid=donor_sid, clone_sid=clone_sid)
    return row


def _core_object_row_by_id(row_id: str) -> dict[str, Any] | None:
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if isinstance(row, dict) and row.get("id") == row_id:
                    return row
    return None


def inject_homm3_landon_object_configs(configs: dict[str, dict[str, Any]], valid_ids: set[str]) -> None:
    def require_donor(donor_sid: str, clone_sid: str) -> dict[str, Any]:
        donor = configs.get(donor_sid)
        if isinstance(donor, dict):
            return donor
        donor = _core_object_row_by_id(donor_sid)
        if not isinstance(donor, dict):
            raise ValueError(f"missing {donor_sid!r} donor config for {clone_sid}")
        configs[donor_sid] = donor
        return donor

    if HOMM3_LANDON_MAP_EVENT_MARKER_SID in valid_ids:
        donor = require_donor(HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID, HOMM3_LANDON_MAP_EVENT_MARKER_SID)
        configs[HOMM3_LANDON_MAP_EVENT_MARKER_SID] = homm3_landon_map_event_marker_object_row(donor)
    if HOMM3_FLOTSAM_PICKUP_SID in valid_ids:
        donor = require_donor(HOMM3_FLOTSAM_PICKUP_DONOR_SID, HOMM3_FLOTSAM_PICKUP_SID)
        configs[HOMM3_FLOTSAM_PICKUP_SID] = homm3_flotsam_pickup_object_row(donor)
    if HOMM3_LANDON_CASTLE_CITY_SID in valid_ids:
        donor = require_donor(HOMM3_LANDON_CASTLE_CITY_DONOR_SID, HOMM3_LANDON_CASTLE_CITY_SID)
        configs[HOMM3_LANDON_CASTLE_CITY_SID] = homm3_landon_bottom_center_gate_city_object_row(
            donor,
            clone_sid=HOMM3_LANDON_CASTLE_CITY_SID,
            donor_sid=HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
        )
    if HOMM3_LANDON_DUNGEON_CITY_SID in valid_ids:
        donor = require_donor(HOMM3_LANDON_DUNGEON_CITY_DONOR_SID, HOMM3_LANDON_DUNGEON_CITY_SID)
        configs[HOMM3_LANDON_DUNGEON_CITY_SID] = homm3_landon_bottom_center_gate_city_object_row(
            donor,
            clone_sid=HOMM3_LANDON_DUNGEON_CITY_SID,
            donor_sid=HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
        )
    for donor_sid, clone_sid in HOMM3_LANDON_BARRACKS_BY_DONOR.items():
        if clone_sid not in valid_ids:
            continue
        donor = require_donor(donor_sid, clone_sid)
        configs[clone_sid] = homm3_landon_barracks_object_row(
            donor, donor_sid=donor_sid, clone_sid=clone_sid
        )


def landon_bottom_center_gate_contract(native_config: dict[str, Any]) -> bool:
    nodes = native_config.get("nodes")
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    return (
        isinstance(nodes, list)
        and isinstance(size_x, int)
        and isinstance(size_z, int)
        and size_x == 3
        and size_z == HOMM3_LANDON_BARRACKS_CASTLE_1_SIZE_Z
        and len(nodes) == size_x * size_z
        and nodes == list(HOMM3_LANDON_BARRACKS_CASTLE_1_NODES)
        and nodes[HOMM3_LANDON_BARRACKS_BOTTOM_CENTER_GATE_INDEX] == 2
        and sum(1 for value in nodes if value == 2) == 1
    )


def verify_homm3_landon_barracks_guardhouse_visit_gate_alignment(native_config: dict[str, Any]) -> dict[str, Any]:
    """Contract: land-on barracks uses a single bottom-center GATE (town policy)."""
    entity = {
        "sourceKey": GUARDHOUSE_DWELLING_SOURCE_KEY,
        "sourceX": 18,
        "sourceY": 34,
        "rotation": 0,
        "templateVisitMask": [0, 0, 0, 0, 0, 128],
        "templateBlockMask": [255, 255, 255, 255, 191, 63],
    }
    bottom_center_gate = landon_bottom_center_gate_contract(native_config)
    default_node = target_node(entity["sourceX"], entity["sourceY"])
    rotation, rotation_evidence = derive_source_mask_rotation(entity, native_config)
    node, anchor_evidence = derive_source_anchor_node(
        entity,
        HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
        native_config,
        default_node,
        rotation=rotation,
    )
    visit_node = target_node(entity["sourceX"], entity["sourceY"])
    gate_nodes = nodes_for_object_instance_with_value(
        HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
        native_config,
        node,
        rotation,
        node_value=2,
    )
    return {
        "sourceKey": GUARDHOUSE_DWELLING_SOURCE_KEY,
        "visitNode": visit_node,
        "emitNode": node,
        "rotation": rotation,
        "rotationDecision": rotation_evidence.get("decision"),
        "gateNodes": sorted(gate_nodes),
        "visitOnGate": visit_node in gate_nodes,
        "bottomCenterGate": bottom_center_gate,
        "gateCount": len(gate_nodes),
        "anchorFootprint": anchor_evidence.get("nativeFootprint"),
    }

def homecoming_water_tile_overlay_object_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": sid,
            "tag": "Environment",
            "biome": "Water",
            "prefs": [WATER_TILE_OVERLAY_DONOR_PREFAB],
            "sizeX": 1,
            "sizeZ": 1,
            "randomRotation": False,
        }
        for _tile_code, sid in sorted(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.items())
    ]

def sanitize_sid_fragment(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if "a" <= char <= "z" or "0" <= char <= "9":
            chars.append(char)
        else:
            chars.append("_")
    compact = "_".join(part for part in "".join(chars).split("_") if part)
    return compact or "object"


def homm3_pathing_visual_sid(source_sid: str) -> str:
    digest = hashlib.sha256(source_sid.encode("utf-8")).hexdigest()[:10]
    return f"{HOMM3_PATHING_VISUAL_SID_PREFIX}_{digest}_{sanitize_sid_fragment(source_sid)[:42]}"


def native_row_pathing_clone_size(row: dict[str, Any]) -> tuple[int, int, str]:
    size_x = row.get("sizeX")
    size_z = row.get("sizeZ")
    nodes = row.get("nodes")
    if isinstance(size_x, int) and isinstance(size_z, int) and size_x > 0 and size_z > 0:
        if nodes is not None and (not isinstance(nodes, list) or len(nodes) != size_x * size_z):
            raise ValueError(f"cannot clone invalid ObjectConfig node grid for {row.get('id')}: {nodes!r}")
        return size_x, size_z, "native_object_config_size_grid"
    generator_config = row.get("generatorConfig")
    if isinstance(generator_config, dict):
        building_size_x = generator_config.get("buildingSizeX")
        building_size_z = generator_config.get("buildingSizeZ")
        if isinstance(building_size_x, int) and isinstance(building_size_z, int) and building_size_x > 0 and building_size_z > 0:
            return building_size_x, building_size_z, "native_generator_building_size_grid"
    return 1, 1, "translator_explicit_visual_point_anchor"


def homm3_nonblocking_visual_object_row(source_row: dict[str, Any]) -> dict[str, Any]:
    source_sid = source_row.get("id")
    if not isinstance(source_sid, str) or not source_sid:
        raise ValueError(f"cannot clone ObjectConfig row without string id: {source_row}")
    row = json.loads(json.dumps(source_row, ensure_ascii=False))
    size_x, size_z, _source = native_row_pathing_clone_size(row)
    row["id"] = homm3_pathing_visual_sid(source_sid)
    row["sizeX"] = size_x
    row["sizeZ"] = size_z
    row["nodes"] = [0] * (size_x * size_z)
    return row


def homm3_pathing_blocker_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    if donor_row.get("id") != HOMM3_PATHING_BLOCKER_DONOR_SID:
        raise ValueError(f"pathing blocker donor row mismatch: {donor_row}")
    row = json.loads(json.dumps(donor_row, ensure_ascii=False))
    row["id"] = HOMM3_PATHING_BLOCKER_SID
    row["tag"] = "Block"
    row["isInteractable"] = False
    row["sizeX"] = 1
    row["sizeZ"] = 1
    row["nodes"] = [1]
    # Keep campaign_FX_block for Block/nodes shape only; override smoke FX prefs.
    row["prefs"] = [HOMM3_CHEAP_BLOCK_PREF]
    return row


def is_homm3_pathing_visual_sid(sid: str) -> bool:
    return sid.startswith(f"{HOMM3_PATHING_VISUAL_SID_PREFIX}_")


def h3m_blocked_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int):
            raise ValueError(f"H3M object mask byte is not an integer: {raw!r}")
        if raw < 0 or raw > 255:
            raise ValueError(f"H3M object mask byte outside 0..255: {raw!r}")
        for col_index in range(H3M_MASK_WIDTH):
            if (raw >> col_index) & 1 == 0:
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def entity_blocked_mask_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return h3m_blocked_mask_offsets(entity.get("templateBlockMask"))


def entity_nonvisitable_block_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return entity_blocked_mask_offsets(entity) - source_visit_offsets(entity)


def entity_nonvisitable_block_nodes(entity: dict[str, Any]) -> set[int]:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        return set()
    nodes: set[int] = set()
    for dx, dy in entity_nonvisitable_block_offsets(entity):
        try:
            nodes.add(target_node_allowing_source_padding(source_x + dx, source_y + dy))
        except ValueError:
            continue
    return nodes


def entity_visit_nodes(entity: dict[str, Any]) -> set[int]:
    """HoMM3 visit-mask cells projected into the Olden 80x80 envelope."""
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        return set()
    nodes: set[int] = set()
    for dx, dy in source_visit_offsets(entity):
        try:
            nodes.add(target_node_allowing_source_padding(source_x + dx, source_y + dy))
        except ValueError:
            continue
    return nodes


def nodes_for_object_instance_with_value(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    node_value: int,
) -> set[int]:
    """Olden cells where ObjectConfig.nodes equals node_value (1=blocked, 2=GATE)."""
    if sid == HOMM3_PATHING_BLOCKER_SID:
        return {anchor_node} if node_value == 1 else set()
    anchor_x = anchor_node % OLDEN_WIDTH
    anchor_y = anchor_node // OLDEN_WIDTH
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        generator_config = config.get("generatorConfig")
        if isinstance(generator_config, dict) and isinstance(generator_config.get("buildingSizeX"), int) and isinstance(generator_config.get("buildingSizeZ"), int):
            size_x = int(generator_config["buildingSizeX"])
            size_z = int(generator_config["buildingSizeZ"])
        else:
            return set()
    nodes = config.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
        return set()
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and config.get("canBeMirrored") is True
    matched: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            if nodes[config_z * size_x + config_x] != node_value:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            grid_x = anchor_x + placed_dx
            grid_y = anchor_y + (size_z - 1 - config_z)
            if 0 <= grid_x < OLDEN_WIDTH and 0 <= grid_y < OLDEN_HEIGHT:
                matched.add(grid_y * OLDEN_WIDTH + grid_x)
    return matched


def subterranean_portal_gate_nodes(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> set[int]:
    """Union of scorched-earth subterranean portal GATE marker cells."""
    gates: set[int] = set()
    for group in objects:
        if not isinstance(group, dict) or group.get("sid") != HOMM3_SUBTERRANEAN_GATE_PORTAL_SID:
            continue
        config = native_object_configs.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
        if not isinstance(config, dict):
            raise ValueError(f"missing ObjectConfig for {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        if not (len(ids) == len(nodes) == len(rotations)):
            raise ValueError(f"object group length mismatch for {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
        for anchor, rotation in zip(nodes, rotations):
            if not isinstance(anchor, int) or not isinstance(rotation, int):
                raise ValueError(f"invalid node/rotation for {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
            gates |= nodes_for_object_instance_with_value(
                HOMM3_SUBTERRANEAN_GATE_PORTAL_SID,
                config,
                anchor,
                rotation,
                node_value=2,
            )
    return gates


def occupied_nodes_for_object_instance(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
) -> set[int]:
    if sid == HOMM3_PATHING_BLOCKER_SID:
        return {anchor_node}
    anchor_x = anchor_node % OLDEN_WIDTH
    anchor_y = anchor_node // OLDEN_WIDTH
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    footprint_source = "native_object_config_size_grid"
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        generator_config = config.get("generatorConfig")
        if isinstance(generator_config, dict) and isinstance(generator_config.get("buildingSizeX"), int) and isinstance(generator_config.get("buildingSizeZ"), int):
            size_x = int(generator_config["buildingSizeX"])
            size_z = int(generator_config["buildingSizeZ"])
            footprint_source = "native_generator_building_size_grid"
        elif sid in POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS or is_homm3_pathing_visual_sid(sid):
            return set()
        else:
            return set()
    nodes = config.get("nodes")
    if nodes is not None and (not isinstance(nodes, list) or len(nodes) != size_x * size_z):
        raise ValueError(f"cannot compute occupied nodes for {sid}: invalid nodes grid {nodes!r}")
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and config.get("canBeMirrored") is True
    occupied: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            value = nodes[config_z * size_x + config_x] if isinstance(nodes, list) else None
            if value != 1:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            grid_x = anchor_x + placed_dx
            grid_y = anchor_y + (size_z - 1 - config_z)
            if 0 <= grid_x < OLDEN_WIDTH and 0 <= grid_y < OLDEN_HEIGHT:
                occupied.add(grid_y * OLDEN_WIDTH + grid_x)
    if footprint_source == "native_object_config_size_grid" and not occupied and sid not in POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS and not is_homm3_pathing_visual_sid(sid):
        return set()
    return occupied


def eight_neighbor_nodes(nodes: set[int], *, grid_width: int = OLDEN_WIDTH, grid_height: int = OLDEN_HEIGHT) -> set[int]:
    neighbors: set[int] = set()
    for node in nodes:
        x = node % grid_width
        y = node // grid_width
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < grid_width and 0 <= ny < grid_height:
                    neighbors.add(ny * grid_width + nx)
    return neighbors


def apply_homm3_pathability_visual_clones(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    visual_rows: dict[str, dict[str, Any]] = {}
    visual_clone_counts = Counter()
    visual_clone_examples: list[dict[str, Any]] = []
    for placement in placements:
        replacement_sid = str(placement["replacementSid"])
        if replacement_sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(replacement_sid):
            continue
        entity = placement.get("entity")
        if not isinstance(entity, dict):
            raise ValueError(f"pathability alignment requires placement entity: {placement}")
        if str(entity.get("category")) in PATHABILITY_VISUAL_CLONE_EXCLUDED_CATEGORIES:
            continue
        if replacement_sid not in SUPPRESSIBLE_SOURCE_SCENERY_SIDS and replacement_sid not in PATHABILITY_VISUAL_CLONE_EXTRA_SIDS:
            continue
        native_config = native_object_configs.get(replacement_sid)
        if not isinstance(native_config, dict):
            raise ValueError(f"missing native object config for pathability alignment SID {replacement_sid}")
        h3_block_nodes = entity_nonvisitable_block_nodes(entity)
        olden_occupied = occupied_nodes_for_object_instance(
            replacement_sid,
            native_config,
            int(placement["node"]),
            int(placement["rotation"]),
        )
        extraneous_blocking = olden_occupied - h3_block_nodes
        if not extraneous_blocking:
            continue
        visual_sid = homm3_pathing_visual_sid(replacement_sid)
        if visual_sid not in visual_rows:
            visual_rows[visual_sid] = homm3_nonblocking_visual_object_row(native_config)
            native_object_configs[visual_sid] = visual_rows[visual_sid]
        placement["replacementSid"] = visual_sid
        placement["pathabilityVisualClone"] = {
            "sourceReplacementSid": replacement_sid,
            "extraneousBlockingNodeCount": len(extraneous_blocking),
            "h3NonvisitableBlockNodeCount": len(h3_block_nodes),
        }
        visual_clone_counts[replacement_sid] += 1
        if len(visual_clone_examples) < 20:
            visual_clone_examples.append({
                "sourceIndex": placement.get("id"),
                "sourceKey": entity.get("sourceKey"),
                "sourceReplacementSid": replacement_sid,
                "visualSid": visual_sid,
                "extraneousBlockingNodeCount": len(extraneous_blocking),
                "h3NonvisitableBlockNodeCount": len(h3_block_nodes),
            })

    return {
        "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": HOMM3_PATHABILITY_ALIGNMENT_POLICY,
        "phase": "visual_clone_before_grouping",
        "humanDecision": HOMM3_PATHABILITY_ALIGNMENT_HUMAN_DECISION,
        "visualCloneSidCount": len(visual_rows),
        "visualCloneObjectCount": sum(visual_clone_counts.values()),
        "visualCloneSourceSidHistogram": dict(visual_clone_counts.most_common()),
        "visualCloneExamples": visual_clone_examples,
        "visualRows": visual_rows,
        "proofBoundary": "source/static/generated-artifact visual clone alignment; runtime interaction of cloned visual SIDs remains user-unvalidated",
    }


def apply_homm3_pathability_alignment(
    placements: list[dict[str, Any]],
    surface_entities: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    visual_alignment = apply_homm3_pathability_visual_clones(placements, native_object_configs)
    occupied_nodes: set[int] = set()
    for placement in placements:
        sid = str(placement["replacementSid"])
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            raise ValueError(f"missing native object config while summing occupied nodes for {sid}")
        full_occ = occupied_nodes_for_object_instance(
            sid,
            config,
            int(placement["node"]),
            int(placement["rotation"]),
        )
        if (
            functional_emit_reservation.is_infrastructure_sid(sid)
            or sid == HOMM3_PATHING_BLOCKER_SID
            or is_homm3_pathing_visual_sid(sid)
            or functional_emit_reservation.is_scenery_placement(placement)
        ):
            occupied_nodes |= full_occ
            continue
        entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else None
        if entity is None:
            occupied_nodes |= full_occ
            continue
        h3_authority = entity_visit_nodes(entity) | entity_nonvisitable_block_nodes(entity)
        occupied_nodes |= full_occ & h3_authority

    required_block_nodes: set[int] = set()
    for entity in surface_entities:
        required_block_nodes |= entity_nonvisitable_block_nodes(entity)
    gap_nodes = sorted(required_block_nodes - occupied_nodes)

    next_blocker_id = HOMM3_PATHING_BLOCKER_ID_BASE
    blocker_examples: list[dict[str, Any]] = []
    for node in gap_nodes:
        placements.append({
            "replacementSid": HOMM3_PATHING_BLOCKER_SID,
            "id": next_blocker_id,
            "entity": {
                "sourceKey": f"pathability_blocker:{node}",
                "category": "pathability_alignment_blocker",
            },
            "ruleName": "h3m_nonvisitable_block_mask_gap_fill",
            "lossiness": "pathability_alignment",
            "node": node,
            "rotation": 0,
            "level": 0.0,
            "pathabilityBlocker": True,
        })
        if len(blocker_examples) < 20:
            blocker_examples.append({"id": next_blocker_id, "node": node, "x": node % OLDEN_WIDTH, "y": node // OLDEN_WIDTH})
        next_blocker_id += 1

    return {
        **{key: value for key, value in visual_alignment.items() if key != "visualRows"},
        "requiredH3NonvisitableBlockNodeCount": len(required_block_nodes),
        "occupiedNodeCountBeforeGapFill": len(occupied_nodes),
        "gapFillBlockerCount": len(gap_nodes),
        "gapFillBlockerExamples": blocker_examples,
        "visualRows": visual_alignment.get("visualRows") or {},
        "pathingBlockerSid": HOMM3_PATHING_BLOCKER_SID,
        "pathingBlockerIdBase": HOMM3_PATHING_BLOCKER_ID_BASE,
        "proofBoundary": "source/static/generated-artifact pathability alignment; native runtime pathfinder and cloned visual interaction remain user-unvalidated",
    }


def load_native_object_configs(valid_ids: set[str]) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                raise ValueError(f"Core map-object member has no array rows: {name}")
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in valid_ids:
                    configs[row["id"]] = row
    if HOMM3_BOAT_SID in valid_ids:
        configs[HOMM3_BOAT_SID] = homm3_boat_object_row()
    if HOMM3_SUBTERRANEAN_GATE_PORTAL_SID in valid_ids:
        donor = configs.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID)
        if not isinstance(donor, dict):
            raise ValueError(f"missing {HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID!r} donor config for {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
        configs[HOMM3_SUBTERRANEAN_GATE_PORTAL_SID] = homm3_subterranean_gate_portal_object_row(donor)
    inject_homm3_landon_object_configs(configs, valid_ids)
    for row in homecoming_water_tile_overlay_object_rows():
        if row["id"] in valid_ids:
            configs[row["id"]] = row
    if HOMM3_PATHING_BLOCKER_SID in valid_ids:
        donor = configs.get(HOMM3_PATHING_BLOCKER_DONOR_SID)
        if not isinstance(donor, dict):
            with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
                for name in core.namelist():
                    if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                        continue
                    doc = json.loads(core.read(name).decode("utf-8-sig"))
                    rows = doc.get("array") if isinstance(doc, dict) else None
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if isinstance(row, dict) and row.get("id") == HOMM3_PATHING_BLOCKER_DONOR_SID:
                            donor = row
                            break
                    if isinstance(donor, dict):
                        break
        if not isinstance(donor, dict):
            raise ValueError(f"missing {HOMM3_PATHING_BLOCKER_DONOR_SID!r} donor config for {HOMM3_PATHING_BLOCKER_SID}")
        configs[HOMM3_PATHING_BLOCKER_SID] = homm3_pathing_blocker_object_row(donor)
    missing = sorted(valid_ids - set(configs))
    if missing:
        raise ValueError(f"missing native object config rows for whitelisted emitted SIDs: {missing[:20]}")
    return configs


def signature_for(entity: dict[str, Any]) -> str:
    return "|".join(str(entity.get(key, "")) for key in ["sid", "templateObjectId", "templateAnimation", "category", "payloadKind"])


def is_in_source_bounds(entity: dict[str, Any]) -> bool:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    return isinstance(source_x, int) and isinstance(source_y, int) and 0 <= source_x < SOURCE_WIDTH and 0 <= source_y < SOURCE_HEIGHT


def project_source_y(source_y: int) -> int:
    if not (0 <= source_y < SOURCE_HEIGHT):
        raise ValueError(f"source y outside emitted envelope: {source_y}")
    return SOURCE_HEIGHT - 1 - source_y


def target_node(source_x: int, source_y: int) -> int:
    if not (0 <= source_x < SOURCE_WIDTH and 0 <= source_y < SOURCE_HEIGHT):
        raise ValueError(f"source coordinate outside emitted envelope: {source_x},{source_y}")
    return (project_source_y(source_y) + SOURCE_OFFSET_Y) * OLDEN_WIDTH + source_x + SOURCE_OFFSET_X


def map_view_sector_count(size: int) -> int:
    if size <= 0:
        raise ValueError(f"map dimension must be positive: {size}")
    return (size + OLDEN_VIEW_SECTION_SIZE - 1) // OLDEN_VIEW_SECTION_SIZE


def generated_surface_view() -> dict[str, Any]:
    return {
        "name": "surface",
        "minSecX": 0,
        "minSecZ": 0,
        "secSizeX": map_view_sector_count(OLDEN_WIDTH),
        "secSizeZ": map_view_sector_count(OLDEN_HEIGHT),
        "isUnderground": False,
        "stack": -1,
    }


def apply_native_ocean_basin_geometry(out: dict[str, list[int]], width: int, height: int) -> dict[str, int]:
    """Lower native water terrain tiles into a basin and stamp perimeter ramp climbs."""
    levels = out["levelsMap"]
    climbs = out["climbsMap"]
    tiles = out["tilesMap"]
    perimeter_count = 0
    interior_count = 0
    for y in range(height):
        for x in range(width):
            node = y * width + x
            if not is_display_water_tile_code(tiles[node]):
                continue
            levels[node] = scenario.NATIVE_OCEAN_BASIN_LEVEL
            perimeter = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    ny = y + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        perimeter = True
                        break
                    neighbor = ny * width + nx
                    if not is_display_water_tile_code(tiles[neighbor]):
                        perimeter = True
                        break
                if perimeter:
                    break
            if perimeter:
                climbs[node] = scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB
                perimeter_count += 1
            else:
                climbs[node] = scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB
                interior_count += 1
    return {
        "basinLevel": scenario.NATIVE_OCEAN_BASIN_LEVEL,
        "interiorClimb": scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB,
        "perimeterClimb": scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB,
        "policy": scenario.NATIVE_OCEAN_BASIN_GEOMETRY_POLICY,
        "oceanTerrainNodeCount": perimeter_count + interior_count,
        "perimeterOceanTerrainNodeCount": perimeter_count,
        "interiorOceanTerrainNodeCount": interior_count,
    }


def project_arrays(surface_map_data: dict[str, Any]) -> dict[str, list[int]]:
    if surface_map_data.get("sizeX_") != SOURCE_WIDTH or surface_map_data.get("sizeZ_") != SOURCE_HEIGHT:
        raise ValueError("surface map data must be 72x72 before projection")
    out = {
        "tilesMap": [PADDING_TILE_ID] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "roadsMap": [0] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "waterMap": [PADDING_WATER_ID] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "levelsMap": [0] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "climbsMap": [0] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "customAreasPainting": [0] * (OLDEN_WIDTH * OLDEN_HEIGHT),
    }
    for y in range(SOURCE_HEIGHT):
        for x in range(SOURCE_WIDTH):
            source_index = y * SOURCE_WIDTH + x
            target_index = target_node(x, y)
            h3_tile = surface_map_data["tilesMap"][source_index]
            h3_water = surface_map_data["waterMap"][source_index]
            h3_road = surface_map_data["roadsMap"][source_index]
            if h3_tile not in H3_SURFACE_TO_OLDEN_TILE:
                raise ValueError(f"unsupported H3 surface terrain {h3_tile} at {x},{y}")
            if h3_road != 0:
                raise ValueError(f"unsupported H3 surface road {h3_road} at {x},{y}")
            if h3_tile == 8:
                if h3_water != 0:
                    raise ValueError(f"H3 water terrain with additional river overlay {h3_water} at {x},{y}")
                out["tilesMap"][target_index] = project_ocean_tile_code(surface_map_data, x, y)
                out["waterMap"][target_index] = VANILLA_OCEAN_WATER_ID
                continue
            terrain_mapping = H3_SURFACE_TO_OLDEN_TILE[h3_tile]
            out["tilesMap"][target_index] = terrain_mapping["oldenId"]
            if "oldenWaterId" in terrain_mapping:
                if h3_water != 0:
                    raise ValueError(f"H3 water terrain with additional river overlay {h3_water} at {x},{y}")
                out["waterMap"][target_index] = terrain_mapping["oldenWaterId"]
            elif h3_water == 0:
                out["waterMap"][target_index] = 0
            else:
                terrain_rivers = H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN.get(h3_tile, {})
                river_mapping = terrain_rivers.get(h3_water)
                if river_mapping is None:
                    raise ValueError(f"unsupported H3 surface river/terrain pair terrain={h3_tile} river={h3_water} at {x},{y}")
                out["waterMap"][target_index] = river_mapping["oldenId"]
    out["nativeOceanBasinGeometry"] = apply_native_ocean_basin_geometry(out, OLDEN_WIDTH, OLDEN_HEIGHT)
    return out



def is_display_water_tile_code(tile_code: Any) -> bool:
    return isinstance(tile_code, int) and tile_code in DISPLAY_WATER_TILE_CODES



def source_ocean_shore_edges(surface_map_data: dict[str, Any], x: int, y: int) -> list[str]:
    edges: list[str] = []
    for (dx, dy), edge in SOURCE_ADJACENCY_TO_OLDEN_SHORE_EDGE.items():
        adjacent_x = x + dx
        adjacent_y = y + dy
        if not (0 <= adjacent_x < SOURCE_WIDTH and 0 <= adjacent_y < SOURCE_HEIGHT):
            continue
        adjacent_index = adjacent_y * SOURCE_WIDTH + adjacent_x
        if surface_map_data["tilesMap"][adjacent_index] != 8:
            edges.append(edge)
    return edges



def project_ocean_tile_code(surface_map_data: dict[str, Any], x: int, y: int) -> int:
    edges = source_ocean_shore_edges(surface_map_data, x, y)
    for edge in SHORELINE_WATER_EDGE_PRIORITY:
        if edge in edges:
            return DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE[edge]
    return DISPLAY_WATER_TILE_CODE



def is_source_ocean_cell(surface_map_data: dict[str, Any], x: int, y: int) -> bool:
    if not (0 <= x < SOURCE_WIDTH and 0 <= y < SOURCE_HEIGHT):
        return False
    index = y * SOURCE_WIDTH + x
    return surface_map_data["tilesMap"][index] == 8 and surface_map_data["waterMap"][index] == 0


def is_land_side_ocean_edge_cell(surface_map_data: dict[str, Any], x: int, y: int) -> bool:
    if not (0 <= x < SOURCE_WIDTH and 0 <= y < SOURCE_HEIGHT):
        return False
    index = y * SOURCE_WIDTH + x
    if surface_map_data["tilesMap"][index] == 8 or surface_map_data["waterMap"][index] != 0:
        return False
    return any(is_source_ocean_cell(surface_map_data, x + dx, y + dy) for dx, dy in SHORELINE_RIVER_DIRECTION_BITS)


def source_ocean_edge_nodes(surface_map_data: dict[str, Any]) -> list[int]:
    nodes: list[int] = []
    for y in range(SOURCE_HEIGHT):
        for x in range(SOURCE_WIDTH):
            if is_land_side_ocean_edge_cell(surface_map_data, x, y):
                nodes.append(target_node(x, y))
    return nodes


def shoreline_river_shape(node: int, shoreline_nodes: set[int]) -> int:
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    shape = 0
    for (dx, dy), bit in SHORELINE_RIVER_DIRECTION_BITS.items():
        adjacent = (y + dy) * OLDEN_WIDTH + x + dx
        if 0 <= x + dx < OLDEN_WIDTH and 0 <= y + dy < OLDEN_HEIGHT and adjacent in shoreline_nodes:
            shape |= bit
    return shape


def build_ocean_shoreline_rivers(surface_map_data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    retired_land_edge_nodes = source_ocean_edge_nodes(surface_map_data)
    # Native maps keep one RiverData seed row (sid "test", empty nodes). Empty rivers
    # breaks Map Editor object panels (River '' / BhOwnerView NRE). Shoreline geometry
    # stays retired — display-water tiles own the visual shoreline.
    rivers = [
        {
            "sid": SHORELINE_RIVER_SID,
            "randomSeed": SHORELINE_RIVER_RANDOM_SEED,
            "nodes": [],
        }
    ]
    summary = {
        "status": "retired_replaced_by_display_water_shoreline_tiles",
        "retiredSid": SHORELINE_RIVER_SID,
        "retiredRandomSeed": SHORELINE_RIVER_RANDOM_SEED,
        "replacement": SHORELINE_WATER_TILE_POLICY,
        "riverNodeCount": 0,
        "retiredRiverNodeCount": len(retired_land_edge_nodes),
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains unvalidated",
    }
    return rivers, summary


def classify_homm3_water_intent(h3_tile: int, h3_water: int) -> str | None:
    if h3_tile == 8 and h3_water == 0:
        return "ocean_terrain"
    if h3_water != 0:
        return "river_overlay"
    return None


def summarize_display_water_projection(surface_map_data: dict[str, Any], projected: dict[str, list[int]]) -> dict[str, Any]:
    source_pair_histogram: Counter[str] = Counter()
    native_pair_histogram: Counter[str] = Counter()
    kind_histogram: Counter[str] = Counter()
    ocean_nodes: list[int] = []
    ocean_deep_nodes: list[int] = []
    ocean_shore_nodes: list[int] = []
    shoreline_tile_histogram: Counter[int] = Counter()
    for source_y in range(SOURCE_HEIGHT):
        for source_x in range(SOURCE_WIDTH):
            source_index = source_y * SOURCE_WIDTH + source_x
            h3_tile = surface_map_data["tilesMap"][source_index]
            h3_water = surface_map_data["waterMap"][source_index]
            kind = classify_homm3_water_intent(h3_tile, h3_water)
            if kind is None:
                continue
            node = target_node(source_x, source_y)
            native_tile = projected["tilesMap"][node]
            native_water = projected["waterMap"][node]
            source_pair_histogram[f"{h3_tile}:{h3_water}"] += 1
            native_pair_histogram[f"{native_tile}:{native_water}"] += 1
            kind_histogram[kind] += 1
            if kind == "ocean_terrain":
                if not is_display_water_tile_code(native_tile) or native_water != VANILLA_OCEAN_WATER_ID:
                    raise ValueError(
                        f"HoMM3 ocean source {source_x},{source_y} did not project to a registered display water tile "
                        f"with vanilla ocean waterMap id {VANILLA_OCEAN_WATER_ID}")
                ocean_nodes.append(node)
                if native_tile == NATIVE_WATER_TILE_CODE:
                    ocean_deep_nodes.append(node)
                else:
                    ocean_shore_nodes.append(node)
                    shoreline_tile_histogram[native_tile] += 1
    return {
        "status": DISPLAY_WATER_STATUS,
        "architecture": DISPLAY_WATER_ARCHITECTURE,
        "terrainTileCode": DISPLAY_WATER_TILE_CODE,
        "waterTileCodes": list(DISPLAY_WATER_TILE_CODES),
        "deepWaterTileCode": DISPLAY_WATER_TILE_CODE,
        "shorelineTileCodesByEdge": dict(DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE),
        "visualMaterialDonorTileId": DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE,
        "vanillaOceanWaterMapId": VANILLA_OCEAN_WATER_ID,
        "behaviorDonorTileId": DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE,
        "behaviorDonorBiome": DISPLAY_WATER_BEHAVIOR_DONOR_BIOME,
        "shorelineTileStatus": SHORELINE_WATER_TILE_STATUS,
        "shorelineSelectionPolicy": SHORELINE_WATER_TILE_POLICY,
        "runtimeGate": "Homecoming ocean cells emit native vanilla water terrain tile ids 18-22 with MapData.waterMap id 18; Homm3HomecomingWaterTraversalBridge supplies hero-start relief and boat visuals",
        "oceanNodeCount": len(ocean_nodes),
        "oceanDeepNodeCount": len(ocean_deep_nodes),
        "oceanShoreNodeCount": len(ocean_shore_nodes),
        "shorelineTileHistogram": {str(tile): count for tile, count in sorted(shoreline_tile_histogram.items())},
        "kindHistogram": dict(sorted(kind_histogram.items())),
        "sourceTerrainWaterPairHistogram": dict(sorted(source_pair_histogram.items())),
        "nativeTileWaterPairHistogram": dict(sorted(native_pair_histogram.items())),
        "nativeOceanBasinGeometry": projected.get("nativeOceanBasinGeometry"),
        "tileConfig": {
            "status": DISPLAY_WATER_STATUS,
            "architecture": DISPLAY_WATER_ARCHITECTURE,
            "member": WATER_TILE_PENALTY_MEMBER,
            "tileIds": list(NATIVE_WATER_TILE_CODES),
            "deepWaterTileId": NATIVE_WATER_TILE_CODE,
            "shorelineTileIdsByEdge": dict(NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE),
            "visualMaterialDonorTileId": DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE,
            "vanillaOceanWaterMapId": VANILLA_OCEAN_WATER_ID,
            "behaviorDonorTileId": DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE,
            "behaviorDonorBiome": DISPLAY_WATER_BEHAVIOR_DONOR_BIOME,
            "penalty": NATIVE_WATER_TERRAIN_PENALTY,
            "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
            "displayIntent": "ocean uses unmodified Core.zip water tile rows 18-22 plus vanilla waterMap overlay id 18",
            "knownLimit": "runtime visual quality and boat pickup remain user-unvalidated until in-game retest",
        },
        "waterMapOverlay": {
            "status": DISPLAY_WATER_STATUS,
            "architecture": "vanilla_watermap_ocean_overlay",
            "waterMapId": VANILLA_OCEAN_WATER_ID,
            "tileIds": list(DISPLAY_WATER_TILE_CODES),
            "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
        },
        "visualMaterialAlias": {
            "status": "retired_display_water_sand_alias_replaced_by_native_vanilla_water_tiles",
            "architecture": "native_vanilla_water_tiles_no_custom_biome_alias",
            "tileIds": list(NATIVE_WATER_TILE_CODES),
            "deepWaterTileId": NATIVE_WATER_TILE_CODE,
            "shorelineTileIdsByEdge": dict(NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE),
            "proofBoundary": "custom biome rows 24-28 are retired; ocean no longer emits those tile codes",
        },
    }


def is_node_in_source_envelope(node: int) -> bool:
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    return SOURCE_OFFSET_X <= x < SOURCE_OFFSET_X + SOURCE_WIDTH and SOURCE_OFFSET_Y <= y < SOURCE_OFFSET_Y + SOURCE_HEIGHT


def is_boat_water_intent(projected: dict[str, list[int]], node: int) -> bool:
    return is_node_in_source_envelope(node) and is_display_water_tile_code(projected["tilesMap"][node])


def has_boat_shore_approach(projected: dict[str, list[int]], node: int, occupied: set[int]) -> bool:
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            ax = x + dx
            ay = y + dy
            if not (0 <= ax < OLDEN_WIDTH and 0 <= ay < OLDEN_HEIGHT):
                continue
            adjacent = ay * OLDEN_WIDTH + ax
            if adjacent in occupied or not is_node_in_source_envelope(adjacent):
                continue
            if not is_display_water_tile_code(projected["tilesMap"][adjacent]):
                return True
    return False


def nearest_non_boat_object_distance(node: int, occupied: set[int]) -> int | None:
    if not occupied:
        return None
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    return min(abs(x - (other % OLDEN_WIDTH)) + abs(y - (other // OLDEN_WIDTH)) for other in occupied)



def find_nearest_valid_boat_node(projected: dict[str, list[int]], original_node: int, occupied: set[int], used_boat_nodes: set[int]) -> int:
    if (
        original_node not in used_boat_nodes
        and is_boat_water_intent(projected, original_node)
        and has_boat_shore_approach(projected, original_node, occupied)
    ):
        return original_node
    origin_x = original_node % OLDEN_WIDTH
    origin_y = original_node // OLDEN_WIDTH
    candidates: list[tuple[int, int, int, int, int]] = []
    for node in range(OLDEN_WIDTH * OLDEN_HEIGHT):
        if node in occupied or node in used_boat_nodes:
            continue
        if not is_boat_water_intent(projected, node):
            continue
        if not has_boat_shore_approach(projected, node, occupied):
            continue
        x = node % OLDEN_WIDTH
        y = node // OLDEN_WIDTH
        object_distance = nearest_non_boat_object_distance(node, occupied) or OLDEN_WIDTH + OLDEN_HEIGHT
        candidates.append((abs(x - origin_x) + abs(y - origin_y), -object_distance, abs(x - origin_x), abs(y - origin_y), node))
    if not candidates:
        raise ValueError(f"no valid Homecoming tile-18 water anchor with land-side shore approach near node {original_node}")
    return min(candidates)[4]

def adjust_homm3_boat_placements(objects: list[dict[str, Any]], projected: dict[str, list[int]]) -> list[dict[str, Any]]:
    occupied = {
        int(node)
        for group in objects
        if group.get("sid") != HOMM3_BOAT_SID
        for node in group.get("nodes", [])
        if isinstance(node, int)
    }
    adjustments: list[dict[str, Any]] = []
    used_boat_nodes: set[int] = set()
    for group in objects:
        if group.get("sid") != HOMM3_BOAT_SID:
            continue
        nodes = group.get("nodes")
        ids = group.get("ids") or []
        if not isinstance(nodes, list):
            raise ValueError("homm3_boat object group has no nodes list")
        for index, original_node in enumerate(list(nodes)):
            if not isinstance(original_node, int):
                raise ValueError(f"homm3_boat node is not an integer: {original_node!r}")
            replacement_node = find_nearest_valid_boat_node(projected, original_node, occupied, used_boat_nodes)
            used_boat_nodes.add(replacement_node)
            if replacement_node != original_node:
                nodes[index] = replacement_node
                adjustments.append({
                    "id": ids[index] if index < len(ids) else None,
                    "fromNode": original_node,
                    "toNode": replacement_node,
                    "fromX": original_node % OLDEN_WIDTH,
                    "fromY": original_node // OLDEN_WIDTH,
                    "toX": replacement_node % OLDEN_WIDTH,
                    "toY": replacement_node // OLDEN_WIDTH,
                    "nearestNonBoatObjectDistance": nearest_non_boat_object_distance(replacement_node, occupied),
                    "reason": "nearest_water_intent_with_source_envelope_land_approach",
                })
    return adjustments

def remove_object_groups_by_sid(objects: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    removed = [group for group in objects if isinstance(group, dict) and group.get("sid") == sid]
    objects[:] = [group for group in objects if not (isinstance(group, dict) and group.get("sid") == sid)]
    return removed


def adjacent_nodes_8(node: int) -> list[int]:
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    out: list[int] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            ax = x + dx
            ay = y + dy
            if 0 <= ax < OLDEN_WIDTH and 0 <= ay < OLDEN_HEIGHT:
                out.append(ay * OLDEN_WIDTH + ax)
    return out


def manhattan_distance(left: int, right: int) -> int:
    return abs((left % OLDEN_WIDTH) - (right % OLDEN_WIDTH)) + abs((left // OLDEN_WIDTH) - (right // OLDEN_WIDTH))



def remove_retired_water_layer_outputs() -> None:
    for path in (RETIRED_WATER_LAYER_ARTIFACT_PATH, RETIRED_WATER_LAYER_RUNTIME_SOURCE_PATH):
        if path.exists():
            path.unlink()
    for directory in (RETIRED_WATER_LAYER_ARTIFACT_PATH.parent, RETIRED_WATER_LAYER_RUNTIME_SOURCE_PATH.parent):
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()


def build_substitution_lookup(substitution: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup = {}
    for entry in substitution.get("invalidEntitySubstitutions", []):
        signature = entry.get("sourceSignature")
        if not isinstance(signature, str):
            raise ValueError(f"substitution entry missing sourceSignature: {entry}")
        if signature in lookup:
            raise ValueError(f"duplicate substitution sourceSignature: {signature}")
        overrides = entry.get("placementOverrides")
        if overrides is not None:
            if not isinstance(overrides, list):
                raise ValueError(f"substitution placementOverrides must be a list for {signature}")
            by_source_index = {}
            for override in overrides:
                if not isinstance(override, dict) or not isinstance(override.get("sourceIndex"), int):
                    raise ValueError(f"invalid placement override for {signature}: {override}")
                source_index = override["sourceIndex"]
                if source_index in by_source_index:
                    raise ValueError(f"duplicate placement override sourceIndex for {signature}: {source_index}")
                by_source_index[source_index] = override
            entry = {**entry, "placementOverridesBySourceIndex": by_source_index}
        lookup[signature] = entry
    return lookup


def resolve_replacement_sid(entity: dict[str, Any], substitution_lookup: dict[str, dict[str, Any]], valid_ids: set[str]) -> tuple[str | None, str, str]:
    import build_homecoming_entity_substitution_map as sub_mod

    signature = signature_for(entity)
    source_sid = entity.get("sid")
    if source_sid in valid_ids:
        return str(source_sid), "already_valid", "direct_or_family_substitution"
    sub = substitution_lookup.get(signature)
    if sub is None:
        raise ValueError(f"missing substitution for {signature}")
    if sub.get("placementOverridesRequired") is True:
        source_index = entity.get("sourceIndex")
        overrides = sub.get("placementOverridesBySourceIndex")
        if not isinstance(source_index, int) or not isinstance(overrides, dict) or source_index not in overrides:
            raise ValueError(f"missing required placement override for {signature} sourceIndex={source_index}")
        sub = overrides[source_index]
    replacement_sid = sub.get("replacementSid")
    if replacement_sid is None:
        return None, str(sub.get("ruleName")), str(sub.get("lossiness"))
    if not isinstance(replacement_sid, str):
        raise ValueError(f"substitution replacement is not a string or blocked null for {signature}: {replacement_sid}")
    # Scenery size from HoMM3 block-mask solid-square subset (not canonical SID size).
    role = sub_mod.terrain_role_for_row(entity)
    if role in {"mountain", "tree", "pool", "pool_big"}:
        evidence = sub.get("evidence") if isinstance(sub.get("evidence"), dict) else {}
        biome = evidence.get("dominantBiome") or evidence.get("biome")
        if not isinstance(biome, str):
            biome = "grass"
        blocks = entity_blocked_mask_offsets(entity)
        footprint_cells, _footprint_evidence = sub_mod.scenery_footprint_cells_from_homm3_blocks(
            role,
            biome,
            blocks,
            valid_ids,
        )
        if footprint_cells is not None:
            node = int(entity.get("sourceIndex") or 0)
            variant = sub_mod.choose_scenery_variant(
                role,
                biome,
                footprint_cells,
                valid_ids,
                seed_key=str(entity.get("sourceKey") or signature),
                node=node,
            )
            if variant:
                return variant, f"{sub.get('ruleName')}_homm3_solid_square_variant", str(sub.get("lossiness"))
        if role in {"mountain", "tree"}:
            node = int(entity.get("sourceIndex") or 0)
            replacement_sid = sub_mod.ensure_mountain_tree_sid_fits_homm3_block_mask(
                replacement_sid,
                role,
                biome,
                blocks,
                valid_ids,
                seed_key=str(entity.get("sourceKey") or signature),
                node=node,
            )
    return replacement_sid, str(sub.get("ruleName")), str(sub.get("lossiness"))



H3M_MASK_WIDTH = 8
H3M_MASK_HEIGHT = 6
H3M_MASK_ANCHOR_X = 7
H3M_MASK_ANCHOR_Y = 5
GUARDED_SOURCE_MASK_PROJECTION = "vcmi_h3m_8x6_bottom_right_visit_tile_static_contract"
GUARDED_SOURCE_GUARD_MODEL = "vcmi_guardingCreaturePosition_same_or_adjacent_visit_tile_static_contract"
GUARDED_PLACEMENT_POLICY = "disabled_preserve_source_anchors"
GUARDED_PLACEMENT_STATUS = "disabled_user_requested_source_anchor_preservation_runtime_unvalidated"
GUARDED_PLACEMENT_DISABLED_REASON = "guard_to_native_gate_relocation_can_break_source_topography_assumptions"
SOURCE_ANCHOR_COMPOSITION_POLICY = "source_footprint_anchor_suppress_approximate_scenery_on_exact_native_anchor_collision"
SOURCE_MASK_ROTATION_ALIGNMENT_POLICY = "h3m_visit_and_block_masks_choose_olden_mirror_rotation_for_interactable_structures"
SOURCE_MASK_ROTATION_ALIGNMENT_STATUS = "generated_artifact_validated_runtime_unvalidated"
SOURCE_ANCHOR_NODE_ALIGNMENT_POLICY = (
    "h3m_bottom_right_anchor_to_olden_native_footprint_anchor;"
    "landon_gate_aligned_to_h3_visit"
)
SOURCE_ANCHOR_NODE_ALIGNMENT_STATUS = "generated_artifact_deployed_user_visible_validated"
SOURCE_ANCHOR_POINT_FOOTPRINT_SOURCES = {
    "explicit_point_anchor_without_native_footprint",
    "native_nodes_no_occupied_footprint_anchor",
}
USER_VISIBLE_VALIDATION = {
    "status": "user_visible_object_placement_validated",
    "date": "2026-07-04",
    "source": "manual Golden Era runtime test reported by user after deployment",
    "scope": (
        "Homecoming single-layer map load and source-footprint object placement, including the "
        "sawmill/lumbermill cluster and multi-tile footprint alignment"
    ),
    "notCovered": [
        "source layer 1 / underground translation",
        "water traversal gameplay",
        "remaining lossy substitutions and object mechanics not exercised by the placement test",
    ],
}
POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS = {
    "dirt_stones_1",
    "dirt_stones_2",
    "flowers_1",
    "flowers_2",
    "fx_map_light",
    "fx_quest_mark_gold_01",
    "fx_quest_mark_silver_01",
    "grass_1",
    "grass_2",
    "grass_snow_1",
    "grass_snow_2",
    "grass_stones_1",
    "grass_stones_2",
    "lava_stones_1",
    "mushrooms_1",
    "mushrooms_2",
    "mushrooms_3",
    "mushrooms_4",
    "snow_stones_1",
    "snow_stones_2",
    "snow_stones_3",
    "snow_stones_4",
    "water_reed_1",
}
OLDEN_DEFAULT_ROTATION = 0
OLDEN_MIRRORED_ROTATION = 10
VCMI_GUARD_SCAN_OFFSETS = (
    (0, 0),
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)
SOURCE_ANCHOR_PRIORITY_BY_CATEGORY = {
    "town": 1000,
    "hero_or_prison": 950,
    "monster_stack": 900,
    "mine": 850,
    "external_dwelling": 840,
    "interactive_reward_object": 800,
    "artifact_pickup": 760,
    "resource_pickup": 720,
    "map_event": 650,
    "interactive_quest_object": 640,
    "readable_sign_or_bottle": 635,
    "travel_link_candidate": 630,
    "boat_or_water_travel_object": 600,
    "payloadless_object_unclassified_for_current_scope": 500,
}
# Canonical set lives in functional_emit_reservation (MiniLM-free shared emit module).
SUPPRESSIBLE_SOURCE_SCENERY_SIDS = functional_emit_reservation.SUPPRESSIBLE_SOURCE_SCENERY_SIDS
def h3m_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int):
            raise ValueError(f"H3M object mask byte is not an integer: {raw!r}")
        if raw < 0 or raw > 255:
            raise ValueError(f"H3M object mask byte outside 0..255: {raw!r}")
        for col_index in range(H3M_MASK_WIDTH):
            if raw & (1 << col_index):
                # VCMI stores H3M template mask bits relative to the object's bottom-right anchor:
                # usedTiles[5 - row][7 - col]. Keep this source projection explicit.
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def h3m_visit_nodes(entity: dict[str, Any]) -> set[tuple[int, int]]:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        return set()
    return {(source_x + dx, source_y + dy) for dx, dy in h3m_mask_offsets(entity.get("templateVisitMask"))}



def source_visit_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return h3m_mask_offsets(entity.get("templateVisitMask"))


def source_block_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
  # VCMI ObjectTemplate::readMap treats blockMask bit 0 as blocked; visitMask bit 1 as visitable.
    return h3m_blocked_mask_offsets(entity.get("templateBlockMask"))


def derive_source_mask_rotation(entity: dict[str, Any], native_config: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    source_rotation = int(entity.get("rotation") or 0)
    evidence: dict[str, Any] = {
        "policy": SOURCE_MASK_ROTATION_ALIGNMENT_POLICY,
        "sourceRotation": source_rotation,
        "rotation": source_rotation,
        "reason": "native_object_not_mirrorable_or_not_structure_like",
    }
    if native_config.get("canBeMirrored") is not True or not isinstance(native_config.get("generatorConfig"), dict):
        return source_rotation, evidence
    visits = source_visit_offsets(entity)
    blocks = source_block_offsets(entity)
    if len(visits) != 1 or not blocks:
        evidence["reason"] = "source_visit_or_block_mask_ambiguous"
        evidence["sourceVisitOffsetCount"] = len(visits)
        evidence["sourceBlockOffsetCount"] = len(blocks)
        return source_rotation, evidence
    visit_dx, visit_dy = next(iter(visits))
    if (visit_dx, visit_dy) == (0, 0):
        reference_dx, reference_dy = visit_dx, visit_dy
        reference_kind = "source_visit_tile"
    else:
        reference_dx, reference_dy = 0, 0
        reference_kind = "h3m_anchor_when_visit_tile_differs_from_anchor"
    relative_x = [dx - reference_dx for dx, _dy in blocks]
    relative_y_olden = [-(dy - reference_dy) for _dx, dy in blocks]
    min_dx = min(relative_x)
    max_dx = max(relative_x)
    avg_dx = sum(relative_x) / len(relative_x)
    min_dy = min(relative_y_olden)
    max_dy = max(relative_y_olden)
    evidence.update({
        "reason": "source_mask_footprint_relative_to_reference",
        "sourceVisitOffset": [visit_dx, visit_dy],
        "sourceFootprintReference": reference_kind,
        "sourceFootprintReferenceOffset": [reference_dx, reference_dy],
        "sourceBlockOffsetCount": len(blocks),
        "sourceOldenRelativeBounds": {"minDx": min_dx, "maxDx": max_dx, "minDy": min_dy, "maxDy": max_dy},
        "sourceOldenRelativeAverageDx": avg_dx,
    })
    if max_dx <= 0 and avg_dx < -0.25:
        evidence["rotation"] = OLDEN_MIRRORED_ROTATION
        evidence["decision"] = "mirror_olden_structure_so_source_body_lies_left_of_visit_tile"
        return OLDEN_MIRRORED_ROTATION, evidence
    if min_dx >= 0 and avg_dx > 0.25:
        evidence["rotation"] = OLDEN_DEFAULT_ROTATION
        evidence["decision"] = "keep_unmirrored_olden_structure_so_source_body_lies_right_of_visit_tile"
        return OLDEN_DEFAULT_ROTATION, evidence
    evidence["decision"] = "preserve_source_rotation_for_balanced_or_centered_source_footprint"
    return source_rotation, evidence


def target_node_allowing_source_padding(source_x: int, source_y: int) -> int:
    olden_x = source_x + SOURCE_OFFSET_X
    olden_y = SOURCE_HEIGHT - 1 - source_y + SOURCE_OFFSET_Y
    if not (0 <= olden_x < OLDEN_WIDTH and 0 <= olden_y < OLDEN_HEIGHT):
        raise ValueError(f"source-space anchor outside Olden envelope: {source_x},{source_y} -> {olden_x},{olden_y}")
    return olden_y * OLDEN_WIDTH + olden_x


def native_main_footprint(native_config: dict[str, Any], replacement_sid: str) -> dict[str, Any]:
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    nodes = native_config.get("nodes")
    if replacement_sid == HOMM3_LANDON_BARRACKS_CASTLE_1_SID:
        if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
            raise ValueError(f"{replacement_sid} is missing a valid expanded ObjectConfig grid")
        if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
            raise ValueError(f"{replacement_sid} nodes must cover the full {size_x}x{size_z} visit-gate grid")
        if nodes[HOMM3_LANDON_BARRACKS_BOTTOM_CENTER_GATE_INDEX] != 2:
            raise ValueError(
                f"{replacement_sid} must keep bottom-row GATE at index "
                f"{HOMM3_LANDON_BARRACKS_BOTTOM_GATE_INDEX}; nodes={nodes!r}"
            )
        if sum(1 for value in nodes if value == 2) != 1:
            raise ValueError(f"{replacement_sid} must have exactly one GATE cell; nodes={nodes!r}")
        cells = [(index % size_x, index // size_x) for index, value in enumerate(nodes) if value == 1]
        if not cells:
            raise ValueError(f"{replacement_sid} bottom-center GATE clone needs occupied value-1 cells")
        xs = [x for x, _z in cells]
        zs = [z for _x, z in cells]
        return {
            "source": "landon_barracks_bottom_center_gate_occupied_bounds",
            "width": max(xs) - min(xs) + 1,
            "height": max(zs) - min(zs) + 1,
            "minX": min(xs),
            "minZ": min(zs),
            "cellCount": len(cells),
        }
    if replacement_sid in HOMM3_LANDON_BARRACKS_SIDS:
        if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
            raise ValueError(f"{replacement_sid} is missing a valid ObjectConfig grid")
        if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
            raise ValueError(f"{replacement_sid} nodes must cover the full {size_x}x{size_z} visit-gate grid")
        if nodes[HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX] != 2:
            raise ValueError(
                f"{replacement_sid} must keep bottom-center GATE at index "
                f"{HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX}; nodes={nodes!r}"
            )
        if sum(1 for value in nodes if value == 2) != 1:
            raise ValueError(f"{replacement_sid} must have exactly one GATE cell; nodes={nodes!r}")
        cells = [(index % size_x, index // size_x) for index, value in enumerate(nodes) if value == 1]
        if not cells:
            raise ValueError(f"{replacement_sid} bottom-center GATE clone needs occupied value-1 cells")
        xs = [x for x, _z in cells]
        zs = [z for _x, z in cells]
        return {
            "source": "landon_barracks_bottom_center_gate_occupied_bounds",
            "width": max(xs) - min(xs) + 1,
            "height": max(zs) - min(zs) + 1,
            "minX": min(xs),
            "minZ": min(zs),
            "cellCount": len(cells),
        }
    if isinstance(size_x, int) and isinstance(size_z, int) and isinstance(nodes, list) and len(nodes) == size_x * size_z:
        cells = [(index % size_x, index // size_x) for index, value in enumerate(nodes) if value == 1]
        if cells:
            xs = [x for x, _z in cells]
            zs = [z for _x, z in cells]
            return {
                "source": "native_nodes_value_1_bounds",
                "width": max(xs) - min(xs) + 1,
                "height": max(zs) - min(zs) + 1,
                "minX": min(xs),
                "minZ": min(zs),
                "cellCount": len(cells),
            }
        return {"source": "native_nodes_no_occupied_footprint_anchor", "width": 1, "height": 1, "minX": None, "minZ": None, "cellCount": 0}
    generator_config = native_config.get("generatorConfig")
    if isinstance(generator_config, dict):
        building_size_x = generator_config.get("buildingSizeX")
        building_size_z = generator_config.get("buildingSizeZ")
        if isinstance(building_size_x, int) and isinstance(building_size_z, int):
            return {
                "source": "native_generator_building_size",
                "width": building_size_x,
                "height": building_size_z,
                "minX": None,
                "minZ": None,
                "cellCount": None,
            }
    if replacement_sid in POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS:
        return {"source": "explicit_point_anchor_without_native_footprint", "width": 1, "height": 1, "minX": None, "minZ": None, "cellCount": None}
    raise ValueError(f"native object config for {replacement_sid} has no occupied footprint metadata and is not an explicit point-anchor SID")


def landon_single_gate_local_cell(native_config: dict[str, Any], replacement_sid: str) -> tuple[int, int, int, int]:
    """Return (gate_x, gate_z, size_x, size_z) for GATE-align.

    Land-on SIDs require exactly one GATE. Scorched subterranean portal uses
    prefer_gate_local when multiple GATE markers are present.
    """
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    nodes = native_config.get("nodes")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        raise ValueError(f"{replacement_sid} missing sizeX/sizeZ for GATE alignment")
    if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
        raise ValueError(f"{replacement_sid} nodes must cover {size_x}x{size_z} for GATE alignment")
    gate_indices = [index for index, value in enumerate(nodes) if value == 2]
    if len(gate_indices) == 1:
        gate_index = gate_indices[0]
    elif replacement_sid == HOMM3_SUBTERRANEAN_GATE_PORTAL_SID and len(gate_indices) > 1:
        preferred_x = size_x // 2
        preferred_z = size_z - 1
        preferred_index = preferred_z * size_x + preferred_x
        if preferred_index not in gate_indices:
            raise ValueError(
                f"{replacement_sid} preferred GATE local ({preferred_x},{preferred_z}) "
                f"missing from nodes={nodes!r}"
            )
        gate_index = preferred_index
    else:
        raise ValueError(f"{replacement_sid} must have exactly one GATE for land-on alignment; nodes={nodes!r}")
    return gate_index % size_x, gate_index // size_x, size_x, size_z


def derive_landon_gate_aligned_node(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    *,
    rotation: int,
    default_node: int,
    reason: str = "landon_single_gate_coincides_with_source_visit_cell",
) -> tuple[int, dict[str, Any]]:
    """Place ObjectConfig so its single GATE cell coincides with the HoMM3 visit cell.

    Land-on policy is visit-the-GATE. ObjectConfig high config_z is building-bottom =
    map-south, so grid_y = anchor_y + (size_z - 1 - config_z) and
    anchor_y = visit_y - (size_z - 1 - gate_z). Native bottom GATE keeps the town body
    inland (north of the visit cell). Fail closed on ambiguous multi-visit masks.
    """
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        raise ValueError(f"cannot GATE-align without source coordinates: {entity.get('sourceKey')}")
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) > 1:
        raise ValueError(
            f"{replacement_sid} GATE alignment requires exactly one HoMM3 visit cell for "
            f"{entity.get('sourceKey')}; got {sorted(visit_nodes)}"
        )
    visit_node = next(iter(visit_nodes)) if visit_nodes else default_node
    gate_x, gate_z, size_x, size_z = landon_single_gate_local_cell(native_config, replacement_sid)
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and native_config.get("canBeMirrored") is True
    placed_dx = size_x - 1 - gate_x if mirrored else gate_x
    visit_x = visit_node % OLDEN_WIDTH
    visit_y = visit_node // OLDEN_WIDTH
    anchor_x = visit_x - placed_dx
    anchor_y = visit_y - (size_z - 1 - gate_z)
    if not (0 <= anchor_x < OLDEN_WIDTH and 0 <= anchor_y < OLDEN_HEIGHT):
        raise ValueError(
            f"{replacement_sid} GATE-aligned anchor out of bounds for {entity.get('sourceKey')}: "
            f"({anchor_x},{anchor_y}) visit={visit_node} gateLocal=({gate_x},{gate_z}) mirrored={mirrored}"
        )
    node = anchor_y * OLDEN_WIDTH + anchor_x
    gate_nodes = nodes_for_object_instance_with_value(
        replacement_sid, native_config, node, rotation, node_value=2
    )
    if visit_node not in gate_nodes:
        raise ValueError(
            f"{replacement_sid} GATE alignment failed for {entity.get('sourceKey')}: "
            f"visit={visit_node} not in gateNodes={sorted(gate_nodes)} "
            f"(emitNode={node}, rotation={rotation})"
        )
    footprint = native_main_footprint(native_config, replacement_sid)
    evidence = {
        "policy": "landon_gate_aligned_to_h3_visit",
        "reason": reason,
        "decision": "align_olden_node_so_gate_equals_h3_visit",
        "sourceAnchor": [source_x, source_y],
        "sourceFootprintAnchor": None,
        "nativeFootprint": {
            **footprint,
            "source": "landon_gate_aligned_to_h3_visit",
            "gateLocal": [gate_x, gate_z],
            "placedDx": placed_dx,
            "mirrored": mirrored,
        },
        "node": node,
        "nodeDelta": [anchor_x - (default_node % OLDEN_WIDTH), anchor_y - (default_node // OLDEN_WIDTH)],
        "visitNode": visit_node,
        "gateNodes": sorted(gate_nodes),
        "sourceAnchorNode": default_node,
    }
    return node, evidence


def _br_visit_buried_in_own_occupied(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    br_node: int,
    rotation: int,
) -> bool:
    """True when BR placement leaves the unique H3 visit on this object's occupied cells, not GATE.

    That is inaccessible under Olden stand-to-interact rules and is the only non-land-on
    case allowed to use GATE→visit alignment (avoids casually shifting blockers / opening paths).
    """
    nodes = native_config.get("nodes")
    if not isinstance(nodes, list) or sum(1 for value in nodes if value == 2) != 1:
        return False
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) != 1:
        return False
    visit_node = next(iter(visit_nodes))
    gate_nodes = nodes_for_object_instance_with_value(
        replacement_sid, native_config, br_node, rotation, node_value=2
    )
    if visit_node in gate_nodes:
        return False
    occupied = occupied_nodes_for_object_instance(replacement_sid, native_config, br_node, rotation)
    return visit_node in occupied


def derive_source_anchor_node(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    default_node: int,
    *,
    rotation: int | None = None,
) -> tuple[int, dict[str, Any]]:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        raise ValueError(f"cannot align source anchor without source coordinates: {entity.get('sourceKey')}")

    rot = int(rotation if rotation is not None else 0)

    # Town / city SIDs:
    # - stock / non-landon: GATE == one north of H3 visit (courtyard open)
    # - landon cities: 3x3 center == one north of H3 body center
    if town_gate_align.is_town_city_sid(replacement_sid):
        visit_nodes = entity_visit_nodes(entity)
        if len(visit_nodes) != 1:
            raise ValueError(
                f"town SID {replacement_sid} for {entity.get('sourceKey')} "
                f"requires exactly one HoMM3 visit cell; found {sorted(visit_nodes)}"
            )
        body_center_node = None
        if town_gate_align.is_landon_city_sid(replacement_sid):
            body_sx, body_sy = town_gate_align.town_body_center_source_xy(entity)
            body_center_node = target_node_allowing_source_padding(body_sx, body_sy)
        return town_gate_align.align_town_emit_node(
            entity=entity,
            replacement_sid=replacement_sid,
            native_config=native_config,
            visit_node=next(iter(visit_nodes)),
            default_node=default_node,
            grid_width=OLDEN_WIDTH,
            grid_height=OLDEN_HEIGHT,
            rotation=rot,
            body_center_node=body_center_node,
        )

    # Land-on barracks (non-city): GATE cell must equal HoMM3 visit cell (not BR occupied-bounds).
    if (
        replacement_sid in HOMM3_LANDON_OBJECT_SIDS
        and replacement_sid != HOMM3_LANDON_MAP_EVENT_MARKER_SID
        and rotation is not None
    ):
        return derive_landon_gate_aligned_node(
            entity,
            replacement_sid,
            native_config,
            rotation=rotation,
            default_node=default_node,
        )

    if replacement_sid == "hero-spawner":
        visit_nodes = entity_visit_nodes(entity)
        if len(visit_nodes) != 1:
            raise ValueError(
                f"hero-spawner for {entity.get('sourceKey')} requires exactly one HoMM3 "
                f"visit cell; found {sorted(visit_nodes)}"
            )
        return exact_fp.derive_gate_aligned_node(
            visit_node=next(iter(visit_nodes)),
            native_config=native_config,
            footprint=exact_fp.footprint_from_donor_config(native_config),
            grid_width=OLDEN_WIDTH,
            grid_height=OLDEN_HEIGHT,
            default_node=default_node,
            rotation=rot,
            can_be_mirrored=native_config.get("canBeMirrored") is True,
        )

    import build_homecoming_entity_substitution_map as sub_mod

    footprint = native_main_footprint(native_config, replacement_sid)
    width = footprint["width"]
    height = footprint["height"]
    cell_count = footprint.get("cellCount")
    role = sub_mod.terrain_role_for_row(entity)
    # HoMM3 BR → Olden south-west emit. After Z→map flip, high config_z is map-south
    # (building bottom) at anchor_y; footprint extends north. Keep source Y = BR Y.
    #
    # Mountain/tree solid squares may sit away from the entity BR when the HoMM3 mask is
    # irregular; align the Olden occupied square to a solid subset of that mask.
    scenery_square = None
    if (
        role in {"mountain", "tree"}
        and isinstance(width, int)
        and width == height
        and width in {1, 2, 3}
        and isinstance(cell_count, int)
        and cell_count == width * height
    ):
        blocks = source_block_offsets(entity)
        origin = sub_mod.prefer_homm3_block_solid_square(blocks, width)
        if origin is None:
            raise ValueError(
                f"scenery SID {replacement_sid} is solid {width}x{width} but HoMM3 block mask "
                f"for {entity.get('sourceKey')} has no solid {width}x{width} subset "
                f"(cells={len(blocks)})"
            )
        min_dx, min_dy = origin
        br_source_x = source_x + min_dx + width - 1
        br_source_y = source_y + min_dy + width - 1
        anchor_source_x = br_source_x - (width - 1)
        anchor_source_y = br_source_y
        scenery_square = {
            "policy": sub_mod.HOMM3_SCENERY_FOOTPRINT_POLICY,
            "side": width,
            "minDx": min_dx,
            "minDy": min_dy,
            "brSource": [br_source_x, br_source_y],
        }
    else:
        anchor_source_x = source_x - (width - 1)
        anchor_source_y = source_y
    node = target_node_allowing_source_padding(anchor_source_x, anchor_source_y)
    node_x = node % OLDEN_WIDTH
    node_y = node // OLDEN_WIDTH
    default_x = default_node % OLDEN_WIDTH
    default_y = default_node // OLDEN_WIDTH
    changed = node != default_node
    evidence = {
        "policy": SOURCE_ANCHOR_NODE_ALIGNMENT_POLICY,
        "reason": (
            "h3m_block_solid_square_to_olden_native_footprint_anchor"
            if scenery_square is not None and changed
            else "h3m_bottom_right_anchor_to_olden_native_footprint_anchor"
            if changed
            else "native_footprint_single_tile_or_anchor_unchanged"
        ),
        "decision": (
            "align_olden_node_to_homm3_block_solid_square"
            if scenery_square is not None
            else "align_olden_node_to_source_bottom_left_footprint"
            if changed
            else "preserve_source_anchor_for_single_tile_native_footprint"
        ),
        "sourceAnchor": [source_x, source_y],
        "sourceFootprintAnchor": [anchor_source_x, anchor_source_y],
        "nativeFootprint": footprint,
        "homm3ScenerySolidSquare": scenery_square,
        "node": node,
        "nodeDelta": [node_x - default_x, node_y - default_y],
    }

    # Non-land-on: keep BR unless the unique visit is buried in this object's own occupied cells.
    if rotation is not None and _br_visit_buried_in_own_occupied(
        entity, replacement_sid, native_config, node, rotation
    ):
        return derive_landon_gate_aligned_node(
            entity,
            replacement_sid,
            native_config,
            rotation=rotation,
            default_node=default_node,
            reason="non_landon_br_visit_buried_in_own_occupied_gate_align_exception",
        )
    return node, evidence


def guarded_visit_candidates_by_source(entities: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    monsters_by_layer_pos: dict[tuple[int, int, int], dict[str, Any]] = {}
    for entity in entities:
        if entity.get("category") != "monster_stack":
            continue
        source_layer = entity.get("sourceLayer")
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_layer, int) or not isinstance(source_x, int) or not isinstance(source_y, int):
            continue
        key = (source_layer, source_x, source_y)
        previous = monsters_by_layer_pos.get(key)
        if previous is not None:
            raise ValueError(f"multiple source monster stacks share one H3M tile: {previous.get('sourceKey')} and {entity.get('sourceKey')}")
        monsters_by_layer_pos[key] = entity

    guarded: dict[int, list[dict[str, Any]]] = {}
    for entity in entities:
        source_index = entity.get("sourceIndex")
        source_layer = entity.get("sourceLayer")
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if (
            entity.get("category") == "monster_stack"
            or not isinstance(source_index, int)
            or not isinstance(source_layer, int)
            or not isinstance(source_x, int)
            or not isinstance(source_y, int)
        ):
            continue
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int]] = set()
        for visit_x, visit_y in sorted(h3m_visit_nodes(entity)):
            for scan_dx, scan_dy in VCMI_GUARD_SCAN_OFFSETS:
                guard_x = visit_x + scan_dx
                guard_y = visit_y + scan_dy
                guard = monsters_by_layer_pos.get((source_layer, guard_x, guard_y))
                if guard is None:
                    continue
                guard_index = guard.get("sourceIndex")
                if not isinstance(guard_index, int):
                    raise ValueError(f"guard monster source index is not an integer: {guard}")
                dedupe_key = (guard_index, visit_x, visit_y)
                if dedupe_key in seen:
                    break
                seen.add(dedupe_key)
                candidates.append({
                    "dx": visit_x - source_x,
                    "dy": visit_y - source_y,
                    "sourceVisitKey": f"{source_layer}:{visit_x}:{visit_y}",
                    "sourceGuardVector": [guard_x - source_x, guard_y - source_y],
                    "sourceGuardToVisitVector": [visit_x - guard_x, visit_y - guard_y],
                    "sourceGuardAdjacency": "same_tile" if scan_dx == 0 and scan_dy == 0 else "adjacent_tile",
                    "guardSourceIndex": guard_index,
                    "guardSourceKey": guard.get("sourceKey"),
                })
                break
        if candidates:
            guarded[source_index] = candidates
    return guarded


def deterministic_entity_sid(replacement_sid: str, object_id: int) -> str:
    return f"homecoming_{replacement_sid}_{object_id}".replace("-", "_")


RANDOM_SQUAD_STRENGTH_MODEL = read_json(RANDOM_MONSTER_STRENGTH_MODEL_PATH)
H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL = {int(key): int(value) for key, value in RANDOM_SQUAD_STRENGTH_MODEL["nominalH3RandomStackCountsByLevel"].items()}
RANDOM_SQUAD_REQUESTED_VALUE_ROUNDING = float(RANDOM_SQUAD_STRENGTH_MODEL["requestedValueRounding"])
RANDOM_SQUAD_STRENGTH_MODEL_ID = str(RANDOM_SQUAD_STRENGTH_MODEL["model"])
_TIER_MEDIAN_SQUAD_VALUE_CACHE: dict[int, float] | None = None
CONCRETE_MONSTER_UNIT_BY_SUBTYPE = {
    0: "h3_pikeman",
    1: "h3_pikeman_upg",
    2: "h3_archer",
    3: "h3_archer_upg",
    6: "h3_swordsman",
    42: "h3_imp",
    43: "h3_imp_upg",
    44: "h3_gog",
    45: "h3_gog_upg",
    46: "h3_hell_hound",
    47: "h3_hell_hound_upg",
    48: "h3_demon",
    49: "h3_demon_upg",
    50: "h3_pit_fiend",
    70: "h3_troglodyte",
    71: "h3_troglodyte_upg",
    72: "h3_harpy",
    73: "h3_harpy_upg",
    74: "h3_beholder",
    75: "h3_beholder_upg",
}
CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE = {
    0: "AvWPike.def",
    1: "AVWpikx0.def",
    2: "AvWLCrs.def",
    3: "AvWHCrs.def",
    6: "AVWswrd0.def",
    42: "AVWimp0.def",
    43: "AVWimpx0.def",
    44: "AVWgog0.def",
    45: "AVWgogx0.def",
    46: "AVWhoun0.def",
    47: "AVWhoux0.def",
    48: "AVWdemn0.def",
    49: "AVWdemx0.def",
    50: "AVWpitf0.def",
    70: "AVWtrog0.def",
    71: "AvWInfr.def",
    72: "AVWharp0.def",
    73: "AVWharx0.def",
    74: "AVWbehl0.def",
    75: "AVWbehx0.def",
}
if set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE) != set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE):
    raise RuntimeError(
        "CONCRETE_MONSTER_UNIT_BY_SUBTYPE and CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE keys "
        f"must stay in lockstep; unit_only={sorted(set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE) - set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE))} "
        f"anim_only={sorted(set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE) - set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE))}"
    )
INTRO_DIALOG_SID = "homecoming_intro_dialog"
SQUAD_OVERLAY_MEMBER_ROOT = "DB/squads/squads_custom_maps/homecoming"
_UNIT_SQUAD_VALUE_CACHE: dict[str, dict[str, Any]] | None = None


def is_concrete_h3_monster_stack(entity: dict[str, Any]) -> bool:
    subtype = entity.get("templateSubtype")
    return entity.get("templateObjectId") == 54 and subtype in CONCRETE_MONSTER_UNIT_BY_SUBTYPE


def concrete_monster_unit_sid(entity: dict[str, Any]) -> str:
    subtype = entity.get("templateSubtype")
    if subtype not in CONCRETE_MONSTER_UNIT_BY_SUBTYPE:
        raise ValueError(f"unsupported concrete monster subtype for {entity.get('sourceKey')}: {subtype}")
    expected_animation = CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE[subtype]
    if entity.get("templateAnimation") != expected_animation:
        raise ValueError(f"concrete monster subtype/animation mismatch for {entity.get('sourceKey')}: subtype={subtype} animation={entity.get('templateAnimation')} expected={expected_animation}")
    return CONCRETE_MONSTER_UNIT_BY_SUBTYPE[subtype]


def h3_unit_logic_rows() -> dict[str, dict[str, Any]]:
    global _UNIT_SQUAD_VALUE_CACHE
    if _UNIT_SQUAD_VALUE_CACHE is not None:
        return dict(_UNIT_SQUAD_VALUE_CACHE)
    rows: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/units/units_logics/homm3_") and name.endswith("_l.json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if not isinstance(row, dict):
                    continue
                unit_id = row.get("id")
                if isinstance(unit_id, str) and unit_id.startswith("h3_"):
                    rows[unit_id] = row
    if not rows:
        raise ValueError("Core.zip contains no h3_ unit logic rows")
    _UNIT_SQUAD_VALUE_CACHE = rows
    return dict(rows)


def concrete_monster_unit_squad_value(entity: dict[str, Any]) -> float:
    unit_sid = concrete_monster_unit_sid(entity)
    row = h3_unit_logic_rows().get(unit_sid)
    if not isinstance(row, dict):
        raise ValueError(f"missing Core unit logic for concrete monster {unit_sid} at {entity.get('sourceKey')}")
    squad_value = row.get("squadValue")
    if not isinstance(squad_value, (int, float)) or float(squad_value) <= 0:
        raise ValueError(f"invalid squadValue for {unit_sid}: {squad_value!r}")
    return float(squad_value)


def concrete_monster_unit_tier(entity: dict[str, Any]) -> int:
    unit_sid = concrete_monster_unit_sid(entity)
    row = h3_unit_logic_rows().get(unit_sid)
    if not isinstance(row, dict):
        raise ValueError(f"missing Core unit logic for concrete monster {unit_sid} at {entity.get('sourceKey')}")
    tier = row.get("tier")
    if not isinstance(tier, int) or tier not in H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL:
        raise ValueError(f"invalid tier for {unit_sid}: {tier!r}")
    return tier


def concrete_monster_count(entity: dict[str, Any]) -> int:
    """H3 creature count. count==0 uses nominal-by-tier CRTRAITS guideline (not literal 1)."""
    count = entity.get("count")
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"unsupported concrete monster count for {entity.get('sourceKey')}: {count}")
    if count > 0:
        return count
    return H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL[concrete_monster_unit_tier(entity)]


def concrete_monster_squad_sid(entity: dict[str, Any]) -> str:
    return f"homecoming_{concrete_monster_unit_sid(entity)}_x{concrete_monster_count(entity)}"


def concrete_monster_requested_value(entity: dict[str, Any]) -> float:
    """Olden value budget = H3 creature count × unit squadValue (difficulty scales at runtime)."""
    return rounded_requested_value(concrete_monster_count(entity) * concrete_monster_unit_squad_value(entity))


def concrete_monster_reaction_type(entity: dict[str, Any]) -> int:
    """Map HoMM3 monster character to Olden propRandomSquads.reactionType.

    Native free-join rows use reactionType 4 with isFreeDiplomacy. Index 5 in
    diplomacy_info.reactionTypeModifiers is a hard-zero modifier, not "always join".
    """

    character = entity.get("character")
    if character == 0:
        return 4  # compliant / recruitable — native free-join family
    if character == 1:
        # Friendly is not free-join until a native Olden contract is proven. Keep
        # reactionType out of the free-join family so RT4 always means joinable.
        return 2
    if character == 2:
        return 2
    if character == 3:
        return 0
    if character == 4:
        return 0
    raise ValueError(f"unsupported concrete monster character for {entity.get('sourceKey')}: {character}")


def h3_random_monster_level(entity: dict[str, Any]) -> int:
    animation = str(entity.get("templateAnimation") or "")
    prefix = "AVWmon"
    suffix = ".def"
    if not animation.startswith(prefix) or not animation.endswith(suffix):
        raise ValueError(f"random monster template is missing AVWmon level animation for {entity.get('sourceKey')}: {animation}")
    raw_level = animation[len(prefix):-len(suffix)]
    if not raw_level.isdigit():
        raise ValueError(f"random monster template animation has non-numeric level for {entity.get('sourceKey')}: {animation}")
    level = int(raw_level)
    if level not in H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL:
        raise ValueError(f"unsupported random monster level for {entity.get('sourceKey')}: {level}")
    return level


def h3_tier_median_squad_values() -> dict[int, float]:
    global _TIER_MEDIAN_SQUAD_VALUE_CACHE
    if _TIER_MEDIAN_SQUAD_VALUE_CACHE is not None:
        return dict(_TIER_MEDIAN_SQUAD_VALUE_CACHE)
    values: dict[int, list[float]] = defaultdict(list)
    unit_rows_seen = 0
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/units/units_logics/homm3_") and name.endswith("_l.json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Core unit logic member has no array rows: {name}")
            h3_rows = [row for row in rows if isinstance(row, dict) and str(row.get("id", "")).startswith("h3_")]
            if not h3_rows:
                raise ValueError(f"Core unit logic member has no h3_ unit row: {name}")
            for row in h3_rows:
                unit_rows_seen += 1
                tier = row.get("tier")
                squad_value = row.get("squadValue")
                unit_id = row.get("id")
                if not isinstance(tier, int) or tier not in H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL:
                    raise ValueError(f"Core h3_ unit row has invalid tier for random strength medians: {name} {unit_id} tier={tier!r}")
                if not isinstance(squad_value, (int, float)):
                    raise ValueError(f"Core h3_ unit row has invalid squadValue for random strength medians: {name} {unit_id} squadValue={squad_value!r}")
                values[tier].append(float(squad_value))
    if unit_rows_seen == 0:
        raise ValueError("Core.zip contains no h3_ unit rows for random monster strength medians")
    missing = sorted(set(H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL) - set(values))
    if missing:
        raise ValueError(f"Core.zip is missing h3_ squadValue rows for random monster tier(s): {missing}")
    _TIER_MEDIAN_SQUAD_VALUE_CACHE = {tier: float(median(rows)) for tier, rows in sorted(values.items())}
    return dict(_TIER_MEDIAN_SQUAD_VALUE_CACHE)


def rounded_requested_value(value: float) -> float:
    return float(math.floor((value / RANDOM_SQUAD_REQUESTED_VALUE_ROUNDING) + 0.5) * RANDOM_SQUAD_REQUESTED_VALUE_ROUNDING)


def random_squad_requested_value(entity: dict[str, Any]) -> float:
    animation = str(entity.get("templateAnimation") or "")
    medians = h3_tier_median_squad_values()
    if not animation.startswith("AVWmon") or not animation.endswith(".def"):
        count = int(entity.get("count") or 1)
        return rounded_requested_value(medians[1] * max(1, count))
    level = h3_random_monster_level(entity)
    nominal_count = H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL[level]
    return rounded_requested_value(medians[level] * nominal_count)


def h3_players_mask_to_sides(players_mask: int | None) -> str:
    """Convert H3M playersMask bitfield (bit0=player1) to Olden action sides CSV."""

    if players_mask is None:
        return ""
    mask = int(players_mask)
    if mask <= 0 or mask >= 255:
        return ""
    sides = [str(index + 1) for index in range(8) if mask & (1 << index)]
    return ",".join(sides)


def random_artifact_rarity(entity: dict[str, Any]) -> int:
    """Bin HoMM3 random-artifact class → Olden ERarity (shared emit policy)."""
    return rarity_bin.random_artifact_rarity(entity)


def monster_squad_property_row(object_id: int, entity: dict[str, Any]) -> dict[str, Any]:
    never_flees = bool(entity.get("neverFlees"))
    not_growing = bool(entity.get("notGrowingTeam"))
    character = entity.get("character")
    if character == 0 and not is_concrete_h3_monster_stack(entity):
        raise ValueError(
            f"joinable monster character==0 at {entity.get('sourceKey')} "
            f"subtype={entity.get('templateSubtype')} animation={entity.get('templateAnimation')} "
            f"is not mapped in CONCRETE_MONSTER_UNIT_BY_SUBTYPE; "
            f"refusing hostile random-squad fallback"
        )
    if is_concrete_h3_monster_stack(entity):
        is_recruitable = character == 0
        # Native free-join rows (e.g. c_M1.map) keep isEscape=true with free-diplomacy
        # flags. HoMM3 neverFlees must not clear Olden escape/join eligibility for
        # character==0 stacks — that forces combat instead of joining.
        return {
            "type": 0,
            "id": object_id,
            "sids": [concrete_monster_squad_sid(entity)],
            "requestedValue": concrete_monster_requested_value(entity),
            "fraction": "",
            "tier": 0,
            "isMainGuard": False,
            "reactionType": concrete_monster_reaction_type(entity),
            "customTopUnit": concrete_monster_unit_sid(entity),
            "weeklyIncrementBonus": 0.0 if not_growing else 0.0,
            "diplomacyUnitsCountBonus": 0.0,
            "isEscape": True if is_recruitable else False,
            # Neutrals/guards: allow adventure-map auto-battle. Enemy-hero auto is
            # gated separately via settings.disableAutoBattleAgainstEnemyHeroes.
            "isAutobatle": True,
            "isFreeDiplomacy": is_recruitable,
            "isCampaignFreeDiplomacy": is_recruitable,
            "isCampaignDiplomacy": False,
            "isIgnoreMultiply": is_recruitable or not_growing,
            "obstruction": "",
            "customStacks": 0,
            "neverFlees": never_flees,
            "notGrowingTeam": not_growing,
        }
    return {
        "type": 0,
        "id": object_id,
        "sids": [],
        "requestedValue": random_squad_requested_value(entity),
        "fraction": "",
        "tier": 0,
        "isMainGuard": False,
        "reactionType": 2,
        "customTopUnit": "",
        "weeklyIncrementBonus": 0.0,
        "diplomacyUnitsCountBonus": 0.0,
        "isEscape": False,
        # Neutrals/guards: allow adventure-map auto-battle. Enemy-hero auto is
        # gated separately via settings.disableAutoBattleAgainstEnemyHeroes.
        "isAutobatle": True,
        "isFreeDiplomacy": False,
        "isCampaignFreeDiplomacy": False,
        "isCampaignDiplomacy": False,
        "isIgnoreMultiply": not_growing,
        "obstruction": "",
        "customStacks": 0,
        "neverFlees": never_flees,
        "notGrowingTeam": not_growing,
    }


def append_approximate_property_rows(
    properties: dict[str, Any],
    placement: dict[str, Any],
    portal_targets: dict[int, int],
    *,
    emit_portal_properties: bool = True,
    map_event_specs: dict[str, dict[str, str]] | None = None,
) -> None:
    sid = placement["replacementSid"]
    object_id = placement["id"]
    entity = placement["entity"]
    if sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(str(sid)):
        return
    if sid == "hero-spawner":
        # Start hero rows are owned by apply_native_start_contract; non-start heroes
        # are bound later by append_placed_hero_properties after all objects merge.
        return
    source_key = str(entity.get("sourceKey") or "")
    map_event_spec = (map_event_specs or {}).get(source_key)
    if sid in MAP_EVENT_MARKER_SIDS and not map_event_spec:
        raise ValueError(
            f"map event marker {source_key} (object {object_id}, sid {sid}) has no map_event_spec binding"
        )
    if map_event_spec and sid in MAP_EVENT_MARKER_SIDS:
        entity_sid = map_event_spec["entitySid"]
        dialog_sid = map_event_spec["dialogSid"]
        sides = h3_players_mask_to_sides(map_event_spec.get("playersMask"))
        if map_event_spec.get("computerActivate") is False and sides == "":
            # Fail closed: computer-only denial with empty sides would still fire for everyone.
            raise ValueError(
                f"map event {source_key} has computerActivate=False but no playersMask sides"
            )
        properties["propEntities"].append({"type": 0, "id": object_id, "sid": entity_sid})
        properties["propActionsBefore"].append({
            "type": 0,
            "id": object_id,
            "repeat": False,
            "sides": sides,
            "computerActivate": bool(map_event_spec.get("computerActivate", True)),
            "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
        })
        after_actions: list[dict[str, Any]] = []
        if map_event_spec.get("removeAfterVisit"):
            after_actions.append({"comment": "", "a": "DeleteEntity", "p": [entity_sid]})
        rewards = map_event_spec.get("rewards") or {}
        if any(
            rewards.get(key)
            for key in ("skills", "artifacts", "spells", "creatures")
        ) or any(int(value or 0) for value in (rewards.get("resources") or [])):
            properties["propRewardParams"].append({
                "type": 0,
                "id": object_id,
                "parameters": [],
                "h3Rewards": rewards,
            })
        if after_actions:
            properties["propActionsAfter"].append({
                "type": 0,
                "id": object_id,
                "repeat": False,
                "sides": sides,
                "actions": after_actions,
            })
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
        return
    faction_sid = LANDON_CITY_PROPERTY_SIDS.get(str(sid))
    if faction_sid is not None:
        owner = entity.get("owner")
        city_row: dict[str, Any] = {
            "type": 0,
            "id": object_id,
            "isDefined": True,
            "factionSid": faction_sid,
            "spawnHero": False,
            "customCityName": homecoming_lang.custom_city_name_sid(str(entity.get("name") or "")),
            "buildingsBanSid": HOMECOMING_BUILDINGS_BAN_SID,
            "buildingsConstructionSid": HOMECOMING_BUILDINGS_CONSTRUCTION_SID,
            "buildingsSettingsSid": HOMECOMING_BUILDINGS_SETTINGS_SID,
        }
        if isinstance(owner, int):
            city_row["owner"] = h3m_hero_sid.h3_owner_to_olden_player_index(owner)
        if entity.get("hasCustomBuildings"):
            city_row["builtBuildingsMask"] = entity.get("builtBuildingsMask")
            city_row["forbiddenBuildingsMask"] = entity.get("forbiddenBuildingsMask")
        if entity.get("hasGarrison"):
            city_row["garrisonStacks"] = entity.get("garrisonStacks") or []
        properties["propCities"].append(city_row)
        return
    if sid == "random-squad":
        properties["propRandomSquads"].append(monster_squad_property_row(object_id, entity))
        interact_message = campaign_script.monster_interact_message(entity)
        if interact_message is not None:
            dialog_sid = campaign_script.monster_message_dialog_sid("homecoming", object_id)
            properties.setdefault("propActionsBefore", []).append(
                {
                    "type": 0,
                    "id": object_id,
                    "repeat": False,
                    "sides": "",
                    "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
                }
            )
        return
    if sid == "random-item":
        properties["propRandomItems"].append({
            "type": 0,
            "id": object_id,
            "rarity": random_artifact_rarity(entity),
        })
        return
    if sid == HOMM3_FLOTSAM_PICKUP_SID:
        properties["propRewardParams"].append({
            "type": 0,
            "id": object_id,
            "parameters": [],
            "flotsamOneShotPolicy": "h3_flotsam_random_basic_resource",
        })
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
        return
    if sid == "random-res":
        properties["propResources"].append({
            "type": 0,
            "id": object_id,
            "overrideVal": 0,
            "isOverrideArray": False,
            "propRes": [],
        })
        return
    if sid in RESOURCE_VALUES:
        properties["propResParams"].append({"type": 0, "id": object_id, "value": RESOURCE_VALUES[sid]})
    if sid in REWARD_PARAM_SIDS:
        properties["propRewardParams"].append({"type": 0, "id": object_id, "parameters": []})
    if sid in VARIANT_SIDS:
        properties["propVariants"].append({"type": 0, "id": object_id, "selectedVar": -1, "typeVariant": 0, "fraction": 0, "unitVersion": 0})
    if sid in ENTITY_SIDS:
        properties["propEntities"].append({"type": 0, "id": object_id, "sid": deterministic_entity_sid(sid, object_id)})
    if sid in NO_COMBINE_GEOMETRY_SIDS:
        properties["propNoCombineGeometries"].append({"type": 0, "id": object_id, "isNoCombineGeometry": True})
    if sid in AI_IGNORE_SIDS:
        properties["propAiIntetactions"].append({"type": 0, "id": object_id, "aiIgnore": True})
    if sid in ACTION_BEFORE_SIDS:
        properties["propActionsBefore"].append({"type": 0, "id": object_id, "repeat": False, "sides": "", "actions": []})
    if sid in ACTION_AFTER_SIDS:
        properties["propActionsAfter"].append({"type": 0, "id": object_id, "repeat": False, "sides": "", "actions": []})
    if sid in ACTIVATION_SIDS:
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
    if sid in PORTAL_SIDS:
        if emit_portal_properties:
            if object_id not in portal_targets:
                raise ValueError(f"missing portal target for emitted portal object {object_id} ({sid})")
            properties["propPortals"].append({"type": 0, "id": object_id, "targetIdx": portal_targets[object_id], "isActive": True})
        properties["propRandomSquads"].append({
            "type": 0, "id": object_id, "sids": [], "requestedValue": 0.0, "fraction": "", "tier": 0,
            "isMainGuard": False, "reactionType": 2, "customTopUnit": "", "weeklyIncrementBonus": 0.0,
            "diplomacyUnitsCountBonus": 0.0, "isEscape": True, "isAutobatle": True, "isFreeDiplomacy": False,
            "isCampaignFreeDiplomacy": False, "isCampaignDiplomacy": False, "isIgnoreMultiply": False,
            "obstruction": "", "customStacks": 0,
        })


def build_portal_targets(placements: list[dict[str, Any]]) -> dict[int, int]:
    targets: dict[int, int] = {}
    by_sid: dict[str, list[int]] = defaultdict(list)
    for placement in placements:
        sid = placement["replacementSid"]
        if sid in PORTAL_SIDS:
            by_sid[sid].append(int(placement["id"]))
    for sid, ids in sorted(by_sid.items()):
        ordered = sorted(ids)
        if len(ordered) % 2:
            raise ValueError(f"cannot pair odd portal count for {sid}: {ordered}")
        for first, second in zip(ordered[0::2], ordered[1::2]):
            targets[first] = second
            targets[second] = first
    return targets


def discover_native_property_required_sids() -> dict[str, dict[str, int]]:
    """Map SID → unsupported native property-family hit counts from shipped maps.

    Keep semantics aligned with approach_cell/surface_emit.py.
    """
    required: dict[str, Counter] = defaultdict(Counter)
    for map_path in poc.OLDEN_MAPS_DIR.rglob("*.map"):
        if map_path.name.startswith("h3_roe_castle_homecoming"):
            continue
        try:
            container = poc.read_olden_map_container(map_path)
        except Exception as ex:
            raise ValueError(f"failed reading native map during property-required SID scan: {map_path}: {ex}") from ex
        if len(container.chunks) < 2:
            raise ValueError(f"native map has no map-data chunk during property-required SID scan: {map_path}")
        map_data = container.chunks[1]
        id_to_sid: dict[int, str] = {}
        for group in map_data.get("objects") or []:
            if not isinstance(group, dict):
                continue
            sid = group.get("sid")
            if not isinstance(sid, str):
                continue
            for object_id in group.get("ids") or []:
                if isinstance(object_id, int):
                    id_to_sid[object_id] = sid
        props = map_data.get("objectsProperties") or {}
        if not isinstance(props, dict):
            raise ValueError(f"native map objectsProperties is not an object during property-required SID scan: {map_path}")
        for prop_name, rows in props.items():
            if prop_name in SUPPORTED_LIVE_PROPERTY_FAMILIES or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("type") != 0:
                    continue
                sid = id_to_sid.get(row.get("id"))
                if sid:
                    required[sid][prop_name] += 1
    return {sid: dict(counter) for sid, counter in sorted(required.items())}


def is_suppressible_source_scenery(placement: dict[str, Any]) -> bool:
    return functional_emit_reservation.is_suppressible_source_scenery(placement)


def source_anchor_priority(placement: dict[str, Any]) -> int:
    if is_suppressible_source_scenery(placement):
        return 100
    entity = placement.get("entity")
    category = entity.get("category") if isinstance(entity, dict) else None
    if str(category) not in SOURCE_ANCHOR_PRIORITY_BY_CATEGORY:
        raise ValueError(f"source-anchor collision priority is not defined for category {category!r}: {placement}")
    return SOURCE_ANCHOR_PRIORITY_BY_CATEGORY[str(category)]


def suppress_exact_anchor_scenery_collisions(placements: list[dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for placement in placements:
        node = placement.get("node")
        if not isinstance(node, int):
            raise ValueError(f"placement missing integer node: {placement}")
        by_node[node].append(placement)

    suppressed_ids: set[int] = set()
    suppressed_examples: list[dict[str, Any]] = []
    suppressed_sid_counts = Counter()
    suppressed_rule_counts = Counter()
    suppressed_reason_counts = Counter()
    unresolved_groups = 0
    unresolved_examples: list[dict[str, Any]] = []
    for node, node_placements in sorted(by_node.items()):
        if len(node_placements) < 2:
            continue
        kept = [placement for placement in node_placements if not is_suppressible_source_scenery(placement)]
        if not kept:
            continue
        suppressible = [placement for placement in node_placements if is_suppressible_source_scenery(placement)]
        if len(kept) > 1:
            unresolved_groups += 1
            if len(unresolved_examples) < 20:
                ordered = sorted(kept, key=lambda item: int(item.get("id") or 0))
                unresolved_examples.append({
                    "node": node,
                    "x": node % OLDEN_WIDTH,
                    "y": node // OLDEN_WIDTH,
                    "ids": [placement.get("id") for placement in ordered],
                    "sids": [placement.get("replacementSid") for placement in ordered],
                    "reason": "exact_anchor_collision_between_non_suppressible_source_objects_preserved",
                })
        if not suppressible:
            continue
        winning = max(kept, key=lambda item: (source_anchor_priority(item), -int(item.get("id") or 0)))
        for placement in suppressible:
            object_id = placement.get("id")
            if not isinstance(object_id, int):
                raise ValueError(f"suppressible placement missing integer id: {placement}")
            suppressed_ids.add(object_id)
            sid = str(placement.get("replacementSid"))
            rule_name = str(placement.get("ruleName"))
            reason = "exact_native_anchor_collision_with_higher_priority_source_object"
            suppressed_sid_counts[sid] += 1
            suppressed_rule_counts[rule_name] += 1
            suppressed_reason_counts[reason] += 1
            entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else {}
            suppressed_examples.append({
                "sourceIndex": object_id,
                "sourceKey": entity.get("sourceKey"),
                "replacementSid": sid,
                "ruleName": rule_name,
                "node": node,
                "x": node % OLDEN_WIDTH,
                "y": node // OLDEN_WIDTH,
                "keptSourceIndex": winning.get("id"),
                "keptReplacementSid": winning.get("replacementSid"),
                "reason": reason,
            })

    if suppressed_ids:
        placements[:] = [placement for placement in placements if placement.get("id") not in suppressed_ids]

    return {
        "status": "generated_artifact_validated_runtime_unvalidated",
        "policy": SOURCE_ANCHOR_COMPOSITION_POLICY,
        "suppressedObjectCount": len(suppressed_ids),
        "suppressedSidHistogram": dict(suppressed_sid_counts.most_common()),
        "suppressedRuleHistogram": dict(suppressed_rule_counts.most_common()),
        "suppressedReasonHistogram": dict(suppressed_reason_counts.most_common()),
        "suppressedExamples": suppressed_examples,
        "unresolvedExactAnchorCollisionGroupCount": unresolved_groups,
        "unresolvedExactAnchorCollisionExamples": unresolved_examples,
    }

def build_surface_objects(
    surface_entities: list[dict[str, Any]],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    property_required_sids: dict[str, dict[str, int]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    portal_property_policy: str = "same_sid_even_pairs",
    surface_map_data: dict[str, Any] | None = None,
    enable_footprint_alignment: bool = True,
    enable_pathability_visual_clones: bool = False,
    synthetic_id_base: int | None = None,
    map_event_specs: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    if portal_property_policy not in {"same_sid_even_pairs", "deferred_to_layered_cross_layer_pairing"}:
        raise ValueError(f"unsupported portal property policy: {portal_property_policy!r}")
    deferred_counts = Counter()
    deferred_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    blocked_counts = Counter()
    blocked_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    placements: list[dict[str, Any]] = []
    rotation_alignment_counts = Counter()
    rotation_changed_count = 0
    rotation_alignment_examples: list[dict[str, Any]] = []
    rotation_ambiguous_examples: list[dict[str, Any]] = []
    source_anchor_node_alignment_counts = Counter()
    source_anchor_node_changed_count = 0
    source_anchor_node_alignment_examples: list[dict[str, Any]] = []
    source_anchor_node_ambiguous_examples: list[dict[str, Any]] = []
    source_anchor_node_ineligible_examples: list[dict[str, Any]] = []
    source_anchor_node_footprint_source_counts = Counter()
    source_anchor_node_point_sid_counts = Counter()
    guarded_candidates = guarded_visit_candidates_by_source(surface_entities)

    source_guard_candidate_count = sum(len(rows) for rows in guarded_candidates.values())
    guarded_policy_disabled_examples: list[dict[str, Any]] = []
    for source_index, candidates in sorted(guarded_candidates.items())[:20]:
        entity = next((item for item in surface_entities if item.get("sourceIndex") == source_index), None)
        sample = candidates[0] if candidates else {}
        guarded_policy_disabled_examples.append({
            "sourceIndex": source_index,
            "sourceKey": entity.get("sourceKey") if isinstance(entity, dict) else None,
            "sourceCategory": entity.get("category") if isinstance(entity, dict) else None,
            "guardSourceIndex": sample.get("guardSourceIndex"),
            "guardSourceKey": sample.get("guardSourceKey"),
            "sourceVisitKey": sample.get("sourceVisitKey"),
            "sourceVisitVector": [int(sample["dx"]), int(sample["dy"])] if "dx" in sample and "dy" in sample else [],
            "sourceGuardVector": sample.get("sourceGuardVector"),
            "sourceGuardToVisitVector": sample.get("sourceGuardToVisitVector"),
            "sourceGuardAdjacency": sample.get("sourceGuardAdjacency"),
            "reason": GUARDED_PLACEMENT_DISABLED_REASON,
        })
    for entity in surface_entities:
        if not is_in_source_bounds(entity):
            raise ValueError(f"surface entity outside emitted bounds reached placement: {entity.get('sourceKey')}")
        signature = signature_for(entity)
        replacement_sid, rule_name, lossiness = resolve_replacement_sid(entity, substitution_lookup, valid_ids)
        if replacement_sid is None:
            blocked_counts[rule_name] += 1
            if len(blocked_examples[rule_name]) < 5:
                blocked_examples[rule_name].append({
                    "sourceKey": entity.get("sourceKey"),
                    "sourceSid": entity.get("sid"),
                    "templateObjectId": entity.get("templateObjectId"),
                    "templateAnimation": entity.get("templateAnimation"),
                    "category": entity.get("category"),
                    "payloadKind": entity.get("payloadKind"),
                    "ruleName": rule_name,
                    "lossiness": lossiness,
                })
            continue
        if replacement_sid not in valid_ids:
            raise ValueError(f"replacement is not whitelisted for {signature}: {replacement_sid}")
        required_props = property_required_sids.get(replacement_sid)
        unsupported_props = sorted(set(required_props or {}) - SUPPORTED_LIVE_PROPERTY_FAMILIES)
        # Fail closed for non-whitelisted SIDs with any native props; whitelisted
        # SIDs only defer on unsupported families (see surface_emit.py).
        if required_props and (
            replacement_sid not in SUPPORTED_LIVE_PROPERTY_SIDS or unsupported_props
        ):
            deferred_counts[replacement_sid] += 1
            if len(deferred_examples[replacement_sid]) < 5:
                deferred_examples[replacement_sid].append({
                    "sourceKey": entity.get("sourceKey"),
                    "sourceSid": entity.get("sid"),
                    "replacementSid": replacement_sid,
                    "requiredNativePropertyFamilies": required_props,
                    "unsupportedNativePropertyFamilies": unsupported_props,
                    "ruleName": rule_name,
                    "lossiness": lossiness,
                })
            continue
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_x, int) or not isinstance(source_y, int):
            raise ValueError(f"surface entity missing source coordinates: {entity}")
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            raise ValueError(f"surface entity missing integer sourceIndex: {entity}")
        default_node = target_node(source_x, source_y)
        if str(replacement_sid) not in native_object_configs:
            raise ValueError(f"missing native object config for emitted SID {replacement_sid}")
        source_rotation = int(entity.get("rotation") or 0)
        rotation, rotation_evidence = derive_source_mask_rotation(entity, native_object_configs[str(replacement_sid)])
        rotation_alignment_counts[str(rotation_evidence.get("decision") or rotation_evidence.get("reason"))] += 1
        if rotation != source_rotation:
            rotation_changed_count += 1
            rotation_alignment_examples.append({
                "sourceIndex": source_index,
                "sourceKey": entity.get("sourceKey"),
                "replacementSid": str(replacement_sid),
                "templateObjectId": entity.get("templateObjectId"),
                "templateAnimation": entity.get("templateAnimation"),
                **rotation_evidence,
            })
        if rotation_evidence.get("reason") == "source_visit_or_block_mask_ambiguous":
            rotation_ambiguous_examples.append({
                "sourceIndex": source_index,
                "sourceKey": entity.get("sourceKey"),
                "replacementSid": str(replacement_sid),
                "templateObjectId": entity.get("templateObjectId"),
                "templateAnimation": entity.get("templateAnimation"),
                **rotation_evidence,
            })
        node, source_anchor_node_evidence = derive_source_anchor_node(
            entity,
            str(replacement_sid),
            native_object_configs[str(replacement_sid)],
            default_node,
            rotation=rotation,
        )
        source_anchor_node_alignment_counts[str(source_anchor_node_evidence.get("decision") or source_anchor_node_evidence.get("reason"))] += 1
        footprint_source = str((source_anchor_node_evidence.get("nativeFootprint") or {}).get("source"))
        source_anchor_node_footprint_source_counts[footprint_source] += 1
        if footprint_source in SOURCE_ANCHOR_POINT_FOOTPRINT_SOURCES:
            source_anchor_node_point_sid_counts[str(replacement_sid)] += 1
        if node != default_node:
            source_anchor_node_changed_count += 1
            source_anchor_node_alignment_examples.append({
                "sourceIndex": source_index,
                "sourceKey": entity.get("sourceKey"),
                "replacementSid": str(replacement_sid),
                "templateObjectId": entity.get("templateObjectId"),
                "templateAnimation": entity.get("templateAnimation"),
                "originalNode": default_node,
                **source_anchor_node_evidence,
            })
        placements.append({"replacementSid": str(replacement_sid), "id": source_index, "entity": entity, "ruleName": rule_name, "lossiness": lossiness, "node": node, "rotation": rotation, "level": float(entity.get("level") or 0)})

    def _occupied_for_emit_placement(placement: dict[str, Any]) -> set[int]:
        sid = str(placement.get("replacementSid") or "")
        config = native_object_configs.get(sid)
        anchor = placement.get("node")
        if not isinstance(config, dict) or not isinstance(anchor, int):
            return set()
        return occupied_nodes_for_object_instance(
            sid,
            config,
            anchor,
            int(placement.get("rotation") or 0),
        )

    functional_emit_reservation_stats = functional_emit_reservation.apply_functional_first_emit_reservation(
        placements,
        native_object_configs,
        grid_width=OLDEN_WIDTH,
        grid_height=OLDEN_HEIGHT,
        mirrored_rotation=OLDEN_MIRRORED_ROTATION,
        entity_visit_nodes_fn=entity_visit_nodes,
        entity_block_nodes_fn=entity_nonvisitable_block_nodes,
        occupied_nodes_for_placement=_occupied_for_emit_placement,
        skip_sid_fn=lambda sid: sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(sid),
    )

    source_anchor_composition = suppress_exact_anchor_scenery_collisions(placements)
    # Visual clones must run before footprint pads so oversized scenery stops blocking
    # cells that pads would otherwise stack onto.
    if enable_pathability_visual_clones:
        pathability_visual_alignment = apply_homm3_pathability_visual_clones(
            placements,
            native_object_configs,
        )
    else:
        pathability_visual_alignment = {
            "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
            "policy": footprint_alignment.FOOTPRINT_ALIGNMENT_POLICY,
            "phase": "visual_clone_disabled",
            "visualCloneSidCount": 0,
            "visualCloneObjectCount": 0,
            "visualCloneSourceSidHistogram": {},
            "visualCloneExamples": [],
            "visualRows": {},
            "proofBoundary": "footprint_alignment owns mask fit; visual clones are disabled",
        }
    footprint_alignment_stats: dict[str, Any] | None = None
    footprint_global_gap_fill: dict[str, Any] | None = None
    if enable_footprint_alignment:
        pad_id_base = synthetic_id_base if synthetic_id_base is not None else footprint_alignment.FOOTPRINT_PAD_ID_BASE
        footprint_alignment_stats = footprint_alignment.apply_footprint_alignment_to_placements(
            placements,
            native_object_configs=native_object_configs,
            valid_ids=valid_ids,
            surface_map_data=surface_map_data,
            grid_width=OLDEN_WIDTH,
            synthetic_id_base=pad_id_base,
        )
        cluster_promote = footprint_alignment.promote_cluster_scenery_placements(
            placements,
            native_object_configs=native_object_configs,
            valid_ids=valid_ids,
            surface_map_data=surface_map_data,
            grid_width=OLDEN_WIDTH,
            next_id=pad_id_base + 40_000,
        )
        footprint_alignment_stats["clusterPromote"] = {
            "promotedClusterCount": cluster_promote.get("promotedClusterCount"),
            "removedPadCount": cluster_promote.get("removedPadCount"),
            "promotedSidHistogram": cluster_promote.get("promotedSidHistogram"),
            "skippedPromoteReasonHistogram": cluster_promote.get("skippedPromoteReasonHistogram"),
        }
        footprint_global_gap_fill = footprint_alignment.append_global_scenery_gap_fill_placements(
            placements,
            surface_entities,
            native_object_configs=native_object_configs,
            valid_ids=valid_ids,
            surface_map_data=surface_map_data,
            next_id=pad_id_base + 50_000,
            grid_width=OLDEN_WIDTH,
        )
        stack_resolve = footprint_alignment.resolve_occupied_scenery_stacks(
            placements,
            native_object_configs=native_object_configs,
        )
        footprint_alignment_stats["occupiedStackResolve"] = stack_resolve
        occupancy = footprint_alignment.compute_occupied_overlap_report(
            placements,
            native_object_configs=native_object_configs,
        )
        footprint_alignment_stats["occupiedOverlap"] = occupancy
        # Pads/shifts can still leave scenery on functional reserved cells; omit again.
        post_align_omit = functional_emit_reservation.apply_functional_first_emit_reservation(
            placements,
            native_object_configs,
            grid_width=OLDEN_WIDTH,
            grid_height=OLDEN_HEIGHT,
            mirrored_rotation=OLDEN_MIRRORED_ROTATION,
            entity_visit_nodes_fn=entity_visit_nodes,
            entity_block_nodes_fn=entity_nonvisitable_block_nodes,
            occupied_nodes_for_placement=_occupied_for_emit_placement,
            skip_sid_fn=lambda sid: sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(sid),
        )
        functional_emit_reservation_stats["postFootprintAlignmentOmit"] = {
            key: value
            for key, value in post_align_omit.items()
            if key != "reservedNodes"
        }
    grouped = defaultdict(lambda: {"ids": [], "nodes": [], "rotations": [], "levels": []})
    replacement_counts = Counter()
    rule_counts = Counter()
    lossy_counts = Counter()
    for placement in placements:
        replacement_sid = str(placement["replacementSid"])
        group = grouped[replacement_sid]
        group["ids"].append(int(placement["id"]))
        group["nodes"].append(int(placement["node"]))
        group["rotations"].append(int(placement["rotation"]))
        group["levels"].append(float(placement["level"]))
        replacement_counts[replacement_sid] += 1
        rule_counts[str(placement["ruleName"])] += 1
        lossy_counts[str(placement["lossiness"])] += 1

    objects = []
    for sid in sorted(grouped):
        data = grouped[sid]
        objects.append({"sid": sid, "ids": data["ids"], "nodes": data["nodes"], "rotations": data["rotations"], "levels": data["levels"]})

    properties = {
        "propsName": [],
        "propComments": [],
        "propSpawns": [],
        "propCities": [],
        "propHeroes": [],
        "propRandomSquads": [],
        "propRandomItems": [],
        "propRandomHires": [],
        "propOwners": [],
        "propResources": [],
        "propSquads": [],
        "propDialogWindows": [],
        "propPortals": [],
        "propQuestNames": [],
        "propMainObjects": [],
        "propActionsLegacy": [],
        "propVariants": [],
        "propActionsBefore": [],
        "propActionsAfter": [],
        "propEntities": [],
        "propAiIntetactions": [],
        "propRewardParams": [],
        "propResParams": [],
        "propMarkers": [],
        "propGrowthUnits": [],
        "propActivations": [],
        "propNoCombineGeometries": [],
        "propCitiesHold": [],
        "propQuestMarkers": [],
    }
    emit_portal_properties = portal_property_policy == "same_sid_even_pairs"
    portal_targets = build_portal_targets(placements) if emit_portal_properties else {}
    for placement in placements:
        append_approximate_property_rows(
            properties,
            placement,
            portal_targets,
            emit_portal_properties=emit_portal_properties,
            map_event_specs=map_event_specs,
        )

    stats = {
        "emittedSurfaceEntityCount": sum(len(group["ids"]) for group in grouped.values()),
        "deferredBlockedEntityCount": sum(blocked_counts.values()),
        "deferredBlockedRuleHistogram": dict(blocked_counts.most_common()),
        "deferredBlockedExamples": {rule: rows for rule, rows in sorted(blocked_examples.items())},
        "deferredPropertyRequiredEntityCount": sum(deferred_counts.values()),
        "deferredPropertyRequiredSidHistogram": dict(deferred_counts.most_common()),
        "deferredPropertyRequiredExamples": {sid: rows for sid, rows in sorted(deferred_examples.items())},
        "emittedObjectGroupCount": len(objects),
        "replacementSidHistogram": dict(replacement_counts.most_common()),
        "propertyRowHistogram": {key: len(value) for key, value in sorted(properties.items()) if isinstance(value, list) and value},
        "ruleHistogram": dict(rule_counts.most_common()),
        "lossinessHistogram": dict(lossy_counts.most_common()),
        "sourceMaskRotationAlignment": {
            "status": SOURCE_MASK_ROTATION_ALIGNMENT_STATUS,
            "policy": SOURCE_MASK_ROTATION_ALIGNMENT_POLICY,
            "decisionHistogram": dict(rotation_alignment_counts.most_common()),
            "changedObjectCount": rotation_changed_count,
            "changedExamples": rotation_alignment_examples,
            "ambiguousObjectCount": len(rotation_ambiguous_examples),
            "ambiguousExamples": rotation_ambiguous_examples,
        },
        "sourceAnchorNodeAlignment": {
            "status": SOURCE_ANCHOR_NODE_ALIGNMENT_STATUS,
            "policy": SOURCE_ANCHOR_NODE_ALIGNMENT_POLICY,
            "decisionHistogram": dict(source_anchor_node_alignment_counts.most_common()),
            "footprintSourceHistogram": dict(source_anchor_node_footprint_source_counts.most_common()),
            "pointAnchorSidHistogram": dict(source_anchor_node_point_sid_counts.most_common()),
            "pointAnchorWithoutNativeFootprintSids": sorted(POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS),
            "changedObjectCount": source_anchor_node_changed_count,
            "changedExamples": source_anchor_node_alignment_examples,
            "ambiguousObjectCount": 0,
            "ambiguousExamples": source_anchor_node_ambiguous_examples,
            "ineligibleObjectCount": 0,
            "ineligibleExamples": source_anchor_node_ineligible_examples,
        },
        "sourceAnchorComposition": source_anchor_composition,
        "functionalEmitReservation": {
            key: value
            for key, value in functional_emit_reservation_stats.items()
            if key != "reservedNodes"
        },
        "pathabilityAlignment": {
            key: value
            for key, value in pathability_visual_alignment.items()
            if key != "visualRows"
        },
        "footprintAlignment": footprint_alignment_stats,
        "footprintGlobalGapFill": footprint_global_gap_fill,
        "guardedVisitRotationContract": {
            "status": GUARDED_PLACEMENT_STATUS,
            "source": "HoMM3 template visitMask vs source guard-stack adjacency; native gate relocation disabled",
            "sourceMaskProjection": GUARDED_SOURCE_MASK_PROJECTION,
            "sourceGuardModel": GUARDED_SOURCE_GUARD_MODEL,
            "guardPlacementPolicy": GUARDED_PLACEMENT_POLICY,
            "disabledReason": GUARDED_PLACEMENT_DISABLED_REASON,
            "sourceGuardedObjectCount": len(guarded_candidates),
            "sourceGuardCandidateCount": source_guard_candidate_count,
            "disabledSourceGuardedExamples": guarded_policy_disabled_examples,
            "guardedCandidateCount": 0,
            "guardedCandidateSourceObjectCount": 0,
            "excludedSourceGuardedObjectCount": 0,
            "excludedSourceGuardedCategoryHistogram": {},
            "excludedSourceGuardedExamples": [],
            "blockedGuardedObjectCount": 0,
            "blockedGuardedRuleHistogram": {},
            "blockedGuardedExamples": [],
            "ungateableGuardedObjectCount": 0,
            "ungateableGuardedSidHistogram": {},
            "ungateableGuardedExamples": [],
            "guardedObjectCount": 0,
            "suppressedCoGuardedObjectCount": 0,
            "suppressedCoGuardedSidHistogram": {},
            "suppressedCoGuardedExamples": [],
            "displacedObjectCount": 0,
            "displacedObjectSidHistogram": {},
            "displacedObjectExamples": [],
            "matches": [],
        },
    }
    if portal_property_policy != "same_sid_even_pairs":
        stats["portalPropertyPolicy"] = portal_property_policy
        stats["portalPropertyTargetCount"] = len(portal_targets)
    return objects, properties, stats, pathability_visual_alignment.get("visualRows") or {}


def append_homm3_pathability_gap_fill_blockers(
    objects: list[dict[str, Any]],
    surface_entities: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entities_by_id = {
        int(entity["sourceIndex"]): entity
        for entity in surface_entities
        if isinstance(entity, dict) and isinstance(entity.get("sourceIndex"), int)
    }
    occupied_nodes: set[int] = set()
    for group in objects:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            raise ValueError(f"missing native object config while summing occupied nodes for emitted group {sid}")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        if not (len(ids) == len(nodes) == len(rotations)):
            raise ValueError(f"object group array length mismatch for {sid}")
        for object_id, anchor_node, rotation in zip(ids, nodes, rotations):
            if not isinstance(anchor_node, int) or not isinstance(rotation, int):
                raise ValueError(f"invalid node/rotation in object group {sid}")
            full_occ = occupied_nodes_for_object_instance(sid, config, anchor_node, rotation)
            if (
                not isinstance(object_id, int)
                or functional_emit_reservation.is_infrastructure_sid(sid)
                or sid == HOMM3_PATHING_BLOCKER_SID
                or is_homm3_pathing_visual_sid(sid)
            ):
                occupied_nodes |= full_occ
                continue
            entity = entities_by_id.get(object_id)
            if entity is None:
                occupied_nodes |= full_occ
                continue
            placement = {
                "replacementSid": sid,
                "id": object_id,
                "entity": entity,
                "node": anchor_node,
                "rotation": rotation,
            }
            if functional_emit_reservation.is_scenery_placement(placement):
                occupied_nodes |= full_occ
                continue
            h3_authority = entity_visit_nodes(entity) | entity_nonvisitable_block_nodes(entity)
            occupied_nodes |= full_occ & h3_authority

    required_block_nodes: set[int] = set()
    for entity in surface_entities:
        required_block_nodes |= entity_nonvisitable_block_nodes(entity)
    # Scorched-earth subterranean portal GATE markers must stay approachable.
    scorched_portal_gates = subterranean_portal_gate_nodes(objects, native_object_configs)
    gap_nodes = sorted(required_block_nodes - occupied_nodes - scorched_portal_gates)

    ids: list[int] = []
    nodes: list[int] = []
    rotations: list[int] = []
    levels: list[float] = []
    next_blocker_id = HOMM3_PATHING_BLOCKER_ID_BASE
    blocker_examples: list[dict[str, Any]] = []
    for node in gap_nodes:
        ids.append(next_blocker_id)
        nodes.append(node)
        rotations.append(0)
        levels.append(0.0)
        if len(blocker_examples) < 20:
            blocker_examples.append({"id": next_blocker_id, "node": node, "x": node % OLDEN_WIDTH, "y": node // OLDEN_WIDTH})
        next_blocker_id += 1
    if ids:
        append_object_instances(
            objects,
            HOMM3_PATHING_BLOCKER_SID,
            ids,
            nodes,
            rotations,
            levels,
        )

    return {
        "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": HOMM3_PATHABILITY_ALIGNMENT_POLICY,
        "phase": "gap_fill_after_boat_and_decorations",
        "requiredH3NonvisitableBlockNodeCount": len(required_block_nodes),
        "occupiedNodeCountBeforeGapFill": len(occupied_nodes),
        "gapFillBlockerCount": len(gap_nodes),
        "gapFillBlockerExamples": blocker_examples,
        "pathingBlockerSid": HOMM3_PATHING_BLOCKER_SID,
        "pathingBlockerIdBase": HOMM3_PATHING_BLOCKER_ID_BASE,
        "proofBoundary": "source/static/generated-artifact pathability gap-fill; native runtime pathfinder remains user-unvalidated",
    }


def append_object_instances(
    objects: list[dict[str, Any]],
    sid: str,
    ids: list[int],
    nodes: list[int],
    rotations: list[int],
    levels: list[float],
) -> None:
    for group in objects:
        if group.get("sid") == sid:
            group["ids"].extend(ids)
            group["nodes"].extend(nodes)
            group["rotations"].extend(rotations)
            group["levels"].extend(levels)
            return
    objects.append({"sid": sid, "ids": ids, "nodes": nodes, "rotations": rotations, "levels": levels})


def stable_node_score(namespace: str, node: int) -> int:
    digest = hashlib.sha256(f"{MAP_SID}:{namespace}:{node}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def occupied_object_nodes(objects: list[dict[str, Any]]) -> set[int]:
    nodes: set[int] = set()
    for group in objects:
        for node in group.get("nodes", []) if isinstance(group, dict) else []:
            if isinstance(node, int):
                nodes.add(node)
    return nodes


def decoration_candidate_nodes(projected: dict[str, list[int]], occupied: set[int], excluded: set[int], tile_code: int) -> list[int]:
    candidates: list[int] = []
    for source_y in range(SOURCE_HEIGHT):
        for source_x in range(SOURCE_WIDTH):
            node = target_node(source_x, source_y)
            if node in occupied or node in excluded:
                continue
            if projected["tilesMap"][node] != tile_code or projected["waterMap"][node] != 0:
                continue
            candidates.append(node)
    candidates.sort(key=lambda node: (stable_node_score(f"decor:{tile_code}", node), node))
    return candidates


def append_object_instance(objects: list[dict[str, Any]], sid: str, object_id: int, node: int) -> None:
    for group in objects:
        if group.get("sid") == sid:
            group["ids"].append(object_id)
            group["nodes"].append(node)
            group["rotations"].append(0)
            group["levels"].append(0.0)
            return
    objects.append({"sid": sid, "ids": [object_id], "nodes": [node], "rotations": [0], "levels": [0.0]})


def add_environment_decorations(objects: list[dict[str, Any]], projected: dict[str, list[int]], shoreline_rivers: list[dict[str, Any]], valid_ids: set[str]) -> dict[str, Any]:
    occupied = occupied_object_nodes(objects)
    shoreline_nodes = {
        int(node.get("n"))
        for river in shoreline_rivers
        for node in river.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("n"), int)
    }
    emitted_by_tile: dict[int, Counter[str]] = {}
    emitted_total = 0
    next_id = ENV_DECORATION_ID_BASE
    for tile_code, sids in sorted(ENV_DECORATION_SIDS_BY_TILE.items()):
        missing = [sid for sid in sids if sid not in valid_ids]
        if missing:
            raise ValueError(f"environment decoration SIDs are not whitelisted for tile {tile_code}: {missing}")
        candidates = decoration_candidate_nodes(projected, occupied, shoreline_nodes, tile_code)
        target = min(ENV_DECORATION_TARGET_BY_TILE[tile_code], len(candidates))
        if target <= 0:
            continue
        sid_counts: Counter[str] = Counter()
        for offset, node in enumerate(candidates[:target]):
            sid = sids[stable_node_score(f"decor-sid:{tile_code}", node) % len(sids)]
            append_object_instance(objects, sid, next_id, node)
            occupied.add(node)
            sid_counts[sid] += 1
            emitted_total += 1
            next_id += 1
        emitted_by_tile[tile_code] = sid_counts
    return {
        "status": "generated_runtime_unvalidated",
        "idBase": ENV_DECORATION_ID_BASE,
        "emittedCount": emitted_total,
        "targetByTile": {str(key): value for key, value in sorted(ENV_DECORATION_TARGET_BY_TILE.items())},
        "sidHistogramByTile": {str(tile): dict(counter.most_common()) for tile, counter in sorted(emitted_by_tile.items())},
    }


def water_tile_overlay_identity_output_path() -> Path:
    override = os.environ.get("HOMECOMING_WATER_TILE_OVERLAY_IDENTITY_OUTPUT")
    if override:
        return Path(override)
    try:
        primary_output_root = BASE_OUT_ROOT.resolve() == DEFAULT_INPUT_ROOT.resolve()
    except OSError:
        primary_output_root = BASE_OUT_ROOT == DEFAULT_INPUT_ROOT
    if primary_output_root:
        return WATER_TILE_OVERLAY_IDENTITY_SOURCE_PATH
    return OUT_ROOT / "runtime_assets" / WATER_TILE_OVERLAY_IDENTITY_RELATIVE_PATH

def add_water_tile_overlay_objects(objects: list[dict[str, Any]], projected: dict[str, list[int]]) -> dict[str, Any]:
    missing = sorted(set(WATER_TILE_OVERLAY_SID_BY_TILE_CODE) - set(NATIVE_WATER_TILE_CODES))
    if missing:
        raise ValueError(f"water tile overlay SID table references non-water tile code(s): {missing}")
    emitted_by_tile: Counter[int] = Counter()
    emitted_by_sid: Counter[str] = Counter()
    object_ids_by_sid: dict[str, list[int]] = defaultdict(list)
    nodes_by_sid: dict[str, list[int]] = defaultdict(list)
    example_nodes: dict[str, list[int]] = defaultdict(list)
    next_id = WATER_TILE_OVERLAY_ID_BASE
    for source_y in range(SOURCE_HEIGHT):
        for source_x in range(SOURCE_WIDTH):
            node = target_node(source_x, source_y)
            tile_code = projected["tilesMap"][node]
            sid = WATER_TILE_OVERLAY_SID_BY_TILE_CODE.get(tile_code)
            if sid is None:
                continue
            if projected["waterMap"][node] != 0:
                raise ValueError(f"water tile overlay target node {node} tile {tile_code} has nonzero waterMap={projected['waterMap'][node]}")
            object_id = next_id
            append_object_instance(objects, sid, object_id, node)
            next_id += 1
            emitted_by_tile[tile_code] += 1
            emitted_by_sid[sid] += 1
            object_ids_by_sid[sid].append(object_id)
            nodes_by_sid[sid].append(node)
            key = str(tile_code)
            if len(example_nodes[key]) < 8:
                example_nodes[key].append(node)
    emitted_count = sum(emitted_by_tile.values())
    if emitted_count <= 0:
        raise ValueError("water tile overlay placement emitted no objects")
    return {
        "status": WATER_TILE_OVERLAY_STATUS,
        "architecture": WATER_TILE_OVERLAY_ARCHITECTURE,
        "runtimeVisual": WATER_TILE_OVERLAY_RUNTIME_VISUAL,
        "objectMember": WATER_TILE_OVERLAY_OBJECT_MEMBER,
        "donorPrefab": WATER_TILE_OVERLAY_DONOR_PREFAB,
        "idBase": WATER_TILE_OVERLAY_ID_BASE,
        "emittedCount": emitted_count,
        "emittedByTileCode": {str(tile): count for tile, count in sorted(emitted_by_tile.items())},
        "sidHistogram": dict(emitted_by_sid.most_common()),
        "objectIdsBySid": {sid: values for sid, values in sorted(object_ids_by_sid.items())},
        "nodesBySid": {sid: values for sid, values in sorted(nodes_by_sid.items())},
        "objectSidsByTileCode": {str(tile): sid for tile, sid in sorted(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.items())},
        "visualContract": WATER_TILE_OVERLAY_VISUAL_CONTRACT,
        "pathingPolicy": "custom Environment rows intentionally omit nodes; terrain tile codes remain the movement authority",
        "placementPolicy": "one overlay object on each source-ocean node after water tile projection; overlay nodes do not reserve occupancy",
        "exampleNodesByTileCode": {tile: nodes for tile, nodes in sorted(example_nodes.items())},
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
    }

def write_water_tile_overlay_identity_runtime_manifest(summary: dict[str, Any], map_sid: str) -> dict[str, Any]:
    object_ids_by_sid = summary.get("objectIdsBySid")
    nodes_by_sid = summary.get("nodesBySid")
    if not isinstance(object_ids_by_sid, dict) or not isinstance(nodes_by_sid, dict):
        raise ValueError("water tile overlay summary is missing runtime identity arrays")
    if not map_sid:
        raise ValueError("water tile overlay identity manifest requires a map SID for node aliases")
    emitted_count = summary.get("emittedCount")
    if sum(len(values) for values in object_ids_by_sid.values() if isinstance(values, list)) != emitted_count:
        raise ValueError(f"water tile overlay identity object-id count mismatch: {summary}")
    nodes_by_map_sid: dict[str, Any] = {}
    identity_path = water_tile_overlay_identity_output_path()
    if identity_path.is_file():
        existing = read_json(identity_path)
        if existing.get("schema") == WATER_TILE_OVERLAY_IDENTITY_SCHEMA:
            existing_object_ids = existing.get("objectIdsBySid")
            if existing_object_ids is not None and existing_object_ids != object_ids_by_sid:
                raise ValueError("water tile overlay identity object ids changed while preserving existing map-node aliases")
            existing_nodes = existing.get("nodesByMapSid")
            if isinstance(existing_nodes, dict):
                nodes_by_map_sid.update(existing_nodes)
    nodes_by_map_sid[map_sid] = nodes_by_sid
    manifest = {
        "schema": WATER_TILE_OVERLAY_IDENTITY_SCHEMA,
        "status": WATER_TILE_OVERLAY_STATUS,
        "architecture": WATER_TILE_OVERLAY_ARCHITECTURE,
        "runtimeVisual": WATER_TILE_OVERLAY_RUNTIME_VISUAL,
        "objectMember": WATER_TILE_OVERLAY_OBJECT_MEMBER,
        "donorPrefab": WATER_TILE_OVERLAY_DONOR_PREFAB,
        "objectIdBase": WATER_TILE_OVERLAY_ID_BASE,
        "emittedCount": emitted_count,
        "objectSidsByTileCode": summary.get("objectSidsByTileCode"),
        "objectIdsBySid": object_ids_by_sid,
        "nodesByMapSid": {sid: nodes_by_map_sid[sid] for sid in sorted(nodes_by_map_sid)},
        "visualContract": WATER_TILE_OVERLAY_VISUAL_CONTRACT,
        "identityPolicy": "runtime overlay instances resolve by donor-carrier generated map object id first and donor-carrier map-scoped node second, both scoped to recognized Homecoming map SIDs; donor prefab SID is never treated as an overlay SID",
        "nodeIdentityPolicy": "node aliases are scoped by map SID and are only considered when the live object reports the registered donor carrier SID, because single-layer and layered-atlas node coordinates can overlap with different shore variants",
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
    }
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(identity_path, manifest)
    return {**manifest, "output": str(identity_path)}

def find_single_object_id(objects: list[dict[str, Any]], sid: str) -> int:
    matches: list[int] = []
    for group in objects:
        if group.get("sid") == sid:
            matches.extend(int(value) for value in group.get("ids", []) if isinstance(value, int))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {sid} object for native start contract, found {matches}")
    return matches[0]


def find_object_ids(objects: list[dict[str, Any]], sid: str) -> list[int]:
    matches: list[int] = []
    for group in objects:
        if group.get("sid") == sid:
            matches.extend(int(value) for value in group.get("ids", []) if isinstance(value, int))
    return matches


def apply_native_start_contract(objects: list[dict[str, Any]], properties: dict[str, Any]) -> int:
    """Bind the player start hero-spawner. Non-start heroes use append_placed_hero_properties."""

    hero_ids = find_object_ids(objects, "hero-spawner")
    if not hero_ids:
        raise ValueError("expected at least one hero-spawner object for native start contract")
    # Prefer the surface start source when multiple spawners exist.
    start_id = None
    for group in objects:
        if group.get("sid") != "hero-spawner":
            continue
        ids = group.get("ids") or []
        levels = group.get("levels") or []
        for object_id, level in zip(ids, levels):
            if isinstance(object_id, int) and int(level or 0) == 0:
                start_id = object_id
                break
        if start_id is not None:
            break
    if start_id is None:
        start_id = hero_ids[0]
    properties["propSpawns"] = [
        {"type": 0, "id": start_id, "owner": 1, "spawnType": 0, "spawnPointType": 1, "isLocked": False}
    ]
    existing_heroes = [
        row for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict) and row.get("id") != start_id
    ]
    properties["propHeroes"] = [
        {"type": 0, "id": start_id, "isDefined": True, "heroSid": START_HERO_SID},
        *existing_heroes,
    ]
    return start_id


def append_placed_hero_properties(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
    *,
    start_hero_object_id: int,
) -> list[dict[str, Any]]:
    """Bind non-start hero-spawner objects to propHeroes via heroType→heroSid."""

    placed: list[dict[str, Any]] = []
    hero_rows = list(properties.get("propHeroes") or [])
    bound_ids = {int(row["id"]) for row in hero_rows if isinstance(row, dict) and isinstance(row.get("id"), int)}
    for object_id in find_object_ids(objects, "hero-spawner"):
        if object_id == start_hero_object_id or object_id in bound_ids:
            continue
        entity = entities_by_id.get(object_id)
        if entity is None:
            raise ValueError(f"placed hero-spawner {object_id} has no source entity")
        if entity.get("hasGarrison") or entity.get("secondarySkillCount") or entity.get("hasArtifactSet"):
            raise ValueError(
                f"placed hero {entity.get('sourceKey')} has custom army/skills/artifacts with no native propHeroes sink"
            )
        hero_type = entity.get("heroType")
        if not isinstance(hero_type, int):
            raise ValueError(f"placed hero {entity.get('sourceKey')} missing heroType")
        hero_sid = h3m_hero_sid.h3_hero_type_to_hero_sid(hero_type)
        row = {"type": 0, "id": object_id, "isDefined": True, "heroSid": hero_sid}
        hero_rows.append(row)
        placed.append({
            "objectId": object_id,
            "sourceKey": entity.get("sourceKey"),
            "heroType": hero_type,
            "owner": entity.get("owner"),
            "heroSid": hero_sid,
        })
        bound_ids.add(object_id)
    properties["propHeroes"] = hero_rows
    return placed


def find_single_replacement_source(
    surface_entities: list[dict[str, Any]],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    replacement_sid: str,
    *,
    expected_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matches = []
    for entity in surface_entities:
        sid, _, _ = resolve_replacement_sid(entity, substitution_lookup, valid_ids)
        if sid == replacement_sid:
            matches.append(entity)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one source entity for {replacement_sid}, found {len(matches)}")
    entity = matches[0]
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    source_index = entity.get("sourceIndex")
    if not isinstance(source_x, int) or not isinstance(source_y, int) or not isinstance(source_index, int):
        raise ValueError(f"start source entity is missing integer source placement fields: {entity}")
    if expected_source is None:
        expected_source = {
            "heroType": START_HERO_SOURCE_HERO_TYPE,
            "owner": 0,
            "payloadKind": "hero_or_prison",
            "templateAnimation": "ah00_e.def",
            "templateObjectId": 34,
        }
    observed_source = {key: entity.get(key) for key in expected_source}
    if observed_source != expected_source:
        raise ValueError(f"start source does not match expected contract: {observed_source}")
    return {
        "replacementSid": replacement_sid,
        "sourceKey": entity.get("sourceKey"),
        "sourceSid": entity.get("sid"),
        "sourceIndex": source_index,
        "sourceX": source_x,
        "sourceY": source_y,
        "node": target_node(source_x, source_y),
        "sourceHeroType": entity.get("heroType"),
        "sourceOwner": entity.get("owner"),
        "sourcePayloadKind": entity.get("payloadKind"),
        "sourceTemplateAnimation": entity.get("templateAnimation"),
        "sourceTemplateObjectId": entity.get("templateObjectId"),
        "sourceHeroName": START_HERO_SOURCE_NAME,
        "oldenHeroSid": START_HERO_SID,
        "oldenFactionSid": START_FACTION_SID,
    }


def load_native_start_shape() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    container = poc.read_olden_map_container(NATIVE_START_TEMPLATE_MAP)
    meta = container.chunks[0]
    map_data = container.chunks[1]
    meta_shape = {
        key: json.loads(json.dumps(meta.get(key), ensure_ascii=False))
        for key in [
            "economicDifficulties",
            "aiDifficulties",
            "neutralDifficulties",
            "quickStartDifficulties",
            "campaignInfo",
            "banInfoData",
        ]
    }
    start_settings = json.loads(json.dumps(meta.get("startSettings", {}), ensure_ascii=False))
    settings = json.loads(json.dumps(map_data.get("settings", {}), ensure_ascii=False))
    if not start_settings or not settings or any(value is None for value in meta_shape.values()):
        raise ValueError(f"native start template missing start settings: {NATIVE_START_TEMPLATE_MAP}")
    return meta_shape, start_settings, settings


def generate_squad_overlays(global_entities: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    squad_dir = out_dir / SQUAD_OVERLAY_MEMBER_ROOT
    if squad_dir.exists():
        for stale in squad_dir.glob("homecoming_*.json"):
            stale.unlink()
    emitted: dict[str, dict[str, Any]] = {}
    for entity in global_entities:
        if not is_concrete_h3_monster_stack(entity):
            continue
        sid = concrete_monster_squad_sid(entity)
        unit_sid = concrete_monster_unit_sid(entity)
        value_budget = int(concrete_monster_requested_value(entity))
        if value_budget < 1:
            raise ValueError(f"concrete monster value budget must be positive for {entity.get('sourceKey')}: {value_budget}")
        emitted[sid] = {
            "array": [{
                "id": sid,
                "squad": [],
                "useOldSquads": False,
                "rollChance": 0,
                "canBeMainGuard": True,
                "baseSquad": {"units": [{"s": unit_sid, "v": value_budget}]},
                "dynamicSquad": {"requiredValue": value_budget, "units": [unit_sid]},
                "randomSquad": {"maxValue": value_budget, "units": [{"s": unit_sid, "v": value_budget}]},
                "tier": 0,
                "fraction": "",
            }]
        }
    outputs = []
    for sid, doc in sorted(emitted.items()):
        path = squad_dir / f"{sid}.json"
        write_json(path, doc)
        outputs.append({"sid": sid, "member": f"{SQUAD_OVERLAY_MEMBER_ROOT}/{sid}.json", "output": str(path)})
    manifest = {
        "status": "generated_squad_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "count": len(outputs),
        "outputs": outputs,
    }
    write_json(out_dir / "homecoming_squad_overlay_manifest.json", manifest)
    return manifest


def upsert_array_row(doc: dict[str, Any], row: dict[str, Any]) -> None:
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError("Core overlay source must contain an array list")
    row_id = row.get("id")
    if not isinstance(row_id, str):
        raise ValueError(f"overlay row is missing string id: {row}")
    matches = [idx for idx, existing in enumerate(rows) if isinstance(existing, dict) and existing.get("id") == row_id]
    if len(matches) > 1:
        raise ValueError(f"Core overlay source contains duplicate row id {row_id!r}")
    if matches:
        rows[matches[0]] = row
    else:
        rows.append(row)



def upsert_numeric_array_row(doc: dict[str, Any], row: dict[str, Any]) -> None:
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError("Core overlay source must contain an array list")
    row_id = row.get("id")
    if not isinstance(row_id, int):
        raise ValueError(f"numeric overlay row is missing int id: {row}")
    matches = [idx for idx, existing in enumerate(rows) if isinstance(existing, dict) and existing.get("id") == row_id]
    if len(matches) > 1:
        raise ValueError(f"Core overlay source contains duplicate numeric row id {row_id!r}")
    if matches:
        rows[matches[0]] = row
    else:
        rows.append(row)


def read_core_json(member: str) -> dict[str, Any]:
    """Prefer an already-written Core overlay member so later overlays merge, not clobber."""
    overlay_path = OUT_ROOT / "core_overlay" / member
    if overlay_path.is_file():
        return json.loads(overlay_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        return json.loads(core.read(member).decode("utf-8-sig"))


def remove_retired_homm3_boat_object_overlay_outputs() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    retired_outputs = [
        HOMM3_BOAT_OBJECT_MEMBER,
        "homecoming_boat_object_overlay_manifest.json",
    ]
    for relative_path in retired_outputs:
        path = out_dir / relative_path
        if path.exists():
            path.unlink()
    for directory in [
        out_dir / "DB" / "map" / "objects",
        out_dir / "DB" / "map",
        out_dir / "DB",
    ]:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    return {
        "status": "retired_until_validated_direct_state_water_traversal",
        "retiredObjectSid": HOMM3_BOAT_SID,
        "retiredMember": HOMM3_BOAT_OBJECT_MEMBER,
        "runtimeHook": ACTIVE_WATER_RUNTIME_HOOK,
        "retiredOutputs": retired_outputs,
    }


def remove_retired_water_tile_overlay_outputs() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    retired_outputs = [
        WATER_TILE_OVERLAY_OBJECT_MEMBER,
        "homecoming_water_tile_overlay_object_manifest.json",
        str(WATER_TILE_OVERLAY_IDENTITY_RELATIVE_PATH).replace("\\", "/"),
    ]
    paths = [out_dir / WATER_TILE_OVERLAY_OBJECT_MEMBER, out_dir / "homecoming_water_tile_overlay_object_manifest.json"]
    source_identity = WATER_TILE_OVERLAY_IDENTITY_SOURCE_PATH
    if source_identity.exists():
        paths.append(source_identity)
    for path in paths:
        if path.exists():
            path.unlink()
    for directory in [
        out_dir / "DB" / "map" / "objects",
        out_dir / "DB" / "map",
        out_dir / "DB",
        source_identity.parent,
    ]:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    return {
        "status": WATER_TILE_OVERLAY_STATUS,
        "architecture": WATER_TILE_OVERLAY_ARCHITECTURE,
        "retiredMember": WATER_TILE_OVERLAY_OBJECT_MEMBER,
        "retiredIdentityRelativePath": str(WATER_TILE_OVERLAY_IDENTITY_RELATIVE_PATH).replace("\\", "/"),
        "reason": "runtime map-object hook did not apply in Golden Era testing; display water now uses terrain material aliasing",
        "retiredOutputs": retired_outputs,
    }



def retire_homm3_boat_runtime_objects(objects: list[dict[str, Any]]) -> dict[str, Any]:
    removed_groups = remove_object_groups_by_sid(objects, HOMM3_BOAT_SID)
    removed_ids = [value for group in removed_groups for value in group.get("ids", []) if isinstance(value, int)]
    return {
        "status": "retired_display_water_visual_contract_replaces_direct_state_traversal",
        "retiredObjectSid": HOMM3_BOAT_SID,
        "replacement": NATIVE_WATER_PENALTY_ARCHITECTURE,
        "runtimeHook": ACTIVE_WATER_RUNTIME_HOOK,
        "removedBoatObjectGroupCount": len(removed_groups),
        "sourceBoatAnchorCount": len(removed_ids),
        "sourceBoatAnchorIds": sorted(removed_ids),
    }


def remove_retired_water_traversal_plan_outputs() -> dict[str, Any]:
    removed_outputs: list[str] = []
    path = WATER_TRAVERSAL_PLAN_SOURCE_PATH
    if path.exists():
        path.unlink()
        removed_outputs.append(str(path))
    for directory in [path.parent]:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    return {
        "status": "retired_display_water_visual_contract_replaces_direct_state_plan",
        "retiredRelativePath": str(WATER_TRAVERSAL_PLAN_RELATIVE_PATH).replace("\\", "/"),
        "replacement": NATIVE_WATER_PENALTY_ARCHITECTURE,
        "runtimeHook": ACTIVE_WATER_RUNTIME_HOOK,
    }

def generate_water_tile_penalty_overlay() -> dict[str, Any]:
    """Retired: ocean now emits native vanilla water tile ids 18-22 from Core.zip without Sand clones."""
    manifest = {
        "status": "retired_native_vanilla_water_tiles_replace_display_water_penalty_overlay",
        "architecture": DISPLAY_WATER_ARCHITECTURE,
        "member": WATER_TILE_PENALTY_MEMBER,
        "tileIds": list(DISPLAY_WATER_TILE_CODES),
        "deepWaterTileId": DISPLAY_WATER_TILE_CODE,
        "shorelineTileIdsByEdge": dict(DISPLAY_WATER_SHORE_TILE_CODES_BY_EDGE),
        "vanillaOceanWaterMapId": VANILLA_OCEAN_WATER_ID,
        "proofBoundary": "ocean uses unmodified Core.zip tiles.json rows for ids 18-22",
    }
    out_dir = OUT_ROOT / "core_overlay"
    write_json(out_dir / "homecoming_display_water_tile_overlay_manifest.json", manifest)
    return manifest


def require_core_array_row(doc: dict[str, Any], member: str, row_id: str) -> dict[str, Any]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain array rows")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == row_id]
    if len(matches) != 1:
        raise ValueError(f"{member} must contain exactly one {row_id!r} row")
    return matches[0]



def optional_core_array_row(doc: dict[str, Any], member: str, row_id: str) -> dict[str, Any] | None:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain array rows")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == row_id]
    if len(matches) > 1:
        raise ValueError(f"{member} contains duplicate {row_id!r} rows")
    return matches[0] if matches else None


def require_absent_or_exact_core_row(doc: dict[str, Any], member: str, expected_row: dict[str, Any]) -> None:
    row_id = expected_row.get("id")
    if not isinstance(row_id, str):
        raise ValueError(f"expected overlay row is missing string id: {expected_row}")
    existing = optional_core_array_row(doc, member, row_id)
    if existing is not None and existing != expected_row:
        raise ValueError(f"{member} already contains conflicting {row_id!r} row: {existing}")


def generate_homm3_pathability_alignment_overlay(visual_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    donor_row: dict[str, Any] | None = None
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get("id") == HOMM3_PATHING_BLOCKER_DONOR_SID:
                    donor_row = row
                    break
            if donor_row is not None:
                break
    if not isinstance(donor_row, dict):
        raise ValueError(f"missing Core donor row {HOMM3_PATHING_BLOCKER_DONOR_SID!r} for pathability alignment overlay")
    blocker_row = homm3_pathing_blocker_object_row(donor_row)
    rows = [blocker_row, *sorted(visual_rows.values(), key=lambda item: str(item.get("id")))]
    out_path = out_dir / HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER
    write_json(out_path, {"array": rows})
    manifest = {
        "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": HOMM3_PATHABILITY_ALIGNMENT_POLICY,
        "humanDecision": HOMM3_PATHABILITY_ALIGNMENT_HUMAN_DECISION,
        "member": HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER,
        "output": str(out_path),
        "pathingBlockerSid": HOMM3_PATHING_BLOCKER_SID,
        "pathingBlockerDonorSid": HOMM3_PATHING_BLOCKER_DONOR_SID,
        "pathingVisualSidCount": len(visual_rows),
        "pathingVisualSids": sorted(visual_rows),
        "proofBoundary": "source/static/generated-artifact pathability alignment overlay; runtime pathfinder and cloned visual interaction remain user-unvalidated",
    }
    write_json(out_dir / "homecoming_pathability_alignment_overlay_manifest.json", manifest)
    return manifest


def generate_water_tile_overlay_object_overlay() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    rows = homecoming_water_tile_overlay_object_rows()
    expected_sids = set(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.values())
    actual_sids = {row.get("id") for row in rows if isinstance(row, dict)}
    if actual_sids != expected_sids:
        raise ValueError(f"water tile overlay object row SID mismatch: {actual_sids} != {expected_sids}")
    for row in rows:
        if row.get("nodes") is not None or row.get("isInteractable") is not None:
            raise ValueError(f"water tile overlay rows must stay no-footprint non-interactable Environment rows: {row}")
    out_path = out_dir / WATER_TILE_OVERLAY_OBJECT_MEMBER
    write_json(out_path, {"array": rows})
    manifest = {
        "status": WATER_TILE_OVERLAY_STATUS,
        "architecture": WATER_TILE_OVERLAY_ARCHITECTURE,
        "member": WATER_TILE_OVERLAY_OBJECT_MEMBER,
        "output": str(out_path),
        "runtimeVisual": WATER_TILE_OVERLAY_RUNTIME_VISUAL,
        "donorPrefab": WATER_TILE_OVERLAY_DONOR_PREFAB,
        "objectSidsByTileCode": {str(tile): sid for tile, sid in sorted(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.items())},
        "objectSids": sorted(expected_sids),
        "pathingPolicy": "ObjectConfig rows omit nodes so they do not define blocking, gates, or traversal cost; underlying native water terrain remains authoritative.",
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
    }
    write_json(out_dir / "homecoming_water_tile_overlay_object_manifest.json", manifest)
    return manifest

def generate_subterranean_gate_portal_overlay() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    object_doc = read_core_json(HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER)
    portal_doc = read_core_json(HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER)
    donor_row = require_core_array_row(
        object_doc,
        HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER,
        HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID,
    )
    object_row = homm3_subterranean_gate_portal_object_row(donor_row)
    portal_row = {"id": HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, "goodsValue": 0}
    require_absent_or_exact_core_row(object_doc, HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER, object_row)
    require_absent_or_exact_core_row(portal_doc, HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER, portal_row)
    upsert_array_row(object_doc, object_row)
    upsert_array_row(portal_doc, portal_row)
    object_path = out_dir / HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER
    portal_path = out_dir / HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER
    write_json(object_path, object_doc)
    write_json(portal_path, portal_doc)
    manifest = {
        "status": HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_STATUS,
        "architecture": HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_ARCHITECTURE,
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "objectSid": HOMM3_SUBTERRANEAN_GATE_PORTAL_SID,
        "donorSid": HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID,
        "prefab": HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB,
        "objectMember": HOMM3_SUBTERRANEAN_GATE_PORTAL_OBJECT_MEMBER,
        "portalLogicMember": HOMM3_SUBTERRANEAN_GATE_PORTAL_LOGIC_MEMBER,
        "outputs": {
            "object": str(object_path),
            "portalLogic": str(portal_path),
        },
        "proofBoundary": "source/static and generated-artifact validated; runtime preview remains unvalidated until installed Core.zip and layered map are exercised in Golden Era",
    }
    write_json(out_dir / "homecoming_subterranean_gate_portal_overlay_manifest.json", manifest)
    return manifest


def generate_homm3_landon_object_overlay() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    fxs_doc = read_core_json(HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER)
    interactables_doc = read_core_json(HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER)
    map_event_donor = require_core_array_row(
        fxs_doc,
        HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER,
        HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
    )
    castle_city_donor = require_core_array_row(
        interactables_doc,
        HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
    )
    dungeon_city_donor = require_core_array_row(
        interactables_doc,
        HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
    )
    barracks_donors = {
        donor_sid: require_core_array_row(
            interactables_doc,
            HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
            donor_sid,
        )
        for donor_sid in HOMM3_LANDON_BARRACKS_BY_DONOR.keys()
    }
    resource_wood_donor = _core_object_row_by_id(HOMM3_FLOTSAM_PICKUP_DONOR_SID)
    if not isinstance(resource_wood_donor, dict):
        raise ValueError(f"missing {HOMM3_FLOTSAM_PICKUP_DONOR_SID!r} donor for flotsam pickup overlay")
    object_rows = {
        HOMM3_LANDON_MAP_EVENT_MARKER_SID: homm3_landon_map_event_marker_object_row(map_event_donor),
        HOMM3_LANDON_CASTLE_CITY_SID: homm3_landon_bottom_center_gate_city_object_row(
            castle_city_donor,
            clone_sid=HOMM3_LANDON_CASTLE_CITY_SID,
            donor_sid=HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
        ),
        HOMM3_LANDON_DUNGEON_CITY_SID: homm3_landon_bottom_center_gate_city_object_row(
            dungeon_city_donor,
            clone_sid=HOMM3_LANDON_DUNGEON_CITY_SID,
            donor_sid=HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
        ),
        HOMM3_FLOTSAM_PICKUP_SID: homm3_flotsam_pickup_object_row(resource_wood_donor),
    }
    for donor_sid, clone_sid in HOMM3_LANDON_BARRACKS_BY_DONOR.items():
        object_rows[clone_sid] = homm3_landon_barracks_object_row(
            barracks_donors[donor_sid],
            donor_sid=donor_sid,
            clone_sid=clone_sid,
        )
    custom_objects_doc: dict[str, Any] = {"array": []}
    for row in object_rows.values():
        if row["id"] == HOMM3_LANDON_MAP_EVENT_MARKER_SID:
            member = HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER
            doc = fxs_doc
        elif row["id"] == HOMM3_FLOTSAM_PICKUP_SID:
            member = HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER
            doc = custom_objects_doc
        else:
            member = HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER
            doc = interactables_doc
        if member != HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER:
            # Owned land-on clones may be regenerated with updated GATE geometry.
            if row["id"] not in HOMM3_LANDON_OBJECT_SIDS:
                require_absent_or_exact_core_row(doc, member, row)
        upsert_array_row(doc, row)

    logic_outputs: dict[str, str] = {}
    logic_specs = [
        (
            HOMM3_LANDON_CASTLE_CITY_LOGIC_MEMBER,
            HOMM3_LANDON_CASTLE_CITY_DONOR_LOGIC_MEMBER,
            HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
            HOMM3_LANDON_CASTLE_CITY_SID,
        ),
        (
            HOMM3_LANDON_DUNGEON_CITY_LOGIC_MEMBER,
            HOMM3_LANDON_DUNGEON_CITY_DONOR_LOGIC_MEMBER,
            HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
            HOMM3_LANDON_DUNGEON_CITY_SID,
        ),
    ]
    for logic_member, donor_logic_member, donor_logic_sid, clone_sid in logic_specs:
        donor_logic_doc = read_core_json(donor_logic_member)
        donor_logic_row = require_core_array_row(donor_logic_doc, donor_logic_member, donor_logic_sid)
        clone_logic_row = clone_core_objects_logic_row(
            donor_logic_row,
            donor_sid=donor_logic_sid,
            clone_sid=clone_sid,
        )
        logic_doc = {"array": [clone_logic_row]}
        logic_path = out_dir / logic_member
        write_json(logic_path, logic_doc)
        logic_outputs[clone_sid] = str(logic_path)

    barracks_logic_doc = read_core_json(HOMM3_LANDON_BARRACKS_LOGIC_MEMBER)
    for donor_sid, clone_sid in HOMM3_LANDON_BARRACKS_BY_DONOR.items():
        barracks_logic_row = require_core_array_row(
            barracks_logic_doc,
            HOMM3_LANDON_BARRACKS_LOGIC_MEMBER,
            donor_sid,
        )
        barracks_clone_logic_row = clone_core_objects_logic_row(
            barracks_logic_row,
            donor_sid=donor_sid,
            clone_sid=clone_sid,
        )
        require_absent_or_exact_core_row(barracks_logic_doc, HOMM3_LANDON_BARRACKS_LOGIC_MEMBER, barracks_clone_logic_row)
        upsert_array_row(barracks_logic_doc, barracks_clone_logic_row)
        logic_outputs[clone_sid] = str(out_dir / HOMM3_LANDON_BARRACKS_LOGIC_MEMBER)
    barracks_logic_path = out_dir / HOMM3_LANDON_BARRACKS_LOGIC_MEMBER
    write_json(barracks_logic_path, barracks_logic_doc)
    for clone_sid in HOMM3_LANDON_BARRACKS_SIDS:
        logic_outputs[clone_sid] = str(barracks_logic_path)

    fxs_path = out_dir / HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER
    interactables_path = out_dir / HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER
    custom_objects_path = out_dir / HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER
    write_json(fxs_path, fxs_doc)
    write_json(interactables_path, interactables_doc)
    write_json(custom_objects_path, custom_objects_doc)

    guardhouse_alignment = verify_homm3_landon_barracks_guardhouse_visit_gate_alignment(
        object_rows[HOMM3_LANDON_BARRACKS_CASTLE_1_SID]
    )
    if not guardhouse_alignment["bottomCenterGate"] or guardhouse_alignment["gateCount"] != 1:
        raise ValueError(
            "homm3_landon_barracks_castle_1 bottom-center GATE contract failed for Guardhouse dwelling "
            f"{GUARDHOUSE_DWELLING_SOURCE_KEY}: {guardhouse_alignment}"
        )

    manifest = {
        "status": HOMM3_LANDON_OBJECT_OVERLAY_STATUS,
        "architecture": HOMM3_LANDON_OBJECT_OVERLAY_ARCHITECTURE,
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "objectSids": sorted(object_rows),
        "donorsBySid": {
            HOMM3_LANDON_MAP_EVENT_MARKER_SID: HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
            HOMM3_LANDON_CASTLE_CITY_SID: HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
            HOMM3_LANDON_DUNGEON_CITY_SID: HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
            **{clone: donor for donor, clone in HOMM3_LANDON_BARRACKS_BY_DONOR.items()},
            HOMM3_FLOTSAM_PICKUP_SID: HOMM3_FLOTSAM_PICKUP_DONOR_SID,
        },
        "objectMembers": {
            HOMM3_LANDON_MAP_EVENT_MARKER_SID: HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER,
            HOMM3_LANDON_CASTLE_CITY_SID: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
            HOMM3_LANDON_DUNGEON_CITY_SID: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
            **{clone: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER for clone in HOMM3_LANDON_BARRACKS_SIDS},
            HOMM3_FLOTSAM_PICKUP_SID: HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER,
        },
        "logicOutputs": logic_outputs,
        "outputs": {
            "fxObjects": str(fxs_path),
            "interactables": str(interactables_path),
            "customObjects": str(custom_objects_path),
        },
        "landonBarracksSids": sorted(HOMM3_LANDON_BARRACKS_SIDS),
        "guardhouseVisitGateAlignment": guardhouse_alignment,
        "proofBoundary": "source/static and generated-artifact validated; runtime land-on interaction remains user-unvalidated",
    }
    write_json(out_dir / "homecoming_landon_object_overlay_manifest.json", manifest)
    return manifest

def generate_building_restriction_overlays() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    ban_member = "DB/buildings_bans/custom_maps_banlists.json"
    preset_member = "DB/buildings_constructions/custom_maps_buildings_presets.json"
    campaign_bans = read_core_json("DB/buildings_bans/general_banlists.json")
    default_presets = read_core_json("DB/buildings_constructions/general_buildings_presets.json")
    ban_source = next((row for row in campaign_bans.get("array", []) if isinstance(row, dict) and row.get("id") == "campaign_default_buildings_ban"), None)
    preset_source = next((row for row in default_presets.get("array", []) if isinstance(row, dict) and row.get("id") == "poor_buildings_construction"), None)
    if not isinstance(ban_source, dict) or not isinstance(preset_source, dict):
        raise ValueError("Core.zip is missing campaign/default building restriction source rows")
    ban_doc = read_core_json(ban_member)
    preset_doc = read_core_json(preset_member)
    ban_row = json.loads(json.dumps(ban_source, ensure_ascii=False))
    preset_row = json.loads(json.dumps(preset_source, ensure_ascii=False))
    ban_row["id"] = HOMECOMING_BUILDINGS_BAN_SID
    preset_row["id"] = HOMECOMING_BUILDINGS_CONSTRUCTION_SID
    upsert_array_row(ban_doc, ban_row)
    upsert_array_row(preset_doc, preset_row)
    ban_path = out_dir / ban_member
    preset_path = out_dir / preset_member
    write_json(ban_path, ban_doc)
    write_json(preset_path, preset_doc)
    manifest = {
        "status": "generated_building_restrictions_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "outputs": {
            "buildingsBan": str(ban_path),
            "buildingsConstruction": str(preset_path),
        },
        "members": {
            "buildingsBan": ban_member,
            "buildingsConstruction": preset_member,
        },
        "banSid": HOMECOMING_BUILDINGS_BAN_SID,
        "constructionSid": HOMECOMING_BUILDINGS_CONSTRUCTION_SID,
        "settingsSid": HOMECOMING_BUILDINGS_SETTINGS_SID,
        "banSourceSid": "campaign_default_buildings_ban",
        "constructionSourceSid": "poor_buildings_construction",
        "constructionSourceReason": "default_buildings_construction starts with Tavern constructed; Homecoming needs Tavern absent plus banned for single-hero campaign behavior.",
    }
    write_json(out_dir / "homecoming_building_restrictions_overlay_manifest.json", manifest)
    return manifest


def generate_quickstart_overlay(map_sid: str) -> dict[str, Any]:
    quickstart = poc.read_core_quickstart(poc.OLDEN_CORE_ZIP)
    scenarios = quickstart.get("scenarios")
    if not isinstance(scenarios, list) or "Thirst_for_Power" not in scenarios:
        raise ValueError("Core quickStart.json scenarios are missing the native Thirst_for_Power anchor")
    if scenarios.count(map_sid) > 1:
        raise ValueError(f"Core quickStart.json contains duplicate {map_sid!r} entries")
    if map_sid not in scenarios:
        scenarios = [*scenarios, map_sid]
    quickstart["scenarios"] = scenarios
    out_dir = OUT_ROOT / "core_overlay"
    out_path = out_dir / "quickStart.json"
    write_json(out_path, quickstart)
    manifest = {
        "status": "generated_catalog_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "coreEntry": "DB/quickStart.json",
        "mapSid": map_sid,
        "scenarioAnchor": "Thirst_for_Power",
        "output": str(out_path),
    }
    write_json(out_dir / "quickstart_catalog_overlay_manifest.json", manifest)
    return manifest



def generate_intro_dialog_overlay(intro_text: str) -> dict[str, Any]:
    return generate_campaign_dialog_overlay(
        [
            {
                "id": INTRO_DIALOG_SID,
                "title": "Homecoming",
                "text": intro_text,
            }
        ]
    )


def generate_campaign_dialog_overlay(entries: list[dict[str, str]]) -> dict[str, Any]:
    if not entries:
        raise ValueError("campaign dialog overlay requires at least one dialog entry")
    out_dir = OUT_ROOT / "core_overlay"
    english_member = "Lang/english/texts/dialogues.json"
    english_path = out_dir / english_member
    dialog_outputs: dict[str, str] = {}
    replacement_tokens: dict[str, str] = {}
    for entry in entries:
        dialog_sid = str(entry["id"])
        title = str(entry.get("title") or "Homecoming")
        text = str(entry.get("text") or "").strip()
        if not text:
            raise ValueError(f"campaign dialog {dialog_sid!r} is missing text")
        # Legacy intro SID keeps historical Core token names (not dialogue_*_homecoming_intro_dialog_*).
        if dialog_sid == INTRO_DIALOG_SID:
            title_token = "dialogue_title_homecoming_intro"
            text_token = "dialogue_text_homecoming_intro_0"
        else:
            title_token = f"dialogue_title_{dialog_sid}"
            text_token = f"dialogue_text_{dialog_sid}_0"
        replacement_tokens[title_token] = title
        replacement_tokens[text_token] = text
        dialog_member = f"DB/dialogs/dialogs/custom_maps/Homecoming/{dialog_sid}.json"
        dialog_path = out_dir / dialog_member
        dialog_doc = {
            "array": [{
                "id": dialog_sid,
                "localization": True,
                "slides": [{
                    "id": "start",
                    "fon": "",
                    "avatars": [],
                    "title": {"sid": title_token, "position": 3},
                    "text": text_token,
                    "next": "ending",
                }, {
                    "id": "ending",
                    "fon": "",
                    "text": "",
                    "invokeOnlyActions": True,
                    "end": True,
                }],
            }]
        }
        write_json(dialog_path, dialog_doc)
        dialog_outputs[dialog_sid] = str(dialog_path)
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        english_doc = json.loads(core.read(english_member).decode("utf-8-sig"))
    tokens = english_doc.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError(f"{english_member} must contain a tokens list")
    existing = {row.get("sid"): row for row in tokens if isinstance(row, dict)}
    for sid, text in replacement_tokens.items():
        if sid in existing:
            existing[sid]["text"] = text
        else:
            tokens.append({"sid": sid, "text": text})
    english_doc["array"] = english_doc.get("array", [])
    write_json(english_path, english_doc)
    try:
        import homecoming_localization as homecoming_lang

        homecoming_lang.write_lang_overlay(out_dir, Path(poc.OLDEN_CORE_ZIP))
    except Exception as ex:
        raise RuntimeError(f"Homecoming multilingual Lang overlay failed after dialog generate: {ex}") from ex
    manifest = {
        "status": "generated_dialog_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "englishMember": english_member,
        "dialogSids": [entry["id"] for entry in entries],
        "outputs": {"dialogs": dialog_outputs, "english": str(english_path)},
    }
    write_json(out_dir / "homecoming_intro_dialog_overlay_manifest.json", manifest)
    return manifest


def require_current_substitution_map() -> None:
    if not SUBSTITUTION_PATH.exists():
        raise FileNotFoundError(
            f"missing reusable Homecoming substitution map: {SUBSTITUTION_PATH}. "
            "Run experiments/campaign_port_poc/build_homecoming_entity_substitution_map.py as an explicit audit/regeneration step."
        )


def generate_map() -> dict[str, Any]:
    require_current_substitution_map()
    alignment = read_json(ALIGNMENT_PATH)
    layered_ir = read_json(LAYERED_IR_PATH)
    substitution = read_json(SUBSTITUTION_PATH)
    core_catalog = read_json(CORE_CATALOG_PATH)
    valid_ids = {row["id"] for row in core_catalog.get("mapObjects", []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
    valid_ids.add(HOMM3_BOAT_SID)
    valid_ids.add(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
    valid_ids.update(HOMM3_LANDON_OBJECT_SIDS)
    valid_ids.add(HOMM3_PATHING_BLOCKER_SID)
    valid_ids.add(HOMM3_FLOTSAM_PICKUP_SID)
    substitution_lookup = build_substitution_lookup(substitution)
    native_object_configs = load_native_object_configs(valid_ids)

    surface_map_data = alignment["container"]["chunks"][1]
    global_entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    layer_histogram = Counter(entity.get("sourceLayer") for entity in global_entities)
    if dict(layer_histogram) != {0: 1453, 1: 400}:
        raise ValueError(f"unexpected source layer histogram: {dict(layer_histogram)}")
    surface_entities_all = [entity for entity in global_entities if entity.get("sourceLayer") == SOURCE_LAYER]
    surface_border_overhang_entities = [entity for entity in surface_entities_all if not is_in_source_bounds(entity)]
    surface_entities = [entity for entity in surface_entities_all if is_in_source_bounds(entity)]
    underground_entities = [entity for entity in global_entities if entity.get("sourceLayer") == 1]

    projected = project_arrays(surface_map_data)
    display_water = summarize_display_water_projection(surface_map_data, projected)
    shoreline_rivers, shoreline_river_summary = build_ocean_shoreline_rivers(surface_map_data)
    remove_retired_water_layer_outputs()
    property_required_sids = discover_native_property_required_sids()
    alignment_story = alignment["container"]["chunks"][3]
    map_event_specs = campaign_script.map_event_specs_by_source_key(alignment_story)
    start_source = find_single_replacement_source(surface_entities, substitution_lookup, valid_ids, "hero-spawner")
    objects, object_properties, object_stats, pathability_visual_rows = build_surface_objects(
        surface_entities,
        substitution_lookup,
        valid_ids,
        property_required_sids,
        native_object_configs,
        surface_map_data=surface_map_data,
        map_event_specs=map_event_specs,
        enable_pathability_visual_clones=False,
    )
    boat_placement_adjustments = adjust_homm3_boat_placements(objects, projected)
    retired_boat_runtime_objects = retire_homm3_boat_runtime_objects(objects)
    retired_water_traversal_plan = remove_retired_water_traversal_plan_outputs()
    retired_boat_object_overlay = remove_retired_homm3_boat_object_overlay_outputs()
    retired_water_tile_overlay = remove_retired_water_tile_overlay_outputs()
    environment_decoration = add_environment_decorations(objects, projected, shoreline_rivers, valid_ids)
    object_stats["footprintGlobalGapFillAfterDecorations"] = object_stats.get("footprintGlobalGapFill")
    object_stats["pathabilityGapFill"] = {
        "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": footprint_alignment.FOOTPRINT_ALIGNMENT_POLICY,
        "phase": "retired_homm3_pathing_blocker_gap_fill",
        "gapFillBlockerCount": 0,
        "proofBoundary": "global scenery gap-fill runs during build_surface_objects footprint alignment",
    }
    pathability_alignment_overlay = generate_homm3_pathability_alignment_overlay(pathability_visual_rows)
    object_stats["emittedObjectGroupCount"] = len(objects)
    object_stats["propertyRowHistogram"] = {key: len(value) for key, value in sorted(object_properties.items()) if isinstance(value, list) and value}
    object_stats["retiredWaterTileOverlay"] = retired_water_tile_overlay
    object_stats["generatedEnvironmentDecoration"] = environment_decoration
    object_stats["generatedEnvironmentDecorationCount"] = environment_decoration["emittedCount"]
    hero_spawner_id = apply_native_start_contract(objects, object_properties)
    entities_by_id = {
        int(entity["sourceIndex"]): entity
        for entity in surface_entities
        if isinstance(entity.get("sourceIndex"), int)
    }
    placed_heroes = append_placed_hero_properties(
        objects,
        object_properties,
        entities_by_id,
        start_hero_object_id=hero_spawner_id,
    )
    object_stats["placedNonStartHeroes"] = placed_heroes
    object_stats["deferredNonStartHeroSpawnerCount"] = 0
    object_stats["deferredNonStartHeroSpawners"] = []
    if start_source["sourceIndex"] != hero_spawner_id:
        raise ValueError(f"hero-spawner id {hero_spawner_id} does not match start source index {start_source['sourceIndex']}")
    meta_shape, start_settings, native_settings = load_native_start_shape()
    native_settings["heroCountMin"] = 1
    native_settings["heroCountMax"] = 1
    native_settings["heroCountIncrement"] = 1
    native_settings["enableCustomHeroMaxLevel"] = True
    native_settings["customHeroMaxLevel"] = 3
    native_settings["mapWinConditions"] = []
    native_settings["idSidesWithoutTimer"] = []
    native_settings["isScenario"] = False
    # Allow auto-battle vs neutrals/guards; block auto vs enemy heroes.
    native_settings["disableAutoBattleAgainstEnemyHeroes"] = True

    container = poc.read_olden_map_container(poc.PLAYABLE_TEMPLATE_MAP)
    chunks = json.loads(json.dumps(container.chunks, ensure_ascii=False))
    meta = chunks[0]
    map_data = chunks[1]
    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()
    meta.update({
        "title": TITLE,
        "template": "",
        "gameMode": 0,
        "endController": 0,
        "economicDifficulties": meta_shape["economicDifficulties"],
        "aiDifficulties": meta_shape["aiDifficulties"],
        "neutralDifficulties": meta_shape["neutralDifficulties"],
        "quickStartDifficulties": meta_shape["quickStartDifficulties"],
        "campaignInfo": meta_shape["campaignInfo"],
        "desc": DESCRIPTION,
        "displayWinCondition": DESCRIPTION,
        "hashSum": map_hash,
        "nameFromLocalization": False,
        "descFromLocalization": False,
        "spawns": {
            "playersCount": 1,
            "spawns": [
                {
                    "owner": 1,
                    "spawnType": 0,
                    "playerId": "",
                    "spawnPointType": 1,
                    "isCityDefined": False,
                    "factionSid": START_FACTION_SID,
                    "isHeroDefined": True,
                    "heroSid": START_HERO_SID,
                    "colorId": -1,
                    "isAlive": True,
                    "isLocked": False,
                }
            ],
            "takenHeroes": [START_HERO_SID],
        },
        "startSettings": start_settings,
        "sizeX": OLDEN_WIDTH,
        "sizeZ": OLDEN_HEIGHT,
        "banInfoData": meta_shape["banInfoData"],
        "daysInGame": 0,
        "isAutoSave": False,
        "currentTurnMode": 0,
        "isScenario": False,
    })
    map_data.update({
        "fileMapName": MAP_SID,
        "mapName": TITLE,
        "mapNameFromLoc": False,
        "mapDesc": DESCRIPTION,
        "mapDescFromLoc": False,
        "sizeX_": OLDEN_WIDTH,
        "sizeZ_": OLDEN_HEIGHT,
        "tilesMap": projected["tilesMap"],
        "levelsMap": projected["levelsMap"],
        "climbsMap": projected["climbsMap"],
        "roadsMap": projected["roadsMap"],
        "waterMap": projected["waterMap"],
        "customAreasPainting": projected["customAreasPainting"],
        "views": [generated_surface_view()],
        "settings": native_settings,
        "objects": objects,
        "objectsProperties": object_properties,
        "areas": [{"id": 0, "nodes": list(range(OLDEN_WIDTH * OLDEN_HEIGHT))}],
        "objectsFreeId": max((value for group in objects for value in group.get("ids", []) if isinstance(value, int)), default=-1) + 1,
        "squads": [],
        "squadsFreeId": 1,
        "markers": [],
        "markersFreeId": 0,
        "rivers": shoreline_rivers,
        "keyObjects": [],
        "objectValuesOverrides": {"list": []},
        "takenHeroes": [START_HERO_SID],
        "areasVersion": 1,
        "haveCustomAreas": False,
        "generatorChecksum": "",
    })
    scenario_menu_shell.apply_menu_shell(meta, map_data, MAP_SID)
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    mission_id = "homecoming"
    runtime_dialog_lines = campaign_script.build_runtime_dialog_lines(mission_id, alignment_story)
    chunks[3] = campaign_script.build_runtime_script_chunk(
        mission_id,
        alignment_story,
        dialog_lines=runtime_dialog_lines,
        featured_city_capture_sids={},
    )

    out_maps = OUT_ROOT / "maps"
    out_map = out_maps / f"{MAP_SID}.map"
    out_json = out_maps / f"{MAP_SID}.json"
    poc.write_olden_map_container(out_map, poc.OldenMapContainer(container.version, container.prefix_suffix, chunks), map_hash)
    write_json(out_json, campaign_script.map_quest_sidecar_payload(chunks[3]))
    squad_overlay = generate_squad_overlays(global_entities)
    quickstart = generate_quickstart_overlay(MAP_SID)
    dialog_entries = campaign_script.core_dialog_entries_from_alignment(mission_id, alignment_story)
    dialog_entries.extend(
        campaign_script.core_dialog_entries_from_monster_messages(
            mission_id,
            global_entities,
            mission_title=alignment_story.get("missionTitle"),
        )
    )
    intro_text = "\n\n".join((layered_ir.get("mission") or {}).get("briefingTexts") or [])
    if not intro_text:
        raise ValueError(f"missing Homecoming briefing text in {LAYERED_IR_PATH}")
    # Keep legacy intro SID for install/validator compatibility; QuestScript uses briefing_0+.
    dialog_entries = [
        {"id": INTRO_DIALOG_SID, "title": "Homecoming", "text": intro_text},
        *[entry for entry in dialog_entries if entry.get("id") != INTRO_DIALOG_SID],
    ]
    intro_dialog = generate_campaign_dialog_overlay(dialog_entries)
    building_restrictions = generate_building_restriction_overlays()
    water_tile_penalty = generate_water_tile_penalty_overlay()
    subterranean_gate_portal = generate_subterranean_gate_portal_overlay()
    landon_object_overlay = generate_homm3_landon_object_overlay()
    object_stats["pathabilityAlignmentOverlay"] = {
        "status": pathability_alignment_overlay["status"],
        "policy": pathability_alignment_overlay["policy"],
        "member": pathability_alignment_overlay["member"],
        "pathingBlockerSid": pathability_alignment_overlay["pathingBlockerSid"],
        "pathingVisualSidCount": pathability_alignment_overlay["pathingVisualSidCount"],
        "output": pathability_alignment_overlay["output"],
    }
    display_water["tileConfig"] = {
        "status": NATIVE_WATER_PENALTY_STATUS,
        "architecture": NATIVE_WATER_PENALTY_ARCHITECTURE,
        "member": WATER_TILE_PENALTY_MEMBER,
        "tileIds": list(NATIVE_WATER_TILE_CODES),
        "deepWaterTileId": NATIVE_WATER_TILE_CODE,
        "shorelineTileIdsByEdge": dict(NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE),
        "vanillaOceanWaterMapId": VANILLA_OCEAN_WATER_ID,
        "behaviorDonorTileId": DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE,
        "behaviorDonorBiome": DISPLAY_WATER_BEHAVIOR_DONOR_BIOME,
        "penalty": NATIVE_WATER_TERRAIN_PENALTY,
        "proofBoundary": "ocean uses unmodified Core.zip tiles.json rows for ids 18-22",
        "displayIntent": "ocean uses native vanilla water terrain tile ids with vanilla waterMap overlay id 18",
        "knownLimit": "runtime visual quality and boat pickup remain user-unvalidated until in-game retest",
    }
    display_water["waterMapOverlay"] = {
        "status": DISPLAY_WATER_STATUS,
        "architecture": "vanilla_watermap_ocean_overlay",
        "waterMapId": VANILLA_OCEAN_WATER_ID,
        "tileIds": list(DISPLAY_WATER_TILE_CODES),
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality remains user-unvalidated",
    }
    display_water["visualMaterialAlias"] = {
        "status": "retired_display_water_sand_alias_replaced_by_native_vanilla_water_tiles",
        "architecture": "native_vanilla_water_tiles_no_custom_biome_alias",
        "tileIds": list(NATIVE_WATER_TILE_CODES),
        "deepWaterTileId": NATIVE_WATER_TILE_CODE,
        "shorelineTileIdsByEdge": dict(NATIVE_WATER_SHORE_TILE_CODES_BY_EDGE),
        "proofBoundary": "custom biome rows 24-28 are retired; ocean no longer emits those tile codes",
    }

    manifest = {
        "schema": SCHEMA,
        "status": STATUS,
        "mapSid": MAP_SID,
        "sourceAlignment": str(ALIGNMENT_PATH.relative_to(poc.ROOT)) if ALIGNMENT_PATH.is_relative_to(poc.ROOT) else str(ALIGNMENT_PATH),
        "sourceSubstitutionMap": str(SUBSTITUTION_PATH.relative_to(poc.ROOT)) if SUBSTITUTION_PATH.is_relative_to(poc.ROOT) else str(SUBSTITUTION_PATH),
        "sourceWhitelist": str(CORE_CATALOG_PATH.relative_to(poc.ROOT)),
        "userVisibleValidation": USER_VISIBLE_VALIDATION,
        "templateMap": str(poc.PLAYABLE_TEMPLATE_MAP),
        "outputs": {
            "map": str(out_map),
            "script": str(out_json),
            "quickStartOverlay": quickstart["output"],
            "introDialogOverlay": intro_dialog["outputs"],
            "squadOverlay": squad_overlay["outputs"],
            "buildingRestrictionsOverlay": building_restrictions["outputs"],
            "waterTilePenaltyOverlay": {
                "status": water_tile_penalty["status"],
                "member": water_tile_penalty["member"],
                "tileIds": water_tile_penalty["tileIds"],
                "deepWaterTileId": water_tile_penalty["deepWaterTileId"],
                "shorelineTileIdsByEdge": water_tile_penalty["shorelineTileIdsByEdge"],
                "architecture": water_tile_penalty["architecture"],
            },

            "subterraneanGatePortalOverlay": {
                "status": subterranean_gate_portal["status"],
                "architecture": subterranean_gate_portal["architecture"],
                "objectSid": subterranean_gate_portal["objectSid"],
                "donorSid": subterranean_gate_portal["donorSid"],
                "prefab": subterranean_gate_portal["prefab"],
                "objectMember": subterranean_gate_portal["objectMember"],
                "portalLogicMember": subterranean_gate_portal["portalLogicMember"],
                "outputs": subterranean_gate_portal["outputs"],
            },
            "landonObjectOverlay": {
                "status": landon_object_overlay["status"],
                "architecture": landon_object_overlay["architecture"],
                "objectSids": landon_object_overlay["objectSids"],
                "donorsBySid": landon_object_overlay["donorsBySid"],
                "objectMembers": landon_object_overlay["objectMembers"],
                "logicOutputs": landon_object_overlay["logicOutputs"],
                "outputs": landon_object_overlay["outputs"],
                "guardhouseVisitGateAlignment": landon_object_overlay["guardhouseVisitGateAlignment"],
            },
        },
        "projection": {
            "sourceLayer": SOURCE_LAYER,
            "excludedLayers": [1],
            "sourceWidth": SOURCE_WIDTH,
            "sourceHeight": SOURCE_HEIGHT,
            "oldenWidth": OLDEN_WIDTH,
            "oldenHeight": OLDEN_HEIGHT,
            "sourceOffsetX": SOURCE_OFFSET_X,
            "sourceOffsetY": SOURCE_OFFSET_Y,
            "oldenViewSectionSize": OLDEN_VIEW_SECTION_SIZE,
            "oldenViewSectionCoverage": {
                "width": map_view_sector_count(OLDEN_WIDTH) * OLDEN_VIEW_SECTION_SIZE,
                "height": map_view_sector_count(OLDEN_HEIGHT) * OLDEN_VIEW_SECTION_SIZE,
            },
            "yAxisTransform": Y_AXIS_TRANSFORM,
            "terrain": H3_SURFACE_TO_OLDEN_TILE,
            "riverByTerrain": H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN,
            "sourceTerrainHistogram": dict(Counter(surface_map_data["tilesMap"]).most_common()),
            "sourceWaterHistogram": dict(Counter(surface_map_data["waterMap"]).most_common()),
            "terrainHistogram": dict(Counter(projected["tilesMap"]).most_common()),
            "waterHistogram": dict(Counter(projected["waterMap"]).most_common()),
        },
        "displayWater": display_water,
        "shorelineRivers": shoreline_river_summary,
        "objects": {
            **object_stats,
            "nativeStartTemplate": str(NATIVE_START_TEMPLATE_MAP),
            "heroSpawnerId": hero_spawner_id,
            "startSource": start_source,
            "boatPlacementAdjustments": boat_placement_adjustments,
            "retiredBoatRuntimeObjects": retired_boat_runtime_objects,
            "retiredWaterTraversalPlan": retired_water_traversal_plan,
            "retiredBoatObjectOverlay": retired_boat_object_overlay,
            "supportedLivePropertySids": sorted(SUPPORTED_LIVE_PROPERTY_SIDS),
            "supportedLivePropertyFamilies": sorted(SUPPORTED_LIVE_PROPERTY_FAMILIES),
            "nativePropertyRequiredSidCount": len(property_required_sids),
            "excludedUndergroundEntityCount": len(underground_entities),
            "excludedSurfaceBorderOverhangEntityCount": len(surface_border_overhang_entities),
            "excludedSurfaceBorderOverhangSourceKeys": [entity.get("sourceKey") for entity in surface_border_overhang_entities],
            "sourceLayerHistogram": {str(key): value for key, value in sorted(layer_histogram.items())},
            "sourceSurfaceEntityCount": len(surface_entities_all),
            "sourceTotalEntityCount": len(global_entities),
            "randomSquadStrengthTranslation": {
                "model": RANDOM_SQUAD_STRENGTH_MODEL_ID,
                "modelSource": str(RANDOM_MONSTER_STRENGTH_MODEL_PATH),
                "modelSourceStatus": RANDOM_SQUAD_STRENGTH_MODEL.get("sourceStatus"),
                "coreSource": str(poc.OLDEN_CORE_ZIP),
                "tierMedianSquadValues": h3_tier_median_squad_values(),
                "nominalH3RandomStackCountsByLevel": H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL,
                "requestedValueRounding": RANDOM_SQUAD_REQUESTED_VALUE_ROUNDING,
            },
            "buildingRestrictions": {
                "cityObjectSid": HOMM3_LANDON_CASTLE_CITY_SID,
                "cityCount": len(object_properties.get("propCities") or []),
                "buildingsBanSid": HOMECOMING_BUILDINGS_BAN_SID,
                "buildingsConstructionSid": HOMECOMING_BUILDINGS_CONSTRUCTION_SID,
                "buildingsSettingsSid": HOMECOMING_BUILDINGS_SETTINGS_SID,
                "coreOverlayMembers": building_restrictions["members"],
            },
            "subterraneanGatePortalCoreOverlay": {
                "status": subterranean_gate_portal["status"],
                "architecture": subterranean_gate_portal["architecture"],
                "objectSid": subterranean_gate_portal["objectSid"],
                "prefab": subterranean_gate_portal["prefab"],
                "objectMember": subterranean_gate_portal["objectMember"],
                "portalLogicMember": subterranean_gate_portal["portalLogicMember"],
            },
        },
        "knownGaps": [
            "Only in-bounds source layer 0 anchors are emitted; source layer 1 remains excluded until native layer support exists.",
            "Surface border-overhang anchors outside 0..71 are explicitly excluded rather than projected into the padding band.",
            "Native live-object SIDs use explicit approximate objectsProperties emitters; only unsupported property families remain deferred.",
            "Object replacements are read from the reusable Homecoming substitution map; MiniLM regeneration is an explicit audit step, not part of normal scenario export.",
            "Lossy placeholder substitutions remain visible in the manifest and substitution map; they are not authentic H3 object mechanics.",
            "Homecoming ocean water is emitted as display-only tile codes 24-28. Core tile behavior is cloned from Sand, while custom-biome material aliasing maps those tile ids to the vanilla Water material; runtime visual quality remains user-unvalidated.",
            "Native water traversal remains intentionally out of scope for display-only water; this test only proves whether the vanilla Water material can draw on non-water behavior tiles.",
            "The exact 72x72 Homecoming source layer remains centered at offset 4,4 inside the 80x80 native-sector envelope because Olden minimap rendering walks integer 16-tile MapView sectors; the rejected exact-72x72 backing shape is still invalid.",
        ],
        "programmaticGeneration": True,
        "silentFallbacksUsed": False,
    }
    write_json(OUT_ROOT / "install_manifest.json", manifest)
    write_report(manifest)
    return manifest


def write_report(manifest: dict[str, Any]) -> None:
    lines = [
        "# Homecoming Single-Layer Map",
        "",
        f"Status: {manifest['status']}",
        f"Map SID: `{manifest['mapSid']}`",
        "",
        "## User-Visible Validation",
        "",
        f"- Status: {manifest['userVisibleValidation']['status']}",
        f"- Date: {manifest['userVisibleValidation']['date']}",
        f"- Source: {manifest['userVisibleValidation']['source']}",
        f"- Scope: {manifest['userVisibleValidation']['scope']}",
        "- Not covered:",
    ]
    lines.extend(f"  - {item}" for item in manifest["userVisibleValidation"]["notCovered"])
    lines.extend([
        "",
        "## Projection",
        "",
        f"- Source layer emitted: `{manifest['projection']['sourceLayer']}`",
        f"- Excluded layers: `{manifest['projection']['excludedLayers']}`",
        f"- Source envelope: {manifest['projection']['sourceWidth']}x{manifest['projection']['sourceHeight']} at offset {manifest['projection']['sourceOffsetX']},{manifest['projection']['sourceOffsetY']} inside {manifest['projection']['oldenWidth']}x{manifest['projection']['oldenHeight']}",
        f"- Olden view section coverage: {manifest['projection']['oldenViewSectionCoverage']['width']}x{manifest['projection']['oldenViewSectionCoverage']['height']} via {manifest['projection']['oldenViewSectionSize']}-tile sectors",
        "",
        "## Objects",
        "",
        f"- Surface source entities emitted: {manifest['objects']['emittedSurfaceEntityCount']}",
        f"- Underground source entities excluded: {manifest['objects']['excludedUndergroundEntityCount']}",
        f"- Object groups emitted: {manifest['objects']['emittedObjectGroupCount']}",
        f"- Lossiness: {manifest['objects']['lossinessHistogram']}",
        "",
        "## Display Water",
        "",
        f"- HoMM3 ocean terrain cells: {manifest['displayWater']['oceanNodeCount']} across water tile codes {manifest['displayWater']['waterTileCodes']}",
        f"- Shoreline water cells: {manifest['displayWater']['oceanShoreNodeCount']} via tile variants {manifest['displayWater']['shorelineTileCodesByEdge']}",
        f"- Shoreline RiverData: {manifest['shorelineRivers']['status']}",
        f"- Water intent: {manifest['displayWater']['kindHistogram']}",
        f"- Display water behavior donor: tile {manifest['displayWater']['tileConfig']['behaviorDonorTileId']} with penalty {manifest['displayWater']['tileConfig']['penalty']} via {manifest['displayWater']['tileConfig']['member']}",
        f"- Water traversal plan: not part of this display-only visual contract",
        "",
        "## Known Gaps",
        "",
    ])
    lines.extend(f"- {gap}" for gap in manifest["knownGaps"])
    (OUT_ROOT / "HOMECOMING_SINGLE_LAYER_MAP_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    manifest = generate_map()
    print(f"generated {manifest['mapSid']} map={manifest['outputs']['map']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
