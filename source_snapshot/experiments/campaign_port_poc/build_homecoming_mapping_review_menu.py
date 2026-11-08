#!/usr/bin/env python3
"""Build a browser-based review menu for Homecoming HoMM3->Olden building mappings."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSTITUTION_PATH = REPO_ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "entity_substitutions" / "homecoming.olden_entity_substitution_map.json"
CORE_CATALOG_PATH = REPO_ROOT / "artifacts" / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"
CHECKPOINT_PATH = REPO_ROOT / "experiments" / "campaign_port_poc" / "homecoming_mapping_review_checkpoint.json"
ALIGNMENT_PATH = REPO_ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"
OUT_DIR = Path(os.environ.get("HOMECOMING_MAPPING_REVIEW_OUT_DIR", REPO_ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "mapping_review"))
SEED_JSON_PATH = OUT_DIR / "homecoming_building_mapping_review_seed.json"
HTML_PATH = OUT_DIR / "homecoming_building_mapping_review.html"
ENGLISH_MAP_OBJECT_TEXT = "Lang/english/texts/mapObjects.json"
ENGLISH_ARTIFACT_TEXT = "Lang/english/texts/artifacts.json"
OBJECT_CONFIG_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
LOGIC_CONFIG_CACHE: dict[tuple[str, str], dict[str, Any]] = {}

SOURCE_BUILDING_FUNCTIONS: dict[int, dict[str, Any]] = {
    4: {"sourceName": "Arena", "sourceFunction": "Permanently trains the visiting hero to increase Attack or Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    23: {"sourceName": "Marletto Tower", "sourceFunction": "Permanently increases the visiting hero's Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    31: {"sourceName": "Fountain of Youth", "sourceFunction": "Grants a temporary morale benefit and extra movement to the visiting hero.", "sourceFunctionConfidence": "needs_h3_primary_source_review"},
    41: {"sourceName": "Library of Enlightenment", "sourceFunction": "Permanently increases Attack, Defense, Spell Power, and Knowledge for an experienced visiting hero.", "sourceFunctionConfidence": "current_mapper_seed"},
    47: {"sourceName": "School of Magic", "sourceFunction": "Lets the visiting hero choose a permanent increase to Spell Power or Knowledge.", "sourceFunctionConfidence": "current_mapper_seed"},
    51: {"sourceName": "Mercenary Camp", "sourceFunction": "Permanently increases the visiting hero's Attack.", "sourceFunctionConfidence": "current_mapper_seed"},
    80: {"sourceName": "Sanctuary", "sourceFunction": "Protects the visiting hero from being attacked while occupying the object.", "sourceFunctionConfidence": "needs_h3_primary_source_review"},
    96: {"sourceName": "Temple", "sourceFunction": "Blesses the visiting hero with extra Morale for a limited time.", "sourceFunctionConfidence": "current_mapper_seed"},
    107: {"sourceName": "School of War", "sourceFunction": "Lets the visiting hero choose a permanent increase to Attack or Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    113: {"sourceName": "Witch Hut", "sourceFunction": "Teaches the visiting hero a random secondary skill.", "sourceFunctionConfidence": "current_mapper_seed"},
}


EXCLUDED_HOMECOMING_REVIEW_CATEGORIES = {
    "payloadless_object_unclassified_for_current_scope",
}
FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS = {30, 32, 39, 49, 94, 100, 101, 102, 104, 107, 109, 112}


def is_reviewable_homecoming_substitution(entry: dict[str, Any]) -> bool:
    if entry.get("category") not in EXCLUDED_HOMECOMING_REVIEW_CATEGORIES:
        return True
    return entry.get("templateObjectId") in FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS

HOMM3_BUILDING_CATALOG_EXTENSION: list[dict[str, Any]] = [
    {"templateObjectId": 30, "templateAnimation": "catalog:fountain", "sourceName": "Fountain", "sourceFunction": "HoMM3 adventure-map fountain object; exact visit reward needs primary-source confirmation.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "fountain", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 32, "templateAnimation": "catalog:garden", "sourceName": "Garden of Revelation", "sourceFunction": "HoMM3 adventure-map knowledge garden object; exact visit reward needs primary-source confirmation.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "knowledge_garden", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 39, "templateAnimation": "catalog:learning_stone", "sourceName": "Learning Stone", "sourceFunction": "Grants experience to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "learning_stone", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 49, "templateAnimation": "catalog:magic_well", "sourceName": "Magic Well", "sourceFunction": "Restores spell points for the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "mana_well", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 94, "templateAnimation": "catalog:stables", "sourceName": "Stables", "sourceFunction": "Increases the visiting hero's adventure movement for the rest of the week.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "stables", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 100, "templateAnimation": "catalog:gazebo", "sourceName": "Gazebo", "sourceFunction": "Grants experience to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "learning_stone", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 101, "templateAnimation": "catalog:treasure_chest", "sourceName": "Treasure Chest", "sourceFunction": "Lets the visiting hero choose between gold and experience.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "chest", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 102, "templateAnimation": "catalog:tree_of_knowledge", "sourceName": "Tree of Knowledge", "sourceFunction": "Can grant the visiting hero a level for a requested cost or condition.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "tree_of_knowledge", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 104, "templateAnimation": "catalog:university", "sourceName": "University", "sourceFunction": "Lets the visiting hero buy secondary skills from an offered set.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "university", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 109, "templateAnimation": "catalog:windmill", "sourceName": "Windmill", "sourceFunction": "Provides a weekly random resource reward to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "windmill", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": 112, "templateAnimation": "catalog:wind_object", "sourceName": "Windmill Variant", "sourceFunction": "Provides a weekly random resource reward to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed", "proposedReplacementSid": "windmill", "currentRuleName": "catalog_extension_exact_template_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:black_market", "sourceName": "Black Market", "sourceFunction": "Sells artifacts to the visiting hero; exact Olden equivalent needs review.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "market", "currentRuleName": "catalog_extension_preliminary_name_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:hill_fort", "sourceName": "Hill Fort", "sourceFunction": "Upgrades eligible creatures in the visiting hero army; no direct map-only Olden equivalent has been proven.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": None, "currentRuleName": "catalog_extension_no_direct_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:trading_post", "sourceName": "Trading Post", "sourceFunction": "Provides marketplace-style resource trading outside a town; exact Olden equivalent needs review.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "market", "currentRuleName": "catalog_extension_preliminary_name_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:freelancers_guild", "sourceName": "Freelancer's Guild", "sourceFunction": "Lets the visiting hero exchange creatures for resources; no direct map-only Olden equivalent has been proven.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": None, "currentRuleName": "catalog_extension_no_direct_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:war_machine_factory", "sourceName": "War Machine Factory", "sourceFunction": "Sells war machines to the visiting hero; no direct map-only Olden equivalent has been proven.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": None, "currentRuleName": "catalog_extension_no_direct_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:magic_spring", "sourceName": "Magic Spring", "sourceFunction": "Restores and can temporarily increase the visiting hero spell points; exact Olden equivalent needs review.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "mana_well", "currentRuleName": "catalog_extension_preliminary_function_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:faerie_ring", "sourceName": "Faerie Ring", "sourceFunction": "Grants a temporary luck benefit to the visiting hero; exact Olden equivalent needs review.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "fairy_ring", "currentRuleName": "catalog_extension_preliminary_name_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:redwood_observatory", "sourceName": "Redwood Observatory", "sourceFunction": "Reveals nearby terrain for the visiting player; exact Olden equivalent needs review.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": "orb_observatory", "currentRuleName": "catalog_extension_preliminary_name_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:seers_hut", "sourceName": "Seer's Hut", "sourceFunction": "Gives a quest and reward contract to the visiting hero; no direct map-only Olden equivalent has been proven.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": None, "currentRuleName": "catalog_extension_no_direct_seed"},
    {"templateObjectId": None, "templateAnimation": "catalog:keymasters_tent", "sourceName": "Keymaster's Tent", "sourceFunction": "Unlocks matching border gates for the visiting player; no direct Olden route-gate equivalent has been proven.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension", "proposedReplacementSid": None, "currentRuleName": "catalog_extension_no_direct_seed"},
]

SOURCE_FUNCTION_BY_TEMPLATE_ID: dict[int, dict[str, Any]] = {
    **SOURCE_BUILDING_FUNCTIONS,
    **{
        row["templateObjectId"]: {
            "sourceName": row["sourceName"],
            "sourceFunction": row["sourceFunction"],
            "sourceFunctionConfidence": row["sourceFunctionConfidence"],
        }
        for row in HOMM3_BUILDING_CATALOG_EXTENSION
        if isinstance(row.get("templateObjectId"), int)
    },
}

HOMM3_ARTIFACT_EFFECTS_BY_SUBTYPE: dict[int, dict[str, str]] = {
    25: {"name": "Breastplate of Petrified Wood", "effect": "Fixed HoMM3 artifact subtype 25. Grants +1 Spell Power to the visiting hero when equipped."},
    35: {"name": "Sword of Judgement", "effect": "Fixed HoMM3 artifact subtype 35. Grants +5 Attack, +5 Defense, +5 Spell Power, and +5 Knowledge to the visiting hero when equipped."},
    56: {"name": "Dead Man's Boots", "effect": "Fixed HoMM3 artifact subtype 56. Increases the hero's necromancy raise percentage by 15 when equipped."},
    57: {"name": "Garniture of Interference", "effect": "Fixed HoMM3 artifact subtype 57. Grants 5% magic resistance to the visiting hero when equipped."},
    58: {"name": "Surcoat of Counterpoise", "effect": "Fixed HoMM3 artifact subtype 58. Grants 10% magic resistance to the visiting hero when equipped."},
}
RANDOM_ARTIFACT_TEMPLATE_DESCRIPTIONS: dict[int, str] = {
    65: "Random artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    66: "Random treasure artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    67: "Random minor artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    68: "Random major artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    69: "Random relic artifact pickup; exact artifact is chosen by the source map rules at runtime.",
}

SOURCE_FUNCTION_BY_CATEGORY: dict[tuple[str, str], dict[str, str]] = {
    ("map_event", "event"): {"sourceName": "Map Event", "sourceFunction": "Runs a scripted map event when its trigger conditions are met.", "sourceFunctionConfidence": "source_category_seed"},
    ("town", "town"): {"sourceName": "Town", "sourceFunction": "Places a capturable town with faction, ownership, garrison, buildings, and campaign objective state.", "sourceFunctionConfidence": "source_category_seed"},
    ("travel_link_candidate", "explicit_no_payload"): {"sourceName": "Travel Link", "sourceFunction": "Moves or connects the visiting hero through an adventure-map travel object such as a cave entrance or whirlpool.", "sourceFunctionConfidence": "source_category_seed"},
    ("monster_stack", "monster"): {"sourceName": "Monster Stack", "sourceFunction": "Places a neutral or scripted creature stack that can block movement, guard rewards, or start combat.", "sourceFunctionConfidence": "source_category_seed"},
    ("artifact_pickup", "artifact"): {"sourceName": "Artifact Pickup", "sourceFunction": "Places an artifact pickup that can be collected by a visiting hero.", "sourceFunctionConfidence": "source_category_seed"},
    ("external_dwelling", "creature_generator"): {"sourceName": "External Dwelling", "sourceFunction": "Places an external creature dwelling that can provide recruitable units for the matching HoMM3 town faction.", "sourceFunctionConfidence": "source_category_seed"},
    ("resource_pickup", "resource"): {"sourceName": "Resource Pickup", "sourceFunction": "Places a resource pickup that grants map resources when collected.", "sourceFunctionConfidence": "source_category_seed"},
    ("mine", "mine"): {"sourceName": "Mine", "sourceFunction": "Places a capturable resource mine that provides recurring income to its owner.", "sourceFunctionConfidence": "source_category_seed"},
    ("hero_or_prison", "hero_or_prison"): {"sourceName": "Hero or Prison", "sourceFunction": "Places a hero-related map object, either a hero entry or a prison-style rescue object.", "sourceFunctionConfidence": "source_category_seed"},
    ("boat_or_water_travel_object", "explicit_no_payload"): {"sourceName": "Boat or Water Travel Object", "sourceFunction": "Places a water-travel object; Olden compatibility depends on map water and travel support.", "sourceFunctionConfidence": "source_category_seed"},
    ("readable_sign_or_bottle", "sign"): {"sourceName": "Readable Sign", "sourceFunction": "Shows map-authored text when visited or inspected.", "sourceFunctionConfidence": "source_category_seed"},
    ("interactive_reward_object", "scholar"): {"sourceName": "Scholar", "sourceFunction": "Grants the visiting hero a knowledge, skill, spell, or experience-style reward depending on source payload.", "sourceFunctionConfidence": "source_category_seed"},
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_english_tokens(core_zip: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with zipfile.ZipFile(core_zip) as archive:
        for member in [ENGLISH_MAP_OBJECT_TEXT, ENGLISH_ARTIFACT_TEXT]:
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            for row in payload.get("tokens", []):
                if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                    result[row["sid"]] = row["text"]
    return result


def read_core_json_member(source_core: str, source: str, cache: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    key = (source_core, source)
    cached = cache.get(key)
    if cached is not None:
        return cached
    with zipfile.ZipFile(source_core) as archive:
        payload = json.loads(archive.read(source).decode("utf-8-sig"))
    cache[key] = payload
    return payload


def localized_map_object_details(candidate_sid: str, row: dict[str, Any], logic_sources: list[str], source_core: str, english_tokens: dict[str, str]) -> dict[str, Any]:
    details: dict[str, Any] = {"sid": candidate_sid, "name": None, "description": None, "narrativeDescription": None, "tag": row.get("tag"), "isInteractable": row.get("isInteractable"), "logicSources": logic_sources}
    source = row.get("source")
    if not isinstance(source, str):
        return details
    data = read_core_json_member(source_core, source, OBJECT_CONFIG_CACHE)
    for object_row in data.get("array", []):
        if not isinstance(object_row, dict) or object_row.get("id") != candidate_sid:
            continue
        for field in ["name", "description", "narrativeDescription"]:
            token_sid = object_row.get(field)
            if not isinstance(token_sid, str):
                token_sid = f"{candidate_sid}_{field}"
            details[f"{field}TokenSid"] = token_sid
            details[field] = english_tokens.get(token_sid)
            if details[field] is None and row.get("tag") == "Artifact":
                artifact_token_sid = f"{candidate_sid}_{field}"
                details[f"{field}TokenSid"] = artifact_token_sid
                details[field] = english_tokens.get(artifact_token_sid)
        return details
    return details


def logic_profile(candidate_sid: str, details: dict[str, Any], source_core: str) -> dict[str, Any]:
    reward_types: set[str] = set()
    stat_parameters: set[str] = set()
    buff_parameters: set[str] = set()
    skill_parameters: set[str] = set()
    for source in details.get("logicSources") or []:
        if not isinstance(source, str):
            continue
        payload = read_core_json_member(source_core, source, LOGIC_CONFIG_CACHE)
        for object_row in payload.get("array", []):
            if not isinstance(object_row, dict) or object_row.get("id") != candidate_sid:
                continue
            variants = object_row.get("variants", [])
            for variant in variants:
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
    return {"rewardTypes": sorted(reward_types), "statParameters": sorted(stat_parameters), "buffParameters": sorted(buff_parameters), "skillParameters": sorted(skill_parameters)}


def build_candidate_catalog(core_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    source_core = core_catalog.get("sourceCoreZip")
    if not isinstance(source_core, str):
        raise ValueError("core catalog must record sourceCoreZip")
    english_tokens = load_english_tokens(source_core)
    logic_sources_by_id: dict[str, list[str]] = {}
    for logic_row in core_catalog.get("objectLogicRows", []):
        if isinstance(logic_row, dict) and isinstance(logic_row.get("id"), str) and isinstance(logic_row.get("source"), str):
            logic_sources_by_id.setdefault(logic_row["id"], []).append(logic_row["source"])
    candidates = []
    for row in core_catalog.get("mapObjects", []):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        details = localized_map_object_details(row["id"], row, sorted(logic_sources_by_id.get(row["id"], [])), source_core, english_tokens)
        profile = logic_profile(row["id"], details, source_core) if details.get("logicSources") else {"rewardTypes": [], "statParameters": [], "buffParameters": [], "skillParameters": []}
        description = details.get("description") or ""
        name = details.get("name") or row["id"]
        candidates.append({"sid": row["id"], "name": name, "description": description, "narrativeDescription": details.get("narrativeDescription") or "", "tag": details.get("tag"), "isInteractable": details.get("isInteractable"), "logicSources": sorted(details.get("logicSources") or []), "logicProfile": profile})
    return sorted(candidates, key=lambda candidate: (not bool(candidate["isInteractable"]), str(candidate["name"]).lower(), candidate["sid"]))


def artifact_details_for_entry(entry: dict[str, Any], source_entities_by_key: dict[str, dict[str, Any]]) -> dict[str, str] | None:
    if entry.get("category") != "artifact_pickup":
        return None
    template_id = entry.get("templateObjectId")
    random_description = RANDOM_ARTIFACT_TEMPLATE_DESCRIPTIONS.get(template_id)
    if random_description is not None:
        return {"name": "Random Artifact", "function": random_description}
    subtype_values = {
        source_entities_by_key[key].get("templateSubtype")
        for key in entry.get("sampleSourceKeys") or []
        if key in source_entities_by_key
    }
    subtype_values.discard(None)
    if len(subtype_values) != 1:
        return None
    artifact = HOMM3_ARTIFACT_EFFECTS_BY_SUBTYPE.get(next(iter(subtype_values)))
    if artifact is None:
        return None
    animation = entry.get("templateAnimation") or "unknown DEF"
    return {"name": artifact["name"], "function": f"{artifact['effect']} Source map DEF: {animation}."}


def source_seed_for_entry(entry: dict[str, Any], source_entities_by_key: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    evidence = entry.get("semanticEvidence") if isinstance(entry.get("semanticEvidence"), dict) else {}
    artifact = artifact_details_for_entry(entry, source_entities_by_key)
    if artifact is not None:
        return artifact["name"], artifact["function"], "h3m_artifact_subtype_seed"
    if isinstance(evidence.get("sourceName"), str) and isinstance(evidence.get("sourceDescription"), str):
        return evidence["sourceName"], evidence["sourceDescription"], "semanticEvidence.sourceDescription"
    template_id = entry.get("templateObjectId")
    fallback = SOURCE_FUNCTION_BY_TEMPLATE_ID.get(template_id)
    if fallback is not None:
        return fallback["sourceName"], fallback["sourceFunction"], fallback["sourceFunctionConfidence"]
    category_seed = SOURCE_FUNCTION_BY_CATEGORY.get((str(entry.get("category")), str(entry.get("payloadKind"))))
    if category_seed is not None:
        animation = entry.get("templateAnimation") or "unknown animation"
        source_name = f"{category_seed['sourceName']} ({animation})"
        return source_name, category_seed["sourceFunction"], category_seed["sourceFunctionConfidence"]
    animation = entry.get("templateAnimation") or "unknown animation"
    source_name = f"H3 template {template_id} / {animation}"
    source_function = "Unclassified HoMM3 map object still needs source-function review before canon mapping."
    return source_name, source_function, "needs_h3_primary_source_review"


def row_from_substitution(entry: dict[str, Any], candidates_by_sid: dict[str, dict[str, Any]], source_entities_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    replacement_sid = entry.get("replacementSid")
    target = candidates_by_sid.get(replacement_sid) if isinstance(replacement_sid, str) else None
    evidence = entry.get("semanticEvidence") if isinstance(entry.get("semanticEvidence"), dict) else {}
    source_name, source_function, source_confidence = source_seed_for_entry(entry, source_entities_by_key)
    return {
        "rowKind": "homecoming_substitution",
        "rowId": entry.get("sourceSignature"),
        "sourceSignature": entry.get("sourceSignature"),
        "sourceSid": entry.get("sourceSid"),
        "templateObjectId": entry.get("templateObjectId"),
        "templateAnimation": entry.get("templateAnimation"),
        "category": entry.get("category"),
        "payloadKind": entry.get("payloadKind"),
        "count": entry.get("count"),
        "lossiness": entry.get("lossiness"),
        "sourceName": source_name,
        "sourceFunction": source_function,
        "sourceFunctionConfidence": source_confidence,
        "currentReplacementSid": replacement_sid,
        "currentReplacementName": target.get("name") if target else "",
        "currentReplacementDescription": target.get("description") if target else "",
        "currentRuleName": entry.get("ruleName") or "blocked_no_rule",
        "currentConfidence": entry.get("confidence") or "blocked",
        "currentScore": evidence.get("score"),
        "status": "blocked" if replacement_sid is None else "needs_review",
        "proposedReplacementSid": replacement_sid,
        "proposedOldenFunction": target.get("description") if target else "",
        "reviewNotes": "",
        "badControls": evidence.get("badControls") or [],
        "topCandidates": evidence.get("topCandidates") or [],
    }


def row_from_catalog_extension(seed: dict[str, Any], candidates_by_sid: dict[str, dict[str, Any]]) -> dict[str, Any]:
    replacement_sid = seed.get("proposedReplacementSid")
    target = candidates_by_sid.get(replacement_sid) if isinstance(replacement_sid, str) else None
    template_id = seed.get("templateObjectId")
    animation = seed.get("templateAnimation")
    row_id = f"homm3.catalog_extension|{template_id}|{animation}"
    return {
        "rowKind": "homm3_catalog_extension",
        "rowId": row_id,
        "sourceSignature": row_id,
        "sourceSid": f"h3m.catalog_extension.{template_id}",
        "templateObjectId": template_id,
        "templateAnimation": animation,
        "category": "homm3_building_catalog_extension",
        "payloadKind": "catalog_only_not_in_homecoming",
        "count": 0,
        "lossiness": "preliminary_catalog_seed",
        "sourceName": seed["sourceName"],
        "sourceFunction": seed["sourceFunction"],
        "sourceFunctionConfidence": seed["sourceFunctionConfidence"],
        "currentReplacementSid": replacement_sid,
        "currentReplacementName": target.get("name") if target else "",
        "currentReplacementDescription": target.get("description") if target else "",
        "currentRuleName": seed.get("currentRuleName") or "catalog_extension_seed",
        "currentConfidence": "preliminary_catalog_seed",
        "currentScore": None,
        "status": "needs_review" if replacement_sid else "blocked",
        "proposedReplacementSid": replacement_sid,
        "proposedOldenFunction": target.get("description") if target else "",
        "reviewNotes": "Catalog extension row; not observed in Homecoming artifact and not accepted canon until reviewed.",
        "badControls": [],
        "topCandidates": [],
    }


def reviewable_homecoming_substitutions(substitution_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in substitution_map.get("invalidEntitySubstitutions") or []
        if isinstance(entry, dict) and is_reviewable_homecoming_substitution(entry)
    ]


def excluded_homecoming_substitutions(substitution_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in substitution_map.get("invalidEntitySubstitutions") or []
        if isinstance(entry, dict) and not is_reviewable_homecoming_substitution(entry)
    ]


def load_checkpoint_by_row_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    checkpoint = read_json(path)
    if checkpoint.get("schema") not in {"homm3.homecoming_building_mapping_review_export.v0", "homm3.homecoming_building_canon_mappings.v0"}:
        raise ValueError(f"unexpected mapping review checkpoint schema: {checkpoint.get('schema')}")
    rows = checkpoint.get("mappings")
    if not isinstance(rows, list):
        raise ValueError("mapping review checkpoint must contain mappings list")
    return {row["rowId"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("rowId"), str)}


def merge_checkpoint(row: dict[str, Any], checkpoint_by_row_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checkpoint = checkpoint_by_row_id.get(row.get("rowId"))
    if checkpoint is None:
        return row
    merged = dict(row)
    for checkpoint_field, row_field in [
        ("oldenReplacementSid", "proposedReplacementSid"),
        ("proposedOldenFunction", "proposedOldenFunction"),
        ("reviewStatus", "status"),
        ("reviewNotes", "reviewNotes"),
    ]:
        if checkpoint_field in checkpoint:
            merged[row_field] = checkpoint.get(checkpoint_field)
    if merged.get("status") == "accepted" and merged.get("proposedReplacementSid") is None:
        existing_note = merged.get("reviewNotes") if isinstance(merged.get("reviewNotes"), str) else ""
        normalization_note = "Checkpoint had accepted status with no Olden replacement; normalized to blocked until a replacement is selected."
        merged["status"] = "blocked"
        merged["reviewNotes"] = f"{existing_note} {normalization_note}".strip()
        merged["checkpointNormalization"] = "accepted_without_replacement_to_blocked"
    if merged.get("proposedReplacementSid") is None and merged.get("currentConfidence") == "artifact_effect_shape" and merged.get("currentReplacementSid") is not None:
        existing_note = merged.get("reviewNotes") if isinstance(merged.get("reviewNotes"), str) else ""
        normalization_note = "Checkpoint had no artifact replacement; seeded proposed mapping from current artifact effect-shape mapper for review."
        merged["proposedReplacementSid"] = merged.get("currentReplacementSid")
        merged["proposedOldenFunction"] = merged.get("currentReplacementDescription") or ""
        merged["status"] = "needs_review"
        merged["reviewNotes"] = f"{existing_note} {normalization_note}".strip()
        merged["checkpointNormalization"] = "empty_checkpoint_to_artifact_effect_shape_proposal"
    merged["checkpointMerged"] = True
    return merged


def load_source_entities_by_key() -> dict[str, dict[str, Any]]:
    alignment = read_json(ALIGNMENT_PATH)
    entities = alignment.get("alignment", {}).get("globalObjectProperties", {}).get("propEntities")
    if not isinstance(entities, list):
        raise ValueError("alignment artifact must contain alignment.globalObjectProperties.propEntities")
    return {entity["sourceKey"]: entity for entity in entities if isinstance(entity, dict) and isinstance(entity.get("sourceKey"), str)}


def build_review_rows(substitution_map: dict[str, Any], candidates_by_sid: dict[str, dict[str, Any]], source_entities_by_key: dict[str, dict[str, Any]], checkpoint_by_row_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    substitutions = reviewable_homecoming_substitutions(substitution_map)
    rows = [row_from_substitution(entry, candidates_by_sid, source_entities_by_key) for entry in sorted(substitutions, key=lambda entry: str(entry.get("sourceSignature")))]
    observed_template_ids = {
        entry.get("templateObjectId")
        for entry in substitution_map.get("invalidEntitySubstitutions") or []
        if isinstance(entry, dict)
    }
    for seed in HOMM3_BUILDING_CATALOG_EXTENSION:
        if seed.get("templateObjectId") in observed_template_ids:
            continue
        rows.append(row_from_catalog_extension(seed, candidates_by_sid))
    return [merge_checkpoint(row, checkpoint_by_row_id) for row in rows]

def html_doc(seed: dict[str, Any]) -> str:
    escaped_seed = json.dumps(seed, ensure_ascii=False, indent=2).replace("</script", "<\\/script")
    return f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Homecoming Building Mapping Review</title>
<style>
:root {{ color-scheme: light dark; --bg:#f6f7f9; --panel:#ffffff; --text:#1b1f24; --muted:#667085; --line:#d0d7de; --accent:#1456cc; --bad:#8a1f11; --ok:#116329; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --panel:#1a1f26; --text:#e6edf3; --muted:#9aa4b2; --line:#333b46; --accent:#7aa2ff; --bad:#ff9b8f; --ok:#7ee787; }} }}
* {{ box-sizing: border-box; }} body {{ margin:0; font:14px/1.45 system-ui, Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--text); }}
header {{ position:sticky; top:0; z-index:3; background:var(--panel); border-bottom:1px solid var(--line); padding:12px 16px; }}
h1 {{ font-size:18px; margin:0 0 10px; }} button, select, input, textarea {{ font:inherit; }} button {{ border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:6px; padding:7px 10px; cursor:pointer; }} button.primary {{ background:var(--accent); color:white; border-color:var(--accent); }}
input, select, textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:7px 8px; background:var(--panel); color:var(--text); }} main {{ padding:14px; }}
.toolbar {{ display:grid; grid-template-columns:minmax(220px, 1fr) 180px 180px auto auto; gap:10px; align-items:center; }} .grid {{ display:grid; gap:12px; margin-top:10px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; display:grid; grid-template-columns: minmax(260px, .9fr) minmax(360px, 1.4fr) minmax(260px, .9fr); gap:12px; }}
.card h2 {{ font-size:16px; margin:0 0 6px; }} .meta {{ color:var(--muted); font-size:12px; display:flex; gap:8px; flex-wrap:wrap; }} .label {{ color:var(--muted); font-size:12px; margin:8px 0 3px; }} .desc {{ white-space:pre-wrap; }}
.status-accepted {{ border-left:4px solid var(--ok); }} .status-blocked {{ border-left:4px solid var(--bad); }} .status-needs_review {{ border-left:4px solid var(--accent); }} .status-rejected {{ border-left:4px solid var(--bad); }}
.small {{ font-size:12px; color:var(--muted); }} .candidateBox {{ border:1px solid var(--line); border-radius:6px; padding:8px; min-height:110px; }} textarea {{ min-height:76px; resize:vertical; }} pre {{ white-space:pre-wrap; background:var(--panel); border:1px solid var(--line); padding:10px; border-radius:6px; max-height:360px; overflow:auto; }} .hidden {{ display:none !important; }}
@media (max-width: 1050px) {{ .toolbar {{ grid-template-columns:1fr 1fr; }} .card {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header><h1>Homecoming Building Mapping Review</h1><div class='toolbar'><input id='filter' placeholder='Filter source, target, SID, function'><select id='statusFilter'><option value=''>All statuses</option><option value='needs_review'>Needs review</option><option value='accepted'>Accepted</option><option value='rejected'>Rejected</option><option value='blocked'>Blocked</option></select><select id='candidateFilter'><option value=''>All candidates</option><option value='mapped'>Has proposed target</option><option value='empty'>Empty mapping</option></select><button id='exportBtn' class='primary'>Export Accepted Canon JSON</button><button id='reviewExportBtn'>Export Full Review JSON</button><button id='copyBtn'>Copy Canon JSON</button></div></header>
<main><datalist id='candidateOptions'></datalist><div class='small' id='summary'></div><div class='grid' id='rows'></div><section id='exportPanel' class='hidden'><h2>Exported Mapping JSON</h2><pre id='exportText'></pre></section></main>
<script id='seed' type='application/json'>{escaped_seed}</script>
<script>
const seed = JSON.parse(document.getElementById('seed').textContent);
const candidates = seed.oldenCandidates;
const candidateBySid = new Map(candidates.map(c => [c.sid, c]));
let rows = seed.reviewRows.map(r => ({{...r}}));
function escapeHtml(value) {{ return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch])); }}
function candidateLabel(c) {{ const desc = c.description ? ' - ' + c.description.replace(/\\s+/g, ' ').slice(0, 110) : ''; return `${{c.name || c.sid}} [${{c.sid}}]${{desc}}`; }}
function renderCandidateDetails(row, container) {{ const sid = row.proposedReplacementSid; if (!sid) {{ container.innerHTML = '<div class="small">No Olden replacement selected.</div>'; return; }} const c = candidateBySid.get(sid); if (!c) {{ container.innerHTML = '<div class="small">Selected SID is not in candidate catalog: ' + escapeHtml(sid) + '</div>'; return; }} container.innerHTML = `<strong>${{escapeHtml(c.name || c.sid)}}</strong> <span class="small">${{escapeHtml(c.sid)}}</span><div class="label">Olden English Description</div><div class="desc">${{escapeHtml(c.description || '')}}</div><div class="label">Logic Profile</div><div class="small">${{escapeHtml(JSON.stringify(c.logicProfile))}}</div><div class="label">Logic Sources</div><div class="small">${{escapeHtml((c.logicSources || []).join(', '))}}</div>`; }}
function mappingPayload(r) {{ const c = r.proposedReplacementSid ? candidateBySid.get(r.proposedReplacementSid) : null; return {{ rowKind: r.rowKind, rowId: r.rowId, sourceSignature: r.sourceSignature, sourceSid: r.sourceSid, category: r.category, payloadKind: r.payloadKind, sourceOccurrenceCount: r.count ?? 0, templateObjectId: r.templateObjectId, templateAnimation: r.templateAnimation, homm3BuildingName: r.sourceName, homm3Function: r.sourceFunction, homm3FunctionConfidence: r.sourceFunctionConfidence, oldenReplacementSid: r.proposedReplacementSid || null, oldenBuildingName: c ? c.name : '', oldenEnglishDescription: c ? c.description : '', proposedOldenFunction: r.proposedOldenFunction || '', reviewStatus: r.status, reviewNotes: r.reviewNotes || '', startingReplacementSid: r.currentReplacementSid, startingRuleName: r.currentRuleName, startingConfidence: r.currentConfidence, startingScore: r.currentScore ?? null }}; }}
function exportObject(mode) {{ const selectedRows = mode === 'canon' ? rows.filter(r => r.status === 'accepted' && r.proposedReplacementSid) : rows; return {{ schema: mode === 'canon' ? 'homm3.homecoming_building_canon_mappings.v0' : 'homm3.homecoming_building_mapping_review_export.v0', exportMode: mode, sourceSeed: seed.sourceSeed, exportedAtLocal: new Date().toISOString(), acceptedMappingCount: rows.filter(r => r.status === 'accepted' && r.proposedReplacementSid).length, unresolvedReviewCount: rows.filter(r => r.status !== 'accepted').length, mappings: selectedRows.map(mappingPayload) }}; }}
function updateExport(download, mode) {{ const text = JSON.stringify(exportObject(mode), null, 2); document.getElementById('exportText').textContent = text; document.getElementById('exportPanel').classList.remove('hidden'); if (download) {{ const blob = new Blob([text + '\\n'], {{type:'application/json'}}); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = mode === 'canon' ? 'homecoming_building_canon_mappings.accepted.json' : 'homecoming_building_mapping_review.full.json'; a.click(); URL.revokeObjectURL(a.href); }} return text; }}
function refreshProposedFunction(row) {{ const c = row.proposedReplacementSid ? candidateBySid.get(row.proposedReplacementSid) : null; row.proposedOldenFunction = c ? (c.description || '') : ''; }}
function populateCandidateDatalist() {{ const list = document.getElementById('candidateOptions'); list.innerHTML = ''; for (const c of candidates) {{ const option = document.createElement('option'); option.value = c.sid; option.label = candidateLabel(c); list.appendChild(option); }} }}
function render() {{ const root = document.getElementById('rows'); root.innerHTML = ''; const filter = document.getElementById('filter').value.toLowerCase(); const statusFilter = document.getElementById('statusFilter').value; const candidateFilter = document.getElementById('candidateFilter').value; let visible = 0; for (const row of rows) {{ const candidate = row.proposedReplacementSid ? candidateBySid.get(row.proposedReplacementSid) : null; const haystack = JSON.stringify([row, candidate]).toLowerCase(); if (filter && !haystack.includes(filter)) continue; if (statusFilter && row.status !== statusFilter) continue; if (candidateFilter === 'mapped' && !row.proposedReplacementSid) continue; if (candidateFilter === 'empty' && row.proposedReplacementSid) continue; visible++; const card = document.createElement('section'); card.className = 'card status-' + row.status; card.innerHTML = `<div><h2>${{escapeHtml(row.sourceName)}}</h2><div class="meta"><span>${{escapeHtml(row.rowKind)}}</span><span>template ${{escapeHtml(row.templateObjectId)}}</span><span>${{escapeHtml(row.templateAnimation)}}</span><span>${{escapeHtml(row.sourceFunctionConfidence)}}</span></div><div class="label">Original H3 Function</div><textarea data-field="sourceFunction">${{escapeHtml(row.sourceFunction)}}</textarea><div class="label">Current Mapper</div><div class="small">${{escapeHtml(row.currentReplacementSid || 'EMPTY')}} via ${{escapeHtml(row.currentRuleName)}} confidence ${{escapeHtml(row.currentConfidence || '')}} count ${{escapeHtml(row.count ?? '')}}</div><div class="label">Source Signature</div><div class="small">${{escapeHtml(row.sourceSignature || '')}}</div></div><div><div class="label">Proposed Olden Replacement SID</div><input data-field="proposedReplacementSid" list="candidateOptions" placeholder="Olden SID or empty" value="${{escapeHtml(row.proposedReplacementSid || '')}}"><div class="candidateBox"></div><div class="label">Proposed New Building Function</div><textarea data-field="proposedOldenFunction">${{escapeHtml(row.proposedOldenFunction || '')}}</textarea></div><div><div class="label">Review Status</div><select data-field="status"><option value="needs_review">Needs review</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="blocked">Blocked</option></select><div class="label">Review Notes</div><textarea data-field="reviewNotes">${{escapeHtml(row.reviewNotes || '')}}</textarea><div class="label">Near Miss / Top Evidence</div><div class="small">${{escapeHtml(JSON.stringify({{topCandidates: row.topCandidates, badControls: row.badControls}}, null, 2))}}</div></div>`; card.querySelector('select[data-field="status"]').value = row.status; const detailBox = card.querySelector('.candidateBox'); renderCandidateDetails(row, detailBox); card.querySelectorAll('[data-field]').forEach(input => {{ input.addEventListener('change', () => {{ const value = input.value.trim(); row[input.dataset.field] = value; if (input.dataset.field === 'proposedReplacementSid') {{ row.proposedReplacementSid = value || null; refreshProposedFunction(row); render(); }} else if (input.dataset.field === 'status') {{ render(); }} }}); }}); root.appendChild(card); }} document.getElementById('summary').textContent = `${{visible}} of ${{rows.length}} mappings visible. Homecoming rows: ${{rows.filter(r => r.rowKind === 'homecoming_substitution').length}}. Catalog extension rows: ${{rows.filter(r => r.rowKind === 'homm3_catalog_extension').length}}. Candidate catalog: ${{candidates.length}} Olden map objects.`; }}
document.getElementById('filter').addEventListener('input', render); document.getElementById('statusFilter').addEventListener('change', render); document.getElementById('candidateFilter').addEventListener('change', render); document.getElementById('exportBtn').addEventListener('click', () => updateExport(true, 'canon')); document.getElementById('reviewExportBtn').addEventListener('click', () => updateExport(true, 'review')); document.getElementById('copyBtn').addEventListener('click', async () => {{ const text = updateExport(false, 'canon'); await navigator.clipboard.writeText(text); }}); populateCandidateDatalist(); render();
</script>
</body>
</html>
"""


