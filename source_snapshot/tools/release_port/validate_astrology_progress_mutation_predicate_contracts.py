#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "astrology_progress_mutation_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresAstrologyProgressMutation" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            result.add(effect_key)
    return result


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("Astrology progress mutation predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"Astrology progress mutation predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresAstrologyProgressMutationProfiles",
            "calendarFamilyOnly",
            "astrologyProgressMustNotBeSubstitutedByGenericReward",
            "companionEventsDoNotProveProgressMutation",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    prefixes = doc.get("allowedEffectKeyPrefixes")
    expected_prefixes = ["castle.", "necropolis.", "stronghold."]
    if not isinstance(prefixes, list) or sorted(prefixes) != sorted(expected_prefixes):
        validation.error(f"allowedEffectKeyPrefixes must be exactly {expected_prefixes!r}")
        prefixes = []

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "native Astrology progress state read proof",
        "native Astrology progress mutation proof",
        "day or battle timing gate proof",
        "companion event correlation proof",
        "duplicate same-day or same-event prevention proof",
        "law owner to progress recipient correlation proof",
        "UI progress synchronization proof",
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
    expected_keys = profile_effect_keys(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing Astrology progress mutation predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: Astrology progress mutation contract has no exact RequiresAstrologyProgressMutation profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresAstrologyProgressMutation profile has invalid effectKey {effect_key!r}")
        elif not any(effect_key.startswith(prefix) for prefix in prefixes):
            validation.error(f"{effect_key}: RequiresAstrologyProgressMutation is outside expected faction scope")
        if row.get("family") != "Calendar":
            validation.error(f"{effect_key}: RequiresAstrologyProgressMutation must remain in Calendar family")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        astrology_kinds = contract.get("astrologyKinds")
        if not isinstance(astrology_kinds, list) or not astrology_kinds:
            validation.error(f"{effect_key}: astrologyKinds must be a non-empty list")
            astrology_kinds = []
        kind_text = "\n".join(str(item).lower() for item in astrology_kinds if isinstance(item, str))
        if "calendar-astrology-progress" not in kind_text:
            validation.error(f"{effect_key}: astrologyKinds must include calendar-astrology-progress")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        matching_profiles = [row for row in profiles if row.get("effectKey") == effect_key]
        profile_preds = set()
        for row in matching_profiles:
            predicates = row.get("requiredPredicates")
            if isinstance(predicates, list):
                profile_preds.update(predicates)
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
        required_forbidden = (
            "daily resource reward counted as astrology progress",
            "calendar text counted as astrology progress",
            "law row presence counted as astrology progress mutation",
            "ui progress preview counted as astrology progress mutation",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        if effect_key.startswith("castle.") and "spell cast counted as astrology progress mutation" not in forbidden_text:
            validation.error(f"{effect_key}: Castle astrology contract must reject spell-cast substitute")
        if effect_key.startswith("necropolis.") and "corpse count counted as astrology progress mutation" not in forbidden_text:
            validation.error(f"{effect_key}: Necropolis astrology contract must reject corpse-count substitute")
        if effect_key.startswith("stronghold.") and "warcry execution counted as astrology progress mutation" not in forbidden_text:
            validation.error(f"{effect_key}: Stronghold astrology contract must reject Warcry substitute")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "native astrology progress mutation" not in notes.lower():
            validation.error(f"{effect_key}: notes must state native Astrology progress mutation boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"Astrology progress mutation predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresAstrologyProgressMutation effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresAstrologyProgressMutation profile rows: {len(profiles)}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())