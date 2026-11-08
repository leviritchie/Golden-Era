#!/usr/bin/env python3
"""Validate the generated Homecoming building mapping review menu artifact."""

from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT_FOR_IMPORTS / "experiments" / "campaign_port_poc"))
import h3m_object_registry as h3obj

SEED_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "mapping_review" / "homecoming_building_mapping_review_seed.json"
HTML_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "mapping_review" / "homecoming_building_mapping_review.html"
SUBSTITUTION_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "entity_substitutions" / "homecoming.olden_entity_substitution_map.json"
CORE_CATALOG_PATH = Path("artifacts") / "campaign_port_poc" / "olden_entity_catalog" / "olden_core_map_valid_entity_catalog.json"
CHECKPOINT_PATH = Path("experiments") / "campaign_port_poc" / "homecoming_mapping_review_checkpoint.json"
ALIGNMENT_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"
GENERATOR = Path("experiments") / "campaign_port_poc" / "build_homecoming_mapping_review_menu.py"
EXPECTED_SCHEMA = "homm3.homecoming_building_mapping_review_seed.v0"
EXPECTED_CANON_EXPORT_SCHEMA = "homm3.homecoming_building_canon_mappings.v0"
EXPECTED_REVIEW_EXPORT_SCHEMA = "homm3.homecoming_building_mapping_review_export.v0"
CATALOG_EXTENSION_CONFIDENCES = {"catalog_extension_seed", "needs_h3_primary_source_review.catalog_extension"}
EXPECTED_CATALOG_EXTENSION_NAMES = {
    "Black Market",
    "Hill Fort",
    "Trading Post",
    "Freelancer's Guild",
    "War Machine Factory",
    "Magic Spring",
    "Faerie Ring",
    "Redwood Observatory",
    "Seer's Hut",
    "Keymaster's Tent",
}

EXCLUDED_HOMECOMING_REVIEW_CATEGORIES = {
    "payloadless_object_unclassified_for_current_scope",
}
FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS = {30, 32, 39, 49, 94, 100, 101, 102, 104, 107, 109, 112}


def is_reviewable_homecoming_substitution(entry: dict[str, Any]) -> bool:
    if entry.get("category") not in EXCLUDED_HOMECOMING_REVIEW_CATEGORIES:
        return True
    return entry.get("templateObjectId") in FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS

