#!/usr/bin/env python3
from __future__ import annotations
"""Copied leaf emit helpers for approach_cell (from build_homecoming_single_layer_map).

Forbidden spine modules are not imported. Footprint pad/gap-fill is disabled;
enable_footprint_alignment must remain False.
"""

import copy
import hashlib
import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from statistics import median
from pathlib import Path
from typing import Any, Iterable, Mapping

import campaign_ocean as ocean
import campaign_runtime_script as campaign_script
import exact_homm3_footprint as exact_fp
import h3_town_name_pool
import town_gate_align
import functional_emit_reservation
import h3m_hero_sid
import h3m_object_registry as h3obj
import h3m_scenario_translation as scenario
import homecoming_localization as homecoming_lang
import native_footprint_model as native_fp
from homm3_external_dwelling_map import (
    HOMM3_LANDON_BARRACKS_BY_DONOR,
    HOMM3_LANDON_BARRACKS_SIDS,
)

# Populated by prepare_exact_homm3_footprints when emit policy requests it.
_EXACT_FOOTPRINT_REGISTRY: exact_fp.ExactFootprintRegistry | None = None
# True while exact-footprint raw_translation mode is active (prepare + emit).
_EXACT_FOOTPRINT_MODE: bool = False

# approach_cell leaf copy: footprint_alignment intentionally absent (forbidden spine).
FOOTPRINT_ALIGNMENT_POLICY = "approach_cell_no_footprint_pad_spine"
FOOTPRINT_PAD_ID_BASE = 890_000

import homm3_olden_rarity_bin as rarity_bin
import port_homecoming_poc as poc
import scenario_menu_shell

SCHEMA = "homm3.homecoming_single_layer_map.v0"
STATUS = "generated_deployed_user_visible_object_placement_validated"
# Ocean is a native basin: Sand seabed tile 2 + waterMap 2 ("water sand") at levelsMap -1,
# the way native Olden Era maps store sea. campaign_ocean owns the ids and the contract;
# the Golden Era-only tile ids 18-22 and waterMap 18 are retired (see campaign_ocean).
OCEAN_TILE_CODE = ocean.OCEAN_TILE_CODE
OCEAN_WATER_MAP_ID = ocean.OCEAN_WATER_MAP_ID
OCEAN_STATUS = "generated_native_basin_ocean_runtime_unvalidated"
OCEAN_ARCHITECTURE = "native_basin_sand_seabed_with_water_sand_watermap"
ACTIVE_WATER_RUNTIME_HOOK = "Homm3HomecomingWaterTraversalBridge"
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
SHORELINE_POLICY = "native_basin_perimeter_climbs_no_shore_tile_variants"
SHORELINE_RIVER_SID = "test"
SHORELINE_RIVER_RANDOM_SEED = 1803185001
ENV_DECORATION_ID_BASE = 900000
UNDERGROUND_POND_SCENERY_ID_BASE = 905_000
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
RANDOM_MONSTER_STRENGTH_MODEL_PATH = Path(os.environ.get(
    "HOMECOMING_POC_RANDOM_MONSTER_STRENGTH_MODEL_PATH",
    Path(__file__).resolve().parent.parent / "h3_random_monster_strength_model.json",
))
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
H3_NEUTRAL_OWNER = 255
OLDEN_SPAWN_TYPE_HUMAN = 0
OLDEN_SPAWN_TYPE_AI = 1
OLDEN_SPAWN_POINT_TYPE_CITY = 0
OLDEN_SPAWN_POINT_TYPE_HERO = 1
OLDEN_HERO_SPAWNER_SID = "hero-spawner"
OLDEN_RANDOM_HERO_SID = "random-hero"
HOMM3_RANDOM_RESOURCE_PICKUP_SID = "homm3_random_resource_pickup"
HOMM3_RANDOM_RESOURCE_PICKUP_DONOR_SID = "resource_gold"
HOMM3_FLOTSAM_PICKUP_SID = "homm3_flotsam_pickup"
HOMM3_FLOTSAM_PICKUP_DONOR_SID = "resource_wood"
HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER = "DB/map/objects/homecoming_custom_objects.json"
# Shared HoMM→OE rarity bin (policy homm3_rarity_bin_to_olden_erarity_v1).
# Used by all raw_translation / approach_cell emitters via random_artifact_rarity.
HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY = rarity_bin.HOMM3_RARITY_BIN_TO_OLDEN_ERARITY_POLICY
H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY = (
    rarity_bin.H3_RANDOM_ARTIFACT_OBJECT_ID_TO_HOMM_RARITY
)
# Back-compat alias: object id → *binned* Olden ERarity (not raw HoMM class).
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
# Scorched-earth accessibility on donor portal_5 2x2 [1,0,0,2]: keep OCC, convert
# every open (0) cell to GATE (2) → [1,2,2,2]. Preferred visit GATE stays south-east
# (index 3 / prefer_gate_local) so GATE-align still coincides with the H3 visit.
# Do not expand to 3x3 Dual-GATE / InteractionLayout.Bottom — that shifts interact
# south of the visit and can bury it (raw_translation 1:14:41 dirt_rock_1).
# Hex.MapGenerator.InteractionLayout (DiffableCs): CornerRight=0, CornerLeft=1, Bottom=2, All=3
# CornerLeft interact is ON buildingLeftBottom. Bottom places interact one cell
# south of the building (external) — do not use Bottom for land-on towns.
HOMM3_SUBTERRANEAN_GATE_PORTAL_NODES = [1, 2, 2, 2]
INTERACTION_LAYOUT_CORNER_LEFT = 1
INTERACTION_LAYOUT_BOTTOM = 2  # external-south; avoid for on-GATE land-on cities
# Retired: garrison towns must not force army_buildings_construction (tiers 1–6 + walls).
# Starting buildings come from h3m_town_construction (H3 builtBuildingsMask → preset).
ARMY_BUILDINGS_CONSTRUCTION_SID = "army_buildings_construction"
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
# (grid_y = anchor_y + (size_z - 1 - config_z)). Land-on towns/dwellings use
# bottom-center GATE index 7 — not native CornerLeft bottom-left index 6.
HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES = [1, 1, 1, 1, 1, 1, 1, 2, 1]
HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX = 7
HOMM3_LANDON_BOTTOM_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # alias
HOMM3_LANDON_BOTTOM_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_NORTH_EDGE_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # retired alias
HOMM3_LANDON_NORTH_EDGE_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_SOUTH_EDGE_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES  # retired alias
HOMM3_LANDON_SOUTH_EDGE_GATE_INDEX = HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX
HOMM3_LANDON_CENTER_GATE_NODES = HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES
# Land-on external dwellings: donor barracks_homm3_{faction}_{N} →
# homm3_landon_barracks_{faction}_{N} (1x1 visit GATE). See homm3_external_dwelling_map.

HOMM3_LANDON_BARRACKS_CASTLE_1_SID = HOMM3_LANDON_BARRACKS_BY_DONOR["barracks_homm3_castle_1"]
HOMM3_LANDON_BARRACKS_CASTLE_1_DONOR_SID = "barracks_homm3_castle_1"
# Approach-cell/raw land-on barracks: 1x1 GATE on H3 visit (no invented 3x3 OCC).
HOMM3_LANDON_BARRACKS_CASTLE_1_NODES = [2]
HOMM3_LANDON_BARRACKS_CASTLE_1_SIZE_Z = 1
HOMM3_LANDON_BARRACKS_NORTH_EDGE_GATE_INDEX = 0
HOMM3_LANDON_BARRACKS_SOUTH_EDGE_GATE_INDEX = 0
HOMM3_LANDON_BARRACKS_BOTTOM_CENTER_GATE_INDEX = 0
HOMM3_LANDON_OBJECT_OVERLAY_STATUS = "generated_static_landon_visit_gate_clone_overlay_runtime_unvalidated"
HOMM3_LANDON_OBJECT_OVERLAY_ARCHITECTURE = "native_donor_objectconfig_and_logic_clones_with_visit_gate_nodes"
HOMM3_LANDON_OBJECT_SIDS = frozenset({
    HOMM3_LANDON_MAP_EVENT_MARKER_SID,
    HOMM3_LANDON_CASTLE_CITY_SID,
    HOMM3_LANDON_DUNGEON_CITY_SID,
    *HOMM3_LANDON_BARRACKS_SIDS,
})
# Kept for documentation / optional disable path; unused while APPROACH_CELL_DISABLE_LANDON_CLONES is False.
APPROACH_CELL_LANDON_DONOR_REMAP = {
    HOMM3_LANDON_MAP_EVENT_MARKER_SID: HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
    HOMM3_LANDON_CASTLE_CITY_SID: HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
    HOMM3_LANDON_DUNGEON_CITY_SID: HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
    **{clone: donor for donor, clone in HOMM3_LANDON_BARRACKS_BY_DONOR.items()},
}
APPROACH_CELL_DISABLE_LANDON_CLONES = False
# HoMM3 shrines → scroll boxes (level 1/2/3). Applied even when substitution artifact is stale/blocked.
APPROACH_CELL_SHRINE_TEMPLATE_REMAP = {
    88: ("scroll_box", "shrine_incantation_to_scroll_box_approach_cell"),
    89: ("enchanted_scroll_box", "shrine_gesture_to_enchanted_scroll_box_approach_cell"),
    90: ("mythic_scroll_box", "shrine_thought_to_mythic_scroll_box_approach_cell"),
}
APPROACH_CELL_ALTAR_TO_SCROLL_REMAP = {
    "altar_of_magic_1": "scroll_box",
    "altar_of_magic_2": "enchanted_scroll_box",
    "altar_of_magic_3": "mythic_scroll_box",
}
GUARDHOUSE_DWELLING_SOURCE_KEY = "0:18:34"
HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER = "DB/map/objects/homm3_pathability_alignment.json"
# Static Core env pref for Block occupancy clones that need prefs.Length >= 1
# (native bve.ope). Do not inherit campaign_FX_block's fx/fx_map_smoke — that
# particle pref dominates Map.Init cost when thousands of blockers are placed.
HOMM3_CHEAP_BLOCK_PREF = "environment/dirt_stones_1"
HOMM3_PATHING_BLOCKER_SID = "homm3_pathing_blocker"
HOMM3_PATHING_BLOCKER_DONOR_SID = "campaign_FX_block"
HOMM3_PATHING_BLOCKER_ID_BASE = 880000
# Visible 1x1 occupied scenery used for raw_translation H3 gap-fill (not smoke FX).
HOMM3_PATHING_GAP_FILL_VISIBLE_SID = "mountain_dirt_small_1"
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
# Retired overlay ObjectConfig rows (kept so stale map rows still resolve); never emitted.
WATER_TILE_OVERLAY_SIDS = (
    "homm3_homecoming_water_overlay_deep",
    "homm3_homecoming_water_overlay_shore_east",
    "homm3_homecoming_water_overlay_shore_north",
    "homm3_homecoming_water_overlay_shore_south",
    "homm3_homecoming_water_overlay_shore_west",
)
HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_STATUS = "generated_static_dungeon_entrance_portal_overlay_runtime_unvalidated"
HOMM3_SUBTERRANEAN_GATE_PORTAL_OVERLAY_ARCHITECTURE = "native_prop_portals_logic_with_dungeon_entrance_prefab"
SUPPORTED_LIVE_PROPERTY_SIDS = {
    "altar_of_magic_1", "arena", "armory_automaton", "chest", "college_of_wonder", "fort",
    "enchanted_scroll_box",
    "fountain", "fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", "grass_1",
    "hero-spawner", "homm3_boat", "homm3_castle_city", "homm3_dungeon_city",
    *HOMM3_LANDON_BARRACKS_SIDS, HOMM3_LANDON_CASTLE_CITY_SID, HOMM3_LANDON_DUNGEON_CITY_SID,
    HOMM3_LANDON_MAP_EVENT_MARKER_SID, "homm3_flotsam_pickup", "random-hero", "random-res", HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, "knowledge_garden", "learning_stone",
    "lost_library", "mana_well", "mereas_shrine", "mine_crystals", "mine_gemstones", "mine_gold", "mine_mercury", "mine_ore",
    "mine_wood", "mountain_dead_small_1", "mountain_dirt_small_1", "mountain_green_small_1", "mountain_lava_small_1", "mountain_snow_small_1", "mountain_water_small_1", "mysterious_stone",
    "mythic_scroll_box",
    "orb_observatory", "pool_dirt_small_1", "portal_1", "portal_1_2", "portal_1_3", "portal_2", "portal_2_2", "portal_2_3", "portal_3", "portal_3_2", "portal_3_3", "portal_4", "portal_4_2", "portal_4_3", "portal_5", "portal_5_2", "portal_5_3", "portal_magic", "prison", "quixs_path",
    "random-item",
    "random-squad", "resource_crystals", "resource_dust", "resource_gemstones", "resource_gold",
    "resource_mercury", "resource_ore", "resource_wood", "scroll_box", "shady_den", "snow_grassy_hill_1",
    "stables", "stinging_sword", "tree_dirt_1", "tree_of_knowledge", "university", "watchtower", "windmill",
    "wise_owl",
}
# Families the live emitter binds. Include both native Ai-intent spellings and propSquads
# so discovery cannot false-defer whitelisted SIDs (e.g. random-squad). Keep in sync with
# build_homecoming_single_layer_map.py.
SUPPORTED_LIVE_PROPERTY_FAMILIES = {
    "propActionsAfter", "propActionsBefore", "propActivations", "propAiIntetactions", "propAiIntetations", "propEntities",
    "propHeroes", "propNoCombineGeometries", "propOwners", "propPortals", "propRandomItems", "propRandomSquads",
    "propCities", "propGrowthUnits", "propQuestMarkers", "propResParams", "propResources", "propRewardParams",
    "propSpawns", "propSquads",
    "propVariants", "propsName",
}
# Native campaign maps (e.g. Thirst_for_Power) emit propResParams with value=0 and
# let ObjectConfig/logic roll the amount. Inventing HoMM3-like amounts (500/5/1)
# diverges from the vanilla PropResParam contract.
RESOURCE_VALUES = {
    "resource_gold": 0,
    "resource_wood": 0,
    "resource_ore": 0,
    "resource_crystals": 0,
    "resource_dust": 0,
    "resource_gemstones": 0,
    "resource_mercury": 0,
}
# Same order as tools/map_load_preflight.NATIVE_RESOURCE_LOGIC_IDS — Meta random-res
# must expand into these concrete SIDs (Loader hangs on campaign-scale Meta rolls).
CONCRETE_RESOURCE_EMIT_SIDS: tuple[str, ...] = (
    "resource_gold",
    "resource_dust",
    "resource_wood",
    "resource_ore",
    "resource_crystals",
    "resource_mercury",
    "resource_gemstones",
)
META_RANDOM_RES_SID = "random-res"


def concrete_resource_sid_for_object_id(object_id: int) -> str:
    """Deterministic Meta random-res → resource_* expansion (install rewrite parity)."""
    return CONCRETE_RESOURCE_EMIT_SIDS[int(object_id) % len(CONCRETE_RESOURCE_EMIT_SIDS)]

