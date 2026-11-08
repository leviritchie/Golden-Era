#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "spell_school_sid_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_TAXONOMY_PATH = ROOT / "custom_factions" / "spell_taxonomy_contracts.json"


def load_spell_school_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresSpellSchoolOrSidClass" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(
    doc: Any,
    profiles: dict[str, dict[str, Any]],
    taxonomy: Any,
    validation: Validation,
) -> None:
    if not isinstance(doc, dict):
        validation.error("spell school/SID predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"spell school/SID predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresSpellSchoolOrSidClassProfiles",
            "genericSchoolMatchForbidden",
            "sidSubstringInferenceForbidden",
            "classificationMustUseSpellTaxonomyContracts",
            "companionPredicateGapsRemainExplicit",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    taxonomy_groups = set()
    allowed_tags = set()
    if isinstance(taxonomy, dict):
        groups = taxonomy.get("predicateGroups")
        if isinstance(groups, dict):
            taxonomy_groups = {str(key) for key in groups}
        tags = taxonomy.get("allowedTags")
        if isinstance(tags, list):
            allowed_tags = {tag for tag in tags if isinstance(tag, str)}
    if not taxonomy_groups:
        validation.error("spell taxonomy predicateGroups must be available for contract validation")
    if not allowed_tags:
        validation.error("spell taxonomy allowedTags must be available for contract validation")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "spell pool identity proof",
        "spell cooldown read/mutation ordering proof",
        "cast-gate and UI synchronization proof",
        "caster law-owner correlation proof when classification is used in runtime",
    }
    if not isinstance(required_runtime, list) or not required_runtime:
        validation.error("requiredRuntimeProof must be a non-empty list")
    else:
        actual_items = {item for item in required_runtime if isinstance(item, str)}
        for missing in sorted(required_items - actual_items):
            validation.error(f"requiredRuntimeProof missing {missing!r}")
        for item in required_runtime:
            if not isinstance(item, str) or not item:
                validation.error(f"requiredRuntimeProof entries must be non-empty strings, got {item!r}")

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return

    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing spell school/SID predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: spell school/SID predicate contract has no exact RequiresSpellSchoolOrSidClass profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        groups = contract.get("classificationGroups")
        if not isinstance(groups, list):
            validation.error(f"{effect_key}: classificationGroups must be a list")
            groups = []
        for group in groups:
            if not isinstance(group, str) or not group:
                validation.error(f"{effect_key}: classificationGroups entries must be non-empty strings")
            elif group not in taxonomy_groups:
                validation.error(f"{effect_key}: unknown spell taxonomy predicate group {group!r}")
        required_tags = contract.get("requiredTags")
        if not isinstance(required_tags, list) or not required_tags:
            validation.error(f"{effect_key}: requiredTags must be a non-empty list")
            required_tags = []
        for tag in required_tags:
            if not isinstance(tag, str) or not tag:
                validation.error(f"{effect_key}: requiredTags entries must be non-empty strings")
            elif tag not in allowed_tags:
                validation.error(f"{effect_key}: requiredTag {tag!r} is not in spell taxonomy allowedTags")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
        else:
            profile = profiles.get(effect_key)
            profile_preds = set(profile.get("requiredPredicates", [])) if isinstance(profile, dict) else set()
            for predicate in companion:
                if not isinstance(predicate, str) or not predicate:
                    validation.error(f"{effect_key}: companionPredicates entries must be non-empty strings")
                elif predicate not in profile_preds:
                    validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on the profile row")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if "substring" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject spell SID substring inference")
        if "cooldown preview" not in forbidden_text and "spellbook open" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject preview/UI-only classification substitutes")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "must use" not in notes.lower() and "can use" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the exact classification boundary")

        tag_text = "\n".join(str(tag).lower() for tag in required_tags if isinstance(tag, str))
        if effect_key.startswith("castle.") and "daylight" not in tag_text:
            validation.error(f"{effect_key}: Castle classification must include daylight")
        if effect_key.startswith("cove.") and not ({"movement", "storm", "sea"} <= set(required_tags)):
            validation.error(f"{effect_key}: Cove classification must include movement, storm, and sea")
        if effect_key.startswith("dungeon.") and not ({"night", "curse"} <= set(required_tags)):
            validation.error(f"{effect_key}: Dungeon classification must include night and curse")
        if effect_key.startswith("inferno.") and "fire" not in tag_text:
            validation.error(f"{effect_key}: Inferno classification must include fire")
        if effect_key.startswith("necropolis.") and not ({"night", "death"} <= set(required_tags)):
            validation.error(f"{effect_key}: Necropolis classification must include night and death")
        if effect_key.startswith("rampart.") and "protection" not in tag_text:
            validation.error(f"{effect_key}: Rampart classification must include protection")
        if effect_key.startswith("tower.") and not companion:
            validation.error(f"{effect_key}: Tower classification must keep overclock/cast-gate companion predicates explicit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_spell_school_profiles(args.inventory)
    taxonomy = load_json(args.taxonomy)
    validate_contracts(doc, profiles, taxonomy, validation)
    print(f"spell school/SID predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresSpellSchoolOrSidClass effect keys: {len(profiles)} unique key(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
