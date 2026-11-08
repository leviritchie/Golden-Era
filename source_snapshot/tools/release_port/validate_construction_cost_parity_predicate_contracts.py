#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "construction_cost_parity_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_cost_parity_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresDisplayedAndChargedCostParity" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("construction cost parity predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"construction cost parity predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresDisplayedAndChargedCostParityProfiles",
            "uiOnlyCostChangeForbidden",
            "displayedAndChargedCostMustShareFormula",
            "extraBuildSlotMustBeSeparatedFromDiscount",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "displayed cost hook proof",
        "charged cost mutation proof",
        "build commit ordering proof",
        "resource affordability check parity proof",
        "refund or surcharge idempotence proof",
        "city owner to law-owner correlation proof",
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
        validation.error(f"{missing}: missing construction cost parity predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: construction cost parity contract has no exact RequiresDisplayedAndChargedCostParity profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        cost_kinds = contract.get("costKinds")
        if not isinstance(cost_kinds, list) or not cost_kinds:
            validation.error(f"{effect_key}: costKinds must be a non-empty list")
            cost_kinds = []
        for item in cost_kinds:
            if not isinstance(item, str) or not item:
                validation.error(f"{effect_key}: costKinds entries must be non-empty strings")
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
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if "ui-only" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject UI-only cost changes")
        if "charged-only" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject charged-only cost changes")
        if effect_key != "inferno-garrison-sacrifice-extra-build" and "extra build slot counted as cost discount" not in forbidden_text and "normal construction slot counted as workshop slot" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must separate extra/workshop slot behavior from cost changes")
        if effect_key.startswith("inferno-") and "deterministic value proof" not in forbidden_text:
            validation.error(f"{effect_key}: Inferno cost parity must require deterministic sacrifice value proof")
        if effect_key.startswith("tower-") and "workshop slot" not in forbidden_text:
            validation.error(f"{effect_key}: Tower cost parity must forbid normal/workshop slot conflation")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "match" not in notes.lower():
            validation.error(f"{effect_key}: notes must state matching displayed/charged cost boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_cost_parity_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"construction cost parity predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresDisplayedAndChargedCostParity effect keys: {len(profiles)} unique key(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
