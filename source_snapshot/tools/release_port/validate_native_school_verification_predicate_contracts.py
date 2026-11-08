#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "native_school_verification_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_native_school_profiles(inventory_path: Path) -> dict[str, list[dict[str, Any]]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresNativeSchoolVerification" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles.setdefault(effect_key, []).append(row)
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, list[dict[str, Any]]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("native school verification contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"native school verification contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresNativeSchoolVerificationProfiles",
            "nativeSchoolNameMustMatchProfileRows",
            "lowAndHighRowsMustShareExactEffectKeySemantics",
            "staticSchoolAccessMustNotBecomeRuntimeGameplayTruth",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "spellbook access mutation surface proof",
        "spellbook UI synchronization proof",
        "cast-gate ordering proof",
        "hero spellbook/source school collection proof",
        "caster law-owner correlation proof when runtime add-ons are used",
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
        validation.error(f"{missing}: missing native school verification predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: native school verification contract has no exact RequiresNativeSchoolVerification profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        rows = profiles.get(effect_key, [])
        expected_school = contract.get("expectedNativeSchoolName")
        if not isinstance(expected_school, str) or not expected_school:
            validation.error(f"{effect_key}: expectedNativeSchoolName must be a non-empty string")
        required_handlers = contract.get("requiredHandlers")
        if not isinstance(required_handlers, list) or not required_handlers:
            validation.error(f"{effect_key}: requiredHandlers must be a non-empty list")
            required_handlers = []
        required_handler_set = {handler for handler in required_handlers if isinstance(handler, str)}
        row_handlers = {row.get("handler") for row in rows}
        if row_handlers != required_handler_set:
            validation.error(f"{effect_key}: handlers must match contract {sorted(required_handler_set)}, got {sorted(str(h) for h in row_handlers)}")
        for row in rows:
            values = row.get("values") if isinstance(row.get("values"), dict) else {}
            if values.get("NativeSchoolName") != expected_school:
                validation.error(
                    f"{effect_key}: row NativeSchoolName {values.get('NativeSchoolName')!r} does not match {expected_school!r}"
                )
            if not isinstance(values.get("NativeAccessShape"), dict):
                validation.error(f"{effect_key}: row must carry NativeAccessShape metadata")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        profile_preds: set[str] = set()
        for row in rows:
            if isinstance(row.get("requiredPredicates"), list):
                profile_preds.update(row.get("requiredPredicates"))
        for predicate in companion:
            if not isinstance(predicate, str) or not predicate:
                validation.error(f"{effect_key}: companionPredicates entries must be non-empty strings")
            elif predicate not in profile_preds:
                validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on the profile rows")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if "ui preview" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject UI-preview substitution")
        if effect_key.startswith("tower.") and "hardcoded" not in forbidden_text:
            validation.error(f"{effect_key}: Tower contract must forbid hardcoded school selection")
        if effect_key.startswith("inferno.") and "gating" not in forbidden_text:
            validation.error(f"{effect_key}: Inferno contract must forbid using native school as gating proof")
        if effect_key.startswith("cove.") and "focus" not in "\n".join(str(item).lower() for item in companion):
            validation.error(f"{effect_key}: Cove contract must keep Focus companion predicate explicit")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "must" not in notes.lower() or "remain" not in notes.lower():
            validation.error(f"{effect_key}: notes must state static verification and remaining runtime boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_native_school_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"native school verification predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresNativeSchoolVerification effect keys: {len(profiles)} unique key(s)")
    print(f"RequiresNativeSchoolVerification profile rows: {sum(len(rows) for rows in profiles.values())}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
