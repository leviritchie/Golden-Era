#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "building_allowlist_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_BUILDING_CATEGORIES_PATH = ROOT / "custom_factions" / "construction_building_category_contracts.json"


def load_building_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresBuildingAllowlist" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(
    doc: Any,
    profiles: dict[str, dict[str, Any]],
    category_doc: Any,
    validation: Validation,
) -> None:
    if not isinstance(doc, dict):
        validation.error("building allowlist predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"building allowlist predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresBuildingAllowlistProfiles",
            "mustReferenceConstructionBuildingCategoryContracts",
            "missingGroupsMustRemainExplicit",
            "genericTownBuildingInferenceForbidden",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "construction commit ordering proof",
        "displayed and charged cost parity proof",
        "city owner to law-owner correlation proof",
        "building data SID/group lookup proof",
        "construction idempotence proof",
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

    category_contracts = category_doc.get("contracts") if isinstance(category_doc, dict) else None
    if not isinstance(category_contracts, dict):
        validation.error("construction building category contracts must be available")
        category_contracts = {}

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return

    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing building allowlist predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: building allowlist predicate contract has no exact RequiresBuildingAllowlist profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        profile = profiles.get(effect_key)
        faction_sid = contract.get("factionSid")
        if not isinstance(faction_sid, str) or not faction_sid:
            validation.error(f"{effect_key}: factionSid must be a non-empty string")
            continue
        if isinstance(profile, dict) and profile.get("factionSid") != faction_sid:
            validation.error(f"{effect_key}: contract factionSid {faction_sid!r} does not match profile {profile.get('factionSid')!r}")
        faction_categories = category_contracts.get(faction_sid)
        if not isinstance(faction_categories, dict):
            validation.error(f"{effect_key}: no construction building category contract for {faction_sid}")
            continue
        available_groups = faction_categories.get("groups") if isinstance(faction_categories.get("groups"), dict) else {}
        missing_groups = faction_categories.get("missingGroups") if isinstance(faction_categories.get("missingGroups"), dict) else {}
        required_groups = contract.get("requiredGroups")
        if not isinstance(required_groups, list) or not required_groups:
            validation.error(f"{effect_key}: requiredGroups must be a non-empty list")
            required_groups = []
        explicit_missing = contract.get("explicitMissingGroups", [])
        if not isinstance(explicit_missing, list):
            validation.error(f"{effect_key}: explicitMissingGroups must be a list when present")
            explicit_missing = []
        explicit_missing_set = {item for item in explicit_missing if isinstance(item, str)}
        for group in required_groups:
            if not isinstance(group, str) or not group:
                validation.error(f"{effect_key}: requiredGroups entries must be non-empty strings")
                continue
            if group in missing_groups:
                if group not in explicit_missing_set:
                    validation.error(f"{effect_key}: missing group {group!r} must be listed in explicitMissingGroups")
            elif group not in available_groups:
                validation.error(f"{effect_key}: required group {group!r} is absent from construction category contract")
            else:
                rows = available_groups.get(group)
                if not isinstance(rows, list) or not rows:
                    validation.error(f"{effect_key}: required group {group!r} has no concrete row mappings and is not explicit missing")
        for group in explicit_missing_set:
            if group not in missing_groups:
                validation.error(f"{effect_key}: explicit missing group {group!r} is not missing in construction category contract")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
        else:
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
        if "any " not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic any-building substitution")
        if "icon" not in forbidden_text and "scene-object" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject visual/icon/scene inference")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "must use exact" not in notes.lower() and "remains blocked" not in notes.lower():
            validation.error(f"{effect_key}: notes must state exact-row or blocked boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--building-categories", type=Path, default=DEFAULT_BUILDING_CATEGORIES_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_building_profiles(args.inventory)
    category_doc = load_json(args.building_categories)
    validate_contracts(doc, profiles, category_doc, validation)
    print(f"building allowlist predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresBuildingAllowlist effect keys: {len(profiles)} unique key(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
