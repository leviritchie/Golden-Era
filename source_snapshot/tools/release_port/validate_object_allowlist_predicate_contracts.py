#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "object_allowlist_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_object_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresObjectSidOrCategoryAllowlist" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("object allowlist predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"object allowlist predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresObjectSidOrCategoryAllowlistProfiles",
            "genericObjectCategoryInferenceForbidden",
            "localizedTextParsingForbidden",
            "visualArtInferenceForbidden",
            "nonexistentMechanicsMustRemainForbidden",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "adventure object runtime identity proof",
        "object owner/side correlation proof where owned structure is used",
        "fog reveal mutation proof",
        "map refresh proof",
        "vision idempotence proof",
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
        validation.error(f"{missing}: missing object allowlist predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: object allowlist predicate contract has no exact RequiresObjectSidOrCategoryAllowlist profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        object_kinds = contract.get("objectKinds")
        if not isinstance(object_kinds, list) or not object_kinds:
            validation.error(f"{effect_key}: objectKinds must be a non-empty list")
            object_kinds = []
        for item in object_kinds:
            if not isinstance(item, str) or not item:
                validation.error(f"{effect_key}: objectKinds entries must be non-empty strings")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        profile = profiles.get(effect_key)
        profile_preds = set(profile.get("requiredPredicates", [])) if isinstance(profile, dict) else set()
        for predicate in companion:
            if not isinstance(predicate, str) or not predicate:
                validation.error(f"{effect_key}: companionPredicates entries must be non-empty strings")
            elif predicate not in profile_preds:
                validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on the profile row")
        if "RequiresFogRevealMutation" not in companion:
            validation.error(f"{effect_key}: object allowlist vision contract must keep RequiresFogRevealMutation explicit")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if "icon" not in forbidden_text and "art" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject icon/art inference")
        if "localized" not in forbidden_text and "display text" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject localized/display text parsing")
        if "any " not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic object substitution")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "must use" not in notes.lower():
            validation.error(f"{effect_key}: notes must state exact object allowlist boundary")

        kinds_text = "\n".join(str(item).lower() for item in object_kinds if isinstance(item, str))
        if effect_key.startswith("conflux.") and "elemental" not in kinds_text:
            validation.error(f"{effect_key}: Conflux object contract must include elemental object context")
        if effect_key.startswith("cove.") and not ({"treasure-cache", "creature-bank"} <= set(object_kinds)):
            validation.error(f"{effect_key}: Cove object contract must include treasure-cache and creature-bank")
        if effect_key.startswith("inferno.") and "teleport" not in forbidden_text:
            validation.error(f"{effect_key}: Inferno object contract must forbid fabricated teleport mechanics")
        if effect_key.startswith("necropolis.") and "corpse" not in kinds_text:
            validation.error(f"{effect_key}: Necropolis object contract must include corpse object context")
        if effect_key.startswith("stronghold.") and "localized threat text parsing" not in forbidden_text:
            validation.error(f"{effect_key}: Stronghold object contract must forbid localized threat text parsing")
        if effect_key.startswith("tower.") and "artifact" not in kinds_text:
            validation.error(f"{effect_key}: Tower object contract must include artifact context")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_object_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"object allowlist predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresObjectSidOrCategoryAllowlist effect keys: {len(profiles)} unique key(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