REWARD_PARAM_SIDS = {
    "altar_of_magic_1", "armory_automaton", "college_of_wonder", "fort", "fountain",
    "knowledge_garden", "learning_stone", "lost_library", "mana_well", "mereas_shrine",
    "mysterious_stone", "orb_observatory", "quixs_path", "shady_den", "stables",
    "stinging_sword",
    "tree_of_knowledge", "university", "watchtower", "windmill", "wise_owl",
}
VARIANT_SIDS = {
    "chest", "enchanted_scroll_box", "lost_library", "mereas_shrine", "mythic_scroll_box",
    "scroll_box", "shady_den", "tree_of_knowledge", "windmill", "wise_owl",
}
ENTITY_SIDS = {
    "fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", "homm3_seer_hut",
    "lost_library", "mana_well",
    "mine_crystals", "mine_gemstones", "mine_gold", "mine_mercury", "mine_ore", "mine_wood", "mountain_dead_small_1", "mountain_dirt_small_1", "mountain_green_small_1", "mountain_lava_small_1", "mountain_snow_small_1", "mountain_water_small_1",
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
    # Native (non-land-on) faction cities used when land-on GATE clones do not exist yet.
    "homm3_inferno_city": "homm3_inferno",
    "homm3_rampart_city": "homm3_rampart",
    "homm3_tower_city": "homm3_tower",
    "homm3_fortress_city": "homm3_fortress",
    "homm3_stronghold_city": "homm3_stronghold",
    "homm3_necropolis_city": "homm3_necropolis",
    "homm3_conflux_city": "homm3_conflux",
    "homm3_cove_city": "homm3_cove",
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
    # H3 sand — Olden has no dedicated sand biome row in this projector; dirt is the
    # nearest land channel (lossy visual).
    1: {"oldenId": 7, "oldenBiome": "Dirt"},
    2: {"oldenId": 1, "oldenBiome": "Grass"},
    3: {"oldenId": 4, "oldenBiome": "Snow"},
    # H3 swamp — map to grass until a native swamp/nature tile contract exists.
    4: {"oldenId": 1, "oldenBiome": "Grass"},
    5: {"oldenId": 1, "oldenBiome": "Grass"},
    # Rare surface subterranean patches (Tunnels) → Burrow.
    6: {"oldenId": 15, "oldenBiome": "Burrow"},
    7: {"oldenId": 7, "oldenBiome": "Dirt"},
    # H3 water: the surface projector writes the native ocean basin (campaign_ocean).
    8: {"oldenId": OCEAN_TILE_CODE, "oldenBiome": ocean.OCEAN_TILE_BIOME, "oldenWaterId": OCEAN_WATER_MAP_ID},
    # H3 rock (border / impassable). Same Void channel as underground rock.
    9: {"oldenId": scenario.OLDEN_VOID_TILE_ID, "oldenBiome": "Void"},
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

H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN = {
    # H3 river codes: 1=clear, 2=icy, 3=muddy, 4=lava. Map all to nearest Olden water
    # channel per terrain (lossy visual for icy/muddy/lava).
    0: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
        2: {"oldenId": 7, "oldenName": "water dirt (icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water dirt (muddy river lossy)"},
    },
    1: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
        2: {"oldenId": 7, "oldenName": "water dirt (icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water dirt (muddy river lossy)"},
    },
    2: {
        1: {"oldenId": 7, "oldenName": "water grass"},
        2: {"oldenId": 7, "oldenName": "water grass (icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water grass (muddy river lossy)"},
    },
    3: {
        1: {"oldenId": 4, "oldenName": "water snow"},
        2: {"oldenId": 4, "oldenName": "water snow"},
        3: {"oldenId": 4, "oldenName": "water snow (muddy river lossy)"},
    },
    4: {
        1: {"oldenId": 1, "oldenName": "water grass (swamp river lossy)"},
        2: {"oldenId": 1, "oldenName": "water grass (swamp icy river lossy)"},
        3: {"oldenId": 1, "oldenName": "water grass (swamp muddy river lossy)"},
    },
    5: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
        2: {"oldenId": 7, "oldenName": "water dirt (icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water dirt (muddy river lossy)"},
    },
    6: {
        1: {"oldenId": 15, "oldenName": "water burrow (surface subterranean river)"},
        2: {"oldenId": 15, "oldenName": "water burrow (icy river lossy)"},
        3: {"oldenId": 15, "oldenName": "water burrow (muddy river lossy)"},
    },
    7: {
        1: {"oldenId": 7, "oldenName": "water dirt"},
        2: {"oldenId": 7, "oldenName": "water dirt (icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water dirt (muddy river lossy)"},
        # H3 river type 4 = lava. Olden has no lava-river mesh; map to dirt water
        # so the channel remains marked in waterMap (lossy visual, fail-closed absent).
        4: {"oldenId": 7, "oldenName": "water dirt (lava river lossy)"},
    },
    # Rock border cells can still carry clear-river overlays on AB/SoD maps.
    9: {
        1: {"oldenId": 7, "oldenName": "water dirt (rock river lossy)"},
        2: {"oldenId": 7, "oldenName": "water dirt (rock icy river lossy)"},
        3: {"oldenId": 7, "oldenName": "water dirt (rock muddy river lossy)"},
    },
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def homm3_boat_object_row() -> dict[str, Any]:
    """HoMM3 boat: 1x1 GATE on the H3 visit cell (VCMI boat templates are 1x1).

    A prior 2x2 ``[2,1,2,2]`` (BR→SW multi-tile sawmill-style anchor) extended
    north into H3-open beach cells — collapsing the empty tile between coastal
    town gates and boats (Homecoming SW town visit y=54, empty y=55, boat y=56).
    """
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
    """Clone donor portal_5 ObjectConfig; SID + prefab + scorched-earth GATE nodes.

    Donor is 2x2 ``[1,0,0,2]``. Scorched-earth policy converts every open (0) cell
    to GATE (2) while keeping OCC → ``[1,2,2,2]``. Placement GATE-aligns the
    preferred south-east marker onto the HoMM3 visit cell.
    """
    row = _clone_jsonable(donor_row)
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
    row = _clone_jsonable(donor_row)
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

    Adventure-map interact uses ObjectConfig.nodes GATE (value 2), not RMG-only
    InteractionLayout math. CornerLeft at LeftBottom (1,2) with a 1x1 building keeps
    generatorConfig aligned with GATE index 7. Stock homm3_*_city ObjectConfigs must
    share this same contract: CreateCity paints from Side.fractionConfig.city (often
    the stock donor), and donor SW GATE (index 6) reappears as a corner entrance
    when map emit stops visit-aligning GATE onto the H3 visit cell.

    Map emit centers the land-on 3x3 one cell north of the H3 town body so the
    H3 visit/courtyard row stays open (VCMI beach gap parity). Visual HoMM3
    billboards still anchor on that footprint center so the art's bottom-center
    entrance falls on the south-center GATE — not on the SW placement root.
    """
    row = clone_core_object_row(donor_row, donor_sid=donor_sid, clone_sid=clone_sid)
    apply_homm3_town_bottom_center_gate(row)
    return row


def is_homm3_town_city_object_sid(sid: Any) -> bool:
    """True for stock/landon town map objects such as homm3_castle_city."""
    if not isinstance(sid, str):
        return False
    return bool(re.fullmatch(r"homm3_(?:landon_)?[a-z0-9]+_city", sid.strip()))


def apply_homm3_town_bottom_center_gate(row: dict[str, Any]) -> dict[str, Any]:
    """Force a 3x3 town ObjectConfig onto south-center GATE (index 7)."""
    if not isinstance(row, dict):
        raise TypeError("city ObjectConfig row must be a dict")
    size_x = int(row.get("sizeX") or 0)
    size_z = int(row.get("sizeZ") or 0)
    if size_x != 3 or size_z != 3:
        raise ValueError(
            f"homm3 town ObjectConfig {row.get('id')!r} must remain 3x3 for bottom-center GATE; "
            f"got sizeX={size_x} sizeZ={size_z}"
        )
    row["nodes"] = list(HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES)
    row["canBeMirrored"] = False
    row["generatorConfig"] = {
        "buildingSizeX": 1,
        "buildingSizeZ": 1,
        "buildingLeftBottomX": 1,
        "buildingLeftBottomZ": size_z - 1,
        "buildingInteractionLayout": INTERACTION_LAYOUT_CORNER_LEFT,
    }
    return row


def normalize_homm3_town_city_bottom_center_gates_in_doc(interactables_doc: dict[str, Any]) -> int:
    """Rewrite every homm3_*_city row in a 4_interactables doc to bottom-center GATE."""
    rows = interactables_doc.get("array")
    if not isinstance(rows, list):
        raise ValueError("4_interactables doc missing array for town GATE normalize")
    changed = 0
    for row in rows:
        if not isinstance(row, dict) or not is_homm3_town_city_object_sid(row.get("id")):
            continue
        before_nodes = row.get("nodes")
        apply_homm3_town_bottom_center_gate(row)
        if before_nodes != row.get("nodes"):
            changed += 1
    return changed


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
    """Land-on dwelling: 1x1 GATE on HoMM3 visit; do not invent a 3x3 OCC body.

    Full 3x3 town-style landon bodies blocked H3-open neighbors (e.g. Archer's
    Tower AVGcros is only visit+one block). Residual H3 non-visit blocks are
    sealed by gap-fill. Prefab/logic stay on the donor dwelling.
    """
    row = clone_core_object_row(donor_row, donor_sid=donor_sid, clone_sid=clone_sid)
    row["sizeX"] = 1
    row["sizeZ"] = 1
    row["nodes"] = [2]
    row["gateInsideObject"] = True
    row["canBeMirrored"] = False
    row["selectionUiPrefabID"] = "1x1"
    row["pivotX"] = 0
    row["pivotZ"] = 0
    row["offsetX"] = 0
    row["offsetZ"] = 0
    row["generatorConfig"] = {
        "buildingSizeX": 1,
        "buildingSizeZ": 1,
        "buildingLeftBottomX": 0,
        "buildingLeftBottomZ": 0,
        "buildingInteractionLayout": 0,
    }
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
    import core_zip_cache

    for name in core_zip_cache.core_namelist(poc.OLDEN_CORE_ZIP):
        if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
            continue
        doc = core_zip_cache.read_core_json(poc.OLDEN_CORE_ZIP, name)
        for row in doc.get("array") or []:
            if isinstance(row, dict) and row.get("id") == row_id:
                # Callers keep and mutate the row; never hand out the cached one.
                return _clone_jsonable(row)
    return None


def _homm3_artifact_map_object_rows() -> list[dict[str, Any]]:
    """Core.zip artifact map objects, then generated overlay rows (overlay wins by id)."""
    member = "DB/map/objects/6_artifacts.json"
    by_id: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        if member not in core.namelist():
            raise ValueError(f"Core.zip missing {member} for homm3 artifact whitelist")
        doc = json.loads(core.read(member).decode("utf-8-sig"))
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain array rows")
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            by_id[row["id"]] = row
    overlay = (
        poc.ROOT
        / "custom_factions"
        / "artifacts"
        / "generated_core_overlay"
        / "DB"
        / "map"
        / "objects"
        / "6_artifacts.json"
    )
    if overlay.is_file():
        overlay_doc = json.loads(overlay.read_text(encoding="utf-8-sig"))
        overlay_rows = overlay_doc.get("array") if isinstance(overlay_doc, dict) else None
        if not isinstance(overlay_rows, list):
            raise ValueError(f"{overlay} must contain array rows")
        for row in overlay_rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                by_id[row["id"]] = row
    return list(by_id.values())


def extend_valid_ids_with_core_homm3_artifacts(valid_ids: set[str]) -> int:
    """Whitelist Core + generated-overlay artifact SIDs used by OBJECT_ARTIFACT emit.

    The entity catalog may lag installed Core.zip (e.g. AB seeds 127–128). Overlay
    rows must still whitelist + load ObjectConfigs for exact-footprint.
    """
    added = 0
    for row in _homm3_artifact_map_object_rows():
        sid = row.get("id")
        if isinstance(sid, str) and sid.startswith("homm3_artifact_") and sid not in valid_ids:
            valid_ids.add(sid)
            added += 1
    return added


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
    gc = native_config.get("generatorConfig") if isinstance(native_config.get("generatorConfig"), dict) else {}
    return (
        isinstance(nodes, list)
        and isinstance(size_x, int)
        and isinstance(size_z, int)
        and size_x == 3
        and size_z == 3
        and len(nodes) == 9
        and nodes == list(HOMM3_LANDON_BOTTOM_CENTER_GATE_NODES)
        and nodes[HOMM3_LANDON_BOTTOM_CENTER_GATE_INDEX] == 2
        and sum(1 for value in nodes if value == 2) == 1
        and native_config.get("canBeMirrored") is False
        and int(gc.get("buildingInteractionLayout") or -1) == INTERACTION_LAYOUT_CORNER_LEFT
        and int(gc.get("buildingSizeX") or -1) == 1
        and int(gc.get("buildingSizeZ") or -1) == 1
        and int(gc.get("buildingLeftBottomX") or -1) == 1
        and int(gc.get("buildingLeftBottomZ") or -1) == 2
    )


def landon_barracks_visit_gate_contract(native_config: dict[str, Any]) -> bool:
    """Land-on barracks: exactly one GATE on a 1x1 size grid (H3 visit marker)."""
    nodes = native_config.get("nodes")
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    return (
        isinstance(nodes, list)
        and isinstance(size_x, int)
        and isinstance(size_z, int)
        and size_x == 1
        and size_z == 1
        and nodes == [2]
        and sum(1 for value in nodes if value == 2) == 1
    )


def verify_homm3_landon_barracks_guardhouse_visit_gate_alignment(native_config: dict[str, Any]) -> dict[str, Any]:
    """Contract: land-on barracks 1x1 GATE coincides with HoMM3 visit cell.

    The synthetic Guardhouse sits at a fixed source cell. On a multi-layer atlas this check
    runs outside any layer projection context, so the source offsets are pinned to the first
    atlas layer for its duration; otherwise the probe lands in inter-layer padding and every
    native cell is clipped away by the per-layer envelope.
    """
    global SOURCE_OFFSET_X, SOURCE_OFFSET_Y
    if not SOURCE_LAYER_ENVELOPES:
        return _verify_guardhouse_visit_gate_alignment(native_config)
    previous = (SOURCE_OFFSET_X, SOURCE_OFFSET_Y)
    SOURCE_OFFSET_X, SOURCE_OFFSET_Y = SOURCE_LAYER_ENVELOPES[0][2], SOURCE_LAYER_ENVELOPES[0][3]
    try:
        return _verify_guardhouse_visit_gate_alignment(native_config)
    finally:
        SOURCE_OFFSET_X, SOURCE_OFFSET_Y = previous


def _verify_guardhouse_visit_gate_alignment(native_config: dict[str, Any]) -> dict[str, Any]:
    entity = {
        "sourceKey": GUARDHOUSE_DWELLING_SOURCE_KEY,
        "sourceX": 18,
        "sourceY": 34,
        "rotation": 0,
        "templateVisitMask": [0, 0, 0, 0, 0, 128],
        "templateBlockMask": [255, 255, 255, 255, 191, 63],
    }
    visit_gate = landon_barracks_visit_gate_contract(native_config)
    default_node = target_node(entity["sourceX"], entity["sourceY"])
    rotation, rotation_evidence = derive_source_mask_rotation(entity, native_config)
    node, anchor_evidence = derive_source_anchor_node(
        entity,
        HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
        native_config,
        default_node,
        rotation=rotation,
    )
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) != 1:
        raise ValueError(
            f"Guardhouse must have exactly one HoMM3 visit cell; got {sorted(visit_nodes)}"
        )
    visit_node = next(iter(visit_nodes))
    gate_nodes = nodes_for_object_instance_with_value(
        HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
        native_config,
        node,
        rotation,
        node_value=2,
    )
    visit_on_gate = visit_node in gate_nodes
    if not visit_on_gate:
        raise ValueError(
            f"Guardhouse land-on barracks GATE must cover visit cell {visit_node}; "
            f"gateNodes={sorted(gate_nodes)} emitNode={node}"
        )
    if not visit_gate:
        raise ValueError(
            f"Guardhouse land-on barracks must use 1x1 visit GATE; "
            f"nodes={native_config.get('nodes')!r} size={native_config.get('sizeX')}x{native_config.get('sizeZ')}"
        )
    occupied = nodes_for_object_instance_with_value(
        HOMM3_LANDON_BARRACKS_CASTLE_1_SID,
        native_config,
        node,
        rotation,
        node_value=1,
    )
    if occupied:
        raise ValueError(
            f"Guardhouse land-on barracks must not invent OCC cells; occupied={sorted(occupied)}"
        )
    return {
        "sourceKey": GUARDHOUSE_DWELLING_SOURCE_KEY,
        "visitNode": visit_node,
        "emitNode": node,
        "rotation": rotation,
        "rotationDecision": rotation_evidence.get("decision"),
        "gateNodes": sorted(gate_nodes),
        "visitOnGate": visit_on_gate,
        "bottomCenterGate": visit_gate,
        "visitGate1x1": visit_gate,
        "gateCount": len(gate_nodes),
        "anchorFootprint": anchor_evidence.get("nativeFootprint"),
        "anchorPolicy": anchor_evidence.get("policy"),
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
        for sid in WATER_TILE_OVERLAY_SIDS
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
    row = _clone_jsonable(source_row)
    size_x, size_z, _source = native_row_pathing_clone_size(row)
    row["id"] = homm3_pathing_visual_sid(source_sid)
    row["sizeX"] = size_x
    row["sizeZ"] = size_z
    row["nodes"] = [0] * (size_x * size_z)
    return row


def homm3_pathing_blocker_object_row(donor_row: dict[str, Any]) -> dict[str, Any]:
    if donor_row.get("id") != HOMM3_PATHING_BLOCKER_DONOR_SID:
        raise ValueError(f"pathing blocker donor row mismatch: {donor_row}")
    row = _clone_jsonable(donor_row)
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


def entity_town_body_center_node(entity: dict[str, Any]) -> int:
    """Olden-grid node for the integer center of an H3 town body (block ∪ visit)."""
    body_sx, body_sy = town_gate_align.town_body_center_source_xy(entity)
    return target_node_allowing_source_padding(body_sx, body_sy)


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
    native_cells = _native_building_nodes_for_value(
        sid,
        config,
        anchor_node,
        rotation,
        node_value=node_value,
    )
    if native_cells is not None:
        return native_cells
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


def occupied_nodes_for_object_instance(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
) -> set[int]:
    if sid == HOMM3_PATHING_BLOCKER_SID:
        return {anchor_node}
    native_cells = _native_building_nodes_for_value(
        sid,
        config,
        anchor_node,
        rotation,
        node_value=1,
    )
    if native_cells is not None:
        return native_cells
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


def gate_nodes_for_object_instance(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
) -> set[int]:
    """Map-space GATE cells (nodes value 2) for one placed instance."""
    if sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(sid):
        return set()
    native_cells = _native_building_nodes_for_value(
        sid,
        config,
        anchor_node,
        rotation,
        node_value=2,
    )
    if native_cells is not None:
        return native_cells
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    if (
        not isinstance(size_x, int)
        or not isinstance(size_z, int)
        or size_x <= 0
        or size_z <= 0
        or not isinstance(nodes, list)
        or len(nodes) != size_x * size_z
    ):
        return set()
    anchor_x = anchor_node % OLDEN_WIDTH
    anchor_y = anchor_node // OLDEN_WIDTH
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and config.get("canBeMirrored") is True
    gates: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            if nodes[config_z * size_x + config_x] != 2:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            grid_x = anchor_x + placed_dx
            grid_y = anchor_y + (size_z - 1 - config_z)
            if 0 <= grid_x < OLDEN_WIDTH and 0 <= grid_y < OLDEN_HEIGHT:
                gates.add(grid_y * OLDEN_WIDTH + grid_x)
    return gates


# Per-layer source envelopes of a side-by-side layer atlas:
# (layer_origin_x, layer_end_x, env_x0, env_y0, env_x1, env_y1), end-exclusive.
# Set by the raw_translation profile (build_raw_translation_map.apply_profile_globals).
# Empty = single-layer module geometry (SOURCE_OFFSET_* / SOURCE_WIDTH / SOURCE_HEIGHT).
SOURCE_LAYER_ENVELOPES: tuple[tuple[int, int, int, int, int, int], ...] = ()


def _native_cells_in_active_source_envelope(cells: Iterable[int], anchor_node: int) -> set[int]:
    """Clip native cells to the H3 layer the object is anchored in; padding is non-playable.

    On a multi-layer atlas the module SOURCE_OFFSET_* describe one layer only while a
    layer projection context is active; post-passes and ground truth run outside it, so
    the layer is taken from the anchor's atlas column instead.
    """
    if not SOURCE_LAYER_ENVELOPES:
        return {int(node) for node in cells if is_node_in_source_envelope(int(node))}
    anchor_x = int(anchor_node) % OLDEN_WIDTH
    for origin_x, end_x, x0, y0, x1, y1 in SOURCE_LAYER_ENVELOPES:
        if origin_x <= anchor_x < end_x:
            return {
                int(node)
                for node in cells
                if x0 <= int(node) % OLDEN_WIDTH < x1 and y0 <= int(node) // OLDEN_WIDTH < y1
            }
    raise ValueError(f"anchor node {anchor_node} (x={anchor_x}) lies in no atlas layer {SOURCE_LAYER_ENVELOPES}")


def _native_building_footprint_model(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
) -> native_fp.NativeFootprintModel:
    """Return a resolved native cell model or fail closed with the reason."""
    model = native_fp.model_native_footprint(
        sid,
        config,
        anchor_node,
        rotation,
        width=OLDEN_WIDTH,
        height=OLDEN_HEIGHT,
    )
    failures = native_fp.native_cell_projection_failure_reasons(model)
    if failures:
        raise ValueError(
            f"cannot project native cells for {sid}: unresolved "
            f"{', '.join(failures)}"
        )
    return model


def _native_building_nodes_for_value(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    node_value: int,
) -> set[int] | None:
    """Project native building/scenery nodes with the ObjectConfig pivot.

    Resource and meta ring objects intentionally return None and retain the
    pickup/enemy emitter convention. Permanent native structures use the
    ObjectConfig nodes query projection; generator rectangles and
    presentation offsets are not promoted to path blockers.
    """
    if not exact_fp.uses_native_building_anchor_policy(config):
        return None
    model = _native_building_footprint_model(sid, config, anchor_node, rotation)
    if node_value == 1:
        return _native_cells_in_active_source_envelope(model.occupied_cells, anchor_node)
    if node_value == 2:
        return _native_cells_in_active_source_envelope(model.gate_cells, anchor_node)
    raise ValueError(f"unsupported native ObjectConfig node value: {node_value}")


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
            gates |= gate_nodes_for_object_instance(
                HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, config, anchor, rotation
            )
    return gates


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


def _clone_jsonable(value: Any) -> Any:
    """Structural clone for JSON-shaped trees (faster than json round-trip)."""
    return copy.deepcopy(value)


def load_native_object_configs(valid_ids: set[str]) -> dict[str, dict[str, Any]]:
    import core_zip_cache

    all_rows = core_zip_cache.map_object_configs_by_id(poc.OLDEN_CORE_ZIP)
    # Deep-copy selected rows so emit mutations cannot poison the process cache.
    configs: dict[str, dict[str, Any]] = {
        sid: _clone_jsonable(all_rows[sid]) for sid in valid_ids if sid in all_rows
    }
    # Generated artifact overlay may be ahead of installed Core.zip (AB campaign seeds).
    for row in _homm3_artifact_map_object_rows():
        sid = row.get("id")
        if isinstance(sid, str) and sid in valid_ids:
            configs[sid] = row
    if HOMM3_BOAT_SID in valid_ids:
        configs[HOMM3_BOAT_SID] = homm3_boat_object_row()
    if "homm3_seer_hut" in valid_ids:
        from seer_hut_quest import homm3_seer_hut_object_row

        configs["homm3_seer_hut"] = homm3_seer_hut_object_row()
    if HOMM3_SUBTERRANEAN_GATE_PORTAL_SID in valid_ids:
        donor = configs.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID)
        if not isinstance(donor, dict):
            donor = all_rows.get(HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID)
        if not isinstance(donor, dict):
            raise ValueError(f"missing {HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID!r} donor config for {HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
        configs[HOMM3_SUBTERRANEAN_GATE_PORTAL_SID] = homm3_subterranean_gate_portal_object_row(donor)
    inject_homm3_landon_object_configs(configs, valid_ids)
    for row in homecoming_water_tile_overlay_object_rows():
        if row["id"] in valid_ids:
            configs[row["id"]] = row
    if HOMM3_PATHING_BLOCKER_SID in valid_ids:
        donor = configs.get(HOMM3_PATHING_BLOCKER_DONOR_SID) or all_rows.get(
            HOMM3_PATHING_BLOCKER_DONOR_SID
        )
        if not isinstance(donor, dict):
            raise ValueError(f"missing {HOMM3_PATHING_BLOCKER_DONOR_SID!r} donor config for {HOMM3_PATHING_BLOCKER_SID}")
        configs[HOMM3_PATHING_BLOCKER_SID] = homm3_pathing_blocker_object_row(donor)
    missing = sorted(valid_ids - set(configs))
    if missing:
        raise ValueError(f"missing native object config rows for whitelisted emitted SIDs: {missing[:20]}")
    return configs


def clear_exact_homm3_footprints() -> None:
    global _EXACT_FOOTPRINT_REGISTRY, _EXACT_FOOTPRINT_MODE
    _EXACT_FOOTPRINT_REGISTRY = None
    _EXACT_FOOTPRINT_MODE = False


def prepare_exact_homm3_footprints(
    entities: list[dict[str, Any]],
    *,
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    native_object_configs: dict[str, dict[str, Any]],
) -> exact_fp.ExactFootprintRegistry:
    """Build exact HoMM3 footprint remaps/clones and inject into valid_ids/configs."""
    global _EXACT_FOOTPRINT_REGISTRY, _EXACT_FOOTPRINT_MODE
    _EXACT_FOOTPRINT_MODE = True
    exact_fp.ensure_scenery_catalog_configs(
        native_object_configs,
        core_zip_path=poc.OLDEN_CORE_ZIP,
    )

    def resolve_donor(entity: dict[str, Any]) -> str | None:
        sid, _rule, _loss = resolve_replacement_sid(
            entity,
            substitution_lookup,
            valid_ids,
            apply_exact_footprint_remap=False,
        )
        return sid

    registry = exact_fp.build_exact_footprint_registry(
        entities,
        resolve_donor=resolve_donor,
        block_offsets_for=source_block_offsets,
        visit_offsets_for=source_visit_offsets,
        configs=native_object_configs,
        core_zip_path=poc.OLDEN_CORE_ZIP,
        in_source_bounds=is_in_source_bounds,
    )
    exact_fp.inject_registry_into_configs(native_object_configs, valid_ids, registry)
    _EXACT_FOOTPRINT_REGISTRY = registry
    return registry


def reset_exact_logic_clone_rows(doc: dict[str, Any]) -> None:
    """Remove prior exact-footprint logic rows before writing the current set."""
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError("exact footprint logic overlay must contain an array list")
    doc["array"] = [
        row
        for row in rows
        if not (
            isinstance(row, dict)
            and str(row.get("id") or "").startswith(exact_fp.CLONE_SID_PREFIX)
        )
    ]


def generate_exact_homm3_footprint_overlay(
    registry: exact_fp.ExactFootprintRegistry | None = None,
) -> dict[str, Any]:
    """Write exact-footprint ObjectConfig + logic clones into core_overlay."""
    active = registry if registry is not None else _EXACT_FOOTPRINT_REGISTRY
    if active is None:
        raise ValueError("exact footprint overlay requires prepare_exact_homm3_footprints first")
    out_dir = OUT_ROOT / "core_overlay"
    out_dir.mkdir(parents=True, exist_ok=True)
    mine_logic_active = any(
        str(entry.get("member")) == exact_fp.MINE_LOGIC_MEMBER
        for entry in active.logic_clones
    )
    mine_logic_path = out_dir / exact_fp.MINE_LOGIC_MEMBER
    if not mine_logic_active and mine_logic_path.is_file():
        stale_doc = json.loads(mine_logic_path.read_text(encoding="utf-8-sig"))
        if not isinstance(stale_doc, dict) or not isinstance(stale_doc.get("array"), list):
            raise ValueError("stale exact footprint mine logic overlay must contain an array list")
        reset_exact_logic_clone_rows(stale_doc)
        if stale_doc["array"]:
            write_json(mine_logic_path, stale_doc)
        else:
            mine_logic_path.unlink()
    object_doc: dict[str, Any] = {"array": []}
    for sid in sorted(active.clone_rows):
        upsert_array_row(object_doc, active.clone_rows[sid])
    write_json(out_dir / exact_fp.OVERLAY_OBJECT_MEMBER, object_doc)

    logic_outputs: dict[str, str] = {}
    logic_docs: dict[str, dict[str, Any]] = {}
    for entry in active.logic_clones:
        member = str(entry["member"])
        doc = logic_docs.get(member)
        if doc is None:
            overlay_path = out_dir / member
            if overlay_path.is_file():
                doc = json.loads(overlay_path.read_text(encoding="utf-8-sig"))
            else:
                with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
                    if member not in core.namelist():
                        doc = {"array": []}
                    else:
                        doc = json.loads(core.read(member).decode("utf-8-sig"))
            if not isinstance(doc, dict):
                doc = {"array": []}
            if not isinstance(doc.get("array"), list):
                doc["array"] = []
            reset_exact_logic_clone_rows(doc)
            logic_docs[member] = doc
        upsert_array_row(doc, entry["row"])
        logic_outputs[str(entry["cloneSid"])] = str(out_dir / member)
    for member, doc in sorted(logic_docs.items()):
        write_json(out_dir / member, doc)

    manifest = {
        "schema": exact_fp.SCHEMA,
        "status": "generated_artifact_validator_runtime_unvalidated",
        "objectMember": exact_fp.OVERLAY_OBJECT_MEMBER,
        "cloneSidCount": len(active.clone_rows),
        "logicCloneCount": len(active.logic_clones),
        "logicOutputs": logic_outputs,
        "stats": active.stats,
        "proofBoundary": "generated_artifact_exact_homm3_footprint_clones_runtime_unvalidated",
    }
    write_json(out_dir / exact_fp.OVERLAY_MANIFEST_NAME, manifest)
    return manifest


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
    """Lower ocean cells into a basin and stamp perimeter ramp climbs."""
    levels = out["levelsMap"]
    climbs = out["climbsMap"]
    tiles = out["tilesMap"]
    water = out["waterMap"]
    perimeter_count = 0
    interior_count = 0
    for y in range(height):
        for x in range(width):
            node = y * width + x
            if not ocean.is_emitter_ocean_pair(tiles[node], water[node]):
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
                    if not ocean.is_emitter_ocean_pair(tiles[neighbor], water[neighbor]):
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
                out["tilesMap"][target_index] = OCEAN_TILE_CODE
                out["waterMap"][target_index] = OCEAN_WATER_MAP_ID
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



def is_ocean_node(projected: Mapping[str, list[int]], node: int) -> bool:
    return ocean.is_emitter_ocean_pair(projected["tilesMap"][node], projected["waterMap"][node])


def clear_stray_water_on_landon_gate_cells(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    water_map: list[int],
    tiles_map: list[int],
) -> dict[str, Any]:
    """Zero waterMap on land-on GATE + cardinal approach cells on non-water terrain.

    HoMM3 visit cells (and their south/cardinal approaches) can project onto Olden
    land tiles that still carry stray waterMap bytes from shoreline/basin projection.
    Land heroes cannot stand on those cells at runtime even when soft-path treats
    goals as enterable. Also clears cardinal neighbors of each GATE so land-on
    cardinal-only enter is not falsely water-blocked. Fail closed if a land-on GATE
    or its cardinal approach lands on true display-water terrain.
    """
    from domains import CARDINAL_OFFSETS, neighbors_with

    landon_gate_sids = HOMM3_LANDON_OBJECT_SIDS - {HOMM3_LANDON_MAP_EVENT_MARKER_SID}
    cleared: list[dict[str, Any]] = []
    for group in objects:
        sid = str(group.get("sid") or "")
        if sid not in landon_gate_sids:
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            raise ValueError(f"clear_stray_water_on_landon_gate_cells missing config for {sid}")
        for object_id, anchor, rotation in zip(
            group.get("ids") or [],
            group.get("nodes") or [],
            group.get("rotations") or [],
        ):
            if not isinstance(object_id, int) or not isinstance(anchor, int):
                continue
            if anchor % OLDEN_WIDTH >= 80:
                continue
            gates = nodes_for_object_instance_with_value(
                sid, config, int(anchor), int(rotation or 0), node_value=2
            )
            targets: set[int] = set(gates)
            for gate in gates:
                targets.update(neighbors_with(gate, CARDINAL_OFFSETS))
            for cell in sorted(targets):
                if cell < 0 or cell >= len(water_map) or cell >= len(tiles_map):
                    raise ValueError(
                        f"land-on GATE/approach {cell} out of map bounds for {sid} id={object_id}"
                    )
                if cell % OLDEN_WIDTH >= 80:
                    continue
                water = int(water_map[cell] or 0)
                tile = int(tiles_map[cell] or 0)
                if water == 0:
                    continue
                role = "gate" if cell in gates else "cardinal_approach"
                if ocean.is_emitter_ocean_pair(tile, water):
                    if role == "gate":
                        raise ValueError(
                            f"land-on GATE for {sid} id={object_id} sits on ocean "
                            f"gate={cell} tile={tile} water={water}; refuse to clear"
                        )
                    # True ocean on a cardinal approach stays water; 1C will skip it.
                    continue
                water_map[cell] = 0
                cleared.append({
                    "sid": sid,
                    "objectId": object_id,
                    "cell": cell,
                    "role": role,
                    "previousWater": water,
                    "tile": tile,
                })
    return {
        "status": "applied" if cleared else "noop",
        "policy": "clear_stray_water_on_landon_gates_and_cardinal_approaches_non_water_terrain",
        "clearedGateCount": sum(1 for row in cleared if row.get("role") == "gate"),
        "clearedApproachCount": sum(1 for row in cleared if row.get("role") == "cardinal_approach"),
        "clearedCellCount": len(cleared),
        "clearedGates": [row for row in cleared if row.get("role") == "gate"],
        "clearedCells": cleared,
        "proofBoundary": "generated_artifact_validator_runtime_unvalidated",
    }


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
    # stays retired — the native ocean basin owns the visual shoreline.
    rivers = [
        {
            "sid": SHORELINE_RIVER_SID,
            "randomSeed": SHORELINE_RIVER_RANDOM_SEED,
            "nodes": [],
        }
    ]
    summary = {
        "status": "retired_replaced_by_native_basin_shoreline",
        "retiredSid": SHORELINE_RIVER_SID,
        "retiredRandomSeed": SHORELINE_RIVER_RANDOM_SEED,
        "replacement": SHORELINE_POLICY,
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
    """Audit the projected surface ocean against campaign_ocean and summarise it.

    Every HoMM3 ocean source cell must land on the native basin (seabed tile +
    ocean waterMap at the basin level); the emitted surface must carry no
    retired Golden Era water ids.
    """
    source_pair_histogram: Counter[str] = Counter()
    native_pair_histogram: Counter[str] = Counter()
    kind_histogram: Counter[str] = Counter()
    ocean_nodes: list[int] = []
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
                if not ocean.is_emitter_ocean_pair(native_tile, native_water):
                    raise ValueError(
                        f"HoMM3 ocean source {source_x},{source_y} did not project to the native ocean basin "
                        f"(tile {OCEAN_TILE_CODE}, waterMap {OCEAN_WATER_MAP_ID}); got tile {native_tile} water {native_water}")
                if projected["levelsMap"][node] != ocean.OCEAN_BASIN_LEVEL:
                    raise ValueError(
                        f"HoMM3 ocean source {source_x},{source_y} is not at basin level {ocean.OCEAN_BASIN_LEVEL}")
                ocean_nodes.append(node)
    errors = ocean.map_ocean_errors(projected, label="projected surface")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "status": OCEAN_STATUS,
        "architecture": OCEAN_ARCHITECTURE,
        "ocean": ocean.describe(),
        "shorelinePolicy": SHORELINE_POLICY,
        "runtimeGate": (
            "Homecoming ocean cells emit native Sand seabed tile 2 with MapData.waterMap id 2 at levelsMap -1; "
            "Homm3HomecomingWaterTraversalBridge supplies hero-start relief and boat visuals"
        ),
        "oceanNodeCount": len(ocean_nodes),
        "kindHistogram": dict(sorted(kind_histogram.items())),
        "sourceTerrainWaterPairHistogram": dict(sorted(source_pair_histogram.items())),
        "nativeTileWaterPairHistogram": dict(sorted(native_pair_histogram.items())),
        "nativeOceanBasinGeometry": projected.get("nativeOceanBasinGeometry"),
        "proofBoundary": "source/static and generated-artifact validated; runtime visual quality and boat travel remain user-unvalidated",
    }


def is_node_in_source_envelope(node: int) -> bool:
    x = node % OLDEN_WIDTH
    y = node // OLDEN_WIDTH
    return SOURCE_OFFSET_X <= x < SOURCE_OFFSET_X + SOURCE_WIDTH and SOURCE_OFFSET_Y <= y < SOURCE_OFFSET_Y + SOURCE_HEIGHT


def is_boat_water_intent(projected: dict[str, list[int]], node: int) -> bool:
    return is_node_in_source_envelope(node) and is_ocean_node(projected, node)


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
            if not is_ocean_node(projected, adjacent):
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
        raise ValueError(f"no valid Homecoming ocean anchor with land-side shore approach near node {original_node}")
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


def resolve_replacement_sid(
    entity: dict[str, Any],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    *,
    apply_exact_footprint_remap: bool = True,
) -> tuple[str | None, str, str]:
    import build_homecoming_entity_substitution_map as sub_mod

    signature = signature_for(entity)
    source_sid = entity.get("sid")
    if source_sid in valid_ids:
        replacement_sid = str(source_sid)
        rule_name = "already_valid"
        lossiness = "direct_or_family_substitution"
        if apply_exact_footprint_remap:
            remapped, suffix = exact_fp.remap_replacement_sid(entity, replacement_sid, _EXACT_FOOTPRINT_REGISTRY)
            if suffix:
                return remapped, f"{rule_name}_{suffix}", lossiness
        return replacement_sid, rule_name, lossiness

    template_id = entity.get("templateObjectId")
    if isinstance(template_id, int) and template_id == 5:
        # OBJECT_ARTIFACT — named catalog SID (SoD+HotA port).
        from vanilla_stock.h3_artifact_stock_map import stock_item_sid_for_h3_artifact_id

        subtype = int(entity.get("templateSubtype") or 0)
        artifact_sid = stock_item_sid_for_h3_artifact_id(subtype)
        if artifact_sid:
            if apply_exact_footprint_remap:
                remapped, suffix = exact_fp.remap_replacement_sid(entity, artifact_sid, _EXACT_FOOTPRINT_REGISTRY)
                if suffix:
                    return remapped, f"homm3_artifact_catalog_{suffix}", "direct_or_family_substitution"
            return artifact_sid, "homm3_artifact_catalog", "direct_or_family_substitution"
    if isinstance(template_id, int) and template_id in APPROACH_CELL_SHRINE_TEMPLATE_REMAP:
        shrine_sid, shrine_rule = APPROACH_CELL_SHRINE_TEMPLATE_REMAP[template_id]
        if shrine_sid not in valid_ids:
            raise ValueError(f"approach_cell shrine remap SID missing from valid catalog: {shrine_sid}")
        if apply_exact_footprint_remap:
            remapped, suffix = exact_fp.remap_replacement_sid(entity, shrine_sid, _EXACT_FOOTPRINT_REGISTRY)
            if suffix:
                return remapped, f"{shrine_rule}_{suffix}", "direct_or_family_substitution"
        return shrine_sid, shrine_rule, "direct_or_family_substitution"

    # Signature-keyed garrison rows can map to random-squad from a nonempty sibling
    # instance. Empty instances still emit as random-squad (no invented army stacks).
    if is_adventure_map_garrison_entity(entity) and not adventure_garrison_has_nonempty_stacks(entity):
        if "random-squad" in valid_ids:
            return "random-squad", "garrison_empty_army_to_random_squad", "role"
        return None, "garrison_instance_empty_army", "blocked"

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

    # DEF/animation encodes blocking scenery family (snow mountain, dead tree, …).
    # Tile-biome substitution remains the artifact contract, but emit must not plant
    # green mountains/pines where the HoMM3 DEF is a different blocking family — that
    # leaves visual holes versus the source map. Override only hard blocking families.
    # Never override functional families (mines/resources/portals/…): short anim tokens
    # like historical ms0 falsely matched AVMgems0/AVTgems0 and stomped mine_gemstones.
    rule_name = str(sub.get("ruleName") or "")
    lossiness = str(sub.get("lossiness") or "direct_or_family_substitution")
    category = str(entity.get("category") or "")
    payload = str(entity.get("payloadKind") or "")
    functional_scenery_override_exempt = category in {
        "mine",
        "resource_pickup",
        "town",
        "monster_stack",
        "garrison",
        "map_event",
        "hero_or_prison",
        "boat_or_water_travel_object",
        "interactive_reward_object",
        "interactive_quest_object",
        "travel_link_candidate",
    } or payload in {
        "mine",
        "resource",
        "monster",
        "garrison",
        "map_event",
        "event",
        "shrine",
        "scholar",
    } or replacement_sid.startswith(
        ("mine_", "resource_", "portal_", "random-", "hero-", "homm3_", "camp_fire", "tavern")
    )
    if not functional_scenery_override_exempt:
        anim_sid, anim_rule = sub_mod.choose_biome_decoration(
            entity.get("templateObjectId"),
            str(entity.get("templateAnimation") or ""),
            valid_ids,
        )
        blocking_anim_rules = {
            "biome_dead_tree",
            "biome_snow_mountain",
            "biome_dirt_mountain",
            "biome_green_mountain",
            "biome_snow_pine",
            "biome_snow_tree",
            "biome_pine_tree",
            "biome_autumn_tree",
            "biome_dirt_tree",
            "anim_snow_mountain",
            "anim_dead_tree",
            "anim_snow_tree",
            "anim_dirt_mountain",
            "anim_green_mountain",
        }
        if (
            isinstance(anim_sid, str)
            and anim_sid
            and isinstance(anim_rule, str)
            and anim_rule in blocking_anim_rules
        ):
            if anim_sid != replacement_sid:
                rule_name = f"{anim_rule}_def_family_blocking_override"
                lossiness = "direct_or_family_substitution"
            replacement_sid = anim_sid

    # Safety: stale substitution artifacts may still map shrines to altar_of_magic_*.
    if (
        entity.get("payloadKind") == "shrine"
        or (isinstance(template_id, int) and template_id in APPROACH_CELL_SHRINE_TEMPLATE_REMAP)
    ) and replacement_sid in APPROACH_CELL_ALTAR_TO_SCROLL_REMAP:
        remapped = APPROACH_CELL_ALTAR_TO_SCROLL_REMAP[replacement_sid]
        if remapped not in valid_ids:
            raise ValueError(f"approach_cell altar→scroll remap SID missing from valid catalog: {remapped}")
        replacement_sid = remapped
        if APPROACH_CELL_DISABLE_LANDON_CLONES and replacement_sid in APPROACH_CELL_LANDON_DONOR_REMAP:
            donor = APPROACH_CELL_LANDON_DONOR_REMAP[replacement_sid]
            return donor, f"{rule_name}_approach_cell_scroll_remap_native_donor", lossiness
        if apply_exact_footprint_remap:
            remapped_sid, suffix = exact_fp.remap_replacement_sid(entity, replacement_sid, _EXACT_FOOTPRINT_REGISTRY)
            if suffix:
                return remapped_sid, f"{rule_name}_approach_cell_scroll_remap_{suffix}", lossiness
        return replacement_sid, f"{rule_name}_approach_cell_scroll_remap", lossiness

    # Scenery size from HoMM3 block-mask solid-square subset (not canonical SID size).
    # Exact-footprint mode: while building the registry, freeze on substitution donors.
    # Afterward, skip solid-square only for catalog-remapped instances; misses still size.
    registry_entry = None
    if _EXACT_FOOTPRINT_REGISTRY is not None:
        source_index = entity.get("sourceIndex")
        if isinstance(source_index, int):
            registry_entry = _EXACT_FOOTPRINT_REGISTRY.by_source_index.get(source_index)
    skip_solid_square = False
    if _EXACT_FOOTPRINT_MODE and _EXACT_FOOTPRINT_REGISTRY is None:
        skip_solid_square = True
    elif registry_entry is not None and registry_entry.action in {
        "catalog_match",
        "same_size_clone",
        "clone",
    }:
        skip_solid_square = True
    role = sub_mod.terrain_role_for_row(entity)
    if role in {"mountain", "tree", "pool", "pool_big", "rock"}:
        evidence = sub.get("semanticEvidence") if isinstance(sub.get("semanticEvidence"), dict) else {}
        if not evidence:
            evidence = sub.get("evidence") if isinstance(sub.get("evidence"), dict) else {}
        biome = (
            sub_mod.scenery_biome_from_sid(replacement_sid)
            or evidence.get("dominantBiome")
            or evidence.get("biome")
        )
        if not isinstance(biome, str):
            raise ValueError(
                f"scenery solid-square sizing missing biome for {entity.get('sourceKey')} "
                f"sid={replacement_sid!r} role={role!r} (refuse silent grass default)"
            )
        blocks = entity_blocked_mask_offsets(entity)
        if not skip_solid_square and role in {"mountain", "tree", "pool", "pool_big"}:
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
                    replacement_sid = variant
                    rule_name = f"{rule_name}_homm3_solid_square_variant"
        # Mountains/trees/rocks: always force 1x1 — catalog-matched *_big_* / dirt_rock
        # / sparsened xfp clones still overhang H3-open neighbors via mesh larger than
        # ObjectConfig OCC. Return before exact-footprint remap so catalog/clone cannot
        # reintroduce multi-tile rock meshes.
        if role in {"mountain", "tree", "rock"}:
            node = int(entity.get("sourceIndex") or 0)
            before = replacement_sid
            if role == "rock":
                replacement_sid = sub_mod.ensure_rock_sid_fits_homm3_block_mask(
                    replacement_sid,
                    blocks,
                    valid_ids,
                )
                if replacement_sid != before and "homm3_1x1_rock" not in rule_name:
                    rule_name = f"{rule_name}_homm3_1x1_rock"
            else:
                replacement_sid = sub_mod.ensure_mountain_tree_sid_fits_homm3_block_mask(
                    replacement_sid,
                    role,
                    biome,
                    blocks,
                    valid_ids,
                    seed_key=str(entity.get("sourceKey") or signature),
                    node=node,
                )
                if replacement_sid != before and "homm3_solid_square_variant" not in rule_name:
                    rule_name = f"{rule_name}_homm3_1x1_mountain_tree"
            if APPROACH_CELL_DISABLE_LANDON_CLONES and replacement_sid in APPROACH_CELL_LANDON_DONOR_REMAP:
                donor = APPROACH_CELL_LANDON_DONOR_REMAP[replacement_sid]
                return donor, f"{rule_name}_approach_cell_native_donor", lossiness
            return replacement_sid, rule_name, lossiness
        # Pools: solid-square only when H3 fills the bucket. Otherwise refuse
        # multi-tile pool meshes (sparsened xfp / OE-larger donors overhang).
        # Pathable H3 (0 blocks) must not invent a 1x1 OCC plant.
        if role in {"pool", "pool_big"} and "homm3_solid_square_variant" not in rule_name:
            if not blocks:
                if APPROACH_CELL_DISABLE_LANDON_CLONES and replacement_sid in APPROACH_CELL_LANDON_DONOR_REMAP:
                    donor = APPROACH_CELL_LANDON_DONOR_REMAP[replacement_sid]
                    return donor, f"{rule_name}_approach_cell_native_donor", lossiness
                if apply_exact_footprint_remap:
                    remapped_sid, suffix = exact_fp.remap_replacement_sid(
                        entity, replacement_sid, _EXACT_FOOTPRINT_REGISTRY
                    )
                    if suffix:
                        return remapped_sid, f"{rule_name}_{suffix}", lossiness
                return replacement_sid, rule_name, lossiness
            if (
                replacement_sid.startswith(("pool", "homm3_xfp_"))
                or replacement_sid in {"pool", "pool_small", "pool_big"}
            ):
                if "mountain_dirt_small_1" in valid_ids:
                    return (
                        "mountain_dirt_small_1",
                        f"{rule_name}_homm3_1x1_pool_no_mesh_overhang",
                        lossiness,
                    )
                raise ValueError(
                    f"pool role cannot plant OE-larger/overhang mesh {replacement_sid!r} "
                    f"for {entity.get('sourceKey')}: mountain_dirt_small_1 missing "
                    f"(h3_blocks={len(blocks)})"
                )
        if not skip_solid_square and "homm3_solid_square_variant" in rule_name:
            if APPROACH_CELL_DISABLE_LANDON_CLONES and replacement_sid in APPROACH_CELL_LANDON_DONOR_REMAP:
                donor = APPROACH_CELL_LANDON_DONOR_REMAP[replacement_sid]
                return donor, f"{rule_name}_approach_cell_native_donor", lossiness
            return replacement_sid, rule_name, lossiness
    if APPROACH_CELL_DISABLE_LANDON_CLONES and replacement_sid in APPROACH_CELL_LANDON_DONOR_REMAP:
        donor = APPROACH_CELL_LANDON_DONOR_REMAP[replacement_sid]
        return donor, f"{rule_name}_approach_cell_native_donor", lossiness
    if apply_exact_footprint_remap:
        remapped_sid, suffix = exact_fp.remap_replacement_sid(entity, replacement_sid, _EXACT_FOOTPRINT_REGISTRY)
        if suffix:
            return remapped_sid, f"{rule_name}_{suffix}", lossiness
    return replacement_sid, rule_name, lossiness



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
    "dirt_strange_flower",
    "dirt_rock_1",
    "dead_stones_1",
    "desert_stones_1",
    "flowers_1",
    "flowers_2",
    "fx_map_light",
    "fx_quest_mark_gold_01",
    "fx_quest_mark_silver_01",
    "grass_1",
    "grass_2",
    "grass_death_1",
    "grass_desert_1",
    "grass_snow_1",
    "grass_snow_2",
    "grass_stones_1",
    "grass_stones_2",
    "lava_stones_1",
    "log_1",
    "mushrooms_1",
    "mushrooms_2",
    "mushrooms_3",
    "mushrooms_4",
    "pool_dead_small_1",
    "snow_stones_1",
    "snow_stones_2",
    "snow_stones_3",
    "snow_stones_4",
    "tree_dead_1",
    "water_reed_1",
    # HotA magic-terrain overlay stand-ins (build_homecoming_entity_substitution_map
    # HOTA_MAGIC_TERRAIN_OVERLAY_MAP): Core rows with no nodes grid, drawn on one cell.
    "dead_stones_2",
    "fx_fireflies_blue",
    "fx_fireflies_yellow",
    "fx_map_fire",
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
    if exact_fp.footprint_spec_from_config(native_config) is not None or exact_fp.is_exact_footprint_sid(
        str(native_config.get("id") or "")
    ):
        evidence["reason"] = "exact_homm3_footprint_never_mirrored"
        evidence["rotation"] = OLDEN_DEFAULT_ROTATION
        return OLDEN_DEFAULT_ROTATION, evidence
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
    if replacement_sid in HOMM3_LANDON_BARRACKS_SIDS:
        if not landon_barracks_visit_gate_contract(native_config):
            raise ValueError(
                f"{replacement_sid} must keep 1x1 visit GATE (no invented OCC); "
                f"size=({size_x},{size_z}) nodes={nodes!r}"
            )
        return {
            "source": "landon_barracks_1x1_visit_gate",
            "width": 1,
            "height": 1,
            "minX": 0,
            "minZ": 0,
            "cellCount": 0,
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

    Land-on SIDs require exactly one GATE. Scorched subterranean portal
    (single_gate with multiple markers) uses prefer_gate_local south-east.
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
    elif (
        replacement_sid == HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
        and exact_fp.classify_object_config_shape(native_config, replacement_sid) == "single_gate"
        and len(gate_indices) > 1
    ):
        preferred_x, preferred_z = exact_fp.prefer_gate_local(size_x, size_z)
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
) -> tuple[int, dict[str, Any]]:
    """Place land-on ObjectConfig so its single GATE cell coincides with the HoMM3 visit cell.

    Occupied-bounds BR anchoring left GATE one tile off the visit cell (barracks inaccessible;
    towns visually shifted). Land-on policy is visit-the-GATE, so align GATE→visit in Olden space.
    ObjectConfig high config_z is building-bottom = map-south, so
    grid_y = anchor_y + (size_z - 1 - config_z) and
    anchor_y = visit_y - (size_z - 1 - gate_z).
    Prefer the unique template visit-mask cell; fall back to source-anchor default_node only when
    the visit mask is empty (fail closed on ambiguous multi-visit masks).
    """
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        raise ValueError(f"cannot GATE-align without source coordinates: {entity.get('sourceKey')}")
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) > 1:
        # HotA/SoD random dwellings often expose a 2-cell visit ring. Land-on still
        # needs one GATE→visit pair — prefer the south-most visit (approachable edge).
        if str(entity.get("payloadKind") or "") == "random_dwelling":
            visit_node = max(visit_nodes, key=lambda node: (node // OLDEN_WIDTH, node % OLDEN_WIDTH))
        else:
            raise ValueError(
                f"{replacement_sid} land-on GATE alignment requires exactly one HoMM3 visit cell for "
                f"{entity.get('sourceKey')}; got {sorted(visit_nodes)}"
            )
    else:
        visit_node = next(iter(visit_nodes)) if visit_nodes else default_node
    gate_x, gate_z, size_x, size_z = landon_single_gate_local_cell(native_config, replacement_sid)
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and native_config.get("canBeMirrored") is True
    try:
        node, _projection = exact_fp.anchor_for_config_local_cell(
            native_config,
            local_x=gate_x,
            local_z=gate_z,
            target_node=visit_node,
            size_x=size_x,
            size_z=size_z,
            grid_width=OLDEN_WIDTH,
            grid_height=OLDEN_HEIGHT,
            rotation=rotation,
            can_be_mirrored=native_config.get("canBeMirrored") is True,
        )
    except ValueError as exc:
        raise ValueError(
            f"{replacement_sid} GATE-aligned anchor failed for {entity.get('sourceKey')}: "
            f"visit={visit_node} gateLocal=({gate_x},{gate_z}) mirrored={mirrored}: {exc}"
        ) from exc
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
        "reason": "landon_single_gate_coincides_with_source_visit_cell",
        "decision": "align_olden_node_so_gate_equals_h3_visit",
        "sourceAnchor": [source_x, source_y],
        "sourceFootprintAnchor": None,
        "nativeFootprint": {
            **footprint,
            "source": "landon_gate_aligned_to_h3_visit",
            "gateLocal": [gate_x, gate_z],
            "anchorProjection": _projection,
            "mirrored": mirrored,
        },
        "node": node,
        "nodeDelta": [
            node % OLDEN_WIDTH - visit_node % OLDEN_WIDTH,
            node // OLDEN_WIDTH - visit_node // OLDEN_WIDTH,
        ],
        "visitNode": visit_node,
        "gateNodes": sorted(gate_nodes),
        "sourceAnchorNode": default_node,
    }
    return node, evidence


# Resource pickups + chests may expand placement range when strict visit-on-GATE
# ∩ mine-clear fails. Rationale: unguarded pickups are never true blockers.
PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY = "pickup_gate_ring_nearby_range_fallback_v1"
# Neighbor search order around the blocked H3 visit: cardinal, then diagonal.
_PICKUP_RANGE_CARDINAL_DELTAS = ((0, -1), (1, 0), (0, 1), (-1, 0))
_PICKUP_RANGE_DIAGONAL_DELTAS = ((1, -1), (1, 1), (-1, 1), (-1, -1))


def is_pickup_range_fallback_sid(sid: str) -> bool:
    """Eligible SIDs for nearby-range fallback after strict gate-ring placement fails."""
    if sid.startswith("resource_"):
        return True
    return sid in {
        "chest",
        HOMM3_RANDOM_RESOURCE_PICKUP_SID,
        HOMM3_FLOTSAM_PICKUP_SID,
    }


def _neighbor_nodes_cardinal_then_diagonal(center: int) -> list[int]:
    """Chebyshev-1 neighbors of ``center`` in fixed cardinal-then-diagonal order."""
    cx = center % OLDEN_WIDTH
    cy = center // OLDEN_WIDTH
    out: list[int] = []
    for dx, dy in (*_PICKUP_RANGE_CARDINAL_DELTAS, *_PICKUP_RANGE_DIAGONAL_DELTAS):
        x = cx + dx
        y = cy + dy
        if 0 <= x < OLDEN_WIDTH and 0 <= y < OLDEN_HEIGHT:
            out.append(y * OLDEN_WIDTH + x)
    return out


def _gate_ring_emit_candidates_for_visit(
    *,
    replacement_sid: str,
    native_config: dict[str, Any],
    visit_node: int,
    rotation: int,
) -> list[tuple[int, set[int], set[int]]]:
    """All emit anchors where ``visit_node`` lands on a GATE cell of the ring."""
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    nodes = native_config.get("nodes")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        raise ValueError(f"{replacement_sid} gate-ring needs sizeX/sizeZ")
    if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
        raise ValueError(f"{replacement_sid} gate-ring needs a full nodes grid")
    visit_x = visit_node % OLDEN_WIDTH
    visit_y = visit_node // OLDEN_WIDTH
    mirrored = rotation == OLDEN_MIRRORED_ROTATION and native_config.get("canBeMirrored") is True
    candidates: list[tuple[int, set[int], set[int]]] = []
    for config_z in range(size_z):
        for config_x in range(size_x):
            if nodes[config_z * size_x + config_x] != 2:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            # Invert nodes_for_object_instance_with_value placement.
            anchor_x = visit_x - placed_dx
            anchor_y = visit_y - (size_z - 1 - config_z)
            if not (0 <= anchor_x < OLDEN_WIDTH and 0 <= anchor_y < OLDEN_HEIGHT):
                continue
            emit_node = anchor_y * OLDEN_WIDTH + anchor_x
            gate_nodes = nodes_for_object_instance_with_value(
                replacement_sid, native_config, emit_node, rotation, node_value=2
            )
            occupied_nodes = nodes_for_object_instance_with_value(
                replacement_sid, native_config, emit_node, rotation, node_value=1
            )
            if visit_node not in gate_nodes:
                continue
            if visit_node in occupied_nodes:
                continue
            candidates.append((emit_node, gate_nodes, occupied_nodes))
    return candidates


def derive_gate_ring_anchor_on_visit_node(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    default_node: int,
    *,
    rotation: int,
    forbidden_occupied: set[int] | None = None,
    allow_pickup_range_fallback: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Plant occupied GATE-ring pickups like native maps: visit on a GATE cell.

    Thirst_for_Power stores resource pickups with ``node`` on a GATE marker and the
    occupied body offset. Putting the occupied body on the HoMM3 visit cell makes
    that tile blocked → forbidden cursor / no pickup.

    When ``forbidden_occupied`` is provided (typically mine bodies), choose among
    GATE-aligned emits so the pickup body and GATE ring stay clear of those cells.
    Fail closed if no clear GATE-aligned emit exists — unless
    ``allow_pickup_range_fallback`` is True for an eligible resource/chest SID, in
    which case try Chebyshev-1 neighbor interact cells (cardinal then diagonal).
    """
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) > 1:
        raise ValueError(
            f"{replacement_sid} occupied GATE-ring requires exactly one HoMM3 visit cell for "
            f"{entity.get('sourceKey')}; got {sorted(visit_nodes)}"
        )
    # Empty H3 visit mask → interact at source-anchor default_node (same land-on policy).
    visit_node = next(iter(visit_nodes)) if visit_nodes else default_node
    forbidden = set(forbidden_occupied or ())
    candidates = _gate_ring_emit_candidates_for_visit(
        replacement_sid=replacement_sid,
        native_config=native_config,
        visit_node=visit_node,
        rotation=rotation,
    )
    if not candidates:
        raise ValueError(
            f"{replacement_sid} visit-on-GATE placement failed for {entity.get('sourceKey')}: "
            f"no GATE-aligned emit keeps visit={visit_node} on a GATE cell"
        )

    def _score(
        item: tuple[int, set[int], set[int]],
        *,
        interact_node: int,
    ) -> tuple[int, int, int, int, int]:
        emit_node, gate_nodes, occupied_nodes = item
        body_hits = len(occupied_nodes & forbidden)
        gate_hits = len(gate_nodes & forbidden)
        # Prefer fully clear footprints. Among clear: keep emit on the H3 visit
        # GATE when possible; otherwise stay nearest that visit. Never maximize
        # mine distance — that drifted clear gold/chest piles by whole tiles.
        body = next(iter(occupied_nodes)) if occupied_nodes else emit_node
        body_to_interact = abs((body % OLDEN_WIDTH) - (interact_node % OLDEN_WIDTH)) + abs(
            (body // OLDEN_WIDTH) - (interact_node // OLDEN_WIDTH)
        )
        prefer_emit_equals_interact = 0 if emit_node == interact_node else 1
        return (body_hits, gate_hits, prefer_emit_equals_interact, body_to_interact, emit_node)

    if forbidden:
        clear = [c for c in candidates if not (c[1] & forbidden) and not (c[2] & forbidden)]
        if clear:
            node, gate_nodes, occupied_nodes = min(
                clear, key=lambda item: _score(item, interact_node=visit_node)
            )
            decision = "emit_gate_aligned_clear_of_forbidden_occupied"
            reason = "gate_ring_visit_preserved_body_and_gates_clear_of_mines"
            evidence = {
                "policy": "gate_ring_anchor_on_h3_visit_marker",
                "reason": reason,
                "decision": decision,
                "nativeFootprint": {
                    "width": native_config.get("sizeX"),
                    "height": native_config.get("sizeZ"),
                    "source": "gate_ring_anchor_on_h3_visit_marker",
                    "occupiedCount": len(occupied_nodes),
                    "gateCount": len(gate_nodes),
                },
                "node": node,
                "visitNode": visit_node,
                "gateNodes": sorted(gate_nodes),
                "occupiedNodes": sorted(occupied_nodes),
                "forbiddenOccupiedHitCount": len((gate_nodes | occupied_nodes) & forbidden),
                "sourceAnchorNode": default_node,
            }
            return node, evidence
        # Strict visit-on-GATE ∩ mine-clear failed.
        if not (
            allow_pickup_range_fallback and is_pickup_range_fallback_sid(replacement_sid)
        ):
            raise ValueError(
                f"{replacement_sid} visit-on-GATE cannot clear forbidden occupied cells for "
                f"{entity.get('sourceKey')}: visit={visit_node} forbiddenSample={sorted(forbidden)[:12]}"
            )
        return _derive_gate_ring_nearby_range_fallback(
            entity=entity,
            replacement_sid=replacement_sid,
            native_config=native_config,
            default_node=default_node,
            rotation=rotation,
            visit_node=visit_node,
            forbidden=forbidden,
        )

    # Default: emit node on the visit GATE marker (native campaign style).
    exact = next((c for c in candidates if c[0] == visit_node), None)
    if exact is None:
        raise ValueError(
            f"{replacement_sid} visit-on-GATE placement failed for {entity.get('sourceKey')}: "
            f"visit={visit_node} is not a valid emit GATE marker"
        )
    node, gate_nodes, occupied_nodes = exact
    decision = "emit_node_equals_h3_visit_gate_marker"
    reason = "native_maps_place_resource_ring_node_on_gate_not_occupied_body"

    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    evidence = {
        "policy": "gate_ring_anchor_on_h3_visit_marker",
        "reason": reason,
        "decision": decision,
        "nativeFootprint": {
            "width": size_x,
            "height": size_z,
            "source": "gate_ring_anchor_on_h3_visit_marker",
            "occupiedCount": len(occupied_nodes),
            "gateCount": len(gate_nodes),
        },
        "node": node,
        "visitNode": visit_node,
        "gateNodes": sorted(gate_nodes),
        "occupiedNodes": sorted(occupied_nodes),
        "forbiddenOccupiedHitCount": len((gate_nodes | occupied_nodes) & forbidden),
        "sourceAnchorNode": default_node,
    }
    return node, evidence


def _derive_gate_ring_nearby_range_fallback(
    *,
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    default_node: int,
    rotation: int,
    visit_node: int,
    forbidden: set[int],
) -> tuple[int, dict[str, Any]]:
    """Expand pickup interact to Chebyshev-1 neighbors when strict placement fails.

    Search order: cardinal neighbors of the H3 visit, then diagonals. Each neighbor
    becomes the GATE interact target; body+gates must stay clear of mine OCC.
    Fail closed if no free clear GATE-ring placement exists in range.
    """
    neighbor_nodes = _neighbor_nodes_cardinal_then_diagonal(visit_node)
    for search_index, interact_node in enumerate(neighbor_nodes):
        # Hero must be able to stand on the interact GATE; skip mine-covered cells.
        if interact_node in forbidden:
            continue
        candidates = _gate_ring_emit_candidates_for_visit(
            replacement_sid=replacement_sid,
            native_config=native_config,
            visit_node=interact_node,
            rotation=rotation,
        )
        clear = [
            c
            for c in candidates
            if not (c[1] & forbidden) and not (c[2] & forbidden)
        ]
        if not clear:
            continue

        def _fallback_score(item: tuple[int, set[int], set[int]]) -> tuple[int, int, int]:
            emit_node, _gates, occupied_nodes = item
            body = next(iter(occupied_nodes)) if occupied_nodes else emit_node
            # Prefer body near original visit, then emit on interact GATE.
            body_to_visit = abs((body % OLDEN_WIDTH) - (visit_node % OLDEN_WIDTH)) + abs(
                (body // OLDEN_WIDTH) - (visit_node // OLDEN_WIDTH)
            )
            prefer_emit_equals_interact = 0 if emit_node == interact_node else 1
            return (body_to_visit, prefer_emit_equals_interact, emit_node)

        node, gate_nodes, occupied_nodes = min(clear, key=_fallback_score)
        evidence = {
            "policy": PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY,
            "reason": "strict_visit_on_gate_mine_clear_failed_expanded_to_chebyshev1_neighbor",
            "decision": "emit_gate_aligned_on_neighbor_interact_clear_of_mines",
            "nativeFootprint": {
                "width": native_config.get("sizeX"),
                "height": native_config.get("sizeZ"),
                "source": PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY,
                "occupiedCount": len(occupied_nodes),
                "gateCount": len(gate_nodes),
            },
            "node": node,
            "visitNode": visit_node,
            "alternateInteractNode": interact_node,
            "neighborSearchIndex": search_index,
            "neighborSearchOrder": "cardinal_then_diagonal_chebyshev1",
            "gateNodes": sorted(gate_nodes),
            "occupiedNodes": sorted(occupied_nodes),
            "forbiddenOccupiedHitCount": len((gate_nodes | occupied_nodes) & forbidden),
            "sourceAnchorNode": default_node,
            "strictFailed": True,
        }
        return node, evidence

    raise ValueError(
        f"{replacement_sid} {PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY} exhausted for "
        f"{entity.get('sourceKey')}: visit={visit_node} neighborsTried={len(neighbor_nodes)} "
        f"forbiddenSample={sorted(forbidden)[:12]} — no free mine-clear GATE-ring placement "
        f"in Chebyshev-1 range"
    )


# HoMM3 cells that must stay open for a function that has no emitted body yet when pickups
# are anchored: the Border Gate (212) passage, which later gets its key-gate block, and the
# Keymaster's Tent (10) visit cell, which later hosts its zone marker
# (raw_translation/border_guard_gates.py). A pickup body must not land on either.
KEY_GATE_RESERVED_TEMPLATE_IDS = (10, 212)


def key_gate_reserved_cells(entities: list[dict[str, Any]]) -> set[int]:
    cells: set[int] = set()
    for entity in entities:
        if isinstance(entity, dict) and entity.get("templateObjectId") in KEY_GATE_RESERVED_TEMPLATE_IDS:
            cells |= entity_visit_nodes(entity)
    return cells


def reanchor_resource_gate_rings_clear_of_mines(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    allow_pickup_range_fallback: bool = False,
    reserved_cells: set[int] | None = None,
) -> dict[str, Any]:
    """Second pass: keep resource/chest visit-on-GATE, but clear mine occupied cells.

    ``reserved_cells`` (key-gate passages and tent cells) are kept clear the same way.
    When ``allow_pickup_range_fallback`` is True and strict clearance fails for an
    eligible pickup SID, expand to Chebyshev-1 neighbor interact cells
    (``pickup_gate_ring_nearby_range_fallback_v1``). Never reshapes mines.
    """
    mine_occupied: set[int] = set()
    for placement in placements:
        sid = str(placement.get("replacementSid") or "")
        if not sid.startswith("mine_"):
            continue
        config = native_object_configs.get(sid)
        node = placement.get("node")
        if not isinstance(config, dict) or not isinstance(node, int):
            continue
        mine_occupied |= occupied_nodes_for_object_instance(
            sid,
            config,
            node,
            int(placement.get("rotation") or 0),
        )
    mine_occupied_count = len(mine_occupied)
    mine_occupied |= set(reserved_cells or ())
    changed = 0
    fallback_count = 0
    examples: list[dict[str, Any]] = []
    fallback_examples: list[dict[str, Any]] = []
    for placement in placements:
        sid = str(placement.get("replacementSid") or "")
        if not (sid.startswith("resource_") or sid == "chest" or is_pickup_range_fallback_sid(sid)):
            continue
        config = native_object_configs.get(sid)
        entity = placement.get("entity")
        node = placement.get("node")
        if not isinstance(config, dict) or not isinstance(entity, dict) or not isinstance(node, int):
            continue
        shape = exact_fp.classify_object_config_shape(config, sid)
        if shape != "gate_ring":
            continue
        rotation = int(placement.get("rotation") or 0)
        default_node = placement.get("defaultNode")
        if not isinstance(default_node, int):
            source_x = entity.get("sourceX")
            source_y = entity.get("sourceY")
            if isinstance(source_x, int) and isinstance(source_y, int):
                default_node = target_node(source_x, source_y)
            else:
                default_node = node
        new_node, evidence = derive_gate_ring_anchor_on_visit_node(
            entity,
            sid,
            config,
            default_node=default_node,
            rotation=rotation,
            forbidden_occupied=mine_occupied,
            allow_pickup_range_fallback=allow_pickup_range_fallback,
        )
        used_fallback = evidence.get("policy") == PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY
        if used_fallback:
            fallback_count += 1
            if len(fallback_examples) < 12:
                fallback_examples.append(
                    {
                        "sourceKey": entity.get("sourceKey"),
                        "sid": sid,
                        "objectId": placement.get("id"),
                        "previousNode": node,
                        "node": new_node,
                        "visitNode": evidence.get("visitNode"),
                        "alternateInteractNode": evidence.get("alternateInteractNode"),
                        "neighborSearchIndex": evidence.get("neighborSearchIndex"),
                        "occupiedNodes": evidence.get("occupiedNodes"),
                        "gateNodes": evidence.get("gateNodes"),
                    }
                )
        if new_node != node:
            changed += 1
            if len(examples) < 12:
                examples.append(
                    {
                        "sourceKey": entity.get("sourceKey"),
                        "sid": sid,
                        "objectId": placement.get("id"),
                        "previousNode": node,
                        "node": new_node,
                        "visitNode": evidence.get("visitNode"),
                        "occupiedNodes": evidence.get("occupiedNodes"),
                        "gateNodes": evidence.get("gateNodes"),
                        "usedPickupRangeFallback": used_fallback,
                    }
                )
            placement["node"] = new_node
            placement["mineClearanceEvidence"] = evidence
        elif used_fallback:
            placement["mineClearanceEvidence"] = evidence
    return {
        "policy": "resource_gate_ring_clear_of_mine_occupied",
        "status": "applied",
        "pickupRangeFallbackPolicy": PICKUP_GATE_RING_NEARBY_RANGE_FALLBACK_POLICY,
        "pickupRangeFallbackEnabled": allow_pickup_range_fallback,
        "mineOccupiedCellCount": mine_occupied_count,
        "keyGateReservedCellCount": len(set(reserved_cells or ())),
        "reanchoredCount": changed,
        "pickupRangeFallbackCount": fallback_count,
        "examples": examples,
        "pickupRangeFallbackExamples": fallback_examples,
    }


def derive_pivot_center_aligned_node(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    default_node: int,
) -> tuple[int, dict[str, Any]]:
    """Place open-center GATE-ring SIDs (random-squad) so the config center sits on H3 visit.

    Occupied-center pickups (gold/chest/item) use ``derive_gate_ring_anchor_on_visit_node``.
    """
    size_x = native_config.get("sizeX")
    size_z = native_config.get("sizeZ")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        raise ValueError(f"{replacement_sid} needs sizeX/sizeZ for pivot-center alignment")
    pivot_x = native_config.get("pivotX")
    pivot_z = native_config.get("pivotZ")
    if not isinstance(pivot_x, int):
        pivot_x = size_x // 2
    if not isinstance(pivot_z, int):
        pivot_z = size_z // 2
    visit_nodes = entity_visit_nodes(entity)
    if len(visit_nodes) > 1:
        raise ValueError(
            f"{replacement_sid} pivot-center requires exactly one HoMM3 visit cell for "
            f"{entity.get('sourceKey')}; got {sorted(visit_nodes)}"
        )
    # Empty H3 visit mask → source-anchor default_node (same land-on / GATE-ring policy).
    visit_node = next(iter(visit_nodes)) if visit_nodes else default_node
    visit_x = visit_node % OLDEN_WIDTH
    visit_y = visit_node // OLDEN_WIDTH
    # Config high-z is map-south: map_y = anchor_y + (size_z - 1 - config_z).
    anchor_x = visit_x - pivot_x
    anchor_y = visit_y - (size_z - 1 - pivot_z)
    if not (0 <= anchor_x < OLDEN_WIDTH and 0 <= anchor_y < OLDEN_HEIGHT):
        raise ValueError(
            f"{replacement_sid} pivot-center anchor out of bounds for {entity.get('sourceKey')}: "
            f"({anchor_x},{anchor_y}) visit={visit_node} pivot=({pivot_x},{pivot_z})"
        )
    node = anchor_y * OLDEN_WIDTH + anchor_x
    evidence = {
        "policy": "pivot_center_aligned_to_h3_visit",
        "reason": "open_center_gate_ring_sid_center_coincides_with_source_visit_cell",
        "decision": "align_olden_node_so_pivot_equals_h3_visit",
        "nativeFootprint": {
            "width": size_x,
            "height": size_z,
            "source": "pivot_center_aligned_to_h3_visit",
            "pivotLocal": [pivot_x, pivot_z],
        },
        "node": node,
        "visitNode": visit_node,
        "sourceAnchorNode": default_node,
    }
    return node, evidence


def derive_native_building_anchor_node(
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    default_node: int,
    *,
    rotation: int,
) -> tuple[int, dict[str, Any]]:
    """Keep a permanent generator object's native pivot on the H3 source anchor."""
    if not exact_fp.uses_native_building_anchor_policy(native_config):
        raise ValueError(
            f"{replacement_sid} is not eligible for native building anchor placement "
            f"for {entity.get('sourceKey')}"
        )
    model = _native_building_footprint_model(
        replacement_sid,
        native_config,
        default_node,
        rotation,
    )
    in_envelope_gates = _native_cells_in_active_source_envelope(model.gate_cells, default_node)
    if not in_envelope_gates:
        raise ValueError(
            f"{replacement_sid} has no in-envelope native GATE for "
            f"{entity.get('sourceKey')}"
        )
    return default_node, {
        "policy": "native_building_anchor_at_h3_source_anchor_v1",
        "reason": "native_generator_building_anchor_is_h3_source_anchor",
        "decision": "preserve_h3_source_anchor_for_native_building",
        "node": default_node,
        "sourceAnchorNode": default_node,
        "rotation": rotation,
        "nativeFootprint": {
            "width": native_config.get("sizeX"),
            "height": native_config.get("sizeZ"),
            "pivotLocal": [
                native_config.get("pivotX"),
                native_config.get("pivotZ"),
            ],
            "source": "native_object_config_pivot_projection",
            "occupiedCellCount": len(model.occupied_cells),
            "gateCellCount": len(model.gate_cells),
            "inEnvelopeGateCellCount": len(in_envelope_gates),
            "unresolvedAuditFindings": list(model.unresolved),
        },
    }


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

    shape = exact_fp.classify_object_config_shape(native_config, replacement_sid)
    rot = int(rotation if rotation is not None else OLDEN_DEFAULT_ROTATION)
    if shape == "gate_ring":
        if exact_fp.uses_native_building_anchor_policy(native_config):
            # Native generator buildings share pickup ring geometry, but their
            # stored node remains the H3 placement reference; the native query
            # applies pivot/mirror semantics to locate OCC and GATE cells.
            return derive_native_building_anchor_node(
                entity,
                replacement_sid,
                native_config,
                default_node,
                rotation=rot,
            )
        # Resource/artifact/meta rings retain the pickup/enemy placement policy:
        # emit node on an H3 visit GATE rather than making the pickup body the
        # interaction cell.
        return derive_gate_ring_anchor_on_visit_node(
            entity, replacement_sid, native_config, default_node, rotation=rot
        )

    # Town / city SIDs must run before exact-footprint GATE→visit keep-donor paths.
    # Landon cities are exact-footprint GATE clones; those early returns previously
    # short-circuited town_gate_align and left GATE on the H3 visit/courtyard cell.
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
            body_center_node = entity_town_body_center_node(entity)
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

    exact_spec = exact_fp.footprint_spec_from_config(native_config)
    if exact_spec is not None or exact_fp.is_exact_footprint_sid(replacement_sid):
        if exact_spec is None:
            raise ValueError(
                f"exact footprint SID {replacement_sid} missing {exact_fp.META_KEY} metadata "
                f"for {entity.get('sourceKey')}"
            )
        if exact_spec.gate_config_x is not None and exact_spec.gate_config_z is not None:
            visit_nodes = entity_visit_nodes(entity)
            if len(visit_nodes) != 1:
                raise ValueError(
                    f"same-size GATE clone {replacement_sid} for {entity.get('sourceKey')} "
                    f"requires exactly one HoMM3 visit cell; found {sorted(visit_nodes)}"
                )
            return exact_fp.derive_gate_aligned_node(
                visit_node=next(iter(visit_nodes)),
                native_config=native_config,
                footprint=exact_spec,
                grid_width=OLDEN_WIDTH,
                grid_height=OLDEN_HEIGHT,
                default_node=default_node,
                rotation=int(rotation or OLDEN_DEFAULT_ROTATION),
                can_be_mirrored=native_config.get("canBeMirrored") is True,
            )
        # Same-size clone without GATE: keep standard BR / solid-square placement below.

    # Keep-donor exact-footprint functionals with a preferred GATE marker:
    # landon / single_gate → align that marker to the H3 visit.
    if _EXACT_FOOTPRINT_REGISTRY is not None:
        source_index = entity.get("sourceIndex")
        entry = (
            _EXACT_FOOTPRINT_REGISTRY.by_source_index.get(source_index)
            if isinstance(source_index, int)
            else None
        )
        if (
            entry is not None
            and entry.action == "keep_donor"
            and entry.footprint is not None
            and entry.footprint.gate_config_x is not None
            and entry.footprint.gate_config_z is not None
            and replacement_sid == entry.result_sid
            and shape in {"single_gate", "landon"}
        ):
            visit_nodes = entity_visit_nodes(entity)
            if len(visit_nodes) == 1:
                return exact_fp.derive_gate_aligned_node(
                    visit_node=next(iter(visit_nodes)),
                    native_config=native_config,
                    footprint=entry.footprint,
                    grid_width=OLDEN_WIDTH,
                    grid_height=OLDEN_HEIGHT,
                    default_node=default_node,
                    rotation=int(rotation or OLDEN_DEFAULT_ROTATION),
                    can_be_mirrored=native_config.get("canBeMirrored") is True,
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

    # HoMM3 boats are 1x1 visitable (visit often one cell west of BR). Do not use the
    # multi-tile BR→SW sawmill anchor — that invented a 2x2 body and ate beach gaps.
    if replacement_sid == HOMM3_BOAT_SID:
        visit_nodes = entity_visit_nodes(entity)
        if len(visit_nodes) != 1:
            raise ValueError(
                f"homm3_boat for {entity.get('sourceKey')} requires exactly one HoMM3 "
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

    # hero-spawner is single_gate keep-donor: GATE must sit on the H3 visit. Do not fall
    # through to BR occupied-bounds (south-edge campaign heroes then sit one footprint
    # off, and spawn-unbury can walk them onto envelope cliffs).
    if replacement_sid == OLDEN_HERO_SPAWNER_SID:
        visit_nodes = entity_visit_nodes(entity)
        if not visit_nodes and entity.get("templateVisitMask") is None:
            # Town-garrison / overlay heroes sometimes omit H3 visit masks entirely.
            # Stand on the source BR (default_node) rather than inventing a visit cell.
            visit_nodes = {default_node}
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
    # Scenery solid squares: mountains/trees are 1x1-only (multi-tile meshes overhang
    # H3-open neighbors). Pools keep BR-anchor placement (variant sizing is separate).
    scenery_square = None
    if (
        role in {"mountain", "tree"}
        and isinstance(width, int)
        and width == height
        and width == 1
        and isinstance(cell_count, int)
        and cell_count == 1
    ):
        blocks = source_block_offsets(entity)
        origin = sub_mod.prefer_homm3_block_solid_square(blocks, width)
        if origin is None:
            raise ValueError(
                f"scenery SID {replacement_sid} is solid 1x1 but HoMM3 block mask "
                f"for {entity.get('sourceKey')} has no solid 1x1 subset "
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
    return f"{mission_squad_sid_prefix()}_{replacement_sid}_{object_id}".replace("-", "_")


RANDOM_SQUAD_STRENGTH_MODEL = read_json(RANDOM_MONSTER_STRENGTH_MODEL_PATH)
H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL = {int(key): int(value) for key, value in RANDOM_SQUAD_STRENGTH_MODEL["nominalH3RandomStackCountsByLevel"].items()}
RANDOM_SQUAD_REQUESTED_VALUE_ROUNDING = float(RANDOM_SQUAD_STRENGTH_MODEL["requestedValueRounding"])
RANDOM_SQUAD_STRENGTH_MODEL_ID = str(RANDOM_SQUAD_STRENGTH_MODEL["model"])
_TIER_MEDIAN_SQUAD_VALUE_CACHE: dict[int, float] | None = None
# Town-garrison / map-event / army / concrete adventure-map monster creatureType → Olden unit SID.
# Indices match Complete Edition CRTRAITS.TXT creature rows (AB/SoD).
# Concrete monster stacks (object id 54) share this table — do not keep a partial
# CONCRETE_MONSTER_UNIT_BY_SUBTYPE allowlist that silently demotes known units
# (e.g. Stronghold goblins) to hostile empty random-squad.
MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE: dict[int, str] = {
    # Castle
    0: "h3_pikeman",
    1: "h3_pikeman_upg",
    2: "h3_archer",
    3: "h3_archer_upg",
    4: "h3_griffin",
    5: "h3_griffin_upg",
    6: "h3_swordsman",
    7: "h3_swordsman_upg",
    8: "h3_monk",
    9: "h3_monk_upg",
    10: "h3_cavalier",
    11: "h3_cavalier_upg",
    12: "h3_angel",
    13: "h3_angel_upg",
    # Rampart
    14: "h3_centaur",
    15: "h3_centaur_captain",
    16: "h3_dwarf",
    17: "h3_battle_dwarf",
    18: "h3_wood_elf",
    19: "h3_grand_elf",
    20: "h3_pegasus",
    21: "h3_silver_pegasus",
    22: "h3_dendroid_guard",
    23: "h3_dendroid_soldier",
    24: "h3_unicorn",
    25: "h3_war_unicorn",
    26: "h3_green_dragon",
    27: "h3_gold_dragon",
    # Tower
    28: "h3_gremlin",
    29: "h3_gremlin_upg",
    30: "h3_gargoyle",
    31: "h3_gargoyle_upg",
    32: "h3_golem",
    33: "h3_golem_upg",
    34: "h3_mage",
    35: "h3_mage_upg",
    36: "h3_genie",
    37: "h3_genie_upg",
    38: "h3_naga",
    39: "h3_naga_upg",
    40: "h3_giant",
    41: "h3_giant_upg",
    # Inferno
    42: "h3_imp",
    43: "h3_imp_upg",
    44: "h3_gog",
    45: "h3_gog_upg",
    46: "h3_hell_hound",
    47: "h3_hell_hound_upg",
    48: "h3_demon",
    49: "h3_demon_upg",
    50: "h3_pit_fiend",
    51: "h3_pit_fiend_upg",
    52: "h3_efreeti",
    53: "h3_efreeti_upg",
    54: "h3_devil",
    55: "h3_devil_upg",
    # Necropolis
    56: "h3_skeleton",
    57: "h3_skeleton_upg",
    58: "h3_walking_dead",
    59: "h3_walking_dead_upg",
    60: "h3_wight",
    61: "h3_wight_upg",
    62: "h3_vampire",
    63: "h3_vampire_upg",
    64: "h3_lich",
    65: "h3_lich_upg",
    66: "h3_black_knight",
    67: "h3_black_knight_upg",
    68: "h3_bone_dragon",
    69: "h3_bone_dragon_upg",
    # Dungeon
    70: "h3_troglodyte",
    71: "h3_troglodyte_upg",
    72: "h3_harpy",
    73: "h3_harpy_upg",
    74: "h3_beholder",
    75: "h3_beholder_upg",
    76: "h3_medusa",
    77: "h3_medusa_upg",
    78: "h3_minotaur",
    79: "h3_minotaur_upg",
    80: "h3_manticore",
    81: "h3_manticore_upg",
    82: "h3_red_dragon",
    83: "h3_red_dragon_upg",
    # Stronghold
    84: "h3_goblin",
    85: "h3_goblin_upg",
    86: "h3_wolf_rider",
    87: "h3_wolf_rider_upg",
    88: "h3_orc",
    89: "h3_orc_upg",
    90: "h3_ogre",
    91: "h3_ogre_upg",
    92: "h3_roc",
    93: "h3_roc_upg",
    94: "h3_cyclops",
    95: "h3_cyclops_upg",
    96: "h3_behemoth",
    97: "h3_behemoth_upg",
    # Fortress
    98: "h3_gnoll",
    99: "h3_gnoll_upg",
    100: "h3_lizardman",
    101: "h3_lizardman_upg",
    102: "h3_gorgon",
    103: "h3_gorgon_upg",
    104: "h3_serpent_fly",
    105: "h3_serpent_fly_upg",
    106: "h3_basilisk",
    107: "h3_basilisk_upg",
    108: "h3_wyvern",
    109: "h3_wyvern_upg",
    110: "h3_hydra",
    111: "h3_hydra_upg",
    # Neutrals + Conflux (Complete CRTRAITS order; NOT USED slots omitted)
    112: "h3_air_elemental",
    113: "h3_earth_elemental",
    114: "h3_fire_elemental",
    115: "h3_water_elemental",
    116: "h3_golem",  # Gold Golem
    117: "h3_golem_upg",  # Diamond Golem
    118: "h3_pixie",
    119: "h3_pixie_upg",
    120: "h3_psychic_elemental",
    121: "h3_psychic_elemental_upg",
    123: "h3_water_elemental_upg",  # Ice Elemental
    125: "h3_earth_elemental_upg",  # Magma Elemental
    127: "h3_air_elemental_upg",  # Storm Elemental
    129: "h3_fire_elemental_upg",  # Energy Elemental
    130: "h3_firebird",
    131: "h3_firebird_upg",
    132: "h3_azure_dragon",
    133: "h3_crystal_dragon",
    134: "h3_faerie_dragon",
    135: "h3_rust_dragon",
    136: "h3_enchanter",
    137: "h3_sharpshooter",
    138: "h3_neutral_halfling",
    139: "h3_peasant",
    140: "h3_boar",
    141: "h3_mummy",
    142: "h3_nomad",
    143: "h3_rogue",
    144: "h3_troll",
}
# Concrete adventure-map monster stacks (object id 54) use the same CRTRAITS index map.
CONCRETE_MONSTER_UNIT_BY_SUBTYPE = dict(MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE)
# HoMM3 creatureType ints → Olden unit SIDs.
H3_CREATURE_TYPE_TO_UNIT_SID = dict(MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE)
H3_CREATURE_EMPTY_TYPES = frozenset({0xFF, 0xFFFF})
# Adventure-map DEF names lockstep with CONCRETE_MONSTER_UNIT_BY_SUBTYPE (harvested from
# Complete Edition object walks; casing preserved from source templates).
CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE = {
    0: "AvWPike.def",  # h3_pikeman
    1: "AVWpikx0.def",  # h3_pikeman_upg
    2: "AvWLCrs.def",  # h3_archer
    3: "AvWHCrs.def",  # h3_archer_upg
    4: "AvWGrif.def",  # h3_griffin
    5: "AVWgrix0.def",  # h3_griffin_upg
    6: "AVWswrd0.def",  # h3_swordsman
    7: "AVWswrx0.def",  # h3_swordsman_upg
    8: "AvWMonk.def",  # h3_monk
    9: "AVWmonx0.def",  # h3_monk_upg
    10: "AVWcvlr0.def",  # h3_cavalier
    11: "AVWcvlx0.def",  # h3_cavalier_upg
    12: "AvWAngl.def",  # h3_angel
    13: "AvWArch.def",  # h3_angel_upg
    14: "AVWcent0.def",  # h3_centaur
    15: "AVWcenx0.def",  # h3_centaur_captain
    16: "AVWdwrf0.def",  # h3_dwarf
    17: "AVWdwrx0.def",  # h3_battle_dwarf
    18: "AVWelfw0.def",  # h3_wood_elf
    19: "AVWelfx0.def",  # h3_grand_elf
    20: "AVWpega0.def",  # h3_pegasus
    21: "AVWpegx0.def",  # h3_silver_pegasus
    22: "AVWtree0.def",  # h3_dendroid_guard
    23: "AVWtrex0.def",  # h3_dendroid_soldier
    24: "AVWunic0.def",  # h3_unicorn
    25: "AVWunix0.def",  # h3_war_unicorn
    26: "AVWdrag0.def",  # h3_green_dragon
    27: "AVWdrax0.def",  # h3_gold_dragon
    28: "AVWgrem0.def",  # h3_gremlin
    29: "AVWgrex0.def",  # h3_gremlin_upg
    30: "AVWgarg0.def",  # h3_gargoyle
    31: "AVWgarx0.def",  # h3_gargoyle_upg
    32: "AVWgolm0.def",  # h3_golem
    33: "AVWgolx0.def",  # h3_golem_upg
    34: "AVWmage0.def",  # h3_mage
    35: "AVWmagx0.def",  # h3_mage_upg
    36: "AVWgeni0.def",  # h3_genie
    37: "AVWgenx0.def",  # h3_genie_upg
    38: "AVWnaga0.def",  # h3_naga
    39: "AVWnagx0.def",  # h3_naga_upg
    40: "AVWtitn0.def",  # h3_giant
    41: "AVWtitx0.def",  # h3_giant_upg
    42: "AVWimp0.def",  # h3_imp
    43: "AVWimpx0.def",  # h3_imp_upg
    44: "AVWgog0.def",  # h3_gog
    45: "AVWgogx0.def",  # h3_gog_upg
    46: "AVWhoun0.def",  # h3_hell_hound
    47: "AVWhoux0.def",  # h3_hell_hound_upg
    48: "AVWdemn0.def",  # h3_demon
    49: "AVWdemx0.def",  # h3_demon_upg
    50: "AVWpitf0.def",  # h3_pit_fiend
    51: "AVWpitx0.def",  # h3_pit_fiend_upg
    52: "AVWefre0.def",  # h3_efreeti
    53: "AVWefrx0.def",  # h3_efreeti_upg
    54: "AVWdevl0.def",  # h3_devil
    55: "AVWdevx0.def",  # h3_devil_upg
    56: "AVWskel0.def",  # h3_skeleton
    57: "AVWskex0.def",  # h3_skeleton_upg
    58: "AVWzomb0.def",  # h3_walking_dead
    59: "AVWzomx0.def",  # h3_walking_dead_upg
    60: "AvWWigh.def",  # h3_wight
    61: "AVWwigx0.def",  # h3_wight_upg
    62: "AVWvamp0.def",  # h3_vampire
    63: "AVWvamx0.def",  # h3_vampire_upg
    64: "AVWlich0.def",  # h3_lich
    65: "AVWlicx0.def",  # h3_lich_upg
    66: "AVWbkni0.def",  # h3_black_knight
    67: "AVWbknx0.def",  # h3_black_knight_upg
    68: "AVWbone0.def",  # h3_bone_dragon
    69: "AVWbonx0.def",  # h3_bone_dragon_upg
    70: "AVWtrog0.def",  # h3_troglodyte
    71: "AvWInfr.def",  # h3_troglodyte_upg
    72: "AVWharp0.def",  # h3_harpy
    73: "AVWharx0.def",  # h3_harpy_upg
    74: "AVWbehl0.def",  # h3_beholder
    75: "AVWbehx0.def",  # h3_beholder_upg
    76: "AvWMeds.def",  # h3_medusa
    77: "AVWmedx0.def",  # h3_medusa_upg
    78: "AvWMino.def",  # h3_minotaur
    79: "AVWminx0.def",  # h3_minotaur_upg
    80: "AVWmant0.def",  # h3_manticore
    81: "AVWmanx0.def",  # h3_manticore_upg
    82: "AvWRDrg.def",  # h3_red_dragon
    83: "AVWddrx0.def",  # h3_red_dragon_upg
    84: "AVWgobl0.def",  # h3_goblin
    85: "AVWgobx0.def",  # h3_goblin_upg (hobgoblin)
    86: "AVWwolf0.def",  # h3_wolf_rider
    87: "AVWwolx0.def",  # h3_wolf_rider_upg
    88: "AVWorc0.def",  # h3_orc
    89: "AVWorcx0.def",  # h3_orc_upg
    90: "AVWogre0.def",  # h3_ogre
    91: "AVWogrx0.def",  # h3_ogre_upg
    92: "AVWroc0.def",  # h3_roc
    93: "AVWrocx0.def",  # h3_roc_upg
    94: "AVWcycl0.def",  # h3_cyclops
    95: "AVWcycx0.def",  # h3_cyclops_upg
    96: "AVWbhmt0.def",  # h3_behemoth
    97: "AVWbhmx0.def",  # h3_behemoth_upg
    98: "AVWgnll0.def",  # h3_gnoll
    99: "AVWgnlx0.def",  # h3_gnoll_upg
    100: "AvWLizr.def",  # h3_lizardman
    101: "AVWlizx0.def",  # h3_lizardman_upg
    102: "AvWGorg.def",  # h3_gorgon
    103: "AVWgorx0.def",  # h3_gorgon_upg
    104: "AvWDFly.def",  # h3_serpent_fly
    105: "AvWDFir.def",  # h3_serpent_fly_upg
    106: "AvWBasl.def",  # h3_basilisk
    107: "AvWGBas.def",  # h3_basilisk_upg
    108: "AvWWyvr.def",  # h3_wyvern
    109: "AVWwyvx0.def",  # h3_wyvern_upg
    110: "AvWHydr.def",  # h3_hydra
    111: "AVWhydx0.def",  # h3_hydra_upg
    112: "AVWelma0.def",  # h3_air_elemental
    113: "AVWelme0.def",  # h3_earth_elemental
    114: "AVWelmf0.def",  # h3_fire_elemental
    115: "AVWelmw0.def",  # h3_water_elemental
    116: "AVWglmg0.def",  # h3_golem (Gold Golem)
    117: "AVWglmd0.def",  # h3_golem_upg (Diamond Golem)
    118: "AVWpixie.def",  # h3_pixie
    119: "AVWsprit.def",  # h3_pixie_upg
    120: "AVWpsye.def",  # h3_psychic_elemental
    121: "AVWmagel.def",  # h3_psychic_elemental_upg
    123: "AVWicee.def",  # h3_water_elemental_upg
    125: "AVWstone.def",  # h3_earth_elemental_upg
    127: "AVWstorm.def",  # h3_air_elemental_upg
    129: "AVWnrg.def",  # h3_fire_elemental_upg
    130: "AVWfbird.def",  # h3_firebird
    131: "AVWphx.def",  # h3_firebird_upg
    132: "AVWazure.def",  # h3_azure_dragon
    133: "AVWcdrg.def",  # h3_crystal_dragon
    134: "AVWfdrg.def",  # h3_faerie_dragon
    135: "AVWrust.def",  # h3_rust_dragon
    136: "AVWench.def",  # h3_enchanter
    137: "AVWsharp.def",  # h3_sharpshooter
    138: "AVWhalf.def",  # h3_neutral_halfling
    139: "AVWpeas.def",  # h3_peasant
    140: "AVWboar.def",  # h3_boar
    141: "AVWmumy.def",  # h3_mummy
    142: "AVWnomd.def",  # h3_nomad
    143: "AVWrog.def",  # h3_rogue
    144: "AVWtrll.def",  # h3_troll
}
# AB maps sometimes store mismatched templateSubtype vs animation; prefer animation.
CONCRETE_MONSTER_UNIT_BY_ANIMATION = {
    value.lower(): CONCRETE_MONSTER_UNIT_BY_SUBTYPE[key]
    for key, value in CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE.items()
}
if set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE) != set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE):
    raise RuntimeError(
        "CONCRETE_MONSTER_UNIT_BY_SUBTYPE and CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE keys "
        f"must stay in lockstep; unit_only={sorted(set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE) - set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE))} "
        f"anim_only={sorted(set(CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE) - set(CONCRETE_MONSTER_UNIT_BY_SUBTYPE))}"
    )
INTRO_DIALOG_SID = "homecoming_intro_dialog"
# Default keeps Homecoming Core.zip paths; raw_translation patches MISSION_ID per profile.
MISSION_ID = "homecoming"
SQUAD_OVERLAY_MEMBER_ROOT = "DB/squads/squads_custom_maps/homecoming"
_UNIT_SQUAD_VALUE_CACHE: dict[str, dict[str, Any]] | None = None


def set_mission_id(mission_id: str) -> None:
    """Namespace squad/dialog Core overlay members by mission (fail-closed empty)."""
    global MISSION_ID, SQUAD_OVERLAY_MEMBER_ROOT
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise ValueError("mission_id must be a non-empty string")
    MISSION_ID = mission_id.strip()
    SQUAD_OVERLAY_MEMBER_ROOT = f"DB/squads/squads_custom_maps/{MISSION_ID}"


def mission_squad_sid_prefix() -> str:
    return MISSION_ID


def campaign_dialog_folder_name() -> str:
    # Homecoming keeps historical Core folder casing.
    if MISSION_ID == "homecoming":
        return "Homecoming"
    return "".join(part[:1].upper() + part[1:] for part in MISSION_ID.split("_") if part)


def is_concrete_h3_monster_stack(entity: dict[str, Any]) -> bool:
    if entity.get("templateObjectId") != 54:
        return False
    subtype = entity.get("templateSubtype")
    animation = str(entity.get("templateAnimation") or "").lower()
    return subtype in CONCRETE_MONSTER_UNIT_BY_SUBTYPE or animation in CONCRETE_MONSTER_UNIT_BY_ANIMATION


def concrete_monster_unit_sid(entity: dict[str, Any]) -> str:
    subtype = entity.get("templateSubtype")
    animation = str(entity.get("templateAnimation") or "")
    animation_key = animation.lower()
    if subtype in CONCRETE_MONSTER_UNIT_BY_SUBTYPE:
        expected_animation = CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE[subtype]
        if animation == expected_animation or animation_key == expected_animation.lower():
            return CONCRETE_MONSTER_UNIT_BY_SUBTYPE[subtype]
    if animation_key in CONCRETE_MONSTER_UNIT_BY_ANIMATION:
        # Prefer authored animation when subtype/animation diverge (seen on AB Conflux maps).
        return CONCRETE_MONSTER_UNIT_BY_ANIMATION[animation_key]
    if subtype in CONCRETE_MONSTER_UNIT_BY_SUBTYPE:
        expected_animation = CONCRETE_MONSTER_ANIMATION_BY_SUBTYPE[subtype]
        raise ValueError(
            f"concrete monster subtype/animation mismatch for {entity.get('sourceKey')}: "
            f"subtype={subtype} animation={entity.get('templateAnimation')} "
            f"expected={expected_animation}"
        )
    raise ValueError(
        f"unsupported concrete monster for {entity.get('sourceKey')}: "
        f"subtype={subtype} animation={entity.get('templateAnimation')}"
    )


def h3_creature_type_to_unit_sid(creature_type: int, *, context: str) -> str:
    """Map HoMM3 creatureType int to Olden h3_ unit SID (concrete neutrals + map-event guards)."""
    if creature_type in H3_CREATURE_EMPTY_TYPES:
        raise ValueError(f"empty HoMM3 creatureType for {context}: {creature_type}")
    unit_sid = H3_CREATURE_TYPE_TO_UNIT_SID.get(creature_type)
    if unit_sid is None:
        raise ValueError(
            f"no HoMM3→Olden unit mapping for creatureType {creature_type} at {context}; "
            f"extend CONCRETE_MONSTER_UNIT_BY_SUBTYPE or MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE"
        )
    return unit_sid


def mapped_map_event_guard_stacks(
    stacks: list[dict[str, Any]],
    *,
    context: str,
) -> list[dict[str, Any]]:
    """Map H3 map-event guardStacks to exact Olden unit rows ({sid, count})."""
    mapped: list[dict[str, Any]] = []
    for stack in stacks:
        if not isinstance(stack, dict):
            raise ValueError(f"malformed map-event guard stack at {context}: {stack!r}")
        creature_type = stack.get("creatureType")
        count = stack.get("count")
        if not isinstance(creature_type, int) or not isinstance(count, int):
            raise ValueError(f"map-event guard stack missing creatureType/count at {context}: {stack!r}")
        if count <= 0 or creature_type in H3_CREATURE_EMPTY_TYPES:
            continue
        unit_sid = h3_creature_type_to_unit_sid(creature_type, context=context)
        if creature_type in MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE:
            expected = MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE[creature_type]
            if unit_sid != expected:
                raise ValueError(
                    f"map-event guard creatureType {creature_type} at {context} "
                    f"must resolve to {expected!r}; got {unit_sid!r}"
                )
        mapped.append({"sid": unit_sid, "count": count})
    if not mapped:
        raise ValueError(f"map-event guard stacks empty after mapping at {context}")
    return mapped


def map_event_guard_prop_squad_row(
    object_id: int,
    *,
    stacks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Exact-roster propSquads row (vanilla c_M2/c_M5 unitProps shape)."""
    unit_props = [{"sid": stack["sid"], "count": int(stack["count"])} for stack in stacks]
    if not unit_props:
        raise ValueError(f"map-event guard unitProps empty for object {object_id}")
    return {
        "type": 0,
        "id": object_id,
        "isMainGuard": False,
        "isStartBattleImmediately": False,
        "reactionType": 2,
        "weeklyIncrementBonus": 0.0,
        "unitProps": unit_props,
    }


def map_event_guard_value_stacks(
    stacks: list[dict[str, Any]],
    *,
    context: str,
) -> list[dict[str, Any]]:
    """Attach count×squadValue budgets for random-squad overlays / requestedValue."""
    unit_rows = h3_unit_logic_rows()
    enriched: list[dict[str, Any]] = []
    for stack in stacks:
        unit_sid = str(stack["sid"])
        count = int(stack["count"])
        logic = unit_rows.get(unit_sid)
        if not isinstance(logic, dict):
            raise ValueError(f"missing Core unit logic for map-event guard {unit_sid} at {context}")
        squad_value = logic.get("squadValue")
        if not isinstance(squad_value, (int, float)) or float(squad_value) <= 0:
            raise ValueError(f"invalid squadValue for map-event guard {unit_sid} at {context}: {squad_value!r}")
        enriched.append(
            {
                "sid": unit_sid,
                "count": count,
                "valueBudget": int(rounded_requested_value(float(count) * float(squad_value))),
            }
        )
    if not enriched:
        raise ValueError(f"map-event guard value stacks empty at {context}")
    return enriched


def map_event_guard_requested_value(stacks: list[dict[str, Any]]) -> float:
    total = sum(int(stack["valueBudget"]) for stack in stacks)
    if total < 1:
        raise ValueError(f"map-event guard requestedValue must be positive; stacks={stacks!r}")
    return float(total)


def map_event_guard_prop_random_squad_row(
    object_id: int,
    *,
    squad_overlay_sid: str,
    stacks: list[dict[str, Any]],
) -> dict[str, Any]:
    """propRandomSquads row required by SpawnsCreator for random-squad hosts."""
    if not squad_overlay_sid:
        raise ValueError(f"map-event guard overlay sid empty for object {object_id}")
    return {
        "type": 0,
        "id": object_id,
        "sids": [squad_overlay_sid],
        "requestedValue": map_event_guard_requested_value(stacks),
        "fraction": "",
        "tier": 0,
        "isMainGuard": False,
        "reactionType": 2,
        "customTopUnit": str(stacks[0]["sid"]),
        "weeklyIncrementBonus": 0.0,
        "diplomacyUnitsCountBonus": 0.0,
        "isEscape": False,
        # Neutrals/guards: allow adventure-map auto-battle. Enemy-hero auto is
        # gated separately via settings.disableAutoBattleAgainstEnemyHeroes.
        "isAutobatle": True,
        "isFreeDiplomacy": False,
        "isCampaignFreeDiplomacy": False,
        "isCampaignDiplomacy": False,
        "isIgnoreMultiply": False,
        "obstruction": "",
        "customStacks": 0,
    }


def map_event_guard_squad_overlay_doc(
    *,
    squad_overlay_sid: str,
    stacks: list[dict[str, Any]],
) -> dict[str, Any]:
    requested = int(map_event_guard_requested_value(stacks))
    base_units = [{"s": stack["sid"], "v": int(stack["valueBudget"])} for stack in stacks]
    dynamic_units = [stack["sid"] for stack in stacks]
    return {
        "array": [
            {
                "id": squad_overlay_sid,
                "squad": [],
                "useOldSquads": False,
                "rollChance": 0,
                "canBeMainGuard": True,
                "baseSquad": {"units": base_units},
                "dynamicSquad": {"requiredValue": requested, "units": dynamic_units},
                "randomSquad": {"maxValue": requested, "units": list(base_units)},
                "tier": 0,
                "fraction": "",
            }
        ]
    }


def entity_is_town(entity: dict[str, Any]) -> bool:
    if entity.get("category") == "town":
        return True
    town_state = entity.get("townState")
    return isinstance(town_state, dict) and (
        "garrisonStacks" in town_state or "hasGarrison" in town_state or "builtBuildingsMask" in town_state
    )


def entity_has_town_garrison(entity: dict[str, Any]) -> bool:
    if not entity_is_town(entity):
        return False
    town_state = entity.get("townState") if isinstance(entity.get("townState"), dict) else {}
    if entity.get("hasGarrison") is True or town_state.get("hasGarrison") is True:
        return True
    for stacks in (entity.get("garrisonStacks"), town_state.get("garrisonStacks")):
        if isinstance(stacks, list) and any(
            isinstance(stack, dict)
            and isinstance(stack.get("count"), int)
            and stack["count"] > 0
            and isinstance(stack.get("creatureType"), int)
            and stack["creatureType"] not in H3_CREATURE_EMPTY_TYPES
            for stack in stacks
        ):
            return True
    return False


def mapped_town_garrison_stacks(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """Map HoMM3 town defenders to Olden unit rows ({sid, count, valueBudget}).

    Native PropCity has no garrisonStacks field (Hex.Map.PropCity). Shipped maps
    bind town defense via ``propRandomSquads.sids`` + squad overlays (see Thirst
    city 5881 / story ``t_C*.map``), never city-linked ``propSquads.unitProps``.
    """
    if not entity_is_town(entity):
        return []
    town_state = entity.get("townState") if isinstance(entity.get("townState"), dict) else {}
    raw_stacks = entity.get("garrisonStacks")
    if not isinstance(raw_stacks, list) or not raw_stacks:
        raw_stacks = town_state.get("garrisonStacks")
    if not isinstance(raw_stacks, list):
        return []
    context = str(entity.get("sourceKey") or entity.get("sourceIndex") or "town")
    mapped: list[dict[str, Any]] = []
    unit_rows = h3_unit_logic_rows()
    for stack in raw_stacks:
        if not isinstance(stack, dict):
            raise ValueError(f"malformed garrison stack at {context}: {stack!r}")
        creature_type = stack.get("creatureType")
        count = stack.get("count")
        if not isinstance(creature_type, int) or not isinstance(count, int):
            raise ValueError(f"garrison stack missing creatureType/count at {context}: {stack!r}")
        if count <= 0 or creature_type in H3_CREATURE_EMPTY_TYPES:
            continue
        unit_sid = h3_creature_type_to_unit_sid(creature_type, context=context)
        logic = unit_rows.get(unit_sid)
        if not isinstance(logic, dict):
            raise ValueError(f"missing Core unit logic for town garrison {unit_sid} at {context}")
        squad_value = logic.get("squadValue")
        if not isinstance(squad_value, (int, float)):
            raise ValueError(f"invalid squadValue for town garrison {unit_sid} at {context}: {squad_value!r}")
        mapped.append({
            "sid": unit_sid,
            "count": count,
            "valueBudget": int(rounded_requested_value(float(count) * float(squad_value))),
        })
    return mapped


def town_garrison_squad_sid(entity: dict[str, Any]) -> str:
    source_key = str(entity.get("sourceKey") or entity.get("sourceIndex") or "town")
    sanitized = source_key.replace(":", "_").replace("-", "_")
    return f"{mission_squad_sid_prefix()}_town_garrison_{sanitized}"


def town_garrison_requested_value(stacks: list[dict[str, Any]]) -> float:
    total = sum(int(stack["valueBudget"]) for stack in stacks)
    if total < 1:
        raise ValueError(f"town garrison requestedValue must be positive; stacks={stacks!r}")
    return float(total)


def town_garrison_squad_overlay_doc(entity: dict[str, Any], stacks: list[dict[str, Any]]) -> dict[str, Any]:
    sid = town_garrison_squad_sid(entity)
    requested = int(town_garrison_requested_value(stacks))
    base_units = [{"s": stack["sid"], "v": int(stack["valueBudget"])} for stack in stacks]
    dynamic_units = [stack["sid"] for stack in stacks]
    return {
        "array": [{
            "id": sid,
            "squad": [],
            "useOldSquads": False,
            "rollChance": 0,
            "canBeMainGuard": True,
            "baseSquad": {"units": base_units},
            "dynamicSquad": {"requiredValue": requested, "units": dynamic_units},
            "randomSquad": {"maxValue": requested, "units": list(base_units)},
            "tier": 0,
            "fraction": "",
        }]
    }


def empty_city_prop_random_squad_row(object_id: int) -> dict[str, Any]:
    """Native campaign cities carry an empty propRandomSquads row on the city object id."""
    return {
        "type": 0,
        "id": object_id,
        "sids": [],
        "requestedValue": 0.0,
        "fraction": "",
        "tier": 0,
        "isMainGuard": False,
        "reactionType": 2,
        "customTopUnit": "",
        "weeklyIncrementBonus": 0.0,
        "diplomacyUnitsCountBonus": 0.0,
        "isEscape": True,
        "isAutobatle": True,
        "isFreeDiplomacy": False,
        "isCampaignFreeDiplomacy": False,
        "isCampaignDiplomacy": False,
        "isIgnoreMultiply": False,
        "obstruction": "",
        "customStacks": 0,
    }


def town_garrison_prop_random_squad_row(
    object_id: int,
    entity: dict[str, Any],
    stacks: list[dict[str, Any]],
    *,
    fraction: str = "",
) -> dict[str, Any]:
    """Native-working town defense binding (Thirst 5881 / story campaign cities)."""
    row = empty_city_prop_random_squad_row(object_id)
    row["sids"] = [town_garrison_squad_sid(entity)]
    row["requestedValue"] = town_garrison_requested_value(stacks)
    row["fraction"] = fraction
    row["isIgnoreMultiply"] = False
    return row


def upsert_property_row_by_id(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    object_id = row.get("id")
    if not isinstance(object_id, int):
        raise ValueError(f"property row missing integer id: {row!r}")
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == object_id:
            rows[index] = row
            return
    rows.append(row)


def append_town_ownership_and_garrison_properties(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
    *,
    human_h3_owner: int = 0,
) -> dict[str, Any]:
    """Bind city ownership via propSpawns (City) and defenders via propRandomSquads.

    Evidence: shipped cities never bind ``propSquads`` on city object ids (0 hits).
    Empty towns use empty ``propRandomSquads`` + ``propGrowthUnits``. Non-empty
    defense uses ``propRandomSquads.sids`` + squad overlays. Starting constructed
    buildings are owned by ``h3m_town_construction`` (H3 mask → preset), not
    ``army_buildings_construction``.

    Human-owned towns must keep empty ``propRandomSquads.sids`` even when the H3M
    stores a garrison. Native Thirst / story owned cities are empty; fightable
    city random-squad SIDs are the neutral-capture path. Binding them on the
    human's towns makes the runtime treat starting towns like guarded neutrals
    and blocks player ownership at mission start.
    """
    city_rows = [
        row
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]
    city_ids = [int(row["id"]) for row in city_rows]
    if not city_ids:
        return {
            "townSpawnCount": 0,
            "townGarrisonCount": 0,
            "townGrowthCount": 0,
            "townIds": [],
            "humanTownGarrisonSuppressedCount": 0,
        }

    spawn_rows = list(properties.get("propSpawns") or [])
    random_squad_rows = list(properties.get("propRandomSquads") or [])
    growth_rows = list(properties.get("propGrowthUnits") or [])
    # Strip any prior city-linked propSquads — dead path that masks the native bind.
    squad_rows = [
        row
        for row in (properties.get("propSquads") or [])
        if not (isinstance(row, dict) and isinstance(row.get("id"), int) and int(row["id"]) in set(city_ids))
    ]
    spawn_by_id = {
        int(row["id"]): row
        for row in spawn_rows
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    city_row_by_id = {int(row["id"]): row for row in city_rows}
    town_spawn_count = 0
    town_garrison_count = 0
    human_town_garrison_suppressed = 0
    garrison_squad_sids: list[str] = []
    for object_id in city_ids:
        entity = entities_by_id.get(object_id)
        if entity is None:
            raise ValueError(f"propCities id {object_id} has no source entity for ownership binding")
        owner = entity.get("owner")
        city_row = city_row_by_id[object_id]
        fraction = str(city_row.get("factionSid") or "")
        # Native cities always carry growth so dwelling tiers can stock the garrison.
        upsert_property_row_by_id(
            growth_rows,
            {
                "type": 0,
                "id": object_id,
                "isConstantGrowth": True,
                "countGrowth": 1,
            },
        )
        stacks = mapped_town_garrison_stacks(entity)
        human_owned = isinstance(owner, int) and owner == human_h3_owner
        if stacks and human_owned:
            # Keep the H3 stacks out of propRandomSquads — that lane is neutral capture.
            upsert_property_row_by_id(random_squad_rows, empty_city_prop_random_squad_row(object_id))
            human_town_garrison_suppressed += 1
        elif stacks:
            upsert_property_row_by_id(
                random_squad_rows,
                town_garrison_prop_random_squad_row(object_id, entity, stacks, fraction=fraction),
            )
            garrison_squad_sids.append(town_garrison_squad_sid(entity))
            town_garrison_count += 1
        else:
            upsert_property_row_by_id(random_squad_rows, empty_city_prop_random_squad_row(object_id))

        if not isinstance(owner, int) or owner == H3_NEUTRAL_OWNER:
            # Neutral towns still get growth/garrison rows; skip player ownership spawn.
            continue
        olden_owner = h3m_hero_sid.h3_owner_to_olden_player_index(owner)
        spawn_type = OLDEN_SPAWN_TYPE_HUMAN if owner == human_h3_owner else OLDEN_SPAWN_TYPE_AI
        existing = spawn_by_id.get(object_id)
        if existing is not None and existing.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO:
            raise ValueError(
                f"town object {object_id} already has a Hero propSpawns row; "
                "city ownership must use a distinct city object id"
            )
        city_spawn = {
            "type": 0,
            "id": object_id,
            "owner": olden_owner,
            "spawnType": spawn_type,
            "spawnPointType": OLDEN_SPAWN_POINT_TYPE_CITY,
            "isLocked": True,
        }
        upsert_property_row_by_id(spawn_rows, city_spawn)
        spawn_by_id[object_id] = city_spawn
        town_spawn_count += 1

    prefix = f"{mission_squad_sid_prefix()}_town_garrison_"
    mismatched = [sid for sid in garrison_squad_sids if not sid.startswith(prefix)]
    if mismatched:
        raise ValueError(
            f"town garrison propRandomSquads SIDs must use mission prefix {prefix!r}; "
            f"got {mismatched[:8]} (MISSION_ID={MISSION_ID!r}). "
            "append_town_ownership must run inside single_output_context / set_mission_id."
        )

    properties["propSpawns"] = spawn_rows
    properties["propSquads"] = squad_rows
    properties["propRandomSquads"] = random_squad_rows
    properties["propGrowthUnits"] = growth_rows
    return {
        "townSpawnCount": town_spawn_count,
        "townGarrisonCount": town_garrison_count,
        "townGrowthCount": len(city_ids),
        "townIds": city_ids,
        "townGarrisonSquadSids": garrison_squad_sids,
        "humanTownGarrisonSuppressedCount": human_town_garrison_suppressed,
        "proofBoundary": (
            "propSpawns City ownership + propGrowthUnits match native campaign maps; "
            "human-owned towns keep empty propRandomSquads (H3 garrison is not a "
            "neutral-capture bind); AI/neutral defense uses propRandomSquads.sids + "
            "squad overlays; starting buildings use h3m_town_construction presets "
            "(not army/rich); city propSquads.unitProps is intentionally omitted "
            "(runtime town-capture still user-unvalidated)"
        ),
    }


def h3_unit_logic_rows() -> dict[str, dict[str, Any]]:
    global _UNIT_SQUAD_VALUE_CACHE
    if _UNIT_SQUAD_VALUE_CACHE is not None:
        return dict(_UNIT_SQUAD_VALUE_CACHE)
    rows: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/units/units_logics/") and name.endswith("_l.json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if not isinstance(row, dict):
                    continue
                unit_id = row.get("id")
                if not isinstance(unit_id, str) or not unit_id:
                    continue
                # HoMM3 port units plus neutrals referenced by AB/SoD creature maps.
                if unit_id.startswith("h3_") or unit_id in H3_CREATURE_TYPE_TO_UNIT_SID.values():
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
    return f"{mission_squad_sid_prefix()}_{concrete_monster_unit_sid(entity)}_x{concrete_monster_count(entity)}"


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
    # AVWmon{N}.def is random level N. AVWmonx0.def is Zealot (concrete), not random.
    if animation.startswith("AVWmon") and animation.endswith(".def"):
        raw_level = animation[len("AVWmon") : -len(".def")]
        if raw_level.isdigit():
            level = h3_random_monster_level(entity)
            nominal_count = H3_RANDOM_MONSTER_NOMINAL_COUNT_BY_LEVEL[level]
            return rounded_requested_value(medians[level] * nominal_count)
    count = int(entity.get("count") or 1)
    return rounded_requested_value(medians[1] * max(1, count))


def h3_players_mask_to_sides(players_mask: int | None) -> str:
    """Convert H3M playersMask bitfield (bit0=player1) to zero-based propActions sides CSV."""

    if players_mask is None:
        return ""
    mask = int(players_mask)
    if mask <= 0:
        return ""
    # Mask 255 is a valid all-sides selection; do not collapse to "".
    from campaign_event_ir.audience_encode import encode_prop_actions_sides

    return encode_prop_actions_sides(mask, context="h3_players_mask_to_sides")


def random_artifact_rarity(entity: dict[str, Any]) -> int:
    """Bin HoMM3 random-artifact class → Olden ERarity (shared emit policy)."""
    return rarity_bin.random_artifact_rarity(entity)


def is_adventure_map_garrison_entity(entity: dict[str, Any]) -> bool:
    return entity.get("category") == "garrison" or entity.get("payloadKind") == "garrison"


def adventure_garrison_squad_overlay_sid(entity: dict[str, Any]) -> str:
    source_index = entity.get("sourceIndex")
    if not isinstance(source_index, int):
        raise ValueError(f"adventure garrison missing sourceIndex: {entity.get('sourceKey')}")
    return f"{mission_squad_sid_prefix()}_garrison_{source_index}"


def adventure_garrison_has_nonempty_stacks(entity: dict[str, Any]) -> bool:
    """True when garrisonStacks has at least one fightable H3 slot (not 0xFF/0xFFFF empties)."""
    raw = entity.get("garrisonStacks")
    if not isinstance(raw, list):
        return False
    for stack in raw:
        if not isinstance(stack, dict):
            continue
        creature_type = stack.get("creatureType")
        count = stack.get("count")
        if (
            isinstance(creature_type, int)
            and isinstance(count, int)
            and count > 0
            and creature_type not in H3_CREATURE_EMPTY_TYPES
        ):
            return True
    return False


def mapped_adventure_garrison_stacks(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """Map H3 garrison stacks; empty armies return [] (no invented creatures)."""
    context = f"adventure garrison {entity.get('sourceKey')}"
    raw = entity.get("garrisonStacks")
    if not isinstance(raw, list):
        raise ValueError(f"{context}: missing garrisonStacks list")
    if not adventure_garrison_has_nonempty_stacks(entity):
        return []
    return mapped_map_event_guard_stacks(raw, context=context)


def adventure_garrison_squad_overlay_doc(entity: dict[str, Any], stacks: list[dict[str, Any]]) -> dict[str, Any]:
    sid = adventure_garrison_squad_overlay_sid(entity)
    if not stacks:
        # Empty roadblock garrison: keep overlay SID with zero-value empty roster.
        return {
            "array": [
                {
                    "id": sid,
                    "squad": [],
                    "useOldSquads": False,
                    "rollChance": 0,
                    "canBeMainGuard": True,
                    "baseSquad": {"units": []},
                    "dynamicSquad": {"requiredValue": 0, "units": []},
                    "randomSquad": {"maxValue": 0, "units": []},
                    "tier": 0,
                    "fraction": "",
                }
            ]
        }
    value_stacks = map_event_guard_value_stacks(
        stacks, context=f"garrison overlay {entity.get('sourceKey')}"
    )
    return map_event_guard_squad_overlay_doc(squad_overlay_sid=sid, stacks=value_stacks)


def monster_squad_property_row(object_id: int, entity: dict[str, Any]) -> dict[str, Any]:
    never_flees = bool(entity.get("neverFlees"))
    not_growing = bool(entity.get("notGrowingTeam"))
    character = entity.get("character")
    # HoMM3 character 0 = Compliant (always join). Never emit those as hostile
    # random-squad fallbacks — that turns joinable flavor packs into fights.
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
    # Exact-footprint clones keep the donor SID for property-family binding.
    lookup_sid = str(placement.get("propertyLookupSid") or sid)
    object_id = placement["id"]
    entity = placement["entity"]
    if sid == HOMM3_PATHING_BLOCKER_SID or is_homm3_pathing_visual_sid(str(sid)):
        return
    if lookup_sid == "hero-spawner" or sid == "hero-spawner":
        # Start hero rows are owned by apply_native_start_contract; non-start heroes
        # are bound later by append_placed_hero_properties after all objects merge.
        return
    source_key = str(entity.get("sourceKey") or "")
    map_event_spec = (map_event_specs or {}).get(source_key)
    is_map_event_entity = (
        entity.get("category") == "map_event"
        or entity.get("payloadKind") == "map_event"
        or (isinstance(entity.get("mapEvent"), dict))
    )
    if lookup_sid in MAP_EVENT_MARKER_SIDS and is_map_event_entity and not map_event_spec:
        raise ValueError(
            f"map event marker {source_key} (object {object_id}, sid {sid}) has no map_event_spec binding"
        )
    if map_event_spec and lookup_sid in MAP_EVENT_MARKER_SIDS:
        entity_sid = map_event_spec["entitySid"]
        dialog_sid = map_event_spec["dialogSid"]
        sides = h3_players_mask_to_sides(map_event_spec.get("playersMask"))
        if not sides:
            raise ValueError(
                f"map event {source_key} requires a nonzero playersMask for propActions.sides"
            )
        has_guards = bool(map_event_spec.get("hasGuards"))
        rewards = map_event_spec.get("rewards") or {}
        campaign_script.assert_resource_only_rewards(
            rewards,
            context=f"map event {source_key}",
        )
        remove_after_visit = bool(map_event_spec.get("removeAfterVisit"))
        # Callback recurrence is independent of physical deletion (vanilla c_M2 markers).
        action_repeat = bool(map_event_spec.get("actionRepeat", False))
        computer_eligible = bool(map_event_spec.get("computerActivate", True))
        if has_guards:
            guard_stacks = campaign_script.nonempty_guard_stacks(
                map_event_spec.get("guardStacks"),
                context=f"map event {source_key}",
                allow_empty=True,
            )
            if not guard_stacks:
                # AB/SoD sometimes sets hasGuards with only 0xFFFF empties; demote to
                # unguarded host (same policy as alignment story emit).
                has_guards = False
            else:
                mapped_stacks = mapped_map_event_guard_stacks(
                    guard_stacks,
                    context=f"map event {source_key}",
                )
                squad_entity_sid = str(map_event_spec.get("squadEntitySid") or "")
                if not squad_entity_sid:
                    raise ValueError(f"map event {source_key} hasGuards but missing squadEntitySid")
                squad_overlay_sid = str(map_event_spec.get("squadOverlaySid") or "")
                if not squad_overlay_sid:
                    raise ValueError(f"map event {source_key} hasGuards but missing squadOverlaySid")
                # SpawnsCreator requires propRandomSquads on random-squad hosts (raw_translation
                # rebinds the object SID). Overlay v/requestedValue are squadValue budgets.
                value_stacks = map_event_guard_value_stacks(
                    mapped_stacks,
                    context=f"map event {source_key}",
                )
                properties["propEntities"].append({"type": 0, "id": object_id, "sid": squad_entity_sid})
                properties.setdefault("propSquads", []).append(
                    map_event_guard_prop_squad_row(object_id, stacks=mapped_stacks)
                )
                properties.setdefault("propRandomSquads", []).append(
                    map_event_guard_prop_random_squad_row(
                        object_id,
                        squad_overlay_sid=squad_overlay_sid,
                        stacks=value_stacks,
                    )
                )
                if not computer_eligible:
                    properties.setdefault("propAiIntetations", []).append(
                        {"type": 0, "id": object_id, "aiIgnore": True}
                    )
                # Guarded pre-battle Dialog must be Actions Before (interrupts combat init).
                # QuestScript SquadInteraction cannot pause battle start (Unfrozen mapmaking guide).
                # repeat=True so flee-and-retry still shows the message until SquadKill cleanup.
                if bool(map_event_spec.get("hasMessage")):
                    properties["propActionsBefore"].append({
                        "type": 0,
                        "id": object_id,
                        "repeat": True,
                        "sides": sides,
                        "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
                    })
                # Post-combat GiveRes / DeleteEntity stay on QuestScript SquadKill.
                properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
                return
        properties["propEntities"].append({"type": 0, "id": object_id, "sid": entity_sid})
        # Human-only unguarded markers still encode the full H3 playersMask into sides;
        # without aiIgnore, AI sides in that CSV can consume Dialog and stall the turn.
        if not computer_eligible:
            properties.setdefault("propAiIntetations", []).append(
                {"type": 0, "id": object_id, "aiIgnore": True}
            )
        properties["propActionsBefore"].append({
            "type": 0,
            "id": object_id,
            "repeat": action_repeat,
            "sides": sides,
            "actions": [{"comment": "", "a": "Dialog", "p": [dialog_sid]}],
        })
        after_actions: list[dict[str, Any]] = []
        # Only disposable event hosts may DeleteEntity themselves. Persistent rebound
        # hosts (Guardhouse dwelling, colocated hero-spawner) must never be deleted.
        host_lifetime = str(map_event_spec.get("hostLifetime") or "disposable_marker")
        if remove_after_visit and host_lifetime not in {
            "persistent_object",
            "colocated_hero_host",
        }:
            after_actions.append({"comment": "", "a": "DeleteEntity", "p": [entity_sid]})
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
    if lookup_sid == "homm3_seer_hut":
        # Seer QuestScript listens to ObjectInteractionBefore on propEntities.sid
        # (PropertyEntity.sid), not objects[].sid / event-bank sidConfig.
        # Dialog/FSM live in chunk-3 QuestScript; local propActions stay empty.
        properties["propEntities"].append({
            "type": 0,
            "id": object_id,
            "sid": deterministic_entity_sid(lookup_sid, object_id),
        })
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
        return
    faction_sid = LANDON_CITY_PROPERTY_SIDS.get(lookup_sid)
    if faction_sid is not None:
        town_display_name = str(entity.get("name") or "").strip()
        if not town_display_name:
            raise ValueError(
                f"town {entity.get('sourceKey') or object_id} (sid {lookup_sid}) reached "
                "PropCity emit without a name; unnamed H3M towns must be named from the "
                "authentic HoMM3 pool via h3_town_name_pool.assign_default_town_names "
                "before layer emit (build_layered_objects). Coordinate placeholders are "
                "forbidden."
            )
        # PropCity has no owner/garrison/building-mask fields (Hex.Map.PropCity).
        # Ownership → propSpawns (City); defenders → propRandomSquads.sids via
        # append_town_ownership_and_garrison_properties after all cities merge.
        properties["propCities"].append({
            "type": 0,
            "id": object_id,
            "isDefined": True,
            "factionSid": faction_sid,
            "spawnHero": False,
            "customCityName": homecoming_lang.custom_city_name_sid(
                town_display_name,
                mission_id=MISSION_ID,
            ),
            "buildingsBanSid": (
                HOMECOMING_BUILDINGS_BAN_SID
                if MISSION_ID == "homecoming"
                else "default_buildings_ban"
            ),
            "buildingsConstructionSid": (
                HOMECOMING_BUILDINGS_CONSTRUCTION_SID
                if MISSION_ID == "homecoming"
                else "poor_buildings_construction"
            ),
            "buildingsSettingsSid": HOMECOMING_BUILDINGS_SETTINGS_SID,
        })
        return
    if lookup_sid == "random-squad":
        if is_adventure_map_garrison_entity(entity):
            stacks = mapped_adventure_garrison_stacks(entity)
            overlay_sid = adventure_garrison_squad_overlay_sid(entity)
            if not stacks:
                # Empty H3 garrison roadblock: no invented army; keep host + empty roster.
                properties.setdefault("propSquads", []).append(
                    {
                        "type": 0,
                        "id": object_id,
                        "isMainGuard": False,
                        "isStartBattleImmediately": False,
                        "reactionType": 2,
                        "weeklyIncrementBonus": 0.0,
                        "unitProps": [],
                    }
                )
                empty_row = empty_city_prop_random_squad_row(object_id)
                empty_row["sids"] = [overlay_sid]
                empty_row["requestedValue"] = 0.0
                empty_row["customTopUnit"] = ""
                properties.setdefault("propRandomSquads", []).append(empty_row)
                return
            value_stacks = map_event_guard_value_stacks(
                stacks, context=f"garrison emit {entity.get('sourceKey')}"
            )
            properties.setdefault("propSquads", []).append(
                map_event_guard_prop_squad_row(object_id, stacks=stacks)
            )
            properties.setdefault("propRandomSquads", []).append(
                map_event_guard_prop_random_squad_row(
                    object_id,
                    squad_overlay_sid=overlay_sid,
                    stacks=value_stacks,
                )
            )
            return
        properties["propRandomSquads"].append(monster_squad_property_row(object_id, entity))
        # H3 custom monster visit text → OE propActionsBefore Dialog on the squad
        # host (native c_M1 free-join / Fun_and_Graves shape). Not SquadInteraction.
        interact_message = campaign_script.monster_interact_message(entity)
        if interact_message is not None:
            dialog_sid = campaign_script.monster_message_dialog_sid(MISSION_ID, object_id)
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
    if lookup_sid == "random-item":
        properties["propRandomItems"].append({
            "type": 0,
            "id": object_id,
            "rarity": random_artifact_rarity(entity),
        })
        return
    if lookup_sid == HOMM3_FLOTSAM_PICKUP_SID:
        properties["propRewardParams"].append({
            "type": 0,
            "id": object_id,
            "parameters": [],
            "flotsamOneShotPolicy": "h3_flotsam_random_basic_resource",
        })
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
        return
    if lookup_sid == META_RANDOM_RES_SID:
        # Stale substitution maps may still emit Meta random-res. Expand at emit
        # time (same object-id bucket as install rewrite) so artifacts never ship
        # Meta groups that hang Loader on Steadwick-scale maps.
        concrete = concrete_resource_sid_for_object_id(object_id)
        properties["propResParams"].append(
            {"type": 0, "id": object_id, "value": RESOURCE_VALUES[concrete]}
        )
        return
    if lookup_sid in RESOURCE_VALUES:
        properties["propResParams"].append({"type": 0, "id": object_id, "value": RESOURCE_VALUES[lookup_sid]})
    if lookup_sid in REWARD_PARAM_SIDS:
        properties["propRewardParams"].append({"type": 0, "id": object_id, "parameters": []})
    if lookup_sid in VARIANT_SIDS:
        properties["propVariants"].append({"type": 0, "id": object_id, "selectedVar": -1, "typeVariant": 0, "fraction": 0, "unitVersion": 0})
    if lookup_sid in ENTITY_SIDS:
        properties["propEntities"].append({"type": 0, "id": object_id, "sid": deterministic_entity_sid(lookup_sid, object_id)})
    if lookup_sid in NO_COMBINE_GEOMETRY_SIDS:
        properties["propNoCombineGeometries"].append({"type": 0, "id": object_id, "isNoCombineGeometry": True})
    if lookup_sid in AI_IGNORE_SIDS:
        properties["propAiIntetactions"].append({"type": 0, "id": object_id, "aiIgnore": True})
    if lookup_sid in ACTION_BEFORE_SIDS:
        properties["propActionsBefore"].append({"type": 0, "id": object_id, "repeat": False, "sides": "", "actions": []})
    if lookup_sid in ACTION_AFTER_SIDS:
        properties["propActionsAfter"].append({"type": 0, "id": object_id, "repeat": False, "sides": "", "actions": []})
    if lookup_sid in ACTIVATION_SIDS:
        properties["propActivations"].append({"type": 0, "id": object_id, "isActive": True})
    if lookup_sid in PORTAL_SIDS:
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
        lookup_sid = str(placement.get("propertyLookupSid") or placement["replacementSid"])
        if lookup_sid in PORTAL_SIDS:
            by_sid[lookup_sid].append(int(placement["id"]))
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

    Only families outside SUPPORTED_LIVE_PROPERTY_FAMILIES are recorded. Whitelisted
    SIDs (e.g. random-squad) must list every emitter-handled family spelling in that
    set so discovery cannot false-defer them. Non-whitelisted SIDs that only bind
    supported scenery families (propEntities / propNoCombineGeometries) stay
    emit-eligible; SIDs that still bind truly unsupported families remain deferred.
    """
    required: dict[str, Counter] = defaultdict(Counter)
    for map_path in poc.OLDEN_MAPS_DIR.rglob("*.map"):
        if map_path.name.startswith("h3_roe_castle_"):
            continue
        if map_path.name.startswith("editor_ab_"):
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
    emit_policy: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    import emit_policy as emit_policy_mod

    policy = emit_policy if emit_policy is not None else emit_policy_mod.APPROACH_CELL_EMIT_POLICY
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
        # Fail closed for SIDs that native maps bind special props to unless the
        # SID is live-whitelisted AND every discovered family is supported.
        # Whitelist membership alone is not enough when discovery finds a family
        # spelling the emitter does not claim (historically deferred random-squad
        # via propSquads / propAiIntetations vs a typo'd allowlist entry).
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
        property_lookup_sid = str(replacement_sid)
        meta = native_object_configs[str(replacement_sid)].get(exact_fp.META_KEY)
        if isinstance(meta, dict) and isinstance(meta.get("donorSid"), str):
            property_lookup_sid = str(meta["donorSid"])
        elif _EXACT_FOOTPRINT_REGISTRY is not None:
            entry = _EXACT_FOOTPRINT_REGISTRY.by_source_index.get(source_index)
            if entry is not None and entry.action == "catalog_match":
                property_lookup_sid = entry.donor_sid
        placements.append({
            "replacementSid": str(replacement_sid),
            "propertyLookupSid": property_lookup_sid,
            "id": source_index,
            "entity": entity,
            "ruleName": rule_name,
            "lossiness": lossiness,
            "node": node,
            "rotation": rotation,
            "level": float(entity.get("level") or 0),
            "defaultNode": default_node,
        })

    resource_mine_clearance = reanchor_resource_gate_rings_clear_of_mines(
        placements,
        native_object_configs,
        allow_pickup_range_fallback=bool(
            getattr(policy, "pickup_range_fallback_when_strict_fails", False)
        ),
        reserved_cells=key_gate_reserved_cells(
            [entity for entity in surface_entities if is_in_source_bounds(entity)]
        ),
    )
    for placement in placements:
        evidence = placement.get("mineClearanceEvidence")
        if not isinstance(evidence, dict):
            continue
        if int(placement.get("node") or -1) == int(placement.get("defaultNode") or -2):
            continue
        source_anchor_node_changed_count += 1
        source_anchor_node_alignment_counts[str(evidence.get("decision") or evidence.get("reason"))] += 1
        entity = placement.get("entity") or {}
        if len(source_anchor_node_alignment_examples) < 40:
            source_anchor_node_alignment_examples.append({
                "sourceIndex": placement.get("id"),
                "sourceKey": entity.get("sourceKey"),
                "replacementSid": str(placement.get("replacementSid")),
                "templateObjectId": entity.get("templateObjectId"),
                "templateAnimation": entity.get("templateAnimation"),
                "originalNode": placement.get("defaultNode"),
                **evidence,
            })

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

    if policy.apply_functional_emit_reservation:
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
    else:
        functional_emit_reservation_stats = {
            "policy": "disabled_raw_translation_emit_policy_pack",
            "status": "disabled",
            "functionalPlacementCount": 0,
            "sceneryKeptCount": len(placements),
            "sceneryOmittedCount": 0,
            "sceneryOmittedSidHistogram": {},
            "emitPolicyPack": policy.name,
        }

    if policy.suppress_exact_anchor_scenery:
        source_anchor_composition = suppress_exact_anchor_scenery_collisions(placements)
    else:
        source_anchor_composition = {
            "policy": "disabled_raw_translation_emit_policy_pack",
            "status": "disabled",
            "suppressedCount": 0,
            "emitPolicyPack": policy.name,
        }
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
            "policy": FOOTPRINT_ALIGNMENT_POLICY,
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
        raise ValueError(
            "approach_cell surface_emit forbids enable_footprint_alignment=True "
            "(footprint pad/gap-fill spine is banned)"
        )
    grouped = defaultdict(lambda: {"ids": [], "nodes": [], "rotations": [], "levels": []})
    replacement_counts = Counter()
    rule_counts = Counter()
    lossy_counts = Counter()
    for placement in placements:
        replacement_sid = str(placement["replacementSid"])
        object_id = int(placement["id"])
        if replacement_sid == META_RANDOM_RES_SID:
            replacement_sid = concrete_resource_sid_for_object_id(object_id)
            placement["replacementSid"] = replacement_sid
            # Keep property lookup on the concrete sid so propResParams emit, not Meta.
            placement["propertyLookupSid"] = replacement_sid
        group = grouped[replacement_sid]
        group["ids"].append(object_id)
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
        "resourceMineClearance": resource_mine_clearance,
        "functionalEmitReservation": {
            key: value
            for key, value in functional_emit_reservation_stats.items()
            if key not in {"reservedNodes"}
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
    *,
    id_base: int | None = None,
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
            # Scenery / infrastructure: full OCC covers H3 block cells for gap-fill.
            # Functional keepers: only OCC ∩ (H3 visit ∪ H3 non-visitable block) counts —
            # keep-donor GATE-align often places native OCC outside the H3 footprint and
            # must not suppress mountains/trees that truly block those cells.
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

    # Gap-fill ONLY true HoMM3 non-visitable block cells that nothing occupied yet.
    # Do not exempt general Olden GATE / landon approach cells: GATE rings invent
    # markers on H3-blocked mountain cells, and skipping them left permanent empty
    # holes. Scorched-earth subterranean portal is the explicit exception — its
    # full GATE ring must stay approachable, so those markers are not sealed.
    # H3 visit cells are not in required_block_nodes, so interact tiles stay open.
    # Never invent blockers on H3-open corridor cells to paper over Olden diagonal
    # squeeze — that planted thousands of phantom mountains and sealed gold/chest
    # approaches while the source map stayed open.
    scorched_portal_gates = subterranean_portal_gate_nodes(objects, native_object_configs)
    gap_nodes = set(required_block_nodes - occupied_nodes) - scorched_portal_gates
    gap_nodes_sorted = sorted(gap_nodes)

    # Prefer DEF-family 1x1 blocking scenery for residual cells (snow/dead/green/dirt).
    # Fall back to dirt mountain (exact-footprint) or pathing blocker (legacy).
    import build_homecoming_entity_substitution_map as sub_mod

    default_gap_sid = (
        HOMM3_PATHING_GAP_FILL_VISIBLE_SID
        if _EXACT_FOOTPRINT_REGISTRY is not None
        else HOMM3_PATHING_BLOCKER_SID
    )
    valid_gap_ids = set(native_object_configs)
    node_to_gap_sid: dict[int, str] = {}
    for entity in surface_entities:
        entity_blocks = entity_nonvisitable_block_nodes(entity)
        family_sid = sub_mod.gap_fill_blocker_sid_for_animation(
            entity.get("templateAnimation") if isinstance(entity, dict) else None,
            valid_gap_ids,
        )
        chosen = family_sid if isinstance(family_sid, str) else default_gap_sid
        for node in entity_blocks:
            if node not in gap_nodes:
                continue
            # First writer wins; entities are processed in source order.
            node_to_gap_sid.setdefault(node, chosen)
    for node in gap_nodes_sorted:
        node_to_gap_sid.setdefault(node, default_gap_sid)

    sid_to_nodes: dict[str, list[int]] = defaultdict(list)
    for node in gap_nodes_sorted:
        sid_to_nodes[node_to_gap_sid[node]].append(node)

    next_blocker_id = HOMM3_PATHING_BLOCKER_ID_BASE if id_base is None else int(id_base)
    blocker_examples: list[dict[str, Any]] = []
    sid_histogram: dict[str, int] = {}
    for gap_fill_sid, sid_nodes in sorted(sid_to_nodes.items()):
        if gap_fill_sid not in native_object_configs:
            raise ValueError(f"missing ObjectConfig for pathability gap-fill SID {gap_fill_sid!r}")
        gap_fill_config = native_object_configs[gap_fill_sid]
        gap_nodes_list = gap_fill_config.get("nodes")
        if gap_fill_config.get("sizeX") != 1 or gap_fill_config.get("sizeZ") != 1:
            raise ValueError(f"pathability gap-fill SID must be 1x1: {gap_fill_sid}")
        if not isinstance(gap_nodes_list, list) or gap_nodes_list != [1]:
            raise ValueError(f"pathability gap-fill SID must occupy its single cell: {gap_fill_sid}")
        ids: list[int] = []
        nodes: list[int] = []
        rotations: list[int] = []
        levels: list[float] = []
        for node in sid_nodes:
            ids.append(next_blocker_id)
            nodes.append(node)
            rotations.append(0)
            levels.append(0.0)
            if len(blocker_examples) < 20:
                blocker_examples.append({
                    "id": next_blocker_id,
                    "node": node,
                    "sid": gap_fill_sid,
                    "x": node % OLDEN_WIDTH,
                    "y": node // OLDEN_WIDTH,
                })
            next_blocker_id += 1
        if ids:
            append_object_instances(objects, gap_fill_sid, ids, nodes, rotations, levels)
        sid_histogram[gap_fill_sid] = len(ids)

    return {
        "status": HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": HOMM3_PATHABILITY_ALIGNMENT_POLICY,
        "phase": "gap_fill_after_boat_and_decorations",
        "requiredH3NonvisitableBlockNodeCount": len(required_block_nodes),
        "occupiedNodeCountBeforeGapFill": len(occupied_nodes),
        "gapFillBlockerCount": len(gap_nodes_sorted),
        "gapFillBlockerExamples": blocker_examples,
        "gapFillSidHistogram": sid_histogram,
        "gapFillDiagonalSqueezeSealCount": 0,
        "gapFillDiagonalSqueezeSealPolicy": "disabled_never_invent_blockers_on_h3_open_cells",
        "gapFillSkippedGateApproachCount": 0,
        "gapFillSkippedGateApproachPolicy": "disabled_h3_block_authority_over_olden_gate_markers",
        "pathingBlockerSid": default_gap_sid,
        "pathingBlockerIdBase": HOMM3_PATHING_BLOCKER_ID_BASE if id_base is None else int(id_base),
        "proofBoundary": (
            "source/static/generated-artifact pathability gap-fill with DEF-family "
            "1x1 blocking scenery when available; native runtime pathfinder remains user-unvalidated"
        ),
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


def add_underground_pond_scenery_objects(
    objects: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    valid_ids: set[str],
) -> dict[str, Any]:
    """Emit decorative pond scenery on converted underground-ocean anchors."""
    occupied = occupied_object_nodes(objects)
    emitted: list[dict[str, Any]] = []
    skipped_occupied = 0
    next_id = UNDERGROUND_POND_SCENERY_ID_BASE
    for placement in placements:
        if not isinstance(placement, dict):
            raise ValueError(f"underground pond placement must be an object, got {type(placement)!r}")
        sid = placement.get("sid")
        node = placement.get("node")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"underground pond placement missing sid: {placement!r}")
        if sid not in valid_ids:
            raise ValueError(f"underground pond scenery SID {sid!r} is not in the core catalog allowlist")
        if not isinstance(node, int):
            raise ValueError(f"underground pond placement missing node: {placement!r}")
        if node in occupied:
            skipped_occupied += 1
            continue
        append_object_instance(objects, sid, next_id, node)
        occupied.add(node)
        emitted.append(
            {
                "objectId": next_id,
                "sid": sid,
                "node": node,
                "sourceX": placement.get("sourceX"),
                "sourceY": placement.get("sourceY"),
                "componentTileCount": placement.get("componentTileCount"),
            }
        )
        next_id += 1
    return {
        "status": "generated_runtime_unvalidated",
        "policy": "underground_ocean_to_pond_scenery_unless_preserved",
        "idBase": UNDERGROUND_POND_SCENERY_ID_BASE,
        "requestedPlacementCount": len(placements),
        "emittedCount": len(emitted),
        "skippedOccupiedCount": skipped_occupied,
        "emitted": emitted,
    }


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


def apply_native_start_contract(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    *,
    start_object_id: int | None = None,
    human_h3_owner: int = 0,
    human_hero_sid: str | None = None,
) -> int:
    """Bind the player start hero-spawner. Non-start heroes use append_placed_hero_properties.

    When ``start_object_id`` is provided (profile startHeroContract sourceIndex), use that
    exact hero-spawner. Multi-hero maps (e.g. Griffin Cliff) emit AI hero-spawners with
    lower ids; picking the first surface spawner would bind the wrong start.
    """

    hero_ids = find_object_ids(objects, "hero-spawner")
    if not hero_ids:
        raise ValueError("expected at least one hero-spawner object for native start contract")
    if start_object_id is not None:
        if start_object_id not in hero_ids:
            raise ValueError(
                f"start_object_id {start_object_id} is not an emitted hero-spawner; "
                f"available={sorted(hero_ids)[:20]}"
            )
        start_id = start_object_id
    else:
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
    hero_sid = str(human_hero_sid or START_HERO_SID).strip()
    if not hero_sid:
        raise ValueError("human_hero_sid must be a non-empty hero SID")
    start_spawn = {
        "type": 0,
        "id": start_id,
        "owner": h3m_hero_sid.h3_owner_to_olden_player_index(human_h3_owner),
        "spawnType": OLDEN_SPAWN_TYPE_HUMAN,
        "spawnPointType": OLDEN_SPAWN_POINT_TYPE_HERO,
        "isLocked": False,
    }
    # Preserve City propSpawns (and any other non-start rows) already bound on map objects.
    preserved = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict) and row.get("id") != start_id
    ]
    properties["propSpawns"] = [start_spawn, *preserved]
    existing_heroes = [
        row for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict) and row.get("id") != start_id
    ]
    properties["propHeroes"] = [
        {"type": 0, "id": start_id, "isDefined": True, "heroSid": hero_sid},
        *existing_heroes,
    ]
    return start_id


def collect_non_neutral_h3_owners(entities: list[dict[str, Any]]) -> list[int]:
    """All HoMM3 player owners present on the scenario (excludes neutral 255)."""
    owners = sorted({
        int(entity["owner"])
        for entity in entities
        if isinstance(entity.get("owner"), int) and int(entity["owner"]) != H3_NEUTRAL_OWNER
    })
    if not owners:
        raise ValueError("scenario has no non-neutral HoMM3 player owners")
    return owners


def bind_orphan_ai_owners_to_neutral_towns(
    properties: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
    *,
    human_olden_owner: int,
) -> dict[str, Any]:
    """Give hero-only AI sides a City propSpawn from the nearest unbound neutral town.

    AB/SoD maps often place AI heroes beside fully neutral towns (Mutare / Dragon's Blood).
    StoryHub Bot binding refuses hero-only AI owners, so claim one unused neutral city per
    orphan AI owner (deterministic nearest by source Manhattan distance).
    """
    spawn_rows = list(properties.get("propSpawns") or [])
    city_ids = {
        int(row["id"])
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    if not city_ids:
        return {"boundCount": 0, "bindings": [], "policy": "no_cities"}

    owners_with_city: set[int] = set()
    owners_with_hero: dict[int, list[int]] = defaultdict(list)
    claimed_city_ids: set[int] = set()
    for row in spawn_rows:
        if not isinstance(row, dict):
            continue
        owner = row.get("owner")
        object_id = row.get("id")
        if not isinstance(owner, int) or not isinstance(object_id, int):
            continue
        if row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_CITY:
            owners_with_city.add(owner)
            claimed_city_ids.add(object_id)
        elif row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO:
            owners_with_hero[owner].append(object_id)

    orphan_owners = sorted(
        owner
        for owner in owners_with_hero
        if owner != human_olden_owner and owner not in owners_with_city
    )
    if not orphan_owners:
        return {"boundCount": 0, "bindings": [], "policy": "no_orphan_ai_owners"}

    available_cities: list[tuple[int, int, int]] = []
    for object_id in sorted(city_ids):
        if object_id in claimed_city_ids:
            continue
        entity = entities_by_id.get(object_id)
        if entity is None:
            continue
        owner = entity.get("owner")
        if isinstance(owner, int) and owner != H3_NEUTRAL_OWNER:
            continue
        x = int(entity.get("sourceX") if entity.get("sourceX") is not None else entity.get("x") or 0)
        y = int(entity.get("sourceY") if entity.get("sourceY") is not None else entity.get("y") or 0)
        available_cities.append((object_id, x, y))
    if len(available_cities) < len(orphan_owners):
        raise ValueError(
            f"orphan AI owners {orphan_owners} need City propSpawns but only "
            f"{len(available_cities)} unbound neutral towns remain"
        )

    bindings: list[dict[str, Any]] = []
    used_cities: set[int] = set()
    for olden_owner in orphan_owners:
        hero_ids = sorted(owners_with_hero[olden_owner])
        # Anchor distance on the lowest hero object id for this owner.
        anchor = entities_by_id.get(hero_ids[0], {})
        ax = int(anchor.get("sourceX") if anchor.get("sourceX") is not None else anchor.get("x") or 0)
        ay = int(anchor.get("sourceY") if anchor.get("sourceY") is not None else anchor.get("y") or 0)
        candidates = [
            (abs(cx - ax) + abs(cy - ay), object_id, cx, cy)
            for object_id, cx, cy in available_cities
            if object_id not in used_cities
        ]
        candidates.sort()
        _dist, city_id, cx, cy = candidates[0]
        used_cities.add(city_id)
        city_spawn = {
            "type": 0,
            "id": city_id,
            "owner": olden_owner,
            "spawnType": OLDEN_SPAWN_TYPE_AI,
            "spawnPointType": OLDEN_SPAWN_POINT_TYPE_CITY,
            "isLocked": True,
        }
        upsert_property_row_by_id(spawn_rows, city_spawn)
        bindings.append(
            {
                "oldenOwner": olden_owner,
                "heroObjectIds": hero_ids,
                "cityObjectId": city_id,
                "citySourceXY": [cx, cy],
                "manhattanDistance": _dist,
            }
        )
    properties["propSpawns"] = spawn_rows
    return {
        "boundCount": len(bindings),
        "bindings": bindings,
        "policy": "nearest_unbound_neutral_town_to_orphan_ai_hero",
        "proofBoundary": (
            "generated_artifact; AI capital assignment for neutral-town AB/SoD maps is "
            "lossy vs H3 capture-on-visit and remains runtime-unvalidated"
        ),
    }


def faction_sid_from_hero_sid(hero_sid: str) -> str:
    if not isinstance(hero_sid, str) or "_hero_" not in hero_sid:
        raise ValueError(f"cannot derive faction from heroSid={hero_sid!r}")
    return hero_sid.rsplit("_hero_", 1)[0]


def town_faction_counts_for_h3_owner(
    entities: list[dict[str, Any]], h3_owner: int
) -> Counter[str]:
    """Per-faction town counts for h3_owner, from HoMM3 town DEF animation prefix."""
    counts: Counter[str] = Counter()
    for entity in entities:
        if int(entity.get("owner") or -1) != h3_owner:
            continue
        if entity.get("category") != "town" and entity.get("payloadKind") != "town":
            continue
        # HoMM3 town DEF prefixes (RoE): AVCcast / AVCdung / AVCinft / AVCramp /
        # AVCtowr / AVCnecr / AVCstro(+AVCstrx) / AVCfort(+AVCftrt/AVCftrx) / AVCelem.
        # SoD variants often use *x* stems (AVCcasx / AVCnecx) for the same factions.
        faction = h3_town_name_pool.town_faction_sid_from_animation(entity.get("templateAnimation"))
        if faction:
            counts[faction] += 1
    return counts


def town_faction_sids_for_h3_owner(entities: list[dict[str, Any]], h3_owner: int) -> list[str]:
    """Faction SIDs of towns owned by h3_owner, from HoMM3 town DEF animation prefix."""
    return list(town_faction_counts_for_h3_owner(entities, h3_owner).keys())


# Homecoming H3 AI owner 2 owns Castle×3 surface towns + Terraneus (Dungeon city) + Xyron
# (Inferno heroType 57 at 1:34:36). StoryHub StartSide.fractionSid would paint every bound
# city as that Bot faction, so Terraneus must split onto its own Olden owner.
# Owner 4 Bot fraction follows Terraneus city faction (Dungeon). Campaign Bot
# campaignSpawns.heroSid is always empty natively; Homm3CampaignSpawnParityHook fills
# Xyron from propHeroes so Inferno-hero-under-Dungeon-Bot is legal without painting
# Terraneus as Inferno.
HOMECOMING_TERRANEUS_OBJECT_ID = 1454
HOMECOMING_XYRON_OBJECT_ID = 1464
HOMECOMING_CASTLE_AI_OLDEN_OWNER = 3  # H3 owner 2 default mapping
HOMECOMING_TERRANEUS_AI_OLDEN_OWNER = 4  # synthetic split owner for Terraneus + Xyron
HOMECOMING_DUNGEON_AI_OLDEN_OWNER = HOMECOMING_TERRANEUS_AI_OLDEN_OWNER  # compat alias
HOMECOMING_TERRANEUS_BOT_FACTION_SID = "homm3_dungeon"
HOMECOMING_AI_OWNER_FACTION_SPLIT_REMAPS: dict[int, int] = {
    HOMECOMING_TERRANEUS_OBJECT_ID: HOMECOMING_TERRANEUS_AI_OLDEN_OWNER,
    HOMECOMING_XYRON_OBJECT_ID: HOMECOMING_TERRANEUS_AI_OLDEN_OWNER,
}


def ai_faction_sid_for_owner(
    entities: list[dict[str, Any]],
    h3_owner: int,
    hero_sid: str,
) -> str:
    """AI meta.spawns factionSid from owned towns (single-faction only).

    Olden applies StartSide.fractionSid to bound cities (native owned towns never
    mismatch Bot faction). Mixed town factions under one H3 owner must be split onto
    distinct Olden owners before spawn emit — majority guessing would paint the
    minority town wrong (Homecoming Terraneus Dungeon under Castle Bot).
    """
    counts = town_faction_counts_for_h3_owner(entities, h3_owner)
    if not counts:
        return faction_sid_from_hero_sid(hero_sid)
    if len(counts) > 1:
        raise ValueError(
            f"AI H3 owner {h3_owner} has mixed town factions {dict(counts)}; "
            f"apply explicit Olden owner split before meta.spawns "
            f"(refuse majority guess; hero={hero_sid!r})"
        )
    return next(iter(counts))


def plan_ai_multi_faction_city_owner_split(
    properties: dict[str, Any],
    *,
    human_olden_owner: int,
    protect_city_ids: set[int] | frozenset[int] | None = None,
) -> dict[int, int]:
    """Plan city remaps so each Olden owner has exactly one city factionSid.

    StoryHub StartSide.fractionSid paints every bound city as that Bot's faction, so
    mixed-faction H3 AI players (common in RoE Liberation) must become multiple Olden
    Bot sides. Majority faction (city count, then factionSid) keeps the original owner;
    minority-faction cities move to the lowest free Olden owner in 1..8. Heroes are not
    remapped here — city binding is the Session.Loader failure mode.

    ``protect_city_ids`` (campaign-granted human start town) must stay on their current
    owner: that city's faction becomes the keep faction so the grant town is never
    remapped away from the human.
    """
    protected = {int(x) for x in (protect_city_ids or ())}
    spawn_rows = properties.get("propSpawns")
    if not isinstance(spawn_rows, list):
        raise ValueError("propSpawns must be a list before AI multi-faction city split")
    city_faction_by_id = {
        int(row["id"]): str(row.get("factionSid") or "")
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    cities_by_owner: dict[int, list[tuple[int, str]]] = {}
    used_owners: set[int] = set()
    for row in spawn_rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int):
            continue
        owner = row.get("owner")
        if not isinstance(owner, int):
            continue
        used_owners.add(owner)
        if row.get("spawnPointType") != OLDEN_SPAWN_POINT_TYPE_CITY:
            continue
        # Include the human owner: StoryHub paints every bound city as the Player
        # fractionSid. Mixed-faction human towns (Steadwick Tower + Castle starts)
        # must split the minority onto a Bot owner or Loader/city init can NRE.
        faction = city_faction_by_id.get(int(row["id"]), "")
        if not faction:
            raise ValueError(
                f"city propSpawn {int(row['id'])} owner {owner} missing propCities.factionSid"
            )
        cities_by_owner.setdefault(owner, []).append((int(row["id"]), faction))

    remaps: dict[int, int] = {}
    free_owners = [
        owner
        for owner in range(1, 9)
        if owner not in used_owners and owner != human_olden_owner
    ]
    free_index = 0
    for owner, cities in sorted(cities_by_owner.items()):
        factions = sorted({faction for _, faction in cities})
        if len(factions) <= 1:
            continue
        counts: Counter[str] = Counter(faction for _, faction in cities)
        protected_here = [(cid, fac) for cid, fac in cities if cid in protected]
        if protected_here:
            protected_factions = sorted({fac for _, fac in protected_here})
            if len(protected_factions) != 1:
                raise ValueError(
                    f"owner {owner} protect_city_ids span multiple factions "
                    f"{protected_factions}; cannot keep campaign-granted start"
                )
            keep_faction = protected_factions[0]
        else:
            # Deterministic majority: highest count, then lexicographic factionSid.
            keep_faction = sorted(counts.keys(), key=lambda sid: (-counts[sid], sid))[0]
        minority = [sid for sid in factions if sid != keep_faction]
        for faction in minority:
            if free_index >= len(free_owners):
                raise ValueError(
                    f"AI multi-faction city split exhausted Olden owners 1..8; "
                    f"owner {owner} still needs faction {faction!r} "
                    f"(keep={keep_faction!r} counts={dict(counts)})"
                )
            new_owner = free_owners[free_index]
            free_index += 1
            used_owners.add(new_owner)
            for object_id, city_faction in cities:
                if city_faction == faction:
                    if object_id in protected:
                        raise ValueError(
                            f"refuse remapping protected campaign-granted city {object_id} "
                            f"from owner {owner} to {new_owner}"
                        )
                    remaps[object_id] = new_owner
    return remaps


def apply_explicit_ai_owner_faction_split(
    properties: dict[str, Any],
    *,
    remaps: dict[int, int],
) -> dict[str, Any]:
    """Remap propSpawns.owner for explicit object ids (fail-closed if any id missing)."""
    if not remaps:
        return {
            "policy": "explicit_object_id_olden_owner_remap",
            "remappedObjectIds": [],
            "owners": {},
        }
    spawn_rows = properties.get("propSpawns")
    if not isinstance(spawn_rows, list):
        raise ValueError("propSpawns must be a list before AI owner faction split")
    by_id = {
        int(row["id"]): row
        for row in spawn_rows
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    missing = sorted(object_id for object_id in remaps if object_id not in by_id)
    if missing:
        raise ValueError(
            f"AI owner faction split remaps missing propSpawns rows for object ids {missing}"
        )
    owners_before_after: dict[str, dict[str, int]] = {}
    for object_id, new_owner in sorted(remaps.items()):
        if not isinstance(new_owner, int) or new_owner < 1 or new_owner > 8:
            raise ValueError(f"split olden owner must be 1..8, got {new_owner!r} for id {object_id}")
        row = by_id[object_id]
        before = row.get("owner")
        if not isinstance(before, int):
            raise ValueError(f"propSpawns {object_id} owner must be int before split; got {before!r}")
        row["owner"] = new_owner
        # Minority cities peeled off a mixed-faction human (or any) side become Bot towns.
        # Leaving spawnType=HUMAN creates a second Player propSpawn and breaks StoryHub.
        row["spawnType"] = OLDEN_SPAWN_TYPE_AI
        owners_before_after[str(object_id)] = {"before": before, "after": new_owner}
    return {
        "policy": "explicit_object_id_olden_owner_remap",
        "remappedObjectIds": sorted(remaps),
        "owners": owners_before_after,
        "proofBoundary": (
            "source/static remap only; StoryHub Bot sides must declare matching spawns owners; "
            "owner 4 Bot fractionSid follows Terraneus city (homm3_dungeon); Xyron spawns via "
            "propHeroes campaign parity hook; runtime Xyron visibility remains user-unvalidated"
        ),
    }


def renumber_map_owners_to_native_compact(
    properties: dict[str, Any],
    *,
    human_olden_owner: int,
) -> dict[str, Any]:
    """Renumber map owner indices to the native compact scheme (human=1, AI=2..N).

    Every stock Olden map and every runtime-proven authored scenario (brine_bell,
    emberwatch) numbers players 1..playersCount with the human as owner 1. The H3M
    translation previously carried the HoMM3 player color (+1) as the Olden owner,
    so a non-red human (e.g. A Gryphon's Heart color 5 -> owner 6) referenced a
    player seat the runtime never creates and the town grant silently failed.

    Rewrites ``owner`` on propSpawns / propOwners / propCities rows. Fail-closed:
    any owner referenced by propOwners/propCities that has no propSpawns seat is an
    orphan side and refuses emit. Call this after every owner-mutating pass
    (faction split, orphan binds) and before meta.spawns / install manifest build.
    """
    spawn_owners = sorted(
        {
            int(row["owner"])
            for row in (properties.get("propSpawns") or [])
            if isinstance(row, dict) and isinstance(row.get("owner"), int)
        }
    )
    if human_olden_owner not in spawn_owners:
        raise ValueError(
            f"human olden owner {human_olden_owner} missing from propSpawns owners "
            f"{spawn_owners}; cannot renumber"
        )
    ai_owners = [owner for owner in spawn_owners if owner != human_olden_owner]
    mapping = {human_olden_owner: 1}
    for index, owner in enumerate(ai_owners, start=2):
        mapping[owner] = index
    rewritten: dict[str, int] = {}
    for prop_key in ("propSpawns", "propOwners", "propCities"):
        count = 0
        for row in properties.get(prop_key) or []:
            if not isinstance(row, dict) or not isinstance(row.get("owner"), int):
                continue
            owner = int(row["owner"])
            if owner not in mapping:
                raise ValueError(
                    f"{prop_key} row id={row.get('id')} owner {owner} has no propSpawns "
                    f"seat (owners {spawn_owners}); orphan side refused"
                )
            row["owner"] = mapping[owner]
            count += 1
        rewritten[prop_key] = count
    return {
        "policy": "native_compact_owner_renumber_human_first",
        "ownerMapping": {str(k): v for k, v in sorted(mapping.items())},
        "humanOldenOwner": 1,
        "playersCount": len(mapping),
        "rewrittenRowCounts": rewritten,
    }


def build_scenario_player_spawns_from_prop_bindings(
    properties: dict[str, Any],
    *,
    human_olden_owner: int,
    human_faction_sid: str,
    human_hero_sid: str,
    human_start_hero_object_id: int | None = None,
    human_start_city_object_id: int | None = None,
) -> dict[str, Any]:
    """Emit meta.spawns from bound propSpawns/propCities/propHeroes (fail-closed).

    Prefer this after apply_explicit_ai_owner_faction_split so each Olden AI owner has
    exactly one city factionSid. Town-less AI owners are refused (would hang Session.Loader
    when StoryHub binds cities, or leave a hero-only side without a declared faction).

    ``human_start_hero_object_id`` must be the object bound by ``apply_native_start_contract``.
    Same-side hero placeholders often receive temporary Hero propSpawns with lower ids; using
    ``min(hero_ids)`` would steal the human primary, demote the real start to random-hero, and
    leave the player with no starting hero (Griffin Cliff / campaign-granted starts).

    ``human_start_city_object_id`` is the campaign-granted / ``mainTown.generateHero`` path:
    human primary is the grant town (City propSpawn + spawnHero + propHeroes on that id),
    matching brine_bell / vanilla_stock. Mutually exclusive with ``human_start_hero_object_id``.
    """
    if human_start_hero_object_id is not None and human_start_city_object_id is not None:
        raise ValueError(
            "human_start_hero_object_id and human_start_city_object_id are mutually exclusive"
        )
    spawn_rows = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int) and isinstance(row.get("owner"), int)
    ]
    if not spawn_rows:
        raise ValueError("propSpawns empty; cannot build meta.spawns")
    city_faction_by_id = {
        int(row["id"]): str(row.get("factionSid") or "")
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    hero_sid_by_id = {
        int(row["id"]): str(row.get("heroSid") or "")
        for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int) and row.get("heroSid")
    }
    owners = sorted({int(row["owner"]) for row in spawn_rows})
    if human_olden_owner not in owners:
        raise ValueError(
            f"human olden owner {human_olden_owner} missing from propSpawns owners {owners}"
        )
    spawns: list[dict[str, Any]] = []
    taken: list[str] = []
    owner_reports: dict[str, Any] = {}
    for olden_owner in owners:
        owner_rows = [row for row in spawn_rows if int(row["owner"]) == olden_owner]
        city_ids = [
            int(row["id"])
            for row in owner_rows
            if row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_CITY
        ]
        hero_ids = [
            int(row["id"])
            for row in owner_rows
            if row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO
        ]
        city_factions = sorted({city_faction_by_id[cid] for cid in city_ids if city_faction_by_id.get(cid)})
        if olden_owner == human_olden_owner:
            faction_sid = human_faction_sid
            city_faction_sid = human_faction_sid
            faction_policy = "human_spawn_faction"
            hero_sid = human_hero_sid
            spawn_type = OLDEN_SPAWN_TYPE_HUMAN
            is_hero_defined = True
            if human_start_city_object_id is not None:
                if human_start_city_object_id not in city_ids:
                    raise ValueError(
                        f"human start city object {human_start_city_object_id} missing from City "
                        f"propSpawns for owner {olden_owner}; city_ids={sorted(city_ids)}"
                    )
                start_spawn_row = next(
                    row for row in owner_rows if int(row["id"]) == human_start_city_object_id
                )
                if start_spawn_row.get("spawnType") != OLDEN_SPAWN_TYPE_HUMAN:
                    raise ValueError(
                        f"human start propSpawn id={human_start_city_object_id} must have "
                        f"spawnType=HUMAN({OLDEN_SPAWN_TYPE_HUMAN}); got {start_spawn_row.get('spawnType')!r}"
                    )
                if start_spawn_row.get("spawnPointType") != OLDEN_SPAWN_POINT_TYPE_CITY:
                    raise ValueError(
                        f"human start propSpawn id={human_start_city_object_id} must have "
                        f"spawnPointType=CITY({OLDEN_SPAWN_POINT_TYPE_CITY}); "
                        f"got {start_spawn_row.get('spawnPointType')!r}"
                    )
                bound_start_hero_sid = hero_sid_by_id.get(human_start_city_object_id)
                if bound_start_hero_sid != human_hero_sid:
                    raise ValueError(
                        f"human start propHeroes id={human_start_city_object_id} heroSid "
                        f"{bound_start_hero_sid!r} != meta human_hero_sid {human_hero_sid!r}"
                    )
                primary_hero_object_id = None
                primary_city_object_id = human_start_city_object_id
                spawn_point_type = OLDEN_SPAWN_POINT_TYPE_CITY
                is_city_defined = True
                extra_hero_ids = sorted(hero_ids)
                multi_hero_policy = "campaign_granted_city_spawn_primary"
                faction_policy = "human_campaign_granted_city_spawn"
            else:
                if human_start_hero_object_id is None:
                    raise ValueError(
                        "human_start_hero_object_id is required; refusing min(hero_ids) primary "
                        "which steals the start on multi-hero / campaign-granted maps"
                    )
                if human_start_hero_object_id not in hero_ids:
                    raise ValueError(
                        f"human start hero object {human_start_hero_object_id} missing from Hero "
                        f"propSpawns for owner {olden_owner}; hero_ids={sorted(hero_ids)}"
                    )
                start_spawn_row = next(
                    row for row in owner_rows if int(row["id"]) == human_start_hero_object_id
                )
                if start_spawn_row.get("spawnType") != OLDEN_SPAWN_TYPE_HUMAN:
                    raise ValueError(
                        f"human start propSpawn id={human_start_hero_object_id} must have "
                        f"spawnType=HUMAN({OLDEN_SPAWN_TYPE_HUMAN}); got {start_spawn_row.get('spawnType')!r}"
                    )
                bound_start_hero_sid = hero_sid_by_id.get(human_start_hero_object_id)
                if bound_start_hero_sid != human_hero_sid:
                    raise ValueError(
                        f"human start propHeroes id={human_start_hero_object_id} heroSid "
                        f"{bound_start_hero_sid!r} != meta human_hero_sid {human_hero_sid!r}"
                    )
                primary_hero_object_id = human_start_hero_object_id
                primary_city_object_id = None
                spawn_point_type = OLDEN_SPAWN_POINT_TYPE_HERO
                is_city_defined = False
                extra_hero_ids = sorted(hid for hid in hero_ids if hid != human_start_hero_object_id)
                multi_hero_policy = (
                    "explicit_start_hero_object_id_as_meta_spawns_primary"
                    if extra_hero_ids
                    else "explicit_start_hero_object_id_only"
                )
        else:
            spawn_type = OLDEN_SPAWN_TYPE_AI
            spawn_point_type = OLDEN_SPAWN_POINT_TYPE_HERO
            is_city_defined = False
            primary_city_object_id = None
            if not city_ids:
                raise ValueError(
                    f"AI olden owner {olden_owner} has no City propSpawns; "
                    f"refuse hero-only / unbound AI side (ids={sorted(int(r['id']) for r in owner_rows)})"
                )
            if len(city_factions) != 1 or not city_factions[0]:
                raise ValueError(
                    f"AI olden owner {olden_owner} city factions must be exactly one non-empty "
                    f"factionSid; got {city_factions} for city ids {city_ids}"
                )
            city_faction_sid = city_factions[0]
            # meta.spawns carries one primary heroSid per owner. Extra AI heroes remain
            # in propHeroes/propSpawns; pick lowest object id as the primary (deterministic).
            hero_bindings = [
                (hid, hero_sid_by_id[hid])
                for hid in sorted(hero_ids)
                if hero_sid_by_id.get(hid)
            ]
            faction_policy = "ai_bot_faction_from_single_city"
            # Bot fractionSid must follow the bound city. StoryHub CreateCityOnCampaignSpawn
            # paints cities as Side.fractionConfig.city; preferring a mismatched hero faction
            # (Homecoming Xyron Inferno under Terraneus Dungeon) turns the town into the wrong
            # faction. Enemy heroes spawn from propHeroes via Homm3CampaignSpawnParityHook
            # because native Bot campaignSpawns.heroSid is always empty.
            if len(hero_bindings) >= 1:
                primary_hero_object_id = hero_bindings[0][0]
                hero_sid = hero_bindings[0][1]
                is_hero_defined = True
                extra_hero_ids = [hid for hid, _ in hero_bindings[1:]]
                multi_hero_policy = "lowest_hero_object_id_as_meta_spawns_primary"
                faction_sid = city_faction_sid
            else:
                primary_hero_object_id = None
                hero_sid = ""
                is_hero_defined = False
                extra_hero_ids = []
                multi_hero_policy = None
                faction_sid = city_faction_sid
        row: dict[str, Any] = {
            "owner": olden_owner,
            "spawnType": spawn_type,
            "playerId": "",
            "spawnPointType": spawn_point_type,
            "isCityDefined": is_city_defined,
            "factionSid": faction_sid,
            "isHeroDefined": is_hero_defined,
            "colorId": -1,
            "isAlive": True,
            "isLocked": False,
        }
        if is_hero_defined:
            row["heroSid"] = hero_sid
            taken.append(hero_sid)
        elif is_city_defined:
            row["heroSid"] = ""
        spawns.append(row)
        owner_reports[str(olden_owner)] = {
            "factionSid": faction_sid,
            "cityFactionSid": city_faction_sid,
            "cityIds": city_ids,
            "heroIds": hero_ids,
            "isHeroDefined": is_hero_defined,
            "isCityDefined": is_city_defined,
            "heroSid": hero_sid if is_hero_defined else None,
            "primaryHeroObjectId": primary_hero_object_id,
            "primaryCityObjectId": primary_city_object_id,
            "extraHeroObjectIds": extra_hero_ids,
            "multiHeroPrimaryPolicy": multi_hero_policy,
            "factionPolicy": faction_policy,
        }
    return {
        "playersCount": len(spawns),
        "spawns": spawns,
        "takenHeroes": taken,
        "oldenOwners": owners,
        "humanOldenOwner": human_olden_owner,
        "ownerReports": owner_reports,
        "policy": "meta_spawns_from_prop_bindings_single_city_faction_per_owner",
    }


def build_scenario_player_spawns(
    entities: list[dict[str, Any]],
    *,
    human_h3_owner: int,
    human_faction_sid: str,
    human_hero_sid: str,
    placed_heroes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Emit meta.spawns for every non-neutral HoMM3 player (human + AI).

    Evidence: infinite_frost / campaign maps use spawnType 0=human, 1=AI in meta.spawns
    and matching propSpawns rows. Homecoming mixed Castle/Dungeon AI towns must call
    apply_explicit_ai_owner_faction_split + build_scenario_player_spawns_from_prop_bindings
    instead of this H3-owner majority path.
    """
    owners = collect_non_neutral_h3_owners(entities)
    if human_h3_owner not in owners:
        raise ValueError(
            f"human H3 owner {human_h3_owner} missing from scenario owners {owners}"
        )
    hero_by_owner: dict[int, str] = {}
    for row in placed_heroes:
        owner = row.get("owner")
        hero_sid = row.get("heroSid")
        if isinstance(owner, int) and owner != H3_NEUTRAL_OWNER and isinstance(hero_sid, str) and hero_sid:
            if owner in hero_by_owner and hero_by_owner[owner] != hero_sid:
                raise ValueError(
                    f"multiple placed heroes for H3 owner {owner}: "
                    f"{hero_by_owner[owner]} vs {hero_sid}"
                )
            hero_by_owner[owner] = hero_sid
    spawns: list[dict[str, Any]] = []
    taken: list[str] = []
    for h3_owner in owners:
        olden_owner = h3m_hero_sid.h3_owner_to_olden_player_index(h3_owner)
        if h3_owner == human_h3_owner:
            faction_sid = human_faction_sid
            hero_sid = human_hero_sid
            spawn_type = OLDEN_SPAWN_TYPE_HUMAN
        else:
            hero_sid = hero_by_owner.get(h3_owner)
            if not hero_sid:
                raise ValueError(
                    f"AI H3 owner {h3_owner} has towns/objects but no placed hero-spawner; "
                    "enemy side would never act"
                )
            faction_sid = ai_faction_sid_for_owner(entities, h3_owner, hero_sid)
            spawn_type = OLDEN_SPAWN_TYPE_AI
        spawns.append({
            "owner": olden_owner,
            "spawnType": spawn_type,
            "playerId": "",
            "spawnPointType": OLDEN_SPAWN_POINT_TYPE_HERO,
            "isCityDefined": False,
            "factionSid": faction_sid,
            "isHeroDefined": True,
            "heroSid": hero_sid,
            "colorId": -1,
            "isAlive": True,
            "isLocked": False,
        })
        taken.append(hero_sid)
    return {
        "playersCount": len(spawns),
        "spawns": spawns,
        "takenHeroes": taken,
        "h3Owners": owners,
        "humanH3Owner": human_h3_owner,
    }


def remap_object_sid_for_ids(
    objects: list[dict[str, Any]],
    *,
    from_sid: str,
    to_sid: str,
    object_ids: set[int],
) -> list[int]:
    """Move selected object ids from one objects[].sid group into another (split groups)."""
    if not object_ids:
        return []
    converted: list[int] = []
    new_objects: list[dict[str, Any]] = []
    pending_to: dict[str, list[Any]] = {
        "ids": [],
        "nodes": [],
        "rotations": [],
        "levels": [],
    }
    for group in objects:
        if not isinstance(group, dict) or group.get("sid") != from_sid:
            new_objects.append(group)
            continue
        ids = list(group.get("ids") or [])
        nodes = list(group.get("nodes") or [])
        rotations = list(group.get("rotations") or [0] * len(ids))
        levels = list(group.get("levels") or [0.0] * len(ids))
        keep_ids: list[int] = []
        keep_nodes: list[int] = []
        keep_rots: list[int] = []
        keep_levels: list[float] = []
        for index, object_id in enumerate(ids):
            if not isinstance(object_id, int):
                continue
            node = int(nodes[index]) if index < len(nodes) else 0
            rot = int(rotations[index]) if index < len(rotations) else 0
            level = float(levels[index]) if index < len(levels) else 0.0
            if object_id in object_ids:
                pending_to["ids"].append(object_id)
                pending_to["nodes"].append(node)
                pending_to["rotations"].append(rot)
                pending_to["levels"].append(level)
                converted.append(object_id)
            else:
                keep_ids.append(object_id)
                keep_nodes.append(node)
                keep_rots.append(rot)
                keep_levels.append(level)
        if keep_ids:
            rewritten = dict(group)
            rewritten["ids"] = keep_ids
            rewritten["nodes"] = keep_nodes
            rewritten["rotations"] = keep_rots
            rewritten["levels"] = keep_levels
            new_objects.append(rewritten)
    if pending_to["ids"]:
        # Merge into an existing destination group when present.
        merged = False
        for group in new_objects:
            if isinstance(group, dict) and group.get("sid") == to_sid:
                group["ids"] = list(group.get("ids") or []) + pending_to["ids"]
                group["nodes"] = list(group.get("nodes") or []) + pending_to["nodes"]
                group["rotations"] = list(group.get("rotations") or []) + pending_to["rotations"]
                group["levels"] = list(group.get("levels") or []) + pending_to["levels"]
                merged = True
                break
        if not merged:
            new_objects.append(
                {
                    "sid": to_sid,
                    "ids": pending_to["ids"],
                    "nodes": pending_to["nodes"],
                    "rotations": pending_to["rotations"],
                    "levels": pending_to["levels"],
                }
            )
    objects[:] = new_objects
    return converted


def object_instance_node(objects: list[dict[str, Any]], object_id: int) -> int | None:
    """Return the map node for ``object_id``, or None if the id is absent."""
    for group in objects:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        if not isinstance(ids, list) or not isinstance(nodes, list):
            continue
        for index, oid in enumerate(ids):
            if oid == object_id and index < len(nodes) and isinstance(nodes[index], int):
                return int(nodes[index])
    return None


def choose_human_primary_city_object_id(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    *,
    human_olden_owner: int,
    human_faction_sid: str,
    near_object_id: int | None = None,
) -> int:
    """Pick the human City propSpawn that should be the campaign start town.

    Prefer towns matching ``human_faction_sid``. When several remain, prefer the
    nearest to ``near_object_id`` (map-embedded start hero), then lowest id.
    """
    city_ids = sorted(
        int(row["id"])
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and int(row.get("owner") or -1) == human_olden_owner
        and row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_CITY
    )
    if not city_ids:
        raise ValueError(
            f"human olden owner {human_olden_owner} has no City propSpawns to promote"
        )
    faction_by_id = {
        int(row["id"]): str(row.get("factionSid") or "")
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    matching = [cid for cid in city_ids if faction_by_id.get(cid) == human_faction_sid]
    candidates = matching or list(city_ids)
    if near_object_id is not None and len(candidates) > 1:
        near_node = object_instance_node(objects, near_object_id)
        if near_node is not None:

            def _distance(city_id: int) -> tuple[int, int]:
                node = object_instance_node(objects, city_id)
                if node is None:
                    return (10**12, city_id)
                return (abs(node - near_node), city_id)

            return min(candidates, key=_distance)
    return min(candidates)


def retire_map_object_ids(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    object_ids: set[int],
) -> dict[str, Any]:
    """Remove object ids from ``objects[]`` and type-0 property rows bound to them."""
    if not object_ids:
        return {"retiredObjectIds": [], "removedPropertyRows": 0}
    import object_property_namespaces as propns

    remaining: list[dict[str, Any]] = []
    retired: list[int] = []
    for group in objects:
        if not isinstance(group, dict):
            remaining.append(group)
            continue
        ids = list(group.get("ids") or [])
        nodes = list(group.get("nodes") or [])
        rotations = list(group.get("rotations") or [0] * len(ids))
        levels = list(group.get("levels") or [0.0] * len(ids))
        keep_ids: list[int] = []
        keep_nodes: list[int] = []
        keep_rots: list[int] = []
        keep_levels: list[float] = []
        for index, object_id in enumerate(ids):
            if isinstance(object_id, int) and object_id in object_ids:
                retired.append(object_id)
                continue
            keep_ids.append(object_id)
            keep_nodes.append(int(nodes[index]) if index < len(nodes) else 0)
            keep_rots.append(int(rotations[index]) if index < len(rotations) else 0)
            keep_levels.append(float(levels[index]) if index < len(levels) else 0.0)
        if keep_ids:
            remaining.append(
                {
                    "sid": group.get("sid"),
                    "ids": keep_ids,
                    "nodes": keep_nodes,
                    "rotations": keep_rots,
                    "levels": keep_levels,
                }
            )
    objects[:] = remaining
    removed_rows = propns.remove_object_property_rows(properties, set(retired))
    return {
        "retiredObjectIds": sorted(set(retired)),
        "removedPropertyRows": int(removed_rows),
    }


def promote_human_hero_start_to_owned_city_spawn(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    *,
    hero_object_id: int,
    human_olden_owner: int,
    human_hero_sid: str,
    human_faction_sid: str,
) -> dict[str, Any] | None:
    """Rebind human start from Hero propSpawn to an owned City when towns exist.

    Campaign ``CreateCityOnCampaignSpawn`` sets ``ownerSide`` from the hub side
    index. Cities left only on ``propOwners`` with spawn-id owners (human=1) are
    read as raw ``sides.array`` indexes — out of range on solo maps and the wrong
    side on multi-side hubs. Stock / Black Sheep bind the start town as City
    propSpawn + ``spawnHero`` + ``propHeroes`` on the town id.

    Returns None when the human has no City propSpawns (hero-only starts stay).
    Fail-closed when a City exists but the hero start object is missing.
    """
    human_city_ids = [
        int(row["id"])
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and int(row.get("owner") or -1) == human_olden_owner
        and row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_CITY
    ]
    if not human_city_ids:
        return None

    hero_rows = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict)
        and row.get("id") == hero_object_id
        and int(row.get("owner") or -1) == human_olden_owner
        and row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO
    ]
    if not hero_rows:
        raise ValueError(
            f"cannot promote human start: hero object {hero_object_id} missing Hero "
            f"propSpawns for owner {human_olden_owner} while City propSpawns exist "
            f"{sorted(human_city_ids)}"
        )

    hero_sid = str(human_hero_sid or "").strip()
    if not hero_sid:
        raise ValueError("promote human city start requires non-empty human_hero_sid")
    faction_sid = str(human_faction_sid or "").strip()
    if not faction_sid:
        raise ValueError("promote human city start requires non-empty human_faction_sid")

    town_object_id = choose_human_primary_city_object_id(
        objects,
        properties,
        human_olden_owner=human_olden_owner,
        human_faction_sid=faction_sid,
        near_object_id=hero_object_id,
    )
    city_rows = [
        row
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]
    city = next((row for row in city_rows if int(row["id"]) == town_object_id), None)
    if city is None:
        raise ValueError(
            f"promote human city start: town {town_object_id} missing from propCities"
        )
    city["spawnHero"] = True
    city_spawn = {
        "type": 0,
        "id": town_object_id,
        "owner": human_olden_owner,
        "spawnType": OLDEN_SPAWN_TYPE_HUMAN,
        "spawnPointType": OLDEN_SPAWN_POINT_TYPE_CITY,
        "isLocked": False,
    }
    spawn_rows = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict) and row.get("id") not in (town_object_id, hero_object_id)
    ]
    properties["propSpawns"] = [city_spawn, *spawn_rows]
    existing_heroes = [
        row
        for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict) and row.get("id") not in (town_object_id, hero_object_id)
    ]
    properties["propHeroes"] = [
        {"type": 0, "id": town_object_id, "isDefined": True, "heroSid": hero_sid},
        *existing_heroes,
    ]
    retire = retire_map_object_ids(objects, properties, {hero_object_id})
    if hero_object_id not in set(retire["retiredObjectIds"]):
        raise ValueError(
            f"promote human city start: failed to retire hero-spawner object {hero_object_id}"
        )
    return {
        "status": "applied",
        "policy": "promote_map_hero_start_to_owned_city_spawn_plus_spawn_hero",
        "townObjectId": town_object_id,
        "retiredHeroObjectId": hero_object_id,
        "humanOldenOwner": human_olden_owner,
        "heroSid": hero_sid,
        "factionSid": faction_sid,
        "candidateCityIds": sorted(human_city_ids),
        "retire": retire,
        "proofBoundary": (
            "source/static: human-owned towns use City propSpawn so campaign "
            "CreateCityOnCampaignSpawn sets ownerSide from side.index; runtime "
            "town entry after install remains user-unvalidated"
        ),
    }


def apply_editor_compatible_spawn_contract(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    player_spawns: dict[str, Any],
) -> dict[str, Any]:
    """Native editor-safe spawn contract (c_M5 / proven orphan-hero fix).

    Map Editor ``BhPropertiesSpawn`` assumes every ``hero-spawner`` is listed in
    ``propSpawns`` and ``len(propSpawns) == playersCount``. Extra AI heroes must use
    ``random-hero`` + ``propHeroes`` (runtime parity still keys off ``propHeroes``).
    Non-primary owned cities/heroes keep ownership via ``propOwners``.
    """
    spawn_rows = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int) and isinstance(row.get("owner"), int)
    ]
    if not spawn_rows:
        raise ValueError("propSpawns empty; cannot apply editor-compatible spawn contract")
    spawn_by_id = {int(row["id"]): row for row in spawn_rows}
    owner_reports = player_spawns.get("ownerReports") or {}
    if not isinstance(owner_reports, dict) or not owner_reports:
        raise ValueError("player_spawns.ownerReports required for editor-compatible spawn contract")
    human_olden_owner = int(player_spawns["humanOldenOwner"])
    players_count = int(player_spawns["playersCount"])
    olden_owners = [int(owner) for owner in (player_spawns.get("oldenOwners") or [])]
    if len(olden_owners) != players_count:
        raise ValueError(
            f"oldenOwners {olden_owners} length != playersCount {players_count}"
        )

    kept_ids: list[int] = []
    kept_rows: list[dict[str, Any]] = []
    primary_by_owner: dict[str, int] = {}
    for olden_owner in olden_owners:
        report = owner_reports.get(str(olden_owner))
        if not isinstance(report, dict):
            raise ValueError(f"missing ownerReports for olden owner {olden_owner}")
        primary_city_id = report.get("primaryCityObjectId")
        if isinstance(primary_city_id, int):
            primary_id = primary_city_id
        elif olden_owner == human_olden_owner or report.get("isHeroDefined") is True:
            primary_id = report.get("primaryHeroObjectId")
            if not isinstance(primary_id, int):
                hero_candidates = [
                    int(row["id"])
                    for row in spawn_rows
                    if int(row["owner"]) == olden_owner
                    and row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO
                ]
                if not hero_candidates:
                    raise ValueError(
                        f"owner {olden_owner} isHeroDefined but has no Hero propSpawns / primaryHeroObjectId"
                    )
                primary_id = min(hero_candidates)
        else:
            city_ids = [int(cid) for cid in (report.get("cityIds") or []) if isinstance(cid, int)]
            if not city_ids:
                raise ValueError(
                    f"owner {olden_owner} has no hero primary and no cityIds for City propSpawns"
                )
            primary_id = min(city_ids)
        if primary_id not in spawn_by_id:
            raise ValueError(
                f"primary spawn object {primary_id} for owner {olden_owner} missing from propSpawns"
            )
        kept_ids.append(primary_id)
        kept_rows.append(dict(spawn_by_id[primary_id]))
        primary_by_owner[str(olden_owner)] = primary_id

    if len(kept_rows) != players_count:
        raise ValueError(
            f"kept propSpawns {len(kept_rows)} != playersCount {players_count}"
        )
    if len(set(kept_ids)) != len(kept_ids):
        raise ValueError(f"duplicate primary spawn object ids: {kept_ids}")

    kept_set = set(kept_ids)
    owner_rows = [
        row
        for row in (properties.get("propOwners") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]
    for row in spawn_rows:
        object_id = int(row["id"])
        if object_id in kept_set:
            continue
        upsert_property_row_by_id(
            owner_rows,
            {"type": 0, "id": object_id, "owner": int(row["owner"])},
        )

    properties["propSpawns"] = kept_rows
    properties["propOwners"] = owner_rows

    orphan_hero_ids = {
        object_id
        for object_id in find_object_ids(objects, OLDEN_HERO_SPAWNER_SID)
        if object_id not in kept_set
    }
    converted = remap_object_sid_for_ids(
        objects,
        from_sid=OLDEN_HERO_SPAWNER_SID,
        to_sid=OLDEN_RANDOM_HERO_SID,
        object_ids=orphan_hero_ids,
    )
    # Fail closed: every remaining hero-spawner must be a primary propSpawn.
    remaining_spawners = set(find_object_ids(objects, OLDEN_HERO_SPAWNER_SID))
    if remaining_spawners - kept_set:
        raise ValueError(
            f"orphan hero-spawner ids remain after remap: {sorted(remaining_spawners - kept_set)}"
        )
    if kept_set - remaining_spawners:
        # Primary may be a city, not a hero-spawner — only hero primaries must remain.
        hero_primaries = {
            int(row["id"])
            for row in kept_rows
            if row.get("spawnPointType") == OLDEN_SPAWN_POINT_TYPE_HERO
        }
        missing = hero_primaries - remaining_spawners
        if missing:
            raise ValueError(
                f"primary Hero propSpawns missing hero-spawner objects: {sorted(missing)}"
            )

    taken_sync = sync_taken_heroes_from_defined_prop_heroes(player_spawns, properties)

    return {
        "policy": "editor_compatible_propSpawns_eq_playersCount_orphan_heroes_as_random_hero",
        "playersCount": players_count,
        "keptPropSpawnIds": kept_ids,
        "primarySpawnByOwner": primary_by_owner,
        "propOwnersAddedOrUpdated": [
            int(row["id"])
            for row in spawn_rows
            if int(row["id"]) not in kept_set
        ],
        "convertedOrphanHeroSpawnerIds": sorted(converted),
        "remainingHeroSpawnerIds": sorted(remaining_spawners),
        "randomHeroIds": sorted(find_object_ids(objects, OLDEN_RANDOM_HERO_SID)),
        "takenHeroesSyncedFromPropHeroes": taken_sync,
    }


def sync_taken_heroes_from_defined_prop_heroes(
    player_spawns: dict[str, Any],
    properties: dict[str, Any],
) -> dict[str, Any]:
    """Ensure every defined ``propHeroes.heroSid`` is listed in ``takenHeroes``.

    Native Story maps (c_M2 / c_M3 / c_M4) put orphan ``random-hero`` identities in
    ``takenHeroes`` alongside lobby/primary spawns. Meta ``takenHeroes`` previously
    only listed primary ``meta.spawns`` heroes, so extra H3 heroes remapped to
    ``random-hero`` (e.g. Tyranell → ``homm3_castle_hero_8``) were omitted and did
    not instantiate at runtime despite ``propHeroes`` + ``propOwners`` rows.
    """
    taken = [
        str(sid)
        for sid in (player_spawns.get("takenHeroes") or [])
        if isinstance(sid, str) and sid
    ]
    seen = set(taken)
    added: list[str] = []
    for row in properties.get("propHeroes") or []:
        if not isinstance(row, dict) or row.get("isDefined") is not True:
            continue
        sid = row.get("heroSid")
        if not isinstance(sid, str) or not sid or sid == "random":
            continue
        if sid in seen:
            continue
        taken.append(sid)
        seen.add(sid)
        added.append(sid)
    player_spawns["takenHeroes"] = taken
    return {
        "policy": "defined_propHeroes_must_appear_in_takenHeroes_native_c_M_parity",
        "added": added,
        "takenHeroes": list(taken),
    }


def bind_human_start_city_entity_sid(
    properties: dict[str, Any],
    player_spawns: dict[str, Any],
    *,
    entity_sid: str,
) -> dict[str, Any]:
    """Stamp propEntities on the human primary city for UnlockBuildingCity grants.

    Featured capture cities already own propEntities SIDs. Starting-bonus BUILDING
    options target the human start town via a deterministic ``{mission}_start_city``
    SID. Fail closed when the human primary is not a city object.
    """
    sid = str(entity_sid or "").strip()
    if not sid:
        raise ValueError("start city entity SID must be non-empty")
    human_olden_owner = int(player_spawns["humanOldenOwner"])
    report = (player_spawns.get("ownerReports") or {}).get(str(human_olden_owner))
    if not isinstance(report, dict):
        raise ValueError(
            f"missing ownerReports for human olden owner {human_olden_owner}"
        )
    primary_city_id = report.get("primaryCityObjectId")
    if not isinstance(primary_city_id, int):
        raise ValueError(
            f"human owner {human_olden_owner} has no primaryCityObjectId; "
            "BUILDING starting bonuses require a town start"
        )
    city_ids = {
        int(row["id"])
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    if primary_city_id not in city_ids:
        raise ValueError(
            f"human primaryCityObjectId {primary_city_id} missing from propCities"
        )
    upsert_property_row_by_id(
        properties.setdefault("propEntities", []),
        {"type": 0, "id": primary_city_id, "sid": sid},
    )
    return {
        "policy": "human_start_city_propEntities_for_unlock_building",
        "humanOldenOwner": human_olden_owner,
        "primaryCityObjectId": primary_city_id,
        "entitySid": sid,
    }


def enable_town_spawn_hero_for_heroless_ai(
    properties: dict[str, Any],
    player_spawns: dict[str, Any],
) -> dict[str, Any]:
    """H3M hasRandomHero AI sides with towns but no placed heroes must spawn from the town.

    Land-on emit always writes propCities.spawnHero=false. When an AI owner has City
    propSpawns and zero Hero bindings, leave that false and the side never gets a hero
    — a strong AI-turn hang candidate. Flip spawnHero on the primary (min) city only.
    """

    owner_reports = player_spawns.get("ownerReports") or {}
    if not isinstance(owner_reports, dict):
        raise ValueError("player_spawns.ownerReports must be an object")
    human_olden_owner = int(player_spawns["humanOldenOwner"])
    city_rows = [
        row
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]
    city_by_id = {int(row["id"]): row for row in city_rows}
    enabled: list[dict[str, Any]] = []
    for owner_key, report in owner_reports.items():
        if not isinstance(report, dict):
            continue
        olden_owner = int(owner_key)
        if olden_owner == human_olden_owner:
            continue
        if report.get("isHeroDefined") is True:
            continue
        city_ids = [int(cid) for cid in (report.get("cityIds") or []) if isinstance(cid, int)]
        if not city_ids:
            raise ValueError(
                f"heroless AI owner {olden_owner} has no cityIds; refuse silent skip"
            )
        primary_city_id = min(city_ids)
        city = city_by_id.get(primary_city_id)
        if city is None:
            raise ValueError(
                f"heroless AI owner {olden_owner} primary city {primary_city_id} "
                f"missing from propCities"
            )
        if city.get("spawnHero") is True:
            continue
        city["spawnHero"] = True
        enabled.append(
            {
                "oldenOwner": olden_owner,
                "cityId": primary_city_id,
                "policy": "h3_has_random_hero_town_spawn_when_no_placed_ai_hero",
            }
        )
    return {
        "policy": "enable_town_spawn_hero_for_heroless_ai",
        "enabled": enabled,
    }


def append_placed_hero_properties(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
    *,
    start_hero_object_id: int,
    hero_names_by_type: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Bind non-start hero-spawner and prison objects to propHeroes (+ AI propSpawns).

    Resolves SIDs through ``resolve_h3_hero_sid`` so known H3M display names
    (including campaign-chain inherited names) win over bare type-id mapping.

    Prisons (H3 object 62) must bind ``propHeroes`` on the same object id — OE
    ``ObjPrison.heroSid`` is the rescue identity. Without that bind, stock prison
    objects_logic rolls a random hero (generator-wide miss, not mission-local).

    Temporary AI Hero propSpawns rows are trimmed later by
    ``apply_editor_compatible_spawn_contract`` (one propSpawn per player; orphans → random-hero).

    HoMM3 patrolRadius (e.g. Xyron 255 = stand still) has no proven Olden PropHero/PropSpawn
    sink. propSpawns.isLocked is lobby/start-hero lock on campaign maps, not adventure AI
    patrol. Do not emit patrolRadius or abuse isLocked for idle AI until a native sink is proven.

    Custom army/artifacts are not PropHero fields. Identity binds here; QuestScript
    ``GiveItemHero`` / ``GiveUnitHero`` grants are planned later from the returned rows
    (see ``campaign_placed_hero_payloads``).
    """
    import campaign_placed_hero_payloads as hero_payloads

    placed: list[dict[str, Any]] = []
    hero_rows = list(properties.get("propHeroes") or [])
    spawn_rows = list(properties.get("propSpawns") or [])
    bound_ids = {int(row["id"]) for row in hero_rows if isinstance(row, dict) and isinstance(row.get("id"), int)}
    spawn_ids = {int(row["id"]) for row in spawn_rows if isinstance(row, dict) and isinstance(row.get("id"), int)}
    taken_sids = {
        str(row.get("heroSid"))
        for row in hero_rows
        if isinstance(row, dict) and isinstance(row.get("heroSid"), str) and row.get("heroSid")
    }
    names_by_type = hero_names_by_type or {}
    import h3_campaign_placed_heroes as placed_campaign_heroes

    host_specs = (
        ("hero-spawner", "hero_spawner"),
        ("prison", "prison"),
    )
    for object_sid, host_kind in host_specs:
        for object_id in find_object_ids(objects, object_sid):
            if object_id == start_hero_object_id or object_id in bound_ids:
                continue
            entity = entities_by_id.get(object_id)
            if entity is None:
                raise ValueError(f"placed {host_kind} {object_id} has no source entity")
            if host_kind == "prison" and not _entity_is_h3_prison(entity):
                raise ValueError(
                    f"prison object id {object_id} source entity is not H3 prison "
                    f"(templateObjectId={entity.get('templateObjectId')!r} "
                    f"animation={entity.get('templateAnimation')!r})"
                )
            hero_type = entity.get("heroType")
            if not isinstance(hero_type, int):
                raise ValueError(f"placed {host_kind} {entity.get('sourceKey')} missing heroType")
            owner = entity.get("owner")
            if hero_type == h3m_hero_sid.H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
                hero_sid = h3m_hero_sid.allocate_placeholder_hero_sid(taken_sids)
                binding_policy = "h3_hero_type_255_lossy_unique_placeholder_pool"
            else:
                # Prefer the placed object's own H3 custom name (Tyranell / Gen. Kendal)
                # over campaign-header type→name aliases so bespoke map names become
                # campaign-only Core stubs instead of stock roster Loc (Tyris / Edric).
                entity_name = None
                if entity.get("hasName") is True:
                    raw_name = entity.get("name")
                    if isinstance(raw_name, str) and raw_name.strip():
                        entity_name = raw_name.strip()
                hero_name = entity_name if entity_name is not None else names_by_type.get(hero_type)
                hero_sid, evidence_tag = placed_campaign_heroes.resolve_placed_hero_sid(
                    hero_type, name=hero_name
                )
                binding_policy = f"h3_hero_resolve:{evidence_tag}"
            taken_sids.add(hero_sid)
            row = {"type": 0, "id": object_id, "isDefined": True, "heroSid": hero_sid}
            hero_rows.append(row)
            # Prisons are neutral rescues — do not emit AI Hero propSpawns.
            if (
                host_kind == "hero_spawner"
                and isinstance(owner, int)
                and owner != H3_NEUTRAL_OWNER
                and object_id not in spawn_ids
            ):
                spawn_rows.append({
                    "type": 0,
                    "id": object_id,
                    "owner": h3m_hero_sid.h3_owner_to_olden_player_index(owner),
                    "spawnType": OLDEN_SPAWN_TYPE_AI,
                    "spawnPointType": OLDEN_SPAWN_POINT_TYPE_HERO,
                    "isLocked": False,
                })
                spawn_ids.add(object_id)
            placed.append({
                "objectId": object_id,
                "sourceKey": entity.get("sourceKey"),
                "heroType": hero_type,
                "owner": owner,
                "heroSid": hero_sid,
                "hostKind": host_kind,
                "entitySid": deterministic_entity_sid(object_sid, object_id),
                "bindingPolicy": binding_policy,
                "hasCustomPayload": hero_payloads.entity_has_custom_payload(entity),
            })
            bound_ids.add(object_id)
    properties["propHeroes"] = hero_rows
    properties["propSpawns"] = spawn_rows
    return placed


def _entity_is_h3_prison(entity: Mapping[str, Any]) -> bool:
    if int(entity.get("templateObjectId") or -1) == 62:
        return True
    anim = str(entity.get("templateAnimation") or "").lower()
    return anim.startswith("avxprsn")


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
        key: _clone_jsonable(meta.get(key))
        for key in [
            "economicDifficulties",
            "aiDifficulties",
            "neutralDifficulties",
            "quickStartDifficulties",
            "campaignInfo",
            "banInfoData",
        ]
    }
    start_settings = _clone_jsonable(meta.get("startSettings", {}))
    settings = _clone_jsonable(map_data.get("settings", {}))
    if not start_settings or not settings or any(value is None for value in meta_shape.values()):
        raise ValueError(f"native start template missing start settings: {NATIVE_START_TEMPLATE_MAP}")
    return meta_shape, start_settings, settings


def generate_squad_overlays(
    global_entities: list[dict[str, Any]],
    *,
    map_event_specs: dict[str, dict[str, Any]] | None = None,
    human_h3_owner: int | None = None,
) -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    squad_dir = out_dir / SQUAD_OVERLAY_MEMBER_ROOT
    if squad_dir.exists():
        for stale in squad_dir.glob(f"{MISSION_ID}_*.json"):
            stale.unlink()
    emitted: dict[str, dict[str, Any]] = {}
    for entity in global_entities:
        if is_adventure_map_garrison_entity(entity):
            stacks = mapped_adventure_garrison_stacks(entity)
            sid = adventure_garrison_squad_overlay_sid(entity)
            emitted[sid] = adventure_garrison_squad_overlay_doc(entity, stacks)
            continue
        if is_concrete_h3_monster_stack(entity):
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
            continue
        stacks = mapped_town_garrison_stacks(entity)
        if stacks:
            owner = entity.get("owner")
            if (
                human_h3_owner is not None
                and isinstance(owner, int)
                and owner == human_h3_owner
            ):
                # Match append_town_ownership: human towns keep empty propRandomSquads.
                continue
            sid = town_garrison_squad_sid(entity)
            emitted[sid] = town_garrison_squad_overlay_doc(entity, stacks)
    # Guarded map events: exact propSquads.unitProps PLUS random-squad overlay
    # (SpawnsCreator requires propRandomSquads; v = count×squadValue).
    for source_key, spec in sorted((map_event_specs or {}).items()):
        if not isinstance(spec, dict) or not spec.get("hasGuards"):
            continue
        overlay_sid = str(spec.get("squadOverlaySid") or "")
        if not overlay_sid:
            raise ValueError(f"map event {source_key} hasGuards but missing squadOverlaySid for overlay emit")
        if overlay_sid in emitted:
            continue
        nonempty = campaign_script.nonempty_guard_stacks(
            spec.get("guardStacks"),
            context=f"map event {source_key} overlay",
            allow_empty=True,
        )
        if not nonempty:
            # Demoted empty hasGuards: no squad overlay row.
            continue
        mapped = mapped_map_event_guard_stacks(
            nonempty,
            context=f"map event {source_key} overlay",
        )
        value_stacks = map_event_guard_value_stacks(
            mapped,
            context=f"map event {source_key} overlay",
        )
        emitted[overlay_sid] = map_event_guard_squad_overlay_doc(
            squad_overlay_sid=overlay_sid,
            stacks=value_stacks,
        )
    outputs = []
    for sid, doc in sorted(emitted.items()):
        path = squad_dir / f"{sid}.json"
        write_json(path, doc)
        outputs.append({"sid": sid, "member": f"{SQUAD_OVERLAY_MEMBER_ROOT}/{sid}.json", "output": str(path)})
    manifest = {
        "status": "generated_squad_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "missionId": MISSION_ID,
        "count": len(outputs),
        "outputs": outputs,
    }
    write_json(out_dir / f"{MISSION_ID}_squad_overlay_manifest.json", manifest)
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
        "replacement": OCEAN_ARCHITECTURE,
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
        "replacement": OCEAN_ARCHITECTURE,
        "runtimeHook": ACTIVE_WATER_RUNTIME_HOOK,
    }

def generate_water_tile_penalty_overlay() -> dict[str, Any]:
    """Retired: ocean is the native basin (campaign_ocean); no tiles.json overlay is written."""
    manifest = {
        "status": "retired_native_basin_ocean_needs_no_tile_overlay",
        "architecture": OCEAN_ARCHITECTURE,
        "ocean": ocean.describe(),
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
    if existing is None or existing == expected_row:
        return
    # Allow replacing our own prior Homecoming subterranean portal footprint while the
    # Dungeon Entrance prefab identity stays fixed (e.g. 2x2 → 3x3 south-center GATE).
    if (
        row_id == HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
        and existing.get("prefs") == [HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB]
        and expected_row.get("prefs") == [HOMM3_SUBTERRANEAN_GATE_PORTAL_PREFAB]
    ):
        return
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


def _core_member_array_row(member: str, row_id: str) -> dict[str, Any] | None:
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        if member not in core.namelist():
            return None
        doc = json.loads(core.read(member).decode("utf-8-sig"))
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == row_id]
    if len(matches) > 1:
        raise ValueError(f"Core.zip {member} contains duplicate {row_id!r} rows")
    return matches[0] if matches else None


def _require_donor_row_from_doc_or_core(
    doc: dict[str, Any],
    member: str,
    row_id: str,
) -> dict[str, Any]:
    """Prefer overlay/doc row; fall back to live Core.zip when inherit overlays are stale.

    Land-on barracks donors expand with Core (factory/bulwark/neutrals). Inherited
    single_layer overlays can predate those rows; fail closed only if Core also lacks them.
    """
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{member} must contain array rows")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == row_id]
    if len(matches) > 1:
        raise ValueError(f"{member} contains duplicate {row_id!r} rows")
    if len(matches) == 1:
        return matches[0]
    donor = _core_member_array_row(member, row_id)
    if not isinstance(donor, dict):
        raise ValueError(f"{member} must contain exactly one {row_id!r} row")
    return donor


def generate_homm3_landon_object_overlay() -> dict[str, Any]:
    out_dir = OUT_ROOT / "core_overlay"
    fxs_doc = read_core_json(HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER)
    interactables_doc = read_core_json(HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER)
    map_event_donor = require_core_array_row(
        fxs_doc,
        HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER,
        HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
    )
    castle_city_donor = _require_donor_row_from_doc_or_core(
        interactables_doc,
        HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
    )
    dungeon_city_donor = _require_donor_row_from_doc_or_core(
        interactables_doc,
        HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
    )
    barracks_donors = {
        donor_sid: _require_donor_row_from_doc_or_core(
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

    # CreateCity often spawns from stock homm3_*_city (fractionConfig.city). Those
    # donor rows ship with SW GATE index 6; normalize every town SID so live interact
    # stays south-center after body-center / one-north map emit (visit-align no longer
    # masks the corner GATE).
    town_gate_normalize_count = normalize_homm3_town_city_bottom_center_gates_in_doc(
        interactables_doc
    )

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
        barracks_logic_row = _require_donor_row_from_doc_or_core(
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
    if (
        not guardhouse_alignment["bottomCenterGate"]
        or guardhouse_alignment["gateCount"] != 1
        or guardhouse_alignment.get("visitOnGate") is not True
        or guardhouse_alignment.get("anchorPolicy") != "landon_gate_aligned_to_h3_visit"
    ):
        raise ValueError(
            "homm3_landon_barracks_castle_1 GATE→visit alignment failed for Guardhouse dwelling "
            f"{GUARDHOUSE_DWELLING_SOURCE_KEY}: {guardhouse_alignment}"
        )

    donors_by_sid = {
        HOMM3_LANDON_MAP_EVENT_MARKER_SID: HOMM3_LANDON_MAP_EVENT_MARKER_DONOR_SID,
        HOMM3_LANDON_CASTLE_CITY_SID: HOMM3_LANDON_CASTLE_CITY_DONOR_SID,
        HOMM3_LANDON_DUNGEON_CITY_SID: HOMM3_LANDON_DUNGEON_CITY_DONOR_SID,
        HOMM3_FLOTSAM_PICKUP_SID: HOMM3_FLOTSAM_PICKUP_DONOR_SID,
        **{clone: donor for donor, clone in HOMM3_LANDON_BARRACKS_BY_DONOR.items()},
    }
    object_members = {
        HOMM3_LANDON_MAP_EVENT_MARKER_SID: HOMM3_LANDON_MAP_EVENT_MARKER_OBJECT_MEMBER,
        HOMM3_LANDON_CASTLE_CITY_SID: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_LANDON_DUNGEON_CITY_SID: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER,
        HOMM3_FLOTSAM_PICKUP_SID: HOMM3_RANDOM_RESOURCE_PICKUP_OBJECT_MEMBER,
        **{clone: HOMM3_LANDON_INTERACTABLE_OBJECT_MEMBER for clone in HOMM3_LANDON_BARRACKS_SIDS},
    }

    manifest = {
        "status": HOMM3_LANDON_OBJECT_OVERLAY_STATUS,
        "architecture": HOMM3_LANDON_OBJECT_OVERLAY_ARCHITECTURE,
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "objectSids": sorted(object_rows),
        "donorsBySid": donors_by_sid,
        "objectMembers": object_members,
        "logicOutputs": logic_outputs,
        "outputs": {
            "fxObjects": str(fxs_path),
            "interactables": str(interactables_path),
            "customObjects": str(custom_objects_path),
        },
        "guardhouseVisitGateAlignment": guardhouse_alignment,
        "townBottomCenterGateNormalizeCount": town_gate_normalize_count,
        "barracksGatePolicy": {
            "nodes": list(HOMM3_LANDON_BARRACKS_CASTLE_1_NODES),
            "sizeX": 1,
            "sizeZ": 1,
            "gateIndex": 0,
            "alignment": "landon_gate_aligned_to_h3_visit",
            "policy": "1x1_visit_gate_no_invented_occ_gap_fill_seals_h3_blocks",
            "landonBarracksSids": sorted(HOMM3_LANDON_BARRACKS_SIDS),
        },
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
    ban_row = _clone_jsonable(ban_source)
    preset_row = _clone_jsonable(preset_source)
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


def generate_campaign_dialog_overlay(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        raise ValueError("campaign dialog overlay requires at least one dialog entry")
    out_dir = OUT_ROOT / "core_overlay"
    english_member = "Lang/english/texts/dialogues.json"
    english_path = out_dir / english_member
    dialog_outputs: dict[str, str] = {}
    replacement_tokens: dict[str, str] = {}
    dialog_folder = campaign_dialog_folder_name()
    for entry in entries:
        dialog_sid = str(entry["id"])
        # Empty string is intentional (narration / no speaker). Only fall back when
        # the entry omitted title entirely.
        if "title" in entry and entry.get("title") is not None:
            title = str(entry.get("title") or "")
        else:
            title = campaign_dialog_folder_name()
        text = str(entry.get("text") or "").strip()
        planned_slides = entry.get("slides") if isinstance(entry.get("slides"), list) else None
        if planned_slides:
            if not planned_slides:
                raise ValueError(f"campaign dialog {dialog_sid!r} has empty slides")
        elif not text:
            raise ValueError(f"campaign dialog {dialog_sid!r} is missing text")
        # Legacy intro SID keeps historical Core token names (not dialogue_*_homecoming_intro_dialog_*).
        if dialog_sid == INTRO_DIALOG_SID and MISSION_ID == "homecoming":
            title_token = "dialogue_title_homecoming_intro"
            text_token = "dialogue_text_homecoming_intro_0"
            replacement_tokens[title_token] = title
            replacement_tokens[text_token] = text
            avatars = entry.get("avatars") if isinstance(entry.get("avatars"), list) else []
            # Portrait planner may attach multi-slide avatars; homecoming intro still
            # emits as one legacy-token slide, so lift any planned avatar onto it.
            if not avatars and planned_slides:
                for slide in planned_slides:
                    if not isinstance(slide, dict):
                        continue
                    slide_avatars = slide.get("avatars")
                    if isinstance(slide_avatars, list) and slide_avatars:
                        avatars = slide_avatars
                        slide_title = str(slide.get("title") or "").strip()
                        if slide_title:
                            replacement_tokens[title_token] = slide_title
                        break
            title_position = entry.get("titlePosition")
            if not isinstance(title_position, int):
                title_position = 1 if avatars else 3
            slides_doc = [{
                "id": "start",
                "fon": "",
                "avatars": avatars,
                "title": {"sid": title_token, "position": title_position},
                "text": text_token,
                "next": "ending",
            }]
        elif planned_slides:
            slides_doc = []
            explicit_ids = {
                str(slide.get("id"))
                for slide in planned_slides
                if isinstance(slide, dict) and isinstance(slide.get("id"), str) and slide.get("id")
            }
            for index, slide in enumerate(planned_slides):
                if not isinstance(slide, dict):
                    raise ValueError(f"campaign dialog {dialog_sid!r} slide {index} malformed")
                slide_text = str(slide.get("text") or "").strip()
                if not slide_text:
                    raise ValueError(f"campaign dialog {dialog_sid!r} slide {index} missing text")
                slide_title_raw = slide.get("title")
                if slide_title_raw is None:
                    slide_title = title
                else:
                    slide_title = str(slide_title_raw)
                title_token = (
                    f"dialogue_title_{dialog_sid}"
                    if index == 0
                    else f"dialogue_title_{dialog_sid}_{index}"
                )
                text_token = f"dialogue_text_{dialog_sid}_{index}"
                replacement_tokens[title_token] = slide_title
                replacement_tokens[text_token] = slide_text
                avatars = slide.get("avatars") if isinstance(slide.get("avatars"), list) else []
                title_position = slide.get("titlePosition")
                if not isinstance(title_position, int):
                    title_position = 1 if avatars else 3
                raw_slide_id = slide.get("id")
                if isinstance(raw_slide_id, str) and raw_slide_id.strip():
                    slide_id = raw_slide_id.strip()
                else:
                    slide_id = "start" if index == 0 else str(index)
                answers = slide.get("answers")
                map_actions = slide.get("mapActions")
                slide_doc: dict[str, Any] = {
                    "id": slide_id,
                    "fon": "",
                    "avatars": avatars,
                    "title": {"sid": title_token, "position": title_position},
                    "text": text_token,
                }
                if isinstance(map_actions, list) and map_actions:
                    for action_index, action in enumerate(map_actions):
                        if not isinstance(action, dict) or not isinstance(action.get("a"), str):
                            raise ValueError(
                                f"campaign dialog {dialog_sid!r} slide {slide_id!r} "
                                f"mapActions[{action_index}] malformed"
                            )
                    slide_doc["mapActions"] = map_actions
                if isinstance(answers, list) and answers:
                    answer_docs: list[dict[str, Any]] = []
                    for answer_index, answer in enumerate(answers):
                        if not isinstance(answer, dict):
                            raise ValueError(
                                f"campaign dialog {dialog_sid!r} slide {slide_id!r} "
                                f"answers[{answer_index}] malformed"
                            )
                        answer_text = str(answer.get("text") or "").strip()
                        if not answer_text:
                            raise ValueError(
                                f"campaign dialog {dialog_sid!r} slide {slide_id!r} "
                                f"answers[{answer_index}] missing text"
                            )
                        answer_token = (
                            f"dialogue_text_{dialog_sid}_{index}_answer_{answer_index + 1}"
                        )
                        replacement_tokens[answer_token] = answer_text
                        answer_actions = answer.get("actions")
                        if not isinstance(answer_actions, list) or not answer_actions:
                            raise ValueError(
                                f"campaign dialog {dialog_sid!r} slide {slide_id!r} "
                                f"answers[{answer_index}] missing actions"
                            )
                        for action in answer_actions:
                            if not isinstance(action, dict) or not isinstance(action.get("a"), str):
                                raise ValueError(
                                    f"campaign dialog {dialog_sid!r} slide {slide_id!r} "
                                    f"answers[{answer_index}] action malformed"
                                )
                            if action.get("a") == "Go":
                                target = (action.get("p") or [None])[0]
                                if target not in explicit_ids and target != "ending":
                                    raise ValueError(
                                        f"campaign dialog {dialog_sid!r} answer Go target "
                                        f"{target!r} is not a defined slide id"
                                    )
                        answer_docs.append(
                            {
                                "text": answer_token,
                                "actions": answer_actions,
                            }
                        )
                    slide_doc["answers"] = answer_docs
                elif slide.get("end") is True:
                    slide_doc["end"] = True
                    if isinstance(slide.get("resultDialog"), str) and slide.get("resultDialog"):
                        slide_doc["resultDialog"] = slide["resultDialog"]
                    if slide.get("invokeOnlyActions") is True:
                        slide_doc["invokeOnlyActions"] = True
                else:
                    if index + 1 >= len(planned_slides):
                        next_id = "ending"
                    else:
                        next_slide = planned_slides[index + 1]
                        next_raw = next_slide.get("id") if isinstance(next_slide, dict) else None
                        next_id = (
                            str(next_raw).strip()
                            if isinstance(next_raw, str) and next_raw.strip()
                            else str(index + 1)
                        )
                    slide_doc["next"] = next_id
                slides_doc.append(slide_doc)
        else:
            title_token = f"dialogue_title_{dialog_sid}"
            text_token = f"dialogue_text_{dialog_sid}_0"
            replacement_tokens[title_token] = title
            replacement_tokens[text_token] = text
            avatars = entry.get("avatars") if isinstance(entry.get("avatars"), list) else []
            title_position = entry.get("titlePosition")
            if not isinstance(title_position, int):
                title_position = 1 if avatars else 3
            slides_doc = [{
                "id": "start",
                "fon": "",
                "avatars": avatars,
                "title": {"sid": title_token, "position": title_position},
                "text": text_token,
                "next": "ending",
            }]
        dialog_member = f"DB/dialogs/dialogs/custom_maps/{dialog_folder}/{dialog_sid}.json"
        dialog_path = out_dir / dialog_member
        dialog_doc = {
            "array": [{
                "id": dialog_sid,
                "localization": True,
                "slides": slides_doc + [{
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
    import core_zip_cache

    english_doc = _clone_jsonable(core_zip_cache.read_core_json(poc.OLDEN_CORE_ZIP, english_member))
    tokens = english_doc.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError(f"{english_member} must contain a tokens list")
    # Core ships many dialog SIDs in both tokens and array. Update both so a later
    # Lang overlay pass (tokens+array scan) cannot resurrect a stale array title.
    array_rows = english_doc.get("array")
    if not isinstance(array_rows, list):
        array_rows = []
        english_doc["array"] = array_rows
    for section in (tokens, array_rows):
        existing = {
            row.get("sid"): row
            for row in section
            if isinstance(row, dict) and isinstance(row.get("sid"), str)
        }
        for sid, text in replacement_tokens.items():
            if sid in existing:
                existing[sid]["text"] = text
            else:
                section.append({"sid": sid, "text": text})
    write_json(english_path, english_doc)
    try:
        import homecoming_localization as homecoming_lang

        homecoming_lang.write_lang_overlay(out_dir, Path(poc.OLDEN_CORE_ZIP))
    except Exception as ex:
        raise RuntimeError(f"Homecoming multilingual Lang overlay failed after dialog generate: {ex}") from ex
    manifest = {
        "status": "generated_dialog_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "missionId": MISSION_ID,
        "dialogFolder": dialog_folder,
        "englishMember": english_member,
        "dialogSids": [entry["id"] for entry in entries],
        "outputs": {"dialogs": dialog_outputs, "english": str(english_path)},
    }
    write_json(out_dir / f"{MISSION_ID}_intro_dialog_overlay_manifest.json", manifest)
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
    valid_ids.add("homm3_seer_hut")
    valid_ids.add(HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
    valid_ids.update(HOMM3_LANDON_OBJECT_SIDS)
    valid_ids.add(HOMM3_PATHING_BLOCKER_SID)
    extend_valid_ids_with_core_homm3_artifacts(valid_ids)
    valid_ids.add(HOMM3_FLOTSAM_PICKUP_SID)
    substitution_lookup = build_substitution_lookup(substitution)
    native_object_configs = load_native_object_configs(valid_ids)

    surface_map_data = alignment["container"]["chunks"][1]
    global_entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    layer_histogram = Counter(entity.get("sourceLayer") for entity in global_entities)
    if dict(layer_histogram) != {0: 1453, 1: 400}:
        raise ValueError(f"unexpected source layer histogram: {dict(layer_histogram)}")
    # Unnamed H3M towns get authentic HoMM3 pool names on the full cross-layer
    # list before any PropCity emit (same contract as build_layered_objects).
    h3_town_name_pool.assign_default_town_names(global_entities, mission_id=MISSION_ID)
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
        "policy": FOOTPRINT_ALIGNMENT_POLICY,
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
    chunks = _clone_jsonable(container.chunks)
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
                    "spawnPointType": OLDEN_SPAWN_POINT_TYPE_HERO,
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
    squad_overlay = generate_squad_overlays(global_entities, map_event_specs=map_event_specs)
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