SOURCE_FUNCTION_OVERRIDES = {
    4: {"sourceName": "Arena", "sourceFunction": "Permanently trains the visiting hero to increase Attack or Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    23: {"sourceName": "Marletto Tower", "sourceFunction": "Permanently increases the visiting hero's Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    30: {"sourceName": "Fountain", "sourceFunction": "HoMM3 adventure-map fountain object; exact visit reward needs primary-source confirmation.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension"},
    31: {"sourceName": "Fountain of Youth", "sourceFunction": "Grants a temporary morale benefit and extra movement to the visiting hero.", "sourceFunctionConfidence": "needs_h3_primary_source_review"},
    32: {"sourceName": "Garden of Revelation", "sourceFunction": "HoMM3 adventure-map knowledge garden object; exact visit reward needs primary-source confirmation.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension"},
    39: {"sourceName": "Learning Stone", "sourceFunction": "Grants experience to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed"},
    41: {"sourceName": "Library of Enlightenment", "sourceFunction": "Permanently increases Attack, Defense, Spell Power, and Knowledge for an experienced visiting hero.", "sourceFunctionConfidence": "current_mapper_seed"},
    47: {"sourceName": "School of Magic", "sourceFunction": "Lets the visiting hero choose a permanent increase to Spell Power or Knowledge.", "sourceFunctionConfidence": "current_mapper_seed"},
    49: {"sourceName": "Magic Well", "sourceFunction": "Restores spell points for the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed"},
    51: {"sourceName": "Mercenary Camp", "sourceFunction": "Permanently increases the visiting hero's Attack.", "sourceFunctionConfidence": "current_mapper_seed"},
    80: {"sourceName": "Sanctuary", "sourceFunction": "Protects the visiting hero from being attacked while occupying the object.", "sourceFunctionConfidence": "needs_h3_primary_source_review"},
    94: {"sourceName": "Stables", "sourceFunction": "Increases the visiting hero's adventure movement for the rest of the week.", "sourceFunctionConfidence": "catalog_extension_seed"},
    96: {"sourceName": "Temple", "sourceFunction": "Blesses the visiting hero with extra Morale for a limited time.", "sourceFunctionConfidence": "current_mapper_seed"},
    100: {"sourceName": "Gazebo", "sourceFunction": "Grants experience to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed"},
    101: {"sourceName": "Treasure Chest", "sourceFunction": "Lets the visiting hero choose between gold and experience.", "sourceFunctionConfidence": "catalog_extension_seed"},
    102: {"sourceName": "Tree of Knowledge", "sourceFunction": "Can grant the visiting hero a level for a requested cost or condition.", "sourceFunctionConfidence": "catalog_extension_seed"},
    104: {"sourceName": "University", "sourceFunction": "Lets the visiting hero buy secondary skills from an offered set.", "sourceFunctionConfidence": "catalog_extension_seed"},
    107: {"sourceName": "School of War", "sourceFunction": "Lets the visiting hero choose a permanent increase to Attack or Defense.", "sourceFunctionConfidence": "current_mapper_seed"},
    109: {"sourceName": "Windmill", "sourceFunction": "Provides a weekly random resource reward to the visiting hero.", "sourceFunctionConfidence": "catalog_extension_seed"},
    112: {"sourceName": "Windmill Variant", "sourceFunction": "HoMM3 wind-themed adventure object; exact visit behavior needs primary-source confirmation.", "sourceFunctionConfidence": "needs_h3_primary_source_review.catalog_extension"},
    113: {"sourceName": "Witch Hut", "sourceFunction": "Teaches the visiting hero a random secondary skill.", "sourceFunctionConfidence": "current_mapper_seed"},
}
CATEGORY_SOURCE_FUNCTIONS = {
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
CATEGORY_SOURCE_CONFIDENCE = "source_category_seed"
ARTIFACT_SOURCE_CONFIDENCE = "h3m_artifact_subtype_seed"
ARTIFACT_SOURCE_FUNCTIONS_BY_SUBTYPE = {
    25: {"sourceName": "Breastplate of Petrified Wood", "sourceFunction": "Fixed HoMM3 artifact subtype 25. Grants +1 Spell Power to the visiting hero when equipped."},
    35: {"sourceName": "Sword of Judgement", "sourceFunction": "Fixed HoMM3 artifact subtype 35. Grants +5 Attack, +5 Defense, +5 Spell Power, and +5 Knowledge to the visiting hero when equipped."},
    56: {"sourceName": "Dead Man's Boots", "sourceFunction": "Fixed HoMM3 artifact subtype 56. Increases the hero's necromancy raise percentage by 15 when equipped."},
    57: {"sourceName": "Garniture of Interference", "sourceFunction": "Fixed HoMM3 artifact subtype 57. Grants 5% magic resistance to the visiting hero when equipped."},
    58: {"sourceName": "Surcoat of Counterpoise", "sourceFunction": "Fixed HoMM3 artifact subtype 58. Grants 10% magic resistance to the visiting hero when equipped."},
}
RANDOM_ARTIFACT_TEMPLATE_DESCRIPTIONS = {
    65: "Random artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    66: "Random treasure artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    67: "Random minor artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    68: "Random major artifact pickup; exact artifact is chosen by the source map rules at runtime.",
    69: "Random relic artifact pickup; exact artifact is chosen by the source map rules at runtime.",
}
CLASSIFIER_LEAK_PATTERNS = ["current classifier", "category=", "payload=", "rule="]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        errors.append(f"cannot read {path}: {ex}")
        return {}


def run_generation(repo_root: Path, errors: list[str]) -> None:
    script = repo_root / GENERATOR
    require(script.exists(), f"missing mapping review generator: {script}", errors)
    if not script.exists():
        return
    temp_root = repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "mapping_review_contract_tmp"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        env = dict(os.environ)
        env["HOMECOMING_MAPPING_REVIEW_OUT_DIR"] = str(temp_root)
        result = subprocess.run([sys.executable, str(script)], cwd=str(repo_root), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            errors.append(f"{GENERATOR} failed with exit {result.returncode}:\n{result.stdout}")
            return
        generated_seed = temp_root / SEED_PATH.name
        generated_html = temp_root / HTML_PATH.name
        shared_seed = repo_root / SEED_PATH
        shared_html = repo_root / HTML_PATH
        require(generated_seed.exists(), f"generator did not write temp seed artifact: {generated_seed}", errors)
        require(generated_html.exists(), f"generator did not write temp HTML artifact: {generated_html}", errors)
        if generated_seed.exists() and shared_seed.exists():
            require(generated_seed.read_text(encoding="utf-8") == shared_seed.read_text(encoding="utf-8"), "shared seed artifact is stale versus temp generation", errors)
        if generated_html.exists() and shared_html.exists():
            require(generated_html.read_text(encoding="utf-8") == shared_html.read_text(encoding="utf-8"), "shared HTML artifact is stale versus temp generation", errors)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_html(repo_root: Path, errors: list[str]) -> None:
    html_path = repo_root / HTML_PATH
    if not html_path.exists():
        errors.append(f"missing HTML artifact: {html_path}")
        return
    html = html_path.read_text(encoding="utf-8")
    require("Homecoming Building Mapping Review" in html, "HTML review menu title missing", errors)
    require(EXPECTED_CANON_EXPORT_SCHEMA in html, "HTML canon export schema missing", errors)
    require(EXPECTED_REVIEW_EXPORT_SCHEMA in html, "HTML review export schema missing", errors)
    require("Export Accepted Canon JSON" in html and "Export Full Review JSON" in html and "Copy Canon JSON" in html, "HTML export controls missing", errors)
    require("candidateOptions" in html and "list=\"candidateOptions\"" in html, "HTML must use one shared Olden candidate datalist", errors)
    require("selectedRows = mode === 'canon' ? rows.filter" in html, "canon export must filter rows instead of exporting all review rows", errors)
    require("r.status === 'accepted' && r.proposedReplacementSid" in html, "canon export must require accepted mapped rows", errors)
    require("refreshProposedFunction(row)" in html, "candidate changes must refresh proposed function text", errors)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    require(len(scripts) == 1, f"HTML must contain exactly one executable script block, found {len(scripts)}", errors)
    if len(scripts) != 1:
        return
    check_path = repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "mapping_review" / ".tmp_review_menu_script_check.js"
    check_path.write_text(scripts[0], encoding="utf-8")
    node_result = subprocess.run(["node", "--check", str(check_path)], cwd=str(repo_root), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        check_path.unlink()
    except OSError:
        pass
    require(node_result.returncode == 0, f"HTML review menu JavaScript does not parse:\n{node_result.stdout}", errors)


def load_alignment_source_entities(repo_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    alignment = read_json(repo_root / ALIGNMENT_PATH, errors)
    entities = alignment.get("alignment", {}).get("globalObjectProperties", {}).get("propEntities")
    require(isinstance(entities, list), "alignment artifact must contain alignment.globalObjectProperties.propEntities", errors)
    if not isinstance(entities, list):
        return {}
    return {entity["sourceKey"]: entity for entity in entities if isinstance(entity, dict) and isinstance(entity.get("sourceKey"), str)}


def expected_artifact_source(substitution: dict[str, Any], source_entities_by_key: dict[str, dict[str, Any]]) -> dict[str, str] | None:
    if substitution.get("category") != "artifact_pickup":
        return None
    template_id = substitution.get("templateObjectId")
    random_function = RANDOM_ARTIFACT_TEMPLATE_DESCRIPTIONS.get(template_id)
    if random_function is not None:
        return {"sourceName": "Random Artifact", "sourceFunction": random_function, "sourceFunctionConfidence": ARTIFACT_SOURCE_CONFIDENCE}
    subtype_values = {
        source_entities_by_key[key].get("templateSubtype")
        for key in substitution.get("sampleSourceKeys") or []
        if key in source_entities_by_key
    }
    subtype_values.discard(None)
    if len(subtype_values) != 1:
        return None
    subtype = next(iter(subtype_values))
    expected = ARTIFACT_SOURCE_FUNCTIONS_BY_SUBTYPE.get(subtype)
    if expected is None:
        return None
    animation = substitution.get("templateAnimation") or "unknown DEF"
    return {
        "sourceName": expected["sourceName"],
        "sourceFunction": f"{expected['sourceFunction']} Source map DEF: {animation}.",
        "sourceFunctionConfidence": ARTIFACT_SOURCE_CONFIDENCE,
    }


def validate_checkpoint(seed: dict[str, Any], rows: list[dict[str, Any]], checkpoint: dict[str, Any], errors: list[str]) -> None:
    require(checkpoint.get("schema") in {EXPECTED_REVIEW_EXPORT_SCHEMA, EXPECTED_CANON_EXPORT_SCHEMA}, f"checkpoint schema mismatch: {checkpoint.get('schema')}", errors)
    mappings = checkpoint.get("mappings")
    require(isinstance(mappings, list), "checkpoint must contain mappings list", errors)
    if not isinstance(mappings, list):
        return
    checkpoint_meta = seed.get("checkpoint")
    require(isinstance(checkpoint_meta, dict), "seed must record checkpoint metadata", errors)
    if isinstance(checkpoint_meta, dict):
        require(checkpoint_meta.get("path") == str(CHECKPOINT_PATH), f"seed checkpoint path mismatch: {checkpoint_meta.get('path')}", errors)
        require(checkpoint_meta.get("mergedRowCount") == len(mappings), f"seed checkpoint mergedRowCount mismatch: {checkpoint_meta.get('mergedRowCount')} != {len(mappings)}", errors)
    checkpoint_by_row_id = {row.get("rowId"): row for row in mappings if isinstance(row, dict) and isinstance(row.get("rowId"), str)}
    row_by_id = {row.get("rowId"): row for row in rows if isinstance(row, dict) and isinstance(row.get("rowId"), str)}
    require(set(checkpoint_by_row_id) == set(row_by_id), "checkpoint rowId coverage must exactly match generated review rows", errors)
    for row_id, checkpoint_row in checkpoint_by_row_id.items():
        row = row_by_id.get(row_id)
        if not isinstance(row, dict):
            continue
        require(row.get("checkpointMerged") is True, f"row {row_id} must record checkpointMerged=true", errors)
        accepted_without_replacement = checkpoint_row.get("reviewStatus") == "accepted" and checkpoint_row.get("oldenReplacementSid") is None
        artifact_effect_shape_seed = checkpoint_row.get("oldenReplacementSid") is None and row.get("currentConfidence") == "artifact_effect_shape" and row.get("currentReplacementSid") is not None
        if artifact_effect_shape_seed:
            require(row.get("status") == "needs_review", f"row {row_id} empty checkpoint artifact effect-shape row must be seeded for review", errors)
            require(row.get("proposedReplacementSid") == row.get("currentReplacementSid"), f"row {row_id} proposed replacement must seed from current artifact effect-shape mapper", errors)
            require(row.get("proposedOldenFunction") == row.get("currentReplacementDescription"), f"row {row_id} proposed function must seed from localized current artifact description", errors)
            require(row.get("checkpointNormalization") == "empty_checkpoint_to_artifact_effect_shape_proposal", f"row {row_id} must record artifact effect-shape checkpoint normalization", errors)
            require("seeded proposed mapping from current artifact effect-shape mapper" in str(row.get("reviewNotes", "")), f"row {row_id} artifact effect-shape normalization note missing", errors)
        elif accepted_without_replacement:
            require(row.get("status") == "blocked", f"row {row_id} accepted-without-replacement checkpoint must be normalized to blocked", errors)
            require(row.get("checkpointNormalization") == "accepted_without_replacement_to_blocked", f"row {row_id} must record accepted-without-replacement normalization", errors)
            require("accepted status with no Olden replacement" in str(row.get("reviewNotes", "")), f"row {row_id} normalization note missing", errors)
            require(row.get("proposedReplacementSid") == checkpoint_row.get("oldenReplacementSid"), f"row {row_id} replacement must merge from checkpoint", errors)
            require(row.get("proposedOldenFunction") == checkpoint_row.get("proposedOldenFunction"), f"row {row_id} proposedOldenFunction must merge from checkpoint", errors)
        else:
            require(row.get("status") == checkpoint_row.get("reviewStatus"), f"row {row_id} status must merge from checkpoint", errors)
            require(row.get("proposedReplacementSid") == checkpoint_row.get("oldenReplacementSid"), f"row {row_id} replacement must merge from checkpoint", errors)
            require(row.get("proposedOldenFunction") == checkpoint_row.get("proposedOldenFunction"), f"row {row_id} proposedOldenFunction must merge from checkpoint", errors)
            require(row.get("reviewNotes") == checkpoint_row.get("reviewNotes"), f"row {row_id} reviewNotes must merge from checkpoint", errors)


def assert_no_classifier_leak(row: dict[str, Any], label: str, errors: list[str]) -> None:
    values = [row.get("sourceName"), row.get("sourceFunction"), row.get("reviewNotes")]
    joined = " ".join(str(value).lower() for value in values if isinstance(value, str))
    leaked = [pattern for pattern in CLASSIFIER_LEAK_PATTERNS if pattern in joined]
    require(not leaked, f"{label} must not expose raw classifier text: {leaked}", errors)


def validate_homecoming_row(row: dict[str, Any], substitution: dict[str, Any], candidate_sids: set[Any], source_entities_by_key: dict[str, dict[str, Any]], errors: list[str]) -> None:
    signature = row.get("sourceSignature")
    require(row.get("rowKind") == "homecoming_substitution", f"Homecoming row {signature} must be rowKind=homecoming_substitution", errors)
    require(row.get("rowId") == signature, f"Homecoming row {signature} rowId must equal sourceSignature", errors)
    for field in ["sourceSignature", "sourceSid", "templateAnimation", "sourceName", "sourceFunction", "sourceFunctionConfidence", "currentRuleName", "currentConfidence", "status", "category", "payloadKind"]:
        require(isinstance(row.get(field), str) and row.get(field), f"Homecoming row {signature} missing {field}", errors)
    for field in ["templateObjectId", "count"]:
        require(isinstance(row.get(field), int), f"Homecoming row {signature} missing integer {field}", errors)
    for field in ["sourceSid", "templateObjectId", "templateAnimation", "category", "payloadKind", "count", "lossiness"]:
        require(row.get(field) == substitution.get(field), f"Homecoming row {signature} field {field} must match substitution artifact", errors)
    require(row.get("currentReplacementSid") == substitution.get("replacementSid"), f"Homecoming row {signature} currentReplacementSid must match substitution artifact", errors)
    require(row.get("currentRuleName") == (substitution.get("ruleName") or "blocked_no_rule"), f"Homecoming row {signature} currentRuleName must match substitution artifact", errors)
    require(row.get("currentConfidence") == (substitution.get("confidence") or "blocked"), f"Homecoming row {signature} currentConfidence must match substitution artifact", errors)
    replacement = row.get("proposedReplacementSid")
    if replacement is None:
        require(row.get("status") == "blocked", f"Homecoming row {signature} empty replacement must start blocked", errors)
    else:
        require(replacement in candidate_sids, f"Homecoming row {signature} replacement not in candidate catalog: {replacement}", errors)
        require(isinstance(row.get("proposedOldenFunction"), str), f"Homecoming row {signature} mapped target must carry proposedOldenFunction", errors)
    evidence = substitution.get("semanticEvidence") if isinstance(substitution.get("semanticEvidence"), dict) else None
    artifact_expected = expected_artifact_source(substitution, source_entities_by_key)
    assert_no_classifier_leak(row, f"Homecoming row {signature}", errors)
    if artifact_expected is not None:
        require(row.get("sourceName") == artifact_expected["sourceName"], f"Homecoming row {signature} artifact sourceName mismatch", errors)
        require(row.get("sourceFunction") == artifact_expected["sourceFunction"], f"Homecoming row {signature} artifact sourceFunction must show exact artifact effect", errors)
        require(row.get("sourceFunctionConfidence") == artifact_expected["sourceFunctionConfidence"], f"Homecoming row {signature} artifact sourceFunctionConfidence mismatch", errors)
        require("Exact stat/effect text still needs" not in row.get("sourceFunction", ""), f"Homecoming row {signature} must not contain stale artifact placeholder text", errors)
    elif evidence is not None and isinstance(evidence.get("sourceDescription"), str):
        require(row.get("sourceFunctionConfidence") == "semanticEvidence.sourceDescription", f"Homecoming row {signature} must source function from semanticEvidence", errors)
        require(row.get("sourceName") == evidence.get("sourceName"), f"Homecoming row {signature} sourceName must match semanticEvidence", errors)
        require(row.get("sourceFunction") == evidence.get("sourceDescription"), f"Homecoming row {signature} sourceFunction must match semanticEvidence", errors)
    elif row.get("templateObjectId") in SOURCE_FUNCTION_OVERRIDES:
        expected = SOURCE_FUNCTION_OVERRIDES[row.get("templateObjectId")]
        require(row.get("sourceName") == expected["sourceName"], f"Homecoming row {signature} sourceName must match manual source override", errors)
        require(row.get("sourceFunction") == expected["sourceFunction"], f"Homecoming row {signature} sourceFunction must match manual source override", errors)
        require(row.get("sourceFunctionConfidence") == expected["sourceFunctionConfidence"], f"Homecoming row {signature} sourceFunctionConfidence must match manual override", errors)
    elif row.get("sourceFunctionConfidence") == CATEGORY_SOURCE_CONFIDENCE:
        expected = CATEGORY_SOURCE_FUNCTIONS.get((row.get("category"), row.get("payloadKind")))
        require(isinstance(expected, dict), f"Homecoming row {signature} category seed must be declared for its category/payload", errors)
        if isinstance(expected, dict):
            expected_name = f"{expected['sourceName']} ({row.get('templateAnimation')})"
            require(row.get("sourceName") == expected_name, f"Homecoming row {signature} category-seeded sourceName mismatch", errors)
            require(row.get("sourceFunction") == expected["sourceFunction"], f"Homecoming row {signature} category-seeded sourceFunction mismatch", errors)
    else:
        require(row.get("sourceFunctionConfidence") == "needs_h3_primary_source_review", f"Homecoming row {signature} without source evidence must be marked for H3 source review", errors)
        require("Unclassified HoMM3 map object" in row.get("sourceFunction", ""), f"Homecoming row {signature} must carry unclassified source-review function text", errors)


def validate_catalog_row(row: dict[str, Any], candidate_sids: set[Any], observed_template_ids: set[Any], errors: list[str]) -> None:
    row_id = row.get("rowId")
    require(row.get("rowKind") == "homm3_catalog_extension", f"Catalog row {row_id} must be rowKind=homm3_catalog_extension", errors)
    require(row.get("sourceSignature") == row_id and str(row_id).startswith("homm3.catalog_extension|"), f"Catalog row {row_id} must use catalog-extension sourceSignature", errors)
    if row.get("templateObjectId") is not None:
        require(row.get("templateObjectId") not in observed_template_ids, f"Catalog row {row_id} duplicates a Homecoming-observed template", errors)
    require(row.get("payloadKind") == "catalog_only_not_in_homecoming", f"Catalog row {row_id} payloadKind must mark not-in-Homecoming status", errors)
    require(row.get("lossiness") == "preliminary_catalog_seed", f"Catalog row {row_id} must be marked preliminary", errors)
    require(row.get("count") == 0, f"Catalog row {row_id} must have count 0", errors)
    require(row.get("status") in {"needs_review", "blocked", "accepted"}, f"Catalog row {row_id} has invalid review status", errors)
    if row.get("status") == "accepted":
        require(row.get("checkpointMerged") is True, f"Catalog row {row_id} may be accepted only through imported review checkpoint", errors)
    require(row.get("sourceFunctionConfidence") in CATALOG_EXTENSION_CONFIDENCES, f"Catalog row {row_id} has invalid sourceFunctionConfidence", errors)
    replacement = row.get("proposedReplacementSid")
    if replacement is None:
        require(row.get("status") == "blocked", f"Catalog row {row_id} empty replacement must stay blocked", errors)
    else:
        require(replacement in candidate_sids, f"Catalog row {row_id} replacement not in candidate catalog: {replacement}", errors)
    require("not observed in Homecoming" in row.get("reviewNotes", ""), f"Catalog row {row_id} must explain Homecoming absence", errors)
    assert_no_classifier_leak(row, f"Catalog row {row_id}", errors)


def validate_seed(repo_root: Path, errors: list[str]) -> None:
    seed = read_json(repo_root / SEED_PATH, errors)
    substitution = read_json(repo_root / SUBSTITUTION_PATH, errors)
    core_catalog = read_json(repo_root / CORE_CATALOG_PATH, errors)
    checkpoint = read_json(repo_root / CHECKPOINT_PATH, errors)
    source_entities_by_key = load_alignment_source_entities(repo_root, errors)
    if not seed:
        return
    require(seed.get("schema") == EXPECTED_SCHEMA, f"seed schema mismatch: {seed.get('schema')}", errors)
    rows = seed.get("reviewRows")
    candidates = seed.get("oldenCandidates")
    require(isinstance(rows, list), "reviewRows must be a list", errors)
    require(isinstance(candidates, list) and len(candidates) > 100, "oldenCandidates must include the reviewable Olden catalog", errors)
    if not isinstance(rows, list) or not isinstance(candidates, list):
        return
    candidate_sids = {candidate.get("sid") for candidate in candidates if isinstance(candidate, dict)}
    valid_sids = {row.get("id") for row in core_catalog.get("mapObjects") or [] if isinstance(row, dict)}
    require(candidate_sids == valid_sids, "review candidate catalog must exactly match Olden valid map object whitelist", errors)
    raw_substitutions = substitution.get("invalidEntitySubstitutions")
    require(isinstance(raw_substitutions, list), "substitution artifact must contain invalidEntitySubstitutions list", errors)
    if not isinstance(raw_substitutions, list):
        return
    all_substitutions = [entry for entry in raw_substitutions if isinstance(entry, dict)]
    require(len(all_substitutions) == len(raw_substitutions), "all invalidEntitySubstitutions entries must be objects", errors)
    require(h3obj.RANDOM_ARTIFACT_OBJECT_IDS == set(RANDOM_ARTIFACT_TEMPLATE_DESCRIPTIONS), "random artifact review descriptions must cover registry ids exactly", errors)
    fixed_generator_artifact_rows = [
        entry for entry in all_substitutions
        if entry.get("templateObjectId") in h3obj.FIXED_CREATURE_GENERATOR_IDS and (entry.get("category") == "artifact_pickup" or entry.get("payloadKind") == "artifact")
    ]
    require(not fixed_generator_artifact_rows, f"mapping review seed must not accept fixed creature-generator artifact semantics: {len(fixed_generator_artifact_rows)} rows", errors)
    random_hero_artifact_rows = [
        entry for entry in all_substitutions
        if entry.get("templateObjectId") == h3obj.OBJECT_RANDOM_HERO and (entry.get("category") == "artifact_pickup" or entry.get("payloadKind") == "artifact")
    ]
    require(not random_hero_artifact_rows, f"mapping review seed must not accept random hero id 70 as artifact semantics: {len(random_hero_artifact_rows)} rows", errors)
    substitutions = [entry for entry in all_substitutions if is_reviewable_homecoming_substitution(entry)]
    excluded_substitutions = [entry for entry in all_substitutions if not is_reviewable_homecoming_substitution(entry)]
    substitution_by_signature = {entry.get("sourceSignature"): entry for entry in substitutions}
    homecoming_rows = [row for row in rows if isinstance(row, dict) and row.get("rowKind") == "homecoming_substitution"]
    catalog_rows = [row for row in rows if isinstance(row, dict) and row.get("rowKind") == "homm3_catalog_extension"]
    require(len(homecoming_rows) == len(substitutions), f"Homecoming row count {len(homecoming_rows)} must equal substitution count {len(substitutions)}", errors)
    require({row.get("sourceSignature") for row in homecoming_rows} == set(substitution_by_signature), "Homecoming row sourceSignature coverage must exactly match reviewable substitutions", errors)
    require(not any(row.get("category") in EXCLUDED_HOMECOMING_REVIEW_CATEGORIES and row.get("templateObjectId") not in FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS for row in homecoming_rows), "payloadless visual/decor rows must not appear in the text-only mapping review menu", errors)
    excluded_summary = seed.get("excludedHomecomingReviewRows")
    require(isinstance(excluded_summary, dict), "seed must record excluded Homecoming review rows", errors)
    if isinstance(excluded_summary, dict):
        require(excluded_summary.get("count") == len(excluded_substitutions), f"excluded Homecoming row count mismatch: {excluded_summary.get('count')} != {len(excluded_substitutions)}", errors)
        require(set(excluded_summary.get("categories") or []) == EXCLUDED_HOMECOMING_REVIEW_CATEGORIES, "excluded Homecoming row categories mismatch", errors)
        require("text-only" in str(excluded_summary.get("reason", "")), "excluded Homecoming row reason must document text-only review boundary", errors)
    excluded_functional_ids = {entry.get("templateObjectId") for entry in excluded_substitutions if entry.get("templateObjectId") in FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS}
    require(not excluded_functional_ids, f"functional payloadless template IDs must stay reviewable, not excluded: {sorted(excluded_functional_ids)}", errors)
    present_functional_payloadless_ids = {
        row.get("templateObjectId")
        for row in homecoming_rows
        if row.get("category") in EXCLUDED_HOMECOMING_REVIEW_CATEGORIES
    }
    observed_functional_payloadless_ids = {
        entry.get("templateObjectId")
        for entry in all_substitutions
        if entry.get("category") in EXCLUDED_HOMECOMING_REVIEW_CATEGORIES
        and entry.get("templateObjectId") in FUNCTIONAL_PAYLOADLESS_TEMPLATE_IDS
    }
    require(present_functional_payloadless_ids == observed_functional_payloadless_ids, f"functional payloadless review coverage mismatch: {sorted(present_functional_payloadless_ids)} != {sorted(observed_functional_payloadless_ids)}", errors)
    row_ids = [row.get("rowId") for row in rows if isinstance(row, dict)]
    require(len(row_ids) == len(set(row_ids)), "review rowIds must be unique", errors)
    observed_template_ids = {entry.get("templateObjectId") for entry in all_substitutions}
    observed_catalog_names = [row.get("sourceName") for row in catalog_rows]
    require(len(catalog_rows) == len(EXPECTED_CATALOG_EXTENSION_NAMES), f"catalog extension row count mismatch: {len(catalog_rows)} != {len(EXPECTED_CATALOG_EXTENSION_NAMES)}", errors)
    require(set(observed_catalog_names) == EXPECTED_CATALOG_EXTENSION_NAMES, f"catalog extension inventory mismatch: {sorted(observed_catalog_names)}", errors)
    require(len(observed_catalog_names) == len(set(observed_catalog_names)), "catalog extension source names must be unique", errors)
    validate_checkpoint(seed, rows, checkpoint, errors)
    for row in homecoming_rows:
        validate_homecoming_row(row, substitution_by_signature.get(row.get("sourceSignature"), {}), candidate_sids, source_entities_by_key, errors)
    for row in catalog_rows:
        validate_catalog_row(row, candidate_sids, observed_template_ids, errors)
    for row in rows:
        if not isinstance(row, dict):
            errors.append(f"review row must be object: {row}")
            continue
        if row.get("rowKind") not in {"homecoming_substitution", "homm3_catalog_extension"}:
            errors.append(f"review row has unknown rowKind: {row.get('rowKind')}")
    candidate_by_sid = {candidate.get("sid"): candidate for candidate in candidates if isinstance(candidate, dict)}
    for row in rows:
        if not isinstance(row, dict) or row.get("proposedReplacementSid") is None:
            continue
        target = candidate_by_sid.get(row.get("proposedReplacementSid"))
        if isinstance(target, dict):
            require(row.get("proposedOldenFunction") == (target.get("description") or ""), f"row {row.get('rowId')} proposed function must start from selected target description", errors)
    for row in homecoming_rows:
        if row.get("currentConfidence") == "artifact_effect_shape" and row.get("currentReplacementSid") is not None:
            require(isinstance(row.get("currentReplacementName"), str) and row.get("currentReplacementName") and row.get("currentReplacementName") != row.get("currentReplacementSid"), f"artifact effect-shape row {row.get('rowId')} must carry localized Olden artifact name", errors)
            require(isinstance(row.get("currentReplacementDescription"), str) and row.get("currentReplacementDescription"), f"artifact effect-shape row {row.get('rowId')} must carry localized Olden artifact description", errors)
            require(row.get("proposedReplacementSid") == row.get("currentReplacementSid"), f"artifact effect-shape row {row.get('rowId')} must surface current mapper target as proposed target", errors)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            errors.append(f"candidate must be object: {candidate}")
            continue
        require(isinstance(candidate.get("sid"), str) and candidate.get("sid"), "candidate missing sid", errors)
        require(isinstance(candidate.get("name"), str) and candidate.get("name"), f"candidate missing name: {candidate}", errors)
        profile = candidate.get("logicProfile")
        require(isinstance(profile, dict), f"candidate missing logicProfile: {candidate.get('sid')}", errors)
        if isinstance(profile, dict):
            sid = candidate.get("sid")
            if sid == "fort":
                require(profile.get("statParameters") == ["defence", "offence"], "fort logic profile must be SID-filtered to Attack/Defense stats", errors)
            if sid == "stinging_sword":
                require(profile.get("statParameters") == ["offence"], "stinging_sword logic profile must be SID-filtered to Attack only", errors)
            if sid == "quixs_path":
                require(profile.get("buffParameters") == ["quixs_path_buff"], "quixs_path logic profile must be SID-filtered to its morale buff", errors)


def validate(repo_root: Path, errors: list[str]) -> None:
    validate_html(repo_root, errors)
    validate_seed(repo_root, errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    if not args.skip_generate:
        run_generation(repo_root, errors)
    validate(repo_root, errors)
    if errors:
        print("Homecoming mapping review menu contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming mapping review menu contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
