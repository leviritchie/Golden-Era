#!/usr/bin/env python3
"""Validate the generated Homecoming Olden entity-substitution map contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT_FOR_IMPORTS / "experiments" / "campaign_port_poc"))
import h3m_object_registry as h3obj

SCHEMA = "homm3.homecoming_olden_entity_substitution_map.v0"
STATUS = "query_shape_substitutions_not_playable"
ALIGNMENT_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"
CORE_CATALOG_PATH = Path("artifacts") / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"
OUTPUT_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "entity_substitutions" / "homecoming.olden_entity_substitution_map.json"
GENERATOR = Path("experiments") / "campaign_port_poc" / "build_homecoming_entity_substitution_map.py"
FORBIDDEN_REPLACEMENTS = {"", "debugObject"}
LOSSY_PLACEHOLDER_RULES: set[str] = set()
CONFIDENCE_VALUES = {
    "exact",
    "role_and_visual",
    "role",
    "template_family",
    "visual_family",
    "visual_context_only",
    "source_tile_biome",
    "localized_semantic_family",
    "minilm_semantic_family",
    "artifact_effect_shape",
    "blocked",
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
    136: "rock",  # HoMM3 Outcropping (AVLoc*); not a lake
    137: "tree",
    147: "rock",
    148: "ruin",
    149: "pool_big",
    150: "shrub",
    151: "rock",
    153: "rock",
    155: "terrain_animation_classification_required",
}
BIOME_ROLE_REPLACEMENTS = {
    "mountain": {"grass": "mountain_green_small_1", "snow": "mountain_snow_small_1", "dirt": "mountain_dirt_small_1", "desert": "mountain_dirt_small_1", "dead": "mountain_dead_small_1", "lava": "mountain_lava_small_1", "water": "mountain_water_small_1"},
    "pool": {"grass": "pool_small", "snow": "pool_snow_small_1", "dirt": "pool_dirt_small_1", "desert": "pool_desert_small_1", "dead": "pool_dead_small_1", "lava": "pool_lava_small_1", "water": "water_reed_1"},
    "pool_big": {"grass": "pool_big", "snow": "pool_snow_big_1", "dirt": "pool_dirt_big_1", "desert": "pool_desert_big_1", "dead": "pool_dead_big_1", "lava": "pool_lava_big_1", "water": "water_reed_1"},
    "tree": {"grass": "pinetree_1", "snow": "pinetree_snow_1", "dirt": "tree_dirt_1", "desert": "grass_desert_1", "dead": "tree_dead_1", "lava": "tree_lava_1", "water": "water_reed_1"},
    "shrub": {"grass": "grass_1", "snow": "grass_snow_1", "dirt": "dirt_strange_flower", "desert": "grass_desert_1", "dead": "grass_death_1", "lava": "lava_ground_1", "water": "water_reed_1"},
    "rock": {"grass": "grass_stones_1", "snow": "snow_stones_1", "dirt": "dirt_rock_1", "desert": "desert_stones_1", "dead": "dead_stones_1", "lava": "lava_stones_1", "water": "water_reed_1"},
    "ground": {"grass": "grass_stones_1", "snow": "snow_stones_1", "dirt": "dirt_stones_1", "desert": "desert_dune_1", "dead": "dead_meadow", "lava": "lava_ground_1", "water": "water_reed_1"},
    "ruin": {"grass": "rocks_1", "snow": "snow_rock_hill_1", "dirt": "dirt_rock_1", "desert": "ruins_desert_1", "dead": "dead_sculls_bones_hill", "lava": "dirt_volcanic_rock", "water": "water_reed_1"},
    "water_decoration": {"grass": "water_reed_1", "snow": "water_reed_1", "dirt": "water_reed_1", "desert": "water_reed_1", "dead": "water_reed_1", "lava": "water_reed_1", "water": "water_reed_1"},
}

EXPECTED_HAND_AUDITED_BUILDING_SUBSTITUTIONS = {
    4: {"templateAnimation": "AVSarna0.def", "replacementSid": "fort", "ruleName": "arena_to_pauper_knight_order_stats_bank"},
    23: {"templateAnimation": "AvSMarl.def", "replacementSid": "armory_automaton", "ruleName": "marletto_tower_to_summit_automaton_defense_bank"},
    31: {"templateAnimation": "AVXfyth0.def", "replacementSid": "fountain", "ruleName": "faith_to_fountain", "confidence": "role_and_visual"},
    41: {"templateAnimation": "AVSlibr0.def", "replacementSid": "college_of_wonder", "ruleName": "library_to_mountain_monastery_all_stats_bank"},
    47: {"templateAnimation": "AVSschm0.def", "replacementSid": "orb_observatory", "ruleName": "school_of_magic_to_four_scholars_observatory_magic_stats_bank"},
    51: {"templateAnimation": "AVSmerc0.def", "replacementSid": "stinging_sword", "ruleName": "mercenary_camp_to_stinging_sword_attack_bank"},
    80: {"templateAnimation": "AVXsanc0.def", "replacementSid": "altar_of_magic_1", "ruleName": "sanctuary_to_altar_of_magic", "confidence": "role_and_visual"},
    96: {"templateAnimation": "AVStmpl0.def", "replacementSid": "quixs_path", "ruleName": "temple_to_quixs_altar_morale_bank"},
    107: {"templateAnimation": "AVSwar20.def", "replacementSid": "fort", "ruleName": "school_of_war_to_pauper_knight_order_stats_bank"},
    113: {"templateAnimation": "AVSwtch0.def", "replacementSid": "wise_owl", "ruleName": "witch_hut_to_wise_owl_skill_bank", "category": "interactive_reward_object", "payloadKind": "witch_hut"},
}
FORBIDDEN_HAND_AUDITED_BUILDING_REPLACEMENTS = {
    4: {"arena"},
    23: {"market"},
    41: {"lost_library"},
    47: {"learning_stone"},
    51: {"mercenary_guild"},
    80: {"mereas_shrine"},
    96: {"fickle_shrine"},
    107: {"arena"},
    113: {"university"},
}
MINILM_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_EMBEDDING_DIMENSION = 384
MINILM_ACCEPTANCE_THRESHOLD = 0.52
MINILM_REJECT_THRESHOLD = 0.54
MINILM_MIN_ACCEPTANCE_MARGIN = 0.03
MINILM_SCORE_TOLERANCE = 0.00001
EXPECTED_ARTIFACT_EFFECT_SHAPE_SUBSTITUTIONS: dict[str, dict[str, Any]] = {}
EXPECTED_CREATURE_GENERATOR_SUBSTITUTIONS = {
    "AVGcros0.def": {"replacementSid": "homm3_landon_barracks_castle_2", "ruleName": "creature_generator_castle_archers_tower", "count": 1, "sampleSourceKeys": ["0:15:45"]},
    "AVGgrff0.def": {"replacementSid": "homm3_landon_barracks_castle_3", "ruleName": "creature_generator_castle_griffin_tower", "count": 1, "sampleSourceKeys": ["0:59:31"]},
    "AVGmonk0.def": {"replacementSid": "homm3_landon_barracks_castle_5", "ruleName": "creature_generator_castle_monastery", "count": 1, "sampleSourceKeys": ["0:19:26"]},
    "AVGpike0.def": {"replacementSid": "homm3_landon_barracks_castle_1", "ruleName": "creature_generator_castle_guardhouse", "count": 2, "sampleSourceKeys": ["0:18:34", "0:65:48"]},
    "AVGswor0.def": {"replacementSid": "homm3_landon_barracks_castle_4", "ruleName": "creature_generator_castle_barracks", "count": 1, "sampleSourceKeys": ["0:45:25"]},
}
EXPECTED_RANDOM_ARTIFACT_IDS = {65, 66, 67, 68, 69}
EXPECTED_FIXED_CREATURE_GENERATOR_IDS = {17, 18, 19, 20}
EXPECTED_RANDOM_MONSTER_IDS = {54, 71, 72, 73, 74, 75, 162, 163, 164}
EXPECTED_RANDOM_ARTIFACT_RULES = {
    "AVArnd1.def": 66,
    "AVArnd2.def": 67,
    "AVArnd3.def": 68,
}

EXPECTED_HAND_AUDITED_MINILM_EVIDENCE = {
    4: {"sourceName": "Arena", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["defence", "offence"], "badControls": {"arena"}},
    23: {"sourceName": "Marletto Tower", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["defence"], "badControls": {"market"}},
    41: {"sourceName": "Library of Enlightenment", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["defence", "intelligence", "offence", "spellPower"], "badControls": {"lost_library"}},
    47: {"sourceName": "School of Magic", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["intelligence", "spellPower"], "badControls": {"learning_stone"}},
    51: {"sourceName": "Mercenary Camp", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["offence"], "badControls": {"mercenary_guild"}},
    96: {"sourceName": "Temple", "requiredTargetLogicSourceTokens": ["buff_banks"], "requiredRewardTypes": ["HeroBuffReward"], "requiredTargetStats": [], "requiredBuffParameters": ["quixs_path_buff"], "badControls": {"fickle_shrine"}},
    107: {"sourceName": "School of War", "requiredTargetLogicSourceTokens": ["stats_banks"], "requiredRewardTypes": ["HeroStatsReward"], "requiredTargetStats": ["defence", "offence"], "badControls": {"arena"}},
    113: {"sourceName": "Witch Hut", "requiredTargetLogicSourceTokens": ["skill_banks"], "requiredRewardTypes": ["HeroSkillAdditionReward"], "requiredTargetStats": [], "requiredSkillParameterPrefix": "skill_", "minimumSkillParameterCount": 3, "badControls": {"university"}},
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:  # pragma: no cover
        errors.append(f"cannot read {path}: {ex}")
        return {}


def normalized_json(path: Path, errors: list[str]) -> Any:
    data = read_json(path, errors)
    if not data:
        return None
    return json.loads(json.dumps(data, sort_keys=True))


def load_minilm_model(repo_root: Path, errors: list[str]) -> Any | None:
    os.environ.setdefault("HF_HOME", str(repo_root / ".cache" / "huggingface"))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(repo_root / ".cache" / "sentence_transformers"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        import torch
        from sentence_transformers import SentenceTransformer

        if not torch.cuda.is_available():
            raise RuntimeError(
                "MiniLM substitution validation requires CUDA; "
                f"torch={torch.__version__} cuda.is_available=False. "
                "Install a CUDA torch build (e.g. cu128) — CPU fallback is forbidden."
            )
        model = SentenceTransformer(MINILM_MODEL_NAME, device="cuda")
    except Exception as ex:
        errors.append(f"cannot load MiniLM model {MINILM_MODEL_NAME}: {ex}")
        return None
    dimension = model.get_embedding_dimension() if hasattr(model, "get_embedding_dimension") else model.get_sentence_embedding_dimension()
    if dimension != MINILM_EMBEDDING_DIMENSION:
        errors.append(f"MiniLM embedding dimension drift: {dimension} != {MINILM_EMBEDDING_DIMENSION}")
        return None
    return model


def recompute_minilm_score(model: Any, source_text: str, target_text: str) -> float:
    import numpy as np

    embeddings = model.encode([source_text, target_text], normalize_embeddings=True)
    return float(np.dot(embeddings[0], embeddings[1]))


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
        if "tr" in animation:
            return "tree"
        return "terrain_animation_classification_required"
    return TERRAIN_OBJECT_ROLES.get(template_id)


def validate_terrain_biome_substitution(entry: dict[str, Any], source_rows: list[dict[str, Any]], layer_tiles: dict[int, list[int]], valid_ids: set[str], errors: list[str]) -> None:
    roles = [terrain_role_for_row(row) for row in source_rows]
    if not any(role is not None for role in roles):
        return
    require(all(role is not None for role in roles), f"terrain substitution contains unclassified terrain role: {entry.get('sourceSignature')}", errors)
    overrides = entry.get("placementOverrides")
    require(entry.get("placementOverridesRequired") is True, f"terrain substitution must require placement overrides: {entry.get('sourceSignature')}", errors)
    require(isinstance(overrides, list), f"terrain substitution must contain placementOverrides list: {entry.get('sourceSignature')}", errors)
    if not isinstance(overrides, list):
        return
    override_indexes: list[Any] = []
    overrides_by_index: dict[Any, dict[str, Any]] = {}
    for override in overrides:
        require(isinstance(override, dict), f"terrain substitution override must be object for {entry.get('sourceSignature')}: {override}", errors)
        if not isinstance(override, dict):
            continue
        source_index = override.get("sourceIndex")
        require(isinstance(source_index, int), f"terrain substitution override sourceIndex must be integer for {entry.get('sourceSignature')}: {override}", errors)
        override_indexes.append(source_index)
        if isinstance(source_index, int) and source_index not in overrides_by_index:
            overrides_by_index[source_index] = override
    require(len(override_indexes) == len(set(override_indexes)), f"terrain substitution overrides contain duplicate sourceIndex values for {entry.get('sourceSignature')}: {override_indexes}", errors)
    expected_indexes = [row.get("sourceIndex") for row in source_rows]
    require(Counter(override_indexes) == Counter(expected_indexes), f"terrain substitution overrides must exactly cover source indexes for {entry.get('sourceSignature')}: {sorted(str(key) for key in override_indexes)} != {sorted(str(key) for key in expected_indexes)}", errors)
    for row in source_rows:
        source_key = row.get("sourceKey")
        source_index = row.get("sourceIndex")
        override = overrides_by_index.get(source_index)
        require(isinstance(override, dict), f"terrain substitution missing override for sourceIndex {source_index}", errors)
        if not isinstance(override, dict):
            continue
        require(override.get("sourceKey") == source_key, f"terrain override sourceKey mismatch for sourceIndex {source_index}: {override.get('sourceKey')} != {source_key}", errors)
        role = terrain_role_for_row(row)
        context = source_terrain_context([row], layer_tiles)
        dominant_biome = context.get("dominantBiome")
        expected_replacement = (BIOME_ROLE_REPLACEMENTS.get(role) or {}).get(dominant_biome) if isinstance(role, str) and isinstance(dominant_biome, str) else None
        evidence = override.get("semanticEvidence")
        require(isinstance(evidence, dict), f"terrain override must carry source terrain evidence: {entry.get('sourceSignature')} {source_key}", errors)
        if not isinstance(evidence, dict):
            continue
        if expected_replacement is None and isinstance(role, str) and role in BIOME_ROLE_REPLACEMENTS:
            # Border-overhang anchors default to grass scenery family.
            expected_border = (BIOME_ROLE_REPLACEMENTS.get(role) or {}).get("grass")
            require(override.get("replacementSid") == expected_border, f"border-overhang terrain override must use grass default for {entry.get('sourceSignature')} {source_key}", errors)
            require(override.get("confidence") == "source_tile_biome", f"border-overhang terrain override confidence mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(override.get("ruleName") == f"terrain_biome_{role}_grass", f"border-overhang terrain override rule mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(isinstance(evidence, dict) and evidence.get("borderOverhangDefaultBiome") is True, f"border-overhang terrain override must mark default biome: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("method") == "source_tile_biome_role_mapping", f"terrain override evidence method mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("role") == role, f"terrain override evidence role mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("biome") == "grass", f"border-overhang terrain override evidence biome mismatch: {entry.get('sourceSignature')} {source_key}", errors)
        elif expected_replacement is None:
            require(override.get("replacementSid") is None, f"terrain override without source tile context must stay blocked: {entry.get('sourceSignature')} {source_key}", errors)
            require(override.get("confidence") == "blocked", f"terrain override without source tile context must use blocked confidence: {entry.get('sourceSignature')} {source_key}", errors)
            require(str(override.get("ruleName")).startswith("terrain_biome_missing_"), f"terrain override without replacement must use explicit blocked rule: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("method") == "source_tile_biome_role_mapping", f"terrain override evidence method mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("role") == role, f"terrain override evidence role mismatch: {entry.get('sourceSignature')} {source_key}", errors)
        else:
            require(override.get("confidence") == "source_tile_biome", f"terrain override must use source_tile_biome confidence: {entry.get('sourceSignature')} {source_key}", errors)
            require(override.get("ruleName") == f"terrain_biome_{role}_{dominant_biome}", f"terrain override rule must encode role and row biome: {entry.get('sourceSignature')} {source_key}", errors)
            require(override.get("replacementSid") == expected_replacement, f"terrain override replacement does not match row biome role table for {entry.get('sourceSignature')} {source_key}: {override.get('replacementSid')} != {expected_replacement}", errors)
            require(expected_replacement in valid_ids, f"terrain override expected replacement is not whitelisted: {expected_replacement}", errors)
            require(evidence.get("candidateReplacementSid") == expected_replacement and evidence.get("candidateWhitelisted") is True, f"terrain override whitelist proof mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("method") == "source_tile_biome_role_mapping", f"terrain override evidence method mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("role") == role, f"terrain override evidence role mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("dominantBiome") == dominant_biome, f"terrain override evidence dominant biome mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("terrainHistogram") == context.get("terrainHistogram"), f"terrain override evidence terrain histogram mismatch: {entry.get('sourceSignature')} {source_key}", errors)
            require(evidence.get("biomeHistogram") == context.get("biomeHistogram"), f"terrain override evidence biome histogram mismatch: {entry.get('sourceSignature')} {source_key}", errors)


def normalize_relpath(value: Any) -> str:
    return str(value).replace("\\\\", "/")


def signature_for(entity: dict[str, Any]) -> str:
    return "|".join(
        str(entity.get(key, ""))
        for key in ["sid", "templateObjectId", "templateAnimation", "category", "payloadKind"]
    )


def run_generation(repo_root: Path, errors: list[str]) -> Path | None:
    script = repo_root / GENERATOR
    require(script.exists(), f"missing entity substitution generator: {script}", errors)
    if not script.exists():
        return None
    out_root = repo_root / "artifacts" / "campaign_port_poc" / "validator_tmp" / "homecoming_entity_substitutions"
    if out_root.exists():
        import shutil
        shutil.rmtree(out_root)
    env = dict(os.environ)
    env["HOMECOMING_POC_OUT_ROOT"] = str(out_root)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        errors.append(f"{GENERATOR} failed with exit {result.returncode}:\n{result.stdout}")
        return None
    return out_root / "entity_substitutions" / "homecoming.olden_entity_substitution_map.json"


def validate_mapping(repo_root: Path, errors: list[str], mapping_path: Path, *, verify_minilm_scores: bool) -> None:
    alignment = read_json(repo_root / ALIGNMENT_PATH, errors)
    core_catalog = read_json(repo_root / CORE_CATALOG_PATH, errors)
    mapping = read_json(mapping_path, errors)
    if not alignment or not core_catalog or not mapping:
        return

    # One whitelist with the generator: a hand-copied custom-id list here drifted (it lacked the
    # all-faction barracks SIDs and homm3_seer_hut) and made validEntityCount mismatch.
    import build_homecoming_entity_substitution_map as substitution_generator

    valid_ids = substitution_generator.valid_entity_ids(core_catalog)
    require(len(valid_ids) > 0, "valid Olden entity whitelist must not be empty", errors)
    minilm_model = load_minilm_model(repo_root, errors) if verify_minilm_scores else None

    entities = (((alignment.get("alignment") or {}).get("globalObjectProperties") or {}).get("propEntities") or [])
    layer_tiles = load_layer_tiles(alignment)
    require(isinstance(entities, list), "alignment global propEntities must be list", errors)
    by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        if isinstance(entity, dict):
            by_signature[signature_for(entity)].append(entity)

    invalid_signatures = {
        signature
        for signature, rows in by_signature.items()
        if rows and rows[0].get("sid") not in valid_ids
    }

    require(mapping.get("schema") == SCHEMA, f"mapping schema mismatch: {mapping.get('schema')}", errors)
    require(mapping.get("status") == STATUS, f"mapping status mismatch: {mapping.get('status')}", errors)
    require(mapping.get("programmaticGeneration") is True, "mapping must mark programmaticGeneration=true", errors)
    require(mapping.get("silentFallbacksUsed") is False, "mapping must mark silentFallbacksUsed=false", errors)
    require(mapping.get("whitelistKind") == "olden_core_map_valid_entity_catalog.mapObjects.id+homecoming_generated", "mapping whitelistKind mismatch", errors)
    require(normalize_relpath(mapping.get("sourceAlignment")) == normalize_relpath(ALIGNMENT_PATH), "mapping sourceAlignment mismatch", errors)
    require(normalize_relpath(mapping.get("sourceWhitelist")) == normalize_relpath(CORE_CATALOG_PATH), "mapping sourceWhitelist mismatch", errors)
    require(mapping.get("validEntityCount") == len(valid_ids), "mapping validEntityCount mismatch", errors)
    require(mapping.get("sourceEntityCount") == len(entities), "mapping sourceEntityCount mismatch", errors)
    require(mapping.get("distinctSourceSignatureCount") == len(by_signature), "mapping distinctSourceSignatureCount mismatch", errors)
    require(mapping.get("invalidSignatureCount") == len(invalid_signatures), "mapping invalidSignatureCount mismatch", errors)
    require(mapping.get("lossyPlaceholderRules") == sorted(LOSSY_PLACEHOLDER_RULES), "lossyPlaceholderRules mismatch", errors)

    substitutions = mapping.get("invalidEntitySubstitutions") or []
    require(isinstance(substitutions, list), "invalidEntitySubstitutions must be list", errors)
    seen = set()
    replacement_hist = Counter()
    rule_hist = Counter()
    lossiness_hist = Counter()
    for index, entry in enumerate(substitutions):
        require(isinstance(entry, dict), f"invalidEntitySubstitutions[{index}] must be object", errors)
        if not isinstance(entry, dict):
            continue
        signature = entry.get("sourceSignature")
        replacement = entry.get("replacementSid")
        source_sid = entry.get("sourceSid")
        require(signature in invalid_signatures, f"substitution has stale or unknown sourceSignature: {signature}", errors)
        require(signature not in seen, f"duplicate substitution sourceSignature: {signature}", errors)
        seen.add(signature)
        rule_name = entry.get("ruleName")
        confidence = entry.get("confidence")
        is_blocked = replacement is None
        if is_blocked:
            require(confidence == "blocked", f"blocked substitution must use confidence=blocked for {signature}", errors)
        else:
            require(replacement in valid_ids, f"replacementSid is not whitelisted: {replacement} for {signature}", errors)
            require(replacement not in FORBIDDEN_REPLACEMENTS, f"replacementSid is forbidden: {replacement} for {signature}", errors)
            require(replacement != source_sid, f"invalid substitution keeps same sourceSid: {signature}", errors)
        require(isinstance(rule_name, str) and rule_name, f"substitution missing ruleName: {signature}", errors)
        require(rule_name != "generic_payloadless_decoration", f"generic payloadless decoration rule is forbidden: {signature}", errors)
        require(confidence in CONFIDENCE_VALUES, f"substitution confidence is not recognized: {confidence} for {signature}", errors)
        expected_lossiness = (
            "blocked"
            if is_blocked
            else "lossy_placeholder" if rule_name in LOSSY_PLACEHOLDER_RULES else "direct_or_family_substitution"
        )
        require(entry.get("lossiness") == expected_lossiness, f"substitution lossiness mismatch for {signature}: {entry.get('lossiness')} != {expected_lossiness}", errors)
        require(entry.get("count") == len(by_signature.get(signature, [])), f"substitution count mismatch for {signature}", errors)
        source_rows = by_signature.get(signature, [])
        expected_layers = dict(Counter(str(row.get("sourceLayer")) for row in source_rows))
        expected_animations = dict(Counter(row.get("templateAnimation") for row in source_rows).most_common(8))
        require(entry.get("sourceLayers") == expected_layers, f"substitution sourceLayers mismatch for {signature}", errors)
        require(entry.get("animationHistogram") == expected_animations, f"substitution animationHistogram mismatch for {signature}", errors)
        validate_terrain_biome_substitution(entry, source_rows, layer_tiles, valid_ids, errors)
        require(isinstance(entry.get("sampleSourceKeys"), list) and len(entry.get("sampleSourceKeys")) > 0, f"substitution missing sampleSourceKeys: {signature}", errors)
        if replacement is not None:
            replacement_hist[replacement] += 1
        rule_hist[rule_name] += 1
        lossiness_hist[entry.get("lossiness")] += 1

    missing = invalid_signatures.difference(seen)
    extra = seen.difference(invalid_signatures)
    for template_id, expected in EXPECTED_HAND_AUDITED_BUILDING_SUBSTITUTIONS.items():
        matches = [
            entry for entry in substitutions
            if isinstance(entry, dict)
            and entry.get("templateObjectId") == template_id
            and entry.get("templateAnimation") == expected.get("templateAnimation")
        ]
        require(len(matches) == 1, f"expected exactly one hand-audited building substitution row for template {template_id}, found {len(matches)}", errors)
        if len(matches) != 1:
            continue
        row = matches[0]
        for key, expected_value in expected.items():
            require(row.get(key) == expected_value, f"hand-audited building substitution mismatch for template {template_id} field {key}: {row.get(key)!r}", errors)
        forbidden = FORBIDDEN_HAND_AUDITED_BUILDING_REPLACEMENTS.get(template_id, set())
        require(row.get("replacementSid") not in forbidden, f"hand-audited building template {template_id} regressed to forbidden replacement {row.get('replacementSid')}", errors)
        evidence_expectation = EXPECTED_HAND_AUDITED_MINILM_EVIDENCE.get(template_id)
        if evidence_expectation is not None:
            evidence = row.get("semanticEvidence")
            require(isinstance(evidence, dict), f"hand-audited building template {template_id} must carry MiniLM semanticEvidence", errors)
            if isinstance(evidence, dict):
                require(row.get("confidence") == "minilm_semantic_family", f"hand-audited building template {template_id} must use MiniLM confidence", errors)
                require(evidence.get("method") == "minilm_semantic_description_similarity", f"MiniLM method mismatch for template {template_id}", errors)
                require(evidence.get("model") == MINILM_MODEL_NAME, f"MiniLM model mismatch for template {template_id}", errors)
                require(evidence.get("embeddingDimension") == MINILM_EMBEDDING_DIMENSION, f"MiniLM embedding dimension mismatch for template {template_id}", errors)
                require(evidence.get("acceptanceThreshold") == MINILM_ACCEPTANCE_THRESHOLD, f"MiniLM acceptance threshold mismatch for template {template_id}", errors)
                require(evidence.get("rejectThreshold") == MINILM_REJECT_THRESHOLD, f"MiniLM reject threshold mismatch for template {template_id}", errors)
                require(evidence.get("minimumAcceptanceMargin") == MINILM_MIN_ACCEPTANCE_MARGIN, f"MiniLM margin threshold mismatch for template {template_id}", errors)
                require(evidence.get("sourceName") == evidence_expectation["sourceName"], f"MiniLM source name mismatch for template {template_id}", errors)
                require(isinstance(evidence.get("sourceDescription"), str) and evidence.get("sourceDescription"), f"missing source description for template {template_id}", errors)
                require(isinstance(evidence.get("sourceEmbeddingText"), str) and evidence.get("sourceEmbeddingText"), f"missing source embedding text for template {template_id}", errors)
                target_embedding_text = evidence.get("targetEmbeddingText")
                require(isinstance(target_embedding_text, str) and target_embedding_text, f"missing target embedding text for template {template_id}", errors)
                if minilm_model is not None and isinstance(evidence.get("sourceEmbeddingText"), str) and isinstance(target_embedding_text, str):
                    recomputed_score = round(recompute_minilm_score(minilm_model, evidence["sourceEmbeddingText"], target_embedding_text), 6)
                    require(abs(recomputed_score - float(evidence.get("score", -999.0))) <= MINILM_SCORE_TOLERANCE, f"MiniLM score is not reproducible for template {template_id}: artifact={evidence.get('score')} recomputed={recomputed_score}", errors)
                require(evidence.get("requiredTargetLogicSourceTokens") == evidence_expectation["requiredTargetLogicSourceTokens"], f"MiniLM logic-source filter mismatch for template {template_id}", errors)
                require(evidence.get("requiredRewardTypes") == evidence_expectation["requiredRewardTypes"], f"MiniLM reward-type filter mismatch for template {template_id}", errors)
                require(evidence.get("requiredTargetStats") == evidence_expectation["requiredTargetStats"], f"MiniLM stat filter mismatch for template {template_id}", errors)
                if "requiredBuffParameters" in evidence_expectation:
                    require(evidence.get("requiredBuffParameters") == evidence_expectation["requiredBuffParameters"], f"MiniLM buff filter mismatch for template {template_id}", errors)
                if "requiredSkillParameterPrefix" in evidence_expectation:
                    require(evidence.get("requiredSkillParameterPrefix") == evidence_expectation["requiredSkillParameterPrefix"], f"MiniLM skill-prefix filter mismatch for template {template_id}", errors)
                    require(evidence.get("minimumSkillParameterCount") == evidence_expectation["minimumSkillParameterCount"], f"MiniLM skill-count filter mismatch for template {template_id}", errors)
                require(isinstance(evidence.get("score"), (int, float)) and evidence.get("score") >= MINILM_ACCEPTANCE_THRESHOLD, f"MiniLM score below threshold for template {template_id}: {evidence.get('score')}", errors)
                if evidence.get("candidateCountAfterLogicFilter") == 1:
                    require(evidence.get("nextBestScore") is None and evidence.get("acceptanceMargin") is None, f"single-candidate MiniLM rows must not report synthetic margin for template {template_id}", errors)
                else:
                    require(isinstance(evidence.get("acceptanceMargin"), (int, float)) and evidence.get("acceptanceMargin") >= MINILM_MIN_ACCEPTANCE_MARGIN, f"MiniLM margin below threshold for template {template_id}: {evidence.get('acceptanceMargin')}", errors)
                require(isinstance(evidence.get("candidateCountAfterLogicFilter"), int) and evidence.get("candidateCountAfterLogicFilter") > 0, f"MiniLM candidate count missing for template {template_id}", errors)
                description = evidence.get("targetEnglishDescription")
                require(isinstance(description, str) and description, f"missing target English description evidence for template {template_id}", errors)
                require(isinstance(evidence.get("targetEnglishDescriptionTokenSid"), str) and evidence.get("targetEnglishDescriptionTokenSid"), f"missing target English description token SID for template {template_id}", errors)
                logic_sources = evidence.get("targetLogicSources")
                require(isinstance(logic_sources, list) and logic_sources, f"missing target logic-source evidence for template {template_id}", errors)
                profile = evidence.get("targetLogicProfile")
                require(isinstance(profile, dict), f"missing target logic profile for template {template_id}", errors)
                if isinstance(profile, dict):
                    require(set(evidence_expectation["requiredRewardTypes"]).issubset(set(profile.get("rewardTypes") or [])), f"target reward types do not satisfy MiniLM contract for template {template_id}: {profile}", errors)
                    require((profile.get("statParameters") or []) == evidence_expectation["requiredTargetStats"], f"target stat parameters do not satisfy MiniLM contract for template {template_id}: {profile}", errors)
                    if "requiredBuffParameters" in evidence_expectation:
                        require(set(evidence_expectation["requiredBuffParameters"]).issubset(set(profile.get("buffParameters") or [])), f"target buff parameters do not satisfy MiniLM contract for template {template_id}: {profile}", errors)
                    if "requiredSkillParameterPrefix" in evidence_expectation:
                        skill_parameters = profile.get("skillParameters") or []
                        require(len(skill_parameters) >= evidence_expectation["minimumSkillParameterCount"] and all(str(skill).startswith(evidence_expectation["requiredSkillParameterPrefix"]) for skill in skill_parameters), f"target skill parameters do not satisfy MiniLM contract for template {template_id}: {profile}", errors)
                top_candidates = evidence.get("topCandidates")
                require(isinstance(top_candidates, list) and top_candidates and top_candidates[0].get("sid") == row.get("replacementSid"), f"MiniLM top candidate must be replacement for template {template_id}", errors)
                controls = evidence.get("badControls")
                require(isinstance(controls, list) and {control.get("sid") for control in controls} == evidence_expectation["badControls"], f"MiniLM bad controls mismatch for template {template_id}: {controls}", errors)
                if isinstance(controls, list):
                    for control in controls:
                        score = control.get("score")
                        require(isinstance(control.get("targetEnglishDescription"), str) and control.get("targetEnglishDescription"), f"MiniLM bad control target text missing for template {template_id}: {control}", errors)
                        require(isinstance(score, (int, float)), f"MiniLM bad control score missing for template {template_id}: {control}", errors)
                        if minilm_model is not None and isinstance(evidence.get("sourceEmbeddingText"), str) and isinstance(control.get("targetEnglishName"), str) and isinstance(control.get("targetEnglishDescription"), str):
                            control_target_text = f"{control['targetEnglishName']}. {control['targetEnglishDescription']}"
                            recomputed_control = round(recompute_minilm_score(minilm_model, evidence["sourceEmbeddingText"], control_target_text), 6)
                            require(abs(recomputed_control - float(score)) <= MINILM_SCORE_TOLERANCE, f"MiniLM bad-control score is not reproducible for template {template_id}: {control} recomputed={recomputed_control}", errors)
                        passes_filters = control.get("passesLogicSourceFilter") and control.get("passesStructuredLogicFilter")
                        require(not (passes_filters and isinstance(score, (int, float)) and score > MINILM_REJECT_THRESHOLD), f"MiniLM bad control passes threshold and filters for template {template_id}: {control}", errors)

    for animation, expected in EXPECTED_ARTIFACT_EFFECT_SHAPE_SUBSTITUTIONS.items():
        matches = [
            entry for entry in substitutions
            if isinstance(entry, dict)
            and entry.get("templateAnimation") == animation
            and entry.get("category") == "artifact_pickup"
            and entry.get("payloadKind") == "artifact"
        ]
        require(len(matches) == 1, f"expected exactly one fixed artifact effect-shape substitution for {animation}, found {len(matches)}", errors)
        if len(matches) != 1:
            continue
        row = matches[0]
        require(row.get("replacementSid") == expected["replacementSid"], f"artifact {animation} replacement mismatch: {row.get('replacementSid')!r}", errors)
        require(row.get("ruleName") == expected["ruleName"], f"artifact {animation} rule mismatch: {row.get('ruleName')!r}", errors)
        require(row.get("confidence") == expected["confidence"], f"artifact {animation} confidence mismatch: {row.get('confidence')!r}", errors)
        require(row.get("lossiness") == "direct_or_family_substitution", f"artifact {animation} must not be marked lossy placeholder", errors)
        evidence = row.get("semanticEvidence")
        require(isinstance(evidence, dict), f"artifact {animation} must carry artifact effect-shape evidence", errors)
        if not isinstance(evidence, dict):
            continue
        require(evidence.get("method") == "artifact_effect_shape_similarity", f"artifact {animation} evidence method mismatch", errors)
        require(evidence.get("sourceSubtype") == expected["sourceSubtype"], f"artifact {animation} subtype mismatch", errors)
        require(evidence.get("sourceName") == expected["sourceName"], f"artifact {animation} sourceName mismatch", errors)
        require(evidence.get("sourceEffects") == expected["sourceEffects"], f"artifact {animation} sourceEffects mismatch: {evidence.get('sourceEffects')}", errors)
        if "sourceSlotHint" in expected:
            require(evidence.get("sourceSlotHint") == expected["sourceSlotHint"], f"artifact {animation} sourceSlotHint mismatch", errors)
        if expected["replacementSid"] is None:
            require(evidence.get("blockedReason") == expected["blockedReason"], f"artifact {animation} blocked reason mismatch", errors)
            require("targetEffects" not in evidence, f"blocked artifact {animation} must not report target effects", errors)
        else:
            require(evidence.get("targetEffects") == expected["targetEffects"], f"artifact {animation} targetEffects mismatch: {evidence.get('targetEffects')}", errors)
            require(isinstance(evidence.get("score"), (int, float)), f"artifact {animation} score missing", errors)
            top_candidates = evidence.get("topCandidates")
            require(isinstance(top_candidates, list) and top_candidates and top_candidates[0].get("sid") == expected["replacementSid"], f"artifact {animation} top candidate must be selected replacement", errors)
            if isinstance(top_candidates, list) and top_candidates:
                require(top_candidates[0].get("targetEffects") == expected["targetEffects"], f"artifact {animation} top target effects mismatch", errors)

    require(h3obj.RANDOM_ARTIFACT_OBJECT_IDS == EXPECTED_RANDOM_ARTIFACT_IDS, f"random artifact registry mismatch: {sorted(h3obj.RANDOM_ARTIFACT_OBJECT_IDS)}", errors)
    require(h3obj.FIXED_CREATURE_GENERATOR_IDS == EXPECTED_FIXED_CREATURE_GENERATOR_IDS, f"fixed creature generator registry mismatch: {sorted(h3obj.FIXED_CREATURE_GENERATOR_IDS)}", errors)
    require(h3obj.MONSTER_OBJECT_IDS == EXPECTED_RANDOM_MONSTER_IDS, f"monster registry mismatch: {sorted(h3obj.MONSTER_OBJECT_IDS)}", errors)

    fixed_generator_artifact_rows = [
        entry for entry in substitutions
        if isinstance(entry, dict)
        and entry.get("templateObjectId") in h3obj.FIXED_CREATURE_GENERATOR_IDS
        and (
            entry.get("category") == "artifact_pickup"
            or entry.get("payloadKind") == "artifact"
            or (isinstance(entry.get("semanticEvidence"), dict) and entry["semanticEvidence"].get("method") == "artifact_effect_shape_similarity")
        )
    ]
    require(not fixed_generator_artifact_rows, f"fixed creature generators must never use artifact substitution semantics: {len(fixed_generator_artifact_rows)} rows", errors)

    random_hero_artifact_rows = [
        entry for entry in substitutions
        if isinstance(entry, dict)
        and entry.get("templateObjectId") == h3obj.OBJECT_RANDOM_HERO
        and (
            entry.get("category") == "artifact_pickup"
            or entry.get("payloadKind") == "artifact"
            or (isinstance(entry.get("semanticEvidence"), dict) and entry["semanticEvidence"].get("method") == "artifact_effect_shape_similarity")
        )
    ]
    require(not random_hero_artifact_rows, f"random hero object id 70 must never use artifact substitution semantics: {len(random_hero_artifact_rows)} rows", errors)

    for animation, expected in EXPECTED_CREATURE_GENERATOR_SUBSTITUTIONS.items():
        matches = [
            entry for entry in substitutions
            if isinstance(entry, dict)
            and entry.get("templateObjectId") in h3obj.FIXED_CREATURE_GENERATOR_IDS
            and entry.get("templateAnimation") == animation
        ]
        require(len(matches) == 1, f"expected exactly one creature-generator substitution for {animation}, found {len(matches)}", errors)
        if len(matches) != 1:
            continue
        row = matches[0]
        require(row.get("templateObjectId") == h3obj.OBJECT_CREATURE_GENERATOR_1, f"Homecoming creature generator {animation} template id mismatch: {row.get('templateObjectId')}", errors)
        require(row.get("category") == "external_dwelling", f"creature generator {animation} category mismatch: {row.get('category')}", errors)
        require(row.get("payloadKind") == "creature_generator", f"creature generator {animation} payload mismatch: {row.get('payloadKind')}", errors)
        require(row.get("replacementSid") == expected["replacementSid"], f"creature generator {animation} replacement mismatch: {row.get('replacementSid')}", errors)
        require(row.get("ruleName") == expected["ruleName"], f"creature generator {animation} rule mismatch: {row.get('ruleName')}", errors)
        require(row.get("confidence") == "role_and_visual", f"creature generator {animation} confidence mismatch: {row.get('confidence')}", errors)
        require(row.get("lossiness") == "direct_or_family_substitution", f"creature generator {animation} must not be marked lossy", errors)
        require(row.get("count") == expected["count"], f"creature generator {animation} count mismatch: {row.get('count')}", errors)
        require(row.get("sampleSourceKeys") == expected["sampleSourceKeys"], f"creature generator {animation} sampleSourceKeys mismatch: {row.get('sampleSourceKeys')}", errors)
        evidence = row.get("semanticEvidence")
        require(isinstance(evidence, dict), f"creature generator {animation} must carry exact-animation evidence", errors)
        if isinstance(evidence, dict):
            require(evidence.get("method") == "creature_generator_exact_animation", f"creature generator {animation} evidence method mismatch", errors)
            require(evidence.get("replacementSid") == expected["replacementSid"], f"creature generator {animation} evidence replacement mismatch", errors)
            require(evidence.get("ruleName") == expected["ruleName"], f"creature generator {animation} evidence rule mismatch", errors)
            require(evidence.get("generatorFamily") == "creature_generator_1", f"creature generator {animation} evidence generatorFamily mismatch", errors)
            require(evidence.get("owner") == 255, f"creature generator {animation} evidence owner mismatch: {evidence.get('owner')}", errors)
            require(evidence.get("ownerEncoding") == "h3m_readPlayer32", f"creature generator {animation} evidence ownerEncoding mismatch", errors)
            decoder_evidence = evidence.get("payloadDecoderEvidence")
            require(isinstance(decoder_evidence, dict), f"creature generator {animation} must carry payload decoder evidence", errors)
            if isinstance(decoder_evidence, dict):
                require(decoder_evidence.get("vcmiReader") == "CMapLoaderH3M::readDwelling", f"creature generator {animation} decoder reader mismatch", errors)
                require(decoder_evidence.get("payloadShape") == "readPlayer32 owner only", f"creature generator {animation} decoder payload shape mismatch", errors)
    expected_random_artifact_rules = {
        h3obj.OBJECT_RANDOM_ARTIFACT: "random_artifact_any_to_random_item",
        h3obj.OBJECT_RANDOM_ARTIFACT_TREASURE: "random_artifact_treasure_to_random_item",
        h3obj.OBJECT_RANDOM_ARTIFACT_MINOR: "random_artifact_minor_to_random_item",
        h3obj.OBJECT_RANDOM_ARTIFACT_MAJOR: "random_artifact_major_to_random_item",
        h3obj.OBJECT_RANDOM_ARTIFACT_RELIC: "random_artifact_relic_to_random_item",
    }
    for animation, template_id in EXPECTED_RANDOM_ARTIFACT_RULES.items():
        matches = [
            entry for entry in substitutions
            if isinstance(entry, dict)
            and entry.get("templateAnimation") == animation
            and entry.get("category") == "artifact_pickup"
            and entry.get("payloadKind") == "artifact"
        ]
        require(len(matches) == 1, f"expected exactly one random artifact substitution for {animation}, found {len(matches)}", errors)
        if len(matches) != 1:
            continue
        row = matches[0]
        require(row.get("templateObjectId") == template_id, f"random artifact {animation} template ID mismatch", errors)
        require(row.get("replacementSid") == "random-item", f"random artifact {animation} must map to random-item", errors)
        require(
            row.get("ruleName") == expected_random_artifact_rules[template_id],
            f"random artifact {animation} rule mismatch: {row.get('ruleName')}",
            errors,
        )
        require(row.get("confidence") == "role", f"random artifact {animation} confidence mismatch", errors)
        require(row.get("lossiness") == "direct_or_family_substitution", f"random artifact {animation} lossiness mismatch", errors)
        evidence = row.get("semanticEvidence")
        require(isinstance(evidence, dict), f"random artifact {animation} must carry rarity evidence", errors)
        if isinstance(evidence, dict):
            require(template_id in h3obj.RANDOM_ARTIFACT_OBJECT_IDS, f"random artifact {animation} template id {template_id} is not in registry", errors)
            require(template_id != h3obj.OBJECT_RANDOM_HERO, f"random artifact {animation} must not use random hero id 70", errors)
            require(evidence.get("method") == "random_artifact_rarity_table", f"random artifact {animation} evidence method mismatch", errors)

    require(not missing, f"missing substitutions for invalid signatures: {sorted(missing)[:20]}", errors)
    require(not extra, f"extra substitutions for non-current signatures: {sorted(extra)[:20]}", errors)
    require(mapping.get("replacementSidHistogram") == dict(replacement_hist.most_common()), "replacementSidHistogram mismatch", errors)
    require(mapping.get("ruleHistogram") == dict(rule_hist.most_common()), "ruleHistogram mismatch", errors)
    require(mapping.get("lossinessHistogram") == dict(lossiness_hist.most_common()), "lossinessHistogram mismatch", errors)
    require(mapping.get("blockedSubstitutionCount") == 0, "blockedSubstitutionCount must be zero for semantic coverage clearance", errors)
    blocked_lossiness_count = lossiness_hist.get("blocked", 0)
    require(blocked_lossiness_count == 0, f"substitution map must have zero lossiness=blocked entries, found {blocked_lossiness_count}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Deprecated compatibility flag. Persisted-map validation is now the default.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Explicit audit mode: regenerate the substitution map into validator_tmp and compare it to the persisted map.",
    )
    parser.add_argument(
        "--verify-minilm-scores",
        action="store_true",
        help="Load MiniLM and recompute stored semantic scores. Intended for deliberate mapping audits, not normal build/deploy.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    shared_mapping_path = repo_root / OUTPUT_PATH
    if args.skip_generate and args.regenerate:
        errors.append("--skip-generate and --regenerate are mutually exclusive")
    regenerate = bool(args.regenerate)
    verify_minilm_scores = bool(args.verify_minilm_scores)
    validate_mapping(repo_root, errors, shared_mapping_path, verify_minilm_scores=verify_minilm_scores)
    if regenerate:
        generated_mapping_path = run_generation(repo_root, errors)
        if generated_mapping_path is not None:
            validate_mapping(repo_root, errors, generated_mapping_path, verify_minilm_scores=verify_minilm_scores)
            shared = normalized_json(shared_mapping_path, errors)
            generated = normalized_json(generated_mapping_path, errors)
            if shared is not None and generated is not None:
                require(shared == generated, "shared substitution map does not match freshly generated temp output", errors)

    if errors:
        print("Homecoming entity substitution map contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming entity substitution map contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
