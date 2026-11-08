#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "negative_status_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_TAXONOMY_PATH = ROOT / "custom_factions" / "status_taxonomy_contracts.json"


def load_negative_status_profiles(inventory_path: Path) -> dict[str, list[dict[str, Any]]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresNegativeStatusPredicate" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles.setdefault(effect_key, []).append(row)
    return profiles


def validate_contracts(
    doc: Any,
    profiles: dict[str, list[dict[str, Any]]],
    taxonomy: Any,
    validation: Validation,
) -> None:
    if not isinstance(doc, dict):
        validation.error("negative status predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"negative status predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresNegativeStatusPredicateProfiles",
            "mustReferenceStatusTaxonomyContracts",
            "genericAnyDebuffForbidden",
            "sidSubstringInferenceForbidden",
            "meleeAndRangedFormationRowsMustShareExactEffectKeySemantics",
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
        validation.error("status taxonomy predicateGroups must be available for contract validation")
    if not allowed_tags:
        validation.error("status taxonomy allowedTags must be available for contract validation")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "live receiver status query proof",
        "live attacker/dealer status query proof when used",
        "status owner/source correlation proof",
        "status timing/duration proof",
        "formation action payload correlation proof",
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
        validation.error(f"{missing}: missing negative status predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: negative status predicate contract has no exact RequiresNegativeStatusPredicate profile")

    for effect_key, rows in sorted(profiles.items()):
        handlers = {row.get("handler") for row in rows}
        if handlers != {"battle.melee-formation", "battle.ranged-formation"}:
            validation.error(
                f"{effect_key}: negative status profile rows must cover exactly melee and ranged formation handlers, "
                f"got {sorted(str(h) for h in handlers)}"
            )

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        groups = contract.get("statusGroups")
        if not isinstance(groups, list) or not groups:
            validation.error(f"{effect_key}: statusGroups must be a non-empty list")
            groups = []
        for group in groups:
            if not isinstance(group, str) or not group:
                validation.error(f"{effect_key}: statusGroups entries must be non-empty strings")
            elif group not in taxonomy_groups:
                validation.error(f"{effect_key}: unknown status taxonomy predicate group {group!r}")
        required_tags = contract.get("requiredTags")
        if not isinstance(required_tags, list) or not required_tags:
            validation.error(f"{effect_key}: requiredTags must be a non-empty list")
            required_tags = []
        for tag in required_tags:
            if not isinstance(tag, str) or not tag:
                validation.error(f"{effect_key}: requiredTags entries must be non-empty strings")
            elif tag not in allowed_tags:
                validation.error(f"{effect_key}: requiredTag {tag!r} is not in status taxonomy allowedTags")
        if "negative" not in required_tags:
            validation.error(f"{effect_key}: requiredTags must include negative")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        profile_preds = set()
        rows = profiles.get(effect_key, [])
        for row in rows:
            if isinstance(row.get("requiredPredicates"), list):
                profile_preds.update(row.get("requiredPredicates"))
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
        if "any debuff" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic any-debuff substitution")
        if "substring" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject SID substring inference")
        if "icon" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject icon inference")
        if "localized" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject localized text parsing")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "must use exact" not in notes.lower():
            validation.error(f"{effect_key}: notes must state exact taxonomy boundary")

        tag_set = {tag for tag in required_tags if isinstance(tag, str)}
        if effect_key.startswith("dungeon.") and not ({"disable", "curse"} <= tag_set):
            validation.error(f"{effect_key}: Dungeon status contract must include disable and curse")
        if effect_key.startswith("fortress.") and not ({"poison", "slow"} <= tag_set):
            validation.error(f"{effect_key}: Fortress status contract must include poison and slow")
        if effect_key.startswith("necropolis.") and not ({"decay", "anti_heal"} <= tag_set):
            validation.error(f"{effect_key}: Necropolis status contract must include decay and anti_heal")
        if effect_key.startswith("stronghold.") and not ({"defense_down", "damage_taken_up"} <= tag_set):
            validation.error(f"{effect_key}: Stronghold status contract must include defense_down and damage_taken_up")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_negative_status_profiles(args.inventory)
    taxonomy = load_json(args.taxonomy)
    validate_contracts(doc, profiles, taxonomy, validation)
    print(f"negative status predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresNegativeStatusPredicate effect keys: {len(profiles)} unique key(s)")
    print(f"RequiresNegativeStatusPredicate profile rows: {sum(len(rows) for rows in profiles.values())}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