def main() -> int:
    substitution_map = read_json(SUBSTITUTION_PATH)
    core_catalog = read_json(CORE_CATALOG_PATH)
    candidates = build_candidate_catalog(core_catalog)
    candidates_by_sid = {candidate["sid"]: candidate for candidate in candidates}
    source_entities_by_key = load_source_entities_by_key()
    checkpoint_by_row_id = load_checkpoint_by_row_id(CHECKPOINT_PATH)
    excluded = excluded_homecoming_substitutions(substitution_map)
    seed = {
        "schema": "homm3.homecoming_building_mapping_review_seed.v0",
        "sourceSeed": str(SUBSTITUTION_PATH.relative_to(REPO_ROOT)),
        "sourceCoreZip": core_catalog.get("sourceCoreZip"),
        "excludedHomecomingReviewRows": {
            "reason": "payloadless visual terrain/decor substitutions are excluded from text-only building review and left to auto mapping",
            "count": len(excluded),
            "categories": sorted(EXCLUDED_HOMECOMING_REVIEW_CATEGORIES),
        },
        "checkpoint": {
            "path": str(CHECKPOINT_PATH.relative_to(REPO_ROOT)),
            "mergedRowCount": len(checkpoint_by_row_id),
        },
        "reviewRows": build_review_rows(substitution_map, candidates_by_sid, source_entities_by_key, checkpoint_by_row_id),
        "oldenCandidates": candidates,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SEED_JSON_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    HTML_PATH.write_text(html_doc(seed), encoding="utf-8")
    print(f"wrote {SEED_JSON_PATH}")
    print(f"wrote {HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
