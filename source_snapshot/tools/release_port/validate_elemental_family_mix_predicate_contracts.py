#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "elemental_family_mix_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_UNIT_FAMILY_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"


def load_elemental_mix_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresElementalFamilyMix" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            keys.add(effect_key)
    return keys


def count_authored_elemental_units(unit_tags_path: Path) -> int:
    tags = load_json(unit_tags_path)
    units = tags.get("units") if isinstance(tags, dict) else None
    if not isinstance(units, dict):
        return 0
    count = 0
    for sid, facts in units.items():
        if isinstance(sid, str) and isinstance(facts, dict) and facts.get("elemental") == "yes":
            count += 1
    return count


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], elemental_unit_count: int, validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("elemental family mix predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"elemental family mix predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresElementalFamilyMixProfiles",
            "confluxOnly",
            "elementalFamilyFactMustComeFromUnitFamilyTags",
            "mixedFamilyMeansAtLeastTwoDistinctElementalFamilies",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    static_evidence = doc.get("requiredStaticEvidence")
    if not isinstance(static_evidence, dict):
        validation.error("requiredStaticEvidence must be an object")
    else:
        if static_evidence.get("unitFamilyTagsPath") != "custom_factions/unit_family_tags.json":
            validation.error("requiredStaticEvidence.unitFamilyTagsPath must point to custom_factions/unit_family_tags.json")
        if static_evidence.get("requiredFact") != "elemental=yes":
            validation.error("requiredStaticEvidence.requiredFact must be elemental=yes")
        minimum = static_evidence.get("minimumElementalUnitSids")
        if not isinstance(minimum, int) or minimum < 2:
            validation.error("requiredStaticEvidence.minimumElementalUnitSids must be an integer >= 2")
        elif elemental_unit_count < minimum:
            validation.error(f"unit_family_tags has {elemental_unit_count} elemental=yes unit SID(s), below required minimum {minimum}")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "live hero party composition proof",
        "battle stack unit identity proof",
        "distinct elemental family discriminator proof",
        "temporary summon exclusion proof",
        "law owner to party or battle side correlation proof",
        "composition snapshot timing proof",
        "idempotent reward or trigger application proof",
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
        validation.error(f"{missing}: missing elemental family mix predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: elemental family mix contract has no exact RequiresElementalFamilyMix profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresElementalFamilyMix profile has invalid effectKey {effect_key!r}")
            continue
        if not effect_key.startswith("conflux."):
            validation.error(f"{effect_key}: RequiresElementalFamilyMix must remain Conflux-only")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        mix_kinds = contract.get("mixKinds")
        if not isinstance(mix_kinds, list) or not mix_kinds:
            validation.error(f"{effect_key}: mixKinds must be a non-empty list")
            mix_kinds = []
        mix_text = "\n".join(str(item).lower() for item in mix_kinds if isinstance(item, str))
        if "at-least-two-distinct-elemental-families" not in mix_text:
            validation.error(f"{effect_key}: mixKinds must require at least two distinct elemental families")
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
            "any elemental unit count",
            "same elemental family duplicates counted as a mix",
            "conflux faction membership counted as elemental family mix",
            "sid substring elemental inference",
            "display-name elemental inference",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "two distinct authored elemental families" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the distinct authored elemental family boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--unit-family-tags", type=Path, default=DEFAULT_UNIT_FAMILY_TAGS_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_elemental_mix_profiles(args.inventory)
    elemental_unit_count = count_authored_elemental_units(args.unit_family_tags)
    validate_contracts(doc, profiles, elemental_unit_count, validation)
    print(f"elemental family mix predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresElementalFamilyMix effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresElementalFamilyMix profile rows: {len(profiles)}")
    print(f"authored elemental=yes unit SIDs: {elemental_unit_count}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())